# Wave ν+7 — Final-Run Review

Three sections matching the user's three asks: **bug scan**, **economic
sanity check**, and **post-debrief dashboard ideas**.

---

## 1. Bug & Simulation-Issue Scan

### Clear bugs worth fixing

#### Bug A: Equity market has no QoQ sanity check

**Where:** `src/orchestrator.py` Phase 11 (equity market). The orchestrator
takes whatever price the equity-market LLM emits (line 1735–1737):

```python
price = terms.get("equity_price", 0)
if price > 0:
    state.firms[fid] = state.firms[fid].evolve(equity_price=price)
```

**Evidence:** In the ν+7 final run, multiple firms had implausible
single-quarter price spikes:

- **firm_9**: $79.50 → **$535.00** at Q80 (+573%) on declining
  fundamentals (revenue halved, NI dropped 90%)
- firm_3: +185% at Q80
- firm_2: +163% at Q74
- firm_2: +55% at Q78

These are LLM hallucinations or temperature artifacts. Real
exchanges have circuit breakers (NYSE limits single-day moves to
±20% with halts). The simulation has no equivalent.

**Fix proposal (RECOMMEND):** Add a soft re-prompt when the LLM-emitted
price moves more than ~3× the prior quarter's price. The verifier should
see the prior price + emitted price + fundamentals and either confirm
or revise. Pattern is identical to the existing env-output verifier
already in the codebase. This is **not** a hardcoded ceiling — it's a
verifier that checks plausibility against fundamentals.

Risk: low. The verifier is qualitative and fires only on extreme moves.

#### Bug B: env never grants Gen2 advancement

**Where:** `src/prompts.py` env system prompt (line 1101–1103) tells
the env that "firms that have not yet accumulated sufficient cumulative
product R&D cannot advance generation" — but never tells the env when
they CAN or SHOULD advance.

**Evidence:** Across 39 quarters of the resume run, with multiple firms
crossing the $200M `gen_2_rd_threshold` (firm_0 reached $343M before
default; firm_9 reached $305M; firm_2 and firm_5 each over $200M), **no
firm ever advanced to Gen2**. The `outcome.product_rd_advance` flag was
never True.

The accounting code is ready (`accounting.py:481`):
```python
if outcome.product_rd_advance and new_gen < 4:
    new_gen = prior.product_generation + 1
    ...
```

But the env never sets it. The env LLM is being conservative (no
explicit "should I advance now?" trigger in the prompt) and defaults
to False every time.

**Fix proposal (RECOMMEND):** Add to env prompt a qualitative trigger
along the lines of:

> When a firm's cumulative product R&D has clearly cleared the
> generation threshold (you can see this in the firm-state block) and
> recent quarters showed sustained product R&D investment, it is
> appropriate to grant `product_advance: true` for that firm. Real
> biotech industries DO see periodic generation advances — withholding
> them indefinitely is implausible.

This stays qualitative (no "advance when X > Y") while breaking the
status-quo bias. Risk: low. Worst case the env grants advances slightly
too freely; that's still better than never.

#### Bug C: Stale defaulted-firm state

**Where:** Defaulted firms accumulated before Bug 2 fix retain
pre-default capability/brand/PPE values:

| Firm | Status | Cap | Brand | PPE | Cash |
|---|---|---|---|---|---|
| firm_0 | DEFAULTED | 89 | 92 | $374M | $445M |
| firm_4 | DEFAULTED | 38 | 76 | $92M | **$852M** |
| firm_5 | DEFAULTED | 75 | 85 | $460M | $128M |
| firm_6 | DEFAULTED | 73 | 79 | $621M | $0M |

vs firms that defaulted AFTER the fix:

| Firm | Status | Cap | Brand | PPE | Cash |
|---|---|---|---|---|---|
| firm_10 | DEFAULTED | 0 | 0 | $327M | $370M |
| firm_11 | DEFAULTED | 0 | 0 | $184M | $265M |
| firm_12 | DEFAULTED | 0 | 0 | $11M | $35M |

The post-fix defaulted firms have cleaned-up state (cap=0, brand=0
because their assets were transferred to firm_7 via auction). The
pre-fix defaults still carry their pre-default values.

**Fix proposal (DON'T fix, but note):** This is residual contamination
from the broken-run portion of the snapshot. Going forward (fresh
runs), this won't happen. For the existing dataset, post-hoc
cleanup is risky — we'd be rewriting historical state. Better to
flag in research analysis: "firm_X defaulted at Q12 under broken
auction code; residual state may be misleading."

Worth adding a one-line `state_dirty_firms` field on snapshot for
provenance? Maybe. Borderline.

### Borderline issues (flagged but no fix proposed)

#### Issue D: firm_4 defaulted with $852M cash

This looks weird but isn't necessarily a bug. firm_4 defaulted at
Q12 (during the original broken run, before the fixes). At that time
cash was probably much lower; the $852M is residual fields from
pre-default. After fixes, defaulted firms have their cash properly
zeroed via `apply_auction_result`.

#### Issue E: firm_9's $13.2B cash hoard

firm_9 (Direct-to-Consumer telemedicine) ended Q80 with $13.2B
cash on $82M Q80 revenue. That's a 40× cash-to-quarterly-revenue
ratio.

This is large but explainable:
- 64 quarters of revenue (Q16 spawn → Q80) at avg ~$50-100M
- Multiple equity issuances during PE/IPO lifecycle
- No buybacks, no dividends, no big M&A spend
- No Gen2 forced reinvestment (because Bug B above)

If Bug B is fixed (env grants Gen2 advances), capital deployment will
be more realistic — firms with R&D progress will see their R&D
*matter* via generation jumps and will redirect spend accordingly.

#### Issue F: firm_14 (leapfrog) cash $3.1B with cap=29 brand=45

firm_14 was a Q46 LEAPFROG entrant that quickly raised PE rounds
and became market leader briefly at Q49. Now sitting on $3.1B but
fundamentals (cap=29, brand=45) are mediocre.

**Hypothesis:** PE rounds raised more capital than firm_14 needed
to operate, and the firm hasn't deployed it. The simulation lacks
strong signals for "return capital to investors" beyond the existing
buyback/dividend mechanism. Borderline; not fixing.

### Bugs already fixed in code (recap from prior bug sweeps)

- ✅ Bug 1 (Wave ν+7): silent zero-default fallback in firm-decision
  exception handler — replaced with carry-forward.
- ✅ Bug 2: auction events not applied in modern judge path —
  indentation fixed.
- ✅ Bug 3: revenue/COGS unit mismatch in accounting — `outcome` is
  now updated when units_to_sell is clamped.
- ✅ Bug 4: deterministic env-clamp dropped R&D advance flags —
  preserved.
- ✅ Bug 5: dict-key inconsistency between env LLM output and
  verifier clamp — unified to LLM-facing keys.

---

## 2. Economic Sanity Check

### Things that make economic sense ✅

**Multi-firm differentiated competition**. Top share oscillated
18-32% over 39 quarters, distributed across 6-9 producers. Market
leadership rotated: firm_12 at Q42 (20.8%), firm_7 at Q43 (17.7%),
firm_14 at Q49 (22.4%, leapfrog displacement!), firm_9 at Q66 (31.9%),
firm_7 again at Q80 (31.8%). This is exactly what differentiated
oligopoly theory predicts.

**Successful Schumpeterian creative destruction**. firm_14 was
spawned as LEAPFROG (cap=60), got PE-funded, and briefly led the
industry at Q49 by displacing the incumbent firm_7. Aghion-Howitt
prediction realized.

**M&A consolidation by cash-rich incumbent**. firm_7 acquired three
distressed competitors (firm_12 for $35M, firm_11 for $350M, firm_10
for $450M = $835M total). Salant-Switzer-Reynolds and Farrell-Shapiro
predict exactly this in a mature industry. firm_7 ended up with
1000-unit capacity (4× original) reflecting accumulated assets.

**Default rate ~50% across 39 quarters**. 8 of 16 firms defaulted —
healthy churn consistent with Klepper-style industry life cycle.

**Revenue growth $300M (Q42) → $632M peak (Q75)**. Industry expanded
through the 39-quarter horizon as the leapfrog matured and consolidation
created scale, then settled into $400-500M range.

**Pricing in $100-250K per treatment course**. Plausible for a
specialty biotech / longevity drug.

**Cumulative LLM decision quality**: 579 llm vs 4 fallback (99.3%).
The fallback fix is doing exactly its job: absorbing transient
LLM glitches without contaminating the run.

### Things that DON'T quite make economic sense

#### Concern 1: No Gen2 advancement (engineering issue, see Bug B)

The biggest economic anomaly. Multiple firms invested $200-343M
cumulative in product R&D — well past the $200M threshold the
scenario sets — but no firm advanced. This is a code/prompt bug
(env doesn't grant advance), not real economics. **Discuss with
fix proposal above.**

If this is fixed, expect to see:
- 2-3 firms advancing to Gen2 over the run
- Process R&D resetting, cost structure dropping
- Demand pool expanding (per env prompt's "advance unlocks larger
  addressable population")
- Higher firm valuations on Gen2 advance

#### Concern 2: firm_9 capital allocation looks strange

$13.2B cash on a firm with $82M Q80 revenue. Real public companies
return excess cash via dividends or buybacks. firm_9's lifecycle
is "public" (IPO'd), so the buyback/dividend mechanism should be
firing. It isn't.

**Hypothesis:** the firm-level prompt doesn't strongly signal
"excess cash should be returned to shareholders." Combined with no
Gen2 to absorb capex, firm_9 just hoards.

**Don't fix** — this is borderline (real Apple held $200B+ for years
before activist pressure). But it's worth discussing if you want a
more lifelike capital-allocation pattern.

#### Concern 3: firm_14 led the industry at Q49 with capability=60

A leapfrog with cap=60 displaced incumbents who had cap=89 (firm_0),
75 (firm_5), etc. Capability-disadvantaged leadership.

**Why this happened:** the leapfrog had a fresh capability advantage
in *its niche* (signature feature, segment fit), not capability in
the abstract sense. The env weighted niche fit + brand novelty over
raw capability score. This is plausible economically — Tesla led
EVs with much less manufacturing scale than Toyota — but worth
verifying this is what the env actually reasoned about.

**Don't fix** — this looks like correct emergent behavior, just
worth confirming.

#### Concern 4: Equity price spikes (engineering issue, see Bug A)

firm_9's 6.7× one-quarter jump is unphysical. Multiple smaller
spikes elsewhere. **Discuss with fix proposal above.**

If fixed, expect:
- More gradual price evolution
- Better correlation with fundamentals (rev, NI)
- More plausible market caps in the final report

#### Concern 5: Defaulted firms with positive cash

firm_4 defaulted with $852M cash; firm_0 with $445M. Defaulting on
covenants while sitting on cash is real (covenant violations often
trigger defaults independent of cash position), but the magnitudes
are striking.

**Don't fix** — this may be residual stale state (Bug C above) or
real covenant-driven defaults. Hard to disentangle without
quarter-by-quarter forensics.

### Things I'd want to discuss

1. **Should defaulted firms with positive cash continue operating?**
   Real bankruptcy is more nuanced than the simulation's binary
   active/defaulted. A real Chapter 11 reorganization could keep
   the firm operating under court protection. Worth modeling?

2. **Should we add a "return capital" prompt nudge for cash-rich
   firms?** Real CFOs facing $13B cash and no acquisition pipeline
   would face activist pressure for buybacks. The activist agent
   exists but doesn't seem to fire on this case.

3. **Should Gen2 transitions be more visible to the env?** The
   current "firms that haven't accumulated... cannot advance" framing
   is one-sided. A symmetric "firms that HAVE accumulated... CAN
   advance" sentence would unblock the bug.

4. **Should equity prices be sanity-checked?** The verifier exists
   for env demand but not for equity prices. Adding a similar
   verifier is the cleanest fix.

---

## 3. Post-Debrief Dashboard / Human-Readable Report

You already have:
- `compustat_q.csv`, `compustat_a.csv` — quarterly + annual fundamentals
- `analyst_forecasts.csv`, `audit_analytics.csv`, `restatements.csv`,
  `ceo_turnover.csv`, `execucomp.csv`, `management_forecasts.csv`,
  `compustat_restated.csv` — WRDS-style datasets
- `firms/*/board_minutes_*.md`, `firms/*/annual_report_FY*.md`,
  `firms/*/product_spec_*.txt` — narrative artifacts
- `gazettes.txt` — env's quarter-by-quarter narrative
- `scorecard.txt`, `summary.txt` — top-level metrics
- 9 `figures/*.pdf` plots from the prior wave

What's missing: **a single "what happened" view** for human navigation.

### My recommendation: a 3-artifact debrief bundle

Generate from a single `make_debrief.py` script, output to
`outputs/run_<id>/debrief/`:

#### Artifact 1: `dashboard.html` (single static file, ~5MB)

Self-contained HTML using Plotly for interactive plots, Bootstrap
for layout. Open in any browser, no server needed. Sections:

- **Headline KPIs** (top of page): final # firms, revenue, top share,
  HHI, # M&A deals, # defaults, # Gen2 advances
- **Industry trajectory** (interactive plot): top-share + HHI + total
  revenue + # producers, all on Q-axis
- **Firm timeline Gantt** (interactive): each firm's lifecycle bar
  with hover-tooltip showing entry/default/M&A/leapfrog events
- **Per-firm story cards** (one per firm, expandable): summary line
  + 4-quadrant mini-plot (revenue, market share, capability, cash)
  + key events list
- **Lifecycle event log** (table): chronological — entry, dormancy,
  default, auction, leapfrog activation, M&A
- **Decision quality trace**: per-quarter LLM-vs-fallback ratio
- **Comparison vs prior runs** (if available): side-by-side metrics

#### Artifact 2: `debrief.md` (10-15 page narrative)

Reads like an industry retrospective. Sections:

- **Executive summary** (1 page)
- **The opening (Q1–Q15 / Q42-…)**
- **The first shakeout** — defaults timeline + reasons
- **The leapfrog event** — firm_14 entry, displacement, reversion
- **The M&A wave** — firm_7's three acquisitions
- **The mature phase** — final 10 quarters
- **Survivors and losers** — per-firm verdicts
- **What this run shows** — pattern interpretation

The narrative is generated from event detection on the data + LLM
prose generation (one-shot per section). Expect ~$1 of LLM cost.

#### Artifact 3: `events.csv` (machine-readable timeline)

One row per detected event: quarter, type, firm(s), value, narrative
snippet. Types: entry, dormancy, default, auction, M&A, leapfrog
activation, generation advance, CEO turnover, restatement, equity
price spike, large dividend/buyback. Useful for cross-run aggregation
and for downstream scripts.

### Why not other approaches

**Streamlit / Dash interactive app** — overkill for a post-mortem
artifact. Requires running a server, breaks portability.

**Per-firm PDF reports** — already exist as annual_reports.csv
content. Could be assembled but the value-add over the dashboard
is small.

**Quarto / RMarkdown** — would work but introduces a new toolchain
dependency. The static-HTML-with-Plotly approach achieves the same
without adding tools.

### Implementation effort

- `dashboard.html` generator: ~300 lines Python, mostly Plotly. ~2h.
- `debrief.md` generator: ~200 lines, plus prompt engineering for
  narrative sections. ~3h including iteration.
- `events.csv` generator: ~100 lines of event detection on existing
  state. ~1h.

Total: ~6 hours to build. Output reusable across all future runs
with no per-run modification.

### Recommended priority

1. **`events.csv`** first — cheapest, highest re-use value, feeds
   the other two.
2. **`dashboard.html`** second — high signal-density for skimming.
3. **`debrief.md`** last — most LLM-dependent, useful for sharing
   findings with non-technical audiences.

---

## Summary of recommendations

| Item | Recommend | Risk | Notes |
|---|---|---|---|
| Bug A: equity-price verifier | **YES** | Low | Same pattern as env verifier |
| Bug B: env Gen2 trigger | **YES** | Low | One paragraph in env prompt |
| Bug C: stale defaulted state | NO | High to retrofit | Note in research analysis instead |
| Issue D-F (cash hoards, etc.) | DISCUSS | — | Borderline economics |
| Concern 1 (Gen2): | tied to Bug B | — | Unblocks once Bug B fixed |
| Concern 2 (firm_9 cash): | DISCUSS | — | Real-world activist pressure |
| Concern 3 (leapfrog leadership): | NO fix | — | Likely correct |
| Concern 4 (price spikes): | tied to Bug A | — | Unblocks once Bug A fixed |
| Concern 5 (defaulted with cash): | tied to Bug C | — | Residual / partly Bug C |
| Dashboard artifacts | **YES** | None | 6h of build, infinite re-use |

Want me to implement Bugs A and B, build the debrief bundle, or
both? Both are independent and can be done in parallel.
