"""
Commercial Bank Agent: LLM-powered revolving credit decisions.

Evaluates each firm's creditworthiness and sets revolver terms:
- Commitment size (how large a credit line)
- Interest rate (reflecting risk)
- Reasoning for each decision

The bank sees published financials (Compustat-equivalent) and macro state,
but NOT private firm data (R&D allocation, capability stock, board minutes).
"""

from __future__ import annotations
from .types import FirmState, MacroState, QuarterFlows
from .llm_backends import LLMBackend


SYSTEM_PROMPT = """You are a commercial bank evaluating revolving credit facilities for pharmaceutical firms.

A revolver is a short-term credit line firms draw on for working capital. You decide:
1. How large a credit line to offer (commitment size)
2. What interest rate to charge (quarterly rate)
3. Your risk assessment

UNDERWRITING DISCIPLINE (Wave ν+4):
Before you offer any credit, you MUST perform a structured underwriting review for each firm. Real commercial bankers don't lend to firms that obviously can't repay — that's how banks lose money. Run through these checks explicitly in your reasoning:

  1. CASH FLOW COVERAGE: Does the firm have positive operating cash flow that can comfortably service the interest you'd charge? If operating cash flow is negative or near zero, debt is the wrong instrument — the firm should raise equity. A revolver for a firm with no cash-flow stream just accelerates default.

  2. PLEDGEABLE COLLATERAL: What assets back the loan? PP&E, inventory, and receivables are pledgeable. Goodwill and intangible R&D investment are NOT good collateral. A firm with mostly cash and intangible R&D has limited collateral support.

  3. STANDARD CREDIT RATIOS: Compute and report the ratios you find relevant for this firm:
     - Interest coverage (operating cash flow / proposed interest expense) — comfortable banking practice expects this to be well above 1
     - Debt-to-equity (total debt / total equity) — over-levered firms are riskier
     - Debt-to-assets — how much of the asset base is encumbered
     - Cash runway under proposed loan — does adding interest expense shorten runway dangerously?

  4. STAGE FIT: Pre-revenue / pre-profit firms should NOT take on revolver debt — they should raise equity from PE/VC who price the risk via dilution rather than fixed interest. Only firms with proven, recurring cash flow are good revolver candidates.

If the firm fails the cash-flow + collateral + ratio checks, DECLINE (set commitment to 0). State explicitly which check failed. The firm will be redirected to equity capital.

Strong-credit firms get larger lines at lower rates; riskier firms get smaller lines at higher rates or denial. Rate should be higher than the risk-free rate (that's your spread for lending).

Output JSON:
```json
{"firms": [{"firm_id": "...", "revolver_commitment": <dollar amount; 0 if declined>, "revolver_rate_quarterly": <your rate>, "risk_assessment": "<low/medium/high/critical/decline>", "ratio_analysis": "<your stated ratios + which checks pass/fail>", "reasoning": "<2-3 sentences>"}]}
```"""


VIOLATION_RESOLVER_PROMPT = """You are a commercial banker handling covenant violations
on debt facilities you (or peer banks) originated. Each violation has three standard
resolutions:

  1. WAIVE — accept the breach as one-time; charge a waiver fee for the trouble.
     Use when the violation looks temporary, firm is otherwise healthy, relationship
     value matters. Fee size is your judgment.
  2. AMEND — relax the covenant threshold (and optionally raise the rate). Use when
     the firm's fundamentals have shifted but remain viable. New threshold should
     reflect the new reality, not paper over risk.
  3. ACCELERATE — demand full immediate repayment. Use when the firm has deteriorated
     such that waiting just increases your loss. This often triggers default.

You judge which path fits each violation. No magic formulas for fees, new thresholds,
or rate bumps — reflect the firm's situation, the covenant type, how much the firm
has breached by, whether it's been violated before.

Output JSON:
```json
{"resolutions": [{"firm_id": "...", "facility_id": "...", "covenant_type": "...",
  "action": "waive" | "amend" | "accelerate",
  "waiver_fee": <dollar amount, only if action=waive>,
  "new_threshold": <number, only if action=amend>,
  "new_rate_quarterly": <rate, only if action=amend and you raise rate; else same as old>,
  "reasoning": "<2-3 sentences>"}]}
```"""


EMERGENCY_BRIDGE_PROMPT = """You are a distressed-debt lender evaluating emergency bridge
financing for a firm that is about to default. This is specialized, high-risk lending:
you price for both the probability of survival and the downside scenario.

The firm has exhausted its revolver and normal financing options. They need immediate
cash to cover a shortfall this quarter; otherwise they go bankrupt. As a bridge lender
you can:
- Approve the bridge (specify amount and rate — reflect the risk honestly)
- Approve a partial bridge (less than asked)
- Decline — the firm then defaults

Consider: asset coverage available to pledge, cash flow trajectory (is this likely a
recoverable firm or a terminal case), debt already outstanding vs total assets, macro
environment, and your recovery prospects if they do default.

Bridge rates are always materially higher than normal lending — the spread reflects
distressed risk premium. You judge the magnitude.

Output JSON:
```json
{
  "approved_amount": <dollar amount, 0 if declined>,
  "quarterly_rate": <your rate as decimal, e.g. 0.08 = 8%/Q>,
  "reasoning": "<2-3 sentences including your survival assessment and rate rationale>"
}
```"""


def build_bank_prompt(firms, flows, macro, gazette, portfolio_history=None, world=None):
    """Build the commercial bank's evaluation prompt.

    Wave ν+12: optional `world` arg lets us append a comprehensive history
    block (full Compustat panel across all firms × compressed history,
    past debt facilities industry-wide, prior bank debrief notes).
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
        runway = f"{firm.cash / max(1, -f.cfo):.1f}Q" if f.cfo < 0 else "positive CF"
        sections.append(
            f"{fid}:\n"
            f"  Revenue: ${f.net_sales:,.0f}/Q | Cash: ${firm.cash:,.0f} | Runway: {runway}\n"
            f"  Total debt: ${debt:,.0f} | Equity: ${firm.total_equity:,.0f}\n"
            f"  Operating CF: ${f.cfo:,.0f} | Interest due: ${f.interest_expense:,.0f}\n"
            f"  Assets: ${firm.total_assets:,.0f} | PP&E: ${firm.ppe_net:,.0f}\n"
            f"  Current revolver: ${firm.revolver_balance:,.0f} / ${firm.revolver_commitment:,.0f} committed"
        )

    # Wave ν+12: append comprehensive history.
    history_section = ""
    if world is not None:
        try:
            from .agent_history import render_intermediary_history
            ext = render_intermediary_history(world, macro, role="bank")
            if ext:
                history_section = (
                    "\n\n=== EXTENDED INDUSTRY HISTORY YOU HAVE ACCESS TO ===\n"
                    "Anchor your revolver underwriting on the actual track\n"
                    "record below — not just this-quarter snapshots.\n\n"
                    f"{ext}\n"
                )
        except Exception:
            pass

    user = (
        f"=== CREDIT EVALUATION — Q{macro.fqtr} {macro.fyear} ===\n"
        f"Risk-free rate: {macro.risk_free_rate*400:.1f}% annual\n\n"
        + "\n\n".join(sections)
        + f"\n\nGAZETTE: {gazette[:300] if gazette else '(none)'}"
        + history_section
    )
    return SYSTEM_PROMPT, user


def make_commercial_bank(backend: LLMBackend, state_ref: list):
    """Create commercial bank agent function."""
    def agent(firms, macro, params):
        world = state_ref[0] if state_ref else None
        flows = world.last_quarter_flows if world else {}
        gazette = world.gazettes[-1] if world and world.gazettes else ""
        sys, user = build_bank_prompt(firms, flows, macro, gazette, world=world)
        result = backend.complete_json(sys, user)
        if result is None:
            return None
        # Wave ν+9 Bug M6: use shared defensive parser. Bare `float()` here
        # crashes on malformed LLM output that the investment_bank parser
        # tolerates; consolidating ensures both intermediaries handle bad
        # responses identically.
        from .parsing_utils import parse_float as _pf
        decisions = {}
        for f in result.get("firms", []):
            fid = f.get("firm_id", "")
            if fid:
                decisions[fid] = {
                    "revolver_commitment": _pf(f.get("revolver_commitment"), 0.0),
                    "revolver_rate": _pf(f.get("revolver_rate_quarterly"), 0.02),
                    "reasoning": f.get("reasoning", ""),
                    "risk": f.get("risk_assessment", "medium"),
                }
        return decisions
    return agent


def make_commercial_bank_panel(agents: list, names: list[str] | None = None):
    """Wave ν+10 item 7: multi-bank competition wrapper.

    Wraps a list of single-bank `agent(firms, macro, params)` functions
    into a single callable that queries every bank in parallel and, for
    each firm, picks the most attractive offer. Selection rule:

        For each firm, consider only banks that quoted a positive
        commitment. Among those, pick the bank with the LOWEST
        revolver_rate. Ties broken by largest commitment, then by bank
        order (deterministic).

    The returned per-firm dict carries a `winning_bank` field and a
    `competing_offers` field listing all valid quotes — so the run
    record carries the full competitive picture, not just the winner.

    A firm with no positive quotes from any bank gets no facility this
    quarter (consistent with single-bank behaviour when the bank
    declines).

    `names` is an optional list (same length as `agents`) of human-
    readable bank labels. Defaults to `bank_1, bank_2, ...`.
    """
    if not agents:
        raise ValueError("make_commercial_bank_panel requires at least one agent")
    if names is None:
        names = [f"bank_{i+1}" for i in range(len(agents))]
    if len(names) != len(agents):
        raise ValueError("names list must have same length as agents")

    def panel_agent(firms, macro, params):
        import concurrent.futures as _cf
        # Query each bank in parallel.
        def _call(idx):
            try:
                return idx, agents[idx](firms, macro, params)
            except Exception as e:
                return idx, {"_error": True, "_exception": f"{type(e).__name__}: {e}"}
        with _cf.ThreadPoolExecutor(max_workers=len(agents)) as pool:
            raw = list(pool.map(_call, range(len(agents))))
        per_bank: dict[int, dict] = {idx: r for idx, r in raw}

        # For each firm, collect quotes from all banks and pick winner.
        decisions: dict[str, dict] = {}
        all_firm_ids = set()
        for r in per_bank.values():
            if isinstance(r, dict) and not r.get("_error"):
                all_firm_ids.update(r.keys())
        for fid in all_firm_ids:
            offers = []
            for idx, r in per_bank.items():
                if not isinstance(r, dict) or r.get("_error"):
                    continue
                terms = r.get(fid)
                if not terms:
                    continue
                commit = float(terms.get("revolver_commitment", 0) or 0)
                if commit <= 0:
                    continue
                offers.append({
                    "bank": names[idx],
                    "revolver_commitment": commit,
                    "revolver_rate": float(terms.get("revolver_rate", 0.02) or 0.02),
                    "risk": terms.get("risk", "medium"),
                    "reasoning": terms.get("reasoning", ""),
                })
            if not offers:
                continue
            # Lowest rate wins; tiebreak by largest commitment, then by name order.
            offers.sort(key=lambda o: (o["revolver_rate"], -o["revolver_commitment"]))
            winner = offers[0]
            decisions[fid] = {
                "revolver_commitment": winner["revolver_commitment"],
                "revolver_rate": winner["revolver_rate"],
                "risk": winner["risk"],
                "reasoning": (
                    f"[{winner['bank']} won {len(offers)}-way bid] "
                    + winner["reasoning"]
                )[:400],
                "winning_bank": winner["bank"],
                "competing_offers": offers,
            }
        return decisions

    return panel_agent


def make_violation_resolver(backend: LLMBackend):
    """Create a covenant-violation-resolution agent.

    Input: list of pending violations (each: firm_id, facility_id, covenant_type,
    threshold, measured_ratio, quarter) + current firms dict for context.
    Output: dict firm_id -> list of resolution actions to apply.

    Caller applies resolutions via debt_management.apply_waiver / apply_amendment
    / apply_acceleration. Reasoning is logged.
    """

    def resolver(violations: list, firms: dict, macro) -> list:
        if not violations:
            return []

        # Build context per unique (firm, facility) pair
        viol_lines = []
        for v in violations:
            fid = v.get("firm_id", "?")
            firm = firms.get(fid)
            fac_id = v.get("facility_id", "?")
            cov_type = v.get("covenant_type", "?")
            measured = v.get("measured_ratio", 0)
            threshold = v.get("threshold", 0)
            # Find the facility for context
            fac = None
            if firm:
                for f in firm.debt_facilities:
                    if f.facility_id == fac_id:
                        fac = f
                        break
            cash_str = f"${firm.cash:,.0f}" if firm else "unknown"
            debt_str = (f"${firm.revolver_balance + firm.long_term_debt:,.0f}"
                        if firm else "unknown")
            assets_str = f"${firm.total_assets:,.0f}" if firm else "unknown"
            equity_str = f"${firm.total_equity:,.0f}" if firm else "unknown"
            fac_desc = ""
            if fac:
                fac_desc = (f"facility {fac.facility_type} "
                            f"${fac.current_balance:,.0f} @ "
                            f"{fac.coupon_rate_quarterly*400:.1f}%/yr, "
                            f"matures Q{fac.maturity_quarter}")
            viol_lines.append(
                f"- firm_id={fid}, facility_id={fac_id}, covenant={cov_type}\n"
                f"  threshold={threshold:.2f}, measured={measured:.2f}\n"
                f"  firm: cash={cash_str} debt={debt_str} assets={assets_str} "
                f"equity={equity_str}\n"
                f"  {fac_desc}"
            )

        user = (
            f"=== COVENANT VIOLATION RESOLUTION — Q{macro.fqtr} {macro.fyear} ===\n"
            f"Risk-free rate: {macro.risk_free_rate*400:.1f}% annual\n\n"
            f"{len(violations)} violations to resolve:\n\n"
            + "\n\n".join(viol_lines)
            + "\n\nDecide each. Output JSON per the schema."
        )
        try:
            result = backend.complete_json(VIOLATION_RESOLVER_PROMPT, user)
        except Exception as e:
            return [{"error": f"resolver LLM failed: {e}"}]
        if result is None:
            return [{"error": "resolver LLM returned None"}]

        out = []
        for r in result.get("resolutions", []) or []:
            if not isinstance(r, dict):
                continue
            action = r.get("action", "waive")
            if action not in ("waive", "amend", "accelerate"):
                action = "waive"
            # Safety clamp: rate in [0, 1.0] quarterly. LLMs sometimes return
            # rate as percent (7.0 meaning 7%) rather than fraction — the
            # clamp catches 7.0+ as obvious unit-confusion, but still permits
            # legitimately punitive distressed rates up to 400%/yr.
            raw_rate = float(r.get("new_rate_quarterly", 0) or 0)
            new_rate_q = max(0.0, min(1.0, raw_rate))
            out.append({
                "firm_id": r.get("firm_id", ""),
                "facility_id": r.get("facility_id", ""),
                "covenant_type": r.get("covenant_type", ""),
                "action": action,
                "waiver_fee": max(0.0, float(r.get("waiver_fee", 0) or 0)),
                "new_threshold": float(r.get("new_threshold", 0) or 0),
                "new_rate_quarterly": new_rate_q,
                "reasoning": r.get("reasoning", ""),
            })
        return out
    return resolver


def make_emergency_bridge(backend: LLMBackend, state_ref: list):
    """Create emergency bridge lending agent.

    Called only when a firm has negative cash and has exhausted its revolver.
    Returns (approved_amount, rate) — zero amount means bridge declined, firm defaults.
    Replaces the prior hardcoded `risk_free_rate + 4%` penalty.
    """
    def bridge_fn(firm, shortfall, macro, params):
        total_debt = firm.revolver_balance + firm.long_term_debt
        debt_to_assets = total_debt / max(1, firm.total_assets)
        runway_msg = "(cash already exhausted)"

        user = f"""EMERGENCY BRIDGE REQUEST — {firm.firm_id}, Q{macro.fqtr} {macro.fyear}

SITUATION:
  Cash shortfall this quarter: ${shortfall:,.0f}
  Firm has exhausted its revolver; this bridge is the last option before default.

FIRM FINANCIALS:
  Cash: ${firm.cash:,.0f} {runway_msg}
  Total assets: ${firm.total_assets:,.0f}
  Total debt: ${total_debt:,.0f} (debt/assets = {debt_to_assets:.0%})
  PP&E (collateral): ${firm.ppe_net:,.0f}
  Inventory: ${firm.inventory_value:,.0f}
  Accounts receivable: ${firm.accounts_receivable:,.0f}
  Total equity: ${firm.total_equity:,.0f}

MACRO:
  Risk-free rate: {macro.risk_free_rate*400:.1f}% annual

Evaluate and decide."""

        try:
            result = backend.complete_json(EMERGENCY_BRIDGE_PROMPT, user)
        except Exception as e:
            return {"approved_amount": 0, "rate": 0, "reasoning": f"bridge LLM failed: {e}"}
        if result is None:
            return {"approved_amount": 0, "rate": 0, "reasoning": "bridge decision failed to parse"}

        amount = max(0.0, float(result.get("approved_amount", 0) or 0))
        rate = float(result.get("quarterly_rate", 0) or 0)
        # Sanity: cap at 100% quarterly (structural, prevents runaway)
        rate = max(0.0, min(1.0, rate))
        return {
            "approved_amount": amount,
            "rate": rate,
            "reasoning": result.get("reasoning", ""),
        }
    return bridge_fn
