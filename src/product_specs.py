"""
Product specification sheets per company.

Tracks each firm's product characteristics, manufacturing details, and
innovation history. Updated each quarter by the orchestrator based on
firm state and R&D outcomes.

Outputs as YAML/text files per run for inspection.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from .types import FirmState, SimParams, QuarterFlows


@dataclass
class ProductSpec:
    """Product specification for one firm at a point in time."""
    firm_id: str
    quarter: int = 0

    # Identity
    company_name: str = ""
    product_name: str = ""

    # Product characteristics
    generation: int = 1
    delivery_method: str = "IV infusion (quarterly, clinic-administered)"
    efficacy_age_reversal_years: float = 6.5
    serious_ae_rate_pct: float = 7.3
    paralysis_risk_pct: float = 0.4

    # Manufacturing
    capacity_per_quarter: int = 250
    unit_cost: float = 14_000
    batch_failure_rate_pct: float = 7.0
    capacity_utilization_pct: float = 0.0

    # Commercial
    price_per_course: float = 95_000
    patients_treated_cumulative: int = 0
    patients_treated_this_quarter: int = 0
    market_share_pct: float = 0.0

    # R&D progress
    rd_product_cumulative: float = 0.0
    rd_product_pct_gen2: float = 0.0
    rd_process_cumulative: float = 0.0
    rd_delivery_cumulative: float = 0.0
    cogs_reduction_from_process_pct: float = 0.0

    # Quality scores
    capability_stock: float = 35.0
    brand_stock: float = 10.0

    # Innovation history (accumulates)
    milestones: list[str] = field(default_factory=list)

    # Key strengths and issues
    strengths: list[str] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)

    # Wave ν: richer narrative context — makes defaults feel costly by
    # surfacing what the firm has actually built up over its R&D history.
    patent_status: str = ""
    customer_satisfaction: str = ""
    willingness_to_pay_estimate: str = ""
    competitor_replication_risk: str = ""
    what_firm_has_achieved: str = ""


COMPANY_NAMES = {
    "firm_0": ("Aeterna Therapeutics", "Revitagen"),
    "firm_1": ("GenVita Sciences", "VitaCore"),
    "firm_2": ("NovaLife Therapeutics", "NovaGen"),
    "firm_3": ("BioAge Pharma", "AgeShield"),
    "firm_4": ("Senova Bio", "SenoVax"),
}

DELIVERY_METHODS = {
    1: "IV infusion (quarterly, clinic-administered)",
    2: "Subcutaneous injection (monthly, self-administered)",
    3: "Oral tablet (daily)",
    4: "One-time gene therapy + annual oral booster",
}

GEN_EFFICACY = {1: 6.5, 2: 12.5, 3: 17.5, 4: 22.5}
GEN_AE_RATE = {1: 7.3, 2: 2.5, 3: 0.5, 4: 0.2}
GEN_PARALYSIS = {1: 0.4, 2: 0.05, 3: 0.01, 4: 0.01}


def build_product_spec(
    firm: FirmState,
    flows: QuarterFlows | None,
    prior_spec: ProductSpec | None,
    params: SimParams,
) -> ProductSpec:
    """Build or update a product spec from current firm state."""

    import math

    names = COMPANY_NAMES.get(firm.firm_id, (firm.firm_id, "SRT Product"))
    gen = firm.product_generation
    gen2_threshold = float(getattr(params, "gen_2_rd_threshold", 500_000_000))

    # Process R&D reduction
    process_reduction = params.process_rd_max_reduction * (
        1 - math.exp(-firm.rd_cumulative_process / params.process_rd_saturation)
    )

    # Cumulative patients
    prior_patients = prior_spec.patients_treated_cumulative if prior_spec else 0
    this_q_patients = flows.units_sold if flows else 0

    # Utilization
    util = (flows.capacity_utilization * 100) if flows else 0

    # Milestones (carry forward + add new)
    milestones = list(prior_spec.milestones) if prior_spec else []
    prior_gen = prior_spec.generation if prior_spec else 1
    if gen > prior_gen:
        milestones.append(f"Q{firm.quarter}: Achieved Gen {gen} product!")
    if prior_spec and firm.rd_cumulative_product > 100_000_000 and prior_spec.rd_product_cumulative <= 100_000_000:
        milestones.append(f"Q{firm.quarter}: Product R&D reached early-cumulative threshold")
    if prior_spec and firm.rd_cumulative_product > 250_000_000 and prior_spec.rd_product_cumulative <= 250_000_000:
        milestones.append(f"Q{firm.quarter}: Product R&D reached mid-stage cumulative threshold")

    # Strengths and issues (recomputed each quarter)
    strengths = []
    issues = []

    if firm.capability_stock > 50:
        strengths.append(f"Strong R&D capability ({firm.capability_stock:.0f}/100)")
    if firm.brand_stock > 40:
        strengths.append(f"Strong brand recognition ({firm.brand_stock:.0f}/100)")
    if process_reduction > 0.10:
        strengths.append(f"Manufacturing efficiency: {process_reduction:.0%} COGS reduction from process R&D")
    if flows and flows.net_sales > 0 and flows.gross_profit / flows.net_sales > 0.80:
        strengths.append(f"High gross margins ({flows.gross_profit/flows.net_sales:.0%})")

    if firm.cash < 100_000_000:
        issues.append(f"Low cash reserves (${firm.cash/1e6:.0f}M)")
    # Note: "behind on Gen 2" check removed — threshold was a hardcoded
    # simulation constant and leaked a specific number into the firm-
    # facing product sheet. Firms judge pacing from their own plan + R&D
    # cumulative + observed competitor progress instead.
    if flows and flows.units_sold < flows.actual_production * 0.7:
        issues.append(f"Low sales vs production ({flows.units_sold}/{flows.actual_production} = {flows.units_sold/max(1,flows.actual_production):.0%} sell-through)")
    if flows and flows.net_income < -30_000_000:
        issues.append(f"Heavy losses (${flows.net_income/1e6:.0f}M net income)")
    if firm.brand_stock < 20:
        issues.append(f"Weak brand ({firm.brand_stock:.0f}/100)")

    # Wave ν: narrative enrichment. These strings capture the firm's
    # intangible build-up (IP posture, customer standing, replication
    # risk, WTP captured). Derived from existing state without adding
    # new state variables or hardcoded thresholds in prompts.
    cum_rd = firm.rd_cumulative_product + firm.rd_cumulative_process + firm.rd_cumulative_delivery
    if cum_rd <= 0:
        patent_status = "No IP filings yet."
    elif firm.capability_stock < 30:
        patent_status = "Early IP — a few provisional filings on initial work."
    elif firm.capability_stock < 60:
        patent_status = "Moderate patent portfolio covering core compound + process."
    else:
        patent_status = "Substantial patent portfolio — core compound, process, delivery, and formulation IP."

    brand = firm.brand_stock
    if brand < 20:
        cust_sat = "Low customer awareness and satisfaction."
    elif brand < 50:
        cust_sat = "Growing customer base; satisfaction positive but not yet a brand moat."
    else:
        cust_sat = "Strong customer loyalty and satisfaction; brand recognized in the market."

    # WTP qualitative read from recent realized price + share
    realized_price = flows.actual_price if flows and flows.actual_price else 0
    share_pct = flows.market_share * 100 if flows else 0
    if realized_price <= 0:
        wtp_estimate = "No sales data yet."
    elif share_pct > 15 and realized_price > 0:
        wtp_estimate = f"Customers are paying ~${realized_price:,.0f}/course at meaningful share ({share_pct:.1f}%), validating pricing power."
    elif share_pct > 5:
        wtp_estimate = f"Customers paying ~${realized_price:,.0f}/course; pricing being tested in the market."
    else:
        wtp_estimate = f"Sales at ~${realized_price:,.0f}/course with limited adoption so far."

    # Replication risk — how hard would it be for a competitor to copy?
    if firm.capability_stock > 60 and process_reduction > 0.15:
        replication = "Hard to replicate: deep scientific capability + proprietary process advantages."
    elif firm.capability_stock > 40:
        replication = "Moderate replication risk: capability is good but not unique; competitors could catch up with sustained R&D."
    else:
        replication = "High replication risk: core product not yet differentiated from what a well-funded entrant could build."

    # What has the firm achieved? Summary of built-up assets
    achievements_bits = []
    if firm.product_generation > 1:
        achievements_bits.append(f"advanced to Gen {firm.product_generation}")
    if firm.rd_cumulative_product > 0:
        achievements_bits.append(f"${firm.rd_cumulative_product/1e6:.0f}M cumulative product R&D invested")
    if firm.capability_stock > 40:
        achievements_bits.append(f"capability stock built to {firm.capability_stock:.0f}/100")
    if firm.brand_stock > 30:
        achievements_bits.append(f"brand stock built to {firm.brand_stock:.0f}/100")
    if firm.capacity_units >= 500:
        achievements_bits.append(f"manufacturing capacity scaled to {firm.capacity_units}/Q")
    if prior_patients + this_q_patients > 0:
        achievements_bits.append(
            f"{prior_patients + this_q_patients:,} cumulative patients treated"
        )
    what_achieved = (
        "; ".join(achievements_bits).capitalize()
        if achievements_bits else "Firm is in early buildup phase — limited operating history."
    )

    return ProductSpec(
        firm_id=firm.firm_id,
        quarter=firm.quarter,
        company_name=names[0],
        product_name=names[1],
        generation=gen,
        delivery_method=DELIVERY_METHODS.get(gen, DELIVERY_METHODS[1]),
        efficacy_age_reversal_years=GEN_EFFICACY.get(gen, 6.5),
        serious_ae_rate_pct=GEN_AE_RATE.get(gen, 7.3),
        paralysis_risk_pct=GEN_PARALYSIS.get(gen, 0.4),
        capacity_per_quarter=firm.capacity_units,
        unit_cost=firm.base_unit_cost,
        batch_failure_rate_pct=7.0 * (1 - process_reduction * 0.3),
        capacity_utilization_pct=util,
        price_per_course=flows.actual_price if flows else 95_000,
        patients_treated_cumulative=prior_patients + this_q_patients,
        patients_treated_this_quarter=this_q_patients,
        market_share_pct=flows.market_share * 100 if flows else 0,
        rd_product_cumulative=firm.rd_cumulative_product,
        rd_product_pct_gen2=firm.rd_cumulative_product / gen2_threshold * 100,
        rd_process_cumulative=firm.rd_cumulative_process,
        rd_delivery_cumulative=firm.rd_cumulative_delivery,
        cogs_reduction_from_process_pct=process_reduction * 100,
        capability_stock=firm.capability_stock,
        brand_stock=firm.brand_stock,
        milestones=milestones,
        strengths=strengths,
        issues=issues,
        patent_status=patent_status,
        customer_satisfaction=cust_sat,
        willingness_to_pay_estimate=wtp_estimate,
        competitor_replication_risk=replication,
        what_firm_has_achieved=what_achieved,
    )


def format_product_spec(spec: ProductSpec) -> str:
    """Format a product spec as readable text."""
    milestones_text = "\n".join(f"  - {m}" for m in spec.milestones) if spec.milestones else "  (none yet)"
    strengths_text = "\n".join(f"  + {s}" for s in spec.strengths) if spec.strengths else "  (none identified)"
    issues_text = "\n".join(f"  ! {i}" for i in spec.issues) if spec.issues else "  (none identified)"

    return f"""=== {spec.company_name} ({spec.firm_id}) -- Q{spec.quarter} Product Sheet ===

PRODUCT: {spec.product_name}
  Generation: {spec.generation}
  Delivery: {spec.delivery_method}
  Efficacy: {spec.efficacy_age_reversal_years:.1f} years epigenetic age reversal
  Serious AE rate: {spec.serious_ae_rate_pct:.1f}%
  Paralysis risk: {spec.paralysis_risk_pct:.2f}%

MANUFACTURING:
  Capacity: {spec.capacity_per_quarter} courses/quarter
  Unit cost: ${spec.unit_cost:,.0f}/course
  Utilization: {spec.capacity_utilization_pct:.0f}%
  COGS reduction from process R&D: {spec.cogs_reduction_from_process_pct:.1f}%

COMMERCIAL:
  Price: ${spec.price_per_course:,.0f}/course
  Patients this quarter: {spec.patients_treated_this_quarter}
  Patients cumulative: {spec.patients_treated_cumulative}
  Market share: {spec.market_share_pct:.1f}%

R&D PIPELINE:
  Product R&D: ${spec.rd_product_cumulative:,.0f}
  Process R&D: ${spec.rd_process_cumulative:,.0f}
  Delivery R&D: ${spec.rd_delivery_cumulative:,.0f}

QUALITY INDICES:
  Capability: {spec.capability_stock:.1f}/100
  Brand: {spec.brand_stock:.1f}/100

INTANGIBLE ASSETS (what the firm has built):
  Achievements: {spec.what_firm_has_achieved}
  Patent posture: {spec.patent_status}
  Customer satisfaction: {spec.customer_satisfaction}
  Current WTP signal: {spec.willingness_to_pay_estimate}
  Replication risk: {spec.competitor_replication_risk}

INNOVATION MILESTONES:
{milestones_text}

KEY STRENGTHS:
{strengths_text}

KEY ISSUES:
{issues_text}
"""
