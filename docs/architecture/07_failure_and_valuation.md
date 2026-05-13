# Failure Mechanics and Equity Valuation

## Overview

This document covers three critical systems:
1. **Firm bankruptcy** -- when and how firms fail, asset auction, creditor waterfall
2. **Financial institution distress** -- when banks/funds lose too much, capital erosion, replacement
3. **Equity valuation** -- how the investment bank reasons about firm value to set prices that are defensible given potential future cash flows

---

## Part 1: Firm Bankruptcy

### When a Firm Defaults

A firm defaults when, after all revenue collections, financing proceeds, and
revolver draws, its cash balance is still negative. The orchestrator checks this
in Phase 8 (Settlement).

```
End-of-quarter cash =
    Beginning cash
  + Revenue collections (cash from sales)
  + Equity issuance proceeds
  + New debt proceeds
  + Revolver draw (up to remaining commitment)
  - COGS payments
  - R&D payments
  - SGA payments
  - Interest on all debt
  - Tax payments
  - Capex
  - Dividends
  - Buybacks

If end-of-quarter cash < 0 after maximum revolver draw:
    -> FIRM DEFAULTS
```

### Bankruptcy Auction

When a firm defaults, its assets are sold at auction with **recovery haircuts**
reflecting the difficulty of liquidating specialized pharmaceutical assets.

| Asset | Book Value Source | Recovery Rate | Rationale |
|-------|------------------|---------------|-----------|
| Cash | cheq (if any positive) | 100% | Cash is cash |
| Accounts receivable | rectq | 80% | Some patients won't pay; collection costs |
| Inventory | invtq | 40-60% | Specialized product; cold chain; limited buyers |
| PP&E | ppentq | 30-50% | Specialized facilities; few buyers; relocation cost |
| Capitalized R&D | intangible (if any) | 10-30% | IP has value but is hard to transfer |
| Brand/goodwill | 0 | 0% | Brand dies with the firm |

Recovery rates are drawn from a distribution (mean = table above, std = 10%)
using the seeded RNG. This introduces uncertainty into creditor recoveries.

```
Total auction proceeds =
    sum(asset_i * recovery_rate_i) for all asset categories
```

### Creditor Waterfall

Auction proceeds are distributed in strict priority:

```
PRIORITY 1: Administrative costs (5% of gross proceeds)
   -> Taken off the top
   |
PRIORITY 2: Secured revolver (commercial bank)
   -> Paid in full if proceeds sufficient
   -> If not, receives pro-rata share
   |
PRIORITY 3: Secured term debt (credit fund)
   -> Paid from remaining proceeds
   -> If not fully covered, records a loss
   |
PRIORITY 4: Unsecured claims
   - Accounts payable (suppliers)
   - Accrued expenses (employees, other)
   - Taxes payable (government)
   -> Pro-rata among these three if insufficient
   |
PRIORITY 5: Equity (residual)
   -> Shareholders get whatever is left (usually zero)
```

### Information Flow on Default

When a firm defaults, the orchestrator notifies:

| Recipient | What they learn |
|-----------|----------------|
| All firms | "Firm X has defaulted." (public knowledge) |
| Commercial bank | Exact revolver exposure, recovery amount, loss amount |
| Credit fund | Exact term debt exposure, recovery amount, loss amount |
| Investment bank | Equity is worthless. Pricing error for final quarter. |
| Environment | Full default details (for narrative generation) |

### The Default Quarter Row

The Compustat panel records one final row for the defaulted firm:
- `default_flag = 1`
- `cheq` may be negative (the cash deficit that triggered default)
- `atq` reflects pre-auction book values
- All flow accounts (revenue, COGS, etc.) reflect the partial quarter of operations
- This row is marked as a "default row" and excluded from certain validation checks
  (e.g., `cheq >= 0` is not enforced for default rows)

### Fresh Entry After Default

The firm slot receives a new entrant next quarter:
- New fingerprint (drawn from seeded RNG)
- Clean balance sheet (zero everything)
- Must go through IPO sub-sequence (Phase 2) before operating
- Incarnation counter increments
- Slot history (number of prior defaults) is visible to financial institutions

### Death-Spiral Prevention

If a slot experiences repeated rapid failures:

| Condition | Action |
|-----------|--------|
| 3 consecutive incarnations default in Q1 | Slot paused for 1 quarter (no entry) |
| After pause, next incarnation defaults in Q1 | Slot paused for 2 quarters |
| 6 total consecutive Q1 defaults | Slot frozen permanently; logged as diagnostic warning |

**During a pause**, the industry operates with I-1 active firms. The macro demand
does not shrink -- remaining firms absorb the "missing" firm's potential share.

**On re-entry after a pause**, the financial institutions see:
- The slot's full default history
- A flag indicating this is a "high-risk slot"
- They may choose to offer lower capitalization, tighter terms, or refuse entirely

---

## Part 2: Financial Institution Failure

### Why Banks Can Fail

Financial institutions have limited capital. Losses from firm defaults erode that
capital. If too many firms default (or one very large exposure goes bad), the
institution may become distressed or fail.

This creates a **systemic risk** channel: firm defaults cause bank losses, which
tighten credit for surviving firms, which may cause more defaults.

### Capital Structure of Financial Institutions

Each financial institution starts with a capital base set in config:

```yaml
financial_institutions:
  investment_bank:
    starting_capital: 5000000000    # $5B
    min_capital_ratio: 0.05         # 5% of AUM
  commercial_bank:
    starting_capital: 2000000000    # $2B
    min_capital_ratio: 0.08         # 8% of total commitments
    max_single_exposure: 0.25       # 25% of capital to one firm
  credit_fund:
    starting_capital: 3000000000    # $3B
    min_capital_ratio: 0.10         # 10% of total deployed
    max_single_exposure: 0.20       # 20% of capital to one firm
```

### Capital Dynamics

Each quarter, institution capital changes:

```
Capital_t = Capital_{t-1}
          + Interest income (from performing loans)
          + Fee income (commitment fees, underwriting fees)
          - Operating expenses (fixed, ~1% of capital annually)
          - Credit losses (principal not recovered from defaults)
          - Writedowns (mark-to-market on impaired loans, if applicable)
```

### Distress Thresholds

| Capital Ratio | Status | Effect |
|--------------|--------|--------|
| > 2x minimum | Well-capitalized | Normal operations |
| 1x - 2x minimum | Adequately capitalized | Mild caution; may tighten terms |
| 0.5x - 1x minimum | **Undercapitalized** | Must reduce exposures; cannot extend new commitments; must raise rates |
| 0 - 0.5x minimum | **Critically undercapitalized** | Existing commitments honored but at maximum rates; no new business |
| <= 0 | **Failed** | Institution is shut down and replaced |

### What Happens When a Bank Becomes Undercapitalized

The orchestrator enforces constraints on undercapitalized institutions:

1. **Commitment cap**: Cannot increase total commitments above current level
2. **Rate floor**: Must charge at least risk-free + 500bps (penalty rate)
3. **Concentration limit halved**: Max single-firm exposure reduced
4. **Notification**: All agents are told "[institution] is undercapitalized"
5. **Recovery plan**: The institution's LLM receives: "Your capital ratio is [X%].
   You must rebuild capital by tightening terms and reducing exposures."

The institution agent still makes its own decisions within these constraints.
It may choose WHICH firms to cut credit to, and by how much.

### What Happens When a Bank Fails

If capital reaches zero:

1. **Existing loans become orphaned**: The orchestrator assumes the role of
   "resolution authority"
   - Revolvers (commercial bank): converted to term debt at last known rate,
     no further draws available
   - Term debt (credit fund): continues at current terms but no new issuance
   - Equity coverage (investment bank): prices frozen at last quarter; a
     "replacement" institution takes over next quarter

2. **Replacement institution**: A new agent is created with:
   - Fresh capital (same as starting config)
   - New fingerprint
   - Knowledge of predecessor's failure (in system prompt)
   - The failed institution's loan book (inherits at face value)

3. **Market impact**: The orchestrator generates a shock:
   - Credit tightening: all surviving institutions raise rates by 100-200bps
     for 2 quarters (systemic stress)
   - Equity sell-off: investment bank marks all equity prices down 10-15%
     (flight to safety)
   - Environment narrative describes the institutional failure

### The Investment Bank Is Special

The investment bank's "capital" is more like "assets under management" (AUM) --
it doesn't lend money directly. Its failure mode is different:

- **Revenue**: Underwriting fees (% of IPO/secondary proceeds) + advisory fees
- **Losses**: Reputational -- if its pricing is consistently wrong, it loses
  credibility (modeled as reduced influence on market prices)
- **Capital erosion**: If it underwrites IPOs at prices that turn out to be
  wildly wrong (e.g., IPO at $20, firm defaults 2 quarters later), it suffers
  "credibility losses"
- **Failure**: If cumulative credibility losses exceed a threshold, the investment
  bank is replaced (its pricing is no longer trusted by the market)

In practice, the investment bank is less likely to fail than the lending
institutions, since it doesn't bear direct credit risk.

---

## Part 3: Equity Valuation

### The Problem

The investment bank must set an equity price for each firm every quarter.
This price must be **reasonable given the potential for future cash flows** --
not arbitrary, not purely formulaic, but grounded in economic reasoning.

This is the hardest intellectual task in the simulation. The investment bank
must think about:
- What the firm is earning now
- What it COULD earn in the future (depends on R&D, market growth, competition)
- What risks could derail that future (default, clinical hold, competitive entry)
- What discount rate is appropriate given those risks
- What comparable firms in past simulations were valued at

### The Valuation Reasoning Framework

The investment bank's reasoning pipeline for equity pricing includes dedicated
analytical and reasoning steps:

#### Step A: Current Financial Analysis (statistical)

Run on the published financial statements:
```
- Revenue and revenue growth rate (trailing 4 quarters)
- Gross margin, operating margin, net margin trajectory
- Cash balance and cash burn/generation rate
- Debt levels and interest coverage
- Market share and market share trend
- R&D spending level (total; allocation not visible)
```

#### Step B: Forward Projection (LLM reasoning)

The LLM is prompted to think through future scenarios:

```
"Based on Firm X's current financials and competitive position, project
their performance under three scenarios:

BASE CASE (50% probability):
- What revenue growth do you expect over the next 4, 8, 12 quarters?
- What margins are achievable?
- When (if ever) does the firm achieve positive free cash flow?
- What is the terminal value at quarter 80 (or at the end of the projection)?

UPSIDE CASE (25% probability):
- R&D succeeds faster than expected
- Market grows faster
- Competitor stumbles

DOWNSIDE CASE (25% probability):
- R&D delayed
- Clinical hold or safety event
- Aggressive price competition

For each case, estimate annual free cash flow in years 1-5 and terminal value."
```

#### Step C: DCF Computation (statistical)

Using the LLM's projections, compute:
```
Discount rate = risk-free rate + equity risk premium
  (equity risk premium depends on firm stage: 8-15% for early biotech)

Firm value = sum(FCF_t / (1+r)^t) + Terminal_value / (1+r)^T

Weighted value = 0.50 * base_value + 0.25 * upside_value + 0.25 * downside_value

Equity value = Firm value - Net debt

Price per share = Equity value / Shares outstanding
```

#### Step D: Cross-Check (LLM reasoning)

The LLM is prompted to sanity-check the DCF result:

```
"Your DCF analysis suggests a price of $X per share for Firm Y.

Cross-check against:
1. Revenue multiple: Current revenue * [peer multiple] / shares = $___
2. Past simulations: Firms at similar stage were priced at $___
3. Last quarter's price: $___. The change from last quarter is ___%.
   Is this change justified by new information?

If the cross-checks suggest your DCF is too high or too low, adjust
and explain why."
```

#### Step E: Final Price (LLM decision)

The LLM sets the price with full justification:

```
"Set your price for Firm Y. Include:
- The price per share
- The key assumptions driving the valuation
- The biggest risk to the valuation
- Your confidence level (high/medium/low)
- A target price for 4 quarters ahead"
```

### Pricing Constraints (Orchestrator Enforced)

To prevent wildly unreasonable prices:

| Constraint | Rule | Rationale |
|-----------|------|-----------|
| Price >= 0 | Always | Cannot be negative |
| Price change < 50% per quarter | Soft (override with justification) | Prevents extreme volatility |
| Price > 0 for non-defaulted firms | Always | A living firm has some option value |
| Price = 0 for defaulted firms | Always | Equity is worthless |
| Market cap < 100x revenue | Soft warning | Absurdly high multiple |
| Market cap > 0.1x cash | Soft warning | Priced below liquidation value |

**Soft constraints**: The orchestrator flags these but does not override. The
pricing error will be measured in the debrief.

### Measuring Pricing Quality

The debrief computes pricing accuracy for the investment bank:

**Ex-post rational price** (computed after the simulation):
```
P_star_t = (Dividends_{t+1} + P_{t+1}) / (1 + r_f / 4)
```
Where `P_{t+1}` is next quarter's actual price (or liquidation value if default).

**Pricing error**:
```
error_t = P_t - P_star_t
```

**Aggregate metrics**:
- RMSE of pricing errors across all firm-quarters
- Mean bias (positive = overvaluation, negative = undervaluation)
- Correlation between P_t and P_star_t
- MAPE (mean absolute percentage error)
- By-firm breakdown (is the bank consistently wrong about one firm?)
- By-stage breakdown (worse at pricing early-stage vs. mature firms?)

### Why This Matters

Equity prices affect the simulation through multiple channels:

1. **IPO pricing**: Determines how much capital new firms raise. Overpricing
   means firms are overcapitalized (wasteful); underpricing means undercapitalized
   (fragile).

2. **Secondary offerings**: Firms may issue equity at the prevailing price.
   Overpriced equity = cheap capital = encourages dilutive growth.

3. **Market signal**: Equity price signals the market's assessment of the firm.
   Competitors and institutions observe prices and adjust behavior.

4. **Debrief measurement**: Equity IRR for investors depends on the entry price
   (IPO) and exit price (terminal or default). Mispricing distorts measured returns.

5. **Behavioral feedback**: Firm agents can observe their own stock price. A
   declining price may cause a firm to cut costs or raise capital; a rising price
   may encourage risk-taking.

---

## Interaction: Firm Default -> Bank Stress -> Credit Tightening

The most interesting dynamic is the potential for cascading failures:

```
Firm A defaults (loses money, cash goes negative)
  |
  v
Commercial bank loses $50M on Firm A's revolver
Credit fund loses $80M on Firm A's term debt
  |
  v
Commercial bank capital ratio drops from 15% to 12%
Credit fund capital ratio drops from 18% to 14%
  |
  v
Both institutions tighten credit terms for surviving firms:
  - Reduced commitments
  - Higher rates
  - Stricter covenants
  |
  v
Firm B, which was relying on revolver draws for cash management,
finds its revolver reduced. It must cut spending.
  |
  v
Firm B's reduced spending -> lower revenue -> possible default
  |
  v
If Firm B defaults, the banks take another loss...
```

This cascading dynamic is emergent -- it is NOT hardcoded. It arises naturally
from the agents' rational responses to losses and risk.

The orchestrator's role is to:
- Track institutional capital accurately
- Enforce capital ratio constraints
- Notify agents of relevant developments
- NOT prevent cascades (they are economically realistic)

---

## Configuration Parameters

```yaml
# Firm bankruptcy
bankruptcy:
  recovery_rates:
    cash: 1.00
    accounts_receivable: 0.80
    inventory: 0.50
    ppe: 0.40
    intangibles: 0.20
  recovery_rate_std: 0.10        # randomness in recovery
  admin_cost_pct: 0.05           # off the top
  death_spiral_max_consecutive: 3
  death_spiral_freeze_after: 6

# Financial institution capital
institutions:
  commercial_bank:
    starting_capital: 2000000000
    min_capital_ratio: 0.08
    max_single_exposure_pct: 0.25
    operating_cost_annual_pct: 0.01
    fee_income_pct_of_commitments: 0.005  # quarterly
  credit_fund:
    starting_capital: 3000000000
    min_capital_ratio: 0.10
    max_single_exposure_pct: 0.20
    operating_cost_annual_pct: 0.01
    fee_income_pct_of_deployed: 0.003
  investment_bank:
    starting_capital: 5000000000
    min_capital_ratio: 0.05
    credibility_loss_threshold: 0.30   # cumulative MAPE before replacement
    underwriting_fee_pct: 0.05

# Equity valuation constraints
valuation:
  max_quarterly_price_change: 0.50     # 50% max change per quarter (soft)
  max_revenue_multiple: 100            # warning threshold
  min_cash_multiple: 0.1               # warning threshold
  equity_risk_premium_range: [0.08, 0.15]  # for DCF guidance
```
