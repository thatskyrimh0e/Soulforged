@echo off
REM Builds a proper Windows installer (SoulforgedSetup.exe) instead of just
REM a folder you copy around -- Start Menu shortcut, optional Desktop
REM shortcut, and a real uninstaller listed in "Apps & features".
REM
REM Needs Inno Setup (free, open-source) installed once:
REM     https://jrsoftware.org/isdl.php
REM This script can't install it for you -- it's a separate Windows
REM installer you run yourself, the same way you'd install any program.
REM
REM Run from inside the Follower Builder folder:   build_installer.bat

cd /d "%~dp0"

echo Building Soulforged.exe first...
call build_exe.bat
if not exist "dist\Soulforged\Soulforged.exe" (
    echo.
    echo build_exe.bat didn't produce dist\Soulforged\Soulforged.exe -- fix that first.
    pause
    exit /b 1
)

set "ISCC="
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
where iscc.exe >nul 2>nul && set "ISCC=iscc.exe"

if not defined ISCC (
    echo.
    echo Inno Setup isn't installed. Get it (free) from:
    echo     https://jrsoftware.org/isdl.php
    echo Then run build_installer.bat again.
    pause
    exit /b 1
)

echo.
echo Compiling the installer...
"%ISCC%" "installer\Soulforged.iss"

if not exist "installer\Output\SoulforgedSetup.exe" (
    echo.
    echo Installer build failed -- scroll up for the error.
    pause
    exit /b 1
)

echo.
echo Done! Your installer is at:
echo     %~dp0installer\Output\SoulforgedSetup.exe
echo.
echo Run that to install Soulforged like any other Windows program --
echo Start Menu shortcut, optional Desktop shortcut, and a proper
echo uninstaller under "Apps & features" when you want it gone.
pause
