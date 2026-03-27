"""
Co-Parent Expense Tracker — Records Page
Full expense log with filters, search, export, inline edit/delete with confirmation,
and settlement proof upload for settling parents.
"""

import streamlit as st
import pandas as pd
from datetime import date, datetime
from io import BytesIO

from shared import (
    get_supabase, get_names, show_identity_picker, show_profile_switcher,
    CATEGORIES, load_expenses, update_expense, delete_expense,
    upload_receipt, delete_file, upload_settlement_proof, payer_share,
)

st.set_page_config(
    page_title="Expense Tracker — Records",
    page_icon="🧾",
    layout="centered",
)

# ─── SESSION STATE ────────────────────────────────────────────────────────────

if "identity" not in st.session_state:
    st.session_state["identity"] = None

# ─── SUPABASE CHECK ──────────────────────────────────────────────────────────

supabase = get_supabase()

if supabase is None:
    st.title("Expense Tracker — Records")
    st.divider()
    st.error("Supabase not configured. Add secrets in Streamlit Cloud settings.")
    st.stop()

if st.session_state["identity"] is None:
    show_identity_picker()

identity = st.session_state["identity"]
my_name, other_name = get_names(identity)

# ─── LOAD DATA ────────────────────────────────────────────────────────────────

try:
    df = load_expenses(supabase)
except Exception:
    df = pd.DataFrame()

# ─── PAGE HEADER ─────────────────────────────────────────────────────────────

st.title("All Records")
st.caption(f"Logged in as **{my_name}** — {len(df)} total expenses")

col_back, col_refresh = st.columns([4, 1])
with col_back:
    st.page_link(
        "expense_tracker.py",
        label="<- Back to Dashboard",
        use_container_width=False,
    )
with col_refresh:
    if st.button("Refresh"):
        st.rerun()

st.divider()

# ─── EMPTY STATE ──────────────────────────────────────────────────────────────

if df.empty:
    st.info("No expenses yet. Go to Dashboard to add one.")
    st.stop()

# ─── FILTERS ──────────────────────────────────────────────────────────────────

min_d = df["date"].min().date()
max_d = df["date"].max().date()

with st.expander("Filters & Search", expanded=True):
    search = st.text_input(
        "Search descriptions",
        placeholder="e.g. Publix, soccer, doctor...",
    )
    f1, f2, f3, f4, f5 = st.columns(5)
    with f1:
        start = st.date_input("From", value=min_d)
    with f2:
        end = st.date_input("To", value=max_d)
    with f3:
        cats = ["All"] + sorted(df["category"].dropna().unique().tolist())
        cat_f = st.selectbox("Category", cats)
    with f4:
        stat_f = st.selectbox("Status", ["All", "Active", "Settled"])
    with f5:
        payer_f = st.selectbox("Paid by", ["All", "Dad", "Mom", "Both"])

# Apply filters
mask = pd.Series(True, index=df.index)
if pd.notna(start):
    mask &= df["date"] >= pd.Timestamp(start)
if pd.notna(end):
    mask &= df["date"] <= pd.Timestamp(end)
if cat_f != "All":
    mask &= df["category"] == cat_f
if stat_f == "Active":
    mask &= df["status"].str.lower() == "active"
elif stat_f == "Settled":
    mask &= df["status"].str.lower() == "settled"
if payer_f != "All":
    mask &= df["paid_by"].str.lower() == payer_f.lower()
if search.strip():
    mask &= df["description"].str.contains(search.strip(), case=False, na=False)

filtered = df[mask].sort_values("date", ascending=False).reset_index(drop=True)

st.markdown(
    f"**{len(filtered)}** expenses shown  ·  "
    f"**${filtered['amount'].sum():,.2f}** total",
)

# ─── SUMMARY METRICS ─────────────────────────────────────────────────────────

active_df  = filtered[filtered["status"].str.lower() != "settled"]
settled_df = filtered[filtered["status"].str.lower() == "settled"]

sc1, sc2, sc3 = st.columns(3)
with sc1:
    st.metric("Active", len(active_df), f"${active_df['amount'].sum():,.2f}")
with sc2:
    st.metric("Settled", len(settled_df), f"${settled_df['amount'].sum():,.2f}")
with sc3:
    st.metric("Total", len(filtered), f"${filtered['amount'].sum():,.2f}")

# ─── EXPORT ──────────────────────────────────────────────────────────────────

if not filtered.empty:
    export_df = filtered.copy()
    export_df["date"] = export_df["date"].dt.strftime("%Y-%m-%d")
    cols_to_export = [
        c for c in [
            "id", "date", "description", "category", "amount",
            "paid_by", "split_pct", "status", "notes",
        ] if c in export_df.columns
    ]
    csv_bytes = export_df[cols_to_export].to_csv(index=False).encode("utf-8")
    st.download_button(
        "Download CSV",
        data=csv_bytes,
        file_name="expenses.csv",
        mime="text/csv",
        use_container_width=True,
    )

st.divider()

# ─── EXPENSE CARDS ───────────────────────────────────────────────────────────

if filtered.empty:
    st.info("No expenses match your filters.")
else:
    for _, r in filtered.iterrows():
        is_active      = str(r.get("status", "")).lower() != "settled"
        amt            = float(r["amount"])
        split          = float(r.get("split_pct", 50))
        payer          = str(r.get("paid_by", "?"))
        dad_s, mom_s   = payer_share(amt, split, payer)
        receipt_url    = r.get("receipt_url") or None
        proof_url      = r.get("settlement_proof_url") or None
        settled_by     = r.get("settled_by") or None
        settled_at     = r.get("settled_at") or None
        settle_note    = r.get("settlement_note") or None

        # Determine who owes on this active expense
        if is_active:
            if payer == "Dad":
                owe_summary = f"Dad owes Mom **${mom_s:.2f}**"
            elif payer == "Mom":
                owe_summary = f"Mom owes Dad **${dad_s:.2f}**"
            else:
                owe_summary = "Each parent pays their share"
        else:
            owe_summary = None

        with st.container():
            # ── Card header ──
            col_left, col_right = st.columns([5, 1])
            with col_left:
                label = "Active" if is_active else "Settled"
                colour = "🟢" if is_active else "✅"
                st.markdown(
                    f"### {colour} #{r['id']} — {r['description']}\n"
                    f"{label}  ·  **${amt:.2f}**  ·  "
                    f"Paid by **{payer}**  ·  "
                    f"Dad {split:.0f}% / Mom {100-split:.0f}%",
                )
                if owe_summary:
                    st.caption(owe_summary)
            with col_right:
                if is_active:
                    if st.button(
                        "Settle",
                        key=f"sbtn_rec_{r['id']}",
                        use_container_width=True,
                    ):
                        st.session_state[f"settle_expand_rec_{r['id']}"] = True
                else:
                    st.markdown("✅ Settled")

            # ── Details row ──
            det1, det2, det3, det4 = st.columns(4)
            with det1:
                date_str = (
                    pd.to_datetime(r["date"]).strftime("%b %d, %Y")
                    if pd.notna(r["date"]) else "—"
                )
                st.markdown(f"**Date**\n{date_str}")
            with det2:
                st.markdown(f"**Category**\n{r.get('category', '—')}")
            with det3:
                st.markdown(f"**Dad's share**\n**${dad_s:.2f}**")
            with det4:
                st.markdown(f"**Mom's share**\n**${mom_s:.2f}**")

            if r.get("notes"):
                st.markdown(f"**Notes:** {r['notes']}")

            # ── Settlement proof banner (settled items) ──────────────────────
            if not is_active and proof_url:
                st.divider()
                st.markdown("**💳 Settlement Proof**")
                proof_col_text, proof_col_btn = st.columns([3, 1])
                with proof_col_text:
                    when_str = ""
                    if settled_at:
                        try:
                            when_str = pd.to_datetime(settled_at).strftime("%b %d, %Y")
                        except Exception:
                            when_str = str(settled_at)
                    st.markdown(
                        f"Settled by **{settled_by or 'Unknown'}**"
                        + (f" on {when_str}" if when_str else "")
                        + ("." if settle_note is None else f": {settle_note}"),
                    )
                with proof_col_btn:
                    st.link_button("Open Proof", proof_url, use_container_width=True)
                ext = proof_url.rsplit(".", 1)[-1].split("?")[0].lower()
                if ext in ("jpg", "jpeg", "png", "gif"):
                    try:
                        st.image(proof_url, width=400, caption="Settlement proof")
                    except Exception:
                        pass

            # ── Receipt (active/purchase receipt) ─────────────────────────────
            if receipt_url:
                st.divider()
                st.markdown("**🧾 Receipt**")
                ext = receipt_url.rsplit(".", 1)[-1].split("?")[0].lower()
                if ext in ("jpg", "jpeg", "png", "gif"):
                    try:
                        st.image(receipt_url, width=300, caption=f"Receipt #{r['id']}")
                    except Exception:
                        st.markdown(f"[Open receipt]({receipt_url})")
                else:
                    st.markdown(f"[Open receipt (PDF)]({receipt_url})")
                st.link_button("Open / Download Receipt", receipt_url)

            # ── Settlement upload expander (active items) ────────────────────
            if is_active and st.session_state.get(f"settle_expand_rec_{r['id']}"):
                st.divider()
                with st.expander(
                    f"📋 Settle Expense #{r['id']} — upload payment proof",
                    expanded=True,
                ):
                    with st.form(f"rec_settle_{r['id']}", clear_on_submit=True):
                        # Who owes whom + how much
                        owing_amount = dad_s if payer == "Mom" else mom_s
                        owing_to = "Dad" if payer == "Mom" else "Mom"
                        owing_parent = my_name if my_name != payer else other_name

                        st.markdown(
                            f"**{owing_parent}** pays **{owing_amount:.2f}** to "
                            f"**{owing_to}**. Upload a payment screenshot to settle.",
                        )

                        proof = st.file_uploader(
                            "💳 Payment screenshot (Venmo, PayPal, Zelle, etc.) *",
                            type=["jpg", "jpeg", "png", "pdf"],
                            key=f"rec_proof_{r['id']}",
                        )
                        s_note = st.text_input(
                            "Note (optional)",
                            placeholder="e.g. Venmo @username, $42.50",
                            key=f"rec_note_{r['id']}",
                        )

                        col_ok, col_cancel = st.columns(2)
                        with col_ok:
                            done = st.form_submit_button(
                                "✅ Confirm & Settle",
                                use_container_width=True,
                            )
                        with col_cancel:
                            if st.form_submit_button("Cancel", use_container_width=True):
                                st.session_state.pop(f"settle_expand_rec_{r['id']}", None)
                                st.rerun()

                        if done:
                            if not proof:
                                st.warning("Please upload a payment screenshot first.")
                            else:
                                proof_url_up = upload_settlement_proof(
                                    supabase,
                                    proof.getvalue(),
                                    proof.name,
                                )
                                if not proof_url_up:
                                    st.error("Proof upload failed. Try again.")
                                else:
                                    try:
                                        update_expense(
                                            supabase, int(r["id"]),
                                            {
                                                "status": "settled",
                                                "settled_by": my_name,
                                                "settled_at": datetime.utcnow().isoformat(),
                                                "settlement_proof_url": proof_url_up,
                                                "settlement_note": s_note.strip() or None,
                                            },
                                        )
                                        st.session_state.pop(
                                            f"settle_expand_rec_{r['id']}", None,
                                        )
                                        st.success(
                                            f"✅ Settled! Proof uploaded for #{r['id']}.",
                                        )
                                        st.rerun()
                                    except Exception as e:
                                        st.error(f"Settlement failed: {e}")

            # ── Edit / Delete ──
            with st.expander(f"Edit or Delete expense #{r['id']}"):
                with st.form(f"edit_{r['id']}", clear_on_submit=False):
                    e_date = st.date_input(
                        "Date",
                        value=(
                            pd.to_datetime(r["date"]).date()
                            if pd.notna(r["date"]) else date.today()
                        ),
                        key=f"e_date_{r['id']}",
                    )
                    e_desc = st.text_input(
                        "Description",
                        value=str(r.get("description", "") or ""),
                        key=f"e_desc_{r['id']}",
                    )
                    col_ec, col_ea = st.columns(2)
                    with col_ec:
                        e_cat = st.selectbox(
                            "Category", CATEGORIES,
                            index=(
                                CATEGORIES.index(r["category"])
                                if r.get("category") in CATEGORIES else 0
                            ),
                            key=f"e_cat_{r['id']}",
                        )
                    with col_ea:
                        e_amt = st.number_input(
                            "Amount ($)",
                            value=float(r["amount"]),
                            min_value=0.01, step=0.01, format="%.2f",
                            key=f"e_amt_{r['id']}",
                        )
                    e_payer = st.radio(
                        "Who paid?",
                        ["Dad", "Mom", "Both"],
                        index=["Dad", "Mom", "Both"].index(payer)
                        if payer in ["Dad", "Mom", "Both"] else 0,
                        horizontal=True,
                        key=f"e_payer_{r['id']}",
                    )
                    e_split = st.slider(
                        "Dad's share %",
                        0, 100, int(split), step=5,
                        key=f"e_split_{r['id']}",
                    )
                    if e_amt > 0:
                        preview_dad = round(float(e_amt) * e_split / 100, 2)
                        preview_mom = round(float(e_amt) - preview_dad, 2)
                        st.caption(f"Dad: **${preview_dad:.2f}** · Mom: **${preview_mom:.2f}**")
                    col_es, col_en = st.columns(2)
                    with col_es:
                        e_stat = st.selectbox(
                            "Status", ["active", "settled"],
                            index=(
                                ["active", "settled"].index(r.get("status", "active"))
                                if r.get("status", "active") in ["active", "settled"]
                                else 0
                            ),
                            key=f"e_stat_{r['id']}",
                        )
                    with col_en:
                        e_notes = st.text_input(
                            "Notes",
                            value=str(r.get("notes") or ""),
                            key=f"e_notes_{r['id']}",
                        )

                    # Show current receipts / proof if present
                    if receipt_url:
                        st.markdown("**Current purchase receipt:**")
                        st.link_button("View Receipt", receipt_url)
                    if proof_url:
                        st.markdown("**Current settlement proof:**")
                        st.link_button("View Proof", proof_url)
                    e_receipt = st.file_uploader(
                        "Replace receipt (leave empty to keep current)",
                        type=["jpg", "jpeg", "png", "pdf"],
                        key=f"e_receipt_{r['id']}",
                    )

                    eu, ed = st.columns(2)
                    with eu:
                        upd = st.form_submit_button("Update", use_container_width=True)
                    with ed:
                        del_ = st.form_submit_button(
                            "Delete", use_container_width=True, type="primary",
                        )

                    if upd:
                        if not e_desc.strip():
                            st.warning("Description cannot be empty.")
                        elif float(e_amt) <= 0:
                            st.warning("Amount must be greater than $0.")
                        else:
                            new_row = {
                                "date": str(e_date),
                                "description": e_desc.strip(),
                                "category": e_cat,
                                "amount": round(float(e_amt), 2),
                                "paid_by": e_payer,
                                "split_pct": float(e_split),
                                "status": e_stat,
                                "notes": e_notes.strip() or None,
                            }
                            if e_receipt:
                                try:
                                    new_url = upload_receipt(
                                        supabase,
                                        e_receipt.getvalue(),
                                        e_receipt.name,
                                    )
                                    if new_url:
                                        if receipt_url:
                                            delete_file(supabase, receipt_url)
                                        new_row["receipt_url"] = new_url
                                except Exception:
                                    st.warning("Receipt upload failed.")
                            try:
                                update_expense(supabase, int(r["id"]), new_row)
                                st.success("Updated!")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Update failed: {e}")

                    if del_:
                        st.session_state[f"confirm_delete_{r['id']}"] = True

                if st.session_state.get(f"confirm_delete_{r['id']}"):
                    st.warning(
                        f"Permanently delete **#{r['id']} — {r['description']}** "
                        f"(${amt:.2f})?",
                    )
                    c_yes, c_no = st.columns(2)
                    with c_yes:
                        if st.button(
                            "Yes, delete",
                            key=f"confirm_yes_{r['id']}",
                            type="primary",
                            use_container_width=True,
                        ):
                            try:
                                if receipt_url:
                                    delete_file(supabase, receipt_url)
                                if proof_url:
                                    delete_file(supabase, proof_url)
                                delete_expense(supabase, int(r["id"]))
                                st.session_state.pop(f"confirm_delete_{r['id']}", None)
                                st.rerun()
                            except Exception as e:
                                st.error(f"Delete failed: {e}")
                    with c_no:
                        if st.button(
                            "Cancel",
                            key=f"confirm_no_{r['id']}",
                            use_container_width=True,
                        ):
                            st.session_state.pop(f"confirm_delete_{r['id']}", None)
                            st.rerun()

            st.divider()

# ─── Footer ──────────────────────────────────────────────────────────────────

st.divider()
show_profile_switcher(identity)
st.caption("Built with Streamlit and Supabase")
