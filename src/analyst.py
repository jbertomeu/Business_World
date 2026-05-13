"""
Data Analyst: statistical analysis that runs BEFORE board discussions.

The analyst performs quantitative analysis on:
1. Cross-run Compustat data (regressions, correlations from past simulations)
2. Within-run trends (own firm performance trajectory)
3. Competitive benchmarks (how this firm compares to peers and historical norms)

CRITICAL DESIGN PRINCIPLE:
The analyst provides DATA and STATISTICAL RESULTS. It does NOT make decisions.
The board discussion (CEO/CFO/COO) interprets the analysis and decides.
Think of the analyst as a junior associate who prepares a briefing deck —
the executives still have to decide what to do with the information.

For the ENVIRONMENT, the analyst summarizes player feedback from prior runs
to enable self-improvement in demand allocation and event generation.
"""

from __future__ import annotations

import csv
import math
from collections import defaultdict
from pathlib import Path

from .types import FirmState, QuarterFlows


def run_firm_analysis(
    firm: FirmState,
    last_flows: dict | None,
    competitors: dict,
    data_dir: str = "data",
) -> str:
    """Run statistical analysis for a firm's board discussion.

    Returns a text briefing suitable for prompt inclusion.
    This is ANALYSIS, not recommendations.
    """
    sections = []

    # ── Section 1: Own performance trends ────────────────────────────────
    sections.append(_analyze_own_trajectory(firm, last_flows))

    # ── Section 2: Competitive position ──────────────────────────────────
    sections.append(_analyze_competitive_position(firm, last_flows, competitors))

    # ── Section 3: Cross-run regression insights ─────────────────────────
    cross_run = _analyze_cross_run_data(firm, data_dir)
    if cross_run:
        sections.append(cross_run)

    return "\n\n".join(s for s in sections if s)


def run_environment_analysis(
    data_dir: str = "data",
) -> str:
    """Run analysis for the environment agent.

    Summarizes player feedback (realism votes) and demand model accuracy
    from past runs to help the environment self-improve.
    """
    sections = []

    # Demand accuracy from past runs
    demand_analysis = _analyze_past_demand_accuracy(data_dir)
    if demand_analysis:
        sections.append(demand_analysis)

    # Scoring feedback
    feedback = _analyze_past_scores(data_dir)
    if feedback:
        sections.append(feedback)

    if not sections:
        return ""

    return "DATA ANALYST BRIEFING FOR ENVIRONMENT:\n" + "\n\n".join(sections)


# ─── Firm Analysis Components ────────────────────────────────────────────

def _analyze_own_trajectory(firm: FirmState, last_flows: dict | None) -> str:
    """Analyze the firm's own performance trend."""
    lines = ["DATA ANALYST BRIEFING:"]

    if not last_flows:
        lines.append("  (First quarter — no historical data to analyze)")
        return "\n".join(lines)

    rev = last_flows.get("net_sales", 0)
    ni = last_flows.get("net_income", 0)
    cfo = last_flows.get("cfo", 0)
    rd = last_flows.get("actual_rd_spend", 0)
    sga = last_flows.get("actual_sga_spend", 0)

    # Key ratios (numbers derive from the firm's own P&L; no external norms)
    if rev > 0:
        rd_intensity = rd / rev
        sga_intensity = sga / rev
        ni_margin = ni / rev
        lines.append(f"  Performance Ratios:")
        lines.append(f"    R&D intensity: {rd_intensity:.0%} of revenue")
        lines.append(f"    SGA intensity: {sga_intensity:.0%} of revenue")
        lines.append(f"    Net margin: {ni_margin:.0%}")

    # Cash burn analysis
    if cfo < 0:
        burn_rate = -cfo
        runway = firm.cash / burn_rate if burn_rate > 0 else float('inf')
        lines.append(f"  Cash Analysis:")
        lines.append(f"    Quarterly burn rate: ${burn_rate/1e6:.1f}M")
        lines.append(f"    Cash runway: {runway:.1f} quarters")
        lines.append(f"    Cash/Assets ratio: {firm.cash/max(1, firm.total_assets):.0%}")

    # R&D efficiency (progress shown as raw cumulative; no threshold leaked)
    if firm.quarter > 0 and rd > 0:
        lines.append(f"  R&D Progress:")
        lines.append(f"    Cumulative product R&D: ${firm.rd_cumulative_product/1e6:.0f}M")
        lines.append(f"    Avg investment per quarter: ${firm.rd_cumulative_product/max(1, firm.quarter)/1e6:.0f}M")

    return "\n".join(lines)


def _analyze_competitive_position(
    firm: FirmState,
    last_flows: dict | None,
    competitors: dict,
) -> str:
    """Compare firm to competitors using available public data."""
    lines = ["  Competitive Analysis:"]

    if not competitors:
        lines.append("    (No competitor data available)")
        return "\n".join(lines)

    # Extract competitor metrics
    comp_prices = []
    comp_shares = []
    comp_rds = []
    comp_revs = []

    for cid, c in competitors.items():
        if cid == firm.firm_id:
            continue
        comp_prices.append(c.get("price", 0))
        comp_shares.append(c.get("market_share", 0))
        comp_rds.append(c.get("total_rd_spend", 0))
        comp_revs.append(c.get("revenue", 0))

    if comp_prices:
        avg_price = sum(comp_prices) / len(comp_prices)
        own_price = last_flows.get("actual_price", 0) if last_flows else 0
        if avg_price > 0 and own_price > 0:
            price_position = (own_price - avg_price) / avg_price
            lines.append(f"    Your price vs competitors: {price_position:+.1%} "
                        f"({'premium' if price_position > 0 else 'discount'})")

    if comp_shares:
        avg_share = sum(comp_shares) / len(comp_shares)
        own_share = last_flows.get("market_share", 0) if last_flows else 0
        lines.append(f"    Your market share: {own_share:.1%} vs competitor avg: {avg_share:.1%}")

    if comp_rds:
        avg_rd = sum(comp_rds) / len(comp_rds)
        own_rd = last_flows.get("actual_rd_spend", 0) if last_flows else 0
        lines.append(f"    Your R&D: ${own_rd/1e6:.0f}M vs competitor avg: ${avg_rd/1e6:.0f}M")

    # Price-share correlation (from what we can see)
    if len(comp_prices) >= 2 and comp_shares:
        all_prices = comp_prices + [last_flows.get("actual_price", 0)] if last_flows else comp_prices
        all_shares = comp_shares + [last_flows.get("market_share", 0)] if last_flows else comp_shares
        if len(all_prices) == len(all_shares) and len(all_prices) >= 3:
            corr = _pearson_correlation(all_prices, all_shares)
            if corr is not None:
                direction = "NEGATIVE" if corr < -0.3 else "POSITIVE" if corr > 0.3 else "WEAK"
                lines.append(f"    Price-share correlation: {corr:.2f} ({direction}) — "
                            f"{'lower prices gain share' if corr < -0.3 else 'price not driving share' if abs(corr) < 0.3 else 'premium pricing working'}")

    return "\n".join(lines)


def _analyze_cross_run_data(firm: FirmState, data_dir: str) -> str:
    """Run statistical analysis on the accumulated cross-run Compustat."""
    compustat_path = Path(data_dir) / "compustat_all.csv"
    if not compustat_path.exists():
        return ""

    try:
        with open(compustat_path) as f:
            reader = csv.DictReader(f)
            rows = list(reader)
    except Exception:
        return ""

    if len(rows) < 10:
        return ""  # not enough data for meaningful stats

    lines = ["  Cross-Run Statistical Analysis (from past simulations):"]

    # Defensive float coercion — cross-run CSV may have schema drift from
    # older runs (e.g. new identifier columns added mid-stream). Swallow
    # ValueError so one malformed row doesn't kill the analysis.
    def _num(v):
        try:
            return float(v) if v not in (None, "", "None") else 0.0
        except (ValueError, TypeError):
            return 0.0

    # Revenue vs R&D correlation
    revs = [_num(r.get("saleq")) for r in rows if _num(r.get("saleq")) > 0]
    rds = [_num(r.get("xrdq")) for r in rows if _num(r.get("saleq")) > 0]

    if len(revs) >= 10:
        corr_rev_rd = _pearson_correlation(revs[:len(rds)], rds[:len(revs)])
        if corr_rev_rd is not None:
            lines.append(f"    Revenue-R&D correlation: {corr_rev_rd:.2f} "
                        f"({'higher R&D → higher revenue' if corr_rev_rd > 0.3 else 'no clear R&D→revenue link' if abs(corr_rev_rd) < 0.3 else 'surprising negative'})")

    def _int(v):
        try:
            return int(float(v)) if v not in (None, "", "None") else 0
        except (ValueError, TypeError):
            return 0

    # Cash at default analysis
    defaulted = [r for r in rows if _int(r.get("default_flag", 0)) == 1]
    non_default = [r for r in rows if _int(r.get("default_flag", 0)) == 0]

    if defaulted:
        avg_cash_at_default = sum(_num(r.get("cheq", 0)) for r in defaulted) / len(defaulted)
        lines.append(f"    Firms that defaulted: {len(defaulted)} (avg cash at default: ${avg_cash_at_default/1e6:.0f}M)")
    else:
        lines.append(f"    No defaults observed in {len(rows)} firm-quarters of past data")

    # Average metrics by quarter
    by_quarter = defaultdict(list)
    for r in rows:
        q = _int(r.get("fqtr", 0))
        by_quarter[q].append(r)

    if by_quarter:
        lines.append(f"    Average metrics by quarter (from {len(rows)} firm-Q observations):")
        for q in sorted(by_quarter.keys()):
            q_rows = by_quarter[q]
            avg_rev = sum(_num(r.get("saleq", 0)) for r in q_rows) / len(q_rows)
            avg_cash = sum(_num(r.get("cheq", 0)) for r in q_rows) / len(q_rows)
            lines.append(f"      Q{q}: Avg Rev=${avg_rev/1e6:.0f}M, Avg Cash=${avg_cash/1e6:.0f}M")

    # Scores analysis
    scores_path = Path(data_dir) / "scores.csv"
    if scores_path.exists():
        try:
            with open(scores_path) as f:
                score_rows = list(csv.DictReader(f))
            firm_scores = [r for r in score_rows if r.get("actor_type") == "firm"]
            if firm_scores:
                npvs = [_num(r.get("equity_npv", 0)) for r in firm_scores]
                irrs = [_num(r.get("equity_irr_annual", 0)) for r in firm_scores]
                invested = [_num(r.get("total_invested", 0)) for r in firm_scores]

                # NPV vs invested correlation (does more investment = better NPV?)
                if len(npvs) >= 5:
                    corr_npv_inv = _pearson_correlation(invested, npvs)
                    if corr_npv_inv is not None:
                        lines.append(f"    Investment-NPV correlation: {corr_npv_inv:.2f}")

                avg_npv = sum(npvs) / len(npvs)
                avg_irr = sum(irrs) / len(irrs)
                lines.append(f"    Past firm avg NPV: ${avg_npv/1e6:+.0f}M, avg IRR: {avg_irr*100:+.0f}%")
        except Exception:
            pass

    return "\n".join(lines)


def _analyze_past_demand_accuracy(data_dir: str) -> str:
    """Analyze how accurate the environment's demand allocation was in past runs."""
    compustat_path = Path(data_dir) / "compustat_all.csv"
    if not compustat_path.exists():
        return ""

    try:
        with open(compustat_path) as f:
            rows = list(csv.DictReader(f))
    except Exception:
        return ""

    if len(rows) < 10:
        return ""

    lines = ["  Demand Accuracy Self-Assessment:"]

    # Aggregate by run-quarter
    by_run_q = defaultdict(list)
    for r in rows:
        key = (r.get("run_id", ""), r.get("fyearq", ""), r.get("fqtr", ""))
        by_run_q[key].append(r)

    def _num2(v):
        try:
            return float(v) if v not in (None, "", "None") else 0.0
        except (ValueError, TypeError):
            return 0.0

    # Per-quarter industry revenue stats
    quarterly_revs = []
    for key, q_rows in by_run_q.items():
        total_rev = sum(_num2(r.get("saleq", 0)) for r in q_rows)
        quarterly_revs.append(total_rev)

    if quarterly_revs:
        avg_rev = sum(quarterly_revs) / len(quarterly_revs)
        std_rev = math.sqrt(sum((r - avg_rev)**2 for r in quarterly_revs) / len(quarterly_revs))
        lines.append(f"    Industry revenue: avg ${avg_rev/1e6:.0f}M/Q, std ${std_rev/1e6:.0f}M")
        lines.append(f"    Revenue variability (CV): {std_rev/max(1,avg_rev):.1%}")

    # HHI (market concentration) per quarter
    hhis = []
    for key, q_rows in by_run_q.items():
        total = sum(_num2(r.get("saleq", 0)) for r in q_rows)
        if total > 0:
            shares = [(_num2(r.get("saleq", 0)) / total)**2 for r in q_rows]
            hhis.append(sum(shares) * 10000)

    if hhis:
        avg_hhi = sum(hhis) / len(hhis)
        lines.append(f"    Avg market concentration (HHI): {avg_hhi:.0f} "
                    f"({'highly concentrated' if avg_hhi > 3000 else 'moderate' if avg_hhi > 1500 else 'competitive'})")

    return "\n".join(lines)


def _analyze_past_scores(data_dir: str) -> str:
    """Analyze past scoring data for environment self-improvement."""
    scores_path = Path(data_dir) / "scores.csv"
    if not scores_path.exists():
        return ""

    try:
        with open(scores_path) as f:
            rows = list(csv.DictReader(f))
    except Exception:
        return ""

    pricing_rows = [r for r in rows if r.get("actor_type") == "pricing"]
    if pricing_rows:
        rmses = [float(r.get("terminal_value", 0)) for r in pricing_rows]  # RMSE stored in terminal_value field
        mapes = [float(r.get("total_invested", 0)) for r in pricing_rows]  # MAPE stored in total_invested field
        avg_rmse = sum(rmses) / len(rmses)
        avg_mape = sum(mapes) / len(mapes)
        return (f"  Equity Pricing Performance Across Runs:\n"
                f"    Avg RMSE: ${avg_rmse:.2f}/share\n"
                f"    Avg MAPE: {avg_mape:.1%}\n"
                f"    (Lower is better. Consider if your demand allocations are too predictable.)")

    return ""


# ─── Statistical Utilities ───────────────────────────────────────────────

def _pearson_correlation(x: list[float], y: list[float]) -> float | None:
    """Compute Pearson correlation between two lists."""
    n = min(len(x), len(y))
    if n < 3:
        return None

    x = x[:n]
    y = y[:n]

    mean_x = sum(x) / n
    mean_y = sum(y) / n

    cov = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y)) / n
    std_x = math.sqrt(sum((xi - mean_x)**2 for xi in x) / n)
    std_y = math.sqrt(sum((yi - mean_y)**2 for yi in y) / n)

    if std_x < 1e-10 or std_y < 1e-10:
        return None

    return cov / (std_x * std_y)
