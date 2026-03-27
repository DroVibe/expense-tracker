"""
shared.py — Single source of truth for the Co-Parent Expense Tracker.
Both pages import from here. No duplicated logic.
"""

import streamlit as st
import pandas as pd
import uuid
from datetime import datetime
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


# ─── STORAGE ──────────────────────────────────────────────────────────────────

BUCKET = "receipts"

MIME_MAP = {
    "jpg": "image/jpeg", "jpeg": "image/jpeg",
    "png": "image/png", "gif": "image/gif",
    "pdf": "application/pdf",
}


def _upload_file(sb: Client, file_bytes: bytes, filename: str, prefix: str) -> str | None:
    """Upload a file to Supabase Storage under the given prefix. Returns public URL or None."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "jpg"
    safe_name = f"{uuid.uuid4().hex}.{ext.replace(' ', '_')}"
    path = f"{prefix}/{safe_name}" if prefix else safe_name
    mime = MIME_MAP.get(ext, "application/octet-stream")
    try:
        sb.storage.from_(BUCKET).upload(path, file_bytes, file_options={"content-type": mime})
        return sb.storage.from_(BUCKET).get_public_url(path)
    except Exception:
        return None


def upload_receipt(sb: Client, file_bytes: bytes, filename: str) -> str | None:
    """Upload a purchase receipt."""
    return _upload_file(sb, file_bytes, filename, "receipts")


def upload_settlement_proof(sb: Client, file_bytes: bytes, filename: str) -> str | None:
    """Upload a settlement payment screenshot/proof."""
    return _upload_file(sb, file_bytes, filename, "settlements")


def delete_file(sb: Client, url: str) -> None:
    """Delete a file from storage given its public URL."""
    if not url:
        return
    fname = url.split("/")[-1].split("?")[0]
    if fname:
        try:
            sb.storage.from_(BUCKET).remove([fname])
        except Exception:
            pass


# ─── DATA OPS ─────────────────────────────────────────────────────────────────

def load_expenses(sb: Client) -> pd.DataFrame:
    result = sb.table("expenses").select("*").order("date", desc=True).execute()
    df = pd.DataFrame(result.data or [])
    if df.empty:
        for col in ["date", "amount", "split_pct", "paid_by", "status",
                    "description", "category", "notes", "receipt_url",
                    "settlement_proof_url", "settled_by", "settled_at", "settlement_note"]:
            df[col] = pd.Series(dtype="object")
        return df
    df["date"]      = pd.to_datetime(df["date"], errors="coerce")
    df["amount"]    = pd.to_numeric(df["amount"], errors="coerce").fillna(0).round(2)
    df["split_pct"] = pd.to_numeric(df["split_pct"], errors="coerce").fillna(50)
    # Fill new settlement columns if missing
    for col in ["settlement_proof_url", "settled_by", "settled_at", "settlement_note"]:
        if col not in df.columns:
            df[col] = None
    return df


def insert_expense(sb: Client, row: dict) -> None:
    sb.table("expenses").insert(row).execute()


def update_expense(sb: Client, expense_id: int, row: dict) -> None:
    sb.table("expenses").update(row).eq("id", expense_id).execute()


def delete_expense(sb: Client, expense_id: int) -> None:
    sb.table("expenses").delete().eq("id", expense_id).execute()


# ─── BALANCE CALCULATION ─────────────────────────────────────────────────────

def calc_balances(df: pd.DataFrame) -> tuple[float, float]:
    """Return (dad_owes_mom, mom_owes_dad) from all active (unsettled) rows."""
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


def payer_share(amt: float, split_pct: float, paid_by: str) -> tuple[float, float]:
    """Return (dad_share, mom_share) dollar amounts for display."""
    dad_share = round(amt * split_pct / 100, 2)
    mom_share = round(amt - dad_share, 2)
    return dad_share, mom_share
