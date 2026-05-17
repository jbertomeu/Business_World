"""
CLI entry point for the LLM Firm Lab.

Usage:
  python -m src smoke --quarters 5 --seed 42          # mock agents
  python -m src run --quarters 5 --seed 42            # real LLM (DeepSeek)
  python -m src run --quarters 5 --seed 42 --mock     # mock agents via run command
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()  # load .env (API keys etc.)

from .types import FirmState, RawDecisions, SimParams, MacroState
from .config import RunConfig, LLMConfig, load_roster, ModelRoster
from .orchestrator import initialize_world, run_quarter, WorldState
from .demand import compute_demand_baseline
from .prompts import build_firm_prompt, build_environment_prompt
from .llm_backends import create_backend, extract_json, LLMBackend, MockBackend
from .board_discussion import (
    BoardMinutes, build_board_prompt, parse_board_minutes,
    format_minutes_for_decision_prompt,
)
from .output_organizer import organize_run_outputs, append_to_cross_run_db
from .memory import AgentMemory
from .world_secrets import generate_world_secrets
from .scoring import (
    compute_firm_scores, compute_debt_score, compute_pricing_score,
    RunScorecard, format_scorecard, save_scores,
)
from .equity_market import make_equity_market
from .investment_bank import make_investment_bank
from .commercial_bank import make_commercial_bank


def make_firm_agent(backends: dict[str, LLMBackend], last_flows: dict,
                    board_minutes_store: dict[str, BoardMinutes],
                    agent_memories: dict[str, AgentMemory],
                    state_ref: list | None = None,
                    earnings_management_enabled: bool = False,
                    debt_covenants_enabled: bool = False,
                    working_capital_decisions: bool = False,
                    bad_debt_enabled: bool = False,
                    restructuring_enabled: bool = False,
                    governance_enabled: bool = False,
                    legal_reserves_enabled: bool = False,
                    pension_enabled: bool = False,
                    data_broker=None):
    """Create a firm agent function that calls an LLM.
    Conducts a board discussion BEFORE making the decision.
    Uses AgentMemory for local accumulation (no redundant re-sends).
    state_ref is [WorldState] for accessing current run Compustat data."""

    def firm_agent(firm_id: str, firm: FirmState, public_info: dict,
                   params: SimParams) -> RawDecisions:
        # Wave θ: tag LLM calls inside this block with firm_id for cost
        # attribution in llm_calls.jsonl.
        from . import telemetry as _tel
        with _tel.set_role(firm_id):
            return _firm_agent_inner(firm_id, firm, public_info, params)

    def _firm_agent_inner(firm_id: str, firm: FirmState, public_info: dict,
                           params: SimParams) -> RawDecisions:
        backend = backends.get(firm_id, backends.get("default"))
        gazette = public_info.get("gazette", "")
        flows = last_flows.get(firm_id, {})
        own_private = public_info.get("own_private", {})
        rd_report = own_private.get("rd_report")
        brand_report = own_private.get("brand_report")

        # Get or create agent memory
        memory = agent_memories.get(firm_id)
        if memory is None:
            memory = AgentMemory(agent_id=firm_id)
            agent_memories[firm_id] = memory

        # Accumulate new data into local memory (not re-sent each Q)
        if gazette:
            memory.add_gazette(firm.quarter + 1, gazette)
        if rd_report:
            memory.add_reports(firm.quarter + 1, rd_report.summary,
                             brand_report.summary if brand_report else "")

        # ── Step 1: Board Discussion (separate LLM call) ──
        board_sys, board_user = build_board_prompt(
            firm, public_info, params, flows,
            rd_report, brand_report, memory, gazette,
            data_dir="data",
        )
        board_response = backend.complete(board_sys, board_user)

        # ── Step 1b: Check for ANALYSIS_REQUEST and run data analyst if needed ──
        if "ANALYSIS_REQUEST" in board_response:
            from .data_analyst import run_data_analysis
            # Extract analysis questions
            questions = _extract_analysis_request(board_response)
            if questions:
                # Get world state for Compustat export
                ws = None
                for ref_list in [agent_memories]:  # access state_ref via closure
                    pass
                # Use data_analyst model from roster
                from .config import LLMConfig, load_roster as _load_roster
                _roster = _load_roster()
                # Wave ν+9 Bug H4: optional role; bail out cleanly if absent.
                if _roster.data_analyst is None:
                    analyst_backend = None
                else:
                    analyst_llm = _roster.llm_config_for("data_analyst")
                    from .llm_backends import create_backend as _create_backend
                    analyst_backend = _create_backend(analyst_llm)

                if analyst_backend is not None:
                    # Get current run Compustat rows from state
                    current_rows = []
                    if state_ref and state_ref[0]:
                        current_rows = state_ref[0].compustat_rows

                    # Run analysis (separate data: current run vs all past runs)
                    analysis_report = run_data_analysis(
                        question="\n".join(questions),
                        current_run_rows=current_rows,
                        data_dir="data",
                        backend=analyst_backend,
                    )

                    # Continue board discussion with analysis results
                    continued_prompt = (
                        board_user + "\n\n"
                        "PREVIOUS BOARD DISCUSSION:\n" + board_response[:2000] + "\n\n"
                        "DATA ANALYST REPORT:\n" + analysis_report[:3000] + "\n\n"
                        "Continue the board discussion in light of this analysis. "
                        "Update your conclusions and business plan accordingly."
                    )
                    board_response = backend.complete(board_sys, continued_prompt)

        # ── Step 1c: Check for DATA_QUERY and consult the Data Broker ──
        if data_broker is not None:
            queries = _extract_data_queries(board_response)
            if queries:
                current_rows = []
                if state_ref and state_ref[0]:
                    current_rows = state_ref[0].compustat_rows
                q_num = state_ref[0].quarter if (state_ref and state_ref[0]) else 0
                answers = []
                for q in queries:
                    ans = data_broker.answer(
                        agent_role=firm_id,
                        query_text=q["question"],
                        hypothesis=q["hypothesis"],
                        current_run_rows=current_rows,
                        quarter=q_num,
                    )
                    answers.append(ans)
                # Re-prompt board with broker answers
                broker_section = "\n\n".join(answers)
                continued_prompt = (
                    board_user + "\n\n"
                    "PREVIOUS BOARD DISCUSSION:\n" + board_response[:2000] + "\n\n"
                    "DATA BROKER ANSWERS:\n" + broker_section[:3000] + "\n\n"
                    "Continue the board discussion using these data points. "
                    "Ground your conclusions in the numbers, or explicitly say why "
                    "you are going another direction."
                )
                board_response = backend.complete(board_sys, continued_prompt)

        minutes = parse_board_minutes(firm_id, firm.quarter + 1, board_response)
        board_minutes_store[firm_id] = minutes

        # Store board results in memory
        memory.add_board_minutes(
            firm.quarter + 1,
            consensus=minutes.consensus,
            action_items=minutes.action_items,
            forecast=minutes.forecast,
        )

        # ── Step 2: Decision (informed by board discussion) ──
        # Wave ν+12: render the firm's own full historical context
        # (compressed BS/IS/CF since inception, action log, cumulative
        # R&D/tenure, recent debriefs). Empty when no state_ref.
        firm_history = ""
        if state_ref and state_ref[0]:
            try:
                from .agent_history import render_firm_self_history
                firm_history = render_firm_self_history(
                    firm, state_ref[0], state_ref[0].macro,
                )
            except Exception:
                firm_history = ""

        system, user = build_firm_prompt(
            firm, public_info, params, flows, gazette, rd_report, brand_report,
            earnings_management_enabled=earnings_management_enabled,
            debt_covenants_enabled=debt_covenants_enabled,
            working_capital_decisions=working_capital_decisions,
            bad_debt_enabled=bad_debt_enabled,
            restructuring_enabled=restructuring_enabled,
            governance_enabled=governance_enabled,
            legal_reserves_enabled=legal_reserves_enabled,
            pension_enabled=pension_enabled,
            extended_history_block=firm_history,
        )
        # Append board minutes to the decision prompt
        board_context = format_minutes_for_decision_prompt(minutes)
        user = user + "\n\n" + board_context

        result = backend.complete_json(system, user)

        if result is None:
            # Fallback: carry-forward the firm's own prior-quarter decisions
            # (rather than generic hardcoded defaults). More emergent — when
            # the LLM dies after 5 retries, the firm "stays the course" on
            # its own recent behavior. Stamped with provenance so downstream
            # research can filter out non-LLM rows.
            print(f"  [{firm_id}] LLM failed, using carry-forward fallback")
            import uuid as _uuid
            # Pull prior-quarter flows for this firm if available
            prior_net_sales = float(flows.get("net_sales", 0.0)) if flows else 0.0
            prior_units = max(1, int(flows.get("units_sold", 0))) if flows else 1
            prior_rd = float(flows.get("rd_expense", 0.0)) if flows else 0.0
            prior_sga = float(flows.get("sga_expense", 0.0)) if flows else 0.0
            # Infer prior price from flows; else use a conservative default.
            if prior_net_sales > 0 and prior_units > 0:
                carried_price = prior_net_sales / prior_units
            else:
                carried_price = 95_000.0
            carried_production = max(1, prior_units) if prior_units > 1 else min(180, firm.capacity_units)
            carried_rd = prior_rd if prior_rd > 0 else 12_000_000.0
            carried_sga = prior_sga if prior_sga > 0 else 5_000_000.0
            return RawDecisions(
                price=carried_price,
                production=min(carried_production, firm.capacity_units),
                rd_spend=carried_rd,
                sga_spend=carried_sga,
                rd_allocation={"product": 0.6, "process": 0.25, "delivery": 0.15},
                decision_source="fallback",
                fallback_reason="LLM returned None (after retries); carry-forward from prior Q",
                proposal_id=str(_uuid.uuid4()),
            )

        def _opt_float(key):
            """Get optional float from LLM response; return None if missing/null."""
            v = result.get(key)
            if v is None:
                return None
            try:
                return float(v)
            except (TypeError, ValueError):
                return None

        import uuid as _uuid
        return RawDecisions(
            price=result.get("price", 95_000),
            production=int(result.get("production", 180)),
            capex=result.get("capex", 0),
            rd_spend=result.get("rd_spend", 12_000_000),
            rd_allocation=result.get("rd_allocation",
                                     {"product": 0.6, "process": 0.25, "delivery": 0.15}),
            sga_spend=result.get("sga_spend", 5_000_000),
            equity_issuance_request=result.get("equity_issuance_request", 0),
            debt_request=result.get("debt_request", 0),
            dividends=result.get("dividends", 0),
            buybacks=result.get("buybacks", 0),
            reasoning=result.get("reasoning", ""),
            deviation_justification=str(result.get("deviation_justification", "")),
            manipulation_amount=result.get("manipulation_amount", 0) if earnings_management_enabled else 0.0,
            proposal_id=str(_uuid.uuid4()),
            # Stage 4/5 optional decision fields (None → use params default / carry forward)
            payables_days_target=_opt_float("payables_days_target"),
            receivables_days_target=_opt_float("receivables_days_target"),
            deposit_pct=_opt_float("deposit_pct"),
            ppe_disposal=float(result.get("ppe_disposal", 0) or 0),
            allowance_pct_of_ar=_opt_float("allowance_pct_of_ar"),
            # Stage 10 restructuring fields (0 if toggle off / not chosen)
            restructuring_severance=float(result.get("restructuring_severance", 0) or 0),
            restructuring_ppe_impairment=float(result.get("restructuring_ppe_impairment", 0) or 0),
            restructuring_inventory_write_off=float(result.get("restructuring_inventory_write_off", 0) or 0),
            restructuring_goodwill_impairment=float(result.get("restructuring_goodwill_impairment", 0) or 0),
            ceo_sell_shares=int(result.get("ceo_sell_shares", 0) or 0),
            # Stage 12 decisions
            ceo_exercise_options=int(result.get("ceo_exercise_options", 0) or 0),
            legal_reserve_change=float(result.get("legal_reserve_change", 0) or 0),
            legal_settlements_paid=float(result.get("legal_settlements_paid", 0) or 0),
            pension_contribution=float(result.get("pension_contribution", 0) or 0),
            # Activist campaign response (when a campaign is pending). The
            # orchestrator writes this back onto the campaign dict in
            # state.activist_campaigns after clamping.
            activist_response=(result.get("activist_response")
                                if isinstance(result.get("activist_response"), dict)
                                else None),
        )

    return firm_agent


def _extract_analysis_request(board_response: str) -> list[str]:
    """Extract analysis questions from board discussion response."""
    questions = []
    in_request = False
    for line in board_response.split("\n"):
        if "ANALYSIS_REQUEST" in line.upper():
            in_request = True
            continue
        if in_request:
            stripped = line.strip()
            if stripped.startswith("-") or stripped.startswith("*") or stripped.startswith("•"):
                questions.append(stripped.lstrip("-*• "))
            elif stripped and not any(h in stripped.upper() for h in ["PART", "CEO", "CFO", "COO", "CONSENSUS", "FORECAST"]):
                questions.append(stripped)
            elif not stripped:
                if questions:
                    break
    return questions


def _extract_data_queries(response: str) -> list[dict]:
    """Extract DATA_QUERY blocks from a response.

    Format expected:
      DATA_QUERY:
      QUESTION: <text>
      HYPOTHESIS: <text>
    Multiple blocks allowed. Returns list of dicts.
    """
    queries = []
    lines = response.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.upper().startswith("DATA_QUERY"):
            question = ""
            hypothesis = ""
            j = i + 1
            while j < len(lines) and j < i + 10:  # look ahead at most 10 lines
                s = lines[j].strip()
                if s.upper().startswith("QUESTION:"):
                    question = s.split(":", 1)[1].strip()
                elif s.upper().startswith("HYPOTHESIS:"):
                    hypothesis = s.split(":", 1)[1].strip()
                elif s.upper().startswith("DATA_QUERY"):
                    break
                j += 1
            if question:
                queries.append({"question": question, "hypothesis": hypothesis})
            i = j
        else:
            i += 1
    return queries


def make_env_agent(backend: LLMBackend, state_ref: list, world_secrets: str = "",
                   earnings_management_enabled: bool = False,
                   working_capital_decisions: bool = False,
                   bad_debt_enabled: bool = False,
                   env_decision_overrides_enabled: bool = False,
                   regional_markets_enabled: bool = True):
    """Create an environment agent function that calls an LLM.
    state_ref is a mutable list holding [WorldState] so env can access reports.
    world_secrets is the hidden context ONLY the environment sees.
    earnings_management_enabled: when True, env sees firm manipulation state and
    decides detection tips for SEC (replaces hardcoded sigmoid detection).
    """

    def env_agent(actions, firms, macro, params, validator_notes: str = ""):
        # Compute baseline for guidance
        baseline = compute_demand_baseline(firms, actions, macro, params)

        # Get operational reports from world state
        world_state = state_ref[0] if state_ref else None
        rd_reports = world_state.rd_reports if world_state else None
        brand_reports = world_state.brand_reports if world_state else None

        # Wave ι: pass scenario's industry character so env calibrates to it
        scenario = getattr(world_state, "_scenario", None) if world_state else None
        industry_character_dict = {}
        if scenario is not None and getattr(scenario, "industry_character", None):
            ic = scenario.industry_character
            industry_character_dict = {
                "narrative": ic.narrative,
                "label": ic.label,
                "tam_at_maturity_usd": ic.tam_at_maturity_usd,
                "years_to_maturity": ic.years_to_maturity,
            }
        # Wave ν+5: pull most-recent demand-calibrator estimate from state
        calibrator_est = getattr(world_state, "demand_calibrator_last", None) if world_state else None

        # Wave ν+12: render the comprehensive history block (cross-firm
        # Compustat with compression, per-firm action log, cumulative R&D,
        # capital raises, M&A/default events, prior env debrief notes).
        # Empty string if no world_state (mock paths).
        extended_history = ""
        if world_state is not None:
            try:
                from .agent_history import render_environment_full_history
                extended_history = render_environment_full_history(world_state, macro)
            except Exception:
                extended_history = ""

        system, user = build_environment_prompt(
            firms=firms,
            actions=actions,
            macro=macro,
            baseline_demand=baseline.total_demand,
            baseline_shares=baseline.firm_shares,
            params=params,
            rd_reports=rd_reports,
            brand_reports=brand_reports,
            data_dir="data",
            earnings_management_enabled=earnings_management_enabled,
            compustat_rows=(world_state.compustat_rows if world_state else None),
            working_capital_decisions=working_capital_decisions,
            bad_debt_enabled=bad_debt_enabled,
            env_decision_overrides_enabled=env_decision_overrides_enabled,
            industry_character=industry_character_dict,
            demand_calibrator_estimate=calibrator_est,
            regional_markets_enabled=regional_markets_enabled,
            extended_history_block=extended_history,
        )

        # Inject world secrets into system prompt (env only)
        if world_secrets:
            system = system + "\n\n" + world_secrets

        # Wave ν+11 E9: if a second-env validator sent the previous output back
        # with notes, append those notes to the user prompt so env-1 can fix
        # the specific inconsistency on this retry.
        if validator_notes:
            user = user + (
                "\n\n=== VALIDATOR FEEDBACK ON YOUR PRIOR ATTEMPT ===\n"
                f"{validator_notes}\n"
                "Regenerate the market resolution. Address the validator's "
                "concern but otherwise keep your output structure identical."
            )

        result = backend.complete_json(system, user)

        if result is None:
            print("  [env] LLM failed, using deterministic fallback")
            return None  # orchestrator will use fallback

        # Convert to the format orchestrator expects
        firm_outcomes = {}
        for fo in result.get("firm_outcomes", []):
            fid = fo.get("firm_id", "")
            firm_outcomes[fid] = fo

        return {
            "total_demand": result.get("total_demand", baseline.total_demand),
            "firm_outcomes": firm_outcomes,
            "narrative": result.get("narrative", ""),
            "detection_tips": result.get("detection_tips", []),
        }

    return env_agent


def mock_firm_agent(firm_id: str, firm: FirmState, public_info: dict,
                    params: SimParams) -> RawDecisions:
    """Deterministic mock: vary by firm index.

    Stamped `decision_source="mock"` so research panels can filter out
    these rows (they carry no behavioral content from a real LLM).
    """
    idx = int(firm_id.split("_")[-1]) if "_" in firm_id else 0
    import uuid as _uuid
    return RawDecisions(
        price=92_000 + idx * 2_000,
        production=min(firm.capacity_units, 190 + idx * 10),
        capex=5_000_000,
        rd_spend=15_000_000 + idx * 2_000_000,
        rd_allocation={"product": 0.6, "process": 0.25, "delivery": 0.15},
        sga_spend=8_000_000 + idx * 1_000_000,
        dividends=0,
        buybacks=0,
        decision_source="mock",
        fallback_reason="deterministic mock agent (--mock flag)",
        proposal_id=str(_uuid.uuid4()),
    )


def run_simulation(config: RunConfig, use_mock: bool = False,
                    restart_from: str | None = None):
    """Run a complete simulation.

    If `restart_from` is given, WorldState is loaded from the snapshot
    instead of being freshly initialized. `config.n_quarters` then means
    "run this many MORE quarters past the snapshot quarter", not total.
    """

    run_id = config.run_id or f"run_{int(time.time())}"
    # Wave θ: start with a clean telemetry slate per-run (the process may
    # run back-to-back runs in batch_runner.py). Optionally fetch pricing
    # table once at run start for $ estimates.
    from . import telemetry as _tel
    _tel.reset()
    if getattr(config, "cost_telemetry_enabled", True):
        _tel.fetch_pricing_openrouter()
    n_quarters = config.n_quarters
    n_firms = config.n_firms_initial
    # Stage 12: copy feature toggles from config → params so accounting.py
    # can gate math purely off SimParams (no config import in accounting).
    from dataclasses import replace as _dc_replace
    params = _dc_replace(
        config.sim_params,
        legal_reserves_enabled=getattr(config, "legal_reserves_enabled", False),
        pension_enabled=getattr(config, "pension_enabled", False),
        deferred_taxes_enabled=getattr(config, "deferred_taxes_enabled", False),
        noisy_signals_enabled=getattr(config, "noisy_signals_enabled", False),
        noisy_signals_sd=getattr(config, "noisy_signals_sd", 0.05),
    )

    print(f"LLM Firm Lab: {n_firms} firms, {n_quarters} quarters, seed={config.seed}")
    print(f"Run ID: {run_id}")
    print(f"Mode: {'MOCK' if use_mock else f'LLM ({config.default_llm.model})'}")
    print()

    # Initialize world — either fresh, or restored from a snapshot.
    if restart_from:
        from .snapshots import restore_world
        print(f"Restarting from snapshot: {restart_from}")
        state = restore_world(restart_from)
        # Wave ν+2: KEEP the snapshot's run_id so subsequent snapshots
        # + outputs land in the SAME run directory as the original run.
        # Previously we overwrote with a new run_id, fragmenting outputs
        # and breaking supervisor-based auto-restart (couldn't find
        # snapshots from prior attempt).
        run_id = state.run_id
        print(f"  Resumed at quarter {state.quarter} with "
              f"{sum(1 for f in state.firms.values() if f.is_active)} active firms"
              f" (run_id preserved: {run_id})")
    else:
        # Wave zeta: load scenario YAML if config.scenario is set.
        scenario = None
        if getattr(config, "scenario", None):
            from .scenarios import load_scenario
            scenario_path = Path("scenarios") / f"{config.scenario}.yaml"
            if scenario_path.exists():
                scenario = load_scenario(scenario_path)
                print(f"Scenario loaded: {scenario.name} — {len(scenario.firms)} firm foundings")
            else:
                print(f"WARN: scenario '{config.scenario}' not found at {scenario_path}; "
                      f"using uniform default")
        # Wave ν+2: when endogenous_entry is on, only the initial cohort
        # is populated at Q1; the rest enter via _run_entry_phase.
        endo_entry = getattr(config, "endogenous_entry_enabled", False)
        if endo_entry:
            cfg_cohort = int(getattr(config, "endogenous_initial_cohort", 0) or 0)
            if cfg_cohort <= 0:
                cfg_cohort = max(3, n_firms // 4)
            initial_cohort = min(n_firms, cfg_cohort)
        else:
            initial_cohort = n_firms
        # Wave ν+12: allow n_firms_max to be set independently of
        # n_firms_initial so the entry judge isn't artificially capped at
        # the initial cohort size. If config.n_firms_max is unset or
        # smaller than n_firms_initial, fall back to n_firms_initial.
        n_firms_max_cfg = max(getattr(config, "n_firms_max", n_firms) or n_firms, n_firms)
        state = initialize_world(
            n_firms, params, config.seed, run_id,
            scenario=scenario,
            directors_enabled=getattr(config, "directors_enabled", True),
            pe_lifecycle_enabled=getattr(config, "pe_lifecycle_enabled", False),
            initial_cohort=initial_cohort,
            regional_markets_enabled=getattr(config, "regional_markets_enabled", True),
            n_firms_max=n_firms_max_cfg,
        )
        if endo_entry:
            print(f"  endogenous_entry: ON (initial cohort {initial_cohort} of "
                  f"max {n_firms_max_cfg}; remaining slots fill via entry judge)")
        regional_on = getattr(config, "regional_markets_enabled", True)
        print(f"  regional_markets: {'ON' if regional_on else 'OFF'} "
              f"({'firms get geographic/segment niches' if regional_on else 'homogeneous market — no horizontal differentiation'})")

    # Create agent functions
    last_flows: dict[str, dict] = {}
    board_minutes_store: dict = {}
    agent_memories: dict[str, AgentMemory] = {}  # per-firm local memory

    # Generate world secrets (hidden env context)
    secrets_category = getattr(config, 'secrets_category', 'baseline')
    world_secrets = generate_world_secrets(config.seed, n_firms, n_quarters, secrets_category)
    print(f"World secrets generated: category={secrets_category}")

    # ── Load model roster (config/model_roster.yaml) ──────────────────────
    roster = load_roster()
    print(f"\nModel roster loaded from config/model_roster.yaml")

    eq_fn = None    # equity market agent
    ib_fn = None    # investment bank agent
    cb_fn = None    # commercial bank agent
    broker = None   # data broker (optional)
    violation_resolver = None  # Stage 3c covenant violation resolver (LLM mode only)

    # Wave ν+14e: wrap every LLM-call site with a BackupBackend chain so
    # persistent failures of a primary model fall through to a backup
    # rather than silently producing None and letting the simulation
    # move forward with a missing decision. Per user direction: "NEVER
    # move forward if missing, just move to next AI if repeated failure".
    from .llm_backends import BackupBackend, build_default_backup_pool
    def _wrap_backups(backend, model_name: str = "", role_tag: str = ""):
        """Wrap a backend with the default backup pool.
        If pool is empty (no API key etc.) returns the unwrapped primary.
        Excludes `model_name` from the pool to avoid duplicating the primary.
        """
        try:
            backups = build_default_backup_pool(role_tag=role_tag,
                                                  exclude_model=model_name or "")
        except Exception:
            backups = []
        if not backups:
            return backend
        return BackupBackend(backend, backups, role_tag=role_tag)

    if use_mock:
        firm_fn = mock_firm_agent
        env_fn = None
    else:
        # Create per-firm LLM backends from roster.
        # Roster uses firm_1..firm_N; simulation uses firm_0..firm_{N-1} internally.
        # With --firms 5: sim firm_0 → roster firm_1, ..., sim firm_4 → roster firm_5.
        #
        # Wave ν+14 bug fix: build backends for ALL slots up to n_firms_max,
        # not just n_firms_initial. Run-6 evidence: with n_firms_initial=6
        # and n_firms_max=20, entry-judge spawned firms 6-19, none of which
        # had a backend, so pitch_fn silently returned None for them every
        # quarter (1100+ "pitch LLM failed" messages in run-6 — these were
        # NOT LLM call failures, they were dispatcher lookup misses). All
        # 14 entrants stayed dormant for the full 80-quarter run.
        n_backend_slots = max(
            int(n_firms),
            int(getattr(config, "n_firms_max", n_firms) or n_firms),
        )
        backends = {}
        roster_firm_ids = roster.firm_ids()  # ["firm_1", "firm_2", ...]
        n_roster = len(roster_firm_ids)
        for i in range(n_backend_slots):
            sim_fid = f"firm_{i}"           # internal sim ID (firm_0, firm_1, ...)

            # Config YAML agent overrides take precedence over roster
            override = config.agent_llm_overrides.get(sim_fid, {})
            if override.get("model"):
                llm = LLMConfig(
                    backend=override.get("backend", "openrouter"),
                    model=override["model"],
                    temperature=override.get("temperature", 0.3 + i * 0.05),
                )
                source = "config override"
            else:
                roster_idx = i % n_roster
                roster_fid = roster_firm_ids[roster_idx]
                llm = roster.llm_config_for(roster_fid)
                if i >= n_roster:
                    llm.temperature = 0.3 + (i * 0.05)
                source = f"roster {roster_fid}"

            # Wave ν+10: wrap firm backends with role-tag (which now also
            # wraps with LoggingBackend) so per-firm prompts are captured
            # on logged quarters.
            from .telemetry import tag_backend as _firm_tag
            backends[sim_fid] = _firm_tag(
                _wrap_backups(create_backend(llm), llm.model, sim_fid),
                sim_fid,
            )
            print(f"  {sim_fid} <- {source}: {llm.model} [{llm.backend}] "
                  f"(temp={llm.temperature:.2f})")

        # Environment agent
        env_llm = roster.llm_config_for("environment")
        from .telemetry import tag_backend as _tag_env
        env_backend = _tag_env(
            _wrap_backups(create_backend(env_llm), env_llm.model, "environment"),
            "environment",
        )
        print(f"  environment: {env_llm.model} [{env_llm.backend}] (temp={env_llm.temperature:.2f})")

        # state_ref allows env agent to access reports from world state
        state_ref = [None]  # mutable container, updated each quarter

        # ── Data Broker (optional, shared across all agents that query it) ──
        if config.data_broker_enabled and roster.data_broker:
            from .data_broker import DataBroker, BROKER_MODES
            if config.data_broker_mode not in BROKER_MODES:
                raise ValueError(
                    f"Invalid data_broker_mode '{config.data_broker_mode}'. "
                    f"Must be one of {BROKER_MODES}."
                )
            broker_llm = roster.llm_config_for("data_broker")
            broker = DataBroker(
                backend=_wrap_backups(create_backend(broker_llm), broker_llm.model, "data_broker"),
                data_dir=config.data_dir,
                enforce_hypothesis=True,
                max_queries_per_agent_per_quarter=config.data_broker_max_queries_per_agent_per_quarter,
                mode=config.data_broker_mode,
            )
            print(f"  data_broker: {broker_llm.model} [{broker_llm.backend}] "
                  f"mode={config.data_broker_mode} "
                  f"(max {config.data_broker_max_queries_per_agent_per_quarter} queries/agent/Q)")

        firm_fn = make_firm_agent(backends, last_flows, board_minutes_store, agent_memories, state_ref,
                                  earnings_management_enabled=config.earnings_management_enabled,
                                  debt_covenants_enabled=getattr(config, "debt_covenants_enabled", False),
                                  working_capital_decisions=getattr(config, "working_capital_decisions", False),
                                  bad_debt_enabled=getattr(config, "bad_debt_enabled", False),
                                  restructuring_enabled=getattr(config, "restructuring_enabled", False),
                                  governance_enabled=getattr(config, "governance_enabled", False),
                                  legal_reserves_enabled=getattr(config, "legal_reserves_enabled", False),
                                  pension_enabled=getattr(config, "pension_enabled", False),
                                  data_broker=broker)
        env_fn = make_env_agent(env_backend, state_ref, world_secrets,
                                 earnings_management_enabled=config.earnings_management_enabled,
                                 working_capital_decisions=getattr(config, "working_capital_decisions", False),
                                 bad_debt_enabled=getattr(config, "bad_debt_enabled", False),
                                 env_decision_overrides_enabled=getattr(config, "env_decision_overrides_enabled", False),
                                 regional_markets_enabled=getattr(config, "regional_markets_enabled", True))

        # Financial institution agents (all from roster).
        # Wave θ: wrap each backend via `tag_backend(role)` so every LLM
        # call inside the factory is tagged in llm_calls.jsonl.
        from .telemetry import tag_backend as _tag

        # Wave ν+8: equity market is now a PANEL of valuators. The orchestrator
        # gives all panel members the same prompt (with rolling price history
        # and recent management guidance for anchoring) and takes the per-firm
        # median price. This is robust to single-LLM hallucinations (e.g. a
        # firm's price spiking to 6× prior on weak fundamentals — we observed
        # that in earlier runs) without imposing any quantitative ceiling on
        # period-to-period moves.
        #
        # Roster lookup: prefer "equity_market_panel_<i>" for i in 1..N if
        # configured; otherwise fall back to a 3-LLM panel using the firm
        # backends (cycling through distinct models in the roster) so we
        # automatically get model diversity. If only one model is available,
        # the panel collapses to a single backend (legacy behaviour).
        from .config import LLMConfig as _LLMC
        panel_backends = []
        # Try explicit panel config first
        for i in range(1, 6):
            try:
                cfg = roster.llm_config_for(f"equity_market_panel_{i}")
                panel_backends.append(_tag(
                    _wrap_backups(create_backend(cfg), cfg.model, f"equity_market_panel_{i}"),
                    f"equity_market_panel_{i}",
                ))
            except Exception:
                break
        if not panel_backends:
            # Default: build a 3-model panel by cycling through distinct firm
            # models (the firms already use a rotating mix). If fewer than 3
            # distinct models available, still produces a usable panel.
            seen_models = set()
            firm_cfgs = []
            for fid in [f"firm_{i}" for i in range(20)]:
                try:
                    cfg = roster.llm_config_for(fid)
                except Exception:
                    continue
                key = (cfg.backend, cfg.model)
                if key not in seen_models:
                    seen_models.add(key)
                    firm_cfgs.append(cfg)
                    if len(firm_cfgs) >= 3:
                        break
            if not firm_cfgs:
                # Final fallback: single equity_market backend (legacy)
                eq_llm = roster.llm_config_for("equity_market")
                panel_backends = [_tag(
                    _wrap_backups(create_backend(eq_llm), eq_llm.model, "equity_market"),
                    "equity_market",
                )]
                eq_models_str = f"{eq_llm.model}"
            else:
                # Use a low temperature for valuation (still some variation
                # via different models, not chaotic temperature variance).
                for i, cfg in enumerate(firm_cfgs):
                    panel_cfg = _LLMC(
                        backend=cfg.backend, model=cfg.model,
                        api_key_env=cfg.api_key_env,
                        temperature=0.20,
                        host=cfg.host,
                        max_retries=cfg.max_retries,
                        timeout_seconds=cfg.timeout_seconds,
                    )
                    panel_backends.append(
                        _tag(
                            _wrap_backups(create_backend(panel_cfg), panel_cfg.model,
                                            f"equity_market_panel_{i+1}"),
                            f"equity_market_panel_{i+1}",
                        )
                    )
                eq_models_str = ", ".join(c.model for c in firm_cfgs)
        else:
            eq_models_str = f"{len(panel_backends)} panel models from roster"
        eq_fn = make_equity_market(panel_backends, state_ref)
        print(f"  equity_market: PANEL of {len(panel_backends)} valuators "
              f"({eq_models_str}); per-firm MEDIAN price taken")

        # Wave ν+10 item 7: assemble investment-bank panel (1 or 2 banks).
        ib_llm = roster.llm_config_for("investment_bank")
        ib_agents = [make_investment_bank(
            _tag(_wrap_backups(create_backend(ib_llm), ib_llm.model, "investment_bank"), "investment_bank"), state_ref,
            debt_covenants_enabled=getattr(config, "debt_covenants_enabled", False),
        )]
        ib_names = ["ibank_1"]
        if roster.investment_bank_2 is not None:
            ib2_llm = roster.llm_config_for("investment_bank_2")
            ib_agents.append(make_investment_bank(
                _tag(_wrap_backups(create_backend(ib2_llm), ib2_llm.model, "investment_bank_2"), "investment_bank_2"), state_ref,
                debt_covenants_enabled=getattr(config, "debt_covenants_enabled", False),
            ))
            ib_names.append("ibank_2")
        if len(ib_agents) > 1:
            from .investment_bank import make_investment_bank_panel
            ib_fn = make_investment_bank_panel(ib_agents, names=ib_names)
            print(f"  investment_bank: PANEL of {len(ib_agents)} "
                  f"({ib_llm.model}, {ib2_llm.model})"
                  + (" +covenants" if getattr(config, "debt_covenants_enabled", False) else ""))
        else:
            ib_fn = ib_agents[0]
            print(f"  investment_bank: {ib_llm.model} [{ib_llm.backend}] (temp={ib_llm.temperature:.2f})"
                  + (" +covenants" if getattr(config, "debt_covenants_enabled", False) else ""))

        # Commercial-bank panel (1 or 2 banks).
        cb_llm = roster.llm_config_for("commercial_bank")
        cb_agents = [make_commercial_bank(_tag(_wrap_backups(create_backend(cb_llm), cb_llm.model, "commercial_bank"), "commercial_bank"), state_ref)]
        cb_names = ["cbank_1"]
        if roster.commercial_bank_2 is not None:
            cb2_llm = roster.llm_config_for("commercial_bank_2")
            cb_agents.append(make_commercial_bank(
                _tag(_wrap_backups(create_backend(cb2_llm), cb2_llm.model, "commercial_bank_2"), "commercial_bank_2"), state_ref,
            ))
            cb_names.append("cbank_2")
        if len(cb_agents) > 1:
            from .commercial_bank import make_commercial_bank_panel
            cb_fn = make_commercial_bank_panel(cb_agents, names=cb_names)
            print(f"  commercial_bank: PANEL of {len(cb_agents)} "
                  f"({cb_llm.model}, {cb2_llm.model})")
        else:
            cb_fn = cb_agents[0]
            print(f"  commercial_bank: {cb_llm.model} [{cb_llm.backend}] (temp={cb_llm.temperature:.2f})")

        # Emergency bridge lender — reuses commercial bank backend, distinct prompt
        from .commercial_bank import make_emergency_bridge, make_violation_resolver
        bridge_fn = make_emergency_bridge(_tag(_wrap_backups(create_backend(cb_llm), cb_llm.model, "emergency_bridge"), "emergency_bridge"), state_ref)
        print(f"  emergency_bridge: {cb_llm.model} (LLM-judged distressed lending rate)")

        # Covenant violation resolver (reuses commercial bank backend)
        violation_resolver = None
        if getattr(config, "debt_covenants_enabled", False):
            violation_resolver = make_violation_resolver(_tag(_wrap_backups(create_backend(cb_llm), cb_llm.model, "violation_resolver"), "violation_resolver"))
            print(f"  violation_resolver: {cb_llm.model} (covenant waive/amend/accelerate)")

    # ── Wire expansion agents (v0.5, all None when toggles off) ──────────
    ma_fn = None
    sec_fn_agent = None
    ea_fn = None
    analyst_fns = None
    activist_fn = None
    audit_fn = None
    gov_fn = None
    annual_report_fn = None
    env_verifier_fn = None
    env_validator_fn = None
    investor_voice_fn = None
    firm_debrief_fn = None
    env_debrief_fn = None
    intermediary_debrief_fns = None
    planning_fn = None
    pitch_fn = None
    pe_eval_fns = None
    ipo_decision_fn = None
    prospectus_fn = None
    if use_mock:
        bridge_fn = None

    if not use_mock:
        # M&A — Wave ν+3: reverted to per-firm bidder model. Each
        # entrepreneur evaluates targets and proposes a bid based on
        # their own valuation, perspective, and strategic logic. The
        # env-judged variant (ν+2) was rapacious — it serially rolled
        # up entrants at fire-sale prices, defeating endogenous entry.
        # Per-firm bidding restores agency to the would-be acquirers.
        if config.ma_enabled:
            from .ma_agent import make_ma_agent, make_ma_regulator
            # Wave ν+11: wire a regulator that uses the env backend (the
            # env IS the antitrust regulator from the firms' perspective).
            ma_regulator_fn = make_ma_regulator(
                _tag_env(_wrap_backups(create_backend(env_llm), env_llm.model, "ma_regulator"), "ma_regulator"), state_ref,
            )
            ma_fn = make_ma_agent(backends, state_ref,
                                    regulator_fn=ma_regulator_fn)
            print("  ma_agent: ON (per-firm bidder model)")

        # SEC
        if config.sec_enabled and roster.sec:
            from .sec_agent import make_sec_agent
            sec_llm = roster.llm_config_for("sec")
            sec_fn_agent = make_sec_agent(_tag(_wrap_backups(create_backend(sec_llm), sec_llm.model, "sec"), "sec"), state_ref, data_broker=broker)
            print(f"  sec: {sec_llm.model} [{sec_llm.backend}]"
                  + (" (+broker)" if broker else ""))

        # Earnings announcement (reuses firm backends)
        if config.earnings_announcement_enabled:
            from .earnings_announcement import make_earnings_announcer
            ea_fn = make_earnings_announcer(backends, state_ref)
            print("  earnings_announcement: ON (using firm backends)")

        # Annual reports (10-K, reuses firm backends — annual at fqtr=4)
        if getattr(config, "annual_reports_enabled", False):
            from .annual_report import make_annual_report_generator
            annual_report_fn = make_annual_report_generator(backends, state_ref)
            print("  annual_report: ON (using firm backends, annual at fqtr=4)")

        # Environment output verifier (called only when anomaly detected)
        if getattr(config, "env_verification_enabled", False):
            from .env_verifier import make_env_verifier
            # Use env_verifier role from roster if defined, else fall back to env model
            try:
                ev_llm = roster.llm_config_for("env_verifier")
                if ev_llm is None:
                    ev_llm = roster.llm_config_for("environment")
            except Exception:
                ev_llm = roster.llm_config_for("environment")
            env_verifier_fn = make_env_verifier(_tag(_wrap_backups(create_backend(ev_llm), ev_llm.model, "env_verifier"), "env_verifier"))
            print(f"  env_verifier: {ev_llm.model} [{ev_llm.backend}] "
                  f"(called only on anomaly trigger)")

        # Wave ν+11 E9: independent second-env validator. Separate from the
        # verifier above (which uses deterministic anomaly heuristics + direct
        # rewrite). The validator runs every quarter, asks a second env if the
        # output is consistent, and on send_back triggers env-1 to retry once
        # with notes appended.
        if getattr(config, "env_validator_enabled", False):
            from .env_verifier import make_env_validator
            try:
                evd_llm = roster.llm_config_for("env_validator")
                if evd_llm is None:
                    evd_llm = roster.llm_config_for("environment")
            except Exception:
                evd_llm = roster.llm_config_for("environment")
            env_validator_fn = make_env_validator(_tag(_wrap_backups(create_backend(evd_llm), evd_llm.model, "env_validator"), "env_validator"))
            print(f"  env_validator: {evd_llm.model} [{evd_llm.backend}] "
                  f"(every quarter, high bar; one retry on send_back)")

        # Wave ν+12: investor voice — per-firm market-analyst commentary
        # delivered after each quarter, rendered in next quarter's firm
        # decision prompt.
        if getattr(config, "investor_voice_enabled", False):
            from .investor_voice import make_investor_voice
            try:
                iv_llm = roster.llm_config_for("investor_voice")
                if iv_llm is None:
                    iv_llm = roster.llm_config_for("data_analyst")
            except Exception:
                iv_llm = roster.llm_config_for("data_analyst")
            investor_voice_fn = make_investor_voice(
                _tag(_wrap_backups(create_backend(iv_llm), iv_llm.model, "investor_voice"), "investor_voice"), state_ref,
            )
            print(f"  investor_voice: {iv_llm.model} [{iv_llm.backend}] "
                  f"(per active firm per quarter; soft market view)")

        # Wave ν+12: per-quarter debrief writers (firm + env + intermediaries).
        # Single cheap backend reused across all roles; the writer factory just
        # wraps it with role-specific prompts. Toggle: debriefs_enabled (default ON).
        firm_debrief_fn = None
        env_debrief_fn = None
        intermediary_debrief_fns = None
        if getattr(config, "debriefs_enabled", True):
            from .debriefs import (
                make_firm_debrief_writer, make_env_debrief_writer,
                make_intermediary_debrief_writer,
            )
            try:
                dbr_llm = roster.llm_config_for("debrief")
                if dbr_llm is None:
                    dbr_llm = roster.llm_config_for("data_analyst")
            except Exception:
                dbr_llm = roster.llm_config_for("data_analyst")
            dbr_backend = _tag(_wrap_backups(create_backend(dbr_llm), dbr_llm.model, "debrief"), "debrief")
            firm_debrief_fn = make_firm_debrief_writer(dbr_backend)
            env_debrief_fn = make_env_debrief_writer(dbr_backend)
            intermediary_debrief_fns = {
                "pe": make_intermediary_debrief_writer(dbr_backend, "pe"),
                "bank": make_intermediary_debrief_writer(dbr_backend, "bank"),
                "ibank": make_intermediary_debrief_writer(dbr_backend, "ibank"),
                "activist": make_intermediary_debrief_writer(dbr_backend, "activist"),
                "auditor": make_intermediary_debrief_writer(dbr_backend, "auditor"),
                "sec": make_intermediary_debrief_writer(dbr_backend, "sec"),
            }
            print(f"  debriefs: {dbr_llm.model} [{dbr_llm.backend}] "
                  f"(per-firm + env + 6 intermediary roles each Q)")

        # Sell-side analysts
        if config.sellside_analysts_enabled and roster.analysts:
            from .sellside_analyst import make_sellside_analyst
            analyst_fns = []
            for aid in sorted(roster.analysts.keys()):
                a_llm = roster.llm_config_for(aid)
                a_fn = make_sellside_analyst(
                    _tag(_wrap_backups(create_backend(a_llm), a_llm.model, aid), aid),
                    aid, state_ref, data_broker=broker,
                )
                analyst_fns.append(a_fn)
                print(f"  {aid}: {a_llm.model} [{a_llm.backend}]"
                      + (" (+broker)" if broker else ""))

        # Activist investor (uses firm backends — reuses available models)
        if getattr(config, "activist_investors_enabled", False):
            from .activist import make_activist_agent
            # Use equity_market role (public-info-only agent); falls back to
            # environment if equity_market not configured.
            try:
                act_llm = roster.llm_config_for("equity_market")
            except Exception:
                act_llm = roster.llm_config_for("environment")
            activist_fn = make_activist_agent(_tag(_wrap_backups(create_backend(act_llm), act_llm.model, "activist"), "activist"), state_ref)
            print(f"  activist: {act_llm.model} [{act_llm.backend}]")

        # Auditor (annual Q4 only)
        if config.auditor_enabled and roster.auditors:
            from .auditor import make_auditor_pool
            auditor_backends = {}
            for aud_id in sorted(roster.auditors.keys()):
                aud_llm = roster.llm_config_for(aud_id)
                auditor_backends[aud_id] = _tag(
                    _wrap_backups(create_backend(aud_llm), aud_llm.model, aud_id),
                    aud_id,
                )
                print(f"  {aud_id}: {aud_llm.model} [{aud_llm.backend}] (annual)")
            audit_fn = make_auditor_pool(auditor_backends, state_ref)

        # Board governance (annual Q4 only)
        if config.governance_enabled and roster.board_governance:
            from .governance import make_governance_agent
            gov_llm = roster.llm_config_for("board_governance")
            if getattr(config, "three_llm_board_enabled", False):
                from .governance import make_governance_agent_3llm
                gov_fn = make_governance_agent_3llm(_tag(_wrap_backups(create_backend(gov_llm), gov_llm.model, "board_governance"), "board_governance"), state_ref)
                print(f"  board_governance: {gov_llm.model} [{gov_llm.backend}] (annual, 3-LLM committee — 4x cost)")
            else:
                gov_fn = make_governance_agent(_tag(_wrap_backups(create_backend(gov_llm), gov_llm.model, "board_governance"), "board_governance"), state_ref)
                print(f"  board_governance: {gov_llm.model} [{gov_llm.backend}] (annual)")

        # Wave λ: PE + IPO lifecycle agents (pitch, PE eval, IPO decision, prospectus)
        if getattr(config, "pe_lifecycle_enabled", False):
            from .private_equity import (
                make_pitch_agent, make_pe_eval_agent,
                make_ipo_decision_agent, make_prospectus_agent,
            )
            # Each firm uses its own backend for pitch/IPO decision/prospectus
            # (consistency with firm's operating voice)
            pitch_fns_per_firm = {
                fid: make_pitch_agent(_tag(backends[fid], f"pe_pitch_{fid}"))
                for fid in backends
            }
            ipo_fns_per_firm = {
                fid: make_ipo_decision_agent(_tag(backends[fid], f"pe_ipo_{fid}"))
                for fid in backends
            }
            prospectus_fns_per_firm = {
                fid: make_prospectus_agent(_tag(backends[fid], f"pe_prosp_{fid}"))
                for fid in backends
            }

            # PE fund eval agents — one per fund, DISTRIBUTED across firm
            # backends so evaluations can run in parallel without hitting
            # a single endpoint. Each fund gets a different backend from
            # the firm pool, cycling. Previously all funds shared firm_1's
            # backend → serialized Q1 wallclock (160 sequential calls at
            # ~58s each). With distributed backends + orchestrator
            # parallelism (see _run_pe_round_phase) wallclock drops to
            # max-across-funds instead of sum.
            pe_eval_fns = {}
            from .private_equity import default_pe_funds
            _default_funds = default_pe_funds()
            _backend_pool = list(backends.values())
            for i, fund in enumerate(_default_funds):
                be = _backend_pool[i % len(_backend_pool)]
                pe_eval_fns[fund.fund_id] = make_pe_eval_agent(
                    _tag(be, f"pe_eval_{fund.fund_id}"),
                    fund,
                    state_ref=state_ref,
                )
            print(f"  pe_lifecycle: {len(_default_funds)} PE funds "
                  f"(distributed across {len(_backend_pool)} backends), "
                  f"per-firm pitch/IPO agents")

            # Per-firm dispatcher functions
            def pitch_fn(firm, round_type, industry_character):
                fn = pitch_fns_per_firm.get(firm.firm_id)
                if fn is None:
                    return None
                return fn(firm, round_type, industry_character)

            def ipo_decision_fn(firm, industry_character):
                fn = ipo_fns_per_firm.get(firm.firm_id)
                if fn is None:
                    return None
                return fn(firm, industry_character)

            def prospectus_fn(firm, industry_character):
                fn = prospectus_fns_per_firm.get(firm.firm_id)
                if fn is None:
                    return None
                return fn(firm, industry_character)
        else:
            pitch_fn = None
            pe_eval_fns = None
            ipo_decision_fn = None
            prospectus_fn = None

        # Wave κ: strategic planning agent (per-firm CFO voice)
        if getattr(config, "strategic_planning_enabled", False):
            from .strategic_planning import make_planning_agent
            # Reuse each firm's own backend so the planning voice matches
            # the firm's operating voice (consistency matters for strategy).
            planning_fns_per_firm = {}
            for fid in backends:
                planning_fns_per_firm[fid] = make_planning_agent(
                    _tag(backends[fid], f"planning_{fid}"), state_ref
                )

            def planning_fn(firm, info_pkg, macro, params,
                             prior_plan=None, recent_variances=()):
                fn = planning_fns_per_firm.get(firm.firm_id)
                if fn is None:
                    return None
                return fn(firm, info_pkg, macro, params,
                          prior_plan=prior_plan, recent_variances=recent_variances)
            print(f"  strategic_planning: ON (per-firm CFO plans every 4Q + CFO gatekeeper)")
        else:
            planning_fn = None

        # Wave ν: distressed-firm auction bidders. Each firm gets a
        # bidder agent using its own backend so bidder reasoning
        # matches the firm's operating voice.
        auction_bidder_fns = {}
        if not use_mock:
            # Wave ν+2: env-LLM judges all auction allocations in one call
            # per quarter (replaces per-firm bidder model). The orchestrator
            # looks for the special "__judge__" key first.
            from .distressed_auction import make_auction_judge_agent
            env_backend_for_judge = backends.get("environment") or list(backends.values())[0]
            auction_bidder_fns["__judge__"] = make_auction_judge_agent(
                _tag(env_backend_for_judge, "auction_judge")
            )
            print(f"  distressed_auction: ON (env-judged single-call allocation)")

        # Wave ν+2: entry-judge agent (env-side LLM that decides spawning)
        entry_judge_fn = None
        if not use_mock and getattr(config, "endogenous_entry_enabled", False):
            from .entry import make_entry_judge
            # Use env backend for the entry-judge role (env-side decision)
            env_backend = backends.get("environment") or list(backends.values())[0]
            entry_judge_fn = make_entry_judge(_tag(env_backend, "entry_judge"))
            print(f"  entry_judge: ON (per-quarter spawn decisions)")

        # Wave ν+5: demand calibrator — separate LLM voice that anchors
        # total demand for each quarter's env allocation. Runs BEFORE
        # the env's market-resolution call.
        demand_calibrator_fn = None
        if not use_mock:
            from .demand_calibrator import make_demand_calibrator_agent
            env_backend_calib = backends.get("environment") or list(backends.values())[0]
            demand_calibrator_fn = make_demand_calibrator_agent(
                _tag(env_backend_calib, "demand_calibrator")
            )
            print(f"  demand_calibrator: ON (anchors total demand for env each Q)")

    # Wave ν+12: wire intra-quarter heartbeat path on state so orchestrator's
    # _log() can refresh the heartbeat every N seconds without waiting for
    # end-of-quarter. Ensures heartbeat is fresh within ~5 min even during
    # long quarters (e.g. annual Q4 with audit + governance + rate-limit
    # retries that can run >60 min).
    import os as _os
    state.heartbeat_path = _os.path.join(config.output_dir, run_id, "heartbeat.json")
    state.heartbeat_min_interval_s = float(
        getattr(config, "heartbeat_min_interval_s", 300.0)
    )

    # Run quarters
    t_start = time.time()
    for q in range(n_quarters):
        t_q = time.time()

        # Update state_ref so env agent can access latest reports
        if not use_mock:
            state_ref[0] = state

        state = run_quarter(
            state, firm_fn, env_fn, eq_fn, ib_fn, cb_fn,
            ma_fn=ma_fn,
            sec_fn=sec_fn_agent,
            earnings_announcement_fn=ea_fn,
            sellside_analyst_fns=analyst_fns,
            activist_fn=activist_fn,
            auditor_fn=audit_fn,
            governance_fn=gov_fn,
            emergency_bridge_fn=bridge_fn,
            violation_resolver_fn=(violation_resolver if not use_mock else None),
            annual_report_fn=annual_report_fn,
            env_verifier_fn=env_verifier_fn,
            env_validator_fn=env_validator_fn,
            firm_debrief_fn=firm_debrief_fn,
            env_debrief_fn=env_debrief_fn,
            intermediary_debrief_fns=intermediary_debrief_fns,
            investor_voice_fn=investor_voice_fn,
            planning_fn=planning_fn if not use_mock else None,
            pitch_fn=pitch_fn if not use_mock else None,
            pe_eval_fns=pe_eval_fns if not use_mock else None,
            ipo_decision_fn=ipo_decision_fn if not use_mock else None,
            prospectus_fn=prospectus_fn if not use_mock else None,
            auction_bidder_fns=auction_bidder_fns if (not use_mock and auction_bidder_fns) else None,
            entry_judge_fn=entry_judge_fn if not use_mock else None,
            demand_calibrator_fn=demand_calibrator_fn if not use_mock else None,
            config=config,
        )

        # Store board minutes for this quarter
        if board_minutes_store:
            q_minutes = {}
            for fid, m in board_minutes_store.items():
                q_minutes[fid] = m.full_text
            state.board_minutes_history.append(q_minutes)

        # Update last_flows for next quarter's prompt context
        for fid, flows in state.last_quarter_flows.items():
            last_flows[fid] = {
                "net_sales": flows.net_sales,
                "cogs": flows.cogs,
                "net_income": flows.net_income,
                "cfo": flows.cfo,
                "units_sold": flows.units_sold,
                "market_share": flows.market_share,
                "actual_price": flows.actual_price,
                "actual_rd_spend": flows.actual_rd_spend,
                "actual_sga_spend": flows.actual_sga_spend,
                "actual_capex": flows.actual_capex,
                "end_cash": state.firms[fid].cash if fid in state.firms else 0,
            }

        # Print summary
        active = sum(1 for f in state.firms.values() if f.is_active)
        total_rev = sum(
            r.saleq for r in state.compustat_rows
            if r.fyearq == state.macro.fyear and r.fqtr == state.macro.fqtr
        )
        # Wave ν+2: with endogenous entry, not all firm_i slots exist
        # at every quarter — iterate over actual active firms instead.
        gens = [f"G{f.product_generation}" for f in state.firms.values()
                if f.is_active]
        elapsed_q = time.time() - t_q
        elapsed_total = time.time() - t_start
        # Format total elapsed as h:mm:ss for at-a-glance progress
        eh = int(elapsed_total // 3600)
        em = int((elapsed_total % 3600) // 60)
        es = int(elapsed_total % 60)
        elapsed_total_str = f"{eh}h{em:02d}m{es:02d}s"
        # Per-quarter wallclock as m:ss
        qm = int(elapsed_q // 60)
        qs = int(elapsed_q % 60)
        elapsed_q_str = f"{qm}m{qs:02d}s"
        # Wallclock timestamp for log readability
        wc_iso = time.strftime("%Y-%m-%d %H:%M:%S")
        # Per-Q index out of total, for "we are at quarter X of N"
        progress_str = f"{state.quarter}/{n_quarters}"

        # Wave delta: auto-snapshot after every quarter (unless disabled).
        # Enables --restart-from. Small (~1 MB) per snapshot; cheap.
        if getattr(config, "snapshots_enabled", True):
            from .snapshots import snapshot_world, snapshot_path
            try:
                snapshot_world(
                    state,
                    snapshot_path(config.output_dir, run_id, state.quarter),
                )
            except Exception as e:
                print(f"  [snapshot] WARN: {e}")

        # Wave ν+10: deactivate prompt logger at end of quarter so the
        # next quarter doesn't accidentally append. Safe no-op when
        # logger isn't active.
        try:
            from .prompt_logger import deactivate as _pl_deactivate
            _pl_deactivate()
        except Exception:
            pass

        # Wave ν+3: enriched per-quarter status line so the user can see
        # advancement at a glance:
        #   [HH:MM:SS]  Q5/16 (Q1 2032)  total=1h23m  this_q=8m42s  Rev=$50M  Firms=4
        print(
            f"[{wc_iso}]  Q{progress_str} "
            f"(Q{state.macro.fqtr} {state.macro.fyear})  "
            f"total={elapsed_total_str}  this_q={elapsed_q_str}  "
            f"Rev=${total_rev/1e6:.1f}M  Firms={active}  "
            f"Gen={','.join(gens)}",
            flush=True,
        )

        # Wave ν+: heartbeat file. Touched after every quarter so an
        # observer can confirm the process is alive without parsing the
        # buffered log. Captures: current sim quarter, wallclock,
        # active-firm count, last-quarter elapsed seconds.
        try:
            import os, json
            hb_path = os.path.join(config.output_dir, run_id, "heartbeat.json")
            os.makedirs(os.path.dirname(hb_path), exist_ok=True)
            with open(hb_path, "w") as _hb:
                json.dump({
                    "run_id": run_id,
                    "wallclock_iso": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "wallclock_epoch": int(time.time()),
                    "wallclock_total_elapsed_seconds": elapsed_total,
                    "wallclock_total_elapsed_pretty": elapsed_total_str,
                    "sim_quarter_completed": state.quarter,
                    "fyear": state.macro.fyear,
                    "fqtr": state.macro.fqtr,
                    "active_firms": active,
                    "total_revenue_usd": float(total_rev),
                    "elapsed_seconds_last_q": elapsed_q,
                    "total_quarters_planned": n_quarters,
                    "progress_pct": round(state.quarter / max(1, n_quarters) * 100, 1),
                }, _hb)
        except Exception:
            pass  # heartbeat failure must never break the run

        # Check for all defaults
        if active == 0:
            print("\n*** ALL FIRMS DEFAULTED. Simulation ended. ***")
            break

    elapsed = time.time() - t_start
    print(f"\nCompleted {state.quarter} quarters in {elapsed:.1f}s")
    print(f"Compustat rows: {len(state.compustat_rows)}")

    # ── Compute run-end scores ───────────────────────────────────────────
    print("\n=== SCORING ===")
    firm_scores = compute_firm_scores(
        state.compustat_rows, state.firms, params, state.macro.risk_free_rate,
        pe_round_history=getattr(state, "pe_round_history", []),
    )
    debt_score = compute_debt_score(
        state.compustat_rows, state.firms, state.macro.risk_free_rate
    )
    pricing_score = compute_pricing_score(state.compustat_rows)

    scorecard = RunScorecard(
        run_id=run_id,
        firm_scores=firm_scores,
        debt_score=debt_score,
        pricing_score=pricing_score,
    )
    print(format_scorecard(scorecard))

    # ── Organize outputs into clean folder structure ─────────────────────
    out_path = organize_run_outputs(
        run_id=run_id,
        output_dir=config.output_dir,
        compustat_rows=state.compustat_rows,
        gazettes=state.gazettes,
        product_spec_history=state.product_spec_history,
        board_minutes_history=state.board_minutes_history,
        n_firms=n_firms,
        n_quarters=n_quarters,
        seed=config.seed,
        world_state=state,
        broker_query_log=(broker.query_log if broker is not None else None),
    )
    # Wave θ: dump LLM call telemetry (token counts + latency per model)
    from . import telemetry as _tel
    _tel.dump(out_path)

    # Wave θ+: post-run integrity check. Report BS-violation status clearly
    # at the top of the output block so researchers see immediately whether
    # the run is data-clean.
    _bs_violations = list(getattr(state, "bs_violation_log", []) or [])
    if _bs_violations:
        unique_firms = sorted({v.get("firm_id", "?") for v in _bs_violations})
        unique_phases = sorted({v.get("phase", "?") for v in _bs_violations})
        print(f"  [WARN] BS-violation check: {len(_bs_violations)} events "
              f"({len(unique_firms)} firm(s), {len(unique_phases)} phase(s)). "
              f"See bs_violations.jsonl.")
    else:
        print(f"  [OK] BS-violation check: 0 events (BS identity held every phase)")

    print(f"Outputs written: {out_path}/")
    print(f"  compustat_q.csv       -- Compustat panel ({len(state.compustat_rows)} rows)")
    print(f"  public/               -- Gazettes ({len(state.gazettes)} quarters)")
    print(f"  firms/firm_*/         -- Board minutes, R&D reports, product specs (per firm)")
    print(f"  19 WRDS datasets      -- compustat_a (funda), execucomp,")
    print(f"                           execucomp_grants, execucomp_outstanding,")
    print(f"                           audit_analytics, restatements,")
    print(f"                           analyst_forecasts, management_forecasts,")
    print(f"                           ceo_turnover, compustat_restated,")
    print(f"                           debt_facilities, debt_covenants,")
    print(f"                           covenant_tests_panel, covenant_violations,")
    print(f"                           bond_issuances, bad_debt_events,")
    print(f"                           annual_reports, insider_transactions,")
    print(f"                           activist_campaigns")
    print(f"  summary.txt           -- Run summary")

    # ── Append to cross-run database ─────────────────────────────────────
    append_to_cross_run_db(
        data_dir=config.data_dir,
        run_id=run_id,
        compustat_rows=state.compustat_rows,
        n_firms=n_firms,
        n_quarters=n_quarters,
        seed=config.seed,
        world_state=state,
    )
    print(f"Cross-run DB updated: {config.data_dir}/compustat_all.csv, "
          f"compustat_a_all.csv, run_index.csv")

    # Save scores
    save_scores(scorecard, str(out_path), config.data_dir)
    print(f"Scorecard: {out_path}/scorecard.txt")
    print(f"Cross-run scores: {config.data_dir}/scores.csv")

    # Save world secrets (for post-run analysis — NEVER shared with firms)
    secrets_dir = out_path / "environment"
    secrets_dir.mkdir(exist_ok=True)
    with open(secrets_dir / "world_secrets.txt", "w", encoding="utf-8") as f:
        f.write(world_secrets)
    print(f"World secrets saved: {secrets_dir}/world_secrets.txt (environment only)")

    # ── Wave ν+12: end-of-run LT-memory writer ─────────────────────────
    # When lt_memory_enabled, a separate LLM summarises the run into a
    # role-specific note appended to data/agent_memory/<role>.md. Toggle
    # OFF by default per user direction; infrastructure exists for opt-in.
    if getattr(config, "lt_memory_enabled", False) and not use_mock:
        try:
            from .debriefs import make_lt_memory_writer, maybe_write_lt_memory
            try:
                ltm_llm = roster.llm_config_for("debrief")
                if ltm_llm is None:
                    ltm_llm = roster.llm_config_for("data_analyst")
            except Exception:
                ltm_llm = roster.llm_config_for("data_analyst")
            ltm_writer = make_lt_memory_writer(
                _tag(_wrap_backups(create_backend(ltm_llm), ltm_llm.model, "lt_memory"), "lt_memory")
            )
            # Build a run summary the writer can synthesise: scorecard +
            # active firm count + final industry rev + key event counts.
            from io import StringIO
            sc_buf = StringIO()
            sc_buf.write(format_scorecard(scorecard))
            run_summary = sc_buf.getvalue()
            for role in ("firm", "env", "pe", "bank", "ibank",
                         "activist", "auditor", "sec"):
                note = ltm_writer(role, state.run_id, run_summary)
                if note:
                    maybe_write_lt_memory(
                        role, state.run_id, note,
                        enabled=True, data_dir=config.data_dir,
                    )
            print(f"LT memory updated: {config.data_dir}/agent_memory/<role>.md "
                  f"(8 roles)")
        except Exception as e:
            print(f"LT memory write failed (non-fatal): {e}")

    # ── Generate post-run debrief bundle (dashboard, events, narrative) ──
    # Wave ν+10: every run produces its own dashboard.html automatically.
    # Failures here are non-fatal — the run's CSVs and snapshots are
    # already on disk; the debrief is a view over them and can be
    # regenerated post hoc if this step crashes.
    if getattr(config, "auto_dashboard", True):
        try:
            from pathlib import Path as _Path
            import sys as _sys
            # Ensure analysis/ is on sys.path so the make_debrief module imports.
            _repo_root = _Path(__file__).parent.parent
            if str(_repo_root) not in _sys.path:
                _sys.path.insert(0, str(_repo_root))
            from analysis.make_debrief import (
                extract_events as _extract_events,
                build_panel_data as _build_panel,
                headline_kpis as _kpis,
                render_debrief_md as _render_md,
            )
            from analysis.dashboard import (
                render_dashboard_html as _render_dash,
            )
            import csv as _csv

            run_dir = _Path(out_path)
            debrief_dir = run_dir / "debrief"
            debrief_dir.mkdir(exist_ok=True)

            print(f"Generating debrief dashboard...")
            events = _extract_events(run_dir)
            if events:
                with open(debrief_dir / "events.csv", "w",
                          newline="", encoding="utf-8") as fp:
                    w = _csv.DictWriter(fp, fieldnames=list(events[0].keys()))
                    w.writeheader()
                    w.writerows(events)
            panel = _build_panel(run_dir)
            kpis = _kpis(panel, events)
            _render_dash(panel, events, kpis, run_id,
                         debrief_dir / "dashboard.html", run_dir)
            _render_md(panel, events, kpis, run_id, debrief_dir / "debrief.md")
            print(f"Debrief bundle: {debrief_dir}/  "
                  f"(dashboard.html, events.csv, debrief.md)")
        except Exception as _e:
            import traceback as _tb
            print(f"  [debrief] non-fatal: {_e}")
            _tb.print_exc()
            print(f"  Run CSVs and snapshots are intact; you can regenerate")
            print(f"  with: python analysis/make_debrief.py {out_path}")

    return state


def main():
    parser = argparse.ArgumentParser(description="LLM Firm Lab")
    sub = parser.add_subparsers(dest="command")

    # smoke: mock agents
    smoke = sub.add_parser("smoke", help="Run with mock agents (no LLM)")
    smoke.add_argument("--quarters", type=int, default=5)
    smoke.add_argument("--seed", type=int, default=42)
    smoke.add_argument("--firms", type=int, default=5)

    # run: real LLM
    run = sub.add_parser("run", help="Run with LLM agents")
    run.add_argument("--quarters", type=int, default=5)
    run.add_argument("--seed", type=int, default=42)
    run.add_argument("--firms", type=int, default=5)
    run.add_argument("--mock", action="store_true", help="Use mock agents instead of LLM")
    run.add_argument("--model", default="deepseek/deepseek-v3.2")
    run.add_argument("--config", default=None, help="Path to config.yaml")
    run.add_argument("--restart-from", default=None,
                     help="Resume from a snapshot at outputs/<run_id>/snapshots/Q<N>.pkl. "
                          "Remaining quarters continue from the snapshotted state.")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return

    if args.command == "smoke":
        config = RunConfig(
            n_firms_initial=args.firms,
            n_quarters=args.quarters,
            seed=args.seed,
        )
        run_simulation(config, use_mock=True)

    elif args.command == "run":
        if args.config:
            from .config import load_config
            config = load_config(args.config)
        else:
            config = RunConfig(
                n_firms_initial=args.firms,
                n_quarters=args.quarters,
                seed=args.seed,
                default_llm=LLMConfig(
                    backend="mock" if args.mock else "openrouter",
                    model=args.model,
                ),
            )
        # Wave ν+2: top-level traceback wrapper. Without this, hard
        # crashes in run_simulation can leave a 0-byte log with no
        # diagnostic. Now any uncaught exception writes the full
        # traceback to BOTH stdout and a sidecar `crash_traceback.txt`
        # that survives even if stdout buffering swallows the print.
        try:
            run_simulation(config, use_mock=args.mock,
                            restart_from=args.restart_from)
        except SystemExit:
            raise
        except BaseException as _crash:
            import traceback as _tb
            tb_text = _tb.format_exc()
            print("\n*** UNCAUGHT EXCEPTION IN run_simulation ***", flush=True)
            print(tb_text, flush=True)
            try:
                from pathlib import Path as _P
                crash_path = _P(getattr(config, "output_dir", "outputs")) / "crash_traceback.txt"
                crash_path.parent.mkdir(parents=True, exist_ok=True)
                with open(crash_path, "w") as _cf:
                    _cf.write(tb_text)
                print(f"crash traceback written to {crash_path}", flush=True)
            except Exception:
                pass
            raise


if __name__ == "__main__":
    main()
