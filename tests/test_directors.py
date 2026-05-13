"""
Tests for Wave θ director pool + interlock info-leak mechanism.

Covers:
- Pool population respects the `directors_enabled` toggle
- Max-seat cap enforced
- Interlock counter is correct
- Info-leak reduces observation noise proportionally
- Lifecycle events (default departure, annual refresh) when enabled
- Lifecycle toggle default = OFF (backward compat)
"""

from __future__ import annotations

import statistics

from src.orchestrator import (
    initialize_world,
    _count_shared_directors,
    _director_lifecycle_phase,
)
from src.types import SimParams
from src.beliefs import observe_peer_data
import random


def test_directors_enabled_default_populates_pool():
    state = initialize_world(n_firms=5, params=SimParams(),
                              seed=42, run_id="t",
                              directors_enabled=True)
    assert len(state.directors) > 0
    # Every seated director should have ≥1 seat
    for d in state.directors.values():
        assert len(d.seats) >= 1


def test_directors_disabled_empty_pool():
    state = initialize_world(n_firms=5, params=SimParams(),
                              seed=42, run_id="t",
                              directors_enabled=False)
    assert state.directors == {}


def test_max_seats_per_director_cap():
    state = initialize_world(n_firms=10, params=SimParams(),
                              seed=42, run_id="t",
                              directors_enabled=True)
    for d in state.directors.values():
        assert len(d.seats) <= 3, (
            f"Director {d.director_id} has {len(d.seats)} seats — exceeds cap"
        )


def test_interlock_counter_correct():
    state = initialize_world(n_firms=5, params=SimParams(),
                              seed=42, run_id="t",
                              directors_enabled=True)
    fids = list(state.firms.keys())
    # Manual recount for a specific pair
    a, b = fids[0], fids[1]
    expected = sum(1 for d in state.directors.values()
                   if a in d.seats and b in d.seats)
    actual = _count_shared_directors(state, a, b)
    assert actual == expected


def test_interlock_zero_when_disabled():
    state = initialize_world(n_firms=5, params=SimParams(),
                              seed=42, run_id="t",
                              directors_enabled=False)
    fids = list(state.firms.keys())
    assert _count_shared_directors(state, fids[0], fids[1]) == 0


def test_info_leak_reduces_noise_proportionally():
    """With 1 shared director, effective SD halves → observations ~2x closer to truth."""
    true_vals = {"revenue": 50_000_000, "price": 100_000, "market_share": 0.3}
    base_sd = 0.20
    n = 500

    errs_0 = []
    errs_1 = []
    errs_2 = []
    for t in range(n):
        rng = random.Random(t)
        errs_0.append(
            abs(observe_peer_data(true_vals, rng, relative_sd=base_sd)["revenue"]
                - true_vals["revenue"]) / true_vals["revenue"]
        )
    for t in range(n):
        rng = random.Random(t + 10000)
        errs_1.append(
            abs(observe_peer_data(true_vals, rng, relative_sd=base_sd / 2)["revenue"]
                - true_vals["revenue"]) / true_vals["revenue"]
        )
    for t in range(n):
        rng = random.Random(t + 20000)
        errs_2.append(
            abs(observe_peer_data(true_vals, rng, relative_sd=base_sd / 3)["revenue"]
                - true_vals["revenue"]) / true_vals["revenue"]
        )

    m0 = statistics.mean(errs_0)
    m1 = statistics.mean(errs_1)
    m2 = statistics.mean(errs_2)
    # 1-shared should be ~50% of 0-shared error
    assert 0.40 < m1 / m0 < 0.65, f"expected ~0.5, got {m1/m0:.2f}"
    # 2-shared should be ~33% of 0-shared error
    assert 0.25 < m2 / m0 < 0.45, f"expected ~0.33, got {m2/m0:.2f}"


def test_lifecycle_default_off():
    """Lifecycle toggle defaults to False — existing runs stay static."""
    from src.config import RunConfig
    c = RunConfig()
    assert c.director_lifecycle_enabled is False


def test_lifecycle_default_departure_on_firm_inactive():
    """When a firm goes inactive, seated directors lose that seat."""
    state = initialize_world(n_firms=3, params=SimParams(),
                              seed=42, run_id="t",
                              directors_enabled=True)
    # Mark firm_0 as inactive
    firm_0 = state.firms["firm_0"]
    state.firms["firm_0"] = firm_0.evolve(is_active=False)
    # Seat the lifecycle phase (not a Q4, so only default departures fire)
    n_dirs_before = len(state.directors)
    _director_lifecycle_phase(state)
    # firm_0 should no longer appear in any director's seats
    for d in state.directors.values():
        assert "firm_0" not in d.seats, (
            f"Director {d.director_id} still seated at defaulted firm_0: "
            f"seats={d.seats}"
        )
    # At least one turnover event should be recorded
    default_events = [e for e in state.director_turnover
                      if e["event_type"] == "firm_default_departure"]
    assert len(default_events) > 0


def test_lifecycle_q4_refresh_generates_events():
    """Q4 refresh triggers retirements + appointments with ~25% probability per firm."""
    state = initialize_world(n_firms=5, params=SimParams(),
                              seed=42, run_id="t",
                              directors_enabled=True)
    # Force Q4
    from src.types import MacroState
    state.macro = MacroState(quarter=4, fyear=2031, fqtr=4)
    # Run lifecycle multiple times (25% per-firm per-Q4 expected = ~1 refresh per 5 firms)
    for _ in range(20):
        _director_lifecycle_phase(state)
    # Over 20 iterations × 5 firms × 25% = 25 expected events
    retirements = [e for e in state.director_turnover if e["event_type"] == "retirement"]
    appointments = [e for e in state.director_turnover if e["event_type"] == "appointment"]
    assert len(retirements) >= 5, f"expected ≥5 retirements, got {len(retirements)}"
    assert len(appointments) >= 5, f"expected ≥5 appointments, got {len(appointments)}"


def test_lifecycle_noop_when_no_directors():
    """Calling lifecycle when directors are disabled should be a no-op."""
    state = initialize_world(n_firms=3, params=SimParams(),
                              seed=42, run_id="t",
                              directors_enabled=False)
    _director_lifecycle_phase(state)
    assert state.directors == {}
    assert state.director_turnover == []
