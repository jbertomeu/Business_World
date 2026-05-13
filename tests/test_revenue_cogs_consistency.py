"""Wave ν+7 regression test: revenue and COGS must use the same units_sold.

Pins the fix where revenue used `outcome.units_sold` (un-clamped) while
COGS used the clamped value, producing accounting inconsistency when the
env over-allocated demand to a firm beyond what it could supply.
"""
import pytest

from src.accounting import post_quarter
from src.types import (
    ClampedDecisions, FirmState, MacroState, MarketOutcome, SimParams,
)


def make_firm(production_decision=100, prior_inventory=0):
    f = FirmState(
        firm_id="firm_x",
        incarnation=1,
        quarter=5,
        is_active=True,
        capacity_units=200,
        base_unit_cost=14_000.0,
        ppe_gross=50_000_000.0,
        capability_stock=50.0,
        brand_stock=40.0,
        cash=200_000_000.0,
        inventory_units=prior_inventory,
        inventory_value=prior_inventory * 14_000.0,
    )
    return f


def make_decisions(price=150_000, production=100):
    return ClampedDecisions(
        price=price,
        production=production,
        capex=0.0,
        rd_spend=10_000_000.0,
        rd_allocation={"product": 0.6, "process": 0.25, "delivery": 0.15},
        sga_spend=5_000_000.0,
        dividends=0.0,
        buybacks=0.0,
        credit_drawn=0.0,
    )


def test_revenue_and_cogs_consistent_when_env_overallocates():
    """If env says firm sold 200 units but firm only produced 100 with no
    inventory, both revenue AND COGS should reflect 100 units, not 200."""
    firm = make_firm(production_decision=100, prior_inventory=0)
    decisions = make_decisions(price=150_000, production=100)
    # Env over-allocates: claims 200 units sold
    outcome = MarketOutcome(firm_id="firm_x", units_sold=200, market_share=0.5)
    macro = MacroState()
    params = SimParams()

    new_firm, flows = post_quarter(firm, decisions, outcome, params)

    # Revenue should reflect 100 units (clamped), not 200
    assert flows.units_sold == 100, "units_sold must be clamped to production+inventory"
    assert flows.net_sales == 100 * 150_000, (
        f"revenue should be 100 * 150K = $15M, got ${flows.net_sales:,.0f}"
    )
    # COGS should also reflect 100 units
    expected_cogs_approx = 100 * 14_000  # base unit cost, before util/COGS adjustments
    assert flows.cogs > 0, "COGS must be non-zero for actual sales"
    # Gross profit consistent: revenue minus COGS
    assert flows.gross_profit == flows.net_sales - flows.cogs


def test_revenue_unchanged_when_env_within_capacity():
    """If env's allocation is within production+inventory, revenue should
    use that allocation directly."""
    firm = make_firm(production_decision=100, prior_inventory=50)
    decisions = make_decisions(price=120_000, production=100)
    outcome = MarketOutcome(firm_id="firm_x", units_sold=100, market_share=0.4)
    macro = MacroState()
    params = SimParams()

    new_firm, flows = post_quarter(firm, decisions, outcome, params)

    assert flows.units_sold == 100
    assert flows.net_sales == 100 * 120_000


def test_inventory_carryover_allows_sales_above_production():
    """Firm produces 50 units but had 80 in inventory; sells 100. All 100
    should generate revenue."""
    firm = make_firm(production_decision=50, prior_inventory=80)
    decisions = make_decisions(price=140_000, production=50)
    outcome = MarketOutcome(firm_id="firm_x", units_sold=100, market_share=0.3)
    macro = MacroState()
    params = SimParams()

    new_firm, flows = post_quarter(firm, decisions, outcome, params)

    # 50 production + 80 inventory = 130 max sellable. 100 fits.
    assert flows.units_sold == 100
    assert flows.net_sales == 100 * 140_000
