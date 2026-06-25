import sqlite3
import json
import time
import functools
from datetime import datetime, date
from config import DATABASE_PATH


def db_retry(max_retries=3, delay=0.3):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except sqlite3.OperationalError as e:
                    if "database is locked" not in str(e):
                        raise
                    if attempt < max_retries - 1:
                        time.sleep(delay * (2 ** attempt))
                        continue
                    raise
        return wrapper
    return decorator


def get_db():
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.executescript("""
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL DEFAULT 0,
            amount REAL NOT NULL,
            category TEXT NOT NULL DEFAULT 'other',
            description TEXT DEFAULT '',
            transaction_date TEXT NOT NULL DEFAULT (date('now')),
            is_asset INTEGER NOT NULL DEFAULT 0,
            bank_account TEXT DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS assets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL DEFAULT 0,
            transaction_id INTEGER REFERENCES transactions(id),
            name TEXT NOT NULL,
            original_value REAL NOT NULL,
            current_value REAL NOT NULL,
            depreciation_months INTEGER NOT NULL DEFAULT 12,
            start_date TEXT NOT NULL DEFAULT (date('now')),
            monthly_depreciation REAL NOT NULL DEFAULT 0,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS depreciation_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            asset_id INTEGER NOT NULL REFERENCES assets(id),
            month TEXT NOT NULL,
            depreciation_amount REAL NOT NULL,
            remaining_value REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
    """)
    try:
        conn.execute("ALTER TABLE transactions ADD COLUMN bank_account TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE assets ADD COLUMN ticker TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE assets ADD COLUMN last_nav REAL DEFAULT NULL")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE assets ADD COLUMN last_nav_date TEXT DEFAULT NULL")
    except sqlite3.OperationalError:
        pass
    conn.commit()
    conn.close()


@db_retry()
def add_transaction(user_id, amount, category, description, transaction_date=None, is_asset=0, bank_account=''):
    conn = get_db()
    if transaction_date is None:
        transaction_date = date.today().isoformat()
    cur = conn.execute(
        "INSERT INTO transactions (user_id, amount, category, description, transaction_date, is_asset, bank_account) VALUES (?,?,?,?,?,?,?)",
        (user_id, amount, category, description, transaction_date, is_asset, bank_account),
    )
    conn.commit()
    tid = cur.lastrowid
    conn.close()
    return tid


@db_retry()
def add_transfer(user_id, amount, from_bank, to_bank, description, transaction_date=None):
    """
    Ghi 1 lệnh chuyển tiền thành 2 dòng đối ứng trong cùng 1 SQLite transaction (atomic).
      - from_bank nhận  -abs(amount)  → tài khoản nguồn bị trừ
      - to_bank   nhận  +abs(amount)  → tài khoản đích được cộng
    Tổng balance không đổi (net = 0).
    Trả về (tid_out, tid_in) — rowid của 2 dòng.
    """
    if transaction_date is None:
        transaction_date = date.today().isoformat()
    conn = get_db()
    try:
        cur_out = conn.execute(
            "INSERT INTO transactions "
            "(user_id, amount, category, description, transaction_date, is_asset, bank_account) "
            "VALUES (?,?,?,?,?,?,?)",
            (user_id, -abs(amount), "transfer", description, transaction_date, 0, from_bank),
        )
        tid_out = cur_out.lastrowid

        cur_in = conn.execute(
            "INSERT INTO transactions "
            "(user_id, amount, category, description, transaction_date, is_asset, bank_account) "
            "VALUES (?,?,?,?,?,?,?)",
            (user_id, +abs(amount), "transfer", description, transaction_date, 0, to_bank),
        )
        tid_in = cur_in.lastrowid

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return tid_out, tid_in


def get_bank_balance(bank_account, user_id=0):
    """Trả về tổng số dư hiện tại của 1 tài khoản ngân hàng cụ thể."""
    conn = get_db()
    row = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) as bal FROM transactions "
        "WHERE bank_account = ? AND user_id = ?",
        (bank_account, user_id),
    ).fetchone()
    conn.close()
    return round(row["bal"], 2) if row else 0.0


def get_transactions(user_id, limit=100, offset=0, category=None, start_date=None, end_date=None):
    conn = get_db()
    params = [user_id]
    sql = "SELECT * FROM transactions WHERE user_id = ?"
    if category:
        sql += " AND category = ?"
        params.append(category)
    if start_date:
        sql += " AND transaction_date >= ?"
        params.append(start_date)
    if end_date:
        sql += " AND transaction_date <= ?"
        params.append(end_date)
    sql += " ORDER BY transaction_date DESC, id DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_transaction_by_id(tid):
    conn = get_db()
    row = conn.execute("SELECT * FROM transactions WHERE id = ?", (tid,)).fetchone()
    conn.close()
    return dict(row) if row else None


@db_retry()
def update_transaction(tid, amount, category, description, transaction_date, bank_account=None):
    conn = get_db()
    
    if bank_account is not None:
        conn.execute(
            "UPDATE transactions SET amount=?, category=?, description=?, transaction_date=?, bank_account=? WHERE id=?",
            (amount, category, description, transaction_date, bank_account, tid),
        )
    else:
        conn.execute(
            "UPDATE transactions SET amount=?, category=?, description=?, transaction_date=? WHERE id=?",
            (amount, category, description, transaction_date, tid),
        )
    conn.commit()
    conn.close()


@db_retry()
def delete_transaction(tid):
    conn = get_db()
    conn.execute("DELETE FROM transactions WHERE id = ?", (tid,))
    conn.commit()
    conn.close()


@db_retry()
def clear_all_transactions(user_id=0):
    """Xóa toàn bộ giao dịch của một user để phục vụ full resync."""
    conn = get_db()
    conn.execute("DELETE FROM transactions WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()


@db_retry()
def clear_all_assets(user_id=0):
    """Xóa toàn bộ asset và log liên quan của một user."""
    conn = get_db()
    asset_ids = [
        row["id"]
        for row in conn.execute("SELECT id FROM assets WHERE user_id = ?", (user_id,)).fetchall()
    ]
    if asset_ids:
        placeholders = ",".join("?" for _ in asset_ids)
        conn.execute(f"DELETE FROM depreciation_log WHERE asset_id IN ({placeholders})", asset_ids)
    conn.execute("DELETE FROM assets WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()


@db_retry()
def clear_all_finance_data(user_id=0):
    """Xóa toàn bộ dữ liệu giao dịch/tài sản của một user."""
    conn = get_db()
    asset_ids = [
        row["id"]
        for row in conn.execute("SELECT id FROM assets WHERE user_id = ?", (user_id,)).fetchall()
    ]
    if asset_ids:
        placeholders = ",".join("?" for _ in asset_ids)
        conn.execute(f"DELETE FROM depreciation_log WHERE asset_id IN ({placeholders})", asset_ids)
    conn.execute("DELETE FROM assets WHERE user_id = ?", (user_id,))
    conn.execute("DELETE FROM transactions WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()


def count_transactions(user_id, category=None, start_date=None, end_date=None):
    conn = get_db()
    params = [user_id]
    sql = "SELECT COUNT(*) as cnt FROM transactions WHERE user_id = ?"
    if category:
        sql += " AND category = ?"
        params.append(category)
    if start_date:
        sql += " AND transaction_date >= ?"
        params.append(start_date)
    if end_date:
        sql += " AND transaction_date <= ?"
        params.append(end_date)
    row = conn.execute(sql, params).fetchone()
    conn.close()
    return row["cnt"] if row else 0


def get_categories(user_id):
    conn = get_db()
    rows = conn.execute("SELECT DISTINCT category FROM transactions WHERE user_id = ? ORDER BY category", (user_id,)).fetchall()
    conn.close()
    return [r["category"] for r in rows]


# ------- Asset CRUD -------

@db_retry()
def add_asset(user_id, transaction_id, name, original_value, depreciation_months, start_date=None):
    if start_date is None:
        start_date = date.today().isoformat()
    monthly = round(original_value / depreciation_months, 2)
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO assets (user_id, transaction_id, name, original_value, current_value, depreciation_months, start_date, monthly_depreciation) VALUES (?,?,?,?,?,?,?,?)",
        (user_id, transaction_id, name, original_value, original_value, depreciation_months, start_date, monthly),
    )
    conn.commit()
    aid = cur.lastrowid
    conn.close()
    return aid


def get_assets(user_id, active_only=False):
    conn = get_db()
    sql = "SELECT * FROM assets WHERE user_id = ?"
    if active_only:
        sql += " AND is_active = 1"
    sql += " ORDER BY start_date DESC"
    rows = conn.execute(sql, (user_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_asset_by_id(aid):
    conn = get_db()
    row = conn.execute("SELECT * FROM assets WHERE id = ?", (aid,)).fetchone()
    conn.close()
    return dict(row) if row else None


@db_retry()
def update_asset_value(aid, new_value):
    conn = get_db()
    conn.execute("UPDATE assets SET current_value = ? WHERE id = ?", (new_value, aid))
    conn.commit()
    conn.close()


@db_retry()
def deactivate_asset(aid):
    conn = get_db()
    conn.execute("UPDATE assets SET is_active = 0 WHERE id = ?", (aid,))
    conn.commit()
    conn.close()


# ------- Depreciation Log -------

def log_depreciation(asset_id, month, amount, remaining):
    conn = get_db()
    conn.execute(
        "INSERT INTO depreciation_log (asset_id, month, depreciation_amount, remaining_value) VALUES (?,?,?,?)",
        (asset_id, month, amount, remaining),
    )
    conn.commit()
    conn.close()


def get_depreciation_logs(asset_id):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM depreciation_log WHERE asset_id = ? ORDER BY month", (asset_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ------- Settings -------

def get_setting(key, default=None):
    conn = get_db()
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else default


def set_setting(key, value):
    conn = get_db()
    conn.execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value)
    )
    conn.commit()
    conn.close()


# ------- User State (SQLite-backed, survives restart) -------

def save_state(user_id, data_dict):
    conn = get_db()
    for k, v in data_dict.items():
        conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (f"state_{user_id}_{k}", json.dumps(v, ensure_ascii=False))
        )
    conn.commit()
    conn.close()


def load_state(user_id):
    conn = get_db()
    prefix = f"state_{user_id}_"
    rows = conn.execute(
        "SELECT key, value FROM settings WHERE key LIKE ?", (prefix + "%",)
    ).fetchall()
    conn.close()
    state = {}
    for r in rows:
        # Strip the full "state_{user_id}_" prefix to get the real field name
        # e.g. "state_123_pending_bank" -> "pending_bank"
        k = r["key"][len(prefix):]
        try:
            state[k] = json.loads(r["value"])
        except (json.JSONDecodeError, ValueError):
            state[k] = r["value"]
    return state


def clear_state(user_id):
    conn = get_db()
    conn.execute("DELETE FROM settings WHERE key LIKE ?", (f"state_{user_id}_%",))
    conn.commit()
    conn.close()


def cleanup_stale_states(max_age_minutes=60):
    conn = get_db()
    conn.execute(
        "DELETE FROM settings WHERE key LIKE 'state_%'"
        " AND rowid NOT IN (SELECT rowid FROM settings"
        "  WHERE key LIKE 'state_%' ORDER BY rowid DESC LIMIT 100)"
    )
    conn.commit()
    conn.close()
