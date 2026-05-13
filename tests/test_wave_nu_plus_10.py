"""Wave ν+10 regression tests.

Covers items 2 (schema validation), 3 (Ch11/Ch7), 6 (friendly-M&A
counter), 7 (multi-bank competition), 8 (heterogeneous IC),
9 (4-analyst panel), 10 (bond failure with discussion), 14 (parser
tests). Item 16 (regression check) lives as its own harness rather
than as pytest assertions.
"""
from __future__ import annotations

import pytest


# ─────────────────────────────────────────────────────────────────────────
# Item 2: Schema validation
# ─────────────────────────────────────────────────────────────────────────

def test_schema_registry_loaded():
    from src.schemas import SCHEMAS
    expected = {
        "env_market_outcome", "equity_panel_response",
        "auction_judge_response", "auction_bidder_response",
        "commercial_bank_response", "investment_bank_response",
        "firm_decision", "sellside_analyst_note",
    }
    assert expected.issubset(set(SCHEMAS.keys()))


def test_schema_lenient_accepts_well_formed_env_outcome():
    from src.schemas import validate_lenient
    payload = {
        "firm_outcomes": {
            "firm_0": {"units_sold": 100, "market_share": 0.5,
                       "product_advance": True},
        },
        "rd_outcomes": [
            {"firm_id": "firm_0", "product_advance": True,
             "process_cogs_reduction_pct": 0.02},
        ],
        "total_demand": 200,
        "narrative": "...",
    }
    ok, errs = validate_lenient("env_market_outcome", payload)
    assert ok, errs


def test_schema_lenient_flags_missing_required_field():
    from src.schemas import validate_lenient
    bad = {"rd_outcomes": []}  # firm_outcomes missing
    ok, errs = validate_lenient("env_market_outcome", bad)
    assert not ok
    assert any("firm_outcomes" in e for e in errs)


def test_schema_lenient_flags_market_share_out_of_range():
    from src.schemas import validate_lenient
    bad = {"firm_outcomes": [
        {"firm_id": "firm_0", "market_share": 5.0},
    ]}
    ok, errs = validate_lenient("env_market_outcome", bad)
    assert not ok
    assert any("market_share" in e or "maximum" in e for e in errs)


def test_schema_lenient_validates_equity_panel_response():
    from src.schemas import validate_lenient
    ok_payload = {"firms": [{"firm_id": "firm_0", "equity_price": 50.0}]}
    ok, errs = validate_lenient("equity_panel_response", ok_payload)
    assert ok, errs

    bad_payload = {"firms": [{"firm_id": "firm_0"}]}  # equity_price required
    ok, errs = validate_lenient("equity_panel_response", bad_payload)
    assert not ok


def test_schema_strict_raises_on_violation():
    from src.schemas import validate, SchemaViolation
    bad = {"rd_outcomes": []}
    with pytest.raises(SchemaViolation):
        validate("env_market_outcome", bad)


def test_schema_unknown_name_raises():
    from src.schemas import validate
    with pytest.raises(KeyError):
        validate("does_not_exist", {})


def test_schema_oneOf_branch_matching():
    """env_market_outcome.firm_outcomes accepts both list and dict shapes."""
    from src.schemas import validate_lenient
    list_shape = {"firm_outcomes": [{"firm_id": "firm_0"}]}
    dict_shape = {"firm_outcomes": {"firm_0": {"units_sold": 100}}}
    ok1, _ = validate_lenient("env_market_outcome", list_shape)
    ok2, _ = validate_lenient("env_market_outcome", dict_shape)
    assert ok1 and ok2


# ─────────────────────────────────────────────────────────────────────────
# Item 3: Chapter 11 vs Chapter 7 classification
# ─────────────────────────────────────────────────────────────────────────

def test_classify_default_routes_viable_firm_to_ch11():
    from src.bankruptcy import classify_default
    from src.types import FirmState
    firm = FirmState(
        firm_id="firm_x", capability_stock=60, brand_stock=50,
        capacity_units=250,
    )
    # Both TTM OI and CFO positive → Ch11
    assert classify_default(firm, ttm_operating_income=10_000_000,
                              ttm_cfo=8_000_000) == "chapter_11"


def test_classify_default_routes_unviable_firm_to_ch7():
    from src.bankruptcy import classify_default
    from src.types import FirmState
    firm = FirmState(
        firm_id="firm_x", capability_stock=60, brand_stock=50,
        capacity_units=250,
    )
    # Both negative → Ch7
    assert classify_default(firm, ttm_operating_income=-5_000_000,
                              ttm_cfo=-7_000_000) == "chapter_7"


def test_classify_default_pre_revenue_always_ch7():
    from src.bankruptcy import classify_default
    from src.types import FirmState
    firm = FirmState(
        firm_id="firm_x", capability_stock=2, brand_stock=2,  # pre-revenue
        capacity_units=250,
    )
    assert classify_default(firm, ttm_operating_income=10_000_000,
                              ttm_cfo=8_000_000) == "chapter_7"


def test_enter_chapter_11_haircuts_ltd_and_wipes_equity():
    from src.bankruptcy import enter_chapter_11, CH11_LTD_HAIRCUT
    from src.types import FirmState
    firm = FirmState(
        firm_id="firm_x",
        cash=10_000_000,
        long_term_debt=100_000_000,
        revolver_balance=20_000_000,
        founder_shares=1_000_000,
        public_shares_outstanding=5_000_000,
        common_stock=50_000_000,
        apic=100_000_000,
        retained_earnings=-30_000_000,
    )
    out = enter_chapter_11(firm)
    assert out.default_type == "chapter_11"
    assert out.is_active is True
    assert out.quarters_in_chapter_11 == 1
    assert out.long_term_debt == 50_000_000  # 50% haircut
    assert out.revolver_balance == 0
    assert out.founder_shares == 0
    assert out.public_shares_outstanding == 0
    assert out.common_stock == 0
    assert out.apic == 0
    # Wave ν+11: retained_earnings is the balancing residual so the BS
    # identity holds (A = L + E) at the moment of Ch11 entry. With
    # cash=10M and LTD haircut to 50M (no revolver, no AR/inv/PPE in
    # this test setup), the residual is 10M - 50M = -40M.
    assert out.retained_earnings == -40_000_000
    # And confirm the BS identity: A = L + E
    new_total_assets = out.cash  # only cash in this minimal test
    new_total_liabilities = out.long_term_debt + out.revolver_balance
    new_total_equity = (out.common_stock + out.apic
                        + out.retained_earnings)
    assert new_total_assets == new_total_liabilities + new_total_equity


def test_enter_chapter_7_keeps_existing_behaviour():
    from src.bankruptcy import enter_chapter_7
    from src.types import FirmState
    firm = FirmState(
        firm_id="firm_x", cash=-5_000_000, long_term_debt=10_000_000,
    )
    out = enter_chapter_7(firm)
    assert out.default_type == "chapter_7"
    assert out.is_active is False
    assert out.cash == 0  # floored
    assert out.long_term_debt == 15_000_000  # absorbed -5M deficit


def test_chapter_11_emerges_after_4q_positive_operations():
    from src.bankruptcy import maybe_emerge_or_convert, CH11_EMERGENCE_QUARTERS
    from src.types import FirmState
    firm = FirmState(
        firm_id="firm_x", default_type="chapter_11",
        quarters_in_chapter_11=CH11_EMERGENCE_QUARTERS,
    )
    out = maybe_emerge_or_convert(firm, ttm_operating_income=5_000_000,
                                    ttm_cfo=3_000_000)
    assert out.default_type == ""
    assert out.quarters_in_chapter_11 == 0


def test_chapter_11_converts_to_ch7_after_8q_persistent_losses():
    from src.bankruptcy import maybe_emerge_or_convert, CH11_CONVERSION_QUARTERS
    from src.types import FirmState
    firm = FirmState(
        firm_id="firm_x", default_type="chapter_11",
        quarters_in_chapter_11=CH11_CONVERSION_QUARTERS,
    )
    out = maybe_emerge_or_convert(firm, ttm_operating_income=-5_000_000,
                                    ttm_cfo=-3_000_000)
    assert out.default_type == "chapter_7"
    assert out.is_active is False


# ─────────────────────────────────────────────────────────────────────────
# Item 7: Multi-bank competition
# ─────────────────────────────────────────────────────────────────────────

def test_commercial_bank_panel_picks_lowest_rate():
    from src.commercial_bank import make_commercial_bank_panel

    def bank_a(firms, macro, params):
        return {"firm_0": {"revolver_commitment": 50_000_000,
                           "revolver_rate": 0.03,
                           "risk": "medium",
                           "reasoning": "A's offer"}}

    def bank_b(firms, macro, params):
        return {"firm_0": {"revolver_commitment": 50_000_000,
                           "revolver_rate": 0.025,  # cheaper
                           "risk": "low",
                           "reasoning": "B's offer"}}

    panel = make_commercial_bank_panel([bank_a, bank_b], names=["A", "B"])
    out = panel({}, None, None)
    assert "firm_0" in out
    assert out["firm_0"]["revolver_rate"] == 0.025
    assert out["firm_0"]["winning_bank"] == "B"
    assert len(out["firm_0"]["competing_offers"]) == 2


def test_commercial_bank_panel_skips_zero_commitments():
    from src.commercial_bank import make_commercial_bank_panel

    def bank_a(firms, macro, params):
        return {"firm_0": {"revolver_commitment": 0, "revolver_rate": 0,
                           "risk": "high", "reasoning": "declined"}}

    def bank_b(firms, macro, params):
        return {"firm_0": {"revolver_commitment": 30_000_000,
                           "revolver_rate": 0.04,
                           "risk": "high", "reasoning": "approved at premium"}}

    panel = make_commercial_bank_panel([bank_a, bank_b], names=["A", "B"])
    out = panel({}, None, None)
    assert out["firm_0"]["winning_bank"] == "B"
    # Only one valid offer; A's zero commitment was filtered out
    assert len(out["firm_0"]["competing_offers"]) == 1


def test_investment_bank_panel_picks_lowest_debt_rate_highest_equity_price():
    from src.investment_bank import make_investment_bank_panel

    def bank_a(firms, macro, params, raw_decisions=None):
        return {"firm_0": {
            "term_debt_approved": 50_000_000,
            "term_debt_rate": 0.03,
            "equity_approved": 20_000_000,
            "equity_price": 15.0,
        }}

    def bank_b(firms, macro, params, raw_decisions=None):
        return {"firm_0": {
            "term_debt_approved": 50_000_000,
            "term_debt_rate": 0.025,  # better debt rate
            "equity_approved": 20_000_000,
            "equity_price": 18.0,  # better equity price
        }}

    panel = make_investment_bank_panel([bank_a, bank_b], names=["A", "B"])
    out = panel({}, None, None)
    assert out["firm_0"]["term_debt_rate"] == 0.025
    assert out["firm_0"]["winning_bank_debt"] == "B"
    assert out["firm_0"]["equity_price"] == 18.0
    assert out["firm_0"]["winning_bank_equity"] == "B"


def test_investment_bank_panel_independent_debt_equity_winners():
    """Bank A wins debt (lower rate); Bank B wins equity (higher price)."""
    from src.investment_bank import make_investment_bank_panel

    def bank_a(firms, macro, params, raw_decisions=None):
        return {"firm_0": {
            "term_debt_approved": 50_000_000,
            "term_debt_rate": 0.025,  # lower
            "equity_approved": 20_000_000,
            "equity_price": 15.0,
        }}

    def bank_b(firms, macro, params, raw_decisions=None):
        return {"firm_0": {
            "term_debt_approved": 50_000_000,
            "term_debt_rate": 0.03,
            "equity_approved": 20_000_000,
            "equity_price": 18.0,  # higher
        }}

    panel = make_investment_bank_panel([bank_a, bank_b], names=["A", "B"])
    out = panel({}, None, None)
    assert out["firm_0"]["winning_bank_debt"] == "A"
    assert out["firm_0"]["winning_bank_equity"] == "B"


# ─────────────────────────────────────────────────────────────────────────
# Item 10: Bond-failure with market discussion
# ─────────────────────────────────────────────────────────────────────────

def test_investment_bank_parses_market_discussion_and_retry_guidance():
    """The parser must propagate market_discussion and retry_guidance
    fields on each firm decision so the orchestrator can persist them."""
    # We stage a fake backend that returns a payload with these fields
    # and check the agent function returns them on the per-firm dict.
    from src.investment_bank import make_investment_bank
    from src.types import FirmState, MacroState, SimParams, QuarterFlows

    class _FakeBackend:
        def complete_json(self, system, user):
            return {"firms": [{
                "firm_id": "firm_0",
                "term_debt_approved": 0,           # declined
                "term_debt_rate_quarterly": 0,
                "equity_offering_approved": 0,
                "equity_offering_price": 0,
                "debt_reasoning": "denied",
                "equity_reasoning": "denied",
                "market_discussion": "Credit markets cold; spreads "
                                       "widened 80bp this quarter.",
                "retry_guidance": "Try smaller principal under $20M.",
            }]}

    class _W:
        def __init__(self):
            self.last_quarter_flows = {}
            self.gazettes = []
            self.compustat_rows = []
    state_ref = [_W()]

    fn = make_investment_bank(_FakeBackend(), state_ref)
    out = fn({"firm_0": FirmState(firm_id="firm_0")}, MacroState(),
             SimParams(), raw_decisions=None)
    assert out is not None
    assert "Credit markets cold" in out["firm_0"]["market_discussion"]
    assert "smaller principal" in out["firm_0"]["retry_guidance"]


# ─────────────────────────────────────────────────────────────────────────
# Item 9: Sell-side analyst panel coverage
# ─────────────────────────────────────────────────────────────────────────

def test_4_analysts_in_personalities():
    from src.sellside_analyst import ANALYST_PERSONALITIES
    assert set(ANALYST_PERSONALITIES.keys()) == {
        "analyst_1", "analyst_2", "analyst_3", "analyst_4"
    }


def test_analyst_4_publishes_every_quarter():
    """analyst_4 is the always-on quant/momentum analyst — at least one
    analyst should always publish in every fiscal quarter."""
    from src.sellside_analyst import ANALYST_PERSONALITIES, should_publish
    for fqtr in (1, 2, 3, 4):
        assert should_publish("analyst_4", fqtr)
    # Combined: at least one analyst always publishes
    for fqtr in (1, 2, 3, 4):
        published = [aid for aid in ANALYST_PERSONALITIES
                     if should_publish(aid, fqtr)]
        assert len(published) >= 2  # baseline + at least one rotating


def test_default_config_enables_sellside_analysts_with_count_4():
    from src.config import RunConfig
    cfg = RunConfig()
    assert cfg.sellside_analysts_enabled is True
    assert cfg.sellside_analyst_count == 4
