# 💰 Finance Tracker — Python Web App

Zero installation on your phone. Pure Python + Streamlit.
Reads Gmail automatically, tracks bills, forecasts 50 weeks.

---

## 🚀 Deploy in 15 Minutes (Free, No Developer Mode)

### Step 1 — Put code on GitHub (free)
1. Go to [github.com](https://github.com) → Sign up / Log in
2. Click **New Repository** → name it `finance-tracker` → **Public** → Create
3. Upload all these files by dragging them into the GitHub page

### Step 2 — Deploy to Streamlit Cloud (free)
1. Go to [share.streamlit.io](https://share.streamlit.io)
2. Sign in with GitHub
3. Click **New app** → select your `finance-tracker` repo
4. Main file path: `app.py`
5. Click **Deploy** → done in ~2 minutes
6. You get a URL like: `https://yourname-finance-tracker.streamlit.app`

### Step 3 — Add to Phone Home Screen (like an app)
**iPhone:** Open URL in Safari → Share → "Add to Home Screen"
**Android:** Open URL in Chrome → Menu → "Add to Home Screen"

It opens full-screen, looks and feels like a native app. ✅

---

## 📧 Gmail Setup (One-Time)

### Get credentials.json
1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Create project → name it "FinanceTracker"
3. Left menu → **APIs & Services** → **Enable APIs** → search "Gmail API" → Enable
4. Left menu → **Credentials** → **Create Credentials** → **OAuth 2.0 Client ID**
5. Application type: **Desktop App** → name it anything → Create
6. Download the JSON file → rename to `credentials.json`

### Connect in the app
1. Open your deployed app
2. Open the sidebar (hamburger menu on mobile)
3. Upload `credentials.json`
4. Click the authorization link → sign in with your Gmail
5. Copy the code → paste it back → Connect
6. App syncs your last 90 days of financial emails automatically

---

## 📁 File Structure

```
finance-tracker/
├── app.py           ← Main Streamlit app (all 5 tabs)
├── database.py      ← SQLite storage (transactions, bills, budgets)
├── gmail_reader.py  ← Gmail API OAuth + email fetching
├── parser.py        ← Email parser (Indian banks, CC bill lifecycle)
├── forecaster.py    ← 50-week Holt-Winters forecast engine
├── requirements.txt ← Python dependencies
└── .streamlit/
    └── config.toml  ← Dark theme config
```

---

## 🧠 How CC Bill Tracking Works

| Email You Receive | What the App Does |
|---|---|
| "Statement generated. Total due: ₹12,450" | Creates a **Bill record**. Nothing else. |
| "Reminder: Pay your CC bill by 15 May" | **Skipped entirely** — just a nudge, no duplicate created |
| "Payment of ₹12,450 received" | Creates a **DEBIT transaction** + auto-marks the Bill as **PAID ✅** |
| "Spent ₹840 at Swiggy on card" | Normal transaction — tracked when you swipe |

Your CC spends are tracked when you swipe. The bill payment is tracked when you pay. Zero double counting.

---

## 🔮 Forecast Algorithm

Uses **Holt-Winters Triple Exponential Smoothing**:
- α = level, β = trend, γ = seasonal (4-week cycle)
- India-specific boosts: Diwali +20%, Year-end +15%, Salary week +8%
- Confidence bands that widen with forecast horizon
- Separate per-category models for Food, Transport, Shopping, etc.
- Falls back to linear regression when less than 4 weeks of data

---

## 📊 Dashboards Included

| Tab | Contents |
|---|---|
| 🏠 Dashboard | KPI cards, daily bar chart, category donut, monthly trend, recent transactions |
| 📋 Transactions | All transactions, search, filter, edit category, delete, manual add |
| 💳 Bills | Auto-detected + manual bills, one-tap mark paid, paid history |
| 🎯 Budget | Set per-category monthly budget, live progress bars |
| 🔮 Forecast | 50-week chart with confidence bands, category table, peak/low week |

---

## 🔒 Privacy

- Gmail accessed **read-only** — the app never sends, deletes, or modifies emails
- All data stored in **finance.db** (SQLite) on the server — not sent anywhere
- No third-party analytics or ads
- OAuth token stored only in your browser session

---

## 💸 Cost

| Item | Cost |
|---|---|
| Streamlit Community Cloud | **Free** |
| GitHub | **Free** |
| Gmail API | **Free** (1 billion units/day) |
| Google Cloud Project | **Free** for these APIs |
| **Total** | **₹0** |
