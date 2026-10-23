@echo off
title DJ Downloader Builder • GilOS
color 0A

echo ============================================
echo     DJ Downloader - Auto Build Script
echo     Made for GilOS
echo ============================================
echo.

REM ---- Work from the folder this script is in ----
cd /d "%~dp0"
set "TMPBUILD=%TEMP%\dj_downloader_build"

echo [1/4] Installing / updating required Python modules...
python -m pip install --upgrade "yt-dlp[default]" customtkinter requests pillow pyinstaller

echo.
echo [2/4] Building EXE from dj_downloader_V1.py (this may take a minute)...
REM Temporary build files go to %TEMP%; the EXE is written next to this script
python -m PyInstaller --noconfirm --onefile --noconsole --hidden-import=requests --collect-all yt_dlp_ejs --icon "%~dp0dj_downloader.ico" --name dj_downloader --distpath "%~dp0." --workpath "%TMPBUILD%" --specpath "%TMPBUILD%" dj_downloader_V1.py

echo.
echo [3/4] Checking build result...
if not exist "dj_downloader.exe" (
    echo ERROR: Build failed. EXE not found.
    pause
    exit /b
)
rmdir /s /q "%TMPBUILD%" 2>nul

echo.
echo [4/4] Done!
echo Your EXE is ready: %~dp0dj_downloader.exe
echo.

pause
exit
