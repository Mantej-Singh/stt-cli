@echo off
REM ====================================================
REM STT-CLI Launcher
REM Speech-to-Text CLI v2.0 - Background Service
REM ====================================================

echo.
echo ====================================================
echo   STT-CLI v2.0 - Speech-to-Text Background Service
echo ====================================================
echo.

REM Step 1: Check if Python is installed
echo [1/3] Checking Python installation...
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed or not in PATH
    echo.
    echo Please install Python from: https://www.python.org/downloads/
    echo Make sure to check "Add Python to PATH" during installation
    echo.
    pause
    exit /b 1
)

python --version
echo [OK] Python found
echo.

REM Step 2: Check if main.pyw exists
echo [2/3] Checking for main.pyw...
if not exist "main.pyw" (
    echo [ERROR] main.pyw not found in current directory
    echo.
    echo Current directory: %CD%
    echo.
    pause
    exit /b 1
)
echo [OK] main.pyw found
echo.

REM Step 3: Launch the application
echo [3/3] Launching STT-CLI...
echo.
echo Starting background service...
echo - System tray icon will appear
echo - Double-tap Left Alt to start/stop recording
echo - Right-click tray icon for settings
echo.

REM Launch Python windowless script (no console window)
start pythonw.exe main.pyw

REM Wait a moment to see if it starts successfully
timeout /t 2 /nobreak >nul

REM Check if process is running
tasklist /FI "IMAGENAME eq pythonw.exe" 2>NUL | find /I /N "pythonw.exe">NUL
if "%ERRORLEVEL%"=="0" (
    echo [OK] STT-CLI started successfully!
    echo.
    echo Look for the system tray icon in the taskbar
    echo (you may need to click the up arrow to expand hidden icons)
) else (
    echo [WARNING] Could not verify if STT-CLI started
    echo.
    echo Check the system tray for the icon
    echo If you see errors, run: python main.pyw
)

echo.
echo ====================================================
echo   To stop: Right-click tray icon and select "Quit"
echo ====================================================
echo.
pause
