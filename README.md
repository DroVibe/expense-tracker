# Co-Parent Expense Tracker

A real-time shared expense tracker for co-parents. Both parents log expenses, the app calculates who owes whom, and one parent can settle up with proof — all without email, spreadsheets, or asking each other for updates.

**Live:** [familyexpensetracker.streamlit.app](https://familyexpensetracker.streamlit.app)

---

## How It Works

After selecting **Me / Dad** or **Mom**, both parents see the same live data. The app tracks who paid, splits the cost by percentage, and calculates a running balance — so at the end of the month you know exactly who's owed and why.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | Streamlit |
| Backend | Supabase (Postgres + Auth + Storage) |
| Deployment | Streamlit Cloud |

---

## Setup

### 1. Supabase Project

Create a free project at [supabase.com](https://supabase.com), then run this in the **SQL Editor**:

```sql
CREATE TABLE expenses (
    id              SERIAL PRIMARY KEY,
    date            DATE,
    description     TEXT,
    category        TEXT,
    amount          NUMERIC,
    paid_by         TEXT,        -- 'me' or 'mom'
    split_pct       NUMERIC DEFAULT 50,
    status          TEXT DEFAULT 'active',  -- 'active' or 'settled'
    settled_by      TEXT,
    settled_at      TIMESTAMP,
    settlement_note TEXT,
    settlement_proof_url TEXT,
    notes           TEXT,
    receipt_url     TEXT,
    created_at      TIMESTAMP DEFAULT NOW()
);

CREATE TABLE profiles (
    id              SERIAL PRIMARY KEY,
    name            TEXT,
    email           TEXT,
    role            TEXT,        -- 'me' or 'mom'
    created_at      TIMESTAMP DEFAULT NOW()
);

ALTER TABLE expenses ENABLE ROW LEVEL SECURITY;
ALTER TABLE profiles ENABLE ROW LEVEL SECURITY;

-- Allow all authenticated users full access to both tables
CREATE POLICY "Allow all" ON expenses FOR ALL USING (true);
CREATE POLICY "Allow all" ON profiles FOR ALL USING (true);
```

In **Storage**, create a public bucket named `receipts`.

Go to **Settings → API** and copy:
- **Project URL** → `SUPABASE_URL`
- **anon public** key → `SUPABASE_KEY`

### 2. Secrets

Copy the example file and fill in your credentials:

```bash
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
# then edit .streamlit/secrets.toml
```

### 3. Install & Run

```bash
pip install -r requirements.txt
streamlit run expense_tracker.py
```

### 4. Deploy

Connect the GitHub repo to [Streamlit Cloud](https://streamlit.io/cloud) and add your secrets in the Streamlit Cloud dashboard under **Settings → Secrets**.

---

## Project Structure

```
expense_tracker.py   — Main app (Dashboard)
pages/
  2_Records.py       — Full expense history with search/filter
shared.py            — Shared logic, balance math, Supabase helpers
migrations/          — SQL migration files
tests/               — Balance math unit tests
.streamlit/
  secrets.toml       — Supabase credentials (not committed)
```

---

## Key Features

- **Real-time shared view** — both parents see the same data after selecting their identity
- **Custom split percentage** — default 50/50, adjustable per expense
- **Receipt uploads** — attach a photo or screenshot to any expense
- **Settlement proof** — settling parent uploads a payment confirmation before settling
- **Search & filter** — find any expense by keyword, category, or date range
- **CSV export** — download your full expense history
- **PWA install** — add to your iPhone home screen for a native app feel

---

## License

MIT
