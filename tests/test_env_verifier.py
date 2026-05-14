"""
Tests for the environment output verifier (deterministic anomaly trigger +
LLM verifier path + deterministic clamp fallback).
"""

from __future__ import annotations

import pytest

from src.env_verifier import (
    is_anomalous, make_env_verifier, _deterministic_clamp,
    make_env_validator,
)


# ── is_anomalous (deterministic check) ─────────────────────────────────


def test_is_anomalous_passes_normal_output():
    """Output near recent trend, within production caps, shares ~1.0 → no flag."""
    env_outcome = {
        "total_demand": 100,
        "firm_outcomes": {
            "firm_0": {"units_sold": 60, "market_share": 0.6},
            "firm_1": {"units_sold": 40, "market_share": 0.4},
        },
    }
    flag, reasons = is_anomalous(
        env_outcome,
        recent_quarter_revenues=[10_000_000, 11_000_000, 12_000_000],
        baseline_demand=100,
        production_caps={"firm_0": 100, "firm_1": 100},
    )
    assert flag is False, f"normal output flagged with reasons: {reasons}"
    assert reasons == []


def test_is_anomalous_flags_revenue_trend_violation():
    """total_demand 50x recent trend → H1 flag."""
    env_outcome = {
        "total_demand": 100_000,  # huge spike
        "firm_outcomes": {
            "firm_0": {"units_sold": 100_000, "market_share": 1.0},
        },
    }
    flag, reasons = is_anomalous(
        env_outcome,
        recent_quarter_revenues=[10_000_000, 11_000_000],  # ~110 unit-equiv at $95k
        baseline_demand=200,
        production_caps={"firm_0": 100_000},
    )
    assert flag is True
    assert any("H1" in r for r in reasons)


def test_is_anomalous_flags_baseline_violation():
    """total_demand 10x baseline → H2 flag."""
    env_outcome = {
        "total_demand": 5_000,
        "firm_outcomes": {"firm_0": {"units_sold": 5_000, "market_share": 1.0}},
    }
    flag, reasons = is_anomalous(
        env_outcome,
        recent_quarter_revenues=[],   # no history → H1 cannot fire
        baseline_demand=200,
        production_caps={"firm_0": 5_000},
    )
    assert flag is True
    assert any("H2" in r for r in reasons)


def test_is_anomalous_flags_production_cap_violation():
    """units_sold > 1.05x cap → H3 flag."""
    env_outcome = {
        "total_demand": 200,
        "firm_outcomes": {
            "firm_0": {"units_sold": 200, "market_share": 1.0},  # cap 100
        },
    }
    flag, reasons = is_anomalous(
        env_outcome,
        recent_quarter_revenues=[],
        baseline_demand=200,
        production_caps={"firm_0": 100},
    )
    assert flag is True
    assert any("H3" in r for r in reasons)


def test_is_anomalous_flags_implied_revenue_spike_from_absurd_price():
    """H5: catches the validation v2 case — units within range but a firm
    set price 100x above trend, so implied revenue spikes."""
    env_outcome = {
        "total_demand": 1287,            # within sane unit range
        "firm_outcomes": {
            "firm_3": {"units_sold": 502, "market_share": 0.39},
            "firm_2": {"units_sold": 219, "market_share": 0.17},
            "firm_0": {"units_sold": 250, "market_share": 0.19},
            "firm_1": {"units_sold": 200, "market_share": 0.16},
            "firm_4": {"units_sold": 116, "market_share": 0.09},
        },
    }
    # Firm_3 prices at $12M (the validation v2 anomaly); others at $95K
    firm_prices = {
        "firm_3": 12_000_000,
        "firm_2": 58_000,
        "firm_0": 95_000,
        "firm_1": 95_000,
        "firm_4": 115_000,
    }
    flag, reasons = is_anomalous(
        env_outcome,
        recent_quarter_revenues=[148_000_000],   # ~$148M typical
        baseline_demand=1500,
        production_caps={fid: 1000 for fid in env_outcome["firm_outcomes"]},
        firm_prices=firm_prices,
    )
    assert flag is True
    assert any("H5" in r for r in reasons), f"H5 not in reasons: {reasons}"


def test_is_anomalous_passes_when_prices_normal():
    """No H5 flag when all firms price within normal range."""
    env_outcome = {
        "total_demand": 1500,
        "firm_outcomes": {
            "firm_0": {"units_sold": 800, "market_share": 0.53},
            "firm_1": {"units_sold": 700, "market_share": 0.47},
        },
    }
    firm_prices = {"firm_0": 95_000, "firm_1": 100_000}
    flag, reasons = is_anomalous(
        env_outcome,
        recent_quarter_revenues=[148_000_000, 150_000_000],
        baseline_demand=1500,
        production_caps={"firm_0": 1000, "firm_1": 1000},
        firm_prices=firm_prices,
    )
    # 800×95K + 700×100K = $146M ≈ recent trend
    assert flag is False, f"Normal output flagged: {reasons}"


def test_is_anomalous_flags_share_sum_violation():
    """Shares summing to 1.5 → H4 flag."""
    env_outcome = {
        "total_demand": 100,
        "firm_outcomes": {
            "firm_0": {"units_sold": 60, "market_share": 0.8},
            "firm_1": {"units_sold": 40, "market_share": 0.7},
        },
    }
    flag, reasons = is_anomalous(
        env_outcome, [], 200, {"firm_0": 100, "firm_1": 100},
    )
    assert flag is True
    assert any("H4" in r for r in reasons)


# ── make_env_verifier (LLM path) ─────────────────────────────────────────


class _MockBackend:
    """LLM stub that returns a fixed JSON response."""
    def __init__(self, response):
        self._resp = response

    def complete_json(self, system, user):
        return self._resp


def test_verifier_ratifies_legitimate_big_move():
    """When verifier returns verified=true, env_outcome passes through."""
    env_outcome = {
        "total_demand": 100_000,
        "firm_outcomes": {"firm_0": {"units_sold": 100_000, "market_share": 1.0}},
        "narrative": "huge spike",
    }
    verifier = make_env_verifier(_MockBackend({
        "verified": True,
        "reason": "Catalyst event in Q narrative explains the spike."
    }))
    from src.types import MacroState
    macro = MacroState(quarter=4, fyear=2031, fqtr=4)
    result = verifier(env_outcome, [10e6], 200, {"firm_0": 100_000}, macro,
                      ["H1: total_demand >> trend"])
    assert result["total_demand"] == 100_000  # unchanged
    assert "[VERIFIER REVISED]" not in result["narrative"]


def test_verifier_revises_hallucinated_output():
    """When verifier returns verified=false + revised, output is replaced."""
    env_outcome = {
        "total_demand": 100_000,
        "firm_outcomes": {"firm_0": {"units_sold": 100_000, "market_share": 1.0}},
        "narrative": "huge spike",
    }
    verifier = make_env_verifier(_MockBackend({
        "verified": False,
        "reason": "No catalyst justifies 50x revenue jump.",
        "revised_total_demand": 250,
        "revised_firm_outcomes": [
            {"firm_id": "firm_0", "units_sold": 250, "market_share": 1.0},
        ],
    }))
    from src.types import MacroState
    macro = MacroState(quarter=4, fyear=2031, fqtr=4)
    result = verifier(env_outcome, [10e6], 200, {"firm_0": 100_000}, macro,
                      ["H1"])
    assert result["total_demand"] == 250
    assert result["firm_outcomes"]["firm_0"]["units_sold"] == 250
    assert "[VERIFIER REVISED]" in result["narrative"]


def test_verifier_falls_back_to_clamp_on_llm_failure():
    """When verifier LLM raises or returns None, the deterministic clamp is used."""
    class _FailingBackend:
        def complete_json(self, sys, user):
            raise RuntimeError("network down")

    env_outcome = {
        "total_demand": 100_000,
        "firm_outcomes": {"firm_0": {"units_sold": 100_000, "market_share": 1.0}},
        "narrative": "huge spike",
    }
    verifier = make_env_verifier(_FailingBackend())
    from src.types import MacroState
    macro = MacroState(quarter=4, fyear=2031, fqtr=4)
    result = verifier(env_outcome, [10e6], 200, {"firm_0": 100}, macro, ["H1"])
    # Deterministic clamp caps firm_0 at production cap (100), not 100,000
    assert result["firm_outcomes"]["firm_0"]["units_sold"] == 100
    assert "[DETERMINISTIC CLAMP]" in result["narrative"]


# ── _deterministic_clamp ─────────────────────────────────────────────────


def test_deterministic_clamp_caps_at_production():
    env_outcome = {
        "total_demand": 1000,
        "firm_outcomes": {
            "firm_0": {"units_sold": 800, "market_share": 0.8},
            "firm_1": {"units_sold": 200, "market_share": 0.2},
        },
    }
    out = _deterministic_clamp(env_outcome, 500,
                                {"firm_0": 100, "firm_1": 100})
    # Each capped at 100
    assert out["firm_outcomes"]["firm_0"]["units_sold"] == 100
    assert out["firm_outcomes"]["firm_1"]["units_sold"] == 100
    # Total = 200; shares recomputed
    assert out["total_demand"] == 200
    assert out["firm_outcomes"]["firm_0"]["market_share"] == pytest.approx(0.5)


# ── Orchestrator integration ─────────────────────────────────────────────


def test_orchestrator_skips_verifier_when_no_anomaly():
    """When env output is normal, verifier is never invoked."""
    from src.orchestrator import WorldState, run_quarter
    from src.types import FirmState, RawDecisions, SimParams
    from src.config import RunConfig

    state = WorldState(run_id="test")
    state.firms["firm_0"] = FirmState(
        firm_id="firm_0", is_active=True, cash=100_000_000,
        capacity_units=100, base_unit_cost=40_000,
        ppe_gross=25_000_000, shares_outstanding=10_000_000,
    )
    state.params = SimParams()
    config = RunConfig(env_verification_enabled=True)

    def firm_fn(fid, firm, info, params):
        return RawDecisions(price=95_000, production=50, capex=0,
                             rd_spend=10_000_000,
                             rd_allocation={"product": 1.0, "process": 0, "delivery": 0},
                             sga_spend=2_000_000)

    def env_fn(actions, firms, macro, params):
        return {
            "total_demand": 50,
            "firm_outcomes": {"firm_0": {"units_sold": 50, "market_share": 1.0}},
            "narrative": "normal",
        }

    verifier_calls = []
    def verifier_fn(*args, **kwargs):
        verifier_calls.append(args)
        return args[0]  # pass through

    new_state = run_quarter(state, firm_agent_fn=firm_fn, env_agent_fn=env_fn,
                             env_verifier_fn=verifier_fn, config=config)
    # No anomaly → verifier not called
    assert len(verifier_calls) == 0
    # No anomaly log line either
    anomaly_logs = [m for m in new_state.quarter_log if "ANOMALY" in m]
    assert anomaly_logs == []


def test_orchestrator_invokes_verifier_on_anomaly():
    """When env produces a 50x demand spike, verifier is called."""
    from src.orchestrator import WorldState, run_quarter
    from src.types import FirmState, RawDecisions, SimParams, CompustatRow
    from src.config import RunConfig

    state = WorldState(run_id="test")
    state.firms["firm_0"] = FirmState(
        firm_id="firm_0", is_active=True, cash=100_000_000,
        capacity_units=100, base_unit_cost=40_000,
        ppe_gross=25_000_000, shares_outstanding=10_000_000,
    )
    state.params = SimParams()
    # Seed history so anomaly check has a baseline
    state.compustat_rows = [
        CompustatRow(run_id="r", firm_id="firm_0", fyearq=2031, fqtr=q,
                      saleq=5_000_000) for q in (1, 2, 3)
    ]
    state.quarter = 3   # next quarter is Q4 2031
    config = RunConfig(env_verification_enabled=True)

    def firm_fn(fid, firm, info, params):
        return RawDecisions(price=95_000, production=50, capex=0,
                             rd_spend=10_000_000,
                             rd_allocation={"product": 1.0, "process": 0, "delivery": 0},
                             sga_spend=2_000_000)

    def env_fn(actions, firms, macro, params):
        return {
            "total_demand": 50_000,  # absurd spike
            "firm_outcomes": {"firm_0": {"units_sold": 50_000, "market_share": 1.0}},
            "narrative": "spike",
        }

    verifier_calls = []
    def verifier_fn(env_outcome, recent_revs, baseline_demand,
                     production_caps, macro, reasons):
        verifier_calls.append({"reasons": reasons,
                                "td": env_outcome.get("total_demand")})
        # Return a sensible revision
        return {
            "total_demand": 50,
            "firm_outcomes": {"firm_0": {"units_sold": 50, "market_share": 1.0}},
            "narrative": env_outcome.get("narrative", "") + " [revised]",
        }

    new_state = run_quarter(state, firm_agent_fn=firm_fn, env_agent_fn=env_fn,
                             env_verifier_fn=verifier_fn, config=config)
    assert len(verifier_calls) == 1, "verifier should fire on anomaly"
    assert verifier_calls[0]["td"] == 50_000   # original spike was forwarded
    # Anomaly log line present
    anomaly_logs = [m for m in new_state.quarter_log if "ANOMALY" in m]
    assert len(anomaly_logs) >= 1


# ── Wave ν+11 E9: env validator (second env) ─────────────────────────────


def test_env_validator_ratifies_normal_output():
    """When validator returns verdict=ok, run_quarter does NOT retry env."""
    from src.types import MacroState
    macro = MacroState(quarter=4, fyear=2031, fqtr=4)
    validator = make_env_validator(_MockBackend({
        "verdict": "ok",
        "notes": "",
    }))
    env_outcome = {
        "total_demand": 1500,
        "firm_outcomes": {
            "firm_0": {"units_sold": 800, "market_share": 0.53},
            "firm_1": {"units_sold": 700, "market_share": 0.47},
        },
        "narrative": "normal quarter",
    }
    result = validator(env_outcome, [148e6, 150e6], 1500,
                        {"firm_0": 1000, "firm_1": 1000}, macro)
    assert result["verdict"] == "ok"
    assert result["notes"] == ""


def test_env_validator_sends_back_with_notes():
    """When validator returns send_back, notes are captured."""
    from src.types import MacroState
    macro = MacroState(quarter=4, fyear=2031, fqtr=4)
    validator = make_env_validator(_MockBackend({
        "verdict": "send_back",
        "notes": "Narrative says firm_0 had a breakthrough but its units fell.",
    }))
    env_outcome = {
        "total_demand": 1000,
        "firm_outcomes": {
            "firm_0": {"units_sold": 100, "market_share": 0.10},
        },
        "narrative": "firm_0 breakthrough drove growth",
    }
    result = validator(env_outcome, [50e6], 1000, {"firm_0": 1000}, macro)
    assert result["verdict"] == "send_back"
    assert "breakthrough" in result["notes"]


def test_env_validator_defaults_to_ok_on_llm_error():
    """If the validator backend raises, default to ok (high-bar; don't block on errors)."""
    class _FailingBackend:
        def complete_json(self, sys, user):
            raise RuntimeError("network down")
    from src.types import MacroState
    macro = MacroState(quarter=4, fyear=2031, fqtr=4)
    validator = make_env_validator(_FailingBackend())
    out = validator({"total_demand": 100, "firm_outcomes": {}, "narrative": ""},
                     [], 0, {}, macro)
    assert out["verdict"] == "ok"
    assert "validator error" in out["notes"]


def test_env_validator_caps_unknown_verdict_to_ok():
    """Bogus verdict strings collapse to ok (never accidentally block)."""
    from src.types import MacroState
    macro = MacroState(quarter=4, fyear=2031, fqtr=4)
    validator = make_env_validator(_MockBackend({
        "verdict": "maybe",  # invalid
        "notes": "ambiguous",
    }))
    out = validator({"total_demand": 100, "firm_outcomes": {}, "narrative": ""},
                     [], 0, {}, macro)
    assert out["verdict"] == "ok"


# ── Wave ν+13: STRICT mandatory-Gen-grant deterministic check ────────────


def test_validator_sends_back_when_mandatory_gen_grant_missed():
    """Firm has $500M cumulative R&D, 6Q tenure, Gen 1, but env didn't grant.
    The deterministic Gen check should fire send_back immediately (no LLM)."""
    from src.types import FirmState, MacroState, SimParams, CompustatRow
    macro = MacroState(quarter=6, fyear=2032, fqtr=2)
    params = SimParams(gen_2_rd_threshold=500_000_000)
    firms = {
        "firm_0": FirmState(
            firm_id="firm_0", is_active=True,
            product_generation=1,
            rd_cumulative_product=750_000_000,  # well past Tier-1 threshold
        ),
    }
    # Tenure = 6Q (one compustat row per quarter)
    compustat_rows = [
        CompustatRow(firm_id="firm_0", fyearq=2031+i//4, fqtr=(i%4)+1)
        for i in range(6)
    ]
    env_outcome = {
        "total_demand": 1000,
        "firm_outcomes": {
            "firm_0": {"units_sold": 1000, "market_share": 1.0,
                        "product_advance": False},  # ENV DID NOT GRANT
        },
        "narrative": "All firms continued operations this quarter.",
    }
    validator = make_env_validator(_MockBackend({"verdict": "ok", "notes": ""}))
    out = validator(env_outcome, [], 0, {"firm_0": 1000}, macro,
                     firms=firms, params=params, compustat_rows=compustat_rows)
    assert out["verdict"] == "send_back", f"got: {out}"
    assert "firm_0" in out["notes"]
    assert "MUST advance" in out["notes"] or "MANDATORY" in out["notes"]


def test_validator_passes_when_mandatory_gen_grant_was_given():
    """Same setup, but env DID grant — should pass through (LLM call may add own verdict)."""
    from src.types import FirmState, MacroState, SimParams, CompustatRow
    macro = MacroState(quarter=6, fyear=2032, fqtr=2)
    params = SimParams(gen_2_rd_threshold=500_000_000)
    firms = {
        "firm_0": FirmState(firm_id="firm_0", is_active=True,
                              product_generation=1,
                              rd_cumulative_product=750_000_000),
    }
    compustat_rows = [
        CompustatRow(firm_id="firm_0", fyearq=2031+i//4, fqtr=(i%4)+1)
        for i in range(6)
    ]
    env_outcome = {
        "total_demand": 1000,
        "firm_outcomes": {
            "firm_0": {"units_sold": 1000, "market_share": 1.0,
                        "product_advance": True},  # env GRANTED
        },
        "narrative": "firm_0 received Phase 3 readout this quarter.",
    }
    validator = make_env_validator(_MockBackend({"verdict": "ok", "notes": ""}))
    out = validator(env_outcome, [], 0, {"firm_0": 1000}, macro,
                     firms=firms, params=params, compustat_rows=compustat_rows)
    assert out["verdict"] == "ok"


def test_validator_accepts_named_blocker_for_skipped_gen():
    """Env declined Gen advance for firm_0 but named a specific blocker —
    should not be sent back."""
    from src.types import FirmState, MacroState, SimParams, CompustatRow
    macro = MacroState(quarter=6, fyear=2032, fqtr=2)
    params = SimParams(gen_2_rd_threshold=500_000_000)
    firms = {
        "firm_0": FirmState(firm_id="firm_0", is_active=True,
                              product_generation=1,
                              rd_cumulative_product=750_000_000),
    }
    compustat_rows = [
        CompustatRow(firm_id="firm_0", fyearq=2031+i//4, fqtr=(i%4)+1)
        for i in range(6)
    ]
    env_outcome = {
        "total_demand": 1000,
        "firm_outcomes": {
            "firm_0": {"units_sold": 1000, "market_share": 1.0,
                        "product_advance": False},
        },
        # Narrative names blocker AND firm_0 explicitly
        "narrative": ("firm_0 had a manufacturing failure this quarter. "
                      "Their Gen 2 candidate was pulled from production "
                      "pending a process investigation."),
    }
    validator = make_env_validator(_MockBackend({"verdict": "ok", "notes": ""}))
    out = validator(env_outcome, [], 0, {"firm_0": 1000}, macro,
                     firms=firms, params=params, compustat_rows=compustat_rows)
    assert out["verdict"] == "ok"


def test_validator_skips_gen_check_when_criteria_not_met():
    """Firm has $200M cumulative R&D (below $500M threshold) — no mandatory grant."""
    from src.types import FirmState, MacroState, SimParams, CompustatRow
    macro = MacroState(quarter=6, fyear=2032, fqtr=2)
    params = SimParams(gen_2_rd_threshold=500_000_000)
    firms = {
        "firm_0": FirmState(firm_id="firm_0", is_active=True,
                              product_generation=1,
                              rd_cumulative_product=200_000_000),  # below threshold
    }
    compustat_rows = [
        CompustatRow(firm_id="firm_0", fyearq=2031+i//4, fqtr=(i%4)+1)
        for i in range(6)
    ]
    env_outcome = {
        "total_demand": 1000,
        "firm_outcomes": {
            "firm_0": {"units_sold": 1000, "market_share": 1.0,
                        "product_advance": False},
        },
        "narrative": "Normal quarter.",
    }
    validator = make_env_validator(_MockBackend({"verdict": "ok", "notes": ""}))
    out = validator(env_outcome, [], 0, {"firm_0": 1000}, macro,
                     firms=firms, params=params, compustat_rows=compustat_rows)
    assert out["verdict"] == "ok"


def test_orchestrator_retries_env_on_validator_send_back():
    """When validator says send_back, orchestrator calls env_agent_fn again
    with validator_notes appended, and the retry's output is used."""
    from src.orchestrator import WorldState, run_quarter
    from src.types import FirmState, RawDecisions, SimParams
    from src.config import RunConfig

    state = WorldState(run_id="test")
    state.firms["firm_0"] = FirmState(
        firm_id="firm_0", is_active=True, cash=100_000_000,
        capacity_units=100, base_unit_cost=40_000,
        ppe_gross=25_000_000, shares_outstanding=10_000_000,
    )
    state.params = SimParams()
    config = RunConfig(env_validator_enabled=True)

    def firm_fn(fid, firm, info, params):
        return RawDecisions(price=95_000, production=50, capex=0,
                             rd_spend=10_000_000,
                             rd_allocation={"product": 1.0, "process": 0, "delivery": 0},
                             sga_spend=2_000_000)

    env_call_count = {"n": 0}
    received_notes = {"n": ""}

    def env_fn(actions, firms, macro, params, validator_notes: str = ""):
        env_call_count["n"] += 1
        if validator_notes:
            received_notes["n"] = validator_notes
            return {
                "total_demand": 50,
                "firm_outcomes": {"firm_0": {"units_sold": 50, "market_share": 1.0}},
                "narrative": "fixed: shares now sum to 1.0",
            }
        # First call — produce inconsistent output
        return {
            "total_demand": 50,
            "firm_outcomes": {"firm_0": {"units_sold": 50, "market_share": 0.40}},
            "narrative": "shares sum 0.40 (inconsistent)",
        }

    def validator_fn(env_outcome, recent_revs, baseline_demand,
                      production_caps, macro, **kwargs):
        # Send back unconditionally for the test. Accepts firms/params/
        # compustat_rows kwargs added in Wave ν+13 (Gen-tier check).
        return {"verdict": "send_back", "notes": "shares should sum to 100%"}

    new_state = run_quarter(state, firm_agent_fn=firm_fn, env_agent_fn=env_fn,
                             env_validator_fn=validator_fn, config=config)
    assert env_call_count["n"] == 2, "env should be called twice (initial + retry)"
    assert "shares should sum to 100%" in received_notes["n"]
    # Log should record the send_back
    sb_logs = [m for m in new_state.quarter_log if "VALIDATOR send_back" in m]
    assert len(sb_logs) == 1


def test_orchestrator_skips_validator_when_disabled():
    """env_validator_enabled=False → validator never called even if fn provided."""
    from src.orchestrator import WorldState, run_quarter
    from src.types import FirmState, RawDecisions, SimParams
    from src.config import RunConfig

    state = WorldState(run_id="test")
    state.firms["firm_0"] = FirmState(
        firm_id="firm_0", is_active=True, cash=100_000_000,
        capacity_units=100, base_unit_cost=40_000,
        ppe_gross=25_000_000, shares_outstanding=10_000_000,
    )
    state.params = SimParams()
    config = RunConfig(env_validator_enabled=False)

    def firm_fn(fid, firm, info, params):
        return RawDecisions(price=95_000, production=50, capex=0,
                             rd_spend=10_000_000,
                             rd_allocation={"product": 1.0, "process": 0, "delivery": 0},
                             sga_spend=2_000_000)

    def env_fn(actions, firms, macro, params, validator_notes: str = ""):
        return {
            "total_demand": 50,
            "firm_outcomes": {"firm_0": {"units_sold": 50, "market_share": 1.0}},
            "narrative": "ok",
        }

    validator_calls = []
    def validator_fn(*args, **kwargs):
        validator_calls.append(args)
        return {"verdict": "ok", "notes": ""}

    run_quarter(state, firm_agent_fn=firm_fn, env_agent_fn=env_fn,
                 env_validator_fn=validator_fn, config=config)
    assert validator_calls == [], "validator should not fire when disabled"
