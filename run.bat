@echo off
REM Windows launcher — double-clickable from Explorer or invoked from cmd/PowerShell.
REM Delegates to run.py which handles every bootstrap concern (Python version,
REM venv creation, OneDrive/antivirus fallback, ffmpeg auto-download).
setlocal

REM Prefer the Python launcher (py.exe). It's installed by python.org's
REM installer by default, picks the correct interpreter version, and avoids
REM the Microsoft Store stub which `where python` would happily resolve to
REM on fresh Windows installs.
where py >nul 2>&1
if not errorlevel 1 (
    py "%~dp0run.py" %*
    set RC=%ERRORLEVEL%
    goto :done
)

REM Fallback: plain `python` (older Pythons / non-standard installs).
where python >nul 2>&1
if errorlevel 1 (
    echo HATA: Python PATH'te bulunamadi.
    echo.
    echo Kurulum:  winget install Python.Python.3
    echo veya:     https://www.python.org/downloads/windows/
    pause
    exit /b 2
)

python "%~dp0run.py" %*
set RC=%ERRORLEVEL%

:done
if not "%RC%"=="0" (
    echo.
    echo Cikis kodu: %RC%
    pause
)
exit /b %RC%
