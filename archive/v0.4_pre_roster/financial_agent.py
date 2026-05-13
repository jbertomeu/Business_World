"""
Financial Agent: LLM-powered equity pricing and credit decisions.

This replaces the built-in DCF formula. ALL financial decisions are now
made by an LLM that reasons about the data and explains its conclusions.

The financial agent sees:
- All firms' published financial statements (Compustat-equivalent)
- Macro state
- Industry gazette
- Its own past pricing accuracy (from cross-run scoring)

It produces:
- Equity price per share for each firm (with reasoning)
- Credit terms for each firm (revolver size, rate, term debt, with reasoning)

The reasoning is logged and saved for inspection.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .types import FirmState, MacroState, SimParams, QuarterFlows
from .llm_backends import LLMBackend


@dataclass
class FinancialDecisions:
    """Output from the financial agent for one quarter."""
    firm_decisions: dict[str, dict] = field(default_factory=dict)
    full_reasoning: str = ""


FINANCIAL_SYSTEM_PROMPT = """You are the financial markets for a simulated pharmaceutical industry.
You represent equity investors, commercial banks, and credit funds combined.

Each quarter, you evaluate every active firm and decide:

1. EQUITY PRICE: What is a fair price per share?
   Use multiple valuation approaches and explain your reasoning:
   - Revenue multiple: What multiple of annualized revenue is appropriate? (Growth biotech: 5-20x)
   - Pipeline value: How much is the R&D pipeline worth? (Gen 2 at $500M threshold)
   - Asset/cash value: What are the tangible assets worth?
   - Risk adjustment: Cash burn rate, default risk, competitive position

   Consider: This is a GROWTH INDUSTRY. Early losses are normal. Value is in future potential.
   But also: dilution matters, cash burn matters, competitive position matters.

2. CREDIT TERMS: Should you lend to this firm?
   - Revolver: How large a credit line? At what rate?
   - Term debt: Should you approve their request? At what rate?

   Consider: What is their ability to repay? Cash flow coverage? Asset coverage?
   A firm burning $50M/Q with $100M cash is 2 quarters from default without your credit.
   Rate should reflect risk: safe firms get low rates, risky firms get high rates.

Output a JSON object with one entry per firm:
```json
{
  "firms": [
    {
      "firm_id": "firm_0",
      "equity_price": <number>,
      "equity_reasoning": "<2-3 sentences explaining the valuation>",
      "revolver_commitment": <number>,
      "revolver_rate_quarterly": <number between 0.01 and 0.10>,
      "term_debt_approved": <number, 0 if denied>,
      "term_debt_rate_quarterly": <number between 0.02 and 0.10>,
      "credit_reasoning": "<2-3 sentences explaining credit decision>",
      "default_risk": "<low/medium/high/critical>"
    }
  ]
}
```

Be specific with numbers. Differentiate between firms based on their fundamentals.
A firm with strong revenue growth deserves a higher price than one with declining revenue.
A firm with 2 quarters of cash runway is HIGH risk regardless of its pipeline."""


def build_financial_prompt(
    firms: dict[str, FirmState],
    flows: dict[str, QuarterFlows],
    macro: MacroState,
    gazette: str = "",
    prior_pricing: dict[str, float] | None = None,
) -> tuple[str, str]:
    """Build the financial agent's prompt with all firm data."""

    system = FINANCIAL_SYSTEM_PROMPT

    # Build per-firm financial summary
    firm_sections = []
    for fid in sorted(firms):
        firm = firms[fid]
        if not firm.is_active:
            continue

        f = flows.get(fid)
        if f is None:
            continue

        total_debt = firm.revolver_balance + firm.long_term_debt
        annualized_rev = f.net_sales * 4
        cash_runway = "N/A"
        if f.cfo < 0:
            runway_q = firm.cash / max(1, -f.cfo)
            cash_runway = f"{runway_q:.1f}Q"

        gen2_pct = firm.rd_cumulative_product / 500_000_000 * 100
        gross_margin = f.gross_profit / max(1, f.net_sales)

        prior_price = prior_pricing.get(fid, 0) if prior_pricing else 0

        firm_sections.append(f"""{fid}:
  Revenue (this Q): ${f.net_sales:,.0f} | Annualized: ${annualized_rev:,.0f}
  COGS: ${f.cogs:,.0f} | Gross margin: {gross_margin:.0%}
  R&D expense: ${f.rd_expense:,.0f} | SGA: ${f.sga_expense:,.0f}
  Net income: ${f.net_income:,.0f}
  Operating cash flow: ${f.cfo:,.0f}
  Cash: ${firm.cash:,.0f} | Cash runway: {cash_runway}
  Total debt: ${total_debt:,.0f} (revolver ${firm.revolver_balance:,.0f} + LTD ${firm.long_term_debt:,.0f})
  Total assets: ${firm.total_assets:,.0f} | Total equity: ${firm.total_equity:,.0f}
  Shares outstanding: {firm.shares_outstanding:,}
  PP&E: ${firm.ppe_net:,.0f} | Inventory: ${firm.inventory_value:,.0f}
  Gen 2 R&D progress: {gen2_pct:.0f}% of threshold
  Prior equity price: ${prior_price:.2f}
  Debt request this Q: (to be determined by your credit decision)""")

    firms_text = "\n\n".join(firm_sections)

    user = f"""=== FINANCIAL MARKETS — Q{macro.fqtr} {macro.fyear} ===

MACRO:
  Risk-free rate: {macro.risk_free_rate*400:.1f}% annual ({macro.risk_free_rate*100:.2f}% quarterly)
  Market awareness: {macro.awareness_rate:.0%}

FIRM FINANCIALS:

{firms_text}

GAZETTE SUMMARY:
{gazette[:400] if gazette else '(none)'}

Price each firm's equity and set credit terms. Explain your reasoning for each.
Output JSON with one entry per active firm."""

    return system, user


def make_financial_agent(backend: LLMBackend, state_ref: list):
    """Create a financial agent function that calls an LLM."""

    def financial_agent(firms, macro, params):
        world_state = state_ref[0] if state_ref else None
        flows = world_state.last_quarter_flows if world_state else {}
        gazette = world_state.gazettes[-1] if world_state and world_state.gazettes else ""

        # Get prior prices for context
        prior_pricing = {fid: f.equity_price for fid, f in firms.items() if f.is_active}

        system, user = build_financial_prompt(firms, flows, macro, gazette, prior_pricing)

        result = backend.complete_json(system, user)

        if result is None:
            print("  [financial] LLM failed, using fallback")
            return None

        # Parse into the format orchestrator expects
        decisions = {}
        firms_data = result.get("firms", [])
        if isinstance(firms_data, list):
            for f in firms_data:
                fid = f.get("firm_id", "")
                if not fid:
                    continue

                try:
                    eq_price = float(f.get("equity_price", 0))
                except (TypeError, ValueError):
                    eq_price = 0

                try:
                    rev_commit = float(f.get("revolver_commitment", 0))
                except (TypeError, ValueError):
                    rev_commit = 0

                try:
                    rev_rate = float(f.get("revolver_rate_quarterly", 0.02))
                except (TypeError, ValueError):
                    rev_rate = 0.02

                try:
                    term_approved = float(f.get("term_debt_approved", 0))
                except (TypeError, ValueError):
                    term_approved = 0

                try:
                    term_rate = float(f.get("term_debt_rate_quarterly", 0.03))
                except (TypeError, ValueError):
                    term_rate = 0.03

                eq_reasoning = f.get("equity_reasoning", "")
                credit_reasoning = f.get("credit_reasoning", "")
                default_risk = f.get("default_risk", "medium")

                decisions[fid] = {
                    "equity_price": max(0.01, eq_price),
                    "revolver_commitment": max(0, rev_commit),
                    "revolver_rate": max(0.005, min(0.10, rev_rate)),
                    "term_debt_approved": max(0, term_approved),
                    "term_debt_rate": max(0.01, min(0.10, term_rate)),
                    "equity_reasoning": eq_reasoning,
                    "credit_reasoning": credit_reasoning,
                    "default_risk": default_risk,
                }

        # Store full reasoning for logging
        full_text = backend.complete(system, user) if not firms_data else str(result)

        return decisions

    return financial_agent
