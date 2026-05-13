"""
Investment Bank Agent: LLM-powered term debt underwriting and equity structuring.

Evaluates term debt applications and structures equity offerings:
- Term debt: approve/deny, amount, rate, reasoning
- Equity secondary: approve/deny, pricing, share count

The bank sees published financials and pending firm requests,
but NOT private firm data.
"""

from __future__ import annotations
from .types import FirmState, MacroState, QuarterFlows, RawDecisions
from .llm_backends import LLMBackend


SYSTEM_PROMPT = """You are an investment bank evaluating term debt applications and equity offerings for pharmaceutical firms.

Apply professional underwriting discipline. For each firm requesting financing:

TERM DEBT
  Assess ability to repay: cash generation, debt service capacity, asset collateral.
  Price rate to reflect risk. Approve less (or deny) when the credit picture doesn't
  support what the firm wants. Explain your reasoning.

  UNDERWRITING DISCIPLINE (Wave ν+4):
  Pre-revenue / pre-profit firms should generally NOT receive term debt — they
  should raise equity instead. Term debt requires:
    - A positive operating cash flow stream that comfortably services interest
      (interest coverage well above 1)
    - Pledgeable collateral: PP&E, inventory, receivables (intangible R&D
      investment is NOT good collateral)
    - A reasonable debt-to-equity ratio post-loan (over-levered firms are risky)
    - A cash runway under the proposed loan that doesn't get materially worse

  Compute and report the standard credit ratios for each firm in your
  debt_reasoning: interest coverage, debt-to-equity, debt-to-assets, cash runway
  with proposed loan. State explicitly which checks pass and which fail.

  If the firm has no positive cash flow and no pledgeable assets, DECLINE
  the term debt and direct them to equity capital. Approving doomed loans
  destroys the firm's runway via interest burden AND your bank's NPV via
  default loss.

EQUITY OFFERINGS
  Consider: dilution impact on existing holders, firm's prior capital raises, use of
  proceeds, current share price, market conditions. Offering price is typically below
  market (a real offering discount). For severely distressed firms with very depressed
  stock, consider alternatives: reverse split, restructuring, smaller size, or decline.
  Your job is to price risk honestly; firms are allowed to fail.

REVIEW YOUR OWN TRACK RECORD
  The firm-specific data shows YOUR prior issuance decisions for each firm: when you
  approved a raise, at what price, and what the share price did afterwards. Use this
  to calibrate. If you've already approved multiple raises at falling prices, and
  the firm is still burning cash with no path to profitability, another raise is
  unlikely to solve the problem — it just transfers more value from new buyers to
  existing holders (who then get diluted again next quarter). Consider whether the
  firm's situation has changed, or whether you're enabling a death spiral.

DEATH-SPIRAL DISCIPLINE
  When a firm has issued equity repeatedly at successively lower prices without
  measurable improvement in operating fundamentals (revenue trajectory flat or
  declining, operating cash flow remaining negative, capability or brand stocks
  not advancing), you are observing a death-spiral pattern. Real investment
  banks recognize this and respond:
    - Decline further routine raises (fee opportunity is not worth the
      reputational damage of underwriting a doomed offering).
    - Recommend the firm consider a structural alternative: a reverse split,
      a strategic restructuring, a sale process, or — if no buyer exists —
      a controlled wind-down.
    - When a firm in this pattern requests yet another raise, your
      `market_discussion` should explicitly flag the death-spiral concern,
      and your `retry_guidance` should describe what fundamental change
      would be needed before you would approve another offering.
  The point is not to refuse all distressed financings — biotech survives
  on distressed financings — but to refuse the financings that have no
  realistic path to recovery. Use judgment based on the firm's trailing
  trajectory of price-per-share, revenue, operating cash flow, and
  cumulative dilution.

FIRMS ARE DISTINCT
  A firm with strong fundamentals and clear use of proceeds gets favorable terms.
  A firm that keeps returning for dilutive raises without a path to profitability
  gets tighter terms or denial. Name the pattern in your reasoning.

WHEN YOU DECLINE OR HAIRCUT (Wave ν+10 item 10): you must produce a
``market_discussion`` field — 2-3 sentences describing the public credit-
market or equity-market conditions that bear on this issuance, plus a
``retry_guidance`` field — 1-2 sentences telling the firm what would
need to change for the issuance to clear (a smaller size, a longer
maturity, a higher rate the firm is willing to accept, an equity
buffer, an equity issuance instead, or a delay until conditions
improve). The firm sees these next quarter and may resubmit a
modified issuance request. Silence on a decline is unacceptable —
the discussion is the public price-formation signal that the
post-trade record carries forward.

Output JSON:
```json
{"firms": [{"firm_id": "...", "term_debt_approved": <dollar amount, 0 if denied>, "term_debt_rate_quarterly": <your rate>, "equity_offering_approved": <dollar amount, 0 if not requested or denied>, "equity_offering_price": <your price>, "debt_reasoning": "<2-3 sentences>", "equity_reasoning": "<2-3 sentences: your judgment on dilution, price, sizing, and how prior raises have played out>", "market_discussion": "<required when declining: 2-3 sentences on credit/equity-market conditions>", "retry_guidance": "<required when declining: 1-2 sentences on what would clear next quarter>"}]}
```"""


SYSTEM_PROMPT_WITH_COVENANTS = SYSTEM_PROMPT + """

DEBT FACILITY STRUCTURING (enabled this run):
When you approve term debt, you also structure the facility. For each approved term
debt raise, specify:

  - facility_type: one of "bank_term", "bond", "convertible_bond". Bank term loans
    are typically smaller with tight covenants. Bonds are larger and public, with
    looser covenants and bullet maturity. Convertibles let creditors upside-share.
  - amortization_type: "bullet" (principal due at maturity) or "amortizing"
    (principal amortized straight-line).
  - maturity_quarters: how many quarters from origination to maturity. Bank
    term loans are typically shorter-dated; bonds and convertibles longer.
  - covenants: a list of covenant dicts. Each has covenant_type and threshold.
    Valid covenant_types: "max_debt_to_ebitda", "min_interest_coverage",
    "min_cash_balance", "min_liquidity", "min_net_worth". Thresholds are numbers
    in the covenant's natural units (ratios are multiples; $ values are dollars).
    Number of covenants and which to use are your judgment.

    IMPORTANT about covenant *feasibility*: some covenant types only make sense
    for firms with positive ongoing EBITDA. Early-stage biotech firms with
    negative or near-zero EBITDA cannot satisfy debt/EBITDA or interest-coverage
    ratios (the measured ratio becomes undefined or trivially violated). For
    such firms prefer dollar-denominated covenants like min_cash_balance,
    min_liquidity, or min_net_worth — those remain measurable whatever EBITDA
    does. Each firm's briefing shows current TTM EBITDA and how standard
    ratios would measure today; use that to pick covenants the firm can
    actually meet. If the briefing says "UNDEFINED", that covenant type
    will trigger instant violation and defeat the purpose of the loan.
  - For convertibles only: conversion_ratio (shares per $1000 face) and
    conversion_price ($/share at which conversion is economic).

Extended JSON schema (same top-level "firms" list; add these fields alongside
term_debt_approved and friends):

```json
{"firms": [{"firm_id": "...",
  "term_debt_approved": <amount>, "term_debt_rate_quarterly": <rate>,
  "facility_type": "bank_term" | "bond" | "convertible_bond",
  "amortization_type": "bullet" | "amortizing",
  "maturity_quarters": <int>,
  "covenants": [{"covenant_type": "...", "threshold": <number>}, ...],
  "conversion_ratio": <float>, "conversion_price": <float>,
  "equity_offering_approved": <amount>, "equity_offering_price": <price>,
  "debt_reasoning": "...", "equity_reasoning": "..."}]}
```"""


def build_ibank_prompt(firms, flows, macro, raw_decisions, gazette, world=None):
    """Build the investment bank's evaluation prompt."""
    sections = []

    # Build per-firm history from compustat if available:
    # - issuance quarters with amounts + price at the time
    # - share count trajectory (shows dilution pattern)
    # - price trajectory (shows distress)
    per_firm_history = {}
    if world is not None:
        for row in world.compustat_rows:
            per_firm_history.setdefault(row.firm_id, []).append({
                "fyearq": row.fyearq,
                "fqtr": row.fqtr,
                "sstkq": float(row.sstkq or 0),
                "cshoq": float(row.cshoq or 0),  # in millions
                "prccq": float(row.prccq or 0),
                "saleq": float(row.saleq or 0),
                "niq": float(row.niq or 0),
                # Needed for EBITDA + interest-coverage feasibility hints
                "xintq": float(row.xintq or 0),
                "dpq": float(row.dpq or 0),
            })

    for fid in sorted(firms):
        firm = firms[fid]
        if not firm.is_active:
            continue
        f = flows.get(fid)
        if f is None:
            continue
        raw = raw_decisions.get(fid)
        debt_req = raw.debt_request if raw else 0
        eq_req = raw.equity_issuance_request if raw else 0
        debt = firm.revolver_balance + firm.long_term_debt
        runway = f"{firm.cash / max(1, -f.cfo):.1f}Q" if f.cfo < 0 else "positive CF"

        # ── Per-firm capital history (the bank's own track record with this firm) ──
        hist = per_firm_history.get(fid, [])
        hist.sort(key=lambda r: (r["fyearq"], r["fqtr"]))

        # Every quarter's actual equity issuance (where we approved > 0)
        issuance_lines = []
        for row in hist:
            if row["sstkq"] > 0 and row["prccq"] > 0:
                dilution_at_issue = row["sstkq"] / (row["cshoq"] * 1_000_000 * row["prccq"]) * 100
                current_px = firm.equity_price
                px_drop = (current_px / row["prccq"] - 1) * 100 if row["prccq"] > 0 else 0
                issuance_lines.append(
                    f"    FY{row['fyearq']}Q{row['fqtr']}: raised ${row['sstkq']/1e6:.0f}M @ "
                    f"${row['prccq']:.2f}/share (price since then: {px_drop:+.0f}%)"
                )

        # Trajectory summary (last 4Q)
        recent = hist[-4:]
        share_traj = " -> ".join(f"{r['cshoq']:.0f}M" for r in recent) if recent else "N/A"
        px_traj = " -> ".join(f"${r['prccq']:.2f}" for r in recent) if recent else "N/A"
        rev_traj = " -> ".join(f"${r['saleq']/1e6:.0f}M" for r in recent) if recent else "N/A"
        # EBITDA trajectory (NI + interest + depreciation, approximate)
        # Most biotech/pharma firms are pre-revenue with burn — EBITDA will be
        # very negative. Show this so the bank can pick covenants that make
        # economic sense for the firm's stage.
        ebitda_series = [
            (r.get("niq", 0) or 0) + (r.get("xintq", 0) or 0) + (r.get("dpq", 0) or 0)
            for r in hist
        ]
        ebitda_traj = (" -> ".join(f"${e/1e6:+.0f}M" for e in ebitda_series[-4:])
                       if ebitda_series else "N/A")
        ttm_ebitda = sum(ebitda_series[-4:]) if ebitda_series else 0.0
        ttm_interest = sum(r.get("xintq", 0) or 0 for r in hist[-4:]) if hist else 0.0

        # Covenant-feasibility hint (context, not a rule):
        # compute what each standard covenant ratio would measure today.
        if ttm_ebitda > 0:
            debt_to_ebitda = debt / ttm_ebitda
            de_str = f"{debt_to_ebitda:.1f}x"
        elif debt > 0:
            de_str = "UNDEFINED (TTM EBITDA <= 0 -- debt/EBITDA covenant is not meaningful for this firm)"
        else:
            de_str = "N/A (no debt yet)"
        if ttm_interest > 0 and ttm_ebitda > 0:
            ic_str = f"{ttm_ebitda/ttm_interest:.1f}x"
        elif ttm_interest > 0:
            ic_str = "UNDEFINED (TTM EBITDA <= 0)"
        else:
            ic_str = "N/A (no interest yet)"

        n_issuances = len(issuance_lines)
        total_raised = sum(row["sstkq"] for row in hist)
        initial_shares_approx = 10_000_000
        dilution_pct = (firm.shares_outstanding - initial_shares_approx) / initial_shares_approx * 100

        req_text = ""
        if debt_req > 0:
            req_text += f"\n  *** REQUESTING TERM DEBT: ${debt_req:,.0f} ***"
        if eq_req > 0:
            req_text += f"\n  *** REQUESTING EQUITY ISSUANCE: ${eq_req:,.0f} ***"
        if not req_text:
            req_text = "\n  (No financing requests this quarter)"

        issuance_block = "\n".join(issuance_lines) if issuance_lines else "    (none yet)"

        sections.append(
            f"{fid}:{req_text}\n"
            f"  Revenue: ${f.net_sales:,.0f}/Q | NI: ${f.net_income:,.0f}\n"
            f"  Cash: ${firm.cash:,.0f} | Runway: {runway}\n"
            f"  Total debt: ${debt:,.0f} | Equity: ${firm.total_equity:,.0f}\n"
            f"  TTM EBITDA: ${ttm_ebitda/1e6:+.1f}M | TTM interest: ${ttm_interest/1e6:.2f}M\n"
            f"  Current debt/EBITDA: {de_str}\n"
            f"  Current interest coverage: {ic_str}\n"
            f"  Assets: ${firm.total_assets:,.0f} | Shares: {firm.shares_outstanding:,} "
            f"(dilution since IPO: {dilution_pct:+.0f}%)\n"
            f"  Current equity price: ${firm.equity_price:.2f}/sh\n"
            f"  Debt/Assets: {debt/max(1,firm.total_assets):.0%} | "
            f"Debt/Equity: {debt/max(1,firm.total_equity):.1f}x\n"
            f"  TRAJECTORY (last 4Q):\n"
            f"    Shares out: {share_traj}\n"
            f"    Price/sh:   {px_traj}\n"
            f"    Revenue:    {rev_traj}\n"
            f"    EBITDA:     {ebitda_traj}\n"
            f"  YOUR PRIOR ISSUANCE DECISIONS FOR THIS FIRM ({n_issuances} issuances, ${total_raised/1e6:.0f}M total):\n"
            f"{issuance_block}"
        )
    user = (
        f"=== INVESTMENT BANK EVALUATION — Q{macro.fqtr} {macro.fyear} ===\n"
        f"Risk-free rate: {macro.risk_free_rate*400:.1f}% annual\n\n"
        + "\n\n".join(sections)
        + f"\n\nGAZETTE: {gazette[:300] if gazette else '(none)'}"
        + "\n\nEvaluate each firm's requests. Deny if too risky. Price debt by risk."
    )
    return SYSTEM_PROMPT, user


from .parsing_utils import parse_float as _parse_float  # noqa: E402


def _parse_facility_structure(f: dict) -> dict:
    """Extract Stage 3c facility-structure fields (facility_type, covenants, etc.).

    Returns a dict even when fields are absent — caller decides whether to act.
    Structural validation happens at add_facility time.
    """
    ftype = f.get("facility_type", "bank_term")
    amort = f.get("amortization_type", "bullet")
    maturity = int(_parse_float(f.get("maturity_quarters", 20), 20))
    cov_raw = f.get("covenants", []) or []
    covenants = []
    if isinstance(cov_raw, list):
        for c in cov_raw:
            if not isinstance(c, dict):
                continue
            ctype = c.get("covenant_type", "")
            thresh = _parse_float(c.get("threshold", 0))
            if ctype:
                covenants.append({"covenant_type": ctype, "threshold": thresh})
    conv_ratio = _parse_float(f.get("conversion_ratio", 0))
    conv_price = _parse_float(f.get("conversion_price", 0))
    return {
        "facility_type": ftype,
        "amortization_type": amort,
        "maturity_quarters": max(1, maturity),
        "covenants": covenants,
        "conversion_ratio": conv_ratio,
        "conversion_price": conv_price,
    }


def make_investment_bank(backend: LLMBackend, state_ref: list,
                          debt_covenants_enabled: bool = False):
    """Create investment bank agent function.

    When debt_covenants_enabled=True, the bank also structures the facility
    (type, covenants, maturity, amortization) which the orchestrator uses to
    create a DebtFacility via debt_management.add_facility.
    """
    system_prompt = (SYSTEM_PROMPT_WITH_COVENANTS
                     if debt_covenants_enabled else SYSTEM_PROMPT)

    def agent(firms, macro, params, raw_decisions=None):
        world = state_ref[0] if state_ref else None
        flows = world.last_quarter_flows if world else {}
        gazette = world.gazettes[-1] if world and world.gazettes else ""
        rds = raw_decisions or {}
        _, user = build_ibank_prompt(firms, flows, macro, rds, gazette, world=world)
        result = backend.complete_json(system_prompt, user)
        if result is None:
            return None
        decisions = {}
        for f in result.get("firms", []):
            fid = f.get("firm_id", "")
            if not fid:
                continue
            term_amt = _parse_float(f.get("term_debt_approved", 0))
            term_rate = _parse_float(f.get("term_debt_rate_quarterly", 0.03), 0.03)
            eq_amt = _parse_float(f.get("equity_offering_approved", 0))
            eq_price = _parse_float(f.get("equity_offering_price", 0))
            decision = {
                "term_debt_approved": max(0, term_amt),
                # Safety-only clamp: rate in [0, 1.0] quarterly (0 to 400%/yr).
                # No behavioral ceiling; distressed lenders can price honestly.
                "term_debt_rate": max(0.0, min(1.0, term_rate)),
                "equity_approved": max(0, eq_amt),
                "equity_price": max(0.01, eq_price) if eq_price > 0 else 0,
                "debt_reasoning": f.get("debt_reasoning", ""),
                "equity_reasoning": f.get("equity_reasoning", ""),
                # Wave ν+10 item 10: when declining, the bank produces a
                # public market_discussion and retry_guidance. These are
                # written to gazettes and (via state.last_ibank_feedback)
                # included in the next quarter's firm prompt.
                "market_discussion": str(f.get("market_discussion", ""))[:600],
                "retry_guidance": str(f.get("retry_guidance", ""))[:400],
            }
            if debt_covenants_enabled:
                decision["facility_structure"] = _parse_facility_structure(f)
            decisions[fid] = decision
        return decisions
    return agent


def make_investment_bank_panel(agents: list, names: list[str] | None = None):
    """Wave ν+10 item 7: multi-investment-bank competition wrapper.

    Wraps a list of single-bank `agent(firms, macro, params, raw_decisions)`
    functions into a single callable. Per-firm selection rules:

      * Term debt: among banks that approve a positive amount, pick the
        one with the LOWEST quarterly rate. Ties broken by largest
        approved amount, then by bank order.
      * Equity offering: among banks that approve a positive amount,
        pick the one with the HIGHEST equity_price (best price for
        the issuer). Ties broken by largest approved amount.

    Term-debt and equity selections are made INDEPENDENTLY: a firm can
    receive its term-debt facility from bank A and its equity placement
    from bank B if those are the best terms available.

    Returned per-firm decisions carry `winning_bank_debt`,
    `winning_bank_equity`, and `competing_offers` for transparency.
    """
    if not agents:
        raise ValueError("make_investment_bank_panel requires at least one agent")
    if names is None:
        names = [f"ibank_{i+1}" for i in range(len(agents))]
    if len(names) != len(agents):
        raise ValueError("names list must have same length as agents")

    def panel_agent(firms, macro, params, raw_decisions=None):
        import concurrent.futures as _cf
        def _call(idx):
            try:
                return idx, agents[idx](firms, macro, params, raw_decisions)
            except Exception as e:
                return idx, {"_error": True, "_exception": f"{type(e).__name__}: {e}"}
        with _cf.ThreadPoolExecutor(max_workers=len(agents)) as pool:
            raw = list(pool.map(_call, range(len(agents))))
        per_bank = {idx: r for idx, r in raw}

        decisions: dict[str, dict] = {}
        all_firm_ids = set()
        for r in per_bank.values():
            if isinstance(r, dict) and not r.get("_error"):
                all_firm_ids.update(r.keys())

        for fid in all_firm_ids:
            debt_offers = []
            equity_offers = []
            for idx, r in per_bank.items():
                if not isinstance(r, dict) or r.get("_error"):
                    continue
                t = r.get(fid)
                if not t:
                    continue
                if (t.get("term_debt_approved", 0) or 0) > 0:
                    debt_offers.append({
                        "bank": names[idx],
                        "term_debt_approved": float(t["term_debt_approved"]),
                        "term_debt_rate": float(t.get("term_debt_rate", 0.03) or 0.03),
                        "debt_reasoning": t.get("debt_reasoning", ""),
                        "facility_structure": t.get("facility_structure"),
                    })
                if (t.get("equity_approved", 0) or 0) > 0:
                    equity_offers.append({
                        "bank": names[idx],
                        "equity_approved": float(t["equity_approved"]),
                        "equity_price": float(t.get("equity_price", 0) or 0),
                        "equity_reasoning": t.get("equity_reasoning", ""),
                    })

            decision = {
                "term_debt_approved": 0,
                "term_debt_rate": 0.03,
                "equity_approved": 0,
                "equity_price": 0,
                "debt_reasoning": "",
                "equity_reasoning": "",
            }

            if debt_offers:
                # Lowest rate wins; tiebreak by largest amount.
                debt_offers.sort(key=lambda o: (o["term_debt_rate"], -o["term_debt_approved"]))
                w = debt_offers[0]
                decision["term_debt_approved"] = w["term_debt_approved"]
                decision["term_debt_rate"] = w["term_debt_rate"]
                decision["debt_reasoning"] = (
                    f"[{w['bank']} won {len(debt_offers)}-way debt bid] "
                    + w["debt_reasoning"]
                )[:400]
                decision["winning_bank_debt"] = w["bank"]
                if w.get("facility_structure"):
                    decision["facility_structure"] = w["facility_structure"]

            if equity_offers:
                # Highest price wins (best for issuer); tiebreak by largest amount.
                equity_offers.sort(key=lambda o: (-o["equity_price"], -o["equity_approved"]))
                w = equity_offers[0]
                decision["equity_approved"] = w["equity_approved"]
                decision["equity_price"] = w["equity_price"]
                decision["equity_reasoning"] = (
                    f"[{w['bank']} won {len(equity_offers)}-way equity bid] "
                    + w["equity_reasoning"]
                )[:400]
                decision["winning_bank_equity"] = w["bank"]

            decision["competing_debt_offers"] = debt_offers
            decision["competing_equity_offers"] = equity_offers

            decisions[fid] = decision

        return decisions

    return panel_agent
