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

def _balance_formula(bank_row_ref):
    """
    Tạo công thức tính số dư cho 1 tài khoản:
      = Tổng từ Expenses (thu + chi)
      + Tổng nhận từ Transfers (cột To = bank → +amount)
      - Tổng gửi đi Transfers (cột From = bank → -amount)
    """
    return (
        f'=SUMIF(Expenses!E:E, {bank_row_ref}, Expenses!B:B)'
        f'+SUMIF(Transfers!D:D, {bank_row_ref}, Transfers!B:B)'
        f'-SUMIF(Transfers!C:C, {bank_row_ref}, Transfers!B:B)'
    )


def setup_summary_sheet(client):
    print("\n--- Setup Summary Sheet ---")
    try:
        sheet = client.open(EXPENSE_SHEET_NAME)
        try:
            ws_summary = sheet.worksheet("Summary")
            print("Tab 'Summary' already exists — updating formulas.")
        except gspread.exceptions.WorksheetNotFound:
            ws_summary = sheet.add_worksheet(title="Summary", rows="100", cols="20")
            print("Created tab 'Summary'.")

        # ── Đảm bảo tab Transfers tồn tại trước khi viết công thức ──
        try:
            sheet.worksheet("Transfers")
        except gspread.exceptions.WorksheetNotFound:
            ws_transfers = sheet.add_worksheet(title="Transfers", rows=1000, cols=6)
            ws_transfers.append_row(
                ["Date", "Amount", "From", "To", "Description"],
                value_input_option="USER_ENTERED",
            )
            print("  Auto-created tab 'Transfers' (needed for Summary formulas).")

        # ── Bank Balances (bao gồm MOMO + tính cả Transfers) ──
        banks = ["VCB", "ACB", "HDBANK", "CASH", "MOMO"]
        bank_rows = [[b] for b in banks]
        last_bank_row = 2 + len(banks) - 1  # Row 6 (A2..A6)
        balance_formulas = [[_balance_formula(f"A{2+i}")] for i in range(len(banks))]

        updates = [
            # Header
            {"range": "A1:B1", "values": [["Bank Account", "Balance"]]},
            # Bank names (A2:A6)
            {"range": f"A2:A{last_bank_row}", "values": bank_rows},
            # Balance formulas (B2:B6) — bao gồm Expenses + Transfers
            {"range": f"B2:B{last_bank_row}", "values": balance_formulas},
            # Total balance row
            {"range": f"A{last_bank_row+1}:B{last_bank_row+1}", "values": [
                ["TOTAL BALANCE", f"=SUM(B2:B{last_bank_row})"]
            ]},

            # ── Category Breakdown ──
            {"range": "D1:E1", "values": [["Category", "Total Expense (All time)"]]},
            {"range": "D2:D7", "values": [
                ["food"], ["transport"], ["bill"], ["shopping"], ["health"], ["entertainment"]
            ]},
            {"range": "E2:E7", "values": [
                ['=SUMIFS(Expenses!B:B, Expenses!C:C, D2, Expenses!B:B, "<0")'],
                ['=SUMIFS(Expenses!B:B, Expenses!C:C, D3, Expenses!B:B, "<0")'],
                ['=SUMIFS(Expenses!B:B, Expenses!C:C, D4, Expenses!B:B, "<0")'],
                ['=SUMIFS(Expenses!B:B, Expenses!C:C, D5, Expenses!B:B, "<0")'],
                ['=SUMIFS(Expenses!B:B, Expenses!C:C, D6, Expenses!B:B, "<0")'],
                ['=SUMIFS(Expenses!B:B, Expenses!C:C, D7, Expenses!B:B, "<0")'],
            ]},

            # ── Monthly Summary (Thu / Chi / Net) ──
            {"range": "G1:H1", "values": [["Tổng Kết Tháng", ""]]},
            {"range": "G2:H2", "values": [
                ["Tổng Thu Nhập",
                 '=SUMPRODUCT((Expenses!B:B>0)*(Expenses!C:C<>"transfer")*(Expenses!C:C<>"initial_balance")*Expenses!B:B)']
            ]},
            {"range": "G3:H3", "values": [
                ["Tổng Chi Tiêu",
                 '=SUMPRODUCT((Expenses!B:B<0)*(Expenses!C:C<>"transfer")*(Expenses!C:C<>"initial_balance")*Expenses!B:B)']
            ]},
            {"range": "G4:H4", "values": [["Net (Thu - Chi)", "=H2+H3"]]},
        ]
        ws_summary.batch_update(updates, value_input_option="USER_ENTERED")

        # ── Formatting ──
        try:
            total_row = f"A{last_bank_row+1}:B{last_bank_row+1}"
            format_cell_range(ws_summary, "A1:B1", HEADER_FORMAT)
            format_cell_range(ws_summary, total_row, HEADER_FORMAT)
            format_cell_range(ws_summary, "D1:E1", HEADER_FORMAT)
            format_cell_range(ws_summary, "G1:H1", HEADER_FORMAT)
            format_cell_range(ws_summary, "G4:H4", HEADER_FORMAT)

            format_cell_range(ws_summary, f"B2:B{last_bank_row+1}", CURRENCY_FORMAT)
            format_cell_range(ws_summary, "E2:E7", CURRENCY_FORMAT)
            format_cell_range(ws_summary, "H2:H4", CURRENCY_FORMAT)
            print("  ✅ Summary formatting applied.")
        except Exception as e:
            print(f"  ⚠️ Could not apply summary formatting: {e}")

    except Exception as e:
        print(f"ERROR setting up Summary sheet: {e}")

CAP_ASSET_HEADERS = ["Ngày", "Tên tài sản", "Giá gốc", "Giá còn lại", "Số tháng KH", "KH/tháng", "Đã KH", "Trạng thái", "Ghi chú"]
DEPR_HEADERS = ["Ngày", "Tên tài sản", "Kỳ KH", "Giá trị KH", "Giá còn lại"]

def setup_capitalized_assets_tab(sheet):
    print("\n--- Setup Capitalized Assets Tab ---")
    try:
        try:
            ws = sheet.worksheet("Capitalized Assets")
            print("Tab 'Capitalized Assets' already exists.")
        except gspread.exceptions.WorksheetNotFound:
            ws = sheet.add_worksheet(title="Capitalized Assets", rows="200", cols="10")
            ws.append_row(CAP_ASSET_HEADERS, value_input_option="USER_ENTERED", table_range="A1")
            print("Created tab 'Capitalized Assets'.")

        apply_header_formatting(ws, num_cols=9)
        apply_currency_formatting(ws, "C")
        apply_currency_formatting(ws, "D")
        apply_currency_formatting(ws, "F")
        apply_currency_formatting(ws, "G")
    except Exception as e:
        print(f"  ⚠️ Could not setup Capitalized Assets tab: {e}")

def setup_depreciation_log_tab(sheet):
    print("\n--- Setup Depreciation Log Tab ---")
    try:
        try:
            ws = sheet.worksheet("Depreciation Log")
            print("Tab 'Depreciation Log' already exists.")
        except gspread.exceptions.WorksheetNotFound:
            ws = sheet.add_worksheet(title="Depreciation Log", rows="500", cols="6")
            ws.append_row(DEPR_HEADERS, value_input_option="USER_ENTERED", table_range="A1")
            print("Created tab 'Depreciation Log'.")

        apply_header_formatting(ws, num_cols=5)
        apply_currency_formatting(ws, "D")
        apply_currency_formatting(ws, "E")
    except Exception as e:
        print(f"  ⚠️ Could not setup Depreciation Log tab: {e}")


TRANSFER_HEADERS = ["Date", "Amount", "From", "To", "Description"]

def setup_transfers_tab(sheet):
    """Tạo tab 'Transfers' trong Google Sheet để ghi các lệnh chuyển tiền."""
    print("\n--- Setup Transfers Tab ---")
    try:
        try:
            ws = sheet.worksheet("Transfers")
            print("Tab 'Transfers' already exists.")
        except gspread.exceptions.WorksheetNotFound:
            ws = sheet.add_worksheet(title="Transfers", rows="1000", cols="6")
            ws.append_row(TRANSFER_HEADERS, value_input_option="USER_ENTERED", table_range="A1")
            print("Created tab 'Transfers'.")

        apply_header_formatting(ws, num_cols=5)
        apply_currency_formatting(ws, "B")   # Amount column
    except Exception as e:
        print(f"  ⚠️ Could not setup Transfers tab: {e}")

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

        all_values = worksheet.get_all_values()
        headers = ["Date", "Amount", "Category", "Description", "Bank Account"]
        if len(all_values) == 0:
            worksheet.append_row(headers, value_input_option="USER_ENTERED", table_range="A1")
            print("Added headers for Expense.")
        elif len(all_values[0]) == 0 or all_values[0][0] != "Date":
            worksheet.insert_row(headers, index=1, value_input_option="USER_ENTERED")
            print("Inserted missing headers at row 1 for Expense.")
        else:
            print("Expense sheet already has correct headers.")

        apply_header_formatting(worksheet, num_cols=5)
        apply_currency_formatting(worksheet, amount_col_letter="B")

        # Capitalized Assets tab (in My Expenses)
        setup_capitalized_assets_tab(sheet)
        # Depreciation Log tab (in My Expenses)
        setup_depreciation_log_tab(sheet)
        # Transfers tab (in My Expenses) — also auto-created by gsheets_sync.py
        setup_transfers_tab(sheet)

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

        all_values = worksheet.get_all_values()
        headers = ["Ngày", "Loại GD", "Tài sản", "Giá trị", "Phí GD", "Thuế bán", "Dòng tiền ròng", "Ghi chú"]
        if len(all_values) == 0:
            worksheet.append_row(headers, value_input_option="USER_ENTERED", table_range="A1")
            print("Added headers for Portfolio.")
        elif len(all_values[0]) == 0 or all_values[0][0] != "Ngày":
            worksheet.insert_row(headers, index=1, value_input_option="USER_ENTERED")
            print("Inserted missing headers at row 1 for Portfolio.")
        else:
            print("Portfolio sheet already has correct headers.")

        apply_header_formatting(worksheet, num_cols=8)
        apply_currency_formatting(worksheet, amount_col_letter="D")  # "Giá trị"
        apply_currency_formatting(worksheet, amount_col_letter="G")  # "Dòng tiền ròng"

    except gspread.exceptions.SpreadsheetNotFound:
        print(f"ERROR: Cannot find '{PORTFOLIO_SHEET_NAME}'. Please create it and share with the Service Account.")

    # ─── Summary Sheet ────────────────────────────────────────────────────────
    setup_summary_sheet(client)

if __name__ == "__main__":
    setup()
    print("\nHoàn tất kiểm tra!")
