"""Generate plots for the ν+6 20Y research overview."""
import csv
import os
from collections import defaultdict
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker

OUT = 'analysis/figures'
os.makedirs(OUT, exist_ok=True)

# load panel
with open(f'{OUT}/panel.csv') as fp:
    rows = [{
        **r,
        'q': int(r['q']),
        'firm_idx': int(r['firm_idx']),
        'is_active': r['is_active'] == 'True',
        'is_dormant': r['is_dormant'] == 'True',
        'defaulted': r['defaulted'] == 'True',
        'net_sales': float(r['net_sales']),
        'units_sold': int(r['units_sold']),
        'units_produced': int(r['units_produced']),
        'cash': float(r['cash']),
        'capability': float(r['capability']),
        'brand': float(r['brand']),
        'rd_cum_product': float(r['rd_cum_product']),
        'product_gen': int(r['product_gen']),
    } for r in csv.DictReader(fp)]

# Index by quarter
by_q = defaultdict(list)
for r in rows:
    by_q[r['q']].append(r)
quarters = sorted(by_q.keys())

# Per-firm time series
firms_seen = sorted(set(r['firm_id'] for r in rows), key=lambda f: int(f.split('_')[1]))

# 16 distinguishable colors
COLORS = plt.cm.tab20.colors
firm_color = {f: COLORS[i % len(COLORS)] for i, f in enumerate(firms_seen)}

# ---------- Plot 1: Top firm share + HHI over time ----------
def hhi(vals):
    s = sum(vals)
    if s <= 0:
        return 0.0
    shares = [v / s for v in vals]
    return sum((sh * 100) ** 2 for sh in shares)

top_share = []
hhis = []
total_rev = []
n_active = []
n_producers = []
n_defaulted = []
for q in quarters:
    qrows = by_q[q]
    revs = [r['net_sales'] for r in qrows if r['net_sales'] > 0]
    tot = sum(revs)
    total_rev.append(tot / 1e6)
    top_share.append(100 * max(revs) / tot if tot > 0 else 0)
    hhis.append(hhi(revs))
    n_active.append(sum(1 for r in qrows if r['is_active']))
    n_producers.append(len(revs))
    n_defaulted.append(sum(1 for r in qrows if r['defaulted']))

fig, ax1 = plt.subplots(figsize=(11, 4.5))
ax1.plot(quarters, top_share, color='#c0392b', linewidth=2, label='Top-firm share (left axis)')
ax1.axhspan(70, 100, color='#fadbd8', alpha=0.4, zorder=0, label='Concentration danger zone')
ax1.axvline(41, color='#34495e', linestyle='--', linewidth=1, alpha=0.7)
ax1.text(41.7, 92, 'Q41 default cascade', fontsize=9, color='#34495e')
ax1.set_xlabel('Quarter')
ax1.set_ylabel('Top-firm market share (%)', color='#c0392b')
ax1.set_ylim(0, 105)
ax1.tick_params(axis='y', labelcolor='#c0392b')
ax1.grid(alpha=0.3)

ax2 = ax1.twinx()
ax2.plot(quarters, hhis, color='#2980b9', linewidth=1.5, alpha=0.8, label='HHI (right axis)')
ax2.set_ylabel('HHI (× 10,000; 10,000 = monopoly)', color='#2980b9')
ax2.set_ylim(0, 10500)
ax2.tick_params(axis='y', labelcolor='#2980b9')

plt.title('Industry concentration over 20 years — top-firm share and HHI')
fig.tight_layout()
plt.savefig(f'{OUT}/concentration.pdf', bbox_inches='tight')
plt.close()
print(f'Wrote {OUT}/concentration.pdf')

# ---------- Plot 2: Total industry revenue over time ----------
fig, ax = plt.subplots(figsize=(11, 4))
ax.plot(quarters, total_rev, color='#2c3e50', linewidth=2)
ax.axvline(41, color='#c0392b', linestyle='--', linewidth=1, alpha=0.7, label='Q41 default cascade')
ax.fill_between(quarters, 0, total_rev, color='#3498db', alpha=0.2)
ax.set_xlabel('Quarter')
ax.set_ylabel('Total industry revenue ($M)')
ax.set_title('Industry revenue collapses after the Q41 default')
ax.grid(alpha=0.3)
ax.legend(loc='upper right')
plt.tight_layout()
plt.savefig(f'{OUT}/revenue.pdf', bbox_inches='tight')
plt.close()
print(f'Wrote {OUT}/revenue.pdf')

# ---------- Plot 3: Per-firm revenue stack/area ----------
firm_rev = {f: [0.0] * len(quarters) for f in firms_seen}
for r in rows:
    qi = quarters.index(r['q'])
    firm_rev[r['firm_id']][qi] = r['net_sales'] / 1e6

# stacked area, ordered by total contribution
order = sorted(firms_seen, key=lambda f: -sum(firm_rev[f]))
fig, ax = plt.subplots(figsize=(11, 5))
ax.stackplot(quarters, [firm_rev[f] for f in order],
             labels=order, colors=[firm_color[f] for f in order], alpha=0.85)
ax.axvline(41, color='black', linestyle='--', linewidth=1, alpha=0.6)
ax.text(41.7, ax.get_ylim()[1] * 0.92, 'Q41', fontsize=9)
ax.set_xlabel('Quarter')
ax.set_ylabel('Revenue ($M, stacked)')
ax.set_title('Per-firm revenue contribution — diversity collapses to firm_9 monopoly after Q41')
ax.legend(loc='center left', bbox_to_anchor=(1.0, 0.5), fontsize=8, ncol=1)
ax.grid(alpha=0.3)
plt.tight_layout()
plt.savefig(f'{OUT}/per_firm_revenue.pdf', bbox_inches='tight')
plt.close()
print(f'Wrote {OUT}/per_firm_revenue.pdf')

# ---------- Plot 4: Active firm count + cumulative defaults ----------
fig, ax = plt.subplots(figsize=(11, 4))
ax.plot(quarters, n_active, color='#27ae60', linewidth=2, label='Active firms')
ax.plot(quarters, n_producers, color='#3498db', linewidth=2, label='Firms with positive sales')
ax.plot(quarters, n_defaulted, color='#c0392b', linewidth=2, label='Cumulative defaults')
ax.axvline(41, color='black', linestyle='--', linewidth=1, alpha=0.5)
ax.set_xlabel('Quarter')
ax.set_ylabel('Number of firms')
ax.set_title('Firm population dynamics — active vs. producing vs. defaulted')
ax.legend(loc='upper left')
ax.grid(alpha=0.3)
ax.set_yticks(range(0, 17, 2))
plt.tight_layout()
plt.savefig(f'{OUT}/firm_population.pdf', bbox_inches='tight')
plt.close()
print(f'Wrote {OUT}/firm_population.pdf')

# ---------- Plot 5: Firm cash trajectories ----------
firm_cash = {f: [None] * len(quarters) for f in firms_seen}
firm_active_q = {f: [False] * len(quarters) for f in firms_seen}
for r in rows:
    qi = quarters.index(r['q'])
    firm_cash[r['firm_id']][qi] = r['cash'] / 1e6
    firm_active_q[r['firm_id']][qi] = r['is_active']

fig, ax = plt.subplots(figsize=(11, 5))
for f in firms_seen:
    series = firm_cash[f]
    qs = [q for q, v in zip(quarters, series) if v is not None]
    vs = [v for v in series if v is not None]
    if not vs:
        continue
    is_winner = f == 'firm_9'
    ax.plot(qs, vs, color=firm_color[f],
            linewidth=2.5 if is_winner else 1,
            alpha=1.0 if is_winner else 0.5,
            label=f if is_winner else None)

ax.axvline(41, color='black', linestyle='--', linewidth=1, alpha=0.5)
ax.set_xlabel('Quarter')
ax.set_ylabel('Cash ($M)')
ax.set_title('Cash trajectories — firm_9 (red) accumulates a $5.9B hoard during 39-quarter monopoly')
ax.legend(loc='upper left')
ax.grid(alpha=0.3)
plt.tight_layout()
plt.savefig(f'{OUT}/cash.pdf', bbox_inches='tight')
plt.close()
print(f'Wrote {OUT}/cash.pdf')

# ---------- Plot 6: Production zoom-in around the cascade Q38-Q50 ----------
zoom_q = list(range(38, 51))
firm_units = {f: [0] * len(zoom_q) for f in firms_seen}
for r in rows:
    if r['q'] in zoom_q:
        qi = zoom_q.index(r['q'])
        firm_units[r['firm_id']][qi] = r['units_produced']

fig, ax = plt.subplots(figsize=(11, 5))
bottom = [0] * len(zoom_q)
for f in firms_seen:
    series = firm_units[f]
    if sum(series) == 0:
        continue
    ax.bar(zoom_q, series, bottom=bottom, label=f, color=firm_color[f], alpha=0.85)
    bottom = [b + s for b, s in zip(bottom, series)]

ax.axvline(41, color='black', linestyle='--', linewidth=1, alpha=0.6)
ax.text(41.2, max(bottom) * 0.92, 'Q41 default', fontsize=9)
ax.set_xlabel('Quarter')
ax.set_ylabel('Units produced (stacked)')
ax.set_title('Production cascade Q38-Q50 — all firms drop to 0 production at Q42 except firm_9 (sells from inventory)')
ax.legend(loc='upper right', fontsize=8)
ax.grid(alpha=0.3, axis='y')
plt.tight_layout()
plt.savefig(f'{OUT}/cascade_zoom.pdf', bbox_inches='tight')
plt.close()
print(f'Wrote {OUT}/cascade_zoom.pdf')

# ---------- Plot 7: Capability stocks over time ----------
firm_cap = {f: [None] * len(quarters) for f in firms_seen}
for r in rows:
    qi = quarters.index(r['q'])
    firm_cap[r['firm_id']][qi] = r['capability']

fig, ax = plt.subplots(figsize=(11, 5))
for f in firms_seen:
    series = firm_cap[f]
    qs = [q for q, v in zip(quarters, series) if v is not None]
    vs = [v for v in series if v is not None]
    if not vs:
        continue
    ax.plot(qs, vs, color=firm_color[f], linewidth=1.2, alpha=0.6, label=f)
ax.axvline(41, color='black', linestyle='--', linewidth=1, alpha=0.5)
ax.set_xlabel('Quarter')
ax.set_ylabel('Capability stock (0–100)')
ax.set_title('Capability stocks across all firms — firm_9 sustains highest capability throughout monopoly era')
ax.legend(loc='center left', bbox_to_anchor=(1.0, 0.5), fontsize=7, ncol=1)
ax.grid(alpha=0.3)
plt.tight_layout()
plt.savefig(f'{OUT}/capability.pdf', bbox_inches='tight')
plt.close()
print(f'Wrote {OUT}/capability.pdf')

# ---------- Plot 8: R&D cumulative product (Gen2 progress) ----------
firm_rd = {f: [None] * len(quarters) for f in firms_seen}
for r in rows:
    qi = quarters.index(r['q'])
    firm_rd[r['firm_id']][qi] = r['rd_cum_product'] / 1e6

fig, ax = plt.subplots(figsize=(11, 5))
for f in firms_seen:
    series = firm_rd[f]
    qs = [q for q, v in zip(quarters, series) if v is not None]
    vs = [v for v in series if v is not None]
    if not vs or max(vs) < 5:
        continue
    ax.plot(qs, vs, color=firm_color[f], linewidth=1.4, alpha=0.7, label=f)
ax.axhline(200, color='gray', linestyle=':', linewidth=1, label='Gen-2 R&D threshold ($200M)')
ax.axvline(41, color='black', linestyle='--', linewidth=1, alpha=0.5)
ax.set_xlabel('Quarter')
ax.set_ylabel('Cumulative product R&D ($M)')
ax.set_title('Cumulative product R&D — no firm advances to Gen-2 across 80 quarters')
ax.legend(loc='center left', bbox_to_anchor=(1.0, 0.5), fontsize=7, ncol=1)
ax.grid(alpha=0.3)
plt.tight_layout()
plt.savefig(f'{OUT}/rd_progress.pdf', bbox_inches='tight')
plt.close()
print(f'Wrote {OUT}/rd_progress.pdf')

print('\n=== Summary stats ===')
print(f'Quarters analysed: 1-{max(quarters)}')
print(f'Total firms: {len(firms_seen)}')
print(f'Final defaults: {n_defaulted[-1]}')
print(f'Final active: {n_active[-1]}')
print(f'Final producers: {n_producers[-1]}')
print(f'Top-share trajectory: Q1={top_share[0]:.1f}%  Q40={top_share[39]:.1f}%  Q42={top_share[41]:.1f}%  Q80={top_share[-1]:.1f}%')
print(f'HHI trajectory: Q1={hhis[0]:.0f}  Q40={hhis[39]:.0f}  Q42={hhis[41]:.0f}  Q80={hhis[-1]:.0f}')
print(f'Total revenue: Q1=${total_rev[0]:.1f}M  Q40=${total_rev[39]:.1f}M  Q80=${total_rev[-1]:.1f}M')
print(f'firm_9 final cash: ${[r["cash"] for r in by_q[80] if r["firm_id"]=="firm_9"][0]/1e6:.0f}M')
