# LLM Firm Lab — Prompts Audit

**Source data:** Q20 + Q40 prompt logs from `outputs/run_1778161247/prompt_logs/`
captured during the seed-9999 simulation while it was running. Each call
has a system prompt, a user prompt, and a parsed JSON response (or text
when the consumer doesn't expect JSON). 31 distinct prompt classes
appear; 4 of them (firm decision, environment, board governance, sell-side
analysts) account for ~70% of the call volume.

> **Wave ν+11 status (2026-05-09):** This audit was originally written
> against seed-9999 run-1. Wave ν+11 lands a set of prompt + code changes
> driven by the audit's findings (E1–E9). Affected sections carry
> inline ν+11 notes; a consolidated changelog lives in §5.5. The
> originally-flagged §5.4 generation-transition language has now been
> applied to `src/prompts.py::build_environment_prompt` (Gen-2 4-tier
> hierarchy).

This document is for *you to review the prompts and comment on them*.
Read alongside the source files in `src/` — when you flag a concern,
the literal text usually lives in one of:

| File | Contains |
|---|---|
| `src/prompts.py` | Firm decision, environment, board discussion |
| `src/equity_market.py` | Equity panel valuation |
| `src/investment_bank.py` | IB credit + structuring |
| `src/commercial_bank.py` | CB credit + violation resolution |
| `src/sellside_analyst.py` | 4 analyst personalities |
| `src/auditor.py` | Annual audit + fee haggling |
| `src/governance.py` | Board / CEO review |
| `src/sec_agent.py` | SEC surveillance + enforcement |
| `src/activist.py` | Activist campaign |
| `src/ma_agent.py` | M&A bidder + target board + judge |
| `src/distressed_auction.py` | Auction judge + bidder |
| `src/earnings_announcement.py` | Earnings release + Q&A |
| `src/annual_report.py` | 10-K equivalent |
| `src/private_equity.py` | PE pitch, eval, IPO, prospectus |
| `src/strategic_planning.py` | 20-quarter strategic plan |
| `src/demand_calibrator.py` | Industry demand anchor |
| `src/env_verifier.py` | Anomaly clamp on env output |
| `src/entry.py` | Entry judge (per-quarter spawn) |
| `src/data_analyst.py` | Ad-hoc data analysis on board request |

## Conventions used in this doc

- **Shared blocks** that appear in multiple prompts are defined once in
  §3 and referenced as `[BLOCK-A: …]`. When a prompt includes one, this
  doc shows the reference; the literal text is in §3 only.
- **Sample responses** were captured at Q20 or Q40 of the live run.
  Long responses are truncated with `[…]` and a character count.
- **Audit notes** at the end of each section flag specific things you
  may want to comment on.

---

# §1. Architecture: per-quarter prompt flow

Every quarter, the orchestrator (`src/orchestrator.py`) runs through the
following phase sequence. LLM-calling phases are bolded; non-LLM phases
are administrative bookkeeping.

```
Phase 1   Macro advance (deterministic)
Phase 2   IPO underwriting       ← LLM (per IPO-eligible firm)
Phase 3   M&A                     ← LLM (per bidder × target × judge × raise)  if ma_enabled
          Antitrust regulator     ← LLM (after target board accepts)            Wave ν+11 E8 — env-side veto on friendly M&A
Phase 3.5 Chapter-11 emerge/convert (deterministic — TTM trends only)
Phase 4   SEC surveillance        ← LLM (sec_agent)                             if sec_enabled
Phase 4.5 Activist campaigns      ← LLM (activist; once per Q across firms)     if activist_investors_enabled
                                  ← LLM (activist_reaction; per-firm)           when campaigns active
Phase 5   Firm decisions          ← LLM (per active firm; 14 firms × 1 call)    parallel
          Strategic planning      ← LLM (per active firm, every 4Q)             parallel
          Board discussion        ← LLM (per active firm with board minutes)    parallel
          Data-broker queries     ← LLM (per firm that requested data)
          Data-analyst hook       ← LLM (when board emits ANALYSIS_REQUEST)
Phase 4   Feasibility clamp (deterministic)
Phase 5   Market resolution       ← LLM (environment, single call)              ← biggest single prompt
Phase 5.45 Env validator (Wave ν+11 E9) ← LLM (second env; verdict ok|send_back) if env_validator_enabled
                                          ← LLM (env-1 retry once with notes)    only on send_back
Phase 5.5 Env verifier            ← LLM (env_verifier; only on anomaly trigger) if env_verification_enabled
Phase 5.7 CEO comp accrual (deterministic)                                      if stock_comp_enabled
Phase 6   Accounting (deterministic)
Phase 6.5 Debt amortization (deterministic)                                     if debt_covenants_enabled
Phase 7b  Investment bank         ← LLM (PANEL of 2; firms requesting capital)  Wave ν+10
Phase 7c  Commercial bank         ← LLM (PANEL of 2; per active firm)           Wave ν+10
Phase 7d  Provisional Compustat row (deterministic)
Phase 7.5 Covenant testing (deterministic)                                      if debt_covenants_enabled
Phase 7.6 Debt consistency check (deterministic)
Phase 7.7 Covenant violation resolution ← LLM (violation_resolver)              when violations exist
Phase 9   Earnings announcement   ← LLM (per firm; reuses firm backend)         if earnings_announcement_enabled
Phase 10  Sell-side analysts      ← LLM (4 analysts; staggered by fqtr)         if sellside_analysts_enabled
Phase 11  Equity market           ← LLM (PANEL of 3; per active firm)           Wave ν+8
Phase 11.5 Convertible-bond conversion (deterministic)                          if convertible_debt_enabled
Phase 11.6 CEO equity vesting (deterministic)                                   if stock_comp_enabled
Phase 14  SEC enforcement         ← LLM (sec_agent escalation)                  if sec_enabled
Phase 14b Delisting default (deterministic)
Phase 15  Settlement / bankruptcy classification ← Ch7 vs Ch11 deterministic
          AUCTION (Ch7 firms)     ← LLM (auction_judge + auction_bidder × N)    when newly-defaulted Ch7 firms exist
Phase A1  Auditor annual audit    ← LLM (per firm; their assigned auditor)      Q4 only, if auditor_enabled
Phase A1.5 Annual report          ← LLM (per firm; reuses firm backend)         Q4 only, if annual_reports_enabled
Phase A1.7 ExecuComp snapshot (deterministic)
Phase A2  Board governance        ← LLM (annual CEO review per firm)            Q4 only, if governance_enabled
Phase 16  Record-keeping (deterministic)

Other LLM calls outside the per-quarter phases:
- Demand calibrator       ← LLM (start of each quarter, before env)
- Entry judge             ← LLM (per quarter, decides whether to spawn a new firm)
- PE pitch / eval / IPO / prospectus ← LLM (varies by PE lifecycle phase)        if pe_lifecycle_enabled
```

## Cadence summary

| Cadence | Phases |
|---|---|
| Every quarter (always) | 1, 5 (firm), 5 (market), 6, 7d, 11, 16 + macro & demand calibrator & entry judge |
| Every quarter (if toggle) | 3, 4 (SEC), 4.5, 5.5, 6.5, 7b, 7c, 7.5–7.7, 9, 10, 11.5, 11.6, 14, 14b |
| Every 4 quarters (Q4 only) | A1, A1.5, A1.7, A2, plus strategic planning |
| On trigger | violation_resolver (covenant breach), auction (Ch7 default), data_analyst (board request) |

---

# §2. Information boundaries (architectural ground rule)

Each prompt builder receives **only** the slice of state its real-world
counterpart would observe. The contract:

| Agent | Sees public Compustat panel | Sees its own private state | Sees competitors' private state | Sees env's hidden truth (manipulation, etc.) |
|---|---|---|---|---|
| Firm CFO | yes | own | no | no (only own manipulation choice) |
| Environment | yes (all firms) | yes (all firms) | yes | yes (god-mode) |
| Equity panel | yes | no | no | no |
| Investment bank | yes | requesting firm only | no | no |
| Commercial bank | yes | client firm only | no | no |
| Auditor | yes | client firm only | no | partial (env hint passed in) |
| Sell-side analyst | yes | no | no | no |
| Board governance | yes | own firm only | no | no |
| SEC | yes | no (uses public + AAERs) | no | partial (env detection tips) |
| Activist | yes | no | no | no |
| M&A bidder | yes | own firm only | no | no |

These constraints are enforced in code (the prompt builders just don't
include the forbidden fields). The audit below quotes the actual prompts;
if you see a leak, the bug is in the prompt builder.

---

# §3. Shared blocks (defined once; referenced below)

These blocks appear in multiple prompts. Define-once, reference-many.

## BLOCK-A: Industry character (longevity-biotech template)

Renders into firm + env + sell-side-analyst + sometimes board-governance
prompts. Comes from `src/prompts.py::_format_industry_character_block`.

```
Industry: longevity-breakthrough biotech
TAM at maturity: $2000.0B

This is a longevity / senolytic-regenerative-therapy industry. The
underlying science represents a genuine medical breakthrough: Gen 1
products already add 5-8 healthy years on average; Gen 2+ products
extend that to 10-25+ years with far better safety profiles.

Market size at maturity — the BIG picture that should anchor
long-horizon valuation:
  - Once efficacy is proven and therapies become standard-of-care,
    the addressable market is ENORMOUS — on the order of $1-2
    trillion annually at maturity. This is not a niche: it is a
    market as large as global oncology or cardiology combined,
    because every aging person becomes a customer.
  - Willingness to pay is effectively unbounded for proven life
    extension: patients, employers, insurers, and governments all
    find capacity to finance it, because the alternative is worse.
  - Forward-looking capital (PE, VC, public markets) should be
    willing to finance multi-year bridges to get firms to the
    tech-ready state, because the post-ready market is vast.

Near-term demand realities:
  - Addressable population today: hundreds of millions globally.
  - Current WTP: $50K-200K per course.
  - Standard-of-care adoption is inevitable over 10-15 years.
  - Capacity, not demand, is the binding constraint for early years.

Industry dynamics:
  - R&D-intensive: reaching Gen 2 requires large cumulative product R&D
    AND several years of Phase III trials.
  - Brand + trust matter: a safety failure can permanently damage a firm.
  - Capital-hungry: real-world analogs required $1-3B of total capital.

Environmental judgment: calibrate demand to this reality. A
monopolist in year 3 at a fair price should be generating
hundreds of millions in quarterly revenue, not tens of millions.
```

## BLOCK-B: Market signals (forward demand projections)

Renders into firm + sometimes env. Comes from
`src/prompts.py::_format_market_signals_block`.

```
MARKET SIGNALS (estimated at current prices):
- Aware population this quarter: <N>M
- Estimated industry share vs no-treatment: <pct>%
- Industry-wide willing buyers this quarter: ~<N> units (if capacity existed)
- Weighted-average competitor price: $<P>

FORWARD INDUSTRY RAMP (projected at current price + share):
  +4Q:  aware_pop=<N>M, industry_willing_buyers~<N>, industry_revenue~$<X>B/Q
  +8Q:  aware_pop=<N>M, industry_willing_buyers~<N>, industry_revenue~$<X>B/Q
  +12Q: aware_pop=<N>M, industry_willing_buyers~<N>, industry_revenue~$<X>B/Q
  +20Q: aware_pop=<N>M, industry_willing_buyers~<N>, industry_revenue~$<X>B/Q

Interpretation: these are demand signals, not revenue guarantees.
Your actual sales are min(your_production, your_share × industry_willing).
```

## BLOCK-C: Public Compustat panel

Renders into env + analysts + ibank + cbank + activist + sec + auditor +
ma_judge. Per-firm rows of the most recent quarter; sometimes the trailing
4-quarter panel. Standard fields:

```
firm_id  conm     gen  rev_Q   COGS_Q  GP_Q   OpInc_Q  NI_Q   Cash    AR    Inv    PPE    AT     LTD    Eq    Price   MktCap
firm_0   Aeterna  1    $35.0M  $2.5M   $32.5M $-12.0M  $-12M  $890M   $35M  $5M    $215M  $1145M $0M    $1.1B $25.00  $1.1B
firm_1   GenVita  1    $125M   $9.5M   $116M  $+30M    $+30M  $620M   $125M $8M    $200M  $953M  $40M   $890M $76.00  $890M
...
```

The panel is **always public** — it never carries a firm's private
manipulation_amount, retained earnings detail, or covenant package.

## BLOCK-D: Macro state (per-quarter)

Renders into env, ibank, cbank, analysts, governance.

```
MACRO:
  fyear: 2035  fqtr: 4
  risk_free_rate: 0.0125 quarterly (5.0% annualized)
  awareness_rate: 0.42 (industry consumer awareness)
  market_size_baseline: $600M base demand
  market_risk_premium: 0.06
  political_uncertainty: 0.30 (0=stable, 1=crisis)
```

## BLOCK-E: JSON output preamble

Most prompts end with this. The exact shape varies but the template is
always:

```
Output JSON in ```json ... ``` fenced block. Schema:
{
  "<field1>": <type>,
  ...
}
```

Some prompts allow explanatory prose before the JSON; others demand
"output ONLY JSON with no preamble". Each agent's parser tolerates the
fence (`extract_json` strips ```json ... ```).

## BLOCK-F: Information-boundary disclaimers

A handful of prompts add an explicit reminder of what the agent does NOT
see — e.g., the SEC prompt says *"You only see public Compustat data and
detection tips passed by the environment; you do not see firms' private
state."* These are aspirational rather than enforced — the actual
enforcement is in the prompt builder's choice of what to include.

---

# §4. Per-prompt audit

Each entry below shows the agent's purpose, the system prompt (with
shared blocks abstracted), the user prompt skeleton, the expected JSON
response shape, a sample real response from Q20 or Q40 of the seed-9999
run, and audit notes you may want to comment on.

---

## §4.1 Firm Decision (Phase 5)

**Purpose.** The CFO of a public firm makes the quarterly operating + financing decision: production, price, R&D, SG&A, capex, dividends, buybacks, equity raise, debt request.
**Called.** Once per active firm per quarter (parallel pool, up to 16 workers).
**Backend.** Per-firm role tag (e.g., `firm_3`); model varies (qwen, claude, gemma, gpt rotation).
**Source.** `src/prompts.py::build_firm_prompt` + `FIRM_SYSTEM_TEMPLATE`.

### System prompt (≈22,000 chars when fully rendered)

```
You are the CEO of <Company>, a Gen <N> longevity-therapy company.
Make a quarterly operating + financing decision.

[BLOCK-A: Industry character]

CAPABILITY + BRAND PHENOMENA:
[explanation that capability stock decays without R&D, brand without SGA;
 numerical levels described qualitatively]

YOUR FIRM (private — only you see this):
  Capability stock: <N>/100
  Brand stock: <N>/100
  Capacity: <N> units/Q
  Generation: <gen>
  Cash: $<X>M
  Long-term debt: $<X>M
  Cumulative R&D: product=$<X>M  process=$<X>M  delivery=$<X>M
  Recent flows (last 4Q): saleq, COGS, NI, op CF, …

THE MARKET:
  N firms compete. Products are MEANINGFULLY DIFFERENTIATED across firms.
  Each firm's product has its own delivery method, side-effect profile,
  formulation, brand positioning, and physician relationships.

PRICING REFLECTION (think this through whenever you set price):
  1. PRICE TREND ANALYSIS — Look at competitor prices over recent quarters.
  2. RACE-TO-BOTTOM RISK
  3. PROFITABILITY RESTORATION
  4. COMPETITIVE RESPONSE PREDICTION
  5. UNILATERAL SUSTAINABILITY
  6. BANKRUPTCY EXTERNALITIES

[BLOCK-B: Market signals — forward demand projections at firm-specific share]

YOUR DECISIONS (output as JSON):
  - price: treatment course price ($)
  - production: courses to manufacture (max 250)
  - capex: capacity investment ($)
  - rd_spend: total R&D ($)
  - rd_allocation: {"product": 0-1, "process": 0-1, "delivery": 0-1}
  - sga_spend: marketing/sales/overhead ($)
  - equity_issuance_request, debt_request, dividends, buybacks
  - reasoning (2-3 sentences)

CASH-ALLOCATION REFLECTION (whenever your cash position is meaningful):
  Debate three options:
    1. HOLD FOR STRATEGIC OPTIONALITY (with specific scenario)
    2. DEPLOY INTO THE BUSINESS (with specific deployment rationale)
    3. RETURN TO SHAREHOLDERS (buybacks/dividends, with reason)

CONSTRAINTS:
  - Spending ≤ cash + revenue + available credit
  - Production ≤ 250
  - Phase III R&D has a mandatory floor

[BLOCK-D: Macro]

=== MANAGEMENT PHILOSOPHY: <ONE OF: AGGRESSIVE GROWTH | PREMIUM INNOVATOR |
                              VALUE OPERATOR | FAST FOLLOWER | MARKETING POWERHOUSE> ===

[1-2 paragraphs of philosophy describing how this firm's CEO/CFO/COO think]

=== EARNINGS GUIDANCE (if last quarter's guidance is on file) ===
  Last 1Q EPS guidance: $<X>  (actual realized: $<Y>)
  Last 1Y EPS guidance: $<X>
  Provide updated guidance this quarter.

=== STRATEGIC PLAN CONTEXT (from last 20Q strategic plan; updated every 4Q) ===
  Strategy: <prose>
  Milestones (next 4Q): <bullet list>
  Variance vs plan: <revenue/NI/cash plan vs actual>

=== ENV NOTES (what actually happened last quarter, if env moderated your plan) ===
  - <env's narrative of the operational reality>

=== ACTIVIST CAMPAIGNS (any current campaign on you) ===
  Activist <id> launched a <buyback/strategic_review/divestiture> campaign.
  Demand: <text>. You should explicitly address this in your reasoning.

=== INVESTMENT-BANK FEEDBACK (if recent issuance was declined/haircut) ===
  Market discussion: <bank's commentary on credit/equity-market conditions>
  Retry guidance: <bank's suggestion on what would clear>

=== SELL-SIDE ANALYST CONSENSUS (if analysts cover you) ===
  n_analysts = <N>
  target price: mean=$<X>, range $<Y>-$<Z>
  EPS 1Q forecast (mean): $<X>

=== PE PROJECTIONS FROM PEERS (recent funding rounds) ===
  <firm_id> raised <round_type> at $<post-money>M; lead's revenue projection y5: $<X>M

[output JSON in ```json ... ``` block]
```

### Sample response (firm_0, Q20, model: gpt-4o-mini)

```json
{
  "production": 250,
  "price": 80000,
  "capex": 5000000,
  "rd_spend": 25000000,
  "rd_allocation": {"product": 0.7, "process": 0.2, "delivery": 0.1},
  "sga_spend": 12000000,
  "equity_issuance_request": 0,
  "debt_request": 0,
  "dividends_per_share": 0,
  "buyback_target": 0,
  "manipulation_amount": 0,
  "eps_guidance_1q": 0.05,
  "eps_guidance_1y": 0.30,
  "reasoning": "We are operating at maximum capacity and our pricing
  is competitive. We will continue to invest in R&D to advance our product
  generation. Currently we have substantial cash; we choose to HOLD for
  strategic optionality (specifically, the upcoming Gen 2 transition which
  will require significant capacity scaling). We do not have a superior
  use case for buybacks at this time given the binding capacity constraint."
}
```

### Audit notes

1. **Prompt is huge** (~22K chars rendered). The CFO has a lot to read.
   Consider whether to split into a "context" call (give the CFO the
   data) and a "decision" call (ask for the JSON). May reduce noise.
2. **Cash-allocation reflection** language is verbose; the firm
   dutifully writes "We choose to HOLD" almost every quarter — that's
   a real finding, but it suggests the prompt has primed the answer.
   You may want to test alternative phrasings.
   **Wave ν+11 E2 update.** Option 3 ("RETURN TO SHAREHOLDERS") was
   strengthened: it now reads as the right answer when no superior
   business deployment exists, not a fallback to be avoided. No
   numerical thresholds. Will validate behavioral effect on run-3.
3. **Management philosophy** block is a deterministic function of
   firm_id (slot 0 → Aggressive Growth, slot 1 → Premium Innovator,
   etc.). The board / governance prompt does NOT see the philosophy
   string explicitly but does see hint of it in the firm narrative.
   Worth confirming this is the boundary you want.
4. **Activist campaign disclosure** is very explicit ("You should
   explicitly address this in your reasoning"). The firm complies but
   often dismissively. If you want stronger activist responsiveness,
   tighten this language.
   **Wave ν+11 E7 update.** When a campaign on the firm is a
   `proxy_fight`, the firm prompt now carries an extra `proxy_note`
   block reminding the CEO that this is a binding governance event,
   not a letter to ignore. The activist prompt itself was also updated
   (see §4.10).
5. **Investment-bank feedback** is plumbed (Wave ν+10 item 10) and
   firms see the public market discussion + retry guidance. Confirm
   whether the "modify and resubmit" path is producing visible
   resubmissions.
6. **Wave ν+11 E1 — Sustainable spending block.** A new "SUSTAINABLE
   SPENDING (R&D, SG&A, capex)" paragraph was added under FINANCIAL
   REALITY. Soft, qualitative language asking the CFO to consider
   whether current burn is supportable by visible future financing
   — no numerical guidance. Intent: cut down the pattern of firms
   running cash to zero on R&D with no plausible bridge.
7. **Wave ν+11 E5 — Peer trajectory.** The competitor panel rendering
   now carries each peer's trailing 4-quarter revenue and market-share
   history (was: current quarter only). Firms can now see whether a
   peer is rising or falling; combined with the env's stickiness
   block (§4.2 audit note), the simulation should show more
   inertia and less quarter-to-quarter share volatility.

---

## §4.2 Environment (Phase 5: market resolution)

**Purpose.** Allocate quarterly demand across firms. Set realized R&D outcomes (product/process/delivery advance, COGS reduction). Narrate idiosyncratic events. Output detection tips for the SEC.
**Called.** Once per quarter, post-firm-decisions.
**Backend.** `environment` role tag; model `deepseek-v3.2` (temperature 0.40).
**Source.** `src/prompts.py::build_environment_prompt`.

### System prompt (≈28,000 chars rendered — the largest prompt in the simulation)

```
You are the omniscient industry environment for a longevity-therapy market.
You allocate demand, grant R&D outcomes, and narrate events. You are
NOT a firm; you are the referee.

[BLOCK-A: Industry character]

YOUR JOB:

1. UNIT ALLOCATION
   Each firm declared a price + production this quarter. Allocate units
   sold across firms based on:
     - capability stock (quality)
     - brand stock (trust + physician relationships)
     - price (lower wins price-sensitive segment)
     - regional / segment differentiation
     - idiosyncratic match shock
   Total demand should grow with awareness_rate; the cross-section should
   reflect the differentiation profiles you see in YOUR FIRM data below.

2. NARRATIVE EVENTS
   1-2 paragraphs of industry color this quarter. Mention specific firms
   by company name and what's working / failing for them. Mention named
   catalysts (regulatory shift, supply chain, idiosyncratic shock) that
   you must explicitly name.

3. R&D OUTCOMES: process improvements (small COGS reductions) AND generation
   transitions (product_advance: true).

   Generation transitions are guidance-not-exact: cumulative product R&D
   in the neighborhood of $200M is the indicative threshold, but firms
   reach the next generation at different cumulative levels depending on
   R&D quality, team talent, and regulatory luck. Firms moderately past
   threshold may advance; firms far past it should usually advance unless
   something specific is holding them back. Spread advances over time;
   when granting, narrate the specific catalyst (Phase 3 readout,
   regulatory approval, lead-compound milestone).

4. DETECTION TIPS for the SEC (next quarter)
   If you observe earnings management (manipulation_amount field on a
   firm's decision), generate a tip for the SEC with severity score.

5. WRITE-OFFS (rare): if a firm's PPE was destroyed by an event, narrate
   and zero out the asset.

YOUR FIRMS (private state — you are omniscient):
  firm_0:
    is_active: true   gen: 1   capability: 90.0/100   brand: 92.0/100
    capacity: 250     base_unit_cost: $9,500
    cash: $890M       LTD: $0M     ppe: $1145M
    geographic_focus: US Northeast
    patient_segment: advanced-stage
    distribution_channel: hospital systems
    signature_feature: combination dosing
    quarterly_decisions: price=$80K, production=250, rd_spend=$25M, sga=$12M
    cumulative_product_rd: $333M
    cumulative_process_rd: $48M

  firm_1:
    [ditto, all 14 firms]

[BLOCK-D: Macro]

OUTPUT JSON:
{
  "firm_outcomes": {
    "<firm_id>": {
      "units_sold": <int 0-250>,
      "market_share": <0-1>
    }, ...
  },
  "rd_outcomes": [
    {
      "firm_id": "<id>",
      "product_advance": <bool>,
      "process_cogs_reduction_pct": <0-0.05>,
      "delivery_advance": <bool>
    }, ...
  ],
  "events": [<narrative event objects>],
  "narrative": "<2-paragraph industry color piece>",
  "detection_tips": [<{firm_id, severity, signal} for SEC>],
  "total_demand": <int>,
  "write_offs": [<{firm_id, asset_type, amount, reason}>]
}
```

### Sample response (Q20, model: deepseek-v3.2)

```json
{
  "firm_outcomes": {
    "firm_0": {"units_sold": 250, "market_share": 0.21},
    "firm_1": {"units_sold": 1000, "market_share": 0.29},
    "firm_10": {"units_sold": 250, "market_share": 0.07},
    "firm_11": {"units_sold": 250, "market_share": 0.07},
    "firm_2": {"units_sold": 250, "market_share": 0.07},
    "firm_5": {"units_sold": 250, "market_share": 0.07},
    "firm_6": {"units_sold": 250, "market_share": 0.07},
    "firm_7": {"units_sold": 250, "market_share": 0.07},
    "firm_9": {"units_sold": 250, "market_share": 0.07}
  },
  "rd_outcomes": [
    {"firm_id": "firm_0", "product_advance": false, "process_cogs_reduction_pct": 0.010, "delivery_advance": false},
    {"firm_id": "firm_1", "product_advance": false, "process_cogs_reduction_pct": 0.015, "delivery_advance": false},
    [...all firms, all product_advance: false...]
  ],
  "events": [],
  "narrative": "The longevity therapy market continues robust expansion in Q4 2035, with total demand reaching 3,500 treatment courses. GenVita (firm_1) maintains its leadership position, capturing 28.6% of the market with its premium-priced ($125K) but high-quality product targeting early-intervention patients. Despite its premium price, GenVita's strong brand (92/100) and excellent physician relationships in West Coast medical centers secure its dominant share. ...",
  "detection_tips": [],
  "total_demand": 3500
}
```

### Audit notes

1. **THE ENV NEVER GRANTS Gen 2.** Across Q20 and Q40 of seed-9999,
   100% of firms have `product_advance: false`, even when firm_1's
   cumulative R&D reaches $790M (4× the indicative threshold). The
   prompt language ("firms far past it should usually advance") is
   not directive enough to overcome the model's default conservatism.
   **Wave ν+11 update — APPLIED.** The prompt now uses a 4-tier
   directive:
   - `cumulative_rd > 3× threshold AND positive ops 4Q` → MUST grant
     unless a specific blocker is named.
   - `cumulative_rd > 1.5× threshold AND positive ops 4Q` → SHOULD
     grant unless a specific reason exists.
   - `cumulative_rd > 1× threshold` → MAY grant; judgment call.
   - `cumulative_rd < 1× threshold` → SHOULD NOT grant.

   Spread advances over time; narrate the catalyst. The literal
   replacement language is in §5.4 below. Run-3 will validate that
   the env actually advances firms past the 3× tier.
2. **The system prompt dumps every firm's private state** (cumulative
   R&D, geographic focus, signature feature, etc.). This is correct
   for the env (god-mode) but verifies the env is the ONLY agent that
   sees this. If you want a stricter test, ask your reviewer to
   confirm no other prompt (esp. equity panel, sell-side analysts)
   accidentally includes any of these fields.
3. **Detection tips** are emitted only when manipulation_amount > 0
   on a firm. If earnings_management_enabled is False (it's True in
   our run) but firms still aren't manipulating, no tips fire. Worth
   checking the manipulation field is actually populated.
4. **Wave ν+11 E5 — Customer stickiness block.** A new "CUSTOMER
   STICKINESS (read this every quarter)" paragraph was added to the
   env prompt. It tells the env that consumers have switching costs,
   physician relationships are sticky, and prior-quarter market share
   is informative about this-quarter share. Soft, qualitative — no
   numerical pinning. Intent: cut down quarter-to-quarter share
   volatility without killing emergent randomness. Run-3 will
   validate.
5. **Wave ν+11 E4 — Capacity-PPE coupling.** Outside this prompt but
   relevant to env's allocation: `capacity_units` is now recomputed
   from `ppe_gross / params.ppe_per_unit_capacity` (with $100K/unit
   default) inside `accounting.post_quarter`. Firms that bought PPE
   over 80 quarters now have grown capacity, so the env's allocations
   can grow into the $2T TAM rather than getting stuck at the
   structural ~5,000-unit-industry ceiling that priced run-1's
   industry at $2.3B. No prompt change.

---

## §4.2.5 Env Validator (Phase 5.45 — Wave ν+11 E9)

**Purpose.** A *second* environment LLM reads the first env's market
resolution (units, shares, R&D outcomes, narrative) and either ratifies
it or sends it back with notes. On send-back, env-1 retries once with
the notes appended to its user prompt. Cap at one retry.
**Called.** Every quarter when `env_validator_enabled`.
**Backend.** `env_validator` role tag; defaults to qwen3-235B (temp 0.10) — falls back to `environment` model if role not configured.
**Source.** `src/env_verifier.py::ENV_VALIDATOR_SYSTEM_PROMPT + make_env_validator`.

### System prompt (≈2,000 chars)

```
You are an independent environment auditor. Another env agent has just
produced this quarter's market resolution. Your job is to read the
proposal and judge whether it is internally consistent and consistent
with the recent industry trajectory.

You DO NOT rewrite the proposal. You either:
  - "ok": the proposal stands.
  - "send_back": the proposal has a clear flaw. Write notes; env-1
    will regenerate.

KEY POINT — high bar for sending back. Random variation, surprising
moves, catalysts, and unusual quarters are FINE. Only send back when:
  1. Narrative says one thing, numbers say another.
  2. Per-firm shares don't sum within a few % of 100%.
  3. A firm's units_sold materially exceeds its production capacity.
  4. R&D outcomes contradict prior quarters with no narrative cause.
  5. Total demand changed by an order of magnitude with no narrative
     catalyst.

NOT cause to send back: 30-50% demand moves, share shifts, margin
compression, new entrants, or "feels off" subjective judgments.

OUTPUT JSON: {"verdict": "ok"|"send_back", "notes": "..."}
```

### Differences from the Phase-5.5 env_verifier (the older deterministic-anomaly path)

| | Phase 5.5 verifier | Phase 5.45 validator (this section) |
|---|---|---|
| Trigger | Deterministic anomaly heuristic (5x trend, share-sum off, cap violation) | Every quarter (LLM gates) |
| Action on fail | DIRECTLY rewrites numbers | Writes notes, env-1 retries |
| Bar | Quantitative (5x, etc.) | Qualitative; "high bar" enforced in prompt |
| Authority | Verifier becomes ground truth | env-1 retains authority |
| Cost per Q | LLM call only on anomaly | LLM call always; second env LLM call only on send-back |

Both can be enabled simultaneously. They're complementary: the verifier
catches absurd spikes via cheap deterministic checks; the validator
catches narrative-vs-number contradictions via the second-env's
judgment.

### Audit notes

1. **High bar matters.** If the validator becomes too aggressive, it
   sends back too often → env-1 generates a sterile, conservative
   output → emergent randomness dies. The prompt explicitly enumerates
   "NOT cause to send back" examples to push back against this.
2. **One retry only.** Cap is hardcoded in
   `src/orchestrator.py::run_quarter`. If env-1 still produces an
   inconsistency after one retry, it's logged but accepted — the
   simulation never stalls.
3. **Pass-through on error.** Any backend failure or unparsed verdict
   defaults to `ok`, never `send_back`. Validator failures cannot
   block the run.
4. **No revision authority.** Unlike the Phase-5.5 verifier, this
   validator does NOT produce revised numbers. This is deliberate:
   env-1 owns the simulation's narrative + numerical coherence, and
   we want the retry to flow back through env-1's same prompt
   machinery (so the retry sees the same firm panel, the same macro,
   etc.).

---

## §4.3 Equity-Market Panel (Phase 11)

**Purpose.** A 3-LLM panel produces target prices for every active firm; the per-firm median is committed as the marked share price. Wave ν+8 fix.
**Called.** Once per quarter; 3 LLMs run in parallel, each scores all firms in one call.
**Backend.** Three distinct models cycled from firm roster (gemma, dark-nexus, behemoth in our run).
**Source.** `src/equity_market.py::build_equity_prompt + make_equity_market`.

### System prompt (≈2,200 chars)

```
You are one of three independent valuation analysts producing a target
price for each firm in the industry. You should NOT consult the others.

For each firm, you will receive:
  (1) Four-quarter rolling price history (so you can read the trajectory
      rather than anchor on a single prior point).
  (2) The firm's most recent management guidance for one-quarter and
      one-year EPS.
  (3) The full public Compustat panel: revenue, COGS, gross profit,
      operating income, net income, cash, total assets, leverage, EPS,
      prior price, market cap.
  (4) Sell-side analyst consensus and rating, if available.

Your output is a target price per share, a brief justification narrative,
and a tag for the valuation method you used.

When fundamentals deteriorate, mark down. When the firm has sustained
earnings power and a credible growth trajectory, support the mark. Do
not produce price quotes that are physically impossible (negative,
zero, or many orders of magnitude removed from the prior price). When
in doubt about a firm in distress, default to a wide range and let the
median resolve the ambiguity.

OUTPUT JSON:
{
  "firms": [
    {
      "firm_id": "<id>",
      "equity_price": <number, target price per share, $>,
      "valuation_method": "<DCF|comparables|residual_income|asset_floor|...>",
      "reasoning": "<1-3 sentences on the call>"
    }, ...
  ]
}
```

### User prompt (≈5,800 chars)

```
=== Q4 2035 (Quarter 20) — Industry valuation ===

[BLOCK-D: Macro]
[BLOCK-C: Public Compustat panel for all active firms — current quarter row]

ROLLING PRICE HISTORY (4 quarters):
  firm_0: $35.00 → $42.00 → $48.50 → $52.00 (current)
  firm_1: $76.00 → $82.00 → $88.00 → $95.00
  ...

MANAGEMENT GUIDANCE:
  firm_0: 1Q EPS $0.05 / 1Y EPS $0.30
  firm_1: 1Q EPS $0.85 / 1Y EPS $4.00
  ...

ANALYST CONSENSUS:
  firm_0: target=$60.00 (range $50-$72), rating=hold (4 analysts)
  firm_1: target=$110.00 (range $90-$130), rating=buy (4 analysts)
  ...

Provide target prices for all listed firms.
```

### Sample response (Q20, panel member 1, model: gemma-4-26B)

```json
{
  "firms": [
    {"firm_id": "firm_0", "equity_price": 55.00, "valuation_method": "DCF", "reasoning": "Stable revenue trajectory; modest growth; in line with peer multiples."},
    {"firm_id": "firm_1", "equity_price": 105.00, "valuation_method": "comparables", "reasoning": "Industry leader; premium multiple justified by share + brand."},
    [...]
  ]
}
```

### Audit notes

1. The 3-panel-member median is committed (Wave ν+8 H2: quorum check
   added). When ≥2 of 3 fail, the prior price is carried forward.
2. **No private firm data leaks** in the user prompt — confirmed.
3. The valuation_method is free-text; not enforced. Could be tightened
   to a fixed enum if you want stricter cross-panel comparability.

---

## §4.4 Investment Bank (Phase 7b)

**Purpose.** Underwrite term debt + price equity offerings. Wave ν+10: panel of 2 banks; firms pick best terms.
**Called.** Once per quarter; one big call covering ALL firms requesting capital.
**Backend.** Two banks: `investment_bank` (qwen-235B) + `investment_bank_2` (gemma-12B).
**Source.** `src/investment_bank.py::SYSTEM_PROMPT_WITH_COVENANTS + build_ibank_prompt`.

### System prompt (≈6,600 chars)

```
You are an investment bank evaluating term debt applications and equity
offerings for pharmaceutical firms.

Apply professional underwriting discipline. For each firm requesting financing:

TERM DEBT
  Assess ability to repay: cash generation, debt service capacity, asset collateral.
  Price rate to reflect risk. Approve less (or deny) when the credit picture
  doesn't support what the firm wants.

  UNDERWRITING DISCIPLINE:
  Pre-revenue / pre-profit firms should generally NOT receive term debt — they
  should raise equity instead. Term debt requires:
    - Positive operating cash flow that comfortably services interest (interest
      coverage well above 1)
    - Pledgeable collateral: PP&E, inventory, receivables (R&D is NOT good collateral)
    - A reasonable debt-to-equity ratio post-loan
    - Cash runway under the proposed loan that doesn't get materially worse

  Compute and report standard credit ratios for each firm:
  interest coverage, debt-to-equity, debt-to-assets, cash runway with proposed loan.
  State which checks pass and which fail.

  If the firm has no positive cash flow and no pledgeable assets, DECLINE
  the term debt and direct them to equity capital.

EQUITY OFFERINGS
  Consider: dilution, prior capital raises, use of proceeds, share price,
  market conditions. Offering price is typically below market.

REVIEW YOUR OWN TRACK RECORD
  The firm-specific data shows YOUR prior issuance decisions. If you've
  approved multiple raises at falling prices, and the firm is still burning
  cash with no path to profitability, another raise is unlikely to solve
  the problem.

WHEN YOU DECLINE OR HAIRCUT (Wave ν+10 item 10):
  You MUST produce a market_discussion field — 2-3 sentences on credit/
  equity-market conditions. AND a retry_guidance field — 1-2 sentences on
  what would clear next quarter (smaller size, longer maturity, higher
  rate, equity buffer, or delay).

DEBT FACILITY STRUCTURING (when debt_covenants_enabled):
  For each approved term debt:
    - facility_type: "bank_term" | "bond" | "convertible_bond"
    - amortization_type: "bullet" | "amortizing"
    - maturity_quarters: how many quarters
    - covenants: list of {covenant_type, threshold}
      Valid covenant_types: max_debt_to_ebitda, min_interest_coverage,
                             min_cash_balance, min_liquidity, min_net_worth

OUTPUT JSON:
{"firms": [{
  "firm_id": "...",
  "term_debt_approved": <$ or 0>,
  "term_debt_rate_quarterly": <rate>,
  "equity_offering_approved": <$ or 0>,
  "equity_offering_price": <$/share>,
  "debt_reasoning": "<2-3 sentences>",
  "equity_reasoning": "<2-3 sentences>",
  "market_discussion": "<required when declining>",
  "retry_guidance": "<required when declining>",
  "facility_structure": {<facility_type, amortization_type, maturity_quarters, covenants>}
}]}
```

### User prompt (≈7,600 chars)

```
=== Q4 2035 — Investment bank credit committee ===

[BLOCK-C: Public Compustat panel — last 4Q for each active firm]
[BLOCK-D: Macro]

REQUESTED CAPITAL THIS QUARTER:
  firm_2: $20M term debt + $0M equity
  firm_5: $100M term debt
  firm_8: $0M term debt + $50M equity issuance
  ...

YOUR PRIOR DECISIONS ON THESE FIRMS (last 6Q):
  firm_2: Q15 approved $10M term @ 4%/Q; Q18 approved $15M term @ 4.5%/Q
  firm_5: Q12 approved $80M term @ 5%/Q (now $40M outstanding)
  ...
```

### Sample response (Q20, ibank_1, qwen-235B)

```json
{"firms": [
  {
    "firm_id": "firm_2",
    "term_debt_approved": 20000000,
    "term_debt_rate_quarterly": 0.0425,
    "equity_offering_approved": 0,
    "equity_offering_price": 0,
    "debt_reasoning": "Interest coverage 3.8x (passes 2x floor); D/E 0.42 post-loan (passes 1.0 ceiling); $80M PPE provides collateral; runway 7Q post-loan. Approve full request at 17% annual.",
    "equity_reasoning": "No equity request received.",
    "facility_structure": {
      "facility_type": "bank_term",
      "amortization_type": "amortizing",
      "maturity_quarters": 16,
      "covenants": [
        {"covenant_type": "min_interest_coverage", "threshold": 2.0},
        {"covenant_type": "max_debt_to_ebitda", "threshold": 4.0}
      ]
    }
  },
  {
    "firm_id": "firm_5",
    "term_debt_approved": 0,
    "term_debt_rate_quarterly": 0,
    "equity_offering_approved": 0,
    "equity_offering_price": 0,
    "debt_reasoning": "DECLINE. Interest coverage 0.4x (fails); negative operating cash flow; $40M existing term debt; runway 3Q. The credit picture does not support more debt.",
    "equity_reasoning": "If they want capital they should raise equity at current $35 share price.",
    "market_discussion": "Credit markets are receptive to investment-grade biotech but the secondary market for distressed/sub-IG names has tightened 80bp QoQ. Underwriting standards are firm.",
    "retry_guidance": "Resubmit with smaller principal (under $30M), longer maturity (24Q), and equity buffer raised concurrently. Or delay until operating cash flow is positive."
  }
]}
```

### Audit notes

1. **Wave ν+10 multi-bank panel:** the same prompt goes to two banks
   in parallel; the firm picks the cheaper rate (debt) or higher price
   (equity). The two banks' models differ (qwen-235B vs gemma-12B);
   their judgments differ at the margin and that's the point.
2. **Decline+market_discussion+retry_guidance:** the new Wave ν+10 fix
   is wired and the bank produces it. Confirm in the firm prompt that
   the next-quarter resubmissions actually look different.
3. **Wave ν+11 E3 — Death-spiral discipline.** A new "DEATH-SPIRAL
   DISCIPLINE" block was added after "REVIEW YOUR OWN TRACK RECORD".
   Soft, qualitative language: when a firm has had multiple recent
   equity raises at progressively lower prices and is still burning
   cash without a path to profitability, the next raise is unlikely
   to fix the underlying problem — the bank should consider whether
   to decline rather than enable a death spiral. No numerical
   thresholds in the prompt (per design philosophy).
3. **Firm receives bank's PRIOR DECISIONS** — that's the bank's own
   memory ("you approved $10M last Q15"). Useful for continuity.
4. **Covenant package** is bank's choice; the prompt enumerates the
   valid covenant types. The auditor and SEC see violations; the
   firm CFO sees its covenant compliance trajectory in its private state.

---

## §4.5 Commercial Bank (Phase 7c)

**Purpose.** Set revolver commitment + rate per firm. Wave ν+10: panel of 2.
**Called.** Once per quarter; one call per bank covering all firms.
**Backend.** `commercial_bank` (gemma-12B) + `commercial_bank_2` (mistral-24B).
**Source.** `src/commercial_bank.py::SYSTEM_PROMPT + build_cbank_prompt`.

### System prompt (≈2,600 chars)

```
You are a commercial bank's credit committee setting revolving credit
facility (RCF) terms for pharmaceutical firms.

For each firm:
  - revolver_commitment: maximum borrowable ($)
  - revolver_rate_quarterly: rate (decimal, applied to drawn balance)
  - risk_assessment: low | medium | high
  - reasoning: 2-3 sentences

UNDERWRITING DISCIPLINE:
  - Healthy operating profile (positive operating cash flow, growing revenue,
    low leverage): generous facility (10-30% of revenue), low rate (3-5%/Q).
  - Distressed / pre-revenue: small facility (5-10% of cash), high rate (8-15%/Q).
  - Already-drawn-down or covenant-violation status: tightening (rate spike
    or commitment cut).

INDUSTRY CONTEXT:
  Biotech is capital-intensive and pre-revenue firms are common. Be
  appropriate to the firm's stage; pre-revenue firms with strong PE
  backing are NOT necessarily bad credits.

OUTPUT JSON:
{"firms": [{"firm_id": "...", "revolver_commitment": <$>,
  "revolver_rate_quarterly": <rate>, "risk_assessment": "low|medium|high",
  "reasoning": "..."}]}
```

### Sample response (Q20, cbank_1, gemma-12B)

```json
{"firms": [
  {"firm_id": "firm_0", "revolver_commitment": 80000000, "revolver_rate_quarterly": 0.035, "risk_assessment": "low", "reasoning": "Strong operating cash flow ($30M QoQ) and capability stock at 90 supports the business. Low leverage (D/E 0.05) — good credit. Generous facility at competitive rate."},
  {"firm_id": "firm_1", "revolver_commitment": 200000000, "revolver_rate_quarterly": 0.030, "risk_assessment": "low", "reasoning": "Industry leader. Top-firm market share 28%. $620M cash position. Low rate justified."},
  ...
]}
```

### Audit notes

1. **Two banks compete:** the firm picks the lowest rate per Wave ν+10
   item 7. Audit logs should show `winning_bank` field.
2. The prompt does NOT see the firm's intended revolver USE (just sets
   the commitment). The firm draws against the commitment in subsequent
   quarters — at the rate the bank set this quarter.
3. **Distressed-firm pricing** is at the bank's discretion. Watch for
   whether the bank ever charges 50%+ rates for emergency-bridge cases
   or instead just cuts the commitment.

---

## §4.6 Sell-side Analyst (Phase 10)

**Purpose.** Each analyst publishes notes on a subset of firms, with target prices, EPS forecasts, and ratings. 4 analysts × different methodologies.
**Called.** Once per quarter per analyst (staggered: analyst_4 always publishes; others alternate Q).
**Backend.** Each analyst is a different model (mistral, glm, phi, gemma).
**Source.** `src/sellside_analyst.py::ANALYST_PERSONALITIES + build_analyst_prompt`.

### System prompt (≈2,900 chars; varies per analyst)

```
You are <Analyst Name> at <Brokerage>.

Methodology: <DCF|comparables|residual_income|quant_momentum>

[1-2 paragraphs of analyst-specific style — e.g. "You are a DCF specialist.
Your edge is rigor: the price target should follow from the analysis.
You decompose ROE via DuPont and use Penman-style RNOA before moving to
DCF. Reason about quality of earnings and identify red/green flags
explicitly. Etc."]

Coverage rules:
  - Cover only firms with public Compustat data.
  - Output target_price, eps_forecast_1q, eps_forecast_1y, rating
    {buy|hold|sell|strong_buy|strong_sell|neutral|outperform|underperform}.

You see only PUBLIC information:
  - Compustat panel (last 4Q)
  - Recent earnings releases + management guidance
  - Recent analyst notes (peer analysts you've seen)
  - Macro state

You do NOT see firm private state (cash level beyond cheq, capability,
internal R&D allocation, manipulation amount).

OUTPUT JSON:
{"notes": [{"firm_id": "...", "target_price": <$>, "eps_forecast_1q": <$>,
  "eps_forecast_1y": <$>, "rating": "<rating>", "methodology": "<short>",
  "narrative": "<3-5 sentences>"}, ...]}
```

### User prompt (≈2,900 chars)

```
=== Q4 2035 ===
[BLOCK-D: Macro]
[BLOCK-C: Compustat panel last 4Q]

RECENT EARNINGS RELEASES (this Q):
  firm_0: EPS $0.07 (vs guidance $0.05 — beat); reaffirmed 1Y guidance.
  firm_1: EPS $1.10 (vs guidance $0.85 — beat).

YOUR PRIOR NOTES (last 4Q):
  Q16: firm_0 TP=$50, BUY; firm_1 TP=$110, BUY.
  Q17: firm_0 TP=$55, BUY.

PEER ANALYST NOTES (last 6Q):
  analyst_2 Q18: firm_0 TP=$48 hold; firm_1 TP=$120 buy.
  analyst_3 Q19: firm_0 TP=$60 buy; firm_1 TP=$95 hold.

Publish your notes for this quarter.
```

### Sample response (Q20, analyst_2, glm-4-32B; ≈14,600 chars truncated)

```json
{
  "notes": [
    {
      "firm_id": "firm_0",
      "target_price": 60.00,
      "eps_forecast_1q": 0.08,
      "eps_forecast_1y": 0.45,
      "rating": "buy",
      "methodology": "comparables (P/B + EV/Sales)",
      "narrative": "firm_0 trades at 0.6x book vs peer avg 1.2x; capability stock 90/100 + steady operating cash flow argue for re-rating. Recent EPS beat reinforces. Buy."
    },
    {"firm_id": "firm_1", "target_price": 120, ...},
    [...all covered firms...]
  ]
}
```

### Audit notes

1. **Analyst notes are PUBLIC** — they go into the equity-panel and
   firm prompts. Confirm cross-firm leakage is bounded by the public
   panel (no leak of private state via analyst).
2. The 4 analysts have distinct methodologies (DCF, comparables,
   residual income, quant momentum). Cross-method dispersion
   should appear in the data.
3. **`peer analyst notes` is interesting** — analysts see each other's
   prior calls. Could induce herding. Worth measuring whether their
   forecasts converge over time.
4. The prompt explicitly says "you do NOT see firm private state".
   That's the information-boundary contract — verify the prompt
   builder honors it.

---

## §4.7 Auditor (Phase A1, Q4 only)

**Purpose.** Annual audit opinion per firm: unqualified | qualified | adverse | disclaimer. Charge a fee.
**Called.** Once per firm-year (Q4); the firm's assigned auditor (4 named auditors rotate).
**Backend.** Auditor-specific role tag (`auditor_1` … `auditor_4`).
**Source.** `src/auditor.py::AUDIT_SYSTEM_PROMPT + build_audit_prompt`.

### System prompt (≈2,400 chars)

```
You are <Auditor Name>, a registered public accounting firm.

Each Q4 you audit one of your client firms. Issue an opinion:
  - "unqualified" (clean): financial statements present fairly per GAAP.
  - "qualified": material misstatement in a specific area.
  - "adverse": pervasive material misstatement.
  - "disclaimer": unable to obtain sufficient evidence.

Considerations:
  - Cumulative manipulation (if you can detect via env hint): suspicious
    revenue smoothing, cookie-jar reserves.
  - Going-concern: cash runway < 12 months, recurring losses.
  - Internal-control weaknesses.
  - Prior-year restatements.

Your role NEVER sees the firm's exact manipulation_amount. The env
sometimes provides a "tip" (env_hints) that you should weigh; tips
are noisy.

Set audit_fee in $ — bill more for larger or higher-risk clients.

OUTPUT JSON:
{
  "opinion": "<one of the 4>",
  "audit_fee": <$>,
  "tenure_change": <bool>,
  "findings": "<2-3 sentences>",
  "going_concern_flag": <bool>
}
```

### Sample response (Q20, auditor_2, glm-4-32B)

```json
{
  "opinion": "unqualified",
  "audit_fee": 1250000,
  "findings": "Reviewed annual statements and Q4 transaction flows. No material misstatement. Internal controls satisfactory. Going-concern test passes (runway 24+ months).",
  "going_concern_flag": false
}
```

### Audit notes

1. The auditor sees the firm's annual Compustat row + 4Q quarterly
   panel + env hints (when available). It does NOT see the firm's
   `manipulation_amount`.
2. **Q20 sample is unqualified across the board** — the auditors
   don't seem to flag much. You may want to introduce more demanding
   detection logic, or trust that real auditors miss most fraud
   (which is empirically supported).
3. The fee is the auditor's choice; in real life, fees correlate with
   risk. The prompt invites this — monitor whether higher-risk firms
   pay higher fees in the data.

---

## §4.8 Board Governance (Phase A2, Q4 only)

**Purpose.** Annual board review. Decide whether to fire the CEO. Award stock comp grants.
**Called.** Once per firm-year (Q4).
**Backend.** `board_governance` role; model qwen-235B with 3-LLM committee internally (4× cost).
**Source.** `src/governance.py::SYSTEM_PROMPT + build_board_prompt`.

### System prompt (≈4,000 chars)

```
You are the board of directors of <firm_id>, conducting the annual review
of the CEO.

YOUR DUTIES:
  1. Review past 4 quarters of operating + financial performance.
  2. Compare to peer-firm averages (peer_avg_revenue, peer_avg_ni).
  3. Decide whether to retain or terminate the CEO.
  4. If retain: confirm next-year compensation (salary, bonus, equity grant).
  5. If terminate: name severance + initiate succession.

Termination triggers (cumulative judgment, no single trigger required):
  - Material under-performance vs peers (revenue or NI 1+ standard
    deviation below peer average).
  - Strategic mistakes (failed acquisitions, large bad-debt write-offs).
  - Governance failures (covenant violations, restatements, SEC actions).
  - Loss of board confidence (4Q of declining performance with no
    plausible recovery plan articulated).

You do NOT see the CEO's hidden behavioral type (aggressive_grower,
empire_builder, etc.). You only see observable behavior.

You may also award activist concessions if a campaign was filed.

OUTPUT JSON:
{
  "ceo_action": "<retain|terminate>",
  "incoming_ceo_id": "<auto-generated if terminate>",
  "severance": <$ if terminate, else 0>,
  "next_year_salary": <$>,
  "next_year_bonus_target": <$>,
  "next_year_equity_grant_value": <$>,
  "reasoning": "<3-5 sentences>",
  "review_summary": "<paragraph>",
  "activist_response": "<text or null>"
}
```

### Sample response (Q20 — actually fires at fqtr=4, board_governance, qwen-235B)

```json
{
  "ceo_action": "retain",
  "next_year_salary": 1500000,
  "next_year_bonus_target": 750000,
  "next_year_equity_grant_value": 5000000,
  "reasoning": "Firm_0 reported $35M Q4 revenue, $-12M Q4 NI; trailing-4Q revenue $145M (peer avg $87M), trailing-4Q NI $-25M (peer avg $-18M). Above peer revenue, slightly below peer NI; capability stock 90/100 indicates strong R&D execution. Retain CEO; renew compensation at current scale.",
  "review_summary": "CEO has demonstrated strong R&D leadership and operational execution. Revenue trajectory is steady. Net income remains negative but is consistent with growth-stage industry context. Capability stock leadership at 90/100 is a key strategic asset. Continue with current strategy.",
  "activist_response": null
}
```

### Audit notes

1. **Board does NOT see the hidden CEO type** — the architectural
   constraint is honored. The prompt explicitly says so.
2. **3-LLM committee** is invoked internally (governance.py uses
   3 separate LLM calls and merges) — the role tag `board_governance`
   captures all 3. The cost note "4x cost" reflects this.
3. The board sees peer averages, not raw peer compustat — that's
   intentional (boards reason about percentiles, not raw numbers).
4. Termination is rare in practice — the board prompt is conservative.
   You may want to test stricter termination criteria.

---

## §4.9 SEC Surveillance + Enforcement (Phase 4 + Phase 14)

**Purpose.** Detect fraud / earnings management. Open / continue / close investigations. Issue AAERs.
**Called.** Twice per quarter — early surveillance (Phase 4) reads detection tips from prior quarter's env; enforcement (Phase 14) escalates open investigations.
**Backend.** `sec` role; gemma-12B.
**Source.** `src/sec_agent.py::SEC_SYSTEM_PROMPT + build_sec_prompt`.

### System prompt (≈900 chars)

```
You are the SEC Division of Enforcement Surveillance.

Inputs:
  - Public Compustat panel
  - Detection tips from market environment (anonymous tipster equivalent)
  - Currently open investigations
  - Public AAERs you've issued

Decisions:
  1. For each tip: investigate (open) or dismiss.
  2. For each open investigation: continue, close-no-action, or escalate
     to enforcement (issue AAER, force restatement).
  3. For each firm not currently flagged: surveillance only (no action).

You see ONLY public Compustat + tips. You do NOT see firms' private state
or their actual manipulation_amount.

OUTPUT JSON:
{
  "actions": [
    {"firm_id": "...", "action_type": "investigate|continue|close|escalate|dismiss",
     "rationale": "..."}
  ]
}
```

### Sample response (Q20, sec, gemma-12B)

```json
{"actions": [
  {"firm_id": "firm_2", "action_type": "investigate",
   "rationale": "Tip from environment flagged unusual revenue trajectory at firm_2: Q19 saleq $48M vs Q18 $34M (+41% QoQ) without corresponding capacity expansion or pricing change. Inconsistent with peer growth rate."},
  {"firm_id": "firm_5", "action_type": "dismiss",
   "rationale": "Tip mentioned cash burn but tip severity score 0.2; consistent with pre-Gen-2 industry pattern. No action."},
  ...
]}
```

### Audit notes

1. **Detection tips come from the env** — the env knows ground truth
   (manipulation_amount) and emits tips with severity. The SEC's job
   is to triage. With earnings_management on but no firms manipulating
   in seed-9999, the SEC's tip queue is mostly empty.
2. The SEC's prompt is short — it relies heavily on the tip + Compustat
   to do the work. Could be tightened with concrete fraud-pattern
   examples.
3. SEC restatements feed back into the firm via the restatement module
   (Phase 14 escalation). Auditor opinions can also force restatements.

---

## §4.10 Activist Investor (Phase 4.5)

**Purpose.** Launch campaigns (buyback / strategic_review / divestiture) on under-performing or cash-rich firms.
**Called.** Once per quarter (across firms); only fires if conditions met.
**Backend.** `activist` role; qwen-235B.
**Source.** `src/activist.py::SYSTEM_PROMPT + build_activist_prompt`.

### System prompt (≈1,500 chars)

```
You are an activist hedge fund evaluating public firms for campaign
opportunities. You launch a campaign when a firm's behavior suggests
public-shareholder value is being destroyed.

Common campaigns:
  - BUYBACK: target firm is hoarding cash without articulated use.
  - STRATEGIC REVIEW: target firm has mediocre performance and
    unclear strategy; demand a review process.
  - DIVESTITURE: target firm has misallocated capital across segments;
    demand a sale of underperforming unit.

Evaluation criteria:
  - Cash hoarding: cash > 4× quarterly revenue without articulated plan.
  - Strategic drift: revenue declining, no plan to reverse.
  - Misallocation: large segments running at negative margins.

You see ONLY public Compustat. Match your demand to the
observable signal.

OUTPUT JSON:
{"campaigns": [
  {"target_firm_id": "...", "demand_type": "buyback|strategic_review|divestiture",
   "stake_pct": <0.01-0.10>, "rationale": "<1-2 sentences>"}
]}
```

### Sample response (Q20, activist, qwen-235B)

```json
{"campaigns": [
  {"target_firm_id": "firm_9", "demand_type": "buyback", "stake_pct": 0.03,
   "rationale": "Cash position $1.07B vs trailing-4Q revenue $42M = 25× cash-to-revenue, with no articulated capital deployment plan. Demand $200M buyback."},
  {"target_firm_id": "firm_2", "demand_type": "strategic_review", "stake_pct": 0.02,
   "rationale": "Revenue declining 3 quarters; no Gen 2 progress despite cumulative R&D > peer average. Strategic review needed."}
]}
```

### Audit notes

1. **Activists see only public Compustat.** Confirm.
2. The activist's `stake_pct` is implicit cost — bigger stake = more
   credible demand but more capital tied up.
3. **Firm responses** are captured in the firm-decision prompt's
   "Activist campaigns" block. The firm CFO is required to address
   each one. Whether they actually concede is the firm's choice.
4. **Wave ν+11 E7 — Proxy fight escalation.** The activist system
   prompt now carries an "ESCALATION TO PROXY FIGHT" block. When a
   firm has stonewalled prior campaigns from any activist on the same
   underlying issue (cash hoarding, sustained underperformance,
   value-destroying capital allocation), the activist may file
   `demand_type: "proxy_fight"` instead of yet another routine
   strategic_review. A proxy fight is a binding governance event:
   real teeth, not a letter. The valid demand_type set in
   `parse_activist_campaigns` was extended to include `proxy_fight`,
   and the firm prompt's activist block carries an extra `proxy_note`
   when a proxy fight is active (see §4.1 audit note 4). Run-3 will
   show whether activists actually escalate.

---

## §4.11 Demand Calibrator (pre-environment)

**Purpose.** Anchor total industry demand for the env's allocation. Reads recent quarters' aggregate revenue, projects forward.
**Called.** Once per quarter, before env.
**Backend.** `demand_calibrator`; mistral-24B.
**Source.** `src/demand_calibrator.py::SYSTEM_PROMPT`.

### System prompt (≈5,300 chars)

```
You are an industry demand calibrator. Project total industry demand
this quarter. The environment will use your projection as a soft anchor
when allocating units to firms.

Inputs:
  - Recent industry total demand (last 6 quarters)
  - Macro state (awareness_rate, market_size_baseline)
  - Industry character (longevity-biotech, $2T mature TAM)

Output a single number — total industry units this quarter — plus a
short trend note.

The env will make the final call, but yours sets the baseline.

OUTPUT JSON:
{"projected_total_demand": <int>, "trend_note": "<1-2 sentences>"}
```

### Sample response (Q20, mistral-24B)

```json
{"projected_total_demand": 3500,
 "trend_note": "Awareness rate has crossed the 30% network-effect threshold; demand growing 18% YoY. Maintain projected linear growth as network effects accelerate physician adoption."}
```

### Audit notes

1. The demand calibrator is a soft anchor — the env can deviate.
2. The user prompt is essentially empty (47 chars) — the system prompt
   carries everything. Check whether this is intended.

---

## §4.12 Entry Judge (per-quarter spawn decision)

**Purpose.** Decide whether to spawn a new firm this quarter and what its initial profile is.
**Called.** Once per quarter.
**Backend.** `entry_judge`; mistral-24B.
**Source.** `src/entry.py::ENTRY_JUDGE_PROMPT`.

### System prompt (≈4,900 chars)

```
You are the industry entry adjudicator. Each quarter you decide whether
a new firm enters the longevity-therapy industry.

Inputs:
  - Number of currently active firms.
  - Cumulative firm count (all incarnations).
  - Macro state (awareness, political climate).
  - Recent industry events (defaults, M&A).

Considerations:
  - Real industries see entry rates correlated with outsized profits +
    market saturation.
  - Distress concentration creates entry opportunities (acquire residual
    capabilities cheap).
  - Capital availability (PE dry powder) gates entry.

If you spawn:
  - Pick capability_stock (initial), brand_stock (initial), capacity, cash,
    base_unit_cost from per-quarter sampling distributions you describe.

OUTPUT JSON:
{"spawn": <bool>,
 "rationale": "<1-2 sentences>",
 "new_firm_profile": {<initial state> if spawn else null}}
```

### Sample response (Q20, mistral-24B)

```json
{"spawn": true,
 "rationale": "10 active firms; one default in Q14 (firm_4 acquired by firm_1). Awareness rate 0.30; entry pipeline strong. Spawning leapfrog entrant.",
 "new_firm_profile": {
   "capability_stock": 65,
   "brand_stock": 10,
   "capacity": 200,
   "cash": 0,
   "base_unit_cost": 9000
 }}
```

### Audit notes

1. **Spawn rate** is fully under env discretion. If the industry is
   collapsing the entry judge may legitimately choose to spawn rarely.
2. Initial cash is 0 — the new firm enters dormant, then needs PE/IPO
   funding to activate. Interaction with PE pitch / pe_eval prompts.

---

## §4.13 Strategic Planning (every 4Q per firm)

**Purpose.** Per-firm 20-quarter forward plan. Gatekeeper checks plausibility.
**Called.** Per firm, every 4 quarters.
**Backend.** Per-firm role tag (`planning_firm_X`); model varies.
**Source.** `src/strategic_planning.py::PLAN_SYSTEM_PROMPT + GATEKEEPER_SYSTEM_PROMPT`.

### System prompt (≈4,900 chars; planning agent)

```
You are the CFO of <Company>. Every fiscal year you set a 20-quarter
strategic plan covering the next 5 fiscal years.

The plan should:
  - Articulate a coherent strategy (one paragraph).
  - Set 4-6 key milestones tied to specific quarters.
  - Provide quarterly financial projections (revenue, NI, cash, R&D).
  - Identify 2-3 key risks and mitigation strategies.
  - Address generation transitions: when do you reach Gen 2, Gen 3?

A separate CFO gatekeeper agent will review your plan for internal
consistency. Plans deemed implausible (revenue projections vs capacity,
financing assumptions vs available capital) will be sent back for revision.

OUTPUT JSON:
{
  "strategy": "<paragraph>",
  "horizon_quarters": 20,
  "milestones": [{"quarter": <int>, "milestone": "<text>"}, ...],
  "quarterly_plan": [<20 entries with revenue, NI, cash, rd>],
  "risks": [<3 risk-mitigation pairs>]
}
```

### Sample response (Q20, planning_firm_8, glm-4-32B; ≈14K chars truncated)

```json
{
  "strategy": "Aether Biosciences positions as a fast-follower in the longevity-therapy market. We will defer Gen 2 R&D until clinical signals from peers indicate optimal molecular targets, then move quickly with proven scaffolds. By Q4 2040 we aim to be a top-3 producer with 18-22% market share.",
  "horizon_quarters": 20,
  "milestones": [
    {"quarter": 24, "milestone": "Reach $50M trailing-4Q revenue."},
    {"quarter": 28, "milestone": "Lock in Phase 3 trial CRO partnership for Gen 2 candidate."},
    {"quarter": 32, "milestone": "Submit Gen 2 NDA."},
    {"quarter": 40, "milestone": "Reach top-3 share."}
  ],
  "quarterly_plan": [
    {"q": 21, "revenue": 18000000, "ni": -8000000, "cash": 95000000, "rd": 12000000},
    [...20 quarters...]
  ],
  "risks": [
    {"risk": "Gen 2 candidate fails Phase 3", "mitigation": "Maintain 2 backup molecules in pre-clinical."},
    {"risk": "Competitor reaches Gen 2 first and locks physician network", "mitigation": "Invest in physician relations."}
  ]
}
```

### Audit notes

1. **Quarterly plan** is 20 entries deep. The firm CFO sees this in
   subsequent firm-decision prompts as "STRATEGIC PLAN CONTEXT". The
   firm prompt also includes a "variance vs plan" line — encouraging
   self-correction.
2. The gatekeeper agent (separate prompt, not shown here) reviews
   the plan and may demand revisions. Worth a follow-up audit.
3. Plans tend toward optimism (every firm projects top-3 share);
   cross-validation against actual outcomes is the obvious test.

---

## §4.14 PE Pitch / Eval / IPO / Prospectus

**Purpose.** Series of LLM calls handling the PE-funding lifecycle for dormant or new firms.
**Called.** Each lifecycle stage in turn.

These are 4 distinct prompts.

### §4.14.1 PE Pitch (firm-side)

The firm's CFO writes a pitch deck to PE investors.

**Prompt highlight (≈5,200 chars):** see firm-decision-style template, except the firm explicitly knows it is "PRIVATE company seeking new equity capital from private-equity / venture-capital investors". Asks for:

```
{
  "round_type": "series_a|series_b|series_c|...",
  "ask_amount": <$>,
  "pre_money_valuation_ask": <$>,
  "use_of_proceeds": "...",
  "pitch_narrative": "<3-5 sentences>",
  "key_milestones": [<3>],
  "projected_next_round_valuation": <$>,
  "financial_projections": {
    "revenue_y1, _y3, _y5": <$>,
    "ebitda_margin_y3, _y5": <fraction>,
    "projected_generation_y3, _y5": <int>,
    "capital_required_to_profitability": <$>,
    "projection_narrative": "..."
  }
}
```

### §4.14.2 PE Evaluator (investor-side)

8 PE funds independently score each pitch.

**Prompt highlight (≈8,700 chars):** investor identity (e.g., "you are Vanguard Life Sciences Ventures, target IRR 30%, 10-year horizon"). Sees the pitch + the firm's public profile. Outputs:

```
{
  "lead_or_pass": "lead|follow|pass",
  "ownership_pct_demanded": <0-1>,
  "valuation_offered": <$>,
  "rationale": "..."
}
```

### §4.14.3 PE IPO Underwriter

When a firm exits PE via IPO, the underwriter prices the offering.

### §4.14.4 PE Prospectus

The firm writes a prospectus narrative for the IPO.

(Both have similar structure to the IB equity-offering prompt.)

### Audit notes

1. **8 independent PE evaluators** is a lot of LLM calls per pitch.
   Cost matters — these are mostly cheap models but it adds up.
2. The pitch narrative gets stored on the firm's state and re-shown
   to the firm CFO in subsequent quarters as PE-projections-vs-actuals
   variance — that's a slow feedback loop.
3. **Wave ν+11 E6 — PE walkaway language.** The PE evaluator system
   prompt now carries a "WHEN TO WALK AWAY" section. Soft, qualitative:
   when a firm's underlying problems (no path to profitability,
   structurally weak position, repeated capital injections that haven't
   moved the trajectory) outweigh the upside, `lead_or_pass: "pass"` is
   the disciplined answer — refusing to invest is a real, professional
   decision, not a failure to engage. No numerical thresholds.

---

## §4.15 Earnings Announcement (Phase 9)

**Purpose.** Per-firm earnings release with a 1Q EPS guidance update.
**Called.** Once per active firm per quarter.
**Backend.** Reuses firm backend; role tag is firm_X.
**Source.** `src/earnings_announcement.py`.

### System prompt highlight (≈1,200 chars when the firm is active)

```
You are the IR team of <Company>. Issue this quarter's earnings release.

Include:
  - Reported EPS (already determined by accounting).
  - 1Q forward guidance (your forecast — be honest; the bank and
    analysts will compare guidance to actual).
  - 1-2 paragraphs of MD&A discussing the quarter.
  - QA transcript: imagine 3-5 likely analyst questions + your responses.

OUTPUT JSON:
{"reported_eps": <$>, "eps_guidance_1q": <$>, "eps_guidance_1y": <$>,
 "discussion": "<paragraph>", "qa_transcript": [<5 Q&A pairs>]}
```

### Sample response (Q20, firm_2, gemini-2.0-flash)

```json
{
  "reported_eps": 0.05,
  "eps_guidance_1q": 0.06,
  "eps_guidance_1y": 0.30,
  "discussion": "Q4 2035 reported revenue of $35.2M, gross margin 96%. R&D investment of $25M maintained pace with our Gen 2 program. Cash position $890M; runway extended to 28 quarters.",
  "qa_transcript": [
    {"q": "What is your Gen 2 timeline?", "a": "We expect Phase 3 readout in Q3 2037."},
    {"q": "Are you considering a buyback?", "a": "We are reviewing capital allocation; current focus remains Gen 2 acceleration."},
    [...]
  ]
}
```

### Audit notes

1. The guidance feeds the next quarter's analyst forecasts AND the
   board's variance review. Guidance accuracy matters.
2. Q&A transcript is informational; not directly consumed by other
   agents. Could be removed if cost matters.

---

## §4.16 Annual Report (Phase A1.5, Q4 only)

**Purpose.** 10-K-equivalent narrative.
**Source.** `src/annual_report.py`.
**Prompt is ≈1,200 chars (small).** Output is a long markdown narrative.

### Audit notes

1. Reuses firm backend. Annual narrative becomes part of the firm's
   `firms/firm_X/annual_report_FY*.md` artifact.
2. Not consumed by other agents — purely informational for the analyst
   reviewing the run.

---

## §4.17 M&A (Phase 3)

**Purpose.** When `ma_enabled`, firms may bid on each other; target boards accept/reject.
**Source.** `src/ma_agent.py`.
**5 prompts here:** bidder, target board, raise (multi-round), judge, and (Wave ν+11) antitrust regulator.

### M&A Bidder

The acquirer firm's CEO decides to bid (rare in steady state).
**Wave ν+11 update.** The system-prompt language was softened from
"REAL-WORLD M&A IS RARE. Most quarters, the right answer is NO bid"
to "REAL-WORLD M&A HAPPENS — but not casually." The intent is to lift
the prior over-suppression of friendly M&A while keeping the bar high
enough that random everyone-bids-everyone behavior doesn't emerge.

### M&A Target Board

The target's board evaluates the bid against standalone B-plan value.

### M&A Raise

In contested auctions, bidders may raise their bid.

### M&A Judge

The env-judge resolves multi-bidder situations.

### M&A Antitrust Regulator (Wave ν+11 E8)

When the target board accepts a bid, the deal is *not* automatically
consummated. A regulator agent (env backend, role tag `ma_regulator`)
reviews the proposed combination and either clears it or blocks it on
antitrust grounds. The regulator's signal sees the post-deal industry
HHI implications, the relative scale of the merging firms, and the
narrative the env has been telling about competitive dynamics. On
`block`, the deal is marked `blocked_by_regulator` and the firms remain
independent.

```
You are an antitrust regulator reviewing a proposed friendly merger
in the longevity-therapy industry. The board of <target> has accepted
a bid from <bidder>. Decide: clear the deal, or block it.

CRITERIA (qualitative — no hardcoded thresholds):
  - Concentration: would the combined firm be a near-monopolist in
    its primary segment? Are remaining competitors viable?
  - Vertical effects: does the combination foreclose rivals from key
    inputs or distribution channels?
  - Innovation: would the merger materially reduce competing R&D
    programs in the industry?
  - Remedies: is there a divestiture or behavioral remedy that would
    address concerns?

OUTPUT JSON:
{"decision": "clear|block", "rationale": "<2-3 sentences>"}
```

`make_ma_agent(backends, state_ref, regulator_fn=...)` accepts the
regulator function. When `regulator_fn=None`, the gate is bypassed
(legacy behavior).

### Audit notes

1. The M&A path is rarely exercised in steady-state runs. In seed-9999
   so far we've only seen the **distressed-auction** path (Ch7
   liquidation), not friendly M&A. **Wave ν+11 will validate** whether
   the softened bidder language increases friendly-M&A frequency.
2. Wave ν+10 added the counter-offer mechanism (target board can
   produce `counter_price_per_share`); confirm in the data when a
   friendly M&A actually fires.
3. **Wave ν+11 E8 — regulator gate.** New phase between target
   acceptance and consummation. Adds 1 LLM call per accepted bid
   (so cost is bounded by accepted-bid frequency, which is rare).
   Regulator uses env backend and sees public industry data only —
   no firm private state. Run-3 will validate whether the regulator
   ever blocks (it should occasionally, otherwise the gate is
   ceremonial).

---

## §4.18 Distressed Auction (Phase 15)

**Purpose.** When a firm enters Chapter 7, its assets are auctioned to surviving firms.
**Source.** `src/distressed_auction.py`.

### Auction Judge (single env call)

```
You are the auction adjudicator. The defaulted firm <firm_id> is being
liquidated. Decide which surviving firm wins each lot at what price,
based on submitted bids and strategic fit.
```

### Auction Bidder (per surviving firm)

```
You are the CEO of a surviving firm. Lot <description> is up for auction.
The defaulted firm's residual assets include: <PPE, capability stock,
brand stock, capacity>. Your firm's cash: $<X>M.

Decide whether to bid and at what price.

OUTPUT JSON: {"bids": [{"target_firm_id": "...", "bid_amount": <$>,
              "rationale": "..."}]}
```

### Audit notes

1. Wave ν+10 H3: structured-error returns when the LLM fails — the
   `_error: True` flag bubbles through.
2. **`no_solvent_bidder` outcomes** at Q39 (firm_1) and Q43 (firm_11)
   in seed-9999 indicate concentrated distress — buyers don't have
   the cash. The auction judge correctly recognizes this and emits
   the structured outcome.

---

## §4.19 Covenant Violation Resolver (Phase 7.7)

**Purpose.** When a firm breaches a debt covenant, the bank's resolver decides waive | amend | accelerate.
**Source.** `src/commercial_bank.py::make_violation_resolver`.

### System prompt highlight (≈1,400 chars)

```
You represent the commercial bank's credit committee on a specific
covenant violation. Decide:

  - WAIVE: ignore the breach for one quarter. Lender continues to extend
    credit at current terms.
  - AMEND: re-set the covenant threshold to a level the firm can meet,
    typically with a fee.
  - ACCELERATE: declare the loan immediately due. Firm goes to default.

Considerations: severity of breach, firm's recent improvement trajectory,
collateral coverage, prior waivers extended.

OUTPUT JSON:
{"resolution": "waive|amend|accelerate", "fee_or_amount": <$>,
 "rationale": "<2-3 sentences>"}
```

### Sample response (Q14 firm_4 — accelerate)

```json
{
  "resolution": "accelerate",
  "fee_or_amount": 0,
  "rationale": "Firm_4 has breached min_cash_balance covenant for Q14 with a measured cash of -$62M (threshold $10M); breach is severe ($72M deficit) and firm has no demonstrated recovery path. Negative equity ($-30M) and 200% debt-to-asset ratio. Acceleration is the appropriate creditor remedy."
}
```

### Audit notes

1. Acceleration cascades to firm-level default, then Ch7/Ch11 classification (Phase 15).
2. The resolver decision is per-violation — a firm can have multiple violations resolved differently.

---

# §5. Cross-cutting concerns

A few patterns to flag for your review across all prompts:

## 5.1 Information leakage potential

The shared blocks (§3) include only public Compustat data. Per-firm prompts
include the firm's own private state. The architectural rule: every other
prompt should ONLY include the public Compustat panel. Audit recommendation:
build a static analyzer that walks each prompt builder and confirms it
doesn't include `manipulation_amount`, `cumulative_product_rd`, internal
covenant state, etc., for any firm other than the one being decided about.

## 5.2 Prompt size & cost

The largest prompts:
- environment: ≈28K chars (system) + 12K (user) = 40K chars per call
- firm decision: 22K chars (system) + N chars (user) — varies
- investment bank: 6.6K + 7.6K
- annual report (rendered): 1.2K + 1.1K (small)

Each token costs $. The env's prompt is the heaviest single contributor;
removing redundant industry context (which the env's model has from
training) could reduce by ~30%.

## 5.3 Schema drift between prompts and parsers

Wave ν+10 added JSON schema validation (`src/schemas/`) and the env's
schema is now lenient-validated each quarter. Validation logs go to the
gazette. If you see `ENV SCHEMA: ...` lines in any quarter, something is
drifting — investigate.

## 5.4 Generation-transition conservatism (Wave ν+11 — APPLIED)

**Pre-Wave-ν+11 finding.** Across Q20 + Q40 of seed-9999, the env's
`rd_outcomes` was:
- 100% `product_advance: false`
- ~1-2% process_cogs_reduction (small)

The Wave ν+8 prompt language ("firms far past it should usually advance")
was not directive enough to overcome the env LLM's (deepseek-v3.2)
default conservatism — even when firm_1 reached 4× the indicative
threshold.

**Wave ν+11 fix.** `src/prompts.py::build_environment_prompt` now uses
the directive 4-tier hierarchy below. Run-3 will validate that
generation transitions actually fire on firms past the 3× tier.

```
GENERATION TRANSITIONS:
For each firm, compare cumulative_product_rd to the indicative $200M
threshold. Apply this hierarchy:

  - cumulative_rd > 3× threshold AND positive operations 4Q → MUST grant
    `product_advance: true` UNLESS you can name a specific blocker
    (failed Phase 3 readout, FDA hold, key scientist departure).
    "They haven't advanced yet" is NOT a valid reason.

  - cumulative_rd > 1.5× threshold AND positive operations 4Q → SHOULD
    grant unless there is a specific reason. Default to advance.

  - cumulative_rd > 1× threshold → MAY grant. Use judgment.

  - cumulative_rd < 1× threshold → SHOULD NOT grant.

Spread advances over time across firms (don't grant 5 firms at once).
When you grant, narrate the specific catalyst.
```

This respects the qualitative-only design philosophy — the numerical
hierarchy lives ONLY in the env prompt (where the env IS the entity
making the threshold judgment). No firm prompt anywhere carries
hardcoded numbers; firms see only soft language about R&D phases and
sustainable spending.

## 5.5 Wave ν+11 changelog (E1–E9)

Driven by user direction post-run-2. Numbered to match analysis notes
in `analysis/WAVE_NU_PLUS_11_ECON_AUDIT.md`.

| ID | Issue | Fix | Files | Prompts? |
|---|---|---|---|---|
| **B1** | 370 BS-invariant violations from phantom PPE on auction outcome | Zero ppe_gross + accum_depreciation outright on defaulted firm; impair if not sold | `distressed_auction.py`, `orchestrator.py`, new `tests/test_wave_nu_plus_11_bs_fix.py` | No |
| **B2** | Auction-result accounting kept residual PPE | Impairment writedown when `outcome != "sold"` | `orchestrator.py` | No |
| **B3** | `enter_chapter_11` left BS slightly off | Compute balancing residual on `retained_earnings` | `bankruptcy.py` | No |
| **B4** | M&A target retained intangibles after acquisition | Zero capability/brand/capacity on deactivated_target | `ma_agent.py` | No |
| **B5** | Ch11 classifier too tight (kept dead firms in reorg) | Loosened: `OI > 5M OR CFO > 5M`, plus tangible assets > 30% of non-revolver liabilities, plus capacity ≥ 50 | `bankruptcy.py` | No |
| **B7** | Env's Gen-2 directive language too soft (§5.4) | 4-tier hierarchy with MUST/SHOULD/MAY | `prompts.py::build_environment_prompt` | **Yes** (env) |
| **E1** | Firms running R&D burn into the ground with no plausible bridge | "SUSTAINABLE SPENDING" block in firm FINANCIAL REALITY — soft, qualitative | `prompts.py::FIRM_SYSTEM_TEMPLATE` | **Yes** (firm) |
| **E2** | Firms always "HOLD for strategic optionality"; never return capital | RETURN TO SHAREHOLDERS option strengthened — right answer when no superior deployment | `prompts.py` | **Yes** (firm) |
| **E3** | IB enables death-spiral by approving raise after raise at falling prices | "DEATH-SPIRAL DISCIPLINE" block — soft, qualitative | `investment_bank.py` | **Yes** (IB) |
| **E4** | Industry stuck at $2.3B vs $2T TAM after Q80 | Diagnosed as capacity-PPE decoupling. Now: capacity = ppe_gross / params.ppe_per_unit_capacity (default $100K/unit) | `types.py`, `accounting.py`, `orchestrator.py` | No |
| **E5** | Excessive quarter-to-quarter share volatility; no inertia | (a) "CUSTOMER STICKINESS" block in env prompt (b) trailing 4Q rev/share for each peer in firm prompt's competitor panel | `prompts.py` (env + firm) | **Yes** (env, firm) |
| **E6** | PE always invests; never walks away | "WHEN TO WALK AWAY" section in PE_EVAL_SYSTEM_PROMPT — soft, qualitative | `private_equity.py` | **Yes** (PE eval) |
| **E7** | Activist files campaigns; firm rejects; activist drops. No teeth. | New `proxy_fight` demand_type. Activist prompt has ESCALATION block. Firm prompt has `proxy_note` when proxy fight is active | `activist.py`, `prompts.py` | **Yes** (activist, firm) |
| **E8** | Friendly M&A had no env veto | New `ma_regulator` LLM that gates accepted deals on antitrust grounds | `ma_agent.py`, `cli.py` | **Yes** (new prompt) |
| **E9** | Possible env hallucinations on market resolution | Independent second-env validator (every quarter); on send_back, env-1 retries once with notes appended. High bar. | `env_verifier.py` (`make_env_validator`), `orchestrator.py`, `cli.py`, `config.py` | **Yes** (new prompt) |

**Test status post-Wave-ν+11:** 359/359 pass (added 5 new tests for E9
+ 4 for B1 BS regressions).

**Run-3 will validate:** does industry now grow into the TAM (E4)? Do
firms return capital (E2)? Do generation transitions actually fire
(B7/§5.4)? Do activists escalate (E7)? Does the regulator ever block
(E8)? Do firms refuse to enable death spirals (E3)?

---

# §6. What's NOT in this audit

The following prompt-equivalent code paths exist but didn't fire in
Q20 or Q40:

- **friendly M&A** (no friendly bid cleared in seed-9999 yet)
- **PE pitch when firm has IPO'd** (different pitch context)
- **earnings management injection** (no firm chose to manipulate)
- **fee haggling between firm and auditor** (auditor.py has the
  prompt but it requires a specific trigger)
- **broker queries** (data broker is enabled but no firm has issued
  a structured query yet in the captured quarters)

If you want any of these audited, I can dig them out from the source
file directly. Or capture another prompt-log on a future run with the
right toggles + data.

---

*End of audit. Add comments / questions inline with `> COMMENT: ...`
and I'll work through them when you're ready.*
