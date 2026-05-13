# LLM Firm Lab — Active Roadmap

Persisted to survive across sessions. Updated each time a wave ships.

See also: [[architecture]], [[principles_review]], [[datasets]], [[../CHANGELOG]].

---

## Status Legend
- ✅ **DONE** — implemented, tested, committed
- 🟡 **IN PROGRESS** — partial work; see notes
- ⬜ **TODO** — not started
- 🔵 **VALIDATION PENDING** — done but needs live LLM run to confirm behavior

---

## Current state (Wave λ, April 2026)

**303 tests passing · ~55 modules · ~8,500 LoC · scorecard 19🟢 / 1🟡** (audit-confirmed).

**Waves ι + κ + λ now comprise a complete lifecycle simulation**:
- **ι**: scenario-driven industry economics (TAM, demand, affordability, outside-option dynamics)
- **κ**: firms plan forward 5 years + face variance accountability
- **λ**: patient private capital funds the ramp; public markets price the eventual IPO

21 WRDS-style CSVs + 6 JSONL audit trails per run. Validation_full ≈ $0.03
USD per 4Q × 3-firm run. All "richness" features user-toggleable via YAML
config. See [[../CHANGELOG]] for the per-wave breakdown.

### Wave α → θ+ summary table

| Wave | Focus | Ship status |
|------|-------|------|
| α | BS-identity invariants · `decision_source` tag | ✅ |
| β | Structured `Action` / `ActionResult` / `ActionLog` | ✅ |
| γ | `Negotiation` primitives · 5 LLM-driven bargaining sites | ✅ |
| δ | Per-Q snapshots · `proposals.jsonl` audit trail · `--restart-from` | ✅ |
| ε | `FirmBelief` + EWMA · noisy peer signals · typed agent memories | ✅ |
| ζ | Scenario library (3 shipped) · identifier graph (`crosswalk.csv`) | ✅ |
| η | Event-study regressions (SEC · restatements · turnover) | ✅ |
| θ | Directors + interlock info-leak · 3-LLM board committee · cost telemetry ($ via OpenRouter) · `actor_class` · `directors_enabled` / `director_lifecycle_enabled` / `three_llm_board_enabled` / `cost_telemetry_enabled` toggles | ✅ |
| θ+ | Per-observation log (`peer_observations.jsonl`) · factory telemetry coverage · `actor_class` backfill · at-run-end BS validator | ✅ |
| θ++ | Codex audit (28/33 CONFIRMED) · env + equity `Action` logging · 12 telemetry tests · Spec 12 archived | ✅ |
| ι | Scenario-driven economics: `IndustryCharacter` narrative + `MarketParams` (10 tunable demand knobs) · industry-agnostic prompts · live `market_signals` · new `declining_industry` scenario | ✅ |
| κ | Strategic planning: `StrategicPlan` + `PlanVariance` · 5y forward budgets authored at Q0 + every 4Q · variance triggers re-plan · `strategic_plans.csv` | ✅ |
| λ | PE + IPO lifecycle: 3 PE funds · pitch → evaluate → auction → IPO via prospectus · `pe_rounds.csv` · `prospectus/*.md` · bargain-purchase GAAP · full `founded → public` lifecycle | ✅ |

### Spec 12 (interlock → observation accuracy) — **confirmed**

With per-observation data, the interlock info-leak mechanism produces a
statistically significant hypothesis-confirming result:
- n_shared_directors coef = **−0.0484, p=0.001** at N=60
- Monotonic decay: 0 shared → 18.1% |err|, 1 → 8.7%, 2 → 6.4%, 3 → 3.1%

---

## Next candidates (not yet shipped)

- **10-seed multi-seed panel** — validation_full × 10 seeds; ~$1-2 USD,
  4-8h wall-clock. First controlled cross-run dataset.
- **Customer-supplier network** — inter-firm COGS flows (firm A's COGS
  feeds firm B's revenue). Enables contagion regressions.
- **Director A/B comp experiment** — same seed × `three_llm_board_enabled`
  toggled. Deterministic causal test of committee-structure effect on
  comp decisions. ~$0.15 USD for 2 runs.
- **3-LLM firm board / CFO / CEO voices at the decision step** — symmetry
  with governance committee. Substantial (3× firm cost per quarter).
- **Network centrality as dataset + regression spec** — degree, betweenness
  per firm from interlock graph; does higher centrality predict pricing
  accuracy, analyst coverage, cost of capital?

---

## Recently Completed (v0.5 major expansion)

| Wave | Feature | Status |
|------|---------|--------|
| 0 | Fix pre-existing bugs (config truncation, state_ref check, dead code) | ✅ |
| 1 | Earnings management (manipulation field + cumulative stock) | ✅ |
| 2 | Earnings announcements + sell-side analysts | ✅ |
| 3 | SEC agent + restatements | ✅ |
| 4 | Auditor pool + CEO governance | ✅ |
| 5 | M&A mechanics + 7 WRDS datasets wired to disk | ✅ |
| 6 | Data Broker (NL queries, 3 modes: template_only, combo, freeform) | ✅ |

---

## Active Roadmap (v0.6 — realism + emergent behavior)

### ✅ Stage 1: De-hardcode prompts (DONE)
Replaced specific numerical rules in prompts with qualitative guidance:
- equity_market: "30x P/S ceiling" → "typical ranges with narrative"
- investment_bank: "25% dilution cap" → "consider impact, you judge"
- commercial_bank: rate categories → open judgment
- environment: "≤15% share change" → "markets sticky, changes have causes"

### ✅ Stage 2a: EM detection → environment LLM (DONE)
- Removed `detection_probability()` sigmoid call from orchestrator
- Environment agent (omniscient) now sees firm manipulation state and produces `detection_tips` via its own judgment
- Tips flow through `state.pending_detection_tips` to next quarter's SEC call

### ✅ Stage 2b: Distressed bridge rate → LLM (DONE)
- Removed hardcoded `risk_free + 4%` penalty rate
- New `make_emergency_bridge()` agent on commercial_bank.py
- LLM judges both approved amount and rate based on firm condition
- Deterministic fallback preserved for mock mode

### ✅ Stage 6: Analyst FSA upgrade (DONE)
- 4 new templates in `data_templates.py`:
  - `dupont_decomposition` — ROE = NPM × AT × Leverage
  - `rnoa_decomposition` — Penman-style RNOA + NBC + NFL
  - `residual_income_valuation` — BV + PV(RI) + terminal
  - `peer_multiple_analysis` — LLM picks multiple + peer exclusions
- Analyst personalities rewritten:
  - analyst_1 "Fundamentalist" — FSA + DCF
  - analyst_2 "Comparables Specialist" — peer selection, multiple choice
  - analyst_3 "Residual Income Modeler" — BV anchor + RI
- Output schema expanded: `financial_snapshot {roe, rnoa, nbc, nfl, ...}`, `forecast_drivers`, `valuation_method_detail`, `risks`, longer narrative
- Equity market now sees full analyst notes (ratios + methodology + risks), not just target prices
- `analyst_forecasts.csv` gained 11 new columns

### ✅ Stage 3a: Debt bookkeeping — data model + pure Python module (DONE)
- `types.py`: `Covenant`, `DebtFacility`, `CovenantViolationEvent` dataclasses
- `FirmState` fields: `debt_facilities`, `covenant_violation_history`
- Config toggles: `debt_covenants_enabled`, `convertible_debt_enabled`, `max_active_facilities_per_firm`
- `src/debt_management.py` (450 lines, pure Python, no LLM):
  - `add_facility`, `prepay_facility`, `draw_revolver`
  - `amortize_quarter` (interest + scheduled principal + maturity)
  - `compute_ratios`, `test_covenants` (deterministic)
  - `apply_waiver`, `apply_amendment`, `apply_acceleration`
  - `convert_facility` (convertible → equity)
  - `consistency_check` (invariants)
- Verified end-to-end with manual test: facility creation, amortization, covenant testing, waiver, conversion all work; consistency invariants pass.

---

## Current state (post-Stage-7 + accounting audit)

All v0.6 stages and post-audit fixes shipped. 146 tests passing.
Validation runs use `config/validation_full.yaml` (all toggles on, including
`debt_covenants_enabled`, `working_capital_decisions`, `bad_debt_enabled`,
`annual_reports_enabled`).

Per-run outputs include:
- 15 WRDS-style datasets covering the canonical research databases:
  Compustat (quarterly + annual funda), ExecuComp, Audit Analytics, I/B/E/S,
  First Call Guidance, ExecuComp transitions, AA Restatements, DealScan
  (Facility + Covenants), Chava/Roberts/Nini covenant-tests panel, Nini
  violation events, Mergent FISD, custom bad-debt panel, 10-K disclosure.
- Per-firm artifacts: board minutes, R&D reports, product specs, 10-K-style
  annual reports (markdown).
- Cross-run accumulation: `data/compustat_all.csv` (quarterly funda), `data/compustat_a_all.csv` (annual funda), `data/run_index.csv`.

### Validation inspection checklist
After each `python -u -m src run --config config/validation_full.yaml`:
- `outputs/run_XXXX/compustat_q.csv` + `compustat_a.csv` — firm trajectories. Look for: realistic P/S (not 123x), sensible dilution (not 5B shares at $0.01), differentiation between firms
- `outputs/run_XXXX/analyst_forecasts.csv` — populated `roe`, `rnoa`, `npm` etc. and longer `narrative` text
- `outputs/run_XXXX/audit_analytics.csv` + `annual_reports.csv` — opinion calibration (not adverse on winners), MD&A populated
- `outputs/run_XXXX/firms/firm_X/board_minutes_Q7.md` — memory threading should not say "first board meeting"
- `outputs/run_XXXX/firms/firm_X/annual_report_FY####.md` — 10-K-style markdown rendered
- `outputs/run_XXXX/scorecard.txt` — dilution-adjusted NPV format
- `outputs/run_XXXX/debt_facilities.csv` + `covenant_violations.csv` — IB picks sensible covenants for negative-EBITDA firms (post-F8 fix), violations resolve through waive/amend not just accelerate

### ✅ Stage 3b: Orchestrator wiring for debt covenants (DONE)
Added 3 new phases to `run_quarter`, all guarded by `config.debt_covenants_enabled`:
- **Phase 6.5** `amortize_quarter()` — accrues interest + applies scheduled principal on each active facility, right after accounting
- **Phase 7.5** `test_covenants()` — tests each facility's quarterly covenants against TTM EBITDA + TTM interest from compustat rows; pushes violations to `state.pending_covenant_violations` for Stage 3c resolution
- **Phase 7.6** `consistency_check()` — logs any BS invariant breaches as warnings
- Added `WorldState.pending_covenant_violations: list` field
- When toggle off: all 3 phases skip entirely. Verified: 4Q smoke run with toggle off is identical to pre-Stage-3b behavior.
- Added `tests/test_debt_covenants.py` (17 tests — 3a facility lifecycle, waiver/amendment, conversion, consistency; 3b orchestrator wiring including no-op, active, and toggle-off cases). All 105 tests pass.

Still to coordinate in Stage 3c: accounting.py currently accrues interest on aggregate `firm.long_term_debt`, which will double-count once facilities carry the debt. Stage 3c's investment-bank origination path must decide whether to (a) wrap new debt as facilities and have accounting skip facility-held debt for legacy interest calc, or (b) keep legacy interest accrual and have amortize_quarter only do principal.

### 🟡 Stage 3c: LLM negotiation prompts (single-round DONE; 2-round deferred)
**Done (single-round):**
- `investment_bank.py` extended with `SYSTEM_PROMPT_WITH_COVENANTS` — when `debt_covenants_enabled`, the bank outputs a `facility_structure` (facility_type, amortization_type, maturity_quarters, covenants list, conversion terms) in addition to the standard approval fields.
- `make_investment_bank(...)` now takes `debt_covenants_enabled=` flag; when True uses the extended prompt.
- Orchestrator Phase 7b (investment bank) now wraps approved term debt as a `DebtFacility` via `debt_management.add_facility()` when structure is present. Legacy lump-sum path preserved when structure is absent (backward compat).
- `make_violation_resolver(...)` added in `commercial_bank.py` — takes list of pending violations + firms dict, returns list of resolutions (waive/amend/accelerate with reasoning).
- Orchestrator Phase 7.7 applies resolutions via `apply_waiver` / `apply_amendment` / `apply_acceleration`; records `CovenantViolationEvent` in `firm.covenant_violation_history`; clears the pending queue.
- `cli.py` wires both agents when `debt_covenants_enabled`; passes None in mock mode.
- Tests: `test_orchestrator_origination_creates_facility_from_ib_structure`, `test_orchestrator_falls_back_to_legacy_when_structure_missing`, `test_orchestrator_resolves_violation_via_waive` — 3 end-to-end orchestrator tests using stub agents.

**Deferred (2-round negotiation):**
- Full round-trip negotiation (bank proposes → firm counter → bank accepts/walks) not implemented. The firm currently accepts bank terms implicitly (by next quarter's request or decline). 2-round flow can be added via a second LLM call after IB proposal, before `add_facility`. Architecturally additive; no existing code needs changing.

Key prompt principle held: no hardcoded thresholds, fees, rate bumps, or covenant sizes — all LLM-judged. Structural bounds only: valid facility types, valid covenant types, max active facilities per firm.

### ✅ Stage 3d: WRDS debt datasets (DONE)
Added 5 builders to `src/datasets.py` with column schemas, all producing
`tic, conm, sic, datadate` WRDS-style identifier columns:
- `debt_facilities.csv` — DealScan Facility-style. One row per facility
  (every facility ever created, across all firms, including repaid/defaulted).
- `debt_covenants.csv` — DealScan Covenants. One row per (facility, covenant).
- `covenant_tests_panel.csv` — Chava/Roberts/Nini quarterly panel.
  Re-runs `compute_ratios` against each firm's compustat history and emits
  one row per firm × quarter × covenant with measured_ratio + violated_flag.
- `covenant_violations.csv` — Nini et al. violation events. Reads
  `firm.covenant_violation_history` (populated by Stage 3c resolver).
- `bond_issuances.csv` — Mergent FISD. Subset of facilities filtered to
  `facility_type in {bond, convertible_bond}`. Includes `is_convertible`
  flag and conversion terms.

All 5 wired in `output_organizer._write_wrds_datasets` and always written
(empty CSV with header-only when no facilities exist, so researcher always
sees the schema). CLI summary updated: "12 WRDS datasets".

Tests: 5 new builder tests in `tests/test_debt_covenants.py` (25 debt tests
total; 113 tests overall pass). `scripts/rebuild_database.py` left for now
(cross-run concatenation; not critical for Stage 3 loop closure).

### 🟡 Stage 3e: Firm prompt integration (display DONE; structured `debt_requests` deferred)
**Done:**
- `prompts.py._format_debt_facilities_block(firm)` renders an informational block
  listing each active facility: facility_id, type, balance, annualized rate,
  maturity, covenants with operator + threshold + VIOLATED flag, conversion
  terms (for convertibles), status.
- `build_firm_prompt` gained `debt_covenants_enabled=False` kwarg; when True
  and firm has active facilities, the block is rendered inline in the user
  prompt after the financial position section.
- `cli.make_firm_agent` wires the toggle through.
- Tests: 3 new prompt tests in `tests/test_debt_covenants.py` (show when on,
  omit when off, skip header when no facilities). 116 tests pass total.

**Deferred:**
- New structured decision field `debt_requests: list[dict]` not added.
  Firm still uses legacy scalar `debt_request: float`; IB layer structures
  the facility via Stage 3c's extended prompt. Adding structured requests
  would let firms choose facility type and covenant preferences directly,
  but is additive and doesn't block the Stage 3 end-to-end flow.
- Full lifecycle test file (~15 tests) not built separately;
  `tests/test_debt_covenants.py` now covers 28 tests across Stages 3a/3b/3c/3d/3e.

Known coordination gap: accounting.py still accrues interest on aggregate
`firm.long_term_debt`, which double-counts against `debt_management.amortize_quarter`
once facilities exist. Workable for short validation runs but should be
resolved before long-horizon studies. Fix: either (a) gate accounting's
legacy interest calc off when `debt_covenants_enabled` and let amortize
own it entirely, or (b) have amortize skip interest and only do principal.

### ✅ Stage 4: Working capital policies (DONE)
- Firm decision fields: `payables_days_target`, `receivables_days_target`,
  `deposit_pct`, `ppe_disposal` (all optional, None = use params defaults).
- `FirmState.deferred_revenue` added + `CompustatRow.drcq` column.
- Accounting: `AP = COGS × DPO / 90`, `AR = credit_revenue × DSO / 90`,
  where `credit_revenue = revenue × (1 − deposit_pct)`. PP&E disposal reduces
  gross + accum_dep pro-rata, puts proceeds in CFI, records gain/loss on sale.
- **Simplification**: deferred_revenue balance stays 0 in v1 (deposits treated
  as immediately-earned cash revenue; the economic signal of deposit_pct is
  captured via the AR split). Richer deposit model with multi-period
  recognition lag deferred as future work.
- Environment prompt gained friction-judgment guidance when enabled.
- Firm prompt gained working-capital policy guidance block + JSON fields.
- BS identity confirmed holding with all fields active.

### ✅ Stage 8: Environment verification + IB upgrade (DONE)
- New `src/env_verifier.py` module:
  - `is_anomalous(env_outcome, recent_revs, baseline, prod_caps)` — pure-Python
    deterministic check with 4 heuristics (H1: total_demand vs recent revenue
    trend; H2: total_demand vs logit baseline; H3: any firm exceeds production
    cap; H4: market_shares sum deviates from 1.0). Returns (flag, reasons).
  - `make_env_verifier(backend)` — LLM verifier called only when anomaly_flag.
    Returns either ratification or a revised env_outcome.
  - `_deterministic_clamp(...)` — last-resort fallback when verifier LLM
    unavailable: caps each firm at production_cap, recomputes shares.
- Orchestrator Phase 5.5: anomaly check → optional LLM verification → optional
  deterministic clamp. Runs only when `env_verification_enabled=True`.
- Config toggle `env_verification_enabled: bool = False`.
- `ModelRoster.env_verifier` optional role — falls back to environment model
  if not configured. Default in `model_roster.yaml`: qwen3-235b (strong
  reasoner so verifier can credibly judge "hallucination vs legitimate move").
- Investment bank upgraded from `meta-llama/llama-4-scout` to
  `qwen/qwen3-235b-a22b-2507` (validation v2 showed scout still picked
  debt/EBITDA covenants on negative-EBITDA firms despite the F8 prompt
  guidance — needed stronger instruction-following).
- 13 new tests covering anomaly heuristics, LLM verifier ratify/revise paths,
  failure-fallback to deterministic clamp, orchestrator integration. 159 tests
  pass total.

**H5 enhancement (added after v3 launch)**: implied-revenue heuristic catches
the validation v2 case where firm priced 100x trend ($12M/unit) and env
accepted it — units stayed in range so H1-H4 missed it, but
`Σ(units × firm_price)` was 40x recent revenue. The orchestrator now passes
clamped firm prices into `is_anomalous`, which compares implied revenue to
recent quarterly revenue trend. Will activate from v4 onward.

### ✅ Stage 10: Restructuring + Env decision overrides (DONE)

**(1) Restructuring** — WRDS `rcp` support:
- RawDecisions/ClampedDecisions/QuarterFlows gain `restructuring_severance`
  (cash), `restructuring_ppe_impairment`, `restructuring_inventory_write_off`
  (scales units proportionally to preserve per-unit cost),
  `restructuring_goodwill_impairment`. Sum → `restructuring_charge` on IS
  between `oiadp` and `pi` (matches WRDS funda conventions).
- Added `rcpq` to CompustatRow, `rcp` to compustat_a annual funda.
- Prompt guidance block when `restructuring_enabled`.
- Config toggle `restructuring_enabled: bool = False`.

**(2) Env decision overrides** — firm decisions as budgets/targets:
- Env output schema gained `decision_overrides: [{firm_id, field, budgeted,
  actual, reasoning}]`. Orchestrator applies each override (whitelisted
  fields only, None skipped, int-cast for production) before accounting.
- Env prompt gets guidance: override when clearly infeasible (SGA=$0 with
  100 employees), default pass-through.
- Config toggle `env_decision_overrides_enabled: bool = False`.
- Replaces the philosophy-violating SGA/capex floors from clamping.py.

### ✅ Stage 11: CEO compensation overhaul (DONE)

**ExecuComp-accurate grant lifecycle**:
- New `StockGrant` frozen dataclass (RSU or stock_option, time-based
  vesting schedule).
- `FirmState` gains `ceo_age`, `ceo_stock_grants`, `ceo_vested_shares_held`,
  `ceo_shares_sold_cumulative`, `ceo_cash_from_sales`, `ceo_cash_bonus_ytd`,
  `ceo_retired`, `ceo_retirement_quarter`.
- `src/ceo_comp.py` module:
  - `create_grant` with FV-at-grant computation (RSU: shares × price;
    option: intrinsic + crude time-value proxy).
  - `vest_grants_this_quarter` — walks each grant's vesting_schedule;
    time-based only; RSUs flow into `ceo_vested_shares_held`.
  - `sell_vested_shares` — CEO sells at market price; proceeds go to
    `ceo_cash_from_sales`.
  - `forfeit_unvested` — on fire.
  - `accelerate_vesting_on_retirement` — on voluntary retirement, all
    unvested vests immediately.
  - `outstanding_snapshot` — ExecuComp-style holdings summary.

**Governance (annual Q4) rewritten** with open-ended comp package:
- Board decides: fire / retire / retain, base_salary_next_year,
  cash_bonus_this_year, new_rsu_grant, new_option_grant (each with custom
  vesting_schedule). No hardcoded pay ranges.
- `apply_governance_decision` returns `(firm, grant_events)` — grants
  accumulate into `state.ceo_grant_events` for the dataset.
- CEO age advances 1 per annual cycle; retirement eligible at 60,
  mandatory at 65.

**CEO sell decision**: firm prompt (when `governance_enabled`) gains
`ceo_sell_shares` integer — CEO's personal decision to sell some vested
shares this quarter (executed in Phase 11.6 after equity market prices).

**Orchestrator**: New Phase 11.6 (quarterly): vest grants + apply CEO sell.
Phase A2 (annual) now routes through the richer governance decision +
captures year-end snapshot into `state.execucomp_annual_snapshots`.

**Three ExecuComp-style datasets**:
- `execucomp.csv` (annual summary, enriched): salary, bonus, stock_awards,
  option_awards, total_comp, shares_owned_eoy, shares_sold_this_year,
  shares_sold_cumulative, cash_from_sales_cumulative, vested/unvested
  options, intrinsic value, fired/retired/hired flags. Sourced from
  `execucomp_annual_snapshots` so historical state is preserved correctly.
- `execucomp_grants.csv` (event-level, new): one row per new grant —
  grant_id, grant_date, type, shares, strike, fair_value_at_grant,
  vesting_schedule_json, first/last_vest_quarter.
- `execucomp_outstanding.csv` (annual panel, new): year-end unvested RSU,
  unvested options, vested-held, intrinsic values, grants outstanding.

**17 WRDS datasets total**.

**Audit + fixes** (4 bugs found and resolved):
1. Inventory write-off now scales units proportionally (no more zombie units).
2. Env override skips when `actual=None` (no coercion-to-0 semantic bug).
3. `execucomp.csv` now sourced from year-end snapshots so historical rows
   are preserved correctly (was previously computing from end-state firm).
4. `execucomp_outstanding.csv` same fix — proper panel data, not just
   last year.

**Tests**: 19 new tests for Stage 10-11 (restructuring IS/BS effects, env
override pass-through + null skip, grant creation/vesting/selling/forfeit/
retirement, governance flows, annual snapshot persistence). 183 tests
pass total.

### ✅ Stage 9: Deep audit + full remediation (DONE)

Four parallel audits (accounting, debt bookkeeping, feature completeness,
hardcoding/WRDS) identified ~25 issues across 6 clusters. All fixed.

**Cluster 1 — Accounting correctness:**
- B1: IS reconciliation after Step 6 — now `oiadp`, `pi`, `txt`, `ni` all
  reconcile even when bad debt + disposal gain active. BDE charged through
  operating_income; disposal gain through pretax (non-operating).
- B3: PP&E disposal fraction — removed `max(1.0, ppe_net)` floor; clamping
  already ensures disposal ≤ ppe_net so ratio is bounded.
- B4: `validate_state` + `build_compustat_row` now use explicit
  `reported_net_income` (no truthy-zero fallback). Edge case where
  manipulation exactly offsets true NI resolved.
- C1: `acoq` → `xaccq` (WRDS convention for accrued expenses).
- C2: `mkvaltq` now in $ millions per WRDS convention (was $).

**Cluster 2 — Covenant lifecycle:**
- H1: unresolved violations re-queue for next quarter's resolver instead of
  silent drop. Resolution tracking by (fid, fac_id, cov_type) key.
- H4: accelerated facilities skip amortize_quarter AND test_covenants. No
  more infinite-interest loop on accelerated-but-unpaid facilities.

**Cluster 3 — De-hardcoded behavioral rules:**
- `prompts.py` FIRM prompt stripped: price-range anchor, "invest well above
  minimum", "~2-3%/Q interest", "typically 0 while unprofitable", "2-3
  rounds", "below 4 quarters" runway rule, "PRODUCE AT OR NEAR CAPACITY"
  with $95K price anchor, 3Q/5Q/8Q cash urgency thresholds, inventory ">1.5Q"
  warning, 30% depreciation nudge.
- `clamping.py`: removed `min_sga_absolute_floor`, `min_sga_pct_of_assets`,
  `maint_capex_pct_of_ppe` behavioral floors. Only Phase-3 R&D + interest +
  taxes remain mandatory (physics + legal). Firms can now under-invest and
  face emergent consequences (brand decay, PP&E erosion).
- `env` prompt: removed `process_cogs_reduction_pct <0-0.02>` cap.
- `earnings_management.py`: sigmoid `detection_probability` deprecated
  (env LLM's `detection_tips` is the live path since Stage 2a).
- Rate clamps loosened to `[0, 1.0]` quarterly (400% annual — pure safety
  against LLM unit-confusion, no behavioral ceiling):
  - `investment_bank.py` term_rate (was `[0.01, 0.10]`)
  - `commercial_bank.py` resolver new_rate (was `[0, 0.20]`)
  - `debt_management.py` apply_amendment (was `[0, 0.20]`)

**Cluster 4 — WRDS schema expansion:**
- Added `ppegtq` (gross PP&E — critical for Sloan-accruals research).
- Added `actq` (total current assets — for current ratio).
- Added `seqq` (total stockholders' equity).
- Added `cusip` (synthetic 9-char — enables CRSP/TRACE-style linking).
- Added funda metadata flags on quarterly: `indfmt='INDL'`, `consol='C'`,
  `popsrc='D'`, `datafmt='STD'`.
- Added `sppe` (sale of PP&E) to `compustat_a` annual funda.

**Cluster 5 — Edge cases:**
- M1: `add_facility` ValueError on max_active cap now DENIES the issuance
  (no silent lump-to-LTD fallback that defeats covenant tracking).
- M2: convertible-bond coerced to bond when `convertible_debt_enabled=False`
  now STRIPS `conversion_ratio`/`conversion_price` to prevent latent
  type-confusion.
- M4: `add_facility` rejects convertibles with `conversion_ratio > 1000`
  shares per $1000 face (LLM unit-confusion guard).

**Cluster 6 — Convertible conversion trigger (F1):**
- New Phase 11.5 in orchestrator: after equity market sets the price, any
  in-the-money convertible (`equity_price ≥ conversion_price`) with
  `current`/`amended`/`in_cure_period` status auto-converts via
  `convert_facility`. Emergent: pure arithmetic check (arbitrageurs would
  force this in real markets).

**Tests**: 163 pass (was 160). Added H1 re-queue regression, H4 accelerated
no-accrual, M4 absurd-conversion-ratio rejection, rate-clamp-at-1.0.

**Validation v3 results (run_1776576488)**:
- (a) Env verifier fired Q1 with H3 (production-cap violation), revised env
  output before accounting saw it. Subsequent quarters all clean.
- (b) IB upgrade (qwen3-235b) created 4 facilities with diverse, sensible
  covenants (`min_cash_balance`, `min_liquidity`, `min_net_worth`,
  `min_interest_coverage`) — exactly the dollar-denominated picks the F8
  prompt asked for. Loaned $115M (vs $4.8M in v2). 1 waived, 1 amended,
  rest accelerated.
- **NEW BUG found and fixed**: violation_resolver returned `new_rate_quarterly=7.0`
  (LLM unit confusion: 7% annual, not 700% quarterly). `apply_amendment`
  blindly accepted, producing 2800% annual rate. Both layers now clamp to
  ≤ 0.20/Q (80% annual). Regression test added. 160 tests pass.

### ✅ Stage 7: WRDS-style annual fundamentals (DONE)
- New `compustat_a.csv` dataset mirrors WRDS `comp.funda` schema:
  funda metadata flags (indfmt='INDL', consol='C', popsrc='D', datafmt='STD'),
  funda column names (sale, cogs, ni, at, ceq — no "q" suffix), one row per
  firm × fiscal year.
- `build_compustat_a()` aggregates from `state.compustat_rows`:
  - IS / CF lines: SUM across the 4 quarters in fyear
  - BS lines: year-end (last fqtr's) snapshot
  - Identifiers carried from year-end row
- Cross-run accumulation: `data/compustat_a_all.csv` appended at run end
  (mirrors how `compustat_all.csv` accumulates quarterly data).
- 2 new tests: 4-quarter aggregation correctness + partial-year handling.
- 146 tests pass total.

### ✅ Stage 6 (post-audit): Annual reports (DONE)
- New `AnnualReport` frozen dataclass on `types.py` covering full-year IS, CFS,
  year-end BS snapshot, capital activity, audit opinion, covenant violations,
  and LLM-authored MD&A + forward guidance + risk factors.
- `src/annual_report.py` module:
  - `aggregate_year(firm, year_rows, prior_year_rows)` — pure-Python deterministic
    aggregation with YoY growth.
  - `build_annual_prompt` + `parse_annual_report` — LLM prompt and JSON parser
    with defensive `_to_float` coercion.
  - `render_annual_report_markdown` — renders 10-K-style markdown.
  - `make_annual_report_generator(backends, state_ref)` — factory; reuses each
    firm's own LLM backend.
- Orchestrator: new Phase A1.5 between A1 (auditor) and A2 (governance), runs at
  `fqtr=4` only when `annual_reports_enabled=True`. Captures audit opinion and
  in-year covenant violations into the report.
- Output: `outputs/run_X/firms/firm_Y/annual_report_FY####.md` (markdown) +
  `annual_reports.csv` (research dataset). 14 WRDS datasets total now.
- Config toggle `annual_reports_enabled: bool = False` (default off).
- 9 new tests covering aggregation, parsing, markdown rendering, fqtr=4 gating,
  and toggle-off behavior. 144 tests pass.

### ✅ Stage 5: Bad debt expense (DONE)
- Firm decision field: `allowance_pct_of_ar`.
- `FirmState.allowance_for_doubtful_accounts` + `CompustatRow.allowance_dca`.
- Accounting:
  - `new_allowance = gross_AR × allowance_pct` (if set, else carry forward %).
  - Write-offs (from env) reduce gross AR and allowance pro-rata.
  - `bad_debt_expense = new_allowance − (prior_allowance − write_offs)`.
  - Bad debt expense reduces reported net income and retained earnings.
- Environment emits `write_offs: [{firm_id, amount}]` in its JSON; orchestrator
  patches each firm's ClampedDecisions with the write-off before accounting.
- New dataset `bad_debt_events.csv` — quarterly panel with gross/allow/net AR,
  bad_debt_expense, write_offs, allowance_pct.
- CFO formula corrected: `cfo = NI_pre − bad_debt_expense + dep − Δnet_AR +
  ΔWC_liab`. BS identity rigorously verified across combined Stage 4/5 fields.
- 13 new tests covering DPO/DSO effects, deposit_pct, PP&E disposal gain/loss,
  allowance topup, write-offs, and env-orchestrator flow (129 tests total).

---

## Structural principles (apply to all future work)

1. **No hardcoded numbers for agent behavior**. Thresholds, rates, fees, eligibility gates = LLM judgments.
2. **Structural bounds OK**: facility type whitelist, covenant template names, max facilities per firm.
3. **Accounting math stays in code**. LLMs never mutate balances directly.
4. **Consistency checks every quarter** on new data structures.
5. **Toggles default OFF**. Backward-compat for existing runs.
6. **WRDS-style outputs**: every new dataset carries `run_id, firm_id, tic, conm, sic, datadate`.

---

## Known issues / deferred

- SGA/capex floors are currently `max($2M, 0.5% assets)` / `0.5% PP&E`. Per Stage 4/5 spirit, should eventually let environment discipline unrealistic SGA via demand penalties rather than hard floor. Keeping floor for now as safety net.
- Phase 3 mandatory R&D cost ($10M) and IPO structure ($175M, 10M shares, $17.50) are game-setup constants. Leave as-is.
- Tax rate (21%), depreciation (2.5%/Q) — legal/regulatory, leave as-is.
- Delisting threshold (price < $1 for 2Q) — exchange rule, matches real NYSE, configurable.

---

## File touchpoints (for anyone picking this up)

| Area | Key files |
|------|-----------|
| Types | `src/types.py` |
| Config toggles | `src/config.py` (RunConfig dataclass + load_config) |
| Orchestrator | `src/orchestrator.py` (run_quarter) |
| Firm prompts | `src/prompts.py` (build_firm_prompt, build_environment_prompt) |
| Agents | `src/{equity,investment,commercial}_bank.py`, `src/sellside_analyst.py`, `src/auditor.py`, `src/governance.py`, `src/sec_agent.py`, `src/earnings_announcement.py` |
| Debt bookkeeping | `src/debt_management.py` (NEW — pure Python) |
| Templates | `src/data_templates.py` |
| Datasets | `src/datasets.py` |
| Output | `src/output_organizer.py` |
| Tests | `tests/test_expansion.py` |
| Config examples | `config/validation_full.yaml`, `config/test_broker_modes.yaml` |
