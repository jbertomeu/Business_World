"""Schema definitions for each LLM-agent JSON output that we validate.

Schemas are intentionally permissive on additional fields (LLMs add
flavor; we don't want to fail on benign extras) and strict on the
required fields and types our parsers consume. Each schema's name is
the string passed to `validate(...)` from the consuming code.

Schemas covered (Wave ν+10 item 2):

  * ``env_market_outcome`` — environment per-quarter market resolution
    (the bug-H1 site)
  * ``equity_panel_response`` — single panelist's per-firm valuation list
  * ``auction_judge_response`` — auction allocations
  * ``auction_bidder_response`` — single bidder's bid list
  * ``commercial_bank_response`` — credit-committee per-firm decision
  * ``investment_bank_response`` — equity/bond placement decisions
  * ``firm_decision`` — quarterly operating + financing JSON from a firm

If your parser reads a field and the schema doesn't include it, the
schema needs updating. The acid test: change the consuming parser's
expected key, run the schema-tests, and they should fail.
"""
from __future__ import annotations

from .registry import register


# ─────────────────────────────────────────────────────────────────────────
# Environment per-quarter market resolution. Both firm_outcomes and the
# top-level rd_outcomes array are required; the orchestrator merges
# them post-receipt (Wave ν+9 H1 fix).
# ─────────────────────────────────────────────────────────────────────────
register("env_market_outcome", {
    "type": "object",
    "required": ["firm_outcomes"],
    "properties": {
        "firm_outcomes": {
            # Either a list of {firm_id, units_sold, market_share, ...}
            # or a dict keyed by firm_id with the same payload. Both
            # shapes appear in the wild; downstream merger normalizes.
            "oneOf": [
                {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["firm_id"],
                        "properties": {
                            "firm_id": {"type": "string"},
                            "units_sold": {"type": "integer", "minimum": 0},
                            "market_share": {
                                "type": "number", "minimum": 0, "maximum": 1
                            },
                            "product_advance": {"type": "boolean"},
                            "delivery_advance": {"type": "boolean"},
                            "process_cogs_reduction_pct": {
                                "type": "number", "minimum": 0, "maximum": 1
                            },
                        },
                    },
                },
                {"type": "object"},  # dict-keyed shape; permissive
            ],
        },
        "rd_outcomes": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["firm_id"],
                "properties": {
                    "firm_id": {"type": "string"},
                    "product_advance": {"type": "boolean"},
                    "delivery_advance": {"type": "boolean"},
                    "process_cogs_reduction_pct": {
                        "type": "number", "minimum": 0, "maximum": 1
                    },
                },
            },
        },
        "total_demand": {"type": ["integer", "number"], "minimum": 0},
        "narrative": {"type": "string"},
    },
})


# ─────────────────────────────────────────────────────────────────────────
# Equity panel: single analyst's per-firm response
# ─────────────────────────────────────────────────────────────────────────
register("equity_panel_response", {
    "type": "object",
    "required": ["firms"],
    "properties": {
        "firms": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["firm_id", "equity_price"],
                "properties": {
                    "firm_id": {"type": "string"},
                    "equity_price": {"type": ["number", "integer"], "minimum": 0},
                    "valuation_method": {"type": "string"},
                    "reasoning": {"type": "string"},
                },
            },
        },
    },
})


# ─────────────────────────────────────────────────────────────────────────
# Auction judge response
# ─────────────────────────────────────────────────────────────────────────
register("auction_judge_response", {
    "type": "object",
    "required": ["allocations"],
    "properties": {
        "allocations": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["target_firm_id"],
                "properties": {
                    "target_firm_id": {"type": "string"},
                    "winner_id": {"type": "string"},
                    "winning_amount": {"type": ["number", "integer"]},
                    "rationale": {"type": "string"},
                },
            },
        },
        "_error": {"type": "boolean"},
        "_exception": {"type": "string"},
    },
})


# ─────────────────────────────────────────────────────────────────────────
# Auction bidder response
# ─────────────────────────────────────────────────────────────────────────
register("auction_bidder_response", {
    "type": "object",
    "required": ["bids"],
    "properties": {
        "bids": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["target_firm_id"],
                "properties": {
                    "target_firm_id": {"type": "string"},
                    "bid_amount": {"type": ["number", "integer", "string"]},
                    "rationale": {"type": "string"},
                },
            },
        },
        "_error": {"type": "boolean"},
        "_exception": {"type": "string"},
    },
})


# ─────────────────────────────────────────────────────────────────────────
# Commercial bank credit committee response
# ─────────────────────────────────────────────────────────────────────────
register("commercial_bank_response", {
    "type": "object",
    "required": ["firms"],
    "properties": {
        "firms": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["firm_id"],
                "properties": {
                    "firm_id": {"type": "string"},
                    "revolver_commitment": {"type": ["number", "integer"], "minimum": 0},
                    "revolver_rate_quarterly": {"type": ["number", "integer"], "minimum": 0},
                    "risk_assessment": {"type": "string"},
                    "reasoning": {"type": "string"},
                },
            },
        },
    },
})


# ─────────────────────────────────────────────────────────────────────────
# Investment bank response (equity + bond decisions per firm)
# ─────────────────────────────────────────────────────────────────────────
register("investment_bank_response", {
    "type": "object",
    "required": ["firms"],
    "properties": {
        "firms": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["firm_id"],
                "properties": {
                    "firm_id": {"type": "string"},
                    "equity_decision": {"type": "string"},
                    "equity_proceeds": {"type": ["number", "integer"], "minimum": 0},
                    "bond_decision": {"type": "string"},
                    "bond_principal": {"type": ["number", "integer"], "minimum": 0},
                    "bond_coupon": {"type": ["number", "integer"], "minimum": 0},
                    "rejection_reason": {"type": "string"},
                    "market_discussion": {"type": "string"},
                },
            },
        },
    },
})


# ─────────────────────────────────────────────────────────────────────────
# Firm quarterly decision (firm CFO output)
# ─────────────────────────────────────────────────────────────────────────
register("firm_decision", {
    "type": "object",
    # Only the most-consumed fields are required; the rest are optional
    # to keep this permissive while we expand coverage.
    "required": ["production", "price"],
    "properties": {
        "production": {"type": ["integer", "number"], "minimum": 0},
        "price": {"type": ["number", "integer"], "minimum": 0},
        "rd_spend": {"type": ["number", "integer"], "minimum": 0},
        "sga_spend": {"type": ["number", "integer"], "minimum": 0},
        "capex": {"type": ["number", "integer"], "minimum": 0},
        "dividend_per_share": {"type": ["number", "integer"], "minimum": 0},
        "buyback_target": {"type": ["number", "integer"], "minimum": 0},
        "manipulation_amount": {"type": ["number", "integer"]},
        "strategic_memo": {"type": "string"},
    },
})


# ─────────────────────────────────────────────────────────────────────────
# Sell-side analyst note
# ─────────────────────────────────────────────────────────────────────────
register("sellside_analyst_note", {
    "type": "object",
    "required": ["firm_id"],
    "properties": {
        "firm_id": {"type": "string"},
        "eps_forecast_1q": {"type": ["number", "integer"]},
        "eps_forecast_1y": {"type": ["number", "integer"]},
        "target_price": {"type": ["number", "integer"], "minimum": 0},
        "rating": {
            "type": "string",
            "enum": ["buy", "hold", "sell", "strong_buy", "strong_sell",
                     "neutral", "outperform", "underperform"],
        },
        "methodology": {"type": "string"},
        "narrative": {"type": "string"},
    },
})
