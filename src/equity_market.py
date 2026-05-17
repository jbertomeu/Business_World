"""
Equity Market Agent: LLM-powered equity pricing.

Represents the aggregated view of public market investors.
Sets a fair equity price for each firm based on fundamental analysis.

Uses multiple valuation approaches:
- Revenue multiples (growth-stage biotech comparables)
- Pipeline/option value (Gen 2 probability-weighted)
- Asset-based (liquidation floor)
- DCF projection (revenue growth → margin improvement → terminal value)

The equity market sees published financials and macro state,
but NOT private firm data. It also sees its own prior pricing errors
for self-improvement.
"""

from __future__ import annotations
from .types import FirmState, MacroState, QuarterFlows
from .llm_backends import LLMBackend


SYSTEM_PROMPT = """You are the equity market — representing all public market investors pricing pharmaceutical stocks.

For each firm, determine a fair equity price per share. Think like a professional investor.

PROCESS (the order and emphasis is yours — these are things to consider):

1. ANCHORING. Real markets typically move gradually quarter-to-quarter without a
   specific catalyst. Consider prior price as context. Large moves usually correspond to
   earnings surprises, guidance changes, M&A, regulatory events, R&D milestones, or
   clear fundamental shifts. You judge whether a move is warranted.

2. FUNDAMENTAL VALUATION. Use any combination of methods that fits the firm:
   - Revenue multiples (P/S): what's reasonable given growth, margin trajectory, and
     industry peers? Pre-revenue, growing, profitable firms have different typical ranges.
   - Pipeline value: how much option value from R&D progress? Consider time to Gen 2,
     probability of success, market opportunity.
   - Asset/cash floor: liquidation value as a lower bound, especially for distressed firms.
     The market cap of an operating, profitable firm should NEVER fall below the firm's
     CASH POSITION net of debt — if it did, an acquirer could buy the firm for $X, take
     its $Y > $X cash, and pocket the difference. If you see yourself pricing a profitable
     firm below its net cash, something is wrong with your reasoning; revisit.
   - Cash burn assessment: firms spending far more than they earn carry going-concern risk.
     Price should reflect that risk. You judge the magnitude.
   - EARNINGS-BASED FLOOR for mature/profitable firms: if a firm has positive recent NI
     and recent revenue is in a sustained range, a reasonable enterprise value is in the
     ballpark of mid-single-digit to mid-double-digit times ANNUAL net income (4×
     quarterly NI). A firm generating $10M of quarterly NI consistently should price
     with market cap on the order of $200M–$2B, not $20M. A firm generating $20B of
     quarterly NI consistently should price on the order of $400B–$4T, not $500M.
     Per-share price = market cap / shares_outstanding. The same multiple logic scales
     to the size of the underlying business.

   SCALE SANITY CHECK: divide your proposed market cap (price × shares_outstanding)
   by the firm's annual revenue (4 × quarterly). If the resulting P/S ratio is below
   0.1 for a growing profitable firm, you are mispricing. If above 50 for any firm,
   you are also mispricing. Real public-market biotech runs 1×–20× P/S depending on
   growth and profitability.

3. DILUTION. Large share issuance changes the per-share value even if total firm value
   doesn't. Make sure your per-share price reflects that.

4. ANALYST RESEARCH. Sell-side notes with specific FSA (ROE decomposition, RNOA, peer
   comparables, residual income) give grounded views. Weigh them based on methodology
   quality, not consensus noise.

5. SHOW YOUR WORK. Your reasoning must cite specific numbers (prior price, the multiple
   you're using, the catalyst, any dilution adjustment). Readers should be able to
   reconstruct your thinking from the reasoning field.

Firms differentiate: different fundamentals → different prices. The equity price is YOUR
judgment as the market, not the firm's. Investors price firms; firms cannot will their
price up.

Output JSON:
```json
{"firms": [{"firm_id": "...", "equity_price": <number>, "valuation_method": "<primary method used>", "reasoning": "<4-5 sentences citing specific numbers>"}]}
```"""


def build_equity_prompt(firms, flows, macro, gazette, prior_prices=None,
                         recent_analyst_notes=None, price_history=None,
                         recent_guidance=None):
    """Build the equity market's pricing prompt.

    recent_analyst_notes: list of AnalystNote objects published recently. The
    market digests them and weighs based on methodology quality.

    price_history: optional dict[firm_id -> list[float]] with the last few
    quarters' prices (most recent last) — feeds the anchoring section so
    the LLM sees the rolling price trajectory, not just the prior point.

    recent_guidance: optional dict[firm_id -> list[dict]] with recent
    management-issued forecasts (target rev/EPS for next 1Q-1Y). Lets the
    market see the firm's own forward plan as additional anchoring info.
    """
    sections = []
    for fid in sorted(firms):
        firm = firms[fid]
        if not firm.is_active:
            continue
        f = flows.get(fid)
        if f is None:
            continue
        debt = firm.revolver_balance + firm.long_term_debt
        annualized_rev = f.net_sales * 4
        runway = f"{firm.cash / max(1, -f.cfo):.1f}Q" if f.cfo < 0 else "positive CF"
        prior = prior_prices.get(fid, 0) if prior_prices else 0
        gm = f.gross_profit / max(1, f.net_sales) * 100

        # Wave ν+8: include rolling price history so the LLM has multi-Q
        # anchoring rather than only a single prior point. Helps damp
        # one-quarter hallucinations.
        history_str = ""
        if price_history and fid in price_history:
            hist = price_history[fid][-4:]
            if hist:
                history_str = (
                    f"\n  Price history (last {len(hist)}Q, oldest→newest): "
                    + ", ".join(f"${p:.2f}" for p in hist)
                )

        # Wave ν+8: include recent management guidance so the market sees
        # the firm's own forward plan as additional anchoring information.
        guidance_str = ""
        if recent_guidance and fid in recent_guidance:
            gd = recent_guidance[fid][-2:]
            if gd:
                gd_lines = []
                for g in gd:
                    gd_lines.append(
                        f"    Q{g.get('quarter','?')}: 1Q-EPS=${g.get('guidance_eps_1q', 0):.2f}, "
                        f"1Q-rev=${g.get('guidance_revenue_1q', 0)/1e6:.1f}M"
                    )
                guidance_str = "\n  Recent management guidance:\n" + "\n".join(gd_lines)

        sections.append(
            f"{fid}:\n"
            f"  Revenue: ${f.net_sales:,.0f}/Q (annualized ${annualized_rev:,.0f}) | Gross margin: {gm:.0f}%\n"
            f"  R&D: ${f.rd_expense:,.0f}/Q | SGA: ${f.sga_expense:,.0f}/Q\n"
            f"  Net income: ${f.net_income:,.0f} | Op cash flow: ${f.cfo:,.0f}\n"
            f"  Cash: ${firm.cash:,.0f} | Runway: {runway}\n"
            f"  Total debt: ${debt:,.0f} | Total equity: ${firm.total_equity:,.0f}\n"
            f"  Shares outstanding: {firm.shares_outstanding:,} | Prior price: ${prior:.2f}"
            f"{history_str}"
            f"{guidance_str}\n"
            f"  Cumulative product R&D: ${firm.rd_cumulative_product:,.0f}\n"
            f"  PP&E: ${firm.ppe_net:,.0f} | Inventory: ${firm.inventory_value:,.0f}"
        )
    # Assemble analyst section — group by firm, include method + target + key FSA ratios
    analyst_section = ""
    if recent_analyst_notes:
        from collections import defaultdict
        by_firm = defaultdict(list)
        for note in recent_analyst_notes:
            by_firm[note.firm_id].append(note)
        a_lines = []
        for fid in sorted(by_firm.keys()):
            a_lines.append(f"\n  {fid}:")
            for n in by_firm[fid][-3:]:  # last 3 notes per firm
                ratios = []
                if n.roe is not None: ratios.append(f"ROE {n.roe:.1%}")
                if n.rnoa is not None: ratios.append(f"RNOA {n.rnoa:.1%}")
                if n.nbc is not None: ratios.append(f"NBC {n.nbc:.1%}")
                if n.quality_of_earnings: ratios.append(f"QoE: {n.quality_of_earnings}")
                ratio_str = " | ".join(ratios) if ratios else ""
                a_lines.append(
                    f"    {n.analyst_id} ({n.methodology}) Q{n.quarter}: "
                    f"TP=${n.target_price:.2f} ({n.rating}) | {ratio_str}"
                )
                if n.valuation_method_detail:
                    a_lines.append(f"      method: {n.valuation_method_detail[:200]}")
                if n.risks:
                    a_lines.append(f"      risks: {n.risks[:150]}")
        analyst_section = "\n\nRECENT ANALYST RESEARCH (weigh based on methodology quality, not consensus):" + "".join(a_lines)

    user = (
        f"=== EQUITY MARKET PRICING — Q{macro.fqtr} {macro.fyear} ===\n"
        f"Risk-free rate: {macro.risk_free_rate*400:.1f}% annual\n"
        f"This is a GROWTH INDUSTRY. Early losses are investment, not failure.\n"
        f"But cash burn and dilution are real risks.\n\n"
        + "\n\n".join(sections)
        + f"\n\nGAZETTE: {gazette[:300] if gazette else '(none)'}"
        + analyst_section
        + "\n\nPrice each firm. Differentiate based on fundamentals. Show your reasoning."
    )
    return SYSTEM_PROMPT, user


def make_equity_market(backend, state_ref: list):
    """Create equity market agent function.

    Wave ν+8: `backend` accepts EITHER a single LLMBackend (legacy) OR a
    list of backends (panel of valuators). When given a panel, each
    backend is queried in parallel with the same prompt and the per-firm
    median price is taken — robust to single-backend hallucinations
    without imposing any quantitative ceiling. The per-backend
    valuations and method/reasoning strings are preserved on the
    returned dict for transparency.
    """
    if isinstance(backend, list):
        backends: list = backend
    else:
        backends = [backend]

    def agent(firms, macro, params):
        world = state_ref[0] if state_ref else None
        flows = world.last_quarter_flows if world else {}
        gazette = world.gazettes[-1] if world and world.gazettes else ""
        prior_prices = {fid: f.equity_price for fid, f in firms.items() if f.is_active}

        # Wave ν+8: assemble rolling price history (last 4Q) per firm so
        # the prompt includes a price trajectory rather than only a
        # single prior point. Anchors more strongly without imposing a
        # hardcoded ceiling on QoQ moves.
        price_history: dict[str, list[float]] = {}
        if world and world.compustat_rows:
            for fid in firms:
                hist = [r.prccq for r in world.compustat_rows
                         if r.firm_id == fid and r.prccq and r.prccq > 0]
                if hist:
                    price_history[fid] = hist[-4:]

        # Wave ν+8: management guidance from recent earnings releases
        # gives the market the firm's own forward plan as additional
        # anchor info.
        recent_guidance: dict[str, list[dict]] = {}
        if world and getattr(world, "earnings_releases", None):
            for r in world.earnings_releases[-12:]:
                fid = getattr(r, "firm_id", "")
                if not fid:
                    continue
                recent_guidance.setdefault(fid, []).append({
                    "quarter": getattr(r, "quarter", "?"),
                    "guidance_eps_1q": getattr(r, "guidance_eps_1q", 0.0),
                    "guidance_revenue_1q": getattr(r, "guidance_revenue_1q", 0.0),
                })

        # Grab recent analyst notes (last 2 publication cycles)
        recent_notes = []
        if world and world.analyst_notes:
            recent_notes = world.analyst_notes[-18:]
        sys, user = build_equity_prompt(
            firms, flows, macro, gazette, prior_prices,
            recent_analyst_notes=recent_notes,
            price_history=price_history,
            recent_guidance=recent_guidance,
        )

        # Wave ν+8: panel of LLM valuators in parallel. Median price
        # per firm is taken (robust to single-LLM outliers).
        # Wave ν+9 Bug H2: track per-backend errors so a partial panel
        # failure can be detected (rather than silently treated as a
        # legitimate "no quote" by some panel members).
        def _call_one(b):
            try:
                return ("ok", b.complete_json(sys, user))
            except Exception as e:
                return ("error", f"{type(e).__name__}: {e}")

        if len(backends) > 1:
            import concurrent.futures as _cf
            with _cf.ThreadPoolExecutor(max_workers=len(backends)) as _pool:
                panel_raw = list(_pool.map(_call_one, backends))
        else:
            panel_raw = [_call_one(backends[0])]

        panel_results = [r for status, r in panel_raw if status == "ok" and r is not None]
        panel_errors = [r for status, r in panel_raw if status == "error"]

        # Aggregate: collect per-firm price votes from every successful
        # panel response, then take the median.
        from collections import defaultdict
        votes: dict[str, list[float]] = defaultdict(list)
        first_method: dict[str, str] = {}
        first_reasoning: dict[str, str] = {}
        for result in panel_results:
            for f in result.get("firms", []) or []:
                fid = f.get("firm_id", "")
                if not fid:
                    continue
                try:
                    p = float(f.get("equity_price", 0) or 0)
                except (TypeError, ValueError):
                    p = 0
                if p > 0:
                    votes[fid].append(p)
                    if fid not in first_method:
                        first_method[fid] = str(f.get("valuation_method", ""))[:120]
                        first_reasoning[fid] = str(f.get("reasoning", ""))[:600]

        if not votes:
            return None  # no usable panel response

        # Wave ν+9 Bug H2: enforce a quorum on panels of 3+. With one
        # successful vote out of three, the "median" is just a single LLM's
        # quote — exactly the outlier the panel was meant to suppress.
        # Below quorum, fall back to the prior-quarter price (mark to last
        # observed value), and tag the response with a fallback_reason.
        n_backends = len(backends)
        quorum = max(2, n_backends // 2 + 1) if n_backends >= 2 else 1

        decisions = {}
        for fid, vlist in votes.items():
            if len(vlist) < quorum:
                prior = float(prior_prices.get(fid, 0.0) or 0.0)
                if prior <= 0:
                    # No prior to anchor to; carry the lone median up.
                    fallback_price = vlist[len(vlist) // 2]
                else:
                    fallback_price = prior
                decisions[fid] = {
                    "equity_price": max(0.01, fallback_price),
                    "method": first_method.get(fid, ""),
                    "reasoning": (first_reasoning.get(fid, "") + " "
                                  f"[panel quorum unmet: {len(vlist)}/{n_backends}; "
                                  f"carrying prior=${prior:.2f}]").strip(),
                    "panel_votes": vlist,
                    "panel_n_responses": len(vlist),
                    "fallback_reason": (
                        f"panel_quorum_unmet:{len(vlist)}/{n_backends}"
                        + (f"; errors={len(panel_errors)}" if panel_errors else "")
                    ),
                }
                continue
            vlist_sorted = sorted(vlist)
            n = len(vlist_sorted)
            if n % 2 == 1:
                median_price = vlist_sorted[n // 2]
            else:
                median_price = 0.5 * (vlist_sorted[n // 2 - 1] + vlist_sorted[n // 2])
            decisions[fid] = {
                "equity_price": max(0.01, median_price),
                "method": first_method.get(fid, ""),
                "reasoning": first_reasoning.get(fid, ""),
                "panel_votes": vlist,        # all per-LLM prices (transparency)
                "panel_n_responses": len(vlist),
            }
        return decisions
    return agent
