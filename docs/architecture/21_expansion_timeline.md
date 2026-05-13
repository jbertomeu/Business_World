# 21. Expansion: Quarterly Timeline & Agent Flow (v0.5)

## Overview

The v0.5 expansion adds 9 new modules and 7 new agent roles to the simulation.
All features are toggleable — default OFF for backward compatibility.

## Quarterly Phase Timeline

```
EVERY QUARTER:

  Phase 1:  MACRO ADVANCE (existing)
            - Calendar, risk-free rate, awareness, demand shock, taste shocks
            - NEW: political_uncertainty, market_return_ytd, market_risk_premium

  Phase 2:  IPO / ENTRY (existing)
            - New firms receive $175M IPO

  Phase 3:  M&A BIDDING + RESOLUTION               [if ma_enabled]
            - Each firm considers bidding for competitors (LLM call)
            - Target board evaluates bids (LLM call)
            - Hostile override if bid > 150% of equity price
            - Consolidation: goodwill, capacity absorption, integration cost

  Phase 4:  SEC SURVEILLANCE                        [if sec_enabled]
            - Detection probability computed for manipulating firms
            - SEC agent scans all firms for red flags (LLM call)
            - Investigation state machine: none -> watching -> investigating
              -> private_contact -> aaer_pending -> resolved
            - Firms notified when privately contacted

  Phase 5:  FIRM DECISIONS (existing)
            - Board discussion + CEO decision (LLM calls per firm)
            - NEW: manipulation_amount in decision JSON [if earnings_management_enabled]

  Phase 6:  CLAMPING (existing)
            - Enforce cash feasibility
            - manipulation_amount passed through

  Phase 7:  ENVIRONMENT / MARKET (existing)
            - Demand allocation, events, gazette narrative (LLM call)

  Phase 8:  ACCOUNTING (existing)
            - IS, BS, CF posting
            - NEW: manipulation injected into reported_net_income
            - cumulative_manipulation updated on FirmState

  Phase 9:  EARNINGS ANNOUNCEMENT                   [if earnings_announcement_enabled]
            - Each firm produces public earnings release (reuses firm LLM)
            - Reported EPS, management discussion, EPS guidance (1Q + 1Y ahead)
            - Stored in WorldState.earnings_releases (public)

  Phase 10: SELL-SIDE ANALYST COVERAGE              [if sellside_analysts_enabled]
            - 3 analysts with staggered schedule:
              Analyst 1 (DCF): publishes Q1, Q3
              Analyst 2 (Comparables): publishes Q2, Q4
              Analyst 3 (Contrarian): publishes Q1, Q4
            - Each active analyst produces brokerage notes (LLM call)
            - Notes include EPS forecasts, target price, buy/hold/sell rating
            - Stored in WorldState.analyst_notes (public)

  Phase 11: EQUITY MARKET (existing)
            - Prices all firms (LLM call)
            - Now sees analyst notes + earnings releases in prompt

  Phase 12: INVESTMENT BANK (existing)
            - Term debt + equity structuring (LLM call)

  Phase 13: COMMERCIAL BANK (existing)
            - Revolver terms (LLM call)

  Phase 14: SEC ENFORCEMENT                         [if sec_enabled]
            - Process AAER actions for firms with aaer_pending status
            - Force restatement if restatements_enabled
            - Log enforcement actions

  Phase 15: SETTLEMENT & SOLVENCY (existing)
            - Emergency financing, default detection

ANNUAL (fqtr == 4):

  Phase A1: AUDITOR ANNUAL AUDIT                    [if auditor_enabled]
            - 4 named audit firms, each a separate LLM
            - Reviews 4Q of financials, issues opinion
            - Opinions: unqualified | qualified | adverse
            - Can force restatement if adverse + restatements_enabled
            - Audit fee computed from firm size + risk

  Phase A2: BOARD GOVERNANCE / CEO REVIEW           [if governance_enabled]
            - Dedicated governance LLM evaluates CEO performance
            - Sets compensation (base, bonus, equity)
            - Can fire CEO -> search (1Q gap), new type assigned
            - CEO history logged for ExecuComp dataset

  Phase 16: RECORD-KEEPING (existing, expanded)
```

## Agent Roster (all roles)

| Agent | Roster ID | LLM Call Frequency | Information Access |
|-------|-----------|-------------------|-------------------|
| Firm 1-8 | firm_1..firm_8 | Every Q (board + decision) | Own private + public |
| Environment | environment | Every Q | Omniscient |
| Equity Market | equity_market | Every Q | Public + analyst notes |
| Investment Bank | investment_bank | Every Q | Public + requests |
| Commercial Bank | commercial_bank | Every Q | Public |
| Data Analyst | data_analyst | On-demand | Public + cross-run DB |
| Analyst 1-3 | analyst_1..analyst_3 | Staggered (2 per Q) | Public only |
| SEC | sec | Every Q | Public + own investigations |
| Auditor 1-4 | auditor_1..auditor_4 | Annual Q4 | Client financials + env hints |
| Board Governance | board_governance | Annual Q4 | Own firm performance |
| Earnings Announcer | (firm's own LLM) | Every Q | Own firm results |
| M&A | (firm LLMs) | Every Q | Own + target public |

## LLM Calls Per Quarter (all features ON, 5 firms)

Regular quarter: ~25-30 calls
- 5 firms x 2 (board + decision) = 10
- 1 environment = 1
- 3 financial = 3
- 1 SEC = 1
- 5 earnings announcements = 5
- ~2 analysts (staggered) = 2
- Total: ~22

Annual Q4: ~35-40 calls
- Regular quarter: 22
- 5 audits = 5
- 5 governance reviews = 5
- Total: ~32

## Toggle Reference

```yaml
# In config YAML or RunConfig:
earnings_management_enabled: false    # Firms can manipulate reported earnings
sec_enabled: false                    # SEC surveillance + enforcement
sellside_analysts_enabled: false      # 3 sell-side analyst agents
sellside_analyst_count: 3             # Number of analysts
auditor_enabled: false                # Annual audit by named firms
governance_enabled: false             # Annual CEO review + compensation
earnings_announcement_enabled: false  # Public earnings releases + guidance
restatements_enabled: false           # Dual-column Compustat (as-reported + restated)
ma_enabled: false                     # M&A bidding + consolidation
macro_expansion_enabled: false        # Political uncertainty, market returns
template_id: "longevity_drug"         # Industry template (hook for future)
```

## Data Flow: Who Sees What

```
PRIVATE (firm only):
  Board minutes, manipulation amount, R&D details, capability stock, brand stock

PUBLIC (all agents):
  Compustat, gazette, analyst notes, earnings releases, audit opinions,
  M&A bids (when announced), AAER actions

HIDDEN (environment only):
  World secrets, CEO types, true manipulation amounts, detection events

RESTRICTED:
  SEC: sees own investigation history + detection tips (from environment)
  Auditor: sees client's financials + environment hints (not raw manipulation)
  Board governance: sees own firm only (not CEO type)
```
