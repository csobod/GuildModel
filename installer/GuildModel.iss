; Inno Setup script for GuildModel — per-user (no-admin) Windows installer.
;
; Packages the PyInstaller one-folder build (dist\GuildModel) into a single
; GuildModel-<version>-setup.exe that installs to %LocalAppData%\Programs\GuildModel,
; adds Start Menu (and optional Desktop) shortcuts, registers the .gmodel project
; association under HKCU, and provides an Add/Remove Programs uninstaller.
;
; Compile manually:
;   "%LocalAppData%\Programs\Inno Setup 6\ISCC.exe" installer\GuildModel.iss
; Or, with overrides from the release script:
;   ISCC.exe /DMyAppVersion=1.0.0-rc1 /DMyAppVersionNumeric=1.0.0.0 installer\GuildModel.iss
;
; The release script (scripts\build_release.ps1) passes the version defines and
; builds dist\GuildModel first. Defaults below let the script be compiled by hand.

#ifndef MyAppVersion
  #define MyAppVersion "1.0.0-rc1a"
#endif
#ifndef MyAppVersionNumeric
  #define MyAppVersionNumeric "1.0.0.0"
#endif
#ifndef MySourceDir
  #define MySourceDir "..\dist\GuildModel"
#endif

#define MyAppName "GuildModel"
#define MyAppPublisher "Guild of American Spectacle Makers"
#define MyAppExeName "GuildModel.exe"
#define MyAppId "{{A02EDEB9-CA5E-4CED-AAF1-7BC42D73DC18}"

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
OutputBaseFilename=GuildModel-{#MyAppVersion}-setup
; Show the GNU GPL v3.0 the app is released under during setup.
LicenseFile=..\LICENSE
SetupIconFile=..\src\guildmodel\assets\icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "associate"; Description: "Associate .gmodel project files with GuildModel"; GroupDescription: "File associations:"

[Files]
Source: "{#MySourceDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Registry]
; .gmodel project association (per-user, removed on uninstall).
Root: HKCU; Subkey: "Software\Classes\.gmodel"; ValueType: string; ValueName: ""; ValueData: "GuildModel.Project"; Flags: uninsdeletevalue; Tasks: associate
Root: HKCU; Subkey: "Software\Classes\GuildModel.Project"; ValueType: string; ValueName: ""; ValueData: "GuildModel Project"; Flags: uninsdeletekey; Tasks: associate
Root: HKCU; Subkey: "Software\Classes\GuildModel.Project\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#MyAppExeName},0"; Tasks: associate
Root: HKCU; Subkey: "Software\Classes\GuildModel.Project\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" ""%1"""; Tasks: associate

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
