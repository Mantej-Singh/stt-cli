@echo off
REM ====================================================
REM STT-CLI Build Script
REM Version: 2.0.0
REM Author: Mantej Singh Dhanjal
REM Description: Hybrid Speech-to-Text with Whisper + Google
REM ====================================================

echo.
echo ====================================================
echo   Building STT-CLI v2.0.0 with Whisper Integration
echo ====================================================
echo.

REM Clean previous build
echo [1/4] Cleaning previous build...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
echo       Done!

REM Build with PyInstaller (includes Whisper dependencies)
echo.
echo [2/4] Building executable with PyInstaller...
echo       Note: This includes faster-whisper, av, numpy, ctranslate2
python -m PyInstaller --onefile --name "speech-to-text-cli" --icon "stt-cli2.ico" --noconsole --add-data "stt-cli2.ico;." --add-data "stt-cli2.png;." --hidden-import=av --hidden-import=faster_whisper --hidden-import=numpy --hidden-import=ctranslate2 --clean main.pyw

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
echo   COPY THE SHA256 HASH ABOVE FOR WINGET MANIFEST!
echo.
echo   Next steps:
echo   1. Test the executable: dist\speech-to-text-cli.exe
echo   2. Test Whisper mode (Engine menu in tray)
echo   3. Test About menu (shows version info)
echo   4. Copy SHA256 hash to winget manifests
echo   5. Push to GitHub
echo   6. Create release v2.0.0
echo   7. Submit to Winget using updated manifests
echo.
echo   Expected size: ~150MB (includes Whisper libraries)
echo.

pause
