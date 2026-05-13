"""
Wave delta: state snapshots + checkpoint restart.

Implements CLAUDE principle 16 (reproducibility and audit trail) in its
most concrete form: a researcher can restart a simulation from any
saved quarter, perfectly preserving the random seed, firm state,
accounting records, action logs, and negotiations.

Snapshots are Python pickles (not JSON) because WorldState contains
objects — frozen dataclasses, tuples, nested structures — that JSON
cannot round-trip. Pickle's tradeoff: Python-version-specific and not
human-readable. For cross-tool readability, derived CSVs (compustat_q,
proposals.jsonl, etc.) remain authoritative.

RNG handling: `random.Random` state is pickleable; we snapshot it
verbatim so subsequent quarters draw identical shocks.

Usage:
    from src.snapshots import snapshot_world, restore_world
    snapshot_world(state, "outputs/run_X/snapshots/Q5.pkl")
    restored = restore_world("outputs/run_X/snapshots/Q5.pkl")
"""

from __future__ import annotations

import pickle
from pathlib import Path


SNAPSHOT_FORMAT_VERSION = 1


def snapshot_world(state, path) -> None:
    """Pickle the full WorldState to `path`.

    Atomic write: first writes to `path.tmp` then renames, so a crashed
    write never leaves a half-written snapshot that would look valid.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "wb") as f:
        pickle.dump({
            "format_version": SNAPSHOT_FORMAT_VERSION,
            "quarter_snapshotted_at": state.quarter,
            "run_id": state.run_id,
            "world_state": state,
        }, f, protocol=pickle.HIGHEST_PROTOCOL)
    tmp.replace(path)


def restore_world(path):
    """Load a snapshot and return the WorldState.

    Raises ValueError on format mismatch. Compatible with
    SNAPSHOT_FORMAT_VERSION = 1.
    """
    path = Path(path)
    with open(path, "rb") as f:
        record = pickle.load(f)
    if record.get("format_version") != SNAPSHOT_FORMAT_VERSION:
        raise ValueError(
            f"Snapshot format version mismatch: "
            f"got {record.get('format_version')}, "
            f"expected {SNAPSHOT_FORMAT_VERSION}"
        )
    return record["world_state"]


def snapshot_dir(output_dir: str, run_id: str) -> Path:
    """Canonical snapshot directory for a run."""
    return Path(output_dir) / run_id / "snapshots"


def snapshot_path(output_dir: str, run_id: str, quarter: int) -> Path:
    """Canonical path: outputs/{run_id}/snapshots/Q{N}.pkl"""
    return snapshot_dir(output_dir, run_id) / f"Q{quarter}.pkl"


def list_snapshots(output_dir: str, run_id: str) -> list[int]:
    """List quarter numbers for which snapshots exist, sorted ascending."""
    d = snapshot_dir(output_dir, run_id)
    if not d.exists():
        return []
    qs = []
    for p in d.glob("Q*.pkl"):
        try:
            qs.append(int(p.stem[1:]))  # "Q5" -> 5
        except ValueError:
            continue
    return sorted(qs)
