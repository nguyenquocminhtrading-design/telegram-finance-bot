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
        print(f"Warning: Google credentials file '{GOOGLE_CREDENTIALS_FILE}' not found.")
        return None
    try:
        credentials = Credentials.from_service_account_file(
            GOOGLE_CREDENTIALS_FILE, scopes=SCOPES
        )
        client = gspread.authorize(credentials)
        return client
    except Exception as e:
        print(f"Error authenticating with Google Sheets: {e}")
        return None

def sync_expense_to_gsheet(transaction_data):
    """
    transaction_data: dict with keys:
    date, amount, category, description, bank_account
    """
    client = get_gspread_client()
    if not client:
        return

    try:
        # Try to open the sheet by name
        try:
            sheet = client.open(EXPENSE_SHEET_NAME)
        except gspread.exceptions.SpreadsheetNotFound:
            print(f"Spreadsheet '{EXPENSE_SHEET_NAME}' not found. Please create it and share with the service account.")
            return

        # Select the first worksheet or a specific one named 'Expenses'
        try:
            worksheet = sheet.worksheet("Expenses")
        except gspread.exceptions.WorksheetNotFound:
            worksheet = sheet.sheet1
            worksheet.update_title("Expenses")
            # Add header if new
            if len(worksheet.get_all_values()) == 0:
                worksheet.append_row(["Date", "Amount", "Category", "Description", "Bank Account"])

        row_data = [
            transaction_data.get("date", date.today().isoformat()),
            transaction_data.get("amount", 0),
            transaction_data.get("category", "other"),
            transaction_data.get("description", ""),
            transaction_data.get("bank_account", "")
        ]
        worksheet.append_row(row_data)

    except Exception as e:
        print(f"Error syncing to expense Google Sheet: {e}")


def sync_asset_to_gsheet(asset_data, is_buy=True):
    """
    asset_data: dict with keys:
    date, name, value, note
    """
    client = get_gspread_client()
    if not client:
        return

    try:
        try:
            sheet = client.open(PORTFOLIO_SHEET_NAME)
        except gspread.exceptions.SpreadsheetNotFound:
            print(f"Spreadsheet '{PORTFOLIO_SHEET_NAME}' not found. Please create it and share with the service account.")
            return

        try:
            worksheet = sheet.worksheet("Transaction")
        except gspread.exceptions.WorksheetNotFound:
            worksheet = sheet.sheet1
            worksheet.update_title("Transaction")
            if len(worksheet.get_all_values()) == 0:
                worksheet.append_row(["Ngày", "Loại GD", "Tài sản", "Giá trị", "Phí GD", "Thuế bán", "Dòng tiền ròng", "Ghi chú"])

        trans_type = "Mua" if is_buy else "Bán"
        net_flow = -asset_data.get("value", 0) if is_buy else asset_data.get("value", 0)

        row_data = [
            asset_data.get("date", date.today().isoformat()),
            trans_type,
            asset_data.get("name", ""),
            asset_data.get("value", 0),
            0, # Phí GD
            0, # Thuế bán
            net_flow, # Dòng tiền ròng
            asset_data.get("note", "")
        ]
        
        worksheet.append_row(row_data)

    except Exception as e:
        print(f"Error syncing to portfolio Google Sheet: {e}")
