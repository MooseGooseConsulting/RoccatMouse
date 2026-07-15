@echo off
echo ROCCAT Tyon physical wheel trial
echo   1. Leave the wheel and paddle untouched for the first 2 seconds.
echo   2. For the following 10 seconds, move ONLY the physical wheel up and down.
echo   3. Do not touch the X-Celerator paddle during this trial.
echo.
call "%~dp0monitor.bat" --trial wheel --start-delay 5 --baseline-seconds 2 --duration 10
