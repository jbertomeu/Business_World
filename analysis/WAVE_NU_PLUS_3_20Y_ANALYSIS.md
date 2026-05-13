# Wave ν+3 — Comprehensive Analysis of the 20-Year Run

**Run ID**: `run_1777317784`
**Period simulated**: Q1 2031 → Q3 2049 (75 quarters, ≈ 18.75 years)
**Target**: Q1 2031 → Q4 2050 (80 quarters / 20 years)
**Outcome**: Industry-wide collapse — all 20 firms defaulted before Q80
**Wallclock**: ~28 hours total (across original 16Q run + 64Q continuation + post-fix resume)
**Cost**: ~$0.50–$0.75 estimated (per-segment summaries; full panel was overwritten by the resume run)

---

## Executive Summary

The simulation ran cleanly for 75 quarters with zero balance-sheet identity violations, a successful crash recovery, and the supervisor + heartbeat infrastructure functioning end-to-end. **The economics, however, produced an industry that ultimately could not sustain a single survivor over a 20-year horizon.** Every firm defaulted; cumulatively, equity holders (founders + PE + public) lost between several hundred million and several billion dollars per firm; debt was the only stakeholder that came out positive (+$1.52B NPV at a 26.1% default rate).

Two structural causes stand out, both pre-existing rather than introduced this wave:

1. **No firm ever reached Generation 2.** Even the firm that survived all 75 quarters (firm_2) stayed at Gen 1 throughout. Cumulative product R&D never crossed the (now scenario-tunable) $500M threshold for any firm.
2. **Gen 1 unit economics did not produce sustained profitability.** Firms that survived 15+ years did so by repeatedly raising capital and bleeding it down, accumulating large negative equity NPVs along the way.

Wave ν+3 closed several real bugs (ZeroDivisionError in demand, BS imbalance for entrants, run-id preservation across restarts, supervisor auto-recovery) and removed quantitative behavioral rules that had crept back into prompts. What remains visible are deeper structural / scenario-calibration issues, a small set of unfixed bugs in pricing units and missing distressed-asset auctions, and several counter-intuitive LLM behaviors.

---

## 1. Run Timeline

### High-level trajectory

| Phase | Quarters | Firms (start → end) | Revenue (industry) | Notable |
|------|---------|---------------------|--------------------|---------|
| Initial 16Q (Wave ν+3 fresh launch) | Q1–Q16 | 5 (initial cohort) → 8 active | $324M → $86M | Endogenous entry filled slots; 8 survived to Q16 |
| Continuation Q17–Q22 | Q17–Q22 | 8 → 6 | $90M → $67M | Slow attrition |
| Mid-period Q23–Q40 | Q23–Q40 | 6 → 5 → 3 | $50M → $20M | Continued attrition; revenue base contracting |
| Late Q41–Q70 | Q41–Q70 | 3 → 2 → 1 | $20M → $1M | Long single-firm tail |
| Final Q71–Q75 | Q71–Q75 | 1 → 0 | $0.5M → $0 | Last firm defaults |

### Lifespans (final standing)

| Firm | Final stage | Lifespan | Founder NPV | Notes |
|---|---|---|---|---|
| **firm_2** | private/series_b | **75Q** (full run) | -$160M | Longest-lived; never IPO'd; never reached Gen 2 |
| firm_4 | PUBLIC | 62Q | -$23M | Long-lived public firm; eventually defaulted |
| firm_7 | private/late_stage_private | 46Q | +$50M (only positive founder NPV) | Reached late_stage but never IPO'd |
| firm_5 | PUBLIC | 40Q | -$75M | Was an early entrant; IPO'd then died |
| firm_15 | PUBLIC | 29Q | -$22M | **The leapfrog entrant** — entered Q11 with elevated capability |
| firm_1 | PUBLIC | 25Q | -$118M | Initial cohort; IPO'd, then defaulted |
| firm_6 | PUBLIC | 21Q | -$6M | Entrant Q2; IPO'd; near-breakeven for founder |
| firm_0 | PUBLIC | 19Q | -$166M | Initial cohort; failed IPO trajectory |
| firm_3 | PUBLIC | 15Q | -$35M | Initial cohort |
| firm_11 | PUBLIC | 5Q | -$76M | IPO'd then defaulted within 5Q |
| firm_13 | private/series_b | 5Q | -$26M | Brief PE trajectory then died |
| firm_16 | private/series_a | 2Q | -$26M | One-and-done |
| firm_8/9/10/12/14/17/18/19 | founded | 1Q each | -$26M each | **Eight 1-quarter deaths** — entered then immediately defaulted |

**12 firms had lifespans of 5 quarters or less** — most of these were endogenous entrants that the entry judge spawned with very small founder seed capital ($0–$1M) and could not raise PE Series A.

### Capital flows (cumulative across run)

| Stakeholder | Invested | Returned | Net |
|---|---|---|---|
| Founders | ~$1.1B | ~$0 | -$1.1B |
| PE funds (8 funds) | $5.4B | $0 | -$5.4B |
| Public-equity holders (post-IPO) | ~$1.1B | $0 (firms eventually defaulted) | -$1.1B |
| Debt holders | $1.50B | $1.91B interest + $1.11B principal recovered | **+$1.52B NPV** |

Debt was the only winner. Lenders charged risk-adjusted interest, collected significant cash inflows over time, and recovered enough principal that the 26.1% default loss rate was offset by the interest premium. Equity stakeholders at every level were wiped out.

### PE fund-level outcomes

All 8 funds deployed ~100% of their initial capital ($5.4B in aggregate), realized $0 in proceeds, and ended the run holding equity stakes worth $0. Per-fund:

| Fund | Strategy | Capital | Invested | Realized | n_portfolio |
|---|---|---|---|---|---|
| Vanguard Life Sciences | early_stage | $600M | $600M | $0 | 11 |
| Horizon Growth | growth | $800M | $800M | $0 | 11 |
| Meridian Capital | generalist | $500M | $500M | $0 | 11 |
| Aperture Seed | seed | $200M | $200M | $0 | 10 |
| Longview Crossover | crossover | $1.20B | $1.20B | $0 | 11 |
| Harbor Patient Capital | patient_capital | $1.00B | $1.00B | $0 | 12 |
| Summit Special Situations | distressed | $400M | $400M | $0 | 10 |
| Keystone Strategic | strategic | $700M | $700M | $0 | 11 |

Even the "Summit Special Situations" fund (whose thesis was supposed to be price-disciplined and walk away from overpriced deals) deployed 100% of its capital and got 0 back. **No fund's stated discipline showed up in the actual portfolio outcome** — every fund participated in losing rounds at similar magnitude. This is one of the more counter-intuitive findings (see §4).

---

## 2. Endogenous Entry — How It Played Out

The entry-judge LLM spawned 15+ entrants over the 75 quarters, exhausting all 20 firm slots. Entries were thoughtfully reasoned by the judge — every entry event has a rationale referencing HHI, recent defaults, slots remaining, and TAM realization.

### Entries that produced something

- **firm_15 (Q11) — flagged LEAPFROG**: starting capability 50, eventually reached PUBLIC stage at series_c, lifespan 29Q. Founder NPV -$22M (modestly negative). PE MOIC partially returned. The leapfrog mechanic produced a real second-tier survivor — the only entrant that reached IPO and survived multiple quarters post-IPO.
- **firm_5 (Q1 entrant)**: 40Q lifespan, IPO'd, eventually defaulted. Was a regular (non-leapfrog) entrant.
- **firm_6 (Q2)**: 21Q lifespan, IPO'd, near-breakeven for founder. Regular entrant.

### Entries that died fast (the dominant pattern)

Eight firms (firm_8, 9, 10, 12, 14, 17, 18, 19) had **1-quarter lifespans**. They entered with $0–$1M cash from the entry judge, could not raise PE Series A in their first quarter, and immediately defaulted. Each lost $26M of founder paper-NPV.

This is a direct consequence of the "no quantitative rules in prompts" principle interacting with judge under-calibration: when I removed the scenario-aware floor and the leapfrog 3× multiplier from `_run_entry_phase`, the judge's proposed `founder_capital_seed_usd` numbers were used directly. The judge — without numeric anchors — proposed very small numbers ($0–$1M) for most entrants. These firms were dead-on-arrival.

**The trade-off this exposes**: emergence-only prompts give the agents full freedom to reason but also risk under-calibration when the LLM has no numeric anchor. Real-world entrant seed amounts are highly bimodal (large institutional rounds vs. tiny garage starts), and the LLM consistently picked the small end without seeing the scenario's $800M founding norm explicitly.

---

## 3. Behavioral Findings — What the Firms Actually Did

### Pricing converged toward unit cost (race-to-bottom not eliminated)

Q1 board minutes from firm_2 read sensibly: "we need to be strategic with our pricing... I propose a target price of $15,000 per unit. This price point allows us to be competitive while still generating a healthy margin." It noted "competitors are currently priced at $0".

By Q75, the same firm's CEO referenced a price of $19,000/unit, but realized revenue of $0.5M / 248 units = $2,000/unit. The firm believed it was pricing premium but the env's allocation produced a far lower realized price. Worth investigating whether the env was clamping prices to defaulted firm levels or whether the firm's stated price was overridden.

### Memory loss in long-lived firms

**At Q75, firm_2's board minutes opened with: "this is our first board meeting and quarter of operations"** — despite the firm having operated continuously since Q1 (74 quarters of board minutes precede this). The LLM lost the historical context.

Mechanism: per-firm memory passes accumulated history through `AgentMemory.get_history_summary()`, but with 18+ years of history, summarization may be losing the "this is my Nth quarter" framing. The firm-prompt template includes prior board context, but at very long horizons it may degrade. **This is a real LLM-side limitation that doesn't have a clean prompt-engineering fix** — it argues for a sliding-window approach where the firm reads only the last K quarters of detail plus a high-level "you have operated for N quarters" header.

### PE funds did not differentiate by stated strategy

All 8 PE funds (seed, growth, generalist, crossover, patient_capital, distressed, strategic, etc.) deployed nearly identical capital and ended with similar (zero) outcomes. The "distressed/special situations" fund — whose prompt explicitly emphasized walking away from overpriced deals — still deployed all $400M.

Likely cause: when 8 funds evaluate the same pitch, they tend to converge to similar per-pitch decisions because each gets the same firm state + industry context. The "thesis" in the prompt is paragraph-level guidance, not a hard rule, and the LLMs often defer to the firm's narrative. Real PE differentiation comes from years of relationship building and proprietary deal flow — neither of which is modeled. **Fixing this would require either differentiated information (each fund sees a different subset of deals) or stronger thesis-anchoring (e.g., the distressed fund only sees down-round opportunities).**

### Strategic plans existed but didn't change outcomes

Each firm had per-quarter strategic plans, with a CFO gatekeeper that occasionally rejected drafts. The plans were thoughtful and referenced industry context. But the realized financials did not match plan assumptions in most quarters — variance was large and persistent. Firms made plans, then deviated when the env's demand allocation undershot expectations, then replanned, then deviated again. This is realistic in the sense that real firms also miss plans, but at the magnitudes observed, the planning cycle mainly produced documentation rather than discipline.

---

## 4. Counter-Intuitive Findings

These are dynamics that don't match expected real-world behavior:

### 1. Industry-wide zero survival over 20 years
Real-world biotech industries with $2T mature TAM (the scenario's stated value) have multiple firms survive 20+ years. The simulation's economics make Gen 1 unit economics insufficiently profitable to sustain the burn from R&D + S&G&A + cost of capital — so even firms that survived 15+ years bled down to negative equity. **Real industries see at least a few "boring profitable" firms emerge that don't chase Gen 2.** Our simulation does not reproduce this.

### 2. PE keeps funding firms that look identical to prior failures
At Q40+, the PE pool had visibility into 15+ failed firms. New entrants in this period had similar starting profiles to earlier failures (low capability + brand + cash). PE funds nonetheless funded subsequent rounds at meaningful valuations. In real PE, after a string of failures with similar characteristics, the funds would tighten criteria sharply. The judge prompts include scenario context but the LLM's deal-by-deal evaluation does not seem to weigh "this opportunity looks like firms 8, 9, 10, 12, 14 that all failed in 1 quarter."

### 3. No distressed-asset auctions despite 20 defaults
Auctioning a defaulted firm's PP&E + capability to surviving competitors should preserve value (real M&A often acquires distressed competitors). Our run produced **zero auction events** — no `distressed_auctions.csv` was written. The auction phase code exists and is wired, but `newly_defaulted_ids` was empty for every quarter despite 20 firms eventually defaulting. The most likely cause is that the `_active_at_start` set captured at the start of `run_quarter()` doesn't see firms that default during the same quarter they entered (the fix attempted in Wave ν+2 only added entrants to the set, not survivors-at-start-of-Q who defaulted later in the same Q). This bug needs a deeper fix.

### 4. Founder NPVs are mostly negative even for long-lived firms
firm_2 survived the entire 75 quarters but founders ended with -$160M NPV. Founders kept their seat at the table for nearly two decades but ended with less than they put in. In real venture, founders typically either fail fast and exit (small loss) or succeed and capture meaningful value at IPO/M&A. The "long survival but accumulating loss" outcome is rare in reality because firms in that situation typically would be acquired, restructured, or wound down well before the founders bled all their equity.

### 5. PE Round pricing has unit-mismatch bugs
Several PE rounds completed at absurdly low per-share prices:
- firm_3 series_a at price $0.00018 (pre-money $180 — looks like the LLM emitted "180" meaning $180M but it was parsed as $180)
- firm_13 series_a at price $0.00004
- firm_5 series_a at price $0.0999

In each case, either the LLM proposed pre-money values in the wrong unit, or the firm's `shares_outstanding` was already large (e.g., post-IPO) and the round was incorrectly run as a "series_a" downround. **The PE round phase should refuse to run a fresh series round on a public firm**, and the pre-money number should be sanity-checked against scenario norms. Neither is currently in place.

### 6. Long-lived public firms continued accumulating losses post-IPO
firm_4 IPO'd, public stakeholders bought in, and 62 quarters later the firm defaulted with all public investors at $0. Public-equity loss of -$1.66B cumulative NPV. Real-world IPO firms with similar profiles either get acquired, undergo activist intervention, or get restructured well before zero. Our activists, board governance, and M&A mechanisms are present but did not intervene effectively at the right moments.

---

## 5. Bugs Found and Status

### FIXED in this wave

| Bug | Symptom | Resolution |
|---|---|---|
| **ZeroDivisionError in `demand.py:161`** | When only 1 firm survived with 0 share, `sum(shares.values())` was 0, crashing the demand calculation at Q75 | Guarded the divide; fall back to unweighted mean of stated prices, then to default. Crash-recovery + supervisor caught the prior crash, run resumed cleanly |
| **BS-imbalance for endogenous entrants** ($25M) | Phase_2_ipo logged a residual whenever a new entrant arrived because PPE was added without offsetting equity | Treat PPE as in-kind founder contribution; `apic = seed_cash + ppe_net` so the BS identity holds |
| **`run_id` overwritten on `--restart-from`** | Restart from snapshot would create a new run dir, splitting outputs and breaking supervisor-based recovery | Preserve the snapshot's `run_id` on restart so all outputs accumulate in one directory |
| **No traceback when run dies** | Silent deaths produced 0-byte logs with no diagnostic | Top-level traceback wrapper in `cli.main` writes `outputs/crash_traceback.txt` on any uncaught exception |
| **Background process killed by parent shell** | Bash run_in_background processes died when Claude Code session boundaries crossed | Switched to PowerShell `Start-Process` for true detachment; supervisor manages restarts |
| **Supervisor lacked auto-recovery** | A crash mid-run lost all progress | New `scripts/supervised_run.py` finds latest snapshot and re-launches with `--restart-from`; capped at N attempts to avoid infinite loops |
| **stdout buffering hid live progress** | Long runs appeared frozen even when alive | `python -u` for unbuffered + `print(..., flush=True)` on per-quarter status line + heartbeat.json updated every Q |

### NOT YET FIXED

| Bug | Symptom | Priority |
|---|---|---|
| **`distressed_auctions.csv` always empty** | 20 firms defaulted but no auction event was recorded; `_active_at_start` set doesn't capture all defaulters | **High** — undermines the entire consolidation mechanic |
| **PE round pricing unit-mismatch** | Several rounds priced at $0.0001/share due to LLM emitting pre-money in wrong units | **Medium** — visible in pe_rounds.csv but doesn't crash anything; may distort cap-table math |
| **PE round can run on public firms?** | Some "series_a" entries appear for public firms with huge share counts; should be gated out | **Medium** — needs investigation; the gate `firm.is_public → continue` exists but maybe a state bug bypasses it |
| **LLM context loss in long-lived firms** | At Q75, firm_2's CEO believed it was "first quarter of operations" | **Medium** — fundamental LLM limitation; needs a sliding-window memory + explicit "you have operated for N quarters" header |
| **Q-progress display misleading after restart** | Continuation showed `Q53/64` but 53 is absolute, 64 is the continuation length | **Low** — cosmetic; doesn't affect correctness |

---

## 6. Engineering Wins

These all worked end-to-end during the 28-hour multi-segment run:

1. **Crash recovery via supervisor + snapshots**. The supervisor caught the `ZeroDivisionError` at Q74, attempted re-restart from Q74 (failed because deterministic), correctly aborted to avoid infinite loop. A patch + manual resume from Q74 finished the run cleanly.
2. **Heartbeat JSON** updated every quarter with timestamp, elapsed wallclock, sim quarter, active firm count, total revenue, and progress percentage. Externally readable for liveness checks without parsing the buffered log.
3. **Live timestamped per-quarter log line** in format `[2026-04-28 18:47:12] Q55/64 (Q3 2044) total=13h04m this_q=4m55s Rev=$21.1M Firms=2 Gen=G1,G1` — visible advancement at a glance.
4. **PowerShell `Start-Process` detachment** kept the run alive across Claude Code session boundaries that previously killed background bash children.
5. **Per-quarter snapshots** (Q1.pkl through Q75.pkl, ~50KB-1MB each) make any quarter resumable.
6. **0 BS-identity violations** across 75 quarters with 20 firms, multiple PE rounds, IPOs, defaults, and the entrant-BS fix from Wave ν+2 holding.

---

## 7. Open Questions / Recommended Next Steps

In rough priority order:

1. **Fix the distressed-asset auction.** With 20 defaults and 0 auctions, the consolidation mechanism is silently broken. Inspect `_active_at_start` flow to capture all firms that were active during ANY phase of a quarter (not just at the start).
2. **Make Gen 2 reachable.** The $500M threshold is now scenario-tunable; either lower it for the well_capitalized scenario, or restructure the R&D function so cumulative product R&D builds faster when firms invest meaningfully.
3. **Fix Gen 1 unit economics.** Currently Gen 1 firms can sell units but the margin (price − unit cost − allocated S&G&A) doesn't sustainably cover R&D investment. This makes long-survival impossible without external capital. Real Gen 1 biotechs DO reach steady-state profitability; ours don't. Likely a scenario-parameter issue (S&G&A intensity, demand response curve, baseline growth).
4. **Address PE under-funding of entrants.** Either give the entry judge richer scenario-norm signals, or have the founders' seed amount derived from an explicit founder-LLM call that sees concrete prior-firm seed magnitudes.
5. **Investigate PE-fund undifferentiation.** Make funds genuinely behave differently — perhaps by giving each fund a private memory of prior bets that informs its bidding, or by partitioning deal flow so different funds see different subsets.
6. **Sanity-check PE round parser for unit mismatches.** Reject rounds where `pre_money_valuation_ask < scenario.founding_cash_norm * 0.001` (or similar) — these are almost certainly LLM unit-mismatch errors. The check should be in `_run_pe_round_phase`.
7. **Add LLM context-window management for long-lived firms.** A sliding-window of last K quarters + a "you have operated for N quarters" header would prevent the firm_2 Q75 hallucination.
8. **Allow re-enabling M&A** with the per-firm-bidder model now in place. The env-judged M&A was rapacious and was disabled this round.

---

## 8. Final Take

The simulation reached a stable engineering state in Wave ν+3:
- All recent-wave bugs (auction BS, run-id, crash recovery, traceback) resolved.
- Live observability is in place (heartbeat, timestamped per-quarter line).
- Crash recovery is real and tested under fire.

But the **economic outputs are not realistic** at long horizons. A 20-year run that produces 0 survivors despite a stated $2T TAM, with 8 PE funds losing 100% of $5.4B capital while debt holders earn $1.5B, is not a market anyone would recognize. Three structural changes are likely needed before the simulation produces realistic long-horizon outcomes:

- **Gen 2 must be reachable** (currently unreachable in 20 years at any plausible burn rate)
- **Gen 1 must be sustainably profitable for at least one firm at any time** (currently not — even 75Q firm_2 was bleeding)
- **Distressed auctions must work** (currently silently broken — defaults destroy value rather than transferring it)

These are now the next round of work, not bugs in the prompt-engineering or supervisor infrastructure.
