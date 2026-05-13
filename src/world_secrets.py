"""
World Secrets: hidden environmental context that ONLY the environment agent sees.

This creates asymmetric information and hidden dynamics that make firms face
genuinely different — and sometimes surprising — outcomes from similar decisions.

The secrets are generated at run start from a template category + seed.
They include:
- Research paths with different success rates
- Pre-planned events triggered by quarter or firm behavior
- Market dynamics with hidden thresholds
- Firm-specific vulnerabilities and advantages

CRITICAL: This content is NEVER sent to firm agents or financial agents.
Only the environment agent sees it in its system prompt.
"""

from __future__ import annotations

import random


# ─── Template Categories ─────────────────────────────────────────────────

TEMPLATE_CATEGORIES = {
    "baseline": "Standard market dynamics with moderate uncertainty",
    "disruption": "High volatility with major technological and regulatory shocks",
    "steady_growth": "Favorable conditions with gradual market expansion",
    "regulatory_storm": "Heavy regulatory intervention and pricing pressure",
    "scientific_breakthrough": "Major academic discoveries accelerate the R&D race",
}

DEFAULT_CATEGORY = "baseline"


# ─── Secret Generation ───────────────────────────────────────────────────

def generate_world_secrets(
    seed: int,
    n_firms: int,
    n_quarters: int,
    category: str = "baseline",
) -> str:
    """Generate hidden environment context for this run.

    Args:
        seed: RNG seed for reproducible randomization within the template
        n_firms: number of firms
        n_quarters: simulation length
        category: template category (baseline, disruption, steady_growth, etc.)

    Returns:
        Multi-page string with hidden context. ONLY for environment agent.
    """
    rng = random.Random(seed + hash(category))

    firm_ids = [f"firm_{i}" for i in range(n_firms)]
    company_names = {
        "firm_0": "Aeterna", "firm_1": "GenVita", "firm_2": "NovaLife",
        "firm_3": "BioAge", "firm_4": "Senova",
    }

    # ── Research Paths ───────────────────────────────────────────────────

    research_paths = _generate_research_paths(rng, category)

    # ── Pre-Planned Events ───────────────────────────────────────────────

    events = _generate_events(rng, firm_ids, company_names, n_quarters, category)

    # ── Market Dynamics ──────────────────────────────────────────────────

    market_dynamics = _generate_market_dynamics(rng, category)

    # ── Firm-Specific Hidden Factors ─────────────────────────────────────

    firm_factors = _generate_firm_factors(rng, firm_ids, company_names, n_quarters, category)

    # ── Demand Sensitivity Rules ─────────────────────────────────────────

    demand_rules = _generate_demand_rules(rng, category)

    # ── Assemble ─────────────────────────────────────────────────────────

    return f"""=== HIDDEN CONTEXT: ENVIRONMENT ONLY ===
=== DO NOT REVEAL THIS TO FIRMS OR FINANCIAL AGENTS ===
=== Category: {category} | Seed: {seed} ===

Use this context to create realistic, varied, and sometimes surprising market
outcomes. Firms should NOT be able to predict what happens — their actions
should have consequences they don't fully anticipate.

--- RESEARCH PATHS ---
{research_paths}

--- PRE-PLANNED EVENTS ---
{events}

--- HIDDEN MARKET DYNAMICS ---
{market_dynamics}

--- FIRM-SPECIFIC HIDDEN FACTORS ---
{firm_factors}

--- DEMAND SENSITIVITY RULES ---
{demand_rules}

--- INSTRUCTIONS ---
1. Use these secrets to JUSTIFY non-uniform outcomes for similar actions.
   Two firms spending the same on R&D should NOT get the same results if
   one is on a better research path.
2. Trigger pre-planned events at the specified quarters. Describe them in
   the gazette narrative WITHOUT revealing that they were pre-planned.
3. Apply firm-specific factors when evaluating outcomes. A firm whose hidden
   vulnerability is triggered should suffer consequences visible in their
   market share and narrative, but the ROOT CAUSE should remain hidden.
4. Market dynamics thresholds should create "tipping points" that surprise
   firms — sudden demand shifts, regulatory actions, competitive dynamics.
5. When narrating the gazette, reference these hidden dynamics indirectly
   ("industry sources report...", "analysts note unexpected...", etc.)
"""


def _generate_research_paths(rng: random.Random, category: str) -> str:
    paths = [
        ("Targeted senolytic (precision medicine)", rng.randint(55, 75), rng.randint(400, 600)),
        ("Combination therapy (multi-target)", rng.randint(35, 55), rng.randint(300, 450)),
        ("Gene editing approach (revolutionary)", rng.randint(20, 40), rng.randint(600, 900)),
    ]

    # Category modifiers
    if category == "scientific_breakthrough":
        paths[2] = (paths[2][0], min(80, paths[2][1] + 20), paths[2][2] - 100)
    elif category == "disruption":
        paths[1] = (paths[1][0], max(20, paths[1][1] - 15), paths[1][2])

    side_effects = [
        f"Path B (combination therapy) has a {rng.randint(20,45)}% chance of discovering a new side effect (liver enzyme elevation) in late-stage trials.",
        f"Path C (gene editing) has a {rng.randint(10,30)}% chance of triggering an immune response that limits efficacy to {rng.randint(40,60)}% of patients.",
    ]

    process_ceiling = rng.randint(60, 72)

    return f"""There are 3 possible R&D approaches to Gen 2. Firms don't know which path
they are on — their spending determines outcomes probabilistically.

Path A: {paths[0][0]}
  Success rate: {paths[0][1]}% once ${paths[0][2]}M+ cumulative product R&D reached
  This is the "safe" path — higher success but needs more investment.

Path B: {paths[1][0]}
  Success rate: {paths[1][1]}% once ${paths[1][2]}M+ reached
  Cheaper threshold but riskier. {side_effects[0]}

Path C: {paths[2][0]}
  Success rate: {paths[2][1]}% once ${paths[2][2]}M+ reached
  High risk, high reward. {side_effects[1]}

Firms do NOT choose their path — it's determined by HOW they allocate R&D:
  - Heavy product allocation (>70%): more likely on Path A
  - Balanced allocation: more likely on Path B
  - Heavy process allocation (>40%): more likely on Path C variant

Process R&D ceiling: Peptide synthesis yields plateau at {process_ceiling}%.
Firms investing beyond ${rng.randint(80,120)}M cumulative in process R&D
will see diminishing returns. Do not grant more than 22% COGS reduction."""


def _generate_events(rng, firm_ids, names, n_quarters, category) -> str:
    events = []

    # Academic breakthrough (early-mid)
    q_academic = rng.randint(3, max(3, min(6, n_quarters)))
    demand_boost = rng.randint(10, 25)
    events.append(
        f"Q{q_academic}: Academic breakthrough — a major university publishes a biomarker\n"
        f"  that predicts paralysis risk. This is big news. Demand increases by {demand_boost}%\n"
        f"  over the next 2 quarters as patients feel safer."
    )

    # Competitor technology threat (mid)
    if n_quarters > 5:
        q_threat = rng.randint(5, max(4, min(8, n_quarters)))
        events.append(
            f"Q{q_threat}-Q{q_threat+2}: A non-SRT longevity approach (caloric restriction mimetic)\n"
            f"  enters Phase II trials. Media attention creates uncertainty. SRT demand growth\n"
            f"  slows by {rng.randint(5,15)}% for 2-3 quarters. This affects all firms equally."
        )

    # Safety event (triggered by behavior)
    low_process_firm = rng.choice(firm_ids)
    events.append(
        f"TRIGGERED: If {names.get(low_process_firm, low_process_firm)} has the LOWEST cumulative process R&D\n"
        f"  when total industry patients exceed {rng.randint(3000, 5000)}, they experience a\n"
        f"  safety event: {rng.choice(['unexpected cardiac arrhythmia', 'rare autoimmune flare cluster', 'severe liver enzyme elevation'])}\n"
        f"  in {rng.randint(2,5)} patients. Their demand drops {rng.randint(15,30)}% for 2 quarters."
    )

    # Regulatory (late, if category warrants)
    if category in ("regulatory_storm", "disruption") and n_quarters > 8:
        q_reg = rng.randint(7, max(7, min(12, n_quarters)))
        events.append(
            f"Q{q_reg}: Government announces price investigation. Any firm charging >${rng.randint(100,130)}K\n"
            f"  faces public scrutiny. Not a hard cap, but brand damage for premium pricers."
        )

    if category == "steady_growth":
        q_insurance = rng.randint(6, max(6, min(10, n_quarters)))
        events.append(
            f"Q{q_insurance}: A major insurance company announces pilot coverage for SRT.\n"
            f"  Firms with price <${rng.randint(80,95)}K and full Phase III data are eligible.\n"
            f"  Eligible firms see {rng.randint(20,40)}% demand increase."
        )

    # Surprise discovery (random)
    q_surprise = rng.randint(2, n_quarters)
    surprise_firm = rng.choice(firm_ids)
    events.append(
        f"Q{q_surprise}: {names.get(surprise_firm, surprise_firm)} accidentally discovers that their\n"
        f"  compound has a secondary benefit: {rng.choice(['cognitive enhancement', 'joint repair', 'immune system strengthening', 'skin rejuvenation'])}.\n"
        f"  If their marketing spend is >${rng.randint(10,20)}M that quarter, the news spreads.\n"
        f"  Demand for their product specifically increases by {rng.randint(10,20)}%."
    )

    return "\n\n".join(events)


def _generate_market_dynamics(rng, category) -> str:
    awareness_threshold = rng.randint(25, 35)
    brand_premium = rng.randint(55, 70)
    price_war_threshold = rng.randint(15, 25)

    base = f"""Awareness tipping point: When market awareness reaches {awareness_threshold}%,
demand growth ACCELERATES (physician network effects). Before this point,
growth is linear. After, it compounds at 2-3x the previous rate.

Premium segment: Patients with net worth >$10M are highly brand-sensitive.
Firms with brand score >{brand_premium} capture a disproportionate share of
this segment (worth 2-3x the average revenue per patient). Firms below
{brand_premium} brand score are almost invisible to this segment.

Price war dynamics: If the spread between the cheapest and most expensive
firm exceeds ${price_war_threshold}K for 3+ quarters, the expensive firm
loses {rng.randint(5,15)}% market share PER QUARTER to cheaper alternatives.
Physicians start recommending cheaper options explicitly."""

    if category == "disruption":
        base += f"""

DISRUPTION: There is a {rng.randint(15,30)}% chance per quarter that a major
non-pharmaceutical company (tech giant) announces entry into the longevity
space. If this happens, ALL SRT firm equity prices drop 15-25% on the news
(market panic), but actual demand is unaffected for 4+ quarters."""

    return base


def _generate_firm_factors(rng, firm_ids, names, n_quarters, category) -> str:
    factors = []

    for fid in firm_ids:
        name = names.get(fid, fid)
        factor_type = rng.choice([
            "key_scientist", "equipment", "patent", "supply_chain",
            "regulatory_relationship", "talent_advantage",
        ])

        if factor_type == "key_scientist":
            sga_threshold = rng.randint(10, 18)
            q_trigger = rng.randint(4, max(4, min(8, n_quarters)))
            factors.append(
                f"{name} ({fid}): KEY SCIENTIST RISK\n"
                f"  Their lead researcher will leave in Q{q_trigger} if SGA drops below\n"
                f"  ${sga_threshold}M/Q (includes competitive salaries). Loss = -20% R&D\n"
                f"  effectiveness for {rng.randint(3,6)} quarters."
            )
        elif factor_type == "equipment":
            capex_threshold = rng.randint(3, 8)
            q_trigger = rng.randint(5, max(6, min(10, n_quarters)))
            factors.append(
                f"{name} ({fid}): EQUIPMENT AGING\n"
                f"  Manufacturing cold-chain unit will fail in Q{q_trigger} unless capex\n"
                f"  >${capex_threshold}M/Q is maintained. Failure = 50% capacity for 1 quarter."
            )
        elif factor_type == "patent":
            factors.append(
                f"{name} ({fid}): PATENT VULNERABILITY\n"
                f"  If any competitor reaches Gen 2 before them, {rng.randint(20,40)}% chance\n"
                f"  of patent infringement lawsuit. Revenue hit: {rng.randint(15,30)}% for 2Q."
            )
        elif factor_type == "supply_chain":
            factors.append(
                f"{name} ({fid}): SUPPLY CHAIN ADVANTAGE\n"
                f"  Has a backup supplier relationship. If industry supply disruption occurs,\n"
                f"  {name} is unaffected while others lose {rng.randint(10,25)}% capacity."
            )
        elif factor_type == "regulatory_relationship":
            factors.append(
                f"{name} ({fid}): REGULATORY INSIDER\n"
                f"  Strong FDA advisory relationship. {rng.randint(15,25)}% faster path to\n"
                f"  full approval once Phase III completes. Also less likely to receive\n"
                f"  clinical holds."
            )
        elif factor_type == "talent_advantage":
            factors.append(
                f"{name} ({fid}): TALENT MAGNET\n"
                f"  Company culture attracts top talent. R&D effectiveness is {rng.randint(10,20)}%\n"
                f"  higher than peers when R&D spend >${rng.randint(25,40)}M/Q."
            )

    return "\n\n".join(factors)


def _generate_demand_rules(rng, category) -> str:
    return f"""When allocating demand, use these hidden rules:

1. PRICE ELASTICITY is non-linear:
   - $60-80K range: -0.8 elasticity (modest price sensitivity)
   - $80-100K range: -1.5 elasticity (moderate)
   - $100-120K range: -2.5 elasticity (high)
   - >$120K: -4.0 elasticity (very few patients willing to pay this much)

2. BRAND MOMENTUM: A firm whose brand grew last quarter gets a {rng.randint(2,5)}%
   demand bonus. A firm whose brand declined gets a {rng.randint(2,5)}% penalty.
   This creates positive/negative feedback loops.

3. SWITCHING COSTS: {rng.randint(60,80)}% of patients who bought last quarter will
   buy from the same firm this quarter (loyalty), UNLESS another firm is >{rng.randint(10,20)}K
   cheaper or has visibly better quality (Gen 2 vs Gen 1).

4. NEW PATIENT ACQUISITION: New patients (not repeat) are 3x more price-sensitive
   than existing patients. They compare all firms and choose primarily on price.

5. PHYSICIAN INFLUENCE: Firms with customer service rating >7/10 get {rng.randint(5,15)}%
   more physician referrals. Below 5/10, physician referrals DECLINE by {rng.randint(10,20)}%."""


# ─── Accessor ─────────────────────────────────────────────────────────────

def get_available_categories() -> dict[str, str]:
    """Return available template categories with descriptions."""
    return dict(TEMPLATE_CATEGORIES)
