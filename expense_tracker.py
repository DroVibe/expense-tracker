"""
Co-Parent Expense Tracker
Full CRUD via Supabase — both parents can add, edit, settle expenses & attach receipts.
"""

import streamlit as st
import pandas as pd
from datetime import date
from supabase import create_client, Client
import uuid
import urllib.request

# ─── SUPABASE CLIENT ──────────────────────────────────────────────────────────

@st.cache_resource
def get_supabase() -> Client:
    url = st.secrets.get("SUPABASE_URL")
    key = st.secrets.get("SUPABASE_KEY")
    if not url or not key:
        return None
    return create_client(url, key)

# ─── STORAGE HELPERS ──────────────────────────────────────────────────────────

BUCKET = "receipts"

def upload_receipt(supabase: Client, file_bytes: bytes, filename: str) -> str:
    """Upload file to Supabase Storage, return public URL."""
    ext = filename.split(".")[-1] if "." in filename else "jpg"
    path = f"{uuid.uuid4().hex}.{ext}"
    supabase.storage.from_(BUCKET).upload(path, file_bytes)
    return supabase.storage.from_(BUCKET).get_public_url(path)

def delete_receipt(supabase: Client, url: str) -> None:
    """Delete receipt from storage given a public URL."""
    if not url or not url.strip():
        return
    filename = url.split("/")[-1].split("?")[0]
    if filename:
        try:
            supabase.storage.from_(BUCKET).remove(filename)
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

def insert_expense(supabase: Client, row: dict) -> None:
    supabase.table("expenses").insert(row).execute()

def update_expense(supabase: Client, expense_id: int, row: dict) -> None:
    supabase.table("expenses").update(row).eq("id", expense_id).execute()

def delete_expense(supabase: Client, expense_id: int) -> None:
    supabase.table("expenses").delete().eq("id", expense_id).execute()

def get_expense(supabase: Client, expense_id: int) -> dict:
    result = supabase.table("expenses").select("*").eq("id", expense_id).execute()
    return result.data[0] if result.data else {}

# ─── HELPERS ────────────────────────────────────────────────────────────────

def identity_display_name(viewer: str, role: str) -> str:
    """
    Map neutral 'Me' / 'Other' to the correct display name based on who's viewing.
    viewer: 'me' (dad) or 'mom'
    role:   'Me'   → the viewer's own name
            'Other'→ the co-parent's name
    """
    if viewer == "me":
        return "Dad" if role == "Me" else "Mom"
    else:  # mom
        return "Mom" if role == "Me" else "Dad"

# ─── BALANCE ─────────────────────────────────────────────────────────────────
# paid_by stored as neutral: "Me" = the person who added the expense,
# "Other" = the co-parent, "Both".  Balance is always from the viewer's
# perspective so it stays correct for both parents.

def calc_balances(df: pd.DataFrame, identity: str) -> tuple[float, float]:
    """
    identity: 'me' (dad) or 'mom'
    Returns (viewer_owes, viewer_is_owed) — correct regardless of who's viewing.
    """
    me_owes, other_owes = 0.0, 0.0   # me_owes = viewer owes co-parent; other_owes = co-parent owes viewer
    for _, row in df.iterrows():
        s = str(row.get("status", "")).lower()
        if s in ("settled",):
            continue
        amt   = float(row.get("amount", 0))
        split = float(row.get("split_pct", 50)) / 100.0
        p     = str(row.get("paid_by", "")).lower()
        if "both" in p:
            continue
        if p == "me":
            # The viewer (identity) paid → co-parent owes their share
            other_owes += amt * (1 - split)
        elif p == "other":
            # Co-parent paid → viewer owes their share
            me_owes   += amt * split
    return round(me_owes, 2), round(other_owes, 2)

# ─── PAGE CONFIG ──────────────────────────────────────────────────────────────

st.set_page_config(
    page_title  = "Co-Parent Expense Tracker",
    page_icon   = "🧾",
    layout      = "centered",
)

# ─── LANDING / IDENTITY SELECTOR ──────────────────────────────────────────────

if "identity" not in st.session_state:
    st.session_state["identity"] = None

supabase = get_supabase()
if supabase is None:
    st.error("❌ Supabase not connected. Add SUPABASE_URL and SUPABASE_KEY in app secrets.")
    st.stop()

if st.session_state["identity"] is None:
    st.title("🧾 Co-Parent Expense Tracker")
    st.markdown("##### Track, split, and settle expenses together — in real time.")
    st.markdown("Both parents share the same view. All data is live and stored securely.")
    st.divider()

    st.markdown("### 👋 Who's viewing the tracker?")
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**👤 Me / Dad**")
        st.caption("Track expenses you've paid. See who owes what.")
        if st.button("Continue as Me (Dad)", use_container_width=True):
            st.session_state["identity"] = "me"
            st.rerun()
    with col2:
        st.markdown("**👤 Mom**")
        st.caption("Track expenses you've paid. See who owes what.")
        if st.button("Continue as Mom", use_container_width=True):
            st.session_state["identity"] = "mom"
            st.rerun()

    st.divider()
    col_i1, col_i2 = st.columns(2)
    with col_i1:
        st.markdown("**📋 What this tracker does**")
        st.markdown("- Log any shared expense\n- Split costs fairly (default 50/50)\n- Attach receipt photos\n- Mark expenses as settled\n- Both parents see everything live")
    with col_i2:
        st.markdown("**🔒 How data is stored**")
        st.markdown("- All data saved to Supabase (secure cloud DB)\n- Receipt images stored in Supabase Storage\n- No logins needed — shared URL is all you need\n- Data persists even when the app is closed")
    st.stop()

identity       = st.session_state["identity"]
my_name       = identity_display_name(identity, "Me")     # "Dad" or "Mom"
other_name    = identity_display_name(identity, "Other")  # "Mom" or "Dad"

# ─── HEADER ───────────────────────────────────────────────────────────────────

st.title("🧾 Expense Tracker")
st.caption(f"Logged in as **{my_name}** · Both parents share the same live data")

if st.button("🔄 Refresh", use_container_width=False):
    st.cache_data.clear()
    st.rerun()

# ─── LOAD DATA ────────────────────────────────────────────────────────────────

try:
    df = load_expenses(supabase)
except Exception as e:
    st.error(f"❌ Could not load data: {e}")
    df = pd.DataFrame()

# ─── BALANCE CARDS ────────────────────────────────────────────────────────────

if not df.empty:
    me_owes, other_owes = calc_balances(df, identity)
    net = other_owes - me_owes
else:
    me_owes, other_owes, net = 0.0, 0.0, 0.0

c1, c2, c3 = st.columns(3)
with c1:
    (st.error if me_owes > 0 else st.success)(
        f"**{my_name}** owes\n**${me_owes:,.2f}**"
    )
with c2:
    (st.success if other_owes > 0 else st.info)(
        f"**{other_name}** owes\n**${other_owes:,.2f}**"
    )
with c3:
    if net > 0.05:
        st.metric("Net", f"+" + f"${net:,.2f}", delta="You're owed")
    elif net < -0.05:
        st.metric("Net", f"-${abs(net):,.2f}", delta="You owe", delta_color="inverse")
    else:
        st.metric("Net", "$0.00", delta="All settled")

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
            help="Me = you (the person filling this out). Other = the co-parent."
        )
        date_in  = st.date_input("Date", value=date.today())
        desc     = st.text_input("Description *", placeholder="e.g. Groceries at Publix")
        cat      = st.selectbox("Category", [
            "Groceries","Kids","Medical","Transportation",
            "Entertainment","Clothing","School","Other"
        ])
        amt      = st.number_input("Amount ($) *", min_value=0.01, step=0.01, format="%.2f")
        split    = st.slider(f"{my_name}'s split %", 0, 100, 50, step=5)
        status   = st.selectbox("Status", ["active", "settled"])
        notes    = st.text_input("Notes (optional)", placeholder="Any extra details…")
        receipt  = st.file_uploader(
            "🧾 Receipt (optional)",
            type=["jpg","jpeg","png","pdf"],
            help="Attach a photo or PDF of the receipt",
        )

        submitted = st.form_submit_button("💾 Save Expense", use_container_width=True)

    if submitted:
        if not desc.strip():
            st.warning("⚠️ Description is required.")
        elif amt <= 0:
            st.warning("⚠️ Amount must be greater than $0.")
        else:
            row = {
                "date"       : str(date_in),
                "description": desc.strip(),
                "category"   : cat,
                "amount"     : round(float(amt), 2),
                "paid_by"    : paid_by,
                "split_pct"  : float(split),
                "status"     : status,
                "notes"      : notes.strip() or None,
            }
            receipt_url = None
            if receipt:
                try:
                    receipt_url = upload_receipt(supabase, receipt.getvalue(), receipt.name)
                    row["receipt_url"] = receipt_url
                except Exception as e:
                    st.warning(f"⚠️ Receipt upload failed: {e}")
            try:
                insert_expense(supabase, row)
                st.success("✅ Expense saved!")
                st.cache_data.clear()
                st.rerun()
            except Exception as e:
                st.error(f"❌ Save failed: {e}")

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
#  EXPENSE LOG + FILTERS
# ══════════════════════════════════════════════════════════════════════════════

st.subheader("📋 Expense Log" + (f"  ({len(df)} rows)" if not df.empty else ""))

if df.empty:
    st.info("No expenses yet. Add one above!")

else:
    # Filters
    f1, f2, f3, f4 = st.columns(4)
    with f1:
        start = st.date_input("From", value=df["date"].min().date())
    with f2:
        end   = st.date_input("To",   value=df["date"].max().date())
    with f3:
        cats  = ["All"] + sorted(df["category"].dropna().unique().tolist())
        cat_f = st.selectbox("Category", cats)
    with f4:
        stat_f = st.selectbox("Status", ["All", "active", "settled"])

    mask = (
        (df["date"]  >= pd.Timestamp(start)) &
        (df["date"]  <= pd.Timestamp(end))   &
        (df["category"] == cat_f if cat_f != "All" else True) &
        (df["status"]   == stat_f if stat_f != "All" else True)
    )
    filtered = df[mask].sort_values("date", ascending=False).reset_index(drop=True)

    # Ensure all expected columns exist
    for col in ["receipt_url"]:
        if col not in filtered.columns:
            filtered[col] = None

    # Map neutral "Me" / "Other" to display names based on viewer's identity
    def display_payer(p):
        p = str(p).strip()
        if p.lower() == "me":     return identity_display_name(identity, "Me")
        if p.lower() == "other":  return identity_display_name(identity, "Other")
        return p  # "Both" or whatever

    # Receipt column — show as clickable text
    filtered["_receipt_link"] = filtered["receipt_url"].apply(
        lambda u: f"[🧾 View receipt]({u})" if u else "—"
    )

    disp = filtered[["id","date","description","category","amount","paid_by","split_pct","status","_receipt_link"]].copy()
    disp["paid_by"] = disp["paid_by"].apply(display_payer)
    disp.columns = [
        "ID","Date","Description","Category",
        "Amount ($)","Paid by","Split (%)","Status","Receipt",
    ]

    st.dataframe(disp, use_container_width=True, hide_index=True)

    # ── Inline receipt viewer + download ──
    receipts_with_urls = filtered[filtered["receipt_url"].notna()][["id","description","receipt_url"]].values
    if len(receipts_with_urls):
        st.divider()
        st.subheader("🧾 Receipts")
        for exp_id, desc, r_url in receipts_with_urls:
            # Try to fetch for preview + download; fall back to link-only
            img_bytes = None
            fname = r_url.split("/")[-1].split("?")[0]
            img_mime = "image/jpeg" if fname.lower().endswith((".jpg","jpeg",".png")) else "application/pdf"

            try:
                req = urllib.request.Request(r_url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=10) as resp:
                    img_bytes = resp.read()
            except Exception:
                img_bytes = None

            with st.container():
                col_r, col_d = st.columns([1, 3])
                with col_r:
                    st.markdown(f"**#{exp_id}** — {desc}")
                    if img_bytes:
                        st.image(img_bytes, width=200, caption=f"Receipt #{exp_id}")
                    else:
                        st.markdown(f"[🖼️ Open receipt]({r_url})")
                with col_d:
                    st.markdown(f"**#{exp_id} — {desc}**")
                    st.markdown(f"[🔗 Open in new tab]({r_url})")
                    if img_bytes:
                        st.download_button(
                            "⬇️ Download receipt",
                            data=img_bytes,
                            file_name=f"receipt_{exp_id}_{fname}",
                            mime=img_mime,
                            use_container_width=True,
                        )
                    else:
                        st.warning("⚠️ Receipt could not be loaded for download. Use 'Open in new tab' instead.")
                st.divider()
    elif df["receipt_url"].notna().any():
        st.divider()
        st.subheader("🧾 Receipts")
        st.info("Some receipts exist but are hidden by current filters. Adjust filters to see them.")

    # ── EDIT / DELETE ──
    st.divider()
    st.subheader("✏️ Edit or Delete")

    ids = [""] + filtered["id"].tolist()
    edit_id = st.selectbox("Select expense", ids, format_func=lambda x: f"#{x}  —  {filtered.loc[filtered['id']==x,'description'].values[0]}" if x and x in filtered["id"].values else "—")

    if edit_id:
        row = filtered[filtered["id"] == edit_id].iloc[0]
        orig_url = str(row.get("receipt_url") or "")

        with st.form(f"edit_{edit_id}", clear_on_submit=False):
            e_date  = st.date_input("Date", value=pd.to_datetime(row["date"]).date(), key=f"e_date_{edit_id}")
            e_desc  = st.text_input("Description", value=row["description"], key=f"e_desc_{edit_id}")
            e_cat   = st.selectbox("Category", [
                "Groceries","Kids","Medical","Transportation",
                "Entertainment","Clothing","School","Other"
            ], index=(
                ["Groceries","Kids","Medical","Transportation",
                 "Entertainment","Clothing","School","Other"].index(row["category"])
                if row["category"] in ["Groceries","Kids","Medical","Transportation",
                                        "Entertainment","Clothing","School","Other"]
                else 0
            ), key=f"e_cat_{edit_id}")
            e_amt   = st.number_input("Amount ($)", value=float(row["amount"]),
                                      min_value=0.01, step=0.01, format="%.2f", key=f"e_amt_{edit_id}")
            # Map stored display name back to neutral for editing
            stored_payer = str(row.get("paid_by", "")).strip()
            neutral_map  = {
                identity_display_name(identity, "Me")   : "Me",
                identity_display_name(identity, "Other"): "Other",
                "Both": "Both",
            }
            neutral_payer = neutral_map.get(stored_payer, "Me")
            payer_opts = ["Me", "Other", "Both"]
            payer_idx  = payer_opts.index(neutral_payer)
            e_payer = st.selectbox("Who paid?", payer_opts, index=payer_idx, key=f"e_payer_{edit_id}")
            e_split = st.slider(f"{my_name}'s split %", 0, 100,
                                int(row["split_pct"]), step=5, key=f"e_split_{edit_id}")
            e_stat  = st.selectbox("Status", ["active","settled"],
                                   index=["active","settled"].index(row["status"])
                                   if row["status"] in ["active","settled"] else 0,
                                   key=f"e_stat_{edit_id}")
            e_notes = st.text_input("Notes", value=row.get("notes") or "",
                                    key=f"e_notes_{edit_id}")

            # Receipt management
            if orig_url:
                st.markdown(f"📎 Current receipt: [{orig_url.split('/')[-1]}]({orig_url})")
            e_receipt = st.file_uploader(
                "🧾 Replace receipt (leave empty to keep current)",
                type=["jpg","jpeg","png","pdf"],
                key=f"e_receipt_{edit_id}",
            )

            col_upd, col_del = st.columns(2)
            with col_upd:
                upd_btn = st.form_submit_button("💾 Update", use_container_width=True)
            with col_del:
                del_btn = st.form_submit_button("🗑️ Delete", use_container_width=True)

            if upd_btn:
                new_row = {
                    "date"       : str(e_date),
                    "description": e_desc.strip(),
                    "category"   : e_cat,
                    "amount"     : round(float(e_amt), 2),
                    "paid_by"    : e_payer,
                    "split_pct"  : float(e_split),
                    "status"     : e_stat,
                    "notes"      : e_notes.strip() or None,
                }
                if e_receipt:
                    try:
                        new_url = upload_receipt(supabase, e_receipt.getvalue(), e_receipt.name)
                        if orig_url:
                            delete_receipt(supabase, orig_url)
                        new_row["receipt_url"] = new_url
                    except Exception as e:
                        st.warning(f"⚠️ Receipt upload failed: {e}")
                try:
                    update_expense(supabase, int(edit_id), new_row)
                    st.success("✅ Updated!")
                    st.cache_data.clear()
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ Update failed: {e}")

            if del_btn:
                try:
                    if orig_url:
                        delete_receipt(supabase, orig_url)
                    delete_expense(supabase, int(edit_id))
                    st.success("🗑️ Deleted!")
                    st.cache_data.clear()
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ Delete failed: {e}")

# ── Debug: raw data + balance math ──
with st.expander("🔧 Debug: Raw Data & Balance Math"):
    st.markdown(f"**Identity:** `{identity}` → `my_name={my_name}`, `other_name={other_name}`")
    if not df.empty:
        debug_df = df[["id","date","description","amount","paid_by","split_pct","status"]].copy()
        debug_df["paid_by_raw"] = debug_df["paid_by"]
        st.dataframe(debug_df[["id","description","amount","paid_by_raw","split_pct","status"]], use_container_width=True, hide_index=True)
        st.markdown("**Calculation (active only):**")
        for _, row in df.iterrows():
            if str(row.get("status","")).lower() in ("settled",): continue
            amt = float(row.get("amount",0))
            split = float(row.get("split_pct",50))/100
            p = str(row.get("paid_by","")).lower()
            if p == "me":
                st.info(f"  #{row['id']} {row['description'][:30]} — Viewer paid ${amt:.2f} → `other_owes` += ${amt*(1-split):.2f}")
            elif p == "other":
                st.info(f"  #{row['id']} {row['description'][:30]} — Co-parent paid ${amt:.2f} → `me_owes` += ${amt*split:.2f}")
            else:
                st.info(f"  #{row['id']} {row['description'][:30]} — Both, skipped")
        st.markdown(f"**Result:** `me_owes={me_owes}`, `other_owes={other_owes}`, **net={net:+.2f}**")
    else:
        st.info("No expenses yet.")

# ── Monthly + Category summary ──
if not df.empty:
    st.divider()
    col_m, col_c = st.columns(2)
    with col_m:
        st.subheader("📅 Monthly")
        monthly = (
            filtered.groupby(filtered["date"].dt.to_period("M"))["amount"]
            .sum().reset_index()
        )
        monthly["date"] = monthly["date"].astype(str).sort_values(key=lambda x: x, ascending=False)
        monthly.columns = ["Month", "Total ($)"]
        st.dataframe(monthly, use_container_width=True, hide_index=True)
    with col_c:
        st.subheader("📂 By Category")
        cat_sum = (
            filtered.groupby("category")["amount"]
            .agg(["sum","count"]).reset_index()
            .rename(columns={"sum":"Total ($)","count":"#"})
            .sort_values("Total ($)", ascending=False)
        )
        st.dataframe(cat_sum, use_container_width=True, hide_index=True)

# ── Switch parent ──
st.divider()
with st.expander("🔄 Switch parent identity"):
    st.info(f"Currently logged in as **{my_name}**")
    if st.button("Switch to the other parent"):
        st.session_state["identity"] = "mom" if identity == "me" else "me"
        st.rerun()

st.caption("Built with Streamlit · Data via Supabase · Both parents share the same live view")
