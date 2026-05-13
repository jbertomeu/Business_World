"""
Tests for Wave κ strategic planning module.
"""

from __future__ import annotations

import pytest

from src.strategic_planning import (
    compute_plan_variance,
    find_plan_line_for_quarter,
    parse_strategic_plan,
    plan_variance_summary_for_prompt,
    should_replan,
)
from src.types import FirmState, PlanLine, PlanVariance, QuarterFlows, StrategicPlan


def _simple_plan() -> StrategicPlan:
    return StrategicPlan(
        firm_id="firm_0",
        plan_id="plan-abc",
        plan_quarter=0,
        plan_fyear=2031,
        plan_fqtr=0,
        horizon_quarters=4,
        strategy_narrative="Ramp capacity to meet breakthrough demand.",
        key_assumptions=("Patients willing to pay $50K+",),
        key_risks=("Slower-than-expected Gen 2 R&D",),
        milestones=("Positive FCF by Q12",),
        lines=(
            PlanLine(fyear=2031, fqtr=1, planned_revenue=50_000_000,
                     planned_units_sold=3_500, planned_price=14_300,
                     planned_capacity=4_000, planned_cogs=49_000_000,
                     planned_rd_spend=10_000_000, planned_sga_spend=5_000_000,
                     planned_capex=20_000_000, projected_ni=-15_000_000,
                     projected_cash_balance_eoq=700_000_000),
            PlanLine(fyear=2031, fqtr=2, planned_revenue=80_000_000,
                     planned_units_sold=5_600, planned_price=14_300,
                     planned_capacity=6_000, planned_cogs=78_400_000,
                     planned_rd_spend=15_000_000, planned_sga_spend=7_000_000,
                     planned_capex=25_000_000, projected_ni=-20_000_000,
                     projected_cash_balance_eoq=660_000_000),
        ),
    )


def _simple_firm() -> FirmState:
    return FirmState(
        firm_id="firm_0",
        quarter=1, is_active=True,
        cash=700_000_000,
        common_stock=10_000, apic=800_000_000, retained_earnings=-100_000_000,
        shares_outstanding=10_000_000,
        capacity_units=4_000, capability_stock=55, brand_stock=50,
        base_unit_cost=9_500,
    )


def test_find_plan_line_returns_correct_quarter():
    plan = _simple_plan()
    line = find_plan_line_for_quarter(plan, 2031, 2)
    assert line is not None
    assert line.planned_revenue == 80_000_000


def test_find_plan_line_returns_none_beyond_horizon():
    plan = _simple_plan()
    assert find_plan_line_for_quarter(plan, 2032, 1) is None


def test_variance_non_material_when_close_to_plan():
    plan = _simple_plan()
    firm = _simple_firm()
    flows = QuarterFlows(
        net_sales=48_000_000,      # 4% below plan
        reported_net_income=-15_500_000,  # close to plan
        units_sold=3_400,
    )
    variance = compute_plan_variance(firm, plan, flows, 2031, 1)
    assert variance is not None
    assert not variance.is_material
    assert variance.revenue_variance_pct == pytest.approx(-0.04, abs=0.01)


def test_variance_material_when_revenue_way_below_plan():
    plan = _simple_plan()
    firm = _simple_firm()
    flows = QuarterFlows(
        net_sales=20_000_000,       # 60% below plan — material
        reported_net_income=-40_000_000,
        units_sold=1_400,
    )
    variance = compute_plan_variance(firm, plan, flows, 2031, 1)
    assert variance is not None
    assert variance.is_material
    assert "revenue" in variance.material_reason.lower()


def test_parse_strategic_plan_handles_minimal_json():
    raw = {
        "strategy_narrative": "Test",
        "quarterly_lines": [
            {"fyear": 2031, "fqtr": 1,
             "planned_revenue": 100_000_000,
             "planned_units_sold": 7000,
             "projected_cash_balance_eoq": 500_000_000},
        ],
    }
    plan = parse_strategic_plan(raw, "firm_x", plan_quarter=0,
                                 plan_fyear=2031, plan_fqtr=0)
    assert plan.firm_id == "firm_x"
    assert len(plan.lines) == 1
    assert plan.lines[0].planned_revenue == 100_000_000


def test_should_replan_on_streak():
    firm = _simple_firm().evolve(material_variance_streak=2)
    assert should_replan(firm, streak_threshold=2)
    firm2 = _simple_firm().evolve(material_variance_streak=1)
    assert not should_replan(firm2, streak_threshold=2)


def test_plan_variance_summary_empty_when_no_plan():
    firm = _simple_firm()
    assert plan_variance_summary_for_prompt(firm) == {}


def test_plan_variance_summary_with_plan():
    firm = _simple_firm().evolve(current_plan=_simple_plan())
    summary = plan_variance_summary_for_prompt(firm)
    assert summary.get("has_plan") is True
    assert summary.get("plan_horizon_quarters") == 4
    assert "Ramp capacity" in summary.get("strategy_narrative", "")
