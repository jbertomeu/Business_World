# Wave ν+7 — What Actually Went Wrong in ν+6

**Hard rule (carried forward):** No hardcoded numerical thresholds in any prompt.
All behavior must be emergent. But this document is about a **code bug**, not
prompt design. The fix lives in the orchestrator, not in any prompt.

---

## TL;DR

The "absorbing monopoly" we observed in Q42–Q80 of the ν+6 run is **not an
economic phenomenon**. It is a **silent code bug** in the orchestrator's
parallel firm-decision pool. Six firms started raising a `TypeError` at Q42 and
continued raising it every quarter for the rest of the run. The orchestrator
caught the exception and substituted dataclass-default `RawDecisions` (all
zeros) — silently — for those firms' actual decisions. Six firms output
zero production, zero price, zero SGA every quarter. The seventh firm
(firm_9) was the only one whose LLM kept succeeding, so the env correctly
routed all demand to the only firm producing.

Phase 2 of the run is essentially a single firm, firm_9, operating against
six placeholder zero-output firms whose decision-making was disabled by an
exception handler nobody noticed.

The research-overview paper currently frames Phase 2 as a coordination
failure / focal-point equilibrium / Cooper-John multiple-equilibria
selection. **That framing is wrong.** Real coordinated firm retreat would
look noisy — different firms picking different prices, some halting
production while others scaled back, varied R&D and SGA reflecting different
risk tolerances. What we observed was perfectly identical zeros for six
firms, every quarter, for 39 quarters. The cleanness of the pattern
should have been the tell.

The Phase 1 narrative (Q1–Q40 horizontal differentiation) and the
intra-Phase-2 lifecycle events (entries, M&A, defaults, leapfrogs) are
unaffected by this bug. The Phase 2 absorbing-state interpretation is.

---

## How I tracked it down

Step-by-step, what convinced me this was a bug rather than coordinated
behavior:

1. **The pattern was too clean.** Six firms with `actual_production = 0`,
   `actual_price = $0`, `actual_sga_spend = $0`, `actual_rd_spend = $10M`
   for 39 consecutive quarters. Six different LLMs (mistral, qwen, gemini,
   glm, gemma) producing identical zeros to four decimal places is not a
   plausible coordination failure.

2. **The R&D figure pinned at $10M.** That's the simulation's mandatory
   Phase 3 R&D floor. When a firm sets R&D = 0, the clamper raises it to
   $10M. So the underlying LLM-returned R&D was zero, and the floor
   produced the visible $10M.

3. **`actual_price = $0` is impossible from a real firm decision.** Even
   a panicked LLM running an explicit "halt operations" reasoning would
   not set price to literally zero — it would set it to a low positive
   number. The combination of zero production and zero price suggests
   the decision wasn't made at all; rather, the entire `RawDecisions`
   struct was constructed with default field values.

4. **Verifying via `decision_source` field.** Every Compustat row carries a
   provenance field stamped by the orchestrator: `"llm"` for genuine LLM
   decisions, `"fallback"` for carry-forward fallback, `"fallback"` with
   a `fallback_reason` for exception-handler fallback. Reading the Q42
   compustat rows directly:

   ```
   firm_2:  source=fallback  reason=firm_agent_fn raised: TypeError: unsupported operand type(s) for /: 'str' and 'f...
   firm_3:  source=fallback  reason=firm_agent_fn raised: TypeError: unsupported operand type(s) for /: 'str' and 'f...
   firm_7:  source=fallback  reason=firm_agent_fn raised: TypeError: unsupported operand type(s) for /: 'str' and 'f...
   firm_9:  source=llm       reason=
   firm_10: source=fallback  reason=firm_agent_fn raised: TypeError: unsupported operand type(s) for /: 'str' and 'f...
   firm_11: source=fallback  reason=firm_agent_fn raised: TypeError: unsupported operand type(s) for /: 'str' and 'f...
   firm_12: source=fallback  reason=firm_agent_fn raised: TypeError: unsupported operand type(s) for /: 'str' and 'f...
   ```

   Six firms hit the exception fallback; firm_9 alone made a real LLM
   decision. The provenance field was telling us this from Q42 onward —
   we just weren't reading it during the live monitoring.

---

## The bug, exactly

In `src/orchestrator.py`, the parallel firm-decision pool catches
exceptions from `firm_agent_fn` and substitutes a fallback `RawDecisions`
that is built **only with provenance fields** — `decision_source`,
`fallback_reason`, `proposal_id`. Every other field falls back to the
dataclass default:

```python
# src/orchestrator.py:917-928 (parallel pool exception handler)
try:
    raw_decisions[fid] = fut.result()
except Exception as e:
    _log(state, f"  {fid}: firm_agent_fn FAILED: {e}")
    import uuid as _u
    raw_decisions[fid] = RawDecisions(
        decision_source="fallback",
        fallback_reason=f"firm_agent_fn raised: {type(e).__name__}: {str(e)[:200]}",
        proposal_id=str(_u.uuid4()),
    )
```

And the dataclass defaults in `src/types.py:407-414`:

```python
@dataclass(frozen=True)
class RawDecisions:
    price: float = 0.0
    production: int = 0
    capex: float = 0.0
    rd_spend: float = 0.0
    rd_allocation: dict[str, float] = field(default_factory=lambda: {...})
    sga_spend: float = 0.0
    ...
```

So when an exception fires, the firm gets `price=0.0, production=0,
rd_spend=0.0, sga_spend=0.0`. The clamper then bumps R&D to its
mandatory floor and lets the other zeros through. From the env's
perspective, the firm "decided" to halt operations entirely.

Compare with the cli.py firm_agent's *non-exception* fallback for
when `complete_json` returns None (i.e., the LLM returned unparseable
JSON but didn't crash):

```python
# src/cli.py:200-230 — carry-forward fallback when LLM returns None
if result is None:
    print(f"  [{firm_id}] LLM failed, using carry-forward fallback")
    return RawDecisions(
        price=carried_price,                     # from prior Q sales / units
        production=min(carried_production, ...), # from prior Q units sold
        rd_spend=carried_rd,                     # from prior Q
        sga_spend=carried_sga,                   # from prior Q
        ...,
        decision_source="fallback",
        fallback_reason="LLM returned None (after retries); carry-forward from prior Q",
    )
```

This carry-forward fallback is the **right design**. It preserves
continuity by carrying forward the firm's prior-quarter behavior. If the
exception handler in `orchestrator.py` had used this instead of
dataclass defaults, the six firms in ν+6 would have continued
producing at their prior-quarter levels, and Phase 2 would have looked
completely different.

The bug is that **two different fallback paths exist and only one is
sensible.** When the LLM returns `None`, carry-forward fires. When
firm_agent_fn raises any other exception (TypeError, RuntimeError from
rate limits, ConnectionError from network, etc.), the broken-default
path fires. There's no architectural reason for the divergence.

---

## What was the underlying TypeError?

The fallback_reason field truncates at 200 characters, so we get
`TypeError: unsupported operand type(s) for /: 'str' and 'f...` —
likely `'float'`. Some division operation in the firm_agent pipeline
was mixing a string and a float.

I haven't pinpointed the exact line yet. Likely candidates: the
board discussion / data broker / memory system fed back a string-typed
value where a float was expected, and a downstream arithmetic operation
crashed. The fact that it started at Q42 and persisted suggests
something about the post-firm_6-default state (or the post-auction-phase
state) put a string into a numeric slot for these firms.

The exact location matters for cleaning up the bug at its source, but
not for the orchestrator-side fix: even after we trace the TypeError,
the orchestrator's exception handler should still use carry-forward as
a defense-in-depth.

---

## The fix

**One change to `src/orchestrator.py`.** Replace the broken-default
`RawDecisions` construction in the parallel-pool exception handler
with a carry-forward fallback. Sketch:

```python
except Exception as e:
    _log(state, f"  {fid}: firm_agent_fn FAILED: {e}")
    import uuid as _u
    # Carry forward prior-quarter decisions instead of zeroing.
    prior_flows = state.last_quarter_flows.get(fid) if state.last_quarter_flows else None
    firm = state.firms[fid]
    raw_decisions[fid] = _carry_forward_decisions(
        firm, prior_flows,
        decision_source="fallback",
        fallback_reason=f"firm_agent_fn raised: {type(e).__name__}: {str(e)[:200]}",
        proposal_id=str(_u.uuid4()),
    )
```

Where `_carry_forward_decisions` is the same logic as the cli.py path
(extracted into a shared helper). It should:

- Pull prior-quarter price (= prior net_sales / prior units_sold)
- Pull prior-quarter production (= prior units_sold, capped at capacity)
- Pull prior-quarter R&D and SGA
- Use sensible non-zero defaults if no prior quarter exists yet (e.g., Q1)

This preserves continuity through any LLM glitch, and if the same
TypeError keeps firing every quarter, the firm just keeps producing
at its prior-quarter level. The economic dynamics stay alive even when
the LLM call doesn't.

---

## What this means for the ν+6 dataset

Phase 1 (Q1–Q40) is unaffected. All firms made successful LLM
decisions through Q41. The horizontal-differentiation equilibrium
documented in the research overview paper is real.

Phase 2 (Q42–Q80) is contaminated by the bug. Six firms had their
decisions silently replaced with dataclass-default zeros for 39
quarters. The "absorbing monopoly" that emerged is not economic
dynamics — it's the env correctly allocating all demand to the only
firm whose LLM kept working. The paper's framing of Phase 2 as
Cooper-John coordination failure / Diamond-Dybvig retreat / focal-point
selection is wrong.

The lifecycle events that occurred during Phase 2 (defaults of
firm_5/6/8/10/11, leapfrog spawns of firm_13/14/15/16, M&A inactivity,
PE refusal to fund leapfrogs) all happened — but they happened in a
contaminated industry where six of seven firms were fictionally idle.
We can't draw clean conclusions about VC dry-powder behavior or
entry deterrence from this data because the "perceived monopoly"
the PE was responding to was a simulation artifact.

The research overview paper needs:
- Phase 1 section: keep mostly as-is (real horizontal differentiation).
- Phase 2 section: rewrite to acknowledge the contamination.
- Synthesis table: many of the Phase 2 mappings to literature need to
  be downgraded or removed.
- Anomalies section: most of these (cash-rich non-response, no M&A,
  no Schumpeterian destruction) are explained by the bug, not by
  novel LLM coordination dynamics.

This is unfortunate for the paper but good for the simulation. The
real research finding is that **silent exception handlers in
multi-agent LLM systems can produce data that looks like sophisticated
emergent behavior but is actually orchestrator artifacts**. That's a
methodological lesson for everyone running these kinds of simulations.

---

## Reconsidering the proposed ν+7 interventions

In the prior draft of this document I proposed seven prompt-side
interventions to dissolve the absorbing state. With the corrected
diagnosis, most of them are unnecessary:

| # | Intervention | Status |
|---|---|---|
| 0 | Firm continuity-of-operations bias | **Drop.** The carry-forward fallback fix is the structural answer. Adding language to the prompt asking firms not to halt is treating a symptom of a non-existent disease. |
| 1 | Niche-resolved demand calibration | **Keep.** Independent of the bug — still a genuine modeling improvement when regional markets are on. |
| 2 | Env narrative refresh | **Drop.** The env wasn't anchoring on a self-fulfilling narrative. It was correctly routing demand to the only producer. |
| 3 | PE counterfactual-demand framing | **Keep but soften.** Real PE behavior under perceived monopoly is risk-averse; ν+6 captured that correctly. The framing change is a modeling enrichment, not a fix. |
| 4 | M&A bargain-hunting language | **Keep.** Independent of the bug — M&A in real life does target idle solvent firms, and the prompt was missing the framing. |
| 5 | Activist remit expansion | **Keep.** Independent of the bug — solvent-but-idle firms are real activist targets. |
| 6 | Production-restart costs (toggle) | **Drop.** Was motivated by the absorbing state. Without the absorbing state, this isn't urgent. |
| 7 | SEC antitrust (toggle) | **Keep optionally.** Independent modeling choice, but not high priority. |

Net interventions for ν+7: items 1, 4, 5, and (optionally) 7. Plus the
bug fix.

---

## Recommended order

1. **Bug fix first** (`src/orchestrator.py` carry-forward fallback in
   parallel-pool exception handler). Add unit test that injects a
   raised exception in `firm_agent_fn` and asserts the resulting
   `RawDecisions` has nonzero carry-forward values.
2. **Pinpoint and fix the TypeError** in firm_agent. Likely worth a
   dedicated investigation pass — the exact failing line tells us
   something about the data plumbing in our prompt pipeline.
3. **Re-run the ν+6 scenario** with the bug fix and unchanged
   prompts. See whether Phase 2 still produces an absorbing state.
   That's the genuine test of whether ν+6 design has a remaining
   problem.
4. If Phase 2 *still* collapses post-fix: layer in interventions 1,
   4, 5 (niche demand, M&A bargain-hunting, activist expansion).
5. If Phase 2 *doesn't* collapse: we have ν+6 working correctly and
   can publish a corrected version of the research overview.

The corrected dataset from step 3 is the one worth analyzing as
research material. The current ν+6 dataset documents a bug, which
is interesting in its own right but is a different paper than the
one we drafted.
