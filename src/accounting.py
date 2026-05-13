"""
Accounting module: pure functions that transform state.

Given a prior FirmState + ClampedDecisions + MarketOutcome + SimParams,
produce a new FirmState + QuarterFlows.

No LLM calls. No side effects. No randomness. Deterministic.

Canonical reference: docs/architecture/16_worked_accounting_example.md
"""

from __future__ import annotations

import math

from .types import (
    ClampedDecisions,
    CompustatRow,
    FirmState,
    MacroState,
    MarketOutcome,
    QuarterFlows,
    SimParams,
)


# ─── Core posting function ───────────────────────────────────────────────

def post_quarter(
    prior: FirmState,
    decisions: ClampedDecisions,
    outcome: MarketOutcome,
    params: SimParams,
) -> tuple[FirmState, QuarterFlows]:
    """
    Post all accounting entries for one firm-quarter.

    Returns (new_state, flows) where:
    - new_state is the end-of-quarter FirmState
    - flows is the QuarterFlows (IS, CF, actuals)

    Pure function. Same inputs -> same outputs. Always.
    """

    # ── Step 1: Effective unit cost ──────────────────────────────────────

    cap_util = (decisions.production / prior.capacity_units
                if prior.capacity_units > 0 else 0.0)
    util_mult = _utilization_multiplier(cap_util, params)

    process_reduction = (params.process_rd_max_reduction
                         * (1 - math.exp(-prior.rd_cumulative_process
                                          / params.process_rd_saturation)))
    base_after_process = prior.base_unit_cost * (1 - process_reduction)
    effective_unit_cost = base_after_process * util_mult

    # ── Step 2: Inventory and COGS (FIFO) ────────────────────────────────

    new_production_cost = decisions.production * effective_unit_cost

    # FIFO: sell old inventory first, then new production
    old_units = prior.inventory_units
    old_value = prior.inventory_value
    old_unit_cost = (old_value / old_units) if old_units > 0 else 0.0

    units_to_sell = outcome.units_sold
    # Clamp units_sold to what's actually available (production + inventory).
    # Wave ν+7 fix: previously revenue used `outcome.units_sold` (un-clamped)
    # while COGS used the clamped value, producing accounting inconsistency
    # (revenue without cost of goods) when the env over-allocated. Now both
    # use the clamped value via `units_to_sell`.
    max_sellable = decisions.production + old_units
    if units_to_sell > max_sellable:
        units_to_sell = max_sellable
    # Reflect the clamp into outcome so reported flows stay consistent.
    if units_to_sell != outcome.units_sold:
        from dataclasses import replace as _dc_replace
        outcome = _dc_replace(outcome, units_sold=units_to_sell)

    # Sell from old inventory first
    sold_from_old = min(units_to_sell, old_units)
    cogs_from_old = sold_from_old * old_unit_cost

    # Then from new production
    sold_from_new = units_to_sell - sold_from_old
    cogs_from_new = sold_from_new * effective_unit_cost

    cogs = cogs_from_old + cogs_from_new

    # Remaining inventory
    remaining_old_units = old_units - sold_from_old
    remaining_old_value = remaining_old_units * old_unit_cost
    remaining_new_units = decisions.production - sold_from_new
    remaining_new_value = remaining_new_units * effective_unit_cost

    end_inventory_units = remaining_old_units + remaining_new_units
    end_inventory_value = remaining_old_value + remaining_new_value

    # ── Step 3: Income statement ─────────────────────────────────────────

    revenue = outcome.units_sold * decisions.price
    gross_profit = revenue - cogs

    rd_expense = decisions.rd_spend
    # CEO compensation (Stage 11) folds into SGA for IS consistency with WRDS:
    # base salary accrues quarterly (cash), cash bonus and stock comp added
    # on governance quarter (Q4). Stock comp is non-cash (SBC); cash comp
    # leaves firm cash. Total both get reported under xsgaq.
    ceo_cash_comp = max(0.0, float(getattr(prior, "ceo_cash_comp_this_q", 0.0) or 0.0))
    ceo_stock_comp = max(0.0, float(getattr(prior, "ceo_stock_comp_this_q", 0.0) or 0.0))
    sga_expense = decisions.sga_spend + ceo_cash_comp + ceo_stock_comp
    depreciation = params.depreciation_rate * prior.ppe_gross
    # Note: Q's capex does NOT depreciate this quarter (end-of-quarter convention)

    operating_income = gross_profit - rd_expense - sga_expense - depreciation

    # Interest expense: legacy aggregate calc uses
    #   (prior.revolver_balance × prior.revolver_rate
    #    + prior.long_term_debt × prior.term_debt_rate)
    # When debt_covenants are enabled AND facilities exist, those facilities
    # own per-facility rates and amortize_quarter handles their interest
    # separately (deducted from cash post-accounting in Phase 6.5, routed
    # back into flows by the orchestrator). To avoid double-counting,
    # exclude facility-owned LTD *and* facility-owned revolver balance from
    # the aggregate calc — the orchestrator re-posts facility interest from
    # amortize_quarter so both IS and CFS reflect it exactly once.
    facility_ltd = 0.0
    facility_revolver = 0.0
    if prior.debt_facilities:
        for _fac in prior.debt_facilities:
            if _fac.status not in ("current", "in_cure_period", "amended", "accelerated"):
                continue
            if _fac.facility_type == "bank_revolver":
                facility_revolver += _fac.current_balance
            else:
                facility_ltd += _fac.current_balance
    non_facility_ltd = max(0.0, prior.long_term_debt - facility_ltd)
    non_facility_revolver = max(0.0, prior.revolver_balance - facility_revolver)

    interest_expense = (non_facility_revolver * prior.revolver_rate
                        + non_facility_ltd * prior.term_debt_rate)

    pretax_income = operating_income - interest_expense

    # Tax with NOL carryforward
    nol_start = prior.nol_carryforward
    if pretax_income > 0:
        nol_usage = min(nol_start, params.nol_usage_limit * pretax_income)
        taxable_income = pretax_income - nol_usage
        tax_expense = taxable_income * params.tax_rate
        nol_end = nol_start - nol_usage
    else:
        tax_expense = 0.0
        nol_usage = 0.0
        nol_end = nol_start + abs(pretax_income)

    net_income = pretax_income - tax_expense

    # ── Step 3b: Earnings manipulation (when enabled) ──────────────────
    # manipulation_amount is on ClampedDecisions (default 0.0).
    # It adjusts reported_net_income but NOT cash flows (accrual manipulation).
    manipulation_amount = getattr(decisions, 'manipulation_amount', 0.0)
    reported_net_income = net_income + manipulation_amount

    # ── Step 4: Working capital ──────────────────────────────────────────
    # Default: use params.theta_ar / theta_ap (legacy behavior when toggle off).
    # When working_capital_decisions enabled, firm can override via decisions:
    #   - receivables_days_target: DSO (days); AR = revenue × DSO / 90
    #   - payables_days_target: DPO (days); AP = COGS × DPO / 90
    #   - deposit_pct: fraction of revenue collected upfront → deferred_revenue
    #   - ppe_disposal: $ of PP&E sold (reduces gross PP&E, generates cash)

    deposit_pct = getattr(decisions, "deposit_pct", None)
    deposit_pct = 0.0 if deposit_pct is None else max(0.0, min(1.0, deposit_pct))

    # Split revenue into upfront (cash/deferred) and credit (AR)
    upfront_revenue = revenue * deposit_pct
    credit_revenue = revenue * (1.0 - deposit_pct)

    dso = getattr(decisions, "receivables_days_target", None)
    if dso is not None and dso > 0:
        end_ar = credit_revenue * min(180.0, float(dso)) / 90.0
    else:
        end_ar = params.theta_ar * credit_revenue
    delta_ar = end_ar - prior.accounts_receivable

    # Deferred revenue (Stage 4 MVP simplification):
    # Deposits are treated as cash collected for revenue delivered THIS quarter
    # (not future-period). So deferred_revenue balance = 0 when revenue is
    # recognized immediately. The economic signal of deposit_pct is captured
    # entirely through AR reduction (less working capital tie-up). A richer
    # multi-period deposit model with proper recognition lag is deferred.
    end_deferred_revenue = 0.0
    delta_deferred_revenue = end_deferred_revenue - prior.deferred_revenue

    delta_inventory = end_inventory_value - prior.inventory_value

    dpo = getattr(decisions, "payables_days_target", None)
    if dpo is not None and dpo > 0:
        end_ap = cogs * min(180.0, float(dpo)) / 90.0
    else:
        end_ap = params.theta_ap * cogs
    delta_ap = end_ap - prior.accounts_payable

    end_accrued = params.theta_accr * (rd_expense + sga_expense)
    delta_accrued = end_accrued - prior.accrued_expenses

    end_taxes_payable = tax_expense  # this quarter's tax, paid next quarter
    delta_taxes_payable = end_taxes_payable - prior.taxes_payable

    # ── Step 4b: PP&E disposal (Stage 4) ─────────────────────────────────
    # Firm can sell PP&E for cash. Gain/loss = proceeds - net book value sold.
    # Simplified: disposal reduces ppe_gross proportionally with the already-
    # accumulated depreciation, so we sell at the proportional net book value
    # plus an implicit market adjustment (proceeds as declared by firm).
    ppe_disposal = max(0.0, float(getattr(decisions, "ppe_disposal", 0.0) or 0.0))
    ppe_disposal_proceeds = 0.0
    ppe_disposal_gain_loss = 0.0
    if ppe_disposal > 0 and prior.ppe_net > 0:
        # Proceeds are the firm's stated disposal amount (LLM judges fair sale price).
        # Net book value sold: pro-rata share of net PP&E matching disposal fraction.
        # disposal_frac is the fraction of NET PP&E sold — cap at 1.0 for entire PP&E.
        # Use prior.ppe_net directly (no artificial floor — clamping already
        # ensures ppe_disposal ≤ ppe_net so the ratio is bounded at 1.0).
        disposal_frac = min(1.0, ppe_disposal / prior.ppe_net)
        gross_sold = prior.ppe_gross * disposal_frac
        accum_sold = prior.accum_depreciation * disposal_frac
        nbv_sold = gross_sold - accum_sold
        ppe_disposal_proceeds = ppe_disposal
        ppe_disposal_gain_loss = ppe_disposal_proceeds - nbv_sold

    # ── Step 4e: Legal reserves (Stage 12, gated by legal_reserves_enabled) ──
    # Firm accrues reserve now (IS special item charge, BS liability grows)
    # or settles litigation (cash out, reduces both reserve and cash).
    # If toggle off at params level, all legal values are 0 and no BS/IS impact.
    legal_enabled = getattr(params, "legal_reserves_enabled", False)
    if legal_enabled:
        legal_reserve_change = float(getattr(decisions, "legal_reserve_change", 0.0) or 0.0)
        legal_settlements_paid = max(0.0,
            float(getattr(decisions, "legal_settlements_paid", 0.0) or 0.0))
        legal_settlements_paid = min(
            legal_settlements_paid,
            max(0.0, prior.legal_reserve_balance + max(0.0, legal_reserve_change)),
        )
        end_legal_reserve = max(0.0, prior.legal_reserve_balance
                                + legal_reserve_change
                                - legal_settlements_paid)
        legal_charge = legal_reserve_change
    else:
        legal_reserve_change = 0.0
        legal_settlements_paid = 0.0
        end_legal_reserve = prior.legal_reserve_balance
        legal_charge = 0.0

    # ── Step 4f: Pension (Stage 12, gated by pension_enabled) ──
    pension_enabled = getattr(params, "pension_enabled", False)
    ceo_cash_comp = max(0.0, float(getattr(prior, "ceo_cash_comp_this_q", 0.0) or 0.0))
    ceo_stock_comp = max(0.0, float(getattr(prior, "ceo_stock_comp_this_q", 0.0) or 0.0))
    if pension_enabled:
        pension_service_cost = 0.05 * (decisions.sga_spend + ceo_cash_comp)
        pension_contribution = max(0.0, float(getattr(decisions, "pension_contribution", 0.0) or 0.0))
        pension_contribution = min(pension_contribution,
                                    prior.pension_liability + pension_service_cost)
        end_pension_liability = max(0.0, prior.pension_liability
                                     + pension_service_cost
                                     - pension_contribution)
    else:
        pension_service_cost = 0.0
        pension_contribution = 0.0
        end_pension_liability = prior.pension_liability

    # ── Step 4g: Deferred taxes (Stage 12, gated by deferred_taxes_enabled) ──
    if getattr(params, "deferred_taxes_enabled", False):
        tax_dep_accel = depreciation * 1.5
        book_tax_temp_diff = tax_dep_accel - depreciation
        dtl_change = book_tax_temp_diff * params.tax_rate
        end_dtl = max(0.0, prior.deferred_tax_liability + dtl_change)
        actual_dtl_change = end_dtl - prior.deferred_tax_liability
    else:
        end_dtl = prior.deferred_tax_liability
        actual_dtl_change = 0.0

    # ── Step 4d: Restructuring (Stage 10) ─────────────────────────────────
    # One-time charge: severance (cash out) + impairments (non-cash). Sum
    # flows through IS as `rcp` line below operating income, above pretax.
    rs_severance = max(0.0, float(getattr(decisions, "restructuring_severance", 0.0) or 0.0))
    rs_ppe_imp = max(0.0, float(getattr(decisions, "restructuring_ppe_impairment", 0.0) or 0.0))
    rs_inv_imp = max(0.0, float(getattr(decisions, "restructuring_inventory_write_off", 0.0) or 0.0))
    rs_gw_imp = max(0.0, float(getattr(decisions, "restructuring_goodwill_impairment", 0.0) or 0.0))
    # Clamping already capped impairments at asset values; defensive re-cap.
    rs_ppe_imp = min(rs_ppe_imp, prior.ppe_net)
    rs_inv_imp = min(rs_inv_imp, prior.inventory_value)
    rs_gw_imp = min(rs_gw_imp, prior.goodwill)
    restructuring_charge = rs_severance + rs_ppe_imp + rs_inv_imp + rs_gw_imp

    # ── Step 4c: Bad debt expense (Stage 5) ─────────────────────────────
    # Apply write-offs FIRST (reduces gross AR), THEN compute new allowance
    # as a fraction of post-write-off AR. Otherwise allowance can exceed
    # gross AR (net AR negative, BS identity breaks via the max(0, net_ar)
    # clamp in the total_assets property).
    write_offs = max(0.0, float(getattr(decisions, "write_offs_this_quarter", 0.0) or 0.0))
    # Cap write_offs at the pre-write-off gross AR (can't write off more than exists)
    write_offs = min(write_offs, end_ar)
    # Reduce gross AR by write-offs
    end_ar = max(0.0, end_ar - write_offs)
    delta_ar = end_ar - prior.accounts_receivable

    # Firm's allowance_pct_of_ar (if set) determines end-of-Q allowance against
    # *post-write-off* gross AR. Carry forward prior pct if not specified.
    allowance_pct = getattr(decisions, "allowance_pct_of_ar", None)
    if allowance_pct is not None and allowance_pct >= 0:
        new_allowance = end_ar * min(1.0, max(0.0, float(allowance_pct)))
    else:
        prior_allowance_pct = (prior.allowance_for_doubtful_accounts
                               / max(1.0, prior.accounts_receivable)) if prior.accounts_receivable > 0 else 0.0
        new_allowance = end_ar * prior_allowance_pct
    # Cap allowance at gross AR so net AR is never negative
    new_allowance = min(new_allowance, end_ar)

    # GAAP bad-debt expense = Δallowance + write_offs. Works in all cases:
    #   - prior.allow >= write_offs: write-offs consume allowance, topup tops it back
    #   - prior.allow < write_offs: allowance goes to 0, excess write-off is direct
    #     bad-debt expense, then topup to new_allowance. Same formula.
    # Can be negative if the firm cuts its estimate and has no write-offs.
    bad_debt_expense = new_allowance - prior.allowance_for_doubtful_accounts + write_offs

    # ── Step 5: Cash flow statement ──────────────────────────────────────
    # `net_income` here is PRE-adjustment (bad_debt_expense and
    # ppe_disposal_gain_loss are applied in Step 6). Starting from NI_pre:
    #   - bad_debt_expense: non-cash charge → subtract (aligns with NI_end path)
    #   - ppe_disposal_gain_loss: cancels (non-cash add-back offsets NI_end
    #     adjustment); no adjustment needed here
    #   - Δ(net_AR) = ΔAR_gross − Δallowance captures write-offs + topup
    delta_allowance = new_allowance - prior.allowance_for_doubtful_accounts
    delta_net_ar = delta_ar - delta_allowance

    cfo = (net_income                      # pre-adjustment NI
           - bad_debt_expense               # non-cash charge (shifts NI → NI_end equivalence)
           - rs_severance                   # severance is cash out (restructuring)
           - legal_settlements_paid         # cash settlements paid this Q
           - pension_contribution           # cash contribution to plan
           + ceo_stock_comp                 # non-cash stock-based comp add-back
           + actual_dtl_change              # deferred tax non-cash add-back (Stage 12)
           + depreciation                  # non-cash add-back
           - delta_net_ar                   # net AR change
           - delta_inventory                # inventory build = cash use
           + delta_ap                       # AP increase = cash source
           + delta_accrued                  # accrued increase = cash source
           + delta_deferred_revenue         # customer deposit cash-in
           + delta_taxes_payable)           # tax payable increase = cash source

    # CFI: capex out, disposal proceeds in
    cfi = -decisions.capex + ppe_disposal_proceeds

    # CFF: revolver draws, equity issuance, payouts
    # Note: equity issuance and debt issuance happen in settlement (Phase 8),
    # not here. CFF here only includes draws, payouts, and buybacks.
    cff = (decisions.credit_drawn
           - decisions.dividends
           - decisions.buybacks)

    change_in_cash = cfo + cfi + cff

    # ── Step 6: Balance sheet updates ────────────────────────────────────

    end_cash = prior.cash + change_in_cash

    # PP&E: capex adds gross, disposal removes proportional gross + accum,
    # restructuring impairment reduces gross directly (NBV hit).
    disposal_frac = (min(1.0, ppe_disposal / prior.ppe_net)
                     if ppe_disposal > 0 and prior.ppe_net > 0 else 0.0)
    gross_sold = prior.ppe_gross * disposal_frac
    accum_sold = prior.accum_depreciation * disposal_frac
    end_ppe_gross = prior.ppe_gross - gross_sold + decisions.capex - rs_ppe_imp
    end_accum_dep = prior.accum_depreciation - accum_sold + depreciation

    # Inventory + goodwill impairments: reduce carrying value directly.
    # Inventory write-off also reduces units proportionally so per-unit cost
    # stays meaningful (avoids "0 dollars / N units" zombie inventory).
    if rs_inv_imp > 0 and end_inventory_value > 0:
        kept_frac = max(0.0, 1.0 - rs_inv_imp / end_inventory_value)
        end_inventory_value = max(0.0, end_inventory_value - rs_inv_imp)
        end_inventory_units = int(end_inventory_units * kept_frac)
    end_goodwill = max(0.0, prior.goodwill - rs_gw_imp)

    end_revolver = prior.revolver_balance + decisions.credit_drawn

    # Bad debt expense + pension service cost = operating (charged to SGA).
    # Restructuring, disposal gain/loss, and legal reserve changes = below
    # operating, above pretax (match WRDS funda's non-operating block).
    adjusted_operating_income = (operating_income
                                  - bad_debt_expense
                                  - pension_service_cost)
    adjusted_pretax_income = (adjusted_operating_income - interest_expense
                              + ppe_disposal_gain_loss
                              - restructuring_charge
                              - legal_charge)
    # Proportionally adjust tax (keep effective-tax-rate approximation).
    if pretax_income != 0:
        scale = adjusted_pretax_income / pretax_income
        adjusted_tax_expense = tax_expense * scale
    else:
        adjusted_tax_expense = tax_expense
    true_ni_adjusted = adjusted_pretax_income - adjusted_tax_expense
    reported_ni_adjusted = true_ni_adjusted + manipulation_amount

    # Overwrite the bindings so QuarterFlows + new_state use the adjusted
    # values. Semantics clarified:
    #   - flows.net_income = true NI excluding manipulation, INCLUDING Stage
    #     4/5 adjustments (BDE + disposal gain). This is what the firm
    #     "actually earned" economically.
    #   - flows.reported_net_income = flows.net_income + manipulation_amount.
    #     This is what the firm publishes.
    #   - flows.true_net_income is a synonym for flows.net_income — the
    #     earnings-management research context where "true" means "without
    #     manipulation" (NOT "before Stage 4/5 adjustments").
    operating_income = adjusted_operating_income
    pretax_income = adjusted_pretax_income
    tax_expense = adjusted_tax_expense
    net_income = true_ni_adjusted
    reported_net_income = reported_ni_adjusted

    # Recompute taxes_payable to use the ADJUSTED tax expense — this is
    # what the firm actually owes. Do NOT adjust CFO's delta_taxes_payable:
    # pre_adj_NI (starting point of CFO) already has -original_tax baked in,
    # and CFO's +delta_taxes_payable (=original_tax) offsets it to zero net
    # cash impact. The tax savings from adjustments (original_tax -
    # adjusted_tax) is non-cash — it reduces future tax owed but doesn't
    # change current cash flow.
    # BS: taxes_payable = adjusted_tax (what firm owes)
    # CFS: CFO reflects pretax (full pre-adjustment cash generation)
    # IS: NI = adjusted_NI (after all Stage 4/5/6 adjustments)
    # These are internally consistent and the BS identity holds.
    end_taxes_payable = tax_expense  # adjusted

    change_in_cash = cfo + cfi + cff
    end_cash = prior.cash + change_in_cash

    # Retained earnings uses REPORTED net income (includes manipulation).
    # True net_income is preserved in QuarterFlows for research.
    end_re = prior.retained_earnings + reported_net_income - decisions.dividends

    end_treasury = prior.treasury_stock + decisions.buybacks

    # ── Step 7: Internal stock updates ───────────────────────────────────

    # R&D allocation
    phase3 = params.mandatory_phase3_quarterly_cost
    discretionary_rd = max(0.0, decisions.rd_spend - phase3)
    alloc = decisions.rd_allocation
    product_rd = discretionary_rd * alloc.get("product", 0.6)
    process_rd = discretionary_rd * alloc.get("process", 0.25)
    delivery_rd = discretionary_rd * alloc.get("delivery", 0.15)

    # Capability stock (diminishing returns near 100)
    cap_headroom = max(0.0, (100.0 - prior.capability_stock) / 100.0)
    new_capability = ((1 - params.delta_a) * prior.capability_stock
                      + params.eta_a * (product_rd / 1_000_000) * cap_headroom)
    new_capability = min(100.0, new_capability)

    # Brand stock (effectiveness scales with quality, diminishing returns near 100)
    eff_quality = max(1.0, prior.capability_stock)
    quality_factor = eff_quality / 50.0
    # Diminishing returns: brand accumulation slows as brand approaches 100
    brand_headroom = max(0.0, (100.0 - prior.brand_stock) / 100.0)
    new_brand = ((1 - params.delta_b) * prior.brand_stock
                 + params.eta_b * (sga_expense / 1_000_000) * quality_factor * brand_headroom)
    new_brand = min(100.0, new_brand)  # hard cap at 100

    # R&D cumulative tracking
    new_cum_product = prior.rd_cumulative_product + product_rd
    new_cum_process = prior.rd_cumulative_process + process_rd
    new_cum_delivery = prior.rd_cumulative_delivery + delivery_rd

    # Generation (not changed here -- environment decides advances)
    new_gen = prior.product_generation
    new_delivery_gen = prior.delivery_generation
    new_base_cost = prior.base_unit_cost

    # Apply generation advance if outcome says so
    if outcome.product_rd_advance and new_gen < 4:
        new_gen = prior.product_generation + 1
        new_base_cost = params.gen_base_cogs[new_gen]
        # Reset process R&D cumulative for new generation
        new_cum_process = 0.0
        # Quality jumps are implicit via generation -> quality index mapping

    if outcome.delivery_rd_advance and new_delivery_gen < 4:
        new_delivery_gen = prior.delivery_generation + 1

    # Wave ν+9 Bug M1: apply env's process-improvement signal directly to
    # base unit cost. Previously this branch was a `pass` with a comment
    # claiming the cumulative-process-R&D formula captured it; in fact
    # that formula updates from `prior.rd_cumulative_process`, which
    # advances only via firm decisions, leaving the env's incremental
    # process advances orphaned. Clamp the per-quarter reduction to a
    # plausible range so a malformed env response can't drive cost
    # negative.
    if outcome.process_cogs_reduction_pct > 0 and not outcome.product_rd_advance:
        red = max(0.0, min(0.10, float(outcome.process_cogs_reduction_pct)))
        new_base_cost = max(0.01 * params.gen_base_cogs[new_gen],
                            new_base_cost * (1.0 - red))

    # ── Step 8: Build new state ──────────────────────────────────────────

    # Wave ν+11 fix for E4: capacity scales with gross PPE. Without
    # this link, the firm prompt's stated relationship between capex and
    # capacity was a fiction — capex grew PPE on the BS but capacity_units
    # never moved off baseline. Industry was stuck at <0.5% of TAM no
    # matter how much firms invested. Now: capacity = floor(ppe_gross /
    # ppe_per_unit_capacity), with a small floor for active firms so
    # operational continuity holds across PPE writedowns / disposals.
    if end_ppe_gross > 0 and params.ppe_per_unit_capacity > 0:
        new_capacity_units = int(end_ppe_gross / params.ppe_per_unit_capacity)
        # Floor: keep at least the firm's prior baseline if it's still
        # producing, so a one-time impairment doesn't kill operations.
        if prior.is_active and new_capacity_units < 50:
            new_capacity_units = max(50, prior.capacity_units // 2)
    else:
        new_capacity_units = prior.capacity_units

    new_state = prior.evolve(
        quarter=prior.quarter + 1,

        # Assets
        cash=end_cash,
        accounts_receivable=end_ar,
        allowance_for_doubtful_accounts=new_allowance,
        inventory_units=end_inventory_units,
        inventory_value=end_inventory_value,
        ppe_gross=end_ppe_gross,
        accum_depreciation=end_accum_dep,
        goodwill=end_goodwill,
        capacity_units=new_capacity_units,

        # Liabilities
        accounts_payable=end_ap,
        accrued_expenses=end_accrued,
        taxes_payable=end_taxes_payable,
        deferred_revenue=end_deferred_revenue,
        legal_reserve_balance=end_legal_reserve,
        deferred_tax_liability=end_dtl,
        pension_liability=end_pension_liability,
        revolver_balance=end_revolver,
        # long_term_debt unchanged (managed in settlement)

        # Equity — APIC absorbs the offsetting credit for stock-based comp
        # (Stage 11). SBC reduces NI (via SGA) and is added back to CFO;
        # without crediting APIC, equity drops without any liability/asset
        # offset, leaving a +SBC residual on the BS each quarter.
        apic=prior.apic + ceo_stock_comp,
        retained_earnings=end_re,
        treasury_stock=end_treasury,

        # Internal
        capability_stock=new_capability,
        brand_stock=new_brand,
        base_unit_cost=new_base_cost,
        product_generation=new_gen,
        delivery_generation=new_delivery_gen,
        rd_cumulative_product=new_cum_product,
        rd_cumulative_process=new_cum_process,
        rd_cumulative_delivery=new_cum_delivery,
        nol_carryforward=nol_end,

        # Earnings management tracking
        cumulative_manipulation=prior.cumulative_manipulation + manipulation_amount,
        manipulation_this_quarter=manipulation_amount,
        # CEO comp fields zeroed after consume (Phase 5.7 will refill next Q)
        ceo_cash_comp_this_q=0.0,
        ceo_stock_comp_this_q=0.0,
    )

    flows = QuarterFlows(
        firm_id=prior.firm_id,
        quarter=prior.quarter + 1,

        # IS
        net_sales=revenue,
        cogs=cogs,
        gross_profit=gross_profit,
        rd_expense=rd_expense,
        sga_expense=sga_expense,
        depreciation=depreciation,
        operating_income=operating_income,
        interest_expense=interest_expense,
        pretax_income=pretax_income,
        tax_expense=tax_expense,
        net_income=net_income,

        # CF
        cfo=cfo,
        cfi=cfi,
        cff=cff,
        change_in_cash=change_in_cash,

        # Actuals
        actual_price=decisions.price,
        actual_production=decisions.production,
        actual_capex=decisions.capex,
        actual_rd_spend=decisions.rd_spend,
        actual_sga_spend=decisions.sga_spend,
        units_sold=outcome.units_sold,
        market_share=outcome.market_share,

        # Cost detail
        effective_unit_cost=effective_unit_cost,
        capacity_utilization=cap_util,

        # Earnings management
        reported_net_income=reported_net_income,
        manipulation_amount=manipulation_amount,
        true_net_income=net_income,

        # WC changes
        delta_ar=delta_ar,
        delta_inventory=delta_inventory,
        delta_ap=delta_ap,
        delta_accrued=delta_accrued,
        delta_taxes_payable=delta_taxes_payable,

        # Stage 4/5: PP&E disposal + bad debt flows
        ppe_disposal_proceeds=ppe_disposal_proceeds,
        ppe_disposal_gain_loss=ppe_disposal_gain_loss,
        bad_debt_expense=bad_debt_expense,
        write_offs_this_quarter=write_offs,
        # Stage 10: restructuring
        restructuring_severance=rs_severance,
        restructuring_ppe_impairment=rs_ppe_imp,
        restructuring_inventory_write_off=rs_inv_imp,
        restructuring_goodwill_impairment=rs_gw_imp,
        restructuring_charge=restructuring_charge,
        # Stage 12: legal / pension / deferred tax
        legal_charge=legal_charge,
        legal_settlements_paid=legal_settlements_paid,
        pension_service_cost=pension_service_cost,
        pension_contribution=pension_contribution,
        dtl_change=actual_dtl_change,
    )

    return new_state, flows


# ─── Validation ──────────────────────────────────────────────────────────

def validate_state(state: FirmState, flows: QuarterFlows, prior: FirmState,
                   decisions: ClampedDecisions | None = None,
                   tol: float = 1.0) -> list[str]:
    """
    Check all hard accounting invariants. Returns list of violations.
    Empty list = all pass. If `decisions` is provided, also enforces the
    retained-earnings roll-forward: RE_end = RE_start + reported_NI - dividends.
    """
    violations = []

    # 1. Balance sheet identity
    bs_diff = abs(state.total_assets - state.total_liabilities - state.total_equity)
    if bs_diff > tol:
        violations.append(
            f"BS identity: |atq - ltq - ceqq| = {bs_diff:.2f} > {tol}"
        )

    # 2. Cash reconciliation
    cash_diff = abs(flows.change_in_cash - (flows.cfo + flows.cfi + flows.cff))
    if cash_diff > tol:
        violations.append(
            f"Cash recon: |chechq - (cfo+cfi+cff)| = {cash_diff:.2f} > {tol}"
        )

    # 3. Cash matches delta
    actual_delta = state.cash - prior.cash
    if abs(actual_delta - flows.change_in_cash) > tol:
        violations.append(
            f"Cash delta: |end-start - chechq| = "
            f"{abs(actual_delta - flows.change_in_cash):.2f} > {tol}"
        )

    # 4. Retained earnings roll-forward: RE_end = RE_start + reported_NI - dividends.
    # Only enforced when decisions are provided (we need dividend amount).
    # Use reported_net_income directly (always assigned in post_quarter; 0 is a
    # legitimate value when manipulation exactly offsets true NI).
    reported_ni = flows.reported_net_income
    if decisions is not None:
        expected_re = prior.retained_earnings + reported_ni - decisions.dividends
        re_diff = abs(state.retained_earnings - expected_re)
        if re_diff > tol:
            violations.append(
                f"RE roll-forward: state.RE={state.retained_earnings:.2f} "
                f"!= prior.RE + reported_NI - div = "
                f"{prior.retained_earnings:.2f} + {reported_ni:.2f} "
                f"- {decisions.dividends:.2f} = {expected_re:.2f} "
                f"(diff {re_diff:.2f})"
            )
    if not flows.default_flag:
        if state.total_assets < -tol:
            violations.append(f"Negative total assets: {state.total_assets:.2f}")
        if state.cash < -tol and state.is_active:
            violations.append(f"Negative cash for active firm: {state.cash:.2f}")

    # 5. Inventory continuity
    expected_inv_units = (prior.inventory_units + flows.actual_production
                          - flows.units_sold)
    if state.inventory_units != expected_inv_units:
        violations.append(
            f"Inventory units: {state.inventory_units} != "
            f"expected {expected_inv_units}"
        )

    # 6. PPE continuity
    # PPE gross: prior + capex - disposal_gross. We don't carry disposal_gross
    # explicitly on flows; approximate by computing what it should be given the
    # disposal_proceeds fraction. Skip the hard invariant when disposal occurred.
    if getattr(flows, "ppe_disposal_proceeds", 0.0) > 0:
        # Skip: disposal reduces gross in proportion to net-book-value fraction;
        # handled correctly inside post_quarter. Soft invariant.
        if state.ppe_gross > prior.ppe_gross + flows.actual_capex + tol:
            violations.append(
                f"PPE gross grew beyond capex with disposal: "
                f"{state.ppe_gross:.2f} > prior+capex {prior.ppe_gross + flows.actual_capex:.2f}"
            )
    else:
        expected_ppe_gross = prior.ppe_gross + flows.actual_capex
        if abs(state.ppe_gross - expected_ppe_gross) > tol:
            violations.append(
                f"PPE gross: {state.ppe_gross:.2f} != expected {expected_ppe_gross:.2f}"
            )

    # 7. Current liabilities decomposition
    lct_sum = (state.accounts_payable + state.accrued_expenses
               + state.taxes_payable + state.deferred_revenue
               + state.revolver_balance)
    if abs(state.total_current_liabilities - lct_sum) > tol:
        violations.append(
            f"LCT decomposition: {state.total_current_liabilities:.2f} != "
            f"sum {lct_sum:.2f}"
        )

    return violations


# ─── Compustat row builder ───────────────────────────────────────────────

def build_compustat_row(
    state: FirmState,
    flows: QuarterFlows,
    decisions: ClampedDecisions,
    macro: MacroState,
    run_id: str,
) -> CompustatRow:
    """Build a Compustat-format row from state, flows, and decisions."""
    from .wrds_identifiers import datadate_for, identifiers_for_firm
    ids = identifiers_for_firm(state.firm_id)
    return CompustatRow(
        run_id=run_id,
        firm_id=state.firm_id,
        incarnation=state.incarnation,
        fyearq=macro.fyear,
        fqtr=macro.fqtr,
        datadate=datadate_for(macro.fyear, macro.fqtr),
        tic=ids["tic"],
        conm=ids["conm"],
        sic=ids["sic"],
        cusip=ids.get("cusip", ""),
        # Funda metadata defaults on CompustatRow (INDL/C/D/STD) — carried
        # through for WRDS-compatible filtering.

        saleq=flows.net_sales,
        cogsq=flows.cogs,
        gpq=flows.gross_profit,
        xrdq=flows.rd_expense,
        xsgaq=flows.sga_expense,
        dpq=flows.depreciation,
        oiadpq=flows.operating_income,
        xintq=flows.interest_expense,
        rcpq=flows.restructuring_charge,
        piq=flows.pretax_income,
        txtq=flows.tax_expense,
        niq=flows.reported_net_income,

        cheq=state.cash,
        rectq=state.accounts_receivable,
        invtq=state.inventory_value,
        ppentq=state.ppe_net,
        ppegtq=state.ppe_gross,
        actq=(state.cash + max(0.0, state.accounts_receivable
                               - state.allowance_for_doubtful_accounts)
              + state.inventory_value),
        atq=state.total_assets,

        apq=state.accounts_payable,
        xaccq=state.accrued_expenses,
        txpq=state.taxes_payable,
        drcq=state.deferred_revenue,
        dlcq=state.revolver_balance,
        lctq=state.total_current_liabilities,
        dlttq=state.long_term_debt,
        ltq=state.total_liabilities,
        allowance_dca=state.allowance_for_doubtful_accounts,
        bad_debt_expense=flows.bad_debt_expense,
        write_offs=flows.write_offs_this_quarter,
        ppe_disposal_proceeds=flows.ppe_disposal_proceeds,
        ppe_disposal_gain_loss=flows.ppe_disposal_gain_loss,
        # Stage 12 additions
        spioq=(flows.restructuring_charge + getattr(flows, "legal_charge", 0.0)),
        legal_reserve_bs=state.legal_reserve_balance,
        pension_liability_bs=state.pension_liability,
        pension_service_cost=getattr(flows, "pension_service_cost", 0.0),
        pension_contribution=getattr(flows, "pension_contribution", 0.0),
        txditcq=state.deferred_tax_liability,

        cstkq=state.common_stock,
        apicq=state.apic,
        ceqq=state.total_equity,
        seqq=state.total_equity,   # no pref stock in this sim → seqq == ceqq
        req=state.retained_earnings,
        tstkq=state.treasury_stock,

        oancfq=flows.cfo,
        ivncfq=flows.cfi,
        fincfq=flows.cff,
        chechq=flows.change_in_cash,
        capxq=decisions.capex,

        dvq=decisions.dividends,
        sstkq=0.0,  # equity issuance happens in settlement, tracked there
        prstkq=decisions.buybacks,

        prccq=state.equity_price,
        cshoq=state.shares_outstanding / 1_000_000,  # Compustat uses millions
        mkvaltq=state.market_cap / 1_000_000,  # WRDS stores market cap in $ millions

        default_flag=1 if flows.default_flag else 0,

        # Employee count (proxy). No explicit headcount in this sim;
        # derive from SGA spend assuming ~$200K total cost per employee
        # per year (salary + benefits + overhead allocation):
        #     emp = sga_quarterly / ($200K / 4) = sga / $50K
        # Stored as actual count (not thousands) since this sim has small
        # biotech firms (<200 employees) — using WRDS thousands convention
        # would round everything to zero. Researchers should treat empq
        # here as headcount.
        empq=int(round(flows.sga_expense / 50_000.0))
            if flows.sga_expense > 0 else 0,

        # Earnings management (hidden truth column, not in public Compustat)
        manipulation_amount=flows.manipulation_amount,

        # Goodwill (from M&A)
        gdwlq=state.goodwill,

        # Wave alpha: decision provenance (pass-through from clamped decisions).
        decision_source=getattr(decisions, "decision_source", "llm"),
        fallback_reason=getattr(decisions, "fallback_reason", ""),
        # Wave beta: link to the Action that produced this decision.
        proposal_id=getattr(decisions, "proposal_id", ""),
    )


# ─── Helper: utilization multiplier ─────────────────────────────────────

def _utilization_multiplier(util: float, params: SimParams) -> float:
    """
    Compute the COGS multiplier based on capacity utilization.
    See doc 09: Parameters and Calibration.
    """
    if util >= 0.90:
        return 1.00
    elif util >= 0.70:
        return 1.00 + 0.50 * (0.90 - util)
    elif util >= 0.50:
        return 1.10 + 1.00 * (0.70 - util)
    elif util >= 0.30:
        return 1.30 + 1.50 * (0.50 - util)
    else:
        return 1.60 + 2.00 * (0.30 - util)
