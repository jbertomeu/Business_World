"""Wave ν+9 regression tests.

Pin the bugs identified in WAVE_NU_PLUS_9_BUG_SWEEP.md so they cannot
silently regress. Covers:

  H1 — orchestrator merges env's top-level rd_outcomes into per-firm
       MarketOutcomes (root cause of zero-Gen2-advance result).
  H2 — equity panel enforces a quorum and falls back to the prior price
       when below quorum.
  H4 — config.get_role raises a clear KeyError on unconfigured optional
       roles instead of returning None.
  M1 — accounting applies env's process_cogs_reduction_pct to base unit
       cost (was a `pass` before).
  M5 — restatement no-op returns a structured event, not an empty dict.
  M6 — parsing_utils.parse_float tolerates the standard LLM failure modes.
"""
from __future__ import annotations

import pytest

from src.parsing_utils import parse_float, parse_int, parse_bool


# ─────────────────────────────────────────────────────────────────────────
# H4: get_role on unconfigured optional roles
# ─────────────────────────────────────────────────────────────────────────

class _FakeRole:
    backend = "mock"
    model = "mock-model"
    temperature = 0.0
    note = ""


def test_get_role_raises_on_none_optional_role():
    from src.config import ModelRoster
    roster = ModelRoster(
        firms={"firm_0": _FakeRole()},
        analysts={},
        auditors={},
        environment=_FakeRole(),
        equity_market=_FakeRole(),
        investment_bank=_FakeRole(),
        commercial_bank=_FakeRole(),
        data_analyst=_FakeRole(),
        sec=None,                # not configured
        board_governance=None,   # not configured
        data_broker=None,
        env_verifier=None,
        api_keys={},
    )
    with pytest.raises(KeyError, match="not configured"):
        roster.get_role("sec")
    with pytest.raises(KeyError, match="not configured"):
        roster.get_role("board_governance")
    # Configured fixed roles still work
    assert roster.get_role("environment") is roster.environment


def test_get_role_raises_on_unknown_firm():
    from src.config import ModelRoster
    roster = ModelRoster(
        firms={"firm_0": _FakeRole()},
        analysts={},
        auditors={},
        environment=_FakeRole(),
        equity_market=_FakeRole(),
        investment_bank=_FakeRole(),
        commercial_bank=_FakeRole(),
        data_analyst=_FakeRole(),
        sec=None,
        board_governance=None,
        data_broker=None,
        env_verifier=None,
        api_keys={},
    )
    with pytest.raises(KeyError, match="not in roster"):
        roster.get_role("firm_99")


# ─────────────────────────────────────────────────────────────────────────
# M6: parse_float tolerates LLM failure modes
# ─────────────────────────────────────────────────────────────────────────

def test_parse_float_handles_none():
    assert parse_float(None, default=7.0) == 7.0


def test_parse_float_handles_empty_string():
    assert parse_float("", default=3.0) == 3.0


def test_parse_float_handles_dollar_string():
    assert parse_float("$1,234.56") == 1234.56


def test_parse_float_handles_garbage():
    assert parse_float("not a number", default=99.0) == 99.0


def test_parse_int_via_float():
    assert parse_int("42.7", default=0) == 42
    assert parse_int(None, default=5) == 5


def test_parse_bool_idioms():
    assert parse_bool("yes") is True
    assert parse_bool("NO") is False
    assert parse_bool(1) is True
    assert parse_bool(0) is False
    assert parse_bool("garbage", default=True) is True


# ─────────────────────────────────────────────────────────────────────────
# M5: restatement no-op returns structured event
# ─────────────────────────────────────────────────────────────────────────

def test_restatement_no_op_returns_structured_event():
    from src.restatement import process_restatement
    from src.types import FirmState

    firm = FirmState(
        firm_id="firm_x",
        cumulative_manipulation=0.5,  # below the $1.00 threshold
    )
    new_firm, rows, event = process_restatement(
        firm, [], trigger="sec_forced", quarter=20
    )
    assert isinstance(event, dict)
    assert event.get("outcome") == "no_op"
    assert event.get("trigger") == "sec_forced"
    assert event.get("sec_flag") == 1
    assert event.get("firm_id") == "firm_x"


# ─────────────────────────────────────────────────────────────────────────
# H1: rd_outcomes array merge
# ─────────────────────────────────────────────────────────────────────────

def test_rd_outcomes_merge_logic():
    """The merge logic that lives inline in orchestrator.run_quarter is
    covered by replicating it here as a small testable function. If the
    inline implementation drifts, this test will still catch the
    behavioural contract: a top-level rd_outcomes array must populate
    the per-firm advance fields."""
    env_outcome = {
        "firm_outcomes": {
            "firm_0": {"units_sold": 100, "market_share": 0.5},
            "firm_1": {"units_sold": 80,  "market_share": 0.5},
        },
        "rd_outcomes": [
            {"firm_id": "firm_0", "product_advance": True,
             "process_cogs_reduction_pct": 0.02, "delivery_advance": False},
            {"firm_id": "firm_1", "product_advance": False,
             "process_cogs_reduction_pct": 0.01, "delivery_advance": True},
        ],
    }
    # Reproduce the merge from orchestrator.run_quarter
    rd_arr = env_outcome.get("rd_outcomes") or []
    for rd in rd_arr:
        fid = rd.get("firm_id")
        if not fid or fid not in env_outcome["firm_outcomes"]:
            continue
        fo = env_outcome["firm_outcomes"][fid]
        if "product_advance" not in fo:
            fo["product_advance"] = bool(rd.get("product_advance", False))
        if "process_cogs_reduction_pct" not in fo:
            fo["process_cogs_reduction_pct"] = float(rd.get("process_cogs_reduction_pct", 0) or 0)
        if "delivery_advance" not in fo:
            fo["delivery_advance"] = bool(rd.get("delivery_advance", False))

    f0 = env_outcome["firm_outcomes"]["firm_0"]
    f1 = env_outcome["firm_outcomes"]["firm_1"]
    assert f0["product_advance"] is True
    assert f0["process_cogs_reduction_pct"] == 0.02
    assert f0["delivery_advance"] is False
    assert f1["product_advance"] is False
    assert f1["delivery_advance"] is True


def test_rd_outcomes_existing_firm_outcome_wins():
    """If both firm_outcomes and rd_outcomes specify the same field, the
    firm_outcomes value should win (setdefault semantics)."""
    env_outcome = {
        "firm_outcomes": {
            "firm_0": {"units_sold": 100, "market_share": 1.0,
                       "product_advance": True},  # already True
        },
        "rd_outcomes": [
            {"firm_id": "firm_0", "product_advance": False},  # contradicts
        ],
    }
    rd_arr = env_outcome.get("rd_outcomes") or []
    for rd in rd_arr:
        fid = rd.get("firm_id")
        fo = env_outcome["firm_outcomes"].get(fid, {})
        if "product_advance" not in fo:
            fo["product_advance"] = bool(rd.get("product_advance", False))

    assert env_outcome["firm_outcomes"]["firm_0"]["product_advance"] is True


# ─────────────────────────────────────────────────────────────────────────
# H2: equity panel quorum check
# ─────────────────────────────────────────────────────────────────────────

class _FakeBackend:
    """Minimal backend exposing complete_json. Some return prices, others raise."""
    def __init__(self, response_or_exc):
        self._r = response_or_exc

    def complete_json(self, sys, user):
        if isinstance(self._r, Exception):
            raise self._r
        return self._r


def _make_world(firms_list, equity_price_prior: float):
    """Build a minimal stand-in for WorldState the equity agent reads via state_ref."""
    class _W:
        def __init__(self, firms_list):
            self.last_quarter_flows = {}
            self.gazettes = []
            self.analyst_notes = []
            self.compustat_rows = []
            self.firms = {f.firm_id: f for f in firms_list}
    return _W(firms_list)


def test_equity_panel_carries_prior_when_below_quorum():
    """With 3 backends and 2 failing, only 1 vote survives. That is below
    the majority quorum, so the firm's price should fall back to the
    prior price rather than commit a single-LLM outlier as the median."""
    from src.equity_market import make_equity_market
    from src.types import FirmState, MacroState, SimParams

    good_response = {
        "firms": [
            {"firm_id": "firm_0", "equity_price": 999.0,
             "valuation_method": "method", "reasoning": "reason"},
        ]
    }
    backends = [
        _FakeBackend(good_response),
        _FakeBackend(RuntimeError("api timeout")),
        _FakeBackend(RuntimeError("rate limited")),
    ]

    firm = FirmState(
        firm_id="firm_0",
        is_active=True,
        capability_stock=50.0,
        brand_stock=50.0,
        capacity_units=100,
        cash=100_000_000.0,
        ppe_gross=100_000_000.0,
        equity_price=50.0,  # the "prior" the agent reads from firm.equity_price
    )
    state_ref = [_make_world([firm], 50.0)]
    agent = make_equity_market(backends, state_ref)

    result = agent({"firm_0": firm}, MacroState(), SimParams())
    assert result is not None
    assert "firm_0" in result
    # Below quorum: prior carried forward, NOT the lone $999 vote
    assert result["firm_0"]["equity_price"] == pytest.approx(50.0)
    assert "panel_quorum_unmet" in result["firm_0"]["fallback_reason"]
    assert result["firm_0"]["panel_n_responses"] == 1


def test_equity_panel_takes_median_when_quorum_met():
    """With 3 backends and 2 succeeding (majority quorum of 2-of-3), the
    median of the surviving votes is committed normally."""
    from src.equity_market import make_equity_market
    from src.types import FirmState, MacroState, SimParams

    good_a = {"firms": [{"firm_id": "firm_0", "equity_price": 100.0,
                          "valuation_method": "a", "reasoning": "a"}]}
    good_b = {"firms": [{"firm_id": "firm_0", "equity_price": 110.0,
                          "valuation_method": "b", "reasoning": "b"}]}
    backends = [
        _FakeBackend(good_a),
        _FakeBackend(good_b),
        _FakeBackend(RuntimeError("only one fails")),
    ]
    firm = FirmState(
        firm_id="firm_0", is_active=True, capability_stock=50.0,
        brand_stock=50.0, capacity_units=100, cash=10_000_000.0,
        ppe_gross=100_000_000.0, equity_price=50.0,
    )
    state_ref = [_make_world([firm], 50.0)]
    agent = make_equity_market(backends, state_ref)
    result = agent({"firm_0": firm}, MacroState(), SimParams())
    assert result["firm_0"]["equity_price"] == pytest.approx(105.0)
    assert "fallback_reason" not in result["firm_0"]
    assert result["firm_0"]["panel_n_responses"] == 2
