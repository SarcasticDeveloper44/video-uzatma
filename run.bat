@echo off
REM Windows launcher — delegates to the cross-platform run.py
where python >nul 2>&1
if errorlevel 1 (
    echo HATA: Python PATH'te bulunamadi. https://www.python.org adresinden kurun.
    exit /b 2
)
python "%~dp0run.py" %*
