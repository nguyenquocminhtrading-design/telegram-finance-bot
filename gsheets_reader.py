import os
import gspread
from google.oauth2.service_account import Credentials
from datetime import date

from config import GOOGLE_CREDENTIALS_FILE, EXPENSE_SHEET_NAME, PORTFOLIO_SHEET_NAME
from database import add_transaction, add_transfer, add_asset, get_db, clear_all_finance_data

SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive'
]

def get_gspread_client():
    if not os.path.exists(GOOGLE_CREDENTIALS_FILE):
        return None, f"File '{GOOGLE_CREDENTIALS_FILE}' not found."
    try:
        credentials = Credentials.from_service_account_file(
            GOOGLE_CREDENTIALS_FILE, scopes=SCOPES
        )
        client = gspread.authorize(credentials)
        return client, None
    except Exception as e:
        return None, f"Auth error: {e}"

def read_expenses_from_sheet():
    client, err = get_gspread_client()
    if not client:
        return None, err
    try:
        sheet = client.open(EXPENSE_SHEET_NAME)
        try:
            worksheet = sheet.worksheet("Expenses")
        except gspread.exceptions.WorksheetNotFound:
            return None, "Worksheet 'Expenses' not found."
        rows = worksheet.get_all_values()
        if len(rows) < 2:
            return [], None
        headers = rows[0]
        data = []
        for row in rows[1:]:
            if not any(row):
                continue
            record = dict(zip(headers, row))
            data.append(record)
        return data, None
    except Exception as e:
        return None, f"Error reading Expenses sheet: {e}"

def read_portfolio_from_sheet():
    client, err = get_gspread_client()
    if not client:
        return None, err
    try:
        sheet = client.open(PORTFOLIO_SHEET_NAME)
        try:
            worksheet = sheet.worksheet("Transaction")
        except gspread.exceptions.WorksheetNotFound:
            return None, "Worksheet 'Transaction' not found."
        rows = worksheet.get_all_values()
        if len(rows) < 2:
            return [], None
        headers = rows[0]
        data = []
        for row in rows[1:]:
            if not any(row):
                continue
            record = dict(zip(headers, row))
            data.append(record)
        return data, None
    except Exception as e:
        return None, f"Error reading Portfolio sheet: {e}"

def read_transfers_from_sheet():
    client, err = get_gspread_client()
    if not client:
        return None, err
    try:
        sheet = client.open(EXPENSE_SHEET_NAME)
        try:
            worksheet = sheet.worksheet("Transfers")
        except gspread.exceptions.WorksheetNotFound:
            return [], None
        rows = worksheet.get_all_values()
        if len(rows) < 2:
            return [], None
        headers = rows[0]
        data = []
        for row in rows[1:]:
            if not any(row):
                continue
            record = dict(zip(headers, row))
            data.append(record)
        return data, None
    except Exception as e:
        return None, f"Error reading Transfers sheet: {e}"

def sync_expenses_to_sqlite(data, user_id=0):
    imported = 0
    skipped = 0
    conn = get_db()
    existing = set()
    for r in conn.execute("SELECT description, amount, transaction_date FROM transactions WHERE user_id = ?", (user_id,)).fetchall():
        existing.add((r["description"], r["amount"], r["transaction_date"]))
    conn.close()

    for row in data:
        try:
            desc = row.get("Description", "").strip()
            amount_str = row.get("Amount", "0").replace(",", "").replace(" ", "")
            amount = float(amount_str) if amount_str else 0
            txn_date = row.get("Date", date.today().isoformat())
            cat = row.get("Category", "other").strip().lower()
            bank = row.get("Bank Account", "").strip()
            if (desc, amount, txn_date) in existing:
                skipped += 1
                continue
            add_transaction(user_id, amount, cat, desc, txn_date, is_asset=0, bank_account=bank)
            imported += 1
        except (ValueError, KeyError) as e:
            skipped += 1
    return imported, skipped

def sync_portfolio_to_sqlite(data, user_id=0):
    imported = 0
    skipped = 0
    conn = get_db()
    existing_assets = set()
    for r in conn.execute("SELECT name, original_value FROM assets WHERE user_id = ?", (user_id,)).fetchall():
        existing_assets.add((r["name"], r["original_value"]))
    conn.close()

    for row in data:
        try:
            name = row.get("Tài sản", "").strip()
            value_str = row.get("Giá trị", "0").replace(",", "").replace(" ", "")
            value = float(value_str) if value_str else 0
            trans_type = row.get("Loại GD", "").strip().lower()
            if not name or value <= 0:
                skipped += 1
                continue
            if (name, value) in existing_assets:
                skipped += 1
                continue
            if trans_type in ("mua", "buy"):
                tid = add_transaction(user_id, -value, "investment", f"Buy {name}", is_asset=1)
                add_asset(user_id, tid, name, value, 12)
                imported += 1
        except (ValueError, KeyError) as e:
            skipped += 1
    return imported, skipped


def _transfer_exists(user_id, txn_date, amount, from_bank, to_bank, description):
    conn = get_db()
    rows = conn.execute(
        """SELECT bank_account, amount
           FROM transactions
           WHERE user_id = ?
             AND category = 'transfer'
             AND transaction_date = ?
             AND description = ?
             AND ABS(amount) = ?""",
        (user_id, txn_date, description, abs(amount)),
    ).fetchall()
    conn.close()
    if len(rows) < 2:
        return False
    bank_amounts = {(r["bank_account"], round(abs(r["amount"]), 2)) for r in rows}
    return (from_bank, round(abs(amount), 2)) in bank_amounts and (to_bank, round(abs(amount), 2)) in bank_amounts


def sync_transfers_to_sqlite(data, user_id=0):
    imported = 0
    skipped = 0
    for row in data:
        try:
            txn_date = row.get("Date", date.today().isoformat())
            amount_str = row.get("Amount", "0").replace(",", "").replace(" ", "")
            amount = abs(float(amount_str)) if amount_str else 0
            from_bank = row.get("From", "").strip().upper()
            to_bank = row.get("To", "").strip().upper()
            desc = row.get("Description", "").strip()
            if not amount or not from_bank or not to_bank or not desc:
                skipped += 1
                continue
            if _transfer_exists(user_id, txn_date, amount, from_bank, to_bank, desc):
                skipped += 1
                continue
            add_transfer(user_id, amount, from_bank, to_bank, desc, txn_date)
            imported += 1
        except (ValueError, KeyError, AttributeError):
            skipped += 1
    return imported, skipped

def sync_all_from_sheets(user_id=0):
    results = {"expenses": {"imported": 0, "skipped": 0, "error": None},
               "transfers": {"imported": 0, "skipped": 0, "error": None},
               "portfolio": {"imported": 0, "skipped": 0, "error": None}}

    exp_data, err = read_expenses_from_sheet()
    if err:
        results["expenses"]["error"] = err
    elif exp_data is not None:
        imp, skip = sync_expenses_to_sqlite(exp_data, user_id)
        results["expenses"]["imported"] = imp
        results["expenses"]["skipped"] = skip

    transfer_data, err = read_transfers_from_sheet()
    if err:
        results["transfers"]["error"] = err
    elif transfer_data is not None:
        imp, skip = sync_transfers_to_sqlite(transfer_data, user_id)
        results["transfers"]["imported"] = imp
        results["transfers"]["skipped"] = skip

    port_data, err = read_portfolio_from_sheet()
    if err:
        results["portfolio"]["error"] = err
    elif port_data is not None:
        imp, skip = sync_portfolio_to_sqlite(port_data, user_id)
        results["portfolio"]["imported"] = imp
        results["portfolio"]["skipped"] = skip

    return results


def full_sync_from_sheets(user_id=0):
    """Xóa dữ liệu SQLite của user rồi import lại toàn bộ từ Google Sheets."""
    clear_all_finance_data(user_id)
    return sync_all_from_sheets(user_id)
