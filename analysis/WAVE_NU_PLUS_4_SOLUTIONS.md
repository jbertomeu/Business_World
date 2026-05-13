# Wave ν+4 — Qualitative Solutions

This document captures the qualitative-only design for each issue raised after the 20-year run. **No hardcoded numerical thresholds in any prompt or code path** — agents reason emergently using scenario context.

---

## Issue 1: Debt should follow lending best practices

**Current**: The commercial bank and investment bank LLMs price loans for any firm requesting one. They occasionally decline but don't perform structured underwriting. Result: pre-revenue firms with no operating cash flow take on debt and the interest burden accelerates default.

**Qualitative solution**:
- Lender prompts (commercial_bank, investment_bank) now require an explicit underwriting analysis BEFORE pricing the loan:
  - "Do you observe a positive operating cash flow stream sufficient to service interest comfortably?"
  - "What pledgeable assets exist (PP&E, receivables, inventory)?"
  - "Compute and report standard credit ratios you find relevant (interest coverage, debt-to-equity, cash runway under proposed loan, debt-to-asset). State which look concerning."
  - "If the firm has no positive cash flow AND no meaningful pledgeable assets, decline the loan and refer the firm to equity capital."
- Lenders are reminded that debt for pre-profit / pre-revenue startups is a real-world rarity; equity is the appropriate vehicle until the firm has operating proof.
- Output of the lender LLM must include the ratio analysis so we can audit.

**Result**: Firms unable to service debt won't take it on — they'll be redirected to PE rounds. Debt becomes a tool for firms with proven cash flow + collateral, not a runway extender for distressed startups.

---

## Issue 2: 1-Q deaths should not happen

**Current**: An entrant arrives with founder seed, immediately needs a Series A. If the PE round produces zero or insufficient bids, the entrant has $26M of capability burn (R&D + S&G&A) hit it in quarter 1 and dies. Eight firms in our run had 1-Q lifespans this way.

**Qualitative solution** — entrant dormant-state mechanism:
- When an entrant arrives, the firm states a minimum funding threshold required to execute its plan (entry-judge specifies this in the entrant_profile, qualitatively: "the founders need a Series A round at a meaningful fraction of their plan-B budget to operate").
- After the first PE round attempt, if the round fails OR fills below what the firm's plan-B requires, the firm can choose to enter a DORMANT state instead of operating:
  - In dormant state: no R&D, no production, no S&G&A, no revenue. Cash preserved, capability decays slowly.
  - The firm can re-pitch in subsequent quarters, hoping for a better PE response.
  - After a few dormant quarters with no funding, the firm's founders close down voluntarily (lose their seed but no further accumulated losses).
- The firm itself decides — emergent behavior — whether to operate at minimal scale, wait dormant, or wind down.

**Result**: Entrants don't die in 1Q. They either (a) raise enough to operate, (b) wait dormant, or (c) wind down without burning more than seed. PE failures don't auto-default firms.

---

## Issue 3: Better endogenous entry — small firms make sales, more leapfrogging

**Current**: Entrants enter with low capability + low brand + small cash. The env allocates them near-zero share even if their pricing is reasonable. Most die before they can build traction.

**Qualitative solution**:
1. **Env share allocation for differentiated small firms**: The env prompt is reinforced — small firms in differentiated-product industries DO retain a niche customer base even at low capability/brand. The env should allocate at least a small but meaningful share to any operating firm with reasonable pricing (not zero). Larger firms don't dominate share simply by being larger.
2. **Stronger leapfrog framing**: The entry judge is reminded that real industries often see breakthroughs from outside the incumbent set (Google in search, Apple in personal computing, garage-stage Microsoft). Leapfrog candidates can arrive with ALREADY-DEVELOPED technology that doesn't require them to spend years catching up via R&D — they got it from academic spinout, prior firm experience, or a fundamental insight the incumbents missed. The judge should flag leapfrog candidates more readily when the industry is concentrated, narrating the specific breakthrough.
3. **Profit at small scale must be possible**: If a firm scales down R&D significantly (relying on its already-developed capability), it should be able to sell its existing Gen 1 product at a margin and operate near break-even. The env's allocation should respect this: a small efficient operator keeps its niche; the env doesn't punish low-R&D operations as long as the firm is delivering its product.

**Result**: Small entrants survive longer, find niches, and can either scale or hold steady. Leapfrog entrants can credibly displace concentrated incumbents.

---

## Issue 4: Monitoring + factual hallucination check

**Current**: Long-lived firms occasionally hallucinate context. The most striking example: firm_2 at Q75 produced board minutes saying "this is our first board meeting and quarter of operations" despite 75 quarters of continuous operation. There is no automated check for factual consistency.

**Qualitative solution** — fact-check gatekeeper LLM:
- After board minutes (or any major LLM-authored artifact: pitch, plan, prospectus, annual report) are produced, a SEPARATE gatekeeper LLM reads the artifact alongside the firm's true state and history summary.
- The gatekeeper checks for factual hallucinations:
  - Does the firm correctly recognize its current quarter, lifecycle stage, IPO status, cumulative R&D, capability/brand levels?
  - Are stated facts consistent with the provided context?
  - Are the recommendations absurd given current cash / industry state (e.g., proposing capacity expansion while at <2Q runway)?
- If the gatekeeper flags issues, the original LLM is re-prompted with the gatekeeper's specific corrections, and the artifact is regenerated.
- Cap on iterations to prevent loops.

Additionally: the firm prompts must include the firm's actual operating history at the top — "you have operated for N quarters; you have completed N planning cycles; here's a compact summary of your prior key decisions and outcomes" — so the firm doesn't lose context over long horizons.

**Result**: No more "I'm a brand new firm" hallucinations from 75-quarter veterans. Factual consistency is enforced.

---

## Issue 7: Per-quarter status visible to the user (this conversation window)

**Current**: When a long run is detached, the user can't see live progress without manually checking the log. Heartbeat exists but requires explicit poll.

**Qualitative solution**:
- Continue using `flush=True` per-quarter status with timestamp (already in place).
- Use Claude Code's `ScheduleWakeup` tool to set hourly status pulses that read the heartbeat + tail the per-quarter log and report progress to this window.
- Each pulse covers the quarters completed since the last pulse (~12-15 quarters at our pace), so the user sees a consolidated update without losing per-quarter granularity.
- When the run completes, the wakeup chain naturally terminates (final report).

**Result**: User sees periodic status without having to ask.

---

## Issue 8: Reactivate M&A with proper controls

**Current**: M&A is currently disabled because the env-judged version was rapacious (acquired every entrant at fire-sale prices), and the per-firm bidder version had no constraints on frequency or target screening.

**Qualitative solution** — re-enable M&A with the following controls (all emergent, no hardcoded triggers):

1. **Sparse trigger**: M&A activity is rare in real industries. The bidder prompt is reminded that a quarter without M&A is the norm. Bidders make a deal only when:
   - The target is doing very poorly (cash crisis, multi-quarter performance deterioration), OR
   - There's a strong strategic opportunity (capability complement, customer-base acquisition)
   - Random opportunistic pursuit is acceptable but should be uncommon
2. **Owner review**: The target firm's board (representing founders, PE, and public) does its own valuation analysis before accepting:
   - What's our standalone-firm B-plan value?
   - Is the offered price meaningfully above standalone value (premium justification)?
   - What's the integration risk?
   - Reject the bid if standalone value clearly exceeds offered price.
3. **Goodwill accounting**: Already correct in `process_acquisition` (purchase price > book value → goodwill on BS; bargain purchase → gain to RE). Verify in tests.
4. **Asset absorption**: When deal closes, the acquirer absorbs:
   - All identifiable assets (PP&E, AR, inventory, cash) — already in `process_acquisition`
   - Capability stock (with friction — already implemented in distressed_auction; replicate for M&A)
   - Brand stock (with friction)
   - Market share (transferred via env's next-quarter share allocation)
   - Customer relationships → reflected in inherited brand
   - Employees → reflected in inherited capability
5. **Frequency**: Per-firm bidder LLMs see a richer prompt that emphasizes "real industries see no M&A in most quarters; only act when justified."

**Result**: M&A becomes occasional, target-defended, accounting-correct, and produces real consolidation when it does happen.

---

## Extras: Gen 2 reachability + market generosity + race-to-bottom training

### Gen 2 reachability
- The Gen 2 R&D threshold is scenario-tunable (`SimParams.gen_2_rd_threshold`). The well_capitalized scenario currently uses the default (a high value). For shorter horizons we lower this scenario value so Gen 2 is reachable in plausible run lengths.
- Lowering the threshold is a SCENARIO change (legitimate — scenario is the conduit for numbers), not a prompt-rule.

### Market generosity (firms not drowning in fixed cost)
- The env's "survival & stability" block already encourages NOT pushing all customers to one firm. We strengthen this:
  - "Differentiated firms with reasonable pricing should retain enough share to cover their unit margin × volume × reasonable allocation. The market should not concentrate so heavily that careful operators cannot reach break-even."
  - "Do not over-allocate to the price leader at the expense of differentiated mid-tier firms — the resulting concentration undermines industry stability."
- Implicitly: if firms set price well above unit cost AND maintain differentiation, the env should produce a share allocation that lets them reach positive contribution margin.

### Race-to-bottom training (price-war reflection)
The firm decision prompt's pricing reflection is strengthened:
- "Before setting price, debate explicitly: are competitors moving prices up or down? What does this trend suggest about the equilibrium?"
- "If you are pricing near or below unit cost, you are not profitable per sale. Re-examine: is this strategically warranted (specific catalyst, market entry tactic) or is it a default that you should reconsider?"
- "Consider: if you raise price modestly, do you keep enough share to be profitable? Or does competitor undercutting destroy your margin?"
- "Price wars are real, but they are not the only equilibrium. Differentiated firms can sustain stable prices above cost. Tacit coordination — every firm pricing where its differentiated value is captured — produces healthier industry outcomes."

### Underlying philosophy
All of these solutions preserve the no-hardcoded-numbers rule. Behaviors emerge from:
- Scenario-provided numbers (legitimate conduit)
- Agent reasoning over scenario context + observed firm/market state
- Qualitative prompt guidance about realistic dynamics

The simulation should produce realistic long-horizon outcomes through agent emergence, not through hardcoded behavioral rules.
