# Economic Review — Part 2 (2026-05-17)

> Continuation of ECON_REVIEW_2026_05_17.md. Per user direction:
> "Find other economics issues; since the error in pricing was not due
> to DCF vs. multiples, no need to worry for now."

## What Wave ν+14e fixed structurally

1. **AI Horde removed from default roster** (the equity-panel root cause).
   firm_1/firm_2/firm_3 now use OpenRouter llama-3.3-70b / qwen-235b /
   gemini-flash-1.5 instead of unreliable AI Horde models. firm_8
   also moved off the rate-limited gemini-2.0-flash. The equity panel,
   which cycles roster firm_1/2/3 for distinct models, will now hit
   actual OpenRouter endpoints.

2. **BackupBackend chain** added in `src/llm_backends.py`. Every LLM
   call site in `cli.py` is now wrapped with a backup pool
   (llama-3.3-70b, gemini-flash-1.5, qwen-235b on OpenRouter). When
   the primary backend persistently fails, the chain falls through to
   each backup in turn. Only returns None when EVERY backend in the
   chain has failed. Prints diagnostics when fallback activates.

   Per user direction: "NEVER move forward if missing, just move to
   next AI if repeated failure."

## Additional economic issues found

### Issue A: Friendly M&A — zero bids ever attempted (not blocked, just never attempted)

- `state.action_log` has **0 acquire_firm actions** across all 80
  quarters of run-6
- `outputs/run_1778766913/llm_calls.jsonl` shows **no M&A-related
  role tags** — the bidder LLM was never called OR called silently
- The completed-acquisitions list has 0 entries
- The negotiations_log also has 0 entries (would record contested
  bids)

This means the M&A bidder LLM either:
- Was never called for any firm (every firm gated out by
  `ceo_search_in_progress` or `acquisition_integration_cost > 0`)
- Was called but returns `{"bid": false}` every time

The bidder prompt was softened in Wave ν+11 from "REAL-WORLD M&A
IS RARE" to "REAL-WORLD M&A HAPPENS — but not casually" but the
behaviour did not change. The LLM still defaults to no-bid.

**Likely cause**: the M&A bidder prompt's framing around "consider
strategic fit" + "consider integration costs" + "consider price
fairness" + "consider walking away" puts the LLM into a permanent
defensive crouch. Real strategic M&A activity often comes from
opportunism rather than careful evaluation.

**Not fixing in this commit** — flagged for prompt review.

### Issue B: Sell-side analyst target prices ARE reasonable; the equity panel ignored them

- analyst_forecasts.csv has 1489 forecasts across run-6
- target_price range: -$395 (negative, broken) to $61,200 (high but
  reflects Gen-4 firm reality), mean $661
- The high prices show analysts CAN see that firm_1 at $43B/Q revenue
  should be priced >> $30/share
- But the equity panel (which is supposed to digest analyst notes as
  input) never ran, so the analyst signal never landed in the price

When the equity panel actually runs in run-7, it will see these
analyst target prices and (hopefully) anchor to them. The bug was
entirely upstream in the panel wiring.

**Sub-issue**: a small number of analyst forecasts have target_price
< 0 (-$395 found). Negative target prices are economically
non-sensical (you can't pay someone to take your stock). Worth
adding a `max(0.01, ...)` floor in the analyst-forecast parser.

### Issue C: 82 analyst forecasts have empty firm_id

Out of 1489 total, 82 (5.5%) have `firm_id = ""`. These are likely
parse failures from the analyst LLM response. They're stored anyway,
contaminating the analyst_forecasts.csv dataset. The downstream
mean/median of target prices is then off by ~5%.

**Fix**: drop forecasts with empty firm_id at parse time, log the
failure.

### Issue D: analyst_3 (microsoft/phi-4) underperforms — 88 forecasts vs 643/456/302 for the others

| analyst | model | forecasts |
|---|---|---|
| analyst_1 | meta-llama/llama-3.3-70b-instruct | 643 |
| analyst_2 | z-ai/glm-4-32b | 456 |
| analyst_4 | google/gemma-3-12b-it | 302 |
| analyst_3 | microsoft/phi-4 | **88** |

analyst_3 is 7× lower than analyst_1. Either:
- phi-4 is failing on most calls
- phi-4 has a different stagger pattern (publishes Q1+Q4 only,
  which is half-frequency, so should be ~322 not 88)

**With backup chain**, phi-4 failures will now fall through to a
backup model, so analyst_3 should produce comparable output in run-7.

### Issue E: CEO over-turnover (290 total fires, ~73 per firm if uniformly distributed)

Looked into this. Actual incarnations on active firms: firm_0=5,
firm_1=2, firm_4=5, firm_5=6. The 290 total is across all firms
including defaulted ones over their entire histories. Per-firm rates
are 13-40 quarters per CEO, which is plausible biotech tenure.

**Not a bug**.

### Issue F: Equity issuance pricing — initial IPOs reasonable

run-6 IPO summary:
- firm_0 Q3 2031: 11.7M shares @ $17.50/sh, raised ~$183M
- firm_1 Q3 2031: 16.7M shares @ $30.00/sh, raised ~$460M
- firm_5 Q2 2032: 11.2M shares @ $22.50/sh, raised ~$229M
- firm_4 Q3 2032: 22.1M shares @ $30.00/sh, raised ~$615M

These are realistic biotech IPO sizes. The bug was the AFTER-IPO
price never moving, not the IPO itself.

### Issue G: Most firms (16 of 20) ended dormant with $0-5M cash

This was the "1100+ pitch LLM failed" bug — backends only built for
n_firms_initial=6. **Already fixed in Wave ν+14b.** Spawned firms
firm_6..firm_19 now get pitch backends, so PE eval will actually run
on them and (per the Wave ν+14 "real PE makes seed bets" prompt) some
should close rounds.

### Issue H: Firm decisions parsed silently as None

Whenever a firm LLM returned malformed JSON, the firm fell back to a
"carry-forward" decision (continue prior quarter's behaviour). This
is a soft fallback but it MASKS LLM failures and produces stale
behaviour. **With the backup chain**, primary failures fall through
to a different model before falling back to carry-forward. Same
firms will now have a hope of producing a fresh decision.

## What needs validation in run-7

1. Equity panel actually runs every quarter → action_log has
   ~80 price_equity entries per firm × 4-20 firms
2. firm_1 equivalent (mature Gen-4 firm) prices update from analyst
   target signals + earnings — not frozen at IPO
3. Spawned firms (firm_6+) get pitches and at least some close PE rounds
4. analyst_3 produces output comparable to peers
5. No silent "pitch LLM failed" messages from dispatcher misses

## Lower-priority issues (not fixing this round)

- M&A bidder defaults to no-bid (issue A) — prompt work
- Negative target prices from analysts (issue B sub)
- Empty firm_ids in analyst forecasts (issue C)
- Debriefs for dormant firms — fixed Wave ν+14c

## Commits this session

- `5a936c0` — ECON_REVIEW part 1 (isolated equity panel never-ran bug)
- (this commit) — ECON_REVIEW part 2 + Wave ν+14e: AI Horde removal +
  BackupBackend chain wired into all LLM call sites
