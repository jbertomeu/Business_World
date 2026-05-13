"""
Accounting tests using the doc 16 worked example as the golden fixture.

If these tests pass, the accounting module is correct.
"""

import math
import pytest

from src.types import (
    ClampedDecisions,
    FirmState,
    MarketOutcome,
    QuarterFlows,
    SimParams,
)
from src.accounting import post_quarter, validate_state, _utilization_multiplier


# ─── Fixtures from doc 16 ────────────────────────────────────────────────

PARAMS = SimParams()

# End-of-Q1 state (the starting point for Q2 computation)
Q1_END_STATE = FirmState(
    firm_id="firm_0",
    incarnation=1,
    quarter=1,
    is_active=True,

    cash=303_655_570,
    accounts_receivable=2_565_000,
    inventory_units=20,
    inventory_value=298_200,
    ppe_gross=25_000_000,
    accum_depreciation=625_000,

    accounts_payable=402_570,
    accrued_expenses=3_700_000,
    taxes_payable=0,
    revolver_balance=0,
    long_term_debt=0,

    common_stock=10_000,
    apic=349_990_000,
    retained_earnings=-23_208_800,
    treasury_stock=0,

    shares_outstanding=10_000_000,
    capability_stock=40.0,
    brand_stock=11.25,
    capacity_units=250,
    base_unit_cost=14_200,
    product_generation=1,
    delivery_generation=1,
    rd_cumulative_product=10_000_000,
    rd_cumulative_process=3_750_000,
    rd_cumulative_delivery=2_250_000,
    nol_carryforward=23_208_800,

    revolver_commitment=0,
    revolver_rate=0.02,
    term_debt_rate=0.03,
    equity_price=0,
)

Q2_DECISIONS = ClampedDecisions(
    price=92_000,
    production=220,
    capex=15_000_000,
    rd_spend=28_000_000,
    rd_allocation={"product": 0.60, "process": 0.25, "delivery": 0.15},
    sga_spend=14_000_000,
    dividends=0,
    buybacks=0,
    credit_drawn=0,
    clamping_log=[],
)

Q2_OUTCOME = MarketOutcome(
    firm_id="firm_0",
    units_sold=200,
    market_share=0.22,
    product_rd_advance=False,
    process_cogs_reduction_pct=0.0,
    delivery_rd_advance=False,
)


# ─── The Golden Test ─────────────────────────────────────────────────────

class TestDoc16WorkedExample:
    """Tests matching the exact numbers in doc 16."""

    def setup_method(self):
        self.state, self.flows = post_quarter(
            Q1_END_STATE, Q2_DECISIONS, Q2_OUTCOME, PARAMS
        )

    # ── Income Statement ──

    def test_revenue(self):
        assert self.flows.net_sales == 200 * 92_000  # 18,400,000

    def test_cogs(self):
        # FIFO: 20 old units at 14,910 each + 180 new units at ~14,245 each
        # Old unit cost: 298,200 / 20 = 14,910
        # New unit cost: 14,200 * (1 - process_reduction) * util_mult
        # process_reduction = 0.22*(1-exp(-3,750,000/120,000,000)) ≈ 0.00677
        # base_after = 14,200 * 0.99323 ≈ 14,103.87
        # util = 220/250 = 0.88 -> mult = 1.00 + 0.50*(0.90-0.88) = 1.01
        # effective = 14,103.87 * 1.01 ≈ 14,244.91
        # COGS = 20*14,910 + 180*14,244.91 ≈ 298,200 + 2,564,083 ≈ 2,862,283
        # Allow tolerance for rounding
        assert abs(self.flows.cogs - 2_862_300) < 500  # within $500

    def test_gross_profit(self):
        assert abs(self.flows.gross_profit - (self.flows.net_sales - self.flows.cogs)) < 1

    def test_rd_expense(self):
        assert self.flows.rd_expense == 28_000_000

    def test_sga_expense(self):
        assert self.flows.sga_expense == 14_000_000

    def test_depreciation(self):
        # 2.5% of starting PPE gross (25M)
        assert self.flows.depreciation == 625_000

    def test_operating_income(self):
        expected = (self.flows.gross_profit - self.flows.rd_expense
                    - self.flows.sga_expense - self.flows.depreciation)
        assert abs(self.flows.operating_income - expected) < 1

    def test_interest_expense(self):
        assert self.flows.interest_expense == 0  # no debt

    def test_tax_expense(self):
        assert self.flows.tax_expense == 0  # pretax is negative

    def test_net_income(self):
        assert abs(self.flows.net_income - self.flows.pretax_income) < 1
        # Net income should be approximately -27,087,300 (doc 16)
        assert abs(self.flows.net_income - (-27_087_300)) < 1000

    # ── Balance Sheet ──

    def test_total_assets_positive(self):
        assert self.state.total_assets > 0

    def test_balance_sheet_identity(self):
        diff = abs(self.state.total_assets - self.state.total_liabilities
                   - self.state.total_equity)
        assert diff < 1.0, f"BS identity violated by {diff:.2f}"

    def test_cash_positive(self):
        assert self.state.cash > 0

    def test_cash_approximately_correct(self):
        # Doc 16: ending cash ≈ 262,253,445
        assert abs(self.state.cash - 262_253_445) < 5000

    def test_ar(self):
        assert abs(self.state.accounts_receivable - 0.15 * 18_400_000) < 1

    def test_inventory_units(self):
        # Started with 20 + produced 220 - sold 200 = 40
        assert self.state.inventory_units == 40

    def test_ppe_gross(self):
        assert self.state.ppe_gross == 25_000_000 + 15_000_000

    def test_accum_depreciation(self):
        assert self.state.accum_depreciation == 625_000 + 625_000

    def test_retained_earnings(self):
        expected = Q1_END_STATE.retained_earnings + self.flows.net_income
        assert abs(self.state.retained_earnings - expected) < 1

    # ── Cash Flow ──

    def test_cash_flow_reconciliation(self):
        recon = abs(self.flows.change_in_cash
                    - (self.flows.cfo + self.flows.cfi + self.flows.cff))
        assert recon < 1.0, f"CF recon violated by {recon:.2f}"

    def test_cash_delta_matches(self):
        delta = self.state.cash - Q1_END_STATE.cash
        assert abs(delta - self.flows.change_in_cash) < 1.0

    def test_cfi(self):
        assert self.flows.cfi == -15_000_000

    def test_cff(self):
        assert self.flows.cff == 0  # no financing, no dividends

    # ── Internal State ──

    def test_capability_stock(self):
        # A = (1-0.025)*40.0 + 0.8*10.8 * headroom
        # headroom = (100-40)/100 = 0.60
        # = 39.0 + 8.64 * 0.60 = 39.0 + 5.184 = 44.184
        expected = (1 - 0.025) * 40.0 + 0.8 * 10.8 * ((100 - 40) / 100)
        assert abs(self.state.capability_stock - expected) < 0.1

    def test_brand_stock(self):
        # B = (1-0.10)*11.25 + 1.5*14*(40/50) * headroom
        # headroom = (100-11.25)/100 = 0.8875
        quality_factor = Q1_END_STATE.capability_stock / 50.0
        brand_headroom = (100.0 - Q1_END_STATE.brand_stock) / 100.0
        expected = ((1 - 0.10) * 11.25
                    + 1.5 * 14.0 * quality_factor * brand_headroom)
        assert abs(self.state.brand_stock - expected) < 0.1

    def test_rd_cumulative_product(self):
        # 10,000,000 + 60% * (28M - 10M) = 10,000,000 + 10,800,000 = 20,800,000
        assert abs(self.state.rd_cumulative_product - 20_800_000) < 1

    def test_rd_cumulative_process(self):
        # 3,750,000 + 25% * 18,000,000 = 3,750,000 + 4,500,000 = 8,250,000
        assert abs(self.state.rd_cumulative_process - 8_250_000) < 1

    def test_nol(self):
        # Prior NOL 23,208,800 + loss 27,087,300 ≈ 50,296,100
        assert abs(self.state.nol_carryforward - 50_296_100) < 1000

    def test_generation_unchanged(self):
        assert self.state.product_generation == 1

    # ── Full Validation ──

    def test_all_invariants_pass(self):
        violations = validate_state(self.state, self.flows, Q1_END_STATE)
        assert violations == [], f"Invariant violations: {violations}"


# ─── Utilization Multiplier Tests ────────────────────────────────────────

class TestUtilizationMultiplier:

    def test_full_utilization(self):
        assert _utilization_multiplier(0.95, PARAMS) == 1.0

    def test_at_90(self):
        assert _utilization_multiplier(0.90, PARAMS) == 1.0

    def test_at_80(self):
        # 1.00 + 0.50 * (0.90 - 0.80) = 1.05
        assert abs(_utilization_multiplier(0.80, PARAMS) - 1.05) < 0.001

    def test_at_88(self):
        # 1.00 + 0.50 * (0.90 - 0.88) = 1.01
        assert abs(_utilization_multiplier(0.88, PARAMS) - 1.01) < 0.001

    def test_at_60(self):
        # 1.10 + 1.00 * (0.70 - 0.60) = 1.20
        assert abs(_utilization_multiplier(0.60, PARAMS) - 1.20) < 0.001

    def test_at_40(self):
        # 1.30 + 1.50 * (0.50 - 0.40) = 1.45
        assert abs(_utilization_multiplier(0.40, PARAMS) - 1.45) < 0.001

    def test_at_20(self):
        # 1.60 + 2.00 * (0.30 - 0.20) = 1.80
        assert abs(_utilization_multiplier(0.20, PARAMS) - 1.80) < 0.001

    def test_at_zero(self):
        # 1.60 + 2.00 * (0.30 - 0.00) = 2.20
        assert abs(_utilization_multiplier(0.0, PARAMS) - 2.20) < 0.001


# ─── Tax / NOL Tests ─────────────────────────────────────────────────────

class TestTaxAndNOL:

    def test_loss_increases_nol(self):
        """A quarter with a loss should increase the NOL balance."""
        state, flows = post_quarter(Q1_END_STATE, Q2_DECISIONS, Q2_OUTCOME, PARAMS)
        assert state.nol_carryforward > Q1_END_STATE.nol_carryforward
        assert flows.tax_expense == 0

    def test_profit_uses_nol(self):
        """A profitable quarter should use NOL to reduce taxes."""
        # Create a firm with NOL and make it profitable
        profitable_firm = Q1_END_STATE.evolve(
            nol_carryforward=10_000_000,
            cash=500_000_000,
        )
        # High price + low costs = profit
        profitable_decisions = ClampedDecisions(
            price=200_000,
            production=200,
            capex=0,
            rd_spend=10_000_000,
            sga_spend=5_000_000,
            dividends=0,
            buybacks=0,
            credit_drawn=0,
            rd_allocation={"product": 0.6, "process": 0.25, "delivery": 0.15},
        )
        outcome = MarketOutcome(
            firm_id="firm_0", units_sold=200, market_share=0.22)

        state, flows = post_quarter(
            profitable_firm, profitable_decisions, outcome, PARAMS)

        assert flows.pretax_income > 0
        assert state.nol_carryforward < profitable_firm.nol_carryforward
        # Tax should be on (pretax - nol_usage) * 0.21
        # NOL usage limited to 80% of pretax
        max_nol_use = 0.80 * flows.pretax_income
        expected_nol_use = min(profitable_firm.nol_carryforward, max_nol_use)
        expected_tax = (flows.pretax_income - expected_nol_use) * 0.21
        assert abs(flows.tax_expense - expected_tax) < 1


# ─── Edge Case: Zero Production ──────────────────────────────────────────

class TestZeroProduction:

    def test_no_production_no_cogs(self):
        decisions = ClampedDecisions(
            price=92_000, production=0, capex=0,
            rd_spend=10_000_000, sga_spend=5_000_000,
            rd_allocation={"product": 0.6, "process": 0.25, "delivery": 0.15},
        )
        outcome = MarketOutcome(firm_id="firm_0", units_sold=0, market_share=0.0)
        state, flows = post_quarter(Q1_END_STATE, decisions, outcome, PARAMS)

        assert flows.net_sales == 0
        assert flows.cogs == 0
        assert state.inventory_units == Q1_END_STATE.inventory_units  # unchanged

        violations = validate_state(state, flows, Q1_END_STATE)
        assert violations == []


# ─── Edge Case: Sell From Inventory Only ─────────────────────────────────

class TestSellFromInventoryOnly:

    def test_sell_old_inventory(self):
        """If production=0 but we have inventory, we can still sell from it."""
        decisions = ClampedDecisions(
            price=92_000, production=0, capex=0,
            rd_spend=10_000_000, sga_spend=5_000_000,
            rd_allocation={"product": 0.6, "process": 0.25, "delivery": 0.15},
        )
        outcome = MarketOutcome(
            firm_id="firm_0", units_sold=10, market_share=0.05)

        state, flows = post_quarter(Q1_END_STATE, decisions, outcome, PARAMS)

        assert flows.net_sales == 10 * 92_000
        assert flows.units_sold == 10
        assert state.inventory_units == Q1_END_STATE.inventory_units - 10

        violations = validate_state(state, flows, Q1_END_STATE)
        assert violations == []
