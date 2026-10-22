@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo Please run powershell -ExecutionPolicy Bypass -File scripts\setup.ps1 first.
  pause
  exit /b 1
)
start "ImageFlow" ".venv\Scripts\pythonw.exe" "run.py"
