"""
Co-Parent Expense Tracker — Dashboard Page
Balances, quick add, and settle up.
"""

import streamlit as st
import pandas as pd
from datetime import date
from supabase import create_client, Client
import uuid

st.set_page_config(page_title="Expense Tracker — Dashboard", page_icon="🧾", layout="centered")

# ─── SESSION STATE ────────────────────────────────────────────────────────────

if "identity" not in st.session_state:
    st.session_state["identity"] = None

# ─── SUPABASE CLIENT ──────────────────────────────────────────────────────────

@st.cache_resource
def get_supabase() -> Client | None:
    try:
        url = st.secrets.get("SUPABASE_URL")
        key = st.secrets.get("SUPABASE_KEY")
    except Exception:
        return None
    if not url or not key or url == "your_url_here":
        return None
    try:
        return create_client(url, key)
    except Exception:
        return None

# ─── STORAGE HELPERS ──────────────────────────────────────────────────────────

BUCKET = "receipts"

def upload_receipt(supabase: Client, file_bytes: bytes, filename: str) -> str | None:
    ext = filename.split(".")[-1].lower() if "." in filename else "jpg"
    path = f"{uuid.uuid4().hex}.{ext.replace(' ', '_')}"
    try:
        mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
                "pdf": "application/pdf", "gif": "image/gif"}.get(ext, "application/octet-stream")
        supabase.storage.from_(BUCKET).upload(path, file_bytes, file_options={"content-type": mime})
        return supabase.storage.from_(BUCKET).get_public_url(path)
    except Exception:
        return None

def delete_receipt(supabase: Client, url: str) -> None:
    if not url:
        return
    fname = url.split("/")[-1].split("?")[0]
    if fname:
        try:
            supabase.storage.from_(BUCKET).remove(fname)
        except Exception:
            pass

# ─── DATA OPS ─────────────────────────────────────────────────────────────────

def load_expenses(supabase: Client) -> pd.DataFrame:
    result = supabase.table("expenses").select("*").order("date", desc=True).execute()
    df = pd.DataFrame(result.data or [])
    if df.empty:
        df["date"] = pd.Series(dtype="datetime64[ns]")
        df["amount"] = pd.Series(dtype=float)
        df["split_pct"] = pd.Series(dtype=float)
        return df
    df["date"]      = pd.to_datetime(df["date"], errors="coerce")
    df["amount"]    = pd.to_numeric(df["amount"], errors="coerce").fillna(0).round(2)
    df["split_pct"] = pd.to_numeric(df["split_pct"], errors="coerce").fillna(50)
    return df

def insert_expense(supabase: Client, row: dict) -> None:
    supabase.table("expenses").insert(row).execute()

def update_expense(supabase: Client, expense_id: int, row: dict) -> None:
    supabase.table("expenses").update(row).eq("id", expense_id).execute()

def delete_expense(supabase: Client, expense_id: int) -> None:
    supabase.table("expenses").delete().eq("id", expense_id).execute()

# ─── HELPERS ─────────────────────────────────────────────────────────────────

def identity_name(viewer: str, role: str) -> str:
    return "Dad" if viewer == "me" else "Mom" if role == "Me" else "Dad"

CATEGORIES = [
    "Groceries", "Kids", "Medical", "Transportation",
    "Entertainment", "Clothing", "School", "Other"
]

def calc_balances(df: pd.DataFrame) -> tuple[float, float]:
    dad_owes_mom, mom_owes_dad = 0.0, 0.0
    for _, row in df.iterrows():
        if str(row.get("status", "")).lower() == "settled":
            continue
        amt   = float(row.get("amount", 0))
        split = float(row.get("split_pct", 50)) / 100.0
        p     = str(row.get("paid_by", "")).strip()
        if p.lower() == "both":
            continue
        if p == "Dad":
            mom_owes_dad += amt * (1 - split)
        elif p == "Mom":
            dad_owes_mom += amt * (1 - split)
    return round(dad_owes_mom, 2), round(mom_owes_dad, 2)

# ─── MIGRATION ────────────────────────────────────────────────────────────────

supabase = get_supabase()
if supabase is not None:
    try:
        rows = supabase.table("expenses").select("id,paid_by").execute().data or []
        for r in rows:
            old = str(r.get("paid_by") or "").strip()
            if old.lower() in ("me", "other"):
                new_val = "Mom" if old.lower() == "other" else "Dad"
                supabase.table("expenses").update({"paid_by": new_val}).eq("id", r["id"]).execute()
    except Exception:
        pass

_is_configured = supabase is not None

# ─── SETUP GATE ───────────────────────────────────────────────────────────────

if not _is_configured:
    st.title("🧾 Co-Parent Expense Tracker")
    st.divider()
    st.error("⚠️ Supabase is not configured.")
    st.markdown("### 🔧 Setup Required")
    st.markdown("Add your secrets in **Streamlit Cloud → Settings → Secrets**:\n\n"
                "```\nSUPABASE_URL = \"https://xxxx.supabase.co\"\nSUPABASE_KEY = \"eyJ...\"\n```\n\n"
                "Then run the SQL setup from the app repository's README.")
    st.stop()

# ─── IDENTITY ────────────────────────────────────────────────────────────────

if st.session_state["identity"] is None:
    st.title("🧾 Co-Parent Expense Tracker")
    st.markdown("##### Track, split, and settle expenses together — in real time.")
    st.divider()
    st.markdown("### 👋 Who's viewing?")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**👤 Me / Dad**")
        if st.button("Continue as Me (Dad)", use_container_width=True):
            st.session_state["identity"] = "me"
            st.rerun()
    with c2:
        st.markdown("**👤 Mom**")
        if st.button("Continue as Mom", use_container_width=True):
            st.session_state["identity"] = "mom"
            st.rerun()
    st.stop()

identity   = st.session_state["identity"]
my_name    = identity_name(identity, "Me")
other_name = identity_name(identity, "Other")

# ─── LOAD DATA ────────────────────────────────────────────────────────────────

try:
    df = load_expenses(supabase)
except Exception:
    df = pd.DataFrame()

# ─── PAGE HEADER ──────────────────────────────────────────────────────────────

st.title("🧾 Expense Tracker")
col_nav, col_refresh = st.columns([4, 1])
with col_nav:
    st.page_link("pages/2_Records.py", label="📋 View All Records →", use_container_width=True)
with col_refresh:
    if st.button("🔄 Refresh", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

st.caption(f"Logged in as **{my_name}** · Both parents share the same live data")
st.divider()

# ─── BALANCE CARDS ───────────────────────────────────────────────────────────

if not df.empty:
    dad_owes_mom, mom_owes_dad = calc_balances(df)
else:
    dad_owes_mom, mom_owes_dad = 0.0, 0.0

c1, c2 = st.columns(2)
with c1:
    (st.error if dad_owes_mom > 0.01 else st.success)(
        f"**👤 Dad owes Mom**\n**${dad_owes_mom:,.2f}**"
    )
with c2:
    (st.success if mom_owes_dad > 0.01 else st.info)(
        f"**👤 Mom owes Dad**\n**${mom_owes_dad:,.2f}**"
    )

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
#  ADD EXPENSE
# ══════════════════════════════════════════════════════════════════════════════

st.subheader("➕ Add Expense")

with st.expander("✏️ Log a new expense", expanded=True):
    with st.form("add_form", clear_on_submit=True):
        paid_by = st.radio(
            "Who paid?",
            ["Me", "Other", "Both"],
            horizontal=True,
            help="Me = you. Other = co-parent."
        )
        date_in = st.date_input("Date", value=date.today())
        desc    = st.text_input("Description *", placeholder="e.g. Groceries at Publix")
        cat     = st.selectbox("Category", CATEGORIES)
        amt     = st.number_input("Amount ($) *", min_value=0.01, step=0.01, format="%.2f")
        split   = st.slider(f"{my_name}'s split %", 0, 100, 50, step=5)
        status  = st.selectbox("Status", ["active", "settled"])
        notes   = st.text_input("Notes (optional)")
        receipt = st.file_uploader("🧾 Receipt (optional)", type=["jpg", "jpeg", "png", "pdf"])

        submitted = st.form_submit_button("💾 Save Expense", use_container_width=True)

    if submitted:
        if not desc.strip():
            st.warning("⚠️ Description is required.")
        elif amt <= 0:
            st.warning("⚠️ Amount must be greater than $0.")
        else:
            row = {
                "date": str(date_in), "description": desc.strip(),
                "category": cat, "amount": round(float(amt), 2),
                "paid_by": paid_by, "split_pct": float(split),
                "status": status, "notes": notes.strip() or None,
            }
            if row["paid_by"] == "Me":
                row["paid_by"] = my_name
            elif row["paid_by"] == "Other":
                row["paid_by"] = other_name
            if receipt:
                try:
                    url = upload_receipt(supabase, receipt.getvalue(), receipt.name)
                    if url:
                        row["receipt_url"] = url
                except Exception:
                    st.warning("⚠️ Receipt upload failed.")
            try:
                insert_expense(supabase, row)
                st.success("✅ Expense saved!")
                st.cache_data.clear()
                st.rerun()
            except Exception as e:
                st.error(f"❌ Save failed: {e}")

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
#  SETTLE UP
# ══════════════════════════════════════════════════════════════════════════════

if not df.empty:
    active = df[df["status"].str.lower() != "settled"].copy()
    if not active.empty:
        st.subheader("💸 Settle Up")
        st.markdown("Click **Settle** when a parent has paid their share. Removes from active balances.")
        for _, r in active.iterrows():
            amt   = float(r["amount"])
            split = float(r.get("split_pct", 50))
            your_share = round(amt * split / 100, 2)
            their_share = round(amt * (100 - split) / 100, 2)
            with st.container():
                cols, colb = st.columns([4, 1])
                with cols:
                    st.markdown(
                        f"**#{r['id']}** — {r['description']}  "
                        f"| **${amt:.2f}** | Split: **{split:.0f}%**"
                    )
                    st.caption(
                        f"{my_name} pays: **${your_share:.2f}**  ·  "
                        f"{other_name} pays: **${their_share:.2f}**"
                    )
                with colb:
                    if st.button(f"✅ Settle", key=f"settle_dash_{r['id']}", use_container_width=True):
                        try:
                            update_expense(supabase, int(r["id"]), {"status": "settled"})
                            st.cache_data.clear()
                            st.rerun()
                        except Exception as e:
                            st.error(f"❌ {e}")
                st.divider()

# ── Monthly summary ──
if not df.empty:
    st.divider()
    st.subheader("📅 Monthly Spending")
    monthly = (
        df.groupby(df["date"].dt.to_period("M"))["amount"]
        .sum().reset_index()
    )
    if not monthly.empty:
        monthly["date"] = monthly["date"].astype(str).sort_values(ascending=False)
        monthly.columns = ["Month", "Total ($)"]
        st.dataframe(monthly, use_container_width=True, hide_index=True)

# ── Switch identity ──
st.divider()
with st.expander("🔄 Switch parent identity"):
    if st.button(f"Switch to {other_name}"):
        st.session_state["identity"] = "mom" if identity == "me" else "me"
        st.rerun()

st.caption("Built with Streamlit · Data via Supabase · Both parents share the same live view")
