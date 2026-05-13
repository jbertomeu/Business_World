# Scoring, Evaluation, and Policy Learning

## Overview

Every run produces scores for all participants. These scores serve two purposes:
1. **Within-run**: Tell each agent how well they did (debrief)
2. **Across-run**: Build a database of what strategies and policies work,
   enabling agents to learn and researchers to analyze

---

## Part 1: Financial Scoring (All Agents)

### Firm Scoring

Each firm-incarnation receives two scores:

#### A. Realized Value (backward-looking)

```
Realized value = Total cash returned to equity investors

Cash flows to equity investors:
  Q0 (IPO):       - equity_invested (negative: investors put money in)
  Q1..Q_T:        + dividends_paid + buyback_payments
  Q_T (terminal): + terminal_equity_value

Where terminal_equity_value =
  If firm alive at end of simulation:
    equity_price_final * shares_outstanding
  If firm was acquired:
    acquisition_proceeds_to_equity
  If firm defaulted:
    equity_recovery_from_waterfall (usually 0)
  If firm voluntarily liquidated:
    liquidation_residual_to_equity
```

From these cash flows, compute:
- **Equity IRR (quarterly)**: Internal rate of return on the equity cash flow stream
- **Equity IRR (annualized)**: `(1 + IRR_q)^4 - 1`
- **Equity multiple**: Total cash returned / Total cash invested
- **Total shareholder return**: `(terminal_value + total_dividends + total_buybacks - total_invested) / total_invested`

#### B. Terminal Enterprise Value (forward-looking estimate)

For firms alive at simulation end, estimate what the business is worth going forward:

```
Terminal enterprise value =
  equity_price_final * shares_outstanding    (equity component)
  + total_debt_outstanding                    (debt component)
  - cash_on_hand                              (net debt adjustment)

This is a market-based estimate. The investment bank's final equity price
implicitly reflects expected future cash flows.
```

#### Combined Firm Score

```json
{
  "firm_id": "firm_0",
  "incarnation": 1,
  "lifespan_quarters": 40,

  "realized_score": {
    "equity_irr_annual": 0.18,
    "equity_multiple": 2.4,
    "total_dividends_paid": 120000000,
    "total_buybacks_paid": 50000000,
    "total_equity_invested": 350000000,
    "terminal_equity_value": 680000000
  },

  "operational_score": {
    "max_generation_achieved": 2,
    "peak_market_share": 0.28,
    "avg_market_share": 0.21,
    "avg_gross_margin": 0.72,
    "total_revenue_lifetime": 4200000000,
    "total_rd_spend_lifetime": 1100000000,
    "quarters_profitable": 28,
    "quarters_negative_cash_flow": 12
  },

  "exit_type": "alive",   # alive | default | liquidation | acquired
  "default_quarter": null
}
```

### Financial Institution Scoring

Each institution receives:

#### Commercial Bank / Credit Fund

```json
{
  "institution_id": "cbank_0",

  "lending_score": {
    "total_principal_advanced": 850000000,
    "total_principal_recovered": 810000000,
    "total_interest_earned": 95000000,
    "total_fee_income": 12000000,
    "total_losses": 40000000,
    "loss_rate": 0.047,                    # losses / principal advanced
    "debt_irr_annual": 0.082,
    "debt_total_return": 1.34,
    "defaults_experienced": 2,
    "recovery_rate_avg": 0.55
  },

  "risk_management_score": {
    "max_single_exposure_pct": 0.22,       # vs. 0.25 limit
    "min_capital_ratio": 0.11,             # vs. 0.08 minimum
    "quarters_undercapitalized": 0,
    "survived": true
  }
}
```

#### Investment Bank

```json
{
  "institution_id": "ibank_0",

  "pricing_score": {
    "pricing_rmse": 4.50,                  # $ per share
    "pricing_mape": 0.18,                  # 18% average absolute error
    "pricing_bias": -1.20,                 # slight undervaluation on average
    "pricing_correlation": 0.85,           # correlation P vs P_star
    "worst_mispricing_firm": "firm_2",
    "worst_mispricing_amount": 12.00
  },

  "underwriting_score": {
    "ipos_underwritten": 7,
    "ipos_successful": 6,                  # firm survived > 4 quarters
    "ipos_failed": 1,                      # firm defaulted within 4 quarters
    "avg_ipo_return_1yr": 0.15,            # price 4Q later vs IPO price
    "total_underwriting_fees": 45000000
  },

  "credibility": {
    "credibility_score": 0.78,             # 1.0 = perfect, 0.0 = replaced
    "survived": true
  }
}
```

---

## Part 2: Environment Rating (Point 4)

### How It Works

At the end of each simulation, every agent (firms + financial institutions)
rates the environment on a 1-10 scale across several dimensions:

The orchestrator sends each agent a special `POST /turn` with `phase: "rate_environment"`:

```json
{
  "phase": "rate_environment",
  "instructions": "The simulation has ended. You have access to the complete history
    of events, market outcomes, and the environment's narratives. Rate the environment
    on each dimension from 1 (terrible) to 10 (excellent). Justify each rating.",
  "full_history": {
    "all_gazettes": [...],
    "all_market_outcomes": [...],
    "all_events": [...],
    "all_dossier_updates": [...]
  }
}
```

### Rating Dimensions

Each agent rates on:

```json
{
  "environment_ratings": {
    "market_realism": 8,
    "market_realism_justification": "Demand patterns were plausible. Price
      elasticities felt right. The market grew as product quality improved,
      which matched the world docs.",

    "event_realism": 7,
    "event_realism_justification": "The safety scandal in Q12 was well-timed
      and had realistic consequences. However, the rapid recovery in Q14
      seemed too fast.",

    "narrative_quality": 9,
    "narrative_quality_justification": "The gazettes were informative and
      maintained continuity. The environment agent clearly tracked company
      stories across quarters.",

    "consistency": 7,
    "consistency_justification": "Mostly consistent, but the demand response
      to price changes was sometimes erratic -- a 5% price cut in Q20
      had no effect, but a 3% cut in Q25 shifted 8% market share.",

    "difficulty_fairness": 8,
    "difficulty_fairness_justification": "The simulation was challenging
      but not unfair. No firm was singled out for bad luck. Macro shocks
      affected everyone similarly.",

    "overall": 8,
    "overall_justification": "A realistic and engaging simulation environment."
  }
}
```

### Aggregated Environment Score

```json
{
  "run_id": "run_042",
  "environment_scores": {
    "market_realism": {"mean": 7.6, "min": 6, "max": 9, "std": 0.9},
    "event_realism": {"mean": 7.2, "min": 5, "max": 9, "std": 1.2},
    "narrative_quality": {"mean": 8.1, "min": 7, "max": 9, "std": 0.7},
    "consistency": {"mean": 7.0, "min": 5, "max": 8, "std": 1.0},
    "difficulty_fairness": {"mean": 7.8, "min": 7, "max": 9, "std": 0.6},
    "overall": {"mean": 7.5, "min": 6, "max": 9, "std": 0.8}
  },
  "n_raters": 8
}
```

### Environment Self-Assessment

The environment also rates itself:

```json
{
  "self_assessment": {
    "consistency_challenges": "Struggled to maintain consistent demand
      response to price changes. Need better calibration to the multinomial
      logit baseline.",
    "narrative_pride": "The firm dossier evolution was rich and coherent.",
    "lessons_for_next_run": "Should reference the demand model baseline more
      explicitly when determining market shares."
  }
}
```

---

## Part 3: Cross-Run Policy Database

### What Gets Stored (data/scores.csv)

Append-only CSV accumulating across all runs:

| Column | Description |
|--------|-------------|
| run_id | Run identifier |
| seed | Random seed |
| information_regime | Regime used |
| measurement_regime | Regime used |
| n_firms_initial | Starting firm count |
| n_quarters | Simulation length |
| actor_id | Agent identifier |
| actor_type | firm / ibank / cbank / cfund / environment |
| incarnation | For firms |
| fingerprint_style | Agent personality style |
| fingerprint_risk | Risk appetite |
| -- Financial scores -- | |
| equity_irr_annual | For firms |
| equity_multiple | For firms |
| loss_rate | For institutions |
| debt_irr_annual | For institutions |
| pricing_rmse | For investment bank |
| -- Operational metrics -- | |
| max_generation | For firms |
| avg_market_share | For firms |
| lifespan_quarters | For firms |
| exit_type | For firms |
| -- Strategy summary -- | |
| avg_rd_pct_revenue | For firms |
| avg_capex_pct_revenue | For firms |
| avg_sga_pct_revenue | For firms |
| avg_leverage | For firms |
| pricing_strategy | "premium" / "competitive" / "aggressive" |
| -- Environment ratings -- | |
| env_rating_overall | 1-10 |
| env_rating_realism | 1-10 |
| env_rating_consistency | 1-10 |

### How Agents Use the Policy Database

When building cross-run context for an agent's prompt:

```python
def build_policy_context(agent_type, agent_fingerprint, scores_db):
    """What can this agent learn from past runs?"""

    if agent_type == "firm":
        # Find past firms with similar fingerprint
        similar = scores_db.query(
            actor_type="firm",
            fingerprint_style=agent_fingerprint.style,
            risk_appetite_range=(agent_fingerprint.risk - 0.2, agent_fingerprint.risk + 0.2)
        )

        # What strategies worked?
        winners = similar[similar.equity_irr_annual > 0.15]
        losers = similar[similar.exit_type == "default"]

        return f"""
        LESSONS FROM PAST SIMULATIONS:
        - Firms with your profile (style={agent_fingerprint.style}) that achieved
          >15% annual equity IRR typically: invested {winners.avg_rd_pct_revenue.mean():.0%}
          of revenue in R&D, maintained leverage below {winners.avg_leverage.mean():.1f}x,
          and reached Gen 2 within {winners.gen2_quarter.median():.0f} quarters.
        - Firms that defaulted typically: had average leverage of {losers.avg_leverage.mean():.1f}x,
          invested only {losers.avg_rd_pct_revenue.mean():.0%} in R&D, and never advanced
          beyond Gen 1.
        - Environment realism ratings in past runs averaged {scores_db.env_rating_overall.mean():.1f}/10.
        """

    elif agent_type == "environment":
        # What made past environments highly rated?
        top_envs = scores_db.query(actor_type="environment", env_rating_overall__gte=8)
        low_envs = scores_db.query(actor_type="environment", env_rating_overall__lte=5)

        return f"""
        LESSONS FROM PAST SIMULATIONS:
        - Highly rated environments (8+/10) were characterized by: consistent demand
          responses to price/quality changes, well-timed events with realistic
          consequences, rich and specific narratives.
        - Poorly rated environments were criticized for: erratic demand allocation,
          too many or too few events, narratives that contradicted established facts.
        """
```

---

## Part 4: What Gets Measured per Run

### Run-Level Summary (data/run_summaries.csv)

One row per run:

| Metric | Description |
|--------|-------------|
| run_id | |
| seed | |
| n_quarters_completed | May be < planned if early termination |
| n_firms_initial | |
| n_defaults | Total firm defaults during run |
| n_entries | Total new entrants |
| n_acquisitions | Total M&A transactions |
| n_institution_failures | |
| total_industry_revenue | Sum of all firm revenue, all quarters |
| avg_hhi | Average market concentration |
| max_generation_achieved | Highest product gen reached by any firm |
| avg_env_rating | Mean environment rating from all agents |
| best_firm_irr | Highest equity IRR among surviving firms |
| worst_firm_irr | Lowest (or default) |
| avg_firm_irr | Mean across all incarnations |
| avg_loss_rate | Mean across lending institutions |
| information_regime | |
| measurement_regime | |
| wall_clock_seconds | How long the run took |

### Run-Level Comparison (across runs)

The inspection UI (doc 13) uses `run_summaries.csv` to compare runs:
- Same seed, different regimes: how do outcomes differ?
- Different seeds, same regime: how variable are outcomes?
- Cross-seed averages: what is the "typical" outcome under each regime?

---

## Configuration

```yaml
scoring:
  # Financial scoring
  risk_free_rate_for_irr: "from_simulation"   # use actual r_f or fixed
  terminal_value_method: "market_price"        # market_price | dcf_estimate | book_value
  min_quarters_for_irr: 4                      # need 4+ quarters for meaningful IRR

  # Environment rating
  rate_environment: true
  rating_dimensions: ["market_realism", "event_realism", "narrative_quality",
                       "consistency", "difficulty_fairness", "overall"]

  # Policy database
  policy_db_path: "data/scores.csv"
  run_summaries_path: "data/run_summaries.csv"
  include_policy_context_in_prompts: true
  max_policy_context_tokens: 1000
```
