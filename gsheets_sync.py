import os
import gspread
from google.oauth2.service_account import Credentials
from datetime import date
from config import GOOGLE_CREDENTIALS_FILE, EXPENSE_SHEET_NAME, PORTFOLIO_SHEET_NAME

# Scopes required for Google Sheets API
SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive'
]

def get_gspread_client():
    if not os.path.exists(GOOGLE_CREDENTIALS_FILE):
        msg = f"Google credentials file '{GOOGLE_CREDENTIALS_FILE}' not found."
        print(f"[GSheets] Warning: {msg}")
        return None, msg
    try:
        credentials = Credentials.from_service_account_file(
            GOOGLE_CREDENTIALS_FILE, scopes=SCOPES
        )
        client = gspread.authorize(credentials)
        return client, None
    except Exception as e:
        msg = f"Lỗi xác thực Google Sheets: {e}"
        print(f"[GSheets] {msg}")
        return None, msg


def sync_expense_to_gsheet(transaction_data):
    """
    Ghi một giao dịch chi tiêu vào Google Sheet.

    transaction_data: dict với các key:
        date, amount, category, description, bank_account

    Trả về:
        (True, None)              — thành công
        (False, error_message)    — thất bại, kèm lý do
    """
    client, auth_err = get_gspread_client()
    if not client:
        return False, auth_err

    try:
        # Mở sheet theo tên
        try:
            sheet = client.open(EXPENSE_SHEET_NAME)
        except gspread.exceptions.SpreadsheetNotFound:
            msg = (
                f"Không tìm thấy Google Sheet tên '{EXPENSE_SHEET_NAME}'. "
                f"Hãy tạo sheet này và share quyền Editor cho service account."
            )
            print(f"[GSheets] {msg}")
            return False, msg

        # Chọn worksheet "Expenses", tạo mới nếu chưa có
        try:
            worksheet = sheet.worksheet("Expenses")
        except gspread.exceptions.WorksheetNotFound:
            worksheet = sheet.sheet1
            worksheet.update_title("Expenses")
            worksheet.append_row(
                ["Date", "Amount", "Category", "Description", "Bank Account"],
                value_input_option="USER_ENTERED",
                table_range="A1"
            )

        row_data = [
            transaction_data.get("date", date.today().isoformat()),
            transaction_data.get("amount", 0),
            transaction_data.get("category", "other"),
            transaction_data.get("description", ""),
            transaction_data.get("bank_account", "")
        ]
        worksheet.append_row(
            row_data,
            value_input_option="USER_ENTERED",
            table_range="A1"
        )
        print(f"[GSheets] Expense synced: {row_data}")
        return True, None

    except Exception as e:
        msg = f"Lỗi ghi vào Google Sheet Expenses: {e}"
        print(f"[GSheets] {msg}")
        return False, msg


def sync_transfer_to_gsheet(transfer_data):
    """
    Ghi 1 dòng chuyển tiền vào tab 'Transfers' trong EXPENSE_SHEET_NAME.
    Tab được tự động tạo nếu chưa tồn tại.

    transfer_data: dict với các key:
        date, amount, from_bank, to_bank, description

    Trả về:
        (True, None)           — thành công
        (False, error_message) — thất bại
    """
    client, auth_err = get_gspread_client()
    if not client:
        return False, auth_err

    try:
        try:
            sheet = client.open(EXPENSE_SHEET_NAME)
        except gspread.exceptions.SpreadsheetNotFound:
            msg = (
                f"Không tìm thấy Google Sheet tên '{EXPENSE_SHEET_NAME}'. "
                f"Hãy tạo sheet này và share quyền Editor cho service account."
            )
            print(f"[GSheets] {msg}")
            return False, msg

        # --- Auto-create tab "Transfers" nếu chưa có ---
        try:
            worksheet = sheet.worksheet("Transfers")
        except gspread.exceptions.WorksheetNotFound:
            worksheet = sheet.add_worksheet(title="Transfers", rows=1000, cols=6)
            worksheet.append_row(
                ["Date", "Amount", "From", "To", "Description"],
                value_input_option="USER_ENTERED",
            )
            print("[GSheets] Tab 'Transfers' đã được tạo tự động.")

        row_data = [
            transfer_data.get("date", date.today().isoformat()),
            transfer_data.get("amount", 0),
            transfer_data.get("from_bank", ""),
            transfer_data.get("to_bank", ""),
            transfer_data.get("description", ""),
        ]
        worksheet.append_row(row_data, value_input_option="USER_ENTERED")
        print(f"[GSheets] Transfer synced: {transfer_data.get('from_bank')} → {transfer_data.get('to_bank')} {transfer_data.get('amount'):,.0f}")
        return True, None

    except Exception as e:
        msg = f"Lỗi ghi vào Google Sheet Transfers: {e}"
        print(f"[GSheets] {msg}")
        return False, msg


def sync_asset_to_gsheet(asset_data, is_buy=True):
    """
    Ghi một giao dịch tài sản vào Google Sheet portfolio.

    asset_data: dict với các key:
        date, name, value, note

    Trả về:
        (True, None)              — thành công
        (False, error_message)    — thất bại, kèm lý do
    """
    client, auth_err = get_gspread_client()
    if not client:
        return False, auth_err

    try:
        try:
            sheet = client.open(PORTFOLIO_SHEET_NAME)
        except gspread.exceptions.SpreadsheetNotFound:
            msg = (
                f"Không tìm thấy Google Sheet tên '{PORTFOLIO_SHEET_NAME}'. "
                f"Hãy tạo sheet này và share quyền Editor cho service account."
            )
            print(f"[GSheets] {msg}")
            return False, msg

        try:
            worksheet = sheet.worksheet("Transaction")
        except gspread.exceptions.WorksheetNotFound:
            worksheet = sheet.sheet1
            worksheet.update_title("Transaction")
            worksheet.append_row(
                ["Ngày", "Loại GD", "Tài sản", "Giá trị", "Phí GD", "Thuế bán", "Dòng tiền ròng", "Ghi chú"],
                value_input_option="USER_ENTERED",
                table_range="A1"
            )

        trans_type = "Mua" if is_buy else "Bán"
        net_flow = -asset_data.get("value", 0) if is_buy else asset_data.get("value", 0)

        row_data = [
            asset_data.get("date", date.today().isoformat()),
            trans_type,
            asset_data.get("name", ""),
            asset_data.get("value", 0),
            0,          # Phí GD
            0,          # Thuế bán
            net_flow,   # Dòng tiền ròng
            asset_data.get("note", "")
        ]
        worksheet.append_row(
            row_data,
            value_input_option="USER_ENTERED",
            table_range="A1"
        )
        print(f"[GSheets] Asset synced: {row_data}")
        return True, None

    except Exception as e:
        msg = f"Lỗi ghi vào Google Sheet Portfolio: {e}"
        print(f"[GSheets] {msg}")
        return False, msg


def sync_capitalized_asset(asset_data):
    """
    Ghi tài sản đã vốn hóa vào tab 'Capitalized Assets' trong My Expenses.

    asset_data: dict với các key:
        date, name, original_value, remaining_value, months, monthly_depr,
        depreciated_sofar, status, note
    """
    client, auth_err = get_gspread_client()
    if not client:
        return False, auth_err
    try:
        sheet = client.open(EXPENSE_SHEET_NAME)
        try:
            worksheet = sheet.worksheet("Capitalized Assets")
        except gspread.exceptions.WorksheetNotFound:
            return False, "Tab 'Capitalized Assets' not found. Run setup_gsheets.py first."

        row_data = [
            asset_data.get("date", date.today().isoformat()),
            asset_data.get("name", ""),
            asset_data.get("original_value", 0),
            asset_data.get("remaining_value", 0),
            asset_data.get("months", 0),
            asset_data.get("monthly_depr", 0),
            asset_data.get("depreciated_sofar", 0),
            asset_data.get("status", "Active"),
            asset_data.get("note", ""),
        ]
        worksheet.append_row(row_data, value_input_option="USER_ENTERED", table_range="A1")
        print(f"[GSheets] Capitalized asset synced: {asset_data.get('name')}")
        return True, None
    except Exception as e:
        msg = f"Lỗi ghi Capitalized Assets: {e}"
        print(f"[GSheets] {msg}")
        return False, msg


def sync_depreciation_log(depr_data):
    """
    Ghi lịch sử khấu hao vào tab 'Depreciation Log' trong My Expenses.

    depr_data: dict với các key:
        date, asset_name, period, amount, remaining_value
    """
    client, auth_err = get_gspread_client()
    if not client:
        return False, auth_err
    try:
        sheet = client.open(EXPENSE_SHEET_NAME)
        try:
            worksheet = sheet.worksheet("Depreciation Log")
        except gspread.exceptions.WorksheetNotFound:
            return False, "Tab 'Depreciation Log' not found. Run setup_gsheets.py first."

        row_data = [
            depr_data.get("date", date.today().isoformat()),
            depr_data.get("asset_name", ""),
            depr_data.get("period", ""),
            depr_data.get("amount", 0),
            depr_data.get("remaining_value", 0),
        ]
        worksheet.append_row(row_data, value_input_option="USER_ENTERED", table_range="A1")
        print(f"[GSheets] Depreciation log synced: {depr_data.get('asset_name')} - {depr_data.get('period')}")
        return True, None
    except Exception as e:
        msg = f"Lỗi ghi Depreciation Log: {e}"
        print(f"[GSheets] {msg}")
        return False, msg


def update_capitalized_asset_value(asset_name, new_remaining, new_depreciated_sofar, new_status="Active"):
    """Update giá trị còn lại + đã KH + trạng thái trong Capitalized Assets tab."""
    client, auth_err = get_gspread_client()
    if not client:
        return False, auth_err
    try:
        sheet = client.open(EXPENSE_SHEET_NAME)
        worksheet = sheet.worksheet("Capitalized Assets")
        all_rows = worksheet.get_all_values()
        if len(all_rows) < 2:
            return False, "No data rows"
        headers = all_rows[0]
        name_col = headers.index("Tên tài sản")
        remaining_col = headers.index("Giá còn lại") + 1
        depr_col = headers.index("Đã KH") + 1
        status_col = headers.index("Trạng thái") + 1

        for i, row in enumerate(all_rows[1:], start=2):
            if row[name_col].strip() == asset_name.strip():
                worksheet.update_cell(i, remaining_col, new_remaining)
                worksheet.update_cell(i, depr_col, new_depreciated_sofar)
                worksheet.update_cell(i, status_col, new_status)
                print(f"[GSheets] Updated capitalized asset: {asset_name}")
                return True, None
        return False, f"Asset '{asset_name}' not found in Capitalized Assets tab"
    except Exception as e:
        msg = f"Lỗi update Capitalized Assets: {e}"
        print(f"[GSheets] {msg}")
        return False, msg
