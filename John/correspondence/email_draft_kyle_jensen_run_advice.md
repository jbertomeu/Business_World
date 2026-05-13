# Email draft — Kyle Jensen (Yale SOM)

**To:** Kyle Jensen \<[kyle.jensen@yale.edu](mailto:kyle.jensen@yale.edu)\>  
*(Confirm address in your directory if different.)*

**Subject:** Quick methodological ask — LLM multi-agent industry simulation (run design / infrastructure)

---

Hi Kyle,

I’m reaching out because you’ve thought more deeply than most of us about how to run computationally heavy, agent-style research workflows without fooling ourselves about what we’re estimating.

We’ve been building a **multi-agent corporate-finance / IO “laboratory”** in which firms, banks, an environment referee, equity-market voices, PE, governance, etc. are separate **LLM-backed roles**, with **GAAP-consistent accounting** and **structured actions** adjudicated in code (not free-form ledger edits). A single long horizon can mean **many hours of wall time**, **hundreds to thousands of API calls**, and **non-trivial dollar cost**; we’re also thinking about **repeated runs** (e.g. Monte Carlo over seeds or prompt variants) for robustness.

**How we run it today (roughly):** one Python orchestrator drives a **quarterly phase pipeline**; agents are usually called over **OpenRouter** (or mock mode for tests). The **draft paper** instead pins **OpenAI / Anthropic model IDs** for the main reported run—the one-pager follows that manuscript description so you’re not stuck in our dev stack details. Each run writes **panels + JSONL audit trails + optional quarter snapshots** under `outputs/`. We sometimes **resume from mid-run snapshots** after code fixes, which raises obvious inference questions we’re trying to be explicit about.

I’d value your **second opinion on whether there is a better way to “run” this class of exercise**, given that setup—both **statistically** (what deserves to be a single run vs. a family of runs; how to report restarts; variance vs. architecture) and **operationally** (budgeting API spend, parallelism, reproducibility given provider weight drift, archiving artifacts for replication).

**Attached:** a **one-pager** (`paper-draft/one_pager_draft_run_pipeline.md`) with the **exact toggles and model roster** described in our draft paper, plus a **high-level pipeline diagram** (Mermaid)—no codebase required.

If you want more detail afterward, there is a longer spec memo and a full architecture diagram in this repo’s `John/` folder (see P.S.).

Thanks for any pointers, even if it’s just “here’s how I’d bound the claims” or “here’s what I wouldn’t bother parallelizing.”

Best,  
John

---

## Optional P.S. (delete if too much)

**Primary attachment (start here):**

- `John/paper-draft/one_pager_draft_run_pipeline.md` — toggles, roster, headline metrics, **single** high-level pipeline figure, replication blanks.

**Optional deeper dive:**

- `John/paper-draft/draft_paper_run_specification_for_review.md` — full checklist for the draft run, Q41 restart caveat, repo vs. manuscript alignment.
- `John/operations/ai_lab_architecture_and_pipeline_schema.md` — detailed quarter pipeline and information boundaries (implementation-level Mermaid).

---

*Edit the greeting/sign-off and recipient line before sending; trim the P.S. if you want a shorter first touch.*
