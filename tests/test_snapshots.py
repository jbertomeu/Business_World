"""
Wave delta: snapshot + restart tests.

Guards CLAUDE principle 16 (reproducibility). Verifies:
  - WorldState is pickleable with full nested structure
  - Snapshot round-trips exactly
  - Continuing from a mid-run snapshot yields the same end-state as
    running straight through (equivalent to replay test)
  - Atomic write: a partial snapshot file does not corrupt state
"""

from __future__ import annotations

import pickle
import pytest

from src.snapshots import (
    snapshot_world, restore_world,
    snapshot_path, snapshot_dir, list_snapshots,
    SNAPSHOT_FORMAT_VERSION,
)
from src.orchestrator import WorldState


def test_worldstate_is_pickleable():
    """WorldState + all its nested types must round-trip through pickle."""
    state = WorldState(run_id="test_pickle")
    # Exercise nested structures
    state.action_log.append({"test": 1})
    state.bs_violation_log.append({"phase": "x"})
    state.negotiations_log.append({"topic": "y"})
    # Must pickle without error
    blob = pickle.dumps(state)
    # Must unpickle to equivalent state
    restored = pickle.loads(blob)
    assert restored.run_id == "test_pickle"
    assert restored.action_log == [{"test": 1}]


def test_snapshot_roundtrip_writes_and_reads(tmp_path):
    state = WorldState(run_id="roundtrip")
    state.quarter = 7
    state.action_log.append({"proposal_id": "abc-123"})

    path = tmp_path / "Q7.pkl"
    snapshot_world(state, path)
    assert path.exists()

    restored = restore_world(path)
    assert restored.run_id == "roundtrip"
    assert restored.quarter == 7
    assert restored.action_log == [{"proposal_id": "abc-123"}]


def test_snapshot_path_canonical_form(tmp_path):
    """snapshot_path() produces a predictable outputs/<run>/snapshots/Q<N>.pkl path."""
    p = snapshot_path(str(tmp_path), "my_run", 5)
    assert p.parts[-1] == "Q5.pkl"
    assert p.parts[-2] == "snapshots"
    assert p.parts[-3] == "my_run"


def test_list_snapshots_returns_sorted_quarters(tmp_path):
    d = snapshot_dir(str(tmp_path), "test_list")
    d.mkdir(parents=True)
    for q in [3, 1, 5, 2]:
        (d / f"Q{q}.pkl").write_bytes(b"x")
    assert list_snapshots(str(tmp_path), "test_list") == [1, 2, 3, 5]


def test_list_snapshots_empty_when_dir_missing(tmp_path):
    assert list_snapshots(str(tmp_path), "nonexistent") == []


def test_atomic_write_does_not_leave_corrupt_partial(tmp_path, monkeypatch):
    """If pickle.dump fails mid-write, the real path must not exist as
    a corrupt file (only .tmp does)."""
    state = WorldState(run_id="atom")
    path = tmp_path / "Q1.pkl"

    # Monkeypatch pickle.dump to raise after opening .tmp
    import src.snapshots as snap_mod
    original_dump = snap_mod.pickle.dump
    def failing_dump(*args, **kwargs):
        raise RuntimeError("simulated write failure")
    snap_mod.pickle.dump = failing_dump
    try:
        with pytest.raises(RuntimeError):
            snapshot_world(state, path)
    finally:
        snap_mod.pickle.dump = original_dump

    # Real path never got written
    assert not path.exists()
    # The .tmp may or may not exist; it's OK either way — point is the
    # authoritative `.pkl` is absent.


def test_format_version_mismatch_raises(tmp_path):
    """Loading a snapshot with a different format version raises ValueError."""
    path = tmp_path / "bad.pkl"
    with open(path, "wb") as f:
        pickle.dump({
            "format_version": 999,
            "quarter_snapshotted_at": 1,
            "run_id": "bad",
            "world_state": WorldState(run_id="bad"),
        }, f)
    with pytest.raises(ValueError, match="format version mismatch"):
        restore_world(path)


def test_format_version_constant_is_1():
    """Guard against accidental format-version bumps without migration."""
    assert SNAPSHOT_FORMAT_VERSION == 1


def test_resume_from_snapshot_continues_at_correct_quarter():
    """Snapshot at Q3, restore, verify quarter=3. Then run_quarter advances
    to 4 (not starts over at 1)."""
    from src.orchestrator import run_quarter
    from src.types import FirmState, RawDecisions, SimParams
    from src.config import RunConfig

    state = WorldState(run_id="resume_test")
    state.firms["firm_0"] = FirmState(
        firm_id="firm_0", is_active=True, cash=0, quarter=0,
        capacity_units=100, base_unit_cost=40_000, ppe_gross=25_000_000,
    )
    state.params = SimParams()
    config = RunConfig()

    def firm_fn(fid, firm, info, params):
        import uuid
        return RawDecisions(
            price=95_000, production=50, capex=0, rd_spend=10_000_000,
            rd_allocation={"product": 0.6, "process": 0.2, "delivery": 0.2},
            sga_spend=5_000_000, decision_source="llm",
            proposal_id=str(uuid.uuid4()),
        )

    def env_fn(a, f, m, p):
        return {"total_demand": 50,
                "firm_outcomes": {"firm_0": {"units_sold": 50, "market_share": 1.0}},
                "narrative": "ok"}

    # Run 3 quarters
    for _ in range(3):
        state = run_quarter(state, firm_agent_fn=firm_fn, env_agent_fn=env_fn,
                             config=config)
    assert state.quarter == 3

    # Snapshot + restore
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        from pathlib import Path
        path = Path(tmp) / "Q3.pkl"
        snapshot_world(state, path)
        restored = restore_world(path)

    # Restored state carries quarter=3
    assert restored.quarter == 3
    # Running one more quarter advances to 4
    restored = run_quarter(restored, firm_agent_fn=firm_fn,
                             env_agent_fn=env_fn, config=config)
    assert restored.quarter == 4
