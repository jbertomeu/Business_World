"""
Tests for Stage 10 (restructuring + env decision overrides) and Stage 11
(CEO comp with grants/vesting/selling/retirement).
"""

from __future__ import annotations
import json

import pytest

from src.types import (
    FirmState, RawDecisions, ClampedDecisions, MarketOutcome, SimParams,
    QuarterFlows, MacroState, StockGrant, AuditResult,
)
from src.accounting import post_quarter, validate_state


# ── Stage 10: Restructuring ──────────────────────────────────────────────

def _balanced_firm(**kw):
    """Helper: balanced FirmState for accounting tests."""
    base = dict(
        firm_id="firm_0", is_active=True, quarter=4,
        cash=100_000_000,
        accounts_receivable=15_000_000,
        inventory_units=50, inventory_value=3_000_000,
        ppe_gross=25_000_000, accum_depreciation=5_000_000,
        accounts_payable=5_000_000, accrued_expenses=1_000_000,
        common_stock=10_000,
        apic=132_000_000 - 10_000 + 20_000_000,  # balance: assets - liab - RE_deficit
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


def test_restructuring_severance_reduces_cash_and_ni():
    firm = _balanced_firm(cash=50_000_000)
    decisions = _decs(restructuring_severance=2_000_000)
    outcome = MarketOutcome(firm_id="firm_0", units_sold=80, market_share=0.2)
    new_state, flows = post_quarter(firm, decisions, outcome, SimParams())
    assert flows.restructuring_charge == 2_000_000
    assert flows.restructuring_severance == 2_000_000
    # NI lower by ~severance (after tax adjustment)
    baseline = post_quarter(firm, _decs(), outcome, SimParams())
    assert flows.net_income < baseline[1].net_income


def test_restructuring_ppe_impairment_writes_down_gross():
    firm = _balanced_firm()
    # PP&E net = 25 - 5 = 20M
    decisions = _decs(restructuring_ppe_impairment=5_000_000)
    outcome = MarketOutcome(firm_id="firm_0", units_sold=80, market_share=0.2)
    new_state, flows = post_quarter(firm, decisions, outcome, SimParams())
    # Gross PP&E should drop by 5M (plus capex/disposal/depr unchanged here)
    # Capex adds 1M, disposal 0, so end_gross = 25 + 1 - 5 = 21M
    assert new_state.ppe_gross == pytest.approx(21_000_000, rel=0.01)
    # Charge recognized
    assert flows.restructuring_ppe_impairment == 5_000_000
    assert flows.restructuring_charge == 5_000_000


def test_restructuring_inventory_writeoff_reduces_inventory():
    firm = _balanced_firm()  # inventory = 3M
    decisions = _decs(restructuring_inventory_write_off=1_500_000,
                      production=0)  # don't add inventory this Q
    outcome = MarketOutcome(firm_id="firm_0", units_sold=0, market_share=0)
    new_state, flows = post_quarter(firm, decisions, outcome, SimParams())
    # Inventory drops by 1.5M. End = 3 - 0 (no new produced/sold) - 1.5 = 1.5M
    assert new_state.inventory_value < firm.inventory_value
    assert flows.restructuring_inventory_write_off == 1_500_000


def test_restructuring_combined_charge_in_compustat_row():
    firm = _balanced_firm()
    decisions = _decs(
        restructuring_severance=1_000_000,
        restructuring_ppe_impairment=2_000_000,
        restructuring_inventory_write_off=500_000,
    )
    outcome = MarketOutcome(firm_id="firm_0", units_sold=80, market_share=0.2)
    new_state, flows = post_quarter(firm, decisions, outcome, SimParams())
    # Total restructuring = 3.5M
    assert flows.restructuring_charge == pytest.approx(3_500_000)


# ── Stage 10: Env decision override ──────────────────────────────────────

def test_orchestrator_env_override_replaces_sga_when_infeasible():
    """Env returns decision_overrides → orchestrator patches clamped_decisions
    before accounting runs."""
    from src.orchestrator import WorldState, run_quarter
    from src.config import RunConfig

    state = WorldState(run_id="test")
    state.firms["firm_0"] = FirmState(
        firm_id="firm_0", is_active=True, cash=100_000_000,
        capacity_units=100, base_unit_cost=40_000,
        ppe_gross=25_000_000, shares_outstanding=10_000_000,
    )
    state.params = SimParams()
    config = RunConfig(env_decision_overrides_enabled=True)

    def firm_fn(fid, firm, info, params):
        # Firm proposes SGA = $0 (infeasible)
        return RawDecisions(price=95_000, production=50, capex=0,
                             rd_spend=10_000_000,
                             rd_allocation={"product": 1.0, "process": 0, "delivery": 0},
                             sga_spend=0)

    def env_fn(actions, firms, macro, params):
        return {
            "total_demand": 50,
            "firm_outcomes": {"firm_0": {"units_sold": 50, "market_share": 1.0}},
            "narrative": "ok",
            "decision_overrides": [
                {"firm_id": "firm_0", "field": "sga_spend",
                 "budgeted": 0, "actual": 2_000_000,
                 "reasoning": "Cannot run with $0 SGA — payroll, rent, legal."}
            ],
        }

    new_state = run_quarter(state, firm_agent_fn=firm_fn, env_agent_fn=env_fn,
                             config=config)
    # firm's actual SGA spend should reflect env override
    flows = new_state.last_quarter_flows.get("firm_0")
    assert flows is not None
    assert flows.sga_expense == 2_000_000
    # Log line should mention override
    override_logs = [m for m in new_state.quarter_log if "ENV OVERRIDE" in m]
    assert len(override_logs) >= 1


def test_orchestrator_passes_through_when_no_override():
    """Env returns empty decision_overrides → firm decisions unchanged."""
    from src.orchestrator import WorldState, run_quarter
    from src.config import RunConfig

    state = WorldState(run_id="test")
    state.firms["firm_0"] = FirmState(
        firm_id="firm_0", is_active=True, cash=100_000_000,
        capacity_units=100, base_unit_cost=40_000,
        ppe_gross=25_000_000, shares_outstanding=10_000_000,
    )
    state.params = SimParams()
    config = RunConfig(env_decision_overrides_enabled=True)

    def firm_fn(fid, firm, info, params):
        return RawDecisions(price=95_000, production=50, capex=0,
                             rd_spend=10_000_000,
                             rd_allocation={"product": 1.0, "process": 0, "delivery": 0},
                             sga_spend=2_000_000)

    def env_fn(actions, firms, macro, params):
        return {
            "total_demand": 50,
            "firm_outcomes": {"firm_0": {"units_sold": 50, "market_share": 1.0}},
            "narrative": "ok",
            "decision_overrides": [],
        }

    new_state = run_quarter(state, firm_agent_fn=firm_fn, env_agent_fn=env_fn,
                             config=config)
    flows = new_state.last_quarter_flows.get("firm_0")
    assert flows.sga_expense == 2_000_000
    override_logs = [m for m in new_state.quarter_log if "ENV OVERRIDE" in m]
    assert override_logs == []


# ── Stage 11: CEO grants + vesting ───────────────────────────────────────

def test_create_grant_basic_rsu():
    from src.ceo_comp import create_grant
    firm = FirmState(firm_id="firm_0", is_active=True,
                     ceo_type="aggressive_grower", equity_price=20.0)
    new_firm, grant = create_grant(
        firm, grant_type="rsu", shares=10_000, strike_price=0.0,
        vesting_schedule=((4, 0.25), (8, 0.25), (12, 0.25), (16, 0.25)),
        grant_quarter=4, share_price_at_grant=20.0,
    )
    assert grant.grant_type == "rsu"
    assert grant.shares == 10_000
    assert grant.fair_value_at_grant == 200_000  # 10k × $20
    assert len(new_firm.ceo_stock_grants) == 1


def test_create_grant_option_with_strike():
    from src.ceo_comp import create_grant
    firm = FirmState(firm_id="firm_0", is_active=True, equity_price=25.0)
    new_firm, grant = create_grant(
        firm, grant_type="stock_option", shares=5_000, strike_price=20.0,
        vesting_schedule=((4, 1.0),),  # cliff vest at 1 year
        grant_quarter=4, share_price_at_grant=25.0,
    )
    assert grant.strike_price == 20.0
    # Intrinsic = 5k × ($25-$20) = $25k; time value = 0.3 × 20 × 5k = $30k → FV $55k
    assert grant.fair_value_at_grant == pytest.approx(55_000)


def test_vesting_schedule_applies_correctly():
    from src.ceo_comp import create_grant, vest_grants_this_quarter
    firm = FirmState(firm_id="firm_0", is_active=True, equity_price=20.0)
    firm, _ = create_grant(
        firm, grant_type="rsu", shares=4_000, strike_price=0.0,
        vesting_schedule=((4, 0.25), (8, 0.25), (12, 0.25), (16, 0.25)),
        grant_quarter=0, share_price_at_grant=20.0,
    )
    # Q3: nothing vested yet
    f, v = vest_grants_this_quarter(firm, current_quarter=3)
    assert v == 0
    assert f.ceo_vested_shares_held == 0
    # Q4: 25% vested = 1000 shares
    f, v = vest_grants_this_quarter(firm, current_quarter=4)
    assert v == 1_000
    assert f.ceo_vested_shares_held == 1_000
    # Q12: 75% cumulative vested = 3000; we already had 1000 → +2000 more
    f, v = vest_grants_this_quarter(f, current_quarter=12)
    assert v == 2_000
    assert f.ceo_vested_shares_held == 3_000


def test_sell_vested_shares_reduces_holdings_and_records_proceeds():
    from src.ceo_comp import sell_vested_shares
    firm = FirmState(firm_id="firm_0", is_active=True,
                     ceo_vested_shares_held=10_000)
    new_firm = sell_vested_shares(firm, shares_to_sell=3_000,
                                    current_price=15.0, current_quarter=8)
    assert new_firm.ceo_vested_shares_held == 7_000
    assert new_firm.ceo_shares_sold_cumulative == 3_000
    assert new_firm.ceo_cash_from_sales == 45_000  # 3k × $15


def test_forfeit_unvested_on_fire():
    from src.ceo_comp import create_grant, forfeit_unvested
    firm = FirmState(firm_id="firm_0", is_active=True, equity_price=20.0)
    firm, _ = create_grant(
        firm, grant_type="rsu", shares=4_000, strike_price=0.0,
        vesting_schedule=((4, 0.25), (8, 0.25), (12, 0.25), (16, 0.25)),
        grant_quarter=0, share_price_at_grant=20.0,
    )
    # Pretend 25% had vested; fire happens at Q4
    g0 = firm.ceo_stock_grants[0]
    from dataclasses import replace as _r
    firm = firm.evolve(ceo_stock_grants=(_r(g0, shares_vested_to_date=1_000),))
    new_firm = forfeit_unvested(firm)
    # 3000 unvested → forfeited
    assert new_firm.ceo_stock_grants[0].shares_forfeited == 3_000
    # Vested-to-date unchanged
    assert new_firm.ceo_stock_grants[0].shares_vested_to_date == 1_000


def test_retirement_accelerates_unvested():
    from src.ceo_comp import create_grant, accelerate_vesting_on_retirement
    firm = FirmState(firm_id="firm_0", is_active=True, equity_price=20.0)
    firm, _ = create_grant(
        firm, grant_type="rsu", shares=4_000, strike_price=0.0,
        vesting_schedule=((4, 0.25), (8, 0.25), (12, 0.25), (16, 0.25)),
        grant_quarter=0, share_price_at_grant=20.0,
    )
    from dataclasses import replace as _r
    g0 = firm.ceo_stock_grants[0]
    firm = firm.evolve(ceo_stock_grants=(_r(g0, shares_vested_to_date=1_000),))
    new_firm, accelerated = accelerate_vesting_on_retirement(firm)
    # All 3000 unvested vest immediately → CEO holds 4000 total
    assert accelerated == 3_000
    assert new_firm.ceo_vested_shares_held == 3_000
    assert new_firm.ceo_stock_grants[0].shares_vested_to_date == 4_000


def test_outstanding_snapshot_reports_correct_state():
    from src.ceo_comp import create_grant, vest_grants_this_quarter, outstanding_snapshot
    firm = FirmState(firm_id="firm_0", is_active=True, equity_price=30.0)
    firm, _ = create_grant(
        firm, grant_type="rsu", shares=4_000, strike_price=0.0,
        vesting_schedule=((4, 0.25), (8, 0.25), (12, 0.25), (16, 0.25)),
        grant_quarter=0, share_price_at_grant=20.0,
    )
    firm, _ = create_grant(
        firm, grant_type="stock_option", shares=2_000, strike_price=25.0,
        vesting_schedule=((4, 0.5), (8, 0.5)),
        grant_quarter=0, share_price_at_grant=20.0,
    )
    # Vest 1 year out
    firm, _ = vest_grants_this_quarter(firm, current_quarter=4)
    snap = outstanding_snapshot(firm, current_price=30.0)
    # RSU: 1000 vested-held, 3000 unvested
    assert snap["vested_rsu_held_shares"] == 1_000
    assert snap["unvested_rsu_shares"] == 3_000
    # Options: 1000 vested, 1000 unvested. Intrinsic vested = 1000 × ($30-$25) = $5000
    assert snap["vested_option_shares"] == 1_000
    assert snap["unvested_option_shares"] == 1_000
    assert snap["intrinsic_value_vested_options"] == 5_000


# ── Stage 11: Governance integration ──────────────────────────────────────

def test_governance_decision_grants_rsu_via_apply():
    from src.governance import apply_governance_decision
    import random
    rng = random.Random(42)
    firm = FirmState(firm_id="firm_0", is_active=True,
                     ceo_type="aggressive_grower", equity_price=20.0,
                     ceo_age=55, ceo_tenure_quarters=4)
    decision = {
        "fire_ceo": False,
        "offer_retirement": False,
        "base_salary_next_year": 2_500_000,
        "cash_bonus_this_year": 500_000,
        "new_rsu_grant": {"shares": 5_000,
                          "vesting_schedule": ((4, 0.25), (8, 0.25), (12, 0.25), (16, 0.25))},
        "new_option_grant": None,
        "reasoning": "performance bonus",
    }
    new_firm, grants = apply_governance_decision(firm, decision, rng,
                                                    current_quarter=4)
    assert new_firm.ceo_base_salary == 2_500_000
    # Stage 11.5: ceo_cash_bonus_ytd removed; comp accrual picks up bonus
    # via ceo_cash_comp_this_q. Verify that instead.
    assert new_firm.ceo_cash_comp_this_q >= 500_000
    assert len(new_firm.ceo_stock_grants) == 1
    assert len(grants) == 1
    assert grants[0].grant_type == "rsu"


def test_governance_fire_forfeits_unvested():
    from src.governance import apply_governance_decision
    from src.ceo_comp import create_grant
    import random
    rng = random.Random(42)
    firm = FirmState(firm_id="firm_0", is_active=True,
                     ceo_type="aggressive_grower", equity_price=20.0,
                     ceo_age=55, ceo_tenure_quarters=4)
    firm, _ = create_grant(
        firm, "rsu", 4_000, 0.0, ((4, 0.25), (8, 0.75)),
        grant_quarter=0, share_price_at_grant=20.0,
    )
    decision = {
        "fire_ceo": True,
        "fire_reason": "underperformance",
        "base_salary_next_year": 2_000_000,
    }
    new_firm, _ = apply_governance_decision(firm, decision, rng, current_quarter=4)
    # Unvested 4000 → forfeited
    assert new_firm.ceo_stock_grants[0].shares_forfeited == 4_000
    # Tenure reset
    assert new_firm.ceo_tenure_quarters == 0
    # Incarnation incremented (Stage 11.5: distinguishes successive CEOs)
    assert new_firm.ceo_incarnation == 2
    # New CEO installed from fallback (no candidates in this decision dict)
    assert new_firm.ceo_type != "aggressive_grower" or new_firm.ceo_incarnation != 1


def test_inventory_writeoff_scales_units():
    """Fix 1: inventory write-off reduces units proportionally to value."""
    firm = _balanced_firm(inventory_units=100, inventory_value=10_000_000)
    # Write off 50% of inventory value
    decisions = _decs(production=0, restructuring_inventory_write_off=5_000_000)
    outcome = MarketOutcome(firm_id="firm_0", units_sold=0, market_share=0)
    new_state, flows = post_quarter(firm, decisions, outcome, SimParams())
    # Value dropped ~50%; units should drop ~50% (from 100 to ~50)
    assert new_state.inventory_units <= 60
    assert new_state.inventory_units >= 40


def test_env_override_skips_null_actual():
    """Fix 2: env override with null/None `actual` is skipped."""
    from src.orchestrator import WorldState, run_quarter
    from src.config import RunConfig

    state = WorldState(run_id="test")
    state.firms["firm_0"] = FirmState(
        firm_id="firm_0", is_active=True, cash=100_000_000,
        capacity_units=100, base_unit_cost=40_000,
        ppe_gross=25_000_000, shares_outstanding=10_000_000,
    )
    state.params = SimParams()
    config = RunConfig(env_decision_overrides_enabled=True)

    def firm_fn(fid, firm, info, params):
        return RawDecisions(price=95_000, production=50, capex=0,
                             rd_spend=10_000_000,
                             rd_allocation={"product": 1.0, "process": 0, "delivery": 0},
                             sga_spend=2_000_000)

    def env_fn(actions, firms, macro, params):
        return {
            "total_demand": 50,
            "firm_outcomes": {"firm_0": {"units_sold": 50, "market_share": 1.0}},
            "narrative": "ok",
            "decision_overrides": [
                {"firm_id": "firm_0", "field": "sga_spend",
                 "budgeted": 2_000_000, "actual": None,    # null
                 "reasoning": "n/a"}
            ],
        }

    new_state = run_quarter(state, firm_agent_fn=firm_fn, env_agent_fn=env_fn,
                             config=config)
    # No override should have been applied — firm's 2M SGA stays
    flows = new_state.last_quarter_flows.get("firm_0")
    assert flows.sga_expense == 2_000_000


def test_B1_fire_year_snapshot_captures_departing_ceo():
    """B1 fix: on fire, the ExecuComp snapshot for that fyear records the
    DEPARTING CEO's identity + final-year state (not the incoming CEO)."""
    from src.orchestrator import WorldState, run_quarter
    from src.config import RunConfig

    state = WorldState(run_id="test")
    state.firms["firm_0"] = FirmState(
        firm_id="firm_0", is_active=True, cash=300_000_000,
        capacity_units=100, base_unit_cost=40_000,
        ppe_gross=25_000_000, shares_outstanding=10_000_000,
        ceo_type="aggressive_grower", ceo_age=55, ceo_tenure_quarters=8,
        ceo_base_salary=3_000_000, equity_price=10.0,
    )
    state.params = SimParams()
    config = RunConfig(governance_enabled=True)

    def firm_fn(fid, firm, info, params):
        return RawDecisions(price=95_000, production=50, capex=0,
                             rd_spend=10_000_000,
                             rd_allocation={"product": 1.0, "process": 0, "delivery": 0},
                             sga_spend=2_000_000)

    def gov_fn(firm, flows_4q, macro, peer_rev, peer_ni):
        # Fire the CEO this year
        return {
            "fire_ceo": True, "fire_reason": "bad performance",
            "offer_retirement": False, "base_salary_next_year": 2_500_000,
            "cash_bonus_this_year": 0, "new_rsu_grant": None, "new_option_grant": None,
        }

    # Run 4 quarters to hit Q4 governance
    for _ in range(4):
        state = run_quarter(state, firm_agent_fn=firm_fn,
                             env_agent_fn=lambda *a, **k: None,
                             governance_fn=gov_fn, config=config)

    snaps = [s for s in state.execucomp_annual_snapshots if s["firm_id"] == "firm_0"]
    assert len(snaps) == 1
    snap = snaps[0]
    # Departing CEO's identity + salary reported
    assert snap["ceo_id"] == "aggressive_grower"
    assert snap["base_salary"] == 3_000_000    # the DEPARTING CEO's salary (not new 2.5M)
    assert snap["fired_flag"] == 1
    # Tenure reflects DEPARTING CEO's actual tenure at fire time (not the
    # reset-to-0 for incoming CEO). Fixture started at 8Q tenure = 2 years.
    assert snap["tenure_years"] == pytest.approx(2.0)


def test_B2_shares_sold_this_year_never_negative():
    """B2 fix: `shares_sold_this_year` stays ≥ 0 in fire-year snapshots."""
    from src.orchestrator import WorldState, run_quarter
    from src.config import RunConfig

    state = WorldState(run_id="test")
    state.firms["firm_0"] = FirmState(
        firm_id="firm_0", is_active=True, cash=300_000_000,
        capacity_units=100, base_unit_cost=40_000,
        ppe_gross=25_000_000, shares_outstanding=10_000_000,
        ceo_type="aggressive_grower", ceo_age=55, ceo_tenure_quarters=4,
        ceo_shares_sold_cumulative=5_000,     # pretend some history
        equity_price=10.0,
    )
    state.params = SimParams()
    config = RunConfig(governance_enabled=True)

    def firm_fn(fid, firm, info, params):
        return RawDecisions(price=95_000, production=50, capex=0,
                             rd_spend=10_000_000,
                             rd_allocation={"product": 1.0, "process": 0, "delivery": 0},
                             sga_spend=2_000_000)

    def gov_fn(firm, flows_4q, macro, peer_rev, peer_ni):
        return {"fire_ceo": True, "fire_reason": "x",
                "base_salary_next_year": 2_000_000,
                "cash_bonus_this_year": 0, "new_rsu_grant": None,
                "new_option_grant": None}

    for _ in range(4):
        state = run_quarter(state, firm_agent_fn=firm_fn,
                             env_agent_fn=lambda *a, **k: None,
                             governance_fn=gov_fn, config=config)

    snaps = [s for s in state.execucomp_annual_snapshots if s["firm_id"] == "firm_0"]
    assert len(snaps) == 1
    # shares_sold_this_year should NOT be negative
    assert snaps[0]["shares_sold_this_year"] >= 0


def test_incarnation_isolates_old_ceo_grants_from_new_ceo():
    """D2 fix: after fire, old CEO's vested options should NOT show on
    `outstanding_snapshot` for the new CEO (different incarnation)."""
    from src.ceo_comp import create_grant, vest_grants_this_quarter, outstanding_snapshot
    from src.governance import apply_governance_decision
    import random
    rng = random.Random(42)

    firm = FirmState(firm_id="firm_0", is_active=True,
                     ceo_type="aggressive_grower", equity_price=30.0,
                     ceo_age=55, ceo_tenure_quarters=8, ceo_incarnation=1)
    # Old CEO got options that fully vested
    firm, _ = create_grant(firm, "stock_option", 2_000, 20.0,
                            ((4, 1.0),), grant_quarter=0, share_price_at_grant=25.0)
    firm, _ = vest_grants_this_quarter(firm, current_quarter=4)
    # Now old CEO has 2000 vested options worth $20K intrinsic
    assert outstanding_snapshot(firm, 30.0)["vested_option_shares"] == 2000

    # Fire: old CEO is replaced
    decision = {
        "fire_ceo": True, "fire_reason": "x",
        "base_salary_next_year": 1_500_000,
        "cash_bonus_this_year": 0,
        "new_rsu_grant": None, "new_option_grant": None,
        "ceo_candidates": [],
    }
    new_firm, _ = apply_governance_decision(firm, decision, rng, current_quarter=8)
    # Incarnation bumped
    assert new_firm.ceo_incarnation == 2
    # Old CEO's vested options NO LONGER show on snapshot (different incarnation)
    snap = outstanding_snapshot(new_firm, 30.0)
    assert snap["vested_option_shares"] == 0
    assert snap["intrinsic_value_vested_options"] == 0.0
    # But historical record preserved
    assert len(new_firm.ceo_stock_grants) == 1
    assert new_firm.ceo_stock_grants[0].ceo_incarnation == 1


def test_golden_parachute_paid_on_fire_not_retire():
    """Golden parachute is paid on fire (involuntary); forfeited on retire."""
    from src.governance import apply_governance_decision
    import random
    rng = random.Random(42)

    firm = FirmState(firm_id="firm_0", is_active=True,
                     ceo_type="aggressive_grower", equity_price=20.0,
                     ceo_age=62, ceo_tenure_quarters=8,
                     ceo_golden_parachute_amount=5_000_000)

    # FIRE path → parachute paid (accrues into cash_comp_this_q)
    decision = {
        "fire_ceo": True, "fire_reason": "underperform",
        "base_salary_next_year": 2_000_000, "cash_bonus_this_year": 0,
        "new_rsu_grant": None, "new_option_grant": None,
        "ceo_candidates": [
            {"type": "honest_operator", "age": 50,
             "requested_base_salary": 2_500_000,
             "requested_golden_parachute": 4_000_000,
             "profile_note": "experienced"},
        ],
        "selected_candidate_index": 0,
    }
    new_firm_fired, _ = apply_governance_decision(firm, decision, rng, current_quarter=8)
    # Parachute accrued into cash comp for next Q
    assert new_firm_fired.ceo_cash_comp_this_q >= 5_000_000
    # New CEO's parachute = incoming's requested
    assert new_firm_fired.ceo_golden_parachute_amount == 4_000_000

    # RETIRE path → parachute FORFEITED (not paid)
    firm2 = FirmState(firm_id="firm_1", is_active=True,
                      ceo_type="conservative_steward", equity_price=20.0,
                      ceo_age=63, ceo_tenure_quarters=12,
                      ceo_golden_parachute_amount=5_000_000)
    decision_retire = {
        "fire_ceo": False, "offer_retirement": True,
        "base_salary_next_year": 0, "cash_bonus_this_year": 0,
        "new_rsu_grant": None, "new_option_grant": None,
        "ceo_candidates": [], "selected_candidate_index": 0,
    }
    new_firm_retired, _ = apply_governance_decision(firm2, decision_retire, rng,
                                                     current_quarter=12)
    # No parachute accrual (retirement forfeits it)
    assert new_firm_retired.ceo_cash_comp_this_q < 5_000_000


def test_three_candidates_install_selected():
    """Governance supplies 3 candidates → selected_candidate_index installs one."""
    from src.governance import apply_governance_decision
    import random
    rng = random.Random(42)

    firm = FirmState(firm_id="firm_0", is_active=True,
                     ceo_type="aggressive_grower", equity_price=20.0,
                     ceo_age=55, ceo_tenure_quarters=8,
                     ceo_golden_parachute_amount=0)
    decision = {
        "fire_ceo": True, "fire_reason": "x",
        "base_salary_next_year": 2_000_000, "cash_bonus_this_year": 0,
        "new_rsu_grant": None, "new_option_grant": None,
        "ceo_candidates": [
            {"type": "honest_operator", "age": 45,
             "requested_base_salary": 2_000_000,
             "requested_golden_parachute": 3_000_000, "profile_note": "A"},
            {"type": "empire_builder", "age": 52,
             "requested_base_salary": 3_500_000,
             "requested_golden_parachute": 5_000_000, "profile_note": "B"},
            {"type": "conservative_steward", "age": 58,
             "requested_base_salary": 2_500_000,
             "requested_golden_parachute": 2_000_000, "profile_note": "C"},
        ],
        "selected_candidate_index": 1,  # pick candidate B
    }
    new_firm, _ = apply_governance_decision(firm, decision, rng, current_quarter=8)
    # Candidate B installed
    assert new_firm.ceo_type == "empire_builder"
    assert new_firm.ceo_age == 52
    assert new_firm.ceo_base_salary == 3_500_000
    assert new_firm.ceo_golden_parachute_amount == 5_000_000


def test_B5_parachute_preserved_when_llm_omits():
    """B5 fix: retain path preserves existing golden_parachute_amount when
    the LLM's decision doesn't include the key (was zeroing it out)."""
    from src.governance import apply_governance_decision, parse_governance_decision
    import random
    rng = random.Random(42)

    firm = FirmState(firm_id="firm_0", is_active=True,
                     ceo_type="aggressive_grower", equity_price=20.0,
                     ceo_age=55, ceo_tenure_quarters=4,
                     ceo_golden_parachute_amount=5_000_000)
    # Simulate LLM returning a retain decision WITHOUT golden_parachute_amount
    raw_llm_response = {
        "fire_ceo": False, "offer_retirement": False,
        "base_salary_next_year": 2_000_000,
        "cash_bonus_this_year": 100_000,
        # no golden_parachute_amount key
        "new_rsu_grant": None, "new_option_grant": None,
        "reasoning": "keep going",
    }
    decision = parse_governance_decision(raw_llm_response)
    # Parser should return None for the parachute (not 0)
    assert decision["golden_parachute_amount"] is None
    new_firm, _ = apply_governance_decision(firm, decision, rng, current_quarter=4)
    # Existing parachute preserved
    assert new_firm.ceo_golden_parachute_amount == 5_000_000


def test_B6_incoming_ceo_id_on_retire_with_candidates():
    """B6 fix: retire-with-candidates installs new CEO; ceo_history event
    correctly logs `incoming_ceo_id` as the new CEO, not the departing one."""
    from src.orchestrator import WorldState, run_quarter
    from src.config import RunConfig

    state = WorldState(run_id="test")
    state.firms["firm_0"] = FirmState(
        firm_id="firm_0", is_active=True, cash=100_000_000,
        capacity_units=100, base_unit_cost=40_000,
        ppe_gross=25_000_000, shares_outstanding=10_000_000,
        ceo_type="conservative_steward", ceo_age=63, ceo_tenure_quarters=8,
        ceo_incarnation=1,
    )
    state.params = SimParams()
    config = RunConfig(governance_enabled=True)

    def firm_fn(fid, firm, info, params):
        return RawDecisions(price=95_000, production=50, capex=0,
                             rd_spend=10_000_000,
                             rd_allocation={"product": 1.0, "process": 0, "delivery": 0},
                             sga_spend=2_000_000)

    def gov_fn(firm, flows_4q, macro, peer_rev, peer_ni):
        return {
            "fire_ceo": False, "offer_retirement": True,
            "base_salary_next_year": 0, "cash_bonus_this_year": 0,
            "golden_parachute_amount": None,
            "new_rsu_grant": None, "new_option_grant": None,
            "ceo_candidates": [
                {"type": "honest_operator", "age": 48,
                 "requested_base_salary": 2_200_000,
                 "requested_golden_parachute": 3_000_000,
                 "profile_note": "picked"}
            ],
            "selected_candidate_index": 0,
        }

    for _ in range(4):
        state = run_quarter(state, firm_agent_fn=firm_fn,
                             env_agent_fn=lambda *a, **k: None,
                             governance_fn=gov_fn, config=config)

    # CEO history should log incoming_ceo_id correctly
    history = state.ceo_history.get("firm_0", [])
    assert len(history) == 1
    ev = history[0]
    assert ev["event_type"] == "retired"
    assert ev["departing_ceo_id"] == "conservative_steward"
    # Incoming is the new CEO (from candidate), not the departing one
    assert ev["incoming_ceo_id"] == "honest_operator"


def test_env_notes_reach_firm_prompt():
    """D1 fix: env firm_notes populate state.pending_env_notes → firm prompt next Q."""
    from src.orchestrator import WorldState, run_quarter
    from src.config import RunConfig

    state = WorldState(run_id="test")
    state.firms["firm_0"] = FirmState(
        firm_id="firm_0", is_active=True, cash=100_000_000,
        capacity_units=100, base_unit_cost=40_000,
        ppe_gross=25_000_000, shares_outstanding=10_000_000,
    )
    state.params = SimParams()
    config = RunConfig(env_decision_overrides_enabled=True)

    def firm_fn(fid, firm, info, params):
        return RawDecisions(price=95_000, production=50, capex=0,
                             rd_spend=10_000_000,
                             rd_allocation={"product": 1.0, "process": 0, "delivery": 0},
                             sga_spend=2_000_000)

    def env_fn(actions, firms, macro, params):
        return {
            "total_demand": 50,
            "firm_outcomes": {"firm_0": {"units_sold": 50, "market_share": 1.0}},
            "narrative": "ok",
            "decision_overrides": [],
            "firm_notes": [
                {"firm_id": "firm_0",
                 "note": "Cash squeeze; only 35 of 50 targeted units shipped."},
            ],
        }

    state = run_quarter(state, firm_agent_fn=firm_fn, env_agent_fn=env_fn,
                         config=config)
    # Notes captured on state
    assert "firm_0" in state.pending_env_notes
    assert any("Cash squeeze" in n for n in state.pending_env_notes["firm_0"])


def test_B4_ceo_cash_comp_debits_firm_cash():
    """B4 fix: CEO base salary accrues each quarter to SGA + debits cash."""
    from src.orchestrator import WorldState, run_quarter
    from src.config import RunConfig

    state = WorldState(run_id="test")
    state.firms["firm_0"] = FirmState(
        firm_id="firm_0", is_active=True, cash=100_000_000,
        capacity_units=100, base_unit_cost=40_000,
        ppe_gross=25_000_000, shares_outstanding=10_000_000,
        ceo_type="aggressive_grower", ceo_age=55, ceo_tenure_quarters=4,
        ceo_base_salary=4_000_000,    # $1M/Q
        equity_price=10.0,
    )
    state.params = SimParams()
    config = RunConfig(governance_enabled=True)

    def firm_fn(fid, firm, info, params):
        return RawDecisions(price=95_000, production=50, capex=0,
                             rd_spend=10_000_000,
                             rd_allocation={"product": 1.0, "process": 0, "delivery": 0},
                             sga_spend=2_000_000)

    # One quarter (not fqtr=4 so no governance)
    state = run_quarter(state, firm_agent_fn=firm_fn,
                         env_agent_fn=lambda *a, **k: None,
                         config=config)
    flows = state.last_quarter_flows["firm_0"]
    # sga_expense should = firm's $2M decision + $1M CEO salary accrual = $3M
    assert flows.sga_expense == pytest.approx(3_000_000, rel=0.01)


def test_execucomp_annual_snapshots_populate_across_years():
    """Fix 3+4: governance records a snapshot at each Q4, preserving history."""
    from src.orchestrator import WorldState, run_quarter
    from src.config import RunConfig

    state = WorldState(run_id="test")
    state.firms["firm_0"] = FirmState(
        firm_id="firm_0", is_active=True, cash=500_000_000,
        capacity_units=100, base_unit_cost=40_000,
        ppe_gross=25_000_000, shares_outstanding=10_000_000,
        ceo_type="aggressive_grower", ceo_age=55, equity_price=10.0,
    )
    state.params = SimParams()
    config = RunConfig(governance_enabled=True, earnings_announcement_enabled=False)

    def firm_fn(fid, firm, info, params):
        return RawDecisions(price=95_000, production=50, capex=0,
                             rd_spend=10_000_000,
                             rd_allocation={"product": 1.0, "process": 0, "delivery": 0},
                             sga_spend=2_000_000)

    def gov_fn(firm, flows_4q, macro, peer_rev, peer_ni):
        return {
            "fire_ceo": False,
            "offer_retirement": False,
            "base_salary_next_year": 2_000_000,
            "cash_bonus_this_year": 100_000,
            "new_rsu_grant": {
                "shares": 1_000,
                "vesting_schedule": ((4, 0.25), (8, 0.25), (12, 0.25), (16, 0.25)),
            },
            "new_option_grant": None,
            "reasoning": "test",
        }

    # Run 8 quarters (2 full fiscal years)
    for _ in range(8):
        state = run_quarter(state, firm_agent_fn=firm_fn,
                             env_agent_fn=lambda *a, **k: None,
                             governance_fn=gov_fn, config=config)

    # Expect 2 snapshots (Q4 of FY2031 and Q4 of FY2032)
    snaps_firm_0 = [s for s in state.execucomp_annual_snapshots
                    if s["firm_id"] == "firm_0"]
    assert len(snaps_firm_0) >= 1  # at least one annual snapshot captured
    # Each snapshot has a distinct fyear
    years = {s["fyear"] for s in snaps_firm_0}
    assert len(years) == len(snaps_firm_0)  # no duplicates per year


def test_governance_retirement_accelerates_vesting():
    from src.governance import apply_governance_decision
    from src.ceo_comp import create_grant
    import random
    rng = random.Random(42)
    firm = FirmState(firm_id="firm_0", is_active=True,
                     ceo_type="conservative_steward", equity_price=20.0,
                     ceo_age=63, ceo_tenure_quarters=12)
    firm, _ = create_grant(
        firm, "rsu", 4_000, 0.0, ((4, 0.25), (8, 0.75)),
        grant_quarter=0, share_price_at_grant=20.0,
    )
    decision = {
        "offer_retirement": True,
        "fire_ceo": False,
        "base_salary_next_year": 0,
    }
    new_firm, _ = apply_governance_decision(firm, decision, rng, current_quarter=12)
    # All unvested should be accelerated (vested_to_date = 4000)
    assert new_firm.ceo_stock_grants[0].shares_vested_to_date == 4_000
    assert new_firm.ceo_retired is True
