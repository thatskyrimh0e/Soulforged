@echo off
REM Builds a standalone Soulforged.exe so you don't have to run
REM "python main.py" every time -- just double-click the exe (or the
REM "Soulforged" shortcut this script drops on your Desktop).
REM
REM Run this once from inside the Follower Builder folder:  (project folder name unchanged)
REM     build_exe.bat
REM Re-run it any time after you (or I) change the app's code.

cd /d "%~dp0"

echo Installing/updating dependencies...
python -m pip install -r requirements.txt
python -m pip install pyinstaller

echo.
echo Building Soulforged.exe (this can take a minute or two)...
python -m PyInstaller --name "Soulforged" --windowed --onedir ^
    --icon "assets\app_icon.ico" ^
    --add-data "ui\theme.qss;ui" ^
    --add-data "assets;assets" ^
    --add-data "config;config" ^
    --noconfirm ^
    main.py

if not exist "dist\Soulforged\Soulforged.exe" (
    echo.
    echo Build failed -- scroll up for the error. Nothing else was changed.
    pause
    exit /b 1
)

echo.
echo Creating a Desktop shortcut...
powershell -NoProfile -Command ^
  "$ws = New-Object -ComObject WScript.Shell; $desktop = [Environment]::GetFolderPath('Desktop'); $s = $ws.CreateShortcut((Join-Path $desktop 'Soulforged.lnk')); $s.TargetPath = '%~dp0dist\Soulforged\Soulforged.exe'; $s.WorkingDirectory = '%~dp0dist\Soulforged'; $s.IconLocation = '%~dp0dist\Soulforged\Soulforged.exe,0'; $s.Save()"

echo.
echo Done! Launch it from the "Soulforged" shortcut now on your Desktop,
echo or directly at: %~dp0dist\Soulforged\Soulforged.exe
echo.
echo Your settings (config\settings.json) were copied into that build folder,
echo so it already points at your MO2 and game install paths.
pause
