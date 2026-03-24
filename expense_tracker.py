"""
Co-Parent Expense Tracker
Full CRUD via Supabase — both parents can add, edit, and settle expenses.
"""

import streamlit as st
import pandas as pd
from datetime import datetime, date
from supabase import create_client, Client

# ─── SUPABASE CLIENT ──────────────────────────────────────────────────────────

@st.cache_resource
def get_supabase() -> Client:
    url = st.secrets.get("SUPABASE_URL") or st.secrets.get("SUPABASE_URL")
    key = st.secrets.get("SUPABASE_KEY") or st.secrets.get("SUPABASE_KEY")
    if not url or not key:
        return None
    return create_client(url, key)

# ─── DATA OPS ─────────────────────────────────────────────────────────────────

def load_expenses(supabase: Client) -> pd.DataFrame:
    result = supabase.table("expenses").select("*").order("date", desc=True).execute()
    df = pd.DataFrame(result.data or [])
    if df.empty:
        return df
    # Normalize types
    df["date"]      = pd.to_datetime(df["date"], errors="coerce")
    df["amount"]    = pd.to_numeric(df["amount"], errors="coerce").fillna(0)
    df["split_pct"] = pd.to_numeric(df["split_pct"], errors="coerce").fillna(50)
    df["amount"]    = df["amount"].round(2)
    return df

def insert_expense(supabase: Client, row: dict) -> None:
    supabase.table("expenses").insert(row).execute()

def update_expense(supabase: Client, expense_id: int, row: dict) -> None:
    supabase.table("expenses").update(row).eq("id", expense_id).execute()

def delete_expense(supabase: Client, expense_id: int) -> None:
    supabase.table("expenses").delete().eq("id", expense_id).execute()

# ─── BALANCE CALCULATION ──────────────────────────────────────────────────────

YOU_LABELS  = ["you", "me", "dad", "dro", "dad's"]
WIFE_LABELS = ["wife", "her", "mom", "mother", "she"]

def calc_balances(df: pd.DataFrame) -> tuple[float, float]:
    you_owe, she_owes = 0.0, 0.0
    for _, row in df.iterrows():
        s = str(row.get("status", "")).lower()
        if s in ("settled", "cancelled", "canceled"):
            continue
        amt   = float(row["amount"])
        split = float(row.get("split_pct", 50)) / 100.0
        p     = str(row.get("paid_by", "")).lower()
        if "both" in p:
            continue
        if any(l in p for l in YOU_LABELS):
            she_owes += amt * (1 - split)
        elif any(l in p for l in WIFE_LABELS):
            you_owe  += amt * split
    return round(you_owe, 2), round(she_owes, 2)

# ─── PAGE ─────────────────────────────────────────────────────────────────────

st.set_page_config(page_title="Co-Parent Expense Tracker", page_icon="🧾", layout="centered")

# ── Identity selector ──
if "identity" not in st.session_state:
    st.session_state["identity"] = None

st.title("🧾 Co-Parent Expense Tracker")

if st.session_state["identity"] is None:
    st.subheader("👋 Who's using the app?")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("👤 I'm Dad / Me", use_container_width=True):
            st.session_state["identity"] = "you"
            st.rerun()
    with col2:
        if st.button("👤 I'm Mom / Wife", use_container_width=True):
            st.session_state["identity"] = "wife"
            st.rerun()
    st.stop()

identity = st.session_state["identity"]
me_label  = "👤 Me (Dad)" if identity == "you" else "👤 Me (Mom)"
other_label = "💁 Wife" if identity == "you" else "💁 Dad"

st.divider()

# ── Supabase init ──
supabase = get_supabase()
if supabase is None:
    st.error("❌ Supabase not connected. Check your app secrets (SUPABASE_URL + SUPABASE_KEY).")
    st.stop()

# ── Load data ──
try:
    df = load_expenses(supabase)
except Exception as e:
    st.error(f"❌ Could not load data: {e}")
    df = pd.DataFrame()

# ── BALANCE CARDS ──
if not df.empty:
    you_owe, she_owes = calc_balances(df)
    net = she_owes - you_owe
else:
    you_owe, she_owes, net = 0.0, 0.0, 0.0

c1, c2 = st.columns(2)
with c1:
    (st.error if you_owe > 0 else st.success)(f"💸 You owe: **${you_owe:,.2f}**")
with c2:
    (st.success if she_owes > 0 else st.info)(f"💰 {other_label.split()[1]} owes you: **${she_owes:,.2f}**")

if net > 0.05:
    st.markdown(f"### 🎉 Net: **You are owed ${net:,.2f}**")
elif net < -0.05:
    st.markdown(f"### ⚠️ Net: **You owe ${abs(net):,.2f}**")
else:
    st.markdown("### ⚖️ All settled up!")

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
#  ADD / EDIT EXPENSE
# ══════════════════════════════════════════════════════════════════════════════

st.subheader("➕ Add Expense")

with st.expander("✏️ New expense", expanded=True):
    with st.form("add_form", clear_on_submit=True):
        paid_by = st.radio("Who paid?", ["Me", other_label.split()[1], "Both"], horizontal=True)
        date_in  = st.date_input("Date", value=date.today())
        desc     = st.text_input("Description", placeholder="e.g. Kids shoes from Target")
        cat      = st.selectbox("Category", [
            "Groceries","Kids","Medical","Transportation",
            "Entertainment","Clothing","School","Other"
        ])
        amt      = st.number_input("Amount ($)", min_value=0.01, step=0.01, format="%.2f")
        split    = st.slider("Your split %", 0, 100, 50, step=5)
        status   = st.selectbox("Status", ["active", "settled"])
        notes    = st.text_input("Notes (optional)")

        submitted = st.form_submit_button("💾 Save Expense", use_container_width=True)

    if submitted:
        if not desc.strip():
            st.warning("⚠️ Description required.")
        elif amt <= 0:
            st.warning("⚠️ Amount must be > $0.")
        else:
            row = {
                "date"       : str(date_in),
                "description": desc.strip(),
                "category"   : cat,
                "amount"     : round(float(amt), 2),
                "paid_by"    : paid_by,
                "split_pct"  : float(split),
                "status"     : status,
                "notes"      : notes.strip() if notes.strip() else None,
            }
            try:
                insert_expense(supabase, row)
                st.success("✅ Expense saved!")
                st.cache_data.clear()
                st.rerun()
            except Exception as e:
                st.error(f"❌ Save failed: {e}")

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
#  EXPENSE LOG (with inline edit / delete)
# ══════════════════════════════════════════════════════════════════════════════

st.subheader("📋 Expense Log" + (f" ({len(df)} rows)" if not df.empty else ""))

if df.empty:
    st.info("No expenses yet. Add one above!")
else:
    # Filters
    c_d1, c_d2, c_cat, c_stat = st.columns(4)
    with c_d1:
        start = st.date_input("From", value=df["date"].min().date() if len(df) else None)
    with c_d2:
        end   = st.date_input("To",   value=df["date"].max().date() if len(df) else None)
    with c_cat:
        cats = ["All"] + sorted(df["category"].dropna().unique().tolist())
        cat_f = st.selectbox("Category", cats)
    with c_stat:
        stats = ["All", "active", "settled"]
        stat_f = st.selectbox("Status", stats)

    mask = (
        (df["date"] >= pd.Timestamp(start)) &
        (df["date"] <= pd.Timestamp(end))   &
        (df["category"] == cat_f if cat_f != "All" else True) &
        (df["status"]   == stat_f if stat_f != "All" else True)
    )
    filtered = df[mask].sort_values("date", ascending=False).reset_index(drop=True)

    st.dataframe(
        filtered[["id","date","description","category","amount","paid_by","split_pct","status","notes"]]
        .rename(columns={
            "id"        : "ID",
            "date"      : "Date",
            "description": "Description",
            "category"  : "Category",
            "amount"    : "Amount ($)",
            "paid_by"   : "Paid by",
            "split_pct" : "Split (%)",
            "status"    : "Status",
            "notes"     : "Notes",
        }),
        use_container_width=True,
        hide_index=True,
    )

    # ── Inline EDIT ──
    st.divider()
    st.subheader("✏️ Edit / Settle Expense")

    expense_ids = filtered["id"].tolist()
    if not expense_ids:
        st.info("No expenses to edit.")
    else:
        edit_id = st.selectbox("Select expense by ID", [""] + expense_ids, format_func=lambda x: f"#{x}" if x else "—")

        if edit_id:
            row = filtered[filtered["id"] == edit_id].iloc[0]

            with st.form(f"edit_form_{edit_id}", clear_on_submit=False):
                e_date  = st.date_input("Date", value=pd.to_datetime(row["date"]).date())
                e_desc  = st.text_input("Description", value=row["description"])
                e_cat   = st.selectbox("Category", [
                    "Groceries","Kids","Medical","Transportation",
                    "Entertainment","Clothing","School","Other"
                ], index=[
                    "Groceries","Kids","Medical","Transportation",
                    "Entertainment","Clothing","School","Other"
                ].index(row["category"]) if row["category"] in [
                    "Groceries","Kids","Medical","Transportation",
                    "Entertainment","Clothing","School","Other"
                ] else 0)
                e_amt   = st.number_input("Amount ($)", value=float(row["amount"]), min_value=0.01, step=0.01, format="%.2f")
                e_payer = st.selectbox("Who paid?", ["Me", other_label.split()[1], "Both"],
                                       index=["Me", other_label.split()[1], "Both"].index(row["paid_by"]) if row["paid_by"] in ["Me", other_label.split()[1], "Both"] else 0)
                e_split = st.slider("Your split %", 0, 100, int(row["split_pct"]), step=5)
                e_stat  = st.selectbox("Status", ["active","settled"],
                                        index=["active","settled"].index(row["status"]) if row["status"] in ["active","settled"] else 0)
                e_notes = st.text_input("Notes", value=row["notes"] or "")

                col_upd, col_del = st.columns(2)
                with col_upd:
                    upd_submitted = st.form_submit_button("💾 Update", use_container_width=True)
                with col_del:
                    del_submitted = st.form_submit_button("🗑️ Delete", use_container_width=True,
                                                          type="primary" if False else "secondary")

                if upd_submitted:
                    updated = {
                        "date"       : str(e_date),
                        "description": e_desc.strip(),
                        "category"   : e_cat,
                        "amount"     : round(float(e_amt), 2),
                        "paid_by"    : e_payer,
                        "split_pct"  : float(e_split),
                        "status"     : e_stat,
                        "notes"      : e_notes.strip() if e_notes.strip() else None,
                    }
                    try:
                        update_expense(supabase, int(edit_id), updated)
                        st.success("✅ Updated!")
                        st.cache_data.clear()
                        st.rerun()
                    except Exception as e:
                        st.error(f"❌ Update failed: {e}")

                if del_submitted:
                    try:
                        delete_expense(supabase, int(edit_id))
                        st.success("🗑️ Deleted!")
                        st.cache_data.clear()
                        st.rerun()
                    except Exception as e:
                        st.error(f"❌ Delete failed: {e}")

st.divider()

# ── Monthly summary ──
if not df.empty:
    st.subheader("📅 Monthly Summary")
    monthly = (
        filtered
        .groupby(filtered["date"].dt.to_period("M"))["amount"]
        .sum()
        .reset_index()
    )
    monthly["date"] = monthly["date"].astype(str)
    monthly = monthly.sort_values("date", ascending=False)
    monthly.columns = ["Month", "Total ($)"]
    st.dataframe(monthly, use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("📂 By Category")
    cat_sum = (
        filtered
        .groupby("category")["amount"]
        .agg(["sum","count"])
        .reset_index()
        .rename(columns={"sum":"Total ($)","count":"# Entries"})
        .sort_values("Total ($)", ascending=False)
    )
    st.dataframe(cat_sum, use_container_width=True, hide_index=True)

# ── Identity reset ──
with st.expander("🔄 Switch parent"):
    if st.button("Swap identity (change who's using the app)"):
        st.session_state["identity"] = None
        st.rerun()

st.caption("Built with Streamlit · Data via Supabase")
