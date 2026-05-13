# Compustat Completeness and Expanded Decisions

## Goal

The simulation should generate a quarterly panel that covers the most important
Compustat Quarterly variables. This means the simulated world must create enough
economic activity to populate these columns meaningfully -- not as afterthoughts,
but as natural consequences of firm decisions and market outcomes.

---

## Gap Analysis: Current Panel vs. Real Compustat

### Variables Already Covered (40 columns)

Our current panel covers the core of Compustat Quarterly well:

**Income Statement**: saleq, cogsq, gpq, xrdq, xsgaq, dpq, oiadpq, xintq, piq, txtq, niq

**Balance Sheet -- Assets**: cheq, rectq, invtq, ppentq, atq

**Balance Sheet -- Liabilities**: apq, acoq, txpq, dlcq, lctq, dlttq, ltq

**Balance Sheet -- Equity**: cstkq, ceqq, req

**Cash Flow**: oancfq, ivncfq, fincfq, chechq, capxq

**Equity & Market**: sstkq, prstkq, dvq, prccq, cshoq, mkvaltq

**Custom**: default_flag, pricing_error

### Variables Missing (Important Compustat Fields)

| Variable | Compustat Name | What It Requires | Priority |
|----------|---------------|-----------------|----------|
| **Goodwill** | gdwlq | M&A transactions (now supported) | High |
| **Goodwill impairment** | gdwlipq | Impairment testing post-acquisition | High |
| **Acquisition amount** | aqaq | M&A transactions | High |
| **Intangible assets** | intanq | R&D capitalization regime, acquired IP | High |
| **Other income/expense** | nopiq / spiq | Gains/losses on asset sales, one-time items | Medium |
| **Accounts receivable (gross)** | rectrq | Credit losses / bad debt reserve | Medium |
| **Allowance for doubtful accounts** | -- | Bad debt experience | Medium |
| **Prepaid expenses** | xppq | Advance payments for raw materials | Low |
| **Other current assets** | acoq (asset side) | Miscellaneous current assets | Low |
| **Deferred revenue** | drcq | Advance patient payments (if applicable) | Medium |
| **Other long-term liabilities** | loq | Pension, lease obligations, contingencies | Medium |
| **Additional paid-in capital** | apicq | Already tracked internally, add to panel | High |
| **Treasury stock** | tstkq | Buyback accounting | High |
| **Accumulated OCI** | aociq | Fair value regime, pension adjustments | Medium |
| **Revenue per segment** | -- | Geographic or product-line breakdowns | Low |
| **Employees** | empq | Workforce tracking (already in dossier) | Medium |
| **Capital lease obligations** | -- | If facility leasing is modeled | Low |
| **Pension/retirement expense** | -- | If workforce benefits are modeled | Low |
| **Earnings per share** | epsfxq / epsfiq | Computed from NI and shares | High |
| **Book value per share** | bkvlps | Computed from equity and shares | High |
| **Dividends per share** | dvpsxq | Computed from dividends and shares | High |
| **Operating lease expense** | -- | Facility costs | Low |
| **Restructuring charges** | rcq | Post-acquisition integration, layoffs | Medium |

---

## Expanded Decision Set

To populate the missing variables, firms need to make richer decisions and the
world needs to generate richer events:

### New Firm Decisions

| Decision | Populates | Description |
|----------|-----------|-------------|
| **Workforce plan** | empq, restructuring | Hiring target, layoff decision, compensation level |
| **Working capital policy** | rectq, invtq, apq, drcq | Collection aggressiveness, inventory target, payment terms |
| **Debt management** | dlcq, dlttq | Repayment schedule, refinancing request |
| **M&A proposal** | gdwlq, aqaq, intanq | Acquisition offer (see doc 10) |
| **Asset disposal** | nopiq, spiq | Sell idle equipment, close a facility |
| **Lease vs. buy** | loq | Lease facilities instead of building (capex) |
| **Reserves and provisions** | acoq (liability), loq | Litigation reserves, warranty provisions |

### Expanded Firm Decision JSON

```json
{
  "price": 92000,
  "production": 220,
  "capex": 20000000,
  "rd_spend": 30000000,
  "rd_allocation": {"product": 0.55, "process": 0.25, "delivery": 0.20},
  "sga_spend": 15000000,

  "workforce": {
    "hiring_target": 25,
    "layoff_count": 0,
    "avg_compensation_increase_pct": 3.0
  },

  "working_capital": {
    "collection_aggressiveness": "normal",
    "inventory_target_quarters": 1.5,
    "supplier_payment_terms": "net_45"
  },

  "debt_management": {
    "term_debt_repayment": 0,
    "refinancing_request": false
  },

  "asset_disposal": {
    "dispose_assets": false,
    "assets_to_dispose": []
  },

  "provisions": {
    "litigation_reserve_addition": 2000000,
    "warranty_reserve_addition": 500000
  },

  "ma_proposal": null,

  "equity_issuance_request": 0,
  "debt_request": 0,
  "dividends": 0,
  "buybacks": 0,

  "reasoning": "..."
}
```

### Expanded Environment Outcomes

The environment now also generates:

```json
{
  "firm_outcomes": [
    {
      "firm_id": "firm_0",
      "units_sold": 19200,
      "market_share": 0.217,
      "bad_debt_pct": 0.02,
      "patient_lawsuits_filed": 1,
      "employee_departures": 3,
      "supplier_issues": "none",
      "special_items": []
    }
  ],
  "industry_events": [
    {
      "type": "restructuring",
      "affected_firm": "firm_3",
      "description": "Firm 3 announced facility closure and 15% workforce reduction",
      "restructuring_charge": 25000000
    }
  ]
}
```

---

## Expanded Compustat Panel (Final Column List)

### Income Statement (18 columns)

| Column | Name | Source |
|--------|------|--------|
| saleq | Net sales | units_sold * price |
| cogsq | Cost of goods sold | units_sold * unit_cost |
| gpq | Gross profit | saleq - cogsq |
| xrdq | R&D expense | actual_rd_spend (or net of capitalization) |
| xsgaq | SGA expense | actual_sga + compensation costs |
| dpq | Depreciation & amortization | PPE depreciation + intangible amort |
| gdwlipq | Goodwill impairment | From impairment test (if M&A) |
| rcq | Restructuring charges | Layoffs, facility closure |
| oiadpq | Operating income | gpq - xrdq - xsgaq - dpq - gdwlipq - rcq |
| nopiq | Non-operating income | Asset sale gains/losses, one-time items |
| xintq | Interest expense | On all debt |
| spiq | Special items | Unusual one-time events |
| piq | Pretax income | oiadpq + nopiq - xintq + spiq |
| txtq | Tax expense | max(0, piq * tax_rate) with loss carryforward |
| niq | Net income | piq - txtq |
| epsfxq | EPS (fully diluted) | niq / diluted_shares |
| epsfiq | EPS (basic) | niq / shares_outstanding |
| dvpsxq | Dividends per share | dvq / cshoq |

### Balance Sheet -- Assets (14 columns)

| Column | Name | Source |
|--------|------|--------|
| cheq | Cash | Settlement residual |
| rectq | Accounts receivable (net) | theta_AR * saleq - allowance |
| invtq | Inventories | Unsold units * unit_cost |
| xppq | Prepaid expenses | Raw material deposits |
| acoq_a | Other current assets | Miscellaneous |
| actq | Total current assets | Sum of above |
| ppentq | PP&E (net) | Gross PPE - accum depreciation |
| intanq | Intangible assets | Capitalized R&D + acquired IP |
| gdwlq | Goodwill | From M&A (purchase price - fair value) |
| aoq | Other long-term assets | Miscellaneous |
| atq | Total assets | actq + ppentq + intanq + gdwlq + aoq |

### Balance Sheet -- Liabilities (13 columns)

| Column | Name | Source |
|--------|------|--------|
| apq | Accounts payable | theta_AP * cogsq |
| acoq | Accrued expenses | Wages, utilities, other accruals |
| txpq | Taxes payable | Current quarter tax due |
| drcq | Deferred revenue | Advance patient payments (if any) |
| dlcq | Current debt | Revolver balance + current portion of LTD |
| lctq | Total current liabilities | Sum of above |
| dlttq | Long-term debt | Term debt (non-current portion) |
| loq | Other long-term liabilities | Litigation reserves, provisions, leases |
| ltq | Total liabilities | lctq + dlttq + loq |

### Balance Sheet -- Equity (8 columns)

| Column | Name | Source |
|--------|------|--------|
| cstkq | Common stock (par) | Shares * par value |
| apicq | Additional paid-in capital | IPO + secondary proceeds above par |
| req | Retained earnings | Cumulative NI - cumulative dividends |
| tstkq | Treasury stock | Cumulative buybacks at cost |
| aociq | Accumulated OCI | Fair value adjustments (if FV regime) |
| ceqq | Total common equity | cstkq + apicq + req - tstkq + aociq |

### Cash Flow Statement (8 columns)

| Column | Name | Source |
|--------|------|--------|
| oancfq | Operating cash flow | NI + depreciation + WC changes + non-cash |
| ivncfq | Investing cash flow | -capex - acquisitions + asset sale proceeds |
| fincfq | Financing cash flow | Equity + debt - repayments - div - buybacks |
| chechq | Change in cash | oancfq + ivncfq + fincfq |
| capxq | Capital expenditure | Actual capex posted |
| aqaq | Acquisition spending | Cash paid for acquisitions |
| sstkq | Stock issuance | Equity raised this quarter |
| prstkq | Stock repurchase | Buybacks this quarter |
| dvq | Dividends paid | Cash dividends this quarter |

### Market & Other (10 columns)

| Column | Name | Source |
|--------|------|--------|
| prccq | Stock price | Set by investment bank |
| cshoq | Shares outstanding | |
| mkvaltq | Market capitalization | prccq * cshoq |
| bkvlpsq | Book value per share | ceqq / cshoq |
| empq | Employees | From workforce tracking |
| default_flag | Default indicator | |
| acquiree_flag | Was acquired this quarter | |
| acquirer_flag | Made acquisition this quarter | |
| pricing_error | P - P* | For research |
| run_id / firm_id / incarnation / fyearq / fqtr | Keys | |

**Total: ~76 columns** (vs. 44 previously)

---

## Validation Invariants (Updated)

### Hard Invariants

All previous invariants remain. New additions:

- `atq == actq + ppentq + intanq + gdwlq + aoq` (asset decomposition)
- `lctq == apq + acoq + txpq + drcq + dlcq` (current liabilities decomposition)
- `ltq == lctq + dlttq + loq` (total liabilities decomposition)
- `ceqq == cstkq + apicq + req - tstkq + aociq` (equity decomposition)
- `gdwlq >= 0` (goodwill cannot be negative)
- `gdwlipq >= 0` (impairment is a loss, recorded as positive expense)
- `empq >= 0` (non-negative employees)
- `epsfxq == niq / diluted_shares` (within rounding)

### Soft Invariants

- `empq` should track roughly with revenue and SGA trends
- `gdwlq` only changes on acquisitions or impairments
- `intanq` only changes under R&D capitalization regime
- `aqaq > 0` only in quarters with actual acquisitions

---

## What Drives Each Compustat Variable

This mapping ensures that every column has an explicit economic mechanism:

| Variable | Driven By |
|----------|----------|
| saleq | Demand system (environment) * firm's price |
| cogsq | Production volume * unit cost (driven by process R&D, scale) |
| xrdq | Firm's R&D decision (clamped by feasibility) |
| xsgaq | Firm's SGA decision + workforce compensation |
| dpq | PPE depreciation schedule + intangible amortization |
| gdwlipq | Annual goodwill impairment test |
| rcq | Firm's restructuring decision + environment events |
| xintq | Outstanding debt * interest rates (set by banks) |
| txtq | Tax code applied to pretax income |
| cheq | Residual from all cash flows |
| rectq | Revenue * collection cycle - bad debt |
| invtq | Production - sales, valued at unit cost |
| ppentq | Prior PPE + capex - depreciation |
| intanq | Capitalized R&D + acquired intangibles - amortization |
| gdwlq | Acquisition premium - impairments |
| apq | COGS * payment cycle |
| acoq | Wages payable + accrued expenses |
| dlcq | Revolver balance + LTD current portion |
| dlttq | Term debt issued - repayments - reclassification to current |
| loq | Litigation reserves + lease obligations + provisions |
| prccq | Investment bank valuation |
| empq | Firm workforce decisions + environment attrition |
