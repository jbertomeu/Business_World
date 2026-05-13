"""
Output organization: structure run outputs into clean folder hierarchy.

Folder structure per run:
  outputs/{run_id}/
    compustat_q.csv                  # Compustat panel (public quant database)
    decisions.csv                    # All firm decisions per quarter
    summary.txt                     # Quick run summary
    gazettes.txt                    # All industry gazettes
    public/                         # Public knowledge (visible to all)
      gazette_Q1.txt
      gazette_Q2.txt
      ...
    firms/                          # Per-firm private data
      firm_0/
        board_minutes_Q1.md
        board_minutes_Q2.md
        rd_report_Q1.txt
        brand_report_Q1.txt
        product_spec_Q1.txt
        ...
      firm_1/
        ...
    environment/                    # Environment-only data
      demand_baseline_Q1.txt
      ...

Cross-run accumulation:
  data/
    compustat_all.csv               # Append-only panel across all runs
    decisions_all.csv               # Append-only decisions across all runs
    run_index.csv                   # One row per run with summary stats
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from dataclasses import dataclass

from .types import CompustatRow
from . import datasets


def organize_run_outputs(
    run_id: str,
    output_dir: str,
    compustat_rows: list[CompustatRow],
    gazettes: list[str],
    product_spec_history: list[dict[str, str]],
    board_minutes_history: list[dict[str, str]],
    n_firms: int,
    n_quarters: int,
    seed: int,
    world_state=None,
    broker_query_log: list | None = None,
):
    """Organize all outputs into the structured folder hierarchy."""

    base = Path(output_dir) / run_id
    base.mkdir(parents=True, exist_ok=True)

    # ── Compustat panel ──────────────────────────────────────────────────
    panel_path = base / "compustat_q.csv"
    if compustat_rows:
        fieldnames = list(compustat_rows[0].as_dict().keys())
        with open(panel_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row in compustat_rows:
                writer.writerow(row.as_dict())

    # ── Public folder (gazettes) ─────────────────────────────────────────
    public_dir = base / "public"
    public_dir.mkdir(exist_ok=True)

    for q_idx, gazette in enumerate(gazettes):
        gazette_path = public_dir / f"gazette_Q{q_idx+1}.txt"
        with open(gazette_path, "w", encoding="utf-8") as f:
            f.write(f"=== Industry Gazette -- Quarter {q_idx+1} ===\n\n")
            f.write(gazette)

    # Combined gazettes
    with open(base / "gazettes.txt", "w", encoding="utf-8") as f:
        for q_idx, gazette in enumerate(gazettes):
            f.write(f"=== Quarter {q_idx+1} ===\n{gazette}\n\n")

    # ── Per-firm folders ─────────────────────────────────────────────────
    firms_dir = base / "firms"
    firms_dir.mkdir(exist_ok=True)

    for i in range(n_firms):
        fid = f"firm_{i}"
        firm_dir = firms_dir / fid
        firm_dir.mkdir(exist_ok=True)

        # Board minutes
        for q_idx, q_minutes in enumerate(board_minutes_history):
            if fid in q_minutes:
                path = firm_dir / f"board_minutes_Q{q_idx+1}.md"
                with open(path, "w", encoding="utf-8") as f:
                    f.write(f"# Board Minutes: {fid} -- Quarter {q_idx+1}\n\n")
                    f.write(q_minutes[fid])

        # Product specs
        for q_idx, q_specs in enumerate(product_spec_history):
            if fid in q_specs:
                path = firm_dir / f"product_spec_Q{q_idx+1}.txt"
                with open(path, "w", encoding="utf-8") as f:
                    f.write(q_specs[fid])

        # Annual reports (10-K-style markdown), one per fiscal year
        if world_state is not None:
            from .annual_report import render_annual_report_markdown
            from .personalities import get_company_name
            firm_idx = int(fid.split("_")[-1]) if "_" in fid else 0
            firm_name = get_company_name(firm_idx)
            for ar in world_state.annual_reports:
                if ar.firm_id == fid:
                    path = firm_dir / f"annual_report_FY{ar.fyear}.md"
                    with open(path, "w", encoding="utf-8") as f:
                        f.write(render_annual_report_markdown(ar, firm_name))

    # ── Run summary ──────────────────────────────────────────────────────
    if compustat_rows:
        last_q_rows = [r for r in compustat_rows
                       if r.fqtr == compustat_rows[-1].fqtr
                       and r.fyearq == compustat_rows[-1].fyearq]
        total_rev = sum(r.saleq for r in last_q_rows)
        active = sum(1 for r in last_q_rows if r.default_flag == 0)

        summary_path = base / "summary.txt"
        with open(summary_path, "w", encoding="utf-8") as f:
            f.write(f"Run: {run_id}\n")
            f.write(f"Firms: {n_firms}, Quarters: {n_quarters}, Seed: {seed}\n")
            f.write(f"Completed: {len(gazettes)} quarters\n")
            f.write(f"Final quarter revenue: ${total_rev/1e6:.1f}M\n")
            f.write(f"Active firms at end: {active}\n")
            f.write(f"Compustat rows: {len(compustat_rows)}\n")
            f.write(f"\nPer-firm final state:\n")
            for r in last_q_rows:
                f.write(f"  {r.firm_id}: Rev=${r.saleq/1e6:.1f}M "
                        f"NI=${r.niq/1e6:.1f}M Cash=${r.cheq/1e6:.1f}M "
                        f"Price=${r.prccq:.2f}\n")

    # ── WRDS-style datasets (only if world_state provided) ────────────────
    if world_state is not None:
        _write_wrds_datasets(base, world_state, compustat_rows)

    # ── Broker query log (for auditing data queries) ──────────────────────
    if broker_query_log:
        with open(base / "broker_queries.jsonl", "w", encoding="utf-8") as f:
            for entry in broker_query_log:
                f.write(json.dumps(entry, default=str) + "\n")

    # ── BS violation log (Wave alpha: structured audit trail) ────────────
    # One record per phase-level BS identity drift. Empty file when clean.
    if world_state is not None:
        violations = getattr(world_state, "bs_violation_log", [])
        with open(base / "bs_violations.jsonl", "w", encoding="utf-8") as f:
            for v in violations:
                f.write(json.dumps(v, default=str) + "\n")

    # ── Proposal log (Wave beta: structured-action audit trail) ──────────
    # One record per (Action, ActionResult) pair. Every compustat_q row's
    # `proposal_id` keys back into this file. `decision_source` in the
    # row AND this file should agree; any mismatch is a wiring bug.
    if world_state is not None:
        proposals = getattr(world_state, "action_log", [])
        with open(base / "proposals.jsonl", "w", encoding="utf-8") as f:
            for p in proposals:
                f.write(json.dumps(p, default=str) + "\n")

    # ── Negotiations log (Wave gamma: multi-round bargaining history) ────
    # One record per completed negotiation (covenant waiver, debt pricing).
    # Each record has the full round-by-round offer history for research.
    if world_state is not None:
        negs = getattr(world_state, "negotiations_log", [])
        with open(base / "negotiations.jsonl", "w", encoding="utf-8") as f:
            for n in negs:
                f.write(json.dumps(n, default=str) + "\n")

    # ── Peer observation log (Wave theta+) ──────────────────────────────
    # One record per (quarter, observer, observed) noisy-peer-observation
    # event. Captures noise_sd_applied + n_shared_directors at the MOMENT
    # of observation for clean interlock→accuracy regressions.
    if world_state is not None:
        obs_log = getattr(world_state, "peer_observation_log", []) or []
        if obs_log:
            with open(base / "peer_observations.jsonl", "w",
                       encoding="utf-8") as f:
                for o in obs_log:
                    f.write(json.dumps(o, default=str) + "\n")

    # ── Strategic plans (Wave κ) ────────────────────────────────────────
    # One row per (firm, plan_quarter) with the plan's narrative, key
    # assumptions/risks/milestones, and a compact summary of its line
    # totals. Full per-quarter lines are omitted from the CSV to keep it
    # flat; the detailed plan is in snapshots if needed.
    if world_state is not None:
        _plan_rows = []
        for fid, firm in world_state.firms.items():
            plan = getattr(firm, "current_plan", None)
            if plan is None:
                continue
            total_planned_rev = sum(
                (line.planned_revenue for line in plan.lines), 0.0)
            total_planned_rd = sum(
                (line.planned_rd_spend for line in plan.lines), 0.0)
            total_planned_capex = sum(
                (line.planned_capex for line in plan.lines), 0.0)
            final_gen = (plan.lines[-1].planned_generation
                         if plan.lines else 1)
            final_cash = (plan.lines[-1].projected_cash_balance_eoq
                          if plan.lines else 0.0)
            _plan_rows.append({
                "run_id": world_state.run_id,
                "firm_id": fid,
                "plan_id": plan.plan_id,
                "plan_quarter": plan.plan_quarter,
                "plan_fyear": plan.plan_fyear,
                "plan_fqtr": plan.plan_fqtr,
                "horizon_quarters": plan.horizon_quarters,
                "total_planned_revenue": total_planned_rev,
                "total_planned_rd_spend": total_planned_rd,
                "total_planned_capex": total_planned_capex,
                "final_projected_generation": final_gen,
                "final_projected_cash": final_cash,
                "strategy_narrative": plan.strategy_narrative,
                "key_assumptions": " | ".join(plan.key_assumptions),
                "key_risks": " | ".join(plan.key_risks),
                "milestones": " | ".join(plan.milestones),
                "supersedes_plan_id": plan.supersedes_plan_id,
            })
        if _plan_rows:
            import csv as _csv_p
            with open(base / "strategic_plans.csv", "w",
                       encoding="utf-8", newline="") as f:
                w = _csv_p.DictWriter(f, fieldnames=list(_plan_rows[0].keys()))
                w.writeheader()
                for r in _plan_rows:
                    w.writerow(r)

    # ── PE rounds + PE portfolio (Wave λ) ────────────────────────────────
    if world_state is not None:
        # PE round events (one row per round)
        rounds = getattr(world_state, "pe_round_history", []) or []
        if rounds:
            import csv as _csv_pe
            with open(base / "pe_rounds.csv", "w",
                       encoding="utf-8", newline="") as f:
                w = _csv_pe.DictWriter(f, fieldnames=[
                    "run_id", "firm_id", "round_type", "round_quarter",
                    "round_fyear", "round_fqtr",
                    "pre_money_valuation", "post_money_valuation",
                    "amount_raised", "shares_issued", "price_per_share",
                    "lead_investor", "n_investors", "investor_ids",
                    # Wave ν: public projections + lead valuation method
                    "firm_revenue_y5", "firm_ebitda_margin_y5",
                    "firm_projected_generation_y5",
                    "firm_capital_required_to_profitability",
                    "lead_revenue_projection_y5", "lead_valuation_method",
                ])
                w.writeheader()
                for r in rounds:
                    investors_str = ";".join(inv[0] for inv in r.investors)
                    fp = r.firm_projections or {}
                    lp = r.lead_investor_projection or {}
                    w.writerow({
                        "run_id": world_state.run_id,
                        "firm_id": r.firm_id,
                        "round_type": r.round_type,
                        "round_quarter": r.round_quarter,
                        "round_fyear": r.round_fyear,
                        "round_fqtr": r.round_fqtr,
                        "pre_money_valuation": r.pre_money_valuation,
                        "post_money_valuation": r.post_money_valuation,
                        "amount_raised": r.amount_raised,
                        "shares_issued": r.shares_issued,
                        "price_per_share": r.price_per_share,
                        "lead_investor": r.lead_investor,
                        "n_investors": len(r.investors),
                        "investor_ids": investors_str,
                        "firm_revenue_y5": fp.get("revenue_y5", ""),
                        "firm_ebitda_margin_y5": fp.get("ebitda_margin_y5", ""),
                        "firm_projected_generation_y5": fp.get("projected_generation_y5", ""),
                        "firm_capital_required_to_profitability":
                            fp.get("capital_required_to_profitability", ""),
                        "lead_revenue_projection_y5":
                            lp.get("your_revenue_projection_y5", ""),
                        "lead_valuation_method": r.lead_valuation_method,
                    })
        # Wave ν: distressed-firm auction events (one row per default event)
        auctions = getattr(world_state, "distressed_auctions", []) or []
        if auctions:
            import csv as _csv_auc
            with open(base / "distressed_auctions.csv", "w",
                       encoding="utf-8", newline="") as f:
                w = _csv_auc.DictWriter(f, fieldnames=[
                    "run_id", "target_firm_id", "outcome",
                    "winner_id", "winning_amount",
                    "n_bids", "bid_ids", "bid_amounts",
                    "winner_rationale",
                ])
                w.writeheader()
                for a in auctions:
                    bids = a.get("bids", []) or []
                    w.writerow({
                        "run_id": world_state.run_id,
                        "target_firm_id": a.get("target_firm_id", ""),
                        "outcome": a.get("outcome", ""),
                        "winner_id": a.get("winner_id", ""),
                        "winning_amount": a.get("winning_amount", 0.0),
                        "n_bids": len(bids),
                        "bid_ids": ";".join(b.get("bidder_id", "") for b in bids),
                        "bid_amounts": ";".join(f"{b.get('amount', 0):.0f}" for b in bids),
                        "winner_rationale": (a.get("winner_rationale", "") or "")[:500],
                    })

        # PE fund end-state snapshot (one row per fund)
        funds = getattr(world_state, "pe_funds", {}) or {}
        if funds:
            import csv as _csv_pf
            with open(base / "pe_funds.csv", "w",
                       encoding="utf-8", newline="") as f:
                w = _csv_pf.DictWriter(f, fieldnames=[
                    "run_id", "fund_id", "name", "strategy",
                    "target_hurdle_rate", "horizon_years",
                    "initial_capital", "available_capital",
                    "invested_capital", "realized_proceeds",
                    "n_portfolio_firms", "sector_thesis",
                ])
                w.writeheader()
                for fund_id, fund in funds.items():
                    w.writerow({
                        "run_id": world_state.run_id,
                        "fund_id": fund.fund_id, "name": fund.name,
                        "strategy": fund.strategy,
                        "target_hurdle_rate": fund.target_hurdle_rate,
                        "horizon_years": fund.horizon_years,
                        "initial_capital": fund.initial_capital,
                        "available_capital": fund.available_capital,
                        "invested_capital": fund.invested_capital,
                        "realized_proceeds": fund.realized_proceeds,
                        "n_portfolio_firms": len(fund.portfolio),
                        "sector_thesis": fund.sector_thesis,
                    })
        # IPO prospectus markdowns
        prospectuses = getattr(world_state, "ipo_prospectuses", {}) or {}
        if prospectuses:
            prosp_dir = base / "prospectus"
            prosp_dir.mkdir(exist_ok=True)
            for fid, p in prospectuses.items():
                text = (
                    f"# IPO Prospectus — {fid}\n\n"
                    f"**Filed Q{p.filing_quarter} | Price range:** "
                    f"${p.price_range_low:.2f}–${p.price_range_high:.2f} | "
                    f"**Shares offered:** {p.shares_offered:,}\n\n"
                    f"**Final IPO price:** ${p.final_ipo_price:.2f}  "
                    f"**Amount raised:** ${p.final_amount_raised/1e6:.1f}M\n\n"
                    f"## Business Overview\n\n{p.business_overview}\n\n"
                    f"## Risk Factors\n\n{p.risk_factors}\n\n"
                    f"## MD&A\n\n{p.mdna}\n\n"
                    f"## Financial Projections\n\n{p.financial_projections}\n\n"
                    f"## Use of Proceeds\n\n{p.use_of_proceeds}\n"
                )
                (prosp_dir / f"{fid}_IPO.md").write_text(text, encoding="utf-8")

    # ── Director turnover (Wave theta) ──────────────────────────────────
    if world_state is not None:
        dt_events = getattr(world_state, "director_turnover", []) or []
        if dt_events:
            import csv as _csv
            with open(base / "director_turnover.csv", "w",
                       encoding="utf-8", newline="") as f:
                w = _csv.DictWriter(f, fieldnames=[
                    "event_quarter", "event_type", "director_id",
                    "director_name", "firm_id", "reason",
                ])
                w.writeheader()
                for e in dt_events:
                    w.writerow(e)

    # ── Crosswalk (Wave zeta: unified entity ID graph) ───────────────────
    # One row per entity (firm, ceo, director, facility, security, grant,
    # product). Key for researchers linking firm panels to security issuance,
    # executive compensation, debt contracts, products, etc.
    if world_state is not None:
        from .identifiers import build_crosswalk, CROSSWALK_COLUMNS
        crosswalk = build_crosswalk(world_state)
        _write_csv(base / "crosswalk.csv", CROSSWALK_COLUMNS, crosswalk)

    return base


def _write_wrds_datasets(base: Path, state, compustat_rows: list[CompustatRow]):
    """Write 7 WRDS-style datasets to the run folder.

    Each dataset is a CSV with canonical columns (see src/datasets.py).
    Empty datasets produce an empty CSV with only a header — so a
    researcher always knows what schema to expect.
    """
    _write_csv(base / "execucomp.csv",
               datasets.EXECUCOMP_COLUMNS,
               datasets.build_execucomp(state))

    # Stage 11: Two new ExecuComp-style datasets — Grants of Plan-Based
    # Awards (event-level, one row per new grant) and Outstanding Equity
    # Awards (annual snapshot of what CEO holds).
    _write_csv(base / "execucomp_grants.csv",
               datasets.EXECUCOMP_GRANTS_COLUMNS,
               datasets.build_execucomp_grants(state))
    _write_csv(base / "execucomp_outstanding.csv",
               datasets.EXECUCOMP_OUTSTANDING_COLUMNS,
               datasets.build_execucomp_outstanding(state))

    _write_csv(base / "audit_analytics.csv",
               datasets.AUDIT_ANALYTICS_COLUMNS,
               datasets.build_audit_analytics(state))

    _write_csv(base / "restatements.csv",
               datasets.RESTATEMENTS_COLUMNS,
               datasets.build_restatements(state))

    _write_csv(base / "analyst_forecasts.csv",
               datasets.ANALYST_FORECASTS_COLUMNS,
               datasets.build_analyst_forecasts(state))

    _write_csv(base / "management_forecasts.csv",
               datasets.MANAGEMENT_FORECASTS_COLUMNS,
               datasets.build_management_forecasts(state))

    _write_csv(base / "ceo_turnover.csv",
               datasets.CEO_TURNOVER_COLUMNS,
               datasets.build_ceo_turnover(state))

    # ── Debt datasets (Stage 3d — always written; empty when no facilities) ──
    _write_csv(base / "debt_facilities.csv",
               datasets.DEBT_FACILITIES_COLUMNS,
               datasets.build_debt_facilities(state))

    _write_csv(base / "debt_covenants.csv",
               datasets.DEBT_COVENANTS_COLUMNS,
               datasets.build_debt_covenants(state))

    _write_csv(base / "covenant_tests_panel.csv",
               datasets.COVENANT_TESTS_PANEL_COLUMNS,
               datasets.build_covenant_tests_panel(state))

    _write_csv(base / "covenant_violations.csv",
               datasets.COVENANT_VIOLATIONS_COLUMNS,
               datasets.build_covenant_violations(state))

    _write_csv(base / "bond_issuances.csv",
               datasets.BOND_ISSUANCES_COLUMNS,
               datasets.build_bond_issuances(state))

    # Stage 5 bad-debt events panel
    _write_csv(base / "bad_debt_events.csv",
               datasets.BAD_DEBT_EVENTS_COLUMNS,
               datasets.build_bad_debt_events(state))

    # Compustat funda-style annual fundamentals (mirrors WRDS comp.funda).
    # Always written; aggregates from compustat_q rows.
    _write_csv(base / "compustat_a.csv",
               datasets.COMPUSTAT_A_COLUMNS,
               datasets.build_compustat_a(state))

    # Annual reports (one row per firm × fiscal year, written at fqtr=4)
    _write_csv(base / "annual_reports.csv",
               datasets.ANNUAL_REPORTS_COLUMNS,
               datasets.build_annual_reports(state))

    # Stage 12: insider transactions (SEC Form 4-style) and activist
    # campaigns. Always written; empty when the toggles weren't active.
    _write_csv(base / "insider_transactions.csv",
               datasets.INSIDER_TRANSACTIONS_COLUMNS,
               datasets.build_insider_transactions(state))

    _write_csv(base / "activist_campaigns.csv",
               datasets.ACTIVIST_CAMPAIGNS_COLUMNS,
               datasets.build_activist_campaigns(state))

    # Compustat restated: same schema as compustat_q but with restated_flag = 1
    # where applicable. If no restatements occurred, it's identical to compustat_q.
    if compustat_rows:
        fieldnames = list(compustat_rows[0].as_dict().keys())
        with open(base / "compustat_restated.csv", "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for r in compustat_rows:
                d = r.as_dict()
                # If restated, use restated columns for the key public values
                if d.get("restatement_flag") == 1:
                    for base_col, restated_col in [
                        ("saleq", "saleq_restated"),
                        ("cogsq", "cogsq_restated"),
                        ("niq", "niq_restated"),
                        ("cheq", "cheq_restated"),
                        ("atq", "atq_restated"),
                        ("ltq", "ltq_restated"),
                        ("ceqq", "ceqq_restated"),
                        ("req", "req_restated"),
                        ("oancfq", "oancfq_restated"),
                    ]:
                        if d.get(restated_col) is not None:
                            d[base_col] = d[restated_col]
                writer.writerow(d)


def _write_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
    """Write rows to CSV. Always writes header, even if no rows."""
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for r in rows:
            writer.writerow(r)


def append_to_cross_run_db(
    data_dir: str,
    run_id: str,
    compustat_rows: list[CompustatRow],
    n_firms: int,
    n_quarters: int,
    seed: int,
    world_state=None,
):
    """Append this run's data to the cross-run accumulated database.

    Creates files:
    - data/compustat_all.csv: full quarterly panel from all runs (funda-q-style)
    - data/compustat_a_all.csv: annual fundamentals (funda-style) from all runs
    - data/run_index.csv: one row per run summary
    """
    data_path = Path(data_dir)
    data_path.mkdir(parents=True, exist_ok=True)

    # Append to compustat_all.csv (quarterly panel)
    all_panel = data_path / "compustat_all.csv"
    write_header = not all_panel.exists()
    if compustat_rows:
        fieldnames = list(compustat_rows[0].as_dict().keys())
        with open(all_panel, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            if write_header:
                writer.writeheader()
            for row in compustat_rows:
                writer.writerow(row.as_dict())

    # Append to compustat_a_all.csv (annual funda); requires world_state
    if world_state is not None:
        annual_rows = datasets.build_compustat_a(world_state)
        if annual_rows:
            annual_path = data_path / "compustat_a_all.csv"
            write_header_a = not annual_path.exists()
            with open(annual_path, "a", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=datasets.COMPUSTAT_A_COLUMNS,
                                          extrasaction="ignore")
                if write_header_a:
                    writer.writeheader()
                for r in annual_rows:
                    writer.writerow(r)

    # Append to run_index.csv
    run_index = data_path / "run_index.csv"
    write_header = not run_index.exists()

    # Compute summary stats
    if compustat_rows:
        total_rev = sum(r.saleq for r in compustat_rows)
        n_defaults = sum(1 for r in compustat_rows if r.default_flag == 1)
        last_rows = [r for r in compustat_rows
                     if r.fqtr == compustat_rows[-1].fqtr
                     and r.fyearq == compustat_rows[-1].fyearq]
        final_active = sum(1 for r in last_rows if r.default_flag == 0)
    else:
        total_rev = 0
        n_defaults = 0
        final_active = 0

    # Wave ν+9 Bug M2: canonical column order for run_index.csv. Previously
    # `fieldnames=list(row.keys())` derived the schema from the first row
    # written, so any new column added in a later run was silently dropped
    # via DictWriter's default extrasaction='ignore'. Pinning the column
    # list keeps the cross-run database stable as the runner evolves.
    RUN_INDEX_COLUMNS = [
        "run_id",
        "n_firms",
        "n_quarters",
        "seed",
        "total_industry_revenue",
        "n_defaults",
        "final_active_firms",
        "compustat_rows",
    ]

    row = {
        "run_id": run_id,
        "n_firms": n_firms,
        "n_quarters": n_quarters,
        "seed": seed,
        "total_industry_revenue": total_rev,
        "n_defaults": n_defaults,
        "final_active_firms": final_active,
        "compustat_rows": len(compustat_rows),
    }

    with open(run_index, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=RUN_INDEX_COLUMNS, extrasaction="ignore"
        )
        if write_header:
            writer.writeheader()
        writer.writerow(row)
