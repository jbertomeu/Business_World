"""
Agent history rendering — shared module that turns WorldState into the
historical context blocks every prompt builder needs.

Design intent (Wave ν+12, item 5 from user direction):
  Real-world firms, intermediaries, and an industry-environment observer
  all have access to extensive historical information. Prior iterations
  of these prompts under-served the LLMs by handing them a snapshot of
  the current quarter plus a few recent flows. The LLM was being asked
  "has this firm invested consistently?" while seeing only this-Q's
  R&D spend, "should you grant another loan?" while seeing only this-Q's
  balance sheet, etc. The result: conservative defaults across the board.

  This module fixes that by providing one source of truth for "render
  history for agent X". Each prompt builder calls the function for its
  role (firm / env / pe / bank / activist / auditor / sec) and gets back
  a multi-line block with:

    1. LT MEMORY FROM PRIOR SIMULATIONS (when enabled — toggle off by
       default in Wave ν+12). Reads data/agent_memory/<role>.md.
    2. COMPRESSED HISTORICAL ACCOUNTING (full quarters since Q1 with
       compression: every 4Q for quarters 1..(current-12), then last 8Q
       in full). See compress_quarters().
    3. ACTION + OUTCOME LOG (per quarter: what the firm decided, what
       the env did to them, what the bank/PE said).
    4. NARRATIVE DEBRIEF NOTES (from per-quarter debrief LLM calls;
       written end-of-quarter, surfaced next quarter).
    5. CURRENT STATE summary.

Compression rule:
  - Quarter ≤ 12 before now: keep every 4th quarter (Q1, Q5, Q9, ...,
    Q(current-12) inclusive).
  - Quarter > current-8: keep every quarter.
  - This gives roughly N/4 + 8 rows per firm at quarter N, manageable in
    context even for an 80Q run.

Toggles:
  - history_full_enabled: master switch. Default ON.
  - lt_memory_enabled: cross-run memory. Default OFF (per user
    direction; infrastructure built but disabled).
  - debrief_enabled: per-quarter debrief LLM calls. Default ON.

Files (when LT memory enabled):
  data/agent_memory/firm.md
  data/agent_memory/env.md
  data/agent_memory/pe.md
  data/agent_memory/bank.md
  data/agent_memory/activist.md
  data/agent_memory/auditor.md
  data/agent_memory/sec.md
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Sequence, TYPE_CHECKING

from .types import CompustatRow, FirmState, MacroState

if TYPE_CHECKING:
    from .orchestrator import WorldState


# ── Compression helpers ────────────────────────────────────────────────


def compress_quarters(
    rows: Sequence[CompustatRow],
    current_quarter: int,
    full_recent_q: int = 8,
    compression_every: int = 4,
    compress_after_q: int = 12,
) -> list[CompustatRow]:
    """Return the rows the prompt should keep.

    Rule (per user direction):
      - last `full_recent_q` quarters before current: keep every quarter
      - older quarters (current - full_recent_q and earlier): keep every
        `compression_every`-th quarter

    Rows must be sorted ascending by (fyearq, fqtr); function preserves
    that order in output.
    """
    if not rows:
        return []
    sorted_rows = sorted(rows, key=lambda r: (r.fyearq, r.fqtr))

    def abs_q(r: CompustatRow) -> int:
        # quarters relative to start of sim (Q1 2031); convention from rest of code
        return (r.fyearq - 2031) * 4 + r.fqtr

    threshold = current_quarter - full_recent_q
    kept = []
    for r in sorted_rows:
        q = abs_q(r)
        if q > threshold:
            kept.append(r)  # full detail for last N quarters
        elif q <= compress_after_q:
            # Early quarters: keep every Nth
            if (q - 1) % compression_every == 0:
                kept.append(r)
        else:
            # Middle quarters: also every Nth
            if (q - 1) % compression_every == 0:
                kept.append(r)
    return kept


# ── Row formatters ─────────────────────────────────────────────────────


def _fmt_money(v: float) -> str:
    """Compact money formatter: $1.2B / $345M / $678K / $0."""
    if v == 0:
        return "$0"
    av = abs(v)
    sign = "-" if v < 0 else ""
    if av >= 1e9:
        return f"{sign}${av/1e9:.2f}B"
    if av >= 1e6:
        return f"{sign}${av/1e6:.1f}M"
    if av >= 1e3:
        return f"{sign}${av/1e3:.0f}K"
    return f"{sign}${av:.0f}"


def _row_label(r: CompustatRow) -> str:
    return f"Q{r.fqtr} {r.fyearq}"


def render_is_bs_cf_table(rows: Sequence[CompustatRow], indent: str = "    ") -> str:
    """Compact one-line-per-quarter table of IS + BS + CF highlights.

    Columns: quarter | rev | NI | cash | total_assets | total_liab |
             equity | op_cf | capex | xrd | xsga
    """
    if not rows:
        return f"{indent}(no history yet)"
    header = (
        f"{indent}{'Q':<10} {'rev':>9} {'NI':>9} {'cash':>9} {'AT':>9} "
        f"{'LT':>9} {'CEQ':>9} {'opCF':>9} {'capx':>9} {'R&D':>9} {'SG&A':>9}"
    )
    lines = [header]
    for r in rows:
        lines.append(
            f"{indent}{_row_label(r):<10} "
            f"{_fmt_money(r.saleq):>9} {_fmt_money(r.niq):>9} "
            f"{_fmt_money(r.cheq):>9} {_fmt_money(r.atq):>9} "
            f"{_fmt_money(r.ltq):>9} {_fmt_money(r.ceqq):>9} "
            f"{_fmt_money(r.oancfq):>9} {_fmt_money(r.capxq):>9} "
            f"{_fmt_money(r.xrdq):>9} {_fmt_money(r.xsgaq):>9}"
        )
    return "\n".join(lines)


def render_public_compustat_compact(rows: Sequence[CompustatRow], indent: str = "    ") -> str:
    """Cross-firm public Compustat panel — one row per firm-quarter,
    compact columns suitable for an env/intermediary scanning all firms.
    Columns: q | firm | rev | NI | cash | AT | LT | price.
    """
    if not rows:
        return f"{indent}(no public Compustat data yet)"
    header = (
        f"{indent}{'Q':<10} {'firm':<8} {'rev':>9} {'NI':>9} "
        f"{'cash':>9} {'AT':>9} {'LT':>9} {'price':>8}"
    )
    lines = [header]
    sorted_rows = sorted(rows, key=lambda r: (r.fyearq, r.fqtr, r.firm_id))
    for r in sorted_rows:
        lines.append(
            f"{indent}{_row_label(r):<10} {r.firm_id:<8} "
            f"{_fmt_money(r.saleq):>9} {_fmt_money(r.niq):>9} "
            f"{_fmt_money(r.cheq):>9} {_fmt_money(r.atq):>9} "
            f"{_fmt_money(r.ltq):>9} ${r.prccq:>7.2f}"
        )
    return "\n".join(lines)


# ── Per-firm action log ────────────────────────────────────────────────


def render_firm_action_log(
    firm_id: str,
    state: "WorldState",
    current_quarter: int,
    full_recent_q: int = 8,
    compression_every: int = 4,
) -> str:
    """Compact log of (price, production, capex, R&D, SG&A, equity_raised,
    debt_raised, dividends, buybacks) decisions per quarter for one firm.

    Sourced from state.action_log (where ActionLog records every quarter's
    decision tuple). Applies the same compression rule as
    compress_quarters().
    """
    actions = getattr(state, "action_log", []) or []
    # action_log rows are written by engine.ActionLog.record() with shape:
    # {"proposal_id", "actor_id", "actor_class", "action_type", "quarter",
    #  "source", "accepted", "partially_accepted", "enforcement_rules",
    #  "rejections", "mutations", "payload", "justification"}
    # The firm's quarterly decision uses action_type="set_quarterly_decisions"
    # with actor_id=firm_id and the decision dict as `payload`.
    firm_actions = [
        a for a in actions
        if a.get("actor_id") == firm_id
        and a.get("action_type") == "set_quarterly_decisions"
    ]
    if not firm_actions:
        return "  (no decisions recorded)"
    threshold = current_quarter - full_recent_q
    kept = []
    for a in firm_actions:
        q = a.get("quarter", 0)
        if q > threshold:
            kept.append(a)
        elif (q - 1) % compression_every == 0:
            kept.append(a)
    if not kept:
        return "  (no decisions in this window)"
    lines = [
        f"  {'Q':<4} {'price':>9} {'prod':>6} {'capex':>9} "
        f"{'R&D':>9} {'SG&A':>9} {'eqReq':>9} {'dbtReq':>9} "
        f"{'divs':>8} {'bbk':>8} {'accept':>6}"
    ]
    for a in kept:
        q = a.get("quarter", 0)
        pl = a.get("payload", {}) or {}
        accepted = a.get("accepted", True)
        lines.append(
            f"  Q{q:<3} ${pl.get('price', 0):>8,.0f} "
            f"{pl.get('production', 0):>6} "
            f"{_fmt_money(pl.get('capex', 0)):>9} "
            f"{_fmt_money(pl.get('rd_spend', 0)):>9} "
            f"{_fmt_money(pl.get('sga_spend', 0)):>9} "
            f"{_fmt_money(pl.get('equity_issuance_request', 0)):>9} "
            f"{_fmt_money(pl.get('debt_request', 0)):>9} "
            f"{_fmt_money(pl.get('dividends', 0)):>8} "
            f"{_fmt_money(pl.get('buybacks', 0)):>8} "
            f"{'OK' if accepted else 'REJ':>6}"
        )
    return "\n".join(lines)


# ── Per-quarter debrief notes ──────────────────────────────────────────


def render_recent_debriefs(
    state: "WorldState", role: str, focal_id: str = "", max_quarters: int = 8
) -> str:
    """Render the per-quarter debrief notes for a given role/agent.

    Debrief notes live on `state.debrief_notes` as a list of dicts:
      {"role": "firm"|"env"|"pe_<fund>"|"bank_<id>", "agent_id": <id>,
       "quarter": <int>, "note": <free-text>}
    """
    notes = getattr(state, "debrief_notes", []) or []
    relevant = [
        n for n in notes
        if n.get("role") == role
        and (not focal_id or n.get("agent_id") == focal_id)
    ]
    if not relevant:
        return "  (no debrief notes yet)"
    recent = sorted(relevant, key=lambda n: n.get("quarter", 0))[-max_quarters:]
    lines = []
    for n in recent:
        q = n.get("quarter", 0)
        txt = (n.get("note", "") or "").strip()
        if len(txt) > 600:
            txt = txt[:600] + "...[truncated]"
        lines.append(f"  Q{q}: {txt}")
    return "\n".join(lines) if lines else "  (no debrief notes in window)"


# ── LT memory across simulations ───────────────────────────────────────


def lt_memory_path(role: str, data_dir: str = "data") -> Path:
    return Path(data_dir) / "agent_memory" / f"{role}.md"


def read_lt_memory(role: str, enabled: bool, data_dir: str = "data") -> str:
    """Read the LT-memory markdown file for this role. Returns empty
    string when disabled or file missing.

    Default in Wave ν+12: lt_memory_enabled=False, so this always
    returns ''. Infrastructure built; not yet active.
    """
    if not enabled:
        return ""
    path = lt_memory_path(role, data_dir)
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def append_lt_memory(
    role: str,
    run_id: str,
    body: str,
    enabled: bool,
    data_dir: str = "data",
) -> None:
    """Append a debrief section to the role's LT-memory file.

    No-op when disabled. When enabled, writes to
    data/agent_memory/<role>.md with a run-tagged section header.
    """
    if not enabled or not body:
        return
    path = lt_memory_path(role, data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    sep = "\n\n---\n\n"
    header = f"## Run {run_id}\n\n"
    try:
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        path.write_text(existing + (sep if existing else "") + header + body + "\n",
                         encoding="utf-8")
    except Exception:
        pass  # never block the run on LT-memory write failure


# ── Composed rendering — one per agent type ────────────────────────────


def _firm_rows(state: "WorldState", firm_id: str) -> list[CompustatRow]:
    return [r for r in (state.compustat_rows or []) if r.firm_id == firm_id]


def render_firm_self_history(
    firm: FirmState,
    state: "WorldState",
    macro: MacroState,
    lt_memory_enabled: bool = False,
    data_dir: str = "data",
) -> str:
    """Full historical context for a firm's CFO making a decision.

    Sections:
      A. LT memory from prior sims (gated)
      B. Compressed BS/IS/CF since simulation start
      C. Compressed action log (own decisions + outcomes)
      D. Cumulative R&D + tenure summary
      E. Recent debrief notes (last 8 quarters)
    """
    parts: list[str] = []

    # A. LT memory
    lt = read_lt_memory("firm", lt_memory_enabled, data_dir)
    if lt:
        parts.append(
            "=== LT MEMORY FROM PRIOR SIMULATIONS (firms) ===\n"
            + lt.strip()
        )

    # B. Own BS/IS/CF table
    own_rows = _firm_rows(state, firm.firm_id)
    compressed = compress_quarters(own_rows, macro.quarter)
    parts.append(
        "=== YOUR OWN HISTORICAL FINANCIALS (compressed: every 4Q early, "
        "last 8Q full) ===\n"
        + render_is_bs_cf_table(compressed)
    )

    # C. Action log
    parts.append(
        "=== YOUR DECISION LOG (compressed by same rule) ===\n"
        + render_firm_action_log(firm.firm_id, state, macro.quarter)
    )

    # D. Cumulative R&D + tenure
    tenure_q = sum(1 for r in own_rows)
    parts.append(
        "=== CUMULATIVE NON-ACCOUNTING INVESTMENT ===\n"
        f"  Cumulative product R&D: {_fmt_money(firm.rd_cumulative_product)}\n"
        f"  Cumulative process R&D: {_fmt_money(firm.rd_cumulative_process)}\n"
        f"  Cumulative delivery R&D: {_fmt_money(firm.rd_cumulative_delivery)}\n"
        f"  Operational tenure: {tenure_q} quarters active\n"
        f"  Generation: product=Gen-{firm.product_generation}, "
        f"delivery=Gen-{firm.delivery_generation}\n"
        f"  Capability/Brand: {firm.capability_stock:.0f}/100, "
        f"{firm.brand_stock:.0f}/100"
    )

    # E. Recent debrief notes (this firm only)
    parts.append(
        "=== YOUR RECENT DEBRIEF NOTES (you wrote these end-of-quarter) ===\n"
        + render_recent_debriefs(state, role="firm", focal_id=firm.firm_id)
    )

    return "\n\n".join(parts)


def render_environment_full_history(
    state: "WorldState",
    macro: MacroState,
    lt_memory_enabled: bool = False,
    data_dir: str = "data",
    compress_every: int = 8,          # sparser than firm self-view: cross-firm panel × 80Q × 40F otherwise blows past 50k tokens
    full_recent_q: int = 4,           # last 4Q in full (was 8) — keep env's view in cheaper model context windows
    active_only_action_log: bool = True,  # action log only for currently-active firms (defaulted firms still in Compustat panel)
) -> str:
    """God-mode historical context for the environment LLM.

    Sections:
      A. LT memory from prior sims (gated)
      B. Public Compustat panel — all firms × all quarters (compressed)
      C. Per-firm action log (compressed) — what every firm decided
      D. Cumulative R&D + tenure for every firm
      E. Capital raises log (PE rounds, IPOs, debt issuances)
      F. M&A + default events
      G. Recent env-side debrief notes
      H. Last-quarter detail (every firm's last decision + outcome verbatim)
    """
    parts: list[str] = []

    lt = read_lt_memory("env", lt_memory_enabled, data_dir)
    if lt:
        parts.append(
            "=== LT MEMORY FROM PRIOR SIMULATIONS (environment) ===\n"
            + lt.strip()
        )

    # B. Cross-firm Compustat (public part of the panel) — sparser
    # compression than the firm self-view to keep env prompt size under
    # ~30k tokens even at Q80 × 40 firms.
    rows = state.compustat_rows or []
    compressed_panel = compress_quarters(
        rows, macro.quarter,
        full_recent_q=full_recent_q,
        compression_every=compress_every,
        compress_after_q=compress_every * 2,
    )
    parts.append(
        "=== PUBLIC COMPUSTAT PANEL — ALL FIRMS × COMPRESSED HISTORY ===\n"
        f"(compression: every {compress_every}Q for older history, "
        f"last {full_recent_q}Q in full)\n"
        + render_public_compustat_compact(compressed_panel)
    )

    # C. Per-firm action log — same sparser rule; defaulted firms filtered out
    action_lines = []
    seen_firms = sorted({
        a.get("actor_id", "") for a in (state.action_log or [])
        if a.get("action_type") == "set_quarterly_decisions"
        and a.get("actor_id", "").startswith("firm_")
    })
    if active_only_action_log:
        seen_firms = [
            fid for fid in seen_firms
            if state.firms.get(fid) is not None
            and state.firms[fid].is_active
        ]
    for fid in seen_firms:
        action_lines.append(f"  -- {fid} --")
        action_lines.append(render_firm_action_log(
            fid, state, macro.quarter,
            full_recent_q=full_recent_q,
            compression_every=compress_every,
        ))
    if action_lines:
        parts.append(
            "=== PER-FIRM ACTION LOG (compressed) ===\n"
            + "\n".join(action_lines)
        )

    # D. R&D + tenure + private quality/brand snapshot
    rd_lines = []
    for fid in sorted(state.firms.keys()):
        firm = state.firms[fid]
        tenure_q = sum(1 for r in rows if r.firm_id == fid)
        rd_lines.append(
            f"  {fid}: prodR&D={_fmt_money(firm.rd_cumulative_product)} "
            f"procR&D={_fmt_money(firm.rd_cumulative_process)} "
            f"delivR&D={_fmt_money(firm.rd_cumulative_delivery)} "
            f"tenure={tenure_q}Q Gen={firm.product_generation} "
            f"Q={firm.capability_stock:.0f}/100 B={firm.brand_stock:.0f}/100 "
            f"{'ACTIVE' if firm.is_active else 'INACTIVE'}"
        )
    if rd_lines:
        parts.append(
            "=== PER-FIRM CUMULATIVE INVESTMENT + PRIVATE STATE ===\n"
            + "\n".join(rd_lines)
        )

    # E. Capital raises log
    cap_lines = []
    for ev in getattr(state, "pe_round_history", []) or []:
        cap_lines.append(
            f"  Q{getattr(ev, 'round_quarter', '?')} {getattr(ev, 'firm_id', '?')}: "
            f"{getattr(ev, 'round_type', '?')} "
            f"raised {_fmt_money(getattr(ev, 'amount_raised', 0))} "
            f"post-money {_fmt_money(getattr(ev, 'post_money_valuation', 0))}"
        )
    for ev in getattr(state, "ipo_history", []) or []:
        cap_lines.append(
            f"  Q{getattr(ev, 'ipo_quarter', '?')} {getattr(ev, 'firm_id', '?')}: "
            f"IPO raised {_fmt_money(getattr(ev, 'gross_proceeds', 0))} "
            f"@ ${getattr(ev, 'offer_price', 0):.2f}/sh"
        )
    if cap_lines:
        parts.append(
            "=== CAPITAL RAISES LOG (cumulative) ===\n"
            + "\n".join(cap_lines)
        )

    # F. M&A + default events
    deal_lines = []
    for ev in getattr(state, "completed_acquisitions", []) or []:
        deal_lines.append(
            f"  Q{ev.get('event_quarter', '?')} M&A: "
            f"{ev.get('bidder_id','?')} acquired {ev.get('target_id','?')} "
            f"for {_fmt_money(ev.get('offer_price_total', 0))}"
        )
    for ev in getattr(state, "default_events", []) or []:
        deal_lines.append(
            f"  Q{ev.get('quarter', '?')} DEFAULT: "
            f"{ev.get('firm_id', '?')} → {ev.get('outcome', '?')}"
        )
    if deal_lines:
        parts.append(
            "=== M&A + DEFAULT EVENTS ===\n"
            + "\n".join(deal_lines)
        )

    # G. Env debrief notes
    parts.append(
        "=== YOUR RECENT DEBRIEF NOTES (you wrote these end-of-quarter) ===\n"
        + render_recent_debriefs(state, role="env")
    )

    return "\n\n".join(parts)


def render_intermediary_history(
    state: "WorldState",
    macro: MacroState,
    role: str,                 # "pe" | "bank" | "ibank" | "activist" | "auditor" | "sec"
    client_firm_id: str = "",
    lt_memory_enabled: bool = False,
    data_dir: str = "data",
    compress_every: int = 8,          # sparser cross-firm panel for intermediaries
    full_recent_q: int = 4,
) -> str:
    """History block for an intermediary (PE evaluator, bank, etc.).

    Sees:
      A. LT memory (role-specific, gated)
      B. Full public Compustat panel (compressed)
      C. If client_firm_id given: that firm's compressed BS/IS/CF + action log
      D. Past deals involving this role (PE rounds, debt issuances)
      E. Role-specific debrief notes
    """
    parts: list[str] = []

    lt = read_lt_memory(role, lt_memory_enabled, data_dir)
    if lt:
        parts.append(
            f"=== LT MEMORY FROM PRIOR SIMULATIONS ({role}) ===\n"
            + lt.strip()
        )

    rows = state.compustat_rows or []
    compressed_panel = compress_quarters(
        rows, macro.quarter,
        full_recent_q=full_recent_q,
        compression_every=compress_every,
        compress_after_q=compress_every * 2,
    )
    parts.append(
        "=== PUBLIC COMPUSTAT PANEL — ALL FIRMS × COMPRESSED HISTORY ===\n"
        f"(compression: every {compress_every}Q for older history, "
        f"last {full_recent_q}Q in full)\n"
        + render_public_compustat_compact(compressed_panel)
    )

    if client_firm_id:
        # Client firm gets DENSER history (every 4Q + last 8 full) — the
        # intermediary specifically cares about this firm's trajectory.
        client_rows = [r for r in rows if r.firm_id == client_firm_id]
        compressed_client = compress_quarters(client_rows, macro.quarter)
        parts.append(
            f"=== CLIENT FIRM ({client_firm_id}) FULL HISTORY ===\n"
            + render_is_bs_cf_table(compressed_client)
            + "\n\n  DECISION LOG:\n"
            + render_firm_action_log(client_firm_id, state, macro.quarter)
        )

    # Past role-specific deals
    if role == "pe":
        deals = []
        for ev in getattr(state, "pe_round_history", []) or []:
            deals.append(
                f"  Q{getattr(ev, 'round_quarter', '?')} {getattr(ev, 'firm_id', '?')}: "
                f"{getattr(ev, 'round_type', '?')} "
                f"raised {_fmt_money(getattr(ev, 'amount_raised', 0))} "
                f"post-money {_fmt_money(getattr(ev, 'post_money_valuation', 0))}"
            )
        if deals:
            parts.append("=== PAST PE ROUNDS (industry-wide) ===\n" + "\n".join(deals))
    elif role in ("bank", "ibank"):
        deals = []
        for ev in getattr(state, "debt_facility_history", []) or []:
            deals.append(
                f"  Q{getattr(ev, 'origin_quarter', '?')} "
                f"{getattr(ev, 'firm_id', '?')}: "
                f"{getattr(ev, 'facility_type', '?')} "
                f"{_fmt_money(getattr(ev, 'principal', 0))} "
                f"@ {getattr(ev, 'quarterly_rate', 0)*4:.1%}/yr "
                f"maturity={getattr(ev, 'maturity_quarters', 0)}Q"
            )
        if deals:
            parts.append("=== PAST DEBT FACILITIES (industry-wide) ===\n" + "\n".join(deals))

    parts.append(
        f"=== YOUR RECENT DEBRIEF NOTES ({role}) ===\n"
        + render_recent_debriefs(state, role=role)
    )

    return "\n\n".join(parts)
