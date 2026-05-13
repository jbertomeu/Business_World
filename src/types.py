"""
Core data types for the LLM Firm Lab simulation.

All state is immutable. Use evolve() or dataclasses.replace() to produce new
instances. This ensures the accounting module is pure-functional: given a prior
state + decisions + outcomes, it deterministically produces a new state.

Canonical reference: docs/architecture/16_worked_accounting_example.md
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Literal


# ─── Simulation Parameters ──────────────────────────────────────────────

@dataclass(frozen=True)
class SimParams:
    """Immutable simulation parameters. Loaded from config.yaml at startup."""

    # Firm count and duration
    n_firms_initial: int = 5
    n_firms_max: int = 7
    n_quarters: int = 80
    seed: int = 42

    # Tax
    tax_rate: float = 0.21
    nol_usage_limit: float = 0.80  # max fraction of pretax income offset by NOL

    # Stage 12 feature toggles (replicated from RunConfig so accounting.py can
    # gate math without config import dependencies; orchestrator copies these
    # from config → params at initialization time).
    legal_reserves_enabled: bool = False
    pension_enabled: bool = False
    deferred_taxes_enabled: bool = False

    # Wave epsilon: noisy peer observations. See config.noisy_signals_enabled.
    noisy_signals_enabled: bool = False
    noisy_signals_sd: float = 0.05

    # Working capital ratios
    theta_ar: float = 0.15   # AR = 15% of revenue
    theta_ap: float = 0.15   # AP = 15% of COGS
    theta_accr: float = 0.10 # Accrued = 10% of (R&D + SGA)

    # Depreciation
    depreciation_rate: float = 0.025  # quarterly (10% annual)

    # Mandatory costs
    mandatory_phase3_quarterly_cost: float = 10_000_000

    # Minimum SGA (unavoidable overhead: salaries, rent, legal, accounting, insurance)
    # Real firms can't run with $0 SGA. Floor = max(absolute, % of total assets).
    min_sga_absolute_floor: float = 2_000_000      # $2M/Q = ~$8M/yr (~80 employees avg)
    min_sga_pct_of_assets: float = 0.005           # 0.5%/Q = 2%/yr of assets

    # Maintenance capex (unavoidable to maintain existing PP&E working)
    # Real firms must maintain equipment. Floor = % of gross PP&E.
    maint_capex_pct_of_ppe: float = 0.005          # 0.5%/Q = 2%/yr of gross PP&E

    # Capability stock (A)
    delta_a: float = 0.025     # quarterly depreciation
    eta_a: float = 0.8         # per $1M product R&D spend

    # Brand stock (B)
    delta_b: float = 0.10      # quarterly depreciation
    eta_b: float = 1.5         # per $1M SGA spend

    # Process R&D -> COGS reduction
    process_rd_max_reduction: float = 0.22  # 22% max within a generation
    process_rd_saturation: float = 120_000_000  # denominator in exponential

    # Wave ν: Gen 2 R&D threshold — scenario-tunable so longer/shorter
    # runs can calibrate. Default $500M cumulative product R&D mirrors
    # real-world biotech analogs. Lower it for short validation runs;
    # raise it for stricter scenarios. The threshold itself is NOT
    # surfaced in agent prompts — firms learn pacing from the scenario
    # narrative + their own R&D trajectory.
    gen_2_rd_threshold: float = 500_000_000

    # Generation base COGS (per treatment course)
    gen_base_cogs: dict[int, float] = field(default_factory=lambda: {
        1: 14_000,
        2: 7_500,
        3: 2_500,
        4: 800,
    })

    # Per-firm COGS variation at creation (drawn from [-var, +var])
    gen1_cogs_variation: float = 1_000

    # Wave ν+11 fix for E4: capacity scales with gross PPE. Capex translates
    # to capacity at this rate (an additional $1 of capex over time produces
    # 1/ppe_per_unit_capacity units of additional quarterly capacity).
    # Calibrated so initial PPE $25M ↔ 250 units/Q baseline ($100K of
    # capital per unit/Q of capacity). Real-world biotech manufacturing
    # facilities are in this range. Without this link, capex was a sunk
    # accounting cost with no operational effect → industry stuck at 0.5%
    # of TAM no matter how much firms invested.
    ppe_per_unit_capacity: float = 100_000.0

    # Capacity utilization multiplier breakpoints
    # (util_threshold, base_multiplier, slope)
    util_bands: list[tuple[float, float, float]] = field(default_factory=lambda: [
        # (min_util, base_mult_at_min, slope per unit below next band)
        (0.90, 1.00, 0.0),     # >= 90%: 1.00
        (0.70, 1.00, 0.50),    # 70-90%: 1.00 + 0.50*(0.90-util)
        (0.50, 1.10, 1.00),    # 50-70%: 1.10 + 1.00*(0.70-util)
        (0.30, 1.30, 1.50),    # 30-50%: 1.30 + 1.50*(0.50-util)
        (0.00, 1.60, 2.00),    # <30%:   1.60 + 2.00*(0.30-util)
    ])

    # Quality composite weights by era
    # (max_quarter, w_eff, w_saf, w_con)
    quality_weight_schedule: list[tuple[int, float, float, float]] = field(
        default_factory=lambda: [
            (12,  0.50, 0.30, 0.20),  # years 1-3
            (28,  0.35, 0.40, 0.25),  # years 4-7
            (48,  0.25, 0.40, 0.35),  # years 8-12
            (999, 0.20, 0.35, 0.45),  # years 13+
        ]
    )

    # Generation quality indices (efficacy, safety, convenience)
    gen_quality: dict[int, tuple[float, float, float]] = field(
        default_factory=lambda: {
            1: (35.0, 27.0, 20.0),
            2: (55.0, 75.0, 50.0),
            3: (75.0, 95.0, 80.0),
            4: (90.0, 98.0, 95.0),
        }
    )

    # Serious AE rates by generation
    gen_serious_ae_rate: dict[int, float] = field(default_factory=lambda: {
        1: 0.073,
        2: 0.025,
        3: 0.005,
        4: 0.002,
    })

    # ── Demand-model coefficients (Wave ι) ─────────────────────────────
    # Previously hardcoded inside src/demand.py; now surfaced here so
    # scenarios can set industry-specific elasticities and outside-option
    # dynamics. Defaults preserve the pre-Wave-ι behavior.
    demand_price_coef: float = 0.000015       # b in utility = a*Q - b*P + g*B
    demand_quality_coef: float = 1.0           # a
    demand_brand_coef: float = 0.4             # g
    # Outside-option utility (unserved market): v0 decays from base → floor.
    # Softer decay (smaller value) keeps more demand available for longer
    # — appropriate for breakthrough industries where the outside option
    # (no treatment) stays unattractive for many years.
    outside_utility_base: float = 3.5
    outside_utility_decay: float = 0.03
    outside_utility_floor: float = 0.5
    # Affordability sigmoid: fraction of willing buyers who can actually
    # pay at a given average price. Center = price where 50% can pay.
    # For longevity / cancer / rare disease, willingness-to-pay is high,
    # so scenarios can raise the center significantly.
    affordability_center: float = 50_000
    affordability_steepness: float = 0.00003


# ─── Firm State ──────────────────────────────────────────────────────────

@dataclass(frozen=True)
class FirmState:
    """Complete state of a firm at end of a quarter. Immutable."""

    firm_id: str
    incarnation: int = 1
    quarter: int = 0           # the quarter this state represents (end-of)
    is_active: bool = True
    # Wave ν+4: dormant state for entrants that haven't raised funding
    # to execute their plan. Dormant firms preserve their seed cash,
    # don't operate (no R&D, no production, no S&G&A), and re-pitch PE
    # each quarter until they either raise or wind down. Prevents the
    # 1Q-death pattern where unfunded entrants instantly burn out.
    is_dormant: bool = False
    quarters_dormant: int = 0   # tracked so prompts can reflect dormancy duration

    # Wave ν+6: idiosyncratic differentiation profile. Every firm has a
    # distinct combination of geographic focus, patient segment, distribution
    # channel, and signature product feature. These give consumers
    # idiosyncratic reasons to use ONE firm over another — so even a
    # firm with low capability/brand has SOME captive customer base.
    # The env LLM uses this in share allocation to prevent the 100%-share
    # winner-take-all collapse seen in long runs.
    geographic_focus: str = ""
    patient_segment: str = ""
    distribution_channel: str = ""
    signature_feature: str = ""

    # ── Balance Sheet: Assets ──
    cash: float = 0.0                   # cheq
    accounts_receivable: float = 0.0    # rectq (GROSS AR; net = gross - allowance)
    allowance_for_doubtful_accounts: float = 0.0   # contra-asset, when bad_debt_enabled
    inventory_units: int = 0
    inventory_value: float = 0.0        # invtq
    ppe_gross: float = 0.0              # ppegtq
    accum_depreciation: float = 0.0
    # Derived: ppe_net = ppe_gross - accum_depreciation

    # ── Balance Sheet: Liabilities ──
    accounts_payable: float = 0.0       # apq
    accrued_expenses: float = 0.0       # xaccq (accrued expenses payable)
    taxes_payable: float = 0.0          # txpq
    deferred_revenue: float = 0.0       # drcq (customer deposits, when working_capital_decisions)
    legal_reserve_balance: float = 0.0  # Stage 12: accrued legal reserves (non-current)
    revolver_balance: float = 0.0       # dlcq
    long_term_debt: float = 0.0         # dlttq
    # Stage 12: deferred taxes — simple model driven by book/tax depreciation gap
    deferred_tax_liability: float = 0.0 # txditcq in WRDS
    # Stage 12: pension obligation — accrued unfunded liability
    pension_liability: float = 0.0      # pnccq in WRDS (simplified)

    # ── Balance Sheet: Equity ──
    common_stock: float = 0.0           # cstkq (par value)
    apic: float = 0.0                   # additional paid-in capital
    retained_earnings: float = 0.0      # req
    treasury_stock: float = 0.0         # tstkq

    # ── Shares ──
    shares_outstanding: int = 0
    # Wave ν: per-class share tracking for accurate post-IPO scoring.
    # Without these, scoring inferred founder_shares = total - pe_shares,
    # which incorrectly attributed IPO-issued shares to founders and
    # collapsed PE+public ownership to near-zero. Set at firm
    # creation (founder_shares) and on IPO (public_shares_outstanding).
    founder_shares: int = 0
    public_shares_outstanding: int = 0

    # ── Internal State (not on financial statements) ──
    capability_stock: float = 35.0      # A_it
    brand_stock: float = 10.0           # B_it
    capacity_units: int = 250           # max production per quarter
    base_unit_cost: float = 14_000.0    # COGS before utilization/process adj

    product_generation: int = 1
    delivery_generation: int = 1

    rd_cumulative_product: float = 0.0
    rd_cumulative_process: float = 0.0
    rd_cumulative_delivery: float = 0.0

    nol_carryforward: float = 0.0       # net operating loss balance

    # ── Credit Terms (set by financial agents) ──
    revolver_commitment: float = 0.0
    revolver_rate: float = 0.02         # quarterly
    term_debt_rate: float = 0.03        # quarterly
    equity_price: float = 0.0           # per share

    # ── Earnings Management (when earnings_management_enabled) ──
    cumulative_manipulation: float = 0.0    # running stock of manipulation $
    manipulation_this_quarter: float = 0.0

    # ── SEC (when sec_enabled) ──
    under_sec_investigation: bool = False
    sec_investigation_quarter: int = 0
    sec_private_contact_sent: bool = False

    # ── Auditor (when auditor_enabled) ──
    auditor_id: str = ""                    # "auditor_1".."auditor_4"
    last_audit_opinion: str = "unqualified" # unqualified|qualified|adverse
    auditor_tenure_years: int = 0
    audit_fee: float = 0.0

    # ── CEO / Governance (when governance_enabled) ──
    ceo_type: str = ""                      # hidden: aggressive_grower|conservative_steward|empire_builder|honest_operator
    ceo_tenure_quarters: int = 0
    ceo_incarnation: int = 1                # increments on every fire/retire (distinguishes successive CEOs with same type)
    ceo_age: int = 50                       # age in years; advances 1 per 4 quarters
    ceo_search_in_progress: bool = False
    ceo_base_salary: float = 2_000_000.0
    ceo_bonus_pct_of_ni: float = 0.05
    ceo_equity_shares_per_year: int = 50_000
    ceo_bonus_threshold_ni: float = 0.0
    ceo_clawback_on_restatement: bool = True

    # ── CEO grants + holdings (Stage 11) ──
    # All grants ever issued (including repaid/forfeited; historical record).
    ceo_stock_grants: tuple = ()              # tuple[StockGrant, ...]
    ceo_vested_shares_held: int = 0           # RSU shares currently owned by CEO
    ceo_shares_sold_cumulative: int = 0       # total sold to date
    ceo_cash_from_sales: float = 0.0          # CEO's personal cash (informational)
    # (ceo_cash_bonus_ytd removed Stage 11.5: redundant with annual snapshots
    # and this-quarter comp fields; never reset, so was accumulating lifetime.)
    # This-quarter comp components (populated by orchestrator before accounting;
    # zeroed after accounting consumes them). Base-salary accrues every quarter;
    # bonus + stock_comp only on governance Q (Q4).
    ceo_cash_comp_this_q: float = 0.0         # cash out this Q (salary + any bonus)
    ceo_stock_comp_this_q: float = 0.0        # SBC this Q (non-cash, grant FV)
    # Ex-ante severance obligation ("golden parachute"). Written at hire or
    # during annual review. Paid as one-time cash + SGA on involuntary
    # termination (fire). Voluntary retirement: per plan, customarily forfeited;
    # we follow that convention.
    ceo_golden_parachute_amount: float = 0.0
    # Retirement tracking
    ceo_retired: bool = False                 # latched once CEO retires
    ceo_retirement_quarter: int = 0           # when retired (0 if active)

    # ── M&A (when ma_enabled) ──
    goodwill: float = 0.0
    acquisition_integration_cost: float = 0.0
    acquired_firms: tuple[str, ...] = ()    # tuple for frozen dataclass

    # ── Delisting tracking (price collapse default) ──
    quarters_below_delisting_threshold: int = 0

    # ── Wave ν+10 item 3: Bankruptcy classification (Ch11 vs Ch7) ──
    # Empty string = not in bankruptcy proceedings.
    # "chapter_11"  = operating reorganization. Firm stays is_active=True,
    #                 LTD restructured (haircut), equity wiped, court
    #                 protection until emergence or conversion to Ch7.
    # "chapter_7"   = liquidation. Firm is_active=False; distressed
    #                 auction phase processes residual assets.
    default_type: str = ""
    quarters_in_chapter_11: int = 0

    # ── Debt facilities (when debt_covenants_enabled) ──
    # All mutations through src/debt_management.py
    debt_facilities: tuple = ()           # tuple[DebtFacility, ...]
    covenant_violation_history: tuple = ()  # tuple[CovenantViolationEvent, ...]

    # ── Earnings Guidance (when earnings_announcement_enabled) ──
    last_eps_guidance_1q: float = 0.0
    last_eps_guidance_1y: float = 0.0

    # ── Strategic Plan (Wave κ, when strategic_planning_enabled) ──
    # Forward 5-year quarterly budget authored by the firm at Q0 and
    # every 4 quarters thereafter. None = no current plan (either
    # pre-Q0 or strategic_planning disabled).
    current_plan: object = None                       # StrategicPlan | None
    # History of PlanVariance records (one per completed quarter under
    # the current plan). Capped to keep state size bounded.
    plan_variance_history: tuple = ()                 # tuple[PlanVariance, ...]
    # Count of consecutive material-variance quarters; resets on re-plan
    material_variance_streak: int = 0

    # ── Funding-ask tracking (Wave λ Fix 3) ──
    # Last quarter's equity-issuance request and what was actually
    # delivered. Used by the firm decision prompt to surface a
    # capital-constraint warning when the gap is large.
    last_funding_ask: float = 0.0
    last_funding_received: float = 0.0

    # ── Lifecycle stage (Wave λ, when pe_lifecycle_enabled) ──
    # Tracks whether the firm is still private (pre-IPO), going public,
    # or fully public. Legacy default "public" preserves backward compat
    # with all pre-Wave-λ runs.
    lifecycle_stage: str = "public"           # founded|series_a|series_b|series_c|late_stage_private|going_public|public
    is_public: bool = True                     # False while private
    # Last PE round's post-money valuation (used as private-firm "price"
    # when is_public=False; equity_price stays 0 pre-IPO).
    last_round_valuation: float = 0.0
    last_round_quarter: int = 0
    last_round_type: str = ""                  # "seed"|"series_a"|...
    # Capitalization table slice: fund_id → shares held by that PE fund.
    # Sum of values ≤ shares_outstanding; balance is founder/employee equity.
    pe_cap_table: dict = field(default_factory=dict)
    # Cumulative capital raised across all PE rounds (not counting IPO).
    cumulative_pe_capital_raised: float = 0.0
    # When the firm IPOs, the prospectus filed.
    ipo_prospectus: object = None              # ProspectusDoc | None
    ipo_quarter: int = 0                        # 0 = never IPO'd

    # ── Derived Properties ──

    @property
    def ppe_net(self) -> float:
        return self.ppe_gross - self.accum_depreciation

    @property
    def total_assets(self) -> float:
        # Net AR = gross AR minus allowance for doubtful accounts.
        # Goodwill is a real asset under GAAP; including it here keeps the
        # BS identity (A = L + E) closed after M&A transactions.
        net_ar = self.accounts_receivable - self.allowance_for_doubtful_accounts
        return (self.cash + max(0.0, net_ar) + self.inventory_value
                + self.ppe_net + self.goodwill)

    @property
    def total_current_liabilities(self) -> float:
        return (self.accounts_payable + self.accrued_expenses
                + self.taxes_payable + self.deferred_revenue
                + self.revolver_balance)

    @property
    def total_liabilities(self) -> float:
        # Long-term liabilities include long-term debt PLUS Stage 12
        # accruals: legal reserves (loss contingencies), pension benefit
        # obligation, and deferred tax liability. Each is gated by a
        # SimParams toggle in accounting.py — when off, the underlying
        # balance stays zero so this aggregation is a no-op.
        return (self.total_current_liabilities + self.long_term_debt
                + self.legal_reserve_balance
                + self.pension_liability
                + self.deferred_tax_liability)

    @property
    def total_equity(self) -> float:
        return (self.common_stock + self.apic + self.retained_earnings
                - self.treasury_stock)

    @property
    def market_cap(self) -> float:
        return self.equity_price * self.shares_outstanding

    @property
    def available_credit(self) -> float:
        return max(0.0, self.revolver_commitment - self.revolver_balance)

    def evolve(self, **kwargs) -> FirmState:
        """Create a new FirmState with specified fields changed."""
        return replace(self, **kwargs)


# ─── Decisions ───────────────────────────────────────────────────────────

@dataclass(frozen=True)
class RawDecisions:
    """What the firm agent requested (before clamping)."""
    price: float = 0.0
    production: int = 0
    capex: float = 0.0
    rd_spend: float = 0.0
    rd_allocation: dict[str, float] = field(
        default_factory=lambda: {"product": 0.6, "process": 0.25, "delivery": 0.15}
    )
    sga_spend: float = 0.0
    equity_issuance_request: float = 0.0
    debt_request: float = 0.0
    dividends: float = 0.0
    buybacks: float = 0.0
    reasoning: str = ""
    # Wave ν: required when firm deviates materially from its strategic
    # plan's this-quarter pacing. Empty means "executing plan as written".
    deviation_justification: str = ""
    manipulation_amount: float = 0.0    # + = overstate, - = understate (when EM enabled)

    # ── Working capital policies (when working_capital_decisions enabled) ──
    # None means "do not override" — accounting will use params.theta_ar/ap defaults.
    payables_days_target: float | None = None    # target DPO (days payable outstanding)
    receivables_days_target: float | None = None # target DSO (days sales outstanding)
    deposit_pct: float | None = None             # fraction of invoice collected upfront (0-1)
    ppe_disposal: float = 0.0                    # $ value of PP&E sold this quarter

    # ── Bad debt policy (when bad_debt_enabled) ──
    # None means keep prior allowance as % of new AR (carry-forward).
    allowance_pct_of_ar: float | None = None     # firm's allowance estimate as fraction of gross AR

    # ── Restructuring (when restructuring_enabled) ──
    # One-time charges the firm takes this quarter. Severance is cash out;
    # impairments reduce asset values (non-cash). All flow through IS as a
    # restructuring line below operating income (matches WRDS `rcp` line).
    restructuring_severance: float = 0.0          # cash severance paid
    restructuring_ppe_impairment: float = 0.0     # PP&E write-down
    restructuring_inventory_write_off: float = 0.0 # inventory impairment
    restructuring_goodwill_impairment: float = 0.0 # goodwill write-down

    # ── Legal reserves / litigation (Stage 12) ──
    # Firm accrues a reserve now (charge IS now, recognize liability on BS)
    # to cover expected future legal settlements. When a settlement is paid,
    # use `legal_settlements_paid` (cash out; reduces reserve balance).
    legal_reserve_change: float = 0.0      # accrue new reserve (positive) or release (negative)
    legal_settlements_paid: float = 0.0    # cash paid to settle (reduces reserve balance)

    # ── CEO stock sale (when governance_enabled) ──
    # CEO's personal decision to sell vested shares this quarter. Not a firm
    # cash-flow item; only affects `firm.ceo_vested_shares_held` and
    # `firm.ceo_cash_from_sales`. The board/firm LLM fills this on behalf
    # of the CEO when incentives + portfolio liquidity warrant it.
    ceo_sell_shares: int = 0
    # ── CEO option exercise (Stage 12) ──
    # CEO's personal decision to exercise some vested options. CEO pays
    # strike × count from their own funds (tracked via `ceo_cash_from_sales`
    # balance), receives shares (added to `ceo_vested_shares_held` AND firm's
    # `shares_outstanding` — dilutive).
    ceo_exercise_options: int = 0

    # ── Pension (Stage 12) ──
    # Firm's contribution to the pension plan this quarter. Cash out;
    # reduces `pension_liability`. Quarterly pension accrual (expense) is
    # automatic based on a fraction of compensation (see accounting).
    pension_contribution: float = 0.0

    # ── Activist response (Stage 12) ──
    # When an activist campaign is pending on this firm, the CEO must
    # respond in the next decision. Serialized as
    # {"response": "accept|reject|negotiate|partial", "rationale": "..."}
    # and written back to the matching entry in
    # `state.activist_campaigns`. None when no pending campaign.
    activist_response: dict | None = None

    # Wave alpha: decision provenance. Distinguishes real LLM reasoning
    # from deterministic / mock fallbacks so research uses of the panel
    # can filter or weight accordingly. Set by the firm_agent factory:
    #   - "llm": LLM returned a valid JSON decision
    #   - "fallback": LLM call failed; conservative default used
    #   - "mock": deterministic mock agent (cli.py mock_firm_agent)
    decision_source: str = "llm"
    # Human-readable reason when decision_source != "llm". Blank otherwise.
    fallback_reason: str = ""
    # Wave beta: stable linkage to the Action (proposal) that generated
    # these decisions. Lets `compustat_q.csv` rows be traced back to
    # `proposals.jsonl` entries for full provenance.
    proposal_id: str = ""


@dataclass(frozen=True)
class ClampedDecisions:
    """What the firm actually does (after clamping). These drive accounting."""
    price: float = 0.0
    production: int = 0
    capex: float = 0.0
    rd_spend: float = 0.0           # includes mandatory Phase III
    rd_allocation: dict[str, float] = field(
        default_factory=lambda: {"product": 0.6, "process": 0.25, "delivery": 0.15}
    )
    sga_spend: float = 0.0
    dividends: float = 0.0
    buybacks: float = 0.0
    credit_drawn: float = 0.0       # revolver draw this quarter
    clamping_log: list[str] = field(default_factory=list)
    manipulation_amount: float = 0.0    # passed through from RawDecisions (when EM enabled)

    # ── Stage 4/5 pass-through (default None → use params/prior values) ──
    payables_days_target: float | None = None
    receivables_days_target: float | None = None
    deposit_pct: float | None = None
    ppe_disposal: float = 0.0
    allowance_pct_of_ar: float | None = None
    # Stage 5: env-injected write-off amount (set by orchestrator before accounting)
    write_offs_this_quarter: float = 0.0
    # Stage 10: restructuring pass-through (when restructuring_enabled)
    restructuring_severance: float = 0.0
    restructuring_ppe_impairment: float = 0.0
    restructuring_inventory_write_off: float = 0.0
    restructuring_goodwill_impairment: float = 0.0
    # Stage 11: CEO sells vested shares this quarter (int count)
    ceo_sell_shares: int = 0
    # Stage 12: CEO exercises vested options this quarter (int count across all
    # vested options, pro-rata).
    ceo_exercise_options: int = 0
    # Stage 12: legal reserves
    legal_reserve_change: float = 0.0
    legal_settlements_paid: float = 0.0
    # Stage 12: pension contribution (cash out → reduces pension_liability)
    pension_contribution: float = 0.0

    # Wave alpha: provenance (pass-through from RawDecisions).
    decision_source: str = "llm"
    fallback_reason: str = ""
    # Wave beta: proposal_id linkage (pass-through from RawDecisions).
    proposal_id: str = ""


# ─── Market Outcomes ─────────────────────────────────────────────────────

@dataclass(frozen=True)
class MarketOutcome:
    """What happened to a firm in the product market this quarter."""
    firm_id: str
    units_sold: int = 0
    market_share: float = 0.0
    product_rd_advance: bool = False
    process_cogs_reduction_pct: float = 0.0
    delivery_rd_advance: bool = False


# ─── Quarter Flows ───────────────────────────────────────────────────────

@dataclass(frozen=True)
class QuarterFlows:
    """All flow accounts for one firm-quarter. The income statement,
    cash flow statement, and summary of what happened."""

    firm_id: str = ""
    quarter: int = 0

    # ── Income Statement ──
    net_sales: float = 0.0          # saleq
    cogs: float = 0.0               # cogsq
    gross_profit: float = 0.0       # gpq
    rd_expense: float = 0.0         # xrdq
    sga_expense: float = 0.0        # xsgaq
    depreciation: float = 0.0       # dpq
    operating_income: float = 0.0   # oiadpq
    interest_expense: float = 0.0   # xintq
    pretax_income: float = 0.0      # piq
    tax_expense: float = 0.0        # txtq
    net_income: float = 0.0         # niq

    # ── Stage 4/5: working capital + bad debt flows (0 when toggles off) ──
    ppe_disposal_proceeds: float = 0.0      # cash inflow from PP&E disposal
    ppe_disposal_gain_loss: float = 0.0     # gain(+) / loss(-) on sale
    bad_debt_expense: float = 0.0           # SGA-line charge (ΔAllowance + write-offs)
    write_offs_this_quarter: float = 0.0    # actual AR written off by env judgment

    # ── Stage 10: restructuring (0 when restructuring_enabled off) ──
    restructuring_severance: float = 0.0          # cash out (CFO reduction)
    restructuring_ppe_impairment: float = 0.0     # non-cash (BS reduction)
    restructuring_inventory_write_off: float = 0.0 # non-cash
    restructuring_goodwill_impairment: float = 0.0 # non-cash
    restructuring_charge: float = 0.0             # sum — IS line (rcpq)

    # ── Stage 12: legal / pension / deferred tax flows ──
    legal_charge: float = 0.0          # this-Q legal reserve change (+accrual / −release) on IS
    legal_settlements_paid: float = 0.0 # this-Q cash out for settlements
    pension_service_cost: float = 0.0  # this-Q expense (operating, SGA line)
    pension_contribution: float = 0.0  # this-Q cash out (CFO)
    dtl_change: float = 0.0            # this-Q Δ deferred tax liability (CFO add-back)

    # ── Cash Flow Statement ──
    cfo: float = 0.0                # oancfq
    cfi: float = 0.0                # ivncfq
    cff: float = 0.0                # fincfq
    change_in_cash: float = 0.0     # chechq

    # ── Key actuals ──
    actual_price: float = 0.0
    actual_production: int = 0
    actual_capex: float = 0.0
    actual_rd_spend: float = 0.0
    actual_sga_spend: float = 0.0
    units_sold: int = 0
    market_share: float = 0.0

    # ── Effective cost ──
    effective_unit_cost: float = 0.0
    capacity_utilization: float = 0.0

    # ── Working capital changes ──
    delta_ar: float = 0.0
    delta_inventory: float = 0.0
    delta_ap: float = 0.0
    delta_accrued: float = 0.0
    delta_taxes_payable: float = 0.0

    # ── Earnings Management ──
    reported_net_income: float = 0.0    # NI after manipulation (= net_income when EM off)
    manipulation_amount: float = 0.0    # + = overstate, - = understate
    true_net_income: float = 0.0        # NI before manipulation (= net_income always)

    # ── CEO Compensation ──
    ceo_cash_comp: float = 0.0
    ceo_equity_comp: float = 0.0

    # ── M&A ──
    acquisition_cost: float = 0.0
    goodwill_impairment: float = 0.0
    integration_expense: float = 0.0

    # ── Status ──
    default_flag: bool = False


# ─── Macro State ─────────────────────────────────────────────────────────

@dataclass(frozen=True)
class MacroState:
    """Aggregate economic conditions for a quarter."""
    quarter: int = 0
    fyear: int = 2031
    fqtr: int = 1              # 1-4
    risk_free_rate: float = 0.01  # quarterly (4% annual)
    market_size_baseline: float = 600_000_000
    awareness_rate: float = 0.15
    macro_shock: float = 0.0
    taste_shocks: dict[str, float] = field(default_factory=dict)
    regulatory_mood: str = "stable"

    # ── Expansion (when macro_expansion_enabled) ──
    political_uncertainty: float = 0.0      # 0-1 scale
    market_return_ytd: float = 0.0          # YTD broad market return
    market_risk_premium: float = 0.05       # annual equity risk premium


# ─── Slot Info (tracks firm slot across incarnations) ────────────────────

@dataclass
class SlotInfo:
    """Mutable tracker for a firm slot. Persists across incarnations."""
    slot_id: str
    current_firm_id: str = ""
    incarnation: int = 0
    consecutive_q1_defaults: int = 0
    total_defaults: int = 0
    is_frozen: bool = False
    is_paused: bool = False
    pause_quarters_remaining: int = 0
    default_history: list[dict] = field(default_factory=list)


# ─── Compustat Row ───────────────────────────────────────────────────────

@dataclass
class CompustatRow:
    """One row of the Compustat quarterly panel. Mutable for construction."""

    # Keys + WRDS-style identifiers (see src/wrds_identifiers.py)
    run_id: str = ""
    firm_id: str = ""
    incarnation: int = 0
    fyearq: int = 0
    fqtr: int = 0
    datadate: str = ""      # fiscal quarter-end date, YYYY-MM-DD
    tic: str = ""           # ticker symbol
    conm: str = ""          # company name
    sic: str = ""           # SIC industry code
    cusip: str = ""         # synthetic 9-char CUSIP (for CRSP/TRACE linking)
    # Compustat funda-compatible metadata flags (constant for this sim —
    # industrial / consolidated / domestic / standard format)
    indfmt: str = "INDL"
    consol: str = "C"
    popsrc: str = "D"
    datafmt: str = "STD"

    # Income statement
    saleq: float = 0.0
    cogsq: float = 0.0
    gpq: float = 0.0
    xrdq: float = 0.0
    xsgaq: float = 0.0
    dpq: float = 0.0
    oiadpq: float = 0.0
    xintq: float = 0.0
    rcpq: float = 0.0       # restructuring charge (WRDS convention; Stage 10)
    piq: float = 0.0
    txtq: float = 0.0
    niq: float = 0.0

    # Balance sheet - assets
    cheq: float = 0.0
    rectq: float = 0.0
    invtq: float = 0.0
    ppentq: float = 0.0   # net PP&E
    ppegtq: float = 0.0   # gross PP&E (new — researchers use with accum depr)
    actq: float = 0.0     # total current assets (cash + AR + inventory)
    atq: float = 0.0

    # Balance sheet - liabilities
    apq: float = 0.0
    xaccq: float = 0.0      # accrued expenses (WRDS convention; previously mis-labeled "acoq")
    txpq: float = 0.0
    drcq: float = 0.0       # deferred revenue (Stage 4)
    dlcq: float = 0.0
    lctq: float = 0.0
    dlttq: float = 0.0
    ltq: float = 0.0

    # Stage 4/5: contra-asset + flows
    allowance_dca: float = 0.0    # allowance for doubtful accounts (Stage 5, contra-asset against rectq)
    bad_debt_expense: float = 0.0 # Stage 5 non-cash charge this quarter
    write_offs: float = 0.0       # Stage 5 write-offs this quarter
    ppe_disposal_proceeds: float = 0.0  # Stage 4 PP&E disposal cash in
    ppe_disposal_gain_loss: float = 0.0 # Stage 4 gain/loss on sale

    # Stage 12: new IS / BS lines
    spioq: float = 0.0            # special items (legal reserve change + restructuring combined WRDS-style)
    legal_reserve_bs: float = 0.0 # BS balance (custom; WRDS doesn't have one standard field)
    pension_liability_bs: float = 0.0  # pnccq (pension liability)
    pension_service_cost: float = 0.0  # quarterly pension service cost
    pension_contribution: float = 0.0  # quarterly cash contribution
    txditcq: float = 0.0          # deferred tax liability (WRDS convention)

    # Balance sheet - equity
    cstkq: float = 0.0
    apicq: float = 0.0
    ceqq: float = 0.0      # common equity (common_stock + apic + RE − treasury)
    seqq: float = 0.0      # total stockholders' equity (incl. pref; same as ceqq here)
    req: float = 0.0
    tstkq: float = 0.0

    # Cash flow
    oancfq: float = 0.0
    ivncfq: float = 0.0
    fincfq: float = 0.0
    chechq: float = 0.0
    capxq: float = 0.0

    # Equity issuance / payouts
    sstkq: float = 0.0     # stock issuance
    prstkq: float = 0.0    # stock repurchase
    dvq: float = 0.0       # dividends

    # Market
    prccq: float = 0.0     # equity price
    cshoq: float = 0.0     # shares outstanding (millions for Compustat compat)
    mkvaltq: float = 0.0   # market cap in $ MILLIONS (WRDS convention)

    # Custom
    default_flag: int = 0
    empq: int = 0           # employees (placeholder)
    # Wave alpha: provenance of this firm-quarter's decisions.
    # Research use: filter decision_source == 'llm' for behavioral analysis.
    decision_source: str = "llm"
    fallback_reason: str = ""
    # Wave beta: FK into proposals.jsonl (one proposal per firm-quarter
    # for now; future migrations will decompose into multiple fine-grained
    # actions per firm).
    proposal_id: str = ""

    # ── Earnings Management (hidden truth, not in public Compustat) ──
    manipulation_amount: float = 0.0

    # ── Restatement columns (None = no restatement for this row) ──
    saleq_restated: float | None = None
    cogsq_restated: float | None = None
    niq_restated: float | None = None
    cheq_restated: float | None = None
    atq_restated: float | None = None
    ltq_restated: float | None = None
    ceqq_restated: float | None = None
    req_restated: float | None = None
    oancfq_restated: float | None = None
    restatement_flag: int = 0
    restatement_quarter: int = 0

    # ── Audit (populated for Q4 rows when auditor_enabled) ──
    audit_opinion: str = ""
    auditor_id: str = ""

    # ── M&A ──
    gdwlq: float = 0.0                     # goodwill

    def as_dict(self) -> dict:
        """Convert to dict for CSV writing."""
        return {k: v for k, v in self.__dict__.items()}


# ─── New Expansion Dataclasses ──────────────────────────────────────────

@dataclass(frozen=True)
class SECInvestigationState:
    """Per-firm SEC investigation tracker."""
    firm_id: str = ""
    status: str = "none"            # none|watching|investigating|private_contact|aaer_pending|resolved
    started_quarter: int = 0
    private_contact_quarter: int = 0
    flags: tuple[str, ...] = ()     # tuple for frozen
    severity: float = 0.0           # 0-1


@dataclass(frozen=True)
class AnalystNote:
    """One sell-side analyst's published brokerage note (full research note)."""
    analyst_id: str = ""
    quarter: int = 0
    firm_id: str = ""
    eps_forecast_1q: float = 0.0
    eps_forecast_1y: float = 0.0
    target_price: float = 0.0
    rating: str = "hold"            # buy|hold|sell
    methodology: str = ""           # fundamental_fsa_dcf|comparables|residual_income
    narrative: str = ""
    # Financial statement analysis snapshot (optional fields; analysts may
    # populate what their methodology uses)
    roe: float | None = None
    npm: float | None = None
    asset_turnover: float | None = None
    leverage: float | None = None
    rnoa: float | None = None
    nbc: float | None = None
    nfl: float | None = None
    quality_of_earnings: str = ""
    forecast_drivers: str = ""
    valuation_method_detail: str = ""
    risks: str = ""


@dataclass(frozen=True)
class AuditResult:
    """Result of an annual audit for one firm."""
    firm_id: str = ""
    auditor_id: str = ""
    fiscal_year: int = 0
    opinion: str = "unqualified"    # unqualified|qualified|adverse
    findings: str = ""
    fee: float = 0.0
    detected_manipulation: bool = False
    recommended_restatement: bool = False
    going_concern: bool = False


@dataclass(frozen=True)
class PlanLine:
    """One quarter's planned financials within a StrategicPlan.

    All values are the firm's OWN forecast at planning time — they are
    NOT ground truth. Variance reports compare realized actuals against
    these forecasts to surface plan deviations each quarter.
    """
    fyear: int = 0                      # fiscal year this line projects
    fqtr: int = 0                       # fiscal quarter (1-4)
    # Top-line + capacity
    planned_revenue: float = 0.0
    planned_units_sold: int = 0
    planned_price: float = 0.0
    planned_capacity: int = 0
    # Cost structure
    planned_cogs: float = 0.0
    planned_rd_spend: float = 0.0
    planned_sga_spend: float = 0.0
    planned_capex: float = 0.0
    # Financing
    planned_equity_raise: float = 0.0    # $ raised this quarter (cumulative by sum)
    planned_debt_raise: float = 0.0
    planned_dividends: float = 0.0
    # Derived projections (firm's estimate)
    projected_ni: float = 0.0
    projected_eps: float = 0.0
    projected_cash_balance_eoq: float = 0.0
    # Milestones
    planned_generation: int = 1          # what gen the firm expects to be at
    planned_rd_cumulative_product: float = 0.0


@dataclass(frozen=True)
class StrategicPlan:
    """Forward 5-year (default) quarterly plan authored by the firm's
    CFO/board. Issued at Q0 and re-issued every 4 quarters (or on
    extraordinary events like a large variance triggering re-plan).

    Wave κ: makes forward budgeting an explicit, auditable artifact.
    Firms see 'actual vs plan' variance each quarter in their decision
    info package and are prompted to react when variance is large.
    """
    firm_id: str = ""
    plan_id: str = ""                    # UUID generated at plan issuance
    plan_quarter: int = 0                # simulation quarter when this plan was authored
    plan_fyear: int = 0
    plan_fqtr: int = 0
    horizon_quarters: int = 20           # default 5-year forward plan
    # The forward quarters this plan covers (length = horizon_quarters)
    lines: tuple = ()                    # tuple[PlanLine, ...]
    # High-level strategic narrative (LLM-authored prose summarizing the plan)
    strategy_narrative: str = ""
    # Top-3 key assumptions the plan depends on (LLM-authored)
    key_assumptions: tuple = ()          # tuple[str, ...]
    # Top-3 risks the firm identified (LLM-authored)
    key_risks: tuple = ()                 # tuple[str, ...]
    # Milestone targets (e.g. "Reach G2 by Q24", "Positive FCF by Q18")
    milestones: tuple = ()                # tuple[str, ...]
    # Wave λ Fix D: contingency plan if next financing fails / is delayed
    contingency_plan: str = ""
    # Supersedes — if this plan replaces an earlier one (e.g. after large
    # variance triggered a re-plan), the prior plan_id is recorded here
    supersedes_plan_id: str = ""


@dataclass(frozen=True)
class PlanVariance:
    """Computed variance between a firm's actual results and its
    strategic plan for a given quarter.

    Wave κ: surfaced in the firm's decision info package. Large
    negative variance for 2+ consecutive quarters triggers a re-plan
    prompt.
    """
    firm_id: str = ""
    plan_id: str = ""
    fyear: int = 0
    fqtr: int = 0
    # Absolute differences (actual - planned); negative = below plan
    revenue_variance: float = 0.0
    ni_variance: float = 0.0
    cash_variance: float = 0.0
    units_variance: int = 0
    # Percent variance (revenue-weighted); float('inf') if plan was 0
    revenue_variance_pct: float = 0.0
    ni_variance_pct: float = 0.0
    # Flag: material deviation that should prompt LLM attention
    is_material: bool = False
    material_reason: str = ""            # "revenue -30% vs plan", "cash projection missed by $50M", etc.


@dataclass(frozen=True)
class PEFund:
    """Wave λ: a private-equity / venture-capital fund that invests in
    firms at seed / Series A / B / C / PIPE rounds.

    Kept simple by design: each fund has a narrative strategy, an
    investment horizon, a target hurdle rate, available capital, and a
    portfolio (firm_id → shares). Behavioral complexity lives in the
    fund's LLM prompt, not in fields.
    """
    fund_id: str = ""                          # "pe_1"…"pe_K"
    name: str = ""                              # e.g. "Patient Capital Partners"
    strategy: str = "generalist"                # "seed" | "early_stage_biotech" | "growth" | "late_stage" | "generalist"
    target_hurdle_rate: float = 0.25            # target IRR (annualized)
    horizon_years: float = 8.0                  # typical fund life
    initial_capital: float = 500_000_000.0      # $ raised at fund inception
    available_capital: float = 500_000_000.0    # $ remaining to deploy
    invested_capital: float = 0.0               # $ deployed to portfolio firms
    realized_proceeds: float = 0.0              # $ recovered via exits
    portfolio: dict = field(default_factory=dict)  # firm_id → shares_held
    sector_thesis: str = ""                     # free-text investment thesis
    founding_quarter: int = 0


@dataclass(frozen=True)
class PERound:
    """One PE funding round event. Immutable record appended to
    state.pe_round_history.
    """
    firm_id: str = ""
    round_type: str = "series_a"                # seed|series_a|series_b|series_c|pipe
    round_quarter: int = 0
    round_fyear: int = 0
    round_fqtr: int = 0
    pre_money_valuation: float = 0.0
    post_money_valuation: float = 0.0
    amount_raised: float = 0.0
    shares_issued: int = 0
    price_per_share: float = 0.0
    # Tuple of (fund_id, shares_bought, dollars_invested)
    investors: tuple = ()
    lead_investor: str = ""
    # LLM-authored rationale (firm's pitch summary + PE's reason for investing)
    firm_pitch_summary: str = ""
    lead_investor_rationale: str = ""
    # Wave ν: firm's financial projections shared in the pitch.
    # Once the round closes, these become PUBLIC — visible to competitor
    # firms, analysts, and other PE funds. This is how the market learns
    # what each firm is promising its investors.
    firm_projections: dict = field(default_factory=dict)
    # Wave ν: lead investor's own counter-projection + valuation method,
    # also public once the round closes. Lets the market see the PE-side
    # view alongside the firm-side view.
    lead_investor_projection: dict = field(default_factory=dict)
    lead_valuation_method: str = ""


@dataclass(frozen=True)
class ProspectusDoc:
    """Full IPO prospectus written by the firm's LLM when going public.
    Rendered to markdown under outputs/<run>/prospectus/.
    """
    firm_id: str = ""
    filing_quarter: int = 0
    filing_fyear: int = 0
    filing_fqtr: int = 0
    price_range_low: float = 0.0
    price_range_high: float = 0.0
    shares_offered: int = 0
    # Full narrative text sections
    business_overview: str = ""
    risk_factors: str = ""
    mdna: str = ""                              # management discussion & analysis
    financial_projections: str = ""              # forward 5-year summary
    use_of_proceeds: str = ""
    # Final pricing (set by public equity market)
    final_ipo_price: float = 0.0
    final_amount_raised: float = 0.0


@dataclass(frozen=True)
class MABid:
    """M&A bid from one firm to another."""
    bidder_id: str = ""
    target_id: str = ""
    offer_price_per_share: float = 0.0
    offer_type: str = "friendly"    # friendly|hostile
    cash_component: float = 0.0
    stock_component: float = 0.0
    quarter: int = 0


@dataclass(frozen=True)
class Covenant:
    """One financial covenant on a debt facility.

    covenant_type is drawn from a fixed template set (code computes ratios).
    threshold and other terms are judged by the bank at origination.
    """
    covenant_type: str = ""              # "max_debt_to_ebitda" | "min_interest_coverage" |
                                          # "min_cash_balance" | "min_liquidity" | "min_net_worth"
    threshold: float = 0.0
    test_frequency: str = "quarterly"    # quarterly | annual
    initial_ratio: float = 0.0           # value at origination
    currently_violated: bool = False
    quarters_in_violation: int = 0


@dataclass(frozen=True)
class DebtFacility:
    """A single debt instrument outstanding on a firm's balance sheet.

    All balance mutations happen through src/debt_management.py — never here,
    never directly from LLM output. Immutable: mutations produce new instances.
    """
    facility_id: str = ""                # e.g. "firm_0-FAC-001"
    firm_id: str = ""
    facility_type: str = ""              # "bank_term" | "bank_revolver" | "bond" | "convertible_bond"
    lender_name: str = ""
    origination_quarter: int = 0
    origination_date: str = ""
    maturity_quarter: int = 0
    maturity_date: str = ""
    original_principal: float = 0.0
    current_balance: float = 0.0
    coupon_rate_quarterly: float = 0.0
    amortization_type: str = "bullet"    # bullet | amortizing | revolver
    status: str = "current"              # current | in_cure_period | amended | accelerated | repaid | defaulted | converted
    covenants: tuple[Covenant, ...] = ()
    # Convertible-specific (0.0 when not applicable)
    conversion_price: float = 0.0        # $ per share
    conversion_ratio: float = 0.0        # shares per $1000 face
    is_converted: bool = False


@dataclass(frozen=True)
class CovenantViolationEvent:
    """Record of a covenant violation and its resolution."""
    firm_id: str = ""
    facility_id: str = ""
    covenant_type: str = ""
    violation_quarter: int = 0
    violation_date: str = ""
    measured_ratio: float = 0.0
    threshold: float = 0.0
    cure_period_quarters: int = 1
    resolution: str = "pending"          # pending | waived | amended | accelerated | converted_to_equity
    amended_threshold: float = 0.0       # if amended
    waiver_fee: float = 0.0              # if waived
    new_rate_quarterly: float = 0.0      # if amended with rate change
    resolution_quarter: int = 0
    resolution_narrative: str = ""


@dataclass(frozen=True)
class StockGrant:
    """A CEO compensation grant (RSU or stock option). Time-based vesting only.

    Mirrors ExecuComp `grants of plan-based awards` schema at a simplified
    level — no performance conditions, no acceleration triggers beyond
    retirement (which the orchestrator handles separately via
    `ceo_comp.accelerate_vesting_on_retirement`).
    """
    grant_id: str = ""
    ceo_id: str = ""                 # who owns the grant (CEO type at grant time)
    ceo_incarnation: int = 1         # firm.ceo_incarnation when granted (disambiguates successive CEOs with same type)
    firm_id: str = ""
    grant_quarter: int = 0           # absolute quarter of issuance
    grant_type: str = "rsu"          # "rsu" or "stock_option"
    shares: int = 0
    strike_price: float = 0.0        # 0 for RSU; positive for options
    # Vesting schedule = tuple of (quarter_offset_from_grant, fraction_vesting).
    # Sum of fractions should ≈ 1.0. Example 4-year annual cliff at origination:
    # ((4, 0.25), (8, 0.25), (12, 0.25), (16, 0.25)).
    vesting_schedule: tuple = ()     # tuple[(int, float), ...]
    fair_value_at_grant: float = 0.0 # for comp accounting / ExecuComp total_comp
    shares_vested_to_date: int = 0   # cumulative shares that have vested
    shares_forfeited: int = 0        # cumulative forfeited (on fire)
    shares_exercised: int = 0        # options only — cumulative exercised


@dataclass(frozen=True)
class EarningsRelease:
    """Public earnings announcement by a firm."""
    firm_id: str = ""
    quarter: int = 0
    reported_eps: float = 0.0
    reported_revenue: float = 0.0
    guidance_eps_1q: float = 0.0
    guidance_eps_1y: float = 0.0
    guidance_revenue_1q: float = 0.0
    management_discussion: str = ""
    qa_transcript: str = ""


@dataclass(frozen=True)
class InsiderTradingEvent:
    """Insider (CEO) transaction event — mirrors WRDS Thomson Reuters Insider
    Filings / SEC Form 4 granularity. One row per event: grant, sell, option
    exercise, share delivery from vesting. Produces `insider_transactions.csv`.
    """
    run_id: str = ""
    firm_id: str = ""
    ceo_id: str = ""
    ceo_incarnation: int = 1
    event_quarter: int = 0
    event_date: str = ""                # ISO date (quarter-end approximation)
    event_type: str = ""                # grant | sell | exercise
    transaction_shares: int = 0
    transaction_price: float = 0.0      # market price at event
    strike_price: float = 0.0           # for exercise events, $ paid per share
    transaction_value: float = 0.0      # shares × price (or gross proceeds)
    shares_held_after: int = 0          # CEO's retained vested-held shares
    notes: str = ""


@dataclass(frozen=True)
class AnnualReport:
    """Annual (10-K-style) report produced at fqtr=4. Combines a deterministic
    full-year financial summary with an LLM-authored MD&A and forward-looking
    statements, plus pointers to that year's audit opinion and covenant events.
    """
    firm_id: str = ""
    fyear: int = 0
    quarter: int = 0          # absolute quarter index of fyear-Q4

    # ── Annual income statement (sum of 4 quarters) ──
    annual_revenue: float = 0.0
    annual_cogs: float = 0.0
    annual_gross_profit: float = 0.0
    annual_rd: float = 0.0
    annual_sga: float = 0.0
    annual_depreciation: float = 0.0
    annual_operating_income: float = 0.0
    annual_interest_expense: float = 0.0
    annual_pretax_income: float = 0.0
    annual_tax: float = 0.0
    annual_net_income: float = 0.0      # reported (post-manipulation)
    annual_true_net_income: float = 0.0 # pre-manipulation
    annual_eps: float = 0.0

    # ── Annual cash flow ──
    annual_cfo: float = 0.0
    annual_cfi: float = 0.0
    annual_cff: float = 0.0
    annual_capex: float = 0.0

    # ── Year-end balance sheet snapshot ──
    year_end_cash: float = 0.0
    year_end_total_assets: float = 0.0
    year_end_total_liabilities: float = 0.0
    year_end_total_equity: float = 0.0
    year_end_long_term_debt: float = 0.0
    year_end_revolver_balance: float = 0.0
    year_end_shares_outstanding: int = 0
    year_end_share_price: float = 0.0

    # ── Year-over-year (vs prior fiscal year) ──
    yoy_revenue_growth: float = 0.0
    yoy_ni_growth: float = 0.0

    # ── Capital activity during the year ──
    equity_issued_during_year: float = 0.0
    debt_issued_during_year: float = 0.0
    dividends_paid: float = 0.0
    buybacks: float = 0.0

    # ── Audit + covenant signals ──
    audit_opinion: str = ""             # from Phase A1 (if auditor enabled)
    going_concern_flag: bool = False
    covenant_violations_count: int = 0  # within fyear

    # ── LLM-authored content ──
    mda_summary: str = ""               # 2-3 paragraphs
    forward_guidance_revenue: float = 0.0
    forward_guidance_eps: float = 0.0
    key_strategic_initiatives: str = "" # short bullets
    risk_factors: str = ""              # short bullets
