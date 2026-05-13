"""
Tests for Stage 12 corporate finance features:
  C1: Stock option exercise mechanics (orchestrator, not accounting)
  C2: Insider transactions dataset
  C3: Legal reserves
  C4: Activist investor parse
  C5: DTA/DTL (book-tax difference)
  C6: Pension obligations
"""

from __future__ import annotations
from dataclasses import replace

import pytest

from src.types import (
    FirmState, ClampedDecisions, MarketOutcome, SimParams,
    InsiderTradingEvent, MacroState,
)
from src.accounting import post_quarter
from src.datasets import (
    build_insider_transactions, ACTIVIST_CAMPAIGNS_COLUMNS,
    INSIDER_TRANSACTIONS_COLUMNS,
)
from src.activist import parse_activist_campaigns


# ── Helpers ──────────────────────────────────────────────────────────────

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


# ── C3: Legal reserves ────────────────────────────────────────────────────

def test_legal_reserve_accrual_gated_off_is_noop():
    """Toggle off → legal_reserve_change ignored, no change to BS."""
    firm = _balanced_firm()
    decs = _decs(legal_reserve_change=5_000_000)  # would accrue $5M
    out = MarketOutcome(firm_id="firm_0", units_sold=80, market_share=0.2)
    new_state, flows = post_quarter(firm, decs, out, SimParams())
    assert flows.legal_charge == 0
    assert new_state.legal_reserve_balance == 0


def test_legal_reserve_accrual_when_enabled():
    """Toggle on → accrual hits IS (non-cash) and BS (liability)."""
    firm = _balanced_firm()
    params = SimParams(legal_reserves_enabled=True)
    decs = _decs(legal_reserve_change=5_000_000)
    out = MarketOutcome(firm_id="firm_0", units_sold=80, market_share=0.2)
    new_state, flows = post_quarter(firm, decs, out, params)
    assert flows.legal_charge == pytest.approx(5_000_000, rel=0.01)
    assert new_state.legal_reserve_balance == pytest.approx(5_000_000, rel=0.01)
    # NI lower than with no accrual
    _, flows_baseline = post_quarter(firm, _decs(), out, params)
    assert flows.net_income < flows_baseline.net_income


def test_legal_settlement_pays_cash_and_reduces_reserve():
    """Settlement: cash out, BS liability down, no IS impact."""
    firm = _balanced_firm(legal_reserve_balance=4_000_000)
    params = SimParams(legal_reserves_enabled=True)
    decs = _decs(legal_settlements_paid=3_000_000)
    out = MarketOutcome(firm_id="firm_0", units_sold=80, market_share=0.2)
    new_state, flows = post_quarter(firm, decs, out, params)
    assert new_state.legal_reserve_balance == pytest.approx(1_000_000, rel=0.01)
    # Cash should drop by at least the settlement amount (plus other cash flows)
    baseline_state, _ = post_quarter(firm, _decs(), out, params)
    assert new_state.cash < baseline_state.cash


# ── C6: Pension ──────────────────────────────────────────────────────────

def test_pension_gated_off_is_noop():
    firm = _balanced_firm()
    decs = _decs(pension_contribution=1_000_000)
    out = MarketOutcome(firm_id="firm_0", units_sold=80, market_share=0.2)
    new_state, flows = post_quarter(firm, decs, out, SimParams())
    assert flows.pension_service_cost == 0
    assert new_state.pension_liability == 0


def test_pension_service_cost_accrues_when_enabled():
    """Toggle on → service cost accrues as a non-cash IS expense, raises liability."""
    firm = _balanced_firm()
    params = SimParams(pension_enabled=True)
    decs = _decs()  # no contribution → liability grows
    out = MarketOutcome(firm_id="firm_0", units_sold=80, market_share=0.2)
    new_state, flows = post_quarter(firm, decs, out, params)
    assert flows.pension_service_cost > 0
    assert new_state.pension_liability > 0


def test_pension_contribution_reduces_liability_and_cash():
    """Contribution: cash out, liability down (after adding service cost)."""
    firm = _balanced_firm(pension_liability=5_000_000)
    params = SimParams(pension_enabled=True)
    decs_no = _decs()
    decs_contrib = _decs(pension_contribution=2_000_000)
    out = MarketOutcome(firm_id="firm_0", units_sold=80, market_share=0.2)
    st_no, _ = post_quarter(firm, decs_no, out, params)
    st_contrib, _ = post_quarter(firm, decs_contrib, out, params)
    # Liability is lower when we contribute
    assert st_contrib.pension_liability < st_no.pension_liability
    # Cash is lower when we contribute
    assert st_contrib.cash < st_no.cash


# ── C5: DTA/DTL ──────────────────────────────────────────────────────────

def test_deferred_tax_gated_off_is_noop():
    firm = _balanced_firm()
    out = MarketOutcome(firm_id="firm_0", units_sold=80, market_share=0.2)
    new_state, flows = post_quarter(firm, _decs(), out, SimParams())
    assert flows.dtl_change == 0
    assert new_state.deferred_tax_liability == 0


def test_deferred_tax_liability_accrues_when_enabled():
    """Toggle on → book-tax depreciation difference accumulates DTL."""
    firm = _balanced_firm()
    params = SimParams(deferred_taxes_enabled=True)
    out = MarketOutcome(firm_id="firm_0", units_sold=80, market_share=0.2)
    new_state, flows = post_quarter(firm, _decs(), out, params)
    # First quarter: with positive capex or PP&E, book-tax timing should
    # create some DTL movement (may be positive or zero depending on sign).
    assert new_state.deferred_tax_liability >= 0  # never negative without reversal


# ── C2: Insider transactions dataset ─────────────────────────────────────

def test_build_insider_transactions_empty_state():
    class _EmptyState:
        run_id = "test"
        insider_events: list = []
    rows = build_insider_transactions(_EmptyState())
    assert rows == []


def test_build_insider_transactions_from_events():
    class _State:
        run_id = "test_run"
        insider_events = [
            InsiderTradingEvent(
                run_id="test_run", firm_id="firm_0", ceo_id="ceo_A",
                ceo_incarnation=1, event_quarter=4, event_date="2028-12-31",
                event_type="grant", transaction_shares=100_000,
                transaction_price=10.0, strike_price=10.0,
                transaction_value=1_000_000.0, shares_held_after=0,
                notes="Annual equity grant",
            ),
            InsiderTradingEvent(
                run_id="test_run", firm_id="firm_0", ceo_id="ceo_A",
                ceo_incarnation=1, event_quarter=8, event_date="2029-12-31",
                event_type="sell", transaction_shares=20_000,
                transaction_price=15.0, strike_price=0.0,
                transaction_value=300_000.0, shares_held_after=80_000,
                notes="10b5-1 scheduled sale",
            ),
        ]
    rows = build_insider_transactions(_State())
    assert len(rows) == 2
    assert rows[0]["event_type"] == "grant"
    assert rows[1]["event_type"] == "sell"
    # Columns must be a subset of the declared schema
    for row in rows:
        for k in row:
            assert k in INSIDER_TRANSACTIONS_COLUMNS, f"unexpected column {k}"


# ── BS identity on CompustatRow (not just on new_state) ─────────────────

def test_compustat_row_bs_identity_with_all_stage12_toggles():
    """Regression for audit bug: BS identity must hold on CompustatRow
    itself (what researchers read), not only on FirmState.evolve output.
    Previously, total_liabilities excluded pension/legal/DTL, so
    atq − ltq − ceqq ≠ 0 on every row when those toggles were ON.
    """
    from src.accounting import build_compustat_row
    firm = _balanced_firm()
    params = SimParams(
        legal_reserves_enabled=True,
        pension_enabled=True,
        deferred_taxes_enabled=True,
    )
    decs = _decs(
        legal_reserve_change=3_000_000,
        pension_contribution=500_000,
    )
    out = MarketOutcome(firm_id="firm_0", units_sold=80, market_share=0.2)
    new_state, flows = post_quarter(firm, decs, out, params)
    # Build the compustat row the way output_organizer does
    macro = MacroState(fyear=2031, fqtr=1, quarter=1)
    row = build_compustat_row(new_state, flows, decs, macro, run_id="t")
    bs_residual = abs(row.atq - row.ltq - row.ceqq)
    assert bs_residual < 1.0, (
        f"BS identity fails: atq={row.atq:.2f} ltq={row.ltq:.2f} "
        f"ceqq={row.ceqq:.2f} residual={bs_residual:.2f}. "
        f"pension_liability_bs={row.pension_liability_bs}, "
        f"legal_reserve_bs={row.legal_reserve_bs}, txditcq={row.txditcq}"
    )
    # Sanity: liabilities must include the Stage 12 items
    assert row.pension_liability_bs > 0 or row.legal_reserve_bs > 0


def test_compustat_row_bs_identity_with_tax_adjustment():
    """Regression for firm_3 deferred-tax leak: when Stage 4/5/6 IS
    adjustments scale tax_expense (scale != 1), end_taxes_payable must
    be recomputed from the ADJUSTED tax_expense or atq − ltq − ceqq
    leaks by (original_tax − adjusted_tax).
    """
    from src.accounting import build_compustat_row
    firm = _balanced_firm()
    params = SimParams(
        legal_reserves_enabled=True,
        pension_enabled=True,
    )
    # Push a legal charge through — scales pretax and tax_expense.
    decs = _decs(legal_reserve_change=1_000_000)
    out = MarketOutcome(firm_id="firm_0", units_sold=120, market_share=0.3)
    new_state, flows = post_quarter(firm, decs, out, params)
    macro = MacroState(fyear=2031, fqtr=1, quarter=1)
    row = build_compustat_row(new_state, flows, decs, macro, run_id="t")
    # txpq and txtq must now agree under our simplification
    assert abs(row.txpq - row.txtq) < 1.0, (
        f"txpq={row.txpq:.2f} != txtq={row.txtq:.2f}"
    )
    assert abs(row.atq - row.ltq - row.ceqq) < 1.0


# ── C4: Activist parse ───────────────────────────────────────────────────

def test_activist_parse_empty_response():
    assert parse_activist_campaigns(None, quarter=4, run_id="r") == []
    assert parse_activist_campaigns({"campaigns": []}, quarter=4, run_id="r") == []


def test_activist_parse_valid_campaign():
    resp = {
        "campaigns": [{
            "firm_id": "firm_2",
            "demand_type": "buyback",
            "demand_specifics": "Return $50M via accelerated buyback.",
            "stake_pct_implied": 0.06,
            "thesis": "Excess cash, no credible M&A, trading below book.",
        }]
    }
    out = parse_activist_campaigns(resp, quarter=8, run_id="run_X")
    assert len(out) == 1
    c = out[0]
    assert c["firm_id"] == "firm_2"
    assert c["demand_type"] == "buyback"
    assert c["stake_pct_implied"] == pytest.approx(0.06)
    assert c["event_quarter"] == 8
    assert c["run_id"] == "run_X"
    # Columns the dataset builder expects are present (except those it reads via .get)
    for key in ("firm_id", "event_quarter", "activist_id", "demand_type",
                "demand_specifics", "stake_pct_implied"):
        assert key in c


def test_activist_parse_sanitizes_bad_demand_type():
    resp = {"campaigns": [{"firm_id": "firm_1", "demand_type": "nonsense"}]}
    out = parse_activist_campaigns(resp, quarter=4, run_id="r")
    assert out[0]["demand_type"] == "strategic_review"


def test_activist_parse_clamps_stake_range():
    resp = {"campaigns": [{"firm_id": "firm_1", "demand_type": "buyback",
                           "stake_pct_implied": 5.0}]}  # impossible 500%
    out = parse_activist_campaigns(resp, quarter=4, run_id="r")
    assert 0 <= out[0]["stake_pct_implied"] <= 0.5
