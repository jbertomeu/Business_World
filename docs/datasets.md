# WRDS-Style Datasets + Audit-Trail Files

Every run writes **21 CSVs + 4 JSONL files + snapshot pickles** to
`outputs/<run_id>/`. They mimic the schemas of real research datasets
(Compustat, ExecuComp, Audit Analytics, I/B/E/S, Thomson Reuters Insider
Filings, Mergent FISD, SEC First Call) and add simulation-specific
provenance / audit trails.

This document lists each dataset, its real-world analog, its row granularity,
and its key columns. Column names follow WRDS conventions (e.g. `saleq`,
`atq`, `ltq`) where a direct analog exists. Simulated-only columns are
flagged **SIM**.

---

## Quick reference

| Dataset | Rows | Granularity | Analog |
|---|---|---|---|
| `compustat_q.csv` | firm × quarter | quarterly panel | `comp.fundq` |
| `compustat_a.csv` | firm × fyear | annual funda | `comp.funda` |
| `compustat_restated.csv` | firm × quarter | as-restated panel | `comp.fundq` post-restatement |
| `execucomp.csv` | firm × fyear | annual CEO comp | ExecuComp `anncomp` |
| `execucomp_grants.csv` | grant event | one per new grant | ExecuComp Grants of Plan-Based Awards |
| `execucomp_outstanding.csv` | firm × fyear | year-end holdings | ExecuComp Outstanding Equity Awards |
| `ceo_turnover.csv` | CEO transition event | one per fire/retire/hire | ExecuComp transitions |
| `audit_analytics.csv` | firm × fyear | annual audit | Audit Analytics Opinions |
| `restatements.csv` | restatement event | one per restatement | AA Restatements |
| `analyst_forecasts.csv` | analyst × firm × quarter | one per note | I/B/E/S Detail |
| `management_forecasts.csv` | guidance event | one per guidance | First Call Guidance |
| `debt_facilities.csv` | facility | one per debt instrument | custom (FISD for bonds) |
| `debt_covenants.csv` | covenant | one per covenant on a facility | DealScan |
| `covenant_tests_panel.csv` | firm × quarter × facility × covenant | every test | custom |
| `covenant_violations.csv` | violation event | one per covenant breach | custom |
| `bond_issuances.csv` | bond issuance | one per bond/convertible | Mergent FISD |
| `bad_debt_events.csv` | firm × quarter | write-offs + allowance | custom |
| `annual_reports.csv` | firm × fyear | aggregate 10-K-style | custom |
| `insider_transactions.csv` | CEO event | grant / sell / exercise | Thomson Reuters Insider Filings / SEC Form 4 |
| `activist_campaigns.csv` | campaign event | one per activist demand + response | 13D/G disclosures + news |
| `crosswalk.csv` | entity | one per firm/CEO/facility/security/grant/product | crosswalk / link tables |

## Audit-trail and provenance files (Wave α/β/γ/δ/ε)

| File | Row unit | When written | Purpose |
|---|---|---|---|
| `proposals.jsonl` | Action + ActionResult | every LLM-driven mutation | Full structured-action audit trail. FK target for `compustat_q.proposal_id`. Every firm / auditor / SEC / activist / IB / CB / governance / M&A / earnings / analyst decision. **Includes `actor_class`** (Wave θ) for easy filtering: firm, auditor, analyst, sec, investment_bank, commercial_bank, activist, board_governance, ma, environment. |
| `negotiations.jsonl` | completed negotiation | covenant waiver / debt pricing / activist campaign / M&A auction / audit fee | Multi-round bargaining history with per-round offers, rationales, and final outcomes. |
| `bs_violations.jsonl` | BS identity drift event | whenever `atq - ltq - ceqq` exceeds $1 at a phase boundary | Empty on clean runs. Localizes any BS drift to the phase that introduced it, with full BS component snapshot for debugging. |
| `broker_queries.jsonl` | data-broker query | when agents use data-broker tool | Records WRDS-style queries issued by LLM agents during reasoning. |
| `llm_calls.jsonl` | per LLM API call | each successful `backend.complete()` response | Wave θ: one row per call with `model`, `input_tokens`, `output_tokens`, `latency_ms`, `t` (seconds-since-run-start). |
| `cost_summary.txt` | run rollup | at run end | Wave θ: human-readable token totals (per-model and grand total), wallclock time, mean latency per model. |
| `snapshots/Q{N}.pkl` | WorldState pickle | every quarter end | Complete state checkpoint. Loaded by `--restart-from` flag to resume. ~60-80 KB per quarter. |

All datasets share a `run_id` column for cross-run research. Firm
identifiers (`firm_id`, `tic`, `conm`, `sic`, `cusip`) are stable across
runs for the same firm slot.

---

## Compustat quarterly (`compustat_q.csv`)

**One row per firm × quarter.** Follows WRDS `comp.fundq` field names.

### Identifiers
| Column | Meaning |
|---|---|
| `run_id` | unique run tag |
| `firm_id` | `firm_0`…`firm_N` |
| `incarnation` | re-entrant firm identity (if a firm defaults + a new firm takes the slot) |
| `fyearq`, `fqtr` | fiscal year, fiscal quarter |
| `datadate` | quarter-end date |
| `tic`, `conm`, `sic`, `cusip` | stable firm identifiers |
| `indfmt`, `consol`, `popsrc`, `datafmt` | Compustat metadata (INDL/C/D/STD) |

### Income statement (quarter)
| | |
|---|---|
| `saleq` | net sales / revenue |
| `cogsq` | cost of goods sold |
| `gpq` | gross profit |
| `xrdq` | R&D expense |
| `xsgaq` | SG&A expense |
| `dpq` | depreciation & amortization |
| `oiadpq` | operating income after depreciation |
| `xintq` | interest expense |
| `rcp` | restructuring cost / charge |
| `piq` | pretax income |
| `txtq` | income taxes |
| `niq` | net income (as reported — includes earnings management) |
| `spioq` | special items (restructuring + legal charge) |

### Balance sheet (quarter-end)
| | |
|---|---|
| `cheq` | cash & equivalents |
| `rectq` | receivables |
| `invtq` | inventories |
| `ppentq`, `ppegtq` | net / gross PP&E |
| `actq` | total current assets |
| `atq` | total assets |
| `apq` | accounts payable |
| `xaccq` | accrued expenses |
| `txpq` | taxes payable |
| `drcq` | deferred revenue (current) |
| `dlcq` | current portion of long-term debt (= revolver) |
| `dlttq` | long-term debt |
| `lctq` | total current liabilities |
| `ltq` | total liabilities |
| `cstkq` | common stock (par value) |
| `apicq` | additional paid-in capital |
| `ceqq`, `seqq` | common equity / stockholders' equity |
| `req` | retained earnings |
| `tstkq` | treasury stock |
| `gdwlq` | goodwill |

### Cash flow (quarter)
| | |
|---|---|
| `oancfq` | cash flow from operations |
| `ivncfq` | cash flow from investing |
| `fincfq` | cash flow from financing |
| `chechq` | change in cash |
| `capxq` | capital expenditures |
| `dvq` | dividends paid |
| `sstkq` | stock issued |
| `prstkq` | stock repurchased |

### Market
| | |
|---|---|
| `prccq` | quarter-end share price |
| `cshoq` | common shares outstanding (millions, WRDS convention) |
| `mkvaltq` | market value (millions) |

### Stage 5 additions (bad debt)
| | |
|---|---|
| `allowance_dca` | allowance for doubtful accounts |
| `bad_debt_expense` | quarterly bad-debt expense |
| `write_offs` | write-offs this quarter |

### Stage 12 additions (legal / pension / deferred tax)
| | |
|---|---|
| `legal_reserve_bs` | legal loss-contingency reserve (liability) |
| `pension_liability_bs` | pension benefit obligation |
| `pension_service_cost` | quarterly pension service cost (IS) |
| `pension_contribution` | quarterly pension contribution (CFO) |
| `txditcq` | deferred tax liability |

### Simulation-only
| | |
|---|---|
| `default_flag` | 1 if firm is inactive (bankrupt/delisted) as of this quarter |
| `manipulation_amount` **SIM** | hidden truth of accrual manipulation this Q (≠ reported) |
| `restatement_flag` | 1 if this row was restated |
| `saleq_restated`, `cogsq_restated`, ... | restated values (NULL when no restatement) |
| `empq` | employee count (proxy derived from SGA / $50K) |

### Identities that MUST hold
- BS: `atq = ltq + ceqq` (tolerance < $1)
- CFS: `chechq = oancfq + ivncfq + fincfq` (tolerance < $1)
- Current assets: `actq ≤ atq`

---

## Compustat annual (`compustat_a.csv`)

**One row per firm × fiscal year.** Mirrors WRDS `comp.funda`. IS / CF lines =
SUM across the four quarters; BS lines = year-end snapshot. Columns drop the
`q` suffix: `sale`, `ni`, `at`, etc. Annual-only additions:

- `bad_debt_expense_a`, `write_offs_a`, `allowance_dca` (Stage 5)
- `spi`, `pension_expense_a`, `pension_liability_eoy`, `legal_reserve_bs_eoy`, `txditc` (Stage 12)

---

## ExecuComp (`execucomp.csv`)

**One row per firm × fyear.** Stored at end-of-Q4 governance.

| Column | Meaning |
|---|---|
| `ceo_id`, `ceo_type` | hidden type: `aggressive_grower`, `conservative_steward`, `empire_builder`, `honest_operator` |
| `age`, `tenure_years` | CEO demographics |
| `salary` | base salary for the year |
| `bonus` | cash bonus this year |
| `stock_awards_value`, `option_awards_value` | fair value of grants this year |
| `total_comp` | salary + bonus + stock + options |
| `shares_owned_eoy` | vested RSU shares held at year-end |
| `shares_sold_this_year`, `shares_sold_cumulative` | |
| `cash_from_sales_cumulative` | CEO personal liquidity |
| `vested_options_held`, `unvested_options_held` | |
| `intrinsic_value_vested_options` | ITM value at year-end |
| `fired_flag`, `retired_flag`, `hired_flag` | transition flags this year |

---

## ExecuComp Grants (`execucomp_grants.csv`)

**One row per new grant.** Granted at IPO (founding package) and at Q4
governance reviews.

| Column | Meaning |
|---|---|
| `grant_id`, `ceo_id`, `grant_quarter`, `grant_date` | |
| `grant_type` | `rsu` or `stock_option` |
| `shares`, `strike_price` | at grant |
| `fair_value_at_grant` | FV for SBC amortization |
| `vesting_schedule_json` | list of `(quarter_offset, fraction)` tuples |
| `first_vest_quarter`, `last_vest_quarter` | schedule bounds |

---

## ExecuComp Outstanding (`execucomp_outstanding.csv`)

**One row per firm × fyear.** Year-end snapshot of what the CEO holds.
Mirrors ExecuComp's Outstanding Equity Awards table.

| Column | Meaning |
|---|---|
| `unvested_rsu_shares`, `unvested_option_shares` | still vesting |
| `vested_rsu_held_shares`, `vested_option_shares` | vested, unsold |
| `intrinsic_value_vested_options` | ITM cash value at current price |
| `intrinsic_value_unvested` | expected value of unvested at current price |
| `total_shares_sold_to_date` | cumulative lifetime sells |
| `n_grants_outstanding` | number of grants with unvested/unforfeited shares |

---

## CEO Turnover (`ceo_turnover.csv`)

**One row per transition event.** `event_type ∈ {fired, retired, reviewed, hired}`.

| Column | Meaning |
|---|---|
| `event_quarter`, `event_type` | |
| `departing_ceo_id`, `departing_tenure_quarters`, `departing_age` | |
| `incoming_ceo_id` | (same as departing for review-without-change) |
| `reason` | LLM-authored rationale |
| `severance`, `new_rsu_shares`, `new_option_shares`, `cash_bonus_this_year`, `base_salary_next_year` | |

---

## Audit Analytics (`audit_analytics.csv`)

**One row per firm × fyear.** Annual audit opinions.

| Column | Meaning |
|---|---|
| `auditor_id` | `auditor_1`…`auditor_4` (Hartley & Moran, Kaplan Pierce, Eastwood Young, Nakamura Global) |
| `opinion` | `unqualified` / `qualified` / `adverse` |
| `findings` | LLM-authored detail |
| `fee` | audit fee (LLM-proposed within ±60% of size-based benchmark) |
| `going_concern_flag` | 1 if auditor flags going-concern doubt |
| `auditor_tenure_years` | continuous tenure on this client |
| `recommended_restatement` | auditor forced a restatement |

---

## Restatements (`restatements.csv`)

**One row per restatement event.**

| Column | Meaning |
|---|---|
| `announcement_q`, `announcement_date` | |
| `trigger` | `auditor_forced` / `sec_forced` / `voluntary` |
| `restated_periods` | list of `(fyear, fqtr)` restated |
| `original_ni_sum`, `restated_ni_sum` | pre vs post adjustment |
| `ni_delta_pct` | % change |
| `reason` | |

---

## Analyst Forecasts (`analyst_forecasts.csv`)

**One row per analyst note.** Each analyst covers each firm when they publish
(staggered: analyst 1 = Q1/Q3, analyst 2 = Q2/Q4, analyst 3 = Q1/Q4).

| Column | Meaning |
|---|---|
| `analyst_id` | `analyst_1` (Chen/Meridian), `analyst_2` (Okonkwo/Atlantic), `analyst_3` (Marchetti/Pinnacle) |
| `methodology` | `fundamental_fsa_dcf` / `comparables` / `residual_income` |
| `forecast_q`, `target_q` | note date + forecast horizon |
| `eps_forecast`, `target_price`, `rating` | |
| `roe`, `npm`, `asset_turnover`, `leverage`, `rnoa`, `nbc`, `nfl` | financial snapshot fields |
| `quality_of_earnings` | `high` / `moderate` / `low` / `poor` |
| `actual_eps`, `forecast_error` | filled once actuals are known |
| `narrative` | 3-5 paragraph thesis |

---

## Management Forecasts (`management_forecasts.csv`)

**One row per guidance event (from earnings release).**

| Column | Meaning |
|---|---|
| `announcement_q`, `target_q` | |
| `eps_guidance`, `revenue_guidance` | |
| `actual_eps`, `actual_revenue` | filled on realization |
| `error` | realization - guidance |

---

## Debt: Facilities, Covenants, Tests, Violations, Bonds

Five linked tables modeling the debt structure at DealScan / FISD / covenant-
test granularity. See `src/types.py::DebtFacility` and `Covenant` for schema
details.

- `debt_facilities.csv` — one per instrument: `facility_type` ∈ {`bank_term`,
  `bank_revolver`, `bond`, `convertible_bond`, `commercial_paper`};
  `amortization_type` ∈ {`bullet`, `amortizing`}; maturity; coupon; status.
- `debt_covenants.csv` — covenant ∈ {`debt_to_ebitda_max`, `interest_coverage_min`,
  `min_liquidity`, `min_ebitda_ltm`, `debt_to_cap_max`, `capex_max`, `dividend_block`,
  `additional_debt_block`}; `threshold`.
- `covenant_tests_panel.csv` — quarterly test of every covenant on every
  facility: `ratio_value`, `passed`, `cushion_pct`.
- `covenant_violations.csv` — every breach: `resolution` ∈ {`waived`, `amended`,
  `accelerated`}; waiver fee; new threshold / rate; quarter of resolution.
- `bond_issuances.csv` — Mergent FISD-style: `bond_type`, `offering_amount`,
  `coupon_rate_annual`, `is_convertible`, `conversion_ratio`, `conversion_price`.

---

## Bad Debt (`bad_debt_events.csv`)

**One row per firm × quarter** (Stage 5).

| Column | Meaning |
|---|---|
| `gross_ar`, `allowance`, `net_ar` | |
| `bad_debt_expense`, `write_offs` | |
| `allowance_pct_of_ar` | CEO's estimate of uncollectible share |

---

## Annual Reports (`annual_reports.csv`)

**One row per firm × fyear.** 10-K-style aggregate: full-year IS / BS / CFS,
YoY growth, MD&A text, audit opinion, covenant violation count, forward
guidance.

---

## Insider Transactions (`insider_transactions.csv`)

**One row per CEO event** (Stage 12). Mirrors SEC Form 4 / Thomson Reuters
Insider Filings granularity.

| Column | Meaning |
|---|---|
| `ceo_id`, `ceo_incarnation` | attribution (tracks multiple CEOs across a firm's life) |
| `event_quarter`, `event_date` | |
| `event_type` | `grant` / `sell` / `exercise` |
| `transaction_shares` | |
| `transaction_price` | market price at event |
| `strike_price` | for `exercise` events only |
| `transaction_value` | shares × price or gross proceeds |
| `shares_held_after` | CEO's retained vested-held shares |
| `notes` | "Founding IPO grant" / "open-market sale" / "option exercise" etc. |

---

## Activist Campaigns (`activist_campaigns.csv`)

**One row per campaign event** (Stage 12). One activist LLM (`Ironbridge
Partners` / `activist_1`) scans the market each quarter.

| Column | Meaning |
|---|---|
| `event_quarter`, `event_date` | |
| `activist_id` | |
| `demand_type` | `buyback` / `divestiture` / `strategic_review` / `board_seat` |
| `demand_specifics` | 1-2 sentence demand |
| `stake_pct_implied` | activist's claimed stake (0-0.5) |
| `firm_response` | `accept` / `partial` / `negotiate` / `reject` (empty if campaign is open) |
| `firm_rationale` | CEO's defense or concession |

---

## Cross-run aggregation (`data/` directory)

Runs are accumulated:

- `data/compustat_all.csv` — every firm × quarter across every run (stacked panel)
- `data/compustat_a_all.csv` — annual version
- `data/run_index.csv` — one row per run with summary stats (`run_id`, `n_firms`,
  `n_quarters`, `seed`, `total_industry_revenue`, `n_defaults`, `final_active_firms`)
- `data/scores.csv` — scorecard per run (firm NPV / IRR, debt P&L, equity pricing
  accuracy)

Use `run_index.csv` + `run_id` to filter aggregate panels to specific experiments.

---

## Notes for researchers

1. **LLM nondeterminism**: real-LLM runs are NOT reproducible even with the
   same seed (backend randomness). Mock runs ARE reproducible — see
   `tests/test_reproducibility.py`.
2. **Multi-incarnation firms**: when a firm defaults, the slot can be filled by
   a new firm with the same `firm_id` but `incarnation=2`. Most analyses want
   `(firm_id, incarnation)` as the panel key, not just `firm_id`.
3. **Earnings management disclosure**: `niq` is what the firm reported.
   `manipulation_amount` is the hidden truth of accrual manipulation. Research
   on detection, restatements, and fraud can use both.
4. **Balance-sheet identities are asserted at write time** — any violation is
   a bug, not data quality noise. See `tests/test_accounting.py` +
   `tests/test_stage_12.py` for the enforcing tests.
5. **Decision provenance**: every `compustat_q` row carries a `decision_source`
   ∈ `{llm, fallback, mock}`. For behavioral analysis, filter to `llm` rows.
   Fallbacks and mocks are hand-coded rules, not emergent behavior.
6. **proposal_id linkage**: every row in `compustat_q.csv` has a `proposal_id`
   that keys into `proposals.jsonl`. Use this to trace "why is this row
   what it is?" back to the LLM's structured action + prose justification.
7. **Negotiation records**: multi-round bargaining produces entries in
   `negotiations.jsonl` with full round-by-round offer history. Topics:
   `covenant_waiver`, `debt_pricing`, `activist_campaign`, `ma_auction`,
   `audit_fee`.
8. **Scenarios**: `config.scenario: <name>` loads `scenarios/<name>.yaml` for
   heterogeneous per-firm founding conditions. Shipped: `biotech_early_stage`,
   `mature_industry`, `distressed`. Default (none) = uniform IPO at $17.50×10M.
9. **Snapshots + restart**: run with `--restart-from outputs/<run>/snapshots/Q5.pkl`
   to resume from any quarter. Useful for debugging specific events or
   extending a run without re-running the full history.
