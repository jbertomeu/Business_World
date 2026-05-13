"""
Backfill `actor_class` field into historical proposals.jsonl files.

Wave θ added `actor_class` to new proposals, derived from `actor_id` via
`engine.derive_actor_class`. Existing runs (pre-Wave-θ) lack the field.
This script walks outputs/run_*/proposals.jsonl and rewrites each row
with the derived class in place, non-destructively (writes a .backfilled
marker file alongside).

Usage:
    python scripts/backfill_actor_class.py                 # all runs
    python scripts/backfill_actor_class.py --runs run_X    # specific
    python scripts/backfill_actor_class.py --dry-run       # preview
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.engine import derive_actor_class


def backfill_file(path: Path, dry_run: bool = False) -> tuple[int, int]:
    """Returns (rows_total, rows_updated)."""
    if not path.exists():
        return 0, 0
    rows = []
    updated = 0
    total = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            rows.append(line)
            continue
        total += 1
        try:
            p = json.loads(line)
        except Exception:
            rows.append(line)
            continue
        if "actor_class" not in p and "actor_id" in p:
            p["actor_class"] = derive_actor_class(p["actor_id"])
            updated += 1
        rows.append(json.dumps(p, default=str))

    if updated > 0 and not dry_run:
        # Write backup then overwrite
        backup = path.with_suffix(path.suffix + ".pre_backfill")
        if not backup.exists():
            backup.write_text(path.read_text(encoding="utf-8"),
                               encoding="utf-8")
        path.write_text("\n".join(rows) + "\n", encoding="utf-8")
        marker = path.with_suffix(path.suffix + ".backfilled")
        marker.write_text("actor_class backfilled\n", encoding="utf-8")
    return total, updated


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", nargs="*",
                    help="Filter to specific run_ids (default: all)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    out_dir = _PROJECT_ROOT / "outputs"
    if not out_dir.exists():
        print("No outputs/ directory found.")
        return

    candidates = sorted(out_dir.glob("run_*"))
    if args.runs:
        candidates = [c for c in candidates if c.name in args.runs]

    total_rows = 0
    total_updated = 0
    files_touched = 0
    for run_dir in candidates:
        p = run_dir / "proposals.jsonl"
        if not p.exists():
            continue
        n, u = backfill_file(p, dry_run=args.dry_run)
        if u > 0:
            files_touched += 1
        total_rows += n
        total_updated += u
        print(f"  {run_dir.name}: {n} rows, {u} updated"
              + (" [dry-run]" if args.dry_run else ""))

    print(f"\nTotal: {total_rows} rows scanned, "
          f"{total_updated} rows updated across {files_touched} file(s)"
          + (" [dry-run]" if args.dry_run else ""))


if __name__ == "__main__":
    main()
