# Wave ν+9 — Bug Sweep

**Status: all fixes applied, 326 tests passing (13 new), mock smoke
clean.** See bottom of file for the post-fix status note.

Four parallel exploration agents covered the financial-intermediary,
governance/M&A, core-engine, and data/config layers. Thirteen bugs
were flagged; I have verified the four highest-severity items by
inspecting the actual code. The most important finding is that the
zero-generation-advance result we discussed at length in the paper has
a code root cause: the env LLM's `rd_outcomes` payload is never read
by the orchestrator or the verifier.

---

## HIGH severity (4 issues)

### H1. `rd_outcomes` array silently ignored — explains zero Gen2 advances

**Files:** `src/orchestrator.py:1276–1291`, `src/env_verifier.py:237–292`

The env system prompt (`prompts.py:1515–1517`) asks the LLM to output:

```json
{
  "firm_outcomes": [{"firm_id": ..., "units_sold": ..., "market_share": ...}],
  "rd_outcomes": [{"firm_id": ..., "product_advance": false,
                   "process_cogs_reduction_pct": 0.01,
                   "delivery_advance": false}]
}
```

But the orchestrator reads `product_advance` and friends from inside
each `firm_outcomes` entry, **never from the `rd_outcomes` array**. If
the env LLM follows the schema correctly (placing R&D advances in the
top-level `rd_outcomes` block), every advance is silently dropped at
the parse step. The env_verifier perpetuates the same pattern: it
reads R&D fields from `firm_outcomes[fid]`, not from `rd_outcomes`.

This is the root cause of the zero-generation-advance result we
described in the paper as "residual env conservatism." The env may
have been granting advances all along — we never read them.

**Fix:**

1. After line 1272 in `orchestrator.py`, merge the `rd_outcomes`
   array into per-firm outcomes:

```python
for rd in env_outcome.get("rd_outcomes", []) or []:
    if not isinstance(rd, dict): continue
    fid = rd.get("firm_id")
    if not fid or fid not in env_outcome.get("firm_outcomes", {}):
        continue
    fo = env_outcome["firm_outcomes"][fid]
    if isinstance(fo, dict):
        fo.setdefault("product_advance", rd.get("product_advance", False))
        fo.setdefault("process_cogs_reduction_pct",
                      float(rd.get("process_cogs_reduction_pct", 0) or 0))
        fo.setdefault("delivery_advance", rd.get("delivery_advance", False))
```

2. The same merge belongs in `env_verifier._deterministic_clamp`
   before it rebuilds the firm_outcomes dict.

3. Add a regression test that constructs an env response with
   `rd_outcomes: [{firm_id: "firm_0", product_advance: true}]` and
   asserts the resulting `MarketOutcome.product_rd_advance == True`.

### H2. Equity-market panel takes "median" of partial failures

**File:** `src/equity_market.py:236–283`

When 2 of 3 panel backends throw an exception, `_call_one` returns
`None` for each, and the surviving 1-vote "median" is committed as
the share price. This silently undermines the panel-median fix from
Wave ν+8: a single-LLM outlier is exactly what the panel was supposed
to suppress, and a 1-of-3-survivors panel reduces to a single LLM.

**Fix:**

```python
# After collecting votes, before returning:
quorum = max(2, len(backends) // 2 + 1)  # majority of panel
for fid, vlist in votes.items():
    if len(vlist) < quorum:
        # Carry forward prior price; log the partial failure
        prior = prior_prices.get(fid, 0.01)
        decisions[fid] = {
            "equity_price": prior,
            "panel_votes": vlist,
            "panel_n_responses": len(vlist),
            "fallback_reason": f"panel quorum not met: {len(vlist)}/{len(backends)}",
        }
        continue
    # ... existing median logic
```

### H3. Auction agents silently swallow LLM exceptions

**File:** `src/distressed_auction.py:230–233` (judge), `:367–370` (bidder)

Both the auction judge and bidder agent wrap `complete_json()` in a
bare `try/except: return None`. Network errors, malformed JSON, and
content-policy refusals are all indistinguishable from "no bid"
or "no allocation." The orchestrator processes a `None` as if the
agent legitimately declined, so a transient API failure becomes a
quiet "no auction this quarter" event.

This is the same pattern as Wave ν+7 Bug 1 in firm decisions.

**Fix:** Mirror the structured-error pattern used in
`make_violation_resolver`:

```python
try:
    return backend.complete_json(system, user)
except Exception as e:
    import traceback
    return {
        "_error": True,
        "_exception": f"{type(e).__name__}: {e}",
        "_traceback": traceback.format_exc()[:2000],
        "allocations": [],  # safe default
    }
```

The orchestrator can then check `result.get("_error")` and emit a
visible warning to `gazettes.txt` rather than treating the failure
as a non-event.

### H4. `config.get_role()` returns `None` for optional roles, breaking `.backend` access

**File:** `src/config.py:271–282`

If the YAML roster omits an optional role (e.g., `sec`, `data_broker`,
`env_verifier`), the `RoleConfig` field is `None`. `get_role("sec")`
returns `None`, and any caller chaining `.backend` or `.model` on the
result raises `AttributeError`. Most callers in `cli.py` guard with
`if roster.X is not None`, but the contract is implicit and one
forgotten guard creates a runtime crash mid-run.

**Fix:** Add an explicit None check in `get_role`:

```python
result = fixed.get(role)
if result is None:
    raise KeyError(
        f"Role {role!r} is not configured in the roster. "
        f"Optional roles must either be present in YAML or callers "
        f"must guard with `if roster.{role} is not None`."
    )
return result
```

This converts a confusing `AttributeError` deep in a downstream
caller into a clear `KeyError` at the lookup site.

---

## MEDIUM severity (6 issues)

### M1. `process_cogs_reduction_pct` received but never applied (`accounting.py:491–495`)

The orchestrator passes the env's `process_cogs_reduction_pct` field
through to `MarketOutcome`, and `accounting.py` reads it — but the
code body is `pass` with a comment claiming the cumulative formula
already captures it. Inspection shows the cumulative formula reads
`firm.rd_cumulative_process` (advanced only by firm decisions), so
the env's process-improvement signal is orphaned. The fix is one line:

```python
if outcome.process_cogs_reduction_pct > 0:
    base_after_process *= (1.0 - outcome.process_cogs_reduction_pct)
```

### M2. `run_index.csv` schema derived from first row's keys

**File:** `src/output_organizer.py:595`

`csv.DictWriter(f, fieldnames=list(row.keys()))` locks the header
to the first run's keys. New columns added later (config toggles,
extra metadata) will be silently dropped because `extrasaction` is
`ignore`. Fix: define a canonical `RUN_INDEX_COLUMNS` list and use
it explicitly.

### M3. M&A integration-cost comment-vs-math mismatch

**File:** `src/ma_agent.py:244–247`

```python
estimated_target_revenue = target.cash * 0.1   # crude proxy
integration_cost_total = estimated_target_revenue * 0.4   # 10% of annual rev
```

The comment says 10% of annual revenue; the actual math gives
4% of target cash. The `0.4` is also undocumented — whether the
intent is 10% of annual rev (which would be `* 0.1` since cash * 0.1
is already a quarterly proxy) or 40% of estimated annual rev is
unclear. Either correct the math or correct the comment; both as
written is misleading.

### M4. Memory CSVs read without explicit utf-8

**File:** `src/memory.py:145, 234`

`open(path)` uses the OS default encoding, which on Windows is cp1252.
Compustat firm names with curly quotes or em-dashes (which the LLM
narrative occasionally produces) silently fail or round-trip
incorrectly. Fix: `open(path, encoding="utf-8")`.

### M5. Restatement no-op returns empty event

**File:** `src/restatement.py:45–48`

If `cumulative_manipulation < 1.0`, the function returns
`(firm, rows, {})`. Downstream code that treats `{}` as "no
restatement" works correctly, but the empty-dict return path is a
silent success: a SEC-forced restatement of a clean firm produces no
audit trail. Either return a structured no-op event or assert
`cumulative >= 1.0` at the call site.

### M6. `commercial_bank.py` and `investment_bank.py` parse floats differently

`commercial_bank.py:150–151` uses bare `float(...)`; `investment_bank.py`
uses a defensive `_parse_float` helper. A malformed LLM response that
investment_bank tolerates will crash commercial_bank. Move
`_parse_float` to a shared utility and use it in both.

---

## LOW severity (3 issues)

### L1. CEO-style hint disclosed in board prompt (`board_discussion.py:48`)

The board sees a `{ceo_style}` label that's deterministic from
firm_id. This is technically information leakage from the
"board doesn't know CEO type" architectural rule, although the
practical impact is low because the style is a flavor tag rather
than the hidden type itself. Acceptable to leave; document the
boundary explicitly in a comment.

### L2. Restatement uses 1-indexed `fqtr`; rest of code uses 0-indexed `quarter`

**File:** `src/restatement.py:85`

`abs_q = (fyearq - 2031) * 4 + fqtr` produces 1-indexed quarter
numbers, while the rest of the codebase uses 0-indexed `firm.quarter`.
Comparisons across the boundary off-by-one. Either subtract 1 here
or document the convention.

### L3. M&A capability/brand absorption rates are magic numbers

**File:** `src/ma_agent.py:279–282`

`* 0.4`, `* 0.3`, `* 0.5` for capability/brand/R&D absorption are
undocumented and unconfigurable. Move to `SimParams` or a named
constant block.

---

## Summary

| # | Severity | File | Bug |
|---|---|---|---|
| H1 | HIGH | orchestrator.py:1276 + env_verifier.py:237 | rd_outcomes array never parsed (root of zero-Gen2-advance) |
| H2 | HIGH | equity_market.py:273 | Panel takes "median" of partial failures |
| H3 | HIGH | distressed_auction.py:230, 367 | Auction LLM exceptions silently swallowed |
| H4 | HIGH | config.py:282 | get_role returns None on optional roles |
| M1 | MED  | accounting.py:491 | process_cogs_reduction_pct orphaned |
| M2 | MED  | output_organizer.py:595 | run_index.csv schema drift |
| M3 | MED  | ma_agent.py:244 | Integration-cost comment ≠ math |
| M4 | MED  | memory.py:145, 234 | CSV reads without utf-8 |
| M5 | MED  | restatement.py:45 | No-op restatement returns empty event |
| M6 | MED  | commercial_bank.py vs investment_bank.py | Float-parse inconsistency |
| L1 | LOW  | board_discussion.py:48 | ceo_style hint in board prompt |
| L2 | LOW  | restatement.py:85 | Quarter indexing convention |
| L3 | LOW  | ma_agent.py:279 | M&A absorption magic numbers |

**Most consequential:** H1. It is the kind of bug that, in retrospect,
explains an entire substantive finding in the paper. The paper claimed
"zero generation advances reflect env conservatism"; the actual cause
appears to be that the env's R&D advance signals are silently dropped
at parse. Fixing H1 will likely produce visible Gen2 transitions in
future runs.

**Recommend fixing in order:** H1, H4, H2, H3, M1, M2, M4, M6, M5,
M3, then the LOW items as cleanup.

---

## Post-fix status (applied this session)

All thirteen items above were applied. Additional findings during
verification:

### Q81 partial-state snapshot (debrief artifact)

The post-run debrief had been reporting:
- Top-firm share = 100% at Q81
- 10 cumulative defaults
- 92 leapfrog activations
- "firm_3 and firm_8 defaulted at Q81"

Investigation showed Q81.pkl is a partial-state snapshot: the
orchestrator started an unplanned 81st iteration after the 39 planned
quarters had completed (heartbeat shows `sim_quarter_completed: 80`
and `total_quarters_planned: 39`). state.quarter advanced to 81,
some entry/PE-funding logic ran, one firm's flow record advanced
(firm_9: $15.95M), and most other firms' flows were cleared but not
repopulated. The post-run aggregator interpreted the empty flows as
zero revenue and computed firm_9's share as 100%.

The Q81 transitions were also spurious: firm_3 and firm_8's
`is_active=True → False` flips happened during partial-state
processing, and three "defaulted" entries (firm_10, firm_11,
firm_12) appeared to "activate" because the entry/PE phase ran
inside the partial Q81.

**Fix in `analysis/make_debrief.py`:** filter out any snapshot whose
quarter index has no corresponding compustat row (the absence of a
compustat row reliably identifies a partial state). Both
`extract_events()` and `build_panel_data()` now apply this filter.

### Corrected headline figures (post-fix)

| Metric | Before fix | After fix |
|---|---:|---:|
| Run length | 81 quarters | 80 quarters |
| Cumulative defaults | 10 | 8 |
| Active at close | 8 | 9 |
| Top firm at close | firm_9 (100%) | firm_7 (31.8%) |
| Leapfrog activations | 92 | 13 |

The QJE-style paper (`analysis/paper/llm_industry_lab.tex`) has been
updated to reflect the corrected figures and to record the H1
finding (the Gen2-transition result was a parse bug, not env
conservatism). The PDF rebuilt cleanly at 41 pages.

### Tests

`tests/test_wave_nu_plus_9_fixes.py` (13 tests, all passing) covers:

- H1: rd_outcomes merge logic
- H2: equity panel quorum (carry-forward fallback when below quorum,
  median when quorum met)
- H4: get_role raises KeyError on None optional roles + unknown firms
- M5: restatement no-op returns structured event
- M6: parse_float / parse_int / parse_bool tolerate the standard LLM
  failure modes

`tests/test_expansion.py::test_restatement_no_manipulation_noop` was
updated to match the new structured-event contract from M5.

Full test suite: 326 passed, 0 failed. Mock smoke: clean.
