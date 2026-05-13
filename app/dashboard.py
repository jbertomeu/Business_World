"""
Streamlit results dashboard.

Lets the user inspect run outputs graphically. Supports:
- Single run, multiple runs, last N runs, or all runs
- Firm-level time series
- Cross-firm averages / medians
- Financial ratios (ROE, ROA, leverage, current ratio, BS identity)
- CEO comp / turnover
- Default timing / survival curve

Launch:
    python -m streamlit run app/dashboard.py
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title="LLM Firm Lab — Results", page_icon="📊",
                   layout="wide")

OUTPUTS = Path("outputs")
DATA_DIR = Path("data")


# ── Loading helpers ────────────────────────────────────────────────────

@st.cache_data(show_spinner=False)
def list_runs() -> list[str]:
    if not OUTPUTS.exists():
        return []
    return sorted(
        [d.name for d in OUTPUTS.iterdir()
         if d.is_dir() and d.name.startswith("run_")],
        reverse=True,
    )


@st.cache_data(show_spinner=False)
def load_panel(run_ids: tuple[str, ...]) -> pd.DataFrame:
    """Stitch compustat_q.csv from each selected run."""
    frames = []
    for rid in run_ids:
        p = OUTPUTS / rid / "compustat_q.csv"
        if p.exists():
            try:
                df = pd.read_csv(p)
                frames.append(df)
            except Exception as e:
                st.warning(f"Skipped {rid}: {e}")
    if not frames:
        return pd.DataFrame()
    d = pd.concat(frames, ignore_index=True, sort=False)
    # Coerce common numeric columns
    for col in ["saleq", "niq", "cheq", "atq", "ltq", "ceqq", "req",
                "dlcq", "dlttq", "prccq", "oancfq", "ivncfq", "fincfq",
                "chechq", "capxq", "xrdq", "xsgaq", "ppentq", "rectq",
                "invtq", "apq", "txtq", "piq", "allowance_dca",
                "pension_liability_bs", "legal_reserve_bs", "txditcq",
                "manipulation_amount"]:
        if col in d.columns:
            d[col] = pd.to_numeric(d[col], errors="coerce")
    # Absolute quarter index for plotting
    d["abs_q"] = (d["fyearq"].astype(int) - d["fyearq"].astype(int).min()) * 4 \
                 + d["fqtr"].astype(int)
    d["period"] = d["fyearq"].astype(int).astype(str) + "Q" + d["fqtr"].astype(int).astype(str)
    return d


@st.cache_data(show_spinner=False)
def load_dataset(run_ids: tuple[str, ...], filename: str) -> pd.DataFrame:
    frames = []
    for rid in run_ids:
        p = OUTPUTS / rid / filename
        if p.exists():
            try:
                frames.append(pd.read_csv(p))
            except Exception:
                continue
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True, sort=False)


# ── Sidebar: run selection ────────────────────────────────────────────

st.sidebar.title("📊 Results Dashboard")

runs_available = list_runs()
if not runs_available:
    st.error("No runs found in `outputs/`. Run a simulation first.")
    st.stop()

mode = st.sidebar.radio("Run selection", [
    "Last run", "Last N runs", "Specific runs", "All runs"], 0)

if mode == "Last run":
    selected_runs = [runs_available[0]]
elif mode == "Last N runs":
    n = st.sidebar.slider("N", 1, min(20, len(runs_available)), 3)
    selected_runs = runs_available[:n]
elif mode == "Specific runs":
    selected_runs = st.sidebar.multiselect(
        "Select runs", runs_available, default=[runs_available[0]])
else:
    selected_runs = runs_available

if not selected_runs:
    st.warning("Pick at least one run.")
    st.stop()

st.sidebar.caption(f"{len(selected_runs)} run(s) selected")
st.sidebar.write("\n".join(f"• `{r}`" for r in selected_runs[:8]))
if len(selected_runs) > 8:
    st.sidebar.caption(f"...+{len(selected_runs)-8} more")

panel = load_panel(tuple(selected_runs))
if panel.empty:
    st.error("No data in selected runs.")
    st.stop()

# ── Top metrics ───────────────────────────────────────────────────────

st.title("📊 LLM Firm Lab — Results")
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Runs", panel["run_id"].nunique())
c2.metric("Firm-quarters", len(panel))
c3.metric("Distinct firms", panel["firm_id"].nunique())
if "default_flag" in panel.columns:
    c4.metric("Default events",
              int(panel.groupby(["run_id", "firm_id"])["default_flag"].max().sum()))
# BS identity sanity
if all(c in panel.columns for c in ("atq", "ltq", "ceqq")):
    resid = (panel["atq"] - panel["ltq"] - panel["ceqq"]).abs()
    c5.metric("Max |atq − ltq − ceqq|", f"${resid.max():,.0f}")

st.divider()

# ── Tabs ──────────────────────────────────────────────────────────────

tabs = st.tabs([
    "📈 Time series", "📊 Ratios", "💼 CEO", "🔁 Turnover",
    "🏦 Debt & covenants", "📝 Analysts & guidance", "⚖️ Data integrity",
    "🔥 EM heatmap", "🆚 Firm compare", "📊 Cross-run dist",
    "🕵️ Auditor timeline", "📜 Proposals", "🤝 Negotiations",
    "📐 Regressions", "🔗 Crosswalk", "💰 Cost",
])

# --- Time series
with tabs[0]:
    st.subheader("Firm time series")
    metric = st.selectbox(
        "Metric",
        ["saleq", "niq", "cheq", "atq", "ltq", "ceqq", "prccq",
         "oancfq", "ivncfq", "fincfq", "capxq", "xrdq", "xsgaq",
         "dlttq", "req"], 0,
        format_func=lambda s: {
            "saleq": "Revenue (quarterly)", "niq": "Net income",
            "cheq": "Cash", "atq": "Total assets", "ltq": "Total liabilities",
            "ceqq": "Common equity", "prccq": "Share price",
            "oancfq": "CFO", "ivncfq": "CFI", "fincfq": "CFF",
            "capxq": "Capex", "xrdq": "R&D", "xsgaq": "SG&A",
            "dlttq": "LT debt", "req": "Retained earnings",
        }.get(s, s))

    agg_mode = st.radio("Aggregation", [
        "Per firm", "Cross-firm mean", "Cross-firm median",
        "Cross-firm mean ± 1 std"], 0, horizontal=True)

    if metric not in panel.columns:
        st.info(f"Metric `{metric}` not in the panel.")
    else:
        if agg_mode == "Per firm":
            fig = px.line(
                panel.sort_values(["run_id", "firm_id", "abs_q"]),
                x="abs_q", y=metric, color="firm_id",
                line_group="run_id",
                hover_data=["run_id", "period"],
                markers=True,
            )
            fig.update_layout(xaxis_title="Absolute quarter",
                              yaxis_title=metric)
            st.plotly_chart(fig, width="stretch")
        else:
            g = panel.groupby("abs_q")[metric]
            if agg_mode == "Cross-firm mean":
                s = g.mean().reset_index()
                fig = px.line(s, x="abs_q", y=metric, markers=True,
                              title=f"{metric} — cross-firm mean")
            elif agg_mode == "Cross-firm median":
                s = g.median().reset_index()
                fig = px.line(s, x="abs_q", y=metric, markers=True,
                              title=f"{metric} — cross-firm median")
            else:
                s = g.agg(["mean", "std"]).reset_index()
                fig = go.Figure()
                fig.add_trace(go.Scatter(x=s["abs_q"], y=s["mean"],
                                          name="mean", mode="lines+markers"))
                fig.add_trace(go.Scatter(
                    x=list(s["abs_q"]) + list(s["abs_q"][::-1]),
                    y=list(s["mean"] + s["std"]) + list((s["mean"] - s["std"])[::-1]),
                    fill="toself", fillcolor="rgba(100,150,255,0.2)",
                    line=dict(color="rgba(0,0,0,0)"), name="±1σ"))
                fig.update_layout(title=f"{metric} — cross-firm mean ± 1σ",
                                   xaxis_title="Absolute quarter",
                                   yaxis_title=metric)
            st.plotly_chart(fig, width="stretch")

# --- Ratios
with tabs[1]:
    st.subheader("Financial ratios (derived)")
    r = panel.copy()
    # Avoid div-zero
    eps = 1e-9
    r["ROE"] = r["niq"] / (r["ceqq"].abs() + eps)
    r["ROA"] = r["niq"] / (r["atq"] + eps)
    r["leverage"] = (r["dlcq"].fillna(0) + r["dlttq"].fillna(0)) / (r["atq"] + eps)
    r["debt_to_equity"] = ((r["dlcq"].fillna(0) + r["dlttq"].fillna(0))
                            / (r["ceqq"].abs() + eps))
    r["net_margin"] = r["niq"] / (r["saleq"] + eps)
    r["asset_turnover"] = r["saleq"] / (r["atq"] + eps)
    if "lctq" in r.columns and "rectq" in r.columns:
        r["current_ratio"] = (r["cheq"] + r["rectq"].fillna(0)
                               + r["invtq"].fillna(0)) / (r["lctq"] + eps)

    ratio = st.selectbox("Ratio", [
        "ROE", "ROA", "leverage", "debt_to_equity",
        "net_margin", "asset_turnover", "current_ratio"], 0)

    # Winsorize at 1/99% for display (ratios blow up near 0 equity)
    q_lo, q_hi = r[ratio].quantile([0.01, 0.99])
    rr = r[(r[ratio] >= q_lo) & (r[ratio] <= q_hi)]

    agg = st.radio("View", ["Per firm", "Cross-firm box per quarter",
                             "Cross-firm mean / median"], 0, horizontal=True)
    if agg == "Per firm":
        fig = px.line(rr.sort_values(["run_id", "firm_id", "abs_q"]),
                      x="abs_q", y=ratio, color="firm_id",
                      line_group="run_id", markers=True)
    elif agg == "Cross-firm box per quarter":
        fig = px.box(rr, x="abs_q", y=ratio, points="outliers")
    else:
        g = rr.groupby("abs_q")[ratio].agg(["mean", "median"]).reset_index()
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=g["abs_q"], y=g["mean"], name="mean"))
        fig.add_trace(go.Scatter(x=g["abs_q"], y=g["median"], name="median"))
    fig.update_layout(title=ratio, xaxis_title="Absolute quarter")
    st.plotly_chart(fig, width="stretch")

# --- CEO comp
with tabs[2]:
    st.subheader("CEO compensation (ExecuComp)")
    exe = load_dataset(tuple(selected_runs), "execucomp.csv")
    outs = load_dataset(tuple(selected_runs), "execucomp_outstanding.csv")
    if exe.empty:
        st.info("No execucomp.csv in selected runs.")
    else:
        # Coerce numerics
        for col in ["salary", "bonus", "stock_awards_value",
                    "option_awards_value", "total_comp",
                    "shares_sold_this_year", "shares_owned_eoy"]:
            if col in exe.columns:
                exe[col] = pd.to_numeric(exe[col], errors="coerce")

        col_a, col_b = st.columns(2)
        with col_a:
            fig = px.bar(exe.sort_values("fyear"), x="fyear", y="total_comp",
                          color="firm_id", barmode="group",
                          title="Total CEO comp by firm × fyear")
            st.plotly_chart(fig, width="stretch")
        with col_b:
            comp_parts = (exe
                          .melt(id_vars=["firm_id", "fyear"],
                                value_vars=["salary", "bonus",
                                            "stock_awards_value",
                                            "option_awards_value"],
                                var_name="component", value_name="amount"))
            fig = px.bar(comp_parts, x="fyear", y="amount", color="component",
                          facet_col="firm_id",
                          title="Comp composition (stacked by firm)",
                          barmode="stack")
            fig.update_xaxes(matches=None)
            st.plotly_chart(fig, width="stretch")

        st.dataframe(exe.sort_values(["fyear", "firm_id"]),
                      width="stretch")

    if not outs.empty:
        st.subheader("Outstanding equity (year-end)")
        for col in ["unvested_rsu_shares", "unvested_option_shares",
                    "vested_rsu_held_shares", "vested_option_shares",
                    "intrinsic_value_vested_options"]:
            if col in outs.columns:
                outs[col] = pd.to_numeric(outs[col], errors="coerce")
        st.dataframe(outs.sort_values(["fyear", "firm_id"]),
                      width="stretch")

# --- Turnover / survival
with tabs[3]:
    st.subheader("CEO turnover")
    turn = load_dataset(tuple(selected_runs), "ceo_turnover.csv")
    if turn.empty:
        st.info("No ceo_turnover.csv in selected runs.")
    else:
        fig = px.histogram(turn, x="event_quarter", color="event_type",
                            nbins=20, title="CEO events by quarter")
        st.plotly_chart(fig, width="stretch")
        st.dataframe(turn.sort_values("event_quarter"),
                      width="stretch")

    st.subheader("Firm survival")
    if "default_flag" in panel.columns:
        # KM-style naive curve: fraction of firm-runs still active by abs_q
        by_q = panel.groupby("abs_q")["default_flag"].agg(
            ["sum", "count"]).reset_index()
        by_q["active_frac"] = 1 - by_q["sum"] / by_q["count"]
        fig = px.line(by_q, x="abs_q", y="active_frac", markers=True,
                       title="Fraction of firms active")
        fig.update_yaxes(range=[0, 1])
        st.plotly_chart(fig, width="stretch")

# --- Debt & covenants
with tabs[4]:
    st.subheader("Debt facilities")
    facs = load_dataset(tuple(selected_runs), "debt_facilities.csv")
    if facs.empty:
        st.info("No debt_facilities.csv.")
    else:
        if "facility_type" in facs.columns:
            fig = px.histogram(facs, x="facility_type",
                                title="Facilities by type")
            st.plotly_chart(fig, width="stretch")
        st.dataframe(facs, width="stretch")

    st.subheader("Covenant violations")
    vios = load_dataset(tuple(selected_runs), "covenant_violations.csv")
    if vios.empty:
        st.info("No covenant_violations.csv.")
    else:
        if "resolution" in vios.columns:
            fig = px.histogram(vios, x="resolution", color="covenant_type",
                                title="Violation resolutions")
            st.plotly_chart(fig, width="stretch")
        st.dataframe(vios, width="stretch")

# --- Analysts & guidance
with tabs[5]:
    st.subheader("Sell-side analyst forecasts")
    af = load_dataset(tuple(selected_runs), "analyst_forecasts.csv")
    if af.empty:
        st.info("No analyst_forecasts.csv.")
    else:
        for col in ["target_price", "eps_forecast", "actual_eps",
                    "forecast_error"]:
            if col in af.columns:
                af[col] = pd.to_numeric(af[col], errors="coerce")
        if "rating" in af.columns:
            fig = px.histogram(af, x="rating", color="analyst_id",
                                title="Analyst ratings distribution")
            st.plotly_chart(fig, width="stretch")
        if "forecast_error" in af.columns and af["forecast_error"].notna().any():
            fig = px.box(af.dropna(subset=["forecast_error"]),
                          x="analyst_id", y="forecast_error",
                          title="Forecast errors by analyst")
            st.plotly_chart(fig, width="stretch")
        st.dataframe(af, width="stretch")

    st.subheader("Management guidance")
    mg = load_dataset(tuple(selected_runs), "management_forecasts.csv")
    if not mg.empty:
        st.dataframe(mg, width="stretch")

# --- Data integrity
with tabs[6]:
    st.subheader("Balance sheet identity residuals")
    if all(c in panel.columns for c in ("atq", "ltq", "ceqq")):
        panel["bs_resid"] = panel["atq"] - panel["ltq"] - panel["ceqq"]
        n_violations = int((panel["bs_resid"].abs() > 1).sum())
        st.metric("Rows with |resid| > $1",
                  f"{n_violations} / {len(panel)}")
        fig = px.scatter(panel, x="abs_q", y="bs_resid",
                          color="firm_id", hover_data=["run_id", "period"],
                          title="BS identity residual over time")
        st.plotly_chart(fig, width="stretch")
        if n_violations:
            st.dataframe(panel[panel["bs_resid"].abs() > 1][
                ["run_id", "firm_id", "period", "atq", "ltq", "ceqq",
                 "bs_resid"]], width="stretch")

    st.subheader("Cash flow reconciliation")
    if all(c in panel.columns for c in
           ("chechq", "oancfq", "ivncfq", "fincfq")):
        panel["cfs_resid"] = panel["chechq"] - (
            panel["oancfq"].fillna(0) + panel["ivncfq"].fillna(0)
            + panel["fincfq"].fillna(0))
        n_cfs = int((panel["cfs_resid"].abs() > 10).sum())
        st.metric("Rows with |chechq − (cfo+cfi+cff)| > $10",
                  f"{n_cfs} / {len(panel)}")

    st.subheader("Earnings management vs reported")
    if "manipulation_amount" in panel.columns:
        # manipulation_amount is the HIDDEN truth; niq is REPORTED.
        fig = px.scatter(panel, x="niq", y="manipulation_amount",
                          color="firm_id",
                          title="Manipulation amount vs reported NI",
                          hover_data=["run_id", "period"])
        st.plotly_chart(fig, width="stretch")

# --- EM heatmap
with tabs[7]:
    st.subheader("Earnings management heatmap")
    if "manipulation_amount" not in panel.columns:
        st.info("No manipulation_amount in panel.")
    else:
        pm = panel.copy()
        pm["abs_manip_M"] = pm["manipulation_amount"].abs() / 1e6
        pivot = pm.pivot_table(index="firm_id", columns="period",
                                values="abs_manip_M", aggfunc="first",
                                fill_value=0)
        if not pivot.empty:
            fig = px.imshow(
                pivot.values, x=pivot.columns, y=pivot.index,
                labels=dict(x="Period", y="Firm", color="|manipulation| ($M)"),
                color_continuous_scale="Reds", aspect="auto",
                title="Absolute manipulation amount per firm × period")
            st.plotly_chart(fig, width="stretch")

    st.subheader("Restatement events overlay")
    rest = load_dataset(tuple(selected_runs), "restatements.csv")
    if rest.empty:
        st.caption("No restatements in selected runs.")
    else:
        st.dataframe(rest, width="stretch")

# --- Firm comparison overlay
with tabs[8]:
    st.subheader("Compare firms side-by-side")
    firm_ids = sorted(panel["firm_id"].unique())
    picks = st.multiselect("Firms to compare", firm_ids, default=firm_ids[:3])
    metric_c = st.selectbox(
        "Metric",
        ["saleq", "niq", "cheq", "ceqq", "prccq", "atq", "req",
         "xrdq", "xsgaq", "dlttq"], 0, key="compare_metric")
    if picks and metric_c in panel.columns:
        sub = panel[panel["firm_id"].isin(picks)].sort_values(
            ["run_id", "firm_id", "abs_q"])
        fig = px.line(sub, x="abs_q", y=metric_c, color="firm_id",
                       line_dash="run_id", markers=True,
                       title=f"{metric_c} — selected firms")
        st.plotly_chart(fig, width="stretch")

    # Normalize for cross-firm scale comparison
    st.subheader("Normalized (index = 100 at earliest quarter)")
    if picks and metric_c in panel.columns:
        sub = panel[panel["firm_id"].isin(picks)].copy()
        # Per (run, firm): divide by first observed value × 100
        def _idx(df):
            df = df.sort_values("abs_q")
            base = df[metric_c].iloc[0]
            if base and abs(base) > 1e-9:
                df["indexed"] = df[metric_c] / base * 100
            else:
                df["indexed"] = pd.NA
            return df
        try:
            sub = sub.groupby(["run_id", "firm_id"], group_keys=False).apply(_idx)
            fig = px.line(sub.dropna(subset=["indexed"]),
                           x="abs_q", y="indexed", color="firm_id",
                           line_dash="run_id", markers=True,
                           title=f"{metric_c} normalized to 100")
            st.plotly_chart(fig, width="stretch")
        except Exception as e:
            st.caption(f"(normalized view unavailable: {e})")

# --- Cross-run distribution
with tabs[9]:
    st.subheader("Cross-run outcome distributions")
    st.caption("Useful when N runs > 1: shows how an outcome varies across seeds / configs.")

    # Final-quarter metric per firm, distribution across runs
    last_q = panel.groupby(["run_id", "firm_id"])["abs_q"].transform("max")
    final = panel[panel["abs_q"] == last_q].copy()

    dist_metric = st.selectbox(
        "Final-period metric",
        ["niq", "saleq", "cheq", "ceqq", "req", "atq", "prccq"], 0,
        key="dist_metric")
    if dist_metric in final.columns and len(final) > 0:
        fig = px.histogram(final, x=dist_metric, color="firm_id",
                            barmode="overlay", nbins=30,
                            title=f"Distribution of final-period {dist_metric}")
        st.plotly_chart(fig, width="stretch")
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Mean", f"${final[dist_metric].mean():,.0f}")
        col2.metric("Median", f"${final[dist_metric].median():,.0f}")
        col3.metric("Std dev", f"${final[dist_metric].std():,.0f}")
        col4.metric("N", f"{len(final)}")

    st.subheader("Default rate across runs")
    if "default_flag" in panel.columns:
        by_run = (panel.groupby(["run_id", "firm_id"])["default_flag"]
                  .max().reset_index())
        rates = (by_run.groupby("run_id")["default_flag"].mean()
                 .reset_index().rename(columns={"default_flag": "default_rate"}))
        fig = px.bar(rates, x="run_id", y="default_rate",
                      title="Fraction of firms that defaulted, by run")
        fig.update_yaxes(range=[0, 1])
        st.plotly_chart(fig, width="stretch")

# --- Auditor timeline
with tabs[10]:
    st.subheader("Auditor opinions + fees over time")
    aud = load_dataset(tuple(selected_runs), "audit_analytics.csv")
    if aud.empty:
        st.info("No audit_analytics.csv.")
    else:
        # Column names vary slightly across schemas — pick what's there.
        opinion_col = ("audit_opinion" if "audit_opinion" in aud.columns
                        else "opinion")
        fee_col = "audit_fee" if "audit_fee" in aud.columns else "fee"
        for col in [fee_col, "going_concern_flag", "auditor_tenure_years"]:
            if col in aud.columns:
                aud[col] = pd.to_numeric(aud[col], errors="coerce")
        fig = px.scatter(
            aud, x="fyear", y="firm_id",
            color=opinion_col if opinion_col in aud.columns else None,
            size=fee_col if fee_col in aud.columns else None,
            symbol="auditor_id" if "auditor_id" in aud.columns else None,
            hover_data=[fee_col, "auditor_id", "going_concern_flag"]
                if fee_col in aud.columns else None,
            title="Audit opinions timeline (size = fee)")
        st.plotly_chart(fig, width="stretch")

        if fee_col in aud.columns:
            fig2 = px.box(aud, x="auditor_id", y=fee_col,
                           title="Audit fees by auditor",
                           points="all")
            st.plotly_chart(fig2, width="stretch")

        st.dataframe(aud.sort_values(["fyear", "firm_id"]), width="stretch")

    st.subheader("Auditor-client tenure heatmap")
    if not aud.empty and "auditor_tenure_years" in aud.columns:
        pivot_t = aud.pivot_table(index="firm_id", columns="fyear",
                                   values="auditor_tenure_years",
                                   aggfunc="first", fill_value=0)
        if not pivot_t.empty:
            fig = px.imshow(
                pivot_t.values, x=pivot_t.columns, y=pivot_t.index,
                labels=dict(x="Fiscal year", y="Firm", color="Tenure (yrs)"),
                color_continuous_scale="Blues", aspect="auto",
                title="Auditor tenure with each client")
            st.plotly_chart(fig, width="stretch")

# --- Proposals browser (Wave beta)
with tabs[11]:
    st.subheader("Structured-action proposals log")
    import json
    all_props = []
    for rid in selected_runs:
        p = OUTPUTS / rid / "proposals.jsonl"
        if p.exists():
            for line in p.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    try:
                        all_props.append(json.loads(line))
                    except Exception:
                        continue
    if not all_props:
        st.info("No proposals.jsonl data in selected runs.")
    else:
        df_p = pd.DataFrame(all_props)
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total proposals", len(df_p))
        if "partially_accepted" in df_p.columns:
            c2.metric("Partially accepted",
                       int(df_p["partially_accepted"].sum()))
        if "accepted" in df_p.columns:
            c3.metric("Fully accepted", int(df_p["accepted"].sum()))
        if "source" in df_p.columns:
            c4.metric("LLM sourced",
                       int((df_p["source"] == "llm").sum()))

        if "actor_id" in df_p.columns:
            # Prefer actor_class if present (Wave θ) — cleaner bucketing
            x_col = "actor_class" if "actor_class" in df_p.columns else "actor_id"
            fig = px.histogram(df_p, x=x_col, color="action_type",
                                title=f"Proposals by {x_col} × type")
            st.plotly_chart(fig, width="stretch")

        # Rejection reasons breakdown (Wave θ): clamp/rejection events
        # structured inside the `rejections[]` list on each proposal.
        st.subheader("Rejection / clamp reasons")
        reject_rows = []
        for p in all_props:
            rs = p.get("rejections", []) or []
            for r in rs:
                reject_rows.append({
                    "proposal_id": p.get("proposal_id", ""),
                    "actor_id": p.get("actor_id", ""),
                    "actor_class": p.get("actor_class", ""),
                    "action_type": p.get("action_type", ""),
                    "field": r.get("field", ""),
                    "kind": r.get("kind", ""),
                    "rule_id": r.get("rule_id", ""),
                    "reason": r.get("reason", ""),
                })
        if reject_rows:
            df_r = pd.DataFrame(reject_rows)
            rc1, rc2, rc3 = st.columns(3)
            rc1.metric("Total rejection events", len(df_r))
            rc2.metric("Unique fields clamped",
                        df_r["field"].nunique() if "field" in df_r.columns else 0)
            rc3.metric("Unique rules fired",
                        df_r["rule_id"].nunique() if "rule_id" in df_r.columns else 0)
            # Most common fields clamped
            fig_f = px.histogram(df_r, x="field", color="kind",
                                  title="Rejections by field × kind")
            st.plotly_chart(fig_f, width="stretch")
            with st.expander("Full rejection events table"):
                st.dataframe(df_r, width="stretch")
        else:
            st.info("No structured rejection/clamp events recorded for selected runs.")

        # Browse
        st.subheader("Browse proposals")
        filter_actor = st.multiselect(
            "Filter by actor",
            sorted(df_p["actor_id"].unique()) if "actor_id" in df_p.columns else [])
        filter_type = st.multiselect(
            "Filter by action type",
            sorted(df_p["action_type"].unique()) if "action_type" in df_p.columns else [])
        view = df_p
        if filter_actor:
            view = view[view["actor_id"].isin(filter_actor)]
        if filter_type:
            view = view[view["action_type"].isin(filter_type)]
        st.dataframe(view, width="stretch")

# --- Negotiations browser (Wave gamma)
with tabs[12]:
    st.subheader("Multi-round negotiations log")
    import json
    all_negs = []
    for rid in selected_runs:
        p = OUTPUTS / rid / "negotiations.jsonl"
        if p.exists():
            for line in p.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    try:
                        all_negs.append(json.loads(line))
                    except Exception:
                        continue
    if not all_negs:
        st.info("No negotiations.jsonl data in selected runs.")
    else:
        df_n = pd.DataFrame(all_negs)
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total negotiations", len(df_n))
        if "outcome" in df_n.columns:
            n_acc = int((df_n["outcome"] == "accepted").sum())
            n_walk = int((df_n["outcome"] == "walked_away").sum())
            acc_rate = n_acc / len(df_n) if len(df_n) > 0 else 0
            c2.metric("Accepted", n_acc)
            c3.metric("Walked away", n_walk)
            c4.metric("Acceptance rate", f"{acc_rate:.0%}")

        if "topic" in df_n.columns and "outcome" in df_n.columns:
            fig = px.histogram(df_n, x="topic", color="outcome",
                                title="Negotiations by topic × outcome",
                                barmode="group")
            st.plotly_chart(fig, width="stretch")

            # Per-topic acceptance rate
            st.subheader("Acceptance rate by topic")
            topic_stats = (df_n.assign(_acc=(df_n["outcome"] == "accepted").astype(int))
                              .groupby("topic")
                              .agg(n=("_acc", "size"),
                                   accepted=("_acc", "sum"),
                                   avg_rounds=("num_rounds", "mean")
                                   if "num_rounds" in df_n.columns
                                   else ("_acc", "size"))
                              .reset_index())
            topic_stats["acceptance_rate"] = topic_stats["accepted"] / topic_stats["n"]
            st.dataframe(topic_stats, width="stretch")

        st.subheader("Browse negotiations")
        st.dataframe(df_n, width="stretch")

# --- Regressions results (Wave eta)
with tabs[13]:
    st.subheader("Baseline regression results")
    reg_dir = OUTPUTS / "regressions"
    if not reg_dir.exists():
        st.info("No regression outputs yet. Run "
                 "`python scripts/baseline_regressions.py` to populate.")
    else:
        specs = sorted(reg_dir.glob("*.txt"))
        if not specs:
            st.info("No *.txt spec files found in outputs/regressions/")
        for spec_path in specs:
            with st.expander(f"📐 {spec_path.stem}", expanded=False):
                try:
                    content = spec_path.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    content = spec_path.read_text(encoding="latin-1")
                st.code(content, language="text")

# --- Crosswalk (Wave zeta)
with tabs[14]:
    st.subheader("Entity crosswalk")
    cw_frames = []
    for rid in selected_runs:
        p = OUTPUTS / rid / "crosswalk.csv"
        if p.exists():
            try:
                cw_frames.append(pd.read_csv(p))
            except Exception:
                continue
    if not cw_frames:
        st.info("No crosswalk.csv in selected runs.")
    else:
        cw = pd.concat(cw_frames, ignore_index=True)
        c1, c2, c3 = st.columns(3)
        c1.metric("Total entities", len(cw))
        c2.metric("Entity types", cw["entity_type"].nunique())
        c3.metric("Firms", (cw["entity_type"] == "firm").sum())
        if "entity_type" in cw.columns:
            fig = px.histogram(cw, x="entity_type",
                                title="Entities by type")
            st.plotly_chart(fig, width="stretch")
        st.dataframe(cw, width="stretch")

# --- Cost / token telemetry (Wave theta)
with tabs[15]:
    st.subheader("LLM cost & token usage per run")
    import json as _json
    for rid in selected_runs:
        summary_path = OUTPUTS / rid / "cost_summary.txt"
        calls_path = OUTPUTS / rid / "llm_calls.jsonl"
        if not summary_path.exists() and not calls_path.exists():
            continue
        with st.expander(f"💰 {rid}", expanded=True):
            if summary_path.exists():
                try:
                    content = summary_path.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    content = summary_path.read_text(encoding="latin-1")
                st.code(content, language="text")
            if calls_path.exists():
                calls = []
                for line in calls_path.read_text(encoding="utf-8").splitlines():
                    if line.strip():
                        try:
                            calls.append(_json.loads(line))
                        except Exception:
                            continue
                if calls:
                    df_c = pd.DataFrame(calls)
                    c1, c2 = st.columns(2)
                    with c1:
                        fig = px.bar(
                            df_c.groupby("model")["total_tokens"].sum().reset_index(),
                            x="model", y="total_tokens",
                            title="Total tokens by model")
                        fig.update_xaxes(tickangle=-30)
                        st.plotly_chart(fig, width="stretch")
                    with c2:
                        fig = px.bar(
                            df_c.groupby("model")["latency_ms"].mean().reset_index(),
                            x="model", y="latency_ms",
                            title="Mean latency by model (ms)")
                        fig.update_xaxes(tickangle=-30)
                        st.plotly_chart(fig, width="stretch")
    if not any((OUTPUTS / rid / "cost_summary.txt").exists()
               for rid in selected_runs):
        st.info("No cost_summary.txt files yet. New live runs will "
                "generate them automatically.")

st.sidebar.markdown("---")
st.sidebar.caption(
    "**Tip**: run `python -m streamlit run app/config_builder.py` "
    "to compose new runs."
)
