# Turn Protocol & Message Formats

## Quarter Lifecycle

Each quarter proceeds through 9 phases. The orchestrator controls the flow.

```
PHASE 1: Shock Generation .............. [Orchestrator, deterministic]
PHASE 2: IPO Sub-Sequence .............. [Firm -> IBank -> CBank -> CFund]
PHASE 3: Firm Decisions ................ [All 5 Firms, parallel]
PHASE 4: Feasibility Clamping .......... [Orchestrator, deterministic]
PHASE 5: Market Resolution ............. [Environment Agent]
PHASE 6: Accounting Postings ........... [Orchestrator, deterministic]
PHASE 7: Financial Institution Decisions  [IBank + CBank + CFund, parallel]
PHASE 8: Settlement & Default Check .... [Orchestrator, deterministic]
PHASE 9: Record-Keeping ................ [Orchestrator, deterministic]
```

**LLM calls occur in phases 2, 3, 5, and 7 only.** All other phases are
deterministic Python code.

---

## Phase 1: Shock Generation

**Actor**: Orchestrator (no LLM)

**Actions**:
1. Advance calendar: `quarter += 1`, compute `fyear` and `fqtr`
2. Draw macro shocks from seeded RNG:
   - Market size: `log(M_t) = mu + rho * log(M_{t-1}) + sigma * eps`
   - Risk-free rate: `r_t = r_{t-1} + sigma_r * eps_r` (bounded [0.005, 0.05])
   - Firm taste shocks: `xi_i ~ N(0, sigma_xi)` for each firm
3. Update awareness rate: `awareness_t = min(0.98, awareness_{t-1} + delta_awareness)`
4. Check and expire any active events from previous quarters
5. Determine which firm slots need IPO (new entrants, first quarter)

**Output**: Updated `MacroState`, list of slots needing IPO.

---

## Phase 2: IPO Sub-Sequence

**Actors**: New firm agent, Investment Bank, Commercial Bank, Credit Fund

Only runs for firm slots that need initial capitalization (quarter 1 of a new
incarnation). For each such slot:

### Step 2a: Firm States Capital Needs

**Prompt to firm agent**:

```json
{
  "phase": "ipo_request",
  "quarter": {"fyear": 2031, "fqtr": 1},
  "context": "You are preparing to launch your company. You have conditional ALT approval for a Gen 1 SRT product. You need to raise capital to fund operations.",
  "starting_assets": {
    "pilot_plant_capacity": 250,
    "product_generation": 1,
    "cash": 0,
    "debt": 0
  },
  "world_summary": "...",
  "slot_history": [],
  "instructions": "State how much equity you wish to raise, and how much debt you wish to request. Equity: $100M-$600M is typical for a biotech IPO. Debt: $0-$200M is typical initial credit."
}
```

**Firm response**:

```json
{
  "desired_equity_raise": 350000000,
  "desired_debt_request": 100000000,
  "business_plan_summary": "We plan to price at $95K, invest $30M/quarter in R&D, and build capacity to 1500 units over 6 quarters.",
  "reasoning": "We need 8 quarters of runway at approximately $40M/quarter burn rate."
}
```

### Step 2b: Investment Bank Prices IPO

**Prompt to investment bank**:

```json
{
  "phase": "ipo_pricing",
  "firm_id": "firm_0",
  "firm_request": {
    "desired_equity_raise": 350000000,
    "business_plan_summary": "..."
  },
  "firm_fingerprint_summary": "Growth-focused, high risk appetite, R&D-intensive",
  "slot_history": [],
  "macro": {"risk_free_rate": 0.01, "market_growth": "emerging"},
  "comparable_ipos": "Past simulation IPOs raised $150M-$500M at $1B-$3B post-money valuations"
}
```

**Investment bank response**:

```json
{
  "approved": true,
  "ipo_price_per_share": 17.50,
  "shares_offered": 20000000,
  "capital_raised": 350000000,
  "post_money_valuation": 1750000000,
  "reasoning": "Strong business plan with realistic R&D timeline. Pricing at 5x projected year-3 revenue."
}
```

### Step 2c: Commercial Bank Offers Revolver

```json
{
  "phase": "initial_credit",
  "firm_id": "firm_0",
  "post_ipo_balance_sheet": {"cash": 350000000, "equity": 350000000, "debt": 0},
  "business_plan_summary": "..."
}
```

**Response**:
```json
{
  "revolver_commitment": 50000000,
  "revolver_rate": 0.022,
  "reasoning": "Standard working capital facility for newly public biotech."
}
```

### Step 2d: Credit Fund Offers Term Debt

Similar structure, offering term debt terms.

### Step 2e: Orchestrator Books Capital

- Credits Cash for equity raised
- Credits APIC for equity raised
- Records shares outstanding
- Books any debt issued (credit Cash, debit Debt)
- Books revolver as available (not drawn)

**Validation**: After booking, `atq >= 0`, `cheq >= 0`, `atq == ltq + ceqq`.

If no capital is raised ("failed IPO"), the firm does not operate this quarter.
The slot records zero on all flow accounts.

---

## Phase 3: Firm Decisions

**Actors**: All 5 active firm agents (can run in **parallel**)

**Prompt to each firm**:

```json
{
  "phase": "quarterly_decisions",
  "quarter": {"fyear": 2031, "fqtr": 2},
  "private_state": { /* full FirmState as dict */ },
  "last_quarter_results": { /* QuarterFlows summary */ },
  "public_info": {
    "competitors": [ /* public financials for other firms */ ],
    "equity_prices": {"firm_0": 18.20, "firm_1": 15.80, ...},
    "macro": { /* MacroState */ },
    "active_events": [ /* any ongoing events */ ],
    "environment_narrative": "Last quarter saw strong initial uptake..."
  },
  "memory": {
    "short_term": [ /* last 4 quarters */ ],
    "long_term_summary": "..."
  },
  "past_simulations": "...",
  "instructions": "Submit your decisions for this quarter. Remember: total spending cannot exceed cash + available credit. Your capacity is 250 units."
}
```

**Firm response schema**:

```json
{
  "price": 92000,
  "production": 230,
  "capex": 18000000,
  "rd_spend": 28000000,
  "rd_allocation": {"product": 0.55, "process": 0.25, "delivery": 0.20},
  "sga_spend": 14000000,
  "equity_issuance_request": 0,
  "debt_request": 0,
  "dividends": 0,
  "buybacks": 0,
  "reasoning": "Slight price reduction to gain share. Heavy R&D focus on product advancement."
}
```

---

## Phase 4: Feasibility Clamping

**Actor**: Orchestrator (no LLM)

For each firm, in priority order:

```
Available = cash + expected_revenue + available_revolver + net_new_financing

1. COGS for units produced: COGS = production * unit_cost
   -> if COGS > Available: reduce production to affordable level
   -> Available -= COGS

2. Mandatory costs: Phase III trial ($10M), interest on existing debt
   -> These cannot be deferred; if insufficient, firm is flagged for default
   -> Available -= mandatory_costs

3. Taxes due: estimated from last quarter
   -> Available -= taxes

4. Discretionary spending (pro-rata if insufficient):
   - Capex (requested)
   - R&D (requested, minus mandatory $10M already counted)
   - SGA (requested)
   -> If total > Available: scale each proportionally
   -> Available -= actual_discretionary

5. Payouts (only from remaining surplus):
   - Dividends
   - Buybacks
   -> If surplus < requested: reduce or eliminate
   -> Available -= actual_payouts
```

**Output**: Actual (clamped) spending amounts for each firm.

**Logging**: If any amount was clamped, log the original request and the clamped
value for diagnostics.

---

## Phase 5: Market Resolution

**Actor**: Environment Agent (LLM)

**Prompt**:

```json
{
  "phase": "market_resolution",
  "quarter": {"fyear": 2031, "fqtr": 2},
  "macro": { /* updated MacroState with shocks */ },
  "firm_actions": [
    {
      "firm_id": "firm_0",
      "price": 92000,
      "actual_production": 230,
      "actual_rd_spend": 28000000,
      "actual_sga_spend": 14000000,
      "product_generation": 1,
      "delivery_generation": 1,
      "quality_composite": 47.2,
      "brand_capital": 33.5,
      "capacity": 250,
      "rd_cumulative_product": 53000000,
      "clinical_hold": false
    }
    // ... all 5 firms
  ],
  "market_history": [ /* last 4 quarters of market outcomes */ ],
  "active_events": [],
  "awareness_rate": 0.18,
  "demand_model_baseline": {
    "estimated_total_demand": 92000,
    "notes": "Based on multinomial logit with current prices and quality"
  },
  "instructions": "Determine market outcomes for this quarter. Total demand should be broadly consistent with the baseline estimate (within 0.5x to 2.0x). Allocate demand across firms based on price, quality, brand, and taste shocks. Determine R&D outcomes. Decide if any events occur."
}
```

**Environment response**:

```json
{
  "total_demand": 88500,
  "demand_rationale": "Slightly below baseline due to cautious physician adoption in Q2",
  "firm_outcomes": [
    {
      "firm_id": "firm_0",
      "units_sold": 19200,
      "market_share": 0.217
    },
    {
      "firm_id": "firm_1",
      "units_sold": 22100,
      "market_share": 0.250
    }
    // ...
  ],
  "rd_outcomes": [
    {
      "firm_id": "firm_0",
      "product_rd_advance": false,
      "process_cogs_reduction_pct": 0.01,
      "delivery_advance": false
    }
    // ...
  ],
  "events": [],
  "narrative": "The second quarter of commercial SRT sales showed continued growth in patient adoption. Physician referral networks are expanding, particularly in major metropolitan areas. Firm 1's lower pricing attracted the largest patient base, while Firm 0 captured the premium segment..."
}
```

**Orchestrator validation**:
- `sum(units_sold) == total_demand`
- `units_sold[i] <= actual_production[i]` for each firm
- `total_demand` in `[0.5 * baseline, 2.0 * baseline]`
- All market shares in [0, 0.6]
- Market shares sum to ~1.0
- R&D outcomes: no firm achieves a generation advance unless cumulative spend
  exceeds the minimum threshold from world docs

If validation fails: re-prompt with specific violation, up to 2 retries.
If still failing: fall back to deterministic multinomial logit calculation.

---

## Phase 6: Accounting Postings

**Actor**: Orchestrator (no LLM)

For each firm, post all entries:

```
UNIT COST COMPUTATION:
  base_cogs = generation_base_cogs * (1 - process_rd_reduction)
  capacity_utilization = actual_production / capacity
  utilization_multiplier = lookup(capacity_utilization)  // see doc 09
  effective_unit_cost = base_cogs * utilization_multiplier

INCOME STATEMENT:
  Revenue = units_sold * price
  COGS = units_sold * effective_unit_cost
  Gross Profit = Revenue - COGS
  R&D Expense = actual_rd_spend (or net of capitalization under R&D cap regime)
  SGA Expense = actual_sga_spend + workforce_cost_overrun (if above budget)
  Stock-Based Comp = stkcpq (non-cash, vesting schedule)
  Depreciation = 0.025 * ppe_gross + intangible_amortization + rou_amortization
  Goodwill Impairment = gdwlipq (if impairment test triggered, every 4Q)
  Restructuring = layoff_costs (3 months salary per laid-off employee)
  Operating Income = GP - R&D - SGA - StockComp - Depreciation - GW Impairment - Restructuring
  Non-Operating = asset_sale_gains_losses + special_items
  Interest Expense = revolver_bal * revolver_rate + ltd * term_rate + lease_interest
  Pretax Income = Operating Income + Non-Operating - Interest
  Tax Expense = max(0, (Pretax Income - NOL_usage) * 0.21)
    where NOL_usage = min(cumulative_NOL, 0.80 * Pretax Income)
  Net Income = Pretax Income - Tax Expense

BALANCE SHEET UPDATES:
  Cash: + Revenue collections (85% same Q) - COGS payments - R&D - SGA - Interest
        - Taxes - Capex - Lease payments + Equity proceeds + Debt proceeds
        - Dividends - Buybacks - Acquisition cash component
  AR: = 0.15 * Revenue (new) + prior_AR * (1 - collection_rate) - bad_debt_writeoff
  Inventory: = unsold_units * effective_unit_cost
  PPE: + Capex + ROU_additions - Depreciation
  Intangibles: + capitalized_R&D (if regime) + acquired_IP - amortization
  Goodwill: + acquisition_goodwill - impairments
  AP: = theta_AP * COGS (0.15)
  Accrued Expenses: = theta_accr * (SGA + R&D) (0.10) + wages_payable
  Taxes Payable: = current_quarter_tax (paid next Q)
  Lease Liability: + new_leases - lease_payments (principal portion)
  Provisions: + litigation_reserve_additions + warranty_additions - settlements
  Retained Earnings: += Net Income - Dividends
  Treasury Stock: += Buyback cost
  AOCI: += fair_value_adjustments (if FV regime)

CASH FLOW STATEMENT:
  CFO = Net Income + Depreciation + GW Impairment + Stock Comp (non-cash add-backs)
        + WC changes (delta AR, delta Inv, delta AP, delta Accrued, delta TaxPay)
  CFI = -Capex - Acquisition_cash + Asset_sale_proceeds
  CFF = Equity proceeds + Debt proceeds - Debt repayments - Lease principal
        - Dividends - Buybacks
  Change in Cash = CFO + CFI + CFF

WORKFORCE UPDATES:
  Headcount: += hires - layoffs - natural_attrition(0.02/quarter)
  Workforce cost: sum(headcount_by_category * cost_per_category)
  R&D effectiveness: eta_A adjusted by scientist count (see doc 09)
  Brand effectiveness: eta_B adjusted by sales staff count (see doc 09)
  Batch failure rate: adjusted by ops staff count (see doc 09)

INTERNAL STOCKS:
  Capability: A_t = (1 - 0.025) * A_{t-1} + effective_eta_A * product_rd_spend
  Brand: B_t = (1 - 0.10) * B_{t-1} + effective_eta_B * sga_spend * (eff_quality/50)
  Capacity: adjusted for capex (with build delay), leases, depreciation, aging
  Unit cost: adjusted for process R&D (exponential saturation) and generation advances
  NOL balance: += max(0, -pretax_income) - NOL_usage
  Diluted shares: basic_shares + in_the_money_options + unvested_RSUs * vesting_pct
```

**Validation after posting**: All hard invariants must hold.

---

## Phase 7: Financial Agent Decisions (4 agents)

Phase 7 is split into sub-phases. 7a is sequential (advisory before pricing);
7b/7c/7d run in parallel.

### Phase 7a: Investment Bank Advisory (sequential, only if transactions pending)

**Actor**: Investment Bank

If any firm has requested an equity issuance, IPO, or M&A deal, the IBank
structures the transaction BEFORE the Equity Market prices it.

Output: Structured offering terms (price range, share count, deal structure).
These are passed to the Equity Market in Phase 7b.

### Phase 7b: Equity Market Pricing + Subscription (parallel with 7c, 7d)

**Actor**: Equity Market

**In public mode**: Sets equity price for each public firm. If any secondary
offering or IPO was structured in 7a, decides whether to subscribe and at
what price.

**In private mode**: Sets "last-round valuation" for each private firm. If
any firm requested a funding round, decides whether to invest, at what
valuation, and with what terms.

Context received includes IBank's research (from 7a) plus all public financials,
macro state, environment narrative, own portfolio history, and past simulations.

### Phase 7c: Commercial Bank Revolver Terms (parallel with 7b, 7d)

**Actor**: Commercial Bank

Sets revolver commitment and rate for each firm. Same context as before.

### Phase 7d: Credit Fund Term Debt Terms (parallel with 7b, 7c)

**Actor**: Credit Fund

Sets term debt availability and rate for each firm. Same context as before.

### Context Sent to All Financial Agents

```json
{
  "phase": "quarterly_financial",
  "quarter": {"fyear": 2031, "fqtr": 2},
  "firm_financials": [
    {
      "firm_id": "firm_0",
      "is_public": true,
      "income_statement": { /* this quarter */ },
      "balance_sheet": { /* end of quarter */ },
      "cash_flow": { /* this quarter */ },
      "dossier_summary": { /* public portions of firm dossier */ },
      "market_share": 0.217,
      "product_generation": 1,
      "quarters_alive": 2,
      "is_active": true,
      "pending_transactions": []
    }
    // ... all active firms
  ],
  "ibank_research": { /* from Phase 7a, if available */ },
  "macro": { /* current MacroState */ },
  "environment_narrative": "...",
  "own_portfolio": { /* current exposures and returns */ },
  "memory": { /* short-term + long-term */ },
  "past_simulations": "..."
}
```

Each agent responds with its role-specific output (see Agent Specifications doc 02).

---

## Phase 8: Settlement & Default Check

**Actor**: Orchestrator (no LLM)

1. **Apply new financing terms** (update revolver commitments, rates, etc.)
2. **Process equity issuances** if approved by investment bank
3. **Process debt issuances** if approved by credit fund
4. **Draw revolver** if cash < 0 (up to commitment)
5. **Check solvency**:
   - If cash < 0 after max revolver draw -> **DEFAULT**
   - For defaulted firm:
     a. Run bankruptcy auction (apply recovery haircuts to assets)
     b. Pay claims in waterfall: revolver -> term debt -> AP/accrued/taxes
     c. Residual (if any) to equity
     d. Mark firm as inactive
     e. Queue fresh entrant for next quarter
     f. Update death-spiral tracker

---

## Phase 9: Record-Keeping

**Actor**: Orchestrator (no LLM)

1. Write firm-quarter row to Compustat panel
2. Update market memory (public events)
3. Update each firm's private memory
4. Update each institution's portfolio memory
5. Write quarterly statements to disk
6. Save checkpoint (full state serialization)
7. Run hard invariant checks
8. Log diagnostics

---

## JSON Schema Definitions

### Firm Decision Schema

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "required": ["price", "production", "capex", "rd_spend", "rd_allocation", "sga_spend"],
  "properties": {
    "price": {"type": "number", "minimum": 0},
    "production": {"type": "integer", "minimum": 0},
    "capex": {"type": "number", "minimum": 0},
    "rd_spend": {"type": "number", "minimum": 0},
    "rd_allocation": {
      "type": "object",
      "required": ["product", "process", "delivery"],
      "properties": {
        "product": {"type": "number", "minimum": 0, "maximum": 1},
        "process": {"type": "number", "minimum": 0, "maximum": 1},
        "delivery": {"type": "number", "minimum": 0, "maximum": 1}
      }
    },
    "sga_spend": {"type": "number", "minimum": 0},
    "equity_issuance_request": {"type": "number", "minimum": 0, "default": 0},
    "debt_request": {"type": "number", "minimum": 0, "default": 0},
    "dividends": {"type": "number", "minimum": 0, "default": 0},
    "buybacks": {"type": "number", "minimum": 0, "default": 0},
    "reasoning": {"type": "string"}
  }
}
```

### Environment Outcome Schema

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "required": ["total_demand", "firm_outcomes", "rd_outcomes", "narrative"],
  "properties": {
    "total_demand": {"type": "integer", "minimum": 0},
    "firm_outcomes": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["firm_id", "units_sold", "market_share"],
        "properties": {
          "firm_id": {"type": "string"},
          "units_sold": {"type": "integer", "minimum": 0},
          "market_share": {"type": "number", "minimum": 0, "maximum": 1}
        }
      }
    },
    "rd_outcomes": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["firm_id"],
        "properties": {
          "firm_id": {"type": "string"},
          "product_rd_advance": {"type": "boolean"},
          "process_cogs_reduction_pct": {"type": "number"},
          "delivery_advance": {"type": "boolean"}
        }
      }
    },
    "events": {"type": "array"},
    "narrative": {"type": "string"}
  }
}
```

---

## Error Recovery

### LLM Timeout or Crash

| Phase | Fallback Behavior |
|-------|------------------|
| Phase 2 (IPO) | Use median IPO size from world docs ($250M equity) |
| Phase 3 (Firm) | Repeat last quarter's decisions with 5% across-the-board cut |
| Phase 5 (Environment) | Fall back to deterministic multinomial logit demand model |
| Phase 7 (Financial) | Hold terms unchanged from previous quarter |

### Invalid JSON

1. Attempt to extract first `{...}` block from response
2. Re-prompt with: "Your response was not valid JSON. Here is the error: [error].
   Here is your response: [response]. Please provide valid JSON."
3. After 2 retries: use fallback

### Out-of-Range Values

Don't re-prompt -- silently clamp and log:
- Negative prices -> 0
- Production > capacity -> capacity
- Spending > available -> clamped in Phase 4
- Market share > 0.6 -> redistribute excess proportionally
