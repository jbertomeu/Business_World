"""Wave ν+11: regression test pinning the auction-PPE-residual fix.

Bug: apply_auction_result() previously used
    ppe_gross = max(0, defaulted.ppe_gross - defaulted.ppe_net)
    accum_depreciation = max(0, accum_dep - (ppe_gross - ppe_net))

which, since ppe_gross - ppe_net == accum_depreciation, reduces to:
    new_ppe_gross = accum_depreciation
    new_accum_depreciation = 0
    new_ppe_net = accum_depreciation   ← phantom PPE

Every distressed auction left the defaulted firm with phantom PPE equal
to its prior accumulated depreciation. Run-2 (seed 9999) accumulated 370
BS-invariant violations from this single bug. Fix zeroes both PPE fields
outright.
"""
from __future__ import annotations

import pytest

from src.distressed_auction import apply_auction_result
from src.types import FirmState


def make_defaulted(cash, ppe_gross, accum_depreciation, ltd):
    return FirmState(
        firm_id="firm_d",
        incarnation=1,
        quarter=20,
        is_active=False,
        capability_stock=50.0,
        brand_stock=40.0,
        capacity_units=250,
        cash=cash,
        ppe_gross=ppe_gross,
        accum_depreciation=accum_depreciation,
        long_term_debt=ltd,
        revolver_balance=0.0,
        inventory_value=10_000_000.0,
        retained_earnings=-50_000_000.0,
        common_stock=0.0,
        apic=200_000_000.0,
    )


def make_winner(cash):
    return FirmState(
        firm_id="firm_w",
        incarnation=1,
        quarter=20,
        is_active=True,
        capacity_units=250,
        capability_stock=70.0,
        brand_stock=60.0,
        cash=cash,
        ppe_gross=300_000_000.0,
        accum_depreciation=50_000_000.0,
    )


class _State:
    def __init__(self, firms):
        self.firms = firms


def test_defaulted_firm_loses_all_ppe():
    """Wave ν+11: the defaulted firm's PPE must be zero after the
    auction. Previously, accumulated depreciation would persist as
    phantom net PPE."""
    defaulted = make_defaulted(
        cash=300_000_000.0,
        ppe_gross=200_000_000.0,
        accum_depreciation=60_000_000.0,  # ppe_net = 140M
        ltd=80_000_000.0,
    )
    winner = make_winner(cash=1_000_000_000.0)
    state = _State({"firm_w": winner, "firm_d": defaulted})
    event = {
        "outcome": "sold",
        "winner_id": "firm_w",
        "winning_amount": 250_000_000.0,
    }
    upd_winner, upd_defaulted = apply_auction_result(
        state, defaulted, event, integration_friction=0.6
    )
    # Defaulted firm has no PPE at all — both gross and accumulated zeroed
    assert upd_defaulted.ppe_gross == 0.0
    assert upd_defaulted.accum_depreciation == 0.0
    # Therefore ppe_net is 0
    assert upd_defaulted.ppe_gross - upd_defaulted.accum_depreciation == 0.0


def test_winner_receives_full_ppe_net():
    """Winner's PPE increases by exactly the defaulted firm's pre-auction
    ppe_net — confirming the asset transfer is conserved."""
    defaulted = make_defaulted(
        cash=0.0, ppe_gross=200_000_000.0,
        accum_depreciation=60_000_000.0, ltd=0.0,
    )
    pre_ppe_net = defaulted.ppe_gross - defaulted.accum_depreciation
    assert pre_ppe_net == 140_000_000.0
    winner = make_winner(cash=500_000_000.0)
    pre_winner_ppe_net = winner.ppe_gross - winner.accum_depreciation
    state = _State({"firm_w": winner, "firm_d": defaulted})
    event = {
        "outcome": "sold",
        "winner_id": "firm_w",
        "winning_amount": 200_000_000.0,
    }
    upd_winner, _ = apply_auction_result(
        state, defaulted, event, integration_friction=0.6
    )
    new_winner_ppe_net = upd_winner.ppe_gross - upd_winner.accum_depreciation
    assert new_winner_ppe_net == pytest.approx(
        pre_winner_ppe_net + pre_ppe_net
    )


def test_industry_total_ppe_conserved_through_auction():
    """The total ppe_net across (defaulted + winner) before and after the
    auction must be conserved. Previous bug created phantom PPE every
    auction; this test pins the conservation invariant."""
    defaulted = make_defaulted(
        cash=0.0, ppe_gross=180_000_000.0,
        accum_depreciation=45_000_000.0, ltd=20_000_000.0,
    )
    winner = make_winner(cash=600_000_000.0)
    pre_total_ppe_net = (
        (defaulted.ppe_gross - defaulted.accum_depreciation)
        + (winner.ppe_gross - winner.accum_depreciation)
    )
    state = _State({"firm_w": winner, "firm_d": defaulted})
    event = {
        "outcome": "sold",
        "winner_id": "firm_w",
        "winning_amount": 150_000_000.0,
    }
    upd_winner, upd_defaulted = apply_auction_result(
        state, defaulted, event, integration_friction=0.6
    )
    post_total_ppe_net = (
        (upd_defaulted.ppe_gross - upd_defaulted.accum_depreciation)
        + (upd_winner.ppe_gross - upd_winner.accum_depreciation)
    )
    assert post_total_ppe_net == pytest.approx(pre_total_ppe_net)


def test_defaulted_zero_predefault_cash_still_works():
    """No-regression: the zero-cash special case still works."""
    defaulted = make_defaulted(
        cash=0.0, ppe_gross=100_000_000.0,
        accum_depreciation=20_000_000.0, ltd=20_000_000.0,
    )
    winner = make_winner(cash=500_000_000.0)
    state = _State({"firm_w": winner, "firm_d": defaulted})
    event = {
        "outcome": "sold",
        "winner_id": "firm_w",
        "winning_amount": 50_000_000.0,
    }
    _, upd_defaulted = apply_auction_result(state, defaulted, event)
    assert upd_defaulted.ppe_gross == 0.0
    assert upd_defaulted.accum_depreciation == 0.0
    # Cash: 0 + 50M proceeds - 20M LTD waterfall = 30M
    assert upd_defaulted.cash == pytest.approx(30_000_000.0)
    assert upd_defaulted.long_term_debt == 0.0
