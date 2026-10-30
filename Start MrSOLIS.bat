@echo off
REM Starts the MrSOLIS 3 desktop app. Double-click this file, or run it from any terminal.
REM (start.bat is the old browser version of Lunar - use this one.)
cd /d "%~dp0desktop"
if not exist "node_modules\electron\dist\electron.exe" (
    echo MrSOLIS can't start: desktop\node_modules is missing.
    echo Open a terminal in the desktop folder and run:  npm install
    pause
    exit /b 1
)
start "" "node_modules\electron\dist\electron.exe" .
