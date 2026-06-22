import os
import gspread
from google.oauth2.service_account import Credentials
from config import GOOGLE_CREDENTIALS_FILE, EXPENSE_SHEET_NAME, PORTFOLIO_SHEET_NAME

SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive'
]

def setup():
    print("Connecting to Google Cloud...")
    credentials = Credentials.from_service_account_file(
        GOOGLE_CREDENTIALS_FILE, scopes=SCOPES
    )
    client = gspread.authorize(credentials)
    
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
            worksheet.append_row(["Date", "Amount", "Category", "Description", "Bank Account"])
            print("Added headers for Expense.")
        else:
            print("Expense sheet already has data, skipping headers.")
    except gspread.exceptions.SpreadsheetNotFound:
        print(f"ERROR: Cannot find '{EXPENSE_SHEET_NAME}'. Please make sure you created it and shared with the Service Account.")

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
            worksheet.append_row(["Ngày", "Loại GD", "Tài sản", "Giá trị", "Phí GD", "Thuế bán", "Dòng tiền ròng", "Ghi chú"])
            print("Added headers for Portfolio.")
        else:
            print("Portfolio sheet already has data, skipping headers.")
    except gspread.exceptions.SpreadsheetNotFound:
        print(f"ERROR: Cannot find '{PORTFOLIO_SHEET_NAME}'. Please make sure you created it and shared with the Service Account.")

if __name__ == "__main__":
    setup()
    print("\nHoàn tất kiểm tra!")
