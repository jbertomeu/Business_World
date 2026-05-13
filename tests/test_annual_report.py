"""
Tests for annual report (10-K-style) generation.

Coverage:
  - aggregate_year: deterministic full-year financials from compustat rows
  - parse_annual_report: builds AnnualReport dataclass from LLM JSON + aggregates
  - render_annual_report_markdown: produces well-formed markdown
  - End-to-end orchestrator wiring: runs at fqtr=4 only, when toggle on
  - Backward-compat: no annual reports when toggle off
"""

from __future__ import annotations

import pytest

from src.types import (
    FirmState, CompustatRow, MacroState, SimParams, RawDecisions,
    AnnualReport, AuditResult,
)
from src.annual_report import (
    aggregate_year, build_annual_prompt, parse_annual_report,
    render_annual_report_markdown, make_annual_report_generator,
)


def _row(fyearq, fqtr, **kwargs):
    """Helper: build a CompustatRow with minimal defaults."""
    base = dict(
        run_id="r", firm_id="firm_0", incarnation=1,
        fyearq=fyearq, fqtr=fqtr,
        saleq=10_000_000, cogsq=4_000_000, gpq=6_000_000,
        xrdq=12_000_000, xsgaq=3_000_000, dpq=500_000,
        oiadpq=-9_500_000, xintq=200_000,
        piq=-9_700_000, txtq=0, niq=-9_700_000,
        cheq=80_000_000, atq=120_000_000, ltq=10_000_000, ceqq=110_000_000,
        dlttq=0, dlcq=0, req=-15_000_000,
        oancfq=-9_000_000, ivncfq=-1_000_000, fincfq=0, chechq=-10_000_000, capxq=1_000_000,
        sstkq=0, prstkq=0, dvq=0, prccq=12.50, cshoq=10.0,
    )
    base.update(kwargs)
    return CompustatRow(**base)


def test_aggregate_year_sums_four_quarters():
    rows = [_row(2031, q, saleq=10e6 + q*1e6) for q in (1, 2, 3, 4)]
    agg = aggregate_year(FirmState(firm_id="firm_0"), rows)
    # Revenue sum = 11+12+13+14 = 50M
    assert agg["annual_revenue"] == pytest.approx(50_000_000)
    # NI sum = 4 × -9.7M = -38.8M
    assert agg["annual_net_income"] == pytest.approx(-38_800_000)
    # Year-end balance (last row's BS)
    assert agg["year_end_cash"] == 80_000_000
    assert agg["year_end_total_assets"] == 120_000_000


def test_aggregate_year_yoy_growth():
    prior = [_row(2030, q, saleq=10_000_000) for q in (1, 2, 3, 4)]   # $40M
    current = [_row(2031, q, saleq=15_000_000) for q in (1, 2, 3, 4)]  # $60M
    agg = aggregate_year(FirmState(firm_id="firm_0"), current, prior)
    assert agg["yoy_revenue_growth"] == pytest.approx(0.50, rel=0.01)


def test_aggregate_year_eps_uses_yearend_shares():
    rows = [_row(2031, q, niq=-1_000_000, cshoq=10.0) for q in (1, 2, 3, 4)]
    agg = aggregate_year(FirmState(firm_id="firm_0"), rows)
    # 4 × -1M / (10M shares) = -$0.40
    assert agg["annual_eps"] == pytest.approx(-0.40, rel=0.01)


def test_parse_annual_report_handles_missing_llm_response():
    """When LLM fails, parse_annual_report returns a report with aggregates
    populated and empty narrative fields."""
    rows = [_row(2031, q) for q in (1, 2, 3, 4)]
    agg = aggregate_year(FirmState(firm_id="firm_0"), rows)
    macro = MacroState(quarter=4, fyear=2031, fqtr=4)
    report = parse_annual_report(None, FirmState(firm_id="firm_0"), macro,
                                  agg, audit=None, covenant_violations_count=0)
    assert report.firm_id == "firm_0"
    assert report.fyear == 2031
    assert report.annual_revenue == agg["annual_revenue"]
    assert report.mda_summary == ""  # no LLM response
    assert report.audit_opinion == ""
    assert report.going_concern_flag is False


def test_parse_annual_report_picks_up_audit_signals():
    rows = [_row(2031, q) for q in (1, 2, 3, 4)]
    agg = aggregate_year(FirmState(firm_id="firm_0"), rows)
    macro = MacroState(quarter=4, fyear=2031, fqtr=4)
    audit = AuditResult(
        firm_id="firm_0", auditor_id="auditor_2", fiscal_year=2031,
        opinion="adverse", going_concern=True, fee=250_000,
    )
    report = parse_annual_report(None, FirmState(firm_id="firm_0"), macro,
                                  agg, audit=audit, covenant_violations_count=2)
    assert report.audit_opinion == "adverse"
    assert report.going_concern_flag is True
    assert report.covenant_violations_count == 2


def test_parse_annual_report_coerces_string_numbers():
    """LLMs sometimes return guidance with $ or , prefix. Parser must handle."""
    rows = [_row(2031, q) for q in (1, 2, 3, 4)]
    agg = aggregate_year(FirmState(firm_id="firm_0"), rows)
    macro = MacroState(quarter=4, fyear=2031, fqtr=4)
    report = parse_annual_report(
        {"forward_guidance_revenue": "$120,000,000",
         "forward_guidance_eps": "$1.50",
         "mda_summary": "Strong year overall."},
        FirmState(firm_id="firm_0"), macro, agg, None, 0,
    )
    assert report.forward_guidance_revenue == 120_000_000
    assert report.forward_guidance_eps == 1.50
    assert "Strong year" in report.mda_summary


def test_render_markdown_well_formed():
    rows = [_row(2031, q) for q in (1, 2, 3, 4)]
    agg = aggregate_year(FirmState(firm_id="firm_0"), rows)
    macro = MacroState(quarter=4, fyear=2031, fqtr=4)
    report = parse_annual_report(
        {"mda_summary": "We had a good year despite headwinds.",
         "forward_guidance_revenue": 60_000_000,
         "forward_guidance_eps": -0.30,
         "key_strategic_initiatives": "- Advance Gen 2\n- Expand market share",
         "risk_factors": "- Regulatory risk\n- Competition"},
        FirmState(firm_id="firm_0", capacity_units=250), macro, agg, None, 0,
    )
    md = render_annual_report_markdown(report, "Aeterna Therapeutics")
    assert "# Annual Report" in md
    assert "Aeterna Therapeutics" in md
    assert "Fiscal Year 2031" in md
    assert "Total revenue" in md
    assert "Management Discussion & Analysis" in md
    assert "We had a good year despite headwinds." in md
    assert "Forward Guidance" in md
    assert "Advance Gen 2" in md
    assert "Regulatory risk" in md


# ── Orchestrator integration ──────────────────────────────────────────────

def test_orchestrator_runs_annual_report_only_at_fqtr_4():
    """Annual report should be appended to state.annual_reports only at fqtr=4
    when annual_reports_enabled is True."""
    from src.orchestrator import WorldState, run_quarter
    from src.config import RunConfig

    state = WorldState(run_id="test")
    state.firms["firm_0"] = FirmState(
        firm_id="firm_0", is_active=True, cash=100_000_000,
        capacity_units=100, base_unit_cost=40_000,
        ppe_gross=25_000_000, shares_outstanding=10_000_000,
    )
    state.params = SimParams()
    config = RunConfig(annual_reports_enabled=True)

    def firm_fn(fid, firm, info, params):
        return RawDecisions(price=95_000, production=50, capex=0,
                             rd_spend=10_000_000,
                             rd_allocation={"product": 1.0, "process": 0, "delivery": 0},
                             sga_spend=2_000_000)

    # Stub annual report generator returns a minimal AnnualReport
    def stub_annual(firm, year_rows, prior_year_rows, macro, audit, viol_count):
        agg = aggregate_year(firm, year_rows, prior_year_rows)
        return parse_annual_report(
            {"mda_summary": "Stub MD&A", "forward_guidance_revenue": 100,
             "forward_guidance_eps": 0},
            firm, macro, agg, audit, viol_count,
        )

    # Run Q1 (fqtr=1) — no annual report should appear
    new_state = run_quarter(state, firm_agent_fn=firm_fn,
                             env_agent_fn=lambda *a, **k: None,
                             annual_report_fn=stub_annual, config=config)
    assert len(new_state.annual_reports) == 0

    # Run Q2, Q3 — still no annual report
    for _ in range(2):
        new_state = run_quarter(new_state, firm_agent_fn=firm_fn,
                                 env_agent_fn=lambda *a, **k: None,
                                 annual_report_fn=stub_annual, config=config)
    assert len(new_state.annual_reports) == 0

    # Q4 — annual report should now appear
    new_state = run_quarter(new_state, firm_agent_fn=firm_fn,
                             env_agent_fn=lambda *a, **k: None,
                             annual_report_fn=stub_annual, config=config)
    assert len(new_state.annual_reports) == 1
    assert new_state.annual_reports[0].fyear == 2031
    assert new_state.annual_reports[0].firm_id == "firm_0"


def test_compustat_a_aggregates_from_quarterly_rows():
    """compustat_a.csv builder mirrors WRDS funda: IS/CF lines summed,
    BS lines from year-end snapshot, identifiers + funda metadata present."""
    from src.orchestrator import WorldState
    from src.datasets import build_compustat_a, COMPUSTAT_A_COLUMNS

    state = WorldState(run_id="test")
    # Two firms × two years
    rows_in = []
    for fid in ("firm_0", "firm_1"):
        for fyear in (2031, 2032):
            for fqtr in (1, 2, 3, 4):
                rows_in.append(_row(
                    fyear, fqtr,
                    firm_id=fid,
                    saleq=10_000_000 * fqtr,    # increases through year
                    cogsq=4_000_000 * fqtr,
                    niq=-(2_000_000 + fqtr * 500_000),
                    cheq=80_000_000 - fqtr * 5_000_000,  # year-end is fqtr=4
                    atq=120_000_000 - fqtr * 3_000_000,
                ))
    state.compustat_rows = rows_in
    out = build_compustat_a(state)
    # 2 firms × 2 years = 4 rows
    assert len(out) == 4

    # Spot-check firm_0 FY2031: revenue summed = 10+20+30+40 = $100M
    fy2031 = next(r for r in out if r["firm_id"] == "firm_0" and r["fyear"] == 2031)
    assert fy2031["sale"] == 100_000_000
    assert fy2031["cogs"] == 40_000_000
    # NI summed = -(2.5 + 3 + 3.5 + 4) = -$13M
    assert fy2031["ni"] == pytest.approx(-13_000_000)
    # BS year-end = fqtr=4 row's cheq (80M - 4*5M = 60M)
    assert fy2031["che"] == 60_000_000
    # Funda metadata constants
    assert fy2031["indfmt"] == "INDL"
    assert fy2031["consol"] == "C"
    assert fy2031["popsrc"] == "D"
    assert fy2031["datafmt"] == "STD"
    # Datadate = fyear-12-31
    assert fy2031["datadate"] == "2031-12-31"
    # Identifiers
    assert fy2031["tic"]  # non-empty
    assert fy2031["conm"]
    assert fy2031["sic"]
    # All schema columns present
    for col in COMPUSTAT_A_COLUMNS:
        assert col in fy2031, f"missing column {col}"


def test_compustat_a_handles_partial_year():
    """A firm with only 2 quarters in a year still produces a row (partial-year
    aggregation is correct sum over available quarters)."""
    from src.orchestrator import WorldState
    from src.datasets import build_compustat_a

    state = WorldState(run_id="test")
    state.compustat_rows = [
        _row(2031, 1, saleq=5_000_000),
        _row(2031, 2, saleq=7_000_000),
    ]
    out = build_compustat_a(state)
    assert len(out) == 1
    assert out[0]["sale"] == 12_000_000
    assert out[0]["fyear"] == 2031


def test_orchestrator_skips_annual_report_when_toggle_off():
    """Annual report not generated when annual_reports_enabled=False."""
    from src.orchestrator import WorldState, run_quarter
    from src.config import RunConfig

    state = WorldState(run_id="test")
    state.firms["firm_0"] = FirmState(
        firm_id="firm_0", is_active=True, cash=100_000_000,
        capacity_units=100, base_unit_cost=40_000,
        ppe_gross=25_000_000, shares_outstanding=10_000_000,
    )
    state.params = SimParams()
    config = RunConfig(annual_reports_enabled=False)

    def firm_fn(fid, firm, info, params):
        return RawDecisions(price=95_000, production=50, capex=0,
                             rd_spend=10_000_000,
                             rd_allocation={"product": 1.0, "process": 0, "delivery": 0},
                             sga_spend=2_000_000)

    # Run 4 quarters with toggle off
    for _ in range(4):
        state = run_quarter(state, firm_agent_fn=firm_fn,
                             env_agent_fn=lambda *a, **k: None,
                             config=config)
    assert len(state.annual_reports) == 0
