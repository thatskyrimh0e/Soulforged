@echo off
REM Builds SoulforgedSetup.msi -- a real MSI installer, via the WiX
REM Toolset (v5), as opposed to build_installer.bat's Inno Setup .exe.
REM
REM One-time setup before this will work:
REM   1. Install the .NET SDK (needed to run the "wix" CLI):
REM      https://dotnet.microsoft.com/download
REM   2. Open a new Command Prompt (so PATH picks up dotnet) and run:
REM      dotnet tool install --global wix
REM
REM After that, just run:  build_msi.bat
REM Re-run it any time after you (or I) change the app's code.

cd /d "%~dp0"

call build_exe.bat
if errorlevel 1 (
    echo.
    echo build_exe.bat failed -- see above. Aborting before the MSI step.
    pause
    exit /b 1
)

where wix >nul 2>nul
if errorlevel 1 (
    echo.
    echo Can't find the "wix" command.
    echo Install the .NET SDK from https://dotnet.microsoft.com/download ,
    echo then open a NEW Command Prompt and run:
    echo     dotnet tool install --global wix
    pause
    exit /b 1
)

wix extension list -g | findstr /i "WixToolset.UI.wixext" >nul 2>nul
if errorlevel 1 (
    echo Installing the WiX UI extension (one-time)...
    wix extension add -g WixToolset.UI.wixext
)

if not exist "installer\Output" mkdir "installer\Output"

echo.
echo Building SoulforgedSetup.msi...
wix build "installer\Soulforged.wxs" ^
    -d SourceDir="dist\Soulforged" ^
    -ext WixToolset.UI.wixext ^
    -arch x64 ^
    -o "installer\Output\SoulforgedSetup.msi"

if not exist "installer\Output\SoulforgedSetup.msi" (
    echo.
    echo MSI build failed -- scroll up for the error.
    pause
    exit /b 1
)

echo.
echo Done: installer\Output\SoulforgedSetup.msi
pause
