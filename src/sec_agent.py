"""
SEC enforcement agent.

Runs every quarter. Scans all firms for red flags (abnormal accruals,
revenue patterns, analyst concerns). Manages investigation state machine.

Investigation flow:
  none -> watching -> investigating -> private_contact -> aaer_pending -> resolved

The SEC does NOT directly observe manipulation. It sees:
- Public Compustat (same as everyone)
- Its own investigation history
- Detection tips from the environment (when detection probability triggers)

INFORMATION BOUNDARY: No access to private firm data, board minutes,
manipulation amounts, or world secrets — unless the environment provides
a detection tip.
"""

from __future__ import annotations

from .types import (
    CompustatRow, MacroState, SECInvestigationState,
)
from .llm_backends import LLMBackend, extract_json


def build_sec_prompt(
    public_compustat: list[dict],
    investigations: dict[str, SECInvestigationState],
    detection_tips: list[str],
    macro: MacroState,
    firm_ids: list[str],
) -> tuple[str, str]:
    """Build SEC surveillance prompt.

    detection_tips are hints from the environment when detection_probability
    triggers (e.g., "Suspicious accrual patterns detected at firm_0").
    """
    system = """You are the SEC Division of Enforcement, monitoring pharmaceutical firms.

Each quarter you review public financial data and decide whether to act.

For each firm, choose ONE action:
- "none": no action, firm appears clean
- "watch": add to watchlist (informal monitoring)
- "investigate": open formal investigation (private, firm not yet notified)
- "private_contact": contact firm privately, request explanation
- "aaer": issue Accounting and Auditing Enforcement Release (public action)
- "resolve": close investigation, no further action

Consider: abnormal accrual patterns, sudden revenue changes, large discretionary
spending shifts, analyst concerns, prior investigation history.

Output JSON:
{"actions": [{"firm_id": "...", "action": "none|watch|investigate|private_contact|aaer|resolve", "reasoning": "..."}]}

Output ONLY JSON wrapped in ```json ... ```."""

    # Build public data summary (last 2 quarters per firm)
    firm_data = {}
    for row in public_compustat:
        fid = row.get("firm_id", "?")
        if fid not in firm_data:
            firm_data[fid] = []
        firm_data[fid].append(row)

    comp_lines = []
    for fid in firm_ids:
        rows = firm_data.get(fid, [])[-2:]  # last 2Q
        for r in rows:
            rev = r.get("saleq", 0)
            ni = r.get("niq", 0)
            cash = r.get("cheq", 0)
            comp_lines.append(f"  {fid} Q{r.get('fqtr', '?')}: Rev=${rev:,.0f} NI=${ni:,.0f} Cash=${cash:,.0f}")

    # Investigation status
    inv_lines = []
    for fid, inv in investigations.items():
        if inv.status != "none":
            inv_lines.append(f"  {fid}: status={inv.status} since Q{inv.started_quarter} severity={inv.severity:.1f}")

    # Detection tips (from environment)
    tip_lines = [f"  - {tip}" for tip in detection_tips] if detection_tips else ["  (no tips)"]

    user = f"""QUARTERLY SURVEILLANCE REPORT:

PUBLIC FINANCIAL DATA:
{chr(10).join(comp_lines) if comp_lines else '(No data yet)'}

ACTIVE INVESTIGATIONS:
{chr(10).join(inv_lines) if inv_lines else '(None)'}

INTELLIGENCE TIPS:
{chr(10).join(tip_lines)}

Firms to review: {', '.join(firm_ids)}
Decide actions for each firm."""

    return system, user


def advance_investigation(
    prior: SECInvestigationState,
    action: str,
    quarter: int,
) -> SECInvestigationState:
    """Advance the investigation state machine based on SEC decision."""
    from dataclasses import replace

    if action == "none" and prior.status == "none":
        return prior  # no change

    if action == "watch":
        if prior.status == "none":
            return replace(prior, status="watching", started_quarter=quarter)
        return prior  # already watching or higher

    if action == "investigate":
        return replace(prior, status="investigating",
                       started_quarter=prior.started_quarter or quarter)

    if action == "private_contact":
        return replace(prior, status="private_contact",
                       private_contact_quarter=quarter)

    if action == "aaer":
        return replace(prior, status="aaer_pending")

    if action == "resolve":
        return replace(prior, status="resolved")

    return prior


def make_sec_agent(backend: LLMBackend, state_ref: list, data_broker=None):
    """Factory: create SEC agent function.

    If data_broker is provided, SEC can query it for anomaly detection
    before making enforcement decisions.
    """

    def sec_surveillance(
        public_compustat: list[dict],
        investigations: dict[str, SECInvestigationState],
        detection_tips: list[str],
        macro: MacroState,
        firm_ids: list[str],
    ) -> dict[str, str]:
        """Run SEC surveillance. Returns {firm_id: action} dict."""

        # Optional: pre-query the Data Broker for anomaly scores
        broker_context = ""
        if data_broker is not None and firm_ids and public_compustat:
            # Ask the broker to flag any unusual accrual patterns
            from .data_access import tiers_for_role
            current_rows = public_compustat  # already filtered to SEC's tier
            # One broker call per quarter scans all firms for anomalies
            for fid in firm_ids[:2]:  # cap at 2 firms per Q (cost control)
                ans = data_broker.answer(
                    agent_role="sec",
                    query_text=f"What is {fid}'s accrual quality relative to peers?",
                    hypothesis=(
                        f"If {fid}'s accrual quality is anomalous relative to peers, "
                        f"escalate surveillance; otherwise, no action warranted."
                    ),
                    current_run_rows=current_rows,
                    quarter=macro.quarter,
                )
                broker_context += f"\n[broker on {fid}]\n{ans[:500]}\n"

        system, user = build_sec_prompt(
            public_compustat, investigations, detection_tips, macro, firm_ids,
        )
        if broker_context:
            user += f"\n\nDATA BROKER ANALYSIS:\n{broker_context}"
        result = backend.complete_json(system, user)

        if result is None:
            return {fid: "none" for fid in firm_ids}

        actions = {}
        for item in result.get("actions", []):
            fid = item.get("firm_id", "")
            action = item.get("action", "none")
            if fid in firm_ids and action in ("none", "watch", "investigate",
                                               "private_contact", "aaer", "resolve"):
                actions[fid] = action

        # Default to "none" for any firm not mentioned
        for fid in firm_ids:
            if fid not in actions:
                actions[fid] = "none"

        return actions

    return sec_surveillance
