"""Audit v7 simulation - read-only analysis."""
import csv
import os
from collections import defaultdict

OUT = "D:/Dropbox/current/LLM_firms/outputs/run_1776642975"

def f(x):
    try:
        return float(x) if x not in ("", None) else 0.0
    except Exception:
        return 0.0

# Load panel
with open(os.path.join(OUT, "compustat_q.csv")) as fh:
    rows = list(csv.DictReader(fh))

# Sort by firm, datadate
rows.sort(key=lambda r: (r["firm_id"], r["datadate"]))

print("=" * 80)
print("Q1: BS VIOLATIONS — atq vs ltq + ceqq")
print("=" * 80)
violations = []
for r in rows:
    atq = f(r["atq"]); ltq = f(r["ltq"]); ceqq = f(r["ceqq"])
    resid = atq - (ltq + ceqq)
    if abs(resid) > 1.0:
        violations.append((r, resid))
print(f"violations: {len(violations)}/{len(rows)}")
for r, resid in violations:
    print(f"\n{r['firm_id']} {r['datadate']} fy{r['fyearq']}q{r['fqtr']} default={r['default_flag']}")
    print(f"  atq={f(r['atq']):,.0f} ltq={f(r['ltq']):,.0f} ceqq={f(r['ceqq']):,.0f} resid={resid:,.2f}")
    print(f"  ASSETS: cheq={f(r['cheq']):,.0f} rectq={f(r['rectq']):,.0f} invtq={f(r['invtq']):,.0f} ppent={f(r['ppentq']):,.0f} actq={f(r['actq']):,.0f} gdwlq={f(r['gdwlq']):,.0f}")
    print(f"  LIABS: apq={f(r['apq']):,.0f} xaccq={f(r['xaccq']):,.0f} dlcq={f(r['dlcq']):,.0f} dlttq={f(r['dlttq']):,.0f} lctq={f(r['lctq']):,.0f} drcq={f(r['drcq']):,.0f} txditcq={f(r['txditcq']):,.0f} legal={f(r['legal_reserve_bs']):,.0f} pens={f(r['pension_liability_bs']):,.0f}")
    print(f"  EQUITY: cstkq={f(r['cstkq']):,.0f} apicq={f(r['apicq']):,.0f} req={f(r['req']):,.0f} tstkq={f(r['tstkq']):,.0f} seqq={f(r['seqq']):,.0f}")
    # liability sum check
    lsum = f(r['apq']) + f(r['xaccq']) + f(r['dlcq']) + f(r['dlttq']) + f(r['drcq']) + f(r['txditcq']) + f(r['legal_reserve_bs']) + f(r['pension_liability_bs'])
    print(f"  liab_components_sum={lsum:,.0f} (vs ltq={f(r['ltq']):,.0f} delta={lsum - f(r['ltq']):,.0f})")
    # equity components
    esum = f(r['cstkq']) + f(r['apicq']) + f(r['req']) - f(r['tstkq'])
    print(f"  equity_components_sum={esum:,.0f} (vs ceqq={f(r['ceqq']):,.0f} delta={esum - f(r['ceqq']):,.0f})")

print("\n" + "=" * 80)
print("Q2: NEGATIVE CASH")
print("=" * 80)
for r in rows:
    cheq = f(r["cheq"])
    if cheq < -0.01:
        print(f"{r['firm_id']} {r['datadate']} default={r['default_flag']} cheq={cheq:,.2f} req={f(r['req']):,.0f} ceqq={f(r['ceqq']):,.0f}")

print("\n" + "=" * 80)
print("Q7: CFO RECONCILIATION  delta_cheq vs oancf+ivncf+fincf")
print("=" * 80)
by_firm = defaultdict(list)
for r in rows:
    by_firm[r["firm_id"]].append(r)
for fid, frows in by_firm.items():
    frows.sort(key=lambda x: x["datadate"])
    prev_cash = None
    for r in frows:
        cheq = f(r["cheq"])
        if prev_cash is not None:
            d = cheq - prev_cash
            cf = f(r["oancfq"]) + f(r["ivncfq"]) + f(r["fincfq"])
            diff = d - cf
            if abs(diff) > 10000:
                print(f"  {fid} {r['datadate']} delta_cash={d:,.0f} cf_sum={cf:,.0f} diff={diff:,.0f}  default={r['default_flag']}")
        prev_cash = cheq

print("\n" + "=" * 80)
print("Q4: SBC/APIC trend")
print("=" * 80)
for fid, frows in by_firm.items():
    frows.sort(key=lambda x: x["datadate"])
    print(f"\n{fid}:")
    for r in frows:
        print(f"  {r['datadate']} fy{r['fyearq']}q{r['fqtr']} cstk={f(r['cstkq']):,.0f} apic={f(r['apicq']):,.0f} re={f(r['req']):,.0f} ceqq={f(r['ceqq']):,.0f} default={r['default_flag']}")

print("\n" + "=" * 80)
print("Q5: REFRESH consistency — rectq+invtq+cheq <= actq")
print("=" * 80)
for r in rows:
    s = f(r['cheq']) + f(r['rectq']) + f(r['invtq'])
    if s > f(r['actq']) + 1.0:
        print(f"  VIOLATION {r['firm_id']} {r['datadate']}: che+rect+invt={s:,.0f} > actq={f(r['actq']):,.0f}")

print("\n" + "=" * 80)
print("Q5b: firm_1 raised debt — show all fields per quarter")
print("=" * 80)
for r in by_firm.get("firm_1", []):
    print(f"  {r['datadate']} cheq={f(r['cheq']):,.0f} rect={f(r['rectq']):,.0f} invt={f(r['invtq']):,.0f} actq={f(r['actq']):,.0f} ppent={f(r['ppentq']):,.0f} atq={f(r['atq']):,.0f} dlcq={f(r['dlcq']):,.0f} dlttq={f(r['dlttq']):,.0f} apq={f(r['apq']):,.0f} ltq={f(r['ltq']):,.0f}")
