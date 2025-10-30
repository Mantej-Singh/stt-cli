@echo off
REM ====================================================
REM STT-CLI Build Script
REM Version: 1.3.1
REM Author: Mantej Singh Dhanjal
REM ====================================================

echo.
echo ====================================================
echo   Building STT-CLI v1.3.1
echo ====================================================
echo.

REM Clean previous build
echo [1/4] Cleaning previous build...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
echo       Done!

REM Build with PyInstaller
echo.
echo [2/4] Building executable with PyInstaller...
python -m PyInstaller --onefile --name "speech-to-text-cli" --icon "stt-cli2.ico" --noconsole --add-data "stt-cli2.ico;." --add-data "stt-cli2.png;." --clean main.pyw

if errorlevel 1 (
    echo.
    echo [ERROR] Build failed! Check the output above for details.
    pause
    exit /b 1
)

echo       Done!

REM Calculate SHA256 hash
echo.
echo [3/4] Calculating SHA256 hash...
certutil -hashfile "dist\speech-to-text-cli.exe" SHA256
echo.

REM Display file info
echo [4/4] Build information:
dir "dist\speech-to-text-cli.exe" | findstr "speech-to-text-cli.exe"

echo.
echo ====================================================
echo   Build Complete!
echo ====================================================
echo.
echo   Output: dist\speech-to-text-cli.exe
echo.
echo   Next steps:
echo   1. Test the executable: dist\speech-to-text-cli.exe
echo   2. Test version flag: dist\speech-to-text-cli.exe --version
echo   3. Test help flag: dist\speech-to-text-cli.exe --help
echo   4. Push to GitHub
echo   5. Create release v1.3.1
echo.

pause
