#define MyAppName "Achieve3000 Automation"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "Achieve3000 Automation"
#define MyAppExeName "Achieve3000Launcher.exe"

[Setup]
AppId={{B8A8B2F7-2A62-4C6B-8B7E-ACHIEVE3000}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Achieve3000 Automation
DefaultGroupName={#MyAppName}
OutputDir=installer-output
OutputBaseFilename=Achieve3000Setup-v1.0.2
SetupIconFile=achieve3000.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible
DisableProgramGroupPage=yes

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
; The launcher bundle contains the automation EXE and bundled Chromium runtime.
; Do not package .env so credentials are entered by the user in the launcher.
Source: "dist\Achieve3000Launcher\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: ".env"

[Icons]
Name: "{group}\Achieve3000 Automation"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\Achieve3000 Automation"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch Achieve3000 Automation"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}"
