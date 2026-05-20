"""
Orchestrator: the quarter loop pipeline.

Runs one quarter at a time, calling agents in the correct order, applying
clamping, posting accounting, and checking invariants.

This module is pure Python (no LLM). It coordinates agents but does not
make strategic decisions.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from .types import (
    ClampedDecisions,
    CompustatRow,
    FirmState,
    MacroState,
    MarketOutcome,
    QuarterFlows,
    RawDecisions,
    SimParams,
    SlotInfo,
)
from .accounting import post_quarter, validate_state, build_compustat_row
from .clamping import clamp_decisions
from .demand import compute_demand_baseline, DemandResult
from .product_specs import ProductSpec, build_product_spec, format_product_spec
from .operational_reports import (
    RDReport, BrandReport,
    generate_rd_report, generate_brand_report,
    format_rd_report_for_firm, format_brand_report_for_firm,
    format_reports_for_environment,
)


@dataclass
class WorldState:
    """Full simulation state. Mutable container updated each quarter."""
    run_id: str
    quarter: int = 0
    macro: MacroState = field(default_factory=MacroState)
    firms: dict[str, FirmState] = field(default_factory=dict)
    slots: dict[str, SlotInfo] = field(default_factory=dict)
    params: SimParams = field(default_factory=SimParams)
    rng: random.Random = field(default_factory=lambda: random.Random(42))
    compustat_rows: list[CompustatRow] = field(default_factory=list)
    gazettes: list[str] = field(default_factory=list)
    quarter_log: list[str] = field(default_factory=list)
    last_quarter_flows: dict[str, QuarterFlows] = field(default_factory=dict)
    product_specs: dict[str, ProductSpec] = field(default_factory=dict)
    product_spec_history: list[dict[str, str]] = field(default_factory=list)
    rd_reports: dict[str, RDReport] = field(default_factory=dict)
    brand_reports: dict[str, BrandReport] = field(default_factory=dict)
    board_minutes_history: list[dict[str, str]] = field(default_factory=list)  # per-Q board minutes

    # ── Expansion state (v0.5) ──
    sec_investigations: dict = field(default_factory=dict)       # firm_id -> SECInvestigationState
    sec_enforcement_log: list = field(default_factory=list)
    analyst_notes: list = field(default_factory=list)            # list of AnalystNote
    audit_results: list = field(default_factory=list)            # list of AuditResult
    ceo_history: dict = field(default_factory=dict)              # firm_id -> [events]
    pending_bids: list = field(default_factory=list)             # list of MABid
    completed_acquisitions: list = field(default_factory=list)
    earnings_releases: list = field(default_factory=list)        # list of EarningsRelease
    annual_reports: list = field(default_factory=list)           # list of AnnualReport (Q4 only)
    ceo_grant_events: list = field(default_factory=list)         # list of StockGrant (Stage 11, event-level)
    # Year-end CEO snapshot (Stage 11): one dict per firm × fiscal year,
    # captured at end of Q4 governance phase. Drives execucomp.csv +
    # execucomp_outstanding.csv panel rows.
    execucomp_annual_snapshots: list = field(default_factory=list)
    restatement_events: list = field(default_factory=list)       # list of restatement event dicts
    # Per-firm operational notes from env (Stage 11.5) — explains what
    # actually happened when env moderated firm decisions (e.g., cash squeeze
    # disrupted production, AR accelerated). Shown on firm's prompt next Q
    # so firm doesn't hallucinate its plan went through as-designed.
    pending_env_notes: dict = field(default_factory=dict)       # {firm_id: [str, ...]}
    # Wave ν+10 item 10: investment-bank feedback on declined / haircut
    # issuances. Carried into next quarter's firm prompt so the firm can
    # respond to the public market discussion and resubmit a modified
    # request. {firm_id: {"market_discussion": str, "retry_guidance": str,
    # "issued_quarter": int}}
    pending_ibank_feedback: dict = field(default_factory=dict)
    # Stage 12: insider trading events (WRDS Thomson Reuters / Form 4 style)
    insider_events: list = field(default_factory=list)          # list of InsiderTradingEvent
    # Stage 12: activist investor campaigns + firm responses
    activist_campaigns: list = field(default_factory=list)      # list of campaign dicts
    # Wave alpha: structured BS-identity violation log (one row per phase-level drift event).
    # Written to outputs/{run_id}/bs_violations.jsonl by output_organizer.
    bs_violation_log: list = field(default_factory=list)
    # Wave beta: append-only log of all Actions + ActionResults.
    # Written to outputs/{run_id}/proposals.jsonl by output_organizer.
    # Every compustat row's `proposal_id` keys into this log for full provenance.
    action_log: list = field(default_factory=list)
    # Wave gamma: completed multi-round negotiations (covenant waivers,
    # debt pricing, etc). Each record has the full round history.
    # Written to outputs/{run_id}/negotiations.jsonl by output_organizer.
    negotiations_log: list = field(default_factory=list)
    # Wave epsilon: per-agent persistent memory. Loaded / used by the
    # agent prompts. Stored on WorldState so snapshots preserve them.
    firm_beliefs: dict = field(default_factory=dict)     # firm_id → FirmBelief
    activist_memory: dict = field(default_factory=dict)  # "activist_1" → ActivistMemory
    auditor_memory: dict = field(default_factory=dict)   # auditor_id → AuditorMemory
    sec_memory: dict = field(default_factory=dict)       # "sec" → SECMemory
    pending_detection_tips: list = field(default_factory=list)   # env-generated EM detection tips for next SEC call
    pending_covenant_violations: list = field(default_factory=list)  # debt covenant violations awaiting LLM resolution (Stage 3c)
    # Wave theta: board directors (shared pool with interlocking seats).
    # Populated at initialize_world; director_id stable across quarters.
    # Each Director has `seats: tuple[firm_id, ...]` for multi-firm membership.
    directors: dict = field(default_factory=dict)   # director_id → Director
    # Wave theta: director turnover events (appointment, retirement, default).
    # One dict per event. Written to director_turnover.csv at run end.
    director_turnover: list = field(default_factory=list)
    # Wave λ: PE funds (pool of K patient-capital funds) and history of
    # private funding rounds. Populated at initialize_world when
    # pe_lifecycle_enabled. Written to pe_funds.csv + pe_rounds.csv.
    pe_funds: dict = field(default_factory=dict)          # fund_id → PEFund
    pe_round_history: list = field(default_factory=list)  # list[PERound]
    # Wave ν: distressed-firm auction events (one per default).
    # Each event is a dict: {target_firm_id, outcome, bids, winner_id,
    # winning_amount, winner_rationale}. Written to distressed_auctions.csv.
    distressed_auctions: list = field(default_factory=list)
    # Mapping firm_id → ProspectusDoc for firms that have IPO'd.
    ipo_prospectuses: dict = field(default_factory=dict)
    # Wave theta+: per-peer-observation log for research on the interlock
    # info-leak mechanism. One record per (quarter, observer, observed)
    # observation event, capturing the noise SD actually applied + shared-
    # director count AT OBSERVATION TIME (not a stale snapshot).
    # Written to peer_observations.jsonl by output_organizer.
    peer_observation_log: list = field(default_factory=list)
    template_id: str = "longevity_drug"
    # Wave ν+2: max firm-slot count (cap for endogenous entry).
    n_firms_max: int = 20
    # Wave ν+2: log of endogenous-entry events {quarter, firm_id, profile, rationale}
    entry_events: list = field(default_factory=list)
    # Wave ν+5: most-recent demand-calibrator estimate (carried forward
    # so env-prompt builder can include it as the total-demand anchor).
    demand_calibrator_last: dict | None = None
    # Wave ν+12: per-firm investor-voice note from end of LAST quarter.
    # Rendered in firm decision prompt this quarter. Soft market view.
    investor_notes_by_firm: dict[str, str] = field(default_factory=dict)

    # Wave ν+12: per-quarter debrief notes from each agent type. One dict
    # per debrief: {"role": "firm"|"env"|"pe"|"bank"|"ibank"|"activist"|"auditor"|"sec",
    # "agent_id": <firm_id or fund_id or "env">, "quarter": <int>, "note": <str>}.
    # Surfaced next quarter via agent_history.render_recent_debriefs().
    debrief_notes: list[dict] = field(default_factory=list)

    # Wave ν+12: intra-quarter heartbeat path + min interval. The
    # end-of-quarter heartbeat in cli.py is sticky on long quarters
    # (e.g. 60min Q4 with annual audit + governance), so _log() also
    # writes the heartbeat any time min-interval has elapsed.
    heartbeat_path: str = ""              # absolute path to outputs/<run_id>/heartbeat.json
    heartbeat_min_interval_s: float = 300.0   # 5 minutes; tunable
    _last_heartbeat_epoch: float = 0.0


def initialize_world(
    n_firms: int,
    params: SimParams,
    seed: int,
    run_id: str,
    scenario=None,
    directors_enabled: bool = True,
    pe_lifecycle_enabled: bool = False,
    initial_cohort: int | None = None,
    regional_markets_enabled: bool = True,
    n_firms_max: int | None = None,
) -> WorldState:
    """Create the initial world state with `n_firms` MAX slots.

    Wave ν+2: when `initial_cohort` is set and < n_firms, only the first
    `initial_cohort` slots are populated with FirmState entries at
    initialization. The remaining slots are reserved for endogenous
    entry over time. When initial_cohort is None, all slots are
    populated immediately (legacy behavior).

    `scenario` (Wave zeta) optionally overrides per-firm founding PPE,
    capability, brand, base_unit_cost, ceo_base_salary. IPO financials
    (cash, price, shares) are applied in Phase 2 — they key off firm_id.
    """
    rng = random.Random(seed)

    state = WorldState(
        run_id=run_id,
        quarter=0,
        params=params,
        rng=rng,
    )
    # Wave ν+2: store the cap so entry phase can enforce it.
    # Wave ν+12: cap can now be set independently of the initial cohort.
    # If n_firms_max is None, fall back to n_firms (legacy behaviour).
    state.n_firms_max = max(n_firms, int(n_firms_max or n_firms))

    # Resolve scenario (None = legacy uniform default)
    scenario_map = {}
    if scenario is not None:
        scenario_map = {f.firm_id: f for f in scenario.firms}

    # How many firms to actually populate at Q1
    n_initial = n_firms if initial_cohort is None else min(n_firms, max(1, initial_cohort))

    # Create firm slots (all max slots created so SlotInfo tracking works)
    for i in range(n_firms):
        if i >= n_initial:
            # Reserved slot for endogenous entry — register slot but skip FirmState
            slot_id = f"slot_{i}"
            state.slots[slot_id] = SlotInfo(
                slot_id=slot_id,
                current_firm_id="",      # empty until entry fills it
                incarnation=0,
            )
            continue
        # Below: original initialization for the active initial cohort.
        slot_id = f"slot_{i}"
        firm_id = f"firm_{i}"
        state.slots[slot_id] = SlotInfo(
            slot_id=slot_id,
            current_firm_id=firm_id,
            incarnation=1,
        )
        sf = scenario_map.get(firm_id)
        cogs_variation = rng.uniform(
            -params.gen1_cogs_variation,
            params.gen1_cogs_variation
        )
        # Wave ν+10 item 8: heterogeneous initial conditions. Real industries
        # don't begin with identical-twin firms; sampling capability, brand,
        # capacity, and PPE from per-firm distributions tests whether the
        # paper's headline patterns survive non-degenerate starting points.
        # Sampled from `rng` so the run remains seed-deterministic.
        # Wave ν+11 fix: het_capacity is derived from het_ppe via
        # ppe_per_unit_capacity so initial state is consistent with the
        # ongoing capex→capacity relationship in accounting. Otherwise
        # firms with high initial capacity but low PPE would have their
        # capacity slashed at Q1 by the PPE-driven recompute.
        het_capability = max(20.0, min(80.0, rng.gauss(50.0, 10.0)))
        het_brand = max(20.0, min(80.0, rng.gauss(50.0, 10.0)))
        het_ppe = max(15_000_000.0, min(50_000_000.0, rng.gauss(25_000_000.0, 5_000_000.0)))
        het_capacity = max(50, int(het_ppe / params.ppe_per_unit_capacity))
        auditor_id = f"auditor_{(i % 4) + 1}"
        from .governance import CEO_TYPES
        ceo_type = (sf.ceo_type if (sf and sf.ceo_type) else rng.choice(CEO_TYPES))
        # Wave ν+6: idiosyncratic differentiation profile (geo/segment/
        # distribution/signature feature) — keeps each firm distinct in
        # the env's eyes so it can't easily collapse to a single-firm
        # winner-take-all allocation.
        from .personalities import get_differentiation_profile
        diff = get_differentiation_profile(i, regional_enabled=regional_markets_enabled)

        # Legacy defaults preserved when no scenario: capability=35,
        # brand=10, ceo_base_salary=0 (unused historically), PPE=$25M.
        if sf is not None:
            state.firms[firm_id] = FirmState(
                firm_id=firm_id,
                incarnation=1,
                quarter=0,
                is_active=True,
                capacity_units=250,
                base_unit_cost=sf.base_unit_cost,
                ppe_gross=sf.founding_ppe_gross,
                capability_stock=sf.founding_capability,
                brand_stock=sf.founding_brand,
                ceo_base_salary=sf.ceo_base_salary,
                auditor_id=auditor_id,
                ceo_type=ceo_type,
                geographic_focus=diff["geographic_focus"],
                patient_segment=diff["patient_segment"],
                distribution_channel=diff["distribution_channel"],
                signature_feature=diff["signature_feature"],
            )
        else:
            state.firms[firm_id] = FirmState(
                firm_id=firm_id,
                incarnation=1,
                quarter=0,
                is_active=True,
                # Wave ν+10 item 8: heterogeneous initial conditions.
                capacity_units=het_capacity,
                base_unit_cost=params.gen_base_cogs[1] + cogs_variation,
                ppe_gross=het_ppe,
                capability_stock=het_capability,
                brand_stock=het_brand,
                auditor_id=auditor_id,
                ceo_type=ceo_type,
                geographic_focus=diff["geographic_focus"],
                patient_segment=diff["patient_segment"],
                distribution_channel=diff["distribution_channel"],
                signature_feature=diff["signature_feature"],
            )

    # Initial macro state
    # Wave ι: scenario can override market_size_baseline + awareness_rate
    # to model larger/smaller or faster/slower-growing industries.
    mp = getattr(scenario, "market_params", None) if scenario else None
    state.macro = MacroState(
        quarter=0,
        fyear=2031,
        fqtr=0,
        risk_free_rate=0.01,
        market_size_baseline=(
            mp.market_size_baseline if mp and mp.market_size_baseline is not None
            else 600_000_000
        ),
        awareness_rate=(
            mp.awareness_rate if mp and mp.awareness_rate is not None
            else 0.15
        ),
    )

    # Wave ι: apply scenario's demand-coefficient + outside-utility +
    # affordability overrides onto SimParams (so demand.py picks them up
    # automatically). Uses dataclasses.replace since SimParams is frozen.
    if mp is not None:
        from dataclasses import replace as _dc_replace_mp
        _param_updates = {}
        for src_key, dst_key in [
            ("price_coef", "demand_price_coef"),
            ("quality_coef", "demand_quality_coef"),
            ("brand_coef", "demand_brand_coef"),
            ("outside_utility_base", "outside_utility_base"),
            ("outside_utility_decay", "outside_utility_decay"),
            ("outside_utility_floor", "outside_utility_floor"),
            ("affordability_center", "affordability_center"),
            ("affordability_steepness", "affordability_steepness"),
            # Wave ν+4: Gen 2 R&D threshold (scenario-tunable)
            ("gen_2_rd_threshold", "gen_2_rd_threshold"),
        ]:
            src_val = getattr(mp, src_key, None)
            if src_val is not None:
                _param_updates[dst_key] = src_val
        if _param_updates:
            state.params = _dc_replace_mp(state.params, **_param_updates)

    # Store scenario on state so Phase 2 IPO + prompt-builders can look it up
    if scenario is not None:
        state._scenario_map = scenario_map  # type: ignore[attr-defined]
        state._scenario = scenario  # type: ignore[attr-defined]

    # ── Wave theta: populate director pool (toggleable) ───────────────
    # Creates ~3 × n_firms directors with interlocking seats. Assign 4
    # independent directors to each firm's board; max 3 seats/director.
    # Enables the interlock info-leak mechanism when combined with
    # `noisy_signals_enabled`. Off = state.directors stays empty and
    # interlock info leak is a no-op (zero seats = zero sharing).
    if directors_enabled:
        _populate_director_pool(state, n_firms)

    # ── Wave λ: populate PE fund pool + mark firms as founded ─────────
    # Firms' capital trajectory changes fundamentally:
    #   legacy: Q0 IPO gives founding_cash → operations use it
    #   Wave λ: Q0 founder seed (5% of founding_cash or $5M) → firms
    #           raise Series A/B/C from PE pool as they grow → eventually IPO
    # To avoid the legacy Phase 2 IPO code also running for these firms,
    # we pre-populate cash + shares here and set lifecycle_stage="founded".
    # Phase 2 skips firms whose lifecycle_stage != "public".
    if pe_lifecycle_enabled:
        from .private_equity import default_pe_funds
        for fund in default_pe_funds():
            state.pe_funds[fund.fund_id] = fund

        for fid, firm in state.firms.items():
            sf = scenario_map.get(fid)
            scenario_cash = sf.founding_cash if sf is not None else 150_000_000
            # Seed round: 5% of what the scenario envisions (rest raised via PE)
            seed_cash = max(5_000_000, scenario_cash * 0.05)
            # Founder shares: 1M shares reserved (will dilute as rounds happen).
            # Wave ν: also stored as founder_shares so scoring can attribute
            # ownership correctly post-IPO.
            founder_shares = 1_000_000
            state.firms[fid] = firm.evolve(
                cash=seed_cash,
                apic=seed_cash,
                retained_earnings=0.0,
                shares_outstanding=founder_shares,
                founder_shares=founder_shares,
                public_shares_outstanding=0,
                lifecycle_stage="founded",
                is_public=False,
                equity_price=0.0,    # no market price until IPO
                # No PPE at founding — scenario's founding_ppe is what they
                # would own post-Series-A; resetting to $0 forces capex during ramp.
                # (Actually keep PPE at scenario level if present — represents
                # in-kind founder contribution / prior-stage investment.)
                # Decision: keep PPE as-is since it's already on the balance
                # sheet from the initial FirmState constructor.
            )

    return state


# Deterministic name pool for director generation.
_DIRECTOR_NAMES = [
    "Patricia Aldrich", "Marcus Bellweather", "Sofia Chen-Ramirez", "David Okonkwo",
    "Elena Voskresenskaya", "James Hartley", "Yuki Nakamura", "Aisha Thiongo",
    "Ronald Fairfax", "Margaret Kim", "Oscar Delacroix", "Priya Subramanian",
    "Henrietta Sloan", "Bartholomew Greaves", "Mei-Lin Zhao", "Farhan Qureshi",
    "Cordelia Ashworth", "Viktor Brannigan", "Sanjay Iyer", "Lucille Bergstrom",
    "Malik Tshabalala", "Beatrice Thornton-Lee", "Dmitri Volkov", "Nadia El-Amin",
    "Pemberton Holloway", "Wilhelmina Thackeray", "Rafael Montenegro", "Kimiko Ishikawa",
    "Theodore Ashenford", "Valentina Castellanos", "Ivan Petrovich", "Chidinma Okafor",
    "Graham Whitfield", "Anastasia Belov", "Tomas Eriksson", "Noor Al-Rashid",
]


def _populate_director_pool(state: "WorldState", n_firms: int) -> None:
    """Generate a shared pool of directors with interlocking seat assignments.

    Pool size ≈ 3 × n_firms (enough diversity for 4 indep directors per
    board). Per-director max seat cap = 3 prevents any one director from
    monopolizing the network. Interlock probability per-slot = 30%:
    produces realistic distribution (mean ~1.5 seats, ~30% of directors
    sit on 2+ boards — close to S&P 500 empirics).
    """
    from .identifiers import Director
    from dataclasses import replace as _replace

    if n_firms == 0:
        return
    pool_size = min(max(10, int(3.0 * n_firms)), len(_DIRECTOR_NAMES))
    MAX_SEATS_PER_DIRECTOR = 3
    INTERLOCK_PROB = 0.30

    # Build pool
    pool: list[Director] = []
    for i in range(pool_size):
        age = 52 + state.rng.randint(0, 22)  # 52-74
        pool.append(Director(
            director_id=f"director_{i+1:03d}",
            name=_DIRECTOR_NAMES[i],
            age=age,
            seats=(),
            independent=True,
        ))

    # Helper: all directors eligible for a new seat at this firm
    def _eligible(pool_list, firm_id, must_have_prior_seat=False):
        out = []
        for d in pool_list:
            if firm_id in d.seats:
                continue  # already on this board
            if len(d.seats) >= MAX_SEATS_PER_DIRECTOR:
                continue  # capped
            if must_have_prior_seat and not d.seats:
                continue
            out.append(d)
        return out

    # Assign 4 directors to each firm.
    for firm_id in state.firms.keys():
        for _ in range(4):
            chosen = None
            if state.rng.random() < INTERLOCK_PROB:
                # Try interlock (director with ≥1 existing seat elsewhere,
                # not already capped, not already on this firm).
                cands = _eligible(pool, firm_id, must_have_prior_seat=True)
                if cands:
                    chosen = state.rng.choice(cands)
            if chosen is None:
                # Fresh draw preference: prefer unseated directors first
                fresh = [d for d in pool if not d.seats]
                if fresh:
                    chosen = state.rng.choice(fresh)
                else:
                    cands = _eligible(pool, firm_id)
                    if not cands:
                        continue  # pool exhausted (rare)
                    chosen = state.rng.choice(cands)
            idx = pool.index(chosen)
            pool[idx] = _replace(chosen, seats=chosen.seats + (firm_id,))

    # Store pool (only directors who got at least one seat)
    for d in pool:
        if d.seats:
            state.directors[d.director_id] = d


def run_quarter(
    state: WorldState,
    firm_agent_fn,
    env_agent_fn,
    equity_market_fn=None,
    investment_bank_fn=None,
    commercial_bank_fn=None,
    # ── Expansion agents (v0.5+, all optional) ──
    ma_fn=None,                 # M&A phase (if ma_enabled)
    sec_fn=None,                # SEC surveillance (if sec_enabled)
    earnings_announcement_fn=None,  # earnings release (if earnings_announcement_enabled)
    sellside_analyst_fns=None,  # list of analyst callables (if sellside_analysts_enabled)
    activist_fn=None,           # activist investor (if activist_investors_enabled)
    auditor_fn=None,            # auditor pool (if auditor_enabled, annual Q4)
    governance_fn=None,         # board governance (if governance_enabled, annual Q4)
    emergency_bridge_fn=None,   # distressed bridge lender (LLM, replaces hardcoded penalty)
    violation_resolver_fn=None, # Stage 3c covenant violation resolver (if debt_covenants_enabled)
    annual_report_fn=None,      # 10-K-style annual report generator (annual Q4)
    planning_fn=None,           # Wave κ strategic planning agent (per-firm)
    # Wave λ: PE + IPO lifecycle agents (all optional)
    pitch_fn=None,              # per-firm pitch generator (CFO voice)
    pe_eval_fns=None,           # dict: fund_id → eval agent
    ipo_decision_fn=None,       # firm-side IPO decision agent
    prospectus_fn=None,         # firm-side S-1 prospectus author
    env_verifier_fn=None,       # env output verifier (if env_verification_enabled)
    env_validator_fn=None,      # Wave ν+11 E9: second-env validator (if env_validator_enabled)
    firm_debrief_fn=None,       # Wave ν+12: per-firm end-of-quarter debrief LLM
    env_debrief_fn=None,        # Wave ν+12: env end-of-quarter debrief LLM
    intermediary_debrief_fns=None,  # Wave ν+12: dict role→writer_fn for PE/bank/etc.
    investor_voice_fn=None,     # Wave ν+12: per-firm market-analyst note (if investor_voice_enabled)
    # Wave ν: distressed-firm asset auction (runs after any defaults)
    auction_bidder_fns=None,    # dict: firm_id → auction bidder agent
    # Wave ν+2: endogenous entry judge (env-side LLM)
    entry_judge_fn=None,
    # Wave ν+5: demand calibrator (LLM that anchors total demand for env)
    demand_calibrator_fn=None,
    config=None,                # RunConfig for toggle checks
) -> WorldState:
    """
    Execute one complete quarter. The main pipeline.

    Agent functions:
        firm_agent_fn(firm_id, firm_state, info_package, params) -> RawDecisions
        env_agent_fn(firm_actions, firms, macro, params) -> dict (market outcomes)
        equity_market_fn(firms, macro, params) -> dict (equity prices per firm)
        investment_bank_fn(firms, macro, params, raw_decisions) -> dict (term debt + equity structuring)
        commercial_bank_fn(firms, macro, params) -> dict (revolver terms per firm)
        ma_fn(firms, macro) -> (updated_firms, deals)
        sec_fn(compustat, investigations, tips, macro, firm_ids) -> {firm_id: action}
        earnings_announcement_fn(firm_id, firm, flows, macro, prior_guidance) -> EarningsRelease
        sellside_analyst_fns: list of analyst(compustat, releases, prior_notes, macro, firm_ids) -> [AnalystNote]
        auditor_fn(firm, compustat_4q, prior_opinions, env_hints) -> AuditResult
        governance_fn(firm, flows_4q, macro, peer_avg_rev, peer_avg_ni) -> dict
    """

    # ── Phase 1: Advance time and draw shocks ────────────────────────────
    state.quarter += 1
    state.quarter_log = []
    _log(state, f"=== Quarter {state.quarter} ===")

    # Wave ν+10: per-quarter full-prompt audit logging. Activate the
    # module-level logger if this quarter is on the schedule
    # (RunConfig.prompt_log_every_n_quarters). All backends are already
    # wrapped with LoggingBackend; activation flips a global on/off flag
    # they consult on each call.
    _prompt_log_path = None
    if config and getattr(config, "prompt_log_every_n_quarters", 0) > 0:
        try:
            from .prompt_logger import activate_for_quarter as _pl_activate
            from pathlib import Path as _Path
            run_dir = _Path(getattr(config, "output_dir", "outputs")) / state.run_id
            _prompt_log_path = _pl_activate(
                run_dir, state.quarter,
                config.prompt_log_every_n_quarters,
            )
            if _prompt_log_path is not None:
                _log(state, f"  PROMPT LOG ACTIVE: writing full prompts + "
                            f"responses to {_prompt_log_path}")
        except Exception as e:
            _log(state, f"  prompt_logger activation failed (non-fatal): {e}")

    # Wave ν: capture set of firms active at start-of-quarter. Used after
    # phase 15 to identify NEWLY defaulted firms → trigger distressed-
    # asset auction.
    _active_at_start = {fid for fid, f in state.firms.items() if f.is_active}

    macro = _advance_macro(state)
    state.macro = macro

    # Wave alpha: initialize the BS snapshot with CURRENT (end-of-prior-Q)
    # state so per-phase delta checks only log drift introduced IN THIS
    # quarter. Previously the snapshot was {} which caused pre-existing
    # residuals from prior quarters to re-log falsely as new drift at
    # phase_2_ipo. For pre-IPO firms (cash==0, quarter==0, PPE on BS but
    # no equity yet), initialize baseline to all-zeros so Phase 2 IPO's
    # correction doesn't register as a spurious "drift" event.
    _bs_snap: dict = {}
    for _fid_baseline, _firm_baseline in state.firms.items():
        # Wave ν+12 fix: include INACTIVE/defaulted firms in the baseline too.
        # Previously this loop skipped defaulted firms, so any persistent
        # residual carried over from a Ch7 wind-down (e.g. firm with
        # phantom $70M asset/liability mismatch after auction) was missing
        # from prior_bs at the start of each new quarter, causing every
        # downstream `_check_bs_invariants` call to log delta=resid as
        # "new drift this phase" — even though the residual was static.
        # Run-3 produced 70 phase_2_ipo events on a single defaulted firm
        # this way. Defaulted firms can't be cured by including them in
        # the baseline (the residual is what it is), but at least we stop
        # spamming the violation log with the same stale value each Q.
        if _firm_baseline.cash == 0 and _firm_baseline.quarter == 0 and _firm_baseline.is_active:
            # Pre-IPO active firm: baseline is zeros; Phase 2 will bring A=L+E=0
            _bs_snap[_fid_baseline] = (0.0, 0.0, 0.0, 0.0)
        else:
            _a = _firm_baseline.total_assets
            _l = _firm_baseline.total_liabilities
            _e = _firm_baseline.total_equity
            _bs_snap[_fid_baseline] = (_a, _l, _e, _a - _l - _e)

    # ── Wave λ Phase 1.5: PE round auction (if enabled) ─────────────────
    # Private firms seeking capital: CFO issues a pitch → PE funds
    # evaluate → firm selects lead + syndicate → shares issued, cash
    # credited. Only fires when pe_lifecycle_enabled + agents wired.
    if (config and getattr(config, "pe_lifecycle_enabled", False)
            and pitch_fn is not None and pe_eval_fns):
        _run_pe_round_phase(
            state, pitch_fn, pe_eval_fns, config,
        )

    # ── Wave λ Phase 1.6: IPO event (if enabled) ────────────────────────
    # Private firms decide whether to IPO. If yes → prospectus →
    # public equity market sets IPO price → transition to public.
    if (config and getattr(config, "pe_lifecycle_enabled", False)
            and ipo_decision_fn is not None):
        _run_ipo_phase(
            state, ipo_decision_fn, prospectus_fn, equity_market_fn, config,
        )

    # ── Wave ν+2 Phase 1.7: endogenous entry ─────────────────────────────
    # When endogenous_entry is enabled, an env-LLM judges each quarter
    # whether a new entrant is plausible. New firms appear in unused
    # slots up to n_firms_max. Entry skipped at Q1 (initial cohort
    # already populated). See entry.make_entry_judge.
    if (config and getattr(config, "endogenous_entry_enabled", False)
            and entry_judge_fn is not None and state.quarter > 0):
        _run_entry_phase(state, entry_judge_fn, config)

    # Wave ν+2 fix: include any newly-entered firms in the "active at
    # start" set so that if they default this same quarter, the auction
    # phase can still bid for their assets.
    for fid, firm in state.firms.items():
        if firm.is_active and fid not in _active_at_start:
            _active_at_start.add(fid)

    # Wave ν+4: dormant-state management. MUST run AFTER entry phase
    # so newly-spawned entrants get checked. Any "founded"-stage firm
    # that has NOT raised yet enters dormant state — preserves seed
    # cash, no operations this quarter. Each subsequent quarter the
    # firm re-pitches; if it raises, it un-dormants. Prevents the 1Q-
    # death pattern where unfunded entrants got firm-decision LLM
    # calls + accounting burn + settlement default in their first Q.
    if config and getattr(config, "pe_lifecycle_enabled", False):
        for fid, firm in list(state.firms.items()):
            if not firm.is_active:
                continue
            if firm.lifecycle_stage == "founded":
                if firm.cumulative_pe_capital_raised <= 0:
                    new_q_dormant = firm.quarters_dormant + 1
                    # Wave ν+14: wind down firms that sit dormant too long.
                    # Real-world founder teams either close a round within
                    # a few quarters or shut down — investors lose interest,
                    # founders run out of patience, the cap-table goes stale.
                    # Cap at 12 quarters (3 years) of dormancy.
                    DORMANT_WINDDOWN_THRESHOLD = 12
                    if new_q_dormant >= DORMANT_WINDDOWN_THRESHOLD:
                        msg = (f"  DORMANT WIND-DOWN Q{state.quarter}: {fid} "
                               f"failed to close PE round after "
                               f"{new_q_dormant}Q. Marking inactive.")
                        _log(state, msg)
                        print(msg, flush=True)
                        state.firms[fid] = firm.evolve(
                            is_active=False, is_dormant=False,
                            quarters_dormant=new_q_dormant,
                        )
                        continue
                    if not firm.is_dormant:
                        msg = (f"  DORMANT Q{state.quarter}: {fid} entered dormant state "
                               f"(no PE round closed). Seed cash preserved; will re-pitch.")
                        _log(state, msg)
                        print(msg, flush=True)
                    state.firms[fid] = firm.evolve(
                        is_dormant=True,
                        quarters_dormant=new_q_dormant,
                    )
                elif firm.is_dormant:
                    msg = (f"  WAKE Q{state.quarter}: {fid} raised PE after "
                           f"{firm.quarters_dormant}Q dormant; resuming operations.")
                    _log(state, msg)
                    print(msg, flush=True)
                    state.firms[fid] = firm.evolve(
                        is_dormant=False,
                        quarters_dormant=0,
                    )
            elif firm.is_dormant:
                state.firms[fid] = firm.evolve(is_dormant=False, quarters_dormant=0)

    # ── Phase 2: IPO for new entrants (simplified for v1) ────────────────
    # Wave zeta: scenario overrides per-firm founding IPO terms.
    # Wave λ: skip this legacy block for firms in the new lifecycle
    # (they start lifecycle_stage="founded" with minimal cash and raise
    # via PE rounds instead).
    scenario_map = getattr(state, "_scenario_map", None) or {}
    pe_lifecycle_on = bool(config and getattr(config, "pe_lifecycle_enabled", False))
    for fid, firm in state.firms.items():
        # Skip legacy IPO if firm is in PE-managed lifecycle and NOT public
        if pe_lifecycle_on and firm.lifecycle_stage != "public":
            continue
        if firm.is_active and firm.cash == 0 and firm.quarter == 0:
            # Resolve per-firm IPO terms (scenario wins; else legacy default)
            sf = scenario_map.get(fid)
            if sf is not None:
                shares = sf.ipo_shares
                ipo_price = sf.ipo_price
                ipo_raise = sf.founding_cash + sf.founding_ppe_gross
            else:
                ipo_raise = 175_000_000
                shares = 10_000_000
                ipo_price = ipo_raise / shares
            # Cash = IPO raise minus pilot plant already on BS (as PPE).
            # For scenario path, firm.ppe_gross already matches sf.founding_ppe_gross
            # from initialize_world; subtract that, not a hardcoded $25M.
            ppe_on_bs = firm.ppe_gross
            # Wave ν: legacy IPO path — no PE/founder/public distinction
            # exists; firm IPOs immediately at Q0 with the founders being
            # the original investors. Leave founder_shares/public_shares
            # unset so scoring's legacy-mode fallback owns the math.
            firm = firm.evolve(
                cash=ipo_raise - ppe_on_bs,
                common_stock=shares * 0.001,
                apic=ipo_raise - shares * 0.001,
                shares_outstanding=shares,
                equity_price=ipo_price,
            )

            # Stage 11: founding CEO equity package (gated on stock_comp_enabled).
            # Realistic IPO-era biotech founder package: ~2% of float in RSU
            # + ~4% in options struck at IPO price, 4-year quarterly vest.
            # Without this, first grants come at year-2 annual governance —
            # and if the firm defaults before then, `execucomp_grants.csv` +
            # `insider_transactions.csv` stay empty (the audit's Critical #2).
            if config and getattr(config, "stock_comp_enabled", False):
                from .ceo_comp import create_grant as _cg
                from .types import InsiderTradingEvent as _ITE
                from .wrds_identifiers import abs_quarter_to_datadate as _dd
                # 16-quarter quarterly vest = 6.25% each quarter.
                vest_sched = tuple((q, 1.0 / 16.0) for q in range(1, 17))
                firm, g_rsu = _cg(
                    firm, grant_type="rsu",
                    shares=int(shares * 0.02),  # 2% RSU
                    strike_price=0.0,
                    vesting_schedule=vest_sched,
                    grant_quarter=state.quarter,
                    share_price_at_grant=ipo_price,
                )
                firm, g_opt = _cg(
                    firm, grant_type="stock_option",
                    shares=int(shares * 0.04),  # 4% options
                    strike_price=ipo_price,
                    vesting_schedule=vest_sched,
                    grant_quarter=state.quarter,
                    share_price_at_grant=ipo_price,
                )
                state.ceo_grant_events.extend([g_rsu, g_opt])
                for g in (g_rsu, g_opt):
                    state.insider_events.append(_ITE(
                        run_id=state.run_id, firm_id=fid,
                        ceo_id=g.ceo_id, ceo_incarnation=g.ceo_incarnation,
                        event_quarter=g.grant_quarter,
                        event_date=_dd(g.grant_quarter),
                        event_type="grant", transaction_shares=g.shares,
                        transaction_price=ipo_price,
                        strike_price=g.strike_price,
                        transaction_value=g.fair_value_at_grant,
                        shares_held_after=firm.ceo_vested_shares_held,
                        notes=f"Founding IPO {g.grant_type} grant",
                    ))

            state.firms[fid] = firm
            _log(state, f"  {fid}: IPO raised ${ipo_raise/1e6:.0f}M "
                        f"({shares/1e6:.0f}M shares at ${ipo_price:.2f})")

    _bs_snap = _check_bs_invariants(state, "phase_2_ipo", _bs_snap)

    # ── Phase 3: M&A bidding + resolution (if ma_enabled) ────────────────
    if ma_fn is not None:
        try:
            updated_firms, deals = ma_fn(state.firms, state.macro)
            state.firms.update(updated_firms)
            from .engine import ActionLog as _AL
            for deal in deals:
                # Wave gamma: multi-bidder auctions recorded in negotiations_log
                auctions = deal.pop("_auctions", None)
                if auctions:
                    state.negotiations_log.extend(auctions)
                if not deal.get("bidder"):
                    # Synthetic deal carrying auction records only; skip the rest
                    continue
                ma_msg = (f"  M&A Q{state.quarter}: {deal['bidder']} acquires "
                          f"{deal['target']} for "
                          f"${deal.get('price_per_share',0)*1:.2f}/sh "
                          f"(goodwill=${deal['goodwill']/1e6:.0f}M)"
                          + (f" | {deal.get('num_competing_bids',1)} bidders"
                              if deal.get("num_competing_bids", 1) > 1 else ""))
                _log(state, ma_msg)
                print(ma_msg, flush=True)
                state.completed_acquisitions.append(deal)
                _AL.quick_record(
                    state.action_log,
                    actor_id=deal.get("bidder", "unknown_bidder"),
                    action_type="acquire_firm",
                    payload={
                        "target": deal.get("target", ""),
                        "goodwill": deal.get("goodwill", 0),
                        "consideration": deal.get("consideration", 0),
                        "num_competing_bids": deal.get("num_competing_bids", 1),
                        "price_per_share": deal.get("price_per_share", 0),
                    },
                    quarter=state.quarter,
                    mutations=(f"acquired {deal.get('target','')}",),
                )
        except Exception as e:
            _log(state, f"  M&A phase FAILED: {e}")

    _bs_snap = _check_bs_invariants(state, "phase_3_ma", _bs_snap)

    # ── Phase 3.5: Chapter 11 emergence / conversion ──────────────────────
    # Wave ν+10 item 3: firms in Chapter 11 either emerge (operations
    # have stabilized) or convert to Chapter 7 (losses persist). The
    # bankruptcy module computes the transition based on TTM operating
    # income and CFO from the recent compustat panel.
    from .bankruptcy import maybe_emerge_or_convert as _maybe_e
    for fid_ch11, firm_ch11 in list(state.firms.items()):
        if getattr(firm_ch11, "default_type", "") != "chapter_11":
            continue
        firm_rows = [r for r in state.compustat_rows
                     if r.firm_id == fid_ch11][-4:]
        ttm_oi = sum(getattr(r, "oiadpq", 0) or 0 for r in firm_rows)
        ttm_cfo = sum(getattr(r, "oancfq", 0) or 0 for r in firm_rows)
        old_qics = firm_ch11.quarters_in_chapter_11
        new_firm = _maybe_e(firm_ch11, ttm_oi, ttm_cfo)
        if new_firm.default_type == "" and firm_ch11.default_type == "chapter_11":
            _log(state, f"  {fid_ch11}: EMERGED from Chapter 11 after "
                        f"{old_qics} quarters (TTM OI ${ttm_oi/1e6:.1f}M)")
        elif new_firm.default_type == "chapter_7" and firm_ch11.default_type == "chapter_11":
            _log(state, f"  {fid_ch11}: CONVERTED Chapter 11 → Chapter 7 "
                        f"after {old_qics} quarters (persistent losses)")
        state.firms[fid_ch11] = new_firm

    # ── Phase 4: SEC surveillance (if sec_enabled) ─────────────────────
    # Detection tips come from the environment agent (omniscient), not from a
    # hardcoded sigmoid. They accumulate on state from prior quarter's env call
    # and are surfaced to SEC this quarter.
    if sec_fn is not None:
        try:
            from .types import SECInvestigationState
            firm_ids = [fid for fid, f in state.firms.items() if f.is_active]
            detection_tips = list(getattr(state, "pending_detection_tips", []))
            sec_actions = sec_fn(
                [r.as_dict() for r in state.compustat_rows[-len(firm_ids)*4:]],
                state.sec_investigations,
                detection_tips,
                state.macro,
                firm_ids,
            )
            from .sec_agent import advance_investigation
            from .engine import ActionLog as _AL
            for fid, action in sec_actions.items():
                prior_inv = state.sec_investigations.get(
                    fid, SECInvestigationState(firm_id=fid)
                )
                new_inv = advance_investigation(prior_inv, action, state.quarter)
                state.sec_investigations[fid] = new_inv
                if action != "none":
                    _log(state, f"  SEC: {fid} -> {action}")
                    _AL.quick_record(
                        state.action_log,
                        actor_id="sec",
                        action_type=f"sec_{action}",
                        payload={"target_firm": fid, "new_status": new_inv.status},
                        quarter=state.quarter,
                        mutations=(f"SEC status {fid}: {prior_inv.status} -> {new_inv.status}",),
                    )
                    # Wave epsilon: update SEC typed memory
                    from .beliefs import SECMemory as _SM
                    sec_mem = state.sec_memory.setdefault("sec", _SM())
                    # Bump prior on investigation actions
                    if action in ("investigate", "subpoena", "aaer"):
                        sec_mem.firm_priors[fid] = min(
                            1.0, sec_mem.firm_priors.get(fid, 0.0) + 0.2)
                        sec_mem.aging_investigations[fid] = (
                            state.quarter - prior_inv.started_quarter
                            if prior_inv.started_quarter else 0
                        )
                    sec_mem.enforcement_history.append(
                        (state.quarter, fid, action)
                    )
                    # If private contact, notify firm
                    if action == "private_contact" and fid in state.firms:
                        state.firms[fid] = state.firms[fid].evolve(
                            under_sec_investigation=True,
                            sec_investigation_quarter=state.quarter,
                            sec_private_contact_sent=True,
                        )
        except Exception as e:
            _log(state, f"  SEC surveillance FAILED: {e}")

    _bs_snap = _check_bs_invariants(state, "phase_4_sec", _bs_snap)

    # ── Phase 4.5: Activist investor campaigns (if activist_investors_enabled) ──
    # Run BEFORE firm decisions so a target firm sees the campaign in this
    # quarter's prompt and can respond same-Q. (Original placement was
    # Phase 10.5, which delayed responses to Q+1 and produced empty
    # firm_response columns when the campaign launched in the final
    # quarter.) Activist sees PRIOR-quarter compustat + analyst notes, no
    # current-quarter information leaks.
    if activist_fn is not None:
        firm_ids_act = [fid for fid, f in state.firms.items() if f.is_active]
        public_compustat_act = [
            r.as_dict() for r in state.compustat_rows[-len(firm_ids_act)*4:]
        ]
        analyst_dicts_act = [
            {"analyst_id": n.analyst_id, "firm_id": n.firm_id,
             "target_price": n.target_price, "rating": n.rating}
            for n in state.analyst_notes[-20:]
        ]
        try:
            campaigns = activist_fn(
                public_compustat_act, analyst_dicts_act, firm_ids_act,
                state.macro, state.activist_campaigns,
            )
            from .engine import ActionLog as _AL
            from .beliefs import ActivistMemory as _AM
            for c in campaigns:
                state.activist_campaigns.append(c)
                target_fid = c.get("firm_id", "")
                if target_fid:
                    _log(state, f"  Activist → {target_fid}: "
                                f"{c.get('demand_type','')} "
                                f"({c.get('stake_pct_implied',0)*100:.1f}% stake)")
                    _AL.quick_record(
                        state.action_log,
                        actor_id=c.get("activist_id", "activist_1"),
                        action_type="launch_campaign",
                        payload={
                            "target_firm": target_fid,
                            "demand_type": c.get("demand_type", ""),
                            "demand_specifics": c.get("demand_specifics", ""),
                            "stake_pct_implied": c.get("stake_pct_implied", 0.0),
                        },
                        quarter=state.quarter,
                        justification=c.get("thesis", "")[:400],
                    )
                    # Wave epsilon: update activist typed memory
                    aid = c.get("activist_id", "activist_1")
                    mem = state.activist_memory.setdefault(aid, _AM(activist_id=aid))
                    mem.campaigns_launched.append(
                        (state.quarter, target_fid,
                         c.get("demand_type", ""), "pending")
                    )
        except Exception as e:
            _log(state, f"  Activist phase FAILED: {e}")

    # ── Phase 5: Firm decisions ──────────────────────────────────────────

    # Build per-firm info packages: each firm gets ONLY its own private data
    # plus the shared public data. No firm ever receives another firm's private info.
    # Firms are queried in PARALLEL — each call is independent (read-only
    # against state.firms during info-package construction; RawDecisions
    # returned without touching shared state). Parallel firm LLMs
    # roughly halve the dominant cost of a quarter. Controlled via
    # config.parallel_firm_decisions (default True).
    # ── Wave κ: strategic planning phase (pre-decisions) ────────────────
    # Fire a plan-LLM call when:
    #   (a) a firm has no current_plan yet (Q0 or first quarter active), OR
    #   (b) this is a fiscal Q4 (annual cycle), OR
    #   (c) should_replan() returned True (material-variance streak).
    # Planning happens BEFORE this quarter's decisions so firms can see
    # the fresh plan in their decision info package.
    if (config and getattr(config, "strategic_planning_enabled", False)
            and planning_fn is not None):
        from .strategic_planning import should_replan, needs_emergency_replan
        active_fids_plan = [fid for fid, f in state.firms.items() if f.is_active]

        # Wave ν+7: parallelize per-firm planning. Each firm's plan is an
        # independent LLM call — there is no inter-firm state read or
        # mutation in the planning function. Mutations to state.firms
        # are applied serially after all calls return.
        plan_jobs = []  # (fid, firm, info_pkg, prior, recent_vars, emergency, trigger_label)
        for fid in active_fids_plan:
            firm = state.firms[fid]
            last_flows = state.last_quarter_flows.get(fid)
            emergency = needs_emergency_replan(firm, last_flows)
            needs_plan = (
                firm.current_plan is None
                or state.macro.fqtr == 4
                or should_replan(firm)
                or emergency
            )
            if not needs_plan:
                continue
            info_pkg = _build_firm_info_package(state, fid)
            prior = firm.current_plan
            recent_vars = firm.plan_variance_history[-4:]
            plan_jobs.append((fid, firm, info_pkg, prior, recent_vars, emergency))

        def _run_plan(job):
            _fid, _firm, _info, _prior, _rvars, _emerg = job
            try:
                _new_plan = planning_fn(
                    _firm, _info, state.macro, state.params,
                    prior_plan=_prior, recent_variances=_rvars,
                )
                return (_fid, _firm, _new_plan, _emerg, None)
            except Exception as e:
                return (_fid, _firm, None, _emerg, e)

        parallel_plan = (config is None
                         or getattr(config, "parallel_firm_decisions", True))
        if parallel_plan and len(plan_jobs) > 1:
            import concurrent.futures as _cf_plan
            with _cf_plan.ThreadPoolExecutor(
                    max_workers=_max_workers(config, len(plan_jobs))) as _pool_plan:
                plan_results = list(_pool_plan.map(_run_plan, plan_jobs))
        else:
            plan_results = [_run_plan(j) for j in plan_jobs]

        # Apply mutations serially (state.firms is the shared mutable map).
        for fid, firm, new_plan, emergency, err in plan_results:
            if err is not None:
                _log(state, f"  {fid}: planning failed: {err}")
                continue
            # Wave ν+14h F6 fix: if LLM returned an empty plan (no
            # quarterly_lines), don't overwrite the prior plan. Run-6 had
            # 3 of 4 active firms ending Q80 with current_plan having
            # lines=0 — caused by re-plan LLM returning empty shells that
            # silently replaced valid 20-quarter plans.
            if new_plan is not None and not new_plan.lines:
                _log(state, f"  {fid}: planning LLM returned empty plan "
                            f"(no quarterly_lines); KEEPING prior plan unchanged")
                continue
            if new_plan is not None:
                state.firms[fid] = firm.evolve(
                    current_plan=new_plan,
                    material_variance_streak=0,
                )
                trigger = "EMERGENCY (runway<4Q)" if emergency else (
                    "annual" if state.macro.fqtr == 4 else
                    "variance-streak" if should_replan(firm) else "initial"
                )
                _log(state, f"  {fid}: strategic plan issued [{trigger}] "
                            f"({len(new_plan.lines)}Q horizon, "
                            f"id={new_plan.plan_id[:8]})")

    raw_decisions: dict[str, RawDecisions] = {}
    # Wave ν+4: dormant firms (founded but unfunded) are skipped from
    # firm-decision phase — they don't operate, just preserve seed cash.
    active_fids = [
        fid for fid, f in state.firms.items()
        if f.is_active and not f.is_dormant
    ]
    firm_infos = {fid: _build_firm_info_package(state, fid) for fid in active_fids}

    parallel = True
    if config is not None:
        parallel = getattr(config, "parallel_firm_decisions", True)

    if parallel and len(active_fids) > 1:
        import concurrent.futures
        max_workers = _max_workers(config, len(active_fids))
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {
                pool.submit(firm_agent_fn, fid, state.firms[fid],
                             firm_infos[fid], state.params): fid
                for fid in active_fids
            }
            for fut in concurrent.futures.as_completed(futures):
                fid = futures[fut]
                try:
                    raw_decisions[fid] = fut.result()
                except Exception as e:
                    # Wave ν+7: log the FULL traceback (truncated to 1KB) to
                    # the quarter log so we can diagnose the underlying cause
                    # of any firm-agent crash. The previous code only saved
                    # the exception message which lost the call site.
                    import traceback as _tb
                    full_tb = _tb.format_exc()
                    _log(state, f"  {fid}: firm_agent_fn FAILED: {e}\n{full_tb[:1000]}")
                    # Wave ν+7 fix: carry forward prior-Q decisions instead of
                    # using dataclass-default zeros. The previous behavior
                    # silently halted any firm whose agent function raised an
                    # exception (LLM crash, JSON parse error, TypeError in the
                    # decision pipeline, ...) and produced data that looked
                    # like an "absorbing monopoly" but was actually a code
                    # artifact. Carry-forward keeps operations continuous
                    # through transient failures.
                    import uuid as _u
                    prior_flows_obj = (
                        state.last_quarter_flows.get(fid)
                        if state.last_quarter_flows else None
                    )
                    raw_decisions[fid] = _carry_forward_raw_decisions(
                        state.firms[fid],
                        prior_flows_obj,
                        decision_source="fallback",
                        fallback_reason=(
                            f"firm_agent_fn raised: {type(e).__name__}: {str(e)[:200]} | "
                            f"tb={full_tb.replace(chr(10),' | ')[:600]}"
                        ),
                        proposal_id=str(_u.uuid4()),
                    )
    else:
        for fid in active_fids:
            raw_decisions[fid] = firm_agent_fn(
                fid, state.firms[fid], firm_infos[fid], state.params,
            )

    # Stage 12: write activist campaign response back onto the pending
    # campaign dict so `activist_campaigns.csv` carries firm_response +
    # firm_rationale. A firm may be facing multiple pending campaigns;
    # apply the same response to all (rare case, OK for the MVP).
    for fid, raw in raw_decisions.items():
        resp = getattr(raw, "activist_response", None)
        if not resp or not isinstance(resp, dict):
            continue
        response_val = str(resp.get("response", "")).strip().lower()
        if response_val not in {"accept", "reject", "negotiate", "partial"}:
            response_val = "reject"
        rationale = str(resp.get("rationale", ""))[:500]
        for c in state.activist_campaigns:
            if c.get("firm_id") == fid and not c.get("firm_response"):
                c["firm_response"] = response_val
                c["firm_rationale"] = rationale
                _log(state, f"  Activist response: {fid} → {response_val}")
                # Wave epsilon: update activist memory with realized outcome +
                # rolling effectiveness-by-demand-type counter.
                aid = c.get("activist_id", "activist_1")
                if aid in state.activist_memory:
                    mem = state.activist_memory[aid]
                    # Update the pending entry to carry the firm response
                    for i, entry in enumerate(mem.campaigns_launched):
                        q, f_id, d_type, outcome = entry
                        if f_id == fid and outcome == "pending":
                            mem.campaigns_launched[i] = (q, f_id, d_type, response_val)
                            # Track effectiveness by demand type (# accepts / #)
                            eff = mem.strategy_effectiveness.setdefault(
                                d_type, {"n": 0, "accepts": 0})
                            eff["n"] += 1
                            if response_val in ("accept", "partial"):
                                eff["accepts"] += 1
                            break

                # Wave gamma: record this campaign as a 2-round negotiation
                # (activist launch → firm response → activist reaction).
                # If the activist agent supports round2() (LLM-driven), use
                # it; otherwise fall back to deterministic reaction policy.
                from .negotiation import Negotiation as _Neg, Offer as _Off, OutsideOption as _OO
                r2 = getattr(activist_fn, "round2", None) if activist_fn else None
                if r2 is not None:
                    try:
                        reaction = r2(c, response_val, rationale)
                        next_action = reaction.get("next_action", "drop")
                        next_rationale = reaction.get("rationale", "")[:400]
                    except Exception as e:
                        # Fall back to deterministic
                        _log(state, f"  Activist round2 FAILED: {e}")
                        next_action, next_rationale = _deterministic_activist_reaction(response_val)
                else:
                    next_action, next_rationale = _deterministic_activist_reaction(response_val)

                # Map LLM next_action into the deterministic tuple used below.
                if next_action == "accept":
                    activist_next = ("accept", next_rationale or "campaign won")
                elif next_action == "escalate":
                    activist_next = ("counter", next_rationale or "escalate to public campaign")
                else:  # drop
                    activist_next = ("walk", next_rationale or "drop — not worth further pressure")
                act_neg = _Neg.new(
                    topic="activist_campaign",
                    party_a=aid,                    # activist
                    party_b=fid,                    # target firm
                    quarter=state.quarter,
                    max_rounds=3,
                    outside_option=_OO(
                        party_utilities={
                            aid: 0.0,               # activist's next move = exit to cash / other target
                            fid: -0.2,              # firm cost = loss of focus + public distraction
                        },
                        descriptor="activist_outside=drop_stake; firm_outside=defend_strategy_status_quo",
                    ),
                )
                # Round 0: activist's initial demand (the original campaign)
                activist_offer_r0 = _Off(
                    party=aid, round_index=0,
                    payload={
                        "demand_type": c.get("demand_type", ""),
                        "demand_specifics": c.get("demand_specifics", ""),
                        "stake_pct_implied": c.get("stake_pct_implied", 0.0),
                    },
                    rationale=(c.get("thesis") or c.get("demand_specifics") or "")[:300],
                )
                firm_r0_response = _Off(
                    party=fid, round_index=0,
                    payload={"response": response_val},
                    rationale=rationale,
                )
                act_neg.submit_round(
                    proposer_offer=activist_offer_r0,
                    counterparty_response="counter",  # firm always counters (via their response)
                    counterparty_counter=firm_r0_response,
                    counterparty_rationale=rationale,
                )
                # Round 1: activist's reaction (LLM-driven if available).
                activist_offer_r1 = _Off(
                    party=aid, round_index=1,
                    payload={"next_action": activist_next[0]},
                    rationale=activist_next[1],
                )
                if activist_next[0] == "accept":
                    act_neg.submit_round(
                        proposer_offer=activist_offer_r1,
                        counterparty_response="accept",
                        counterparty_rationale=activist_next[1],
                    )
                elif activist_next[0] == "walk":
                    act_neg.submit_round(
                        proposer_offer=activist_offer_r1,
                        counterparty_response="walk",
                        counterparty_rationale=activist_next[1],
                    )
                else:  # counter / escalate
                    act_neg.submit_round(
                        proposer_offer=activist_offer_r1,
                        counterparty_response="counter",  # stay open for next Q
                        counterparty_counter=activist_offer_r1,
                        counterparty_rationale=activist_next[1],
                    )
                state.negotiations_log.append(act_neg.to_record())

    # ── Phase 4: Feasibility clamping + adjudication ──────────────────────
    # Wave beta: each firm RawDecisions is wrapped as an Action, clamping
    # runs as the adjudicator, and the (Action, ActionResult) pair is
    # appended to `state.action_log` → `proposals.jsonl`. This preserves
    # the existing clamping logic unchanged while giving researchers a
    # full audit trail of every proposal, whether accepted or modified.
    from .engine import Action, ActionResult, ActionLog, parse_clamping_log

    clamped_decisions: dict[str, ClampedDecisions] = {}

    for fid, raw in raw_decisions.items():
        firm = state.firms[fid]
        expected_rev = raw.production * raw.price * 0.85
        expected_ar = firm.accounts_receivable

        clamped = clamp_decisions(
            firm=firm,
            decisions=raw,
            expected_revenue=expected_rev,
            expected_ar_collection=expected_ar,
            params=state.params,
        )

        if clamped.clamping_log:
            for msg in clamped.clamping_log:
                _log(state, f"  {fid} clamped: {msg}")

        clamped_decisions[fid] = clamped

        # Record the Action + ActionResult.
        # Payload captures ONLY what the firm proposed (pre-clamp).
        action = Action(
            actor_id=fid,
            action_type="set_quarterly_decisions",
            payload={
                "price": raw.price,
                "production": raw.production,
                "capex": raw.capex,
                "rd_spend": raw.rd_spend,
                "rd_allocation": raw.rd_allocation,
                "sga_spend": raw.sga_spend,
                "equity_issuance_request": getattr(raw, "equity_issuance_request", 0),
                "debt_request": getattr(raw, "debt_request", 0),
                "dividends": raw.dividends,
                "buybacks": raw.buybacks,
                "manipulation_amount": getattr(raw, "manipulation_amount", 0.0),
                "legal_reserve_change": getattr(raw, "legal_reserve_change", 0.0),
                "legal_settlements_paid": getattr(raw, "legal_settlements_paid", 0.0),
                "pension_contribution": getattr(raw, "pension_contribution", 0.0),
                "ceo_sell_shares": getattr(raw, "ceo_sell_shares", 0),
                "ceo_exercise_options": getattr(raw, "ceo_exercise_options", 0),
                "restructuring_severance": getattr(raw, "restructuring_severance", 0.0),
            },
            quarter=state.quarter,
            proposal_id=getattr(raw, "proposal_id", ""),
            justification=getattr(raw, "reasoning", ""),
            source=getattr(raw, "decision_source", "llm"),
        )
        result = ActionResult(
            proposal_id=action.proposal_id,
            accepted=True,  # firms always execute some plan after clamping
            partially_accepted=bool(clamped.clamping_log),
            rejections=parse_clamping_log(action.proposal_id,
                                            clamped.clamping_log),
            mutations=(f"produce {clamped.production} units at ${clamped.price}",
                        f"spend R&D ${clamped.rd_spend:,.0f}, SGA ${clamped.sga_spend:,.0f}"),
            enforcement_rules=tuple(
                # Best-effort: first word of each clamp message is a proxy for rule_id
                msg.split(":", 1)[0].split()[0] if msg else ""
                for msg in clamped.clamping_log
            ),
        )
        ActionLog.record(state.action_log, action, result)

    # ── Phase 5: Market resolution ───────────────────────────────────────

    actions_for_demand = {
        fid: {"price": cd.price, "production": cd.production}
        for fid, cd in clamped_decisions.items()
    }

    # Wave ν+5: demand calibrator — separate LLM voice estimates a
    # generous total-demand anchor BEFORE the env's allocation. Stored
    # on state so the env-prompt builder can include it. Optional —
    # if calibrator_fn is None or returns None, env falls back to
    # deriving demand on its own.
    calibrator_estimate = None
    if demand_calibrator_fn is not None:
        try:
            ic = _build_industry_character_dict(state)
            calibrator_estimate = demand_calibrator_fn(state, ic)
            if calibrator_estimate:
                _log(state, f"  DEMAND_CALIBRATOR Q{state.quarter}: "
                            f"total_units={calibrator_estimate.get('total_units_demanded', 0):,} "
                            f"({calibrator_estimate.get('trend_note', '')[:80]})")
        except Exception as e:
            _log(state, f"  Demand calibrator failed: {e}")
    state.demand_calibrator_last = calibrator_estimate

    # Get environment outcome (from LLM or fallback)
    env_outcome = None
    if env_agent_fn is not None:
        try:
            env_outcome = env_agent_fn(
                actions_for_demand, state.firms, state.macro, state.params
            )
        except Exception as e:
            _log(state, f"  Environment agent failed: {e}. Using fallback.")

    # ── Wave ν+11 E9: independent second-env validator ────────────────────
    # If env_validator_enabled, a second env reads env-1's output and either
    # ratifies it or sends it back with notes. On send_back, env-1 retries
    # ONCE with the notes appended to its prompt. High-bar validator (only
    # sends back on clear inconsistencies) so the simulation's emergent
    # randomness is preserved.
    if (config and getattr(config, "env_validator_enabled", False)
            and env_validator_fn is not None
            and env_agent_fn is not None
            and isinstance(env_outcome, dict)):
        # Build the same inputs the verifier uses (recent revenues +
        # production caps) so the validator has trajectory context.
        recent_revs_v: list[float] = []
        for q_offset in range(1, 5):
            q_rows = [r for r in state.compustat_rows
                      if (r.fyearq - 2031) * 4 + r.fqtr == state.quarter - q_offset]
            if q_rows:
                recent_revs_v.append(sum(r.saleq for r in q_rows))
        production_caps_v = {
            fid: clamped_decisions[fid].production
                 + state.firms.get(fid, FirmState(firm_id=fid)).inventory_units
            for fid in clamped_decisions
        }
        # baseline isn't computed yet at this point — pass 0 as baseline_demand;
        # the validator's prompt only uses it for context, not for thresholding.
        try:
            verdict = env_validator_fn(
                env_outcome, recent_revs_v, 0, production_caps_v, state.macro,
                firms=state.firms,
                params=state.params,
                compustat_rows=state.compustat_rows,
            )
        except Exception as e:
            verdict = {"verdict": "ok", "notes": f"(validator threw: {e})"}
        v = verdict.get("verdict", "ok") if isinstance(verdict, dict) else "ok"
        notes = verdict.get("notes", "") if isinstance(verdict, dict) else ""
        if v == "send_back" and notes:
            _log(state, f"  ENV VALIDATOR send_back: {notes[:200]}")
            try:
                retry = env_agent_fn(
                    actions_for_demand, state.firms, state.macro, state.params,
                    validator_notes=notes,
                )
                if isinstance(retry, dict):
                    env_outcome = retry
                    _log(state, "  ENV VALIDATOR: env-1 regenerated with notes")
            except Exception as e:
                _log(state, f"  ENV VALIDATOR retry failed: {e}; keeping original env output")
        else:
            _log(state, "  ENV VALIDATOR: ok")

        # Wave ν+13 step 2: AFTER the retry round, run the deterministic
        # mandatory-Gen check one more time. If env-1 ignored the notes
        # (run-6 Q24 evidence: firm_0 at $434M, firm_1 at $467M were
        # never granted despite the directive + retry), FORCE-APPLY the
        # grants directly. The strict rule is non-negotiable; env retains
        # authority over allocation + narrative but not over this rule.
        try:
            from .env_verifier import force_apply_mandatory_gen_grants
            env_outcome, forced = force_apply_mandatory_gen_grants(
                env_outcome, state.firms, state.params,
                state.compustat_rows,
            )
            if forced:
                _log(state, f"  ENV VALIDATOR FORCE-GRANT: {', '.join(forced)} "
                            f"(env-1 ignored mandatory directive even after retry)")
        except Exception as e:
            _log(state, f"  ENV VALIDATOR force-grant skipped: {e}")

    # Wave ν+10 item 2: validate the env response against our published
    # schema. Lenient mode — we log violations to gazettes and continue
    # with whatever fields ARE present, so a malformed response degrades
    # the run rather than crashing it. The Wave ν+9 H1 bug (rd_outcomes
    # never read) would have surfaced here on the first quarter.
    if isinstance(env_outcome, dict):
        try:
            from .schemas import validate_lenient
            ok, errs = validate_lenient("env_market_outcome", env_outcome)
            if not ok:
                _log(state, "  ENV SCHEMA: " + " | ".join(errs[:5]))
        except Exception as e:
            _log(state, f"  ENV SCHEMA check failed (non-fatal): {e}")

    # Wave ν+9 Bug H1: merge top-level `rd_outcomes` array into per-firm
    # outcomes immediately, BEFORE any verifier or clamp inspects firm_outcomes.
    # The env prompt schema places product_advance / process_cogs_reduction_pct
    # / delivery_advance in a separate top-level `rd_outcomes` array; without
    # this merge, every R&D advance the env granted was silently dropped.
    # This was the root cause of the zero-Gen2-advance result.
    if isinstance(env_outcome, dict):
        rd_arr = env_outcome.get("rd_outcomes") or []
        if isinstance(rd_arr, list) and isinstance(env_outcome.get("firm_outcomes"), dict):
            for rd in rd_arr:
                if not isinstance(rd, dict):
                    continue
                fid = rd.get("firm_id")
                if not fid or fid not in env_outcome["firm_outcomes"]:
                    continue
                fo = env_outcome["firm_outcomes"][fid]
                if not isinstance(fo, dict):
                    continue
                # Only set the field if firm_outcomes did not already carry
                # it; the env may legitimately put advances in either place.
                if "product_advance" not in fo:
                    fo["product_advance"] = bool(rd.get("product_advance", False))
                if "process_cogs_reduction_pct" not in fo:
                    try:
                        fo["process_cogs_reduction_pct"] = float(
                            rd.get("process_cogs_reduction_pct", 0) or 0
                        )
                    except (TypeError, ValueError):
                        fo["process_cogs_reduction_pct"] = 0.0
                if "delivery_advance" not in fo:
                    fo["delivery_advance"] = bool(rd.get("delivery_advance", False))

    # Always compute baseline — used by verifier (Phase 5.5) AND by fallback path.
    baseline = compute_demand_baseline(
        state.firms, actions_for_demand, state.macro, state.params
    )

    if env_outcome is None:
        # Deterministic fallback
        env_outcome = {
            "total_demand": baseline.total_demand,
            "firm_outcomes": {
                fid: MarketOutcome(
                    firm_id=fid,
                    units_sold=baseline.firm_units.get(fid, 0),
                    market_share=baseline.firm_shares.get(fid, 0),
                )
                for fid in clamped_decisions
            },
            "narrative": f"[Fallback] {baseline.baseline_note}",
        }
    else:
        # ── Phase 5.5: Environment output verification (if env_verification_enabled) ──
        # Before processing the env's output, run a deterministic anomaly check
        # (against recent industry trajectory + production caps + share sums).
        # If anomalous, call the verifier LLM (or fall back to a deterministic
        # clamp if no verifier wired). This catches env hallucinations like
        # "$6B revenue spike" without imposing hardcoded demand formulas.
        if config and getattr(config, "env_verification_enabled", False):
            from .env_verifier import is_anomalous, _deterministic_clamp
            # Recent industry revenue (last 4 quarters)
            recent_revs: list[float] = []
            for q_offset in range(1, 5):
                q_rows = [r for r in state.compustat_rows
                          if (r.fyearq - 2031) * 4 + r.fqtr == state.quarter - q_offset]
                if q_rows:
                    recent_revs.append(sum(r.saleq for r in q_rows))
            # Production caps from clamped decisions (firm.production + inventory)
            production_caps_map = {
                fid: clamped_decisions[fid].production
                     + state.firms.get(fid, FirmState(firm_id=fid)).inventory_units
                for fid in clamped_decisions
            }
            firm_prices_map = {
                fid: clamped_decisions[fid].price
                for fid in clamped_decisions
            }
            anomaly_flag, reasons = is_anomalous(
                env_outcome, recent_revs, baseline.total_demand, production_caps_map,
                firm_prices=firm_prices_map,
            )
            if anomaly_flag:
                _log(state, "  ENV ANOMALY flagged: " + "; ".join(reasons))
                if env_verifier_fn is not None:
                    env_outcome = env_verifier_fn(
                        env_outcome, recent_revs, baseline.total_demand,
                        production_caps_map, state.macro, reasons,
                    )
                    _log(state, f"  ENV VERIFIER applied; new total_demand="
                                f"{env_outcome.get('total_demand', 0):,}")
                else:
                    env_outcome = _deterministic_clamp(
                        env_outcome, baseline.total_demand, production_caps_map,
                        reason="no verifier_fn; fell back to deterministic clamp",
                    )
                    _log(state, f"  ENV CLAMP applied; new total_demand="
                                f"{env_outcome.get('total_demand', 0):,}")

        # Convert env_outcome dict to MarketOutcome objects if needed
        if "firm_outcomes" in env_outcome and isinstance(
            list(env_outcome["firm_outcomes"].values())[0] if env_outcome["firm_outcomes"] else None,
            dict
        ):
            env_outcome["firm_outcomes"] = {
                fid: MarketOutcome(
                    firm_id=fid,
                    units_sold=fo.get("units_sold", 0),
                    market_share=fo.get("market_share", 0),
                    product_rd_advance=fo.get("product_advance", False),
                    process_cogs_reduction_pct=fo.get("process_cogs_reduction_pct", 0),
                    delivery_rd_advance=fo.get("delivery_advance", False),
                )
                for fid, fo in env_outcome["firm_outcomes"].items()
            }

    # Validate and clamp environment output
    firm_outcomes = env_outcome.get("firm_outcomes", {})
    for fid, fo in firm_outcomes.items():
        if isinstance(fo, MarketOutcome):
            max_prod = clamped_decisions.get(fid, ClampedDecisions()).production
            max_prod += state.firms.get(fid, FirmState(firm_id=fid)).inventory_units
            if fo.units_sold > max_prod:
                _log(state, f"  ENV CLAMP: {fid} units_sold {fo.units_sold} -> {max_prod} (production cap)")
                firm_outcomes[fid] = MarketOutcome(
                    firm_id=fid,
                    units_sold=max_prod,
                    market_share=fo.market_share,
                    product_rd_advance=fo.product_rd_advance,
                    process_cogs_reduction_pct=fo.process_cogs_reduction_pct,
                    delivery_rd_advance=fo.delivery_rd_advance,
                )
    env_outcome["firm_outcomes"] = firm_outcomes

    total_demand = env_outcome.get("total_demand", 0)
    narrative = env_outcome.get("narrative", "")
    state.gazettes.append(narrative)

    # Wave θ+ (B-1 audit fix): log env outcome as a structured Action so
    # `proposals.jsonl` carries a full audit trail of environment decisions.
    # One Action per quarter (aggregate, not per-firm — the env is a single
    # omniscient adjudicator). Mutations = the resulting market shares + demand.
    from .engine import ActionLog as _AL_env
    _env_mutations = tuple(
        f"{fid}: units={mo.units_sold:.0f}, share={mo.market_share:.3f}"
        for fid, mo in firm_outcomes.items()
    )
    _AL_env.quick_record(
        state.action_log,
        actor_id="environment",
        action_type="resolve_market",
        payload={
            "total_demand": float(total_demand),
            "n_firm_outcomes": len(firm_outcomes),
            "has_narrative": bool(narrative),
            "narrative_len": len(narrative) if narrative else 0,
            "detection_tips_n": len(state.pending_detection_tips),
        },
        quarter=state.quarter,
        justification=(narrative or "")[:400],
        source="llm" if env_agent_fn is not None else "fallback",
        mutations=_env_mutations,
    )

    # Environment's detection tips → queued for next quarter's SEC call
    state.pending_detection_tips = list(env_outcome.get("detection_tips", []) or [])

    # Environment's operational notes per firm → firm sees next quarter.
    # These tell the firm what actually happened if the env moderated the plan
    # (cash squeeze disrupted production, etc.) — avoids hallucination that
    # their original plan executed as designed.
    env_firm_notes = env_outcome.get("firm_notes", []) or []
    new_notes: dict[str, list] = {}
    for entry in env_firm_notes:
        if not isinstance(entry, dict):
            continue
        fid_n = entry.get("firm_id", "")
        note = entry.get("note", "")
        if fid_n and note:
            new_notes.setdefault(fid_n, []).append(str(note))
    state.pending_env_notes = new_notes

    # Wave ν+10 item 10: clear ibank feedback once it's been seen by the
    # firm (decisions phase already consumed it). Carrying it past two
    # quarters spams the prompt with stale signals.
    state.pending_ibank_feedback = {
        fid: fb for fid, fb in state.pending_ibank_feedback.items()
        if state.quarter - fb.get("issued_quarter", 0) <= 1
    }

    # Stage 10: environment can override specific firm decisions when the
    # firm's budget is infeasible (e.g., SGA=$0 with 100 employees). The
    # orchestrator patches the ClampedDecisions field with the env's "actual"
    # value before accounting runs.
    if config and getattr(config, "env_decision_overrides_enabled", False):
        from dataclasses import replace as _dc_replace2
        overrides = env_outcome.get("decision_overrides", []) or []
        # Fields that can be overridden (structural whitelist).
        _overridable_fields = {
            "price", "production", "capex", "rd_spend", "sga_spend",
            "dividends", "buybacks",
            "payables_days_target", "receivables_days_target", "deposit_pct",
            "ppe_disposal", "allowance_pct_of_ar",
            "restructuring_severance", "restructuring_ppe_impairment",
            "restructuring_inventory_write_off", "restructuring_goodwill_impairment",
        }
        for ov in overrides:
            if not isinstance(ov, dict):
                continue
            fid_o = ov.get("firm_id", "")
            field = ov.get("field", "")
            if fid_o not in clamped_decisions or field not in _overridable_fields:
                continue
            # Skip if env didn't actually provide a value (None / missing)
            raw_actual = ov.get("actual")
            if raw_actual is None:
                continue
            try:
                actual = float(raw_actual)
            except (TypeError, ValueError):
                continue
            budgeted = ov.get("budgeted", "?")
            reasoning = ov.get("reasoning", "")
            cur = clamped_decisions[fid_o]
            # Type-aware cast
            new_value: object = actual
            if field == "production":
                new_value = int(max(0, actual))
            clamped_decisions[fid_o] = _dc_replace2(cur, **{field: new_value})
            _log(state, f"  ENV OVERRIDE {fid_o}.{field}: "
                        f"firm targeted {budgeted}, actual={new_value} "
                        f"| {reasoning[:100]}")

    # Stage 5: environment decides actual AR write-offs this quarter.
    # Parse into a per-firm map and patch onto each firm's ClampedDecisions
    # before accounting runs (accounting consumes decisions.write_offs_this_quarter).
    if config and getattr(config, "bad_debt_enabled", False):
        from dataclasses import replace as _dc_replace
        write_off_list = env_outcome.get("write_offs", []) or []
        write_off_map: dict[str, float] = {}
        for entry in write_off_list:
            if not isinstance(entry, dict):
                continue
            fid_wo = entry.get("firm_id", "")
            try:
                amt = float(entry.get("amount", 0) or 0)
            except (TypeError, ValueError):
                amt = 0.0
            if fid_wo and amt > 0:
                write_off_map[fid_wo] = max(0.0, amt)
        for fid_c, clamped_c in clamped_decisions.items():
            wo = write_off_map.get(fid_c, 0.0)
            if wo > 0:
                clamped_decisions[fid_c] = _dc_replace(clamped_c,
                                                       write_offs_this_quarter=wo)
                _log(state, f"  {fid_c}: ENV WRITE-OFF ${wo/1e6:.2f}M "
                            f"(decided by environment)")

    _log(state, f"  Market: {total_demand} units sold industry-wide")

    # ── Phase 5.7: CEO comp accrual (Stage 11) ────────────────────────────
    # Each quarter, accrue CEO base salary (cash) + GAAP SBC amortization
    # (non-cash, FV × fraction vesting this Q). SGA + APIC post via
    # accounting Phase 6 below. ADD to existing field so any governance-
    # added bonus from last Q4 carries forward. Accounting zeroes the
    # fields after consuming them. Only runs when governance_enabled.
    if config and getattr(config, "governance_enabled", False):
        from .ceo_comp import quarterly_sbc_expense
        for fid, firm in list(state.firms.items()):
            if not firm.is_active or not firm.ceo_type:
                continue
            base_q = firm.ceo_base_salary / 4.0
            sbc_q = quarterly_sbc_expense(firm, state.quarter)
            state.firms[fid] = firm.evolve(
                ceo_cash_comp_this_q=firm.ceo_cash_comp_this_q + base_q,
                ceo_stock_comp_this_q=firm.ceo_stock_comp_this_q + sbc_q,
            )

    _bs_snap = _check_bs_invariants(state, "phase_5_7_ceo_accrual", _bs_snap)

    # ── Phase 6: Accounting postings ─────────────────────────────────────

    new_firms = {}
    all_flows = {}

    for fid, clamped in clamped_decisions.items():
        firm = state.firms[fid]
        outcome = env_outcome["firm_outcomes"].get(
            fid,
            MarketOutcome(firm_id=fid, units_sold=0, market_share=0)
        )

        new_state, flows = post_quarter(firm, clamped, outcome, state.params)
        new_firms[fid] = new_state
        all_flows[fid] = flows

        # Validate
        violations = validate_state(new_state, flows, firm, decisions=clamped)
        if violations:
            for v in violations:
                _log(state, f"  INVARIANT VIOLATION {fid}: {v}")

        # NOTE: Compustat row is built AFTER Phase 7b (financing) so it
        # captures debt/equity issuances on the balance sheet.

        _log(state, f"  {fid}: Rev=${flows.net_sales/1e6:.1f}M "
                    f"NI=${flows.net_income/1e6:.1f}M "
                    f"Cash=${new_state.cash/1e6:.1f}M "
                    f"Share={outcome.market_share:.1%}")

    # Save prior states for report generation BEFORE updating
    prior_states = {fid: state.firms[fid] for fid in new_firms}

    state.firms.update(new_firms)
    state.last_quarter_flows = all_flows

    _bs_snap = _check_bs_invariants(state, "phase_6_accounting", _bs_snap)

    # ── Wave κ: plan-variance computation (post-accounting) ─────────────
    # For each firm with a current_plan, compare this quarter's actuals
    # vs plan line. Append PlanVariance to history. Bump
    # material_variance_streak if variance is material; reset if not.
    if config and getattr(config, "strategic_planning_enabled", False):
        from .strategic_planning import compute_plan_variance
        for fid, firm in list(state.firms.items()):
            if not firm.is_active or firm.current_plan is None:
                continue
            flows = all_flows.get(fid)
            if flows is None:
                continue
            variance = compute_plan_variance(
                firm, firm.current_plan, flows,
                fyear=state.macro.fyear, fqtr=state.macro.fqtr,
            )
            if variance is None:
                continue
            new_history = firm.plan_variance_history + (variance,)
            # Cap history at 20 entries
            if len(new_history) > 20:
                new_history = new_history[-20:]
            new_streak = (firm.material_variance_streak + 1
                          if variance.is_material else 0)
            state.firms[fid] = firm.evolve(
                plan_variance_history=new_history,
                material_variance_streak=new_streak,
            )

    # ── Phase 6.5: Debt facility amortization (if debt_covenants_enabled) ──
    # Accrues interest + applies scheduled principal on each active facility.
    # No-op when no facilities exist — safe backward-compat.
    # NOTE: when facilities exist AND accounting.py's legacy interest
    # calculation is still active, this can double-count. Stage 3c coordinates
    # the transition by having the investment bank wrap new debt as facilities
    # and accounting skip facility-held debt for its aggregate interest calc.
    if config and getattr(config, "debt_covenants_enabled", False):
        from .debt_management import amortize_quarter
        from dataclasses import replace as _dc_replace
        for fid, firm in list(state.firms.items()):
            if not firm.is_active or not firm.debt_facilities:
                continue
            new_firm, interest_paid, principal_paid = amortize_quarter(firm, state.quarter)
            # Route facility debt service through flows and firm state so:
            #   (a) compustat row cash identity holds: ΔCash = CFO + CFI + CFF
            #   (b) IS shows full interest burden (legacy + facility)
            #   (c) RE / equity drop by facility interest (not just cash)
            # Tax effect of additional interest ignored (pre-profit firms).
            if (interest_paid > 0 or principal_paid > 0) and fid in all_flows:
                fl = all_flows[fid]
                all_flows[fid] = _dc_replace(
                    fl,
                    interest_expense=fl.interest_expense + interest_paid,
                    pretax_income=fl.pretax_income - interest_paid,
                    net_income=fl.net_income - interest_paid,
                    reported_net_income=fl.reported_net_income - interest_paid,
                    cfo=fl.cfo - interest_paid,
                    cff=fl.cff - principal_paid,
                    change_in_cash=fl.change_in_cash - interest_paid - principal_paid,
                )
                # Retained earnings also absorbs the interest hit. Firm cash was
                # already debited inside amortize_quarter.
                new_firm = new_firm.evolve(
                    retained_earnings=new_firm.retained_earnings - interest_paid,
                )
            state.firms[fid] = new_firm
            # Re-validate post-amortize so any arithmetic drift in the flow
            # adjustment above surfaces immediately (catches F4/F2 regressions).
            if interest_paid > 0 or principal_paid > 0:
                prior_firm_for_val = prior_states.get(fid)
                clamped_for_val = clamped_decisions.get(fid)
                if prior_firm_for_val is not None and clamped_for_val is not None:
                    violations = validate_state(new_firm, all_flows[fid],
                                                prior_firm_for_val,
                                                decisions=clamped_for_val)
                    for v in violations:
                        _log(state, f"  POST-AMORTIZE INVARIANT {fid}: {v}")
                _log(state, f"  {fid}: facility serviced "
                            f"interest=${interest_paid/1e6:.2f}M "
                            f"principal=${principal_paid/1e6:.2f}M")

    # Generate operational reports (R&D + brand) using prior vs current
    for fid, firm in state.firms.items():
        if not firm.is_active or fid not in all_flows:
            continue
        flows = all_flows[fid]
        prior = prior_states.get(fid, firm)

        rd_report = generate_rd_report(firm, prior, flows, state.params, state.rng)
        brand_report = generate_brand_report(firm, prior, flows, state.params, state.rng)
        state.rd_reports[fid] = rd_report
        state.brand_reports[fid] = brand_report

    # Build/update product specs
    quarter_specs = {}
    for fid, firm in state.firms.items():
        if not firm.is_active:
            continue
        flows = all_flows.get(fid)
        prior_spec = state.product_specs.get(fid)
        spec = build_product_spec(firm, flows, prior_spec, state.params)
        state.product_specs[fid] = spec
        quarter_specs[fid] = format_product_spec(spec)
    state.product_spec_history.append(quarter_specs)

    _bs_snap = _check_bs_invariants(state, "phase_6_5_amortize", _bs_snap)

    # ── Phase 9: Earnings announcement (if earnings_announcement_enabled) ──
    # Each firm's announcement is independent → parallelize.
    if earnings_announcement_fn is not None:
        ea_candidates = []
        for fid, firm in state.firms.items():
            if not firm.is_active or fid not in all_flows:
                continue
            flows = all_flows[fid]
            prior_guidance = None
            for rel in reversed(state.earnings_releases):
                if rel.firm_id == fid:
                    prior_guidance = {
                        "guidance_eps_1q": rel.guidance_eps_1q,
                        "guidance_eps_1y": rel.guidance_eps_1y,
                    }
                    break
            ea_candidates.append((fid, firm, flows, prior_guidance))

        def _run_ea(args):
            _fid, _firm, _flows, _pg = args
            try:
                return (_fid, earnings_announcement_fn(
                    _fid, _firm, _flows, state.macro, _pg))
            except Exception as e:
                return (_fid, e)

        parallel_ea = (config is None
                       or getattr(config, "parallel_firm_decisions", True))
        if parallel_ea and len(ea_candidates) > 1:
            import concurrent.futures as _cf
            with _cf.ThreadPoolExecutor(
                    max_workers=_max_workers(config, len(ea_candidates))) as pool:
                results = list(pool.map(_run_ea, ea_candidates))
        else:
            results = [_run_ea(a) for a in ea_candidates]

        from .engine import ActionLog as _AL
        for fid, release in results:
            if isinstance(release, Exception):
                _log(state, f"  EA {fid} FAILED: {release}")
                continue
            state.earnings_releases.append(release)
            _log(state, f"  EA: {fid} EPS=${release.reported_eps:.2f} "
                        f"guidance_1Q=${release.guidance_eps_1q:.2f}")
            _AL.quick_record(
                state.action_log,
                actor_id=fid, action_type="issue_earnings_release",
                payload={
                    "reported_eps": release.reported_eps,
                    "reported_revenue": release.reported_revenue,
                    "guidance_eps_1q": release.guidance_eps_1q,
                    "guidance_eps_1y": release.guidance_eps_1y,
                    "guidance_revenue_1q": release.guidance_revenue_1q,
                },
                quarter=state.quarter,
                justification=(release.management_discussion or "")[:400],
            )

    # ── Phase 10: Sell-side analyst coverage (if sellside_analysts_enabled) ──
    if sellside_analyst_fns:
        from .sellside_analyst import should_publish
        firm_ids = [fid for fid, f in state.firms.items() if f.is_active]
        public_compustat = [r.as_dict() for r in state.compustat_rows[-len(firm_ids)*4:]]
        releases_dicts = [
            {"firm_id": r.firm_id, "reported_eps": r.reported_eps,
             "guidance_eps_1q": r.guidance_eps_1q}
            for r in state.earnings_releases[-len(firm_ids)*2:]
        ]
        prior_notes_dicts = [
            {"analyst_id": n.analyst_id, "firm_id": n.firm_id,
             "target_price": n.target_price, "rating": n.rating}
            for n in state.analyst_notes[-20:]
        ]

        # Parallelize analysts: each is an independent LLM call, they don't
        # depend on each other's notes within a quarter. ~3x speedup for
        # sell-side coverage (most notable when all 3 publish same quarter).
        import concurrent.futures as _cf
        active_analysts = [
            (i, analyst_fn) for i, analyst_fn in enumerate(sellside_analyst_fns)
            if should_publish(f"analyst_{i+1}", state.macro.fqtr)
        ]
        if active_analysts:
            parallel = True
            if config is not None:
                parallel = getattr(config, "parallel_firm_decisions", True)
            def _run_analyst(idx_fn):
                _i, _fn = idx_fn
                _aid = f"analyst_{_i+1}"
                try:
                    return (_aid, _fn(public_compustat, releases_dicts,
                                       prior_notes_dicts, state.macro, firm_ids))
                except Exception as e:
                    return (_aid, e)
            if parallel and len(active_analysts) > 1:
                with _cf.ThreadPoolExecutor(max_workers=len(active_analysts)) as pool:
                    results = list(pool.map(_run_analyst, active_analysts))
            else:
                results = [_run_analyst(a) for a in active_analysts]
            from .engine import ActionLog as _AL
            for analyst_id, notes_or_err in results:
                if isinstance(notes_or_err, Exception):
                    _log(state, f"  Analyst {analyst_id} FAILED: {notes_or_err}")
                    continue
                state.analyst_notes.extend(notes_or_err)
                for note in notes_or_err:
                    _log(state, f"  Analyst {analyst_id}: {note.firm_id} "
                                f"TP=${note.target_price:.2f} ({note.rating})")
                    _AL.quick_record(
                        state.action_log,
                        actor_id=analyst_id, action_type="publish_note",
                        payload={
                            "target_firm": note.firm_id,
                            "target_price": note.target_price,
                            "rating": note.rating,
                            "eps_forecast_1q": note.eps_forecast_1q,
                            "eps_forecast_1y": note.eps_forecast_1y,
                            "methodology": note.methodology,
                        },
                        quarter=state.quarter,
                        justification=(note.narrative or "")[:400],
                    )

    # ── Phase 11: Equity Market prices PUBLIC firms ─────────────────────────
    # Wave λ: only PUBLIC firms (is_public=True) have a market-determined
    # price. Private firms' valuation is the last PE round's post-money
    # (tracked on last_round_valuation) — not updated here.
    _log(state, "  --- Equity Market ---")
    if equity_market_fn is not None:
        try:
            public_firms = {
                fid: f for fid, f in state.firms.items() if f.is_public
            }
            eq_decisions = (equity_market_fn(public_firms, state.macro, state.params)
                            if public_firms else {})
            if eq_decisions:
                # Wave ν+14l: mild deterministic price-sanity guard.
                # Catches obviously-broken values (e.g., run-8 firm_18 going
                # \$60 → \$60,000 in one quarter — 1000× spike). Not heavy-
                # handed: only fires on extreme single-Q moves, clamps to a
                # still-substantial 5× change (so genuine catalysts still
                # produce big moves), and logs for visibility. Per user
                # direction: 'just have it review if numbers seem very odd'.
                _MAX_Q_MOVE = 20.0  # >20× change triggers review
                _CLAMP_Q_MOVE = 5.0  # clamp to 5× move (still big)
                for fid, terms in list(eq_decisions.items()):
                    firm = public_firms.get(fid)
                    if firm is None or firm.equity_price <= 0:
                        continue
                    new_price = float(terms.get("equity_price", 0) or 0)
                    if new_price <= 0:
                        continue
                    prior = float(firm.equity_price)
                    ratio = new_price / prior
                    if ratio > _MAX_Q_MOVE:
                        capped = prior * _CLAMP_Q_MOVE
                        msg = (f"  EQUITY SANITY: {fid} panel-proposed "
                               f"${new_price:,.2f} is {ratio:.0f}× prior "
                               f"${prior:.2f} — likely LLM error; clamping to "
                               f"${capped:,.2f} ({_CLAMP_Q_MOVE:.0f}× still a "
                               f"big move). Method was: "
                               f"{terms.get('method', '')[:80]}")
                        _log(state, msg)
                        terms["equity_price"] = capped
                    elif ratio < 1.0 / _MAX_Q_MOVE:
                        capped = prior / _CLAMP_Q_MOVE
                        msg = (f"  EQUITY SANITY: {fid} panel-proposed "
                               f"${new_price:,.2f} is {1/ratio:.0f}× DROP from "
                               f"prior ${prior:.2f} — likely LLM error; "
                               f"clamping to ${capped:,.2f}")
                        _log(state, msg)
                        terms["equity_price"] = capped
                # Wave θ+ (B-1 audit fix): log equity market pricing as a
                # structured Action per firm so `proposals.jsonl` covers it.
                from .engine import ActionLog as _AL_eq
                for fid, terms in eq_decisions.items():
                    if fid in state.firms and state.firms[fid].is_active and state.firms[fid].is_public:
                        price = terms.get("equity_price", 0)
                        if price > 0:
                            state.firms[fid] = state.firms[fid].evolve(equity_price=price)
                        reasoning = terms.get("reasoning", "")
                        method = terms.get("method", "")
                        _log(state, f"  {fid}: ${price:.2f}/sh ({method}) {reasoning[:100]}")
                        _AL_eq.quick_record(
                            state.action_log,
                            actor_id="equity_market",
                            action_type="price_equity",
                            payload={
                                "target_firm": fid,
                                "equity_price": float(price),
                                "method": method or "",
                            },
                            quarter=state.quarter,
                            justification=(reasoning or "")[:400],
                        )
        except Exception as e:
            _log(state, f"  Equity Market FAILED: {e}")

    _bs_snap = _check_bs_invariants(state, "phase_11_equity_market", _bs_snap)

    # ── Phase 11.5: Convertible bond conversion trigger ───────────────────
    # After equity market sets the price, any convertible bond in the money
    # (current share price ≥ conversion_price) with status "current" or
    # "amended" gets converted. Arbitrageurs would force this in real markets
    # (buy bond at face, convert to stock, sell stock for a profit). Emergent
    # trigger: no LLM decision needed — pure arithmetic check.
    if (config and getattr(config, "debt_covenants_enabled", False)
            and getattr(config, "convertible_debt_enabled", False)):
        from .debt_management import convert_facility as _convert
        for fid, firm in list(state.firms.items()):
            if not firm.is_active or not firm.debt_facilities:
                continue
            for fac in firm.debt_facilities:
                if (fac.facility_type == "convertible_bond"
                        and fac.status in ("current", "amended", "in_cure_period")
                        and fac.current_balance > 0
                        and fac.conversion_price > 0
                        and firm.equity_price >= fac.conversion_price):
                    new_firm, info = _convert(firm, fac.facility_id, state.quarter)
                    state.firms[fid] = new_firm
                    firm = new_firm  # refresh for next facility in same firm
                    _log(state, f"  {fid}: CONVERSION {fac.facility_id} "
                                f"${info['converted_balance']/1e6:.1f}M "
                                f"→ {info['new_shares']:,} shares "
                                f"(price ${firm.equity_price:.2f} ≥ strike ${fac.conversion_price:.2f})")

    _bs_snap = _check_bs_invariants(state, "phase_11_5_convertible_conv", _bs_snap)

    # ── Phase 11.6: CEO vesting + sell + option exercise (Stage 11/12) ──
    # Every quarter: (1) check grant vesting schedules, (2) apply CEO sell
    # decision on vested RSU shares, (3) apply CEO option-exercise decision
    # (pay strike × count, receive shares — dilutive to firm). Events logged
    # to `state.insider_events` for WRDS-style Form 4 disclosures.
    if config and getattr(config, "governance_enabled", False):
        from .ceo_comp import vest_grants_this_quarter, sell_vested_shares
        from .types import InsiderTradingEvent
        from .wrds_identifiers import abs_quarter_to_datadate
        for fid, firm in list(state.firms.items()):
            if not firm.is_active:
                continue
            # 1. Vest
            if firm.ceo_stock_grants:
                firm, vested = vest_grants_this_quarter(firm, state.quarter)
                if vested > 0:
                    _log(state, f"  {fid}: CEO vested {vested:,} RSU shares "
                                f"(now holds {firm.ceo_vested_shares_held:,})")
            # 2. Sell
            clamped = clamped_decisions.get(fid, ClampedDecisions())
            sell_qty = int(clamped.ceo_sell_shares)
            if sell_qty > 0 and firm.ceo_vested_shares_held > 0:
                before = firm.ceo_vested_shares_held
                firm = sell_vested_shares(firm, sell_qty, firm.equity_price, state.quarter)
                sold = before - firm.ceo_vested_shares_held
                if sold > 0:
                    _log(state, f"  {fid}: CEO sold {sold:,} shares "
                                f"@ ${firm.equity_price:.2f} = "
                                f"${sold * firm.equity_price / 1e6:.2f}M proceeds")
                    state.insider_events.append(InsiderTradingEvent(
                        run_id=state.run_id, firm_id=fid,
                        ceo_id=firm.ceo_type, ceo_incarnation=firm.ceo_incarnation,
                        event_quarter=state.quarter,
                        event_date=abs_quarter_to_datadate(state.quarter),
                        event_type="sell", transaction_shares=sold,
                        transaction_price=firm.equity_price,
                        transaction_value=sold * firm.equity_price,
                        shares_held_after=firm.ceo_vested_shares_held,
                        notes="open-market sale",
                    ))
            # 3. Option exercise (Stage 12)
            exercise_qty = int(clamped.ceo_exercise_options)
            if exercise_qty > 0:
                # Walk grants, exercise pro-rata across vested options with
                # strike < current price (in-the-money). Exercise at strike;
                # deliver shares (dilutive, adds to firm shares_outstanding
                # AND to CEO's vested_shares_held).
                remaining = exercise_qty
                new_grants = []
                total_exercised = 0
                total_strike_paid = 0.0
                for g in firm.ceo_stock_grants:
                    if (remaining <= 0 or g.ceo_incarnation != firm.ceo_incarnation
                            or g.grant_type != "stock_option"):
                        new_grants.append(g)
                        continue
                    vested_avail = g.shares_vested_to_date - g.shares_exercised
                    # Only exercise in-the-money (rational)
                    if vested_avail <= 0 or firm.equity_price <= g.strike_price:
                        new_grants.append(g)
                        continue
                    exercise_here = min(remaining, vested_avail)
                    total_exercised += exercise_here
                    total_strike_paid += exercise_here * g.strike_price
                    remaining -= exercise_here
                    from dataclasses import replace as _r
                    new_grants.append(_r(g, shares_exercised=g.shares_exercised + exercise_here))
                if total_exercised > 0:
                    firm = firm.evolve(
                        ceo_stock_grants=tuple(new_grants),
                        ceo_vested_shares_held=firm.ceo_vested_shares_held + total_exercised,
                        # CEO's personal cash OUT by strike (then they hold shares)
                        ceo_cash_from_sales=firm.ceo_cash_from_sales - total_strike_paid,
                        # Firm receives strike cash; shares issued (dilutive)
                        cash=firm.cash + total_strike_paid,
                        shares_outstanding=firm.shares_outstanding + total_exercised,
                        # APIC up by cash received (simplified; ignoring par-value accounting)
                        apic=firm.apic + total_strike_paid,
                    )
                    _log(state, f"  {fid}: CEO exercised {total_exercised:,} options "
                                f"@ avg strike → paid ${total_strike_paid/1e6:.2f}M, "
                                f"received shares (worth ${total_exercised * firm.equity_price/1e6:.2f}M "
                                f"at market)")
                    state.insider_events.append(InsiderTradingEvent(
                        run_id=state.run_id, firm_id=fid,
                        ceo_id=firm.ceo_type, ceo_incarnation=firm.ceo_incarnation,
                        event_quarter=state.quarter,
                        event_date=abs_quarter_to_datadate(state.quarter),
                        event_type="exercise", transaction_shares=total_exercised,
                        transaction_price=firm.equity_price,
                        strike_price=(total_strike_paid / total_exercised
                                      if total_exercised else 0.0),
                        transaction_value=total_strike_paid,
                        shares_held_after=firm.ceo_vested_shares_held,
                        notes="option exercise (cash paid, shares received)",
                    ))
            state.firms[fid] = firm

    _bs_snap = _check_bs_invariants(state, "phase_11_6_ceo_ops", _bs_snap)

    # ── Wave ν+12: Investor voice (per-firm market commentary) ────────────
    # Runs AFTER the equity market marks share prices so the voice has the
    # freshest publicly-observable signal. Notes are stored on state and
    # rendered into the firm decision prompt NEXT quarter — a one-quarter
    # asynchronous loop, no synchronous coupling with firm decisions.
    if (config and getattr(config, "investor_voice_enabled", False)
            and investor_voice_fn is not None):
        # Build a global public-competitors view (snapshot per active firm).
        # The investor voice for firm X sees all other firms as peers.
        all_public = {}
        for _pfid, _pfirm in state.firms.items():
            if not _pfirm.is_active:
                continue
            _flows = state.last_quarter_flows.get(_pfid)
            all_public[_pfid] = {
                "price": _flows.actual_price if _flows else 0,
                "market_share": _flows.market_share if _flows else 0,
                "generation": _pfirm.product_generation,
                "equity_price": _pfirm.equity_price,
                "revenue": _flows.net_sales if _flows else 0,
            }
        # Industry character string for context
        ic_str = ""
        try:
            scenario = getattr(state, "_scenario", None)
            ic = getattr(scenario, "industry_character", None) if scenario else None
            if ic is not None:
                ic_str = (
                    f"Industry: {ic.label}\n"
                    f"TAM at maturity (annual): ${ic.tam_at_maturity_usd/1e9:.1f}B\n"
                    f"Years to maturity (indicative): {ic.years_to_maturity}"
                )
        except Exception:
            ic_str = ""
        for fid, firm in state.firms.items():
            if not firm.is_active:
                continue
            # Public peer panel for this firm = everyone else who is active
            peer_panel = {pid: p for pid, p in all_public.items() if pid != fid}
            own_panel = []
            for r in state.compustat_rows[-200:]:
                if r.firm_id != fid:
                    continue
                own_panel.append({
                    "fyearq": r.fyearq, "fqtr": r.fqtr,
                    "saleq": r.saleq, "niq": r.niq, "cheq": r.cheq,
                    "dlttq": getattr(r, "long_term_debt", 0),
                    "prccq": r.prccq,
                })
            try:
                note = investor_voice_fn(
                    firm, peer_panel, state.macro,
                    own_panel, ic_str,
                )
            except Exception:
                note = ""
            if note:
                state.investor_notes_by_firm[fid] = note

    # ── Delisting counter update (after equity market sets final price) ──
    # A firm trading below the delisting threshold for N consecutive quarters
    # will be defaulted in the settlement phase.
    # Wave λ: the delisting check only applies to PUBLIC firms. Private
    # firms (is_public=False) have no market price by design — their
    # valuation is set at PE rounds, not continuously traded.
    price_threshold = config.delisting_price_threshold if config else 1.00
    for fid, firm in state.firms.items():
        if not firm.is_active:
            continue
        if not firm.is_public:
            # Private firm: reset counter, no price-based delisting risk
            if firm.quarters_below_delisting_threshold != 0:
                state.firms[fid] = firm.evolve(quarters_below_delisting_threshold=0)
            continue
        if firm.equity_price < price_threshold:
            new_count = firm.quarters_below_delisting_threshold + 1
        else:
            new_count = 0
        state.firms[fid] = firm.evolve(quarters_below_delisting_threshold=new_count)

    _bs_snap = _check_bs_invariants(state, "delisting_counter", _bs_snap)

    # ── Phase 7b: Investment Bank evaluates term debt + equity requests ────
    _log(state, "  --- Investment Bank ---")
    if investment_bank_fn is not None:
        try:
            ib_decisions = investment_bank_fn(
                state.firms, state.macro, state.params, raw_decisions
            )
            # Wave gamma: record debt-pricing negotiations (firm requests X at
            # rate Y; IB responds with approved_amount Z at rate W). One
            # 1-round negotiation per (firm, request) pair.
            from .negotiation import Negotiation, Offer, OutsideOption
            if ib_decisions:
                for fid, terms in ib_decisions.items():
                    raw = raw_decisions.get(fid)
                    if raw is not None and (getattr(raw, "debt_request", 0)
                                              or getattr(raw, "equity_issuance_request", 0)):
                        debt_neg = Negotiation.new(
                            topic="debt_pricing",
                            party_a=fid, party_b="investment_bank",
                            quarter=state.quarter, max_rounds=3,
                            outside_option=OutsideOption(
                                party_utilities={
                                    fid: -0.5,                 # no capital → operational risk
                                    "investment_bank": 0.0,    # bank just doesn't book the deal
                                },
                                descriptor="firm_outside=no_financing; ib_outside=no_deal_booked",
                            ),
                        )
                        firm_offer = Offer(
                            party=fid, round_index=0,
                            payload={
                                "debt_requested": getattr(raw, "debt_request", 0),
                                "equity_requested": getattr(raw, "equity_issuance_request", 0),
                            },
                            rationale=getattr(raw, "reasoning", "")[:300],
                        )
                        ib_counter = Offer(
                            party="investment_bank", round_index=0,
                            payload={
                                "term_debt_approved": terms.get("term_debt_approved", 0),
                                "term_debt_rate": terms.get("term_debt_rate", 0.0),
                                "equity_approved": terms.get("equity_approved", 0),
                                "equity_price": terms.get("equity_price", 0.0),
                                "facility_type": (terms.get("facility_structure") or {}).get(
                                    "facility_type", ""),
                            },
                            rationale=terms.get("reasoning", "")[:400],
                        )
                        # Accept if IB approved any portion; walk away if none.
                        approved_anything = (terms.get("term_debt_approved", 0) > 0
                                              or terms.get("equity_approved", 0) > 0)
                        response = "accept" if approved_anything else "walk"
                        debt_neg.submit_round(
                            proposer_offer=firm_offer,
                            counterparty_response=response,
                            counterparty_counter=ib_counter,
                            counterparty_rationale=terms.get("reasoning", "")[:400],
                        )
                        state.negotiations_log.append(debt_neg.to_record())
                        # Also record as a structured Action for the proposals log.
                        from .engine import ActionLog as _AL_ib
                        _AL_ib.quick_record(
                            state.action_log,
                            actor_id="investment_bank",
                            action_type="underwrite",
                            payload={
                                "target_firm": fid,
                                "term_debt_approved": terms.get("term_debt_approved", 0),
                                "term_debt_rate": terms.get("term_debt_rate", 0.0),
                                "equity_approved": terms.get("equity_approved", 0),
                                "equity_price": terms.get("equity_price", 0.0),
                                "linked_negotiation_id": debt_neg.negotiation_id,
                            },
                            quarter=state.quarter,
                            justification=(terms.get("reasoning") or "")[:400],
                            accepted=approved_anything,
                        )
                for fid, terms in ib_decisions.items():
                    if fid not in state.firms or not state.firms[fid].is_active:
                        continue
                    updates = {}

                    # Wave ν+10 item 10: capture market discussion + retry
                    # guidance whenever the bank produced one (typically on
                    # decline/haircut). Persist on state so next quarter's
                    # firm prompt sees the public market signal and can
                    # resubmit a modified issuance request.
                    md = (terms.get("market_discussion") or "").strip()
                    rg = (terms.get("retry_guidance") or "").strip()
                    requested_debt = (raw_decisions.get(fid).debt_principal_request > 0
                                       if raw_decisions and fid in raw_decisions
                                       and hasattr(raw_decisions.get(fid), "debt_principal_request")
                                       else False)
                    requested_equity = (raw_decisions.get(fid).equity_offering_request > 0
                                         if raw_decisions and fid in raw_decisions
                                         and hasattr(raw_decisions.get(fid), "equity_offering_request")
                                         else False)
                    declined_debt = requested_debt and (terms.get("term_debt_approved", 0) or 0) <= 0
                    declined_equity = requested_equity and (terms.get("equity_approved", 0) or 0) <= 0
                    if (declined_debt or declined_equity) and (md or rg):
                        state.pending_ibank_feedback[fid] = {
                            "market_discussion": md[:600],
                            "retry_guidance": rg[:400],
                            "issued_quarter": state.quarter,
                            "declined_debt": declined_debt,
                            "declined_equity": declined_equity,
                        }
                        _log(state, f"  IBANK FEEDBACK to {fid}: "
                                    f"{md[:120]}... | retry: {rg[:80]}")

                    # Term debt
                    term_amt = terms.get("term_debt_approved", 0)
                    if term_amt > 0:
                        term_rate = terms.get("term_debt_rate", 0.03)
                        structure = terms.get("facility_structure")
                        if (config and getattr(config, "debt_covenants_enabled", False)
                                and structure):
                            # Stage 3c: wrap as DebtFacility (cash + long_term_debt
                            # updated atomically inside add_facility).
                            from .types import DebtFacility, Covenant
                            from .debt_management import (
                                add_facility, VALID_FACILITY_TYPES,
                                VALID_COVENANT_TYPES,
                            )
                            ftype = structure["facility_type"]
                            if ftype not in VALID_FACILITY_TYPES:
                                ftype = "bank_term"
                            # Reject convertible unless separately enabled.
                            # If coerced to bond, STRIP conversion fields so
                            # a downstream `convert_facility` call can't be
                            # misled by stale conversion_ratio/price.
                            if (ftype == "convertible_bond"
                                    and not getattr(config, "convertible_debt_enabled", False)):
                                ftype = "bond"
                                structure = dict(structure)  # copy — don't mutate input
                                structure["conversion_ratio"] = 0.0
                                structure["conversion_price"] = 0.0
                            amort = structure["amortization_type"]
                            if amort not in ("bullet", "amortizing"):
                                amort = "bullet"
                            covs = tuple(
                                Covenant(covenant_type=c["covenant_type"],
                                         threshold=c["threshold"])
                                for c in structure["covenants"]
                                if c["covenant_type"] in VALID_COVENANT_TYPES
                            )
                            # bank_revolver needs special handling: facility
                            # must be undrawn at origination, then immediately
                            # drawn for term_amt. This keeps add_facility's
                            # invariant (revolver origination with balance>0)
                            # clean while still delivering cash.
                            if ftype == "bank_revolver":
                                fac = DebtFacility(
                                    facility_id="",
                                    firm_id=fid,
                                    facility_type=ftype,
                                    original_principal=term_amt,
                                    current_balance=0.0,  # undrawn at origination
                                    coupon_rate_quarterly=term_rate,
                                    origination_quarter=state.quarter,
                                    maturity_quarter=state.quarter + structure["maturity_quarters"],
                                    amortization_type=amort,
                                    covenants=covs,
                                    conversion_ratio=0.0,
                                    conversion_price=0.0,
                                )
                                try:
                                    new_firm = add_facility(
                                        state.firms[fid], fac,
                                        max_active=getattr(config, "max_active_facilities_per_firm", 10),
                                    )
                                    # Draw the full amount (keeps the cash/liability identity)
                                    from .debt_management import draw_revolver as _draw
                                    new_fac = new_firm.debt_facilities[-1]
                                    new_firm = _draw(new_firm, new_fac.facility_id, term_amt)
                                    state.firms[fid] = new_firm
                                    _log(state, f"  {fid}: REVOLVER {fac.facility_type} "
                                                f"${term_amt/1e6:.1f}M @ {term_rate*400:.1f}% ann "
                                                f"(drawn immediately) "
                                                f"maturity Q{state.quarter + structure['maturity_quarters']} "
                                                f"covenants={len(covs)}")
                                except ValueError as ve:
                                    _log(state, f"  {fid}: revolver creation rejected: {ve}"
                                                f"; falling back to legacy revolver bookkeeping")
                                    # Legacy fallback for a rejected revolver must hit
                                    # revolver_balance, not long_term_debt.
                                    updates["revolver_balance"] = state.firms[fid].revolver_balance + term_amt
                                    updates["revolver_commitment"] = (
                                        state.firms[fid].revolver_commitment + term_amt
                                    )
                                    updates["cash"] = state.firms[fid].cash + term_amt
                                    updates["revolver_rate"] = term_rate
                            else:
                                fac = DebtFacility(
                                    facility_id="",
                                    firm_id=fid,
                                    facility_type=ftype,
                                    original_principal=term_amt,
                                    current_balance=term_amt,
                                    coupon_rate_quarterly=term_rate,
                                    origination_quarter=state.quarter,
                                    maturity_quarter=state.quarter + structure["maturity_quarters"],
                                    amortization_type=amort,
                                    covenants=covs,
                                    conversion_ratio=structure["conversion_ratio"],
                                    conversion_price=structure["conversion_price"],
                                )
                                try:
                                    new_firm = add_facility(
                                        state.firms[fid], fac,
                                        max_active=getattr(config, "max_active_facilities_per_firm", 10),
                                    )
                                    state.firms[fid] = new_firm
                                    _log(state, f"  {fid}: FACILITY {fac.facility_type} "
                                                f"${term_amt/1e6:.1f}M @ {term_rate*400:.1f}% ann "
                                                f"maturity Q{state.quarter + structure['maturity_quarters']} "
                                                f"covenants={len(covs)} "
                                                f"| {terms.get('debt_reasoning', '')[:80]}")
                                except ValueError as ve:
                                    # If the rejection was due to max_active cap, DENY
                                    # the issuance rather than silently lump into legacy
                                    # LTD without covenants/tracking. Other ValueErrors
                                    # (bad type, etc.) also deny to avoid dropping the
                                    # covenant structure the IB proposed.
                                    _log(state, f"  {fid}: facility creation rejected: {ve}"
                                                f" — issuance DENIED (no legacy fallback)")
                        else:
                            # Legacy (toggle-off) path: lump sum, no facility tracking
                            updates["long_term_debt"] = state.firms[fid].long_term_debt + term_amt
                            updates["cash"] = state.firms[fid].cash + term_amt
                            updates["term_debt_rate"] = term_rate
                            _log(state, f"  {fid}: TERM DEBT ${term_amt/1e6:.1f}M at {term_rate*400:.0f}% ann "
                                        f"| {terms.get('debt_reasoning', '')[:100]}")
                    else:
                        debt_reason = terms.get("debt_reasoning", "")
                        if debt_reason:
                            _log(state, f"  {fid}: Debt DENIED | {debt_reason[:100]}")

                    # Equity issuance
                    eq_amt = terms.get("equity_approved", 0)
                    eq_price = terms.get("equity_price", 0)
                    if eq_amt > 0 and eq_price > 0:
                        new_shares = int(eq_amt / eq_price)
                        if new_shares > 0:
                            updates["shares_outstanding"] = state.firms[fid].shares_outstanding + new_shares
                            updates["apic"] = state.firms[fid].apic + eq_amt
                            updates["cash"] = updates.get("cash", state.firms[fid].cash) + eq_amt
                            _log(state, f"  {fid}: EQUITY ${eq_amt/1e6:.1f}M at ${eq_price:.2f}/sh "
                                        f"({new_shares:,} new shares) | {terms.get('equity_reasoning', '')[:80]}")

                    if updates:
                        state.firms[fid] = state.firms[fid].evolve(**updates)
        except Exception as e:
            _log(state, f"  Investment Bank FAILED: {e}")

    _bs_snap = _check_bs_invariants(state, "phase_7b_investment_bank", _bs_snap)

    # ── Phase 7c: Commercial Bank sets revolver terms ─────────────────────
    _log(state, "  --- Commercial Bank ---")
    if commercial_bank_fn is not None:
        try:
            bank_decisions = commercial_bank_fn(state.firms, state.macro, state.params)
            from .engine import ActionLog as _AL_cb
            if bank_decisions:
                for fid, terms in bank_decisions.items():
                    if fid in state.firms and state.firms[fid].is_active:
                        updates = {}
                        commit = terms.get("revolver_commitment", 0)
                        rate = terms.get("revolver_rate", 0.02)
                        if commit > 0:
                            updates["revolver_commitment"] = commit
                            updates["revolver_rate"] = rate
                        risk = terms.get("risk", "medium")
                        reasoning = terms.get("reasoning", "")
                        _log(state, f"  {fid}: Revolver ${commit/1e6:.0f}M at {rate*400:.0f}% ann "
                                    f"| Risk={risk} | {reasoning[:80]}")
                        if updates:
                            state.firms[fid] = state.firms[fid].evolve(**updates)
                        _AL_cb.quick_record(
                            state.action_log,
                            actor_id="commercial_bank",
                            action_type="set_revolver_terms",
                            payload={
                                "target_firm": fid,
                                "revolver_commitment": commit,
                                "revolver_rate": rate,
                                "risk": risk,
                            },
                            quarter=state.quarter,
                            justification=reasoning[:400],
                        )
        except Exception as e:
            _log(state, f"  Commercial Bank FAILED: {e}")

    # Fallback if no financial agents: simple book value pricing
    if equity_market_fn is None and investment_bank_fn is None and commercial_bank_fn is None:
        for fid, firm in state.firms.items():
            if not firm.is_active or firm.shares_outstanding <= 0:
                continue
            flows = all_flows.get(fid)
            if flows is None:
                continue
            book = max(0.01, firm.total_equity / firm.shares_outstanding)
            rev_mult = (flows.net_sales * 4 * 8) / firm.shares_outstanding if flows.net_sales > 0 else 0
            new_price = max(0.01, book * 0.4 + rev_mult * 0.6)
            state.firms[fid] = firm.evolve(equity_price=new_price)

    _bs_snap = _check_bs_invariants(state, "phase_7c_commercial_bank", _bs_snap)

    # ── Phase 7d: Provisional Compustat row (mid-quarter snapshot) ──
    # Built here so Phase 7.5 covenant testing can use it for TTM calcs.
    # Known issue: `financing_cf` below double-counts principal repayments —
    # debt_proceeds picks up the LTD reduction from Phase 6.5 amortize, AND
    # flows.cff has the principal outflow subtracted via the amortize→CFS
    # routing. The resulting row.chechq / row.fincfq are wrong until the
    # end-of-quarter refresh (_refresh_compustat_rows_for_quarter) runs at
    # the end of run_quarter. That refresh recomputes chechq from actual
    # (firm.cash - prior.cash) and derives fincfq as the residual, restoring
    # cash identity. Nothing between here and the refresh reads chechq/fincfq.

    for fid in clamped_decisions:
        firm = state.firms.get(fid)
        if firm is None or not firm.is_active:
            continue
        flows = all_flows.get(fid)
        clamped = clamped_decisions.get(fid)
        if flows and clamped:
            row = build_compustat_row(firm, flows, clamped, state.macro, state.run_id)

            # Compute financing cash flows from Phase 7b
            raw = raw_decisions.get(fid)
            prior_firm_for_fid = prior_states.get(fid)
            debt_proceeds = 0.0
            equity_proceeds = 0.0

            if prior_firm_for_fid:
                # Debt change = new LTD - old LTD (positive = borrowed)
                debt_proceeds = firm.long_term_debt - prior_firm_for_fid.long_term_debt
                # Equity proceeds from APIC change (positive = issued)
                equity_proceeds = max(0, firm.apic - prior_firm_for_fid.apic)

            financing_cf = debt_proceeds + equity_proceeds + flows.cff  # cff from clamping (revolver draws, dividends)

            # Update all balance sheet fields to post-financing state
            row.cheq = firm.cash
            row.dlcq = firm.revolver_balance
            row.dlttq = firm.long_term_debt
            row.atq = firm.total_assets
            row.ltq = firm.total_liabilities
            row.lctq = firm.total_current_liabilities
            row.ceqq = firm.total_equity
            row.apicq = firm.apic
            row.cshoq = firm.shares_outstanding / 1_000_000
            row.mkvaltq = firm.market_cap / 1_000_000  # WRDS $ millions
            row.xintq = flows.interest_expense

            # Update cash flow statement to include financing
            row.fincfq = financing_cf
            row.sstkq = equity_proceeds
            row.chechq = flows.cfo + flows.cfi + financing_cf  # full reconciliation
            state.compustat_rows.append(row)

            # Wave λ Fix 3: track funding ask vs received for next-Q
            # capital-constraint prompt block.
            ask = float(getattr(raw, "equity_issuance_request", 0) or 0)
            received = float(equity_proceeds + debt_proceeds)
            state.firms[fid] = state.firms[fid].evolve(
                last_funding_ask=ask,
                last_funding_received=received,
            )

    # ── Phase 7.5: Covenant testing (if debt_covenants_enabled) ──
    # Tests each active facility's covenants against current BS + TTM income.
    # Violations are logged and appended to state.pending_covenant_violations
    # for Stage 3c's LLM-driven resolution phase to handle. No-op until
    # facilities exist.
    if config and getattr(config, "debt_covenants_enabled", False):
        from .debt_management import test_covenants
        for fid, firm in state.firms.items():
            if not firm.is_active or not firm.debt_facilities:
                continue
            # TTM EBITDA + interest from last 4 compustat rows for this firm
            firm_rows = [r for r in state.compustat_rows
                         if r.firm_id == fid][-4:]
            ttm_ebitda = sum((r.niq or 0) + (r.xintq or 0) + (r.dpq or 0)
                             for r in firm_rows)
            ttm_interest = sum((r.xintq or 0) for r in firm_rows)
            violations = test_covenants(firm, ttm_ebitda, ttm_interest)
            for v in violations:
                v["firm_id"] = fid
                v["quarter"] = state.quarter
                state.pending_covenant_violations.append(v)
                _log(state, f"  {fid}: COVENANT VIOLATION "
                            f"{v['facility_id']} {v['covenant_type']} "
                            f"measured={v['measured_ratio']:.2f} "
                            f"threshold={v['threshold']:.2f}")

    # ── Phase 7.6: Debt consistency check (if debt_covenants_enabled) ──
    # Invariants: facility balances sum to aggregate, no negatives,
    # no balance > original principal, status within valid set.
    # Logs warnings but does not fail. No-op when no facilities exist.
    if config and getattr(config, "debt_covenants_enabled", False):
        from .debt_management import consistency_check
        for fid, firm in state.firms.items():
            if not firm.is_active:
                continue
            issues = consistency_check(firm)
            for issue in issues:
                _log(state, f"  {fid}: DEBT CONSISTENCY WARNING {issue}")

    # ── Phase 7.7: Covenant violation resolution (if debt_covenants_enabled) ──
    # Runs LLM resolver on state.pending_covenant_violations, then applies
    # waive/amend/accelerate via debt_management.apply_*.
    # H1 FIX: unresolved violations (resolver returned fewer resolutions than
    # pending, or returned errors) are NOT silently dropped — they survive into
    # `quarters_in_violation` counter and re-queue for next quarter's resolver.
    if (config and getattr(config, "debt_covenants_enabled", False)
            and violation_resolver_fn is not None
            and state.pending_covenant_violations):
        pending = list(state.pending_covenant_violations)
        resolved_keys: set[tuple[str, str, str]] = set()

        # Wave gamma: wrap each resolution as a Negotiation record so the
        # borrower-lender bargaining history is persistently logged. The
        # current LLM resolver is single-shot (lender dictates terms), so
        # each negotiation has exactly one completed round for now. A
        # future multi-round resolver can append additional rounds without
        # changing the log schema.
        from .negotiation import Negotiation, Offer, OutsideOption

        try:
            resolutions = violation_resolver_fn(
                pending, state.firms, state.macro,
            )
            from .debt_management import (
                apply_waiver, apply_amendment, apply_acceleration,
            )
            for res in resolutions:
                if "error" in res:
                    _log(state, f"  VIOLATION RESOLVER: {res['error']}")
                    continue
                fid = res.get("firm_id", "")
                fac_id = res.get("facility_id", "")
                cov_type = res.get("covenant_type", "")
                action = res.get("action", "")
                if fid not in state.firms or not state.firms[fid].is_active:
                    continue
                firm_now = state.firms[fid]
                if action == "waive":
                    new_firm, event = apply_waiver(
                        firm_now, fac_id, cov_type,
                        res.get("waiver_fee", 0.0), state.quarter,
                    )
                    state.firms[fid] = new_firm
                    _log(state, f"  {fid}: WAIVED {fac_id} {cov_type} "
                                f"fee=${res.get('waiver_fee', 0)/1e6:.2f}M "
                                f"| {res.get('reasoning','')[:80]}")
                elif action == "amend":
                    new_rate = res.get("new_rate_quarterly", 0.0) or None
                    new_firm, event = apply_amendment(
                        firm_now, fac_id, cov_type,
                        res.get("new_threshold", 0.0), new_rate, state.quarter,
                    )
                    state.firms[fid] = new_firm
                    _log(state, f"  {fid}: AMENDED {fac_id} {cov_type} "
                                f"new_threshold={res.get('new_threshold',0):.2f} "
                                f"| {res.get('reasoning','')[:80]}")
                elif action == "accelerate":
                    new_firm, event = apply_acceleration(
                        firm_now, fac_id, cov_type, state.quarter,
                    )
                    state.firms[fid] = new_firm
                    _log(state, f"  {fid}: ACCELERATED {fac_id} {cov_type} "
                                f"| {res.get('reasoning','')[:80]}")
                else:
                    continue  # unknown action — treat as unresolved
                resolved_keys.add((fid, fac_id, cov_type))
                # Wave gamma: record as a 1-round covenant_waiver Negotiation.
                # The borrower's "initial offer" is the implicit request for
                # continued lender forbearance; the lender's response is the
                # action taken (waive / amend / accelerate).
                cov_neg = Negotiation.new(
                    topic="covenant_waiver",
                    party_a=fid,                     # borrower
                    party_b="commercial_bank",       # lender
                    quarter=state.quarter,
                    max_rounds=3,
                    outside_option=OutsideOption(
                        party_utilities={
                            fid: -1.0,                 # acceleration is bad for borrower
                            "commercial_bank": -0.3,   # recovery at liquidation is bad for lender too
                        },
                        descriptor=(
                            "borrower_outside=acceleration_and_default; "
                            "lender_outside=recovery_at_liquidation"
                        ),
                    ),
                )
                borrower_offer = Offer(
                    party=fid, round_index=0,
                    payload={
                        "facility_id": fac_id,
                        "covenant_type": cov_type,
                        "request": "continued_forbearance",
                        "measured_ratio": res.get("measured_ratio", 0.0),
                        "threshold": res.get("threshold", 0.0),
                    },
                    rationale=(
                        f"Firm {fid} in breach of {cov_type} on {fac_id}; "
                        f"seeking resolution"
                    ),
                )
                # Lender's response: counter with the action they chose.
                lender_counter_payload = {
                    "action": action,
                    "waiver_fee": res.get("waiver_fee", 0.0),
                    "new_threshold": res.get("new_threshold", 0.0),
                    "new_rate_quarterly": res.get("new_rate_quarterly", 0.0),
                }
                lender_counter = Offer(
                    party="commercial_bank", round_index=0,
                    payload=lender_counter_payload,
                    rationale=res.get("reasoning", "")[:400],
                )
                # One round: lender accepted continued relationship with
                # modifications. Count as "accept" for the relationship to
                # persist (unless acceleration, which is "walk").
                response = "walk" if action == "accelerate" else "accept"
                cov_neg.submit_round(
                    proposer_offer=borrower_offer,
                    counterparty_response=response,
                    counterparty_counter=lender_counter,
                    counterparty_rationale=res.get("reasoning", "")[:400],
                )
                state.negotiations_log.append(cov_neg.to_record())
                # Record event in violation history
                new_hist = state.firms[fid].covenant_violation_history + (event,)
                state.firms[fid] = state.firms[fid].evolve(
                    covenant_violation_history=new_hist,
                )
        except Exception as e:
            _log(state, f"  Violation resolver FAILED: {e}")
        # H1: re-queue ALL unresolved violations rather than silently dropping.
        # They'll re-surface next quarter when covenant testing runs again, OR
        # the resolver gets another chance.
        unresolved = [
            v for v in pending
            if (v.get("firm_id", ""), v.get("facility_id", ""),
                v.get("covenant_type", "")) not in resolved_keys
        ]
        if unresolved:
            _log(state, f"  {len(unresolved)} covenant violation(s) unresolved "
                        f"this quarter — re-queueing for next quarter")
            state.pending_covenant_violations = unresolved
        else:
            state.pending_covenant_violations = []

    _bs_snap = _check_bs_invariants(state, "phase_7_7_covenant_resolution", _bs_snap)

    # ── Phase 14: SEC enforcement actions (if sec_enabled) ─────────────────
    if sec_fn is not None:
        from .types import SECInvestigationState
        for fid, inv in list(state.sec_investigations.items()):
            if inv.status == "aaer_pending":
                _log(state, f"  SEC AAER: {fid} — public enforcement action")
                state.sec_enforcement_log.append({
                    "firm_id": fid, "quarter": state.quarter,
                    "type": "aaer", "status": inv.status,
                })
                # Force restatement if restatements_enabled
                if config and config.restatements_enabled and fid in state.firms:
                    from .restatement import process_restatement
                    firm = state.firms[fid]
                    if abs(firm.cumulative_manipulation) > 1.0:
                        new_firm, updated_rows, event = process_restatement(
                            firm, state.compustat_rows, "sec_forced", state.quarter,
                        )
                        state.firms[fid] = new_firm
                        state.compustat_rows = updated_rows
                        if event:
                            state.restatement_events.append(event)
                        _log(state, f"  RESTATEMENT (SEC-forced): {fid} "
                                    f"cumulative manipulation reversed")
                # Resolve investigation
                state.sec_investigations[fid] = SECInvestigationState(
                    firm_id=fid, status="resolved",
                    started_quarter=inv.started_quarter,
                )

    _bs_snap = _check_bs_invariants(state, "phase_14_sec_enforcement", _bs_snap)

    # ── Phase 14b: Delisting default (price collapse) ─────────────────────
    # Firms below the delisting threshold for N consecutive quarters default,
    # even if they are still technically solvent on cash. Matches real-world
    # exchange delisting rules (NYSE: price < $1 for 30 consecutive days).
    q_threshold = config.delisting_quarters_threshold if config else 2
    for fid, firm in list(state.firms.items()):
        if not firm.is_active:
            continue
        if firm.quarters_below_delisting_threshold >= q_threshold:
            _log(state, f"  {fid}: *** DELISTING DEFAULT *** "
                        f"(price ${firm.equity_price:.2f} below "
                        f"${config.delisting_price_threshold if config else 1.00:.2f} "
                        f"for {firm.quarters_below_delisting_threshold}Q)")
            # Floor cash at 0 just like the bridge-fail default path so the
            # row doesn't carry negative cash. Deficit becomes LTD (firm
            # owed cash it couldn't pay → debt outstanding).
            neg_cash = max(0.0, -firm.cash)
            state.firms[fid] = firm.evolve(
                is_active=False,
                cash=max(0.0, firm.cash),
                long_term_debt=firm.long_term_debt + neg_cash,
            )
            for slot in state.slots.values():
                if slot.current_firm_id == fid:
                    slot.total_defaults += 1
                    slot.default_history.append({
                        "incarnation": firm.incarnation,
                        "quarter": state.quarter,
                        "cause": "delisting",
                    })

    _bs_snap = _check_bs_invariants(state, "phase_14b_delisting_default", _bs_snap)

    # ── Phase 15: Settlement and solvency check ──────────────────────────
    # If cash is negative, the firm needs emergency financing.
    # 1. Try existing revolver (cheapest)
    # 2. If insufficient, arrange emergency short-term debt at penalty rate
    #    (like a distressed bridge loan — expensive but keeps the firm alive)
    # 3. Only DEFAULT if the firm is so deep in debt that no lender would touch it
    #    (total debt > 2x total assets = truly insolvent, not just illiquid)

    for fid, firm in list(state.firms.items()):
        if not firm.is_active:
            continue

        if firm.cash < 0:
            shortfall = -firm.cash

            # Step 1: Draw from existing revolver
            available_credit = firm.available_credit
            if shortfall <= available_credit:
                state.firms[fid] = firm.evolve(
                    cash=0,
                    revolver_balance=firm.revolver_balance + shortfall,
                )
                _log(state, f"  {fid}: Revolver draw ${shortfall/1e6:.1f}M")
                continue

            # Step 2: Emergency bridge — distressed lender (LLM) decides amount and rate.
            # When no bridge agent is wired (e.g. mock mode), fall back to a deterministic
            # rule (debt service possible if total leverage stays reasonable).
            remaining_shortfall = shortfall - available_credit
            new_revolver = firm.revolver_balance + available_credit  # max out revolver first

            if emergency_bridge_fn is not None:
                try:
                    bridge_decision = emergency_bridge_fn(
                        firm.evolve(revolver_balance=new_revolver),
                        remaining_shortfall, state.macro, state.params,
                    )
                except Exception as e:
                    _log(state, f"  {fid}: bridge agent failed ({e}); will default")
                    bridge_decision = None
                approved = (bridge_decision or {}).get("approved_amount", 0.0)
                bridge_rate = (bridge_decision or {}).get("rate", 0.0)
                bridge_reason = (bridge_decision or {}).get("reasoning", "")
            else:
                # Deterministic fallback: bridge available if leverage stays reasonable.
                # No hardcoded "penalty rate" — uses firm's existing term_debt_rate.
                current_total_debt = firm.revolver_balance + firm.long_term_debt + available_credit
                if (remaining_shortfall <= firm.total_assets * 0.30
                        and current_total_debt < firm.total_assets * 1.5):
                    approved = remaining_shortfall
                    bridge_rate = firm.term_debt_rate  # use existing rate, no markup
                    bridge_reason = "deterministic fallback (no LLM bridge wired)"
                else:
                    approved = 0.0
                    bridge_rate = 0.0
                    bridge_reason = "fallback declined: leverage too high"

            if approved >= remaining_shortfall:
                emergency_debt = remaining_shortfall
                new_ltd = firm.long_term_debt + emergency_debt
                state.firms[fid] = firm.evolve(
                    cash=0,
                    revolver_balance=new_revolver,
                    long_term_debt=new_ltd,
                    term_debt_rate=bridge_rate if bridge_rate > 0 else firm.term_debt_rate,
                )
                _log(state, f"  {fid}: EMERGENCY BRIDGE ${emergency_debt/1e6:.1f}M "
                            f"at {bridge_rate*400:.0f}% annual. {bridge_reason[:120]}")
            else:
                _log(state, f"  {fid}: *** DEFAULT *** (cash=${firm.cash/1e6:.1f}M, "
                            f"shortfall=${remaining_shortfall/1e6:.1f}M, "
                            f"bridge offered ${approved/1e6:.1f}M). {bridge_reason[:120]}")
                # Wave ν+10 item 3: classify Ch11 vs Ch7 based on TTM
                # operating-income and cash-flow-from-operations trends.
                # Ch11 firms keep operating with restructured capital;
                # Ch7 firms enter the existing liquidation+auction path.
                from .bankruptcy import (
                    classify_default, enter_chapter_11, enter_chapter_7,
                )
                # Compute TTM operating income and CFO from the firm's
                # last four compustat rows.
                firm_rows = [r for r in state.compustat_rows
                             if r.firm_id == fid][-4:]
                ttm_oi = sum(getattr(r, "oiadpq", 0) or 0 for r in firm_rows)
                ttm_cfo = sum(getattr(r, "oancfq", 0) or 0 for r in firm_rows)
                ch_type = classify_default(firm, ttm_oi, ttm_cfo)
                if ch_type == "chapter_11":
                    state.firms[fid] = enter_chapter_11(firm)
                    _log(state, f"  {fid}: → CHAPTER 11 (TTM OI ${ttm_oi/1e6:.1f}M, "
                                f"CFO ${ttm_cfo/1e6:.1f}M; LTD haircut 50%, "
                                f"equity wiped, continues operating)")
                else:
                    state.firms[fid] = enter_chapter_7(firm)
                    _log(state, f"  {fid}: → CHAPTER 7 (TTM OI ${ttm_oi/1e6:.1f}M, "
                                f"CFO ${ttm_cfo/1e6:.1f}M; liquidation auction follows)")

                for slot in state.slots.values():
                    if slot.current_firm_id == fid:
                        slot.total_defaults += 1
                        slot.default_history.append({
                            "incarnation": firm.incarnation,
                            "quarter": state.quarter,
                        })

    # Final end-of-quarter check (after Phase 15 + terminal-state transition).
    _bs_snap = _check_bs_invariants(state, "phase_15_settlement", _bs_snap)

    # ── Compustat row refresh (end-of-quarter snapshot) ────────────────────
    # The row was initially built in Phase 7d (post-financing). Phases 7.5/7.6/7.7
    # (covenant resolution), 14 (SEC), 14b (delisting), 15 (settlement/bridge)
    # may have mutated cash, long_term_debt, revolver_balance, or is_active
    # further. Refresh the most-recent row for each firm so it reflects true
    # end-of-Q state. (SEC restatement Phase 14 rewrites its own rows already.)
    _refresh_compustat_rows_for_quarter(state, prior_states)

    # ── Terminal-state transition: accelerated → defaulted ──
    # An accelerated facility with residual balance means the bank called
    # the loan AND `apply_acceleration` couldn't fully pay off from cash
    # (cash was exhausted). By end-of-quarter, if the residual still isn't
    # zero, the facility defaults. The liability stays on BS as defaulted
    # debt (researchers can see it via `status="defaulted"`) but no longer
    # amortizes or triggers covenant tests.
    # Only fires when debt_covenants are on.
    if config and getattr(config, "debt_covenants_enabled", False):
        from dataclasses import replace as _dc_replace
        for fid, firm in list(state.firms.items()):
            if not firm.debt_facilities:
                continue
            changed = False
            new_facs = []
            for fac in firm.debt_facilities:
                if fac.status == "accelerated" and fac.current_balance > 1.0:
                    new_facs.append(_dc_replace(fac, status="defaulted"))
                    changed = True
                    _log(state, f"  {fid}: FACILITY {fac.facility_id} "
                                f"accelerated residual ${fac.current_balance/1e6:.1f}M "
                                f"unpaid → DEFAULTED")
                else:
                    new_facs.append(fac)
            if changed:
                state.firms[fid] = firm.evolve(debt_facilities=tuple(new_facs))

    # ── Wave ν+2 Phase 15b: distressed-firm asset auction (env-judged) ──
    # Single env-LLM call allocates all lots simultaneously (O(1)),
    # replacing the per-survivor bidder model from Wave ν (which was
    # already O(N) but expensive — 20 calls per quarter at scale).
    # See distressed_auction.run_quarterly_auctions_via_judge.
    if auction_bidder_fns:
        # Wave ν+10 item 3: only Chapter-7 defaults route to auction.
        # Chapter-11 defaults stay is_active=True (operating under
        # court protection) and are excluded from the auction phase.
        # The default_type field carries the classification; firms
        # without that field set fall back to legacy is_active check.
        newly_defaulted_ids = [
            fid for fid in _active_at_start
            if fid in state.firms and not state.firms[fid].is_active
            and getattr(state.firms[fid], "default_type", "") != "chapter_11"
        ]
        # Wave ν+4 diagnostic: log auction-phase entry every quarter so
        # we can audit whether the phase is even being reached (the v3
        # 20Y run had 20 defaults but 0 auction events — silently broken).
        # ASCII-only to avoid cp1252 encoding errors on Windows console.
        if newly_defaulted_ids:
            msg = f"  AUCTION_PHASE Q{state.quarter}: {len(newly_defaulted_ids)} newly-defaulted firms -> triggering auction"
            _log(state, msg)
            print(msg, flush=True)
        if newly_defaulted_ids:
            from .distressed_auction import (
                run_quarterly_auctions_via_judge, apply_auction_result,
            )
            industry_character = _build_industry_character_dict(state)
            defaulted_firms_list = [
                state.firms[dfid] for dfid in newly_defaulted_ids
            ]
            survivors = [
                f for fid_s, f in state.firms.items() if f.is_active
            ]
            # auction_bidder_fns now carries the SINGLE judge under a
            # special key __judge__ wired in cli.py. Backward-compat:
            # if no judge present, fall back to the legacy per-survivor
            # bidder model (used by older configs / mocks).
            judge_fn = auction_bidder_fns.get("__judge__")
            if judge_fn is not None and survivors:
                try:
                    events = run_quarterly_auctions_via_judge(
                        defaulted_list=defaulted_firms_list,
                        survivors=survivors,
                        judge_fn=judge_fn,
                        industry_context=industry_character,
                        rng=state.rng,
                    )
                except Exception as e:
                    _log(state, f"  AUCTION (judge): raised {e}")
                    events = []
            else:
                # Legacy per-survivor-bidder fallback
                from .distressed_auction import run_quarterly_auctions
                bidder_fns_for_survivors = {
                    s.firm_id: auction_bidder_fns[s.firm_id]
                    for s in survivors if s.firm_id in auction_bidder_fns
                }
                if not survivors or not bidder_fns_for_survivors:
                    events = []
                else:
                    try:
                        events = run_quarterly_auctions(
                            defaulted_list=defaulted_firms_list,
                            survivors=survivors,
                            bidder_fns=bidder_fns_for_survivors,
                            industry_context=industry_character,
                            rng=state.rng,
                        )
                    except Exception as e:
                        _log(state, f"  AUCTION: run_quarterly_auctions raised {e}")
                        events = []

            # Wave ν+7 fix: apply auction events to firm state OUTSIDE the
            # if/else above. Previously this loop was indented inside the
            # `else:` (legacy) branch, which meant the modern judge-path
            # events were computed but never applied — defaulted firms
            # stayed in their pre-auction state and winners never received
            # the assets they "won." Pull the loop out one level so it
            # runs for either branch.
            for event in events:
                target_id = event.get("target_firm_id", "")
                if not target_id or target_id not in state.firms:
                    state.distressed_auctions.append(event)
                    continue
                defaulted = state.firms[target_id]
                if event.get("outcome") == "sold":
                    try:
                        updated_winner, updated_defaulted = apply_auction_result(
                            state, defaulted, event,
                        )
                    except Exception as e:
                        _log(state, f"  AUCTION: {target_id} apply_auction_result raised {e}")
                        updated_winner = None
                    if updated_winner is not None:
                        state.firms[event["winner_id"]] = updated_winner
                        state.firms[target_id] = updated_defaulted
                        msg = (f"  AUCTION Q{state.quarter}: {target_id} "
                               f"assets sold to {event['winner_id']} for "
                               f"${event['winning_amount']/1e6:.1f}M")
                        _log(state, msg)
                        print(msg, flush=True)
                else:
                    # Wave ν+11: when no buyer materializes (no_solvent_bidder
                    # / no_bids / no_sale / judge_failed), the defaulted firm
                    # still must have its PPE, inventory, and operational
                    # stocks zeroed — otherwise the BS check sees phantom
                    # assets every subsequent quarter (one of the patterns
                    # behind the 370 phase_2_ipo violations in run-2). The
                    # asset writedown hits retained earnings (impairment).
                    impaired_value = (
                        max(0.0, defaulted.ppe_gross - defaulted.accum_depreciation)
                        + defaulted.inventory_value
                    )
                    state.firms[target_id] = defaulted.evolve(
                        ppe_gross=0.0,
                        accum_depreciation=0.0,
                        inventory_value=0.0,
                        capability_stock=0.0,
                        brand_stock=0.0,
                        capacity_units=0,
                        retained_earnings=defaulted.retained_earnings - impaired_value,
                    )
                    msg = (f"  AUCTION Q{state.quarter}: {target_id} "
                           f"{event.get('outcome', 'no_sale')} — assets "
                           f"impaired ${impaired_value/1e6:.1f}M to RE")
                    _log(state, msg)
                    print(msg, flush=True)
                state.distressed_auctions.append(event)

    # ── ANNUAL PHASES (Q4 only) ────────────────────────────────────────────
    is_annual = state.macro.fqtr == 4

    # ── Phase A1: Auditor annual audit (if auditor_enabled) ──────────────
    # Each firm's audit is independent → parallelize across firms. Only the
    # post-call mutations (state.firms, restatements) run serially.
    if is_annual and auditor_fn is not None:
        _log(state, "  --- Annual Audit ---")
        active_audit_firms = [
            (fid, firm) for fid, firm in state.firms.items()
            if firm.is_active and firm.auditor_id
        ]
        def _run_audit(fid_firm):
            _fid, _firm = fid_firm
            _rows = [r.as_dict() for r in state.compustat_rows
                     if r.firm_id == _fid][-4:]
            _priors = [r for r in state.audit_results if r.firm_id == _fid]
            _hints = []
            if abs(_firm.cumulative_manipulation) > 20_000_000:
                _hints.append("Accrual quality metrics show unusual patterns")
            if _firm.under_sec_investigation:
                _hints.append("Firm is known to be under regulatory scrutiny")
            try:
                return (_fid, auditor_fn(_firm, _rows, _priors, _hints))
            except Exception as e:
                return (_fid, e)

        parallel_audit = (config is None
                          or getattr(config, "parallel_firm_decisions", True))
        if parallel_audit and len(active_audit_firms) > 1:
            import concurrent.futures as _cf
            with _cf.ThreadPoolExecutor(
                    max_workers=_max_workers(config, len(active_audit_firms))) as pool:
                audit_results = list(pool.map(_run_audit, active_audit_firms))
        else:
            audit_results = [_run_audit(p) for p in active_audit_firms]

        # Apply results serially (state mutations + restatement dependencies).
        from .engine import ActionLog as _AL_aud
        for fid, result in audit_results:
            if isinstance(result, Exception):
                _log(state, f"  Audit {fid} FAILED: {result}")
                continue
            firm = state.firms[fid]
            state.audit_results.append(result)
            state.firms[fid] = firm.evolve(
                last_audit_opinion=result.opinion,
                auditor_tenure_years=firm.auditor_tenure_years + 1,
                audit_fee=result.fee,
            )
            # Patch the Q4 compustat row with audit_opinion + auditor_id so
            # compustat_q.csv carries the annual opinion on the Q4 row
            # (previously NaN — refresh ran before audits). Walk back to find
            # this firm's Q4 row in the current fyear.
            for _row in reversed(state.compustat_rows):
                if (_row.firm_id == fid and _row.fyearq == state.macro.fyear
                        and _row.fqtr == 4):
                    _row.audit_opinion = result.opinion
                    _row.auditor_id = result.auditor_id or ""
                    break
            _log(state, f"  Audit {fid}: {result.opinion} by {result.auditor_id} "
                        f"(fee=${result.fee:,.0f})")
            _AL_aud.quick_record(
                state.action_log,
                actor_id=result.auditor_id or "unknown_auditor",
                action_type="issue_audit_opinion",
                payload={
                    "target_firm": fid,
                    "fyear": state.macro.fyear,
                    "opinion": result.opinion,
                    "fee": result.fee,
                    "going_concern": result.going_concern,
                    "recommended_restatement": result.recommended_restatement,
                },
                quarter=state.quarter,
                justification=(result.findings or "")[:400],
            )
            # Wave epsilon: update auditor typed memory (client history)
            from .beliefs import AuditorMemory as _AMA
            aid = result.auditor_id or "unknown_auditor"
            aud_mem = state.auditor_memory.setdefault(aid, _AMA(auditor_id=aid))
            aud_mem.client_history.setdefault(fid, []).append({
                "fyear": state.macro.fyear,
                "opinion": result.opinion,
                "going_concern": bool(result.going_concern),
                "findings_summary": (result.findings or "")[:200],
                "fee": result.fee,
            })
            # Wave gamma: audit fee haggle. LLM-driven when both firm and
            # auditor have backends; deterministic fallback otherwise
            # (10% discount when going_concern=True; else hold).
            from .negotiation import Negotiation as _Neg, Offer as _Off, OutsideOption as _OO
            haggle_fn = getattr(auditor_fn, "haggle_fee", None)
            prior_fees = [op.fee for op in state.audit_results
                           if op.firm_id == fid and op.fee > 0]
            if haggle_fn is not None:
                try:
                    haggle_result = haggle_fn(
                        firm, result.fee, prior_fees[-3:], result.going_concern,
                    )
                    final_fee = haggle_result["final_fee"]
                    haggle_rounds = haggle_result["haggle_rounds"]
                    outcome = haggle_result["outcome"]
                except Exception as e:
                    _log(state, f"  Fee haggle {fid} FAILED: {e}")
                    # Fall back to deterministic
                    final_fee = result.fee * (0.90 if result.going_concern else 1.0)
                    haggle_rounds = []
                    outcome = "fallback_deterministic"
            else:
                final_fee = result.fee * (0.90 if result.going_concern else 1.0)
                haggle_rounds = []
                outcome = "deterministic_no_llm"

            haggle = _Neg.new(
                topic="audit_fee",
                party_a=fid, party_b=aid,
                quarter=state.quarter, max_rounds=2,
                outside_option=_OO(
                    party_utilities={
                        fid: -0.3, aid: 0.0,
                    },
                    descriptor="firm_outside=no_audit_risk_delisting; auditor_outside=lose_client",
                ),
            )
            # Build round history from haggle_rounds (LLM-driven) or one
            # synthetic round (deterministic fallback).
            if haggle_rounds:
                firm_r0 = next((r for r in haggle_rounds
                                 if r["party"] == fid), None)
                auditor_r1 = next((r for r in haggle_rounds
                                    if r["party"] == aid), None)
                if firm_r0:
                    firm_offer = _Off(
                        party=fid, round_index=0,
                        payload={"action": firm_r0["action"],
                                 "requested_fee": firm_r0.get("requested_fee")},
                        rationale=firm_r0.get("reasoning", ""),
                    )
                    if auditor_r1:
                        haggle.submit_round(
                            proposer_offer=firm_offer,
                            counterparty_response=(
                                "accept" if auditor_r1["action"] == "accept"
                                else "walk" if auditor_r1["action"] == "walk"
                                else "counter"),
                            counterparty_counter=_Off(
                                party=aid, round_index=0,
                                payload={"action": auditor_r1["action"],
                                         "final_fee": auditor_r1.get("final_fee")},
                                rationale=auditor_r1.get("reasoning", ""),
                            ),
                            counterparty_rationale=auditor_r1.get("reasoning", ""),
                        )
                    else:
                        # Firm accepted or rejected; no auditor round
                        resp = ("accept" if firm_r0["action"] == "accept"
                                 else "walk")
                        haggle.submit_round(
                            proposer_offer=firm_offer,
                            counterparty_response=resp,
                            counterparty_rationale="",
                        )
            else:
                # Deterministic fallback — single synthetic round
                haggle.submit_round(
                    proposer_offer=_Off(
                        party=fid, round_index=0,
                        payload={"requested_discount_pct":
                                 15 if result.going_concern else 0},
                        rationale=("going concern pressure; request discount"
                                    if result.going_concern
                                    else "no counter — firm accepts posted fee"),
                    ),
                    counterparty_response=(
                        "counter" if result.going_concern else "accept"),
                    counterparty_counter=_Off(
                        party=aid, round_index=0,
                        payload={"final_fee": final_fee,
                                 "discount_granted": result.going_concern},
                        rationale=(
                            "10% distressed-client discount to retain engagement"
                            if result.going_concern
                            else "posted fee reflects risk; hold"),
                    ),
                    counterparty_rationale="deterministic fallback",
                )
            # Apply final fee
            if final_fee != result.fee:
                state.firms[fid] = state.firms[fid].evolve(audit_fee=final_fee)
            state.negotiations_log.append(haggle.to_record())
            # If adverse + restatements enabled, force restatement
            if result.recommended_restatement and config and config.restatements_enabled:
                if abs(firm.cumulative_manipulation) > 1.0:
                    from .restatement import process_restatement
                    new_firm, updated_rows, event = process_restatement(
                        state.firms[fid], state.compustat_rows,
                        "auditor_forced", state.quarter,
                    )
                    state.firms[fid] = new_firm
                    state.compustat_rows = updated_rows
                    if event:
                        state.restatement_events.append(event)
                    _log(state, f"  RESTATEMENT (auditor-forced): {fid}")

    _bs_snap = _check_bs_invariants(state, "phase_A1_audit", _bs_snap)

    # ── Phase A1.5: Annual report generation (if annual_reports_enabled) ──
    # Runs after auditor (so audit opinion is available) and before governance.
    # For each active firm, aggregates the 4 quarters of compustat into a 10-K-
    # style report combining deterministic financials with LLM-authored MD&A.
    if (is_annual and annual_report_fn is not None
            and config and getattr(config, "annual_reports_enabled", False)):
        _log(state, "  --- Annual Reports ---")
        # Gather independent (firm, year_rows, prior_year_rows, audit, cov_violations) tuples
        ar_candidates = []
        for fid, firm in state.firms.items():
            if not firm.is_active:
                continue
            year_rows = [r for r in state.compustat_rows
                         if r.firm_id == fid and r.fyearq == state.macro.fyear]
            if not year_rows:
                continue
            prior_year_rows = [r for r in state.compustat_rows
                               if r.firm_id == fid and r.fyearq == state.macro.fyear - 1]
            audit = next((a for a in reversed(state.audit_results)
                          if a.firm_id == fid), None)
            cov_violations = sum(
                1 for ev in firm.covenant_violation_history
                if (ev.violation_quarter - 1) // 4 + 2031 == state.macro.fyear
            )
            ar_candidates.append((fid, firm, year_rows, prior_year_rows, audit, cov_violations))

        def _run_ar(args):
            _fid, _firm, _yr, _pyr, _audit, _cv = args
            try:
                return (_fid, annual_report_fn(_firm, _yr, _pyr, state.macro,
                                                 _audit, _cv))
            except Exception as e:
                return (_fid, e)

        parallel_ar = (config is None
                       or getattr(config, "parallel_firm_decisions", True))
        if parallel_ar and len(ar_candidates) > 1:
            import concurrent.futures as _cf
            with _cf.ThreadPoolExecutor(
                    max_workers=_max_workers(config, len(ar_candidates))) as pool:
                results = list(pool.map(_run_ar, ar_candidates))
        else:
            results = [_run_ar(a) for a in ar_candidates]

        for fid, report in results:
            if isinstance(report, Exception):
                _log(state, f"  Annual report {fid} FAILED: {report}")
                continue
            state.annual_reports.append(report)
            _log(state, f"  Annual {fid}: rev=${report.annual_revenue/1e6:.1f}M "
                        f"NI=${report.annual_net_income/1e6:.1f}M "
                        f"YoY={report.yoy_revenue_growth*100:+.0f}% "
                        f"opinion={report.audit_opinion or 'n/a'}")

    # ── Phase A1.7: Annual ExecuComp outstanding-equity snapshot ──
    # Capture for ALL firms (active + just-defaulted) so the
    # `execucomp_outstanding.csv` panel covers every firm × fyear that
    # was active at any point during the year. Without this, firms that
    # defaulted before Q4 governance (or had insufficient tenure for
    # LLM review) get dropped from the dataset entirely. Governance
    # below may overwrite this snapshot with post-decision values for
    # firms that go through the LLM path. Only fires when stock_comp
    # toggle is on so we have grants to track.
    if (is_annual and config
            and getattr(config, "stock_comp_enabled", False)):
        from .ceo_comp import outstanding_snapshot as _snap_pre
        existing_keys = {(s["firm_id"], s["fyear"])
                          for s in state.execucomp_annual_snapshots}
        # Identify firms that had ANY compustat activity in the current
        # fyear. Firms that defaulted in a PRIOR fyear are no longer
        # operating; emitting a post-default snapshot produces stale rows
        # (audit flagged firm_0 FY2032 after Q3 2031 default). Skip them.
        active_this_fyear = {
            r.firm_id for r in state.compustat_rows
            if r.fyearq == state.macro.fyear
        }
        for fid_pre, firm_pre in state.firms.items():
            # Capture if firm has any grants ever (active or recently defaulted)
            if not firm_pre.ceo_stock_grants:
                continue
            # Only capture if firm was active during this fyear (avoids
            # stale post-default snapshots in later years).
            if fid_pre not in active_this_fyear:
                continue
            key = (fid_pre, state.macro.fyear)
            if key in existing_keys:
                continue
            try:
                snap_pre = _snap_pre(firm_pre, firm_pre.equity_price or 0.01)
                # Compute shares_sold THIS fyear from cumulative deltas
                prior_snaps = [s for s in state.execucomp_annual_snapshots
                                if s["firm_id"] == fid_pre]
                prior_cum = (max(s["shares_sold_cumulative"] for s in prior_snaps)
                              if prior_snaps else 0)
                shares_sold_this_year = max(
                    0, firm_pre.ceo_shares_sold_cumulative - prior_cum
                )
                # Schema must match the post-gov snapshot — see governance
                # block below — so build_execucomp() / build_execucomp_outstanding()
                # can read either kind without branching.
                state.execucomp_annual_snapshots.append({
                    "firm_id": fid_pre,
                    "fyear": state.macro.fyear,
                    "ceo_id": firm_pre.ceo_type,
                    "age": firm_pre.ceo_age,
                    "tenure_years": firm_pre.ceo_tenure_quarters / 4.0,
                    "base_salary": firm_pre.ceo_base_salary,
                    "cash_bonus_this_year": 0.0,
                    "stock_awards_value": 0.0,
                    "option_awards_value": 0.0,
                    "shares_owned_eoy": snap_pre["vested_rsu_held_shares"],
                    "shares_sold_cumulative": firm_pre.ceo_shares_sold_cumulative,
                    "shares_sold_this_year": shares_sold_this_year,
                    "cash_from_sales_cumulative": firm_pre.ceo_cash_from_sales,
                    "vested_options_held": snap_pre["vested_option_shares"],
                    "unvested_options_held": snap_pre["unvested_option_shares"],
                    "intrinsic_value_vested_options": snap_pre["intrinsic_value_vested_options"],
                    "intrinsic_value_unvested": snap_pre["intrinsic_value_unvested"],
                    "unvested_rsu_shares": snap_pre["unvested_rsu_shares"],
                    "vested_rsu_held_shares": snap_pre["vested_rsu_held_shares"],
                    "vested_option_shares": snap_pre["vested_option_shares"],
                    "unvested_option_shares": snap_pre["unvested_option_shares"],
                    "total_shares_sold_to_date": firm_pre.ceo_shares_sold_cumulative,
                    "n_grants_outstanding": sum(
                        1 for g in firm_pre.ceo_stock_grants
                        if g.shares - g.shares_vested_to_date - g.shares_forfeited > 0
                    ),
                    "fired_flag": 0,
                    "retired_flag": 0,
                    "hired_flag": 0,
                })
            except Exception as e:
                _log(state, f"  Pre-gov snapshot {fid_pre} FAILED: {e}")

    # ── Phase A2: Board governance / CEO review (if governance_enabled) ──
    if is_annual and governance_fn is not None:
        _log(state, "  --- Board Governance ---")
        # Compute peer averages for comparison
        active = {fid: f for fid, f in state.firms.items() if f.is_active}
        all_annual_flows = {}
        for fid in active:
            fid_flows = [fl for fl in state.last_quarter_flows.values()
                         if fl.firm_id == fid]
            # Approximate: use current Q flows * 4 (crude but functional)
            if fid in all_flows:
                all_annual_flows[fid] = [all_flows[fid]]  # just this Q for now

        avg_rev = sum(f.net_sales for f in all_flows.values()) / max(1, len(all_flows)) * 4
        avg_ni = sum(f.reported_net_income for f in all_flows.values()) / max(1, len(all_flows)) * 4

        from .governance import apply_governance_decision

        # First-year firms skip the LLM review — handle those serially.
        to_review = []
        for fid, firm in list(active.items()):
            if firm.ceo_tenure_quarters < 4:
                firm_updated = firm.evolve(
                    ceo_tenure_quarters=firm.ceo_tenure_quarters + 4,
                    ceo_age=firm.ceo_age + 1,
                )
                state.firms[fid] = firm_updated
            else:
                to_review.append((fid, firm))

        # Call governance LLMs in parallel (one per firm eligible for review).
        def _call_gov(fid_firm):
            _fid, _firm = fid_firm
            _flows_4q = all_annual_flows.get(_fid, [])
            try:
                return (_fid, _firm, governance_fn(
                    _firm, _flows_4q, state.macro, avg_rev, avg_ni))
            except Exception as e:
                return (_fid, _firm, e)

        parallel_gov = (config is None
                        or getattr(config, "parallel_firm_decisions", True))
        if parallel_gov and len(to_review) > 1:
            import concurrent.futures as _cf
            with _cf.ThreadPoolExecutor(
                    max_workers=_max_workers(config, len(to_review))) as pool:
                gov_results = list(pool.map(_call_gov, to_review))
        else:
            gov_results = [_call_gov(p) for p in to_review]

        # Apply mutations serially (state.firms, ceo_grant_events, etc).
        from .engine import ActionLog as _AL_gov
        for fid, firm, decision in gov_results:
            if isinstance(decision, Exception):
                _log(state, f"  Governance {fid} FAILED: {decision}")
                continue
            # Record as a structured Action before applying.
            _AL_gov.quick_record(
                state.action_log,
                actor_id="board_governance",
                action_type=("fire_ceo" if decision.get("fire_ceo")
                              else "retire_ceo" if decision.get("offer_retirement")
                              else "review_ceo"),
                payload={
                    "target_firm": fid,
                    "fire_ceo": bool(decision.get("fire_ceo", False)),
                    "retire": bool(decision.get("offer_retirement", False)),
                    "cash_bonus_this_year": decision.get("cash_bonus_this_year", 0.0),
                    "base_salary_next_year": decision.get("base_salary_next_year", 0.0),
                    "new_rsu_shares": (decision.get("new_rsu_grant") or {}).get("shares", 0),
                    "new_option_shares": (decision.get("new_option_grant") or {}).get("shares", 0),
                },
                quarter=state.quarter,
                justification=(decision.get("fire_reason") or decision.get("rationale") or "")[:400],
            )
            try:
                new_firm, grant_events = apply_governance_decision(
                    firm, decision, state.rng, current_quarter=state.quarter,
                )
                new_firm = new_firm.evolve(
                    ceo_tenure_quarters=new_firm.ceo_tenure_quarters + 4,
                    ceo_age=new_firm.ceo_age + 1,
                )
                state.firms[fid] = new_firm
                # Record new grants (Stage 11) — `ceo_grant_events` always
                # exists on WorldState (default_factory=list).
                state.ceo_grant_events.extend(grant_events)
                # Also record each grant as an insider event (SEC Form 4-style)
                from .types import InsiderTradingEvent
                from .wrds_identifiers import abs_quarter_to_datadate
                for g in grant_events:
                    state.insider_events.append(InsiderTradingEvent(
                        run_id=state.run_id, firm_id=fid,
                        ceo_id=g.ceo_id, ceo_incarnation=g.ceo_incarnation,
                        event_quarter=g.grant_quarter,
                        event_date=abs_quarter_to_datadate(g.grant_quarter),
                        event_type="grant", transaction_shares=g.shares,
                        transaction_price=state.firms[fid].equity_price,
                        strike_price=g.strike_price,
                        transaction_value=g.fair_value_at_grant,
                        shares_held_after=state.firms[fid].ceo_vested_shares_held,
                        notes=f"{g.grant_type} grant, FV=${g.fair_value_at_grant:,.0f}",
                    ))
                # Log CEO event (fired / retired / reviewed)
                fired = decision.get("fire_ceo", False)
                retired = decision.get("offer_retirement", False) and firm.ceo_age >= 60 and not fired
                event_type = ("fired" if fired
                              else "retired" if retired
                              else "reviewed")
                # Incoming CEO id: on fire, always new. On retire-with-
                # candidates, incarnation bumped → new CEO installed. On
                # retain or retire-to-search, incoming = departing (no change
                # or pending search). Check incarnation delta for safety.
                incoming = (new_firm.ceo_type
                            if new_firm.ceo_incarnation != firm.ceo_incarnation
                            else firm.ceo_type)
                event = {
                    "run_id": state.run_id,
                    "firm_id": fid,
                    "event_quarter": state.quarter,
                    "event_type": event_type,
                    "departing_ceo_id": firm.ceo_type,
                    "departing_tenure_quarters": firm.ceo_tenure_quarters,
                    "departing_age": firm.ceo_age,
                    "incoming_ceo_id": incoming,
                    "reason": (decision.get("fire_reason", "") if fired
                               else ("voluntary retirement" if retired else "review"))[:200],
                    "severance": 0.0,
                    "new_rsu_shares": (decision.get("new_rsu_grant") or {}).get("shares", 0),
                    "new_option_shares": (decision.get("new_option_grant") or {}).get("shares", 0),
                    "cash_bonus_this_year": decision.get("cash_bonus_this_year", 0.0),
                    "base_salary_next_year": decision.get("base_salary_next_year", 0.0),
                }
                if fid not in state.ceo_history:
                    state.ceo_history[fid] = []
                state.ceo_history[fid].append(event)
                if fired:
                    _log(state, f"  GOVERNANCE {fid}: CEO FIRED — {decision.get('fire_reason', '')[:80]}")
                elif retired:
                    _log(state, f"  GOVERNANCE {fid}: CEO RETIRED (age {firm.ceo_age}, "
                                f"vesting accelerated)")
                else:
                    _log(state, f"  GOVERNANCE {fid}: CEO retained "
                                f"(rsu={len(grant_events)} grants, "
                                f"bonus=${decision.get('cash_bonus_this_year', 0)/1e6:.2f}M)")

                # ── Capture year-end CEO snapshot for ExecuComp datasets ──
                # B1-B3 fix: for fire/retire paths, the snapshot must reflect
                # the DEPARTING CEO's final fyear (their identity, their
                # salary this year, their holdings right before/at separation).
                # For retain, snapshot uses continuing CEO state.
                from .ceo_comp import (
                    outstanding_snapshot as _snap, forfeit_unvested as _forfeit,
                    accelerate_vesting_on_retirement as _accel,
                )
                year_grants = [g for g in grant_events]
                stock_fv = sum(g.fair_value_at_grant for g in year_grants
                               if g.grant_type == "rsu")
                option_fv = sum(g.fair_value_at_grant for g in year_grants
                                if g.grant_type == "stock_option")

                if fired:
                    # Departing CEO's final-year snapshot. Use PRE-decision
                    # firm state (identity + tenure + salary + historical
                    # cumulative sold). Apply forfeit to get accurate
                    # end-of-year holdings (vested held they keep; unvested
                    # forfeited). No new grants for departing CEO, no bonus.
                    snap_firm = _forfeit(firm)  # firm = pre-decision
                    snap = _snap(snap_firm, firm.equity_price or 0.01)
                    ceo_id_snap = firm.ceo_type
                    age_snap = firm.ceo_age
                    tenure_snap = firm.ceo_tenure_quarters / 4
                    base_salary_snap = firm.ceo_base_salary
                    bonus_snap = 0.0
                    stock_fv_snap = 0.0
                    option_fv_snap = 0.0
                    # shares_sold_this_year requires prior-year snapshot diff
                    prior_cum_for_diff = 0
                    for snap_prior in reversed(state.execucomp_annual_snapshots):
                        if snap_prior["firm_id"] == fid:
                            prior_cum_for_diff = snap_prior.get("shares_sold_cumulative", 0)
                            break
                    shares_sold_this_year = (snap["total_shares_sold_to_date"]
                                              - prior_cum_for_diff)
                elif retired:
                    # Departing CEO retiring voluntarily. Accelerate vesting
                    # on pre-decision firm, snapshot that. No new grants.
                    snap_firm, _ = _accel(firm)
                    snap = _snap(snap_firm, firm.equity_price or 0.01)
                    ceo_id_snap = firm.ceo_type
                    age_snap = firm.ceo_age
                    tenure_snap = firm.ceo_tenure_quarters / 4
                    base_salary_snap = firm.ceo_base_salary
                    bonus_snap = decision.get("cash_bonus_this_year", 0.0)
                    stock_fv_snap = 0.0
                    option_fv_snap = 0.0
                    prior_cum_for_diff = 0
                    for snap_prior in reversed(state.execucomp_annual_snapshots):
                        if snap_prior["firm_id"] == fid:
                            prior_cum_for_diff = snap_prior.get("shares_sold_cumulative", 0)
                            break
                    shares_sold_this_year = (snap["total_shares_sold_to_date"]
                                              - prior_cum_for_diff)
                else:
                    # Retain: continuing CEO, post-decision state (includes
                    # new grants, incremented tenure).
                    cur_firm = state.firms[fid]
                    snap = _snap(cur_firm, cur_firm.equity_price or 0.01)
                    ceo_id_snap = cur_firm.ceo_type
                    age_snap = cur_firm.ceo_age
                    tenure_snap = cur_firm.ceo_tenure_quarters / 4
                    base_salary_snap = cur_firm.ceo_base_salary
                    bonus_snap = decision.get("cash_bonus_this_year", 0.0)
                    stock_fv_snap = stock_fv
                    option_fv_snap = option_fv
                    prior_cum_for_diff = 0
                    for snap_prior in reversed(state.execucomp_annual_snapshots):
                        if snap_prior["firm_id"] == fid:
                            prior_cum_for_diff = snap_prior.get("shares_sold_cumulative", 0)
                            break
                    shares_sold_this_year = (snap["total_shares_sold_to_date"]
                                              - prior_cum_for_diff)

                state.execucomp_annual_snapshots.append({
                    "firm_id": fid,
                    "fyear": state.macro.fyear,
                    "ceo_id": ceo_id_snap,
                    "age": age_snap,
                    "tenure_years": tenure_snap,
                    "base_salary": base_salary_snap,
                    "cash_bonus_this_year": bonus_snap,
                    "stock_awards_value": stock_fv_snap,
                    "option_awards_value": option_fv_snap,
                    "shares_owned_eoy": snap["vested_rsu_held_shares"],
                    "shares_sold_cumulative": snap["total_shares_sold_to_date"],
                    "shares_sold_this_year": shares_sold_this_year,
                    "cash_from_sales_cumulative": snap["cash_from_sales_cumulative"],
                    "vested_options_held": snap["vested_option_shares"],
                    "unvested_options_held": snap["unvested_option_shares"],
                    "intrinsic_value_vested_options": snap["intrinsic_value_vested_options"],
                    "intrinsic_value_unvested": snap["intrinsic_value_unvested"],
                    "unvested_rsu_shares": snap["unvested_rsu_shares"],
                    "vested_rsu_held_shares": snap["vested_rsu_held_shares"],
                    "vested_option_shares": snap["vested_option_shares"],
                    "unvested_option_shares": snap["unvested_option_shares"],
                    "n_grants_outstanding": sum(
                        1 for g in (firm if (fired or retired) else state.firms[fid]).ceo_stock_grants
                        if g.shares - g.shares_vested_to_date - g.shares_forfeited > 0
                    ),
                    "fired_flag": 1 if fired else 0,
                    "retired_flag": 1 if retired else 0,
                    # `hired_flag` means an incoming CEO was hired THIS fyear.
                    # True on fire (replacement) or retirement. Separate flag
                    # from `fired_flag` — not redundant.
                    "hired_flag": 1 if (fired or retired) else 0,
                })
            except Exception as e:
                _log(state, f"  Governance {fid} FAILED: {e}")

    _bs_snap = _check_bs_invariants(state, "phase_A2_governance", _bs_snap)

    # ── Wave θ: Director lifecycle (toggleable) ─────────────────────────
    # Fires every quarter (default departures on any quarter) but refresh
    # events only at fqtr==4. Off = static director pool at founding.
    if config is not None and getattr(config, "director_lifecycle_enabled", False):
        _director_lifecycle_phase(state)

    # ── Phase 15.9: End-of-quarter debrief notes (Wave ν+12) ─────────────
    # Each active firm + env + each intermediary writes a short narrative
    # note capturing what mattered this quarter. Surfaced in next quarter's
    # prompts via agent_history.render_recent_debriefs(). Toggle-able via
    # config.debriefs_enabled (default ON).
    if (config is not None and getattr(config, "debriefs_enabled", True)
            and (firm_debrief_fn is not None
                  or env_debrief_fn is not None
                  or intermediary_debrief_fns)):
        try:
            from .debriefs import (
                build_firm_quarter_summary, build_env_quarter_summary,
                build_intermediary_quarter_summary,
            )
            # Firms
            if firm_debrief_fn is not None:
                for fid, firm in state.firms.items():
                    # Wave ν+14b: skip dormant firms — they haven't operated
                    # so they have nothing meaningful to debrief. Run-6 wasted
                    # ~1100 LLM calls writing "uneventful quarter" notes for
                    # firms that never made a decision.
                    if not firm.is_active or firm.is_dormant:
                        continue
                    summary = build_firm_quarter_summary(fid, state, state.macro)
                    note = firm_debrief_fn(fid, state.quarter, summary)
                    if note:
                        state.debrief_notes.append({
                            "role": "firm", "agent_id": fid,
                            "quarter": state.quarter, "note": note,
                        })
            # Environment
            if env_debrief_fn is not None:
                summary = build_env_quarter_summary(state, state.macro)
                note = env_debrief_fn(state.quarter, summary)
                if note:
                    state.debrief_notes.append({
                        "role": "env", "agent_id": "env",
                        "quarter": state.quarter, "note": note,
                    })
            # Intermediaries (passed as dict: role → writer_fn)
            for role, writer_fn in (intermediary_debrief_fns or {}).items():
                if writer_fn is None:
                    continue
                summary = build_intermediary_quarter_summary(
                    role, role, state, state.macro,
                )
                note = writer_fn(role, state.quarter, summary)
                if note:
                    state.debrief_notes.append({
                        "role": role, "agent_id": role,
                        "quarter": state.quarter, "note": note,
                    })
            _log(state, f"  DEBRIEFS: wrote {len([n for n in state.debrief_notes if n['quarter']==state.quarter])} notes this quarter")
        except Exception as e:
            _log(state, f"  Debrief phase failed (non-fatal): {e}")

    # ── Phase 16: Record-keeping ─────────────────────────────────────────

    # Summary line
    active_firms = sum(1 for f in state.firms.values() if f.is_active)
    total_rev = sum(all_flows[fid].net_sales for fid in all_flows)
    _log(state, f"  Summary: {active_firms} active firms, "
                f"total revenue ${total_rev/1e6:.1f}M")

    # ── Phase 16.5: End-of-quarter completeness check (Wave ν+14h) ──────
    # Per user direction: "at the end of each Q, there needs to be a
    # bug check for missing decisions ... One should not move forward
    # if there is an issue."
    #
    # The check is deterministic (no LLM). It verifies that every
    # operating decision-point that SHOULD have produced a logged
    # action this quarter actually did. Raises QuarterCompletenessError
    # on violations so the simulation halts immediately rather than
    # silently moving forward with missing data.
    #
    # What's checked:
    #   - Every active+non-dormant firm has a set_quarterly_decisions
    #     action logged for this quarter
    #   - Every active+public firm has either an equity_market price
    #     update OR an explicit fallback note this quarter (when
    #     equity_market_fn was wired)
    #   - The env produced a market resolution (resolve_market action
    #     logged) when env_agent_fn was wired
    violations = _check_quarter_completeness(
        state, env_agent_fn, equity_market_fn,
    )
    if violations:
        msg = ("QUARTER COMPLETENESS CHECK FAILED — refusing to advance.\n"
               + "Violations:\n  - " + "\n  - ".join(violations[:30])
               + f"\n(Total: {len(violations)} violations)")
        _log(state, msg)
        print(msg, flush=True)
        raise QuarterCompletenessError(msg)

    return state


class QuarterCompletenessError(RuntimeError):
    """Raised when end-of-quarter checks find missing required decisions.

    Per user direction: the simulation must NOT move forward if any
    required decision is missing. This exception halts the run so the
    operator can investigate. Backup chains catch transient LLM
    failures upstream; if this still fires, something deeper is wrong.
    """


def _check_quarter_completeness(
    state: WorldState,
    env_agent_fn=None,
    equity_market_fn=None,
) -> list[str]:
    """Deterministic end-of-quarter sanity check. Returns list of
    violation strings (empty list = clean).
    """
    violations: list[str] = []
    q = state.quarter

    # 1. Every active+non-dormant firm should have a logged decision this Q
    have_decisions: set[str] = {
        a.get("actor_id", "") for a in (state.action_log or [])
        if a.get("action_type") == "set_quarterly_decisions"
        and a.get("quarter") == q
    }
    for fid, firm in state.firms.items():
        if not firm.is_active or firm.is_dormant:
            continue
        if fid not in have_decisions:
            violations.append(
                f"firm {fid} (active, not dormant) has no "
                f"set_quarterly_decisions action this quarter (Q{q})"
            )

    # 2. Env must have produced a market resolution when env_agent_fn wired
    if env_agent_fn is not None:
        env_actions = [
            a for a in (state.action_log or [])
            if a.get("action_type") == "resolve_market"
            and a.get("quarter") == q
        ]
        if not env_actions:
            violations.append(
                f"env_agent_fn wired but no resolve_market action this Q{q}"
            )

    # 3. Every public+active firm should have an equity_market price
    # update OR an explicit fallback note this quarter (when
    # equity_market_fn was wired).
    if equity_market_fn is not None:
        priced_firms: set[str] = {
            a.get("payload", {}).get("target_firm", "")
            for a in (state.action_log or [])
            if a.get("action_type") == "price_equity"
            and a.get("quarter") == q
            and a.get("actor_id") == "equity_market"
        }
        for fid, firm in state.firms.items():
            if not (firm.is_active and getattr(firm, "is_public", False)):
                continue
            if fid not in priced_firms:
                violations.append(
                    f"firm {fid} (public, active) has no equity price "
                    f"update this Q{q} — equity panel may have failed silently"
                )

    return violations


# ─── Helpers ─────────────────────────────────────────────────────────────

def _advance_macro(state: WorldState) -> MacroState:
    """Advance time, draw shocks, return new MacroState."""
    q = state.quarter
    prior = state.macro

    # Calendar
    fyear = 2031 + (q - 1) // 4
    fqtr = ((q - 1) % 4) + 1

    # Risk-free rate (random walk, bounded)
    rate_shock = state.rng.gauss(0, 0.002)
    new_rate = max(0.005, min(0.05, prior.risk_free_rate + rate_shock))

    # Awareness growth
    new_awareness = min(0.98, prior.awareness_rate + 0.02)

    # Macro demand shock
    macro_shock = state.rng.gauss(0, 0.08)

    # Taste shocks (per firm)
    taste_shocks = {
        fid: state.rng.gauss(0, 0.05)
        for fid in state.firms
    }

    # ── Macro expansion (when macro_expansion_enabled) ──
    # Political uncertainty: mean-reverting to 0.3 with shocks
    new_pol_unc = max(0.0, min(1.0,
        prior.political_uncertainty * 0.9 + 0.03 + state.rng.gauss(0, 0.05)))

    # Market return: random walk around 2%/Q (8% annual)
    mkt_return_q = state.rng.gauss(0.02, 0.06)
    new_mkt_return_ytd = (prior.market_return_ytd + mkt_return_q
                          if fqtr > 1 else mkt_return_q)  # reset at Q1

    # Risk premium: mean-reverting to 5% annual
    new_risk_prem = max(0.02, min(0.12,
        prior.market_risk_premium * 0.95 + 0.0025 + state.rng.gauss(0, 0.005)))

    return MacroState(
        quarter=q,
        fyear=fyear,
        fqtr=fqtr,
        risk_free_rate=new_rate,
        market_size_baseline=prior.market_size_baseline,
        awareness_rate=new_awareness,
        macro_shock=macro_shock,
        taste_shocks=taste_shocks,
        political_uncertainty=new_pol_unc,
        market_return_ytd=new_mkt_return_ytd,
        market_risk_premium=new_risk_prem,
    )


def _director_lifecycle_phase(state: "WorldState") -> None:
    """Annual director refresh + default-triggered departures.

    Runs at end of Q4 when `director_lifecycle_enabled`. Two effects:
    - DEFAULT DEPARTURE: directors seated at defaulted firms lose that seat.
      When a director's seat count drops to 0, they leave the pool.
    - ANNUAL REFRESH: ~25% probability per firm that one director rotates
      out and a fresh director (from the unused name pool) is appointed.
      Simulates the normal 3-4 year director terms observed empirically.

    Every event appends to `state.director_turnover` for research.
    """
    from .identifiers import Director
    from dataclasses import replace as _replace

    if not state.directors:
        return

    # ── Default-triggered departures ──────────────────────────────────
    active_firm_ids = {fid for fid, f in state.firms.items() if f.is_active}
    for did, director in list(state.directors.items()):
        kept_seats = tuple(s for s in director.seats if s in active_firm_ids)
        lost_seats = tuple(s for s in director.seats if s not in active_firm_ids)
        if lost_seats:
            for firm_id in lost_seats:
                state.director_turnover.append({
                    "event_quarter": state.quarter,
                    "event_type": "firm_default_departure",
                    "director_id": did,
                    "director_name": director.name,
                    "firm_id": firm_id,
                    "reason": "firm defaulted; seat vacated",
                })
            if kept_seats:
                state.directors[did] = _replace(director, seats=kept_seats)
            else:
                # Director loses all seats — remove from pool.
                del state.directors[did]

    # ── Annual refresh (Q4 only) ──────────────────────────────────────
    if state.macro.fqtr != 4:
        return
    # For each active firm: 25% chance one director rotates out.
    for firm_id in sorted(active_firm_ids):
        if state.rng.random() >= 0.25:
            continue
        # Find this firm's seated directors
        seated_here = [
            (did, d) for did, d in state.directors.items()
            if firm_id in d.seats
        ]
        if not seated_here:
            continue
        # Retire the oldest director
        did_out, d_out = max(seated_here, key=lambda x: x[1].age)
        new_seats = tuple(s for s in d_out.seats if s != firm_id)
        state.director_turnover.append({
            "event_quarter": state.quarter,
            "event_type": "retirement",
            "director_id": did_out,
            "director_name": d_out.name,
            "firm_id": firm_id,
            "reason": f"annual refresh (age {d_out.age}, {len(d_out.seats)} seats → "
                      f"{len(new_seats)})",
        })
        if new_seats:
            state.directors[did_out] = _replace(d_out, seats=new_seats)
        else:
            del state.directors[did_out]

        # Appoint replacement: prefer a NEW name (not yet in pool)
        used_names = {d.name for d in state.directors.values()}
        used_ids = set(state.directors.keys())
        fresh_candidates = [
            (i, n) for i, n in enumerate(_DIRECTOR_NAMES)
            if n not in used_names and f"director_{i+1:03d}" not in used_ids
        ]
        if fresh_candidates:
            idx, name = state.rng.choice(fresh_candidates)
            new_did = f"director_{idx+1:03d}"
            new_d = Director(
                director_id=new_did,
                name=name,
                age=50 + state.rng.randint(0, 15),
                seats=(firm_id,),
                independent=True,
            )
            state.directors[new_did] = new_d
            state.director_turnover.append({
                "event_quarter": state.quarter,
                "event_type": "appointment",
                "director_id": new_did,
                "director_name": name,
                "firm_id": firm_id,
                "reason": f"replacement appointment (fresh, age {new_d.age})",
            })
        else:
            # Pool exhausted — pick an existing unseated-at-this-firm director
            existing = [
                d for d in state.directors.values()
                if firm_id not in d.seats and len(d.seats) < 3
            ]
            if existing:
                chosen = state.rng.choice(existing)
                idx = list(state.directors.keys()).index(chosen.director_id)
                state.directors[chosen.director_id] = _replace(
                    chosen, seats=chosen.seats + (firm_id,)
                )
                state.director_turnover.append({
                    "event_quarter": state.quarter,
                    "event_type": "appointment",
                    "director_id": chosen.director_id,
                    "director_name": chosen.name,
                    "firm_id": firm_id,
                    "reason": f"replacement appointment (interlock: now {len(chosen.seats)+1} seats)",
                })


def _count_shared_directors(state: "WorldState",
                              firm_a: str, firm_b: str) -> int:
    """Count directors seated at BOTH firms (interlock strength).

    Wave θ: input to the interlocking-directorship info-leak mechanism.
    Returns 0 if either firm has no seated directors.
    """
    directors = getattr(state, "directors", None) or {}
    if not directors:
        return 0
    count = 0
    for d in directors.values():
        if firm_a in d.seats and firm_b in d.seats:
            count += 1
    return count


def _build_firm_info_package(state: WorldState, target_firm_id: str) -> dict:
    """Build the info package for ONE specific firm.

    This function enforces information separation at the source:
    - The firm receives ONLY its own private data
    - It receives PUBLIC data about competitors (no private fields)
    - No other firm's private data is included in the dict at all

    Information tiers:
      PUBLIC    -- observable from market (price, share, generation, equity price, revenue, total R&D)
      PRIVATE   -- only this firm sees (own cash, costs, R&D pipeline, brand details, operational reports)
      UNOBSERVED -- not in this dict at all (taste shocks, demand model params, other firms' private data)
    """

    # PUBLIC: competitor info (same for everyone, excludes target firm).
    # Wave epsilon: if noisy_signals_enabled, peer numerics get Gaussian
    # noise applied per-firm via a seeded RNG (reproducible: the seed
    # is (quarter, target_firm_id, peer_fid) so two firms observing the
    # same peer get DIFFERENT noisy observations).
    #
    # Wave θ: INTERLOCKING-DIRECTOR INFO LEAK. If observer and observed
    # share ≥1 director, that director transmits information informally.
    # Noise SD is divided by (1 + n_shared_directors). With 1 shared
    # director, effective noise halves; with 2, it's a third. This gates
    # a testable hypothesis: interlocked peer observations are more
    # accurate (lower RMSE vs true value). Only active when noise is on.
    noisy = bool(getattr(state.params, "noisy_signals_enabled", False))
    noise_sd = float(getattr(state.params, "noisy_signals_sd", 0.05))
    if noisy:
        from .beliefs import observe_peer_data
        import random as _rand

    public_competitors = {}
    # Wave ν+11 fix for E5: assemble each peer's last 4 quarters of public
    # data (revenue + market share) so the target firm can read peer
    # trajectories, not just current snapshot. Without this, firms had no
    # way to detect "competitor X is rising / falling" — they could only
    # see current-quarter levels. This blocks rational strategic planning.
    peer_history_4q: dict[str, list] = {}
    if state.compustat_rows:
        # Compute industry total revenue per quarter for share denominator
        per_q_total: dict = {}
        for r in state.compustat_rows:
            key = (r.fyearq, r.fqtr)
            per_q_total[key] = per_q_total.get(key, 0.0) + r.saleq
        # Per-firm last-4 rows
        per_firm: dict = {}
        for r in state.compustat_rows:
            per_firm.setdefault(r.firm_id, []).append(r)
        for fid_p, rows in per_firm.items():
            rows.sort(key=lambda r: (r.fyearq, r.fqtr))
            recent = rows[-4:]
            peer_history_4q[fid_p] = [
                {
                    "saleq": r.saleq,
                    "share": (r.saleq / per_q_total[(r.fyearq, r.fqtr)]
                              if per_q_total[(r.fyearq, r.fqtr)] > 0 else 0),
                }
                for r in recent
            ]

    for fid, firm in state.firms.items():
        if not firm.is_active or fid == target_firm_id:
            continue
        flows = state.last_quarter_flows.get(fid)
        true_public = {
            "price": flows.actual_price if flows else 0,
            "market_share": flows.market_share if flows else 0,
            "generation": firm.product_generation,
            "equity_price": firm.equity_price,
            "revenue": flows.net_sales if flows else 0,
            "total_rd_spend": flows.rd_expense if flows else 0,
            # Wave ν+11: peer trajectory (4Q public history)
            "revenue_history_4q": [h["saleq"] for h in peer_history_4q.get(fid, [])],
            "share_history_4q": [h["share"] for h in peer_history_4q.get(fid, [])],
        }
        if noisy:
            # Per-(quarter, observer, observed) seed keeps noise reproducible
            # across re-runs with the same simulation seed.
            seed = hash((state.quarter, target_firm_id, fid)) & 0xFFFFFFFF
            rng = _rand.Random(seed)
            # Wave θ: reduce noise on interlocked observations
            shared_dirs = _count_shared_directors(state, target_firm_id, fid)
            effective_sd = noise_sd / (1 + shared_dirs)
            observation = observe_peer_data(
                true_public, rng, relative_sd=effective_sd,
            )
            public_competitors[fid] = observation
            # Wave θ+: log this observation event with interlock count AT
            # OBSERVATION TIME (for clean regression analysis).
            state.peer_observation_log.append({
                "quarter": state.quarter,
                "observer": target_firm_id,
                "observed": fid,
                "n_shared_directors": shared_dirs,
                "noise_sd_applied": effective_sd,
                "true_revenue": true_public["revenue"],
                "observed_revenue": observation["revenue"],
                "true_price": true_public["price"],
                "observed_price": observation["price"],
            })
        else:
            public_competitors[fid] = true_public

    # Wave epsilon: update this firm's belief state via EWMA from the
    # (possibly noisy) peer observations. Stored persistently so snapshots
    # preserve belief dynamics. Not currently read by the LLM prompt but
    # available for research panel queries.
    if public_competitors:
        from .beliefs import FirmBelief as _FB, update_firm_belief as _upd
        belief = state.firm_beliefs.setdefault(
            target_firm_id, _FB(firm_id=target_firm_id))
        _upd(belief, public_competitors, state.quarter, alpha=0.5)

    # PRIVATE: only this firm's own data
    own_flows = state.last_quarter_flows.get(target_firm_id)
    own_private = {
        "cash": state.firms[target_firm_id].cash,
        "total_assets": state.firms[target_firm_id].total_assets,
        "total_equity": state.firms[target_firm_id].total_equity,
        "net_income": own_flows.net_income if own_flows else 0,
        "cfo": own_flows.cfo if own_flows else 0,
        "capex": own_flows.actual_capex if own_flows else 0,
        "sga_spend": own_flows.sga_expense if own_flows else 0,
        "units_sold": own_flows.units_sold if own_flows else 0,
        "rd_report": state.rd_reports.get(target_firm_id),
        "brand_report": state.brand_reports.get(target_firm_id),
    }

    # Env operational notes from last quarter (Stage 11.5) — tells this
    # firm what actually happened if env moderated their plan. Filter out
    # activist-campaign notes (those are surfaced separately below with
    # structured data so the firm can issue a formal response).
    raw_notes = state.pending_env_notes.get(target_firm_id, [])
    env_notes = [n for n in raw_notes if not n.startswith("ACTIVIST CAMPAIGN")]

    # Wave ν+10 item 10: investment-bank feedback from a declined or
    # haircut issuance last quarter. Surfaced to the firm as a public
    # market signal so it can submit a modified resubmission.
    ibank_feedback = state.pending_ibank_feedback.get(target_firm_id)
    if ibank_feedback:
        # Stale-bound: only show if from the most recent quarter or
        # immediately prior.
        if state.quarter - ibank_feedback.get("issued_quarter", 0) > 1:
            ibank_feedback = None

    # Wave epsilon: noisy macro observation. When enabled, risk_free_rate,
    # awareness_rate, and market_risk_premium are observed with noise.
    # quarter + fyear + fqtr stay EXACT (calendar dates don't have noise).
    macro_dict = {
        "risk_free_rate": state.macro.risk_free_rate,
        "awareness_rate": state.macro.awareness_rate,
        "quarter": state.quarter,
        "fyear": state.macro.fyear,
        "fqtr": state.macro.fqtr,
    }
    if noisy:
        from .beliefs import add_observation_noise
        import random as _rand_m
        m_seed = hash((state.quarter, target_firm_id, "macro")) & 0xFFFFFFFF
        m_rng = _rand_m.Random(m_seed)
        macro_dict["risk_free_rate"] = add_observation_noise(
            macro_dict["risk_free_rate"], m_rng, noise_sd)
        macro_dict["awareness_rate"] = add_observation_noise(
            macro_dict["awareness_rate"], m_rng, noise_sd)

    # Wave epsilon: analyst consensus for THIS firm, if analysts have
    # covered it. Exposed as `analyst_consensus` in the info_package so
    # the firm + equity market can read it. Consensus is computed from
    # the most recent note per analyst per firm (not averaged over time).
    latest_per_analyst: dict = {}  # analyst_id -> most-recent note
    for n in state.analyst_notes:
        if n.firm_id != target_firm_id:
            continue
        prior = latest_per_analyst.get(n.analyst_id)
        if prior is None or n.quarter >= prior.quarter:
            latest_per_analyst[n.analyst_id] = n
    consensus = None
    if latest_per_analyst:
        notes = list(latest_per_analyst.values())
        tp_vals = [n.target_price for n in notes if n.target_price > 0]
        eps_vals = [n.eps_forecast_1q for n in notes]
        ratings = [n.rating for n in notes]
        consensus = {
            "n_analysts": len(notes),
            "mean_target_price": (sum(tp_vals) / len(tp_vals)) if tp_vals else None,
            "min_target_price": min(tp_vals) if tp_vals else None,
            "max_target_price": max(tp_vals) if tp_vals else None,
            "mean_eps_forecast_1q": (sum(eps_vals) / len(eps_vals))
                                      if eps_vals else None,
            "buy_count": sum(1 for r in ratings if r == "buy"),
            "hold_count": sum(1 for r in ratings if r == "hold"),
            "sell_count": sum(1 for r in ratings if r == "sell"),
        }

    # Unresolved activist campaigns targeting this firm — surfaced as
    # structured objects so the firm's decision JSON includes a response.
    active_campaigns = [
        c for c in state.activist_campaigns
        if c.get("firm_id") == target_firm_id and not c.get("firm_response")
    ]

    # Wave ι: scenario-driven industry character + market signals
    industry_character = _build_industry_character_dict(state)
    market_signals = _build_market_signals_dict(state, target_firm_id)

    # Wave κ: strategic plan + recent variances for this firm.
    # Wave μ: also pass current fyear/fqtr so plan surfaces this quarter's
    # committed pacing (for deviation-justification language).
    from .strategic_planning import plan_variance_summary_for_prompt
    plan_context = plan_variance_summary_for_prompt(
        state.firms[target_firm_id],
        current_fyear=state.macro.fyear,
        current_fqtr=state.macro.fqtr,
    )

    # Wave ν: peer projections made public when shared in a PE raise.
    # Competitor firms + the target firm itself can see what others are
    # promising their investors. This gives the market a projection
    # reference point distinct from current-quarter revenue.
    peer_pe_projections = []
    for round_event in (state.pe_round_history or [])[-30:]:
        if round_event.firm_id == target_firm_id:
            continue  # firm already knows its own pitch
        if not round_event.firm_projections:
            continue
        peer_pe_projections.append({
            "firm_id": round_event.firm_id,
            "round_type": round_event.round_type,
            "round_quarter": round_event.round_quarter,
            "post_money_valuation": round_event.post_money_valuation,
            "firm_projections": round_event.firm_projections,
            "lead_investor_projection": round_event.lead_investor_projection,
            "lead_valuation_method": round_event.lead_valuation_method,
        })

    return {
        "public_competitors": public_competitors,
        "own_private": own_private,
        "macro": macro_dict,
        "gazette": state.gazettes[-1] if state.gazettes else "",
        "env_notes": env_notes,
        "pending_activist_campaigns": active_campaigns,
        # Wave ν+12: investor voice note (end of last quarter)
        "investor_note": (state.investor_notes_by_firm or {}).get(target_firm_id, ""),
        # Wave epsilon: analyst consensus (None when no coverage yet)
        "analyst_consensus": consensus,
        # Wave ι: scenario-driven industry context + market signals
        "industry_character": industry_character,
        "market_signals": market_signals,
        # Wave κ: strategic plan context (empty dict if planning disabled
        # or firm has no plan yet)
        "plan_context": plan_context,
        # Wave ν: peer PE projections shared in recent rounds
        "peer_pe_projections": peer_pe_projections,
        # Wave ν+10 item 10: investment-bank feedback from declined /
        # haircut issuance. None unless the firm had a recent decline.
        "ibank_feedback": ibank_feedback,
    }


def _run_entry_phase(state, entry_judge_fn, config) -> None:
    """Wave ν+2: endogenous entry phase.

    Each quarter (after Q1), the entry judge LLM decides whether to
    spawn a new firm. New firms occupy reserved slots (slot_id with
    empty current_firm_id). Capped at state.n_firms_max.

    Founded firms enter at lifecycle_stage='founded' with seed cash so
    they immediately participate in the next quarter's PE round phase
    (matching the path Q1 founders take).
    """
    from .entry import (
        summarize_industry_for_entry_judge,
        make_entrant_firm,
    )

    # Slot accounting
    n_active = sum(1 for f in state.firms.values() if f.is_active)
    n_max = getattr(state, "n_firms_max", 20)
    # Find first empty slot index (entry uses unused firm_X ids)
    used_indices = set()
    for fid in state.firms:
        try:
            used_indices.add(int(fid.split("_")[-1]))
        except (ValueError, IndexError):
            continue
    available_slot_idx = None
    for i in range(n_max):
        if i not in used_indices:
            available_slot_idx = i
            break
    if available_slot_idx is None:
        return  # cap reached

    slots_remaining = n_max - len(state.firms)
    if slots_remaining <= 0:
        return

    # Recent defaults (last 4Q) — signal for entry attractiveness
    recent_defaults = sum(
        1 for slot in state.slots.values()
        for d in (slot.default_history or [])
        if d.get("quarter", -999) >= state.quarter - 4
    )

    industry_summary = summarize_industry_for_entry_judge(state)
    decision = entry_judge_fn(
        industry_summary=industry_summary,
        slots_remaining=slots_remaining,
        recent_defaults=recent_defaults,
        q_index=state.quarter,
    )
    if decision is None or not decision.get("should_spawn_entrant", False):
        return

    profile = decision.get("entrant_profile", {}) or {}
    new_firm_id = f"firm_{available_slot_idx}"
    new_slot_id = f"slot_{available_slot_idx}"

    # Pull base unit cost from scenario or params
    base_cost = float(getattr(state.params.gen_base_cogs, "get",
                               lambda *_: 14_000)(1) or 14_000) if hasattr(state.params, "gen_base_cogs") else 14_000

    new_firm = make_entrant_firm(
        firm_id=new_firm_id,
        slot_id=new_slot_id,
        incarnation=1,
        profile=profile,
        base_unit_cost=base_cost,
        rng=state.rng,
        regional_markets_enabled=getattr(config, "regional_markets_enabled", True),
    )

    # Wave ν+3: founder seed cash is whatever the entry judge decided.
    # No code-side scaling against scenario, no leapfrog multiplier —
    # both would re-introduce hardcoded behavioral rules. The judge sees
    # the scenario context and produces an emergent number. Code only
    # enforces non-negative + a tiny positive floor so the firm exists.
    if getattr(config, "pe_lifecycle_enabled", False):
        seed_cash = float(profile.get("founder_capital_seed_usd", 0) or 0)
        # Bare-minimum positive floor: a founded firm needs SOME cash to
        # exist; truly zero would crash downstream finance code. This is
        # not a behavioral signal, just a sanity floor.
        seed_cash = max(1.0, seed_cash)
        founder_shares = 1_000_000
        in_kind_ppe = float(new_firm.ppe_net)  # treat existing PPE as contributed
        new_firm = new_firm.evolve(
            cash=seed_cash,
            apic=seed_cash + in_kind_ppe,
            shares_outstanding=founder_shares,
            founder_shares=founder_shares,
            public_shares_outstanding=0,
            lifecycle_stage="founded",
            is_public=False,
        )

    state.firms[new_firm_id] = new_firm
    state.slots[new_slot_id] = SlotInfo(
        slot_id=new_slot_id,
        current_firm_id=new_firm_id,
        incarnation=1,
    )
    leapfrog_flag = bool(profile.get("leapfrog_candidate", False))
    state.entry_events.append({
        "quarter": state.quarter,
        "firm_id": new_firm_id,
        "rationale": str(decision.get("rationale", ""))[:500],
        "starting_capability": new_firm.capability_stock,
        "starting_brand": new_firm.brand_stock,
        "leapfrog_candidate": leapfrog_flag,
        "narrative": str(profile.get("narrative", ""))[:300],
    })
    msg = (f"  ENTRY Q{state.quarter}: {new_firm_id} spawned "
           f"(cap={new_firm.capability_stock:.0f}, "
           f"brand={new_firm.brand_stock:.0f}, "
           f"cash=${new_firm.cash/1e6:.0f}M"
           f"{', LEAPFROG' if leapfrog_flag else ''}). "
           f"{(decision.get('rationale') or '')[:100]}")
    _log(state, msg)
    print(msg, flush=True)


def _coerce_money(v) -> float:
    """Coerce LLM-emitted money values to float, tolerating '$', ',', '%'.

    LLMs occasionally return '$150,000,000' instead of 150000000 even when
    the schema says number. This was caught in the v3 5x16Q run when a
    pitch crashed _run_pe_round_phase. Single tight helper, used at the
    four PE auction call sites only.
    """
    if v is None:
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    try:
        s = str(v).strip().replace("$", "").replace(",", "").replace("%", "")
        return float(s) if s else 0.0
    except (TypeError, ValueError):
        return 0.0


def _run_pe_round_phase(
    state: "WorldState",
    pitch_fn,
    pe_eval_fns: dict,
    config,
) -> None:
    """Wave λ Phase 1.5: PE round auction.

    For each private firm needing capital (low cash runway or
    first-round firm with no capital raised yet), run a pitch → bid →
    select cycle. Executes the selected deal via execute_pe_round.
    """
    from .private_equity import execute_pe_round

    industry_character = _build_industry_character_dict(state)

    # Identify firms that need/should raise this quarter
    # Wave λ Fix 2: more permissive triggers — real biotechs raise
    # MULTIPLE times in 5 years, not just once. Lower runway threshold
    # to 8Q (2 years out) so firms can raise BEFORE crisis. Cooldown
    # between rounds dropped from 2Q to 1Q so back-to-back rounds work.
    for fid, firm in list(state.firms.items()):
        if not firm.is_active or firm.is_public:
            continue
        first_round_needed = firm.lifecycle_stage == "founded"
        # Estimate quarterly burn from recent flows
        last_flows = state.last_quarter_flows.get(fid)
        burn = max(10_000_000, (last_flows.sga_expense + last_flows.rd_expense)
                   if last_flows else 20_000_000)
        runway_q = firm.cash / burn if burn > 0 else 999
        # Trigger follow-on when runway < 8Q AND last round was at least
        # 1Q ago (avoid same-quarter double rounds).
        runway_low = runway_q < 8.0 and firm.last_round_quarter < state.quarter - 1
        # Trigger when firm explicitly asked for capital last quarter
        # but didn't get most of it (Fix 3 + Fix 2 interaction).
        underfunded = (
            firm.last_funding_ask > 0
            and firm.last_funding_received < 0.5 * firm.last_funding_ask
            and firm.last_round_quarter < state.quarter - 1
        )
        if not (first_round_needed or runway_low or underfunded):
            continue

        # Determine round type based on prior rounds
        next_round = {
            "founded": "series_a",
            "series_a": "series_b",
            "series_b": "series_c",
            "series_c": "late_stage_private",
            "late_stage_private": "bridge",
        }.get(firm.lifecycle_stage, "series_a")
        # If runway is critical (< 4Q), label this as a bridge regardless
        # of stage — signals to PE this is rescue financing, not growth.
        if runway_q < 4.0 and not first_round_needed:
            next_round = "bridge"

        # 1. Firm issues a pitch
        pitch = pitch_fn(firm, next_round, industry_character)
        if pitch is None:
            # Wave ν+14: more diagnostic — distinguish dispatcher miss
            # (no backend wired for this firm) from real LLM failure.
            # The dispatcher in cli.py returns None when backends.get(fid)
            # is None, which is the same as an LLM exception — hard to
            # debug without distinguishing them.
            _log(state, f"  PE: {fid} pitch unavailable (None) — "
                        f"check that a backend exists for this firm in cli.py; "
                        f"skipping round")
            continue
        ask_amount = _coerce_money(pitch.get("ask_amount"))
        pre_money_ask = _coerce_money(pitch.get("pre_money_valuation_ask"))
        if ask_amount <= 0 or pre_money_ask <= 0:
            continue
        # Wave ν+4 sanity floor: reject obviously-unit-mismatched LLM
        # outputs. A pitch with pre_money below $100K (one hundred
        # thousand dollars) is almost certainly an LLM unit error
        # (e.g., emitted "150" meaning $150M but parsed as $150). Such
        # rounds previously cleared at price-per-share fractions of a
        # cent, corrupting cap tables and lifecycle stage. Same for
        # an absurdly small ask. This is a sanity check, not a
        # behavioral rule — real Series A rounds are always well above
        # this floor.
        SANITY_USD_FLOOR = 100_000.0
        if pre_money_ask < SANITY_USD_FLOOR or ask_amount < SANITY_USD_FLOOR:
            _log(state, f"  PE: {fid} pitch rejected (sanity floor): "
                        f"pre_money=${pre_money_ask:,.0f}, ask=${ask_amount:,.0f}")
            continue

        # 2. Each PE fund evaluates INDEPENDENTLY — parallelize across funds.
        # Funds are distributed across different backends (cli.py wiring)
        # so concurrent calls don't serialize on one endpoint.
        import concurrent.futures as _cf_pe

        # Wave ν+5: when pe_unlimited_capital is ON, bypass the
        # available_capital check — PE funds can raise follow-on
        # capital from LPs for good deals. Otherwise honor the
        # legacy capital constraint.
        _pe_unlimited = bool(getattr(config, "pe_unlimited_capital", True))

        def _eval_one_fund(fund_id_eval_fn):
            _fund_id, _eval_fn = fund_id_eval_fn
            _fund = state.pe_funds.get(_fund_id)
            if _fund is None:
                return None
            if not _pe_unlimited and _fund.available_capital <= 0:
                return None
            try:
                _result = _eval_fn(firm, pitch, industry_character)
            except Exception:
                return None
            if _result is None:
                return None
            _decision = str(_result.get("decision", "PASS")).upper()
            if _decision not in ("BID", "LEAD"):
                return None
            _bid_val = _coerce_money(_result.get("bid_pre_money_valuation"))
            _bid_amt = _coerce_money(_result.get("bid_amount"))
            if _bid_val <= 0 or _bid_amt <= 0:
                return None
            # Wave ν+4 sanity floor (matches pitch-side check):
            # reject obviously-unit-mismatched LLM bids.
            if _bid_val < 100_000.0 or _bid_amt < 100_000.0:
                return None
            # Cap to available capital only when capital constraint is active
            if not _pe_unlimited:
                _bid_amt = min(_bid_amt, _fund.available_capital)
            return {
                "fund_id": _fund_id,
                "decision": _decision,
                "pre_money": _bid_val,
                "amount": _bid_amt,
                "rationale": str(_result.get("rationale", ""))[:500],
                "pe_projection": {
                    "your_revenue_projection_y5": _coerce_money(
                        _result.get("your_revenue_projection_y5")
                    ),
                    "valuation_rationale": str(
                        _result.get("your_valuation_rationale", "")
                    )[:800],
                },
                "valuation_method": str(
                    _result.get("valuation_method_primary", "")
                )[:100],
            }

        bids = []
        _fund_items = list(pe_eval_fns.items())
        _max_pe_workers = _max_workers(config, len(_fund_items))
        if _max_pe_workers > 1:
            with _cf_pe.ThreadPoolExecutor(max_workers=_max_pe_workers) as _ex:
                for _b in _ex.map(_eval_one_fund, _fund_items):
                    if _b is not None:
                        bids.append(_b)
        else:
            for _item in _fund_items:
                _b = _eval_one_fund(_item)
                if _b is not None:
                    bids.append(_b)

        if not bids:
            _log(state, f"  PE: {fid} round_type={next_round} — no bids received")
            continue

        # 3. Lead selection: prefer LEAD decisions; break ties by highest
        # pre-money + bid amount.
        # Wave λ Fix 2: existing investors (those already in pe_cap_table)
        # get pro-rata follow-on priority — real-world VCs almost always
        # exercise pro-rata in subsequent rounds.
        existing_investors = set(firm.pe_cap_table.keys())
        for b in bids:
            b["is_existing"] = b["fund_id"] in existing_investors
        leaders = [b for b in bids if b["decision"] == "LEAD"]
        if leaders:
            # Prefer existing investor as lead if any present
            existing_leaders = [b for b in leaders if b["is_existing"]]
            if existing_leaders:
                lead_bid = max(existing_leaders, key=lambda b: (b["pre_money"], b["amount"]))
            else:
                lead_bid = max(leaders, key=lambda b: (b["pre_money"], b["amount"]))
        else:
            existing_bids = [b for b in bids if b["is_existing"]]
            if existing_bids:
                lead_bid = max(existing_bids, key=lambda b: b["amount"])
            else:
                lead_bid = max(bids, key=lambda b: b["amount"])
        lead_fund_id = lead_bid["fund_id"]
        pre_money = lead_bid["pre_money"]

        # 4. Assemble syndicate: include leader + any BID/LEAD that agree
        # with the lead pre-money (within 20% tolerance)
        investors = []
        total_round = 0
        for b in bids:
            if abs(b["pre_money"] - pre_money) / pre_money <= 0.20:
                fund = state.pe_funds.get(b["fund_id"])
                # Wave ν+5: respect unlimited-capital flag here too.
                if _pe_unlimited:
                    invest_amt = b["amount"]
                else:
                    invest_amt = min(b["amount"], fund.available_capital if fund else b["amount"])
                if invest_amt <= 0:
                    continue
                investors.append((b["fund_id"], invest_amt))
                total_round += invest_amt

        if total_round <= 0:
            continue

        # Cap at firm's ask (prevent oversubscription from exploding valuation)
        if total_round > ask_amount * 1.5:
            scale = (ask_amount * 1.5) / total_round
            investors = [(fid_i, amt * scale) for fid_i, amt in investors]
            total_round = sum(amt for _, amt in investors)

        # 5. Execute the round — Wave ν: attach firm + lead projections
        # so they become part of the public record (PERound is written to
        # pe_rounds.csv and surfaced in public_info for subsequent quarters).
        firm_projections_public = pitch.get("financial_projections") or {}
        lead_proj_public = lead_bid.get("pe_projection") or {}
        lead_method = lead_bid.get("valuation_method", "")
        try:
            new_firm, event, alloc = execute_pe_round(
                firm=firm,
                round_type=next_round,
                ask_amount=ask_amount,
                pre_money_valuation=pre_money,
                investors=investors,
                lead_investor=lead_fund_id,
                pitch_narrative=str(pitch.get("pitch_narrative", ""))[:500],
                lead_rationale=lead_bid["rationale"],
                macro=state.macro,
                firm_projections=firm_projections_public,
                lead_investor_projection=lead_proj_public,
                lead_valuation_method=lead_method,
            )
        except Exception as e:
            _log(state, f"  PE: {fid} round execution failed: {e}")
            continue

        state.firms[fid] = new_firm
        state.pe_round_history.append(event)
        # Update PE fund state: reduce available, add to portfolio
        from dataclasses import replace as _dc_rep
        for fund_id, shares in alloc.items():
            fund = state.pe_funds.get(fund_id)
            if fund is None:
                continue
            dollars = next((d for f, d in investors if f == fund_id), 0)
            new_portfolio = dict(fund.portfolio)
            new_portfolio[fid] = new_portfolio.get(fid, 0) + shares
            # Wave ν+5: when unlimited capital, do NOT decrement available
            # (allows the fund to keep funding good deals indefinitely).
            new_available = (
                fund.available_capital
                if _pe_unlimited
                else fund.available_capital - dollars
            )
            state.pe_funds[fund_id] = _dc_rep(
                fund,
                available_capital=new_available,
                invested_capital=fund.invested_capital + dollars,
                portfolio=new_portfolio,
            )

        _log(state, f"  PE: {fid} {next_round} led by {lead_fund_id} @ "
                    f"${pre_money/1e6:.0f}M pre-money; raised ${total_round/1e6:.0f}M "
                    f"({len(investors)} investor(s))")
        # Log structured Action
        from .engine import ActionLog as _AL_pe
        _AL_pe.quick_record(
            state.action_log,
            actor_id=lead_fund_id,
            action_type=f"pe_round_{next_round}",
            payload={
                "target_firm": fid,
                "pre_money": pre_money,
                "post_money": pre_money + total_round,
                "amount_raised": total_round,
                "n_investors": len(investors),
            },
            quarter=state.quarter,
            justification=lead_bid["rationale"][:300],
        )


def _run_ipo_phase(
    state: "WorldState",
    ipo_decision_fn,
    prospectus_fn,
    equity_market_fn,
    config,
) -> None:
    """Wave λ Phase 1.6: IPO event.

    Private firms at series_b+ stage decide whether to go public. If
    yes, write a prospectus, public equity market prices the offering,
    transition to 'public'.
    """
    from .private_equity import execute_ipo

    industry_character = _build_industry_character_dict(state)

    for fid, firm in list(state.firms.items()):
        if not firm.is_active or firm.is_public:
            continue
        # Only late-stage privates are eligible to IPO
        if firm.lifecycle_stage not in ("series_b", "series_c", "late_stage_private"):
            continue
        # IPO decision
        dec = ipo_decision_fn(firm, industry_character)
        if dec is None:
            continue
        decision = str(dec.get("decision", "")).upper()
        if decision != "FILE_IPO":
            continue
        # Write prospectus
        if prospectus_fn is None:
            continue
        prospectus = prospectus_fn(firm, industry_character)
        if prospectus is None:
            _log(state, f"  IPO: {fid} prospectus LLM failed; skipping")
            continue
        # Price via public equity market (uses midpoint of firm's proposed range)
        ipo_price = (prospectus.price_range_low + prospectus.price_range_high) / 2.0
        if ipo_price <= 0:
            continue
        shares_offered = max(1, prospectus.shares_offered)
        try:
            new_firm = execute_ipo(firm, prospectus, ipo_price, shares_offered, state.macro)
        except Exception as e:
            _log(state, f"  IPO: {fid} execution failed: {e}")
            continue

        state.firms[fid] = new_firm
        state.ipo_prospectuses[fid] = new_firm.ipo_prospectus
        _log(state, f"  IPO: {fid} priced at ${ipo_price:.2f} × {shares_offered:,} = "
                    f"${ipo_price * shares_offered / 1e6:.0f}M raised")
        from .engine import ActionLog as _AL_ipo
        _AL_ipo.quick_record(
            state.action_log,
            actor_id=fid,
            action_type="ipo_pricing",
            payload={
                "ipo_price": ipo_price,
                "shares_offered": shares_offered,
                "amount_raised": ipo_price * shares_offered,
                "price_range_low": prospectus.price_range_low,
                "price_range_high": prospectus.price_range_high,
            },
            quarter=state.quarter,
            justification=str(dec.get("rationale", ""))[:400],
        )


def _build_industry_character_dict(state: "WorldState") -> dict:
    """Extract scenario's industry_character as a plain dict for prompts."""
    scenario = getattr(state, "_scenario", None)
    if scenario is None:
        return {}
    ic = getattr(scenario, "industry_character", None)
    if ic is None:
        return {}
    return {
        "narrative": ic.narrative,
        "label": ic.label,
        "tam_at_maturity_usd": ic.tam_at_maturity_usd,
        "years_to_maturity": ic.years_to_maturity,
    }


def _build_market_signals_dict(state: "WorldState", firm_id: str) -> dict:
    """Compute quantitative market signals for a firm's decision prompt.

    Wave ι: reports aware-population, estimated industry share vs
    outside option, estimated industry-wide willing buyers, and
    weighted-average competitor price. Populated only when reasonable
    inputs are available; otherwise returns {} (prompt omits block).
    """
    if not state.firms:
        return {}
    aware_pop = state.macro.market_size_baseline * state.macro.awareness_rate
    # Estimate inside-share using the logit outside option (quick approx,
    # not a full demand solve — that happens in env phase).
    import math as _math
    v0_base = getattr(state.params, "outside_utility_base", 3.5)
    v0_decay = getattr(state.params, "outside_utility_decay", 0.03)
    v0_floor = getattr(state.params, "outside_utility_floor", 0.5)
    v0 = max(v0_floor, v0_base - v0_decay * state.quarter)
    # Rough utility for a typical active firm at current quality
    active_firms = [f for fid, f in state.firms.items() if f.is_active]
    if not active_firms:
        return {}
    # Average quality * coef + brand*coef across active firms (rough)
    avg_capability = sum(f.capability_stock for f in active_firms) / len(active_firms)
    avg_brand = sum(f.brand_stock for f in active_firms) / len(active_firms)
    a = state.params.demand_quality_coef
    g = state.params.demand_brand_coef
    typical_utility = a * avg_capability + g * avg_brand - 0.21  # price penalty approx
    # Soft inside-share estimate using outside-logit
    numer = _math.exp(typical_utility - max(typical_utility, v0))
    denom = numer + _math.exp(v0 - max(typical_utility, v0))
    inside_share = numer / denom if denom > 0 else 0.0
    # Apply affordability filter (sigmoid). Assume average industry price
    # is 3× the typical unit cost (reasonable markup). If we have flows
    # with realized prices, use those.
    avg_price_est = 0.0
    tot_units = 0
    for fid_any, f in state.firms.items():
        flows = state.last_quarter_flows.get(fid_any)
        if flows and flows.units_sold > 0:
            avg_price_est += (flows.net_sales / flows.units_sold) * flows.units_sold
            tot_units += flows.units_sold
    if tot_units > 0:
        avg_price_est = avg_price_est / tot_units
    else:
        # Assume markup over base_unit_cost
        avg_cost = sum(f.base_unit_cost for f in active_firms) / len(active_firms)
        avg_price_est = avg_cost * 3.0
    affordability = 1.0 / (1.0 + _math.exp(
        state.params.affordability_steepness
        * (avg_price_est - state.params.affordability_center)
    ))
    industry_willing = aware_pop * inside_share * affordability
    # Weighted-average competitor price from last-quarter flows
    tot_w = 0.0
    px_sum = 0.0
    for fid, f in state.firms.items():
        if fid == firm_id or not f.is_active:
            continue
        flows = state.last_quarter_flows.get(fid)
        if flows and flows.units_sold > 0:
            px = flows.net_sales / flows.units_sold
            px_sum += px * flows.units_sold
            tot_w += flows.units_sold
    avg_competitor_price = (px_sum / tot_w) if tot_w > 0 else 0.0

    # Wave λ Fix 1: forward demand ramp — project industry-wide willing
    # buyers + addressable revenue over the next 5 years. Lets firms
    # connect "current capacity" to "expected demand at maturity" so
    # capex/financing decisions can be DCF-anchored, not extrapolated
    # from current tiny revenues.
    forward_ramp = []
    # Use the same awareness growth model as MacroState (linear ramp with
    # cap). awareness_rate IS the current; we project assuming
    # awareness grows ~10% absolute per year toward a cap of 0.95.
    # Conservative: use a modest growth that respects scenario reality.
    base_aware = state.macro.awareness_rate
    awareness_growth_per_q = 0.025   # +2.5% per quarter (toward 0.95 cap)
    base_pop = state.macro.market_size_baseline
    for q_offset in range(1, 21):    # 20Q forward
        proj_awareness = min(0.95, base_aware + awareness_growth_per_q * q_offset)
        proj_aware_pop = base_pop * proj_awareness
        # Use same affordability + inside_share logic
        proj_willing = proj_aware_pop * inside_share * affordability
        # Approximate industry revenue at avg current price
        proj_industry_revenue = proj_willing * (avg_price_est if avg_price_est > 0 else 30000)
        forward_ramp.append({
            "q_offset": q_offset,
            "aware_population": proj_aware_pop,
            "industry_willing_buyers": proj_willing,
            "industry_revenue_at_current_price": proj_industry_revenue,
        })

    return {
        "aware_population": aware_pop,
        "inside_share": inside_share,
        "industry_willing_buyers": industry_willing,
        "avg_competitor_price": avg_competitor_price,
        # Wave λ Fix 1: 5-year forward ramp
        "forward_demand_ramp_5y": forward_ramp,
        "current_avg_price_estimate": avg_price_est,
    }


def _deterministic_activist_reaction(firm_response: str) -> tuple[str, str]:
    """Fallback when activist agent doesn't implement round2() (e.g. mock
    or no activist LLM). Returns (next_action, rationale) where
    next_action ∈ {accept, escalate, drop}.
    """
    if firm_response == "accept":
        return ("accept", "firm capitulated -- campaign won")
    if firm_response == "partial":
        return ("accept", "partial concession accepted; press for more next Q")
    if firm_response == "negotiate":
        return ("escalate", "firm opened door -- remain engaged, demand concrete terms")
    return ("escalate", "firm rejected -- escalate to public campaign")


def _check_bs_invariants(state: WorldState, phase_label: str,
                           prior_bs: dict | None = None) -> dict:
    """Log any BS identity violation and attribute it to the phase.

    Called after each orchestrator phase that mutates firm state:
    - Returns the current BS snapshot so the next call can compute the
      per-phase delta (only log violations where THIS phase introduced
      drift, not ones carried over from earlier phases).
    - Emits stdout + quarter_log message for live visibility.
    - Appends a structured JSON record to `state.bs_violation_log`,
      which output_organizer writes to `outputs/{run_id}/bs_violations.jsonl`.
      Record captures firm BS breakdown for post-hoc root cause analysis.
    """
    current = {}
    for fid, firm in state.firms.items():
        # Wave ν+8: check ALL firms (including defaulted) so auction-induced
        # BS errors don't go silent. Previously this skipped defaulted firms,
        # which masked phantom equity/asset gaps when `apply_auction_result`
        # had a cash-overwrite bug. Defaulted firms are still relevant —
        # their stub state continues to live in compustat / panels and any
        # imbalance contaminates downstream analysis.
        resid = firm.total_assets - firm.total_liabilities - firm.total_equity
        current[fid] = (firm.total_assets, firm.total_liabilities,
                         firm.total_equity, resid)
        if abs(resid) > 1.0:
            prior_resid = (prior_bs or {}).get(fid, (0, 0, 0, 0))[3]
            delta_resid = resid - prior_resid
            if abs(delta_resid) > 1.0:
                msg = (f"  BS-VIOL [{phase_label}] {fid}: "
                       f"resid={resid:+,.0f} "
                       f"(delta this phase {delta_resid:+,.0f})")
                _log(state, msg)
                print(msg)
                # Structured JSON record for post-run diagnosis.
                record = {
                    "run_id": state.run_id,
                    "quarter": state.quarter,
                    "fyear": state.macro.fyear if state.macro else 0,
                    "fqtr": state.macro.fqtr if state.macro else 0,
                    "phase": phase_label,
                    "firm_id": fid,
                    "residual": round(resid, 2),
                    "delta_this_phase": round(delta_resid, 2),
                    "cash": round(firm.cash, 2),
                    "rec": round(firm.accounts_receivable, 2),
                    "allow": round(firm.allowance_for_doubtful_accounts, 2),
                    "inv": round(firm.inventory_value, 2),
                    "ppe_net": round(firm.ppe_net, 2),
                    "goodwill": round(firm.goodwill, 2),
                    "total_assets": round(firm.total_assets, 2),
                    "ap": round(firm.accounts_payable, 2),
                    "accrued": round(firm.accrued_expenses, 2),
                    "txp": round(firm.taxes_payable, 2),
                    "def_rev": round(firm.deferred_revenue, 2),
                    "revolver": round(firm.revolver_balance, 2),
                    "ltd": round(firm.long_term_debt, 2),
                    "legal_reserve": round(firm.legal_reserve_balance, 2),
                    "pension": round(firm.pension_liability, 2),
                    "dtl": round(firm.deferred_tax_liability, 2),
                    "total_liabilities": round(firm.total_liabilities, 2),
                    "common_stock": round(firm.common_stock, 2),
                    "apic": round(firm.apic, 2),
                    "retained_earnings": round(firm.retained_earnings, 2),
                    "treasury": round(firm.treasury_stock, 2),
                    "total_equity": round(firm.total_equity, 2),
                }
                # bs_violation_log is created lazily — older WorldState may lack it
                if not hasattr(state, "bs_violation_log"):
                    state.bs_violation_log = []
                state.bs_violation_log.append(record)
    return current


def _refresh_compustat_rows_for_quarter(state: WorldState,
                                          prior_states: dict) -> None:
    """Update the most-recent compustat row for each firm to reflect
    post-settlement state. Mutates row fields in place.

    Rationale: Phase 7d builds the row mid-quarter (post-financing) so that
    Phase 7.5 covenant testing has current Q data. But phases 7.7 (violation
    resolution), 14b (delisting), and 15 (settlement/bridge) can further
    mutate cash, debt, and is_active. Without this refresh, compustat_q.csv
    would show stale end-of-Q balances for any quarter with these events.

    SEC-forced restatements (Phase 14) rewrite their own row subset via
    src/restatement.py; those rows are not touched here.

    Cash-identity discipline:
      row.chechq = firm.cash - prior.cash  (exact; no approximations)
      row.fincfq = row.chechq - row.oancfq - row.ivncfq  (residual; all
        cash flow not classified as operating or investing lands in
        financing — the GAAP default).
    """
    target_fyear = state.macro.fyear
    target_fqtr = state.macro.fqtr
    seen_fids: set[str] = set()
    for row in reversed(state.compustat_rows):
        if row.fyearq != target_fyear or row.fqtr != target_fqtr:
            continue
        if row.firm_id in seen_fids:
            continue
        seen_fids.add(row.firm_id)
        firm = state.firms.get(row.firm_id)
        if firm is None:
            continue
        prior = prior_states.get(row.firm_id)
        # Refresh BS snapshot — refresh ALL balance-sheet fields used in
        # researcher-facing aggregations so they stay mutually consistent
        # (atq = sum of components, actq = current-assets sum, etc).
        # Without this, mid-quarter mutations leave atq updated but
        # rectq/invtq/ppent/actq stale, producing impossible relationships
        # like actq > atq (audit found in firm_4 Q4 2032).
        row.cheq = firm.cash
        row.rectq = firm.accounts_receivable
        row.invtq = firm.inventory_value
        row.ppentq = firm.ppe_net
        row.ppegtq = firm.ppe_gross
        row.actq = (firm.cash
                    + max(0.0, firm.accounts_receivable
                          - firm.allowance_for_doubtful_accounts)
                    + firm.inventory_value)
        row.atq = firm.total_assets
        row.apq = firm.accounts_payable
        row.xaccq = firm.accrued_expenses
        row.txpq = firm.taxes_payable
        row.dlcq = firm.revolver_balance
        row.dlttq = firm.long_term_debt
        row.lctq = firm.total_current_liabilities
        row.ltq = firm.total_liabilities
        row.legal_reserve_bs = firm.legal_reserve_balance
        row.pension_liability_bs = firm.pension_liability
        row.txditcq = firm.deferred_tax_liability
        row.cstkq = firm.common_stock
        row.apicq = firm.apic
        row.req = firm.retained_earnings
        row.tstkq = firm.treasury_stock
        row.ceqq = firm.total_equity
        row.seqq = firm.total_equity
        row.cshoq = firm.shares_outstanding / 1_000_000
        row.mkvaltq = firm.market_cap / 1_000_000  # WRDS $ millions
        row.allowance_dca = firm.allowance_for_doubtful_accounts
        row.drcq = firm.deferred_revenue
        row.gdwlq = firm.goodwill
        # is_active → default_flag
        if not firm.is_active:
            row.default_flag = 1
        # Restore cash-identity on CFS:
        if prior is not None:
            actual_delta_cash = firm.cash - prior.cash
            row.chechq = actual_delta_cash
            # Residual financing = everything not already in CFO/CFI
            row.fincfq = actual_delta_cash - row.oancfq - row.ivncfq


def _log(state: WorldState, msg: str):
    """Append to quarter log + maybe touch heartbeat.

    Wave ν+12 fix: the heartbeat was only updated at end-of-quarter, so
    on a 60-minute quarter an observer (or scheduled wakeup) could see
    nothing change for a full hour. Now every _log call also writes
    the heartbeat IF the configured min-interval has elapsed since
    the last write (default 300s = 5 min). That guarantees the
    heartbeat is fresh within ~5 minutes of any phase logging, no
    matter how long a single phase takes.
    """
    state.quarter_log.append(msg)
    _maybe_touch_heartbeat(state, msg)


def _maybe_touch_heartbeat(state: WorldState, latest_log: str = "") -> None:
    """Write the heartbeat file if min-interval has elapsed.

    Stamps the *in-progress* quarter (state.quarter + 1, since
    state.quarter is the last COMPLETED quarter) plus the latest log
    line so an observer can see which phase is active. End-of-quarter
    heartbeat in cli.py still runs and overwrites this with the
    completed-quarter view.
    """
    import os, json, time
    hb_path = getattr(state, "heartbeat_path", "")
    if not hb_path:
        return
    interval = getattr(state, "heartbeat_min_interval_s", 300.0)  # 5 min default
    now = time.time()
    last = getattr(state, "_last_heartbeat_epoch", 0.0)
    if (now - last) < interval:
        return
    try:
        os.makedirs(os.path.dirname(hb_path), exist_ok=True)
        active = sum(1 for f in state.firms.values() if f.is_active)
        payload = {
            "run_id": getattr(state, "run_id", ""),
            "wallclock_iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now)),
            "wallclock_epoch": int(now),
            "sim_quarter_completed": state.quarter,
            "sim_quarter_in_progress": state.quarter + 1,
            "fyear": state.macro.fyear,
            "fqtr": state.macro.fqtr,
            "active_firms": active,
            "latest_phase_log": latest_log[:300],
            "status": "in_progress",
        }
        with open(hb_path, "w", encoding="utf-8") as _hb:
            json.dump(payload, _hb)
        state._last_heartbeat_epoch = now
    except Exception:
        pass  # never break the run on heartbeat write failure


def _max_workers(config, n_jobs: int, default: int = 16) -> int:
    """Pick a worker count for parallel LLM-call pools.

    Reads `config.max_parallel_workers` (default 16; was 8 historically)
    and caps at `n_jobs` so we never spin up unused threads. Each worker
    holds at most one in-flight LLM call; the practical bound is the LLM
    provider's per-key concurrency limit, not local CPU.
    """
    cap = int(getattr(config, "max_parallel_workers", default)) if config is not None else default
    return max(1, min(int(n_jobs), int(cap)))


def _carry_forward_raw_decisions(
    firm: FirmState,
    prior_flows,                      # QuarterFlows | None
    decision_source: str,
    fallback_reason: str,
    proposal_id: str,
) -> RawDecisions:
    """Build a `RawDecisions` that carries forward the firm's prior-quarter
    behavior. Used when the firm-agent function fails (LLM crash, JSON parse
    failure, TypeError downstream, etc.) so the firm "stays the course"
    rather than dropping to dataclass-default zeros.

    Critical: the dataclass defaults on `RawDecisions` are ALL ZERO (price,
    production, rd, sga). If an exception path constructs `RawDecisions(
    decision_source=..., fallback_reason=..., proposal_id=...)` without
    setting the operating fields, the firm silently halts operations even
    though it has cash and capacity. That contaminates downstream env
    allocation. This helper is the canonical replacement for that pattern.
    """
    # Pull prior-quarter primitives from the QuarterFlows object if present.
    prior_net_sales = 0.0
    prior_units = 0
    prior_rd = 0.0
    prior_sga = 0.0
    if prior_flows is not None:
        prior_net_sales = float(getattr(prior_flows, "net_sales", 0.0) or 0.0)
        prior_units = int(getattr(prior_flows, "units_sold", 0) or 0)
        prior_rd = float(getattr(prior_flows, "actual_rd_spend", 0.0) or 0.0)
        if prior_rd <= 0:
            prior_rd = float(getattr(prior_flows, "rd_expense", 0.0) or 0.0)
        prior_sga = float(getattr(prior_flows, "actual_sga_spend", 0.0) or 0.0)
        if prior_sga <= 0:
            prior_sga = float(getattr(prior_flows, "sga_expense", 0.0) or 0.0)

    # Infer carried price from prior revenue / units. If none, use a
    # conservative non-zero default that wouldn't crater the firm.
    if prior_net_sales > 0 and prior_units > 0:
        carried_price = prior_net_sales / prior_units
    else:
        carried_price = 95_000.0  # conservative non-zero default
    carried_production = max(1, prior_units) if prior_units > 0 else min(
        180, max(1, firm.capacity_units)
    )
    carried_production = min(carried_production, firm.capacity_units)
    carried_rd = prior_rd if prior_rd > 0 else 12_000_000.0
    carried_sga = prior_sga if prior_sga > 0 else 5_000_000.0
    return RawDecisions(
        price=carried_price,
        production=carried_production,
        rd_spend=carried_rd,
        sga_spend=carried_sga,
        rd_allocation={"product": 0.6, "process": 0.25, "delivery": 0.15},
        decision_source=decision_source,
        fallback_reason=fallback_reason,
        proposal_id=proposal_id,
    )
