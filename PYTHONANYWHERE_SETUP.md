# Hướng dẫn deploy lên PythonAnywhere

## ⚠️ QUAN TRỌNG: PythonAnywhere dùng Python 3.11

**PythonAnywhere free tier chỉ hỗ trợ Python 3.11 (tính đến 2026).**
**KHÔNG dùng lệnh `py` hay `pip` mặc định — phải dùng `python3.11` và `pip3.11`.**

---

## 1. Tạo Web App

1. Vào **Web tab** → **Add a new web app**
2. Chọn **Manual configuration**
3. Chọn **Python 3.11**
4. Ghi nhớ đường dẫn: `/home/{username}/telegram-finance-bot`

## 2. Clone code & cài đặt

Mở **Bash console** (trong PythonAnywhere Dashboard → **Consoles tab** → **Bash**):

```bash
# Clone repo
git clone https://github.com/nguyenquocminhtrading-design/telegram-finance-bot.git
cd telegram-finance-bot

# LUÔN dùng pip3.11, KHÔNG dùng pip
pip3.11 install --user -r requirements.txt

# Tạo file .env từ mẫu
cp .env.example .env
nano .env   # Điền token thật vào
```

## 3. Cấu hình WSGI file

Vào **Web tab** → **Code** section → click đường dẫn **WSGI configuration file**.

Xoá hết nội dung cũ, paste:

```python
import sys
path = '/home/{TEN_USER}/telegram-finance-bot'
if path not in sys.path:
    sys.path.append(path)

import os
os.environ['BOT_MODE'] = 'webhook'

from app import app as application
```

Thay `{TEN_USER}` bằng username PythonAnywhere của bạn.

## 4. Chạy setup Google Sheets (1 lần)

```bash
cd ~/telegram-finance-bot
python3.11 setup_gsheets.py
```

## 5. Cấu hình Webhook Telegram

Vào **Bash console**:

```bash
cd ~/telegram-finance-bot
python3.11 -c "
from config import TELEGRAM_TOKEN, WEBHOOK_URL
import requests
url = f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/setWebhook?url={WEBHOOK_URL}/webhook/{TELEGRAM_TOKEN}'
print(requests.get(url).json())
"
```

## 6. Reload web app

Vào **Web tab** → nhấn **Reload**.

## 7. Giữ web app luôn thức

PythonAnywhere free tier tắt web sau 3 tháng không hoạt động.

**Cách 1:** Dùng [cron-job.org](https://cron-job.org) — tạo task ping `https://{username}.pythonanywhere.com/ping` mỗi 5 phút.

**Cách 2:** Dùng PythonAnywhere Scheduled Task:
- **Schedule tab** → **Create scheduled task**
- `python3.11 -c "import requests; requests.get('https://{username}.pythonanywhere.com/ping')"`
- Chạy mỗi ngày hoặc mỗi giờ

---

## Các lệnh thường dùng

```bash
# Cập nhật code mới
cd ~/telegram-finance-bot
git pull
pip3.11 install --user -r requirements.txt   # Luôn dùng pip3.11
python3.11 setup_gsheets.py                  # Luôn dùng python3.11

# Reload web (vào Web tab → Reload)

# Kiểm tra database
python3.11 -c "from database import init_db, get_db; init_db(); conn = get_db(); print('OK:', conn.execute('SELECT COUNT(*) FROM transactions').fetchone()[0])"

# Đồng bộ dữ liệu từ Google Sheets
python3.11 -c "from gsheets_reader import sync_all_from_sheets; r = sync_all_from_sheets(); print(r)"
```

---

## Debug nếu gặp lỗi

| Lỗi | Nguyên nhân | Fix |
|-----|-------------|-----|
| `ModuleNotFoundError` | Dùng sai `pip` (dùng pip2 hoặc pip mặc định) | Dùng `pip3.11 install --user -r requirements.txt` |
| `python: command not found` | Không dùng đúng phiên bản | Dùng `python3.11` thay vì `python` |
| Web không load / 502 | WSGI file sai | Kiểm tra path trong WSGI file |
| Bot không trả lời | Webhook chưa set hoặc sai URL | Chạy lại lệnh set webhook ở bước 5 |
