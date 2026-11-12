; Inno Setup script for SuperPOS (Windows).
; Build the app first, then the installer:
;   pyinstaller --noconfirm superpos.spec
;   iscc installer\superpos.iss        ->  dist\SuperPOS-<version>-setup.exe
;
; Installs the one-folder build (dist\SuperPOS) into Program Files. The DB,
; logs, backups and backup password live in %APPDATA%\SuperPOS, never in {app}:
; uninstalling or upgrading never touches shop data.

; The version comes from the built exe's version resource (set by superpos.spec
; from app/__version__.py), so there is still only one place to bump it.
#define AppExe "..\dist\SuperPOS\SuperPOS.exe"
#define AppVersion GetStringFileInfo(AppExe, "ProductVersion")
#if AppVersion == ""
  #error Build dist\SuperPOS with PyInstaller before compiling the installer
#endif

[Setup]
; Never change AppId: it is how a new installer recognises an installed SuperPOS to upgrade.
AppId={{8B39E1EE-DBA4-489F-97EB-89714859802D}
AppName=SuperPOS
AppVersion={#AppVersion}
AppPublisher=SKBC bv
DefaultDirName={autopf}\SuperPOS
DefaultGroupName=SuperPOS
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\SuperPOS.exe
SetupIconFile=..\resources\icons\kassa.ico
OutputDir=..\dist
OutputBaseFilename=SuperPOS-{#AppVersion}-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; Ask to close a running SuperPOS instead of failing on locked files.
CloseApplications=yes
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[InstallDelete]
; Drop the previous version's bundled libs so stale DLLs/modules can't be picked up after an upgrade.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\dist\SuperPOS\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\SuperPOS"; Filename: "{app}\SuperPOS.exe"
Name: "{group}\{cm:UninstallProgram,SuperPOS}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\SuperPOS"; Filename: "{app}\SuperPOS.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\SuperPOS.exe"; Description: "{cm:LaunchProgram,SuperPOS}"; Flags: nowait postinstall skipifsilent
; The in-app updater installs silently: start the new version again (as the cashier, not the UAC admin).
Filename: "{app}\SuperPOS.exe"; Flags: nowait postinstall skipifnotsilent
