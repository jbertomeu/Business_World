"""
Board Discussion: structured management deliberation before each quarterly decision.

Three-part process each quarter:
  Part A: FORECAST REVIEW — compare last quarter's plan vs actuals
  Part B: BOARD DISCUSSION — CEO strategy, CFO financing plan, COO operations
  Part C: BUSINESS PLAN — agreed forecast for next quarter (P&L, CF, targets)

The output (BoardMinutes) includes the full discussion + forecast.
The forecast is stored in memory and compared against actuals next quarter.

All board content is PRIVATE to the firm — never shared with competitors
or the environment agent.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .types import FirmState, SimParams
from .memory import AgentMemory, query_cross_run_compustat, query_cross_run_scores
from .operational_reports import RDReport, BrandReport
from .analyst import run_firm_analysis


@dataclass
class BoardMinutes:
    """Output of one quarterly board meeting."""
    firm_id: str
    quarter: int
    full_text: str = ""
    consensus: str = ""
    action_items: str = ""
    forecast: dict = field(default_factory=dict)  # next Q plan


BOARD_SYSTEM_PROMPT = """You are simulating a quarterly board meeting for {company_name}.

THREE PARTS to this meeting:

PART A: FORECAST REVIEW
If there was a forecast from last quarter, compare plan vs actuals.
State which targets were HIT and which were MISSED, with numbers.

PART B: EXECUTIVE DISCUSSION
Three executives present their areas:

CEO ({ceo_style}):
  # NOTE (Wave ν+9 Bug L1): {ceo_style} is a flavor tag deterministic from
  # firm_id; it is NOT the hidden CEO type used by the governance agent.
  # The board legitimately knows the CEO's public investing style; the
  # hidden personality type that drives behavioural variation is supplied
  # separately to the firm-decision agent and never to the board.
  Present STRATEGIC DIRECTION with specific pricing and positioning recommendations.
  Include: target price, expected market share impact, competitive response analysis.
  Build a 4-quarter revenue projection based on your recommended price and expected volume.

CFO:
  Present a FINANCING PLAN with concrete options. Calculate:
  * Current cash runway (cash / quarterly burn rate)
  * Option A: Status quo — how many quarters until cash runs out
  * Option B: Borrow $X at Y%/Q — interest cost, extended runway, debt service burden
  * Option C: Issue equity — shares needed, dilution %, capital raised
  * Option D: Cut spending — what to cut, savings, impact on Gen 2 timeline
  * RECOMMEND one option with specific numbers.

COO:
  Present an OPERATIONAL PLAN covering:
  * Production: recommended level vs capacity, inventory management
  * R&D allocation: specific $M to product/process/delivery with expected outcomes
  * Marketing: SGA budget, physician outreach targets, brand growth projection
  * Capex: maintenance needs, expansion plans
  * Gen 2 timeline: quarters to threshold at current investment rate

DEBATE: Executives disagree on at least one key issue. The CFO and CEO
  often clash on R&D spending vs cash preservation. Resolve the disagreement.

PART C: AGREED BUSINESS PLAN FOR NEXT QUARTER
Output a specific forecast:
  FORECAST:
  price: $X
  production: N units
  revenue_target: $X (price × expected units sold)
  rd_spend: $X (product $X / process $X / delivery $X)
  sga_spend: $X
  capex: $X
  expected_ni: $X
  expected_end_cash: $X
  debt_request: $X (if CFO recommends borrowing)
  equity_request: $X (if CFO recommends equity raise)
  gen2_progress_target: X%
  market_share_target: X%

Be extremely specific with numbers. Ground every number in data from the reports.
Disagree vigorously where appropriate — the best plans come from honest debate.

OPTIONAL: If the board needs deeper statistical analysis to resolve a debate,
include an ANALYSIS_REQUEST section with specific questions for the data analyst.
Example:
  ANALYSIS_REQUEST:
  - What is the correlation between R&D spending and revenue growth across all past simulations?
  - What was the average cash runway of firms that defaulted vs survived?
The data analyst will run statistical analysis on the accumulated Compustat database
and report back. Only request analysis when the board genuinely needs data to decide.

OPTIONAL (DATA_QUERY): If seeing a specific statistic would change your decision,
you may query the Data Broker. Include a QUESTION and a HYPOTHESIS stating what
you would do differently based on the answer. Queries without a hypothesis are
rejected. Example:

  DATA_QUERY:
  QUESTION: How does our gross margin compare to peers this quarter?
  HYPOTHESIS: If we are below the 25th percentile, the CFO will argue for process R&D
              to reduce COGS; if above the 75th, no action needed.

Only query when the answer would change your decision. One or two queries per board
meeting is reasonable. Do NOT query for data already shown above."""


def build_board_prompt(
    firm: FirmState,
    public_info: dict,
    params: SimParams,
    last_flows: dict | None,
    rd_report: RDReport | None,
    brand_report: BrandReport | None,
    memory: AgentMemory | None,
    gazette: str = "",
    data_dir: str = "data",
) -> tuple[str, str]:
    """Build the board discussion prompt."""

    from .personalities import get_company_name
    firm_idx = int(firm.firm_id.split("_")[-1]) if "_" in firm.firm_id else 0
    # Cycle CEO styles across firms beyond the baseline pool so 20+-firm
    # simulations still produce a mix of strategic temperaments.
    ceo_styles_pool = (
        "Aggressive Growth — believes market share is everything, willing to underprice competitors to capture volume",
        "Premium Innovator — wants highest price in market, invests heavily in R&D and brand",
        "Value Operator — obsesses over unit economics, wants positive cash flow as soon as possible",
        "Fast Follower — watches competitors closely, copies winning strategies with slight improvements",
        "Marketing Powerhouse — believes brand wins markets, wants highest SGA in the industry",
        "Patient Builder — takes the long view, willing to operate sub-scale while preserving optionality",
        "Disruptive Challenger — seeks asymmetric bets that could reshape the market",
        "Balanced Operator — hedges across all dimensions without extreme bias",
    )

    system = BOARD_SYSTEM_PROMPT.format(
        company_name=get_company_name(firm_idx),
        ceo_style=ceo_styles_pool[firm_idx % len(ceo_styles_pool)],
    )

    # ── Forecast review ──────────────────────────────────────────────────

    forecast_review = "(First quarter — no prior forecast to review)"
    if memory and memory.get_last_forecast():
        last_fc = memory.get_last_forecast()
        forecast_review = "LAST QUARTER'S FORECAST vs ACTUALS:\n"
        if last_flows:
            actual_rev = last_flows.get("net_sales", 0)
            target_rev = last_fc.get("revenue_target", 0)
            rev_hit = "HIT" if target_rev > 0 and abs(actual_rev - target_rev) / target_rev < 0.1 else "MISS"

            actual_ni = last_flows.get("net_income", 0)
            target_ni = last_fc.get("expected_ni", 0)

            actual_rd = last_flows.get("actual_rd_spend", 0)
            target_rd = last_fc.get("rd_spend", 0)

            forecast_review += (
                f"  Revenue: Plan ${target_rev:,.0f} | Actual ${actual_rev:,.0f} | {rev_hit}"
                f" ({(actual_rev-target_rev)/max(1,target_rev)*100:+.0f}%)\n"
                f"  Net Income: Plan ${target_ni:,.0f} | Actual ${actual_ni:,.0f}\n"
                f"  R&D: Plan ${target_rd:,.0f} | Actual ${actual_rd:,.0f}\n"
                f"  End Cash: Plan ${last_fc.get('expected_end_cash', 0):,.0f} | Actual ${firm.cash:,.0f}\n"
            )
            target_share = last_fc.get("market_share_target", 0)
            if target_share > 0:
                actual_share = last_flows.get("market_share", 0)
                share_hit = "HIT" if abs(actual_share - target_share) < 0.03 else "MISS"
                forecast_review += f"  Market Share: Plan {target_share:.0%} | Actual {actual_share:.1%} | {share_hit}\n"

    # ── Financial data ───────────────────────────────────────────────────

    macro = public_info.get("macro", {})
    competitors = public_info.get("public_competitors", {})

    # Cash runway calculation
    cash_runway = "unknown"
    quarterly_burn = 0
    if last_flows and last_flows.get("cfo", 0) < 0:
        quarterly_burn = -last_flows["cfo"]
        if quarterly_burn > 0:
            cash_runway = f"{firm.cash / quarterly_burn:.1f} quarters"

    # Competitor summary
    comp_lines = []
    for cid, c in sorted(competitors.items()):
        comp_lines.append(
            f"  {cid}: Price=${c.get('price',0):,.0f} Share={c.get('market_share',0):.1%} "
            f"Rev=${c.get('revenue',0)/1e6:.1f}M R&D=${c.get('total_rd_spend',0)/1e6:.0f}M"
        )
    comp_text = "\n".join(comp_lines) if comp_lines else "  (no data)"

    # R&D report
    rd_text = "(no R&D report yet)"
    if rd_report:
        rd_text = rd_report.summary

    # Brand report
    brand_text = "(no brand report yet)"
    if brand_report:
        brand_text = brand_report.summary

    # Memory summary
    history_text = "(first quarter)"
    if memory:
        history_text = memory.get_history_summary()

    # Last quarter results
    lq_text = "(first quarter — no results)"
    if last_flows:
        lq_text = (
            f"Revenue: ${last_flows.get('net_sales', 0):,.0f} | "
            f"NI: ${last_flows.get('net_income', 0):,.0f} | "
            f"CFO: ${last_flows.get('cfo', 0):,.0f}\n"
            f"  Units sold: {last_flows.get('units_sold', 0)} | "
            f"Share: {last_flows.get('market_share', 0):.1%} | "
            f"Price: ${last_flows.get('actual_price', 0):,.0f}\n"
            f"  R&D: ${last_flows.get('actual_rd_spend', 0):,.0f} | "
            f"SGA: ${last_flows.get('actual_sga_spend', 0):,.0f} | "
            f"Capex: ${last_flows.get('actual_capex', 0):,.0f}"
        )

    # Activist campaigns the firm has been publicly targeted with (Stage 12).
    # Surfaced here so the board debates the response before the CEO commits
    # to accept/reject/negotiate in the firm decision prompt.
    activist_block = ""
    pending_campaigns = public_info.get("pending_activist_campaigns", []) or []
    if pending_campaigns:
        lines = []
        for c in pending_campaigns:
            lines.append(
                f"  • {c.get('activist_id','activist')} "
                f"(stake {c.get('stake_pct_implied',0)*100:.1f}%) demands "
                f"{c.get('demand_type','')}: {c.get('demand_specifics','')}"
            )
            thesis = c.get("thesis") or ""
            if thesis:
                lines.append(f"      thesis: {thesis[:240]}")
        activist_block = (
            "\n*** ACTIVIST INVESTOR PRESSURE (public campaign) ***\n"
            + "\n".join(lines)
            + "\nThe board MUST debate a response. CEO/CFO/COO should discuss:\n"
              "  - Does the activist's thesis have merit given our numbers?\n"
              "  - Accept / partial / negotiate / reject — with a clear rationale.\n"
              "  - If rejecting, how do we defend the strategy publicly?\n"
        )

    user = f"""BOARD MEETING — Q{macro.get('fqtr', '?')} {macro.get('fyear', '?')} (Quarter {macro.get('quarter', '?')})

{forecast_review}{activist_block}

CURRENT FINANCIAL POSITION:
  Cash: ${firm.cash:,.0f} | Runway: {cash_runway} | Burn: ${quarterly_burn:,.0f}/Q
  Total equity: ${firm.total_equity:,.0f} | Equity price: ${firm.equity_price:.2f}/share
  Shares: {firm.shares_outstanding:,} | Debt: ${firm.revolver_balance + firm.long_term_debt:,.0f}

LAST QUARTER:
  {lq_text}

R&D STATUS: {rd_text}
BRAND STATUS: {brand_text}

OUR COMPETITIVE POSITION:
  Gen: {firm.product_generation} | Capability: {firm.capability_stock:.1f}/100 | Brand: {firm.brand_stock:.1f}/100
  Cumulative product R&D: ${firm.rd_cumulative_product:,.0f}
  Manufacturing: {firm.capacity_units}/Q capacity | Unit cost: ~${firm.base_unit_cost:,.0f}

COMPETITORS:
{comp_text}

HISTORY: {history_text}

GAZETTE: {gazette[:300] if gazette else '(none)'}

{_get_cross_run_context(firm, data_dir)}

{run_firm_analysis(firm, last_flows, public_info.get('public_competitors', {}), data_dir)}

Now conduct the board meeting (Part A: review, Part B: discussion, Part C: business plan).
The DATA ANALYST BRIEFING above contains statistical analysis — use it to ground your discussion in data, but remember the analyst does NOT make decisions. That is your job."""

    return system, user


def _get_cross_run_context(firm: FirmState, data_dir: str) -> str:
    """Get cross-run data for the board discussion."""
    compustat_ctx = query_cross_run_compustat(
        data_dir, firm.cash, firm.total_assets, firm.quarter
    )
    scores_ctx = query_cross_run_scores(data_dir)
    if "(no past" in compustat_ctx and "(no past" in scores_ctx:
        return ""
    return f"{compustat_ctx}\n\n{scores_ctx}"


def parse_board_minutes(firm_id: str, quarter: int, response: str) -> BoardMinutes:
    """Parse board meeting response into structured minutes."""

    # Extract forecast from the response
    forecast = _extract_forecast(response)

    # Extract consensus
    consensus = ""
    for line in response.split("\n"):
        upper = line.strip().upper()
        if "CONSENSUS" in upper and ":" in line:
            consensus = line.split(":", 1)[1].strip()
            break

    # Extract action items
    action_items = ""
    in_actions = False
    action_lines = []
    for line in response.split("\n"):
        if "ACTION" in line.upper() and ("ITEM" in line.upper() or ":" in line):
            in_actions = True
            rest = line.split(":", 1)[1].strip() if ":" in line else ""
            if rest:
                action_lines.append(rest)
            continue
        if in_actions:
            if line.strip().startswith("*") or line.strip().startswith("-") or line.strip().startswith("•"):
                action_lines.append(line.strip())
            elif line.strip() and not any(h in line.upper() for h in ["FORECAST", "PART C", "CEO", "CFO", "COO"]):
                action_lines.append(line.strip())
            else:
                if action_lines:
                    break
    action_items = " ".join(action_lines)

    return BoardMinutes(
        firm_id=firm_id,
        quarter=quarter,
        full_text=response,
        consensus=consensus,
        action_items=action_items,
        forecast=forecast,
    )


def _extract_forecast(response: str) -> dict:
    """Extract the numerical forecast from the board discussion response.

    Looks for a section header that is a line containing 'FORECAST' with a
    colon or as a markdown heading (e.g. 'FORECAST:', '### FORECAST',
    '**FORECAST:**', 'PART C: ... FORECAST', 'AGREED BUSINESS PLAN').
    Then parses subsequent lines as key: value pairs until a blank line or
    a new section starts.
    """
    import re
    forecast = {}
    in_forecast = False

    # Known forecast keys we care about (normalized form)
    known_keys = {
        "price", "production", "revenue_target", "rd_spend", "sga_spend",
        "capex", "expected_ni", "expected_end_cash",
        "debt_request", "equity_request",
        "gen2_progress_target", "market_share_target",
    }

    def looks_like_header(line: str) -> bool:
        """Return True if this line opens the forecast section."""
        u = line.strip().upper()
        if not u:
            return False
        # Strip markdown decorations and trailing colon
        stripped = re.sub(r'[*#>\-\s]', '', u).rstrip(":")
        # Direct match: "FORECAST" on its own line
        if stripped in ("FORECAST", "FORECASTS", "AGREEDFORECAST"):
            return True
        # Line like "FORECAST:" or "### FORECAST:" at start
        if u.startswith("FORECAST:") or u.startswith("FORECAST "):
            return True
        # PART C header with AGREED or PLAN
        if "PART C" in u and ("AGREED" in u or "PLAN" in u or "FORECAST" in u):
            return True
        return False

    def looks_like_new_section(line: str) -> bool:
        """Detect a new section (stops forecast parsing)."""
        u = line.strip().upper()
        if not u:
            return False
        stripped = re.sub(r'[*#>\-\s]', '', u).rstrip(":")
        if stripped in ("PARTA", "PARTB", "PARTD", "CONSENSUS", "ACTIONITEMS", "DEBATE"):
            return True
        if u.startswith("PART A") or u.startswith("PART B") or u.startswith("PART D"):
            return True
        if u.startswith("CONSENSUS:") or u.startswith("ACTION"):
            return True
        return False

    for line in response.split("\n"):
        if looks_like_header(line):
            in_forecast = True
            continue
        if in_forecast:
            if looks_like_new_section(line):
                break
            if ":" not in line:
                continue
            key, _, val = line.partition(":")
            # Strip markdown decorations from key, but preserve underscores in identifiers
            key = re.sub(r'[*`#>]', '', key).strip().lower()
            key = re.sub(r'[\s\-]+', '_', key)
            val = val.strip()
            # Extract a number (first numeric token)
            numbers = re.findall(r'[\-]?\$?([\d,]+(?:\.\d+)?)', val)
            if numbers:
                try:
                    num_str = numbers[0].replace(",", "")
                    num = float(num_str)
                    if "%" in val and num > 1:
                        num = num / 100
                    # Only keep keys we recognize (skip junk like "part_c")
                    if key in known_keys or any(k in key for k in known_keys):
                        # Normalize common aliases
                        if "revenue" in key and "target" not in key:
                            key = "revenue_target"
                        forecast[key] = num
                except ValueError:
                    pass

    return forecast


def format_minutes_for_decision_prompt(minutes: BoardMinutes) -> str:
    """Compact format of board conclusions for the decision prompt."""
    fc = minutes.forecast
    forecast_line = ""
    if fc:
        parts = []
        if "price" in fc: parts.append(f"Price=${fc['price']:,.0f}")
        if "revenue_target" in fc: parts.append(f"Rev=${fc['revenue_target']:,.0f}")
        if "rd_spend" in fc: parts.append(f"R&D=${fc['rd_spend']:,.0f}")
        if "sga_spend" in fc: parts.append(f"SGA=${fc['sga_spend']:,.0f}")
        if "debt_request" in fc and fc["debt_request"] > 0: parts.append(f"Debt=${fc['debt_request']:,.0f}")
        if "equity_request" in fc and fc["equity_request"] > 0: parts.append(f"Equity=${fc['equity_request']:,.0f}")
        forecast_line = f"\n  Agreed plan: {' | '.join(parts)}"

    return f"""BOARD MEETING CONCLUSIONS:
  Consensus: {minutes.consensus[:250]}
  Action items: {minutes.action_items[:300]}{forecast_line}

Consider the board's discussion and agreed direction when making your decisions."""
