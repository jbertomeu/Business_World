"""
Environment output verifier.

The environment LLM occasionally produces hallucinated outputs — most notably
total_demand spikes 10-100x trend with no narrative cause, or units_sold
allocations that violate firm production caps. These poison downstream
accounting (firm IS shows fake revenue), market valuation, and research data.

Two-layer guard:
  1. `is_anomalous(env_outcome, recent_history)` — pure-Python deterministic
     check. Returns (anomaly_flag, reasons). Cheap; runs every quarter.
  2. `make_env_verifier(backend)` — LLM verifier called only when anomaly_flag
     is True. The verifier sees the env's proposal + recent trajectory and
     either ratifies it (with reasoning) or revises it.

This keeps the simulation emergent (env still LLM-driven, no hardcoded demand
formulas), while preventing single-quarter hallucinations from cascading.
"""

from __future__ import annotations

from .llm_backends import LLMBackend


# ── Anomaly trigger (deterministic) ────────────────────────────────────


def is_anomalous(env_outcome: dict,
                  recent_quarter_revenues: list[float],
                  baseline_demand: int,
                  production_caps: dict[str, int],
                  firm_prices: dict[str, float] | None = None) -> tuple[bool, list[str]]:
    """Detect obvious hallucinations in env output. Returns (flag, reasons).

    Conservative — only flags when something is clearly off vs trend, NOT
    every large move. The verifier LLM gets the final say.

    Heuristics (all structural, none about specific firm choices):
      H1. total_demand > 5x mean of last 4Q industry revenue (proxy for demand)
      H2. total_demand > 5x baseline_demand from logit model
      H3. any firm units_sold exceeds production cap (env cap was supposed to
          enforce this; if it slipped through, that's also an anomaly)
      H4. market_shares sum way off from 1.0 (>0.10 deviation)
      H5. implied revenue (units × firm prices) > 5x recent revenue trend.
          Catches the case where units stayed in range but firm priced 10-100x
          higher than typical, producing absurd revenue (the $6B Q2 spike in
          validation v2 was this case: units ~1287 but firm priced at $12M).
    """
    reasons: list[str] = []
    total_demand = env_outcome.get("total_demand", 0)
    firm_outcomes = env_outcome.get("firm_outcomes", {})

    # H1: vs recent revenue trajectory (using $95K avg price, units → revenue
    # at scale; if recent revenues averaged $X, demand ≈ X / 95K units).
    if recent_quarter_revenues and len(recent_quarter_revenues) >= 2:
        mean_recent_rev = sum(recent_quarter_revenues) / len(recent_quarter_revenues)
        if mean_recent_rev > 0:
            implied_demand_band = mean_recent_rev / 95_000.0  # rough units conversion
            if total_demand > 5.0 * max(implied_demand_band, 1):
                reasons.append(
                    f"H1: total_demand={total_demand:,} > 5x recent revenue "
                    f"trend ({implied_demand_band:,.0f} unit-equiv from "
                    f"avg ${mean_recent_rev/1e6:.1f}M revenue)"
                )

    # H2: vs logit baseline
    if baseline_demand > 0 and total_demand > 5.0 * baseline_demand:
        reasons.append(
            f"H2: total_demand={total_demand:,} > 5x baseline "
            f"({baseline_demand:,} from logit model)"
        )

    # H3: any firm exceeds its production cap (defensive — orchestrator already
    # clamps these in env_outcome post-processing, but check here too)
    for fid, fo in firm_outcomes.items():
        if isinstance(fo, dict):
            units_sold = fo.get("units_sold", 0)
        else:
            units_sold = getattr(fo, "units_sold", 0)
        cap = production_caps.get(fid, 0)
        if cap > 0 and units_sold > cap * 1.05:  # 5% tolerance
            reasons.append(
                f"H3: {fid} units_sold={units_sold:,} > production cap "
                f"({cap:,})"
            )

    # H4: shares sum
    share_sum = 0.0
    for fo in firm_outcomes.values():
        if isinstance(fo, dict):
            share_sum += fo.get("market_share", 0)
        else:
            share_sum += getattr(fo, "market_share", 0)
    if share_sum > 0 and abs(share_sum - 1.0) > 0.10:
        reasons.append(
            f"H4: market_shares sum to {share_sum:.2f} (>0.10 from 1.0)"
        )

    # H5: implied total revenue at this Q's firm prices vs recent revenue.
    # Catches absurd-price hallucinations: units OK but price → 100x trend.
    # Fires with >= 1 history entry (firms can spike in Q2 with only Q1 baseline).
    if firm_prices and recent_quarter_revenues:
        mean_recent_rev = sum(recent_quarter_revenues) / len(recent_quarter_revenues)
        implied_revenue = 0.0
        for fid, fo in firm_outcomes.items():
            if isinstance(fo, dict):
                units_sold = fo.get("units_sold", 0)
            else:
                units_sold = getattr(fo, "units_sold", 0)
            implied_revenue += units_sold * firm_prices.get(fid, 0.0)
        if mean_recent_rev > 0 and implied_revenue > 5.0 * mean_recent_rev:
            reasons.append(
                f"H5: implied revenue ${implied_revenue/1e6:,.0f}M = sum of "
                f"(units_sold × firm_price) > 5x recent trend "
                f"(${mean_recent_rev/1e6:.1f}M); likely an absurd price set "
                f"by a firm that env accepted at face value"
            )

    return (len(reasons) > 0), reasons


# ── LLM verifier ────────────────────────────────────────────────────────


VERIFIER_PROMPT = """You are reviewing a market-resolution output produced by
the environment agent for a pharmaceutical industry simulation. The output has
been flagged by automated checks as potentially anomalous (numbers far outside
recent trend, units_sold exceeding production caps, shares not summing to 1).

Your job: decide whether the output is plausible or a hallucination, and
either ratify or revise it.

Be conservative about revising. Big moves CAN happen for real reasons (a
catalyst event, a competitor failure, a regulatory shift). Only revise when
the proposal is clearly inconsistent with:
  - Recent revenue trajectory (no narrative-explained catalyst for a sudden
    multi-x jump)
  - Physical capacity (firms can't sell more than they produced + inventory)
  - Industry size (a 5-firm pre-Gen-2 biotech market doesn't suddenly become
    a $10B/quarter industry)

Output JSON:
```json
{
  "verified": true | false,
  "reason": "<1-2 sentences explaining your judgment>",
  "revised_total_demand": <integer; only present if verified=false>,
  "revised_firm_outcomes": [
    {"firm_id": "...", "units_sold": <int>, "market_share": <0-1>}
  ]
}
```

If verified=true, you don't need to include the revised fields. If false,
provide both revised_total_demand and revised_firm_outcomes (covering all
firms in the original output)."""


def make_env_verifier(backend: LLMBackend):
    """Factory: returns a verifier(env_outcome, recent_revs, baseline_demand,
    production_caps, macro, anomaly_reasons) function.

    The function calls the LLM only when invoked (caller decides). Returns
    a possibly-revised env_outcome dict.
    """

    def verify(env_outcome: dict,
                recent_quarter_revenues: list[float],
                baseline_demand: int,
                production_caps: dict[str, int],
                macro,
                anomaly_reasons: list[str]) -> dict:
        firm_outcomes = env_outcome.get("firm_outcomes", {}) or {}
        # Build a compact summary of the proposal for the verifier
        proposal_lines = [
            f"  total_demand: {env_outcome.get('total_demand', 0):,}",
        ]
        for fid in sorted(firm_outcomes.keys()):
            fo = firm_outcomes[fid]
            us = fo.get("units_sold", 0) if isinstance(fo, dict) else getattr(fo, "units_sold", 0)
            ms = fo.get("market_share", 0) if isinstance(fo, dict) else getattr(fo, "market_share", 0)
            cap = production_caps.get(fid, 0)
            proposal_lines.append(
                f"  {fid}: units_sold={us:,} (cap={cap:,}), share={ms:.1%}"
            )

        recent_str = (
            ", ".join(f"${r/1e6:.1f}M" for r in recent_quarter_revenues[-6:])
            if recent_quarter_revenues else "(no history)"
        )

        user = f"""=== ENV OUTPUT VERIFICATION — Q{macro.fqtr} {macro.fyear} ===

ANOMALY FLAGS RAISED:
{chr(10).join('  - ' + r for r in anomaly_reasons)}

ENV'S PROPOSED OUTPUT:
{chr(10).join(proposal_lines)}

RECENT INDUSTRY REVENUE (last 6 quarters):
{recent_str}

LOGIT BASELINE DEMAND THIS QUARTER: {baseline_demand:,} units

PRODUCTION CAPS:
{chr(10).join(f'  {fid}: {cap:,}' for fid, cap in sorted(production_caps.items()))}

Decide: ratify or revise."""

        try:
            result = backend.complete_json(VERIFIER_PROMPT, user)
        except Exception as e:
            # Fall back to a deterministic clamp if verifier fails: cap each
            # firm at production_cap, scale down proportionally to match
            # baseline_demand.
            return _deterministic_clamp(env_outcome, baseline_demand, production_caps,
                                          reason=f"verifier failed: {e}")
        if result is None:
            return _deterministic_clamp(env_outcome, baseline_demand, production_caps,
                                          reason="verifier returned None")

        verified = bool(result.get("verified", True))
        if verified:
            return env_outcome  # ratified, pass through

        # Revise. Build new firm_outcomes from the verifier's response.
        revised_total = int(result.get("revised_total_demand", baseline_demand))
        revised_firms_list = result.get("revised_firm_outcomes", []) or []
        revised_firm_outcomes = {}
        for fo in revised_firms_list:
            if not isinstance(fo, dict):
                continue
            fid = fo.get("firm_id", "")
            if fid:
                revised_firm_outcomes[fid] = {
                    "units_sold": int(fo.get("units_sold", 0)),
                    "market_share": float(fo.get("market_share", 0)),
                    # Preserve env's R&D / advance flags from the original
                    "product_advance": (firm_outcomes.get(fid, {}) or {}).get("product_advance", False)
                                        if isinstance(firm_outcomes.get(fid), dict)
                                        else getattr(firm_outcomes.get(fid, {}), "product_rd_advance", False),
                    "process_cogs_reduction_pct": (firm_outcomes.get(fid, {}) or {}).get("process_cogs_reduction_pct", 0)
                                                   if isinstance(firm_outcomes.get(fid), dict)
                                                   else getattr(firm_outcomes.get(fid, {}), "process_cogs_reduction_pct", 0),
                    "delivery_advance": (firm_outcomes.get(fid, {}) or {}).get("delivery_advance", False)
                                         if isinstance(firm_outcomes.get(fid), dict)
                                         else getattr(firm_outcomes.get(fid, {}), "delivery_rd_advance", False),
                }

        # Build revised env_outcome (preserve unchanged keys like narrative, events,
        # detection_tips, write_offs)
        out = dict(env_outcome)
        out["total_demand"] = revised_total
        out["firm_outcomes"] = revised_firm_outcomes
        out["narrative"] = (
            (env_outcome.get("narrative", "") or "")
            + f"\n\n[VERIFIER REVISED]: {result.get('reason', '')}"
        )
        return out

    return verify


def _deterministic_clamp(env_outcome: dict,
                           baseline_demand: int,
                           production_caps: dict[str, int],
                           reason: str = "") -> dict:
    """Last-resort fallback when verifier LLM unavailable. Cap each firm at
    production cap and scale total to baseline_demand."""
    out = dict(env_outcome)
    new_outcomes = {}
    firm_outcomes = env_outcome.get("firm_outcomes", {}) or {}
    total_capped = 0
    for fid, fo in firm_outcomes.items():
        if isinstance(fo, dict):
            us = fo.get("units_sold", 0)
            base = dict(fo)
        else:
            us = getattr(fo, "units_sold", 0)
            # Preserve R&D advance flags + process improvement when the
            # deterministic clamp kicks in. Wave ν+7: previously this
            # built a fresh dict with only units_sold/market_share, so
            # any product/process/delivery advance set by the env was
            # silently dropped on the rare quarters where the verifier
            # had to clamp. Note: dict shape uses the LLM-facing keys
            # (`product_advance`, `delivery_advance`) so the downstream
            # dict-to-MarketOutcome converter in orchestrator.py picks
            # them up correctly.
            base = {
                "product_advance": getattr(fo, "product_rd_advance", False),
                "process_cogs_reduction_pct": getattr(fo, "process_cogs_reduction_pct", 0.0),
                "delivery_advance": getattr(fo, "delivery_rd_advance", False),
            }
        cap = production_caps.get(fid, 0)
        capped = min(us, cap) if cap > 0 else us
        base["units_sold"] = capped
        base["market_share"] = 0.0  # recompute below
        new_outcomes[fid] = base
        total_capped += capped
    # Recompute shares
    for fid, fo in new_outcomes.items():
        fo["market_share"] = (fo["units_sold"] / total_capped) if total_capped > 0 else 0.0
    out["total_demand"] = total_capped
    out["firm_outcomes"] = new_outcomes
    out["narrative"] = (
        (env_outcome.get("narrative", "") or "")
        + f"\n\n[DETERMINISTIC CLAMP]: {reason}"
    )
    return out


# ── Wave ν+11 E9: independent env validator (second env) ─────────────────
#
# Distinct from the verifier above. The verifier above is triggered by
# deterministic anomaly heuristics and DIRECTLY rewrites env's numbers.
# The validator below is triggered EVERY quarter (no heuristic gate) and
# does NOT rewrite anything itself — instead it issues a verdict
# (ok | send_back) plus notes. The orchestrator then re-asks env-1 to
# regenerate its output with the notes appended.
#
# Design intent (per user spec for E9): "ask a second env to validate the
# env, and send it back if it does not work with notes (reasonably high
# bar since we do want randomness)". The bar is high — the validator only
# sends back when the proposal has clear inconsistencies (with the
# narrative, with capacity, with itself), not when numbers are merely
# unusual. Random shocks, catalyst events, and unusual moves are
# expressly fine.


ENV_VALIDATOR_SYSTEM_PROMPT = """You are an independent environment auditor for
a pharmaceutical industry simulation. Another environment agent has just
produced this quarter's market resolution (total demand, per-firm units sold,
per-firm market shares, R&D outcomes, narrative). Your job is to read the
proposal and judge whether it is internally consistent and consistent with
the recent industry trajectory.

You DO NOT rewrite the proposal. You either:
  - "ok": the proposal stands. Allow it through.
  - "send_back": the proposal has a clear flaw. Write notes describing what
    needs fixing, and the original env will regenerate.

KEY POINT — high bar for sending back. Random variation, surprising moves,
catalysts, and unusual quarters are FINE. The simulation's value depends
on emergent randomness; over-validation kills it. Only send back when:

  1. The narrative says one thing and the numbers say another
     (e.g. narrative claims "Firm A breakthrough drove growth" but
     Firm A's units_sold fell);
  2. Per-firm shares do not sum within a few percentage points of 100%;
  3. A firm's units_sold materially exceeds its production capacity;
  4. R&D outcomes contradict prior quarters with no narrative cause
     (e.g. firm advanced to Gen-2, but next quarter it's back at Gen-1);
  5. The total_demand changed by an order of magnitude vs trend with NO
     narrative explanation (a justified catalyst is fine; an unexplained
     spike is not).

Things that are NOT cause to send back:
  - Total demand moved 30-50% — markets move
  - One firm gained significant share — that's competition
  - Margins compressed or expanded — that's pricing
  - A new entrant disrupted incumbents — that happens
  - Numbers feel "high" or "low" subjectively
  - You'd have allocated differently — env-1 has authority

Output JSON:
```json
{
  "verdict": "ok" | "send_back",
  "notes": "<empty string if ok; 1-3 sentences describing the inconsistency if send_back>"
}
```

Output ONLY the JSON wrapped in ```json ... ```."""


def make_env_validator(backend: LLMBackend):
    """Factory: returns validator(env_outcome, recent_revs, baseline_demand,
    production_caps, macro) -> {"verdict": str, "notes": str}.

    Cheap LLM call (verdict + short notes only). Invoked unconditionally
    when env_validator_enabled is True.
    """

    def validate(env_outcome: dict,
                  recent_quarter_revenues: list[float],
                  baseline_demand: int,
                  production_caps: dict[str, int],
                  macro) -> dict:
        firm_outcomes = env_outcome.get("firm_outcomes", {}) or {}
        proposal_lines: list[str] = [
            f"  total_demand: {env_outcome.get('total_demand', 0):,}",
        ]
        share_sum = 0.0
        for fid in sorted(firm_outcomes.keys()):
            fo = firm_outcomes[fid]
            us = fo.get("units_sold", 0) if isinstance(fo, dict) else getattr(fo, "units_sold", 0)
            ms = fo.get("market_share", 0) if isinstance(fo, dict) else getattr(fo, "market_share", 0)
            cap = production_caps.get(fid, 0)
            pa = fo.get("product_advance", False) if isinstance(fo, dict) else getattr(fo, "product_rd_advance", False)
            da = fo.get("delivery_advance", False) if isinstance(fo, dict) else getattr(fo, "delivery_rd_advance", False)
            pcr = fo.get("process_cogs_reduction_pct", 0) if isinstance(fo, dict) else getattr(fo, "process_cogs_reduction_pct", 0)
            share_sum += float(ms or 0)
            rd_tag = []
            if pa:
                rd_tag.append("product+")
            if da:
                rd_tag.append("delivery+")
            if pcr:
                rd_tag.append(f"process-{float(pcr):.1%}")
            rd_str = (" rd=[" + ",".join(rd_tag) + "]") if rd_tag else ""
            proposal_lines.append(
                f"  {fid}: units_sold={us:,} (cap={cap:,}), share={ms:.1%}{rd_str}"
            )

        recent_str = (
            ", ".join(f"${r/1e6:.1f}M" for r in recent_quarter_revenues[-6:])
            if recent_quarter_revenues else "(no history)"
        )

        narrative = env_outcome.get("narrative", "") or "(none)"
        if len(narrative) > 1500:
            narrative = narrative[:1500] + "...[truncated]"

        user = f"""=== ENV VALIDATION — Q{macro.fqtr} {macro.fyear} ===

PROPOSED MARKET RESOLUTION:
{chr(10).join(proposal_lines)}
  share_sum: {share_sum:.1%}

RECENT INDUSTRY REVENUE (last 6 quarters):
{recent_str}

LOGIT BASELINE DEMAND THIS QUARTER: {baseline_demand:,} units

NARRATIVE FROM ENV-1:
{narrative}

Decide: ratify (verdict=ok) or send back with notes (verdict=send_back).
Remember the high bar: only send back for clear inconsistencies, not for
unusual moves."""

        try:
            result = backend.complete_json(ENV_VALIDATOR_SYSTEM_PROMPT, user)
        except Exception as e:
            return {"verdict": "ok", "notes": f"(validator error, defaulting to ok: {e})"}
        if result is None:
            return {"verdict": "ok", "notes": "(validator returned None, defaulting to ok)"}
        verdict = str(result.get("verdict", "ok")).strip().lower()
        if verdict not in {"ok", "send_back"}:
            verdict = "ok"
        notes = str(result.get("notes", ""))[:1000]
        return {"verdict": verdict, "notes": notes}

    return validate
