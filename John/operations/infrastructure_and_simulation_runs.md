# LLM Firm Lab — Infrastructure & How We Run Simulations

High-level reference for **information architecture**, **runtime stack**, and **execution workflow**. Details of individual modules live in `README.md` and `docs/SIMULATION_SUMMARY.md` at the repo root.

---

## 1. What the infrastructure is for

The lab runs a **multi-agent corporate-finance simulation**: LLM-backed **firms** and **institutions** (auditors, analysts, SEC, banks, equity market, governance, M&A, etc.) interact in a **GAAP-consistent** economic world. The engine **adjudicates** structured decisions, updates **canonical state**, and exports **research-style panels** plus **audit trails** for each run.

---

## 2. Logical architecture (layers)

| Layer | Role |
|--------|------|
| **Configuration** | YAML run files under `config/` (firm count, quarters, seed, feature toggles, model roster). Scenario packs under `scenarios/` set heterogeneous founding conditions (e.g. biotech vs mature vs distressed). |
| **Orchestration** | A **quarterly pipeline** (~20+ phases) sequences macro, IPO, M&A, surveillance, firm decisions, clamping, accounting, markets, financing, covenants, enforcement, settlement, snapshots, and annual-only steps (audit, 10-K-style reports, board governance). |
| **Agents** | Each role produces **structured actions**; the engine applies rules, feasibility **clamping**, and accounting—LLMs do not directly post journal entries. |
| **LLM backend** | Primary path uses **OpenRouter** (broad model access); optional keys and **mock** mode for tests without external calls. |
| **State & I/O** | Canonical **`WorldState`** (and per-quarter **pickle snapshots** for resume/replay). Run outputs under `outputs/<run_id>/`. |
| **Downstream** | `data/` can accumulate stacked panels across runs; `scripts/` and `app/` support regressions, meta-analysis, and Streamlit exploration. |

This is a **single Python codebase** driven from the package entrypoint (`python -m src …`). Design docs may also describe a distributed HTTP-per-agent layout; the **documented operational path** in this repo is the integrated engine described in the root `README.md`.

---

## 3. Information architecture (who sees what)

Enforced when building each agent’s **context package** (summarized from `docs/SIMULATION_SUMMARY.md`):

- **Public** — Competitor prices, shares, generations, equity prices, published revenue and aggregate R&D, industry gazette, macro, analyst consensus.
- **Private (own firm + environment)** — Cash, full balance sheet detail, unit economics, R&D split, capability/brand, internal reports, board materials, CEO holdings.
- **Noisy public (optional)** — Peer signals observed with noise; **interlocking directors** can reduce effective noise (information leak channel).
- **Unobserved (environment only)** — Hidden demand/taste structure, simultaneous private data of all firms, manipulation truth until detection.

Every exported accounting row can carry identifiers (e.g. **`proposal_id`**) that link to **`proposals.jsonl`** for full provenance.

---

## 4. How we run simulations

### 4.1 Prerequisites

- **Python 3.10+**
- Dependencies: `pip install -r requirements.txt`
- **API keys** in `.env` at repo root, e.g. `OPENROUTER_API_KEY` (primary); others optional per config.

### 4.2 Commands (from root `README.md`)

```bash
# Smoke test — mock agents, no external LLM calls
python -m src run --config config/test_stage12_mock.yaml --mock

# Short live validation run (example: 3 firms × 4 quarters; cost ~tens of cents)
python -u -m src run --config config/validation_v15_theta.yaml

# Resume from a saved quarter snapshot
python -m src run --config config/my_run.yaml --restart-from outputs/<run_id>/snapshots/Q<N>.pkl
```

Custom runs: copy or edit a YAML under `config/`, set `n_firms_initial`, `n_quarters`, `seed`, and feature toggles (`RunConfig` / README examples), then:

```bash
python -m src run --config config/my_run.yaml
```

### 4.3 Post-run tools

```bash
python -m streamlit run app/dashboard.py
python -m streamlit run app/config_builder.py
python scripts/baseline_regressions.py --runs <run_id>
python scripts/meta_analysis.py
```

---

## 5. What each run produces (`outputs/<run_id>/`)

Typical artifacts:

- **WRDS-style CSVs** — e.g. quarterly fundamentals (`compustat_q.csv`), executive comp, audit analytics, analyst forecasts, restatements, turnover, debt facilities, covenant violations, insider trades, activism, crosswalks, etc. (full list in `README.md` / intended `docs/datasets.md`).
- **Six JSONL audit trails** — proposals, negotiations, balance-sheet checks, broker queries, peer observations, per-call LLM telemetry.
- **Cost summary** — tokens and USD by model and role.
- **Snapshots** — `snapshots/Q*.pkl` for forensic replay and `--restart-from`.
- **Narratives** — per-firm board minutes, reports, and similar markdown under the run’s firm folders.

---

## 6. Repository map (where things live)

| Path | Purpose |
|------|---------|
| `src/` | Simulation engine (orchestrator, accounting, agents, types, telemetry, snapshots). |
| `config/` | Run YAMLs and model roster. |
| `scenarios/` | Scenario definitions for firm heterogeneity. |
| `tests/` | Unit/integration tests (including reproducibility under mock). |
| `app/` | Streamlit dashboard and config builder. |
| `scripts/` | Batch analysis (regressions, meta-analysis, backfills). |
| `outputs/` | One directory per run ID. |
| `data/` | Optional cross-run stacked panels and indices. |
| `docs/` | Design summaries (`SIMULATION_SUMMARY.md`, architecture notes). |
| `analysis/` | Paper, figures, Obsidian notes. |

---

## 7. Reproducibility (expectations)

- **Mock runs** — Intended to be **byte-reproducible** for a fixed seed (see `tests/test_reproducibility.py` when present).
- **Live LLM runs** — **Not** bitwise reproducible; full **structured history + snapshots** support qualitative and quantitative replay of what actually happened.

---

*Draft aligned with root `README.md` and `docs/SIMULATION_SUMMARY.md` (Wave θ+ / April 2026 narrative). Update this file if the entrypoint or output layout changes.*
