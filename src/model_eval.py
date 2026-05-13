"""
Model evaluation: test multiple LLM models for each role and compare quality.

For FIRMS: we already tested DeepSeek, Qwen, Mistral. Metric: NPV, strategy coherence.
For FINANCIAL: test equity pricing accuracy and credit decision quality.
For ENVIRONMENT: test realism, variation, context-mindfulness via polling.

This module runs focused evaluations, not full simulations.
"""

from __future__ import annotations

import json
import time
from .llm_backends import LLMBackend, OpenRouterBackend, extract_json
from .config import LLMConfig


# Models to evaluate (all cheap, diverse architectures)
EVAL_MODELS = [
    "deepseek/deepseek-v3.2",                    # $0.64/M - our proven default
    "qwen/qwen3-235b-a22b-2507",                 # $0.17/M - Qwen MoE
    "mistralai/mistral-small-24b-instruct-2501",  # $0.13/M - Mistral
    "google/gemma-3-12b-it",                      # $0.17/M - Google
    "microsoft/phi-4",                             # $0.21/M - Microsoft
]


def create_backend(model: str, api_key: str, temperature: float = 0.2) -> LLMBackend:
    config = LLMConfig(
        backend="openrouter", model=model,
        api_key_env="__direct__", temperature=temperature,
    )
    # Inject key directly
    import os
    os.environ["__direct__"] = api_key
    config = LLMConfig(backend="openrouter", model=model,
                       api_key_env="__direct__", temperature=temperature)
    return OpenRouterBackend(config)


# ── Environment Evaluation ───────────────────────────────────────────────

ENV_EVAL_PROMPT_SYSTEM = """You are evaluating the REALISM and QUALITY of a market environment simulation
for a pharmaceutical industry. You will be shown a market scenario and the
environment's response (demand allocation, events, narrative).

Rate the environment on these dimensions (1-10 each):

1. DEMAND_REALISM: Are the total demand numbers and firm-level allocations plausible?
   Do they respond sensibly to price differences, quality differences, and market conditions?

2. EVENT_QUALITY: Are the events (if any) well-timed, consequential, and realistic?
   Or are they generic/missing? Note: having zero events in an early quarter is fine.

3. NARRATIVE_RICHNESS: Is the gazette narrative specific, referencing real firm names,
   real price differences, and real competitive dynamics? Or is it generic boilerplate?

4. VARIATION: Does the environment create meaningful differences between firms?
   Or does it treat all firms identically despite different strategies?

5. CONSISTENCY: Does the narrative match the numbers? If the narrative says
   "firm_0 gained share" does the data show firm_0 gaining share?

Output ONLY a JSON object:
{"demand_realism": N, "event_quality": N, "narrative_richness": N, "variation": N, "consistency": N, "overall": N, "brief_comment": "..."}"""


def eval_environment(
    env_response: str,
    scenario_description: str,
    evaluator_model: str,
    api_key: str,
) -> dict | None:
    """Have one model evaluate an environment response."""
    backend = create_backend(evaluator_model, api_key, temperature=0.1)

    user = f"""SCENARIO:
{scenario_description}

ENVIRONMENT RESPONSE:
{env_response}

Rate this environment response (1-10 per dimension). Output JSON only."""

    result = backend.complete_json(ENV_EVAL_PROMPT_SYSTEM, user)
    return result


# ── Equity Pricing Evaluation ────────────────────────────────────────────

PRICING_EVAL_PROMPT = """You are a financial analyst evaluating equity pricing for pharmaceutical firms.

Given the financial data below, estimate a fair price per share for each firm.
Use multiple valuation approaches:
1. Revenue multiple (what multiple of annualized revenue is fair for a growth biotech?)
2. Asset-based (what are the tangible + intangible assets worth?)
3. Pipeline value (what is the R&D pipeline worth given progress toward Gen 2?)

For each firm, output your estimated fair price and brief reasoning.

Output JSON:
{"firms": [{"firm_id": "...", "fair_price": N, "reasoning": "...", "confidence": "high/medium/low"}]}"""


def eval_equity_pricing(
    firm_data: str,
    model: str,
    api_key: str,
) -> dict | None:
    """Have a model price equity for a set of firms."""
    backend = create_backend(model, api_key, temperature=0.1)
    result = backend.complete_json(PRICING_EVAL_PROMPT, firm_data)
    return result


# ── Credit Decision Evaluation ───────────────────────────────────────────

CREDIT_EVAL_PROMPT = """You are a credit analyst evaluating loan applications from pharmaceutical firms.

For each firm, decide:
1. Should we extend a revolving credit facility? If yes, how much and at what rate?
2. Should we approve their term debt request? If yes, how much and at what rate?
3. What is our assessment of their default risk?

Consider: cash position, burn rate, revenue trend, debt levels, R&D progress.

Output JSON:
{"firms": [{"firm_id": "...", "revolver_approved": N, "revolver_rate_quarterly": N, "term_debt_approved": N, "term_rate_quarterly": N, "default_risk": "low/medium/high", "reasoning": "..."}]}"""


def eval_credit_decisions(
    firm_data: str,
    model: str,
    api_key: str,
) -> dict | None:
    """Have a model make credit decisions for a set of firms."""
    backend = create_backend(model, api_key, temperature=0.1)
    result = backend.complete_json(CREDIT_EVAL_PROMPT, firm_data)
    return result


# ── Run Full Model Comparison ────────────────────────────────────────────

def run_model_comparison(api_key: str, env_response: str, scenario: str,
                         firm_data: str) -> dict:
    """Run all models through all evaluations and compile results."""

    results = {
        "environment_ratings": {},      # model -> ratings by other models
        "environment_self_ratings": {},  # model -> its own env response rating
        "pricing_estimates": {},         # model -> price estimates
        "credit_decisions": {},          # model -> credit decisions
        "timing": {},                    # model -> seconds per call
    }

    for model in EVAL_MODELS:
        print(f"\nEvaluating: {model}")

        # 1. Rate the environment response
        t0 = time.time()
        try:
            env_rating = eval_environment(env_response, scenario, model, api_key)
            results["environment_ratings"][model] = env_rating
            print(f"  Env rating: {env_rating.get('overall', '?') if env_rating else 'FAIL'}")
        except Exception as e:
            print(f"  Env rating FAILED: {e}")
            results["environment_ratings"][model] = None

        # 2. Price equity
        try:
            pricing = eval_equity_pricing(firm_data, model, api_key)
            results["pricing_estimates"][model] = pricing
            if pricing and "firms" in pricing:
                prices = [f.get("fair_price", 0) for f in pricing["firms"]]
                print(f"  Pricing: {prices}")
            else:
                print(f"  Pricing: {pricing}")
        except Exception as e:
            print(f"  Pricing FAILED: {e}")
            results["pricing_estimates"][model] = None

        # 3. Credit decisions
        try:
            credit = eval_credit_decisions(firm_data, model, api_key)
            results["credit_decisions"][model] = credit
            if credit and "firms" in credit:
                risks = [f.get("default_risk", "?") for f in credit["firms"]]
                print(f"  Credit: default risks = {risks}")
            else:
                print(f"  Credit: {credit}")
        except Exception as e:
            print(f"  Credit FAILED: {e}")
            results["credit_decisions"][model] = None

        elapsed = time.time() - t0
        results["timing"][model] = elapsed
        print(f"  Time: {elapsed:.1f}s")

    return results


def format_comparison_report(results: dict) -> str:
    """Format the comparison results as a readable report."""
    lines = ["=== MODEL COMPARISON REPORT ===\n"]

    # Environment ratings
    lines.append("ENVIRONMENT REALISM RATINGS (each model rates the env response):")
    for model, rating in results["environment_ratings"].items():
        if rating:
            overall = rating.get("overall", "?")
            comment = rating.get("brief_comment", "")[:80]
            lines.append(f"  {model:55} Overall: {overall}/10  {comment}")
        else:
            lines.append(f"  {model:55} FAILED")

    lines.append("")

    # Pricing estimates
    lines.append("EQUITY PRICING ESTIMATES (fair price per share):")
    for model, pricing in results["pricing_estimates"].items():
        if pricing and "firms" in pricing:
            firms_data = pricing["firms"]
            if isinstance(firms_data, list):
                for f in firms_data:
                    fid = f.get("firm_id", "?")
                    try:
                        price = float(f.get("fair_price", 0))
                    except (TypeError, ValueError):
                        price = 0
                    conf = f.get("confidence", "?")
                    lines.append(f"  {model:40} {fid}: ${price:,.0f} ({conf})")
            else:
                lines.append(f"  {model:40} (non-list format)")
        elif pricing:
            lines.append(f"  {model:40} (unexpected format)")
        else:
            lines.append(f"  {model:40} FAILED")

    lines.append("")

    # Credit decisions
    lines.append("CREDIT DECISIONS:")
    for model, credit in results["credit_decisions"].items():
        if credit and "firms" in credit:
            for f in credit["firms"]:
                fid = f.get("firm_id", "?")
                risk = f.get("default_risk", "?")
                try:
                    revolver = float(f.get("revolver_approved", 0))
                    term = float(f.get("term_debt_approved", 0))
                    lines.append(f"  {model:40} {fid}: risk={risk} rev=${revolver/1e6:.0f}M term=${term/1e6:.0f}M")
                except (TypeError, ValueError):
                    lines.append(f"  {model:40} {fid}: risk={risk}")
        else:
            lines.append(f"  {model:40} FAILED")

    lines.append("")

    # Timing
    lines.append("RESPONSE TIME:")
    for model, t in sorted(results["timing"].items(), key=lambda x: x[1]):
        lines.append(f"  {model:55} {t:.1f}s")

    return "\n".join(lines)
