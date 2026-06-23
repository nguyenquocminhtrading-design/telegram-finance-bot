import os
import gspread
from google.oauth2.service_account import Credentials
from gspread_formatting import (
    CellFormat, TextFormat, Color, format_cell_range,
    set_frozen, get_default_format
)
from config import GOOGLE_CREDENTIALS_FILE, EXPENSE_SHEET_NAME, PORTFOLIO_SHEET_NAME

SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive'
]

HEADER_FORMAT = CellFormat(
    backgroundColor=Color(0.157, 0.306, 0.612),   # Dark blue (#284EA0)
    textFormat=TextFormat(bold=True, foregroundColor=Color(1, 1, 1)),  # White bold text
)

CURRENCY_FORMAT = CellFormat(
    numberFormat={"type": "NUMBER", "pattern": "#,##0"}
)

def apply_header_formatting(worksheet, num_cols):
    """Bold + color header row and freeze it."""
    try:
        col_letter = chr(ord('A') + num_cols - 1)
        format_cell_range(worksheet, f"A1:{col_letter}1", HEADER_FORMAT)
        set_frozen(worksheet, rows=1)
        print("  ✅ Header formatting applied (bold, color, frozen).")
    except Exception as e:
        print(f"  ⚠️ Could not apply header formatting (install gspread-formatting?): {e}")

def apply_currency_formatting(worksheet, amount_col_letter, num_data_rows=1000):
    """Apply currency format to the Amount column."""
    try:
        format_cell_range(
            worksheet,
            f"{amount_col_letter}2:{amount_col_letter}{num_data_rows + 1}",
            CURRENCY_FORMAT
        )
        print(f"  ✅ Currency format applied to column {amount_col_letter}.")
    except Exception as e:
        print(f"  ⚠️ Could not apply currency formatting: {e}")

def setup():
    print("Connecting to Google Cloud...")
    if not os.path.exists(GOOGLE_CREDENTIALS_FILE):
        print(f"ERROR: Credentials file '{GOOGLE_CREDENTIALS_FILE}' not found.")
        return

    credentials = Credentials.from_service_account_file(
        GOOGLE_CREDENTIALS_FILE, scopes=SCOPES
    )
    client = gspread.authorize(credentials)

    # ─── Expense Sheet ────────────────────────────────────────────────────────
    print("\n--- Setup Expense Sheet ---")
    try:
        sheet = client.open(EXPENSE_SHEET_NAME)
        print(f"Found '{EXPENSE_SHEET_NAME}'")

        try:
            worksheet = sheet.worksheet("Expenses")
            print("Tab 'Expenses' already exists.")
        except gspread.exceptions.WorksheetNotFound:
            worksheet = sheet.sheet1
            worksheet.update_title("Expenses")
            print("Renamed first tab to 'Expenses'.")

        if len(worksheet.get_all_values()) == 0:
            headers = ["Date", "Amount", "Category", "Description", "Bank Account"]
            worksheet.append_row(headers, value_input_option="USER_ENTERED", table_range="A1")
            print("Added headers for Expense.")
        else:
            print("Expense sheet already has data, skipping headers.")

        # Apply formatting regardless (idempotent)
        apply_header_formatting(worksheet, num_cols=5)
        apply_currency_formatting(worksheet, amount_col_letter="B")

    except gspread.exceptions.SpreadsheetNotFound:
        print(f"ERROR: Cannot find '{EXPENSE_SHEET_NAME}'. Please create it and share with the Service Account.")

    # ─── Portfolio Sheet ──────────────────────────────────────────────────────
    print("\n--- Setup Portfolio Sheet ---")
    try:
        sheet = client.open(PORTFOLIO_SHEET_NAME)
        print(f"Found '{PORTFOLIO_SHEET_NAME}'")

        try:
            worksheet = sheet.worksheet("Transaction")
            print("Tab 'Transaction' already exists.")
        except gspread.exceptions.WorksheetNotFound:
            worksheet = sheet.sheet1
            worksheet.update_title("Transaction")
            print("Renamed first tab to 'Transaction'.")

        if len(worksheet.get_all_values()) == 0:
            headers = ["Ngày", "Loại GD", "Tài sản", "Giá trị", "Phí GD", "Thuế bán", "Dòng tiền ròng", "Ghi chú"]
            worksheet.append_row(headers, value_input_option="USER_ENTERED", table_range="A1")
            print("Added headers for Portfolio.")
        else:
            print("Portfolio sheet already has data, skipping headers.")

        apply_header_formatting(worksheet, num_cols=8)
        apply_currency_formatting(worksheet, amount_col_letter="D")  # "Giá trị"
        apply_currency_formatting(worksheet, amount_col_letter="G")  # "Dòng tiền ròng"

    except gspread.exceptions.SpreadsheetNotFound:
        print(f"ERROR: Cannot find '{PORTFOLIO_SHEET_NAME}'. Please create it and share with the Service Account.")

if __name__ == "__main__":
    setup()
    print("\nHoàn tất kiểm tra!")
