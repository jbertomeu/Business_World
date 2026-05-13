# Configurable Regimes: Information and Measurement

## Why This Matters

A central goal of the simulation is to study how **information structure** and
**accounting rules** affect firm behavior, market outcomes, and financial stability.
By varying these regimes across runs, we can answer questions like:

- Does more disclosure lead to better equity pricing?
- Does R&D capitalization change how much firms invest in R&D?
- Does hiding cash flow details make credit markets less efficient?
- Do firms behave differently when they know competitors can see their margins?

Both regimes are **parameters of the orchestrator** set in `config.yaml`. Agents
do not choose what to disclose -- the orchestrator filters information before
sending it.

---

## Information Regime

### What It Controls

The information regime specifies, for each agent type, which fields from other
agents' data are visible. It is a **filter matrix**: rows are observer types,
columns are data fields.

### Configuration Format

```yaml
information_regime: "baseline"
# OR specify custom:
information_regime:
  name: "custom_asymmetric"
  firms_see:
    competitor_fields: ["saleq", "niq", "atq", "ltq", "ceqq", "prccq", "cshoq"]
    competitor_ratios: ["gross_margin", "debt_equity"]
    macro: true
    environment_narrative: true
    equity_prices: true
    credit_terms_of_others: false
    competitor_rd_spend_total: true
    competitor_rd_allocation: false
    competitor_capacity: false
    competitor_unit_cost: false
  financial_institutions_see:
    firm_fields: ["saleq", "cogsq", "gpq", "xrdq", "xsgaq", "niq",
                  "cheq", "atq", "ltq", "ceqq", "dlcq", "dlttq",
                  "oancfq", "ivncfq", "fincfq", "capxq"]
    firm_ratios: ["gross_margin", "operating_margin", "debt_equity",
                  "current_ratio", "interest_coverage"]
    firm_capacity: false
    firm_unit_cost: false
    firm_rd_allocation: false
    firm_internal_stocks: false
    other_institution_terms: false
    macro: true
    environment_narrative: true
  environment_sees:
    all_firm_actions: true
    all_firm_private_state: true
    all_institution_portfolios: true
    macro: true
```

### Preset Regimes

#### 1. `baseline` (default)

The standard information structure. Reflects roughly what public markets provide.

| Observer | Sees | Does Not See |
|----------|------|-------------|
| Firms | Competitors' summary financials (revenue, net income, total assets, equity, debt, equity price). Macro. Narrative. Past simulations. | Competitors' COGS detail, unit cost, R&D allocation, internal stocks. Other firms' credit terms. |
| Investment Bank | All firms' full published statements. Macro. Narrative. Own pricing history. Past simulations. | Internal stocks, R&D allocation, unit costs. Other institutions' terms. |
| Commercial Bank | All firms' full published statements. Macro. Narrative. Own loan portfolio. Past simulations. | Internal stocks, R&D allocation. Other institutions' portfolios. |
| Credit Fund | Same as commercial bank. | Same as commercial bank. |
| Environment | Everything (god-mode). | Nothing hidden. |

#### 2. `full_transparency`

Everyone sees everything. Useful as a benchmark.

| Observer | Sees |
|----------|------|
| All agents | All firms' complete state (including internal stocks, unit cost, R&D allocation, capacity). All institutions' portfolios and terms. Full macro. Full narrative. |

#### 3. `minimal_disclosure`

Firms disclose almost nothing. Tests whether markets can function with scarce info.

| Observer | Sees |
|----------|------|
| Firms | Only competitors' revenue and equity price. Macro. Narrative. |
| Financial institutions | Only revenue, net income, cash, total debt for each firm. |
| Environment | Everything. |

#### 4. `asymmetric_banks`

Banks see more than equity investors. Tests information advantage of lenders.

| Observer | Sees |
|----------|------|
| Investment Bank | Revenue, net income, total assets, equity only (like a public investor). |
| Commercial Bank | Full financial statements + cash flow + capacity utilization (like a relationship lender with covenants). |
| Credit Fund | Same as commercial bank. |
| Firms | Baseline. |

#### 5. `competitor_intelligence`

Firms can see more about each other. Tests strategic interaction effects.

| Observer | Sees extra (vs. baseline) |
|----------|-------------------------|
| Firms | Competitors' capacity, total R&D spend, capex (but not R&D allocation or unit cost). |
| Financial institutions | Baseline. |

### How Filtering Works

The orchestrator maintains the FULL state of every agent. When constructing the
context for a turn prompt, it:

1. Starts with the full state
2. Applies the information regime filter for the observer's type
3. Removes all fields not in the allowed set
4. Computes any allowed derived ratios
5. Sends the filtered context to the agent

**Important**: The agent never knows what it cannot see. It does not receive
empty fields -- the fields simply do not appear in the prompt. The agent cannot
infer what is being hidden.

### How Agents Handle Missing Information

Agents are prompted to work with whatever information they have:

- "Base your decisions on the information provided. If you do not have
  competitor cost data, estimate it from their pricing and margins."
- "If you do not know a firm's capacity, infer it from their production
  volume (production cannot exceed capacity)."

This makes the simulation more realistic -- real firms must also estimate
hidden competitor information.

---

## Measurement Regime

### What It Controls

The measurement regime specifies HOW financial statements are constructed from
the underlying economic transactions. Different accounting rules produce different
numbers from the same economic reality.

This affects:
- What numbers appear on the income statement, balance sheet, and cash flow statement
- How R&D, assets, and liabilities are valued
- What ratios and metrics agents compute from financial statements
- How the investment bank prices equity (different statements -> different valuations)

### Configuration Format

```yaml
measurement_regime: "baseline_gaap"
# OR specify custom:
measurement_regime:
  name: "custom_mixed"
  rd_treatment: "expense"          # "expense" | "capitalize_partial" | "capitalize_full"
  rd_capitalization_rate: 0.0      # fraction of R&D capitalized (if capitalize_*)
  rd_amortization_quarters: 12     # amortization period for capitalized R&D
  asset_valuation: "historical"    # "historical" | "fair_value" | "lower_of_cost_or_market"
  fair_value_noise_std: 0.0        # std dev of noise added to fair value estimates
  revenue_recognition: "accrual"   # "accrual" | "cash"
  expense_recognition: "accrual"   # "accrual" | "cash"
  inventory_method: "fifo"         # "fifo" | "lifo" | "weighted_average"
  depreciation_method: "straight_line"  # "straight_line" | "accelerated"
  goodwill_treatment: "none"       # "none" | "amortize" | "impair_test"
  disclosure_level: "full"         # "full" | "summary" | "minimal"
```

### Preset Regimes

#### 1. `baseline_gaap` (default)

Standard accrual accounting. R&D expensed. Historical cost.

```yaml
rd_treatment: "expense"
asset_valuation: "historical"
revenue_recognition: "accrual"
expense_recognition: "accrual"
inventory_method: "fifo"
depreciation_method: "straight_line"
disclosure_level: "full"
```

**Effect on statements**:
- R&D appears as a line item on IS (xrdq), reducing operating income
- PPE carried at cost minus accumulated depreciation
- Accounts receivable and payable reflect accrual timing
- Full IS + BS + CF + SOE disclosed (subject to information regime filtering)

#### 2. `rd_capitalization`

60% of R&D spending is capitalized as an intangible asset and amortized.

```yaml
rd_treatment: "capitalize_partial"
rd_capitalization_rate: 0.60
rd_amortization_quarters: 12
# Everything else same as baseline_gaap
```

**Effect on statements**:
- R&D expense on IS is only 40% of actual spending
- Remaining 60% appears as "capitalized R&D" on BS (intangible asset)
- Amortization of capitalized R&D flows through IS over 12 quarters
- **Net income is higher in heavy-R&D periods** (expense is deferred)
- **Total assets are higher** (intangible asset on BS)
- **This changes equity pricing** -- the investment bank sees higher earnings
  and assets, potentially leading to higher valuations for R&D-heavy firms
- **This may change firm behavior** -- if firms know R&D is capitalized, they
  may invest more (reported earnings are less penalized)

#### 3. `fair_value_assets`

PPE and inventory marked to (noisy) fair value each quarter.

```yaml
asset_valuation: "fair_value"
fair_value_noise_std: 0.10    # 10% noise around "true" value
# Everything else same as baseline_gaap
```

**Effect on statements**:
- PPE and inventory revalued each quarter
- Gains/losses flow through other comprehensive income (OCI) or IS
- **Balance sheet is more volatile** but potentially more informative
- **Noise introduces uncertainty** -- fair value is estimated, not exact
- Investment bank must decide how much weight to give noisy fair values

#### 4. `cash_basis`

No accruals. Revenue recognized when cash received. Expenses when cash paid.

```yaml
revenue_recognition: "cash"
expense_recognition: "cash"
# No AR, no AP, no accrued expenses
```

**Effect on statements**:
- No accounts receivable or payable on balance sheet
- Revenue = cash collections (lagged vs. accrual)
- Expenses = cash payments
- **IS is more volatile** (timing of cash flows != timing of economic activity)
- **Simpler balance sheet** but potentially misleading about economic reality

#### 5. `minimal_disclosure`

Firms report only summary numbers. Fewer line items on statements.

```yaml
disclosure_level: "minimal"
# Income statement: only revenue, operating_income, net_income
# Balance sheet: only total_assets, total_liabilities, total_equity, cash
# Cash flow: only total change_in_cash
# No component breakdowns
```

**Effect**: Financial institutions and competitors have less data to analyze.
Credit underwriting becomes harder. Equity pricing becomes noisier.

#### 6. `expanded_disclosure`

Firms report additional operational metrics beyond financial statements.

```yaml
disclosure_level: "expanded"
# Everything in baseline_gaap, PLUS:
# - Capacity utilization (%)
# - R&D spending by program (product/process/delivery)
# - Product generation
# - Backlog / unfilled orders
# - Employee count (proxy for scale)
```

**Effect**: More information available to all observers. May improve equity
pricing accuracy and credit underwriting.

### How Measurement Regimes Are Applied

The orchestrator applies the measurement regime when **computing financial
statements** from the underlying economic data:

```
Underlying Economic Reality
  (transactions, stocks, flows -- maintained by orchestrator)
         |
         v
    [Measurement Regime]
    Apply accounting rules:
    - Capitalize or expense R&D?
    - Historical cost or fair value?
    - Accrual or cash basis?
    - What level of disclosure?
         |
         v
Published Financial Statements
  (what agents see, subject to information regime filtering)
```

**The underlying economic reality is always the same.** Only the REPORTING differs.
This means:
- The orchestrator tracks both the "true" economic state AND the reported state
- Feasibility clamping and solvency checks use the TRUE state (real cash, real debt)
- Agent decisions are based on the REPORTED state (what they see on statements)
- Equity pricing is based on REPORTED financials
- But defaults are triggered by REAL cash positions

This creates a natural tension: if the measurement regime makes firms look
healthier than they are (e.g., R&D capitalization inflates assets), the market
may misprice equity and extend too much credit -- until reality catches up.

---

## Combining Information and Measurement Regimes

The two regimes are orthogonal and can be combined freely:

| Combination | What It Tests |
|-------------|--------------|
| baseline info + baseline GAAP | Standard modern capital market |
| baseline info + R&D capitalization | Does capitalizing R&D improve investment efficiency? |
| minimal info + baseline GAAP | Can markets function with limited disclosure? |
| full transparency + baseline GAAP | Does more info improve outcomes? (benchmark) |
| baseline info + minimal disclosure | Double opacity -- limited fields AND limited line items |
| asymmetric banks + expanded disclosure | Banks as informed lenders -- does it reduce defaults? |

### Experimental Design

A typical experimental run plan:

```yaml
experiments:
  - name: "baseline"
    information_regime: "baseline"
    measurement_regime: "baseline_gaap"
    n_runs: 5
    seeds: [1, 2, 3, 4, 5]

  - name: "rd_capitalization_effect"
    information_regime: "baseline"
    measurement_regime: "rd_capitalization"
    n_runs: 5
    seeds: [1, 2, 3, 4, 5]    # same seeds for comparability

  - name: "transparency_effect"
    information_regime: "full_transparency"
    measurement_regime: "baseline_gaap"
    n_runs: 5
    seeds: [1, 2, 3, 4, 5]
```

By holding seeds constant across experiments, the exogenous shocks are identical,
and differences in outcomes are attributable to the regime change.

---

## Implementation Notes

### Where Regime Logic Lives

- **Information regime**: Applied in the orchestrator's prompt builder.
  A `filter_context(full_state, observer_type, info_regime)` function strips
  fields before sending to agents.

- **Measurement regime**: Applied in the orchestrator's accounting module.
  A `build_statements(economic_state, measurement_regime)` function produces
  the published financial statements.

### Adding New Regimes

To add a new regime:
1. Define it in `config/regimes/` as a YAML file
2. Implement any new accounting logic in `accounting/postings.py`
3. The filter and statement builder read the regime config dynamically
4. No changes needed to agent code -- agents just see different data

### Regime Is Fixed Within a Run

The information and measurement regimes are set at run start and do not change
during the run. (A future extension could model regime changes -- e.g., a
regulatory mandate to capitalize R&D mid-simulation.)
