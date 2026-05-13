"""Wave ν+8 — post-run debrief generator.

Reads a run directory and produces a 3-artifact bundle:

  debrief/
    events.csv      — chronological lifecycle events
    dashboard.html  — single-file interactive Plotly dashboard
    debrief.md      — narrative industry retrospective

Usage:
    python analysis/make_debrief.py outputs/run_<id>

Designed to be reusable across all runs. Pulls only from the run dir
(snapshots, csvs, logs); no network or LLM calls.
"""
from __future__ import annotations

import sys, os, re, csv, glob, json, pickle, datetime
from collections import defaultdict
from pathlib import Path

# Ensure src/ is importable for FirmState pickle deserialization
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def find_run_log(run_dir: Path) -> Path | None:
    """Find the supervisor log next to the run dir, if any."""
    parent = run_dir.parent
    rid = run_dir.name
    # Common naming patterns the supervisor uses
    candidates = list(parent.glob(f"validation_*log*.txt"))
    return candidates[-1] if candidates else None


def extract_events(run_dir: Path) -> list[dict]:
    """Build a chronological event list from snapshots, CSVs, and logs."""
    events = []

    # 1. From snapshots: detect quarter-by-quarter state transitions
    snap_dir = run_dir / "snapshots"
    snap_paths = sorted(
        snap_dir.glob("Q*.pkl"),
        key=lambda p: int(re.match(r"Q(\d+)\.pkl", p.name).group(1)),
    )

    # Determine the highest quarter the run actually completed (= last
    # compustat row's absolute quarter). Snapshots beyond that are
    # partial-state artifacts; their state transitions aren't real events.
    comp_csv = run_dir / "compustat_q.csv"
    max_complete_q = None
    if comp_csv.exists():
        try:
            with open(comp_csv, encoding="utf-8") as fp:
                _crows = list(csv.DictReader(fp))
            if _crows:
                _base = (int(_crows[0]["fyearq"]) * 4 +
                         int(_crows[0]["fqtr"]))
                max_complete_q = max(
                    (int(r["fyearq"]) * 4 + int(r["fqtr"]) - _base + 1)
                    for r in _crows
                )
        except Exception:
            pass

    prior_state_data = {}  # firm_id -> {quarter, status, gen, capability, brand, cash}
    for path in snap_paths:
        q = int(re.match(r"Q(\d+)\.pkl", path.name).group(1))
        # Skip partial-state snapshot (see panel-data note for rationale).
        if max_complete_q is not None and q > max_complete_q:
            continue
        try:
            snap = pickle.load(open(path, "rb"))
        except Exception:
            continue
        state = snap["world_state"]
        for fid, f in state.firms.items():
            cur = {
                "quarter": q,
                "is_active": f.is_active,
                "is_dormant": getattr(f, "is_dormant", False),
                "gen": f.product_generation,
                "capability": f.capability_stock,
                "brand": f.brand_stock,
                "cash": float(f.cash),
                "ppe_gross": float(f.ppe_gross),
            }
            prior = prior_state_data.get(fid)
            if prior is None:
                # Firm appeared this quarter
                events.append({
                    "quarter": q,
                    "type": "spawn",
                    "primary_firm": fid,
                    "secondary_firm": "",
                    "value_usd": 0.0,
                    "narrative": f"{fid} spawned (cap={cur['capability']:.0f}, brand={cur['brand']:.0f})",
                })
            else:
                # State transition detection
                # Active -> dormant
                if prior["is_active"] and not cur["is_active"] and cur["is_dormant"]:
                    events.append({
                        "quarter": q,
                        "type": "dormancy",
                        "primary_firm": fid,
                        "secondary_firm": "",
                        "value_usd": cur["cash"],
                        "narrative": f"{fid} entered dormant state",
                    })
                # Active -> defaulted
                if prior["is_active"] and not cur["is_active"] and not cur["is_dormant"]:
                    events.append({
                        "quarter": q,
                        "type": "default",
                        "primary_firm": fid,
                        "secondary_firm": "",
                        "value_usd": cur["cash"],
                        "narrative": f"{fid} defaulted (cash at default ${cur['cash']/1e6:.0f}M)",
                    })
                # Activation: firm exits dormant state. Firms spawn with
                # is_active=True AND is_dormant=True; activation flips
                # is_dormant False while is_active stays True.
                if prior["is_dormant"] and not cur["is_dormant"] and cur["is_active"]:
                    events.append({
                        "quarter": q,
                        "type": "activation",
                        "primary_firm": fid,
                        "secondary_firm": "",
                        "value_usd": cur["cash"],
                        "narrative": f"{fid} activated (PE-funded; cash ${cur['cash']/1e6:.0f}M)",
                    })
                # Generation advance
                if cur["gen"] > prior["gen"]:
                    events.append({
                        "quarter": q,
                        "type": "generation_advance",
                        "primary_firm": fid,
                        "secondary_firm": "",
                        "value_usd": 0.0,
                        "narrative": f"{fid} advanced to Gen{cur['gen']}",
                    })
            prior_state_data[fid] = cur

    # 2. M&A / auction events from distressed_auctions.csv. The CSV doesn't
    # carry a quarter column; we cross-reference each target's default quarter
    # from the default events already collected.
    default_q_by_firm = {
        e["primary_firm"]: e["quarter"] for e in events if e["type"] == "default"
    }
    auction_csv = run_dir / "distressed_auctions.csv"
    if auction_csv.exists():
        with open(auction_csv, encoding="utf-8") as fp:
            for r in csv.DictReader(fp):
                if r.get("outcome") != "sold":
                    continue
                target = r.get("target_firm_id", "")
                winner = r.get("winner_id", "")
                amount = float(r.get("winning_amount", 0) or 0)
                q = default_q_by_firm.get(target, 0)
                events.append({
                    "quarter": int(q),
                    "type": "auction_sale",
                    "primary_firm": winner,
                    "secondary_firm": target,
                    "value_usd": amount,
                    "narrative": (
                        f"{winner} acquired {target} for ${amount/1e6:.0f}M "
                        f"(distressed auction)"
                    ),
                })
        # Also try snapshot's in-memory event log as a backup source for any
        # auctions not in the CSV (e.g. crash before flush).
        try:
            last_snap = pickle.load(open(snap_paths[-1], "rb"))
            existing_targets = {
                e["secondary_firm"] for e in events if e["type"] == "auction_sale"
            }
            for ev in last_snap["world_state"].distressed_auctions:
                if ev.get("outcome") != "sold":
                    continue
                target = ev.get("target_firm_id", "")
                if target in existing_targets:
                    continue
                q = ev.get("quarter") or default_q_by_firm.get(target, 0)
                events.append({
                    "quarter": int(q) if q else 0,
                    "type": "auction_sale",
                    "primary_firm": ev.get("winner_id", ""),
                    "secondary_firm": target,
                    "value_usd": float(ev.get("winning_amount", 0)),
                    "narrative": (
                        f"{ev.get('winner_id','')} acquired {target} "
                        f"for ${float(ev.get('winning_amount',0))/1e6:.0f}M "
                        f"(distressed auction)"
                    ),
                })
        except Exception:
            pass

    # 3. CEO turnover from ceo_turnover.csv
    ceo_csv = run_dir / "ceo_turnover.csv"
    if ceo_csv.exists():
        with open(ceo_csv, encoding="utf-8") as fp:
            for r in csv.DictReader(fp):
                try:
                    q = int(r.get("event_quarter", 0))
                except (ValueError, TypeError):
                    q = 0
                events.append({
                    "quarter": q,
                    "type": f"ceo_{r.get('event_type','turnover')}",
                    "primary_firm": r.get("firm_id", ""),
                    "secondary_firm": "",
                    "value_usd": float(r.get("severance", 0) or 0),
                    "narrative": (
                        f"{r.get('firm_id','')} CEO {r.get('event_type','')}; "
                        f"{r.get('departing_ceo_id','')} → {r.get('incoming_ceo_id','')}"
                    ),
                })

    # 4. Activist campaigns from activist_campaigns.csv
    act_csv = run_dir / "activist_campaigns.csv"
    if act_csv.exists():
        with open(act_csv, encoding="utf-8") as fp:
            for r in csv.DictReader(fp):
                try:
                    q = int(r.get("event_quarter", 0))
                except (ValueError, TypeError):
                    q = 0
                events.append({
                    "quarter": q,
                    "type": "activist_campaign",
                    "primary_firm": r.get("firm_id", ""),
                    "secondary_firm": r.get("activist_id", ""),
                    "value_usd": 0.0,
                    "narrative": (
                        f"{r.get('activist_id','')} launched {r.get('demand_type','')} "
                        f"campaign on {r.get('firm_id','')} "
                        f"({float(r.get('stake_pct_implied',0) or 0)*100:.1f}% stake)"
                    ),
                })

    # 5. Restatements
    rest_csv = run_dir / "restatements.csv"
    if rest_csv.exists():
        with open(rest_csv, encoding="utf-8") as fp:
            for r in csv.DictReader(fp):
                try:
                    q = int(r.get("announcement_quarter", 0))
                except (ValueError, TypeError):
                    q = 0
                events.append({
                    "quarter": q,
                    "type": "restatement",
                    "primary_firm": r.get("firm_id", ""),
                    "secondary_firm": "",
                    "value_usd": 0.0,
                    "narrative": f"{r.get('firm_id','')} restatement: {r.get('reason','')}",
                })

    # 6. Equity price spikes (>3x QoQ) from compustat
    comp_csv = run_dir / "compustat_q.csv"
    if comp_csv.exists():
        with open(comp_csv, encoding="utf-8") as fp:
            rows = list(csv.DictReader(fp))
        rows.sort(key=lambda r: (r.get("firm_id", ""), int(r.get("fyearq", 0)),
                                  int(r.get("fqtr", 0))))
        prev_price = {}
        for r in rows:
            fid = r.get("firm_id", "")
            try:
                p = float(r.get("prccq", 0) or 0)
                fy = int(r.get("fyearq", 0))
                fq = int(r.get("fqtr", 0))
            except (ValueError, TypeError):
                continue
            q = (fy - 2031) * 4 + fq if fy else 0
            pp = prev_price.get(fid, 0)
            if pp > 0 and p > 0 and (p / pp >= 3.0 or pp / p >= 3.0):
                direction = "spike" if p > pp else "crash"
                events.append({
                    "quarter": q,
                    "type": f"equity_{direction}",
                    "primary_firm": fid,
                    "secondary_firm": "",
                    "value_usd": p,
                    "narrative": (
                        f"{fid} equity price {direction}: ${pp:.2f} → ${p:.2f} "
                        f"({p/pp:.1f}x)"
                    ),
                })
            prev_price[fid] = p

    # Sort by quarter, then by type for stable ordering
    events.sort(key=lambda e: (e["quarter"], e["type"], e["primary_firm"]))
    return events


def build_panel_data(run_dir: Path) -> dict:
    """Read all snapshots and produce per-quarter aggregates + per-firm time series.

    Skips any snapshot whose quarter index has no corresponding compustat row.
    This filters out partial-state snapshots (e.g. a Q81.pkl written when the
    orchestrator started Q81 but exited before accounting flushed the
    compustat panel for that quarter). Without this filter the partial state
    produces a misleading row in the panel — most firms show $0 net_sales
    while one firm with stale flows is reported as 100% market share.
    """
    snap_dir = run_dir / "snapshots"
    snap_paths = sorted(
        snap_dir.glob("Q*.pkl"),
        key=lambda p: int(re.match(r"Q(\d+)\.pkl", p.name).group(1)),
    )

    # Determine the highest quarter index that has a compustat row. Any
    # snapshot beyond this is a partial-state artifact and is excluded.
    comp_csv = run_dir / "compustat_q.csv"
    max_complete_q = None
    if comp_csv.exists():
        try:
            with open(comp_csv, encoding="utf-8") as fp:
                comp_rows = list(csv.DictReader(fp))
            if comp_rows:
                base = (int(comp_rows[0]["fyearq"]) * 4 +
                        int(comp_rows[0]["fqtr"]))
                max_complete_q = max(
                    (int(r["fyearq"]) * 4 + int(r["fqtr"]) - base + 1)
                    for r in comp_rows
                )
        except Exception:
            pass
    quarters = []
    quarterly = []  # {q, total_rev, top_share, hhi, n_active, n_producers, n_defaulted, n_dormant}
    firm_history = defaultdict(list)  # firm_id -> list of {q, status, rev, share, cap, brand, cash, gen, units}

    skipped_partial = []
    for path in snap_paths:
        q = int(re.match(r"Q(\d+)\.pkl", path.name).group(1))
        # Snapshot Q<n>.pkl is the post-quarter-n state. If the simulation
        # exited mid-quarter, the snapshot may be partial (state.quarter
        # advanced and some flows populated but accounting / compustat
        # write incomplete). Skip if that quarter has no compustat row.
        if max_complete_q is not None and q > max_complete_q:
            skipped_partial.append(q)
            continue
        try:
            snap = pickle.load(open(path, "rb"))
        except Exception:
            continue
        state = snap["world_state"]
        flows = state.last_quarter_flows or {}

        revs = []
        for fid, fl in flows.items():
            try:
                r = float(getattr(fl, "net_sales", 0) or 0)
            except (TypeError, ValueError):
                r = 0
            if r > 0:
                revs.append(r)
        total = sum(revs)
        top_share = (max(revs) / total * 100) if revs and total > 0 else 0
        hhi = sum(((r / total) * 100) ** 2 for r in revs) if total > 0 else 0
        n_active = sum(1 for f in state.firms.values() if f.is_active)
        n_dormant = sum(1 for f in state.firms.values()
                         if getattr(f, "is_dormant", False))
        n_defaulted = sum(1 for f in state.firms.values()
                           if not f.is_active and not getattr(f, "is_dormant", False))

        quarters.append(q)
        quarterly.append({
            "q": q,
            "total_rev": total,
            "top_share": top_share,
            "hhi": hhi,
            "n_active": n_active,
            "n_producers": len(revs),
            "n_defaulted": n_defaulted,
            "n_dormant": n_dormant,
        })

        for fid, f in state.firms.items():
            fl = flows.get(fid)
            rev = float(getattr(fl, "net_sales", 0) or 0) if fl else 0
            units = int(getattr(fl, "actual_production", 0) or 0) if fl else 0
            status = ("active" if f.is_active
                      else "dormant" if getattr(f, "is_dormant", False)
                      else "defaulted")
            firm_history[fid].append({
                "q": q, "status": status, "rev": rev, "units": units,
                "cap": float(f.capability_stock),
                "brand": float(f.brand_stock),
                "cash": float(f.cash),
                "gen": int(f.product_generation),
                "share": (rev / total * 100) if total > 0 else 0,
                "geo": str(getattr(f, "geographic_focus", "") or ""),
                "segment": str(getattr(f, "patient_segment", "") or ""),
            })

    return {
        "quarters": quarters,
        "quarterly": quarterly,
        "firm_history": dict(firm_history),
        "skipped_partial": skipped_partial,
    }


def headline_kpis(panel: dict, events: list[dict]) -> dict:
    """Compute top-level KPIs for the dashboard."""
    if not panel["quarterly"]:
        return {}
    last = panel["quarterly"][-1]
    first = panel["quarterly"][0]
    total_revenue_cumulative = sum(q["total_rev"] for q in panel["quarterly"])
    n_defaults = sum(1 for e in events if e["type"] == "default")
    n_acquisitions = sum(1 for e in events if e["type"] == "auction_sale")
    n_gen_advances = sum(1 for e in events if e["type"] == "generation_advance")
    n_equity_spikes = sum(1 for e in events if e["type"].startswith("equity_"))
    n_activations = sum(1 for e in events if e["type"] == "activation")
    n_unique_firms = len(panel["firm_history"])
    return {
        "first_quarter": first["q"],
        "last_quarter": last["q"],
        "n_quarters": len(panel["quarterly"]),
        "n_unique_firms": n_unique_firms,
        "n_active_end": last["n_active"],
        "n_defaulted_end": last["n_defaulted"],
        "final_top_share_pct": last["top_share"],
        "final_hhi": last["hhi"],
        "final_revenue_m": last["total_rev"] / 1e6,
        "cumulative_revenue_m": total_revenue_cumulative / 1e6,
        "n_defaults_total": n_defaults,
        "n_acquisitions_total": n_acquisitions,
        "n_gen_advances": n_gen_advances,
        "n_equity_spikes": n_equity_spikes,
        "n_activations_total": n_activations,
    }


def render_dashboard_html(panel: dict, events: list[dict], kpis: dict,
                            run_id: str, out_path: Path) -> None:
    """Build a single-file Plotly HTML dashboard."""
    try:
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
    except ImportError:
        print("plotly not installed; skipping dashboard.html. "
              "Install with: pip install plotly")
        return

    quarters = panel["quarters"]
    quarterly = panel["quarterly"]
    firm_history = panel["firm_history"]

    # Plot 1: top share + HHI + revenue (3 panels stacked)
    fig1 = make_subplots(rows=3, cols=1, shared_xaxes=True,
                          subplot_titles=("Top-firm market share (%)",
                                          "HHI (10000 = monopoly)",
                                          "Total industry revenue ($M)"),
                          vertical_spacing=0.06)
    fig1.add_trace(go.Scatter(x=quarters, y=[q["top_share"] for q in quarterly],
                              line=dict(color="#c0392b", width=2),
                              name="Top share"), row=1, col=1)
    fig1.add_trace(go.Scatter(x=quarters, y=[q["hhi"] for q in quarterly],
                              line=dict(color="#2980b9", width=2),
                              name="HHI"), row=2, col=1)
    fig1.add_trace(go.Scatter(x=quarters, y=[q["total_rev"]/1e6 for q in quarterly],
                              line=dict(color="#27ae60", width=2),
                              name="Revenue", fill='tozeroy', fillcolor="rgba(46,204,113,0.2)"),
                   row=3, col=1)
    fig1.update_layout(height=600, showlegend=False, margin=dict(l=60, r=40, t=60, b=40))
    fig1.update_xaxes(title_text="Quarter", row=3, col=1)

    # Plot 2: firm population
    fig2 = go.Figure()
    fig2.add_trace(go.Scatter(x=quarters, y=[q["n_active"] for q in quarterly],
                               line=dict(color="#27ae60", width=2), name="Active"))
    fig2.add_trace(go.Scatter(x=quarters, y=[q["n_producers"] for q in quarterly],
                               line=dict(color="#3498db", width=2), name="Producers (positive sales)"))
    fig2.add_trace(go.Scatter(x=quarters, y=[q["n_defaulted"] for q in quarterly],
                               line=dict(color="#c0392b", width=2), name="Defaulted (cumulative)"))
    fig2.add_trace(go.Scatter(x=quarters, y=[q["n_dormant"] for q in quarterly],
                               line=dict(color="#95a5a6", width=2), name="Dormant"))
    fig2.update_layout(title="Firm population over time",
                       xaxis_title="Quarter", yaxis_title="Number of firms",
                       height=400, margin=dict(l=60, r=40, t=60, b=40))

    # Plot 3: per-firm revenue stacked area
    firms_sorted = sorted(firm_history.keys(), key=lambda f: int(f.split("_")[1]))
    fig3 = go.Figure()
    palette = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
                "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf",
                "#aec7e8", "#ffbb78", "#98df8a", "#ff9896", "#c5b0d5",
                "#c49c94", "#f7b6d2"]
    for i, fid in enumerate(firms_sorted):
        hist = firm_history[fid]
        x = [h["q"] for h in hist]
        y = [h["rev"] / 1e6 for h in hist]
        fig3.add_trace(go.Scatter(x=x, y=y, name=fid, mode="lines",
                                    stackgroup="one", line=dict(width=0.5),
                                    fillcolor=palette[i % len(palette)]))
    fig3.update_layout(title="Per-firm revenue contribution (stacked)",
                       xaxis_title="Quarter", yaxis_title="Revenue ($M)",
                       height=500, margin=dict(l=60, r=40, t=60, b=40),
                       hovermode="x unified")

    # Plot 4: firm timeline gantt
    fig4 = go.Figure()
    color_map = {"active": "#27ae60", "active_idle": "#f39c12",
                  "dormant": "#bdc3c7", "defaulted": "#34495e"}
    # For each firm, build segments by status
    for i, fid in enumerate(firms_sorted):
        hist = firm_history[fid]
        for h in hist:
            status = h["status"]
            # 'active_idle' if active but no production
            if status == "active" and h["units"] == 0 and h["rev"] == 0:
                status = "active_idle"
            color = color_map.get(status, "#cccccc")
            fig4.add_trace(go.Bar(
                x=[1], y=[fid], orientation="h",
                base=[h["q"] - 0.5], marker=dict(color=color),
                showlegend=False,
                hovertemplate=(
                    f"{fid}<br>Q{h['q']}<br>status: {status}<br>"
                    f"rev: ${h['rev']/1e6:.1f}M<br>"
                    f"cap: {h['cap']:.0f}, brand: {h['brand']:.0f}<br>"
                    f"cash: ${h['cash']/1e6:.0f}M<extra></extra>"
                ),
            ))
    # Legend proxies
    for label, color in color_map.items():
        fig4.add_trace(go.Bar(x=[None], y=[None], marker_color=color,
                                name=label, orientation="h"))
    fig4.update_layout(title="Firm lifecycle timeline",
                       xaxis_title="Quarter", yaxis=dict(autorange="reversed"),
                       height=max(400, 30 * len(firms_sorted) + 100),
                       barmode="stack", showlegend=True,
                       margin=dict(l=80, r=40, t=60, b=40))

    # Plot 5: per-firm cash trajectories
    fig5 = go.Figure()
    for i, fid in enumerate(firms_sorted):
        hist = firm_history[fid]
        x = [h["q"] for h in hist]
        y = [h["cash"] / 1e6 for h in hist]
        fig5.add_trace(go.Scatter(x=x, y=y, name=fid, mode="lines",
                                    line=dict(color=palette[i % len(palette)], width=1.5)))
    fig5.update_layout(title="Per-firm cash trajectory ($M)",
                       xaxis_title="Quarter", yaxis_title="Cash ($M)",
                       height=500, margin=dict(l=60, r=40, t=60, b=40),
                       hovermode="x unified")

    # Build per-firm story cards
    firm_cards_html = []
    for fid in firms_sorted:
        hist = firm_history[fid]
        if not hist:
            continue
        first = hist[0]
        last = hist[-1]
        # Lifetime peak share
        peak_share_idx = max(range(len(hist)), key=lambda i: hist[i]["share"])
        peak = hist[peak_share_idx]
        # Final status
        status_label = {
            "active": "ACTIVE",
            "dormant": "DORMANT",
            "defaulted": "DEFAULTED",
        }.get(last["status"], "?")
        status_color = {
            "active": "#27ae60",
            "dormant": "#95a5a6",
            "defaulted": "#34495e",
        }.get(last["status"], "#888")
        # Firm-specific events
        firm_events = [e for e in events if e.get("primary_firm") == fid
                        or e.get("secondary_firm") == fid]
        firm_events.sort(key=lambda e: e["quarter"])
        evt_lines = "".join(
            f"<li>Q{e['quarter']}: {e['type']} — {e.get('narrative', '')}</li>"
            for e in firm_events[:30]
        )
        firm_cards_html.append(f"""
        <div class="firm-card">
          <h3>{fid} <span class="badge" style="background:{status_color}">{status_label}</span></h3>
          <div class="firm-meta">
            <div><strong>Niche:</strong> {first['geo'][:60]} / {first['segment'][:60]}</div>
            <div><strong>Spawned:</strong> Q{first['q']} (cap={first['cap']:.0f}, brand={first['brand']:.0f})</div>
            <div><strong>Final:</strong> Q{last['q']} cap={last['cap']:.0f} brand={last['brand']:.0f} cash=${last['cash']/1e6:.0f}M Gen{last['gen']}</div>
            <div><strong>Peak share:</strong> {peak['share']:.1f}% at Q{peak['q']}</div>
          </div>
          <details><summary>Events ({len(firm_events)})</summary><ul>{evt_lines}</ul></details>
        </div>
        """)

    # Events table HTML
    events_table_rows = "".join(
        f"<tr><td>Q{e['quarter']}</td><td>{e['type']}</td>"
        f"<td>{e.get('primary_firm', '')}</td>"
        f"<td>{e.get('secondary_firm', '')}</td>"
        f"<td>${e.get('value_usd', 0)/1e6:,.1f}M</td>"
        f"<td>{e.get('narrative', '')[:140]}</td></tr>"
        for e in events
    )

    # Inline plotly figures
    fig_html = lambda fig: fig.to_html(include_plotlyjs="cdn",
                                         full_html=False,
                                         div_id=None)

    out_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Run Debrief — {run_id}</title>
<style>
  body {{
    font-family: -apple-system, "Segoe UI", Roboto, sans-serif;
    margin: 0; padding: 20px 40px; background: #f5f6fa; color: #2d3436;
    max-width: 1300px; margin: 0 auto;
  }}
  h1 {{ color: #2d3436; border-bottom: 3px solid #6c5ce7; padding-bottom: 8px; }}
  h2 {{ color: #6c5ce7; margin-top: 30px; }}
  .kpi-grid {{
    display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px;
    margin: 20px 0;
  }}
  .kpi {{
    background: white; padding: 16px; border-radius: 8px;
    box-shadow: 0 2px 4px rgba(0,0,0,0.05);
  }}
  .kpi-label {{ font-size: 0.75em; color: #636e72; text-transform: uppercase; }}
  .kpi-value {{ font-size: 1.5em; font-weight: bold; color: #2d3436; }}
  .firm-grid {{
    display: grid; grid-template-columns: repeat(2, 1fr); gap: 16px;
  }}
  .firm-card {{
    background: white; padding: 14px 18px; border-radius: 8px;
    box-shadow: 0 2px 4px rgba(0,0,0,0.05);
  }}
  .firm-card h3 {{ margin: 0 0 8px 0; }}
  .firm-meta div {{ margin: 3px 0; font-size: 0.9em; }}
  .firm-card details {{ margin-top: 8px; font-size: 0.85em; color: #636e72; }}
  .firm-card summary {{ cursor: pointer; }}
  .firm-card ul {{ padding-left: 20px; max-height: 200px; overflow-y: auto; }}
  .badge {{
    color: white; padding: 2px 10px; border-radius: 12px;
    font-size: 0.7em; vertical-align: middle;
  }}
  .plot-section {{ background: white; padding: 12px;
    border-radius: 8px; margin: 16px 0;
    box-shadow: 0 2px 4px rgba(0,0,0,0.05); }}
  table {{ width: 100%; border-collapse: collapse; font-size: 0.85em; }}
  th, td {{ padding: 6px 10px; text-align: left; border-bottom: 1px solid #eee; }}
  th {{ background: #ecf0f1; font-weight: 600; }}
  tr:hover {{ background: #f8f9fa; }}
  .events-scroll {{ max-height: 500px; overflow-y: auto;
    background: white; border-radius: 8px;
    box-shadow: 0 2px 4px rgba(0,0,0,0.05); }}
  .footnote {{ font-size: 0.8em; color: #95a5a6; margin-top: 30px; }}
</style>
</head>
<body>

<h1>Run Debrief — {run_id}</h1>
<div class="footnote">Generated {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')} from
  snapshots Q{kpis.get('first_quarter','?')}–Q{kpis.get('last_quarter','?')}.</div>

<h2>Headline KPIs</h2>
<div class="kpi-grid">
  <div class="kpi"><div class="kpi-label">Quarters analyzed</div>
    <div class="kpi-value">{kpis.get('n_quarters','?')}</div></div>
  <div class="kpi"><div class="kpi-label">Unique firms</div>
    <div class="kpi-value">{kpis.get('n_unique_firms','?')}</div></div>
  <div class="kpi"><div class="kpi-label">Active at end</div>
    <div class="kpi-value">{kpis.get('n_active_end','?')}</div></div>
  <div class="kpi"><div class="kpi-label">Defaulted total</div>
    <div class="kpi-value">{kpis.get('n_defaults_total','?')}</div></div>
  <div class="kpi"><div class="kpi-label">M&amp;A acquisitions</div>
    <div class="kpi-value">{kpis.get('n_acquisitions_total','?')}</div></div>
  <div class="kpi"><div class="kpi-label">Leapfrog activations</div>
    <div class="kpi-value">{kpis.get('n_activations_total','?')}</div></div>
  <div class="kpi"><div class="kpi-label">Gen advances</div>
    <div class="kpi-value">{kpis.get('n_gen_advances','?')}</div></div>
  <div class="kpi"><div class="kpi-label">Equity spikes/crashes</div>
    <div class="kpi-value">{kpis.get('n_equity_spikes','?')}</div></div>
  <div class="kpi"><div class="kpi-label">Final top share</div>
    <div class="kpi-value">{kpis.get('final_top_share_pct',0):.1f}%</div></div>
  <div class="kpi"><div class="kpi-label">Final HHI</div>
    <div class="kpi-value">{kpis.get('final_hhi',0):,.0f}</div></div>
  <div class="kpi"><div class="kpi-label">Final revenue</div>
    <div class="kpi-value">${kpis.get('final_revenue_m',0):,.0f}M</div></div>
  <div class="kpi"><div class="kpi-label">Cumulative revenue</div>
    <div class="kpi-value">${kpis.get('cumulative_revenue_m',0):,.0f}M</div></div>
</div>

<h2>Industry trajectory</h2>
<div class="plot-section">{fig_html(fig1)}</div>

<h2>Firm population</h2>
<div class="plot-section">{fig_html(fig2)}</div>

<h2>Per-firm revenue</h2>
<div class="plot-section">{fig_html(fig3)}</div>

<h2>Per-firm cash</h2>
<div class="plot-section">{fig_html(fig5)}</div>

<h2>Firm lifecycle timeline</h2>
<div class="plot-section">{fig_html(fig4)}</div>

<h2>Per-firm story cards</h2>
<div class="firm-grid">{''.join(firm_cards_html)}</div>

<h2>Lifecycle events ({len(events)} total)</h2>
<div class="events-scroll">
<table>
  <thead><tr><th>Q</th><th>Type</th><th>Primary</th><th>Secondary</th>
  <th>Value</th><th>Narrative</th></tr></thead>
  <tbody>{events_table_rows}</tbody>
</table>
</div>

</body>
</html>
"""
    out_path.write_text(out_html, encoding="utf-8")
    print(f"  dashboard.html: {out_path} ({len(out_html):,} bytes)")


def render_debrief_md(panel: dict, events: list[dict], kpis: dict,
                       run_id: str, out_path: Path) -> None:
    """Build a narrative markdown debrief from the data."""
    quarterly = panel["quarterly"]
    firm_history = panel["firm_history"]

    # Identify lifecycle events for the narrative
    def evs_of_type(*types):
        return [e for e in events if e["type"] in types]

    defaults = evs_of_type("default")
    auctions = evs_of_type("auction_sale")
    activations = evs_of_type("activation")
    gen_advances = evs_of_type("generation_advance")
    spikes = evs_of_type("equity_spike", "equity_crash")
    spawns = [e for e in evs_of_type("spawn") if e["quarter"] > 1]  # post-Q1 entries

    # Survivors and losers
    last_q = max((q["q"] for q in quarterly), default=0)
    survivors = []
    losers = []
    for fid, hist in firm_history.items():
        last = hist[-1]
        if last["status"] == "active":
            survivors.append(fid)
        elif last["status"] == "defaulted":
            losers.append(fid)

    # Top of the table at end
    final_q = quarterly[-1] if quarterly else {}
    # Find top firm at end
    last_snap_firms = sorted(
        ((fid, h[-1]["rev"]) for fid, h in firm_history.items() if h),
        key=lambda x: -x[1]
    )
    top_firm = last_snap_firms[0][0] if last_snap_firms else "?"

    out = []
    out.append(f"# Industry Debrief — {run_id}")
    out.append("")
    out.append(f"_Period: Q{kpis.get('first_quarter','?')}–Q{kpis.get('last_quarter','?')}._")
    out.append("")
    out.append("## Executive summary")
    out.append("")
    out.append(
        f"Across {kpis.get('n_quarters','?')} quarters, "
        f"{kpis.get('n_unique_firms','?')} distinct firms competed in this industry. "
        f"By the final quarter, {kpis.get('n_active_end',0)} firms remained active "
        f"(top firm **{top_firm}** at {kpis.get('final_top_share_pct',0):.1f}% share), "
        f"with {kpis.get('n_defaults_total',0)} cumulative defaults along the way. "
        f"The industry consolidated through {kpis.get('n_acquisitions_total',0)} "
        f"M&A acquisitions and saw {kpis.get('n_activations_total',0)} leapfrog "
        f"activations from PE-funded entrants. "
        f"Cumulative industry revenue: ${kpis.get('cumulative_revenue_m',0):,.0f}M."
    )
    out.append("")

    # Defaults section
    out.append("## Defaults")
    out.append("")
    if defaults:
        out.append(f"{len(defaults)} firm(s) defaulted over the run:")
        out.append("")
        out.append("| Quarter | Firm | Cash at default |")
        out.append("|---|---|---|")
        for e in defaults:
            out.append(f"| Q{e['quarter']} | {e['primary_firm']} | "
                        f"${e.get('value_usd', 0)/1e6:,.0f}M |")
    else:
        out.append("_No defaults._")
    out.append("")

    # M&A section
    out.append("## Mergers and acquisitions")
    out.append("")
    if auctions:
        out.append(f"{len(auctions)} M&A deal(s) cleared via the distressed auction:")
        out.append("")
        out.append("| Quarter | Acquirer | Target | Price |")
        out.append("|---|---|---|---|")
        for e in auctions:
            out.append(f"| Q{e['quarter']} | {e['primary_firm']} | "
                        f"{e['secondary_firm']} | "
                        f"${e.get('value_usd', 0)/1e6:,.0f}M |")
    else:
        out.append("_No M&A activity._")
    out.append("")

    # Entry / leapfrog section
    out.append("## Entry and leapfrog activations")
    out.append("")
    if spawns:
        out.append(f"{len(spawns)} new firm(s) entered after Q1:")
        out.append("")
        for e in spawns:
            out.append(f"- Q{e['quarter']}: {e['narrative']}")
    out.append("")
    if activations:
        out.append("Of those entrants, the following secured PE funding and activated:")
        out.append("")
        for e in activations:
            out.append(f"- Q{e['quarter']}: {e['narrative']}")
    out.append("")

    # Generation advances
    out.append("## Generation advances")
    out.append("")
    if gen_advances:
        out.append(f"{len(gen_advances)} generation advance(s) granted:")
        out.append("")
        for e in gen_advances:
            out.append(f"- Q{e['quarter']}: {e['narrative']}")
    else:
        out.append("_No generation advances were granted in this run._")
    out.append("")

    # Equity anomalies
    if spikes:
        out.append("## Equity anomalies (likely engineering issues)")
        out.append("")
        out.append(f"{len(spikes)} large single-quarter equity move(s) detected (>3× threshold):")
        out.append("")
        for e in spikes:
            out.append(f"- Q{e['quarter']}: {e['narrative']}")
        out.append("")

    # Survivors and losers
    out.append("## Final roster")
    out.append("")
    out.append("### Survivors")
    out.append("")
    if survivors:
        for fid in sorted(survivors, key=lambda f: int(f.split("_")[1])):
            last = firm_history[fid][-1]
            peak_idx = max(range(len(firm_history[fid])),
                            key=lambda i: firm_history[fid][i]["share"])
            peak = firm_history[fid][peak_idx]
            out.append(
                f"- **{fid}** — final cash ${last['cash']/1e6:,.0f}M, "
                f"capability {last['cap']:.0f}, brand {last['brand']:.0f}, "
                f"Gen {last['gen']}. Peak share {peak['share']:.1f}% at Q{peak['q']}."
            )
    out.append("")
    out.append("### Defaulted")
    out.append("")
    if losers:
        for fid in sorted(losers, key=lambda f: int(f.split("_")[1])):
            default_q = next(
                (e["quarter"] for e in events
                 if e["type"] == "default" and e["primary_firm"] == fid),
                "?"
            )
            peak_idx = max(range(len(firm_history[fid])),
                            key=lambda i: firm_history[fid][i]["share"])
            peak = firm_history[fid][peak_idx]
            out.append(
                f"- **{fid}** — defaulted at Q{default_q}. "
                f"Peak share {peak['share']:.1f}% at Q{peak['q']}."
            )
    out.append("")

    # Patterns
    out.append("## Pattern interpretation")
    out.append("")
    n_defaults = kpis.get('n_defaults_total', 0)
    n_total = kpis.get('n_unique_firms', 1)
    default_rate = n_defaults / max(1, n_total) * 100
    avg_top_share = sum(q["top_share"] for q in quarterly) / max(1, len(quarterly))
    avg_producers = sum(q["n_producers"] for q in quarterly) / max(1, len(quarterly))
    out.append(
        f"Across the run, the average top-firm market share was "
        f"{avg_top_share:.1f}%, with on average {avg_producers:.1f} firms "
        f"producing positive revenue per quarter. "
        f"The default rate was {default_rate:.0f}% "
        f"({n_defaults} of {n_total} firms). "
    )
    if kpis.get('n_acquisitions_total', 0) > 0:
        out.append(
            f"M&A activity cleared {kpis['n_acquisitions_total']} deal(s), "
            "indicating active consolidation by cash-rich incumbents."
        )
    if kpis.get('n_gen_advances', 0) == 0:
        out.append(
            "**No firm advanced to a new product generation** over the period — "
            "this may indicate the env was overly conservative on generation "
            "transitions, or that no firm clearly cleared the technology threshold."
        )
    if kpis.get('n_equity_spikes', 0) > 0:
        out.append(
            f"**{kpis['n_equity_spikes']} large equity-price move(s) detected** "
            "(>3× single quarter), which may indicate the equity-market LLM "
            "produced unphysical valuations."
        )
    out.append("")

    out.append("---")
    out.append("")
    out.append(
        "_This debrief was generated programmatically from the run's snapshots, "
        "compustat panel, and event logs. For interactive exploration see "
        "`dashboard.html`. For the raw event timeline see `events.csv`._"
    )
    out.append("")

    out_path.write_text("\n".join(out), encoding="utf-8")
    print(f"  debrief.md: {out_path} ({sum(len(l) for l in out):,} chars)")


def main():
    if len(sys.argv) < 2:
        print("Usage: python analysis/make_debrief.py outputs/run_<id>")
        sys.exit(1)
    run_dir = Path(sys.argv[1])
    if not run_dir.exists():
        print(f"Run dir not found: {run_dir}")
        sys.exit(1)
    out_dir = run_dir / "debrief"
    out_dir.mkdir(exist_ok=True)
    run_id = run_dir.name

    print(f"Generating debrief for {run_id}...")
    print(f"  Reading snapshots from {run_dir / 'snapshots'}")

    # 1. Events
    print("  Extracting events...")
    events = extract_events(run_dir)
    print(f"    {len(events)} events")
    events_csv = out_dir / "events.csv"
    if events:
        with open(events_csv, "w", newline="", encoding="utf-8") as fp:
            w = csv.DictWriter(fp, fieldnames=list(events[0].keys()))
            w.writeheader()
            w.writerows(events)
    print(f"  events.csv: {events_csv}")

    # 2. Panel data
    print("  Building panel data...")
    panel = build_panel_data(run_dir)
    print(f"    {len(panel['quarters'])} quarters, "
          f"{len(panel['firm_history'])} firms tracked")

    # 3. KPIs
    kpis = headline_kpis(panel, events)

    # 4. Dashboard — Wave ν+10: tabbed renderer with 9 menus exposing
    # ~40+ variables. Falls back to the legacy renderer if the tabbed
    # module fails to import (e.g. plotly missing).
    print("  Rendering dashboard.html...")
    try:
        from analysis.dashboard import render_dashboard_html as _tabbed
        _tabbed(panel, events, kpis, run_id,
                out_dir / "dashboard.html", run_dir)
    except Exception as e:
        import traceback
        print(f"  Tabbed dashboard failed: {e}; falling back to legacy.")
        traceback.print_exc()
        render_dashboard_html(panel, events, kpis, run_id,
                              out_dir / "dashboard.html")

    # 5. Debrief markdown
    print("  Rendering debrief.md...")
    render_debrief_md(panel, events, kpis, run_id, out_dir / "debrief.md")

    print()
    print(f"Done. Outputs in {out_dir}/")


if __name__ == "__main__":
    main()
