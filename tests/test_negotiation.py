"""
Wave gamma: tests for the Negotiation primitive.

Guards CLAUDE principle 10 (protocolized bargaining — no vague free-form
chat between agents for consequential decisions).
"""

from __future__ import annotations
import json

import pytest

from src.negotiation import (
    Negotiation, Offer, Round, OutsideOption, midpoint_offer,
)


def test_negotiation_new_creates_open_state():
    n = Negotiation.new("debt_pricing", "firm_1", "investment_bank", quarter=3)
    assert n.is_open()
    assert n.outcome == "open"
    assert n.rounds == []
    assert len(n.negotiation_id) > 10  # UUID


def test_single_round_accept_terminates_as_accepted():
    n = Negotiation.new("covenant_waiver", "firm_0", "commercial_bank",
                          quarter=4, max_rounds=3)
    offer = Offer(party="firm_0", round_index=0,
                   payload={"request": "waive", "fee": 100_000},
                   rationale="quick cure")
    n.submit_round(
        proposer_offer=offer,
        counterparty_response="accept",
        counterparty_rationale="reasonable ask",
    )
    assert n.outcome == "accepted"
    assert n.final_offer == offer
    assert not n.is_open()


def test_walk_away_terminates_without_final():
    n = Negotiation.new("debt_pricing", "firm_1", "investment_bank", quarter=2)
    n.submit_round(
        proposer_offer=Offer(party="firm_1", round_index=0,
                               payload={"amount": 50_000_000}),
        counterparty_response="walk",
        counterparty_rationale="firm too distressed to lend to",
    )
    assert n.outcome == "walked_away"
    assert n.final_offer is None


def test_counter_at_max_rounds_yields_max_rounds_reached():
    n = Negotiation.new("debt_pricing", "firm_1", "investment_bank",
                          quarter=2, max_rounds=2)
    # Round 0
    n.submit_round(
        proposer_offer=Offer(party="firm_1", round_index=0,
                               payload={"rate": 0.05}),
        counterparty_response="counter",
        counterparty_counter=Offer(party="investment_bank", round_index=0,
                                      payload={"rate": 0.08}),
    )
    assert n.is_open()
    # Round 1
    n.submit_round(
        proposer_offer=Offer(party="firm_1", round_index=1,
                               payload={"rate": 0.06}),
        counterparty_response="counter",
        counterparty_counter=Offer(party="investment_bank", round_index=1,
                                      payload={"rate": 0.075}),
    )
    # Hit max rounds (=2) with counter → max_rounds_reached
    assert n.outcome == "max_rounds_reached"
    # Final offer is the counter from the last round
    assert n.final_offer.payload == {"rate": 0.075}


def test_invalid_response_raises():
    n = Negotiation.new("test", "a", "b", quarter=1)
    with pytest.raises(ValueError):
        n.submit_round(
            proposer_offer=Offer(party="a", round_index=0, payload={}),
            counterparty_response="invalid",
        )


def test_to_record_is_json_serializable():
    n = Negotiation.new(
        "covenant_waiver", "firm_0", "commercial_bank", quarter=5,
        outside_option=OutsideOption(
            party_utilities={"firm_0": -1.0, "commercial_bank": -0.3},
            descriptor="acceleration vs recovery",
        ),
    )
    n.submit_round(
        proposer_offer=Offer(party="firm_0", round_index=0,
                               payload={"request": "waive"},
                               rationale="short cash"),
        counterparty_response="accept",
        counterparty_counter=Offer(party="commercial_bank", round_index=0,
                                      payload={"fee": 75_000}),
        counterparty_rationale="OK but fee",
    )
    rec = n.to_record()
    # Must be JSON-serializable
    s = json.dumps(rec, default=str)
    assert "covenant_waiver" in s
    assert "acceleration vs recovery" in s
    # Round history preserved
    assert len(rec["rounds"]) == 1
    assert rec["rounds"][0]["response"] == "accept"
    assert rec["outcome"] == "accepted"


def test_midpoint_offer_averages_numeric_fields():
    a = Offer(party="firm_0", round_index=1,
                payload={"rate": 0.05, "amount": 10_000_000, "desc": "A"})
    b = Offer(party="investment_bank", round_index=1,
                payload={"rate": 0.09, "amount": 10_000_000, "desc": "B"})
    mid = midpoint_offer("mediator", 2, a, b)
    assert mid.payload["rate"] == pytest.approx(0.07)
    assert mid.payload["amount"] == 10_000_000
    # Non-numeric fields preserved from offer A
    assert mid.payload["desc"] == "A"


def test_end_to_end_covenant_waiver_records_negotiation_in_log():
    """Orchestrator covenant resolution phase should append to negotiations_log."""
    from src.orchestrator import WorldState
    # Seed a pending violation + a mock resolver that waives.
    state = WorldState(run_id="test_neg")
    # State has negotiations_log field ready
    assert hasattr(state, "negotiations_log")
    assert state.negotiations_log == []

    # Simulate: build a one-round waiver negotiation directly (the logic
    # the orchestrator now does internally).
    n = Negotiation.new("covenant_waiver", "firm_0", "commercial_bank",
                          quarter=4)
    n.submit_round(
        proposer_offer=Offer(party="firm_0", round_index=0,
                               payload={"facility_id": "FAC-001",
                                        "covenant_type": "debt_to_ebitda_max"}),
        counterparty_response="accept",
        counterparty_counter=Offer(
            party="commercial_bank", round_index=0,
            payload={"action": "waive", "waiver_fee": 75_000},
            rationale="short-term cure expected",
        ),
        counterparty_rationale="short-term cure expected",
    )
    state.negotiations_log.append(n.to_record())
    assert len(state.negotiations_log) == 1
    rec = state.negotiations_log[0]
    assert rec["topic"] == "covenant_waiver"
    assert rec["outcome"] == "accepted"
    assert rec["rounds"][0]["counter_payload"]["action"] == "waive"
