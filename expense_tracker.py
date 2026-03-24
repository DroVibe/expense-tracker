"""
Co-Parent Expense Tracker
Reads live from Google Sheets (Form → Sheet → CSV export).
No API keys needed. Form handles writes; this app handles reading & analytics.
"""

import streamlit as st
import pandas as pd
import urllib.request
import io
from datetime import datetime

# ─── CONFIG ──────────────────────────────────────────────────────────────────

SHEET_ID   = "1wcpGQtmUzUlvCQ2fMTWNKoszR3NyIWHAGRqQl17aXZY"
CSV_URL    = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv"
GOOGLE_FORM_URL = "https://docs.google.com/forms/d/18g2QqE8vRpGkSuXmu-7q9TIcKmSXCZONozoftDtf0HM/viewform"

# ─── COLUMN MAP (raw → clean) ────────────────────────────────────────────────
# Some columns have trailing/leading spaces in the Google Sheet export.
COLUMN_MAP = {
    "Timestamp"    : "Timestamp",
    "Date"         : "Date",
    "Description " : "Description",   # note trailing space
    "Category"     : "Category",
    "Amount"       : "Amount",
    "Paid by "     : "Paid_by",        # note trailing space
    "Split %"      : "Split_pct",      # note space before %
    "Status"       : "Status",
    "Notes"        : "Notes",
}

# Payer labels that appear in the sheet
YOU_LABELS  = ["you", "me", "dad", "dad's", "dro"]
WIFE_LABELS = ["wife", "her", "mom", "mother", "she"]

# ─── DATA LOADING ─────────────────────────────────────────────────────────────

@st.cache_data(ttl=60)   # cache for 60 seconds, so we don't hammer Google
def load_data() -> pd.DataFrame:
    """Fetch and parse the Google Sheet CSV export."""
    try:
        with urllib.request.urlopen(CSV_URL, timeout=15) as response:
            raw = response.read().decode("utf-8")
    except Exception as e:
        st.error(f"❌ Could not reach Google Sheet: {e}")
        return pd.DataFrame()

    # Read CSV — Google Viz returns a quirky header line; parse normally
    df = pd.read_csv(io.StringIO(raw))

    # Rename columns to clean names
    df = df.rename(columns=COLUMN_MAP)

    # Strip whitespace from string columns
    for col in df.columns:
        if df[col].dtype == object:
            df[col] = df[col].str.strip()

    # Parse Amount
    df["Amount"] = pd.to_numeric(
        df["Amount"].astype(str).str.replace(r"[$,]", "", regex=True),
        errors="coerce"
    ).fillna(0)

    # Parse Date
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")

    # Normalize Paid_by to lowercase for comparison
    df["Paid_by_clean"] = df["Paid_by"].str.lower()

    # Parse Split % — default to 50 if missing or invalid
    df["Split_pct"] = pd.to_numeric(
        df["Split_pct"].astype(str).str.replace("%", "").str.strip(),
        errors="coerce"
    ).fillna(50)

    return df


def is_you(payer: str) -> bool:
    return any(label in payer.lower() for label in YOU_LABELS)

def is_wife(payer: str) -> bool:
    return any(label in payer.lower() for label in WIFE_LABELS)


# ─── BALANCE CALCULATION ──────────────────────────────────────────────────────

def calculate_balances(df: pd.DataFrame) -> dict:
    """
    Returns dict:
      you_owe    = amount YOU owe Wife
      she_owes   = amount Wife owes YOU
    """
    you_owe  = 0.0
    she_owes = 0.0

    for _, row in df.iterrows():
        if row.get("Status", "").lower() not in ["active", "unpaid", "pending", ""]:
            continue  # skip settled / cancelled rows

        amount      = row["Amount"]
        split_pct   = row["Split_pct"] / 100.0  # e.g. 50 → 0.5
        payer_clean = row.get("Paid_by_clean", "")

        # "Both" → split equally, net = 0
        if "both" in payer_clean:
            continue

        your_share   = amount * split_pct
        her_share    = amount * (1 - split_pct)

        if is_you(payer_clean):
            # You paid full amount; Wife should reimburse her share
            she_owes += her_share
        elif is_wife(payer_clean):
            # Wife paid full amount; You reimburse your share
            you_owe  += your_share
        # Unknown payer → skip safely

    return {
        "you_owe" : round(you_owe, 2),
        "she_owes": round(she_owes, 2),
    }


# ─── STREAMLIT UI ─────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Co-Parent Expense Tracker",
    page_icon="🧾",
    layout="centered",
)

st.title("🧾 Co-Parent Expense Tracker")
st.caption("Live data from Google Sheet · Updated every 60 s")

# ── Reload button ──
if st.button("🔄 Refresh Data"):
    st.cache_data.clear()
    st.rerun()

# ── Load data ──
df = load_data()

if df.empty:
    st.stop()

# ── TOP BALANCE CARDS ──
balances = calculate_balances(df)
net_you  = balances["she_owes"] - balances["you_owe"]   # positive = she owes you

col1, col2 = st.columns(2)

with col1:
    if balances["you_owe"] > 0:
        st.error(f"💸 You owe: **${balances['you_owe']:,.2f}**")
    else:
        st.success(f"✅ You owe: **$0.00**")

with col2:
    if balances["she_owes"] > 0:
        st.success(f"💰 She owes you: **${balances['she_owes']:,.2f}**")
    else:
        st.info(f"📭 She owes you: **$0.00**")

if net_you > 0.05:
    st.markdown(f"### 🎉 Net: **You are owed $${net_you:,.2f}**")
elif net_you < -0.05:
    st.markdown(f"### ⚠️ Net: **You owe $${abs(net_you):,.2f}**")
else:
    st.markdown("### ⚖️ Net: **All settled up!**")

st.divider()

# ── ADD EXPENSE ──
st.subheader("➕ Add Expense")
st.markdown(
    f"**[Open Google Form →]({GOOGLE_FORM_URL})**",
    unsafe_allow_html=True,
)
st.caption("Fill the form to log a new expense. It appears here automatically.")

st.divider()

# ── FILTERS ──
st.subheader("🔍 Filter Expenses")

col_date1, col_date2, col_cat, col_payer, col_status = st.columns(5)

with col_date1:
    start_date = st.date_input("From", value=df["Date"].min().date() if len(df) else None)

with col_date2:
    end_date = st.date_input("To",   value=df["Date"].max().date() if len(df) else None)

with col_cat:
    cats = ["All"] + sorted(df["Category"].dropna().unique().tolist())
    cat_filter = st.selectbox("Category", cats)

with col_payer:
    payers = ["All"] + sorted(df["Paid_by"].dropna().unique().tolist())
    payer_filter = st.selectbox("Paid by", payers)

with col_status:
    statuses = ["All"] + sorted(df["Status"].dropna().unique().tolist())
    status_filter = st.selectbox("Status", statuses)

# Apply filters
mask = (
    (df["Date"] >= pd.Timestamp(start_date)) &
    (df["Date"] <= pd.Timestamp(end_date))   &
    (df["Category"] == cat_filter if cat_filter != "All" else True) &
    (df["Paid_by"]   == payer_filter if payer_filter != "All" else True) &
    (df["Status"]    == status_filter if status_filter != "All" else True)
)
filtered = df[mask].copy().sort_values("Date", ascending=False)

st.divider()

# ── EXPENSE TABLE ──
st.subheader(f"📋 Expense Log ({len(filtered)} rows)")

display_cols = ["Date", "Description", "Category", "Amount", "Paid_by",
                "Split_pct", "Status", "Notes"]

# Rename for display
display = filtered[display_cols].rename(columns={
    "Date"       : "Date",
    "Description": "Description",
    "Category"   : "Category",
    "Amount"     : "Amount ($)",
    "Paid_by"    : "Paid by",
    "Split_pct"  : "Split (%)",
    "Status"     : "Status",
    "Notes"      : "Notes",
})

st.dataframe(
    display,
    use_container_width=True,
    hide_index=True,
)

# ── MONTHLY SUMMARY ──
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
monthly.columns = ["Month", "Total Spent ($)"]

st.dataframe(monthly, use_container_width=True, hide_index=True)

# ── CATEGORY BREAKDOWN ──
st.divider()
st.subheader("📂 By Category")

cat_summary = (
    filtered
    .groupby("Category")["Amount"]
    .agg(["sum", "count"])
    .reset_index()
    .rename(columns={"sum": "Total ($)", "count": "# Entries"})
    .sort_values("Total ($)", ascending=False)
)

st.dataframe(cat_summary, use_container_width=True, hide_index=True)

st.caption("Built with Streamlit · Data via Google Sheets CSV · No API key required")
