"""Reproduce the Q42 TypeError by simulating the firm_agent against Q41 state.

Uses MockBackend so we don't burn LLM tokens. The board discussion + firm
decision JSON are mocked. The point is to walk the orchestration code path
and see if any division crashes for the firms that crashed in production.
"""
import sys, os, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pickle
from src.cli import make_firm_agent
from src.llm_backends import MockBackend
from src.orchestrator import _build_firm_info_package


def main():
    snap = pickle.load(open('outputs/run_1777670848/snapshots/Q41.pkl','rb'))
    state = snap['world_state']

    # Mock backend that returns a perfectly valid decision JSON.
    # If the crash is in board prompt / parsing / something pre-LLM,
    # this won't matter. If it's post-LLM, this gives valid result.
    valid_response = '''```json
{
  "price": 150000,
  "production": 250,
  "capex": 5000000,
  "rd_spend": 18000000,
  "rd_allocation": {"product": 0.6, "process": 0.25, "delivery": 0.15},
  "sga_spend": 8000000,
  "equity_issuance_request": 0,
  "debt_request": 0,
  "dividends": 0,
  "buybacks": 0,
  "reasoning": "test"
}
```'''
    # Board response with a forecast section
    board_response = """CONSENSUS: continue at full capacity
ACTION ITEMS: monitor competitors

PART C: AGREED FORECAST
price: $150,000
production: 250
revenue_target: $37,500,000
rd_spend: $18,000,000
sga_spend: $8,000,000
expected_ni: $5,000,000
expected_end_cash: $4,000,000,000
market_share_target: 15%
"""
    backend = MockBackend(responses={
        "BOARD MEETING": board_response,
        "DECISION": valid_response,
        "": valid_response,  # default
    })
    backends = {"default": backend}
    last_flows = {}
    # Populate last_flows the same way orchestrator does
    for fid, fl in (state.last_quarter_flows or {}).items():
        last_flows[fid] = {
            "net_sales": fl.net_sales, "cogs": fl.cogs,
            "net_income": fl.net_income, "cfo": fl.cfo,
            "units_sold": fl.units_sold, "market_share": fl.market_share,
            "actual_price": fl.actual_price,
            "actual_rd_spend": fl.actual_rd_spend,
            "actual_sga_spend": fl.actual_sga_spend,
            "actual_capex": fl.actual_capex,
            "end_cash": state.firms[fid].cash if fid in state.firms else 0,
        }
    board_minutes_store = {}
    agent_memories = {}
    state_ref = [state]

    firm_agent = make_firm_agent(
        backends, last_flows, board_minutes_store, agent_memories, state_ref,
        earnings_management_enabled=True,
        debt_covenants_enabled=True,
        working_capital_decisions=True,
        bad_debt_enabled=True,
        restructuring_enabled=True,
        governance_enabled=True,
        legal_reserves_enabled=True,
        pension_enabled=True,
        data_broker=None,  # skip data broker path
    )

    surviving = sorted([fid for fid, f in state.firms.items()
                         if f.is_active and not getattr(f, "is_dormant", False)])
    print(f'Testing firm_agent on {len(surviving)} surviving firms from Q41 state')
    print(f'(after Q41 firm_6 default; same firms that crashed at Q42 in prod)')
    print()

    for fid in surviving:
        try:
            info = _build_firm_info_package(state, fid)
            raw = firm_agent(fid, state.firms[fid], info, state.params)
            print(f'  {fid}: OK  prod={raw.production} price=${raw.price:,.0f} src={raw.decision_source}')
        except Exception as e:
            print(f'  {fid}: FAIL: {type(e).__name__}: {e}')
            traceback.print_exc()
            print()


if __name__ == "__main__":
    main()
