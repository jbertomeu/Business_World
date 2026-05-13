# Parameters and Calibration: The Numeric Foundation

## Purpose

This document is the **single source of truth** for every numeric parameter in
the simulation. When other documents reference a number, this is where the
canonical value lives. Agents do not need to memorize these -- the orchestrator
uses them internally -- but they provide grounding for what "reasonable" looks like.

---

## Demand System Parameters

### Multinomial Logit Utility

```
U_i = a * quality_i - b * price_i + g * brand_i + xi_i + eps_i
U_0 = V_0(t) + macro_shock + eps_0    (outside option)
```

| Parameter | Symbol | Value | Units | Notes |
|-----------|--------|-------|-------|-------|
| Price coefficient | b | 0.000015 | per dollar | Higher price -> lower utility |
| Quality coefficient | a | 1.0 | per quality point | Normalized to 1.0 |
| Brand coefficient | g | 0.4 | per brand point | Brand matters, less than quality |
| Outside option base (Q1 2031) | V_0(0) | 3.5 | utility units | High = most people choose "do nothing" |
| Outside option decay rate | lambda_V0 | 0.03/quarter | per quarter | As awareness grows, barrier falls |
| Outside option floor | V_0_min | 0.5 | utility units | Some people will never adopt |
| Logit scale parameter | mu | 1.0 | -- | Standard normalization |
| Macro demand shock std dev | sigma_macro | 0.08 | -- | ~+-16% in extreme quarters |
| Firm taste shock std dev | sigma_xi | 0.05 | -- | ~+-10% firm-specific variation |

### Potential Market Size

| Parameter | Value | Units |
|-----------|-------|-------|
| Base potential patients (Q1 2031) | 600,000,000 | adults 50+ in high-income countries |
| Initial awareness rate | 0.15 | fraction who know SRT exists |
| Awareness growth (natural) | 0.02/quarter | per quarter, additive |
| Awareness growth (per $1M SGA industry-wide) | 0.001 | per quarter per $1M |
| Awareness ceiling | 0.98 | maximum awareness |

### Safety-Adjusted Demand Modifier

The serious adverse event rate adjusts the effective quality score:

| Serious AE Rate | Quality Multiplier | Interpretation |
|-----------------|-------------------|----------------|
| > 5% | 0.5x | "Experimental, risky" -- halves perceived quality |
| 3-5% | 0.7x | "Promising but dangerous" |
| 1-3% | 1.0x | "Acceptable for high-value therapy" (baseline) |
| 0.5-1% | 1.3x | "Safe enough for broader adoption" |
| < 0.5% | 2.0x | "Routine medical procedure" |
| < 0.1% | 3.0x | "Over-the-counter safe" |

This multiplier is applied to the quality_score before entering the logit:
```
effective_quality_i = quality_score_i * ae_demand_modifier(serious_ae_rate_i)
```

---

## Quality Composite Score

```
quality_score = w_eff(t) * efficacy_index + w_saf(t) * safety_index + w_con(t) * convenience_index
```

### Component Indices (0-100 scale)

| Component | Gen 1 | Gen 2 | Gen 3 | Gen 4 | Calculation |
|-----------|-------|-------|-------|-------|-------------|
| Efficacy index | 35 | 55 | 75 | 90 | 4 * epigenetic_age_reversal_years |
| Safety index | 27 | 75 | 95 | 98 | 100 * (1 - serious_ae_rate / 0.10) |
| Convenience index | 20 | 50 | 80 | 95 | Lookup by delivery method |

### Time-Varying Weights

| Period | w_eff | w_saf | w_con | Rationale |
|--------|-------|-------|-------|-----------|
| Years 1-3 (Q1-Q12) | 0.50 | 0.30 | 0.20 | Early adopters care most about "does it work?" |
| Years 4-7 (Q13-Q28) | 0.35 | 0.40 | 0.25 | Safety becomes key as market broadens |
| Years 8-12 (Q29-Q48) | 0.25 | 0.40 | 0.35 | Convenience matters as products commoditize |
| Years 13-20 (Q49-Q80) | 0.20 | 0.35 | 0.45 | Mass market wants easy + safe |

Weights transition linearly between periods (no discontinuity).

---

## Capability, Brand, and Capacity Stocks

### Capability Stock (A_it) -- Drives Efficacy/Safety

```
A_t = (1 - delta_A) * A_{t-1} + eta_A * actual_product_rd_spend
```

| Parameter | Symbol | Value | Notes |
|-----------|--------|-------|-------|
| Depreciation rate | delta_A | 0.025/quarter | 10% annual; knowledge decays slowly |
| Accumulation rate | eta_A | 0.8 per $1M | $30M/quarter -> +24 points/quarter (net of depreciation) |
| Starting value (all firms) | A_0 | 35.0 | Baseline Gen 1 quality |
| Gen 2 threshold | -- | 120.0 | Stochastic check begins at A >= 120 |
| Gen 3 threshold | -- | 280.0 | |
| Gen 4 threshold | -- | 500.0 | |

When the stochastic check triggers a generation advance, the efficacy/safety indices
jump to the new generation's values (see table above). The capability stock continues
to accumulate beyond the threshold, improving efficacy/safety incrementally within
a generation.

### Brand Stock (B_it) -- Drives Brand Utility

```
B_t = (1 - delta_B) * B_{t-1} + eta_B * actual_sga_spend * quality_effectiveness
```

| Parameter | Symbol | Value | Notes |
|-----------|--------|-------|-------|
| Depreciation rate | delta_B | 0.10/quarter | 40% annual; brand fades fast without marketing |
| Accumulation rate | eta_B | 1.5 per $1M | $10M/quarter -> +15 points/quarter (before depreciation) |
| Starting value | B_0 | 10.0 | Low initial brand |
| Quality effectiveness | -- | effective_quality / 50 | Marketing more effective when product is better |
| Brand crash on safety event | -- | -30% of current B | Per publicized AE event at this firm |

### Capacity Stock (K_it) -- Drives Max Production

```
K_effective_t = K_installed_t * (1 - aging_penalty_t)
```

| Parameter | Value | Notes |
|-----------|-------|-------|
| Starting capacity | 250 courses/quarter | Pilot plant |
| Capacity per $1M capex | ~4.3 courses/quarter | At small-commercial scale ($120M -> 1,500) |
| Build delay | 4-8 quarters | Depends on scale |
| Depreciation (PPE) | 2.5%/quarter of gross PPE | 10% annual |
| Aging penalty (no reinvestment) | +0.5%/quarter after 20Q | Equipment wear |
| Minimum utilization to avoid cost penalty | 70% | Below this, COGS multiplier kicks in |

---

## Cost Structure

### COGS Computation (Per Treatment Course)

```
base_cogs = generation_base_cogs * (1 - process_rd_reduction)
utilization_cogs = base_cogs * utilization_multiplier(capacity_utilization)
final_cogs = utilization_cogs
```

| Generation | Base COGS/course | At Scale |
|-----------|-----------------|----------|
| Gen 1 | $14,000 | $13,600 at 5000+ courses/year |
| Gen 2 | $7,500 | |
| Gen 3 | $2,500 | |
| Gen 4 | $800 | |

**Note**: The $14,000 base includes per-firm variation of +/-$1,000 drawn at
firm creation. This is why the dossier example shows $14,200 while the world
doc baseline is $13,600 (which assumes full commercial scale + process optimization).

### Capacity Utilization Multiplier

| Utilization | COGS Multiplier | Formula |
|-------------|----------------|---------|
| >= 90% | 1.00 | -- |
| 70-90% | 1.00 + 0.5*(0.90 - util) | Linear interpolation |
| 50-70% | 1.10 + 1.0*(0.70 - util) | Steeper slope |
| 30-50% | 1.30 + 1.5*(0.50 - util) | Even steeper |
| < 30% | 1.60 + 2.0*(0.30 - util) | Severe penalty |

This multiplier is applied to base_cogs when computing actual COGS posted to
the income statement. It captures the fixed-cost absorption effect: when a factory
runs below capacity, fixed costs are spread over fewer units.

---

## Workforce Parameters

### Workforce Mechanics

Workforce size affects operations through three channels:

```
1. R&D speed: More scientists -> faster capability accumulation
   effective_eta_A = eta_A * (1 + 0.3 * log(scientists / 50))
   At 50 scientists (baseline): multiplier = 1.0x
   At 100 scientists: multiplier = 1.21x
   At 200 scientists: multiplier = 1.42x

2. Manufacturing quality: More ops staff -> lower batch failure rate
   batch_failure_rate = base_rate * (80 / ops_staff)^0.3
   At 80 ops staff (baseline): 1.0x base rate
   At 120 ops staff: 0.88x base rate (fewer failures)
   At 50 ops staff: 1.15x base rate (more failures)

3. Commercial effectiveness: More sales staff -> higher brand accumulation
   effective_eta_B = eta_B * (1 + 0.2 * log(sales_staff / 30))
```

### Workforce Cost Model

| Role Category | Base Annual Salary | Overhead Multiplier | Total Cost/Employee/Quarter |
|--------------|-------------------|--------------------|-----------------------------|
| Research scientists | $185,000 | 1.4x (benefits, equipment) | $64,750 |
| Process development | $155,000 | 1.3x | $50,375 |
| Manufacturing ops | $95,000 | 1.25x | $29,688 |
| Quality assurance | $120,000 | 1.3x | $39,000 |
| Commercial/sales | $140,000 | 1.5x (commissions, travel) | $52,500 |
| Medical affairs | $165,000 | 1.3x | $53,625 |
| General & admin | $130,000 | 1.2x | $39,000 |

Workforce costs flow into SGA (commercial, G&A), R&D (scientists, process dev),
and COGS (manufacturing, QA) proportionally.

### Workforce Decisions and Effects

| Decision | Effect | Lag |
|----------|--------|-----|
| Hire N employees (by category) | +headcount, +cost, +capability after ramp-up | 1 quarter ramp-up (50% effectiveness in Q1) |
| Lay off N employees | -headcount, -cost, restructuring charge (3 months' salary per person) | Immediate cost; capacity reduction next quarter |
| Increase compensation X% | Reduces turnover, improves retention of talent | Immediate cost; retention benefit over 2-4 quarters |
| Freeze hiring | No new hires; natural attrition continues (8%/year baseline) | Gradual headcount decline |

---

## Leasing and Facility Decisions

### Lease vs. Build

Firms can choose to LEASE manufacturing capacity instead of building:

| Decision | Lease | Build (Capex) |
|----------|-------|---------------|
| Upfront cost | $0 | Full build cost (e.g., $120M for small commercial) |
| Quarterly cost | $8-12M/quarter (lease payment) | $2M/quarter (maintenance) |
| Capacity available | Immediately (next quarter) | After build delay (4-8 quarters) |
| Balance sheet | Operating lease liability (loq) | PPE asset (ppentq) |
| Flexibility | Can terminate with 4Q notice | Permanent (can idle but not sell) |
| Customization | Standard facility | Fully customized |
| Capacity | Fixed | Can expand later |

### Lease Accounting

Under the simulation's accounting rules (simplified ASC 842):
- **Right-of-use asset**: Recorded as part of PPE (ppentq), equal to present value of remaining lease payments
- **Lease liability**: Recorded as part of other long-term liabilities (loq)
- **Lease expense**: Recorded as part of COGS (for manufacturing leases) or SGA (for office leases)
- **Depreciation**: Right-of-use asset is amortized over the lease term

### Compustat Columns for Leases

| Column | Name | Source |
|--------|------|--------|
| rouq | Right-of-use assets | PV of remaining lease payments |
| leaseq | Lease liability (total) | Same as rouq at inception; diverges with payments |
| xlrq | Lease expense (quarterly) | Lease payment allocated to P&L |

---

## Stock-Based Compensation

### How It Works

Firms grant stock options and restricted stock units (RSUs) to employees as part
of compensation. This is especially important in biotech where cash is scarce.

### Firm Decision

Each quarter, firms decide:
```json
{
  "stock_comp": {
    "option_grants": 100000,          // number of options granted
    "option_strike_price": "at_market", // at current stock price
    "rsu_grants": 50000,               // number of RSUs granted
    "vesting_quarters": 12             // vest over 12 quarters
  }
}
```

### Accounting Treatment

- **Expense**: Stock-based compensation is a **non-cash SGA expense** recognized
  over the vesting period
- **Fair value**: Options valued using Black-Scholes at grant date; RSUs valued
  at grant-date stock price
- **P&L impact**: Reduces operating income (non-cash)
- **Cash flow**: Added back to CFO (non-cash expense)
- **Dilution**: Options/RSUs increase diluted share count when exercised/vested
- **EPS impact**: Diluted EPS uses higher share count

### Parameters

| Parameter | Value |
|-----------|-------|
| Typical option grant (% of shares outstanding) | 0.5-2.0% per year |
| Typical RSU grant (% of shares outstanding) | 0.3-1.0% per year |
| Option vesting period | 12 quarters (3 years) |
| RSU vesting period | 8-16 quarters |
| Option exercise ratio (employees who exercise) | 70-85% |
| Black-Scholes volatility assumption | 40-60% (biotech) |
| Expected option life | 2.5 years |

### Compustat Columns for Stock Compensation

| Column | Name | Source |
|--------|------|--------|
| stkcpq | Stock-based compensation expense | Fair value of grants / vesting period |
| diluted_shares | Diluted shares outstanding | Basic + in-the-money options + unvested RSUs |

---

## Tax Parameters

| Parameter | Value | Notes |
|-----------|-------|-------|
| Corporate tax rate | 21% | Flat rate, matching US federal |
| NOL carryforward usage limit | 80% of taxable income | Per US TCJA rules |
| NOL expiration | None (infinite carryforward) | Simplified from real 20-year limit |
| State taxes | 0% (not modeled) | Simplification |
| R&D tax credit | 0% (not modeled) | Simplification; could add as regime option |
| Withholding on dividends | 0% | Simplification |
| Deferred tax asset from NOL | tax_rate * cumulative_NOL | Recorded on BS as part of other assets |

---

## Financial Institution Parameters

### Starting Capital (Canonical Values)

| Institution | Starting Capital | Min Capital Ratio | Max Single Exposure |
|-------------|-----------------|-------------------|-------------------|
| Investment Bank | $5,000,000,000 | 5% of AUM | N/A (equity, not credit) |
| Commercial Bank | $2,000,000,000 | 8% of total commitments | 25% of capital |
| Credit Fund | $3,000,000,000 | 10% of total deployed | 20% of capital |

### Income and Expense

| Parameter | Investment Bank | Commercial Bank | Credit Fund |
|-----------|----------------|-----------------|-------------|
| Fee income | 5% of IPO/secondary proceeds | 0.5%/quarter of commitments | 0.3%/quarter of deployed |
| Operating expense | 1% of capital annually | 1% of capital annually | 1% of capital annually |
| Interest income | N/A | Revolver balance * rate | Term debt balance * rate |

### Distress Thresholds (Canonical)

| Capital Ratio | Status | Constraint |
|--------------|--------|-----------|
| > 2x minimum | Well-capitalized | None |
| 1x - 2x minimum | Adequate | Mild caution |
| 0.5x - 1x minimum | Undercapitalized | Cannot increase commitments; rate floor = r_f + 500bps |
| 0 - 0.5x minimum | Critically undercapitalized | No new business; max rates |
| <= 0 | Failed | Replaced next quarter |

---

## Macro Shock Parameters

### Market Size AR(1) Process

```
log(M_t) = mu + rho * log(M_{t-1}) + sigma * eps_t
```

| Parameter | Symbol | Value |
|-----------|--------|-------|
| Drift | mu | 0.005 | per quarter (~2% annual growth) |
| Persistence | rho | 0.95 |
| Volatility | sigma | 0.05 |

### Risk-Free Rate Process

```
r_t = max(0.005, min(0.05, r_{t-1} + sigma_r * eps_t))
```

| Parameter | Value |
|-----------|-------|
| Starting value | 0.01/quarter (4% annual) |
| Volatility | 0.002/quarter |
| Floor | 0.005/quarter (2% annual) |
| Ceiling | 0.05/quarter (20% annual) |

### Event Probabilities (Per Quarter)

| Event | Per-Firm Probability | Industry Probability |
|-------|---------------------|---------------------|
| Publicized adverse event | 3% | ~14% (at least one firm) |
| Partial clinical hold | 2% (higher if AE rate above avg) | -- |
| Full clinical hold | 0.5% | -- |
| Class-wide clinical hold | -- | 0.3% |
| Academic breakthrough | -- | 5% |
| Supply chain disruption | 2% per firm | -- |
| Regulatory pricing event | -- | ~0.5% (~15% cumulative over 80Q) |
| Insurance coverage mandate | -- | ~0.4% (~25% cumulative over 80Q) |

---

## Stochastic R&D Success

### Generation Advance Check

Each quarter, for each firm, if cumulative product R&D exceeds the minimum threshold:

```
P(success) = base_rate * min(2.0, (cumulative / threshold_mid)^0.5)
```

| Transition | Threshold (min) | Threshold (mid) | Base Rate | Max P/quarter |
|-----------|----------------|-----------------|-----------|---------------|
| Gen 1 -> Gen 2 | $400M | $500M | 0.12 | 0.24 |
| Gen 2 -> Gen 3 | $800M | $1,000M | 0.08 | 0.16 |
| Gen 3 -> Gen 4 | $1,500M | $2,000M | 0.06 | 0.12 |

"Threshold (min)" is the absolute minimum cumulative spend to have any chance.
"Threshold (mid)" is the calibrated center of the range. Spending beyond mid
improves probability but with diminishing returns (the square root).

### Process R&D (COGS Reduction)

```
cogs_reduction_pct = 0.22 * (1 - exp(-cumulative_process_rd / 120_000_000))
```

This is an exponential saturation: fast gains initially, diminishing returns,
maximum 22% reduction within a generation.

### Delivery R&D

Same stochastic check as product R&D, with separate thresholds:

| Transition | Threshold (min) | Base Rate | Requires |
|-----------|----------------|-----------|----------|
| IV -> Subcutaneous | $100M | 0.15 | Nothing (can do with Gen 1) |
| SubQ -> Oral | $300M | 0.10 | Gen 2 compound |
| Oral -> Gene therapy | $800M | 0.06 | Gen 3 compound |

---

## Scoring Parameters

### Equity IRR Computation

Terminal value for surviving firms at end of simulation:
```
terminal_equity_value = equity_price_final * shares_outstanding
```

For defaulted firms: terminal equity = 0 (or waterfall residual, usually 0).
For acquired firms: terminal equity = acquisition proceeds to equity holders.

Cash flows to equity: [-IPO investment, +dividends, +buybacks, +terminal_value]
IRR computed on this cash flow stream.

**This is the canonical formula. Doc 11's "terminal enterprise value" is a separate
metric for reporting, NOT used in the IRR calculation.**

### Environment Rating Scale

| Score | Meaning |
|-------|---------|
| 1-2 | Unrealistic, inconsistent, unfair |
| 3-4 | Below average; notable problems |
| 5-6 | Adequate; functional but some issues |
| 7-8 | Good; realistic and engaging |
| 9-10 | Excellent; highly immersive and consistent |
