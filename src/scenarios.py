"""
Wave zeta: scenario library.

Heterogeneous founding conditions per firm. Previously every firm IPO'd
at identical terms ($175M raised, 10M shares at $17.50, $25M PPE pilot).
Real industries are heterogeneous, so we parameterize per-firm.

Scenarios live as YAML files in `scenarios/`. Each scenario defines:
  - Per-firm founding cash, shares, IPO price, PPE, capability, brand,
    base unit cost, CEO base salary.
  - Overall industry parameters (if different from SimParams defaults).

The orchestrator's `initialize_world()` checks for `config.scenario` and,
if set, loads `scenarios/<name>.yaml` and applies per-firm founding.

Backward compatibility: if no scenario is specified, the existing uniform
$17.50 IPO path is used unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class FirmFoundingParams:
    """Founding conditions for one firm in a scenario."""
    firm_id: str
    founding_cash: float = 150_000_000         # cash at founding (post-IPO)
    ipo_price: float = 17.50                   # $/share at IPO
    ipo_shares: int = 10_000_000               # shares outstanding at IPO
    founding_ppe_gross: float = 25_000_000     # pilot plant
    founding_capability: float = 10.0           # 0-100
    founding_brand: float = 5.0                 # 0-100
    base_unit_cost: float = 14_000             # Gen 1 cost
    ceo_base_salary: float = 1_000_000         # annual
    # Optional: custom CEO type (if not set, env_secrets assigns)
    ceo_type: str = ""


@dataclass
class IndustryCharacter:
    """Narrative guidance about the industry for LLM agents.

    This is free-form text passed to firm + environment + analyst prompts
    so that the scenario defines the industry's economic reality rather
    than hardcoded prompt text. Supports both expansionary scenarios
    (e.g. "longevity breakthrough, TAM $1T+") and contracting ones
    (e.g. "declining ICE engine industry, shrinking TAM"). Agents MUST
    form their strategies in light of this guidance.
    """
    # Industry-level narrative — shown to firms + env + analysts.
    # Should cover: TAM, growth trajectory, scientific/regulatory context,
    # demand elasticity, competitive intensity expectation, time horizons.
    narrative: str = ""
    # Short label ("biotech growth", "mature industry", "declining") used
    # in summaries and dashboards.
    label: str = "unspecified"
    # Implied total industry TAM at maturity, in dollars. Used to size
    # market signals shown to firms. None = use SimParams default.
    tam_at_maturity_usd: float | None = None
    # Expected years to market maturity — shapes firm planning horizons.
    years_to_maturity: float | None = None


@dataclass
class MarketParams:
    """Optional scenario-level overrides for demand/market mechanics.

    Any field left None inherits from `SimParams` / `MacroState`. Setting
    these lets a scenario model a genuinely different industry (bigger
    TAM, faster awareness, different price elasticity, etc.) without
    editing global defaults.
    """
    market_size_baseline: float | None = None      # aware-population base
    awareness_rate: float | None = None             # fraction aware each Q
    outside_utility_base: float | None = None       # v0 starting value (logit)
    outside_utility_decay: float | None = None      # v0 decay per Q
    outside_utility_floor: float | None = None      # v0 minimum
    price_coef: float | None = None                 # logit price coefficient (b)
    quality_coef: float | None = None               # logit quality coefficient (a)
    brand_coef: float | None = None                 # logit brand coefficient (g)
    affordability_center: float | None = None       # sigmoid center (price where 50% can pay)
    affordability_steepness: float | None = None    # sigmoid steepness
    # Wave ν+4: Gen 2 R&D threshold (scenario-tunable). When set,
    # overrides SimParams.gen_2_rd_threshold so different scenarios can
    # calibrate the R&D ladder steepness. Lower = Gen 2 reachable in
    # shorter runs.
    gen_2_rd_threshold: float | None = None


@dataclass
class ScenarioConfig:
    """Full scenario: list of firm foundings + optional industry overrides."""
    name: str
    description: str = ""
    firms: list[FirmFoundingParams] = field(default_factory=list)
    # Industry-level narrative + quantitative overrides.
    industry_character: IndustryCharacter = field(default_factory=IndustryCharacter)
    market_params: MarketParams = field(default_factory=MarketParams)
    # Legacy catch-all for any SimParams fields not covered above (kept
    # for backward compat with existing scenario YAMLs).
    industry_overrides: dict = field(default_factory=dict)


def load_scenario(path: str | Path) -> ScenarioConfig:
    """Load a scenario YAML file."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Scenario not found: {path}")
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    firms = [
        FirmFoundingParams(
            firm_id=f.get("firm_id", f"firm_{i}"),
            founding_cash=float(f.get("founding_cash", 150_000_000)),
            ipo_price=float(f.get("ipo_price", 17.50)),
            ipo_shares=int(f.get("ipo_shares", 10_000_000)),
            founding_ppe_gross=float(f.get("founding_ppe_gross", 25_000_000)),
            founding_capability=float(f.get("founding_capability", 10.0)),
            founding_brand=float(f.get("founding_brand", 5.0)),
            base_unit_cost=float(f.get("base_unit_cost", 14_000)),
            ceo_base_salary=float(f.get("ceo_base_salary", 1_000_000)),
            ceo_type=str(f.get("ceo_type", "")),
        )
        for i, f in enumerate(raw.get("firms", []))
    ]
    # Industry character (narrative + labels)
    ic_raw = raw.get("industry_character", {}) or {}
    industry_character = IndustryCharacter(
        narrative=str(ic_raw.get("narrative", "")),
        label=str(ic_raw.get("label", "unspecified")),
        tam_at_maturity_usd=(
            float(ic_raw["tam_at_maturity_usd"])
            if ic_raw.get("tam_at_maturity_usd") is not None else None
        ),
        years_to_maturity=(
            float(ic_raw["years_to_maturity"])
            if ic_raw.get("years_to_maturity") is not None else None
        ),
    )
    # Market parameter overrides
    mp_raw = raw.get("market_params", {}) or {}
    def _opt_float(key):
        v = mp_raw.get(key)
        return float(v) if v is not None else None
    market_params = MarketParams(
        market_size_baseline=_opt_float("market_size_baseline"),
        awareness_rate=_opt_float("awareness_rate"),
        outside_utility_base=_opt_float("outside_utility_base"),
        outside_utility_decay=_opt_float("outside_utility_decay"),
        outside_utility_floor=_opt_float("outside_utility_floor"),
        price_coef=_opt_float("price_coef"),
        quality_coef=_opt_float("quality_coef"),
        brand_coef=_opt_float("brand_coef"),
        affordability_center=_opt_float("affordability_center"),
        affordability_steepness=_opt_float("affordability_steepness"),
        gen_2_rd_threshold=_opt_float("gen_2_rd_threshold"),
    )
    return ScenarioConfig(
        name=raw.get("name", path.stem),
        description=raw.get("description", ""),
        firms=firms,
        industry_character=industry_character,
        market_params=market_params,
        industry_overrides=raw.get("industry_overrides", {}),
    )


def default_scenario(n_firms: int) -> ScenarioConfig:
    """Legacy-compatible default: all firms start identical.

    Preserves backward compatibility when no scenario specified.
    """
    return ScenarioConfig(
        name="uniform_default",
        description="Legacy uniform IPO: all firms identical founding.",
        firms=[
            FirmFoundingParams(firm_id=f"firm_{i}")
            for i in range(n_firms)
        ],
    )
