@echo off
echo ROCCAT Tyon X-Celerator trial
echo   1. Leave the paddle untouched for the first 2 seconds.
echo   2. For the following 10 seconds, press ONLY the paddle up and down.
echo   3. Do not touch the physical scroll wheel during this trial.
echo.
call "%~dp0monitor.bat" --raw --trial paddle --start-delay 5 --baseline-seconds 2 --duration 12
