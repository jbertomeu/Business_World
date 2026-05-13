"""
Feasibility clamping: convert raw decisions to feasible decisions.

Pure function. No LLM calls. No side effects.

Canonical reference: docs/architecture/17_clamping_algorithm.md
"""

from __future__ import annotations

import math

from .types import ClampedDecisions, FirmState, RawDecisions, SimParams


def clamp_decisions(
    firm: FirmState,
    decisions: RawDecisions,
    expected_revenue: float,
    expected_ar_collection: float,
    params: SimParams,
) -> ClampedDecisions:
    """
    Convert requested decisions to feasible decisions given available resources.

    Args:
        firm: Current FirmState (end of prior quarter)
        decisions: What the LLM requested
        expected_revenue: Optimistic estimate of cash from sales this Q
        expected_ar_collection: Prior AR expected to be collected this Q
        params: Simulation parameters

    Returns:
        ClampedDecisions with feasible values + clamping log
    """
    log: list[str] = []

    # ── Step 0: Sanitize inputs ──────────────────────────────────────────

    # Wave ν+2: removed the unit-cost price floor. The previous clamp
    # prevented the most extreme race-to-bottom outcomes but was a hard
    # quantitative rule. The new approach: products are DIFFERENTIATED
    # (env + firm prompts model this), so a firm pricing at unit cost
    # captures the price-sensitive segment but does NOT zero-out
    # competitors with loyal customer bases. Firms must reason about
    # price-war dynamics, competitor bankruptcy, and unilateral
    # sustainability themselves. Only sanity-floor at $0 (no negative).
    price = max(0.0, float(decisions.price))
    if price != decisions.price:
        log.append(f"price clipped from {decisions.price} to {price} (negative)")

    production = max(0, int(decisions.production))
    if production > firm.capacity_units:
        log.append(f"production clamped from {production} to {firm.capacity_units} (capacity)")
        production = firm.capacity_units

    capex = max(0.0, decisions.capex)
    rd_spend = max(0.0, decisions.rd_spend)
    sga_spend = max(0.0, decisions.sga_spend)
    dividends = max(0.0, decisions.dividends)
    buybacks = max(0.0, decisions.buybacks)

    # Validate R&D allocation
    alloc = dict(decisions.rd_allocation)
    alloc_sum = sum(alloc.values())
    if abs(alloc_sum - 1.0) > 0.01 and alloc_sum > 0:
        alloc = {k: v / alloc_sum for k, v in alloc.items()}
        log.append(f"R&D allocation renormalized from {alloc_sum:.2f} to 1.0")
    elif alloc_sum == 0:
        alloc = {"product": 0.6, "process": 0.25, "delivery": 0.15}
        log.append("R&D allocation was zero; set to default")

    # ── Step 1: Starting cash position ───────────────────────────────────

    available = firm.cash + expected_revenue + expected_ar_collection
    available_credit = firm.available_credit

    # ── Step 2: COGS (Priority 1) ────────────────────────────────────────

    proposed_production = production
    effective_unit_cost = 0.0

    for _iteration in range(5):
        effective_unit_cost = _compute_effective_unit_cost(
            firm, proposed_production, params
        )
        cogs_required = proposed_production * effective_unit_cost

        if cogs_required <= available:
            break

        new_production = int(available / effective_unit_cost) if effective_unit_cost > 0 else 0
        if new_production >= proposed_production:
            break
        proposed_production = new_production

    if proposed_production < production:
        log.append(f"production clamped from {production} to {proposed_production} "
                    f"(insufficient cash for COGS)")
    production = proposed_production

    cogs = production * effective_unit_cost
    available -= cogs

    # ── Step 3: Mandatory obligations (Priority 2) ───────────────────────
    # These include unavoidable operating costs. A firm that can't cover them
    # goes into default (it can't pay its people or maintain equipment).

    phase3_cost = params.mandatory_phase3_quarterly_cost
    interest_due = (firm.revolver_balance * firm.revolver_rate
                    + firm.long_term_debt * firm.term_debt_rate)
    taxes_due = firm.taxes_payable

    # Only Phase 3 R&D, interest, and taxes are genuinely mandatory from an
    # operational / legal standpoint. Previous versions imposed an "SGA floor"
    # and "maintenance capex floor" — those were BEHAVIORAL rules, removed so
    # firms can choose (and face the environment's consequences for under-
    # investing in overhead or equipment). Depreciation still erodes PP&E;
    # under-funding SGA will lose brand/service.
    mandatory = phase3_cost + interest_due + taxes_due

    credit_drawn = 0.0

    if mandatory > available + available_credit:
        log.append(f"DEFAULT: mandatory obligations ${mandatory:,.0f} exceed "
                    f"cash+credit ${available + available_credit:,.0f} "
                    f"(Phase 3 R&D + interest + taxes)")
        return ClampedDecisions(
            price=price,
            production=production,
            capex=0.0,
            rd_spend=phase3_cost,            # must still pay Phase 3 even in default
            rd_allocation=alloc,
            sga_spend=0.0,
            dividends=0.0,
            buybacks=0.0,
            credit_drawn=0.0,
            clamping_log=log,
            manipulation_amount=getattr(decisions, 'manipulation_amount', 0.0),
            decision_source=getattr(decisions, 'decision_source', 'llm'),
            fallback_reason=getattr(decisions, 'fallback_reason', ''),
            proposal_id=getattr(decisions, 'proposal_id', ''),
        )

    if mandatory > available:
        credit_needed = mandatory - available
        log.append(f"drawing ${credit_needed:,.0f} from revolver for mandatory costs")
        credit_drawn += credit_needed
        available_credit -= credit_needed
        available = 0.0
    else:
        available -= mandatory

    # ── Step 4: R&D/SGA/Capex minimum enforcement ────────────────────────

    if rd_spend < phase3_cost:
        log.append(f"R&D spend raised from ${rd_spend:,.0f} to "
                    f"${phase3_cost:,.0f} (mandatory minimum)")
        rd_spend = phase3_cost

    # No SGA / capex floor — firm judges (under-investing has emergent
    # consequences: PP&E depreciation, brand/service loss, etc.).
    discretionary_rd = rd_spend - phase3_cost
    discretionary_sga = sga_spend   # full SGA is discretionary
    discretionary_capex = capex     # full capex is discretionary

    # ── Step 5: Discretionary spending (Priority 3, pro-rata) ────────────
    # Only the portion ABOVE floors pro-rata clamps. Floors are in mandatory.

    discretionary_total = discretionary_rd + discretionary_sga + discretionary_capex

    if discretionary_total <= available:
        actual_disc_capex = discretionary_capex
        actual_disc_rd = discretionary_rd
        actual_disc_sga = discretionary_sga
        available -= discretionary_total
    else:
        cash_short = discretionary_total - available

        if cash_short <= available_credit:
            log.append(f"drawing ${cash_short:,.0f} from revolver for discretionary spending")
            credit_drawn += cash_short
            available_credit -= cash_short
            actual_disc_capex = discretionary_capex
            actual_disc_rd = discretionary_rd
            actual_disc_sga = discretionary_sga
            available = 0.0
        else:
            total_resources = available + available_credit
            if discretionary_total > 0:
                scale = total_resources / discretionary_total
            else:
                scale = 0.0
            log.append(f"pro-rata clamping discretionary at {scale:.2%} "
                        f"(insufficient cash+credit)")

            actual_disc_capex = discretionary_capex * scale
            actual_disc_rd = discretionary_rd * scale
            actual_disc_sga = discretionary_sga * scale

            credit_drawn += available_credit
            available_credit = 0.0
            available = 0.0

    actual_rd_spend = phase3_cost + actual_disc_rd
    actual_sga = actual_disc_sga  # no floor
    actual_capex = actual_disc_capex  # no floor

    # ── Step 6: Payouts (Priority 4, surplus only) ───────────────────────

    actual_dividends = 0.0
    actual_buybacks = 0.0

    if dividends > 0:
        if firm.retained_earnings <= 0:
            log.append(f"dividends blocked: retained earnings "
                        f"${firm.retained_earnings:,.0f} <= 0")
        elif available >= dividends:
            actual_dividends = dividends
            available -= dividends
        else:
            actual_dividends = max(0.0, available)
            if actual_dividends < dividends:
                log.append(f"dividends clamped from ${dividends:,.0f} to "
                            f"${actual_dividends:,.0f} (limited surplus)")
            available -= actual_dividends

    if buybacks > 0:
        if available >= buybacks:
            actual_buybacks = buybacks
            available -= buybacks
        else:
            actual_buybacks = max(0.0, available)
            if actual_buybacks < buybacks:
                log.append(f"buybacks clamped from ${buybacks:,.0f} to "
                            f"${actual_buybacks:,.0f} (limited surplus)")
            available -= actual_buybacks

    # ── Build result ─────────────────────────────────────────────────────

    # ── Stage 4/5 pass-through: clamp + forward to ClampedDecisions ──
    # None = no override (accounting uses params.theta_* / carry-forward).
    dpo_raw = getattr(decisions, "payables_days_target", None)
    dpo = None if dpo_raw is None else max(0.0, min(180.0, float(dpo_raw)))

    dso_raw = getattr(decisions, "receivables_days_target", None)
    dso = None if dso_raw is None else max(0.0, min(180.0, float(dso_raw)))

    deposit_raw = getattr(decisions, "deposit_pct", None)
    deposit = None if deposit_raw is None else max(0.0, min(1.0, float(deposit_raw)))

    ppe_disp_raw = float(getattr(decisions, "ppe_disposal", 0.0) or 0.0)
    # Cap disposal to current net PP&E (can't sell more than you have)
    ppe_disp = max(0.0, min(ppe_disp_raw, firm.ppe_net))

    allowance_raw = getattr(decisions, "allowance_pct_of_ar", None)
    allowance_pct = None if allowance_raw is None else max(0.0, min(1.0, float(allowance_raw)))

    # Stage 10: restructuring — cap impairments at available asset values.
    rs_sev = max(0.0, float(getattr(decisions, "restructuring_severance", 0.0) or 0.0))
    rs_ppe = max(0.0, min(float(getattr(decisions, "restructuring_ppe_impairment", 0.0) or 0.0),
                          firm.ppe_net))
    rs_inv = max(0.0, min(float(getattr(decisions, "restructuring_inventory_write_off", 0.0) or 0.0),
                          firm.inventory_value))
    rs_gw = max(0.0, min(float(getattr(decisions, "restructuring_goodwill_impairment", 0.0) or 0.0),
                         firm.goodwill))

    # Stage 11: CEO sell shares — cap at ceo_vested_shares_held.
    sell_raw = int(getattr(decisions, "ceo_sell_shares", 0) or 0)
    ceo_sell = max(0, min(sell_raw, firm.ceo_vested_shares_held))
    # Stage 12: CEO option exercise — cap at total vested-unexercised options.
    exer_raw = int(getattr(decisions, "ceo_exercise_options", 0) or 0)
    total_vested_opts = sum(
        max(0, g.shares_vested_to_date - g.shares_exercised)
        for g in firm.ceo_stock_grants
        if g.grant_type == "stock_option"
        and g.ceo_incarnation == firm.ceo_incarnation
    )
    ceo_exer = max(0, min(exer_raw, total_vested_opts))
    # Stage 12: legal reserves
    legal_res_chg = float(getattr(decisions, "legal_reserve_change", 0.0) or 0.0)
    legal_settle = max(0.0, float(getattr(decisions, "legal_settlements_paid", 0.0) or 0.0))
    legal_settle = min(legal_settle,
                       firm.legal_reserve_balance + max(0.0, legal_res_chg))
    # Stage 12: pension contribution — cap at pension liability + service cost proxy
    pension_contrib = max(0.0, float(getattr(decisions, "pension_contribution", 0.0) or 0.0))

    return ClampedDecisions(
        price=price,
        production=production,
        capex=actual_capex,
        rd_spend=actual_rd_spend,
        rd_allocation=alloc,
        sga_spend=actual_sga,
        dividends=actual_dividends,
        buybacks=actual_buybacks,
        credit_drawn=credit_drawn,
        clamping_log=log,
        manipulation_amount=getattr(decisions, 'manipulation_amount', 0.0),
        payables_days_target=dpo,
        receivables_days_target=dso,
        deposit_pct=deposit,
        ppe_disposal=ppe_disp,
        allowance_pct_of_ar=allowance_pct,
        restructuring_severance=rs_sev,
        restructuring_ppe_impairment=rs_ppe,
        restructuring_inventory_write_off=rs_inv,
        restructuring_goodwill_impairment=rs_gw,
        ceo_sell_shares=ceo_sell,
        ceo_exercise_options=ceo_exer,
        legal_reserve_change=legal_res_chg,
        legal_settlements_paid=legal_settle,
        pension_contribution=pension_contrib,
        decision_source=getattr(decisions, 'decision_source', 'llm'),
        fallback_reason=getattr(decisions, 'fallback_reason', ''),
        proposal_id=getattr(decisions, 'proposal_id', ''),
    )


# ─── Helper ──────────────────────────────────────────────────────────────

def _compute_effective_unit_cost(
    firm: FirmState,
    production_level: int,
    params: SimParams,
) -> float:
    """
    Compute per-unit cost for a given production level.
    Includes process R&D reduction and capacity utilization multiplier.
    """
    if firm.capacity_units == 0:
        return float("inf")
    if production_level == 0:
        return firm.base_unit_cost  # doesn't matter, COGS will be 0

    # Process R&D reduction
    process_reduction = (params.process_rd_max_reduction
                         * (1 - math.exp(-firm.rd_cumulative_process
                                          / params.process_rd_saturation)))
    base_cost = firm.base_unit_cost * (1 - process_reduction)

    # Utilization multiplier
    util = production_level / firm.capacity_units

    if util >= 0.90:
        mult = 1.00
    elif util >= 0.70:
        mult = 1.00 + 0.50 * (0.90 - util)
    elif util >= 0.50:
        mult = 1.10 + 1.00 * (0.70 - util)
    elif util >= 0.30:
        mult = 1.30 + 1.50 * (0.50 - util)
    else:
        mult = 1.60 + 2.00 * (0.30 - util)

    return base_cost * mult
