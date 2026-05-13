"""
Run model evaluation across all roles: environment, equity pricing, credit.

Uses data from the most recent simulation run as the test scenario.
Polls all 5 cheap models and compares their outputs.

Usage:
  OPENROUTER_API_KEY=sk-or-... python run_model_eval.py
"""

import os
import sys
import csv
import time
from pathlib import Path
from collections import defaultdict

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.model_eval import (
    EVAL_MODELS, run_model_comparison, format_comparison_report,
    eval_environment, eval_equity_pricing, eval_credit_decisions,
    create_backend,
)

API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
if not API_KEY:
    print("Set OPENROUTER_API_KEY environment variable")
    sys.exit(1)

# Find latest run
outputs_dir = Path("outputs")
runs = sorted(outputs_dir.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True)
if not runs:
    print("No runs found in outputs/")
    sys.exit(1)

latest_run = runs[0]
print(f"Using data from: {latest_run.name}")

# Load environment response (gazette)
gazette_path = latest_run / "public" / "gazette_Q3.txt"
if not gazette_path.exists():
    gazette_path = latest_run / "public" / "gazette_Q2.txt"
if not gazette_path.exists():
    gazette_path = latest_run / "public" / "gazette_Q1.txt"

env_response = gazette_path.read_text(encoding="utf-8") if gazette_path.exists() else "No gazette found"

# Load Compustat for firm data
panel_path = latest_run / "compustat_q.csv"
if not panel_path.exists():
    print(f"No compustat found at {panel_path}")
    sys.exit(1)

rows = list(csv.DictReader(open(panel_path)))

# Build scenario description (what the environment was given)
scenario = """
SRT pharmaceutical market simulation, Q3 of first year.
3 firms competing with Gen 1 senolytic regenerative therapy.
Prices range from $68K-$100K per annual treatment course.
Market is nascent, growing, with 600M potential patients globally.
Each firm has different R&D spending levels ($10M-$100M/Q).
IPO was $175M. Some firms have raised additional capital.
This is a growth industry similar to early biotech/Internet.
"""

# Build firm data for pricing and credit evaluation
by_firm = defaultdict(list)
for r in rows:
    by_firm[r["firm_id"]].append(r)

firm_data_lines = ["FIRM FINANCIAL DATA (latest quarter):\n"]
for fid in sorted(by_firm):
    r = by_firm[fid][-1]  # latest quarter
    debt = float(r['dlcq']) + float(r['dlttq'])
    firm_data_lines.append(f"""
{fid}:
  Revenue (quarterly): ${float(r['saleq']):,.0f}
  Net Income: ${float(r['niq']):,.0f}
  Cash: ${float(r['cheq']):,.0f}
  Total Assets: ${float(r['atq']):,.0f}
  Total Debt: ${debt:,.0f}
  Total Equity: ${float(r['ceqq']):,.0f}
  R&D Spend: ${float(r['xrdq']):,.0f}
  SGA Spend: ${float(r['xsgaq']):,.0f}
  Capex: ${float(r['capxq']):,.0f}
  Shares Outstanding: {float(r['cshoq']):.1f}M
  Current Equity Price: ${float(r['prccq']):.2f}
  PPE: ${float(r['ppentq']):,.0f}
  Gross Margin: {(float(r['saleq'])-float(r['cogsq']))/max(1,float(r['saleq']))*100:.0f}%
""")
firm_data = "\n".join(firm_data_lines)

print(f"\n{'='*60}")
print("MODEL EVALUATION: 5 models × 3 tasks = 15 API calls")
print(f"Estimated cost: ~$0.10")
print(f"{'='*60}\n")

# Run the comparison
results = run_model_comparison(API_KEY, env_response, scenario, firm_data)

# Print report
report = format_comparison_report(results)
print(f"\n{report}")

# Save report
report_path = latest_run / "model_eval_report.txt"
with open(report_path, "w", encoding="utf-8") as f:
    f.write(report)
print(f"\nReport saved: {report_path}")

# ── Cross-model polling for environment quality ──────────────────────────
print(f"\n{'='*60}")
print("ENVIRONMENT QUALITY POLL: Each model rates the environment")
print(f"{'='*60}\n")

# Also generate environment responses from each model and have others rate them
print("Generating environment responses from each model...")

ENV_SCENARIO_PROMPT_SYSTEM = """You are the market environment for a pharmaceutical simulation.
Given firm actions, produce market outcomes. Be realistic, create variation.
Output JSON with: total_demand (integer), firm_outcomes (list with units_sold and market_share),
and narrative (2-3 paragraph gazette)."""

ENV_SCENARIO_PROMPT_USER = """Quarter 3 of year 1. Three firms competing.

firm_0: Price $75,000, Production 250, R&D $100M, SGA $20M. Aggressive growth strategy.
firm_1: Price $90,000, Production 250, R&D $50M, SGA $15M. Balanced strategy.
firm_2: Price $95,000, Production 200, R&D $10M, SGA $5M. Conservative strategy.

Baseline demand: 700 units.
firm_0 has strongest R&D pipeline (50% of Gen 2), firm_1 moderate (25%), firm_2 minimal (5%).
firm_0 has $250M cash, firm_1 has $200M, firm_2 has $140M.

Produce market outcomes. Price differences should affect shares. Quality should matter.
Include a narrative gazette."""

env_responses = {}
for model in EVAL_MODELS:
    print(f"  Generating env response from {model}...")
    try:
        backend = create_backend(model, API_KEY, temperature=0.3)
        response = backend.complete(ENV_SCENARIO_PROMPT_SYSTEM, ENV_SCENARIO_PROMPT_USER)
        env_responses[model] = response
        # Extract total demand from response
        from src.llm_backends import extract_json
        parsed = extract_json(response)
        if parsed:
            td = parsed.get("total_demand", "?")
            print(f"    Total demand: {td}")
        else:
            print(f"    (couldn't parse JSON)")
    except Exception as e:
        print(f"    FAILED: {e}")
        env_responses[model] = None

# Now cross-poll: each model rates each other model's env response
print("\nCross-polling environment responses...")
cross_ratings = defaultdict(dict)  # rated_model -> rater_model -> rating

for rated_model, response in env_responses.items():
    if response is None:
        continue
    for rater_model in EVAL_MODELS:
        if rater_model == rated_model:
            continue  # don't self-rate
        try:
            rating = eval_environment(response, scenario, rater_model, API_KEY)
            if rating:
                cross_ratings[rated_model][rater_model] = rating
                print(f"  {rater_model:40} rates {rated_model:40} -> {rating.get('overall', '?')}/10")
        except Exception as e:
            print(f"  {rater_model} rating {rated_model} FAILED: {e}")

# Compile final scores
print(f"\n{'='*60}")
print("FINAL ENVIRONMENT RANKINGS")
print(f"{'='*60}\n")

env_scores = {}
for rated_model in env_responses:
    if rated_model not in cross_ratings:
        continue
    ratings = cross_ratings[rated_model]
    if not ratings:
        continue
    overalls = [r.get("overall", 5) for r in ratings.values()]
    avg = sum(overalls) / len(overalls)
    env_scores[rated_model] = avg
    dims = ["demand_realism", "event_quality", "narrative_richness", "variation", "consistency"]
    dim_avgs = {}
    for d in dims:
        vals = [r.get(d, 5) for r in ratings.values()]
        dim_avgs[d] = sum(vals) / len(vals)
    print(f"{rated_model:55} Overall: {avg:.1f}/10")
    for d, v in dim_avgs.items():
        print(f"  {d:25} {v:.1f}/10")
    print()

# Save full results
eval_report_path = latest_run / "model_eval_full.txt"
with open(eval_report_path, "w", encoding="utf-8") as f:
    f.write("=== FULL MODEL EVALUATION RESULTS ===\n\n")
    f.write(report + "\n\n")
    f.write("=== ENVIRONMENT CROSS-POLL ===\n\n")
    for rated, raters in cross_ratings.items():
        f.write(f"\n{rated} rated by others:\n")
        for rater, rating in raters.items():
            f.write(f"  {rater}: {json.dumps(rating)}\n")
    f.write(f"\n=== FINAL RANKINGS ===\n")
    for model, score in sorted(env_scores.items(), key=lambda x: -x[1]):
        f.write(f"  {model}: {score:.1f}/10\n")

print(f"\nFull report saved: {eval_report_path}")
print(f"\nTotal API calls: ~{len(EVAL_MODELS) * 3 + len(EVAL_MODELS) + len(EVAL_MODELS) * (len(EVAL_MODELS)-1)}")
