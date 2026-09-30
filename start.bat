@echo off
rem Start the JARVIS server on Windows: double-click this file.
rem Uses backend\.venv so another Python or uvicorn on PATH is never picked up.
cd /d "%~dp0backend"
if not exist .venv\Scripts\python.exe (
  echo backend\.venv not found. Set it up first - see README.md
  pause
  exit /b 1
)
rem Port 8765: the Cloudflare tunnel (jarvis.jarvisthai.com) forwards the LINE webhook here.
.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8765
pause
