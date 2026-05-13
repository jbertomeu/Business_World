# World Overview: The Senolytic Revolution

## Document Purpose

This document describes the world in which you (an LLM agent) operate as either a
pharmaceutical firm, a financial-market intermediary, or the market environment.
Everything here is shared knowledge -- all agents have access to this context.

**Configurable parameters**: The number of firms (default 5), number of quarters
(default 80), and starting mode (public or private) are set by the user before
the simulation begins. Firms produce a **single product** (senolytic regenerative
therapy, SRT) and compete in a **single global market** (no regional segmentation).
Various complexity features (M&A, leasing, stock compensation, etc.) can be toggled
on or off per run -- see the simulation configuration for what is active.

The default simulation begins in **Q1 2031** and runs for up to **80 quarters
(20 years)** through Q4 2050.

---

## The Breakthrough (2028–2030)

In late 2028, a consortium of university labs published simultaneous results confirming
that a class of small-molecule compounds -- **senolytics** -- could reliably clear
senescent cells from human tissue and, when combined with **telomere-stabilizing
peptides**, produce measurable reversal of biological aging in Phase II clinical trials.

Key findings from the landmark "RESET" trial (published *Nature Medicine*, March 2029):

- **Biological age reduction**: Participants aged 60–75 showed an average 8.2-year
  reduction in epigenetic age (Horvath clock) after 12 months of treatment.
- **Functional improvement**: 40% improvement in grip strength, 25% improvement in
  VO2max, measurable cognitive gains on standardized tests.
- **Serious adverse events**: 7.3% of participants experienced Grade 3+ adverse events,
  including transient peripheral neuropathy (3.1%), autoimmune flares (2.4%), and
  severe fatigue requiring hospitalization (1.8%).
- **One case of partial limb paralysis** (0.4%) -- temporary but lasting 4 months,
  generating significant media attention and regulatory concern.

By mid-2029, the FDA created a new **Accelerated Longevity Therapy (ALT)** regulatory
pathway, acknowledging that traditional disease-specific endpoints were inadequate for
therapies targeting biological aging itself.

In 2030, the first three companies received **conditional ALT approval** for
first-generation senolytic-telomere combination therapies. Two more firms are entering
in early 2031. The simulation begins with **five firms** holding ALT-conditional
approval and preparing to commercialize.

---

## The State of the World in Q1 2031

### Demographics and Demand

The world population is 8.3 billion. The therapy is initially relevant to adults over
age 50 in high-income countries -- roughly **600 million people**. However, at launch
prices ($80,000–$150,000/year), the realistic addressable market is far smaller:

| Segment | Population | Willingness to Pay (annual) | Penetration Year 1 |
|---------|-----------|---------------------------|-------------------|
| Ultra-high-net-worth (>$30M) | ~300,000 | >$200,000 | 15–25% |
| High-net-worth ($5M–$30M) | ~3,000,000 | $80,000–$150,000 | 3–8% |
| Affluent ($1M–$5M) | ~25,000,000 | $30,000–$80,000 | <1% (priced out) |
| Upper-middle-class | ~120,000,000 | $5,000–$30,000 | 0% (priced out) |
| Mass market | ~450,000,000 | <$5,000 | 0% (priced out) |

**Key insight for firms**: The initial market is small but extremely high-value.
As manufacturing costs fall and side-effect profiles improve, lower price points unlock
dramatically larger segments. The firm that first achieves a safe, affordable product
captures an enormous market.

### Macroeconomic Backdrop

- **Global GDP growth**: ~2.8% annually (moderate).
- **Risk-free rate**: ~4.0% annualized (1.0% per quarter) at simulation start, subject
  to shocks.
- **Inflation**: ~2.5%, stable.
- **Healthcare spending**: Rising as a share of GDP in all OECD countries. Governments
  are debating whether longevity therapies should be covered by public insurance -- no
  consensus yet.
- **Capital markets**: Biotech is a hot sector. Investors are eager but scarred by
  previous biotech busts (2021–2022 drawdowns). They demand evidence of commercial
  viability, not just scientific promise.

### Competitive Landscape

Five firms enter the simulation. Each has:
- ALT-conditional approval for a first-generation product,
- Access to the same underlying scientific knowledge,
- Different starting capabilities (drawn randomly -- see agent fingerprints),
- Zero balance sheet (must raise capital via IPO before operating).

No firm has a dominant position. The market is a **nascent oligopoly** -- competition
is fierce but the pie is growing.

### Technology Trajectory (What Firms Know)

The scientific community broadly agrees on the development roadmap:

| Generation | Timeline | Efficacy | Side Effects | Est. COGS/dose | Key Advance |
|-----------|----------|----------|-------------|----------------|------------|
| Gen 1 (current) | 2031–2034 | 5–8 yr age reversal | 7% serious AE | $15,000–$25,000 | Basic senolytic + telomere stabilizer |
| Gen 2 | 2034–2038 | 10–15 yr reversal | 3% serious AE | $5,000–$12,000 | Targeted delivery, reduced off-target |
| Gen 3 | 2038–2043 | 15–20 yr reversal | <1% serious AE | $1,500–$4,000 | Oral formulation, synthetic biology |
| Gen 4 | 2043–2050 | 20+ yr reversal | <0.3% serious AE | $300–$1,000 | Gene therapy adjunct, one-time dosing |

**This roadmap is NOT guaranteed.** R&D investment determines whether and when each
generation becomes available. A firm that underinvests in R&D will be stuck selling
Gen 1 products while competitors advance. A firm that overinvests may burn through cash
before the technology matures.

### Risks and Uncertainties

1. **Regulatory risk**: The ALT pathway is new and politically contentious. A serious
   adverse event (paralysis, death) could trigger a clinical hold, pausing sales for
   1–4 quarters.
2. **Reimbursement risk**: If governments mandate coverage, prices may be capped but
   volumes explode. If they refuse, the market stays small and premium.
3. **Scientific risk**: Gen 2+ advances may prove harder than expected. Some R&D
   programs will fail.
4. **Public perception**: Media coverage of side effects can crater demand. A "paralysis
   scandal" could reduce industry-wide demand by 20–40% for several quarters.
5. **Competition from outside**: Gene therapy companies, Big Pharma, or sovereign
   biotech programs could enter (modeled as demand/supply shocks).

---

## What You Are Deciding Each Quarter

### If You Are a Firm Agent

Every quarter, you choose:
- **Price**: What to charge per annual treatment course.
- **Production quantity**: How many courses to manufacture (limited by capacity).
- **Capital expenditure (capex)**: Investment in manufacturing capacity.
- **R&D spending**: Investment in next-generation technology.
- **Marketing/SGA**: Sales force, direct-to-consumer advertising, physician education.
- **Financing**: Equity issuance, debt requests, dividend payments, share buybacks.

Your goal is to build a valuable, sustainable enterprise. You are judged on equity
returns to investors, not just revenue or market share.

### If You Are a Financial Agent

There are four financial roles:

- **Equity Market**: Prices equity for each firm. If firms are private, acts as
  PE/VC investors (decides funding rounds, valuations). If firms are public, acts
  as the stock market (sets share price, decides on secondary offering subscriptions).
  Judged on pricing accuracy.
- **Investment Bank**: Structures IPOs, secondary offerings, and M&A deals.
  Publishes equity research. Advisory role only -- does not set prices.
- **Commercial Bank**: Sets revolving credit terms (commitment size, interest rate).
  Judged on credit losses and portfolio returns.
- **Credit Fund**: Provides term debt. Sets loan amounts, rates, maturities.
  Judged on credit losses and portfolio returns.

---

## Simulation Mechanics (Summary)

1. **Orchestrator draws macro shocks** (market size, taste shocks, rate shocks).
2. **New entrants go through capitalization** (firm pitches -> IBank structures -> Equity Market funds -> banks offer credit).
3. **Firms submit decisions** (price, production, capex, R&D, marketing, financing).
4. **Orchestrator clamps spending** to feasible levels (you cannot spend more than you have).
5. **Environment agent resolves the market** (demand allocation, R&D outcomes, events, narrative).
6. **Orchestrator posts accounting entries** (revenue, COGS, depreciation, interest, taxes).
7. **Financial agents set terms**: Equity Market prices equity; IBank publishes research; banks set credit terms.
8. **Orchestrator settles** -- draws revolvers if needed, checks solvency.
9. **Defaults and entry** -- insolvent firms default; environment decides if new entrants appear.

The cycle repeats. An Industry Gazette summarizing each quarter is published and
shared with all agents.
