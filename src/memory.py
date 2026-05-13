"""
Agent Memory: local accumulation to avoid redundant data transfer.

Each agent maintains a local memory that accumulates over quarters.
Only NEW information is sent each quarter. The memory provides a
summary of its history for prompt inclusion.

Memory tiers:
  ENVIRONMENT:
    - ACCUMULATED OVER RUNS: compustat_all.csv, run_index.csv
    - PUBLIC: gazettes, product specs
    - PRIVATE BY PLAYER: firm reports, board minutes (env sees all)
    - ENV ONLY: world secrets, taste shocks, demand params

  PLAYER (each firm):
    - ACCUMULATED OVER RUNS: compustat_all.csv (public columns only)
    - PUBLIC: gazettes, competitor Compustat filings
    - PRIVATE (own): board minutes, R&D/brand reports, financials, forecasts
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class AgentMemory:
    """Local memory for one agent. Accumulates over quarters.
    Only new items are sent to the LLM each quarter; older items
    are summarized in a compact history line."""

    agent_id: str

    # Accumulated gazettes (public market narratives)
    gazettes: list[str] = field(default_factory=list)

    # Board minutes (firm only — private)
    board_minutes: list[dict] = field(default_factory=list)  # {quarter, consensus, action_items}

    # Forecasts (firm only — private)
    forecasts: list[dict] = field(default_factory=list)  # {quarter, revenue_target, rd_budget, ...}

    # R&D and brand report summaries (firm only — private)
    rd_summaries: list[str] = field(default_factory=list)
    brand_summaries: list[str] = field(default_factory=list)

    # Competitor observations (public)
    competitor_snapshots: list[dict] = field(default_factory=list)  # per-quarter

    # Financial milestones
    milestones: list[str] = field(default_factory=list)

    # Last quarter this memory was updated
    last_quarter: int = 0

    def add_gazette(self, quarter: int, gazette: str):
        """Add a new gazette. Only the latest is sent in prompts."""
        self.gazettes.append(gazette)
        self.last_quarter = quarter

    def add_board_minutes(self, quarter: int, consensus: str, action_items: str,
                          forecast: dict | None = None):
        """Store board meeting outcome."""
        self.board_minutes.append({
            "quarter": quarter,
            "consensus": consensus,
            "action_items": action_items,
        })
        if forecast:
            self.forecasts.append({"quarter": quarter, **forecast})
        self.last_quarter = quarter

    def add_reports(self, quarter: int, rd_summary: str, brand_summary: str):
        """Store operational report summaries."""
        self.rd_summaries.append(rd_summary)
        self.brand_summaries.append(brand_summary)

    def add_milestone(self, text: str):
        """Record a notable event."""
        self.milestones.append(text)

    def get_history_summary(self, max_lines: int = 8) -> str:
        """Compact summary of accumulated memory for prompt inclusion.
        This replaces sending full historical data."""
        lines = []

        n_q = len(self.gazettes)
        if n_q > 0:
            lines.append(f"You have operated for {n_q} quarter(s).")

        # Summarize financial trajectory from board minutes
        if len(self.board_minutes) >= 2:
            first = self.board_minutes[0]
            last = self.board_minutes[-1]
            lines.append(f"Q{first['quarter']} consensus: {first['consensus'][:80]}")
            lines.append(f"Q{last['quarter']} consensus: {last['consensus'][:80]}")

        # Milestones
        for m in self.milestones[-3:]:  # last 3
            lines.append(f"Milestone: {m}")

        # Forecasts performance (if we have last quarter's forecast and this quarter's actuals)
        # This is populated by the board discussion module

        return "\n".join(lines[:max_lines]) if lines else "(first quarter — no history)"

    def get_last_forecast(self) -> dict | None:
        """Get the most recent quarterly forecast for review."""
        return self.forecasts[-1] if self.forecasts else None

    def get_last_board_consensus(self) -> str | None:
        """Get the last board meeting's consensus direction."""
        if self.board_minutes:
            return self.board_minutes[-1].get("consensus", "")
        return None

    def get_last_action_items(self) -> str | None:
        """Get the last board meeting's action items."""
        if self.board_minutes:
            return self.board_minutes[-1].get("action_items", "")
        return None


# ─── Cross-Run Database Query ────────────────────────────────────────────

def query_cross_run_compustat(
    data_dir: str,
    current_revenue: float,
    current_assets: float,
    current_quarter: int,
    max_results: int = 5,
) -> str:
    """Query the accumulated Compustat panel for similar firm-quarters.

    Returns a text summary suitable for prompt inclusion.
    Agents use this to learn from past simulations.
    """
    compustat_path = Path(data_dir) / "compustat_all.csv"
    if not compustat_path.exists():
        return "(no past simulation data available)"

    try:
        # Wave ν+9 Bug M4: explicit utf-8 encoding so company names and
        # narrative fields with non-ASCII characters round-trip cleanly on
        # Windows (where the default cp1252 mangles em-dashes / curly quotes).
        with open(compustat_path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
    except Exception:
        return "(error reading past simulation data)"

    if not rows:
        return "(no past simulation data available)"

    # Find similar firm-quarters by revenue and quarter
    scored = []
    for r in rows:
        try:
            rev = float(r.get("saleq", 0))
            assets = float(r.get("atq", 0))
            q = int(r.get("fqtr", 0))

            # Similarity: closeness in revenue + assets + quarter
            rev_sim = 1 / (1 + abs(rev - current_revenue) / max(1, current_revenue))
            asset_sim = 1 / (1 + abs(assets - current_assets) / max(1, current_assets))
            q_sim = 1 / (1 + abs(q - (current_quarter % 4 + 1)))
            score = rev_sim * 0.4 + asset_sim * 0.3 + q_sim * 0.3

            scored.append((score, r))
        except (ValueError, KeyError):
            continue

    scored.sort(key=lambda x: -x[0])
    top = scored[:max_results]

    if not top:
        return "(no similar firm-quarters found in past data)"

    # Format as summary
    lines = [f"PAST SIMULATION DATA ({len(rows)} firm-quarters across past runs):"]
    lines.append(f"  Similar firms to yours (Rev~${current_revenue/1e6:.0f}M, Assets~${current_assets/1e6:.0f}M):")

    for sim_score, r in top:
        run = r.get("run_id", "?")[-6:]  # last 6 chars of run ID
        fid = r.get("firm_id", "?")
        rev = float(r.get("saleq", 0))
        ni = float(r.get("niq", 0))
        cash = float(r.get("cheq", 0))
        rd = float(r.get("xrdq", 0))
        debt = float(r.get("dlttq", 0))
        price = float(r.get("prccq", 0))
        defaulted = int(r.get("default_flag", 0))

        status = "DEFAULTED" if defaulted else f"Price=${price:.0f}"
        lines.append(
            f"    [{run}] {fid}: Rev=${rev/1e6:.0f}M NI=${ni/1e6:.0f}M "
            f"Cash=${cash/1e6:.0f}M R&D=${rd/1e6:.0f}M Debt=${debt/1e6:.0f}M {status}"
        )

    # Wave λ Fix A: aggregate stats now show MEDIANS not means, and
    # explicitly call out that the per-quarter default rate is NOT the
    # firm-lifetime rate — see `query_cross_run_scores` for tenure-
    # cumulative survival.
    all_revs = sorted(float(r.get("saleq", 0)) for _, r in scored[:30])
    all_rds = sorted(float(r.get("xrdq", 0)) for _, r in scored[:30])
    all_defaults = sum(1 for _, r in scored if int(r.get("default_flag", 0)) == 1)
    if all_revs:
        med_rev = all_revs[len(all_revs)//2]
        med_rd = all_rds[len(all_rds)//2]
        lines.append(
            f"  Median peer firm-quarter (sample of {len(all_revs)}): "
            f"Rev=${med_rev/1e6:.1f}M, R&D=${med_rd/1e6:.1f}M. "
            f"Per-quarter default flag: {all_defaults/max(1,len(scored)):.0%} "
            f"(NOTE: this is a per-quarter snapshot, NOT lifetime "
            f"firm survival — see HISTORICAL FIRM SURVIVAL block for "
            f"cumulative-by-tenure default rates)."
        )

    return "\n".join(lines)


def query_cross_run_scores(data_dir: str) -> str:
    """Query past run scores for strategy insights.

    Wave λ Fix A: anchor on MORTALITY (cumulative default by tenure) and
    MEDIAN (not mean) outcomes. The prior version reported mean NPV +
    "best performer" which encouraged firms to chase the unicorn outcome
    while ignoring base-rate failure risk.
    """
    scores_path = Path(data_dir) / "scores.csv"
    if not scores_path.exists():
        return "(no past scoring data)"

    try:
        # Wave ν+9 Bug M4: explicit utf-8 encoding (see compustat reader above).
        with open(scores_path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
    except Exception:
        return "(error reading past scores)"

    firm_rows = [r for r in rows if r.get("actor_type") == "firm"]
    if not firm_rows:
        return "(no past firm scores)"

    n = len(firm_rows)

    # Cumulative default rate by tenure (firm dies before quarter Q)
    def default_by_tenure(q_threshold: int) -> tuple[int, int]:
        """Returns (n_died_before_threshold, n_with_at_least_threshold_lifespan_potential)."""
        died = 0
        denom = 0
        for r in firm_rows:
            lifespan = int(float(r.get("lifespan_quarters", 0) or 0))
            defaulted = int(float(r.get("defaulted", 0) or 0))
            denom += 1
            # Firm "died before Q" if defaulted AND lifespan < q_threshold
            if defaulted and lifespan < q_threshold:
                died += 1
        return died, denom

    npvs = sorted(float(r.get("equity_npv", 0) or 0) for r in firm_rows)
    p25 = npvs[len(npvs) // 4] if npvs else 0
    p50 = npvs[len(npvs) // 2] if npvs else 0
    p75 = npvs[3 * len(npvs) // 4] if npvs else 0

    # Cumulative default rate at Q4, Q8, Q16
    d4, d4_n = default_by_tenure(4)
    d8, d8_n = default_by_tenure(8)
    d16, d16_n = default_by_tenure(16)

    # Outcome distribution: how many ever became profitable / large?
    profitable = sum(1 for r in firm_rows
                     if float(r.get("equity_npv", 0) or 0) > 0)
    survived = sum(1 for r in firm_rows
                   if int(float(r.get("defaulted", 0) or 0)) == 0)

    lines = [
        f"HISTORICAL FIRM SURVIVAL ({n} firm-incarnations across past runs):",
        "",
        "  Cumulative default rate by tenure:",
        f"    by Q4:  {d4/max(1,d4_n):.0%}  ({d4} of {d4_n} firms died in their first year)",
        f"    by Q8:  {d8/max(1,d8_n):.0%}  ({d8} of {d8_n} firms died in their first 2 years)",
        f"    by Q16: {d16/max(1,d16_n):.0%}  ({d16} of {d16_n} firms died in their first 4 years)",
        "",
        "  Equity NPV distribution (across ALL firms, including failures):",
        f"    p25 = ${p25/1e6:+.0f}M  median = ${p50/1e6:+.0f}M  p75 = ${p75/1e6:+.0f}M",
        "",
        f"  Survivors (still active at run end): {survived}/{n} ({survived/n:.0%})",
        f"  Ever-profitable firms: {profitable}/{n} ({profitable/n:.0%})",
        "",
        "  Reading these stats: median outcomes are usually NEGATIVE, not the",
        "  mean. The few large winners pull the mean up but most firms underperform.",
        "  High capital-efficiency and survival are the dominant predictors of",
        "  reaching profitability. A firm that defaults in Year 1 captured zero",
        "  of the industry's TAM regardless of its strategy.",
    ]

    return "\n".join(lines)
