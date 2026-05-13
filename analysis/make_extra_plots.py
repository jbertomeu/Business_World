"""Additional plot: firm timeline (Gantt-style)."""
import csv, os
from collections import defaultdict
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

OUT = 'analysis/figures'

with open(f'{OUT}/panel.csv') as fp:
    rows = [r for r in csv.DictReader(fp)]

# Build per-firm state per quarter
firms = sorted(set(r['firm_id'] for r in rows), key=lambda f: int(f.split('_')[1]))
firm_states = defaultdict(dict)  # fid -> q -> state
for r in rows:
    q = int(r['q'])
    if r['is_active'] == 'True':
        if r['net_sales'] != '0.0' and float(r['net_sales']) > 0:
            firm_states[r['firm_id']][q] = 'producing'
        else:
            firm_states[r['firm_id']][q] = 'active_idle'
    elif r['is_dormant'] == 'True':
        firm_states[r['firm_id']][q] = 'dormant'
    else:
        firm_states[r['firm_id']][q] = 'defaulted'

# Plot timeline
fig, ax = plt.subplots(figsize=(11.5, 5.5))
state_colors = {
    'producing': '#27ae60',
    'active_idle': '#f39c12',
    'dormant': '#bdc3c7',
    'defaulted': '#34495e',
}
state_labels = {
    'producing': 'Producing (positive sales)',
    'active_idle': 'Active but zero sales',
    'dormant': 'Dormant (unfunded)',
    'defaulted': 'Defaulted',
}

for i, fid in enumerate(firms):
    y = i
    for q in range(1, 81):
        st = firm_states[fid].get(q)
        if st is None:
            continue
        ax.barh(y, 1, left=q - 0.5, height=0.8,
                color=state_colors[st], edgecolor='none')

ax.set_yticks(range(len(firms)))
ax.set_yticklabels(firms)
ax.invert_yaxis()
ax.set_xlim(0.5, 80.5)
ax.set_xlabel('Quarter')
ax.set_title('Firm lifecycle timeline — entry, dormancy, production, default')
ax.axvline(41, color='red', linestyle='--', linewidth=1, alpha=0.7)
ax.text(41.5, -0.5, 'Q41 cascade', fontsize=9, color='red')

# Legend
patches = [mpatches.Patch(color=state_colors[k], label=state_labels[k])
           for k in ['producing', 'active_idle', 'dormant', 'defaulted']]
ax.legend(handles=patches, loc='center left', bbox_to_anchor=(1.0, 0.5), fontsize=9)
ax.grid(False)
plt.tight_layout()
plt.savefig(f'{OUT}/timeline.pdf', bbox_inches='tight')
plt.close()
print(f'Wrote {OUT}/timeline.pdf')
