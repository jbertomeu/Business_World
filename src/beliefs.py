"""
Wave epsilon: explicit belief / signal / memory layers.

Enforces CLAUDE principle 17 (separate latent / signal / report) by making
beliefs first-class state. Previously, agent prompts effectively fed agents
the TRUE state (even for quantities that would realistically be observed
with noise in practice). This module adds:

- `FirmBelief`: firm's estimate of demand, peer prices, macro. Updated
  by the orchestrator from noisy observations.
- `ActivistMemory`, `AuditorMemory`, `SECMemory`: non-firm agents carry
  persistent learning across quarters (who they've engaged with, what
  strategies worked, what red flags showed up).
- `add_observation_noise`: deterministic seeded noise for numerical
  signals. Toggle via `config.noisy_signals_enabled`.

MINIMAL wire for this wave:
- Types defined + tests exist.
- noisy_signals_enabled config toggle.
- One demo path: when toggle is on, firms observe PEER data (not their
  own) with noise and 1-quarter lag. Their own books are perfect (the
  firm knows what's in its own bank account).
- Non-firm agent memories stored on WorldState; each agent's prompt
  builder can read its own memory. Wiring the PROMPTS to actually use
  the memory is a follow-on pass.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field


# ── Firm beliefs ───────────────────────────────────────────────────────

@dataclass
class FirmBelief:
    """One firm's subjective beliefs about itself, peers, and the market.

    For Wave epsilon we track the minimal set needed to demonstrate the
    mechanism. A future pass can add prior/posterior distributions,
    confidence intervals, and Bayesian updating.
    """
    firm_id: str
    quarter_observed: int = 0
    # Estimated total industry demand (noisy observation of prior-Q gazette)
    estimated_total_demand: float = 0.0
    # Estimated peer prices (firm_id → price). Lagged + noisy.
    estimated_peer_prices: dict = field(default_factory=dict)
    # Estimated peer revenues (lagged + noisy)
    estimated_peer_revenue: dict = field(default_factory=dict)
    # Scalar confidence (0-1): how much the firm trusts its estimates.
    confidence: float = 1.0


# ── Non-firm agent memories ────────────────────────────────────────────

@dataclass
class ActivistMemory:
    """Stateful memory for the activist investor agent across quarters.

    Tracks campaign history and outcomes so the LLM can reference prior
    experience in new demands. `strategy_effectiveness` could be
    populated from firm_response outcomes.
    """
    activist_id: str = "activist_1"
    campaigns_launched: list = field(default_factory=list)    # list of (quarter, firm_id, demand_type, outcome)
    strategy_effectiveness: dict = field(default_factory=dict)  # demand_type → avg acceptance rate


@dataclass
class AuditorMemory:
    """Stateful memory for an auditor agent.

    `client_history[firm_id]` lists past (fyear, opinion, findings,
    going_concern). `red_flag_patterns` captures anomalies seen across
    clients.
    """
    auditor_id: str = ""
    client_history: dict = field(default_factory=dict)         # firm_id → [ {fyear, opinion, findings, going_concern} ]
    red_flag_patterns: list = field(default_factory=list)      # global learnings


@dataclass
class SECMemory:
    """Stateful memory for the SEC agent."""
    firm_priors: dict = field(default_factory=dict)            # firm_id → float (0-1 prior misconduct risk)
    aging_investigations: dict = field(default_factory=dict)   # firm_id → quarters_open
    enforcement_history: list = field(default_factory=list)    # list of (quarter, firm_id, action)


# ── Noise helpers ──────────────────────────────────────────────────────

def add_observation_noise(value: float, rng: random.Random,
                             relative_sd: float = 0.05) -> float:
    """Add mean-zero Gaussian noise to a scalar observation.

    `relative_sd` is the standard deviation as a fraction of `value`.
    Bounded at 0 lower (prices and revenues don't go negative).
    """
    if value == 0:
        return 0.0
    noisy = value + rng.gauss(0.0, abs(value) * relative_sd)
    return max(0.0, noisy)


def ewma_update(prior: float | None, observation: float,
                alpha: float = 0.5) -> float:
    """Exponentially-weighted moving average update.

    `prior` is the prior belief; `observation` is the new noisy signal.
    `alpha` ∈ [0, 1] is the weight on the new observation. alpha = 1.0
    ignores history; alpha = 0.0 ignores new info.

    If `prior` is None (no prior), returns `observation` unchanged.
    """
    if prior is None:
        return observation
    return alpha * observation + (1 - alpha) * prior


def update_firm_belief(belief, peer_observations: dict,
                         quarter: int, alpha: float = 0.5):
    """Fold new noisy peer observations into a FirmBelief via EWMA.

    `peer_observations` maps peer_fid → {"price": float, "revenue": float}
    (already noised; typically comes from observe_peer_data).

    Mutates `belief` in place and returns it.
    """
    belief.quarter_observed = quarter
    for peer_fid, obs in peer_observations.items():
        price = obs.get("price")
        rev = obs.get("revenue")
        if price is not None:
            prior_price = belief.estimated_peer_prices.get(peer_fid)
            belief.estimated_peer_prices[peer_fid] = ewma_update(
                prior_price, price, alpha,
            )
        if rev is not None:
            prior_rev = belief.estimated_peer_revenue.get(peer_fid)
            belief.estimated_peer_revenue[peer_fid] = ewma_update(
                prior_rev, rev, alpha,
            )
    return belief


def observe_peer_data(peer_public_info: dict, rng: random.Random,
                        relative_sd: float = 0.05) -> dict:
    """Produce a noisy, possibly lagged observation of peer public data.

    `peer_public_info` is the peer's public fields (price, revenue,
    market_share, equity_price, generation, total_rd_spend).

    Returns a copy with numerical fields noised. Preserves keys and
    non-numeric values. Designed to be called on the peer data that
    would otherwise be passed directly to the firm prompt.
    """
    out = dict(peer_public_info)
    for k in ("price", "revenue", "market_share", "equity_price",
              "total_rd_spend"):
        if k in out and isinstance(out[k], (int, float)):
            out[k] = add_observation_noise(float(out[k]), rng, relative_sd)
    return out
