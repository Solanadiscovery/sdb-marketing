@echo off
rem Carica il progetto su GitHub (repository PUBBLICO vuoto creato da te). Il file .env NON viene caricato (e' escluso).
cd /d "%~dp0"
set /p REPO=Incolla l'indirizzo del repository (es. https://github.com/TUOUTENTE/sdb-marketing.git): 
if not exist .git git init -b main
git add -A
git commit -m "Campagna Instagram" 2>nul
git remote remove origin 2>nul
git remote add origin %REPO%
git push -u origin main
echo.
echo Fatto. Ora in GitHub: Settings - Pages - Source = GitHub Actions, e Settings - Secrets - Actions: IG_USER_ID, IG_ACCESS_TOKEN, MEDIA_BASE_URL.
pause
