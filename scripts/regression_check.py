"""Wave ν+10 item 16: deterministic regression check.

Runs a fixed-seed mock simulation, fingerprints the output (compustat
panel digest + final firm states + selected event counts), and either:

  * `--update`: writes the fingerprint to a golden file, OR
  * default: compares against the golden file and fails on drift.

The intent: catch silent semantic drift between waves. A code change
that legitimately alters behaviour requires explicit `--update` to
re-bless the fingerprint; an unintended drift produces a visible,
diff-able failure with the offending fields named.

Mock smoke runs the simulation entirely against the mock backend
(deterministic JSON responses per agent class), so the fingerprint is
reproducible across machines and across LLM-provider weight updates.

Usage:
    python -m scripts.regression_check                # check
    python -m scripts.regression_check --update       # bless current

Exit code 0 = match (or update succeeded); 1 = drift detected.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

# Ensure the repo root is on sys.path so pickled snapshots that reference
# `src.types.FirmState` etc. can deserialize.
_repo_root = Path(__file__).parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

GOLDEN_PATH = Path(__file__).parent.parent / "tests" / "regression_golden.json"
MOCK_QUARTERS = 8
MOCK_SEED = 4242


def _stable_digest(d: dict) -> str:
    """Deterministic hash of a dict — sorts keys, JSON-encodes, sha256s.
    Catches any reordering or value drift without false positives from
    dict iteration order."""
    payload = json.dumps(d, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def fingerprint_run(out_dir: Path) -> dict:
    """Read the run's outputs and produce a fingerprint dict. Each value
    is either a small scalar or a 16-char digest of a larger payload.

    Layout:
      {
        "n_compustat_rows": int,
        "compustat_digest": "<16-char hex>",
        "final_firm_states_digest": "<16-char hex>",
        "n_defaults": int,
        "n_chapter_11": int,
        "n_chapter_7": int,
        "events_digest": "<16-char hex>",
      }
    """
    fp: dict = {}

    # Compustat panel digest (revenue, NI, cash, total assets per row)
    comp_csv = out_dir / "compustat_q.csv"
    if comp_csv.exists():
        import csv
        rows = []
        with open(comp_csv, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                rows.append({
                    "fid": r["firm_id"],
                    "fy": r["fyearq"],
                    "fq": r["fqtr"],
                    "saleq": round(float(r.get("saleq", 0) or 0), 2),
                    "niq": round(float(r.get("niq", 0) or 0), 2),
                    "cheq": round(float(r.get("cheq", 0) or 0), 2),
                    "atq": round(float(r.get("atq", 0) or 0), 2),
                })
        fp["n_compustat_rows"] = len(rows)
        fp["compustat_digest"] = _stable_digest({"rows": rows})

    # Final firm states from latest snapshot
    snap_dir = out_dir / "snapshots"
    if snap_dir.exists():
        import re
        import pickle
        snaps = sorted(
            snap_dir.glob("Q*.pkl"),
            key=lambda p: int(re.match(r"Q(\d+)\.pkl", p.name).group(1)),
        )
        if snaps:
            with open(snaps[-1], "rb") as f:
                snap = pickle.load(f)
            ws = snap["world_state"]
            firm_states = {}
            n_default_total = 0
            n_ch11 = 0
            n_ch7 = 0
            for fid, fst in sorted(ws.firms.items()):
                dtype = getattr(fst, "default_type", "")
                firm_states[fid] = {
                    "active": fst.is_active,
                    "default_type": dtype,
                    "cap": round(float(fst.capability_stock), 2),
                    "brand": round(float(fst.brand_stock), 2),
                    "cash": round(float(fst.cash), 2),
                    "ltd": round(float(fst.long_term_debt), 2),
                    "qics": getattr(fst, "quarters_in_chapter_11", 0),
                }
                if not fst.is_active and dtype != "chapter_11":
                    n_default_total += 1
                if dtype == "chapter_11":
                    n_ch11 += 1
                if dtype == "chapter_7":
                    n_ch7 += 1
            fp["final_firm_states_digest"] = _stable_digest(firm_states)
            fp["n_defaults"] = n_default_total
            fp["n_chapter_11"] = n_ch11
            fp["n_chapter_7"] = n_ch7

    # Events digest from gazettes
    gazettes_path = out_dir / "gazettes.txt"
    if gazettes_path.exists():
        with open(gazettes_path, encoding="utf-8") as f:
            text = f.read()
        # Just length and digest — full text would be too noisy
        fp["gazettes_len"] = len(text)
        fp["events_digest"] = _stable_digest({"len": len(text),
                                                "h": hashlib.sha256(text.encode()).hexdigest()[:32]})

    return fp


def run_mock_sim(quarters: int, seed: int, out_root: Path) -> Path:
    """Invoke the simulation in mock mode and return the run output dir."""
    import subprocess
    cmd = [sys.executable, "-m", "src", "smoke",
           "--quarters", str(quarters), "--seed", str(seed)]
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    result = subprocess.run(cmd, capture_output=True, text=True,
                              env=env, cwd=str(out_root.parent))
    if result.returncode != 0:
        print("SIM STDOUT:", result.stdout[-2000:])
        print("SIM STDERR:", result.stderr[-2000:])
        raise SystemExit("Mock simulation failed; cannot regression-check.")

    # Find the most recently created run directory.
    runs = sorted(out_root.glob("run_*"), key=lambda p: p.stat().st_mtime)
    if not runs:
        raise SystemExit(f"No run output found in {out_root}")
    return runs[-1]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--update", action="store_true",
                    help="Update the golden fingerprint to match current run.")
    ap.add_argument("--quarters", type=int, default=MOCK_QUARTERS)
    ap.add_argument("--seed", type=int, default=MOCK_SEED)
    args = ap.parse_args()

    repo_root = Path(__file__).parent.parent
    out_root = repo_root / "outputs"

    print(f"[regression] running mock sim "
          f"({args.quarters} quarters, seed={args.seed})...")
    run_dir = run_mock_sim(args.quarters, args.seed, out_root)
    print(f"[regression] run output: {run_dir}")

    fp = fingerprint_run(run_dir)
    print(f"[regression] fingerprint: {json.dumps(fp, indent=2)}")

    if args.update:
        GOLDEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(GOLDEN_PATH, "w") as f:
            json.dump(fp, f, indent=2, sort_keys=True)
        print(f"[regression] UPDATED golden file at {GOLDEN_PATH}")
        return 0

    if not GOLDEN_PATH.exists():
        print(f"[regression] no golden file at {GOLDEN_PATH}")
        print(f"[regression] run with --update to bless the current run")
        return 1

    with open(GOLDEN_PATH) as f:
        golden = json.load(f)

    diffs = []
    all_keys = set(fp.keys()) | set(golden.keys())
    for k in sorted(all_keys):
        if fp.get(k) != golden.get(k):
            diffs.append(f"  {k}: {golden.get(k)!r} → {fp.get(k)!r}")

    if diffs:
        print("[regression] FAILED — fingerprint drift detected:")
        for d in diffs:
            print(d)
        print("\n[regression] If this drift is intentional, re-bless with:")
        print(f"    python -m scripts.regression_check --update")
        return 1

    print("[regression] OK — no drift.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
