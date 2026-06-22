import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")
_raw_db = os.getenv("DATABASE_PATH", "")
DATABASE_PATH = _raw_db if _raw_db else os.path.join(os.path.dirname(__file__), "instance", "finance.db")
SECRET_KEY = os.getenv("SECRET_KEY", "default-secret-key-change-me")
_raw_uid = os.getenv("ADMIN_USER_ID", "0")
ADMIN_USER_ID = int(_raw_uid) if _raw_uid else 0

_raw_cred = os.getenv("GOOGLE_CREDENTIALS_FILE", "google_credentials.json")
GOOGLE_CREDENTIALS_FILE = _raw_cred if os.path.isabs(_raw_cred) else os.path.join(os.path.dirname(__file__), _raw_cred)
EXPENSE_SHEET_NAME = os.getenv("EXPENSE_SHEET_NAME", "My Expenses")
PORTFOLIO_SHEET_NAME = os.getenv("PORTFOLIO_SHEET_NAME", "My Portfolio")

os.makedirs(os.path.dirname(DATABASE_PATH), exist_ok=True)
