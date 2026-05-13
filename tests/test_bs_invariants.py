"""
Wave alpha: regression tests for the balance-sheet invariant checker.

These tests verify that:
1. The per-phase instrumentation catches manufactured BS violations.
2. End-to-end mock runs produce zero violations across all phases.
3. Stage 10/11/12 toggles (legal charge + settlement, pension accrual,
   DTL, SBC vesting, covenant waivers) don't break BS identity.

The principles these tests guard: Principle 6 (correct bookkeeping) and
Operational Rule 3 (no broken accounting).
"""

from __future__ import annotations
import json
from pathlib import Path

import pytest

from src.types import (
    FirmState, RawDecisions, ClampedDecisions, MarketOutcome,
    SimParams, MacroState, StockGrant,
)
from src.accounting import post_quarter, build_compustat_row


def _balanced_firm(**kw):
    base = dict(
        firm_id="firm_0", is_active=True, quarter=4,
        cash=100_000_000,
        accounts_receivable=15_000_000,
        inventory_units=50, inventory_value=3_000_000,
        ppe_gross=25_000_000, accum_depreciation=5_000_000,
        accounts_payable=5_000_000, accrued_expenses=1_000_000,
        common_stock=10_000,
        apic=132_000_000 - 10_000 + 20_000_000,
        retained_earnings=-20_000_000,
        shares_outstanding=10_000_000,
        capacity_units=150, base_unit_cost=14_000,
    )
    base.update(kw)
    return FirmState(**base)


def _decs(**kw):
    base = dict(
        price=95_000, production=100, capex=1_000_000,
        rd_spend=12_000_000,
        rd_allocation={"product": 0.6, "process": 0.25, "delivery": 0.15},
        sga_spend=3_000_000,
        dividends=0, buybacks=0, credit_drawn=0,
    )
    base.update(kw)
    return ClampedDecisions(**base)


def _bs_ok(firm: FirmState, tol: float = 1.0) -> bool:
    return abs(firm.total_assets - firm.total_liabilities - firm.total_equity) <= tol


# ── Baseline: each Stage 12 item individually ──

def test_legal_charge_plus_full_settlement_balances():
    """Reproduce v9 firm_1 Q2 2032 condition: $1.749M accrual + full
    settlement same-Q. Should balance."""
    firm = _balanced_firm()
    params = SimParams(legal_reserves_enabled=True)
    decs = _decs(
        legal_reserve_change=1_749_000,
        legal_settlements_paid=1_749_000,
    )
    out = MarketOutcome(firm_id="firm_0", units_sold=80, market_share=0.2)
    new_state, flows = post_quarter(firm, decs, out, params)
    assert _bs_ok(new_state), (
        f"BS fail with legal charge+settlement: "
        f"{new_state.total_assets - new_state.total_liabilities - new_state.total_equity:+,.2f}"
    )
    assert flows.legal_charge == pytest.approx(1_749_000)


def test_legal_charge_larger_than_settlement_balances():
    """Firm accrues more than it pays — reserve grows."""
    firm = _balanced_firm()
    params = SimParams(legal_reserves_enabled=True)
    decs = _decs(
        legal_reserve_change=2_000_000,
        legal_settlements_paid=500_000,
    )
    out = MarketOutcome(firm_id="firm_0", units_sold=80, market_share=0.2)
    new_state, _ = post_quarter(firm, decs, out, params)
    assert _bs_ok(new_state)
    # Reserve grew by 1.5M
    assert new_state.legal_reserve_balance == pytest.approx(1_500_000)


def test_sbc_vesting_plus_legal_plus_pension_all_on():
    """All Stage 10/11/12 items simultaneously — the 'everything at once' case."""
    vest_sched = tuple((q, 1.0 / 16.0) for q in range(1, 17))
    rsu = StockGrant(
        grant_id="g1", ceo_id="ceo_A", ceo_incarnation=1,
        firm_id="firm_0", grant_quarter=1,
        grant_type="rsu", shares=200_000, strike_price=0.0,
        vesting_schedule=vest_sched, fair_value_at_grant=3_500_000,
    )
    opt = StockGrant(
        grant_id="g2", ceo_id="ceo_A", ceo_incarnation=1,
        firm_id="firm_0", grant_quarter=1,
        grant_type="stock_option", shares=400_000, strike_price=17.50,
        vesting_schedule=vest_sched, fair_value_at_grant=2_100_000,
    )
    # Put pension + DTL into APIC offset so the starting firm balances.
    # (_balanced_firm's apic is calibrated to a zero-liability starting state.)
    firm = _balanced_firm(
        quarter=5,
        ceo_stock_grants=(rsu, opt),
        ceo_type="ceo_A", ceo_incarnation=1,
        ceo_stock_comp_this_q=350_000,  # simulating Phase 5.7 SBC accrual
        pension_liability=1_000_000,
        deferred_tax_liability=200_000,
        retained_earnings=-20_000_000 - 1_000_000 - 200_000,  # offset L growth
    )
    assert _bs_ok(firm), "starting firm must balance for this test to be meaningful"
    params = SimParams(
        legal_reserves_enabled=True,
        pension_enabled=True,
        deferred_taxes_enabled=True,
    )
    decs = _decs(
        legal_reserve_change=1_500_000,
        legal_settlements_paid=1_500_000,
        pension_contribution=50_000,
    )
    out = MarketOutcome(firm_id="firm_0", units_sold=80, market_share=0.2)
    new_state, flows = post_quarter(firm, decs, out, params)
    assert _bs_ok(new_state, tol=1.0), (
        f"BS fail with all Stage 12 on simultaneously: "
        f"resid={new_state.total_assets - new_state.total_liabilities - new_state.total_equity:+,.2f}"
    )
    # APIC grew by SBC
    assert new_state.apic - firm.apic == pytest.approx(350_000, abs=1)


def test_multi_quarter_run_stays_balanced():
    """Run 8 quarters of legal charges + pension + DTL without SBC.
    Checks that residuals don't accumulate quarter-to-quarter."""
    firm = _balanced_firm()
    params = SimParams(
        legal_reserves_enabled=True,
        pension_enabled=True,
        deferred_taxes_enabled=True,
    )
    decs = _decs(
        legal_reserve_change=500_000,
        legal_settlements_paid=500_000,
        pension_contribution=0,
    )
    out = MarketOutcome(firm_id="firm_0", units_sold=80, market_share=0.2)
    for q in range(1, 9):
        firm, _ = post_quarter(firm, decs, out, params)
        assert _bs_ok(firm), (
            f"Q{q}: BS fail "
            f"resid={firm.total_assets - firm.total_liabilities - firm.total_equity:+,.2f}"
        )


def test_compustat_row_decision_source_flows_through():
    """Wave alpha provenance test: decision_source stamped on raw/clamped/row."""
    firm = _balanced_firm()
    decs = _decs(
        decision_source="fallback",
        fallback_reason="LLM returned None",
    )
    out = MarketOutcome(firm_id="firm_0", units_sold=80, market_share=0.2)
    new_state, flows = post_quarter(firm, decs, out, SimParams())
    macro = MacroState(fyear=2031, fqtr=1, quarter=1)
    row = build_compustat_row(new_state, flows, decs, macro, run_id="t")
    assert row.decision_source == "fallback"
    assert row.fallback_reason == "LLM returned None"


# ── Manufactured violation to prove the checker fires ──

def test_bs_invariant_checker_fires_on_manufactured_violation():
    """Directly create an imbalanced firm and verify _check_bs_invariants
    logs it. Proves the guard isn't silently broken."""
    from src.orchestrator import _check_bs_invariants, WorldState

    state = WorldState(run_id="test_fire")
    state.firms["firm_X"] = FirmState(
        firm_id="firm_X", is_active=True,
        cash=1_000_000,
        # Liabilities + equity = 0 → resid = +1M
    )

    # Run the checker; it should add one entry to bs_violation_log
    _check_bs_invariants(state, "manufactured_test", None)
    assert len(state.bs_violation_log) == 1
    entry = state.bs_violation_log[0]
    assert entry["firm_id"] == "firm_X"
    assert entry["residual"] == pytest.approx(1_000_000)
    assert entry["phase"] == "manufactured_test"


def test_bs_invariant_writes_to_jsonl(tmp_path):
    """End-to-end: manufactured violation → output_organizer writes it to
    bs_violations.jsonl as one record per event."""
    from src.orchestrator import _check_bs_invariants, WorldState
    from src.output_organizer import organize_run_outputs

    state = WorldState(run_id="t_jsonl_001")
    state.firms["firm_X"] = FirmState(
        firm_id="firm_X", is_active=True, cash=500_000,
    )
    _check_bs_invariants(state, "test_phase", None)

    organize_run_outputs(
        run_id="t_jsonl_001",
        output_dir=str(tmp_path),
        compustat_rows=[],
        gazettes=[],
        product_spec_history=[],
        board_minutes_history=[],
        n_firms=1, n_quarters=1, seed=0,
        world_state=state,
    )

    path = tmp_path / "t_jsonl_001" / "bs_violations.jsonl"
    assert path.exists()
    lines = path.read_text().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["firm_id"] == "firm_X"
    assert record["residual"] == pytest.approx(500_000)
    assert record["phase"] == "test_phase"
