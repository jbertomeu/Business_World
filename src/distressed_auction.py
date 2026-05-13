"""
Wave ν: distressed-firm asset auction.

When a firm defaults (delisting or cash-insolvency), its remaining
operating assets — manufacturing capacity (PP&E), inventory, R&D
capability stock, brand goodwill, and residual market position — are
auctioned to surviving firms. Winner pays cash; proceeds flow to
creditors (LTD) first, then to PE cap table pro-rata. Founders, as
residual claimants, get what remains (usually zero).

Design notes:
  - The auction is a single-round sealed-bid. Each surviving firm's
    bidder LLM produces a bid amount (can be zero = pass) + rationale.
  - Highest non-zero bid wins. Ties broken randomly.
  - Winner inherits the defaulted firm's capability_stock, brand_stock,
    inventory, and PP&E (net). The capability/brand carry over as
    weighted additions to the winner's stocks (not simple sums — real
    M&A integration has friction).
  - Proceeds are paid FROM winner's cash TO the defaulted firm's
    creditors (LTD reduction first) then PE pro-rata. Anything left is
    recorded as residual-to-founders (usually $0 after creditor recovery).
  - No quantitative rules in bidder prompt: bidders see the asset
    bundle and decide emergently.

This module is pure — no LLM is constructed here; the orchestrator
passes in bidder_fn per surviving firm.
"""

from __future__ import annotations

import random
from dataclasses import replace as _dc_replace

from .types import FirmState


AUCTION_BIDDER_SYSTEM_PROMPT = """You are the CEO of {bidder_company_name}, a surviving firm in this industry. Other firms have DEFAULTED this quarter and their remaining operating assets are being auctioned as separate LOTS. For each lot you may submit a bid (or decline by bidding zero).

Each lot contains a defaulted firm's manufacturing capacity, inventory, R&D capability, brand position, and residual market share. Winning a lot will absorb those assets into your firm (with real integration friction — absorbed capability and brand do not fully transfer).

ALL LOTS AVAILABLE THIS QUARTER:
{lots_summary}

YOUR FIRM'S CURRENT STATE (what you're bidding FROM):
{your_firm_summary}

OTHER SURVIVING COMPETITORS (who may also bid on any or all lots):
{competitor_summary}

INDUSTRY CONTEXT (from scenario):
{industry_context}

HOW TO THINK ABOUT THIS:
  - Each lot's value is INCREMENTAL to what you already have. You
    already have capability + brand + capacity. The question is what
    each bundle adds on the margin.
  - Absorbed capability + brand do NOT simply add to your stocks — real
    integration has friction; assume meaningful but partial uplift.
  - Inherited market share transitions to whichever firm absorbs the
    customer relationships, but customers may churn.
  - Creditors are paid FIRST from your bid; the defaulted firm's PE
    investors are paid from residual. Your bid goes to them, not to
    you or the defaulted firm's founders.
  - You pay CASH from your own balance sheet. Bid too high and you
    damage your own runway. Bid too low and a competitor wins.
  - You cannot win more lots than your cash supports — your total
    bid amount across all lots will not exceed a prudent fraction of
    your cash. Weigh each lot independently but be aware of the
    aggregate commitment.
  - A bid of 0 on a lot means you decline it. Declining is often
    correct — not every distressed lot is worth buying.

OUTPUT (JSON):
{{
  "bids": [
    {{
      "target_firm_id": "<firm_id of the defaulted firm whose lot you're bidding on>",
      "bid_amount": <$ you would pay for this lot; 0 = decline>,
      "rationale": "<2-3 sentences on why this price and this lot>"
    }}
    // one entry per lot you care about (you may omit lots you would not bid on at any price)
  ],
  "overall_strategic_fit": "<1-2 sentences on how these potential acquisitions fit your strategy>"
}}"""


def _format_asset_summary(defaulted: FirmState) -> str:
    """What's on offer — assets of one defaulted firm at moment of default."""
    return (
        f"  Manufacturing capacity: {defaulted.capacity_units} units/quarter\n"
        f"  PP&E (net): ${defaulted.ppe_net:,.0f}\n"
        f"  Inventory: ${defaulted.inventory_value:,.0f}\n"
        f"  Capability stock: {defaulted.capability_stock:.1f}/100\n"
        f"  Brand stock: {defaulted.brand_stock:.1f}/100\n"
        f"  Product generation at default: Gen {defaulted.product_generation}\n"
        f"  Cumulative product R&D invested: ${defaulted.rd_cumulative_product:,.0f}\n"
        f"  Cumulative process R&D invested: ${defaulted.rd_cumulative_process:,.0f}\n"
        f"  Existing creditors will be paid first from the sale proceeds."
    )


def _format_lots_summary(defaulted_list: list, get_company_name_fn) -> str:
    """Format ALL defaulted firms as labeled lots for one bidder prompt.

    Keeps per-lot asset info visible so the bidder can price each lot
    independently.
    """
    lines = []
    for i, d in enumerate(defaulted_list, start=1):
        idx = int(d.firm_id.split("_")[-1]) if "_" in d.firm_id else 0
        lines.append(f"LOT {i} ({d.firm_id} / {get_company_name_fn(idx)}):")
        lines.append(_format_asset_summary(d))
    return "\n\n".join(lines) if lines else "(no lots this quarter)"


def _format_firm_summary(firm: FirmState) -> str:
    """Bidder's own state — what they have to work with."""
    return (
        f"  Cash: ${firm.cash:,.0f}\n"
        f"  Total assets: ${firm.total_assets:,.0f}\n"
        f"  Capacity: {firm.capacity_units} units/Q\n"
        f"  Capability stock: {firm.capability_stock:.1f}/100\n"
        f"  Brand stock: {firm.brand_stock:.1f}/100\n"
        f"  Product generation: Gen {firm.product_generation}"
    )


def _format_competitor_summary(other_survivors: list[FirmState]) -> str:
    """Other bidders the winner might be competing with."""
    if not other_survivors:
        return "  (no other surviving firms are bidding)"
    lines = []
    for f in other_survivors[:10]:  # cap display
        lines.append(
            f"  {f.firm_id}: cash ${f.cash/1e6:.0f}M, "
            f"capacity {f.capacity_units}, capability {f.capability_stock:.0f}, "
            f"brand {f.brand_stock:.0f}"
        )
    return "\n".join(lines)


AUCTION_JUDGE_SYSTEM_PROMPT = """You are the market environment adjudicating a single-round distressed-asset auction this quarter. Several firms have just defaulted; their remaining operating assets are being sold as separate LOTS to the surviving firms in the industry.

You are OMNISCIENT — you see each surviving firm's cash, capability, brand, capacity, generation, and strategic posture. For each lot you allocate ONE winner (or no-sale), a winning price, and a brief rationale. The price the winner pays comes out of their cash.

ALLOCATION PRINCIPLES:
  - The winner must have cash to support the bid. A bid must not exceed the bidder's cash on hand.
  - Better strategic fit (similar generation, complementary capability, brand affinity) usually beats just-deepest-pockets.
  - A surviving firm may win MULTIPLE lots if it has the cash and strategic logic for both — but track total cash spent against their starting cash.
  - A lot may go UNSOLD if no surviving firm has both the cash and strategic interest. Mark outcome="no_sale" in that case.
  - Pricing should reflect each lot's intrinsic value: PP&E book value + inventory + capability + brand + market-share residual + scarcity premium. Lots with stronger capability + brand command higher prices. Distressed sales typically clear at a discount to going-concern value.

LOTS AVAILABLE THIS QUARTER:
{lots_block}

SURVIVING FIRMS (potential bidders):
{survivors_block}

INDUSTRY CONTEXT (from scenario):
{industry_context}

OUTPUT (JSON):
{{
  "allocations": [
    {{
      "target_firm_id": "<defaulted firm whose lot this is>",
      "outcome": "sold" | "no_sale",
      "winner_id": "<surviving firm_id, or empty string if no_sale>",
      "winning_price_usd": <number; 0 if no_sale>,
      "rationale": "<2-3 sentences on the allocation logic and the price>"
    }}
    // one entry per lot
  ],
  "narrative": "<1-2 paragraphs on what this round of consolidation means for the industry>"
}}"""


def _format_lots_block_for_judge(defaulted_list, get_company_name_fn) -> str:
    lines = []
    for d in defaulted_list:
        idx = int(d.firm_id.split("_")[-1]) if "_" in d.firm_id else 0
        lines.append(
            f"LOT {d.firm_id} ({get_company_name_fn(idx)}):\n"
            + _format_asset_summary(d)
        )
    return "\n\n".join(lines) if lines else "(no lots this quarter)"


def _format_survivors_block_for_judge(survivors, get_company_name_fn) -> str:
    lines = []
    for s in survivors:
        idx = int(s.firm_id.split("_")[-1]) if "_" in s.firm_id else 0
        lines.append(
            f"{s.firm_id} ({get_company_name_fn(idx)}): "
            f"cash=${s.cash:,.0f} | capacity={s.capacity_units} | "
            f"capability={s.capability_stock:.1f}/100 | "
            f"brand={s.brand_stock:.1f}/100 | Gen{s.product_generation} | "
            f"stage={s.lifecycle_stage}{' [PUBLIC]' if s.is_public else ''}"
        )
    return "\n".join(lines) if lines else "(no surviving firms)"


def make_auction_judge_agent(backend):
    """Wave ν+2: env-LLM judges all distressed-auction allocations in
    ONE call per quarter.

    Replaces the per-survivor bidder model (which was already O(N) but
    expensive — 20 LLM calls per quarter at scale). Single env call
    judges all lots simultaneously, like an omniscient market maker.

    Returns a callable (defaulted_list, survivors, industry_context) -> dict
    with `allocations` list (one per lot).
    """
    def judge_fn(
        defaulted_list: list,
        survivors: list,
        industry_context: dict | None,
    ) -> dict | None:
        if not defaulted_list or not survivors:
            return {"allocations": []}
        from .personalities import get_company_name
        ic = industry_context or {}
        ic_text = (ic.get("narrative") or "")[:1500]
        system = AUCTION_JUDGE_SYSTEM_PROMPT.format(
            lots_block=_format_lots_block_for_judge(defaulted_list, get_company_name),
            survivors_block=_format_survivors_block_for_judge(survivors, get_company_name),
            industry_context=ic_text if ic_text else "(no scenario context)",
        )
        user = "Adjudicate the auction. Output JSON."
        try:
            return backend.complete_json(system, user)
        except Exception as e:
            # Wave ν+9 Bug H3: structured error rather than silent None.
            # Returning None made API failures indistinguishable from a
            # legitimate "no allocation" decision; downstream code now
            # detects _error and logs the failure visibly.
            import traceback as _tb
            return {
                "_error": True,
                "_exception": f"{type(e).__name__}: {e}",
                "_traceback": _tb.format_exc()[:2000],
                "allocations": [],
            }
    return judge_fn


def run_quarterly_auctions_via_judge(
    defaulted_list: list,
    survivors: list,
    judge_fn,
    industry_context: dict | None,
    rng: random.Random,
    integration_friction: float = 0.6,
) -> list[dict]:
    """Wave ν+2: O(1) auction allocation via the env judge.

    Returns a list of auction-event dicts in the same shape as
    run_quarterly_auctions (target_firm_id, outcome, winner_id,
    winning_amount, ...) so the orchestrator's apply_auction_result
    code path is unchanged.

    Cash safety: if the judge allocates a lot to a winner who can't
    afford it (e.g., already won an earlier expensive lot), that lot
    is marked no_sale and the next-quarter judge sees the cleaner state.
    """
    if not defaulted_list or not survivors or judge_fn is None:
        return []

    result = judge_fn(defaulted_list, survivors, industry_context)
    if result is None or (isinstance(result, dict) and result.get("_error")):
        # Wave ν+9 Bug H3: surface the underlying exception in the events
        # so the run record carries an audit trail of LLM failures.
        err = (result or {}).get("_exception", "judge_fn returned None")
        return [
            {"target_firm_id": d.firm_id, "outcome": "judge_failed",
             "bids": [], "winner_id": "", "winning_amount": 0.0,
             "judge_error": err}
            for d in defaulted_list
        ]

    allocations = result.get("allocations") or []
    target_to_alloc: dict[str, dict] = {}
    for a in allocations:
        if not isinstance(a, dict):
            continue
        tid = str(a.get("target_firm_id", "")).strip()
        if tid:
            target_to_alloc[tid] = a

    # Track remaining cash so multi-lot wins by one bidder don't double-spend
    remaining_cash = {s.firm_id: s.cash for s in survivors}
    valid_survivor_ids = {s.firm_id for s in survivors}
    events = []

    for d in defaulted_list:
        a = target_to_alloc.get(d.firm_id)
        if a is None:
            events.append({
                "target_firm_id": d.firm_id,
                "outcome": "no_sale",
                "bids": [],
                "winner_id": "",
                "winning_amount": 0.0,
                "winner_rationale": "judge did not allocate",
            })
            continue
        outcome = str(a.get("outcome", "no_sale")).lower()
        winner = str(a.get("winner_id", "")).strip()
        amount = _coerce_bid(a.get("winning_price_usd"))
        rationale = str(a.get("rationale", ""))[:500]

        if outcome != "sold" or not winner or winner not in valid_survivor_ids or amount <= 0:
            events.append({
                "target_firm_id": d.firm_id,
                "outcome": "no_sale",
                "bids": [],
                "winner_id": "",
                "winning_amount": 0.0,
                "winner_rationale": rationale,
            })
            continue

        # Cash check
        if remaining_cash.get(winner, 0) < amount:
            events.append({
                "target_firm_id": d.firm_id,
                "outcome": "no_solvent_bidder",
                "bids": [{"bidder_id": winner, "amount": amount, "rationale": rationale}],
                "winner_id": "",
                "winning_amount": 0.0,
                "winner_rationale": "judge over-allocated cash",
            })
            continue

        remaining_cash[winner] -= amount
        events.append({
            "target_firm_id": d.firm_id,
            "outcome": "sold",
            "bids": [{"bidder_id": winner, "amount": amount, "rationale": rationale}],
            "winner_id": winner,
            "winning_amount": amount,
            "winner_rationale": rationale,
            "integration_friction": integration_friction,
        })

    return events


def make_auction_bidder_agent(backend):
    """Factory: bidder function for one surviving firm.

    Wave ν linearization: ONE LLM call per surviving firm per quarter
    covers ALL defaulted-firm lots on offer. The bidder submits a list
    of per-lot bids in a single JSON response. Previously we invoked
    the bidder LLM once per (survivor, defaulted) pair — that was
    O(M*N) per quarter. Now it is O(N).

    Returns a callable (bidder, defaulted_list, others, industry_context)
    → dict with a `bids` list keyed by target_firm_id.
    """
    def bidder_fn(
        bidder_firm: FirmState,
        defaulted_list: list,
        other_survivors: list,
        industry_context: dict | None,
    ) -> dict | None:
        if not defaulted_list:
            return {"bids": []}
        from .personalities import get_company_name
        b_idx = int(bidder_firm.firm_id.split("_")[-1]) if "_" in bidder_firm.firm_id else 0
        ic = industry_context or {}
        ic_text = (ic.get("narrative") or "")[:1500]
        system = AUCTION_BIDDER_SYSTEM_PROMPT.format(
            bidder_company_name=get_company_name(b_idx),
            lots_summary=_format_lots_summary(defaulted_list, get_company_name),
            your_firm_summary=_format_firm_summary(bidder_firm),
            competitor_summary=_format_competitor_summary(other_survivors),
            industry_context=ic_text if ic_text else "(no scenario context)",
        )
        user = "Submit bids (or decline) for each lot. Output JSON only."
        try:
            return backend.complete_json(system, user)
        except Exception as e:
            # Wave ν+9 Bug H3: structured error rather than silent None.
            # See judge_fn for rationale.
            import traceback as _tb
            return {
                "_error": True,
                "_exception": f"{type(e).__name__}: {e}",
                "_traceback": _tb.format_exc()[:2000],
                "bids": [],
            }
    return bidder_fn


def _coerce_bid(v) -> float:
    """Tolerate '$X,XXX' style money strings."""
    if v is None:
        return 0.0
    if isinstance(v, (int, float)):
        return max(0.0, float(v))
    try:
        s = str(v).strip().replace("$", "").replace(",", "").replace("%", "")
        return max(0.0, float(s)) if s else 0.0
    except (TypeError, ValueError):
        return 0.0


def run_quarterly_auctions(
    defaulted_list: list,
    survivors: list,
    bidder_fns: dict,
    industry_context: dict | None,
    rng: random.Random,
    integration_friction: float = 0.6,
) -> list[dict]:
    """Wave ν linear-scaling auction: one LLM call per surviving firm
    resolves all defaulted-firm lots this quarter.

    Each survivor submits a `bids` list covering any lots they want.
    Per-lot winners are picked independently (highest bid wins).

    Returns a list of auction-event dicts, one per defaulted firm
    (regardless of whether it sold).

    Cash constraint: a survivor's total allocated cash across
    lots-they-win cannot exceed their cash on hand. If a bidder's
    winning bids collectively exceed their cash, lots are awarded in
    descending-bid order until cash runs out; remaining winning bids
    from that bidder are treated as withdrawn and the next-highest
    bidder on each remaining lot is picked instead.
    """
    if not defaulted_list or not survivors or not bidder_fns:
        return []

    # Step 1: collect per-lot bids via ONE LLM call per survivor
    # Shape after collection: per_lot_bids[target_id] = [
    #   {"bidder_id", "amount", "rationale"}, ...
    # ]
    per_lot_bids: dict[str, list[dict]] = {
        d.firm_id: [] for d in defaulted_list
    }
    valid_target_ids = {d.firm_id for d in defaulted_list}

    bidder_errors: list[str] = []
    for bidder in survivors:
        fn = bidder_fns.get(bidder.firm_id)
        if fn is None:
            continue
        others = [f for f in survivors if f.firm_id != bidder.firm_id]
        result = fn(bidder, defaulted_list, others, industry_context)
        if result is None:
            continue
        # Wave ν+9 Bug H3: track explicit LLM-failure markers so callers
        # can surface them rather than silently treating them as no-bid.
        if isinstance(result, dict) and result.get("_error"):
            bidder_errors.append(
                f"{bidder.firm_id}: {result.get('_exception', 'unknown error')}"
            )
            continue
        raw_bids = result.get("bids") or []
        if not isinstance(raw_bids, list):
            continue
        for entry in raw_bids:
            if not isinstance(entry, dict):
                continue
            target_id = str(entry.get("target_firm_id", "")).strip()
            if target_id not in valid_target_ids:
                continue
            amt = _coerce_bid(entry.get("bid_amount"))
            if amt <= 0:
                continue
            # Cap any single bid at bidder's cash
            amt = min(amt, bidder.cash)
            if amt <= 0:
                continue
            per_lot_bids[target_id].append({
                "bidder_id": bidder.firm_id,
                "amount": amt,
                "rationale": str(entry.get("rationale", ""))[:300],
            })

    # Step 2: resolve winners per lot, respecting per-bidder cash budget
    # Remaining-cash tracker so a bidder who wins lot A for $X can't
    # also win lot B for > cash-X.
    remaining_cash = {s.firm_id: s.cash for s in survivors}
    events: list[dict] = []

    # Sort lots by max bid (highest stakes resolve first so small
    # lots don't starve big lots of bidders' cash)
    def _lot_top(target_id):
        bids_l = per_lot_bids[target_id]
        return max((b["amount"] for b in bids_l), default=0.0)
    lot_order = sorted(
        valid_target_ids, key=lambda t: _lot_top(t), reverse=True,
    )

    defaulted_by_id = {d.firm_id: d for d in defaulted_list}
    for target_id in lot_order:
        lot_bids = per_lot_bids.get(target_id, [])
        if not lot_bids:
            events.append({
                "target_firm_id": target_id,
                "outcome": "no_bids",
                "bids": [],
                "winner_id": "",
                "winning_amount": 0.0,
            })
            continue

        # Highest bidder whose remaining cash covers their bid wins.
        # Process in descending order, first qualifying bidder wins.
        lot_bids_sorted = sorted(
            lot_bids, key=lambda b: b["amount"], reverse=True,
        )
        # Random tiebreak at the top
        top_amt = lot_bids_sorted[0]["amount"]
        top_ties = [b for b in lot_bids_sorted if b["amount"] == top_amt]
        if len(top_ties) > 1:
            rng.shuffle(top_ties)
            lot_bids_sorted = top_ties + [
                b for b in lot_bids_sorted if b["amount"] != top_amt
            ]

        winner = None
        for b in lot_bids_sorted:
            if remaining_cash.get(b["bidder_id"], 0) >= b["amount"]:
                winner = b
                break

        if winner is None:
            events.append({
                "target_firm_id": target_id,
                "outcome": "no_solvent_bidder",
                "bids": lot_bids,
                "winner_id": "",
                "winning_amount": 0.0,
            })
            continue

        remaining_cash[winner["bidder_id"]] -= winner["amount"]
        events.append({
            "target_firm_id": target_id,
            "outcome": "sold",
            "bids": lot_bids,
            "winner_id": winner["bidder_id"],
            "winning_amount": winner["amount"],
            "winner_rationale": winner["rationale"],
            "integration_friction": integration_friction,
            **({"bidder_errors": bidder_errors} if bidder_errors else {}),
        })

    return events


# Legacy alias preserved so any caller using the old single-lot name
# continues to work (returns the first event for that target).
def execute_auction(
    defaulted: FirmState,
    survivors: list,
    bidder_fns: dict,
    industry_context: dict | None,
    rng: random.Random,
    integration_friction: float = 0.6,
) -> dict | None:
    """Deprecated single-lot wrapper — delegates to run_quarterly_auctions."""
    events = run_quarterly_auctions(
        defaulted_list=[defaulted],
        survivors=survivors,
        bidder_fns=bidder_fns,
        industry_context=industry_context,
        rng=rng,
        integration_friction=integration_friction,
    )
    return events[0] if events else None


def apply_auction_result(
    state,
    defaulted: FirmState,
    auction_event: dict,
    integration_friction: float = 0.6,
) -> tuple[FirmState, FirmState]:
    """Apply an auction outcome to state:
      - Winner: pays cash, absorbs capability + brand (with friction),
        inherits PP&E + inventory + capacity.
      - Defaulted firm: assets stripped; proceeds distributed to creditors
        (LTD reduction) first, then PE pro-rata. Any residual recorded
        but typically zero.

    Returns (updated_winner, updated_defaulted) so caller can commit them
    back to state.firms.
    """
    if auction_event.get("outcome") != "sold":
        return None, defaulted

    winner_id = auction_event["winner_id"]
    amount = auction_event["winning_amount"]
    winner = state.firms.get(winner_id)
    if winner is None:
        return None, defaulted

    f = 1.0 - integration_friction  # fraction actually absorbed

    # Capability + brand: weighted additive uplift (not simple sum, not BS items)
    new_capability = min(100.0, winner.capability_stock + f * defaulted.capability_stock)
    new_brand = min(100.0, winner.brand_stock + f * defaulted.brand_stock)

    # Capacity: additive (not BS item)
    new_capacity = winner.capacity_units + defaulted.capacity_units

    # PP&E + inventory: transferred at book value
    ppe_net_transfer = defaulted.ppe_net
    inventory_transfer = defaulted.inventory_value
    assets_received_at_book = ppe_net_transfer + inventory_transfer

    # ── PURCHASE ACCOUNTING (mirrors GAAP ASC 805 like ma_agent) ────────
    # Winner pays `amount` cash, receives PP&E + inventory worth book value.
    # If amount > book: difference recorded as goodwill on winner's BS.
    # If amount < book: difference is a bargain-purchase gain to RE.
    # Without this the winner's BS broke (the v6 phase_A1_audit residuals).
    if amount >= assets_received_at_book:
        goodwill_added = amount - assets_received_at_book
        bargain_gain = 0.0
    else:
        goodwill_added = 0.0
        bargain_gain = assets_received_at_book - amount

    new_winner_cash = max(0.0, winner.cash - amount)

    updated_winner = winner.evolve(
        cash=new_winner_cash,
        capability_stock=new_capability,
        brand_stock=new_brand,
        capacity_units=new_capacity,
        ppe_gross=winner.ppe_gross + ppe_net_transfer,
        inventory_value=winner.inventory_value + inventory_transfer,
        goodwill=winner.goodwill + goodwill_added,
        retained_earnings=winner.retained_earnings + bargain_gain,
        acquired_firms=list(winner.acquired_firms or []) + [defaulted.firm_id],
        acquisition_integration_cost=(
            winner.acquisition_integration_cost
            + amount * integration_friction * 0.1
        ),
    )
    # BS check (winner): ΔA = -amount + ppe_net + inv + goodwill
    #                       = -amount + book + (amount - book) if amount>=book
    #                       = 0 ✓
    #                  or = -amount + book + 0 = bargain_gain (if amount<book)
    #                  ΔE = bargain_gain → balances ✓

    # Defaulted firm: assets stripped, sale proceeds ADDED to existing
    # cash (Wave ν+8 fix: previously the code wrote `cash=amount` which
    # overwrote any pre-default cash the firm was holding — that cash
    # would silently disappear, breaking the BS identity by exactly
    # `defaulted.cash`. After fix, total cash = pre-default cash + sale
    # proceeds, then the creditor waterfall pays down LTD from the
    # combined pool, then the revolver if any cash remains).
    # Gain/loss on sale = amount - book → adjust retained_earnings to
    # keep BS identity.
    sale_gain_loss = amount - assets_received_at_book

    # Wave ν+11 BS-violation fix:
    # The defaulted firm's PPE must be FULLY zeroed (gross AND accumulated
    # depreciation), not partially. Previous formulation:
    #
    #     ppe_gross = max(0, ppe_gross - ppe_net)
    #     accum_depreciation = max(0, accum_dep - (ppe_gross - ppe_net))
    #
    # silently retained `accum_depreciation` worth of phantom PPE because
    # `ppe_gross - ppe_net = accum_dep`, so the formulas reduce to:
    #     new_ppe_gross = accum_dep
    #     new_accum_dep = max(0, accum_dep - accum_dep) = 0
    #     new_ppe_net   = accum_dep − 0 = accum_dep   ← phantom PPE
    #
    # The winner correctly received `ppe_net_transfer` (full ppe_net), so
    # the industry net PPE grew by `accum_depreciation` every auction
    # (e.g. +$10.5M on firm_3 → +$80.5M cumulative residual through the
    # rest of run-2). All 362 phase_2_ipo BS-violation events in run-2
    # trace to this. The fix: zero both PPE fields outright. The book
    # value transferred to the winner remains `defaulted.ppe_net` (above);
    # nothing is left on the defaulted firm.
    updated_defaulted = defaulted.evolve(
        cash=defaulted.cash + amount,  # PRE-default cash retained + sale proceeds
        capability_stock=0.0,
        brand_stock=0.0,
        capacity_units=0,
        ppe_gross=0.0,
        accum_depreciation=0.0,
        inventory_value=0.0,
        retained_earnings=defaulted.retained_earnings + sale_gain_loss,
    )
    # BS check (defaulted, before waterfall):
    #   ΔA = +amount (cash added) - ppe_net (ppe gone) - inv (inv gone)
    #      = amount - book = sale_gain_loss
    #   ΔE = sale_gain_loss → balances ✓

    # Creditor waterfall: pay down LTD first, then revolver, from
    # whatever cash the defaulted firm now holds.
    cash_pool = updated_defaulted.cash
    pay_to_ltd = min(cash_pool, updated_defaulted.long_term_debt)
    cash_pool -= pay_to_ltd
    pay_to_revolver = min(cash_pool, updated_defaulted.revolver_balance)
    cash_pool -= pay_to_revolver
    updated_defaulted = updated_defaulted.evolve(
        cash=cash_pool,
        long_term_debt=max(0.0, updated_defaulted.long_term_debt - pay_to_ltd),
        revolver_balance=max(0.0, updated_defaulted.revolver_balance - pay_to_revolver),
    )

    return updated_winner, updated_defaulted
