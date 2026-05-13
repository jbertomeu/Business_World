"""
Per-quarter debrief LLM calls (Wave ν+12 item 5).

Every active firm, the environment, every PE fund, and every bank can
emit a short "what happened this quarter and what I learned" note at
the end of each quarter. These notes are stored on
`state.debrief_notes` and surfaced in next quarter's prompts (via
agent_history.render_recent_debriefs).

Design intent (per user direction):
  - Always use a separate LLM for this work (not the agent's own
    backend re-used for both decision and debrief — clear separation
    of concerns).
  - Soft, narrative, qualitative. No numerical thresholds the agent
    must hit. The agent decides what's important to remember.
  - Toggle-able (default ON). Adds N+5 LLM calls per quarter.

End-of-run hook: cross-run LT memory writer (see end of this module).
LT memory toggle is OFF by default in Wave ν+12 per user direction;
infrastructure built but not active.
"""

from __future__ import annotations

from typing import Any

from .llm_backends import LLMBackend
from .types import MacroState
from .agent_history import append_lt_memory


DEBRIEF_SYSTEM_PROMPT = """You are writing a short end-of-quarter debrief
note in your own voice. Your job is to capture what just happened and
what you learned, in a few sentences. These notes are your memory —
you will read them at the start of next quarter, so write them so YOUR
FUTURE SELF can use them.

Good notes:
  - State the concrete event that mattered (a specific decision, a
    specific firm move, a specific number that surprised you).
  - State what you would do differently or what you are now watching for.
  - 2-4 sentences. Plain prose. No bullet points, no markdown headers.

Bad notes:
  - Generic "we monitored the market and continued operations" filler.
  - Restating things you already knew at the start of the quarter.
  - Long lectures.

Output JSON:
```json
{"note": "<your 2-4 sentence debrief>"}
```

Output ONLY the JSON wrapped in ```json ... ```."""


def _safe_json_call(backend: LLMBackend, system: str, user: str) -> dict | None:
    try:
        return backend.complete_json(system, user)
    except Exception:
        return None


def make_firm_debrief_writer(backend: LLMBackend):
    """Factory: returns a function that writes one firm's debrief note."""
    def writer(firm_id: str, quarter: int, summary: str) -> str:
        user = (
            f"You are the CFO of {firm_id}. The quarter that just ended is Q{quarter}.\n\n"
            "WHAT HAPPENED THIS QUARTER (your own actions + the env's response):\n"
            f"{summary}\n\n"
            "Write your 2-4 sentence debrief in your own voice. What mattered? "
            "What surprised you? What are you now watching for?"
        )
        result = _safe_json_call(backend, DEBRIEF_SYSTEM_PROMPT, user)
        if not result:
            return ""
        return str(result.get("note", "")).strip()[:1500]
    return writer


def make_env_debrief_writer(backend: LLMBackend):
    """Factory: returns a function that writes the env's debrief note."""
    def writer(quarter: int, summary: str) -> str:
        user = (
            f"You are the industry environment. Quarter Q{quarter} just ended.\n\n"
            "WHAT HAPPENED THIS QUARTER (your own allocation + R&D decisions + "
            "the narrative you produced):\n"
            f"{summary}\n\n"
            "Write your 2-4 sentence debrief. What did the data tell you that "
            "you might miss next quarter? Which firms surprised you in either "
            "direction? Are you under- or over-granting on anything?"
        )
        result = _safe_json_call(backend, DEBRIEF_SYSTEM_PROMPT, user)
        if not result:
            return ""
        return str(result.get("note", "")).strip()[:1500]
    return writer


def make_intermediary_debrief_writer(backend: LLMBackend, role: str):
    """Factory: returns a function that writes a PE / bank / etc. debrief.
    role ∈ {'pe', 'bank', 'ibank', 'activist', 'auditor', 'sec'}.
    """
    def writer(agent_id: str, quarter: int, summary: str) -> str:
        user = (
            f"You are an intermediary in role '{role}' (agent_id={agent_id}). "
            f"Quarter Q{quarter} just ended.\n\n"
            "WHAT HAPPENED THIS QUARTER (your decisions + the outcomes):\n"
            f"{summary}\n\n"
            "Write your 2-4 sentence debrief. What did you learn about the "
            "firms you interact with? What pattern are you starting to see? "
            "What would you do differently?"
        )
        result = _safe_json_call(backend, DEBRIEF_SYSTEM_PROMPT, user)
        if not result:
            return ""
        return str(result.get("note", "")).strip()[:1500]
    return writer


# ── Summary builders (input to the debrief LLM call) ────────────────────


def build_firm_quarter_summary(firm_id: str, state, macro: MacroState) -> str:
    """Build a compact summary of what happened to one firm this quarter,
    suitable as input to make_firm_debrief_writer.

    Sources: this firm's latest compustat row, last_quarter_flows, any
    env_notes / ibank_feedback / activist campaigns directed at it.
    """
    lines: list[str] = []
    firm = state.firms.get(firm_id)
    if firm is None:
        return ""
    # Latest Compustat row for this firm
    rows = [r for r in (state.compustat_rows or []) if r.firm_id == firm_id]
    if rows:
        rows.sort(key=lambda r: (r.fyearq, r.fqtr))
        r = rows[-1]
        lines.append(
            f"FY{r.fyearq}Q{r.fqtr} financials: revenue ${r.saleq/1e6:.1f}M, "
            f"NI ${r.niq/1e6:.1f}M, cash ${r.cheq/1e6:.1f}M, "
            f"total assets ${r.atq/1e6:.1f}M, total liab ${r.ltq/1e6:.1f}M, "
            f"equity price ${r.prccq:.2f}."
        )
    # Flows
    flows = (state.last_quarter_flows or {}).get(firm_id)
    if flows is not None:
        lines.append(
            f"Operating CF ${getattr(flows, 'cfo', 0)/1e6:.1f}M; "
            f"capex ${getattr(flows, 'capex_invested', 0)/1e6:.1f}M; "
            f"R&D ${getattr(flows, 'rd_expense', 0)/1e6:.1f}M; "
            f"SG&A ${getattr(flows, 'sga_expense', 0)/1e6:.1f}M."
        )
    # Env notes
    env_notes = (state.pending_env_notes or {}).get(firm_id) or []
    if env_notes:
        lines.append("Env said about you: " + " | ".join(env_notes[-2:]))
    # IB feedback
    ibk = (state.pending_ibank_feedback or {}).get(firm_id)
    if ibk:
        md = ibk.get("market_discussion", "")
        rg = ibk.get("retry_guidance", "")
        if md or rg:
            lines.append(f"IB feedback: {md} {rg}".strip())
    # Active campaigns
    campaigns = [c for c in (state.activist_campaigns or [])
                 if c.get("firm_id") == firm_id]
    if campaigns:
        latest = campaigns[-1]
        lines.append(
            f"Activist campaign open: {latest.get('demand_type','?')} - "
            f"{latest.get('demand_specifics','')[:200]}"
        )
    return "\n".join(lines) if lines else "(no notable events this quarter)"


def build_env_quarter_summary(state, macro: MacroState) -> str:
    """Build a compact summary of what the env just did this quarter."""
    lines: list[str] = []
    # Gazette (env's own narrative)
    if state.gazettes:
        last_gazette = state.gazettes[-1]
        if len(last_gazette) > 1200:
            last_gazette = last_gazette[:1200] + "...[truncated]"
        lines.append("Gazette you wrote:\n" + last_gazette)
    # Total demand + active firm count
    active = sum(1 for f in state.firms.values() if f.is_active)
    rows = [r for r in (state.compustat_rows or [])
            if r.fyearq == macro.fyear and r.fqtr == macro.fqtr]
    total_rev = sum(r.saleq for r in rows)
    lines.append(
        f"Active firms: {active}. Industry revenue this Q: ${total_rev/1e6:.0f}M."
    )
    # Generation distribution
    gen_counts: dict[int, int] = {}
    for f in state.firms.values():
        if f.is_active:
            gen_counts[f.product_generation] = gen_counts.get(f.product_generation, 0) + 1
    if gen_counts:
        gen_str = ", ".join(f"Gen{g}: {n}" for g, n in sorted(gen_counts.items()))
        lines.append(f"Generation mix: {gen_str}.")
    return "\n".join(lines) if lines else "(quiet quarter)"


def build_intermediary_quarter_summary(agent_id: str, role: str, state, macro: MacroState) -> str:
    """Compact summary of intermediary's quarter (rough — caller can specialize)."""
    lines: list[str] = []
    if role == "pe":
        recent = [r for r in (state.pe_round_history or [])
                  if getattr(r, "round_quarter", 0) == macro.quarter]
        for r in recent[:5]:
            lines.append(
                f"  PE round: {getattr(r,'firm_id','?')} raised "
                f"${getattr(r,'amount_raised',0)/1e6:.0f}M, post-money "
                f"${getattr(r,'post_money_valuation',0)/1e6:.0f}M"
            )
    elif role in ("bank", "ibank"):
        active_facilities = [f for f in state.firms.values()
                              if (f.revolver_balance > 0 or f.long_term_debt > 0)]
        lines.append(f"  Firms with active debt: {len(active_facilities)}")
    elif role == "activist":
        recent = [c for c in (state.activist_campaigns or [])
                   if c.get("event_quarter") == macro.quarter]
        for c in recent[:3]:
            lines.append(
                f"  Campaign on {c.get('firm_id','?')}: "
                f"{c.get('demand_type','?')} -> "
                f"{c.get('firm_response','pending')}"
            )
    return "\n".join(lines) if lines else "(no notable events)"


# ── End-of-run LT memory writer ────────────────────────────────────────


LT_MEMORY_SYSTEM = """You are summarising a complete N-quarter simulation
into a long-term memory note for future simulations. Your readers will
be agents in OTHER simulations who will inherit your wisdom.

Write 1-2 paragraphs of CONCRETE, ACTIONABLE lessons:
  - What patterns emerged that matter for similar future industries?
  - What did the data show that the agents underweighted?
  - What specific kinds of decisions paid off; what kinds were costly?

Include numerical anchors where meaningful (revenue trajectories,
cumulative R&D milestones, valuation patterns). Don't be excessively
summary-like — be specific. Future agents will read your notes verbatim.

Output a JSON object:
```json
{"lt_memory": "<your 1-2 paragraph LT note>"}
```"""


def make_lt_memory_writer(backend: LLMBackend):
    """Factory: end-of-run writer that synthesizes a role-specific LT note.
    Caller decides whether to actually persist it (gated by toggle).
    """
    def writer(role: str, run_id: str, summary: str) -> str:
        user = (
            f"You are writing the LT-memory note for role '{role}' at end of "
            f"run {run_id}.\n\n"
            "FULL-RUN SUMMARY (scorecard + key events):\n"
            f"{summary}\n\n"
            "Write the 1-2 paragraph LT note. Concrete, numerical where "
            "meaningful, future-actionable."
        )
        result = _safe_json_call(backend, LT_MEMORY_SYSTEM, user)
        if not result:
            return ""
        return str(result.get("lt_memory", "")).strip()
    return writer


def maybe_write_lt_memory(
    role: str,
    run_id: str,
    note: str,
    enabled: bool,
    data_dir: str = "data",
) -> None:
    """Persist LT memory (or no-op when toggle off)."""
    append_lt_memory(role, run_id, note, enabled, data_dir)
