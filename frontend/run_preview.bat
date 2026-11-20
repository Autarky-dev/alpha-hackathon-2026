@echo off
cd /d "%~dp0"
set PYTHON_EXE=..\.venv\Scripts\python.exe
if not exist "%PYTHON_EXE%" (
  set PYTHON_EXE=.venv\Scripts\python.exe
)
if not exist "%PYTHON_EXE%" (
  py -m venv ..\.venv
  set PYTHON_EXE=..\.venv\Scripts\python.exe
)
"%PYTHON_EXE%" -m pip install -r requirements.txt
"%PYTHON_EXE%" -m uvicorn preview:app --reload --port 3000
pause
