"""
Clamping tests based on doc 17 edge cases.
"""

import pytest

from src.types import ClampedDecisions, FirmState, RawDecisions, SimParams
from src.clamping import clamp_decisions, _compute_effective_unit_cost


PARAMS = SimParams()

# A well-capitalized firm for baseline tests
RICH_FIRM = FirmState(
    firm_id="firm_0",
    incarnation=1,
    quarter=1,
    cash=300_000_000,
    capacity_units=250,
    base_unit_cost=14_200,
    accounts_receivable=2_565_000,
    revolver_commitment=50_000_000,
    revolver_balance=0,
    long_term_debt=0,
    revolver_rate=0.02,
    term_debt_rate=0.03,
    taxes_payable=0,
    retained_earnings=50_000_000,  # positive RE for dividend tests
    rd_cumulative_process=3_750_000,
)

STANDARD_DECISIONS = RawDecisions(
    price=92_000,
    production=200,
    capex=15_000_000,
    rd_spend=28_000_000,
    rd_allocation={"product": 0.6, "process": 0.25, "delivery": 0.15},
    sga_spend=14_000_000,
    dividends=0,
    buybacks=0,
)


class TestNoClamping:
    """Edge case 1: plenty of cash, no clamping needed."""

    def test_all_pass_through(self):
        result = clamp_decisions(
            RICH_FIRM, STANDARD_DECISIONS,
            expected_revenue=15_640_000,
            expected_ar_collection=2_565_000,
            params=PARAMS,
        )
        assert result.price == 92_000
        assert result.production == 200
        assert result.capex == 15_000_000
        assert result.rd_spend == 28_000_000
        assert result.sga_spend == 14_000_000
        assert result.dividends == 0
        assert result.buybacks == 0
        assert result.credit_drawn == 0
        assert result.clamping_log == []


class TestProductionCapacity:
    """Edge case 2: production exceeds capacity."""

    def test_production_capped(self):
        decisions = RawDecisions(production=400, price=92_000,
                                  rd_spend=10_000_000, sga_spend=5_000_000)
        result = clamp_decisions(
            RICH_FIRM, decisions,
            expected_revenue=15_000_000, expected_ar_collection=0, params=PARAMS,
        )
        assert result.production == 250
        assert any("capacity" in msg for msg in result.clamping_log)


class TestCOGSExceedsCash:
    """Edge case 3: not enough cash for full production."""

    def test_production_reduced(self):
        poor_firm = RICH_FIRM.evolve(cash=1_000_000, revolver_commitment=0)
        decisions = RawDecisions(production=200, price=92_000,
                                  rd_spend=10_000_000, sga_spend=0)
        result = clamp_decisions(
            poor_firm, decisions,
            expected_revenue=0, expected_ar_collection=0, params=PARAMS,
        )
        assert result.production < 200
        assert result.production >= 0
        assert any("COGS" in msg or "production clamped" in msg
                    for msg in result.clamping_log)


class TestMandatoryForcesDefault:
    """Edge case 5: can't pay mandatory obligations."""

    def test_default_flagged(self):
        broke_firm = RICH_FIRM.evolve(
            cash=5_000_000,
            revolver_commitment=0,
            long_term_debt=100_000_000,
            term_debt_rate=0.025,  # $2.5M interest
            taxes_payable=0,
        )
        decisions = RawDecisions(price=0, production=0,
                                  rd_spend=0, sga_spend=0)
        result = clamp_decisions(
            broke_firm, decisions,
            expected_revenue=0, expected_ar_collection=0, params=PARAMS,
        )
        # Phase III $10M + interest $2.5M = $12.5M > $5M cash + $0 credit
        assert any("DEFAULT" in msg for msg in result.clamping_log)


class TestMandatoryForcesRevolverDraw:
    """Edge case 6: mandatory costs require credit draw."""

    def test_revolver_drawn(self):
        tight_firm = RICH_FIRM.evolve(
            cash=5_000_000,
            revolver_commitment=50_000_000,
        )
        decisions = RawDecisions(price=92_000, production=0,
                                  rd_spend=10_000_000, sga_spend=5_000_000)
        result = clamp_decisions(
            tight_firm, decisions,
            expected_revenue=0, expected_ar_collection=0, params=PARAMS,
        )
        # Mandatory: $10M Phase III. Cash: $5M. Need $5M from revolver.
        assert result.credit_drawn >= 5_000_000
        assert any("revolver" in msg.lower() for msg in result.clamping_log)


class TestProRataClamping:
    """Edge case 7: discretionary spending exceeds available, pro-rata cut."""

    def test_proportional_reduction(self):
        firm = RICH_FIRM.evolve(cash=40_000_000, revolver_commitment=0)
        # After mandatory ($10M Phase III), ~$30M available for discretionary
        decisions = RawDecisions(
            price=92_000, production=0,
            capex=20_000_000,
            rd_spend=30_000_000,  # 20M discretionary
            sga_spend=10_000_000,
        )
        result = clamp_decisions(
            firm, decisions,
            expected_revenue=0, expected_ar_collection=0, params=PARAMS,
        )
        # Discretionary = $20M + $20M + $10M = $50M, but only ~$30M available
        assert result.capex < 20_000_000
        assert result.rd_spend < 30_000_000
        assert result.sga_spend < 10_000_000
        assert any("pro-rata" in msg for msg in result.clamping_log)


class TestDividendsBlockedNegativeRE:
    """Edge case 8: dividends blocked by negative retained earnings."""

    def test_dividends_zero(self):
        negative_re_firm = RICH_FIRM.evolve(retained_earnings=-30_000_000)
        decisions = RawDecisions(
            price=92_000, production=100,
            rd_spend=10_000_000, sga_spend=5_000_000,
            dividends=5_000_000,
        )
        result = clamp_decisions(
            negative_re_firm, decisions,
            expected_revenue=5_000_000, expected_ar_collection=0, params=PARAMS,
        )
        assert result.dividends == 0
        assert any("retained earnings" in msg for msg in result.clamping_log)


class TestDividendsLimitedBySurplus:
    """Edge case 9: dividends limited by available surplus."""

    def test_dividends_clamped(self):
        # Arrange: firm with positive RE but limited surplus after spending
        decisions = RawDecisions(
            price=92_000, production=200,
            capex=200_000_000, rd_spend=50_000_000, sga_spend=30_000_000,
            dividends=50_000_000,
        )
        result = clamp_decisions(
            RICH_FIRM, decisions,
            expected_revenue=15_000_000, expected_ar_collection=2_565_000,
            params=PARAMS,
        )
        # After ~$280M+ in spending from ~$318M available, little left for dividends
        assert result.dividends < 50_000_000


class TestNegativePrice:
    """Edge case 10: negative price sanitized to 0."""

    def test_price_clipped(self):
        decisions = RawDecisions(price=-1000, production=100,
                                  rd_spend=10_000_000, sga_spend=5_000_000)
        result = clamp_decisions(
            RICH_FIRM, decisions,
            expected_revenue=0, expected_ar_collection=0, params=PARAMS,
        )
        assert result.price == 0
        assert any("price" in msg for msg in result.clamping_log)


class TestRDBelowMinimum:
    """Edge case 11: R&D below Phase III minimum."""

    def test_rd_raised_to_minimum(self):
        decisions = RawDecisions(price=92_000, production=100,
                                  rd_spend=5_000_000, sga_spend=5_000_000)
        result = clamp_decisions(
            RICH_FIRM, decisions,
            expected_revenue=5_000_000, expected_ar_collection=0, params=PARAMS,
        )
        assert result.rd_spend >= 10_000_000
        assert any("mandatory minimum" in msg for msg in result.clamping_log)


class TestRDAllocationRenormalization:
    """Edge case 12: allocation doesn't sum to 1.0."""

    def test_renormalized(self):
        decisions = RawDecisions(
            price=92_000, production=100,
            rd_spend=28_000_000, sga_spend=14_000_000,
            rd_allocation={"product": 0.5, "process": 0.3, "delivery": 0.3},
        )
        result = clamp_decisions(
            RICH_FIRM, decisions,
            expected_revenue=5_000_000, expected_ar_collection=0, params=PARAMS,
        )
        alloc_sum = sum(result.rd_allocation.values())
        assert abs(alloc_sum - 1.0) < 0.01
        assert any("renormalized" in msg for msg in result.clamping_log)


class TestZeroProduction:
    """Edge case 15: zero production is valid."""

    def test_zero_production_ok(self):
        decisions = RawDecisions(
            price=92_000, production=0,
            rd_spend=28_000_000, sga_spend=14_000_000,
        )
        result = clamp_decisions(
            RICH_FIRM, decisions,
            expected_revenue=0, expected_ar_collection=2_565_000, params=PARAMS,
        )
        assert result.production == 0
        assert result.clamping_log == [] or not any(
            "production clamped" in msg for msg in result.clamping_log)


class TestEffectiveUnitCost:
    """Test the helper function."""

    def test_full_utilization(self):
        cost = _compute_effective_unit_cost(RICH_FIRM, 250, PARAMS)
        # No process reduction at 3.75M cumulative:
        # reduction = 0.22*(1-exp(-3.75M/120M)) ≈ 0.22*0.0308 ≈ 0.00677
        # base = 14,200 * (1-0.00677) = 14,103.87
        # util = 250/250 = 1.0, mult = 1.0
        assert abs(cost - 14_104) < 5

    def test_low_utilization_expensive(self):
        cost_low = _compute_effective_unit_cost(RICH_FIRM, 50, PARAMS)
        cost_high = _compute_effective_unit_cost(RICH_FIRM, 230, PARAMS)
        assert cost_low > cost_high

    def test_zero_production(self):
        cost = _compute_effective_unit_cost(RICH_FIRM, 0, PARAMS)
        # Should return base_unit_cost (doesn't matter since COGS=0)
        assert cost == RICH_FIRM.base_unit_cost
