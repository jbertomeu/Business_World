"""
Tests for Wave λ: PE funds + round execution + IPO.

Focuses on pure-function correctness (transaction math). LLM agents
tested implicitly via mock smokes.
"""
from __future__ import annotations

import pytest

from src.private_equity import (
    default_pe_funds,
    execute_ipo,
    execute_pe_round,
)
from src.types import FirmState, MacroState, PEFund, ProspectusDoc


def _founded_firm() -> FirmState:
    return FirmState(
        firm_id="firm_0",
        is_active=True, quarter=0,
        cash=5_000_000, apic=5_000_000, retained_earnings=0.0,
        shares_outstanding=1_000_000,
        lifecycle_stage="founded", is_public=False, equity_price=0.0,
        capacity_units=100, capability_stock=50, brand_stock=40,
        base_unit_cost=10_000,
    )


def test_execute_pe_round_series_a_math():
    firm = _founded_firm()
    macro = MacroState(quarter=2, fyear=2031, fqtr=2)
    # Series A: $30M raise at $60M pre-money ($90M post-money)
    investors = [("pe_1", 20_000_000), ("pe_3", 10_000_000)]
    new_firm, event, alloc = execute_pe_round(
        firm, round_type="series_a",
        ask_amount=30_000_000,
        pre_money_valuation=60_000_000,
        investors=investors,
        lead_investor="pe_1",
        pitch_narrative="breakthrough longevity platform",
        lead_rationale="strong pre-clinical data",
        macro=macro,
    )
    # Cash: 5M seed + 30M raised = 35M
    assert new_firm.cash == 35_000_000
    # APIC: 5M + 30M = 35M
    assert new_firm.apic == 35_000_000
    # Pre-round shares = 1M; price = 60M / 1M = $60/share
    # Shares issued = 30M / $60 = 500k
    assert new_firm.shares_outstanding == 1_500_000
    assert alloc["pe_1"] == pytest.approx(333_333, abs=5)
    assert alloc["pe_3"] == pytest.approx(166_667, abs=5)
    # Stage progression: founded + series_a round → series_a
    assert new_firm.lifecycle_stage == "series_a"
    # Still private
    assert not new_firm.is_public
    # Event record
    assert event.round_type == "series_a"
    assert event.pre_money_valuation == 60_000_000
    assert event.post_money_valuation == 90_000_000
    assert event.lead_investor == "pe_1"


def test_execute_ipo_transitions_to_public():
    firm = _founded_firm().evolve(
        lifecycle_stage="late_stage_private",
        shares_outstanding=5_000_000,
        cash=50_000_000,
    )
    prospectus = ProspectusDoc(
        firm_id="firm_0", filing_quarter=20,
        price_range_low=15.0, price_range_high=20.0,
        shares_offered=2_000_000,
        business_overview="biotech firm pre-launch",
    )
    macro = MacroState(quarter=20, fyear=2036, fqtr=1)
    firm_with_apic = firm.evolve(apic=50_000_000)  # founder APIC from seed
    new_firm = execute_ipo(firm_with_apic, prospectus, ipo_price=18.0,
                            shares_offered=2_000_000, macro=macro)
    # Cash: 50M + 18 × 2M = 50M + 36M = 86M
    assert new_firm.cash == 86_000_000
    # APIC: 50M (founder) + 36M (IPO) = 86M
    assert new_firm.apic == 86_000_000
    # Shares: 5M + 2M = 7M
    assert new_firm.shares_outstanding == 7_000_000
    assert new_firm.equity_price == 18.0
    assert new_firm.is_public
    assert new_firm.lifecycle_stage == "public"
    assert new_firm.ipo_quarter == 20


def test_default_pe_funds_pool_is_diverse():
    # Wave ν: pool expanded from 3 to 8 funds to support 20-firm runs
    # with a realistic mix of investor types.
    funds = default_pe_funds()
    assert len(funds) >= 3  # at least the original Wave λ trio
    # Unique IDs
    fund_ids = {f.fund_id for f in funds}
    assert len(fund_ids) == len(funds)
    # Strategies differentiated (cheap proxy for behavior diversity)
    strategies = {f.strategy for f in funds}
    assert len(strategies) == len(funds)
    # Every fund has positive capital and non-empty thesis
    for f in funds:
        assert f.initial_capital > 0
        assert f.sector_thesis.strip() != ""


def test_pe_round_rejects_invalid_inputs():
    firm = _founded_firm()
    macro = MacroState(quarter=1, fyear=2031, fqtr=1)
    with pytest.raises(ValueError):
        execute_pe_round(
            firm, "series_a", 0, 60_000_000,
            [("pe_1", 0)], "pe_1", "", "", macro,
        )
    with pytest.raises(ValueError):
        execute_pe_round(
            firm, "series_a", 30_000_000, 0,  # zero pre-money
            [("pe_1", 30_000_000)], "pe_1", "", "", macro,
        )
