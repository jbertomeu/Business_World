"""
Operational Reports: connect R&D and SGA spending to practical outcomes.

This module generates quarterly reports that:
1. Translate abstract stock changes into concrete narrative events
2. Feed into the environment agent for market share determination
3. Feed back to firm agents so they understand what their spending accomplished
4. Accumulate over time into a living product/brand history

The reports are DETERMINISTIC (computed from state + randomness) so they are
consistent with the accounting. The environment agent reads them to inform its
demand allocation; the firm agent reads them to inform next quarter's decisions.

Flow:
  Firm spends R&D/SGA -> Accounting updates stocks ->
  This module generates reports -> Reports sent to environment + firm prompts
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from .types import FirmState, QuarterFlows, SimParams


# ─── R&D Progress Report ────────────────────────────────────────────────

@dataclass
class RDReport:
    """Quarterly R&D progress report for one firm."""
    firm_id: str
    quarter: int

    # Spending summary
    total_rd_spend: float = 0
    product_rd_spend: float = 0
    process_rd_spend: float = 0
    delivery_rd_spend: float = 0

    # Capability change
    capability_before: float = 0
    capability_after: float = 0
    capability_delta: float = 0

    # Gen 2 progress
    gen2_cumulative: float = 0
    gen2_pct: float = 0
    gen2_pct_prior: float = 0

    # Concrete outcomes (narrative color, deterministic from state)
    lab_results: list[str] = field(default_factory=list)
    pipeline_status: str = ""
    process_improvements: list[str] = field(default_factory=list)
    team_notes: str = ""

    # Summary for prompt
    summary: str = ""


def generate_rd_report(
    firm: FirmState,
    prior: FirmState,
    flows: QuarterFlows,
    params: SimParams,
    rng: random.Random,
) -> RDReport:
    """Generate an R&D progress report from the quarter's outcomes."""

    phase3_cost = params.mandatory_phase3_quarterly_cost
    discretionary = max(0, flows.rd_expense - phase3_cost)
    alloc = {"product": 0.6, "process": 0.25, "delivery": 0.15}  # default
    # Try to get actual allocation from R&D cumulative deltas
    prod_delta = firm.rd_cumulative_product - prior.rd_cumulative_product
    proc_delta = firm.rd_cumulative_process - prior.rd_cumulative_process
    deliv_delta = firm.rd_cumulative_delivery - prior.rd_cumulative_delivery

    gen2_threshold = float(getattr(params, "gen_2_rd_threshold", 500_000_000))
    gen2_pct = firm.rd_cumulative_product / gen2_threshold * 100
    gen2_pct_prior = prior.rd_cumulative_product / gen2_threshold * 100

    cap_delta = firm.capability_stock - prior.capability_stock

    # Generate concrete lab results based on spending level
    lab_results = []
    if prod_delta > 20_000_000:
        lab_results.append("Lead compound optimization showing promising selectivity improvements in cell assays")
        lab_results.append(f"Screening library expanded; {rng.randint(3,8)} new candidate molecules identified")
    elif prod_delta > 10_000_000:
        lab_results.append("Continued compound screening; incremental improvements in target binding affinity")
    elif prod_delta > 0:
        lab_results.append("Maintaining baseline research activities; no significant breakthroughs this quarter")

    if prod_delta > 15_000_000 and gen2_pct > 15:
        lab_results.append(f"Preclinical toxicology data encouraging -- Schwann cell toxicity reduced by {rng.randint(5,15)}% in latest batch")
    if gen2_pct > 30 and gen2_pct_prior <= 30:
        lab_results.append("*** MILESTONE: Gen 2 program entering IND-enabling development phase. Significant cumulative R&D invested. ***")
    if gen2_pct > 50 and gen2_pct_prior <= 50:
        lab_results.append("*** MILESTONE: Gen 2 lead candidate entering expanded testing. ***")

    # Process improvements
    process_improvements = []
    if proc_delta > 5_000_000:
        yield_improvement = 0.5 + rng.random() * 1.0
        process_improvements.append(f"Peptide synthesis yield improved by {yield_improvement:.1f} percentage points this quarter")
        process_improvements.append(f"Batch failure rate reduced; current rate ~{max(4, 7.0 - proc_delta/10_000_000):.1f}%")
    elif proc_delta > 0:
        process_improvements.append("Minor process optimization work; no significant yield improvement")

    # Delivery R&D
    if deliv_delta > 5_000_000:
        process_improvements.append("Subcutaneous formulation stability tests ongoing; shelf-life data pending")
    elif deliv_delta > 0:
        process_improvements.append("Preliminary delivery formulation work at early stage")

    # Pipeline status (qualitative stage labels; no simulation thresholds leaked)
    if gen2_pct < 5:
        pipeline_status = "Gen 2 program at concept stage. Current efforts focused on target identification and early screening."
    elif gen2_pct < 15:
        pipeline_status = "Gen 2 compound discovery ongoing. Hit-to-lead optimization in progress."
    elif gen2_pct < 30:
        pipeline_status = "Gen 2 lead optimization underway. Several promising candidates in preclinical evaluation."
    elif gen2_pct < 50:
        pipeline_status = "Gen 2 preclinical development. Lead candidate identified; IND-enabling studies planned."
    elif gen2_pct < 75:
        pipeline_status = "Gen 2 advanced preclinical development. IND filing approaching."
    else:
        pipeline_status = "Gen 2 late-stage development. Regulatory submission imminent."

    # Team notes (spending-dependent morale/capacity)
    if flows.rd_expense > 40_000_000:
        team_notes = "R&D team fully staffed and well-resourced. High morale. Multiple parallel workstreams active."
    elif flows.rd_expense > 25_000_000:
        team_notes = "R&D team adequately resourced. Good progress on primary programs."
    elif flows.rd_expense > 15_000_000:
        team_notes = "R&D budget tight. Some programs deferred. Team focused on highest-priority work."
    else:
        team_notes = "R&D funding at minimum levels. Only mandatory Phase III activities underway. Pipeline stalled."

    # Build summary (no simulation thresholds leaked — pipeline_status carries
    # the qualitative stage label).
    cap_direction = "improved" if cap_delta > 0.5 else "stable" if cap_delta > -0.5 else "declined"
    summary = (
        f"R&D Report Q{firm.quarter}: Spent ${flows.rd_expense/1e6:.0f}M total "
        f"(${prod_delta/1e6:.0f}M product, ${proc_delta/1e6:.0f}M process, ${deliv_delta/1e6:.0f}M delivery). "
        f"Capability {cap_direction} ({prior.capability_stock:.1f} -> {firm.capability_stock:.1f}). "
        f"Cumulative product R&D: ${firm.rd_cumulative_product/1e6:.0f}M. "
        f"{pipeline_status}"
    )

    return RDReport(
        firm_id=firm.firm_id,
        quarter=firm.quarter,
        total_rd_spend=flows.rd_expense,
        product_rd_spend=prod_delta,
        process_rd_spend=proc_delta,
        delivery_rd_spend=deliv_delta,
        capability_before=prior.capability_stock,
        capability_after=firm.capability_stock,
        capability_delta=cap_delta,
        gen2_cumulative=firm.rd_cumulative_product,
        gen2_pct=gen2_pct,
        gen2_pct_prior=gen2_pct_prior,
        lab_results=lab_results,
        pipeline_status=pipeline_status,
        process_improvements=process_improvements,
        team_notes=team_notes,
        summary=summary,
    )


# ─── Brand & Marketing Report ───────────────────────────────────────────

@dataclass
class BrandReport:
    """Quarterly brand and marketing report for one firm."""
    firm_id: str
    quarter: int

    # Spending
    sga_spend: float = 0

    # Brand change
    brand_before: float = 0
    brand_after: float = 0
    brand_delta: float = 0

    # Marketing activities (narrative, deterministic from spend level)
    marketing_activities: list[str] = field(default_factory=list)
    physician_outreach: str = ""
    patient_feedback: list[str] = field(default_factory=list)
    media_coverage: list[str] = field(default_factory=list)
    brand_health: str = ""

    # Customer service quality (affects retention, tied to SGA level)
    customer_service_rating: float = 0.0  # 1-10
    physician_satisfaction: float = 0.0   # 1-10
    patient_retention_risk: str = ""

    # Summary
    summary: str = ""


def generate_brand_report(
    firm: FirmState,
    prior: FirmState,
    flows: QuarterFlows,
    params: SimParams,
    rng: random.Random,
) -> BrandReport:
    """Generate a brand/marketing report from the quarter's outcomes."""

    brand_delta = firm.brand_stock - prior.brand_stock
    sga = flows.sga_expense

    # Marketing activities based on spend level
    marketing_activities = []
    if sga > 20_000_000:
        marketing_activities.extend([
            "Major direct-to-consumer awareness campaign across digital and print media",
            f"Sponsored {rng.randint(3,6)} medical conferences with keynote presentations",
            "Expanded sales force; new territories opened",
            "Launched patient ambassador program with enrolled testimonial providers",
        ])
    elif sga > 12_000_000:
        marketing_activities.extend([
            "Targeted digital advertising campaign to high-net-worth demographics",
            f"Presentations at {rng.randint(2,4)} medical conferences",
            "Physician education program: 200+ doctors briefed on latest clinical data",
        ])
    elif sga > 5_000_000:
        marketing_activities.extend([
            "Basic physician outreach maintained; no new campaigns",
            "Limited online presence; relying on word-of-mouth",
        ])
    else:
        marketing_activities.append("Minimal marketing activity. Brand awareness stagnating.")

    # Physician outreach quality
    if sga > 15_000_000:
        physician_outreach = (
            f"Active engagement with {rng.randint(150,300)} prescribing physicians. "
            f"Medical affairs team conducting {rng.randint(5,12)} KOL advisory boards this quarter."
        )
        physician_satisfaction = 7.0 + rng.random() * 1.5
    elif sga > 8_000_000:
        physician_outreach = (
            f"Maintaining relationships with ~{rng.randint(80,150)} physicians. "
            "Limited new physician acquisition."
        )
        physician_satisfaction = 5.5 + rng.random() * 1.5
    else:
        physician_outreach = (
            "Physician outreach minimal. Risk of losing prescriber base."
        )
        physician_satisfaction = 3.0 + rng.random() * 1.5

    # Patient feedback (depends on units sold + SGA quality)
    patient_feedback = []
    if flows.units_sold > 0:
        if sga > 10_000_000:
            patient_feedback.append(f"Patient support hotline handling {flows.units_sold * rng.randint(2,4)} calls/quarter. Satisfaction: good.")
            patient_feedback.append(f"Post-treatment follow-up completion rate: {rng.randint(85,95)}%")
        else:
            patient_feedback.append(f"Patient support understaffed. Complaints about wait times increasing.")
            patient_feedback.append(f"Post-treatment follow-up completion rate: {rng.randint(55,75)}%")

        if sga < 5_000_000 and flows.units_sold > 100:
            patient_feedback.append("*** WARNING: Customer service quality declining due to low SGA investment. Risk of negative reviews and patient attrition. ***")

    # Media coverage
    media_coverage = []
    if sga > 15_000_000:
        media_coverage.append(f"Positive feature in health trade publication ({rng.choice(['Endpoints News', 'STAT News', 'BioPharma Dive'])})")
        if rng.random() > 0.6:
            media_coverage.append("Favorable patient testimonial shared widely on social media")
    elif sga > 8_000_000:
        media_coverage.append("Modest trade press mentions; no mainstream coverage")
    else:
        media_coverage.append("No significant media activity. Low visibility.")

    # Customer service rating (1-10, directly affects patient retention)
    if sga > 20_000_000:
        customer_service_rating = 8.0 + rng.random() * 1.5
    elif sga > 12_000_000:
        customer_service_rating = 6.5 + rng.random() * 1.5
    elif sga > 5_000_000:
        customer_service_rating = 4.5 + rng.random() * 1.5
    else:
        customer_service_rating = 2.0 + rng.random() * 1.5

    # Patient retention risk
    if customer_service_rating >= 7:
        patient_retention_risk = "Low -- patients well-supported and likely to continue treatment"
    elif customer_service_rating >= 5:
        patient_retention_risk = "Moderate -- some patients may switch to competitors with better service"
    else:
        patient_retention_risk = "HIGH -- poor service quality driving patient dissatisfaction and attrition"

    # Brand health narrative
    if brand_delta > 2:
        brand_health = f"Brand strengthening rapidly (+{brand_delta:.1f} points). Marketing investment paying off with growing physician and patient awareness."
    elif brand_delta > 0:
        brand_health = f"Brand growing modestly (+{brand_delta:.1f} points). Steady marketing keeping pace with natural decay."
    elif brand_delta > -2:
        brand_health = f"Brand roughly stable ({brand_delta:+.1f} points). Current spending barely offsetting natural brand decay."
    else:
        brand_health = f"*** Brand declining ({brand_delta:+.1f} points). Marketing spend insufficient to maintain brand presence. Competitors are gaining mindshare. ***"

    summary = (
        f"Brand Report Q{firm.quarter}: SGA ${sga/1e6:.0f}M. "
        f"Brand {prior.brand_stock:.1f} -> {firm.brand_stock:.1f} ({brand_delta:+.1f}). "
        f"Customer service: {customer_service_rating:.1f}/10. "
        f"Physician satisfaction: {physician_satisfaction:.1f}/10. "
        f"Retention risk: {patient_retention_risk.split(' --')[0]}. "
        f"{brand_health.split('.')[0]}."
    )

    return BrandReport(
        firm_id=firm.firm_id,
        quarter=firm.quarter,
        sga_spend=sga,
        brand_before=prior.brand_stock,
        brand_after=firm.brand_stock,
        brand_delta=brand_delta,
        marketing_activities=marketing_activities,
        physician_outreach=physician_outreach,
        patient_feedback=patient_feedback,
        media_coverage=media_coverage,
        brand_health=brand_health,
        customer_service_rating=customer_service_rating,
        physician_satisfaction=physician_satisfaction,
        patient_retention_risk=patient_retention_risk,
        summary=summary,
    )


# ─── Format for Prompts ─────────────────────────────────────────────────

def format_rd_report_for_firm(report: RDReport) -> str:
    """Format R&D report for inclusion in the firm's prompt."""
    labs = "\n".join(f"  - {r}" for r in report.lab_results) if report.lab_results else "  (no significant results)"
    procs = "\n".join(f"  - {r}" for r in report.process_improvements) if report.process_improvements else "  (none)"

    return f"""R&D PROGRESS REPORT (Q{report.quarter}):
  Total R&D: ${report.total_rd_spend/1e6:.0f}M (product ${report.product_rd_spend/1e6:.0f}M, process ${report.process_rd_spend/1e6:.0f}M, delivery ${report.delivery_rd_spend/1e6:.0f}M)
  Capability: {report.capability_before:.1f} -> {report.capability_after:.1f} ({report.capability_delta:+.1f})
  Cumulative product R&D: ${report.gen2_cumulative/1e6:.0f}M
  Pipeline: {report.pipeline_status}

  Lab Results:
{labs}

  Process Improvements:
{procs}

  Team Assessment: {report.team_notes}"""


def format_brand_report_for_firm(report: BrandReport) -> str:
    """Format brand report for inclusion in the firm's prompt."""
    activities = "\n".join(f"  - {a}" for a in report.marketing_activities)
    feedback = "\n".join(f"  - {f}" for f in report.patient_feedback) if report.patient_feedback else "  (no patient data)"
    media = "\n".join(f"  - {m}" for m in report.media_coverage)

    return f"""BRAND & MARKETING REPORT (Q{report.quarter}):
  SGA Spend: ${report.sga_spend/1e6:.0f}M
  Brand: {report.brand_before:.1f} -> {report.brand_after:.1f} ({report.brand_delta:+.1f})
  Customer Service Rating: {report.customer_service_rating:.1f}/10
  Physician Satisfaction: {report.physician_satisfaction:.1f}/10
  Patient Retention Risk: {report.patient_retention_risk}

  Marketing Activities:
{activities}

  Physician Outreach: {report.physician_outreach}

  Patient Feedback:
{feedback}

  Media Coverage:
{media}

  Brand Health: {report.brand_health}"""


def format_reports_for_environment(
    rd_reports: dict[str, RDReport],
    brand_reports: dict[str, BrandReport],
) -> str:
    """Format all reports for the environment agent's market resolution prompt.
    The environment uses this to justify demand allocation."""
    lines = []
    for fid in sorted(rd_reports):
        rd = rd_reports[fid]
        br = brand_reports[fid]
        lines.append(f"""{fid}:
  R&D: ${rd.total_rd_spend/1e6:.0f}M -> Capability {rd.capability_after:.0f}/100, cumulative product R&D ${rd.gen2_cumulative/1e6:.0f}M
  SGA: ${br.sga_spend/1e6:.0f}M -> Brand {br.brand_after:.0f}/100, Service {br.customer_service_rating:.0f}/10
  Brand trend: {br.brand_health.split('.')[0]}
  Retention risk: {br.patient_retention_risk.split(' --')[0]}""")

    return "OPERATIONAL REPORTS (use these to inform demand allocation):\n" + "\n".join(lines)
