"""
Wave beta: tests for src/engine.py — structured-action adjudication.

Guards CLAUDE principle 4 (structured actions only) and principle 5
(validation / adjudication / consequence). Specifically:
  - Every firm decision produces one proposal log entry
  - Clamping produces structured RejectionEvents, not free-form strings
  - Compustat rows link back to proposals via `proposal_id`
  - Rejected actions ARE logged (not silently dropped)
"""

from __future__ import annotations
import json
from pathlib import Path

import pytest

from src.engine import (
    Action, ActionResult, ActionLog, RejectionEvent, parse_clamping_log,
)


def test_action_new_generates_unique_proposal_id():
    a1 = Action.new("firm_0", "set_decisions", {"price": 100}, quarter=1)
    a2 = Action.new("firm_0", "set_decisions", {"price": 100}, quarter=1)
    assert a1.proposal_id != a2.proposal_id
    assert len(a1.proposal_id) > 10  # UUID


def test_action_payload_is_structured_dict():
    a = Action.new("firm_1", "issue_equity",
                     {"amount": 50_000_000, "shares": 1_000_000},
                     quarter=3, justification="Fund Gen2 trials")
    assert a.payload["amount"] == 50_000_000
    assert a.justification == "Fund Gen2 trials"


def test_actionlog_record_stores_proposal_and_result():
    log: list = []
    a = Action.new("firm_0", "set_decisions", {"x": 1}, quarter=1,
                     source="llm")
    r = ActionResult(
        proposal_id=a.proposal_id,
        accepted=True,
        partially_accepted=False,
    )
    ActionLog.record(log, a, r)
    assert len(log) == 1
    entry = log[0]
    assert entry["proposal_id"] == a.proposal_id
    assert entry["actor_id"] == "firm_0"
    assert entry["action_type"] == "set_decisions"
    assert entry["source"] == "llm"
    assert entry["accepted"] is True


def test_actionlog_json_serializable():
    """Must round-trip through json.dumps without a custom encoder — critical
    for writing proposals.jsonl."""
    log: list = []
    a = Action.new("firm_0", "set_decisions",
                     {"price": 95_000, "production": 100}, quarter=1)
    r = ActionResult(
        proposal_id=a.proposal_id,
        accepted=True,
        partially_accepted=True,
        rejections=(RejectionEvent(
            field="sga_spend", kind="clamped",
            proposed_value=0, adjusted_value=2_000_000,
            reason="below min floor",
        ),),
        mutations=("sga: 0 -> 2M",),
        enforcement_rules=("sga_min_floor",),
    )
    ActionLog.record(log, a, r)
    # Must serialize cleanly
    serialized = json.dumps(log[0], default=str)
    assert "sga_min_floor" in serialized
    # Must round-trip
    parsed = json.loads(serialized)
    assert parsed["rejections"][0]["field"] == "sga_spend"
    assert parsed["rejections"][0]["proposed"] == 0
    assert parsed["rejections"][0]["adjusted"] == 2_000_000


def test_parse_clamping_log_legacy_messages():
    """The clamping_log historically held free-form strings. Parser turns
    them into typed RejectionEvents so the proposal log has structure."""
    msgs = [
        "sga_spend $0 below min floor $2,000,000 -- raised to $2,000,000",
        "rd_spend $50,000,000 capped at cash $20,000,000",
        "capex $5,000,000 reduced to maintenance floor $100,000",
    ]
    events = parse_clamping_log("prop_test", msgs)
    assert len(events) == 3
    # Each event has a parsed field name + reason
    assert events[0].field == "sga_spend"
    assert events[1].field == "rd_spend"
    assert events[2].field == "capex"
    # All are kind="clamped"
    assert all(e.kind == "clamped" for e in events)
    # All preserve original message in reason
    for e, msg in zip(events, msgs):
        assert e.reason == msg


def test_parse_clamping_log_empty_input():
    assert parse_clamping_log("p", []) == ()


def test_firm_decisions_produce_proposal_log_entry():
    """End-to-end: running a quarter of mock firm decisions should produce
    one proposal log entry per firm-quarter."""
    from src.orchestrator import WorldState, run_quarter
    from src.types import FirmState, RawDecisions, MarketOutcome, SimParams
    from src.config import RunConfig, LLMConfig

    state = WorldState(run_id="test_proposal_log")
    # Start pre-IPO (cash=0, quarter=0) so Phase 2 IPO fires and sets a
    # balanced BS. Otherwise the firm starts with unbalanced assets.
    state.firms["firm_0"] = FirmState(
        firm_id="firm_0", is_active=True, cash=0, quarter=0,
        capacity_units=100, base_unit_cost=40_000,
        ppe_gross=25_000_000,
    )
    state.params = SimParams()
    config = RunConfig()

    def firm_fn(fid, firm, info, params):
        import uuid
        return RawDecisions(
            price=95_000, production=50, capex=0,
            rd_spend=10_000_000,
            rd_allocation={"product": 0.6, "process": 0.2, "delivery": 0.2},
            sga_spend=5_000_000,
            decision_source="llm",
            proposal_id=str(uuid.uuid4()),
            reasoning="Test quarter plan",
        )

    def env_fn(actions, firms, macro, params):
        return {
            "total_demand": 50,
            "firm_outcomes": {"firm_0": {"units_sold": 50, "market_share": 1.0}},
            "narrative": "ok",
        }

    new_state = run_quarter(state, firm_agent_fn=firm_fn, env_agent_fn=env_fn,
                             config=config)
    # Wave θ+ (B-1 audit fix): env also produces an Action record, so
    # action_log has ≥1 entry. Find the firm decision specifically.
    firm_entries = [e for e in new_state.action_log
                    if e["actor_id"] == "firm_0"]
    assert len(firm_entries) == 1
    entry = firm_entries[0]
    assert entry["action_type"] == "set_quarterly_decisions"
    assert entry["quarter"] == 1
    assert entry["source"] == "llm"
    # proposal_id is a UUID
    assert len(entry["proposal_id"]) > 10
    # Env record also present with actor_class="environment"
    env_entries = [e for e in new_state.action_log
                   if e["actor_id"] == "environment"]
    assert len(env_entries) == 1
    assert env_entries[0]["action_type"] == "resolve_market"
    assert env_entries[0]["actor_class"] == "environment"


def test_compustat_row_proposal_id_links_to_action_log():
    """Compustat row's `proposal_id` must match an entry in the action log."""
    from src.orchestrator import WorldState, run_quarter
    from src.types import FirmState, RawDecisions, MarketOutcome, SimParams
    from src.config import RunConfig

    state = WorldState(run_id="test_link")
    # Start pre-IPO (cash=0, quarter=0) so Phase 2 IPO fires and sets a
    # balanced BS. Otherwise the firm starts with unbalanced assets.
    state.firms["firm_0"] = FirmState(
        firm_id="firm_0", is_active=True, cash=0, quarter=0,
        capacity_units=100, base_unit_cost=40_000,
        ppe_gross=25_000_000,
    )
    state.params = SimParams()
    config = RunConfig()

    target_pid = None

    def firm_fn(fid, firm, info, params):
        import uuid
        nonlocal target_pid
        target_pid = str(uuid.uuid4())
        return RawDecisions(
            price=95_000, production=50, capex=0, rd_spend=10_000_000,
            rd_allocation={"product": 0.6, "process": 0.2, "delivery": 0.2},
            sga_spend=5_000_000,
            decision_source="llm", proposal_id=target_pid,
        )

    def env_fn(actions, firms, macro, params):
        return {"total_demand": 50,
                "firm_outcomes": {"firm_0": {"units_sold": 50, "market_share": 1.0}},
                "narrative": "ok"}

    new_state = run_quarter(state, firm_agent_fn=firm_fn, env_agent_fn=env_fn,
                             config=config)
    # The compustat row should have the same proposal_id
    rows = [r for r in new_state.compustat_rows if r.firm_id == "firm_0"]
    assert len(rows) == 1
    assert rows[0].proposal_id == target_pid
    # And the action log has it too
    log_ids = [e["proposal_id"] for e in new_state.action_log]
    assert target_pid in log_ids


def test_rejections_captured_when_decision_is_clamped():
    """Firm proposes infeasible SGA = 0 → clamping raises to min floor
    → RejectionEvent captured in action log."""
    from src.orchestrator import WorldState, run_quarter
    from src.types import FirmState, RawDecisions, SimParams
    from src.config import RunConfig

    state = WorldState(run_id="test_rej")
    # Start pre-IPO (cash=0, quarter=0) so Phase 2 IPO fires and sets a
    # balanced BS. Otherwise the firm starts with unbalanced assets.
    state.firms["firm_0"] = FirmState(
        firm_id="firm_0", is_active=True, cash=0, quarter=0,
        capacity_units=100, base_unit_cost=40_000,
        ppe_gross=25_000_000,
    )
    state.params = SimParams()
    config = RunConfig()

    def firm_fn(fid, firm, info, params):
        # Over-spend way more than available cash → clamping triggers
        # pro-rata scaling with a "drawing X from revolver" or "pro-rata"
        # clamping_log message.
        return RawDecisions(
            price=95_000, production=50, capex=500_000_000,  # 500M capex
            rd_spend=100_000_000,                           # 100M R&D
            rd_allocation={"product": 0.6, "process": 0.2, "delivery": 0.2},
            sga_spend=50_000_000,                            # 50M SGA
            decision_source="llm", proposal_id="test_rej_prop",
        )

    def env_fn(actions, firms, macro, params):
        return {"total_demand": 50,
                "firm_outcomes": {"firm_0": {"units_sold": 50, "market_share": 1.0}},
                "narrative": "ok"}

    new_state = run_quarter(state, firm_agent_fn=firm_fn, env_agent_fn=env_fn,
                             config=config)
    entry = new_state.action_log[0]
    # Was partially accepted because clamping fired
    assert entry["partially_accepted"] is True
    # Has at least one rejection event
    assert len(entry["rejections"]) >= 1
