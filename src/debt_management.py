"""
Debt management: pure Python bookkeeping for DebtFacility state.

All balance mutations, amortization, interest accrual, maturity handling,
and covenant testing happen here. LLMs never directly modify facility balances.
LLMs only decide policy (approve/deny, set covenants, waive/amend/accelerate);
this module enforces the math.

Consistency invariants are checked every quarter after mutations.

Principle: the code does not impose economic rules (rates, thresholds, haircuts);
those emerge from LLM negotiation. The code enforces only:
- Accounting identities (sum of facility balances = aggregate debt)
- Structural bounds (max facilities, valid types, no negative balances)
- Deterministic math (interest = balance × rate; principal amortization schedule)
"""

from __future__ import annotations

from dataclasses import replace
from typing import Literal

from .types import (
    FirmState, DebtFacility, Covenant, CovenantViolationEvent,
)


# Structural whitelists (universe of instruments / covenants the sim supports)
VALID_FACILITY_TYPES = (
    "bank_term",         # amortizing or bullet bank loan, has covenants
    "bank_revolver",     # drawable credit line, may have covenants
    "bond",              # public debt, bullet, usually incurrence covenants only
    "convertible_bond",  # bond convertible to equity at conversion_price
)

VALID_COVENANT_TYPES = (
    "max_debt_to_ebitda",     # leverage ceiling
    "min_interest_coverage",  # EBITDA / interest expense floor
    "min_cash_balance",       # $ floor
    "min_liquidity",          # cash + unused revolver
    "min_net_worth",          # equity floor
)

VALID_AMORTIZATION = ("bullet", "amortizing", "revolver")

VALID_STATUS = (
    "current", "in_cure_period", "amended", "accelerated",
    "repaid", "defaulted", "converted",
)


# ── Facility ID generation ────────────────────────────────────────────

def _next_facility_id(firm: FirmState) -> str:
    """Generate a unique facility ID for a firm."""
    existing = [f.facility_id for f in firm.debt_facilities]
    n = len(existing) + 1
    return f"{firm.firm_id}-FAC-{n:03d}"


# ── Add / remove / prepay facilities ──────────────────────────────────

def add_facility(firm: FirmState, facility: DebtFacility,
                 max_active: int = 10) -> FirmState:
    """Register a new debt facility on the firm.

    Raises ValueError if structural constraints are violated.
    Also updates aggregate long_term_debt / revolver_balance.
    """
    # Structural validations
    if facility.facility_type not in VALID_FACILITY_TYPES:
        raise ValueError(f"Invalid facility_type: {facility.facility_type}")
    if facility.amortization_type not in VALID_AMORTIZATION:
        raise ValueError(f"Invalid amortization_type: {facility.amortization_type}")
    for cov in facility.covenants:
        if cov.covenant_type not in VALID_COVENANT_TYPES:
            raise ValueError(f"Invalid covenant_type: {cov.covenant_type}")
    if facility.current_balance < 0:
        raise ValueError("Facility balance cannot be negative at origination")
    if facility.original_principal <= 0:
        raise ValueError("Facility principal must be positive")
    # Revolvers must be undrawn at origination — subsequent draws go through
    # draw_revolver() which properly credits cash. Originating a revolver with
    # a drawn balance would add the liability without the matching cash inflow.
    if (facility.facility_type == "bank_revolver"
            and facility.current_balance > 0):
        raise ValueError(
            f"bank_revolver must originate with current_balance=0 "
            f"(got {facility.current_balance}); use draw_revolver() to draw."
        )
    # Convertible sanity: ratio and price must be positive, and ratio × par
    # must not imply extreme dilution. A ratio of 10k shares per $1000 face
    # is almost certainly an LLM hallucination. Cap at 1000 shares per $1000
    # face (= $1/share conversion — already extremely dilutive but bounded).
    if facility.facility_type == "convertible_bond":
        if facility.conversion_ratio <= 0 or facility.conversion_price <= 0:
            raise ValueError(
                f"convertible_bond must have positive conversion_ratio and "
                f"conversion_price (got {facility.conversion_ratio}, "
                f"{facility.conversion_price})"
            )
        if facility.conversion_ratio > 1000:
            raise ValueError(
                f"convertible_bond conversion_ratio={facility.conversion_ratio} "
                f"> 1000 shares/$1000 face — implausibly dilutive "
                f"(likely LLM unit confusion)"
            )

    active = [f for f in firm.debt_facilities
              if f.status not in ("repaid", "defaulted", "converted")]
    if len(active) >= max_active:
        raise ValueError(f"Firm {firm.firm_id} already has {len(active)} active facilities "
                         f"(max {max_active}); repay some before adding more")

    # Assign ID if not provided
    if not facility.facility_id:
        facility = replace(facility, facility_id=_next_facility_id(firm), firm_id=firm.firm_id)

    new_facilities = firm.debt_facilities + (facility,)

    # Update aggregate balances
    new_ltd = _sum_non_revolver(new_facilities) + _non_facility_ltd(firm)
    new_rev = _sum_revolver(new_facilities) + _non_facility_rev(firm)

    return firm.evolve(
        debt_facilities=new_facilities,
        long_term_debt=new_ltd,
        revolver_balance=new_rev,
        # If facility is cash-providing (term/bond), add to cash
        cash=firm.cash + (facility.current_balance
                          if facility.facility_type != "bank_revolver" else 0.0),
    )


def prepay_facility(firm: FirmState, facility_id: str, amount: float) -> FirmState:
    """Partially or fully repay a facility. amount comes out of cash."""
    if amount <= 0:
        return firm
    new_facilities = []
    found = False
    cash_used = 0.0
    for f in firm.debt_facilities:
        if f.facility_id == facility_id and f.status == "current":
            pay = min(amount, f.current_balance, max(0.0, firm.cash))
            new_balance = f.current_balance - pay
            cash_used = pay
            new_status = "repaid" if new_balance < 1.0 else f.status
            new_facilities.append(replace(f, current_balance=new_balance, status=new_status))
            found = True
        else:
            new_facilities.append(f)
    if not found:
        return firm  # silently noop if facility not found / not current

    new_facilities = tuple(new_facilities)
    new_ltd = _sum_non_revolver(new_facilities) + _non_facility_ltd(firm)
    new_rev = _sum_revolver(new_facilities) + _non_facility_rev(firm)
    return firm.evolve(
        debt_facilities=new_facilities,
        long_term_debt=new_ltd,
        revolver_balance=new_rev,
        cash=firm.cash - cash_used,
    )


def draw_revolver(firm: FirmState, facility_id: str, amount: float) -> FirmState:
    """Draw on an existing revolver up to its committed amount."""
    if amount <= 0:
        return firm
    new_facilities = []
    drawn = 0.0
    for f in firm.debt_facilities:
        if (f.facility_id == facility_id
                and f.facility_type == "bank_revolver"
                and f.status == "current"):
            room = f.original_principal - f.current_balance
            draw = min(amount, max(0.0, room))
            new_facilities.append(replace(f, current_balance=f.current_balance + draw))
            drawn = draw
        else:
            new_facilities.append(f)

    new_facilities = tuple(new_facilities)
    new_rev = _sum_revolver(new_facilities) + _non_facility_rev(firm)
    return firm.evolve(
        debt_facilities=new_facilities,
        revolver_balance=new_rev,
        cash=firm.cash + drawn,
    )


# ── Amortization (quarterly) ──────────────────────────────────────────

def amortize_quarter(firm: FirmState, current_quarter: int) -> tuple[FirmState, float, float]:
    """Apply one quarter of amortization to all active facilities.

    - Accrues interest on each facility at its rate × balance
    - Applies scheduled principal for amortizing facilities (straight-line
      over remaining quarters to maturity)
    - Marks matured facilities as 'repaid' (bullet) or 'defaulted' if cash short
    - Returns (new_firm_state, total_interest_paid, total_principal_paid)

    Caller routes interest_paid into CFO (operating cash out) and
    principal_paid into CFF (financing cash out) for proper compustat
    reconciliation. If cash is insufficient for scheduled payment, the
    facility shifts to 'in_cure_period' (a technical default that the
    orchestrator will resolve via the violation-resolution phase).
    """
    new_facilities = []
    total_interest = 0.0
    total_principal = 0.0
    cash_remaining = firm.cash
    for f in firm.debt_facilities:
        # Skip terminal statuses — a facility that's been repaid, defaulted,
        # converted, OR accelerated (bank has demanded + call resolved) should
        # not continue to accrue interest or service principal. Accelerated
        # facilities with residual balance stay on BS until Phase 15 settlement
        # converts them to `defaulted` (see settlement in orchestrator).
        if f.status in ("repaid", "defaulted", "converted", "accelerated"):
            new_facilities.append(f)
            continue

        # Interest accrual
        interest = f.current_balance * f.coupon_rate_quarterly
        total_interest += interest
        cash_remaining -= interest  # interest paid in cash this quarter

        # Maturity handling
        if current_quarter >= f.maturity_quarter and f.current_balance > 0:
            # Bullet maturity — full principal due
            payoff = min(f.current_balance, max(0.0, cash_remaining))
            new_balance = f.current_balance - payoff
            cash_remaining -= payoff
            total_principal += payoff
            if new_balance < 1.0:
                new_status = "repaid"
            else:
                new_status = "in_cure_period"  # couldn't pay at maturity
            new_facilities.append(replace(f, current_balance=new_balance, status=new_status))
            continue

        # Scheduled principal amortization (only for amortizing type)
        if f.amortization_type == "amortizing" and f.current_balance > 0:
            q_remaining = max(1, f.maturity_quarter - current_quarter)
            scheduled_principal = f.current_balance / q_remaining
            paid = min(scheduled_principal, f.current_balance, max(0.0, cash_remaining))
            new_balance = f.current_balance - paid
            cash_remaining -= paid
            total_principal += paid
            new_status = f.status
            if scheduled_principal > paid + 1.0:
                # Couldn't meet scheduled amortization
                new_status = "in_cure_period"
            new_facilities.append(replace(f, current_balance=new_balance, status=new_status))
            continue

        new_facilities.append(f)

    new_facilities = tuple(new_facilities)
    new_ltd = _sum_non_revolver(new_facilities) + _non_facility_ltd(firm)
    new_rev = _sum_revolver(new_facilities) + _non_facility_rev(firm)
    # Note: cash can go negative here; settlement phase will handle
    new_firm = firm.evolve(
        debt_facilities=new_facilities,
        long_term_debt=new_ltd,
        revolver_balance=new_rev,
        cash=cash_remaining,
    )
    return new_firm, total_interest, total_principal


# ── Covenant ratio computation (deterministic) ───────────────────────

def compute_ratios(firm: FirmState, ttm_ebitda: float, ttm_interest: float) -> dict:
    """Compute all covenant-relevant ratios deterministically.

    Takes TTM EBITDA and interest expense from caller (orchestrator computes
    from last 4 quarters of flows).
    """
    total_debt = firm.revolver_balance + firm.long_term_debt

    # Unused revolver capacity (for min_liquidity)
    unused_revolver = 0.0
    for f in firm.debt_facilities:
        if f.facility_type == "bank_revolver" and f.status == "current":
            unused_revolver += max(0.0, f.original_principal - f.current_balance)

    return {
        "debt_to_ebitda": total_debt / ttm_ebitda if ttm_ebitda > 0 else float("inf"),
        "interest_coverage": ttm_ebitda / ttm_interest if ttm_interest > 0 else float("inf"),
        "cash_balance": firm.cash,
        "liquidity": firm.cash + unused_revolver,
        "net_worth": firm.total_equity,
    }


def test_covenants(firm: FirmState, ttm_ebitda: float, ttm_interest: float) -> list[dict]:
    """Check all covenants on active facilities. Returns list of violations.

    A violation dict: {facility_id, covenant_type, threshold, measured_ratio}
    """
    ratios = compute_ratios(firm, ttm_ebitda, ttm_interest)
    violations = []
    for f in firm.debt_facilities:
        # Covenants don't get retested on terminal-state facilities:
        # accelerated/repaid/defaulted/converted are closed out.
        if f.status not in ("current", "in_cure_period", "amended"):
            continue
        for cov in f.covenants:
            if cov.test_frequency != "quarterly":
                continue
            measured = _ratio_for_covenant(cov.covenant_type, ratios)
            if measured is None:
                continue
            violated = _is_violated(cov.covenant_type, measured, cov.threshold)
            if violated:
                violations.append({
                    "facility_id": f.facility_id,
                    "covenant_type": cov.covenant_type,
                    "threshold": cov.threshold,
                    "measured_ratio": measured,
                })
    return violations


def _ratio_for_covenant(cov_type: str, ratios: dict) -> float | None:
    """Map covenant type to the relevant ratio key."""
    mapping = {
        "max_debt_to_ebitda": ratios.get("debt_to_ebitda"),
        "min_interest_coverage": ratios.get("interest_coverage"),
        "min_cash_balance": ratios.get("cash_balance"),
        "min_liquidity": ratios.get("liquidity"),
        "min_net_worth": ratios.get("net_worth"),
    }
    return mapping.get(cov_type)


def _is_violated(cov_type: str, measured: float, threshold: float) -> bool:
    """True if measured value breaches the covenant direction."""
    # "max_" covenants: violated if measured > threshold
    # "min_" covenants: violated if measured < threshold
    if cov_type.startswith("max_"):
        return measured > threshold
    if cov_type.startswith("min_"):
        return measured < threshold
    return False


# ── Violation resolution (policy set by LLM; this applies it) ─────────

def apply_waiver(firm: FirmState, facility_id: str, covenant_type: str,
                 waiver_fee: float, quarter: int) -> tuple[FirmState, CovenantViolationEvent]:
    """Apply a waiver: clear violation flag, charge fee from cash."""
    new_facilities = []
    event = None
    for f in firm.debt_facilities:
        if f.facility_id == facility_id:
            new_covs = []
            for cov in f.covenants:
                if cov.covenant_type == covenant_type:
                    new_covs.append(replace(cov, currently_violated=False,
                                             quarters_in_violation=0))
                else:
                    new_covs.append(cov)
            new_facilities.append(replace(f, covenants=tuple(new_covs), status="current"))
        else:
            new_facilities.append(f)

    event = CovenantViolationEvent(
        firm_id=firm.firm_id, facility_id=facility_id,
        covenant_type=covenant_type, violation_quarter=quarter,
        resolution="waived", waiver_fee=waiver_fee, resolution_quarter=quarter,
    )
    # Waiver fee is an expense — debit cash AND reduce retained earnings.
    # Without the RE leg, the BS leaks by the fee amount each quarter
    # (audit traced 6 of 7 v7 BS violations to this missing entry).
    fee = max(0.0, waiver_fee)
    return firm.evolve(
        debt_facilities=tuple(new_facilities),
        cash=firm.cash - fee,
        retained_earnings=firm.retained_earnings - fee,
    ), event


def apply_amendment(firm: FirmState, facility_id: str, covenant_type: str,
                    new_threshold: float, new_rate: float | None,
                    quarter: int) -> tuple[FirmState, CovenantViolationEvent]:
    """Amend a covenant threshold (and optionally raise rate).

    Defensive: clamp `new_rate` to [0, 1.0] per quarter (400% annual max —
    pure safety clamp against LLM unit confusion; no behavioral ceiling).
    LLMs sometimes return rate as percent (7.0 meaning 7%) rather than
    fraction; 7.0 → 1.0 is still wrong but bounded and recoverable.
    """
    new_facilities = []
    for f in firm.debt_facilities:
        if f.facility_id == facility_id:
            new_covs = []
            for cov in f.covenants:
                if cov.covenant_type == covenant_type:
                    new_covs.append(replace(cov, threshold=new_threshold,
                                             currently_violated=False,
                                             quarters_in_violation=0))
                else:
                    new_covs.append(cov)
            if new_rate is not None and new_rate > 0:
                new_rate_q = max(0.0, min(1.0, new_rate))
            else:
                new_rate_q = f.coupon_rate_quarterly
            new_facilities.append(replace(f, covenants=tuple(new_covs),
                                           status="amended",
                                           coupon_rate_quarterly=new_rate_q))
        else:
            new_facilities.append(f)
    event = CovenantViolationEvent(
        firm_id=firm.firm_id, facility_id=facility_id, covenant_type=covenant_type,
        violation_quarter=quarter, resolution="amended",
        amended_threshold=new_threshold,
        new_rate_quarterly=new_rate if new_rate else 0.0,
        resolution_quarter=quarter,
    )
    return firm.evolve(debt_facilities=tuple(new_facilities)), event


def apply_acceleration(firm: FirmState, facility_id: str, covenant_type: str,
                       quarter: int) -> tuple[FirmState, CovenantViolationEvent]:
    """Accelerate a facility: full balance becomes due immediately.

    If firm has cash, pay it off. If not, mark 'accelerated' and settlement
    phase will handle default.
    """
    new_facilities = []
    balance_due = 0.0
    for f in firm.debt_facilities:
        if f.facility_id == facility_id:
            balance_due = f.current_balance
            payoff = min(balance_due, max(0.0, firm.cash))
            new_balance = balance_due - payoff
            status = "repaid" if new_balance < 1.0 else "accelerated"
            new_facilities.append(replace(f, current_balance=new_balance, status=status))
        else:
            new_facilities.append(f)

    event = CovenantViolationEvent(
        firm_id=firm.firm_id, facility_id=facility_id, covenant_type=covenant_type,
        violation_quarter=quarter, resolution="accelerated",
        resolution_quarter=quarter,
    )
    payoff_amount = min(balance_due, max(0.0, firm.cash))
    new_facilities_t = tuple(new_facilities)
    new_ltd = _sum_non_revolver(new_facilities_t) + _non_facility_ltd(firm)
    new_rev = _sum_revolver(new_facilities_t) + _non_facility_rev(firm)
    return firm.evolve(
        debt_facilities=new_facilities_t,
        long_term_debt=new_ltd,
        revolver_balance=new_rev,
        cash=firm.cash - payoff_amount,
    ), event


# ── Convertible debt: conversion event ────────────────────────────────

def convert_facility(firm: FirmState, facility_id: str,
                     quarter: int) -> tuple[FirmState, dict]:
    """Convert a convertible bond to equity.

    Creates new shares = balance × conversion_ratio. Balance goes to 0.
    Balance sheet: long_term_debt down, common_stock + apic up by balance.
    """
    new_facilities = []
    converted_balance = 0.0
    new_shares = 0
    for f in firm.debt_facilities:
        if f.facility_id == facility_id and f.facility_type == "convertible_bond":
            converted_balance = f.current_balance
            if f.conversion_ratio > 0 and converted_balance > 0:
                # ratio is shares per $1000 face
                new_shares = int(converted_balance / 1000 * f.conversion_ratio)
            new_facilities.append(replace(f, current_balance=0.0, status="converted",
                                           is_converted=True))
        else:
            new_facilities.append(f)

    new_facilities_t = tuple(new_facilities)
    new_ltd = _sum_non_revolver(new_facilities_t) + _non_facility_ltd(firm)

    # Book the equity addition at face value (simplified; real accounting involves
    # premium allocation between debt/equity components at issuance)
    new_firm = firm.evolve(
        debt_facilities=new_facilities_t,
        long_term_debt=new_ltd,
        shares_outstanding=firm.shares_outstanding + new_shares,
        apic=firm.apic + converted_balance,
    )
    return new_firm, {
        "converted_balance": converted_balance,
        "new_shares": new_shares,
        "quarter": quarter,
    }


# ── Consistency check (runs every quarter) ───────────────────────────

def consistency_check(firm: FirmState, tol: float = 1.0) -> list[str]:
    """Return a list of invariant violations. Empty list if all good.

    Does NOT modify state. Orchestrator can log warnings or assert.
    """
    issues = []

    # 1. Sum of active non-revolver facilities should match long_term_debt
    facility_ltd = sum(f.current_balance for f in firm.debt_facilities
                       if f.facility_type != "bank_revolver"
                       and f.status in ("current", "in_cure_period", "amended", "accelerated"))
    non_facility = _non_facility_ltd(firm)
    expected_ltd = facility_ltd + non_facility
    if abs(expected_ltd - firm.long_term_debt) > tol:
        issues.append(
            f"LTD mismatch: facility_sum={facility_ltd:.2f} + non_facility={non_facility:.2f} "
            f"= {expected_ltd:.2f} vs firm.long_term_debt={firm.long_term_debt:.2f}"
        )

    # 2. Sum of revolver balances matches revolver_balance
    facility_rev = sum(f.current_balance for f in firm.debt_facilities
                       if f.facility_type == "bank_revolver"
                       and f.status in ("current", "in_cure_period", "amended", "accelerated"))
    non_facility_rev = _non_facility_rev(firm)
    expected_rev = facility_rev + non_facility_rev
    if abs(expected_rev - firm.revolver_balance) > tol:
        issues.append(
            f"Revolver mismatch: facility_sum={facility_rev:.2f} + non_facility={non_facility_rev:.2f} "
            f"= {expected_rev:.2f} vs firm.revolver_balance={firm.revolver_balance:.2f}"
        )

    # 3. No facility with negative balance
    for f in firm.debt_facilities:
        if f.current_balance < -tol:
            issues.append(f"Facility {f.facility_id} has negative balance: {f.current_balance}")

    # 4. No facility with balance > original_principal
    for f in firm.debt_facilities:
        if f.current_balance > f.original_principal + tol:
            issues.append(
                f"Facility {f.facility_id} balance {f.current_balance} "
                f"exceeds original {f.original_principal}"
            )

    # 5. Status must be valid
    for f in firm.debt_facilities:
        if f.status not in VALID_STATUS:
            issues.append(f"Facility {f.facility_id} has invalid status: {f.status}")

    # 6. Defensive drift check: facility sum must not exceed aggregate.
    # `_non_facility_ltd` / `_non_facility_rev` clamp at 0 with max(0, ...);
    # if the raw diff is negative, something has desync'd silently.
    raw_ltd_gap = firm.long_term_debt - sum(
        f.current_balance for f in firm.debt_facilities
        if f.facility_type != "bank_revolver"
        and f.status in ("current", "in_cure_period", "amended", "accelerated")
    )
    if raw_ltd_gap < -tol:
        issues.append(
            f"LTD drift: facility sum exceeds firm.long_term_debt by "
            f"{-raw_ltd_gap:.2f} (the max(0, ...) clamp would hide this)"
        )
    raw_rev_gap = firm.revolver_balance - sum(
        f.current_balance for f in firm.debt_facilities
        if f.facility_type == "bank_revolver"
        and f.status in ("current", "in_cure_period", "amended", "accelerated")
    )
    if raw_rev_gap < -tol:
        issues.append(
            f"Revolver drift: facility sum exceeds firm.revolver_balance by "
            f"{-raw_rev_gap:.2f} (the max(0, ...) clamp would hide this)"
        )

    return issues


# ── Internal helpers ──────────────────────────────────────────────────

def _sum_non_revolver(facilities: tuple[DebtFacility, ...]) -> float:
    """Sum current_balance of non-revolver facilities that are still on BS."""
    return sum(f.current_balance for f in facilities
               if f.facility_type != "bank_revolver"
               and f.status in ("current", "in_cure_period", "amended", "accelerated"))


def _sum_revolver(facilities: tuple[DebtFacility, ...]) -> float:
    """Sum current_balance of revolver facilities that are still on BS.

    Includes 'accelerated' — a revolver that was accelerated but couldn't
    be fully paid off from cash still has a liability balance that must
    stay on the BS until it's fully repaid or formally defaulted.
    """
    return sum(f.current_balance for f in facilities
               if f.facility_type == "bank_revolver"
               and f.status in ("current", "in_cure_period", "amended", "accelerated"))


def _non_facility_ltd(firm: FirmState) -> float:
    """LTD not represented by any facility (legacy lump, when toggle off).

    Computed as firm.long_term_debt minus sum of facility balances. Ensures
    backward compatibility when debt_covenants_enabled=False and firm has
    plain long_term_debt without facility detail.
    """
    facility_sum = sum(f.current_balance for f in firm.debt_facilities
                       if f.facility_type != "bank_revolver"
                       and f.status in ("current", "in_cure_period", "amended", "accelerated"))
    return max(0.0, firm.long_term_debt - facility_sum)


def _non_facility_rev(firm: FirmState) -> float:
    """Revolver balance not represented by any facility.

    Status set matches `_sum_revolver` — includes 'accelerated' so an
    unpaid accelerated revolver stays on BS until fully repaid/defaulted.
    """
    facility_sum = sum(f.current_balance for f in firm.debt_facilities
                       if f.facility_type == "bank_revolver"
                       and f.status in ("current", "in_cure_period", "amended", "accelerated"))
    return max(0.0, firm.revolver_balance - facility_sum)
