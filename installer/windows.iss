#ifndef AppVersion
  #error Pass /DAppVersion=X.Y.Z
#endif

[Setup]
#ifdef NativeEdition
AppId={{C34CC054-8D2C-47F4-8635-48A8932A9A36}
AppName=IDEmu Native
DefaultDirName={localappdata}\Programs\IDEmu Native
OutputBaseFilename=IDEmu-Native-Setup
InfoBeforeFile=native-info.txt
#else
AppId={{1C37C78F-21F2-4D49-8DD7-41AA78250FD8}
AppName=IDEmu
DefaultDirName={localappdata}\Programs\IDEmu
OutputBaseFilename=IDEmu-Setup
InfoBeforeFile=install-info.txt
#endif
AppVersion={#AppVersion}
VersionInfoVersion={#AppVersion}
AppPublisher=IDEmu contributors
AppPublisherURL=https://github.com/KClemente11/IDEmu
AppUpdatesURL=https://github.com/KClemente11/IDEmu/releases
DisableDirPage=yes
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#OutputDir}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
AppMutex=IDEmu.Windows.App
CloseApplications=no
UninstallDisplayIcon={app}\IDEmu.exe

[Files]
Source: "{#PayloadDir}\IDEmu\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#PayloadDir}\installed-version.txt"; DestDir: "{app}"; Flags: ignoreversion
#ifndef NativeEdition
Source: "{#PayloadDir}\IDEmu-Prep\*"; DestDir: "{app}\prep"; Flags: ignoreversion recursesubdirs createallsubdirs
#endif

[Icons]
#ifdef NativeEdition
Name: "{autoprograms}\IDEmu Native\IDEmu Native"; Filename: "{app}\IDEmu.exe"; WorkingDir: "{app}"
Name: "{autoprograms}\IDEmu Native\Check for updates"; Filename: "{app}\IDEmu.exe"; Parameters: "--check-update"; WorkingDir: "{app}"
#else
Name: "{autoprograms}\IDEmu\IDEmu (WSL2)"; Filename: "{app}\IDEmu.exe"; WorkingDir: "{app}"
Name: "{autoprograms}\IDEmu\Prepare firmware (Windows)"; Filename: "{app}\prep\IDEmu-Prep.exe"; WorkingDir: "{app}\prep"
Name: "{autoprograms}\IDEmu\Check for updates"; Filename: "{app}\IDEmu.exe"; Parameters: "--check-update"; WorkingDir: "{app}"
#endif

[Run]
#ifdef NativeEdition
Filename: "{app}\IDEmu.exe"; Description: "Open IDEmu Native"; Flags: postinstall nowait skipifsilent unchecked
#else
Filename: "{app}\IDEmu.exe"; Description: "Open IDEmu (requires Ubuntu WSL2 and WSLg)"; Flags: postinstall nowait skipifsilent unchecked
Filename: "{app}\prep\IDEmu-Prep.exe"; Description: "Open the native Windows firmware tool"; Flags: postinstall nowait skipifsilent unchecked
#endif
