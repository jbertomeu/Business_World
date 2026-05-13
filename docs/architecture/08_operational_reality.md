# Operational Reality: The Living Context

## Why This Matters

Financial statements are summaries. An LLM reading "$28M in R&D expense" does not
know whether that money went toward a promising oral-formulation program that just
cleared a key hurdle, or toward a failing compound that the chief scientist quietly
abandoned. A firm agent reading "market share fell 3 points" does not know whether
patients switched because a competitor launched a subcutaneous version, or because
a viral social-media post showed a paralysis case.

The **operational reality** is the rich, evolving, narrative-level description of
what each firm actually IS -- its product, its people, its facilities, its
reputation -- maintained by the environment agent and the orchestrator as a
living document that updates every quarter.

This layer sits BETWEEN the raw financial numbers and the agent prompts. It makes
the simulation intuitive: agents reason about concrete things (a factory in Basel,
a Phase III trial readout, an angry patient forum post), not abstract accounting
entries.

---

## The Firm Dossier

Every firm has a **dossier** -- a structured document that describes its current
operational reality. The dossier is initialized at firm creation (IPO) and updated
every quarter by the environment agent based on firm actions and market outcomes.

### Dossier Structure

```yaml
firm_dossier:
  firm_id: "firm_0"
  company_name: "Aeterna Therapeutics"    # generated at creation
  incarnation: 1
  founded_quarter: "Q1 2031"
  headquarters: "Cambridge, MA"

  # ── PRODUCT ──────────────────────────────────────────────
  product:
    brand_name: "Revitagen"               # generated at creation
    generation: 1
    delivery_method: "IV infusion (quarterly, 4-6 hours, clinic-administered)"
    active_ingredients:
      senolytic_compound: "AT-401 (proprietary aminoquinoline derivative)"
      telomere_peptide: "TP-28a (28-amino-acid telomerase activator)"
    formulation: "Lyophilized powder, reconstituted in sterile saline, -20C storage"
    dosing_regimen: "One infusion per quarter, 4 per year"
    shelf_life: "24 months at -20C"

    efficacy:
      epigenetic_age_reversal_years: 6.8
      vo2max_improvement_pct: 24
      cognitive_improvement_pct: 12
      onset_of_benefit: "3-4 months"
      durability_if_stopped: "Benefits reverse over 18-24 months"
      non_responder_rate_pct: 5.2

    safety:
      serious_ae_rate_pct: 7.1
      peripheral_neuropathy_rate_pct: 2.9
      autoimmune_flare_rate_pct: 2.5
      severe_fatigue_rate_pct: 1.8
      paralysis_rate_pct: 0.38
      organ_toxicity_rate_pct: 0.28
      death_rate_pct: 0.018
      known_risk_factors: "Higher risk in patients with pre-existing autoimmune conditions"
      black_box_warnings: "Risk of transient motor neuropathy including partial paralysis"

    competitive_positioning: >
      Revitagen is positioned as a premium, science-first product. Its efficacy
      is slightly above the industry average for Gen 1 (6.8 years vs. 6.2 mean),
      but its safety profile is close to average. The company emphasizes its
      rigorous clinical monitoring program and patient support services.

  # ── MANUFACTURING ──────��─────────────────────────────────
  manufacturing:
    facilities:
      - name: "Cambridge Pilot Plant"
        location: "Cambridge, MA"
        type: "pilot"
        capacity_courses_per_quarter: 250
        status: "operational"
        age_quarters: 0
        workforce: 85
        gmp_certified: true
        notes: "Converted from clinical-trial manufacturing. Running at near capacity."

    supply_chain:
      senolytic_precursor_supplier: "Lonza (Basel, Switzerland)"
      peptide_synthesis: "In-house SPPS at Cambridge facility"
      excipient_suppliers: "Merck KGaA (Germany), Sigma-Aldrich (US)"
      cold_chain_logistics: "World Courier (specialized pharma logistics)"
      supply_chain_risk: "moderate -- single-source for key precursor"
      safety_stock_weeks: 6

    unit_economics:
      cogs_per_course: 14200
      cogs_breakdown:
        senolytic_api: 3800
        peptide_api: 5400
        formulation_fill_finish: 1900
        quality_control: 1200
        batch_failure_allocation: 850
        shipping_cold_chain: 600
        regulatory_compliance: 450
      batch_failure_rate_pct: 7.2
      capacity_utilization_pct: 88
      yield_senolytic_pct: 63
      yield_peptide_pct: 48

  # ── WORKFORCE ───────���────────────────────────────────────
  workforce:
    total_employees: 320
    breakdown:
      research_scientists: 85
      process_development: 35
      manufacturing_operations: 85
      quality_assurance: 30
      commercial_sales: 40
      medical_affairs: 20
      general_admin: 25
    key_personnel:
      ceo: "Dr. Sarah Chen (former Genentech VP, cell biology PhD, MIT)"
      cso: "Dr. James Park (led RESET trial consortium, Stanford)"
      cmo: "Dr. Maria Vasquez (former FDA reviewer, 15 years regulatory)"
      cfo: "Michael Torres (former JP Morgan healthcare banking MD)"
    culture: "Academic-oriented, science-first, cautious on commercialization"
    turnover_rate_pct: 8   # low for biotech

  # ── R&D PIPELINE ─────────────────────────────────────────
  rd_pipeline:
    active_programs:
      - name: "AT-501 (Gen 2 compound)"
        stage: "preclinical optimization"
        focus: "Targeted senolytic with reduced Schwann cell toxicity"
        progress_pct: 18
        key_milestone_next: "IND-enabling toxicology studies"
        expected_timeline: "12-16 quarters to conditional approval"
        risk: "medium -- mechanism understood but formulation challenging"

      - name: "Process optimization (Gen 1)"
        stage: "ongoing"
        focus: "Improving peptide synthesis yield from 48% to 60%+"
        progress_pct: 35
        last_quarter_result: "Achieved 51% yield in pilot batch"
        cost_reduction_potential_pct: 8

      - name: "Subcutaneous delivery (Gen 1)"
        stage: "early feasibility"
        focus: "Reformulating AT-401 for self-injection"
        progress_pct: 8
        key_challenge: "Stability at room temperature; reconstitution complexity"
        risk: "high -- may not be feasible with Gen 1 compound"

    phase_3_trial:
      status: "enrolling"
      enrolled: 1200
      target: 5000
      sites: 35
      interim_data: "No unexpected safety signals. Efficacy consistent with Phase II."
      quarterly_cost: 10000000
      expected_completion: "Q4 2033"

  # ── CUSTOMERS & REPUTATION ─────���─────────────────────────
  customers:
    total_active_patients: 740
    patient_demographics:
      median_age: 64
      median_net_worth: 12000000
      geographic_mix: "55% North America, 25% Europe, 15% Middle East, 5% Asia"
    patient_satisfaction:
      overall_score: 7.8   # out of 10
      efficacy_rating: 8.2
      convenience_rating: 5.1   # IV infusion is burdensome
      side_effect_concerns: 6.9
      value_for_money: 6.4
      would_recommend_pct: 72
    notable_feedback:
      positive: "Remarkable energy improvement. I feel 10 years younger."
      negative: "The quarterly clinic visits are disruptive. Wish there were a home option."
      concerning: "A friend had the neuropathy side effect. Made me nervous about continuing."
    physician_sentiment:
      enthusiasm: "moderate-positive"
      main_concern: "Paralysis risk makes referral conversations difficult"
      prescriber_count: 180
      top_prescribing_centers: ["Mass General", "Mayo Clinic", "Cleveland Clinic"]
    adverse_event_history:
      total_serious_ae: 53
      paralysis_cases: 3
      deaths: 0
      media_incidents: 1   # local news story about a paralysis case in Q1

  # ── BRAND & PUBLIC PERCEPTION ────────────────────────────
  brand:
    brand_capital_index: 32   # internal score, 0-100
    public_awareness_pct: 8   # % of target population who know the brand
    media_sentiment: "cautiously positive"
    social_media_mentions_quarterly: 4500
    sentiment_breakdown:
      positive_pct: 45
      neutral_pct: 35
      negative_pct: 20
    recent_coverage:
      - "Nature Medicine profile of Dr. Park and the science behind Revitagen"
      - "Patient testimonial in WSJ: 'I ran my first 10K at 68'"
      - "Local news: 'Cambridge woman reports temporary paralysis after treatment'"
    physician_brand_perception: "Serious science company. Premium product. Safety concerns limit referrals."

  # ── REGULATORY STATUS ───────────���────────────────────────
  regulatory:
    approval_status: "conditional ALT"
    fda_relationship: "cooperative"
    rems_status: "in compliance"
    recent_inspections: "Pre-approval inspection passed with minor observations (Q4 2030)"
    clinical_hold: false
    pending_submissions: "Annual safety report due Q2 2031"
    ip_status: "3 active patents (composition, process, formulation). No challenges pending."
```

### How the Dossier Is Generated

**At firm creation (IPO)**:
The orchestrator generates the initial dossier using:
- A name generator (company name + product brand name)
- The firm's fingerprint (maps to culture, leadership style, strategic emphasis)
- Baseline product specs from Gen 1 world docs (with small random variation)
- A template for starting facilities, workforce, and pipeline

The environment agent then enriches the dossier with a narrative pass:
"Given this firm's profile, write a 1-paragraph company description and
competitive positioning statement."

**Each quarter**:
The environment agent updates the dossier based on what happened:
- Firm actions (R&D spend, capex, marketing, pricing) -> updated pipeline progress,
  capacity changes, workforce growth, brand investment
- Market outcomes (sales volume, market share) -> updated patient counts,
  satisfaction data, physician penetration
- R&D outcomes -> updated pipeline milestones, efficacy/safety improvements
- Events (safety scandal, clinical hold, etc.) -> updated regulatory status,
  adverse event history, media coverage, brand sentiment
- Competitive dynamics -> updated competitive positioning narrative

---

## The Industry Ledger

Beyond individual firms, the environment maintains a **living description of the
industry** as a whole:

```yaml
industry_ledger:
  quarter: "Q2 2031"

  # ── MARKET STATE ─────────────────────────────────────────
  market:
    total_patients_on_therapy: 3850
    total_patients_ever_treated: 4200
    treatment_discontinuation_rate_pct: 8
    waiting_list_patients: ~1200   # patients who want treatment but can't access/afford
    average_price_per_course: 96400
    price_range: [82000, 115000]
    total_industry_revenue_quarterly: 185000000

  # ── PUBLIC HEALTH ────────────────────────────────────────
  public_health:
    total_serious_ae_industry: 285
    total_paralysis_cases_industry: 16
    total_deaths_industry: 1
    fda_safety_database_status: "No class-wide signal detected"
    public_perception: >
      Cautiously optimistic. The paralysis risk dominates media coverage
      but is seen as manageable by most physicians. Patient demand exceeds
      supply at current prices. Advocacy groups are pushing for price
      reduction and insurance coverage.

  # ── REGULATORY CLIMATE ───────────────────────────────────
  regulatory:
    fda_mood: "supportive but watchful"
    congressional_attention: "low (no hearings scheduled)"
    insurance_coverage_status: "No major payer covers SRT yet. CMS studying the issue."
    international: "EMA conditional approval granted to 3 firms. Japan PMDA reviewing."
    pricing_pressure: "Minimal -- too early for government intervention"

  # ── SCIENTIFIC FRONTIER ──────────────────────────────────
  scientific:
    recent_publications: 12   # SRT-related papers this quarter
    notable_findings:
      - "University of Tokyo: new biomarker may predict paralysis susceptibility (preclinical)"
      - "NIH grant awarded for combination therapy study (senolytics + rapamycin)"
    academic_sentiment: "Optimistic about Gen 2 potential. Concern about rushed commercialization."
    conferences_this_quarter: ["AACR Annual Meeting (poster presentations)", "Longevity Summit (keynote by Dr. Park)"]

  # ── COMPETITIVE DYNAMICS ─────────────────────────────────
  competitive:
    market_structure: "Fragmented oligopoly -- 5 firms, no clear leader"
    hhi_index: 2050   # moderate concentration
    price_competition: "limited -- firms competing on quality/brand, not price (yet)"
    capacity_constraint: "Industry-wide capacity ~1300 courses/quarter vs. demand ~1000"
    entry_threat: "Two large-pharma companies (unnamed) rumored to be developing SRT programs"
    substitution_threat: "Caloric restriction mimetics in Phase I -- too early to be a threat"

  # ── LABOR MARKET ─────────────────────────────────────────
  labor:
    talent_availability: "Tight -- senolytic expertise is rare"
    key_bottleneck: "Peptide chemists -- only ~200 qualified globally"
    average_scientist_salary: 185000
    poaching_activity: "moderate -- firms competing for same talent pool"
    university_pipeline: "3-5 years before PhD programs produce enough specialists"

  # ── SUPPLY CHAIN ──��──────────────────────────────────────
  supply_chain:
    precursor_chemical_supply: "adequate but concentrated (3 suppliers)"
    peptide_raw_materials: "stable"
    cold_chain_capacity: "sufficient for current volumes; will need expansion at scale"
    potential_disruptions: "Swiss supplier Lonza has planned maintenance shutdown in Q4 2031"

  # ── INVESTOR SENTIMENT ───────────────────────────────────
  investor_sentiment:
    sector_mood: "bullish with caution"
    recent_capital_flows: "Net $1.2B raised by SRT firms this quarter"
    analyst_consensus: "Long-term opportunity is enormous; near-term profitability unlikely"
    key_investor_concerns: ["Paralysis liability", "Time to Gen 2", "Pricing sustainability"]
    comparable_sector_multiples: "Early-stage SRT trading at 12-18x forward revenue estimates"
```

---

## How the Operational Reality Evolves

### Quarter-by-Quarter Update Process

After the environment agent determines market outcomes (Phase 5), it also produces
dossier and ledger updates. This is part of the environment's reasoning pipeline:

```
Step 1: Environment receives firm actions + market outcomes

Step 2: For EACH firm, update the dossier:
  - Product: If R&D advance occurred, update generation, specs, safety rates.
    If process R&D paid off, update COGS, yields.
  - Manufacturing: If capex spent, update capacity (with build delay noted).
    Update utilization based on production volume.
  - Workforce: Scale headcount roughly with revenue and R&D spending.
    Note key hires or departures (narrative color).
  - R&D Pipeline: Update progress percentages. Add milestones reached.
    Note any setbacks or breakthroughs.
  - Customers: Update patient counts from units sold. Generate satisfaction
    scores based on product quality + service quality + side effect experience.
    Generate notable patient feedback (positive and negative).
  - Brand: Update brand capital from marketing spend + track record.
    Generate media coverage based on events + marketing + outcomes.
  - Regulatory: Update trial enrollment, inspection status, any holds.

Step 3: Update the INDUSTRY LEDGER:
  - Aggregate industry statistics
  - Update public health data (cumulative AEs, deaths, etc.)
  - Update regulatory climate based on events
  - Update competitive dynamics narrative
  - Update investor sentiment based on financial performance and events
  - Note any supply chain changes

Step 4: Generate the quarter narrative:
  This is the "newspaper article" that all agents read. It draws from
  the updated dossiers and ledger to tell a coherent story about what
  happened this quarter.
```

### What Changes vs. What Is Stable

| Element | Update Frequency | Volatility |
|---------|-----------------|-----------|
| Company name, HQ, founding date | Never changes | Fixed |
| Key personnel | Rarely (maybe 1 change per 10 quarters) | Low |
| Product specs (efficacy, safety) | Only on generation advance | Step changes |
| COGS, yields | Quarterly (small changes from process R&D) | Low |
| Capacity | When capex projects complete | Step changes |
| Workforce size | Quarterly (scales with operations) | Low |
| R&D pipeline progress | Quarterly | Medium |
| Patient counts, satisfaction | Quarterly | Medium |
| Brand sentiment | Quarterly | Medium-High (events cause spikes) |
| Media coverage | Quarterly | High (event-driven) |
| Regulatory status | Mostly stable; changes on events | Low normally, high on events |

### Narrative Continuity

The environment agent is prompted to maintain continuity:
- "The company you are describing has existed for N quarters. Its story should
  be consistent with previous quarters."
- "Do not introduce characters, facilities, or events that contradict the
  established dossier."
- "If a firm has been struggling financially, its workforce should show stress
  (hiring freeze, departures). If thriving, it should show growth."
- "Customer satisfaction should correlate with product quality, side effect rates,
  and pricing. Do not fabricate satisfaction scores inconsistent with reality."

---

## What Agents See from the Dossier

### What Firms See About Themselves (always full access)

Each firm sees its own complete dossier. This is their internal view of the company.
They can use it to:
- Understand their own product's strengths and weaknesses
- Plan R&D based on pipeline status
- Assess manufacturing constraints
- Read customer feedback to inform pricing and marketing
- Track their own brand perception

### What Firms See About Competitors (depends on information regime)

| Information Regime | Competitor Dossier Access |
|-------------------|-------------------------|
| `baseline` | Product brand name, generation, delivery method, published efficacy (from trials), approximate safety rate (from public pharmacovigilance data), company description. NOT: COGS, yields, R&D pipeline details, internal satisfaction scores. |
| `full_transparency` | Everything |
| `minimal_disclosure` | Company name, product generation, price only |
| `competitor_intelligence` | Baseline + capacity estimate, total R&D spend, workforce size |

### What Financial Institutions See

| Information Regime | Dossier Access |
|-------------------|---------------|
| `baseline` | Company description, product specs (public), manufacturing capacity (from disclosures), R&D pipeline (summary only -- "pursuing Gen 2"), patient count, published AE data, regulatory status. NOT: unit economics, satisfaction scores, internal pipeline details. |
| `full_transparency` | Everything |
| `asymmetric_banks` | Baseline + COGS breakdown, capacity utilization, R&D pipeline detail (lender due-diligence access) |

### What the Environment Sees

Everything. The environment is omniscient -- it needs the full picture to generate
coherent outcomes.

---

## Customer Ratings in Detail

### How Satisfaction Scores Are Computed

The environment agent computes patient satisfaction scores using a combination of
deterministic factors and LLM-generated narrative:

**Deterministic inputs** (computed by orchestrator, given to environment):

```python
base_satisfaction = (
    0.35 * efficacy_score_normalized      # how well does it work
  + 0.25 * (1 - serious_ae_rate / 0.10)   # how safe (relative to 10% threshold)
  + 0.20 * convenience_score_normalized    # how easy to take
  + 0.10 * (1 - price / 200000)           # value for money (relative to $200K)
  + 0.10 * brand_trust_normalized          # do patients trust this company
)
# Result: 0-10 scale
```

**LLM-enriched narrative** (generated by environment agent):
Given the numerical satisfaction score, the environment generates:
- 2-3 representative patient quotes (positive, neutral, negative)
- Physician sentiment summary
- Notable patient stories (anonymized)
- Social media sentiment description

### Why Satisfaction Matters

1. **Demand feedback**: Higher satisfaction -> higher word-of-mouth -> demand boost
   (modeled as a small positive feedback in the demand system)
2. **Retention**: Patients with satisfaction > 7/10 renew treatment; below 5/10,
   they discontinue or switch
3. **Brand building**: Satisfaction contributes to brand capital accumulation
   (marketing spend is more effective when patients are happy)
4. **Regulatory signal**: Low satisfaction + high AE rate may trigger FDA scrutiny

### How Satisfaction Evolves

| Event | Effect on Satisfaction |
|-------|-----------------------|
| Firm achieves Gen 2 (better efficacy + safety) | +1.0 to +2.0 points |
| Firm achieves subcutaneous delivery | +0.5 to +1.0 (convenience) |
| Price reduction | +0.2 to +0.5 (value for money) |
| Publicized paralysis case (at this firm) | -0.8 to -1.5 |
| Industry-wide safety scandal | -0.3 to -0.5 (guilt by association) |
| Strong marketing campaign | +0.1 to +0.3 (brand trust) |
| Supply shortage (patients can't get treatment) | -0.5 to -1.0 |
| Competitor launches Gen 2 (relative comparison) | -0.2 to -0.5 |

---

## Manufacturing Reality in Detail

### Why We Track This

LLM agents need to understand that "capacity = 250" means something concrete:
a physical facility in Cambridge with 85 people running a GMP line. When the
firm decides to spend $120M on capex, the environment translates that into:
"Aeterna breaks ground on a new commercial manufacturing facility in Research
Triangle Park, NC. Expected to add 1,500 courses/quarter capacity in 4 quarters."

### Facility Lifecycle

```
PLANNING (1 quarter)
  Firm announces capex. Site selected. Permits filed.
  Environment generates: location, name, planned capacity.
  |
CONSTRUCTION (2-6 quarters depending on scale)
  Spending continues. Progress updates in dossier.
  Environment generates: construction milestones, hiring announcements.
  No production capacity yet.
  |
COMMISSIONING (1 quarter)
  Equipment installed. Validation batches running.
  Environment generates: "First batches produced. Awaiting GMP certification."
  Partial capacity available (50%).
  |
OPERATIONAL
  Full capacity. Running costs begin.
  Environment generates: utilization updates, quality metrics.
  |
AGING (after 20+ quarters without reinvestment)
  Equipment wearing out. Batch failure rates increase.
  Environment generates: "Aging equipment at Cambridge plant driving higher failure rates."
  Effective capacity declines unless reinvestment (capex) is applied.
```

### Supply Chain Events

The environment can generate supply chain events that affect specific firms:

| Event | Probability | Effect | Duration |
|-------|------------|--------|----------|
| Supplier maintenance shutdown | ~5%/quarter | -20% capacity for affected firm | 1 quarter |
| Raw material price spike | ~3%/quarter | +10-20% COGS for all firms | 2-4 quarters |
| Cold chain failure (product loss) | ~2%/quarter/firm | Lost inventory (1 batch) | Immediate |
| Quality failure (batch rejection) | ~5-8%/quarter/firm | Already in COGS; dossier narrative | Immediate |
| Supplier bankruptcy | ~0.5%/quarter | -30% capacity until alternative found | 2-4 quarters |

These events appear in the firm dossier and the industry ledger, giving agents
concrete context for their decisions.

---

## Personnel and Culture

### Why We Track This

A firm that has been losing money for 4 quarters will have different internal
dynamics than one that just reported record revenue. The dossier captures this:

- **Growing firm**: "Aeterna added 45 employees this quarter, primarily in
  commercial and manufacturing roles. The company opened a new R&D center in
  San Diego."
- **Struggling firm**: "Aeterna announced a 15% workforce reduction, affecting
  primarily commercial staff. CSO Dr. Park reportedly in discussions with a
  competitor about a move."
- **Stable firm**: "No significant personnel changes. Employee satisfaction
  survey results: 7.2/10 (industry average: 6.8)."

### Key Personnel Events

The environment may generate personnel events:

| Event | Trigger | Effect |
|-------|---------|--------|
| Key hire | Firm growing rapidly + high SGA | +brand, +narrative color |
| Key departure | Firm struggling financially | -brand, possible R&D slowdown |
| CEO replaced | Sustained poor performance (4+ quarters of losses) | New fingerprint element, strategy shift |
| Whistleblower | Very low quality + high AE rate | Regulatory scrutiny, media coverage |
| Award/recognition | Top R&D performance | +brand, +physician perception |

---

## How This Feeds Into Agent Prompts

### Firm Agent Prompt (excerpt)

```
=== YOUR COMPANY: AETERNA THERAPEUTICS ===

You are the management team of Aeterna Therapeutics, a Cambridge-based
biopharmaceutical company commercializing Revitagen, a Gen 1 senolytic
regenerative therapy.

PRODUCT STATUS:
  Revitagen (AT-401 + TP-28a): IV infusion, quarterly dosing
  Efficacy: 6.8 years epigenetic age reversal (above industry average of 6.2)
  Safety: 7.1% serious AE rate (industry average: 7.3%)
  Paralysis risk: 0.38% (3 cases in 740 patients treated)
  Patient satisfaction: 7.8/10

MANUFACTURING:
  Cambridge Pilot Plant: 250 courses/quarter, running at 88% utilization
  Unit cost: $14,200/course (peptide yield is the bottleneck at 48%)
  Last quarter's quality: 1 batch rejection out of 14 (7.2% failure rate)

R&D PIPELINE:
  AT-501 (Gen 2 compound): 18% complete, preclinical stage
    Key next step: IND-enabling toxicology studies
  Process optimization: 35% complete, recently achieved 51% peptide yield
  Subcutaneous delivery: 8% complete, early feasibility -- high risk

CUSTOMERS:
  740 active patients (55% North America, 25% Europe)
  72% would recommend to others
  Main complaint: "Clinic visits are disruptive"
  180 prescribing physicians

BRAND & REPUTATION:
  Brand index: 32/100
  Media: Cautiously positive. Recent coverage includes a patient success
  story in WSJ and a local news report on a paralysis case.
  Physician perception: "Serious science company, premium product"

COMPETITIVE LANDSCAPE:
  [summaries of competitor dossiers, filtered by information regime]

RECENT EVENTS:
  [from industry ledger and environment narrative]
```

### Financial Institution Prompt (excerpt)

```
=== FIRM UNDER REVIEW: AETERNA THERAPEUTICS (firm_0) ===

Company: Cambridge, MA. Conditional ALT approval. Gen 1 product "Revitagen."
Founded Q1 2031. 2 quarters of operations.

PRODUCT: IV infusion, quarterly. 6.8yr efficacy (above avg). 7.1% serious
AE rate (average). 3 paralysis cases / 740 patients (0.4%).

OPERATIONS: 250 courses/quarter capacity (88% utilized). COGS $14,200/course.
Peptide yield bottleneck at 48%.

R&D: Gen 2 compound AT-501 at 18% progress (preclinical). Process improvement
showing early results (yield improvement).

MARKET POSITION: 740 patients, 21.7% market share. Patient satisfaction 7.8/10.
72% recommend. 180 prescribers.

REPUTATION: Brand index 32/100. Cautiously positive media. One local paralysis
news story.

FINANCIALS: [from published financial statements per measurement regime]
```

### Environment Agent Prompt (excerpt)

```
=== FIRM DOSSIERS (complete) ===

[Full dossier for each of the 5 firms -- the environment sees everything]

=== INDUSTRY LEDGER ===

[Full ledger with market state, public health, regulatory climate, etc.]

=== FIRM ACTIONS THIS QUARTER ===

[All firm decisions: pricing, production, R&D allocation, capex, marketing]

=== YOUR TASK ===

Update the dossiers and industry ledger based on this quarter's actions and
outcomes. Maintain narrative continuity. For each firm:
1. Update product specs if R&D advances occurred
2. Update manufacturing (capacity changes, utilization, yields)
3. Update patient counts and satisfaction
4. Update R&D pipeline progress
5. Update brand and media coverage
6. Note any personnel or supply chain developments

Then determine market outcomes and write the quarter narrative.
```

---

## Storage and Synchronization

### Where the Dossier Lives

- The **canonical version** lives in the orchestrator (as a YAML/JSON structure)
- After each quarter, the orchestrator sends updated dossiers to agents via `POST /sync`
- Each agent receives only the dossier content allowed by the information regime
- The environment agent receives all dossiers (full) and returns updated versions

### Dossier Size Management

A full dossier is ~5-10 KB of YAML. With 5 firms + industry ledger, that is ~60 KB.
Over 80 quarters, the historical dossiers would be ~5 MB total.

For prompt inclusion:
- **Current quarter dossier**: included in full (~10 KB per firm)
- **Historical dossiers**: NOT included in prompts. Instead, the agent's memory
  system stores key changes and the analyst tools can query "what was my satisfaction
  score 4 quarters ago?"
- **Industry ledger**: current quarter only (~5 KB)

### Archival

All dossier versions are saved in the run output:
```
outputs/{run_id}/dossiers/
  firm_0/
    Q1_2031.yaml
    Q2_2031.yaml
    ...
  firm_1/
    ...
  industry_ledger/
    Q1_2031.yaml
    ...
```

This archive is valuable for post-simulation analysis and for feeding into
future agents as historical context.

---

## Configuration

### Dossier Generation Settings

```yaml
operational_reality:
  generate_company_names: true          # false = use "Firm 0", "Firm 1", etc.
  generate_product_names: true
  generate_personnel_names: true
  personnel_event_probability: 0.05     # per firm per quarter
  supply_chain_event_probability: 0.03
  satisfaction_update_method: "formula_plus_narrative"  # or "formula_only"
  dossier_detail_level: "full"          # "full" | "summary" | "minimal"
  industry_ledger_detail: "full"
```

### Minimal Mode (for fast runs / testing)

In minimal mode, dossiers are reduced to key numbers only (no narrative, no
personnel, no customer quotes). This speeds up the environment agent's update
task and reduces prompt sizes.

```yaml
operational_reality:
  dossier_detail_level: "minimal"
  # Dossier includes: product generation, COGS, capacity, patient count,
  # satisfaction score, brand index. No narrative text.
```
