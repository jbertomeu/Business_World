"""
Wave ν+2: supervised run with auto-recovery from crashes.

Launches `python -m src run --config <cfg>` in a subprocess. If the
subprocess exits with a non-zero status (crash, OOM kill, signal, etc.),
the supervisor finds the most recent snapshot for that run_id and
re-launches with `--restart-from <snapshot>`. Loops until success or
max attempts reached.

Usage:
    python scripts/supervised_run.py <config_path> <log_path> [max_attempts]

The supervisor itself is a tiny loop with no LLM calls or heavy state
— extremely unlikely to crash. It writes its own status to the log
file so the user can see attempt boundaries.
"""

from __future__ import annotations

import glob
import os
import re
import subprocess
import sys
import time
from pathlib import Path


def find_latest_snapshot(run_id: str) -> str | None:
    """Return path to the highest-quarter snapshot for `run_id`, or None."""
    pattern = f"outputs/{run_id}/snapshots/Q*.pkl"
    snaps = glob.glob(pattern)
    if not snaps:
        return None
    def _q_num(p: str) -> int:
        m = re.match(r"Q(\d+)\.pkl", Path(p).name)
        return int(m.group(1)) if m else -1
    snaps.sort(key=_q_num)
    return snaps[-1]


def extract_run_id_from_log(log_path: str) -> str | None:
    """Read the log to find the `Run ID: run_<n>` line."""
    if not os.path.exists(log_path):
        return None
    with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            if line.startswith("Run ID:"):
                return line.split(":", 1)[1].strip()
    return None


def main():
    if len(sys.argv) < 3:
        print("Usage: python scripts/supervised_run.py <config_path> <log_path> [max_attempts] [initial_restart_from]",
              file=sys.stderr)
        sys.exit(2)
    config_path = sys.argv[1]
    log_path = sys.argv[2]
    max_attempts = int(sys.argv[3]) if len(sys.argv) >= 4 else 8
    # Wave ν+3: optional initial --restart-from. Lets a supervisor be
    # used to CONTINUE an existing run from its latest snapshot (e.g.
    # extending a 16Q run to 80Q without losing accumulated state).
    initial_restart_from = sys.argv[4] if len(sys.argv) >= 5 else None

    run_id: str | None = None
    # If continuation: extract run_id from the snapshot path AND
    # pre-populate restart_from so attempt 1 starts from the snapshot.
    restart_from: str | None = initial_restart_from
    if initial_restart_from:
        # Path looks like outputs/run_<id>/snapshots/Q<n>.pkl
        try:
            parts = Path(initial_restart_from).parts
            for p in parts:
                if p.startswith("run_"):
                    run_id = p
                    break
        except Exception:
            pass
    attempt = 0
    success = False

    while attempt < max_attempts:
        attempt += 1
        cmd = ["python", "-u", "-m", "src", "run", "--config", config_path]
        if restart_from:
            cmd.extend(["--restart-from", restart_from])

        banner = (
            f"\n{'='*70}\n"
            f"[supervisor] attempt {attempt}/{max_attempts} at {time.ctime()}\n"
            f"[supervisor] cmd: {' '.join(cmd)}\n"
            f"[supervisor] restart_from: {restart_from or '(fresh)'}\n"
            f"{'='*70}\n"
        )
        print(banner.rstrip(), flush=True)
        with open(log_path, "a", encoding="utf-8") as logf:
            logf.write(banner)
            logf.flush()
            t0 = time.time()
            proc = subprocess.run(cmd, stdout=logf, stderr=subprocess.STDOUT)
            elapsed = time.time() - t0

        # Discover run_id from log if not yet known
        if run_id is None:
            run_id = extract_run_id_from_log(log_path)

        msg = (
            f"[supervisor] attempt {attempt} exited code={proc.returncode} "
            f"after {elapsed:.0f}s; run_id={run_id}"
        )
        print(msg, flush=True)
        with open(log_path, "a", encoding="utf-8") as logf:
            logf.write(msg + "\n")

        if proc.returncode == 0:
            success = True
            break

        # Crash — try to find latest snapshot for restart
        if run_id is None:
            print("[supervisor] no run_id discovered; can't auto-restart. Aborting.",
                  flush=True)
            break
        latest = find_latest_snapshot(run_id)
        if latest is None:
            print(f"[supervisor] no snapshots found under outputs/{run_id}/snapshots/. "
                  f"Aborting (run died before completing Q1).", flush=True)
            break
        if restart_from == latest:
            # Same snapshot as last attempt = no progress — bail to avoid loop
            print(f"[supervisor] no progress since last restart (snapshot={latest}). "
                  f"Aborting to avoid infinite loop.", flush=True)
            break
        restart_from = latest
        print(f"[supervisor] will restart from {latest} (attempt {attempt+1})",
              flush=True)
        # Brief pause to let any partial output flush
        time.sleep(2)

    final = (
        f"\n[supervisor] final: success={success}, attempts={attempt}, "
        f"run_id={run_id}, time={time.ctime()}\n"
    )
    print(final.rstrip(), flush=True)
    with open(log_path, "a", encoding="utf-8") as logf:
        logf.write(final)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
