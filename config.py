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

os.makedirs(os.path.dirname(DATABASE_PATH), exist_ok=True)
