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
UninstallDisplayName=IDEmu Native
#else
AppId={{1C37C78F-21F2-4D49-8DD7-41AA78250FD8}
AppName=IDEmu
DefaultDirName={localappdata}\Programs\IDEmu
OutputBaseFilename=IDEmu-Setup
InfoBeforeFile=install-info.txt
UninstallDisplayName=IDEmu
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
Uninstallable=yes
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\icon.ico

[Files]
Source: "{#PayloadDir}\IDEmu\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#PayloadDir}\installed-version.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "icon.ico"; DestDir: "{app}"; Flags: ignoreversion
#ifndef NativeEdition
Source: "{#PayloadDir}\IDEmu-Prep\*"; DestDir: "{app}\prep"; Flags: ignoreversion recursesubdirs createallsubdirs
#endif

[Tasks]
Name: "desktopicon"; Description: "Add a shortcut to the desktop"; GroupDescription: "Shortcuts:"

[Icons]
#ifdef NativeEdition
Name: "{autoprograms}\IDEmu Native\IDEmu Native"; Filename: "{app}\IDEmu.exe"; WorkingDir: "{app}"; IconFilename: "{app}\icon.ico"
Name: "{autoprograms}\IDEmu Native\Check for updates"; Filename: "{app}\IDEmu.exe"; Parameters: "--check-update"; WorkingDir: "{app}"; IconFilename: "{app}\icon.ico"
Name: "{autoprograms}\IDEmu Native\Uninstall IDEmu Native"; Filename: "{uninstallexe}"
Name: "{autodesktop}\IDEmu Native"; Filename: "{app}\IDEmu.exe"; WorkingDir: "{app}"; IconFilename: "{app}\icon.ico"; Tasks: desktopicon
#else
Name: "{autoprograms}\IDEmu\IDEmu (WSL2)"; Filename: "{app}\IDEmu.exe"; WorkingDir: "{app}"; IconFilename: "{app}\icon.ico"
Name: "{autoprograms}\IDEmu\Prepare firmware (Windows)"; Filename: "{app}\prep\IDEmu-Prep.exe"; WorkingDir: "{app}\prep"; IconFilename: "{app}\icon.ico"
Name: "{autoprograms}\IDEmu\Check for updates"; Filename: "{app}\IDEmu.exe"; Parameters: "--check-update"; WorkingDir: "{app}"; IconFilename: "{app}\icon.ico"
Name: "{autoprograms}\IDEmu\Uninstall IDEmu"; Filename: "{uninstallexe}"
Name: "{autodesktop}\IDEmu (WSL2)"; Filename: "{app}\IDEmu.exe"; WorkingDir: "{app}"; IconFilename: "{app}\icon.ico"; Tasks: desktopicon
#endif

[Run]
#ifdef NativeEdition
Filename: "{app}\IDEmu.exe"; Description: "Open IDEmu Native"; Flags: postinstall nowait skipifsilent unchecked
#else
Filename: "{app}\IDEmu.exe"; Description: "Open IDEmu (requires Ubuntu WSL2 and WSLg)"; Flags: postinstall nowait skipifsilent unchecked
Filename: "{app}\prep\IDEmu-Prep.exe"; Description: "Open the native Windows firmware tool"; Flags: postinstall nowait skipifsilent unchecked
#endif

[UninstallDelete]
; Files the app creates beside itself, such as Python bytecode caches written by the WSL backend.
Type: filesandordirs; Name: "{app}"

[Code]
const
  DataFolderName = 'IDEmu';

function HasParam(const Name: String): Boolean;
var
  I: Integer;
begin
  Result := False;
  for I := 1 to ParamCount do
    if CompareText(ParamStr(I), Name) = 0 then
      Result := True;
end;

{ Ends processes running from this installation, such as QEMU or the renderer left behind by an older build. }
procedure StopInstalledProcesses();
var
  AppPath, Command: String;
  ResultCode: Integer;
begin
  AppPath := ExpandConstant('{app}');
  StringChangeEx(AppPath, '''', '''''', True);
  Command := '-NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "' +
    'Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.Path -and $_.Path.StartsWith(''' + AppPath + '\'', ' +
    '[System.StringComparison]::OrdinalIgnoreCase) } | Stop-Process -Force -ErrorAction SilentlyContinue"';
  Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'), Command, '', SW_HIDE,
    ewWaitUntilTerminated, ResultCode);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  StopInstalledProcesses();
  Result := '';
end;

{ Removes %LOCALAPPDATA%\IDEmu when the user agrees, or always with /PURGEDATA (useful for scripted test runs). }
procedure RemoveUserData();
var
  DataDir: String;
  Purge: Boolean;
begin
  DataDir := ExpandConstant('{localappdata}\') + DataFolderName;
  if not DirExists(DataDir) then
    Exit;
  Purge := HasParam('/PURGEDATA');
  if (not Purge) and (not UninstallSilent()) then
    Purge := MsgBox('Also delete IDEmu settings, built environments, logs and caches?' + #13#10#13#10 +
                    DataDir + #13#10#13#10 +
                    'This folder is shared by IDEmu Native and the Windows firmware tool of the WSL2 edition. ' +
                    'Your BMW firmware (PSdZData) and WSL2 environments are not touched.',
                    mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES;
  if not Purge then
    Exit;
  if not DelTree(DataDir, True, True, True) then
    if not UninstallSilent() then
      MsgBox('Some files in ' + DataDir + ' could not be deleted. Close any program using them, then delete the folder manually.',
             mbError, MB_OK);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
    StopInstalledProcesses();
  if CurUninstallStep = usPostUninstall then
    RemoveUserData();
end;
