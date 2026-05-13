# Financial Benchmarks & Valuation Context

## Purpose

This document helps both firm agents and the financial-market agent understand what
"good" and "bad" financial performance looks like in the biotech/pharmaceutical
industry. It provides reference points for decision-making -- not hard rules.

---

## Biotech Industry Financial Benchmarks (Real-World Reference)

These benchmarks are drawn from real-world biotech and specialty pharma companies
in the 2020s. They help calibrate expectations for the SRT industry.

### Revenue and Growth

| Metric | Early-Stage Biotech | Growth Biotech | Mature Pharma |
|--------|-------------------|---------------|--------------|
| Annual revenue | $0–$200M | $200M–$2B | $2B–$50B+ |
| Revenue growth (annual) | 50–200%+ | 20–50% | 5–15% |
| Years to profitability | 3–8 | 1–3 | Already profitable |
| Revenue per employee | $200K–$500K | $500K–$1.5M | $500K–$1M |

**For SRT firms in simulation**: Expect $0 revenue in Q1 (building operations), growing
to $50M–$500M/year by year 2–3 (depending on pricing and capacity), potentially
reaching $1B–$10B+ annually if the market expands and the firm captures meaningful share.

### Margins

| Margin | Biotech Launch Phase | Biotech Growth Phase | Biotech Mature |
|--------|---------------------|---------------------|---------------|
| Gross margin | 60–75% | 70–85% | 80–90% |
| R&D as % of revenue | 80–200% (spending > revenue) | 25–50% | 15–25% |
| SGA as % of revenue | 40–100% | 20–40% | 15–25% |
| Operating margin | -100% to -50% | -10% to +30% | +25% to +45% |
| Net margin | -120% to -60% | -15% to +20% | +15% to +35% |

**Key insight**: It is **normal** for biotech firms to lose money for several years
after launch. The financial market expects this -- what matters is the trajectory toward
profitability and the quality of the R&D pipeline.

### Balance Sheet

| Metric | Healthy Biotech | Stressed Biotech | Danger Zone |
|--------|----------------|-----------------|------------|
| Cash / quarterly burn | >6 quarters | 3–6 quarters | <3 quarters |
| Debt / equity | <0.5x | 0.5–1.5x | >2.0x |
| Current ratio | >2.0 | 1.0–2.0 | <1.0 |
| Debt / EBITDA | <3.0x (if EBITDA+) | 3–6x | >6x or EBITDA negative |

**Cash runway** is the most critical metric in early years. A firm that runs out of
cash defaults. The financial-market agent will closely monitor cash burn rate vs.
available liquidity (cash + undrawn revolver).

---

## Valuation Frameworks (for the Financial-Market Agent)

The financial-market agent must set equity prices each quarter. While it should NOT
use a fixed formula (per the simulation rules), these frameworks describe how
real-world biotech investors think.

### 1. Discounted Cash Flow (DCF)

The theoretically "correct" approach: estimate future free cash flows and discount
at the cost of equity.

**Challenge**: SRT firms have minimal current cash flows. Value is almost entirely
in future expectations (R&D outcomes, market expansion, pricing evolution).

**Typical assumptions for early-stage SRT**:
- Revenue growth: 30–80% annually for years 1–5, declining to 10–20% at maturity.
- Terminal gross margin: 75–85%.
- Terminal operating margin: 25–40%.
- Discount rate: 12–18% (high uncertainty -> high required return).
- Terminal value: 15–25x terminal free cash flow.

### 2. Revenue Multiples

For pre-profit companies, investors often use revenue multiples:

| Category | EV / Revenue Multiple |
|---------|---------------------|
| Pre-revenue biotech (Phase III) | 10–30x projected peak revenue |
| Commercial launch biotech | 5–15x current annual revenue |
| Growing specialty pharma | 4–8x revenue |
| Mature pharma | 3–5x revenue |

**For SRT firms**: Early valuations will be driven by potential, not current revenue.
A firm with strong R&D progress (close to Gen 2) deserves a higher multiple than one
stuck at Gen 1 with stagnant R&D.

### 3. Comparable Company Analysis

| Benchmark Company Profile | Market Cap Range | EV / Revenue |
|--------------------------|-----------------|-------------|
| Newly launched blockbuster drug (one product) | $5B–$30B | 8–15x |
| Multi-product specialty pharma | $10B–$80B | 5–10x |
| Large-cap diversified pharma | $50B–$500B+ | 3–6x |

**SRT firms in the simulation** start with zero revenue and uncertain R&D. Initial
market caps should reflect this -- perhaps $500M–$3B based on conditional approval +
Gen 1 product + R&D potential. Market caps could grow to $10B–$100B+ if a firm
achieves Gen 3 and captures a large global market.

---

## Credit Underwriting Benchmarks (for the Financial-Market Agent)

The financial-market agent also sets credit terms. Here are reference points:

### Revolver Sizing

| Firm Profile | Typical Revolver Commitment | Rationale |
|-------------|---------------------------|-----------|
| Pre-revenue, well-capitalized | 0.5–1.0x quarterly burn rate | Bridge financing only |
| Early revenue, growing | 1.0–2.0x quarterly revenue | Working capital support |
| Profitable, stable | 2.0–3.0x quarterly revenue | Flexibility buffer |
| Stressed / high-leverage | 0.5x or less | Minimize exposure |

### Interest Rate Spreads

| Credit Quality | Spread Over Risk-Free | Implied Annual Rate (at 4% r_f) |
|---------------|----------------------|--------------------------------|
| Investment grade (BBB+) | +150–250 bps | 5.5–6.5% |
| Speculative (BB) | +300–500 bps | 7.0–9.0% |
| High yield (B) | +500–800 bps | 9.0–12.0% |
| Distressed (CCC) | +800–1500 bps | 12.0–19.0% |
| Pre-revenue biotech (typical) | +400–700 bps | 8.0–11.0% |

### Debt Covenants (Implicit)

Real-world credit agreements include covenants. The financial-market agent should
implicitly consider:
- **Minimum liquidity**: Cash + undrawn revolver > 2x quarterly fixed charges.
- **Maximum leverage**: Total debt / tangible equity < 3.0x (higher tolerance for
  early-stage with strong R&D).
- **Revenue ramp**: Firm must demonstrate revenue growth trajectory consistent with
  business plan.

If covenants are tripped, the financial-market agent should:
- Tighten credit terms (reduce commitment, raise rate), or
- Refuse to extend/renew the revolver.

---

## Capital Raising Benchmarks

### IPO (Initial Capitalization)

At simulation start, each firm must raise capital via IPO. Reference points:

| Firm Profile | Typical IPO Raise | Post-IPO Market Cap | IPO Price Logic |
|-------------|------------------|--------------------|--------------------|
| Strong R&D team, good Phase II data | $300M–$600M | $1.5B–$4.0B | 15–25% of post-money valuation |
| Average R&D, decent data | $150M–$350M | $800M–$2.0B | 15–20% of post-money |
| Weak profile | $50M–$150M | $300M–$800M | 15–20% of post-money |

**Guidance for firms**: Request enough capital to fund 6–8 quarters of operations
(including R&D, capex for capacity building, and working capital). Under-raising
leads to early dilutive secondary offerings or excessive debt reliance.

### Secondary Offerings (Follow-On Equity)

Firms can raise additional equity after IPO. Typical considerations:
- **Dilution**: Existing shareholders are diluted. Frequent equity raises are viewed
  negatively by the market.
- **Timing**: Best raised when the stock price is high (less dilution per dollar raised).
- **Signal**: Raising equity can signal that the firm needs cash (negative) or that it
  has exciting investment opportunities (positive, if accompanied by R&D news).

---

## Performance Benchmarks for Firm Agents

### What "Good" Looks Like (Annual Metrics by Year)

| Year | Revenue | Gross Margin | Net Income | R&D Spend | Market Share |
|------|---------|-------------|-----------|-----------|-------------|
| 1 | $50–200M | 55–70% | Negative | $60–120M | 15–25% |
| 3 | $200M–$1B | 65–80% | Breakeven to +10% | $80–200M | 15–30% |
| 5 | $500M–$3B | 70–85% | +10–25% | $100–250M | 15–35% |
| 10 | $2B–$15B | 75–88% | +20–35% | $150–400M | 10–40% |
| 15 | $5B–$40B | 80–90% | +25–40% | $200–600M | 10–45% |
| 20 | $10B–$80B | 82–92% | +30–45% | $250–800M | 10–50% |

**These are ranges, not targets.** The actual trajectory depends on R&D success,
competitive dynamics, and macro shocks.

### Red Flags (Indicators of Poor Performance)

- **Cash burn acceleration** without revenue growth -> heading toward default.
- **R&D spend at zero** beyond mandatory -> falling behind competitors permanently.
- **Gross margin below 40%** -> pricing below cost or severe manufacturing inefficiency.
- **Debt/equity above 3x** -> overleveraged, one bad quarter from default.
- **Market share consistently declining** -> product or marketing failure.
- **Repeated equity raises** without corresponding revenue growth -> dilution spiral.

### Green Flags (Indicators of Strong Performance)

- **Revenue growth > 20% annually** sustained for 3+ years.
- **Gross margin expanding** toward 80%+ (process R&D paying off).
- **Positive free cash flow** (operating cash flow > capex) by year 3–5.
- **R&D advancing** (approaching or achieving Gen 2/3).
- **Market share stable or growing** despite competitive entry.
- **Self-funding R&D** from operating cash flow (no longer dependent on external financing).

---

## Return Expectations (for the Financial-Market Agent)

### Equity Returns

Biotech equity investors expect high returns to compensate for high risk:

| Scenario | Annual Equity Return | Explanation |
|---------|---------------------|-------------|
| Home run (Gen 3 + market dominance) | 40–80% annualized | Rare but transformative |
| Strong performer | 20–35% annualized | Good execution on R&D + commercial |
| Average | 10–20% annualized | Adequate but unremarkable |
| Disappointing | 0–10% annualized | Missed R&D milestones, competitive pressure |
| Failure | -50% to -100% (total loss) | Default, recall, or product failure |

**Expected value**: Given the risk of total loss (default), equity investors in early
biotech need the winners to return 3–5x their investment to make the portfolio math work.

### Debt Returns

Biotech credit investors expect:
- **If no default**: Risk-free rate + credit spread (7–12% annually for speculative grade).
- **If default**: Recovery of 30–60% of principal (biotech assets have moderate
  recovery values -- specialized equipment and IP have some value, but manufacturing
  facilities are hard to repurpose).
- **Expected loss rate**: 5–15% of principal over the loan life (reflecting default
  probability * loss-given-default).

---

## What the Financial-Market Agent Should Focus On

1. **Cash runway**: How many quarters can the firm survive at current burn rate?
   Firms with < 3 quarters of runway are distressed.

2. **R&D progress**: Is the firm advancing toward Gen 2/3? How does its R&D spend
   compare to competitors? A firm spending $100M/quarter on R&D is more likely to
   break through than one spending $15M.

3. **Revenue trajectory**: Is revenue growing, stable, or declining? Growth rate
   matters more than level in the early years.

4. **Competitive position**: What is the firm's product quality relative to competitors?
   Is it gaining or losing market share?

5. **Capital structure**: Is the firm appropriately leveraged? Too much debt in a
   risky business is dangerous. Too little leverage in a growing business may
   indicate under-investment.

6. **Management quality** (proxy: consistency of strategy): Does the firm's LLM
   agent make coherent decisions quarter to quarter, or does it thrash between
   strategies? Consistent strategy execution is a positive signal.
