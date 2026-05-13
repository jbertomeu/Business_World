"""
Data Broker: a research assistant agent for any simulation role.

Receives natural-language queries with a required hypothesis, executes the
analysis (template or code), and returns an interpreted answer.

Three modes (selected at simulation start via config.data_broker_mode):

  "template_only" — Broker picks from 10 pre-built templates. If none fit,
                    returns an error. Fastest, most reliable.

  "combo"         — Broker tries templates first. If no template matches,
                    falls back to writing custom pandas code. Balanced.

  "freeform"      — Broker always writes custom pandas code. Most flexible,
                    slowest, highest variance.

Other principles:
- Demand-driven: only fires when an agent explicitly asks
- Per-agent, per-request: no batching
- Hypothesis-gated: query without a decision-relevant hypothesis rejected
- Tier-scoped: data access follows src/data_access.py policy
- Cache-aware: identical queries within a quarter reuse the answer
- Cost-capped: max queries per agent per quarter (default 3)
"""

from __future__ import annotations

import csv
import json
import os
import re
import subprocess
import tempfile

from .data_access import (
    DataTier, tiers_for_role, filter_compustat_row, role_to_key,
)
from .data_templates import TEMPLATE_REGISTRY, load_cross_run, load_current_run
from .llm_backends import LLMBackend


BROKER_MODES = ("template_only", "combo", "freeform")


# ── Data catalog exposed to the Broker ─────────────────────────────────

DATA_CATALOG = """
Available data tables (all roles with PUBLIC tier have access):

TABLE: current_run_compustat
  Granularity: firm-quarter for the CURRENT run only
  Rows: grows as simulation progresses (N_firms * N_quarters_elapsed)
  Key columns (Compustat-style, quarterly, USD unless noted):
    firm_id (string), fyearq (fiscal year), fqtr (fiscal quarter 1-4)
    saleq (net sales), cogsq (cost of goods sold), gpq (gross profit)
    xrdq (R&D expense), xsgaq (SGA expense), dpq (depreciation)
    oiadpq (operating income), xintq (interest expense), piq (pretax income)
    niq (net income, REPORTED i.e. post-manipulation if EM enabled)
    cheq (cash), rectq (AR), invtq (inventory), ppentq (PP&E net), atq (total assets)
    apq (AP), lctq (current liab), dlcq (ST debt), dlttq (LT debt), ltq (total liab)
    ceqq (total equity), req (retained earnings)
    oancfq (cash from ops), ivncfq (investing CF), fincfq (financing CF)
    capxq (capex), sstkq (stock issued), prstkq (stock repurchased), dvq (dividends)
    prccq (share price), cshoq (shares outstanding, millions), mkvaltq (market cap)
    default_flag (1/0), audit_opinion (Q4 only), restatement_flag (1/0)

TABLE: cross_run_compustat
  Granularity: firm-quarter across ALL past runs
  Rows: ~800-15000 depending on run history
  Columns: same as current_run_compustat + run_id
  Use for: historical benchmarks, "what happened to firms like this?"

Available templates (call one of these):
  peer_benchmark(metric, firm_id, quarter_filter=None)
    - Firm vs peers: z-score, percentile, rank
  time_series(metric, firm_id, lookback=8)
    - Trend, volatility, AR(1), QoQ growth
  anomaly_score(metric, firm_id)
    - Combines peer + self-history z-scores
  correlation(var1, var2, lag=0)
    - Pearson r between two metrics (optional time lag)
  cohort_compare(firm_id, cohort_criterion="same_quarter"|"same_generation")
    - Firm vs matched cohort on multiple key metrics
  dcf_projection(revenue_last_4q, opex_last_4q, growth_rate_annual,
                 discount_rate_annual, terminal_growth=0.03, horizon_quarters=20)
    - 20Q DCF with terminal value
  accrual_quality(firm_id, lookback=8)
    - Dechow-Dichev-style accrual quality measure
  credit_metrics(firm_id)
    - Leverage, interest coverage, cash runway
  industry_concentration(quarter=None)
    - HHI, top-3 market share
"""


# ── Broker prompt ──────────────────────────────────────────────────────

BROKER_SYSTEM_PROMPT_TEMPLATE_ONLY = """You are the Data Broker — a research assistant for simulation agents.

An agent has asked you a question with a stated hypothesis. Your job:
1. Pick the best template from the catalog below
2. Fill in its parameters using the context and the agent's question
3. Return a JSON object describing what to run

You do NOT make the agent's decision. You produce numeric evidence the agent
will interpret. Be precise about metric names (use Compustat column names —
e.g. saleq, niq, xrdq).

If the query cannot be answered by any template, return:
{"action": "reject", "reason": "<brief explanation>"}

Otherwise return:
{
  "action": "template",
  "template_name": "<one of the templates>",
  "args": {<template args>},
  "data_source": "current_run" | "cross_run" | "both"
}

Output ONLY JSON wrapped in ```json ... ```."""


BROKER_SYSTEM_PROMPT_COMBO = """You are the Data Broker — a research assistant for simulation agents.

An agent has asked you a question with a stated hypothesis. Your job is to
decide the best way to answer.

Prefer TEMPLATES when one fits — they're tested and fast. Use CODE only when
no template matches the question.

Return one of these JSON structures:

Option A (preferred — use a template):
{
  "action": "template",
  "template_name": "<one of the templates>",
  "args": {<template args>},
  "data_source": "current_run" | "cross_run" | "both"
}

Option B (custom pandas code for novel queries):
{
  "action": "code",
  "code": "<Python code that reads CURRENT_RUN and/or ALL_RUNS paths,
           computes the analysis, and prints results as structured text>",
  "data_source": "current_run" | "cross_run" | "both"
}

Option C (reject if hypothesis is trivial or question is unanswerable):
{"action": "reject", "reason": "<brief explanation>"}

Output ONLY JSON wrapped in ```json ... ```."""


BROKER_SYSTEM_PROMPT_FREEFORM = """You are the Data Broker — a research assistant for simulation agents.

An agent has asked you a question with a stated hypothesis. Write pandas code
to answer it. Your code will execute in a subprocess with access to CSV files
(paths provided as CURRENT_RUN and ALL_RUNS variables).

Available libraries: pandas (pd), numpy (np), scipy.stats (if needed).

Guidelines:
- Filter to relevant rows first
- Print numeric results as labeled output (e.g., print('firm_X mean revenue:', val))
- Keep output under 1000 characters
- Handle missing columns gracefully (use .get or try/except)
- Do NOT import os, sys, or anything file-system related — only pandas/numpy

Return JSON:
{
  "action": "code",
  "code": "<pandas code>",
  "data_source": "current_run" | "cross_run" | "both"
}

Or reject trivial queries:
{"action": "reject", "reason": "..."}

Output ONLY JSON wrapped in ```json ... ```."""


def _get_system_prompt(mode: str) -> str:
    """Pick the system prompt for the Broker based on mode."""
    if mode == "template_only":
        return BROKER_SYSTEM_PROMPT_TEMPLATE_ONLY
    if mode == "combo":
        return BROKER_SYSTEM_PROMPT_COMBO
    if mode == "freeform":
        return BROKER_SYSTEM_PROMPT_FREEFORM
    raise ValueError(f"Unknown broker mode: {mode}")


def _write_temp_csv(rows: list[dict]) -> str:
    """Write rows (already filtered) to a temp CSV. Returns path."""
    tmp = tempfile.NamedTemporaryFile(suffix=".csv", mode="w", delete=False,
                                       newline="", encoding="utf-8")
    if not rows:
        tmp.write("empty\n")
        tmp.close()
        return tmp.name
    # Gather union of all column names in case rows have different subsets
    fieldnames: list[str] = []
    seen: set[str] = set()
    for r in rows:
        for k in r.keys():
            if k not in seen:
                seen.add(k)
                fieldnames.append(k)
    writer = csv.DictWriter(tmp, fieldnames=fieldnames)
    writer.writeheader()
    for r in rows:
        writer.writerow(r)
    tmp.close()
    return tmp.name


def _run_sandboxed_code(code: str, current_csv: str, all_runs_csv: str) -> str:
    """Run LLM-generated pandas code in a subprocess. Returns stdout+stderr."""
    # Strip ```python fences if LLM included them
    m = re.search(r"```(?:python)?\s*(.*?)\s*```", code, re.DOTALL)
    if m:
        code = m.group(1)

    script = (
        "import pandas as pd\n"
        "import numpy as np\n"
        "try:\n"
        "    from scipy import stats\n"
        "except ImportError:\n"
        "    pass\n"
        "\n"
        f"CURRENT_RUN = r'{current_csv}'\n"
        f"ALL_RUNS = r'{all_runs_csv}'\n"
        "\n"
        f"{code}\n"
    )

    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False,
                                       encoding="utf-8") as f:
        f.write(script)
        script_path = f.name

    try:
        result = subprocess.run(
            ["python", script_path],
            capture_output=True, text=True, timeout=30,
            encoding="utf-8",
        )
        out = result.stdout or ""
        if result.stderr:
            out += "\n[stderr]\n" + result.stderr
        return out.strip() or "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: code timed out after 30s"
    except Exception as e:
        return f"Error: {e}"
    finally:
        try:
            os.unlink(script_path)
        except OSError:
            pass


def _is_valid_hypothesis(hypothesis: str) -> bool:
    """A valid hypothesis describes a decision-relevant branch."""
    if not hypothesis or not isinstance(hypothesis, str):
        return False
    stripped = hypothesis.strip().lower()
    if len(stripped) < 15:
        return False
    # Reject common non-hypotheses
    bad_patterns = [
        "data check", "want to see", "curious", "just checking",
        "what is", "show me",
    ]
    if any(p in stripped for p in bad_patterns) and len(stripped) < 40:
        return False
    return True


class DataBroker:
    """Per-request data analyst. Call `.answer()` for each query.

    Typical usage:
        broker = DataBroker(backend, data_dir)
        result = broker.answer(
            agent_role="sec",
            query_text="Are firm_2's accruals abnormal?",
            hypothesis="If accrual z-score > 2, I'll open an investigation.",
            current_run_rows=state.compustat_rows,
            quarter=state.quarter,
        )
    """

    def __init__(
        self,
        backend: LLMBackend,
        data_dir: str = "data",
        enforce_hypothesis: bool = True,
        max_queries_per_agent_per_quarter: int = 3,
        mode: str = "template_only",
    ):
        if mode not in BROKER_MODES:
            raise ValueError(f"Invalid broker mode '{mode}'. Must be one of {BROKER_MODES}.")
        self.backend = backend
        self.data_dir = data_dir
        self.enforce_hypothesis = enforce_hypothesis
        self.max_queries = max_queries_per_agent_per_quarter
        self.mode = mode

        # Cache: (query_text_normalized, role_key) -> answer_string
        self._cache: dict[tuple[str, str], str] = {}

        # Query log: (agent_role, quarter) -> count
        self._query_counts: dict[tuple[str, int], int] = {}

        # Full log of queries for auditing
        self.query_log: list[dict] = []

    def answer(
        self,
        agent_role: str,
        query_text: str,
        hypothesis: str,
        current_run_rows: list | None = None,
        quarter: int = 0,
        extra_context: dict | None = None,
    ) -> str:
        """Answer a data query from an agent.

        Returns a string (the interpreted answer, or a rejection message).
        """
        # Cost cap check
        key = (agent_role, quarter)
        count = self._query_counts.get(key, 0)
        if count >= self.max_queries:
            return (
                f"[Data Broker] Query rejected: {agent_role} has used "
                f"{count}/{self.max_queries} queries this quarter. Proceed without data."
            )

        # Hypothesis check
        if self.enforce_hypothesis and not _is_valid_hypothesis(hypothesis):
            return (
                "[Data Broker] Query rejected: no decision-relevant hypothesis. "
                "Reformulate: describe what you'd do differently based on the answer, "
                "or proceed without data."
            )

        # Cache check
        cache_key = (query_text.strip().lower(), role_to_key(agent_role))
        if cache_key in self._cache:
            return f"{self._cache[cache_key]} [cached]"

        # Load data filtered by tier
        rows = load_current_run(current_run_rows)
        rows = [filter_compustat_row(r, agent_role) for r in rows]

        cross_run_rows = load_cross_run(self.data_dir)
        cross_run_rows = [filter_compustat_row(r, agent_role) for r in cross_run_rows]

        # Build broker prompt
        user = self._build_user_prompt(
            agent_role, query_text, hypothesis, quarter,
            n_current=len(rows), n_cross=len(cross_run_rows),
            extra_context=extra_context,
        )

        # Call LLM with mode-specific system prompt
        system_prompt = _get_system_prompt(self.mode)
        try:
            plan = self.backend.complete_json(system_prompt, user)
        except Exception as e:
            return f"[Data Broker] LLM error: {e}"

        if plan is None:
            return "[Data Broker] Failed to produce a valid plan."

        # Execute the plan
        action = plan.get("action")
        if action == "reject":
            answer = f"[Data Broker] Cannot answer: {plan.get('reason', 'unclear')}"
        elif action == "template":
            if self.mode == "freeform":
                answer = "[Data Broker] Mode is 'freeform'; only code actions allowed."
            else:
                answer = self._execute_template(plan, rows, cross_run_rows)
        elif action == "code":
            if self.mode == "template_only":
                answer = (
                    "[Data Broker] Query did not match any template. "
                    "Mode is 'template_only'; enable 'combo' or 'freeform' mode for custom code."
                )
            else:
                answer = self._execute_code(plan, rows, cross_run_rows, agent_role)
        else:
            answer = f"[Data Broker] Unknown action: {action}"

        # Log and cache
        self._cache[cache_key] = answer
        self._query_counts[key] = count + 1
        self.query_log.append({
            "agent_role": agent_role,
            "quarter": quarter,
            "query": query_text,
            "hypothesis": hypothesis,
            "plan": plan,
            "answer_preview": answer[:200],
        })

        return answer

    def _build_user_prompt(
        self,
        agent_role: str,
        query_text: str,
        hypothesis: str,
        quarter: int,
        n_current: int,
        n_cross: int,
        extra_context: dict | None = None,
    ) -> str:
        tiers = tiers_for_role(agent_role)
        tier_names = sorted(t.value for t in tiers)

        ctx_str = ""
        if extra_context:
            ctx_str = f"\nAGENT CONTEXT:\n{json.dumps(extra_context, default=str)[:500]}"

        return f"""AGENT: {agent_role}
DATA TIERS ACCESSIBLE: {', '.join(tier_names)}
CURRENT QUARTER: {quarter}
DATA AVAILABLE: {n_current} rows current run | {n_cross} rows cross-run

QUESTION: {query_text}

HYPOTHESIS (what they'll do differently based on answer):
{hypothesis}
{ctx_str}

DATA CATALOG:
{DATA_CATALOG}

{self._mode_instruction()}"""

    def _mode_instruction(self) -> str:
        """Per-mode final instruction for the Broker LLM."""
        if self.mode == "template_only":
            return "Pick a template and parameters. Be specific about column names."
        if self.mode == "combo":
            return (
                "Prefer a template if one fits. If no template matches the query, "
                "write custom pandas code. Be specific about column names."
            )
        if self.mode == "freeform":
            return (
                "Write pandas code to answer the question. Use CURRENT_RUN and/or "
                "ALL_RUNS as CSV paths in your code. Print labeled numeric results."
            )
        return ""

    def _execute_code(
        self,
        plan: dict,
        current_rows: list[dict],
        cross_run_rows: list[dict],
        agent_role: str,
    ) -> str:
        """Execute LLM-generated pandas code in a sandboxed subprocess."""
        code = plan.get("code", "")
        if not code.strip():
            return "[Data Broker] Empty code block."

        source = plan.get("data_source", "current_run")

        # Write current_run rows to temp CSV (already tier-filtered by caller)
        current_csv = _write_temp_csv(current_rows)
        cross_csv = os.path.join(self.data_dir, "compustat_all.csv")
        if not os.path.exists(cross_csv):
            cross_csv = current_csv  # fallback

        try:
            output = _run_sandboxed_code(code, current_csv, cross_csv)
        finally:
            try:
                os.unlink(current_csv)
            except OSError:
                pass

        # Truncate pathological outputs
        if len(output) > 2000:
            output = output[:2000] + "\n...[truncated]"

        return f"[Data Broker] custom pandas analysis:\n{output}"

    def _execute_template(
        self,
        plan: dict,
        current_rows: list[dict],
        cross_run_rows: list[dict],
    ) -> str:
        """Run a template by name and interpret the result."""
        name = plan.get("template_name", "")
        args = plan.get("args", {})
        source = plan.get("data_source", "current_run")

        if name not in TEMPLATE_REGISTRY:
            return f"[Data Broker] Unknown template: {name}"

        # Pick data source
        if source == "cross_run":
            args["rows"] = cross_run_rows
        elif source == "both":
            args["rows"] = current_rows + cross_run_rows
        else:
            args["rows"] = current_rows

        # Some templates don't take rows (dcf_projection)
        if name == "dcf_projection":
            args.pop("rows", None)

        try:
            fn = TEMPLATE_REGISTRY[name]
            result = fn(**args)
        except TypeError as e:
            return f"[Data Broker] Template args invalid for {name}: {e}"
        except Exception as e:
            return f"[Data Broker] Template {name} failed: {e}"

        # Format the result as a readable answer
        if "error" in result:
            return f"[Data Broker] {name}: {result['error']}"

        return self._format_result(name, args, result)

    def _format_result(self, name: str, args: dict, result: dict) -> str:
        """Render a template result as a concise, numeric answer."""
        lines = [f"[Data Broker] {name}("]
        # Brief arg summary (skip rows)
        arg_parts = []
        for k, v in args.items():
            if k == "rows":
                continue
            arg_parts.append(f"{k}={v}")
        lines[0] += ", ".join(arg_parts) + ")"

        # Format common results
        for k, v in result.items():
            if k in ("caveat", "interpretation_hint", "note"):
                continue
            if k == "all_values":
                preview = list(v.items())[:5]
                lines.append(f"  {k}: {dict(preview)}" + (" ..." if len(v) > 5 else ""))
            elif k == "values":
                lines.append(f"  {k}: {v}")
            elif k == "comparisons":
                lines.append(f"  {k}:")
                for m, vv in v.items():
                    lines.append(f"    {m}: firm={vv.get('firm_value'):.0f}, "
                                 f"mean={vv.get('cohort_mean'):.0f}, "
                                 f"z={vv.get('z_score'):.2f}")
            elif isinstance(v, float):
                lines.append(f"  {k}: {v:.4g}")
            else:
                lines.append(f"  {k}: {v}")

        if "interpretation_hint" in result:
            lines.append(f"  (hint: {result['interpretation_hint']})")
        if "caveat" in result:
            lines.append(f"  (caveat: {result['caveat']})")

        return "\n".join(lines)
