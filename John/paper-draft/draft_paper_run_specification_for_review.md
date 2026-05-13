# Draft paper — simulation specification (for external review)

**Purpose:** Single-page checklist of what the **current draft manuscript** claims was used for the main reported run, so a colleague (e.g. Kyle Jensen, Yale SOM) can sanity-check scope, inference, and reproducibility **without reading the full TeX**.

**Source of truth:** `analysis/paper/llm_industry_lab.tex` (Introduction, §Experimental Design, §Measurement, headline results table). If the team later pins a specific `outputs/run_*` folder to the published numbers, add that ID in the “Repository alignment” section at the bottom.

---

## 1. Agent scope (what is “on” in the story)

**Core agent types** (manuscript Introduction): operating firms; environment (product market / R&D / shocks); commercial bank (revolvers + amortizing term debt + covenants); investment bank (equity and bond placement); **equity market as a panel of LLM analysts** (median quote = marked price); **PE sponsor** for dormant entrants; **board** (CEO dismissal, hidden CEO type); **activist** (e.g. buyback campaigns).

**Optional modules** named in the draft: auditors, sell-side analysts, SEC enforcement, **M&A bidding**, restatements, earnings-management injection. The text states the reported run uses the **“production-and-finance subset”** — i.e. those optional modules are **not** the focus and are **off** for that design (while **post-default distressed asset auctions** and the rest of the bankruptcy resolution block remain part of the core loop described in §Entry, exit, and bankruptcy resolution).

---

## 2. LLM roster (as written in the draft)

All of the following are **direct quotations of model IDs** from §Experimental Design (“Roster details and parameter choices”). The draft describes **provider-native** models (OpenAI / Anthropic), **not** OpenRouter slugs.

| Role | Model(s) | Temperature notes (draft) |
|------|-----------|----------------------------|
| **Firm CFOs (6)** | Even split: `gpt-4o-2024-11-20` and `claude-3-5-sonnet-20241022` | (Pilot motivation: GPT-4-class slightly more aggressive on capacity; Claude-class slightly more cautious on leverage.) |
| **Environment** | `claude-3-5-sonnet-20241022` | **0.30** — draft says lower temps produced overly mechanical, anchored narratives. |
| **Equity valuation panel** | Built from **firm-CFO models** in a **3-member rotation** so **no panelist values its own firm** | — |
| **Commercial bank, investment bank, board, activist, PE sponsor** | `gpt-4o-mini-2024-07-18` | **0.40** for “quantitative” agents; **up to 0.70** for “narrative” agents (draft’s wording). |

The draft also states the **full YAML roster and random seed** are **retained** for the reported run (exact seed value is in the TeX / replication bundle — not duplicated here if omitted from the public draft).

---

## 3. Industry template & initial conditions

- **Template:** Longevity-drug industry (prices in tens of thousands USD per treatment course; capacity in hundreds of courses per quarter; therapeutic “generations”). Other templates (EV battery, satellite) exist but are **not** used in this paper.
- **Incumbents at \(t=1\):** **Six** firms, **symmetric** starting state in the draft:
  - Capability stock **50**, brand stock **50**
  - Capacity **250** units
  - Gross PPE **\$300M**, cash **\$200M**, **no debt**
- **Entry:** Exogenous Poisson-style injection of new firms; entrants can be **dormant** until activated by **PE** or **IPO** path (as in §Entry, exit, and bankruptcy resolution).

---

## 4. Macro & template parameters (draft)

- **Initial macro:** policy rate **3.5%**, market risk premium **5.0%**, political-uncertainty index **0.30** (0–1).
- **Macro dynamics:** environment may move policy rate by up to **50 bps/q** and political uncertainty by up to **0.10/q**; draft states limits did not bind in the reported run; benign band described (~2.5–4.0% policy, etc.).
- **Template guidance** (loaded from YAML read by firm + environment prompts): e.g. price floor **\$5,000** per course; Gen transitions tied to cumulative R\&D in the **\$200M–\$500M** range as **guidance** (not a hard cutoff in the narrative); elasticity “in the \(-1\) to \(-3\)” range; brand half-life ~**14 quarters**.

---

## 5. Run protocol & engineering (draft)

| Item | Manuscript claim |
|------|------------------|
| **Horizon** | **80 quarters** (“20-year” narrative). |
| **Restart / code version** | Quarters **1–41** on a development build with known environment bugs; **Q41 snapshot** taken; **bug fixes applied**; simulation **resumed** for **39 more quarters** (terminology in draft: through \(t=81\) boundary — interpret as 80 Q of economics + restart artifact). |
| **Parallelism** | ~**16** concurrent LLM calls (workstation). |
| **Wall time** | ~**21 hours** (draft). |
| **API spend** | ~**\$120** total for the 80-quarter run (draft; provider billing may differ slightly from internal token ledgers). |

**Inference caveat (draft):** early trajectory shares state with the pre-fix code path; later entrants face the post-fix code path — draft flags implications in §Mechanisms.

---

## 6. Reported headline outcomes (abstract + Table “Headline figures”)

Figures below are **as stated in the draft** for the single main run (not cross-run averages):

| Quantity | Value (draft) |
|----------|----------------|
| Run length | 80 quarters |
| Distinct firms (lifetime) | **17** |
| Active firms at close | **9** |
| Cumulative defaults | **8** |
| Distressed / consolidation events tied to defaults | **3** (draft table; narrative emphasizes roll-up via auctions) |
| Cumulative leapfrog activations | **13** |
| Cumulative generation advances | **0** |
| Average Herfindahl \(H_t\) | **1,697** |
| Average top-firm revenue share | **24.2%** |
| Cumulative industry revenue | **\$24.1B** |
| Cumulative industry net income | **\(-\$5.9B\)** |
| Average producers per quarter | **7.3** |

**Measurement (draft):** `compustat_q.csv` with **583 firm-quarters** and **80** columns (WRDS-style); full **quarterly snapshots** on disk; event logs from CSVs + snapshots.

---

## 7. Reproducibility & audit trail (draft claims)

- Orchestrator + accounting are **deterministic** conditional on **seed** and **frozen model roster**; **LLM sampling** breaks bitwise replay across providers.
- Draft commits to **per-call logging** (`llm_calls.jsonl`-style) sufficient to **re-price** a run even if weights change.
- **Balance-sheet identity** checked each quarter with **\$1,000** tolerance; violations logged (development relied on this heavily).

---

## 8. Repository alignment (important for a second opinion)

Internal validation configs in this repo (e.g. `config/validation_20f_80q.yaml`) often use **`n_firms_initial: 20`**, **`scenario: well_capitalized`**, **OpenRouter** backends, and **mixed open models** — that is **not** the same parameterization as the **six-incumbent, GPT-4o / Claude 3.5 Sonnet** roster described in the **draft paper**.

The folder **`outputs/run_1777317784`** appears in wave-ν internal analysis as a **long OpenRouter-style run** with **20 firm slots** and outcomes that **do not match** the draft’s headline table (e.g. manuscript: **9 survivors**; that run’s scorecard describes **universal default**). **Do not cite that run ID as the paper’s main result** unless you have explicitly reconciled it with the manuscript.

**Action item for the team:** Insert the **actual** `outputs/run_*` ID(s), **exact YAML path**, and **exact random seed** that produced the Table 1 numbers, and archive `cost_summary.txt` + model roster YAML next to this memo when you circulate to Kyle.

---

## 9. Suggested questions for an external reader

1. Is the **Q41 restart + bug-fix resume** acceptable for a single-case narrative, or should pre- and post-fix segments be reported separately?
2. Does **turning off** SEC / sell-side / auditor / strategic M&A / restatements / earnings management **undermine** or **clarify** the economic claims (e.g. roll-ups, activism, leverage stories)?
3. Given **non-replicability of LLM weights**, is the **token ledger + frozen roster** discipline adequate for journal standards in your field?

---

*Memo generated to accompany `analysis/paper/llm_industry_lab.tex`; update §8 once the canonical replication bundle is frozen.*
