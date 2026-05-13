# Agent Specifications

## Common Agent Structure

Every agent is a standalone Python application with:

| Component | Purpose |
|-----------|---------|
| `server.py` | FastAPI HTTP server -- interface to orchestrator |
| `brain.py` | Multi-step reasoning engine (analyze -> reflect -> decide) |
| `analyst.py` | Statistical tools (pandas/numpy) for data analysis |
| `memory.py` | SQLite database for decisions, reasoning, observations |
| `tools.py` | Python functions the reasoning engine can invoke |
| `config.yaml` | Role, model, fingerprint, orchestrator URL |
| `prompts/` | Role-specific prompt templates for each reasoning step |
| `data/shared/` | Read-only mirror: world docs + past simulation data |
| `data/private/` | Private database, grows over the run |

### Common Interface

```python
# What the orchestrator calls (HTTP)
POST /turn     <- context JSON     -> decision JSON
POST /sync     <- shared data      -> ack
POST /reset    <- new run config   -> ack
GET  /health   -> {"status": "ok", "agent_id": "firm_0"}
GET  /memory/summary -> condensed memory for diagnostics
```

### Common Reasoning Pipeline

Every agent type follows the same 6-step pipeline per turn. The CONTENT differs
by agent type, but the STRUCTURE is identical:

```
OBSERVE -> ANALYZE -> REFLECT -> STRATEGIZE -> DECIDE -> STORE
  (parse)   (stats)   (LLM #1)   (LLM #2)    (LLM #3)  (DB write)
```

### Fingerprints (Personality Profiles)

Each agent receives a randomly drawn personality at run start. The fingerprint is:
- Fixed for the run (deterministic from run seed + agent index)
- Included in the system prompt
- Designed to create heterogeneity across agents of the same type

Fingerprint dimensions (all agents):
- `risk_appetite`: 0.0 (very conservative) to 1.0 (very aggressive)
- `time_horizon`: "short" (2-3yr), "medium" (5-7yr), "long" (10+yr)
- `style`: role-specific (see below)
- `narrative_personality`: a paragraph describing the agent's philosophy

---

## Agent 1: Environment

### Identity
- `agent_id`: `env_0`
- `agent_type`: `environment`
- **1 instance**, typically on the strongest machine / largest model

### Role
The "game master" -- takes firm actions as input, produces market outcomes.
Maintains narrative continuity of the simulated world.

### Fingerprint Dimensions
```yaml
style: "balanced"          # balanced, volatile, conservative, disruption-prone
macro_volatility: 0.6      # tendency to generate large vs. small shocks
event_frequency: 0.3       # tendency to generate special events
narrative_style: "analytical"  # analytical, dramatic, terse
```

### Reasoning Pipeline (per turn)

**Step 1 - OBSERVE**: Parse all firm actions, current macro state, active events.

**Step 2 - ANALYZE** (statistical):
- Compute multinomial logit demand baseline from prices/qualities/brands
- Check active event durations (which expire this quarter?)
- Compare firm actions to historical patterns from past simulations
- Compute aggregate statistics: industry revenue, average price, capacity utilization

**Step 3 - REFLECT** (LLM call #1):
Prompt: "Given these firm actions and market conditions, what is happening in
this market this quarter? Are firms competing on price or quality? Is the market
growing or stagnating? Are any firms behaving unusually?"

**Step 4 - STRATEGIZE** (LLM call #2):
Prompt: "Determine market outcomes. Consider: (a) How much total demand
materializes given awareness, prices, and product quality? (b) How is demand
allocated across firms? (c) Do any R&D programs succeed this quarter? (d) Do any
special events occur? Use the baseline demand model as a reference but you may
deviate if you have a good reason."

**Step 5 - DECIDE** (LLM call #3):
Prompt: "Produce the final outcome JSON. Also write a 2-3 paragraph narrative
explaining what happened this quarter and why. This narrative will be shared with
all agents."

**Step 6 - STORE**: Save the full reasoning trace + outcomes.

### Output Schema

```json
{
  "total_demand": 88500,
  "demand_rationale": "...",
  "firm_outcomes": [
    {"firm_id": "firm_0", "units_sold": 19200, "market_share": 0.217}
  ],
  "rd_outcomes": [
    {"firm_id": "firm_0", "product_advance": false, "process_cogs_reduction": 0.01, "delivery_advance": false}
  ],
  "events": [
    {"type": "none|safety_scandal|regulatory_change|breakthrough|supply_disruption|macro_shock",
     "description": "...", "affected_firms": [], "duration_quarters": 0, "demand_impact": 0.0}
  ],
  "macro_update": {"awareness_change": 0.02, "regulatory_mood": "stable"},
  "narrative": "Q2 2031 saw continued growth in SRT adoption..."
}
```

### Guardrails (enforced by orchestrator)
- `total_demand` in [0.3x, 3.0x] of multinomial logit baseline
- `sum(units_sold) == total_demand`
- `units_sold[i] <= production[i]` for each firm
- No firm market share > 60%
- R&D advances respect cumulative thresholds from world docs
- Event probabilities respect base rates (no scandal every quarter)

---

## Agent 2: Firm (x5 instances)

### Identity
- `agent_id`: `firm_0` through `firm_4`
- `agent_type`: `firm`
- **5 instances**, each with unique fingerprint

### Role
Runs a pharmaceutical company. Makes all operational and financing decisions.
Builds and defends competitive position over 20 years.

### Fingerprint Dimensions
```yaml
style: "growth-focused"       # growth, profitability, rd-intensive, marketing-driven, conservative, balanced
risk_appetite: 0.72
time_horizon: "long"
innovation_priority: "efficacy"  # efficacy, safety, convenience, cost
financing_preference: "equity"   # equity, debt, balanced
narrative_personality: "We are a science-first company..."
```

### What Firms Know (depends on information regime -- see doc 06)

**Always available (private)**:
- Own complete balance sheet, income statement, cash flows
- Own internal stocks (capability, brand, capacity, unit cost)
- Own R&D progress (cumulative spending by program, generation status)
- Own decision history and reasoning traces (from memory.db)

**Available under baseline regime (public)**:
- Competitors' published financial statements (level of detail depends on
  measurement regime)
- Equity prices for all firms
- Macro state (risk-free rate, market growth indicators)
- Environment narrative (qualitative description of market events)
- Shared past simulation database (Compustat panels from prior runs)

**Never available**:
- Competitors' private internal stocks (capability, brand levels)
- Competitors' R&D allocation across programs
- Competitors' unit costs
- Financial institutions' internal portfolio decisions about OTHER firms
- (Unless information regime is set to "full_transparency" for research)

### Reasoning Pipeline (per turn)

**Step 2 - ANALYZE** (statistical, unique to firms):
- Margin analysis: gross, operating, net margin trends over last 4-8 quarters
- Revenue decomposition: price effect vs. volume effect vs. market growth
- R&D efficiency: capability gain per dollar invested, by program
- Cash runway: quarters of runway at current burn rate
- Competitor analysis: price trends, share trends, inferred strategies
- Historical comps: "firms like me in past simulations did X and got Y"
- Capacity utilization: production vs. capacity, and demand vs. production

**Step 3 - REFLECT** (LLM call #1):
"Here is your financial summary, competitive position, and historical comparisons.
What is your assessment of the situation? What are your strengths, weaknesses,
and the key strategic questions for this quarter?"

**Step 4 - STRATEGIZE** (LLM call #2):
"Given your assessment, generate 2-3 strategic options. For each, specify the
key decision variables (price, R&D, capex, marketing) and the expected tradeoffs.
Consider your cash position -- you have $X in cash and $Y in available credit.
Your capacity is K units. Do NOT plan to spend more than you can afford."

**Step 5 - DECIDE** (LLM call #3):
"Choose your plan for this quarter. Output the decision JSON. Justify each
major number."

### Output Schema

```json
{
  "price": 92000,
  "production": 220,
  "capex": 20000000,
  "rd_spend": 30000000,
  "rd_allocation": {"product": 0.55, "process": 0.25, "delivery": 0.20},
  "sga_spend": 15000000,
  "equity_issuance_request": 0,
  "debt_request": 0,
  "dividends": 0,
  "buybacks": 0,
  "reasoning": "Lowering price slightly to capture volume. Heavy R&D push..."
}
```

---

## Agent 3: Investment Bank (1 instance)

### Identity
- `agent_id`: `ibank_0`
- `agent_type`: `investment_bank`

### Role (Revised -- equity pricing moved to Equity Market agent)
- **Advisory and structuring**: structures IPOs, secondary offerings, M&A deals
- Does NOT price equity (that is the Equity Market agent's role)
- Acts as intermediary: firms request capital -> IBank structures -> Equity Market decides
- If `ma_enabled`: advises on acquisition strategy, values targets, structures deals
- Publishes equity research and recommendations (advisory, not price-setting)

### Fingerprint Dimensions
```yaml
style: "relationship-advisory"   # relationship, aggressive-dealmaker, conservative, balanced
deal_appetite: 0.55
advisory_approach: "fundamental valuation with strategic premium"
fee_sensitivity: 0.3              # willingness to discount fees for repeat clients
```

### What the Investment Bank Does Each Quarter

1. **IPO/secondary structuring** (if any firm requests equity):
   - Reviews firm's request and financials
   - Recommends share count, price range, offering structure
   - Passes structured offering to Equity Market for subscription decision
   - Earns underwriting fee (5% of proceeds if successful)

2. **M&A advisory** (if `ma_enabled` and any firm proposes acquisition):
   - Values the target firm
   - Structures the deal (cash/stock mix, financing plan)
   - Recommends to both parties
   - Earns advisory fee (2% of deal value)

3. **Equity research** (every quarter):
   - Publishes ratings (overweight/neutral/underweight) and target prices
   - These are OPINIONS, not binding prices
   - Firms and other agents see the research

### Output Schema

```json
{
  "equity_research": [
    {
      "firm_id": "firm_0",
      "rating": "overweight",
      "target_price_4q": 42.00,
      "reasoning": "Strong R&D pipeline approaching Gen 2..."
    }
  ],
  "ipo_structuring": [
    {
      "firm_id": "firm_3",
      "recommended_price_range": [14.00, 17.00],
      "recommended_shares": 12000000,
      "offering_structure": "firm_commitment",
      "reasoning": "Conservative range for new entrant..."
    }
  ],
  "ma_advisory": [],
  "commentary": "SRT sector showing diverging fundamentals..."
}
```

---

## Agent 3b: Equity Market (1 instance) -- NEW

### Identity
- `agent_id`: `eqmkt_0`
- `agent_type`: `equity_market`

### Role
The Equity Market represents the aggregate behavior of equity investors --
private equity and venture capital when firms are private, public stock market
investors when firms are public.

**This is the agent that actually prices equity and decides whether to invest.**

### Mode-Dependent Behavior

**Private mode** (firm is private):
- Acts as a PE/VC consortium evaluating funding rounds
- Has MORE information than public mode (due diligence access)
- Applies an illiquidity premium (higher required return)
- Can impose governance terms (board seats, liquidation preferences)
- Sets "last-round valuation" each quarter (portfolio mark-to-market)
- Decides: fund this round? At what valuation? How much capital?

**Public mode** (firm is public):
- Acts as the aggregated stock market
- Prices equity based on DCF + multiples + sentiment + momentum
- Decides whether to subscribe to secondary offerings (and at what discount)
- Has LESS information than private mode (only public financials)
- No governance terms beyond shareholder voting
- Sets market price each quarter

**IPO transition**: When a private firm IPOs, the Equity Market shifts from PE
to public mode for that firm. The IBank structures the offering; the Equity
Market sets the market-clearing price and subscribes.

### Fingerprint Dimensions
```yaml
style: "fundamental-value"       # fundamental-value, growth-investor, momentum-trader, contrarian
risk_appetite: 0.60
sentiment_sensitivity: 0.4       # how much macro mood affects pricing
illiquidity_premium: 0.05        # extra return demanded for private equity (quarterly)
portfolio_concentration_limit: 0.30  # max % of portfolio in one firm
```

### Valuation Reasoning (see doc 07 for full framework)

The Equity Market agent uses the multi-step reasoning pipeline to price firms:

1. **Analyze financials** (statistical tools): revenue trajectory, margins, cash,
   debt, R&D progress, market share trends
2. **Project scenarios** (LLM): base case (50%), upside (25%), downside (25%)
   with revenue, margin, and FCF projections
3. **Compute value** (statistical): probability-weighted DCF
4. **Cross-check** (LLM): revenue multiples, past simulation comps, reasonableness
5. **Set price** (LLM): final price with justification and confidence level

### What the Equity Market Knows

| Information | Private Mode | Public Mode |
|-------------|-------------|-------------|
| Financial statements | Full (due diligence) | Published only (per info regime) |
| R&D pipeline detail | Full (board access) | Summary only |
| Internal capability/brand | Yes (board reporting) | No |
| Unit cost detail | Yes | No |
| Customer satisfaction | Yes | Public scores only |
| Competitor private info | No (only own portfolio) | No |

### Output Schema (Public Mode)

```json
{
  "equity_prices": [
    {
      "firm_id": "firm_0",
      "price_per_share": 34.00,
      "valuation_method": "DCF",
      "key_assumptions": {
        "revenue_growth_5yr": 0.35,
        "terminal_margin": 0.30,
        "discount_rate": 0.15,
        "terminal_multiple": 18
      },
      "base_case_value": 38.00,
      "downside_value": 22.00,
      "confidence": "medium",
      "reasoning": "Strong R&D pipeline approaching Gen 2..."
    }
  ],
  "subscription_decisions": [
    {
      "firm_id": "firm_3",
      "offering_type": "ipo",
      "subscribe": true,
      "shares_subscribed": 12000000,
      "price_accepted": 15.50,
      "reasoning": "Fair pricing given early stage. Willing to take full allocation."
    }
  ],
  "market_sentiment": "cautiously_bullish"
}
```

### Output Schema (Private Mode)

```json
{
  "private_valuations": [
    {
      "firm_id": "firm_0",
      "post_money_valuation": 800000000,
      "implied_price_per_share": 16.00,
      "valuation_method": "comparable_transactions",
      "key_assumptions": {
        "revenue_multiple": 12,
        "pipeline_premium": 1.3,
        "illiquidity_discount": 0.25
      },
      "reasoning": "Comparable to Series C biotech valuations..."
    }
  ],
  "funding_decisions": [
    {
      "firm_id": "firm_2",
      "fund": true,
      "amount": 75000000,
      "valuation_pre_money": 400000000,
      "equity_stake_pct": 15.8,
      "terms": {
        "liquidation_preference": "1x_non_participating",
        "board_seat": true,
        "anti_dilution": "weighted_average"
      },
      "reasoning": "Early-stage bet on promising R&D team."
    }
  ]
}
```

---

## Agent 4: Commercial Bank (1 instance)

### Identity
- `agent_id`: `cbank_0`
- `agent_type`: `commercial_bank`

### Role
- Provides revolving credit facilities (working capital)
- Manages credit risk through commitment sizing and pricing
- Can be forced into losses if firms default (see doc 07)
- **Can itself become distressed** if cumulative losses exceed capital

### Fingerprint Dimensions
```yaml
style: "relationship-lender"   # aggressive, conservative, relationship, opportunistic
risk_appetite: 0.45
loss_tolerance: 0.05           # max tolerable loss rate
concentration_limit: 0.30      # max % of portfolio to single firm
```

### Bank Capital and Failure (see doc 07 for full details)

The commercial bank starts with a capital base (set in config, e.g., $2B).
Losses from defaults erode capital. If capital falls below a regulatory minimum
(e.g., 8% of outstanding commitments), the bank becomes constrained:
- Must reduce commitments (cannot extend new credit)
- Must raise interest rates to rebuild capital
- If capital reaches zero, the bank fails and is replaced

### What the Commercial Bank Knows

- All firms' published financial statements (per measurement regime)
- Its own loan portfolio (outstanding balances, rates, covenants, loss history)
- Macro state
- Environment narrative
- Shared past simulation database
- Default recovery rates from past simulations

### Reasoning Pipeline (unique elements)

**ANALYZE step** includes:
- Portfolio concentration analysis (exposure per firm as % of capital)
- Coverage ratio analysis per firm (EBITDA / interest, cash / debt)
- Liquidity analysis per firm (cash runway, revolver utilization)
- Historical default prediction (firms with similar metrics in past sims)
- Own capital adequacy check (current capital / total commitments)

### Output Schema

```json
{
  "revolver_terms": [
    {
      "firm_id": "firm_0",
      "commitment": 75000000,
      "rate_quarterly": 0.020,
      "maturity_quarters": 4,
      "covenants": {
        "min_cash": 20000000,
        "max_leverage": 3.0,
        "revenue_decline_trigger": -0.30
      },
      "reasoning": "Maintaining $75M facility. Firm has strong cash position..."
    }
  ],
  "own_capital_status": {
    "capital": 1850000000,
    "total_commitments": 350000000,
    "capital_ratio": 0.189,
    "status": "well_capitalized"
  }
}
```

---

## Agent 5: Credit Fund (1 instance)

### Identity
- `agent_id`: `cfund_0`
- `agent_type`: `credit_fund`

### Role
- Provides term debt (longer-duration financing for growth, capex, acquisitions)
- Prices credit risk through interest rates and structures
- Subject to same capital/failure dynamics as commercial bank (see doc 07)

### Fingerprint Dimensions
```yaml
style: "growth-capital"       # conservative, growth-capital, distressed, yield-focused
target_return: 0.10           # annual target return on deployed capital
max_single_exposure: 200000000
preferred_maturity_quarters: 12
capital_base: 3000000000      # starting capital
```

### What the Credit Fund Knows

Same as commercial bank, plus:
- Term debt outstanding per firm (balances, rates, maturities)
- Amortization schedules
- Seniority structure (its term debt vs. the commercial bank's revolver)

### Output Schema

```json
{
  "term_debt_terms": [
    {
      "firm_id": "firm_0",
      "max_new_issuance": 100000000,
      "rate_quarterly": 0.030,
      "maturity_quarters": 12,
      "seniority": "senior_secured",
      "amortization": "bullet",
      "covenants": {
        "max_total_leverage": 4.0,
        "min_interest_coverage": 2.0
      },
      "reasoning": "Offering growth capital to fund capacity expansion..."
    }
  ],
  "own_capital_status": {
    "capital": 2900000000,
    "total_deployed": 280000000,
    "unrealized_losses": 0,
    "status": "healthy"
  }
}
```

---

## Agent Lifecycle Events

### Run Start
1. Orchestrator generates fingerprints from seeded RNG
2. Orchestrator sends `POST /reset` to each agent with:
   - `config.yaml` content (agent_id, fingerprint, regime settings)
   - Shared data (world docs, past simulation summaries)
3. Each agent initializes its database and builds its system prompt

### Normal Quarter
- Orchestrator sends `POST /turn` with phase-appropriate context
- Agent runs reasoning pipeline, returns decision
- Orchestrator sends `POST /sync` with updated shared data after quarter ends

### Firm Default
- Orchestrator notifies the defaulting firm agent: "You have defaulted. Produce
  a final reflection on what went wrong."
- Orchestrator notifies financial institutions: "Firm X has defaulted. Your
  exposures are [amounts]. Recovery is [amount]."
- The firm agent for that incarnation receives `POST /reset` with new incarnation
  config (new fingerprint, clean slate, but slot history included)
- Financial institutions update their portfolios

### Financial Institution Distress
- If a bank/fund's capital falls below threshold, the orchestrator:
  1. Notifies the institution: "Your capital ratio is [X%], below [threshold].
     You must reduce exposures."
  2. Notifies firms: "Your [revolver/term debt] provider is distressed. Terms may
     tighten."
  3. If capital reaches zero: institution is replaced (new fingerprint, fresh capital)
  4. See doc 07 for full failure mechanics

### Death-Spiral Prevention (Firm Slots)
- 3 consecutive Q1 defaults: slot paused 1 quarter
- 6 consecutive failures: slot frozen permanently
- Financial institutions see slot default history in their context

### Run End
- Orchestrator sends `POST /turn` with `phase: "debrief"` to every agent
- Each agent produces a final reflection (stored in debrief.csv)
- Agents' private databases are archived for potential post-run analysis
