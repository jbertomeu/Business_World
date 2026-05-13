# Simulation Modes and Complexity Toggles

## Purpose

Not every run needs every feature. This document defines the configuration
switches that control the simulation's scope and complexity. Simpler runs
are faster, easier to debug, and better for isolating specific effects.
Complex runs are richer and more realistic.

All toggles are set in `config.yaml` before the run starts and are fixed
for the duration of the run.

---

## Simulation Mode: Public vs. Private

### The Choice

At run start, the user chooses how firms begin:

```yaml
simulation:
  mode: "private_start"    # or "public_start"
  allow_ipo: true          # if private_start, can firms IPO during the run?
```

### Mode: `public_start` (Default)

Firms begin with an IPO in Q1. The Equity Market agent acts as the public
stock market from the start.

**Q1 sequence**:
1. Firm requests capital raise
2. Investment Bank structures the IPO (share count, price range, prospectus)
3. Equity Market sets the market-clearing price and subscribes to shares
4. Capital is booked; firm has public equity and a stock price
5. Firm begins operating

**Ongoing**: Equity Market sets a stock price every quarter. Secondary offerings
go through IBank structuring then Equity Market subscription. Shares are freely
tradeable (modeled as continuous market pricing by the Equity Market agent).

### Mode: `private_start`

Firms begin as private companies funded by the Equity Market agent acting as
a PE/VC consortium.

**Q1 sequence**:
1. Firm pitches for funding (capital need, business plan, equity offered)
2. Investment Bank advises on deal structure (valuation, terms, governance)
3. Equity Market (in PE mode) decides: fund or pass? At what valuation?
   - Sets a "post-money valuation" and takes an equity stake
   - May impose governance terms: board seat, anti-dilution, liquidation preference
4. Capital is booked; firm has private equity at the agreed valuation
5. Firm begins operating

**Ongoing**: No public stock price. Equity Market sets a "last-round valuation"
each quarter (a private mark-to-market, like a VC portfolio valuation). Firms
can raise additional private rounds (same process: firm requests -> IBank
structures -> Equity Market decides).

**Key differences from public mode**:

| Aspect | Private | Public |
|--------|---------|--------|
| Equity pricing | Last-round valuation (PE markup) | Market price (public trading) |
| Pricing frequency | Each funding round + quarterly mark | Every quarter |
| Information available | Extensive due diligence (more than public) | Published financials only |
| Liquidity | Zero (no secondary market) | Full (shares trade freely) |
| Governance | Board seats, veto rights, preferences | Shareholder voting only |
| Dilution mechanics | Down rounds, anti-dilution ratchets | Market-price issuance |
| Cost of capital | Higher (illiquidity premium) | Lower (liquid market) |

### IPO Transition (if `allow_ipo: true`)

A private firm can choose to IPO at any point. The IPO decision is part of
the firm's quarterly decision:

```json
{
  "ipo_request": {
    "go_public": true,
    "desired_raise": 500000000,
    "shares_to_offer_pct": 0.25,
    "reasoning": "We need growth capital and our PE investors want liquidity."
  }
}
```

**IPO process**:
1. IBank evaluates and structures the offering (price range, share count, roadshow)
2. Equity Market (switching from PE to public mode for this firm) sets the IPO price
3. If Equity Market subscribes: IPO succeeds, firm becomes public
4. If Equity Market declines (price too high, market conditions bad): IPO fails,
   firm remains private, can try again next quarter
5. Existing PE investors' shares convert to public shares at IPO price

**After IPO**: The firm is treated as public for all future quarters. The Equity
Market agent prices it as a public stock. PE-era governance terms expire.

### When Would a Firm IPO?

The firm agent (and the environment narrative) should consider:
- **Cash need**: Private rounds become expensive (high dilution) for mature companies
- **PE investor pressure**: After 8-12 quarters, PE investors want exits
- **Market conditions**: IPO windows open and close with market sentiment
- **Competitive positioning**: Being public signals maturity and credibility
- **Regulatory**: Full ALT approval may require public disclosure levels

---

## Complexity Toggles

### Toggle Table

```yaml
complexity:
  # Core toggles (recommended for all runs)
  entry_exit: true               # firm bankruptcy, entry, death-spiral prevention
  financial_institutions: true    # banks and equity market; if false, fixed financing

  # Feature toggles (activate for richer runs)
  ma_enabled: false              # M&A proposals, goodwill, impairment
  leasing_enabled: false         # lease vs. build, ROU assets, lease liabilities
  stock_comp_enabled: false      # option/RSU grants, diluted shares, non-cash expense
  workforce_detail: false        # hiring/layoff decisions, workforce effects
  working_capital_decisions: false # collection, inventory, payment terms
  provisions_enabled: false      # litigation reserves, warranty provisions
  voluntary_liquidation: false   # firms can choose to wind down

  # Product/market toggles
  multi_product: false           # multiple product lines per firm (NOT v1)
  regions: false                 # geographic market segmentation (NOT v1)

  # Accounting toggles (orthogonal to above)
  nol_carryforward: true         # tax loss carryforward tracking
  fair_value_regime: false       # PPE marked to fair value (vs. historical cost)
  rd_capitalization: false       # capitalize portion of R&D (vs. expense all)
```

### What Each Toggle Controls

#### `entry_exit: true` (default ON)

**ON**: Firms can default. Vacant slots may receive new entrants (environment
decides). Death-spiral tracker active.

**OFF**: Firms never default. If cash goes negative, orchestrator injects
emergency equity (logged as "government bailout") at dilutive terms. Useful
for studying firm behavior without bankruptcy risk.

#### `financial_institutions: true` (default ON)

**ON**: 4 financial agents (Equity Market, IBank, Commercial Bank, Credit Fund)
operate independently with LLM-driven decisions.

**OFF**: Financing is on autopilot. Orchestrator provides:
- Fixed revolver at r_f + 300bps, commitment = 1x quarterly revenue
- Fixed term debt at r_f + 500bps, max = 0.5x total assets
- Equity price = book value (no market pricing)
- No equity subscription decisions (firms issue freely)
Useful for studying firm strategy in isolation from capital market effects.

#### `ma_enabled: false` (default OFF)

**ON**: Firms can propose acquisitions. Full M&A process: financing, goodwill,
impairment testing, integration effects. IBank advises on deals. Equity Market
prices post-merger equity. Creates vacant slots for potential entry.

**OFF**: No M&A. The `ma_proposal` field is removed from firm decisions. No
goodwill on balance sheets. Simpler accounting.

#### `leasing_enabled: false` (default OFF)

**ON**: Firms choose lease vs. build for capacity. Lease decisions added to
firm JSON. ROU assets and lease liabilities on balance sheet. Lease expense
flows through P&L.

**OFF**: All capacity expansion is via capex (purchase). No lease-related
balance sheet items. `rouq`, `leaseq`, `xlrq` columns are zero.

#### `stock_comp_enabled: false` (default OFF)

**ON**: Firms grant options and RSUs. Non-cash SGA expense. Diluted shares
tracked. EPS computed on diluted basis.

**OFF**: All compensation is cash. Basic shares = diluted shares. `stkcpq`
column is zero.

#### `workforce_detail: false` (default OFF)

**ON**: Firms make hiring/layoff decisions by category. Workforce count affects
R&D speed (scientists), manufacturing quality (ops staff), and commercial
effectiveness (sales). Restructuring charges on layoffs.

**OFF**: Workforce is modeled implicitly. Headcount scales automatically with
revenue/R&D/SGA spending. No explicit workforce decisions. `empq` is computed
from a formula, not a decision.

#### `working_capital_decisions: false` (default OFF)

**ON**: Firms choose collection aggressiveness, inventory targets, supplier
payment terms. Working capital becomes a strategic lever.

**OFF**: Working capital uses defaults: AR = 15% of revenue, AP = 15% of COGS,
accrued = 10% of (SGA + R&D). Firms cannot influence these ratios.

#### `provisions_enabled: false` (default OFF)

**ON**: Firms decide litigation reserve additions, warranty provisions.
Provisions appear as long-term liabilities. Settlements reduce provisions.

**OFF**: Litigation costs are rolled into SGA automatically (2-4% of revenue).
No explicit provision decisions or balance sheet items.

---

## Recommended Configurations

### Minimal (fastest, for testing and debugging)

```yaml
simulation:
  mode: "public_start"
  n_firms_initial: 3
  n_quarters: 20
complexity:
  entry_exit: true
  financial_institutions: false    # autopilot financing
  ma_enabled: false
  leasing_enabled: false
  stock_comp_enabled: false
  workforce_detail: false
  working_capital_decisions: false
  provisions_enabled: false
```

3 firms, 20 quarters, no banks, no M&A, no leasing, no stock comp. Focus on
product market competition and R&D race.

### Standard (balanced realism and speed)

```yaml
simulation:
  mode: "public_start"
  n_firms_initial: 5
  n_quarters: 40
complexity:
  entry_exit: true
  financial_institutions: true
  ma_enabled: false
  leasing_enabled: false
  stock_comp_enabled: false
  workforce_detail: false
  working_capital_decisions: false
  provisions_enabled: false
```

5 firms, 40 quarters, full financial agents, but no optional complexity. This
is the recommended starting point for research runs.

### Full (maximum realism)

```yaml
simulation:
  mode: "private_start"
  allow_ipo: true
  n_firms_initial: 5
  n_quarters: 80
complexity:
  entry_exit: true
  financial_institutions: true
  ma_enabled: true
  leasing_enabled: true
  stock_comp_enabled: true
  workforce_detail: true
  working_capital_decisions: true
  provisions_enabled: true
```

Private start with IPO option, all features on, 80 quarters. Richest simulation
but slowest (most LLM calls, most complexity).

### Research: Regime Comparison

```yaml
# Run A: Baseline
simulation:
  mode: "public_start"
  seed: 42
information_regime: "baseline"
measurement_regime: "baseline_gaap"

# Run B: Same seed, different measurement
simulation:
  mode: "public_start"
  seed: 42
information_regime: "baseline"
measurement_regime: "rd_capitalization"
```

Same firms, same shocks, different accounting rules. Compare outcomes.

---

## How Toggles Affect Agent Prompts

When a toggle is OFF, the corresponding section is **omitted from prompts entirely**.
Agents are not told "M&A is disabled" -- they simply never see the M&A decision
field or any M&A-related context. This prevents agents from reasoning about
features that don't exist in the current run.

When a toggle is ON, the corresponding decision fields, context sections, and
world doc references are included in prompts.

The prompt builder checks toggles:

```python
def build_firm_prompt(firm_state, config):
    prompt = base_prompt(firm_state)

    if config.complexity.ma_enabled:
        prompt += ma_decision_section(firm_state)
    if config.complexity.leasing_enabled:
        prompt += lease_decision_section(firm_state)
    if config.complexity.stock_comp_enabled:
        prompt += stock_comp_section(firm_state)
    if config.complexity.workforce_detail:
        prompt += workforce_section(firm_state)
    # etc.

    return prompt
```

---

## How Toggles Affect Compustat

All Compustat columns are ALWAYS present in the panel (for schema consistency).
When a toggle is OFF, the corresponding columns contain zero or null:

| Toggle OFF | Affected Columns | Value |
|-----------|-----------------|-------|
| ma_enabled | gdwlq, gdwlipq, aqaq | 0 |
| leasing_enabled | rouq, leaseq, xlrq | 0 |
| stock_comp_enabled | stkcpq, diluted_shares | 0 / = basic_shares |
| workforce_detail | empq | Computed from formula, not decision |
| provisions_enabled | loq (provisions component) | 0 |

This means analysis code works on any run regardless of toggle configuration --
columns are always there, just sometimes zero.

---

## How Toggles Affect Scoring

Scoring uses the same formulas regardless of toggles. Equity IRR is always
computed from cash flows to equity investors. Debt returns are always computed
from lending cash flows. The scoring system is toggle-agnostic.

The environment rating system is also toggle-agnostic -- agents rate the
environment on the same 6 dimensions regardless of which features were active.

---

## Configuration Validation

The orchestrator validates toggle combinations at run start:

| Rule | Enforcement |
|------|------------|
| `ma_enabled` requires `entry_exit` | Error if M&A on but entry/exit off |
| `allow_ipo` requires `mode: "private_start"` | Warning if IPO allowed but already public |
| `stock_comp_enabled` ignored if `financial_institutions: false` | Warning (no dilution effect without market pricing) |
| `n_firms_initial <= n_firms_max` | Error |
| `n_quarters >= 4` | Error (need at least 1 year) |
| `n_firms_initial >= 2` | Error (need competition) |
