"""Extract panel data from snapshots for ν+6 20Y analysis."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pickle
import glob
import re
import csv

SNAP_DIR = 'outputs/run_1777670848/snapshots'
OUT_DIR = 'analysis/figures'
os.makedirs(OUT_DIR, exist_ok=True)

paths = sorted(
    glob.glob(f'{SNAP_DIR}/Q*.pkl'),
    key=lambda p: int(re.match(r'.*Q(\d+)\.pkl', p).group(1)),
)

rows = []
for path in paths:
    q = int(re.match(r'.*Q(\d+)\.pkl', path).group(1))
    if q > 80:  # cap at Q80
        continue
    snap = pickle.load(open(path, 'rb'))
    state = snap['world_state']
    flows = state.last_quarter_flows or {}
    for fid, f in state.firms.items():
        fl = flows.get(fid)
        rev = float(getattr(fl, 'net_sales', 0) or 0) if fl else 0.0
        units_sold = int(getattr(fl, 'units_sold', 0) or 0) if fl else 0
        units_prod = int(getattr(fl, 'units_produced', 0) or 0) if fl else 0
        is_active = bool(f.is_active)
        is_dormant = bool(getattr(f, 'is_dormant', False))
        defaulted = (not is_active) and (not is_dormant)
        rows.append({
            'q': q,
            'firm_id': fid,
            'firm_idx': int(fid.split('_')[1]),
            'is_active': is_active,
            'is_dormant': is_dormant,
            'defaulted': defaulted,
            'net_sales': rev,
            'units_sold': units_sold,
            'units_produced': units_prod,
            'cash': float(f.cash),
            'capability': float(f.capability_stock),
            'brand': float(f.brand_stock),
            'rd_cum_product': float(f.rd_cumulative_product),
            'product_gen': int(f.product_generation),
            'geo_focus': str(f.geographic_focus or ''),
            'patient_seg': str(f.patient_segment or ''),
        })

with open(f'{OUT_DIR}/panel.csv', 'w', newline='') as fp:
    w = csv.DictWriter(fp, fieldnames=list(rows[0].keys()))
    w.writeheader()
    w.writerows(rows)

print(f'Wrote {len(rows)} rows to {OUT_DIR}/panel.csv')
print(f'Quarters: {min(r["q"] for r in rows)}-{max(r["q"] for r in rows)}')
print(f'Firms ever seen: {len(set(r["firm_id"] for r in rows))}')
