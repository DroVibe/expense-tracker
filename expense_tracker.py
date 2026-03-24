"""
Co-Parent Expense Tracker
Full CRUD via Supabase — both parents can add, edit, settle expenses & attach receipts.
"""

import streamlit as st
import pandas as pd
from datetime import date
from supabase import create_client, Client
import uuid

# ─── PAGE CONFIG ──────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Co-Parent Expense Tracker",
    page_icon="🧾",
    layout="centered",
)

# ─── SESSION STATE ───────────────────────────────────────────────────────────

if "identity" not in st.session_state:
    st.session_state["identity"] = None

# ─── SUPABASE CLIENT ──────────────────────────────────────────────────────────

@st.cache_resource
def get_supabase() -> Client | None:
    """Return Supabase client, or None if secrets are missing/invalid."""
    try:
        url = st.secrets.get("SUPABASE_URL")
        key = st.secrets.get("SUPABASE_KEY")
    except Exception:
        url, key = None, None

    if not url or not key or url == "your_url_here":
        return None
    try:
        return create_client(url, key)
    except Exception:
        return None

# ─── STORAGE HELPERS ──────────────────────────────────────────────────────────

BUCKET = "receipts"

def upload_receipt(supabase: Client, file_bytes: bytes, filename: str) -> str:
    ext = filename.split(".")[-1] if "." in filename else "jpg"
    path = f"{uuid.uuid4().hex}.{ext}"
    supabase.storage.from_(BUCKET).upload(path, file_bytes)
    return supabase.storage.from_(BUCKET).get_public_url(path)

def delete_receipt(supabase: Client, url: str) -> None:
    if not url:
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

# ─── HELPERS ──────────────────────────────────────────────────────────────────

def identity_name(viewer: str, role: str) -> str:
    """Map neutral 'Me'/'Other' to Dad/Mom based on who's viewing."""
    if viewer == "me":
        return "Dad" if role == "Me" else "Mom"
    return "Mom" if role == "Me" else "Dad"

def calc_balances(df: pd.DataFrame, identity: str) -> tuple[float, float]:
    """
    Returns (i_owe, owed_to_me) — both always from the VIEWER'S perspective.
    identity 'me' = Dad; identity 'mom' = Mom.

    Logic:
      - Stored payer = "Me"  → the person who logged this expense paid
      - Stored payer = "Other" → the co-parent paid
      - "I owe"       = viewer's share of what the CO-PARENT paid
      - "Owed to me"  = my share of what I paid (i.e. what co-parent owes me)
    """
    i_owe, owed_to_me = 0.0, 0.0

    for _, row in df.iterrows():
        if str(row.get("status", "")).lower() in ("settled",):
            continue
        amt   = float(row.get("amount", 0))
        split = float(row.get("split_pct", 50)) / 100.0
        p     = str(row.get("paid_by", "")).strip().lower()

        if p == "both":
            continue

        if p == "me":
            # The viewer logged this expense → viewer paid → co-parent owes viewer's share
            owed_to_me += amt * (1 - split)

        elif p == "other":
            # Co-parent paid → viewer owes co-parent's share
            i_owe += amt * split

    return round(i_owe, 2), round(owed_to_me, 2)

CATEGORIES = [
    "Groceries", "Kids", "Medical", "Transportation",
    "Entertainment", "Clothing", "School", "Other"
]

# ══════════════════════════════════════════════════════════════════════════════
#  SETUP CHECK — must run before any feature UI
# ══════════════════════════════════════════════════════════════════════════════

supabase = get_supabase()
_is_configured = supabase is not None

def render_setup_warning():
    st.title("🧾 Co-Parent Expense Tracker")
    st.divider()
    st.error("⚠️ Supabase is not configured.")
    st.markdown("### 🔧 Setup Required")
    st.markdown(
        "This app needs a **Supabase project** to store your expense data. "
        "Follow these steps to get it running:\n\n"
        "**Step 1:** Go to [supabase.com](https://supabase.com) → Create a free project.\n\n"
        "**Step 2:** In your Supabase project, go to **SQL Editor** and run:\n"
    )
    st.code("""
CREATE TABLE expenses (
  id          SERIAL PRIMARY KEY,
  date        DATE,
  description TEXT,
  category    TEXT,
  amount      NUMERIC,
  paid_by     TEXT,
  split_pct   NUMERIC DEFAULT 50,
  status      TEXT DEFAULT 'active',
  notes       TEXT,
  receipt_url TEXT,
  created_at  TIMESTAMP DEFAULT NOW()
);

ALTER TABLE expenses ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Allow all" ON expenses FOR ALL USING (true) WITH CHECK (true);

CREATE TABLE expenses (
  id          SERIAL PRIMARY KEY,
  date        DATE,
  description TEXT,
  category    TEXT,
  amount      NUMERIC,
  paid_by     TEXT,
  split_pct   NUMERIC DEFAULT 50,
  status      TEXT DEFAULT 'active',
  notes       TEXT,
  receipt_url TEXT,
  created_at  TIMESTAMP DEFAULT NOW()
);
    """, language="sql")
    st.markdown(
        "**Step 3:** In Supabase → **Storage** → **New bucket** → name it `receipts` "
        "and make it **Public**.\n\n"
        "**Step 4:** In Supabase → **Settings → API**, copy your:\n"
        "- `Project URL`\n"
        "- `anon public` key\n\n"
        "**Step 5:** Add these secrets in Streamlit Cloud:\n"
        "→ Go to [share.streamlit.io](https://share.streamlit.io) → your app → **Settings → Secrets**\n"
        "→ Add:\n"
    )
    st.code("""
SUPABASE_URL = "https://xxxxx.supabase.co"
SUPABASE_KEY = "eyJhbGc..."
    """)
    st.markdown("→ Click **Save** → the app will refresh and load your data.")
    st.stop()

# ══════════════════════════════════════════════════════════════════════════════
#  LANDING / IDENTITY SELECTOR
# ══════════════════════════════════════════════════════════════════════════════

if not _is_configured:
    render_setup_warning()

if st.session_state["identity"] is None:
    st.title("🧾 Co-Parent Expense Tracker")
    st.markdown("##### Track, split, and settle expenses together — in real time.")
    st.markdown("Both parents share the same live view. All data is stored securely.")
    st.divider()

    st.markdown("### 👋 Who's viewing the tracker?")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**👤 Me / Dad**")
        st.caption("Track your expenses. See who owes what.")
        if st.button("Continue as Me (Dad)", use_container_width=True):
            st.session_state["identity"] = "me"
            st.rerun()
    with c2:
        st.markdown("**👤 Mom**")
        st.caption("Track your expenses. See who owes what.")
        if st.button("Continue as Mom", use_container_width=True):
            st.session_state["identity"] = "mom"
            st.rerun()

    st.divider()
    ci1, ci2 = st.columns(2)
    with ci1:
        st.markdown("**📋 What this tracker does**")
        st.markdown(
            "- Log any shared expense\n"
            "- Split costs fairly (default 50/50)\n"
            "- Attach receipt photos\n"
            "- Mark expenses as settled\n"
            "- Both parents see everything live"
        )
    with ci2:
        st.markdown("**🔒 How data is stored**")
        st.markdown(
            "- All data saved to Supabase (secure cloud DB)\n"
            "- Receipt images stored in Supabase Storage\n"
            "- No logins needed — shared URL is all you need\n"
            "- Data persists even when the app is closed"
        )
    st.stop()

# ─── ACTIVE APP ───────────────────────────────────────────────────────────────

identity   = st.session_state["identity"]
my_name    = identity_name(identity, "Me")
other_name = identity_name(identity, "Other")

st.title("🧾 Expense Tracker")
st.caption(f"Logged in as **{my_name}** · Both parents share the same live data")

# ── Refresh button ──
if st.button("🔄 Refresh Data", use_container_width=True):
    st.cache_data.clear()
    st.rerun()

st.divider()

# ── Load data ──
try:
    df = load_expenses(supabase)
except Exception as e:
    st.error(f"❌ Could not load data from Supabase: {e}")
    df = pd.DataFrame()

# ── Balance cards ──
if not df.empty:
    i_owe, owed_to_me = calc_balances(df, identity)
    net = owed_to_me - i_owe
else:
    i_owe, owed_to_me, net = 0.0, 0.0, 0.0

c1, c2, c3 = st.columns(3)
with c1:
    (st.error if i_owe > 0 else st.success)(
        f"**{my_name}** owes  \n**${i_owe:,.2f}**"
    )
with c2:
    (st.success if owed_to_me > 0 else st.info)(
        f"**{other_name}** owes you  \n**${owed_to_me:,.2f}**"
    )
with c3:
    if net > 0.05:
        st.metric("Net", f"+${net:,.2f}", delta="You're owed")
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
            help="Me = you. Other = the co-parent."
        )
        date_in = st.date_input("Date", value=date.today())
        desc    = st.text_input("Description *", placeholder="e.g. Groceries at Publix")
        cat     = st.selectbox("Category", CATEGORIES)
        amt     = st.number_input("Amount ($) *", min_value=0.01, step=0.01, format="%.2f")
        split   = st.slider(f"{my_name}'s split %", 0, 100, 50, step=5)
        status  = st.selectbox("Status", ["active", "settled"])
        notes   = st.text_input("Notes (optional)", placeholder="Any extra details…")
        receipt = st.file_uploader(
            "🧾 Receipt (optional)",
            type=["jpg", "jpeg", "png", "pdf"],
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
            if receipt:
                try:
                    url = upload_receipt(supabase, receipt.getvalue(), receipt.name)
                    row["receipt_url"] = url
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
    # Safe filter defaults
    min_d = df["date"].min().date() if pd.notna(df["date"].min()) else date.today()
    max_d = df["date"].max().date() if pd.notna(df["date"].max()) else date.today()

    f1, f2, f3, f4 = st.columns(4)
    with f1:
        start = st.date_input("From", value=min_d)
    with f2:
        end   = st.date_input("To",   value=max_d)
    with f3:
        cats  = ["All"] + sorted(df["category"].dropna().unique().tolist())
        cat_f = st.selectbox("Category", cats)
    with f4:
        stat_f = st.selectbox("Status", ["All", "active", "settled"])

    mask = pd.Series(True, index=df.index)
    if pd.notna(start): mask &= df["date"] >= pd.Timestamp(start)
    if pd.notna(end):   mask &= df["date"] <= pd.Timestamp(end)
    if cat_f  != "All":  mask &= df["category"] == cat_f
    if stat_f != "All":  mask &= df["status"] == stat_f

    filtered = df[mask].sort_values("date", ascending=False).reset_index(drop=True)

    for col in ["receipt_url"]:
        if col not in filtered.columns:
            filtered[col] = None

    # Map neutral payer to display name
    def display_payer(p):
        p = str(p).strip().lower()
        if p == "me":    return my_name
        if p == "other": return other_name
        return p.title()

    filtered["_display_payer"] = filtered["paid_by"].apply(display_payer)

    disp = filtered[["id","date","description","category","amount","_display_payer","split_pct","status"]].copy()
    disp.columns = ["ID","Date","Description","Category","Amount ($)","Paid by","Split (%)","Status"]

    # Add receipt column as markdown link
    def receipt_link(u):
        if not u: return "—"
        fname = u.split("/")[-1].split("?")[0]
        return f"[🧾 {fname}]({u})"
    disp["Receipt"] = filtered["receipt_url"].apply(receipt_link)

    st.dataframe(disp, use_container_width=True, hide_index=True)

    # ── Receipt preview (no urllib) ──
    receipt_rows = filtered[filtered["receipt_url"].notna()]
    if not receipt_rows.empty:
        st.divider()
        st.subheader("🧾 Receipts")
        for _, r in receipt_rows.iterrows():
            fname = r["receipt_url"].split("/")[-1].split("?")[0]
            with st.container():
                col_r, col_l = st.columns([1, 2])
                with col_r:
                    st.markdown(f"**#{r['id']}** — {r['description']}")
                    # st.image handles both URLs and local paths
                    try:
                        st.image(r["receipt_url"], width=220, caption=f"Receipt #{r['id']}")
                    except Exception:
                        st.markdown(f"[🖼️ Open receipt]({r['receipt_url']})")
                with col_l:
                    st.markdown(f"**#{r['id']} — {r['description']}**")
                    st.markdown(f"Amount: **${float(r['amount']):.2f}**  |  Paid by: **{r['_display_payer']}**")
                    st.markdown(f"[🔗 Open in new tab]({r['receipt_url']})")
                    st.markdown(f"[📥 Download receipt]({r['receipt_url']})")
                st.divider()

    # ── EDIT / DELETE ──
    st.divider()
    st.subheader("✏️ Edit or Delete an Expense")

    exp_rows = filtered.to_dict("records")
    if not exp_rows:
        st.info("No expenses match your current filters.")
    else:
        options = {f"#{r['id']}  —  {str(r['description'])[:40]}": r["id"] for r in exp_rows}
        labels  = list(options.keys())
        sel     = st.selectbox("Select expense", [""] + labels)

        if sel:
            eid     = options[sel]
            row     = filtered[filtered["id"] == eid].iloc[0]
            orig_url = str(row.get("receipt_url") or "")

            with st.form(f"edit_{eid}", clear_on_submit=False):
                e_date = st.date_input(
                    "Date",
                    value=pd.to_datetime(row["date"]).date() if pd.notna(row["date"]) else date.today(),
                    key=f"e_date_{eid}",
                )
                e_desc = st.text_input("Description", value=str(row["description"] or ""), key=f"e_desc_{eid}")
                e_cat  = st.selectbox(
                    "Category", CATEGORIES,
                    index=CATEGORIES.index(row["category"]) if row["category"] in CATEGORIES else 0,
                    key=f"e_cat_{eid}",
                )
                e_amt  = st.number_input(
                    "Amount ($)", value=float(row["amount"]),
                    min_value=0.01, step=0.01, format="%.2f", key=f"e_amt_{eid}",
                )
                # Map stored payer to neutral
                stored = str(row.get("paid_by","")).strip().lower()
                payer_map = {"me": "Me", "other": "Other", "both": "Both"}
                neutral_stored = payer_map.get(stored, "Me")
                e_payer = st.selectbox(
                    "Who paid?", ["Me", "Other", "Both"],
                    index=["Me", "Other", "Both"].index(neutral_stored),
                    key=f"e_payer_{eid}",
                )
                e_split = st.slider(
                    f"{my_name}'s split %", 0, 100,
                    int(float(row.get("split_pct", 50))), step=5,
                    key=f"e_split_{eid}",
                )
                e_stat = st.selectbox(
                    "Status", ["active", "settled"],
                    index=["active", "settled"].index(row.get("status","active"))
                    if row.get("status","active") in ["active","settled"] else 0,
                    key=f"e_stat_{eid}",
                )
                e_notes = st.text_input("Notes", value=str(row.get("notes") or ""), key=f"e_notes_{eid}")

                if orig_url:
                    st.markdown(f"📎 Current receipt: [Open receipt]({orig_url})")
                e_receipt = st.file_uploader(
                    "🧾 Replace receipt (leave empty to keep current)",
                    type=["jpg", "jpeg", "png", "pdf"],
                    key=f"e_receipt_{eid}",
                )

                cu, cd = st.columns(2)
                with cu:
                    upd = st.form_submit_button("💾 Update", use_container_width=True)
                with cd:
                    del_ = st.form_submit_button("🗑️ Delete", use_container_width=True,
                                                  type="primary")

                if upd:
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
                        update_expense(supabase, int(eid), new_row)
                        st.success("✅ Updated!")
                        st.cache_data.clear()
                        st.rerun()
                    except Exception as e:
                        st.error(f"❌ Update failed: {e}")

                if del_:
                    try:
                        if orig_url:
                            delete_receipt(supabase, orig_url)
                        delete_expense(supabase, int(eid))
                        st.success("🗑️ Deleted!")
                        st.cache_data.clear()
                        st.rerun()
                    except Exception as e:
                        st.error(f"❌ Delete failed: {e}")

# ── Monthly + Category summary ──
if not df.empty:
    st.divider()
    cm, cc = st.columns(2)
    with cm:
        st.subheader("📅 Monthly")
        monthly = (
            filtered
            .groupby(filtered["date"].dt.to_period("M"))["amount"]
            .sum()
            .reset_index()
        )
        if not monthly.empty:
            monthly["date"] = monthly["date"].astype(str)
            monthly = monthly.sort_values("date", ascending=False)
            monthly.columns = ["Month", "Total ($)"]
            st.dataframe(monthly, use_container_width=True, hide_index=True)
        else:
            st.info("No data in selected range.")
    with cc:
        st.subheader("📂 By Category")
        cat_sum = (
            filtered.groupby("category")["amount"]
            .agg(["sum", "count"]).reset_index()
            .rename(columns={"sum": "Total ($)", "count": "#"})
            .sort_values("Total ($)", ascending=False)
        )
        if not cat_sum.empty:
            st.dataframe(cat_sum, use_container_width=True, hide_index=True)
        else:
            st.info("No data in selected range.")

# ── Debug ──
if not df.empty:
    with st.expander("🔧 Debug: Raw Data & Balance Math"):
        st.markdown(
            f"**Identity:** `{identity}` → my_name=`{my_name}`, other_name=`{other_name}`"
        )
        debug_cols = ["id","description","amount","paid_by","split_pct","status"]
        st.dataframe(
            df[debug_cols] if all(c in df.columns for c in debug_cols) else df,
            use_container_width=True, hide_index=True,
        )
        st.markdown(f"**Result:** `i_owe={i_owe}`, `owed_to_me={owed_to_me}`, **net={net:+.2f}**")

# ── Switch parent ──
st.divider()
with st.expander("🔄 Switch parent identity"):
    st.info(f"Currently viewing as **{my_name}**")
    if st.button("Switch to the other parent"):
        st.session_state["identity"] = "mom" if identity == "me" else "me"
        st.rerun()

st.caption("Built with Streamlit · Data via Supabase · Both parents share the same live view")
