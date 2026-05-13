"""
Wave ν+2: endogenous firm entry.

When `endogenous_entry_enabled` is ON, firms do NOT all spawn at Q1.
Instead:
  - Q1 starts with a small cohort (default: max(3, n_firms // 4)).
  - Each subsequent quarter, an env-LLM judges whether the industry
    attractiveness + capital availability + maturity warrant a new
    entrant. If yes, a new firm is spawned (within `n_firms_max` cap)
    using public technology (current public-knowledge generation,
    publicly-observable cost benchmarks, modest starting capability).
  - As the industry matures (incumbent share consolidation, time
    elapsed), the env should find entry less attractive — new entrants
    face entrenched competitors.

The entry decision is QUALITATIVE: the env reads industry state (no
hardcoded thresholds in the prompt) and judges whether entry is
plausible. New firms enter as PRIVATE (founded stage) when
pe_lifecycle is on, or as legacy public IPO when off.
"""

from __future__ import annotations

import random as _random
from dataclasses import replace as _dc_replace

from .types import FirmState
from .governance import CEO_TYPES


ENTRY_JUDGE_SYSTEM_PROMPT = """You are the market environment judging whether a new entrant is plausible THIS QUARTER given the state of the industry.

ASSESS THE OPPORTUNITY EACH QUARTER (this is the central judgement):
Entry happens when a founder + investor pair see UNREALISED POTENTIAL. The question to ask yourself, each quarter, is:

  Given the industry's stated TAM (its long-run addressable market), the
  share of that potential ALREADY being captured by current incumbents,
  the technical and capital barriers a new entrant would face, and the
  fundraising climate they would meet — how much UNCAPTURED UPSIDE
  remains, and would a founder-investor pair see it as compelling
  enough to commit?

This is a judgement, not a formula. But read the industry honestly:
  - Big stated TAM, very little of it captured so far, few incumbents,
    fragmented share → enormous unrealised upside. Founders are drawn
    into these markets. Investors fund them. Multiple entrants per
    year is normal in this phase, sometimes per quarter when the
    science is hot.
  - TAM partially captured, several incumbents but no decisive winner,
    visible differentiation niches → meaningful upside still exists.
    Entry continues, often targeted at specific gaps.
  - Most of the TAM already captured by entrenched incumbents with
    deep brand + scale, narrow remaining niches → upside is constrained
    to displacement plays. Entry is harder; only differentiated or
    leapfrog candidates appear.
  - Saturation: incumbents absorb essentially all addressable demand,
    new entrants cannot find a foothold even with a credible product
    → entry effectively stops.

When several open slots remain AND the industry is far from its TAM
AND the visible competitive field is not entrenched, the typical real-
world outcome is more entry, not less. Dormant prior entrants are not
a deterrent — failed prior attempts are normal in industries with big
upside; the next founder still tries. If you've been declining entry
for many consecutive quarters in an early-stage, under-penetrated
industry, that itself is a sign your bar is too high.

You judge holistically. Inputs:
  - Industry character (scenario)
  - Time elapsed (entry usually thinner late in a TAM-realization curve)
  - Number of active incumbents and their share concentration
  - Whether incumbents are advancing generation or stuck
  - Recent defaults (creates entry opportunity in vacated niches)
  - Cap on total firms — slots remaining

LEAPFROG ENTRANTS:
A meaningful share of entrants are LEAPFROG candidates: they bring a
genuine technological breakthrough — a new modality, a synthesis advance,
a delivery innovation, a fundamental insight the incumbents missed.
Real-world examples of leapfrogs displacing incumbents:
  - Google entering search when Yahoo and AltaVista dominated
  - Apple disrupting personal computing
  - Microsoft writing DOS for IBM
  - mRNA vaccine companies leapfrogging traditional vaccine producers
In each case, the founders carried a fundamental technological insight
INTO the new firm — they didn't have to spend years catching up via R&D
spending. The breakthrough was already there.

Set leapfrog_candidate = true when:
  - There's a credible scientific or technical premise (industry context supports it)
  - Particularly when the market is concentrated or stagnant — a leapfrog
    is the most realistic threat to entrenched incumbents
  - You can describe the specific breakthrough in the narrative

Leapfrog entrants:
  - Have ALREADY-DEVELOPED technology — set starting_capability
    meaningfully higher than regular entrants to reflect this
  - Carry pre-credited cumulative product R&D (the breakthrough WORK
    is done; they didn't need to spend years on it)
  - Are funded more meaningfully — sophisticated investors back
    breakthroughs at higher valuations than greenfield startups

Incumbents may MIMIC the leapfrog over time (knowledge diffusion through
hiring, publications, patent expirations) — but only after a delay,
giving the leapfrog a window to scale up.

REGULAR entrants bring public-domain technology and a more modest
seed. They focus on niche differentiation, customer acquisition, and
incremental progress rather than a big-bang technology lead.

HETEROGENEOUS ENTRANTS (not all entrants are equally credible):
Real entry pools are not uniform in quality. Some founders bring
deep scientific backgrounds, others are weaker; some have credible
clinical-trial designs, others have wishful theses; some come with
distribution channels already secured, others rely on optimism. You
can reflect this by sometimes seeding entrants with weaker starting
fundamentals: a lower starting_capability than a leapfrog or strong
regular entrant would have, a more modest founder_capital_seed_usd, a
narrative that names a specific weakness ("the founding team's
clinical-trial experience is limited", "the synthesis route is
public-domain but the manufacturing cost edge is unproven", "the
distribution partnership is preliminary"). Their weakness need NOT be
obvious on day one — it will surface over time as their R&D
underperforms, their share fails to grow, or their next funding round
prices flat.

Avoid making every new entrant a strong candidate. A diverse pool of
strong, average, and weak entrants is what real entry looks like, and
it is what produces a natural shake-out downstream: the weak ones
fail, the strong ones survive, the average ones consolidate or get
acquired. Do not force this outcome — it should emerge from honest
entrant heterogeneity meeting honest competitive allocation.

SMALL FIRMS CAN STILL OPERATE PROFITABLY:
A founded firm doesn't NEED to chase Gen-2 R&D aggressively to survive.
A small efficient operator that:
  - Sells its existing-generation product at a margin
  - Holds R&D and SG&A to a modest level
  - Builds brand gradually
...should be able to operate at break-even or modest profit and persist
in the industry. Founder seed amounts should reflect this: enough to
launch operations, not necessarily enough to fund a Gen-2 program.

OUTPUT (JSON):
{{
  "should_spawn_entrant": <true|false>,
  "rationale": "<2-3 sentences justifying the decision>",
  "entrant_profile": {{
    "starting_capability": <0-100 — your judgment given entrant type and scenario>,
    "starting_brand": <0-100 — entrants typically start low>,
    "leapfrog_candidate": <true|false>,
    "starting_cumulative_product_rd_usd": <$ — pre-credited R&D from public tech / academic spinout; your judgment given entrant type>,
    "founder_capital_seed_usd": <$ — founder seed; your judgment given entrant type and scenario norms>,
    "narrative": "<1-2 sentences on what the entrant brings — for leapfrog candidates, describe the breakthrough specifically>"
  }}
}}

If should_spawn_entrant is false, populate entrant_profile with zeros + an empty narrative."""


def make_entry_judge(backend):
    """Factory: env-side LLM that decides whether a new firm enters this Q.

    Returns a callable (industry_summary, slots_remaining, recent_defaults, q_index) -> dict.
    """
    def judge_fn(
        industry_summary: str,
        slots_remaining: int,
        recent_defaults: int,
        q_index: int,
    ) -> dict | None:
        if slots_remaining <= 0:
            return {"should_spawn_entrant": False, "rationale": "no slots", "entrant_profile": {}}
        system = ENTRY_JUDGE_SYSTEM_PROMPT
        user = (
            f"CURRENT QUARTER: {q_index}\n"
            f"REMAINING ENTRY SLOTS: {slots_remaining}\n"
            f"RECENT DEFAULTS (last 4Q): {recent_defaults}\n\n"
            f"INDUSTRY STATE:\n{industry_summary}\n\n"
            "Decide whether a new entrant is plausible. Output JSON."
        )
        try:
            return backend.complete_json(system, user)
        except Exception:
            return None
    return judge_fn


def summarize_industry_for_entry_judge(state) -> str:
    """Build a compact industry-state summary for the entry judge.

    Includes: number of active firms, generation distribution, share
    concentration (HHI), recent default count, scenario context.
    Wave ν+12: also exposes the stated industry TAM and the recent
    industry annualized revenue so the judge can reason about the
    fraction of potential already captured — driving more entry when
    the industry is far from saturation.
    """
    active = [f for f in state.firms.values() if f.is_active]
    n_active = len(active)
    if n_active == 0:
        return "No active firms — industry is empty (or all incumbents have failed)."

    # Generation distribution
    gen_counts: dict[int, int] = {}
    for f in active:
        gen_counts[f.product_generation] = gen_counts.get(f.product_generation, 0) + 1
    gen_str = ", ".join(f"Gen{g}: {c}" for g, c in sorted(gen_counts.items()))

    # Share concentration via last-quarter revenues
    last_flows = state.last_quarter_flows or {}
    shares = []
    total_rev = 0.0
    for fid, fl in last_flows.items():
        rev = float(getattr(fl, "net_sales", 0) or 0)
        total_rev += rev
        shares.append((fid, rev))
    if total_rev > 0:
        norm = [(fid, rev / total_rev) for fid, rev in shares]
        hhi = sum((s * 100) ** 2 for _, s in norm)
        top_fid, top_share = max(norm, key=lambda x: x[1])
        share_text = (
            f"  Total revenue last Q: ${total_rev/1e6:.1f}M\n"
            f"  HHI: {hhi:.0f} (10000 = monopoly, low = fragmented)\n"
            f"  Largest player: {top_fid} ({top_share:.0%})"
        )
    else:
        share_text = "  No revenue yet — industry is still pre-revenue."

    if active:
        max_cap = max(f.capability_stock for f in active)
        avg_cap = sum(f.capability_stock for f in active) / len(active)
        cap_text = f"  Capability: max {max_cap:.0f}/100, avg {avg_cap:.0f}/100"
    else:
        cap_text = "  Capability: n/a"

    # Wave ν+12: TAM context for the judge. The stated TAM lives on the
    # scenario's industry_character. Recent industry annualized revenue
    # (last 4Q) approximates "what's already being captured". The judge
    # uses these together to gauge unrealised potential.
    tam_text = ""
    try:
        scenario = getattr(state, "_scenario", None)
        ic = getattr(scenario, "industry_character", None) if scenario else None
        tam_usd = getattr(ic, "tam_at_maturity_usd", 0.0) if ic else 0.0
        if tam_usd:
            # Compute trailing-4Q industry revenue (annual) from compustat rows
            current_abs_q = state.quarter
            annual_rev = 0.0
            for r in getattr(state, "compustat_rows", []):
                abs_q = (r.fyearq - 2031) * 4 + r.fqtr
                if current_abs_q - 4 < abs_q <= current_abs_q:
                    annual_rev += float(r.saleq or 0)
            captured_pct = (annual_rev / tam_usd * 100) if tam_usd > 0 else 0
            tam_text = (
                f"  Stated TAM at maturity (annual): ${tam_usd/1e9:.1f}B\n"
                f"  Trailing-4Q industry revenue (annualised): ${annual_rev/1e9:.1f}B\n"
                f"  Share of TAM already captured (rough): {captured_pct:.1f}%"
            )
    except Exception:
        tam_text = ""

    return (
        f"  Active firms: {n_active}\n"
        f"  Generation mix: {gen_str}\n"
        f"{share_text}\n"
        f"{cap_text}\n"
        f"{tam_text}"
    ) if tam_text else (
        f"  Active firms: {n_active}\n"
        f"  Generation mix: {gen_str}\n"
        f"{share_text}\n"
        f"{cap_text}"
    )


def make_entrant_firm(
    firm_id: str,
    slot_id: str,
    incarnation: int,
    profile: dict,
    base_unit_cost: float,
    rng: _random.Random,
    regional_markets_enabled: bool = True,
) -> FirmState:
    """Build a fresh FirmState for an endogenous entrant.

    `profile` comes from the entry judge — it sets capability, brand, and
    pre-credited cumulative R&D (leapfrog candidates get a head start).
    `base_unit_cost` is the scenario's Gen-1 cost (entrants enter with
    public tech = current peers' starting cost).

    `regional_markets_enabled` (default True) controls whether the entrant
    receives an idiosyncratic geographic / segment / channel / feature
    differentiation profile. When False, those fields are blank — entrant
    competes in a homogeneous market with no regional anchor.
    """
    cap = float(profile.get("starting_capability", 35.0) or 35.0)
    brand = float(profile.get("starting_brand", 5.0) or 5.0)
    cap = max(0.0, min(100.0, cap))
    brand = max(0.0, min(100.0, brand))
    # Wave ν+2: leapfrog entrants bring pre-credited cumulative product R&D
    # representing the knowledge / data / IP they already developed (e.g.,
    # academic spinout). This is what gives them a credible shot at
    # advancing generation faster than incumbents.
    pre_credited_rd = max(0.0, float(profile.get("starting_cumulative_product_rd_usd", 0.0) or 0.0))
    ceo_type = rng.choice(CEO_TYPES)
    auditor_id = f"auditor_{(rng.randint(0, 3)) + 1}"
    # Wave ν+6: idiosyncratic differentiation profile (entrants get one
    # too, derived from firm_idx so it's stable across simulation reruns).
    from .personalities import get_differentiation_profile
    try:
        firm_idx_int = int(firm_id.split("_")[-1])
    except (ValueError, IndexError):
        firm_idx_int = 0
    diff = get_differentiation_profile(firm_idx_int, regional_enabled=regional_markets_enabled)

    return FirmState(
        firm_id=firm_id,
        incarnation=incarnation,
        quarter=0,
        is_active=True,
        capacity_units=250,
        base_unit_cost=base_unit_cost,
        ppe_gross=25_000_000,    # pilot plant
        capability_stock=cap,
        brand_stock=brand,
        rd_cumulative_product=pre_credited_rd,
        auditor_id=auditor_id,
        ceo_type=ceo_type,
        geographic_focus=diff["geographic_focus"],
        patient_segment=diff["patient_segment"],
        distribution_channel=diff["distribution_channel"],
        signature_feature=diff["signature_feature"],
    )
