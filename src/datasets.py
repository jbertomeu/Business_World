"""
WRDS-style dataset builders.

Produces research-ready CSV datasets from simulation state, modeled on
real WRDS databases (ExecuComp, Audit Analytics, I/B/E/S, etc.).

Each function takes a WorldState and returns a list of dicts (rows).
The output_organizer calls these at end-of-run to write CSVs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .orchestrator import WorldState


# ── Column schemas (for CSV header ordering) ────────────────────────────

EXECUCOMP_COLUMNS = [
    # ExecuComp annual comp summary (one row per firm × fyear × exec).
    # Extended to track realized wealth: shares owned, shares sold, cash
    # from sales, plus the components of total comp.
    "run_id", "firm_id", "tic", "conm", "sic",
    "fyear", "datadate",
    "ceo_id", "ceo_type", "age", "tenure_years",
    "salary", "bonus",                          # cash components
    "stock_awards_value", "option_awards_value", # grant fair values
    "total_comp",                               # salary + bonus + new grant FV
    "shares_owned_eoy",                         # RSU shares currently held by CEO
    "shares_sold_this_year",                    # sold during this fyear
    "shares_sold_cumulative",                   # lifetime sold-to-date
    "cash_from_sales_cumulative",               # CEO's realized gain
    "vested_options_held", "unvested_options_held",
    "intrinsic_value_vested_options",
    "retired_flag", "fired_flag", "hired_flag",
]

# ExecuComp-style Grants of Plan-Based Awards — one row per NEW grant event.
EXECUCOMP_GRANTS_COLUMNS = [
    "run_id", "firm_id", "tic", "conm", "sic",
    "grant_id", "ceo_id",
    "grant_quarter", "grant_date",
    "grant_type",                   # rsu | stock_option
    "shares", "strike_price",
    "fair_value_at_grant",
    "vesting_schedule_json",        # JSON-encoded tuple of (offset, fraction)
    "first_vest_quarter", "last_vest_quarter",
]

# ExecuComp-style Outstanding Equity Awards — year-end snapshot per firm × fyear.
EXECUCOMP_OUTSTANDING_COLUMNS = [
    "run_id", "firm_id", "tic", "conm", "sic",
    "fyear", "datadate",
    "ceo_id", "age", "tenure_years",
    "unvested_rsu_shares", "unvested_option_shares",
    "vested_rsu_held_shares", "vested_option_shares",
    "intrinsic_value_vested_options",
    "intrinsic_value_unvested",
    "total_shares_sold_to_date", "cash_from_sales_cumulative",
    "n_grants_outstanding",
]

AUDIT_ANALYTICS_COLUMNS = [
    "run_id", "firm_id", "tic", "conm", "sic",
    "fyear", "datadate",
    "auditor_id", "auditor_name",
    "audit_opinion", "going_concern_flag", "audit_fee",
    "auditor_tenure_years", "auditor_change_flag", "prior_auditor_id",
]

RESTATEMENTS_COLUMNS = [
    "run_id", "firm_id", "tic", "conm", "sic",
    "announcement_quarter", "anndats",
    "trigger",
    "restated_start_quarter", "restated_start_date",
    "restated_end_quarter", "restated_end_date",
    "original_ni", "restated_ni", "restatement_amount",
    "sec_flag", "aaer_flag",
]

ANALYST_FORECASTS_COLUMNS = [
    "run_id", "analyst_id", "firm_id", "tic", "conm",
    "forecast_quarter", "anndats", "target_quarter", "fpedats",
    "eps_forecast", "target_price", "rating", "methodology",
    "horizon", "prior_forecast", "revision",
    "actual_eps", "forecast_error",
    # Financial statement analysis fields (new; null when analyst doesn't populate)
    "roe", "npm", "asset_turnover", "leverage", "rnoa", "nbc", "nfl",
    "quality_of_earnings", "forecast_drivers",
    "valuation_method_detail", "risks",
]

MANAGEMENT_FORECASTS_COLUMNS = [
    "run_id", "firm_id", "tic", "conm", "sic",
    "announcement_quarter", "anndats",
    "target_quarter", "fpedats",
    "eps_guidance", "revenue_guidance",
    "actual_eps", "actual_revenue", "guidance_error",
]

CEO_TURNOVER_COLUMNS = [
    "run_id", "firm_id", "tic", "conm", "sic",
    "event_quarter", "event_date", "event_type",
    "departing_ceo_id", "departing_tenure_quarters",
    "incoming_ceo_id", "reason", "severance",
]

# ── Debt datasets (Stage 3d, DealScan / Mergent FISD / Nini style) ─────────

# DealScan Facility — event-level record of each debt facility originated.
# One row per facility. (Initial record at origination; final state captured
# at run end with status + balance.)
DEBT_FACILITIES_COLUMNS = [
    "run_id", "firm_id", "tic", "conm", "sic",
    "facility_id", "facility_type",
    "origination_quarter", "origination_date",
    "maturity_quarter", "maturity_date",
    "original_principal", "current_balance",
    "coupon_rate_quarterly", "coupon_rate_annual",
    "amortization_type", "status",
    "conversion_ratio", "conversion_price", "is_converted",
]

# DealScan Covenants — event-level, linked to facility_id (many-to-one).
DEBT_COVENANTS_COLUMNS = [
    "run_id", "firm_id", "tic", "conm", "sic",
    "facility_id", "covenant_type", "threshold",
    "test_frequency", "currently_violated", "quarters_in_violation",
    "origination_quarter", "origination_date",
]

# Chava / Roberts / Nini quarterly panel — one row per firm × quarter × covenant.
COVENANT_TESTS_PANEL_COLUMNS = [
    "run_id", "firm_id", "tic", "conm", "sic",
    "quarter", "datadate",
    "facility_id", "covenant_type", "threshold",
    "measured_ratio", "violated_flag",
]

# Nini et al. violation events — one row per violation event.
COVENANT_VIOLATIONS_COLUMNS = [
    "run_id", "firm_id", "tic", "conm", "sic",
    "facility_id", "covenant_type",
    "violation_quarter", "violation_date",
    "resolution", "waiver_fee",
    "amended_threshold", "new_rate_quarterly",
    "resolution_quarter", "resolution_date",
]

# Mergent FISD — bond issuances (bond + convertible_bond subset of facilities).
BOND_ISSUANCES_COLUMNS = [
    "run_id", "firm_id", "tic", "conm", "sic",
    "facility_id", "bond_type",
    "offering_amount", "offering_quarter", "offering_date",
    "maturity_quarter", "maturity_date",
    "coupon_rate_annual",
    "is_convertible", "conversion_ratio", "conversion_price",
]

# Insider transactions (Stage 12, SEC Form 4 / WRDS Thomson Reuters style).
# One row per CEO event: grant, sell, exercise.
INSIDER_TRANSACTIONS_COLUMNS = [
    "run_id", "firm_id", "tic", "conm", "sic",
    "ceo_id", "ceo_incarnation",
    "event_quarter", "event_date", "event_type",
    "transaction_shares", "transaction_price", "strike_price",
    "transaction_value", "shares_held_after", "notes",
]

# Activist investor campaigns (Stage 12).
# One row per campaign event: activist proposes, firm responds.
ACTIVIST_CAMPAIGNS_COLUMNS = [
    "run_id", "firm_id", "tic", "conm", "sic",
    "event_quarter", "event_date",
    "activist_id",                # "activist_1" etc.
    "demand_type",                # buyback | divestiture | strategic_review | board_seat | other
    "demand_specifics",           # short description
    "stake_pct_implied",          # activist's claimed ownership (0-1)
    "firm_response",              # accept | reject | negotiate | partial
    "firm_rationale",             # short text
]

# Bad-debt events panel (Stage 5) — one row per firm × quarter
BAD_DEBT_EVENTS_COLUMNS = [
    "run_id", "firm_id", "tic", "conm", "sic",
    "quarter", "datadate",
    "gross_ar", "allowance", "net_ar",
    "bad_debt_expense", "write_offs", "allowance_pct_of_ar",
]

# Compustat annual fundamentals (mirrors WRDS `comp.funda`).
# One row per firm × fiscal year. Aggregates quarterly compustat rows:
# IS / CF lines = SUM across the year's 4 quarters; BS lines = year-end snapshot.
# Column names use Compustat funda conventions (no "q" suffix; e.g. sale not saleq).
COMPUSTAT_A_COLUMNS = [
    # Identifiers / format flags (mirror funda)
    "run_id", "firm_id", "tic", "conm", "sic",
    "fyear", "datadate",
    "indfmt", "consol", "popsrc", "datafmt",  # Compustat metadata: INDL/C/D/STD
    # Income statement (annual sum)
    "sale", "cogs", "gp", "xrd", "xsga", "dp",
    "oiadp", "xint", "rcp", "pi", "txt", "ni",
    # Balance sheet (year-end snapshot)
    "che", "rect", "invt", "ppent", "ppegt",
    "at", "ap", "lct", "drc", "dlc", "dltt", "lt",
    "cstk", "apic", "ceq", "re", "tstk",
    "csho", "mkvalt",
    # Cash flow (annual sum)
    "oancf", "ivncf", "fincf", "capx", "sppe",
    # Equity / payout (annual sum)
    "sstk", "prstkc", "dv",
    # Market (year-end)
    "prcc_f",
    # Custom: BDE / write-offs (annual sum) + allowance year-end
    "bad_debt_expense_a", "write_offs_a", "allowance_dca",
    # Stage 12: spi (special items), pension, DTL
    "spi", "pension_expense_a", "pension_liability_eoy",
    "legal_reserve_bs_eoy", "txditc",
]

# Annual reports (10-K-style) — one row per firm × fiscal year
ANNUAL_REPORTS_COLUMNS = [
    "run_id", "firm_id", "tic", "conm", "sic", "fyear", "datadate",
    "annual_revenue", "annual_cogs", "annual_gross_profit",
    "annual_rd", "annual_sga", "annual_depreciation",
    "annual_operating_income", "annual_interest_expense",
    "annual_pretax_income", "annual_tax",
    "annual_net_income", "annual_eps",
    "annual_cfo", "annual_cfi", "annual_cff", "annual_capex",
    "year_end_cash", "year_end_total_assets", "year_end_total_liabilities",
    "year_end_total_equity", "year_end_long_term_debt",
    "year_end_revolver_balance", "year_end_shares_outstanding",
    "year_end_share_price",
    "yoy_revenue_growth", "yoy_ni_growth",
    "equity_issued_during_year", "debt_issued_during_year",
    "dividends_paid", "buybacks",
    "audit_opinion", "going_concern_flag", "covenant_violations_count",
    "forward_guidance_revenue", "forward_guidance_eps",
    "mda_summary",  # last column (long text)
]


def build_execucomp(state: WorldState) -> list[dict]:
    """Build ExecuComp-style CEO annual comp summary.

    One row per firm × fiscal year, sourced from `state.execucomp_annual_snapshots`.
    Snapshots are captured (a) pre-governance for ALL firms with grants
    (so defaulted firms appear) and (b) post-governance for firms that
    went through the LLM review path (overrides the pre-gov snapshot).
    Dedup keeps the LAST snapshot per (firm, fyear).
    """
    from .wrds_identifiers import identifiers_for_firm, datadate_for
    by_key: dict = {}
    for snap in state.execucomp_annual_snapshots:
        by_key[(snap["firm_id"], snap["fyear"])] = snap
    rows = []
    for snap in by_key.values():
        fid = snap["firm_id"]
        ids = identifiers_for_firm(fid)
        total = (snap["base_salary"] + snap["cash_bonus_this_year"]
                 + snap["stock_awards_value"] + snap["option_awards_value"])
        rows.append({
            "run_id": state.run_id,
            "firm_id": fid,
            "tic": ids["tic"],
            "conm": ids["conm"],
            "sic": ids["sic"],
            "fyear": snap["fyear"],
            "datadate": datadate_for(snap["fyear"], 4),
            "ceo_id": snap["ceo_id"] or "unknown",
            "ceo_type": snap["ceo_id"] or "unknown",
            "age": snap["age"],
            "tenure_years": snap["tenure_years"],
            "salary": snap["base_salary"],
            "bonus": snap["cash_bonus_this_year"],
            "stock_awards_value": snap["stock_awards_value"],
            "option_awards_value": snap["option_awards_value"],
            "total_comp": total,
            "shares_owned_eoy": snap["shares_owned_eoy"],
            "shares_sold_this_year": snap["shares_sold_this_year"],
            "shares_sold_cumulative": snap["shares_sold_cumulative"],
            "cash_from_sales_cumulative": snap["cash_from_sales_cumulative"],
            "vested_options_held": snap["vested_options_held"],
            "unvested_options_held": snap["unvested_options_held"],
            "intrinsic_value_vested_options": snap["intrinsic_value_vested_options"],
            "retired_flag": snap["retired_flag"],
            "fired_flag": snap["fired_flag"],
            "hired_flag": snap["hired_flag"],
        })
    return rows


def build_execucomp_grants(state: WorldState) -> list[dict]:
    """ExecuComp-style Grants of Plan-Based Awards.

    One row per NEW grant event (from `state.ceo_grant_events`). Captures
    grant date, type (RSU/option), shares, strike, fair value at grant,
    vesting schedule, and derived first/last vest quarters.
    """
    from .wrds_identifiers import identifiers_for_firm, abs_quarter_to_datadate
    import json

    rows = []
    for g in state.ceo_grant_events:
        ids = identifiers_for_firm(g.firm_id)
        vesting = list(g.vesting_schedule) if g.vesting_schedule else []
        vest_offsets = [v[0] for v in vesting] if vesting else [0]
        first_vest_q = g.grant_quarter + min(vest_offsets)
        last_vest_q = g.grant_quarter + max(vest_offsets)
        rows.append({
            "run_id": state.run_id,
            "firm_id": g.firm_id,
            "tic": ids["tic"],
            "conm": ids["conm"],
            "sic": ids["sic"],
            "grant_id": g.grant_id,
            "ceo_id": g.ceo_id,
            "grant_quarter": g.grant_quarter,
            "grant_date": abs_quarter_to_datadate(g.grant_quarter),
            "grant_type": g.grant_type,
            "shares": g.shares,
            "strike_price": g.strike_price,
            "fair_value_at_grant": g.fair_value_at_grant,
            "vesting_schedule_json": json.dumps(vesting),
            "first_vest_quarter": first_vest_q,
            "last_vest_quarter": last_vest_q,
        })
    return rows


def build_execucomp_outstanding(state: WorldState) -> list[dict]:
    """ExecuComp-style Outstanding Equity Awards — annual panel.

    One row per firm × fiscal year, sourced from
    `state.execucomp_annual_snapshots` (captured at end of Q4 governance,
    plus a pre-governance fallback so defaulted firms appear too). When
    multiple snapshots exist for the same (firm, fyear) — e.g. pre-gov
    plus post-gov — keep the LAST one (most recent / post-decision).
    """
    from .wrds_identifiers import identifiers_for_firm, datadate_for
    # Dedup by (firm_id, fyear), preserving the LAST snapshot in append order.
    by_key: dict = {}
    for snap in state.execucomp_annual_snapshots:
        key = (snap["firm_id"], snap["fyear"])
        by_key[key] = snap
    rows = []
    for snap in by_key.values():
        fid = snap["firm_id"]
        ids = identifiers_for_firm(fid)
        rows.append({
            "run_id": state.run_id,
            "firm_id": fid,
            "tic": ids["tic"],
            "conm": ids["conm"],
            "sic": ids["sic"],
            "fyear": snap["fyear"],
            "datadate": datadate_for(snap["fyear"], 4),
            "ceo_id": snap["ceo_id"] or "unknown",
            "age": snap["age"],
            "tenure_years": snap["tenure_years"],
            "unvested_rsu_shares": snap["unvested_rsu_shares"],
            "unvested_option_shares": snap["unvested_option_shares"],
            "vested_rsu_held_shares": snap["vested_rsu_held_shares"],
            "vested_option_shares": snap["vested_option_shares"],
            "intrinsic_value_vested_options": snap["intrinsic_value_vested_options"],
            "intrinsic_value_unvested": snap["intrinsic_value_unvested"],
            "total_shares_sold_to_date": snap["shares_sold_cumulative"],
            "cash_from_sales_cumulative": snap["cash_from_sales_cumulative"],
            "n_grants_outstanding": snap["n_grants_outstanding"],
        })
    return rows


def build_audit_analytics(state: WorldState) -> list[dict]:
    """Build Audit Analytics-style dataset.

    One row per firm-year audit. Looks up auditor_name from the canonical
    AUDITOR_NAMES dict. Tracks auditor changes and going-concern flags.
    """
    from .auditor import AUDITOR_NAMES
    from .wrds_identifiers import identifiers_for_firm, datadate_for

    # Track prior auditor per firm to detect changes
    prior_auditor: dict[str, str] = {}
    # Track auditor tenure per (firm, auditor) pair
    tenure: dict[tuple[str, str], int] = {}

    rows = []
    # Sort by fiscal year so tenure accumulates correctly
    results = sorted(state.audit_results, key=lambda r: (r.firm_id, r.fiscal_year))
    for result in results:
        fid = result.firm_id
        prior = prior_auditor.get(fid, "")
        changed = 1 if prior and prior != result.auditor_id else 0

        tkey = (fid, result.auditor_id)
        tenure[tkey] = tenure.get(tkey, 0) + 1

        # Going-concern flag: auditor says so, OR adverse opinion, OR firm defaulted
        firm = state.firms.get(fid)
        firm_defaulted = bool(firm and not firm.is_active)
        auditor_flagged = bool(getattr(result, "going_concern", False))
        going_concern = 1 if (auditor_flagged
                              or result.opinion == "adverse"
                              or firm_defaulted) else 0

        ids = identifiers_for_firm(fid)
        rows.append({
            "run_id": state.run_id,
            "firm_id": fid,
            "tic": ids["tic"],
            "conm": ids["conm"],
            "sic": ids["sic"],
            "fyear": result.fiscal_year,
            "datadate": datadate_for(result.fiscal_year, 4),
            "auditor_id": result.auditor_id,
            "auditor_name": AUDITOR_NAMES.get(result.auditor_id, result.auditor_id),
            "audit_opinion": result.opinion,
            "going_concern_flag": going_concern,
            "audit_fee": result.fee,
            "auditor_tenure_years": tenure[tkey],
            "auditor_change_flag": changed,
            "prior_auditor_id": prior if changed else "",
        })
        prior_auditor[fid] = result.auditor_id
    return rows


def build_restatements(state: WorldState) -> list[dict]:
    """Build restatements dataset from state.restatement_events."""
    from .wrds_identifiers import identifiers_for_firm, abs_quarter_to_datadate

    rows = []
    for event in getattr(state, "restatement_events", []) or []:
        fid = event.get("firm_id", "")
        ids = identifiers_for_firm(fid)
        ann_q = event.get("announcement_quarter", 0)
        start_q = event.get("restated_start_quarter", ann_q)
        end_q = event.get("restated_end_quarter", ann_q)
        rows.append({
            "run_id": state.run_id,
            "firm_id": fid,
            "tic": ids["tic"],
            "conm": ids["conm"],
            "sic": ids["sic"],
            "announcement_quarter": ann_q,
            "anndats": abs_quarter_to_datadate(ann_q) if ann_q else "",
            "trigger": event.get("trigger", ""),
            "restated_start_quarter": start_q,
            "restated_start_date": abs_quarter_to_datadate(start_q) if start_q else "",
            "restated_end_quarter": end_q,
            "restated_end_date": abs_quarter_to_datadate(end_q) if end_q else "",
            "original_ni": event.get("original_ni", 0.0),
            "restated_ni": event.get("restated_ni", 0.0),
            "restatement_amount": event.get("restatement_amount", 0.0),
            "sec_flag": event.get("sec_flag", 0),
            "aaer_flag": event.get("aaer_flag", 0),
        })
    return rows


def build_analyst_forecasts(state: WorldState) -> list[dict]:
    """Build I/B/E/S-style analyst forecast dataset.

    One row per (analyst, firm, forecast_quarter) pair. Each row includes:
    - The forecast itself (eps_forecast_1q for the next quarter)
    - Prior forecast from same analyst-firm (if any)
    - Revision (current - prior)
    - Actual EPS from Compustat (backfilled when target_quarter is in the panel)
    - Forecast error (actual - forecast)
    """
    from .wrds_identifiers import identifiers_for_firm, abs_quarter_to_datadate
    # Index Compustat actuals: (firm_id, (fyearq, fqtr)) -> eps (niq / shares_outstanding)
    # shares_outstanding not in CompustatRow directly — use cshoq * 1e6
    actuals: dict[tuple[str, tuple[int, int]], float] = {}
    for r in state.compustat_rows:
        shares = r.cshoq * 1_000_000 if r.cshoq else 0
        if shares > 0:
            eps = r.niq / shares
            actuals[(r.firm_id, (r.fyearq, r.fqtr))] = eps

    def q_to_fy_fq(q: int) -> tuple[int, int]:
        """Map absolute quarter number (1-based) to (fyearq, fqtr)."""
        return (2031 + (q - 1) // 4, ((q - 1) % 4) + 1)

    # Track prior forecast per (analyst_id, firm_id) by date order
    by_pair: dict[tuple[str, str], list] = {}
    for note in sorted(state.analyst_notes, key=lambda n: n.quarter):
        by_pair.setdefault((note.analyst_id, note.firm_id), []).append(note)

    rows = []
    for note in state.analyst_notes:
        pair = (note.analyst_id, note.firm_id)
        history = by_pair[pair]
        # Find prior forecast (immediately preceding this one)
        prior = 0.0
        for h in history:
            if h.quarter < note.quarter:
                prior = h.eps_forecast_1q
            else:
                break
        revision = note.eps_forecast_1q - prior if prior != 0 else 0.0

        target_q = note.quarter + 1
        target_fyfq = q_to_fy_fq(target_q)
        actual = actuals.get((note.firm_id, target_fyfq), 0.0)
        error = actual - note.eps_forecast_1q if actual != 0 else 0.0

        ids = identifiers_for_firm(note.firm_id)
        rows.append({
            "run_id": state.run_id,
            "analyst_id": note.analyst_id,
            "firm_id": note.firm_id,
            "tic": ids["tic"],
            "conm": ids["conm"],
            "forecast_quarter": note.quarter,
            "anndats": abs_quarter_to_datadate(note.quarter),
            "target_quarter": target_q,
            "fpedats": abs_quarter_to_datadate(target_q),
            "eps_forecast": note.eps_forecast_1q,
            "target_price": note.target_price,
            "rating": note.rating,
            "methodology": note.methodology,
            "horizon": "1Q",
            "prior_forecast": prior,
            "revision": revision,
            "actual_eps": actual,
            "forecast_error": error,
            "roe": note.roe,
            "npm": note.npm,
            "asset_turnover": note.asset_turnover,
            "leverage": note.leverage,
            "rnoa": note.rnoa,
            "nbc": note.nbc,
            "nfl": note.nfl,
            "quality_of_earnings": note.quality_of_earnings,
            "forecast_drivers": note.forecast_drivers,
            "valuation_method_detail": note.valuation_method_detail,
            "risks": note.risks,
        })
    return rows


def build_management_forecasts(state: WorldState) -> list[dict]:
    """Build management guidance dataset (First Call Guidance style).

    One row per firm-quarter guidance issuance. Backfills actuals from
    Compustat so guidance_error can be computed.
    """
    from .wrds_identifiers import identifiers_for_firm, abs_quarter_to_datadate
    # Index Compustat by (firm_id, absolute quarter) for actuals lookup
    actuals_eps: dict[tuple[str, int], float] = {}
    actuals_rev: dict[tuple[str, int], float] = {}
    for r in state.compustat_rows:
        # Absolute quarter from (fyearq, fqtr) where fyearq=2031 is Q1-4
        abs_q = (r.fyearq - 2031) * 4 + r.fqtr
        shares = r.cshoq * 1_000_000 if r.cshoq else 0
        if shares > 0:
            actuals_eps[(r.firm_id, abs_q)] = r.niq / shares
        actuals_rev[(r.firm_id, abs_q)] = r.saleq

    def _num(v):
        """Defensive coercion in case older stored releases have string fields."""
        if isinstance(v, (int, float)):
            return float(v)
        try:
            return float(str(v).replace("$", "").replace(",", ""))
        except (ValueError, TypeError):
            return 0.0

    rows = []
    for release in state.earnings_releases:
        target_q = release.quarter + 1
        actual_eps = actuals_eps.get((release.firm_id, target_q), 0.0)
        actual_rev = actuals_rev.get((release.firm_id, target_q), 0.0)
        guidance_eps = _num(release.guidance_eps_1q)
        guidance_rev = _num(release.guidance_revenue_1q)
        eps_err = actual_eps - guidance_eps if actual_eps else 0.0

        ids = identifiers_for_firm(release.firm_id)
        rows.append({
            "run_id": state.run_id,
            "firm_id": release.firm_id,
            "tic": ids["tic"],
            "conm": ids["conm"],
            "sic": ids["sic"],
            "announcement_quarter": release.quarter,
            "anndats": abs_quarter_to_datadate(release.quarter),
            "target_quarter": target_q,
            "fpedats": abs_quarter_to_datadate(target_q),
            "eps_guidance": guidance_eps,
            "revenue_guidance": guidance_rev,
            "actual_eps": actual_eps,
            "actual_revenue": actual_rev,
            "guidance_error": eps_err,
        })
    return rows


def build_ceo_turnover(state: WorldState) -> list[dict]:
    """Build CEO turnover dataset.

    Derived from governance events in state.ceo_history. Only emits rows
    for actual transitions (fired/hired/resigned), not annual "reviewed"
    events (those are captured in execucomp).
    """
    from .wrds_identifiers import identifiers_for_firm, abs_quarter_to_datadate

    rows = []
    for fid, events in state.ceo_history.items():
        ids = identifiers_for_firm(fid)
        for ev in events:
            if ev.get("event_type") not in ("fired", "hired", "resigned"):
                continue
            rows.append({
                "run_id": state.run_id,
                "firm_id": fid,
                "tic": ids["tic"],
                "conm": ids["conm"],
                "sic": ids["sic"],
                "event_quarter": ev.get("event_quarter", 0),
                "event_date": abs_quarter_to_datadate(ev.get("event_quarter", 1)),
                "event_type": ev.get("event_type", ""),
                "departing_ceo_id": ev.get("departing_ceo_id", ""),
                "departing_tenure_quarters": ev.get("departing_tenure_quarters", 0),
                "incoming_ceo_id": ev.get("incoming_ceo_id", ""),
                "reason": ev.get("reason", ""),
                "severance": ev.get("severance", 0.0),
            })
    return rows


# ── Debt dataset builders (Stage 3d) ───────────────────────────────────────

def _iter_facilities(state: WorldState):
    """Yield (firm_id, DebtFacility) pairs for every facility across all firms.

    Includes repaid/defaulted/converted (historical record; not just active)."""
    for fid, firm in state.firms.items():
        for fac in firm.debt_facilities:
            yield fid, fac


def build_debt_facilities(state: WorldState) -> list[dict]:
    """DealScan-style facility record. One row per facility, capturing final
    (end-of-run) state — status, balance, etc."""
    from .wrds_identifiers import identifiers_for_firm, abs_quarter_to_datadate
    rows = []
    for fid, fac in _iter_facilities(state):
        ids = identifiers_for_firm(fid)
        rows.append({
            "run_id": state.run_id,
            "firm_id": fid,
            "tic": ids["tic"],
            "conm": ids["conm"],
            "sic": ids["sic"],
            "facility_id": fac.facility_id,
            "facility_type": fac.facility_type,
            "origination_quarter": fac.origination_quarter,
            "origination_date": abs_quarter_to_datadate(fac.origination_quarter),
            "maturity_quarter": fac.maturity_quarter,
            "maturity_date": abs_quarter_to_datadate(fac.maturity_quarter),
            "original_principal": fac.original_principal,
            "current_balance": fac.current_balance,
            "coupon_rate_quarterly": fac.coupon_rate_quarterly,
            "coupon_rate_annual": fac.coupon_rate_quarterly * 4,
            "amortization_type": fac.amortization_type,
            "status": fac.status,
            "conversion_ratio": fac.conversion_ratio,
            "conversion_price": fac.conversion_price,
            "is_converted": int(fac.is_converted),
        })
    return rows


def build_debt_covenants(state: WorldState) -> list[dict]:
    """DealScan covenant record. One row per (facility, covenant) pair."""
    from .wrds_identifiers import identifiers_for_firm, abs_quarter_to_datadate
    rows = []
    for fid, fac in _iter_facilities(state):
        ids = identifiers_for_firm(fid)
        for cov in fac.covenants:
            rows.append({
                "run_id": state.run_id,
                "firm_id": fid,
                "tic": ids["tic"],
                "conm": ids["conm"],
                "sic": ids["sic"],
                "facility_id": fac.facility_id,
                "covenant_type": cov.covenant_type,
                "threshold": cov.threshold,
                "test_frequency": cov.test_frequency,
                "currently_violated": int(cov.currently_violated),
                "quarters_in_violation": cov.quarters_in_violation,
                "origination_quarter": fac.origination_quarter,
                "origination_date": abs_quarter_to_datadate(fac.origination_quarter),
            })
    return rows


def build_covenant_tests_panel(state: WorldState) -> list[dict]:
    """Chava/Roberts/Nini-style quarterly panel of covenant tests.

    Reconstructs a quarterly measurement for each covenant by re-running
    compute_ratios against each firm's compustat history. This gives a
    per-firm × per-quarter × per-covenant panel of measured values."""
    from .wrds_identifiers import identifiers_for_firm, abs_quarter_to_datadate
    from .debt_management import compute_ratios, _ratio_for_covenant, _is_violated

    # Pre-index compustat by (firm_id, abs_q)
    comp_by_fid: dict[str, list] = {}
    for r in state.compustat_rows:
        comp_by_fid.setdefault(r.firm_id, []).append(r)
    for fid in comp_by_fid:
        comp_by_fid[fid].sort(key=lambda r: (r.fyearq, r.fqtr))

    rows = []
    for fid, firm in state.firms.items():
        if not firm.debt_facilities:
            continue
        ids = identifiers_for_firm(fid)
        firm_rows = comp_by_fid.get(fid, [])
        # For each quarter where we have compustat, compute TTM EBITDA + interest
        # and test each covenant on each facility that existed at that quarter.
        for i, crow in enumerate(firm_rows):
            abs_q = (crow.fyearq - 2031) * 4 + crow.fqtr
            # TTM using last 4 rows ending at this quarter
            window = firm_rows[max(0, i-3): i+1]
            ttm_ebitda = sum((r.niq or 0) + (r.xintq or 0) + (r.dpq or 0)
                             for r in window)
            ttm_interest = sum((r.xintq or 0) for r in window)
            # For each facility active at this quarter, test covenants
            for fac in firm.debt_facilities:
                if fac.origination_quarter > abs_q:
                    continue
                if fac.maturity_quarter < abs_q:
                    continue
                # Use a synthetic firm state with the snapshot balances to test
                # (approximation: we use current firm state's covenants since they
                # don't change quarter-to-quarter unless amended).
                ratios = compute_ratios(firm, ttm_ebitda, ttm_interest)
                for cov in fac.covenants:
                    if cov.test_frequency != "quarterly":
                        continue
                    measured = _ratio_for_covenant(cov.covenant_type, ratios)
                    if measured is None:
                        continue
                    violated = _is_violated(cov.covenant_type, measured, cov.threshold)
                    rows.append({
                        "run_id": state.run_id,
                        "firm_id": fid,
                        "tic": ids["tic"],
                        "conm": ids["conm"],
                        "sic": ids["sic"],
                        "quarter": abs_q,
                        "datadate": abs_quarter_to_datadate(abs_q),
                        "facility_id": fac.facility_id,
                        "covenant_type": cov.covenant_type,
                        "threshold": cov.threshold,
                        "measured_ratio": measured,
                        "violated_flag": int(violated),
                    })
    return rows


def build_covenant_violations(state: WorldState) -> list[dict]:
    """Nini et al. style violation events. One row per recorded violation event
    in each firm's covenant_violation_history."""
    from .wrds_identifiers import identifiers_for_firm, abs_quarter_to_datadate
    rows = []
    for fid, firm in state.firms.items():
        ids = identifiers_for_firm(fid)
        for ev in firm.covenant_violation_history:
            rows.append({
                "run_id": state.run_id,
                "firm_id": fid,
                "tic": ids["tic"],
                "conm": ids["conm"],
                "sic": ids["sic"],
                "facility_id": ev.facility_id,
                "covenant_type": ev.covenant_type,
                "violation_quarter": ev.violation_quarter,
                "violation_date": abs_quarter_to_datadate(ev.violation_quarter),
                "resolution": ev.resolution,
                "waiver_fee": ev.waiver_fee,
                "amended_threshold": ev.amended_threshold,
                "new_rate_quarterly": ev.new_rate_quarterly,
                "resolution_quarter": ev.resolution_quarter,
                "resolution_date": abs_quarter_to_datadate(ev.resolution_quarter),
            })
    return rows


def build_bad_debt_events(state: WorldState) -> list[dict]:
    """Stage 5 bad-debt panel: one row per firm × quarter summarizing
    gross AR, allowance, net AR, bad_debt_expense, and write_offs.
    Source is state.compustat_rows — where the columns now carry
    allowance_dca, bad_debt_expense, write_offs (from accounting module)."""
    from .wrds_identifiers import identifiers_for_firm, abs_quarter_to_datadate
    rows = []
    for cr in state.compustat_rows:
        ids = identifiers_for_firm(cr.firm_id)
        abs_q = (cr.fyearq - 2031) * 4 + cr.fqtr
        gross_ar = cr.rectq or 0
        allow = cr.allowance_dca or 0
        net_ar = max(0.0, gross_ar - allow)
        rows.append({
            "run_id": state.run_id,
            "firm_id": cr.firm_id,
            "tic": ids["tic"],
            "conm": ids["conm"],
            "sic": ids["sic"],
            "quarter": abs_q,
            "datadate": cr.datadate or abs_quarter_to_datadate(abs_q),
            "gross_ar": gross_ar,
            "allowance": allow,
            "net_ar": net_ar,
            "bad_debt_expense": cr.bad_debt_expense or 0,
            "write_offs": cr.write_offs or 0,
            "allowance_pct_of_ar": (allow / gross_ar) if gross_ar > 0 else 0,
        })
    return rows


def build_compustat_a(state: WorldState) -> list[dict]:
    """Compustat funda-style annual fundamentals (one row per firm × fyear).

    Aggregates quarterly compustat rows:
      - IS / CF lines: SUM across the 4 quarters in the fyear
      - BS / market lines: year-end (last quarter's) snapshot
      - Identifiers carried from the year-end row

    Mirrors WRDS `comp.funda`. Schema metadata (indfmt, consol, popsrc,
    datafmt) hardcoded to industrial / consolidated / domestic / standard
    — the standard funda combination — matching how research code typically
    filters (`indfmt='INDL' and consol='C' and popsrc='D' and datafmt='STD'`).
    """
    from .wrds_identifiers import identifiers_for_firm

    # Group quarterly rows by (firm_id, fyear)
    by_key: dict[tuple[str, int], list] = {}
    for r in state.compustat_rows:
        by_key.setdefault((r.firm_id, r.fyearq), []).append(r)

    rows = []
    for (fid, fyear), q_rows in sorted(by_key.items()):
        if not q_rows:
            continue
        # Sort by fqtr so year-end snapshot uses the last fiscal quarter
        q_rows.sort(key=lambda r: r.fqtr)
        last = q_rows[-1]
        ids = identifiers_for_firm(fid)
        year_end_date = f"{fyear}-12-31"

        # IS / CF: sum across quarters
        annual_sale = sum(r.saleq for r in q_rows)
        annual_cogs = sum(r.cogsq for r in q_rows)
        annual_gp = sum(r.gpq for r in q_rows)
        annual_xrd = sum(r.xrdq for r in q_rows)
        annual_xsga = sum(r.xsgaq for r in q_rows)
        annual_dp = sum(r.dpq for r in q_rows)
        annual_oiadp = sum(r.oiadpq for r in q_rows)
        annual_xint = sum(r.xintq for r in q_rows)
        annual_rcp = sum(getattr(r, "rcpq", 0) or 0 for r in q_rows)
        annual_pi = sum(r.piq for r in q_rows)
        annual_txt = sum(r.txtq for r in q_rows)
        annual_ni = sum(r.niq for r in q_rows)
        annual_oancf = sum(r.oancfq for r in q_rows)
        annual_ivncf = sum(r.ivncfq for r in q_rows)
        annual_fincf = sum(r.fincfq for r in q_rows)
        annual_capx = sum(r.capxq for r in q_rows)
        annual_sppe = sum(getattr(r, "ppe_disposal_proceeds", 0) or 0 for r in q_rows)
        annual_sstk = sum(r.sstkq for r in q_rows)
        annual_prstkc = sum(r.prstkq for r in q_rows)
        annual_dv = sum(r.dvq for r in q_rows)
        annual_bad_debt = sum(getattr(r, "bad_debt_expense", 0) or 0 for r in q_rows)
        annual_write_offs = sum(getattr(r, "write_offs", 0) or 0 for r in q_rows)
        annual_spi = sum(getattr(r, "spioq", 0) or 0 for r in q_rows)
        annual_pension = sum(getattr(r, "pension_service_cost", 0) or 0 for r in q_rows)

        rows.append({
            # Identifiers
            "run_id": state.run_id,
            "firm_id": fid,
            "tic": ids["tic"],
            "conm": ids["conm"],
            "sic": ids["sic"],
            "fyear": fyear,
            "datadate": year_end_date,
            # Funda metadata (constants for this sim — pure industrial firms)
            "indfmt": "INDL",
            "consol": "C",
            "popsrc": "D",
            "datafmt": "STD",
            # Income statement
            "sale": annual_sale,
            "cogs": annual_cogs,
            "gp": annual_gp,
            "xrd": annual_xrd,
            "xsga": annual_xsga,
            "dp": annual_dp,
            "oiadp": annual_oiadp,
            "xint": annual_xint,
            "rcp": annual_rcp,
            "pi": annual_pi,
            "txt": annual_txt,
            "ni": annual_ni,
            # Balance sheet (year-end snapshot)
            "che": last.cheq,
            "rect": last.rectq,
            "invt": last.invtq,
            "ppent": last.ppentq,
            "ppegt": last.ppentq,  # we don't carry ppegt separately on quarterly rows; use ppent as proxy
            "at": last.atq,
            "ap": last.apq,
            "lct": last.lctq,
            "drc": getattr(last, "drcq", 0.0),
            "dlc": last.dlcq,
            "dltt": last.dlttq,
            "lt": last.ltq,
            "cstk": last.cstkq,
            "apic": last.apicq,
            "ceq": last.ceqq,
            "re": last.req,
            "tstk": last.tstkq,
            "csho": last.cshoq,
            "mkvalt": last.mkvaltq,
            # Cash flow
            "oancf": annual_oancf,
            "ivncf": annual_ivncf,
            "fincf": annual_fincf,
            "capx": annual_capx,
            "sppe": annual_sppe,   # Sale of PP&E (WRDS funda convention)
            # Equity / payout
            "sstk": annual_sstk,
            "prstkc": annual_prstkc,
            "dv": annual_dv,
            # Market (year-end)
            "prcc_f": last.prccq,
            # Custom Stage 5 fields
            "bad_debt_expense_a": annual_bad_debt,
            "write_offs_a": annual_write_offs,
            "allowance_dca": getattr(last, "allowance_dca", 0.0),
            "spi": annual_spi,
            "pension_expense_a": annual_pension,
            "pension_liability_eoy": getattr(last, "pension_liability_bs", 0.0),
            "legal_reserve_bs_eoy": getattr(last, "legal_reserve_bs", 0.0),
            "txditc": getattr(last, "txditcq", 0.0),
        })
    return rows


def build_annual_reports(state: WorldState) -> list[dict]:
    """Annual report rows. One row per firm × fiscal year."""
    from .wrds_identifiers import identifiers_for_firm
    rows = []
    for r in state.annual_reports:
        ids = identifiers_for_firm(r.firm_id)
        # year-end Q4 datadate
        year_end_date = f"{r.fyear}-12-31"
        rows.append({
            "run_id": state.run_id,
            "firm_id": r.firm_id,
            "tic": ids["tic"],
            "conm": ids["conm"],
            "sic": ids["sic"],
            "fyear": r.fyear,
            "datadate": year_end_date,
            "annual_revenue": r.annual_revenue,
            "annual_cogs": r.annual_cogs,
            "annual_gross_profit": r.annual_gross_profit,
            "annual_rd": r.annual_rd,
            "annual_sga": r.annual_sga,
            "annual_depreciation": r.annual_depreciation,
            "annual_operating_income": r.annual_operating_income,
            "annual_interest_expense": r.annual_interest_expense,
            "annual_pretax_income": r.annual_pretax_income,
            "annual_tax": r.annual_tax,
            "annual_net_income": r.annual_net_income,
            "annual_eps": r.annual_eps,
            "annual_cfo": r.annual_cfo,
            "annual_cfi": r.annual_cfi,
            "annual_cff": r.annual_cff,
            "annual_capex": r.annual_capex,
            "year_end_cash": r.year_end_cash,
            "year_end_total_assets": r.year_end_total_assets,
            "year_end_total_liabilities": r.year_end_total_liabilities,
            "year_end_total_equity": r.year_end_total_equity,
            "year_end_long_term_debt": r.year_end_long_term_debt,
            "year_end_revolver_balance": r.year_end_revolver_balance,
            "year_end_shares_outstanding": r.year_end_shares_outstanding,
            "year_end_share_price": r.year_end_share_price,
            "yoy_revenue_growth": r.yoy_revenue_growth,
            "yoy_ni_growth": r.yoy_ni_growth,
            "equity_issued_during_year": r.equity_issued_during_year,
            "debt_issued_during_year": r.debt_issued_during_year,
            "dividends_paid": r.dividends_paid,
            "buybacks": r.buybacks,
            "audit_opinion": r.audit_opinion,
            "going_concern_flag": int(r.going_concern_flag),
            "covenant_violations_count": r.covenant_violations_count,
            "forward_guidance_revenue": r.forward_guidance_revenue,
            "forward_guidance_eps": r.forward_guidance_eps,
            "mda_summary": r.mda_summary,
        })
    return rows


def build_insider_transactions(state: WorldState) -> list[dict]:
    """Stage 12: SEC Form 4-style insider transaction events.

    One row per event from `state.insider_events` (grants, sells, exercises
    — recorded as they happen by the orchestrator). Mirrors the WRDS
    Thomson Reuters Insider Filings granularity.
    """
    from .wrds_identifiers import identifiers_for_firm
    rows = []
    for ev in state.insider_events:
        ids = identifiers_for_firm(ev.firm_id)
        rows.append({
            "run_id": ev.run_id,
            "firm_id": ev.firm_id,
            "tic": ids["tic"],
            "conm": ids["conm"],
            "sic": ids["sic"],
            "ceo_id": ev.ceo_id,
            "ceo_incarnation": ev.ceo_incarnation,
            "event_quarter": ev.event_quarter,
            "event_date": ev.event_date,
            "event_type": ev.event_type,
            "transaction_shares": ev.transaction_shares,
            "transaction_price": ev.transaction_price,
            "strike_price": ev.strike_price,
            "transaction_value": ev.transaction_value,
            "shares_held_after": ev.shares_held_after,
            "notes": ev.notes,
        })
    return rows


def build_activist_campaigns(state: WorldState) -> list[dict]:
    """Stage 12: activist investor campaigns and firm responses.

    One row per campaign event from `state.activist_campaigns`.
    """
    from .wrds_identifiers import identifiers_for_firm, abs_quarter_to_datadate
    rows = []
    for ev in state.activist_campaigns:
        fid = ev.get("firm_id", "")
        ids = identifiers_for_firm(fid)
        q = ev.get("event_quarter", 0)
        rows.append({
            "run_id": state.run_id,
            "firm_id": fid,
            "tic": ids["tic"],
            "conm": ids["conm"],
            "sic": ids["sic"],
            "event_quarter": q,
            "event_date": abs_quarter_to_datadate(q) if q else "",
            "activist_id": ev.get("activist_id", ""),
            "demand_type": ev.get("demand_type", ""),
            "demand_specifics": ev.get("demand_specifics", ""),
            "stake_pct_implied": ev.get("stake_pct_implied", 0.0),
            "firm_response": ev.get("firm_response", ""),
            "firm_rationale": ev.get("firm_rationale", ""),
        })
    return rows


def build_bond_issuances(state: WorldState) -> list[dict]:
    """Mergent FISD-style bond issuance record. One row per bond or convertible
    bond facility; excludes bank term loans and revolvers."""
    from .wrds_identifiers import identifiers_for_firm, abs_quarter_to_datadate
    rows = []
    for fid, fac in _iter_facilities(state):
        if fac.facility_type not in ("bond", "convertible_bond"):
            continue
        ids = identifiers_for_firm(fid)
        rows.append({
            "run_id": state.run_id,
            "firm_id": fid,
            "tic": ids["tic"],
            "conm": ids["conm"],
            "sic": ids["sic"],
            "facility_id": fac.facility_id,
            "bond_type": fac.facility_type,
            "offering_amount": fac.original_principal,
            "offering_quarter": fac.origination_quarter,
            "offering_date": abs_quarter_to_datadate(fac.origination_quarter),
            "maturity_quarter": fac.maturity_quarter,
            "maturity_date": abs_quarter_to_datadate(fac.maturity_quarter),
            "coupon_rate_annual": fac.coupon_rate_quarterly * 4,
            "is_convertible": int(fac.facility_type == "convertible_bond"),
            "conversion_ratio": fac.conversion_ratio,
            "conversion_price": fac.conversion_price,
        })
    return rows
