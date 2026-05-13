"""
Tests for Stage 4 (working capital policies) and Stage 5 (bad debt).

Stage 4:
  - payables_days_target → DPO-driven AP
  - receivables_days_target → DSO-driven AR
  - deposit_pct → deferred_revenue BS line
  - ppe_disposal → PP&E sale, cash-in, gain/loss, reduces gross+accum_dep

Stage 5:
  - allowance_pct_of_ar → allowance_for_doubtful_accounts contra-asset
  - env-injected write_offs_this_quarter → gross AR reduction + allowance release
  - bad_debt_expense = Δallowance (after write-offs applied)

Also: backward-compat when toggles off (behavior identical to pre-Stage-4).
"""

from __future__ import annotations

import pytest

from src.types import (
    FirmState, RawDecisions, ClampedDecisions, MarketOutcome, SimParams,
    QuarterFlows,
)
from src.accounting import post_quarter, validate_state


def _base_firm(cash=100_000_000, ar=15_000_000, ap=5_000_000):
    # Carefully balanced: assets = liabilities + equity
    # assets = cash + AR + inv + net_ppe = 100M + 15M + 3M + 20M = 138M
    # liabilities = AP + accrued = 5M + 1M = 6M
    # equity = 138M - 6M = 132M = common_stock (10k) + APIC - RE_deficit
    apic = 132_000_000 - 10_000 + 20_000_000  # = 151,990,000
    return FirmState(
        firm_id="firm_0", is_active=True, quarter=4,
        cash=cash,
        accounts_receivable=ar,
        inventory_units=50, inventory_value=3_000_000,
        ppe_gross=25_000_000, accum_depreciation=5_000_000,
        accounts_payable=ap, accrued_expenses=1_000_000,
        taxes_payable=0,
        common_stock=10_000, apic=apic,
        retained_earnings=-20_000_000,
        shares_outstanding=10_000_000,
        capacity_units=150, base_unit_cost=14_000,
    )


def _base_decisions(**kwargs):
    base = dict(
        price=95_000, production=100, capex=1_000_000,
        rd_spend=12_000_000,
        rd_allocation={"product": 0.6, "process": 0.25, "delivery": 0.15},
        sga_spend=3_000_000,
        dividends=0, buybacks=0, credit_drawn=0,
    )
    base.update(kwargs)
    return ClampedDecisions(**base)


def _base_outcome(units=80, share=0.2):
    return MarketOutcome(firm_id="firm_0", units_sold=units, market_share=share)


# ── Stage 4: DPO/DSO drive AR/AP ─────────────────────────────────────────

def test_dso_higher_than_default_increases_ar():
    """receivables_days_target = 60 → AR = revenue × 60/90 ≈ 67% of revenue.
    Default (params.theta_ar = 0.15) would give AR = 15% of revenue."""
    firm = _base_firm()
    # Drive revenue: price × 0.85 × units_sold
    decisions = _base_decisions(receivables_days_target=60.0)
    outcome = _base_outcome(units=80)
    new_state, flows = post_quarter(firm, decisions, outcome, SimParams())
    expected_revenue = decisions.price * outcome.units_sold
    expected_ar = expected_revenue * 60.0 / 90.0  # no deposit_pct → 100% credit
    assert new_state.accounts_receivable == pytest.approx(expected_ar, rel=0.01)
    # Compare: default theta_ar=0.15 would give 0.15*rev = much smaller
    decisions_default = _base_decisions()
    new_default, _ = post_quarter(firm, decisions_default, outcome, SimParams())
    assert new_state.accounts_receivable > new_default.accounts_receivable


def test_dpo_higher_than_default_increases_ap():
    firm = _base_firm()
    decisions = _base_decisions(payables_days_target=90.0)
    outcome = _base_outcome(units=80)
    new_state, flows = post_quarter(firm, decisions, outcome, SimParams())
    # COGS = units_sold × effective_unit_cost; AP = COGS × 90/90 = COGS
    expected_ap = flows.cogs * 1.0  # 90/90 = 1.0
    assert new_state.accounts_payable == pytest.approx(expected_ap, rel=0.01)


def test_deposit_pct_reduces_ar_proportionally():
    """deposit_pct=0.4 → only 60% of revenue becomes AR (rest collected as cash).
    Stage 4 MVP: deferred_revenue balance stays 0 (deposits treated as
    immediately-earned cash revenue)."""
    firm = _base_firm()
    without_deposit = post_quarter(firm, _base_decisions(), _base_outcome(units=80),
                                    SimParams())
    with_deposit = post_quarter(firm, _base_decisions(deposit_pct=0.4),
                                  _base_outcome(units=80), SimParams())
    # AR under deposit is lower than without
    assert with_deposit[0].accounts_receivable < without_deposit[0].accounts_receivable
    # Ratio ~ 60% because 40% of revenue came in as cash
    assert with_deposit[0].accounts_receivable == pytest.approx(
        without_deposit[0].accounts_receivable * 0.6, rel=0.05
    )
    # Deferred revenue stays at 0 in the Stage 4 MVP simplification
    assert with_deposit[0].deferred_revenue == 0.0


# ── Stage 4: PP&E disposal ────────────────────────────────────────────────

def test_ppe_disposal_reduces_gross_and_accum():
    firm = _base_firm()
    # Sell $10M of PP&E (net book value ~$20M so disposal frac = 0.5)
    decisions = _base_decisions(ppe_disposal=10_000_000)
    outcome = _base_outcome(units=80)
    new_state, flows = post_quarter(firm, decisions, outcome, SimParams())
    # disposal_frac = 10M / 20M = 0.5 → gross reduced by 0.5*25M = 12.5M
    # plus capex adds 1M → end gross = 25 - 12.5 + 1 = 13.5M
    assert new_state.ppe_gross == pytest.approx(13_500_000, rel=0.05)
    # accum_dep reduced by 0.5*5M = 2.5M, plus new depreciation
    assert new_state.accum_depreciation < firm.accum_depreciation


def test_ppe_disposal_generates_cash_inflow():
    firm = _base_firm(cash=20_000_000)
    # Keep operating flows minimal; focus on disposal cash
    decisions = _base_decisions(ppe_disposal=5_000_000, capex=0,
                                 rd_spend=10_000_000, sga_spend=2_000_000,
                                 production=10, price=90_000)
    outcome = _base_outcome(units=10)
    new_state, flows = post_quarter(firm, decisions, outcome, SimParams())
    # CFI includes disposal proceeds
    assert flows.ppe_disposal_proceeds == 5_000_000
    assert flows.cfi > -1_000_000  # capex=0, disposal adds 5M


def test_ppe_disposal_gain_loss_recorded():
    """Set up a partial disposal where proceeds differ from NBV-of-sold-portion.
    Start: gross 40M, accum 10M → net 30M.
    Sell 15M worth (proceeds). disposal_frac = min(1.0, 15M / 30M) = 0.5.
    gross_sold = 20M, accum_sold = 5M → nbv_sold = 15M. Gain = 15M - 15M = 0.

    So use different fixture: gross 40M, accum 20M → net 20M. Sell 15M:
    disposal_frac = 0.75. gross_sold = 30M, accum_sold = 15M → nbv_sold = 15M.
    Gain = 15M - 15M = 0 again (proceeds = declared disposal value).

    The only way proceeds ≠ nbv_sold given current logic is if disposal exceeds
    net PP&E (capped at 100% frac, but proceeds = declared amount > nbv_sold)."""
    firm = FirmState(
        firm_id="firm_0", is_active=True, quarter=4,
        cash=100_000_000,
        accounts_receivable=15_000_000,
        inventory_units=50, inventory_value=3_000_000,
        ppe_gross=40_000_000, accum_depreciation=30_000_000,  # net = 10M
        common_stock=10_000, apic=149_990_000,
        retained_earnings=-10_000_000,
        shares_outstanding=10_000_000,
        capacity_units=150, base_unit_cost=14_000,
    )
    # Sell 15M of a 10M net asset — proceeds 15M > implied NBV → gain
    decisions = _base_decisions(ppe_disposal=15_000_000)
    outcome = _base_outcome(units=80)
    new_state, flows = post_quarter(firm, decisions, outcome, SimParams())
    # proceeds = 15M, nbv_sold = disposal_frac × net = 1.0 × 10M = 10M → gain 5M
    assert flows.ppe_disposal_gain_loss > 0


# ── Stage 4: no-op when toggles off ───────────────────────────────────────

def test_legacy_behavior_when_no_new_fields():
    """When no Stage 4 fields set, post_quarter produces identical result
    to pre-Stage-4 behavior (uses params.theta_ar / theta_ap)."""
    firm = _base_firm()
    # Explicitly not setting any Stage 4 fields
    decisions = _base_decisions()
    outcome = _base_outcome(units=80)
    new_state, flows = post_quarter(firm, decisions, outcome, SimParams())
    expected_revenue = decisions.price * outcome.units_sold
    # Legacy: AR = 0.15 * revenue
    assert new_state.accounts_receivable == pytest.approx(expected_revenue * 0.15,
                                                            rel=0.01)
    # Legacy: AP = 0.15 * COGS
    assert new_state.accounts_payable == pytest.approx(flows.cogs * 0.15, rel=0.01)
    assert new_state.deferred_revenue == 0.0


# ── Stage 5: allowance_pct_of_ar creates allowance ─────────────────────────

def test_allowance_pct_populates_allowance_contra_asset():
    firm = _base_firm()
    decisions = _base_decisions(allowance_pct_of_ar=0.05)  # 5% of gross AR
    outcome = _base_outcome(units=80)
    new_state, flows = post_quarter(firm, decisions, outcome, SimParams())
    expected_allowance = new_state.accounts_receivable * 0.05
    assert new_state.allowance_for_doubtful_accounts == pytest.approx(
        expected_allowance, rel=0.01
    )


def test_env_write_offs_reduce_gross_ar():
    firm = _base_firm(ar=10_000_000)
    # Start with no allowance
    decisions = _base_decisions(write_offs_this_quarter=500_000)
    outcome = _base_outcome(units=80)
    new_state, flows = post_quarter(firm, decisions, outcome, SimParams())
    # Gross AR reduced: new AR computed from revenue, then minus write-offs
    expected_revenue = decisions.price * outcome.units_sold
    ar_before_writeoff = expected_revenue * 0.15  # params default
    expected_ar = ar_before_writeoff - 500_000
    assert new_state.accounts_receivable == pytest.approx(expected_ar, rel=0.01)
    assert flows.write_offs_this_quarter == 500_000


def test_allowance_topup_drives_bad_debt_expense():
    """When firm increases allowance pct quarter-over-quarter, bad_debt_expense
    reflects the Δ. Starting with prior allowance=0, new allowance=5% of new AR."""
    firm = _base_firm()
    decisions = _base_decisions(allowance_pct_of_ar=0.05)
    outcome = _base_outcome(units=80)
    new_state, flows = post_quarter(firm, decisions, outcome, SimParams())
    # Prior allowance=0, new_allowance=5%*new_ar → bad_debt_expense = new_allowance
    assert flows.bad_debt_expense == pytest.approx(
        new_state.allowance_for_doubtful_accounts, rel=0.01
    )


def test_bad_debt_expense_hits_net_income():
    """Bad debt expense should reduce reported net income."""
    firm = _base_firm()
    with_bad_debt = post_quarter(firm,
                                   _base_decisions(allowance_pct_of_ar=0.10),
                                   _base_outcome(units=80), SimParams())
    without_bad_debt = post_quarter(firm, _base_decisions(),
                                      _base_outcome(units=80), SimParams())
    # NI is lower when bad debt is charged
    assert with_bad_debt[1].net_income < without_bad_debt[1].net_income


# ── Invariants still hold ─────────────────────────────────────────────────

def test_balance_sheet_identity_with_all_new_fields():
    """All Stage 4/5 fields active simultaneously — BS still balances."""
    firm = _base_firm()
    decisions = _base_decisions(
        receivables_days_target=45,
        payables_days_target=60,
        deposit_pct=0.2,
        ppe_disposal=3_000_000,
        allowance_pct_of_ar=0.03,
        write_offs_this_quarter=100_000,
    )
    outcome = _base_outcome(units=80)
    new_state, flows = post_quarter(firm, decisions, outcome, SimParams())
    violations = validate_state(new_state, flows, firm)
    # Any invariant violations would fail the test
    assert violations == [], f"Invariant violations: {violations}"


# ── Orchestrator: env write-offs flow through ─────────────────────────────

def test_orchestrator_env_write_offs_reach_accounting():
    """End-to-end: env returns write_offs list → orchestrator patches clamped
    decisions → accounting applies the write-off."""
    from src.orchestrator import WorldState, run_quarter
    from src.config import RunConfig

    state = WorldState(run_id="test")
    state.firms["firm_0"] = FirmState(
        firm_id="firm_0", is_active=True, cash=100_000_000,
        accounts_receivable=10_000_000,
        capacity_units=100, base_unit_cost=40_000,
        ppe_gross=25_000_000, shares_outstanding=10_000_000,
    )
    state.params = SimParams()
    config = RunConfig(bad_debt_enabled=True)

    def firm_fn(fid, firm, info, params):
        return RawDecisions(price=95_000, production=50, capex=0,
                             rd_spend=10_000_000,
                             rd_allocation={"product": 1.0, "process": 0, "delivery": 0},
                             sga_spend=2_000_000,
                             allowance_pct_of_ar=0.05)

    def env_fn(actions, firms, macro, params):
        return {
            "total_demand": 100,
            "firm_outcomes": {
                "firm_0": {"units_sold": 50, "market_share": 0.5}
            },
            "narrative": "test",
            "write_offs": [{"firm_id": "firm_0", "amount": 200_000}],
        }

    new_state = run_quarter(state, firm_agent_fn=firm_fn, env_agent_fn=env_fn,
                             config=config)
    # Write-off should show in log
    wo_logs = [m for m in new_state.quarter_log if "WRITE-OFF" in m.upper()]
    assert len(wo_logs) >= 1
    # And the firm's compustat row should reflect write-offs > 0
    firm_row = [r for r in new_state.compustat_rows if r.firm_id == "firm_0"][-1]
    assert firm_row.write_offs == 200_000
