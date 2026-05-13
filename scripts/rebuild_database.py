"""
Rebuild the cross-run database from all past run outputs.

Scans outputs/run_*/ and consolidates the following into data/:
- compustat_all.csv          — firm-quarter panel (as-reported)
- compustat_restated_all.csv — same panel with restated values where applicable
- run_index.csv              — one row per run with summary stats
- execucomp_all.csv          — CEO compensation across runs
- audit_analytics_all.csv    — auditor + opinions across runs
- restatements_all.csv       — restatement events across runs
- analyst_forecasts_all.csv  — sell-side forecasts across runs
- management_forecasts_all.csv — firm-issued guidance across runs
- ceo_turnover_all.csv       — CEO transitions across runs

Run this once to catch up, then the normal run process maintains it.
"""

import csv
import os
from pathlib import Path
from collections import defaultdict

OUTPUTS_DIR = Path("outputs")
DATA_DIR = Path("data")

def rebuild():
    DATA_DIR.mkdir(exist_ok=True)

    all_rows = []
    run_summaries = []
    all_fieldnames = None

    # Scan all run directories
    run_dirs = sorted(OUTPUTS_DIR.glob("run_*"))
    print(f"Found {len(run_dirs)} run directories")

    for run_dir in run_dirs:
        panel_path = run_dir / "compustat_q.csv"
        if not panel_path.exists():
            continue

        try:
            with open(panel_path, encoding="utf-8") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
        except Exception as e:
            print(f"  SKIP {run_dir.name}: {e}")
            continue

        if not rows:
            continue

        if all_fieldnames is None:
            all_fieldnames = list(rows[0].keys())

        # Ensure run_id is set
        run_id = run_dir.name
        for r in rows:
            if not r.get("run_id") or r["run_id"] == "":
                r["run_id"] = run_id

        all_rows.extend(rows)

        # Build run summary
        n_firms = len(set(r.get("firm_id", "") for r in rows))
        n_quarters = len(set((r.get("fyearq", ""), r.get("fqtr", "")) for r in rows))
        total_rev = sum(float(r.get("saleq", 0)) for r in rows)
        n_defaults = sum(1 for r in rows if int(r.get("default_flag", 0)) == 1)

        # Get seed from run_id (timestamp-based, not actual seed)
        run_summaries.append({
            "run_id": run_id,
            "n_firms": n_firms,
            "n_quarters": n_quarters,
            "seed": 0,  # can't recover from output
            "total_industry_revenue": total_rev,
            "n_defaults": n_defaults,
            "final_active_firms": n_firms - n_defaults,
            "compustat_rows": len(rows),
        })

        print(f"  {run_id}: {len(rows)} rows, {n_firms} firms, {n_quarters} quarters, rev=${total_rev/1e6:.0f}M")

    # Write consolidated compustat
    if all_rows and all_fieldnames:
        # Normalize fieldnames across runs (some runs may have different columns)
        final_fieldnames = all_fieldnames
        compustat_path = DATA_DIR / "compustat_all.csv"
        with open(compustat_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=final_fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(all_rows)
        print(f"\nWrote {len(all_rows)} rows to {compustat_path}")

    # Write run index
    if run_summaries:
        index_path = DATA_DIR / "run_index.csv"
        fieldnames = list(run_summaries[0].keys())
        with open(index_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(run_summaries)
        print(f"Wrote {len(run_summaries)} runs to {index_path}")

    # Summary stats
    print(f"\n=== DATABASE SUMMARY ===")
    print(f"Total runs: {len(run_summaries)}")
    print(f"Total firm-quarter rows: {len(all_rows)}")
    n_unique_firms = len(set(r.get("firm_id", "") for r in all_rows))
    print(f"Unique firm IDs: {n_unique_firms}")

    # Revenue distribution
    revs = [float(r.get("saleq", 0)) for r in all_rows if float(r.get("saleq", 0)) > 0]
    if revs:
        print(f"Revenue: avg ${sum(revs)/len(revs)/1e6:.1f}M, min ${min(revs)/1e6:.1f}M, max ${max(revs)/1e6:.1f}M")

    defaults = sum(1 for r in all_rows if int(r.get("default_flag", 0)) == 1)
    print(f"Default events: {defaults} ({defaults/len(all_rows)*100:.1f}%)")

    # ── Consolidate expansion datasets (v0.5) ─────────────────────────────
    expansion_datasets = [
        ("compustat_restated.csv", "compustat_restated_all.csv"),
        ("execucomp.csv",          "execucomp_all.csv"),
        ("audit_analytics.csv",    "audit_analytics_all.csv"),
        ("restatements.csv",       "restatements_all.csv"),
        ("analyst_forecasts.csv",  "analyst_forecasts_all.csv"),
        ("management_forecasts.csv", "management_forecasts_all.csv"),
        ("ceo_turnover.csv",       "ceo_turnover_all.csv"),
    ]

    print(f"\n=== EXPANSION DATASETS (v0.5) ===")
    for per_run_name, combined_name in expansion_datasets:
        total = _consolidate_dataset(run_dirs, per_run_name, combined_name)
        if total > 0:
            print(f"  {combined_name}: {total} rows")

    return len(all_rows)


def _consolidate_dataset(run_dirs: list, per_run_name: str, combined_name: str) -> int:
    """Consolidate a per-run CSV into a combined cross-run CSV.

    Returns the total number of rows written. Skips runs that don't have
    this dataset. Writes header from first non-empty file.
    """
    fieldnames = None
    all_rows = []
    for run_dir in run_dirs:
        path = run_dir / per_run_name
        if not path.exists():
            continue
        try:
            with open(path, encoding="utf-8") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
                if fieldnames is None and reader.fieldnames:
                    fieldnames = list(reader.fieldnames)
            # Stamp run_id if missing
            run_id = run_dir.name
            for r in rows:
                if not r.get("run_id"):
                    r["run_id"] = run_id
            all_rows.extend(rows)
        except Exception as e:
            print(f"  SKIP {run_dir.name}/{per_run_name}: {e}")
            continue

    if not fieldnames:
        return 0  # No runs had this dataset

    out_path = DATA_DIR / combined_name
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(all_rows)
    return len(all_rows)


if __name__ == "__main__":
    rebuild()
