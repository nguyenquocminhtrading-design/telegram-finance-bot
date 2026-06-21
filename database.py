import sqlite3
from datetime import datetime, date
from config import DATABASE_PATH


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
    conn.commit()
    conn.close()


def add_transaction(user_id, amount, category, description, transaction_date=None, is_asset=0):
    conn = get_db()
    if transaction_date is None:
        transaction_date = date.today().isoformat()
    cur = conn.execute(
        "INSERT INTO transactions (user_id, amount, category, description, transaction_date, is_asset) VALUES (?,?,?,?,?,?)",
        (user_id, amount, category, description, transaction_date, is_asset),
    )
    conn.commit()
    tid = cur.lastrowid
    conn.close()
    return tid


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


def update_transaction(tid, amount, category, description, transaction_date):
    conn = get_db()
    conn.execute(
        "UPDATE transactions SET amount=?, category=?, description=?, transaction_date=? WHERE id=?",
        (amount, category, description, transaction_date, tid),
    )
    conn.commit()
    conn.close()


def delete_transaction(tid):
    conn = get_db()
    conn.execute("DELETE FROM transactions WHERE id = ?", (tid,))
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


def update_asset_value(aid, new_value):
    conn = get_db()
    conn.execute("UPDATE assets SET current_value = ? WHERE id = ?", (new_value, aid))
    conn.commit()
    conn.close()


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
