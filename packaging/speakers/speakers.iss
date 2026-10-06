; Dictado speaker add-on (Inno Setup 6), t0u.22. Built by build_speakers.py --installer.
; Its own folder and uninstall entry: Dictado's installer and upgrades never touch it.
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef DistDir
  #define DistDir "dist\DictadoSpeakers"
#endif

[Setup]
AppId={{9E4D2A61-3B7C-4F85-A1D2-5C6B7E8F9A0B}
AppName=Dictado speaker add-on
AppVersion={#AppVersion}
AppVerName=Dictado speaker add-on {#AppVersion}
AppPublisher=ErikBros
VersionInfoVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\Dictado Speakers
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputBaseFilename=Dictado-Speakers-Setup-{#AppVersion}
SetupIconFile=..\dictado.ico
UninstallDisplayName=Dictado speaker add-on
WizardStyle=modern
Compression=lzma2/normal
SolidCompression=yes
CloseApplications=no

[Languages]
Name: "en"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "{#DistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Code]
{ A speakers pass running right now would lose its exe mid-run: stop only that process. }
procedure StopAddon();
var
  Code: Integer;
begin
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/IM DictadoSpeakers.exe /F', '', SW_HIDE, ewWaitUntilTerminated, Code);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  StopAddon();
  Result := '';
end;

function InitializeUninstall(): Boolean;
begin
  StopAddon();
  Result := True;
end;
