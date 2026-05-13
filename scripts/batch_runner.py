"""
Batch runner: launch N simulation runs with varying seeds in parallel.

Use this to build a research-grade cross-run panel. Output accumulates in
`data/compustat_all.csv` for multi-seed regressions.

Usage:
    python scripts/batch_runner.py --config config/validation_full.yaml \
                                    --seeds 1 2 3 4 5 \
                                    --max-parallel 3
    python scripts/batch_runner.py --config config/test_stage12_mock.yaml \
                                    --seeds 100..110 --mock --max-parallel 5

Output: prints per-run wall-clock + exit code. Failed runs don't block the batch.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import subprocess
import sys
import time
from pathlib import Path


def _parse_seeds(arg: list[str]) -> list[int]:
    """Accept ints or 'A..B' ranges."""
    seeds = []
    for s in arg:
        if ".." in s:
            a, b = s.split("..")
            seeds.extend(range(int(a), int(b) + 1))
        else:
            seeds.append(int(s))
    return seeds


def _run_one(config_path: str, seed: int, use_mock: bool,
             quarters: int | None, output_dir: Path,
             stagger_s: float = 0.0) -> dict:
    # Stagger launches so parallel runs get distinct auto-generated run_ids
    # (based on time.time() at cli.py init).
    if stagger_s > 0:
        time.sleep(stagger_s)
    t0 = time.time()
    log_path = output_dir / f"seed{seed}_{int(t0)}.log"
    cmd = [sys.executable, "-u", "-m", "src", "run",
           "--config", config_path, "--seed", str(seed)]
    if use_mock:
        cmd.append("--mock")
    if quarters:
        cmd.extend(["--quarters", str(quarters)])
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "w") as f:
        proc = subprocess.Popen(cmd, stdout=f, stderr=subprocess.STDOUT)
        rc = proc.wait()
    return {
        "seed": seed,
        "elapsed_s": time.time() - t0,
        "exit_code": rc, "log_path": str(log_path),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True, help="Base config YAML")
    ap.add_argument("--seeds", nargs="+", required=True,
                    help="Seeds: '1 2 3' or '1..10' range")
    ap.add_argument("--max-parallel", type=int, default=3,
                    help="Max concurrent runs (respect API rate limits)")
    ap.add_argument("--mock", action="store_true")
    ap.add_argument("--quarters", type=int, default=None,
                    help="Override quarter count")
    ap.add_argument("--output-dir", default="outputs/batch_logs")
    args = ap.parse_args()

    seeds = _parse_seeds(args.seeds)
    output_dir = Path(args.output_dir)

    print(f"Batch: {len(seeds)} runs, max {args.max_parallel} parallel")
    print(f"  config={args.config} mock={args.mock} quarters={args.quarters}")
    print(f"  seeds={seeds}")
    print()

    t_batch = time.time()
    results = []
    with concurrent.futures.ThreadPoolExecutor(
            max_workers=args.max_parallel) as pool:
        futures = {
            pool.submit(_run_one, args.config, seed, args.mock,
                         args.quarters, output_dir,
                         stagger_s=1.5 * i): seed
            for i, seed in enumerate(seeds)
        }
        for fut in concurrent.futures.as_completed(futures):
            seed = futures[fut]
            try:
                r = fut.result()
                status = "OK" if r["exit_code"] == 0 else f"FAIL({r['exit_code']})"
                print(f"  seed={seed}: {status} in {r['elapsed_s']:.0f}s "
                      f"(log: {r['log_path']})")
                results.append(r)
            except Exception as e:
                print(f"  seed={seed}: CRASHED — {e}")
                results.append({"seed": seed, "exit_code": -1, "error": str(e)})

    elapsed = time.time() - t_batch
    n_ok = sum(1 for r in results if r.get("exit_code") == 0)
    print()
    print(f"Batch complete: {n_ok}/{len(results)} successful in {elapsed:.0f}s "
          f"(= {elapsed/60:.1f} min)")

    # Dump summary
    import json
    summary_path = output_dir / f"batch_summary_{int(t_batch)}.json"
    summary_path.write_text(json.dumps(results, indent=2, default=str))
    print(f"Summary: {summary_path}")


if __name__ == "__main__":
    main()
