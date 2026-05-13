"""Wave ν+8 regression test: defaulted firm's pre-default cash must
not be overwritten by auction proceeds.

Previously `apply_auction_result` wrote `cash=amount` (sale proceeds),
silently destroying any pre-default cash the firm was holding. After
the fix, sale proceeds are ADDED to existing cash and a multi-tier
waterfall pays creditors.
"""
import pytest

from src.distressed_auction import apply_auction_result
from src.types import FirmState


def make_defaulted_with_cash(cash, ppe_gross=200_000_000.0, ltd=80_000_000.0):
    return FirmState(
        firm_id="firm_d",
        incarnation=1,
        quarter=20,
        is_active=False,
        capacity_units=250,
        base_unit_cost=14_000.0,
        ppe_gross=ppe_gross,
        accum_depreciation=ppe_gross * 0.3,
        capability_stock=50.0,
        brand_stock=40.0,
        cash=cash,
        long_term_debt=ltd,
        revolver_balance=0.0,
        inventory_value=10_000_000.0,
        retained_earnings=-50_000_000.0,
    )


def make_winner_with_cash(cash):
    return FirmState(
        firm_id="firm_w",
        incarnation=1,
        quarter=20,
        is_active=True,
        capacity_units=250,
        base_unit_cost=14_000.0,
        ppe_gross=300_000_000.0,
        capability_stock=70.0,
        brand_stock=60.0,
        cash=cash,
    )


class _State:
    def __init__(self, firms):
        self.firms = firms


def test_defaulted_firm_cash_preserved_through_auction():
    """firm_d had $300M cash + $200M ppe + $80M LTD. Acquirer pays $250M.
    After auction:
      - Acquirer should have its old cash - $250M
      - Defaulted firm should have $300M + $250M - $80M LTD waterfall
        = $470M cash (NOT just $250 - $80 = $170M as the old buggy code would produce)
    """
    defaulted = make_defaulted_with_cash(cash=300_000_000.0, ppe_gross=200_000_000.0, ltd=80_000_000.0)
    winner = make_winner_with_cash(cash=1_000_000_000.0)
    state = _State({"firm_w": winner, "firm_d": defaulted})
    event = {
        "outcome": "sold",
        "winner_id": "firm_w",
        "winning_amount": 250_000_000.0,
    }
    upd_winner, upd_defaulted = apply_auction_result(
        state, defaulted, event, integration_friction=0.6
    )
    # Pre-default cash + proceeds, minus LTD waterfall
    expected_cash = 300_000_000.0 + 250_000_000.0 - 80_000_000.0
    assert upd_defaulted.cash == pytest.approx(expected_cash), (
        f"defaulted firm cash should be {expected_cash:,.0f}, got {upd_defaulted.cash:,.0f}"
    )
    # LTD should be paid off
    assert upd_defaulted.long_term_debt == 0.0
    # Acquirer's cash decreased by sale price
    assert upd_winner.cash == pytest.approx(1_000_000_000.0 - 250_000_000.0)


def test_zero_predefault_cash_still_works():
    """Sanity: when defaulted firm had 0 cash pre-default, behavior matches
    the old code (no regression in that special case)."""
    defaulted = make_defaulted_with_cash(cash=0.0, ppe_gross=100_000_000.0, ltd=20_000_000.0)
    winner = make_winner_with_cash(cash=500_000_000.0)
    state = _State({"firm_w": winner, "firm_d": defaulted})
    event = {
        "outcome": "sold",
        "winner_id": "firm_w",
        "winning_amount": 50_000_000.0,
    }
    _, upd_defaulted = apply_auction_result(state, defaulted, event)
    # 0 + 50M - 20M waterfall = 30M
    assert upd_defaulted.cash == pytest.approx(30_000_000.0)
    assert upd_defaulted.long_term_debt == 0.0
