# Model Ratings

Last updated: 2026-04-15 | 28 models (22 OpenRouter + 6 AI Horde) | 3 tasks each

## Summary Table

Sorted by tier then value. All models evaluated on the **same 3 tasks** (firm decision, environment, pricing).

| Model | Backend | Tier | Quality | Firm | Env | Pricing | Avg $/M | Value | Speed | Rec. Role |
|-------|---------|------|---------|------|-----|---------|---------|-------|-------|-----------|
| mistralai/mistral-small-24b-instruct-2501 | openrouter | S | 100% | 17/17 | 11/11 | 9/9 | $0.065 | 1538 | 15s | data_analyst, firm |
| qwen/qwen3-235b-a22b-2507 | openrouter | S | 100% | 17/17 | 11/11 | 9/9 | $0.085 | 1170 | 33s | firm |
| z-ai/glm-4-32b | openrouter | S | 100% | 17/17 | 11/11 | 9/9 | $0.100 | 1000 | 21s | firm |
| microsoft/phi-4 | openrouter | S | 100% | 17/17 | 11/11 | 9/9 | $0.103 | 976 | 36s | firm (revalidate) |
| meta-llama/llama-4-scout | openrouter | S | 100% | 17/17 | 11/11 | 9/9 | $0.190 | 526 | 20s | firm |
| google/gemini-2.0-flash-001 | openrouter | S | 100% | 17/17 | 11/11 | 9/9 | $0.250 | 400 | 10s | data_analyst |
| deepseek/deepseek-v3.2 | openrouter | S | 100% | 17/17 | 11/11 | 9/9 | $0.320 | 312 | 115s | env, equity, inv_bank |
| deepseek/deepseek-v3.2-exp | openrouter | S | 100% | 17/17 | 11/11 | 9/9 | $0.340 | 294 | 67s | — (no gain over stable) |
| nvidia/nemotron-super-49b-v1.5 | openrouter | S | 100% | 17/17 | 11/11 | 9/9 | $0.250 | 400 | 325s | — (too slow) |
| bytedance-seed/seed-2.0-mini | openrouter | S | 100% | 17/17 | 11/11 | 9/9 | $0.250 | 400 | 657s | — (too slow) |
| deepseek/deepseek-r1-0528 | openrouter | S | 100% | 17/17 | 11/11 | 9/9 | $1.325 | 75 | 426s | KEEP — best reasoning |
| koboldcpp/gemma-4-26B-A4B-it-heretic.IQ4_XS | aihorde | S | 100% | 17/17 | 11/11 | 9/9 | free | n/a | 46s | firm |
| koboldcpp/Dark-Nexus-24B-v2.0.i1-Q5_K_M | aihorde | S | 100% | 17/17 | 11/11 | 9/9 | free | n/a | 104s | firm |
| aphrodite/Behemoth-R1-123B-v2-w4a16 | aihorde | S | 100% | 17/17 | 11/11 | 9/9 | free | n/a | 231s | firm (if available) |
| google/gemma-3-12b-it | openrouter | A | 95% | 17/17 | 10/11 | 8/9 | $0.085 | 1113 | 35s | commercial_bank |
| nvidia/nemotron-nano-9b-v2 | openrouter | A | 97% | 17/17 | 10/11 | 9/9 | $0.100 | 973 | 79s | firm (budget) |
| mistralai/mistral-small-3.2-24b | openrouter | A | 97% | 17/17 | 10/11 | 9/9 | $0.138 | 708 | 17s | — (2501 is cheaper) |
| minimax/minimax-m2.5 | openrouter | A | 97% | 17/17 | 10/11 | 9/9 | $0.554 | 176 | 109s | KEEP — firm |
| google/gemma-4-26b-a4b-it | openrouter | A | 97% | 17/17 | 10/11 | 9/9 | $0.215 | 453 | 34s | firm |
| qwen/qwen3-32b | openrouter | A | 97% | 17/17 | 10/11 | 9/9 | $0.160 | 608 | 255s | — (MoE is better) |
| nvidia/nemotron-3-super-120b | openrouter | A | 97% | 17/17 | 10/11 | 9/9 | $0.300 | 324 | 294s | — (too slow) |
| aphrodite/TheDrummer/Skyfall-31B-v4.1 | aihorde | A | 95% | 17/17 | 11/11 | 7/9 | free | n/a | 41s | firm |
| minimax/minimax-m2.7 | openrouter | A | 100%* | 17/17 | FAIL | 9/9 | $0.750 | 133 | 56s | — (env failed) |
| qwen/qwen3.5-9b | openrouter | A | 96% | 17/17 | 10/11 | FAIL | $0.100 | 964 | 397s | �� (pricing failed) |
| qwen/qwen3-14b | openrouter | A | 95% | 17/17 | 9/11 | 9/9 | $0.150 | 631 | 660s | — (too slow) |
| meta-llama/llama-3.3-70b | openrouter | A | 95% | 17/17 | 9/11 | 9/9 | $0.210 | 450 | 34s | — (Scout is better) |
| TheDrummer/Cydonia-24B-v4.3 | aihorde | F | 0% | FAIL | FAIL | FAIL | free | n/a | 1007s | — (all timed out) |
| koboldcpp/Gemma-4-31B-it | aihorde | F | 0% | FAIL | FAIL | FAIL | free | n/a | 1000s | — (all timed out) |

Tier: **S** = 100% (37/37) | **A** = 95–99% | **F** = failed | Value = quality% / avg cost per M tokens

*\* minimax-m2.7 scored 100% on tasks that ran, but environment task failed entirely.*

Detailed data: `model_ratings.csv` | Raw results: `sweep_history/`

---

## Evaluation Method

Each model runs 3 tasks that mirror core simulation roles:

**Firm Decision (17 pts)**: Generate a quarterly CEO decision as JSON.
Scored on: valid JSON (1), all required fields present (7 x 1), price in 50K–150K range (2),
production in 50–500 (2), R&D allocation sums to 1.0 (2), R&D spend $5M–$200M (2),
reasoning >50 chars (2).

**Environment (11 pts)**: Generate market outcomes given firm actions.
Scored on: total demand 500–1200 (2), firm_outcomes with 3+ firms (2), market shares sum
to 1.0 (2), firm_0 has highest share (2), narrative >200 chars (2), events present (1).

**Pricing (9 pts)**: Price 3 pharma firms given financials.
Scored on: all 3 firms priced (2), prices in $5–$500 range (3), firm_0 highest (2),
reasoning >20 chars per firm (2).

---

## Robustness & Plausibility

### S-Tier (all checks pass)

| Check | DS-R1 | DS-v3.2 | Mistral | Qwen-235B | GLM-4 | Phi-4 | Scout | Gemini | Gemma4-Horde | DarkNexus | Behemoth |
|-------|-------|---------|---------|-----------|-------|-------|-------|--------|-------------|-----------|----------|
| JSON valid | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes |
| Price sane | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes ($78K) | Yes ($70K) | Yes ($80K) |
| Production sane | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes |
| R&D alloc sums | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes |
| Reasoning present | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes |
| Demand realistic | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes (735) | Yes (735) | Yes (735) |
| Shares sum to 1 | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes |
| firm_0 leads | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes |
| Narrative rich | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes |
| All firms priced | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes |
| Pipeline valued | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes |

### A-Tier (minor gaps)

| Check | MiniMax-M2.5 | Gemma-3 | Nemotron-9B | Gemma-4-OR | Skyfall | Llama-3.3-70B | Qwen3-14B |
|-------|-------------|---------|-------------|------------|---------|---------------|-----------|
| Narrative rich | No | No | No | No | Yes | No | No |
| Shares sum to 1 | Yes | Yes | Yes | Yes | Yes | No | No |
| firm_0 leads | Yes | Yes | Yes | Yes | Yes | No | No |
| Pipeline valued | Yes | No | Yes | Yes | Partial* | Yes | Yes |
| All firms priced | Yes | Yes | Yes | Yes | No** | Yes | Yes |

*\* Skyfall priced firm_0 and firm_1 but missed firm_2, scoring 7/9.*
*\*\* Only 2 of 3 firms returned in pricing output.*

---

## Decision Quality

| Dimension | Best | Good | Fair |
|-----------|------|------|------|
| **Strategic coherence** (NPV reasoning, pipeline optionality) | DS-R1, DS-v3.2, Qwen-235B, MiniMax | Mistral, GLM-4, Phi-4, Scout, Gemini, Behemoth | Gemma-3, Nemotron, Skyfall |
| **Financial accuracy** (DCF, debt/equity tradeoffs) | DS-R1, DS-v3.2 | Qwen-235B, Mistral, Scout, DarkNexus | Gemma-3, GLM-4, Horde models |
| **Competitive awareness** (pricing vs rivals) | DS-R1, DS-v3.2, Qwen-235B, MiniMax, Scout | Mistral, GLM-4, Phi-4, Gemini, DarkNexus | Gemma-3, Nemotron, Skyfall |
| **Credit risk assessment** (full-sim validated) | Gemma-3 | DS-v3.2 | others untested in full sim |

---

## AI Horde Notes

| Model | Status | Workers | Notes |
|-------|--------|---------|-------|
| koboldcpp/gemma-4-26B-A4B-it-heretic.IQ4_XS | **S-tier, 100%** | 1 | Fastest horde model (46s). Perfect scores. Best horde pick. |
| koboldcpp/Dark-Nexus-24B-v2.0.i1-Q5_K_M | **S-tier, 100%** | 1 | Solid all-around (104s). Good number sense ($70K price). |
| aphrodite/Behemoth-R1-123B-v2-w4a16 | **S-tier, 100%** | 1 | Perfect but slow (231s). Queue can be long (900+ jobs). |
| aphrodite/TheDrummer/Skyfall-31B-v4.1 | **A-tier, 95%** | 8 | Fast (41s), many workers. Pricing weak (missed 1 firm). |
| TheDrummer/Cydonia-24B-v4.3 | **F — timed out** | 8 | All 3 tasks timed out despite 8 workers. Unreliable. |
| koboldcpp/Gemma-4-31B-it | **F — timed out** | 1 | All 3 tasks timed out. Avoid. |
| aphrodite/GPT-OSS-120B | Offline | — | Not available on horde. |
| TheDrummer/Qwen3-Next-80B-Thinking | Offline | — | Not available on horde. |
| koboldcpp/DeepSeek-R1-Distill-Qwen-32B | Offline | — | Not available on horde. |
| aphrodite/Llama-3-70B-Instruct-v3 | Offline | — | Not available on horde. |

**Recommended horde models**: gemma-4-26B heretic (best) and Dark-Nexus-24B (runner-up).
Cydonia and Skyfall — previously fast on simple prompts — failed or weakened on full evaluation.

---

## Models Not Recommended

| Model | Reason |
|-------|--------|
| TheDrummer/Cydonia-24B-v4.3 | All 3 tasks timed out (F-tier) |
| koboldcpp/Gemma-4-31B-it | All 3 tasks timed out (F-tier) |
| bytedance-seed/seed-2.0-mini | 11 min per eval — unusable for simulation |
| nvidia/nemotron-super-49b | 5 min, same cost as Gemini Flash (10s) |
| nvidia/nemotron-3-super-120b | 5 min, $0.30/M, same quality as $0.065/M models |
| qwen/qwen3-14b | 11 min, dense variant — MoE (235B) is 20x faster |
| qwen/qwen3-32b | 4 min, dense variant — MoE (235B) is 8x faster |
| deepseek/deepseek-v3.2-exp | 6% pricier than stable v3.2, no quality gain |
| mistralai/mistral-small-3.2 | 2x cost of v2501, no quality gain |
| minimax/minimax-m2.7 | Environment task failed; $0.75/M; M2.5 is cheaper and more reliable |

---

## Notes

- **Phi-4 previously failed** in a full 16Q simulation (defaulted Q4, broken credit JSON).
  Now passes all 3 tasks. Needs full-sim revalidation before trusting for financial roles.
- **AI Horde availability fluctuates**. 4 of 10 requested models were offline.
  Cydonia had 8 workers but timed out on full prompts — simple prompts =/= simulation prompts.
- **DeepSeek R1** reasoning is qualitatively superior (explicit NPV calculations,
  pipeline optionality analysis) but 30x slower and 20x more expensive than Mistral.
- The efficient frontier is flat: 14 models achieve 100% on this rubric (11 OpenRouter + 3 horde).
  Differentiation happens in narrative depth and multi-quarter stability,
  which require full simulation runs to assess.
