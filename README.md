# Personal Finance Manager

A comprehensive personal finance management system with Telegram Bot + Web Dashboard + Asset Capitalization features.

## Features

- **Telegram Bot**: Record income/expense via chat messages
- **Web Dashboard**: Visualize finances with charts and tables
- **Asset Capitalization**: Convert large purchases into depreciable assets
- **Automatic Depreciation**: Monthly depreciation tracking
- **Cash Flow Analysis**: Income/expense trends over time
- **Daily Backups**: Automatic database backup
- **PythonAnywhere Ready**: Deployable on free tier with keep-alive

## Quick Start

### 1. Create a Telegram Bot

1. Open Telegram and search for [@BotFather](https://t.me/BotFather)
2. Send `/newbot` and follow instructions
3. Copy the bot token (e.g., `123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11`)

### 2. Local Setup

```bash
# Clone or copy the project
cd telegram-finance-bot

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
# or: venv\Scripts\activate  # Windows

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your TELEGRAM_TOKEN

# Run the app
python app.py
```

### 3. Using the Bot

Open your bot on Telegram and send:

- `+500 salary March` - Record income
- `-200 lunch` - Record expense
- `-10000 laptop` - Record expense, bot will ask if you want to capitalize it as an asset

Commands:
- `/start` - Welcome message
- `/balance` - Current balance
- `/report` - Monthly summary
- `/asset` - Asset list
- `/web` - Dashboard link

### 4. Web Dashboard

Open `http://localhost:5000/dashboard` in your browser.

## Deploy on PythonAnywhere

### Step 1: Create Web App

1. Log in to [PythonAnywhere](https://www.pythonanywhere.com)
2. Go to **Web** tab → **Add a new web app**
3. Choose **Manual configuration** → **Python 3.10+**
4. Set path to your project directory

### Step 2: Upload Code

```bash
# Via Git
git clone your-repo-url

# Or upload files manually through PythonAnywhere Files tab
```

### Step 3: Install Dependencies

Open a **Bash console** on PythonAnywhere:

```bash
cd telegram-finance-bot
pip install --user -r requirements.txt
```

### Step 4: Configure

Create `.env` in the project root:

```
TELEGRAM_TOKEN=your_actual_token
WEBHOOK_URL=https://yourusername.pythonanywhere.com/webhook
DATABASE_PATH=/home/yourusername/telegram-finance-bot/instance/finance.db
SECRET_KEY=generate_a_random_string
```

### Step 5: WSGI Configuration

In the **Web** tab, edit the WSGI file:

```python
import sys
path = '/home/yourusername/telegram-finance-bot'
if path not in sys.path:
    sys.path.append(path)
from app import app as application
```

### Step 6: Set Webhook

Run this in a PythonAnywhere console:

```python
import requests
token = "YOUR_TELEGRAM_TOKEN"
webhook_url = "https://yourusername.pythonanywhere.com/webhook"
requests.get(f"https://api.telegram.org/bot{token}/setWebhook?url={webhook_url}")
```

### Step 7: Keep-Alive (Prevent Sleep)

Option A - **PythonAnywhere Scheduled Task**:
1. Go to **Tasks** tab
2. Create a new hourly task
3. Command: `curl https://yourusername.pythonanywhere.com/ping`

Option B - **cron-job.org** (free):
1. Sign up at cron-job.org
2. Create a job that pings `https://yourusername.pythonanywhere.com/ping` every 5 minutes

## Project Structure

```
telegram-finance-bot/
├── app.py              # Flask application & routes
├── bot.py              # Telegram bot handlers
├── database.py         # SQLite models & CRUD
├── asset_manager.py    # Asset capitalization logic
├── finance_logic.py    # Balance & report calculations
├── scheduler.py        # Scheduled tasks (depreciation, backup)
├── config.py           # Environment configuration
├── requirements.txt    # Python dependencies
├── .env.example        # Environment template
├── static/
│   ├── css/style.css   # Stylesheet
│   └── js/chart.js     # Chart drawing (Canvas API)
├── templates/
│   ├── dashboard.html  # Overview page
│   ├── transactions.html # Transaction list
│   ├── assets.html     # Asset management
│   ├── reports.html    # Charts & reports
│   └── settings.html   # Settings page
└── instance/
    └── finance.db      # SQLite database (auto-created)
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/dashboard` | Web dashboard |
| GET | `/transactions` | Transaction list |
| GET | `/assets` | Asset list |
| GET | `/reports` | Charts & reports |
| GET | `/api/transactions` | List transactions (JSON) |
| POST | `/api/transactions` | Add transaction |
| PUT | `/api/transactions/<id>` | Update transaction |
| DELETE | `/api/transactions/<id>` | Delete transaction |
| GET | `/api/summary` | Financial summary (JSON) |
| GET | `/api/assets` | Asset summary (JSON) |
| GET | `/api/categories` | Category list (JSON) |
| POST | `/api/run-depreciation` | Run depreciation now |
| GET | `/ping` | Health check / keep-alive |
| POST | `/webhook/<token>` | Telegram webhook |

## License

MIT
