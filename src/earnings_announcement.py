"""
Earnings announcement agent.

After quarterly accounting, each firm produces a public earnings release:
- Reported EPS and key financials
- Management discussion of results
- Forward EPS guidance (1Q ahead and 1Y ahead)

Then sell-side analysts can ask questions (Q&A round).
The firm's own LLM backend is reused with a different prompt.

Output: EarningsRelease stored in WorldState.earnings_releases (public).
"""

from __future__ import annotations

from .types import FirmState, QuarterFlows, MacroState, SimParams, EarningsRelease
from .llm_backends import LLMBackend, extract_json


def build_earnings_prompt(
    firm: FirmState,
    flows: QuarterFlows,
    macro: MacroState,
    prior_guidance: dict | None = None,
) -> tuple[str, str]:
    """Build (system, user) prompts for an earnings announcement.

    Uses the firm's own LLM backend but a public-facing prompt.
    The firm should present results favorably but honestly.
    """
    eps = flows.reported_net_income / firm.shares_outstanding if firm.shares_outstanding > 0 else 0

    system = f"""You are the investor relations team for {firm.firm_id}, a pharmaceutical company.
You are producing a PUBLIC quarterly earnings announcement.

Output a JSON object with:
- reported_eps: number (earnings per share this quarter)
- reported_revenue: number (total quarterly revenue in USD)
- guidance_eps_1q: number (your EPS forecast for next quarter)
- guidance_eps_1y: number (your EPS forecast for the next 4 quarters combined)
- guidance_revenue_1q: number (revenue forecast for next quarter, in USD)
- management_discussion: string (2-3 paragraph discussion of results, strategy, and outlook)

Be specific: reference actual numbers (revenue, margins, R&D progress, cash position).
Compare to prior guidance if available. Be professional but positive.
Output ONLY JSON wrapped in ```json ... ```."""

    # Prior guidance comparison
    guidance_text = ""
    if prior_guidance:
        prior_1q = prior_guidance.get("guidance_eps_1q", 0)
        if prior_1q != 0:
            guidance_text = f"\nPrior quarter's 1Q-ahead guidance: ${prior_1q:.2f}/share (compare to actual ${eps:.2f})"

    user = f"""QUARTERLY RESULTS for {firm.firm_id}:
  Revenue: ${flows.net_sales:,.0f}
  COGS: ${flows.cogs:,.0f}
  Gross Margin: {(flows.gross_profit / max(1, flows.net_sales)) * 100:.0f}%
  R&D Expense: ${flows.rd_expense:,.0f}
  SGA Expense: ${flows.sga_expense:,.0f}
  Operating Income: ${flows.operating_income:,.0f}
  Net Income (reported): ${flows.reported_net_income:,.0f}
  EPS: ${eps:.2f}
  Units Sold: {flows.units_sold}
  Market Share: {flows.market_share:.1%}
  Cash Position: ${firm.cash:,.0f}
  Total Debt: ${firm.long_term_debt + firm.revolver_balance:,.0f}
{guidance_text}

MACRO: Risk-free rate {macro.risk_free_rate:.1%}/Q, Awareness {macro.awareness_rate:.0%}

Produce the earnings announcement."""

    return system, user


def _to_float(v, default: float = 0.0) -> float:
    """Coerce LLM response value to float. Handles strings with $, commas, percent."""
    if v is None:
        return default
    if isinstance(v, (int, float)):
        return float(v)
    try:
        s = str(v).strip().replace("$", "").replace(",", "").replace("%", "")
        return float(s) if s else default
    except (ValueError, TypeError):
        return default


def parse_earnings_release(
    response: dict | None,
    firm_id: str,
    quarter: int,
    default_eps: float = 0.0,
    default_revenue: float = 0.0,
) -> EarningsRelease:
    """Parse LLM response into an EarningsRelease (with type coercion)."""
    if response is None:
        return EarningsRelease(
            firm_id=firm_id, quarter=quarter,
            reported_eps=default_eps, reported_revenue=default_revenue,
        )
    return EarningsRelease(
        firm_id=firm_id,
        quarter=quarter,
        reported_eps=_to_float(response.get("reported_eps"), default_eps),
        reported_revenue=_to_float(response.get("reported_revenue"), default_revenue),
        guidance_eps_1q=_to_float(response.get("guidance_eps_1q")),
        guidance_eps_1y=_to_float(response.get("guidance_eps_1y")),
        guidance_revenue_1q=_to_float(response.get("guidance_revenue_1q")),
        management_discussion=str(response.get("management_discussion", "")),
    )


def make_earnings_announcer(backends: dict[str, LLMBackend], state_ref: list):
    """Factory: create earnings announcement function.

    Reuses each firm's own LLM backend (same model, different prompt).
    backends: the same dict used for firm decisions {firm_id -> backend}.
    """

    def announce_earnings(firm_id: str, firm: FirmState, flows: QuarterFlows,
                          macro: MacroState, prior_guidance: dict | None = None) -> EarningsRelease:
        backend = backends.get(firm_id)
        if backend is None:
            return EarningsRelease(firm_id=firm_id, quarter=firm.quarter)

        system, user = build_earnings_prompt(firm, flows, macro, prior_guidance)
        from . import telemetry as _tel
        with _tel.set_role(f"earnings_{firm_id}"):
            result = backend.complete_json(system, user)

        eps = flows.reported_net_income / firm.shares_outstanding if firm.shares_outstanding > 0 else 0
        return parse_earnings_release(
            result, firm_id, firm.quarter,
            default_eps=eps, default_revenue=flows.net_sales,
        )

    return announce_earnings
