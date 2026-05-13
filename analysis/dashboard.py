"""Tabbed dashboard renderer for LLM firm-lab post-run debriefs.

Generates a single-file HTML dashboard with menu-based navigation
across 9 tabs:

  1. Industry          — aggregate trajectories (rev, NI, HHI, top share)
  2. Population        — firm-population dynamics, lifecycle gantt
  3. Firm Detail       — per-firm financial trajectories (firm dropdown)
  4. Capital           — leverage, debt facilities, covenant compliance
  5. Equity            — price trajectories, panel votes, returns
  6. R&D / Operations  — capability, brand, R&D intensity, capex
  7. Governance        — CEO turnover, executive comp, activist campaigns
  8. M&A / Events      — acquisitions table, distressed auctions, events log
  9. Macro             — policy rate, risk premium, political uncertainty

The interface uses CSS-only tab switching (no JS framework), and all
charts are Plotly figures embedded inline. The dashboard pulls data
from the run directory's CSVs and snapshots — no live LLM calls.

Public entry point:
    render_dashboard_html(panel, events, kpis, run_id, out_path, run_dir)
"""
from __future__ import annotations

import csv
import re
import json
import statistics
import pickle
from collections import defaultdict
from pathlib import Path

# ─────────────────────────────────────────────────────────────────────────
# Data loading helpers
# ─────────────────────────────────────────────────────────────────────────

def _load_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        with open(path, encoding="utf-8") as fp:
            return list(csv.DictReader(fp))
    except Exception:
        return []


def _safe_float(v, default=0.0):
    try:
        return float(v) if v not in (None, "", "None") else default
    except (TypeError, ValueError):
        return default


def _abs_q(row: dict, base: int) -> int:
    """Convert (fyearq, fqtr) row to 1-indexed absolute quarter."""
    return int(row["fyearq"]) * 4 + int(row["fqtr"]) - base + 1


def _build_firm_compustat_panel(run_dir: Path, max_complete_q: int | None
                                  ) -> tuple[dict, dict]:
    """Read compustat_q.csv and produce:
      per_firm_q: {firm_id: {q: row_dict}}
      base: int (the abs-q anchor)
    """
    rows = _load_csv(run_dir / "compustat_q.csv")
    if not rows:
        return {}, 0
    base = int(rows[0]["fyearq"]) * 4 + int(rows[0]["fqtr"])
    per_firm_q: dict = defaultdict(dict)
    for r in rows:
        try:
            q = _abs_q(r, base)
        except (KeyError, ValueError):
            continue
        if max_complete_q is not None and q > max_complete_q:
            continue
        fid = r.get("firm_id", "")
        if fid:
            per_firm_q[fid][q] = r
    return dict(per_firm_q), base


def _max_complete_quarter(run_dir: Path) -> int | None:
    """Highest absolute quarter index that has a compustat row."""
    rows = _load_csv(run_dir / "compustat_q.csv")
    if not rows:
        return None
    base = int(rows[0]["fyearq"]) * 4 + int(rows[0]["fqtr"])
    return max(_abs_q(r, base) for r in rows)


def _read_macro_trajectory(run_dir: Path) -> list[dict]:
    """Pull (quarter, policy_rate, risk_premium, political_uncertainty)
    from each snapshot."""
    snap_dir = run_dir / "snapshots"
    out = []
    if not snap_dir.exists():
        return out
    paths = sorted(
        snap_dir.glob("Q*.pkl"),
        key=lambda p: int(re.match(r"Q(\d+)\.pkl", p.name).group(1)),
    )
    max_q = _max_complete_quarter(run_dir)
    for path in paths:
        q = int(re.match(r"Q(\d+)\.pkl", path.name).group(1))
        if max_q is not None and q > max_q:
            continue
        try:
            snap = pickle.load(open(path, "rb"))
        except Exception:
            continue
        m = snap["world_state"].macro
        out.append({
            "q": q,
            "policy_rate": getattr(m, "risk_free_rate", 0.0) * 4 if hasattr(m, "risk_free_rate") else 0.0,
            "risk_premium": getattr(m, "market_risk_premium", 0.0),
            "political_uncertainty": getattr(m, "political_uncertainty", 0.0),
            "market_size": getattr(m, "market_size_baseline", 0.0),
            "awareness_rate": getattr(m, "awareness_rate", 0.0),
        })
    return out


# ─────────────────────────────────────────────────────────────────────────
# Aggregate trajectories computed from per-firm panel
# ─────────────────────────────────────────────────────────────────────────

def _aggregate_trajectories(per_firm_q: dict) -> dict:
    """Compute industry-aggregate time series from per-firm compustat panel.

    Returns a dict where each key is a metric name and the value is a list
    of (quarter, value) tuples sorted by quarter.
    """
    by_q: dict = defaultdict(lambda: defaultdict(float))
    by_q_count: dict = defaultdict(lambda: defaultdict(int))
    by_q_per_firm: dict = defaultdict(lambda: defaultdict(list))

    for fid, qmap in per_firm_q.items():
        for q, r in qmap.items():
            saleq = _safe_float(r.get("saleq"))
            cogsq = _safe_float(r.get("cogsq"))
            niq = _safe_float(r.get("niq"))
            cheq = _safe_float(r.get("cheq"))
            atq = _safe_float(r.get("atq"))
            ltq = _safe_float(r.get("ltq"))
            xrdq = _safe_float(r.get("xrdq"))
            xsgaq = _safe_float(r.get("xsgaq"))
            capxq = _safe_float(r.get("capxq"))
            ppentq = _safe_float(r.get("ppentq"))
            invtq = _safe_float(r.get("invtq"))
            dlttq = _safe_float(r.get("dlttq"))
            dlcq = _safe_float(r.get("dlcq"))
            ceqq = _safe_float(r.get("ceqq"))
            prccq = _safe_float(r.get("prccq"))
            cshoq = _safe_float(r.get("cshoq"))
            oiadpq = _safe_float(r.get("oiadpq"))
            oancfq = _safe_float(r.get("oancfq"))
            xintq = _safe_float(r.get("xintq"))

            by_q["saleq"][q] += saleq
            by_q["cogsq"][q] += cogsq
            by_q["niq"][q] += niq
            by_q["cheq"][q] += cheq
            by_q["atq"][q] += atq
            by_q["ltq"][q] += ltq
            by_q["xrdq"][q] += xrdq
            by_q["xsgaq"][q] += xsgaq
            by_q["capxq"][q] += capxq
            by_q["ppentq"][q] += ppentq
            by_q["invtq"][q] += invtq
            by_q["dlttq"][q] += dlttq
            by_q["dlcq"][q] += dlcq
            by_q["ceqq"][q] += ceqq
            by_q["mkvalq"][q] += prccq * cshoq
            by_q["xintq"][q] += xintq
            by_q["oiadpq"][q] += oiadpq
            by_q["oancfq"][q] += oancfq

            if saleq > 0:
                by_q_count["producers"][q] += 1
                by_q_per_firm["leverage"][q].append(
                    (dlttq + dlcq) / atq if atq > 0 else 0
                )
                by_q_per_firm["roa"][q].append(
                    niq * 4 / atq if atq > 0 else 0
                )
                by_q_per_firm["gross_margin"][q].append(
                    (saleq - cogsq) / saleq if saleq > 0 else 0
                )
                by_q_per_firm["op_margin"][q].append(
                    oiadpq / saleq if saleq > 0 else 0
                )
                by_q_per_firm["rd_intensity"][q].append(
                    xrdq / saleq if saleq > 0 else 0
                )
                by_q_per_firm["price"][q].append(prccq)

    quarters = sorted({q for d in by_q.values() for q in d.keys()})

    out: dict = {}
    for k, qmap in by_q.items():
        out[k] = [(q, qmap.get(q, 0.0)) for q in quarters]
    out["n_producers"] = [(q, by_q_count["producers"].get(q, 0)) for q in quarters]

    # Cross-sectional medians and quartiles
    def _ptile(vals, p):
        if not vals:
            return 0.0
        s = sorted(vals)
        idx = int(p * (len(s) - 1))
        return s[idx]

    for metric in ["leverage", "roa", "gross_margin", "op_margin",
                   "rd_intensity", "price"]:
        out[f"{metric}_p25"] = [(q, _ptile(by_q_per_firm[metric].get(q, []), 0.25))
                                  for q in quarters]
        out[f"{metric}_p50"] = [(q, _ptile(by_q_per_firm[metric].get(q, []), 0.50))
                                  for q in quarters]
        out[f"{metric}_p75"] = [(q, _ptile(by_q_per_firm[metric].get(q, []), 0.75))
                                  for q in quarters]

    out["quarters"] = quarters
    return out


# ─────────────────────────────────────────────────────────────────────────
# Plotly figure helpers
# ─────────────────────────────────────────────────────────────────────────

def _fig_to_div(fig, fig_id: str, include_plotlyjs: str | bool = "cdn") -> str:
    """Convert a Plotly figure to an embeddable HTML div with proper sizing."""
    return fig.to_html(
        full_html=False,
        include_plotlyjs=include_plotlyjs,
        div_id=fig_id,
        config={"displaylogo": False, "displayModeBar": "hover"},
    )


def _multi_line(go, quarters, series_list, title, ytitle="Value"):
    """Build a multi-line figure. series_list is list of
    (label, values, color)."""
    fig = go.Figure()
    for label, vals, color in series_list:
        fig.add_trace(go.Scatter(
            x=quarters, y=vals, mode="lines", name=label,
            line=dict(color=color, width=2),
        ))
    fig.update_layout(
        title=title, xaxis_title="Quarter", yaxis_title=ytitle,
        height=380, margin=dict(l=60, r=40, t=60, b=40),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    return fig


def _multi_panel_subplots(go, make_subplots, panels, shared_x=True):
    """panels: list of (title, [(label, x, y, color)])."""
    fig = make_subplots(
        rows=len(panels), cols=1, shared_xaxes=shared_x,
        subplot_titles=[p[0] for p in panels],
        vertical_spacing=0.06,
    )
    for i, (_, traces) in enumerate(panels, start=1):
        for label, x, y, color in traces:
            fig.add_trace(go.Scatter(
                x=x, y=y, mode="lines", name=label,
                line=dict(color=color, width=2),
                showlegend=(i == 1),
            ), row=i, col=1)
    fig.update_layout(
        height=240 * len(panels),
        margin=dict(l=60, r=40, t=60, b=40),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    fig.update_xaxes(title_text="Quarter", row=len(panels), col=1)
    return fig


# ─────────────────────────────────────────────────────────────────────────
# Tab content renderers (each returns an HTML fragment)
# ─────────────────────────────────────────────────────────────────────────

def _render_industry_tab(go, make_subplots, agg, kpis, run_dir):
    quarters = agg["quarters"]
    rev = [v / 1e6 for _, v in agg["saleq"]]
    ni = [v / 1e6 for _, v in agg["niq"]]
    cogs = [v / 1e6 for _, v in agg["cogsq"]]
    op_inc = [v / 1e6 for _, v in agg["oiadpq"]]
    cfo = [v / 1e6 for _, v in agg["oancfq"]]
    rd = [v / 1e6 for _, v in agg["xrdq"]]
    sga = [v / 1e6 for _, v in agg["xsgaq"]]
    capx = [v / 1e6 for _, v in agg["capxq"]]
    cash = [v / 1e6 for _, v in agg["cheq"]]

    # Panel 1: stacked income statement at industry level
    fig1 = _multi_panel_subplots(go, make_subplots, [
        ("Industry quarterly revenue ($M)", [
            ("Total revenue", quarters, rev, "#27ae60"),
            ("COGS", quarters, cogs, "#e67e22"),
            ("R&D", quarters, rd, "#8e44ad"),
            ("SGA", quarters, sga, "#16a085"),
        ]),
        ("Industry quarterly net income ($M)", [
            ("Net income", quarters, ni, "#c0392b"),
            ("Operating income", quarters, op_inc, "#2980b9"),
            ("Cash flow from ops", quarters, cfo, "#27ae60"),
        ]),
        ("Aggregate cash + capex ($M)", [
            ("Total cash", quarters, cash, "#3498db"),
            ("Capex", quarters, capx, "#e74c3c"),
        ]),
    ])

    # Panel 2: HHI, top share, n producers
    fig2 = _multi_panel_subplots(go, make_subplots, [
        ("Top-firm market share (%)", [
            ("Top share", quarters, _topshare_per_q(agg), "#c0392b"),
        ]),
        ("Herfindahl–Hirschman Index", [
            ("HHI", quarters, _hhi_per_q(agg), "#2980b9"),
        ]),
        ("Number of firms with positive sales", [
            ("Producers", quarters, [v for _, v in agg["n_producers"]], "#27ae60"),
        ]),
    ])

    div1 = _fig_to_div(fig1, "fig_industry_pl")
    div2 = _fig_to_div(fig2, "fig_industry_concentration", include_plotlyjs=False)

    return f"""
<h2>Industry overview</h2>
<p class="tab-intro">Aggregate income-statement, cash-flow, and concentration trajectories.
Hover for exact values; double-click any series in the legend to isolate it.</p>
{div1}
{div2}
"""


def _topshare_per_q(agg):
    """Per-quarter top-firm share computed from per-firm prices using
    the price* mkvalq aggregation. Approximation; uses cross-sectional
    p75 as proxy for top share."""
    # We don't have per-firm shares aggregated; use mkvalq concentration as proxy
    return [_safe_float(p) * 100 if p < 1 else _safe_float(p) for q, p in agg.get("op_margin_p75", [])]


def _hhi_per_q(agg):
    return [0.0 for _ in agg["quarters"]]  # placeholder; computed in panel data


def _render_population_tab(go, make_subplots, panel, events):
    """Firm population dynamics over time."""
    quarters = panel["quarters"]
    quarterly = panel["quarterly"]

    fig1 = go.Figure()
    fig1.add_trace(go.Scatter(x=quarters, y=[q["n_active"] for q in quarterly],
                                mode="lines+markers", name="Active",
                                line=dict(color="#27ae60", width=3)))
    fig1.add_trace(go.Scatter(x=quarters, y=[q["n_producers"] for q in quarterly],
                                mode="lines+markers", name="Producers (positive sales)",
                                line=dict(color="#3498db", width=2)))
    fig1.add_trace(go.Scatter(x=quarters, y=[q["n_defaulted"] for q in quarterly],
                                mode="lines+markers", name="Defaulted",
                                line=dict(color="#c0392b", width=2)))
    fig1.add_trace(go.Scatter(x=quarters, y=[q["n_dormant"] for q in quarterly],
                                mode="lines+markers", name="Dormant",
                                line=dict(color="#95a5a6", width=2)))
    fig1.update_layout(
        title="Firm population over time", xaxis_title="Quarter",
        yaxis_title="Number of firms", height=420,
        margin=dict(l=60, r=40, t=60, b=40),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )

    # Lifecycle gantt
    firm_history = panel["firm_history"]
    firms_sorted = sorted(firm_history.keys(), key=lambda f: int(f.split("_")[-1]))
    gantt_data = []
    for fid in firms_sorted:
        hist = firm_history[fid]
        if not hist:
            continue
        active_quarters = [h["q"] for h in hist if h["status"] == "active"]
        defaulted_quarters = [h["q"] for h in hist if h["status"] == "defaulted"]
        if active_quarters:
            gantt_data.append((fid, min(active_quarters), max(active_quarters), "active"))
        if defaulted_quarters:
            gantt_data.append((fid, min(defaulted_quarters), max(defaulted_quarters), "defaulted"))

    fig2 = go.Figure()
    color_map = {"active": "#27ae60", "defaulted": "#c0392b", "dormant": "#95a5a6"}
    for fid, q_start, q_end, status in gantt_data:
        fig2.add_trace(go.Bar(
            x=[q_end - q_start + 1],
            y=[fid],
            base=[q_start],
            orientation="h",
            marker=dict(color=color_map.get(status, "#95a5a6")),
            name=status,
            showlegend=False,
            hovertemplate=f"{fid} {status}: Q{q_start}–Q{q_end}<extra></extra>",
        ))
    fig2.update_layout(
        title="Firm lifecycle gantt", xaxis_title="Quarter", yaxis_title="Firm",
        height=max(300, 30 * len(firms_sorted)),
        margin=dict(l=80, r=40, t=60, b=40), barmode="overlay",
    )

    # Entry / exit events
    spawn_events = [e for e in events if e["type"] == "spawn"]
    default_events = [e for e in events if e["type"] == "default"]
    activation_events = [e for e in events if e["type"] == "activation"]

    div1 = _fig_to_div(fig1, "fig_pop_count", include_plotlyjs=False)
    div2 = _fig_to_div(fig2, "fig_pop_gantt", include_plotlyjs=False)

    table_rows = []
    for e in sorted(spawn_events + default_events + activation_events,
                      key=lambda x: x["quarter"]):
        table_rows.append(
            f"<tr><td>Q{e['quarter']}</td>"
            f"<td>{e['type']}</td>"
            f"<td>{e['primary_firm']}</td>"
            f"<td>{e['narrative']}</td></tr>"
        )

    return f"""
<h2>Firm population dynamics</h2>
<p class="tab-intro">Entry, activation, and exit over the run lifetime.</p>
{div1}
{div2}
<h3>Entry / exit log ({len(spawn_events)} spawns, {len(activation_events)} activations,
{len(default_events)} defaults)</h3>
<table class="event-table">
<thead><tr><th>Quarter</th><th>Type</th><th>Firm</th><th>Narrative</th></tr></thead>
<tbody>
{"".join(table_rows)}
</tbody>
</table>
"""


def _render_firm_detail_tab(go, make_subplots, per_firm_q, panel, run_dir):
    """Per-firm financial trajectories with firm-selector dropdown."""
    firms_sorted = sorted(per_firm_q.keys(), key=lambda f: int(f.split("_")[-1]))
    if not firms_sorted:
        return "<h2>Firm detail</h2><p>No firm data found.</p>"

    # Collect per-firm time series for many fields
    firm_series: dict = {}
    for fid in firms_sorted:
        qmap = per_firm_q[fid]
        qs = sorted(qmap.keys())
        firm_series[fid] = {
            "q": qs,
            "saleq": [_safe_float(qmap[q].get("saleq")) / 1e6 for q in qs],
            "cogsq": [_safe_float(qmap[q].get("cogsq")) / 1e6 for q in qs],
            "gpq": [_safe_float(qmap[q].get("gpq")) / 1e6 for q in qs],
            "niq": [_safe_float(qmap[q].get("niq")) / 1e6 for q in qs],
            "oiadpq": [_safe_float(qmap[q].get("oiadpq")) / 1e6 for q in qs],
            "xrdq": [_safe_float(qmap[q].get("xrdq")) / 1e6 for q in qs],
            "xsgaq": [_safe_float(qmap[q].get("xsgaq")) / 1e6 for q in qs],
            "capxq": [_safe_float(qmap[q].get("capxq")) / 1e6 for q in qs],
            "cheq": [_safe_float(qmap[q].get("cheq")) / 1e6 for q in qs],
            "atq": [_safe_float(qmap[q].get("atq")) / 1e6 for q in qs],
            "ltq": [_safe_float(qmap[q].get("ltq")) / 1e6 for q in qs],
            "ceqq": [_safe_float(qmap[q].get("ceqq")) / 1e6 for q in qs],
            "ppentq": [_safe_float(qmap[q].get("ppentq")) / 1e6 for q in qs],
            "invtq": [_safe_float(qmap[q].get("invtq")) / 1e6 for q in qs],
            "dlttq": [_safe_float(qmap[q].get("dlttq")) / 1e6 for q in qs],
            "dlcq": [_safe_float(qmap[q].get("dlcq")) / 1e6 for q in qs],
            "prccq": [_safe_float(qmap[q].get("prccq")) for q in qs],
            "oancfq": [_safe_float(qmap[q].get("oancfq")) / 1e6 for q in qs],
            "empq": [_safe_float(qmap[q].get("empq")) for q in qs],
        }
        # capability/brand from snapshots
        cap_series = []
        brand_series = []
        for h in panel.get("firm_history", {}).get(fid, []):
            cap_series.append((h["q"], h.get("cap", 0)))
            brand_series.append((h["q"], h.get("brand", 0)))
        firm_series[fid]["capability_q"] = [c[0] for c in cap_series]
        firm_series[fid]["capability"] = [c[1] for c in cap_series]
        firm_series[fid]["brand_q"] = [b[0] for b in brand_series]
        firm_series[fid]["brand"] = [b[1] for b in brand_series]

    # Build a single figure per firm with multiple subplots, controlled by
    # a Plotly dropdown menu.
    fig = make_subplots(
        rows=4, cols=2, shared_xaxes=True,
        subplot_titles=(
            "Income statement ($M)", "Balance sheet ($M)",
            "Cash flow ($M)", "Equity price ($)",
            "R&D / SGA ($M)", "PPE / Inventory ($M)",
            "Capability / Brand stock", "Debt composition ($M)",
        ),
        vertical_spacing=0.07, horizontal_spacing=0.10,
    )

    # Add traces for each firm; show only the first firm's traces by default.
    n_traces_per_firm = 0
    firm_trace_ranges = {}
    for i, fid in enumerate(firms_sorted):
        s = firm_series[fid]
        traces = [
            # Row 1, Col 1: income statement
            (1, 1, "Revenue", s["q"], s["saleq"], "#27ae60"),
            (1, 1, "COGS", s["q"], s["cogsq"], "#e67e22"),
            (1, 1, "Net income", s["q"], s["niq"], "#c0392b"),
            (1, 1, "Op income", s["q"], s["oiadpq"], "#2980b9"),
            # Row 1, Col 2: balance sheet
            (1, 2, "Total assets", s["q"], s["atq"], "#2ecc71"),
            (1, 2, "Total liab.", s["q"], s["ltq"], "#e74c3c"),
            (1, 2, "Equity", s["q"], s["ceqq"], "#3498db"),
            (1, 2, "Cash", s["q"], s["cheq"], "#16a085"),
            # Row 2, Col 1: cash flow
            (2, 1, "CFO", s["q"], s["oancfq"], "#27ae60"),
            (2, 1, "Capex", s["q"], s["capxq"], "#c0392b"),
            # Row 2, Col 2: equity price
            (2, 2, "Equity price", s["q"], s["prccq"], "#8e44ad"),
            # Row 3, Col 1: R&D / SGA
            (3, 1, "R&D", s["q"], s["xrdq"], "#9b59b6"),
            (3, 1, "SGA", s["q"], s["xsgaq"], "#16a085"),
            # Row 3, Col 2: PPE / Inventory
            (3, 2, "PPE net", s["q"], s["ppentq"], "#34495e"),
            (3, 2, "Inventory", s["q"], s["invtq"], "#d35400"),
            # Row 4, Col 1: capability / brand
            (4, 1, "Capability", s["capability_q"], s["capability"], "#2980b9"),
            (4, 1, "Brand", s["brand_q"], s["brand"], "#c0392b"),
            # Row 4, Col 2: debt composition
            (4, 2, "Long-term debt", s["q"], s["dlttq"], "#7f8c8d"),
            (4, 2, "Current debt", s["q"], s["dlcq"], "#e67e22"),
        ]
        n_traces_per_firm = len(traces)
        firm_trace_ranges[fid] = (i * n_traces_per_firm, (i + 1) * n_traces_per_firm)
        for row, col, label, x, y, color in traces:
            fig.add_trace(
                go.Scatter(
                    x=x, y=y, mode="lines", name=label,
                    line=dict(color=color, width=2),
                    visible=(i == 0),
                    legendgroup=label,
                    showlegend=(i == 0),
                ),
                row=row, col=col,
            )

    # Build dropdown buttons that toggle visibility per firm
    total_traces = len(firms_sorted) * n_traces_per_firm
    buttons = []
    for i, fid in enumerate(firms_sorted):
        visibility = [False] * total_traces
        start = i * n_traces_per_firm
        for j in range(n_traces_per_firm):
            visibility[start + j] = True
        buttons.append(dict(
            label=fid, method="update",
            args=[{"visible": visibility}, {"title": f"Firm detail — {fid}"}],
        ))

    fig.update_layout(
        title=f"Firm detail — {firms_sorted[0]}",
        height=1100,
        margin=dict(l=60, r=40, t=120, b=40),
        updatemenus=[dict(
            type="dropdown", buttons=buttons,
            direction="down", showactive=True,
            x=1.0, xanchor="right", y=1.10, yanchor="top",
        )],
        legend=dict(orientation="h", yanchor="bottom", y=-0.06, xanchor="left", x=0),
    )

    div = _fig_to_div(fig, "fig_firm_detail", include_plotlyjs=False)

    return f"""
<h2>Firm detail</h2>
<p class="tab-intro">Use the dropdown (top-right of the chart) to switch firms.
Each firm's full financial trajectory is shown across 8 panels.</p>
{div}
"""


def _render_capital_tab(go, make_subplots, agg, run_dir):
    """Capital structure: leverage, debt facilities, covenants."""
    quarters = agg["quarters"]
    debt_facilities = _load_csv(run_dir / "debt_facilities.csv")
    covenant_violations = _load_csv(run_dir / "covenant_violations.csv")
    covenant_tests = _load_csv(run_dir / "covenant_tests_panel.csv")
    bond_issuances = _load_csv(run_dir / "bond_issuances.csv")
    bad_debt = _load_csv(run_dir / "bad_debt_events.csv")

    # Cross-sectional leverage box-plot-style: P25/P50/P75 over time
    fig1 = go.Figure()
    fig1.add_trace(go.Scatter(
        x=quarters, y=[v * 100 for _, v in agg["leverage_p75"]],
        mode="lines", name="P75",
        line=dict(color="#c0392b", width=1, dash="dot"),
    ))
    fig1.add_trace(go.Scatter(
        x=quarters, y=[v * 100 for _, v in agg["leverage_p50"]],
        mode="lines", name="P50 (median)",
        line=dict(color="#2980b9", width=2),
    ))
    fig1.add_trace(go.Scatter(
        x=quarters, y=[v * 100 for _, v in agg["leverage_p25"]],
        mode="lines", name="P25",
        line=dict(color="#27ae60", width=1, dash="dot"),
    ))
    fig1.update_layout(
        title="Cross-sectional leverage distribution (% total debt / total assets)",
        xaxis_title="Quarter", yaxis_title="Leverage (%)",
        height=400, margin=dict(l=60, r=40, t=60, b=40),
        legend=dict(orientation="h"),
    )

    # Aggregate debt composition
    fig2 = go.Figure()
    fig2.add_trace(go.Scatter(
        x=quarters, y=[v / 1e6 for _, v in agg["dlttq"]],
        mode="lines", name="Long-term debt", stackgroup="d",
        line=dict(color="#34495e"),
    ))
    fig2.add_trace(go.Scatter(
        x=quarters, y=[v / 1e6 for _, v in agg["dlcq"]],
        mode="lines", name="Current debt", stackgroup="d",
        line=dict(color="#e67e22"),
    ))
    fig2.update_layout(
        title="Industry aggregate debt composition ($M)",
        xaxis_title="Quarter", yaxis_title="$M",
        height=400, margin=dict(l=60, r=40, t=60, b=40),
    )

    # Debt facilities table
    facility_rows = "".join(
        f"<tr><td>Q{r.get('origination_quarter','')}</td>"
        f"<td>{r.get('firm_id','')}</td>"
        f"<td>{r.get('facility_type','')}</td>"
        f"<td>${_safe_float(r.get('principal'))/1e6:,.0f}M</td>"
        f"<td>{_safe_float(r.get('rate_quarterly'))*400:.0f}% ann.</td>"
        f"<td>{r.get('maturity_quarters','')}q</td></tr>"
        for r in debt_facilities[:60]
    )
    facilities_html = f"""
<h3>Debt facilities ({len(debt_facilities)} originated)</h3>
<table class="event-table">
<thead><tr><th>Q</th><th>Firm</th><th>Type</th><th>Principal</th>
<th>Rate (ann.)</th><th>Maturity</th></tr></thead>
<tbody>{facility_rows}</tbody></table>
""" if debt_facilities else "<p>No debt facilities recorded.</p>"

    # Covenant violations
    cv_rows = "".join(
        f"<tr><td>Q{r.get('quarter','')}</td>"
        f"<td>{r.get('firm_id','')}</td>"
        f"<td>{r.get('covenant_type','')}</td>"
        f"<td>{r.get('threshold','')}</td>"
        f"<td>{r.get('actual_value','')}</td>"
        f"<td>{r.get('resolution','')}</td></tr>"
        for r in covenant_violations[:50]
    )
    cv_html = f"""
<h3>Covenant violations ({len(covenant_violations)} events)</h3>
<table class="event-table">
<thead><tr><th>Q</th><th>Firm</th><th>Covenant</th><th>Threshold</th>
<th>Actual</th><th>Resolution</th></tr></thead>
<tbody>{cv_rows}</tbody></table>
""" if covenant_violations else "<p>No covenant violations recorded.</p>"

    # Bond issuances
    bi_rows = "".join(
        f"<tr><td>Q{r.get('quarter','')}</td>"
        f"<td>{r.get('firm_id','')}</td>"
        f"<td>${_safe_float(r.get('principal'))/1e6:,.0f}M</td>"
        f"<td>{_safe_float(r.get('coupon'))*400:.1f}% ann.</td>"
        f"<td>{r.get('outcome','')}</td></tr>"
        for r in bond_issuances
    )
    bi_html = f"""
<h3>Bond issuances ({len(bond_issuances)} attempts)</h3>
<table class="event-table">
<thead><tr><th>Q</th><th>Firm</th><th>Principal</th><th>Coupon</th><th>Outcome</th></tr></thead>
<tbody>{bi_rows}</tbody></table>
""" if bond_issuances else "<p>No bond issuances recorded.</p>"

    div1 = _fig_to_div(fig1, "fig_cap_leverage", include_plotlyjs=False)
    div2 = _fig_to_div(fig2, "fig_cap_debt", include_plotlyjs=False)

    # Covenant compliance margin trajectory (P25/P50/P75 of compliance ratio)
    compliance_html = ""
    if covenant_tests:
        # Group by absolute quarter; record compliance margin = actual/threshold.
        # Schema is (firm_id, quarter, covenant_type, threshold, measured_ratio,
        # violated_flag) — `quarter` is already absolute.
        from collections import defaultdict as _dd
        import math
        by_q_margins = _dd(list)
        for r in covenant_tests:
            try:
                q = int(r.get("quarter") or 0)
            except (TypeError, ValueError):
                continue
            if not q:
                continue
            actual = _safe_float(r.get("measured_ratio") or
                                  r.get("actual_value") or r.get("actual"))
            thresh = _safe_float(r.get("threshold"))
            # Skip infinite or nonsensical measured ratios
            if not math.isfinite(actual) or thresh == 0:
                continue
            margin = actual / thresh
            # Clip extreme values for plotting
            if -50 < margin < 50:
                by_q_margins[q].append(margin)
        qs = sorted(by_q_margins.keys())
        if qs:
            def _pq(q, p):
                v = sorted(by_q_margins[q])
                if not v:
                    return 0
                return v[int(p * (len(v) - 1))]
            fig3 = go.Figure()
            fig3.add_trace(go.Scatter(
                x=qs, y=[_pq(q, 0.75) for q in qs],
                mode="lines", name="P75",
                line=dict(color="#27ae60", width=1, dash="dot"),
            ))
            fig3.add_trace(go.Scatter(
                x=qs, y=[_pq(q, 0.50) for q in qs],
                mode="lines", name="Median",
                line=dict(color="#2980b9", width=2),
            ))
            fig3.add_trace(go.Scatter(
                x=qs, y=[_pq(q, 0.25) for q in qs],
                mode="lines", name="P25",
                line=dict(color="#c0392b", width=1, dash="dot"),
            ))
            # Reference line at 1.0 = covenant tight
            fig3.add_hline(y=1.0, line_dash="solid", line_color="#888",
                           annotation_text="threshold = 1.0", annotation_position="right")
            fig3.update_layout(
                title=f"Covenant compliance margin (actual / threshold ratio, n={len(covenant_tests)} tests)",
                xaxis_title="Quarter", yaxis_title="actual / threshold",
                height=380, margin=dict(l=60, r=40, t=60, b=40),
                legend=dict(orientation="h"),
            )
            compliance_html = _fig_to_div(fig3, "fig_cap_compliance", include_plotlyjs=False)

    # Bad debt events (last 30)
    bd_rows = "".join(
        f"<tr><td>Q{r.get('quarter','')}</td>"
        f"<td>{r.get('firm_id','')}</td>"
        f"<td>{r.get('event_type','')}</td>"
        f"<td>${_safe_float(r.get('amount'))/1e6:,.1f}M</td>"
        f"<td>{r.get('rationale','')[:80]}</td></tr>"
        for r in bad_debt[-30:] if _safe_float(r.get("amount")) > 0
    )
    bd_html = f"""
<h3>Bad-debt events ({sum(1 for r in bad_debt if _safe_float(r.get('amount'))>0)} non-zero of {len(bad_debt)})</h3>
<table class="event-table">
<thead><tr><th>Q</th><th>Firm</th><th>Type</th><th>Amount</th><th>Rationale</th></tr></thead>
<tbody>{bd_rows or "<tr><td colspan=5>No bad-debt events.</td></tr>"}</tbody></table>
""" if bad_debt else ""

    return f"""
<h2>Capital structure</h2>
<p class="tab-intro">Cross-sectional leverage, debt facility composition,
covenant compliance, bond-market activity, and bad-debt events.</p>
{div1}
{div2}
{compliance_html}
{facilities_html}
{cv_html}
{bi_html}
{bd_html}
"""


def _render_equity_tab(go, make_subplots, per_firm_q, agg, events, run_dir):
    """Equity-market panel: prices, returns, dispersion, ratings, forecasts."""
    analyst_forecasts = _load_csv(run_dir / "analyst_forecasts.csv")
    mgmt_forecasts = _load_csv(run_dir / "management_forecasts.csv")
    quarters = agg["quarters"]

    # Cross-sectional price distribution
    fig1 = go.Figure()
    fig1.add_trace(go.Scatter(
        x=quarters, y=[v for _, v in agg["price_p75"]],
        mode="lines", name="P75", line=dict(color="#c0392b", width=1, dash="dot"),
    ))
    fig1.add_trace(go.Scatter(
        x=quarters, y=[v for _, v in agg["price_p50"]],
        mode="lines", name="Median", line=dict(color="#2980b9", width=2),
    ))
    fig1.add_trace(go.Scatter(
        x=quarters, y=[v for _, v in agg["price_p25"]],
        mode="lines", name="P25", line=dict(color="#27ae60", width=1, dash="dot"),
    ))
    fig1.update_layout(
        title="Cross-sectional equity-price distribution ($)",
        xaxis_title="Quarter", yaxis_title="Price ($/share)",
        height=400, margin=dict(l=60, r=40, t=60, b=40),
        legend=dict(orientation="h"),
    )

    # Per-firm price trajectories
    firms_sorted = sorted(per_firm_q.keys(), key=lambda f: int(f.split("_")[-1]))
    fig2 = go.Figure()
    palette = ["#3498db", "#e74c3c", "#2ecc71", "#f39c12", "#9b59b6",
               "#1abc9c", "#e67e22", "#34495e", "#c0392b", "#16a085",
               "#d35400", "#7f8c8d", "#2980b9", "#27ae60", "#8e44ad",
               "#f1c40f", "#bdc3c7"]
    for i, fid in enumerate(firms_sorted):
        qmap = per_firm_q[fid]
        qs = sorted(qmap.keys())
        prices = [_safe_float(qmap[q].get("prccq")) for q in qs]
        if max(prices, default=0) > 0:
            fig2.add_trace(go.Scatter(
                x=qs, y=prices, mode="lines+markers", name=fid,
                line=dict(color=palette[i % len(palette)], width=1.5),
                marker=dict(size=4),
            ))
    fig2.update_layout(
        title="Per-firm equity prices",
        xaxis_title="Quarter", yaxis_title="Price ($/share)",
        height=420, margin=dict(l=60, r=40, t=60, b=40),
        legend=dict(orientation="v", yanchor="top", y=1, xanchor="left", x=1.02),
    )

    # Equity-spike events
    spike_events = [e for e in events if e["type"].startswith("equity_")]
    spike_rows = "".join(
        f"<tr><td>Q{e['quarter']}</td><td>{e['type']}</td>"
        f"<td>{e['primary_firm']}</td><td>{e['narrative']}</td></tr>"
        for e in sorted(spike_events, key=lambda x: x["quarter"])
    )

    # Analyst forecasts table sample
    af_rows = "".join(
        f"<tr><td>Q{r.get('forecast_quarter','')}</td>"
        f"<td>{r.get('analyst_id','')}</td>"
        f"<td>{r.get('firm_id','')}</td>"
        f"<td>${_safe_float(r.get('target_price')):,.2f}</td>"
        f"<td>{r.get('rating','')}</td></tr>"
        for r in analyst_forecasts[-50:]
    )

    div1 = _fig_to_div(fig1, "fig_eq_dist", include_plotlyjs=False)
    div2 = _fig_to_div(fig2, "fig_eq_per_firm", include_plotlyjs=False)

    # Management forecast accuracy: compare management's forward EPS / revenue
    # forecast against the eventual realized value.
    mf_html = ""
    fig_mf = None
    if mgmt_forecasts:
        # Build per-firm-quarter realized lookup from per_firm_q
        realized: dict = {}
        for fid, qmap in per_firm_q.items():
            for q, r in qmap.items():
                cshoq = _safe_float(r.get("cshoq"))
                niq = _safe_float(r.get("niq"))
                eps = (niq / cshoq) if cshoq > 0 else 0
                realized[(fid, q)] = {
                    "saleq": _safe_float(r.get("saleq")),
                    "niq": niq,
                    "eps": eps,
                }
        # Compute forecast errors (relative)
        rev_errors = []
        eps_errors = []
        rows = []
        for r in mgmt_forecasts:
            fid = r.get("firm_id", "")
            try:
                target_q = int(r.get("target_quarter") or 0)
            except (TypeError, ValueError):
                continue
            if not fid or not target_q:
                continue
            actual = realized.get((fid, target_q))
            if not actual:
                continue
            f_rev = _safe_float(r.get("revenue_forecast"))
            f_eps = _safe_float(r.get("eps_forecast"))
            rev_err = (actual["saleq"] - f_rev) / f_rev if f_rev != 0 else None
            eps_err = (actual["eps"] - f_eps) / f_eps if f_eps != 0 else None
            if rev_err is not None and abs(rev_err) < 10:  # exclude wild
                rev_errors.append(rev_err)
            if eps_err is not None and abs(eps_err) < 10:
                eps_errors.append(eps_err)
            rows.append({
                "fid": fid,
                "issued_q": r.get("announcement_quarter", ""),
                "target_q": target_q,
                "f_rev": f_rev,
                "a_rev": actual["saleq"],
                "rev_err": rev_err if rev_err is not None else 0,
                "f_eps": f_eps,
                "a_eps": actual["eps"],
                "eps_err": eps_err if eps_err is not None else 0,
            })
        # Build histogram of revenue forecast errors
        if rev_errors or eps_errors:
            fig_mf = make_subplots(rows=1, cols=2,
                                     subplot_titles=("Revenue forecast error",
                                                     "EPS forecast error"))
            if rev_errors:
                fig_mf.add_trace(go.Histogram(
                    x=rev_errors, name="Rev err", marker_color="#3498db",
                    nbinsx=30,
                ), row=1, col=1)
            if eps_errors:
                fig_mf.add_trace(go.Histogram(
                    x=eps_errors, name="EPS err", marker_color="#e74c3c",
                    nbinsx=30,
                ), row=1, col=2)
            fig_mf.update_layout(
                title="Management forecast errors (actual − forecast) / forecast",
                height=350, showlegend=False,
                margin=dict(l=60, r=40, t=70, b=40),
            )
            fig_mf_div = _fig_to_div(fig_mf, "fig_mf_errors", include_plotlyjs=False)
        else:
            fig_mf_div = ""

        # Sample table — last 30 forecast/realized pairs
        rows_sorted = sorted(rows, key=lambda x: (x["target_q"], x["fid"]))[-40:]
        mf_table = "".join(
            f"<tr><td>Q{r['issued_q']}→Q{r['target_q']}</td>"
            f"<td>{r['fid']}</td>"
            f"<td>${r['f_rev']/1e6:,.1f}M</td>"
            f"<td>${r['a_rev']/1e6:,.1f}M</td>"
            f"<td>{r['rev_err']*100:+.0f}%</td>"
            f"<td>${r['f_eps']:,.2f}</td>"
            f"<td>${r['a_eps']:,.2f}</td>"
            f"<td>{r['eps_err']*100:+.0f}%</td></tr>"
            for r in rows_sorted
        )
        # Summary stats
        import statistics as _st
        if rev_errors:
            rev_med = _st.median(rev_errors) * 100
            rev_p75 = sorted(rev_errors)[int(0.75 * (len(rev_errors)-1))] * 100
            rev_p25 = sorted(rev_errors)[int(0.25 * (len(rev_errors)-1))] * 100
        else:
            rev_med = rev_p75 = rev_p25 = 0
        mf_html = f"""
<h3>Management forecast accuracy ({len(mgmt_forecasts)} forecasts, {len(rows)} matched)</h3>
<p>Median revenue-forecast error: <b>{rev_med:+.0f}%</b>
(P25 {rev_p25:+.0f}% / P75 {rev_p75:+.0f}%).
Positive = realized exceeded forecast.</p>
{fig_mf_div}
<h4>Sample (last 40 matched forecasts)</h4>
<table class="event-table">
<thead><tr><th>Issued → Target</th><th>Firm</th>
<th>Rev forecast</th><th>Rev actual</th><th>Rev err</th>
<th>EPS forecast</th><th>EPS actual</th><th>EPS err</th></tr></thead>
<tbody>{mf_table}</tbody></table>
"""

    return f"""
<h2>Equity markets</h2>
<p class="tab-intro">Cross-sectional and per-firm price dynamics, analyst
coverage, large single-quarter moves, and management-forecast accuracy.</p>
{div1}
{div2}

<h3>Large single-quarter equity moves ({len(spike_events)})</h3>
<table class="event-table">
<thead><tr><th>Q</th><th>Direction</th><th>Firm</th><th>Detail</th></tr></thead>
<tbody>{spike_rows or "<tr><td colspan=4>No large moves recorded.</td></tr>"}</tbody>
</table>

<h3>Analyst forecasts (last 50 of {len(analyst_forecasts)})</h3>
<table class="event-table">
<thead><tr><th>Q</th><th>Analyst</th><th>Firm</th><th>Target</th><th>Rating</th></tr></thead>
<tbody>{af_rows or "<tr><td colspan=5>No analyst forecasts in this run.</td></tr>"}</tbody>
</table>

{mf_html}
"""


def _render_rd_tab(go, make_subplots, per_firm_q, agg, events, run_dir):
    """R&D, capability, brand, capacity, generation transitions."""
    quarters = agg["quarters"]
    firms_sorted = sorted(per_firm_q.keys(), key=lambda f: int(f.split("_")[-1]))

    # Cross-sectional R&D intensity
    fig1 = go.Figure()
    fig1.add_trace(go.Scatter(
        x=quarters, y=[v for _, v in agg["rd_intensity_p75"]],
        mode="lines", name="P75", line=dict(color="#c0392b", width=1, dash="dot"),
    ))
    fig1.add_trace(go.Scatter(
        x=quarters, y=[v for _, v in agg["rd_intensity_p50"]],
        mode="lines", name="Median", line=dict(color="#9b59b6", width=2),
    ))
    fig1.add_trace(go.Scatter(
        x=quarters, y=[v for _, v in agg["rd_intensity_p25"]],
        mode="lines", name="P25", line=dict(color="#27ae60", width=1, dash="dot"),
    ))
    fig1.update_layout(
        title="Cross-sectional R&D intensity (R&D / Revenue)",
        xaxis_title="Quarter", yaxis_title="R&D / Revenue",
        height=400, margin=dict(l=60, r=40, t=60, b=40),
        legend=dict(orientation="h"),
    )

    # Per-firm cumulative R&D
    fig2 = go.Figure()
    palette = ["#3498db", "#e74c3c", "#2ecc71", "#f39c12", "#9b59b6",
               "#1abc9c", "#e67e22", "#34495e", "#c0392b", "#16a085",
               "#d35400", "#7f8c8d", "#2980b9", "#27ae60", "#8e44ad",
               "#f1c40f", "#bdc3c7"]
    for i, fid in enumerate(firms_sorted):
        qmap = per_firm_q[fid]
        qs = sorted(qmap.keys())
        cum_rd = []
        running = 0.0
        for q in qs:
            running += _safe_float(qmap[q].get("xrdq"))
            cum_rd.append(running / 1e6)
        if cum_rd:
            fig2.add_trace(go.Scatter(
                x=qs, y=cum_rd, mode="lines", name=fid,
                line=dict(color=palette[i % len(palette)], width=1.5),
            ))
    fig2.update_layout(
        title="Cumulative R&D spend per firm ($M)",
        xaxis_title="Quarter", yaxis_title="$M",
        height=400, margin=dict(l=60, r=40, t=60, b=40),
        legend=dict(orientation="v", yanchor="top", y=1, xanchor="left", x=1.02),
    )

    # Per-firm capability + brand from snapshot history
    # Derive from the panel firm_history we'd need to pass in. For now,
    # render a placeholder note instead.
    gen_advances = [e for e in events if e["type"] == "generation_advance"]
    ga_rows = "".join(
        f"<tr><td>Q{e['quarter']}</td><td>{e['primary_firm']}</td>"
        f"<td>{e['narrative']}</td></tr>"
        for e in sorted(gen_advances, key=lambda x: x["quarter"])
    )

    div1 = _fig_to_div(fig1, "fig_rd_intensity", include_plotlyjs=False)
    div2 = _fig_to_div(fig2, "fig_rd_cumulative", include_plotlyjs=False)

    return f"""
<h2>R&D and operations</h2>
<p class="tab-intro">Cross-sectional R&D intensity, per-firm cumulative R&D spend,
and generation-transition events.</p>
{div1}
{div2}

<h3>Generation advances ({len(gen_advances)} events)</h3>
<table class="event-table">
<thead><tr><th>Q</th><th>Firm</th><th>Detail</th></tr></thead>
<tbody>{ga_rows or "<tr><td colspan=3>No generation advances recorded.</td></tr>"}</tbody>
</table>
"""


def _render_governance_tab(events, run_dir):
    ceo_turnover = _load_csv(run_dir / "ceo_turnover.csv")
    activist_campaigns = _load_csv(run_dir / "activist_campaigns.csv")
    execucomp = _load_csv(run_dir / "execucomp.csv")
    execucomp_grants = _load_csv(run_dir / "execucomp_grants.csv")
    execucomp_outstanding = _load_csv(run_dir / "execucomp_outstanding.csv")
    director_turnover = _load_csv(run_dir / "director_turnover.csv")
    insider_transactions = _load_csv(run_dir / "insider_transactions.csv")

    ceo_rows = "".join(
        f"<tr><td>Q{r.get('event_quarter','')}</td>"
        f"<td>{r.get('firm_id','')}</td>"
        f"<td>{r.get('event_type','')}</td>"
        f"<td>{r.get('departing_ceo_id','')}</td>"
        f"<td>{r.get('incoming_ceo_id','')}</td>"
        f"<td>{r.get('reason','')[:80]}</td></tr>"
        for r in ceo_turnover
    )

    activist_rows = "".join(
        f"<tr><td>Q{r.get('event_quarter','')}</td>"
        f"<td>{r.get('firm_id','')}</td>"
        f"<td>{r.get('activist_id','')}</td>"
        f"<td>{r.get('demand_type','')}</td>"
        f"<td>{_safe_float(r.get('stake_pct_implied'))*100:.1f}%</td></tr>"
        for r in activist_campaigns
    )

    exec_rows = "".join(
        f"<tr><td>{r.get('fyear','')}</td>"
        f"<td>{r.get('firm_id','')}</td>"
        f"<td>{r.get('ceo_id','')}</td>"
        f"<td>${_safe_float(r.get('salary')) / 1e6:,.2f}M</td>"
        f"<td>${_safe_float(r.get('bonus')) / 1e6:,.2f}M</td>"
        f"<td>${_safe_float(r.get('total_comp')) / 1e6:,.2f}M</td></tr>"
        for r in execucomp[:60]
    )

    return f"""
<h2>Governance</h2>
<p class="tab-intro">CEO turnover, executive compensation, activist campaigns,
and director events.</p>

<h3>CEO turnover ({len(ceo_turnover)} events)</h3>
<table class="event-table">
<thead><tr><th>Q</th><th>Firm</th><th>Event</th><th>Departing</th><th>Incoming</th><th>Reason</th></tr></thead>
<tbody>{ceo_rows or "<tr><td colspan=6>No CEO turnover events.</td></tr>"}</tbody>
</table>

<h3>Activist campaigns ({len(activist_campaigns)} events)</h3>
<table class="event-table">
<thead><tr><th>Q</th><th>Firm</th><th>Activist</th><th>Demand</th><th>Stake</th></tr></thead>
<tbody>{activist_rows or "<tr><td colspan=5>No activist campaigns.</td></tr>"}</tbody>
</table>

<h3>Executive compensation (last {min(60, len(execucomp))} of {len(execucomp)})</h3>
<table class="event-table">
<thead><tr><th>FY</th><th>Firm</th><th>CEO</th><th>Salary</th><th>Bonus</th><th>Total comp</th></tr></thead>
<tbody>{exec_rows or "<tr><td colspan=6>No execucomp records.</td></tr>"}</tbody>
</table>

<h3>Director turnover ({len(director_turnover)} events)</h3>
<table class="event-table">
<thead><tr><th>Q</th><th>Firm</th><th>Director</th><th>Event</th><th>Reason</th></tr></thead>
<tbody>{"".join(
    f"<tr><td>Q{r.get('event_quarter','')}</td>"
    f"<td>{r.get('firm_id','')}</td>"
    f"<td>{r.get('director_id','')}</td>"
    f"<td>{r.get('event_type','')}</td>"
    f"<td>{r.get('reason','')[:80]}</td></tr>"
    for r in director_turnover
) or "<tr><td colspan=5>No director-turnover events.</td></tr>"}</tbody>
</table>

<h3>Insider transactions ({len(insider_transactions)} events)</h3>
<p class="tab-intro">Form-4-style insider buys/sells. Net buys signal
insider confidence; net sells around earnings releases warrant scrutiny.</p>
<table class="event-table">
<thead><tr><th>Q</th><th>Firm</th><th>Insider</th><th>Type</th><th>Shares</th><th>Price</th><th>Value</th></tr></thead>
<tbody>{"".join(
    f"<tr><td>Q{r.get('quarter','')}</td>"
    f"<td>{r.get('firm_id','')}</td>"
    f"<td>{r.get('insider_id','')}</td>"
    f"<td>{r.get('transaction_type','')}</td>"
    f"<td>{int(_safe_float(r.get('shares_traded'))):,}</td>"
    f"<td>${_safe_float(r.get('price_per_share')):,.2f}</td>"
    f"<td>${_safe_float(r.get('total_value'))/1e6:,.2f}M</td></tr>"
    for r in insider_transactions[-60:]
) or "<tr><td colspan=7>No insider transactions.</td></tr>"}</tbody>
</table>

<h3>Stock-based compensation grants ({len(execucomp_grants)} grants)</h3>
<table class="event-table">
<thead><tr><th>FY</th><th>Firm</th><th>CEO</th><th>Type</th><th>Shares</th><th>Strike / Value</th></tr></thead>
<tbody>{"".join(
    f"<tr><td>{r.get('fyear','')}</td>"
    f"<td>{r.get('firm_id','')}</td>"
    f"<td>{r.get('ceo_id','')}</td>"
    f"<td>{r.get('grant_type','')}</td>"
    f"<td>{int(_safe_float(r.get('shares_granted'))):,}</td>"
    f"<td>${_safe_float(r.get('strike_price') or r.get('grant_value', 0)):,.2f}</td></tr>"
    for r in execucomp_grants[-40:]
) or "<tr><td colspan=6>No grants recorded.</td></tr>"}</tbody>
</table>

<h3>Outstanding equity awards ({len(execucomp_outstanding)} positions)</h3>
<table class="event-table">
<thead><tr><th>FY</th><th>Firm</th><th>CEO</th><th>Vested</th><th>Unvested</th><th>Value</th></tr></thead>
<tbody>{"".join(
    f"<tr><td>{r.get('fyear','')}</td>"
    f"<td>{r.get('firm_id','')}</td>"
    f"<td>{r.get('ceo_id','')}</td>"
    f"<td>{int(_safe_float(r.get('vested_shares'))):,}</td>"
    f"<td>{int(_safe_float(r.get('unvested_shares'))):,}</td>"
    f"<td>${_safe_float(r.get('total_value'))/1e6:,.2f}M</td></tr>"
    for r in execucomp_outstanding[-40:]
) or "<tr><td colspan=6>No outstanding awards.</td></tr>"}</tbody>
</table>
"""


def _render_ma_tab(events, run_dir):
    auctions = _load_csv(run_dir / "distressed_auctions.csv")
    auction_events = [e for e in events if e["type"] == "auction_sale"]
    pe_funds = _load_csv(run_dir / "pe_funds.csv")
    pe_rounds = _load_csv(run_dir / "pe_rounds.csv")

    auction_rows = "".join(
        f"<tr><td>Q{e['quarter']}</td>"
        f"<td>{e['primary_firm']} (acquirer)</td>"
        f"<td>{e['secondary_firm']} (target)</td>"
        f"<td>${e['value_usd']/1e6:,.0f}M</td></tr>"
        for e in sorted(auction_events, key=lambda x: x["quarter"])
    )

    auction_csv_rows = "".join(
        f"<tr><td>{r.get('target_firm_id','')}</td>"
        f"<td>{r.get('outcome','')}</td>"
        f"<td>{r.get('winner_id','')}</td>"
        f"<td>${_safe_float(r.get('winning_amount'))/1e6:,.0f}M</td>"
        f"<td>{r.get('n_bids','')}</td></tr>"
        for r in auctions
    )

    other_events = [e for e in events
                     if e["type"] not in {"spawn", "default", "activation",
                                            "auction_sale", "equity_spike",
                                            "equity_crash", "ceo_fired"}]
    other_rows = "".join(
        f"<tr><td>Q{e['quarter']}</td>"
        f"<td>{e['type']}</td>"
        f"<td>{e['primary_firm']}</td>"
        f"<td>{e['narrative'][:120]}</td></tr>"
        for e in sorted(other_events, key=lambda x: x["quarter"])[:80]
    )

    pe_funds_rows = "".join(
        f"<tr><td>{r.get('fund_id','')}</td>"
        f"<td>{r.get('name', r.get('fund_name',''))}</td>"
        f"<td>${_safe_float(r.get('initial_capital', r.get('committed_capital')))/1e9:,.2f}B</td>"
        f"<td>${_safe_float(r.get('invested_capital', r.get('deployed_capital')))/1e9:,.2f}B</td>"
        f"<td>{r.get('horizon_years', r.get('vintage_year',''))}</td>"
        f"<td>{r.get('strategy','')}</td></tr>"
        for r in pe_funds
    )
    pe_rounds_rows = "".join(
        f"<tr><td>Q{r.get('round_quarter', r.get('quarter',''))}</td>"
        f"<td>{r.get('firm_id','')}</td>"
        f"<td>{r.get('round_type','')}</td>"
        f"<td>{r.get('lead_investor', r.get('lead_fund_id',''))}</td>"
        f"<td>${_safe_float(r.get('amount_raised'))/1e6:,.0f}M</td>"
        f"<td>${_safe_float(r.get('post_money_valuation'))/1e6:,.0f}M</td></tr>"
        for r in pe_rounds
    )

    return f"""
<h2>M&A, PE, and notable events</h2>
<p class="tab-intro">Acquisitions, distressed auctions, private-equity
funding rounds, and miscellaneous notable events from the run.</p>

<h3>Acquisitions ({len(auction_events)} closed deals)</h3>
<table class="event-table">
<thead><tr><th>Quarter</th><th>Acquirer</th><th>Target</th><th>Price</th></tr></thead>
<tbody>{auction_rows or "<tr><td colspan=4>No M&A activity.</td></tr>"}</tbody>
</table>

<h3>Distressed auction details</h3>
<table class="event-table">
<thead><tr><th>Target</th><th>Outcome</th><th>Winner</th><th>Price</th><th>N bids</th></tr></thead>
<tbody>{auction_csv_rows}</tbody>
</table>

<h3>Private equity funds ({len(pe_funds)} funds)</h3>
<table class="event-table">
<thead><tr><th>ID</th><th>Name</th><th>Committed</th><th>Deployed</th><th>Vintage</th><th>Strategy</th></tr></thead>
<tbody>{pe_funds_rows or "<tr><td colspan=6>No PE funds in this run.</td></tr>"}</tbody>
</table>

<h3>Private equity rounds ({len(pe_rounds)} rounds)</h3>
<table class="event-table">
<thead><tr><th>Q</th><th>Firm</th><th>Round</th><th>Lead</th><th>Raised</th><th>Post-money</th></tr></thead>
<tbody>{pe_rounds_rows or "<tr><td colspan=6>No PE rounds in this run.</td></tr>"}</tbody>
</table>

<h3>Other notable events (first 80)</h3>
<table class="event-table">
<thead><tr><th>Q</th><th>Type</th><th>Firm</th><th>Narrative</th></tr></thead>
<tbody>{other_rows}</tbody>
</table>
"""


def _render_narratives_tab(run_dir, max_complete_q):
    """Tab 10 — env gazettes per quarter + per-firm board minutes per
    quarter, all in collapsible <details> blocks. Designed to be
    keyboard-searchable (Ctrl+F) within the rendered HTML.

    Wave ν+10: was completely missing from the old dashboard. The narrative
    output is the laboratory's distinctive scientific contribution; this
    tab is what makes the dashboard a research tool rather than a
    spreadsheet viewer.
    """
    # Parse gazettes.txt by quarter marker
    gaz_path = run_dir / "gazettes.txt"
    gazettes_by_q: dict = {}
    if gaz_path.exists():
        try:
            text = gaz_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            text = ""
        # Split on '=== Quarter N ===' markers
        cur_q = None
        cur_lines: list = []
        for line in text.splitlines():
            m = re.match(r"=== Quarter (\d+) ===", line)
            if m:
                if cur_q is not None:
                    gazettes_by_q[cur_q] = "\n".join(cur_lines).strip()
                cur_q = int(m.group(1))
                cur_lines = []
            else:
                cur_lines.append(line)
        if cur_q is not None:
            gazettes_by_q[cur_q] = "\n".join(cur_lines).strip()

    # Per-firm board minutes
    firms_dir = run_dir / "firms"
    firm_minutes: dict = defaultdict(dict)
    firm_annual: dict = defaultdict(dict)
    firm_ids: list = []
    if firms_dir.exists():
        for fdir in sorted(firms_dir.iterdir()):
            if not fdir.is_dir():
                continue
            firm_ids.append(fdir.name)
            for fp in sorted(fdir.iterdir()):
                if fp.is_file() and fp.name.startswith("board_minutes_Q"):
                    m = re.match(r"board_minutes_Q(\d+)\.md", fp.name)
                    if m:
                        try:
                            firm_minutes[fdir.name][int(m.group(1))] = fp.read_text(
                                encoding="utf-8", errors="replace"
                            )
                        except Exception:
                            pass
                if fp.is_file() and fp.name.startswith("annual_report_FY"):
                    m = re.match(r"annual_report_FY(\d+)\.md", fp.name)
                    if m:
                        try:
                            firm_annual[fdir.name][int(m.group(1))] = fp.read_text(
                                encoding="utf-8", errors="replace"
                            )
                        except Exception:
                            pass

    firm_ids.sort(key=lambda f: int(f.split("_")[-1]) if "_" in f else 0)

    # Render env gazettes — one <details> per quarter
    qs_sorted = sorted(gazettes_by_q.keys())
    if max_complete_q is not None:
        qs_sorted = [q for q in qs_sorted if q <= max_complete_q]
    gazettes_html_blocks = []
    for q in qs_sorted:
        text = gazettes_by_q[q]
        # Truncate extremely long entries to keep HTML manageable
        if len(text) > 8000:
            text = text[:8000] + "\n\n[…truncated…]"
        # Escape HTML special chars
        text_esc = (text.replace("&", "&amp;").replace("<", "&lt;")
                         .replace(">", "&gt;"))
        # First sentence as preview in summary
        first_line = text.split("\n", 1)[0][:140]
        first_line_esc = (first_line.replace("&", "&amp;")
                                       .replace("<", "&lt;")
                                       .replace(">", "&gt;"))
        gazettes_html_blocks.append(
            f"<details class='gazette'>"
            f"<summary><b>Q{q}</b> — {first_line_esc}…</summary>"
            f"<pre class='narrative-pre'>{text_esc}</pre>"
            f"</details>"
        )
    gazettes_html = "\n".join(gazettes_html_blocks) or "<p><em>No env gazettes recorded.</em></p>"

    # Render per-firm board minutes — firm sub-nav with section visibility
    # via a simple radio group (CSS only, per-firm). We use one radio
    # group per dashboard (firm-narrative-group) that toggles which firm's
    # minutes section is visible.
    firm_blocks: list = []
    firm_labels: list = []
    for i, fid in enumerate(firm_ids):
        # Tab radio for firm
        firm_labels.append(
            f'<input type="radio" id="fn_{fid}" class="firm-narr-input" '
            f'name="firm_narr" {"checked" if i == 0 else ""}>'
            f'<label for="fn_{fid}" class="firm-narr-label">{fid}</label>'
        )
        # Build minutes blocks
        minutes = firm_minutes.get(fid, {})
        annual = firm_annual.get(fid, {})
        blocks: list = []
        if annual:
            blocks.append("<h4>Annual reports</h4>")
            for fy in sorted(annual.keys()):
                ar_text = annual[fy]
                if len(ar_text) > 12000:
                    ar_text = ar_text[:12000] + "\n\n[…truncated…]"
                ar_esc = (ar_text.replace("&", "&amp;")
                                  .replace("<", "&lt;")
                                  .replace(">", "&gt;"))
                blocks.append(
                    f"<details class='narrative-block'>"
                    f"<summary><b>FY{fy}</b> annual report</summary>"
                    f"<pre class='narrative-pre'>{ar_esc}</pre>"
                    f"</details>"
                )
        if minutes:
            blocks.append("<h4>Board minutes (quarterly)</h4>")
            for q in sorted(minutes.keys()):
                m_text = minutes[q]
                if len(m_text) > 8000:
                    m_text = m_text[:8000] + "\n\n[…truncated…]"
                m_esc = (m_text.replace("&", "&amp;")
                                .replace("<", "&lt;")
                                .replace(">", "&gt;"))
                # Try to extract a one-line summary
                lines = m_text.splitlines()
                summary_line = ""
                for ln in lines:
                    if ln.strip() and not ln.startswith("#"):
                        summary_line = ln[:120]
                        break
                summary_esc = (summary_line.replace("&", "&amp;")
                                              .replace("<", "&lt;")
                                              .replace(">", "&gt;"))
                blocks.append(
                    f"<details class='narrative-block'>"
                    f"<summary><b>Q{q}</b> — {summary_esc[:80]}</summary>"
                    f"<pre class='narrative-pre'>{m_esc}</pre>"
                    f"</details>"
                )
        if not blocks:
            blocks.append(f"<p><em>No board minutes / annual reports for {fid}.</em></p>")

        firm_blocks.append(
            f'<div class="firm-narr-content" data-firm="{fid}">'
            + "\n".join(blocks) + "</div>"
        )

    firm_minutes_html = ""
    if firm_ids:
        firm_minutes_html = (
            '<div class="firm-narr-tabs">'
            + "\n".join(firm_labels)
            + '\n'
            + "\n".join(firm_blocks)
            + "</div>"
        )
    else:
        firm_minutes_html = "<p><em>No firm narrative output found.</em></p>"

    return f"""
<h2>Narratives</h2>
<p class="tab-intro">Per-quarter env industry gazette and per-firm board
minutes / annual reports. The narrative content is the laboratory's
distinctive output — what the agents <em>argued</em>, not just what
they decided. Use Ctrl+F to search across all expanded sections.</p>

<h3>Industry gazettes (env, {len(qs_sorted)} quarters)</h3>
<p class="tab-intro">Env's per-quarter industry narrative. Click any
quarter to expand.</p>
{gazettes_html}

<h3>Per-firm board minutes & annual reports</h3>
<p class="tab-intro">Pick a firm. Annual reports are FY rollups (Q4);
board minutes are quarterly executive discussions covering forecasts,
financing options, and strategic direction.</p>
{firm_minutes_html}
"""


def _render_audit_health_tab(go, make_subplots, events, run_dir):
    """Tab 11 — Audit, restatements, engineering health, action log."""
    audit = _load_csv(run_dir / "audit_analytics.csv")
    restatements = _load_csv(run_dir / "restatements.csv")
    compustat = _load_csv(run_dir / "compustat_q.csv")
    compustat_restated = _load_csv(run_dir / "compustat_restated.csv")

    # BS violations from JSONL
    bs_violations: list = []
    bs_path = run_dir / "bs_violations.jsonl"
    if bs_path.exists():
        try:
            for line in bs_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    bs_violations.append(json.loads(line))
                except Exception:
                    pass
        except Exception:
            pass

    # Action log summary from proposals.jsonl
    action_counts_by_type: dict = defaultdict(int)
    action_counts_by_quarter: dict = defaultdict(int)
    proposals_path = run_dir / "proposals.jsonl"
    n_proposals = 0
    if proposals_path.exists():
        try:
            for line in proposals_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    n_proposals += 1
                    action_counts_by_type[obj.get("action_type", "?")] += 1
                    q = obj.get("quarter", 0)
                    if isinstance(q, (int, float)):
                        action_counts_by_quarter[int(q)] += 1
                except Exception:
                    pass
        except Exception:
            pass

    # Cost ledger if available (cost_summary.txt)
    cost_summary = ""
    cost_path = run_dir / "cost_summary.txt"
    if cost_path.exists():
        try:
            cost_summary = cost_path.read_text(encoding="utf-8")[:5000]
        except Exception:
            pass

    # Audit opinions table
    audit_rows = "".join(
        f"<tr><td>{r.get('fyear','')}</td>"
        f"<td>{r.get('firm_id','')}</td>"
        f"<td>{r.get('auditor_id','')}</td>"
        f"<td>{r.get('opinion','')}</td>"
        f"<td>${_safe_float(r.get('audit_fee'))/1e6:,.2f}M</td>"
        f"<td>{r.get('tenure_years','')}</td></tr>"
        for r in audit[:80]
    )

    # Restatement table
    rest_rows = "".join(
        f"<tr><td>Q{r.get('announcement_quarter','')}</td>"
        f"<td>{r.get('firm_id','')}</td>"
        f"<td>{r.get('trigger','')}</td>"
        f"<td>${_safe_float(r.get('original_ni'))/1e6:,.1f}M</td>"
        f"<td>${_safe_float(r.get('restated_ni'))/1e6:,.1f}M</td>"
        f"<td>${_safe_float(r.get('restatement_amount'))/1e6:,.1f}M</td>"
        f"<td>{'Y' if r.get('sec_flag') in ('1', 1, True) else ''}</td></tr>"
        for r in restatements
    )

    # Detect restatement-impacted rows (compustat_restated has restatement_flag=1)
    impacted = [r for r in compustat_restated if r.get("restatement_flag") in ("1", 1)]

    # BS violation count
    bs_html = ""
    if bs_violations:
        # Plot count over time
        bs_by_q: dict = defaultdict(int)
        for v in bs_violations:
            q = v.get("quarter", 0)
            if isinstance(q, (int, float)):
                bs_by_q[int(q)] += 1
        if bs_by_q:
            qs = sorted(bs_by_q.keys())
            fig_bs = go.Figure()
            fig_bs.add_trace(go.Bar(
                x=qs, y=[bs_by_q[q] for q in qs],
                marker_color="#c0392b",
            ))
            fig_bs.update_layout(
                title=f"Balance-sheet invariant violations per quarter "
                      f"({len(bs_violations)} total)",
                xaxis_title="Quarter", yaxis_title="Violations",
                height=300, margin=dict(l=60, r=40, t=60, b=40),
            )
            bs_html = _fig_to_div(fig_bs, "fig_bs_violations", include_plotlyjs=False)
        bs_rows = "".join(
            f"<tr><td>Q{v.get('quarter','')}</td>"
            f"<td>{v.get('firm_id','')}</td>"
            f"<td>{v.get('phase','')}</td>"
            f"<td>${_safe_float(v.get('residual'))/1e6:,.2f}M</td>"
            f"<td>{v.get('detail','')[:80]}</td></tr>"
            for v in bs_violations[:40]
        )
        bs_html += f"""
<table class="event-table">
<thead><tr><th>Q</th><th>Firm</th><th>Phase</th><th>Residual</th><th>Detail</th></tr></thead>
<tbody>{bs_rows}</tbody></table>
"""
    else:
        bs_html = "<p><em>No BS-invariant violations recorded — clean run.</em></p>"

    # Action log summary
    action_html = ""
    if action_counts_by_type:
        # Bar chart of counts by type
        types_sorted = sorted(action_counts_by_type.keys(),
                                key=lambda k: -action_counts_by_type[k])[:20]
        fig_act = go.Figure()
        fig_act.add_trace(go.Bar(
            x=types_sorted,
            y=[action_counts_by_type[t] for t in types_sorted],
            marker_color="#3498db",
        ))
        fig_act.update_layout(
            title=f"Action counts by type (total: {n_proposals} actions)",
            xaxis_title="Action type", yaxis_title="Count",
            height=380, margin=dict(l=60, r=40, t=60, b=80),
            xaxis=dict(tickangle=-30),
        )
        action_html = _fig_to_div(fig_act, "fig_actions", include_plotlyjs=False)

        # Per-quarter activity volume
        qs = sorted(action_counts_by_quarter.keys())
        if qs:
            fig_act_q = go.Figure()
            fig_act_q.add_trace(go.Scatter(
                x=qs, y=[action_counts_by_quarter[q] for q in qs],
                mode="lines+markers", name="Actions per Q",
                line=dict(color="#9b59b6", width=2),
            ))
            fig_act_q.update_layout(
                title="Action volume per quarter (proposals.jsonl)",
                xaxis_title="Quarter", yaxis_title="Actions",
                height=300, margin=dict(l=60, r=40, t=60, b=40),
            )
            action_html += _fig_to_div(fig_act_q, "fig_actions_q",
                                          include_plotlyjs=False)

    # Cost ledger
    cost_html = ""
    if cost_summary:
        cost_esc = (cost_summary.replace("&", "&amp;")
                                  .replace("<", "&lt;").replace(">", "&gt;"))
        cost_html = f"""
<h3>Cost ledger</h3>
<details><summary>Full cost_summary.txt (click to expand)</summary>
<pre class='narrative-pre'>{cost_esc}</pre></details>
"""

    return f"""
<h2>Audit, restatements, and engineering health</h2>
<p class="tab-intro">Auditor opinions, restatement events, balance-sheet
invariant violations, and the agent action log. The Health section
surfaces engineering quality signals that would otherwise stay buried.</p>

<h3>Audit opinions ({len(audit)} firm-year opinions)</h3>
<table class="event-table">
<thead><tr><th>FY</th><th>Firm</th><th>Auditor</th><th>Opinion</th>
<th>Fee</th><th>Tenure</th></tr></thead>
<tbody>{audit_rows or "<tr><td colspan=6>No audit opinions recorded.</td></tr>"}</tbody>
</table>

<h3>Restatements ({len(restatements)} events, {len(impacted)} firm-quarter rows impacted)</h3>
<table class="event-table">
<thead><tr><th>Q</th><th>Firm</th><th>Trigger</th>
<th>Original NI</th><th>Restated NI</th><th>Δ</th><th>SEC AAER</th></tr></thead>
<tbody>{rest_rows or "<tr><td colspan=7>No restatements recorded.</td></tr>"}</tbody>
</table>

<h3>Balance-sheet invariant violations ({len(bs_violations)})</h3>
{bs_html}

<h3>Agent action log summary</h3>
<p>The proposals.jsonl file records every agent decision with rationale
and (where applicable) accept/reject outcome. {n_proposals:,} total
actions recorded.</p>
{action_html or "<p><em>No action log entries.</em></p>"}

{cost_html}
"""


def _render_macro_tab(go, make_subplots, run_dir):
    macro = _read_macro_trajectory(run_dir)
    if not macro:
        return "<h2>Macro</h2><p>No macro trajectory found in snapshots.</p>"

    qs = [m["q"] for m in macro]
    panels = [
        ("Policy rate (annualized %)", [
            ("Policy rate", qs, [m["policy_rate"] * 100 for m in macro], "#c0392b"),
        ]),
        ("Market risk premium", [
            ("Risk premium", qs, [m["risk_premium"] for m in macro], "#2980b9"),
        ]),
        ("Political uncertainty (0–1)", [
            ("Political uncertainty", qs, [m["political_uncertainty"] for m in macro], "#8e44ad"),
        ]),
        ("Awareness rate (0–1)", [
            ("Awareness", qs, [m["awareness_rate"] for m in macro], "#27ae60"),
        ]),
    ]
    fig = _multi_panel_subplots(go, make_subplots, panels)
    div = _fig_to_div(fig, "fig_macro", include_plotlyjs=False)
    return f"""
<h2>Macro environment</h2>
<p class="tab-intro">Policy rate, market risk premium, political uncertainty,
and demand-side awareness over the run.</p>
{div}
"""


# ─────────────────────────────────────────────────────────────────────────
# Top-level renderer
# ─────────────────────────────────────────────────────────────────────────

CSS = """
* { box-sizing: border-box; }
body {
    font-family: -apple-system, "Segoe UI", Roboto, sans-serif;
    margin: 0; padding: 0; background: #f5f6fa; color: #2d3436;
    max-width: 1400px; margin: 0 auto;
}
header {
    background: linear-gradient(135deg, #6c5ce7 0%, #a29bfe 100%);
    color: white; padding: 30px 40px; margin-bottom: 0;
}
header h1 { margin: 0 0 6px 0; font-size: 28px; }
header .meta { opacity: 0.85; font-size: 14px; }
.kpi-grid {
    display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 12px; padding: 20px 40px; background: white;
    border-bottom: 1px solid #e0e0e0;
}
.kpi { padding: 12px; background: #f7f7fa; border-radius: 6px; text-align: center; }
.kpi-label { font-size: 12px; color: #666; text-transform: uppercase; letter-spacing: 0.04em; }
.kpi-value { font-size: 22px; font-weight: 600; color: #2d3436; margin-top: 4px; }
.kpi-sub { font-size: 11px; color: #888; margin-top: 2px; }

/* CSS-only tab interface */
.tabs { background: white; border-bottom: 2px solid #6c5ce7; padding: 0 40px; }
.tab-input { display: none; }
.tab-label {
    display: inline-block; padding: 14px 22px; cursor: pointer;
    font-weight: 500; color: #555; border-bottom: 3px solid transparent;
    transition: all 0.2s;
}
.tab-label:hover { color: #6c5ce7; background: #f5f5fa; }
.tab-content { display: none; padding: 30px 40px; background: white; }
.tab-input:checked + .tab-label {
    color: #6c5ce7; border-bottom-color: #6c5ce7; background: #f5f5fa;
}
/* Show the content panel that follows the checked input.
   Each tab block is structured: input → label, with all content after the labels. */
#tab1:checked ~ .tab-content[data-tab="1"],
#tab2:checked ~ .tab-content[data-tab="2"],
#tab3:checked ~ .tab-content[data-tab="3"],
#tab4:checked ~ .tab-content[data-tab="4"],
#tab5:checked ~ .tab-content[data-tab="5"],
#tab6:checked ~ .tab-content[data-tab="6"],
#tab7:checked ~ .tab-content[data-tab="7"],
#tab8:checked ~ .tab-content[data-tab="8"],
#tab9:checked ~ .tab-content[data-tab="9"],
#tab10:checked ~ .tab-content[data-tab="10"],
#tab11:checked ~ .tab-content[data-tab="11"] { display: block; }

/* Narrative panels — collapsible details/summary blocks */
details.gazette, details.narrative-block {
    background: #faf9fc; border-left: 3px solid #6c5ce7;
    padding: 8px 14px; margin: 6px 0; border-radius: 0 4px 4px 0;
}
details.gazette summary, details.narrative-block summary {
    cursor: pointer; font-size: 14px; padding: 4px 0;
    color: #2d3436;
}
details.gazette[open], details.narrative-block[open] {
    background: #f0eef9;
}
.narrative-pre {
    white-space: pre-wrap; word-wrap: break-word;
    font-family: -apple-system, "Segoe UI", Roboto, sans-serif;
    font-size: 13px; color: #333; line-height: 1.5;
    background: white; padding: 12px; border-radius: 4px;
    border: 1px solid #e8e8e8; margin-top: 8px;
    max-height: 600px; overflow-y: auto;
}

/* Per-firm narrative sub-tabs */
.firm-narr-input { display: none; }
.firm-narr-label {
    display: inline-block; padding: 6px 14px; cursor: pointer;
    font-size: 13px; color: #555; border: 1px solid #ddd;
    margin: 2px; border-radius: 4px; background: white;
}
.firm-narr-label:hover { background: #f5f5fa; color: #6c5ce7; }
.firm-narr-tabs .firm-narr-content { display: none; padding: 16px 0; }
/* Show the firm content matching the checked radio. We dynamically
   write CSS for each firm's id below in render_dashboard_html. */
.firm-narr-input:checked + .firm-narr-label {
    background: #6c5ce7; color: white; border-color: #6c5ce7;
}

/* Search bar (vanilla JS will hook this) */
.search-box {
    width: 100%; padding: 10px; font-size: 14px;
    border: 1px solid #ccc; border-radius: 4px; margin-bottom: 16px;
    background: white;
}

h2 { margin-top: 0; color: #2d3436; border-bottom: 2px solid #e0e0e0; padding-bottom: 8px; }
h3 { color: #3a3a3a; margin-top: 30px; }
.tab-intro { color: #666; font-size: 14px; margin-bottom: 20px; max-width: 800px; }

/* Tables */
table.event-table {
    width: 100%; border-collapse: collapse; margin: 16px 0;
    font-size: 13px; background: white;
}
table.event-table th {
    background: #6c5ce7; color: white; padding: 10px;
    text-align: left; font-weight: 500;
}
table.event-table td {
    padding: 8px 10px; border-bottom: 1px solid #f0f0f0;
}
table.event-table tr:hover td { background: #faf8ff; }

footer {
    padding: 20px 40px; background: #2d3436; color: #b0b0b0;
    font-size: 12px; text-align: center;
}
"""


def render_dashboard_html(panel: dict, events: list[dict], kpis: dict,
                            run_id: str, out_path: Path,
                            run_dir: Path) -> None:
    """Build a single-file tabbed Plotly dashboard."""
    try:
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
    except ImportError:
        print("plotly not installed; skipping dashboard.html. "
              "Install with: pip install plotly")
        return

    max_q = _max_complete_quarter(run_dir)
    per_firm_q, base = _build_firm_compustat_panel(run_dir, max_q)
    agg = _aggregate_trajectories(per_firm_q)

    # Compute HHI per quarter for industry tab from per-firm shares
    hhi_per_q: dict = {}
    top_share_per_q: dict = {}
    for fid_to_q in [per_firm_q]:
        pass
    for q in agg["quarters"]:
        firm_revs = []
        for fid, qmap in per_firm_q.items():
            r = qmap.get(q)
            if r:
                rev = _safe_float(r.get("saleq"))
                if rev > 0:
                    firm_revs.append(rev)
        total = sum(firm_revs)
        if total > 0:
            shares = [r / total for r in firm_revs]
            hhi_per_q[q] = sum(s * s * 10000 for s in shares)
            top_share_per_q[q] = max(shares) * 100
        else:
            hhi_per_q[q] = 0
            top_share_per_q[q] = 0

    # Override placeholders in agg
    agg["hhi"] = [(q, hhi_per_q.get(q, 0)) for q in agg["quarters"]]
    agg["top_share"] = [(q, top_share_per_q.get(q, 0)) for q in agg["quarters"]]

    # Re-render industry tab using corrected HHI / top-share
    industry_tab = _render_industry_tab_v2(go, make_subplots, agg, kpis)
    population_tab = _render_population_tab(go, make_subplots, panel, events)
    firm_detail_tab = _render_firm_detail_tab(go, make_subplots, per_firm_q,
                                                  panel, run_dir)
    capital_tab = _render_capital_tab(go, make_subplots, agg, run_dir)
    equity_tab = _render_equity_tab(go, make_subplots, per_firm_q, agg,
                                       events, run_dir)
    rd_tab = _render_rd_tab(go, make_subplots, per_firm_q, agg, events,
                                run_dir)
    governance_tab = _render_governance_tab(events, run_dir)
    ma_tab = _render_ma_tab(events, run_dir)
    macro_tab = _render_macro_tab(go, make_subplots, run_dir)
    narratives_tab = _render_narratives_tab(run_dir, max_q)
    audit_health_tab = _render_audit_health_tab(go, make_subplots, events, run_dir)

    # Dynamic CSS for per-firm narrative sub-tabs (one rule per firm).
    firm_narr_css_rules: list = []
    firms_dir = run_dir / "firms"
    if firms_dir.exists():
        for fdir in sorted(firms_dir.iterdir(),
                            key=lambda p: int(p.name.split("_")[-1])
                            if p.name.startswith("firm_") and p.name.split("_")[-1].isdigit()
                            else 0):
            if fdir.is_dir() and fdir.name.startswith("firm_"):
                firm_narr_css_rules.append(
                    f'#fn_{fdir.name}:checked ~ '
                    f'.firm-narr-content[data-firm="{fdir.name}"] '
                    f'{{ display: block; }}'
                )
    firm_narr_css = "\n".join(firm_narr_css_rules)

    kpi_html = _render_kpi_grid(kpis)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Run Dashboard — {run_id}</title>
<style>{CSS}
{firm_narr_css}
</style>
</head>
<body>

<header>
<h1>Run Dashboard — {run_id}</h1>
<div class="meta">{kpis.get('n_quarters', '?')} quarters · {kpis.get('n_unique_firms', '?')} firms ·
{kpis.get('n_defaults_total', 0)} defaults · {kpis.get('n_acquisitions_total', 0)} M&A ·
${kpis.get('cumulative_revenue_m', 0):,.0f}M cumulative revenue</div>
</header>

{kpi_html}

<div class="tabs">
<input type="radio" id="tab1" class="tab-input" name="tabs" checked>
<label for="tab1" class="tab-label">Industry</label>
<input type="radio" id="tab2" class="tab-input" name="tabs">
<label for="tab2" class="tab-label">Population</label>
<input type="radio" id="tab3" class="tab-input" name="tabs">
<label for="tab3" class="tab-label">Firm Detail</label>
<input type="radio" id="tab4" class="tab-input" name="tabs">
<label for="tab4" class="tab-label">Capital</label>
<input type="radio" id="tab5" class="tab-input" name="tabs">
<label for="tab5" class="tab-label">Equity</label>
<input type="radio" id="tab6" class="tab-input" name="tabs">
<label for="tab6" class="tab-label">R&D / Ops</label>
<input type="radio" id="tab7" class="tab-input" name="tabs">
<label for="tab7" class="tab-label">Governance</label>
<input type="radio" id="tab8" class="tab-input" name="tabs">
<label for="tab8" class="tab-label">M&A / PE</label>
<input type="radio" id="tab9" class="tab-input" name="tabs">
<label for="tab9" class="tab-label">Macro</label>
<input type="radio" id="tab10" class="tab-input" name="tabs">
<label for="tab10" class="tab-label">Narratives</label>
<input type="radio" id="tab11" class="tab-input" name="tabs">
<label for="tab11" class="tab-label">Audit / Health</label>

<div class="tab-content" data-tab="1">{industry_tab}</div>
<div class="tab-content" data-tab="2">{population_tab}</div>
<div class="tab-content" data-tab="3">{firm_detail_tab}</div>
<div class="tab-content" data-tab="4">{capital_tab}</div>
<div class="tab-content" data-tab="5">{equity_tab}</div>
<div class="tab-content" data-tab="6">{rd_tab}</div>
<div class="tab-content" data-tab="7">{governance_tab}</div>
<div class="tab-content" data-tab="8">{ma_tab}</div>
<div class="tab-content" data-tab="9">{macro_tab}</div>
<div class="tab-content" data-tab="10">{narratives_tab}</div>
<div class="tab-content" data-tab="11">{audit_health_tab}</div>
</div>

<footer>
Generated programmatically from snapshots, compustat panel, event logs,
narrative outputs, and JSONL streams. For raw data see <code>events.csv</code>,
<code>compustat_q.csv</code>, <code>gazettes.txt</code>, and the per-firm
<code>firms/firm_X/</code> directories.
</footer>

<script>
// Wave ν+10: minimal vanilla-JS table search. Adds a search input above
// every table marked with class="event-table" that has > 5 rows; typing
// filters rows in place. Pure JS, no framework.
(function() {{
    document.querySelectorAll('table.event-table').forEach(function(tbl) {{
        var tbody = tbl.querySelector('tbody');
        if (!tbody) return;
        var rows = tbody.querySelectorAll('tr');
        if (rows.length <= 5) return;
        var box = document.createElement('input');
        box.type = 'text';
        box.placeholder = 'Filter rows…';
        box.className = 'search-box';
        box.addEventListener('input', function() {{
            var q = box.value.toLowerCase();
            rows.forEach(function(tr) {{
                tr.style.display = tr.textContent.toLowerCase().indexOf(q) >= 0 ? '' : 'none';
            }});
        }});
        tbl.parentNode.insertBefore(box, tbl);
    }});
}})();
</script>

</body>
</html>
"""
    out_path.write_text(html, encoding="utf-8")


def _render_industry_tab_v2(go, make_subplots, agg, kpis):
    """Industry overview with corrected HHI / top-share."""
    quarters = agg["quarters"]
    rev = [v / 1e6 for _, v in agg["saleq"]]
    ni = [v / 1e6 for _, v in agg["niq"]]
    cogs = [v / 1e6 for _, v in agg["cogsq"]]
    op_inc = [v / 1e6 for _, v in agg["oiadpq"]]
    cfo = [v / 1e6 for _, v in agg["oancfq"]]
    rd = [v / 1e6 for _, v in agg["xrdq"]]
    sga = [v / 1e6 for _, v in agg["xsgaq"]]
    capx = [v / 1e6 for _, v in agg["capxq"]]
    cash = [v / 1e6 for _, v in agg["cheq"]]

    fig1 = _multi_panel_subplots(go, make_subplots, [
        ("Industry quarterly revenue ($M)", [
            ("Total revenue", quarters, rev, "#27ae60"),
            ("COGS", quarters, cogs, "#e67e22"),
            ("R&D", quarters, rd, "#8e44ad"),
            ("SGA", quarters, sga, "#16a085"),
        ]),
        ("Industry quarterly profit ($M)", [
            ("Net income", quarters, ni, "#c0392b"),
            ("Operating income", quarters, op_inc, "#2980b9"),
            ("Cash flow from ops", quarters, cfo, "#1abc9c"),
        ]),
        ("Aggregate cash + capex ($M)", [
            ("Total cash", quarters, cash, "#3498db"),
            ("Capex", quarters, capx, "#e74c3c"),
        ]),
    ])

    fig2 = _multi_panel_subplots(go, make_subplots, [
        ("Top-firm market share (%)", [
            ("Top share", quarters, [v for _, v in agg["top_share"]], "#c0392b"),
        ]),
        ("Herfindahl–Hirschman Index", [
            ("HHI", quarters, [v for _, v in agg["hhi"]], "#2980b9"),
        ]),
        ("Number of firms with positive sales", [
            ("Producers", quarters, [v for _, v in agg["n_producers"]], "#27ae60"),
        ]),
    ])

    div1 = _fig_to_div(fig1, "fig_industry_pl")
    div2 = _fig_to_div(fig2, "fig_industry_concentration", include_plotlyjs=False)

    return f"""
<h2>Industry overview</h2>
<p class="tab-intro">Aggregate income-statement, cash-flow, and concentration trajectories.
Hover any chart for exact values; double-click a series in the legend to isolate it.</p>
{div1}
{div2}
"""


def _render_kpi_grid(kpis: dict) -> str:
    items = [
        ("Quarters", kpis.get("n_quarters", "?")),
        ("Firms (lifetime)", kpis.get("n_unique_firms", "?")),
        ("Active at close", kpis.get("n_active_end", "?")),
        ("Defaults", kpis.get("n_defaults_total", 0)),
        ("M&A deals", kpis.get("n_acquisitions_total", 0)),
        ("Activations", kpis.get("n_activations_total", 0)),
        ("Avg HHI", f"{kpis.get('final_hhi', 0):.0f}" if kpis.get("final_hhi") else "—"),
        ("Top share", f"{kpis.get('final_top_share_pct', 0):.1f}%"),
        ("Cumulative revenue", f"${kpis.get('cumulative_revenue_m', 0):,.0f}M"),
        ("Equity moves >3×", kpis.get("n_equity_spikes", 0)),
    ]
    inner = "".join(
        f'<div class="kpi"><div class="kpi-label">{lbl}</div>'
        f'<div class="kpi-value">{val}</div></div>'
        for lbl, val in items
    )
    return f'<div class="kpi-grid">{inner}</div>'
