import pandas as pd
import sys

file_path = "C:/Users/Acer/Desktop/My carrer/Personal financial manage/telegram-finance-bot/My portfolio.xlsm"
try:
    xl = pd.ExcelFile(file_path, engine='xlrd')
    print(f"Sheet names: {xl.sheet_names}")
    for sheet in xl.sheet_names:
        df = pd.read_excel(file_path, sheet_name=sheet, nrows=5, engine='xlrd')
        print(f"\n--- Sheet: {sheet} ---")
        print("Columns:")
        print(list(df.columns))
        print("First 2 rows:")
        print(df.head(2).to_dict(orient='records'))
except Exception as e:
    print(f"Error reading file: {e}")
