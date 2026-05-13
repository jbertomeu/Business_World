"""
Data Analyst Agent: LLM writes Python code for statistical analysis, executes
in subprocess, interprets results, and returns a report.

Flow:
1. Requesting agent (board discussion) sends specific analysis questions
2. Data analyst LLM writes Python code to answer the questions
3. Code executed in subprocess against Compustat data (safe sandbox)
4. stdout/stderr captured and sent back to analyst LLM
5. Analyst LLM interprets results and writes a report
6. Report returned to the requesting agent

Information boundaries:
- Data analyst sees ONLY: Compustat data (public financials) + the question
- Does NOT see: private firm data, board minutes, world secrets
- Each request is independent — no memory between requests
"""

from __future__ import annotations

import csv
import os
import subprocess
import tempfile
from pathlib import Path

from .llm_backends import LLMBackend, extract_json


CODE_GENERATION_PROMPT = """You are a quantitative financial analyst. You write Python code to analyze
pharmaceutical firm financial data from Compustat quarterly panels.

You have TWO separate data sources:
1. CURRENT_RUN (CSV path): This simulation's data only (the run in progress)
2. ALL_RUNS (CSV path): Historical database from ALL past simulations (759+ rows from 39+ runs)

Use CURRENT_RUN for questions about the current competitive situation.
Use ALL_RUNS for questions about historical patterns, benchmarks, and cross-run trends.
You can join or compare them.

Compustat columns include:
  run_id, firm_id, fyearq, fqtr,
  saleq (revenue), cogsq (COGS), gpq (gross profit),
  xrdq (R&D expense), xsgaq (SGA expense), dpq (depreciation),
  oiadpq (operating income), xintq (interest expense),
  niq (net income), cheq (cash), rectq (AR), invtq (inventory),
  ppentq (PP&E net), atq (total assets),
  dlcq (revolver balance), dlttq (long-term debt), ltq (total liabilities),
  ceqq (total equity), req (retained earnings),
  prccq (equity price), cshoq (shares outstanding in millions),
  mkvaltq (market cap), capxq (capital expenditure),
  sstkq (equity issuance), fincfq (financing cash flow),
  default_flag (1 if defaulted)

Write Python code using pandas and numpy. Print clear formatted results.
Output ONLY the Python code, no explanation."""


INTERPRETATION_PROMPT = """You are a financial analyst interpreting statistical results.

Given the raw output from a Python analysis script, write a clear 1-3 page report
that a board of directors would understand. Include:
- Key findings with specific numbers
- What the data suggests about strategy
- Caveats or limitations of the analysis
- Actionable insights

Do NOT include code or technical details. Write for executives."""


def run_data_analysis(
    question: str,
    current_run_rows: list,
    data_dir: str,
    backend: LLMBackend,
    max_retries: int = 2,
) -> str:
    """Run a complete data analysis cycle: question → code → execute → interpret.

    Returns a formatted report string, or an error message.
    """

    # Export current run data to temp CSV
    current_csv = _export_to_temp_csv(current_run_rows)
    all_runs_csv = str(Path(data_dir) / "compustat_all.csv")

    if not Path(all_runs_csv).exists():
        all_runs_csv = current_csv  # fallback if no cross-run data

    # Step 1: LLM writes analysis code
    code_prompt = (
        f"ANALYSIS QUESTION:\n{question}\n\n"
        f"Write Python code to answer this question using the Compustat data.\n"
        f"The code will have these variables available:\n"
        f"  CURRENT_RUN = '{current_csv}'\n"
        f"  ALL_RUNS = '{all_runs_csv}'\n\n"
        f"Print clear, formatted results. Use pandas and numpy."
    )

    code_response = backend.complete(CODE_GENERATION_PROMPT, code_prompt)
    code = _extract_code(code_response)

    if not code:
        return f"(Data analyst failed to generate code for: {question[:100]})"

    # Step 2: Execute in subprocess
    for attempt in range(max_retries + 1):
        output = _execute_code(code, current_csv, all_runs_csv)

        if "Error" in output or "Traceback" in output:
            if attempt < max_retries:
                # Ask LLM to fix the code
                fix_prompt = (
                    f"Your code produced an error:\n\n{output}\n\n"
                    f"Original question: {question}\n"
                    f"Fix the code. Output ONLY the corrected Python code."
                )
                fix_response = backend.complete(CODE_GENERATION_PROMPT, fix_prompt)
                code = _extract_code(fix_response)
                if not code:
                    break
            else:
                return f"(Analysis failed after {max_retries} retries: {output[:200]})"
        else:
            break

    if not output.strip():
        return "(Analysis produced no output)"

    # Step 3: LLM interprets results
    interpret_prompt = (
        f"ANALYSIS QUESTION: {question}\n\n"
        f"RAW ANALYSIS OUTPUT:\n{output}\n\n"
        f"Write a clear executive report interpreting these results."
    )

    report = backend.complete(INTERPRETATION_PROMPT, interpret_prompt)
    return report


def _export_to_temp_csv(rows: list) -> str:
    """Export Compustat rows to a temporary CSV file."""
    if not rows:
        tmp = tempfile.NamedTemporaryFile(suffix='.csv', mode='w', delete=False,
                                          newline='', encoding='utf-8')
        tmp.write("empty\n")
        tmp.close()
        return tmp.name

    tmp = tempfile.NamedTemporaryFile(suffix='.csv', mode='w', delete=False,
                                      newline='', encoding='utf-8')
    fieldnames = list(rows[0].as_dict().keys())
    writer = csv.DictWriter(tmp, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
        writer.writerow(row.as_dict())
    tmp.close()
    return tmp.name


def _extract_code(response: str) -> str:
    """Extract Python code from LLM response."""
    import re

    # Try ```python ... ``` block
    m = re.search(r'```python\s*(.*?)\s*```', response, re.DOTALL)
    if m:
        return m.group(1)

    # Try ``` ... ``` block
    m = re.search(r'```\s*(.*?)\s*```', response, re.DOTALL)
    if m:
        return m.group(1)

    # If response looks like pure code (starts with import), use it directly
    lines = response.strip().split('\n')
    if lines and (lines[0].startswith('import ') or lines[0].startswith('from ')):
        return response.strip()

    return ""


def _execute_code(code: str, current_csv: str, all_runs_csv: str) -> str:
    """Execute Python code in subprocess with data paths injected."""
    # Build the full script
    script = (
        f"import pandas as pd\n"
        f"import numpy as np\n"
        f"try:\n"
        f"    from scipy import stats\n"
        f"except ImportError:\n"
        f"    pass\n"
        f"\n"
        f"CURRENT_RUN = r'{current_csv}'\n"
        f"ALL_RUNS = r'{all_runs_csv}'\n"
        f"\n"
        f"{code}\n"
    )

    # Write to temp file
    with tempfile.NamedTemporaryFile(suffix='.py', mode='w', delete=False,
                                     encoding='utf-8') as f:
        f.write(script)
        script_path = f.name

    try:
        result = subprocess.run(
            ['python', script_path],
            capture_output=True, text=True, timeout=30,
            encoding='utf-8',
        )
        output = result.stdout
        if result.stderr:
            output += "\n" + result.stderr
        return output
    except subprocess.TimeoutExpired:
        return "Error: Analysis timed out after 30 seconds"
    except Exception as e:
        return f"Error: {e}"
    finally:
        try:
            os.unlink(script_path)
        except OSError:
            pass
