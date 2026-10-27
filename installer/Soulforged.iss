; Inno Setup script for Soulforged -- packages the PyInstaller --onedir
; build (dist\Soulforged\) into a normal Windows installer: Start Menu
; shortcut, optional Desktop shortcut, a proper uninstaller listed in
; "Apps & features", the works. Compiled by build_installer.bat; you
; shouldn't need to run ISCC.exe by hand.
;
; AppId is a fixed GUID so re-running the installer (for an update) upgrades
; the existing install in place instead of creating a second copy.

#define MyAppName "Soulforged"
#define MyAppVersion "1.0.0"
#define MyAppExeName "Soulforged.exe"

[Setup]
AppId={{7B8F2A1E-4C3D-4E9A-9F1B-2D6E8A5C7F10}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppName}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=Output
OutputBaseFilename=SoulforgedSetup
SetupIconFile=..\assets\app_icon.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Files]
Source: "..\dist\Soulforged\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName} now"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}"
