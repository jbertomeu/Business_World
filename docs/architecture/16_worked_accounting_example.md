# Worked Accounting Example: One Complete Quarter

## Purpose

This document walks through a single firm's full quarterly accounting cycle,
starting from a given balance sheet, applying a set of decisions and market
outcomes, and producing the ending balance sheet with every intermediate
calculation shown.

**This example is the canonical test fixture.** When the accounting code is
written, it must reproduce these numbers exactly. It is also the specification:
any ambiguity in the architecture docs should be resolved by what this example
shows.

All values follow the canonical parameters in world doc 09 (Parameters and
Calibration).

---

## The Firm: Aeterna Therapeutics (firm_0)

- **Quarter**: Q2 2031 (the firm's second quarter of operations)
- **Mode**: Public (post-IPO)
- **Generation**: Gen 1
- **Starting shares outstanding**: 10,000,000
- **Par value**: $0.001 per share
- **Capacity**: 250 courses/quarter (pilot plant)
- **Base unit cost**: $14,200 per course (no process R&D effect yet)
- **Tax rate**: 21%
- **Measurement regime**: `baseline_gaap`
- **Toggles**: entry_exit=ON, financial_institutions=ON, all others OFF

---

## Section 1: Starting Balance Sheet (End of Q1 2031)

These values are the inputs to the Q2 calculation. They are derived from a
prior Q1 calculation (shown in the appendix) where the firm IPO'd for $350M,
produced 200 courses, sold 180 at $95,000, and invested $25M in R&D and $12M
in SGA.

### Assets

| Line | Amount | Source |
|------|--------|--------|
| Cash (cheq) | 303,655,570 | IPO 325M minus Q1 cash outflows |
| Accounts receivable (rectq) | 2,565,000 | 15% of Q1 revenue of 17,100,000 |
| Inventory (invtq) | 298,200 | 20 unsold units from Q1 at 14,910 each |
| PPE gross | 25,000,000 | Pilot plant |
| Accumulated depreciation | 625,000 | One quarter of depreciation |
| PPE net (ppentq) | 24,375,000 | |
| **Total assets (atq)** | **330,893,770** | |

### Liabilities

| Line | Amount | Source |
|------|--------|--------|
| Accounts payable (apq) | 402,570 | 15% of Q1 COGS of 2,683,800 |
| Accrued expenses (acoq) | 3,700,000 | 10% of Q1 (R&D + SGA) of 37,000,000 |
| Taxes payable (txpq) | 0 | Q1 was a loss |
| Current debt (dlcq) | 0 | No revolver drawn |
| Long-term debt (dlttq) | 0 | No term debt |
| **Total liabilities (ltq)** | **4,102,570** | |

### Equity

| Line | Amount | Source |
|------|--------|--------|
| Common stock (cstkq) | 10,000 | 10M shares * $0.001 par |
| Additional paid-in capital (apicq) | 349,990,000 | IPO proceeds above par |
| Retained earnings (req) | (23,208,800) | Q1 net loss |
| Treasury stock (tstkq) | 0 | No buybacks |
| **Total equity (ceqq)** | **326,791,200** | |

### Balance Check

- Total assets: 330,893,770
- Total liabilities + equity: 4,102,570 + 326,791,200 = 330,893,770
- Difference: 0 **PASS**

### Internal State (not on balance sheet)

| Variable | Value | Notes |
|----------|-------|-------|
| Capability stock (A) | 35.0 + 5.0 = 40.0 | Start 35 + Q1 R&D effect |
| Brand stock (B) | 10.0 + 1.25 = 11.25 | Start 10 + Q1 SGA effect |
| Cumulative product R&D | 10,000,000 | From Q1 (60% of 15M discretionary, after 10M Phase III) |
| Cumulative process R&D | 3,750,000 | From Q1 (25% of 15M discretionary) |
| Cumulative delivery R&D | 2,250,000 | From Q1 (15% of 15M discretionary) |
| NOL carryforward | 23,208,800 | Q1 net loss |
| Product generation | 1 | |
| Delivery generation | 1 | IV infusion |

---

## Section 2: Q2 Inputs (Decisions and Outcomes)

### Firm Decisions (from firm agent, after clamping)

```json
{
  "price": 92000,
  "production": 220,
  "capex": 15000000,
  "rd_spend": 28000000,
  "rd_allocation": {"product": 0.60, "process": 0.25, "delivery": 0.15},
  "sga_spend": 14000000,
  "equity_issuance_request": 0,
  "debt_request": 0,
  "dividends": 0,
  "buybacks": 0
}
```

Note: `rd_spend` of 28,000,000 includes the $10M mandatory Phase III trial cost.
The discretionary R&D is 28,000,000 - 10,000,000 = 18,000,000, allocated per
the above percentages.

### Market Outcomes (from environment agent)

```json
{
  "firm_0": {
    "units_sold": 200,
    "market_share": 0.22,
    "product_rd_advance": false,
    "process_cogs_reduction_this_quarter": 0.0,
    "delivery_advance": false
  }
}
```

### Feasibility Check (Phase 4)

Clamping verification:
- Cash on hand: 303,655,570
- Expected Q2 revenue (80% collected this Q per policy): 200 * 92,000 * 0.85 = 15,640,000
- Prior AR collection (all of it): 2,565,000
- Revolver available: 0 (no commitment yet)
- **Total available this quarter**: 321,860,570

Requested spending:
- COGS cash portion: clamped to actual production cost
- Phase III (mandatory): 10,000,000
- Discretionary R&D: 18,000,000
- SGA: 14,000,000
- Capex: 15,000,000
- Total before COGS: 57,000,000

Available is 321M, requested is well below. **No clamping needed.** All
requested amounts are feasible.

Dividends blocked (RE < 0) -- check passes automatically, dividends=0.

---

## Section 3: Computing the Income Statement

### Step 3.1: Effective Unit Cost

```
capacity_utilization = production / capacity
                     = 220 / 250
                     = 0.88
```

Utilization multiplier (from doc 09):
- 0.88 is in the 70-90% band
- Formula: 1.00 + 0.5 * (0.90 - util)
- = 1.00 + 0.5 * (0.90 - 0.88)
- = 1.00 + 0.01
- = **1.01**

Process R&D reduction (from cumulative process R&D spending up to start of Q2):
- Cumulative at start of Q2: 3,750,000 (from Q1)
- Formula: 0.22 * (1 - exp(-cumulative / 120,000,000))
- = 0.22 * (1 - exp(-3,750,000 / 120,000,000))
- = 0.22 * (1 - exp(-0.03125))
- = 0.22 * (1 - 0.96923)
- = 0.22 * 0.03077
- = 0.00677 (0.68%)

```
base_cogs_after_process_rd = 14,200 * (1 - 0.00677)
                           = 14,200 * 0.99323
                           = 14,103.87
                           ≈ 14,104

effective_unit_cost = 14,104 * 1.01
                    = 14,245.04
                    ≈ 14,245
```

### Step 3.2: Inventory Accounting (FIFO)

Starting inventory: 20 units from Q1 at $14,910 each = 298,200 total.

Q2 production: 220 units at new effective cost of $14,245 each = 3,133,900.

Total units available to sell: 20 (old) + 220 (new) = 240.
Units sold: 200.
Remaining inventory: 40 units (all from Q2 production).

FIFO cost of goods sold:
- 20 old units * 14,910 = 298,200
- 180 new units * 14,245 = 2,564,100
- **COGS = 2,862,300**

Ending inventory:
- 40 new units * 14,245 = **569,800**

### Step 3.3: Income Statement

```
Revenue (saleq)           = 200 * 92,000         = 18,400,000
COGS (cogsq)              =                        2,862,300
Gross profit (gpq)        =                       15,537,700

R&D expense (xrdq)        = 28,000,000
SGA expense (xsgaq)       = 14,000,000
Depreciation (dpq)        = 0.025 * PPE_gross
                          = 0.025 * 25,000,000  =    625,000
                          (capex from Q2 not yet depreciating)

Operating expenses        = 28,000,000 + 14,000,000 + 625,000
                          =                       42,625,000

Operating income (oiadpq) = 15,537,700 - 42,625,000
                          =                     (27,087,300)

Interest expense (xintq)  =                              0
Pretax income (piq)       =                     (27,087,300)
Tax expense (txtq)        =                              0
                          (loss; no tax; NOL carryforward grows)
Net income (niq)          =                     (27,087,300)
```

### Step 3.4: NOL Update

NOL at start of Q2: 23,208,800 (from Q1)
Q2 is a loss, so NOL increases:
```
NOL_end_Q2 = 23,208,800 + 27,087,300 = 50,296,100
```
No NOL was used in Q2 (no taxable income to offset).

---

## Section 4: Computing Working Capital Changes

### Accounts Receivable

```
Target AR = 15% * current quarter revenue
          = 0.15 * 18,400,000
          = 2,760,000

Collection of prior AR = 100% of opening AR (paid this quarter)
                       = 2,565,000  (becomes cash)

Ending AR = 2,760,000
ΔAR      = 2,760,000 - 2,565,000 = +195,000  (AR grew)
```

### Inventory

```
Starting inventory: 298,200
Add production cost: 220 * 14,245 = 3,133,900
Subtract COGS: 2,862,300

Ending inventory = 298,200 + 3,133,900 - 2,862,300 = 569,800
ΔInventory      = 569,800 - 298,200 = +271,600
```

### Accounts Payable

```
Target AP = 15% * current quarter COGS
          = 0.15 * 2,862,300
          = 429,345

Payment of prior AP = 100% (paid this quarter)
                    = 402,570  (cash outflow)

Ending AP = 429,345
ΔAP      = 429,345 - 402,570 = +26,775
```

### Accrued Expenses

```
Target accrued = 10% * (R&D + SGA)
               = 0.10 * (28,000,000 + 14,000,000)
               = 4,200,000

Payment of prior accrued = 100%
                         = 3,700,000

Ending accrued = 4,200,000
ΔAccrued      = 4,200,000 - 3,700,000 = +500,000
```

### Taxes Payable

```
Ending = 0 (no tax in Q2)
ΔTaxes payable = 0
```

---

## Section 5: Computing the Cash Flow Statement

### Cash from Operations (CFO)

```
Net income                           (27,087,300)
+ Depreciation (non-cash)                625,000
+ ΔAP (source of cash)                    26,775
+ ΔAccrued (source of cash)              500,000
+ ΔTaxes payable                               0
- ΔAR (use of cash)                     (195,000)
- ΔInventory (use of cash)              (271,600)
                                     ------------
CFO (oancfq)                         (26,401,925)
```

### Cash from Investing (CFI)

```
- Capex                              (15,000,000)
- Acquisitions                                 0
+ Asset sales                                  0
                                     ------------
CFI (ivncfq)                         (15,000,000)
```

### Cash from Financing (CFF)

```
+ Equity issuance                              0
+ New debt                                     0
- Debt repayment                               0
- Dividends                                    0
- Buybacks                                     0
                                     ------------
CFF (fincfq)                                   0
```

### Total Change in Cash

```
ΔCash = CFO + CFI + CFF
      = (26,401,925) + (15,000,000) + 0
      = (41,401,925)

Ending cash = Starting cash + ΔCash
            = 303,655,570 + (41,401,925)
            = 262,253,645
```

---

## Section 6: Computing PPE and Depreciation

```
Starting PPE gross            25,000,000
+ Q2 capex                    15,000,000
Ending PPE gross              40,000,000

Starting accum depreciation      625,000
+ Q2 depreciation                625,000
                             (on beginning PPE of 25,000,000)
Ending accum depreciation      1,250,000

Ending PPE net  = 40,000,000 - 1,250,000
                = 38,750,000
```

Note: Q2 capex is added to PPE but does not depreciate in Q2 (placed in service
at end of quarter -- conservative convention).

---

## Section 7: Computing Retained Earnings

```
Starting RE                  (23,208,800)
+ Net income Q2              (27,087,300)
- Dividends Q2                         0
                             -----------
Ending RE                    (50,296,100)
```

Note: Ending RE equals negative of NOL carryforward by construction (no dividends,
no other OCI). This cross-checks the NOL tracking.

---

## Section 8: Computing Internal Stock Updates

### Capability Stock (A)

Product R&D in Q2:
- Total R&D: 28,000,000
- Less Phase III: 10,000,000
- Discretionary: 18,000,000
- Product allocation: 60% * 18,000,000 = 10,800,000

```
A_Q2 = (1 - 0.025) * A_Q1 + eta_A * product_rd_spend
     = 0.975 * 40.0 + 0.0008/1,000,000 * 10,800,000
     = 39.0 + 0.00864 * 1,000
     = 39.0 + 8.64
     = 47.64
```

Wait, let me re-check the eta_A formula from doc 09:
> `eta_A`: 0.0008 per $1M

So for $10.8M of product R&D:
```
contribution = 0.0008 * (10,800,000 / 1,000,000)
             = 0.0008 * 10.8
             = 0.00864
```

That gives a tiny increment. Let me re-read the formula:
> `A_t = (1 - delta_A) * A_{t-1} + eta_A * actual_product_rd_spend`

If eta_A = 0.0008 per $1M, then effectively the formula is:
```
A_t = (1 - 0.025) * A_{t-1} + 0.0008 * (product_rd_spend / 1,000,000)
```

With $10.8M product R&D:
```
A_Q2 = 0.975 * 40.0 + 0.0008 * 10.8
     = 39.0 + 0.00864
     = 39.00864
```

That's essentially no growth. Doc 09 says "$30M/quarter -> +24 points/quarter
(net of depreciation)". Let me check:

With $30M product R&D:
```
A_growth = 0.0008 * 30 = 0.024  (NOT 24)
```

There's a unit mismatch in doc 09. The intended behavior is probably:
```
eta_A * product_rd_spend_in_millions = 0.8 per $1M
```

So with $30M -> 0.8 * 30 = 24 points gross. After depreciation:
```
A_new = 0.975 * A_old + 0.8 * 30
      = 0.975 * A_old + 24
```

**CORRECTION TO DOC 09 NEEDED**: eta_A should be 0.8 per $1M (not 0.0008 per $1M).
Same issue for eta_B.

Using corrected eta_A = 0.8 per $1M:

```
A_Q2 = 0.975 * 40.0 + 0.8 * 10.8
     = 39.0 + 8.64
     = 47.64
```

### Brand Stock (B)

SGA spend Q2: 14,000,000.
Effective quality at start of Q2 (approximate): ~35 (Gen 1 baseline).
Quality effectiveness factor: 35 / 50 = 0.70.

Using corrected eta_B = 1.5 per $1M:

```
B_Q2 = (1 - 0.10) * B_Q1 + eta_B * sga_millions * quality_effectiveness
     = 0.90 * 11.25 + 1.5 * 14.0 * 0.70
     = 10.125 + 14.70
     = 24.825
```

### R&D Cumulative Tracking

```
Cumulative product R&D = 10,000,000 + 10,800,000 = 20,800,000
Cumulative process R&D =  3,750,000 +  4,500,000 =  8,250,000
Cumulative delivery R&D=  2,250,000 +  2,700,000 =  4,950,000

(Q2 discretionary: 18,000,000 * 0.25 = 4,500,000 process; 18,000,000 * 0.15 = 2,700,000 delivery)
```

None of these have crossed the Gen 2 threshold ($400M minimum), so no stochastic
advance check runs yet.

### Capacity Stock

Starting capacity: 250 (pilot plant)
Q2 capex: 15,000,000 -- this is below the threshold for any meaningful new
facility. Treat as maintenance capex (capacity stays at 250).

Alternatively, treat it as the start of a multi-quarter build (doc 03 small
commercial plant: $120M over 4 quarters = $30M/Q). 15M is below that rate too.

For this example: capex is maintenance + pilot augmentation. Capacity stays 250.
The 15M is added to PPE gross but does not change capacity.

---

## Section 9: Ending Balance Sheet

### Assets

| Line | Amount | Derivation |
|------|--------|-----------|
| Cash | 262,253,645 | 303,655,570 + (-41,401,925) |
| Accounts receivable | 2,760,000 | 15% of Q2 revenue |
| Inventory | 569,800 | 40 units * 14,245 |
| PPE gross | 40,000,000 | 25M + 15M capex |
| Accum depreciation | (1,250,000) | 625K + 625K |
| PPE net | 38,750,000 | |
| **Total assets** | **304,333,445** | |

### Liabilities

| Line | Amount | Derivation |
|------|--------|-----------|
| Accounts payable | 429,345 | 15% of Q2 COGS |
| Accrued expenses | 4,200,000 | 10% of (R&D + SGA) |
| Taxes payable | 0 | Q2 loss |
| Current debt | 0 | |
| Long-term debt | 0 | |
| **Total liabilities** | **4,629,345** | |

### Equity

| Line | Amount | Derivation |
|------|--------|-----------|
| Common stock | 10,000 | Unchanged |
| APIC | 349,990,000 | Unchanged |
| Retained earnings | (50,296,100) | (23,208,800) + (27,087,300) |
| Treasury stock | 0 | Unchanged |
| **Total equity** | **299,703,900** | |

---

## Section 10: Invariant Verification

### Invariant 1: Balance Sheet Identity

```
Total assets = 304,333,445
Total liabilities + equity = 4,629,345 + 299,703,900 = 304,333,245
Difference = 304,333,445 - 304,333,245 = 200
```

**FAIL by $200** -- this is a rounding issue to fix. Let me find it.

Tracing: the mismatch is exactly 200. Checking RE:
- Starting RE: (23,208,800)
- Net income: (27,087,300)
- Expected ending RE: (50,296,100)
- Recomputing: 23,208,800 + 27,087,300 = 50,296,100 ✓

Checking cash:
- Start: 303,655,570
- CFO: (26,401,925)
- CFI: (15,000,000)
- End: 262,253,645
- Check: 303,655,570 - 26,401,925 - 15,000,000 = 262,253,645 ✓

Checking total assets arithmetic:
```
262,253,645 + 2,760,000 + 569,800 + 38,750,000
= 264,013,645 + 569,800 + 38,750,000
= 264,583,445 + 38,750,000
= 303,333,445
```

Hmm I wrote 304 earlier. Recounting:
```
262,253,645
+ 2,760,000  -> 265,013,645
+    569,800 -> 265,583,445
+ 38,750,000 -> 304,333,445
```

That's 304,333,445.

Total L+E:
```
  4,629,345
+ 10,000     -> 4,639,345
+ 349,990,000 -> 354,629,345
- 50,296,100 -> 304,333,245
```

Hmm so 304,333,245 vs 304,333,445. Difference is exactly 200.

Let me recheck inventory. Q2 production 220 at 14,245:
```
220 * 14,245 = ?
220 * 14,000 = 3,080,000
220 * 245 = 53,900
Total = 3,133,900 ✓
```

40 units * 14,245 = 569,800 ✓

Hmm, 14,245 * 40 = 569,800. Let me verify: 14,245 * 4 = 56,980. * 10 = 569,800. ✓

COGS: FIFO
```
20 units at 14,910 = 298,200
180 units at 14,245 = ?
180 * 14,245 = 180 * 14,000 + 180 * 245
             = 2,520,000 + 44,100
             = 2,564,100
Total COGS = 298,200 + 2,564,100 = 2,862,300 ✓
```

Now check inventory continuity:
```
Start inv: 298,200
Add production: 3,133,900
Less COGS: 2,862,300
End inv: 298,200 + 3,133,900 - 2,862,300

298,200 + 3,133,900 = 3,432,100
3,432,100 - 2,862,300 = 569,800 ✓
```

OK that's right.

Check CFO:
```
NI:           (27,087,300)
+ Dep:             625,000
+ ΔAP:              26,775
+ ΔAcc:            500,000
- ΔAR:            (195,000)
- ΔInv:           (271,600)
```

Wait: ΔInv should be 569,800 - 298,200 = 271,600 ✓

CFO sum:
```
-27,087,300 + 625,000 = -26,462,300
-26,462,300 + 26,775 = -26,435,525
-26,435,525 + 500,000 = -25,935,525
-25,935,525 - 195,000 = -26,130,525
-26,130,525 - 271,600 = -26,402,125
```

Hmm I got (26,402,125), not (26,401,925). Off by 200.

Let me recompute ΔAR:
```
Target AR = 0.15 * 18,400,000 = 2,760,000
Start AR = 2,565,000
ΔAR = 2,760,000 - 2,565,000 = 195,000 ✓
```

And the accounting treatment: during the quarter, 100% of prior AR is collected,
85% of new revenue collected, 15% becomes new AR. Let me verify via direct cash:

Cash inflow from revenue + AR:
```
Revenue collected: 0.85 * 18,400,000 = 15,640,000
Prior AR collected: 2,565,000
Total cash in: 18,205,000
```

New AR at end of Q2 = 0.15 * 18,400,000 = 2,760,000 ✓

The direct CFO method (more intuitive):
```
Cash from customers = 18,205,000
- Cash paid to suppliers (COGS - ΔAP) = 2,862,300 - 26,775 = 2,835,525
- Cash paid for R&D (full, since accrued is 10% * combined)
  Actually: R&D + SGA = 42,000,000, ending accrued = 4,200,000, starting accrued = 3,700,000
  Cash paid = 42,000,000 - (4,200,000 - 3,700,000) = 42,000,000 - 500,000 = 41,500,000
- Taxes paid = 0
- Interest paid = 0

CFO = 18,205,000 - 2,835,525 - 41,500,000
    = 18,205,000 - 44,335,525
    = (26,130,525)
```

So the direct method gives CFO = (26,130,525).

The indirect method gave (26,402,125). These disagree by 271,600 which is exactly
the inventory change!

**Found the bug.** In the indirect method, I subtracted the 271,600 inventory
change, but inventory is a NON-CASH build. Production cost of 3,133,900 came
from where? Raw materials purchased (becoming AP then cash out) plus labor
(becoming accrued then cash out). The inventory build represents cost
capitalized, not yet expensed.

The correct indirect CFO:
```
NI                     (27,087,300)
+ Dep                      625,000
Changes in WC:
+ ΔAP                       26,775
+ ΔAccrued                 500,000
- ΔAR                     (195,000)
- ΔInventory              (271,600)

Sum: (26,402,125)
```

But the direct method shows (26,130,525). Discrepancy = 271,600.

The issue is that in the indirect method, when you subtract ΔInventory, you are
saying "we spent 271,600 building inventory (cash out)". But production cost
INCLUDES expenses that were already NON-CASH (accrued).

Actually no. Let me think more carefully.

**The subtlety**: Cost of production = 3,133,900. This consists of:
- Materials (cash or AP)
- Labor (cash or accrued)
- Overhead (depreciation, utilities)

Of this 3,133,900:
- 2,862,300 becomes COGS (expensed)
- 271,600 becomes inventory (capitalized)

When we compute NI, we subtract only the 2,862,300 (the COGS portion). The
271,600 is NOT expensed, so it doesn't reduce NI.

But the 271,600 WAS spent (cash or accrual). If it was cash, we need to subtract
it from CFO. If it was accrued, we don't.

**The issue is that my working capital model doesn't separate "production costs
unpaid" from "production costs paid as cash".** In the simplified model with
theta_AP = 15% of COGS, AP relates only to expensed COGS, not to inventory build.

To fix this: either (a) treat 100% of production as cash (no AP), or (b) AP
covers full production cost (not just COGS).

**Cleanest fix**: AP ratio is applied to total production cost, not COGS. So:
```
AP = 0.15 * (production * unit_cost)
   = 0.15 * 3,133,900
   = 470,085
```

Let me redo with this convention:

```
Target AP = 0.15 * 3,133,900 = 470,085
ΔAP = 470,085 - 402,570 = 67,515
```

Payment flow:
- Pay prior AP: 402,570 (cash out)
- Incur new AP: 470,085 (deferred)
- Net AP payment this Q: 402,570 - 0.15 * prior_production_cost...

Actually wait, this is getting complicated. Let me use a different, cleaner
convention: **Production cost is ALL paid in cash** (no AP). Inventory is
financed by cash. Then AP applies only to COGS-related purchases during the
period, which is effectively the same as the old theta_AP = 15% of COGS.

Under this cleaner rule:
- Cost of production 3,133,900 is entirely cash outflow
- AP ratio becomes a lag on COGS-specific vendor payments, which is a separate
  abstraction. For simplicity, let's REMOVE AP and assume cash-basis supplier
  payments.

But that changes the whole model. Let me try yet another approach that keeps
the accrual model.

**Alternative fix: separate the inventory-building cash from the COGS-related cash**.

Direct method breakdown:
```
Cash to suppliers for COGS-related materials = COGS - ΔAP (AP applies to COGS)
                                              = 2,862,300 - 26,775
                                              = 2,835,525

Cash to build inventory (not yet in COGS) = production_cost - COGS
                                          = 3,133,900 - 2,862,300
                                          = 271,600
```

Total cash to suppliers = 2,835,525 + 271,600 = 3,107,125

Then:
```
CFO direct =
  Cash from revenue + AR:    18,205,000
  - Cash to suppliers:       (3,107,125)
  - Cash for R&D+SGA:       (41,500,000)
  - Interest:                        0
  - Taxes:                           0
  = CFO:                    (26,402,125)
```

This matches the indirect method. **Good.**

So the actual CFO is **(26,402,125)**, not (26,130,525). My direct method above
missed the inventory build cost.

Let me recompute ending cash:
```
Starting cash: 303,655,570
+ CFO:         (26,402,125)
+ CFI:         (15,000,000)
+ CFF:                   0
= Ending cash: 262,253,445
```

That's 262,253,445 (not 262,253,645 as I had before). The 200 discrepancy was in my
arithmetic.

Let me re-verify:
```
303,655,570
- 26,402,125 = ?

303,655,570
-26,402,125
----------
277,253,445  (303M - 26M = 277M, then adjustments)

Actually: 303,655,570 - 26,402,125
= 303,655,570 - 26,000,000 - 402,125
= 277,655,570 - 402,125
= 277,253,445

Then: 277,253,445 - 15,000,000 = 262,253,445
```

Ending cash = **262,253,445**.

Recomputing total assets:
```
262,253,445 + 2,760,000 + 569,800 + 38,750,000
```
```
262,253,445 + 2,760,000 = 265,013,445
265,013,445 + 569,800 = 265,583,245
265,583,245 + 38,750,000 = 304,333,245
```

Total assets = **304,333,245**.

Total L+E was **304,333,245** (computed earlier).

**BALANCE SHEET IDENTITY: 304,333,245 = 304,333,245 ✓ PASS**

The original $200 error was an arithmetic slip in cash computation. With the
corrected cash of 262,253,445 (not ...645), everything balances.

### Invariant 2: Cash Reconciliation

```
ΔCash = CFO + CFI + CFF
      = (26,402,125) + (15,000,000) + 0
      = (41,402,125)

Ending cash - starting cash = 262,253,445 - 303,655,570 = (41,402,125) ✓
```

### Invariant 3: Retained Earnings Roll-Forward

```
RE_end = RE_start + NI - dividends + other_comprehensive_income
       = (23,208,800) + (27,087,300) - 0 + 0
       = (50,296,100) ✓
```

### Invariant 4: Inventory Continuity

```
End inv = Start inv + production_cost - COGS
        = 298,200 + 3,133,900 - 2,862,300
        = 569,800 ✓
```

### Invariant 5: PPE Continuity

```
End PPE gross = Start PPE gross + capex
              = 25,000,000 + 15,000,000
              = 40,000,000 ✓

End accum dep = Start accum dep + Q2 dep
              = 625,000 + 625,000
              = 1,250,000 ✓
```

### Invariant 6: Non-Negative Cash

```
Ending cash = 262,253,445 > 0 ✓
```

### Invariant 7: Non-Negative Total Assets

```
atq = 304,333,245 > 0 ✓
```

---

## Section 11: Final Ending State Snapshot

```
Firm: firm_0
Quarter: Q2 2031
Status: active

BALANCE SHEET
  Cash:                      262,253,445
  Accounts receivable:         2,760,000
  Inventory:                     569,800
  PPE gross:                  40,000,000
  Accum depreciation:         (1,250,000)
  PPE net:                    38,750,000
  TOTAL ASSETS               304,333,245

  Accounts payable:              429,345
  Accrued expenses:            4,200,000
  Taxes payable:                       0
  Current debt:                        0
  Long-term debt:                      0
  TOTAL LIABILITIES            4,629,345

  Common stock:                   10,000
  APIC:                      349,990,000
  Retained earnings:         (50,296,100)
  Treasury stock:                      0
  TOTAL EQUITY               299,703,900

  LIAB + EQUITY              304,333,245  ✓

INCOME STATEMENT
  Revenue:                    18,400,000
  COGS:                        2,862,300
  Gross profit:               15,537,700
  R&D expense:                28,000,000
  SGA expense:                14,000,000
  Depreciation:                  625,000
  Operating income:          (27,087,300)
  Interest:                            0
  Pretax income:             (27,087,300)
  Tax expense:                         0
  NET INCOME                 (27,087,300)

CASH FLOW STATEMENT
  CFO:                       (26,402,125)
  CFI:                       (15,000,000)
  CFF:                                 0
  CHANGE IN CASH             (41,402,125)

INTERNAL STATE
  Capability stock (A):             47.64
  Brand stock (B):                  24.83
  Cumulative product R&D:      20,800,000
  Cumulative process R&D:       8,250,000
  Cumulative delivery R&D:      4,950,000
  NOL carryforward:            50,296,100
  Product generation:                   1
  Capacity:                           250
  Effective unit cost:             14,245
```

---

## Section 12: Notes for the Implementation

### Issues Found During This Exercise

1. **Doc 09 parameter bug**: eta_A and eta_B in doc 09 are stated as "0.0008 per $1M"
   and "0.0015 per $1M" but the example in doc 09 says "$30M/quarter -> +24 points".
   The correct values are **eta_A = 0.8 per $1M** and **eta_B = 1.5 per $1M**.
   Doc 09 needs correction.

2. **Working capital timing**: The convention used here is:
   - AR = theta_AR * current quarter revenue (NOT including prior AR)
   - Prior period AR is fully collected each quarter (100% turnover)
   - AP = theta_AP * current quarter COGS (NOT production cost)
   - Prior period AP is fully paid each quarter
   - Accrued = theta_accrued * (R&D + SGA) of current quarter
   - Prior period accrued is fully settled each quarter

3. **Inventory build as non-cash**: Production cost exceeds COGS by the inventory
   build amount (271,600 in this example). This must be treated as a cash outflow
   in the CFO statement (the cost was incurred but not expensed). The indirect
   method does this automatically via the ΔInventory adjustment. The direct
   method must separately account for the inventory build cash.

4. **Depreciation timing**: Q2 capex is added to PPE gross but does not generate
   Q2 depreciation (placed in service at end of quarter, depreciates starting Q3).
   This is a conservative convention.

5. **Inventory FIFO**: Old inventory sold first at old cost; new units sold at new
   cost. This matches standard FIFO accounting.

6. **NOL tracking**: Retained earnings and cumulative NOL should equal each other
   (negated) as long as no dividends and no OCI. This is a useful cross-check.

### What This Example Does NOT Cover

- Stock-based compensation (toggle OFF)
- Lease accounting (toggle OFF)
- Goodwill / M&A (toggle OFF)
- Restructuring charges (no layoffs)
- R&D capitalization (baseline GAAP regime)
- Fair value adjustments (baseline GAAP regime)
- Diluted shares (no options/warrants)
- Process R&D generation advance (below threshold)
- Interest expense (no debt)
- Tax expense (pretax loss)
- Revolver draws (not needed)

Each of these should get its own worked example as the corresponding feature
is implemented.

---

## Section 13: Test Fixture (for pytest)

```python
# tests/fixtures/q2_2031_firm_0.py

STARTING_STATE = FirmState(
    firm_id="firm_0",
    quarter=1,  # END of Q1
    cash=303_655_570,
    accounts_receivable=2_565_000,
    inventory_units=20,
    inventory_value=298_200,
    ppe_gross=25_000_000,
    accum_depreciation=625_000,
    accounts_payable=402_570,
    accrued_expenses=3_700_000,
    taxes_payable=0,
    revolver_balance=0,
    long_term_debt=0,
    common_stock=10_000,
    apic=349_990_000,
    retained_earnings=-23_208_800,
    treasury_stock=0,
    shares_outstanding=10_000_000,
    capability_stock=40.0,
    brand_stock=11.25,
    rd_cumulative_product=10_000_000,
    rd_cumulative_process=3_750_000,
    rd_cumulative_delivery=2_250_000,
    nol_carryforward=23_208_800,
    product_generation=1,
    capacity_units=250,
    base_unit_cost=14_200,
)

Q2_DECISIONS = Decisions(
    price=92_000,
    production=220,
    capex=15_000_000,
    rd_spend=28_000_000,
    rd_allocation={"product": 0.60, "process": 0.25, "delivery": 0.15},
    sga_spend=14_000_000,
    equity_issuance_request=0,
    debt_request=0,
    dividends=0,
    buybacks=0,
)

Q2_OUTCOMES = MarketOutcomes(
    firm_id="firm_0",
    units_sold=200,
    market_share=0.22,
    product_rd_advance=False,
    process_cogs_reduction_this_quarter=0.0,
    delivery_advance=False,
)

EXPECTED_END_STATE = FirmState(
    firm_id="firm_0",
    quarter=2,
    cash=262_253_445,
    accounts_receivable=2_760_000,
    inventory_units=40,
    inventory_value=569_800,
    ppe_gross=40_000_000,
    accum_depreciation=1_250_000,
    accounts_payable=429_345,
    accrued_expenses=4_200_000,
    taxes_payable=0,
    revolver_balance=0,
    long_term_debt=0,
    common_stock=10_000,
    apic=349_990_000,
    retained_earnings=-50_296_100,
    treasury_stock=0,
    shares_outstanding=10_000_000,
    capability_stock=47.64,
    brand_stock=24.825,
    rd_cumulative_product=20_800_000,
    rd_cumulative_process=8_250_000,
    rd_cumulative_delivery=4_950_000,
    nol_carryforward=50_296_100,
    product_generation=1,
    capacity_units=250,
    base_unit_cost=14_200,
)

EXPECTED_FLOWS = QuarterFlows(
    # Income statement
    net_sales=18_400_000,
    cogs=2_862_300,
    gross_profit=15_537_700,
    rd_expense=28_000_000,
    sga_expense=14_000_000,
    depreciation=625_000,
    operating_income=-27_087_300,
    interest_expense=0,
    pretax_income=-27_087_300,
    tax_expense=0,
    net_income=-27_087_300,
    # Cash flow
    cfo=-26_402_125,
    cfi=-15_000_000,
    cff=0,
    change_in_cash=-41_402_125,
    # Actuals (after clamping -- no clamping in this example)
    actual_price=92_000,
    actual_production=220,
    actual_capex=15_000_000,
    actual_rd_spend=28_000_000,
    actual_sga_spend=14_000_000,
    units_sold=200,
    market_share=0.22,
)


def test_q2_2031_posting():
    result_state, result_flows = post_quarter(
        prior_state=STARTING_STATE,
        decisions=Q2_DECISIONS,
        outcomes=Q2_OUTCOMES,
        params=DEFAULT_PARAMS,
    )

    assert_state_equal(result_state, EXPECTED_END_STATE, tol=1.0)
    assert_flows_equal(result_flows, EXPECTED_FLOWS, tol=1.0)

    # Invariants
    assert abs(result_state.total_assets - result_state.total_liabilities - result_state.total_equity) < 1.0
    assert result_state.cash >= 0
    assert result_state.total_assets >= 0
    assert result_state.retained_earnings == STARTING_STATE.retained_earnings + result_flows.net_income
    assert result_flows.change_in_cash == result_flows.cfo + result_flows.cfi + result_flows.cff
```

This fixture becomes the first regression test. Any change to the accounting
module must produce these exact numbers (within $1 tolerance for rounding).
