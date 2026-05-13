"""
Wave epsilon: tests for beliefs.py.

Guards CLAUDE principle 17 (separate latent / signal / report). Verifies:
  - Noise is deterministic given the RNG (reproducibility preserved)
  - Zero-valued fields don't blow up
  - Numeric fields noised, non-numeric untouched
  - Toggle actually gates the behavior
  - Two observers of the same peer see DIFFERENT noisy observations
    (noise is per-pair, not shared)
"""

from __future__ import annotations
import random

import pytest

from src.beliefs import (
    FirmBelief, ActivistMemory, AuditorMemory, SECMemory,
    add_observation_noise, observe_peer_data,
)


def test_add_observation_noise_deterministic_given_rng():
    rng1 = random.Random(42)
    rng2 = random.Random(42)
    v1 = add_observation_noise(1000.0, rng1, 0.05)
    v2 = add_observation_noise(1000.0, rng2, 0.05)
    assert v1 == v2


def test_add_observation_noise_zero_value_stays_zero():
    rng = random.Random(1)
    assert add_observation_noise(0.0, rng) == 0.0


def test_add_observation_noise_never_negative():
    rng = random.Random(1)
    for _ in range(100):
        v = add_observation_noise(1.0, rng, relative_sd=10.0)  # extreme SD
        assert v >= 0


def test_observe_peer_data_noises_numerics_keeps_rest():
    rng = random.Random(7)
    true = {"price": 100_000, "market_share": 0.25, "generation": 2,
             "equity_price": 50.0, "revenue": 10_000_000,
             "firm_id": "firm_0"}
    noisy = observe_peer_data(true, rng, relative_sd=0.1)
    # Numeric fields changed
    assert noisy["price"] != 100_000 or noisy["market_share"] != 0.25
    # Generation (int) still present, generation is noised too since it's numeric
    # Per the code, only specified keys get noised — generation isn't in the list
    assert noisy["generation"] == 2
    # Non-numeric firm_id preserved
    assert noisy["firm_id"] == "firm_0"


def test_observe_peer_data_two_observers_see_different_values():
    """Two observers MUST see different noisy values of the same peer."""
    true = {"price": 100_000, "revenue": 5_000_000}
    noisy1 = observe_peer_data(true, random.Random(1), 0.05)
    noisy2 = observe_peer_data(true, random.Random(2), 0.05)
    assert noisy1["price"] != noisy2["price"]


def test_firm_belief_default_initializes_empty():
    b = FirmBelief(firm_id="firm_0")
    assert b.quarter_observed == 0
    assert b.estimated_peer_prices == {}
    assert b.confidence == 1.0


def test_activist_memory_campaigns_list():
    m = ActivistMemory()
    m.campaigns_launched.append((5, "firm_2", "buyback", "reject"))
    assert len(m.campaigns_launched) == 1


def test_auditor_memory_client_history():
    m = AuditorMemory(auditor_id="auditor_1")
    m.client_history.setdefault("firm_1", []).append(
        {"fyear": 2031, "opinion": "unqualified", "going_concern": False}
    )
    assert m.client_history["firm_1"][0]["opinion"] == "unqualified"


def test_sec_memory_priors():
    m = SECMemory()
    m.firm_priors["firm_1"] = 0.75
    assert m.firm_priors["firm_1"] == 0.75


def test_noisy_signals_toggle_off_yields_exact_observation():
    """When noisy_signals_enabled=False, info_package peer data should
    EXACTLY match the true flows (no noise applied)."""
    from src.orchestrator import WorldState, _build_firm_info_package
    from src.types import FirmState, SimParams, QuarterFlows

    state = WorldState(run_id="noise_off")
    state.firms["firm_0"] = FirmState(
        firm_id="firm_0", is_active=True, equity_price=10.0,
        product_generation=1, shares_outstanding=1_000_000,
    )
    state.firms["firm_1"] = FirmState(
        firm_id="firm_1", is_active=True, equity_price=20.0,
        product_generation=1, shares_outstanding=1_000_000,
    )
    state.last_quarter_flows["firm_1"] = QuarterFlows(
        firm_id="firm_1", actual_price=95_000, market_share=0.3,
        net_sales=10_000_000, rd_expense=5_000_000,
    )
    state.params = SimParams(noisy_signals_enabled=False)
    pkg = _build_firm_info_package(state, "firm_0")
    # firm_1 observation should equal true flows
    peer = pkg["public_competitors"]["firm_1"]
    assert peer["price"] == 95_000
    assert peer["market_share"] == 0.3
    assert peer["revenue"] == 10_000_000


def test_noisy_signals_toggle_on_perturbs_peer_observations():
    """When noisy_signals_enabled=True, info_package peer prices should
    differ from the true value."""
    from src.orchestrator import WorldState, _build_firm_info_package
    from src.types import FirmState, SimParams, QuarterFlows

    state = WorldState(run_id="noise_on")
    state.quarter = 5  # stable seed component
    state.firms["firm_0"] = FirmState(
        firm_id="firm_0", is_active=True,
        product_generation=1, shares_outstanding=1_000_000,
    )
    state.firms["firm_1"] = FirmState(
        firm_id="firm_1", is_active=True,
        product_generation=1, shares_outstanding=1_000_000,
    )
    state.last_quarter_flows["firm_1"] = QuarterFlows(
        firm_id="firm_1", actual_price=100_000, market_share=0.25,
        net_sales=10_000_000, rd_expense=5_000_000,
    )
    state.params = SimParams(noisy_signals_enabled=True, noisy_signals_sd=0.1)
    pkg = _build_firm_info_package(state, "firm_0")
    peer = pkg["public_competitors"]["firm_1"]
    # Must differ from true value (nonzero-noise chance of exact match is ~0)
    assert peer["price"] != 100_000


def test_noisy_signals_reproducible_across_info_package_calls():
    """Calling _build_firm_info_package twice in the same state should
    yield the SAME noisy peer observation (seed is deterministic in
    state.quarter + target_firm_id + peer_fid)."""
    from src.orchestrator import WorldState, _build_firm_info_package
    from src.types import FirmState, SimParams, QuarterFlows

    def _build_state():
        state = WorldState(run_id="repro")
        state.quarter = 3
        state.firms["firm_0"] = FirmState(
            firm_id="firm_0", is_active=True,
            product_generation=1, shares_outstanding=1_000_000,
        )
        state.firms["firm_1"] = FirmState(
            firm_id="firm_1", is_active=True,
            product_generation=1, shares_outstanding=1_000_000,
        )
        state.last_quarter_flows["firm_1"] = QuarterFlows(
            firm_id="firm_1", actual_price=100_000,
            net_sales=5_000_000, rd_expense=1_000_000,
        )
        state.params = SimParams(noisy_signals_enabled=True, noisy_signals_sd=0.1)
        return state

    s1 = _build_state()
    s2 = _build_state()
    p1 = _build_firm_info_package(s1, "firm_0")["public_competitors"]["firm_1"]
    p2 = _build_firm_info_package(s2, "firm_0")["public_competitors"]["firm_1"]
    assert p1["price"] == p2["price"]
    assert p1["revenue"] == p2["revenue"]
