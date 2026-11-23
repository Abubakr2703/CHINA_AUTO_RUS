@echo off
rem Read-only collector: saves device listings to dump\<timestamp>\.
rem Nothing is written to the car and nothing is installed.
setlocal
chcp 65001 >nul
cd /d "%~dp0.."

where adb >nul 2>nul
if errorlevel 1 (
    echo [CHINA AUTO RUS] adb not found in PATH.
    echo Install Android platform-tools and add the folder to PATH:
    echo     https://developer.android.com/tools/releases/platform-tools
    echo Then run this script again.
    pause
    exit /b 1
)

for /f "delims=" %%I in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd-HHmmss"') do set "STAMP=%%I"
if not defined STAMP set "STAMP=manual"
set "OUT=dump\%STAMP%"
mkdir "%OUT%" 2>nul

adb devices > "%OUT%\devices.txt" 2>&1
findstr /r /c:"device$" "%OUT%\devices.txt" >nul
if errorlevel 1 (
    echo [CHINA AUTO RUS] No authorized device found.
    echo Check the cable, USB debugging and the prompt on the car screen.
    type "%OUT%\devices.txt"
    pause
    exit /b 1
)

echo Collecting read-only information...
adb shell getprop > "%OUT%\getprop.txt" 2>&1
adb shell pm list packages > "%OUT%\packages.txt" 2>&1
adb shell ls -l / > "%OUT%\listing_root.txt" 2>&1
adb shell ls -l /system > "%OUT%\listing_system.txt" 2>&1
adb shell ls -l /system/app > "%OUT%\listing_system_app.txt" 2>&1
adb shell ls -l /system/etc > "%OUT%\listing_system_etc.txt" 2>&1
adb shell ls -l /vendor > "%OUT%\listing_vendor.txt" 2>&1
adb shell ls -l /data/app > "%OUT%\listing_data_app.txt" 2>&1

echo.
echo Done. Files are in %OUT%
dir /b "%OUT%"
echo.
echo Send getprop.txt, packages.txt and listing_*.txt to the project.
pause
