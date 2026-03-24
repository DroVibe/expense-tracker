"""
Co-Parent Expense Tracker — Records Page
Full expense log with click-to-expand details, receipts, and inline edit/delete.
"""

import streamlit as st
import pandas as pd
from datetime import date
from supabase import create_client, Client
import uuid

st.set_page_config(page_title="Expense Tracker — Records", page_icon="🧾", layout="centered")

# ─── SESSION STATE ─────────────────────────────────────────────────────────────

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

# ─── STORAGE ───────────────────────────────────────────────────────────────────

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
        return df
    df["date"]      = pd.to_datetime(df["date"], errors="coerce")
    df["amount"]    = pd.to_numeric(df["amount"], errors="coerce").fillna(0).round(2)
    df["split_pct"] = pd.to_numeric(df["split_pct"], errors="coerce").fillna(50)
    return df

def update_expense(supabase: Client, expense_id: int, row: dict) -> None:
    supabase.table("expenses").update(row).eq("id", expense_id).execute()

def delete_expense(supabase: Client, expense_id: int) -> None:
    supabase.table("expenses").delete().eq("id", expense_id).execute()

# ─── HELPERS ──────────────────────────────────────────────────────────────────

def identity_name(viewer: str, role: str) -> str:
    return "Dad" if viewer == "me" else "Mom" if role == "Me" else "Dad"

CATEGORIES = [
    "Groceries", "Kids", "Medical", "Transportation",
    "Entertainment", "Clothing", "School", "Other"
]

# ─── INIT ─────────────────────────────────────────────────────────────────────

supabase = get_supabase()
_is_configured = supabase is not None

if not _is_configured or st.session_state["identity"] is None:
    st.title("🧾 Expense Tracker — Records")
    st.divider()
    if not _is_configured:
        st.error("⚠️ Supabase not configured. Add secrets in Streamlit Cloud settings.")
        st.stop()
    st.markdown("### 👋 Select your profile first")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("👤 Continue as Me (Dad)", use_container_width=True):
            st.session_state["identity"] = "me"
            st.rerun()
    with c2:
        if st.button("👤 Continue as Mom", use_container_width=True):
            st.session_state["identity"] = "mom"
            st.rerun()
    st.stop()

identity   = st.session_state["identity"]
my_name    = identity_name(identity, "Me")
other_name = identity_name(identity, "Other")

# ─── LOAD ─────────────────────────────────────────────────────────────────────

try:
    df = load_expenses(supabase)
except Exception:
    df = pd.DataFrame()

# ─── PAGE HEADER ─────────────────────────────────────────────────────────────

st.title("📋 All Records")
col_back, col_refresh = st.columns([4, 1])
with col_back:
    st.page_link("expense_tracker.py", label="← Back to Dashboard", use_container_width=False)
with col_refresh:
    if st.button("🔄 Refresh"):
        st.cache_data.clear()
        st.rerun()

st.caption(f"Logged in as **{my_name}** · {len(df)} total expenses")
st.divider()

# ─── FILTERS ──────────────────────────────────────────────────────────────────

if df.empty:
    st.info("No expenses yet. Go to Dashboard to add one.")
    st.stop()

min_d = df["date"].min().date()
max_d = df["date"].max().date()

f1, f2, f3, f4, f5 = st.columns(5)
with f1:
    start = st.date_input("From", value=min_d)
with f2:
    end   = st.date_input("To",   value=max_d)
with f3:
    cats  = ["All"] + sorted(df["category"].dropna().unique().tolist())
    cat_f = st.selectbox("Category", cats)
with f4:
    stat_f = st.selectbox("Status", ["All", "Active", "Settled"])
with f5:
    payer_f = st.selectbox("Paid by", ["All", my_name, other_name, "Both"])

mask = pd.Series(True, index=df.index)
if pd.notna(start): mask &= df["date"] >= pd.Timestamp(start)
if pd.notna(end):   mask &= df["date"] <= pd.Timestamp(end)
if cat_f   != "All":     mask &= df["category"] == cat_f
if stat_f  == "Active":  mask &= df["status"].str.lower() == "active"
elif stat_f == "Settled":mask &= df["status"].str.lower() == "settled"
if payer_f != "All":     mask &= df["paid_by"].str.lower() == payer_f.lower()

filtered = df[mask].sort_values("date", ascending=False).reset_index(drop=True)

st.markdown(f"**{len(filtered)}** expenses shown  ·  **${filtered['amount'].sum():.2f}** total")

# ─── SUMMARY ROW ──────────────────────────────────────────────────────────────

active_df = filtered[filtered["status"].str.lower() != "settled"]
settled_df = filtered[filtered["status"].str.lower() == "settled"]

sc1, sc2, sc3 = st.columns(3)
with sc1:
    st.metric("Active", len(active_df), f"${active_df['amount'].sum():.2f}")
with sc2:
    st.metric("Settled", len(settled_df), f"${settled_df['amount'].sum():.2f}")
with sc3:
    st.metric("Total", len(filtered), f"${filtered['amount'].sum():.2f}")

st.divider()

# ─── EXPENSE CARDS ─────────────────────────────────────────────────────────────

if filtered.empty:
    st.info("No expenses match your filters.")
else:
    for _, r in filtered.iterrows():
        is_active = r["status"].lower() != "settled"
        amt   = float(r["amount"])
        split = float(r.get("split_pct", 50))
        your_share   = round(amt * split / 100, 2)
        their_share  = round(amt * (100 - split) / 100, 2)

        with st.container():
            # Card header
            col_left, col_right = st.columns([3, 1])

            with col_left:
                status_label = "🟢 Active" if is_active else "✅ Settled"
                st.markdown(
                    f"### #{r['id']} — {r['description']}"
                )
                st.markdown(
                    f"{status_label}  ·  **${amt:.2f}**  ·  "
                    f"Paid by **{r.get('paid_by', '?')}**  ·  "
                    f"Split **{split:.0f}%**"
                )

            with col_right:
                if is_active:
                    if st.button(f"✅ Settle", key=f"settle_{r['id']}", use_container_width=True):
                        try:
                            update_expense(supabase, int(r["id"]), {"status": "settled"})
                            st.cache_data.clear()
                            st.rerun()
                        except Exception as e:
                            st.error(f"❌ {e}")
                else:
                    st.markdown("#### ✅ Settled")

            # Details
            det1, det2, det3, det4 = st.columns(4)
            with det1:
                date_str = pd.to_datetime(r["date"]).strftime("%b %d, %Y") if pd.notna(r["date"]) else "—"
                st.markdown(f"**Date**\n{date_str}")
            with det2:
                st.markdown(f"**Category**\n{r.get('category', '—')}")
            with det3:
                st.markdown(f"**Your share**\n**${your_share:.2f}**")
            with det4:
                st.markdown(f"**Their share**\n**${their_share:.2f}**")

            if r.get("notes"):
                st.markdown(f"**Notes:** {r['notes']}")

            # Receipt
            receipt_url = r.get("receipt_url")
            if receipt_url:
                st.divider()
                st.markdown("**🧾 Receipt**")
                try:
                    st.image(receipt_url, width=400, caption=f"Receipt #{r['id']}")
                except Exception:
                    st.markdown(f"[🖼️ Open receipt]({receipt_url})")
                st.link_button("📥 Open / Download Receipt", receipt_url)

            # ── Edit / Delete ──
            with st.expander(f"✏️ Edit or Delete expense #{r['id']}"):
                stored_payer = str(r.get("paid_by", "")).strip()
                if stored_payer == my_name:
                    neutral_p = "Me"
                elif stored_payer == other_name:
                    neutral_p = "Other"
                else:
                    neutral_p = "Both"

                with st.form(f"edit_{r['id']}", clear_on_submit=False):
                    e_date  = st.date_input(
                        "Date",
                        value=pd.to_datetime(r["date"]).date() if pd.notna(r["date"]) else date.today(),
                        key=f"e_date_{r['id']}",
                    )
                    e_desc  = st.text_input("Description", value=str(r.get("description","") or ""), key=f"e_desc_{r['id']}")
                    e_cat   = st.selectbox(
                        "Category", CATEGORIES,
                        index=CATEGORIES.index(r["category"]) if r["category"] in CATEGORIES else 0,
                        key=f"e_cat_{r['id']}",
                    )
                    e_amt   = st.number_input(
                        "Amount ($)", value=float(r["amount"]),
                        min_value=0.01, step=0.01, format="%.2f", key=f"e_amt_{r['id']}",
                    )
                    e_payer = st.selectbox(
                        "Who paid?", ["Me", "Other", "Both"],
                        index=["Me", "Other", "Both"].index(neutral_p),
                        key=f"e_payer_{r['id']}",
                    )
                    e_split = st.slider(
                        f"{my_name}'s split %", 0, 100, int(split), step=5,
                        key=f"e_split_{r['id']}",
                    )
                    e_stat  = st.selectbox(
                        "Status", ["active", "settled"],
                        index=["active", "settled"].index(r.get("status", "active"))
                        if r.get("status", "active") in ["active","settled"] else 0,
                        key=f"e_stat_{r['id']}",
                    )
                    e_notes = st.text_input(
                        "Notes", value=str(r.get("notes") or ""),
                        key=f"e_notes_{r['id']}",
                    )

                    if receipt_url:
                        st.markdown("**Current receipt:**")
                        st.link_button("🧾 View Current Receipt", receipt_url)
                    e_receipt = st.file_uploader(
                        "🧾 Replace receipt (leave empty to keep current)",
                        type=["jpg","jpeg","png","pdf"],
                        key=f"e_receipt_{r['id']}",
                    )

                    eu, ed = st.columns(2)
                    with eu:
                        upd = st.form_submit_button("💾 Update", use_container_width=True)
                    with ed:
                        del_ = st.form_submit_button("🗑️ Delete", use_container_width=True, type="primary")

                    if upd:
                        new_row = {
                            "date": str(e_date), "description": e_desc.strip(),
                            "category": e_cat, "amount": round(float(e_amt), 2),
                            "paid_by": e_payer, "split_pct": float(e_split),
                            "status": e_stat, "notes": e_notes.strip() or None,
                        }
                        if new_row["paid_by"] == "Me":
                            new_row["paid_by"] = my_name
                        elif new_row["paid_by"] == "Other":
                            new_row["paid_by"] = other_name
                        if e_receipt:
                            try:
                                new_url = upload_receipt(supabase, e_receipt.getvalue(), e_receipt.name)
                                if new_url:
                                    if receipt_url:
                                        delete_receipt(supabase, receipt_url)
                                    new_row["receipt_url"] = new_url
                            except Exception:
                                st.warning("⚠️ Receipt upload failed.")
                        try:
                            update_expense(supabase, int(r["id"]), new_row)
                            st.success("✅ Updated!")
                            st.cache_data.clear()
                            st.rerun()
                        except Exception as e:
                            st.error(f"❌ Update failed: {e}")

                    if del_:
                        try:
                            if receipt_url:
                                delete_receipt(supabase, receipt_url)
                            delete_expense(supabase, int(r["id"]))
                            st.success("🗑️ Deleted!")
                            st.cache_data.clear()
                            st.rerun()
                        except Exception as e:
                            st.error(f"❌ Delete failed: {e}")

            st.divider()

# ─── Switch identity ──
st.divider()
with st.expander("🔄 Switch parent identity"):
    if st.button(f"Switch to {other_name}"):
        st.session_state["identity"] = "mom" if identity == "me" else "me"
        st.rerun()

st.caption("Built with Streamlit · Data via Supabase · Both parents share the same live view")
