; Ecoscribe installer (Inno Setup 6). Built by tools/build.py --installer, which passes
; /DAppVersion=x.y.z and /DDistDir=<PyInstaller dist\Ecoscribe>.
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef DistDir
  #define DistDir "dist\Ecoscribe"
#endif

[Setup]
AppId={{7C1B3F2E-5D4A-4E8B-9A61-D1C7A0D1C7A0}
AppName=Ecoscribe
AppVersion={#AppVersion}
AppVerName=Ecoscribe {#AppVersion}
AppPublisher=ErikBros
VersionInfoVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\Ecoscribe
; same AppId as Dictado: without this an upgrade would stay in Programs\Dictado (dictado-c9u)
UsePreviousAppDir=no
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputBaseFilename=Ecoscribe-Setup-{#AppVersion}
SetupIconFile=ecoscribe.ico
UninstallDisplayIcon={app}\Ecoscribe.exe
UninstallDisplayName=Ecoscribe
WizardStyle=modern
Compression=lzma2/normal
SolidCompression=yes
CloseApplications=no

[Languages]
Name: "en"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "startup"; Description: "Start Ecoscribe with Windows"; GroupDescription: "Options:"

[Files]
Source: "{#DistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{userprograms}\Ecoscribe"; Filename: "{app}\Ecoscribe.exe"; Comment: "Voice dictation: tap Right Ctrl"

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "Ecoscribe"; \
  ValueData: """{app}\Ecoscribe.exe"""; Tasks: startup; Flags: uninsdeletevalue

[Run]
Filename: "{app}\Ecoscribe.exe"; Description: "Open Ecoscribe"; Flags: nowait postinstall

[InstallDelete]
; the 1.0 script deploy started itself from here; the installed app uses the Run key
Type: files; Name: "{userstartup}\Dictado.lnk"
; renamed to Ecoscribe (dictado-c9u): the old Start menu shortcut and the old install folder go
Type: files; Name: "{userprograms}\Dictado.lnk"
Type: filesandordirs; Name: "{localappdata}\Programs\Dictado"

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Code]
const
  RunKey = 'Software\Microsoft\Windows\CurrentVersion\Run';

procedure StopEcoscribe();
var
  Code: Integer;
  Pid: AnsiString;
begin
  { Our own per-user processes: the background app and the window. }
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/IM Ecoscribe.exe /F', '', SW_HIDE, ewWaitUntilTerminated, Code);
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/IM Dictado.exe /F', '', SW_HIDE, ewWaitUntilTerminated, Code);  { before the rename }
  { The 1.0 script engine runs as pythonw.exe; its pid is in dictado.pid. The image filter
    makes sure a reused pid of some other program is never touched. }
  if LoadStringFromFile(ExpandConstant('{localappdata}\dictado\dictado.pid'), Pid) then
    Exec(ExpandConstant('{sys}\taskkill.exe'), '/FI "PID eq ' + Trim(String(Pid)) + '" /FI "IMAGENAME eq pythonw.exe" /F',
      '', SW_HIDE, ewWaitUntilTerminated, Code);
  Sleep(800);
end;

{ The meeting worker's pid from a meetings.json (the "pid" inside "meeting", before "job"),
  or 0 when no meeting records or saves. }
function MeetingPid(F: String): Integer;
var
  S: AnsiString;
  T: String;
  I, J: Integer;
begin
  Result := 0;
  if not LoadStringFromFile(F, S) then
    Exit;
  T := String(S);
  I := Pos('"meeting":', T);
  if (I = 0) or (Pos('"meeting": null', T) = I) then
    Exit;
  J := Pos('"job":', T);  { the meeting's own pid comes before the job's }
  if J > 0 then
    T := Copy(T, I, J - I)
  else
    T := Copy(T, I, Length(T));
  I := Pos('"pid": ', T);
  if I = 0 then
    Exit;
  I := I + 7;
  J := I;
  while (J <= Length(T)) and (T[J] >= '0') and (T[J] <= '9') do
    J := J + 1;
  Result := StrToIntDef(Copy(T, I, J - I), 0);
end;

{ True while that meeting worker is alive: a stale meetings.json after a crash must not block. }
function WorkerAlive(F, Exe: String): Boolean;
var
  Pid, Code: Integer;
begin
  Result := False;
  Pid := MeetingPid(F);
  if Pid = 0 then
    Exit;
  Exec(ExpandConstant('{cmd}'), '/C tasklist /FI "PID eq ' + IntToStr(Pid) + '" /FI "IMAGENAME eq ' + Exe + '" /NH | find /I "' + Exe + '" >NUL',
    '', SW_HIDE, ewWaitUntilTerminated, Code);
  Result := Code = 0;
end;

{ /MeetingsFile= points it at another file (tests). Upgrading from Dictado (dictado-c9u): the old
  app's folder and exe name. }
function MeetingRecording(): Boolean;
begin
  Result := WorkerAlive(ExpandConstant('{param:MeetingsFile|{localappdata}\ecoscribe\meetings.json}'), 'Ecoscribe.exe')
    or WorkerAlive(ExpandConstant('{localappdata}\dictado\meetings.json'), 'Dictado.exe');
end;

{ Never kill a call that is being recorded (t0u.18): wait until it is stopped and saved.
  Silent installs (/SUPPRESSMSGBOXES) take the Cancel default and refuse. }
function MeetingDone(): Boolean;
begin
  Result := True;
  while MeetingRecording() do
    if SuppressibleMsgBox('Ecoscribe is recording a meeting right now. Closing it would cut the recording.' + #13#10#13#10 +
         'Stop the meeting in Ecoscribe (it saves the transcript first), wait for "Ready", then click Retry.',
         mbError, MB_RETRYCANCEL, IDCANCEL) <> IDRETRY then begin
      Result := False;
      Exit;
    end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  if not MeetingDone() then begin
    Result := 'Ecoscribe is recording a meeting, so nothing was changed. Run Setup again when the meeting is over.';
    Exit;
  end;
  StopEcoscribe();
  Result := '';
end;

function InitializeUninstall(): Boolean;
begin
  Result := MeetingDone();
  if Result then
    StopEcoscribe();
end;

{ Start with Windows from before the rename (dictado-c9u): the "Dictado" value, or an "Ecoscribe"
  one that 1.6.0 pointed at Dictado.exe, now starts this install. }
procedure CurStepChanged(CurStep: TSetupStep);
var
  Cmd: String;
begin
  if CurStep <> ssPostInstall then
    Exit;
  if RegValueExists(HKEY_CURRENT_USER, RunKey, 'Dictado') or
     (RegQueryStringValue(HKEY_CURRENT_USER, RunKey, 'Ecoscribe', Cmd) and (Pos('dictado.exe', Lowercase(Cmd)) > 0)) then
    RegWriteStringValue(HKEY_CURRENT_USER, RunKey, 'Ecoscribe', '"' + ExpandConstant('{app}\Ecoscribe.exe') + '"');
  RegDeleteValue(HKEY_CURRENT_USER, RunKey, 'Dictado');
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
  begin
    RegDeleteValue(HKEY_CURRENT_USER, RunKey, 'Ecoscribe');
    RegDeleteValue(HKEY_CURRENT_USER, RunKey, 'Dictado');
  end;
end;
