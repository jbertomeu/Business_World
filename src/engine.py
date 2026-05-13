"""
Wave beta: structured-action adjudication layer.

Enforces CLAUDE-principle 4 (structured actions only) and principle 5
(validation / adjudication / consequence). Every state-changing agent
decision flows through this module:

    1. Agent (firm, auditor, activist, SEC, IB, CB, ...) proposes an Action.
    2. Engine validates + adjudicates (feasibility, authorization, rules).
    3. Engine returns ActionResult with accepted/rejected status, clamps
       applied, enforcement rules triggered, and a proposal_id that links
       the downstream compustat row back to this action.
    4. ActionLog accumulates every proposal (accepted or rejected) for the
       audit trail in `proposals.jsonl`.

This file does NOT re-implement the clamping / env / accounting logic that
already lives elsewhere. It wraps existing call sites in a structured
interface so we can:
  - log every proposal with full justification
  - surface rejections (instead of silent clamps)
  - trace every compustat row back to the action that produced it

Migration strategy: wire firm decisions first (biggest volume), then
progressively migrate IB, auditor, activist, SEC, governance.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Action:
    """A proposal from an agent to mutate world state.

    The payload is STRUCTURED (dict of validated field→value). Natural-
    language reasoning goes in `justification` but is not authoritative —
    the payload is the only thing the engine acts on.
    """

    actor_id: str            # "firm_1", "auditor_2", "activist_1", "sec", "commercial_bank", "investment_bank"
    action_type: str         # "set_quarterly_decisions", "issue_audit_opinion", ...
    payload: dict            # structured parameters
    quarter: int             # when proposed (simulation quarter)
    proposal_id: str = ""    # UUID — auto-filled if empty
    justification: str = ""  # LLM's prose "why" — stored but not authoritative
    source: str = "llm"      # "llm" | "fallback" | "mock" | "rule"

    @staticmethod
    def new(actor_id: str, action_type: str, payload: dict,
            quarter: int, justification: str = "", source: str = "llm"
            ) -> "Action":
        return Action(
            actor_id=actor_id, action_type=action_type, payload=payload,
            quarter=quarter, proposal_id=str(uuid.uuid4()),
            justification=justification, source=source,
        )


@dataclass(frozen=True)
class RejectionEvent:
    """Structured record of a single rejection / clamp applied to an Action.

    Replaces ad-hoc strings in `ClampedDecisions.clamping_log`. Distinguishes
    rejections (action refused entirely) from clamps (action bounded).
    """
    field: str               # the decision field that was rejected/clamped (e.g. "sga_spend")
    kind: str                # "rejected" | "clamped" | "coerced_type"
    proposed_value: float | int | str | None
    adjusted_value: float | int | str | None
    reason: str              # human-readable rule that fired
    rule_id: str = ""        # canonical rule identifier (e.g. "sga_min_floor", "cash_available")


@dataclass(frozen=True)
class ActionResult:
    """Outcome of engine adjudication on an Action.

    `accepted` = any portion of the action executed. For firm decisions,
    this is always True (firms always execute some baseline plan even in
    fallback mode). For other agents (SEC investigations, activist
    campaigns), `accepted=False` is possible.

    `partially_accepted` = action executed with one or more clamps.
    `rejections` = per-field clamp/rejection details.
    `mutations` = human-readable summary of state changes.
    `enforcement_rules` = canonical rule IDs that fired.
    """
    proposal_id: str
    accepted: bool
    partially_accepted: bool = False
    rejections: tuple[RejectionEvent, ...] = field(default_factory=tuple)
    mutations: tuple[str, ...] = field(default_factory=tuple)
    enforcement_rules: tuple[str, ...] = field(default_factory=tuple)


# ── Parsing helpers ────────────────────────────────────────────────────

def parse_clamping_log(proposal_id: str,
                       clamping_messages: list[str]
                       ) -> tuple[RejectionEvent, ...]:
    """Convert legacy free-form clamping_log strings into structured
    RejectionEvents. Until clamping.py is refactored to emit typed
    rejections directly, this keeps the proposal log meaningful.

    The clamping_log contains messages like:
      "sga_spend ${X} < min_floor ${Y} -- raised to ${Y}"
      "rd_spend ${X} capped at available cash ${Y}"
      "price {X} below unit cost {Y}; using cost"

    Heuristic parsing: first word = field, look for $/% values for
    proposed vs adjusted. If parsing fails, still record the message as
    a `kind="clamped"` event with `field="unknown"`.
    """
    import re
    rejections = []
    for msg in clamping_messages:
        if not msg:
            continue
        # Try to extract a field hint
        m = re.match(r"^(\w+)\b", msg.strip())
        field_name = m.group(1) if m else "unknown"
        # Extract dollar amounts if present (for proposed/adjusted)
        dollars = re.findall(r"\$?([\d,]+(?:\.\d+)?)", msg)
        proposed = None
        adjusted = None
        if len(dollars) >= 2:
            try:
                proposed = float(dollars[0].replace(",", ""))
                adjusted = float(dollars[1].replace(",", ""))
            except ValueError:
                pass
        rejections.append(RejectionEvent(
            field=field_name,
            kind="clamped",
            proposed_value=proposed,
            adjusted_value=adjusted,
            reason=msg.strip(),
            rule_id="",  # legacy clamping_log doesn't have rule IDs yet
        ))
    return tuple(rejections)


# ── Actor-class derivation ─────────────────────────────────────────────

def derive_actor_class(actor_id: str) -> str:
    """Map an actor_id to its class for easier log-slicing.

    Wave θ: previously researchers had to bucket actor_ids by string prefix
    (e.g. "auditor_1" vs "auditor_4"). This helper canonicalizes the class
    so proposals.jsonl carries a stable `actor_class` column for filtering.

    Classes: firm | auditor | analyst | sec | commercial_bank |
             investment_bank | activist | board_governance | ma | unknown
    """
    if not actor_id:
        return "unknown"
    aid = actor_id.lower()
    # Order matters: check more-specific prefixes before less-specific
    if aid.startswith("firm_"):
        return "firm"
    if aid.startswith("auditor"):
        return "auditor"
    if aid.startswith("analyst"):
        return "analyst"
    if aid.startswith("sec"):
        return "sec"
    if aid.startswith("commercial"):
        return "commercial_bank"
    if aid.startswith("investment"):
        return "investment_bank"
    if aid.startswith("activist"):
        return "activist"
    if aid.startswith("board"):
        return "board_governance"
    if aid.startswith("ma_") or aid == "m_and_a":
        return "ma"
    if aid.startswith("env") or aid == "environment":
        return "environment"
    return "unknown"


# ── Log ────────────────────────────────────────────────────────────────

class ActionLog:
    """Append-only log of all Actions + their ActionResults.

    Held on WorldState as `action_log` (a list of dicts, not of Action
    objects directly, so the dataclass default_factory pattern stays
    simple and JSON-serializable without a custom encoder).
    """

    @staticmethod
    def quick_record(action_log: list, actor_id: str, action_type: str,
                       payload: dict, quarter: int,
                       justification: str = "", source: str = "llm",
                       accepted: bool = True,
                       enforcement_rules: tuple = (),
                       mutations: tuple = ()) -> str:
        """Convenience: record a minimal Action + fully-accepted result.

        Used by agent migration sites where the decision is already applied
        to state and we just need to log the (Action, outcome) pair. Returns
        the generated proposal_id so the caller can stash it in outputs if
        needed.
        """
        action = Action.new(
            actor_id=actor_id, action_type=action_type, payload=payload,
            quarter=quarter, justification=justification, source=source,
        )
        result = ActionResult(
            proposal_id=action.proposal_id,
            accepted=accepted,
            partially_accepted=False,
            enforcement_rules=tuple(enforcement_rules),
            mutations=tuple(mutations),
        )
        ActionLog.record(action_log, action, result)
        return action.proposal_id

    @staticmethod
    def record(action_log: list, action: Action, result: ActionResult) -> None:
        """Append one (Action, Result) pair to the log."""
        action_log.append({
            "proposal_id": action.proposal_id,
            "actor_id": action.actor_id,
            "actor_class": derive_actor_class(action.actor_id),
            "action_type": action.action_type,
            "quarter": action.quarter,
            "source": action.source,
            "accepted": result.accepted,
            "partially_accepted": result.partially_accepted,
            "enforcement_rules": list(result.enforcement_rules),
            "rejections": [
                {
                    "field": r.field,
                    "kind": r.kind,
                    "proposed": r.proposed_value,
                    "adjusted": r.adjusted_value,
                    "reason": r.reason,
                    "rule_id": r.rule_id,
                }
                for r in result.rejections
            ],
            "mutations": list(result.mutations),
            "payload": action.payload,
            # Cap justification to keep the log file reasonable.
            "justification": (action.justification or "")[:500],
        })
