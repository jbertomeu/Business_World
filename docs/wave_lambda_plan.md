# Wave λ Plan — PE + IPO Lifecycle Refactor

**STATUS: IMPLEMENTED April 22, 2026.** See `CHANGELOG.md` Wave λ
section for what actually shipped. This document retained as
reference for design rationale and potential future extensions
(multi-round-aware scoring refactor, richer PE fund strategy diversity,
sector-specific PE funds from scenario-defined `pe_landscape`).

## Context

The current simulation starts firms post-IPO with a fixed founding cash
amount (e.g. $175M default, $800M in `well_capitalized`). This compresses
the real biotech lifecycle into a single starting condition and assumes
away the whole private-equity / venture-capital arc that real firms
traverse before public listing. The user flagged (see
`CHANGELOG.md` Wave κ note + this session's transcript) that:

1. Real firms start with private funding (seed → Series A → B → C) before
   ever becoming public.
2. IPO is an *event*, not a starting condition; it should involve a
   formal prospectus and public-market pricing.
3. Pre-IPO there is no "equity price" — instead, the firm's valuation
   is set at the last PE round.
4. Patient capital (PE/VC) with a long investment horizon may be what
   bridges firms to profitability — its absence may be why firms
   die in the simulation.

Wave λ adds the full private → public lifecycle.

## Architectural target

### New lifecycle states on `FirmState`

```python
lifecycle_stage: str = "public"   # legacy default (backward compat)
# Canonical stages:
#   "founded"           - seed stage, pre-Series A
#   "series_a"          - raised Series A, private
#   "series_b"          - raised Series B, private
#   "series_c"          - raised Series C, private
#   "late_stage_private" - multiple private rounds, pre-IPO
#   "going_public"      - prospectus filed, pricing in progress
#   "public"            - post-IPO
last_round_valuation: float = 0.0  # from last private round
last_round_quarter: int = 0
is_public: bool = False
pe_cap_table: dict = field(default_factory=dict)  # pe_fund_id → shares
```

### New `WorldState` fields

```python
pe_funds: dict = field(default_factory=dict)  # pe_fund_id → PEFund state
pe_round_history: list = field(default_factory=list)  # one event per round
prospectus_docs: dict = field(default_factory=dict)  # firm_id → prospectus text
```

### New `PEFund` dataclass

```python
@dataclass
class PEFund:
    fund_id: str                          # "pe_1", ... "pe_K"
    name: str                             # narrative name
    strategy: str                         # "early-stage biotech" | "growth" | "late-stage" | ...
    target_hurdle_rate: float = 0.25      # 25% IRR target (typical VC)
    horizon_years: float = 8              # typical fund life
    available_capital: float = 0.0        # $ left to invest
    portfolio: dict = field(default_factory=dict)  # firm_id → shares
    sector_thesis: str = ""               # narrative pref
```

### New `PERound` event dataclass

```python
@dataclass(frozen=True)
class PERound:
    firm_id: str
    round_type: str                       # "seed" | "series_a" | "series_b" | "series_c" | "pipe"
    round_quarter: int
    pre_money_valuation: float
    post_money_valuation: float
    amount_raised: float
    investors: tuple                      # tuple[str, ...] — pe_fund_ids
    lead_investor: str = ""
    shares_issued: int = 0
    price_per_share: float = 0.0
    sector_context: str = ""
```

## Phase ordering in `run_quarter`

New phases inserted into the quarterly flow:

1. **Phase 1.5 — PE round auction** (if any firm needs capital AND is
   still private). Firms' CFO agents signal capital need via the
   strategic planning process (already in Wave κ). PE funds evaluate
   pitches; if multiple bid, the firm chooses (LLM call). Money +
   shares issued. `PERound` appended to `state.pe_round_history`.

2. **Phase 2a — IPO event** (replaces current Phase 2 for private
   firms). Firm decides whether to IPO based on: cash runway, market
   conditions, board pressure. If YES → writes a prospectus (LLM call
   ~3000 tokens) → public equity market prices it → `lifecycle_stage`
   transitions to "public". Firm's existing equity_price field gets
   populated for the first time.

3. **Phase 11 — Equity Market** (existing) now only runs for firms
   with `is_public=True`.

## New agents (factories in `src/private_equity.py`)

```python
def make_pe_fund_agents(backends: dict[str, LLMBackend], fund_configs: list) -> dict:
    """Per-fund agent that evaluates pitches, bids, and decides follow-on."""

def make_ipo_decision_agent(backend: LLMBackend) -> callable:
    """Firm-side agent that decides whether to IPO this quarter."""

def make_prospectus_agent(backend: LLMBackend) -> callable:
    """Generates the IPO prospectus document (narrative + financials)."""
```

## New datasets

- `pe_rounds.csv` — one row per PE round event (firm, round_type,
  amount, investors, valuation, pre/post-money)
- `pe_portfolio.csv` — snapshot of each PE fund's holdings per quarter
- `prospectus/<firm_id>_IPO.md` — prospectus text for each IPO event

## Config toggles

```python
pe_lifecycle_enabled: bool = False      # master toggle
n_pe_funds: int = 3                      # K = 3-5 reasonable
ipo_threshold_revenue: float = 50_000_000  # guideline, not hard
default_seed_capital: float = 5_000_000  # initial founder equity
```

## Scenario integration

`ScenarioConfig` gains:

```python
pe_landscape: list[dict] = field(default_factory=list)
# Describes the PE funds that will exist in this scenario. Each entry:
#   - fund_id, name, strategy, target_hurdle_rate, horizon_years,
#     initial_capital, sector_thesis
# Scenarios can describe "3 generalist PE funds" or "1 late-stage + 2
# early-stage funds" depending on industry realism.

# The existing `firms` list is REINTERPRETED when pe_lifecycle_enabled:
# instead of being "post-IPO starting conditions", it's the FOUNDERS'
# starting conditions (small cash, idea, zero capacity). PE rounds then
# fund the ramp.
```

## Scoring implications

`scoring.py::compute_firm_score` needs to handle:

1. Multi-round dilution: track share count across all rounds
2. Pre-IPO NPV: compute against last-round valuation instead of market
3. IPO event: record the "founder NPV" and "VC NPV" separately in the
   scorecard — founders typically dilute from 100% → 15-30% post-IPO;
   VCs typically 30-50% of post-IPO cap
4. Post-IPO: behave like current scoring but account for pre-IPO dilution

## Roster additions

`config/model_roster.yaml` gains a `pe_funds` section:

```yaml
pe_funds:
  pe_1:
    model: "qwen/qwen3-235b-a22b-2507"   # long-horizon reasoning
    backend: openrouter
    temperature: 0.25
    strategy: "early-stage biotech"
    horizon_years: 10
  pe_2:
    model: "deepseek/deepseek-v3.2"
    backend: openrouter
    temperature: 0.25
    strategy: "late-stage growth"
    horizon_years: 7
  pe_3:
    model: "mistralai/mistral-small-24b-instruct-2501"
    backend: openrouter
    temperature: 0.30
    strategy: "generalist"
    horizon_years: 8
```

## Cost + time estimates

Per 5-firm × 4Q run:
- 3 PE funds × ~3 rounds/firm over lifecycle × ~3 pitch evaluations = ~45 PE-eval LLM calls
- 5 firms × 1 IPO decision LLM call × some fraction that IPO = ~2-3 calls
- 2-3 prospectus calls (larger, ~3k tokens each)
- Estimated +$0.20-0.40 per run

Per 10-seed × 8Q panel:
- +$2.00-4.00 total (on top of the $0.90-1.00 baseline)

Implementation effort: ~**2-3 days of focused work**.

## Dependencies + ordering

Wave λ depends on Waves ι + κ being stable:
- ι: scenario drives industry character + market params — PE funds need
  this to evaluate opportunities
- κ: strategic plans — PE funds read a firm's plan to decide whether
  to invest; firms cite their plan when pitching

Wave λ should be built BEFORE Wave μ (competitive intel / patents)
because it establishes the lifecycle state machine that patents + exit
events hang off of.

## Task breakdown for execution

1. **λ.1** Add lifecycle dataclasses (`PEFund`, `PERound`, `ProspectusDoc`) + `FirmState` lifecycle fields
2. **λ.2** `src/private_equity.py` — PE fund evaluation prompt + pitch agent
3. **λ.3** PE round auction mechanism in orchestrator (Phase 1.5)
4. **λ.4** IPO decision + prospectus event (Phase 2a)
5. **λ.5** Gate existing equity_market phase on `is_public=True`
6. **λ.6** Scoring refactor (multi-round dilution)
7. **λ.7** Datasets: `pe_rounds.csv`, `pe_portfolio.csv`, `prospectus/*.md`
8. **λ.8** Config toggle + roster section
9. **λ.9** Scenario updates: `well_capitalized` gains `pe_landscape`;
    firms restart as "founded" stage with seed capital only
10. **λ.10** Tests + mock smoke + short live validation

## Success criteria

After Wave λ, running the updated `well_capitalized` scenario with
`pe_lifecycle_enabled=true` should:

- All firms start "founded" with seed capital (~$5M each)
- All firms raise Series A in Q1-Q4 from PE funds (LLM-judged)
- At least one firm reaches Series B by Q8-Q12
- At least one firm IPOs by Q20-Q30
- Prospectus documents are written with realistic projections
- Scorecard distinguishes founder vs PE vs post-IPO NPV

This is a major step toward matching real biotech capital dynamics.
