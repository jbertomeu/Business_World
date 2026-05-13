# User Interface: Inspection, Monitoring, and Visualization

## Overview

The orchestrator provides a **dashboard UI** for the user to:
1. **Monitor live runs** -- watch key variables update each quarter
2. **Inspect completed runs** -- drill into any quarter, any firm, any decision
3. **Compare across runs** -- see how different regimes or seeds affect outcomes
4. **Aggregate all runs** -- see patterns across the full simulation database

The UI is a **local web application** (Python + Streamlit or Panel) that reads
from the run outputs and the cross-run database. It does NOT require internet
access.

---

## Dashboard Sections

### 1. Run Monitor (Live)

Shows the current run's progress in real time (updated after each quarter):

```
RUN: run_042 | Quarter: Q3 2034 (14/80) | Regime: baseline / baseline_gaap
Elapsed: 45 min | Est. remaining: 2h 30min

┌─────────────────────────────────────────────────────┐
│  INDUSTRY OVERVIEW                                  │
│  Active firms: 5 | Total patients: 12,400           │
│  Total revenue: $1.2B/quarter | HHI: 2,150         │
│  Avg price: $72,000 | Max generation: Gen 2         │
├─────────────────────────────────────────────────────┤
│  FIRM PERFORMANCE (sparklines)                      │
│  Firm 0 (Aeterna):  Revenue ▁▂▃▄▅▆▇ $280M  ↑12%  │
│  Firm 1 (GenVita):  Revenue ▁▂▃▃▃▄▅ $245M  ↑6%   │
│  Firm 2 (NovaLife): Revenue ▁▂▃▄▃▂▁ $120M  ↓15%  │
│  Firm 3 (BioAge):   Revenue ▁▁▂▃▄▅▆ $310M  ↑20%  │
│  Firm 4 (Senova):   Revenue ▁▂▂▃▃▃▃ $190M  ↑2%   │
├─────────────────────────────────────────────────────┤
│  FINANCIAL HEALTH                                    │
│  Cash runway (quarters): 8, 5, 3(!), 12, 7         │
│  Debt/equity: 0.3, 0.8, 2.1(!), 0.2, 0.5           │
│  Bank capital: CBank 92% | CFund 88%                │
├─────────────────────────────────────────────────────┤
│  LATEST GAZETTE HEADLINE                            │
│  "BioAge Captures Lead with Gen 2 Launch;           │
│   NovaLife Cash Position Raises Concerns"           │
└─────────────────────────────────────────────────────┘
```

### 2. Time-Series Plots (Single Run)

Interactive charts for any completed (or in-progress) run:

**Revenue and Market Share**
- Line chart: each firm's quarterly revenue over time
- Stacked area: market share evolution
- Event markers: defaults, entries, M&A, clinical holds

**Profitability**
- Line chart: gross margin, operating margin, net margin per firm
- Bar chart: net income per firm per quarter (positive/negative)
- Cumulative profit/loss by firm

**Balance Sheet**
- Stacked bar: asset composition (cash, AR, inventory, PPE, intangibles, goodwill)
- Stacked bar: liability + equity composition
- Line chart: debt/equity ratio over time

**Cash Flow**
- Waterfall chart: CFO, CFI, CFF, net change per firm per quarter
- Line chart: cumulative cash position
- Cash runway estimate over time

**R&D and Technology**
- Line chart: R&D spending per firm over time
- Step chart: product generation achieved per firm
- Bar chart: R&D allocation (product/process/delivery) per firm

**Market Dynamics**
- Line chart: average price, high price, low price over time
- Line chart: total demand (patients) over time
- Scatter: price vs. market share per firm per quarter

**Equity Valuation**
- Line chart: stock price per firm over time
- Line chart: pricing error (P - P*) over time
- Bar chart: IPO valuations for all entrants

**Financial Institutions**
- Line chart: bank capital over time
- Bar chart: cumulative interest income vs. losses
- Pie chart: loan portfolio by firm

**Scoring**
- Table: equity IRR, multiple, key metrics per firm-incarnation
- Radar chart: environment ratings by dimension
- Bar chart: institution loss rates

### 3. Single-Quarter Drill-Down

Click on any quarter to see:

**Market outcomes**:
- Who sold how much, at what price, at what market share
- Events that occurred
- Environment narrative (the gazette)
- Demand model baseline vs. actual outcome

**Per-firm details**:
- Full income statement, balance sheet, cash flow statement
- Raw decision (what the firm requested)
- Clamped decision (what actually happened)
- Reasoning trace (the firm's multi-step reasoning)
- Dossier snapshot

**Financial institution details**:
- Terms offered to each firm
- Reasoning for each term
- Portfolio state

**Orchestrator actions**:
- Feasibility clamping details (what was clamped and by how much)
- Settlement details (revolver draws, equity issuance)
- Validation results (which invariants checked)
- Warnings/flags

### 4. Cross-Run Comparison

Select 2+ runs to compare:

**Side-by-side line charts**:
- Same metric, different runs (e.g., "revenue for run_042 vs. run_043")
- Overlay with confidence bands if multiple seeds available

**Regime comparison**:
- Table: key outcome metrics by regime (rows = regimes, columns = metrics)
- Box plots: distribution of outcomes across seeds for each regime

**Scatter plots**:
- X = one strategy metric (e.g., avg R&D spend), Y = outcome (e.g., equity IRR)
- Colored by regime or fingerprint style
- Across all firm-incarnations in the database

### 5. All-Runs Aggregate Dashboard

Summary across the entire simulation database:

**Database statistics**:
- Total runs: N
- Total firm-incarnations: M
- Total quarters simulated: K
- Default rate: X%
- Average equity IRR: Y%

**Strategy-outcome analysis**:
- Heatmap: fingerprint_style x outcome_metric
- "Which personality types perform best under which regimes?"

**Environment quality tracking**:
- Line chart: average environment rating over successive runs
- "Is the environment agent improving with cross-run learning?"

**Regime comparison (aggregated)**:
- Table: all regimes tested, with mean and std of key outcomes
- Statistical test results (if enough runs): "Does R&D capitalization significantly
  change R&D spending?"

---

## Implementation

### Technology Choice

**Streamlit** is recommended:
- Pure Python (no JavaScript needed)
- Interactive widgets (sliders, dropdowns, date pickers)
- Native support for pandas DataFrames and matplotlib/plotly charts
- Runs locally (`streamlit run dashboard.py`)
- Single file for simple dashboards, modular for complex ones

### File Structure

```
llm_firm_lab/
  dashboard/
    app.py                    # Main Streamlit app
    pages/
      01_run_monitor.py       # Live run monitoring
      02_time_series.py       # Single-run time-series plots
      03_quarter_drill.py     # Single-quarter detail view
      04_cross_run.py         # Cross-run comparison
      05_aggregate.py         # All-runs aggregate analysis
    components/
      charts.py               # Reusable chart components
      data_loader.py          # Load Compustat, debrief, scores, dossiers
      formatters.py           # Statement formatting for display
```

### Data Sources

The dashboard reads from:
- `data/compustat_q.csv` (all runs)
- `data/debrief.csv` (all runs)
- `data/scores.csv` (all runs)
- `data/run_summaries.csv` (all runs)
- `outputs/{run_id}/` (per-run details: statements, dossiers, gazettes, reasoning)

### Running the Dashboard

```bash
# View a specific run
python -m llm_firm_lab dashboard --run-id run_042

# View all runs
python -m llm_firm_lab dashboard

# Monitor a live run
python -m llm_firm_lab dashboard --live --run-id run_042
```

### Plot Export

All plots can be exported to:
- PNG/SVG (for papers)
- Interactive HTML (for sharing)
- PDF (for reports)

---

## CLI Inspection (Non-GUI Alternative)

For quick checks without launching the dashboard:

```bash
# Summary of a run
python -m llm_firm_lab inspect --run-id run_042

# Print a firm's income statement for a specific quarter
python -m llm_firm_lab inspect --run-id run_042 --firm firm_0 --quarter 14 --statement is

# Print the gazette for a quarter
python -m llm_firm_lab inspect --run-id run_042 --quarter 14 --gazette

# Print a firm's reasoning for a quarter
python -m llm_firm_lab inspect --run-id run_042 --firm firm_0 --quarter 14 --reasoning

# Quick aggregate statistics
python -m llm_firm_lab inspect --all-runs --summary

# Export plots to PNG
python -m llm_firm_lab plot --run-id run_042 --type revenue --output plots/
python -m llm_firm_lab plot --all-runs --type strategy_outcomes --output plots/
```

---

## Configuration

```yaml
dashboard:
  port: 8501
  auto_refresh_seconds: 30     # for live monitoring
  default_chart_library: "plotly"   # plotly | matplotlib
  export_format: "png"
  theme: "light"               # light | dark
```
