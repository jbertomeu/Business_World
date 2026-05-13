"""
Wave zeta: end-to-end scenario tests.

Verifies that a scenario YAML actually takes effect through the full
pipeline (load → initialize_world → Phase 2 IPO → compustat row).
Catches regressions where scenario path is wired but scenarios aren't
actually applied to firm state.
"""

from __future__ import annotations
from pathlib import Path

import pytest

from src.scenarios import (
    ScenarioConfig, FirmFoundingParams, load_scenario, default_scenario,
)
from src.orchestrator import initialize_world, run_quarter, WorldState
from src.types import (
    FirmState, RawDecisions, SimParams, MarketOutcome,
)
from src.config import RunConfig


def test_scenario_config_default_roundtrip():
    sc = default_scenario(n_firms=3)
    assert sc.name == "uniform_default"
    assert len(sc.firms) == 3
    assert sc.firms[0].founding_cash == 150_000_000
    assert sc.firms[0].ipo_price == 17.50


def test_scenario_yaml_loads_biotech_early_stage():
    path = Path("scenarios/biotech_early_stage.yaml")
    assert path.exists()
    sc = load_scenario(path)
    assert sc.name == "biotech_early_stage"
    assert len(sc.firms) == 5
    # Firm-level heterogeneity
    capabilities = [f.founding_capability for f in sc.firms]
    assert len(set(capabilities)) > 1, "scenario firms should differ in capability"


def test_scenario_yaml_loads_mature_industry():
    path = Path("scenarios/mature_industry.yaml")
    sc = load_scenario(path)
    # Mature industry: one challenger at lower IPO price
    prices = [f.ipo_price for f in sc.firms]
    assert min(prices) < 25, "mature industry expects 1 smaller firm"
    assert max(prices) >= 45, "mature industry expects 4 large incumbents"


def test_scenario_yaml_loads_distressed():
    path = Path("scenarios/distressed.yaml")
    sc = load_scenario(path)
    # Distressed: low cash across the board
    cash_vals = [f.founding_cash for f in sc.firms]
    assert max(cash_vals) < 100_000_000, "distressed firms should all be low-cash"


def test_initialize_world_applies_scenario_founding():
    """Verify per-firm founding conditions flow from scenario to FirmState."""
    sc = ScenarioConfig(
        name="test",
        firms=[
            FirmFoundingParams(firm_id="firm_0", founding_capability=30.0,
                                 founding_brand=20.0, base_unit_cost=10_000,
                                 ceo_base_salary=2_000_000),
            FirmFoundingParams(firm_id="firm_1", founding_capability=40.0,
                                 founding_brand=25.0, base_unit_cost=11_000,
                                 ceo_base_salary=1_500_000),
        ],
    )
    params = SimParams()
    state = initialize_world(n_firms=2, params=params, seed=42,
                               run_id="test_scen", scenario=sc)
    assert state.firms["firm_0"].capability_stock == 30.0
    assert state.firms["firm_0"].brand_stock == 20.0
    assert state.firms["firm_0"].base_unit_cost == 10_000
    assert state.firms["firm_0"].ceo_base_salary == 2_000_000
    assert state.firms["firm_1"].capability_stock == 40.0
    assert state.firms["firm_1"].ceo_base_salary == 1_500_000


def test_phase2_ipo_applies_scenario_financial_terms():
    """Running one quarter with a scenario should IPO firms at scenario
    terms (cash, shares, apic), not the legacy uniform $17.50 × 10M."""
    sc = ScenarioConfig(
        name="test_ipo",
        firms=[
            FirmFoundingParams(
                firm_id="firm_0",
                founding_cash=500_000_000,
                ipo_price=50.0,
                ipo_shares=20_000_000,
                founding_ppe_gross=100_000_000,
                founding_capability=50.0,
                founding_brand=40.0,
                base_unit_cost=9_000,
            ),
        ],
    )
    state = initialize_world(n_firms=1, params=SimParams(), seed=42,
                               run_id="test_ipo", scenario=sc)
    # Pre-IPO: no cash, PPE at scenario founding
    assert state.firms["firm_0"].cash == 0
    assert state.firms["firm_0"].ppe_gross == 100_000_000

    def firm_fn(fid, firm, info, params):
        import uuid
        return RawDecisions(
            price=95_000, production=10, capex=0, rd_spend=5_000_000,
            rd_allocation={"product": 0.6, "process": 0.2, "delivery": 0.2},
            sga_spend=3_000_000, decision_source="llm",
            proposal_id=str(uuid.uuid4()),
        )

    def env_fn(a, f, m, p):
        return {"total_demand": 10,
                "firm_outcomes": {"firm_0": {"units_sold": 10, "market_share": 1.0}},
                "narrative": "ok"}

    state = run_quarter(state, firm_agent_fn=firm_fn,
                          env_agent_fn=env_fn, config=RunConfig())
    firm = state.firms["firm_0"]
    # Post-IPO: scenario-specified shares outstanding, APIC, cash
    # (equity_price is a market function; we don't assert its level here)
    assert firm.shares_outstanding == 20_000_000, (
        f"Scenario IPO shares not applied: got {firm.shares_outstanding}"
    )
    # APIC ≈ ipo_raise - common_stock par. Scenario: $600M raise, $20K par.
    assert firm.apic > 500_000_000, (
        f"APIC too low for scenario IPO: got ${firm.apic:,.0f}"
    )
    # Cash after 1Q of accounting: started at $500M (= ipo_raise 600M - PPE 100M),
    # minus ~$10-20M opex. Assert still majority intact.
    assert firm.cash > 400_000_000, (
        f"Cash too low for scenario IPO: got ${firm.cash:,.0f}"
    )


def test_scenario_backward_compat_when_none():
    """No scenario → heterogeneous initial conditions sampled from
    per-firm distributions (Wave ν+10 item 8). The exact values vary
    per firm and per seed; assert the sampling bounds.
    """
    state = initialize_world(n_firms=2, params=SimParams(), seed=1,
                               run_id="legacy", scenario=None)
    f0 = state.firms["firm_0"]
    # PPE in [$15M, $50M] from N($25M, $5M) clipped
    assert 15_000_000 <= f0.ppe_gross <= 50_000_000
    # Capability and brand in [20, 80] from N(50, 10) clipped
    assert 20 <= f0.capability_stock <= 80
    assert 20 <= f0.brand_stock <= 80
    # Capacity in [150, 350]
    assert 150 <= f0.capacity_units <= 350


def test_scenario_load_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        load_scenario("scenarios/nonexistent.yaml")
