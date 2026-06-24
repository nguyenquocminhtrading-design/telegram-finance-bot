# Personal Finance Manager — Telegram Bot + Web Dashboard

A full-stack personal finance management system built with Python. Users record income/expenses via a Telegram bot, track depreciable assets, run Monte Carlo portfolio projections, and visualize everything through a Flask web dashboard with Chart.js. Data syncs to Google Sheets as a cloud backup.

---

## Architecture Overview

```
Telegram (user) ──> bot.py ──> database.py ──> finance_logic.py ──> templates/ (Jinja2)
                      │            │                 │                  │
                      │            │                 │                  └── static/js/chart.js
                      │            │                 │
                      │            ├── gsheets_sync.py ──> Google Sheets (cloud backup)
                      │            ├── excel_sync.py   ──> Local .xlsx/.xlsm (legacy fallback)
                      │            └── scheduler.py    ──> APScheduler (backup, depreciation)
                      │
                      ├── asset_manager.py ──> database.py (depreciation engine)
                      ├── simulation.py    ──> numpy + matplotlib (Monte Carlo)
                      └── app.py (Flask)    ──> serves web UI + REST API + webhook
```

---

## Tech Stack

| Dependency | Version | Role |
|-----------|---------|------|
| Flask | 3.1.1 | Web server, REST API, Jinja2 templates |
| pyTelegramBotAPI | 4.28.0 | Telegram bot framework |
| python-dotenv | 1.1.0 | Load `.env` config |
| gunicorn | 23.0.0 | WSGI server (production) |
| requests | 2.32.3 | HTTP calls (Telegram API, webhook setup) |
| openpyxl | 3.1.5 | Read/write Excel files |
| APScheduler | 3.11.0 | Scheduled background jobs |
| gspread | 6.1.2 | Google Sheets API (cloud sync) |
| google-auth | 2.30.0 | Google service account auth |
| numpy | 2.1.2 | Monte Carlo simulation math |
| matplotlib | 3.9.2 | Projection chart generation |
| Chart.js | (CDN) | Client-side charts on dashboard |

---

## Directory Structure

```
telegram-finance-bot/
├── app.py                  # Flask app: all routes, API endpoints, webhook handler
├── bot.py                  # Telegram bot: all command handlers, message parsing, inline keyboards
├── database.py             # SQLite layer: schema, CRUD for transactions/assets/depreciation/settings
├── finance_logic.py        # Business logic: balance calc, monthly summary, cash flow, reports
├── asset_manager.py        # Asset engine: depreciation, liquidation, asset summary
├── scheduler.py            # APScheduler: daily backup (02:00), monthly depreciation (1st @ 00:05)
├── simulation.py           # Monte Carlo: Geometric Brownian Motion, chart generation
├── gsheets_sync.py         # Google Sheets: sync expense & asset data to cloud sheets
├── excel_sync.py           # Local Excel: legacy sync to .xlsx/.xlsm (fallback)
├── config.py               # Env var loader: token, webhook URL, DB path, secret key, admin ID
├── setup_gsheets.py        # One-time setup: verify access, create sheets, add headers
├── read_excel_temp.py      # Utility: inspect Excel file structure with pandas
├── deploy.bat              # Windows script: git init → gh repo create → push
├── requirements.txt        # Pip dependencies (11 packages)
├── .env                    # Runtime configuration (gitignored)
├── .env.example            # Template for .env
├── .gitignore              # Ignores .env, __pycache__, venv/, .idea/, .vscode/
├── portfolio_dashboard.html# Standalone HTML portfolio dashboard (Vietnamese, Excel upload via SheetJS)
├── genuine-box-500214-e2-5a8934bf85be.json  # Google service account key (gitignored)
├── My portfolio.xlsm       # Local portfolio Excel file with VBA macros
├── instance/
│   └── finance.db          # SQLite database (auto-created at first run)
├── static/
│   ├── css/style.css        # Dark blue theme, sidebar layout, cards, responsive utilities
│   └── js/chart.js          # Chart.js config: doughnut & bar charts
└── templates/
    ├── dashboard.html       # Main overview: balance, cash flow chart, recent transactions, category donut
    ├── transactions.html    # Full transaction table: filters, pagination, CRUD modal via REST API
    ├── assets.html          # Asset list: depreciation progress bars, status badges, summary cards
    ├── reports.html         # Reports: cash flow trend, income vs expense, top categories, monthly table
    ├── settings.html        # System info, one-click depreciation run, export controls
    └── mobile_snapshot.html # Telegram Mini App: compact mobile view of balance & assets
```

---

## File-by-File Breakdown

### `config.py` (18 lines)
Loads environment variables via `python-dotenv`. Exposes: `TELEGRAM_TOKEN`, `WEBHOOK_URL`, `DATABASE_PATH`, `SECRET_KEY`, `ADMIN_USER_ID`, `GSHEETS_JSON_PATH`. All other modules import config from here.

### `database.py` (240 lines)
SQLite layer with four tables:

| Table | Columns | Purpose |
|-------|---------|---------|
| `transactions` | id, type (income/expense), amount, category, description, bank, date, created_at | All income/expense records |
| `assets` | id, name, description, purchase_price, current_value, purchase_date, category, lifespan_months, status (active/liquidated), liquidated_price, liquidated_date, created_at | Capitalized assets with depreciation |
| `depreciation_log` | id, asset_id (FK), month, year, depreciation_amount, created_at | Monthly depreciation history |
| `settings` | key (PK), value | Key-value config store |

Functions: `init_db()`, `add_transaction()`, `get_transactions()`, `update_transaction()`, `delete_transaction()`, `get_balance()`, `add_asset()`, `get_assets()`, `update_asset()`, `liquidate_asset()`, `add_depreciation_log()`, `get_depreciation_logs()`, `get_setting()`, `set_setting()`, `check_duplicate_transaction()`, `backup_database()`.

### `bot.py` (467 lines)
Telegram bot with 11 commands + free-text message parsing. Uses `pyTelegramBotAPI` with polling mode (or webhook mode via Flask).

**Commands:**
- `/start` — Welcome + feature tour
- `/help` — Command reference (grouped by feature)
- `/balance` — Current balance across 3 bank accounts, with total
- `/report [month] [year]` — Detailed monthly summary: income, expense, top categories, cash flow
- `/asset` — List all assets with depreciation status
- `/web` — Web dashboard link
- `/project` — Monte Carlo 5-year portfolio projection (returns matplotlib chart photo)
- `/liquidate <asset_id> [price]` — Liquidate an asset at given price
- `/export` — Excel file export (triggers Flask download route)
- `/buy <name> <price>` — Register a new asset (alternative to auto-capitalization)
- `/sell <asset_id> <price>` — Alias for `/liquidate`

**Free-text message parsing** (the core UX):
1. User sends `+500 salary` or `-200 lunch`
2. `parse_transaction()` extracts type (+/-), amount, and description
3. `guess_category()` matches description keywords against a mapping to auto-assign category
4. For expenses ≥ 1,000,000 VND: bot asks "Do you want to capitalize this as an asset?" with inline buttons
5. For all expenses: bank account selection via inline keyboard (3 buttons: `Techcombank`, `VPBank`, `Tiền mặt`)
6. Saves to DB → syncs to Google Sheets (if configured) → syncs to local Excel (if file exists)
7. For asset capitalization flow: asks name, category from pick list, lifespan in months, confirms creation

**Category auto-guess mapping** (hardcoded in `bot.py`):
Food → `Ăn uống`, Coffee → `Ăn uống`, Transport → `Đi lại`, Gas → `Đi lại`, etc. Complete mapping covers ~30 Vietnamese categories.

### `app.py` (238 lines)
Flask application factory. Routes:

| Method | Route | Function | Description |
|--------|-------|----------|-------------|
| GET | `/` | redirect to `/dashboard` | Root redirect |
| GET | `/dashboard` | `dashboard()` | Main overview page |
| GET | `/transactions` | `transactions()` | Transaction list |
| GET | `/assets` | `assets()` | Asset management |
| GET | `/reports` | `reports()` | Charts & reports |
| GET | `/settings` | `settings()` | System settings |
| GET | `/api/transactions` | `list_transactions()` | JSON transaction list |
| POST | `/api/transactions` | `add_transaction()` | Create transaction (JSON body) |
| PUT | `/api/transactions/<id>` | `update_transaction()` | Update transaction |
| DELETE | `/api/transactions/<id>` | `delete_transaction()` | Delete transaction |
| GET | `/api/summary` | `api_summary()` | Balance + monthly stats (JSON) |
| GET | `/api/assets` | `api_assets()` | Asset summary (JSON) |
| GET | `/api/categories` | `api_categories()` | All known categories (JSON) |
| GET | `/api/monthly-data` | `api_monthly_data()` | Monthly breakdown (JSON, for reports) |
| POST | `/api/run-depreciation` | `run_depreciation()` | Trigger depreciation now |
| GET | `/ping` | `ping()` | Health check |
| POST | `/webhook/<token>` | `webhook()` | Telegram bot webhook receiver |
| GET | `/export/excel` | `export_excel()` | Download transactions as `.xlsx` |
| GET | `/mobile-snapshot` | `mobile_snapshot()` | Mobile Mini App view |

Each HTML route injects data via `finance_logic.py` (or direct DB queries) and renders a Jinja2 template.

### `finance_logic.py` (103 lines)
Pure calculation layer (no side effects):
- `get_balance(db_path)` — Returns dict with bank balances (`techcombank`, `vpbank`, `tien_mat`) and total
- `get_monthly_summary(year, month)` — Income total, expense total, net, transaction count
- `get_category_breakdown(year, month, type)` — Per-category totals for pie chart
- `get_cash_flow(months=12)` — Monthly income/expense arrays for bar chart
- `get_top_categories(year, month, type, limit=5)` — Top N categories
- `get_full_report(year, month)` — Combines all above into one dict for the reports page

### `asset_manager.py` (110 lines)
Manages the asset lifecycle:
- `run_monthly_depreciation()` — For all active assets, calculates straight-line depreciation (`purchase_price / lifespan_months`), creates `depreciation_log` entry, decrements `current_value`. If `current_value` reaches 0, marks asset as `liquidated`. Returns list of depreciation events.
- `liquidate_asset(asset_id, liquidated_price)` — Sets `status='liquidated'`, records `liquidated_price` and `liquidated_date`, computes gain/loss vs `current_value`.
- `get_asset_summary()` — Returns active count, total original value, total current value, liquidated count, per-asset details with depreciation percentage.

Depreciation formula: `monthly_depreciation = purchase_price / lifespan_months`. Straight-line, no residual value.

### `scheduler.py` (57 lines)
Uses `APScheduler` with a background thread:
- **Daily at 02:00** — `backup_database()` copies `finance.db` to `finance_backup_YYYYMMDD.db`
- **1st of each month at 00:05** — `run_monthly_depreciation()` then logs result via `set_setting('last_depreciation', timestamp)`

Scheduler starts via `start_scheduler(app)` which is called in `app.py` during app initialization.

### `simulation.py` (113 lines)
Monte Carlo portfolio projection engine:
- Defines 4 asset classes with fixed parameters: `DCDS` (mu=0.08, sigma=0.15), `DCDE` (mu=0.10, sigma=0.20), `ETFVN30` (mu=0.09, sigma=0.18), `CCQ` (mu=0.07, sigma=0.10). All prices start at 10,000 VND.
- `run_simulation(years=5, simulations=1000)` — For each asset, runs `simulations` Geometric Brownian Motion paths over `years * 12` months. `GBM: S(t+1) = S(t) * exp((mu - 0.5*sigma^2)*dt + sigma * sqrt(dt) * N(0,1))`. Returns a dict with `dates`, `median`, `percentile_5`, `percentile_95` per asset.
- `generate_projection_chart(years=5, simulations=1000)` — Generates a matplotlib chart (RGB array via `BytesIO`) showing median + 5th/95th percentile bands for each asset. Chart has Vietnamese labels ("Dự báo danh mục đầu tư 5 năm", etc).
- Called by `/project` command in `bot.py` and sends the chart as a Telegram photo.

### `gsheets_sync.py` (108 lines)
Google Sheets sync module:
- `get_gsheet_client()` — Authenticates via service account JSON and returns `gspread.Client`
- `sync_expense_to_gsheet(data)` — Opens the expense sheet by URL or key, finds the "Expenses" worksheet, appends a row: `[date, amount, category, description, bank]`
- `sync_asset_to_gsheet(data)` — Opens the portfolio sheet, finds the "Transaction" worksheet, appends a row with Vietnamese headers: `[Ngày mua, Mã CP, Giá mua, Số lượng, Giá hiện tại, Giá trị hiện tại, Trạng thái]`

Both functions are called from `bot.py` after every successful transaction or asset creation. Failure is caught and logged silently to avoid disrupting the user experience.

### `excel_sync.py` (72 lines)
Legacy local Excel sync (fallback when Google Sheets is not configured):
- `sync_expense_to_excel(data)` — Writes/creates `My expenses.xlsx` via `openpyxl`, appending rows
- `sync_asset_to_portfolio(data)` — Opens `My portfolio.xlsm` with `openpyxl` (read-only preserves VBA macros), finds the first sheet, appends asset data. Uses a `keep_vba` workaround: opens for data-only reading, collects rows, then re-creates the workbook structure.

### `setup_gsheets.py` (60 lines)
One-time setup script:
1. Authenticates via service account JSON
2. Opens the expense sheet by URL → checks for "Expenses" worksheet (creates if missing)
3. Opens the portfolio sheet → checks for "Transaction" worksheet (creates if missing)
4. Adds header rows if sheets are empty
5. Reports success/failure for each step
Run via `python setup_gsheets.py` after configuring `.env`.

### `config.py` (18 lines)
Loads and exports environment variables. Uses `os.getenv()` with fallback defaults. Paths are resolved relative to the project root.

### Templates (6 files)
All templates extend a common layout (sidebar + header) and use Jinja2 templating:

- **`dashboard.html`** (134 lines) — Balance card (total + per-bank), 4 stat cards (monthly income/expense/net), cashflow Chart.js bar chart, recent transactions table (last 10), category donut chart, active assets sidebar.
- **`transactions.html`** (157 lines) — Full table with type/amount/category/description/bank/date columns. Date range filters + type filter. Inline JavaScript implements full CRUD via REST API calls (`fetch()`) with a modal form — no page reloads.
- **`assets.html`** (83 lines) — Summary cards (active/total assets, original/current value). Per-asset cards with progress bars (depreciation %), status badges (Active/Liquidated), purchase date, current value.
- **`reports.html`** (81 lines) — 4 Chart.js canvases: cash flow trend (line), income vs expense (bar), top spending categories (pie), net balance trend (line). Monthly breakdown table below.
- **`settings.html`** (68 lines) — System info: DB path, version, last depreciation. Action buttons: "Run Depreciation Now", "Export Excel". Instructions for setup.
- **`mobile_snapshot.html`** (85 lines) — Telegram Mini App view. Compact layout: total balance, monthly income/expense, active assets count, link to full dashboard. Designed for 400×600 mobile viewport.

### Static Assets
- **`static/css/style.css`** (264 lines) — Dark blue theme (`rgb(0, 25, 152)`). Sidebar navigation (fixed left), dashboard grid layout, card components with shadows, table styling, badge variants (success/warning/danger), progress bars, responsive breakpoints, modal overlay.
- **`static/js/chart.js`** (137 lines) — Two Chart.js configurations: 1) Doughnut chart for category breakdown (income/expense toggle), 2) Bar chart for monthly cash flow. Dark blue color palette matching the CSS theme. Formatters for VND currency.

### Additional Files
- **`portfolio_dashboard.html`** (444 lines) — Standalone HTML page (not Flask-served). Vietnamese language. Has tabs: Overview (allocation donut, value bar), Projection 5Y (line chart), Best/Base/Worst scenarios (bar chart), Transactions (table). Uses SheetJS (xlsx) library for Excel file upload. Includes hardcoded sample data. Can be opened directly in a browser (no server needed). This is a supplementary tool, not part of the main app.
- **`read_excel_temp.py`** (16 lines) — Temporary debug script: reads `My portfolio.xlsm` with `openpyxl`, prints sheet names and first 5 rows of each sheet using pandas. Used during development to understand Excel structure.
- **`deploy.bat`** (45 lines) — Windows automation: initializes git, creates `.gitignore`, adds all files, commits, creates GitHub repo via `gh repo create`, and pushes. Runs on Windows only.
- **`genuine-box-500214-e2-5a8934bf85be.json`** (13 lines) — Google Cloud service account private key. Contains `type`, `project_id`, `private_key_id`, `private_key`, `client_email`, `client_id`, `auth_uri`, `token_uri`. The `client_email` is used by `gspread` for authentication.
- **`My portfolio.xlsm`** — Binary Excel file with VBA macros. Used by `excel_sync.py` as the legacy portfolio tracking file (fallback when Google Sheets is unavailable).

---

## Database Schema

```sql
-- Core transaction log
CREATE TABLE transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT NOT NULL CHECK(type IN ('income', 'expense')),
    amount REAL NOT NULL,
    category TEXT NOT NULL,
    description TEXT DEFAULT '',
    bank TEXT DEFAULT 'tien_mat',
    date TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);

-- Capitalized assets
CREATE TABLE assets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    purchase_price REAL NOT NULL,
    current_value REAL NOT NULL,
    purchase_date TEXT NOT NULL,
    category TEXT NOT NULL,
    lifespan_months INTEGER NOT NULL,
    status TEXT DEFAULT 'active' CHECK(status IN ('active', 'liquidated')),
    liquidated_price REAL,
    liquidated_date TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

-- Monthly depreciation trail
CREATE TABLE depreciation_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id INTEGER NOT NULL,
    month INTEGER NOT NULL,
    year INTEGER NOT NULL,
    depreciation_amount REAL NOT NULL,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (asset_id) REFERENCES assets(id)
);

-- Key-value settings
CREATE TABLE settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
```

**Relationships:**
- `depreciation_log.asset_id` → `assets.id` (one asset has many depreciation logs)
- No FK cascade — application code handles consistency (`asset_manager.py`)

---

## Data Flows

### Flow 1: Recording an Expense

```
User sends "-200 lunch" in Telegram
    │
    ▼
bot.py: parse_transaction()
    │  Extracts: type=expense, amount=200, description="lunch"
    │
    ▼
bot.py: guess_category("lunch")
    │  Matches keyword → returns "Ăn uống"
    │
    ▼  (if amount >= 1,000,000 VND)
bot.py: sends inline keyboard "Do you want to capitalize this as an asset?"
    │  If YES → asset capitalization flow (name, category, lifespan)
    │  If NO → continue
    │
    ▼
bot.py: sends inline keyboard "Choose bank account"
    │  [Techcombank] [VPBank] [Tiền mặt]
    │  User selects one → callback_data = "bank_techcombank" etc.
    │
    ▼
database.py: add_transaction(...)
    │  INSERT INTO transactions (type, amount, category, description, bank, date)
    │
    ▼
gsheets_sync.py: sync_expense_to_gsheet(data)
    │  Appends row to Google Sheets "Expenses" worksheet
    │  (silent on failure)
    │
    ▼
excel_sync.py: sync_expense_to_excel(data)  (if file exists)
    │  Appends row to My expenses.xlsx
    │
    ▼
bot.py: sends "✅ Ghi nhận thành công! ..." confirmation message
```

### Flow 2: Asset Lifecycle

```
User sends "-15000000 xe máy" (expense >= 1M threshold)
    │
    ▼
Auto-capitalization prompt → User agrees
    │
    ▼
bot.py: asks asset name, category, lifespan
    │
    ▼
database.py: add_asset(name, purchase_price, lifespan_months, category, purchase_date)
    │  current_value = purchase_price, status = 'active'
    │
    ▼
gsheets_sync.py: sync_asset_to_gsheet(data)
    │
    ▼
scheduler.py: run_monthly_depreciation()  (1st of month at 00:05)
    │  Or: POST /api/run-depreciation (manual trigger)
    │
    ▼
asset_manager.py: for each active asset:
    │  depreciation = purchase_price / lifespan_months
    │  current_value -= depreciation
    │  INSERT INTO depreciation_log (asset_id, month, year, amount)
    │  IF current_value <= 0: status = 'liquidated'
    │
    ▼
User can manually liquidate via:
    │  /liquidate <id> <price>
    │  database.py: liquidate_asset(id, price)
    │  Sets liquidated_price, liquidated_date, status='liquidated'
```

### Flow 3: Web Dashboard Rendering

```
User opens browser at /dashboard
    │
    ▼
app.py: dashboard() route
    │
    ├── finance_logic.py: get_balance()         → bank balances, total
    ├── finance_logic.py: get_monthly_summary()  → income, expense, net
    ├── finance_logic.py: get_cash_flow()        → 12-month arrays
    ├── finance_logic.py: get_category_breakdown()→ category totals
    └── database.py: get_transactions(limit=10)  → recent items
    │
    ▼
Flask renders templates/dashboard.html with all data
    │  Jinja2 fills balance cards, stat cards, transaction table
    │  Chart.js configs embedded in HTML reference static/js/chart.js
    │  charts.js renders doughnut (categories) and bar (cash flow)
    │
    ▼
User sees a complete dashboard with all financial data
```

---

## Bot Commands Reference

| Command | Arguments | Description | Handler in `bot.py` |
|---------|-----------|-------------|---------------------|
| `/start` | none | Welcome message with feature highlights | `cmd_start()` |
| `/help` | none | Grouped command reference | `cmd_help()` |
| `/balance` | none | Per-bank + total balance | `cmd_balance()` |
| `/report` | `[month] [year]` | Monthly income/expense/categories (defaults to current) | `cmd_report()` |
| `/asset` | none | List all assets with depreciation | `cmd_asset()` |
| `/web` | none | Return web dashboard URL | `cmd_web()` |
| `/project` | `[years=5] [simulations=1000]` | Monte Carlo projection chart | `cmd_project()` |
| `/liquidate` | `<asset_id> [price]` | Liquidate an asset | `cmd_liquidate()` |
| `/export` | none | Download transactions Excel file | `cmd_export()` |
| `/buy` | `<name> <price>` | Register a new asset directly | `cmd_buy()` |
| `/sell` | `<asset_id> <price>` | Alias for `/liquidate` | `cmd_sell()` |

Plus a **message handler** (no prefix) that parses free-text like `+500 salary` or `-200 lunch`.

---

## API Endpoints

All JSON endpoints accept/return `Content-Type: application/json`.

| Method | Endpoint | Request Body / Params | Response |
|--------|----------|-----------------------|----------|
| GET | `/api/transactions` | `?type=expense&category=An+uong&from=2024-01-01&to=2024-12-31` | `{transactions: [{id, type, amount, category, description, bank, date}]}` |
| POST | `/api/transactions` | `{type, amount, category, description, bank, date}` | `{success: true, id: N}` |
| PUT | `/api/transactions/<id>` | `{type?, amount?, category?, description?, bank?, date?}` | `{success: true}` |
| DELETE | `/api/transactions/<id>` | none | `{success: true}` |
| GET | `/api/summary` | none | `{balance: {total, techcombank, vpbank, tien_mat}, monthly: {income, expense, net, count}}` |
| GET | `/api/assets` | none | `{summary: {active, total, original_value, current_value}, assets: [{...}]}` |
| GET | `/api/categories` | none | `{categories: ["An uong", "Di lai", ...]}` |
| GET | `/api/monthly-data` | `?year=2024` | `{months: [{month, income, expense, net}], year}` |
| POST | `/api/run-depreciation` | none | `{success: true, events: [{asset, amount, new_value}]}` |
| GET | `/ping` | none | `"pong"` (plain text) |
| POST | `/webhook/<token>` | Telegram Update JSON | `200 OK` |
| GET | `/export/excel` | none | Excel file download |
| GET | `/mobile-snapshot` | none | HTML page (Mini App) |

---

## How Key Features Work

### Bank Account Selection
When recording any expense, the bot presents 3 inline keyboard buttons: `Techcombank`, `VPBank`, `Tiền mặt`. Each button has a callback prefix like `bank_techcombank`. The callback handler extracts the bank name and saves it to `transactions.bank`. The `get_balance()` function in `finance_logic.py` sums amounts per bank group. The dashboard shows each bank's balance separately plus a total.

### Category Auto-Guessing
Hardcoded keyword→category mapping in `bot.py`. For example: `"lunch" → "Ăn uống"`, `"taxi" → "Đi lại"`, `"rent" → "Nhà cửa"`, `"salary" → "Lương"`. The mapping is a dict with ~30 entries. Matching is case-insensitive and checks if any keyword is a substring of the description. Falls back to `"Khác"` (Other) if no match.

### Asset Capitalization Threshold
Any expense ≥ 1,000,000 VND triggers an inline confirmation: "Do you want to capitalize this as an asset?" If the user agrees, the bot walks them through: asset name → category pick list → lifespan in months. It creates both a transaction (expense) and an asset record. The expense is recorded from the chosen bank; the asset starts depreciating the following month.

### Straight-Line Depreciation
`monthly_depreciation = purchase_price / lifespan_months`. Runs monthly via APScheduler (1st of month at 00:05) or manually via `POST /api/run-depreciation`. Each run creates a `depreciation_log` row and decrements `assets.current_value`. When `current_value ≤ 0`, asset is auto-liquidated. Depreciation only runs once per month per asset (checked via `depreciation_log`).

### Monte Carlo Simulation (`/project`)
Uses Geometric Brownian Motion: `S(t+1) = S(t) * exp((μ - 0.5σ²)Δt + σ√Δt * Z)` where `Z ~ N(0,1)`. Runs 1000 simulations per asset over 5 years (default). Plots the median (solid line), 5th percentile (lower band), and 95th percentile (upper band) for each of the 4 asset types (DCDS, DCDE, ETFVN30, CCQ). The chart is rendered via matplotlib with Vietnamese labels and sent as a Telegram photo.

### Google Sheets Sync
Every transaction and asset operation calls `gsheets_sync.py` functions. These authenticate via the service account JSON file (`genuine-box-500214-e2-...json`), open the configured Google Sheet by URL (stored in `.env` as `GSHEETS_EXPENSE_URL` and `GSHEETS_PORTFOLIO_URL`), and append a row to the appropriate worksheet. Failure is caught and logged but does not block the user operation.

### Scheduled Jobs
APScheduler runs in a background thread within the Flask app. Two jobs:
1. **Daily DB backup** — copies `finance.db` → `finance_backup_YYYYMMDD.db` at 02:00
2. **Monthly depreciation** — runs `asset_manager.run_monthly_depreciation()` at 00:05 on the 1st of each month

The scheduler is initialized in `app.py` via `start_scheduler(app)` after the Flask app is created.

### Telegram Mini App (`/mobile-snapshot`)
A lightweight mobile-optimized HTML page designed for Telegram's Mini App WebView. Shows: total balance, monthly income/expense, active asset count, and a button linking to the full dashboard. It is served via Flask at `/mobile-snapshot` and designed for a 400×600 viewport.

---

## Setup Guide

### Prerequisites
- Python 3.10+
- Telegram bot token (from [@BotFather](https://t.me/BotFather))
- (Optional) Google Cloud service account for Sheets sync
- (Optional) PythonAnywhere account for deployment

### Local Installation

```bash
# 1. Clone or copy the project
cd telegram-finance-bot

# 2. Create virtual environment
python -m venv venv
source venv/bin/activate      # Linux/Mac
# venv\Scripts\activate        # Windows

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env
# Edit .env with your values (see Configuration section)

# 5. Initialize database (auto-creates on first run)
python -c "from database import init_db; init_db()"

# 6. Run the Flask app (development)
python app.py
```

### Configuration (`.env`)

| Variable | Required | Description |
|----------|----------|-------------|
| `TELEGRAM_TOKEN` | Yes | Bot token from BotFather |
| `WEBHOOK_URL` | For webhook | Public URL for Telegram to call (e.g., `https://yourdomain.com/webhook`) |
| `DATABASE_PATH` | No | Path to SQLite DB (default: `instance/finance.db`) |
| `SECRET_KEY` | Yes | Flask session secret key (any random string) |
| `ADMIN_USER_ID` | No | Telegram user ID for admin-only features |
| `GSHEETS_EXPENSE_URL` | For GSheets | Google Sheets URL for expense tracking |
| `GSHEETS_PORTFOLIO_URL` | For GSheets | Google Sheets URL for portfolio tracking |
| `GSHEETS_JSON_PATH` | For GSheets | Path to service account JSON key file |

### Google Sheets Setup (Optional)
1. Go to [Google Cloud Console](https://console.cloud.google.com), create project → enable Google Sheets API
2. Create service account → download JSON key → save as `genuine-box-...json`
3. Share your Google Sheets with the service account `client_email` (viewer/edit)
4. Run `python setup_gsheets.py` to create required worksheets and headers

---

## Deployment

### PythonAnywhere (Free Tier)

> ⚠️ **PythonAnywhere dùng Python 3.11.** LUÔN dùng `python3.11` và `pip3.11`, KHÔNG dùng `py` hay `pip`.
> Xem hướng dẫn chi tiết: [`PYTHONANYWHERE_SETUP.md`](PYTHONANYWHERE_SETUP.md)

1. **Create web app**: Manual configuration → Python 3.11
2. **Clone code**:
   ```bash
   git clone https://github.com/nguyenquocminhtrading-design/telegram-finance-bot.git
   cd telegram-finance-bot
   ```
3. **Install deps** (bắt buộc dùng `pip3.11`):
   ```bash
   pip3.11 install --user -r requirements.txt
   ```
4. **WSGI file** (`/var/www/yourusername_pythonanywhere_com_wsgi.py`):
   ```python
   import sys
   path = '/home/yourusername/telegram-finance-bot'
   if path not in sys.path:
       sys.path.append(path)
   from app import app as application
   ```
5. **Set webhook**:
   ```bash
   cd ~/telegram-finance-bot
   python3.11 -c "
   from config import TELEGRAM_TOKEN, WEBHOOK_URL
   import requests
   url = f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/setWebhook?url={WEBHOOK_URL}/webhook/{TELEGRAM_TOKEN}'
   print(requests.get(url).json())
   "
   ```
6. **Keep alive**: Set up a cron-job.org task or PythonAnywhere scheduled task to ping `/ping` every 5 minutes (free tier sleeps after inactivity).

### Bot Mode: Polling vs Webhook

| Mode | Configuration | Use Case |
|------|--------------|----------|
| Polling | No webhook set, `bot.py` runs `bot.polling()` | Local dev |
| Webhook | Set webhook URL to `https://yourdomain.com/webhook/<token>` | Production (PythonAnywhere, Render, etc.) |

When using webhook mode, the bot is driven by Flask receiving Telegram updates via `POST /webhook/<token>`. The `bot.py` handler `route_webhook()` processes the incoming JSON. The token mismatch check prevents unauthorized calls.

---

## Extending the Project

### Adding a New Bot Command
1. Add handler function in `bot.py` (pattern: `def cmd_mycommand(message):`)
2. Register it: `@bot.message_handler(commands=['mycommand'])`
3. Add help text in `cmd_help()` under the appropriate section

### Adding a New Database Table
1. Add `CREATE TABLE` in `database.py:init_db()`
2. Add CRUD functions following existing patterns (cursor.execute/commit/fetch)
3. Add any business logic in a new module or existing `finance_logic.py`

### Adding a New Chart to Dashboard
1. Add data endpoint in `app.py` if existing APIs don't cover it
2. Add canvas element in the relevant template (e.g., `dashboard.html`)
3. Add Chart.js config in `static/js/chart.js`

### Adding a New Bank Account
1. Add the bank name to the inline keyboard list in `bot.py` (in the bank selection callback)
2. Add a field for it in `get_balance()` in `finance_logic.py`
3. The rest works automatically (transactions are tagged by bank)

---

## License

MIT
