# Economic Review — Part 3 (2026-05-17)

> Continues ECON_REVIEW + ECON_REVIEW_PART2. Run-7 is in startup;
> reviewing additional un-scrutinized areas in run-6 data + code.

## Findings ranked by severity

### HIGH — features enabled but never exercised

These are bugs because the system's design promised certain dynamics
that never actually materialised, but they look fine on the surface
because nothing crashes.

**F1: No firm ever manipulated earnings.** `earnings_management_enabled=true`
but `firms[*].cumulative_manipulation == 0` for every firm at Q80.
The firm decision LLM never chose to use the manipulation lever.
Consequence: the entire SEC enforcement pipeline (20 investigations
open, 0 enforcement actions, 0 restatements) is moot because there's
nothing for it to act on. The auditor adverse opinions (6 on firm_0)
were triggered by negative equity (the Ch11 treasury bug, now fixed),
not by detected manipulation.

**F2: No legal reserves ever accrued.** `legal_reserves_enabled=true`
but `legal_reserve_balance == 0` for every firm at Q80. The firm
decision LLM never elected to set `legal_reserve_change > 0`. So the
legal-reserve dynamics (accrual, settlement, P&L impact) never test.

**F3: Bad debt expense accrues but write-offs never realize.** 303
firm-quarter rows show $247M of accrued `bad_debt_expense`, but
`write_offs_this_quarter == 0` across the entire run. The env is
supposed to decide write-offs each quarter (env prompt has the
instructions); env-1 (deepseek-v3.2) never produces them. Net effect:
allowance for doubtful accounts grows in proportion to AR (which is
realistic at 1-5% of AR), but no losses ever realize. Cash flow
slightly biased — the "uncollectible" portion of AR is never written
down to actual cash recovery.

**F4: CEO stock never sold.** All four active firms have
`ceo_shares_sold_cumulative == 0` despite vested holdings of
150K–1.1M shares per firm. The firm decision LLM never elects
`ceo_sell_shares > 0`. Real CEOs DO sell some stock periodically
(10b5-1 plans, tax-burden coverage). This pattern is plausibly
caused by the firm prompt not surfacing the CEO's tax/diversification
considerations as a real motive.

**F5: insider trading events log `shares_held_after=0` always.** 77
`InsiderTradingEvent` rows recorded for grants; the `shares_held_after`
field is 0 on every one. The firm-level `ceo_vested_shares_held` IS
correctly tracked (firm_1=150K, firm_4=1.1M, etc.), so this is a
data-integrity issue in the event log only. Researcher analysing the
insider_transactions.csv would see misleading zeros.

### MEDIUM — partial functioning

**F6: Strategic plans empty for active firms.** Out of 20 firms at
Q80, the only firm with a `current_plan` having `len(plan.lines) > 0`
is firm_3 (dormant). The 4 ACTIVE firms all have `current_plan`
objects but with `lines = 0`. Either the planning LLM returned
plans with no quarter-line items, or something is clearing
them. Strategic-planning agent runs at Q4 annually + on
emergency-replan. Worth investigating whether the planning LLM
actually produces 20-quarter plans or empty shells.

**F7: SEC investigations open but never escalate.** 20 SEC
investigations are open at end of run with statuses
`watching`/`investigating`/`private_contact`/`resolved`, but the
`sec_enforcement_log` is empty (no fines, no public actions).
Without manipulation to act on (see F1), this is structurally
inevitable, but the half-implemented escalation pipeline could be
collapsed.

**F8: ~5% of firm decisions missing.** 303 `set_quarterly_decisions`
actions vs ~320 expected (4 active firms × 80 quarters). 17 decisions
missing — likely the periods around defaults, CEO searches, or LLM
failures. With backup chain landing in run-7, the LLM-failure component
should go to 0.

### LOW — within plausible variance

**F9: Pension liabilities large but plausible.** firm_1 at $2.67B
pension and $1.74B deferred-tax-liability — large but consistent
with a firm generating $25B/Q NI over many years. Not a bug.

**F10: CEO turnover 5-6 incarnations per firm.** Already
investigated; ~13-40 quarters per CEO. Within plausibility.

**F11: 27 activist campaigns with diverse responses.** "accept",
"partial", "negotiate" — system works. Not a bug.

**F12: Demand calibrator outputs sane.** Last calibration: 270K
units, with qualitative reasoning citing TAM, WTP, prior quarter
realised, awareness growth. Not a bug.

### FIXED — earlier waves

- AI Horde models (equity panel never ran): Wave ν+14e
- Ch11 treasury_stock not zeroed (firm_0 -$9.95B equity): Wave ν+14b
- Backends for spawned firms (1100+ false "pitch LLM failed"): Wave ν+14b
- BackupBackend chain (silent skip on LLM failure): Wave ν+14e
- M&A bidder defensive crouch: Wave ν+14f
- Negative analyst target prices: Wave ν+14f
- Empty firm_id analyst forecasts: Wave ν+14f
- Debriefs for dormant firms: Wave ν+14c

## Cross-cutting pattern observed

Many of these bugs (F1-F4) share a common root cause: **the LLM is
asked to make an optional decision, and reflexively chooses the
"nothing happens" default.** Earnings management, legal reserves,
bad debt write-offs, CEO stock sales — all are levers the LLM
*could* pull but consistently doesn't. The PE bidder pattern was
the same (F1 in the previous review). The M&A bidder was the same
(addressed in Wave ν+14f).

The general fix pattern: explicit per-option articulation requirement
in the prompt + soft "pushback on permanent defensive crouch"
language. We applied this to M&A; could apply analogously to:
- Firm decision prompt: write-offs / manipulation / legal accrual /
  CEO sales
- Env prompt: write-off decision (env-side)

**Not fixing in this commit** — awaiting your prioritisation.

## What run-7 will validate

The Wave ν+14b/c/e/f fixes should produce:
- Equity panel actually runs each quarter (price_equity actions in log)
- Spawned firms get pitches (no false "pitch LLM failed")
- BackupBackend tier-fallback diagnostic lines if any model fails
- M&A bidder evaluates each target individually (more bids attempted)
- analyst forecasts clean (no negative prices, no empty firm_ids)

If those land, the next iteration's review can focus on F1-F8.

## Commits this session

- `5a936c0` — Part 1 (isolated equity panel never-ran)
- `93dd401` — Part 2 + Wave ν+14e (AI Horde removal + BackupBackend)
- `1bfb04c` — Wave ν+14f (M&A bidder, analyst parser hygiene)
- (this commit) — Part 3 (additional patterns found while run-7 starts)
