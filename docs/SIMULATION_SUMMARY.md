# LLM Firm Lab: Simulation Summary

*Current as of Wave θ+ (April 2026). See [[../CHANGELOG]] for wave history,
[[architecture]] for layered design, [[principles_review]] for the
20-principle scorecard, [[datasets]] for the output-file reference, and
[[ROADMAP]] for next candidates.*

## What This Is

A multi-agent corporate-finance simulation where LLM-powered firms,
auditors, analysts, SEC, activists, bankers, and board governance interact
inside a GAAP-accurate product-market world. Every decision — pricing,
R&D investment, financing, audit opinion, CEO comp, M&A bid, covenant
waiver — is a structured LLM action, adjudicated by the engine, recorded
with full provenance.

**Scale**: ~8,500 LoC · ~55 modules · **303 tests passing** · scorecard
19🟢 / 1🟡 against the 20 CLAUDE Industry Simulation Principles
(Codex independently confirmed 28/33 specific claims). As of Wave λ,
the simulation models the full corporate lifecycle: firms start
private with founder seed, raise 4-5 private rounds from a PE fund
pool, and IPO when ready (writing a full S-1 prospectus).

## Agents (all default-toggleable)

| Agent class | Count | Model role | When |
|-------------|-------|------------|------|
| **Firm board + decision** | N firms | per-firm roster | Every Q |
| **Environment** | 1 | `environment` | Every Q (omniscient) |
| **Equity market** | 1 | `equity_market` | Every Q |
| **Investment bank** | 1 | `investment_bank` | Every Q |
| **Commercial bank** | 1 | `commercial_bank` | Every Q |
| **Earnings announcement** | per firm | firm's own | Every Q |
| **Sell-side analyst** | 3 staggered | `analyst_1/2/3` | Every Q |
| **Activist** | 1 | `equity_market` fallback | Every Q |
| **SEC** | 1 | `sec` | Every Q |
| **M&A bidder / target / raise** | per firm | firm's own | Every Q (if ma_enabled) |
| **Auditor pool** | 4 named | `auditor_1..4` | Annual Q4 |
| **Board governance** | 1 (or 3-voice committee) | `board_governance` | Annual Q4 |
| **Annual report writer** | per firm | firm's own | Annual Q4 |
| **Emergency bridge lender** | 1 | reuses commercial_bank | Settlement phase |
| **Covenant violation resolver** | 1 | reuses commercial_bank | Phase 7.7 |
| **Environment verifier** | 1 | `env_verifier` | On anomaly trigger |
| **Data broker** | 1 | `data_broker` | Per agent query |
| **Data analyst** | 1 | `data_analyst` | On board-request |

When `three_llm_board_enabled` is on, the board-governance call expands
to **4 LLM calls** (CEO-voice / CFO-voice / comp-committee-voice +
synthesis). Otherwise it's 1 call.

Every LLM call is tagged with its `agent_role` via `telemetry.set_role`
and accumulated to `llm_calls.jsonl` + `cost_summary.txt` (per-model
and per-agent-role token + $ USD breakdown).

## Quarter Flow (~20 phases)

```
EVERY QUARTER:
  1.  Macro advance (deterministic; mean-reverting shocks)
  2.  IPO (scenario-aware)
  3.  M&A bidding + auction (if ma_enabled; LLM raises multi-round)
  4.  SEC surveillance
  5.  Activist campaign (LLM picks target, round-2 reaction)
  6.  Firm decisions (parallel across firms; board discussion + action JSON)
  7.  Clamping (adjudication; structured RejectionEvents)
  8.  Accounting (GAAP BS/IS/CFS; manipulation injected)
  9.  Debt amortization (interest + principal per facility)
 10.  Earnings announcement (parallel per firm)
 11.  Sell-side analyst notes (parallel across 3 analysts)
 12.  Equity market pricing
 13.  Convertible bond conversion (if ITM)
 14.  CEO vesting / selling / option exercise
 15.  Investment bank (debt + equity requests)
 16.  Commercial bank (revolver terms)
 17.  Provisional Compustat row
 18.  Covenant testing + violation resolution (waive / amend / accelerate)
 19.  SEC enforcement (resolves pending AAERs → restatements)
 20.  Delisting check (price < threshold N quarters)
 21.  Settlement + emergency bridge loans / default
 22.  End-of-Q refresh (Compustat row = final state)
 23.  Director lifecycle (default departures every Q; Q4 refresh)

ANNUAL (Q4):
 A1.  Auditor opinion (parallel pool of 4) + LLM fee haggle
 A1.5 Annual reports (parallel per firm, 10-K style)
 A1.7 ExecuComp outstanding-equity snapshot
 A2.  Board governance (1-LLM or 3-LLM committee; CEO review + comp)

END OF Q:
 24.  WorldState snapshot to outputs/<run>/snapshots/Q{N}.pkl
```

See [[architecture]] for the full layered view and design choices.

## Information Architecture

Enforced at source in `_build_firm_info_package(state, target_firm_id)`.

```
PUBLIC (all firms see):
  - Competitor prices, market shares, generation, equity prices
  - Published revenue, total R&D spend
  - Industry gazette, macro state
  - Analyst consensus (aggregated across analysts)

PRIVATE (only own firm + environment):
  - Cash, assets, liabilities, unit cost
  - R&D allocation (product/process/delivery)
  - Capability stock, brand stock
  - R&D/brand operational reports
  - Board minutes, forecasts
  - CEO holdings (grants vested/unvested, sold-to-date)

NOISY-PUBLIC (if noisy_signals_enabled):
  - Peer prices/revenues observed with mean-zero Gaussian noise
  - SD divided by (1 + n_shared_directors) when directors_enabled
    → interlocking directorship info leak (confirmed hypothesis, Spec 12)

UNOBSERVED (environment only):
  - World secrets (hidden research paths, firm factors)
  - Taste shocks, demand model parameters
  - All firms' private data simultaneously
  - Firm manipulation truth (until SEC/auditor detects)
```

## Structured actions + audit trails

Every mutation flows through: **Agent → `Action(payload)` → Engine
adjudication → `ActionResult` → `ActionLog`**. All 10 agent classes
migrated to this spine.

### Audit-trail files per run

| File | Row unit | Purpose |
|------|----------|---------|
| `proposals.jsonl` | Action + ActionResult | Every structured decision w/ `actor_class` |
| `negotiations.jsonl` | Completed negotiation | 5 bargaining topics: debt_pricing, covenant_waiver, audit_fee, activist_campaign, ma_auction |
| `bs_violations.jsonl` | BS identity drift | Empty on clean runs |
| `broker_queries.jsonl` | Data broker query | WRDS-style queries by agents |
| `peer_observations.jsonl` | Per observation event | Interlock + noise applied at observation time |
| `llm_calls.jsonl` | Per LLM API call | Tokens + latency + role + model |

Every `compustat_q.csv` row carries a `proposal_id` that keys into
`proposals.jsonl` — the full "why is this row what it is" chain is
traceable to the LLM's structured action + prose justification.

## Features (all user-toggleable)

See [[../README]] or the `RunConfig` dataclass in `src/config.py` for the
full list with defaults. Highlights:

- `earnings_management_enabled` — firms can manipulate reported earnings
- `sec_enabled` — SEC surveillance + AAERs + enforcement
- `auditor_enabled` + `three_llm_board_enabled` — 4-firm pool + optional
  3-voice committee (CEO / CFO / comp) + synthesis
- `sellside_analysts_enabled` — 3 staggered analysts
- `ma_enabled` — M&A bidding + multi-round raise + goodwill accounting
- `debt_covenants_enabled` — DealScan-style covenant tracking
- `noisy_signals_enabled` — firms see peers with Gaussian noise
- `directors_enabled` — shared director pool w/ interlocking seats
- `director_lifecycle_enabled` — annual refresh + default departures
- `scenario` — `biotech_early_stage` | `mature_industry` | `distressed`
- `cost_telemetry_enabled` — $ cost via OpenRouter pricing API

## Scenarios (heterogeneous founding conditions)

| Scenario | Profile |
|----------|---------|
| `biotech_early_stage` | High burn, $200M+ cash, no revenue yet |
| `mature_industry` | Established, steady margins, modest growth |
| `distressed` | Leveraged, thin cash, covenant-heavy |

Default (no scenario) = uniform IPO at $17.50 × 10M shares per firm.

## Scoring + Research

Per-run scorecard:
- **Firms**: Equity NPV (dilution-adjusted) + IRR from IPO-shareholder POV
- **Debt**: total interest + principal recovered - total loaned; loss rate
- **Equity pricing**: RMSE + MAPE vs next-Q actual
- **12 regression specs**: pay-performance, leverage determinants,
  covenant→default, CEO turnover, EM detection, analyst bias, SEC/
  restatement/turnover event studies, matched-firm pricing,
  disclosure tone, **interlock → observation accuracy (significant)**.

Cross-run accumulation:
- `data/compustat_all.csv` — stacked quarterly panel
- `data/compustat_a_all.csv` — annual funda panel
- `data/run_index.csv` — one row per run w/ summary stats
- `data/scores.csv` — scorecard per run

## Reproducibility

- **Mock runs** are byte-reproducible with the same seed (see
  `tests/test_reproducibility.py`).
- **Live runs** are NOT reproducible across LLM calls (backend
  randomness), but full structured-action + state history is
  snapshotted every quarter for forensic replay.
- `--restart-from outputs/<run>/snapshots/Q{N}.pkl` resumes from any
  quarter.

## Standing Design Rules

1. **All decisions emergent.** No hardcoded numbers for agent behavior
   (thresholds, rates, fees = LLM judgment). Structural bounds OK.
2. **Information boundaries enforced at source.** Each agent receives
   only data it's allowed to see. Env agent is the only omniscient one.
3. **Structured Actions only.** Every mutation flows through the Action
   spine; every clamp produces a `RejectionEvent`.
4. **Accounting math stays in code.** LLMs never mutate balances.
5. **Identities asserted every phase.** BS drift is a bug, not noise.
6. **Toggles default OFF.** Backward compatibility preserved.
7. **Every LLM call is tagged** with its agent_role for cost attribution.

## Where to look first

| Question | File |
|---|---|
| "How does the firm LLM decide?" | `prompts.py::build_firm_prompt`, `cli.py::make_firm_agent` |
| "What determines market share?" | `prompts.py::build_environment_prompt` + env agent |
| "Why did firm X default?" | `outputs/<run>/firms/<fid>/board_minutes_Q*.md` + `quarter_log` |
| "How is BS identity enforced?" | `accounting.py::post_quarter` + `orchestrator._check_bs_invariants` |
| "Where does the interlock info leak?" | `orchestrator._build_firm_info_package` + `_count_shared_directors` |
| "How do I trace a decision?" | `proposals.jsonl` by `proposal_id` |
| "How do I add an agent?" | `types.py` dataclass + factory in `src/{agent}.py` + wiring in `cli.py` + `tag_backend(role)` |
