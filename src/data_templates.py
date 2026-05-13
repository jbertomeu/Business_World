"""
Data templates: callable statistical functions for the Data Broker.

Each function:
- Takes explicit parameters (metric name, firm_id, cohort criterion, etc.)
- Returns a structured dict: {"value": ..., "context": ..., "caveat": ...}
- Never formats prose — the Broker LLM interprets structured results

Data sources:
- Current run Compustat: outputs/run_{id}/compustat_q.csv
- Cross-run Compustat:   data/compustat_all.csv
- Scores:                data/scores.csv

All functions respect data tier filtering — they operate on pre-filtered
DataFrames handed in by the Broker.
"""

from __future__ import annotations

import csv
import math
import statistics
from pathlib import Path


# ── Loaders ─────────────────────────────────────────────────────────────

def load_cross_run(data_dir: str = "data") -> list[dict]:
    """Load cross-run Compustat panel. Returns list of dicts (columns as strings)."""
    path = Path(data_dir) / "compustat_all.csv"
    if not path.exists():
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def load_current_run(run_rows: list | None = None) -> list[dict]:
    """Load current run's Compustat rows (passed from orchestrator).

    Accepts either pre-converted dicts or CompustatRow objects. Returns
    a normalized list of dicts.
    """
    if not run_rows:
        return []
    out = []
    for r in run_rows:
        if isinstance(r, dict):
            out.append(r)
        elif hasattr(r, "as_dict"):
            out.append(r.as_dict())
        else:
            out.append(dict(r.__dict__))
    return out


def _to_float(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ── Template 1: peer benchmark ──────────────────────────────────────────

def peer_benchmark(
    metric: str,
    firm_id: str,
    rows: list[dict],
    quarter_filter: int | None = None,
) -> dict:
    """Where does this firm stand on `metric` vs its peers?

    Returns: value, cohort_mean, cohort_median, z_score, percentile, rank, cohort_size.
    """
    # Filter to a single quarter (last quarter if unspecified)
    if quarter_filter is None:
        quarters = sorted({int(r.get("fqtr", 0)) for r in rows if r.get("fqtr")})
        if not quarters:
            return {"error": "no rows with quarter data"}
        # Last fyearq+fqtr combo
        latest_rows = sorted(rows, key=lambda r: (int(r.get("fyearq", 0)), int(r.get("fqtr", 0))))
        if not latest_rows:
            return {"error": "no rows"}
        last = latest_rows[-1]
        fy, fq = last.get("fyearq"), last.get("fqtr")
        cohort_rows = [r for r in rows if r.get("fyearq") == fy and r.get("fqtr") == fq]
    else:
        cohort_rows = [r for r in rows if int(r.get("fqtr", 0)) == quarter_filter]

    values = [(r.get("firm_id", ""), _to_float(r.get(metric))) for r in cohort_rows]
    values = [(fid, v) for fid, v in values if v is not None]
    if len(values) < 2:
        return {"error": f"insufficient cohort size ({len(values)})"}

    firm_val = next((v for fid, v in values if fid == firm_id), None)
    if firm_val is None:
        return {"error": f"firm {firm_id} not in cohort"}

    all_vals = [v for _, v in values]
    mean = statistics.mean(all_vals)
    median = statistics.median(all_vals)
    sd = statistics.stdev(all_vals) if len(all_vals) > 1 else 0.0

    z = (firm_val - mean) / sd if sd > 0 else 0.0
    below = sum(1 for v in all_vals if v < firm_val)
    percentile = below / len(all_vals) * 100

    sorted_desc = sorted(all_vals, reverse=True)
    rank = sorted_desc.index(firm_val) + 1

    return {
        "metric": metric,
        "firm_id": firm_id,
        "firm_value": firm_val,
        "cohort_mean": mean,
        "cohort_median": median,
        "cohort_sd": sd,
        "z_score": z,
        "percentile": percentile,
        "rank": rank,
        "cohort_size": len(all_vals),
        "all_values": {fid: v for fid, v in values},
    }


# ── Template 2: time series ─────────────────────────────────────────────

def time_series(
    metric: str,
    firm_id: str,
    rows: list[dict],
    lookback: int = 8,
) -> dict:
    """Time-series on `metric` for one firm. Returns trend, volatility, AR(1).

    lookback: max quarters to include (most recent N).
    """
    firm_rows = [r for r in rows if r.get("firm_id") == firm_id]
    firm_rows.sort(key=lambda r: (int(r.get("fyearq", 0)), int(r.get("fqtr", 0))))
    firm_rows = firm_rows[-lookback:]

    values = [_to_float(r.get(metric)) for r in firm_rows]
    values = [v for v in values if v is not None]
    if len(values) < 3:
        return {"error": f"insufficient time series ({len(values)} quarters)"}

    # Linear trend slope (OLS on t)
    n = len(values)
    t = list(range(n))
    t_mean = sum(t) / n
    v_mean = sum(values) / n
    num = sum((ti - t_mean) * (vi - v_mean) for ti, vi in zip(t, values))
    den = sum((ti - t_mean) ** 2 for ti in t)
    slope = num / den if den > 0 else 0.0
    intercept = v_mean - slope * t_mean

    # Volatility: std dev of residuals from trend
    residuals = [v - (slope * ti + intercept) for ti, v in zip(t, values)]
    vol = statistics.stdev(residuals) if len(residuals) > 1 else 0.0

    # AR(1): lag-1 autocorrelation on deviations
    if len(residuals) >= 2:
        r0 = residuals[:-1]
        r1 = residuals[1:]
        m0, m1 = sum(r0)/len(r0), sum(r1)/len(r1)
        cov = sum((a-m0)*(b-m1) for a, b in zip(r0, r1)) / len(r0)
        v0 = statistics.pvariance(r0) or 1e-9
        v1 = statistics.pvariance(r1) or 1e-9
        ar1 = cov / (math.sqrt(v0 * v1))
    else:
        ar1 = 0.0

    # QoQ growth
    qoq = []
    for i in range(1, n):
        if values[i-1] != 0:
            qoq.append((values[i] - values[i-1]) / abs(values[i-1]))
    qoq_mean = statistics.mean(qoq) if qoq else 0.0

    return {
        "metric": metric,
        "firm_id": firm_id,
        "n_quarters": n,
        "values": values,
        "trend_slope": slope,
        "volatility": vol,
        "ar1": ar1,
        "mean_qoq_growth": qoq_mean,
        "latest": values[-1],
        "earliest": values[0],
    }


# ── Template 3: anomaly z-score ─────────────────────────────────────────

def anomaly_score(
    metric: str,
    firm_id: str,
    rows: list[dict],
) -> dict:
    """How unusual is firm's latest value on this metric vs its own history AND peers?"""

    # Cohort z-score (latest quarter)
    peer = peer_benchmark(metric, firm_id, rows)
    if "error" in peer:
        return peer

    # Self-history z-score
    ts = time_series(metric, firm_id, rows, lookback=12)
    if "error" in ts:
        return {**peer, "self_history_error": ts["error"]}

    firm_val = ts["latest"]
    prior_values = ts["values"][:-1]
    if len(prior_values) < 3:
        self_z = 0.0
    else:
        self_mean = statistics.mean(prior_values)
        self_sd = statistics.stdev(prior_values) if len(prior_values) > 1 else 0.0
        self_z = (firm_val - self_mean) / self_sd if self_sd > 0 else 0.0

    return {
        "metric": metric,
        "firm_id": firm_id,
        "latest": firm_val,
        "peer_z_score": peer["z_score"],
        "peer_percentile": peer["percentile"],
        "self_history_z": self_z,
        "interpretation_hint": (
            "peer_z > 2 or < -2: unusual vs peers. "
            "self_history_z > 2 or < -2: unusual vs own history. "
            "Both extreme: likely a genuine anomaly."
        ),
    }


# ── Template 4: correlation ─────────────────────────────────────────────

def correlation(
    var1: str,
    var2: str,
    rows: list[dict],
    lag: int = 0,
) -> dict:
    """Pearson correlation between two metrics in the panel.

    lag: if > 0, var2 is measured `lag` quarters after var1 for the same firm.
    """
    pairs = []
    if lag == 0:
        for r in rows:
            a = _to_float(r.get(var1))
            b = _to_float(r.get(var2))
            if a is not None and b is not None:
                pairs.append((a, b))
    else:
        # By firm, sorted by time
        by_firm = {}
        for r in rows:
            fid = r.get("firm_id", "")
            by_firm.setdefault(fid, []).append(r)
        for fid, frows in by_firm.items():
            frows.sort(key=lambda r: (int(r.get("fyearq", 0)), int(r.get("fqtr", 0))))
            for i in range(len(frows) - lag):
                a = _to_float(frows[i].get(var1))
                b = _to_float(frows[i + lag].get(var2))
                if a is not None and b is not None:
                    pairs.append((a, b))

    n = len(pairs)
    if n < 3:
        return {"error": f"insufficient data ({n} pairs)"}

    xs = [p[0] for p in pairs]
    ys = [p[1] for p in pairs]
    mx, my = sum(xs)/n, sum(ys)/n
    num = sum((x-mx)*(y-my) for x, y in pairs)
    denx = math.sqrt(sum((x-mx)**2 for x in xs))
    deny = math.sqrt(sum((y-my)**2 for y in ys))
    r = num / (denx * deny) if denx > 0 and deny > 0 else 0.0

    return {
        "var1": var1, "var2": var2,
        "lag_quarters": lag,
        "pearson_r": r,
        "sample_size": n,
        "interpretation_hint": "|r| > 0.5: strong. 0.3-0.5: moderate. <0.3: weak."
    }


# ── Template 5: cohort compare ──────────────────────────────────────────

def cohort_compare(
    firm_id: str,
    rows: list[dict],
    cohort_criterion: str = "same_quarter",
    metrics: list[str] | None = None,
) -> dict:
    """Compare firm vs a cohort on several key metrics.

    cohort_criterion:
      - "same_quarter":   firms in the same fyearq+fqtr
      - "same_generation": firms at same product generation
    """
    if metrics is None:
        metrics = ["saleq", "niq", "xrdq", "xsgaq", "cheq", "ceqq"]

    # Find the firm's latest row
    firm_rows = [r for r in rows if r.get("firm_id") == firm_id]
    if not firm_rows:
        return {"error": f"firm {firm_id} not found"}
    firm_rows.sort(key=lambda r: (int(r.get("fyearq", 0)), int(r.get("fqtr", 0))))
    firm_row = firm_rows[-1]
    fy, fq = firm_row.get("fyearq"), firm_row.get("fqtr")

    # Build cohort
    if cohort_criterion == "same_quarter":
        cohort = [r for r in rows if r.get("fyearq") == fy and r.get("fqtr") == fq
                  and r.get("firm_id") != firm_id]
    elif cohort_criterion == "same_generation":
        gen = firm_row.get("product_generation", 1)
        cohort = [r for r in rows if r.get("product_generation") == gen
                  and r.get("firm_id") != firm_id]
    else:
        return {"error": f"unknown cohort_criterion {cohort_criterion}"}

    if len(cohort) < 2:
        return {"error": f"insufficient cohort ({len(cohort)})"}

    result = {
        "firm_id": firm_id,
        "cohort_criterion": cohort_criterion,
        "cohort_size": len(cohort),
        "comparisons": {},
    }
    for m in metrics:
        firm_val = _to_float(firm_row.get(m))
        cohort_vals = [_to_float(r.get(m)) for r in cohort]
        cohort_vals = [v for v in cohort_vals if v is not None]
        if firm_val is None or len(cohort_vals) < 2:
            continue
        mean = statistics.mean(cohort_vals)
        median = statistics.median(cohort_vals)
        sd = statistics.stdev(cohort_vals) if len(cohort_vals) > 1 else 0.0
        result["comparisons"][m] = {
            "firm_value": firm_val,
            "cohort_mean": mean,
            "cohort_median": median,
            "cohort_sd": sd,
            "z_score": (firm_val - mean) / sd if sd > 0 else 0.0,
        }
    return result


# ── Template 6: DCF projection ──────────────────────────────────────────

def dcf_projection(
    revenue_last_4q: list[float],
    opex_last_4q: list[float],
    growth_rate_annual: float,
    discount_rate_annual: float,
    terminal_growth: float = 0.03,
    horizon_quarters: int = 20,
) -> dict:
    """Simple 20-quarter DCF with terminal value.

    Projections assume constant annual growth and opex margin.
    """
    if len(revenue_last_4q) < 1 or len(opex_last_4q) < 1:
        return {"error": "insufficient input"}

    rev_ttm = sum(revenue_last_4q)
    opex_ttm = sum(opex_last_4q)
    opex_margin = opex_ttm / rev_ttm if rev_ttm > 0 else 0.9

    # Project quarterly
    q_growth = (1 + growth_rate_annual) ** 0.25 - 1
    q_disc = (1 + discount_rate_annual) ** 0.25 - 1

    pv = 0.0
    current_q_rev = rev_ttm / 4
    for t in range(1, horizon_quarters + 1):
        current_q_rev *= (1 + q_growth)
        cf = current_q_rev * (1 - opex_margin)
        pv += cf / ((1 + q_disc) ** t)

    # Terminal value at end of horizon
    terminal_q_rev = current_q_rev * (1 + q_growth)
    terminal_cf_annual = terminal_q_rev * 4 * (1 - opex_margin)
    tv = terminal_cf_annual / (discount_rate_annual - terminal_growth) if discount_rate_annual > terminal_growth else 0.0
    pv_tv = tv / ((1 + q_disc) ** horizon_quarters)

    return {
        "revenue_ttm": rev_ttm,
        "opex_margin": opex_margin,
        "growth_assumed": growth_rate_annual,
        "discount_rate": discount_rate_annual,
        "terminal_growth": terminal_growth,
        "horizon_quarters": horizon_quarters,
        "pv_operations": pv,
        "pv_terminal": pv_tv,
        "enterprise_value": pv + pv_tv,
        "caveat": "Assumes constant growth and opex margin. Sensitive to discount rate.",
    }


# ── Template 7: accrual quality ────────────────────────────────────────

def accrual_quality(
    firm_id: str,
    rows: list[dict],
    lookback: int = 8,
) -> dict:
    """Accrual quality: total accruals / total assets, and its volatility."""
    firm_rows = [r for r in rows if r.get("firm_id") == firm_id]
    firm_rows.sort(key=lambda r: (int(r.get("fyearq", 0)), int(r.get("fqtr", 0))))
    firm_rows = firm_rows[-lookback:]

    ratios = []
    for r in firm_rows:
        ni = _to_float(r.get("niq"))
        cfo = _to_float(r.get("oancfq"))
        at = _to_float(r.get("atq"))
        if ni is None or cfo is None or at is None or at == 0:
            continue
        accruals = ni - cfo
        ratios.append(accruals / at)

    if len(ratios) < 2:
        return {"error": f"insufficient data ({len(ratios)} quarters)"}

    mean_ratio = statistics.mean(ratios)
    sd_ratio = statistics.stdev(ratios) if len(ratios) > 1 else 0.0

    return {
        "firm_id": firm_id,
        "mean_accruals_to_assets": mean_ratio,
        "sd_accruals_to_assets": sd_ratio,
        "n_quarters": len(ratios),
        "series": ratios,
        "interpretation_hint": (
            "High positive mean: persistent overstatement signal. "
            "High SD: earnings smoothing or volatility. "
            "Dechow-Dichev-style: higher SD = lower earnings quality."
        ),
    }


# ── Template 8: credit metrics ──────────────────────────────────────────

def credit_metrics(
    firm_id: str,
    rows: list[dict],
) -> dict:
    """Credit-focused ratios from latest row: leverage, coverage, liquidity."""
    firm_rows = [r for r in rows if r.get("firm_id") == firm_id]
    if not firm_rows:
        return {"error": f"firm {firm_id} not found"}
    firm_rows.sort(key=lambda r: (int(r.get("fyearq", 0)), int(r.get("fqtr", 0))))
    row = firm_rows[-1]

    cash = _to_float(row.get("cheq")) or 0
    at = _to_float(row.get("atq")) or 0
    ltq = _to_float(row.get("ltq")) or 0
    ceqq = _to_float(row.get("ceqq")) or 0
    oiadpq = _to_float(row.get("oiadpq")) or 0
    xintq = _to_float(row.get("xintq")) or 0
    oancfq = _to_float(row.get("oancfq")) or 0
    dlcq = _to_float(row.get("dlcq")) or 0
    dlttq = _to_float(row.get("dlttq")) or 0

    total_debt = dlcq + dlttq
    interest_coverage = oiadpq / xintq if xintq > 0 else float("inf")
    leverage = total_debt / at if at > 0 else 0
    debt_equity = total_debt / ceqq if ceqq > 0 else 0
    cash_runway_q = cash / abs(oancfq) if oancfq < 0 else float("inf")

    return {
        "firm_id": firm_id,
        "cash": cash,
        "total_debt": total_debt,
        "total_assets": at,
        "total_equity": ceqq,
        "debt_to_assets": leverage,
        "debt_to_equity": debt_equity,
        "interest_coverage": interest_coverage,
        "cash_runway_quarters": cash_runway_q,
        "caveat": "Runway assumes current burn rate persists. Coverage infinite if no interest expense.",
    }


# ── Template 9: forecast accuracy ───────────────────────────────────────

def forecast_accuracy(
    firm_id: str,
    rows: list[dict],
    forecast_quarters: list[int] | None = None,
) -> dict:
    """Compare management guidance to actuals.

    Requires guidance data from EarningsRelease history (passed via rows
    with guidance_eps_1q column, if available).
    """
    # This needs guidance passed explicitly; for now operate on Compustat only
    return {
        "firm_id": firm_id,
        "note": (
            "Forecast accuracy requires guidance history. "
            "Query the Broker with guidance data explicitly passed."
        ),
    }


# ── Template 10: DuPont decomposition (traditional) ────────────────────

def dupont_decomposition(
    firm_id: str,
    rows: list[dict],
    lookback: int = 4,
) -> dict:
    """Traditional DuPont: ROE = NPM × Asset Turnover × Equity Multiplier.

    Computes the trailing 4Q (or specified lookback) decomposition for one firm.
    """
    firm_rows = [r for r in rows if r.get("firm_id") == firm_id]
    firm_rows.sort(key=lambda r: (int(r.get("fyearq", 0)), int(r.get("fqtr", 0))))
    firm_rows = firm_rows[-lookback:]

    if not firm_rows:
        return {"error": f"firm {firm_id} not found"}

    sale_ttm = sum(_to_float(r.get("saleq")) or 0 for r in firm_rows)
    ni_ttm = sum(_to_float(r.get("niq")) or 0 for r in firm_rows)

    last = firm_rows[-1]
    avg_assets = sum(_to_float(r.get("atq")) or 0 for r in firm_rows) / len(firm_rows)
    avg_equity = sum(_to_float(r.get("ceqq")) or 0 for r in firm_rows) / len(firm_rows)

    npm = ni_ttm / sale_ttm if sale_ttm else 0.0          # Net Profit Margin
    at = sale_ttm / avg_assets if avg_assets else 0.0     # Asset Turnover
    leverage = avg_assets / avg_equity if avg_equity else 0.0  # Equity Multiplier
    roe = npm * at * leverage

    return {
        "firm_id": firm_id,
        "ttm_revenue": sale_ttm,
        "ttm_net_income": ni_ttm,
        "avg_total_assets": avg_assets,
        "avg_total_equity": avg_equity,
        "npm": npm,
        "asset_turnover": at,
        "equity_multiplier": leverage,
        "roe": roe,
        "interpretation_hint": (
            "ROE = NPM × AT × Leverage. NPM measures profitability of sales; "
            "AT measures efficiency of asset use; Leverage amplifies. Compare to peers."
        ),
    }


# ── Template 11: RNOA decomposition (Penman-style operating/financing) ─

def rnoa_decomposition(
    firm_id: str,
    rows: list[dict],
    lookback: int = 4,
    tax_rate: float = 0.21,
) -> dict:
    """Penman-style decomposition separating operating from financing leverage.

    ROE = RNOA + (RNOA - NBC) × NFL
      RNOA = NOPAT / NOA      (Return on Net Operating Assets)
      NBC  = After-tax interest / NFO   (Net Borrowing Cost)
      NFL  = NFO / CSE        (Net Financial Leverage)
    """
    firm_rows = [r for r in rows if r.get("firm_id") == firm_id]
    firm_rows.sort(key=lambda r: (int(r.get("fyearq", 0)), int(r.get("fqtr", 0))))
    firm_rows = firm_rows[-lookback:]
    if not firm_rows:
        return {"error": f"firm {firm_id} not found"}

    last = firm_rows[-1]

    # Trailing twelve months (TTM) operating income, interest, NI
    oi_ttm = sum(_to_float(r.get("oiadpq")) or 0 for r in firm_rows)
    int_ttm = sum(_to_float(r.get("xintq")) or 0 for r in firm_rows)
    ni_ttm = sum(_to_float(r.get("niq")) or 0 for r in firm_rows)

    # NOPAT = operating income × (1 - tax_rate); after-tax interest = int × (1 - tax_rate)
    nopat = oi_ttm * (1 - tax_rate)
    after_tax_int = int_ttm * (1 - tax_rate)

    # Net Operating Assets (NOA) ≈ Operating WC + PP&E
    # = (AR + Inventory + Other operating - AP - Accrued - Taxes payable) + PP&E_net
    cash = _to_float(last.get("cheq")) or 0
    ar = _to_float(last.get("rectq")) or 0
    inv = _to_float(last.get("invtq")) or 0
    ppe = _to_float(last.get("ppentq")) or 0
    ap = _to_float(last.get("apq")) or 0
    accrued = _to_float(last.get("xaccq")) or 0  # WRDS convention (was mis-labeled acoq)
    txp = _to_float(last.get("txpq")) or 0
    op_wc = ar + inv - ap - accrued - txp
    noa = op_wc + ppe

    # Net Financial Obligations (NFO) = total debt - excess cash
    # Excess cash assumption: all cash is "operating" minimum; excess depends. Simplify: NFO = LTD + ST debt - cash
    ltd = _to_float(last.get("dlttq")) or 0
    std = _to_float(last.get("dlcq")) or 0
    nfo = (ltd + std) - cash
    cse = _to_float(last.get("ceqq")) or 0  # Common Shareholders Equity

    rnoa = nopat / noa if noa else 0.0
    nbc = after_tax_int / nfo if nfo > 0 else 0.0  # only meaningful if net obligation
    nfl = nfo / cse if cse else 0.0
    spread = rnoa - nbc
    leverage_effect = spread * nfl
    roe = rnoa + leverage_effect

    return {
        "firm_id": firm_id,
        "nopat_ttm": nopat,
        "noa": noa,
        "nfo": nfo,
        "cse": cse,
        "rnoa": rnoa,
        "nbc": nbc,
        "nfl": nfl,
        "spread_rnoa_minus_nbc": spread,
        "leverage_effect_on_roe": leverage_effect,
        "roe_total": roe,
        "interpretation_hint": (
            "ROE = RNOA + (RNOA - NBC) × NFL. Operating return (RNOA) is the core; "
            "financing leverage amplifies (or destroys) value depending on whether "
            "RNOA exceeds borrowing cost. Negative spread + high leverage = wealth destruction."
        ),
        "caveat": (
            "Tax rate assumed 21%. NOA may include non-operating items if firm "
            "carries excess cash; treat directionally, not precisely."
        ),
    }


# ── Template 12: Residual Income valuation ─────────────────────────────

def residual_income_valuation(
    firm_id: str,
    rows: list[dict],
    cost_of_equity_annual: float,
    horizon_quarters: int = 20,
    terminal_growth_annual: float = 0.03,
    lookback_for_estimates: int = 4,
) -> dict:
    """Residual Income (RI) valuation: V = BV + Σ PV(RI_t) + terminal.

    RI_t = Net Income_t - r_e × BV_{t-1}
    Uses TTM NI as the base earnings expectation; book value from latest row.
    """
    firm_rows = [r for r in rows if r.get("firm_id") == firm_id]
    firm_rows.sort(key=lambda r: (int(r.get("fyearq", 0)), int(r.get("fqtr", 0))))
    if not firm_rows:
        return {"error": f"firm {firm_id} not found"}

    last = firm_rows[-1]
    bv = _to_float(last.get("ceqq")) or 0
    if bv <= 0:
        return {"error": "non-positive book value; RI valuation undefined"}

    # TTM net income as base run-rate
    ttm_rows = firm_rows[-lookback_for_estimates:]
    ni_ttm = sum(_to_float(r.get("niq")) or 0 for r in ttm_rows)
    annual_ni = ni_ttm  # already TTM

    r_e_annual = cost_of_equity_annual
    r_e_quarterly = (1 + r_e_annual) ** 0.25 - 1

    # Project: hold annual_ni constant for horizon, then terminal RI growth
    pv_ri = 0.0
    bv_t = bv
    for t in range(1, horizon_quarters + 1):
        ni_t = annual_ni / 4  # quarterly NI
        ri_t = ni_t - r_e_quarterly * bv_t
        pv_ri += ri_t / ((1 + r_e_quarterly) ** t)
        bv_t = bv_t + ni_t   # clean surplus: BV grows by retained earnings (no dividends assumed)

    # Terminal RI (perpetuity growing at terminal_growth)
    if r_e_annual > terminal_growth_annual:
        terminal_ri = (annual_ni - r_e_annual * bv_t) / (r_e_annual - terminal_growth_annual)
        pv_terminal = terminal_ri / ((1 + r_e_quarterly) ** horizon_quarters)
    else:
        pv_terminal = 0.0

    intrinsic_value = bv + pv_ri + pv_terminal

    return {
        "firm_id": firm_id,
        "book_value": bv,
        "ttm_net_income": ni_ttm,
        "cost_of_equity_annual": r_e_annual,
        "horizon_quarters": horizon_quarters,
        "terminal_growth_annual": terminal_growth_annual,
        "pv_residual_income": pv_ri,
        "pv_terminal": pv_terminal,
        "intrinsic_equity_value": intrinsic_value,
        "interpretation_hint": (
            "RI valuation: book value + PV of residual income (NI above cost of equity). "
            "If TTM NI < r_e × BV, firm is destroying value relative to required return; "
            "RI will be negative; intrinsic value < book value."
        ),
        "caveat": (
            "Holds annual_ni constant for the explicit horizon (no growth path modeled). "
            "Sensitive to r_e and terminal growth assumptions."
        ),
    }


# ── Template 13: Peer multiples analysis ───────────────────────────────

def peer_multiple_analysis(
    firm_id: str,
    rows: list[dict],
    metric: str = "saleq",            # numerator base for the multiple
    multiple_type: str = "p_s",       # "p_s" | "p_b" | "ev_sales"
    exclude_firms: list[str] | None = None,
    quarter_filter: int | None = None,
) -> dict:
    """Compute a price multiple for the firm and compare to peers.

    Researcher chooses the multiple type and which peers to exclude (e.g.,
    defaulted firms, outliers).
    """
    exclude = set(exclude_firms or [])
    if quarter_filter is None:
        latest_rows = sorted(rows, key=lambda r: (int(r.get("fyearq", 0)), int(r.get("fqtr", 0))))
        if not latest_rows:
            return {"error": "no rows"}
        last = latest_rows[-1]
        fy, fq = last.get("fyearq"), last.get("fqtr")
        cohort_rows = [r for r in rows if r.get("fyearq") == fy and r.get("fqtr") == fq]
    else:
        cohort_rows = [r for r in rows if int(r.get("fqtr", 0)) == quarter_filter]

    def compute_multiple(row):
        prccq = _to_float(row.get("prccq"))
        cshoq = _to_float(row.get("cshoq"))    # in millions
        if prccq is None or cshoq is None or cshoq <= 0:
            return None
        mkt_cap = prccq * cshoq * 1_000_000
        if multiple_type == "p_s":
            denom = (_to_float(row.get("saleq")) or 0) * 4  # annualized
            return mkt_cap / denom if denom > 0 else None
        if multiple_type == "p_b":
            denom = _to_float(row.get("ceqq")) or 0
            return mkt_cap / denom if denom > 0 else None
        if multiple_type == "ev_sales":
            debt = (_to_float(row.get("dlttq")) or 0) + (_to_float(row.get("dlcq")) or 0)
            cash = _to_float(row.get("cheq")) or 0
            ev = mkt_cap + debt - cash
            denom = (_to_float(row.get("saleq")) or 0) * 4
            return ev / denom if denom > 0 else None
        return None

    firm_mult = None
    peers = []
    for r in cohort_rows:
        fid = r.get("firm_id", "")
        if fid in exclude:
            continue
        m = compute_multiple(r)
        if m is None:
            continue
        if fid == firm_id:
            firm_mult = m
        else:
            peers.append((fid, m))

    if firm_mult is None:
        return {"error": f"could not compute multiple for {firm_id}"}
    if len(peers) < 1:
        return {"error": "insufficient peers"}

    peer_vals = [m for _, m in peers]
    median = statistics.median(peer_vals)
    mean = statistics.mean(peer_vals)
    sd = statistics.stdev(peer_vals) if len(peer_vals) > 1 else 0.0
    z = (firm_mult - mean) / sd if sd > 0 else 0.0
    discount_premium_to_median = (firm_mult - median) / median if median else 0.0

    return {
        "firm_id": firm_id,
        "multiple_type": multiple_type,
        "firm_multiple": firm_mult,
        "peer_count": len(peers),
        "excluded_count": len(exclude),
        "peer_median": median,
        "peer_mean": mean,
        "peer_sd": sd,
        "peer_values": dict(peers),
        "z_score": z,
        "premium_or_discount_to_median": discount_premium_to_median,
        "interpretation_hint": (
            "Positive premium = firm trades richer than peer median; negative = at discount. "
            "Z-score > 2 or < -2 is unusual. Choice of multiple matters: P/S for unprofitable, "
            "P/B for asset-heavy, EV/Sales for capital-structure-neutral comparisons."
        ),
    }


# ── Template 14: industry concentration (formerly #10) ─────────────────

def industry_concentration(
    rows: list[dict],
    quarter: int | None = None,
) -> dict:
    """HHI and top-N share for latest (or specified) quarter."""
    if quarter is None:
        # Use latest available quarter
        sorted_rows = sorted(rows, key=lambda r: (int(r.get("fyearq", 0)), int(r.get("fqtr", 0))))
        if not sorted_rows:
            return {"error": "no data"}
        last = sorted_rows[-1]
        fy, fq = last.get("fyearq"), last.get("fqtr")
        cohort = [r for r in rows if r.get("fyearq") == fy and r.get("fqtr") == fq]
    else:
        cohort = [r for r in rows if int(r.get("fqtr", 0)) == quarter]

    revenues = [(r.get("firm_id", ""), _to_float(r.get("saleq")) or 0) for r in cohort]
    total = sum(v for _, v in revenues)
    if total == 0:
        return {"error": "zero total revenue"}

    shares = [(fid, v / total) for fid, v in revenues]
    hhi = sum(s ** 2 for _, s in shares) * 10000  # scaled to standard HHI (0-10000)
    shares_sorted = sorted(shares, key=lambda x: -x[1])
    top_3_share = sum(s for _, s in shares_sorted[:3])

    return {
        "n_firms": len(shares),
        "total_revenue": total,
        "hhi": hhi,
        "top_3_share": top_3_share,
        "firm_shares": {fid: s for fid, s in shares_sorted},
        "caveat": "HHI > 2500 = highly concentrated. 1500-2500 = moderately. < 1500 = competitive.",
    }


# ── Registry ────────────────────────────────────────────────────────────

TEMPLATE_REGISTRY = {
    "peer_benchmark": peer_benchmark,
    "time_series": time_series,
    "anomaly_score": anomaly_score,
    "correlation": correlation,
    "cohort_compare": cohort_compare,
    "dcf_projection": dcf_projection,
    "accrual_quality": accrual_quality,
    "credit_metrics": credit_metrics,
    "dupont_decomposition": dupont_decomposition,
    "rnoa_decomposition": rnoa_decomposition,
    "residual_income_valuation": residual_income_valuation,
    "peer_multiple_analysis": peer_multiple_analysis,
    "forecast_accuracy": forecast_accuracy,
    "industry_concentration": industry_concentration,
}
