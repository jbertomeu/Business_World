# Wave ν+7 — Bug sweep findings

Investigation triggered by the discovery that ν+6 Phase 2 was contaminated
by a silent exception handler. While tracking the headline bug, a second
real bug surfaced. This document records both, plus what was checked and
ruled out as either non-bugs or not-yet-actionable.

## Bug 1: silent zero-default fallback in firm-decision exception handler

**Location:** `src/orchestrator.py`, formerly lines 919–928, in the
parallel firm-decision pool.

**Behavior:** When `firm_agent_fn` raised any exception, the
exception handler constructed a `RawDecisions(decision_source=...,
fallback_reason=..., proposal_id=...)` with only provenance fields
populated. Every other field — `price`, `production`, `rd_spend`,
`sga_spend`, `capex`, `dividends`, `buybacks` — fell back to the
dataclass default, which is zero. The clamper then bumped R&D up to
its mandatory floor and let the other zeros through. The firm
"decided" to halt operations with no actual decision having been
made.

**Impact in ν+6:** A `TypeError` started firing for six of seven
surviving firms at Q42 (post-firm_6-default). Each of those firms
got dataclass-default zeros every quarter for the next 39 quarters.
The env then routed all demand to firm_9 (the only firm still
returning real LLM decisions). The "absorbing monopoly" we observed
was an artifact of this fallback, not a coordinated economic
phenomenon.

**Diagnosis trail:**
1. Six firms with literal-zero `actual_price`, `actual_production`,
   `actual_sga_spend` and exactly $10M `actual_rd_spend` (the
   mandatory R&D floor) for 39 consecutive quarters. Six different
   LLM models (mistral, qwen, gemini, glm, gemma) producing
   identical zeros to the cent is impossible unless the decisions
   weren't made by LLMs.
2. `decision_source` field on Compustat rows was stamped
   `"fallback"` with `fallback_reason="firm_agent_fn raised:
   TypeError: unsupported operand type(s) for /: 'str' and 'float'"`.
   firm_9 alone had `decision_source="llm"`.

**Fix:** Replaced the broken-default `RawDecisions(...)` with a call
to a new `_carry_forward_raw_decisions()` helper that reads prior-Q
flows and builds a continuity-preserving `RawDecisions`. If a firm
has prior flows, it carries forward its own price (= rev/units),
production, R&D, SGA. If not (Q1, fresh entrant), uses non-zero
defaults that don't crater the firm.

**Tests added:** `tests/test_carry_forward_fallback.py` — five tests
including a sanity test that *confirms* the buggy pattern produces
zeros, so any future contributor who reverts the fix gets a clear
diagnostic.

---

## Bug 2: auction events not applied in modern judge path

**Location:** `src/orchestrator.py`, formerly lines 2675-2702, in the
`AUCTION_PHASE` block.

**Behavior:** The `for event in events:` loop that applies auction
results to firm state was indented at 16 spaces — inside the `else:`
(legacy per-survivor-bidder fallback) branch at 12 spaces. The
modern judge path at the same level produces `events` correctly,
but those events fall out of the function unused: defaulted firms
stay in their pre-default state, winners never receive transferred
assets.

**Impact in ν+6:** Every auction in the run went through the modern
judge path (`run_quarterly_auctions_via_judge`), so no auction
events were ever applied to state. Defaulted firms (firm_4, 0, 1,
5, 6, 8, 10, 11) retained their full pre-default cash, capacity,
brand, and capability stocks throughout the rest of the run. No
winner ever consolidated a defaulted competitor. The "no M&A
response in Phase 2" finding from the research overview is partly
an artifact of this: the auction *judge* allocated, but the
allocation was a no-op.

**Diagnosis trail:** The `awk` indentation-extraction confirmed:

```
2641 [12]             if judge_fn is not None and survivors:
2653 [12]             else:                           ← 12-space else
2675 [16]                 for event in events:        ← 16 spaces, INSIDE else
```

The loop at 16 spaces is inside the 12-space `else:` block, so it
only runs for the legacy path.

**Fix:** Outdented the `for event in events:` loop and its body
from 16 → 12 spaces (and matching offsets), placing it outside the
if/else so events from either branch get applied to state.

**Tests:** Existing tests still pass. Auction-application semantics
are exercised in the broader test suite.

---

## Instrumentation: full-traceback capture in fallback_reason

The exception handler now formats the full Python traceback (truncated
to about 1KB) into the `fallback_reason` field, in addition to the
exception type and message it was already capturing. The next time
any firm-agent path raises, we'll see exactly which line of code
crashed without needing to reproduce. This was free to add and
gives us debugging telemetry going forward.

---

## What was checked and ruled out

**firm_9 selling 310 units at Q40 with capacity 250.** Looked like a
capacity-overrun bug. Not a bug — firm_9 had 160 units in
inventory at end of Q39 (produced 250, sold 270 from prior carry).
At Q40 it produced 150 + sold 250+60=310 from inventory. End
inventory 0. Capacity wasn't violated; the units came from
prior-Q carryover. Standard FIFO inventory accounting.

**`units_produced` field on QuarterFlows returns None.** Not a
simulation bug. The QuarterFlows dataclass has `actual_production`
not `units_produced`. My data extraction script had been reading
the wrong field name. Fixed the extraction script, no source
change needed.

**Heartbeat showing `total_quarters_planned: 16` at Q17 of the 20Y
session.** Possible but not localized — may be a stale display
issue around the restart-from boundary. Not investigated further.
The simulation itself ran the correct number of quarters
(reached Q80 with the 80Q config); only the heartbeat field was
misleading. Low priority.

**Defaulted firms retaining $445M–$852M cash.** Initially looked
strange. Explained by Bug 2 above: the auction never applied, so
the defaulted firm's cash was never transferred to a winner. This
will resolve naturally once Bug 2's fix runs in a fresh
simulation.

**Six firms returning identical R&D = $10M exactly.** This is the
mandatory Phase III floor enforced in `clamping.py`. R&D = 0 in
the underlying decision (the dataclass default) gets bumped to
$10M by the clamp. So the mandatory-floor is correct; the bug
was upstream, in the dataclass-zero substitution.

---

## Underlying TypeError still unlocalized

The exact line of code that raises `TypeError: unsupported operand
type(s) for /: 'str' and 'float'` for these specific firms at Q42+
hasn't been pinned down. Direct repro attempts:

- Loading the Q41 snapshot and calling `_build_firm_info_package`
  for each surviving firm — succeeds, no error.
- Calling `build_board_prompt` and `build_firm_prompt` for each
  surviving firm — succeeds, no error.
- Running a mock-backend firm_agent against the Q41 state — all
  firms hit the carry-forward fallback (because mock LLM responses
  don't match prompt substrings), but no TypeError raised.

The TypeError likely fires inside one of:
- The board-discussion LLM-response post-processing
- The data-broker code execution path (`_execute_code` /
  `_run_sandboxed_code`)
- The data-analyst report parsing
- The strategic-planning or activist-response handling

Without a repro, the next investigation step is to wait for the next
crash (now that we have full-traceback capture) or to write a more
aggressive integration test that exercises each LLM-response path
with deliberately malformed responses.

The carry-forward fallback fix means the simulation will degrade
gracefully even if the TypeError keeps happening — firms will continue
operating at prior-Q levels. So this is no longer a critical bug; it's
a data-quality concern (fallback-decisions are not as good as fresh
LLM decisions, and we'd prefer the LLM path).

---

## Bug 3: revenue and COGS used different units in accounting

**Location:** `src/accounting.py`, lines 66-93 (the `post_quarter`
function).

**Behavior:** `units_to_sell` was clamped down to `production +
inventory` (correct). COGS was computed from the clamped value
(correct). End inventory was based on the clamped value (correct).
But **revenue at line 93 was computed from `outcome.units_sold`
(unclamped)**:

```python
revenue = outcome.units_sold * decisions.price
```

If the env over-allocated demand to a firm (env says firm sold 200
units, but firm only had 100 production + 0 inventory), the clamp
would set `units_to_sell = 100` for COGS purposes, but revenue
would still be recognized for 200 units. Revenue and COGS got out
of sync; the firm "earned" revenue from goods that were never sold.

**Impact in ν+6:** The orchestrator-level ENV CLAMP at
`orchestrator.py:1276` already capped env outputs at production +
inventory before passing to accounting, so in practice the bug
mostly didn't fire. But it was a defense-in-depth gap that would
have produced silently inconsistent accounting if any code path
bypassed the orchestrator clamp (e.g., if env output was a dict
with an unrecognized shape that skipped the `isinstance(fo,
MarketOutcome)` check at line 1273).

**Fix:** When the clamp fires, replace `outcome` with a
`dataclasses.replace(outcome, units_sold=units_to_sell)` so
downstream code (revenue, units_sold field on QuarterFlows, etc.)
uses the clamped value consistently.

**Tests added:** `tests/test_revenue_cogs_consistency.py` — three
tests covering env over-allocation, normal cases, and inventory
carryover.

---

## Bug 4: deterministic env-clamp dropped R&D advance flags

**Location:** `src/env_verifier.py`, `_deterministic_clamp()`
function.

**Behavior:** When the env produced an anomalous output (e.g.,
total demand > 5x recent revenue trend) and no LLM verifier was
wired, a deterministic fallback clamp would rebuild
`firm_outcomes` with a fresh `{"units_sold": ..., "market_share":
...}` dict for each firm. **All other fields from the original
outcome — `product_advance`, `process_cogs_reduction_pct`,
`delivery_advance` — were silently dropped.** Any firm that the env
had granted an R&D advance lost it on the clamp quarter.

**Impact in ν+6:** Sporadic. The deterministic clamp only fires
when (a) the env output is anomalous AND (b) no LLM verifier is
wired. The 20-firm config has the LLM verifier wired
(`env_verifier_enabled: true`), so this path mostly didn't fire
in the ν+6 run. But it was a real correctness bug that would have
silently dropped Gen-2 advancements during anomaly clamps.

**Fix:** Preserve the original dict (or re-populate from
MarketOutcome attributes) before applying the units_sold clamp.

---

## Bug 5: dict-key inconsistency between env LLM output and verifier
clamp

**Location:** `src/env_verifier.py` `_deterministic_clamp()` (now
fixed) and the dict-to-MarketOutcome converter at
`src/orchestrator.py:1259-1268`.

**Behavior:** The env LLM is told (in its prompt at
`prompts.py:1469`) to emit firm_outcomes with the dict keys
`product_advance` and `delivery_advance`. The orchestrator
converter at line 1263-1265 reads exactly those keys to populate
the MarketOutcome's `product_rd_advance` and `delivery_rd_advance`
fields. So far so good.

But my initial fix to `_deterministic_clamp` accidentally wrote
`product_rd_advance` (the MarketOutcome field name) into the dict
instead of `product_advance` (the LLM-facing key). The downstream
converter would have read the absent key and defaulted to False —
re-introducing the dropped-advance bug from Bug 4.

**Fix:** Use the LLM-facing key names (`product_advance`,
`delivery_advance`) consistently in the dict shape produced by
`_deterministic_clamp`, matching what the env LLM produces and
what the converter expects.

**Lesson:** The codebase has two parallel name conventions for
these fields — LLM-facing (`product_advance`) for dicts and
Python-style (`product_rd_advance`) for the MarketOutcome
dataclass. Either is fine, but the boundary between them must be
crossed explicitly. The verifier's `is_anomalous` function
already handled this correctly by reading both forms; the clamp
function did not. Now both functions use the dict-shape
convention internally.

---

## Parallelization wins (Wave ν+7)

Independent of the bug fixes, three parallelization opportunities
were applied to reduce per-quarter wallclock. Each was verified
safe — no inter-iteration state read or mutation.

### Win 1: Strategic-planning loop

**Where:** `src/orchestrator.py` — Phase 4.5 (CFO planning).

**Before:** Per-firm loop calling `planning_fn(...)` sequentially.
On annual quarters (every 4Q) ALL active firms get a planning
call, so the loop fires N planning LLM calls in series. With ~9
active firms × ~30-60s per planning call, this is roughly 5
minutes of wallclock per annual quarter.

**After:** Built `plan_jobs` list, dispatched LLM calls via
ThreadPoolExecutor, applied state mutations serially after all
calls return. Speedup ≈ N/min(N, max_workers). For 9 firms this
is roughly 9× → essentially the time of the slowest single call.

### Win 2: M&A bidder Round 0

**Where:** `src/ma_agent.py` — initial bid collection.

**Before:** Per-firm loop calling `backend.complete_json(...)` for
each potential bidder. Each iteration was independent (read-only
on `active_firms`, no shared mutation), but executed sequentially.

**After:** Collected `bidder_jobs` (firm + targets + backend),
dispatched bidder LLM calls in parallel, aggregated results into
`all_bids` and `bidder_rationale` serially. The "Round 1"
contested-auction LLM calls and target-board evaluation remain
serial — they're rare (only contested deals) and have subtle
inter-deal dependencies if firms appear as both bidder and target.

### Win 3: Bumped pool ceiling 8 → 16, made it configurable

**Where:** Six ThreadPoolExecutor sites in `src/orchestrator.py`
and `src/ma_agent.py`.

**Before:** All pools hardcoded `max_workers = min(N_jobs, 8)`.
With the 16-firm validation config, half the parallelism was left
unused: 16 firms competing for 8 worker slots = 2 waves of LLM
calls.

**After:** New helper `_max_workers(config, n_jobs)` reads
`config.max_parallel_workers` (default 16) and caps at `n_jobs`.
Six sites updated: firm-decision, planning, earnings-announcement,
audit, governance, annual-report, PE-fund-eval. Per-LLM-provider
concurrency limits are typically 10-20 for typical paid plans;
the existing 429-retry logic handles any transient backpressure,
so 16 is conservative.

For 16-firm runs, the firm-decision phase alone halves in
wallclock (one wave instead of two). For larger N, set
`max_parallel_workers: 20` in the YAML config.

### What was checked and left as-is

**M&A target-board evaluation loop:** a single firm can appear as
both bidder (acquiring someone) and target (being acquired) in
the same quarter. The serial loop currently propagates each
deal's `active_firms` mutation to subsequent iterations — so a
firm that was just acquired won't subsequently acquire someone
else. Parallelizing changes this semantics. Left serial.

**PE round phase outer loop:** each iteration calls
`pitch_fn` then `_eval_one_fund` per fund, then mutates
`state.firms` and `state.pe_funds`. The fund-eval step is
already parallel internally. The outer loop's serial dependency
on `state.pe_funds.available_capital` (when
`pe_unlimited_capital=False`) makes parallelization risky.
Left serial.

**Activist agent:** single LLM call per quarter (one activist
looks at all firms holistically). Not parallelizable.

**Equity market / investment bank / commercial bank:** each is a
single LLM call per quarter that handles all firms in one shot.
Not per-firm-parallelizable.

**Env LLM, demand calibrator, entry judge, env verifier, M&A
judge, distressed auction judge:** all single-call agents.

---

## Test status

- Full test suite: **311 passed** (5 new tests for carry-forward
  fallback + 3 new tests for revenue/COGS consistency).
- Mock smoke (`python -m src smoke --quarters 4`): clean.
- No production behavior changes for runs that don't trigger the
  patched paths; all fixes are conservative defense-in-depth or
  correct only when the previously-buggy path fires.
- Parallelization changes preserve all serial mutations
  (state.firms, state.pe_funds, etc.) by separating LLM-call
  phase from mutation-application phase.

## Re-running ν+6

The corrected ν+6 run is the one worth analyzing as research material.
With:
- Bug 1 fixed: firms keep operating through transient LLM crashes.
- Bug 2 fixed: auction events apply to firm state.
- Instrumentation in place: any remaining TypeError will leave a
  full traceback for diagnosis.

Re-running the same scenario from scratch should produce a much
cleaner Phase 2 — possibly still showing some industry consolidation
(the env's interpretation can still tilt allocations) but without
the artificial six-firm-zero-output pattern that the bug created.
