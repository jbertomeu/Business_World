"""Unit tests for the orchestrator's carry-forward fallback (Wave ν+7).

Pins the behavior introduced after diagnosing the Wave ν+6 absorbing-state
bug: when `firm_agent_fn` raises an exception in the parallel firm-decision
pool, the orchestrator must carry forward the firm's prior-quarter
decisions rather than substituting dataclass-default zeros.

The bug we are protecting against: dataclass defaults on `RawDecisions`
are all zero. Constructing `RawDecisions(decision_source=..., ...)`
without setting price/production/rd/sga produces a silent firm shutdown
that the env then misreads as a real production halt.
"""

import pytest

from src.orchestrator import _carry_forward_raw_decisions
from src.types import FirmState, QuarterFlows, RawDecisions


def make_firm(capacity_units=250, cash=500_000_000.0):
    return FirmState(
        firm_id="firm_x",
        incarnation=1,
        quarter=10,
        is_active=True,
        capacity_units=capacity_units,
        base_unit_cost=14_000.0,
        ppe_gross=100_000_000.0,
        capability_stock=60.0,
        brand_stock=50.0,
        cash=cash,
    )


def test_carry_forward_uses_prior_q_primitives():
    """When prior flows exist with positive sales, the carry-forward
    inherits price (= rev/units), production, R&D, SGA from them."""
    firm = make_firm()
    prior = QuarterFlows(
        firm_id="firm_x",
        quarter=10,
        net_sales=37_500_000.0,
        units_sold=250,
        actual_rd_spend=15_000_000.0,
        actual_sga_spend=8_000_000.0,
        actual_price=150_000.0,
        actual_production=250,
    )
    raw = _carry_forward_raw_decisions(
        firm, prior,
        decision_source="fallback",
        fallback_reason="test",
        proposal_id="pid",
    )
    # Price should come from rev/units = 37.5M / 250 = 150_000
    assert raw.price == pytest.approx(150_000.0)
    assert raw.production == 250
    assert raw.rd_spend == pytest.approx(15_000_000.0)
    assert raw.sga_spend == pytest.approx(8_000_000.0)
    assert raw.decision_source == "fallback"
    assert raw.fallback_reason == "test"


def test_carry_forward_never_returns_zero_production_when_prior_was_active():
    """The headline regression: prior production was 250, fallback must
    not return 0 production."""
    firm = make_firm()
    prior = QuarterFlows(
        firm_id="firm_x",
        quarter=10,
        net_sales=37_500_000.0,
        units_sold=250,
        actual_rd_spend=15_000_000.0,
        actual_sga_spend=8_000_000.0,
        actual_price=150_000.0,
        actual_production=250,
    )
    raw = _carry_forward_raw_decisions(
        firm, prior, "fallback", "test", "pid"
    )
    assert raw.production > 0, "carry-forward must never zero out production for a firm that was producing"
    assert raw.price > 0, "carry-forward must never zero out price"
    assert raw.rd_spend > 0
    assert raw.sga_spend > 0


def test_carry_forward_handles_no_prior_flows():
    """At Q1 (or for newly-spawned firms), prior_flows may be None.
    The fallback must still return non-zero defaults."""
    firm = make_firm()
    raw = _carry_forward_raw_decisions(
        firm, None, "fallback", "test", "pid"
    )
    assert raw.price > 0
    assert raw.production > 0
    assert raw.rd_spend > 0
    assert raw.sga_spend > 0


def test_carry_forward_clamps_production_to_capacity():
    """If prior units_sold exceeded capacity (rare but possible due to
    inventory), the carry-forward production must be clamped down."""
    firm = make_firm(capacity_units=200)
    prior = QuarterFlows(
        firm_id="firm_x",
        quarter=10,
        net_sales=50_000_000.0,
        units_sold=300,    # exceeded capacity historically
        actual_rd_spend=10_000_000.0,
        actual_sga_spend=5_000_000.0,
    )
    raw = _carry_forward_raw_decisions(
        firm, prior, "fallback", "test", "pid"
    )
    assert raw.production <= 200


def test_naked_rawdecisions_construction_produces_zeros():
    """Sanity check: this is the buggy pattern we replaced. Confirms that
    constructing RawDecisions with only provenance fields yields the
    dataclass-default zeros that caused the ν+6 absorbing state."""
    raw = RawDecisions(
        decision_source="fallback",
        fallback_reason="test",
        proposal_id="pid",
    )
    assert raw.price == 0.0
    assert raw.production == 0
    assert raw.rd_spend == 0.0
    assert raw.sga_spend == 0.0
    # If you ever revert the orchestrator fix, this all-zero pattern is
    # what a firm "decides" on every exception. Don't.
