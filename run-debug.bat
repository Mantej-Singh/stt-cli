@echo off
REM ====================================================
REM STT-CLI Launcher (DEBUG MODE)
REM Shows console output for troubleshooting
REM ====================================================

echo.
echo ====================================================
echo   STT-CLI v2.0 - DEBUG MODE
echo ====================================================
echo.
echo This will run STT-CLI with visible console output
echo Use this if you need to see errors or debug messages
echo.
echo For normal use, run: run.bat
echo.
pause

REM Launch with console window visible
python main.pyw

echo.
echo ====================================================
echo   STT-CLI has stopped
echo ====================================================
echo.
pause
