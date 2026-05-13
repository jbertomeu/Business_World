# Market & Demand

## Market Structure

The SRT market is a **differentiated oligopoly** with 5 firms. Products are
substitutes but not identical -- they differ in efficacy, safety, convenience, and
brand reputation. Patients (and their physicians) choose among available products
based on these attributes and price.

---

## Demand System

Demand is modeled as a **multinomial logit** system, a standard model of differentiated
product competition used in industrial organization economics.

Each quarter, a population of potential patients makes a choice:
- Buy from Firm 1, Firm 2, ... Firm 5, or
- Buy nothing (the "outside option").

The probability that a patient chooses Firm *i* depends on:

```
Utility_i = a * quality_i - b * price_i + g * brand_i + xi_i + eps_i
```

Where:
- `quality_i` = **safety-adjusted** composite quality score (see below)
- `price_i` = annual treatment price
- `brand_i` = accumulated brand capital (from marketing and track record)
- `xi_i` = firm-specific taste shock (random, drawn each quarter; std dev = 0.05)
- `eps_i` = individual patient taste shock (Type I extreme value -- creates the logit)

The **outside option** utility is:
```
Utility_0 = V_0(t) + macro_shock + eps_0
```

Where `V_0(t)` captures the baseline reluctance to adopt (starts at 3.5, decays
by 0.03/quarter as awareness grows, floor at 0.5) and `macro_shock` represents
aggregate demand shocks (std dev = 0.08).

### Quality Score and Safety Adjustment

The quality score entering the utility function is:

```
raw_quality = w_eff(t) * efficacy_index + w_saf(t) * safety_index + w_con(t) * convenience_index
effective_quality = raw_quality * ae_demand_modifier(serious_ae_rate)
```

Where the **ae_demand_modifier** scales demand based on the firm's serious adverse
event rate -- a critical multiplier that captures the public's fear of side effects:

| Serious AE Rate | Modifier | Interpretation |
|-----------------|----------|----------------|
| > 5% | 0.5x | "Experimental, risky" |
| 3-5% | 0.7x | "Promising but dangerous" |
| 1-3% | 1.0x | "Acceptable" (baseline) |
| 0.5-1% | 1.3x | "Safe enough for broad adoption" |
| < 0.5% | 2.0x | "Routine medical procedure" |
| < 0.1% | 3.0x | "Over-the-counter safe" |

The quality weights shift over time (early market values efficacy most; mature
market values convenience and safety most):

| Period | w_eff | w_saf | w_con |
|--------|-------|-------|-------|
| Years 1-3 | 0.50 | 0.30 | 0.20 |
| Years 4-7 | 0.35 | 0.40 | 0.25 |
| Years 8-12 | 0.25 | 0.40 | 0.35 |
| Years 13-20 | 0.20 | 0.35 | 0.45 |

See doc 09 (Parameters and Calibration) for all numeric parameters including
the demand coefficients (a=1.0, b=0.000015, g=0.4) and stock accumulation rates.

### What This Means Intuitively

- **Lower prices attract more patients**, but with diminishing returns (you can't
  capture 100% of the market with low prices alone).
- **Higher quality attracts more patients**, and quality differences matter more than
  price differences for wealthy early adopters.
- **Brand matters**: patients are nervous about a new therapy. A firm with a strong
  brand (built through marketing and a good safety track record) is preferred over
  an unknown competitor, all else equal.
- **Random shocks prevent deterministic outcomes**: even with identical products and
  prices, market shares fluctuate quarter to quarter.

---

## Market Size Over Time

The total addressable market grows as the product improves and awareness spreads.

### Potential Patient Pool (global, adults 50+)

| Year | Awareness Rate | Willing if Affordable | Implied Addressable |
|------|---------------|----------------------|-------------------|
| 2031 (start) | 15% | 5% of aware | ~4,500,000 |
| 2033 | 35% | 12% of aware | ~25,200,000 |
| 2036 | 60% | 25% of aware | ~90,000,000 |
| 2040 | 80% | 45% of aware | ~216,000,000 |
| 2045 | 95% | 70% of aware | ~399,000,000 |
| 2050 | 98% | 85% of aware | ~499,800,000 |

**But affordability is the binding constraint.** The "addressable" market is only
the subset that can and will pay the prevailing price.

### Demand as a Function of Price (Gen 1 quality, Year 1)

| Price Point (annual) | Patients Who Would Buy | Revenue Potential |
|---------------------|----------------------|------------------|
| $200,000 | ~40,000 | $8.0B |
| $150,000 | ~75,000 | $11.3B |
| $100,000 | ~180,000 | $18.0B |
| $80,000 | ~300,000 | $24.0B |
| $50,000 | ~800,000 | $40.0B |
| $30,000 | ~2,500,000 | $75.0B |
| $10,000 | ~15,000,000 | $150.0B |
| $5,000 | ~40,000,000 | $200.0B |

**The revenue-maximizing price depends on your cost structure and competitors' prices.**
At Gen 1 COGS of $13,600/course, pricing below ~$30,000 sacrifices margin. But a firm
with Gen 3 COGS of $2,500 can profitably serve at $10,000 and capture enormous volume.

### Market Growth Drivers

1. **Product improvement** (lower side effects -> more people willing to try)
2. **Price reduction** (lower COGS -> lower prices -> larger addressable market)
3. **Awareness** (grows naturally over time + accelerated by marketing)
4. **Reimbursement** (government/insurance coverage -- uncertain, may arrive mid-sim)
5. **Demographic aging** (the 50+ population grows ~1.5% annually)

### Market Contraction Risks

1. **Safety scandal** (paralysis/death event -> industry-wide demand drop 20–40%
   for 2–4 quarters)
2. **Regulatory tightening** (new requirements -> reduced supply or suspended sales)
3. **Recession** (macro shock -> discretionary healthcare spending cut 10–25%)
4. **Competitor substitute** (non-SRT longevity approach, e.g., caloric restriction
   mimetic, captures some demand)

---

## Geographic Segments

The global market breaks into distinct regions with different characteristics:

| Region | Share of Addressable | Price Sensitivity | Regulatory | Growth Rate |
|--------|---------------------|-------------------|-----------|------------|
| North America | 35% | Low (premium market) | FDA (ALT pathway) | Moderate |
| Europe | 25% | Medium | EMA (slower approval) | Moderate |
| East Asia (Japan, Korea, China) | 25% | Medium-High | Variable by country | High |
| Middle East & Gulf | 8% | Very Low (ultra-premium) | Fast-track | Moderate |
| Rest of World | 7% | Very High | Variable | Low initially |

**In the simulation**, geographic segments are abstracted -- firms compete in a single
global market, but demand shocks may reflect regional events (e.g., "China approves
reimbursement" -> demand surge; "EU safety review" -> regional demand drop).

---

## Brand Capital and Marketing

### How Brand Works

Brand capital accumulates over time based on:
- **Marketing spend** (SGA): Direct-to-consumer advertising, physician education,
  medical conference presence.
- **Track record**: Quarters of operation without serious safety incidents.
- **Word of mouth**: Satisfied patients generate organic demand (modeled as a
  small positive feedback on quality * patient base).

Brand **depreciates** at ~10% per quarter if a firm stops marketing. It can also
**crash** if the firm experiences a publicized safety event.

### Marketing Effectiveness

| Quarterly SGA Spend | Brand Capital Gain | Notes |
|--------------------|-------------------|-------|
| $0 | -10% of current brand | Brand decays without maintenance |
| $5M | Maintenance (0% net) | Holds current position |
| $10M | +5% brand growth | Moderate investment |
| $25M | +10% brand growth | Aggressive campaign |
| $50M+ | +12% brand growth | Diminishing returns above $50M |

**Marketing is more effective when product quality is higher.** Advertising a product
with 7% serious AE rate is less persuasive than advertising one with 2% AE rate.

### Physician Influence

In the early market (2031–2036), ~70% of treatment decisions are physician-influenced.
Physician education (part of SGA) is therefore more important than consumer advertising
early on. As the market matures and patient awareness grows, direct-to-consumer
marketing becomes relatively more important.

---

## Price Competition Dynamics

### Price Elasticity

The market is **relatively inelastic at high prices** (wealthy early adopters are not
price-sensitive) but **highly elastic in the mid-range** (the "affordability cliff"
where millions of patients enter or exit based on small price changes).

Rough price elasticities by segment:
- Ultra-wealthy: -0.3 (very inelastic)
- High-net-worth: -0.8 (moderately inelastic)
- Affluent: -1.5 (elastic)
- Upper-middle: -2.5 (very elastic)
- Mass market: -4.0+ (hyper-elastic)

### Strategic Implications

1. **Early years (Gen 1)**: Price high ($80K–$150K), serve the wealthy, maximize
   margin per patient. Volume is constrained by capacity anyway.

2. **Mid-years (Gen 2)**: Lower prices to $30K–$60K as COGS drops, capture the
   affluent segment. Volume growth drives revenue even as margin per unit declines.

3. **Late years (Gen 3+)**: Price at $5K–$15K, serve the mass market. Volume is
   enormous. The winner is the firm with the lowest COGS and broadest distribution.

4. **Undercutting is risky**: Cutting price below COGS to gain share is suicidal.
   The financial market will punish unprofitable pricing with lower equity valuations
   and tighter credit.

---

## Demand Shocks (Environment-Generated)

Each quarter, the environment draws random shocks that affect demand:

### Macro Demand Shock (affects all firms equally)
- Mean: 0, Std Dev: 0.08
- Represents: economic conditions, media coverage, regulatory mood
- Range: roughly -20% to +20% in extreme quarters

### Firm-Specific Taste Shock (xi_i)
- Mean: 0, Std Dev: 0.05
- Represents: word of mouth, physician preference shifts, regional variation
- Independent across firms

### Safety Event Shock (rare but large)
- Probability: ~3% per firm per quarter of a "publicized adverse event"
- Effect: -15% to -40% demand for that firm for 2–4 quarters
- Industry spillover: other firms also lose 5–10% demand (guilt by association)

These shocks ensure that outcomes are not purely deterministic, even when firms make
similar decisions.

---

## What Firms Should Consider

1. **You are creating the market, not just competing in it.** Early investment in
   R&D and marketing grows the total pie, benefiting everyone -- but benefiting you
   most if you lead.

2. **Price is a strategic choice, not just a margin calculation.** Pricing below
   competitors signals aggression and may trigger a price war. Pricing above signals
   premium quality but risks losing volume.

3. **Demand is noisy.** Don't overreact to a single bad quarter. Look at trends
   over 4–8 quarters before concluding your strategy isn't working.

4. **The outside option is your biggest competitor initially.** Most potential patients
   are choosing "do nothing" -- not choosing a rival firm. Your marketing and pricing
   should focus on converting non-adopters, not just stealing share from competitors.

5. **Market share is sticky but not permanent.** Patients who start on one firm's
   product tend to stay (switching costs are real -- new titration, monitoring). But a
   clearly superior product will overcome switching costs within 2–3 quarters.
