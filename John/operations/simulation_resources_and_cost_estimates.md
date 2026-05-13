# Simulation resources & cost estimates (including 100-run planning)

What you need to run the lab **live** (paid LLM inference), how dollars are tracked, and how to extrapolate to **many repeated runs**—including **100×** the same configuration.

---

## 1. Required resources

### 1.1 Accounts & API access

| Resource | Purpose |
|----------|---------|
| **[OpenRouter](https://openrouter.ai/)** account + billing | Primary backend documented in the repo (`OPENROUTER_API_KEY`). Model IDs in YAML look like `mistralai/mistral-small-24b-instruct-2501`, `deepseek/deepseek-v3.2`, etc. |
| **Credits / payment method** on OpenRouter | Charges accrue per token; pricing follows OpenRouter’s live model cards (the simulator can pull pricing at run start when `cost_telemetry_enabled: true`). |
| **`MINIMAX_API_KEY`** (optional) | README lists optional MiniMax; only needed if configs route agents to that backend. |

Environment: store keys in a **`.env`** at the repo root (or export in the shell before `python -m src run`).

### 1.2 Compute & software

| Resource | Notes |
|----------|--------|
| **Python 3.10+** | Stated in README. |
| **Dependencies** | `pip install -r requirements.txt` (when `requirements.txt` is present in your checkout). |
| **Disk** | Each run writes `outputs/<run_id>/` (CSVs, JSONL, optional `snapshots/*.pkl` ~order **1 MB per quarter** per design notes—plus narratives). **100 runs** can mean **tens of GB** if snapshots and full traces are kept; plan retention or archive cold storage. |
| **RAM / CPU** | Mostly orchestration + I/O; **wall time** is dominated by **LLM latency**, not local FLOPs. `parallel_firm_decisions: true` reduces calendar time by overlapping firm calls. |
| **Network** | Stable connection for OpenRouter; default LLM timeout in config is **180 seconds** per call. |

### 1.3 Configuration artifacts

| Resource | Purpose |
|----------|---------|
| **`config/*.yaml`** | Run definition: `n_firms_initial`, `n_quarters`, `seed`, feature toggles, per-agent models. |
| **`scenarios/*.yaml`** (optional) | Heterogeneous founding conditions when `scenario:` is set. |

---

## 2. How spend is measured in-project

With **`cost_telemetry_enabled: true`** (default in `RunConfig`):

- The run may call OpenRouter’s **pricing API** once at startup to label costs.
- Every LLM call is logged (e.g. **`llm_calls.jsonl`**).
- **`outputs/<run_id>/cost_summary.txt`** aggregates **call counts, tokens, estimated USD**, and breakdowns by **model** and **`agent_role`**.

**Important:** the dollar line is an **estimate** from then-current OpenRouter pricing and recorded token counts—not a substitute for your **actual OpenRouter invoice** (promotions, routing, cache, or price changes can differ slightly).

---

## 3. What drives cost (order of impact)

Roughly **more LLM calls × larger contexts × pricier models ⇒ higher $**.

| Knob | Effect |
|------|--------|
| **`n_quarters`** | Nearly linear in time horizon for recurring per-quarter agents (firms, env, markets, analysts, …). |
| **`n_firms_initial` / max firms / entry** | More firms ⇒ more firm-scoped calls per quarter. |
| **`three_llm_board_enabled`** | Code comments: **~4×** governance LLM cost vs single-call governance (CEO/CFO/comp + synthesis). |
| **`pe_lifecycle_enabled`** | Comment in `RunConfig`: order **~$0.30 extra per 8Q at 5 firms** (PE evaluation calls dominate). |
| **`strategic_planning_enabled`** | Comment: order **~$0.02/firm/year** additional. |
| **`ma_enabled`** | Extra M&A bidder / auction / raise logic → more calls. |
| **`data_broker_enabled`** + high `data_broker_max_queries_per_agent_per_quarter` | More broker-tagged work. |
| **Model mix** | Large reasoning models (e.g. high-parameter chat models) vs small instruct models can move **$/1M tokens** by an order of magnitude. |
| **`--mock`** | **$0** API spend (tests / debugging); not valid for research samples you care about statistically. |

---

## 4. Empirical price anchors (this repo’s own runs)

These are **real `cost_summary.txt` totals** already on disk—use them as **anchors**, then scale.

| Profile (indicative) | Estimated cost (USD) | Scale notes |
|----------------------|----------------------|-------------|
| README “short live” **3 firms × 4Q** (Wave θ validation) | **~$0.03** | Documented in root `README.md` (~45 min wall time). |
| **`config/validation_cost_1y.yaml`**: **5 firms × 4Q**, rich toggles, **1-LLM** board | **~$0.047** | Example: `outputs/run_1776797447/cost_summary.txt` — **136** calls, **~353k** tokens. |
| **Single very large run** (many firms, planning, PE/M&A/governance-heavy) | **~$1.09** | Example: `outputs/run_1777670848/cost_summary.txt` — **3,465** calls, **~10.6M** tokens, **~21 h** wallclock. |

**Sanity check:** API spend is **not** proportional to wall time alone—slow models burn **hours** while a **flash** model might finish faster with different $/token.

---

## 5. Estimating cost for **100 runs**

### 5.1 Recommended procedure (most accurate)

1. Fix the **exact YAML** you will use for the study (including `seed` **policy**: 100 different seeds vs repeated seeds—see below).
2. Run **once** on that YAML:  
   `python -u -m src run --config config/<your_study>.yaml`
3. Open **`outputs/<run_id>/cost_summary.txt`** and read **`Estimated cost:`**.
4. **Multiply by 100** for a first-order budget:  
   **`budget_usd ≈ 100 × cost_one_run`**.

Add **~10–25% contingency** for:

- OpenRouter **price drift** or model reroutes  
- **Longer outputs** in some seeds (token variance)  
- Retries after timeouts  

### 5.2 Quick scenarios (using anchors above)

| If one run looks like… | ×100 (point estimate) | ×100 + ~20% contingency |
|------------------------|----------------------|-------------------------|
| README 3×4 validation | **~$3** | **~$3.60** |
| `validation_cost_1y` 5×4 | **~$4.7** | **~$5.6** |
| “Full” long-horizon / many-firm run ≈ **$1.09** each | **~$109** | **~$131** |

These brackets are **not** upper bounds—**custom configs** (80 quarters, 15+ firms, 3-LLM board + PE + M&A + expensive models) can exceed the **$1/run** class easily.

### 5.3 Time budget for 100 runs

- **Sequential:** `100 × wallclock_one_run` (e.g. 45 min → **~75 hours**; 21 h → **~87 days** continuous).
- **Parallel:** if you run **K** machines with **K** different seeds, divide **wall** by ~K (watch **OpenRouter rate limits** and cost caps).

Store **`run_id`** and **`seed`** in a ledger (CSV or `data/run_index.csv` patterns) so runs are traceable.

---

## 6. Seeds, reproducibility, and billing

| Mode | API cost | Use case |
|------|----------|----------|
| **`--mock`** | $0 | CI, wiring tests, byte-reproducible checks. |
| **Live, varying `seed`** | Full ×100 | Monte Carlo–style distribution over LLM stochasticity. |
| **Live, same `seed`** | Still charged **100×** | You pay for every inference; stochastic backends may still differ run-to-run. |

---

## 7. Cost-control checklist before a 100-run campaign

- [ ] Turn off features you do not need for the research question (e.g. `three_llm_board_enabled: false`, `pe_lifecycle_enabled: false`, `ma_enabled: false`).  
- [ ] Prefer **`config/validation_cost_1y.yaml`**-style **pilot** to measure *your* YAML.  
- [ ] Set **OpenRouter budget alerts** / credit limits.  
- [ ] Confirm **`cost_summary.txt`** and **`llm_calls.jsonl`** are retained for audit.  
- [ ] Plan **disk** for 100× outputs or symlink/archive policy.  

---

## 8. Related docs

- [John/infrastructure_and_simulation_runs.md](infrastructure_and_simulation_runs.md) — how runs are executed and where artifacts live.  
- Root **`README.md`** — quick start and feature toggles.  
- **`src/config.py`** — authoritative defaults and inline comments on marginal cost of PE, strategic planning, 3-LLM board.  

---

*Figures in §4 are copied from specific `outputs/run_*/cost_summary.txt` files in this workspace; re-measure after changing models or YAML.*
