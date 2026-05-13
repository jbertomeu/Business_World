# Changelog

Wave-by-wave history. Each wave was a focused sprint addressing specific
gaps in the CLAUDE Industry Simulation Principles scorecard. For the
current scorecard see `docs/principles_review.md`; for the architecture
see `docs/architecture.md`.

## Wave λ (April 2026) — Private-equity + IPO lifecycle

**Architectural**: fundamental shift from "firms IPO at Q0 with fixed
cash" to "firms start private, raise PE rounds, decide when to IPO".

### New features (toggle: `pe_lifecycle_enabled: bool = False`)

- **Lifecycle states** on `FirmState`: `founded → series_a → series_b →
  series_c → late_stage_private → going_public → public`. `is_public`
  flag; `equity_price = 0` until IPO.
- **PE fund pool** (3 default funds, configurable): Vanguard Life
  Sciences Ventures (early-stage biotech, 30% hurdle, $600M),
  Horizon Growth Partners (growth, 22% hurdle, $800M), Meridian
  Capital (generalist, 20% hurdle, $500M). Each has distinct strategy,
  sector thesis, horizon, portfolio tracking.
- **PE round auction** (Phase 1.5): firms needing capital (first round
  OR runway < 4Q) issue CFO pitch → PE funds independently evaluate
  (LEAD / BID / PASS with proposed valuation + amount) → firm selects
  lead + syndicate within 20% pre-money tolerance → shares issued +
  cash credited + cap table updated.
- **IPO event** (Phase 1.6): late-stage privates (series_b+) decide
  FILE_IPO / STAY_PRIVATE / RAISE_PRIVATE. Filing → firm authors full
  S-1 prospectus (business overview, risk factors, MD&A, projections,
  use of proceeds, target price range) → public equity market prices
  at midpoint → transition to public.
- **Bargain-purchase GAAP**: when PE price is below book value (or
  M&A bid below book), the excess flows to retained earnings as a
  bargain-purchase gain (ASC 805). Builds on Wave θ++ M&A fix.
- **`pe_rounds.csv`, `pe_funds.csv`, `prospectus/*.md`**: new datasets
  capturing every round event + fund state + full prospectus text.

### Infrastructure
- 4 new per-firm LLM factories in `src/cli.py` (pitch, PE eval per
  fund, IPO decision, prospectus)
- All tagged via `tag_backend` for cost attribution
- `src/private_equity.py` (440 LoC): prompts + agents + pure-function
  transaction execution (`execute_pe_round`, `execute_ipo`)
- `docs/wave_lambda_plan.md` — the pre-implementation design doc,
  now retained as reference for future extensions

### Test count: 299 → **303** (4 new PE accounting tests)

---

## Wave κ (April 2026) — Strategic planning

Firms now author forward 5-year strategic plans and face variance
accountability. Designed to prevent the "drift into default without
course-correcting" pathology identified in v1/v2 runs.

### New features (toggle: `strategic_planning_enabled: bool = False`)

- **`StrategicPlan`** dataclass: 20-quarter forward budget with revenue,
  units, capacity, COGS, R&D, SGA, capex, equity/debt raises,
  projected NI, projected cash, planned generation + cumulative R&D.
- **`PlanLine`** per-quarter projection; **`PlanVariance`** per-quarter
  actual-vs-plan comparison.
- **`FirmState` fields**: `current_plan`, `plan_variance_history`,
  `material_variance_streak`.
- **Planning phase** (pre-Phase-5): fires at Q0, every fqtr=4, or when
  `material_variance_streak >= 2`. LLM is prompted as the CFO with
  scenario industry context + current firm state + plan-summary from
  the prior plan. Outputs full 20-quarter JSON plan with narrative,
  assumptions, risks, milestones.
- **Variance computation** (post-accounting): compares actual revenue,
  NI, cash, units vs plan line. Flags material variance (>20% revenue
  miss OR >20% cash miss OR >50% NI miss with negative direction).
- **Prompt integration**: firm decision prompt now includes strategy
  narrative, key milestones, last-3-quarters variance table, and a
  warning block if `material_variance_streak >= 2`.
- **`strategic_plans.csv`** dataset: narrative + milestones + totals
  per issued plan.

### Key finding from 2y live test
A Wave ι+κ live run (run_1776862973) showed firm_1 produce an honest
re-plan at Q4 acknowledging: *"prior plan underestimated capital
requirements for scaling and overestimated near-term revenue
generation... $226M in net losses over two quarters highlight
critical..."*. The variance mechanism worked; what the firms needed
was patient capital — which Wave λ now provides.

### Test count: 291 → **299** (8 new strategic-planning tests)

---

## Wave ι (April 2026) — Scenario-driven economics

**Removing industry assumptions from prompts.** Previously prompts
hardcoded "senolytic therapy" and "biopharmaceutical" language.
Now scenarios drive the industry character — the same prompts work
for breakthrough, mature, and declining industries.

### New features

- **`IndustryCharacter`** on `ScenarioConfig`: narrative (free-form
  text surfaced to firm + env + analyst prompts), label, TAM at
  maturity, years to maturity.
- **`MarketParams`** on `ScenarioConfig`: 10 scenario-overridable
  demand-model parameters (market_size_baseline, awareness_rate,
  outside_utility_base/decay/floor, price/quality/brand coefficients,
  affordability_center/steepness). All Nones inherit from SimParams.
- **Demand coefficients on `SimParams`** (previously hardcoded in
  `demand.py`): `demand_price_coef`, `demand_quality_coef`,
  `demand_brand_coef`, outside-utility triple, affordability pair.
- **Market signals in firm info_package**: at current prices, what
  is the estimated aware population × inside share × affordability?
  Tells firms their capacity-constraint vs demand-constraint reality.
- **Prompt refactor**: `FIRM_SYSTEM_TEMPLATE` and `ENV_SYSTEM_PROMPT`
  are now industry-agnostic. `{industry_character_block}` and
  `{market_signals_block}` slots populated from scenario.
- **New scenarios**: `well_capitalized` (updated — longevity
  breakthrough, $800B TAM, WTP $150K center, outside option decays
  fast), `declining_industry` (new — $80B shrinking 7%/yr, negative
  outside-option decay, commodity pricing, high price elasticity).

### Key finding from 1y live test
Revenue went from v2's $19M/Q to $60M/Q in Q1 (3× improvement); firm_2
(monopolist) generated +$151M NPV — vs v2's monopolist losing $1.4B.
Scenario framing + market signals caused firms to price/scale more
realistically. But they still over-invested in capacity, which
motivated Wave λ (PE capital bridges the ramp).

### Test count unchanged (291); Wave κ + λ added the new tests.

---

## Wave θ++ (April 2026) — Codex audit findings addressed

**Scorecard: 19🟢 / 1🟡 (unchanged).** Codex independent audit produced
28/33 CONFIRMED, 2 DISPUTED, 1 FALSE_POSITIVE, 2 UNCLEAR. All
actionable findings addressed:

- **B-1 fix (DISPUTED → resolved)**: Environment + equity-market decisions
  now produce structured `Action` records in `proposals.jsonl`. Two new
  sites in `orchestrator.py`: `actor_id="environment", action_type="resolve_market"`
  after env outcome is finalized; `actor_id="equity_market",
  action_type="price_equity"` per firm inside Phase 11. Test updated in
  `tests/test_engine.py` to assert both firm + env Action records are logged.
- **H-4 + F-4 (DISPUTED + UNCLEAR → resolved)**: new `tests/test_telemetry.py`
  with 12 direct tests covering `record_call`, `reset`, per-role breakdown,
  unattributed bucket, `set_role` ContextVar semantics, `tag_backend`
  wrapper, dump format, `$` pricing math, and **static coverage checks
  that every agent factory in cli.py + per-agent factories uses
  `tag_backend` or `set_role`**. Replaces the F-4 "need live run" gap
  with structural verification.
- **G-4 (UNCLEAR → resolved)**: Spec 12 regression output archived to
  `outputs/regressions/interlock_belief_accuracy_mock.txt`. The N=60
  result (coef −0.0484, p=0.001) is now verifiable from static
  artifacts without re-running Python.
- **D-3 (FALSE_POSITIVE → doc tightened)**: the interlock info-leak
  description in CHANGELOG now correctly states the mechanism is gated
  on `noisy_signals_enabled` in code; the `directors_enabled=False` case
  is a natural no-op (empty pool → 0 shared → unchanged SD), not an
  explicit second gate.

**Test count**: 273 → **285** (+12 telemetry tests).
**Audit trail summary**: see `CODEX_AUDIT_FILLED.md` for the full
Codex-produced audit report.

## Wave θ+ (April 2026) — Research polish

**Scorecard: 19🟢 / 1🟡 (unchanged; θ+ is polish on existing green cells)**

- **Per-observation log** `peer_observations.jsonl`: records
  `(quarter, observer, observed, n_shared_directors, noise_sd_applied,
  true_revenue, observed_revenue)` at the moment of observation. Enables
  clean identification of the interlock info-leak effect — previously
  Spec 12 used stale snapshot data. With the new log, Spec 12 produces
  a statistically significant result: n_shared coefficient = −0.0484,
  p=0.001 at N=60 (mock smoke).
- **Cost telemetry complete coverage**: earnings_announcement,
  annual_report, ma_agent bidder/raise/target, environment — all now
  tagged via `telemetry.set_role` or `tag_backend`. The "unattributed"
  bucket shrinks to near-zero.
- **Backfill utility** `scripts/backfill_actor_class.py`: retroactively
  adds `actor_class` field to historical `proposals.jsonl` files.
  Applied to 19 pre-θ runs (665 rows updated).
- **At-run-end BS validator**: CLI prints `[OK]` or `[WARN]` summary
  of `bs_violation_log` after every run — researchers see integrity
  status immediately before diving into outputs.
- **README + CHANGELOG**: refreshed getting-started walkthrough; this
  file.

## Wave θ (April 2026) — Richness + observability

**Scorecard: 17🟢 / 3🟡 → 19🟢 / 1🟡**

### New features (all toggleable; defaults preserve backward compat)

- **`directors_enabled` (default ON)**: Shared director pool populated
  at firm founding. ~3 × n_firms directors with interlocking seats,
  max 3 seats per director, 30% interlock probability. Emitted to
  `crosswalk.csv`.
- **`director_lifecycle_enabled` (default OFF)**: Annual Q4 refresh
  (~25% probability per firm that one director rotates out and a fresh
  director is appointed), plus automatic seat-vacation when a firm
  defaults. Events recorded in `director_turnover.csv`.
- **Interlocking-director info leak**: The mechanism is gated in code
  on `noisy_signals_enabled` only; the effect becomes a no-op when
  `directors_enabled=False` (empty pool → `_count_shared_directors`
  returns 0, SD division factor is 1). So effectively both toggles
  must be on. When active, observer/observed pairs sharing `n`
  directors see peer signals with noise SD divided by `(1+n)`.
  Testable hypothesis registered as Spec 12 in baseline regressions.
- **`three_llm_board_enabled` (default OFF)**: Replaces the 1-call-3-
  perspective governance prompt with 3 separate CEO-voice / CFO-voice /
  comp-committee-voice LLM calls running in parallel, plus a synthesis
  call. 4× governance cost. The three voices + synthesis are all tagged
  in telemetry via distinct role names.
- **`cost_telemetry_enabled` (default ON)**: `src/telemetry.py`
  — OpenRouter pricing table fetched at run start (343 models loaded);
  every OpenRouter/MiniMax call records (input_tokens, output_tokens,
  latency, model, agent_role) via ContextVar-based role tagging.
  Dumped to `llm_calls.jsonl` (per-call) + `cost_summary.txt`
  (aggregates per-model and per-agent-role with $ USD).
- **Firm LLM-failure fallback carry-forward**: When a firm's LLM fails
  all 5 retries, the fallback now carries forward prior-quarter flows
  (price, production, R&D, SGA) instead of hardcoded constants. More
  emergent, removes the last non-design hardcoded policy. Closes
  Principle 3's major gap.
- **3-LLM board committee structure**: `make_governance_agent_3llm()`
  in `src/governance.py`.
- **Board/firm context measured**: Principle 12 promoted from 🟡 to 🟢
  after direct measurement — board prompt = 1,846 tokens, firm prompt
  = 1,567 tokens on mid-run state. 11.5% of phi-4's 16k context on the
  tightest model. No splitting needed.
- **`actor_class` field on `proposals.jsonl`**: canonical class tag
  (`firm | auditor | analyst | sec | commercial_bank | investment_bank |
  activist | board_governance | ma | environment`) auto-derived from
  `actor_id` via `engine.derive_actor_class`.
- **Regression specs 10-12**: matched-firm pricing, disclosure tone →
  next-year return, interlock → observation accuracy.
- **Dashboard additions**: 💰 Cost tab (cost_summary + bar charts by
  model and latency), enhanced Negotiations tab (acceptance rate +
  per-topic table), enhanced Proposals tab (rejection-reasons
  breakdown + histogram).
- **Test coverage**: `tests/test_directors.py` — 10 new tests for
  director pool, interlock counter, info-leak, lifecycle.

### Validation runs
- **v14** (pre-θ, post-tax-fix): 3 firms × 4Q live, 0 BS violations.
- **v15** (all-θ-features ON): 3 firms × 4Q live, 0 BS violations,
  $0.0326 USD total cost for 104 LLM calls / 266k tokens, 3-LLM
  committee fired correctly at Q4, director lifecycle recorded 6
  events (4 default departures from firm_0, 1 retirement, 1
  appointment).

## Wave η (April 2026) — Event studies + regressions

- **`scripts/baseline_regressions.py`** expanded from 6 to 9 specs:
  added event-study specifications around SEC actions (investigate /
  subpoena / AAER), restatement announcements, CEO turnover.
- **Key finding on v13 data**: CEO forced-turnover event study shows
  −25% mean 1-quarter price drop on firings (t=−2.66, significant at 1%).

## Wave ζ (April 2026) — Scenarios + identifier graph

- **Scenario library** (`scenarios/`): 3 shipped YAMLs —
  `biotech_early_stage`, `mature_industry`, `distressed`. Per-firm
  founding cash, IPO price/shares, PPE, capability, brand, unit cost,
  CEO salary. Backward-compatible uniform default when unset.
- **Identifier graph** (`src/identifiers.py`): Director, Product,
  Security dataclasses + `build_crosswalk(state)` emits
  `crosswalk.csv` linking every entity (firm, ceo, facility, security,
  grant, product; director populated in Wave θ).
- **Snapshots** (`src/snapshots.py`): `snapshot_world` / `restore_world`
  with atomic write + `format_version` guard. `--restart-from` CLI
  flag. ~60-80 KB per quarter. Enables perfect mid-run resume.

## Wave ε (March 2026) — Beliefs + noise

- **`noisy_signals_enabled` (default OFF)**: Peer observations get
  mean-zero Gaussian noise applied per-(quarter, observer, observed)
  via a seeded RNG (reproducible across re-runs with same seed).
- **`FirmBelief`** on WorldState: EWMA-smoothed estimates of peer
  prices + revenues. Updated each quarter from (possibly noisy)
  observations.
- **Typed memories** for non-firm agents: `ActivistMemory`,
  `AuditorMemory`, `SECMemory` (stored on WorldState, pickled with
  snapshots).

## Wave δ (March 2026) — Reproducibility + audit

- **Per-quarter snapshots** to `outputs/<run>/snapshots/Q{N}.pkl`.
- **`proposals.jsonl`**: one record per (Action, ActionResult) pair.
  Every firm / auditor / SEC / activist / IB / CB / governance / M&A /
  earnings / analyst decision. Every `compustat_q.csv` row links back
  via `proposal_id`.

## Wave γ (March 2026) — Protocolized bargaining

- **`src/negotiation.py`**: `Negotiation`, `Offer`, `Round`,
  `OutsideOption` primitives.
- **5 LLM-driven negotiation sites**: covenant waiver, debt pricing,
  activist campaign (2-round LLM-driven), M&A auction (multi-bidder
  LLM-driven raise round), audit fee haggle.
- **`negotiations.jsonl`**: completed multi-round bargaining history.

## Wave β (March 2026) — Structured actions

- **`src/engine.py`**: `Action` / `ActionResult` / `ActionLog` /
  `RejectionEvent` dataclasses. Every agent decision is a structured
  proposal; adjudication is explicit; clamping produces structured
  rejection events.
- **All 10 agent classes migrated** to the Action spine.

## Wave α (March 2026) — Canonical-state hardening

- **Balance-sheet identity invariants**: `_check_bs_invariants` fires
  at every mutation-phase boundary. Drift events logged to
  `bs_violations.jsonl` with full BS component snapshot + phase label.
  Makes root-cause trivial.
- **`decision_source` tag** on every compustat row: `llm | fallback |
  mock | rule` so research can filter to purely emergent rows.

## Pre-α (v0.5) — Expansion

20-phase quarterly pipeline with all major corporate-finance features:
earnings management, SEC surveillance, sell-side analysts, annual
auditor opinions, CEO governance + comp, M&A, earnings announcements,
restatements, debt covenants, macro shocks, Stage-12 corporate finance
(legal reserves, pension, deferred tax, CEO options, insider trading).

## Pre-v0.5 — Core

Base simulation: firms make operating + financing decisions; product
market with Bass-style demand; environment agent resolves market share;
accounting (BS / IS / CFS) with GAAP identities enforced.
