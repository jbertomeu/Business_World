"""
Earnings management mechanics.

Pure math — no LLM calls. Firms choose a manipulation amount (+ = overstate,
- = understate). A cumulative stock of manipulation builds up. Detection
probability is a function of that stock (asymmetric: overstatement riskier).

Detection does not happen here — the environment agent decides when to
reveal detection events. This module only computes the probability.

Tunable parameters are in SimParams (added in v0.5).
"""

from __future__ import annotations

import math
import random


# ── Detection probability defaults ──────────────────────────────────────
# These can be moved to SimParams if per-run tuning is needed.

# Cumulative overstatement at which detection probability = 50%
DETECTION_MIDPOINT = 50_000_000  # $50M

# Steepness of the sigmoid (higher = sharper transition)
DETECTION_STEEPNESS = 5e-8

# Understatement detection is this fraction of overstatement detection
UNDERSTATEMENT_DISCOUNT = 0.5


def apply_manipulation(
    true_net_income: float,
    manipulation_amount: float,
    prior_cumulative: float,
) -> tuple[float, float]:
    """Apply earnings manipulation to true net income.

    Args:
        true_net_income: NI from accounting (before manipulation)
        manipulation_amount: + = overstate, - = understate. Chosen by firm.
        prior_cumulative: running stock from prior quarters.

    Returns:
        (reported_net_income, new_cumulative_stock)
    """
    reported_ni = true_net_income + manipulation_amount
    new_cumulative = prior_cumulative + manipulation_amount
    return reported_ni, new_cumulative


def detection_probability(cumulative_stock: float) -> float:
    """DEPRECATED — retained for test compatibility only.

    Stage 2a replaced this hardcoded sigmoid with the environment LLM's
    emergent `detection_tips` output (see `build_environment_prompt` +
    `state.pending_detection_tips` → SEC). The env is omniscient about
    firms' true vs reported financials and judges when an external observer
    (auditor, short-seller, regulator) would realistically notice anomalies.

    This function is no longer called in the production pipeline. It remains
    only so existing tests continue to pass. Remove the tests and this
    function together in a future cleanup.
    """
    if abs(cumulative_stock) < 1.0:
        return 0.0
    magnitude = abs(cumulative_stock)
    base_prob = 1.0 / (1.0 + math.exp(-DETECTION_STEEPNESS * (magnitude - DETECTION_MIDPOINT)))
    if cumulative_stock < 0:
        return base_prob * UNDERSTATEMENT_DISCOUNT
    return base_prob


def check_detection(prob: float, rng: random.Random) -> bool:
    """DEPRECATED — see `detection_probability` docstring. Retained for tests."""
    if prob <= 0:
        return False
    return rng.random() < prob
