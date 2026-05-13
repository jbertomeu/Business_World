"""
M&A agent — merger and acquisition mechanics.

Supports hostile and friendly acquisitions. The flow:
1. Bidder firm decides whether to bid (LLM call on bidder's model)
2. Target board evaluates bid (LLM call on target's model)
3. If accepted (or hostile override at >150% of equity price): consolidate

Consolidation:
- Goodwill = purchase price - target's book value of net assets
- Acquirer absorbs target's capacity, R&D cumulative, brand stock
- Integration cost = 10% of target revenue, spread over 4 quarters
- Target firm deactivated

Runs as Phase 3 (after IPO, before firm decisions) when ma_enabled.
"""

from __future__ import annotations

from dataclasses import replace

from .types import FirmState, MacroState, MABid
from .llm_backends import LLMBackend, extract_json


# Hostile override threshold: if bid > this multiple of equity price,
# shareholders override board rejection.
HOSTILE_OVERRIDE_MULTIPLE = 1.5

# Wave ν+9 Bug L3: post-acquisition operational-stock absorption rates.
# These were previously bare magic numbers inline in process_acquisition;
# naming them documents intent and makes them tunable without grepping
# through code. Capability and brand are 0-100 scales (clamped post-merge);
# R&D cumulative is a dollar stock (uncapped). The values are the
# pre-existing behaviour preserved verbatim, not a recalibration.
MA_CAPABILITY_ABSORPTION = 0.4   # acquirer gains 40% of target capability
MA_BRAND_ABSORPTION = 0.3        # acquirer gains 30% of target brand stock
MA_RD_ABSORPTION = 0.5           # acquirer gains 50% of target R&D cumulative


def build_raise_bid_prompt(
    firm: FirmState,
    target_id: str,
    own_current_bid: float,
    leader_bid: float,
    target_equity_price: float,
) -> tuple[str, str]:
    """Wave gamma: ask a losing bidder if they want to raise their offer.

    Called in round 1 of a contested M&A auction when the firm's round-0
    bid was beaten. The firm decides whether to raise above the current
    leader, match, or drop out.
    """
    max_raise_cost_pct = 0.9
    max_feasible_per_share = (firm.cash * max_raise_cost_pct) / max(
        1, firm.shares_outstanding)  # placeholder; target shares differ
    system = f"""You are the CEO of {firm.firm_id}, currently outbid in an
M&A auction for {target_id}.

Your round-0 offer: ${own_current_bid:.2f}/share
Leading bid (competitor): ${leader_bid:.2f}/share
Target's pre-deal equity price: ${target_equity_price:.2f}/share

You may:
  - RAISE above the leader (specify new price)
  - DROP OUT (match or fold)

Consider:
  - Overpayment risk: bids much above pre-deal price destroy value.
  - Your own cash runway and financing options.
  - Strategic value of winning this target (synergies, market share).

Cash available: ${firm.cash:,.0f}.

Output JSON:
```json
{{
  "action": "raise|drop",
  "new_offer_price_per_share": <number, required when action=raise>,
  "reasoning": "<1-2 sentences>"
}}
```
Output ONLY JSON wrapped in ```json ... ```."""

    user = f"""The target board will accept the highest remaining offer.
If you drop, you lose this target. If you raise, commit real money.
Decide."""

    return system, user


def build_bidder_prompt(
    firm: FirmState,
    potential_targets: list[dict],
    macro: MacroState,
) -> tuple[str, str]:
    """Build prompt for a firm considering an acquisition.

    Wave ν+4: emphasizes the sparse-trigger nature of M&A in real
    industries — the default outcome is no bid; only act when there's
    a clear strategic reason or a target in genuine distress.
    """
    system = f"""You are the CEO of {firm.firm_id} considering whether to make an acquisition.

M&A is a normal strategic-capital-allocation choice. It is not adversarial, it is not casual, and there is no default answer (yes or no). Read your own position and the industry honestly, then decide whether bidding now creates more value than the alternatives (organic growth, capital return, holding cash). Reasons to consider an acquisition:

  - The target is in genuine distress (cash crisis, multi-quarter performance deterioration, going-concern signals) and you can buy assets at a meaningful discount.
  - The target has a complementary capability or customer base that would meaningfully strengthen your position.
  - You have surplus capital AND a clear integration plan AND a target whose standalone value the market is undervaluing.
  - Persistent sub-scale incumbents are also legitimate targets: a firm that has been in the industry for many quarters but has never reached competitive scale ties up capacity, talent, and a market slot that a stronger consolidator could deploy more productively. These are NOT predatory acquisitions of fresh entrants — they are consolidation of structurally weak incumbents, which is exactly what mature-industry M&A looks like in reality.
  - When the industry is highly concentrated (one or two firms accounting for most of industry revenue while the rest stay sub-scale), real M&A activity tends to INCREASE, not decrease:
      * The leaders may acquire trailing peers to extract their capability, brand, or capacity, or simply to clear the field.
      * Trailing firms may merge with each other to create a competitive number-two.
      * Specialty firms with differentiated segments may be acquired to fill product-line gaps.
    A concentrated industry where nobody ever bids is unusual — there is normally either consolidation by the leader, defensive mergers among the laggards, or both.

Reasons NOT to bid:
  - You don't have surplus cash relative to your own runway needs.
  - The target is a brand-new entrant (a firm that has been operating for only a few quarters) — acquiring fresh entrants for fire-sale prices is predatory and undermines the industry's pipeline. Wait for them to either succeed or fail on their own. (Note: a firm that has been operating for many years but never grew is a different case — see "persistent sub-scale incumbents" above.)
  - You don't have an articulable integration thesis.
  - The target's price reflects fair value — there's no bargain and no synergy upside.

WHAT YOU ABSORB IF A DEAL CLOSES:
  - All identifiable assets and liabilities at book value
  - Goodwill (the premium over book value) on your balance sheet
  - The target's capability stock (with integration friction — only a fraction transfers)
  - The target's brand and customer relationships (with friction)
  - The target's manufacturing capacity (no friction — physical equipment)
  - Inherited market share (customers may churn after the deal)

Output JSON:
{{"bid": false, "reasoning": "<1-2 sentences on why no bid this quarter>"}}
OR
{{"bid": true, "target_id": "firm_X", "offer_price_per_share": <number>, "offer_type": "friendly", "reasoning": "<2-3 sentences on the strategic logic, expected synergy, and price justification>"}}

Your available cash: ${firm.cash:,.0f}. Bidding more than your cash would deplete will destabilize your own firm.
Output ONLY JSON wrapped in ```json ... ```."""

    target_lines = []
    for t in potential_targets:
        # Wave ν+12: include real (recent-quarter) revenue and the target's
        # operating tenure so the bidder can distinguish "fresh entrant"
        # (do not predate on them) from "persistent sub-scale incumbent"
        # (legitimate consolidation target). The fake `Revenue=cash*0.1`
        # placeholder previously here was misleading.
        rev = t.get('revenue_last_q', 0)
        tenure = t.get('tenure_q', 0)
        tenure_tag = (
            "fresh entrant"
            if tenure <= 6 else
            ("multi-year incumbent" if tenure >= 16 else "established firm")
        )
        target_lines.append(
            f"  {t['firm_id']}: SharePrice=${t['equity_price']:.2f} "
            f"LastQRevenue=${rev:,.0f} Cash=${t['cash']:,.0f} "
            f"Generation={t.get('generation', 1)} "
            f"Tenure={tenure}Q ({tenure_tag})"
        )

    user = f"""YOUR POSITION:
  Cash: ${firm.cash:,.0f}
  Revenue: ${firm.market_cap:,.0f} market cap
  Generation: {firm.product_generation}

POTENTIAL TARGETS:
{chr(10).join(target_lines) if target_lines else '(None available)'}

Decide whether to bid."""

    return system, user


def build_target_board_prompt(
    target: FirmState,
    bid: MABid,
    macro: MacroState,
) -> tuple[str, str]:
    """Build prompt for target board evaluating a bid.

    Wave ν+4: target board does its own B-plan analysis comparing
    offered price to standalone-firm value. Bid is rejected if
    standalone value clearly exceeds the offer.
    """
    premium = (bid.offer_price_per_share / target.equity_price - 1) * 100 if target.equity_price > 0 else 0

    system = f"""You are the board of {target.firm_id} reviewing an acquisition offer. You represent founders, PE investors, and (if public) public shareholders. Your duty is to evaluate whether the offer is in the best interest of these stakeholders.

YOUR EVALUATION PROCESS (do this explicitly in your reasoning):

  1. STANDALONE B-PLAN: What is your firm's expected forward value if you remain independent? Consider:
     - Current cash and runway
     - R&D pipeline and time to next-generation product
     - Likely future financing rounds (terms, dilution)
     - Probability of reaching profitability vs. defaulting
     - Reasonable expected exit value (IPO, eventual M&A) discounted to today

  2. OFFER COMPARISON: Does the bidder's offered price meaningfully exceed your standalone B-plan value? A reasonable acquisition premium reflects the bidder's expected synergies. If the offer is at or below your standalone value, REJECT — the bidder is trying to capture firm value cheaply.

  3. INTEGRATION CONSIDERATIONS: Even at a fair price, ask:
     - Will the deal preserve your customer base / employees / brand?
     - Is the bidder a credible operator?
     - For PE shareholders: does this exit produce a reasonable multiple?

  4. RISK CONSIDERATIONS: Standalone risk vs. acquired risk:
     - If you're in financial distress, even a modest premium may be the rational outcome.
     - If you're healthy and growing, hold out for a better offer or remain independent.

Output JSON:
{{"accept": true/false, "counter_price_per_share": <optional number — the price at which you WOULD accept, if any>, "reasoning": "<3-5 sentences explicitly comparing offered price to your standalone B-plan value and articulating the decision>"}}

Wave ν+10 item 6: when you reject, you SHOULD specify a counter_price_per_share if there is a price (typically a modest premium over the offered) at which you would have accepted. This converts a binary reject into a negotiated counter that the bidder may consider next quarter. Set counter_price to 0 only if no price would have cleared (the deal is structurally undesirable, not just under-priced).

Output ONLY JSON wrapped in ```json ... ```."""

    user = f"""ACQUISITION OFFER:
  Bidder: {bid.bidder_id}
  Offer price: ${bid.offer_price_per_share:.2f}/share
  Premium over current price: {premium:.0f}%
  Offer type: {bid.offer_type}
  Total purchase price: ${bid.cash_component:,.0f}

YOUR FIRM (target):
  Current equity price: ${target.equity_price:.2f}
  Cash: ${target.cash:,.0f}
  Capability: {target.capability_stock:.0f}/100
  Brand: {target.brand_stock:.0f}/100
  Generation: {target.product_generation}
  Lifecycle stage: {target.lifecycle_stage}
  Cumulative product R&D: ${target.rd_cumulative_product:,.0f}
  Market cap: ${target.market_cap:,.0f}
  Total assets: ${target.total_assets:,.0f}
  Total liabilities: ${target.total_liabilities:,.0f}

Conduct your B-plan analysis and decide."""

    return system, user


MA_REGULATOR_SYSTEM_PROMPT = """You are the antitrust regulator (industry oversight body) reviewing a friendly merger between two firms in this industry. You have already received the bidder + target's submission and the public Compustat panel for the industry.

Your job is a substantive review of the proposed deal. Approve when the deal is consistent with continued competitive industry structure; block when it concentrates the market in a way that would harm consumers, foreclose competitors, or create a dominant firm with no offsetting efficiencies.

Considerations:
  - INDUSTRY STRUCTURE: how many active firms exist, what is the post-merger HHI, does the combination create a clearly dominant firm? Concentration that crosses obvious thresholds (one firm >40% share post-merger, or HHI rising sharply into a concentrated regime) warrants closer scrutiny.
  - EFFICIENCY DEFENSE: combinations that produce real efficiencies (manufacturing scale, R&D platform consolidation, complementary products) can be defended. Combinations that look like share-grabs without operational logic should be blocked.
  - DISTRESSED-TARGET DEFENSE: when the target is in genuine financial distress (cash crisis, near-default), a deal may be permitted even at higher post-merger concentration because the alternative is asset destruction. This is the failing-firm defense in real antitrust law.
  - CONSUMER WELFARE: would post-merger pricing power likely raise prices, narrow access, or reduce R&D investment? When the answer is plausibly yes, block.

You are NOT supposed to block every deal. Real regulators approve most filed mergers — the bar is "does this materially harm competition," not "does this concentrate the industry at all." Use judgment.

OUTPUT JSON:
{
  "decision": "approve | block | approve_with_conditions",
  "rationale": "<3-5 sentences referencing the industry structure facts and the deal's logic>",
  "conditions": "<if approve_with_conditions: 1-2 conditions, e.g. divestiture of a specific facility or assets; otherwise empty string>"
}"""


def build_ma_regulator_prompt(
    acquirer: FirmState,
    target: FirmState,
    bid_price_per_share: float,
    industry_firms: dict,
    macro: MacroState,
) -> tuple[str, str]:
    """Build (system, user) prompt for the regulator's review of a friendly
    merger. PUBLIC information only — the regulator sees the same Compustat
    panel as the public + the announced deal terms."""
    deal_value = bid_price_per_share * target.shares_outstanding
    # Industry stats
    active = [(fid, f) for fid, f in industry_firms.items() if f.is_active]
    n_active = len(active)
    # Approximate share via market_cap as a rough proxy
    total_mcap = sum(max(0.0, f.market_cap) for fid, f in active) or 1.0
    acquirer_share = acquirer.market_cap / total_mcap if acquirer.market_cap > 0 else 0
    target_share = target.market_cap / total_mcap if target.market_cap > 0 else 0
    post_merger_share = acquirer_share + target_share

    industry_lines = []
    for fid, f in sorted(active, key=lambda x: -x[1].market_cap):
        industry_lines.append(
            f"  {fid}: capability={f.capability_stock:.0f}/100 "
            f"brand={f.brand_stock:.0f}/100 cash=${f.cash/1e6:.0f}M "
            f"market_cap=${f.market_cap/1e6:.0f}M"
        )

    user = f"""ANNOUNCED DEAL:
  Acquirer: {acquirer.firm_id} ({acquirer.firm_id})
  Target:   {target.firm_id}
  Bid price/share: ${bid_price_per_share:,.2f}
  Total deal value: ${deal_value:,.0f}
  Acquirer pre-merger share (mcap proxy): {acquirer_share:.1%}
  Target pre-merger share: {target_share:.1%}
  Post-merger combined share: {post_merger_share:.1%}

INDUSTRY STRUCTURE (n_active={n_active}):
{chr(10).join(industry_lines)}

TARGET FIRM STATE:
  Cash: ${target.cash:,.0f}
  LTD: ${target.long_term_debt:,.0f}
  Capability: {target.capability_stock:.0f}/100
  Brand: {target.brand_stock:.0f}/100
  Lifecycle: {target.lifecycle_stage}
  Recent operating cash flow trajectory: (use the public Compustat panel)

Decide: approve, block, or approve_with_conditions."""

    return MA_REGULATOR_SYSTEM_PROMPT, user


def make_ma_regulator(backend, state_ref: list):
    """Returns a callable regulator(acquirer, target, bid) -> dict."""
    def regulator(acquirer: FirmState, target: FirmState,
                   bid_price_per_share: float) -> dict:
        if backend is None:
            # No regulator wired → default approve so legacy behaviour is
            # preserved when the orchestrator doesn't wire this.
            return {"decision": "approve", "rationale": "no regulator wired",
                    "conditions": ""}
        world = state_ref[0] if state_ref and state_ref[0] else None
        if world is None:
            return {"decision": "approve", "rationale": "no world state",
                    "conditions": ""}
        system, user = build_ma_regulator_prompt(
            acquirer, target, bid_price_per_share,
            world.firms, world.macro,
        )
        try:
            from .telemetry import set_role
            with set_role("ma_regulator"):
                result = backend.complete_json(system, user)
        except Exception as e:
            return {"decision": "approve",
                    "rationale": f"regulator call failed: {e}",
                    "conditions": ""}
        if not isinstance(result, dict):
            return {"decision": "approve",
                    "rationale": "regulator returned non-dict",
                    "conditions": ""}
        decision = str(result.get("decision", "approve")).strip().lower()
        if decision not in {"approve", "block", "approve_with_conditions"}:
            decision = "approve"
        return {
            "decision": decision,
            "rationale": str(result.get("rationale", ""))[:600],
            "conditions": str(result.get("conditions", ""))[:300],
        }
    return regulator


def process_acquisition(
    acquirer: FirmState,
    target: FirmState,
    bid: MABid,
) -> tuple[FirmState, FirmState, float]:
    """Execute acquisition under purchase-method GAAP. Returns
    (new_acquirer, deactivated_target, goodwill).

    Acquirer pays `purchase_price` in cash and absorbs ALL of target's
    identifiable assets + liabilities. Residual of purchase_price over
    net book value is recorded as goodwill.

    BS identity check:
      Δ(acquirer assets)      = target.total_assets + goodwill - purchase_price
      Δ(acquirer liabilities) = target.total_liabilities
      Δ(acquirer equity)      = 0 (cash-financed acquisition; no share
                                 issuance; the residual equity impact is
                                 zero because goodwill = purchase_price -
                                 (target.assets - target.liabilities), so
                                 net asset gain = liabilities absorbed.)
    """
    purchase_price = bid.offer_price_per_share * target.shares_outstanding
    net_book_value = target.total_assets - target.total_liabilities
    # Standard GAAP (ASC 805):
    #   - purchase_price > net_book_value: excess booked as goodwill (asset)
    #   - purchase_price < net_book_value: excess booked as "bargain-
    #     purchase gain" in earnings (flows into retained_earnings)
    goodwill = max(0, purchase_price - net_book_value)
    bargain_purchase_gain = max(0, net_book_value - purchase_price)

    # Wave ν+9 Bug M3: documenting and disentangling the integration cost.
    # Previously the comments on these lines were inconsistent with the
    # math (claimed "10% of annual rev" but produced cash * 0.04). The math
    # is preserved for behavioural continuity; comments now describe what
    # is actually happening.
    #
    # Rough proxy: target quarterly revenue ≈ 10% of cash (a stand-in for
    # the missing trailing-revenue look-up). Integration cost is then
    # ~40% of that quarterly proxy = 4% of target cash, applied as a
    # one-time integration drag spread evenly over four quarters.
    estimated_target_revenue_quarterly = target.cash * 0.1
    integration_cost_total = estimated_target_revenue_quarterly * 0.4
    integration_cost_per_q = integration_cost_total / 4

    # Absorb ALL target assets + all liabilities. Operational stocks
    # (capacity/capability/brand/R&D) keep the legacy partial weighting
    # since they represent operational efficiency, not book-value items.
    new_acquirer = acquirer.evolve(
        # Cash: acquirer pays bid, receives target's cash
        cash=acquirer.cash - purchase_price + target.cash,
        # All other balance-sheet assets transfer at book value
        accounts_receivable=acquirer.accounts_receivable + target.accounts_receivable,
        allowance_for_doubtful_accounts=acquirer.allowance_for_doubtful_accounts
            + target.allowance_for_doubtful_accounts,
        inventory_units=acquirer.inventory_units + target.inventory_units,
        inventory_value=acquirer.inventory_value + target.inventory_value,
        ppe_gross=acquirer.ppe_gross + target.ppe_gross,
        accum_depreciation=acquirer.accum_depreciation + target.accum_depreciation,
        goodwill=acquirer.goodwill + goodwill,
        # All liabilities transfer at book value
        accounts_payable=acquirer.accounts_payable + target.accounts_payable,
        accrued_expenses=acquirer.accrued_expenses + target.accrued_expenses,
        taxes_payable=acquirer.taxes_payable + target.taxes_payable,
        deferred_revenue=acquirer.deferred_revenue + target.deferred_revenue,
        legal_reserve_balance=acquirer.legal_reserve_balance + target.legal_reserve_balance,
        revolver_balance=acquirer.revolver_balance + target.revolver_balance,
        long_term_debt=acquirer.long_term_debt + target.long_term_debt,
        deferred_tax_liability=acquirer.deferred_tax_liability + target.deferred_tax_liability,
        pension_liability=acquirer.pension_liability + target.pension_liability,
        # Operational stocks: partial absorption (integration discount).
        # Wave ν+4: added capability_stock absorption (was missing —
        # the user's "absorb technology" intent). Capped at 100 since
        # capability is a 0-100 scale.
        capacity_units=acquirer.capacity_units + target.capacity_units,
        capability_stock=min(100.0,
            acquirer.capability_stock + target.capability_stock * MA_CAPABILITY_ABSORPTION),
        rd_cumulative_product=acquirer.rd_cumulative_product
            + target.rd_cumulative_product * MA_RD_ABSORPTION,
        rd_cumulative_process=acquirer.rd_cumulative_process
            + target.rd_cumulative_process * MA_RD_ABSORPTION,
        brand_stock=min(100.0,
            acquirer.brand_stock + target.brand_stock * MA_BRAND_ABSORPTION),
        # Integration cost + lineage tracking
        acquisition_integration_cost=acquirer.acquisition_integration_cost + integration_cost_per_q * 4,
        acquired_firms=acquirer.acquired_firms + (target.firm_id,),
        # Bargain-purchase gain flows to RE (like a non-cash earnings item)
        retained_earnings=acquirer.retained_earnings + bargain_purchase_gain,
    )

    # Target deactivated; zero out its balance sheet so it can't be
    # double-counted in aggregate industry metrics. Equity also zeroed
    # (all value transferred to acquirer via the cash payment).
    # Wave ν+11 fix: also zero operational stocks (capability, brand,
    # capacity) so post-deactivation reads are clean.
    deactivated_target = target.evolve(
        is_active=False,
        cash=0.0,
        accounts_receivable=0.0,
        allowance_for_doubtful_accounts=0.0,
        inventory_units=0,
        inventory_value=0.0,
        ppe_gross=0.0,
        accum_depreciation=0.0,
        goodwill=0.0,
        accounts_payable=0.0,
        accrued_expenses=0.0,
        taxes_payable=0.0,
        deferred_revenue=0.0,
        legal_reserve_balance=0.0,
        revolver_balance=0.0,
        long_term_debt=0.0,
        deferred_tax_liability=0.0,
        pension_liability=0.0,
        common_stock=0.0,
        apic=0.0,
        retained_earnings=0.0,
        treasury_stock=0.0,
        # Wave ν+11: also clear operational stocks
        capability_stock=0.0,
        brand_stock=0.0,
        capacity_units=0,
    )

    return new_acquirer, deactivated_target, goodwill


def make_ma_agent(backends: dict[str, LLMBackend], state_ref: list,
                    regulator_fn=None):
    """Factory: create M&A agent functions.

    Returns a function that handles the full M&A phase:
    checks if any firm wants to bid, processes bids, consolidates.

    Wave ν+11: when `regulator_fn` is provided, it is called after the
    target board accepts a bid. The regulator can block the deal on
    competition grounds — implementing the antitrust review step that
    real friendly mergers go through.
    """

    def ma_phase(
        firms: dict[str, FirmState],
        macro: MacroState,
    ) -> tuple[dict[str, FirmState], list[dict]]:
        """Run M&A phase with multi-bidder auctions.

        Two-round auction protocol (Wave gamma):
          Round 0: every eligible firm proposes a bid on one target.
          Round 1: if multiple firms bid on the same target, lower bidders
                   get a 10% auto-raise (deterministic; LLM re-bid would be
                   richer but adds N extra calls per contested target).
          Target board: accepts the HIGHEST final bid (or rejects all).
        Also records each contested auction as a `negotiations_log` entry
        with round-by-round bid history.
        """
        deals = []
        negotiations = []   # returned to orchestrator for logging
        active_firms = {fid: f for fid, f in firms.items() if f.is_active}

        # ── Round 0: collect initial bids ────────────────────────────────
        all_bids: dict[str, list[MABid]] = {}  # target_id → [MABid, ...]
        bidder_rationale: dict[tuple[str, str], str] = {}  # (bidder, target) → prose
        # Wave ν: cap target list at K most-relevant peers to keep
        # bidder prompt size bounded at large N. Relevance heuristic:
        # closest equity price (proxy for affordability + peer status),
        # tiebreak by same generation. Keeps real agency (bidder still
        # chooses) while preventing prompt-bytes from blowing up as O(N).
        MAX_TARGETS_PER_BIDDER = 6

        # Wave ν+7: parallelize bidder LLM calls. Each bidder reads a
        # snapshot of `active_firms` and emits a bid; nothing in the
        # bidder body mutates shared state. We aggregate results into
        # `all_bids` and `bidder_rationale` serially after all calls
        # return, so the dict mutations are race-free.
        from . import telemetry as _tel
        bidder_jobs = []  # (fid, firm, targets, backend)
        for fid, firm in list(active_firms.items()):
            if firm.ceo_search_in_progress or firm.acquisition_integration_cost > 0:
                continue
            backend = backends.get(fid)
            if backend is None:
                continue
            all_candidates = [
                (tid, t) for tid, t in active_firms.items()
                if tid != fid and t.is_active
            ]
            if not all_candidates:
                continue
            # Rank: closest equity price first, then matching generation
            def _relevance_score(item, bidder_firm=firm):
                _tid, _t = item
                price_gap = abs(_t.equity_price - bidder_firm.equity_price)
                gen_match = 0 if _t.product_generation == bidder_firm.product_generation else 1
                return (gen_match, price_gap)
            all_candidates.sort(key=_relevance_score)
            top_candidates = all_candidates[:MAX_TARGETS_PER_BIDDER]
            # Wave ν+12: pass REAL last-quarter revenue and tenure so the
            # bidder can distinguish fresh entrants from sub-scale incumbents.
            # Previously `revenue: t.cash * 0.1` was a fake placeholder that
            # misled bidders. Pull both from world state via state_ref.
            _state = state_ref[0] if state_ref and state_ref[0] else None
            _last_flows = getattr(_state, "last_quarter_flows", {}) if _state else {}
            _compustat = getattr(_state, "compustat_rows", []) if _state else []
            targets = []
            for tid, t in top_candidates:
                # Last-quarter revenue from QuarterFlows on world state
                last_q_rev = 0.0
                flow = _last_flows.get(tid)
                if flow is not None:
                    last_q_rev = float(getattr(flow, "net_sales",
                                                getattr(flow, "revenue", 0)) or 0)
                # Tenure: count of compustat rows we've recorded for this firm
                tenure_q = sum(1 for r in _compustat if r.firm_id == tid)
                targets.append({
                    "firm_id": tid,
                    "equity_price": t.equity_price,
                    "revenue_last_q": last_q_rev,
                    "cash": t.cash,
                    "generation": t.product_generation,
                    "tenure_q": tenure_q,
                })
            if not targets:
                continue
            bidder_jobs.append((fid, firm, targets, backend))

        def _run_bidder(job):
            _fid, _firm, _targets, _backend = job
            try:
                _system, _user = build_bidder_prompt(_firm, _targets, macro)
                with _tel.set_role(f"ma_bidder_{_fid}"):
                    _result = _backend.complete_json(_system, _user)
                return (_fid, _firm, _result, None)
            except Exception as e:
                return (_fid, _firm, None, e)

        if len(bidder_jobs) > 1:
            import concurrent.futures as _cf_ma
            with _cf_ma.ThreadPoolExecutor(
                    max_workers=min(len(bidder_jobs), 8)) as _pool_ma:
                bidder_results = list(_pool_ma.map(_run_bidder, bidder_jobs))
        else:
            bidder_results = [_run_bidder(j) for j in bidder_jobs]

        for fid, firm, result, err in bidder_results:
            if err is not None or result is None or not result.get("bid"):
                continue
            target_id = result.get("target_id", "")
            if target_id not in active_firms:
                continue
            offer_price = result.get("offer_price_per_share", 0)
            if offer_price <= 0:
                continue
            total_cost = offer_price * active_firms[target_id].shares_outstanding
            if total_cost > firm.cash * 0.9:
                continue
            bid = MABid(
                bidder_id=fid, target_id=target_id,
                offer_price_per_share=offer_price,
                offer_type=result.get("offer_type", "friendly"),
                cash_component=total_cost,
                quarter=macro.quarter,
            )
            all_bids.setdefault(target_id, []).append(bid)
            bidder_rationale[(fid, target_id)] = (result.get("reasoning") or "")[:300]

        # ── Round 1: contested targets — each losing bidder decides via LLM
        # (raise / drop). LLM call only fires when ≥2 firms bid the same
        # target, which is rare. Deterministic fallback when LLM unavailable.
        round_history: dict[str, list[dict]] = {}
        for target_id, bids in all_bids.items():
            if len(bids) <= 1:
                continue
            # Record round 0
            round_history[target_id] = [{
                "round": 0,
                "bids": [
                    {"bidder": b.bidder_id,
                     "price_per_share": b.offer_price_per_share}
                    for b in bids
                ],
            }]
            # Sort desc by offer
            bids.sort(key=lambda b: b.offer_price_per_share, reverse=True)
            top = bids[0]
            raised_bids = [top]
            target = active_firms[target_id]

            for b in bids[1:]:
                bidder_firm = active_firms.get(b.bidder_id)
                if bidder_firm is None:
                    raised_bids.append(b)
                    continue

                # Ask bidder's LLM to decide raise/drop
                bidder_backend = backends.get(b.bidder_id)
                new_bid = b  # default: no change (= drop out implicitly)
                if bidder_backend is not None:
                    try:
                        rsys, ruser = build_raise_bid_prompt(
                            bidder_firm, target_id,
                            b.offer_price_per_share,
                            top.offer_price_per_share,
                            target.equity_price,
                        )
                        with _tel.set_role(f"ma_raise_{b.bidder_id}"):
                            rresult = bidder_backend.complete_json(rsys, ruser)
                        if rresult and rresult.get("action") == "raise":
                            new_price = float(rresult.get(
                                "new_offer_price_per_share", 0))
                            if new_price > b.offer_price_per_share:
                                raised_cost = new_price * target.shares_outstanding
                                if raised_cost <= bidder_firm.cash * 0.9:
                                    from dataclasses import replace as _r
                                    new_bid = _r(
                                        b,
                                        offer_price_per_share=new_price,
                                        cash_component=raised_cost,
                                    )
                    except Exception:
                        pass
                raised_bids.append(new_bid)

            # Sort raised bids by price desc
            raised_bids.sort(key=lambda b: b.offer_price_per_share, reverse=True)
            all_bids[target_id] = raised_bids
            round_history[target_id].append({
                "round": 1,
                "bids": [
                    {"bidder": b.bidder_id,
                     "price_per_share": b.offer_price_per_share}
                    for b in raised_bids
                ],
            })

        # ── Target board evaluates HIGHEST bid per target ────────────────
        for target_id, bids in all_bids.items():
            if not bids:
                continue
            winning_bid = max(bids, key=lambda b: b.offer_price_per_share)
            target = active_firms[target_id]
            bidder_firm = active_firms[winning_bid.bidder_id]
            target_backend = backends.get(target_id)
            accepted = False
            counter_price = 0.0
            if target_backend:
                t_system, t_user = build_target_board_prompt(target, winning_bid, macro)
                with _tel.set_role(f"ma_target_{target_id}"):
                    t_result = target_backend.complete_json(t_system, t_user)
                if t_result:
                    accepted = t_result.get("accept", False)
                    try:
                        counter_price = float(
                            t_result.get("counter_price_per_share", 0) or 0
                        )
                    except (TypeError, ValueError):
                        counter_price = 0.0
            # Wave ν+10 item 6: friendly counter-offer bridge. If target
            # rejected but countered at a price the bidder's offer is
            # already within 10% of, treat as accepted at the counter
            # price (the bidder is implicitly willing to pay near that
            # level given they made the original offer). This converts
            # binary accept/reject into a negotiated outcome and unlocks
            # the friendly M&A pathway that was structurally closed.
            if (not accepted) and counter_price > 0 and winning_bid.offer_price_per_share > 0:
                gap = (counter_price - winning_bid.offer_price_per_share) / winning_bid.offer_price_per_share
                if 0 < gap <= 0.10:
                    bidder_cash_ok = (counter_price * target.shares_outstanding
                                      <= bidder_firm.cash * 0.9)
                    if bidder_cash_ok:
                        from dataclasses import replace as _dr
                        winning_bid = _dr(
                            winning_bid,
                            offer_price_per_share=counter_price,
                            cash_component=counter_price * target.shares_outstanding,
                        )
                        accepted = True
            # Hostile override
            if not accepted and target.equity_price > 0:
                if winning_bid.offer_price_per_share > target.equity_price * HOSTILE_OVERRIDE_MULTIPLE:
                    accepted = True
            # Build negotiation record for contested auctions
            if target_id in round_history:
                negotiations.append({
                    "topic": "ma_auction",
                    "target_firm": target_id,
                    "quarter": macro.quarter,
                    "num_bidders": len(round_history[target_id][0]["bids"]),
                    "rounds": round_history[target_id],
                    "winner": winning_bid.bidder_id if accepted else None,
                    "winning_price": winning_bid.offer_price_per_share if accepted else None,
                    "outcome": (
                        "accepted_at_counter" if accepted and counter_price > 0
                        else "accepted" if accepted
                        else "rejected_with_counter" if counter_price > 0
                        else "rejected"
                    ),
                    "counter_price_per_share": counter_price if counter_price > 0 else None,
                })
            # Wave ν+11: regulator approval gate. After target accepts,
            # the regulator reviews the deal. The deal proceeds only on
            # approve / approve_with_conditions. On block, the deal is
            # killed and the negotiation outcome flips to "blocked_by_regulator".
            regulator_decision = None
            if accepted and regulator_fn is not None:
                try:
                    regulator_decision = regulator_fn(
                        bidder_firm, target, winning_bid.offer_price_per_share,
                    )
                except Exception as e:
                    regulator_decision = {
                        "decision": "approve",
                        "rationale": f"regulator threw {type(e).__name__}: {e}",
                        "conditions": "",
                    }
                if regulator_decision.get("decision") == "block":
                    accepted = False
                    # Update the negotiation record to reflect the block
                    if target_id in round_history and negotiations:
                        for n in negotiations:
                            if n.get("target_firm") == target_id and n.get("outcome") in ("accepted_at_counter", "accepted"):
                                n["outcome"] = "blocked_by_regulator"
                                n["winner"] = None
                                n["winning_price"] = None
                                n["regulator_rationale"] = regulator_decision.get("rationale", "")

            if accepted:
                new_acquirer, deactivated_target, goodwill = process_acquisition(
                    bidder_firm, target, winning_bid,
                )
                active_firms[winning_bid.bidder_id] = new_acquirer
                active_firms[target_id] = deactivated_target
                deals.append({
                    "bidder": winning_bid.bidder_id,
                    "target": target_id,
                    "price_per_share": winning_bid.offer_price_per_share,
                    "goodwill": goodwill,
                    "quarter": macro.quarter,
                    "num_competing_bids": len(round_history.get(target_id, [])) and
                                           len(round_history[target_id][0]["bids"]) or 1,
                    "regulator_decision": regulator_decision.get("decision") if regulator_decision else "n/a",
                    "regulator_conditions": regulator_decision.get("conditions", "") if regulator_decision else "",
                })

        # Attach negotiation records to the first deal (so orchestrator can
        # extract them). Uses a magic key that won't collide with normal
        # deal fields.
        if negotiations and deals:
            deals[0]["_auctions"] = negotiations
        elif negotiations:
            # No deal succeeded but auctions happened — return as a synthetic
            # empty deal marker.
            deals.append({"_auctions": negotiations, "bidder": "", "target": "",
                           "goodwill": 0, "quarter": macro.quarter,
                           "price_per_share": 0})

        return active_firms, deals

    return ma_phase


# ────────────────────────────────────────────────────────────────────────
# Wave ν+2: env-LLM-judged M&A
#
# Single env call decides which acquisitions happen this quarter, at
# what prices. Replaces the per-bidder LLM model (which made N+ calls
# per quarter). Same `ma_phase(firms, macro) -> (firms, deals)` contract
# so the orchestrator's call site is unchanged.
# ────────────────────────────────────────────────────────────────────────

MA_JUDGE_SYSTEM_PROMPT = """You are the market environment adjudicating M&A activity this quarter. You see ALL active firms (their cash, capability, brand, generation, lifecycle stage). Each quarter, real M&A activity is sparse — most quarters see zero deals. Real-world deals happen when:
  - A strategic acquirer sees clear synergy with a target
  - A target firm is undervalued relative to its assets
  - Industry consolidation pressure exists
  - A weaker firm seeks safe harbor with a stronger one

For each plausible deal, decide:
  - Bidder firm + target firm
  - Offer price per share (typically a modest premium to target's pre-deal equity price; bargain deals can be lower; competitive auctions higher)
  - Whether the target board accepts (most do at fair premium; rejection happens for strategic-mismatch deals or hostile situations)
  - 1-2 sentence rationale citing the synergy

CONSTRAINTS:
  - Bidder must have cash to fund the deal (purchase_price within bidder's cash on hand with margin)
  - Bidder cannot acquire itself
  - At most one deal per bidder per quarter (real firms can't integrate multiple targets simultaneously)
  - At most one deal per target per quarter (a target can only be sold once)
  - M&A activity is sparse in real industries — most quarters see no deals. Spawn deals only when a clear strategic logic exists.

ACTIVE FIRMS:
{firms_block}

INDUSTRY CONTEXT (from scenario):
{industry_context}

OUTPUT (JSON):
{{
  "deals": [
    {{
      "bidder_id": "<firm_id>",
      "target_id": "<firm_id>",
      "offer_price_per_share": <number>,
      "target_accepts": <true|false>,
      "offer_type": "friendly" | "hostile",
      "rationale": "<1-2 sentences>"
    }}
    // empty list if no deals this quarter
  ],
  "narrative": "<1-2 sentences on industry M&A activity (or its absence)>"
}}"""


def _format_firms_block_for_ma_judge(firms_dict) -> str:
    from .personalities import get_company_name
    lines = []
    for fid, f in firms_dict.items():
        if not f.is_active:
            continue
        try:
            idx = int(fid.split("_")[-1])
        except (ValueError, IndexError):
            idx = 0
        lines.append(
            f"  {fid} ({get_company_name(idx)}): "
            f"cash=${f.cash:,.0f} | shares={f.shares_outstanding:,} | "
            f"equity_price=${f.equity_price:.2f} | "
            f"capability={f.capability_stock:.0f}/100 | "
            f"brand={f.brand_stock:.0f}/100 | "
            f"Gen{f.product_generation} | stage={f.lifecycle_stage}"
            f"{' [PUBLIC]' if f.is_public else ''}"
        )
    return "\n".join(lines) if lines else "(no active firms)"


def make_ma_judge_agent(env_backend: LLMBackend, state_ref: list):
    """Wave ν+2: env-LLM-judged M&A. Single LLM call per quarter
    decides all deals. Returns the same `ma_phase(firms, macro)` callable
    as `make_ma_agent` so the orchestrator wiring is unchanged.
    """
    def ma_phase(
        firms: dict[str, FirmState],
        macro: MacroState,
    ) -> tuple[dict[str, FirmState], list[dict]]:
        deals = []
        active_firms = {fid: f for fid, f in firms.items() if f.is_active}
        if len(active_firms) < 2:
            return active_firms, deals

        state = state_ref[0] if state_ref else None
        industry_context_text = "(no scenario context)"
        if state is not None:
            try:
                from .orchestrator import _build_industry_character_dict
                ic = _build_industry_character_dict(state)
                industry_context_text = (ic.get("narrative") or "")[:1500] or industry_context_text
            except Exception:
                pass

        system = MA_JUDGE_SYSTEM_PROMPT.format(
            firms_block=_format_firms_block_for_ma_judge(active_firms),
            industry_context=industry_context_text,
        )
        user = f"Adjudicate M&A activity for Q{macro.quarter}. Output JSON."
        from . import telemetry as _tel
        try:
            with _tel.set_role("ma_judge"):
                result = env_backend.complete_json(system, user)
        except Exception:
            return active_firms, deals
        if result is None:
            return active_firms, deals

        proposed_deals = result.get("deals") or []
        used_bidders: set[str] = set()
        used_targets: set[str] = set()

        for d in proposed_deals:
            if not isinstance(d, dict):
                continue
            bidder_id = str(d.get("bidder_id", "")).strip()
            target_id = str(d.get("target_id", "")).strip()
            if not bidder_id or not target_id or bidder_id == target_id:
                continue
            if bidder_id in used_bidders or target_id in used_targets:
                continue
            if bidder_id not in active_firms or target_id not in active_firms:
                continue
            try:
                offer_per_share = float(d.get("offer_price_per_share", 0) or 0)
            except (TypeError, ValueError):
                continue
            if offer_per_share <= 0:
                continue
            if not bool(d.get("target_accepts", True)):
                continue
            bidder = active_firms[bidder_id]
            target = active_firms[target_id]
            total_cost = offer_per_share * target.shares_outstanding
            if total_cost > bidder.cash * 0.9:
                continue

            bid = MABid(
                bidder_id=bidder_id,
                target_id=target_id,
                offer_price_per_share=offer_per_share,
                offer_type=str(d.get("offer_type", "friendly")),
                cash_component=total_cost,
                quarter=macro.quarter,
            )
            try:
                new_acquirer, deactivated_target, goodwill = process_acquisition(
                    bidder, target, bid,
                )
            except Exception:
                continue
            active_firms[bidder_id] = new_acquirer
            active_firms[target_id] = deactivated_target
            used_bidders.add(bidder_id)
            used_targets.add(target_id)
            deals.append({
                "bidder": bidder_id,
                "target": target_id,
                "price_per_share": offer_per_share,
                "goodwill": goodwill,
                "quarter": macro.quarter,
                "num_competing_bids": 1,  # judge model does not auction
                "_judge_rationale": str(d.get("rationale", ""))[:300],
            })

        return active_firms, deals

    return ma_phase
