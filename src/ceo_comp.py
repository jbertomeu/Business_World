"""
CEO compensation with grants, vesting, selling, retirement.

Mirrors ExecuComp databases at a simplified level:
- Annual summary (existing `execucomp.csv`, extended with shares_owned_eoy etc.)
- Grants (new `execucomp_grants.csv` — one row per new grant event)
- Outstanding (new `execucomp_outstanding.csv` — annual year-end snapshot)

Only time-based vesting (no performance conditions). Grant types:
- "rsu" (restricted stock units): shares vest on schedule; no strike price
- "stock_option": shares granted as options; vest on schedule; CEO must pay
  strike to exercise. In-the-money intrinsic value = max(0, price − strike).

Lifecycle:
- Board grants awards (annual decision at fqtr=4)
- Each quarter, automatic vesting check: schedule → vested_shares increment
- CEO can sell vested shares (vested_shares_held → cash_from_sales)
- Fire: unvested forfeited, vested retained
- Retirement (voluntary age ≥60 / mandatory ≥65): unvested vest immediately

All mutations here are pure Python; LLM decides policy (grant structure,
retire/sell choices) elsewhere.
"""

from __future__ import annotations

from dataclasses import replace
from .types import FirmState, StockGrant


VALID_GRANT_TYPES = ("rsu", "stock_option")


# ─── Grant creation ──────────────────────────────────────────────────────


def _next_grant_id(firm: FirmState) -> str:
    n = len(firm.ceo_stock_grants) + 1
    return f"{firm.firm_id}-GRANT-{n:04d}"


def create_grant(firm: FirmState,
                 grant_type: str,
                 shares: int,
                 strike_price: float,
                 vesting_schedule: tuple,
                 grant_quarter: int,
                 share_price_at_grant: float) -> tuple[FirmState, StockGrant]:
    """Issue a new grant to the CEO. Returns (new_firm, grant).

    `vesting_schedule` is a tuple of (quarter_offset, fraction) pairs. Sum of
    fractions should ≈ 1.0 (we don't enforce — the grant records what the
    board specified). Example 4-year annual cliff: ((4, 0.25), (8, 0.25),
    (12, 0.25), (16, 0.25)).

    `share_price_at_grant` is used to compute fair_value_at_grant:
    - RSU: shares × share_price
    - Option: Black-Scholes is too complex; use a simple intrinsic + time-
      value proxy (max(0, share_price - strike) × shares + 0.3 × strike ×
      shares as a crude time-value component). Sufficient for reporting.
    """
    if grant_type not in VALID_GRANT_TYPES:
        raise ValueError(f"grant_type must be one of {VALID_GRANT_TYPES}, got {grant_type}")
    if shares <= 0:
        raise ValueError("grant shares must be positive")
    if grant_type == "stock_option" and strike_price <= 0:
        raise ValueError("stock_option grants require positive strike_price")

    # Fair value at grant (simplified)
    if grant_type == "rsu":
        fv = shares * share_price_at_grant
    else:  # option
        intrinsic = max(0.0, share_price_at_grant - strike_price) * shares
        time_value = 0.3 * strike_price * shares  # crude proxy
        fv = intrinsic + time_value

    grant = StockGrant(
        grant_id=_next_grant_id(firm),
        ceo_id=firm.ceo_type or "ceo",
        ceo_incarnation=firm.ceo_incarnation,
        firm_id=firm.firm_id,
        grant_quarter=grant_quarter,
        grant_type=grant_type,
        shares=shares,
        strike_price=float(strike_price),
        vesting_schedule=tuple(vesting_schedule),
        fair_value_at_grant=fv,
        shares_vested_to_date=0,
        shares_forfeited=0,
        shares_exercised=0,
    )
    new_firm = firm.evolve(
        ceo_stock_grants=firm.ceo_stock_grants + (grant,),
    )
    return new_firm, grant


# ─── Vesting ──────────────────────────────────────────────────────────────


def quarterly_sbc_expense(firm: FirmState, current_quarter: int) -> float:
    """Compute this quarter's stock-based compensation expense (GAAP).

    GAAP amortizes a grant's fair value over its vesting period: each
    quarter, recognize FV × fraction_vesting_this_Q. Only active (current-
    incarnation) grants contribute; already-forfeited shares don't.

    Returns total SBC expense for the quarter (for `ceo_stock_comp_this_q`).
    """
    total_fv_vested_this_q = 0.0
    for g in firm.ceo_stock_grants:
        if g.ceo_incarnation != firm.ceo_incarnation:
            continue
        # Sum the fraction that vests exactly this quarter (not cumulative).
        frac_this_q = sum(
            frac for (offset, frac) in g.vesting_schedule
            if g.grant_quarter + offset == current_quarter
        )
        if frac_this_q <= 0:
            continue
        # FV weighted by fraction of total grant vesting this Q.
        # Reduce by forfeiture share (pro-rata).
        active_shares = max(0, g.shares - g.shares_forfeited)
        if g.shares > 0:
            active_ratio = active_shares / g.shares
        else:
            active_ratio = 0.0
        total_fv_vested_this_q += g.fair_value_at_grant * frac_this_q * active_ratio
    return total_fv_vested_this_q


def vest_grants_this_quarter(firm: FirmState,
                               current_quarter: int) -> tuple[FirmState, int]:
    """Apply scheduled vesting to grants OWNED BY THE CURRENT CEO.

    Grants owned by prior CEO incarnations are skipped — they stay in the
    historical record (`ceo_stock_grants` tuple) with their forfeiture /
    acceleration state frozen, but do not accrue new vestings to the current
    (different) CEO.

    Returns (new_firm, shares_vested_this_q_for_current_ceo).
    """
    new_grants = []
    new_vested_rsu_shares = 0
    for g in firm.ceo_stock_grants:
        # Grants for past CEO incarnations: frozen archival record, no change.
        if g.ceo_incarnation != firm.ceo_incarnation:
            new_grants.append(g)
            continue
        cumulative_vested_frac = 0.0
        for (offset, frac) in g.vesting_schedule:
            if g.grant_quarter + offset <= current_quarter:
                cumulative_vested_frac += frac
        target_vested = int(g.shares * min(1.0, cumulative_vested_frac))
        new_to_vest = max(0, target_vested - g.shares_vested_to_date
                          - g.shares_forfeited)
        if new_to_vest > 0 and g.grant_type == "rsu":
            new_vested_rsu_shares += new_to_vest
        new_grants.append(replace(g, shares_vested_to_date=g.shares_vested_to_date + new_to_vest))

    new_firm = firm.evolve(
        ceo_stock_grants=tuple(new_grants),
        ceo_vested_shares_held=firm.ceo_vested_shares_held + new_vested_rsu_shares,
    )
    return new_firm, new_vested_rsu_shares


# ─── Sell (CEO decision) ──────────────────────────────────────────────────


def sell_vested_shares(firm: FirmState, shares_to_sell: int,
                         current_price: float, current_quarter: int) -> FirmState:
    """CEO sells some of their vested RSU shares at the current market price.

    Shares come out of `ceo_vested_shares_held`. Cash proceeds go to
    `ceo_cash_from_sales` (informational — the CEO's personal wealth, not
    the firm's cash). The shares are retired from CEO holdings and counted
    in `ceo_shares_sold_cumulative` for WRDS execucomp disclosures.
    """
    if shares_to_sell <= 0 or current_price <= 0:
        return firm
    shares_sold = min(shares_to_sell, firm.ceo_vested_shares_held)
    if shares_sold == 0:
        return firm
    proceeds = shares_sold * current_price
    return firm.evolve(
        ceo_vested_shares_held=firm.ceo_vested_shares_held - shares_sold,
        ceo_shares_sold_cumulative=firm.ceo_shares_sold_cumulative + shares_sold,
        ceo_cash_from_sales=firm.ceo_cash_from_sales + proceeds,
    )


# ─── Termination (fire / retire) ──────────────────────────────────────────


def forfeit_unvested(firm: FirmState) -> FirmState:
    """Apply "fire" event: the CURRENT CEO's unvested shares are forfeited.

    Only touches grants owned by the current `ceo_incarnation`. Previously-
    forfeited grants (from earlier CEOs' firings) are left untouched.
    """
    new_grants = []
    for g in firm.ceo_stock_grants:
        if g.ceo_incarnation != firm.ceo_incarnation:
            new_grants.append(g)
            continue
        unvested = g.shares - g.shares_vested_to_date - g.shares_forfeited
        if unvested > 0:
            new_grants.append(replace(g, shares_forfeited=g.shares_forfeited + unvested))
        else:
            new_grants.append(g)
    return firm.evolve(ceo_stock_grants=tuple(new_grants))


def accelerate_vesting_on_retirement(firm: FirmState) -> tuple[FirmState, int]:
    """CEO retires voluntarily — accelerate vesting on CURRENT CEO's unvested.

    Only touches grants owned by the current `ceo_incarnation`.
    Returns (new_firm, total_accelerated_rsu_shares).
    """
    new_grants = []
    total_accelerated_rsu = 0
    for g in firm.ceo_stock_grants:
        if g.ceo_incarnation != firm.ceo_incarnation:
            new_grants.append(g)
            continue
        unvested = g.shares - g.shares_vested_to_date - g.shares_forfeited
        if unvested > 0:
            new_grants.append(replace(g,
                                       shares_vested_to_date=g.shares_vested_to_date + unvested))
            if g.grant_type == "rsu":
                total_accelerated_rsu += unvested
        else:
            new_grants.append(g)
    new_firm = firm.evolve(
        ceo_stock_grants=tuple(new_grants),
        ceo_vested_shares_held=firm.ceo_vested_shares_held + total_accelerated_rsu,
    )
    return new_firm, total_accelerated_rsu


# ─── Introspection helpers ────────────────────────────────────────────────


def outstanding_snapshot(firm: FirmState, current_price: float) -> dict:
    """Compute the CURRENT CEO's grant holdings summary (ExecuComp-style).

    Only grants belonging to the current CEO incarnation are counted — prior
    CEOs' grants are archival only. Returns fields suitable for
    `execucomp_outstanding.csv`:
      - unvested_rsu_shares, unvested_option_shares
      - vested_rsu_held_shares (on the CEO's books), vested_options
      - intrinsic_value_vested_options
      - intrinsic_value_unvested (for options, Max(0, price-strike); for RSU, shares × price)
      - total_shares_sold_to_date
    """
    unvested_rsu = 0
    unvested_opt = 0
    vested_opt = 0
    iv_vested_opt = 0.0
    iv_unvested = 0.0
    for g in firm.ceo_stock_grants:
        # Skip grants belonging to prior CEO incarnations
        if g.ceo_incarnation != firm.ceo_incarnation:
            continue
        outstanding = g.shares - g.shares_forfeited
        vested = g.shares_vested_to_date
        unvested = max(0, outstanding - vested)
        if g.grant_type == "rsu":
            unvested_rsu += unvested
            iv_unvested += unvested * current_price
        else:  # stock_option
            unvested_opt += unvested
            vested_opt += vested - g.shares_exercised
            iv_vested_opt += max(0.0, current_price - g.strike_price) * (vested - g.shares_exercised)
            iv_unvested += max(0.0, current_price - g.strike_price) * unvested
    return {
        "unvested_rsu_shares": unvested_rsu,
        "unvested_option_shares": unvested_opt,
        "vested_rsu_held_shares": firm.ceo_vested_shares_held,
        "vested_option_shares": vested_opt,
        "intrinsic_value_vested_options": iv_vested_opt,
        "intrinsic_value_unvested": iv_unvested,
        "total_shares_sold_to_date": firm.ceo_shares_sold_cumulative,
        "cash_from_sales_cumulative": firm.ceo_cash_from_sales,
    }
