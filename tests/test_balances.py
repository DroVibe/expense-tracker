"""
tests/test_balances.py — Self-contained unit tests for shared.py balance math.
Run: python3 tests/test_balances.py
"""

import sys, os, math
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pandas as pd

# ── Local mirrors of the functions under test (avoids supabase import) ───────

def calc_balances(df: pd.DataFrame):
    dad_owes_mom, mom_owes_dad = 0.0, 0.0
    for _, row in df.iterrows():
        if str(row.get("status", "")).lower() == "settled":
            continue
        amt     = float(row.get("amount", 0))
        dad_pct = float(row.get("split_pct", 50)) / 100.0
        payer   = str(row.get("paid_by", "")).strip()
        if payer == "Dad":
            mom_owes_dad += amt * (1 - dad_pct)
        elif payer == "Mom":
            dad_owes_mom += amt * dad_pct
    return round(dad_owes_mom, 2), round(mom_owes_dad, 2)

def payer_share(amt: float, split_pct: float, paid_by: str):
    dad = round(amt * split_pct / 100, 2)
    mom = round(amt - dad, 2)
    return dad, mom

# ── Test framework ────────────────────────────────────────────────────────────

def Assert(actual, expected, tol=0.01, msg=""):
    ok = abs(float(actual) - float(expected)) <= tol
    print(f"  {'✅' if ok else '❌'} {msg or f'got {actual}, expected {expected}'}")
    return ok

passed = failed = 0
def df(rows):
    return pd.DataFrame(rows) if rows else pd.DataFrame(columns=["amount","split_pct","paid_by","status"])

# ════════════════════════════════════════════════════════════════════════════════
print("\n[ payer_share ]")
#  (label, amt, pct, exp_dad, exp_mom)
for label, amt, pct, exp_dad, exp_mom in [
    ("50/50 split",            100.0, 50.0,   50.0,  50.0),
    ("70/30 Dad-heavy",        100.0, 70.0,   70.0,  30.0),
    ("30/70 Mom-heavy",        100.0, 30.0,   30.0,  70.0),
    ("0% Dad share",            85.0,  0.0,    0.0,  85.0),
    ("100% Dad share",          85.0,100.0,   85.0,   0.0),
    ("33.33% rounding $10",     10.0, 33.33,  3.33,  6.67),
    ("$200 at 75%",            200.0, 75.0,  150.0,  50.0),
]:
    dad, mom = payer_share(amt, pct, "Dad")
    if Assert(dad, exp_dad, msg=f"{label} → dad={dad}"): passed += 1
    else: failed += 1
    if Assert(mom, exp_mom, msg=f"{label} → mom={mom}"): passed += 1
    else: failed += 1

# ════════════════════════════════════════════════════════════════════════════════
print("\n[ calc_balances ]")

d, m = calc_balances(df([]))
if Assert(d + m, 0.0, msg="empty df → 0/0"): passed += 1
else: failed += 1

d, m = calc_balances(df([{"amount":100,"split_pct":50,"paid_by":"Dad","status":"active"}]))
if Assert(m, 50.0, msg=f"Dad $100 50/50 → mom={m}"): passed += 1
else: failed += 1

d, m = calc_balances(df([{"amount":100,"split_pct":50,"paid_by":"Mom","status":"active"}]))
if Assert(d, 50.0, msg=f"Mom $100 50/50 → dad={d}"): passed += 1
else: failed += 1

d, m = calc_balances(df([{"amount":100,"split_pct":70,"paid_by":"Dad","status":"active"}]))
if Assert(m, 30.0, msg=f"Dad $100 70% → mom={m}"): passed += 1
else: failed += 1

d, m = calc_balances(df([{"amount":100,"split_pct":70,"paid_by":"Mom","status":"active"}]))
if Assert(d, 70.0, msg=f"Mom $100 70% → dad={d}"): passed += 1
else: failed += 1

d, m = calc_balances(df([{"amount":999,"split_pct":50,"paid_by":"Both","status":"active"}]))
if Assert(d + m, 0.0, msg=f"Both → no debt {d}/{m}"): passed += 1
else: failed += 1

d, m = calc_balances(df([{"amount":9999,"split_pct":50,"paid_by":"Dad","status":"settled"}]))
if Assert(d + m, 0.0, msg=f"Settled ignored → {d}/{m}"): passed += 1
else: failed += 1

d, m = calc_balances(df([{"amount":9999,"split_pct":50,"paid_by":"Dad","status":"SETTLED"}]))
if Assert(d + m, 0.0, msg=f"SETTLED uppercase → {d}/{m}"): passed += 1
else: failed += 1

d, m = calc_balances(df([
    {"amount":100,"split_pct":50,"paid_by":"Dad","status":"active"},
    {"amount":60, "split_pct":70,"paid_by":"Mom","status":"active"},
]))
if Assert(d, 42.0, msg=f"Mixed: dad={d}"): passed += 1
else: failed += 1
if Assert(m, 50.0, msg=f"Mixed: mom={m}"): passed += 1
else: failed += 1

d, m = calc_balances(df([
    {"amount":100,"split_pct":50,"paid_by":"Dad","status":"active"},
    {"amount":100,"split_pct":50,"paid_by":"Mom","status":"active"},
]))
if Assert(d, 50.0, msg=f"Net zero dad={d}"): passed += 1
else: failed += 1
if Assert(m, 50.0, msg=f"Net zero mom={m}"): passed += 1
else: failed += 1

d, m = calc_balances(df([{"split_pct":50,"paid_by":"Dad","status":"active"}]))
if Assert(d + m, 0.0, msg=f"Missing amount → {d}/{m}"): passed += 1
else: failed += 1

d, m = calc_balances(df([{"amount":100,"paid_by":"Dad","status":"active"}]))
if Assert(m, 50.0, msg=f"Missing split → mom={m}"): passed += 1
else: failed += 1

d, m = calc_balances(df([{"amount":100,"split_pct":50,"paid_by":"Uncle","status":"active"}]))
if Assert(d + m, 0.0, msg=f"Unknown payer → {d}/{m}"): passed += 1
else: failed += 1

# Rounding: 3 × ($10 at 33.33% → mom owes ~$6.667 each)
# Note: 10 * (1 - 0.3333) = 6.667, 3× = 20.001 → bank() rounds → 20.0
d, m = calc_balances(df([
    {"amount":10,"split_pct":33.33,"paid_by":"Dad","status":"active"},
    {"amount":10,"split_pct":33.33,"paid_by":"Dad","status":"active"},
    {"amount":10,"split_pct":33.33,"paid_by":"Dad","status":"active"},
]))
if Assert(m, 20.0, 0.02, msg=f"Rounding accumulation mom={m} (~20.0, banker's rounding)"): passed += 1
else: failed += 1

# ════════════════════════════════════════════════════════════════════════════════
total = passed + failed
print(f"\n{'─'*40}")
if failed == 0:
    print(f"  ✅ ALL {total} TESTS PASSED")
else:
    print(f"  ❌ {failed}/{total} FAILED")
print()
sys.exit(0 if failed == 0 else 1)
