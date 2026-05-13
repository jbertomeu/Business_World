"""
Integration test: full 5-quarter smoke run with mock agents.

This test verifies the complete pipeline:
  Initialize -> IPO -> Firm decisions -> Clamp -> Demand -> Accounting -> Settlement

All agents are deterministic mocks. The test checks that:
1. The simulation runs without errors for 5 quarters
2. All accounting invariants hold every quarter
3. Compustat panel has the right number of rows
4. Firms differentiate (not all identical)
5. Cash evolves plausibly (IPO -> gradual burn)
"""

import pytest

from src.types import FirmState, RawDecisions, SimParams, MacroState
from src.orchestrator import initialize_world, run_quarter, WorldState
from src.accounting import validate_state


PARAMS = SimParams()


def mock_firm_agent(firm_id: str, firm: FirmState, public_info: dict,
                    params: SimParams) -> RawDecisions:
    """Mock firm agent: simple deterministic strategy based on firm_id."""
    # Different firms get different strategies (via firm_id hash)
    firm_idx = int(firm_id.split("_")[1])

    base_price = 90_000 + firm_idx * 3_000  # 90K to 102K
    production = min(firm.capacity_units, 200 + firm_idx * 10)
    rd_spend = 20_000_000 + firm_idx * 5_000_000  # 20M to 40M
    sga_spend = 10_000_000 + firm_idx * 2_000_000

    return RawDecisions(
        price=base_price,
        production=production,
        capex=10_000_000,
        rd_spend=rd_spend,
        rd_allocation={"product": 0.6, "process": 0.25, "delivery": 0.15},
        sga_spend=sga_spend,
        dividends=0,
        buybacks=0,
        reasoning=f"Mock strategy for {firm_id}",
    )


class TestSmokeRun:
    """Full integration smoke test."""

    def setup_method(self):
        self.state = initialize_world(
            n_firms=5,
            params=PARAMS,
            seed=42,
            run_id="smoke_test",
        )

    def test_initialization(self):
        """World initializes correctly."""
        assert len(self.state.firms) == 5
        assert len(self.state.slots) == 5
        assert self.state.quarter == 0
        for fid, firm in self.state.firms.items():
            assert firm.is_active
            # Wave ν+10 item 8: heterogeneous IC sample capacity from
            # N(250, 30) clipped to [150, 350]. The exact value varies
            # per firm; assert the bounds rather than a specific number.
            assert 150 <= firm.capacity_units <= 350
            assert firm.cash == 0  # pre-IPO

    def test_5_quarter_run(self):
        """Full 5-quarter run completes without errors."""
        state = self.state

        for q in range(5):
            state = run_quarter(
                state,
                firm_agent_fn=mock_firm_agent,
                env_agent_fn=None,  # use deterministic fallback
                            )

            # Print quarter summary
            for msg in state.quarter_log:
                print(msg)

            # Check all firms
            for fid, firm in state.firms.items():
                if not firm.is_active:
                    continue

                # Balance sheet identity
                bs_diff = abs(firm.total_assets - firm.total_liabilities
                              - firm.total_equity)
                assert bs_diff < 1.0, (
                    f"Q{state.quarter} {fid}: BS identity violated by {bs_diff:.2f}"
                )

                # Non-negative cash (for active firms)
                assert firm.cash >= -1.0, (
                    f"Q{state.quarter} {fid}: Negative cash {firm.cash:.2f}"
                )

                # Non-negative assets
                assert firm.total_assets >= -1.0, (
                    f"Q{state.quarter} {fid}: Negative assets {firm.total_assets:.2f}"
                )

        # Final checks
        assert state.quarter == 5

        # Compustat panel
        assert len(state.compustat_rows) == 25  # 5 firms * 5 quarters

        # Firms should still be active (mock agents don't burn too fast)
        active = sum(1 for f in state.firms.values() if f.is_active)
        assert active >= 3, f"Only {active} firms active after 5Q"

    def test_firms_differentiate(self):
        """Firms should have different prices and outcomes."""
        state = self.state

        # Run 3 quarters
        for _ in range(3):
            state = run_quarter(state, mock_firm_agent, None, None)

        # Check that prices differ
        prices = [state.firms[f"firm_{i}"].equity_price for i in range(5)]
        # At minimum, firms should have different cash levels
        cash_levels = [state.firms[f"firm_{i}"].cash for i in range(5)
                       if state.firms[f"firm_{i}"].is_active]
        assert len(set(int(c / 1_000_000) for c in cash_levels)) > 1, (
            f"All firms have identical cash: {cash_levels}"
        )

    def test_cash_trajectory(self):
        """Cash should start high (IPO) and gradually decrease (R&D burn)."""
        state = self.state
        firm_0_cash = []

        for _ in range(5):
            state = run_quarter(state, mock_firm_agent, None, None)
            firm_0_cash.append(state.firms["firm_0"].cash)

        # Cash should be positive (no default in 5Q with $325M IPO)
        assert all(c > 0 for c in firm_0_cash), f"Cash went negative: {firm_0_cash}"

        # Cash should be declining (burning through IPO capital)
        assert firm_0_cash[-1] < firm_0_cash[0], (
            f"Cash not declining: {firm_0_cash[0]/1e6:.0f}M -> {firm_0_cash[-1]/1e6:.0f}M"
        )

    def test_compustat_panel_valid(self):
        """Compustat panel has correct structure."""
        state = self.state

        for _ in range(3):
            state = run_quarter(state, mock_firm_agent, None, None)

        assert len(state.compustat_rows) == 15  # 5 firms * 3 quarters

        for row in state.compustat_rows:
            assert row.run_id == "smoke_test"
            assert row.firm_id.startswith("firm_")
            assert row.fyearq >= 2031
            assert row.fqtr in (1, 2, 3, 4)
            assert row.atq > 0  # assets should be positive
            # BS identity in Compustat
            bs_diff = abs(row.atq - row.ltq - row.ceqq)
            assert bs_diff < 2.0, f"Compustat BS identity: {bs_diff:.2f}"

    def test_20_quarter_run(self):
        """Longer run to test stability."""
        state = self.state

        def conservative_agent(firm_id, firm, public_info, params):
            """Conservative mock: lower spend to survive 20+ quarters."""
            idx = int(firm_id.split("_")[1])
            return RawDecisions(
                price=95_000 + idx * 2_000,
                production=min(firm.capacity_units, 180 + idx * 10),
                capex=0,  # no expansion
                rd_spend=12_000_000 + idx * 1_000_000,  # just above Phase III
                rd_allocation={"product": 0.7, "process": 0.2, "delivery": 0.1},
                sga_spend=5_000_000 + idx * 500_000,
                dividends=0,
                buybacks=0,
            )

        for q in range(20):
            state = run_quarter(state, conservative_agent, None, None)

        assert state.quarter == 20

        # At least some firms should survive 20 quarters with conservative spend
        active = sum(1 for f in state.firms.values() if f.is_active)
        assert active >= 2, f"Only {active} firms active after 20Q"

        # Compustat should have ~100 rows (5*20, minus any defaults)
        assert len(state.compustat_rows) >= 80  # allow for some defaults

        # R&D should have accumulated for surviving firms
        for fid, firm in state.firms.items():
            if firm.is_active:
                assert firm.rd_cumulative_product > 0, f"{fid} has no R&D progress"
                # With diminishing returns + low discretionary R&D, cap stock may
                # decline slightly from 35.0 due to depreciation outpacing gains
                assert firm.capability_stock > 25, f"{fid} capability collapsed to {firm.capability_stock:.1f}"

    def test_gazette_generated_each_quarter(self):
        """A gazette (or fallback note) should exist for each quarter."""
        state = self.state

        for _ in range(5):
            state = run_quarter(state, mock_firm_agent, None, None)

        assert len(state.gazettes) == 5
        for g in state.gazettes:
            assert len(g) > 0  # non-empty
