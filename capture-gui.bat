@echo off
REM Compact paddle/wheel diagnostic window. Uses the project venv when available.
if exist "%~dp0.venv\Scripts\pythonw.exe" (
    start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0tyon_capture_gui.py" %*
) else (
    py -3 "%~dp0tyon_capture_gui.py" %*
)
