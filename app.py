"""
app.py — Finance Tracker Web App
Built with Python + Streamlit. No phone installation needed.
Open in any browser (desktop or mobile). Add to home screen for app-like feel.

Deploy free: https://streamlit.io/cloud
"""

import json
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime, timedelta, date
from typing import Optional

import database as db
import gmail_reader as gmail
import parser as p
import forecaster as fc

# ── Page Config ───────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Finance Tracker",
    page_icon="💰",
    layout="wide",
    initial_sidebar_state="collapsed",
    menu_items={"Get help": None, "Report a bug": None, "About": "Finance Tracker v2.0"}
)

# ── Theme CSS ─────────────────────────────────────────────────────────────────

st.markdown("""
<style>
  /* Mobile-first */
  .main .block-container { padding: 1rem 1rem 4rem; max-width: 100%; }
  .metric-card {
    background: linear-gradient(135deg, #1A1D27, #222635);
    border-radius: 16px; padding: 1rem 1.2rem;
    border: 1px solid #2a2d3e; margin-bottom: 0.5rem;
  }
  .metric-label { color: #6c757d; font-size: 0.75rem; margin-bottom: 2px; }
  .metric-value { color: #fff; font-size: 1.5rem; font-weight: 700; }
  .metric-sub   { color: #00C9A7; font-size: 0.8rem; }
  .pill-green { background:#00C9A7; color:#000; padding:2px 10px;
                border-radius:12px; font-size:0.75rem; font-weight:600; }
  .pill-red   { background:#FF6B6B; color:#fff; padding:2px 10px;
                border-radius:12px; font-size:0.75rem; font-weight:600; }
  .pill-amber { background:#FFD43B; color:#000; padding:2px 10px;
                border-radius:12px; font-size:0.75rem; font-weight:600; }
  .section-title { font-size:1.1rem; font-weight:700; margin:1.2rem 0 0.5rem; color:#eee; }
  div[data-testid="stTabs"] button { font-size: 0.85rem !important; }
  @media (max-width: 640px) {
    .metric-value { font-size: 1.2rem; }
  }
</style>
""", unsafe_allow_html=True)

# ── Init DB ───────────────────────────────────────────────────────────────────

db.init_db()

# ── Session State ─────────────────────────────────────────────────────────────

if "gmail_creds" not in st.session_state:
    st.session_state.gmail_creds = None
if "oauth_flow"  not in st.session_state:
    st.session_state.oauth_flow  = None
if "client_cfg"  not in st.session_state:
    st.session_state.client_cfg  = None
if "syncing"     not in st.session_state:
    st.session_state.syncing     = False


# ── Helpers ───────────────────────────────────────────────────────────────────

def fmt_inr(x: float) -> str:
    if x >= 1_00_000:
        return f"₹{x/1_00_000:.1f}L"
    if x >= 1_000:
        return f"₹{x/1_000:.1f}K"
    return f"₹{x:,.0f}"


def ts(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def range_ts(period: str):
    now = datetime.now()
    if period == "Today":
        s = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == "This Week":
        s = now - timedelta(days=now.weekday())
        s = s.replace(hour=0, minute=0, second=0)
    elif period == "This Month":
        s = now.replace(day=1, hour=0, minute=0, second=0)
    elif period == "This Year":
        s = now.replace(month=1, day=1, hour=0, minute=0, second=0)
    else:
        s = now - timedelta(days=90)
    return ts(s), ts(now)


PLOTLY_LAYOUT = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(color="#ccc", size=11),
    margin=dict(l=10, r=10, t=30, b=10),
    xaxis=dict(gridcolor="#2a2d3e", showgrid=True),
    yaxis=dict(gridcolor="#2a2d3e", showgrid=True),
    legend=dict(bgcolor="rgba(0,0,0,0)"),
)

CATEGORY_COLORS = {
    "Food & Dining":     "#FF6B6B",
    "Groceries":         "#51CF66",
    "Transport":         "#74C0FC",
    "Shopping":          "#FFD43B",
    "Utilities & Bills": "#A9E34B",
    "Entertainment":     "#DA77F2",
    "Health & Medical":  "#F783AC",
    "Education":         "#4DABF7",
    "Travel":            "#FFA94D",
    "Investments":       "#63E6BE",
    "Transfers":         "#868E96",
    "Salary / Income":   "#00C9A7",
    "Other":             "#ADB5BD",
}

CATEGORIES = list(CATEGORY_COLORS.keys())


# ══════════════════════════════════════════════════════════════════════════════
#  GMAIL SYNC
# ══════════════════════════════════════════════════════════════════════════════

def sync_gmail():
    """Pull emails, parse them, store transactions + CC bills."""
    creds = st.session_state.gmail_creds
    if not creds:
        return 0, 0

    with st.spinner("🔄 Reading your Gmail..."):
        emails = gmail.fetch_emails(creds, max_results=300)

    new_tx, new_bills = 0, 0
    progress = st.progress(0)

    for i, email in enumerate(emails):
        progress.progress((i + 1) / max(len(emails), 1))
        parsed = p.parse_email(email)
        if not parsed:
            continue

        ptype = parsed.get("type")

        if ptype == "TRANSACTION":
            if not db.hash_exists(parsed["hash"]):
                db.insert_transaction({
                    "amount":       parsed["amount"],
                    "type":         parsed.get("tx_type", "DEBIT"),
                    "merchant":     parsed.get("merchant", "Unknown"),
                    "category":     parsed.get("category", "Other"),
                    "bank":         parsed.get("bank", ""),
                    "account_last4": parsed.get("account_last4", ""),
                    "balance":      parsed.get("balance"),
                    "source":       "EMAIL",
                    "raw":          parsed.get("raw", "")[:500],
                    "hash":         parsed["hash"],
                    "ts":           parsed["ts"],
                })
                new_tx += 1

        elif ptype == "CC_BILL":
            name   = parsed["name"]
            amount = parsed["amount"]
            if not db.bill_duplicate(name, amount):
                db.insert_bill({
                    "name":        name,
                    "amount":      amount,
                    "category":    "Utilities & Bills",
                    "next_due_ts": parsed.get("due_ts") or ts(datetime.now() + timedelta(days=15)),
                    "keyword":     parsed.get("bank", ""),
                    "auto_detected": True,
                })
                new_bills += 1

        elif ptype == "CC_PAYMENT":
            # Record the payment as a DEBIT transaction
            if not db.hash_exists(parsed["hash"]):
                db.insert_transaction({
                    "amount":   parsed["amount"],
                    "type":     "DEBIT",
                    "merchant": parsed.get("merchant", "CC Payment"),
                    "category": "Utilities & Bills",
                    "bank":     parsed.get("bank", ""),
                    "source":   "EMAIL",
                    "hash":     parsed["hash"],
                    "ts":       parsed["ts"],
                })
                new_tx += 1

            # Auto-mark matching pending bill as PAID
            matching = db.find_matching_bill(parsed["amount"], parsed.get("bank", ""))
            if matching:
                db.mark_bill_paid(matching["id"])

    progress.empty()
    return new_tx, new_bills


# ══════════════════════════════════════════════════════════════════════════════
#  SIDEBAR — Google Auth
# ══════════════════════════════════════════════════════════════════════════════

with st.sidebar:
    st.title("💰 Finance Tracker")
    st.divider()

    if st.session_state.gmail_creds:
        st.success("✅ Gmail Connected")
        if st.button("🔄 Sync Now", use_container_width=True):
            nt, nb = sync_gmail()
            st.success(f"Imported {nt} transactions, {nb} new bills")
            st.rerun()
        if st.button("🔓 Disconnect", use_container_width=True):
            st.session_state.gmail_creds = None
            st.rerun()
    else:
        st.markdown("### Connect Gmail")
        st.caption("Upload your OAuth credentials JSON from Google Cloud Console.")
        uploaded = st.file_uploader("credentials.json", type="json", key="cred_upload")

        if uploaded:
            try:
                cfg = json.load(uploaded)
                st.session_state.client_cfg = cfg
                auth_url, flow = gmail.get_auth_url(cfg)
                st.session_state.oauth_flow = flow
                st.markdown(f"**[Click here to authorise Gmail →]({auth_url})**")
                st.caption("Paste the code you get back below:")

                code = st.text_input("Auth code", key="auth_code")
                if st.button("Connect", use_container_width=True) and code:
                    try:
                        creds = gmail.exchange_code(st.session_state.oauth_flow, code.strip())
                        st.session_state.gmail_creds = creds
                        st.success("Connected! Syncing now...")
                        nt, nb = sync_gmail()
                        st.success(f"Done — {nt} transactions, {nb} bills")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Auth failed: {e}")
            except Exception as e:
                st.error(f"Invalid JSON: {e}")

        st.divider()
        st.caption("""
**How to get credentials.json:**
1. [Google Cloud Console](https://console.cloud.google.com)
2. Create project → Enable Gmail API
3. Credentials → Create OAuth 2.0 Client ID
4. Application type: **Desktop App**
5. Download JSON → upload above
        """)

    st.divider()
    st.caption("🔒 All data stored locally. Gmail read-only access.")


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN TABS
# ══════════════════════════════════════════════════════════════════════════════

tab_home, tab_tx, tab_bills, tab_budget, tab_forecast = st.tabs([
    "🏠 Dashboard", "📋 Transactions", "💳 Bills", "🎯 Budget", "🔮 Forecast"
])


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 1: DASHBOARD
# ══════════════════════════════════════════════════════════════════════════════

with tab_home:
    period = st.radio("View", ["Today", "This Week", "This Month", "This Year"],
                      horizontal=True, label_visibility="collapsed")
    s_ts, e_ts = range_ts(period)

    all_df      = db.get_all_transactions_df()
    period_df   = db.get_transactions_df(s_ts, e_ts)
    cat_df      = db.get_category_spend(s_ts, e_ts)
    daily_df    = db.get_daily_spend(s_ts, e_ts)
    monthly_df  = db.get_monthly_spend_history()
    weekly_df   = db.get_weekly_spend_history()
    bills_df    = db.get_bills_df()

    debit_df = period_df[period_df["type"] == "DEBIT"] if not period_df.empty else pd.DataFrame()
    total    = debit_df["amount"].sum() if not debit_df.empty else 0

    # ── KPI Cards ─────────────────────────────────────────────────────────────
    c1, c2, c3, c4 = st.columns(4)
    for col, label, val, sub in [
        (c1, period, total, f"{len(debit_df)} transactions"),
        (c2, "Avg/Day", total / max((e_ts - s_ts) / 86400000, 1), ""),
        (c3, "Pending Bills", bills_df[bills_df["status"]=="PENDING"]["amount"].sum() if not bills_df.empty else 0, "this month"),
        (c4, "Top Category", 0 if cat_df.empty else cat_df.iloc[0]["total"],
             "" if cat_df.empty else cat_df.iloc[0]["category"]),
    ]:
        with col:
            st.markdown(f"""
            <div class="metric-card">
              <div class="metric-label">{label}</div>
              <div class="metric-value">{fmt_inr(val)}</div>
              <div class="metric-sub">{sub}</div>
            </div>""", unsafe_allow_html=True)

    # ── Spend Over Time Chart ─────────────────────────────────────────────────
    st.markdown('<div class="section-title">📈 Spend Over Time</div>', unsafe_allow_html=True)

    if not daily_df.empty:
        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=daily_df["day"], y=daily_df["total"],
            marker_color="#00C9A7", name="Daily Spend",
            hovertemplate="₹%{y:,.0f}<extra></extra>"
        ))
        fig.update_layout(**PLOTLY_LAYOUT, height=220, title="Daily Spend")
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No transactions yet. Connect Gmail and sync to see data.")

    # ── Category Breakdown ────────────────────────────────────────────────────
    if not cat_df.empty:
        col_pie, col_bar = st.columns([1, 1])

        with col_pie:
            st.markdown('<div class="section-title">🏷️ Category Split</div>', unsafe_allow_html=True)
            fig = go.Figure(go.Pie(
                labels=cat_df["category"], values=cat_df["total"],
                hole=0.5,
                marker_colors=[CATEGORY_COLORS.get(c, "#aaa") for c in cat_df["category"]],
                hovertemplate="%{label}: ₹%{value:,.0f}<extra></extra>",
                textinfo="percent",
            ))
            fig.update_layout(**PLOTLY_LAYOUT, height=280, showlegend=True,
                              legend=dict(orientation="v", x=1, y=0.5))
            st.plotly_chart(fig, use_container_width=True)

        with col_bar:
            st.markdown('<div class="section-title">📊 By Category</div>', unsafe_allow_html=True)
            fig = go.Figure(go.Bar(
                y=cat_df["category"], x=cat_df["total"],
                orientation="h",
                marker_color=[CATEGORY_COLORS.get(c, "#aaa") for c in cat_df["category"]],
                hovertemplate="₹%{x:,.0f}<extra></extra>",
            ))
            fig.update_layout(**PLOTLY_LAYOUT, height=280)
            st.plotly_chart(fig, use_container_width=True)

    # ── Monthly Trend ─────────────────────────────────────────────────────────
    if not monthly_df.empty and len(monthly_df) > 1:
        st.markdown('<div class="section-title">📅 Monthly Trend</div>', unsafe_allow_html=True)
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=monthly_df["month"], y=monthly_df["total"],
            mode="lines+markers",
            line=dict(color="#00C9A7", width=2),
            fill="tozeroy", fillcolor="rgba(0,201,167,0.08)",
            hovertemplate="₹%{y:,.0f}<extra></extra>",
        ))
        fig.update_layout(**PLOTLY_LAYOUT, height=200)
        st.plotly_chart(fig, use_container_width=True)

    # ── Recent Transactions ───────────────────────────────────────────────────
    st.markdown('<div class="section-title">🕐 Recent Transactions</div>', unsafe_allow_html=True)
    if not all_df.empty:
        recent = all_df[all_df["type"] == "DEBIT"].head(10)
        for _, row in recent.iterrows():
            col_a, col_b, col_c = st.columns([3, 2, 1])
            with col_a:
                cat_color = CATEGORY_COLORS.get(row["category"], "#aaa")
                st.markdown(f"**{row['merchant']}**  \n<small style='color:{cat_color}'>"
                            f"{row['category']}</small>", unsafe_allow_html=True)
            with col_b:
                st.caption(row["date"].strftime("%d %b %Y, %I:%M %p") if pd.notnull(row.get("date")) else "")
            with col_c:
                st.markdown(f"<span class='pill-red'>–{fmt_inr(row['amount'])}</span>",
                            unsafe_allow_html=True)
            st.divider()


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 2: TRANSACTIONS
# ══════════════════════════════════════════════════════════════════════════════

with tab_tx:
    st.markdown("### All Transactions")

    col_search, col_cat, col_type = st.columns([3, 2, 1])
    with col_search:
        search = st.text_input("🔍 Search merchant...", key="tx_search")
    with col_cat:
        cat_filter = st.selectbox("Category", ["All"] + CATEGORIES, key="tx_cat")
    with col_type:
        type_filter = st.selectbox("Type", ["All", "DEBIT", "CREDIT"], key="tx_type")

    all_df = db.get_all_transactions_df()
    view_df = all_df.copy() if not all_df.empty else pd.DataFrame()

    if not view_df.empty:
        if search:
            view_df = view_df[view_df["merchant"].str.contains(search, case=False, na=False)]
        if cat_filter != "All":
            view_df = view_df[view_df["category"] == cat_filter]
        if type_filter != "All":
            view_df = view_df[view_df["type"] == type_filter]

        total_shown = view_df[view_df["type"] == "DEBIT"]["amount"].sum()
        st.caption(f"{len(view_df)} transactions · Total: {fmt_inr(total_shown)}")

        for _, row in view_df.head(100).iterrows():
            is_debit = row["type"] == "DEBIT"
            color    = "#FF6B6B" if is_debit else "#51CF66"
            sign     = "–" if is_debit else "+"
            cat_col  = CATEGORY_COLORS.get(row["category"], "#aaa")

            with st.expander(
                f"{sign}{fmt_inr(row['amount'])}  •  {row['merchant']}  "
                f"•  {row['date'].strftime('%d %b') if pd.notnull(row.get('date')) else ''}",
                expanded=False
            ):
                c1, c2 = st.columns(2)
                with c1:
                    new_cat = st.selectbox(
                        "Category", CATEGORIES,
                        index=CATEGORIES.index(row["category"]) if row["category"] in CATEGORIES else 0,
                        key=f"cat_{row['id']}"
                    )
                    if new_cat != row["category"]:
                        db.update_transaction_category(int(row["id"]), new_cat)
                        st.rerun()
                with c2:
                    st.caption(f"Bank: {row.get('bank','—')}  ·  Acct: XX{row.get('account_last4','—')}")
                    st.caption(f"Source: {row.get('source','—')}")
                if st.button("🗑️ Delete", key=f"del_{row['id']}"):
                    db.delete_transaction(int(row["id"]))
                    st.rerun()
    else:
        st.info("No transactions yet — sync Gmail from the sidebar.")

    # ── Manual entry ──────────────────────────────────────────────────────────
    with st.expander("➕ Add Transaction Manually"):
        c1, c2, c3 = st.columns(3)
        with c1: m_amt = st.number_input("Amount (₹)", min_value=0.0, step=10.0, key="m_amt")
        with c2: m_mer = st.text_input("Merchant", key="m_mer")
        with c3: m_cat = st.selectbox("Category", CATEGORIES, key="m_cat")
        m_type = st.radio("Type", ["DEBIT", "CREDIT"], horizontal=True, key="m_type")
        m_date = st.date_input("Date", value=date.today(), key="m_date")
        if st.button("Save", key="m_save") and m_amt and m_mer:
            import hashlib, time
            db.insert_transaction({
                "amount":   m_amt,
                "type":     m_type,
                "merchant": m_mer,
                "category": m_cat,
                "source":   "MANUAL",
                "hash":     hashlib.md5(f"{m_mer}{m_amt}{time.time()}".encode()).hexdigest(),
                "ts":       int(datetime.combine(m_date, datetime.min.time()).timestamp() * 1000),
            })
            st.success("Saved!")
            st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 3: BILLS
# ══════════════════════════════════════════════════════════════════════════════

with tab_bills:
    st.markdown("### Bills & Subscriptions")
    bills_df = db.get_bills_df()

    pending = bills_df[bills_df["status"] == "PENDING"] if not bills_df.empty else pd.DataFrame()
    paid    = bills_df[bills_df["status"] == "PAID"]    if not bills_df.empty else pd.DataFrame()

    # ── Pending ───────────────────────────────────────────────────────────────
    if not pending.empty:
        st.markdown("#### 🔴 Pending")
        total_pending = pending["amount"].sum()
        st.caption(f"{len(pending)} bills · {fmt_inr(total_pending)} total due")

        for _, row in pending.iterrows():
            c1, c2, c3 = st.columns([4, 2, 1])
            with c1:
                due_str = row["due_date"].strftime("%d %b %Y") if pd.notnull(row.get("due_date")) else "—"
                st.markdown(f"**{row['name']}**  \n<small style='color:#FFD43B'>Due {due_str}</small>",
                            unsafe_allow_html=True)
            with c2:
                st.markdown(f"<span class='pill-amber'>{fmt_inr(row['amount'])}</span>",
                            unsafe_allow_html=True)
            with c3:
                if st.button("✅", key=f"pay_{row['id']}", help="Mark Paid"):
                    db.mark_bill_paid(int(row["id"]))
                    st.success(f"{row['name']} marked paid!")
                    st.rerun()
            st.divider()
    else:
        st.success("🎉 No pending bills!")

    # ── Paid ──────────────────────────────────────────────────────────────────
    if not paid.empty:
        with st.expander(f"✅ Paid Bills ({len(paid)})"):
            for _, row in paid.iterrows():
                c1, c2 = st.columns([5, 2])
                with c1:
                    st.write(f"~~{row['name']}~~")
                with c2:
                    st.markdown(f"<span class='pill-green'>{fmt_inr(row['amount'])}</span>",
                                unsafe_allow_html=True)

    # ── Add Bill Manually ─────────────────────────────────────────────────────
    with st.expander("➕ Add Bill"):
        c1, c2 = st.columns(2)
        with c1: b_name = st.text_input("Bill Name", key="b_name")
        with c2: b_amt  = st.number_input("Amount (₹)", min_value=0.0, step=100.0, key="b_amt")
        c3, c4 = st.columns(2)
        with c3: b_due  = st.date_input("Next Due Date", key="b_due")
        with c4: b_cat  = st.selectbox("Category", CATEGORIES, index=CATEGORIES.index("Utilities & Bills"), key="b_cat")
        if st.button("Add Bill", key="b_save") and b_name and b_amt:
            db.insert_bill({
                "name":        b_name,
                "amount":      b_amt,
                "category":    b_cat,
                "next_due_ts": ts(datetime.combine(b_due, datetime.min.time())),
                "due_day":     b_due.day,
            })
            st.success("Bill added!")
            st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 4: BUDGET
# ══════════════════════════════════════════════════════════════════════════════

with tab_budget:
    st.markdown("### Monthly Budgets")
    now = datetime.now()
    s_ts, e_ts = range_ts("This Month")
    cat_spend = db.get_category_spend(s_ts, e_ts)
    budgets   = db.get_budgets_df(now.month, now.year)

    spend_map  = dict(zip(cat_spend["category"], cat_spend["total"])) if not cat_spend.empty else {}
    budget_map = dict(zip(budgets["category"], budgets["monthly_limit"])) if not budgets.empty else {}

    for cat in CATEGORIES:
        spent  = spend_map.get(cat, 0)
        limit  = budget_map.get(cat, 0)
        color  = CATEGORY_COLORS.get(cat, "#aaa")

        with st.expander(f"{cat}  —  {fmt_inr(spent)}{f' / {fmt_inr(limit)}' if limit else ''}"):
            new_limit = st.number_input(
                f"Monthly limit for {cat} (₹)",
                min_value=0.0, value=float(limit), step=500.0, key=f"bgt_{cat}"
            )
            if new_limit != limit and st.button("Save", key=f"bgt_save_{cat}"):
                db.set_budget(cat, new_limit, now.month, now.year)
                st.success("Saved!")
                st.rerun()

            if limit > 0:
                pct = min(spent / limit, 1.0)
                bar_color = "#FF6B6B" if pct >= 1 else ("#FFD43B" if pct >= 0.8 else "#00C9A7")
                st.markdown(f"""
                <div style="background:#2a2d3e;border-radius:6px;height:8px;margin-top:4px">
                  <div style="background:{bar_color};width:{pct*100:.0f}%;height:8px;border-radius:6px"></div>
                </div>
                <small style="color:{bar_color}">{pct*100:.0f}% used</small>
                """, unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 5: 50-WEEK FORECAST
# ══════════════════════════════════════════════════════════════════════════════

with tab_forecast:
    st.markdown("### 🔮 50-Week Spending Forecast")

    weekly_df = db.get_weekly_spend_history()
    all_df    = db.get_all_transactions_df()

    if weekly_df.empty or len(weekly_df) < 2:
        st.info("Need at least 2 weeks of data to forecast. Sync your Gmail to get started.")
    else:
        fc_df   = fc.forecast_50_weeks(weekly_df, weeks_ahead=50)
        summary = fc.forecast_summary(fc_df)

        # ── Summary KPIs ──────────────────────────────────────────────────────
        trend_emoji = {"increasing": "📈", "decreasing": "📉", "stable": "➡️"}.get(summary["trend"], "")
        c1, c2, c3, c4 = st.columns(4)
        metrics = [
            ("Avg/Week (hist.)", summary["avg_weekly"]),
            ("Next 4 Weeks",     summary["next_4_weeks"]),
            ("Next 12 Weeks",    summary["next_12_weeks"]),
            ("Full 50 Weeks",    summary["total_50_weeks"]),
        ]
        for col, (label, val) in zip([c1, c2, c3, c4], metrics):
            with col:
                st.markdown(f"""
                <div class="metric-card">
                  <div class="metric-label">{label}</div>
                  <div class="metric-value">{fmt_inr(val)}</div>
                  <div class="metric-sub">{trend_emoji} {summary['trend']}</div>
                </div>""", unsafe_allow_html=True)

        # ── 50-Week Chart ─────────────────────────────────────────────────────
        st.markdown('<div class="section-title">📊 Weekly Spend — Historical + 50-Week Forecast</div>',
                    unsafe_allow_html=True)

        hist = fc_df[~fc_df["is_forecast"]]
        fore = fc_df[fc_df["is_forecast"]]

        fig = go.Figure()

        # Confidence band
        fig.add_trace(go.Scatter(
            x=pd.concat([fore["week_label"], fore["week_label"].iloc[::-1]]),
            y=pd.concat([fore["upper"], fore["lower"].iloc[::-1]]),
            fill="toself", fillcolor="rgba(0,201,167,0.08)",
            line=dict(color="rgba(0,0,0,0)"),
            name="80% Confidence Band", showlegend=True
        ))

        # Forecast bars
        fig.add_trace(go.Bar(
            x=fore["week_label"], y=fore["predicted"],
            name="Forecast", marker_color="rgba(0,201,167,0.45)",
            hovertemplate="Week: %{x}<br>₹%{y:,.0f}<extra></extra>"
        ))

        # Historical bars
        fig.add_trace(go.Bar(
            x=hist["week_label"], y=hist["predicted"],
            name="Actual", marker_color="#00C9A7",
            hovertemplate="Week: %{x}<br>₹%{y:,.0f}<extra></extra>"
        ))

        fig.update_layout(
            **PLOTLY_LAYOUT,
            height=380,
            barmode="overlay",
            xaxis_tickangle=-45,
            xaxis=dict(
                gridcolor="#2a2d3e",
                rangeslider=dict(visible=True),  # mobile scrollable
                type="category"
            ),
        )
        st.plotly_chart(fig, use_container_width=True)

        # ── Notable Weeks ─────────────────────────────────────────────────────
        if summary["peak_week"] is not None and summary["lowest_week"] is not None:
            c1, c2 = st.columns(2)
            with c1:
                pk = summary["peak_week"]
                st.markdown(f"""
                <div class="metric-card">
                  <div class="metric-label">📈 Highest Forecast Week</div>
                  <div class="metric-value" style="color:#FF6B6B">{fmt_inr(pk['predicted'])}</div>
                  <div class="metric-sub">{pk['week_label']}</div>
                </div>""", unsafe_allow_html=True)
            with c2:
                lw = summary["lowest_week"]
                st.markdown(f"""
                <div class="metric-card">
                  <div class="metric-label">📉 Lowest Forecast Week</div>
                  <div class="metric-value" style="color:#51CF66">{fmt_inr(lw['predicted'])}</div>
                  <div class="metric-sub">{lw['week_label']}</div>
                </div>""", unsafe_allow_html=True)

        # ── Category Forecasts ────────────────────────────────────────────────
        if not all_df.empty and "date" in all_df.columns:
            debit_df = all_df[all_df["type"] == "DEBIT"].copy()
            if not debit_df.empty:
                st.markdown('<div class="section-title">🏷️ Category Forecasts (Next 4 Weeks)</div>',
                            unsafe_allow_html=True)
                cat_forecasts = fc.forecast_by_category(debit_df, weeks_ahead=4)
                if cat_forecasts:
                    rows_fc = []
                    for cat, df_cat in cat_forecasts.items():
                        future4 = df_cat[df_cat["is_forecast"]].head(4)
                        rows_fc.append({
                            "Category": cat,
                            "W1": fmt_inr(future4.iloc[0]["predicted"]) if len(future4) > 0 else "—",
                            "W2": fmt_inr(future4.iloc[1]["predicted"]) if len(future4) > 1 else "—",
                            "W3": fmt_inr(future4.iloc[2]["predicted"]) if len(future4) > 2 else "—",
                            "W4": fmt_inr(future4.iloc[3]["predicted"]) if len(future4) > 3 else "—",
                            "4-Wk Total": fmt_inr(future4["predicted"].sum()),
                        })
                    st.dataframe(pd.DataFrame(rows_fc).set_index("Category"),
                                 use_container_width=True)

        # ── Full Forecast Table ───────────────────────────────────────────────
        with st.expander("📋 Full 50-Week Forecast Table"):
            display_fc = fore[["week_label","predicted","lower","upper"]].copy()
            display_fc.columns = ["Week", "Predicted", "Lower Bound", "Upper Bound"]
            display_fc["Predicted"]    = display_fc["Predicted"].apply(fmt_inr)
            display_fc["Lower Bound"]  = display_fc["Lower Bound"].apply(fmt_inr)
            display_fc["Upper Bound"]  = display_fc["Upper Bound"].apply(fmt_inr)
            st.dataframe(display_fc, use_container_width=True, hide_index=True)


# ── Footer ────────────────────────────────────────────────────────────────────
st.markdown("""
<div style="text-align:center;color:#555;padding:2rem 0 1rem;font-size:0.75rem">
  🔒 All data processed locally · Gmail read-only · No data shared with third parties
</div>
""", unsafe_allow_html=True)
