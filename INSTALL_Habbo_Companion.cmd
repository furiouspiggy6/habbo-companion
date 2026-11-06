@echo off
setlocal
cd /d "%~dp0"
echo.
echo ========================================
echo   HABBO COMPANION - ONE-CLICK INSTALL
echo ========================================
echo.
where py >nul 2>&1
if not errorlevel 1 (
  py -3 "%~dp0Install_Habbo_Companion.py"
  goto result
)
where python >nul 2>&1
if not errorlevel 1 (
  python "%~dp0Install_Habbo_Companion.py"
  goto result
)
echo ERROR: Python 3 was not found.
echo Install Python from https://www.python.org/downloads/windows/
echo then run this installer again.
pause
exit /b 1
:result
if errorlevel 1 (
  echo.
  echo Installation failed. Read the error above.
  pause
  exit /b 1
)
echo.
echo Habbo Companion has been installed and launched.
echo You can close this window.
timeout /t 3 /nobreak >nul
exit /b 0
