@echo off
REM Read-only X-Celerator monitor. Uses the project venv when available.
if exist "%~dp0.venv\Scripts\python.exe" (
    "%~dp0.venv\Scripts\python.exe" "%~dp0tyon_monitor.py" %*
) else (
    py -3 "%~dp0tyon_monitor.py" %*
)
