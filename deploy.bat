@echo off
echo ==============================================
echo  TELEGRAM FINANCE BOT - AUTO DEPLOY SCRIPT
echo ==============================================

if exist .git goto deploy

echo [0/4] Khoi tao Git repository lan dau...
git init
git branch -M main
git add .
git commit -m "Initial commit"

echo [1/4] Dang tao GitHub repository tu dong qua GitHub CLI...
for %%I in (.) do set RepoName=%%~nxI
echo Ten repository se tao: %RepoName%

gh repo create %RepoName% --private --source=. --remote=origin --push

echo ==============================================
echo [Thanh cong] Da khoi tao va day code len GitHub repository: %RepoName%!
goto finish

:deploy
echo [1/3] Adding files to Git...
git add .

set /p commitMsg="Enter commit message (or press Enter for default 'Auto deploy update'): "
if "%commitMsg%"=="" set commitMsg=Auto deploy update

echo [2/3] Committing changes...
git commit -m "%commitMsg%"

echo [3/3] Pushing to GitHub...
git push origin main

:finish
echo ==============================================
echo Deploy script finished!
echo Now, to update PythonAnywhere:
echo 1. Go to your PythonAnywhere bash console.
echo 2. Run: cd telegram-finance-bot ^&^& git pull
echo 3. Go to Web tab and click "Reload".
echo ==============================================
pause
