"""
Tests for v0.5 expansion modules.

Covers:
  - earnings_management math (apply_manipulation, detection probability)
  - restatement accounting (reversal, dual-column CompustatRows)
  - data_access tier filtering
  - data_templates (statistical functions)
  - data_broker (all 3 modes) with mock backend
  - output_organizer writes 7 WRDS datasets with correct schemas
"""

import random
from pathlib import Path

import pytest

from src.types import (
    FirmState, QuarterFlows, CompustatRow, MarketOutcome,
    ClampedDecisions, SimParams,
    SECInvestigationState, AnalystNote, AuditResult, EarningsRelease,
)


# ── Earnings Management ─────────────────────────────────────────────────

def test_em_apply_manipulation_overstate():
    from src.earnings_management import apply_manipulation
    reported, cumul = apply_manipulation(
        true_net_income=5_000_000,
        manipulation_amount=10_000_000,
        prior_cumulative=0,
    )
    assert reported == 15_000_000
    assert cumul == 10_000_000


def test_em_apply_manipulation_understate_accumulates():
    from src.earnings_management import apply_manipulation
    reported, cumul = apply_manipulation(
        true_net_income=20_000_000,
        manipulation_amount=-5_000_000,
        prior_cumulative=3_000_000,
    )
    assert reported == 15_000_000
    assert cumul == -2_000_000


def test_em_detection_prob_asymmetric():
    from src.earnings_management import detection_probability
    # Overstatement more detectable than understatement (same magnitude)
    p_over = detection_probability(50_000_000)
    p_under = detection_probability(-50_000_000)
    assert p_over > p_under
    # At the midpoint, overstatement detection is 50%
    assert 0.45 < p_over < 0.55


def test_em_detection_zero_stock():
    from src.earnings_management import detection_probability
    assert detection_probability(0.0) == 0.0
    assert detection_probability(0.5) == 0.0  # near-zero tolerance


def test_em_flows_through_accounting():
    """Manipulation injects into reported_net_income but not cash flows."""
    from src.accounting import post_quarter
    params = SimParams()
    firm = FirmState(
        firm_id="firm_0", quarter=1, cash=200_000_000,
        accounts_receivable=2_565_000, inventory_units=10,
        inventory_value=140_000, ppe_gross=25_000_000,
        accum_depreciation=0, accounts_payable=1_470_000,
        accrued_expenses=2_300_000, taxes_payable=0,
        revolver_balance=0, common_stock=500_000,
        apic=174_500_000, retained_earnings=0,
        capacity_units=250, base_unit_cost=14_000,
        shares_outstanding=10_000_000,
    )
    decisions = ClampedDecisions(
        price=92_000, production=200, capex=15_000_000,
        rd_spend=28_000_000,
        rd_allocation={"product": 0.6, "process": 0.25, "delivery": 0.15},
        sga_spend=8_000_000,
        manipulation_amount=5_000_000,
    )
    outcome = MarketOutcome(firm_id="firm_0", units_sold=180, market_share=0.35)
    new_state, flows = post_quarter(firm, decisions, outcome, params)

    # True vs reported differ by exactly manipulation_amount
    assert flows.reported_net_income - flows.true_net_income == 5_000_000
    # Cumulative stock grows
    assert new_state.cumulative_manipulation == 5_000_000
    # Cash should NOT include manipulation (it's an accrual)
    # (no direct check, but the difference shows up in retained_earnings vs CFO)


# ── Restatement ────────────────────────────────────────────────────────

def test_restatement_reverses_cumulative():
    from src.restatement import process_restatement
    firm = FirmState(firm_id="firm_0", cumulative_manipulation=10_000_000)
    row = CompustatRow(
        firm_id="firm_0", fyearq=2031, fqtr=3,
        niq=5_000_000, req=20_000_000, ceqq=100_000_000, atq=200_000_000,
        manipulation_amount=10_000_000,
    )
    new_firm, new_rows, event = process_restatement(firm, [row], "sec_forced", quarter=8)

    assert new_firm.cumulative_manipulation == 0.0
    assert new_rows[0].niq_restated == -5_000_000  # original niq - manipulation
    assert new_rows[0].restatement_flag == 1
    assert new_rows[0].restatement_quarter == 8
    # Event populated
    assert event["trigger"] == "sec_forced"
    assert event["sec_flag"] == 1
    assert event["restatement_amount"] == 10_000_000


def test_restatement_no_manipulation_noop():
    from src.restatement import process_restatement
    firm = FirmState(firm_id="firm_0", cumulative_manipulation=0.0)
    row = CompustatRow(firm_id="firm_0", niq=5_000_000, manipulation_amount=0.0)
    new_firm, new_rows, event = process_restatement(firm, [row], "voluntary", quarter=5)
    assert new_rows[0].restatement_flag == 0
    assert new_firm is firm  # unchanged
    # Wave ν+9 Bug M5: no-op returns a structured event (not {}) so a
    # forced restatement of a clean firm leaves an audit trail.
    assert event["outcome"] == "no_op"
    assert event["restatement_amount"] == 0.0
    assert event["trigger"] == "voluntary"
    assert event["firm_id"] == "firm_0"


# ── Data Access ────────────────────────────────────────────────────────

def test_access_sec_cannot_see_manipulation():
    from src.data_access import filter_compustat_row
    row = {"firm_id": "firm_0", "saleq": 100, "manipulation_amount": 5_000_000}
    filtered = filter_compustat_row(row, "sec")
    assert "manipulation_amount" not in filtered
    assert filtered["saleq"] == 100


def test_access_environment_sees_all():
    from src.data_access import filter_compustat_row
    row = {"firm_id": "firm_0", "saleq": 100, "manipulation_amount": 5_000_000}
    filtered = filter_compustat_row(row, "environment")
    assert "manipulation_amount" in filtered


def test_access_tiers_for_role():
    from src.data_access import DataTier, tiers_for_role
    assert DataTier.PUBLIC in tiers_for_role("firm_0")
    assert DataTier.OWN_PRIVATE in tiers_for_role("firm_0")
    assert DataTier.HIDDEN not in tiers_for_role("firm_0")
    assert DataTier.HIDDEN in tiers_for_role("environment")


# ── Data Templates ─────────────────────────────────────────────────────

def test_template_peer_benchmark():
    from src.data_templates import peer_benchmark
    rows = [
        {"firm_id": "firm_0", "fyearq": 2031, "fqtr": 1, "niq": 10},
        {"firm_id": "firm_1", "fyearq": 2031, "fqtr": 1, "niq": 20},
        {"firm_id": "firm_2", "fyearq": 2031, "fqtr": 1, "niq": 30},
    ]
    r = peer_benchmark("niq", "firm_1", rows)
    assert r["firm_value"] == 20
    assert r["cohort_size"] == 3
    assert r["rank"] == 2
    assert abs(r["percentile"] - 33.33) < 0.1


def test_template_time_series():
    from src.data_templates import time_series
    rows = [
        {"firm_id": "firm_0", "fyearq": 2031, "fqtr": q, "saleq": 100 + q * 10}
        for q in range(1, 6)
    ]
    r = time_series("saleq", "firm_0", rows)
    assert r["n_quarters"] == 5
    assert r["trend_slope"] > 0  # growing
    assert r["latest"] == 150


# ── Data Broker (all three modes) ──────────────────────────────────────

class _MockTemplateBackend:
    def complete(self, system, user):
        return '''```json
{"action": "template", "template_name": "peer_benchmark",
 "args": {"metric": "niq", "firm_id": "firm_0"},
 "data_source": "current_run"}
```'''

    def complete_json(self, system, user, retries=2):
        import json
        import re
        text = self.complete(system, user)
        m = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
        return json.loads(m.group(1)) if m else None


class _MockCodeBackend:
    def complete(self, system, user):
        return '''```json
{"action": "code",
 "code": "import pandas as pd\\ndf = pd.read_csv(CURRENT_RUN)\\nprint('rows:', len(df))",
 "data_source": "current_run"}
```'''

    def complete_json(self, system, user, retries=2):
        import json
        import re
        text = self.complete(system, user)
        m = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
        return json.loads(m.group(1)) if m else None


def _sample_rows():
    return [
        {"firm_id": "firm_0", "fyearq": 2031, "fqtr": 1, "niq": 10, "saleq": 100},
        {"firm_id": "firm_1", "fyearq": 2031, "fqtr": 1, "niq": 20, "saleq": 150},
    ]


HYP = "If z-score > 2 I escalate; otherwise I take no action this quarter."


def test_broker_template_only_executes_template():
    from src.data_broker import DataBroker
    b = DataBroker(_MockTemplateBackend(), mode="template_only")
    ans = b.answer("sec", "Is firm_0 unusual?", HYP,
                   current_run_rows=_sample_rows(), quarter=1)
    assert "peer_benchmark" in ans
    assert "z_score" in ans


def test_broker_template_only_rejects_code():
    from src.data_broker import DataBroker
    b = DataBroker(_MockCodeBackend(), mode="template_only")
    ans = b.answer("sec", "Novel query", HYP,
                   current_run_rows=_sample_rows(), quarter=1)
    assert "did not match any template" in ans.lower()


def test_broker_combo_executes_code():
    from src.data_broker import DataBroker
    b = DataBroker(_MockCodeBackend(), mode="combo")
    ans = b.answer("sec", "Count rows", HYP,
                   current_run_rows=_sample_rows(), quarter=1)
    assert "rows:" in ans
    assert "2" in ans  # two rows in sample


def test_broker_freeform_rejects_template():
    from src.data_broker import DataBroker
    b = DataBroker(_MockTemplateBackend(), mode="freeform")
    ans = b.answer("sec", "Any query", HYP,
                   current_run_rows=_sample_rows(), quarter=1)
    assert "only code actions" in ans.lower()


def test_broker_rejects_bad_hypothesis():
    from src.data_broker import DataBroker
    b = DataBroker(_MockTemplateBackend(), mode="template_only")
    ans = b.answer("sec", "show me firm_0", "just checking",
                   current_run_rows=_sample_rows(), quarter=1)
    assert "no decision-relevant hypothesis" in ans.lower()


def test_broker_cost_cap():
    from src.data_broker import DataBroker
    b = DataBroker(_MockTemplateBackend(), mode="template_only",
                   max_queries_per_agent_per_quarter=1)
    # First query succeeds
    r1 = b.answer("sec", "Query 1", HYP, current_run_rows=_sample_rows(), quarter=1)
    assert "peer_benchmark" in r1
    # Second query rejected
    r2 = b.answer("sec", "Query 2", HYP, current_run_rows=_sample_rows(), quarter=1)
    assert "rejected" in r2.lower()


def test_broker_cache():
    from src.data_broker import DataBroker
    b = DataBroker(_MockTemplateBackend(), mode="template_only")
    r1 = b.answer("sec", "same question", HYP, current_run_rows=_sample_rows(), quarter=1)
    r2 = b.answer("sec", "same question", HYP, current_run_rows=_sample_rows(), quarter=1)
    assert "[cached]" in r2


def test_broker_invalid_mode_raises():
    from src.data_broker import DataBroker
    with pytest.raises(ValueError, match="Invalid broker mode"):
        DataBroker(_MockTemplateBackend(), mode="bogus")


# ── Dataset output ─────────────────────────────────────────────────────

def test_datasets_schema_columns():
    """Every dataset builder's column list matches its schema constant."""
    from src import datasets
    # These constants define canonical columns
    assert "ceo_id" in datasets.EXECUCOMP_COLUMNS
    assert "audit_opinion" in datasets.AUDIT_ANALYTICS_COLUMNS
    assert "trigger" in datasets.RESTATEMENTS_COLUMNS
    assert "eps_forecast" in datasets.ANALYST_FORECASTS_COLUMNS
    assert "eps_guidance" in datasets.MANAGEMENT_FORECASTS_COLUMNS
    assert "event_type" in datasets.CEO_TURNOVER_COLUMNS


def test_datasets_empty_world_state_produces_empty_lists():
    """Builders don't crash on empty WorldState (fresh simulation)."""
    from src import datasets
    from src.orchestrator import WorldState
    state = WorldState(run_id="test")
    assert datasets.build_execucomp(state) == []
    assert datasets.build_audit_analytics(state) == []
    assert datasets.build_analyst_forecasts(state) == []
    assert datasets.build_management_forecasts(state) == []
    assert datasets.build_ceo_turnover(state) == []


def test_datasets_analyst_notes_produce_forecast_rows():
    """AnalystNotes in state produce rows in analyst_forecasts."""
    from src import datasets
    from src.orchestrator import WorldState
    state = WorldState(run_id="test")
    state.analyst_notes.append(AnalystNote(
        analyst_id="analyst_1", firm_id="firm_0", quarter=3,
        eps_forecast_1q=0.50, target_price=17.50, rating="buy",
        methodology="DCF", narrative="strong pipeline",
    ))
    rows = datasets.build_analyst_forecasts(state)
    assert len(rows) == 1
    assert rows[0]["analyst_id"] == "analyst_1"
    assert rows[0]["eps_forecast"] == 0.50
    assert rows[0]["rating"] == "buy"


def test_output_organizer_writes_7_datasets(tmp_path):
    """End-to-end: organize_run_outputs produces 7 CSVs with headers."""
    from src.output_organizer import organize_run_outputs
    from src.orchestrator import WorldState
    state = WorldState(run_id="test_run")
    # Minimal valid run
    compustat_rows = [CompustatRow(run_id="test", firm_id="firm_0",
                                    fyearq=2031, fqtr=1, saleq=100, niq=10)]
    out = organize_run_outputs(
        run_id="test_run",
        output_dir=str(tmp_path),
        compustat_rows=compustat_rows,
        gazettes=["Q1 gazette"],
        product_spec_history=[],
        board_minutes_history=[],
        n_firms=1, n_quarters=1, seed=42,
        world_state=state,
    )
    expected = [
        "execucomp.csv", "audit_analytics.csv", "restatements.csv",
        "analyst_forecasts.csv", "management_forecasts.csv",
        "ceo_turnover.csv", "compustat_restated.csv",
    ]
    for name in expected:
        path = out / name
        assert path.exists(), f"{name} not written"
        content = path.read_text().strip().split("\n")
        assert len(content) >= 1, f"{name} has no header"
