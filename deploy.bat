@echo off
echo ==============================================
echo  TELEGRAM FINANCE BOT - AUTO DEPLOY SCRIPT
echo ==============================================

echo [1/3] Adding files to Git...
git add .

set /p commitMsg="Enter commit message (or press Enter for default 'Auto deploy update'): "
if "%commitMsg%"=="" set commitMsg=Auto deploy update

echo [2/3] Committing changes...
git commit -m "%commitMsg%"

echo [3/3] Pushing to GitHub...
git push origin main

echo ==============================================
echo Deploy script finished!
echo Now, to update PythonAnywhere:
echo 1. Go to your PythonAnywhere bash console.
echo 2. Run: cd telegram-finance-bot ^&^& git pull
echo 3. Go to Web tab and click "Reload".
echo ==============================================
pause
