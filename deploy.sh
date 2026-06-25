#!/bin/bash
# Deploy script: pull latest code + verify no crash
# Usage: bash deploy.sh
set -e

cd ~/telegram-finance-bot/telegram-finance-bot

echo "=== 1. Stash local changes ==="
git stash --include-untracked || true

echo "=== 2. Pull latest ==="
git pull

echo "=== 3. Restore local changes ==="
git stash pop || true

echo "=== 4. Verify imports ==="
python3.11 -c "
from config import TELEGRAM_TOKEN, WEBHOOK_URL, GOOGLE_CREDENTIALS_FILE
import os
assert TELEGRAM_TOKEN and ':' in TELEGRAM_TOKEN, 'Missing or invalid token'
assert WEBHOOK_URL.startswith('http'), 'Missing WEBHOOK_URL'
print(f'Token: {TELEGRAM_TOKEN[:10]}...')
print(f'Webhook: {WEBHOOK_URL[:30]}...')
print(f'Credentials exist: {os.path.exists(GOOGLE_CREDENTIALS_FILE)}')
print('OK')
" 2>&1

echo ""
echo "=== 5. Done! ==="
echo "Reload web app: https://www.pythonanywhere.com/user/Quocminh/webapps/"
echo "Or use: touch /var/www/Quocminh_pythonanywhere_com_wsgi.py"
