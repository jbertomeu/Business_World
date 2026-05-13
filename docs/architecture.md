# Current Architecture

Snapshot of the LLM Firm Lab's architecture as of Wave ζ / η. Stitches
together what Waves α–η built, why, and how the pieces fit. Read this
alongside `principles_review.md` (principle-by-principle scorecard) and
`datasets.md` (output-file reference).

---

## Layered view

```
┌─────────────────────────────────────────────────────────────────┐
│  WORLD / ENGINE LAYER                                            │
│  - WorldState (canonical, serializable, pickleable)              │
│  - orchestrator.run_quarter() — phase pipeline                   │
│  - accounting.post_quarter() — BS/IS/CFS integrity               │
│  - engine.Action / ActionResult / ActionLog (structured actions) │
│  - negotiation.Negotiation / Offer / Round (bargaining)          │
│  - snapshots.snapshot_world / restore_world (reproducibility)    │
└─────────────────────────────────────────────────────────────────┘
                              ▲
                              │ actions
                              │
┌─────────────────────────────────────────────────────────────────┐
│  AGENT LAYER                                                     │
│  Firm decisions      firm_agent (cli.make_firm_agent)            │
│  Market resolution   env_agent                                   │
│  Equity pricing      equity_market                               │
│  Debt underwriting   investment_bank                             │
│  Revolver            commercial_bank                             │
│  Earnings release    earnings_announcement                       │
│  Sell-side notes     analyst_1/2/3                               │
│  Activist            activist_1 (round-0 + LLM round-2)          │
│  Auditor (4 pool)    auditor_1..4 + fee-haggle                   │
│  SEC surveillance    sec                                         │
│  Board governance    board_governance (Q4 only)                  │
│  M&A bidding         per-firm backends with raise-round          │
│  Annual report       per-firm backends (Q4)                      │
│                                                                  │
│  All agents read from WorldState; mutations flow back through    │
│  Action → adjudication → ActionResult → action_log.              │
└─────────────────────────────────────────────────────────────────┘
                              ▲
                              │
┌─────────────────────────────────────────────────────────────────┐
│  DATA LAYER                                                      │
│  - 21 WRDS-style CSVs                                            │
│  - 4 JSONL audit trails (proposals, negotiations, bs_violations, │
│    broker_queries)                                               │
│  - Per-quarter pickle snapshots                                  │
│  - crosswalk.csv (entity linkage)                                │
└─────────────────────────────────────────────────────────────────┘
```

---

## Quarterly phase pipeline

Roughly in order of execution inside `run_quarter()`:

1. **Phase 1** — advance macro, draw shocks (mean-reverting)
2. **Phase 2** — IPO any pre-IPO firms (scenario-aware)
3. **Phase 3** — M&A bidding (if `ma_enabled`):
   - Round 0: each firm's LLM proposes at most one bid
   - Round 1: if contested target, losing bidders get LLM prompt to raise/drop
   - Target board accepts highest final bid (or hostile override at >150% of price)
4. **Phase 4** — SEC surveillance (LLM decides investigate / subpoena / aaer / none)
5. **Phase 4.5** — Activist campaign (LLM picks target, demand type, stake)
6. **Phase 5** — Firm decisions (parallel LLM calls, one per firm):
   - Each firm sees: public competitors, own private, macro, gazette, activist campaigns, analyst consensus
   - Proposals wrapped as `Action` → clamping as adjudication → `ActionResult`
   - Activist responses written back to campaigns; LLM-driven round-2 reaction follows
7. **Phase 5.7** — CEO cash/stock comp accrual (Stage 11)
8. **Phase 6** — Accounting (post flows, BS/IS/CFS)
9. **Phase 6.5** — Debt facility amortization (interest + principal)
10. **Phase 9** — Earnings announcement (parallel per firm)
11. **Phase 10** — Sell-side analyst notes (parallel across 3 analysts)
12. **Phase 11** — Equity market pricing
13. **Phase 11.5** — Convertible bond conversion (if in-the-money)
14. **Phase 11.6** — CEO vesting / selling / option exercise
15. **Phase 7b** — Investment bank evaluates debt + equity requests
16. **Phase 7c** — Commercial bank sets revolver terms
17. **Phase 7d** — Provisional Compustat row
18. **Phase 7.5–7.7** — Covenant testing + violation resolution (waive / amend / accelerate)
19. **Phase 14** — SEC enforcement (resolves pending AAERs, triggers restatements)
20. **Phase 14b** — Delisting default (price below threshold N quarters)
21. **Phase 15** — Settlement + bridge loans / default
22. **Refresh** — Compustat row reflects final end-of-Q state
23. **Annual (Q4 only)**:
    - A1: Auditor opinion (parallel) + LLM fee haggle
    - A1.5: Annual reports (parallel, 10-K style)
    - A1.7: ExecuComp outstanding-equity snapshot
    - A2: Board governance review (parallel per firm, 3-perspective reasoning)
24. **Snapshot** to `outputs/<run>/snapshots/Q{N}.pkl`

---

## Principle coverage

See `principles_review.md` for the detailed scorecard. As of Wave ζ + η:

| # | Principle | Status |
|---|-----------|--------|
| 1 | Canonical world state | 🟢 |
| 2 | Modular architecture | 🟢 |
| 3 | Emergent behavior / explicit institutions | 🟡 (labeled fallbacks) |
| 4 | Structured actions only | 🟢 |
| 5 | Validation / adjudication / consequence | 🟢 |
| 6 | Correct bookkeeping | 🟢 (instrumented) |
| 7 | Info partitions | 🟢 |
| 8 | Persistent memory | 🟢 |
| 9 | Shared markets | 🟢 |
| 10 | Protocolized bargaining | 🟢 (5 sites LLM-driven) |
| 11 | Temporal discipline | 🟢 |
| 12 | Rich but bounded context | 🟢 (measured: 1.8k tok board, 11% of phi-4 16k ctx) |
| 13 | Quantitative reasoning | 🟢 |
| 14 | Research-grade data | 🟢 |
| 15 | Persistent identifiers | 🟢 (crosswalk) |
| 16 | Reproducibility + audit trail | 🟢 (snapshots + JSONLs) |
| 17 | Latent / signal / report | 🟢 (noise + consensus + EWMA) |
| 18 | Coherent scenarios | 🟢 (3-scenario library) |
| 19 | Modular role-to-model | 🟢 |
| 20 | Usable control layer | 🟢 (15-tab dashboard) |

**19 green / 1 yellow / 0 red.**

---

## Key design choices

### 1. Canonical state via pickleable WorldState
Every mutation flows through `WorldState.firms[fid] = firm.evolve(...)` (frozen
dataclass). Snapshots pickle the full state including RNG, so any quarter can
be resumed perfectly with `--restart-from`.

### 2. Structured Action spine
All agents output JSON that's parsed into a typed `Action(actor_id, action_type,
payload, quarter, proposal_id, justification, source)`. Adjudication (clamping,
env overrides, auctions) returns `ActionResult` with structured `RejectionEvent`s.
Every (Action, ActionResult) pair is logged to `proposals.jsonl`. Every
`compustat_q` row carries a `proposal_id` FK to the action that produced it.

### 3. Multi-round bargaining via Negotiation
`Negotiation(topic, party_a, party_b, rounds, outside_option, outcome,
final_offer)`. Sites that use it:
- `covenant_waiver`: borrower ↔ commercial bank (1-round today; schema supports more)
- `debt_pricing`: firm ↔ investment bank (1-round)
- `audit_fee`: firm CFO ↔ auditor (LLM-driven, up to 2 rounds)
- `activist_campaign`: activist ↔ target firm (LLM-driven 2-round)
- `ma_auction`: multiple bidders ↔ target (LLM-driven raise round; up to N bidders)

### 4. Belief + signal separation
- `noisy_signals_enabled` gates whether firms observe peers / macro with noise.
- Per-observer RNG seed (`hash(quarter, observer, observed)`) makes noise
  reproducible.
- **Interlocking-director info leak (Wave θ)**: observer and observed firms
  sharing `n` directors see peer signals with noise SD divided by `(1+n)`.
  Produces testable prediction: interlocked peer observations have lower
  RMSE vs truth. Mechanism is gated by `noisy_signals_enabled`.
- `FirmBelief` + `ActivistMemory` / `AuditorMemory` / `SECMemory` persist
  across quarters on WorldState (pickled with snapshots).
- Analyst consensus is aggregated into `analyst_consensus` in firm info_package.

### 5. Parallel LLM execution
Phases where agents are independent are run with `ThreadPoolExecutor`:
- Phase 5 firm decisions (parallel per firm)
- Phase 9 earnings announcements (parallel per firm)
- Phase 10 sell-side analysts (parallel across 3 analysts)
- Phase A1 auditors (parallel per firm)
- Phase A1.5 annual reports (parallel per firm)
- Phase A2 governance (parallel per firm)

Config: `parallel_firm_decisions` (default `true`). Gate turns all parallel
execution off for debugging with deterministic ordering.

### 6. Scenario library for heterogeneous industries
`config.scenario: biotech_early_stage` loads per-firm founding cash / shares /
IPO price / PPE / capability / brand / unit cost / CEO salary. Legacy default
(no scenario) preserved bit-for-bit for reproducibility of prior runs.

### 7. Per-phase BS-identity invariants
`_check_bs_invariants()` fires at every mutation-phase boundary. Violations
log to `bs_violations.jsonl` with full BS component snapshot (cash, AR, inv,
PPE, AP, accrued, DTL, pension, legal, etc) and phase label — making root-cause
trivial when drift recurs.

---

## Where to look first for any topic

| Question | File |
|---|---|
| "How does the firm LLM decide what to do?" | `prompts.py::build_firm_prompt`, `cli.py::make_firm_agent` |
| "What determines market share?" | `prompts.py::build_environment_prompt` + env agent |
| "How is an audit generated?" | `auditor.py` + `orchestrator.py` Phase A1 |
| "Why did firm X default?" | `outputs/<run>/firms/<fid>/board_minutes_Q*.md` + `quarter_log` |
| "Where's the BS identity enforced?" | `accounting.py::post_quarter` + `orchestrator._check_bs_invariants` |
| "How do I run a scenario?" | `config/validation_full.yaml` — add `scenario: biotech_early_stage` |
| "How do I read proposals.jsonl?" | `app/dashboard.py` Proposals tab, or `scripts/meta_analysis.py` |
| "How do I add a new entity?" | `types.py` (dataclass) + `orchestrator.py` (instantiate) + `output_organizer.py` (serialize) |

---

## Future work

Per the `principles_review.md` and the most recent session summary:

1. ~~**Principle 3**: Replace deterministic fallbacks.~~ **PARTIAL (Wave θ)**: live-mode LLM-fail fallback now carries forward prior-Q flows. Mock-mode fallbacks remain by-design.
2. ~~**Principle 12**: Measure prompt token counts.~~ **DONE (Wave θ)**: 1.8k board, 1.6k firm, 11% of tightest model context — no split needed.
3. ~~**Director entity**: stub in crosswalk.~~ **DONE (Wave θ)**: shared pool of ~2.5× n_firms directors with interlocking seats (realistic distribution: mean 2.1 seats/director at n=10).
4. **3-LLM board committee**: replace 1-LLM-with-3-perspectives with 3 separate CEO/CFO/comp-committee LLM calls (3× governance cost).
5. **Real-LLM multi-seed scale-out**: 10+ seeds × validation_full for cross-run research panel (~20h wall-clock).

Everything else is either on the principle-green list or bounded research-polish work.
