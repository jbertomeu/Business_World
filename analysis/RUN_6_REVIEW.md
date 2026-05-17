# Run-6 Review (Wave ν+13, seed 2222)

> 80 quarters, 20-firm cap, all Wave ν+13 changes (strict mandatory-Gen
> tiers + deterministic force-grant, intensive history blocks in
> firm/env/PE/IB/CB prompts, per-quarter debriefs, sleep disabled).

## TL;DR

**Wins:** the force-grant fix worked. For the first time across 6 runs,
firms actually advanced generations — firm_0, firm_1, firm_5 all reached
Gen 4. Industry revenue grew into a plausible scale ($43B/Q for the
Gen-4 monopolist firm_1, vs the run-3 $8T overshoot). BS violations
dropped from 70 → 4. Debt loss rate became realistic (2.2%).

**Big bugs still open:**
1. **Equity panel wildly under-values Gen-4 firms.** firm_1 ends with
   $413B in cash, $43B/Q revenue, $25B/Q NI — and the panel says it's
   worth $502M. P/E of 0.005. The equity market completely fails to
   re-price firms that scale into Gen-4 mature-revenue range.
2. **16 of 20 firms are dormant.** They spawn, PE rejects, they sit
   forever with $0-5M seed cash. Wave ν+12 PE history visibility made
   PE evaluators MORE selective (good in principle) but pushed past
   functional. No new firm in the run successfully closed a PE round.
3. **firm_0 negative equity accumulated to -$9.95B.** BS violation
   pattern: equity destruction without corresponding asset/liability
   adjustment. Persistent bug since Q1 2032. 4 violations in
   bs_violations.jsonl (Q6, Q8, Q19, Q65) all this firm, this phase.

## Findings

### Force-grant fired 7 times across 80 quarters
- Q25, Q26: firm_0, firm_1 (the original targets that prompted the fix)
- Q34, Q42, Q44, others: subsequent firms

The env-1 (deepseek-v3.2) sometimes complied on retry but often did
not. The force-grant is the safety net that made the strict rule
actually bite.

### Generation distribution at Q80

```
firm_0  G4 INACTIVE (defaulted Q68 despite reaching Gen-4)
firm_1  G4 ACTIVE   $413B cash, $43B/Q revenue
firm_2  G1 DORMANT
firm_3  G1 DORMANT
firm_4  G1 ACTIVE   IPO'd but stuck at Gen-1
firm_5  G4 ACTIVE   $2B cash, $891M cum R&D
firm_6-19  G1 DORMANT (14 firms)
```

**3 of 20 firms reached Gen-4.** That's the first time in any run any
firm has left Gen-1. The system finally produces the differentiated
outcomes that real biotech industries show: a small number of
breakthrough leaders + many also-rans.

### firm_0 default at Q68 despite reaching Gen-4

Counterintuitive but emergent: firm_0 reached Gen-4 around Q42 but
ran a too-aggressive capital structure (negative equity since Q1
2032 — see bug #3 above). Even with Gen-4 revenue, accumulated debt
+ accounting-bug-driven equity destruction made the firm unrecoverable.
Capital structure killed a firm with a winning product. That's a real
phenomenon in biotech, even if the immediate cause here is partly a
BS bug rather than purely organic.

### firm_4 PE wiped out (0.06× MOIC, $518M in)

The Wave ν+12 PE history visibility was supposed to prevent this. It
didn't, for firm_4 specifically because:
- firm_4 IPO'd successfully early (got to PUBLIC status)
- PE rounds happened pre-IPO and looked plausible at the time
- firm_4 never accumulated enough R&D to advance (only $57M cum at Q80)
- Stuck at Gen-1 forever with structural under-investment

PE evaluators didn't see this coming because at the time they
invested, firm_4 was producing revenue. The pattern of "PE bets on a
firm that then under-invests in R&D and stays Gen-1 forever" is hard
to predict ex-ante.

### Equity-panel valuation failure

| firm | rev/Q | NI/Q | cash | reported value |
|---|---|---|---|---|
| firm_1 | $43,506M | $24,260M | $413,635M | **$502M** |
| firm_5 | (smaller) | (smaller) | $2,031M | $485M |

firm_1 has revenue 87× its market cap and cash 824× its market cap.
This is the equity panel completely failing on Gen-4 scale. Likely
causes:
- Panel is anchored on industry historical pattern and can't process
  the post-Gen-4 step-change in revenue
- Panel prompt may cap valuation implicitly through phrasing
- Panel uses median across 3 valuators; if 2 are anchored low and
  one is anchored realistically, median = low

**Fix needed**: equity panel needs explicit instruction that Gen-N firms
have N-step-change addressable markets and that mature-Gen revenue can
sustain enterprise values 10-20× ANNUAL revenue, not 0.01× quarterly.

### 16 dormant firms

Entry judge spawned 14 new firms (Q3 through Q17), every one of which
went dormant immediately ("no PE round closed") and stayed dormant
through Q80. The PE rejection rate is 100% for spawned entrants.

Likely cause: the Wave ν+12 PE history visibility shows PE evaluators
the pattern of prior PE failures (firm_4 0.06× MOIC, firm_0 default,
etc.) and the new walk-away language in the PE eval prompt. Result:
zero new bets.

**Fix needed**: PE should still bet on a fraction of new entrants —
real PE doesn't decline 100% of new pitches. Either:
- Soften the walk-away language for new pitches with no operating
  track record (they have nothing to dock points for)
- OR add a "we make N bets per year regardless" floor
- OR the entry judge should not spawn if dormant queue is large

### 4 BS violations on firm_0 phase_15_settlement

All same firm, same phase, residual growing over time:
- Q6: $400M
- Q8: $600M
- Q19: $1.94B
- Q65: $9.14B

`delta_residual=0` on all — the violation is pre-existing when phase_15
runs. The phase is NOTICING the residual, not creating it. The actual
accounting bug is upstream — equity is being destroyed without
corresponding adjustment to assets or liabilities.

Looking at the compustat trajectory, firm_0's CEQ went negative at
Q3 2032 (-$124M) and stayed negative all 80 quarters, ending at
-$9.95B. The asset side is only $443M and liability side is $1.25B,
implying CEQ should be -$807M. The extra $9B of negative equity is
the phantom destruction.

**Fix needed**: trace which phase is dropping equity without
balancing. Likely a stock-comp accrual, treasury buyback at the wrong
time, or M&A goodwill impairment without offset.

## Priorities for Wave ν+14

1. **Equity panel: handle Gen-N scale realistically.** This is the
   single largest contaminator — every downstream metric uses equity
   prices and they're 800× too low for the mature firms.

2. **Restore PE betting on new entrants.** Either soften walk-away
   for unbacked pitches OR require N bets/quarter from each fund.

3. **Trace firm_0 phantom equity destruction.** Probably stock-comp
   or treasury accounting.

4. **Dormant cleanup.** Firms that sit dormant >N quarters should
   either get a smaller "rescue" seed round or be wound down. 16
   permanently-dormant firms clutter the simulation.

5. **firm_4 PE pattern.** Even with the history visibility, PE
   evaluators couldn't detect the "IPO'd then stuck" trajectory.
   Maybe surface PE-investment-vs-Gen-advance variance specifically
   in the PE eval prompt.

## Repository state

`598bdb6` is the Wave ν+13 commit on `main`. Next wave addresses the
priorities above.
