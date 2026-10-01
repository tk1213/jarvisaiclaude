@echo off
rem Back up JARVIS now: the code (latest from GitHub), backend\.env, jarvis.db and catalog.db
rem into a folder per day under BACKUP_DIR (default D:\JarvisClaudeBackup). Safe while start.bat runs.
cd /d "%~dp0backend"
if not exist .venv\Scripts\python.exe (
  echo backend\.venv not found. Set it up first - see README.md
  pause
  exit /b 1
)
.venv\Scripts\python.exe -m app.scripts.backup %*
pause
