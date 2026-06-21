@echo off
chcp 65001 >nul
echo ========================================
echo   DAY CODE LEN GITHUB - SEE Bot
echo ========================================
echo.
echo Repository: github.com/nguyenquocminhtrading-design/SEE-code
echo.

if not exist .git (
    git init
    git branch -M main
    git remote add origin https://github.com/nguyenquocminhtrading-design/SEE-code.git
)

echo [1/4] Copy .env -^> .env.example (neu chua co)
if not exist .env.example copy .env .env.example

echo [2/4] Them file vao staging...
git add -A

echo [3/4] Commit...
git commit -m "SEE Bot - Update %date%"

echo [4/4] Push...
git push -u origin main

echo.
echo Done! Kiem tra: https://github.com/nguyenquocminhtrading-design/SEE-code
pause
