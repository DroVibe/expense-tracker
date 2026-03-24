"""
Co-Parent Expense Tracker
Reads live from Google Sheets (Form → Sheet → CSV export).
No API keys needed. Form handles writes; this app handles reading & analytics.
"""

import streamlit as st
import pandas as pd
import urllib.request
import io
from datetime import datetime, date

# ─── CONFIG ───────────────────────────────────────────────────────────────────

SHEET_ID  = "1wcpGQtmUzUlvCQ2fMTWNKoszR3NyIWHAGRqQl17aXZY"
CSV_URL   = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv"
FORM_URL  = "https://docs.google.com/forms/d/18g2QqE8vRpGkSuXmu-7q9TIcKmSXCZONozoftDtf0HM/viewform"
FORM_FILL = "https://docs.google.com/forms/d/e/1FAIpQLSdGSEWi58ZWN6C1c0eDheG9qR3pMHBTmXbC1Q/formResponse"

# ─── COLUMN MAP (raw → clean) ─────────────────────────────────────────────────
# Google Sheet exports sometimes preserve trailing spaces in column names.
COLUMN_MAP = {
    "Timestamp"   : "Timestamp",
    "Date"        : "Date",
    "Description ": "Description",
    "Category"    : "Category",
    "Amount"      : "Amount",
    "Paid by "    : "Paid_by",
    "Split %"     : "Split_pct",
    "Status"      : "Status",
    "Notes"       : "Notes",
}

YOU_LABELS  = ["you", "me", "dad", "dro", "dad's"]
WIFE_LABELS = ["wife", "her", "mom", "mother", "she"]

# ─── DATA LOADING ─────────────────────────────────────────────────────────────

@st.cache_data(ttl=60)
def load_data() -> pd.DataFrame:
    try:
        with urllib.request.urlopen(CSV_URL, timeout=15) as resp:
            raw = resp.read().decode("utf-8")
    except Exception as e:
        st.error(f"❌ Could not reach Google Sheet: {e}")
        return pd.DataFrame()

    df = pd.read_csv(io.StringIO(raw))
    df = df.rename(columns=COLUMN_MAP)

    for col in df.columns:
        if df[col].dtype == object:
            df[col] = df[col].str.strip()

    df["Amount"] = pd.to_numeric(
        df["Amount"].astype(str).str.replace(r"[$,]", "", regex=True),
        errors="coerce"
    ).fillna(0)

    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df["Paid_by_clean"] = df["Paid_by"].str.lower()
    df["Split_pct"] = pd.to_numeric(
        df["Split_pct"].astype(str).str.replace("%", "").str.strip(),
        errors="coerce"
    ).fillna(50)

    return df

# ─── BALANCE CALCULATION ──────────────────────────────────────────────────────

def calc_balances(df: pd.DataFrame) -> tuple[float, float]:
    you_owe, she_owes = 0.0, 0.0
    for _, row in df.iterrows():
        if row.get("Status", "").lower() in ("settled", "cancelled", "canceled"):
            continue
        amt  = row["Amount"]
        split = row["Split_pct"] / 100.0
        p     = row.get("Paid_by_clean", "")
        if "both" in p:
            continue
        if any(l in p for l in YOU_LABELS):
            she_owes += amt * (1 - split)
        elif any(l in p for l in WIFE_LABELS):
            you_owe  += amt * split
    return round(you_owe, 2), round(she_owes, 2)

# ─── STREAMLIT PAGE ───────────────────────────────────────────────────────────

st.set_page_config(page_title="Co-Parent Expense Tracker", page_icon="🧾", layout="centered")

st.title("🧾 Co-Parent Expense Tracker")
st.caption("Live data from Google Sheet · Refreshes every 60 s")

# ── Reload ──
if st.button("🔄 Refresh Data"):
    st.cache_data.clear()
    st.rerun()

df = load_data()
if df.empty:
    st.stop()

# ── BALANCE CARDS ──
you_owe, she_owes = calc_balances(df)
net = she_owes - you_owe

c1, c2 = st.columns(2)
with c1:
    (st.error if you_owe > 0 else st.success)(f"💸 You owe: **${you_owe:,.2f}**")
with c2:
    (st.success if she_owes > 0 else st.info)(f"💰 She owes you: **${she_owes:,.2f}**")

if net > 0.05:
    st.markdown(f"### 🎉 Net: **You are owed ${net:,.2f}**")
elif net < -0.05:
    st.markdown(f"### ⚠️ Net: **You owe ${abs(net):,.2f}**")
else:
    st.markdown("### ⚖️ All settled up!")

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
#  ADD EXPENSE — IN-APP FORM (writes via Google Form link)
# ══════════════════════════════════════════════════════════════════════════════

st.subheader("➕ Add Expense")

with st.expander("✏️ Fill in the form below & submit", expanded=True):

    with st.form("add_expense_form", clear_on_submit=True):
        st.write("**Who paid?**")
        paid_by = st.radio(
            "Paid by",
            ["You", "Wife", "Both"],
            horizontal=True,
            label_visibility="collapsed"
        )

        date_val = st.date_input("Date", value=date.today())
        desc     = st.text_input("Description", placeholder="e.g. Kids shoes from Target")
        cat      = st.selectbox("Category", [
            "Groceries", "Kids", "Medical", "Transportation",
            "Entertainment", "Clothing", "School", "Other"
        ])
        amt      = st.number_input("Amount ($)", min_value=0.0, step=0.01, format="%.2f")
        split    = st.slider("Your split %", 0, 100, 50, step=5)
        status   = st.selectbox("Status", ["Active", "Settled"])
        notes    = st.text_input("Notes (optional)", placeholder="Any extra details…")

        col_a, col_b = st.columns(2)
        with col_a:
            submitted = st.form_submit_button("📤 Submit via Google Form", use_container_width=True)
        with col_b:
            st.write("")
            st.markdown(
                f"[🔗 Open Google Form directly]({FORM_URL})",
                unsafe_allow_html=True
            )

    if submitted:
        if not desc.strip():
            st.warning("⚠️ Description is required.")
        elif amt <= 0:
            st.warning("⚠️ Amount must be greater than $0.")
        else:
            # Build pre-fill URL for the Google Form
            # entry IDs must match the actual form fields.
            # We open the form with a pre-fill prompt so the user just confirms.
            st.session_state["pending"] = {
                "date"     : str(date_val),
                "desc"     : desc.strip(),
                "cat"      : cat,
                "amt"      : f"{amt:.2f}",
                "paid_by"  : paid_by,
                "split"    : str(split),
                "status"   : status,
                "notes"    : notes.strip(),
            }
            st.rerun()

# Show pending entry with direct Google Form link
if "pending" in st.session_state:
    p = st.session_state.pop("pending")
    st.success("✅ Entry ready! Click the link below to submit to Google Sheet:")
    cols = st.columns([1, 3])
    with cols[0]:
        st.write(f"**{p['desc']}** — ${p['amt']} ({p['cat']})")
        st.write(f"Paid by: {p['paid_by']} · Split: {p['split']}%")
    with cols[1]:
        st.write("Open & fill:")
        st.link_button("📋 Open Google Form to Submit", FORM_URL, type="primary")
    st.info("Fill the Google Form with the details above, then click 'Submit'. It will appear in this app within 60 seconds.")

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
#  EXPENSE LOG
# ══════════════════════════════════════════════════════════════════════════════

st.subheader("🔍 Filter Expenses")

c_d1, c_d2, c_cat, c_payer, c_stat = st.columns(5)
with c_d1:
    start = st.date_input("From", value=df["Date"].min().date() if len(df) else None)
with c_d2:
    end   = st.date_input("To",   value=df["Date"].max().date() if len(df) else None)
with c_cat:
    cats = ["All"] + sorted(df["Category"].dropna().unique().tolist())
    cat_f = st.selectbox("Category", cats)
with c_payer:
    payers = ["All"] + sorted(df["Paid_by"].dropna().unique().tolist())
    payer_f = st.selectbox("Paid by", payers)
with c_stat:
    stats  = ["All"] + sorted(df["Status"].dropna().unique().tolist())
    stat_f = st.selectbox("Status", stats)

mask = (
    (df["Date"] >= pd.Timestamp(start)) &
    (df["Date"] <= pd.Timestamp(end))   &
    (df["Category"] == cat_f if cat_f != "All" else True) &
    (df["Paid_by"]   == payer_f if payer_f != "All" else True) &
    (df["Status"]    == stat_f  if stat_f  != "All" else True)
)
filtered = df[mask].sort_values("Date", ascending=False)

st.divider()
st.subheader(f"📋 Expense Log ({len(filtered)} rows)")

display = filtered[["Date","Description","Category","Amount","Paid_by","Split_pct","Status","Notes"]].rename(columns={
    "Amount"   : "Amount ($)",
    "Paid_by"  : "Paid by",
    "Split_pct": "Split (%)",
})
st.dataframe(display, use_container_width=True, hide_index=True)

# ── Monthly summary ──
st.divider()
st.subheader("📅 Monthly Summary")
monthly = (
    filtered
    .groupby(filtered["Date"].dt.to_period("M"))["Amount"]
    .sum()
    .reset_index()
)
monthly["Date"] = monthly["Date"].astype(str)
monthly = monthly.sort_values("Date", ascending=False)
monthly.columns = ["Month", "Total ($)"]
st.dataframe(monthly, use_container_width=True, hide_index=True)

# ── Category breakdown ──
st.divider()
st.subheader("📂 By Category")
cat_sum = (
    filtered
    .groupby("Category")["Amount"]
    .agg(["sum","count"])
    .reset_index()
    .rename(columns={"sum":"Total ($)","count":"# Entries"})
    .sort_values("Total ($)", ascending=False)
)
st.dataframe(cat_sum, use_container_width=True, hide_index=True)

st.caption("Built with Streamlit · Data via Google Sheets CSV · No API key required")
