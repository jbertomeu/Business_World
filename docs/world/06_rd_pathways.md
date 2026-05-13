# R&D Pathways and Innovation

## How R&D Works in This Simulation

Research and development is the primary mechanism by which firms improve their products,
reduce manufacturing costs, and build long-term competitive advantage. R&D spending each
quarter contributes to **R&D capital** -- an intangible asset that accumulates over time
and determines when (and whether) a firm achieves the next technology generation.

---

## The R&D Pipeline

### Three Parallel Research Programs

Each firm can invest in three distinct R&D programs simultaneously. Resources (dollars)
are allocated across these programs each quarter:

#### 1. Product R&D (Efficacy & Safety)

**Goal**: Develop the next-generation SRT compound with better efficacy and fewer
side effects.

**What it produces**:
- Progress toward Gen 2, Gen 3, and Gen 4 compounds.
- Each generation requires crossing a **cumulative R&D investment threshold** (see below).
- Progress is NOT guaranteed -- there is a stochastic element. More spending increases
  the probability of success but does not guarantee it.

**Key milestones**:

| Transition | Cumulative Investment Required | Success Probability | Expected Timeline |
|-----------|-------------------------------|--------------------|--------------------|
| Gen 1 -> Gen 2 | $400M–$600M | 80% once threshold reached | 12–16 quarters |
| Gen 2 -> Gen 3 | $800M–$1.2B | 65% once threshold reached | 12–20 quarters |
| Gen 3 -> Gen 4 | $1.5B–$2.5B | 50% once threshold reached | 16–24 quarters |

**How the stochastic element works**:
Each quarter, if cumulative product R&D spending exceeds the minimum threshold for
the next generation, the environment draws a success check:
```
P(success this quarter) = base_rate * (cumulative_spend / threshold)^0.5
```
Where `base_rate` is ~10–15% per quarter once the minimum is met. Spending well
beyond the threshold increases the probability but with diminishing returns.

If the check fails, spending is not lost -- it continues to count toward future
checks. But it means a firm could spend $600M and still not achieve Gen 2 for
several additional quarters, while a luckier competitor might succeed at $450M.

**When a generation advance occurs**:
- The firm's product quality scores (efficacy, safety) jump to the new generation's
  parameters.
- The firm must retool its manufacturing process (1–2 quarters of reduced capacity
  during changeover).
- The firm can market the new generation immediately.
- Competitors can observe the advance (it becomes public knowledge).

#### 2. Process R&D (Cost Reduction)

**Goal**: Reduce manufacturing cost (COGS) within the current generation through
process improvements.

**What it produces**:
- Incremental COGS reduction: each $50M invested reduces COGS by ~3–5% (diminishing
  returns beyond $200M cumulative per generation).
- Improvements include: better synthesis yields, lower batch failure rates, faster
  cycle times, raw material substitution.

**Key parameters**:

| Investment Level (cumulative per generation) | COGS Reduction | Notes |
|---------------------------------------------|---------------|-------|
| $0–$50M | 0–5% | Low-hanging fruit |
| $50M–$100M | 5–12% | Meaningful optimization |
| $100M–$200M | 12–18% | Approaching diminishing returns |
| $200M+ | 18–22% max | Hard floor -- need next gen for more |

**Process R&D does NOT help achieve the next generation** -- it only reduces cost
within the current one. A firm must invest in Product R&D to advance generations.

#### 3. Delivery R&D (Convenience)

**Goal**: Improve the administration route and patient experience.

**What it produces**:
- Progress toward subcutaneous injection (Gen 2 delivery), oral formulation (Gen 3),
  or one-time treatment (Gen 4).
- Delivery advances can be achieved independently of product compound advances,
  but they are harder to achieve without the corresponding compound chemistry.

**Key milestones**:

| Transition | R&D Investment | Difficulty | Standalone Possible? |
|-----------|---------------|-----------|---------------------|
| IV -> Subcutaneous | $100M–$200M | Moderate | Yes (with Gen 1 compound) |
| Subcutaneous -> Oral | $300M–$500M | High | Requires at least Gen 2 compound |
| Oral -> One-time gene therapy | $800M–$1.5B | Very High | Requires Gen 3+ compound |

**Strategic note**: A firm could achieve subcutaneous delivery for its Gen 1 compound
before a competitor achieves Gen 2. This gives a convenience advantage even with
inferior efficacy/safety -- and can be very valuable in the early market where
clinic visits are a major barrier.

---

## R&D Spending: Practical Guidance

### Quarterly R&D Budget Ranges

| Strategy | Quarterly R&D Spend | Annual | Characteristic |
|---------|-------------------|--------|---------------|
| Minimal | $5–10M | $20–40M | Mandatory Phase III only; no advancement |
| Conservative | $15–25M | $60–100M | Slow but steady progress toward Gen 2 |
| Moderate | $30–50M | $120–200M | Competitive timeline for Gen 2 |
| Aggressive | $60–100M | $240–400M | Fast-track Gen 2; accelerate Gen 3 |
| Moonshot | $100M+ | $400M+ | Racing to leapfrog; very capital-intensive |

**Remember**: $10M/quarter is the mandatory Phase III cost (non-discretionary).
Any R&D spending above that is the firm's strategic choice.

### Allocation Across Programs

There is no "right" split, but common strategies include:

| Strategy | Product R&D | Process R&D | Delivery R&D |
|---------|------------|------------|-------------|
| Balanced | 50% | 25% | 25% |
| Efficacy-first | 70% | 20% | 10% |
| Cost leader | 30% | 55% | 15% |
| Convenience play | 30% | 15% | 55% |

**Firms must specify their R&D allocation each quarter.** The environment tracks
cumulative investment in each program separately.

---

## R&D Spillovers and Knowledge

### Public Knowledge

When any firm achieves a generation advance, certain knowledge becomes public:
- The fact that the advance is possible (eliminates scientific uncertainty for others).
- General approach (not specific formulation).
- This reduces the remaining R&D cost for competitors by ~15–20% (they can learn
  from published literature and reverse-engineer the general approach).

### No Explicit Technology Sharing

Firms do not license or share technology in this simulation. Each must develop its
own formulation and process. (This could be added as a future extension.)

### Academic Breakthroughs (Environment Shocks)

The environment may occasionally generate an "academic breakthrough" shock:
- An open-access scientific publication that advances understanding.
- Reduces all firms' R&D cost for the next generation by 10–20%.
- Probability: ~5% per quarter.
- This is a windfall that rewards firms already investing in R&D (they are closer
  to the threshold) and doesn't help firms that have stopped investing.

---

## R&D Risks

### Failure Modes

1. **Clinical failure**: A Gen 2 candidate turns out to have unexpected toxicity in
   expanded testing. The firm must abandon this compound and restart with a new one.
   - Probability: embedded in the success check (the 20–50% failure probability).
   - Cost: cumulative investment in that failed candidate is partially lost (50% of
     spending contributes to the next attempt, 50% is sunk).

2. **Manufacturing translation failure**: The new compound works in the lab but
   cannot be manufactured at commercial scale at acceptable cost.
   - Probability: ~10% per generation advance.
   - Cost: 1–2 quarter delay + $50–100M additional process R&D.

3. **Regulatory rejection**: The FDA doesn't approve the new generation based on the
   data submitted.
   - Probability: ~5–10% per generation advance.
   - Cost: 2–4 quarter delay while additional data is generated.

### The "R&D Trap"

A firm can fall into an R&D trap by:
- Spending aggressively on R&D while competitors also spend aggressively -> no
  lasting advantage, just mutual cash burn.
- Spending so much on R&D that it cannot fund marketing and operations -> great product
  with no patients.
- Pursuing Gen 3 before Gen 2 is commercially established -> no revenue base to fund
  the continued R&D investment.

The optimal R&D strategy depends on competitors' strategies, current market conditions,
and the firm's financial position.

---

## Technology Evolution: What Firms Are Racing Toward

### The "Golden Product" (Gen 3–4)

The ultimate competitive position is a product that is:
- **Highly effective** (15+ years of age reversal)
- **Very safe** (<0.5% serious AE rate)
- **Convenient** (oral or one-time)
- **Cheap to produce** (COGS < $2,000/course)

This product can be priced at $5,000–$15,000 per year and serve hundreds of millions
of patients. The firm that gets there first (or close to first) with adequate
manufacturing capacity captures a market worth hundreds of billions of dollars annually.

### The Race Dynamics

- **First-mover advantage in R&D is real but not decisive.** Being 2–4 quarters
  ahead in R&D matters, but a competitor can catch up (especially with public
  knowledge spillovers).
- **Speed vs. capital efficiency**: Spending $100M/quarter on R&D gets you there
  faster but requires massive financing. A firm spending $30M/quarter gets there
  eventually at lower risk.
- **The financial market rewards R&D leadership** -- equity prices reflect expected
  future cash flows, and a firm closer to Gen 2/3 commands a premium.

---

## What Firms Should Remember

1. **R&D is not optional.** A firm that does not invest beyond mandatory Phase III
   will be selling Gen 1 products while competitors sell Gen 2 and Gen 3. Its margin
   will shrink and its market share will evaporate.

2. **R&D is not revenue.** Dollars spent on R&D do not generate revenue this quarter.
   The payoff is 3–5 years away. You must finance the gap with operating income,
   equity, or debt.

3. **Allocate deliberately.** Don't spread R&D evenly across all programs without
   thought. Choose a focus -- efficacy, cost, or convenience -- based on your strategy.

4. **Watch competitors' R&D.** If a competitor achieves Gen 2 and you haven't,
   you will lose market share rapidly. The financial-market agent will also devalue
   your equity.

5. **R&D has diminishing returns within a generation.** Once you've reduced Gen 1
   COGS by 20%, further spending on process R&D has minimal effect. Shift resources
   to the next generation.
