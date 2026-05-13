# Entry, Exit, and Mergers & Acquisitions

## Firm Death: How and When Firms Exit

### Causes of Exit

A firm can exit the simulation through three paths:

| Exit Path | Trigger | Frequency |
|-----------|---------|-----------|
| **Bankruptcy** | Cash < 0 after exhausting credit (involuntary) | Most common |
| **Voluntary liquidation** | Firm agent decides to wind down (rare) | Uncommon |
| **Acquisition** (merged into acquirer) | M&A transaction approved | Occasional |

### Bankruptcy (Involuntary Exit)

As described in doc 07, a firm defaults when end-of-quarter cash is negative
after maximum revolver draw. The bankruptcy process:

1. Firm is declared insolvent
2. Asset auction with recovery haircuts
3. Creditor waterfall distributes proceeds
4. Equity holders receive residual (usually zero)
5. Firm slot becomes vacant
6. Final row in Compustat with `default_flag = 1`
7. All agents notified; gazette reports the failure

### Voluntary Liquidation

A firm agent may decide to wind down if the business is unviable but not yet
bankrupt. This is a strategic choice:

```json
{
  "action": "voluntary_liquidation",
  "reasoning": "Our Gen 1 product is uncompetitive. Two competitors have Gen 2.
    Our market share has fallen from 20% to 5%. Better to return remaining capital
    to shareholders than continue burning cash."
}
```

Process:
1. Firm ceases operations (no production, no sales)
2. Assets sold in orderly fashion (HIGHER recovery rates than bankruptcy):
   - Cash: 100%, AR: 90%, Inventory: 60%, PPE: 50%, Intangibles: 25%
3. Debts repaid in priority order
4. Residual distributed to equity holders
5. Firm slot becomes vacant
6. Compustat records a "liquidation" row

### What Happens to Vacant Slots

A vacant slot does NOT automatically get a new entrant. Entry is a separate
process (see below).

---

## Entry: How New Firms Join

### Entry Is Not Automatic

In previous versions, firm slots were instantly refilled. This was unrealistic
and caused death spirals. The new design:

- When a slot becomes vacant (via bankruptcy, liquidation, or acquisition),
  the slot enters a **vacancy pool**
- Entry requires a **potential entrant** to be generated and approved
- The number of active firms can fluctuate between 0 and N_max
- N_max is set at simulation start (default: 5) and represents the maximum
  number of firms the industry can support

### Entry Decision Process

Each quarter, if there are vacant slots, the orchestrator runs an entry check:

```
1. ORCHESTRATOR checks: Are there vacant slots?
   If no: skip entry.
   If yes: continue.

2. ORCHESTRATOR checks death-spiral guard:
   If this slot had 3+ consecutive Q1 defaults: slot is paused (skip entry).
   If slot has been paused for the required cooldown period: allow entry.
   If slot has 6+ total consecutive failures: slot is permanently frozen.

3. ENVIRONMENT AGENT is asked:
   "A slot is vacant. Given current market conditions (market size, growth,
    competition, technology state), is it plausible that a new entrant would
    attempt to enter the SRT market?
    Consider: Is there room for another competitor? Is the technology mature
    enough to attract investment? What would a new entrant look like?"

   Environment responds:
   {
     "entry_recommended": true,
     "entrant_profile": "A European biotech spin-off from a university lab
       with a novel formulation approach. Likely to pursue a cost-leadership
       strategy.",
     "market_rationale": "Market growing at 15%/year with only 3 active firms.
       Room for a 4th competitor targeting the underserved European market."
   }
   OR:
   {
     "entry_recommended": false,
     "rationale": "Market is saturated with 5 firms already losing money.
       No rational investor would fund a new entrant."
   }

4. If entry recommended:
   - ORCHESTRATOR creates a new firm agent with fresh fingerprint
   - New firm goes through IPO sub-sequence (Phase 2)
   - Financial institutions decide whether to fund the entrant
   - If IPO raises at least minimum viable capital: firm enters
   - If IPO fails: slot remains vacant (try again next quarter)

5. If entry not recommended:
   - Slot remains vacant
   - Checked again next quarter
```

### Entry After Acquisition

When a firm is acquired (see M&A below), the acquired firm's slot becomes vacant.
Entry into that slot follows the same process, but with additional context:
the environment knows the slot was vacated by acquisition (not failure), which
may make entry more attractive.

### Configurable Entry Parameters

```yaml
entry:
  n_max_firms: 5                    # maximum active firms (user sets at start)
  entry_check_every_n_quarters: 1   # how often to check for entry
  min_quarters_after_death: 1       # minimum vacancy before re-entry attempt
  death_spiral_consecutive_max: 3   # Q1 defaults before slot paused
  death_spiral_cooldown_quarters: 2 # pause duration
  death_spiral_freeze_after: 6      # permanent freeze threshold
  min_ipo_capital: 50000000         # minimum capital to be considered viable
  environment_decides_entry: true   # if false, entry is automatic when slot open
```

---

## Mergers & Acquisitions (Point 7)

### Overview

Firms can propose to acquire other firms. M&A is a complex process involving:
- A willing buyer and seller (or hostile takeover)
- Actual financing (the buyer must pay for the acquisition)
- Goodwill accounting (purchase price vs. book value)
- Regulatory approval (the environment decides)
- Integration (operational disruption during merger)

### When M&A Can Happen

The firm agent can include an acquisition proposal in its quarterly decision:

```json
{
  "ma_proposal": {
    "action": "acquire",
    "target_firm_id": "firm_2",
    "offer_type": "friendly",
    "offer_price_per_share": 28.00,
    "financing": {
      "cash_component": 150000000,
      "stock_component": 100000000,
      "new_debt_for_acquisition": 200000000
    },
    "strategic_rationale": "Acquiring firm_2's Gen 2 pipeline and
      manufacturing capacity would accelerate our technology roadmap
      by 8+ quarters."
  }
}
```

The target firm can also signal willingness to be acquired:
```json
{
  "ma_signal": {
    "action": "open_to_acquisition",
    "minimum_price_per_share": 25.00,
    "reasoning": "Our cash runway is 3 quarters. A strategic buyer
      could fund our R&D pipeline to completion."
  }
}
```

### M&A Process (Multi-Step)

```
Quarter T: Acquirer proposes, target signals willingness (or not)

Quarter T+1: If both willing (friendly) or acquirer persists (hostile):

  1. ORCHESTRATOR checks financing feasibility:
     - Does the acquirer have enough cash + credit for the cash component?
     - Can the acquirer raise the proposed new debt?
     - Is the stock component feasible (enough authorized shares)?
     If financing is infeasible: deal rejected.

  2. FINANCIAL INSTITUTIONS evaluate:
     - Investment bank: Is the offer price reasonable? (valuation check)
     - Commercial bank / credit fund: Will they finance the acquisition debt?
     If financing denied: deal fails (acquirer can try again with different terms).

  3. ENVIRONMENT AGENT evaluates regulatory approval:
     "Two SRT firms propose to merge. The combined entity would have [X%]
      market share. Is this likely to receive regulatory approval?"
     Factors: combined market share, HHI impact, number of remaining
     competitors, public interest in SRT competition.
     Probability of approval: roughly 90% if combined share < 35%,
     50% if 35-50%, 10% if > 50%.

  4. If approved:
     - ORCHESTRATOR executes the merger (see accounting below)
     - Target firm slot becomes vacant
     - Combined firm continues in the acquirer's slot

Quarter T+2: Integration begins (see integration effects below)
```

### M&A Accounting

On the acquisition closing date:

```
ACQUIRER'S BALANCE SHEET:

Assets acquired (at fair value):
  + Target's cash
  + Target's AR (at recovery value)
  + Target's inventory (at fair value)
  + Target's PPE (at appraised value)
  + Target's intangibles (R&D capital at fair value)
  + GOODWILL = Purchase Price - Fair Value of Net Assets Acquired

Liabilities assumed:
  + Target's AP, accrued expenses, taxes payable
  + Target's debt (assumed or refinanced)

Consideration paid:
  - Cash paid
  - New shares issued (at current market price)
  - New debt incurred

Goodwill = Total consideration - (Fair value of assets - Fair value of liabilities)
```

**Goodwill** appears on the acquirer's balance sheet as a new asset line.
It is NOT amortized (consistent with current US GAAP) but is subject to
**annual impairment testing**.

### Goodwill Impairment

Each year (every 4 quarters), the orchestrator tests goodwill for impairment:

```
Carrying value of acquired business = Goodwill + net assets from acquisition
Fair value of acquired business = DCF or market-based estimate

If fair value < carrying value:
  Impairment loss = carrying value - fair value
  Recorded as: operating expense on IS, reduction of goodwill on BS

Triggers for impairment:
- Acquired firm's products losing market share
- R&D pipeline (the reason for acquisition) failing
- Market conditions deteriorating
- Integration problems
```

Goodwill impairment is a **non-cash charge** that reduces net income and equity
but does not affect cash flow. It is important because:
- It signals the acquisition was overpriced
- It reduces the acquirer's reported equity (affects credit ratios)
- It appears on the IS as a large one-time charge
- The investment bank should factor impairment risk into the acquirer's valuation

### Compustat Columns for M&A

Added to the panel:
- `gdwlq` -- Goodwill (balance sheet)
- `gdwlipq` -- Goodwill impairment this quarter (income statement)
- `aqaq` -- Acquisition amount this quarter
- `acquiree_id` -- ID of acquired firm (blank if no acquisition)

### Integration Effects

After an acquisition closes, the combined firm experiences:

| Effect | Duration | Magnitude |
|--------|----------|-----------|
| Capacity disruption | 2 quarters | -20% capacity utilization |
| SGA increase (integration costs) | 2 quarters | +30% SGA |
| R&D disruption | 1-2 quarters | -15% R&D effectiveness |
| Workforce attrition | 2-4 quarters | 10-20% of acquired workforce leaves |
| Synergy realization (cost) | 4-8 quarters | -10% COGS (if complementary) |
| Synergy realization (R&D) | 4-8 quarters | Combined R&D progress accelerates |
| Brand confusion | 2-4 quarters | -5% brand capital during transition |

These effects are generated by the environment agent based on the specifics
of the deal and the firms involved.

### M&A Impact on Entry

When an acquisition reduces the number of active firms, it may trigger entry:
- The vacant slot enters the entry pool
- The environment evaluates whether a new entrant is plausible
- Regulatory approval of the merger may be conditioned on "maintaining competition"
  (the environment can mandate that the vacant slot be filled)

---

## Firm Count Dynamics

### Starting Configuration (Point 11)

The user sets at simulation start:

```yaml
simulation:
  n_firms_initial: 5        # firms at t=0 (all go through IPO in Q1)
  n_firms_max: 7            # maximum concurrent active firms
  n_quarters: 80            # total quarters to simulate
  seed: 42
```

`n_firms_initial` can differ from `n_firms_max` -- for example, start with 3
firms and allow up to 5, letting the market grow.

### How Firm Count Changes Over Time

```
Q1: 5 firms IPO (n_firms_initial = 5)

Q8: Firm 2 defaults. Active firms = 4.
    Environment recommends entry. New firm IPOs in Q9.
    Active firms = 5.

Q15: Firm 0 acquires Firm 4. Active firms = 4.
     Vacant slot created. Entry attempted.
     Environment: "Market supports 5 firms." New entrant in Q16.
     Active firms = 5.

Q30: Firm 1 and Firm 3 default in same quarter. Active firms = 3.
     Two slots vacant. Environment recommends 1 entry (not 2).
     Active firms = 4 in Q31.
     Second entry considered in Q32.

Q50: Market mature. 5 firms active. No entry pressure.

Q65: Firm 2 (2nd incarnation) defaults. Environment: "Market saturated,
     no entry recommended." Active firms = 4 for remainder.
```

The key insight: the number of firms is **endogenous** -- it depends on market
conditions, competitive dynamics, and the environment agent's assessment.

---

## Configuration Summary

```yaml
entry:
  n_firms_initial: 5
  n_firms_max: 7
  environment_decides_entry: true
  min_quarters_vacancy: 1
  death_spiral_consecutive_max: 3
  death_spiral_cooldown: 2
  death_spiral_freeze_after: 6
  min_ipo_capital: 50000000

exit:
  voluntary_liquidation_allowed: true
  liquidation_recovery_premium: 0.10    # % better recovery than bankruptcy

ma:
  enabled: true
  min_quarters_before_ma: 4             # firms must operate 4Q before acquiring
  max_combined_market_share: 0.50       # soft regulatory limit
  goodwill_impairment_test_frequency: 4 # every 4 quarters
  integration_disruption_quarters: 2
  integration_cost_multiplier: 1.30     # SGA increase during integration
  synergy_realization_quarters: 8       # time to realize cost synergies
  hostile_takeover_allowed: false       # start with friendly only

simulation:
  n_quarters: 80
  seed: 42
```
