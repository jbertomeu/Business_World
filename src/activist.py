"""
Activist investor agent (Stage 12).

A single activist LLM that scans public market data each quarter for
underperforming firms and proposes a campaign demand: buyback, divestiture,
strategic review, or board seat. The firm's CEO sees the campaign on the
following quarter's decision prompt (via pending_env_notes) and responds
via a `firm_response` (accept/reject/negotiate) that the orchestrator
logs alongside a rationale.

INFORMATION BOUNDARY: activist sees ONLY public information — Compustat
rows, analyst notes, earnings releases. No private firm data, no world
secrets, no manipulation truth.

Output: appended to `state.activist_campaigns` (list of dicts) which
drives the `activist_campaigns.csv` WRDS-style dataset.
"""

from __future__ import annotations

from .types import MacroState
from .llm_backends import LLMBackend


ACTIVIST_PERSONALITY = {
    "id": "activist_1",
    "name": "Ironbridge Partners",
    "style": (
        "You are an activist investor fund. You take concentrated stakes "
        "in public companies where you believe shareholder value is being "
        "destroyed by weak capital allocation, bloated cost structure, or "
        "entrenched management. You issue public campaigns demanding "
        "specific actions: share buybacks when cash is idle, divestiture "
        "of non-core assets, a strategic review when strategy is drifting, "
        "or board representation when governance is broken."
    ),
}


def build_activist_prompt(
    public_compustat: list[dict],
    analyst_notes: list[dict],
    firm_ids: list[str],
    macro: MacroState,
    prior_campaigns: list[dict],
) -> tuple[str, str]:
    """Build (system, user) prompt. PUBLIC data only."""
    system = f"""You are {ACTIVIST_PERSONALITY['name']}, an activist investor fund.

{ACTIVIST_PERSONALITY['style']}

PROCESS:
1. Scan the public financials and analyst sentiment for firms that look like
   classic activist targets:
   - Cash-rich but slow-growing (buyback candidate)
   - Weak operating margins vs peers (cost-cutting candidate)
   - Sell-side ratings trending negative (strategic review)
   - Persistent price underperformance vs peers
2. You are not obligated to launch a campaign. If no firm is a strong target
   this quarter, output an empty list.
3. Pick at most ONE firm per quarter. Concentrated stakes require conviction.
4. Specify the demand clearly. Ground it in the numbers you see.

ESCALATION TO PROXY FIGHT (Wave ν+11):
Real activists do not just file campaigns and accept refusal. When a firm
has repeatedly ignored your prior campaigns (or a peer activist's campaigns
on the same firm) without engaging substantively on the underlying issue,
you have a credible escalation path: take a larger position and run a
proxy fight for board seats or a binding shareholder vote on your demand.
A proxy fight is costly — you commit more capital, your reputation is on
the line, and you cannot back out cheaply — but it converts a one-shot
demand letter into a binding governance event.

Use the `demand_type: "proxy_fight"` value when:
  - Prior campaigns from any activist on this firm have been ignored or
    addressed only with boilerplate language;
  - The underlying issue is material (cash hoarding well past plausible
    use, sustained operating under-performance, value-destroying capital
    allocation); and
  - You believe other public shareholders would support your slate or
    your demand if forced to vote.

A proxy fight is a serious commitment. Do not file proxy_fight casually —
real activists win some and lose some, and a lost proxy fight damages
your fund's reputation. But when the firm's behaviour merits escalation
and you have conviction, ESCALATE rather than file yet another routine
strategic_review demand.

Output JSON:
```json
{{
  "campaigns": [{{
    "firm_id": "firm_X",
    "demand_type": "buyback|divestiture|strategic_review|board_seat|proxy_fight",
    "demand_specifics": "<1-2 sentences stating the specific demand>",
    "stake_pct_implied": <decimal fraction>,
    "thesis": "<2-3 sentences on why this firm, grounded in the numbers>"
  }}]
}}
```

If no campaign is warranted this quarter, return {{"campaigns": []}}.
Output ONLY the JSON wrapped in ```json ... ```."""

    # Public data summary — last 4Q per firm
    comp_lines = []
    for row in public_compustat[-24:]:
        fid = row.get("firm_id", "?")
        rev = row.get("saleq", 0)
        ni = row.get("niq", 0)
        cash = row.get("cheq", 0)
        at = row.get("atq", 0)
        lt = row.get("ltq", 0)
        price = row.get("prccq", 0)
        comp_lines.append(
            f"  {fid}: Rev=${rev/1e6:.1f}M NI=${ni/1e6:.1f}M "
            f"Cash=${cash/1e6:.1f}M AT=${at/1e6:.1f}M LT=${lt/1e6:.1f}M "
            f"Price=${price:.2f}"
        )

    # Recent analyst views
    analyst_lines = []
    for n in analyst_notes[-12:]:
        aid = n.get("analyst_id", "?")
        fid = n.get("firm_id", "?")
        tp = n.get("target_price", 0)
        rating = n.get("rating", "?")
        analyst_lines.append(f"  {aid} on {fid}: TP=${tp:.2f} ({rating})")

    # Prior campaigns (activist has memory)
    prior_lines = []
    for c in prior_campaigns[-6:]:
        fid = c.get("firm_id", "?")
        dt = c.get("demand_type", "?")
        resp = c.get("firm_response", "pending")
        prior_lines.append(f"  Q{c.get('event_quarter','?')} {fid}: {dt} → {resp}")

    user = f"""PUBLIC FINANCIALS (Compustat, most recent quarters):
{chr(10).join(comp_lines) if comp_lines else '(No data yet)'}

SELL-SIDE ANALYST NOTES (recent):
{chr(10).join(analyst_lines) if analyst_lines else '(None)'}

YOUR PRIOR CAMPAIGNS:
{chr(10).join(prior_lines) if prior_lines else '(None yet)'}

MACRO: Risk-free {macro.risk_free_rate:.1%}/Q

Candidate firms this quarter: {', '.join(firm_ids)}
Decide: launch a campaign on one firm, or stand down."""

    return system, user


def parse_activist_campaigns(
    response: dict | None,
    quarter: int,
    run_id: str,
) -> list[dict]:
    """Parse LLM response into campaign event dicts (for state.activist_campaigns)."""
    if response is None:
        return []
    campaigns = response.get("campaigns", [])
    if not isinstance(campaigns, list):
        return []

    results = []
    for c in campaigns:
        try:
            stake = float(c.get("stake_pct_implied", 0.05))
        except (TypeError, ValueError):
            stake = 0.05
        demand_type = str(c.get("demand_type", "strategic_review")).strip().lower()
        if demand_type not in {"buyback", "divestiture", "strategic_review",
                                "board_seat", "proxy_fight"}:
            demand_type = "strategic_review"
        results.append({
            "run_id": run_id,
            "firm_id": c.get("firm_id", ""),
            "event_quarter": quarter,
            "activist_id": ACTIVIST_PERSONALITY["id"],
            "demand_type": demand_type,
            "demand_specifics": c.get("demand_specifics", ""),
            "stake_pct_implied": max(0.0, min(0.5, stake)),
            "thesis": c.get("thesis", ""),
            # Firm response fields — populated on the following quarter when the
            # firm's decision JSON includes an activist_response field, OR left
            # blank if the firm never addresses it.
            "firm_response": "",
            "firm_rationale": "",
        })
    return results


def build_activist_reaction_prompt(
    campaign: dict, firm_response: str, firm_rationale: str,
) -> tuple[str, str]:
    """Wave gamma round 2: activist reacts to firm's response.

    Activist decides one of:
      - `accept`: firm's response is enough; close campaign as won
      - `escalate`: firm stonewalled; go public/hostile (keep campaign open)
      - `drop`: not worth pressing further; close as lost
    """
    system = f"""You are {ACTIVIST_PERSONALITY['name']}, an activist investor fund.

Your original campaign on {campaign.get('firm_id','?')} demanded
{campaign.get('demand_type','')}: {campaign.get('demand_specifics','')}

The firm's board has responded. You must now decide your NEXT MOVE.

Options:
  - "accept": The firm's response satisfies you (full concession or adequate
    partial compliance). Close the campaign as a win.
  - "escalate": The firm resisted. Go public, write a hostile letter, push
    for a proxy fight, or expand the stake. Keep the campaign open.
  - "drop": The firm rejected, but the cost of further pressure outweighs
    the expected gain. Walk away — move on to a better target.

Think about:
  - Quality of the firm's rationale: is it substantive, or boilerplate?
  - Your reputation: dropping after rejection looks weak; escalating on
    a weak thesis looks foolish.
  - Opportunity cost: escalation ties up management attention and stake.

Output JSON:
```json
{{
  "next_action": "accept|escalate|drop",
  "rationale": "<1-2 sentences>"
}}
```

Output ONLY the JSON wrapped in ```json ... ```."""

    user = f"""FIRM RESPONSE: {firm_response}

FIRM RATIONALE: {firm_rationale or "(no rationale provided)"}

YOUR ORIGINAL THESIS: {campaign.get('thesis') or campaign.get('demand_specifics', '')}

Decide your next move."""

    return system, user


def parse_activist_reaction(response: dict | None) -> dict:
    """Parse LLM response into a structured reaction."""
    if response is None:
        return {"next_action": "drop", "rationale": "no LLM response"}
    action = str(response.get("next_action", "drop")).strip().lower()
    if action not in {"accept", "escalate", "drop"}:
        action = "drop"
    rationale = str(response.get("rationale", ""))[:500]
    return {"next_action": action, "rationale": rationale}


def make_activist_agent(backend: LLMBackend, state_ref: list):
    """Factory: create the activist agent callable with both round-0 and
    round-2 capability.

    Returns a callable that has a `round2(campaign, firm_response,
    firm_rationale)` method for post-response reaction.
    """

    def activist_fn(
        public_compustat: list[dict],
        analyst_notes: list[dict],
        firm_ids: list[str],
        macro: MacroState,
        prior_campaigns: list[dict],
    ) -> list[dict]:
        system, user = build_activist_prompt(
            public_compustat, analyst_notes, firm_ids, macro, prior_campaigns
        )
        result = backend.complete_json(system, user)
        world = state_ref[0] if state_ref else None
        run_id = getattr(world, "run_id", "") if world else ""
        return parse_activist_campaigns(result, macro.quarter, run_id)

    def round2(campaign: dict, firm_response: str, firm_rationale: str) -> dict:
        """Second-round LLM reaction to firm's response."""
        system, user = build_activist_reaction_prompt(
            campaign, firm_response, firm_rationale,
        )
        result = backend.complete_json(system, user)
        return parse_activist_reaction(result)

    activist_fn.round2 = round2  # attach for orchestrator
    return activist_fn
