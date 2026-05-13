"""
Test the environment market resolution prompt against any LLM backend.

Usage:
  python test_env_prompt.py --backend ollama --model llama3.2:3b
  python test_env_prompt.py --backend openrouter --model anthropic/claude-sonnet-4-20250514
  python test_env_prompt.py --backend mock
"""

import argparse
import json
import re
import sys
import time

# ── THE PROMPTS (verbatim from doc 18) ──────────────────────────────────

ENV_SYSTEM_PROMPT = """You are the market environment for a simulated pharmaceutical industry. Each
quarter, you observe the actions of 5 firms competing in the senolytic
regenerative therapy (SRT) market and determine what happens in the world:
total demand, market share allocation, R&D outcomes, and any special events.

Your job is to be a REALISTIC and CONSISTENT referee. You are not adversarial.
You do not favor any firm. You produce outcomes that are economically plausible
given the actions you see.

THE WORLD:
- 2031, single global market for SRT therapy
- ~600 million potential patients (adults 50+ in high-income countries)
- Awareness rate currently ~18% and growing
- Multinomial logit demand: patients choose based on price, quality, brand,
  with random taste shocks
- Quality has three dimensions: efficacy, safety (1 - serious AE rate),
  convenience (delivery method)
- Price elasticities range from -0.3 (ultra-wealthy) to -4.0 (mass market)

WHAT YOU DECIDE each quarter:
1. TOTAL DEMAND: how many treatment courses sell across the whole industry
2. MARKET SHARES: how that demand is allocated across the 5 firms
3. R&D OUTCOMES: did any firm achieve a generation advance? Process improvements?
4. EVENTS: did anything special happen? (safety scandal, breakthrough,
   regulatory action, supply disruption, macro shock)
5. NARRATIVE: a 2-3 paragraph industry summary for the quarter (the gazette)

CONSTRAINTS:
- Total demand must be in range [0.5x, 2.0x] of the deterministic baseline
  the orchestrator computes from a multinomial logit model. You receive this
  baseline as input. Stay close to it unless you have a reason to deviate.
- Market shares must sum to 1.0
- No firm can have > 60% share
- Units sold for each firm cannot exceed that firm's production
- R&D advances require crossing the cumulative threshold ($400M+ for Gen 2)
  -- you cannot grant a Gen 2 to a firm with $50M cumulative R&D
- Events should be RARE: typically 0-1 per quarter, not every quarter
- Narrative must be consistent with the numerical outcomes

OUTPUT FORMAT:
A single JSON object wrapped in triple backticks."""

ENV_USER_PROMPT = """=== QUARTER: Q2 2031 ===

MACRO STATE
  Risk-free rate: 4.0% annual
  Awareness rate: 18%
  Market growth trend: emerging, growing
  Macro shock this quarter: +0.03 (mildly positive)

DETERMINISTIC DEMAND BASELINE (computed from multinomial logit)
  Total expected units: 920
  Reference allocation:
    firm_0 (Aeterna):   200 units (21.7%)
    firm_1 (GenVita):   227 units (24.7%)
    firm_2 (NovaLife):  152 units (16.5%)
    firm_3 (BioAge):    179 units (19.5%)
    firm_4 (Senova):    162 units (17.6%)

FIRM ACTIONS THIS QUARTER

firm_0 (Aeterna Therapeutics)
  Price: $92,000 (was $95,000 last Q -- a 3.2% cut)
  Production: 220 (capacity 250, 88% utilization)
  R&D spend: $28M (was $25M)  [60% product, 25% process, 15% delivery]
  SGA spend: $14M (was $12M)
  Capex: $15M (was $0)
  Quality composite: 47.2/100 (Gen 1)
  Brand: 24.8/100
  Cumulative product R&D: $20.8M (4% of Gen 2 threshold)
  Serious AE rate: 7.1%

firm_1 (GenVita Sciences)
  Price: $85,000 (was $88,000 -- aggressive pricing)
  Production: 250 (at capacity -- CANNOT SELL MORE THAN 250)
  R&D spend: $20M  [40% product, 50% process, 10% delivery]
  SGA spend: $18M
  Capex: $40M (building new facility)
  Quality composite: 44.5
  Brand: 28.0
  Cumulative product R&D: $14M
  Serious AE rate: 7.3%

firm_2 (NovaLife Therapeutics)
  Price: $115,000 (premium positioning increased)
  Production: 180
  R&D spend: $35M  [70% product, 15% process, 15% delivery]
  SGA spend: $10M
  Capex: $0
  Quality composite: 49.0 (slightly above Gen 1 baseline)
  Brand: 22.0
  Cumulative product R&D: $26M
  Serious AE rate: 6.8%

firm_3 (BioAge Pharma)
  Price: $95,000 (unchanged)
  Production: 200
  R&D spend: $30M  [50% product, 30% process, 20% delivery]
  SGA spend: $15M
  Capex: $20M
  Quality composite: 46.5
  Brand: 25.5
  Cumulative product R&D: $20M
  Serious AE rate: 7.2%

firm_4 (Senova Bio)
  Price: $99,000 (unchanged)
  Production: 210
  R&D spend: $25M  [55% product, 30% process, 15% delivery]
  SGA spend: $13M
  Capex: $10M
  Quality composite: 45.8
  Brand: 24.0
  Cumulative product R&D: $17M
  Serious AE rate: 7.0%

LAST QUARTER GAZETTE (for continuity)
  "Q1 2031: First commercial quarter for SRT. 920 patients treated industry-wide.
  Total revenue $93M. Patient satisfaction 7.5/10. No safety incidents. GenVita's
  aggressive pricing captured the largest share. NovaLife premium-priced at $110K.
  Physicians cautious due to 7% serious AE rate."

ACTIVE EVENTS: none

NOW DETERMINE OUTCOMES:

1. TOTAL DEMAND: How many courses sell this quarter? Consider:
   - Baseline is 920. The market is growing (~12% QoQ).
   - GenVita cut price further; this should expand demand somewhat.
   - No safety events; no demand crash.
   - Reasonable range: 950-1050 units.

2. MARKET SHARES: Allocate the total. Consider:
   - GenVita's price cut should boost their share.
   - NovaLife's premium pricing limits volume.
   - Aeterna's small price cut is modest; minor share gain.
   - All firms within 15-30% range; no monopoly.

3. R&D OUTCOMES: Process R&D may yield small COGS reductions for firms
   that invested in it. No firm is close to Gen 2 threshold. No advances.

4. EVENTS: Rare. Consider whether to introduce one (e.g., academic publication,
   minor supply hiccup, modest macro shock). Most quarters have NO events.

5. NARRATIVE: 2-3 paragraphs describing what happened, mentioning specific firms
   and dynamics. Continue the story from Q1.

OUTPUT FORMAT:

```json
{
  "total_demand": <integer>,
  "demand_rationale": "<1 sentence>",
  "firm_outcomes": [
    {"firm_id": "firm_0", "units_sold": <int>, "market_share": <0-1>},
    {"firm_id": "firm_1", "units_sold": <int>, "market_share": <0-1>},
    {"firm_id": "firm_2", "units_sold": <int>, "market_share": <0-1>},
    {"firm_id": "firm_3", "units_sold": <int>, "market_share": <0-1>},
    {"firm_id": "firm_4", "units_sold": <int>, "market_share": <0-1>}
  ],
  "rd_outcomes": [
    {
      "firm_id": "firm_0",
      "product_advance": false,
      "process_cogs_reduction_pct": <0.0-0.05>,
      "delivery_advance": false
    },
    ... (one per firm)
  ],
  "events": [
    {
      "type": "<none|academic_publication|supply_disruption|safety_event|regulatory_action|macro_shock>",
      "description": "<1 sentence>",
      "affected_firms": ["firm_X", ...],
      "duration_quarters": <int>,
      "demand_impact": <-0.5 to 0.5>
    }
  ],
  "narrative": "<2-3 paragraph industry summary>"
}
```

CRITICAL -- CHECK THESE BEFORE OUTPUTTING:
- units_sold must sum EXACTLY to total_demand
- market_share must sum to ~1.0
- *** units_sold for each firm MUST NOT EXCEED their production ***
  Max allowed: firm_0=220, firm_1=250, firm_2=180, firm_3=200, firm_4=210
  If a firm deserves more share than its production allows, cap at production
  and redistribute the excess to other firms.
- rd_outcomes: process_cogs_reduction_pct should be small (0-2%) per quarter
- Empty events array is fine and is the most common case"""


# ── VALIDATION ──────────────────────────────────────────────────────────

FIRM_PRODUCTIONS = {
    "firm_0": 220, "firm_1": 250, "firm_2": 180,
    "firm_3": 200, "firm_4": 210,
}
BASELINE_DEMAND = 920
FIRM_CUMULATIVE_RD = {
    "firm_0": 20_800_000, "firm_1": 14_000_000, "firm_2": 26_000_000,
    "firm_3": 20_000_000, "firm_4": 17_000_000,
}
GEN2_THRESHOLD = 400_000_000


def extract_json(text: str) -> dict | None:
    """Extract the first JSON object from a response."""
    m = re.search(r'```json\s*(.*?)\s*```', text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    depth = 0
    start = None
    for i, c in enumerate(text):
        if c == '{':
            if depth == 0:
                start = i
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0 and start is not None:
                try:
                    return json.loads(text[start:i+1])
                except json.JSONDecodeError:
                    start = None
    return None


def validate_env_response(outcome: dict) -> list[str]:
    """Validate environment outcome. Returns list of issues."""
    issues = []

    # Required top-level fields
    for f in ["total_demand", "firm_outcomes", "rd_outcomes", "narrative"]:
        if f not in outcome:
            issues.append(f"MISSING FIELD: {f}")
    if issues:
        return issues

    td = outcome["total_demand"]

    # Total demand range
    if not isinstance(td, (int, float)):
        issues.append(f"total_demand not numeric: {type(td)}")
        return issues

    low, high = int(BASELINE_DEMAND * 0.3), int(BASELINE_DEMAND * 3.0)
    if td < low or td > high:
        issues.append(f"total_demand={td} out of range [{low}, {high}]")

    reasonable_low, reasonable_high = 800, 1200
    if td < reasonable_low or td > reasonable_high:
        issues.append(f"WARNING: total_demand={td} outside reasonable range [{reasonable_low}, {reasonable_high}]")

    # Firm outcomes
    fo = outcome.get("firm_outcomes", [])
    if len(fo) != 5:
        issues.append(f"Expected 5 firm outcomes, got {len(fo)}")
        return issues

    units_sum = 0
    share_sum = 0
    for firm_out in fo:
        fid = firm_out.get("firm_id", "?")
        us = firm_out.get("units_sold", 0)
        ms = firm_out.get("market_share", 0)

        # Production cap
        max_prod = FIRM_PRODUCTIONS.get(fid, 999999)
        if us > max_prod:
            issues.append(f"{fid}: units_sold={us} > production={max_prod}")

        # Non-negative
        if us < 0:
            issues.append(f"{fid}: negative units_sold={us}")

        # Market share bounds
        if ms > 0.60:
            issues.append(f"{fid}: market_share={ms:.2f} > 0.60 cap")
        if ms < 0:
            issues.append(f"{fid}: negative market_share={ms:.2f}")

        units_sum += us
        share_sum += ms

    # Sum checks
    if abs(units_sum - td) > 2:
        issues.append(f"units_sold sum={units_sum} != total_demand={td}")
    if abs(share_sum - 1.0) > 0.02:
        issues.append(f"market_share sum={share_sum:.3f} != 1.0")

    # R&D outcomes
    rd = outcome.get("rd_outcomes", [])
    for r in rd:
        fid = r.get("firm_id", "?")
        if r.get("product_advance", False):
            cum = FIRM_CUMULATIVE_RD.get(fid, 0)
            if cum < GEN2_THRESHOLD:
                issues.append(f"{fid}: product_advance=true but cumulative R&D "
                              f"${cum:,.0f} < threshold ${GEN2_THRESHOLD:,.0f}")

        pct = r.get("process_cogs_reduction_pct", 0)
        if isinstance(pct, (int, float)) and (pct < 0 or pct > 0.05):
            issues.append(f"WARNING: {fid} process_cogs_reduction_pct={pct:.3f} outside [0, 0.05]")

    # Events
    events = outcome.get("events", [])
    if len(events) > 2:
        issues.append(f"WARNING: {len(events)} events this quarter (expected 0-1)")

    # Narrative
    narr = outcome.get("narrative", "")
    if len(narr) < 50:
        issues.append(f"WARNING: narrative too short ({len(narr)} chars)")

    return issues


def grade_response(outcome: dict) -> str:
    issues = validate_env_response(outcome)
    critical = [i for i in issues if not i.startswith("WARNING")]
    warnings = [i for i in issues if i.startswith("WARNING")]
    if critical:
        return "F"
    elif warnings:
        return "B"
    else:
        return "A"


# ── LLM BACKENDS ────────────────────────────────────────────────────────

def call_ollama(model, system, user):
    import requests
    resp = requests.post("http://localhost:11434/api/chat", json={
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "options": {"temperature": 0.2},  # slight temp for environment creativity
    }, timeout=300)
    resp.raise_for_status()
    return resp.json()["message"]["content"]


def call_openrouter(model, system, user):
    import os, requests
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise ValueError("Set OPENROUTER_API_KEY environment variable")
    resp = requests.post("https://openrouter.ai/api/v1/chat/completions", json={
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.2,
    }, headers={"Authorization": f"Bearer {api_key}"}, timeout=300)
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def call_mock(model, system, user):
    return '''```json
{
  "total_demand": 1010,
  "demand_rationale": "Moderate growth driven by increasing awareness and GenVita's price cut expanding addressable market.",
  "firm_outcomes": [
    {"firm_id": "firm_0", "units_sold": 215, "market_share": 0.213},
    {"firm_id": "firm_1", "units_sold": 250, "market_share": 0.248},
    {"firm_id": "firm_2", "units_sold": 145, "market_share": 0.144},
    {"firm_id": "firm_3", "units_sold": 200, "market_share": 0.198},
    {"firm_id": "firm_4", "units_sold": 199, "market_share": 0.197}
  ],
  "rd_outcomes": [
    {"firm_id": "firm_0", "product_advance": false, "process_cogs_reduction_pct": 0.005, "delivery_advance": false},
    {"firm_id": "firm_1", "product_advance": false, "process_cogs_reduction_pct": 0.008, "delivery_advance": false},
    {"firm_id": "firm_2", "product_advance": false, "process_cogs_reduction_pct": 0.002, "delivery_advance": false},
    {"firm_id": "firm_3", "product_advance": false, "process_cogs_reduction_pct": 0.006, "delivery_advance": false},
    {"firm_id": "firm_4", "product_advance": false, "process_cogs_reduction_pct": 0.004, "delivery_advance": false}
  ],
  "events": [],
  "narrative": "Q2 2031 saw continued growth in the SRT market, with total treatments rising 10% to 1,010 courses. GenVita Sciences consolidated its market leadership by cutting prices to $85,000, capturing over 26% of the market and running at full capacity. The aggressive pricing strategy is clearly attracting price-sensitive patients and physician referrals, though analysts note GenVita's thin margins may not be sustainable.\\n\\nAeterna Therapeutics responded with a modest price reduction to $92,000 while significantly increasing both R&D ($28M) and marketing ($14M) investment. The science-first strategy appears to be positioning Aeterna for long-term competitiveness, though near-term revenue growth remains modest. NovaLife maintained its ultra-premium positioning at $115,000, resulting in the smallest patient base but the highest revenue per patient. The industry continues to operate without safety incidents, maintaining cautious optimism among physicians and patients."
}
```'''


# ── MAIN ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Test environment resolution prompt")
    parser.add_argument("--backend", choices=["ollama", "openrouter", "mock"],
                        default="mock")
    parser.add_argument("--model", default="deepseek/deepseek-v3.2")
    parser.add_argument("--runs", type=int, default=1)
    args = parser.parse_args()

    backends = {"ollama": call_ollama, "openrouter": call_openrouter, "mock": call_mock}
    call_fn = backends[args.backend]

    print(f"Testing environment prompt with {args.backend} / {args.model}")
    print(f"Running {args.runs} iteration(s)...\n")

    results = []
    for i in range(args.runs):
        print(f"--- Run {i+1}/{args.runs} ---")
        t0 = time.time()
        try:
            response = call_fn(args.model, ENV_SYSTEM_PROMPT, ENV_USER_PROMPT)
        except Exception as e:
            print(f"  ERROR: {e}")
            results.append({"run": i+1, "grade": "F", "error": str(e)})
            continue
        elapsed = time.time() - t0

        outcome = extract_json(response)
        if outcome is None:
            print(f"  FAIL: Could not extract JSON ({len(response)} chars)")
            print(f"  First 300 chars: {response[:300]}")
            results.append({"run": i+1, "grade": "F", "error": "no JSON found"})
            continue

        issues = validate_env_response(outcome)
        grade = grade_response(outcome)

        print(f"  Time: {elapsed:.1f}s")
        print(f"  Grade: {grade}")
        print(f"  Total demand: {outcome.get('total_demand', '?')}")

        fo = outcome.get("firm_outcomes", [])
        for f in fo:
            fid = f.get("firm_id", "?")
            us = f.get("units_sold", "?")
            ms = f.get("market_share", "?")
            print(f"    {fid}: {us} units ({ms:.1%})" if isinstance(ms, float) else f"    {fid}: {us} units")

        events = outcome.get("events", [])
        print(f"  Events: {len(events)}" + (f" -- {events[0].get('type','?')}" if events else ""))

        narr = outcome.get("narrative", "")
        print(f"  Narrative: {len(narr)} chars")

        if issues:
            for issue in issues:
                print(f"  ISSUE: {issue}")

        results.append({
            "run": i+1, "grade": grade, "outcome": outcome,
            "issues": issues, "elapsed": elapsed,
        })
        print()

    grades = [r["grade"] for r in results]
    print(f"\n=== SUMMARY ===")
    print(f"Runs: {len(results)}")
    print(f"Grades: {' '.join(grades)}")
    print(f"Pass rate (A or B): {sum(1 for g in grades if g in ('A','B'))}/{len(grades)}")
    if any(r.get("elapsed") for r in results):
        avg_time = sum(r.get("elapsed", 0) for r in results) / len(results)
        print(f"Avg time: {avg_time:.1f}s")


if __name__ == "__main__":
    main()
