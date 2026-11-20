@echo off
cd /d "%~dp0frontend"
..\.venv\Scripts\python.exe -m uvicorn preview:app --host 127.0.0.1 --port 3000 --reload
pause
