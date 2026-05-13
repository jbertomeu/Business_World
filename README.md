# LLM Firm Lab

Multi-agent corporate-finance simulation where LLM-powered firms,
auditors, analysts, regulators, bankers, and activists interact inside a
GAAP-accurate product-market world. Produces 21 WRDS-style research
datasets + 6 JSONL audit trails per run.

As of Wave λ (April 2026): **~8,500 LoC across ~55 modules, 303 tests
passing, scorecard 19🟢 / 1🟡** against the 20 CLAUDE Industry Simulation
Principles. Codex-audited: 28/33 specific claims independently confirmed
(`CODEX_AUDIT_FILLED.md`). Waves ι + κ + λ added scenario-driven
industry economics, 5-year strategic planning with variance
accountability, and full private→public lifecycle (founder seed → PE
rounds → IPO).

## Quick Start

```bash
# 1. Install deps (Python 3.10+)
pip install -r requirements.txt

# 2. Set API keys in .env
#    OPENROUTER_API_KEY=sk-or-...   (primary backend, 343 models)
#    MINIMAX_API_KEY=sk-cp-...      (optional)

# 3. Smoke test (mock agents, no external calls — verifies installation)
python -m src run --config config/test_stage12_mock.yaml --mock

# 4. Short live run (3 firms x 4 quarters, ~45 min, ~$0.03 USD)
python -u -m src run --config config/validation_v15_theta.yaml

# 5. Explore results
python -m streamlit run app/dashboard.py
```

## What You Get Per Run

Every run produces `outputs/<run_id>/` with:

- **21 WRDS-style CSVs**: `compustat_q.csv` (firm × quarter), `execucomp.csv`,
  `audit_analytics.csv`, `analyst_forecasts.csv`, `restatements.csv`,
  `ceo_turnover.csv`, `debt_facilities.csv`, `covenant_violations.csv`,
  `insider_transactions.csv`, `activist_campaigns.csv`, `crosswalk.csv`,
  `director_turnover.csv`, ... (see `docs/datasets.md`)
- **6 JSONL audit trails**: `proposals.jsonl` (every structured agent
  action), `negotiations.jsonl` (multi-round bargaining), `bs_violations.jsonl`,
  `broker_queries.jsonl`, `peer_observations.jsonl`, `llm_calls.jsonl`
- **Cost telemetry**: `cost_summary.txt` — per-model + per-agent-role
  token + $ USD breakdown
- **Snapshots**: `snapshots/Q{N}.pkl` — complete WorldState every quarter,
  resumable with `--restart-from`
- **Narrative**: board minutes, R&D reports, analyst notes, 10-K-style
  annual reports per firm

## How It Works

Each quarter runs a ~20-phase pipeline. All agents (firm, auditor,
analyst, SEC, activist, investment bank, commercial bank, equity market,
board governance, M&A) emit structured `Action` proposals; the engine
adjudicates (clamping, auctions, voting); state mutates through the
canonical `WorldState`. See `docs/architecture.md` for the full layered
architecture and `docs/principles_review.md` for the design-principle
scorecard.

## Features (All Toggleable)

Every feature defaults to a safe value. Enable via YAML config:

```yaml
# config/my_run.yaml
n_firms_initial: 5
n_quarters: 20
seed: 42

# Core expansion (v0.5)
earnings_management_enabled: true
sec_enabled: true
sellside_analysts_enabled: true
auditor_enabled: true
governance_enabled: true
earnings_announcement_enabled: true
restatements_enabled: true
ma_enabled: true
debt_covenants_enabled: true
annual_reports_enabled: true
activist_investors_enabled: true

# Stage 12 (corporate finance)
legal_reserves_enabled: true
pension_enabled: true
deferred_taxes_enabled: true
stock_comp_enabled: true
bad_debt_enabled: true
restructuring_enabled: true

# Wave zeta (scenarios)
scenario: biotech_early_stage    # or: mature_industry, distressed

# Wave eta (noise + beliefs)
noisy_signals_enabled: true
noisy_signals_sd: 0.20

# Wave theta (directors, interlock, 3-LLM committee, $ telemetry)
directors_enabled: true                # shared pool with interlocking seats
director_lifecycle_enabled: true       # annual refresh + default departures
three_llm_board_enabled: true          # 3 voices + synthesis (4x gov cost)
cost_telemetry_enabled: true           # $ pricing via OpenRouter API

parallel_firm_decisions: true          # ~3x speedup on parallel LLM calls
```

Run with: `python -m src run --config config/my_run.yaml`

## Scenarios

Three shipped scenarios set per-firm founding conditions (cash, IPO
price, PPE, capability, brand, cost structure, CEO pay):

- `biotech_early_stage` — high-risk, cash-burning R&D
- `mature_industry` — established players, modest growth
- `distressed` — leveraged firms in fragile cash positions

See `scenarios/*.yaml`. Default (no scenario) = uniform IPO at $17.50 × 10M shares.

## Post-Run Analysis

```bash
# Baseline regressions (12 specifications)
python scripts/baseline_regressions.py --runs <run_id>

# Cross-run meta-analysis
python scripts/meta_analysis.py

# Streamlit dashboard (16 tabs)
python -m streamlit run app/dashboard.py

# Config builder UI
python -m streamlit run app/config_builder.py
```

## Project Structure

```
src/                         # Simulation engine (~50 modules)
  orchestrator.py            # Phase pipeline, WorldState
  accounting.py              # GAAP (BS/IS/CFS, manipulation, restatement)
  types.py                   # Dataclasses (FirmState, CompustatRow, etc.)
  engine.py                  # Action / ActionResult / ActionLog
  negotiation.py             # Multi-round bargaining primitives
  scenarios.py               # Scenario loader
  beliefs.py                 # FirmBelief, noise, EWMA
  telemetry.py               # LLM cost tracking
  identifiers.py             # Director, Product, Security, crosswalk
  snapshots.py               # Pickle + restart
  # Agent factories:
  cli.py                     # make_firm_agent (+ board discussion)
  auditor.py, sec_agent.py, sellside_analyst.py, activist.py,
  governance.py, ma_agent.py, annual_report.py,
  equity_market.py, investment_bank.py, commercial_bank.py,
  earnings_announcement.py, env_verifier.py

config/                      # YAML configs + model roster
scenarios/                   # Heterogeneous firm scenarios
scripts/                     # Analysis: regressions, meta, backfill
app/                         # Streamlit: dashboard + config_builder
tests/                       # 273 tests (accounting, governance, directors, ...)
docs/
  architecture.md            # Layered architecture + design choices
  principles_review.md       # 20-principle scorecard (19🟢/1🟡)
  datasets.md                # CSV + JSONL reference
outputs/                     # Per-run folders
data/                        # Cross-run accumulated panel
```

## Reproducibility

- **Mock runs** are byte-reproducible with the same seed (see
  `tests/test_reproducibility.py`).
- **Live runs** are NOT reproducible across LLM calls (backend
  randomness), but the full structured-action + state history is snapshotted
  every quarter for forensic replay.
- Every `compustat_q.csv` row carries a `proposal_id` that keys into
  `proposals.jsonl` — the full "why is this row what it is" chain is
  traceable to the LLM's structured action + prose justification.

## License

MIT. See LICENSE.
