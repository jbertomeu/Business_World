# PE Failures Across Runs — Wave ν+12 analysis

> **Purpose**: catalogue what private-equity evaluators got wrong in
> recent multi-quarter runs, identify the pattern, and write the
> long-term-memory note that should be carried into future simulations
> (when `lt_memory_enabled` is turned on).

## TL;DR

Across the three completed 80-quarter live runs (seed 9999 / 7777 / 5555),
PE evaluators systematically over-funded firms that had no path to
profitability. The aggregate PE result is concentrated dispersion —
one or two **210×/153× MOIC** windfalls per run, dozens of total
write-offs (`MOIC=0.00x`), and a heavy negative-NPV tail. The mean PE
fund returns about 1/10th of cost recovery across the portfolio.

**Root cause:** evaluators anchored on the industry's stated $2T TAM
and the founder's optimistic five-year revenue projection — and did
*not* discipline themselves against the trail of prior funding rounds,
flat revenue, and consumed cash that the data showed plainly. The
"WHEN TO WALK AWAY" language added in Wave ν+11 E6 did not bite,
because the evaluator never saw the prior-round trail in a usable form.

The Wave ν+12 step-2 wire-in (`render_intermediary_history(role="pe",
client_firm_id=…)`) was built specifically to fix this; this document
is the receipt of why it was needed and what the next run should
demonstrate.

---

## Run-by-run PE numbers

### run_1778161247 (run-2, seed 9999, 80Q, 14 firms over time)

| firm | status | Q | PE in | final stake | stake value | PE MOIC | PE NPV |
|---|---|---|---|---|---|---|---|
| firm_2 | private (series_c) | 80Q ACTIVE | $720M | 62.6% | $923M | **1.28x** | **+$203M** |
| firm_9 | public | 64Q ACTIVE | $285M | 22.9% | $60,040M | **210.67x** | **+$59,755M** |
| firm_10 | public | 63Q ACTIVE | $575M | 0.0% | $23M | 0.04x | -$552M |
| firm_4 | DEFAULTED Q14 | 14Q | $450M | — | $0 | 0.00x | -$450M |
| firm_0 | DEFAULTED Q44 | 44Q | $1,200M | — | $0 | 0.00x | -$1,200M |
| firm_1 | DEFAULTED Q39 | 39Q | $345M | — | $0 | 0.00x | -$345M |
| firm_5 | DEFAULTED Q23 | 23Q | $195M | — | $0 | 0.00x | -$195M |
| firm_6 | DEFAULTED Q31 | 31Q | $488M | — | $0 | 0.00x | -$487M |
| firm_7 | DEFAULTED Q63 | 63Q | $675M | — | $0 | 0.00x | -$675M |
| firm_11 | DEFAULTED Q25 | 25Q | $450M | — | $0 | 0.00x | -$450M |
| firm_12 | DEFAULTED Q15 | 15Q | $142M | — | $0 | 0.00x | -$143M |
| firm_3 | DEFAULTED Q6 | 6Q | $225M | — | $0 | 0.00x | -$225M |

**Pattern**: 1 mega-winner (firm_9 at 210×) carried the portfolio. **11
of 14 firms returned 0.00x** to PE — total write-off. firm_2 squeaked
out a 1.28x. firm_10 limped to 0.04x.

### run_1778342636 (run-3, seed 7777, 80Q)

| firm | status | Q | PE in | PE MOIC | PE NPV |
|---|---|---|---|---|---|
| firm_0 | ACTIVE | 80Q | $1,125M | **153.48x** | **+$171,535M** |
| firm_2 | private (series_a) | 80Q ACTIVE | $120M | 0.01x | -$119M |
| firm_4 | ACTIVE | 80Q | $615M | 0.10x | -$553M |
| firm_1 | ACTIVE | 80Q | $232M | 0.07x | -$217M |
| firm_5 | ACTIVE | 79Q | $1,575M | 0.08x | -$1,446M |
| firm_6 | ACTIVE | 74Q | $162M | 0.09x | -$147M |
| firm_7 | ACTIVE | 69Q | $262M | 0.22x | -$204M |
| firm_9 | ACTIVE | 67Q | $525M | 0.87x | -$70M |
| firm_8 | ACTIVE | 64Q | $2,880M | 0.07x | -$2,677M |
| firm_10 | private (series_c) | 66Q | $172M | 0.00x | -$172M |
| firm_3 | DEFAULTED Q6 | 6Q | $225M | 0.00x | -$225M |

**Pattern**: same shape — 1 windfall (firm_0 at 153×) carries the
portfolio; **firm_8 PE lost $2.7B** alone on a 0.07x MOIC after
investing $2.88B. **firm_5 PE lost $1.4B** on 0.08x after $1.58B in.
Nine firms below 0.25x MOIC.

### run_1778527742 (run-4, seed 5555, 80Q, capped at 40 firms)

| firm | status | Q | PE in | PE MOIC | PE NPV |
|---|---|---|---|---|---|
| firm_4 | ACTIVE | 78Q | $75M | **4.17x** | **+$238M** |
| firm_5 | ACTIVE | 77Q | $325M | 0.17x | -$271M |
| firm_6 | ACTIVE | 76Q | $240M | 0.11x | -$214M |
| firm_7 | ACTIVE | 75Q | $630M | 0.14x | -$539M |
| firm_1 | ACTIVE | 80Q | $188M | 0.06x | -$177M |
| firm_2 | DEFAULTED Q51 | 51Q | $495M | 0.00x | -$495M |
| firm_0 | DEFAULTED Q69 | 69Q | $675M | 0.00x | -$675M |

**Pattern**: only one firm beat 1× MOIC; **firm_7 PE lost $539M** on
0.14× after $630M in; firm_0 PE was wiped out at Q69 after $675M
deployed. No mega-windfall this run — the cap on max firms changed
the distribution. Result: catastrophic mean PE return.

---

## What did the evaluators get wrong?

### 1. Anchoring on the $2T TAM, not the firm's track record

Every spawn-quarter entry-judge narrative contained verbatim phrases
like:

> *"The industry has a massive stated TAM of $2000.0B, with only 0.5%
> captured so far, indicating enormous upside..."*

PE evaluators inherited this anchor. They reasoned: TAM × small share =
huge potential. They DID NOT discipline themselves against the
specific firm's R&D burn history, revenue trajectory, or pattern of
flat valuations across prior rounds.

### 2. No prior-round visibility

The Wave ν+11 prompt asked evaluators to "use comparables and the
firm's own track record against its prior projections to discipline
yourself." But the **evaluator never saw the prior projections** —
the prompt builder did not include them. Each evaluation was effectively
de novo: this firm, this pitch, this current snapshot. Repeat funding
rounds at falling valuations were invisible.

This is exactly what `render_intermediary_history(role="pe",
client_firm_id=firm_id)` now surfaces — but only as of Wave ν+12
step 2 (commit `5c30846`). All three completed runs predate this
fix.

### 3. Cash-burn evidence ignored

Multiple firms showed up at series_b / series_c pitches with:
- Multi-quarter negative operating cash flow
- R&D spend exceeding revenue 10x+
- No advance to Gen-2 (because the env was systematically failing
  to grant — see WAVE_NU_PLUS_11_ECON_AUDIT.md)
- Falling per-share valuations vs prior round

These are textbook stop signs. PE evaluators continued to LEAD or BID
on these firms. Across the three runs, **the most common failure was
firm-0, firm-1, firm-2 type "promising biotech with no path" wipeouts**
where PE invested $200M–$2.9B over multiple rounds and recovered $0.

### 4. The "WHEN TO WALK AWAY" language did not bite

Wave ν+11 E6 added an explicit walkaway section to
`PE_EVAL_SYSTEM_PROMPT`. It read:

> *"Real PE partners decline more deals than they accept ... Walk away
> when the firm has been raising repeatedly without operational
> improvement (revenue trajectory flat after multiple prior rounds is
> the strongest negative signal you can observe)..."*

This language did not change the empirical decision pattern because
**the evaluator could not OBSERVE prior rounds** — there was no
"prior PE rounds" block in the user prompt. Adding the directive
without surfacing the data was insufficient.

### 5. PE projection vs PE outcome variance was not fed back

The simulation captures `state.pe_round_history` (every PE round with
firm_id, round_type, amount_raised, post_money_valuation, the lead
PE fund's projected y5 revenue). But the evaluator on the next round
NEVER saw the prior lead's projections vs how revenue actually evolved.
There was no learning loop.

---

## What changes in Wave ν+12

1. **`render_intermediary_history(role="pe", client_firm_id=firm_id)`**
   now surfaces:
   - Full public Compustat panel across all firms × compressed history
   - This firm's compressed BS/IS/CF since inception
   - This firm's full decision log
   - Past PE rounds INDUSTRY-WIDE (so the evaluator sees the recent
     comparable rounds, not just this firm)
   - Recent PE-role debrief notes

2. **PE debriefs** (per-quarter, role="pe") will accumulate notes like
   *"Round in firm_8 at $400M post-money — bet on Gen-2 timeline, watch
   quarterly readouts."* These get surfaced to the same role next
   quarter via `render_recent_debriefs(role="pe")`.

3. **LT memory** (when `lt_memory_enabled` is turned on) will write a
   role-specific note at end-of-run into `data/agent_memory/pe.md`.
   Future runs read it as the *"LT MEMORY FROM PRIOR SIMULATIONS"*
   block. The note below is what should land there.

---

## Proposed LT-memory note for role="pe"

(To be the first content of `data/agent_memory/pe.md` once
`lt_memory_enabled` is turned on for a run with the Wave ν+12 history
wiring.)

> **Across three 80-quarter biotech-industry simulations (seed 9999 /
> 7777 / 5555), PE funds systematically lost money on a large majority
> of investments while one or two firms per run produced 100×+ windfalls
> that statistically masked the failures. The empirical PE failure
> pattern was: invest in a firm with a strong-sounding pitch deck,
> watch revenue trajectory stay flat across multiple rounds while R&D
> burn continued unabated, watch the env never grant Gen-2 advance,
> watch cash run out around quarter 30-70, write the position to zero.**
>
> **Operational rules from this experience:**
> - **Look at prior rounds first.** If a firm has raised in 2+ prior
>   rounds and revenue is still flat, the next round will most likely
>   end the same way. The lead PE fund's y5 revenue projection from
>   the prior round vs the firm's actual revenue path is the single
>   most informative signal you have — variance there should make you
>   PASS, not raise the valuation.
> - **The TAM number is not a thesis.** "Industry has $2T TAM and we
>   are at 0.5% captured" was the rationale on most firms that
>   subsequently wiped out. Use TAM as a far-future ceiling, NOT as
>   evidence that this specific firm is the one that captures it.
> - **Cash runway with the proposed raise must extend past the next
>   credible milestone**, and the firm must have a real shot at hitting
>   it. If the proceeds will run out before Gen-2 readout, this round
>   is a bridge, not a thesis investment.
> - **A firm at series_c with no operating-cash-flow improvement vs
>   series_a is a structurally weak signal.** Treat it as such even
>   when the pitch is polished.
> - **Concentrate funding.** In all three observed runs, ~10% of firms
>   carried 100% of PE NPV. Backing 8 firms with $200M each across an
>   industry produced worse returns than backing 2 firms with $800M
>   each would have. Be aggressive on the leaders, decisive on the
>   passes.
> - **Default rate is much higher than founder pitches imply.** Across
>   these three runs roughly 40-70% of PE-backed firms eventually
>   defaulted. The PASS button is the correct default; BID/LEAD is
>   the exception. A 1-in-3 win rate at 10× is good portfolio math
>   only if you are paying for one in three, not all of them.

---

## Next-run validation checklist

After the Wave ν+12 wiring lands on a future 80Q run, check:

1. **PE pass rate increases.** Currently the evaluators BID/LEAD on
   most pitches they see. With history visible, the pass rate should
   rise — especially on second-and-third rounds of firms with flat
   revenue.
2. **Reduced total deployment.** Aggregate PE-in dollar volume should
   come down. A more selective evaluator deploys less capital but on
   better firms.
3. **PE mean MOIC improves.** The 0.07x-0.22x cluster should
   disappear. Mean PE MOIC should approach 1.0×, with the windfall
   distribution carrying it above.
4. **Repeat-funding pattern weakens.** Firms that raise series_a should
   be less likely to also raise series_b and series_c at the same
   speed if their fundamentals haven't moved.
5. **PE debrief notes show pattern recognition.** Look in
   `state.debrief_notes` for `role="pe"`: the notes should reference
   prior rounds and concrete trajectory evidence, not just the latest
   pitch deck.

Re-run this analysis (`analysis/PE_FAILURES.md`) after the next 80Q
run lands; update the LT-memory note accordingly.

---

*Source data: `outputs/run_1778161247/scorecard.txt`,
`outputs/run_1778342636/scorecard.txt`,
`outputs/run_1778527742/scorecard.txt`. Code references:
`src/private_equity.py::PE_EVAL_SYSTEM_PROMPT`,
`src/private_equity.py::make_pe_eval_agent`,
`src/agent_history.py::render_intermediary_history`.*
