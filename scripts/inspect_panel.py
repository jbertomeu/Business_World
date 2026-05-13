"""Inspect a Compustat panel for anomalies."""
import csv
import sys
from collections import defaultdict

path = sys.argv[1] if len(sys.argv) > 1 else "outputs/run_1775879334/compustat_q.csv"
rows = list(csv.DictReader(open(path)))

print("=== CROSS-QUARTER CHECKS ===\n")

by_firm = defaultdict(list)
for r in rows:
    by_firm[r["firm_id"]].append(r)

for fid in sorted(by_firm):
    frows = by_firm[fid]
    print(f"--- {fid} ---")

    for i in range(1, len(frows)):
        # RE roll-forward
        prev_re = float(frows[i-1]["req"])
        curr_re = float(frows[i]["req"])
        ni = float(frows[i]["niq"])
        dv = float(frows[i]["dvq"])
        expected_re = prev_re + ni - dv
        re_diff = abs(curr_re - expected_re)
        if re_diff > 1:
            print(f"  Q{frows[i]['fqtr']}: RE roll FAIL: {prev_re:,.0f}+{ni:,.0f}-{dv:,.0f}={expected_re:,.0f} vs {curr_re:,.0f} (diff={re_diff:,.0f})")

        # Cash continuity
        prev_cash = float(frows[i-1]["cheq"])
        curr_cash = float(frows[i]["cheq"])
        chechq = float(frows[i]["chechq"])
        expected_cash = prev_cash + chechq
        cash_diff = abs(curr_cash - expected_cash)
        if cash_diff > 1:
            print(f"  Q{frows[i]['fqtr']}: Cash continuity FAIL: {prev_cash:,.0f}+{chechq:,.0f}={expected_cash:,.0f} vs {curr_cash:,.0f} (diff={cash_diff:,.0f})")

        # PPE continuity
        prev_ppent = float(frows[i-1]["ppentq"])
        curr_ppent = float(frows[i]["ppentq"])
        capx = float(frows[i]["capxq"])
        dep = float(frows[i]["dpq"])
        expected_ppe = prev_ppent + capx - dep
        ppe_diff = abs(curr_ppent - expected_ppe)
        if ppe_diff > 1:
            print(f"  Q{frows[i]['fqtr']}: PPE FAIL: {prev_ppent:,.0f}+{capx:,.0f}-{dep:,.0f}={expected_ppe:,.0f} vs {curr_ppent:,.0f} (diff={ppe_diff:,.0f})")

    # CF reconciliation
    for r in frows:
        cfo = float(r["oancfq"])
        cfi = float(r["ivncfq"])
        cff = float(r["fincfq"])
        chechq = float(r["chechq"])
        cf_diff = abs(chechq - (cfo + cfi + cff))
        if cf_diff > 1:
            print(f"  Q{r['fqtr']}: CF recon FAIL: {cfo:,.0f}+{cfi:,.0f}+{cff:,.0f}={cfo+cfi+cff:,.0f} vs chechq={chechq:,.0f}")

    rev_min = min(float(r["saleq"]) for r in frows)
    rev_max = max(float(r["saleq"]) for r in frows)
    print(f"  Revenue: ${rev_min:,.0f} - ${rev_max:,.0f}")
    print(f"  Cash: ${float(frows[0]['cheq']):,.0f} -> ${float(frows[-1]['cheq']):,.0f}")
    print(f"  Price: ${float(frows[0]['prccq']):.2f} -> ${float(frows[-1]['prccq']):.2f}")
    print(f"  Total R&D: ${sum(float(r['xrdq']) for r in frows):,.0f}")
    print(f"  Total SGA: ${sum(float(r['xsgaq']) for r in frows):,.0f}")
    print(f"  Total Capex: ${sum(float(r['capxq']) for r in frows):,.0f}")
    print()

print("=== STALENESS CHECKS ===")
for fid in sorted(by_firm):
    frows = by_firm[fid]
    for i in range(1, len(frows)):
        if float(frows[i]["saleq"]) == float(frows[i-1]["saleq"]) and float(frows[i]["saleq"]) > 0:
            print(f"  {fid} Q{frows[i-1]['fqtr']}-Q{frows[i]['fqtr']}: IDENTICAL revenue ${float(frows[i]['saleq']):,.0f}")
        if (float(frows[i]["xrdq"]) == float(frows[i-1]["xrdq"]) and
            float(frows[i]["xsgaq"]) == float(frows[i-1]["xsgaq"])):
            print(f"  {fid} Q{frows[i-1]['fqtr']}-Q{frows[i]['fqtr']}: IDENTICAL R&D+SGA")

print()
print("=== ALWAYS-ZERO COLUMNS ===")
always_zero = []
for col in rows[0].keys():
    if col in ("run_id", "firm_id", "incarnation", "fyearq", "fqtr", "default_flag"):
        continue
    try:
        vals = [float(r[col]) for r in rows]
        if all(v == 0 for v in vals):
            always_zero.append(col)
    except ValueError:
        pass
print(f"  {always_zero}")

print()
print("=== RATIO ANALYSIS ===")
for fid in sorted(by_firm):
    frows = by_firm[fid]
    print(f"--- {fid} ---")
    for r in frows:
        rev = float(r["saleq"])
        cogs = float(r["cogsq"])
        xrd = float(r["xrdq"])
        xsga = float(r["xsgaq"])
        gm = (rev-cogs)/rev*100 if rev > 0 else 0
        rd_pct = xrd/rev*100 if rev > 0 else 0
        sga_pct = xsga/rev*100 if rev > 0 else 0
        atq = float(r["atq"])
        ltq = float(r["ltq"])
        leverage = ltq/max(1, atq-ltq)
        print(f"  Q{r['fqtr']}: GM={gm:.0f}% R&D/Rev={rd_pct:.0f}% SGA/Rev={sga_pct:.0f}% Leverage={leverage:.2f}x")
