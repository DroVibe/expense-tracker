"""
Co-Parent Expense Tracker — Dashboard
Balances, quick-add, settle up with proof upload, and monthly summary.
"""

import streamlit as st
import pandas as pd
from datetime import date, datetime

from shared import (
    get_supabase, get_names, show_identity_picker, show_profile_switcher,
    CATEGORIES, load_expenses, insert_expense, update_expense,
    upload_receipt, upload_settlement_proof, delete_file,
    calc_balances, payer_share,
)

st.set_page_config(
    page_title="Expense Tracker — Dashboard",
    page_icon="🧾",
    layout="centered",
)

# ─── SESSION STATE ────────────────────────────────────────────────────────────

if "identity" not in st.session_state:
    st.session_state["identity"] = None

# ─── SUPABASE CHECK ────────────────────────────────────────────────────────────

supabase = get_supabase()

if supabase is None:
    st.title("Co-Parent Expense Tracker")
    st.divider()
    st.error("Supabase is not configured.")
    st.markdown(
        "### Setup Required\n\n"
        "Add your secrets in **Streamlit Cloud -> Settings -> Secrets**:\n\n"
        "```\n"
        'SUPABASE_URL = "https://xxxx.supabase.co"\n'
        'SUPABASE_KEY = "eyJ..."\n'
        "```\n\n"
        "Then run the migration to add settlement columns (see README)."
    )
    st.stop()

# ─── IDENTITY GATE ────────────────────────────────────────────────────────────

if st.session_state["identity"] is None:
    show_identity_picker()

identity = st.session_state["identity"]
my_name, other_name = get_names(identity)

# ─── LOAD DATA ────────────────────────────────────────────────────────────────

try:
    df = load_expenses(supabase)
except Exception:
    df = pd.DataFrame()

# ─── PAGE HEADER ──────────────────────────────────────────────────────────────

st.title("Expense Tracker")

col_nav, col_refresh = st.columns([4, 1])
with col_nav:
    st.page_link(
        "pages/2_Records.py",
        label="View All Records ->",
        use_container_width=True,
    )
with col_refresh:
    if st.button("Refresh", use_container_width=True):
        st.rerun()

st.caption(f"Logged in as **{my_name}** — both parents share the same live data")
st.divider()

# ─── BALANCE CARDS ────────────────────────────────────────────────────────────

if not df.empty:
    dad_owes_mom, mom_owes_dad = calc_balances(df)
else:
    dad_owes_mom, mom_owes_dad = 0.0, 0.0

net = dad_owes_mom - mom_owes_dad

c1, c2, c3 = st.columns(3)
with c1:
    color = st.error if dad_owes_mom > 0.01 else st.success
    color(f"**Dad owes Mom**\n**${dad_owes_mom:,.2f}**")
with c2:
    color = st.error if mom_owes_dad > 0.01 else st.success
    color(f"**Mom owes Dad**\n**${mom_owes_dad:,.2f}**")
with c3:
    if net > 0.01:
        st.warning(f"**Net: Dad owes Mom**\n**${abs(net):,.2f}**")
    elif net < -0.01:
        st.warning(f"**Net: Mom owes Dad**\n**${abs(net):,.2f}**")
    else:
        st.success("**All settled up!**\n**$0.00**")

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
#  ADD EXPENSE
# ══════════════════════════════════════════════════════════════════════════════

st.subheader("Add Expense")

with st.expander("Log a new expense", expanded=False):
    with st.form("add_form", clear_on_submit=True):
        col_pay, col_date = st.columns(2)
        with col_pay:
            paid_by = st.radio(
                "Who paid?",
                ["Dad", "Mom", "Both"],
                horizontal=True,
                help="Select who actually paid for this expense.",
            )
        with col_date:
            date_in = st.date_input("Date", value=date.today())

        desc = st.text_input(
            "Description *", placeholder="e.g. Groceries at Publix",
        )

        col_cat, col_amt = st.columns(2)
        with col_cat:
            cat = st.selectbox("Category", CATEGORIES)
        with col_amt:
            amt = st.number_input(
                "Amount ($) *", min_value=0.01, step=0.01, format="%.2f",
            )

        split = st.slider(
            "Dad's share %",
            0, 100, 50, step=5,
            help="How much of this expense is Dad's responsibility. The rest is Mom's.",
        )

        if amt > 0:
            dad_s = round(amt * split / 100, 2)
            mom_s = round(amt - dad_s, 2)
            st.caption(f"Dad pays **${dad_s:.2f}** · Mom pays **${mom_s:.2f}**")

        col_status, col_notes = st.columns(2)
        with col_status:
            status = st.selectbox("Status", ["active", "settled"])
        with col_notes:
            notes = st.text_input("Notes (optional)")

        receipt = st.file_uploader(
            "Receipt (optional)", type=["jpg", "jpeg", "png", "pdf"],
        )

        submitted = st.form_submit_button(
            "Save Expense", use_container_width=True,
        )

    if submitted:
        if not desc.strip():
            st.warning("Description is required.")
        elif amt <= 0:
            st.warning("Amount must be greater than $0.")
        else:
            row = {
                "date": str(date_in),
                "description": desc.strip(),
                "category": cat,
                "amount": round(float(amt), 2),
                "paid_by": paid_by,
                "split_pct": float(split),
                "status": status,
                "notes": notes.strip() or None,
            }
            if receipt:
                try:
                    url = upload_receipt(supabase, receipt.getvalue(), receipt.name)
                    if url:
                        row["receipt_url"] = url
                except Exception:
                    st.warning("Receipt upload failed — expense saved without it.")
            try:
                insert_expense(supabase, row)
                st.success("Expense saved!")
                st.rerun()
            except Exception as e:
                st.error(f"Save failed: {e}")

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
#  SETTLE UP  (with settlement proof upload)
# ══════════════════════════════════════════════════════════════════════════════

if not df.empty:
    active = df[df["status"].str.lower() != "settled"].copy()
    if not active.empty:
        st.subheader("Settle Up")
        st.markdown(
            "To settle an expense, upload a screenshot of your payment "
            "(Venmo, PayPal, Zelle, bank transfer, etc.).",
        )

        show_active = active.head(20)

        for _, r in show_active.iterrows():
            amt   = float(r["amount"])
            split = float(r.get("split_pct", 50))
            payer = str(r.get("paid_by", "?"))
            dad_s, mom_s = payer_share(amt, split, payer)

            # Who owes whom?
            owing = ""
            if payer == "Dad":
                owing = f"Mom owes Dad ${round(amt * (1 - split/100), 2):.2f}"
            elif payer == "Mom":
                owing = f"Dad owes Mom ${round(amt * split/100, 2):.2f}"

            with st.container():
                col_info, col_btn = st.columns([5, 1])
                with col_info:
                    st.markdown(
                        f"**#{r['id']}** — {r['description']}  "
                        f"| **${amt:.2f}** | {payer} paid",
                    )
                    st.caption(f"Due: {owing}")
                with col_btn:
                    if st.button(
                        "Settle",
                        key=f"sbtn_{r['id']}",
                        use_container_width=True,
                    ):
                        st.session_state[f"settle_expand_{r['id']}"] = True

                # ── Settlement modal (inline expander) ──────────────────────
                if st.session_state.get(f"settle_expand_{r['id']}"):
                    with st.expander(f"📋 Settle Expense #{r['id']} — upload proof", expanded=True):
                        with st.form(f"settle_form_{r['id']}", clear_on_submit=True):
                            owed = dad_s if payer == "Mom" else mom_s
                            owing_to = "Dad" if payer == "Mom" else "Mom"
                            st.markdown(
                                f"**{payer}** pays **${owed:.2f}** to **{owing_to}** — upload a screenshot as proof."
                            )

                            proof = st.file_uploader(
                                "💳 Payment screenshot (Venmo, PayPal, Zelle, etc.) *",
                                type=["jpg", "jpeg", "png", "pdf"],
                                key=f"proof_file_{r['id']}",
                            )
                            settle_note = st.text_input(
                                "Note (optional)",
                                placeholder="e.g. Venmo @username, $42.50",
                                key=f"proof_note_{r['id']}",
                            )

                            col_ok, col_cancel = st.columns(2)
                            with col_ok:
                                submitted_settle = st.form_submit_button(
                                    "✅ Confirm & Settle",
                                    use_container_width=True,
                                )
                            with col_cancel:
                                if st.form_submit_button(
                                    "Cancel", use_container_width=True,
                                ):
                                    st.session_state[f"settle_expand_{r['id']}"] = False
                                    st.rerun()

                        if submitted_settle:
                            if not proof:
                                st.warning("Please upload a payment screenshot first.")
                            else:
                                proof_url = upload_settlement_proof(
                                    supabase, proof.getvalue(), proof.name,
                                )
                                if not proof_url:
                                    st.error("Proof upload failed. Try again.")
                                else:
                                    row_update = {
                                        "status": "settled",
                                        "settled_by": my_name,
                                        "settled_at": datetime.utcnow().isoformat(),
                                        "settlement_proof_url": proof_url,
                                        "settlement_note": settle_note.strip() or None,
                                    }
                                    try:
                                        update_expense(
                                            supabase, int(r["id"]), row_update,
                                        )
                                        st.session_state[f"settle_expand_{r['id']}"] = False
                                        st.success(
                                            f"✅ Settled! Proof uploaded for #{r['id']}.",
                                        )
                                        st.rerun()
                                    except Exception as e:
                                        st.error(f"Settlement failed: {e}")

                st.divider()

        if len(active) > 20:
            st.info(
                f"{len(active) - 20} more active expenses. "
                "Open **Records** to see all.",
            )

# ─── Monthly Summary ────────────────────────────────────────────────────────

if not df.empty:
    st.subheader("Monthly Spending")
    monthly = (
        df.groupby(df["date"].dt.to_period("M"))["amount"]
        .sum()
        .reset_index()
    )
    if not monthly.empty:
        monthly.columns = ["Month", "Total ($)"]
        monthly["Month"] = monthly["Month"].astype(str)
        monthly = monthly.sort_values("Month", ascending=False)
        st.bar_chart(monthly.set_index("Month"), y="Total ($)")
        with st.expander("View table"):
            st.dataframe(monthly, use_container_width=True, hide_index=True)

# ─── Footer ─────────────────────────────────────────────────────────────────

st.divider()
show_profile_switcher(identity)

# ── PWA Install Guide ──────────────────────────────
if not st.session_state.get("_pwa_dismissed", False):
    with st.expander("\U0001f4f1 Add to Home Screen \u2014 install as an app on your iPhone", expanded=False):
        PWA_GUIDE = (
            "<style>"
            ".pwa-guide-card { background:#0f172a; border:1px solid rgba(148,163,184,0.15); "
            "border-radius:10px; padding:14px; } "
            ".pwa-step { display:flex; align-items:flex-start; gap:10px; margin-bottom:9px; } "
            ".pwa-step-num { background:#6366f1; color:white; font-size:11px; font-weight:700; "
            "width:20px; height:20px; border-radius:50%; display:flex; align-items:center; "
            "justify-content:center; flex-shrink:0; margin-top:1px; } "
            ".pwa-step-text { font-size:12px; color:#cbd5e1; line-height:1.5; } "
            ".pwa-step-text strong { color:#e2e8f0; } "
            "</style>"
            "<div class=\"pwa-guide-card\">"
            "<div class=\"pwa-step\"><div class=\"pwa-step-num\">1</div>"
            "<div class=\"pwa-step-text\"><strong>Open Safari</strong> \u2014 tap the Share button at the bottom</div></div>"
            "<div class=\"pwa-step\"><div class=\"pwa-step-num\">2</div>"
            "<div class=\"pwa-step-text\"><strong>Scroll down</strong> \u2014 tap \"Add to Home Screen\"</div></div>"
            "<div class=\"pwa-step\"><div class=\"pwa-step-num\">3</div>"
            "<div class=\"pwa-step-text\"><strong>Tap Add</strong> \u2014 the icon appears on your home screen</div></div>"
            "</div>"
        )
        st.markdown(PWA_GUIDE, unsafe_allow_html=True)
        if st.button("\u2713 Dismiss", use_container_width=True):
            st.session_state["_pwa_dismissed"] = True
            st.rerun()

st.caption("Built with Streamlit \xb7 Data via Supabase \xb7 Both parents share the same live view")
