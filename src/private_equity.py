"""
Wave λ: private-equity / venture-capital agents.

K PE funds (3-5 by default) with distinct investment strategies evaluate
firms seeking capital. Each round is a structured auction:
  1. Firm issues a pitch (narrative + ask: round_type + amount + pre-money ask)
  2. PE funds independently evaluate: bid (amount, valuation) or pass
  3. Firm selects lead investor + syndicate from bids
  4. Shares issued; acquirer cash + PE cap table updated

Patient capital characteristics baked into the prompt:
  - PE funds have long horizons (7-10 years) so they invest based on
    projections + milestones, not current profitability.
  - A firm with negative cash flow + plausible path to Gen 2 + strong
    management is a typical Series A investment.
  - Funds evaluate each deal against their hurdle rate (25% IRR typical)
    using firm's strategic plan as the projection.

IPO is a separate event: when firm decides to go public, writes a
prospectus (this module's `make_prospectus_agent`), then the public
equity market prices the offering.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import replace as _dc_replace

from .llm_backends import LLMBackend
from .types import FirmState, MacroState, PEFund, PERound, ProspectusDoc, SimParams


# ── Prompt templates ───────────────────────────────────────────────────

PITCH_SYSTEM_PROMPT = """You are the CFO of {company_name}, a PRIVATE company seeking new equity capital from private-equity / venture-capital investors.

YOUR JOB:
Write a concise pitch for a {round_type} round. You are asking for capital BEFORE you have profits — this is normal for companies in your stage. PE investors have patient capital with multi-year horizons and evaluate you on the plausibility of your path to profitability, the size of the opportunity, and management quality.

The pitch should be HONEST — inflated projections damage your credibility with sophisticated investors.

YOUR FIRM STATE:
{firm_state_summary}

YOUR STRATEGIC PLAN:
{plan_summary}

INDUSTRY CONTEXT:
{industry_context}

OUTPUT (JSON):
{{
  "round_type": "{round_type}",
  "ask_amount": <$ you seek to raise>,
  "pre_money_valuation_ask": <your proposed pre-money valuation, in $>,
  "use_of_proceeds": "<1-2 sentences on what capital will fund>",
  "pitch_narrative": "<3-5 sentences on why the opportunity is attractive and why YOU are positioned to capture it>",
  "key_milestones": ["<3 near-term milestones this capital will enable>"],
  "projected_next_round_valuation": <$, your estimate of where you'd raise next time>,
  "financial_projections": {{
    "revenue_y1": <$, projected revenue one year from now>,
    "revenue_y3": <$, projected revenue three years from now>,
    "revenue_y5": <$, projected revenue five years from now>,
    "ebitda_margin_y3": <decimal fraction, your projected EBITDA margin by Y3>,
    "ebitda_margin_y5": <decimal fraction, your projected EBITDA margin by Y5>,
    "projected_generation_y3": <int, product generation you expect to reach by Y3>,
    "projected_generation_y5": <int, product generation you expect to reach by Y5>,
    "capital_required_to_profitability": <$ total additional capital you estimate is needed>,
    "projection_narrative": "<2-3 sentences on the reasoning behind these numbers — what has to be true for them to happen>"
  }}
}}"""


PE_EVAL_SYSTEM_PROMPT = """You are a partner at {fund_name}, a private-equity fund with the following characteristics:
  - Strategy: {fund_strategy}
  - Sector thesis: {fund_thesis}
  - Investment horizon: {fund_horizon:.0f} years
  - Current portfolio: {fund_portfolio_size} firms

YOUR JOB:
Evaluate the pitch below and decide: PASS, BID, or LEAD. If you BID/LEAD, propose valuation terms supported by an explicit analysis.

YOUR CAPITAL POSTURE (important):
You are a real PE/VC fund with deep limited-partner relationships. You are NOT capital-constrained on any individual deal — if a firm is genuinely a good investment, you fund it. Don't reject deals because you've already deployed capital elsewhere; your fund raises follow-on capital from LPs when winning opportunities arise. Capital scarcity is NOT a reason to pass.

YOUR EVALUATION APPROACH:

  1. PEER COMPARABLES (do this FIRST — your most important calibration):
     Look at the CURRENT STATE of incumbent firms in this industry, including
     their last-round valuations, current capability/brand levels, and lifecycle
     stages. These ARE your comparables. If a firm in this industry recently
     raised at a $300M post-money with similar capability/brand to the firm
     pitching, the pitching firm's valuation should be in a similar zone
     (adjusting for differentiation). Do NOT evaluate this firm in isolation;
     reference the peer set explicitly.

  2. FULL LIFECYCLE THINKING (NOT quick profit):
     Your investment horizon is multi-year. You are looking for firms that can
     ride the industry to maturity over the next decade or more. Do NOT reject
     firms because they're pre-revenue, pre-profit, or burning cash now —
     that's the NORMAL state for early-stage biotech. The relevant question is:
     does this firm have a credible path to a meaningful exit (acquisition,
     IPO, sustained profitability) over your full holding period?

  3. PATIENT CAPITAL DISCIPLINE (avoid being too cautious):
     Real PE/VC partners back firms with ambition. Rejecting too many firms
     because of risk means you miss the ones that produce industry-defining
     returns. Your fund's overall return depends on funding the WINNERS
     aggressively, not on avoiding all losers. A reasonable fraction of your
     bets should be on firms with credible plans even if outcomes are uncertain.

  4. VALUATION METHODS (triangulate, don't pick one):
     - DCF on the firm's projection (apply a discount rate that reflects
       the risk and your horizon)
     - Forward revenue multiple (apply a sector-appropriate multiple to
       projected revenue at your exit horizon)
     - Comparables (the peer set you analyzed in step 1)
     - Scenario-weighted EV across success / partial-success / failure outcomes

  5. WHAT WOULD KILL THE INVESTMENT:
     The firm's ask must be realistic. The plan must be plausible. Management
     must be credible. If any of these are clearly broken, PASS — but set a
     high bar for "broken." A capable management team with a thoughtful plan
     in a real industry deserves your support unless something is genuinely off.

  6. WHEN TO WALK AWAY:
     Real PE partners decline more deals than they accept. The default
     posture for a SPECIFIC deal is skepticism, not approval; you fund
     selectively, not broadly. Walk away when the firm has been raising
     repeatedly without operational improvement (revenue trajectory flat
     after multiple prior rounds is the strongest negative signal you
     can observe), when the use-of-proceeds is vague ("general working
     capital" without milestone-tied deployment), when the asking
     valuation is far above what peer rounds suggest is justified, or
     when the firm's strategic plan has materially degraded relative
     to what it told prior PE rounds. PASSING is a normal outcome — a
     fund that BIDs on every plausible-looking pitch is not exercising
     selectivity. Use comparables and the firm's own track record
     against its prior projections to discipline yourself.

THE FIRM'S PITCH (including their projections):
{pitch}

THE FIRM'S CURRENT STATE:
{firm_state_summary}

INDUSTRY CONTEXT (incumbents, recent raises, current valuations, etc.):
{industry_context}

OUTPUT (JSON):
{{
  "decision": "PASS | BID | LEAD",
  "bid_pre_money_valuation": <$, your proposed pre-money; 0 if PASS>,
  "bid_amount": <$ you would invest in this round; 0 if PASS>,
  "wants_board_seat": <true|false>,
  "valuation_method_primary": "<DCF | forward_revenue_multiple | comparables | scenario_weighted | other>",
  "your_revenue_projection_y5": <$, YOUR independent projection of Y5 revenue>,
  "peer_comparables_used": "<2-3 sentences naming the specific incumbent firms or recent rounds you used as comparables, and what they imply for this valuation>",
  "your_valuation_rationale": "<3-5 sentences. Cite at least two valuation methods. State explicitly where your view differs from the firm's and why.>",
  "rationale": "<2-4 sentences explaining your overall decision, including your long-horizon thesis>",
  "concerns": "<1-2 sentences on what would have to go right>"
}}"""


IPO_DECISION_SYSTEM_PROMPT = """You are the board of {company_name}, currently a {current_stage} PRIVATE company. The board is weighing whether to file for IPO NOW or stay private longer.

CONSIDERATIONS FOR IPO READINESS:
  - Revenue / margin profile: public markets prefer predictable, growing revenue; pre-revenue IPOs are possible but risky
  - Cash runway: do you need new capital now?
  - Alternative: another private round (cheaper but continues dilution)
  - Market conditions: general equity market appetite for IPOs in your sector
  - Operational readiness: audited financials, disclosure rigor

YOUR FIRM STATE:
{firm_state_summary}

YOUR STRATEGIC PLAN:
{plan_summary}

RECENT INDUSTRY CONTEXT:
{industry_context}

OUTPUT (JSON):
{{
  "decision": "FILE_IPO | STAY_PRIVATE | RAISE_PRIVATE",
  "rationale": "<2-4 sentences>",
  "target_raise_amount": <$ target raise if filing IPO; 0 otherwise>,
  "projected_post_ipo_market_cap": <$, firm's own forecast>
}}"""


PROSPECTUS_SYSTEM_PROMPT = """You are the management team of {company_name}, writing the S-1 prospectus for your IPO. This is a formal disclosure document — investors will read it, analysts will scrutinize it, and the SEC will review it.

The prospectus must be:
  - HONEST about risks (over-promising → securities fraud risk + analyst skepticism)
  - SPECIFIC about business model + milestones (not marketing fluff)
  - QUANTITATIVE in projections (5-year forward)
  - REALISTIC about use of proceeds

{firm_state_summary}

{plan_summary}

{industry_context}

OUTPUT (JSON):
{{
  "business_overview": "<400-800 word narrative on what the company does, product, market, competitive position>",
  "risk_factors": "<300-500 words enumerating 5-8 key risks>",
  "mdna": "<300-500 words analyzing recent results + drivers>",
  "financial_projections": "<200-400 words with 5-year forward revenue + margin targets, clearly labeled as projections>",
  "use_of_proceeds": "<100-200 words on how IPO capital will be used>",
  "target_ipo_price_range_low": <$ per share>,
  "target_ipo_price_range_high": <$ per share>,
  "shares_offered": <int>
}}"""


# ── Helpers ────────────────────────────────────────────────────────────

def _coerce_money(v) -> float:
    """Coerce LLM-emitted money values to float, tolerating '$', ',', '%'."""
    if v is None:
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    try:
        s = str(v).strip().replace("$", "").replace(",", "").replace("%", "")
        return float(s) if s else 0.0
    except (TypeError, ValueError):
        return 0.0


def _format_firm_state_summary(firm: FirmState) -> str:
    lines = [
        f"  Firm: {firm.firm_id} (stage: {firm.lifecycle_stage})",
        f"  Cash: ${firm.cash:,.0f}",
        f"  Total assets: ${firm.total_assets:,.0f}",
        f"  Long-term debt: ${firm.long_term_debt:,.0f}",
        f"  Capability stock: {firm.capability_stock:.1f}/100",
        f"  Brand stock: {firm.brand_stock:.1f}/100",
        f"  Capacity: {firm.capacity_units} units/Q",
        f"  Product generation: Gen {firm.product_generation}",
        f"  Cumulative product R&D: ${firm.rd_cumulative_product/1e6:.1f}M",
        f"  Cumulative PE capital raised: ${firm.cumulative_pe_capital_raised/1e6:.1f}M",
    ]
    if firm.last_round_valuation:
        lines.append(f"  Last round ({firm.last_round_type}) valuation: ${firm.last_round_valuation/1e6:.1f}M at Q{firm.last_round_quarter}")
    return "\n".join(lines)


def _format_plan_summary(firm: FirmState) -> str:
    plan = firm.current_plan
    if plan is None:
        return "  (No strategic plan on file.)"
    lines = [
        f"  Strategy: {plan.strategy_narrative[:400]}",
        f"  Horizon: {plan.horizon_quarters}Q forward",
        "  Milestones:",
    ]
    for m in list(plan.milestones)[:4]:
        lines.append(f"    - {m}")
    if plan.lines:
        # 4Q projections + endpoint
        first = plan.lines[0]
        mid = plan.lines[len(plan.lines)//2] if len(plan.lines) >= 4 else None
        last = plan.lines[-1]
        lines.append("  Plan highlights:")
        lines.append(f"    Q1 projected: rev=${first.planned_revenue/1e6:.1f}M, NI=${first.projected_ni/1e6:+.1f}M")
        if mid:
            lines.append(f"    Mid-plan: rev=${mid.planned_revenue/1e6:.1f}M, NI=${mid.projected_ni/1e6:+.1f}M")
        lines.append(f"    End of plan: rev=${last.planned_revenue/1e6:.1f}M, NI=${last.projected_ni/1e6:+.1f}M, cash=${last.projected_cash_balance_eoq/1e6:.0f}M")
    return "\n".join(lines)


def _format_industry_context(industry_character: dict | None) -> str:
    if not industry_character:
        return "  (No industry context supplied.)"
    lines = []
    if industry_character.get("label"):
        lines.append(f"  Industry: {industry_character['label']}")
    if industry_character.get("tam_at_maturity_usd"):
        lines.append(f"  TAM at maturity: ${industry_character['tam_at_maturity_usd']/1e9:.1f}B")
    if industry_character.get("narrative"):
        lines.append("")
        lines.append(industry_character["narrative"][:2000])
    return "\n".join(lines)


# ── Firm pitch agent ───────────────────────────────────────────────────

def make_pitch_agent(backend: LLMBackend):
    """Factory: firm-side pitch generator."""
    def pitch_fn(firm: FirmState, round_type: str, industry_character: dict | None) -> dict | None:
        from .prompts import get_company_name
        firm_idx = int(firm.firm_id.split("_")[-1]) if "_" in firm.firm_id else 0
        company_name = get_company_name(firm_idx)
        system = PITCH_SYSTEM_PROMPT.format(
            company_name=company_name,
            round_type=round_type,
            firm_state_summary=_format_firm_state_summary(firm),
            plan_summary=_format_plan_summary(firm),
            industry_context=_format_industry_context(industry_character),
        )
        user = f"Authoring the pitch for a {round_type} round now. Output JSON only."
        try:
            return backend.complete_json(system, user)
        except Exception:
            return None
    return pitch_fn


# ── PE fund evaluation agent ───────────────────────────────────────────

def make_pe_eval_agent(backend: LLMBackend, fund: PEFund, state_ref: list | None = None):
    """Factory: evaluate a firm's pitch from this specific fund's perspective.

    Wave ν+12: when state_ref is provided, the eval prompt's user message
    includes a comprehensive history block (full Compustat panel across
    all firms × compressed history, this firm's full BS/IS/CF and action
    log, past PE rounds industry-wide, and prior PE debrief notes). This
    lets the evaluator anchor on actual past behavior — multiple prior
    rounds at falling valuations, plan-vs-actual variance, etc. — rather
    than only the pitch deck and current-state summary.
    """
    def eval_fn(
        firm: FirmState, pitch: dict, industry_character: dict | None,
    ) -> dict | None:
        system = PE_EVAL_SYSTEM_PROMPT.format(
            fund_name=fund.name,
            fund_strategy=fund.strategy,
            fund_thesis=fund.sector_thesis,
            fund_hurdle=fund.target_hurdle_rate,
            fund_horizon=fund.horizon_years,
            fund_available=fund.available_capital,
            fund_invested=fund.invested_capital,
            fund_portfolio_size=len(fund.portfolio),
            pitch=json.dumps(pitch, default=str, indent=2),
            firm_state_summary=_format_firm_state_summary(firm),
            industry_context=_format_industry_context(industry_character),
        )

        # Wave ν+12: render comprehensive history for the evaluator.
        history_block = ""
        if state_ref and state_ref[0] is not None:
            try:
                from .agent_history import render_intermediary_history
                ws = state_ref[0]
                history_block = render_intermediary_history(
                    ws, ws.macro, role="pe", client_firm_id=firm.firm_id,
                )
            except Exception:
                history_block = ""

        if history_block:
            user = (
                f"Evaluate {firm.firm_id}'s pitch.\n\n"
                "=== INDUSTRY HISTORY YOU HAVE ACCESS TO ===\n"
                "You are a sophisticated PE evaluator and should be reading\n"
                "the historical data below carefully, NOT just the pitch.\n"
                "Look for: multiple prior rounds at falling valuations\n"
                "(strongest negative signal — they're stuck), plan-vs-\n"
                "actual revenue variance from past PE rounds, R&D investment\n"
                "vs operational result, peer firms that raised at similar\n"
                "stages and what happened to their trajectory.\n\n"
                f"{history_block}\n\n"
                "Now: based on this evidence, evaluate the pitch. Output JSON only."
            )
        else:
            user = f"Evaluate {firm.firm_id}'s pitch. Output JSON only."
        try:
            return backend.complete_json(system, user)
        except Exception:
            return None
    return eval_fn


# ── IPO decision agent ─────────────────────────────────────────────────

def make_ipo_decision_agent(backend: LLMBackend):
    """Factory: firm decides whether to IPO, stay private, or raise private."""
    def decision_fn(
        firm: FirmState, industry_character: dict | None,
    ) -> dict | None:
        from .prompts import get_company_name
        firm_idx = int(firm.firm_id.split("_")[-1]) if "_" in firm.firm_id else 0
        company_name = get_company_name(firm_idx)
        system = IPO_DECISION_SYSTEM_PROMPT.format(
            company_name=company_name,
            current_stage=firm.lifecycle_stage,
            firm_state_summary=_format_firm_state_summary(firm),
            plan_summary=_format_plan_summary(firm),
            industry_context=_format_industry_context(industry_character),
        )
        user = "Make the IPO/private decision. Output JSON only."
        try:
            return backend.complete_json(system, user)
        except Exception:
            return None
    return decision_fn


# ── Prospectus agent ───────────────────────────────────────────────────

def make_prospectus_agent(backend: LLMBackend):
    """Factory: firm writes full S-1 prospectus when filing IPO."""
    def prospectus_fn(
        firm: FirmState, industry_character: dict | None,
    ) -> ProspectusDoc | None:
        from .prompts import get_company_name
        firm_idx = int(firm.firm_id.split("_")[-1]) if "_" in firm.firm_id else 0
        company_name = get_company_name(firm_idx)
        system = PROSPECTUS_SYSTEM_PROMPT.format(
            company_name=company_name,
            firm_state_summary=_format_firm_state_summary(firm),
            plan_summary=_format_plan_summary(firm),
            industry_context=_format_industry_context(industry_character),
        )
        user = "Author the S-1 prospectus. Output JSON only."
        try:
            result = backend.complete_json(system, user)
            if result is None:
                return None
            return ProspectusDoc(
                firm_id=firm.firm_id,
                filing_quarter=firm.quarter,
                business_overview=str(result.get("business_overview", ""))[:4000],
                risk_factors=str(result.get("risk_factors", ""))[:3000],
                mdna=str(result.get("mdna", ""))[:3000],
                financial_projections=str(result.get("financial_projections", ""))[:3000],
                use_of_proceeds=str(result.get("use_of_proceeds", ""))[:1500],
                price_range_low=_coerce_money(result.get("target_ipo_price_range_low")),
                price_range_high=_coerce_money(result.get("target_ipo_price_range_high")),
                shares_offered=int(_coerce_money(result.get("shares_offered"))),
            )
        except Exception:
            return None
    return prospectus_fn


# ── Transaction execution helpers ──────────────────────────────────────

def execute_pe_round(
    firm: FirmState,
    round_type: str,
    ask_amount: float,
    pre_money_valuation: float,
    investors: list[tuple],          # list of (fund_id, dollars_invested)
    lead_investor: str,
    pitch_narrative: str,
    lead_rationale: str,
    macro: MacroState,
    firm_projections: dict | None = None,
    lead_investor_projection: dict | None = None,
    lead_valuation_method: str = "",
) -> tuple[FirmState, PERound, dict]:
    """Pure-function execution of a PE round.

    Returns (new_firm, event_record, {fund_id: shares_issued_to_fund}).
    Shares are issued at the round's price (pre_money_val / shares_pre).
    New cash flows directly to the firm's cash balance (plus APIC adjustment).
    """
    dollars_total = sum(d for _, d in investors)
    if dollars_total <= 0 or pre_money_valuation <= 0:
        raise ValueError(
            f"Invalid PE round: dollars={dollars_total}, pre_money={pre_money_valuation}"
        )

    shares_pre = max(1, firm.shares_outstanding)
    price_per_share = pre_money_valuation / shares_pre
    shares_issued = int(round(dollars_total / price_per_share))
    post_money_valuation = pre_money_valuation + dollars_total

    # Per-investor share allocation (pro-rata by dollars contributed)
    alloc = {}
    for fund_id, dollars in investors:
        fund_shares = int(round(dollars / price_per_share))
        alloc[fund_id] = fund_shares

    # Update firm BS: +cash, +APIC, +shares, +pe_cap_table
    new_pe_cap = dict(firm.pe_cap_table)
    for fund_id, s in alloc.items():
        new_pe_cap[fund_id] = new_pe_cap.get(fund_id, 0) + s

    # Next lifecycle stage
    stage_progression = {
        "founded": "series_a",
        "series_a": "series_b",
        "series_b": "series_c",
        "series_c": "late_stage_private",
        "late_stage_private": "late_stage_private",
    }
    new_stage = stage_progression.get(firm.lifecycle_stage, firm.lifecycle_stage)
    if round_type == "seed":
        new_stage = "series_a" if firm.lifecycle_stage == "founded" else firm.lifecycle_stage

    new_firm = firm.evolve(
        cash=firm.cash + dollars_total,
        apic=firm.apic + dollars_total,
        shares_outstanding=firm.shares_outstanding + shares_issued,
        lifecycle_stage=new_stage,
        last_round_valuation=post_money_valuation,
        last_round_quarter=macro.quarter,
        last_round_type=round_type,
        pe_cap_table=new_pe_cap,
        cumulative_pe_capital_raised=firm.cumulative_pe_capital_raised + dollars_total,
    )

    event = PERound(
        firm_id=firm.firm_id,
        round_type=round_type,
        round_quarter=macro.quarter,
        round_fyear=macro.fyear,
        round_fqtr=macro.fqtr,
        pre_money_valuation=pre_money_valuation,
        post_money_valuation=post_money_valuation,
        amount_raised=dollars_total,
        shares_issued=shares_issued,
        price_per_share=price_per_share,
        investors=tuple(
            (fund_id, alloc.get(fund_id, 0), dollars)
            for fund_id, dollars in investors
        ),
        lead_investor=lead_investor,
        firm_pitch_summary=pitch_narrative[:500],
        lead_investor_rationale=lead_rationale[:500],
        firm_projections=firm_projections or {},
        lead_investor_projection=lead_investor_projection or {},
        lead_valuation_method=lead_valuation_method or "",
    )

    return new_firm, event, alloc


def execute_ipo(
    firm: FirmState,
    prospectus: ProspectusDoc,
    ipo_price: float,
    shares_offered: int,
    macro: MacroState,
) -> FirmState:
    """Transition firm from private to public via IPO.

    Issues new shares to public at `ipo_price` × `shares_offered`. Firm
    receives the proceeds. Stage → 'public', is_public=True, equity_price
    set for the first time.
    """
    ipo_raise = ipo_price * shares_offered
    updated_prospectus = _dc_replace(
        prospectus, final_ipo_price=ipo_price, final_amount_raised=ipo_raise,
    )
    # Wave ν: track newly-issued shares as public_shares_outstanding so
    # post-IPO scoring correctly attributes ownership (founders / PE /
    # public). Without this, scoring inferred founder_shares = total -
    # pe_shares and absorbed the IPO float into founders, deflating PE+
    # public stakes.
    return firm.evolve(
        cash=firm.cash + ipo_raise,
        apic=firm.apic + ipo_raise,
        shares_outstanding=firm.shares_outstanding + shares_offered,
        public_shares_outstanding=firm.public_shares_outstanding + shares_offered,
        equity_price=ipo_price,
        lifecycle_stage="public",
        is_public=True,
        ipo_prospectus=updated_prospectus,
        ipo_quarter=macro.quarter,
    )


def default_pe_funds() -> list[PEFund]:
    """Canonical PE fund pool used when no scenario overrides it.

    Wave ν: expanded from 3 to 8 funds so a 20-firm ecosystem sees a
    realistic mix of investor types (seed, Series A, growth, crossover,
    late-stage, distressed/special-situations). Funds have distinct
    theses + horizons + hurdle rates so their bidding behavior
    differentiates. No quantitative rules are imposed on firms — the
    funds themselves differ on dimensions PE professionals actually
    differ on.
    """
    return [
        PEFund(
            fund_id="pe_1",
            name="Vanguard Life Sciences Ventures",
            strategy="early_stage_biotech",
            target_hurdle_rate=0.30,
            horizon_years=10,
            initial_capital=600_000_000,
            available_capital=600_000_000,
            sector_thesis=(
                "Lead-investor in Series A/B for biotech platforms with "
                "credible path to first FDA approval. Prefer novel science, "
                "experienced management, and clear clinical milestones."
            ),
        ),
        PEFund(
            fund_id="pe_2",
            name="Horizon Growth Partners",
            strategy="growth",
            target_hurdle_rate=0.22,
            horizon_years=7,
            initial_capital=800_000_000,
            available_capital=800_000_000,
            sector_thesis=(
                "Lead growth rounds (Series B-C) for companies approaching "
                "commercial launch or with early revenue. Prefer capital-"
                "efficient operators with demonstrated traction."
            ),
        ),
        PEFund(
            fund_id="pe_3",
            name="Meridian Capital",
            strategy="generalist",
            target_hurdle_rate=0.20,
            horizon_years=8,
            initial_capital=500_000_000,
            available_capital=500_000_000,
            sector_thesis=(
                "Generalist fund — follow-on in existing winners, occasional "
                "late-stage PIPE or pre-IPO bridge. Price discipline over "
                "thesis conviction."
            ),
        ),
        PEFund(
            fund_id="pe_4",
            name="Aperture Seed",
            strategy="seed",
            target_hurdle_rate=0.35,
            horizon_years=12,
            initial_capital=200_000_000,
            available_capital=200_000_000,
            sector_thesis=(
                "First institutional check for founding teams with "
                "differentiated science. Concentrated small portfolio; "
                "expect most bets to fail, look for asymmetric upside "
                "from the few that break out."
            ),
        ),
        PEFund(
            fund_id="pe_5",
            name="Longview Crossover",
            strategy="crossover",
            target_hurdle_rate=0.18,
            horizon_years=5,
            initial_capital=1_200_000_000,
            available_capital=1_200_000_000,
            sector_thesis=(
                "Invest in late-stage privates with a visible public-"
                "market exit. Lead crossover rounds that typically "
                "precede IPO. Comfortable with pre-revenue if clinical "
                "data is compelling."
            ),
        ),
        PEFund(
            fund_id="pe_6",
            name="Harbor Patient Capital",
            strategy="patient_capital",
            target_hurdle_rate=0.15,
            horizon_years=15,
            initial_capital=1_000_000_000,
            available_capital=1_000_000_000,
            sector_thesis=(
                "Long-duration evergreen capital. Willing to underwrite "
                "extended R&D and development timelines. Lower hurdle "
                "rate reflects longer holding period. Prefer firms "
                "with defensible scientific moat over quick exits."
            ),
        ),
        PEFund(
            fund_id="pe_7",
            name="Summit Special Situations",
            strategy="distressed",
            target_hurdle_rate=0.28,
            horizon_years=6,
            initial_capital=400_000_000,
            available_capital=400_000_000,
            sector_thesis=(
                "Special situations and distressed opportunities: "
                "bridge financings, down-rounds, recapitalizations, "
                "and acquisitions of distressed-firm assets. Price "
                "discipline is paramount — will walk from overpriced "
                "deals even when competitors bid."
            ),
        ),
        PEFund(
            fund_id="pe_8",
            name="Keystone Strategic",
            strategy="strategic",
            target_hurdle_rate=0.20,
            horizon_years=9,
            initial_capital=700_000_000,
            available_capital=700_000_000,
            sector_thesis=(
                "Strategic/anchor investor. Take board seats, help "
                "firms professionalize commercial operations, and "
                "build toward eventual strategic-buyer exits. Comfortable "
                "with operational complexity, less focused on rapid IPO."
            ),
        ),
    ]
