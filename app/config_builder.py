"""
Streamlit config builder.

Interactive GUI for composing a simulation config file. User picks
firm count, quarter count, seed, feature toggles, and LLM backend.
Output: preview YAML + download button + launch-run button.

Launch:
    python -m streamlit run app/config_builder.py
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import streamlit as st
import yaml

st.set_page_config(page_title="LLM Firm Lab — Config Builder",
                   page_icon="⚙️", layout="wide")

st.title("⚙️ LLM Firm Lab — Config Builder")
st.caption("Compose a run config, preview the YAML, and launch the simulation.")

# ── Basics ───────────────────────────────────────────────────────────────

st.header("1. Basics")
col1, col2, col3 = st.columns(3)
with col1:
    n_firms = st.number_input("Firms (initial)", 2, 20, 5, 1)
    n_quarters = st.number_input("Quarters", 4, 80, 8, 1)
    seed = st.number_input("Seed", 0, 999999, 42, 1)
with col2:
    mode = st.selectbox("Mode", ["public_start", "stealth_start"], 0)
    information_regime = st.selectbox(
        "Information regime", ["baseline", "high_opacity", "full_transparency"], 0)
    measurement_regime = st.selectbox(
        "Measurement regime", ["baseline_gaap", "ifrs", "cash_basis"], 0)
with col3:
    entry_exit = st.checkbox("Entry / exit", True)
    financial_institutions = st.checkbox("Financial institutions", True)
    parallel = st.checkbox("Parallel firm LLM calls (~N× speedup)", True)

# ── Backend ──────────────────────────────────────────────────────────────

st.header("2. LLM backend")
col1, col2 = st.columns(2)
with col1:
    backend = st.selectbox("Default backend",
                           ["openrouter", "mock", "ollama", "minimax", "aihorde"], 0)
    model = st.text_input("Default model",
                          "mistralai/mistral-small-24b-instruct-2501")
with col2:
    if backend != "mock":
        st.info("Override individual firm models below (section 4).")

use_mock_for_run = backend == "mock"

# ── Feature toggles ──────────────────────────────────────────────────────

st.header("3. Features (all toggleable)")

tabs = st.tabs(["Stage 0-2", "Stage 3 debt", "Stage 4-5 WC/BDE",
                "Stage 6-9 EM/SEC/analysts", "Stage 10-12 advanced"])

with tabs[0]:
    c1, c2 = st.columns(2)
    with c1:
        ma_enabled = st.checkbox("M&A (mergers + acquisitions)", False)
        leasing_enabled = st.checkbox("Leasing (operating leases)", False)
        stock_comp_enabled = st.checkbox("Stock-based comp (CEO grants)", True)
    with c2:
        workforce_detail = st.checkbox("Workforce detail (hires/fires)", False)
        provisions_enabled = st.checkbox("Provisions (warranty / restructuring)", False)
        macro_expansion_enabled = st.checkbox("Macro expansion (wider shocks)", True)

with tabs[1]:
    c1, c2 = st.columns(2)
    with c1:
        debt_covenants_enabled = st.checkbox("Debt covenants", True)
        convertible_debt_enabled = st.checkbox(
            "Convertible debt (requires covenants)", False)
    with c2:
        max_active_facilities = st.number_input(
            "Max active facilities per firm", 1, 50, 10, 1)

with tabs[2]:
    c1, c2 = st.columns(2)
    with c1:
        working_capital_decisions = st.checkbox(
            "Firm sets DSO/DPO/deposits/PP&E disposal", True)
        bad_debt_enabled = st.checkbox("Bad debt + allowance", True)
    with c2:
        restructuring_enabled = st.checkbox(
            "Restructuring (severance, impairments)", True)
        env_decision_overrides_enabled = st.checkbox(
            "Env can override infeasible firm decisions", True)

with tabs[3]:
    c1, c2 = st.columns(2)
    with c1:
        earnings_management_enabled = st.checkbox(
            "Earnings management (accrual manipulation)", True)
        sec_enabled = st.checkbox("SEC surveillance", True)
        restatements_enabled = st.checkbox("Restatements", True)
    with c2:
        sellside_analysts_enabled = st.checkbox("Sell-side analysts", True)
        earnings_announcement_enabled = st.checkbox(
            "Earnings announcements + guidance", True)
        auditor_enabled = st.checkbox("Auditor pool (annual)", True)
        governance_enabled = st.checkbox("Board governance (annual)", True)

with tabs[4]:
    c1, c2 = st.columns(2)
    with c1:
        legal_reserves_enabled = st.checkbox("Legal reserves / litigation", True)
        pension_enabled = st.checkbox("Pension obligations", True)
        deferred_taxes_enabled = st.checkbox("Deferred taxes (DTA/DTL)", True)
    with c2:
        activist_investors_enabled = st.checkbox("Activist investors", True)
        annual_reports_enabled = st.checkbox("10-K-style annual reports", True)
        env_verification_enabled = st.checkbox(
            "Env output verifier (catches hallucinations)", True)
        data_broker_enabled = st.checkbox("Data broker (WRDS-style queries)", True)

if data_broker_enabled:
    data_broker_mode = st.selectbox(
        "Data broker mode",
        ["combo", "templates_only", "code_gen_only"], 0,
        help="combo = templates first, fall back to code gen")
    data_broker_max_queries = st.number_input(
        "Max broker queries / agent / quarter", 0, 10, 2, 1)
else:
    data_broker_mode = "combo"
    data_broker_max_queries = 2

# ── Per-firm overrides (optional) ────────────────────────────────────────

st.header("4. Per-firm LLM overrides (optional)")
st.caption("Leave blank to use the default. Useful for model-diversity experiments.")

firm_overrides = {}
with st.expander("Configure each firm's model", expanded=False):
    for i in range(n_firms):
        c1, c2, c3 = st.columns([2, 2, 1])
        with c1:
            m_model = st.text_input(f"firm_{i} model",
                                     "" if not use_mock_for_run else "mock",
                                     key=f"firm_{i}_model")
        with c2:
            m_backend = st.selectbox(f"firm_{i} backend",
                                      ["", "openrouter", "mock", "ollama"], 0,
                                      key=f"firm_{i}_backend")
        with c3:
            m_temp = st.number_input(f"firm_{i} temp",
                                      0.0, 2.0, 0.3, 0.05,
                                      key=f"firm_{i}_temp")
        if m_model.strip() and m_backend.strip():
            firm_overrides[f"firm_{i}"] = {
                "model": m_model, "backend": m_backend, "temperature": m_temp,
            }

# ── Assemble config ─────────────────────────────────────────────────────

config = {
    "n_firms_initial": int(n_firms),
    "n_firms_max": max(int(n_firms) + 2, 7),
    "n_quarters": int(n_quarters),
    "seed": int(seed),
    "mode": mode,
    "information_regime": information_regime,
    "measurement_regime": measurement_regime,
    "entry_exit": entry_exit,
    "financial_institutions": financial_institutions,
    "parallel_firm_decisions": parallel,
    "default_llm": {"backend": backend, "model": model},
    "ma_enabled": ma_enabled,
    "leasing_enabled": leasing_enabled,
    "stock_comp_enabled": stock_comp_enabled,
    "workforce_detail": workforce_detail,
    "provisions_enabled": provisions_enabled,
    "macro_expansion_enabled": macro_expansion_enabled,
    "debt_covenants_enabled": debt_covenants_enabled,
    "convertible_debt_enabled": convertible_debt_enabled,
    "max_active_facilities_per_firm": int(max_active_facilities),
    "working_capital_decisions": working_capital_decisions,
    "bad_debt_enabled": bad_debt_enabled,
    "restructuring_enabled": restructuring_enabled,
    "env_decision_overrides_enabled": env_decision_overrides_enabled,
    "earnings_management_enabled": earnings_management_enabled,
    "sec_enabled": sec_enabled,
    "sellside_analysts_enabled": sellside_analysts_enabled,
    "earnings_announcement_enabled": earnings_announcement_enabled,
    "auditor_enabled": auditor_enabled,
    "governance_enabled": governance_enabled,
    "restatements_enabled": restatements_enabled,
    "legal_reserves_enabled": legal_reserves_enabled,
    "pension_enabled": pension_enabled,
    "deferred_taxes_enabled": deferred_taxes_enabled,
    "activist_investors_enabled": activist_investors_enabled,
    "annual_reports_enabled": annual_reports_enabled,
    "env_verification_enabled": env_verification_enabled,
    "data_broker_enabled": data_broker_enabled,
    "data_broker_mode": data_broker_mode,
    "data_broker_max_queries_per_agent_per_quarter": int(data_broker_max_queries),
}
if firm_overrides:
    config["agents"] = firm_overrides

# ── Preview + download + launch ─────────────────────────────────────────

st.header("5. Preview + launch")
yaml_text = yaml.safe_dump(config, default_flow_style=False, sort_keys=False)
st.code(yaml_text, language="yaml")

col1, col2, col3 = st.columns([1, 1, 2])
with col1:
    st.download_button("📥 Download YAML", yaml_text,
                       file_name="custom_run.yaml", mime="text/yaml")
with col2:
    save_path = st.text_input("Save as", "config/custom_run.yaml")
    if st.button("💾 Save to disk"):
        Path(save_path).parent.mkdir(parents=True, exist_ok=True)
        Path(save_path).write_text(yaml_text)
        st.success(f"Saved to {save_path}")

with col3:
    launch_cols = st.columns(2)
    with launch_cols[0]:
        use_mock_flag = st.checkbox("--mock (deterministic, no API calls)",
                                     value=use_mock_for_run)
    with launch_cols[1]:
        quarters_override = st.number_input(
            "Quarters (override, 0 = use config)", 0, 80, 0, 1,
            help="Useful for quick smoke tests.")

    if st.button("🚀 Launch run", type="primary"):
        Path(save_path).parent.mkdir(parents=True, exist_ok=True)
        Path(save_path).write_text(yaml_text)
        cmd = [sys.executable, "-u", "-m", "src", "run",
               "--config", save_path]
        if use_mock_flag:
            cmd.append("--mock")
        if quarters_override > 0:
            cmd.extend(["--quarters", str(int(quarters_override))])
        st.info(f"Running: `{' '.join(cmd)}`")
        st.caption("Live runs take ~15-25 min per quarter on OpenRouter. "
                   "Check outputs/run_*/ for results.")
        # Spawn detached so the dashboard stays responsive.
        subprocess.Popen(cmd)
        st.success(f"Launched in background at {time.strftime('%H:%M:%S')}. "
                   "Switch to the dashboard to monitor outputs.")

st.sidebar.markdown("### Quick presets")
if st.sidebar.button("🧪 Mock smoke (3×5Q, all toggles on)"):
    st.session_state["preset"] = "mock_smoke"
    st.rerun()
if st.sidebar.button("🏭 Full validation (5×8Q, all toggles)"):
    st.session_state["preset"] = "validation_full"
    st.rerun()
if st.sidebar.button("🤝 M&A stress test"):
    st.session_state["preset"] = "ma_stress"
    st.rerun()

st.sidebar.markdown("---")
st.sidebar.markdown("### Runs so far")
outputs = Path("outputs")
if outputs.exists():
    runs = sorted(
        [d.name for d in outputs.iterdir() if d.is_dir() and d.name.startswith("run_")],
        reverse=True)
    st.sidebar.metric("Total runs", len(runs))
    if runs:
        st.sidebar.caption(f"Most recent: `{runs[0]}`")
else:
    st.sidebar.caption("No outputs yet.")
