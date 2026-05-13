"""
Run-end scoring: measure financial performance for all participants.

For FIRMS: NPV of equity cash flows (outflows at IPO, inflows from dividends/buybacks,
  terminal value at run end, all discounted at the risk-free rate).

For EQUITY MARKET (built-in pricing): pricing error (price vs realized return).

For DEBT (lenders): NPV of lending activity (loans out, interest + principal back, discounted).

For ENVIRONMENT: each firm votes on realism (1-10) across dimensions.
  These votes accumulate in the cross-run database.

All scores are appended to data/scores.csv for cross-run analysis.
"""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass, field
from pathlib import Path

from .types import FirmState, CompustatRow, SimParams


@dataclass
class FirmScore:
    """Valuation-anchored score for one firm (Wave λ refactor).

    Returns for each class of investor (founders, PE funds, public
    shareholders) are computed by comparing their retained stake's
    CURRENT VALUE against the cash they contributed. Current value uses
    market cap for public firms, last PE-round post-money valuation
    for private firms.

    This replaces the pre-Wave-λ anchoring on a hardcoded $175M IPO
    baseline — which was wrong for firms that raised via PE rounds, and
    wrong even for firms that raised secondary equity.
    """
    firm_id: str
    incarnation: int
    lifespan_quarters: int
    # ── Valuation anchor (current point-in-time value) ──
    is_public: bool = False
    lifecycle_stage: str = "public"
    current_valuation: float = 0.0        # market cap (public) | last round post-money (private)
    # ── Capital-in vs current value, by investor class ──
    # Founders: original seed / pre-PE contribution
    founder_capital_in: float = 0.0       # aggregate $ contributed by founders
    founder_shares_held: int = 0
    founder_ownership_pct: float = 0.0    # founder shares / total shares
    founder_stake_value: float = 0.0      # ownership_pct × current_valuation
    founder_npv: float = 0.0              # stake_value + distributions_to_founders - seed

    # PE funds: aggregate across all rounds
    pe_total_invested: float = 0.0        # sum of round amounts
    pe_total_shares_held: int = 0
    pe_ownership_pct: float = 0.0
    pe_total_stake_value: float = 0.0     # ownership_pct × current_valuation
    pe_multiple: float = 0.0              # stake_value / invested (MOIC)
    pe_npv: float = 0.0                   # stake_value - invested (unrealized)

    # Public-market shareholders (IPO + secondary offerings). Tracked as a
    # single pool (treasury of non-founder, non-PE shares).
    public_capital_in: float = 0.0
    public_shares_held: int = 0
    public_ownership_pct: float = 0.0
    public_stake_value: float = 0.0
    public_npv: float = 0.0

    # Firm-level distributions (to all shareholders pro-rata)
    total_dividends: float = 0.0
    total_buybacks: float = 0.0
    # Legacy diagnostics (kept for backward compatibility)
    ipo_invested: float = 0.0
    total_capital_raised: float = 0.0
    terminal_market_cap: float = 0.0
    # Aggregate NPV across all stakeholder classes (founders + PE + public)
    equity_npv: float = 0.0
    equity_irr_approx: float = 0.0
    defaulted: bool = False
    default_quarter: int | None = None


@dataclass
class DebtScore:
    """Score for the lending system across all firms."""
    total_loaned: float
    total_interest_received: float
    total_principal_recovered: float
    total_losses: float
    debt_npv: float
    loss_rate: float


@dataclass
class PricingScore:
    """Equity pricing accuracy."""
    mean_error: float       # average (P_t - P*_t) where P* = realized next-Q return
    rmse: float
    mean_abs_pct_error: float
    n_observations: int


@dataclass
class EnvironmentVote:
    """One firm's vote on environment realism."""
    voter_id: str
    market_realism: int      # 1-10
    event_realism: int       # 1-10
    narrative_quality: int   # 1-10
    consistency: int         # 1-10
    fairness: int            # 1-10
    overall: int             # 1-10
    comments: str = ""


@dataclass
class RunScorecard:
    """Complete scorecard for one run."""
    run_id: str
    firm_scores: list[FirmScore] = field(default_factory=list)
    debt_score: DebtScore | None = None
    pricing_score: PricingScore | None = None
    environment_votes: list[EnvironmentVote] = field(default_factory=list)


IPO_SHARES = 10_000_000  # canonical IPO share lot (see orchestrator Phase 2)
IPO_RAISE = 175_000_000  # canonical IPO raise (see orchestrator Phase 2)


def compute_firm_scores(
    compustat_rows: list[CompustatRow],
    firms: dict[str, FirmState],
    params: SimParams,
    risk_free_rate: float,
    pe_round_history: list | None = None,
) -> list[FirmScore]:
    """Wave λ: valuation-anchored NPV by stakeholder class.

    Each firm's current valuation is the anchor:
      - public firms: market cap (equity_price × shares_outstanding)
      - private firms: last PE round's post-money valuation
      - defaulted firms: 0

    For each investor class (founders / PE funds / public shareholders),
    we compute:
      - Ownership %: stake shares / total shares outstanding
      - Stake value: ownership % × current valuation
      - NPV: stake value + received distributions - capital contributed

    This replaces the pre-Wave-λ scoring which hardcoded every IPO at
    $175M and 10M shares regardless of what actually happened.
    """
    scores = []

    from collections import defaultdict
    by_firm = defaultdict(list)
    for row in compustat_rows:
        by_firm[row.firm_id].append(row)

    # Build fid ->list[PERound] lookup for per-firm PE history
    pe_by_firm: dict[str, list] = defaultdict(list)
    for event in (pe_round_history or []):
        pe_by_firm[event.firm_id].append(event)

    for fid, rows in by_firm.items():
        if not rows:
            continue

        firm = firms.get(fid)
        n_quarters = len(rows)
        total_div = sum(float(r.dvq) for r in rows)
        total_buyback = sum(float(r.prstkq) for r in rows)
        r_q = risk_free_rate

        is_public = bool(firm and firm.is_public)
        lifecycle_stage = firm.lifecycle_stage if firm else "public"
        defaulted = firm is None or not firm.is_active
        default_q = None
        for r in rows:
            if int(r.default_flag) == 1:
                default_q = int(r.fqtr)
                break

        # ── Current valuation (the anchor) ──
        if defaulted or firm is None:
            current_valuation = 0.0
        elif is_public:
            current_valuation = firm.equity_price * firm.shares_outstanding
        else:
            current_valuation = firm.last_round_valuation

        total_shares = firm.shares_outstanding if firm else 0
        price_per_share_now = (current_valuation / total_shares) if total_shares > 0 else 0.0

        # ── PE stakeholder (Wave λ): aggregate across all rounds ──
        pe_events = pe_by_firm.get(fid, [])
        pe_total_invested = sum(ev.amount_raised for ev in pe_events)
        pe_total_shares = (
            sum((firm.pe_cap_table or {}).values()) if firm else 0
        )
        pe_ownership_pct = (pe_total_shares / total_shares) if total_shares > 0 else 0.0
        pe_total_stake_value = pe_ownership_pct * current_valuation
        pe_multiple = (pe_total_stake_value / pe_total_invested) if pe_total_invested > 0 else 0.0
        pe_npv = pe_total_stake_value - pe_total_invested

        # ── Founder stakeholder ──
        # Three cases:
        #  1. PE-lifecycle firm (stage != "public" at some point): founders
        #     contributed seed capital (first compustat row's apicq); founder
        #     shares = total - sum(pe_cap_table).
        #  2. PE-lifecycle firm, now public: same founder_capital_in but
        #     founder_shares are tracked via the (shares_at_IPO - PE shares)
        #     distinction (approximation via first-row apicq).
        #  3. Legacy public firm: IPO at $175M for 10M shares at Q0.
        in_pe_lifecycle = bool(pe_events) or (firm and firm.lifecycle_stage != "public") or (firm and not firm.is_public)
        # Wave ν: read founder_shares from FirmState (tracked at firm
        # creation + preserved through PE rounds + IPO). Previously
        # inferred as `total - pe_shares`, which incorrectly attributed
        # IPO-issued shares to founders and produced 95% founder + ~0%
        # public splits post-IPO.
        if firm and getattr(firm, "founder_shares", 0) > 0:
            founder_shares = firm.founder_shares
        elif in_pe_lifecycle:
            founder_shares = max(0, total_shares - pe_total_shares)
        else:
            founder_shares = total_shares

        if in_pe_lifecycle:
            founder_capital_in = float(rows[0].apicq) if rows else 0.0
        else:
            founder_capital_in = IPO_RAISE

        founder_ownership_pct = (
            (founder_shares / total_shares) if total_shares > 0 else 0.0
        )
        founder_stake_value = founder_ownership_pct * current_valuation

        # Founder distributions received (pro-rata with their ownership)
        founder_distributions = 0.0
        for q in range(n_quarters):
            shares_q = float(rows[q].cshoq) * 1_000_000
            if shares_q > 0:
                own_q = founder_shares / shares_q
                own_q = min(1.0, max(0.0, own_q))
                div_q = float(rows[q].dvq) * own_q
                founder_distributions += div_q / (1 + r_q) ** (q + 1)
        founder_npv = (
            founder_stake_value / ((1 + r_q) ** n_quarters)
            + founder_distributions
            - founder_capital_in
        )

        # ── Public shareholder ──
        # = shares not held by founders and not held by PE = secondary-IPO
        # or post-IPO public float. In legacy (no PE), all shares are
        # founder/IPO; public_shares = 0.
        # Wave ν: read public_shares_outstanding from FirmState too.
        if firm and getattr(firm, "public_shares_outstanding", 0) > 0:
            public_shares = firm.public_shares_outstanding
        elif not pe_events and not is_public:
            public_shares = 0
        else:
            public_shares = max(0, total_shares - founder_shares - pe_total_shares)
        public_ownership_pct = (
            (public_shares / total_shares) if total_shares > 0 else 0.0
        )
        public_stake_value = public_ownership_pct * current_valuation
        # Public capital in: sstkq across all quarters (secondaries + IPO proceeds)
        public_capital_in = sum(float(r.sstkq) for r in rows)
        public_npv = (
            public_stake_value / ((1 + r_q) ** n_quarters)
            - public_capital_in
        )

        # ── Aggregate equity NPV (legacy field for backward compat) ──
        total_npv = founder_npv + pe_npv + public_npv

        # IRR approximation (founder perspective, annualized)
        if founder_capital_in > 0 and n_quarters > 0:
            total_return = (
                founder_stake_value + founder_distributions
                + founder_capital_in  # adjusting so multiple is gross
            )
            total_multiple = (
                (founder_stake_value + founder_distributions) / founder_capital_in
                if founder_capital_in > 0 else 0
            )
            if total_multiple > 0:
                irr_approx = total_multiple ** (4 / n_quarters) - 1
            else:
                irr_approx = -1.0
        else:
            irr_approx = -1.0

        scores.append(FirmScore(
            firm_id=fid,
            incarnation=int(rows[0].incarnation),
            lifespan_quarters=n_quarters,
            is_public=is_public,
            lifecycle_stage=lifecycle_stage,
            current_valuation=current_valuation,
            founder_capital_in=founder_capital_in,
            founder_shares_held=founder_shares,
            founder_ownership_pct=founder_ownership_pct,
            founder_stake_value=founder_stake_value,
            founder_npv=founder_npv,
            pe_total_invested=pe_total_invested,
            pe_total_shares_held=pe_total_shares,
            pe_ownership_pct=pe_ownership_pct,
            pe_total_stake_value=pe_total_stake_value,
            pe_multiple=pe_multiple,
            pe_npv=pe_npv,
            public_capital_in=public_capital_in,
            public_shares_held=public_shares,
            public_ownership_pct=public_ownership_pct,
            public_stake_value=public_stake_value,
            public_npv=public_npv,
            total_dividends=total_div,
            total_buybacks=total_buyback,
            ipo_invested=founder_capital_in,  # legacy alias
            total_capital_raised=founder_capital_in + pe_total_invested + public_capital_in,
            terminal_market_cap=current_valuation,
            equity_npv=total_npv,
            equity_irr_approx=irr_approx,
            defaulted=defaulted,
            default_quarter=default_q,
        ))

    return scores


def compute_debt_score(
    compustat_rows: list[CompustatRow],
    firms: dict[str, FirmState],
    risk_free_rate: float,
) -> DebtScore:
    """Compute NPV for the lending system."""

    total_loaned = 0
    total_interest = 0
    total_principal_back = 0

    # Track debt changes across quarters per firm
    from collections import defaultdict
    by_firm = defaultdict(list)
    for row in compustat_rows:
        by_firm[row.firm_id].append(row)

    for fid, rows in by_firm.items():
        for i in range(len(rows)):
            current_debt = float(rows[i].dlttq) + float(rows[i].dlcq)
            prev_debt = (float(rows[i-1].dlttq) + float(rows[i-1].dlcq)) if i > 0 else 0
            interest = float(rows[i].xintq)

            new_lending = max(0, current_debt - prev_debt)
            repayment = max(0, prev_debt - current_debt)

            total_loaned += new_lending
            total_interest += interest
            total_principal_back += repayment

    # Terminal: outstanding debt at run end
    for fid, firm in firms.items():
        if firm.is_active:
            outstanding = firm.revolver_balance + firm.long_term_debt
            total_principal_back += outstanding  # assume recovered at par if firm alive

    total_losses = max(0, total_loaned - total_principal_back)
    loss_rate = total_losses / max(1, total_loaned)

    # NPV: loaned out (negative), interest + principal back (positive)
    debt_npv = -total_loaned + total_interest + total_principal_back

    return DebtScore(
        total_loaned=total_loaned,
        total_interest_received=total_interest,
        total_principal_recovered=total_principal_back,
        total_losses=total_losses,
        debt_npv=debt_npv,
        loss_rate=loss_rate,
    )


def compute_pricing_score(compustat_rows: list[CompustatRow]) -> PricingScore:
    """Compute equity pricing accuracy.
    Pricing error = P_t - P*_t where P*_t = (P_{t+1} + DIV_{t+1}) / (1 + r_f)
    i.e., the "rational" price is what you'd pay to receive next quarter's price + dividends.
    """
    from collections import defaultdict
    by_firm = defaultdict(list)
    for row in compustat_rows:
        by_firm[row.firm_id].append(row)

    errors = []
    for fid, rows in by_firm.items():
        for i in range(len(rows) - 1):
            p_t = float(rows[i].prccq)
            p_next = float(rows[i+1].prccq)
            # Wave ν: skip observations where either price is essentially
            # zero (defaulted / pre-IPO firm). Including them blew the
            # MAPE up to >10,000% because pct_error = abs(err)/0.01 floor.
            # The metric only makes sense for actively traded firms.
            if p_t < 1.0 or p_next < 1.0:
                continue
            div_next = float(rows[i+1].dvq) / max(1, float(rows[i+1].cshoq) * 1_000_000)
            r_f = 0.01  # quarterly risk-free
            p_star = (p_next + div_next) / (1 + r_f)
            error = p_t - p_star
            pct_error = abs(error) / p_t
            errors.append((error, pct_error))

    if not errors:
        return PricingScore(0, 0, 0, 0)

    mean_err = sum(e[0] for e in errors) / len(errors)
    rmse = math.sqrt(sum(e[0]**2 for e in errors) / len(errors))
    mape = sum(e[1] for e in errors) / len(errors)

    return PricingScore(
        mean_error=mean_err,
        rmse=rmse,
        mean_abs_pct_error=mape,
        n_observations=len(errors),
    )


def format_scorecard(sc: RunScorecard) -> str:
    """Format the scorecard as readable text."""
    lines = [f"=== RUN SCORECARD: {sc.run_id} ===\n"]

    lines.append("FIRM PERFORMANCE (valuation-anchored NPV by stakeholder class):")
    for fs in sc.firm_scores:
        status = "DEFAULTED" if fs.defaulted else "ACTIVE"
        stage_tag = (f"PUBLIC" if fs.is_public else f"PRIVATE/{fs.lifecycle_stage}")
        # Headline line: aggregate equity NPV + current valuation + lifespan + status
        lines.append(
            f"  {fs.firm_id} [{stage_tag}]: "
            f"total equity NPV=${fs.equity_npv/1e6:+.1f}M | "
            f"valuation=${fs.current_valuation/1e6:.0f}M | "
            f"{fs.lifespan_quarters}Q | {status}"
        )
        # Founder detail (always shown — every firm has founders)
        lines.append(
            f"    Founders: ${fs.founder_capital_in/1e6:.0f}M in ->"
            f"{fs.founder_ownership_pct:.1%} stake worth "
            f"${fs.founder_stake_value/1e6:.1f}M | NPV=${fs.founder_npv/1e6:+.1f}M"
        )
        # PE detail (only if any PE capital was raised)
        if fs.pe_total_invested > 0:
            lines.append(
                f"    PE funds: ${fs.pe_total_invested/1e6:.0f}M in ->"
                f"{fs.pe_ownership_pct:.1%} stake worth "
                f"${fs.pe_total_stake_value/1e6:.1f}M | "
                f"MOIC={fs.pe_multiple:.2f}x | NPV=${fs.pe_npv/1e6:+.1f}M"
            )
        # Public detail (only if firm is/was public)
        if fs.public_capital_in > 0 or fs.is_public:
            lines.append(
                f"    Public: ${fs.public_capital_in/1e6:.0f}M in ->"
                f"{fs.public_ownership_pct:.1%} stake worth "
                f"${fs.public_stake_value/1e6:.1f}M | NPV=${fs.public_npv/1e6:+.1f}M"
            )

    if sc.debt_score:
        ds = sc.debt_score
        lines.append(f"\nDEBT PERFORMANCE:")
        lines.append(
            f"  Loaned: ${ds.total_loaned/1e6:.1f}M | "
            f"Interest: ${ds.total_interest_received/1e6:.1f}M | "
            f"Recovered: ${ds.total_principal_recovered/1e6:.1f}M | "
            f"Losses: ${ds.total_losses/1e6:.1f}M | "
            f"Loss rate: {ds.loss_rate:.1%} | "
            f"NPV: ${ds.debt_npv/1e6:+.1f}M"
        )

    if sc.pricing_score:
        ps = sc.pricing_score
        lines.append(f"\nEQUITY PRICING ACCURACY:")
        lines.append(
            f"  Mean error: ${ps.mean_error:.2f}/sh | "
            f"RMSE: ${ps.rmse:.2f}/sh | "
            f"MAPE: {ps.mean_abs_pct_error:.1%} | "
            f"Observations: {ps.n_observations}"
        )

    if sc.environment_votes:
        lines.append(f"\nENVIRONMENT REALISM VOTES ({len(sc.environment_votes)} voters):")
        dims = ["market_realism", "event_realism", "narrative_quality",
                "consistency", "fairness", "overall"]
        for dim in dims:
            vals = [getattr(v, dim) for v in sc.environment_votes]
            avg = sum(vals) / len(vals)
            lines.append(f"  {dim}: {avg:.1f}/10 (range {min(vals)}-{max(vals)})")

    return "\n".join(lines)


def save_scores(
    scorecard: RunScorecard,
    output_dir: str,
    data_dir: str,
):
    """Save scorecard to run output and append to cross-run database."""

    # Save to run output
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    with open(out_path / "scorecard.txt", "w", encoding="utf-8") as f:
        f.write(format_scorecard(scorecard))

    # Append to cross-run scores.csv
    scores_path = Path(data_dir) / "scores.csv"
    write_header = not scores_path.exists()

    rows = []
    for fs in scorecard.firm_scores:
        rows.append({
            "run_id": scorecard.run_id,
            "actor_id": fs.firm_id,
            "actor_type": "firm",
            "equity_npv": fs.equity_npv,                     # aggregate (all classes)
            "equity_irr_annual": fs.equity_irr_approx,
            "terminal_value": fs.founder_stake_value,         # founder residual (was terminal_value_to_ipo)
            "terminal_market_cap": fs.current_valuation,     # current valuation anchor
            "dilution_factor_final": fs.founder_ownership_pct,  # reused slot for founder %
            "total_invested": fs.founder_capital_in,
            "total_capital_raised": fs.total_capital_raised,
            "lifespan_quarters": fs.lifespan_quarters,
            "defaulted": 1 if fs.defaulted else 0,
            # Wave λ additional fields
            "founder_npv": fs.founder_npv,
            "pe_invested": fs.pe_total_invested,
            "pe_npv": fs.pe_npv,
            "pe_multiple": fs.pe_multiple,
            "public_npv": fs.public_npv,
            "is_public": 1 if fs.is_public else 0,
            "lifecycle_stage": fs.lifecycle_stage,
        })

    _wave_lambda_extras = {
        "founder_npv": 0, "pe_invested": 0, "pe_npv": 0,
        "pe_multiple": 0, "public_npv": 0,
        "is_public": 0, "lifecycle_stage": "n/a",
    }
    if scorecard.debt_score:
        ds = scorecard.debt_score
        rows.append({
            "run_id": scorecard.run_id,
            "actor_id": "debt_system",
            "actor_type": "debt",
            "equity_npv": ds.debt_npv,
            "equity_irr_annual": 0,
            "terminal_value": 0,
            "terminal_market_cap": 0,
            "dilution_factor_final": 0,
            "total_invested": ds.total_loaned,
            "total_capital_raised": 0,
            "lifespan_quarters": 0,
            "defaulted": 0,
            **_wave_lambda_extras,
        })

    if scorecard.pricing_score:
        ps = scorecard.pricing_score
        rows.append({
            "run_id": scorecard.run_id,
            "actor_id": "equity_pricing",
            "actor_type": "pricing",
            "equity_npv": 0,
            "equity_irr_annual": 0,
            "terminal_value": ps.rmse,
            "terminal_market_cap": 0,
            "dilution_factor_final": 0,
            "total_invested": ps.mean_abs_pct_error,
            "total_capital_raised": 0,
            "lifespan_quarters": ps.n_observations,
            "defaulted": 0,
            **_wave_lambda_extras,
        })

    if rows:
        fieldnames = list(rows[0].keys())
        with open(scores_path, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            if write_header:
                writer.writeheader()
            writer.writerows(rows)
