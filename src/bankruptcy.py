"""Wave ν+10 item 3: Chapter 11 vs Chapter 7 bankruptcy classification.

When a firm exhausts its cash AND credit, current code routes it to
Chapter-7-style liquidation through the distressed auction. This is
the right path for firms whose operations are not viable; it is the
wrong path for firms whose underlying business produces value but
whose capital structure has become unsustainable. Real bankruptcies
split roughly 60/40 Ch11/Ch7 by count, with most operating-business
filings entering Ch11.

This module classifies a defaulting firm at the moment of default and
returns the post-bankruptcy FirmState. The classifier is currently
deterministic and based on operating-income / cash-flow-from-operations
trends; an LLM-driven judge can be substituted via the
`classify_fn` argument when one is desired.
"""
from __future__ import annotations

from dataclasses import replace
from .types import FirmState


# Chapter 11 emerges when operations have been sustainably positive for
# this many consecutive quarters; converts to Ch7 if losses persist
# this long instead.
CH11_EMERGENCE_QUARTERS = 4
CH11_CONVERSION_QUARTERS = 8

# When entering Chapter 11, LTD is haircut by this fraction (creditors
# accept restructuring losses) and revolver is wiped. Equity is also
# wiped (founders and public shareholders get nothing under the
# absolute-priority rule). These are reasonable defaults; future work
# might calibrate them more carefully.
CH11_LTD_HAIRCUT = 0.50
CH11_REVOLVER_HAIRCUT = 1.00  # revolver fully written off in restructuring


def classify_default(firm: FirmState, ttm_operating_income: float,
                       ttm_cfo: float) -> str:
    """Decide whether a defaulting firm enters Chapter 11 or Chapter 7.

    Wave ν+11 looser rule (run-2 had zero Ch11 outcomes because both
    flows had to be positive simultaneously, which never co-occurred at
    a default trigger):

      - Pre-revenue / minimal-capability firms always go to Ch7.
      - If TTM operating income > 0 OR TTM CFO > 0 AND the firm has
        non-trivial revenue capacity AND total assets meaningfully
        exceed total liabilities ex-revolver, → Chapter 11.
      - Otherwise Chapter 7.

    The "either flow positive" rule captures firms that have positive
    operations but a single-quarter liquidity wall — the textbook Ch11
    profile. The asset-coverage gate prevents Ch11 protection of firms
    with no realistic emergence path.

    Args:
        firm: defaulting FirmState
        ttm_operating_income: trailing-four-quarter operating income (sum)
        ttm_cfo: trailing-four-quarter cash flow from operations (sum)
    """
    # Pre-revenue / minimal-capability firms always go to Ch7
    if firm.capability_stock < 5 or firm.brand_stock < 5:
        return "chapter_7"

    # Operations sign — at least one of the two trailing flows must be
    # non-trivially positive. We use "non-trivially" rather than > 0 so
    # a $1 of operating income doesn't tip a fundamentally distressed
    # firm into Ch11.
    operations_viable = (
        ttm_operating_income > 5_000_000  # > $5M TTM OI
        or ttm_cfo > 5_000_000             # > $5M TTM CFO
    )
    if not operations_viable:
        return "chapter_7"

    # Asset-coverage gate: total tangible assets must be at least 30% of
    # non-revolver liabilities. Below this ratio there is no realistic
    # path to emergence even with debt restructuring.
    tangible_assets = (
        firm.cash + firm.accounts_receivable + firm.inventory_value
        + max(0.0, firm.ppe_gross - firm.accum_depreciation)
    )
    non_revolver_liabilities = (
        firm.long_term_debt + firm.accounts_payable
        + firm.accrued_expenses + firm.deferred_tax_liability
    )
    if (non_revolver_liabilities > 0
            and tangible_assets / non_revolver_liabilities < 0.30):
        return "chapter_7"

    # Capacity check: firm must have at least 50 units of capacity.
    # Smaller firms don't have enough operating scale to support the
    # overhead of Ch11 reorganization.
    if firm.capacity_units < 50:
        return "chapter_7"

    return "chapter_11"


def enter_chapter_11(firm: FirmState) -> FirmState:
    """Apply Chapter 11 entry: LTD haircut, equity wipe, court protection.

    Returns a new FirmState with:
      - default_type = "chapter_11"
      - is_active = True (firm continues operating under court protection)
      - quarters_in_chapter_11 = 1
      - long_term_debt reduced by CH11_LTD_HAIRCUT
      - revolver_balance written off
      - cash floored at 0 (negative cash absorbed by haircut)
      - founder_shares = 0, public_shares_outstanding = 0 (old equity wiped)
      - common_stock = 0, apic = 0
      - retained_earnings = balancing residual so the BS identity holds
        (creditors' new equity stake; we simplify by parking it in RE)

    Wave ν+11: previously we zeroed retained_earnings too, leaving the BS
    structurally unbalanced (A > L + E) at every Ch11 entry. The fix
    parks the post-restructuring equity stub in RE so total_equity equals
    total_assets - total_liabilities.
    """
    cash_floored = max(0.0, firm.cash)
    new_ltd = max(0.0, firm.long_term_debt * (1.0 - CH11_LTD_HAIRCUT))
    new_revolver = max(0.0, firm.revolver_balance * (1.0 - CH11_REVOLVER_HAIRCUT))

    # Compute the post-haircut total assets and total liabilities so we
    # can park the residual in retained_earnings. We intentionally use
    # the post-evolve fields (cash_floored, new_ltd, new_revolver)
    # rather than firm.cash / firm.long_term_debt.
    new_total_assets = (
        cash_floored + firm.accounts_receivable
        - firm.allowance_for_doubtful_accounts + firm.inventory_value
        + max(0.0, firm.ppe_gross - firm.accum_depreciation) + firm.goodwill
    )
    new_total_liabilities = (
        firm.accounts_payable + firm.accrued_expenses + firm.taxes_payable
        + firm.deferred_revenue + firm.legal_reserve_balance + new_revolver
        + new_ltd + firm.deferred_tax_liability + firm.pension_liability
    )
    # Equity = Assets - Liabilities. With common_stock = apic = 0,
    # retained_earnings absorbs the entire residual.
    new_re = new_total_assets - new_total_liabilities

    return firm.evolve(
        default_type="chapter_11",
        is_active=True,
        quarters_in_chapter_11=1,
        cash=cash_floored,
        long_term_debt=new_ltd,
        revolver_balance=new_revolver,
        founder_shares=0,
        public_shares_outstanding=0,
        common_stock=0.0,
        apic=0.0,
        # Wave ν+14 bug fix: treasury_stock must also be cancelled in
        # Ch11 reorganisation. Old common stock + treasury are both
        # cancelled when new shares are issued to creditors. Without
        # this, treasury_stock retains its pre-default value and keeps
        # subtracting from equity forever — caused firm_0 in run-6 to
        # accumulate -$9.95B phantom equity destruction over 65Q.
        treasury_stock=0.0,
        retained_earnings=new_re,
    )


def enter_chapter_7(firm: FirmState) -> FirmState:
    """Apply Chapter 7 entry: is_active=False, residual cash deficit
    capitalized as additional LTD (preserves BS identity), default_type
    flag set so the auction phase knows to process this firm.

    This mirrors the legacy default-handling code at the original
    bankruptcy site; refactored here to keep the two paths symmetric
    and to make the classification explicit in state.
    """
    neg_cash = max(0.0, -firm.cash)
    return firm.evolve(
        default_type="chapter_7",
        is_active=False,
        cash=max(0.0, firm.cash),
        long_term_debt=firm.long_term_debt + neg_cash,
    )


def maybe_emerge_or_convert(
    firm: FirmState, ttm_operating_income: float, ttm_cfo: float
) -> FirmState:
    """Called each quarter for firms in Chapter 11. Decides whether to
    emerge from court protection (operations viable for several Qs),
    convert to Chapter 7 (losses persist for many Qs), or continue
    in Chapter 11.

    Returns the (possibly transitioned) FirmState.
    """
    if firm.default_type != "chapter_11":
        return firm

    # Emerge: sustained positive operations
    if (firm.quarters_in_chapter_11 >= CH11_EMERGENCE_QUARTERS
            and ttm_operating_income > 0 and ttm_cfo > 0):
        return firm.evolve(
            default_type="",
            quarters_in_chapter_11=0,
        )

    # Convert: persistent losses
    if firm.quarters_in_chapter_11 >= CH11_CONVERSION_QUARTERS:
        return firm.evolve(
            default_type="chapter_7",
            is_active=False,
            quarters_in_chapter_11=0,
        )

    # Continue: increment counter
    return firm.evolve(
        quarters_in_chapter_11=firm.quarters_in_chapter_11 + 1,
    )
