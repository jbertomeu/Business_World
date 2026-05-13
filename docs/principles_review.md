# Simulation Review Against CLAUDE Industry Simulation Principles

**Updated: Wave ζ + η complete.**

Reviewing the current codebase (>6,000 LoC across ~50 modules, 21 WRDS-style CSVs + 4 JSONL audit trails + snapshots, 263 tests passing) against the 20 principles in `CLAUDE_industry_simulation_principles.md`.

See `architecture.md` for the layered architecture. See `datasets.md` for the output-file reference.

---

## 1. Principle-by-principle scorecard

Scale: 🟢 solid · 🟡 partial · 🔴 violating · ⚠️ intermittently broken

| # | Principle | Status | Evidence |
|---|-----------|--------|----------|
| 1 | Canonical world state | 🟢 | `WorldState` + `FirmState` in `types.py`; all mutations via `evolve()`. Env agent is the only omniscient reader. Snapshots pickle full state including RNG. |
| 2 | Modular architecture | 🟢 | ~30 `_enabled` toggles in `RunConfig`; each module (sec, auditor, activist, ma, scenario, etc.) wired through optional kwargs on `run_quarter`. All-off = deterministic baseline. |
| 3 | Emergent behavior / explicit institutions | 🟡 | LLM agents produce decisions; institutional rules are hard-coded (accounting, vesting, tax, GAAP). **Gap:** (a) mock mode uses deterministic agents by design (cheap reproducible tests); (b) live-mode LLM-failure fallback now carries forward prior-quarter flows instead of hardcoded constants (post-fix: Wave θ). Remaining yellow is structural: mock-mode fallbacks exist by design. All non-LLM rows tagged via `decision_source` for filtering. |
| 4 | Structured actions only | 🟢 | Every agent's decision flows through `Action`/`ActionResult` into `proposals.jsonl`. Action types across **12** agent classes: firms, IB, CB, auditor, activist, SEC, governance, M&A, earnings, analysts, **environment (`resolve_market`), equity_market (`price_equity`)** — last two added in Wave θ++ after Codex audit flagged the gap. |
| 5 | Validation · adjudication · consequence | 🟢 | Clamping is the firm-decision adjudicator; M&A auction is the bidder adjudicator; target board vote is the acquisition adjudicator; auditor fee haggle is the fee adjudicator. Structured `RejectionEvent`s in action log. |
| 6 | Correct bookkeeping | 🟢 (instrumented) | BS identity checked at every phase boundary; drift events logged to `bs_violations.jsonl` with full BS snapshot. CFO reconciles exactly. Mock + v11/v12 live runs had 0 violations. |
| 7 | Realistic information partitions | 🟢 | `_build_firm_info_package` enforces partition; each firm sees own private + shared public. Env is explicitly omniscient. Analysts/SEC/auditor/activist see only public data. |
| 8 | Persistent incentives, contracts, memory | 🟢 | `CEOContract`, `DebtFacility`, `Covenant`, `StockGrant`, `ceo_incarnation`. Typed memories: `FirmBelief` (EWMA-updated), `ActivistMemory` (campaigns + effectiveness), `AuditorMemory` (client history), `SECMemory` (firm priors + aging). All pickled with snapshots. |
| 9 | Shared markets | 🟢 | One product market, one equity market, one debt market, shared macro, shared gazette. Analyst consensus aggregated and shared. |
| 10 | Protocolized bargaining | 🟢 | **5 LLM-driven negotiation sites**: covenant waiver (1-round), debt pricing (1-round), activist campaign (2-round LLM-driven), M&A auction (multi-bidder LLM-driven raises), audit fee (LLM-driven haggle). All logged to `negotiations.jsonl` with per-round offer history. |
| 11 | Temporal discipline | 🟢 | Every object has `quarter`, `fyear`, `fqtr`, maturity dates, vesting offsets, grant quarters. |
| 12 | Rich but bounded context | 🟢 | Firm prompts include analyst consensus + activist + env notes + ceo holdings. **Measured:** board prompt = 1,846 tokens, firm prompt = 1,567 tokens on a mid-run state (Q4, with peers + gazette + 4-quarter memory). 11.5% saturation on phi-4 (tightest 16k model); < 2% on all 128k+ backends. No splitting required. |
| 13 | Quantitative reasoning | 🟢 | `analyst.py`, `data_analyst.py`, `data_broker` + templates. Models can query WRDS panels. |
| 14 | Research-grade data generation | 🟢 | 21 WRDS-style CSVs + 4 JSONL audit trails. Snapshots allow mid-run resume. Documented in `datasets.md`. |
| 15 | Persistent identifiers | 🟢 | `firm_id` + `incarnation`, `ceo_incarnation`, `facility_id`, `grant_id`, `proposal_id`. `crosswalk.csv` links all entities (firm, ceo, facility, security, grant, product, **director**). Wave θ populates a shared director pool with interlocking seats (n=10 → 30 seated directors, mean 1.33 seats/director, cap 3 seats/director). **Interlocks generate info-leak**: observer firms with shared directors see peer signals with noise scaled 1/(1+n_shared) — testable prediction on belief accuracy. |
| 16 | Reproducibility + audit trail | 🟢 | Seeded mock runs byte-reproducible. Live runs snapshot every quarter → `outputs/<run>/snapshots/Q{N}.pkl`. `--restart-from` CLI flag. Full proposal audit trail in `proposals.jsonl`. |
| 17 | Latent / signal / report separation | 🟢 | `manipulation_amount` vs `niq`; `noisy_signals_enabled` adds Gaussian noise to peer observations + macro signals; **interlocked directors halve noise** (Wave θ); analyst consensus injected as public belief; `FirmBelief` EWMA-updates from noisy observations. |
| 18 | Coherent scenario generation | 🟢 | `scenarios/` library with 3 shipped: `biotech_early_stage`, `mature_industry`, `distressed`. Per-firm heterogeneous founding conditions. Backward-compatible uniform default when unset. |
| 19 | Modular role-to-model assignment | 🟢 | `config/model_roster.yaml` supports per-role model overrides. |
| 20 | Usable control layer | 🟢 | Streamlit config builder + 15-tab dashboard (time series, ratios, CEO, turnover, debt, analysts, data integrity, EM heatmap, firm compare, cross-run dist, auditor timeline, proposals, negotiations, regressions, crosswalk). CLI with `--config`, `--seed`, `--mock`, `--restart-from`. Batch runner + meta-analysis scripts. |

**Net: 19 🟢, 1 🟡, 0 🔴, 0 ⚠️** (confirmed by Codex independent audit:
28/33 CONFIRMED across 33 specific claims; see `CODEX_AUDIT_FILLED.md`).

---

## 2. Anti-pattern check

| Anti-pattern | Present? | Evidence |
|---|---|---|
| Role-play realism | No | Narratives surface in board minutes / MD&A / analyst notes but are downstream of structured state, not causing it. |
| Fake emergence | No (labeled) | Fallback deterministic paths exist (mock firm, deterministic bridge) but carry `decision_source="fallback"` / `"mock"` tags. Research filtering is trivial. |
| Omniscient prompts | No | Information partition enforced via `_build_firm_info_package`. |
| Accounting as decoration | No | BS identity enforced at every mutation phase; violations trigger structured log. |
| Soft overrides | No | Every clamp produces a structured `RejectionEvent`. |
| Dataset-first | No | 21 CSVs derived from underlying latent world state. |
| Model dogmatism | No | Role-specific model assignments work. |

---

## 3. Remaining follow-ups

### Minor (non-blocking for research use)

1. ~~**3-LLM board committee**~~ — **DONE (Wave θ+)**. `make_governance_agent_3llm()` spawns 3 parallel perspective calls (CEO / CFO / comp-committee) + synthesis. Gated by `three_llm_board_enabled` (default OFF; 4× governance cost when ON).
2. ~~**Director entity populated**~~ — **DONE (Wave θ)**. Shared director pool with interlocking seats emitted to `crosswalk.csv`. `director_lifecycle_enabled` (default OFF) adds annual refresh + default-triggered departures → `director_turnover.csv`.
3. ~~**Principle 12 (context discipline)**~~ — **MEASURED (Wave θ)**. Board = 1,846 tokens, firm = 1,567 tokens on mid-run. 11.5% of phi-4's 16k. No splitting needed.
4. ~~**Principle 3 (fake emergence)**~~ — **PARTIAL (Wave θ)**. Live-mode LLM-failure fallback now carries forward prior-quarter flows (was hardcoded constants). Mock-mode fallbacks remain by-design for cheap reproducible testing.

### New infrastructure (Wave θ+)

5. **Cost/token telemetry with $ pricing** — OpenRouter pricing API fetched at run start; per-call JSONL + per-model + per-agent-role breakdowns in `cost_summary.txt`. Toggle: `cost_telemetry_enabled` (default ON).
6. **Interlock info leak** — peer observations noise SD scales by `1/(1+n_shared_directors)`. Testable prediction registered as Spec 12 (interlock → belief accuracy). v15 preliminary: N=24, coefficient not significant — multi-seed run needed for power.
7. **`actor_class` in proposals.jsonl** — canonical class tags (firm / auditor / analyst / sec / etc.) auto-derived from actor_id.
8. **Regression specs 10-12** — matched-firm pricing, disclosure tone → next-year return, interlock → belief accuracy.

### Research scale-out

5. **Real-LLM multi-seed panel** — 10 seeds × validation_full ≈ 20h wall-clock. Would produce first research-grade cross-run panel.
6. **More regression specs** — currently 9 specs: pay-performance, leverage, covenant→default, CEO turnover logit, EM detection, analyst bias, event-study SEC / restatement / turnover. Possible additions: matched-firm pricing study, disclosure-tone analysis.

---

## 4. How to validate the simulation holds together

Run this sequence:

```bash
# Unit tests
python -m pytest tests/ -q              # 263 tests

# Mock smoke (0 external API calls)
python -m src run --config config/test_stage12_mock.yaml --mock

# Live validation (requires API key)
python -u -m src run --config config/validation_full.yaml

# Or with a scenario
# (edit config to add: scenario: biotech_early_stage)

# Post-run analysis
python scripts/baseline_regressions.py --runs <run_id>
python scripts/meta_analysis.py
python -m streamlit run app/dashboard.py
```

If all of the above return without errors and `bs_violations.jsonl` is empty
or explains its contents, the simulation is holding together.
