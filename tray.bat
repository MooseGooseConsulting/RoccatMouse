@echo off
REM On-demand continuous observation. Pass --start to begin this session immediately.
if exist "%~dp0.venv\Scripts\pythonw.exe" (
    start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0tray.py"
) else (
    py -3 "%~dp0tray.py"
)
