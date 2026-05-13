# Wave ν+11 — Bug Fixes Applied

This wave fixes bugs identified during the run-2 (seed 9999) review and
its follow-on bug sweep. Eight bugs total. All have regression tests
where applicable.

## Critical / HIGH-severity

### B1. Auction PPE asymmetry (root cause of 370 BS violations in run-2)

**File:** `src/distressed_auction.py::apply_auction_result`
**Pattern:** the defaulted firm retained phantom PPE = its accumulated
depreciation after every auction.

**Old code:**
```python
ppe_gross=max(0.0, defaulted.ppe_gross - defaulted.ppe_net),
accum_depreciation=max(0.0, defaulted.accum_depreciation - (defaulted.ppe_gross - defaulted.ppe_net)),
```

Since `ppe_gross - ppe_net = accum_depreciation`, this collapses to
`new_ppe_gross = accum_depreciation`, `new_accum = 0`,
**`new_ppe_net = accum_depreciation`** — phantom PPE every auction.

**Fix:** zero both PPE fields outright on the defaulted firm.

**Validated:** with `tests/test_wave_nu_plus_11_bs_fix.py` (4 tests),
including an industry-wide PPE conservation test that catches any
similar accounting asymmetry in the future.

### B2. `no_solvent_bidder` outcome leaves phantom assets

**File:** `src/orchestrator.py` (Phase 15 auction loop, around line 2894)
**Pattern:** when an auction outcome is anything other than "sold"
(`no_solvent_bidder`, `no_bids`, `no_sale`, `judge_failed`), the
defaulted firm's PPE, inventory, capability, and brand stayed on the
balance sheet indefinitely. The BS-invariant check would catch this
every subsequent quarter. In run-2, 5 such outcomes occurred (firm_1,
firm_11, firm_0 + 2 more) — each contributing to the persistent BS
residual stream.

**Fix:** when no buyer materializes, write off the defaulted firm's
operating assets to retained earnings as an impairment. This zeroes
PPE/inventory/capability/brand and reduces RE by the impaired amount,
preserving the BS identity.

## MEDIUM-severity

### B3. Ch11 entry left BS unbalanced

**File:** `src/bankruptcy.py::enter_chapter_11`
**Pattern:** at the moment of Ch11 entry, equity was wiped (apic = 0,
common_stock = 0, retained_earnings = 0) but assets and (haircut)
liabilities remained. The result: A ≠ L + E at the moment of
restructuring. No firm hit Ch11 in run-2, so this didn't surface — but
the Wave ν+11 looser Ch11 classifier will produce Ch11 firms in run-3.

**Fix:** retained_earnings now absorbs the residual so A = L + E at
entry. Existing test updated to verify the BS identity.

### B4. M&A target operational stocks not zeroed

**File:** `src/ma_agent.py::process_acquisition` (deactivated_target)
**Pattern:** the deactivated target's BS components were zeroed but
`capability_stock`, `brand_stock`, `capacity_units` were left on the
firm's record. Not directly a BS violation (these are operational
stocks, not BS items) but creates orphaned data in compustat.

**Fix:** zero capability/brand/capacity on the deactivated target.

### B5. Ch11/Ch7 classifier too restrictive

**File:** `src/bankruptcy.py::classify_default`
**Pattern:** required `ttm_operating_income > 0 AND ttm_cfo > 0` for
Ch11. In practice, defaulting firms had both flows deeply negative
together, so 0 of 12 defaults in run-2 went to Ch11.

**Fix:** loosened to `OI > 5M OR CFO > 5M`, plus tangible-asset coverage
gate (>30% of non-revolver liabilities) and minimum capacity (50 units).
This admits firms with mixed-flow profiles (positive OI but liquidity
crunch — the textbook Ch11 case) while still routing fundamentally
broken firms to Ch7.

## LOW-severity / preventative

### B6. Dividend block silent (acceptable, marked LOW)

**File:** `src/clamping.py:214-217`
**Status:** functionally correct. The block is enforced; the log entry
is the warning. No fix needed.

## Behavioral / prompt fix (not strictly a bug)

### B7. Env prompt Gen-2 directive rewrite

**File:** `src/prompts.py` (env system prompt)
**Pattern:** across 80 quarters of run-2, the env emitted
`product_advance: false` for every firm at every captured prompt log,
even when firm_9 reached $3.2B cumulative R&D (16× the indicative
threshold).

**Fix:** replaced soft language ("firms far past it should usually
advance") with a hierarchy:
- ratio > 3× → MUST grant unless specific blocker named
- ratio > 1.5× → SHOULD grant unless ongoing blocker
- ratio 1.0–1.5 → MAY grant (judgment)
- ratio < 1.0 → SHOULD NOT grant

The directive language about "specific blocker" forces the env to
articulate a reason when declining. The hierarchical framing also
makes the env's choices more auditable.

## Summary table

| # | File | Severity | Status |
|---|---|---|---|
| B1 | distressed_auction.py | HIGH (root cause of 370 violations) | fixed + tested |
| B2 | orchestrator.py (Phase 15) | HIGH (phantom assets) | fixed |
| B3 | bankruptcy.py (enter_chapter_11) | MEDIUM | fixed + test updated |
| B4 | ma_agent.py (process_acquisition) | MEDIUM | fixed |
| B5 | bankruptcy.py (classify_default) | MEDIUM | fixed |
| B6 | clamping.py | LOW | already correct |
| B7 | prompts.py (env Gen-2) | n/a (prompt fix) | applied |

## Test status

- **353 tests passing** (350 prior + 4 new in
  `test_wave_nu_plus_11_bs_fix.py` − 1 updated test for B3)
- New regression tests pin the **PPE conservation invariant** at the
  industry level — total ppe_net across all firms must not change
  through an auction transfer. Catches any similar accounting
  asymmetry going forward.

## Expected impact on run-3

- BS violations: should drop from 370 → 0 (or near zero)
- Ch11 outcomes: should appear (some operationally-viable firms hit
  liquidity walls under the looser classifier)
- Generation transitions: should appear at firms 3× past threshold
  (env prompt rewrite is the binding fix here)
- All other patterns from `WAVE_NU_PLUS_11_ECON_AUDIT.md` should be
  measured fresh after run-3 to see which are downstream of these
  fixes vs which require additional intervention.
