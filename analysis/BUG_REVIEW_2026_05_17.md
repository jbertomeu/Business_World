# Bug Review — 2026-05-17 (full sweep across runs 1–6)

> Triggered after run-6. User asked for a full review of all bugs
> before launching the next run. Wave ν+14 had landed three fixes
> from the run-6 review but did not address the underlying causes.

## Critical bugs found in this sweep

### Bug 1: Ch11 reorganisation leaves treasury_stock intact → cumulative phantom equity destruction

**Symptom:** firm_0 in run-6 ended with -$9.95B in equity, when actual
net assets - liabilities was ~-$807M. Excess negative equity = -$9B
phantom destruction over 65 quarters.

**Root cause:** `src/bankruptcy.py::enter_chapter_11` wipes
`common_stock=0` and `apic=0` (cancelling old shareholder capital
when new shares are issued to creditors) but leaves
`treasury_stock` at its pre-default value. Since `CEQ = CS + APIC + RE - TS`,
treasury stock keeps subtracting from equity forever.

Pattern in run-6 firm_0: buybacks accumulated $200M of TS, firm
defaulted, Ch11 wiped APIC, TS stayed at $200M. Next quarter firm
operated again, did more buybacks → TS grew, next default wiped APIC
again. Pattern compounded over 65 quarters.

**Fix landed:** `enter_chapter_11` now also sets `treasury_stock=0.0`.

### Bug 2: Backends only built for `n_firms_initial`, not `n_firms_max` → spawned firms permanently dormant

**Symptom:** run-6 ended with 16 of 20 firms dormant. Quarter logs showed
**1100+ "PE: firm_X pitch LLM failed; skipping round"** messages.
Initially attributed (incorrectly) to PE eval rejecting pitches; that's
why Wave ν+14 added the "BUT — REAL PE FUNDS ALSO MAKE SEED BETS" prompt.

**Real cause:** `src/cli.py` builds `backends = {firm_i: ...}` in
`for i in range(n_firms)` where `n_firms = config.n_firms_initial = 6`.
Per-firm pitch / IPO / prospectus / planning fns are then constructed
`for fid in backends`. When the entry judge spawns firm_6, firm_7,
…, firm_19 partway through the run, those firms have NO backend.
`pitch_fns_per_firm.get("firm_7")` returns `None`. The dispatcher
silently returns `None`. The orchestrator's `if pitch is None:` branch
logs "pitch LLM failed" and skips. Firm stays dormant.

**Fix landed:** backends now built for `max(n_firms_initial, n_firms_max)`
slots. Pitch fns / IPO fns / prospectus fns / planning fns inherit
correctly.

**Side effect:** the Wave ν+14 PE seed-bet softening is now redundant
for fixing dormancy (but still good language to keep — it reflects
real-world PE behaviour). Dormant cleanup mechanism (wind down at
12Q) becomes relevant only when the PE evaluator genuinely passes.

### Bug 3: Pitch failure log message was indistinguishable from real LLM failure

**Symptom:** "PE: firm_X pitch LLM failed" appeared 1100+ times in
run-6 — looked like rate-limiting, was actually dispatcher-miss.

**Fix landed:** message now reads "pitch unavailable (None) — check
that a backend exists for this firm in cli.py" so the dispatcher case
is distinguishable.

## Bugs from prior runs (already fixed, verified)

| Run | Bug | Fix wave |
|---|---|---|
| run-2 | 362 phase_2_ipo BS violations | Wave ν+11 (verified: run-6 has 0) |
| run-3 | TAM overshoot to $8.3T/Q | Wave ν+11 capacity-PPE coupling |
| run-3 | 70 phase_2_ipo BS violations on firm_3 | Wave ν+11 |

## Bugs not yet fixed (deferred)

### Equity panel issuing P/S < 0.01 for Gen-N firms

**Status:** Wave ν+14 added scale sanity check + earnings-based floor
language to the equity panel prompt. Not yet validated under live LLM
behaviour. Run-7 will test.

### env-1 deepseek-v3.2 ignores strict directive even after retry

**Status:** Wave ν+13 added deterministic force-grant after retry, so
even if env-1 is stubborn, the validator mutates the output. This is
the safety net rather than a fix; the underlying behaviour (env-1
not following its own strict-tier directive) is unchanged.

## Lower-priority issues found during sweep

- **Debriefs fire for dormant firms** (1451 firm-debrief notes for 4
  truly-active firms over 80Q ≈ ~1100 wasted LLM calls). Should skip
  is_dormant=True firms in `debriefs` phase.
- **ENV ANOMALY (50 events)** firm_5/firm_1 routinely allocate units
  beyond production cap. The verifier catches and clamps; not a
  blocker but suggests env over-allocates by ~20-30% on high-volume
  firms. Could tune the env prompt's production-cap awareness.

## Verification

- 365 tests pass after both fixes
- 3Q smoke clean
- New behaviour to validate in run-7:
  - All 20 firm slots get backends (smoke test confirms n_backend_slots=20)
  - Firm_0-equivalent doesn't accumulate phantom negative equity
  - Spawned firms can issue pitches and (sometimes) close rounds

## Commits

- `cb12603` — Wave ν+14 (equity panel, PE soft, dormant cleanup)
- (this commit) — Bug review fixes (Ch11 treasury, n_firms_max
  backends, log diagnostic)
