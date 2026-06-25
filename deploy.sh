#!/bin/bash
# Deploy script: pull latest code + verify no crash
cd ~/telegram-finance-bot/telegram-finance-bot

echo "=== 1. Stash local changes ==="
git stash

echo "=== 2. Pull latest ==="
git pull

echo "=== 3. Restore local changes ==="
git stash pop

echo "=== 4. Verify imports ==="
python3.11 -c "from config import TELEGRAM_TOKEN, GOOGLE_CREDENTIALS_FILE; import os; assert TELEGRAM_TOKEN, 'Missing token'; assert os.path.exists(GOOGLE_CREDENTIALS_FILE), 'Missing credentials'; print('OK')" 2>&1

echo "=== 5. Done! Reload web app on PythonAnywhere ==="
