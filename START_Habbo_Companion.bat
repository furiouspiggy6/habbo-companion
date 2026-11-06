@echo off
setlocal
cd /d "%~dp0"
where pyw >nul 2>&1
if %ERRORLEVEL% EQU 0 (
  start "" pyw -3 "%~dp0Habbo_Companion.pyw"
  exit /b
)
where pythonw >nul 2>&1
if %ERRORLEVEL% EQU 0 (
  start "" pythonw "%~dp0Habbo_Companion.pyw"
  exit /b
)
echo Python 3 is needed. Install Python for Windows and try again.
pause
