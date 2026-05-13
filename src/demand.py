"""
Deterministic multinomial logit demand model.

This is the FALLBACK demand system used when:
- The environment LLM is unavailable
- The environment output fails validation
- Computing the baseline for environment prompt guidance

It is also the orchestrator's validation reference: the environment LLM's
demand allocation should be broadly consistent with this model.

Parameters from: docs/world/09_parameters_and_calibration.md
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .types import FirmState, MacroState, SimParams


@dataclass
class DemandResult:
    """Output of the demand model."""
    total_demand: int
    firm_units: dict[str, int]       # firm_id -> units sold
    firm_shares: dict[str, float]    # firm_id -> market share
    baseline_note: str = ""


def compute_demand_baseline(
    firms: dict[str, FirmState],
    actions: dict[str, dict],
    macro: MacroState,
    params: SimParams,
) -> DemandResult:
    """
    Compute deterministic demand allocation using multinomial logit.

    Args:
        firms: dict of firm_id -> FirmState
        actions: dict of firm_id -> {"price": float, "production": int}
        macro: current MacroState
        params: SimParams

    Returns:
        DemandResult with total demand and per-firm allocation
    """

    # ── Step 1: Compute total potential market ───────────────────────────

    aware_population = macro.market_size_baseline * macro.awareness_rate
    # Apply macro shock as a demand multiplier
    demand_multiplier = 1.0 + macro.macro_shock
    potential = aware_population * demand_multiplier

    # ── Step 2: Compute utility for each firm ────────────────────────────

    # Get quality weights for this quarter
    w_eff, w_saf, w_con = _get_quality_weights(macro.quarter, params)

    utilities = {}
    for fid, firm in firms.items():
        if not firm.is_active:
            continue

        action = actions.get(fid, {})
        price = action.get("price", 0)
        production = action.get("production", 0)

        if production == 0 or price <= 0:
            utilities[fid] = -1e10  # effectively zero share
            continue

        # Quality composite
        gen = firm.product_generation
        eff_idx, saf_idx, con_idx = params.gen_quality.get(gen, (35, 27, 20))

        # Adjust for capability stock (incremental within generation)
        base_eff = params.gen_quality[gen][0]
        eff_bonus = max(0, (firm.capability_stock - base_eff) * 0.5)
        eff_idx = min(100, eff_idx + eff_bonus)

        raw_quality = w_eff * eff_idx + w_saf * saf_idx + w_con * con_idx

        # AE demand modifier
        ae_rate = params.gen_serious_ae_rate.get(gen, 0.073)
        ae_modifier = _ae_demand_modifier(ae_rate)
        effective_quality = raw_quality * ae_modifier

        # Brand
        brand = firm.brand_stock

        # Taste shock
        taste = macro.taste_shocks.get(fid, 0.0)

        # Utility: a * quality - b * price + g * brand + taste
        # Wave ι: coefficients sourced from SimParams so scenarios can tune
        # industry-specific elasticities.
        a = params.demand_quality_coef
        b = params.demand_price_coef
        g = params.demand_brand_coef

        u = a * effective_quality - b * price + g * brand + taste
        utilities[fid] = u

    # ── Step 3: Outside option utility ───────────────────────────────────

    # V_0 decays from base toward floor as awareness grows. Wave ι:
    # scenario-controllable so breakthrough industries (longevity) can
    # keep outside utility low, while declining industries can keep it
    # high (more consumers prefer no treatment as market matures).
    v0_base = params.outside_utility_base
    v0_decay = params.outside_utility_decay
    v0_floor = params.outside_utility_floor
    v0 = max(v0_floor, v0_base - v0_decay * macro.quarter)

    outside_utility = v0 + macro.macro_shock

    # ── Step 4: Multinomial logit shares ─────────────────────────────────

    # exp(utility) for each option
    max_u = max(max(utilities.values()) if utilities else 0, outside_utility)

    exp_utils = {}
    for fid, u in utilities.items():
        exp_utils[fid] = math.exp(u - max_u)  # subtract max for numerical stability

    exp_outside = math.exp(outside_utility - max_u)
    total_exp = sum(exp_utils.values()) + exp_outside

    shares = {}
    for fid in exp_utils:
        shares[fid] = exp_utils[fid] / total_exp

    outside_share = exp_outside / total_exp

    # ── Step 5: Convert shares to units ──────────────────────────────────

    # Total market size: potential * (1 - outside_share) gives "willing buyers"
    # But this gives the theoretical maximum. Actual is much smaller in early quarters
    # because the logit naturally allocates most to the outside option.

    # Scale factor: at the market-level, we want total industry units to be
    # reasonable. The "potential" is hundreds of millions but actual buyers
    # at $80K+ are tens of thousands.
    #
    # The logit share for the "inside options" (all firms combined) represents
    # the fraction of aware population that would buy at current prices/quality.
    inside_share = 1.0 - outside_share

    # Total willing buyers from the aware population
    # Note: aware_population is e.g. 600M * 0.15 = 90M in Q1
    # inside_share might be 0.001 (very small), giving ~90K buyers
    total_willing = potential * inside_share

    # But buyers are further filtered by price affordability
    # Use a rough affordability filter based on average price.
    # Wave ν+3: guard against ZeroDivisionError when all firms have zero
    # share (e.g., last surviving firm with no demand yet, or all firms
    # priced themselves out). Fall back to unweighted mean of stated
    # prices, then to default.
    total_share = sum(shares.values()) if shares else 0.0
    if shares and total_share > 0:
        avg_price = sum(
            actions.get(fid, {}).get("price", 100_000) * s
            for fid, s in shares.items()
        ) / total_share
    elif shares:
        # Shares exist but all zero — use unweighted mean of prices
        prices = [actions.get(fid, {}).get("price", 100_000) for fid in shares]
        avg_price = sum(prices) / len(prices) if prices else 100_000
    else:
        avg_price = 100_000

    # Affordability: fraction of willing buyers who can actually pay.
    # Wave ι: scenario-controllable. For longevity/cancer/rare disease
    # (high willingness-to-pay), scenarios raise the center and/or
    # lower steepness so more buyers can pay at given price.
    affordability = 1.0 / (1.0 + math.exp(
        params.affordability_steepness * (avg_price - params.affordability_center)
    ))

    total_demand_raw = total_willing * affordability
    total_demand = max(1, int(total_demand_raw))

    # ── Step 6: Allocate to firms, capped by production ──────────────────

    # Normalize shares among firms only (not outside option)
    firm_share_sum = sum(shares.values())
    if firm_share_sum > 0:
        normalized_shares = {fid: s / firm_share_sum for fid, s in shares.items()}
    else:
        normalized_shares = {fid: 1.0 / len(shares) for fid in shares}

    # Initial allocation
    firm_units = {}
    remaining = total_demand
    production_caps = {fid: actions.get(fid, {}).get("production", 0) for fid in shares}

    # First pass: allocate proportionally, cap at production
    uncapped_units = {}
    capped_firms = set()
    for fid, share in normalized_shares.items():
        raw_units = int(total_demand * share)
        cap = production_caps.get(fid, 0)
        if raw_units > cap:
            uncapped_units[fid] = cap
            capped_firms.add(fid)
        else:
            uncapped_units[fid] = raw_units

    # Second pass: redistribute excess from capped firms
    allocated = sum(uncapped_units.values())
    excess = total_demand - allocated

    if excess > 0 and len(capped_firms) < len(shares):
        uncapped_fids = [fid for fid in shares if fid not in capped_firms]
        uncapped_share_sum = sum(normalized_shares[fid] for fid in uncapped_fids)
        if uncapped_share_sum > 0:
            for fid in uncapped_fids:
                extra = int(excess * normalized_shares[fid] / uncapped_share_sum)
                cap = production_caps.get(fid, 0)
                uncapped_units[fid] = min(cap, uncapped_units[fid] + extra)

    # Final: ensure sum equals total_demand (adjust largest firm for rounding)
    firm_units = dict(uncapped_units)
    current_total = sum(firm_units.values())
    if current_total != total_demand and firm_units:
        # Adjust the firm with most units
        largest = max(firm_units, key=firm_units.get)
        firm_units[largest] += (total_demand - current_total)
        # But don't exceed production
        cap = production_caps.get(largest, 0)
        if firm_units[largest] > cap:
            firm_units[largest] = cap

    # Recompute actual total and shares
    actual_total = sum(firm_units.values())
    firm_shares = {}
    for fid in firm_units:
        firm_shares[fid] = firm_units[fid] / actual_total if actual_total > 0 else 0

    return DemandResult(
        total_demand=actual_total,
        firm_units=firm_units,
        firm_shares=firm_shares,
        baseline_note=(
            f"Logit baseline: {actual_total} units "
            f"(aware={aware_population/1e6:.1f}M, inside_share={inside_share:.4f}, "
            f"affordability={affordability:.3f})"
        ),
    )


# ─── Helpers ─────────────────────────────────────────────────────────────

def _get_quality_weights(quarter: int, params: SimParams) -> tuple[float, float, float]:
    """Get interpolated quality weights for this quarter."""
    schedule = params.quality_weight_schedule
    # Find the bracket
    prev_q, prev_w = 0, schedule[0][1:]
    for max_q, w_e, w_s, w_c in schedule:
        if quarter <= max_q:
            # Linear interpolation from prev to current
            if max_q == prev_q:
                return (w_e, w_s, w_c)
            t = (quarter - prev_q) / (max_q - prev_q)
            return (
                prev_w[0] + t * (w_e - prev_w[0]),
                prev_w[1] + t * (w_s - prev_w[1]),
                prev_w[2] + t * (w_c - prev_w[2]),
            )
        prev_q = max_q
        prev_w = (w_e, w_s, w_c)
    # Past the last bracket
    return schedule[-1][1:]


def _ae_demand_modifier(serious_ae_rate: float) -> float:
    """
    Quality multiplier based on serious adverse event rate.
    From doc 09 / doc 04.
    """
    if serious_ae_rate > 0.05:
        return 0.5
    elif serious_ae_rate > 0.03:
        return 0.7
    elif serious_ae_rate > 0.01:
        return 1.0
    elif serious_ae_rate > 0.005:
        return 1.3
    elif serious_ae_rate > 0.001:
        return 2.0
    else:
        return 3.0
