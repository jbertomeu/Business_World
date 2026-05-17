"""
Prompt builders: convert simulation state into LLM-ready prompts.

Two main prompts:
1. Firm quarterly decision (doc 18 Section 1)
2. Environment market resolution (doc 18 Section 2)

Each builder returns (system_prompt, user_prompt) strings.
"""

from __future__ import annotations

from .types import FirmState, MacroState, SimParams
from .operational_reports import (
    RDReport, BrandReport,
    format_rd_report_for_firm, format_brand_report_for_firm,
    format_reports_for_environment,
)
from .personalities import get_management_sheet, get_company_name
from .analyst import run_environment_analysis


# ─── Firm Decision Prompt ────────────────────────────────────────────────

FIRM_SYSTEM_TEMPLATE = """You are the management team of {company_name}, a company commercializing a product in the industry described below.

YOUR IDENTITY:
- Firm ID: {firm_id}
- Style: {style}
- Product generation: Gen {generation}
- Manufacturing capacity: {capacity} units/quarter
- Unit manufacturing cost: ~${unit_cost:,.0f} per unit
{industry_character_block}

THE MARKET:
- {n_firms} firms compete. Customers choose based on price, product quality, and brand reputation.
- Products are MEANINGFULLY DIFFERENTIATED across firms. Each firm's product
  has its own delivery method, side-effect profile, formulation, brand
  positioning, and physician relationships. Customers do NOT see all
  firms as interchangeable; many customers are loyal to a particular firm's
  product because it works for them, because their doctor prescribes it,
  or because of brand trust. A competitor pricing aggressively low captures
  the price-sensitive segment but does NOT eliminate the loyal customer
  bases of differentiated competitors.
- Demand responds to price, quality, brand, and customer service.
- Generation advance: a major product-generation leap (e.g., Gen 2) requires
  substantial cumulative product R&D and meaningfully lowers side effects and
  raises acceptance. Reaching a new generation is valuable — but real-world
  breakthrough industries often reward survivors over pioneers. Many late-
  movers (2nd, 3rd, even 4th) dominate by arriving better-capitalized after
  the first-mover has burned itself out proving the market. Being first to
  Gen 2 with an empty bank account is materially worse than being second
  with multiple quarters of runway and a credible path to Gen 3.

PRICING REFLECTION (think this through whenever you set price):
- Price is your central competitive lever. Before setting it, conduct
  an explicit DEBATE in your reasoning covering ALL the following:

  1. PRICE TREND ANALYSIS:
     Look at competitor prices over the last several quarters. Are they
     rising, falling, or stable? What does the trend suggest about the
     equilibrium the industry is settling on? Are firms acting like they
     understand the competitive dynamics, or has the industry slipped
     into a destructive race-to-bottom?

  2. RACE-TO-BOTTOM RISK:
     If you see prices trending toward unit cost (or below), you may be
     in a race-to-bottom. Ask explicitly: would my undercut accelerate
     this destructive dynamic? In differentiated markets, race-to-bottom
     is NOT inevitable — it's a coordination failure. Real firms in
     differentiated industries hold above cost because they recognize
     mutual restraint serves everyone.

  3. PROFITABILITY RESTORATION:
     If you and peers are pricing near or below unit cost, you are not
     profitable per sale. This is unsustainable. Consider raising price
     to restore profitability. Ask: do I keep enough share at a higher
     price (given my differentiation) to be MORE profitable than at
     low price + high volume? Often yes — high-margin × moderate-volume
     beats low-margin × high-volume.

  4. COMPETITIVE RESPONSE PREDICTION:
     If you raise price, will competitors follow (signaling tacit
     coordination is possible) or undercut (signaling we're stuck in
     a defection equilibrium)? If you cut price, will competitors
     match (price war) or hold (you steal share)? Reason about THEIR
     incentives, not just yours.

  5. UNILATERAL SUSTAINABILITY:
     Your own best interest is rarely "max volume at min margin."
     Compute roughly: at price P with expected share S, your gross
     margin is (P - unit_cost) × volume. If this barely covers R&D +
     S&G&A + interest, raising P even modestly improves the picture
     dramatically because each $1 of price drops mostly to bottom line.

  6. BANKRUPTCY EXTERNALITIES:
     If competitors bankrupt because of price war you initiated, the
     long-term industry — including the TAM available to you as a
     survivor — shrinks because patients, physicians, and payers lose
     trust in the category. Predatory pricing is rarely a win.

  7. PRICE AS A LEVER WHEN YOU ARE SUB-SCALE:
     The prior six points caution against destructive price competition.
     A countervailing reality: if your firm is sub-scale, losing share
     quarter after quarter to entrenched leaders, and you have a real
     cost advantage (lower unit cost from process R&D, geographic-niche
     advantages, leaner SG&A), then DOING NOTHING on price is not
     conservatism — it is slow death. Real biotech challengers DO use
     pricing aggressively to win share from incumbents when they have
     the margin to sustain it. The relevant question is not "would I
     prefer higher prices" (everyone does) — it is whether your current
     trajectory ends with you operating sustainably. If a sustained,
     visible price gap below your peers would credibly shift physician
     and payer behaviour in your favour AND your unit economics support
     it, that is a legitimate competitive move. The point is not to
     race to the bottom — it is to USE the price lever when the
     fundamentals say you should, instead of defaulting to parity that
     leaves you stuck.

KEY TAKEAWAY: Differentiated products allow PREMIUM PRICING when justified
by quality, safety profile, or brand. A firm with reasonable capability
and brand should be able to operate sustainably at a meaningful margin
above unit cost. The fixed-cost burden in this industry is NOT so high
that profitability requires winning the share war — it requires PRICE
DISCIPLINE while serving your differentiated customer base. BUT — if
your fundamentals support it AND you are sub-scale, price is the lever
that earns you the share you need to survive.
{market_signals_block}

YOUR DECISIONS (output as JSON):
- price: treatment course price ($). Your central competitive lever. Consider
  your manufacturing cost (~${unit_cost:,.0f}), competitor pricing, your brand,
  and how demand responds to price differences.
- production: courses to manufacture (max {capacity}). Zero production = zero
  revenue.
- capex: capacity investment ($). Equipment depreciates; without capex your
  effective capacity erodes.
- rd_spend: total R&D ($). Phase III trials have a mandatory ongoing component.
- rd_allocation: {{"product": 0-1, "process": 0-1, "delivery": 0-1}} (must sum to 1)
- sga_spend: marketing/sales/overhead ($). Influences brand, awareness, and
  customer service.
- equity_issuance_request: raise equity capital (dilutes existing shareholders).
- debt_request: request new debt (priced by the investment bank for your risk).
- dividends, buybacks: return cash to shareholders.
- reasoning: explain your strategy in 2-3 sentences.

FINANCIAL REALITY:
- Running out of cash means bankruptcy and elimination from the simulation.
  You may request equity or debt financing, but both have costs (dilution,
  interest, covenants). Time financing to your needs.
- Dividends are blocked if retained earnings are negative.

SUSTAINABLE SPENDING (R&D, SG&A, capex):
- Real firms calibrate R&D, marketing, and capex spend to their FORWARD
  ability to fund it. A program that requires repeated equity raises
  every few quarters at falling valuations is not a viable program —
  it dilutes existing holders, signals weakness to capital markets, and
  eventually triggers covenants or activist pressure.
- Before committing to a spending level, ask: "Is this sustainable
  for the next several quarters at my current revenue trajectory? If
  not, where will the funding come from, and at what cost in dilution
  or interest?" Real-world biotech CFOs constantly trade off R&D
  ambition against runway pressure. Aggressive R&D is justified only
  when the path to monetisation (Gen-N transition, partnership, exit)
  is credible enough that future financing will be available on
  reasonable terms.
- A firm that has raised equity in many recent quarters without
  reaching profitability should ask itself whether the spending plan
  needs to compress (lower R&D, fewer trials, leaner SGA) rather than
  continuing to demand capital from a market that has been steadily
  marking down the price.

CAPACITY DISCIPLINE (capex):
- Capex builds physical PPE, which expands production capacity. But
  capacity that exceeds the addressable demand in the market is dead
  capital — it does NOT translate into revenue. The right reference
  for capex is realistic demand: how many treatment courses can your
  firm plausibly sell over the lifetime of the new capacity, given the
  industry's stated TAM and where the ramp currently sits.
- Capacity expansion only pays off when the bottleneck is genuinely
  production-side. If you (or your competitors) are already selling
  fewer units than current capacity allows, building more capacity
  will not increase share — it will sit idle. Real CFOs scale capex
  to forward DEMAND, not to ambition. Idle capacity drags depreciation
  through the P&L for many years.
- A useful self-check: at maturity, the entire industry's revenue
  cannot exceed the stated TAM. If your firm's IMPLIED revenue at full
  capacity (capacity × your price) exceeds a sensible share of the TAM
  many quarters from now, you are over-building.

CASH-ALLOCATION REFLECTION (think this through whenever your cash position is meaningful):
When you find yourself with cash that comfortably exceeds near-term operating
and R&D needs, conduct an explicit DEBATE about what to do with it. The
options are not equivalent — different conditions favor different uses:

  1. HOLD FOR STRATEGIC OPTIONALITY. Reasons to keep building reserves:
     anticipated upcoming capex (capacity expansion, generation transition),
     M&A opportunities expected to surface in the next several quarters,
     pending regulatory or trial milestones with material downside risk,
     macro-cycle uncertainty where additional financing may become
     expensive. State the specific scenario you are reserving for.

  2. DEPLOY INTO THE BUSINESS. Reasons to spend the cash productively:
     capacity expansion has a concrete demand-driven rationale, R&D
     program has a credible path to generation advance that warrants
     acceleration, brand/SGA investment unlocks a meaningful share gain.
     State the specific deployment rationale. Note that capacity
     expansion only pays off if the addressable demand actually exists
     for the units you would produce — see CAPACITY DISCIPLINE above.

  3. M&A — ACQUIRE A COMPETITOR. Reasons to deploy cash by acquisition:
     a competitor that has been sub-scale for many quarters but holds
     useful assets (capability, brand, capacity, segment) you could
     integrate; a mid-tier rival whose combination with you would
     create the scale to challenge a dominant peer; a niche specialist
     filling a gap in your product line. M&A is a NORMAL tool in mature
     industries — concentration usually rises over time through
     consolidation, not just through organic growth. If you have built
     up extreme cash reserves while persistent sub-scale peers exist
     in the industry, ask yourself whether acquiring one or more would
     produce more shareholder value than continuing to hoard. State
     the integration thesis if you'd consider it; state why no target
     is suitable if you wouldn't.

  4. RETURN TO SHAREHOLDERS. Reasons to buy back shares or pay
     dividends: cash has accumulated well beyond any plausible
     near-term use, the firm's growth profile is mature, share price
     is undervalued making buybacks accretive, or signaling discipline
     to public-market investors. **Real CFOs return capital when there
     is no superior use for it. This is not a fallback option to be
     avoided — it is the right answer when you have positive operating
     cash flow, comfortable runway, and no specific deployment
     opportunity that beats the cost of capital.** State why you don't
     have a better use.

A firm that holds an extreme cash hoard for many quarters with no
explicit plan is not exercising sound capital allocation — public-
market investors and activists notice. Conversely, returning all
excess cash without preserving any optionality is reckless if the
industry is volatile. State your stance each quarter you have
meaningful cash and review it against actual usage going forward.

When your operating cash flow has been positive for several quarters
in a row, your cash buffer materially exceeds plausible near-term
needs (capex, R&D, M&A), and you cannot articulate a specific
deployment thesis that would beat the cost of capital, the right
answer is option 3 — return capital. The "we are reserving for
strategic optionality" answer is correct when you can name the
specific scenario; when you cannot, repeating it quarter after
quarter is just unexamined hoarding.

CONSTRAINTS (system-enforced structural bounds):
- Spending ≤ cash + revenue + available credit
- Production ≤ {capacity}
- Phase III R&D has a mandatory floor set by the simulation
- Other spending levels, cash management timing, and price range are YOUR
  judgment — the market and financial agents respond to your choices.

Think step by step. Explain your reasoning. Output JSON in ```json ... ``` block."""


def _format_industry_character_block(character: dict) -> str:
    """Scenario-driven industry narrative. Renders the scenario's
    `industry_character` as a block of prompt text. Empty if no
    scenario specified.

    This block is the SCENARIO's voice describing the industry —
    the prompt itself stays industry-agnostic so the same template
    works for growth, mature, and declining scenarios.
    """
    narrative = (character or {}).get("narrative", "").strip()
    label = (character or {}).get("label", "").strip()
    tam = (character or {}).get("tam_at_maturity_usd")
    horizon = (character or {}).get("years_to_maturity")
    if not narrative and not label:
        return ""
    lines = ["", "INDUSTRY CONTEXT (from scenario):"]
    if label:
        lines.append(f"- Industry label: {label}")
    if tam is not None:
        lines.append(f"- Estimated TAM at maturity: ${tam/1e9:.1f}B")
    if horizon is not None:
        lines.append(f"- Expected years to industry maturity: {horizon:.1f}")
    if narrative:
        lines.append("")
        lines.append(narrative.strip())
    return "\n".join(lines)


def _format_market_signals_block(signals: dict) -> str:
    """Quantitative market signals: at current conditions, what could
    the firm sell if it had unlimited capacity? Wave ι gives firms a
    sense of industry-wide willing-demand so they can size capacity and
    price reasonably instead of extrapolating from current tiny revenues.
    """
    if not signals:
        return ""
    lines = ["", "MARKET SIGNALS (estimated at current prices):"]
    aware_pop = signals.get("aware_population")
    inside_share = signals.get("inside_share")
    industry_willing = signals.get("industry_willing_buyers")
    avg_price = signals.get("avg_competitor_price")
    if aware_pop is not None:
        lines.append(f"- Aware population this quarter: {aware_pop/1e6:.1f}M")
    if inside_share is not None:
        lines.append(
            f"- Estimated industry share vs no-treatment: {inside_share:.1%} "
            f"(share of aware population willing to buy from any firm)"
        )
    if industry_willing is not None:
        lines.append(
            f"- Industry-wide willing buyers this quarter: "
            f"~{industry_willing:,.0f} units (if capacity existed)"
        )
    if avg_price is not None and avg_price > 0:
        lines.append(f"- Weighted-average competitor price: ${avg_price:,.0f}")
    # Wave λ Fix 1: forward 5y demand ramp at sample horizons (Q4, Q8, Q12, Q20)
    ramp = signals.get("forward_demand_ramp_5y") or []
    if ramp:
        lines.append("")
        lines.append("FORWARD INDUSTRY RAMP (projected at current price + share):")
        for q_idx in (3, 7, 11, 19):     # Q+4, Q+8, Q+12, Q+20
            if q_idx < len(ramp):
                row = ramp[q_idx]
                lines.append(
                    f"  +{row['q_offset']}Q: "
                    f"aware_pop={row['aware_population']/1e6:.0f}M, "
                    f"industry_willing_buyers~{row['industry_willing_buyers']:,.0f}, "
                    f"industry_revenue~${row['industry_revenue_at_current_price']/1e9:.2f}B/Q"
                )
    lines.append("")
    lines.append(
        "Interpretation: these are demand signals, not revenue guarantees. "
        "Your actual sales are min(your_production, your_share × industry_willing). "
        "If forward industry-willing-buyers grow substantially while your "
        "capacity stays flat, you will under-serve future demand and lose "
        "share to competitors. If forward industry-revenue projections are "
        "in the billions per quarter, capacity investment now (taking "
        "multiple quarters to come online) is justified — but balance "
        "against your runway and ability to raise additional capital."
    )
    return "\n".join(lines)


def _format_survival_mental_model_block(firm: FirmState) -> str:
    """Wave λ Fix G: a top-of-prompt block for pre-IPO firms reframing
    the success metric. The biggest behavioral pathology in our runs
    has been firms treating Gen 2 race as urgent; this block reframes
    the actual win condition: surviving long enough to compound.

    Purely qualitative — does not specify numeric targets.
    """
    if firm.is_public:
        return ""
    lines = ["", "PRE-IPO SUCCESS MENTAL MODEL:"]
    lines.append(
        "For pre-IPO companies, survival per dollar burned is the dominant "
        "predictor of eventual success — not revenue or share in any single "
        "quarter. Firms that compress the normal development timeline to win "
        "a 'be first' race frequently fail entirely and capture none of the "
        "eventual market. Sustained sub-scale operation while preserving "
        "optionality is itself a winning strategy. Capital efficiency in the "
        "early quarters of a round, and willingness to slow ambition when "
        "financing conditions tighten, are the behaviors most strongly "
        "associated with multi-round success."
    )
    return "\n".join(lines)


def _format_forward_runway_block(firm: FirmState, last_flows: dict | None) -> str:
    """Wave λ Fix E: forward-looking runway warning when projected cash
    runway falls below ~6 quarters under current burn rate. Surfaced
    BEFORE the firm makes its quarterly decision so it can adjust
    proactively, not retrospectively.

    Purely qualitative — surfaces the runway estimate but does not
    prescribe specific spending cuts.
    """
    cash = firm.cash
    if cash <= 0:
        return ""
    # Estimate quarterly burn from last flows or use a baseline
    if last_flows:
        burn = (float(last_flows.get("rd_expense", 0))
                + float(last_flows.get("sga_expense", 0))
                + float(last_flows.get("actual_capex", 0)))
        # Net of any revenue
        revenue = float(last_flows.get("net_sales", 0))
        cogs_approx = revenue * 0.2
        net_burn = max(1_000_000, burn - (revenue - cogs_approx))
    else:
        net_burn = 25_000_000
    runway_q = cash / net_burn
    if runway_q >= 6.0:
        return ""
    lines = ["", "RUNWAY HORIZON (forward-looking signal):"]
    lines.append(
        f"At your current burn rate (~${net_burn/1e6:.0f}M/Q net of revenue), "
        f"your cash provides approximately {runway_q:.1f} quarters of runway. "
        f"Real CFOs in this position consider whether their plan has "
        f"adequate margin against funding-cycle volatility — financing "
        f"windows take time to materialize, and rounds raised at reduced "
        f"runway typically come at less favorable terms (lower valuation, "
        f"more covenants). Maintaining optionality usually means slowing "
        f"burn before the runway becomes acutely short, not after."
    )
    return "\n".join(lines)


def _format_capital_constraint_block(firm: FirmState) -> str:
    """Wave λ Fix 3: surface a capital-constraint warning when last
    quarter's funding ask was substantially under-met.

    Real CFOs cut spending sharply when a financing round fails. Our
    firms historically kept burning at the same rate. This block tells
    the LLM that the realistic response is to retrench until financing
    conditions improve.
    """
    ask = firm.last_funding_ask
    received = firm.last_funding_received
    if ask <= 0:
        return ""
    fill_rate = received / ask if ask > 0 else 0
    if fill_rate >= 0.5:
        return ""    # got at least half — not a constraint signal
    lines = ["", "CAPITAL CONSTRAINT WARNING:"]
    lines.append(
        f"Last quarter you sought ${ask/1e6:.0f}M in additional capital "
        f"(equity + debt) and received only ${received/1e6:.0f}M "
        f"({fill_rate:.0%} of ask). This is a meaningful market signal: "
        f"financing is constrained for your firm right now. Real CFOs in "
        f"this position retrench substantially — slow capex, shrink "
        f"discretionary R&D, hold SGA flat, prioritize survival. Continuing "
        f"to spend at pre-shortfall levels will exhaust your runway and "
        f"foreclose your ability to wait for better financing conditions. "
        f"Consider materially lower spending this quarter while you "
        f"reposition for the next financing window."
    )
    return "\n".join(lines)


def _format_pe_pacing_block(firm: FirmState) -> str:
    """Wave λ: qualitative guidance on deploying PE round capital.

    Surfaced only when the firm has raised PE capital (pre-IPO). No
    numbers — purely qualitative reminder that patient capital is meant
    to bridge multi-quarter execution, not be immediately exhausted.
    """
    if firm.is_public or firm.cumulative_pe_capital_raised <= 0:
        return ""
    lines = ["", "PRIVATE-COMPANY CAPITAL DISCIPLINE:"]
    lines.append(
        f"You have raised private capital from investors ({firm.last_round_type} "
        f"most recently). These investors have patient, multi-year horizons "
        f"and evaluate you primarily on capital efficiency between rounds. "
        f"Firms that exhaust a round's capital rapidly tend to struggle to "
        f"raise their next round at favorable terms, and some fail entirely. "
        f"Capital efficiency in the early quarters of a new round is one of "
        f"the strongest predictors of multi-round success — not how "
        f"aggressively capital can be deployed. Round capital is meant to "
        f"bridge execution across multiple quarters of operations, R&D "
        f"progress, and capacity build. Investors REWARD firms that spend "
        f"when spending is justified by validated milestones; investors "
        f"PUNISH firms that spend because cash is available."
    )
    return "\n".join(lines)


def _format_plan_context_block(plan_context: dict) -> str:
    """Wave κ: surface the firm's current plan + recent variances in the
    decision prompt. Empty if no plan."""
    if not plan_context or not plan_context.get("has_plan"):
        return ""
    lines = ["", "STRATEGIC PLAN (from prior planning cycle):"]
    lines.append(f"  Strategy: {plan_context.get('strategy_narrative', '')[:300]}")
    milestones = plan_context.get("key_milestones") or []
    if milestones:
        lines.append("  Key milestones:")
        for m in milestones:
            lines.append(f"    - {m}")
    contingency = plan_context.get("contingency_plan", "")
    if contingency:
        lines.append("  Your contingency plan (if next funding fails/delayed):")
        lines.append(f"    {contingency[:400]}")
    # Wave μ: surface THIS QUARTER's planned pacing so the firm must
    # justify deviations. Plans without this block are aspirational;
    # with it they are accountable.
    this_q = plan_context.get("this_quarter_plan")
    if this_q:
        lines.append("")
        lines.append("  THIS QUARTER'S PLAN (you committed to these numbers):")
        lines.append(
            f"    Revenue target: ${this_q.get('planned_revenue', 0)/1e6:.1f}M  |  "
            f"Units: {int(this_q.get('planned_units_sold', 0))}  |  "
            f"Capacity: {int(this_q.get('planned_capacity', 0))}"
        )
        lines.append(
            f"    R&D spend: ${this_q.get('planned_rd_spend', 0)/1e6:.1f}M  |  "
            f"Capex: ${this_q.get('planned_capex', 0)/1e6:.1f}M  |  "
            f"SG&A: ${this_q.get('planned_sga_spend', 0)/1e6:.1f}M"
        )
        lines.append(
            "    FOLLOW YOUR PLAN. The plan line above is the default "
            "execution for this quarter — it is the numbers the board "
            "and CFO already approved. Deviate ONLY when materially new "
            "information has arrived that invalidates the plan (a "
            "demand surprise, a financing shortfall, a competitor action, "
            "a safety event, etc.). If you deviate from any of revenue "
            "target / R&D / capex / SG&A, you MUST populate the "
            "`deviation_justification` field in your JSON output with a "
            "clear explanation of what changed. Absent justification, "
            "execute the plan as written."
        )
    variances = plan_context.get("recent_variances") or []
    if variances:
        lines.append("")
        lines.append("  Recent actual-vs-plan variance (last 3Q):")
        for v in variances:
            mat = "*** MATERIAL" if v.get("is_material") else ""
            lines.append(
                f"    Q{v['fyear']}-{v['fqtr']}: "
                f"rev_var={v['revenue_variance_pct']:+.0%}, "
                f"ni_var=${v['ni_variance']/1e6:+.1f}M {mat}"
            )
            if v.get("is_material") and v.get("material_reason"):
                lines.append(f"      → {v['material_reason']}")
    streak = plan_context.get("material_variance_streak", 0)
    if streak >= 2:
        lines.append("")
        lines.append(
            f"  ⚠ {streak} consecutive material-variance quarters. "
            f"The board expects you to ACT on this — either adjust execution "
            f"or the assumptions behind the plan were wrong. A new plan will "
            f"be issued next quarter unless you resolve the variance."
        )
    return "\n".join(lines)


def _format_peer_projections_block(peer_projections: list) -> str:
    """Wave ν: show competitor firms' PE-pitch projections + PE-side
    counter-projections. These become public once a round closes, so
    every firm + investor sees what peers are promising and what PE
    investors thought of those promises.

    Empty when no peer has raised a round with shared projections yet.
    """
    if not peer_projections:
        return ""
    lines = ["", "PEER PROJECTIONS FROM RECENT PE RAISES (public record):"]
    for p in peer_projections[-8:]:   # last 8 rounds at most
        fp = p.get("firm_projections") or {}
        lp = p.get("lead_investor_projection") or {}
        rev_y5 = fp.get("revenue_y5")
        margin_y5 = fp.get("ebitda_margin_y5")
        gen_y5 = fp.get("projected_generation_y5")
        lead_rev_y5 = lp.get("your_revenue_projection_y5")
        method = p.get("lead_valuation_method", "")
        line = (
            f"  {p['firm_id']} ({p.get('round_type','?')} "
            f"@ Q{p.get('round_quarter','?')}, post-money "
            f"${p.get('post_money_valuation', 0)/1e6:.0f}M):"
        )
        lines.append(line)
        bits = []
        if rev_y5:
            bits.append(f"firm projects Y5 rev ${rev_y5/1e6:.0f}M")
        if margin_y5 is not None:
            try:
                bits.append(f"EBITDA margin Y5 {float(margin_y5):.0%}")
            except (TypeError, ValueError):
                pass
        if gen_y5:
            bits.append(f"Gen {gen_y5} by Y5")
        if bits:
            lines.append("    " + " | ".join(bits))
        if lead_rev_y5:
            lines.append(
                f"    lead investor's counter-projection Y5 rev "
                f"${lead_rev_y5/1e6:.0f}M"
                + (f" (method: {method})" if method else "")
            )
    lines.append(
        "  Read these as credible public claims under the weight of "
        "investor-diligence scrutiny — peers are on-record with these "
        "numbers and PE funds signed off on them."
    )
    return "\n".join(lines)


def _format_working_capital_guidance() -> str:
    """Guidance block appended to firm system prompt when
    working_capital_decisions is enabled. Introduces the new decision fields
    without imposing specific numerical targets — firm judges tradeoffs."""
    return """

WORKING CAPITAL POLICY (enabled this run):
You also set:
  - payables_days_target: days you take to pay suppliers (DPO). Longer = more
    cash in hand, but suppliers may raise prices or tighten terms if you stretch.
  - receivables_days_target: days you let customers pay (DSO). Longer terms may
    attract more volume but increase working capital tie-up and bad-debt risk.
  - deposit_pct: fraction of invoice collected upfront (0-1). Upfront deposits
    improve cash flow and reduce collection risk, but customers may dislike
    large deposits. Recognized revenue spreads across quarters; the deposit
    sits on the balance sheet as deferred revenue until delivered.
  - ppe_disposal: $ value of PP&E you sell this quarter (0 = no sale). Raises
    cash and reduces capacity; generates gain/loss on sale.
These are trade-offs, not free levers. The market environment judges supplier
friction and customer preference based on how extreme your policies are."""


def _format_ceo_holdings_block(firm: FirmState) -> str:
    """CEO's personal equity holdings (Stage 11). Shown to the firm LLM when
    governance_enabled. Matters for incentive alignment — CEO with lots of
    unvested equity cares more about long-term survival; CEO near retirement
    may want to diversify."""
    if not firm.ceo_type:
        return ""
    from .ceo_comp import outstanding_snapshot
    snap = outstanding_snapshot(firm, firm.equity_price or 0.01)
    vested_ar_value = snap["vested_rsu_held_shares"] * (firm.equity_price or 0.01)
    return f"""
CEO COMPENSATION POSITION (personal):
  CEO: {firm.ceo_type} | age {firm.ceo_age}, tenure {firm.ceo_tenure_quarters}Q
  Vested RSU shares held: {snap['vested_rsu_held_shares']:,} (${vested_ar_value/1e6:.2f}M at current price)
  Unvested RSU shares: {snap['unvested_rsu_shares']:,} (${snap['intrinsic_value_unvested']/1e6:.2f}M unrealized)
  Unvested options: {snap['unvested_option_shares']:,} | Vested options: {snap['vested_option_shares']:,}
  Shares sold to date: {snap['total_shares_sold_to_date']:,} (${snap['cash_from_sales_cumulative']/1e6:.2f}M)
  CEO may sell some vested shares via `ceo_sell_shares` (int count of shares)."""


def _format_legal_reserves_guidance() -> str:
    """Stage 12 guidance for legal_reserves_enabled."""
    return """

LEGAL RESERVES (enabled this run):
Firms facing litigation risk accrue a reserve now (charged to IS as a
special item; liability grows on BS) in anticipation of future settlement.
When a settlement is actually paid, it uses the previously-accrued reserve
(cash out; reduces the reserve balance without a new IS charge).
  - legal_reserve_change: positive = accrue new reserve (charge this Q);
    negative = release existing reserve (credit this Q, tax-affected).
  - legal_settlements_paid: cash paid to settle cases this Q. Can't exceed
    the current reserve balance + this Q's new accrual.
These hit "special items" on the IS, not operating expenses."""


def _format_pension_guidance() -> str:
    """Stage 12 guidance for pension_enabled."""
    return """

PENSION (enabled this run):
Service cost accrues automatically each quarter at 5% of cash compensation
(SGA cash + CEO cash comp). Liability builds on BS until the firm makes a
contribution:
  - pension_contribution: cash paid to fund the plan this Q. Reduces the
    pension_liability line. No contribution = unfunded liability grows."""


def _format_restructuring_guidance() -> str:
    """Guidance block when restructuring_enabled.

    Purely descriptive — no prescriptive thresholds. Firm decides magnitude
    and composition."""
    return """

RESTRUCTURING (enabled this run):
When the business is under strain you can take restructuring actions. These
produce a one-time charge on the income statement (WRDS `rcp`) but may be
necessary to right-size operations. You can combine any of:
  - restructuring_severance: cash paid to lay off employees (reduces cash;
    the environment will judge impact on brand, customer service, and
    future delivery capacity).
  - restructuring_ppe_impairment: write down PP&E below book value (non-cash
    charge; permanently reduces PP&E gross).
  - restructuring_inventory_write_off: write off unsellable inventory (non-
    cash charge; reduces inventory value).
  - restructuring_goodwill_impairment: write down goodwill from acquisitions
    that aren't performing (non-cash; reduces goodwill).

Restructuring signals to analysts and investors that you're taking a hit
now to improve the long-term trajectory. Excessive or repeated restructurings
without improvement are a red flag (serial restructurer)."""


def _format_bad_debt_guidance() -> str:
    """Guidance block appended when bad_debt_enabled."""
    return """

BAD DEBT POLICY (enabled this run):
You also set:
  - allowance_pct_of_ar: your estimate of uncollectible AR as a fraction of
    gross receivables (0-1). This is your audited accounting judgment. Setting
    it too low understates true losses (auditor may flag); too high hits
    reported earnings and lowers your reported equity. Market conditions and
    your customer mix determine actual realized write-offs (decided by the
    environment)."""


def _format_debt_facilities_block(firm: FirmState) -> str:
    """Render a firm's debt facilities with covenant status.

    Shown in the firm decision prompt when debt_covenants_enabled and the
    firm has active facilities. Read-only informational block — the firm
    uses the legacy debt_request: float field to request more debt.
    """
    active = [f for f in firm.debt_facilities
              if f.status not in ("repaid", "defaulted", "converted")]
    if not active:
        return ""
    lines = ["", "DEBT FACILITIES (your current obligations):"]
    for fac in active:
        rate_ann = fac.coupon_rate_quarterly * 4 * 100
        bal_m = fac.current_balance / 1e6
        line = (f"  {fac.facility_id} [{fac.facility_type}] "
                f"${bal_m:,.1f}M @ {rate_ann:.1f}%/yr, "
                f"matures Q{fac.maturity_quarter} ({fac.amortization_type})")
        lines.append(line)
        if fac.covenants:
            for cov in fac.covenants:
                op = "≤" if cov.covenant_type.startswith("max_") else "≥"
                flag = " VIOLATED" if cov.currently_violated else ""
                lines.append(f"    Covenant: {cov.covenant_type} {op} "
                             f"{cov.threshold:.2f}{flag}")
        if fac.facility_type == "convertible_bond" and fac.conversion_price > 0:
            lines.append(f"    Conversion: strike ${fac.conversion_price:.2f} "
                         f"({fac.conversion_ratio:.0f} shares per $1000 face)")
        lines.append(f"    Status: {fac.status}")
    return "\n".join(lines)


def build_firm_prompt(
    firm: FirmState,
    public_info: dict,
    params: SimParams,
    last_flows: dict | None = None,
    gazette: str = "",
    rd_report: RDReport | None = None,
    brand_report: BrandReport | None = None,
    earnings_management_enabled: bool = False,
    debt_covenants_enabled: bool = False,
    working_capital_decisions: bool = False,
    bad_debt_enabled: bool = False,
    restructuring_enabled: bool = False,
    governance_enabled: bool = False,
    legal_reserves_enabled: bool = False,
    pension_enabled: bool = False,
    extended_history_block: str = "",   # Wave ν+12: full firm self-history from agent_history
) -> tuple[str, str]:
    """Build (system, user) prompts for a firm's quarterly decision.

    Wave ι: scenario-driven industry character + quantitative market
    signals are pulled from `public_info` (populated by
    `_build_firm_info_package` in the orchestrator) so scenarios can
    specify their own industry without editing prompt text.
    """

    gen = firm.product_generation
    efficacy_map = {1: "5-8", 2: "10-15", 3: "15-20", 4: "20-25"}
    delivery_map = {1: "IV infusion, quarterly, clinic-administered",
                    2: "subcutaneous injection, monthly, self-administered",
                    3: "oral tablet, daily",
                    4: "one-time gene therapy + annual booster"}
    ae_rate = params.gen_serious_ae_rate.get(gen, 0.073)
    # Personality descriptions — philosophical, not prescriptive. Wave λ
    # Fix B: each style now includes survival realism. Real-world
    # operators with these styles still die when they ignore runway.
    style_map = {
        0: "Aggressive Growth — believes market share matters in winner-take-most industries, but also knows the dead don't win share. Pursues growth while preserving multi-quarter optionality.",
        1: "Premium Innovator — premium pricing and brand create long-term advantage, but survival to fund the next breakthrough beats speed-to-first. Disciplined burn between milestones.",
        2: "Value Operator — believes disciplined cash management and efficiency win long-term; capital preservation IS the strategy, not a constraint on it.",
        3: "Fast Follower — learns from competitors' mistakes, moves decisively when uncertainty resolves AND capital is available. Patient about timing, aggressive about execution.",
        4: "Marketing Powerhouse — brand and patient trust are durable competitive moats, but moats require a living firm to defend them. Builds brand at burn rates the firm can sustain across multiple funding cycles.",
    }
    firm_idx = int(firm.firm_id.split("_")[-1]) if "_" in firm.firm_id else 0
    company_name = get_company_name(firm_idx)
    mgmt_sheet = get_management_sheet(firm_idx)

    # Wave ι: pull scenario-driven industry character + market signals
    industry_character = public_info.get("industry_character") or {}
    industry_character_block = _format_industry_character_block(industry_character)
    market_signals_block = _format_market_signals_block(
        public_info.get("market_signals") or {}
    )

    system = FIRM_SYSTEM_TEMPLATE.format(
        company_name=company_name,
        firm_id=firm.firm_id,
        style=style_map.get(firm_idx, "balanced"),
        generation=gen,
        capacity=firm.capacity_units,
        delivery_desc=delivery_map.get(gen, "IV infusion"),
        efficacy_years=efficacy_map.get(gen, "5-8"),
        ae_rate=ae_rate,
        unit_cost=firm.base_unit_cost,
        n_firms=len(public_info.get("competitors", {})),
        industry_character_block=industry_character_block,
        market_signals_block=market_signals_block,
    )

    # Append management approach sheet (scenario-specific guidance)
    if mgmt_sheet:
        system = system + "\n\n" + mgmt_sheet

    # Stage 4/5: optional policy-decision guidance
    if working_capital_decisions:
        system = system + _format_working_capital_guidance()
    if bad_debt_enabled:
        system = system + _format_bad_debt_guidance()
    if restructuring_enabled:
        system = system + _format_restructuring_guidance()
    if legal_reserves_enabled:
        system = system + _format_legal_reserves_guidance()
    if pension_enabled:
        system = system + _format_pension_guidance()

    # Wave κ: strategic plan + variance context
    plan_block = _format_plan_context_block(public_info.get("plan_context") or {})
    if plan_block:
        system = system + plan_block

    # Wave ν: peer projections shared in recent PE rounds (public record)
    peer_proj_block = _format_peer_projections_block(
        public_info.get("peer_pe_projections") or []
    )
    if peer_proj_block:
        system = system + peer_proj_block

    # Wave λ: PE-round capital discipline guidance for pre-IPO firms
    pe_pacing_block = _format_pe_pacing_block(firm)
    if pe_pacing_block:
        system = system + pe_pacing_block

    # Wave λ Fix 3: capital-constraint warning (both private + public)
    cap_constraint_block = _format_capital_constraint_block(firm)
    if cap_constraint_block:
        system = system + cap_constraint_block

    # Wave λ Fix E: forward-looking runway block (proactive, not retrospective)
    runway_block = _format_forward_runway_block(firm, last_flows)
    if runway_block:
        system = system + runway_block

    # Wave λ Fix G: survival mental model for pre-IPO firms
    survival_block = _format_survival_mental_model_block(firm)
    if survival_block:
        system = system + survival_block

    # Build user prompt with clean PUBLIC vs PRIVATE separation
    # public_info contains ONLY: public_competitors, own_private, macro, gazette
    # No other firm's private data exists in this dict.
    macro = public_info.get("macro", {})
    public_competitors = public_info.get("public_competitors", {})
    own_private = public_info.get("own_private", {})
    env_notes = public_info.get("env_notes", []) or []
    pending_activist_campaigns = (
        public_info.get("pending_activist_campaigns", []) or []
    )
    analyst_consensus = public_info.get("analyst_consensus")

    # Get own reports from own_private (no other firm's reports in scope)
    if rd_report is None:
        rd_report = own_private.get("rd_report")
    if brand_report is None:
        brand_report = own_private.get("brand_report")

    # PUBLIC competitor info (what you can observe from the market).
    # Wave ν+11 fix for E5: include each peer's 4-quarter revenue + share
    # trajectory so the firm CFO can read trends rather than just a
    # single-quarter snapshot. Without this, peer dynamics are invisible
    # and the firm has no basis for strategic comparison over time.
    comp_lines = []
    for cid, cinfo in sorted(public_competitors.items()):
        if cid != firm.firm_id:
            price_c = cinfo.get("price", 0)
            share = cinfo.get("market_share", 0)
            gen = cinfo.get("generation", 1)
            ep = cinfo.get("equity_price", 0)
            rev = cinfo.get("revenue", 0)
            total_rd = cinfo.get("total_rd_spend", 0)
            rev_hist = cinfo.get("revenue_history_4q", []) or []
            share_hist = cinfo.get("share_history_4q", []) or []
            hist_str = ""
            if len(rev_hist) >= 2:
                rev_str = " → ".join(f"${r/1e6:.0f}M" for r in rev_hist)
                share_str = " → ".join(f"{s:.0%}" for s in share_hist)
                hist_str = (f"\n     trailing 4Q rev:   {rev_str}"
                            f"\n     trailing 4Q share: {share_str}")
            comp_lines.append(
                f"  {cid}: Price=${price_c:,.0f} Share={share:.1%} "
                f"Rev=${rev/1e6:.1f}M R&D(total)=${total_rd/1e6:.0f}M "
                f"Gen={gen} Eq.Price=${ep:.2f}{hist_str}"
            )
    comp_text = "\n".join(comp_lines) if comp_lines else "  (no competitor data yet)"

    # Cash runway (descriptive, not prescriptive — firm decides whether
    # any particular level warrants action).
    cash_runway = "N/A (positive cash flow)"
    cash_urgency = ""
    if last_flows and last_flows.get("cfo", 0) < 0:
        burn_rate = -last_flows["cfo"]
        if burn_rate > 0:
            runway_q = firm.cash / burn_rate
            cash_runway = f"{runway_q:.1f} quarters at last quarter's burn rate"

    # Inventory (descriptive).
    inv_warning = ""
    if firm.inventory_units > 0:
        if last_flows and last_flows.get("units_sold", 0) > 0:
            inv_quarters = firm.inventory_units / last_flows["units_sold"]
            inv_warning = (f"  Inventory: {firm.inventory_units} courses "
                           f"({inv_quarters:.1f}Q of recent sales)")
        else:
            inv_warning = f"  Inventory: {firm.inventory_units} unsold courses"

    # PP&E depreciation state (descriptive only).
    cap_warning = ""
    ppe_depr_pct = (firm.accum_depreciation / firm.ppe_gross * 100) if firm.ppe_gross > 0 else 0

    # Prior quarter decisions (if available)
    prior_decisions_text = ""
    if last_flows:
        prior_decisions_text = f"""
YOUR LAST QUARTER RESULTS
  Revenue: ${last_flows.get('net_sales', 0):,.0f}
  Units sold: {last_flows.get('units_sold', 0)}
  Net income: ${last_flows.get('net_income', 0):,.0f}
  Cash flow from ops: ${last_flows.get('cfo', 0):,.0f}
  Market share: {last_flows.get('market_share', 0):.1%}
  Price: ${last_flows.get('actual_price', 0):,.0f}
  R&D spent: ${last_flows.get('actual_rd_spend', 0):,.0f}
  SGA spent: ${last_flows.get('actual_sga_spend', 0):,.0f}
  Capex: ${last_flows.get('actual_capex', 0):,.0f}"""

    # Optional facility block (only shown when debt covenants are enabled
    # and the firm actually has facilities — otherwise empty string).
    facilities_block = (_format_debt_facilities_block(firm)
                        if debt_covenants_enabled else "")
    # CEO holdings block (Stage 11 — governance_enabled)
    ceo_block = (_format_ceo_holdings_block(firm)
                 if governance_enabled else "")

    env_notes_block = ""
    if env_notes:
        env_notes_block = (
            "\n*** WHAT ACTUALLY HAPPENED LAST QUARTER (operational reality) ***\n"
            "Your plan last quarter did not fully execute as designed. The market\n"
            "environment moderated some decisions due to infeasibility:\n"
            + "\n".join(f"  - {n}" for n in env_notes)
            + "\nTake this into account — do not assume your prior plan went through\n"
              "as stated. Build from the actual outcome.\n"
        )

    # Wave ν+12: investor voice — short market-analyst note from end of
    # last quarter on what the public market would view as positive next
    # operating + financing moves. Soft input, not a directive. Firm is
    # free to disagree; but visibly ignoring repeated market commentary
    # has its own consequences (analysts go from buy to hold, activists
    # take notice, IB pricing tightens).
    investor_note = public_info.get("investor_note") or ""
    investor_note_block = ""
    if investor_note:
        investor_note_block = (
            "\n*** MARKET / INVESTOR VIEW ON YOUR FIRM (end of last quarter) ***\n"
            f"  {investor_note}\n"
            "This is the public market's perspective on what would be received\n"
            "well next quarter. Consider it in your reasoning — agree or\n"
            "disagree, but do not silently ignore.\n"
        )

    # Wave ν+10 item 10: investment-bank feedback from a recent declined
    # or haircut issuance. The bank's market_discussion + retry_guidance
    # are now public price-formation signals; the firm should respond
    # explicitly in its strategic memo and (if it still wants the
    # capital) submit a modified issuance request that addresses the
    # bank's concerns.
    ibank_feedback = public_info.get("ibank_feedback")
    ibank_feedback_block = ""
    if ibank_feedback:
        decl_kinds = []
        if ibank_feedback.get("declined_debt"):
            decl_kinds.append("term debt")
        if ibank_feedback.get("declined_equity"):
            decl_kinds.append("equity offering")
        kinds_str = " and ".join(decl_kinds) if decl_kinds else "issuance"
        ibank_feedback_block = (
            f"\n*** INVESTMENT-BANK FEEDBACK ({kinds_str} declined / haircut) ***\n"
            f"Market discussion: {ibank_feedback.get('market_discussion', '')}\n"
            f"Retry guidance: {ibank_feedback.get('retry_guidance', '')}\n"
            f"Acknowledge this in your strategic memo. If you still want the\n"
            f"capital, submit a MODIFIED issuance request that addresses the\n"
            f"bank's concerns (smaller size, longer maturity, higher rate, an\n"
            f"equity buffer, or a delay until conditions improve).\n"
        )

    # Wave epsilon: sell-side analyst consensus on your firm.
    consensus_block = ""
    if analyst_consensus and analyst_consensus.get("n_analysts", 0) > 0:
        mtp = analyst_consensus.get("mean_target_price")
        meps = analyst_consensus.get("mean_eps_forecast_1q")
        bc = analyst_consensus.get("buy_count", 0)
        hc = analyst_consensus.get("hold_count", 0)
        sc = analyst_consensus.get("sell_count", 0)
        consensus_block = (
            f"\n*** SELL-SIDE ANALYST CONSENSUS ON YOUR FIRM ***\n"
            f"  n_analysts = {analyst_consensus['n_analysts']}\n"
        )
        if mtp is not None:
            consensus_block += (
                f"  target price: mean=${mtp:.2f} "
                f"(range ${analyst_consensus.get('min_target_price', 0):.2f}-"
                f"${analyst_consensus.get('max_target_price', 0):.2f})\n"
            )
        if meps is not None:
            consensus_block += f"  EPS 1Q forecast (mean): ${meps:.2f}\n"
        consensus_block += (
            f"  ratings: {bc} buy / {hc} hold / {sc} sell\n"
            f"These are public observations. They shape the equity market\n"
            f"and peer expectations. Address material gaps vs consensus.\n"
        )

    # Activist campaigns pending a response. These are public events — the
    # activist has taken a stake and publicly demanded action. Your board
    # MUST acknowledge with an accept / reject / negotiate decision. The
    # market and media will judge your response.
    activist_block = ""
    if pending_activist_campaigns:
        lines = []
        has_proxy_fight = False
        for c in pending_activist_campaigns:
            dt = c.get("demand_type", "")
            if dt == "proxy_fight":
                has_proxy_fight = True
            lines.append(
                f"  • {c.get('activist_id','activist')} "
                f"(stake {c.get('stake_pct_implied',0)*100:.1f}%): "
                f"demands {dt} — "
                f"{c.get('demand_specifics','')}"
            )
            thesis = c.get("thesis") or c.get("demand_specifics", "")
            if thesis:
                lines.append(f"      thesis: {thesis[:200]}")
        proxy_note = ""
        if has_proxy_fight:
            # Wave ν+11 fix for E7: proxy_fight is a binding governance event
            # — the firm cannot just decline. The board's options are to
            # comply (accept the demand and act on it this quarter or
            # commit to a near-term timeline), or run a defense (which has
            # real cost: legal fees, distraction, disclosure friction, and
            # the reputational hit if the activist ultimately wins). Silence
            # or pure rejection is not a viable strategy in a proxy fight.
            proxy_note = (
                "\n  *** ONE OF THESE IS A PROXY FIGHT ***\n"
                "  A proxy fight is a binding governance event: the activist\n"
                "  has committed enough capital and reputation that the\n"
                "  matter will go to a shareholder vote. Real boards facing\n"
                "  a proxy fight either negotiate a settlement (accept or\n"
                "  partial-comply with the underlying demand) or run an\n"
                "  active defense (which is costly and uncertain). Pure\n"
                "  rejection without a substantive defense narrative is\n"
                "  not a credible response. State your strategy clearly\n"
                "  in your activist_response: accept (full compliance),\n"
                "  partial (compromise with named concessions), or reject\n"
                "  (with explicit defense plan and cost acknowledgement).\n"
            )
        activist_block = (
            "\n*** ACTIVIST INVESTOR CAMPAIGN(S) AGAINST YOUR FIRM ***\n"
            + "\n".join(lines)
            + proxy_note
            + "\nYou MUST include an `activist_response` field in your JSON\n"
              "(response: accept | reject | negotiate | partial; rationale: 1-2\n"
              "sentences). Silence is not acceptable.\n"
        )

    # Wave ν+4: prominent GROUND TRUTH header to prevent context-loss
    # hallucinations (e.g., long-lived firms forgetting they've operated
    # for many years). The header forces the LLM to acknowledge actual
    # firm state before reasoning about any decision.
    abs_q = macro.get('quarter', '?')
    ground_truth_header = f"""=== GROUND TRUTH ABOUT YOUR FIRM (do not ignore or contradict) ===
  This is QUARTER {abs_q} of your firm's operating history.
  Your firm: {firm.firm_id}  |  Lifecycle stage: {firm.lifecycle_stage}  |  Public: {firm.is_public}
  You have operated continuously since founding — this is NOT your first quarter unless quarter == 1.
  Your current capability stock: {firm.capability_stock:.1f}/100
  Your current brand stock: {firm.brand_stock:.1f}/100
  Your cumulative product R&D invested: ${firm.rd_cumulative_product:,.0f}
  Your product generation: Gen {firm.product_generation}
  Your cash on hand: ${firm.cash:,.0f}
  Your total liabilities: ${firm.total_liabilities:,.0f}
  When you reason in this prompt, your statements MUST be consistent with these facts.
  Do not refer to this as your "first board meeting" or "first quarter" if quarter > 1.
"""

    # Wave ν+12: full firm self-history rendered by agent_history. Empty
    # string if caller didn't compute it (e.g. mock paths). Inserted right
    # after the ground-truth header so the CFO sees memory before private state.
    firm_history_section = ""
    if extended_history_block:
        firm_history_section = (
            "\n\n=== YOUR HISTORICAL CONTEXT (everything since you were founded) ===\n"
            "Read your own financials, decisions, and recent debrief notes\n"
            "carefully. The compression rule: every 4th quarter for older\n"
            "history, every quarter for the last 8. Use this memory to ground\n"
            "this quarter's decision — what worked, what failed, what your\n"
            "trajectory looks like, where the cumulative R&D and SG&A actually\n"
            "stand vs your peers' visible behaviour.\n\n"
            f"{extended_history_block}\n"
        )

    user = f"""{ground_truth_header}=== QUARTER: Q{macro.get('fqtr', '?')} {macro.get('fyear', '?')} (Quarter {macro.get('quarter', '?')}) ==={env_notes_block}{investor_note_block}{ibank_feedback_block}{consensus_block}{activist_block}{firm_history_section}

===== PRIVATE INFORMATION (only you and the market environment know this) =====

YOUR FINANCIAL POSITION
  Cash: ${firm.cash:,.0f}
  Accounts receivable: ${firm.accounts_receivable:,.0f}
  PP&E (net): ${firm.ppe_net:,.0f}  (gross ${firm.ppe_gross:,.0f}, {ppe_depr_pct:.0f}% depreciated)
  Total assets: ${firm.total_assets:,.0f}
  Total liabilities: ${firm.total_liabilities:,.0f}
  Retained earnings: ${firm.retained_earnings:,.0f}
  Total equity: ${firm.total_equity:,.0f}
  Equity price: ${firm.equity_price:,.2f}/share
{inv_warning}
{cap_warning}
{facilities_block}
{ceo_block}

INTERNAL STATE
  Capability stock: {firm.capability_stock:.1f}
  Brand stock: {firm.brand_stock:.1f}
  Capacity: {firm.capacity_units} courses/quarter
  Unit cost: ~${firm.base_unit_cost:,.0f}/course
  Product generation: {firm.product_generation}
  Cumulative product R&D: ${firm.rd_cumulative_product:,.0f}
  Cumulative process R&D: ${firm.rd_cumulative_process:,.0f}
  Available revolver: ${firm.available_credit:,.0f}
{prior_decisions_text}

===== PUBLIC INFORMATION (all firms and investors can see this) =====

COMPETITORS (observable market data -- you do NOT know their internal costs, R&D pipeline details, brand scores, or cash):
{comp_text}

MACRO
  Risk-free rate: {macro.get('risk_free_rate', 0.01)*400:.1f}% annual
  Quarter: {macro.get('quarter', '?')}
  Awareness rate: {macro.get('awareness_rate', 0.15):.0%}

{format_rd_report_for_firm(rd_report) if rd_report else '(No R&D report yet -- first quarter)'}

{format_brand_report_for_firm(brand_report) if brand_report else '(No brand report yet -- first quarter)'}

STRATEGIC DASHBOARD
  Cash runway: {cash_runway}
  Industry status: All firms Gen {firm.product_generation}.

{f'INDUSTRY GAZETTE:{chr(10)}{gazette}' if gazette else ''}

{'EARNINGS MANAGEMENT (Wave ν+14h F1 — explicit articulation required):' + chr(10) + 'You may choose to adjust reported earnings through legal but aggressive accounting.' + chr(10) + 'Set manipulation_amount: positive = overstate earnings, negative = understate (cookie jar).' + chr(10) + 'Set to 0 for honest reporting. Larger amounts increase detection risk by regulators.' + chr(10) + 'Cumulative manipulation stock: $' + f'{firm.cumulative_manipulation:,.0f}' + chr(10) + 'Real public-company CFOs DO sometimes use this lever — to smooth earnings around analyst guidance, to hit a covenant tripwire, to build a cookie-jar reserve in a strong quarter, or to manage a transitory shortfall. Defaulting to 0 quarter after quarter regardless of pressure (a missed guidance, a meaningful variance from plan, a looming covenant) is not realistic CFO behaviour. Each quarter, briefly state in your reasoning WHY 0 is the right answer (e.g., \"comfortably above guidance + no covenant pressure + no incentive\") or WHY a non-zero amount is justified. A bare 0 with no articulation suggests you are not actually evaluating the decision.' + chr(10) if earnings_management_enabled else ''}{'LEGAL RESERVES (Wave ν+14h F2 — explicit articulation):' + chr(10) + 'You may accrue or release legal reserves via legal_reserve_change.' + chr(10) + 'Real public-company CFOs accrue reserves periodically — for litigation in progress, contingent liabilities, product-liability exposure, regulatory settlements. Defaulting to 0 in every quarter when an industry has active litigation patterns (you can see them in peer events) is not realistic. Consider whether your firm has any contingent legal exposure this quarter; if you accrue 0, briefly note why.' + chr(10) if legal_reserves_enabled else ''}{'CEO STOCK SALES (Wave ν+14h F4 — explicit articulation):' + chr(10) + f'Your CEO holds {firm.ceo_vested_shares_held:,} vested shares (currently worth ${firm.ceo_vested_shares_held * firm.equity_price:,.0f} at the current price).' + chr(10) + 'Real public-company CEOs DO sell some stock periodically — typically via 10b5-1 plans for tax-burden coverage, portfolio diversification, or planned wealth events. Permanently holding ALL vested stock with zero sales over many years is not typical CEO behaviour. Each quarter the CEO has meaningful vested holdings, consider whether ceo_sell_shares > 0 is appropriate; if you set it to 0, briefly note why.' + chr(10) if (governance_enabled and firm.ceo_vested_shares_held > 0) else ''}Output your decision as JSON:

```json
{{
  "price": <number>,
  "production": <integer 0-{firm.capacity_units}>,
  "capex": <number>,
  "rd_spend": <number>,
  "rd_allocation": {{"product": <0-1>, "process": <0-1>, "delivery": <0-1>}},
  "sga_spend": <number>,
  "equity_issuance_request": 0,
  "debt_request": 0,
  "dividends": 0,
  "buybacks": 0,{"" + chr(10) + '  "manipulation_amount": 0,' if earnings_management_enabled else ""}{"" + chr(10) + '  "payables_days_target": <days>,' + chr(10) + '  "receivables_days_target": <days>,' + chr(10) + '  "deposit_pct": <0 to 1>,' + chr(10) + '  "ppe_disposal": <$ amount of PP&E sold>,' if working_capital_decisions else ""}{"" + chr(10) + '  "allowance_pct_of_ar": <0 to 1>,' if bad_debt_enabled else ""}{"" + chr(10) + '  "restructuring_severance": <$ cash for layoffs>,' + chr(10) + '  "restructuring_ppe_impairment": <$ PP&E write-down>,' + chr(10) + '  "restructuring_inventory_write_off": <$ inventory write-off>,' + chr(10) + '  "restructuring_goodwill_impairment": <$ goodwill write-down>,' if restructuring_enabled else ""}{"" + chr(10) + '  "ceo_sell_shares": <int shares CEO sells from vested>,' + chr(10) + '  "ceo_exercise_options": <int vested options to exercise (CEO pays strike, receives shares)>,' if governance_enabled else ""}{"" + chr(10) + '  "legal_reserve_change": <$ accrual (+) or release (-)>,' + chr(10) + '  "legal_settlements_paid": <$ paid to settle>,' if legal_reserves_enabled else ""}{"" + chr(10) + '  "pension_contribution": <$ paid to fund plan>,' if pension_enabled else ""}{"" + chr(10) + '  "activist_response": {"response": "accept|reject|negotiate|partial", "rationale": "<1-2 sentences>"},' if pending_activist_campaigns else ""}
  "deviation_justification": "<empty string if you are executing the plan as written; otherwise explain what materially new information warrants deviating from the plan>",
  "reasoning": "<brief explanation>"
}}
```"""

    return system, user


# ─── Environment Market Resolution Prompt ────────────────────────────────

ENV_SYSTEM_PROMPT = """You are the market environment for a simulated industry. Each quarter, you observe the actions of firms competing and determine outcomes. The specific industry (longevity therapy, mature pharma, declining sector, etc.) is described by the SCENARIO context supplied in the user prompt — read it carefully and calibrate demand realism to that industry's real-world economics.

You are OMNISCIENT -- you see everything: all firms' private R&D progress, brand health, customer service quality, internal capabilities, and financial details.

CRITICAL DEMAND RULES:
- PRICE MATTERS. Patients are price-sensitive. Lower prices generally attract more patients. Higher prices generally reduce volume but may signal quality. Price differences should influence share allocation, though quality and brand also matter.
- QUALITY MATTERS. Higher capability and brand scores should translate to higher share, all else equal.
- SERVICE MATTERS. Firms with low customer service (from low SGA) should gradually lose patients.
- The market is NOT a fixed pie -- lower prices across the industry increase total demand.

TOTAL DEMAND ANCHOR (provided by the demand calibrator):
The demand calibrator (a separate market-research voice) will provide you with a generous estimate of total industry demand this quarter, based on the scenario's TAM and current industry conditions. Treat this estimate as your ANCHOR for the total demand pool — calibrate to it rather than to your own first instinct, which may under-estimate. The calibrator's number is the realistic top-of-funnel for this market; your job is to ALLOCATE that pool across firms based on their differentiation, price, quality, and brand.

PER-FIRM ALLOCATION (qualitative, not formula-driven):
For each firm, reason narratively about which customer segment it serves and what fraction of the calibrator-anchored total demand it would naturally attract. Use comparison language ("firm X serves a similar segment to firm Y but at a premium price, capturing the brand-loyal subset") rather than computed multipliers. The result: firms with reasonable products should produce meaningful revenue at meaningful capacity utilization. Industry-total revenue should reflect the scenario's economic scale, not a small fraction of it.

# REGIONAL_BLOCK_START
PRODUCT DIFFERENTIATION + IDIOSYNCRATIC CONSUMER PREFERENCES (CRITICAL):
- Each firm's product is meaningfully differentiated. Firms differ in
  delivery method (IV / subcutaneous / oral), formulation, side-effect
  profile, brand reputation, physician-network relationships, and
  customer-service quality. These differences create LOYAL customer
  segments — patients/physicians who prefer a specific firm's product
  for clinical, logistical, or trust reasons.
- Per-firm differentiation dimensions are explicitly listed in each
  firm's section below: geographic focus, target patient segment,
  distribution channel, and signature feature. READ THESE — they are
  the primary basis for share allocation, not just price/quality/brand.

CONSUMERS HAVE IDIOSYNCRATIC PREFERENCES:
Real customers do NOT all flock to the cheapest or highest-quality
firm. They have personal, idiosyncratic reasons to use ONE firm over
another — even when other firms offer better terms on price or
capability:
  - Geographic proximity: a patient in the US Midwest naturally uses
    a firm with Midwest distribution, NOT a firm focused on Asia-Pacific
  - Doctor / payer relationships: physicians prescribe what they know
    and trust; insurance plans have negotiated networks
  - Product format fit: some patients medically NEED IV; some can only
    do oral; some require pediatric formulations. These create captive
    segments that no single firm can fully serve
  - Side-effect tolerance: each patient tolerates a different side-effect
    profile, so firms with different safety/efficacy tradeoffs each
    capture different patients
  - Brand affinity / prior treatment continuation: patients on a working
    therapy don't switch even if a competitor undercuts on price
  - Care-setting requirements: some patients need clinic-administered;
    some need home-delivery; some need hospital infusion

CONSEQUENCE — 100% SHARE FOR ONE FIRM IS UNREALISTIC:
A single firm capturing the entire market with ALL OTHER FIRMS AT
$0 REVENUE is implausible in a real differentiated industry. Even an
inferior firm retains a niche customer base because its specific
combination of geographic / segment / channel / feature attributes
is the best fit for SOME patients. If you find yourself routing all
demand to one firm, you are producing a degenerate allocation that
wouldn't occur in any real-world differentiated market — re-allocate
so that every operating firm with reasonable economics has SOME share
reflecting its niche customer base.
- Consequence: when one firm prices aggressively low (even at or below
  cost), it CAPTURES the price-sensitive marginal segment but does NOT
  zero-out competitors with loyal customer bases. A firm with strong
  brand, capability, or specialized niche keeps a meaningful share even
  when undercut on price. Differentiated competitors are NOT in
  cutthroat Bertrand competition.
- Allocate share with this in mind: at any reasonable price the
  highest-quality, highest-brand firm retains a base of loyal customers;
  the cheapest-priced firm captures the price-sensitive marginal demand;
  middle firms capture middle segments. Avoid winner-take-all allocations
  unless one firm is genuinely dominant on multiple dimensions.
# REGIONAL_BLOCK_END

KNOWLEDGE DIFFUSION (incumbents may mimic leapfrog entrants):
- When an entrant brings a leapfrog technology (you can see this in the
  entrant's pre-credited cumulative R&D and elevated capability stock),
  incumbents do NOT instantly copy it. But over several quarters, the
  technology diffuses through hiring, scientific publication, patent
  expirations, and reverse engineering. Incumbents that were
  competitive can gradually narrow the capability gap by investing in
  product R&D themselves.
- This means: a leapfrog entrant has a multi-quarter window to scale
  before incumbents catch up. If the leapfrog firm uses that window
  well (raises capital, builds capacity + brand), it can become a real
  threat. If it squanders it, incumbents close the gap.
- You can reflect diffusion by: granting incumbents who invest in
  product R&D a slightly faster capability gain in quarters AFTER a
  leapfrog entry. Do not auto-equalize — the leapfrog firm keeps its
  head start unless its execution falters.

SURVIVAL & STABILITY (avoid winner-take-all):
- Real industries rarely consolidate to a single survivor in just a few
  years. Multiple differentiated firms typically coexist for many years,
  each serving distinct customer segments / niches.
- A firm that is operating efficiently — pricing thoughtfully (not
  giving the product away), holding burn under revenue when possible,
  retaining customer loyalty — should be able to SURVIVE even without
  winning the share war. Don't allocate so aggressively that careful
  operators get starved.
- Sustained existence per dollar burned is the dominant outcome metric
  for these firms. A firm that retains a meaningful share with positive
  contribution margin and runway is a genuine survivor, not a failure.
  Reward this pattern in your share allocation by NOT pushing all
  customers to one or two firms when several differentiated alternatives
  exist.

PRICE-DEVIATION DISCIPLINE (demand-side realism, not a hard clamp):
- Calibrate what constitutes a plausible price range from the SCENARIO's industry
  description and from the observed prices of firms in this market. Prices far
  below a firm's unit manufacturing cost signal distress. Prices far above the
  prevailing industry band are an affordability / insurance hurdle — customers
  generally do not pay such prices absent a specific narrative reason (monopoly
  catalyst, breakthrough, supply cutoff) that you must explicitly name.
- Extreme outliers should earn near-zero share, NOT dominant share. A firm
  pricing well above the prevailing peer band without a supporting catalyst
  should see market_share collapse toward zero. A firm pricing well below the
  band (likely loss-leader) may attract volume, but unit economics will
  destroy the firm — share can rise sharply while the firm shows negative NI.
- You are the market's realism check. Do not reward nonsense pricing with nonsense share.

STICKINESS & REALISM:
- Real markets have patient loyalty. Existing patients tend to stick with their provider
  absent major events (safety issue, insurance changes, price gap widening meaningfully).
- Demand and market shares typically evolve gradually. Big moves should have specific
  narrative causes (events, catalysts, clear fundamental shifts). Name the cause when
  moves are large.
- New patients respond more to price/quality than existing patients, so share shifts
  happen at the margin.

CUSTOMER STICKINESS (read this every quarter):
- Patients on a given firm's therapy face real switching costs — physician
  relationships, dosing schedules, side-effect profiles already known to them,
  insurance contracting. They do NOT re-shop their longevity therapy quarter-by-
  quarter. The right mental model is: most of last quarter's customers stay
  with the same firm this quarter unless a specific reason pushes them to switch
  (a safety event, a meaningful new entrant matching their segment, a price
  hike). Marginal patient acquisition happens at the margin.
- Therefore: a firm's market share THIS quarter is anchored heavily on its share
  LAST quarter. Look at the per-firm share trajectory you have produced over
  recent quarters — the quarter-on-quarter change should be modest in the
  absence of specific catalysts. If you find yourself moving a firm's share
  by more than a few percentage points in one quarter, you should be able to
  name the catalyst (price war initiation, a generation transition by a
  competitor, a recall, a major clinical readout). Without a named catalyst,
  default to gradual change.
- Do not move share to "rebalance" the industry. Real customer behaviour
  does not mean-revert. Even when one firm dominates, customer stickiness
  preserves the dominant share until a specific competitive event erodes it.
- The trajectory data you receive (per-firm revenue + share over the last
  several quarters) is your check on yourself: if you're producing a series
  with high quarter-on-quarter volatility for the same firm, that's a sign
  you're allocating demand too freely. Real industries are stickier.

PRICE-DRIVEN SHARE SHIFT IS LEGITIMATE (a check on the stickiness block above):
- Stickiness does NOT mean prices have no effect. A SUSTAINED, VISIBLE
  price gap — a firm pricing meaningfully below its peers, quarter after
  quarter, with a credible product — IS a catalyst. New patients enter
  the market every quarter; payers re-bid contracts; physicians become
  aware of cost-effective alternatives. Over several quarters, a real
  price advantage will move share toward the cheaper firm.
- When you observe a sustained price gap in the firm panel, do NOT
  suppress its effect just because share moves gradually quarter-by-
  quarter. The right pattern is: the cheaper firm gains share STEADILY
  but VISIBLY, while the higher-priced firms see share erosion at the
  margin. The cumulative effect over many quarters can be substantial —
  that is how price competition actually works in real industries.
- The narrative should reflect this when relevant. Name the dynamic:
  "Firm X's sustained pricing below peers has begun to win contract
  business with regional payers; share is migrating gradually."
- A SINGLE quarter of price-cutting is not yet a catalyst — it might
  be a one-off response to inventory pressure. But a sustained pattern
  IS one. Read the trajectory, not just this-quarter's snapshot.

DEMAND IS PHYSICALLY BOUNDED (not a prescription — a check on your own math):
- The industry's stated TAM (above, in industry character) describes a
  finite addressable market — a finite population, a finite typical
  course duration per patient, and a finite willingness-to-pay range.
  Demand for a given quarter must be consistent with those facts.
- Specifically: cumulative units sold over the most recent treatment-
  course-duration window cannot exceed the addressable population times
  realistic penetration. Annual industry revenue (4 × quarterly) cannot
  meaningfully exceed the stated TAM-at-maturity, because TAM is the
  steady-state ceiling implied by population × course frequency × price.
- Capacity is a necessary condition for revenue, not a sufficient one.
  A firm with huge PPE only realises that PPE's revenue potential when
  the addressable demand exists for the units. PPE that exceeds realistic
  demand sits idle and depreciates — that is real-world over-investment,
  and your allocation should reflect it.
- This is NOT a directive to compress demand to fit a target. If the
  underlying ramp warrants growth this quarter, grant it. The constraint
  is only the physical one: the math of population × penetration × price
  must close.

COMPETITIVE REALISM (allocate honestly; do not protect or punish):
- Allocate units across firms based on what each firm is actually
  offering this quarter — price, capability stock (quality), brand
  stock (trust + relationships), distribution fit, segment focus,
  service quality. A firm with weak fundamentals (low capability,
  depleted brand, uncompetitive price, weak distribution) loses
  marginal customers to firms with stronger fundamentals. A firm
  with strong fundamentals attracts them.
- Do NOT protect weak firms from competition by inflating their
  share. Do NOT artificially smooth allocations across firms to
  keep a level playing field. The competitive consequences — share
  loss, revenue decline, cash burn — are real and should land where
  the fundamentals say they should land.
- Equally, do NOT punish firms beyond what the fundamentals justify.
  If a sub-scale firm is offering a credible differentiated product
  to a real niche, they retain that niche's customers.
- Whatever happens to weak firms downstream (cash exhaustion, covenant
  breach, default, takeover) is the job of the settlement / bankruptcy
  / M&A machinery operating on the financials you produce. Your job is
  honest allocation given fundamentals; theirs is to translate that
  into structural outcomes.

INDUSTRY STRUCTURE — WHY A REAL MARKET DOES NOT SUPPORT AN UNLIMITED FIRM COUNT:
- Real pharmaceutical industries consolidate around a small number of
  brand families. Hospital procurement, payer formulary slots, physician
  relationships, and regulatory inspection capacity all favour scale.
  A firm that cannot reach a meaningful share of these institutional
  buyers struggles to monetise even good science.
- Returns to scale matter. Clinical-trial fixed costs are large and
  amortise better over higher volume. Manufacturing yield improves with
  scale. Brand investment compounds. A small fragmented set of sub-scale
  firms all carry the SAME fixed costs but generate less revenue per
  firm to cover them — that is structurally unstable. Some of them will
  not survive.
- Entrants are NOT homogeneous. New entrants often come in with weaker
  IP, less experienced founding teams, or thinner safety/efficacy data
  than the entrenched leaders. Their disadvantage is not always visible
  on day one — it surfaces over time as their R&D under-performs, their
  clinical readouts disappoint, their differentiation thesis fails to
  hold. When you allocate, you can reflect this heterogeneity: a recent
  entrant with no operating track record should NOT command the share
  of an entrenched leader with equivalent stated capability/brand,
  because the leader's track record is itself an information signal
  that the entrant has not yet earned.
- Therefore: a market with many active firms, when followed honestly
  over time, naturally winnows. Sub-scale firms with weak fundamentals
  lose ground to leaders quarter by quarter. Some firms run out of
  cash. Some get acquired. Some recover. This is the SHAKE-OUT, and
  it is the normal life of an industry — not something you should
  resist, but also not something you should force. Allocate honestly
  on fundamentals; the structural outcomes follow.
- When you NARRATE the quarter, name the dynamics. If a firm is losing
  share to a leader, say why: stronger brand, better trial readouts,
  superior distribution, lower side-effect profile. If an entrant has
  weak underlying technology, surface it through observable narrative
  (a disappointing readout, a manufacturing setback, slower than expected
  ramp) — not as a hidden penalty but as the market revealing what was
  always true.

You are REALISTIC and CONSISTENT, not adversarial. Do not "rebalance" firms just because
one is dominating — real markets don't mean-revert that way.

YOU DECIDE:
1. TOTAL DEMAND: treatment courses sold, informed by baseline + macro shocks + events.
   Be thoughtful about QoQ changes.
2. MARKET SHARES: allocation based on price, quality, brand, customer service, and
   incumbency. Changes have reasons.
3. R&D OUTCOMES: process improvements (small COGS reductions) AND generation
   advances (Gen 1 → Gen 2 → Gen 3 → …).

   GENERATION ADVANCES ARE THE PRIMARY STORY OF THIS INDUSTRY. The whole
   point of a longevity-therapy market is that science progresses.
   Gen-1 → Gen-2 should fire on a typical leading firm somewhere in the
   first 3–6 years of operation; Gen-2 → Gen-3 follows. A simulation that
   reports every firm permanently stuck at Gen-1 across 20 fiscal years
   is unrealistic and not what the industry character supports — it
   means you have under-granted.

   For each firm, READ THE PANEL FIELD `Cumulative R&D: product=$X.XM …`
   together with `Operational tenure: NQ active`. These are the
   investment-and-time facts you need. Then ask:

     - Has the firm invested in product R&D consistently for many quarters,
       relative to its peers and to the cumulative effort a major
       generational leap plausibly requires? (Use the `Cumulative R&D`
       field directly — that IS the track record.)
     - Has the firm been operating long enough — and profitably enough —
       to have actually run the clinical work, regulatory filings, and
       manufacturing readiness this requires? (Use the `Operational
       tenure` field + the trajectory block's profitability picture.)
     - Is there a credible scientific story for this firm right now —
       a Phase 3 readout, a lead-compound milestone, a manufacturing
       breakthrough, a regulatory inflection?
     - Are there peers further along that have already advanced, suggesting
       the technology frontier has moved? (And: if NO peer has advanced
       after years of cumulative industry R&D, look harder at which firm
       is closest to ready — the frontier moves when leaders move it.)

   When you see sustained R&D investment (the `Cumulative R&D` figure
   is large relative to peers), operational longevity (multi-year tenure),
   no specific blocker, and a credible scientific story, the default is to
   GRANT `product_advance: true` this quarter and narrate the catalyst.

   "They haven't advanced yet", "I want to be conservative", or "no firm
   has reached the frontier yet" are NOT valid reasons to refuse the
   leading firm. A specific event IS — a failed Phase 3 readout, an FDA
   hold, a named scientist departure, a manufacturing failure, a safety
   signal in a competitor's programme that triggers regulatory caution
   industry-wide.

   Spread advances across firms over time. When you grant, the narrative
   MUST identify the specific catalyst. When you decline a firm that
   visibly has the investment + the operating track record, the narrative
   MUST name the specific blocker.

   Real industries see periodic generation transitions. If you find
   yourself in year 5+ of the simulation with EVERY firm still at Gen-1
   despite some firms having large cumulative R&D and years of operation,
   you are systematically under-granting — the right correction is to
   identify the leader and grant. Across a multi-year run, you SHOULD
   advance the leader once they have done the work, and you should
   advance later firms as they catch up.
4. EVENTS: occasional (0-1 per quarter usually). Time them to context.
5. NARRATIVE: 2-3 paragraph industry summary. Large demand/share moves must be
   explained with specific causes.

STRUCTURAL CONSTRAINTS (mathematical, not judgment):
- Market shares sum to ~1.0
- units_sold for each firm MUST NOT exceed their production + inventory (physical cap)

Output a single JSON object in ```json ... ``` block."""


def build_environment_prompt(
    firms: dict[str, FirmState],
    actions: dict[str, dict],
    macro: MacroState,
    baseline_demand: int,
    baseline_shares: dict[str, float],
    params: SimParams,
    last_gazette: str = "",
    rd_reports: dict[str, RDReport] | None = None,
    brand_reports: dict[str, BrandReport] | None = None,
    data_dir: str = "data",
    earnings_management_enabled: bool = False,
    compustat_rows: list | None = None,
    working_capital_decisions: bool = False,
    bad_debt_enabled: bool = False,
    env_decision_overrides_enabled: bool = False,
    industry_character: dict | None = None,
    demand_calibrator_estimate: dict | None = None,  # Wave ν+5
    regional_markets_enabled: bool = True,           # Wave ν+6 toggle
    extended_history_block: str = "",                # Wave ν+12: full-history render from agent_history
) -> tuple[str, str]:
    """Build (system, user) prompts for the environment's market resolution.

    If earnings_management_enabled, the env sees each firm's true manipulation
    stock and decides (as the omniscient observer) when anomalies become
    detectable by regulators — producing detection_tips for the SEC.

    `regional_markets_enabled` (Wave ν+6 toggle): when True (default), the
    env system prompt includes the horizontal-differentiation block telling
    the env that consumers have idiosyncratic geographic / segment / channel
    preferences. When False, that block is stripped — the env allocates
    demand on price/capability/brand alone (homogeneous market).
    """

    # Wave ν+13: STRICT mandatory-generation-advance rules at the very TOP
    # of the env prompt. The env is the ONLY agent that sees these numerical
    # thresholds — firms see only rough qualitative guidance from the scenario.
    # Validator (env_verifier.make_env_validator) re-checks these criteria
    # after env returns and sends the output back if any mandatory grant
    # was missed without a named blocker.
    try:
        _gen2_thr = float(getattr(params, "gen_2_rd_threshold", 500_000_000))
    except (TypeError, ValueError):
        _gen2_thr = 500_000_000.0
    _gen3_thr = _gen2_thr * 2.0
    _gen4_thr = _gen2_thr * 4.0
    strict_gen_block = (
        "=== MANDATORY GENERATION ADVANCES — APPLY BEFORE EVERYTHING ELSE ===\n\n"
        "For each firm in the FIRM PANEL below, run this check FIRST every\n"
        "quarter, BEFORE allocating demand or writing the narrative. The\n"
        "rules are STRICT: if a firm satisfies a tier's criteria, you MUST\n"
        "grant `product_advance: true` for that firm this quarter. Non-\n"
        "optional. The env validator will check your output and SEND IT\n"
        "BACK if a mandatory grant is missed without a named blocker.\n\n"
        "Read the panel field `Cumulative R&D: product=$X.XM` and the\n"
        "`Operational tenure: NQ active` field together with `Gen: <n>`.\n\n"
        f"TIER 1 — Gen 1 → Gen 2 (mandatory):\n"
        f"  * cumulative product R&D ≥ ${_gen2_thr/1e6:,.0f}M\n"
        f"  * AND operational tenure ≥ 4 quarters\n"
        f"  * AND firm is currently Gen 1\n"
        f"  → You MUST set product_advance=true for this firm.\n\n"
        f"TIER 2 — Gen 2 → Gen 3 (mandatory):\n"
        f"  * cumulative product R&D ≥ ${_gen3_thr/1e6:,.0f}M\n"
        f"  * AND operational tenure ≥ 8 quarters\n"
        f"  * AND firm is currently Gen 2\n"
        f"  → You MUST set product_advance=true.\n\n"
        f"TIER 3 — Gen 3 → Gen 4 (mandatory):\n"
        f"  * cumulative product R&D ≥ ${_gen4_thr/1e6:,.0f}M\n"
        f"  * AND operational tenure ≥ 12 quarters\n"
        f"  * AND firm is currently Gen 3\n"
        f"  → You MUST set product_advance=true.\n\n"
        "EXCEPTIONS — when you may decline a mandatory grant:\n"
        "The ONLY valid reasons to decline are a specific, NAMED blocker:\n"
        "  - A failed Phase 3 readout in the last 4 quarters\n"
        "  - An active FDA hold or regulatory adverse action\n"
        "  - A named scientific failure (lead compound failed, manufacturing\n"
        "    process abandoned, key scientist or named team departed)\n"
        "  - A safety signal in the firm's own programme\n"
        "If you decline a mandatory grant, you MUST name the specific blocker\n"
        "in your narrative or in the firm_notes section. 'Conservative\n"
        "judgment', 'wait and see', 'no peer has advanced yet', and 'they\n"
        "should keep investing' are NOT valid blockers and will cause the\n"
        "validator to send your output back.\n\n"
        "WHY THIS IS STRICT: prior runs systematically under-granted Gen\n"
        "advances — every firm sat at Gen 1 for 80 quarters despite some\n"
        "firms accumulating multi-$B of product R&D. The strict tier\n"
        "rules above eliminate that failure mode.\n\n"
        "===================================================================\n\n"
    )
    system = strict_gen_block + ENV_SYSTEM_PROMPT
    if not regional_markets_enabled:
        # Strip the regional / horizontal-differentiation block. Markers
        # are placed in the constant for surgical removal.
        start = system.find("# REGIONAL_BLOCK_START")
        end = system.find("# REGIONAL_BLOCK_END")
        if start >= 0 and end >= 0:
            # Drop the block + the trailing newline after the END marker
            after_end = end + len("# REGIONAL_BLOCK_END")
            if after_end < len(system) and system[after_end] == "\n":
                after_end += 1
            system = system[:start] + system[after_end:]

    # Wave ι: prepend scenario's industry character so the env calibrates
    # demand realism to the scenario's industry (longevity, mature, declining).
    ic_block = _format_industry_character_block(industry_character or {})
    if ic_block:
        system = system + ic_block

    # Wave ν: post-innovation sales-potential block. Reminds the env that
    # each firm's addressable market ceiling depends on HOW ADVANCED the
    # product is, not just current quarter revenue. As firms invest in
    # R&D and advance generation, their upside should scale with what
    # the scenario's TAM implies. No hardcoded numbers — the env reads
    # the scenario narrative and calibrates accordingly.
    system = system + """

POST-INNOVATION UPSIDE (sales potential after R&D advancement):
When a firm advances its product generation or meaningfully grows its
capability stock, its addressable market UPSIDE grows toward the
industry's mature-market TAM described in the scenario above. For a
given quarter:

  - A firm still at a low generation level faces a limited addressable
    sub-segment of the scenario TAM — the early-adopter population who
    accept the current product profile at current risk/benefit.
  - A firm that advances generation unlocks a larger addressable
    population: safer/more effective products expand the addressable
    subset, AND the willingness-to-pay band widens.
  - At full maturity (standard-of-care), the industry can approach the
    scenario's stated mature-market TAM. Forward-looking judgment
    should weight current-quarter demand against this trajectory — a
    firm with strong R&D momentum deserves a larger demand pool than
    a firm with comparable current revenue but no pipeline.

When narrating, explicitly connect generation advancement or capability
growth to the firm's expanded addressable market. Do NOT let current-
quarter revenue anchor you to a small demand pool if the scenario's
mature market is dramatically larger and firms are credibly advancing
toward it."""

    if earnings_management_enabled:
        system = system + """

EARNINGS MANAGEMENT DETECTION (when EM is enabled):
You are omniscient — you know each firm's TRUE accounting manipulation versus what
they've reported. Each quarter, judge whether an external observer (SEC, auditors,
short-sellers) would realistically notice statistical anomalies.

Consider: how large is the cumulative overstatement/understatement? How sustained?
How does it compare to typical accrual volatility? Is it concentrated in one period
or spread thin? Would it trip industry-standard screens?

Produce detection_tips: a list of brief anomaly flags that feed into SEC surveillance.
Each tip names the firm and describes the anomaly pattern. Detection should NOT be
automatic — small, isolated manipulation may stay hidden; large or persistent
manipulation should eventually surface. You judge when and how."""

    if working_capital_decisions:
        system = system + """

SUPPLIER & CUSTOMER FRICTION (when working_capital_decisions enabled):
Firms set their own DPO (payables_days_target), DSO (receivables_days_target),
and deposit_pct. Judge whether their choices create real-world friction:

  - A firm stretching DPO far beyond peers may see suppliers tighten terms or
    raise prices. Mild stretch is fine; aggressive stretch creates trouble.
  - A firm offering long DSO may gain volume but take on bad-debt risk.
  - A firm demanding large upfront deposits may deter some customers but
    improve cash quality.

You may include per-firm commentary in your narrative. Demand effects (if any)
should flow through your units_sold allocation — don't create magic penalties,
just let customer preference emerge naturally."""

    if bad_debt_enabled:
        system = system + """

BAD DEBT WRITE-OFFS (when bad_debt_enabled):
Each firm carries an allowance_for_doubtful_accounts set by management. You
decide the REAL write-offs that occur this quarter, based on the firm's credit
policy (DSO, customer mix implied by their behavior), gross AR size, and macro
conditions. Small write-offs should be frequent; large write-offs concentrated
in distressed periods or stretched-credit firms.

Output a list of write_offs (by firm_id + amount) in the JSON response. If no
write-offs this quarter, return an empty list. Don't mechanically tie write-offs
to the allowance — that's the firm's estimate; yours is the reality.

WAVE ν+14h F3 EXPLICIT REQUIREMENT — do not skip this decision:
A real industry will see PERIODIC bad-debt write-offs across firms over time.
A small fraction of customer AR genuinely becomes uncollectible each year:
payer disputes, hospital insolvency, individual non-payment, fraud. The
realistic pattern is occasional small write-offs spread across firms.

If you find yourself returning `write_offs: []` quarter after quarter while
firms are accruing meaningful bad_debt_expense (>$1M/Q for any firm), that
pattern means the firms' allowance is growing without ever being realized as
cash loss — economically unrealistic. Each quarter, briefly think: "which of
the firms has the kind of customer mix or distressed-credit profile that
would PLAUSIBLY produce a small write-off this quarter?" and reflect that
in your write_offs list. The total can be tiny (a few $M industry-wide most
quarters) but it should not be zero forever."""

    if env_decision_overrides_enabled:
        system = system + """

DECISION OVERRIDES (when env_decision_overrides_enabled):
Firm decisions are submitted as BUDGETS/TARGETS. In reality, some plans
aren't feasible — operations are sticky, costs can't drop instantly, people
don't disappear overnight. You are allowed to OVERRIDE specific firm
decisions when the budget is clearly unrealistic.

Common cases where override is appropriate:
  - Firm sets SGA=$0 but has 100+ employees and existing rent/insurance/legal
    obligations → override upward to a realistic floor.
  - Firm cuts production to 0 without a clear reason → if the firm has
    workforce and contractual supply, production may not go to zero.
  - Firm promises instant large cost cuts when stickiness would spread the
    cut across multiple quarters.
  - CASH SQUEEZE: if a firm's cash is very low and your overrides push it
    negative, reflect the operational disruption. Cut production (can't
    afford inputs), accelerate AR (factor receivables for quick cash),
    reduce capex, or delay payments. Don't force an infeasible plan.

Default is PASS-THROUGH: do not override unless clearly infeasible.
Legitimate strategic shifts are firm's call.

Output `decision_overrides` JSON, each:
  {"firm_id": "...", "field": "sga_spend|production|capex|rd_spend|...",
   "budgeted": <firm's target>, "actual": <your override>,
   "reasoning": "<1-2 sentences: why the budget was infeasible>"}

Additionally, when you moderate a firm's plan, ALWAYS include a note in
`firm_notes` so the firm's management doesn't hallucinate next quarter
that their original plan executed as-designed:
  {"firm_id": "...",
   "note": "<2-3 sentences describing what actually happened — cash
     squeeze disrupted production, 20 units unshippable, receivables
     factored at discount, etc. Uses `you` framing.>"}

Empty lists when nothing to moderate."""

    # Add self-improvement analysis from past runs
    env_analysis = run_environment_analysis(data_dir)
    if env_analysis:
        system = system + "\n\n" + env_analysis

    # Build firm actions table
    firm_lines = []
    production_caps = []
    for fid in sorted(actions.keys()):
        firm = firms.get(fid)
        act = actions[fid]
        if firm is None or not firm.is_active:
            continue

        price = act.get("price", 0)
        prod = act.get("production", 0)
        production_caps.append(f"{fid}={prod}")

        from .personalities import get_company_name
        try:
            _idx = int(fid.split("_")[-1])
        except (ValueError, IndexError):
            _idx = 0
        name = get_company_name(_idx).split()[0]  # short form (first word)
        baseline_units = int(baseline_demand * baseline_shares.get(fid, 0.2))

        em_line = ""
        if earnings_management_enabled:
            cumul = firm.cumulative_manipulation
            this_q = firm.manipulation_this_quarter
            if abs(cumul) > 1.0 or abs(this_q) > 1.0:
                em_line = (f"\n  EM state (HIDDEN): cumulative ${cumul:+,.0f}, "
                           f"this Q ${this_q:+,.0f} [you see truth; others don't]")

        # Wave ν+6: per-firm idiosyncratic differentiation profile.
        # Surfacing these dimensions prevents the env from collapsing
        # to a single-firm winner-take-all allocation — different firms
        # serve different geographic / patient / channel segments and
        # have distinct signature features, so they can't all be
        # substituted by one product.
        diff_lines = []
        if firm.geographic_focus:
            diff_lines.append(f"  Geographic focus: {firm.geographic_focus}")
        if firm.patient_segment:
            diff_lines.append(f"  Target patient segment: {firm.patient_segment}")
        if firm.distribution_channel:
            diff_lines.append(f"  Distribution channel: {firm.distribution_channel}")
        if firm.signature_feature:
            diff_lines.append(f"  Signature product feature: {firm.signature_feature}")
        diff_block = "\n".join(diff_lines)

        # Wave ν+12: surface the cumulative R&D track record and operational
        # tenure the Gen-N directive asks the env to evaluate. Without these,
        # the env had no signal of "has this firm invested consistently?" and
        # defaulted to refusing every advance across multiple 80Q runs.
        try:
            cum_prod = float(getattr(firm, "rd_cumulative_product", 0.0) or 0.0)
        except (TypeError, ValueError):
            cum_prod = 0.0
        try:
            cum_proc = float(getattr(firm, "rd_cumulative_process", 0.0) or 0.0)
        except (TypeError, ValueError):
            cum_proc = 0.0
        try:
            cum_deliv = float(getattr(firm, "rd_cumulative_delivery", 0.0) or 0.0)
        except (TypeError, ValueError):
            cum_deliv = 0.0
        # Tenure: count this firm's compustat rows (one per quarter active)
        tenure_q = 0
        if compustat_rows:
            tenure_q = sum(1 for r in compustat_rows if r.firm_id == fid)
        tenure_str = f"{tenure_q}Q active" if tenure_q > 0 else "new this quarter"

        firm_lines.append(f"""{fid} ({name})
  Price: ${price:,}
  Production: {prod} (capacity {firm.capacity_units})
  Quality: {firm.capability_stock:.0f}/100
  Brand: {firm.brand_stock:.0f}/100
  Gen: {firm.product_generation}
  Cumulative R&D: product=${cum_prod/1e6:.1f}M  process=${cum_proc/1e6:.1f}M  delivery=${cum_deliv/1e6:.1f}M
  Operational tenure: {tenure_str}
{diff_block}
  Baseline allocation: {baseline_units} units ({baseline_shares.get(fid, 0.2):.1%}){em_line}""")

    firms_text = "\n\n".join(firm_lines)
    caps_text = ", ".join(production_caps)

    # ── Per-firm trajectory (shows env its own prior outputs) ───────────
    trajectory_block = ""
    if compustat_rows:
        per_firm: dict = {}
        by_qtr: dict = {}
        for r in compustat_rows:
            per_firm.setdefault(r.firm_id, []).append(r)
            key = (r.fyearq, r.fqtr)
            by_qtr.setdefault(key, {"total": 0.0, "firms": {}})
            by_qtr[key]["total"] += r.saleq
            by_qtr[key]["firms"][r.firm_id] = r.saleq

        traj_lines = []
        for fid in sorted(firms.keys()):
            if not firms[fid].is_active:
                continue
            firm_rows = sorted(per_firm.get(fid, []),
                               key=lambda r: (r.fyearq, r.fqtr))[-6:]
            if not firm_rows:
                continue
            rev_parts = []
            share_parts = []
            for r in firm_rows:
                key = (r.fyearq, r.fqtr)
                total = by_qtr[key]["total"]
                share = r.saleq / total if total > 0 else 0
                rev_parts.append(f"${r.saleq/1e6:.0f}M")
                share_parts.append(f"{share:.0%}")
            traj_lines.append(
                f"  {fid}: revenue {' -> '.join(rev_parts)} | "
                f"share {' -> '.join(share_parts)}"
            )

        # Industry total demand trajectory
        sorted_qtrs = sorted(by_qtr.keys())
        industry_totals = [f"${by_qtr[k]['total']/1e6:.0f}M" for k in sorted_qtrs[-6:]]

        if traj_lines:
            trajectory_block = (
                "\nYOUR PRIOR OUTCOMES (last up to 6 quarters, so you can see the "
                "trajectory you've been producing):\n"
                + "\n".join(traj_lines)
                + f"\n  INDUSTRY TOTAL REVENUE: {' -> '.join(industry_totals)}\n"
                + "  Notice patterns: if one firm has been dominating or revenue has "
                "been moving sharply, ask whether continued movement is realistic or "
                "if something should self-correct (market saturation, competitive "
                "response, patient caps, price fatigue)."
            )

    # Price comparison
    prices = {fid: actions[fid].get("price", 0) for fid in sorted(actions.keys())}
    avg_price = sum(prices.values()) / max(1, len(prices))
    price_comp_lines = []
    for fid in sorted(prices, key=lambda x: prices[x]):
        p = prices[fid]
        diff_pct = (p - avg_price) / avg_price * 100 if avg_price > 0 else 0
        label = "CHEAPEST" if p == min(prices.values()) else "MOST EXPENSIVE" if p == max(prices.values()) else ""
        price_comp_lines.append(f"  {fid}: ${p:,} ({diff_pct:+.1f}% vs avg) {label}")
    if len(set(prices.values())) == 1:
        price_comp_lines.append("  *** ALL FIRMS PRICED IDENTICALLY -- allocate based on quality, brand, and taste shocks ***")
    price_comparison_text = "\n".join(price_comp_lines)

    # Build taste shock info
    taste_lines = []
    for fid in sorted(actions.keys()):
        ts = macro.taste_shocks.get(fid, 0)
        direction = "favorable" if ts > 0.02 else "unfavorable" if ts < -0.02 else "neutral"
        taste_lines.append(f"  {fid}: {direction} ({ts:+.3f})")
    taste_text = "\n".join(taste_lines)

    # Wave ν+5: demand calibrator block (separate market-research voice)
    calibrator_block = ""
    if demand_calibrator_estimate:
        units_anchor = demand_calibrator_estimate.get("total_units_demanded", 0)
        calib_reason = demand_calibrator_estimate.get("qualitative_reasoning", "")
        calib_trend = demand_calibrator_estimate.get("trend_note", "")
        calibrator_block = (
            f"\n=== DEMAND CALIBRATOR ESTIMATE (your ANCHOR for total demand this quarter) ===\n"
            f"Total units to allocate this quarter: {int(units_anchor):,}\n"
            f"Calibrator's reasoning: {calib_reason[:500]}\n"
            f"Trend: {calib_trend[:200]}\n"
            f"Use this as your anchor — calibrate your total share allocation toward "
            f"this number rather than your own first instinct (which tends to "
            f"under-estimate).\n"
        )

    # Wave ν+12: an extensive "everything you need to know" history block,
    # produced by src.agent_history.render_environment_full_history and
    # passed in by the caller. If empty, the prompt falls back to the
    # legacy compact panel + 6Q trajectory block below.
    history_section = ""
    if extended_history_block:
        history_section = (
            "\n\n=== HISTORICAL CONTEXT (everything that has happened so far) ===\n"
            "Read these tables carefully — they are the basis for evaluating\n"
            "which firms have invested consistently, which have a viable\n"
            "trajectory, and which firms' R&D track record now justifies a\n"
            "generation advance. The compression rule: every 4th quarter for\n"
            "older history, every quarter for the last 8. THIS IS YOUR LONG-\n"
            "RUN MEMORY OF WHAT HAS HAPPENED — USE IT.\n\n"
            f"{extended_history_block}\n"
        )

    user = f"""=== QUARTER: Q{macro.fqtr} {macro.fyear} ==={calibrator_block}{history_section}

MACRO: Risk-free {macro.risk_free_rate*400:.1f}% annual, Awareness {macro.awareness_rate:.0%}, Shock {macro.macro_shock:+.2f}

TASTE SHOCKS THIS QUARTER (random patient/physician preference shifts):
{taste_text}
These should cause small but real differences from the baseline allocation.

DEMAND BASELINE (from logit model): {baseline_demand} units total

PRICE COMPARISON (lower price should gain share, higher price should lose share):
{price_comparison_text}

FIRM ACTIONS THIS QUARTER (last quarter's full detail):

{firms_text}
{trajectory_block}

{format_reports_for_environment(rd_reports, brand_reports) if rd_reports and brand_reports else '(No operational reports yet -- first quarter)'}

PRODUCTION CAPS (units_sold MUST NOT exceed): {caps_text}

{f'LAST GAZETTE:{chr(10)}{last_gazette[:500]}' if last_gazette else 'LAST GAZETTE: (first quarter)'}

Output JSON:

```json
{{
  "total_demand": <integer>,
  "demand_rationale": "<1 sentence>",
  "firm_outcomes": [
    {{"firm_id": "<id>", "units_sold": <int>, "market_share": <0-1>}}
  ],
  "rd_outcomes": [
    {{"firm_id": "<id>", "product_advance": false, "process_cogs_reduction_pct": <fraction, typically small per Q>, "delivery_advance": false}}
  ],
  "events": [],
  "narrative": "<2-3 paragraph summary>",
  "detection_tips": [],
  "write_offs": [],
  "decision_overrides": [],
  "firm_notes": []
}}
```

`write_offs` (when bad_debt_enabled) is a list of {{"firm_id": "...", "amount": <$>}}
representing REAL AR write-offs the firm has to book this quarter.

`decision_overrides` (when env_decision_overrides_enabled) is a list of
{{"firm_id": "...", "field": "...", "budgeted": <firm target>, "actual": <real>,
"reasoning": "..."}}. Leave empty unless a firm budget was physically
infeasible.

`firm_notes` (when env_decision_overrides_enabled) is a list of
{{"firm_id": "...", "note": "..."}} explaining to the firm's management what
ACTUALLY happened despite their plan — shown on their prompt next quarter
so they don't hallucinate their original plan executed as-designed.

`detection_tips` is for earnings management detection (when enabled). Empty list if
no firm's manipulation is detectable this quarter. Otherwise a list of strings naming
the firm and the anomaly you'd expect regulators/short-sellers to notice.

IMPORTANT:
- units_sold must sum EXACTLY to total_demand
- No firm can exceed their production cap
- Do NOT give the same numbers as last quarter. Market conditions shift every quarter
  due to taste shocks, brand changes, and firm actions. Even if firm actions are similar,
  your allocation should vary by at least a few percent due to random patient preferences.
- Do NOT use perfectly round numbers for units_sold. Real markets have irregular demand.
  Example: 187 is better than 200; 213 is better than 210."""

    return system, user
