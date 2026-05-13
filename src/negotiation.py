"""
Wave gamma: multi-round bargaining protocols.

Negotiations are NOT free-form chat. A Negotiation is a stateful protocol
with explicit rounds, offers, counter-offers, outside options, and a
deterministic break/accept condition. Used for:

- Covenant waiver bargaining (borrower vs lender)
- Debt pricing (firm vs investment bank)
- (Future) M&A bidder vs target
- (Future) Activist campaign demand vs firm counter

Each Round is a structured Action (Wave beta). The Negotiation itself
is persisted to `negotiations.jsonl` as one record per completed
negotiation with the full offer history — so researchers can study
bargaining outcomes, number of rounds, concessions, etc.

Key design choices:
- Two-party only for this version (most real-world negotiations are 2-party
  and multi-party requires coalition logic).
- Finite round cap (default 3) with a deterministic break rule if no
  agreement reached. Prevents infinite loops when LLMs disagree forever.
- Each party's offer is STRUCTURED; LLM prose goes into `rationale` but
  the accept/reject + structured counter is what the engine acts on.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Offer:
    """One structured offer within a negotiation round.

    `payload` is the deal terms (e.g., {"rate": 0.08, "threshold": 2.5,
    "fee": 500_000}). `rationale` is LLM prose — stored but not
    authoritative.
    """
    party: str              # "firm_1", "commercial_bank", ...
    round_index: int        # 0 = initial, 1 = first counter, ...
    payload: dict
    rationale: str = ""


@dataclass(frozen=True)
class Round:
    """One complete back-and-forth: proposer offers, counterparty responds."""
    index: int
    proposer_offer: Offer
    counterparty_response: str   # "accept" | "counter" | "reject" | "walk"
    counterparty_counter: Offer | None = None
    counterparty_rationale: str = ""


@dataclass(frozen=True)
class OutsideOption:
    """What each party gets if negotiation breaks down.

    For covenant waiver: borrower's outside option is acceleration
    (usually much worse); lender's is acceleration + recovery at
    liquidation price (also bad for the lender).
    For debt pricing: firm's outside option is no financing; bank's is
    no loan booked.

    `party_utility` scores each party's BATNA. Higher = better.
    """
    party_utilities: dict[str, float] = field(default_factory=dict)
    descriptor: str = ""


@dataclass
class Negotiation:
    """Stateful multi-round protocol between two parties.

    Lifecycle:
        1. Party A submits initial_offer (round 0).
        2. Party B responds with accept / counter / reject / walk.
        3. If counter: Party A responds in round 1. Continue.
        4. Terminates on first accept/reject/walk, or after `max_rounds`.

    Result: `final_offer` + `outcome` ("accepted" | "rejected" |
    "walked_away" | "max_rounds_reached").
    """
    negotiation_id: str
    topic: str              # "covenant_waiver", "debt_pricing", ...
    party_a: str            # "firm_1"
    party_b: str            # "commercial_bank"
    quarter: int
    max_rounds: int = 3
    outside_option: OutsideOption = field(default_factory=OutsideOption)
    rounds: list[Round] = field(default_factory=list)
    outcome: str = "open"   # "open" | "accepted" | "rejected" | "walked_away" | "max_rounds_reached"
    final_offer: Offer | None = None

    @staticmethod
    def new(topic: str, party_a: str, party_b: str, quarter: int,
            max_rounds: int = 3,
            outside_option: OutsideOption | None = None) -> "Negotiation":
        return Negotiation(
            negotiation_id=str(uuid.uuid4()),
            topic=topic,
            party_a=party_a, party_b=party_b,
            quarter=quarter, max_rounds=max_rounds,
            outside_option=outside_option or OutsideOption(),
        )

    def submit_round(self, proposer_offer: Offer,
                     counterparty_response: str,
                     counterparty_counter: Offer | None = None,
                     counterparty_rationale: str = "") -> None:
        """Append one completed round. Sets outcome when terminal."""
        if counterparty_response not in {"accept", "counter", "reject", "walk"}:
            raise ValueError(
                f"counterparty_response must be one of "
                f"accept/counter/reject/walk, got {counterparty_response}"
            )
        r = Round(
            index=len(self.rounds),
            proposer_offer=proposer_offer,
            counterparty_response=counterparty_response,
            counterparty_counter=counterparty_counter,
            counterparty_rationale=counterparty_rationale,
        )
        self.rounds.append(r)

        if counterparty_response == "accept":
            self.outcome = "accepted"
            self.final_offer = proposer_offer
        elif counterparty_response == "reject":
            self.outcome = "rejected"
            self.final_offer = proposer_offer  # rejected terms recorded
        elif counterparty_response == "walk":
            self.outcome = "walked_away"
            self.final_offer = None
        elif (counterparty_response == "counter"
              and len(self.rounds) >= self.max_rounds):
            # Counter on the last allowed round → timeout.
            self.outcome = "max_rounds_reached"
            self.final_offer = counterparty_counter

    def is_open(self) -> bool:
        return self.outcome == "open"

    def to_record(self) -> dict:
        """Flatten to a JSON-serializable dict for negotiations.jsonl."""
        return {
            "negotiation_id": self.negotiation_id,
            "topic": self.topic,
            "party_a": self.party_a,
            "party_b": self.party_b,
            "quarter": self.quarter,
            "max_rounds": self.max_rounds,
            "num_rounds": len(self.rounds),
            "outcome": self.outcome,
            "final_payload": (self.final_offer.payload
                               if self.final_offer else None),
            "final_party": (self.final_offer.party
                             if self.final_offer else None),
            "outside_option_descriptor": self.outside_option.descriptor,
            "outside_option_utilities": dict(self.outside_option.party_utilities),
            "rounds": [
                {
                    "index": r.index,
                    "proposer": r.proposer_offer.party,
                    "proposer_payload": r.proposer_offer.payload,
                    "proposer_rationale": r.proposer_offer.rationale[:400],
                    "response": r.counterparty_response,
                    "counter_payload": (r.counterparty_counter.payload
                                          if r.counterparty_counter else None),
                    "counterparty_rationale": r.counterparty_rationale[:400],
                }
                for r in self.rounds
            ],
        }


# ── Convenience: a simple terminal-round resolver ──────────────────────

def _move_toward(current: dict, target: dict, fraction: float) -> dict:
    """For numeric fields, move from current toward target by `fraction`.

    Used by deterministic counter-offer logic when an LLM isn't available
    or as a sanity bound on LLM counters. Non-numeric fields unchanged.
    """
    out = dict(current)
    for k, v_target in target.items():
        if k in current and isinstance(v_target, (int, float)) and isinstance(current[k], (int, float)):
            out[k] = current[k] + (v_target - current[k]) * fraction
    return out


def midpoint_offer(party: str, round_index: int,
                    offer_a: Offer, offer_b: Offer,
                    rationale: str = "midpoint compromise") -> Offer:
    """Produce a midpoint payload between two offers' numeric fields.

    Useful as a deterministic fallback when both LLMs make reasonable but
    incompatible demands. Non-numeric fields from `offer_a` are preserved.
    """
    payload = dict(offer_a.payload)
    for k, v in offer_b.payload.items():
        if k in payload and isinstance(v, (int, float)) and isinstance(payload[k], (int, float)):
            payload[k] = (payload[k] + v) / 2.0
    return Offer(party=party, round_index=round_index, payload=payload,
                   rationale=rationale)
