; OpenDeck installer (Inno Setup 6). Built by scripts\build.ps1:
;   ISCC.exe /DAppVersion=1.0.0 installer\OpenDeck.iss   ->  dist\installer\OpenDeck-Setup-1.0.0.exe
;
; Program files go to Program Files\OpenDeck. User data lives in %LOCALAPPDATA%\OpenDeck
; and is never touched by upgrades; uninstalling asks before deleting it (default: keep).

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#define AppName "OpenDeck"
#define AppExe "OpenDeck.exe"
#define SourceDir "..\dist\OpenDeck"

[Setup]
; Never change AppId: upgrades find the existing installation through it.
AppId={{A4B5C3EC-9EFB-4024-9723-B725239DF3A5}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=OpenDeck contributors
AppComments=Turn a phone or tablet into a Stream Deck-style control surface for this PC.
VersionInfoVersion={#AppVersion}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
; Administrator install by default (Program Files, firewall rule). /CURRENTUSER installs per user without them.
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=commandline dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=..\dist\installer
OutputBaseFilename=OpenDeck-Setup-{#AppVersion}
SetupIconFile=..\assets\icons\app.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
LicenseFile=..\LICENSE
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; Fallback if the running app could not be asked to exit (see InitializeSetup).
AppMutex=Local\OpenDeck.Desktop
CloseApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: unchecked
Name: "startup"; Description: "&Start OpenDeck when I sign in to Windows (in the notification area)"; GroupDescription: "Startup:"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\LICENSE"; DestDir: "{app}"; DestName: "LICENSE.txt"; Flags: ignoreversion

[InstallDelete]
; Upgrades replace the whole program folder content (never user data, which is elsewhere).
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
; The same Run value the app's own "Start with Windows" setting manages.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "{#AppName}"; ValueData: """{app}\{#AppExe}"" --minimized"; Tasks: startup; Flags: uninsdeletevalue

[Run]
; Let phones on PRIVATE networks reach the server (public Wi-Fi stays blocked). Admin installs only.
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""{#AppName}"" program=""{app}\{#AppExe}"""; Flags: runhidden; Check: IsAdminInstallMode
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""{#AppName}"" dir=in action=allow program=""{app}\{#AppExe}"" enable=yes profile=private"; Flags: runhidden; StatusMsg: "Allowing OpenDeck on private networks..."; Check: IsAdminInstallMode
Filename: "{app}\{#AppExe}"; Description: "Start {#AppName}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""{#AppName}"" program=""{app}\{#AppExe}"""; Flags: runhidden; RunOnceId: "RemoveFirewallRule"; Check: IsAdminInstallMode

[Code]
const
  { Inno writes the uninstall entry under the AppId with ONE opening brace. }
  UninstallKey = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{A4B5C3EC-9EFB-4024-9723-B725239DF3A5}_is1';
  { The app was called MyStreamDeck before; that install is replaced (its user data is kept and imported). }
  OldUninstallKey = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{6A4B2D1E-7C3F-4E8A-9B15-2F6D8C0E4A71}_is1';
  OldMutex = 'Local\MyStreamDeck.Desktop';
  AppMutexName = 'Local\OpenDeck.Desktop';
  WebView2Key ='SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';

function WebView2Installed: Boolean;
var
  Version: String;
begin
  Result := (RegQueryStringValue(HKLM, WebView2Key, 'pv', Version) and (Version <> '') and (Version <> '0.0.0.0'))
    or (RegQueryStringValue(HKCU, 'Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version)
        and (Version <> '') and (Version <> '0.0.0.0'));
end;

{ Ask a running copy to quit cleanly (it stops the server and closes the database). }
procedure AskRunningAppToExit(const Exe, Mutex: String);
var
  Code, Waited: Integer;
begin
  if not CheckForMutexes(Mutex) then
    exit;
  if FileExists(Exe) then
    Exec(Exe, '--exit', '', SW_HIDE, ewWaitUntilTerminated, Code);
  Waited := 0;
  while CheckForMutexes(Mutex) and (Waited < 15000) do
  begin
    Sleep(250);
    Waited := Waited + 250;
  end;
end;

function InstalledExe: String;
var
  Path: String;
begin
  Result := '';
  if RegQueryStringValue(HKLM, UninstallKey, 'InstallLocation', Path)
     or RegQueryStringValue(HKCU, UninstallKey, 'InstallLocation', Path) then
    Result := AddBackslash(Path) + '{#AppExe}';
end;

function InitializeSetup: Boolean;
begin
  Result := True;
  if not WebView2Installed then
    MsgBox('OpenDeck needs the Microsoft Edge WebView2 Runtime, which is part of Windows 11 and most Windows 10 PCs. ' +
      'It was not found on this PC.' + #13#10#13#10 +
      'Setup will continue. If the OpenDeck window stays blank, install the "Evergreen" WebView2 Runtime from ' +
      'https://developer.microsoft.com/microsoft-edge/webview2/', mbInformation, MB_OK);
  AskRunningAppToExit(InstalledExe, AppMutexName);
end;

function OldInstallKey(var Root: Integer): Boolean;
begin
  Result := True;
  Root := HKLM;
  if RegKeyExists(HKLM, OldUninstallKey) then exit;
  Root := HKCU;
  if RegKeyExists(HKCU, OldUninstallKey) then exit;
  Result := False;
end;

{ Remove MyStreamDeck (the previous name) silently: its shortcuts, firewall rule and startup entry go,
  its user data stays and OpenDeck imports it on first start. }
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Root, Code, Waited: Integer;
  Uninstaller, Location: String;
begin
  Result := '';
  if not OldInstallKey(Root) then
    exit;
  if RegQueryStringValue(Root, OldUninstallKey, 'InstallLocation', Location) then
    AskRunningAppToExit(AddBackslash(Location) + 'MyStreamDeck.exe', OldMutex);
  if not RegQueryStringValue(Root, OldUninstallKey, 'UninstallString', Uninstaller) then
    exit;
  if not Exec(RemoveQuotes(Uninstaller), '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART', '', SW_HIDE,
              ewWaitUntilTerminated, Code) then
  begin
    Result := 'The previous version (MyStreamDeck) could not be removed. Uninstall it in Windows Settings > Apps, then run this setup again.';
    exit;
  end;
  { The uninstaller hands over to a copy of itself; wait until it has finished. }
  Waited := 0;
  while RegKeyExists(Root, OldUninstallKey) and (Waited < 60000) do
  begin
    Sleep(500);
    Waited := Waited + 500;
  end;
end;

function InitializeUninstall: Boolean;
begin
  Result := True;
  AskRunningAppToExit(ExpandConstant('{app}\{#AppExe}'), AppMutexName);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    { The app's own "Start with Windows" setting may have created this value. }
    RegDeleteValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', '{#AppName}');
    DataDir := ExpandConstant('{localappdata}\{#AppName}');
    if DirExists(DataDir) and not UninstallSilent then
      if MsgBox('Also delete your OpenDeck profiles, buttons, paired devices and logs?' + #13#10#13#10 +
                DataDir + #13#10#13#10 + 'Choose No to keep them for a later reinstall.',
                mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        DelTree(DataDir, True, True, True);
  end;
end;
