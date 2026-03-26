"""
shared.py — Single source of truth for the Co-Parent Expense Tracker.
Both pages import from here. No duplicated logic.
"""

import streamlit as st
import pandas as pd
import uuid
from supabase import create_client, Client


# ─── SUPABASE CLIENT (cached singleton) ──────────────────────────────────────

@st.cache_resource
def get_supabase() -> Client | None:
    """Return a cached Supabase client, or None if secrets are missing."""
    try:
        url = st.secrets.get("SUPABASE_URL") or st.secrets.get("supabase_url") or ""
        key = st.secrets.get("SUPABASE_KEY") or st.secrets.get("supabase_key") or ""
    except Exception:
        return None
    if not url or not key or url == "your_url_here":
        return None
    try:
        return create_client(url, key)
    except Exception:
        return None


# ─── IDENTITY ─────────────────────────────────────────────────────────────────

def get_names(identity: str) -> tuple[str, str]:
    """Return (my_name, other_name) based on the viewer identity."""
    if identity == "me":
        return "Dad", "Mom"
    return "Mom", "Dad"


def show_identity_picker() -> None:
    """Render the 'Who are you?' picker and st.stop() until chosen."""
    st.title("Co-Parent Expense Tracker")
    st.markdown("##### Track, split, and settle expenses together.")
    st.divider()
    st.markdown("### Who's viewing?")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("Continue as Dad", use_container_width=True):
            st.session_state["identity"] = "me"
            st.rerun()
    with c2:
        if st.button("Continue as Mom", use_container_width=True):
            st.session_state["identity"] = "mom"
            st.rerun()
    st.stop()


def show_profile_switcher(identity: str) -> None:
    """Render the profile switcher bar at the bottom of a page."""
    current = "Dad" if identity == "me" else "Mom"
    new_identity = "mom" if identity == "me" else "me"
    new_label = "Switch to Mom" if identity == "me" else "Switch to Dad"
    with st.container():
        c1, c2 = st.columns([1, 1])
        with c1:
            st.markdown(f"**Profile:** {current}")
        with c2:
            if st.button(new_label, use_container_width=True):
                st.session_state["identity"] = new_identity
                st.rerun()


# ─── CATEGORIES ───────────────────────────────────────────────────────────────

CATEGORIES = [
    "Groceries", "Kids", "Medical", "Transportation",
    "Entertainment", "Clothing", "School", "Other",
]


# ─── RECEIPT STORAGE ──────────────────────────────────────────────────────────

BUCKET = "receipts"

MIME_MAP = {
    "jpg": "image/jpeg", "jpeg": "image/jpeg",
    "png": "image/png", "gif": "image/gif",
    "pdf": "application/pdf",
}


def upload_receipt(sb: Client, file_bytes: bytes, filename: str) -> str | None:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "jpg"
    path = f"{uuid.uuid4().hex}.{ext.replace(' ', '_')}"
    mime = MIME_MAP.get(ext, "application/octet-stream")
    try:
        sb.storage.from_(BUCKET).upload(
            path, file_bytes, file_options={"content-type": mime},
        )
        return sb.storage.from_(BUCKET).get_public_url(path)
    except Exception:
        return None


def delete_receipt(sb: Client, url: str) -> None:
    if not url:
        return
    fname = url.split("/")[-1].split("?")[0]
    if fname:
        try:
            sb.storage.from_(BUCKET).remove([fname])   # API expects a list
        except Exception:
            pass


# ─── DATA OPS ─────────────────────────────────────────────────────────────────

def load_expenses(sb: Client) -> pd.DataFrame:
    result = sb.table("expenses").select("*").order("date", desc=True).execute()
    df = pd.DataFrame(result.data or [])
    if df.empty:
        df["date"]      = pd.Series(dtype="datetime64[ns]")
        df["amount"]    = pd.Series(dtype=float)
        df["split_pct"] = pd.Series(dtype=float)
        return df
    df["date"]      = pd.to_datetime(df["date"], errors="coerce")
    df["amount"]    = pd.to_numeric(df["amount"], errors="coerce").fillna(0).round(2)
    df["split_pct"] = pd.to_numeric(df["split_pct"], errors="coerce").fillna(50)
    return df


def insert_expense(sb: Client, row: dict) -> None:
    sb.table("expenses").insert(row).execute()


def update_expense(sb: Client, expense_id: int, row: dict) -> None:
    sb.table("expenses").update(row).eq("id", expense_id).execute()


def delete_expense(sb: Client, expense_id: int) -> None:
    sb.table("expenses").delete().eq("id", expense_id).execute()


# ─── BALANCE CALCULATION ─────────────────────────────────────────────────────
#
#  split_pct = "Dad's share %" (always, regardless of who is logged in).
#
#  Example: $100 expense, split_pct = 60, paid_by = "Mom"
#    Dad's share  = $100 * 60%  = $60   → Dad owes Mom $60
#    Mom's share  = $100 * 40%  = $40   → she paid, so nothing extra
#
#  Example: $100 expense, split_pct = 60, paid_by = "Dad"
#    Mom's share  = $100 * 40%  = $40   → Mom owes Dad $40
#    Dad's share  = $100 * 60%  = $60   → he paid, so nothing extra
#
# ─────────────────────────────────────────────────────────────────────────────

def calc_balances(df: pd.DataFrame) -> tuple[float, float]:
    """Return (dad_owes_mom, mom_owes_dad) from all active (unsettled) rows."""
    dad_owes_mom = 0.0
    mom_owes_dad = 0.0
    for _, row in df.iterrows():
        if str(row.get("status", "")).lower() == "settled":
            continue
        amt       = float(row.get("amount", 0))
        dad_pct   = float(row.get("split_pct", 50)) / 100.0
        payer     = str(row.get("paid_by", "")).strip()
        if payer == "Dad":
            # Dad paid. Mom owes her share.
            mom_owes_dad += amt * (1 - dad_pct)
        elif payer == "Mom":
            # Mom paid. Dad owes his share.
            dad_owes_mom += amt * dad_pct
        # "Both" → each paid their own share, no debt.
    return round(dad_owes_mom, 2), round(mom_owes_dad, 2)


def payer_share(amt: float, split_pct: float, paid_by: str) -> tuple[float, float]:
    """Return (dad_share, mom_share) dollar amounts for display."""
    dad_share = round(amt * split_pct / 100, 2)
    mom_share = round(amt - dad_share, 2)
    return dad_share, mom_share
