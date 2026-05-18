@echo off
REM Windows launcher — double-clickable from Explorer or invoked from cmd/PowerShell.
setlocal

where python >nul 2>&1
if errorlevel 1 (
    echo HATA: Python PATH'te bulunamadi.
    echo Kurulum: winget install Python.Python.3   veya   https://www.python.org
    pause
    exit /b 2
)

python "%~dp0run.py" %*
set RC=%ERRORLEVEL%
if not "%RC%"=="0" (
    echo.
    echo Cikis kodu: %RC%
    pause
)
exit /b %RC%
