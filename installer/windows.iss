#ifndef AppVersion
  #error Pass /DAppVersion=X.Y.Z
#endif

[Setup]
AppId={{1C37C78F-21F2-4D49-8DD7-41AA78250FD8}
AppName=IDEmu
AppVersion={#AppVersion}
VersionInfoVersion={#AppVersion}
AppPublisher=IDEmu contributors
AppPublisherURL=https://github.com/KClemente11/IDEmu
AppUpdatesURL=https://github.com/KClemente11/IDEmu/releases
DefaultDirName={localappdata}\Programs\IDEmu
DisableDirPage=yes
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#OutputDir}
OutputBaseFilename=IDEmu-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
AppMutex=IDEmu.Windows.App
CloseApplications=no
UninstallDisplayIcon={app}\IDEmu.exe
InfoBeforeFile=install-info.txt

[Files]
Source: "{#PayloadDir}\IDEmu\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#PayloadDir}\IDEmu-Prep\*"; DestDir: "{app}\prep"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#PayloadDir}\installed-version.txt"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\IDEmu\IDEmu (WSL2)"; Filename: "{app}\IDEmu.exe"; WorkingDir: "{app}"
Name: "{autoprograms}\IDEmu\Prepare firmware (Windows)"; Filename: "{app}\prep\IDEmu-Prep.exe"; WorkingDir: "{app}\prep"
Name: "{autoprograms}\IDEmu\Check for updates"; Filename: "{app}\IDEmu.exe"; Parameters: "--check-update"; WorkingDir: "{app}"

[Run]
Filename: "{app}\IDEmu.exe"; Description: "Open IDEmu (requires Ubuntu WSL2 and WSLg)"; Flags: postinstall nowait skipifsilent unchecked
Filename: "{app}\prep\IDEmu-Prep.exe"; Description: "Open the native Windows firmware tool"; Flags: postinstall nowait skipifsilent unchecked
