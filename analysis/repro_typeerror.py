"""Reproduce the Q42 TypeError that contaminated Wave ν+6 Phase 2.

Loads the Q41 snapshot and calls _build_firm_info_package for each
surviving firm. We then call build_board_prompt + build_firm_prompt with
that package and see which (if any) raise a TypeError.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pickle, traceback
from src.orchestrator import _build_firm_info_package
from src.prompts import build_firm_prompt
from src.board_discussion import build_board_prompt


def main():
    snap = pickle.load(open('outputs/run_1777670848/snapshots/Q41.pkl', 'rb'))
    state = snap['world_state']
    print(f'Loaded Q41 snapshot. Firms: {sorted(state.firms.keys())}')
    print(f'Active: {[fid for fid,f in state.firms.items() if f.is_active]}')
    print()

    surviving = [fid for fid, f in state.firms.items()
                 if f.is_active and not getattr(f, "is_dormant", False)]

    for fid in sorted(surviving):
        try:
            info = _build_firm_info_package(state, fid)
            firm = state.firms[fid]
            flows = info.get("own_private", {})
            # _build_firm_info_package may not be the trigger. The crash
            # happened inside firm_agent when building prompts. Try those.
            gazette = info.get("gazette", "")
            rd_report = info.get("own_private", {}).get("rd_report")
            brand_report = info.get("own_private", {}).get("brand_report")
            params = state.params

            try:
                board_sys, board_user = build_board_prompt(
                    firm, info, params, flows, rd_report, brand_report,
                    None, gazette, data_dir="data",
                )
                print(f'  {fid}: build_board_prompt OK  (sys={len(board_sys)}c, user={len(board_user)}c)')
            except Exception as e:
                print(f'  {fid}: build_board_prompt FAIL: {type(e).__name__}: {e}')
                traceback.print_exc()
                continue

            try:
                sys_p, user_p = build_firm_prompt(
                    firm, info, params, flows, gazette, rd_report, brand_report,
                )
                print(f'  {fid}: build_firm_prompt  OK  (sys={len(sys_p)}c, user={len(user_p)}c)')
            except Exception as e:
                print(f'  {fid}: build_firm_prompt FAIL: {type(e).__name__}: {e}')
                traceback.print_exc()

        except Exception as e:
            print(f'  {fid}: info-package FAIL: {type(e).__name__}: {e}')
            traceback.print_exc()


if __name__ == "__main__":
    main()
