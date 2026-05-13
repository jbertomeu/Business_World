"""
Meta-analysis across runs: cross-run summary statistics for research.

Aggregates every run in `outputs/` to answer questions like:
  - How variable are firm outcomes across seeds?
  - Which industries (scenarios) default firms the fastest?
  - How does covenant breach frequency scale with leverage?
  - What's the cross-run mean / median / std of core metrics?

Usage:
    python scripts/meta_analysis.py
    python scripts/meta_analysis.py --runs run_X run_Y
    python scripts/meta_analysis.py --output outputs/meta/summary.txt

Output: `outputs/meta/` directory with summary tables and plots (CSV +
text). Complements `scripts/baseline_regressions.py` which runs specific
empirical specs.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    import pandas as pd
    import numpy as np
except ImportError:
    print("pandas + numpy required.", file=sys.stderr)
    sys.exit(1)


def _load_all_runs(runs_filter: list[str] | None) -> dict:
    """Load the per-run outputs. Returns dict of concatenated DataFrames."""
    out_root = Path("outputs")
    if not out_root.exists():
        return {}
    run_dirs = sorted(
        [d for d in out_root.iterdir()
         if d.is_dir() and d.name.startswith("run_")]
    )
    if runs_filter:
        run_dirs = [d for d in run_dirs if d.name in set(runs_filter)]

    frames: dict = {"compustat": [], "exec": [], "turnover": [],
                     "audit": [], "cov": [], "activist": [],
                     "proposals": [], "negotiations": []}
    for d in run_dirs:
        def try_csv(name, key):
            p = d / name
            if p.exists():
                try:
                    frames[key].append(pd.read_csv(p))
                except Exception:
                    pass
        try_csv("compustat_q.csv", "compustat")
        try_csv("execucomp.csv", "exec")
        try_csv("ceo_turnover.csv", "turnover")
        try_csv("audit_analytics.csv", "audit")
        try_csv("covenant_violations.csv", "cov")
        try_csv("activist_campaigns.csv", "activist")

        # JSONL
        import json
        for name, key in [("proposals.jsonl", "proposals"),
                          ("negotiations.jsonl", "negotiations")]:
            p = d / name
            if p.exists():
                rows = []
                for line in p.read_text(encoding="utf-8").splitlines():
                    if line.strip():
                        try:
                            rows.append(json.loads(line))
                        except Exception:
                            pass
                if rows:
                    frames[key].append(pd.DataFrame(rows))

    return {
        k: (pd.concat(v, ignore_index=True, sort=False)
            if v else pd.DataFrame())
        for k, v in frames.items()
    }


def _summarize_firm_outcomes(comp: pd.DataFrame) -> str:
    """Cross-run firm-outcome stats."""
    if comp.empty:
        return "No compustat_q data.\n"
    out = ["=== Firm outcome distribution (across runs) ==="]
    # Coerce numerics
    for col in ["saleq", "niq", "cheq", "atq", "ltq", "ceqq", "prccq", "default_flag"]:
        if col in comp.columns:
            comp[col] = pd.to_numeric(comp[col], errors="coerce")
    # Final-quarter per (run, firm)
    if "run_id" in comp.columns and "firm_id" in comp.columns:
        comp["abs_q"] = (
            comp["fyearq"].astype(int, errors="ignore") - comp["fyearq"].min()
        ) * 4 + comp["fqtr"].astype(int, errors="ignore")
        final = (comp.sort_values("abs_q")
                 .groupby(["run_id", "firm_id"]).tail(1))
        out.append(f"\nRuns: {comp['run_id'].nunique()}")
        out.append(f"Firm-quarters: {len(comp)}")
        out.append(f"Unique firms: {final.groupby(['run_id','firm_id']).ngroups}")
        if "default_flag" in final.columns:
            out.append(f"\nDefault rate (per firm): "
                       f"{final['default_flag'].mean():.1%}")
        if "niq" in final.columns:
            s = final["niq"].describe()
            out.append(f"\nFinal-period NI across firms:")
            out.append(f"  mean   ${s['mean']:,.0f}")
            out.append(f"  median ${s['50%']:,.0f}")
            out.append(f"  sd     ${s['std']:,.0f}")
            out.append(f"  min    ${s['min']:,.0f}")
            out.append(f"  max    ${s['max']:,.0f}")
    return "\n".join(out) + "\n\n"


def _summarize_events(turnover, cov, activist, proposals, negs) -> str:
    """Cross-run event counts."""
    out = ["=== Event counts (across runs) ==="]
    def n(df):
        return 0 if df.empty else len(df)
    out.append(f"CEO turnover events:      {n(turnover):>6}")
    out.append(f"Covenant violations:      {n(cov):>6}")
    out.append(f"Activist campaigns:       {n(activist):>6}")
    out.append(f"Structured proposals:     {n(proposals):>6}")
    out.append(f"Multi-round negotiations: {n(negs):>6}")

    if not proposals.empty and "actor_id" in proposals.columns:
        out.append("\nProposals by actor class:")
        # Group by actor prefix
        def _cls(a):
            if a.startswith("firm_"):
                return "firm"
            if a.startswith("analyst_"):
                return "analyst"
            if a.startswith("auditor_"):
                return "auditor"
            return a.split("_")[0] if "_" in a else a
        p_by_cls = (proposals.assign(cls=proposals["actor_id"].apply(_cls))
                     .groupby("cls").size().sort_values(ascending=False))
        for cls, cnt in p_by_cls.items():
            out.append(f"  {cls:20s} {cnt:>6}")

    if not negs.empty and "outcome" in negs.columns:
        out.append("\nNegotiation outcomes:")
        for outc, cnt in negs["outcome"].value_counts().items():
            out.append(f"  {outc:25s} {cnt:>6}")
        if "topic" in negs.columns:
            out.append("\nNegotiation topics:")
            for topic, cnt in negs["topic"].value_counts().items():
                out.append(f"  {topic:25s} {cnt:>6}")
    return "\n".join(out) + "\n\n"


def _summarize_ceo_comp(exec_df) -> str:
    if exec_df.empty:
        return "No execucomp data.\n\n"
    out = ["=== CEO compensation across runs ==="]
    for col in ["salary", "bonus", "total_comp", "tenure_years"]:
        if col in exec_df.columns:
            exec_df[col] = pd.to_numeric(exec_df[col], errors="coerce")
    for col in ("salary", "bonus", "total_comp"):
        if col in exec_df.columns:
            s = exec_df[col].dropna().describe()
            if s["count"] > 0:
                out.append(
                    f"{col:12s}  n={int(s['count']):4d}  "
                    f"mean=${s['mean']:,.0f}  median=${s['50%']:,.0f}  "
                    f"sd=${s['std']:,.0f}"
                )
    return "\n".join(out) + "\n\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", nargs="*",
                    help="Filter to specific run_ids")
    ap.add_argument("--output", default="outputs/meta",
                    help="Where to write summary (default: outputs/meta/)")
    args = ap.parse_args()

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    print("Loading runs...", file=sys.stderr)
    data = _load_all_runs(args.runs)

    report = []
    report.append(f"Meta-analysis | {len(data.get('compustat', pd.DataFrame()))} "
                   f"firm-quarters across runs\n")
    report.append(_summarize_firm_outcomes(data.get("compustat", pd.DataFrame())))
    report.append(_summarize_events(
        data.get("turnover", pd.DataFrame()),
        data.get("cov", pd.DataFrame()),
        data.get("activist", pd.DataFrame()),
        data.get("proposals", pd.DataFrame()),
        data.get("negotiations", pd.DataFrame()),
    ))
    report.append(_summarize_ceo_comp(data.get("exec", pd.DataFrame())))

    text = "\n".join(report)
    print(text)
    (out_dir / "summary.txt").write_text(text, encoding="utf-8")
    print(f"\nSaved to {out_dir / 'summary.txt'}", file=sys.stderr)


if __name__ == "__main__":
    main()
