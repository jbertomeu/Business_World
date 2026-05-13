# Accounting Rules in the SRT World

## Purpose

This document explains how financial statements work in the simulated world.
All agents (firms, financial institutions, environment) should understand these
rules to correctly interpret financial statements and make informed decisions.

The default accounting follows **US GAAP** principles, but the simulation can be
configured to use alternative rules (see the measurement regime system). This
document describes the default ("baseline GAAP") treatment.

---

## Income Statement

### Revenue Recognition (Accrual Basis)

Revenue is recognized when a treatment course is **delivered** to the patient,
not when cash is collected.

- A patient signs up and begins treatment -> revenue recognized this quarter
- Payment may be received this quarter (cash) or next quarter (accounts receivable)
- Typical collection cycle: 85% of revenue collected in the same quarter,
  15% collected next quarter (becomes AR)
- Bad debt: approximately 1-3% of AR is never collected (written off)

### Cost of Goods Sold (COGS)

COGS = units sold * unit cost per course

Unit cost includes:
- Raw materials (senolytic API, peptide API)
- Manufacturing labor and overhead
- Quality control and testing
- Batch failure allocation
- Shipping and cold chain logistics

COGS is matched to revenue: only the cost of goods SOLD is expensed, not the
cost of goods produced. Unsold inventory remains on the balance sheet.

### Research & Development Expense

Under default GAAP, ALL R&D spending is **expensed immediately**:
- Product R&D (next-generation compounds)
- Process R&D (manufacturing improvements)
- Delivery R&D (new formulations)
- Mandatory Phase III trial costs ($10M/quarter)

R&D does NOT appear as an asset on the balance sheet under baseline GAAP.
This means a firm spending heavily on R&D will report LOWER net income (and
lower assets) than one that is not, even if the R&D is creating enormous future
value.

**Alternative regime** (R&D capitalization): Under this regime, a portion
(e.g., 60%) of R&D spending is capitalized as an intangible asset and amortized
over 12 quarters. This makes R&D-heavy firms look more profitable and asset-rich.

### Selling, General & Administrative (SGA)

SGA includes:
- Sales force compensation and commissions
- Direct-to-consumer advertising
- Physician education and medical affairs
- General management salaries
- Office rent and corporate overhead
- Litigation reserves and insurance premiums
- Integration costs (after an acquisition)

### Depreciation & Amortization

**Depreciation** (PPE): Straight-line, 10% per year (2.5% per quarter) of gross
PPE value. Manufacturing equipment has a useful life of approximately 10 years.

**Amortization** (intangible assets): If R&D is capitalized, amortization is
straight-line over the amortization period (default: 12 quarters). Acquired IP
from M&A is also amortized.

### Goodwill Impairment

Goodwill arises from acquisitions where the purchase price exceeds the fair
value of acquired net assets. Under GAAP:
- Goodwill is NOT amortized
- Instead, it is tested for impairment annually (every 4 quarters)
- If the fair value of the acquired business has declined below its carrying
  value, the difference is recorded as an **impairment loss** on the IS
- Impairment is a non-cash charge (does not affect cash flow directly)

### Interest Expense

Interest expense includes:
- Revolver interest: balance * quarterly rate
- Term debt interest: balance * quarterly rate
- Commitment fees: undrawn revolver * small fee rate (~50 bps annually)

### Taxes

Tax rate: 21% (flat corporate rate, matching US federal rate)

- Applied to pretax income
- If pretax income is negative: no tax due (tax expense = 0)
- **Net operating loss carryforward**: Losses from prior quarters can offset
  future income. Tracked as a deferred tax asset (DTA).
- Limitation: NOL carryforward can offset up to 80% of taxable income in
  any given quarter (matching current US rules)
- Taxes payable: recognized on IS this quarter, paid next quarter (current
  liability on BS)

### Earnings Per Share

- **Basic EPS** = Net income / Weighted average shares outstanding
- **Diluted EPS** = Net income / Diluted shares (if options or warrants exist)
  In this simulation, diluted = basic unless there are specific dilutive instruments.

---

## Balance Sheet

### Assets

**Current assets** (expected to convert to cash within 4 quarters):
- **Cash** (cheq): Cash on hand + short-term investments
- **Accounts receivable** (rectq): Revenue earned but not yet collected (net of
  allowance for bad debt)
- **Inventories** (invtq): Unsold treatment courses, valued at cost (FIFO)
- **Prepaid expenses** (xppq): Advance payments for raw materials
- **Other current assets**: Miscellaneous

**Non-current assets**:
- **PP&E net** (ppentq): Manufacturing facilities and equipment, at cost minus
  accumulated depreciation
- **Intangible assets** (intanq): Capitalized R&D (if applicable), acquired IP
- **Goodwill** (gdwlq): From acquisitions (purchase price minus fair value of
  net assets acquired)
- **Other long-term assets**: Deferred tax assets, deposits

### Liabilities

**Current liabilities** (due within 4 quarters):
- **Accounts payable** (apq): Amounts owed to suppliers for raw materials
- **Accrued expenses** (acoq): Wages payable, utilities, accrued benefits
- **Taxes payable** (txpq): Current quarter tax obligation
- **Deferred revenue** (drcq): Advance patient payments (rare in SRT)
- **Current portion of debt** (dlcq): Revolver balance + portion of term debt
  due within 4 quarters

**Non-current liabilities**:
- **Long-term debt** (dlttq): Term debt principal, minus current portion
- **Other long-term liabilities** (loq): Litigation reserves, lease obligations,
  warranty provisions, pension obligations

### Equity

- **Common stock** (cstkq): Par value of shares issued (typically nominal)
- **Additional paid-in capital** (apicq): Amounts received above par value
  (IPO proceeds, secondary offering proceeds)
- **Retained earnings** (req): Cumulative net income minus cumulative dividends
  - Can be negative ("accumulated deficit") for unprofitable firms
  - A negative RE does NOT mean the firm is insolvent -- it means it has
    invested more than it has earned so far (common for biotech)
- **Treasury stock** (tstkq): Cost of shares repurchased (reduces equity)
- **Accumulated OCI** (aociq): Unrealized gains/losses from fair value
  adjustments (only under fair value measurement regime)

### The Balance Sheet Identity

**Always holds**: Total Assets = Total Liabilities + Total Equity

`atq = ltq + ceqq`

This is an accounting identity, not an approximation. The orchestrator
enforces it every quarter (hard invariant, tolerance < $1).

---

## Cash Flow Statement

### Operating Cash Flow (CFO)

Starts with net income and adjusts for non-cash items and working capital changes:

```
Net income
+ Depreciation & amortization (non-cash expense)
+ Goodwill impairment (non-cash charge)
+ Stock-based compensation (if any, non-cash)
- Increase in accounts receivable (cash tied up in AR)
+ Decrease in accounts receivable (cash released from AR)
- Increase in inventory (cash spent building inventory)
+ Decrease in inventory (cash released from inventory)
+ Increase in accounts payable (cash conserved by delaying payment)
- Decrease in accounts payable (cash used to pay down AP)
+ Increase in accrued expenses
- Decrease in accrued expenses
+ Increase in taxes payable
- Decrease in taxes payable
= Cash from operations (oancfq)
```

### Investing Cash Flow (CFI)

```
- Capital expenditure (capxq) [always negative]
- Acquisition spending (aqaq) [cash paid for M&A]
+ Proceeds from asset sales [if any]
= Cash from investing (ivncfq) [usually negative]
```

### Financing Cash Flow (CFF)

```
+ Equity issuance proceeds (sstkq)
+ New debt proceeds (revolver draws + term debt issuance)
- Debt repayments (revolver paydowns + term debt repayment)
- Share buybacks (prstkq)
- Dividend payments (dvq)
= Cash from financing (fincfq)
```

### The Cash Reconciliation Identity

**Always holds**: Change in cash = CFO + CFI + CFF

`chechq = oancfq + ivncfq + fincfq`
`cheq_t = cheq_{t-1} + chechq`

This is enforced as a hard invariant.

---

## Key Ratios and What They Mean

### Profitability

| Ratio | Formula | What It Tells You |
|-------|---------|------------------|
| Gross margin | gpq / saleq | How efficiently you produce |
| Operating margin | oiadpq / saleq | How efficiently you run the business |
| Net margin | niq / saleq | Bottom-line profitability |
| R&D intensity | xrdq / saleq | How much you invest in innovation |
| SGA intensity | xsgaq / saleq | How much you spend on sales and admin |
| Return on equity | niq / ceqq | How well you use shareholders' capital |
| Return on assets | niq / atq | How well you use all capital |

### Liquidity

| Ratio | Formula | What It Tells You |
|-------|---------|------------------|
| Current ratio | actq / lctq | Can you pay short-term obligations? (>1.5 is healthy) |
| Cash ratio | cheq / lctq | Can you pay with cash alone? |
| Cash runway | cheq / quarterly_burn | How many quarters before cash runs out |

### Leverage

| Ratio | Formula | What It Tells You |
|-------|---------|------------------|
| Debt-to-equity | (dlcq + dlttq) / ceqq | How leveraged is the firm? |
| Interest coverage | oiadpq / xintq | Can you pay interest from operations? (>2x is healthy) |
| Debt-to-EBITDA | total_debt / (oiadpq + dpq) | Leverage relative to cash generation |

### Valuation

| Ratio | Formula | What It Tells You |
|-------|---------|------------------|
| P/E ratio | prccq / epsfxq | Price relative to current earnings |
| P/S ratio | mkvaltq / (saleq * 4) | Price relative to annualized revenue |
| P/B ratio | prccq / bkvlpsq | Price relative to book value |
| EV/Revenue | (mkvaltq + debt - cheq) / (saleq * 4) | Enterprise value relative to revenue |

---

## How Accounting Affects Strategy

1. **R&D expensing hurts reported earnings** but preserves the true economic picture.
   A firm spending $100M on R&D with $200M revenue reports an operating loss even
   if the R&D is creating enormous future value. Financial institutions and the
   investment bank should look through the R&D expense to assess underlying economics.

2. **Accrual accounting smooths cash flow timing.** Revenue is recognized when earned,
   not when cash arrives. This means a firm can be "profitable" on the IS but cash-poor
   if AR is growing (customers haven't paid yet). Watch cash, not just net income.

3. **Depreciation is non-cash.** A firm with high depreciation may look unprofitable
   on the IS but still generate strong cash flow (because depreciation is added back
   in CFO). Look at operating cash flow, not just net income.

4. **Goodwill impairment is a delayed loss recognition.** When a firm takes a goodwill
   impairment charge, it is admitting that an acquisition was overpriced. The actual
   loss happened when the deal closed; the impairment just records it formally.

5. **Tax loss carryforwards are valuable.** A firm that has accumulated losses has a
   "tax shield" -- future profits will be partially sheltered from tax. This makes
   unprofitable firms slightly more valuable as acquisition targets (the acquirer
   can use the target's tax losses).

6. **Working capital is real money.** Growing firms often need more working capital
   (more AR as revenue grows, more inventory to support higher production). This cash
   requirement can surprise firms that focus only on profitability -- you can be
   profitable and still run out of cash if working capital absorbs all your earnings.
