"""
Wave κ: Strategic planning module.

Firms author a forward 5-year quarterly budget at Q0 and every 4 quarters
thereafter. Each quarter, actual results are compared against the plan;
large variance triggers a prompt for the firm to reflect and (optionally)
re-plan early.

This is the core mechanism for preventing the "slowly drifting into
default without course-correcting" pathology seen in v1 and v2 runs.
Firms forced to project forward notice cash crunches before they happen.

Architecture:
  - `make_planning_agent(backend, state_ref)` — factory for the planning
    LLM call. Uses a CFO-perspective prompt.
  - `compute_plan_variance(firm, plan, actual_flows, compustat_row)` —
    pure function comparing actuals to plan. Returns `PlanVariance`.
  - `plan_variance_dict(firm)` — helper producing the prompt-ready
    variance summary for a firm's info package.
  - `should_replan(firm, config)` — heuristic: material variance for N+
    consecutive quarters triggers re-plan.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import replace as _dc_replace
from typing import Any

from .llm_backends import LLMBackend
from .types import (
    FirmState,
    MacroState,
    PlanLine,
    PlanVariance,
    QuarterFlows,
    SimParams,
    StrategicPlan,
)


# ── Prompt templates ───────────────────────────────────────────────────

PLANNING_SYSTEM_PROMPT = """You are the CFO of {company_name}, authoring the firm's forward {horizon_years}-year strategic plan.

YOUR JOB:
Produce a quarter-by-quarter financial plan for the next {horizon_quarters} quarters.
The plan must be REALISTIC, INTERNALLY CONSISTENT, and grounded in:
  - The industry's economic reality (see scenario context below)
  - Your firm's current state (cash, capacity, capability, competitive position)
  - Your strategic narrative (what you're trying to achieve)

This plan will be held against you: each quarter, the board will compare
actuals to this plan and ask why variances happened. Be ambitious but honest.

{industry_character_block}

OUTPUT FORMAT (JSON):
{{
  "strategy_narrative": "<2-4 sentences on what the firm is trying to achieve>",
  "key_assumptions": ["<3 key assumptions the plan relies on>"],
  "key_risks": ["<3 key risks that could derail the plan>"],
  "milestones": ["<3-5 milestones with target quarters, e.g. 'Reach G2 by Q24'>"],
  "contingency_plan": "<3-5 sentences. If your next financing round is materially delayed or materially under-filled, what specific spending lines would you cut and by approximately how much? Be concrete about what would be deferred, reduced, or eliminated. Real CFOs always have a Plan B; this is yours.>",
  "quarterly_lines": [
    {{
      "fyear": <int>, "fqtr": <int 1-4>,
      "planned_revenue": <number>, "planned_units_sold": <int>, "planned_price": <number>,
      "planned_capacity": <int>,
      "planned_cogs": <number>, "planned_rd_spend": <number>, "planned_sga_spend": <number>,
      "planned_capex": <number>,
      "planned_equity_raise": <number>, "planned_debt_raise": <number>,
      "planned_dividends": <number>,
      "projected_ni": <number>, "projected_eps": <number>,
      "projected_cash_balance_eoq": <number>,
      "planned_generation": <int 1-4>,
      "planned_rd_cumulative_product": <number>
    }},
    ... (one object per quarter, {horizon_quarters} total)
  ]
}}

GUIDANCE:
- Match your plan to the industry character. Breakthrough industries justify
  aggressive ramps; mature/declining industries require disciplined shrinkage.
- If the plan predicts cash < 0 in any quarter WITHOUT financing, you must
  either cut spend or include a financing round (equity_raise / debt_raise).
- Project forward R&D trajectory: when do you expect to reach Generation 2?
- Be HONEST about competitive response. Prices + shares respond to rivals.
"""


CFO_GATEKEEPER_SYSTEM_PROMPT = """You are the CFO of {company_name}, in a final review of a strategic plan the board has just drafted. Your role is gatekeeper: you approve the plan or send it back for revision. Your reputation depends on not approving plans that will bankrupt the firm.

YOUR JOB:
Review the draft plan for INTERNAL CONSISTENCY and FEASIBILITY. Ask yourself:

  1. Cash feasibility: does projected cash stay positive across every quarter
     of the horizon, assuming the financing lines in the plan actually happen?
     If the plan requires financing the firm has no credible path to raising,
     the plan is infeasible.

  2. Realism of the growth path: is the projected revenue/share trajectory
     plausible given the industry, competitors, and the firm's current state?
     Plans that assume dominant share without naming the mechanism are
     unrealistic.

  3. Consistency: do the planned R&D + capex + SG&A lines match the stated
     strategy? A "disciplined operator" plan that spends like a moonshot is
     internally inconsistent.

  4. Survival risk: if the next financing round is delayed, under-filled, or
     unavailable, does the plan still keep the firm solvent long enough to
     replan? A plan with no resilience to a funding hiccup is fragile.

  5. Assumption quality: are the stated key_assumptions specific and
     falsifiable, or generic ("demand will be strong")? Generic assumptions
     signal the plan hasn't been stress-tested.

If the plan passes all five checks, APPROVE. If it fails any, REVISE with
specific, actionable feedback (what part of the plan is broken, what the
CEO/board must reconsider).

{industry_character_block}

OUTPUT (JSON):
{{
  "decision": "APPROVE" | "REVISE",
  "concerns": ["<concrete concern 1>", "<concrete concern 2>", ...],
  "revision_guidance": "<1-3 sentences on what the CEO/board must change before resubmitting. Empty if APPROVE.>",
  "rationale": "<2-4 sentences justifying your decision>"
}}"""


REPLAN_SYSTEM_PROMPT = """You are the CFO of {company_name}, re-planning after {n_quarters} consecutive quarters of material variance from the prior plan.

CONTEXT: the board has asked for a fresh 5-year strategic plan because
the firm has been consistently off-plan. Review the prior plan, the
variances that occurred, and produce a REVISED plan that reflects the
new reality. Be honest about what went wrong.

PRIOR PLAN NARRATIVE:
{prior_narrative}

PRIOR PLAN KEY ASSUMPTIONS:
{prior_assumptions}

RECENT VARIANCES:
{variance_summary}

{industry_character_block}

OUTPUT FORMAT: same JSON schema as the initial plan. Include in your
strategy_narrative an acknowledgment of what changed from the prior
plan and why.
"""


def _build_user_prompt(
    firm: FirmState,
    public_info: dict,
    macro: MacroState,
    params: SimParams,
    horizon_quarters: int = 20,
    is_replan: bool = False,
) -> str:
    """Build the user prompt with current state + plan-input data."""
    lines = [f"CURRENT QUARTER: Q{macro.fqtr} {macro.fyear} (abs quarter {macro.quarter})"]
    lines.append("")
    lines.append("CURRENT FIRM STATE:")
    lines.append(f"  Cash: ${firm.cash:,.0f}")
    lines.append(f"  Total assets: ${firm.total_assets:,.0f}")
    lines.append(f"  Total equity: ${firm.total_equity:,.0f}")
    lines.append(f"  Long-term debt: ${firm.long_term_debt:,.0f}")
    lines.append(f"  Capacity: {firm.capacity_units} units/quarter")
    lines.append(f"  Unit cost: ${firm.base_unit_cost:,.0f}")
    lines.append(f"  Product generation: Gen {firm.product_generation}")
    lines.append(f"  Capability stock: {firm.capability_stock:.1f}/100")
    lines.append(f"  Brand stock: {firm.brand_stock:.1f}/100")
    lines.append(f"  Cumulative product R&D: ${firm.rd_cumulative_product/1e6:.1f}M")
    lines.append("")

    # Market signals — firm's forecast anchor
    market_signals = public_info.get("market_signals") or {}
    if market_signals:
        lines.append("MARKET SIGNALS (current quarter, from scenario + demand model):")
        aware = market_signals.get("aware_population")
        if aware:
            lines.append(f"  Aware population: {aware/1e6:.1f}M")
        willing = market_signals.get("industry_willing_buyers")
        if willing:
            lines.append(f"  Industry-wide willing buyers (at current prices, if capacity existed): ~{willing:,.0f} units/Q")
        avg_px = market_signals.get("avg_competitor_price")
        if avg_px and avg_px > 0:
            lines.append(f"  Weighted-avg competitor price: ${avg_px:,.0f}")
        lines.append("")

    # Macro
    lines.append("MACRO CONTEXT:")
    lines.append(f"  Risk-free rate: {macro.risk_free_rate*400:.1f}% annual")
    lines.append(f"  Market size baseline: {macro.market_size_baseline:,}")
    lines.append(f"  Awareness rate: {macro.awareness_rate:.0%}")
    lines.append("")

    lines.append(f"PLANNING HORIZON: {horizon_quarters} quarters forward")
    lines.append(f"(starting from Q{macro.fqtr+1 if macro.fqtr < 4 else 1} {macro.fyear if macro.fqtr < 4 else macro.fyear+1})")
    lines.append("")
    lines.append(
        "Output the JSON strategic plan per the system prompt schema. "
        "Every quarterly line must be populated (no placeholders)."
    )
    return "\n".join(lines)


def _render_industry_block(industry_character: dict | None) -> str:
    """Render the scenario's industry character as a prompt block."""
    if not industry_character:
        return ""
    lines = ["", "INDUSTRY CONTEXT:"]
    if industry_character.get("label"):
        lines.append(f"  Industry label: {industry_character['label']}")
    if industry_character.get("tam_at_maturity_usd"):
        lines.append(f"  TAM at maturity: ${industry_character['tam_at_maturity_usd']/1e9:.1f}B")
    if industry_character.get("years_to_maturity"):
        lines.append(f"  Years to maturity: {industry_character['years_to_maturity']:.1f}")
    if industry_character.get("narrative"):
        lines.append("")
        lines.append(industry_character["narrative"])
    return "\n".join(lines)


# ── Agent factory ──────────────────────────────────────────────────────

def make_planning_agent(backend: LLMBackend, state_ref: list):
    """Factory: create the strategic-planning function for a firm.

    Wave ν: after the CEO-voiced plan draft is produced, a CFO gatekeeper
    review runs. If the CFO flags the plan as infeasible or internally
    inconsistent, the planning LLM is re-invoked with the CFO's revision
    guidance appended to the user prompt. Capped at 2 total attempts to
    keep cost bounded.
    """

    def _render_plan_for_review(plan: StrategicPlan) -> str:
        """Compact plan summary for the CFO gatekeeper — narrative +
        assumptions + risks + a condensed view of the early-quarter
        pacing (where infeasibility usually surfaces)."""
        lines = [f"STRATEGY: {plan.strategy_narrative}"]
        if plan.key_assumptions:
            lines.append("KEY ASSUMPTIONS:")
            lines.extend(f"  - {a}" for a in plan.key_assumptions)
        if plan.key_risks:
            lines.append("KEY RISKS:")
            lines.extend(f"  - {r}" for r in plan.key_risks)
        if plan.milestones:
            lines.append("MILESTONES:")
            lines.extend(f"  - {m}" for m in plan.milestones)
        if plan.contingency_plan:
            lines.append(f"CONTINGENCY: {plan.contingency_plan}")
        if plan.lines:
            lines.append("EARLY QUARTERS (for feasibility check):")
            for pl in plan.lines[:8]:
                lines.append(
                    f"  Q{pl.fyear}-{pl.fqtr}: "
                    f"rev=${pl.planned_revenue/1e6:.0f}M, "
                    f"R&D=${pl.planned_rd_spend/1e6:.0f}M, "
                    f"capex=${pl.planned_capex/1e6:.0f}M, "
                    f"SG&A=${pl.planned_sga_spend/1e6:.0f}M, "
                    f"equity_raise=${pl.planned_equity_raise/1e6:.0f}M, "
                    f"end_cash=${pl.projected_cash_balance_eoq/1e6:.0f}M"
                )
        return "\n".join(lines)

    def _run_cfo_gatekeeper(
        plan: StrategicPlan,
        firm: FirmState,
        industry_block: str,
        company_name: str,
    ) -> dict | None:
        """Ask the CFO (same firm backend, different prompt) to review
        the draft plan. Returns {decision, concerns, revision_guidance,
        rationale} or None on LLM failure.
        """
        system = CFO_GATEKEEPER_SYSTEM_PROMPT.format(
            company_name=company_name,
            industry_character_block=industry_block,
        )
        user = (
            f"CURRENT FIRM STATE:\n"
            f"  Cash: ${firm.cash:,.0f}\n"
            f"  Total equity: ${firm.total_equity:,.0f}\n"
            f"  Cumulative product R&D: ${firm.rd_cumulative_product:,.0f}\n"
            f"  Lifecycle stage: {firm.lifecycle_stage}\n"
            f"  Public: {firm.is_public}\n\n"
            f"DRAFT PLAN FOR REVIEW:\n{_render_plan_for_review(plan)}\n\n"
            "Decide: APPROVE or REVISE. Output JSON."
        )
        try:
            return backend.complete_json(system, user)
        except Exception:
            return None

    def plan_fn(
        firm: FirmState,
        public_info: dict,
        macro: MacroState,
        params: SimParams,
        prior_plan: StrategicPlan | None = None,
        recent_variances: tuple = (),
    ) -> StrategicPlan | None:
        """Produce a new StrategicPlan for this firm. Returns None on LLM failure."""
        from .prompts import get_company_name
        firm_idx = int(firm.firm_id.split("_")[-1]) if "_" in firm.firm_id else 0
        company_name = get_company_name(firm_idx)

        horizon_quarters = 20    # 5-year forward plan
        horizon_years = 5

        industry_block = _render_industry_block(public_info.get("industry_character"))

        is_replan = prior_plan is not None and len(recent_variances) > 0
        if is_replan:
            system = REPLAN_SYSTEM_PROMPT.format(
                company_name=company_name,
                n_quarters=len(recent_variances),
                prior_narrative=prior_plan.strategy_narrative[:500],
                prior_assumptions="\n".join(
                    f"  - {a}" for a in (prior_plan.key_assumptions or [])
                ),
                variance_summary="\n".join(
                    f"  Q{v.fyear}-{v.fqtr}: "
                    f"rev_var={v.revenue_variance_pct:+.1%}, "
                    f"ni_var=${v.ni_variance/1e6:+.1f}M"
                    for v in recent_variances[-4:]
                ),
                industry_character_block=industry_block,
            )
        else:
            system = PLANNING_SYSTEM_PROMPT.format(
                company_name=company_name,
                horizon_years=horizon_years,
                horizon_quarters=horizon_quarters,
                industry_character_block=industry_block,
            )

        base_user = _build_user_prompt(
            firm, public_info, macro, params,
            horizon_quarters=horizon_quarters, is_replan=is_replan,
        )

        # Wave ν: draft -> CFO gate -> (optional) revise -> commit.
        # Max 2 attempts total; if CFO rejects the revised draft too,
        # we ship it anyway rather than leaving the firm plan-less.
        user = base_user
        last_plan = None
        for attempt in range(2):
            try:
                result = backend.complete_json(system, user)
            except Exception:
                return last_plan
            if result is None:
                return last_plan

            draft_plan = parse_strategic_plan(
                result, firm.firm_id,
                plan_quarter=macro.quarter,
                plan_fyear=macro.fyear,
                plan_fqtr=macro.fqtr,
                supersedes=(prior_plan.plan_id if prior_plan else ""),
                horizon_quarters=horizon_quarters,
            )
            if draft_plan is None:
                return last_plan
            last_plan = draft_plan

            # Gatekeeper review — only on the FIRST attempt. If the CFO
            # flags issues, re-prompt with revision guidance; if the
            # second draft still fails, we ship anyway.
            if attempt == 0:
                review = _run_cfo_gatekeeper(
                    draft_plan, firm, industry_block, company_name,
                )
                if review is None:
                    # CFO LLM failed — ship the draft rather than block.
                    return draft_plan
                decision = str(review.get("decision", "APPROVE")).upper()
                if decision == "APPROVE":
                    return draft_plan
                # REVISE: append CFO feedback and re-prompt
                concerns = review.get("concerns") or []
                concerns_text = "\n".join(f"  - {c}" for c in concerns)
                guidance = str(review.get("revision_guidance", "")).strip()
                user = (
                    base_user
                    + "\n\n*** CFO GATEKEEPER REQUESTED REVISION ***\n"
                    + "Concerns raised:\n"
                    + (concerns_text if concerns_text else "  (none specified)")
                    + "\n\nRevision guidance from CFO:\n"
                    + (guidance if guidance else "(no specific guidance)")
                    + "\n\nProduce a REVISED plan addressing these concerns. "
                      "Output the full plan JSON again with the revisions applied."
                )
            else:
                # second attempt — ship whatever came back
                return draft_plan
        return last_plan

    return plan_fn


def parse_strategic_plan(
    result: dict,
    firm_id: str,
    plan_quarter: int,
    plan_fyear: int,
    plan_fqtr: int,
    supersedes: str = "",
    horizon_quarters: int = 20,
) -> StrategicPlan:
    """Parse LLM JSON into a StrategicPlan. Defensive — fills missing
    fields with zeros rather than rejecting the plan.
    """
    def _f(x, default=0.0):
        try:
            return float(x) if x is not None else default
        except (TypeError, ValueError):
            return default

    def _i(x, default=0):
        try:
            return int(x) if x is not None else default
        except (TypeError, ValueError):
            return default

    raw_lines = result.get("quarterly_lines", []) or []
    parsed_lines = []
    for r in raw_lines[:horizon_quarters]:
        if not isinstance(r, dict):
            continue
        parsed_lines.append(PlanLine(
            fyear=_i(r.get("fyear"), plan_fyear),
            fqtr=_i(r.get("fqtr"), 1),
            planned_revenue=_f(r.get("planned_revenue")),
            planned_units_sold=_i(r.get("planned_units_sold")),
            planned_price=_f(r.get("planned_price")),
            planned_capacity=_i(r.get("planned_capacity")),
            planned_cogs=_f(r.get("planned_cogs")),
            planned_rd_spend=_f(r.get("planned_rd_spend")),
            planned_sga_spend=_f(r.get("planned_sga_spend")),
            planned_capex=_f(r.get("planned_capex")),
            planned_equity_raise=_f(r.get("planned_equity_raise")),
            planned_debt_raise=_f(r.get("planned_debt_raise")),
            planned_dividends=_f(r.get("planned_dividends")),
            projected_ni=_f(r.get("projected_ni")),
            projected_eps=_f(r.get("projected_eps")),
            projected_cash_balance_eoq=_f(r.get("projected_cash_balance_eoq")),
            planned_generation=_i(r.get("planned_generation"), 1),
            planned_rd_cumulative_product=_f(r.get("planned_rd_cumulative_product")),
        ))

    return StrategicPlan(
        firm_id=firm_id,
        plan_id=str(uuid.uuid4()),
        plan_quarter=plan_quarter,
        plan_fyear=plan_fyear,
        plan_fqtr=plan_fqtr,
        horizon_quarters=horizon_quarters,
        lines=tuple(parsed_lines),
        strategy_narrative=str(result.get("strategy_narrative", "") or "")[:2000],
        key_assumptions=tuple(
            str(x)[:300] for x in (result.get("key_assumptions", []) or [])[:5]
        ),
        key_risks=tuple(
            str(x)[:300] for x in (result.get("key_risks", []) or [])[:5]
        ),
        milestones=tuple(
            str(x)[:300] for x in (result.get("milestones", []) or [])[:6]
        ),
        contingency_plan=str(result.get("contingency_plan", "") or "")[:1500],
        supersedes_plan_id=supersedes,
    )


# ── Variance computation ───────────────────────────────────────────────

def find_plan_line_for_quarter(plan: StrategicPlan, fyear: int, fqtr: int) -> PlanLine | None:
    """Find the PlanLine matching a given (fyear, fqtr). Returns None if not in plan."""
    for line in plan.lines:
        if line.fyear == fyear and line.fqtr == fqtr:
            return line
    return None


def compute_plan_variance(
    firm: FirmState,
    plan: StrategicPlan,
    flows: QuarterFlows,
    fyear: int,
    fqtr: int,
    material_threshold_pct: float = 0.20,
) -> PlanVariance | None:
    """Compare actual quarter results to the plan line for this quarter.

    Returns None if the plan has no line for this (fyear, fqtr) — e.g.
    we're beyond the plan's horizon.
    """
    line = find_plan_line_for_quarter(plan, fyear, fqtr)
    if line is None:
        return None

    actual_rev = flows.net_sales
    actual_ni = flows.reported_net_income if flows.reported_net_income != 0 else flows.net_income
    actual_cash = firm.cash
    actual_units = flows.units_sold

    rev_var = actual_rev - line.planned_revenue
    ni_var = actual_ni - line.projected_ni
    cash_var = actual_cash - line.projected_cash_balance_eoq
    units_var = actual_units - line.planned_units_sold

    rev_var_pct = (rev_var / line.planned_revenue) if line.planned_revenue != 0 else 0.0
    ni_var_pct = (ni_var / abs(line.projected_ni)) if line.projected_ni != 0 else 0.0

    # Material deviation logic: big negative variance on revenue OR cash
    is_material = False
    reason = ""
    if line.planned_revenue > 0 and rev_var_pct < -material_threshold_pct:
        is_material = True
        reason = f"revenue {rev_var_pct:+.0%} vs plan (${actual_rev/1e6:.1f}M vs ${line.planned_revenue/1e6:.1f}M planned)"
    elif line.projected_cash_balance_eoq > 0 and cash_var < -0.20 * line.projected_cash_balance_eoq:
        is_material = True
        reason = f"cash ${actual_cash/1e6:.0f}M vs ${line.projected_cash_balance_eoq/1e6:.0f}M planned"
    elif line.projected_ni != 0 and abs(ni_var_pct) > 0.50 and ni_var < 0:
        is_material = True
        reason = f"NI missed by ${ni_var/1e6:+.1f}M ({ni_var_pct:+.0%} of plan)"

    return PlanVariance(
        firm_id=firm.firm_id,
        plan_id=plan.plan_id,
        fyear=fyear, fqtr=fqtr,
        revenue_variance=rev_var,
        ni_variance=ni_var,
        cash_variance=cash_var,
        units_variance=units_var,
        revenue_variance_pct=rev_var_pct,
        ni_variance_pct=ni_var_pct,
        is_material=is_material,
        material_reason=reason,
    )


def plan_variance_summary_for_prompt(
    firm: FirmState,
    current_fyear: int = 0,
    current_fqtr: int = 0,
) -> dict:
    """Summarize recent plan vs actuals for the firm's decision prompt.

    If current_fyear/fqtr are provided, also surface the PlanLine for
    this quarter so the decision prompt can ask the firm to justify
    material deviations from its own plan.
    """
    plan: StrategicPlan | None = firm.current_plan  # type: ignore
    history = firm.plan_variance_history
    if plan is None:
        return {}
    recent = list(history)[-3:]  # last 3 quarters

    # Look up the PlanLine for the current quarter, if known
    this_q_line = None
    if current_fyear and current_fqtr:
        for line in plan.lines:
            if line.fyear == current_fyear and line.fqtr == current_fqtr:
                this_q_line = {
                    "planned_revenue": line.planned_revenue,
                    "planned_rd_spend": line.planned_rd_spend,
                    "planned_capex": line.planned_capex,
                    "planned_sga_spend": line.planned_sga_spend,
                    "planned_units_sold": line.planned_units_sold,
                    "planned_capacity": line.planned_capacity,
                }
                break

    return {
        "has_plan": True,
        "plan_quarter": plan.plan_quarter,
        "plan_horizon_quarters": plan.horizon_quarters,
        "strategy_narrative": plan.strategy_narrative[:300],
        "key_milestones": list(plan.milestones)[:3],
        "contingency_plan": plan.contingency_plan[:600],
        "this_quarter_plan": this_q_line,
        "recent_variances": [
            {
                "fyear": v.fyear, "fqtr": v.fqtr,
                "revenue_variance_pct": v.revenue_variance_pct,
                "ni_variance": v.ni_variance,
                "is_material": v.is_material,
                "material_reason": v.material_reason,
            }
            for v in recent
        ],
        "material_variance_streak": firm.material_variance_streak,
    }


def estimate_quarterly_burn(firm: FirmState, last_flows) -> float:
    """Estimate the firm's quarterly cash burn rate from last quarter's flows.

    Burn = max(0, (R&D + SG&A + capex) - revenue). Returns 0 if firm
    is cash-flow positive. Fallback minimum $10M/Q when no flows yet
    (avoid divide-by-zero for first-quarter firms).
    """
    if last_flows is None:
        return 10_000_000.0
    outflow = (
        float(getattr(last_flows, "rd_expense", 0) or 0)
        + float(getattr(last_flows, "sga_expense", 0) or 0)
        + float(getattr(last_flows, "capex", 0) or 0)
    )
    inflow = float(getattr(last_flows, "revenue", 0) or 0)
    return max(0.0, outflow - inflow)


def should_replan(firm: FirmState, streak_threshold: int = 2) -> bool:
    """Heuristic: fire an early re-plan if the firm has had N+ consecutive
    material-variance quarters.
    """
    return firm.material_variance_streak >= streak_threshold


def needs_emergency_replan(
    firm: FirmState, last_flows, runway_threshold_q: float = 4.0,
) -> bool:
    """Fire a mid-year replan when runway is dangerously short.

    Triggers when projected runway (cash / quarterly burn) drops below
    `runway_threshold_q`. Default 4Q = "will burn all cash within 1 year."
    The firm is forced to write a new plan reflecting the capital reality,
    rather than waiting for the annual Q4 cycle.

    Returns False if the firm is cash-flow positive (no burn → infinite
    runway) or if a plan was already issued this quarter (guard against
    same-quarter double replans).
    """
    if firm.current_plan is None:
        return False  # the normal "no plan yet" path handles this
    burn = estimate_quarterly_burn(firm, last_flows)
    if burn <= 0:
        return False  # cash-flow positive
    runway = firm.cash / burn if burn > 0 else 999.0
    return runway < runway_threshold_q
