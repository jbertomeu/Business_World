# Wave ν+8 — Changes Applied This Session

## What was implemented

### 1. Bug A fix: equity-market PANEL with median pricing (replaces single LLM)

**Problem:** Single equity-market LLM occasionally produced unphysical
prices — firm_9 jumped $79.50→$535 in one quarter, firm_3 jumped
+185% on declining fundamentals. No clamp, no second opinion.

**Fix:**
- `src/equity_market.py` — `make_equity_market(backend_or_panel, …)`
  now accepts either a single backend (legacy) or a list of backends.
  When given a panel, all members run in parallel with the same prompt
  and the **per-firm median** price is taken (robust to single-LLM
  outliers without imposing a quantitative ceiling).
- The result dict carries `panel_votes` (list of all per-LLM prices)
  and `panel_n_responses` for transparency.
- Prompt now includes:
  - **Rolling 4-quarter price history** per firm (anchors via trajectory,
    not just single prior point)
  - **Recent management guidance** (firm's own forward plan as
    additional anchor info)
- `src/cli.py` — wires a 3-LLM panel by default, cycling distinct
  models from the firm roster (gets natural model diversity for free).
  Falls back to single backend if only one model available. Roster can
  override with `equity_market_panel_1..N` keys for explicit panel
  composition.

**Risk:** low. The verifier is qualitative (no thresholds), and the
panel falls back gracefully to single-LLM behavior when the roster
doesn't have multiple models. Median is more robust than mean to
outliers.

### 2. Bug B fix: env Gen2 advancement prompt

**Problem:** env never granted `product_advance: true`. Multiple firms
crossed $200M cumulative R&D threshold (firm_0 reached $343M, firm_9
$305M, firm_2 $562M) without advancing in 39 quarters.

**Fix:** `src/prompts.py` env system prompt section 3 (R&D OUTCOMES)
now explicitly tells the env:
- Threshold is **guidance, not exact** — firms reach Gen2 at
  different times depending on R&D quality, team talent, regulatory
  luck
- Firms moderately past threshold MAY advance; firms far past it
  SHOULD usually advance unless something is holding them back
- Spread advances over time (don't grant every qualifying firm at once)
- Narrate the specific catalyst (Phase 3 readout, regulatory approval,
  lead-compound milestone)

This unblocks Gen2 transitions while keeping the env's qualitative
discretion. Different firms will reach Gen2 at different cumulative
R&D levels because the env reasons about quality, not just dollars.

### 3. Cash-allocation reflection (firm prompt)

**Problem:** firm_9 ended Q80 with $13.2B cash on $82M Q80 revenue
— extreme hoarding with no explicit reasoning. firm_14 sat on $3.1B
similarly.

**Fix:** `src/prompts.py` firm system prompt — added a CASH-ALLOCATION
REFLECTION block (qualitative, no numbers). Firms are now asked to
debate three options whenever cash position is meaningful:

1. **Hold for strategic optionality** (with specific scenario stated)
2. **Deploy into the business** (with specific deployment rationale)
3. **Return to shareholders** (buybacks/dividends, with reason
   no superior use exists)

This nudges firms to articulate a stance every quarter rather than
silently hoard. Real activists and public-market investors notice
unexplained cash pile-ups; the prompt language reflects that.

### 4. Bug D fix: auction destroyed defaulted firm's pre-default cash

**Problem:** `apply_auction_result()` in `src/distressed_auction.py`
wrote `cash=amount` (sale proceeds), overwriting any pre-default cash
the firm was holding. firm_10 had $370M cash before default, after
$450M auction sale it ended up with $370M cash again — meaning
$370M of pre-default cash silently disappeared, replaced by sale
proceeds. The BS identity broke by exactly the lost cash. We
observed phantom equity in firm_10 (+$246M residual), firm_11
(+$109M), firm_12 (−$1560M).

**Fix:** `cash=defaulted.cash + amount` (sale proceeds **added** to
existing cash). Then a multi-tier creditor waterfall pays LTD first,
then revolver. Reflects realistic bankruptcy proceeds distribution.

**Tests added:** `tests/test_auction_cash_preserved.py` — 2 tests
covering both the bug case (pre-default cash preserved) and the
zero-cash case (no regression).

### 5. Bug E fix: BS invariant check skipped defaulted firms

**Problem:** `_check_bs_invariants()` had `if not firm.is_active:
continue`, so auction-induced residuals on defaulted firms were
silent. The residuals from Bug D went unlogged (0 entries in
`bs_violations.jsonl`).

**Fix:** Removed the skip. All firms now get checked, including
defaulted. Their stub state continues to live in compustat / panels
and any imbalance contaminates downstream analysis, so it's worth
seeing.

### 6. Documentation: firm_14 was a non-issue

You asked what I meant about firm_14. I had flagged that firm_14 took
the industry lead at Q49 with capability=60, lower than incumbents
like firm_0 (89). I marked this as potentially weird. **On reflection
it's correct emergent behavior:** a leapfrog's advantage is its
specific niche/feature/brand novelty, not raw capability. Tesla led
EVs without Toyota-scale manufacturing. The env weighting niche fit
+ brand novelty over raw capability is the right answer. **No fix.**

---

## Discussion items not implemented this session

### Chapter 11 vs Chapter 7 (deferred to next wave)

**Why deferred:** Substantial structural change requiring:
- New `default_type: str` field on FirmState
- New "bankruptcy judge" agent (likely env-driven) to classify Ch11
  vs Ch7 based on operational viability
- Ch11 path: equity wiped, debt restructured, firm KEEPS operating
  under court protection; emergence path back to active
- Ch7 path: current behavior (full liquidation via auction)
- Multiple downstream code paths to gate (PE pitches, M&A bidding,
  governance)

**Recommendation:** Capture as Wave ν+9 design. Quick implementation
sketch:

```python
# When a firm's mandatory_obligations exceed cash + credit:
#   Call bankruptcy_judge_fn(firm, recent_4q_flows) → 'chapter_11' | 'chapter_7'
# If chapter_11:
#   - state.firms[fid] = firm.evolve(
#       default_type='chapter_11',
#       founder_shares=0, public_shares_outstanding=0,
#       common_stock=0, apic=0, retained_earnings=0,
#       long_term_debt=firm.long_term_debt * 0.5,  # restructured
#       quarters_in_chapter_11=1,
#     )
#   # Firm STAYS is_active=True but flagged
# If chapter_7:
#   - is_active=False, auction phase fires (current path)
```

The decision criterion (operating income TTM positive vs persistent
losses) would be qualitative in the bankruptcy judge's prompt, not
hardcoded.

### Cash-rich defaulted firms — partially addressed

Bug D fix prevents NEW phantom cash issues. firm_4's pre-existing
$852M cash post-default is residual data from the broken Q12 default
(pre-fix). Going forward, defaulted firms will have their cash
properly distributed via the creditor waterfall.

In Ch11/Ch7 design, a Ch11 firm with positive operations can also
end up with substantial post-restructuring cash if creditors took
haircuts — that's realistic and fine.

---

## Bugs still open / pending discussion

| # | Issue | Status |
|---|---|---|
| pre-existing firm_2 $78M BS residual | from broken pre-Q41 era | Not fixable post-hoc; flag in research |
| firm_4 $852M defaulted cash | residual from broken Q12 default | Same — pre-existing data quality |
| Ch11/Ch7 distinction | designed, not implemented | Wave ν+9 |
| Dashboard / debrief artifacts | proposed, not built | Pending your green light |

---

## Cumulative bug count for ν+7 → ν+8

- ν+7 bugs: 1 (silent zero fallback), 2 (auction indentation), 3
  (revenue/COGS units), 4 (env-clamp R&D drop), 5 (dict-key key
  mismatch)
- ν+8 bugs: A (equity panel/median), B (Gen2 advance), D (auction
  cash overwrite), E (BS check skips defaulted)

Total bugs found and fixed in 2 waves: **9**.

---

## Test status

- Full suite: **313 passed** (310 prior + 3 new in
  `test_auction_cash_preserved.py`).
- Mock smoke: clean.
- All fixes are conservative (defense-in-depth, qualitative prompt
  additions, or correct only when previously-buggy path fires).
