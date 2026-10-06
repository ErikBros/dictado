; Dictado installer (Inno Setup 6). Built by tools/build.py --installer, which passes
; /DAppVersion=x.y.z and /DDistDir=<PyInstaller dist\Dictado>.
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef DistDir
  #define DistDir "dist\Dictado"
#endif

[Setup]
AppId={{7C1B3F2E-5D4A-4E8B-9A61-D1C7A0D1C7A0}
AppName=Dictado
AppVersion={#AppVersion}
AppVerName=Dictado {#AppVersion}
AppPublisher=ErikBros
VersionInfoVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\Dictado
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputBaseFilename=Dictado-Setup-{#AppVersion}
SetupIconFile=dictado.ico
UninstallDisplayIcon={app}\Dictado.exe
UninstallDisplayName=Dictado
WizardStyle=modern
Compression=lzma2/normal
SolidCompression=yes
CloseApplications=no

[Languages]
Name: "en"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "startup"; Description: "Start Dictado with Windows"; GroupDescription: "Options:"

[Files]
Source: "{#DistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{userprograms}\Dictado"; Filename: "{app}\Dictado.exe"; Comment: "Voice dictation: tap Right Ctrl"

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "Dictado"; \
  ValueData: """{app}\Dictado.exe"""; Tasks: startup; Flags: uninsdeletevalue

[Run]
Filename: "{app}\Dictado.exe"; Description: "Open Dictado"; Flags: nowait postinstall

[InstallDelete]
; the 1.0 script deploy started itself from here; the installed app uses the Run key
Type: files; Name: "{userstartup}\Dictado.lnk"

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Code]
procedure StopDictado();
var
  Code: Integer;
  Pid: AnsiString;
begin
  { Our own per-user processes: the background app and the window. }
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/IM Dictado.exe /F', '', SW_HIDE, ewWaitUntilTerminated, Code);
  { The 1.0 script engine runs as pythonw.exe; its pid is in dictado.pid. The image filter
    makes sure a reused pid of some other program is never touched. }
  if LoadStringFromFile(ExpandConstant('{localappdata}\dictado\dictado.pid'), Pid) then
    Exec(ExpandConstant('{sys}\taskkill.exe'), '/FI "PID eq ' + Trim(String(Pid)) + '" /FI "IMAGENAME eq pythonw.exe" /F',
      '', SW_HIDE, ewWaitUntilTerminated, Code);
  Sleep(800);
end;

{ The meeting worker's pid from meetings.json (the "pid" inside "meeting", before "job"),
  or 0 when no meeting records or saves. /MeetingsFile= points it at another file (tests). }
function MeetingPid(): Integer;
var
  S: AnsiString;
  T: String;
  I, J: Integer;
begin
  Result := 0;
  if not LoadStringFromFile(ExpandConstant('{param:MeetingsFile|{localappdata}\dictado\meetings.json}'), S) then
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

{ True while a meeting worker is alive: a stale meetings.json after a crash must not block. }
function MeetingRecording(): Boolean;
var
  Pid, Code: Integer;
begin
  Result := False;
  Pid := MeetingPid();
  if Pid = 0 then
    Exit;
  Exec(ExpandConstant('{cmd}'), '/C tasklist /FI "PID eq ' + IntToStr(Pid) + '" /FI "IMAGENAME eq Dictado.exe" /NH | find /I "Dictado.exe" >NUL',
    '', SW_HIDE, ewWaitUntilTerminated, Code);
  Result := Code = 0;
end;

{ Never kill a call that is being recorded (t0u.18): wait until it is stopped and saved.
  Silent installs (/SUPPRESSMSGBOXES) take the Cancel default and refuse. }
function MeetingDone(): Boolean;
begin
  Result := True;
  while MeetingRecording() do
    if SuppressibleMsgBox('Dictado is recording a meeting right now. Closing it would cut the recording.' + #13#10#13#10 +
         'Stop the meeting in Dictado (it saves the transcript first), wait for "Ready", then click Retry.',
         mbError, MB_RETRYCANCEL, IDCANCEL) <> IDRETRY then begin
      Result := False;
      Exit;
    end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  if not MeetingDone() then begin
    Result := 'Dictado is recording a meeting, so nothing was changed. Run Setup again when the meeting is over.';
    Exit;
  end;
  StopDictado();
  Result := '';
end;

function InitializeUninstall(): Boolean;
begin
  Result := MeetingDone();
  if Result then
    StopDictado();
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
    RegDeleteValue(HKEY_CURRENT_USER, 'Software\Microsoft\Windows\CurrentVersion\Run', 'Dictado');
end;
