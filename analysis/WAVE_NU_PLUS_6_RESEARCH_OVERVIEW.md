# Wave ν+6 — A Research Overview

**What this document is.** A reading of the 80-quarter (20-year) Wave ν+6
simulation as a piece of generated industry data, set against the
empirical and theoretical industrial-organization (IO) literature. The
simulation began with five biotech firms in a "longevity drug" scenario
and ran with endogenous entry, PE-backed lifecycle, named auditors,
SEC, sell-side analysts, M&A, and an env-side demand calibrator. Sixteen
distinct firms were spawned over the run; nine defaulted; seven survived
to Q80. The single design intervention introduced in this wave was
**idiosyncratic product differentiation** — each firm carries a
geographic focus, patient segment, distribution channel, and signature
feature, and the environment LLM is told consumers have heterogeneous
preferences over those dimensions.

The run produced two qualitatively different regimes that map cleanly
onto two distinct strands of the IO literature, and a transition between
them that maps onto a third.

---

## Phase 1 (Q1–Q40): Differentiated competition, stable equilibrium

For the first decade of simulated time, the industry behaved exactly
as horizontal-differentiation models predict.

**What we observed.** Top-firm share oscillated in a tight 16–22% band.
Eight to nine firms produced simultaneously in nearly uniform
distributions — quarters in which the top six firms each held 11–17%
share were typical. Each firm anchored its sales in its assigned niche
(US Northeast for firm_0, US West Coast for firm_1, Western Europe for
firm_4, Nordic+Benelux for firm_5, US Southeast for firm_2, US Midwest
for firm_3, etc.). Firms entered and exited the market, but the
equilibrium share *structure* was robust to that churn — when firm_4
(Western Europe) defaulted at Q12 and firm_6 entered, the new entrant
inherited a similar slice of demand. Sutton (1991) describes this as
the natural endpoint of horizontally-differentiated industries with
finite niche sizes: the industry settles at a number of firms determined
by minimum efficient scale and niche heterogeneity, and that number is
robust to identity-level churn.

**What economic theory predicts and we saw.**
- **Hotelling/Salop circular city.** Geographic differentiation creates
  local market power and prevents winner-take-all in price competition.
  We observed exactly this: firms with distinct regions never competed
  away each other's profits.
- **BLP-style discrete-choice demand.** When consumers have idiosyncratic
  taste shocks over product attributes, share is bounded by the
  attribute-similarity of competitors. Our env LLM, prompted with each
  firm's differentiation profile, allocated demand across firms in
  proportions that respect those niches — the empirical pattern
  matches what a BLP demand system would generate from random-coefficient
  preferences.
- **Bresnahan-Reiss equilibrium-firm-count.** Their entry-threshold
  framework predicts that an industry's equilibrium number of firms
  scales with market size and inversely with fixed costs. Our entry
  judge, reading industry concentration and recent performance, reached
  an equilibrium of roughly 8–9 firms — consistent with the kind of
  market-size-implied count their structural estimates produce.

**What's missing or different.** Real industries take longer to reach
this equilibrium (decades vs. our ~10 simulated years), and entry/exit
in real data is more lumpy — Klepper's life-cycle work shows a wave
of entry followed by a sharp shakeout, not the steady churn we
observed. Our entry judge fired more frequently than Klepper-style
data would suggest. This is partly an artifact of LLM tempo: each
simulated quarter is one decision-cycle, with no inertia or hysteresis.

---

## Phase 2 (Q42–Q80): Absorbing-state monopoly

The second phase looks completely different. From Q42 onward, the
industry collapsed into an absorbing equilibrium where one firm
(firm_9) held 100% market share for 39 consecutive quarters, while
six to eight cash-flush competitors produced zero units and four
sequential leapfrog entrants (firm_13 through firm_16) failed to
secure PE funding.

**What economic theory predicts.**
- **Multiple-equilibria coordination games (Cooper & John 1988).**
  When firms' best responses are strategic complements, an industry can
  sit in either a "high activity" equilibrium (everyone produces) or a
  "low activity" equilibrium (everyone retrenches). The default
  cascade at Q41 acted as a coordinating signal: surviving firms
  simultaneously read the failure as evidence that the industry was
  contracting, and best-responded by cutting production to zero.
- **Diamond-Dybvig bank-run mechanics applied to product markets.**
  Once a few competitors stop producing, the remaining firms face
  a "thinner" market and the optimal response can flip to "also stop."
  Our cash-rich firms (firm_2 with $1.5B, firm_5 with $1.1B) had the
  capital to keep competing; they stopped because everyone else did.
  This is the product-market analog of a bank run.
- **Diamond-Verrecchia / Caplin-Leahy on uncertainty-driven exit.**
  When firms are uncertain whether peers will produce, the
  option value of waiting is positive. Our retrenchment is consistent
  with a coordinated decision to wait out the uncertainty.

**What we saw that the literature predicts:**
- Default cascade triggering retrenchment (consistent with Allen &
  Gale 2000 financial-contagion mechanics, transposed to product
  markets).
- Persistent monopoly with no organic challenger funding (consistent
  with Sutton's "endogenous sunk cost" prediction that established
  incumbents in concentrated markets enjoy entry deterrence even
  without overt strategic action).
- Failure of leapfrog entry (firm_13–16 stayed dormant) — VC/PE
  literature on dry-powder withdrawal in mature concentrated markets
  (Gompers et al., Kaplan-Strömberg) predicts exactly this: when
  one firm is perceived as having "won" the market, sophisticated
  investors decline to fund challengers.

**What we saw that the literature does NOT cleanly predict:**
- **Speed and depth of the cascade.** A single default (Q41) flipping
  the entire industry to zero output within one quarter is faster than
  any historical analog I know of. Real-world coordination failures
  (e.g., the 2007–08 commercial paper market freeze) unfold over
  weeks but rarely instantly across a whole industry. This appears to
  be an LLM artifact: when the firm-decision LLMs read each other's
  Q41 retrenchment, they all best-respond identically because they
  share similar reasoning priors.
- **Cash-rich firms declining to produce.** Standard IO models assume
  firms with positive variable margins keep producing as long as
  fixed costs are paid. Our firms had cash, capacity, brand stocks —
  and chose 0 production. The closest analog is "rational inattention"
  or "managerial fatalism" in the behavioral-IO literature (Hortaçsu
  et al. on inertia), but that literature usually concerns *small*
  deviations from optimization, not full shutdown.
- **Persistence of monopoly across PE/M&A/leapfrog channels.** Real
  monopolies face activist investors, antitrust enforcement, and
  competitive pressure from adjacent product categories. Our env's
  consolidation read activated *none* of those channels effectively;
  the simulation has the mechanisms (entry judge, M&A bidder, activist
  investors are all toggled ON) but they didn't bind.

---

## The transition: what flipped, and why it matters

The most research-relevant artifact of this run is the **transition
itself**, between Q40 and Q42. The differentiation profiles that worked
to keep the industry segmented in Q1–Q40 were still present at Q42 —
firms didn't lose their geographic focus. What changed was the *env
LLM's interpretation* of the Q41 default and the resulting unit-sales
pattern.

This is closest to Diamond-Dybvig and to Cooper-John's coordination
literature, but with a twist: the equilibrium-selection mechanism is
**not the firms' beliefs** about each other (firms acted reasonably
given their best-response priors). It's the **environment's
interpretation** of an ambiguous price/quantity signal. Once the env
read the industry as "consolidating around firm_9," that interpretation
was self-fulfilling: the env's allocation gave firm_9 demand, which
made firm_9 the natural producer, which the env then read as
confirmation of consolidation.

The IO literature on **focal points** (Schelling, Mailath-Postlewaite)
is the closest analog: when an ambiguous game has multiple equilibria,
players coordinate on the most "salient" one. In our simulation, the
env LLM is the focal-point selector, and once it selected firm_9 as
the focal incumbent, it never re-selected.

**Practical implication for empirical IO research using LLM-generated
data.** This run produces an unusually clean illustration of
multiple-equilibria coordination failure. A research paper using this
data could exploit the Q40→Q42 transition as a "natural experiment" in
which the same firm primitives (capability, cash, brand,
differentiation profile) produced two completely different observed
outcomes depending on the env's equilibrium selection. That's
hard to obtain from real data, where unobserved heterogeneity always
contaminates such comparisons.

---

## What we learned, in one paragraph each

1. **Horizontal differentiation prevents winner-take-all under
   competitive conditions** — a result that's been clear since Hotelling
   1929 but is rarely shown so directly in simulation. Our Q1–Q40 record
   matches what BLP-style demand estimation would produce.

2. **Coordination failures can flip an industry between equilibria
   sharply** — Cooper-John 1988 in action. Our Q42 retrenchment is a
   clean coordination failure with no fundamental change in firm
   characteristics.

3. **Cash buffers don't substitute for competitive pressure** — firms
   with $1B+ cash held perfect dry powder for 39 quarters and never
   used it to challenge firm_9. This contradicts a naive reading of
   the strategic-management literature (Porter, Ghemawat) that says
   resource depth predicts competitive response. It's consistent with
   the more nuanced commitment-credibility literature (Tirole's
   capacity-as-commitment): without a credible expansion plan, cash
   alone doesn't deter or displace an incumbent.

4. **VC/PE refuse to fund into perceived monopolies** — entry-judge
   logs explicitly note "industry highly concentrated with a single
   dominant firm" for the Q44–Q75 leapfrog spawns, and PE rounds
   never closed. Real-world dry-powder withdrawal (Gompers et al.)
   shows the same pattern; our simulation reproduces it.

5. **Env LLM as equilibrium selector** — the most novel finding. The
   environment's narrative read of an ambiguous outcome at Q41 fixed
   the equilibrium for the next 39 quarters. This isn't standard
   IO theory; it's closest to Schelling-style focal-point coordination
   with the twist that the focal-point selector is itself an agent
   (the LLM), not a feature of common knowledge.

---

## Caveats and limits

- **One run, one seed.** The Q41 cascade may be path-dependent on the
  specific firm that defaulted and the env LLM's reasoning priors. A
  cross-seed study would tell us whether this is robust.
- **LLM tempo, not real tempo.** Quarter-by-quarter LLM cycles compress
  decision time relative to real industry dynamics. Real coordination
  failures take longer to set in.
- **No exogenous shocks.** Real industries get jolted by macro events,
  regulatory shifts, and demand disruptions. Our run has none, so the
  absorbing state had no stochastic kick to escape from.
- **Env design choices.** The env was given idiosyncratic preferences
  but no explicit "geographic markets remain segmented even when one
  firm dominates" constraint. A future wave that surfaces *unmet niche
  demand* as a separate signal might prevent the consolidation collapse.

---

## What this generates for future research

The dataset has four properties that make it useful as a research
artifact, independent of the absorbing-state regression:

1. **Structural primitives + behavior.** Each firm has observable
   capability, brand, cash, capacity, plus differentiation
   covariates. Standard reduced-form firm-dynamics regressions can
   be run on it.

2. **Within-firm time series of strategic decisions** that are
   self-justified in board minutes and annual reports — useful for
   text-as-data work.

3. **A clean coordination-failure event** at Q41 that researchers
   could use to test cascade-prediction models.

4. **A long-horizon monopoly persistence record** with continuous
   entry attempts that all failed — useful for testing
   entry-deterrence models against PE investment behavior.

The Wave ν+5 monopoly was a design failure. The Wave ν+6 monopoly is
a research artifact: a clean instance of multiple-equilibria
coordination failure with full observable trace.
