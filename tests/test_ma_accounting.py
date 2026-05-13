"""
Tests for M&A balance-sheet integrity.

Regression guard for the BS bug found in the 20y v2 run
(run_1776823883), where `process_acquisition` transferred only the
target's cash and PPE to the acquirer — leaving AR, inventory, and
all liabilities behind. That created a $500M free-asset gain at Q4
2031 when firm_2 acquired firm_0.

Under purchase-method GAAP, an acquirer must absorb ALL identifiable
assets AND liabilities of the target at book value, with goodwill
recording any premium over net book value.
"""

from __future__ import annotations

import pytest

from src.ma_agent import process_acquisition
from src.types import FirmState, MABid


def _target_firm() -> FirmState:
    """A target with diverse balance-sheet items (not just cash+PPE)."""
    return FirmState(
        firm_id="target_x",
        incarnation=1,
        quarter=4,
        is_active=True,
        cash=200_000_000.0,
        accounts_receivable=30_000_000.0,
        allowance_for_doubtful_accounts=1_500_000.0,
        inventory_units=100,
        inventory_value=5_000_000.0,
        ppe_gross=80_000_000.0,
        accum_depreciation=8_000_000.0,
        accounts_payable=4_000_000.0,
        accrued_expenses=3_000_000.0,
        taxes_payable=500_000.0,
        deferred_revenue=1_000_000.0,
        legal_reserve_balance=2_000_000.0,
        revolver_balance=10_000_000.0,
        long_term_debt=20_000_000.0,
        deferred_tax_liability=500_000.0,
        pension_liability=1_000_000.0,
        common_stock=10_000.0,
        apic=280_000_000.0,
        retained_earnings=-16_510_000.0,  # chosen so total_equity + liab = total_assets
        shares_outstanding=10_000_000,
        equity_price=25.00,
        capacity_units=100,
        capability_stock=30.0,
        brand_stock=15.0,
        base_unit_cost=10_000.0,
    )


def _acquirer_firm() -> FirmState:
    """A cash-rich acquirer ready to absorb the target."""
    return FirmState(
        firm_id="acquirer_x",
        incarnation=1,
        quarter=4,
        is_active=True,
        cash=800_000_000.0,
        accounts_receivable=10_000_000.0,
        inventory_value=2_000_000.0,
        ppe_gross=100_000_000.0,
        accum_depreciation=5_000_000.0,
        accounts_payable=2_000_000.0,
        accrued_expenses=1_500_000.0,
        common_stock=10_000.0,
        apic=800_000_000.0,
        retained_earnings=103_490_000.0,  # balances the books
        shares_outstanding=10_000_000,
        equity_price=75.00,
        capacity_units=200,
        capability_stock=55.0,
        brand_stock=50.0,
        base_unit_cost=9_500.0,
    )


def test_bs_identity_holds_after_acquisition_at_book_value():
    """Acquisition at exactly net book value should leave zero goodwill
    AND preserve the combined BS identity."""
    acquirer = _acquirer_firm()
    target = _target_firm()
    # Pre-check: each firm's BS balances on its own
    assert abs(acquirer.total_assets
                - acquirer.total_liabilities - acquirer.total_equity) < 1.0
    assert abs(target.total_assets
                - target.total_liabilities - target.total_equity) < 1.0

    net_book = target.total_assets - target.total_liabilities
    # Pay exactly net book value per share
    price_per_share = net_book / target.shares_outstanding
    bid = MABid(
        bidder_id="acquirer_x", target_id="target_x",
        offer_price_per_share=price_per_share,
        cash_component=net_book,
        offer_type="friendly",
    )

    new_acquirer, dead_target, goodwill = process_acquisition(
        acquirer, target, bid,
    )

    # Combined BS identity must hold
    bs_residual = (new_acquirer.total_assets
                   - new_acquirer.total_liabilities
                   - new_acquirer.total_equity)
    assert abs(bs_residual) < 1.0, (
        f"BS residual after acquisition at book value: ${bs_residual:,.0f}"
    )
    # No goodwill when purchase_price = net_book_value
    assert goodwill == 0.0
    # Target is deactivated
    assert not dead_target.is_active


def test_bs_identity_holds_after_acquisition_with_premium():
    """Acquisition at a premium creates goodwill that balances the BS."""
    acquirer = _acquirer_firm()
    target = _target_firm()

    net_book = target.total_assets - target.total_liabilities
    # Pay 30% premium over book
    premium = 1.30
    price_per_share = (net_book * premium) / target.shares_outstanding
    bid = MABid(
        bidder_id="acquirer_x", target_id="target_x",
        offer_price_per_share=price_per_share,
        cash_component=net_book * premium,
        offer_type="friendly",
    )

    new_acquirer, dead_target, goodwill = process_acquisition(
        acquirer, target, bid,
    )

    # Combined BS identity must hold — goodwill should exactly close it
    bs_residual = (new_acquirer.total_assets
                   - new_acquirer.total_liabilities
                   - new_acquirer.total_equity)
    assert abs(bs_residual) < 1.0, (
        f"BS residual after acquisition w/ premium: ${bs_residual:,.0f}"
    )
    # Goodwill should be ~30% of net book
    expected_goodwill = net_book * (premium - 1.0)
    assert abs(goodwill - expected_goodwill) < 1.0


def test_all_target_assets_absorbed_by_acquirer():
    """Acquirer should absorb target's AR, inventory, and PPE (not just cash+PPE)."""
    acquirer = _acquirer_firm()
    target = _target_firm()
    bid = MABid(
        bidder_id="acquirer_x", target_id="target_x",
        offer_price_per_share=30.0,
        cash_component=300_000_000.0,
        offer_type="friendly",
    )

    new_acquirer, _, _ = process_acquisition(acquirer, target, bid)

    assert new_acquirer.accounts_receivable == (
        acquirer.accounts_receivable + target.accounts_receivable
    )
    assert new_acquirer.inventory_units == (
        acquirer.inventory_units + target.inventory_units
    )
    assert new_acquirer.inventory_value == (
        acquirer.inventory_value + target.inventory_value
    )
    assert new_acquirer.ppe_gross == (
        acquirer.ppe_gross + target.ppe_gross
    )


def test_all_target_liabilities_absorbed_by_acquirer():
    """Acquirer should absorb target's AP, accrued, debt, pension, etc."""
    acquirer = _acquirer_firm()
    target = _target_firm()
    bid = MABid(
        bidder_id="acquirer_x", target_id="target_x",
        offer_price_per_share=30.0,
        cash_component=300_000_000.0,
        offer_type="friendly",
    )

    new_acquirer, _, _ = process_acquisition(acquirer, target, bid)

    assert new_acquirer.accounts_payable == (
        acquirer.accounts_payable + target.accounts_payable
    )
    assert new_acquirer.accrued_expenses == (
        acquirer.accrued_expenses + target.accrued_expenses
    )
    assert new_acquirer.revolver_balance == (
        acquirer.revolver_balance + target.revolver_balance
    )
    assert new_acquirer.long_term_debt == (
        acquirer.long_term_debt + target.long_term_debt
    )
    assert new_acquirer.pension_liability == (
        acquirer.pension_liability + target.pension_liability
    )
    assert new_acquirer.legal_reserve_balance == (
        acquirer.legal_reserve_balance + target.legal_reserve_balance
    )


def test_deactivated_target_bs_is_zeroed():
    """The target post-acquisition should have zero assets + zero liabs
    so it can't double-count in aggregate industry metrics."""
    acquirer = _acquirer_firm()
    target = _target_firm()
    bid = MABid(
        bidder_id="acquirer_x", target_id="target_x",
        offer_price_per_share=30.0,
        cash_component=300_000_000.0,
        offer_type="friendly",
    )

    _, dead_target, _ = process_acquisition(acquirer, target, bid)

    assert not dead_target.is_active
    assert dead_target.cash == 0.0
    assert dead_target.accounts_receivable == 0.0
    assert dead_target.ppe_gross == 0.0
    assert dead_target.accounts_payable == 0.0
    assert dead_target.long_term_debt == 0.0


def test_regression_v2_run_pattern():
    """Regression: this is the exact pattern from the 20y v2 run where
    firm_2 acquired a cash-rich target at below-book-value price, creating
    a $500M residual. With the fix, the residual should be zero."""
    # Approximately reconstructed target state from v2 Q4 2031
    target = FirmState(
        firm_id="t", incarnation=1, quarter=4, is_active=True,
        cash=300_000_000.0,
        accounts_receivable=15_000_000.0,
        inventory_value=3_000_000.0,
        ppe_gross=80_000_000.0,
        accum_depreciation=6_000_000.0,
        accounts_payable=3_000_000.0,
        accrued_expenses=2_000_000.0,
        common_stock=10_000.0,
        apic=380_000_000.0,
        retained_earnings=6_990_000.0,  # Adjusted to make BS balance
        shares_outstanding=10_000_000,
        equity_price=40.00,
        capability_stock=50.0, brand_stock=40.0,
        capacity_units=100,
    )
    # Sanity: target BS balances
    residual_target = (target.total_assets - target.total_liabilities
                       - target.total_equity)
    assert abs(residual_target) < 1.0, f"Target BS unbalanced: {residual_target}"

    acquirer = _acquirer_firm()
    # Simulated v2 scenario: firm_2 bid LOW (below book value) because
    # the target was visibly dying. This is where the bug bit.
    price_per_share = 15.0   # well below $40 target equity price
    cash_component = price_per_share * target.shares_outstanding  # $150M
    bid = MABid(
        bidder_id="acquirer_x", target_id="t",
        offer_price_per_share=price_per_share,
        cash_component=cash_component,
        offer_type="friendly",
    )

    new_acquirer, _, goodwill = process_acquisition(acquirer, target, bid)

    # Under the buggy version, acquirer gained target.cash + target.ppe_net
    # without assuming liabilities, creating a ~$300M residual. With the
    # fix, residual should be exactly zero.
    bs_residual = (new_acquirer.total_assets
                   - new_acquirer.total_liabilities
                   - new_acquirer.total_equity)
    assert abs(bs_residual) < 1.0, (
        f"v2 regression: BS residual = ${bs_residual:,.0f} "
        f"(should be zero after fix)"
    )
    # Below-book-value purchase: goodwill = 0 (max with 0)
    assert goodwill == 0.0
