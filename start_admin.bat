@echo off
rem ============================================================
rem  Administrator-mode launcher for StellaSoraGachaTool
rem  A UAC prompt will appear - click "Yes" to run as admin.
rem ============================================================
set "PY=C:\Users\sfjdk\AppData\Local\Programs\Python\Python312\python.exe"
set "ROOT=%~dp0"

if not exist "%PY%" (
  echo Python 3.12 + PySide6 was NOT found at:
  echo   %PY%
  echo Please install it, or edit this batch file's PY variable.
  pause
  exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%PY%' -ArgumentList '-m','stellasora_toolkit.gui','--output',(Join-Path '%ROOT%' 'exports') -WorkingDirectory '%ROOT%' -Verb RunAs"

echo Launched as administrator. You may close this window.
