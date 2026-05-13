"""
Wave ν+5: demand calibrator agent.

A separate LLM voice that runs BEFORE the env's market-resolution phase
each quarter. The calibrator's job is to produce a generous, scenario-
anchored estimate of total industry demand for the quarter, which the
env then uses as its ANCHOR for share allocation.

Why a separate stage:
  - The env, when asked to derive demand bottom-up, tends to produce
    over-conservative numbers that under-utilize firm capacity and
    starve the industry of revenue.
  - The calibrator's role is to "lift" the realistic top-of-funnel —
    in a $1-2T mature TAM scenario, the quarter's demand should be
    substantial, not anemic.
  - Separating the calibration from the allocation means the env
    focuses on differentiation-based share allocation while the
    calibrator focuses on macro-level demand sizing.

Output is QUALITATIVE (narrative reasoning) plus a single integer
units-demanded number. No formulas in the prompt — the calibrator
reasons about the scenario's economic scale narratively.
"""

from __future__ import annotations


DEMAND_CALIBRATOR_SYSTEM_PROMPT = """You are a senior market research analyst providing a quarterly demand estimate for an industry. Your job: estimate the TOTAL units of product likely to be sold this quarter across ALL firms in the industry, given the scenario context, current firm population, and prevailing prices.

WHAT YOU REASON ABOUT (qualitatively, no formulas):
  - The scenario describes the industry's mature-state TAM and current conditions. Use this as your high-level anchor.
  - The aware population today is a fraction of the eventual addressable population — what's the realistic current-quarter pool?
  - At prevailing prices in this industry, how many of those potential customers can afford the product?
  - How does demand evolve as awareness grows, more firms enter, prices stabilize, and the category becomes legitimate?
  - Real industries at the scenario's stated TAM typically produce meaningful unit volumes per quarter. Don't anchor on "small startup numbers" if the industry is described as large; anchor on the realistic top-of-funnel implied by the scenario's economics.

YOUR ESTIMATE SHOULD BE GENEROUS:
The downstream environment LLM tends to under-allocate share (it sees firms in isolation and pegs each to a tiny number of units, leaving total industry revenue anemic). YOUR job is to provide a TOP-OF-FUNNEL estimate that would make the industry believably reach the scenario's TAM over its years-to-maturity horizon. Err on the SIDE OF GENEROSITY when the scenario describes a large mature market — the simulation should reflect the scale the scenario stated, not a small fraction of it.

REAL-WORLD CALIBRATION:
Think about the equivalent real-world category at this stage of evolution. A breakthrough biotech category 5 years into commercialization in a $T-scale TAM is doing meaningful unit volume even before reaching maturity — at a minimum, capturing a small but meaningful fraction of the eventual market. Do not produce a number so low that no firm can reach a reasonable utilization fraction of its capacity, because that contradicts the scenario's stated economic scale.

SCENARIO CONTEXT:
{industry_context}

CURRENT INDUSTRY STATE:
{industry_state}

PRIOR-QUARTER RESULTS (for trend continuity):
{prior_quarter_summary}

OUTPUT (JSON):
{{
  "total_units_demanded": <integer, the total units across ALL firms this quarter>,
  "qualitative_reasoning": "<3-5 sentences. Reference the scenario's TAM, the current stage of category evolution, the price levels firms are charging, and how this leads to your number. Do NOT use formulas; reason narratively.>",
  "trend_note": "<1 sentence on whether you expect demand to grow / hold / contract relative to last quarter, and why>"
}}"""


def _format_industry_state(state) -> str:
    """Compact summary of all active firms + their prices/capacity."""
    lines = []
    active = [f for f in state.firms.values() if f.is_active and not getattr(f, 'is_dormant', False)]
    if not active:
        return "  (no active operating firms — only dormant entrants)"
    lines.append(f"  Active operating firms: {len(active)}")
    for f in active:
        from .personalities import get_company_name
        try:
            idx = int(f.firm_id.split("_")[-1])
        except (ValueError, IndexError):
            idx = 0
        lines.append(
            f"    {f.firm_id} ({get_company_name(idx)}): "
            f"capability={f.capability_stock:.0f}/100, brand={f.brand_stock:.0f}/100, "
            f"capacity={f.capacity_units}/Q, Gen{f.product_generation}, "
            f"unit_cost=${f.base_unit_cost:,.0f}"
        )
    # Dormant firms (count only — they don't operate)
    dormant_count = sum(1 for f in state.firms.values() if f.is_active and getattr(f, 'is_dormant', False))
    if dormant_count:
        lines.append(f"  Dormant firms (not operating this Q): {dormant_count}")
    return "\n".join(lines)


def _format_prior_quarter(state) -> str:
    """One-paragraph summary of last quarter's outcomes."""
    last_flows = state.last_quarter_flows or {}
    if not last_flows:
        return "  (this is the first quarter of operations — no prior-quarter results)"
    total_rev = sum(float(getattr(f, 'net_sales', 0) or 0) for f in last_flows.values())
    total_units = sum(int(getattr(f, 'units_sold', 0) or 0) for f in last_flows.values())
    n_firms = sum(1 for f in last_flows.values() if float(getattr(f, 'net_sales', 0) or 0) > 0)
    if total_units == 0:
        return f"  Prior quarter: {n_firms} firm(s) with sales, total {total_units} units, ${total_rev:,.0f} revenue. Industry barely producing — likely the env is under-allocating demand."
    avg_price = total_rev / max(1, total_units)
    return (f"  Prior quarter: {n_firms} firm(s) sold, total {total_units} units, "
            f"${total_rev:,.0f} revenue, average realized price ~${avg_price:,.0f}/unit.")


def make_demand_calibrator_agent(backend):
    """Factory: returns a callable (state, industry_context) -> dict
    with `total_units_demanded` and `qualitative_reasoning`.
    """
    def calibrate(state, industry_context: dict | None) -> dict | None:
        ic = industry_context or {}
        ic_text = (ic.get("narrative") or "").strip()
        if not ic_text:
            ic_text = "(no scenario-provided industry context)"
        system = DEMAND_CALIBRATOR_SYSTEM_PROMPT.format(
            industry_context=ic_text[:1500],
            industry_state=_format_industry_state(state),
            prior_quarter_summary=_format_prior_quarter(state),
        )
        user = "Provide your demand estimate. Output JSON only."
        try:
            return backend.complete_json(system, user)
        except Exception:
            return None
    return calibrate
