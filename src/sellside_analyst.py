"""
Sell-side analyst agents.

3 analysts (default, configurable) with different methodologies.
Each is a separate LLM. They publish staggered — not all every quarter.

Analyst 1: DCF-focused, publishes Q1, Q3 (fqtr 1, 3)
Analyst 2: Comparables-focused, publishes Q2, Q4 (fqtr 2, 4)
Analyst 3: Contrarian/event-driven, publishes Q1, Q4 (fqtr 1, 4)

Output: AnalystNote stored in WorldState.analyst_notes (public).

INFORMATION BOUNDARY: Analysts see ONLY public data — Compustat, earnings
releases, gazette, other analysts' prior notes. They NEVER see private firm
data, board minutes, manipulation amounts, or world secrets.
"""

from __future__ import annotations

from .types import (
    CompustatRow, MacroState, AnalystNote, EarningsRelease,
)
from .llm_backends import LLMBackend, extract_json


# ── Analyst personalities ────────────────────────────────────────────────

ANALYST_PERSONALITIES = {
    "analyst_1": {
        "name": "Sarah Chen (Meridian Capital)",
        "methodology": "fundamental_fsa_dcf",
        "style": (
            "You are a fundamentals-first analyst who does disciplined financial statement "
            "analysis BEFORE settling on a valuation. Start with a DuPont decomposition "
            "(ROE = NPM × Asset Turnover × Leverage) and then refine with Penman-style "
            "RNOA decomposition to separate operating return from financing leverage. "
            "Assess quality of earnings (accruals vs. cash flows) and identify red or green "
            "flags. Only THEN move to DCF valuation with explicit forecast drivers. "
            "Your edge is rigor: the price target should follow from the analysis."
        ),
        "publishes": {1, 3},
    },
    "analyst_2": {
        "name": "James Okonkwo (Atlantic Securities)",
        "methodology": "comparables",
        "style": (
            "You are a comparables specialist. Your framework: which multiple is right for "
            "this firm given its stage (P/S for unprofitable, P/B for asset-heavy, EV/Sales "
            "for leverage-neutral, EV/EBITDA for stable operators)? Which peers are genuinely "
            "comparable? Do you exclude distressed or outlier peers? Explain your choices. "
            "Then use the peer multiple on the target firm, adjusting for firm-specific "
            "factors (growth differential, margin gap, balance sheet strength, R&D pipeline). "
            "Your edge is peer selection and multiple choice — not canned DCFs."
        ),
        "publishes": {2, 4},
    },
    "analyst_3": {
        "name": "Lisa Marchetti (Pinnacle Research)",
        "methodology": "residual_income",
        "style": (
            "You are a residual-income modeler. Intrinsic value = book value + PV of future "
            "residual income (earnings above the cost of equity times book value). This "
            "framework directly answers: is management creating or destroying shareholder "
            "value relative to the required return? Book value is your anchor; RI is where "
            "skill and competitive advantage show up. Use it to identify firms where the "
            "market is pricing in too much optimism (P/B rich when RI is negative) or "
            "missing real value creation. Your edge is anchoring to book + evaluating "
            "whether operations truly clear the cost of equity."
        ),
        "publishes": {1, 4},
    },
    # Wave ν+10 item 9: 4th analyst with quant/momentum methodology and an
    # always-on schedule, ensuring at least one analyst publishes every
    # quarter so the equity panel never sees an empty consensus block.
    "analyst_4": {
        "name": "Rohan Mehra (Crescent Quant)",
        "methodology": "quant_momentum",
        "style": (
            "You are a quantitative momentum analyst. Your framework is empirical, not "
            "narrative: trailing 4-quarter price momentum, earnings revision direction, "
            "short-interest dynamics, and implied-volatility skew (where available). "
            "You are skeptical of stories; you trust price action and revision data. When "
            "a firm's fundamentals are improving but the price hasn't followed, you flag "
            "it as undervalued; when a firm's price has run ahead of fundamentals, you "
            "flag it as crowded. Your edge is timing and contrary signals — and you "
            "publish every quarter, providing always-on baseline coverage."
        ),
        "publishes": {1, 2, 3, 4},
    },
}


def should_publish(analyst_id: str, fqtr: int) -> bool:
    """Check if this analyst publishes in this fiscal quarter."""
    personality = ANALYST_PERSONALITIES.get(analyst_id, {})
    publishes = personality.get("publishes", set())
    return fqtr in publishes


def build_analyst_prompt(
    personality: dict,
    public_compustat: list[dict],
    earnings_releases: list[dict],
    prior_notes: list[dict],
    macro: MacroState,
    firm_ids: list[str],
    own_forecast_history: list[dict] | None = None,
) -> tuple[str, str]:
    """Build (system, user) prompt for a sell-side analyst.

    ONLY public information is passed. No private firm data.

    own_forecast_history: optional list of {firm_id, forecast_quarter, eps_forecast,
    actual_eps, forecast_error} from prior notes by THIS analyst, for calibration.
    """
    system = f"""You are {personality['name']}, a sell-side equity analyst covering pharmaceutical companies.

YOUR METHODOLOGY AND EDGE:
{personality['style']}

PROCESS — you are writing a FULL research note, not just a price tag. For each firm:

1. FINANCIAL SNAPSHOT (quantitative): compute or estimate key ratios from the Compustat
   data below. Report ROE, net profit margin, asset turnover, leverage, and — if your
   methodology calls for it — operating return (RNOA) vs net borrowing cost (NBC), or
   book value vs residual income. Note quality-of-earnings flags (accruals vs cash flow,
   unusual items, cash burn).

2. FORECAST: project the next quarter and the full year (4Q). Name the drivers
   (revenue growth rate, margin trajectory, R&D progress, competitive dynamics).

3. VALUATION: apply your primary method. State the assumptions clearly. Show a
   sensitivity if applicable. Your target price must follow from this analysis.

4. RATING: align with target vs current price. buy/hold/sell. Explain.

5. RISKS: 2-3 things that would make you wrong.

DISCIPLINE:
- Review your own prior forecasts vs actuals (shown below). Calibrate accordingly —
  systematic bias is a failure of analysis, not a feature.
- Large revisions need catalysts (earnings surprise, guidance change, R&D milestone,
  macro shift). Name them.
- Your narrative must reference specific numbers (ratios, forecasts, valuations).
  Vague prose earns no target-price credibility.

Output JSON (one entry per firm you cover):
```json
{{
  "notes": [{{
    "firm_id": "...",
    "financial_snapshot": {{
      "roe": <number or null>, "npm": <number or null>, "asset_turnover": <number or null>,
      "leverage": <number or null>, "rnoa": <number or null>, "nbc": <number or null>,
      "nfl": <number or null>, "quality_of_earnings": "<your assessment: high|moderate|low|poor>"
    }},
    "forecast_drivers": "<2-3 sentences on what drives your forecast>",
    "eps_forecast_1q": <number>,
    "eps_forecast_1y": <number>,
    "valuation_method_detail": "<2-3 sentences on method + key assumptions>",
    "target_price": <number>,
    "rating": "buy|hold|sell",
    "risks": "<2-3 short sentences>",
    "narrative": "<3-5 paragraph thesis including your methodology, key numbers, and how your view changed from prior note>"
  }}]
}}
```

Output ONLY the JSON wrapped in ```json ... ```."""

    # Build public data summary
    comp_lines = []
    for row in public_compustat[-20:]:  # last 20 rows (cap context size)
        fid = row.get("firm_id", "?")
        rev = row.get("saleq", 0)
        ni = row.get("niq", 0)
        cash = row.get("cheq", 0)
        price = row.get("prccq", 0)
        comp_lines.append(f"  {fid}: Rev=${rev:,.0f} NI=${ni:,.0f} Cash=${cash:,.0f} Price=${price:.2f}")

    # Recent earnings releases
    release_lines = []
    for rel in earnings_releases[-10:]:
        fid = rel.get("firm_id", "?")
        eps = rel.get("reported_eps", 0)
        guidance = rel.get("guidance_eps_1q", 0)
        release_lines.append(f"  {fid}: EPS=${eps:.2f}, 1Q guidance=${guidance:.2f}")

    # Prior analyst notes
    prior_lines = []
    for note in prior_notes[-6:]:
        aid = note.get("analyst_id", "?")
        fid = note.get("firm_id", "?")
        tp = note.get("target_price", 0)
        rating = note.get("rating", "?")
        prior_lines.append(f"  {aid} on {fid}: TP=${tp:.2f} ({rating})")

    # Own forecast history (for calibration)
    own_lines = []
    if own_forecast_history:
        for h in own_forecast_history[-8:]:
            fid = h.get("firm_id", "?")
            fq = h.get("forecast_quarter", "?")
            fc = h.get("eps_forecast", 0)
            act = h.get("actual_eps", 0)
            err = h.get("forecast_error", 0)
            if act != 0:  # only show ones with realized actuals
                own_lines.append(
                    f"  {fid} Q{fq}: forecasted ${fc:.2f}, actual ${act:.2f}, error {err:+.2f}"
                )

    user = f"""PUBLISHED FINANCIAL DATA (Compustat):
{chr(10).join(comp_lines) if comp_lines else '(No data yet)'}

RECENT EARNINGS RELEASES:
{chr(10).join(release_lines) if release_lines else '(None)'}

YOUR OWN PRIOR FORECASTS vs ACTUALS (calibrate from these):
{chr(10).join(own_lines) if own_lines else '(No prior forecasts with realized actuals yet)'}

PEER ANALYST NOTES:
{chr(10).join(prior_lines) if prior_lines else '(None)'}

MACRO: Risk-free {macro.risk_free_rate:.1%}/Q, Awareness {macro.awareness_rate:.0%}

Cover these firms: {', '.join(firm_ids)}
Produce your research note."""

    return system, user


def parse_analyst_notes(
    response: dict | None,
    analyst_id: str,
    quarter: int,
    methodology: str,
) -> list[AnalystNote]:
    """Parse LLM response into AnalystNote objects."""
    if response is None:
        return []

    notes_data = response.get("notes", [])
    if not isinstance(notes_data, list):
        return []

    results = []
    for n in notes_data:
        snap = n.get("financial_snapshot", {}) or {}

        def _num(v):
            try:
                return float(v) if v is not None else None
            except (TypeError, ValueError):
                return None

        # Wave ν+14e issue C: drop forecasts with empty firm_id.
        # Run-6 had 82/1489 (5.5%) such rows polluting the
        # analyst_forecasts.csv dataset and skewing aggregate
        # statistics.
        fid_raw = str(n.get("firm_id", "")).strip()
        if not fid_raw or not fid_raw.startswith("firm_"):
            continue

        # Wave ν+14e issue B: clamp target_price to >= $0.01.
        # Negative target prices are economically non-sensical
        # (you cannot pay someone to take your stock; shorts have
        # a different mechanism). Run-6 had a -$395 outlier that
        # poisoned aggregate target-price statistics.
        tp_raw = _num(n.get("target_price")) or 0.0
        target_price_clamped = max(0.01, tp_raw) if tp_raw > 0 else 0.0

        results.append(AnalystNote(
            analyst_id=analyst_id,
            quarter=quarter,
            firm_id=fid_raw,
            eps_forecast_1q=_num(n.get("eps_forecast_1q")) or 0.0,
            eps_forecast_1y=_num(n.get("eps_forecast_1y")) or 0.0,
            target_price=target_price_clamped,
            rating=n.get("rating", "hold"),
            methodology=methodology,
            narrative=n.get("narrative", ""),
            roe=_num(snap.get("roe")),
            npm=_num(snap.get("npm")),
            asset_turnover=_num(snap.get("asset_turnover")),
            leverage=_num(snap.get("leverage")),
            rnoa=_num(snap.get("rnoa")),
            nbc=_num(snap.get("nbc")),
            nfl=_num(snap.get("nfl")),
            quality_of_earnings=snap.get("quality_of_earnings", ""),
            forecast_drivers=n.get("forecast_drivers", ""),
            valuation_method_detail=n.get("valuation_method_detail", ""),
            risks=n.get("risks", ""),
        ))
    return results


def _build_own_forecast_history(state_ref: list, analyst_id: str) -> list[dict]:
    """Reconstruct this analyst's forecast-vs-actual history from WorldState.

    Returns rows with {firm_id, forecast_quarter, eps_forecast, actual_eps,
    forecast_error} suitable for including in the prompt.
    """
    world = state_ref[0] if state_ref else None
    if world is None:
        return []
    # Reuse the dataset builder which handles actuals reconciliation
    from .datasets import build_analyst_forecasts
    all_rows = build_analyst_forecasts(world)
    return [r for r in all_rows if r.get("analyst_id") == analyst_id]


def make_sellside_analyst(backend: LLMBackend, analyst_id: str, state_ref: list,
                          data_broker=None):
    """Factory: create one sell-side analyst function.

    If data_broker is provided, analyst uses methodology-specific templates
    (DCF analyst queries DCF projections; comparables analyst queries
    peer benchmarks; contrarian queries anomaly scores).
    """

    personality = ANALYST_PERSONALITIES.get(analyst_id, ANALYST_PERSONALITIES["analyst_1"])

    def analyst_fn(
        public_compustat: list[dict],
        earnings_releases: list[dict],
        prior_notes: list[dict],
        macro: MacroState,
        firm_ids: list[str],
    ) -> list[AnalystNote]:
        # Optional: methodology-aligned broker query
        broker_context = ""
        if data_broker is not None and firm_ids and public_compustat:
            methodology = personality.get("methodology", "")
            # One query per publication event (cost control)
            target_firm = firm_ids[0]
            if methodology == "fundamental_fsa_dcf":
                query_text = (
                    f"For {target_firm}, perform a DuPont + RNOA decomposition. "
                    f"I need to understand what's driving ROE and whether operations "
                    f"clear the cost of equity."
                )
                hypothesis = (
                    "If RNOA > cost of equity, operations create value and I lean buy; "
                    "if RNOA is negative or materially below cost of equity, I lean sell. "
                    "Leverage effect tells me if debt is amplifying gains or destroying value."
                )
            elif methodology == "comparables":
                query_text = (
                    f"For {target_firm}, compute a peer multiple analysis. I'll choose "
                    f"the multiple based on firm stage; compare to peer median + range; "
                    f"identify outliers to exclude."
                )
                hypothesis = (
                    "If firm trades at significant premium to peers without justified "
                    "fundamentals (higher growth or margins), I lean sell. At discount "
                    "without obvious reasons, I lean buy."
                )
            elif methodology == "residual_income":
                query_text = (
                    f"For {target_firm}, compute a residual income valuation at a "
                    f"reasonable cost of equity. Intrinsic value = BV + PV(RI)."
                )
                hypothesis = (
                    "If intrinsic value from RI > current market cap, firm is undervalued "
                    "(buy). If intrinsic value < book value, firm is destroying wealth "
                    "relative to cost of equity (sell)."
                )
            else:
                query_text = f"Run financial snapshot and peer comparison for {target_firm}."
                hypothesis = "Use ratios and peer context to ground my target price."
            ans = data_broker.answer(
                agent_role=analyst_id,
                query_text=query_text,
                hypothesis=hypothesis,
                current_run_rows=public_compustat,
                quarter=macro.quarter,
            )
            broker_context = f"\n\nBROKER ANALYSIS:\n{ans[:800]}"

        own_history = _build_own_forecast_history(state_ref, analyst_id)
        system, user = build_analyst_prompt(
            personality, public_compustat, earnings_releases, prior_notes, macro, firm_ids,
            own_forecast_history=own_history,
        )
        if broker_context:
            user += broker_context
        from . import telemetry as _tel
        with _tel.set_role(analyst_id):
            result = backend.complete_json(system, user)
        return parse_analyst_notes(result, analyst_id, macro.quarter, personality["methodology"])

    return analyst_fn
