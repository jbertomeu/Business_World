"""
Annual report (10-K-style) generation. Produced at fqtr=4 for each active firm.

Two parts:
  1. Deterministic financial aggregation — sum the firm's 4 quarters of compustat
     rows + balance-sheet snapshot at year-end + capital-activity tally.
  2. LLM-authored narrative — MD&A summary, forward guidance, strategic initiatives,
     risk factors. Reuses the firm's own LLM backend (same model that ran its
     quarterly decisions and earnings releases).

Outputs:
  - AnnualReport dataclass (in WorldState.annual_reports)
  - Markdown file written by output_organizer to firms/firm_X/annual_report_FY####.md
  - CSV row in annual_reports.csv
"""

from __future__ import annotations

from dataclasses import replace
from .types import FirmState, MacroState, AnnualReport, AuditResult, CompustatRow
from .llm_backends import LLMBackend


SYSTEM_PROMPT = """You are the investor relations team for a pharmaceutical company
preparing the annual report (10-K equivalent) for the fiscal year just ended.

This is a PUBLIC document. Investors, analysts, regulators, and competitors will
read it. Be professional, specific, and balanced — acknowledge weaknesses where
real, but frame opportunities clearly.

Output a JSON object with these fields:
  - mda_summary: 2-3 paragraphs of Management Discussion & Analysis. Reference
    actual annual numbers (revenue growth, margin trends, R&D progress, capital
    structure changes). Compare to prior year if data is provided. Discuss
    strategy, competitive position, and key risks.
  - forward_guidance_revenue: number (full-year revenue forecast for next fiscal year)
  - forward_guidance_eps: number (full-year EPS forecast for next fiscal year)
  - key_strategic_initiatives: string (3-5 bullets, short)
  - risk_factors: string (3-5 bullets — material risks the firm faces)

Tone: factual, professional, balanced. Don't over-promise. Don't bury bad news,
but don't overstate it either. Use specific numbers from the year's data.

Output ONLY JSON wrapped in ```json ... ```."""


# ─── Deterministic aggregation ──────────────────────────────────────────


def aggregate_year(firm: FirmState,
                   year_rows: list[CompustatRow],
                   prior_year_rows: list[CompustatRow] | None = None) -> dict:
    """Compute deterministic full-year financials from this fyear's compustat rows.

    Returns a dict suitable for populating an AnnualReport. Pure Python.
    """
    if not year_rows:
        return {}

    # Sum income-statement and cash-flow lines across the 4 quarters
    annual_revenue = sum(r.saleq for r in year_rows)
    annual_cogs = sum(r.cogsq for r in year_rows)
    annual_gross_profit = sum(r.gpq for r in year_rows)
    annual_rd = sum(r.xrdq for r in year_rows)
    annual_sga = sum(r.xsgaq for r in year_rows)
    annual_dep = sum(r.dpq for r in year_rows)
    annual_oi = sum(r.oiadpq for r in year_rows)
    annual_interest = sum(r.xintq for r in year_rows)
    annual_pretax = sum(r.piq for r in year_rows)
    annual_tax = sum(r.txtq for r in year_rows)
    annual_ni = sum(r.niq for r in year_rows)
    annual_cfo = sum(r.oancfq for r in year_rows)
    annual_cfi = sum(r.ivncfq for r in year_rows)
    annual_cff = sum(r.fincfq for r in year_rows)
    annual_capex = sum(r.capxq for r in year_rows)

    # Capital activity across the year
    equity_issued = sum(r.sstkq for r in year_rows)
    dividends_paid = sum(r.dvq for r in year_rows)
    buybacks = sum(r.prstkq for r in year_rows)

    # Debt issued = sum of positive LTD changes within the year
    # (we approximate via the cumulative LTD delta from start of year)
    last_row = year_rows[-1]
    first_row = year_rows[0]
    # Year-over-year revenue growth
    yoy_rev_growth = 0.0
    yoy_ni_growth = 0.0
    if prior_year_rows:
        prior_rev = sum(r.saleq for r in prior_year_rows)
        prior_ni = sum(r.niq for r in prior_year_rows)
        if prior_rev > 0:
            yoy_rev_growth = (annual_revenue - prior_rev) / prior_rev
        if abs(prior_ni) > 1.0:
            yoy_ni_growth = (annual_ni - prior_ni) / abs(prior_ni)

    # EPS (annual NI / year-end shares; cshoq is in millions)
    shares_m = last_row.cshoq if last_row.cshoq > 0 else 1.0
    annual_eps = annual_ni / (shares_m * 1_000_000) if shares_m > 0 else 0.0

    return {
        "annual_revenue": annual_revenue,
        "annual_cogs": annual_cogs,
        "annual_gross_profit": annual_gross_profit,
        "annual_rd": annual_rd,
        "annual_sga": annual_sga,
        "annual_depreciation": annual_dep,
        "annual_operating_income": annual_oi,
        "annual_interest_expense": annual_interest,
        "annual_pretax_income": annual_pretax,
        "annual_tax": annual_tax,
        "annual_net_income": annual_ni,
        "annual_true_net_income": annual_ni,  # pre-manipulation not directly on row
        "annual_eps": annual_eps,
        "annual_cfo": annual_cfo,
        "annual_cfi": annual_cfi,
        "annual_cff": annual_cff,
        "annual_capex": annual_capex,
        "year_end_cash": last_row.cheq,
        "year_end_total_assets": last_row.atq,
        "year_end_total_liabilities": last_row.ltq,
        "year_end_total_equity": last_row.ceqq,
        "year_end_long_term_debt": last_row.dlttq,
        "year_end_revolver_balance": last_row.dlcq,
        "year_end_shares_outstanding": int(shares_m * 1_000_000),
        "year_end_share_price": last_row.prccq,
        "yoy_revenue_growth": yoy_rev_growth,
        "yoy_ni_growth": yoy_ni_growth,
        "equity_issued_during_year": equity_issued,
        "debt_issued_during_year": max(0.0, last_row.dlttq - first_row.dlttq),  # approx
        "dividends_paid": dividends_paid,
        "buybacks": buybacks,
    }


# ─── LLM prompt ──────────────────────────────────────────────────────────


def build_annual_prompt(firm: FirmState,
                         agg: dict,
                         macro: MacroState,
                         audit: AuditResult | None = None,
                         prior_year_agg: dict | None = None) -> tuple[str, str]:
    """Compose (system, user) prompts for the LLM-authored MD&A section."""
    audit_line = ""
    if audit:
        gc = " (going-concern flag raised)" if audit.going_concern else ""
        audit_line = (f"  Auditor opinion this year: {audit.opinion} "
                      f"by {audit.auditor_id}{gc}")
    prior_line = ""
    if prior_year_agg:
        prior_rev = prior_year_agg.get("annual_revenue", 0)
        prior_ni = prior_year_agg.get("annual_net_income", 0)
        prior_line = (f"  Prior year revenue: ${prior_rev:,.0f}\n"
                      f"  Prior year net income: ${prior_ni:,.0f}\n")

    user = f"""=== ANNUAL REPORT PREPARATION — FY{macro.fyear} ===

FIRM: {firm.firm_id}

THIS YEAR'S RESULTS:
  Revenue: ${agg.get('annual_revenue', 0):,.0f}
  Gross profit: ${agg.get('annual_gross_profit', 0):,.0f} (margin: {agg.get('annual_gross_profit', 0) / max(1, agg.get('annual_revenue', 1)) * 100:.1f}%)
  R&D expense: ${agg.get('annual_rd', 0):,.0f}
  SG&A expense: ${agg.get('annual_sga', 0):,.0f}
  Operating income: ${agg.get('annual_operating_income', 0):,.0f}
  Interest expense: ${agg.get('annual_interest_expense', 0):,.0f}
  Net income: ${agg.get('annual_net_income', 0):,.0f}
  Annual EPS: ${agg.get('annual_eps', 0):.2f}

YEAR-END BALANCE SHEET:
  Cash: ${agg.get('year_end_cash', 0):,.0f}
  Total assets: ${agg.get('year_end_total_assets', 0):,.0f}
  Long-term debt: ${agg.get('year_end_long_term_debt', 0):,.0f}
  Revolver balance: ${agg.get('year_end_revolver_balance', 0):,.0f}
  Total equity: ${agg.get('year_end_total_equity', 0):,.0f}
  Shares outstanding: {agg.get('year_end_shares_outstanding', 0):,}
  Year-end share price: ${agg.get('year_end_share_price', 0):.2f}

CAPITAL ACTIVITY:
  Equity issued during year: ${agg.get('equity_issued_during_year', 0):,.0f}
  Debt issued during year (approx): ${agg.get('debt_issued_during_year', 0):,.0f}
  Dividends paid: ${agg.get('dividends_paid', 0):,.0f}
  Buybacks: ${agg.get('buybacks', 0):,.0f}

CASH FLOW:
  Operating: ${agg.get('annual_cfo', 0):,.0f}
  Investing: ${agg.get('annual_cfi', 0):,.0f}
  Financing: ${agg.get('annual_cff', 0):,.0f}
  Capex: ${agg.get('annual_capex', 0):,.0f}

YOY:
  Revenue growth: {agg.get('yoy_revenue_growth', 0) * 100:+.1f}%
  Net income growth: {agg.get('yoy_ni_growth', 0) * 100:+.1f}%

{prior_line}{audit_line}

PRODUCT GENERATION: Gen {firm.product_generation}
CAPACITY: {firm.capacity_units} courses/quarter
CAPABILITY STOCK: {firm.capability_stock:.0f}/100
BRAND STOCK: {firm.brand_stock:.0f}/100

MACRO: Risk-free {macro.risk_free_rate*400:.1f}% annual

Produce the annual report MD&A and outlook."""

    return SYSTEM_PROMPT, user


# ─── Parser ──────────────────────────────────────────────────────────────


def _to_float(v, default: float = 0.0) -> float:
    if v is None:
        return default
    if isinstance(v, (int, float)):
        return float(v)
    try:
        s = str(v).strip().replace("$", "").replace(",", "").replace("%", "")
        return float(s) if s else default
    except (ValueError, TypeError):
        return default


def _to_text_block(v) -> str:
    """LLMs sometimes return list-of-strings for bullet sections instead of
    a single string. Normalize: join lists with newlines + leading dash."""
    if v is None:
        return ""
    if isinstance(v, list):
        out = []
        for item in v:
            s = str(item).strip()
            if not s:
                continue
            if not s.startswith(("-", "*", "•")):
                s = f"- {s}"
            out.append(s)
        return "\n".join(out)
    return str(v)


def parse_annual_report(response: dict | None,
                         firm: FirmState,
                         macro: MacroState,
                         agg: dict,
                         audit: AuditResult | None,
                         covenant_violations_count: int) -> AnnualReport:
    """Build an AnnualReport from the LLM response + deterministic aggregates."""
    response = response or {}
    return AnnualReport(
        firm_id=firm.firm_id,
        fyear=macro.fyear,
        quarter=macro.quarter,
        annual_revenue=agg.get("annual_revenue", 0.0),
        annual_cogs=agg.get("annual_cogs", 0.0),
        annual_gross_profit=agg.get("annual_gross_profit", 0.0),
        annual_rd=agg.get("annual_rd", 0.0),
        annual_sga=agg.get("annual_sga", 0.0),
        annual_depreciation=agg.get("annual_depreciation", 0.0),
        annual_operating_income=agg.get("annual_operating_income", 0.0),
        annual_interest_expense=agg.get("annual_interest_expense", 0.0),
        annual_pretax_income=agg.get("annual_pretax_income", 0.0),
        annual_tax=agg.get("annual_tax", 0.0),
        annual_net_income=agg.get("annual_net_income", 0.0),
        annual_true_net_income=agg.get("annual_true_net_income", 0.0),
        annual_eps=agg.get("annual_eps", 0.0),
        annual_cfo=agg.get("annual_cfo", 0.0),
        annual_cfi=agg.get("annual_cfi", 0.0),
        annual_cff=agg.get("annual_cff", 0.0),
        annual_capex=agg.get("annual_capex", 0.0),
        year_end_cash=agg.get("year_end_cash", 0.0),
        year_end_total_assets=agg.get("year_end_total_assets", 0.0),
        year_end_total_liabilities=agg.get("year_end_total_liabilities", 0.0),
        year_end_total_equity=agg.get("year_end_total_equity", 0.0),
        year_end_long_term_debt=agg.get("year_end_long_term_debt", 0.0),
        year_end_revolver_balance=agg.get("year_end_revolver_balance", 0.0),
        year_end_shares_outstanding=int(agg.get("year_end_shares_outstanding", 0)),
        year_end_share_price=agg.get("year_end_share_price", 0.0),
        yoy_revenue_growth=agg.get("yoy_revenue_growth", 0.0),
        yoy_ni_growth=agg.get("yoy_ni_growth", 0.0),
        equity_issued_during_year=agg.get("equity_issued_during_year", 0.0),
        debt_issued_during_year=agg.get("debt_issued_during_year", 0.0),
        dividends_paid=agg.get("dividends_paid", 0.0),
        buybacks=agg.get("buybacks", 0.0),
        audit_opinion=(audit.opinion if audit else ""),
        going_concern_flag=(audit.going_concern if audit else False),
        covenant_violations_count=covenant_violations_count,
        mda_summary=_to_text_block(response.get("mda_summary", "")),
        forward_guidance_revenue=_to_float(response.get("forward_guidance_revenue")),
        forward_guidance_eps=_to_float(response.get("forward_guidance_eps")),
        key_strategic_initiatives=_to_text_block(response.get("key_strategic_initiatives", "")),
        risk_factors=_to_text_block(response.get("risk_factors", "")),
    )


# ─── Markdown rendering ──────────────────────────────────────────────────


def render_annual_report_markdown(report: AnnualReport, firm_name: str = "") -> str:
    """Render an AnnualReport as a 10-K-style markdown document."""
    name = firm_name or report.firm_id
    rev = report.annual_revenue
    margin = (report.annual_gross_profit / max(1.0, rev)) * 100
    debt = report.year_end_long_term_debt + report.year_end_revolver_balance

    return f"""# Annual Report — {name} ({report.firm_id})
## Fiscal Year {report.fyear}

---

### Key Financial Highlights

| Metric | Value |
|---|---|
| Total revenue | ${rev:,.0f} |
| Gross profit | ${report.annual_gross_profit:,.0f} ({margin:.1f}% margin) |
| Operating income | ${report.annual_operating_income:,.0f} |
| Net income | ${report.annual_net_income:,.0f} |
| EPS | ${report.annual_eps:.2f} |
| Year-over-year revenue growth | {report.yoy_revenue_growth * 100:+.1f}% |
| Year-over-year NI growth | {report.yoy_ni_growth * 100:+.1f}% |

### Year-End Balance Sheet

| Line | Value |
|---|---|
| Cash and equivalents | ${report.year_end_cash:,.0f} |
| Total assets | ${report.year_end_total_assets:,.0f} |
| Total liabilities | ${report.year_end_total_liabilities:,.0f} |
| Long-term debt | ${report.year_end_long_term_debt:,.0f} |
| Revolver balance | ${report.year_end_revolver_balance:,.0f} |
| Total equity | ${report.year_end_total_equity:,.0f} |
| Shares outstanding | {report.year_end_shares_outstanding:,} |
| Year-end share price | ${report.year_end_share_price:.2f} |

### Cash Flow Summary

| Activity | Amount |
|---|---|
| Operating | ${report.annual_cfo:,.0f} |
| Investing | ${report.annual_cfi:,.0f} |
| Financing | ${report.annual_cff:,.0f} |
| Capital expenditures | ${report.annual_capex:,.0f} |

### Capital Activity During the Year

| Activity | Amount |
|---|---|
| Equity issued | ${report.equity_issued_during_year:,.0f} |
| Debt issued (approx) | ${report.debt_issued_during_year:,.0f} |
| Dividends paid | ${report.dividends_paid:,.0f} |
| Share buybacks | ${report.buybacks:,.0f} |

### Audit & Compliance

- **Audit opinion**: {report.audit_opinion or "(not audited this year)"}
- **Going concern flag**: {"YES — material doubt about firm's ability to continue" if report.going_concern_flag else "no"}
- **Debt covenant violations during year**: {report.covenant_violations_count}

---

## Management Discussion & Analysis

{report.mda_summary or "(Management discussion not available.)"}

---

## Forward Guidance

- **Revenue (next fiscal year)**: ${report.forward_guidance_revenue:,.0f}
- **EPS (next fiscal year)**: ${report.forward_guidance_eps:.2f}

## Key Strategic Initiatives

{report.key_strategic_initiatives or "(Not specified.)"}

## Risk Factors

{report.risk_factors or "(Not specified.)"}
"""


# ─── Factory ─────────────────────────────────────────────────────────────


def make_annual_report_generator(backends: dict[str, LLMBackend], state_ref: list):
    """Factory: returns a function the orchestrator calls at fqtr=4 for each firm.

    Reuses the firm's own LLM backend (same model that ran the firm's quarterly
    decisions). Returns an AnnualReport.
    """

    def generate(firm: FirmState,
                 year_rows: list[CompustatRow],
                 prior_year_rows: list[CompustatRow] | None,
                 macro: MacroState,
                 audit: AuditResult | None,
                 covenant_violations_count: int) -> AnnualReport:
        agg = aggregate_year(firm, year_rows, prior_year_rows)
        if not agg:
            # No data — return an empty report so downstream still works
            return AnnualReport(firm_id=firm.firm_id, fyear=macro.fyear,
                                quarter=macro.quarter)
        prior_agg = (aggregate_year(firm, prior_year_rows)
                     if prior_year_rows else None)

        backend = backends.get(firm.firm_id)
        if backend is None:
            # No LLM available — return aggregate-only report
            return parse_annual_report(None, firm, macro, agg, audit,
                                        covenant_violations_count)

        system, user = build_annual_prompt(firm, agg, macro, audit, prior_agg)
        from . import telemetry as _tel
        try:
            with _tel.set_role(f"annual_report_{firm.firm_id}"):
                result = backend.complete_json(system, user)
        except Exception:
            result = None
        return parse_annual_report(result, firm, macro, agg, audit,
                                    covenant_violations_count)

    return generate
