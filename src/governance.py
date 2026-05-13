"""
Board governance agent.

Runs ANNUALLY at Q4. A dedicated LLM evaluates CEO performance,
sets compensation, and can fire the CEO.

CEO types (hidden from board, known to environment):
- aggressive_grower: high risk tolerance, pushes for market share
- conservative_steward: preserves cash, avoids risk
- empire_builder: maximizes firm size, prone to overinvestment
- honest_operator: low manipulation tendency, steady execution

CEO dismissal triggers a 1-quarter search (ceo_search_in_progress = True),
then a new CEO type is assigned (different from predecessor).
"""

from __future__ import annotations

from .types import FirmState, QuarterFlows, MacroState
from .llm_backends import LLMBackend, extract_json


CEO_TYPES = [
    "aggressive_grower",
    "conservative_steward",
    "empire_builder",
    "honest_operator",
]


def build_governance_prompt(
    firm: FirmState,
    flows_4q: list[QuarterFlows],
    macro: MacroState,
    peer_avg_revenue: float = 0.0,
    peer_avg_ni: float = 0.0,
) -> tuple[str, str]:
    """Build annual board governance prompt.

    The board sees the firm's full performance and the CEO's current
    holdings (grants vested/unvested, shares held, shares sold). Board does
    NOT know the CEO's hidden type.

    Open-ended: board proposes a compensation package it judges appropriate
    for this firm's situation, with base + cash bonus + new equity grants
    (RSU and/or options, with a time-based vesting schedule). No hardcoded
    ranges — the LLM decides pay levels and grant structures.
    """
    from .ceo_comp import outstanding_snapshot

    annual_revenue = sum(f.net_sales for f in flows_4q)
    annual_ni = sum(f.reported_net_income for f in flows_4q)
    annual_cfo = sum(f.cfo for f in flows_4q)
    annual_rd = sum(f.rd_expense for f in flows_4q)

    # CEO's current holdings
    snap = outstanding_snapshot(firm, firm.equity_price or 0.01)

    system = f"""You are the board of directors of {firm.firm_id}, conducting the annual CEO review.

The review is a committee deliberation (Wave gamma). Before reaching a
decision, STRUCTURE YOUR REASONING by passing through three perspectives:

  (a) CHAIR'S PERSPECTIVE: strategic direction, CEO's vision execution,
      cultural fit, board relationship. Lean toward retain unless a major
      strategic failure is evident.
  (b) CFO / AUDIT-COMMITTEE PERSPECTIVE: financial discipline, disclosure
      quality, risk management, audit concerns. Lean toward stricter when
      cash burn is high, covenants breached, or going-concern flagged.
  (c) COMPENSATION-COMMITTEE PERSPECTIVE: pay-performance alignment, peer
      benchmarks, retention risk, clawback triggers. Calibrate bonus +
      new grants to actual performance vs. peer averages below.

After hearing all three perspectives explicitly, the FULL BOARD votes on
the three decisions. The `reasoning` field should summarize each
perspective's key point in ~1 sentence each, then the verdict.

Your decisions:
  1. RETAIN, FIRE, or OFFER RETIREMENT to the CEO (retirement available if age ≥ 60)
  2. Set compensation package: base salary, cash bonus, equity grants
     (RSU and/or stock options), and golden parachute (ex-ante severance)
  3. If firing: propose 3 CEO candidates and select one to install

Design the package with purpose. Consider:
  - Pay for performance: cash bonus typically ties to concrete outcomes
    (hit a revenue, NI, or market-cap milestone)
  - Retention: unvested equity keeps talent from leaving; longer vesting =
    more retention power
  - Alignment: large grants of RSU or in-the-money options align CEO with
    shareholders
  - Golden parachute: written ex-ante in the contract as a multiple of base
    salary; paid if the CEO is fired without cause (involuntary termination);
    retirement usually forfeits the parachute per standard plans
  - Market norms: peer CEO pay at similar firms informs the level

If FIRING the CEO: propose 3 candidate profiles and select one. Candidates
can differ by CEO type, age, requested base salary, and requested golden
parachute. The `selected_candidate_index` (0, 1, or 2) picks which one to
install. The firm pays the OUTGOING CEO's current golden_parachute (set
earlier); the INCOMING CEO's requested_golden_parachute becomes the new
ex-ante obligation.

Output JSON:
```json
{{
  "fire_ceo": false,
  "fire_reason": "",
  "offer_retirement": false,
  "base_salary_next_year": <annual $ base>,
  "cash_bonus_this_year": <$ paid for this year's performance, 0 if none>,
  "golden_parachute_amount": <$ ex-ante severance obligation to set/update>,
  "new_rsu_grant": {{
     "shares": <int, 0 if none>,
     "vesting_schedule": [[<quarter_offset>, <fraction>], ...]
  }},
  "new_option_grant": {{
     "shares": <int, 0 if none>,
     "strike_price": <$/share>,
     "vesting_schedule": [[<quarter_offset>, <fraction>], ...]
  }},
  "ceo_candidates": [
     {{"type": "aggressive_grower|conservative_steward|empire_builder|honest_operator",
       "age": <int, 42-62>,
       "requested_base_salary": <annual $>,
       "requested_golden_parachute": <$ ex-ante severance>,
       "profile_note": "<1-2 sentences on candidate's fit>"}},
     ...
  ],
  "selected_candidate_index": 0,
  "reasoning": "<2-3 sentences on pay-performance rationale + hiring rationale>"
}}
```
`ceo_candidates` + `selected_candidate_index` only matter when fire_ceo=true.
Vesting schedule: each entry is (quarters_after_grant, fraction_vesting).
Fractions should sum to ~1.0. Example 4-year annual cliff:
[[4, 0.25], [8, 0.25], [12, 0.25], [16, 0.25]]."""

    user = f"""ANNUAL CEO REVIEW — {firm.firm_id} (FY{macro.fyear})

CEO STATUS:
  Tenure: {firm.ceo_tenure_quarters} quarters
  Age: {firm.ceo_age}
  Retirement eligible: {'YES (age >= 60)' if firm.ceo_age >= 60 else 'no'}
  Mandatory retirement: {'REQUIRED (age >= 65)' if firm.ceo_age >= 65 else 'no'}

CEO CURRENT HOLDINGS:
  Vested RSU shares held: {snap['vested_rsu_held_shares']:,} (retainable even if fired)
  Unvested RSU shares: {snap['unvested_rsu_shares']:,} (forfeited on fire; vested on retire)
  Vested options: {snap['vested_option_shares']:,}
  Unvested options: {snap['unvested_option_shares']:,}
  Intrinsic value of vested options: ${snap['intrinsic_value_vested_options']:,.0f}
  Intrinsic value of unvested equity: ${snap['intrinsic_value_unvested']:,.0f}
  Shares sold to date: {snap['total_shares_sold_to_date']:,}
  Cumulative cash from sales: ${snap['cash_from_sales_cumulative']:,.0f}

CURRENT BASE SALARY: ${firm.ceo_base_salary:,.0f}
CURRENT GOLDEN PARACHUTE (paid if fired): ${firm.ceo_golden_parachute_amount:,.0f}

ANNUAL PERFORMANCE (FY{macro.fyear}):
  Revenue: ${annual_revenue:,.0f} (peer avg: ${peer_avg_revenue:,.0f})
  Net income: ${annual_ni:,.0f} (peer avg: ${peer_avg_ni:,.0f})
  Cash from ops: ${annual_cfo:,.0f}
  R&D spend: ${annual_rd:,.0f}
  Cash position: ${firm.cash:,.0f}
  Equity price: ${firm.equity_price:.2f}/share
  Market cap: ${firm.market_cap:,.0f}

Evaluate and decide the compensation package."""

    return system, user


def _parse_vesting_schedule(raw) -> tuple:
    """Coerce LLM-returned schedule to tuple[(int, float)]. Returns () on invalid."""
    if not isinstance(raw, list):
        return ()
    out = []
    for pair in raw:
        if isinstance(pair, (list, tuple)) and len(pair) >= 2:
            try:
                offset = int(pair[0])
                frac = float(pair[1])
                if offset >= 0 and frac >= 0:
                    out.append((offset, frac))
            except (TypeError, ValueError):
                continue
    return tuple(out)


def _parse_candidates(raw) -> list[dict]:
    """Parse the LLM's `ceo_candidates` list → list of 3 candidate dicts.

    Each candidate: {type, age, requested_base_salary, requested_golden_parachute,
    profile_note}. Falls back to empty list on malformed input.
    """
    if not isinstance(raw, list):
        return []
    out = []
    for c in raw:
        if not isinstance(c, dict):
            continue
        c_type = str(c.get("type", "")).lower()
        if c_type not in CEO_TYPES:
            c_type = "honest_operator"  # structural fallback
        try:
            age = int(c.get("age", 50))
            age = max(30, min(70, age))
        except (TypeError, ValueError):
            age = 50
        try:
            salary = max(0.0, float(c.get("requested_base_salary", 2_000_000)))
        except (TypeError, ValueError):
            salary = 2_000_000.0
        try:
            parachute = max(0.0, float(c.get("requested_golden_parachute", 0)))
        except (TypeError, ValueError):
            parachute = 0.0
        out.append({
            "type": c_type,
            "age": age,
            "requested_base_salary": salary,
            "requested_golden_parachute": parachute,
            "profile_note": str(c.get("profile_note", "")),
        })
    return out


def parse_governance_decision(response: dict | None) -> dict:
    """Parse LLM response into governance decision (open-ended comp package)."""
    if response is None:
        return {
            "fire_ceo": False,
            "offer_retirement": False,
            "base_salary_next_year": 2_000_000,
            "cash_bonus_this_year": 0.0,
            "golden_parachute_amount": 0.0,
            "new_rsu_grant": None,
            "new_option_grant": None,
            "ceo_candidates": [],
            "selected_candidate_index": 0,
            "reasoning": "No changes — default decision.",
        }

    def _num(v, default=0):
        try:
            return float(v) if v is not None else default
        except (TypeError, ValueError):
            return default

    rsu_raw = response.get("new_rsu_grant") or {}
    new_rsu = None
    if isinstance(rsu_raw, dict):
        rsu_shares = int(_num(rsu_raw.get("shares", 0)))
        if rsu_shares > 0:
            sched = _parse_vesting_schedule(rsu_raw.get("vesting_schedule", []))
            if sched:
                new_rsu = {"shares": rsu_shares, "vesting_schedule": sched}

    opt_raw = response.get("new_option_grant") or {}
    new_opt = None
    if isinstance(opt_raw, dict):
        opt_shares = int(_num(opt_raw.get("shares", 0)))
        opt_strike = _num(opt_raw.get("strike_price", 0))
        if opt_shares > 0 and opt_strike > 0:
            sched = _parse_vesting_schedule(opt_raw.get("vesting_schedule", []))
            if sched:
                new_opt = {"shares": opt_shares, "strike_price": opt_strike,
                           "vesting_schedule": sched}

    candidates = _parse_candidates(response.get("ceo_candidates", []))
    try:
        sel_idx = int(response.get("selected_candidate_index", 0))
    except (TypeError, ValueError):
        sel_idx = 0
    sel_idx = max(0, min(sel_idx, max(0, len(candidates) - 1)))

    # B5 fix: golden_parachute_amount returns None when LLM omits the key.
    # This lets the retain path preserve existing parachute (falls back to
    # firm.ceo_golden_parachute_amount). Previous default of 0.0 zeroed
    # the ex-ante obligation on any review that didn't explicitly restate it.
    raw_parachute = response.get("golden_parachute_amount")
    if raw_parachute is None:
        parachute_decision = None
    else:
        parachute_decision = max(0.0, _num(raw_parachute, 0))

    return {
        "fire_ceo": bool(response.get("fire_ceo", False)),
        "fire_reason": str(response.get("fire_reason", "")),
        "offer_retirement": bool(response.get("offer_retirement", False)),
        "base_salary_next_year": _num(response.get("base_salary_next_year", 2_000_000),
                                         2_000_000),
        "cash_bonus_this_year": max(0.0, _num(response.get("cash_bonus_this_year", 0))),
        "golden_parachute_amount": parachute_decision,  # None = keep existing
        "new_rsu_grant": new_rsu,
        "new_option_grant": new_opt,
        "ceo_candidates": candidates,
        "selected_candidate_index": sel_idx,
        "reasoning": str(response.get("reasoning", "")),
    }


def apply_governance_decision(
    firm: FirmState,
    decision: dict,
    rng,
    current_quarter: int = 0,
) -> tuple[FirmState, list]:
    """Apply annual board governance decision.

    Returns (new_firm, grant_events) where grant_events is a list of
    newly-created StockGrant objects (for dataset writing).

    Order of operations:
      1. Fire → forfeit unvested grants; reset CEO (new type, tenure 0).
      2. Retirement → accelerate vesting on unvested; mark CEO retired; firm
         enters CEO search.
      3. Retain → update base salary, pay cash bonus, issue new grants.
    """
    from .ceo_comp import (
        create_grant, forfeit_unvested, accelerate_vesting_on_retirement,
    )
    grant_events: list = []

    # ── Fire path ──
    if decision.get("fire_ceo"):
        # 1. Forfeit unvested grants on the OUTGOING CEO (only their
        #    incarnation — past CEOs' archival records untouched).
        firm = forfeit_unvested(firm)
        # 2. Pay the ex-ante golden parachute on involuntary termination.
        #    Accrues into next quarter's cash_comp_this_q (hits SGA + cash).
        parachute = firm.ceo_golden_parachute_amount
        # 3. Choose the incoming CEO from proposed candidates.
        candidates = decision.get("ceo_candidates", [])
        sel = decision.get("selected_candidate_index", 0)
        if candidates and 0 <= sel < len(candidates):
            incoming = candidates[sel]
            new_type = incoming["type"]
            new_age = incoming["age"]
            new_base = incoming["requested_base_salary"]
            new_parachute = incoming["requested_golden_parachute"]
        else:
            # Structural fallback if LLM didn't propose candidates
            available_types = [t for t in CEO_TYPES if t != firm.ceo_type]
            new_type = rng.choice(available_types) if available_types else firm.ceo_type
            new_age = rng.randint(45, 58)
            new_base = decision.get("base_salary_next_year", firm.ceo_base_salary)
            new_parachute = 0.0
        return firm.evolve(
            ceo_search_in_progress=False,    # candidate immediately installed
            ceo_tenure_quarters=0,
            ceo_incarnation=firm.ceo_incarnation + 1,  # new CEO = new incarnation
            ceo_age=new_age,
            ceo_type=new_type,
            ceo_base_salary=new_base,
            ceo_golden_parachute_amount=new_parachute,
            # Reset CEO-specific live holdings for incoming CEO. Historical
            # grants stay on `ceo_stock_grants` for research record (archival).
            ceo_vested_shares_held=0,
            ceo_shares_sold_cumulative=0,
            ceo_cash_from_sales=0.0,
            ceo_retired=False,
            ceo_retirement_quarter=0,
            # Golden parachute paid to departing CEO: accrues into next Q's
            # cash comp (hits SGA, cash out). Added to existing cash_comp_this_q
            # so any pending fyear salary accrual is preserved.
            ceo_cash_comp_this_q=firm.ceo_cash_comp_this_q + parachute,
        ), grant_events

    # ── Retirement path ──
    # Retirement accelerates the outgoing CEO's unvested grants (they keep
    # them, per prior CEO-comp spec). Golden parachute is FORFEITED on
    # voluntary retirement per standard plan conventions. Incarnation
    # increments so subsequent CEO's grants stay properly attributed.
    if decision.get("offer_retirement") and firm.ceo_age >= 60:
        firm, accelerated = accelerate_vesting_on_retirement(firm)
        # Note: do NOT pay golden_parachute on retirement (forfeited).
        # If candidates are provided, install one; else search mode.
        candidates = decision.get("ceo_candidates", [])
        sel = decision.get("selected_candidate_index", 0)
        if candidates and 0 <= sel < len(candidates):
            incoming = candidates[sel]
            return firm.evolve(
                ceo_retired=True,
                ceo_retirement_quarter=current_quarter,
                ceo_search_in_progress=False,
                ceo_incarnation=firm.ceo_incarnation + 1,
                ceo_age=incoming["age"],
                ceo_type=incoming["type"],
                ceo_base_salary=incoming["requested_base_salary"],
                ceo_golden_parachute_amount=incoming["requested_golden_parachute"],
                ceo_tenure_quarters=0,
                ceo_vested_shares_held=0,
                ceo_shares_sold_cumulative=0,
                ceo_cash_from_sales=0.0,
            ), grant_events
        return firm.evolve(
            ceo_retired=True,
            ceo_retirement_quarter=current_quarter,
            ceo_search_in_progress=True,  # incoming CEO needed next quarter
        ), grant_events

    # ── Retain path ──
    new_base = decision.get("base_salary_next_year", firm.ceo_base_salary)
    cash_bonus = decision.get("cash_bonus_this_year", 0.0)

    # Issue new grants (RSU + option if specified)
    rsu = decision.get("new_rsu_grant")
    if rsu:
        firm, g = create_grant(
            firm, grant_type="rsu", shares=rsu["shares"],
            strike_price=0.0,
            vesting_schedule=rsu["vesting_schedule"],
            grant_quarter=current_quarter,
            share_price_at_grant=firm.equity_price or 0.01,
        )
        grant_events.append(g)
    opt = decision.get("new_option_grant")
    if opt:
        firm, g = create_grant(
            firm, grant_type="stock_option", shares=opt["shares"],
            strike_price=opt["strike_price"],
            vesting_schedule=opt["vesting_schedule"],
            grant_quarter=current_quarter,
            share_price_at_grant=firm.equity_price or 0.01,
        )
        grant_events.append(g)

    # Cash bonus + stock comp FV carry into next quarter's accounting
    # (orchestrator Phase 5.7 accrues base; we add bonus + stock here).
    stock_fv_granted = sum(g.fair_value_at_grant for g in grant_events)
    # Golden parachute: board can set/update as part of retention review.
    # If decision is None (LLM didn't specify), keep existing.
    parachute_spec = decision.get("golden_parachute_amount")
    new_parachute = (parachute_spec if parachute_spec is not None
                     else firm.ceo_golden_parachute_amount)
    firm = firm.evolve(
        ceo_search_in_progress=False,
        ceo_base_salary=new_base,
        ceo_golden_parachute_amount=new_parachute,
        # Carry-forward: next quarter's accrual picks these up. Adding to
        # existing _this_q fields so if governance runs mid-quarter these
        # compound; Phase 5.7 next Q will add base ON TOP.
        ceo_cash_comp_this_q=firm.ceo_cash_comp_this_q + cash_bonus,
        ceo_stock_comp_this_q=firm.ceo_stock_comp_this_q + stock_fv_granted,
    )
    return firm, grant_events


def make_governance_agent(backend: LLMBackend, state_ref: list):
    """Factory: create board governance function."""

    def governance_review(
        firm: FirmState,
        flows_4q: list[QuarterFlows],
        macro: MacroState,
        peer_avg_revenue: float = 0.0,
        peer_avg_ni: float = 0.0,
    ) -> dict:
        system, user = build_governance_prompt(
            firm, flows_4q, macro, peer_avg_revenue, peer_avg_ni,
        )
        result = backend.complete_json(system, user)
        return parse_governance_decision(result)

    return governance_review


# ── Wave θ: 3-LLM board committee ───────────────────────────────────────

_COMMITTEE_PERSPECTIVES = {
    "ceo_voice": (
        "You represent the CEO's perspective in this board meeting. Speak "
        "to what would best serve the firm's long-term strategic vision "
        "and the CEO's ability to execute. Be honest about the CEO's "
        "performance but argue for continuity where reasonable. "
        "You advocate for adequate compensation to retain talent."
    ),
    "cfo_voice": (
        "You represent the CFO's perspective. Your lens is financial "
        "discipline, risk management, and covenant compliance. Flag any "
        "numbers that concern you. Argue for comp structures that reduce "
        "risk-taking incentives if the firm's balance sheet is fragile. "
        "Push back against dilutive equity awards when the firm's cash "
        "is strong."
    ),
    "comp_committee_voice": (
        "You represent the compensation committee's perspective. Focus on "
        "pay-performance alignment, shareholder interests, and external "
        "benchmarking. Recommend clawback provisions and performance-based "
        "vesting where appropriate. Ensure the package is defensible to "
        "shareholders, proxy advisors, and any activist investors."
    ),
}


def build_committee_synthesis_prompt(
    firm: FirmState,
    perspectives: dict[str, dict],
) -> tuple[str, str]:
    """Build the synthesis prompt that combines 3 committee voices.

    `perspectives`: {"ceo_voice": {...rec dict...}, "cfo_voice": {...},
                     "comp_committee_voice": {...}}
    """
    import json as _json
    system = (
        "You are the board chair synthesizing input from three committee "
        "voices (CEO perspective, CFO perspective, compensation committee "
        "perspective). Produce a single governance decision that balances "
        "their views. When voices disagree, prefer the comp-committee "
        "recommendation on pay levels (shareholder-aligned) but weight the "
        "CFO's financial-discipline concerns heavily when covenants are "
        "tight or cash is low.\n\n"
        "Output the FINAL decision as JSON with the same schema each "
        "committee voice used: cash_bonus_this_year, base_salary_next_year, "
        "new_rsu_grant, new_option_grant, fire_ceo, offer_retirement, "
        "rationale, fire_reason (empty if not firing)."
    )
    user = (
        f"FIRM: {firm.firm_id}\n"
        f"CURRENT CEO: type={firm.ceo_type}, tenure={firm.ceo_tenure_quarters}Q, "
        f"salary=${firm.ceo_base_salary:,.0f}\n"
        f"FIRM STATE: cash=${firm.cash/1e6:.1f}M, "
        f"equity=${firm.total_equity/1e6:.1f}M, "
        f"debt=${(firm.revolver_balance + firm.long_term_debt)/1e6:.1f}M\n\n"
        f"--- COMMITTEE INPUT ---\n\n"
    )
    for voice_name, rec in perspectives.items():
        user += f"### {voice_name.upper()} says:\n"
        user += _json.dumps(rec, indent=2, default=str) + "\n\n"
    user += "Synthesize these three views into a single final decision (JSON)."
    return system, user


def make_governance_agent_3llm(backend: LLMBackend, state_ref: list):
    """3-LLM board committee: CEO + CFO + Comp-committee voices + synthesis.

    4× the API cost of the 1-call governance agent (3 perspective calls
    + 1 synthesis call per firm per year). Gated by
    `config.three_llm_board_enabled`.
    """
    from . import telemetry as _tel
    import concurrent.futures as _cf

    def governance_review_3llm(
        firm: FirmState,
        flows_4q: list[QuarterFlows],
        macro: MacroState,
        peer_avg_revenue: float = 0.0,
        peer_avg_ni: float = 0.0,
    ) -> dict:
        base_sys, base_user = build_governance_prompt(
            firm, flows_4q, macro, peer_avg_revenue, peer_avg_ni,
        )

        # Build three perspective-tagged prompts
        def _call_perspective(voice_name: str) -> tuple[str, dict]:
            perspective_framing = _COMMITTEE_PERSPECTIVES[voice_name]
            voice_sys = base_sys + "\n\n--- YOUR PERSPECTIVE ---\n" + perspective_framing
            with _tel.set_role(f"board_{voice_name}"):
                result = backend.complete_json(voice_sys, base_user)
            return voice_name, result or {}

        # Call all 3 voices (parallel — safe, they're independent)
        perspectives: dict[str, dict] = {}
        with _cf.ThreadPoolExecutor(max_workers=3) as pool:
            for voice_name, rec in pool.map(_call_perspective, _COMMITTEE_PERSPECTIVES.keys()):
                perspectives[voice_name] = rec

        # Synthesize
        syn_sys, syn_user = build_committee_synthesis_prompt(firm, perspectives)
        with _tel.set_role("board_synthesis"):
            syn_result = backend.complete_json(syn_sys, syn_user)
        decision = parse_governance_decision(syn_result or {})
        # Attach committee trail for audit
        decision["_committee_voices"] = perspectives
        return decision

    return governance_review_3llm
