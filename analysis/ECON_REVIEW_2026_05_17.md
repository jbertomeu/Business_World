# Economic Review — 2026-05-17

> Per user direction: isolate the issue first; talk about prompts after.
> Started with the "$413B cash but $502M market cap" anomaly on firm_1.

## Headline finding: the equity panel never ran

**firm_1's price was stuck at exactly $30.00 from Q3 2032 through Q80 —
73 consecutive quarters.** Across the entire run:

- `state.action_log` has **0 "price_equity" entries** (the equity
  market's logged decisions)
- `proposals.jsonl` confirms **0 actor_id="equity_market" entries**
- `state.firms.firm_1.equity_price` was set to $30 at IPO (Q3 2032)
  and never moved
- The "--- Equity Market ---" phase header appears in every quarter's
  log, but **no per-firm price lines** ("firm_X: $XX.XX/sh (method) …")
  follow it

This is not "the panel chose bad multiples." It is **the panel
literally produced an empty `eq_decisions` dict every single quarter
for 80 quarters straight**. The orchestrator's `if eq_decisions:`
guard then skipped the price-update + log block.

## Root cause: the panel uses 3 unreliable AI Horde backends

`src/cli.py` lines 727-743 construct the panel by cycling through
distinct roster firm models (firm_1, firm_2, firm_3 by default). The
roster defines firm_1, firm_2, firm_3 as **AI Horde free
community-hosted models** (`koboldcpp/gemma-4-26B`,
`koboldcpp/Dark-Nexus-24B`, `aphrodite/Behemoth-R1-123B`):

```yaml
firm_1: { model: koboldcpp/gemma-4-26B..., backend: aihorde }
firm_2: { model: koboldcpp/Dark-Nexus-24B..., backend: aihorde }
firm_3: { model: aphrodite/Behemoth-R1-123B..., backend: aihorde }
```

AI Horde is a community-hosted free LLM network. On long-running
research workloads, hits are unreliable — models timeout, queue
indefinitely, or return malformed output. With ALL three panel votes
failing every quarter, the equity panel's quorum logic (requires 2 of
3 votes) produces no decisions.

Critically: **the run-6 firm OVERRIDES (in
`validation_20f_80q_run6.yaml` agents block) assign firm_0..firm_19
to OpenRouter models**, but the equity panel's construction reads
**from the ROSTER, not from the run-6 effective firm backends**. So
the run-6 firms work fine on OpenRouter (which is why firm_1 reached
Gen-4 with $43B/Q revenue), but the equity panel silently used the
default-roster AI Horde models that were never substituted.

**This is the bug that produced "P/E of 0.005."** Not bad valuation
methodology, not bad comp selection — the panel never ran at all.

## Other economic anomalies found in this review

### 1. Zero friendly M&A in 80 quarters

`state.completed_acquisitions` is empty across run-6. Despite:
- `ma_enabled: true`
- M&A bidder language softened in Wave ν+11 from "REAL-WORLD M&A IS
  RARE" to "REAL-WORLD M&A HAPPENS — but not casually"
- Regulator gate added that should only block certain deals (not all)

Zero friendly bids cleared. Either no bidder firm ever proposed an
acquisition, or every proposal was blocked by the target board or
regulator. Worth checking: did any `pending_bids` ever exist? Or is
the bidder fn silently failing the same way the equity panel did?

Distressed auctions DID fire once (firm_0 sold to firm_1 at $150M
post-Ch7). So the asset-disposition machinery works; the friendly-M&A
LLM path may not.

### 2. CEO over-turnover

`action_log` has 290 `fire_ceo` events across 80 quarters. Most are
on dormant or defaulted firms (long after they stopped operating).
On the 4 active firms, current CEO incarnations are 5, 2, 5, 6 —
meaning each active firm has had 2-6 CEOs over its lifetime.
firm_5 has had 6 CEOs in 77Q — one CEO every ~13 quarters. That's
~3 years per CEO, which is at the low end of realistic for biotech
but plausible.

Worth investigating: are governance LLM firing decisions data-driven
(firms underperforming their plan) or noise-driven (different LLM
firing for different reasons each quarter)?

### 3. Debt market WORKS (initial false alarm)

I initially saw "all 41 facilities $0M @ 0%" but that was a column-
name mistake on my part (`principal` vs `original_principal`). The
actual data is clean: facility sizes $0.1M–$500M, rates 1–10%/Q
(4–40%/yr). Pre-IPO firms get high rates; mature firms get bond-
quality terms. The IB pricing works.

### 4. firm_0 phantom equity (already fixed Wave ν+14b)

`enter_chapter_11` wiped `common_stock + apic` but kept
`treasury_stock`. Over 65 quarters firm_0 accumulated -$9.95B
phantom equity destruction. Fix landed in `5f07754`.

### 5. Backends only for n_firms_initial (already fixed Wave ν+14b)

Per-firm pitch / IPO / planning dispatchers silently returned None
for spawned firms (firm_6+). Fix landed in `5f07754`.

## What needs fixing — in this order

| # | Issue | Fix needed | When |
|---|---|---|---|
| 1 | Equity panel uses unreliable AI Horde models | Add explicit `equity_market_panel_1/2/3` roles in roster with reliable OpenRouter models; panel construction prefers explicit panel roles over roster-firm cycling. **PURE WIRING FIX.** | Now |
| 2 | Equity prompt language allows multiples even with poor comps | After fix 1 lands and the panel actually runs, tighten prompt to emphasize **DCF as primary method** for any firm with positive operating cash flow, and **comp-quality requirements** (compare-cash-rich vs cash-rich, etc.). **PROMPT WORK.** | Per user — after isolation confirmed |
| 3 | Friendly M&A never fires | Investigate whether bidder fn returns None silently (same pattern as equity panel) or whether prompts produce zero bids. | Next iteration |
| 4 | Investment bank prompt may be similarly affected | Check whether IB panel also uses AI Horde via roster cycling. **Inspect now.** | Now (cheap check) |

## Sequencing per user direction

1. ✅ **Isolated the equity-pricing nonsense to backend wiring** (this doc)
2. Next: confirm investment-bank panel doesn't have the same wiring bug
3. Then: present prompt changes for DCF emphasis + comp-quality rules
4. Then: relaunch run-7 with all fixes
