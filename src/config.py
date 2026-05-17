"""
Configuration loading and validation.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .types import SimParams


@dataclass
class LLMConfig:
    """LLM backend configuration for one agent."""
    backend: str = "mock"       # mock, openrouter, minimax, aihorde, ollama
    model: str = "deepseek/deepseek-v3.2"
    api_key_env: str = "OPENROUTER_API_KEY"
    temperature: float = 0.0
    host: str = "http://localhost:11434"   # for ollama
    max_retries: int = 2
    timeout_seconds: int = 180

    @property
    def api_key(self) -> str | None:
        return os.environ.get(self.api_key_env)


@dataclass
class RunConfig:
    """Full configuration for a simulation run."""
    # Simulation
    n_firms_initial: int = 5
    n_firms_max: int = 7
    n_quarters: int = 80
    seed: int = 42
    mode: str = "public_start"   # public_start | private_start
    run_id: str = ""

    # LLM defaults
    default_llm: LLMConfig = field(default_factory=LLMConfig)

    # Per-agent overrides (agent_id -> LLMConfig partial overrides)
    agent_llm_overrides: dict[str, dict] = field(default_factory=dict)

    # Paths
    world_docs_dir: str = "config/worlds/default"
    output_dir: str = "outputs"
    data_dir: str = "data"

    # Regimes
    information_regime: str = "baseline"
    measurement_regime: str = "baseline_gaap"

    # Complexity toggles (existing)
    entry_exit: bool = True
    financial_institutions: bool = True
    ma_enabled: bool = False
    leasing_enabled: bool = False
    stock_comp_enabled: bool = False
    workforce_detail: bool = False
    working_capital_decisions: bool = False
    provisions_enabled: bool = False

    # Expansion toggles (v0.5)
    earnings_management_enabled: bool = False
    sec_enabled: bool = False
    # Wave ν+10 item 9: 4 sell-side analysts, on by default, public to
    # form prices (visible to the equity panel).
    sellside_analysts_enabled: bool = True
    sellside_analyst_count: int = 4
    auditor_enabled: bool = False
    governance_enabled: bool = False
    earnings_announcement_enabled: bool = False
    restatements_enabled: bool = False
    macro_expansion_enabled: bool = False
    template_id: str = "longevity_drug"
    data_broker_enabled: bool = False
    data_broker_max_queries_per_agent_per_quarter: int = 3
    data_broker_mode: str = "template_only"  # template_only | combo | freeform
    delisting_price_threshold: float = 1.00   # price floor below which firm risks delisting
    delisting_quarters_threshold: int = 2     # consecutive Qs below threshold -> default
    debt_covenants_enabled: bool = False     # enables debt facility tracking + covenants
    convertible_debt_enabled: bool = False   # enables convertible debt (requires debt_covenants_enabled)
    max_active_facilities_per_firm: int = 10 # structural cap to avoid instrument explosion
    bad_debt_enabled: bool = False           # enables allowance for doubtful accounts + env write-offs
    annual_reports_enabled: bool = False     # enables 10-K-style annual report generation at fqtr=4
    env_verification_enabled: bool = False   # enables anomaly check + LLM verifier on env output
    env_validator_enabled: bool = False      # Wave ν+11 E9: second-env reviews env-1 output, sends back with notes if inconsistent
    debriefs_enabled: bool = True            # Wave ν+12: per-quarter debrief LLM calls (firm + env + intermediaries); adds N+5 LLM calls per Q
    heartbeat_min_interval_s: float = 300.0  # Wave ν+12: intra-quarter heartbeat min interval. Default 5min. Set to 3600 for hourly-only updates.
    lt_memory_enabled: bool = False          # Wave ν+12: cross-run LT memory file (data/agent_memory/<role>.md). Default OFF per user direction.
    investor_voice_enabled: bool = False     # Wave ν+12: per-firm market analyst note delivered at start of each quarter
    restructuring_enabled: bool = False      # firm can take restructuring charges (severance, impairments)
    env_decision_overrides_enabled: bool = False  # env can override firm decisions if infeasible
    # Stage 12: richer corporate finance features
    legal_reserves_enabled: bool = False     # firm can accrue + settle legal reserves
    activist_investors_enabled: bool = False # activist agent proposes campaigns to underperformers
    deferred_taxes_enabled: bool = False     # DTA/DTL from book-tax depreciation gap
    pension_enabled: bool = False            # pension accrual + contribution decision

    # Performance: parallel firm LLM calls within a quarter. Firms are
    # independent in Phase 5; threading the firm_agent_fn gives ~N×
    # speedup on IO-bound LLM calls. Off = serial (deterministic order,
    # useful for debugging).
    parallel_firm_decisions: bool = True

    # Wave delta: per-quarter WorldState snapshots to `outputs/{run_id}/
    # snapshots/Q{N}.pkl`. Enables `--restart-from` and exact replay of
    # any mid-run state. ~1 MB per quarter so small cost for recovery
    # capability.
    snapshots_enabled: bool = True

    # Wave ν+10: auto-generate the debrief bundle (dashboard.html,
    # events.csv, debrief.md) at the end of every run. The bundle is a
    # view over the run's existing outputs; turning this off skips the
    # ~5-10s post-run rendering step but the bundle can still be built
    # post hoc with `python analysis/make_debrief.py outputs/<run_id>`.
    auto_dashboard: bool = True

    # Wave ν+10: full-prompt audit logging. When > 0, every Nth quarter
    # every LLM call's full system prompt + user prompt + response is
    # appended to outputs/<run_id>/prompt_logs/Q<N>_full_log.txt with
    # timestamps, role, model, and backend. Disabled by default after
    # a one-off audit run captured representative prompts at Q20/Q40 of
    # run_1778161247 (used to author docs/prompts_audit.md). Re-enable
    # by setting to 20 (or any positive interval) in your run config.
    prompt_log_every_n_quarters: int = 0

    # Wave epsilon: noisy peer observations. When True, firms see peer
    # public data (prices, revenue, market share) with mean-zero
    # Gaussian noise (default sd = 5% of value) AND 1-quarter lag.
    # Own-firm data remains exact (agents know their own books).
    # Research use: study how information frictions affect competition.
    # Default off to preserve existing validation-run comparability.
    noisy_signals_enabled: bool = False
    noisy_signals_sd: float = 0.05

    # Wave zeta: scenario name → loads `scenarios/<name>.yaml` for per-firm
    # founding conditions (cash, IPO price, shares, PPE, capability, brand,
    # cost structure, CEO pay). None = uniform default (legacy path).
    scenario: str | None = None

    # Wave θ toggles (research richness — all can be turned off for clean baselines)
    # Director pool with interlocking seats at firm founding. Emits director
    # rows to crosswalk.csv. When `noisy_signals_enabled` is also True,
    # interlocked observer/observed pairs see each other with reduced noise
    # (SD divided by 1 + n_shared_directors). Off = no director pool, no
    # interlock info leak.
    directors_enabled: bool = True
    # Annual director-refresh events: ~1 director per firm rotates out each
    # Q4, departing directors recorded in director_turnover.csv. Off =
    # static pool at founding (current default-safe baseline).
    director_lifecycle_enabled: bool = False
    # 3-LLM board committee (CEO/CFO/comp-committee) replaces the 1-call-3-
    # perspective governance prompt. 3× API cost per governance review.
    three_llm_board_enabled: bool = False
    # LLM cost telemetry ($ estimates via OpenRouter pricing API). Default on
    # — safe, cheap, pure observability. Turn off if you want to skip the
    # pricing lookup network call at run start.
    cost_telemetry_enabled: bool = True

    # Wave κ: firms author forward 5-year strategic plans at Q0 + every 4
    # quarters. Each quarter, actuals are compared to plan → variance
    # report shown to firm decision LLM. Large consistent variance can
    # trigger early re-plan. +1 LLM call per firm per 4Q at steady state,
    # +1 extra when re-plan fires. ~$0.02/firm/year additional.
    strategic_planning_enabled: bool = False

    # Wave λ: full private→public lifecycle with K PE funds. Private
    # firms raise seed/Series A/B/C rounds from the PE pool, then decide
    # when to IPO (write prospectus → public market prices it). When OFF,
    # firms IPO at Q0 with scenario-specified founding cash (legacy path).
    # ~$0.30 extra per 8Q run at 5 firms (PE eval calls dominate cost).
    pe_lifecycle_enabled: bool = False

    # Wave ν+2: endogenous entry. When ON (default), firms appear over
    # time as the env-LLM judges new entry attractive (high TAM
    # unrealized, incumbent share gaps, generation lag). When OFF, all
    # `n_firms_initial` firms exist at Q1 (legacy behavior).
    # `n_firms_initial` then becomes the MAX firm count regardless of
    # toggle — it caps total slots used.
    endogenous_entry_enabled: bool = True
    # Initial cohort size when entry is enabled (Q1 founding count).
    # Default: 1/4 of max firms, minimum 3. Remaining slots fill via
    # endogenous entry over the run.
    endogenous_initial_cohort: int = 0  # 0 = compute from n_firms_initial

    # Wave ν+6 (toggleable): regional / horizontal-differentiation markets.
    # When ON (default), each firm is assigned an idiosyncratic
    # differentiation profile (geographic focus, patient segment,
    # distribution channel, signature feature) at spawn, and the env LLM
    # is told consumers have heterogeneous preferences over those
    # dimensions. When OFF, firms have no geographic/segment differentiation
    # and the env allocates demand on price/capability/brand alone — i.e.,
    # a single homogeneous market.
    regional_markets_enabled: bool = True

    # Wave ν+7: cap on parallel worker threads in per-firm phases. Bumped
    # from the historical 8 to 16 to accommodate larger-N runs (e.g. 16-
    # firm validations). Each worker issues at most one LLM call at a
    # time, so the practical cap is the LLM provider's concurrent-request
    # limit. Most providers handle 10-20 concurrent requests per API key
    # comfortably; the existing 429-retry logic handles transient
    # rate-limit responses, so over-provisioning here is safe.
    max_parallel_workers: int = 16

    # Wave ν+5: PE unlimited-capital mode. When ON (default), PE funds
    # bypass their `available_capital` constraint when bidding — the
    # premise being that real PE firms raise follow-on capital from LPs
    # when winning opportunities arise. Capital scarcity should NOT be
    # a reason to pass on a good deal. When OFF, the legacy capital
    # constraint applies (bids capped to fund.available_capital).
    pe_unlimited_capital: bool = True

    # Simulation parameters (feeds into SimParams)
    sim_params: SimParams = field(default_factory=SimParams)

    def get_llm_config(self, agent_id: str) -> LLMConfig:
        """Get LLM config for a specific agent, with overrides applied."""
        base = self.default_llm
        overrides = self.agent_llm_overrides.get(agent_id, {})
        if not overrides:
            return base
        return LLMConfig(
            backend=overrides.get("backend", base.backend),
            model=overrides.get("model", base.model),
            api_key_env=overrides.get("api_key_env", base.api_key_env),
            temperature=overrides.get("temperature", base.temperature),
            host=overrides.get("host", base.host),
            max_retries=overrides.get("max_retries", base.max_retries),
            timeout_seconds=overrides.get("timeout_seconds", base.timeout_seconds),
        )


@dataclass
class RoleConfig:
    """LLM assignment for a single simulation role."""
    model: str
    backend: str
    temperature: float
    note: str = ""


@dataclass
class ModelRoster:
    """All role -> model assignments, loaded from config/model_roster.yaml."""
    firms: dict[str, RoleConfig]       # firm_1 .. firm_N
    environment: RoleConfig
    equity_market: RoleConfig
    investment_bank: RoleConfig
    commercial_bank: RoleConfig
    data_analyst: RoleConfig
    api_keys: dict[str, str]           # env var names + ollama host

    # ── Expansion roles (optional, loaded when present in YAML) ──
    analysts: dict[str, RoleConfig] = field(default_factory=dict)   # analyst_1..analyst_N
    auditors: dict[str, RoleConfig] = field(default_factory=dict)   # auditor_1..auditor_4
    sec: RoleConfig | None = None
    board_governance: RoleConfig | None = None
    data_broker: RoleConfig | None = None
    env_verifier: RoleConfig | None = None  # used when env_verification_enabled
    env_validator: RoleConfig | None = None # Wave ν+11 E9: second-env validator (used when env_validator_enabled)
    debrief: RoleConfig | None = None       # Wave ν+12: per-quarter debrief writer (cheap model, shared across all agent types)
    investor_voice: RoleConfig | None = None # Wave ν+12: per-firm market-analyst commentary
    # Wave ν+10 item 7: optional second commercial / investment bank for
    # competitive bidding. When present, both banks quote and firms pick
    # the best terms.
    commercial_bank_2: RoleConfig | None = None
    investment_bank_2: RoleConfig | None = None

    def llm_config_for(self, role: str) -> LLMConfig:
        """Build an LLMConfig for the given role name."""
        rc = self.get_role(role)
        # Pick the right api_key_env based on backend
        key_map = {
            "openrouter": self.api_keys.get("openrouter_env", "OPENROUTER_API_KEY"),
            "minimax":    self.api_keys.get("minimax_env", "MINIMAX_API_KEY"),
            "aihorde":    self.api_keys.get("aihorde_env", "AIHORDE_API_KEY"),
            "ollama":     "OLLAMA_UNUSED",
            "mock":       "MOCK_UNUSED",
        }
        return LLMConfig(
            backend=rc.backend,
            model=rc.model,
            api_key_env=key_map.get(rc.backend, "OPENROUTER_API_KEY"),
            temperature=rc.temperature,
            host=self.api_keys.get("ollama_host", "http://localhost:11434"),
        )

    def get_role(self, role: str) -> RoleConfig:
        """Look up a role by name (firm_1, environment, equity_market, analyst_1, etc.).

        Raises KeyError if the role is not configured (or is configured as
        None for optional roles). Wave ν+9 Bug H4: previously returned None
        for unconfigured optional roles, producing confusing AttributeError
        deep in callers. Callers that legitimately operate on optional roles
        must check `roster.X is not None` before calling get_role.
        """
        if role.startswith("firm_"):
            if role not in self.firms:
                raise KeyError(
                    f"Firm role {role!r} not in roster. Available: "
                    f"{sorted(self.firms.keys())}"
                )
            return self.firms[role]
        if role.startswith("analyst_"):
            if role not in self.analysts:
                raise KeyError(
                    f"Analyst role {role!r} not in roster. Available: "
                    f"{sorted(self.analysts.keys())}"
                )
            return self.analysts[role]
        if role.startswith("auditor_"):
            if role not in self.auditors:
                raise KeyError(
                    f"Auditor role {role!r} not in roster. Available: "
                    f"{sorted(self.auditors.keys())}"
                )
            return self.auditors[role]
        fixed = {
            "environment": self.environment,
            "equity_market": self.equity_market,
            "investment_bank": self.investment_bank,
            "investment_bank_2": self.investment_bank_2,
            "commercial_bank": self.commercial_bank,
            "commercial_bank_2": self.commercial_bank_2,
            "data_analyst": self.data_analyst,
            "sec": self.sec,
            "board_governance": self.board_governance,
            "data_broker": self.data_broker,
            "env_verifier": self.env_verifier,
            "env_validator": self.env_validator,
            "investor_voice": self.investor_voice,
            "debrief": self.debrief,
        }
        if role not in fixed:
            raise KeyError(
                f"Unknown role {role!r}. Known fixed roles: {sorted(fixed.keys())}"
            )
        result = fixed[role]
        if result is None:
            raise KeyError(
                f"Optional role {role!r} is not configured in this roster. "
                f"Callers must guard with `if roster.{role} is not None` "
                f"before calling get_role."
            )
        return result

    def firm_ids(self) -> list[str]:
        """Return sorted list of firm IDs defined in the roster."""
        return sorted(self.firms.keys(), key=lambda k: int(k.split("_")[1]))


def _parse_role(raw: dict) -> RoleConfig:
    return RoleConfig(
        model=raw["model"],
        backend=raw["backend"],
        temperature=raw.get("temperature", 0.3),
        note=raw.get("note", ""),
    )


def load_roster(path: str | Path | None = None) -> ModelRoster:
    """Load model roster from YAML. Falls back to config/model_roster.yaml."""
    if path is None:
        path = Path("config/model_roster.yaml")
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(
            f"Model roster not found: {path}\n"
            f"Copy config/model_roster.yaml from the template and edit it."
        )
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    api_keys = raw.get("api_keys", {})
    firms = {}
    for fid, fraw in raw.get("firms", {}).items():
        firms[fid] = _parse_role(fraw)

    return ModelRoster(
        firms=firms,
        environment=_parse_role(raw.get("environment", {"model": "deepseek/deepseek-v3.2", "backend": "openrouter", "temperature": 0.4})),
        equity_market=_parse_role(raw.get("equity_market", {"model": "deepseek/deepseek-v3.2", "backend": "openrouter", "temperature": 0.2})),
        investment_bank=_parse_role(raw.get("investment_bank", {"model": "deepseek/deepseek-v3.2", "backend": "openrouter", "temperature": 0.2})),
        commercial_bank=_parse_role(raw.get("commercial_bank", {"model": "google/gemma-3-12b-it", "backend": "openrouter", "temperature": 0.2})),
        data_analyst=_parse_role(raw.get("data_analyst", {"model": "mistralai/mistral-small-24b-instruct-2501", "backend": "openrouter", "temperature": 0.1})),
        api_keys=api_keys,
        analysts={k: _parse_role(v) for k, v in raw.get("analysts", {}).items()},
        auditors={k: _parse_role(v) for k, v in raw.get("auditors", {}).items()},
        sec=_parse_role(raw["sec"]) if "sec" in raw else None,
        board_governance=_parse_role(raw["board_governance"]) if "board_governance" in raw else None,
        data_broker=_parse_role(raw["data_broker"]) if "data_broker" in raw else None,
        env_verifier=_parse_role(raw["env_verifier"]) if "env_verifier" in raw else None,
        env_validator=_parse_role(raw["env_validator"]) if "env_validator" in raw else None,
        investor_voice=_parse_role(raw["investor_voice"]) if "investor_voice" in raw else None,
        debrief=_parse_role(raw["debrief"]) if "debrief" in raw else None,
        commercial_bank_2=_parse_role(raw["commercial_bank_2"]) if "commercial_bank_2" in raw else None,
        investment_bank_2=_parse_role(raw["investment_bank_2"]) if "investment_bank_2" in raw else None,
    )


def load_config(path: str | Path | None = None) -> RunConfig:
    """Load config from YAML file. Returns defaults if no file."""
    if path is None or not Path(path).exists():
        return RunConfig()

    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    # Build LLM default
    llm_raw = raw.get("default_llm", {})
    default_llm = LLMConfig(**{k: v for k, v in llm_raw.items()
                               if k in LLMConfig.__dataclass_fields__})

    # Build run config
    config = RunConfig(
        n_firms_initial=raw.get("n_firms_initial", 5),
        n_firms_max=raw.get("n_firms_max", 7),
        n_quarters=raw.get("n_quarters", 80),
        seed=raw.get("seed", 42),
        mode=raw.get("mode", "public_start"),
        default_llm=default_llm,
        agent_llm_overrides=raw.get("agents", {}),
        world_docs_dir=raw.get("world_docs_dir", "config/worlds/default"),
        output_dir=raw.get("output_dir", "outputs"),
        data_dir=raw.get("data_dir", "data"),
        information_regime=raw.get("information_regime", "baseline"),
        measurement_regime=raw.get("measurement_regime", "baseline_gaap"),
        entry_exit=raw.get("entry_exit", True),
        financial_institutions=raw.get("financial_institutions", True),
        ma_enabled=raw.get("ma_enabled", False),
        leasing_enabled=raw.get("leasing_enabled", False),
        stock_comp_enabled=raw.get("stock_comp_enabled", False),
        workforce_detail=raw.get("workforce_detail", False),
        working_capital_decisions=raw.get("working_capital_decisions", False),
        provisions_enabled=raw.get("provisions_enabled", False),
        earnings_management_enabled=raw.get("earnings_management_enabled", False),
        sec_enabled=raw.get("sec_enabled", False),
        sellside_analysts_enabled=raw.get("sellside_analysts_enabled", True),
        sellside_analyst_count=raw.get("sellside_analyst_count", 4),
        auditor_enabled=raw.get("auditor_enabled", False),
        governance_enabled=raw.get("governance_enabled", False),
        earnings_announcement_enabled=raw.get("earnings_announcement_enabled", False),
        restatements_enabled=raw.get("restatements_enabled", False),
        macro_expansion_enabled=raw.get("macro_expansion_enabled", False),
        template_id=raw.get("template_id", "longevity_drug"),
        data_broker_enabled=raw.get("data_broker_enabled", False),
        data_broker_max_queries_per_agent_per_quarter=raw.get(
            "data_broker_max_queries_per_agent_per_quarter", 3
        ),
        data_broker_mode=raw.get("data_broker_mode", "template_only"),
        delisting_price_threshold=raw.get("delisting_price_threshold", 1.00),
        delisting_quarters_threshold=raw.get("delisting_quarters_threshold", 2),
        debt_covenants_enabled=raw.get("debt_covenants_enabled", False),
        convertible_debt_enabled=raw.get("convertible_debt_enabled", False),
        max_active_facilities_per_firm=raw.get("max_active_facilities_per_firm", 10),
        bad_debt_enabled=raw.get("bad_debt_enabled", False),
        annual_reports_enabled=raw.get("annual_reports_enabled", False),
        env_verification_enabled=raw.get("env_verification_enabled", False),
        env_validator_enabled=raw.get("env_validator_enabled", False),
        debriefs_enabled=raw.get("debriefs_enabled", True),
        heartbeat_min_interval_s=float(raw.get("heartbeat_min_interval_s", 300.0)),
        lt_memory_enabled=raw.get("lt_memory_enabled", False),
        investor_voice_enabled=raw.get("investor_voice_enabled", False),
        restructuring_enabled=raw.get("restructuring_enabled", False),
        env_decision_overrides_enabled=raw.get("env_decision_overrides_enabled", False),
        legal_reserves_enabled=raw.get("legal_reserves_enabled", False),
        activist_investors_enabled=raw.get("activist_investors_enabled", False),
        deferred_taxes_enabled=raw.get("deferred_taxes_enabled", False),
        pension_enabled=raw.get("pension_enabled", False),
        parallel_firm_decisions=raw.get("parallel_firm_decisions", True),
        snapshots_enabled=raw.get("snapshots_enabled", True),
        auto_dashboard=raw.get("auto_dashboard", True),
        prompt_log_every_n_quarters=raw.get("prompt_log_every_n_quarters", 0),
        noisy_signals_enabled=raw.get("noisy_signals_enabled", False),
        noisy_signals_sd=raw.get("noisy_signals_sd", 0.05),
        scenario=raw.get("scenario", None),
        directors_enabled=raw.get("directors_enabled", True),
        director_lifecycle_enabled=raw.get("director_lifecycle_enabled", False),
        three_llm_board_enabled=raw.get("three_llm_board_enabled", False),
        cost_telemetry_enabled=raw.get("cost_telemetry_enabled", True),
        strategic_planning_enabled=raw.get("strategic_planning_enabled", False),
        pe_lifecycle_enabled=raw.get("pe_lifecycle_enabled", False),
        endogenous_entry_enabled=raw.get("endogenous_entry_enabled", True),
        endogenous_initial_cohort=raw.get("endogenous_initial_cohort", 0),
        pe_unlimited_capital=raw.get("pe_unlimited_capital", True),
        regional_markets_enabled=raw.get("regional_markets_enabled", True),
        max_parallel_workers=raw.get("max_parallel_workers", 16),
    )
    return config
