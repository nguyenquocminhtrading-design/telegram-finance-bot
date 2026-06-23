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
