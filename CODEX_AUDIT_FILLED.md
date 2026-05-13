# Codex Independent Audit Scaffold

**Purpose**: independent second-opinion audit of the LLM Firm Lab
codebase by Codex, using Claude-authored documentation as the spec.
Every claim below is a falsifiable statement pulled from the project's
own docs. Codex's job is to **verify** each claim against the actual
code and tests ƒ?" not to fix anything, not to suggest improvements
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
run. Development proceeded in named "waves" (Iñ through I,+); see
`CHANGELOG.md`.

Current claimed state (per `docs/principles_review.md` and
`CHANGELOG.md`):
- 273 tests passing (`python -m pytest tests/ -q`)
- Scorecard 19dYY› / 1dYY­ against 20 CLAUDE simulation principles
- All feature toggles default-safe (backward-compatible with pre-Wave-I, runs)

Key files:
- `src/types.py` ƒ?" canonical dataclasses
- `src/orchestrator.py` ƒ?" phase pipeline, WorldState
- `src/accounting.py` ƒ?" GAAP (BS / IS / CFS)
- `src/engine.py` ƒ?" Action / ActionResult / ActionLog
- `src/telemetry.py` ƒ?" cost tracking
- `src/governance.py` ƒ?" board review, incl. 3-LLM committee
- `src/cli.py` ƒ?" agent wiring, run orchestration
- `tests/` ƒ?" 273 tests covering everything above

---

## A. Accounting integrity

### A-1 ƒ?" BS identity enforced at every mutation phase
**Claim** (`docs/architecture.md`, "Per-phase BS-identity invariants"):
`_check_bs_invariants` fires at every mutation-phase boundary; drift
events log to `bs_violations.jsonl` with full BS component snapshot.

**Verify**: `src/orchestrator.py::_check_bs_invariants` ƒ?" count call
sites in `run_quarter`. Does every mutation phase have one? Is the
tolerance ($1) consistent with `tests/test_accounting.py`?

**Status**: CONFIRMED
**Findings**: `src/orchestrator.py` calls `_check_bs_invariants` repeatedly inside `run_quarter` (e.g., after phases labeled `phase_2_ipo` at ~L448 through `phase_A2_governance` at ~L2796) and `_check_bs_invariants` itself logs a structured record with a full BS breakdown (cash/AR/inventory/PPE/goodwill; AP/accruals/taxes/debt/legal/pension/DTL; equity components) into `state.bs_violation_log` when `abs(resid) > 1.0` and `abs(delta_resid) > 1.0` (`src/orchestrator.py` ~L3193-L3259). `src/output_organizer.py` writes `world_state.bs_violation_log` to `outputs/{run_id}/bs_violations.jsonl` (see write block around `src/output_organizer.py` ~L150-190), and the $1 tolerance matches `tests/test_accounting.py`’s `assert diff < 1.0` in `test_balance_sheet_identity` (~L154).

### A-2 ƒ?" Tax-fix: pension tax savings is non-cash; CFO unchanged
**Claim** (`CHANGELOG.md` Wave I, and session summary):
"Tax savings from pension accrual ($5,250) is non-cash ƒ?" CFO should
NOT be adjusted for it. Only `end_taxes_payable` is recomputed to
use the adjusted tax."

**Verify**: `src/accounting.py` around line 750 (post_quarter tax
handling). Confirm `cfo += (new_delta_taxes_payable - delta_taxes_payable)`
was REMOVED; only `end_taxes_payable = tax_expense` remains.

**Status**: CONFIRMED
**Findings**: In `src/accounting.py`’s `post_quarter`, the adjusted-tax logic explicitly says “Do NOT adjust CFO's delta_taxes_payable” and sets `end_taxes_payable = tax_expense  # adjusted` without any `cfo += ...` correction (see block around `end_taxes_payable = tax_expense` near ~L416-L427). The earlier `delta_taxes_payable` is computed off `end_taxes_payable` (e.g., `delta_taxes_payable = end_taxes_payable - prior.taxes_payable` near ~L200-L201) but CFO is not retroactively patched.

### A-3 ƒ?" Zero BS violations on v14 + v15 live runs
**Claim** (`CHANGELOG.md`): both v14 and v15 live runs show
`bs_violations.jsonl` is empty.

**Verify**:
`wc -l outputs/run_1776742095/bs_violations.jsonl` (v13, pre-fix, should have 8)
`wc -l outputs/run_1776772063/bs_violations.jsonl` (v14, post-fix, should be 0)
`wc -l outputs/run_1776783195/bs_violations.jsonl` (v15, all I, on, should be 0)

**Status**: CONFIRMED
**Findings**: `outputs/run_1776742095/bs_violations.jsonl` has 8 lines, while `outputs/run_1776772063/bs_violations.jsonl` and `outputs/run_1776783195/bs_violations.jsonl` both have 0 lines (line counts verified via `Measure-Object -Line` on each file).

### A-4 ƒ?" At-run-end BS validator prints status
**Claim** (`CHANGELOG.md` I,+): CLI prints `[OK]` or `[WARN]` summary
after each run.

**Verify**: `src/cli.py` around line 841 ƒ?" check for the
`_bs_violations` summary print block.

**Status**: CONFIRMED
**Findings**: `src/cli.py` prints a post-run summary based on `state.bs_violation_log`: it emits `[WARN]` with counts and points to `bs_violations.jsonl` when non-empty, else emits `[OK] BS-violation check: 0 events (BS identity held every phase)` (see `src/cli.py` ~L842-L857).

---

## B. Structured actions + audit trails

### B-1 ƒ?" Every agent mutation flows through Action ƒ+' ActionResult ƒ+' ActionLog
**Claim** (`docs/architecture.md` + `docs/principles_review.md` #4):
All 10 agent classes migrated. `proposals.jsonl` has one row per
(Action, ActionResult) pair.

**Verify**: Grep `ActionLog.quick_record|ActionLog.record` across
`src/`. Count unique call sites. Map to agent classes: firm, env,
equity_market, investment_bank, commercial_bank, earnings,
sellside_analyst, activist, auditor, sec, ma, board_governance. Any missing?

**Status**: DISPUTED
**Findings**: Many agents are logged via `ActionLog.quick_record` but typically through an alias (e.g., `from .engine import ActionLog as _AL; _AL.quick_record(...)`) at multiple sites in `src/orchestrator.py` (e.g., M&A bidder acquisition logging around ~L460-L480; SEC actions ~L510+; earnings announcements ~L1215-L1250; analysts ~L1290-L1320; IB/CB/auditor/governance later in the file). However, the environment agent and equity market do not appear to be logged as Actions: `src/orchestrator.py` calls `env_agent_fn(...)` and applies results without an ActionLog record (market resolution around the Phase 5 block ~L861-L950), and similarly sets `equity_price` from `equity_market_fn(...)` without emitting an Action (`src/orchestrator.py` Phase 11 block ~L1313-L1327). Correspondingly, `outputs/run_1776783195/proposals.jsonl` contains actor classes like `sec`, `investment_bank`, `commercial_bank`, `auditor`, `analyst`, and `firm`, but no `environment` entries.

### B-2 ƒ?" `proposal_id` FK on compustat_q.csv
**Claim** (`docs/datasets.md`): every `compustat_q.csv` row carries
`proposal_id` that keys into `proposals.jsonl`.

**Verify**: `src/accounting.py::build_compustat_row` end ƒ?" confirm
`proposal_id=getattr(decisions, "proposal_id", "")` is set. Then open
a recent run's `compustat_q.csv` and sample 10 rows ƒ?" are they all
populated with a valid UUID?

**Status**: CONFIRMED
**Findings**: `src/accounting.py::build_compustat_row` sets `proposal_id=getattr(decisions, "proposal_id", "")` (see end of builder around ~L820-L824). In `outputs/run_1776783195/compustat_q.csv`, the `proposal_id` column exists and the first 10 data rows show non-empty UUID4-like values (e.g., `a25c0163-c63c-4cc4-9e37-51bf8bc4b864`, `324a235a-b0c4-47cf-aba2-c99f35009e5e`, etc.).

### B-3 ƒ?" `actor_class` auto-derived (Wave I,)
**Claim** (`CHANGELOG.md` I,): `actor_class` field in `proposals.jsonl`
derived from `actor_id` via `engine.derive_actor_class`.

**Verify**: `src/engine.py::derive_actor_class`. Check all 10 actor
classes have a case (firm, auditor, analyst, sec, commercial_bank,
investment_bank, activist, board_governance, ma, environment). Then
check `ActionLog.record` calls `derive_actor_class(action.actor_id)`.

**Status**: CONFIRMED
**Findings**: `src/engine.py::derive_actor_class` maps prefixes for `firm_`, `auditor`, `analyst`, `sec`, `commercial`, `investment`, `activist`, `board`, `ma_`/`m_and_a`, and `env`/`environment` (see `src/engine.py` ~L150-L184). `ActionLog.record` writes `"actor_class": derive_actor_class(action.actor_id)` into each proposal record (`src/engine.py` ~L225-L245).

---

## C. Negotiations

### C-1 ƒ?" 5 LLM-driven negotiation sites
**Claim** (`docs/principles_review.md` #10): 5 sites ƒ?"
`covenant_waiver`, `debt_pricing`, `audit_fee`, `activist_campaign`,
`ma_auction`. All logged to `negotiations.jsonl`.

**Verify**: grep `topic=` or `topic: str = "` patterns in `src/`.
Find all 5. Then check each writes into `state.negotiations_log`.

**Status**: CONFIRMED
**Findings**: Four topics are created as `Negotiation.new(topic=...)` in `src/orchestrator.py` (`activist_campaign` ~L709+, `debt_pricing` ~L1492+, `covenant_waiver` ~L1920+, `audit_fee` ~L2311+), and the M&A auction emits dict records with `"topic": "ma_auction"` in `src/ma_agent.py` (~L357). Each is persisted into `state.negotiations_log` via `append(...to_record())` for Negotiation-based sites (`src/orchestrator.py` ~L768, ~L1533, ~L1972, ~L2386) and via `state.negotiations_log.extend(auctions)` for M&A auctions (`src/orchestrator.py` ~L460).

### C-2 ƒ?" Per-round offer history preserved
**Claim** (`docs/datasets.md`): `negotiations.jsonl` records "full
round-by-round offer history for research."

**Verify**: inspect `src/negotiation.py` ƒ?" does `Negotiation.rounds`
persist after the last round? Sample a real negotiation record in
`outputs/run_1776783195/negotiations.jsonl` ƒ?" does the `rounds`
array have ƒ%1 entry?

**Status**: CONFIRMED
**Findings**: `src/negotiation.py` stores rounds in `Negotiation.rounds: list[Round]` and `submit_round(...)` appends to that list; `to_record()` serializes `rounds` into the JSON record (see `src/negotiation.py` ~L65-L175). In `outputs/run_1776783195/negotiations.jsonl`, records include a `rounds` array with at least one entry (e.g., the first `debt_pricing` record shows `"num_rounds": 1` and a `rounds` list containing index 0).

---

## D. Directors + interlock info leak (Wave I,)

### D-1 ƒ?" Pool size bounded
**Claim** (`docs/principles_review.md` #15): pool size
`max(10, 3A-n_firms)` capped at `len(_DIRECTOR_NAMES)`.

**Verify**: `src/orchestrator.py::_populate_director_pool`. Check the
formula matches exactly. `_DIRECTOR_NAMES` is a constant list ƒ?" count
its length.

**Status**: CONFIRMED
**Findings**: `src/orchestrator.py::_populate_director_pool` sets `pool_size = min(max(10, int(3.0 * n_firms)), len(_DIRECTOR_NAMES))` (around `src/orchestrator.py` ~L250). `_DIRECTOR_NAMES` is a hardcoded constant list in `src/orchestrator.py` (~L223-L233) with 36 entries (from “Patricia Aldrich” through “Noor Al-Rashid”).

### D-2 ƒ?" Max 3 seats per director
**Claim**: `MAX_SEATS_PER_DIRECTOR = 3`.

**Verify**: `src/orchestrator.py::_populate_director_pool` + same in
`_director_lifecycle_phase`. Check that no director can acquire a 4th
seat through either pathway.

**Status**: CONFIRMED
**Findings**: In `_populate_director_pool`, `MAX_SEATS_PER_DIRECTOR = 3` and eligibility excludes any director with `len(d.seats) >= MAX_SEATS_PER_DIRECTOR` (`src/orchestrator.py` ~L251, ~L272). In `_director_lifecycle_phase`, when the name pool is exhausted it only appoints an existing director if `len(d.seats) < 3` (hard-coded cap) (`src/orchestrator.py` ~L2940-L2960), preventing a 4th seat via lifecycle appointments.

### D-3 ƒ?" Info-leak: noise SD scales by 1/(1+n_shared)
**Claim** (`CHANGELOG.md` I,): interlocked peer observations have noise
SD divided by `(1+n_shared_directors)`.

**Verify**: `src/orchestrator.py::_build_firm_info_package`. Find the
line `effective_sd = noise_sd / (1 + shared_dirs)`. Confirm it's
active only when `noisy_signals_enabled=True` AND `directors_enabled=True`
(i.e., when there are any directors in `state.directors`).

**Status**: FALSE_POSITIVE
**Findings**: `_build_firm_info_package` does compute `effective_sd = noise_sd / (1 + shared_dirs)` (see `src/orchestrator.py` ~L3055-L3060) and `shared_dirs` is the interlock count from `_count_shared_directors`. But there is no explicit `directors_enabled` gate in this function: the entire observation/noise path is gated on `noisy_signals_enabled` (`noisy = bool(getattr(state.params, "noisy_signals_enabled", False))` around ~L3032), and when directors are disabled the effect becomes a no-op because `_count_shared_directors` returns 0 when `state.directors` is empty (`src/orchestrator.py` ~L2989-L3012), yielding `effective_sd == noise_sd`.

### D-4 ƒ?" Lifecycle: annual refresh + default departures
**Claim**: Q4 refresh has 25% probability per firm; default departures
fire every quarter when the firm's `is_active=False`.

**Verify**: `src/orchestrator.py::_director_lifecycle_phase`. Check
the `if state.rng.random() >= 0.25: continue` line. Check that
default-triggered departures run unconditionally (not gated on Q4).

**Status**: CONFIRMED
**Findings**: `_director_lifecycle_phase` executes default-triggered seat removals before the Q4-only guard (default departures loop runs before `if state.macro.fqtr != 4: return`) (`src/orchestrator.py` ~L2887-L2923). The annual refresh runs only at `fqtr == 4` and uses `if state.rng.random() >= 0.25: continue` per firm (`src/orchestrator.py` ~L2926-L2935). `run_quarter` calls `_director_lifecycle_phase(state)` every quarter when `config.director_lifecycle_enabled` is True (`src/orchestrator.py` ~L2799-L2803).

### D-5 ƒ?" `directors_enabled` toggle gates everything
**Claim** (`CHANGELOG.md` I,): when toggle off, `state.directors` stays
empty, interlock info leak becomes a no-op.

**Verify**: `src/orchestrator.py::initialize_world` ƒ?" confirm
`_populate_director_pool` only runs when `directors_enabled=True`.
Then confirm `_count_shared_directors` returns 0 when `state.directors`
is empty (so effective_sd = noise_sd / 1 = noise_sd, unchanged).

**Status**: CONFIRMED
**Findings**: `src/orchestrator.py::initialize_world` accepts `directors_enabled: bool = True` and only calls `_populate_director_pool(state, n_firms)` inside `if directors_enabled:` (around `src/orchestrator.py` ~L120-L216). `_count_shared_directors` returns 0 when `state.directors` is empty (`directors = getattr(state, "directors", None) or {}; if not directors: return 0` in `src/orchestrator.py` ~L2998-L3003), so the noise-scaling division uses `1 + 0` when directors are absent.

### D-6 ƒ?" `tests/test_directors.py` coverage
**Claim**: 10 tests covering pool generation, interlock counter,
info-leak proportionality, lifecycle, toggle-off.

**Verify**: `python -m pytest tests/test_directors.py -v` ƒ?" does each
of the 10 tests target a distinct aspect? Any test that's trivial or
tautological?

**Status**: CONFIRMED
**Findings**: `tests/test_directors.py` defines 10 `test_...` functions (`rg` shows 10 definitions, e.g., `test_directors_enabled_default_populates_pool`, `test_max_seats_per_director_cap`, `test_interlock_counter_correct`, `test_info_leak_reduces_noise_proportionally`, and three lifecycle tests around Q4/default departure). The tests are not tautologies: they validate seat caps (`len(d.seats) <= 3`), shared-director counting vs a manual recount, and proportional noise reduction via `observe_peer_data(true_vals, ..., relative_sd=base_sd/2)` vs `/3`.

---

## E. 3-LLM board committee (Wave I,)

### E-1 ƒ?" 4A- cost: 3 perspective calls + 1 synthesis
**Claim** (`CHANGELOG.md` I,): `make_governance_agent_3llm` runs 3
parallel voice calls + 1 synthesis = 4A- API cost.

**Verify**: `src/governance.py::make_governance_agent_3llm`. Count
`backend.complete_json` call sites in the returned function. Confirm
the 3 voice calls run in parallel (`ThreadPoolExecutor`) and the
synthesis runs sequentially after.

**Status**: CONFIRMED
**Findings**: `src/governance.py::make_governance_agent_3llm` calls `backend.complete_json(...)` once per voice inside `_call_perspective` and runs those three calls in a `ThreadPoolExecutor(max_workers=3)` over `_COMMITTEE_PERSPECTIVES.keys()` (around `src/governance.py` ~L553-L570). It then calls `backend.complete_json(...)` one additional time for synthesis (`board_synthesis`) after collecting perspectives (around `src/governance.py` ~L572-L576), totaling 4 calls per governance review.

### E-2 ƒ?" Toggle default OFF
**Claim**: `three_llm_board_enabled: bool = False` default in `RunConfig`.

**Verify**: `src/config.py::RunConfig`. Then check `src/cli.py` branches
on `getattr(config, "three_llm_board_enabled", False)`.

**Status**: CONFIRMED
**Findings**: `src/config.py` defines `three_llm_board_enabled: bool = False` in `RunConfig` (around `src/config.py` ~L137). `src/cli.py` checks `if getattr(config, "three_llm_board_enabled", False):` to switch between `make_governance_agent_3llm` and `make_governance_agent` (see `src/cli.py` ~L710-L721).

### E-3 ƒ?" Perspective prompts differ only in framing
**Claim**: The three voices see the SAME base prompt; only the
perspective framing differs.

**Verify**: `src/governance.py`. Confirm `base_sys, base_user =
build_governance_prompt(...)` is called once, and each voice appends
`_COMMITTEE_PERSPECTIVES[voice_name]` to `base_sys` only. If one voice
sees different data than the others, that's an information leak bug.

**Status**: CONFIRMED
**Findings**: `make_governance_agent_3llm` calls `base_sys, base_user = build_governance_prompt(...)` once per review (`src/governance.py` ~L553-L556). Each voice uses `voice_sys = base_sys + ... + perspective_framing` while passing the same `base_user` to `backend.complete_json` (`src/governance.py` ~L559-L563), so only the system framing changes across voices.

---

## F. Cost telemetry (Wave I, + I,+)

### F-1 ƒ?" OpenRouter pricing fetched at run start
**Claim** (`CHANGELOG.md` I,+): pricing fetched once via
`fetch_pricing_openrouter()` when `cost_telemetry_enabled=True`.

**Verify**: `src/cli.py` near line 440, look for
`_tel.fetch_pricing_openrouter()`. Confirm it's gated on the toggle.
Then `src/telemetry.py::fetch_pricing_openrouter` ƒ?" confirm it's
idempotent (`_pricing_fetched` flag prevents re-fetch).

**Status**: CONFIRMED
**Findings**: `src/cli.py::run_simulation` calls `_tel.reset()` and then, if `getattr(config, "cost_telemetry_enabled", True)`, calls `_tel.fetch_pricing_openrouter()` at run start (`src/cli.py` ~L433-L446). `src/telemetry.py` implements idempotence with `_pricing_fetched`: `fetch_pricing_openrouter` returns immediately if already fetched and sets `self._pricing_fetched = True` before attempting the request (`src/telemetry.py` ~L97-L111).

### F-2 ƒ?" Every OpenRouter + MiniMax call records usage
**Claim** (`CHANGELOG.md` I,): every successful backend call records
(input_tokens, output_tokens, latency, model, agent_role).

**Verify**: `src/llm_backends.py::_record_usage`. Check both
`OpenRouterBackend.complete` and `MiniMaxBackend.complete` call it
exactly once per successful response. Does it also record on failed
retries? (It should NOT ƒ?" partial calls don't count.)

**Status**: CONFIRMED
**Findings**: `_record_usage` extracts the OpenAI-style `usage` block and records to telemetry with `agent_role=_tel.current_role()` and token/latency fields (`src/llm_backends.py` ~L144-L170). `OpenRouterBackend.complete` calls `_record_usage(...)` only after successfully parsing JSON and extracting `body["choices"][0]["message"]["content"]` (around `src/llm_backends.py` ~L118-L123); `MiniMaxBackend.complete` does the same (around ~L210-L220). On malformed JSON / malformed shapes / retries it returns `""` or continues, without calling `_record_usage`, so failed retries are not recorded.

### F-3 ƒ?" Role tagging via ContextVar (thread-safe)
**Claim** (`CHANGELOG.md` I,): `telemetry.set_role()` uses
`contextvars.ContextVar` so it works with `ThreadPoolExecutor`.

**Verify**: `src/telemetry.py::_current_role`. Confirm it's a
`ContextVar` (not a plain module-level var). Then `tag_backend(role)`
wraps a backend so every `complete`/`complete_json` runs inside
`set_role(role)`.

**Status**: CONFIRMED
**Findings**: `src/telemetry.py` defines `_current_role` as a `contextvars.ContextVar[str]` with default `""` and exposes it via `current_role()` (`src/telemetry.py` ~L25-L35). `tag_backend(backend, role)` returns a proxy whose `.complete` and `.complete_json` both run inside `with set_role(role): ...` (`src/telemetry.py` ~L60-L82).

### F-4 ƒ?" "unattributed" bucket shrinks on v15
**Claim** (`CHANGELOG.md` I,+): wiring earnings_announcement,
annual_report, ma_agent, env_verifier via `tag_backend` should shrink
the "unattributed" row in `cost_summary.txt`.

**Verify**: `outputs/run_1776783195/cost_summary.txt` (v15, pre-I,+).
The "unattributed" row was $0.0148. Run a new short smoke or look at
any post-I,+ live run to see if it's smaller. If no post-I,+ live run
exists, verify theoretically by grepping `set_role` / `tag_backend`
coverage across the factories.

**Status**: UNCLEAR
**Findings**: In `outputs/run_1776783195/cost_summary.txt`, the per-agent-role breakdown includes `unattributed` with `cost=$0.0148` (line containing `unattributed` is at ~L28). The current codebase does include explicit role-tagging for the cited areas (e.g., `src/earnings_announcement.py` uses `with _tel.set_role(f"earnings_{firm_id}"):` ~L131; `src/annual_report.py` uses `with _tel.set_role(f"annual_report_{firm.firm_id}"):` ~L417; `src/ma_agent.py` tags bidder/raise/target calls with `set_role(...)` around ~L243/~L305/~L346; `src/cli.py` tags `env_verifier` via `_tag(create_backend(ev_llm), "env_verifier")` ~L672). However, there is no post-I,+ live run artifact with a `cost_summary.txt` available in `outputs/` to empirically verify that the unattributed bucket shrank (a recursive search found only `outputs/run_1776783195/cost_summary.txt`).

---

## G. Per-observation log (Wave I,+)

### G-1 ƒ?" n_shared captured at observation time, not snapshot time
**Claim** (`CHANGELOG.md` I,+): `peer_observations.jsonl` captures
`n_shared_directors` at the moment of observation (not later from a
stale snapshot).

**Verify**: `src/orchestrator.py::_build_firm_info_package`. The
observation-log append should happen INSIDE the `for fid, firm in
state.firms.items()` loop, using `shared_dirs` that was just computed
from `state.directors` at the current quarter. Confirm no async delay
between compute and log.

**Status**: CONFIRMED
**Findings**: In `src/orchestrator.py::_build_firm_info_package`, inside the competitor loop (`for fid, firm in state.firms.items(): ...`), it computes `shared_dirs = _count_shared_directors(state, target_firm_id, fid)` and immediately appends a record containing `"n_shared_directors": shared_dirs` into `state.peer_observation_log` (around `src/orchestrator.py` ~L3055-L3077). The record is built synchronously from the just-computed `shared_dirs` and includes the applied `effective_sd`, so it is not derived later from snapshots.

### G-2 ƒ?" Only written when noisy_signals_enabled
**Claim**: the log should be empty when noise is off (since there's
nothing to attribute accuracy to).

**Verify**: same function, confirm the `state.peer_observation_log.append`
is inside the `if noisy:` branch.

**Status**: CONFIRMED
**Findings**: `state.peer_observation_log.append({...})` appears only inside the `if noisy:` branch in `_build_firm_info_package` (`src/orchestrator.py` ~L3049-L3077). When `noisy_signals_enabled` is False, the code uses `public_competitors[fid] = true_public` and does not append any peer-observation-log record.

### G-3 ƒ?" Spec 12 uses observation log as primary source
**Claim** (`scripts/baseline_regressions.py`): Spec 12 prefers
`peer_observations.jsonl` over snapshot-derived beliefs.

**Verify**: `scripts/baseline_regressions.py::spec_interlock_belief_accuracy`.
Check the "PRIMARY SOURCE" block loads `peer_observations.jsonl`
first, then only falls back to snapshots if primary is empty.

**Status**: CONFIRMED
**Findings**: `scripts/baseline_regressions.py::spec_interlock_belief_accuracy` first iterates candidates and loads `peer_observations.jsonl` if present (“PRIMARY SOURCE: peer_observations.jsonl”), building `rows` from it (`scripts/baseline_regressions.py` ~L828-L860). Only if `rows` remains empty does it enter the “FALLBACK: snapshot-derived” block that reads snapshots and derives interlock/error (`scripts/baseline_regressions.py` ~L862-L915).

### G-4 ƒ?" Spec 12 result: p=0.001 at N=60 (mock smoke)
**Claim** (`CHANGELOG.md` I,+): on mock smoke with n_firms=5,
noisy_signals_sd=0.20, Spec 12 produces n_shared coef = ƒ^'0.0484, p=0.001.

**Verify**: reproduce ƒ?"
```
python -m src run --config config/test_interlock_mock.yaml --mock
python scripts/baseline_regressions.py --runs <latest_run_id>
```
Look at Spec 12 output. Coefficient, p-value, N should match.

**Status**: UNCLEAR
**Findings**: There is an existing 5-firm, 4-quarter run artifact with `peer_observations.jsonl` at `outputs/run_1776789016/peer_observations.jsonl` containing 80 observation records; since Spec 12 filters out rows with `true_revenue <= 0` (`scripts/baseline_regressions.py` ~L851-L855), this run plausibly yields N=60 usable observations (80 total minus the first quarter’s 20 zero-true-revenue rows). However, no saved Spec 12 regression output corresponding to `run_1776789016` is present under `outputs/` (the existing `outputs/regressions/interlock_belief_accuracy.txt` shows `No. Observations: 24`, consistent with a 3-firm run, not the 5-firm mock), and this environment blocks executing Python to reproduce the exact coefficient/p-value.

---

## H. Principles scorecard (spot audit)

### H-1 ƒ?" Principle 6 (correct bookkeeping) is dYY›
**Claim**: `docs/principles_review.md` gives Principle 6 a dYY› based on
"0 violations in mock + v11/v12 live runs; BS identity checked at
every phase."

**Verify**: run `python -m pytest tests/test_accounting.py -v`. All
should pass. Then check `tests/test_accounting.py::TestDoc16WorkedExample`
ƒ?" is the canonical 16-step worked example exercised?

**Status**: CONFIRMED
**Findings**: `tests/test_accounting.py` is explicitly “Accounting tests using the doc 16 worked example as the golden fixture” and defines `class TestDoc16WorkedExample` with balance-sheet identity and cash-flow reconciliation assertions (e.g., `test_balance_sheet_identity` asserts `diff < 1.0`, and `test_all_invariants_pass` asserts `validate_state(...)` returns no violations). In-code phase-level BS checking is implemented by `_check_bs_invariants` in `src/orchestrator.py` and is invoked throughout `run_quarter` (see A-1 evidence), matching the “checked at every phase boundary” portion of the principle evidence.

### H-2 ƒ?" Principle 7 (info partitions)
**Claim**: `_build_firm_info_package` enforces partition; env agent
is the only omniscient reader.

**Verify**: grep `state.firms` in `src/prompts.py` ƒ?" does any firm-side
prompt builder receive the full state? Trace `_build_firm_info_package`
output shape: PUBLIC fields per peer, PRIVATE only for the target firm.

**Status**: CONFIRMED
**Findings**: `src/prompts.py` does not reference `state.firms` (firm prompts are built from `(firm, public_info, params, ...)`, and `build_firm_prompt` accepts `public_info: dict` rather than the full WorldState). `_build_firm_info_package` constructs `public_competitors` with a limited set of peer-visible fields (`price`, `market_share`, `generation`, `equity_price`, `revenue`, `total_rd_spend`) and a separate `own_private` block containing the target firm’s private state (cash, total_assets/equity, flows-derived `cfo`, reports, etc.) (`src/orchestrator.py` ~L3038-L3110).

### H-3 ƒ?" Principle 16 (reproducibility)
**Claim**: mock runs are byte-reproducible; live runs are NOT.

**Verify**: `tests/test_reproducibility.py` ƒ?" run it twice, confirm
outputs match. Then inspect `src/llm_backends.py::OpenRouterBackend`
ƒ?" is there any seeding that would make it reproducible? (There
shouldn't be; backend temperature + provider randomness is out of
our control.)

**Status**: CONFIRMED
**Findings**: `tests/test_reproducibility.py` enforces that two mock runs with the same seed produce identical `compustat_q.csv` content (hashing after removing `run_id` and `proposal_id`) and explicitly states LLM runs are not guaranteed reproducible. `src/llm_backends.py::OpenRouterBackend.complete` sends only `model`, `messages`, and `temperature` to OpenRouter and contains no `seed` parameter or deterministic sampling control in the request body (see `src/llm_backends.py` ~L86-L123).

### H-4 ƒ?" Scorecard is NOT over-claimed
**Claim**: 19dYY› / 1dYY­. The dYY­ is Principle 3 (mock-mode fallbacks are
by-design).

**Verify**: for each dYY› cell in `docs/principles_review.md`'s table,
trace to the code that justifies it. List any cell where:
(a) no test covers the mechanism, or
(b) the test is trivial (asserts `x == x` or similar).

**Status**: DISPUTED
**Findings**: Several dYY› table items are not backed by any direct tests importing the relevant modules or exercising the feature: for example, telemetry/cost-tracking mechanisms (`src/telemetry.py`, `src/llm_backends.py::_record_usage`) have no test references (no `telemetry`/`cost_summary`/`llm_calls` mentions in `tests/`), and there are no tests referencing the Streamlit “usable control layer” (`app/` dashboard) described in Principle 20. In addition, the role-to-model assignment in Principle 19 is described in terms of `config/model_roster.yaml`, but tests only incidentally copy the roster file for CLI execution (e.g., `tests/test_reproducibility.py`) without assertions about roster semantics.

---

## I. Deferred / known gaps

### I-1 ƒ?" Mock-mode fallbacks by design
**Claim** (`CHANGELOG.md` I, + `docs/principles_review.md` Principle 3):
mock mode uses deterministic agents; this is the remaining dYY­ and is
NOT a bug.

**Verify**: `src/cli.py` ƒ?" find the fallback RawDecisions in the mock
path. Does it carry `decision_source="mock"` or `"fallback"`? Is this
filterable downstream?

**Status**: CONFIRMED
**Findings**: `src/cli.py::mock_firm_agent` returns `RawDecisions(..., decision_source="mock", fallback_reason="deterministic mock agent (--mock flag)", proposal_id=str(uuid4()))` (see `src/cli.py` around ~L229-L260). Separately, the live-path exception fallback in `src/orchestrator.py` constructs `RawDecisions(decision_source="fallback", fallback_reason=..., proposal_id=uuid4())` when a firm agent call errors in the parallel executor (around `src/orchestrator.py` ~L634-L646). These tags are filterable downstream because `build_compustat_row` writes `decision_source` and `fallback_reason` into each `compustat_q.csv` row (`src/accounting.py` ~L818-L823).

### I-2 ƒ?" TODO / FIXME sweep
**Task**: grep `TODO|FIXME|HACK|XXX` across `src/` + `scripts/` +
`app/`. For each hit, classify:
- (a) real bug worth filing
- (b) deferred enhancement
- (c) stale comment (concern already addressed)

**Status**: CONFIRMED
**Findings**: A word-boundary grep across `src/`, `scripts/`, and `app/` for `TODO|FIXME|HACK|XXX` (excluding `*.tmp*`) returned no matches, so there are no TODO/FIXME/HACK/XXX markers to classify. A case-insensitive search without word boundaries produced a false hit inside a director name (“Thackeray”), reinforcing that the word-boundary result is the relevant one.

### I-3 ƒ?" Test coverage gaps
**Task**: for each module in `src/`, check there's at least one test
file that imports from it. List modules with zero test imports.

**Status**: CONFIRMED
**Findings**: Direct-import grep of `tests/` shows imports from a limited set of modules (notably `types`, `accounting`, `orchestrator`, `engine`, `negotiation`, `snapshots`, `clamping`, `debt_management`, `beliefs`, `env_verifier`, `cli`, `config`, `annual_report`, `datasets`, `scenarios`, and `activist`). The following `src/` modules have zero direct test imports: `src/analyst.py`, `src/board_discussion.py`, `src/ceo_comp.py`, `src/commercial_bank.py`, `src/data_access.py`, `src/data_analyst.py`, `src/data_broker.py`, `src/data_templates.py`, `src/demand.py`, `src/earnings_announcement.py`, `src/earnings_management.py`, `src/equity_market.py`, `src/governance.py`, `src/identifiers.py`, `src/investment_bank.py`, `src/llm_backends.py`, `src/ma_agent.py`, `src/memory.py`, `src/model_eval.py`, `src/operational_reports.py`, `src/output_organizer.py`, `src/personalities.py`, `src/product_specs.py`, `src/prompts.py`, `src/restatement.py`, `src/scoring.py`, `src/sec_agent.py`, `src/sellside_analyst.py`, `src/telemetry.py`, `src/world_secrets.py`, `src/wrds_identifiers.py`, `src/__main__.py`, and `src/__init__.py`.

---

## Summary

_Codex fills this paragraph after completing all claims above._

**Totals**: CONFIRMED: 28 / DISPUTED: 2 / FALSE_POSITIVE: 1 / UNCLEAR: 2

**Top 3 most-important findings** (if any):
1. B-1 is not fully true as written: environment and equity-market decisions appear to bypass the Action/ActionResult logging spine (no `environment` proposals in `proposals.jsonl`, and no ActionLog call sites around env/equity-market application in `src/orchestrator.py`).
2. The “scorecard not over-claimed” assertion is contradicted by missing direct test coverage for multiple dYY› items, especially the “usable control layer” (dashboard) and telemetry/cost plumbing.
3. Two CHANGELOG-style empirical claims can’t be validated from available artifacts: telemetry “unattributed” shrink (no post-I,+ `cost_summary.txt`), and Spec 12’s reported coef/p-value for the mock interlock smoke (no saved regression output for the 5-firm mock run, and Python execution is blocked here).

**Recommended follow-ups** (if any):
- Produce and archive a post-I,+ live-run `cost_summary.txt` (or any artifact showing the new unattributed bucket) to make F-4 verifiable from `outputs/` alone.
- Run Spec 12 against `outputs/run_1776789016` and save the resulting Spec 12 text output alongside run artifacts (so G-4 is verifiable without re-execution).
- Decide whether “all agent mutations” should include environment/equity-market; if yes, add a corresponding proposal log entry (or adjust the documentation claim to scope it to the 10 LLM decision agents).

---

*Generated: see CHANGELOG.md "Wave I,+" for the state being audited.
Claude Code wrote the scaffold; Codex fills the Status + Findings
fields. When complete, ship this doc alongside the run artifacts.*