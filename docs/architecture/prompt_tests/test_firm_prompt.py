"""
Test the firm quarterly decision prompt against any LLM backend.

Usage:
  python test_firm_prompt.py --backend ollama --model llama3.2:3b
  python test_firm_prompt.py --backend openrouter --model anthropic/claude-sonnet-4-20250514
  python test_firm_prompt.py --backend mock  (uses built-in evaluation)

The script sends the exact prompt from doc 18 and validates the response.
"""

import argparse
import json
import re
import sys
import time

# ── THE PROMPTS (verbatim from doc 18) ──────────────────────────────────

FIRM_SYSTEM_PROMPT = """You are the management team of Aeterna Therapeutics, a biopharmaceutical
company commercializing senolytic regenerative therapy (SRT) -- a treatment
that reverses biological aging. You operate in a near-future setting (2031+)
where SRT is a brand-new therapeutic class with conditional FDA approval.

YOUR IDENTITY:
- Style: growth-focused, science-first
- Risk appetite: high (0.72/1.0)
- Time horizon: long (10+ years)
- Innovation priority: efficacy over cost
- Financing preference: equity over debt

YOUR PRODUCT (Generation 1):
- Revitagen: IV infusion, quarterly dosing, clinic-administered
- Efficacy: ~6-8 years of epigenetic age reversal
- Serious adverse event rate: ~7% (the industry baseline for Gen 1)
- Includes a small (~0.4%) risk of transient paralysis -- the most feared side effect
- Manufacturing cost: ~$14,000-$15,000 per annual treatment course
- Initial capacity: 250 courses per quarter (pilot plant)

THE INDUSTRY:
- Five firms compete in a global market for SRT therapy
- Initial addressable market: ~600 million people aged 50+, but the willing-and-able
  buyers at premium prices number in the tens of thousands
- Technology will advance through generations: Gen 2 (better), Gen 3 (oral), Gen 4 (one-time)
- Each generation requires R&D investment beyond a threshold (~$400-600M for Gen 2)
- The race to Gen 2/3 is the central long-term competition

YOUR DECISIONS each quarter:
- price: annual treatment course price ($USD)
- production: number of courses to manufacture (cannot exceed capacity)
- capex: investment in new manufacturing capacity ($USD)
- rd_spend: total R&D spending ($USD; minimum $10M for mandatory Phase III trial)
- rd_allocation: how to split R&D across {product, process, delivery}
- sga_spend: sales, marketing, administrative spending ($USD)
- equity_issuance_request: amount to raise via secondary offering (0 if none)
- debt_request: amount to request as term debt (0 if none)
- dividends: cash to return to shareholders (typically 0 in early years)
- buybacks: share repurchases (typically 0 in early years)

REASONING PROCESS:
You will be given financial statistics, competitor information, and market context.
Your job is to think step by step:
1. What is your current situation? (cash, market share, R&D progress)
2. What are the key dynamics and risks?
3. What are 2-3 strategic options worth considering?
4. Which option do you choose, and what specific numbers?

OUTPUT FORMAT:
You must output a single JSON object with all decision fields. Wrap it in
triple backticks: ```json ... ```

CRITICAL CONSTRAINTS:
- Total spending (cogs + R&D + SGA + capex + dividends + buybacks) must not
  exceed your cash + expected revenue + available credit
- Production cannot exceed capacity
- Dividends require positive retained earnings
- R&D below $10M will be raised to $10M (Phase III is mandatory)
- All values are quarterly unless stated otherwise"""

FIRM_USER_PROMPT = """=== QUARTER: Q2 2031 ===

YOUR FINANCIAL POSITION (private)
  Cash: $303,655,570
  Accounts receivable: $2,565,000
  Inventory: 20 courses ($298,200)
  PP&E (net): $24,375,000
  Total assets: $330,893,770

  Accounts payable: $402,570
  Accrued expenses: $3,700,000
  Total liabilities: $4,102,570

  Common stock + APIC: $350,000,000
  Retained earnings: -$23,208,800 (Q1 net loss)
  Total equity: $326,791,200

  Available revolver: $0 (no facility yet)

INTERNAL OPERATIONS (private)
  Capability stock (R&D quality index): 40.0 / 100
  Brand stock: 11.25 / 100
  Manufacturing capacity: 250 courses/quarter
  Effective unit cost: $14,910 (last quarter's actual)
  Product generation: 1
  Cumulative product R&D: $10,000,000 (toward Gen 2 threshold of ~$500M)
  Cumulative process R&D: $3,750,000
  Cumulative delivery R&D: $2,250,000
  NOL carryforward: $23,208,800

LAST QUARTER (Q1 2031) RESULTS
  Revenue: $17,100,000 (180 courses sold at $95,000)
  COGS: $2,683,800
  Net income: -$23,208,800
  Cash flow from ops: -$28,500,000
  Market share: 19% (vs. 5 firms total)

PUBLIC INFO ON COMPETITORS (last quarter)
  GenVita Sciences:    Price $88,000  Share 24.7%  Revenue $21.0M  Equity $325M
  NovaLife Therapeutics: Price $110,000 Share 16.5% Revenue $18.0M Equity $310M
  BioAge Pharma:        Price $95,000  Share 19.5%  Revenue $17.5M  Equity $330M
  Senova Bio:           Price $99,000  Share 20.3%  Revenue $19.8M  Equity $320M
  (Yours):              Price $95,000  Share 19.0%  Revenue $17.1M  Equity $327M

MACRO STATE
  Risk-free rate: 4.0% annual
  Market growth: emerging, +12% addressable patients QoQ
  Active events: none

INDUSTRY GAZETTE (Q1 2031)
  "The first commercial quarter for SRT therapy saw 920 patients treated
  across the five active firms. Total industry revenue of $93M was driven
  primarily by ultra-high-net-worth patients in North America. GenVita's
  aggressive pricing captured the largest share, while NovaLife's premium
  positioning attracted the wealthiest segment. Patient satisfaction is
  high (mean 7.5/10) but physicians remain cautious about referring patients
  given the 7% serious adverse event rate. No safety incidents this quarter."

YOUR LAST DECISION AND REASONING
  Q1: price=$95,000, production=200, capex=$0, rd_spend=$25M
      (60% product, 25% process, 15% delivery), sga=$12M
  Reasoning: "Premium pricing to capture wealthy early adopters. Heavy R&D
  toward Gen 2. Moderate marketing to build physician relationships."

ANALYTICAL CONTEXT (computed from your data)
  - Cash runway at current burn: 11 quarters
  - Gross margin: 84.3%  (industry leading)
  - Capacity utilization: 80%
  - R&D as % of revenue: 146%
  - Days sales outstanding: 13.7
  - Gen 2 progress: 2% of threshold (need ~$490M more product R&D)

NOW THINK STEP BY STEP:

1. SITUATION: Where do you stand? What is working? What is concerning?

2. KEY QUESTIONS for this quarter: Should you cut price to gain share?
   Increase R&D to accelerate Gen 2? Build capacity ahead of demand? Raise capital?

3. STRATEGIC OPTIONS: List 2-3 distinct paths forward with their tradeoffs.

4. DECISION: Pick your path. Write the JSON.

Remember: total spending must be feasible. You have $303.7M cash, expect to
collect ~$2.6M from prior AR, and have no revolver. Conservative estimate of
maximum total quarterly outlay: $290M (preserving some buffer).

OUTPUT YOUR DECISION AS JSON:

```json
{
  "price": <number>,
  "production": <integer>,
  "capex": <number>,
  "rd_spend": <number>,
  "rd_allocation": {"product": <0-1>, "process": <0-1>, "delivery": <0-1>},
  "sga_spend": <number>,
  "equity_issuance_request": <number>,
  "debt_request": <number>,
  "dividends": <number>,
  "buybacks": <number>,
  "reasoning": "<2-3 sentence explanation>"
}
```"""


# ── VALIDATION ──────────────────────────────────────────────────────────

def extract_json(text: str) -> dict | None:
    """Extract the first JSON object from a response."""
    # Try to find ```json ... ``` block
    m = re.search(r'```json\s*(.*?)\s*```', text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass

    # Try to find first { ... } block
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


def validate_firm_response(decision: dict) -> list[str]:
    """Validate a firm decision. Returns list of issues (empty = pass)."""
    issues = []

    REQUIRED_FIELDS = [
        "price", "production", "capex", "rd_spend", "rd_allocation",
        "sga_spend", "equity_issuance_request", "debt_request",
        "dividends", "buybacks", "reasoning"
    ]

    # Check required fields
    for f in REQUIRED_FIELDS:
        if f not in decision:
            issues.append(f"MISSING FIELD: {f}")

    if issues:
        return issues  # can't validate values if fields missing

    # Type checks
    if not isinstance(decision["price"], (int, float)):
        issues.append(f"price is not numeric: {type(decision['price'])}")
    if not isinstance(decision["production"], (int, float)):
        issues.append(f"production is not numeric: {type(decision['production'])}")

    # Range checks
    p = decision["price"]
    if p < 0:
        issues.append(f"price is negative: {p}")
    elif p < 10000:
        issues.append(f"WARNING: price very low: ${p:,.0f}")
    elif p > 500000:
        issues.append(f"WARNING: price very high: ${p:,.0f}")

    prod = int(decision["production"])
    if prod < 0:
        issues.append(f"production is negative: {prod}")
    elif prod > 250:
        issues.append(f"production exceeds capacity (250): {prod}")

    for field in ["capex", "rd_spend", "sga_spend", "equity_issuance_request",
                   "debt_request", "dividends", "buybacks"]:
        v = decision.get(field, 0)
        if isinstance(v, (int, float)) and v < 0:
            issues.append(f"{field} is negative: {v}")

    # R&D minimum
    rd = decision.get("rd_spend", 0)
    if isinstance(rd, (int, float)) and rd < 10_000_000:
        issues.append(f"rd_spend below mandatory $10M: ${rd:,.0f}")

    # R&D allocation
    alloc = decision.get("rd_allocation", {})
    if isinstance(alloc, dict):
        alloc_sum = sum(alloc.values())
        if abs(alloc_sum - 1.0) > 0.05:
            issues.append(f"rd_allocation sums to {alloc_sum:.2f}, not 1.0")

    # Dividends check (RE is negative)
    div = decision.get("dividends", 0)
    if isinstance(div, (int, float)) and div > 0:
        issues.append(f"dividends={div:,.0f} but retained earnings are NEGATIVE")

    # Budget feasibility
    total_spend = sum(
        decision.get(f, 0) or 0
        for f in ["capex", "rd_spend", "sga_spend", "dividends", "buybacks"]
    )
    cogs_estimate = prod * 14910  # approximate unit cost
    total_outflow = total_spend + cogs_estimate
    available = 303_655_570 + 2_565_000  # cash + AR collection
    if total_outflow > available:
        issues.append(f"BUDGET VIOLATION: total outflow ${total_outflow:,.0f} > available ${available:,.0f}")

    return issues


def grade_response(decision: dict) -> str:
    """Return A/B/C/F grade for the response quality."""
    issues = validate_firm_response(decision)
    critical = [i for i in issues if not i.startswith("WARNING")]
    warnings = [i for i in issues if i.startswith("WARNING")]

    if critical:
        return "F"
    elif warnings:
        return "B"
    elif decision.get("reasoning") and len(decision["reasoning"]) > 20:
        return "A"
    else:
        return "B"


# ── LLM BACKENDS ────────────────────────────────────────────────────────

def call_ollama(model: str, system: str, user: str) -> str:
    import requests
    resp = requests.post("http://localhost:11434/api/chat", json={
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "options": {"temperature": 0},
    }, timeout=300)
    resp.raise_for_status()
    return resp.json()["message"]["content"]


def call_openrouter(model: str, system: str, user: str) -> str:
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
        "temperature": 0,
    }, headers={"Authorization": f"Bearer {api_key}"}, timeout=300)
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def call_mock(model: str, system: str, user: str) -> str:
    """Return a hardcoded valid response for testing the validation logic."""
    return '''Let me think through this step by step.

1. SITUATION: We have strong cash ($304M, 11Q runway) but are burning fast
   (-$28M/Q). Market share is middle-of-pack at 19%. R&D progress toward
   Gen 2 is at 2% -- we need to accelerate dramatically.

2. KEY QUESTIONS: We should increase R&D but not at the expense of market
   position. Capacity expansion is premature (we're at 80% and demand is
   only 180/250). No need for external capital yet.

3. OPTIONS:
   A) Hold price, boost R&D to $35M, modest SGA increase
   B) Cut price to $90K to gain share, maintain R&D at $25M
   C) Keep price, start capacity build ($30M capex), steady R&D

```json
{
  "price": 92000,
  "production": 220,
  "capex": 15000000,
  "rd_spend": 30000000,
  "rd_allocation": {"product": 0.60, "process": 0.25, "delivery": 0.15},
  "sga_spend": 14000000,
  "equity_issuance_request": 0,
  "debt_request": 0,
  "dividends": 0,
  "buybacks": 0,
  "reasoning": "Slight price cut to gain share while increasing R&D spend toward Gen 2. Starting capacity expansion with modest capex. No financing needed yet with 10+ quarters of runway."
}
```'''


# ── MAIN ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Test firm decision prompt")
    parser.add_argument("--backend", choices=["ollama", "openrouter", "mock"],
                        default="mock")
    parser.add_argument("--model", default="deepseek/deepseek-v3.2")
    parser.add_argument("--runs", type=int, default=1)
    args = parser.parse_args()

    backends = {
        "ollama": call_ollama,
        "openrouter": call_openrouter,
        "mock": call_mock,
    }
    call_fn = backends[args.backend]

    print(f"Testing firm prompt with {args.backend} / {args.model}")
    print(f"Running {args.runs} iteration(s)...\n")

    results = []
    for i in range(args.runs):
        print(f"--- Run {i+1}/{args.runs} ---")
        t0 = time.time()
        try:
            response = call_fn(args.model, FIRM_SYSTEM_PROMPT, FIRM_USER_PROMPT)
        except Exception as e:
            print(f"  ERROR: {e}")
            results.append({"run": i+1, "grade": "F", "error": str(e)})
            continue
        elapsed = time.time() - t0

        decision = extract_json(response)
        if decision is None:
            print(f"  FAIL: Could not extract JSON from response ({len(response)} chars)")
            print(f"  First 200 chars: {response[:200]}")
            results.append({"run": i+1, "grade": "F", "error": "no JSON found"})
            continue

        issues = validate_firm_response(decision)
        grade = grade_response(decision)

        print(f"  Time: {elapsed:.1f}s")
        print(f"  Grade: {grade}")
        print(f"  Price: ${decision.get('price', '?'):,}")
        print(f"  Production: {decision.get('production', '?')}")
        print(f"  R&D: ${decision.get('rd_spend', '?'):,}")
        print(f"  Capex: ${decision.get('capex', '?'):,}")
        print(f"  SGA: ${decision.get('sga_spend', '?'):,}")
        if issues:
            for issue in issues:
                print(f"  ISSUE: {issue}")
        if decision.get("reasoning"):
            print(f"  Reasoning: {decision['reasoning'][:120]}...")

        results.append({
            "run": i+1, "grade": grade, "decision": decision,
            "issues": issues, "elapsed": elapsed,
        })
        print()

    # Summary
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
