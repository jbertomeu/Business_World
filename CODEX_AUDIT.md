# Codex Independent Audit Scaffold

**Purpose**: independent second-opinion audit of the LLM Firm Lab
codebase by Codex, using Claude-authored documentation as the spec.
Every claim below is a falsifiable statement pulled from the project's
own docs. Codex's job is to **verify** each claim against the actual
code and tests — not to fix anything, not to suggest improvements
unless prompted.

**How to use**
1. Codex opens this file and reads the Preamble.
2. For each `A-*` claim, Codex reads the cited source/code, then fills
   the `Status` + `Findings` fields in-place.
3. When finished, Codex writes a 1-paragraph summary at the bottom
   listing: N confirmed, N disputed, N false-positive, N unclear.
4. No code changes. No rebasing. No "while I'm here" cleanups.

**Ground rules**
- CONFIRMED = claim matches code, and a test exists.
- DISPUTED = claim looks wrong or contradicted by the code.
- FALSE_POSITIVE = claim is fine but doc phrasing is misleading.
- UNCLEAR = insufficient evidence either way; note what's missing.

**Graphify aid**
- If context for a file is needed, query `graphify-out/graph.json`
  (use `graphify query "..."` or `graphify explain "SymbolName"`)
  before cold-reading the file.

---

## Preamble for Codex

This project is a ~7,000-LoC Python simulation of a pharmaceutical
industry with LLM-powered firms, auditors, analysts, regulators, and
bankers. It produces 21 WRDS-style CSVs + 6 JSONL audit trails per
run. Development proceeded in named "waves" (α through θ+); see
`CHANGELOG.md`.

Current claimed state (per `docs/principles_review.md` and
`CHANGELOG.md`):
- 273 tests passing (`python -m pytest tests/ -q`)
- Scorecard 19🟢 / 1🟡 against 20 CLAUDE simulation principles
- All feature toggles default-safe (backward-compatible with pre-Wave-θ runs)

Key files:
- `src/types.py` — canonical dataclasses
- `src/orchestrator.py` — phase pipeline, WorldState
- `src/accounting.py` — GAAP (BS / IS / CFS)
- `src/engine.py` — Action / ActionResult / ActionLog
- `src/telemetry.py` — cost tracking
- `src/governance.py` — board review, incl. 3-LLM committee
- `src/cli.py` — agent wiring, run orchestration
- `tests/` — 273 tests covering everything above

---

## A. Accounting integrity

### A-1 — BS identity enforced at every mutation phase
**Claim** (`docs/architecture.md`, "Per-phase BS-identity invariants"):
`_check_bs_invariants` fires at every mutation-phase boundary; drift
events log to `bs_violations.jsonl` with full BS component snapshot.

**Verify**: `src/orchestrator.py::_check_bs_invariants` — count call
sites in `run_quarter`. Does every mutation phase have one? Is the
tolerance ($1) consistent with `tests/test_accounting.py`?

**Status**: _[Codex fills]_
**Findings**: _[Codex fills]_

### A-2 — Tax-fix: pension tax savings is non-cash; CFO unchanged
**Claim** (`CHANGELOG.md` Wave θ and session summary):
"Tax savings from pension accrual ($5,250) is non-cash — CFO should
NOT be adjusted for it. Only `end_taxes_payable` is recomputed to
use the adjusted tax."

**Verify**: `src/accounting.py` around line 750 (post_quarter tax
handling). Confirm `cfo += (new_delta_taxes_payable - delta_taxes_payable)`
was REMOVED; only `end_taxes_payable = tax_expense` remains.

**Status**: _[Codex fills]_
**Findings**: _[Codex fills]_

### A-3 — Zero BS violations on v14 + v15 live runs
**Claim** (`CHANGELOG.md`): both v14 and v15 live runs show
`bs_violations.jsonl` is empty.

**Verify**:
`wc -l outputs/run_1776742095/bs_violations.jsonl` (v13, pre-fix, should have 8)
`wc -l outputs/run_1776772063/bs_violations.jsonl` (v14, post-fix, should be 0)
`wc -l outputs/run_1776783195/bs_violations.jsonl` (v15, all θ on, should be 0)

**Status**: _[Codex fills]_
**Findings**: _[Codex fills]_

### A-4 — At-run-end BS validator prints status
**Claim** (`CHANGELOG.md` θ+): CLI prints `[OK]` or `[WARN]` summary
after each run.

**Verify**: `src/cli.py` around line 841 — check for the
`_bs_violations` summary print block.

**Status**: _[Codex fills]_
**Findings**: _[Codex fills]_

---

## B. Structured actions + audit trails

### B-1 — Every agent mutation flows through Action → ActionResult → ActionLog
**Claim** (`docs/architecture.md` + `docs/principles_review.md` #4):
All 10 agent classes migrated. `proposals.jsonl` has one row per
(Action, ActionResult) pair.

**Verify**: Grep `ActionLog.quick_record|ActionLog.record` across
`src/`. Count unique call sites. Map to agent classes: firm, env,
equity_market, investment_bank, commercial_bank, earnings,
sellside_analyst, activist, auditor, sec, ma, board_governance. Any missing?

**Status**: _[Codex fills]_
**Findings**: _[Codex fills]_

### B-2 — `proposal_id` FK on compustat_q.csv
**Claim** (`docs/datasets.md`): every `compustat_q.csv` row carries
`proposal_id` that keys into `proposals.jsonl`.

**Verify**: `src/accounting.py::build_compustat_row` end — confirm
`proposal_id=getattr(decisions, "proposal_id", "")` is set. Then open
a recent run's `compustat_q.csv` and sample 10 rows — are they all
populated with a valid UUID?

**Status**: _[Codex fills]_
**Findings**: _[Codex fills]_

### B-3 — `actor_class` auto-derived (Wave θ)
**Claim** (`CHANGELOG.md` θ): `actor_class` field in `proposals.jsonl`
derived from `actor_id` via `engine.derive_actor_class`.

**Verify**: `src/engine.py::derive_actor_class`. Check all 10 actor
classes have a case (firm, auditor, analyst, sec, commercial_bank,
investment_bank, activist, board_governance, ma, environment). Then
check `ActionLog.record` calls `derive_actor_class(action.actor_id)`.

**Status**: _[Codex fills]_
**Findings**: _[Codex fills]_

---

## C. Negotiations

### C-1 — 5 LLM-driven negotiation sites
**Claim** (`docs/principles_review.md` #10): 5 sites —
`covenant_waiver`, `debt_pricing`, `audit_fee`, `activist_campaign`,
`ma_auction`. All logged to `negotiations.jsonl`.

**Verify**: grep `topic=` or `topic: str = "` patterns in `src/`.
Find all 5. Then check each writes into `state.negotiations_log`.

**Status**: _[Codex fills]_
**Findings**: _[Codex fills]_

### C-2 — Per-round offer history preserved
**Claim** (`docs/datasets.md`): `negotiations.jsonl` records "full
round-by-round offer history for research."

**Verify**: inspect `src/negotiation.py` — does `Negotiation.rounds`
persist after the last round? Sample a real negotiation record in
`outputs/run_1776783195/negotiations.jsonl` — does the `rounds`
array have ≥1 entry?

**Status**: _[Codex fills]_
**Findings**: _[Codex fills]_

---

## D. Directors + interlock info leak (Wave θ)

### D-1 — Pool size bounded
**Claim** (`docs/principles_review.md` #15): pool size
`max(10, 3×n_firms)` capped at `len(_DIRECTOR_NAMES)`.

**Verify**: `src/orchestrator.py::_populate_director_pool`. Check the
formula matches exactly. `_DIRECTOR_NAMES` is a constant list — count
its length.

**Status**: _[Codex fills]_
**Findings**: _[Codex fills]_

### D-2 — Max 3 seats per director
**Claim**: `MAX_SEATS_PER_DIRECTOR = 3`.

**Verify**: `src/orchestrator.py::_populate_director_pool` + same in
`_director_lifecycle_phase`. Check that no director can acquire a 4th
seat through either pathway.

**Status**: _[Codex fills]_
**Findings**: _[Codex fills]_

### D-3 — Info-leak: noise SD scales by 1/(1+n_shared)
**Claim** (`CHANGELOG.md` θ): interlocked peer observations have noise
SD divided by `(1+n_shared_directors)`.

**Verify**: `src/orchestrator.py::_build_firm_info_package`. Find the
line `effective_sd = noise_sd / (1 + shared_dirs)`. Confirm it's
active only when `noisy_signals_enabled=True` AND `directors_enabled=True`
(i.e., when there are any directors in `state.directors`).

**Status**: _[Codex fills]_
**Findings**: _[Codex fills]_

### D-4 — Lifecycle: annual refresh + default departures
**Claim**: Q4 refresh has 25% probability per firm; default departures
fire every quarter when the firm's `is_active=False`.

**Verify**: `src/orchestrator.py::_director_lifecycle_phase`. Check
the `if state.rng.random() >= 0.25: continue` line. Check that
default-triggered departures run unconditionally (not gated on Q4).

**Status**: _[Codex fills]_
**Findings**: _[Codex fills]_

### D-5 — `directors_enabled` toggle gates everything
**Claim** (`CHANGELOG.md` θ): when toggle off, `state.directors` stays
empty, interlock info leak becomes a no-op.

**Verify**: `src/orchestrator.py::initialize_world` — confirm
`_populate_director_pool` only runs when `directors_enabled=True`.
Then confirm `_count_shared_directors` returns 0 when `state.directors`
is empty (so effective_sd = noise_sd / 1 = noise_sd, unchanged).

**Status**: _[Codex fills]_
**Findings**: _[Codex fills]_

### D-6 — `tests/test_directors.py` coverage
**Claim**: 10 tests covering pool generation, interlock counter,
info-leak proportionality, lifecycle, toggle-off.

**Verify**: `python -m pytest tests/test_directors.py -v` — does each
of the 10 tests target a distinct aspect? Any test that's trivial or
tautological?

**Status**: _[Codex fills]_
**Findings**: _[Codex fills]_

---

## E. 3-LLM board committee (Wave θ)

### E-1 — 4× cost: 3 perspective calls + 1 synthesis
**Claim** (`CHANGELOG.md` θ): `make_governance_agent_3llm` runs 3
parallel voice calls + 1 synthesis = 4× API cost.

**Verify**: `src/governance.py::make_governance_agent_3llm`. Count
`backend.complete_json` call sites in the returned function. Confirm
the 3 voice calls run in parallel (`ThreadPoolExecutor`) and the
synthesis runs sequentially after.

**Status**: _[Codex fills]_
**Findings**: _[Codex fills]_

### E-2 — Toggle default OFF
**Claim**: `three_llm_board_enabled: bool = False` default in `RunConfig`.

**Verify**: `src/config.py::RunConfig`. Then check `src/cli.py` branches
on `getattr(config, "three_llm_board_enabled", False)`.

**Status**: _[Codex fills]_
**Findings**: _[Codex fills]_

### E-3 — Perspective prompts differ only in framing
**Claim**: The three voices see the SAME base prompt; only the
perspective framing differs.

**Verify**: `src/governance.py`. Confirm `base_sys, base_user =
build_governance_prompt(...)` is called once, and each voice appends
`_COMMITTEE_PERSPECTIVES[voice_name]` to `base_sys` only. If one voice
sees different data than the others, that's an information leak bug.

**Status**: _[Codex fills]_
**Findings**: _[Codex fills]_

---

## F. Cost telemetry (Wave θ + θ+)

### F-1 — OpenRouter pricing fetched at run start
**Claim** (`CHANGELOG.md` θ+): pricing fetched once via
`fetch_pricing_openrouter()` when `cost_telemetry_enabled=True`.

**Verify**: `src/cli.py` near line 440, look for
`_tel.fetch_pricing_openrouter()`. Confirm it's gated on the toggle.
Then `src/telemetry.py::fetch_pricing_openrouter` — confirm it's
idempotent (`_pricing_fetched` flag prevents re-fetch).

**Status**: _[Codex fills]_
**Findings**: _[Codex fills]_

### F-2 — Every OpenRouter + MiniMax call records usage
**Claim** (`CHANGELOG.md` θ): every successful backend call records
(input_tokens, output_tokens, latency, model, agent_role).

**Verify**: `src/llm_backends.py::_record_usage`. Check both
`OpenRouterBackend.complete` and `MiniMaxBackend.complete` call it
exactly once per successful response. Does it also record on failed
retries? (It should NOT — partial calls don't count.)

**Status**: _[Codex fills]_
**Findings**: _[Codex fills]_

### F-3 — Role tagging via ContextVar (thread-safe)
**Claim** (`CHANGELOG.md` θ): `telemetry.set_role()` uses
`contextvars.ContextVar` so it works with `ThreadPoolExecutor`.

**Verify**: `src/telemetry.py::_current_role`. Confirm it's a
`ContextVar` (not a plain module-level var). Then `tag_backend(role)`
wraps a backend so every `complete`/`complete_json` runs inside
`set_role(role)`.

**Status**: _[Codex fills]_
**Findings**: _[Codex fills]_

### F-4 — "unattributed" bucket shrinks on v15
**Claim** (`CHANGELOG.md` θ+): wiring earnings_announcement,
annual_report, ma_agent, env_verifier via `tag_backend` should shrink
the "unattributed" row in `cost_summary.txt`.

**Verify**: `outputs/run_1776783195/cost_summary.txt` (v15, pre-θ+).
The "unattributed" row was $0.0148. Run a new short smoke or look at
any post-θ+ live run to see if it's smaller. If no post-θ+ live run
exists, verify theoretically by grepping `set_role` / `tag_backend`
coverage across the factories.

**Status**: _[Codex fills]_
**Findings**: _[Codex fills]_

---

## G. Per-observation log (Wave θ+)

### G-1 — n_shared captured at observation time, not snapshot time
**Claim** (`CHANGELOG.md` θ+): `peer_observations.jsonl` captures
`n_shared_directors` at the moment of observation (not later from a
stale snapshot).

**Verify**: `src/orchestrator.py::_build_firm_info_package`. The
observation-log append should happen INSIDE the `for fid, firm in
state.firms.items()` loop, using `shared_dirs` that was just computed
from `state.directors` at the current quarter. Confirm no async delay
between compute and log.

**Status**: _[Codex fills]_
**Findings**: _[Codex fills]_

### G-2 — Only written when noisy_signals_enabled
**Claim**: the log should be empty when noise is off (since there's
nothing to attribute accuracy to).

**Verify**: same function, confirm the `state.peer_observation_log.append`
is inside the `if noisy:` branch.

**Status**: _[Codex fills]_
**Findings**: _[Codex fills]_

### G-3 — Spec 12 uses observation log as primary source
**Claim** (`scripts/baseline_regressions.py`): Spec 12 prefers
`peer_observations.jsonl` over snapshot-derived beliefs.

**Verify**: `scripts/baseline_regressions.py::spec_interlock_belief_accuracy`.
Check the "PRIMARY SOURCE" block loads `peer_observations.jsonl`
first, then only falls back to snapshots if primary is empty.

**Status**: _[Codex fills]_
**Findings**: _[Codex fills]_

### G-4 — Spec 12 result: p=0.001 at N=60 (mock smoke)
**Claim** (`CHANGELOG.md` θ+): on mock smoke with n_firms=5,
noisy_signals_sd=0.20, Spec 12 produces n_shared coef = −0.0484, p=0.001.

**Verify**: reproduce —
```
python -m src run --config config/test_interlock_mock.yaml --mock
python scripts/baseline_regressions.py --runs <latest_run_id>
```
Look at Spec 12 output. Coefficient, p-value, N should match.

**Status**: _[Codex fills]_
**Findings**: _[Codex fills]_

---

## H. Principles scorecard (spot audit)

### H-1 — Principle 6 (correct bookkeeping) is 🟢
**Claim**: `docs/principles_review.md` gives Principle 6 a 🟢 based on
"0 violations in mock + v11/v12 live runs; BS identity checked at
every phase."

**Verify**: run `python -m pytest tests/test_accounting.py -v`. All
should pass. Then check `tests/test_accounting.py::TestDoc16WorkedExample`
— is the canonical 16-step worked example exercised?

**Status**: _[Codex fills]_
**Findings**: _[Codex fills]_

### H-2 — Principle 7 (info partitions)
**Claim**: `_build_firm_info_package` enforces partition; env agent
is the only omniscient reader.

**Verify**: grep `state.firms` in `src/prompts.py` — does any firm-side
prompt builder receive the full state? Trace `_build_firm_info_package`
output shape: PUBLIC fields per peer, PRIVATE only for the target firm.

**Status**: _[Codex fills]_
**Findings**: _[Codex fills]_

### H-3 — Principle 16 (reproducibility)
**Claim**: mock runs are byte-reproducible; live runs are NOT.

**Verify**: `tests/test_reproducibility.py` — run it twice, confirm
outputs match. Then inspect `src/llm_backends.py::OpenRouterBackend`
— is there any seeding that would make it reproducible? (There
shouldn't be; backend temperature + provider randomness is out of
our control.)

**Status**: _[Codex fills]_
**Findings**: _[Codex fills]_

### H-4 — Scorecard is NOT over-claimed
**Claim**: 19🟢 / 1🟡. The 🟡 is Principle 3 (mock-mode fallbacks are
by-design).

**Verify**: for each 🟢 cell in `docs/principles_review.md`'s table,
trace to the code that justifies it. List any cell where:
(a) no test covers the mechanism, or
(b) the test is trivial (asserts `x == x` or similar).

**Status**: _[Codex fills]_
**Findings**: _[Codex fills]_

---

## I. Deferred / known gaps

### I-1 — Mock-mode fallbacks by design
**Claim** (`CHANGELOG.md` θ + `docs/principles_review.md` Principle 3):
mock mode uses deterministic agents; this is the remaining 🟡 and is
NOT a bug.

**Verify**: `src/cli.py` — find the fallback RawDecisions in the mock
path. Does it carry `decision_source="mock"` or `"fallback"`? Is this
filterable downstream?

**Status**: _[Codex fills]_
**Findings**: _[Codex fills]_

### I-2 — TODO / FIXME sweep
**Task**: grep `TODO|FIXME|HACK|XXX` across `src/` + `scripts/` +
`app/`. For each hit, classify:
- (a) real bug worth filing
- (b) deferred enhancement
- (c) stale comment (concern already addressed)

**Status**: _[Codex fills]_
**Findings**: _[Codex fills]_

### I-3 — Test coverage gaps
**Task**: for each module in `src/`, check there's at least one test
file that imports from it. List modules with zero test imports.

**Status**: _[Codex fills]_
**Findings**: _[Codex fills]_

---

## Summary

_Codex fills this paragraph after completing all claims above._

**Totals**: CONFIRMED: _N_ / DISPUTED: _N_ / FALSE_POSITIVE: _N_ / UNCLEAR: _N_

**Top 3 most-important findings** (if any):
1.
2.
3.

**Recommended follow-ups** (if any):
-

---

*Generated: see CHANGELOG.md "Wave θ+" for the state being audited.
Claude Code wrote the scaffold; Codex fills the Status + Findings
fields. When complete, ship this doc alongside the run artifacts.*
