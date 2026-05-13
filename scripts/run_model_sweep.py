"""
Model Sweep: systematically evaluate 20+ LLM models for quality vs price.

Tests each model on three tasks critical to the simulation:
1. FIRM DECISIONS: Can it produce valid JSON with reasonable business decisions?
2. ENVIRONMENT: Can it generate realistic market outcomes?
3. FINANCIAL: Can it do equity pricing and credit assessment?

Produces a quality/price frontier to identify the best models.

Usage:
  # Set your API key first
  set OPENROUTER_API_KEY=sk-or-...
  python run_model_sweep.py
"""

import csv
import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.llm_backends import OpenRouterBackend, extract_json
from src.config import LLMConfig

API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
if not API_KEY:
    print("Set OPENROUTER_API_KEY environment variable")
    sys.exit(1)


# ── Models to evaluate ──────────────────────────────────────────────────
# Organized by tier. Excludes OpenAI/Anthropic (too expensive).
# Keeps DeepSeek R1 and MiniMax as requested.

SWEEP_MODELS = [
    # ── MUST KEEP (user requirement) ──
    {"id": "deepseek/deepseek-r1-0528",        "input_per_m": 0.50,  "output_per_m": 2.15, "note": "DeepSeek R1 reasoning (KEEP)"},
    {"id": "minimax/minimax-m2.5",              "input_per_m": 0.118, "output_per_m": 0.99, "note": "MiniMax M2.5 (KEEP)"},

    # ── CURRENT ROSTER ──
    {"id": "deepseek/deepseek-v3.2",            "input_per_m": 0.26,  "output_per_m": 0.38, "note": "Current default, proven best"},
    {"id": "qwen/qwen3-235b-a22b-2507",         "input_per_m": 0.071, "output_per_m": 0.10, "note": "Current roster, MoE"},
    {"id": "mistralai/mistral-small-24b-instruct-2501", "input_per_m": 0.05, "output_per_m": 0.08, "note": "Current roster, fastest"},
    {"id": "google/gemma-3-12b-it",             "input_per_m": 0.04,  "output_per_m": 0.13, "note": "Current roster, credit expert"},

    # ── CANDIDATES: VERY CHEAP (<$0.20 avg) ──
    {"id": "qwen/qwen3-32b",                    "input_per_m": 0.08,  "output_per_m": 0.24, "note": "Qwen3 dense 32B"},
    {"id": "qwen/qwen3-14b",                    "input_per_m": 0.06,  "output_per_m": 0.24, "note": "Qwen3 dense 14B"},
    {"id": "qwen/qwen3.5-9b",                   "input_per_m": 0.05,  "output_per_m": 0.15, "note": "Qwen3.5 small, newest"},
    {"id": "mistralai/mistral-small-3.2-24b-instruct", "input_per_m": 0.075, "output_per_m": 0.20, "note": "Mistral Small 3.2"},
    {"id": "z-ai/glm-4-32b",                    "input_per_m": 0.10,  "output_per_m": 0.10, "note": "Zhipu GLM-4 32B"},
    {"id": "google/gemma-4-26b-a4b-it",         "input_per_m": 0.08,  "output_per_m": 0.35, "note": "Gemma 4 MoE, newest Google"},
    {"id": "nvidia/nemotron-nano-9b-v2",         "input_per_m": 0.04,  "output_per_m": 0.16, "note": "NVIDIA Nemotron Nano"},
    {"id": "microsoft/phi-4",                    "input_per_m": 0.065, "output_per_m": 0.14, "note": "Phi-4 (prev. failed, retest)"},

    # ── CANDIDATES: MID-RANGE ($0.20-$0.50 avg) ──
    {"id": "meta-llama/llama-4-scout",           "input_per_m": 0.08,  "output_per_m": 0.30, "note": "Llama 4 Scout MoE"},
    {"id": "meta-llama/llama-3.3-70b-instruct",  "input_per_m": 0.10,  "output_per_m": 0.32, "note": "Llama 3.3 70B"},
    {"id": "google/gemini-2.0-flash-001",        "input_per_m": 0.10,  "output_per_m": 0.40, "note": "Gemini 2.0 Flash"},
    {"id": "nvidia/llama-3.3-nemotron-super-49b-v1.5", "input_per_m": 0.10, "output_per_m": 0.40, "note": "NVIDIA Nemotron Super"},
    {"id": "bytedance-seed/seed-2.0-mini",       "input_per_m": 0.10,  "output_per_m": 0.40, "note": "ByteDance Seed 2.0"},
    {"id": "nvidia/nemotron-3-super-120b-a12b",  "input_per_m": 0.10,  "output_per_m": 0.50, "note": "NVIDIA 120B MoE"},

    # ── CANDIDATES: HIGHER TIER ($0.50+, strong reasoning) ──
    {"id": "minimax/minimax-m2.7",               "input_per_m": 0.30,  "output_per_m": 1.20, "note": "MiniMax M2.7 latest"},
    {"id": "deepseek/deepseek-v3.2-exp",         "input_per_m": 0.27,  "output_per_m": 0.41, "note": "DeepSeek v3.2 experimental"},
]


def make_backend(model_id: str, temperature: float = 0.2) -> OpenRouterBackend:
    config = LLMConfig(
        backend="openrouter", model=model_id,
        api_key_env="OPENROUTER_API_KEY", temperature=temperature,
    )
    return OpenRouterBackend(config)


# ── Test 1: Firm Decision Quality ────────────────────────────────────────

FIRM_SYSTEM = """You are the CEO/CFO of a pharmaceutical firm making quarterly decisions.
You must output a JSON object with these fields:
- price: int (per-unit price in dollars, range 50000-150000)
- production: int (units to produce, range 50-500)
- capex: int (capital expenditure in dollars)
- rd_spend: int (R&D spending in dollars)
- rd_allocation: object with keys "product", "process", "delivery" (floats summing to 1.0)
- sga_spend: int (selling/admin spending)
- equity_issuance_request: int (dollars of new equity to request, 0 if none)
- debt_request: int (dollars of new debt to request, 0 if none)
- dividends: int (dividend payout)
- buybacks: int (share buyback amount)
- reasoning: string (brief strategic rationale)

Output ONLY the JSON object wrapped in ```json ... ```."""

FIRM_USER = """Quarter 4, Year 1. You are firm_0 competing in the senolytic regenerative therapy market.

YOUR FINANCIALS:
- Cash: $180,000,000
- Revenue last quarter: $18,000,000 (240 units at $75,000)
- Net income last quarter: -$22,000,000 (growth phase)
- Total assets: $350,000,000
- Total debt: $50,000,000
- R&D progress: Gen 1 complete, Gen 2 at 45%
- Production capacity: 300 units/quarter
- Current employees: 850

MARKET:
- Total market demand: ~700 units/quarter, growing 5%/quarter
- 3 competitors: firm_1 (price $90K, moderate R&D), firm_2 (price $95K, low R&D)
- Your market share: 35% (strongest due to low price + high R&D)
- Gen 2 therapy expected to double efficacy, first-mover advantage worth ~$500M NPV

MACRO: Interest rates 4.5%, pharma sector sentiment bullish.

Make your Q4 decisions."""


def test_firm_decision(model_id: str) -> dict:
    """Test firm decision generation. Returns quality metrics."""
    backend = make_backend(model_id, temperature=0.3)
    t0 = time.time()
    try:
        raw = backend.complete(FIRM_SYSTEM, FIRM_USER)
        elapsed = time.time() - t0
        parsed = extract_json(raw)

        if parsed is None:
            return {"success": False, "error": "no_json", "time": elapsed, "raw_len": len(raw)}

        # Score the decision quality
        score = 0
        issues = []

        # Required fields
        required = ["price", "production", "capex", "rd_spend", "rd_allocation",
                     "sga_spend", "reasoning"]
        for f in required:
            if f in parsed:
                score += 1
            else:
                issues.append(f"missing_{f}")

        # Price sanity (should be 50K-150K range)
        price = parsed.get("price", 0)
        try:
            price = float(price)
            if 50000 <= price <= 150000:
                score += 2
            elif 30000 <= price <= 200000:
                score += 1
                issues.append("price_borderline")
            else:
                issues.append(f"price_insane_{price}")
        except (TypeError, ValueError):
            issues.append("price_not_numeric")

        # Production sanity
        prod = parsed.get("production", 0)
        try:
            prod = float(prod)
            if 50 <= prod <= 500:
                score += 2
            elif 10 <= prod <= 1000:
                score += 1
            else:
                issues.append(f"production_insane_{prod}")
        except (TypeError, ValueError):
            issues.append("production_not_numeric")

        # R&D allocation sums to ~1.0
        alloc = parsed.get("rd_allocation", {})
        if isinstance(alloc, dict):
            total = sum(float(v) for v in alloc.values() if isinstance(v, (int, float)))
            if 0.95 <= total <= 1.05:
                score += 2
            elif 0.8 <= total <= 1.2:
                score += 1
                issues.append("rd_alloc_off")
            else:
                issues.append(f"rd_alloc_bad_{total:.2f}")
        else:
            issues.append("rd_alloc_not_dict")

        # R&D spend reasonable ($5M-$200M)
        rd = parsed.get("rd_spend", 0)
        try:
            rd = float(rd)
            if 5_000_000 <= rd <= 200_000_000:
                score += 2
            else:
                issues.append(f"rd_spend_off_{rd/1e6:.0f}M")
        except (TypeError, ValueError):
            issues.append("rd_not_numeric")

        # Reasoning present and substantive
        reasoning = parsed.get("reasoning", "")
        if len(str(reasoning)) > 50:
            score += 2
        elif len(str(reasoning)) > 10:
            score += 1

        return {
            "success": True,
            "score": score,
            "max_score": 17,
            "issues": issues,
            "time": elapsed,
            "price": price,
            "production": prod,
            "rd_spend": rd,
        }

    except Exception as e:
        return {"success": False, "error": str(e)[:100], "time": time.time() - t0}


# ── Test 2: Environment Quality ──────────────────────────────────────────

ENV_SYSTEM = """You are the market environment for a pharmaceutical simulation.
Given firm actions, produce market outcomes.

Output JSON with:
- total_demand: integer (total units demanded this quarter)
- firm_outcomes: list of objects, each with:
  - firm_id: string
  - units_sold: integer
  - market_share: float (0-1)
  - demand_unmet: integer
- events: list of market events (0-3 events, each with "type" and "description")
- narrative: string (2-3 paragraph market gazette)

Output ONLY JSON wrapped in ```json ... ```."""

ENV_USER = """Quarter 3, Year 1. Three firms competing in senolytic therapy market.

FIRM ACTIONS:
firm_0: Price $75,000, Production 280, R&D $100M (Gen2 50%), SGA $20M, 300 capacity
firm_1: Price $90,000, Production 250, R&D $50M (Gen2 25%), SGA $15M, 250 capacity
firm_2: Price $95,000, Production 200, R&D $10M (Gen2 5%), SGA $5M, 200 capacity

MARKET CONDITIONS:
- Baseline demand: 700 units (growing ~5%/Q)
- Price elasticity: -1.2 (lower price = more demand share)
- Quality matters: firm_0 has best R&D pipeline
- firm_0 has $250M cash, firm_1 $200M, firm_2 $140M

Generate market outcomes. Price and quality differences should create meaningful variation."""


def test_environment(model_id: str) -> dict:
    """Test environment generation quality."""
    backend = make_backend(model_id, temperature=0.3)
    t0 = time.time()
    try:
        raw = backend.complete(ENV_SYSTEM, ENV_USER)
        elapsed = time.time() - t0
        parsed = extract_json(raw)

        if parsed is None:
            return {"success": False, "error": "no_json", "time": elapsed}

        score = 0
        issues = []

        # Has total_demand
        td = parsed.get("total_demand", 0)
        try:
            td = int(td)
            if 500 <= td <= 1200:
                score += 2
            elif 200 <= td <= 2000:
                score += 1
                issues.append(f"demand_borderline_{td}")
            else:
                issues.append(f"demand_insane_{td}")
        except (TypeError, ValueError):
            issues.append("demand_not_int")

        # Has firm_outcomes
        outcomes = parsed.get("firm_outcomes", [])
        if isinstance(outcomes, list) and len(outcomes) >= 3:
            score += 2

            # Check shares sum to ~1.0
            shares = []
            for o in outcomes:
                ms = o.get("market_share", 0)
                try:
                    shares.append(float(ms))
                except (TypeError, ValueError):
                    pass
            if shares:
                total_share = sum(shares)
                if 0.95 <= total_share <= 1.05:
                    score += 2
                elif 0.8 <= total_share <= 1.2:
                    score += 1

            # firm_0 should have highest share (lowest price + best R&D)
            firm_shares = {}
            for o in outcomes:
                fid = o.get("firm_id", "")
                ms = o.get("market_share", 0)
                try:
                    firm_shares[fid] = float(ms)
                except (TypeError, ValueError):
                    pass
            if firm_shares:
                f0_share = firm_shares.get("firm_0", 0)
                if f0_share == max(firm_shares.values()):
                    score += 2  # correctly gave firm_0 highest share
                else:
                    issues.append("firm_0_not_leader")
        else:
            issues.append("missing_outcomes")

        # Has narrative
        narrative = parsed.get("narrative", "")
        if len(str(narrative)) > 200:
            score += 2
        elif len(str(narrative)) > 50:
            score += 1
        else:
            issues.append("thin_narrative")

        # Has events (optional but good)
        events = parsed.get("events", [])
        if isinstance(events, list) and len(events) > 0:
            score += 1

        return {
            "success": True,
            "score": score,
            "max_score": 11,
            "issues": issues,
            "time": elapsed,
            "total_demand": td,
        }

    except Exception as e:
        return {"success": False, "error": str(e)[:100], "time": time.time() - t0}


# ── Test 3: Equity Pricing ───────────────────────────────────────────────

PRICING_SYSTEM = """You are a financial analyst pricing pharmaceutical stocks.
Given firm financials, estimate fair share prices using DCF, revenue multiples, and pipeline value.

Output JSON:
{"firms": [{"firm_id": "...", "fair_price": N, "reasoning": "...", "confidence": "high/medium/low"}]}

Output ONLY JSON wrapped in ```json ... ```."""

PRICING_USER = """Price these three pharma firms (quarterly data):

firm_0:
  Revenue: $18,000,000/Q, Net Income: -$22,000,000/Q
  Cash: $180M, Total Assets: $350M, Debt: $50M, Equity: $280M
  R&D: $100M/Q, Gen 2 at 50% (first-mover), 850 employees
  Shares: 10M outstanding, IPO was $175M (implied $17.50/share)

firm_1:
  Revenue: $16,500,000/Q, Net Income: -$12,000,000/Q
  Cash: $200M, Total Assets: $320M, Debt: $30M, Equity: $270M
  R&D: $50M/Q, Gen 2 at 25%, 700 employees
  Shares: 10M outstanding

firm_2:
  Revenue: $14,000,000/Q, Net Income: -$3,000,000/Q
  Cash: $140M, Total Assets: $250M, Debt: $20M, Equity: $210M
  R&D: $10M/Q, Gen 2 at 5%, 400 employees
  Shares: 10M outstanding

Market: Senolytic therapy, growing 20%/yr, 600M potential patients globally.
Sector: Early biotech, comparable to 2005-era biologics."""


def test_pricing(model_id: str) -> dict:
    """Test equity pricing quality."""
    backend = make_backend(model_id, temperature=0.1)
    t0 = time.time()
    try:
        raw = backend.complete(PRICING_SYSTEM, PRICING_USER)
        elapsed = time.time() - t0
        parsed = extract_json(raw)

        if parsed is None:
            return {"success": False, "error": "no_json", "time": elapsed}

        score = 0
        issues = []

        firms = parsed.get("firms", [])
        if not isinstance(firms, list) or len(firms) < 3:
            return {"success": True, "score": 0, "max_score": 10, "issues": ["missing_firms"], "time": elapsed}

        prices = {}
        for f in firms:
            fid = f.get("firm_id", "")
            try:
                fp = float(f.get("fair_price", 0))
                prices[fid] = fp
            except (TypeError, ValueError):
                issues.append(f"non_numeric_price_{fid}")

        # All 3 firms priced
        if len(prices) >= 3:
            score += 2
        elif len(prices) >= 2:
            score += 1

        # Prices positive and reasonable ($5-$500 range for early biotech)
        reasonable = sum(1 for p in prices.values() if 5 <= p <= 500)
        score += min(reasonable, 3)

        # firm_0 should be highest (best R&D pipeline despite losses)
        f0 = prices.get("firm_0", 0)
        f2 = prices.get("firm_2", 0)
        if f0 > f2:
            score += 2  # correctly values R&D pipeline
        else:
            issues.append("firm_0_undervalued")

        # Has reasoning
        has_reasoning = sum(1 for f in firms if len(str(f.get("reasoning", ""))) > 20)
        if has_reasoning >= 3:
            score += 2
        elif has_reasoning >= 1:
            score += 1

        return {
            "success": True,
            "score": score,
            "max_score": 9,
            "issues": issues,
            "time": elapsed,
            "prices": prices,
        }

    except Exception as e:
        return {"success": False, "error": str(e)[:100], "time": time.time() - t0}


# ── Main sweep ───────────────────────────────────────────────────────────

def run_sweep():
    print("=" * 80)
    print("MODEL SWEEP: Testing quality vs price across 20+ models")
    print(f"Models: {len(SWEEP_MODELS)}")
    print(f"Tests per model: 3 (firm decision, environment, pricing)")
    print(f"Total API calls: ~{len(SWEEP_MODELS) * 3}")
    print(f"Estimated cost: ~$0.50-$1.00")
    print("=" * 80)

    results = []

    for i, model_info in enumerate(SWEEP_MODELS):
        model_id = model_info["id"]
        avg_cost = (model_info["input_per_m"] + model_info["output_per_m"]) / 2
        note = model_info["note"]

        print(f"\n[{i+1}/{len(SWEEP_MODELS)}] {model_id}")
        print(f"  Cost: ${model_info['input_per_m']:.3f}/${model_info['output_per_m']:.3f} per M tokens (avg ${avg_cost:.3f})")
        print(f"  Note: {note}")

        # Test 1: Firm decisions
        print("  Testing firm decisions...", end=" ", flush=True)
        firm_result = test_firm_decision(model_id)
        if firm_result["success"]:
            print(f"Score: {firm_result['score']}/{firm_result['max_score']}  "
                  f"({firm_result['time']:.1f}s)  Issues: {firm_result.get('issues', [])}")
        else:
            print(f"FAILED: {firm_result.get('error', 'unknown')} ({firm_result['time']:.1f}s)")

        # Test 2: Environment
        print("  Testing environment...", end=" ", flush=True)
        env_result = test_environment(model_id)
        if env_result["success"]:
            print(f"Score: {env_result['score']}/{env_result['max_score']}  "
                  f"({env_result['time']:.1f}s)  Issues: {env_result.get('issues', [])}")
        else:
            print(f"FAILED: {env_result.get('error', 'unknown')} ({env_result['time']:.1f}s)")

        # Test 3: Pricing
        print("  Testing pricing...", end=" ", flush=True)
        pricing_result = test_pricing(model_id)
        if pricing_result["success"]:
            print(f"Score: {pricing_result['score']}/{pricing_result['max_score']}  "
                  f"({pricing_result['time']:.1f}s)  Issues: {pricing_result.get('issues', [])}")
        else:
            print(f"FAILED: {pricing_result.get('error', 'unknown')} ({pricing_result['time']:.1f}s)")

        # Aggregate
        total_score = 0
        max_score = 0
        total_time = 0
        failures = 0
        for r in [firm_result, env_result, pricing_result]:
            if r["success"]:
                total_score += r["score"]
                max_score += r["max_score"]
            else:
                failures += 1
            total_time += r.get("time", 0)

        if max_score > 0:
            quality_pct = total_score / max_score * 100
        else:
            quality_pct = 0

        # Quality per dollar (higher = better value)
        if avg_cost > 0:
            value_score = quality_pct / avg_cost
        else:
            value_score = 0

        row = {
            "model": model_id,
            "note": note,
            "input_per_m": model_info["input_per_m"],
            "output_per_m": model_info["output_per_m"],
            "avg_cost_per_m": avg_cost,
            "firm_score": firm_result.get("score", 0) if firm_result["success"] else -1,
            "firm_max": firm_result.get("max_score", 17),
            "env_score": env_result.get("score", 0) if env_result["success"] else -1,
            "env_max": env_result.get("max_score", 11),
            "pricing_score": pricing_result.get("score", 0) if pricing_result["success"] else -1,
            "pricing_max": pricing_result.get("max_score", 9),
            "total_score": total_score,
            "max_score": max_score,
            "quality_pct": quality_pct,
            "value_score": value_score,
            "total_time": total_time,
            "failures": failures,
        }
        results.append(row)

        print(f"  => Quality: {quality_pct:.0f}%  Value: {value_score:.0f}  Time: {total_time:.1f}s  Failures: {failures}")

    # ── Results summary ──────────────────────────────────────────────────

    print("\n" + "=" * 100)
    print("RESULTS SUMMARY: Quality vs Price")
    print("=" * 100)

    # Sort by quality
    by_quality = sorted(results, key=lambda r: r["quality_pct"], reverse=True)

    print(f"\n{'Model':<55} {'Quality':>7} {'Avg$/M':>7} {'Value':>7} {'Firm':>5} {'Env':>5} {'Price':>5} {'Time':>6} {'Fail':>4}")
    print("-" * 100)
    for r in by_quality:
        firm_s = f"{r['firm_score']}/{r['firm_max']}" if r['firm_score'] >= 0 else "FAIL"
        env_s = f"{r['env_score']}/{r['env_max']}" if r['env_score'] >= 0 else "FAIL"
        price_s = f"{r['pricing_score']}/{r['pricing_max']}" if r['pricing_score'] >= 0 else "FAIL"
        print(f"{r['model']:<55} {r['quality_pct']:>6.0f}% ${r['avg_cost_per_m']:>5.3f} {r['value_score']:>7.0f} "
              f"{firm_s:>5} {env_s:>5} {price_s:>5} {r['total_time']:>5.1f}s {r['failures']:>4}")

    # Best value (quality/price frontier)
    print("\n" + "=" * 100)
    print("BEST VALUE (Quality % / Avg Cost per M tokens)")
    print("=" * 100)
    by_value = sorted(results, key=lambda r: r["value_score"], reverse=True)
    for i, r in enumerate(by_value[:10]):
        print(f"  {i+1}. {r['model']:<50} Value={r['value_score']:>7.0f}  "
              f"Quality={r['quality_pct']:.0f}%  Cost=${r['avg_cost_per_m']:.3f}/M")

    # Recommended roster
    print("\n" + "=" * 100)
    print("RECOMMENDED ROSTER (Top 5 by value, must include DeepSeek R1 + MiniMax)")
    print("=" * 100)

    must_keep = {"deepseek/deepseek-r1-0528", "minimax/minimax-m2.5"}
    roster = []
    for r in by_value:
        if r["model"] in must_keep:
            roster.append(r)
    for r in by_value:
        if r["model"] not in must_keep and len(roster) < 7:
            if r["quality_pct"] >= 50 and r["failures"] == 0:
                roster.append(r)

    for i, r in enumerate(roster):
        tag = " [KEEP]" if r["model"] in must_keep else ""
        print(f"  {i+1}. {r['model']:<50} Quality={r['quality_pct']:.0f}%  "
              f"Cost=${r['avg_cost_per_m']:.3f}/M  Value={r['value_score']:.0f}{tag}")

    # Save CSV
    csv_path = Path("data/model_sweep_results.csv")
    csv_path.parent.mkdir(exist_ok=True)
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=results[0].keys())
        writer.writeheader()
        writer.writerows(results)
    print(f"\nResults saved to {csv_path}")

    return results


if __name__ == "__main__":
    run_sweep()
