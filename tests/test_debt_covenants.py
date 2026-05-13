"""
Tests for Stage 3a + 3b debt covenant machinery.

Stage 3a: debt_management module (pure Python — facility lifecycle, amortization,
covenant testing, waiver/amendment/acceleration, conversion, consistency).

Stage 3b: orchestrator wiring — when debt_covenants_enabled=True, the three new
phases (amortize, test_covenants, consistency_check) execute correctly on firm
state with facilities, and are no-ops when no facilities exist.
"""

from __future__ import annotations

import pytest

from src.types import (
    FirmState, DebtFacility, Covenant, CovenantViolationEvent,
    MacroState, SimParams, ClampedDecisions, MarketOutcome,
)
from src.debt_management import (
    add_facility, prepay_facility, draw_revolver,
    amortize_quarter, compute_ratios,
    test_covenants as run_covenant_tests,  # aliased: pytest collects fns prefixed test_
    apply_waiver, apply_amendment, apply_acceleration,
    convert_facility, consistency_check,
    VALID_FACILITY_TYPES, VALID_COVENANT_TYPES,
)


# ── Stage 3a: add_facility ────────────────────────────────────────────────

def test_add_facility_basic_bank_term():
    firm = FirmState(firm_id="firm_0", is_active=True, cash=100_000_000)
    fac = DebtFacility(
        facility_id="",  # will be auto-assigned
        firm_id="firm_0",
        facility_type="bank_term",
        original_principal=50_000_000,
        current_balance=50_000_000,
        coupon_rate_quarterly=0.02,
        origination_quarter=1,
        maturity_quarter=21,
        amortization_type="bullet",
    )
    new_firm = add_facility(firm, fac)
    assert len(new_firm.debt_facilities) == 1
    assert new_firm.debt_facilities[0].facility_id.startswith("firm_0-FAC-")
    assert new_firm.cash == 100_000_000 + 50_000_000  # cash increased
    assert new_firm.long_term_debt == 50_000_000


def test_add_facility_revolver_does_not_increase_cash():
    firm = FirmState(firm_id="firm_0", is_active=True, cash=10_000_000)
    fac = DebtFacility(
        facility_id="", firm_id="firm_0",
        facility_type="bank_revolver",
        original_principal=25_000_000,
        current_balance=0.0,  # undrawn at origination
        coupon_rate_quarterly=0.015,
        origination_quarter=1, maturity_quarter=17,
        amortization_type="revolver",
    )
    new_firm = add_facility(firm, fac)
    assert new_firm.cash == 10_000_000  # undrawn: no cash impact
    assert new_firm.revolver_balance == 0.0


def test_add_facility_rejects_invalid_type():
    firm = FirmState(firm_id="firm_0", is_active=True)
    fac = DebtFacility(
        facility_id="", firm_id="firm_0",
        facility_type="junk_bond_weird",  # invalid
        original_principal=10_000_000, current_balance=10_000_000,
        coupon_rate_quarterly=0.03,
        origination_quarter=1, maturity_quarter=17,
        amortization_type="bullet",
    )
    with pytest.raises(ValueError, match="Invalid facility_type"):
        add_facility(firm, fac)


def test_add_facility_rejects_over_max_active():
    firm = FirmState(firm_id="firm_0", is_active=True, cash=500_000_000)
    for i in range(10):
        fac = DebtFacility(
            facility_id="", firm_id="firm_0",
            facility_type="bank_term",
            original_principal=1_000_000, current_balance=1_000_000,
            coupon_rate_quarterly=0.02,
            origination_quarter=1, maturity_quarter=21,
            amortization_type="bullet",
        )
        firm = add_facility(firm, fac, max_active=10)
    assert len(firm.debt_facilities) == 10
    # 11th should fail
    extra = DebtFacility(
        facility_id="", firm_id="firm_0",
        facility_type="bank_term",
        original_principal=1_000_000, current_balance=1_000_000,
        coupon_rate_quarterly=0.02,
        origination_quarter=1, maturity_quarter=21,
        amortization_type="bullet",
    )
    with pytest.raises(ValueError, match="max"):
        add_facility(firm, extra, max_active=10)


# ── Stage 3a: amortize_quarter ────────────────────────────────────────────

def test_amortize_accrues_interest_and_pays_cash():
    firm = FirmState(firm_id="firm_0", is_active=True, cash=0)
    fac = DebtFacility(
        facility_id="", firm_id="firm_0",
        facility_type="bank_term",
        original_principal=100_000_000, current_balance=100_000_000,
        coupon_rate_quarterly=0.025,  # 10% annual
        origination_quarter=1, maturity_quarter=21,
        amortization_type="bullet",
    )
    firm = add_facility(firm, fac)
    assert firm.cash == 100_000_000
    new_firm, interest, principal = amortize_quarter(firm, current_quarter=2)
    # 100M * 2.5% = 2.5M interest for the quarter
    assert interest == pytest.approx(2_500_000)
    assert new_firm.cash == pytest.approx(100_000_000 - 2_500_000)
    # Bullet: balance unchanged until maturity
    assert new_firm.debt_facilities[0].current_balance == 100_000_000


def test_amortize_bullet_maturity_repays():
    firm = FirmState(firm_id="firm_0", is_active=True, cash=0)
    fac = DebtFacility(
        facility_id="", firm_id="firm_0",
        facility_type="bank_term",
        original_principal=50_000_000, current_balance=50_000_000,
        coupon_rate_quarterly=0.02,
        origination_quarter=1, maturity_quarter=5,
        amortization_type="bullet",
    )
    firm = add_facility(firm, fac)  # cash now 50M
    # At quarter 5 (maturity), firm has 50M cash. Interest takes 1M.
    # Remaining 49M → tries to pay 50M principal, can only pay 49M.
    new_firm, interest, principal = amortize_quarter(firm, current_quarter=5)
    assert interest == pytest.approx(1_000_000)
    # Could pay 49M toward 50M principal; 1M short → in_cure_period
    assert new_firm.debt_facilities[0].status == "in_cure_period"
    assert new_firm.debt_facilities[0].current_balance == pytest.approx(1_000_000)


def test_amortize_amortizing_pays_scheduled_principal():
    firm = FirmState(firm_id="firm_0", is_active=True, cash=0)
    fac = DebtFacility(
        facility_id="", firm_id="firm_0",
        facility_type="bank_term",
        original_principal=20_000_000, current_balance=20_000_000,
        coupon_rate_quarterly=0.01,  # 4% annual
        origination_quarter=1, maturity_quarter=21,  # 20 quarters remaining
        amortization_type="amortizing",
    )
    firm = add_facility(firm, fac)  # cash=20M
    new_firm, interest, principal = amortize_quarter(firm, current_quarter=2)
    # Interest: 20M * 1% = 200k
    # Scheduled principal: 20M / 19 remaining quarters ≈ 1.053M
    assert interest == pytest.approx(200_000)
    new_balance = new_firm.debt_facilities[0].current_balance
    assert new_balance < 20_000_000
    assert new_balance > 18_500_000  # roughly 20M - 1.05M


# ── Stage 3a: test_covenants ──────────────────────────────────────────────

def test_covenant_max_debt_to_ebitda_violation():
    firm = FirmState(
        firm_id="firm_0", is_active=True,
        long_term_debt=200_000_000, revolver_balance=0,
    )
    cov = Covenant(
        covenant_type="max_debt_to_ebitda",
        threshold=5.0,
        test_frequency="quarterly",
    )
    fac = DebtFacility(
        facility_id="F1", firm_id="firm_0",
        facility_type="bank_term",
        original_principal=200_000_000, current_balance=200_000_000,
        coupon_rate_quarterly=0.025,
        origination_quarter=1, maturity_quarter=21,
        amortization_type="bullet",
        covenants=(cov,),
    )
    firm = firm.evolve(debt_facilities=(fac,))
    # TTM EBITDA = 20M → debt/EBITDA = 10x → violated
    violations = run_covenant_tests(firm, ttm_ebitda=20_000_000, ttm_interest=2_000_000)
    assert len(violations) == 1
    assert violations[0]["covenant_type"] == "max_debt_to_ebitda"
    assert violations[0]["measured_ratio"] == 10.0


def test_covenant_min_interest_coverage_not_violated():
    firm = FirmState(firm_id="firm_0", is_active=True)
    cov = Covenant(
        covenant_type="min_interest_coverage",
        threshold=2.0,
        test_frequency="quarterly",
    )
    fac = DebtFacility(
        facility_id="F1", firm_id="firm_0",
        facility_type="bank_term",
        original_principal=10_000_000, current_balance=10_000_000,
        coupon_rate_quarterly=0.02,
        origination_quarter=1, maturity_quarter=21,
        amortization_type="bullet",
        covenants=(cov,),
    )
    firm = firm.evolve(debt_facilities=(fac,))
    # EBITDA/interest = 10M/2M = 5x ≥ 2x threshold → no violation
    violations = run_covenant_tests(firm, ttm_ebitda=10_000_000, ttm_interest=2_000_000)
    assert len(violations) == 0


# ── Stage 3a: waiver / amendment / acceleration ───────────────────────────

def test_apply_waiver_clears_violation_and_charges_fee():
    firm = FirmState(firm_id="firm_0", is_active=True, cash=10_000_000)
    cov = Covenant(covenant_type="max_debt_to_ebitda", threshold=5.0,
                   currently_violated=True, quarters_in_violation=1)
    fac = DebtFacility(
        facility_id="F1", firm_id="firm_0",
        facility_type="bank_term",
        original_principal=50_000_000, current_balance=50_000_000,
        coupon_rate_quarterly=0.02,
        origination_quarter=1, maturity_quarter=21,
        amortization_type="bullet",
        covenants=(cov,), status="in_cure_period",
    )
    firm = firm.evolve(debt_facilities=(fac,))
    new_firm, event = apply_waiver(firm, "F1", "max_debt_to_ebitda",
                                    waiver_fee=250_000, quarter=3)
    assert new_firm.cash == pytest.approx(10_000_000 - 250_000)
    assert new_firm.debt_facilities[0].status == "current"
    assert new_firm.debt_facilities[0].covenants[0].currently_violated is False
    assert event.resolution == "waived"


def test_H1_unresolved_violations_requeue():
    """H1 regression: when resolver returns fewer resolutions than pending
    violations, unresolved ones survive in state.pending_covenant_violations
    for next quarter (not silently dropped)."""
    from src.orchestrator import WorldState, run_quarter
    from src.config import RunConfig
    from src.types import SimParams, RawDecisions, CompustatRow

    state = WorldState(run_id="test")
    # Firm with a facility + 2 covenants, both violating
    cov1 = Covenant(covenant_type="min_cash_balance", threshold=200_000_000)
    cov2 = Covenant(covenant_type="min_net_worth", threshold=200_000_000)
    fac = DebtFacility(
        facility_id="F1", firm_id="firm_0",
        facility_type="bank_term",
        original_principal=50_000_000, current_balance=50_000_000,
        coupon_rate_quarterly=0.02,
        origination_quarter=0, maturity_quarter=21,
        amortization_type="bullet",
        covenants=(cov1, cov2),
    )
    state.firms["firm_0"] = FirmState(
        firm_id="firm_0", is_active=True, cash=10_000_000,
        capacity_units=100, base_unit_cost=40_000,
        ppe_gross=25_000_000, shares_outstanding=10_000_000,
        debt_facilities=(fac,), long_term_debt=50_000_000,
    )
    state.params = SimParams()
    state.compustat_rows.append(CompustatRow(
        run_id="r", firm_id="firm_0", fyearq=2030, fqtr=4,
        niq=-5_000_000,
    ))
    config = RunConfig(debt_covenants_enabled=True)

    def firm_fn(fid, firm, info, params):
        return RawDecisions(price=95_000, production=50, capex=0,
                             rd_spend=10_000_000,
                             rd_allocation={"product": 1.0, "process": 0, "delivery": 0},
                             sga_spend=0)

    def resolver(violations, firms, macro):
        # Resolve only the first, silently skip the second
        if not violations:
            return []
        v = violations[0]
        return [{"firm_id": v["firm_id"], "facility_id": v["facility_id"],
                 "covenant_type": v["covenant_type"], "action": "waive",
                 "waiver_fee": 10_000, "new_threshold": 0,
                 "new_rate_quarterly": 0, "reasoning": "ok"}]

    new_state = run_quarter(state, firm_agent_fn=firm_fn,
                             env_agent_fn=lambda *a, **k: None,
                             violation_resolver_fn=resolver, config=config)
    # The unresolved second violation should be in the queue for next quarter
    assert len(new_state.pending_covenant_violations) >= 1, (
        f"expected unresolved violations to survive; "
        f"got {new_state.pending_covenant_violations}"
    )


def test_H4_accelerated_residual_transitions_to_defaulted():
    """H4 completion: an accelerated facility with residual balance transitions
    to `defaulted` at end of quarter (was stuck in `accelerated` forever)."""
    from src.orchestrator import WorldState, run_quarter
    from src.types import SimParams, RawDecisions
    from src.config import RunConfig

    state = WorldState(run_id="test")
    fac = DebtFacility(
        facility_id="F1", firm_id="firm_0",
        facility_type="bank_term",
        original_principal=50_000_000,
        current_balance=20_000_000,   # unpaid residual
        coupon_rate_quarterly=0.02,
        origination_quarter=1, maturity_quarter=21,
        amortization_type="bullet",
        status="accelerated",
    )
    state.firms["firm_0"] = FirmState(
        firm_id="firm_0", is_active=True, cash=50_000_000,  # positive cash
        capacity_units=100, base_unit_cost=40_000,
        ppe_gross=25_000_000, shares_outstanding=10_000_000,
        debt_facilities=(fac,), long_term_debt=20_000_000,
    )
    state.params = SimParams()
    config = RunConfig(debt_covenants_enabled=True)

    def firm_fn(fid, firm, info, params):
        return RawDecisions(price=95_000, production=50, capex=0,
                             rd_spend=10_000_000,
                             rd_allocation={"product": 1.0, "process": 0, "delivery": 0},
                             sga_spend=2_000_000)

    new_state = run_quarter(state, firm_agent_fn=firm_fn,
                             env_agent_fn=lambda *a, **k: None,
                             config=config)
    # Accelerated residual → defaulted
    assert new_state.firms["firm_0"].debt_facilities[0].status == "defaulted"


def test_H4_accelerated_facility_stops_accruing_interest():
    """H4 regression: an accelerated facility with residual balance should
    not keep accruing interest on subsequent quarters."""
    fac = DebtFacility(
        facility_id="F1", firm_id="firm_0",
        facility_type="bank_term",
        original_principal=50_000_000, current_balance=30_000_000,  # partial after accel
        coupon_rate_quarterly=0.02,
        origination_quarter=1, maturity_quarter=21,
        amortization_type="bullet",
        status="accelerated",   # already accelerated
    )
    firm = FirmState(
        firm_id="firm_0", is_active=True, cash=5_000_000,
        debt_facilities=(fac,), long_term_debt=30_000_000,
    )
    new_firm, interest, principal = amortize_quarter(firm, current_quarter=5)
    # Accelerated facility is skipped — no interest, no principal, no state change
    assert interest == 0
    assert principal == 0
    assert new_firm.debt_facilities[0].current_balance == 30_000_000


def test_M4_convertible_sanity_rejects_absurd_ratio():
    """M4: add_facility rejects convertible bonds with conversion_ratio > 1000."""
    firm = FirmState(firm_id="firm_0", is_active=True, cash=10_000_000)
    bad_conv = DebtFacility(
        facility_id="", firm_id="firm_0",
        facility_type="convertible_bond",
        original_principal=10_000_000, current_balance=10_000_000,
        coupon_rate_quarterly=0.01,
        origination_quarter=1, maturity_quarter=41,
        amortization_type="bullet",
        conversion_ratio=10_000,  # absurd
        conversion_price=1.0,
    )
    with pytest.raises(ValueError, match="implausibly dilutive"):
        add_facility(firm, bad_conv)


def test_apply_amendment_clamps_absurd_rate():
    """Regression test: validation v3 showed an LLM resolver returned
    new_rate_quarterly=7.0 (likely meaning 7% annual, not 700% quarterly).
    apply_amendment must clamp to a sane range so a single LLM unit-confusion
    doesn't poison interest accrual for the rest of the simulation."""
    firm = FirmState(firm_id="firm_0", is_active=True, cash=10_000_000)
    cov = Covenant(covenant_type="max_debt_to_ebitda", threshold=4.0,
                   currently_violated=True)
    fac = DebtFacility(
        facility_id="F1", firm_id="firm_0",
        facility_type="bank_term",
        original_principal=50_000_000, current_balance=50_000_000,
        coupon_rate_quarterly=0.02,    # 8% annual baseline
        origination_quarter=1, maturity_quarter=21,
        amortization_type="bullet",
        covenants=(cov,), status="in_cure_period",
    )
    firm = firm.evolve(debt_facilities=(fac,))
    new_firm, event = apply_amendment(firm, "F1", "max_debt_to_ebitda",
                                       new_threshold=7.0, new_rate=7.0,  # absurd!
                                       quarter=4)
    # Clamped to 1.0 quarterly (safety clamp — 7.0 is obvious unit-confusion).
    assert new_firm.debt_facilities[0].coupon_rate_quarterly == 1.0


def test_apply_amendment_relaxes_threshold():
    firm = FirmState(firm_id="firm_0", is_active=True, cash=5_000_000)
    cov = Covenant(covenant_type="max_debt_to_ebitda", threshold=4.0,
                   currently_violated=True)
    fac = DebtFacility(
        facility_id="F1", firm_id="firm_0",
        facility_type="bank_term",
        original_principal=30_000_000, current_balance=30_000_000,
        coupon_rate_quarterly=0.02,
        origination_quarter=1, maturity_quarter=21,
        amortization_type="bullet",
        covenants=(cov,), status="in_cure_period",
    )
    firm = firm.evolve(debt_facilities=(fac,))
    new_firm, event = apply_amendment(firm, "F1", "max_debt_to_ebitda",
                                       new_threshold=7.0, new_rate=0.025,
                                       quarter=4)
    assert new_firm.debt_facilities[0].covenants[0].threshold == 7.0
    assert new_firm.debt_facilities[0].coupon_rate_quarterly == 0.025
    assert new_firm.debt_facilities[0].status == "amended"


# ── Stage 3a: convertible bond conversion ─────────────────────────────────

def test_convert_facility_creates_shares_and_zeros_debt():
    firm = FirmState(firm_id="firm_0", is_active=True,
                     shares_outstanding=10_000_000, apic=0)
    fac = DebtFacility(
        facility_id="F_CONV", firm_id="firm_0",
        facility_type="convertible_bond",
        original_principal=10_000_000, current_balance=10_000_000,
        coupon_rate_quarterly=0.01,
        origination_quarter=1, maturity_quarter=41,
        amortization_type="bullet",
        conversion_ratio=40.0,  # 40 shares per $1000 face
        conversion_price=25.0,
    )
    firm = firm.evolve(debt_facilities=(fac,), long_term_debt=10_000_000)
    new_firm, info = convert_facility(firm, "F_CONV", quarter=8)
    # 10M face / 1000 * 40 = 400k new shares
    assert info["new_shares"] == 400_000
    assert new_firm.shares_outstanding == 10_400_000
    assert new_firm.apic == 10_000_000
    assert new_firm.debt_facilities[0].status == "converted"
    assert new_firm.debt_facilities[0].current_balance == 0.0
    assert new_firm.long_term_debt == 0


# ── Stage 3a: consistency_check ───────────────────────────────────────────

def test_consistency_check_clean_passes():
    firm = FirmState(firm_id="firm_0", is_active=True)
    fac = DebtFacility(
        facility_id="F1", firm_id="firm_0",
        facility_type="bank_term",
        original_principal=20_000_000, current_balance=20_000_000,
        coupon_rate_quarterly=0.02,
        origination_quarter=1, maturity_quarter=21,
        amortization_type="bullet",
    )
    firm = firm.evolve(debt_facilities=(fac,), long_term_debt=20_000_000)
    assert consistency_check(firm) == []


def test_consistency_check_detects_ltd_mismatch():
    firm = FirmState(firm_id="firm_0", is_active=True)
    fac = DebtFacility(
        facility_id="F1", firm_id="firm_0",
        facility_type="bank_term",
        original_principal=20_000_000, current_balance=20_000_000,
        coupon_rate_quarterly=0.02,
        origination_quarter=1, maturity_quarter=21,
        amortization_type="bullet",
    )
    # Intentionally desync: facility says 20M, firm.long_term_debt says 5M
    firm = firm.evolve(debt_facilities=(fac,), long_term_debt=5_000_000)
    issues = consistency_check(firm)
    assert any("LTD mismatch" in msg for msg in issues)


# ── Stage 3b: orchestrator wiring ─────────────────────────────────────────

def test_orchestrator_phase_noop_when_no_facilities():
    """When debt_covenants_enabled=True but no facilities exist on any firm,
    the new phases run and log nothing — true no-op."""
    from src.orchestrator import WorldState, run_quarter
    from src.types import SimParams
    from src.config import RunConfig

    state = WorldState(run_id="test")
    state.firms["firm_0"] = FirmState(
        firm_id="firm_0", is_active=True, cash=200_000_000,
        capacity_units=100, base_unit_cost=40_000,
        ppe_gross=25_000_000, shares_outstanding=10_000_000,
    )
    state.params = SimParams()
    config = RunConfig(debt_covenants_enabled=True)

    # Minimal agent stubs — firm makes neutral decisions, env gives fallback
    from src.types import RawDecisions
    def firm_fn(fid, firm, info, params):
        return RawDecisions(price=95_000, production=50,
                             capex=0, rd_spend=10_000_000,
                             rd_allocation={"product": 1.0, "process": 0, "delivery": 0},
                             sga_spend=2_000_000)
    new_state = run_quarter(state, firm_agent_fn=firm_fn, env_agent_fn=lambda *a, **k: None,
                             config=config)
    # Should complete without errors; no facilities → no covenant warnings
    assert new_state.pending_covenant_violations == []
    debt_logs = [m for m in new_state.quarter_log
                 if "COVENANT" in m or "CONSISTENCY" in m or "facility interest" in m]
    assert debt_logs == []


def test_orchestrator_amortizes_facility_when_enabled():
    """With a facility on a firm and debt_covenants_enabled=True, the orchestrator
    amortize phase should actually accrue interest."""
    from src.orchestrator import WorldState, run_quarter
    from src.types import SimParams, RawDecisions
    from src.config import RunConfig

    state = WorldState(run_id="test")
    # Firm with $50M facility at 2%/Q
    fac = DebtFacility(
        facility_id="F1", firm_id="firm_0",
        facility_type="bank_term",
        original_principal=50_000_000, current_balance=50_000_000,
        coupon_rate_quarterly=0.02,
        origination_quarter=1, maturity_quarter=21,
        amortization_type="bullet",
    )
    state.firms["firm_0"] = FirmState(
        firm_id="firm_0", is_active=True, cash=200_000_000,
        capacity_units=100, base_unit_cost=40_000,
        ppe_gross=25_000_000, shares_outstanding=10_000_000,
        debt_facilities=(fac,), long_term_debt=50_000_000,
    )
    state.params = SimParams()
    config = RunConfig(debt_covenants_enabled=True)

    def firm_fn(fid, firm, info, params):
        return RawDecisions(price=95_000, production=50,
                             capex=0, rd_spend=10_000_000,
                             rd_allocation={"product": 1.0, "process": 0, "delivery": 0},
                             sga_spend=2_000_000)

    new_state = run_quarter(state, firm_agent_fn=firm_fn, env_agent_fn=lambda *a, **k: None,
                             config=config)
    # Look for amortization log line (orchestrator logs "facility serviced ...")
    amort_logs = [m for m in new_state.quarter_log if "facility serviced" in m]
    assert len(amort_logs) >= 1, f"expected amortize log line; got: {new_state.quarter_log}"


def test_orchestrator_phase_skipped_when_toggle_off():
    """When debt_covenants_enabled=False, debt phases skip entirely even if a
    facility exists on the firm (backward compat)."""
    from src.orchestrator import WorldState, run_quarter
    from src.types import SimParams, RawDecisions
    from src.config import RunConfig

    state = WorldState(run_id="test")
    fac = DebtFacility(
        facility_id="F1", firm_id="firm_0",
        facility_type="bank_term",
        original_principal=50_000_000, current_balance=50_000_000,
        coupon_rate_quarterly=0.02,
        origination_quarter=1, maturity_quarter=21,
        amortization_type="bullet",
    )
    state.firms["firm_0"] = FirmState(
        firm_id="firm_0", is_active=True, cash=200_000_000,
        capacity_units=100, base_unit_cost=40_000,
        ppe_gross=25_000_000, shares_outstanding=10_000_000,
        debt_facilities=(fac,), long_term_debt=50_000_000,
    )
    state.params = SimParams()
    config = RunConfig(debt_covenants_enabled=False)  # toggle off

    def firm_fn(fid, firm, info, params):
        return RawDecisions(price=95_000, production=50,
                             capex=0, rd_spend=10_000_000,
                             rd_allocation={"product": 1.0, "process": 0, "delivery": 0},
                             sga_spend=2_000_000)

    new_state = run_quarter(state, firm_agent_fn=firm_fn, env_agent_fn=lambda *a, **k: None,
                             config=config)
    amort_logs = [m for m in new_state.quarter_log if "facility interest" in m]
    covenant_logs = [m for m in new_state.quarter_log if "COVENANT" in m]
    assert amort_logs == []
    assert covenant_logs == []


# ── Stage 3c: LLM-driven origination + violation resolution ────────────────

def test_orchestrator_origination_creates_facility_from_ib_structure():
    """When debt_covenants_enabled and IB returns facility_structure,
    orchestrator wraps the approved debt as a DebtFacility via add_facility."""
    from src.orchestrator import WorldState, run_quarter
    from src.types import SimParams, RawDecisions
    from src.config import RunConfig

    state = WorldState(run_id="test")
    state.firms["firm_0"] = FirmState(
        firm_id="firm_0", is_active=True, cash=200_000_000,
        capacity_units=100, base_unit_cost=40_000,
        ppe_gross=25_000_000, shares_outstanding=10_000_000,
    )
    state.params = SimParams()
    config = RunConfig(debt_covenants_enabled=True)

    def firm_fn(fid, firm, info, params):
        return RawDecisions(price=95_000, production=50,
                             capex=0, rd_spend=10_000_000,
                             rd_allocation={"product": 1.0, "process": 0, "delivery": 0},
                             sga_spend=2_000_000,
                             debt_request=50_000_000)  # firm asks for debt

    def ib_fn(firms, macro, params, raw_decisions):
        """Stub IB that approves with full facility structure."""
        return {
            "firm_0": {
                "term_debt_approved": 50_000_000,
                "term_debt_rate": 0.025,
                "equity_approved": 0,
                "equity_price": 0,
                "debt_reasoning": "test approval",
                "equity_reasoning": "",
                "facility_structure": {
                    "facility_type": "bank_term",
                    "amortization_type": "bullet",
                    "maturity_quarters": 20,
                    "covenants": [
                        {"covenant_type": "max_debt_to_ebitda", "threshold": 5.0}
                    ],
                    "conversion_ratio": 0.0,
                    "conversion_price": 0.0,
                }
            }
        }

    new_state = run_quarter(state, firm_agent_fn=firm_fn,
                             env_agent_fn=lambda *a, **k: None,
                             investment_bank_fn=ib_fn, config=config)
    firm = new_state.firms["firm_0"]
    # Expect exactly one facility on the firm
    assert len(firm.debt_facilities) == 1
    fac = firm.debt_facilities[0]
    assert fac.facility_type == "bank_term"
    assert fac.original_principal == 50_000_000
    assert fac.coupon_rate_quarterly == 0.025
    assert len(fac.covenants) == 1
    assert fac.covenants[0].covenant_type == "max_debt_to_ebitda"
    assert fac.covenants[0].threshold == 5.0
    # And an amortize log line should have run (post-accounting)
    fac_logs = [m for m in new_state.quarter_log
                if "FACILITY" in m or "facility interest" in m]
    assert len(fac_logs) >= 1


def test_orchestrator_falls_back_to_legacy_when_structure_missing():
    """If IB returns no facility_structure, orchestrator uses the legacy
    lump-sum path (backward compat with v0.5 IB output shape)."""
    from src.orchestrator import WorldState, run_quarter
    from src.types import SimParams, RawDecisions
    from src.config import RunConfig

    state = WorldState(run_id="test")
    state.firms["firm_0"] = FirmState(
        firm_id="firm_0", is_active=True, cash=100_000_000,
        capacity_units=100, base_unit_cost=40_000,
        ppe_gross=25_000_000, shares_outstanding=10_000_000,
    )
    state.params = SimParams()
    config = RunConfig(debt_covenants_enabled=True)

    def firm_fn(fid, firm, info, params):
        return RawDecisions(price=95_000, production=50,
                             capex=0, rd_spend=10_000_000,
                             rd_allocation={"product": 1.0, "process": 0, "delivery": 0},
                             sga_spend=2_000_000)

    def ib_fn(firms, macro, params, raw_decisions):
        return {"firm_0": {
            "term_debt_approved": 30_000_000,
            "term_debt_rate": 0.03,
            "equity_approved": 0, "equity_price": 0,
            "debt_reasoning": "test legacy", "equity_reasoning": "",
            # no facility_structure key
        }}

    new_state = run_quarter(state, firm_agent_fn=firm_fn,
                             env_agent_fn=lambda *a, **k: None,
                             investment_bank_fn=ib_fn, config=config)
    firm = new_state.firms["firm_0"]
    # Legacy path: no facility created, but long_term_debt increased
    assert len(firm.debt_facilities) == 0
    assert firm.long_term_debt == 30_000_000


def test_orchestrator_resolves_violation_via_waive():
    """End-to-end: firm with distressed facility → covenant violates →
    violation_resolver returns 'waive' → orchestrator applies waiver."""
    from src.orchestrator import WorldState, run_quarter
    from src.types import SimParams, RawDecisions
    from src.config import RunConfig

    state = WorldState(run_id="test")
    # Pre-existing facility in violation (too much debt for the EBITDA)
    cov = Covenant(covenant_type="max_debt_to_ebitda", threshold=3.0,
                   currently_violated=False)
    fac = DebtFacility(
        facility_id="F1", firm_id="firm_0",
        facility_type="bank_term",
        original_principal=100_000_000, current_balance=100_000_000,
        coupon_rate_quarterly=0.02,
        origination_quarter=0, maturity_quarter=21,
        amortization_type="bullet",
        covenants=(cov,),
    )
    state.firms["firm_0"] = FirmState(
        firm_id="firm_0", is_active=True, cash=50_000_000,
        capacity_units=100, base_unit_cost=40_000,
        ppe_gross=25_000_000, shares_outstanding=10_000_000,
        debt_facilities=(fac,), long_term_debt=100_000_000,
    )
    state.params = SimParams()
    # Seed one compustat row so TTM computation yields small EBITDA → violation
    from src.types import CompustatRow
    state.compustat_rows.append(CompustatRow(
        run_id="test", firm_id="firm_0", fyearq=2030, fqtr=4,
        niq=5_000_000, xintq=2_000_000, dpq=1_000_000,
        saleq=10_000_000, cogsq=5_000_000,
    ))

    config = RunConfig(debt_covenants_enabled=True)

    def firm_fn(fid, firm, info, params):
        return RawDecisions(price=95_000, production=50,
                             capex=0, rd_spend=10_000_000,
                             rd_allocation={"product": 1.0, "process": 0, "delivery": 0},
                             sga_spend=2_000_000)

    def resolver(violations, firms, macro):
        return [{"firm_id": v["firm_id"], "facility_id": v["facility_id"],
                 "covenant_type": v["covenant_type"], "action": "waive",
                 "waiver_fee": 100_000, "new_threshold": 0,
                 "new_rate_quarterly": 0, "reasoning": "one-time issue"}
                for v in violations]

    new_state = run_quarter(state, firm_agent_fn=firm_fn,
                             env_agent_fn=lambda *a, **k: None,
                             violation_resolver_fn=resolver, config=config)
    # After waiver: covenant should no longer be flagged violated, facility current
    firm = new_state.firms["firm_0"]
    assert firm.debt_facilities[0].status == "current"
    assert firm.debt_facilities[0].covenants[0].currently_violated is False
    # Waiver fee came out of cash
    waiver_logs = [m for m in new_state.quarter_log if "WAIVED" in m]
    assert len(waiver_logs) >= 1
    # Queue cleared
    assert new_state.pending_covenant_violations == []


# ── Stage 3d: WRDS debt dataset builders ──────────────────────────────────

def _make_state_with_facility_and_bond():
    """Helper: WorldState with a firm holding one bank_term facility with a
    covenant, and one convertible_bond."""
    from src.orchestrator import WorldState
    state = WorldState(run_id="r")
    cov = Covenant(covenant_type="max_debt_to_ebitda", threshold=4.0)
    term = DebtFacility(
        facility_id="firm_0-FAC-001", firm_id="firm_0",
        facility_type="bank_term",
        original_principal=50_000_000, current_balance=50_000_000,
        coupon_rate_quarterly=0.02,
        origination_quarter=1, maturity_quarter=21,
        amortization_type="bullet", covenants=(cov,),
    )
    conv = DebtFacility(
        facility_id="firm_0-FAC-002", firm_id="firm_0",
        facility_type="convertible_bond",
        original_principal=100_000_000, current_balance=100_000_000,
        coupon_rate_quarterly=0.01,
        origination_quarter=2, maturity_quarter=41,
        amortization_type="bullet",
        conversion_ratio=40.0, conversion_price=25.0,
    )
    state.firms["firm_0"] = FirmState(
        firm_id="firm_0", is_active=True,
        debt_facilities=(term, conv),
        long_term_debt=150_000_000,
    )
    return state


def test_build_debt_facilities_has_both_facility_types():
    from src.datasets import build_debt_facilities
    state = _make_state_with_facility_and_bond()
    rows = build_debt_facilities(state)
    assert len(rows) == 2
    types = {r["facility_type"] for r in rows}
    assert types == {"bank_term", "convertible_bond"}
    # Convertible fields populated
    conv_row = next(r for r in rows if r["facility_type"] == "convertible_bond")
    assert conv_row["conversion_ratio"] == 40.0
    assert conv_row["conversion_price"] == 25.0


def test_build_debt_covenants_links_to_facility_id():
    from src.datasets import build_debt_covenants
    state = _make_state_with_facility_and_bond()
    rows = build_debt_covenants(state)
    # Only bank_term has covenants in our fixture
    assert len(rows) == 1
    assert rows[0]["facility_id"] == "firm_0-FAC-001"
    assert rows[0]["covenant_type"] == "max_debt_to_ebitda"
    assert rows[0]["threshold"] == 4.0


def test_build_bond_issuances_excludes_bank_term():
    from src.datasets import build_bond_issuances
    state = _make_state_with_facility_and_bond()
    rows = build_bond_issuances(state)
    # Only convertible_bond qualifies (no plain "bond" in fixture)
    assert len(rows) == 1
    assert rows[0]["bond_type"] == "convertible_bond"
    assert rows[0]["is_convertible"] == 1


def test_build_covenant_violations_reads_firm_history():
    from src.datasets import build_covenant_violations
    from src.orchestrator import WorldState
    state = WorldState(run_id="r")
    event = CovenantViolationEvent(
        firm_id="firm_0", facility_id="F1",
        covenant_type="max_debt_to_ebitda",
        violation_quarter=5, resolution="waived",
        waiver_fee=500_000, resolution_quarter=5,
    )
    state.firms["firm_0"] = FirmState(
        firm_id="firm_0", is_active=True,
        covenant_violation_history=(event,),
    )
    rows = build_covenant_violations(state)
    assert len(rows) == 1
    assert rows[0]["resolution"] == "waived"
    assert rows[0]["waiver_fee"] == 500_000


def test_N2_orchestrator_handles_revolver_origination():
    """N2: when IB proposes a bank_revolver facility, orchestrator must
    create it undrawn and then draw_revolver() — not fall back to legacy
    lump-sum LTD path. Cash must increase by term_amt; revolver_balance
    must reflect the draw."""
    from src.orchestrator import WorldState, run_quarter
    from src.types import SimParams, RawDecisions
    from src.config import RunConfig

    state = WorldState(run_id="test")
    state.firms["firm_0"] = FirmState(
        firm_id="firm_0", is_active=True, cash=100_000_000,
        capacity_units=100, base_unit_cost=40_000,
        ppe_gross=25_000_000, shares_outstanding=10_000_000,
    )
    state.params = SimParams()
    config = RunConfig(debt_covenants_enabled=True)

    def firm_fn(fid, firm, info, params):
        return RawDecisions(price=95_000, production=50, capex=0,
                             rd_spend=10_000_000,
                             rd_allocation={"product": 1.0, "process": 0, "delivery": 0},
                             sga_spend=2_000_000, debt_request=20_000_000)

    def ib_fn(firms, macro, params, raw_decisions):
        return {"firm_0": {
            "term_debt_approved": 20_000_000,
            "term_debt_rate": 0.015,
            "equity_approved": 0, "equity_price": 0,
            "debt_reasoning": "revolver", "equity_reasoning": "",
            "facility_structure": {
                "facility_type": "bank_revolver",
                "amortization_type": "revolver",
                "maturity_quarters": 20,
                "covenants": [],
                "conversion_ratio": 0.0, "conversion_price": 0.0,
            }
        }}

    new_state = run_quarter(state, firm_agent_fn=firm_fn,
                             env_agent_fn=lambda *a, **k: None,
                             investment_bank_fn=ib_fn, config=config)
    firm = new_state.firms["firm_0"]
    assert len(firm.debt_facilities) == 1
    fac = firm.debt_facilities[0]
    assert fac.facility_type == "bank_revolver"
    assert fac.current_balance == 20_000_000, f"revolver drawn to {fac.current_balance}"
    assert firm.revolver_balance == 20_000_000
    # long_term_debt should NOT include revolver balance
    assert firm.long_term_debt == 0


def test_F5_rejects_revolver_with_drawn_balance_at_origination():
    """F5: add_facility must reject a bank_revolver with current_balance > 0.
    Subsequent draws go through draw_revolver() which credits cash."""
    firm = FirmState(firm_id="firm_0", is_active=True, cash=10_000_000)
    bad = DebtFacility(
        facility_id="", firm_id="firm_0",
        facility_type="bank_revolver",
        original_principal=25_000_000, current_balance=5_000_000,  # drawn!
        coupon_rate_quarterly=0.015,
        origination_quarter=1, maturity_quarter=17,
        amortization_type="revolver",
    )
    with pytest.raises(ValueError, match="must originate with current_balance=0"):
        add_facility(firm, bad)


def test_F6_accelerated_revolver_stays_on_balance_sheet():
    """F6: accelerated revolver with unpaid balance must remain in
    _sum_revolver / consistency aggregates until repaid or defaulted."""
    from src.debt_management import _sum_revolver, _non_facility_rev
    fac = DebtFacility(
        facility_id="F1", firm_id="firm_0",
        facility_type="bank_revolver",
        original_principal=10_000_000, current_balance=5_000_000,
        coupon_rate_quarterly=0.015,
        origination_quarter=1, maturity_quarter=17,
        amortization_type="revolver", status="accelerated",
    )
    firm = FirmState(
        firm_id="firm_0", is_active=True,
        debt_facilities=(fac,), revolver_balance=5_000_000,
    )
    # Before fix: _sum_revolver would drop accelerated → 0
    assert _sum_revolver(firm.debt_facilities) == 5_000_000
    # consistency_check: no mismatch
    from src.debt_management import consistency_check
    assert consistency_check(firm) == []


def test_F3_bad_debt_expense_with_writeoffs_exceeding_allowance():
    """F3: when env write-offs exceed prior allowance, bad_debt_expense must
    include the direct portion (write_offs − prior_allow) plus the topup.
    Formula: bad_debt_expense = new_allowance − prior.allowance + write_offs.
    After N1 reordering: write-offs applied before new_allowance computed,
    so new_allowance ≤ end_ar_post_writeoff."""
    from src.accounting import post_quarter
    # Large revenue so end_ar is comfortably larger than write_offs
    firm = FirmState(
        firm_id="firm_0", is_active=True, quarter=4,
        cash=100_000_000,
        accounts_receivable=10_000_000,
        allowance_for_doubtful_accounts=100_000,  # prior allow = $100K (small)
        ppe_gross=25_000_000, accum_depreciation=5_000_000,
        common_stock=10_000, apic=0,
        retained_earnings=100_000_000 + 10_000_000 - 100_000 + 20_000_000 - 10_000,
        shares_outstanding=10_000_000,
        capacity_units=200, base_unit_cost=14_000,
    )
    # revenue = 100 × 95000 = 9.5M → end_ar pre-writeoff = 9.5M × 0.15 = 1.425M
    # write_offs = $500K (5x prior allow), end_ar post = 925K
    # new_allow = 925K × 0.05 = 46.25K
    # bad_debt_expense = 46.25K - 100K + 500K = 446.25K
    decisions = ClampedDecisions(
        price=95_000, production=100, capex=0, rd_spend=10_000_000,
        rd_allocation={"product": 1.0, "process": 0, "delivery": 0},
        sga_spend=2_000_000,
        allowance_pct_of_ar=0.05,
        write_offs_this_quarter=500_000,
    )
    outcome = MarketOutcome(firm_id="firm_0", units_sold=100, market_share=0.5)
    new_state, flows = post_quarter(firm, decisions, outcome, SimParams())
    # write_offs > prior_allowance (500K > 100K) — the excess 400K must still
    # hit P&L as bad_debt_expense via the new formula.
    expected = (new_state.allowance_for_doubtful_accounts
                - 100_000 + 500_000)
    assert flows.bad_debt_expense == pytest.approx(expected, rel=0.01), (
        f"Expected bad_debt_expense = {expected:,.0f}; got {flows.bad_debt_expense:,.0f}"
    )
    # Specifically: the "direct portion" (400K = 500K - 100K) is hit
    assert flows.bad_debt_expense > 400_000
    # BS identity holds
    from src.accounting import validate_state
    violations = validate_state(new_state, flows, firm, decisions=decisions)
    assert violations == [], f"BS/identity violations: {violations}"


def test_F7_end_of_quarter_row_reflects_post_settlement_state():
    """F7: compustat row for a quarter with post-Phase-7d state mutations
    (e.g., covenant acceleration paying off a facility) must reflect the
    final end-of-Q state, not the mid-quarter snapshot."""
    from src.orchestrator import WorldState, run_quarter
    from src.types import SimParams, RawDecisions

    state = WorldState(run_id="test")
    from src.config import RunConfig

    state.firms["firm_0"] = FirmState(
        firm_id="firm_0", is_active=True, cash=200_000_000,
        capacity_units=100, base_unit_cost=40_000,
        ppe_gross=25_000_000, shares_outstanding=10_000_000,
    )
    state.params = SimParams()
    config = RunConfig(debt_covenants_enabled=True)

    def firm_fn(fid, firm, info, params):
        return RawDecisions(price=95_000, production=50, capex=0,
                             rd_spend=10_000_000,
                             rd_allocation={"product": 1.0, "process": 0, "delivery": 0},
                             sga_spend=2_000_000, debt_request=50_000_000)

    def ib_fn(firms, macro, params, raw_decisions):
        # Propose a facility with impossible debt/EBITDA covenant → will
        # violate Phase 7.5, Phase 7.7 will accelerate.
        return {"firm_0": {
            "term_debt_approved": 50_000_000,
            "term_debt_rate": 0.02,
            "equity_approved": 0, "equity_price": 0,
            "debt_reasoning": "test", "equity_reasoning": "",
            "facility_structure": {
                "facility_type": "bank_term",
                "amortization_type": "bullet",
                "maturity_quarters": 20,
                "covenants": [{"covenant_type": "max_debt_to_ebitda",
                               "threshold": 1.0}],
                "conversion_ratio": 0.0, "conversion_price": 0.0,
            }
        }}

    def resolver(violations, firms, macro):
        return [{"firm_id": v["firm_id"], "facility_id": v["facility_id"],
                 "covenant_type": v["covenant_type"], "action": "accelerate",
                 "waiver_fee": 0, "new_threshold": 0,
                 "new_rate_quarterly": 0, "reasoning": "force payoff"}
                for v in violations]

    new_state = run_quarter(state, firm_agent_fn=firm_fn,
                             env_agent_fn=lambda *a, **k: None,
                             investment_bank_fn=ib_fn,
                             violation_resolver_fn=resolver, config=config)
    # After Phase 7.7 acceleration: facility balance=0, LTD=0.
    # Row must reflect that, not the mid-Q $50M.
    firm = new_state.firms["firm_0"]
    assert firm.long_term_debt == 0
    # The end-of-Q row
    row = next(r for r in new_state.compustat_rows
               if r.firm_id == "firm_0" and r.fqtr == new_state.macro.fqtr)
    assert row.dlttq == pytest.approx(0, abs=1.0), (
        f"row.dlttq should reflect post-acceleration LTD=0; got {row.dlttq}"
    )
    # Cash identity: chechq = end_cash - prior.cash. In this test, prior.cash
    # was 200M. Acceleration pays off the 50M that was added by origination,
    # so net cash impact from the facility is 0; the only cash change is from
    # accounting (operations).
    assert row.cheq == firm.cash
    # Cash identity: chechq = end_cash - prior_cash should hold
    # prior was 200M. End is firm.cash.
    expected_chechq = firm.cash - 200_000_000
    assert abs(row.chechq - expected_chechq) < 1.0, (
        f"row.chechq {row.chechq} != firm.cash - prior.cash {expected_chechq}"
    )


def test_accounting_excludes_facility_debt_from_legacy_interest():
    """Regression test: when a facility carries long_term_debt, accounting.py's
    legacy interest calc (which uses aggregate LTD × term_rate) must exclude
    the facility-owned portion to avoid double-counting with amortize_quarter.
    """
    from src.accounting import post_quarter
    from src.types import (FirmState, ClampedDecisions, MarketOutcome,
                            SimParams, DebtFacility)

    # Firm with $100M legacy LTD at 2%/Q + $50M facility at 4%/Q.
    # Legacy calc (without fix) would charge: 150M × 2% = 3M interest.
    # With fix: only non-facility LTD (100M × 2% = 2M) charged to IS.
    # Amortize_quarter (not called here) would charge 50M × 4% = 2M separately.
    fac = DebtFacility(
        facility_id="F1", firm_id="firm_0",
        facility_type="bank_term",
        original_principal=50_000_000, current_balance=50_000_000,
        coupon_rate_quarterly=0.04,
        origination_quarter=0, maturity_quarter=21,
        amortization_type="bullet", status="current",
    )
    firm = FirmState(
        firm_id="firm_0", is_active=True, quarter=4,
        cash=100_000_000,
        accounts_receivable=0, inventory_units=0, inventory_value=0,
        ppe_gross=25_000_000, accum_depreciation=5_000_000,
        long_term_debt=150_000_000,          # 100M legacy + 50M facility
        revolver_balance=0,
        term_debt_rate=0.02,
        debt_facilities=(fac,),
        common_stock=10_000, apic=0, retained_earnings=-30_010_000,  # to balance
        shares_outstanding=10_000_000,
        capacity_units=100, base_unit_cost=14_000,
    )
    decisions = ClampedDecisions(
        price=95_000, production=50, capex=0, rd_spend=10_000_000,
        rd_allocation={"product": 1.0, "process": 0, "delivery": 0},
        sga_spend=2_000_000, credit_drawn=0,
    )
    outcome = MarketOutcome(firm_id="firm_0", units_sold=40, market_share=0.2)
    new_state, flows = post_quarter(firm, decisions, outcome, SimParams())
    # With the fix: facility LTD (50M) excluded → only 100M × 0.02 = 2M interest
    # (revolver balance = 0, so no revolver interest).
    # Without fix: 150M × 0.02 = 3M.
    assert flows.interest_expense == pytest.approx(2_000_000, rel=0.01), \
        f"Expected 2M interest (100M non-facility × 2%); got {flows.interest_expense}"


def test_build_covenant_tests_panel_empty_when_no_compustat():
    from src.datasets import build_covenant_tests_panel
    state = _make_state_with_facility_and_bond()
    # No compustat rows → no panel rows
    rows = build_covenant_tests_panel(state)
    assert rows == []


# ── Stage 3e: Firm prompt facility display ────────────────────────────────

def test_firm_prompt_shows_facilities_when_toggle_on():
    from src.prompts import build_firm_prompt
    from src.types import SimParams

    cov = Covenant(covenant_type="max_debt_to_ebitda", threshold=5.0)
    fac = DebtFacility(
        facility_id="firm_0-FAC-001", firm_id="firm_0",
        facility_type="bank_term",
        original_principal=50_000_000, current_balance=50_000_000,
        coupon_rate_quarterly=0.025,
        origination_quarter=1, maturity_quarter=21,
        amortization_type="bullet", covenants=(cov,), status="current",
    )
    firm = FirmState(
        firm_id="firm_0", is_active=True, cash=100_000_000,
        capacity_units=100, base_unit_cost=40_000,
        ppe_gross=25_000_000, shares_outstanding=10_000_000,
        debt_facilities=(fac,), long_term_debt=50_000_000,
    )
    info = {
        "public_competitors": {}, "own_private": {},
        "macro": {"risk_free_rate": 0.01, "awareness_rate": 0.15,
                  "quarter": 1, "fyear": 2031, "fqtr": 1},
        "gazette": "",
    }
    _, user = build_firm_prompt(firm, info, SimParams(),
                                  debt_covenants_enabled=True)
    # Display block appears
    assert "DEBT FACILITIES" in user
    assert "firm_0-FAC-001" in user
    assert "bank_term" in user
    assert "max_debt_to_ebitda" in user
    assert "5.00" in user  # threshold
    assert "10.0%/yr" in user  # annualized rate display


def test_firm_prompt_omits_facility_block_when_toggle_off():
    from src.prompts import build_firm_prompt
    from src.types import SimParams

    cov = Covenant(covenant_type="max_debt_to_ebitda", threshold=5.0)
    fac = DebtFacility(
        facility_id="firm_0-FAC-001", firm_id="firm_0",
        facility_type="bank_term",
        original_principal=50_000_000, current_balance=50_000_000,
        coupon_rate_quarterly=0.025,
        origination_quarter=1, maturity_quarter=21,
        amortization_type="bullet", covenants=(cov,), status="current",
    )
    firm = FirmState(
        firm_id="firm_0", is_active=True, cash=100_000_000,
        capacity_units=100, base_unit_cost=40_000,
        ppe_gross=25_000_000, shares_outstanding=10_000_000,
        debt_facilities=(fac,), long_term_debt=50_000_000,
    )
    info = {
        "public_competitors": {}, "own_private": {},
        "macro": {"risk_free_rate": 0.01, "awareness_rate": 0.15,
                  "quarter": 1, "fyear": 2031, "fqtr": 1},
        "gazette": "",
    }
    _, user = build_firm_prompt(firm, info, SimParams(),
                                  debt_covenants_enabled=False)
    # Display block suppressed; no facility ID leaks
    assert "DEBT FACILITIES" not in user
    assert "firm_0-FAC-001" not in user


def test_firm_prompt_facility_block_empty_when_no_facilities():
    from src.prompts import build_firm_prompt
    from src.types import SimParams

    firm = FirmState(
        firm_id="firm_0", is_active=True, cash=100_000_000,
        capacity_units=100, base_unit_cost=40_000,
        ppe_gross=25_000_000, shares_outstanding=10_000_000,
    )
    info = {
        "public_competitors": {}, "own_private": {},
        "macro": {"risk_free_rate": 0.01, "awareness_rate": 0.15,
                  "quarter": 1, "fyear": 2031, "fqtr": 1},
        "gazette": "",
    }
    _, user = build_firm_prompt(firm, info, SimParams(),
                                  debt_covenants_enabled=True)
    # Toggle on but firm has no facilities → header not shown
    assert "DEBT FACILITIES" not in user
