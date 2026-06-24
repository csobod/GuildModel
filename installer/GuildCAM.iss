; Inno Setup script for GuildCAM — per-user (no-admin) Windows installer.
;
; Packages the PyInstaller one-folder build (dist\GuildCAM) into a single
; GuildCAM-<version>-setup.exe that installs to %LocalAppData%\Programs\GuildCAM,
; adds Start Menu (and optional Desktop) shortcuts, registers the .gcam project
; association under HKCU, and provides an Add/Remove Programs uninstaller.
;
; Compile manually:
;   "%LocalAppData%\Programs\Inno Setup 6\ISCC.exe" installer\GuildCAM.iss
; Or, with overrides from the release script:
;   ISCC.exe /DMyAppVersion=1.0.0-rc1 /DMyAppVersionNumeric=1.0.0.0 installer\GuildCAM.iss
;
; The release script (scripts\build_release.ps1) passes the version defines and
; builds dist\GuildCAM first. Defaults below let the script be compiled by hand.

#ifndef MyAppVersion
  #define MyAppVersion "1.0.0-rc1"
#endif
#ifndef MyAppVersionNumeric
  #define MyAppVersionNumeric "1.0.0.0"
#endif
#ifndef MySourceDir
  #define MySourceDir "..\dist\GuildCAM"
#endif

#define MyAppName "GuildCAM"
#define MyAppPublisher "Guild of American Spectacle Makers"
#define MyAppExeName "GuildCAM.exe"
#define MyAppId "{{D2C8A1F6-7B4E-4A3D-9E52-1C6B8F0A5E92}"

[Setup]
AppId={#MyAppId}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
VersionInfoVersion={#MyAppVersionNumeric}
VersionInfoProductVersion={#MyAppVersionNumeric}
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
; Per-user install — no UAC/admin prompt.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=GuildCAM-{#MyAppVersion}-setup
; Show the GNU GPL v3.0 the app is released under during setup.
LicenseFile=..\LICENSE
SetupIconFile=..\src\guildcam\assets\icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "associate"; Description: "Associate .gcam project files with GuildCAM"; GroupDescription: "File associations:"

[Files]
Source: "{#MySourceDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Registry]
; .gcam project association (per-user, removed on uninstall).
Root: HKCU; Subkey: "Software\Classes\.gcam"; ValueType: string; ValueName: ""; ValueData: "GuildCAM.Project"; Flags: uninsdeletevalue; Tasks: associate
Root: HKCU; Subkey: "Software\Classes\GuildCAM.Project"; ValueType: string; ValueName: ""; ValueData: "GuildCAM Project"; Flags: uninsdeletekey; Tasks: associate
Root: HKCU; Subkey: "Software\Classes\GuildCAM.Project\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#MyAppExeName},0"; Tasks: associate
Root: HKCU; Subkey: "Software\Classes\GuildCAM.Project\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" ""%1"""; Tasks: associate

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
