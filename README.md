# Personal Finance Manager — Telegram Bot + Web Dashboard

Hệ thống quản lý tài chính cá nhân toàn diện: ghi chép thu/chi qua Telegram, theo dõi tài sản khấu hao, chuyển tiền giữa tài khoản, đồng bộ lên Google Sheets, và hiển thị toàn bộ trên Web Dashboard.

---

## Kiến trúc tổng quan (Pipeline)

```
Người dùng nhắn tin Telegram
        │
        ▼
[Telegram Server] ──POST──▶ /webhook/<token>
        │                        │
        │                   app.py (Flask)
        │                        │ process_new_updates()
        │                        ▼
        │                   bot.py (pyTelegramBotAPI)
        │                   ├── parse_transaction()   ← llm_parser.py (Gemini AI)
        │                   ├── parse_transaction_local() ← local_parser.py (regex)
        │                   ├── add_transaction()     ─┐
        │                   ├── add_transfer()         ├── database.py (SQLite)
        │                   ├── add_asset()           ─┘
        │                   ├── sync_expense_to_gsheet()  ─┐
        │                   ├── sync_transfer_to_gsheet()  ├── gsheets_sync.py
        │                   └── sync_asset_to_gsheet()    ─┘
        │
        ▼
Người dùng mở trình duyệt → /dashboard
        │
   app.py (Flask)
   ├── finance_logic.py   ← tính balance, report, cash flow
   ├── asset_manager.py   ← tổng hợp tài sản, khấu hao
   └── templates/         ← Jinja2 HTML + Chart.js
        │
        ▼
   Web Dashboard (dark UI, responsive)

Background (APScheduler trong app.py):
   scheduler.py ──▶ daily backup DB
                ──▶ monthly depreciation (1st of month)
```

---

## Cấu trúc thư mục

```
telegram-finance-bot/
├── app.py                  # Flask app: routes, REST API, webhook handler, scheduler init
├── bot.py                  # Telegram bot: handlers, parsers, inline keyboards, transfer logic
├── database.py             # SQLite CRUD: transactions, assets, depreciation, state, settings
├── finance_logic.py        # Tính toán thuần: balance, monthly summary, cash flow, report
├── asset_manager.py        # Vòng đời tài sản: khấu hao, thanh lý, tổng hợp
├── scheduler.py            # APScheduler: backup hàng ngày, khấu hao đầu tháng
├── simulation.py           # Monte Carlo: GBM projection, vẽ chart matplotlib
├── local_parser.py         # Parser regex thuần: nhận dạng tiếng Việt, số tiền, bank, transfer
├── llm_parser.py           # Parser AI: gọi Gemini API, fallback nếu local_parser không hiểu
├── gsheets_sync.py         # Đồng bộ Google Sheets: Expenses, Transfers, Portfolio tabs
├── gsheets_reader.py       # Đọc dữ liệu từ Google Sheets về để import vào SQLite
├── excel_sync.py           # Đồng bộ Excel local: legacy fallback khi không có GSheets
├── nav_fetcher.py          # Lấy NAV quỹ từ VNSignal API, cập nhật tài sản đầu tư
├── config.py               # Load .env: token, webhook URL, DB path, admin ID, GSheets keys
├── setup_gsheets.py        # Script chạy 1 lần: tạo worksheets và headers trong Google Sheets
├── read_excel_temp.py      # Debug script: in cấu trúc file Excel ra console
├── requirements.txt        # Danh sách pip dependencies
├── .env                    # Biến môi trường runtime (gitignored)
├── .env.example            # Template .env cho người dùng mới
├── .gitignore              # Ignore .env, __pycache__, venv/, credential JSON
├── deploy.bat / deploy.sh  # Script auto deploy lên GitHub
├── PYTHONANYWHERE_SETUP.md # Hướng dẫn deploy lên PythonAnywhere step-by-step
├── instance/
│   └── finance.db          # SQLite database (tự tạo khi chạy lần đầu)
├── static/
│   ├── css/style.css       # Dark blue theme, sidebar layout, responsive
│   └── js/chart.js         # Chart.js: doughnut (categories) + bar (cash flow)
└── templates/
    ├── dashboard.html      # Overview: balance, cash flow, transactions gần nhất, donut
    ├── transactions.html   # Bảng đầy đủ: filter, pagination, CRUD modal (no reload)
    ├── assets.html         # Danh mục tài sản: progress bar khấu hao, status badge
    ├── reports.html        # Báo cáo: 4 charts + bảng tháng
    ├── settings.html       # Cài đặt hệ thống, trigger khấu hao, export
    └── mobile_snapshot.html# Telegram Mini App: giao diện mobile compact
```

---

## Mô tả từng file

### `config.py`
Load biến môi trường từ `.env` qua `python-dotenv`. Export các hằng số:
- `TELEGRAM_TOKEN` — Bot token từ BotFather
- `WEBHOOK_URL` — URL public để Telegram POST update vào
- `DATABASE_PATH` — Đường dẫn SQLite (mặc định `instance/finance.db`)
- `SECRET_KEY` — Flask session key
- `ADMIN_USER_ID` — Telegram user ID được phép dùng bot (0 = cho phép tất cả)
- `GEMINI_API_KEY` — Key Gemini AI cho LLM parser
- `GOOGLE_CREDENTIALS_FILE` — Đường dẫn service account JSON
- `EXPENSE_SHEET_NAME` / `PORTFOLIO_SHEET_NAME` — Tên Google Sheet

---

### `database.py`
Toàn bộ SQLite layer. Schema 4 bảng:

| Bảng | Mô tả |
|------|-------|
| `transactions` | Mọi giao dịch thu/chi/chuyển tiền. Cột quan trọng: `amount` (dương=vào, âm=ra), `category`, `bank_account`, `is_asset` |
| `assets` | Tài sản vốn hóa. Cột: `name`, `original_value`, `current_value`, `depreciation_months`, `is_active`, `ticker`, `last_nav` |
| `depreciation_log` | Lịch sử khấu hao hàng tháng mỗi tài sản |
| `settings` | Key-value store: dùng để lưu user state (pending_bank, pending_transfer_pick, ...) và các setting hệ thống |

**Hàm chính:**

| Hàm | Mô tả |
|-----|-------|
| `init_db()` | Tạo tables nếu chưa có, chạy ALTER TABLE migration an toàn |
| `add_transaction()` | INSERT 1 giao dịch đơn lẻ |
| `add_transfer(uid, amount, from_bank, to_bank, desc)` | **Atomic**: INSERT 2 dòng đối ứng trong 1 SQLite transaction. `from_bank: -amount`, `to_bank: +amount`. Rollback nếu 1 cái fail. |
| `get_bank_balance(bank, uid)` | `SUM(amount)` của 1 tài khoản cụ thể |
| `save_state(uid, dict)` | Lưu trạng thái hội thoại vào bảng `settings` với prefix `state_{uid}_{key}` |
| `load_state(uid)` | Load toàn bộ state của user, strip đúng prefix để lấy key gốc (e.g. `pending_bank`) |
| `clear_state(uid)` | Xóa toàn bộ state của user sau khi hoàn thành flow |
| `cleanup_stale_states()` | Xóa state cũ, giữ 100 gần nhất — gọi bởi `/keepalive` |

---

### `bot.py`
Telegram bot handler. Chạy ở **webhook mode** (được `app.py` gọi `bot.process_new_updates()`).

**Commands:**

| Command | Mô tả |
|---------|-------|
| `/start` | Chào mừng |
| `/help` | Tham chiếu đầy đủ tất cả lệnh |
| `/balance` | Tổng số dư |
| `/bankbalance` | Số dư từng tài khoản (VCB, ACB, HDBANK, CASH, MOMO) |
| `/report` | Báo cáo tháng hiện tại (thu, chi, net) |
| `/asset` | Danh sách tài sản vốn hóa |
| `/buy <name> <qty> <price>` | Mua tài sản đầu tư |
| `/liquidate <id> <price>` | Thanh lý tài sản |
| `/nav <id> [ticker]` | Cập nhật NAV tài sản từ VNSignal |
| `/refresh` | Refresh NAV tất cả tài sản |
| `/sync` | Import dữ liệu từ Google Sheets về SQLite |
| `/project` | Chạy Monte Carlo, gửi chart photo |
| `/export` | Gửi file Excel transactions |
| `/web` | Link dashboard |
| `/setbalance <bank> <amount>` | Đặt số dư ban đầu cho 1 tài khoản |
| `/ping` `/dbcheck` `/gscheck` `/envcheck` `/logs` `/navtest` | Debug/health check |

**Free-text message flow (core UX):**
1. User gửi tin nhắn tự nhiên (vd: `-70 xăng`, `chuyển 2tr vcb sang acb`)
2. `parse_transaction()` (Gemini AI) thử parse trước
3. Nếu fail → `parse_transaction_local()` (regex) làm fallback
4. Dựa trên `action`:
   - **expense/income + bank đã biết** → ghi thẳng vào DB + sync GSheets
   - **expense/income không có bank** → hiện inline keyboard `[VCB][ACB][HDBANK][CASH][MOMO]`
   - **transfer đủ thông tin** → gọi `do_transfer()` ngay
   - **transfer thiếu from_bank** → hỏi từ đâu qua inline keyboard (`trfrom:`)
   - **transfer thiếu to_bank** → hỏi sang đâu qua inline keyboard (`trto:`)

**Hàm transfer quan trọng:**

| Hàm | Mô tả |
|-----|-------|
| `do_transfer(uid, amount, desc, from_bank, to_bank)` | Gọi `add_transfer()` atomic, sync GSheets tab Transfers, hiển thị balance 2 bank |
| `ask_transfer_from(uid, amount)` | Gửi keyboard hỏi tài khoản nguồn, lưu state `pending_transfer_pick` |
| `ask_transfer_to(uid, amount, from_bank)` | Gửi keyboard hỏi tài khoản đích (loại from_bank khỏi danh sách) |
| `handle_trfrom_callback` | Sau khi chọn from → đổi keyboard thành chọn to |
| `handle_trto_callback` | Sau khi chọn to → gọi `do_transfer()`, edit message xóa keyboard |

**Inline keyboard callbacks:**

| Prefix | Xử lý |
|--------|-------|
| `bank:` | Chọn bank cho expense/income |
| `cap:yes/no` | Quyết định vốn hóa tài sản |
| `trfrom:` | Chọn tài khoản nguồn transfer |
| `trto:` | Chọn tài khoản đích transfer |

---

### `local_parser.py`
Parser thuần Python (không cần API), dùng regex + keyword matching. Chạy khi Gemini fail hoặc không có API key.

**Nhận dạng:**
- **Amount**: hỗ trợ `2tr`, `500k`, `1.5tr`, `200,000`, `50đ`
- **Bank**: `vcb/vietcombank → VCB`, `acb → ACB`, `momo → MOMO`, `tiền mặt/cash → CASH`, ...
- **Action**:
  - `income`: "nhận", "lương", "thưởng", "cashback", ...
  - `transfer`: `TRANSFER_PATTERN` — regex bắt "chuyển X từ A sang B"
  - `transfer` ngắn: `TRANSFER_SHORT_PATTERN` — "rút X từ A" (to_bank mặc định CASH)
  - `expense`: mặc định nếu không khớp
- **Category**: scoring keyword (food, transport, entertainment, bill, health, shopping, salary)
- **Description**: loại bỏ amount tokens và bank keywords, giữ lại nội dung chính

---

### `llm_parser.py`
Gọi Gemini AI (`gemini-1.5-flash`) với prompt tiếng Việt để parse transaction. Trả về JSON với:
`{action, amount, category, bank, from_bank, to_bank, description}`

Được gọi trước `local_parser`. Nếu fail hoặc không có `GEMINI_API_KEY` → trả về `None` → fallback local.

---

### `finance_logic.py`
Layer tính toán thuần (không ghi DB, không side effect):

| Hàm | Mô tả |
|-----|-------|
| `get_balance(user_id)` | `SUM(amount)` tất cả transactions (trừ is_asset=1). Transfer không ảnh hưởng vì net=0 |
| `get_monthly_summary(user_id, year, month)` | Thu + chi tháng, **exclude category='transfer'** |
| `get_category_breakdown()` | Tổng chi theo category, exclude transfer |
| `get_cash_flow(months=12)` | Mảng 12 tháng gần nhất, mỗi tháng có income/expense/net |
| `get_full_report()` | Gộp tất cả trên vào 1 dict cho dashboard/API |

> ⚠️ **Lưu ý thiết kế**: Transfer category='transfer' bị **exclude** khỏi mọi báo cáo thu/chi. Chỉ ảnh hưởng balance từng bank (qua `get_bank_balance()` trong database.py).

---

### `asset_manager.py`
Quản lý vòng đời tài sản:

| Hàm | Mô tả |
|-----|-------|
| `get_asset_summary()` | Tổng hợp: active count, total original/current value, list chi tiết |
| `run_monthly_depreciation()` | Khấu hao thẳng: `monthly = original_value / depreciation_months`, trừ vào `current_value`, ghi `depreciation_log` |
| `liquidate_asset(aid, sell_price)` | Đặt `is_active=0`, tính gain/loss, ghi transaction thu nhập từ thanh lý |

---

### `gsheets_sync.py`
Ghi dữ liệu lên Google Sheets. Mỗi hàm tự authenticate và append row:

| Hàm | Tab GSheets | Columns |
|-----|-------------|---------|
| `sync_expense_to_gsheet(data)` | `Expenses` | Date, Amount, Category, Description, Bank Account |
| `sync_transfer_to_gsheet(data)` | `Transfers` (**auto-create**) | Date, Amount, From, To, Description |
| `sync_asset_to_gsheet(data)` | `Transaction` (Portfolio sheet) | Ngày, Loại GD, Tài sản, Giá trị, Phí, Thuế, Dòng tiền ròng, Ghi chú |
| `sync_capitalized_asset(data)` | `Capitalized Assets` | Date, Tên, Gốc, Còn lại, Tháng, KH/tháng, Đã KH, Trạng thái |
| `sync_depreciation_log(data)` | `Depreciation Log` | Date, Tên, Period, Amount, Remaining |

> Tab `Transfers` được **tự động tạo** khi gọi lần đầu nếu chưa tồn tại trong Google Sheet.

---

### `gsheets_reader.py`
Import dữ liệu từ Google Sheets **về** SQLite (chiều ngược lại với `gsheets_sync.py`):
- `sync_all_from_sheets()` — đọc Expenses + Portfolio, import vào DB, dedup theo date+amount+desc
- `read_expenses_from_sheet()` / `read_portfolio_from_sheet()` — đọc raw data để preview
- Được trigger bởi `/sync` command

---

### `nav_fetcher.py`
Lấy NAV (Net Asset Value) quỹ mở từ VNSignal API:
- `fetch_nav_from_vnsignal(ticker)` — trả về (nav, date, error)
- `update_asset_nav(asset_id, ticker)` — cập nhật `last_nav` + `current_value` của tài sản
- `refresh_all_assets()` — chạy update cho tất cả assets có ticker
- Trigger: `/nav <id> [ticker]`, `/refresh`, `/navtest <ticker>`

---

### `app.py`
Flask application với đầy đủ routes:

**Web pages:**

| Route | Template | Dữ liệu |
|-------|----------|---------|
| `/dashboard` | `dashboard.html` | balance, monthly summary, recent 5 txns, assets |
| `/transactions` | `transactions.html` | paginated txns với filter category/date |
| `/assets` | `assets.html` | asset summary + list |
| `/reports` | `reports.html` | full report với cash flow |
| `/snapshot` | `mobile_snapshot.html` | compact mobile view |

**REST API:**

| Method | Endpoint | Mô tả |
|--------|----------|-------|
| GET | `/api/transactions` | Danh sách txns (filter, paginate) |
| POST | `/api/transactions` | Thêm transaction mới |
| PUT | `/api/transactions/<id>` | Sửa transaction |
| DELETE | `/api/transactions/<id>` | Xóa transaction |
| GET | `/api/summary` | Balance + monthly stats |
| GET | `/api/assets` | Asset summary |
| GET | `/api/categories` | Danh sách categories |
| POST | `/api/run-depreciation` | Trigger khấu hao ngay |
| GET | `/api/export/excel` | Download file .xlsx |

**Infrastructure:**

| Route | Mô tả |
|-------|-------|
| `POST /webhook/<token>` | Nhận Telegram updates, dedup bằng `recent_update_ids`, process trong ThreadPoolExecutor với timeout 12s, dùng `webhook_lock` tránh concurrent processing |
| `GET /health` | Kiểm tra DB + scheduler |
| `GET /keepalive` | Touch DB + restart scheduler nếu chết + cleanup stale states |
| `POST /webhook/register` | Re-register webhook với Telegram |
| `GET /webhook/info` | Lấy trạng thái webhook từ Telegram API |

---

### `scheduler.py`
APScheduler background jobs (chạy trong thread của Flask):

| Job | Lịch | Mô tả |
|-----|------|-------|
| `backup_db` | Hằng ngày 02:00 | Copy `finance.db` → `finance_backup_YYYYMMDD.db` |
| `monthly_depreciation` | Ngày 1 hàng tháng 00:05 | Chạy `run_monthly_depreciation()`, ghi log kết quả |

---

### `simulation.py`
Monte Carlo portfolio projection:
- `run_monte_carlo(initial_value, monthly_saving, months, n_simulations)` — Geometric Brownian Motion: `S(t+1) = S(t) * exp((μ - 0.5σ²)Δt + σ√Δt * Z)` với `Z ~ N(0,1)`
- `generate_projection_chart(paths, monthly)` — Vẽ matplotlib chart: median + P10 + P90 bands, trả về `BytesIO` để bot gửi photo

---

### `excel_sync.py`
Fallback khi không dùng Google Sheets. Ghi vào file Excel local:
- `sync_expense_to_excel(data)` — append vào `My expenses.xlsx`

---

### `setup_gsheets.py`
Script chạy **1 lần** để chuẩn bị Google Sheets:
1. Xác thực service account
2. Kiểm tra + tạo worksheet `Expenses` trong expense sheet (nếu trống thì thêm header)
3. Kiểm tra + tạo worksheet `Transaction` trong portfolio sheet
4. Kiểm tra + tạo worksheet `Capitalized Assets`, `Depreciation Log`, `Transfers`
5. Report kết quả

> Worksheet `Transfers` cũng được `gsheets_sync.py` tự động tạo khi có transfer đầu tiên (không cần chạy script này trước).

---

## Database Schema (thực tế)

```sql
CREATE TABLE transactions (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id           INTEGER NOT NULL DEFAULT 0,
    amount            REAL NOT NULL,          -- dương=vào, âm=ra
    category          TEXT NOT NULL DEFAULT 'other',  -- 'transfer' được exclude khỏi report
    description       TEXT DEFAULT '',
    transaction_date  TEXT NOT NULL DEFAULT (date('now')),
    is_asset          INTEGER NOT NULL DEFAULT 0,
    bank_account      TEXT DEFAULT '',        -- VCB | ACB | HDBANK | CASH | MOMO
    created_at        TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE assets (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id               INTEGER NOT NULL DEFAULT 0,
    transaction_id        INTEGER REFERENCES transactions(id),
    name                  TEXT NOT NULL,
    original_value        REAL NOT NULL,
    current_value         REAL NOT NULL,
    depreciation_months   INTEGER NOT NULL DEFAULT 12,
    start_date            TEXT NOT NULL DEFAULT (date('now')),
    monthly_depreciation  REAL NOT NULL DEFAULT 0,
    is_active             INTEGER NOT NULL DEFAULT 1,
    ticker                TEXT DEFAULT '',    -- mã quỹ/CP để fetch NAV
    last_nav              REAL DEFAULT NULL,
    last_nav_date         TEXT DEFAULT NULL,
    created_at            TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE depreciation_log (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id             INTEGER NOT NULL REFERENCES assets(id),
    month                TEXT NOT NULL,       -- format YYYY-MM
    depreciation_amount  REAL NOT NULL,
    remaining_value      REAL NOT NULL
);

CREATE TABLE settings (
    key    TEXT PRIMARY KEY,
    value  TEXT NOT NULL
    -- Dùng double-purpose:
    -- 1. System settings: key='last_depreciation', value='2025-06-01'
    -- 2. User state:      key='state_{uid}_{field}', value=JSON
);
```

---

## Toàn bộ Data Flows

### Flow 1: Ghi chi tiêu thông thường

```
User: "-70 xăng vcb"
    ↓
bot.py: parse_transaction() [Gemini]
    → fail hoặc không đủ thông tin
    ↓
bot.py: parse_transaction_local() [regex]
    → action=expense, amount=70000, cat=transport, bank=VCB
    ↓
bot.py: add_transaction(uid, -70000, "transport", "xăng", bank="VCB")
    ↓
bot.py: sync_expense_to_gsheet({date, -70000, transport, xăng, VCB})
    → append 1 dòng vào tab "Expenses"
    ↓
Bot reply: "✅ Recorded: -70,000 - xăng (VCB)\nBalance: 5,000,000"
```

### Flow 2: Ghi chi tiêu không nói bank → hỏi keyboard

```
User: "-70 xăng"
    ↓ parse → amount=-70000, bank=None
    ↓
bot.py: ask_bank(uid, -70000, "transport", "xăng")
    → save_state: pending_bank={amount, cat, desc}
    → gửi keyboard [VCB][ACB][HDBANK][CASH][MOMO]
    ↓
User bấm: [VCB]
    ↓
handle_bank_callback(call, data="bank:VCB")
    → load_state → pending_bank found
    → add_transaction(uid, -70000, "transport", "xăng", bank="VCB")
    → clear_state
    → sync_expense_to_gsheet(...)
    → edit message: "✅ Recorded: -70,000 - xăng (VCB)" (keyboard biến mất)
```

### Flow 3: Chuyển tiền đầy đủ

```
User: "chuyển 2tr từ vcb sang acb"
    ↓
local_parser: TRANSFER_PATTERN match
    → action=transfer, amount=2000000, from_bank=VCB, to_bank=ACB
    ↓
bot.py: do_transfer(uid, 2000000, desc, "VCB", "ACB")
    ↓
    database.py: add_transfer() [ATOMIC SQLite transaction]
        → INSERT transactions: -2,000,000 / bank=VCB / cat=transfer
        → INSERT transactions: +2,000,000 / bank=ACB / cat=transfer
        → COMMIT (hoặc ROLLBACK nếu lỗi)
    ↓
    gsheets_sync.py: sync_transfer_to_gsheet()
        → Nếu tab "Transfers" chưa có → auto-create với header
        → append 1 dòng: [date, 2000000, VCB, ACB, desc]
    ↓
    database.py: get_bank_balance("VCB"), get_bank_balance("ACB")
    ↓
Bot reply:
    ✅ Chuyển 2,000,000 VND
    VCB → ACB
    💳 VCB: +3,000,000
    💳 ACB: +7,000,000
```

### Flow 4: Chuyển tiền không nói bank → hỏi 2 bước

```
User: "chuyển 500k"
    ↓ parse → action=transfer, amount=500000, from_bank=None, to_bank=None
    ↓
bot.py: ask_transfer_from(uid, 500000)
    → save_state: pending_transfer_pick={amount=500000, step="from"}
    → gửi keyboard [VCB][ACB][HDBANK][CASH][MOMO]
    ↓
User bấm: [VCB]  → handle_trfrom_callback
    → update state: step="to", from_bank="VCB"
    → edit keyboard thành [ACB][HDBANK][CASH][MOMO]  (loại VCB)
    ↓
User bấm: [MOMO]  → handle_trto_callback
    → load state: amount=500000, from_bank="VCB"
    → clear_state
    → do_transfer(uid, 500000, "Chuyển từ VCB sang MOMO", "VCB", "MOMO")
    → edit message: "✅ Chuyển 500,000 VND\nVCB → MOMO\n💳 ..."
```

### Flow 5: Vốn hóa tài sản

```
User: "-15000000 mua laptop"  (amount > 199)
    ↓ handle_bank_callback chọn VCB
    ↓ add_transaction(-15000000, "shopping", "mua laptop", bank=VCB)
    ↓ (amount < -199) → hỏi: "Capitalize as asset? [✅ Yes][❌ No]"
    ↓
User bấm [✅ Yes]  → handle_cap_callback(yes)
    → save_state: pending_capitalize={tid, value=15000000, step="ask_name"}
    → edit message: "📦 Capitalize: Yes"
    → gửi: "What is the asset name?"
    ↓
User: "MacBook Pro 14"
    → handle_capitalize_step(step=ask_name)
    → save name, step="ask_months"
    → hỏi: "Depreciation period (months)?"
    ↓
User: "36"
    → handle_capitalize_step(step=ask_months)
    → add_asset(uid, tid, "MacBook Pro 14", 15000000, 36)
    → UPDATE transactions SET is_asset=1 WHERE id=tid
    → clear_state
    → reply: "✅ Asset capitalized! Monthly: 416,667"
```

### Flow 6: Web Dashboard

```
Browser: GET /dashboard
    ↓
app.py: dashboard()
    ↓
    finance_logic.get_full_report() → {balance, monthly, cash_flow, categories}
    asset_manager.get_asset_summary() → {active_count, total_current, assets[]}
    database.get_transactions(limit=5) → recent transactions
    ↓
Flask render_template("dashboard.html", ...)
    ↓
Browser: Dark UI với balance card, cash flow bar chart, category donut, asset list
```

### Flow 7: Scheduled Jobs (background)

```
Hàng ngày 02:00:
    scheduler.py → backup_database()
    → copy instance/finance.db → instance/finance_backup_20250625.db

Ngày 1 hàng tháng 00:05:
    scheduler.py → run_monthly_depreciation()
    → asset_manager.run_monthly_depreciation()
    → For each active asset:
        current_value -= original_value / depreciation_months
        INSERT depreciation_log
        IF current_value <= 0: is_active = 0
    → set_setting("last_depreciation", "2025-06-01")
```

---

## Tài khoản ngân hàng hỗ trợ

| Tên | Keywords nhận dạng |
|-----|-------------------|
| `VCB` | vcb, vietcombank, vietcom |
| `ACB` | acb, asia commercial |
| `HDBANK` | hdbank, hd bank |
| `CASH` | cash, tiền mặt, tien mat, mặt, tienmat |
| `MOMO` | momo, ví điện tử |

Thêm bank mới: chỉnh `BANK_KEYWORDS` trong `local_parser.py` và `VALID_BANKS` trong `bot.py`.

---

## Setup & Chạy

### Cài đặt local

```bash
git clone <repo>
cd telegram-finance-bot

python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # Mac/Linux

pip install -r requirements.txt
cp .env.example .env         # điền giá trị vào .env
python app.py                # chạy Flask dev server
```

### Biến môi trường (`.env`)

| Biến | Bắt buộc | Mô tả |
|------|----------|-------|
| `TELEGRAM_TOKEN` | ✅ | Bot token từ @BotFather |
| `WEBHOOK_URL` | ✅ (production) | URL public, vd: `https://user.pythonanywhere.com/webhook/TOKEN` |
| `SECRET_KEY` | ✅ | Chuỗi ngẫu nhiên cho Flask session |
| `ADMIN_USER_ID` | Nên có | Telegram user ID của bạn (lấy qua @userinfobot) |
| `GEMINI_API_KEY` | Khuyến nghị | Key Gemini AI — nếu không có thì chỉ dùng local parser |
| `GOOGLE_CREDENTIALS_FILE` | Nếu dùng GSheets | Đường dẫn file JSON service account |
| `EXPENSE_SHEET_NAME` | Nếu dùng GSheets | Tên Google Sheet chứa Expenses |
| `PORTFOLIO_SHEET_NAME` | Nếu dùng GSheets | Tên Google Sheet chứa Portfolio |

### Google Sheets Setup

```bash
# 1. Vào Google Cloud Console → tạo Service Account → download JSON
# 2. Share Google Sheet với email service account (Editor)
# 3. Đặt tên Sheet trong .env
python setup_gsheets.py      # tạo tabs và headers
```

Tab `Transfers` sẽ **tự động được tạo** khi có transfer đầu tiên — không cần chạy setup.

---

## Deploy lên PythonAnywhere

> Xem chi tiết: [`PYTHONANYWHERE_SETUP.md`](PYTHONANYWHERE_SETUP.md)

```bash
# 1. Upload code lên PythonAnywhere (git clone hoặc upload)
pip3.11 install --user -r requirements.txt

# 2. WSGI file trỏ vào app.py
# from app import app as application

# 3. Set webhook
python3.11 -c "
from config import TELEGRAM_TOKEN, WEBHOOK_URL
import requests
r = requests.post(f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/setWebhook',
                  json={'url': WEBHOOK_URL, 'max_connections': 1})
print(r.json())
"

# 4. Keepalive (QUAN TRỌNG — free tier sleep sau 10p)
# Dùng cron-job.org, gọi /keepalive mỗi 3 phút
# URL: https://yourusername.pythonanywhere.com/keepalive
```

**Webhook flow trên production:**
```
Telegram → POST /webhook/<token>
app.py: dedup update_id → webhook_lock.acquire() → ThreadPoolExecutor(timeout=12s)
    → bot.process_new_updates([update])
    → [all handlers run] → webhook_lock.release()
→ return "OK" 200
```

---

## Tech Stack

| Package | Version | Role |
|---------|---------|------|
| Flask | 3.1.1 | Web server + REST API + Jinja2 |
| pyTelegramBotAPI | 4.28.0 | Telegram bot framework (webhook mode) |
| python-dotenv | 1.1.0 | Load `.env` |
| gunicorn | 23.0.0 | WSGI production server |
| gspread | 6.1.2 | Google Sheets API client |
| google-auth | 2.30.0 | Service account authentication |
| openpyxl | 3.1.5 | Đọc/ghi Excel |
| APScheduler | 3.11.0 | Scheduled background jobs |
| numpy | 2.1.2 | Monte Carlo math |
| matplotlib | 3.9.2 | Chart generation |
| google-generativeai | — | Gemini AI API (LLM parser) |
| requests | 2.32.3 | HTTP calls |
| Chart.js | CDN | Client-side charts |

---

## License

MIT
