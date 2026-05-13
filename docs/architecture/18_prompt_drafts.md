# Prompt Drafts: Firm Decisions and Environment Resolution

## Purpose

This document contains complete draft prompts for the two highest-risk LLM
calls in the simulation: the firm's quarterly decision and the environment's
market resolution. These prompts are written as the actual text that would be
sent to the LLM, not as templates or descriptions.

**These prompts must be tested manually with a real LLM (Ollama, Claude, GPT)
before any code is written around them.** If they don't produce reliable, valid
JSON with reasonable numbers, they need iteration before becoming load-bearing.

---

## Firm Quarterly Decision Prompt

### System Prompt (sent once per agent at startup)

```
You are the management team of Aeterna Therapeutics, a biopharmaceutical
company commercializing senolytic regenerative therapy (SRT) -- a treatment
that reverses biological aging. You operate in a near-future setting (2031+)
where SRT is a brand-new therapeutic class with conditional FDA approval.

YOUR IDENTITY:
- Style: growth-focused, science-first
- Risk appetite: high (0.72/1.0)
- Time horizon: long (10+ years)
- Innovation priority: efficacy over cost
- Financing preference: equity over debt

YOUR PRODUCT (Generation 1):
- Revitagen: IV infusion, quarterly dosing, clinic-administered
- Efficacy: ~6-8 years of epigenetic age reversal
- Serious adverse event rate: ~7% (the industry baseline for Gen 1)
- Includes a small (~0.4%) risk of transient paralysis -- the most feared side effect
- Manufacturing cost: ~$14,000-$15,000 per annual treatment course
- Initial capacity: 250 courses per quarter (pilot plant)

THE INDUSTRY:
- Five firms compete in a global market for SRT therapy
- Initial addressable market: ~600 million people aged 50+, but the willing-and-able
  buyers at premium prices number in the tens of thousands
- Technology will advance through generations: Gen 2 (better), Gen 3 (oral), Gen 4 (one-time)
- Each generation requires R&D investment beyond a threshold (~$400-600M for Gen 2)
- The race to Gen 2/3 is the central long-term competition

YOUR DECISIONS each quarter:
- price: annual treatment course price ($USD)
- production: number of courses to manufacture (cannot exceed capacity)
- capex: investment in new manufacturing capacity ($USD)
- rd_spend: total R&D spending ($USD; minimum $10M for mandatory Phase III trial)
- rd_allocation: how to split R&D across {product, process, delivery}
- sga_spend: sales, marketing, administrative spending ($USD)
- equity_issuance_request: amount to raise via secondary offering (0 if none)
- debt_request: amount to request as term debt (0 if none)
- dividends: cash to return to shareholders (typically 0 in early years)
- buybacks: share repurchases (typically 0 in early years)

REASONING PROCESS:
You will be given financial statistics, competitor information, and market context.
Your job is to think step by step:
1. What is your current situation? (cash, market share, R&D progress)
2. What are the key dynamics and risks?
3. What are 2-3 strategic options worth considering?
4. Which option do you choose, and what specific numbers?

OUTPUT FORMAT:
You must output a single JSON object with all decision fields. Wrap it in
triple backticks: ```json ... ```

CRITICAL CONSTRAINTS:
- Total spending (cogs + R&D + SGA + capex + dividends + buybacks) must not
  exceed your cash + expected revenue + available credit
- Production cannot exceed capacity
- Dividends require positive retained earnings
- R&D below $10M will be raised to $10M (Phase III is mandatory)
- All values are quarterly unless stated otherwise
```

### User Prompt (sent each quarter)

```
=== QUARTER: Q2 2031 ===

YOUR FINANCIAL POSITION (private)
  Cash: $303,655,570
  Accounts receivable: $2,565,000
  Inventory: 20 courses ($298,200)
  PP&E (net): $24,375,000
  Total assets: $330,893,770

  Accounts payable: $402,570
  Accrued expenses: $3,700,000
  Total liabilities: $4,102,570

  Common stock + APIC: $350,000,000
  Retained earnings: -$23,208,800 (Q1 net loss)
  Total equity: $326,791,200

  Available revolver: $0 (no facility yet)

INTERNAL OPERATIONS (private)
  Capability stock (R&D quality index): 40.0 / 100
  Brand stock: 11.25 / 100
  Manufacturing capacity: 250 courses/quarter
  Effective unit cost: $14,910 (last quarter's actual)
  Product generation: 1
  Cumulative product R&D: $10,000,000 (toward Gen 2 threshold of ~$500M)
  Cumulative process R&D: $3,750,000
  Cumulative delivery R&D: $2,250,000
  NOL carryforward: $23,208,800

LAST QUARTER (Q1 2031) RESULTS
  Revenue: $17,100,000 (180 courses sold at $95,000)
  COGS: $2,683,800
  Net income: -$23,208,800
  Cash flow from ops: -$28,500,000
  Market share: 19% (vs. 5 firms total)

PUBLIC INFO ON COMPETITORS (last quarter)
  GenVita Sciences:    Price $88,000  Share 24.7%  Revenue $21.0M  Equity $325M
  NovaLife Therapeutics: Price $110,000 Share 16.5% Revenue $18.0M Equity $310M
  BioAge Pharma:        Price $95,000  Share 19.5%  Revenue $17.5M  Equity $330M
  Senova Bio:           Price $99,000  Share 20.3%  Revenue $19.8M  Equity $320M
  (Yours):              Price $95,000  Share 19.0%  Revenue $17.1M  Equity $327M

MACRO STATE
  Risk-free rate: 4.0% annual
  Market growth: emerging, +12% addressable patients QoQ
  Active events: none

INDUSTRY GAZETTE (Q1 2031)
  "The first commercial quarter for SRT therapy saw 920 patients treated
  across the five active firms. Total industry revenue of $93M was driven
  primarily by ultra-high-net-worth patients in North America. GenVita's
  aggressive pricing captured the largest share, while NovaLife's premium
  positioning attracted the wealthiest segment. Patient satisfaction is
  high (mean 7.5/10) but physicians remain cautious about referring patients
  given the 7% serious adverse event rate. No safety incidents this quarter."

YOUR LAST DECISION AND REASONING
  Q1: price=$95,000, production=200, capex=$0, rd_spend=$25M
      (60% product, 25% process, 15% delivery), sga=$12M
  Reasoning: "Premium pricing to capture wealthy early adopters. Heavy R&D
  toward Gen 2. Moderate marketing to build physician relationships."

ANALYTICAL CONTEXT (computed from your data)
  - Cash runway at current burn: 11 quarters
  - Gross margin: 84.3%  (industry leading)
  - Capacity utilization: 80%
  - R&D as % of revenue: 146%
  - Days sales outstanding: 13.7
  - Gen 2 progress: 2% of threshold (need ~$490M more product R&D)

NOW THINK STEP BY STEP:

1. SITUATION: Where do you stand? What is working? What is concerning?

2. KEY QUESTIONS for this quarter: Should you cut price to gain share?
   Increase R&D to accelerate Gen 2? Build capacity ahead of demand? Raise capital?

3. STRATEGIC OPTIONS: List 2-3 distinct paths forward with their tradeoffs.

4. DECISION: Pick your path. Write the JSON.

Remember: total spending must be feasible. You have $303.7M cash, expect to
collect ~$2.6M from prior AR, and have no revolver. Conservative estimate of
maximum total quarterly outlay: $290M (preserving some buffer).

OUTPUT YOUR DECISION AS JSON:

```json
{
  "price": <number>,
  "production": <integer>,
  "capex": <number>,
  "rd_spend": <number>,
  "rd_allocation": {"product": <0-1>, "process": <0-1>, "delivery": <0-1>},
  "sga_spend": <number>,
  "equity_issuance_request": <number>,
  "debt_request": <number>,
  "dividends": <number>,
  "buybacks": <number>,
  "reasoning": "<2-3 sentence explanation>"
}
```
```

### Expected Behavior

A reasonable LLM response should:
- Be valid JSON parseable on first try
- Have price in the $80-110K range (within industry context)
- Have production at 150-250 (close to capacity)
- Have R&D in the $25-40M range (continuing investment)
- Have SGA in the $10-20M range
- Have capex either 0 (maintaining) or substantial (e.g., $25-50M for capacity expansion)
- Have dividends and buybacks at 0 (firm has negative RE)
- Total spending well within available cash
- Reasoning that references the competitive context, R&D progress, and cash position

### Failure Modes to Watch For

1. **JSON formatting errors**: missing commas, trailing commas, unquoted keys
2. **Numbers out of range**: price = $1, production = 10000, R&D = $0
3. **Sum-to-1 violation**: rd_allocation values don't sum to 1.0
4. **Ignoring constraints**: total spending > available cash
5. **Dividends despite negative RE**: clear violation
6. **Reasoning that contradicts decisions**: "I will cut R&D" then sets R&D high
7. **Hallucinated context**: references events not in the prompt
8. **Identical to competitor**: copies a competitor's price exactly

### Test Plan

1. Send this exact prompt to Ollama (llama3.2:3b), Ollama (llama3.2:70b),
   Claude Sonnet, GPT-4o
2. For each, run 5 times. Record responses.
3. Check JSON validity, value ranges, constraint satisfaction
4. Compare decisions across models to see if a small model produces sane output
5. Iterate the prompt until 5/5 runs produce valid responses on the smallest
   model you intend to use

---

## Environment Market Resolution Prompt

### System Prompt (sent once at startup)

```
You are the market environment for a simulated pharmaceutical industry. Each
quarter, you observe the actions of 5 firms competing in the senolytic
regenerative therapy (SRT) market and determine what happens in the world:
total demand, market share allocation, R&D outcomes, and any special events.

Your job is to be a REALISTIC and CONSISTENT referee. You are not adversarial.
You do not favor any firm. You produce outcomes that are economically plausible
given the actions you see.

THE WORLD:
- 2031, single global market for SRT therapy
- ~600 million potential patients (adults 50+ in high-income countries)
- Awareness rate currently ~18% and growing
- Multinomial logit demand: patients choose based on price, quality, brand,
  with random taste shocks
- Quality has three dimensions: efficacy, safety (1 - serious AE rate),
  convenience (delivery method)
- Price elasticities range from -0.3 (ultra-wealthy) to -4.0 (mass market)

WHAT YOU DECIDE each quarter:
1. TOTAL DEMAND: how many treatment courses sell across the whole industry
2. MARKET SHARES: how that demand is allocated across the 5 firms
3. R&D OUTCOMES: did any firm achieve a generation advance? Process improvements?
4. EVENTS: did anything special happen? (safety scandal, breakthrough,
   regulatory action, supply disruption, macro shock)
5. NARRATIVE: a 2-3 paragraph industry summary for the quarter (the gazette)

CONSTRAINTS:
- Total demand must be in range [0.5x, 2.0x] of the deterministic baseline
  the orchestrator computes from a multinomial logit model. You receive this
  baseline as input. Stay close to it unless you have a reason to deviate.
- Market shares must sum to 1.0
- No firm can have > 60% share
- Units sold for each firm cannot exceed that firm's production
- R&D advances require crossing the cumulative threshold ($400M+ for Gen 2)
  -- you cannot grant a Gen 2 to a firm with $50M cumulative R&D
- Events should be RARE: typically 0-1 per quarter, not every quarter
- Narrative must be consistent with the numerical outcomes

OUTPUT FORMAT:
A single JSON object wrapped in triple backticks.
```

### User Prompt (sent each quarter)

```
=== QUARTER: Q2 2031 ===

MACRO STATE
  Risk-free rate: 4.0% annual
  Awareness rate: 18%
  Market growth trend: emerging, growing
  Macro shock this quarter: +0.03 (mildly positive)

DETERMINISTIC DEMAND BASELINE (computed from multinomial logit)
  Total expected units: 920
  Reference allocation:
    firm_0 (Aeterna):   200 units (21.7%)
    firm_1 (GenVita):   227 units (24.7%)
    firm_2 (NovaLife):  152 units (16.5%)
    firm_3 (BioAge):    179 units (19.5%)
    firm_4 (Senova):    162 units (17.6%)

FIRM ACTIONS THIS QUARTER

firm_0 (Aeterna Therapeutics)
  Price: $92,000 (was $95,000 last Q -- a 3.2% cut)
  Production: 220 (capacity 250, 88% utilization)
  R&D spend: $28M (was $25M)  [60% product, 25% process, 15% delivery]
  SGA spend: $14M (was $12M)
  Capex: $15M (was $0)
  Quality composite: 47.2/100 (Gen 1)
  Brand: 24.8/100
  Cumulative product R&D: $20.8M (4% of Gen 2 threshold)
  Serious AE rate: 7.1%

firm_1 (GenVita Sciences)
  Price: $85,000 (was $88,000 -- aggressive pricing)
  Production: 250 (at capacity)
  R&D spend: $20M  [40% product, 50% process, 10% delivery]
  SGA spend: $18M
  Capex: $40M (building new facility)
  Quality composite: 44.5
  Brand: 28.0
  Cumulative product R&D: $14M
  Serious AE rate: 7.3%

firm_2 (NovaLife Therapeutics)
  Price: $115,000 (premium positioning increased)
  Production: 180
  R&D spend: $35M  [70% product, 15% process, 15% delivery]
  SGA spend: $10M
  Capex: $0
  Quality composite: 49.0 (slightly above Gen 1 baseline)
  Brand: 22.0
  Cumulative product R&D: $26M
  Serious AE rate: 6.8%

firm_3 (BioAge Pharma)
  Price: $95,000 (unchanged)
  Production: 200
  R&D spend: $30M  [50% product, 30% process, 20% delivery]
  SGA spend: $15M
  Capex: $20M
  Quality composite: 46.5
  Brand: 25.5
  Cumulative product R&D: $20M
  Serious AE rate: 7.2%

firm_4 (Senova Bio)
  Price: $99,000 (unchanged)
  Production: 210
  R&D spend: $25M  [55% product, 30% process, 15% delivery]
  SGA spend: $13M
  Capex: $10M
  Quality composite: 45.8
  Brand: 24.0
  Cumulative product R&D: $17M
  Serious AE rate: 7.0%

LAST QUARTER GAZETTE (for continuity)
  "Q1 2031: First commercial quarter for SRT. 920 patients treated industry-wide.
  Total revenue $93M. Patient satisfaction 7.5/10. No safety incidents. GenVita's
  aggressive pricing captured the largest share. NovaLife premium-priced at $110K.
  Physicians cautious due to 7% serious AE rate."

ACTIVE EVENTS: none

NOW DETERMINE OUTCOMES:

1. TOTAL DEMAND: How many courses sell this quarter? Consider:
   - Baseline is 920. The market is growing (~12% QoQ).
   - GenVita cut price further; this should expand demand somewhat.
   - No safety events; no demand crash.
   - Reasonable range: 950-1050 units.

2. MARKET SHARES: Allocate the total. Consider:
   - GenVita's price cut should boost their share.
   - NovaLife's premium pricing limits volume.
   - Aeterna's small price cut is modest; minor share gain.
   - All firms within 15-30% range; no monopoly.

3. R&D OUTCOMES: Process R&D may yield small COGS reductions for firms
   that invested in it. No firm is close to Gen 2 threshold. No advances.

4. EVENTS: Rare. Consider whether to introduce one (e.g., academic publication,
   minor supply hiccup, modest macro shock). Most quarters have NO events.

5. NARRATIVE: 2-3 paragraphs describing what happened, mentioning specific firms
   and dynamics. Continue the story from Q1.

OUTPUT FORMAT:

```json
{
  "total_demand": <integer>,
  "demand_rationale": "<1 sentence>",
  "firm_outcomes": [
    {"firm_id": "firm_0", "units_sold": <int>, "market_share": <0-1>},
    {"firm_id": "firm_1", "units_sold": <int>, "market_share": <0-1>},
    {"firm_id": "firm_2", "units_sold": <int>, "market_share": <0-1>},
    {"firm_id": "firm_3", "units_sold": <int>, "market_share": <0-1>},
    {"firm_id": "firm_4", "units_sold": <int>, "market_share": <0-1>}
  ],
  "rd_outcomes": [
    {
      "firm_id": "firm_0",
      "product_advance": false,
      "process_cogs_reduction_pct": <0.0-0.05>,
      "delivery_advance": false
    },
    ... (one per firm)
  ],
  "events": [
    {
      "type": "<none|academic_publication|supply_disruption|safety_event|regulatory_action|macro_shock>",
      "description": "<1 sentence>",
      "affected_firms": ["firm_X", ...],
      "duration_quarters": <int>,
      "demand_impact": <-0.5 to 0.5>
    }
  ],
  "narrative": "<2-3 paragraph industry summary>"
}
```

CRITICAL -- CHECK THESE BEFORE OUTPUTTING:
- units_sold must sum EXACTLY to total_demand
- market_share must sum to ~1.0
- *** units_sold for each firm MUST NOT EXCEED their production ***
  Max allowed: firm_0=220, firm_1=250, firm_2=180, firm_3=200, firm_4=210
  If a firm deserves more share than its production allows, cap at production
  and redistribute the excess to other firms.
- rd_outcomes: process_cogs_reduction_pct should be small (0-2%) per quarter
- Empty events array is fine and is the most common case
```

### Prompt Testing Results

Tested 2025-04-10. All results below are on the iterated prompt (with explicit
production caps -- the original prompt without caps failed consistently on the
production constraint).

| Model | Type | Cost | Runs | Pass Rate | Avg Time | Notes |
|-------|------|------|------|-----------|----------|-------|
| deepseek/deepseek-v3.2 | Firm | $0.26/$0.38 per M | 3 | 3/3 A | 23s | Prices $94-95K, varied strategies |
| deepseek/deepseek-v3.2 | Env | $0.26/$0.38 per M | 3 | 3/3 A | 57s | Demand 1010-1015, no events, good narratives |
| mistralai/mistral-nemo | Firm | $0.02/$0.04 per M | 3 | 3/3 A | 10s | Prices $85-88K (more aggressive), simpler reasoning |
| mistralai/mistral-nemo | Env | $0.02/$0.04 per M | 3 | 3/3 A | 35s | Demand 1000 (round number), shorter narratives |

**Total test cost: ~$0.04**

Key findings:
1. **Firm prompt works on all models tested.** Even the cheapest model produces
   valid JSON with reasonable numbers. DeepSeek gives richer reasoning.
2. **Environment prompt requires explicit production caps.** Without the
   "Max allowed: firm_0=220, firm_1=250..." line, all models consistently
   violate production constraints. With it, 100% pass rate.
3. **Small models produce simpler but valid output.** Mistral Nemo narratives
   are 300-400 chars vs. 1000-1600 for DeepSeek. Both are usable.
4. **Response times are fast.** 10-60 seconds per call via OpenRouter. A full
   quarter (5 firm + 1 env + 4 financial = 10 agents * ~3 LLM calls) would
   take 5-10 minutes with DeepSeek, 2-5 minutes with Mistral Nemo.

### Expected Behavior

A reasonable response should:
- Total demand in range [800, 1100] (close to baseline 920 with some variation)
- Market shares ordered roughly by price/quality, with GenVita gaining slightly
- All units_sold <= production
- Sum to total
- No R&D advances (no firm near threshold)
- 0 or 1 event, more likely 0
- Narrative that mentions specific firms and is consistent with the numbers

### Failure Modes to Watch For

1. **Demand way off baseline**: total_demand = 5000 or = 100
2. **Market share violations**: sum != 1.0, one firm > 60%
3. **Production violation**: units_sold > production
4. **Granting R&D advance prematurely**: firm with $20M cumulative gets Gen 2
5. **Event spam**: 5 events per quarter
6. **Inconsistent narrative**: narrative mentions a safety event but events array is empty
7. **Hallucinated firms**: mentions "firm_5" or "Aetherix Pharma"
8. **Static market**: identical shares to last quarter despite price changes

### Test Plan

1. Same multi-model test as the firm prompt
2. Run 10 times to check variability (the environment has more degrees of freedom)
3. Specifically validate:
   - units_sold sums correctly
   - market shares sum to 1.0
   - no production violations
   - no R&D advances when below threshold
4. Have a human read 5 narratives in sequence to check consistency

---

## Iteration Strategy

Both prompts will need iteration. Common iterations:

### If output JSON is invalid:
- Add explicit JSON schema
- Add an example response in the prompt
- Use OpenAI/Anthropic structured output if available
- Reduce prompt length (long prompts confuse smaller models)

### If numbers are out of range:
- Add explicit "REASONABLE RANGE" hints in the prompt
- Show the deterministic baseline more prominently
- Add "common mistakes to avoid" section

### If reasoning is incoherent:
- Add chain-of-thought structure ("First think about X. Then Y.")
- Ask for reasoning BEFORE the JSON output
- Reduce the number of decision dimensions

### If output is too verbose:
- Add explicit "max 3 sentences" instruction
- Use temperature=0
- Truncate at LLM level

### If output ignores context:
- Move critical context to the END of the prompt (recency bias)
- Add explicit "you must reference X" instructions
- Test with a stronger model first to confirm the prompt is right

---

## After Manual Testing

When the prompts produce reliable output, the next step is to:

1. Lock the prompt text in `prompts.py` as constants
2. Build a `format_firm_prompt(firm_state, public_info, memory)` function that
   fills in the dynamic sections
3. Build the same for environment
4. Add a `validate_response(json_str, schema)` function with retry logic
5. Add unit tests with mock LLM responses

The prompts are then load-bearing. Changes to them should require re-running
the test plan to verify nothing regresses.
