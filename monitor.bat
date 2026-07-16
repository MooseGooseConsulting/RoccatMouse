@echo off
REM Normal capture is read-only; --raw sends bounded start/end only. Uses the project venv.
if exist "%~dp0.venv\Scripts\python.exe" (
    "%~dp0.venv\Scripts\python.exe" "%~dp0tyon_monitor.py" %*
) else (
    py -3 "%~dp0tyon_monitor.py" %*
)
