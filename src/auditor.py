"""
Auditor agent pool.

4 named audit firms (Big 4 style), each a separate LLM. Runs ANNUALLY
at Q4 only. Each firm is assigned one auditor at creation.

Auditor does NOT directly observe manipulation. The environment controls
what information the auditor receives via env_hints (e.g., "Accrual
patterns for firm_0 show unusual growth" when detection triggers).

Opinions: unqualified | qualified | adverse
Auditor shopping: firm can request change (visible as auditor_change_flag).
Audit fee: scales with firm size + risk.
"""

from __future__ import annotations

from .types import FirmState, CompustatRow, AuditResult
from .llm_backends import LLMBackend, extract_json


AUDITOR_NAMES = {
    "auditor_1": "Hartley & Moran",
    "auditor_2": "Kaplan Pierce",
    "auditor_3": "Eastwood Young",
    "auditor_4": "Nakamura Global",
}


def compute_audit_fee(firm: FirmState) -> float:
    """Compute audit fee based on firm size and complexity.
    Roughly 0.1-0.3% of total assets, with a floor of $500K.
    """
    base = max(500_000, firm.total_assets * 0.002)
    # Risk premium for firms under investigation or with high debt
    if firm.under_sec_investigation:
        base *= 1.5
    if firm.total_liabilities > firm.total_assets * 0.6:
        base *= 1.2
    return base


def build_audit_prompt(
    firm: FirmState,
    compustat_4q: list[dict],
    auditor_name: str,
    prior_opinions: list[AuditResult],
    env_hints: list[str],
    peer_fee_benchmark: float = 0.0,
    is_incumbent: bool = True,
) -> tuple[str, str]:
    """Build annual audit prompt.

    env_hints: controlled information from the environment about anomalies
    the auditor notices (NOT raw manipulation amounts).

    peer_fee_benchmark: deterministic fee estimate based on firm size/risk —
    the auditor sees what a competing auditor would plausibly charge and
    decides its own fee based on the client's specific circumstances.
    """
    incumbent_note = ("You are the INCUMBENT auditor this year."
                      if is_incumbent else
                      "You are considering this engagement as a potential new auditor.")
    system = f"""You are an audit partner at {auditor_name}, conducting the annual audit of {firm.firm_id}.

{incumbent_note} Peer audit firms are likely to charge around ${peer_fee_benchmark:,.0f} for
a firm of this size and risk profile — that's orientation, not a constraint. Set your fee
based on this client's specific risk, complexity, and the relationship value you see; you
may go below the peer benchmark when you want to compete harder (low risk, future cross-sell,
strong control environment) or above it when the engagement warrants a premium.

Review the 4 quarters of financial data and issue an audit opinion. UNQUALIFIED is the
typical outcome when books reconcile and disclosures are adequate. QUALIFIED and ADVERSE
opinions are genuinely rare because audit-worthy issues require the firm's own controls
to fail — issue what the evidence supports, without targeting any particular distribution.

- "unqualified" (CLEAN, default): financials fairly present the firm's position in all
  material respects. Issue this when the books reconcile, disclosures are adequate, and
  you have no substantial evidence of misstatement. Rapid growth, large losses, or heavy
  spending ALONE are not grounds for a non-clean opinion — real firms in emerging markets
  routinely look this way.

- "qualified" (RARE): issue ONLY when you find a specific, material exception in a
  particular account (e.g., a material revenue recognition error, an inadequate
  allowance for receivables, a scope limitation on a subsidiary). Name the specific
  exception in findings.

- "adverse" (VERY RARE): issue ONLY when the financials as a whole are materially misleading
  — multiple material misstatements, evidence of fraud, or pervasive misrepresentation that
  would change a reasonable investor's decision. Requires concrete evidence from the anomalies
  list below, not a judgment that "growth looks suspicious."

going_concern: set to true when cash runway is acutely short AND the firm cannot
plausibly raise capital OR cut costs to survive. Otherwise false.

recommend_restatement: set to true ONLY if you are issuing qualified/adverse AND specific
prior-period misstatements need correction.

Output JSON:
{{"opinion": "unqualified|qualified|adverse", "findings": "...", "going_concern": false, "recommend_restatement": false, "proposed_fee": <$ fee you want to charge>}}

Output ONLY JSON wrapped in ```json ... ```."""

    # Build 4Q financial summary
    q_lines = []
    for r in compustat_4q[-4:]:
        rev = r.get("saleq", 0)
        ni = r.get("niq", 0)
        cash = r.get("cheq", 0)
        cfo = r.get("oancfq", 0)
        q_lines.append(f"  Q{r.get('fqtr', '?')}: Rev=${rev:,.0f} NI=${ni:,.0f} Cash=${cash:,.0f} CFO=${cfo:,.0f}")

    # Prior opinions
    prior_lines = []
    for op in prior_opinions[-3:]:
        prior_lines.append(f"  FY{op.fiscal_year}: {op.opinion} ({op.findings[:60]}...)")

    # Hints from environment (what audit procedures revealed)
    hint_lines = [f"  - {h}" for h in env_hints] if env_hints else ["  (no anomalies detected)"]

    user = f"""ANNUAL AUDIT — {firm.firm_id} (FY{firm.quarter // 4 + 2031})

QUARTERLY FINANCIAL SUMMARY (last 4 quarters):
{chr(10).join(q_lines) if q_lines else '(No data)'}

KEY BALANCE SHEET:
  Total Assets: ${firm.total_assets:,.0f}
  Total Liabilities: ${firm.total_liabilities:,.0f}
  Total Equity: ${firm.total_equity:,.0f}
  Cash: ${firm.cash:,.0f}
  Goodwill: ${firm.goodwill:,.0f}

PRIOR AUDIT OPINIONS:
{chr(10).join(prior_lines) if prior_lines else '  (First audit)'}

AUDIT PROCEDURES — ANOMALIES DETECTED:
{chr(10).join(hint_lines)}

Issue your audit opinion."""

    return system, user


def parse_audit_result(
    response: dict | None,
    firm_id: str,
    auditor_id: str,
    fiscal_year: int,
    fee: float,
) -> AuditResult:
    """Parse LLM response into AuditResult. `fee` here is the benchmark;
    a proposed_fee in the response (if present + sane) overrides it within
    a ±60% band around the benchmark."""
    if response is None:
        return AuditResult(
            firm_id=firm_id, auditor_id=auditor_id, fiscal_year=fiscal_year,
            opinion="unqualified", fee=fee,
        )
    # Fee: auditor may propose its own, bounded around benchmark to prevent
    # absurd outputs. Falls back to benchmark if missing/bad.
    final_fee = fee
    proposed = response.get("proposed_fee")
    try:
        if proposed is not None:
            p = float(proposed)
            if p > 0:
                final_fee = max(fee * 0.4, min(fee * 1.6, p))
    except (TypeError, ValueError):
        pass
    return AuditResult(
        firm_id=firm_id,
        auditor_id=auditor_id,
        fiscal_year=fiscal_year,
        opinion=response.get("opinion", "unqualified"),
        findings=response.get("findings", ""),
        fee=final_fee,
        detected_manipulation=response.get("recommend_restatement", False),
        recommended_restatement=response.get("recommend_restatement", False),
        going_concern=response.get("going_concern", False),
    )


def build_fee_haggle_prompt(firm_id: str, auditor_id: str,
                              auditor_name: str, proposed_fee: float,
                              firm_cash: float, firm_going_concern: bool,
                              prior_fees: list[float]) -> tuple[str, str]:
    """Wave gamma: firm reacts to auditor's proposed fee.

    Firm decides accept / counter (with requested_fee) / reject (walk —
    forces auditor change, rarely used).
    """
    mean_prior = (sum(prior_fees) / len(prior_fees)) if prior_fees else proposed_fee
    system = f"""You are the CFO of {firm_id} reviewing the proposed audit fee from {auditor_name}.

Proposed fee this year: ${proposed_fee:,.0f}
Your firm's prior-year audit fees (mean): ${mean_prior:,.0f}
Your cash on hand: ${firm_cash:,.0f}
Going-concern risk flagged: {firm_going_concern}

You may:
  - ACCEPT: pay the proposed fee and keep the engagement.
  - COUNTER: propose a lower fee (specify `requested_fee`). Counters should
    be plausible relative to the proposal; counters far below the proposal
    risk the auditor walking away.
  - REJECT: refuse, forcing a search for a new auditor (very costly — only
    defensible if the fee is egregiously high vs peers).

Consider:
  - Switching auditors mid-year is disruptive (re-education, delays).
  - A modest counter below the proposed fee often gets accepted.
  - A severe lowball counter usually triggers rejection.

Output JSON:
```json
{{"action": "accept|counter|reject", "requested_fee": <required if counter>, "reasoning": "<1 sentence>"}}
```
Output ONLY JSON wrapped in ```json ... ```."""
    user = "Decide."
    return system, user


def build_auditor_counter_response_prompt(
    auditor_name: str, proposed_fee: float, firm_counter: float,
    firm_reasoning: str,
) -> tuple[str, str]:
    """Auditor's response to firm's counter-offer."""
    pct_of_proposed = (firm_counter / proposed_fee) if proposed_fee > 0 else 0
    system = f"""You are an audit partner at {auditor_name}.

You proposed a fee of ${proposed_fee:,.0f}.
The client countered with ${firm_counter:,.0f} ({pct_of_proposed:.0%} of your proposal).
Client's rationale: {firm_reasoning or "(none given)"}

Decide:
  - ACCEPT the counter: keep the client at the lower fee.
  - STAND (counter with your original fee): insist on your number.
  - WALK AWAY: you won't work at this price; client must find another auditor.

Guidance:
  - If the counter is close to your proposal, usually accept.
  - If meaningfully below, it's judgment — depends on relationship value.
  - If severely below, standing or walking is defensible.
  - Walking away is rare (you lose an engagement); only defensible if the
    client is unreasonable or the risk is higher than the fee supports.

Output JSON:
```json
{{"action": "accept|stand|walk", "final_fee": <number>, "reasoning": "<1 sentence>"}}
```
Output ONLY JSON wrapped in ```json ... ```."""
    user = "Decide."
    return system, user


def make_auditor_pool(backends: dict[str, LLMBackend], state_ref: list):
    """Factory: create auditor pool function.

    backends: {auditor_id -> LLMBackend} for each audit firm.
    Returns a function that audits one firm given its auditor_id.
    """

    def audit_firm(
        firm: FirmState,
        compustat_4q: list[dict],
        prior_opinions: list[AuditResult],
        env_hints: list[str],
    ) -> AuditResult:
        auditor_id = firm.auditor_id
        if not auditor_id or auditor_id not in backends:
            return AuditResult(
                firm_id=firm.firm_id, auditor_id=auditor_id or "none",
                fiscal_year=firm.quarter // 4 + 2031,
            )

        backend = backends[auditor_id]
        auditor_name = AUDITOR_NAMES.get(auditor_id, auditor_id)
        fee = compute_audit_fee(firm)
        is_incumbent = any(op.auditor_id == auditor_id for op in prior_opinions)

        system, user = build_audit_prompt(
            firm, compustat_4q, auditor_name, prior_opinions, env_hints,
            peer_fee_benchmark=fee, is_incumbent=is_incumbent,
        )
        from . import telemetry as _tel
        with _tel.set_role(auditor_id):
            result = backend.complete_json(system, user)
        opinion_result = parse_audit_result(
            result, firm.firm_id, auditor_id,
            firm.quarter // 4 + 2031, fee,
        )
        return opinion_result

    def haggle_fee(
        firm: FirmState, proposed_fee: float,
        prior_fees: list[float], going_concern: bool,
    ) -> dict:
        """Wave gamma: firm-auditor fee haggle. Returns dict with keys:
          - "final_fee": float (the fee actually applied)
          - "haggle_rounds": list of round dicts (firm counter, auditor response)
          - "outcome": "accepted" | "countered_and_accepted" | "countered_and_stood" | "walked"

        Only fires when both firm and auditor have LLM backends. Typically
        1-2 LLM calls on top of the existing audit call.
        """
        auditor_id = firm.auditor_id
        fid = firm.firm_id
        rounds = []
        if auditor_id not in backends:
            return {"final_fee": proposed_fee, "haggle_rounds": rounds,
                     "outcome": "no_negotiation"}
        auditor_backend = backends[auditor_id]
        auditor_name = AUDITOR_NAMES.get(auditor_id, auditor_id)

        # Find a firm backend (firm_agent factories hold these; we can't
        # access them from here). Use the auditor backend as a proxy for
        # the firm's CFO voice — same model, different role. This is a
        # simplification; a richer future version would route through a
        # shared registry of firm backends.
        firm_backend = auditor_backend

        # Round 0: firm reacts to proposed fee
        fsys, fuser = build_fee_haggle_prompt(
            fid, auditor_id, auditor_name, proposed_fee,
            firm.cash, going_concern, prior_fees,
        )
        fresp = firm_backend.complete_json(fsys, fuser)
        if fresp is None:
            return {"final_fee": proposed_fee, "haggle_rounds": rounds,
                     "outcome": "llm_failure"}
        action = str(fresp.get("action", "accept")).strip().lower()
        rounds.append({
            "round": 0, "party": fid, "action": action,
            "requested_fee": fresp.get("requested_fee"),
            "reasoning": str(fresp.get("reasoning", ""))[:300],
        })

        if action == "accept":
            return {"final_fee": proposed_fee, "haggle_rounds": rounds,
                     "outcome": "accepted"}
        if action == "reject":
            # Walk — firm must find another auditor. Keep original fee
            # but record the walk. (Actual auditor-change machinery is
            # future work; for now fee still applies.)
            return {"final_fee": proposed_fee, "haggle_rounds": rounds,
                     "outcome": "walked_no_replacement"}

        # Counter — ask auditor to respond
        firm_counter = float(fresp.get("requested_fee", proposed_fee) or proposed_fee)
        firm_counter = max(0.0, min(firm_counter, proposed_fee * 1.5))  # sanity

        asys, auser = build_auditor_counter_response_prompt(
            auditor_name, proposed_fee, firm_counter,
            fresp.get("reasoning", ""),
        )
        aresp = auditor_backend.complete_json(asys, auser)
        if aresp is None:
            return {"final_fee": proposed_fee, "haggle_rounds": rounds,
                     "outcome": "auditor_llm_failure"}
        a_action = str(aresp.get("action", "stand")).strip().lower()
        try:
            a_final = float(aresp.get("final_fee", proposed_fee))
        except (TypeError, ValueError):
            a_final = proposed_fee
        rounds.append({
            "round": 1, "party": auditor_id, "action": a_action,
            "final_fee": a_final,
            "reasoning": str(aresp.get("reasoning", ""))[:300],
        })

        if a_action == "accept":
            return {"final_fee": firm_counter, "haggle_rounds": rounds,
                     "outcome": "countered_and_accepted"}
        if a_action == "walk":
            return {"final_fee": proposed_fee, "haggle_rounds": rounds,
                     "outcome": "walked_by_auditor"}
        # Stand → auditor's original fee stands
        return {"final_fee": proposed_fee, "haggle_rounds": rounds,
                 "outcome": "countered_and_stood"}

    audit_firm.haggle_fee = haggle_fee  # attach for orchestrator
    return audit_firm
