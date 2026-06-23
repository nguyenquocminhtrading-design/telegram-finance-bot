# -*- coding: utf-8 -*-
"""
test_gsheets.py - Script kiem tra ket noi Google Sheets

Chay bang:
    py -3 test_gsheets.py
"""
import sys
import os
import json

# Force UTF-8 output on Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import GOOGLE_CREDENTIALS_FILE, EXPENSE_SHEET_NAME, PORTFOLIO_SHEET_NAME

print("=" * 60)
print("  KIEM TRA KET NOI GOOGLE SHEETS")
print("=" * 60)

# Buoc 1: Kiem tra file credentials
print(f"\n[1] File credentials: {GOOGLE_CREDENTIALS_FILE}")
if os.path.exists(GOOGLE_CREDENTIALS_FILE):
    print("    [OK] File ton tai")
    with open(GOOGLE_CREDENTIALS_FILE) as f:
        svc = json.load(f)
    SERVICE_EMAIL = svc.get("client_email", "???")
    KEY_ID = svc.get("private_key_id", "???")
    print(f"    Service account: {SERVICE_EMAIL}")
    print(f"    Key ID: {KEY_ID}")
else:
    print("    [LOI] File KHONG ton tai!")
    sys.exit(1)

# Buoc 2: Khoi tao client
print("\n[2] Khoi tao gspread client...")
try:
    import gspread
    from google.oauth2.service_account import Credentials

    SCOPES = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    creds = Credentials.from_service_account_file(GOOGLE_CREDENTIALS_FILE, scopes=SCOPES)
    client = gspread.authorize(creds)
    print("    [OK] Client khoi tao thanh cong (chua goi API)")
except Exception as e:
    print(f"    [LOI] {e}")
    sys.exit(1)

# Buoc 3: Goi API that de test JWT token
print("\n[3] Goi API that (kiem tra JWT token)...")
try:
    sheets = client.list_spreadsheet_files()
    print(f"    [OK] Token hop le! Tim thay {len(sheets)} spreadsheet:")
    for s in sheets:
        print(f"         - {s['name']}")
except Exception as e:
    print(f"    [FAILED] {e}")
    err_str = str(e)
    if "Invalid JWT Signature" in err_str or "invalid_grant" in err_str:
        print()
        print("    NGUYEN NHAN: Private key trong JSON het han / bi thu hoi!")
        print()
        print("    HUONG DAN SUA:")
        print("    1. Vao: https://console.cloud.google.com")
        print("    2. Chon project: genuine-box-500214-e2")
        print("    3. IAM & Admin -> Service Accounts")
        print(f"    4. Tim service account: {SERVICE_EMAIL}")
        print("    5. Click vao -> tab KEYS")
        print(f"    6. Xem key ID '{KEY_ID}' con ton tai khong")
        print("    7. Neu khong co: Add Key -> Create New Key -> JSON -> Download")
        print("    8. Thay the file JSON cu trong project bang file moi")
        print("    9. Chay lai script nay de xac nhan")
    elif "403" in err_str or "Forbidden" in err_str:
        print()
        print("    NGUYEN NHAN: Google Sheets API / Drive API chua duoc bat!")
        print("    -> Vao Cloud Console -> APIs & Services -> Enable Sheets API & Drive API")
    sys.exit(1)

# Buoc 4: Kiem tra Expense Sheet
print(f"\n[4] Mo Expense Sheet: '{EXPENSE_SHEET_NAME}'")
try:
    sh = client.open(EXPENSE_SHEET_NAME)
    print(f"    [OK] Mo thanh cong (ID: {sh.id})")
    try:
        ws = sh.worksheet("Expenses")
        all_rows = ws.get_all_values()
        print(f"    [OK] Worksheet 'Expenses' co {len(all_rows)} dong (ke ca header)")
    except gspread.exceptions.WorksheetNotFound:
        print("    [OK] Worksheet 'Expenses' chua co -> se tu tao khi ghi lan dau")
except gspread.exceptions.SpreadsheetNotFound:
    print(f"    [LOI] Khong tim thay sheet '{EXPENSE_SHEET_NAME}'")
    print(f"    -> Tao Google Sheet ten '{EXPENSE_SHEET_NAME}' va Share Editor cho:")
    print(f"       {SERVICE_EMAIL}")
except Exception as e:
    print(f"    [LOI] {e}")

# Buoc 5: Kiem tra Portfolio Sheet
print(f"\n[5] Mo Portfolio Sheet: '{PORTFOLIO_SHEET_NAME}'")
try:
    sh = client.open(PORTFOLIO_SHEET_NAME)
    print(f"    [OK] Mo thanh cong (ID: {sh.id})")
    try:
        ws = sh.worksheet("Transaction")
        all_rows = ws.get_all_values()
        print(f"    [OK] Worksheet 'Transaction' co {len(all_rows)} dong")
    except gspread.exceptions.WorksheetNotFound:
        print("    [OK] Worksheet 'Transaction' chua co -> se tu tao khi ghi lan dau")
except gspread.exceptions.SpreadsheetNotFound:
    print(f"    [LOI] Khong tim thay sheet '{PORTFOLIO_SHEET_NAME}'")
    print(f"    -> Tao Google Sheet ten '{PORTFOLIO_SHEET_NAME}' va Share Editor cho:")
    print(f"       {SERVICE_EMAIL}")
except Exception as e:
    print(f"    [LOI] {e}")

print()
print("=" * 60)
print("  XONG.")
print("  Neu tat ca [OK] -> bot se ghi duoc vao Google Sheet.")
print("  Neu co [LOI] -> lam theo huong dan o tren.")
print("=" * 60)
