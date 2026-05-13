# Manufacturing & Cost Structure

## Overview

Producing a senolytic regenerative therapy (SRT) is a complex biopharmaceutical
manufacturing process. It combines **small-molecule chemical synthesis** (the senolytic
compound) with **peptide manufacturing** (the telomere-stabilizing component) and
**aseptic fill-finish** (combining, formulating, and packaging the final product).

This document describes the production process, cost structure, and capacity economics
that firms face when deciding capex, production volumes, and pricing.

---

## The Manufacturing Process

### Step 1: Active Pharmaceutical Ingredient (API) Synthesis

**Senolytic compound** (small molecule):
- Synthesized via 6–8 step organic chemistry process.
- Key raw materials: proprietary precursor chemicals sourced from 3–4 specialized
  suppliers (mostly in Switzerland, Japan, and the US).
- Yield: ~60–70% at commercial scale (improves with process R&D).
- Lead time: 8–12 weeks from raw material to purified API.
- Requires GMP-certified chemical synthesis facility.

**Telomere-stabilizing peptide**:
- Produced via solid-phase peptide synthesis (SPPS) or recombinant expression in
  engineered E. coli.
- The peptide is 28 amino acids long, requiring high-purity synthesis.
- Yield: ~40–55% (lower than the small molecule; a key cost driver).
- Lead time: 10–14 weeks.
- Requires specialized peptide manufacturing suite.

### Step 2: Formulation

The two APIs are combined with excipients (stabilizers, buffers, cryoprotectants) into
the final drug product:
- **Gen 1**: Lyophilized (freeze-dried) powder in single-use vials, reconstituted at
  the clinic with sterile saline before IV infusion.
- **Gen 2**: Pre-filled syringe with liquid formulation (if subcutaneous delivery
  is achieved via R&D).
- **Gen 3**: Oral tablet with enteric coating and absorption enhancers (requires
  significant formulation R&D).

### Step 3: Fill-Finish and Packaging

- Aseptic filling in ISO Class 5 cleanroom.
- Each vial/syringe is individually inspected, labeled, serialized.
- Packaged in temperature-controlled shipping containers.
- Shelf life: 24 months at -20°C (Gen 1); future generations target room-temperature
  stability.

### Step 4: Quality Control and Release

- Each batch undergoes 40+ analytical tests (identity, purity, potency, sterility,
  endotoxin, particle count).
- QC testing takes 4–6 weeks.
- Batch failure rate: ~5–8% for Gen 1 (improves with experience and process R&D).
- Failed batches are destroyed -- total loss of materials and labor.

---

## Cost Structure (Gen 1, per treatment course)

A treatment course = 4 quarterly infusions per year. Costs below are per annual course.

| Cost Category | Amount | Notes |
|--------------|--------|-------|
| **Senolytic API** | $3,500 | Raw materials + synthesis labor |
| **Peptide API** | $5,200 | Most expensive component; low yield |
| **Formulation & fill-finish** | $1,800 | Aseptic processing, vials, excipients |
| **Quality control** | $1,200 | Testing, batch release, stability |
| **Batch failure allocation** | $900 | ~7% of batches fail, cost spread across good batches |
| **Shipping & cold chain** | $600 | -20°C logistics, last-mile to clinic |
| **Regulatory compliance** | $400 | Lot tracking, pharmacovigilance reporting |
| **Total COGS per course** | **$13,600** | At commercial scale (>5,000 courses/year) |

### How COGS Varies with Scale

| Annual Production (courses) | COGS/course | Notes |
|----------------------------|------------|-------|
| 500 (minimum viable) | $22,000 | High fixed-cost absorption |
| 2,000 | $17,500 | Some scale benefits |
| 5,000 | $13,600 | Reference commercial scale |
| 15,000 | $10,800 | Bulk purchasing, optimized yields |
| 50,000 | $8,200 | World-class efficiency |
| 200,000+ (Gen 3 oral) | $1,500–3,000 | Completely different manufacturing paradigm |

**Key insight**: COGS falls significantly with scale, but moving from 5,000 to 50,000
courses/year requires massive capex. Firms must decide how aggressively to build
capacity ahead of demand.

### COGS by Generation

| Generation | COGS/course (at scale) | Key Cost Driver Change |
|-----------|----------------------|----------------------|
| Gen 1 | $13,600 | Peptide synthesis yield |
| Gen 2 | $7,500 | Improved peptide yield, simpler formulation |
| Gen 3 | $2,500 | Oral formulation eliminates aseptic fill |
| Gen 4 | $800 | Synthetic biology, commodity-scale production |

---

## Manufacturing Capacity

### What Capacity Means

Capacity is measured in **treatment courses per quarter**. A firm's capacity determines
the maximum number of patients it can supply in any given quarter. Production cannot
exceed capacity.

### Building Capacity

| Facility Type | Capacity (courses/quarter) | Build Cost | Build Time | Annual Maintenance |
|--------------|--------------------------|-----------|-----------|-------------------|
| Pilot plant | 250 | $25 million | Already exists at start | $2M/year |
| Small commercial | 1,500 | $120 million | 4 quarters | $8M/year |
| Standard commercial | 5,000 | $350 million | 6 quarters | $20M/year |
| Large-scale | 15,000 | $800 million | 8 quarters | $40M/year |
| Mega-facility (Gen 3+) | 50,000 | $500 million | 6 quarters | $25M/year |

**Notes**:
- All firms start with a **pilot plant** (250 courses/quarter capacity) -- this
  represents the clinical-trial manufacturing capability converted to commercial use.
- Capacity expansion is **lumpy**: you invest the full build cost upfront (as capex),
  and the capacity comes online after the build time.
- **Capex in the simulation** represents quarterly spending on capacity expansion.
  A $350M facility built over 6 quarters means ~$58M/quarter in capex if spending
  evenly. Firms can choose to spend more or less per quarter.
- Capacity **depreciates**: equipment wears out, requiring reinvestment. Depreciation
  rate is ~2.5% of gross PPE per quarter (10% annually).
- **Capacity cannot be sold** (it is specialized and has no liquid secondary market),
  but it can be idled (reducing maintenance costs by 50%).

### Capacity Utilization and Unit Cost

Running below capacity increases unit cost because fixed costs are spread over fewer
units:

| Utilization | Effective COGS Multiplier | Reason |
|------------|--------------------------|--------|
| >90% | 1.0x (optimal) | Full absorption of fixed costs |
| 70–90% | 1.1x | Moderate under-absorption |
| 50–70% | 1.3x | Significant idle capacity costs |
| 30–50% | 1.6x | Severe under-utilization |
| <30% | 2.0x+ | Most costs are fixed; very inefficient |

---

## Supply Chain Risks

### Raw Material Concentration

- The senolytic precursor chemical is sourced from only 3 global suppliers. A supply
  disruption (factory fire, regulatory action, geopolitical event) could constrain
  production for 2–4 quarters. Firms can mitigate this by holding safety stock
  (increases inventory carrying cost).

### Cold Chain Fragility

- Gen 1 products must maintain -20°C throughout distribution. A cold-chain break
  destroys the product. Roughly 2–3% of product is lost in transit (included in
  COGS above). Gen 3+ products at room temperature eliminate this problem.

### Quality Failures

- A serious quality failure (contaminated batch reaching patients) would trigger:
  - Product recall ($10–50M direct cost depending on scale)
  - FDA clinical hold (1–4 quarters of no sales)
  - Demand shock (patient trust loss)
  This is rare (<1% probability per firm per year) but catastrophic.

---

## What This Means for Firm Decisions

1. **Capex is a long-term bet.** Capacity takes 4–8 quarters to build. If you wait
   for demand to materialize before building, you will miss the window. If you build
   too early, you burn cash on idle capacity.

2. **COGS declines with both scale and technology generation.** The biggest cost
   reductions come from advancing to Gen 2 and Gen 3, not from scaling Gen 1.

3. **Process R&D (distinct from product R&D) reduces COGS.** Improving peptide
   synthesis yields, reducing batch failure rates, and optimizing formulation all
   lower per-unit cost within a given generation.

4. **Working capital matters.** You must purchase raw materials 8–14 weeks before
   selling the final product. This means cash is tied up in inventory. A firm growing
   rapidly needs working capital financing (revolver draws) to bridge the gap.

5. **Capacity is the hard constraint on revenue.** You cannot sell more than you can
   make. Under-investing in capacity means leaving revenue on the table even if demand
   is strong.

6. **The transition from Gen 1 to Gen 3 manufacturing is a paradigm shift.** Gen 1
   is artisanal biopharmaceutical manufacturing. Gen 3 is closer to mass-market
   pharmaceutical tablet production. Firms must plan this transition carefully -- Gen 1
   facilities cannot be easily converted.
