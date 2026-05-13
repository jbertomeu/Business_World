"""
Baseline research regressions on the cross-run datasets.

Three specifications — each matches a standard empirical corporate-finance
paper:

1. **Pay-performance sensitivity** (Jensen-Murphy style)
       log(total_comp) ~ ROA + log(assets) + CEO_tenure + firm FE + year FE
   Tests whether CEO comp moves with firm performance.

2. **Leverage determinants** (Rajan-Zingales style)
       D/A ~ log(assets) + profitability + growth + tangibility + firm FE
   Tests whether larger / more profitable / more tangible firms lever up
   (or down).

3. **Covenant violation → default hazard** (cross-sectional OLS proxy)
       I(defaulted_next_q) ~ covenant_violation_this_q
           + log(cash) + debt/assets + firm FE
   Tests whether covenant breaches predict default.

Outputs regression tables to stdout and saves them to
`outputs/regressions/<spec>.txt`.

Usage:
    python scripts/baseline_regressions.py
    python scripts/baseline_regressions.py --data-dir data --runs run_X run_Y

Dependencies: pandas, statsmodels. Both pip-installable.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure project root is on sys.path so pickle can resolve `src.*` classes
# when unpickling WorldState snapshots.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

try:
    import pandas as pd
    import numpy as np
except ImportError:
    print("pandas + numpy required. `pip install pandas numpy statsmodels`",
          file=sys.stderr)
    sys.exit(1)

try:
    import statsmodels.api as sm
    import statsmodels.formula.api as smf
    HAVE_STATSMODELS = True
except ImportError:
    HAVE_STATSMODELS = False
    print("statsmodels not installed — will fall back to raw correlations.",
          file=sys.stderr)


def _load_panel(data_dir: Path, runs: list[str] | None = None) -> pd.DataFrame:
    """Load cross-run quarterly panel, optionally filtered to specific runs.

    Falls back to stitching per-run `compustat_q.csv` files when
    `compustat_all.csv` has schema drift across old runs (earlier schemas
    had fewer columns; pandas c-parser rejects mixed row widths).
    """
    path = data_dir / "compustat_all.csv"
    if not path.exists():
        print(f"No {path} — stitching from outputs/*/compustat_q.csv",
              file=sys.stderr)
        df = _stitch_from_runs(runs)
    else:
        try:
            df = pd.read_csv(path)
        except pd.errors.ParserError:
            print(f"Schema drift in {path} — stitching from per-run files instead.",
                  file=sys.stderr)
            df = _stitch_from_runs(runs)
    if runs:
        df = df[df["run_id"].isin(runs)].copy()
    if df.empty:
        print("Panel is empty after filtering.", file=sys.stderr)
        sys.exit(3)
    # Make composite firm key that respects incarnation
    df["firm_key"] = df["run_id"] + "_" + df["firm_id"] + "_" + df["incarnation"].astype(str)
    return df


def _stitch_from_runs(runs: list[str] | None) -> pd.DataFrame:
    """Concat per-run compustat_q.csv files; tolerates schema drift."""
    output_root = Path("outputs")
    frames = []
    for run_dir in sorted(output_root.iterdir() if output_root.exists() else []):
        if runs and run_dir.name not in runs:
            continue
        panel = run_dir / "compustat_q.csv"
        if not panel.exists():
            continue
        try:
            d = pd.read_csv(panel)
            frames.append(d)
        except Exception:
            continue
    if not frames:
        print("No usable compustat_q.csv files found.", file=sys.stderr)
        sys.exit(4)
    return pd.concat(frames, ignore_index=True, sort=False)


def _load_execucomp(data_dir: Path) -> pd.DataFrame | None:
    """ExecuComp annual panel, aggregated across runs by reading each run folder."""
    output_root = Path("outputs")
    rows = []
    if not output_root.exists():
        return None
    for run_dir in output_root.iterdir():
        exe = run_dir / "execucomp.csv"
        if exe.exists():
            try:
                d = pd.read_csv(exe)
                if "run_id" not in d.columns:
                    d["run_id"] = run_dir.name
                rows.append(d)
            except Exception:
                continue
    if not rows:
        return None
    return pd.concat(rows, ignore_index=True)


def _load_covenant_violations() -> pd.DataFrame | None:
    output_root = Path("outputs")
    rows = []
    for run_dir in output_root.iterdir() if output_root.exists() else []:
        cv = run_dir / "covenant_violations.csv"
        if cv.exists():
            try:
                d = pd.read_csv(cv)
                rows.append(d)
            except Exception:
                continue
    if not rows:
        return None
    return pd.concat(rows, ignore_index=True)


def _ols(df: pd.DataFrame, formula: str, cluster_col: str | None = None,
         label: str = "") -> str:
    """Run OLS with optional clustered SEs. Returns a printable summary."""
    if not HAVE_STATSMODELS:
        return f"[no statsmodels — skipping {label}]"
    try:
        model = smf.ols(formula, data=df).fit(
            cov_type="cluster",
            cov_kwds={"groups": df[cluster_col]} if cluster_col else None,
        )
        return model.summary().as_text()
    except Exception as e:
        return f"[{label} FAILED: {e}]"


# ── Spec 1: Pay-performance ──

def spec_pay_performance(data_dir: Path) -> str:
    """log(total_comp) ~ ROA + log(at) + tenure."""
    exe = _load_execucomp(data_dir)
    if exe is None or exe.empty:
        return "Pay-performance: no execucomp data."
    # Merge with annual Compustat for ROA + assets. Fall back to stitching
    # per-run compustat_a.csv on schema drift.
    ann_path = data_dir / "compustat_a_all.csv"
    ann = None
    if ann_path.exists():
        try:
            ann = pd.read_csv(ann_path)
        except pd.errors.ParserError:
            ann = None
    if ann is None:
        frames = []
        for run_dir in Path("outputs").iterdir() if Path("outputs").exists() else []:
            p = run_dir / "compustat_a.csv"
            if p.exists():
                try:
                    frames.append(pd.read_csv(p))
                except Exception:
                    continue
        if not frames:
            return "Pay-performance: no annual Compustat data."
        ann = pd.concat(frames, ignore_index=True, sort=False)
    m = exe.merge(
        ann[["run_id", "firm_id", "fyear", "at", "ni"]],
        on=["run_id", "firm_id", "fyear"], how="inner",
    )
    # Coerce numerics — CSV readers occasionally parse as object.
    for col in ["at", "ni", "total_comp", "tenure_years"]:
        if col in m.columns:
            m[col] = pd.to_numeric(m[col], errors="coerce")
    m = m[(m["at"] > 0) & (m["total_comp"] > 0)].dropna(
        subset=["at", "ni", "total_comp"]
    ).copy()
    if m.empty:
        return "Pay-performance: no rows after merge/filter."
    m["roa"] = m["ni"] / m["at"]
    m["log_total_comp"] = np.log(m["total_comp"].astype(float))
    m["log_at"] = np.log(m["at"].astype(float))
    formula = "log_total_comp ~ roa + log_at + tenure_years"
    summary = _ols(m, formula, cluster_col="firm_id", label="pay-performance")
    return f"=== Spec 1: Pay-performance ===\n{formula}\nN = {len(m)}\n\n{summary}\n"


# ── Spec 2: Leverage determinants ──

def spec_leverage_determinants(df: pd.DataFrame) -> str:
    """D/A ~ log(at) + profitability + tangibility."""
    # Coerce numerics (CSV stitching can leave object columns).
    for col in ["atq", "dlcq", "dlttq", "niq", "ppentq"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    # Quarterly data → collapse to firm × fyear averages for reasonable cross-section
    g = df[df["atq"] > 0].copy()
    g["leverage"] = (g["dlcq"].fillna(0) + g["dlttq"].fillna(0)) / g["atq"]
    g["profitability"] = g["niq"] / g["atq"]
    g["tangibility"] = g["ppentq"].fillna(0) / g["atq"]
    g["log_at"] = np.log(g["atq"].astype(float))
    annual = (g.groupby(["run_id", "firm_id", "fyearq"])
              [["leverage", "profitability", "tangibility", "log_at"]]
              .mean().reset_index())
    formula = "leverage ~ log_at + profitability + tangibility"
    summary = _ols(annual, formula, cluster_col="firm_id", label="leverage")
    return f"=== Spec 2: Leverage determinants ===\n{formula}\nN = {len(annual)}\n\n{summary}\n"


# ── Spec 3: Covenant violation → default hazard ──

def spec_covenant_default(df: pd.DataFrame) -> str:
    """I(default_next_q) ~ covenant_violation_this_q + controls."""
    cv = _load_covenant_violations()
    if cv is None or cv.empty:
        return "Covenant-default: no covenant_violations.csv data."
    # Sort and create lead default indicator per firm
    df = df.sort_values(["run_id", "firm_id", "fyearq", "fqtr"]).copy()
    df["default_next"] = (df.groupby(["run_id", "firm_id"])["default_flag"]
                           .shift(-1).fillna(0).astype(int))
    # Build a quarter identifier matching the violations table
    # covenant_violations has `violation_quarter` absolute; compustat has fyearq+fqtr.
    # Heuristic: build an absolute quarter on both then merge.
    df["abs_q"] = (df["fyearq"] - df["fyearq"].min()) * 4 + df["fqtr"]
    cv2 = cv[["run_id", "firm_id", "violation_quarter"]].rename(
        columns={"violation_quarter": "abs_q"}
    )
    cv2["cov_violation"] = 1
    m = df.merge(cv2, on=["run_id", "firm_id", "abs_q"], how="left")
    m["cov_violation"] = m["cov_violation"].fillna(0)
    for col in ["atq", "cheq", "dlcq", "dlttq"]:
        if col in m.columns:
            m[col] = pd.to_numeric(m[col], errors="coerce")
    m = m[m["atq"] > 0].copy()
    if m.empty:
        return "Covenant-default: empty after merge."
    m["log_cash"] = np.log(m["cheq"].clip(lower=1).astype(float))
    m["debt_to_assets"] = (m["dlcq"].fillna(0) + m["dlttq"].fillna(0)) / m["atq"]
    formula = "default_next ~ cov_violation + log_cash + debt_to_assets"
    summary = _ols(m, formula, cluster_col="firm_id", label="covenant-default")
    n_viol = int(m["cov_violation"].sum())
    n_def = int(m["default_next"].sum())
    return (f"=== Spec 3: Covenant violation -> default hazard ===\n"
            f"{formula}\nN = {len(m)} | covenant violations in sample: {n_viol} | "
            f"next-Q defaults: {n_def}\n\n{summary}\n")


# ── Spec 4: CEO turnover logit ──

def spec_ceo_turnover(df: pd.DataFrame) -> str:
    """I(fired | retired) ~ ROA + log(at) + tenure + stock return.

    Coefaceho-Kothari-style forced-turnover model: does poor performance
    predict CEO termination?
    """
    turn_frames = []
    for run_dir in Path("outputs").iterdir() if Path("outputs").exists() else []:
        p = run_dir / "ceo_turnover.csv"
        if p.exists():
            try:
                turn_frames.append(pd.read_csv(p))
            except Exception:
                continue
    if not turn_frames:
        return "CEO-turnover: no ceo_turnover.csv data."
    turn = pd.concat(turn_frames, ignore_index=True, sort=False)

    exe_frames = []
    for run_dir in Path("outputs").iterdir() if Path("outputs").exists() else []:
        p = run_dir / "execucomp.csv"
        if p.exists():
            try:
                exe_frames.append(pd.read_csv(p))
            except Exception:
                continue
    if not exe_frames:
        return "CEO-turnover: no execucomp.csv data."
    exe = pd.concat(exe_frames, ignore_index=True, sort=False)

    # Build firm × fyear event indicator (was the CEO fired this year?)
    turn["fyear"] = 2031 + (turn["event_quarter"] - 1) // 4
    turn["forced_out"] = turn["event_type"].isin(["fired", "retired"]).astype(int)
    events = (turn.groupby(["run_id", "firm_id", "fyear"])["forced_out"]
              .max().reset_index())
    m = exe.merge(events, on=["run_id", "firm_id", "fyear"], how="left")
    m["forced_out"] = m["forced_out"].fillna(0).astype(int)

    # ROA + size from annual compustat
    ann_frames = []
    for run_dir in Path("outputs").iterdir() if Path("outputs").exists() else []:
        p = run_dir / "compustat_a.csv"
        if p.exists():
            try:
                ann_frames.append(pd.read_csv(p))
            except Exception:
                continue
    if not ann_frames:
        return "CEO-turnover: no annual Compustat."
    ann = pd.concat(ann_frames, ignore_index=True, sort=False)
    m = m.merge(ann[["run_id", "firm_id", "fyear", "at", "ni", "prcc_f"]],
                 on=["run_id", "firm_id", "fyear"], how="inner")

    for col in ["at", "ni", "prcc_f", "tenure_years", "forced_out"]:
        if col in m.columns:
            m[col] = pd.to_numeric(m[col], errors="coerce")
    m = m[m["at"] > 0].dropna(subset=["at", "ni", "tenure_years"]).copy()
    if m.empty:
        return "CEO-turnover: empty after filter."
    m["roa"] = m["ni"] / m["at"]
    m["log_at"] = np.log(m["at"].astype(float))
    # Stock return: Δ share price over last year (requires prior year)
    m = m.sort_values(["run_id", "firm_id", "fyear"])
    m["prcc_lag"] = m.groupby(["run_id", "firm_id"])["prcc_f"].shift(1)
    m["stock_return"] = (m["prcc_f"] - m["prcc_lag"]) / m["prcc_lag"].replace(0, np.nan)
    m["stock_return"] = m["stock_return"].fillna(0)

    formula = "forced_out ~ roa + log_at + tenure_years + stock_return"
    summary = _ols(m, formula, cluster_col="firm_id", label="ceo-turnover")
    return (f"=== Spec 4: CEO forced turnover (fired|retired) ===\n"
            f"{formula}\nN = {len(m)} | forced_out events = "
            f"{int(m['forced_out'].sum())}\n\n{summary}\n")


# ── Spec 5: Earnings management → SEC investigation ──

def spec_earnings_management(df: pd.DataFrame) -> str:
    """I(SEC investigation next quarter) ~ |manipulation_amount| + controls.

    Does reporting aggressive accruals actually predict regulatory scrutiny
    in the simulated world? Critical for validating the SEC agent's signal.
    """
    if "manipulation_amount" not in df.columns:
        return "Earnings-mgmt: no manipulation_amount column."

    df = df.sort_values(["run_id", "firm_id", "fyearq", "fqtr"]).copy()
    for col in ["manipulation_amount", "niq", "saleq", "atq"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Read SEC investigation log if available (alternative: use restatements)
    inv_frames = []
    for run_dir in Path("outputs").iterdir() if Path("outputs").exists() else []:
        p = run_dir / "restatements.csv"
        if p.exists():
            try:
                inv_frames.append(pd.read_csv(p))
            except Exception:
                continue
    if not inv_frames:
        return "Earnings-mgmt: no restatements.csv (proxy for SEC action)."
    inv = pd.concat(inv_frames, ignore_index=True, sort=False)
    if "announcement_q" not in inv.columns:
        # Empty restatements dataset — column wasn't emitted.
        return (f"Earnings-mgmt: restatements.csv has no rows. "
                f"0 restatements across {len(inv_frames)} run(s) — "
                f"specification uninformative at this sample size.")
    inv["fyearq"] = 2031 + (inv["announcement_q"] - 1) // 4
    inv["fqtr"] = ((inv["announcement_q"] - 1) % 4) + 1
    inv["restatement_next"] = 1

    # Lead: will this firm restate in Q+1 or Q+2?
    m = df.merge(
        inv[["run_id", "firm_id", "fyearq", "fqtr", "restatement_next"]],
        on=["run_id", "firm_id", "fyearq", "fqtr"], how="left",
    )
    # Lead: shift restatement indicator back 1 quarter
    m["restatement_next"] = m["restatement_next"].fillna(0)
    m["restatement_lead"] = (m.groupby(["run_id", "firm_id"])["restatement_next"]
                              .shift(-1).fillna(0).astype(int))

    m["abs_manip"] = m["manipulation_amount"].abs()
    m["log_abs_manip"] = np.log1p(m["abs_manip"])
    m = m[m["atq"] > 0].copy()
    if m.empty or m["restatement_lead"].sum() == 0:
        return (f"Earnings-mgmt: N={len(m)}, but zero restatement events "
                f"in next quarter. Specification uninformative.")

    m["log_at"] = np.log(m["atq"].clip(lower=1).astype(float))
    formula = "restatement_lead ~ log_abs_manip + log_at"
    summary = _ols(m, formula, cluster_col="firm_id",
                    label="earnings-mgmt-detection")
    return (f"=== Spec 5: Earnings mgmt predicts next-Q restatement ===\n"
            f"{formula}\nN = {len(m)} | restatement events in sample: "
            f"{int(m['restatement_lead'].sum())}\n\n{summary}\n")


# ── Spec 6: Analyst forecast bias ──

def spec_analyst_bias(data_dir: Path) -> str:
    """forecast_error ~ firm_size + analyst FE.

    Tests whether sell-side analysts systematically over- or under-predict
    EPS. Real world: analysts are slightly optimistic on average.
    """
    frames = []
    for run_dir in Path("outputs").iterdir() if Path("outputs").exists() else []:
        p = run_dir / "analyst_forecasts.csv"
        if p.exists():
            try:
                frames.append(pd.read_csv(p))
            except Exception:
                continue
    if not frames:
        return "Analyst-bias: no analyst_forecasts.csv."
    af = pd.concat(frames, ignore_index=True, sort=False)
    for col in ["eps_forecast", "actual_eps", "forecast_error", "target_price"]:
        if col in af.columns:
            af[col] = pd.to_numeric(af[col], errors="coerce")
    af = af.dropna(subset=["forecast_error"]).copy()
    if af.empty:
        return "Analyst-bias: no realized forecasts (no actual_eps filled yet)."

    # Mean + t-test of forecast error = 0 (is bias significant?)
    mean_err = af["forecast_error"].mean()
    sd_err = af["forecast_error"].std()
    n = len(af)
    t_stat = mean_err / (sd_err / np.sqrt(n)) if sd_err > 0 else 0

    # Regression: error ~ log_at (do analysts mis-predict larger firms more?)
    ann_frames = []
    for run_dir in Path("outputs").iterdir() if Path("outputs").exists() else []:
        p = run_dir / "compustat_q.csv"
        if p.exists():
            try:
                ann_frames.append(pd.read_csv(p))
            except Exception:
                continue
    if not ann_frames:
        summary = "[no compustat for size controls]"
    else:
        comp = pd.concat(ann_frames, ignore_index=True, sort=False)
        comp["atq"] = pd.to_numeric(comp["atq"], errors="coerce")
        comp["forecast_q"] = comp["fyearq"].astype(str).str.strip()
        af["quarter"] = pd.to_numeric(af.get("quarter"), errors="coerce")
        comp["abs_q"] = (comp["fyearq"] - comp["fyearq"].min()) * 4 + comp["fqtr"]
        m = af.merge(comp[["run_id", "firm_id", "abs_q", "atq"]]
                      .rename(columns={"abs_q": "quarter"}),
                      on=["run_id", "firm_id", "quarter"], how="left")
        m = m.dropna(subset=["atq", "forecast_error"])
        m = m[m["atq"] > 0]
        if m.empty:
            summary = "[no merged rows for size regression]"
        else:
            m["log_at"] = np.log(m["atq"].astype(float))
            formula = "forecast_error ~ log_at + C(analyst_id)"
            summary = _ols(m, formula, cluster_col="firm_id",
                            label="analyst-bias")
    return (f"=== Spec 6: Analyst forecast bias ===\n"
            f"N = {n} realized forecasts\n"
            f"Mean forecast error: {mean_err:+.4f} "
            f"(s.d. {sd_err:.4f}, t = {t_stat:+.2f})\n"
            f"  positive = optimistic bias, negative = pessimistic\n"
            f"Per-analyst mean errors:\n"
            + af.groupby("analyst_id")["forecast_error"].mean()
                .round(4).to_string() + "\n\n"
            + summary + "\n")


# ── Spec 7: Event study — equity-price drift around SEC investigation ──

def spec_event_study_sec(df: pd.DataFrame) -> str:
    """Price-level window around SEC investigation announcements.

    For each firm that had an SEC investigation action, compare the
    firm's equity price in the quarter of announcement vs the prior
    quarter. Reports mean price change and the raw data.

    Not a classic CAR (no market-adjusted return since we don't have
    per-firm beta); this is a simplified event-time drift view.
    """
    # Find SEC actions from proposals.jsonl
    import json
    events = []
    for run_dir in Path("outputs").iterdir() if Path("outputs").exists() else []:
        p = run_dir / "proposals.jsonl"
        if not p.exists():
            continue
        try:
            for line in p.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                rec = json.loads(line)
                if rec.get("actor_id") == "sec" and rec.get("action_type", "").startswith("sec_"):
                    events.append({
                        "run_id": rec.get("proposal_id", "")[:0] or run_dir.name,
                        "firm_id": (rec.get("payload") or {}).get("target_firm", ""),
                        "event_quarter": rec.get("quarter", 0),
                        "action_type": rec.get("action_type", ""),
                    })
        except Exception:
            continue
    if not events:
        return "Event-study SEC: no SEC actions logged in proposals.jsonl."

    ev_df = pd.DataFrame(events)
    # Merge with panel on (run_id, firm_id) to get equity prices pre/post
    for col in ["prccq", "atq"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.sort_values(["run_id", "firm_id", "fyearq", "fqtr"]).copy()
    df["abs_q"] = (df["fyearq"] - df["fyearq"].min()) * 4 + df["fqtr"]
    # For each event, find price at abs_q - 1 and abs_q
    results = []
    for _, ev in ev_df.iterrows():
        sub = df[(df["run_id"] == ev["run_id"]) & (df["firm_id"] == ev["firm_id"])]
        if sub.empty:
            continue
        before = sub[sub["abs_q"] == ev["event_quarter"] - 1]
        at = sub[sub["abs_q"] == ev["event_quarter"]]
        if before.empty or at.empty:
            continue
        p_before = float(before["prccq"].iloc[0])
        p_at = float(at["prccq"].iloc[0])
        if p_before > 0:
            pct = (p_at - p_before) / p_before
            results.append({
                "firm": ev["firm_id"], "q": ev["event_quarter"],
                "action": ev["action_type"],
                "p_before": p_before, "p_at": p_at, "pct_change": pct,
            })
    if not results:
        return "Event-study SEC: no usable price pairs."
    res_df = pd.DataFrame(results)
    mean_pct = res_df["pct_change"].mean()
    n = len(res_df)
    sd = res_df["pct_change"].std()
    t_stat = (mean_pct / (sd / np.sqrt(n))) if (n > 1 and sd > 0) else 0
    return (f"=== Spec 7: Event-study price drift around SEC actions ===\n"
            f"N = {n} SEC events with usable pre/post prices\n"
            f"Mean 1-quarter price change: {mean_pct:+.4%}\n"
            f"  (sd {sd:.4%}, t={t_stat:+.2f})\n"
            f"  negative = SEC action associated with price decline\n\n"
            + res_df.groupby("action")["pct_change"].describe().to_string()
            + "\n")


# ── Spec 8: Event study — returns around restatements ──

def spec_event_study_restatement(df: pd.DataFrame) -> str:
    """Price drift around restatement announcements."""
    frames = []
    for run_dir in Path("outputs").iterdir() if Path("outputs").exists() else []:
        p = run_dir / "restatements.csv"
        if p.exists():
            try:
                frames.append(pd.read_csv(p))
            except Exception:
                continue
    if not frames:
        return "Event-study restatement: no restatements.csv."
    rest = pd.concat(frames, ignore_index=True, sort=False)
    if rest.empty or "announcement_quarter" not in rest.columns:
        return "Event-study restatement: empty / missing columns."

    for col in ["prccq"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.sort_values(["run_id", "firm_id", "fyearq", "fqtr"]).copy()
    df["abs_q"] = (df["fyearq"] - df["fyearq"].min()) * 4 + df["fqtr"]

    results = []
    for _, ev in rest.iterrows():
        sub = df[(df["run_id"] == ev["run_id"])
                 & (df["firm_id"] == ev["firm_id"])]
        if sub.empty:
            continue
        q = int(ev.get("announcement_quarter", 0))
        before = sub[sub["abs_q"] == q - 1]
        at = sub[sub["abs_q"] == q]
        after = sub[sub["abs_q"] == q + 1]
        rec = {"firm": ev["firm_id"], "q": q}
        if not before.empty and not at.empty:
            p0 = float(before["prccq"].iloc[0]); p1 = float(at["prccq"].iloc[0])
            if p0 > 0:
                rec["pct_at"] = (p1 - p0) / p0
        if not at.empty and not after.empty:
            p1 = float(at["prccq"].iloc[0]); p2 = float(after["prccq"].iloc[0])
            if p1 > 0:
                rec["pct_after"] = (p2 - p1) / p1
        results.append(rec)
    if not results:
        return "Event-study restatement: no usable price windows."
    res_df = pd.DataFrame(results)
    lines = [f"=== Spec 8: Event-study — restatement announcements ===",
             f"N = {len(res_df)} restatement events"]
    for col in ["pct_at", "pct_after"]:
        if col in res_df.columns and res_df[col].notna().any():
            s = res_df[col].dropna()
            lines.append(
                f"  {col:10s}  n={len(s):4d}  mean={s.mean():+.4%}  "
                f"sd={s.std():.4%}"
            )
    return "\n".join(lines) + "\n"


# ── Spec 9: Event study — returns around CEO turnover ──

def spec_event_study_turnover(df: pd.DataFrame) -> str:
    """Price drift in the quarter of CEO turnover."""
    frames = []
    for run_dir in Path("outputs").iterdir() if Path("outputs").exists() else []:
        p = run_dir / "ceo_turnover.csv"
        if p.exists():
            try:
                frames.append(pd.read_csv(p))
            except Exception:
                continue
    if not frames:
        return "Event-study turnover: no ceo_turnover.csv."
    turn = pd.concat(frames, ignore_index=True, sort=False)

    for col in ["prccq"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.sort_values(["run_id", "firm_id", "fyearq", "fqtr"]).copy()
    df["abs_q"] = (df["fyearq"] - df["fyearq"].min()) * 4 + df["fqtr"]

    results = []
    for _, ev in turn.iterrows():
        sub = df[(df["run_id"] == ev["run_id"])
                 & (df["firm_id"] == ev["firm_id"])]
        if sub.empty:
            continue
        q = int(ev.get("event_quarter", 0))
        before = sub[sub["abs_q"] == q - 1]
        at = sub[sub["abs_q"] == q]
        if before.empty or at.empty:
            continue
        p0 = float(before["prccq"].iloc[0]); p1 = float(at["prccq"].iloc[0])
        if p0 > 0:
            results.append({
                "event_type": ev.get("event_type", ""),
                "pct_change": (p1 - p0) / p0,
            })
    if not results:
        return "Event-study turnover: no usable price pairs."
    res_df = pd.DataFrame(results)
    lines = [f"=== Spec 9: Event-study price drift around CEO turnover ==="]
    # Group by event_type
    for et, sub in res_df.groupby("event_type"):
        s = sub["pct_change"]
        t = (s.mean() / (s.std() / np.sqrt(len(s))) if len(s) > 1 and s.std() > 0 else 0)
        lines.append(
            f"  {et:12s}  n={len(s):3d}  mean={s.mean():+.4%}  "
            f"sd={s.std():.4%}  t={t:+.2f}"
        )
    return "\n".join(lines) + "\n"


def spec_matched_firm_pricing(df: pd.DataFrame) -> str:
    """Test for systematic biases in the equity market's pricing.

    For each firm-quarter, compute a peer-matched 'benchmark' price using
    firms with similar size (log(assets)) and leverage (D/A) in the same
    quarter. Regress the pricing gap (firm's prccq − peer-matched median)
    on firm characteristics to surface systematic over/under-pricing
    drivers (e.g., growth, R&D intensity).
    """
    if df.empty or "prccq" not in df.columns or "atq" not in df.columns:
        return "=== Spec 10: Matched-firm pricing — insufficient data ==="
    d = df.copy()
    for c in ["prccq", "atq", "ltq", "saleq", "xrdq", "niq"]:
        if c in d.columns:
            d[c] = pd.to_numeric(d[c], errors="coerce")
    d = d.dropna(subset=["prccq", "atq", "ltq"])
    d = d[d["atq"] > 0]
    d["log_at"] = np.log(d["atq"])
    d["lev"] = d["ltq"] / d["atq"]
    d["rd_int"] = (d["xrdq"].fillna(0) / d["saleq"].replace(0, np.nan)).clip(0, 5)
    d["roa"] = (d["niq"].fillna(0) / d["atq"]).clip(-1, 1)

    # Peer-match by quarter: median prccq among firms with similar (log_at, lev)
    # using coarse buckets. Simple but surfaces structural biases.
    d["size_bucket"] = pd.qcut(d["log_at"], q=3, labels=False, duplicates="drop")
    d["lev_bucket"] = pd.qcut(d["lev"], q=3, labels=False, duplicates="drop")
    d["peer_median"] = d.groupby(
        ["run_id", "fyearq", "fqtr", "size_bucket", "lev_bucket"]
    )["prccq"].transform("median")
    d["pricing_gap"] = (d["prccq"] - d["peer_median"]) / d["peer_median"].replace(0, np.nan)
    d = d.dropna(subset=["pricing_gap"])
    if len(d) < 20:
        return "=== Spec 10: Matched-firm pricing — sample too small ==="
    lines = [
        "=== Spec 10: Matched-firm pricing (gap vs size×leverage peers) ===",
        f"pricing_gap ~ log_at + lev + rd_int + roa",
        f"N = {len(d)} firm-quarters",
        f"Mean gap: {d['pricing_gap'].mean():+.3f}  "
        f"(sd {d['pricing_gap'].std():.3f})",
    ]
    model_out = _ols(d.dropna(subset=["log_at", "lev", "rd_int", "roa"]),
                     "pricing_gap ~ log_at + lev + rd_int + roa",
                     cluster_col="firm_id")
    lines.append(model_out)
    return "\n".join(lines) + "\n"


def spec_disclosure_tone(df: pd.DataFrame) -> str:
    """Annual-report tone → next-year return.

    Extract a simple positive-minus-negative word count from each firm's
    annual report `mda_summary`. Regress the next-year equity return
    on this tone score + controls. Tests whether LLM-authored disclosure
    tone is informative about future performance.
    """
    # Load annual_reports per run
    frames = []
    for rd in Path("outputs").glob("run_*") if Path("outputs").exists() else []:
        p = rd / "annual_reports.csv"
        if p.exists():
            try:
                frames.append(pd.read_csv(p))
            except Exception:
                continue
    if not frames:
        return "=== Spec 11: Disclosure tone — no annual_reports.csv ==="
    ar = pd.concat(frames, ignore_index=True, sort=False)
    if "mda_summary" not in ar.columns or ar["mda_summary"].isna().all():
        return "=== Spec 11: Disclosure tone — no mda_summary text ==="

    # Small Loughran-McDonald-style keyword lists (literature-standard)
    POS = {"growth", "strong", "gain", "profit", "exceeded", "positive",
           "opportunity", "improvement", "successful", "confident", "robust"}
    NEG = {"decline", "weak", "loss", "risk", "challenge", "uncertain",
           "adverse", "shortfall", "disappointing", "default", "impairment",
           "restructuring", "deterioration", "concern"}

    def tone(text: str) -> float:
        if not isinstance(text, str) or not text.strip():
            return 0.0
        words = text.lower().split()
        if not words:
            return 0.0
        p = sum(1 for w in words if w.strip(".,:;!?\"'()[]") in POS)
        n = sum(1 for w in words if w.strip(".,:;!?\"'()[]") in NEG)
        return (p - n) / len(words) * 100  # net-positive word share × 100

    ar["tone"] = ar["mda_summary"].apply(tone)

    # Merge: for each annual report row (firm × fyear), get next-year return
    # (price change from fyear Q4 to fyear+1 Q4).
    if "prccq" not in df.columns:
        return "=== Spec 11: Disclosure tone — no prccq in panel ==="
    d = df.copy()
    d["prccq"] = pd.to_numeric(d["prccq"], errors="coerce")
    q4_prices = d[d["fqtr"] == 4][["run_id", "firm_id", "fyearq", "prccq"]].copy()
    q4_prices = q4_prices.rename(columns={"prccq": "price_yearend"})
    merged = ar.merge(q4_prices, left_on=["run_id", "firm_id", "fyear"],
                       right_on=["run_id", "firm_id", "fyearq"], how="left")
    # Get next-year price
    q4_next = q4_prices.rename(columns={
        "price_yearend": "price_next",
        "fyearq": "fyear_next"
    })
    q4_next["fyear_link"] = q4_next["fyear_next"] - 1
    merged = merged.merge(q4_next[["run_id", "firm_id", "fyear_link", "price_next"]],
                           left_on=["run_id", "firm_id", "fyear"],
                           right_on=["run_id", "firm_id", "fyear_link"],
                           how="left")
    merged = merged.dropna(subset=["price_yearend", "price_next"])
    merged = merged[merged["price_yearend"] > 0]
    if merged.empty:
        return "=== Spec 11: Disclosure tone — no linked price pairs ==="
    merged["nextyear_return"] = (merged["price_next"] / merged["price_yearend"]) - 1
    merged = merged.dropna(subset=["tone", "nextyear_return"])
    if len(merged) < 15:
        return (f"=== Spec 11: Disclosure tone - only {len(merged)} obs "
                f"(need >=15); skipping regression ===")

    lines = [
        "=== Spec 11: Disclosure-tone → next-year return ===",
        "nextyear_return ~ tone",
        f"N = {len(merged)} annual-report × return pairs",
        f"Mean tone: {merged['tone'].mean():+.3f} (net pos-word share × 100)",
        f"Mean next-year return: {merged['nextyear_return'].mean():+.3%}",
    ]
    lines.append(_ols(merged, "nextyear_return ~ tone",
                       cluster_col="firm_id"))
    return "\n".join(lines) + "\n"


def spec_interlock_belief_accuracy(runs: list[str] | None) -> str:
    """Interlocking-director info leak → observation accuracy.

    Prefers `peer_observations.jsonl` (per-observation log with interlock
    count AT OBSERVATION TIME — clean for causal identification). Falls
    back to snapshot-derived beliefs for older runs.

    Hypothesis (Wave θ): more shared directors → lower observation error,
    because interlocked observations have noise SD divided by (1+n_shared).
    """
    import json as _json
    import pickle
    from pathlib import Path as _P

    out_dir = _P("outputs")
    if not out_dir.exists():
        return "=== Spec 12: Interlock -> belief accuracy - no outputs/ ==="
    candidates = sorted(out_dir.glob("run_*"))
    if runs:
        candidates = [c for c in candidates if c.name in runs]
    rows = []
    data_source = None  # "observation_log" | "snapshot_belief"

    # PRIMARY SOURCE: peer_observations.jsonl (direct observations)
    for run_dir in candidates:
        obs_path = run_dir / "peer_observations.jsonl"
        if not obs_path.exists():
            continue
        data_source = "observation_log"
        for line in obs_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                r = _json.loads(line)
            except Exception:
                continue
            true_rev = r.get("true_revenue", 0) or 0
            obs_rev = r.get("observed_revenue", 0) or 0
            if true_rev <= 0:
                continue
            rows.append({
                "run_id": run_dir.name,
                "quarter": r.get("quarter", 0),
                "observer": r.get("observer", ""),
                "observed": r.get("observed", ""),
                "rel_err": abs(obs_rev - true_rev) / true_rev,
                "n_shared_directors": r.get("n_shared_directors", 0),
                "noise_sd_applied": r.get("noise_sd_applied", 0.0),
                "true_rev": true_rev,
                "belief_rev": obs_rev,
            })

    # FALLBACK: snapshot-derived (for runs without observation log)
    if not rows:
        for run_dir in candidates:
            snap_dir = run_dir / "snapshots"
            if not snap_dir.exists():
                continue
            for snap_path in sorted(snap_dir.glob("Q*.pkl")):
                try:
                    with open(snap_path, "rb") as f:
                        obj = pickle.load(f)
                except Exception:
                    continue
                if isinstance(obj, dict):
                    state = obj.get("world_state") or obj.get("state")
                else:
                    state = obj
                if state is None or not getattr(state, "firm_beliefs", None) \
                        or not getattr(state, "directors", None):
                    continue
                for obs_fid, belief in state.firm_beliefs.items():
                    for peer_fid, belief_rev in belief.estimated_peer_revenue.items():
                        peer_flows = state.last_quarter_flows.get(peer_fid)
                        if peer_flows is None or peer_flows.net_sales <= 0:
                            continue
                        true_rev = peer_flows.net_sales
                        n_shared = sum(
                            1 for d in state.directors.values()
                            if obs_fid in d.seats and peer_fid in d.seats
                        )
                        rows.append({
                            "run_id": state.run_id,
                            "quarter": state.quarter,
                            "observer": obs_fid, "observed": peer_fid,
                            "rel_err": abs(belief_rev - true_rev) / true_rev,
                            "n_shared_directors": n_shared,
                            "noise_sd_applied": None,
                            "true_rev": true_rev, "belief_rev": belief_rev,
                        })
        if rows:
            data_source = "snapshot_belief (EWMA-smoothed)"

    if not rows:
        return ("=== Spec 12: Interlock -> belief accuracy - "
                "no snapshots with firm_beliefs + directors found ===")
    d = pd.DataFrame(rows)
    lines = [
        "=== Spec 12: Interlock -> observation accuracy ===",
        "Hypothesis: shared directors reduce observation noise -> lower |err|.",
        f"Data source: {data_source}",
        f"N = {len(d)} (observer, observed, quarter) triples "
        f"across {d['run_id'].nunique()} run(s)",
        "",
        "Mean |rel_err| by interlock count:",
    ]
    grp = d.groupby("n_shared_directors")["rel_err"].agg(
        ["count", "mean", "std"]
    )
    for n, row in grp.iterrows():
        lines.append(
            f"  n_shared={n}: N={int(row['count']):3d}  "
            f"mean_err={row['mean']:.3%}  sd={row['std']:.3%}"
        )
    lines.append("")
    if len(d) < 10 or d["n_shared_directors"].nunique() < 2:
        lines.append("(insufficient variation in n_shared_directors for regression)")
        return "\n".join(lines) + "\n"
    # log(true_rev) as size control; fixed effects via firm dummy if desired
    d["log_true_rev"] = np.log(d["true_rev"].clip(lower=1.0))
    lines.append(_ols(d, "rel_err ~ n_shared_directors + log_true_rev",
                        cluster_col="observer"))
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="data",
                    help="Cross-run data directory (default: data/)")
    ap.add_argument("--runs", nargs="*",
                    help="Filter to specific run_ids (default: all)")
    ap.add_argument("--output-dir", default="outputs/regressions",
                    help="Where to write text summaries")
    args = ap.parse_args()

    data_dir = Path(args.data_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    df = _load_panel(data_dir, args.runs)
    print(f"Loaded panel: {len(df)} rows, {df['run_id'].nunique()} run(s), "
          f"{df['firm_key'].nunique()} firm-incarnations.\n")

    for spec_name, fn, args_ in [
        ("pay_performance", spec_pay_performance, (data_dir,)),
        ("leverage_determinants", spec_leverage_determinants, (df,)),
        ("covenant_default", spec_covenant_default, (df,)),
        ("ceo_turnover_logit", spec_ceo_turnover, (df,)),
        ("earnings_mgmt_detection", spec_earnings_management, (df,)),
        ("analyst_bias", spec_analyst_bias, (data_dir,)),
        ("event_study_sec", spec_event_study_sec, (df,)),
        ("event_study_restatement", spec_event_study_restatement, (df,)),
        ("event_study_turnover", spec_event_study_turnover, (df,)),
        ("matched_firm_pricing", spec_matched_firm_pricing, (df,)),
        ("disclosure_tone", spec_disclosure_tone, (df,)),
        ("interlock_belief_accuracy", spec_interlock_belief_accuracy,
         (args.runs,)),
    ]:
        out = fn(*args_)
        print(out)
        print()
        (output_dir / f"{spec_name}.txt").write_text(out)

    print(f"\nWrote summaries to {output_dir}/")


if __name__ == "__main__":
    main()
