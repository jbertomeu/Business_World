# Wave ν+11 — Economic Soundness Audit (run_1778161247)

Run-2 (seed 9999) ended with several patterns in the data that look
*economically* off. None are software bugs in the strict sense; they are
features the simulation produces that don't match how a real biotech
industry behaves. They will all be candidates for prompt or model
revision.

I am separating these from the **8 software bugs** documented in
`WAVE_NU_PLUS_11_BUG_FIXES.md` (those are Wave-ν+11 code fixes). This
document focuses on *behavior* that emerges from the LLMs' choices
under the current prompt structure.

---

## E1. R&D intensity is unrealistically high

**Observation:** Median R&D intensity (xrdq / saleq) across all firm-quarters
is **66%**. Mean is **77%**.

**Real-world benchmark.** Even top R&D-spending biotech firms run 25–30%
intensity at peak (Moderna pre-COVID, Vertex peak, Genentech early
years). Pharmaceutical industry average is ~15%. Pre-revenue biotech can
spend nearly all its raised capital on R&D, but the "intensity ratio"
divides by *revenue* — meaningless for pre-revenue firms. Once a firm
has revenue, sustaining 66% R&D intensity for 20 years is not realistic.

**Probable cause.** The firm prompt strongly encourages R&D
("Phase III has a mandatory floor", "Gen 2 transition is the central
strategic milestone"). The env never grants Gen 2, so firms keep
spending on R&D without payoff. They have nothing else strategic to
do — capacity expansion alone doesn't drive a 20-year strategy.

**Likely effect.** The Wave ν+11 env-prompt rewrite (granting Gen 2 at
3× threshold) should reduce this. After Gen 2 transitions actually
happen, firms will probably reduce R&D intensity as the post-Gen-2
firm has a different optimization problem.

**Recommendation.** No firm-prompt change yet. Re-measure after run-3.
If R&D intensity remains at 60%+, then loosen the firm prompt's R&D
language.

---

## E2. Zero dividends, $300M total buybacks vs $6.3B total equity raised

**Observation.** Across 80 quarters × 20 firms, the industry paid:
- **$0** in dividends
- **$300M** in buybacks (all by firm_0)
- **$6,301M** in equity issuance

A 21:1 ratio of new-equity to capital-return is sharply asymmetric.
Real biotech runs ~3-4:1.

**Probable cause #1: GAAP block.** "Dividends are blocked if retained
earnings are negative" is enforced in `clamping.py`. Every firm has
negative RE (cumulative NI -$20B → RE deeply negative for nearly all
firms). So nobody can pay dividends.

**Counter-evidence.** firm_14 had +$55M RE at terminal date and **could**
have paid a dividend. Didn't. So even with positive RE, firms don't
choose dividends.

**Probable cause #2: prompt-side.** The firm prompt's cash-allocation
reflection asks firms to consider "RETURN TO SHAREHOLDERS" as one of
three options. But all 5 management philosophies (Aggressive Growth,
Premium Innovator, Value Operator, Fast Follower, Marketing Powerhouse)
have language strongly biased *against* returning capital. Even Value
Operator says "capital preservation IS the strategy" rather than
"return when no superior use exists".

**Recommendation:**
- Update Value Operator philosophy: explicit "we return capital when
  there's no productive use, especially when public-market valuations
  are stretched"
- Add a concrete numerical heuristic to the cash-allocation reflection:
  "if your trailing-4Q operating cash flow is positive AND you have
  >2× annual revenue in cash AND you can articulate no specific
  deployment, dividends or buybacks are the recommended action"
- Watch run-3 for any change

---

## E3. Death-spiral firms: 32 equity issuances by firm_9

**Observation.** firm_9 issued equity in **32 of 80 quarters** (40% of
its life). Cumulative issuance: $855M. firm_1 had 22 issuance quarters.
firm_10 had 15, firm_16 had 10.

This is a classic death-spiral pattern: firm raises equity at falling
prices, dilutes existing holders, raises again. Sustained for years
without resolution.

**Probable cause.** The investment bank approves repeated equity
issuances even when the firm is operationally distressed. Wave ν+10
added "REVIEW YOUR OWN TRACK RECORD" to the IB prompt, but it's not
strong enough — IB still approves the 22nd, 25th, 30th issuance.

**Real-world analog.** Investment banks DO approve repeated issuances
for biotech in a hot market. But there's typically a price floor
(reverse split, restructuring) once dilution becomes severe. The
simulation never triggers reverse splits or "no-deal" outcomes from
the IB.

**Recommendation:**
- Tighten IB prompt: "after 5 issuances at successively lower prices
  with no revenue improvement, you should DECLINE further issuances
  and recommend either restructuring or a reverse split"
- Add a reverse-split mechanic to the simulation if shares outstanding
  exceed some threshold of book value
- Watch run-3 for whether firm_9-style death spirals continue

---

## E4. Industry never reaches commercial scale

**Observation.** At Q80 (terminal), the largest firm (firm_9) had
quarterly revenue of $219M, annualized ~$876M. Industry total was
$584M/quarter (=$2.3B/year).

**Real-world benchmark.** A leading firm in a $2T-TAM industry over
20 years should be reaching $5–15B/year. The longevity-drug template
explicitly anchors $2T mature TAM. Industry at $2.3B/year = 0.1% of
TAM after 20 years. That's not "early stage" anymore.

**Probable cause.** The env's demand allocation seems to be capacity-
constrained at ~250 units/firm × ~10 firms = 2,500 units/quarter, at
prices ~$100-200K → ~$250-500M/quarter. The env literally cannot
allocate more demand than firms can produce.

But firms' capacity is bounded by base capacity (250 by default) plus
acquired capacity. Since firms don't aggressively expand capacity
(capex would help), the industry never breaks the supply ceiling.

**Recommendation.**
- Track capex over time. Are firms investing in capacity?
- The firm prompt should include a "capacity-constrained-pricing"
  observation: when env signals total demand > firm_capacity for
  multiple quarters, capex should be a high priority
- Or: make the env's market signals show actual unmet demand
  prominently, so firms see "industry under-served by X units/Q"
  and plan capex accordingly

---

## E5. Top-firm share volatility

**Observation.** Top-firm share fluctuates from 16.7% (Q40) to 50.2%
(Q47) — a 3× swing in 7 quarters. Average HHI swings 1,030–4,158.

Real industries do not have this volatility. share gains/losses are
typically <5pp/quarter.

**Probable cause.** The env's market-share allocation is based on
capability + brand + price + idiosyncratic match. The match shock has
high variance. The result is per-quarter share that swings dramatically.

**Recommendation.** Add prompt language: "share gains/losses
quarter-to-quarter should be modest unless a specific catalyst applies
(price war, generation transition, distress acquisition). Default
share inertia is high — last quarter's share is the strongest predictor
of this quarter's share for the same firm."

---

## E6. PE evaluators routinely overpay

**Observation.** From the PE rounds CSV, lead investor valuations
ranged from $200M (early-stage seed) to $3.75B (late-stage). At Q80,
firm_8 went from $727M post-money to a default outcome with all
stakeholders zeroed (negative NPV). Cumulative PE invested $4.1B with
$2.7B recovered = 34% loss rate.

**Real-world benchmark.** Top-tier biotech VC has ~30% loss rate but
~3-5× MOIC on winners. Here, MOIC averaged 0.04x for one firm, 0.80x
for another — both well below 1×. The PE evaluators are funding
firms that don't generate returns.

**Probable cause.** The PE eval prompt has the investor identity
("you are Vanguard Life Sciences Ventures, target IRR 30%, 10-year
horizon") but nothing about WALK-AWAY thresholds. The investor sees
the pitch, scores plausibility, and almost always commits. Real PE
investors decline 90%+ of pitches.

**Recommendation.**
- Add "REJECTION CRITERIA" section to PE eval prompt: pre-revenue
  firms with no path to revenue in 24 months should be declined;
  firms requesting >$200M without a specific milestone-tied use of
  proceeds should be declined; firms with prior PE rounds at falling
  valuations should be challenged
- Track PE decision rates: what % of pitches are accepted? Should be
  10-20%, currently probably 80%+

---

## E7. Activist campaigns 100% ignored

**Observation.** 38 activist campaigns launched (24 buybacks, 10
divestitures, 4 strategic reviews). **Zero** resulted in firm action.
Same as seed-7913.

This is identified in the paper as a finding (option-value of cash
beats one-shot activist demand). But it's overstated in the simulation:
real-world activists win some campaigns (~25-35% per Brav et al. 2008).

**Probable cause.** The firm prompt instructs the firm to "explicitly
address" the activist demand in its strategic memo, but doesn't
require a particular kind of response. The firm typically writes
"acknowledged the activist's concerns; declined to act because of
strategic optionality."

**Recommendation.**
- Add escalation path: if same activist files 3+ campaigns on same
  firm without success, the next campaign triggers a proxy fight
  with binary win/lose outcome (LLM-judged)
- Or: when a firm has cash >5x revenue for 6+ quarters, ANY activist
  buyback campaign requires the firm to either (a) return at least
  20% of excess cash, or (b) name a specific scheduled deployment

---

## E8. No friendly M&A despite many distressed targets

**Observation.** 7 closed M&A deals (all distressed auctions) + 5
`no_solvent_bidder` outcomes. **Zero friendly M&A** across 80
quarters.

**Probable cause.** The friendly-M&A bidder prompt strongly encourages
"NO bid" as the default. The Wave ν+10 counter-offer mechanism
(target board can produce `counter_price_per_share`) has never been
exercised because no friendly bid has ever been initiated.

**Recommendation.**
- The bidder prompt's "REAL-WORLD M&A IS RARE. Most quarters, the
  right answer is NO bid" is too strong. Real biotech M&A is **less
  rare than this prompt makes it sound** — strategic acquisitions
  happen multiple times per industry per decade.
- Loosen to: "M&A deserves serious consideration when (a) you have
  surplus capital relative to your runway needs, AND (b) a peer has
  a complementary capability you cannot easily build, AND (c)
  industry consolidation pressure exists. Default to NO bid in the
  absence of these triggers, but ACTIVELY SEEK these triggers each
  quarter."

---

## E9. Q57 supply-constrained price drop (counterintuitive)

**Observation.** Q57 industry demand surged to ~5,000 units (from
~3,500 prior quarter). All firms capacity-constrained at 250 each
(except firm_9 at 500). Total industry sales 2,750 units. Yet
**prices DROPPED** ($150K → $100K avg).

This is economically unusual. Normally scarcity raises prices.

**Probable cause.** Firms anticipated competitive price-cutting and
preemptively cut their own prices. Coordination failure in
differentiated competition.

**Recommendation.** This is actually an interesting *finding* — could
be worth flagging in the paper as a coordination-failure result. But
worth checking whether it's a one-off in this run or a systematic
pattern that recurs in run-3.

---

## Summary

| # | Finding | Severity | Fix path |
|---|---|---|---|
| E1 | R&D intensity 66% | medium | Watch run-3 (after Gen 2 fix). If persistent, loosen firm prompt R&D language |
| E2 | $0 dividends, $300M buybacks vs $6.3B raised | medium | Tighten cash-allocation prompt + Value Operator philosophy |
| E3 | Death-spiral equity issuance (firm_9: 32 quarters) | medium | Tighten IB underwriting; add reverse-split mechanic |
| E4 | Industry $2.3B/yr at Q80 vs $2T TAM | medium | Surface unmet-demand signal in firm prompt |
| E5 | Top-firm share volatility 16.7% → 50.2% | low | Add inertia language to env prompt |
| E6 | PE evaluators rarely decline | medium | Add rejection criteria + walk-away thresholds |
| E7 | Activist campaigns 100% ignored | low | Add escalation path or hard threshold trigger |
| E8 | No friendly M&A | low | Loosen "default = no bid" framing in bidder prompt |
| E9 | Counterintuitive Q57 price drop | low | Watch — may be a substantive finding |

**For run-3 immediate priority:** Wave ν+11 fixes (Ch11 loosening, env Gen-2 prompt, BS-violation fixes) should be enough to test the binding constraints. E1, E2, E3, E4 are likely downstream — fix what can be fixed by the env prompt change first; revisit if the patterns persist.
