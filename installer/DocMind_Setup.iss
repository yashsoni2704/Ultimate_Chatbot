; ============================================================
;  DocMind — Inno Setup Installer Script
;  Version  : 1.0.0
;  Target   : Windows 10/11 x64
;  Output   : installer\Output\DocMind_Setup.exe
;
;  What this installer does:
;   1. Checks for Python 3.11+  → downloads & installs if missing
;   2. Checks for MongoDB       → downloads & installs if missing
;   3. Checks for Ollama        → downloads & installs if missing
;   4. Copies all app files to C:\DocMind
;   5. Runs install_helper.bat  → creates venv, pip install,
;                                  pulls AI models (bge-m3 + llama3.1)
;   6. Creates Desktop shortcut + Start Menu entry
;   7. Registers uninstaller
; ============================================================

#define AppName        "DocMind"
#define AppVersion     "1.0.0"
#define AppPublisher   "DocMind"
#define AppURL         "http://localhost:5000"
#define AppExeName     "DocMind.bat"
#define DefaultDirName "C:\DocMind"
#define OutputDir      "Output"

; ── Download URLs (online installer — fetched during install) ─────────────
#define PythonURL      "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe"
#define OllamaURL      "https://ollama.com/download/OllamaSetup.exe"
#define MongoURL       "https://fastdl.mongodb.org/windows/mongodb-windows-x86_64-8.0.4-signed.msi"

; ── Source path = parent folder of installer\ ────────────────────────────
#define SourceRoot     ".."

[Setup]
AppId                    = {{7A3F2C1D-8B4E-4F6A-9C2D-1E5B7D3A6F8C}
AppName                  = {#AppName}
AppVersion               = {#AppVersion}
AppPublisher             = {#AppPublisher}
AppPublisherURL          = {#AppURL}
AppSupportURL            = {#AppURL}
AppUpdatesURL            = {#AppURL}
DefaultDirName           = {#DefaultDirName}
DefaultGroupName         = {#AppName}
DisableProgramGroupPage  = yes
OutputDir                = {#OutputDir}
OutputBaseFilename       = DocMind_Setup
SetupIconFile            = assets\DocMind.ico
Compression              = lzma2/ultra64
SolidCompression         = yes
WizardStyle              = modern
WizardResizable          = no
PrivilegesRequired       = admin
PrivilegesRequiredOverridesAllowed = dialog
MinVersion               = 10.0.17763
ArchitecturesInstallIn64BitMode = x64compatible
UninstallDisplayIcon     = {app}\assets\DocMind.ico
UninstallDisplayName     = {#AppName}
CloseApplications        = yes
RestartIfNeededByRun     = no
ShowLanguageDialog       = no

; ── Installer pages ───────────────────────────────────────────────────────
[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Messages]
WelcomeLabel1=Welcome to the DocMind Setup Wizard
WelcomeLabel2=This will install DocMind on your computer.%n%nDocMind is an AI-powered document chatbot. It lets you upload PDFs, Word files, Excel sheets and more, then ask questions about them in natural language.%n%nThe installer will automatically set up:%n  - Python 3.11 (if not installed)%n  - MongoDB        (if not installed)%n  - Ollama AI      (if not installed)%n  - All Python packages%n  - AI models: bge-m3 + llama3.1%n%nInternet connection required. Total download: ~6 GB.%n%nClick Next to continue.
FinishedHeadingLabel=DocMind Installation Complete
FinishedLabel=DocMind has been installed successfully.%n%nA shortcut has been created on your Desktop.%n%nClick [Launch DocMind] below or double-click the Desktop icon to start.

[Tasks]
Name: "desktopicon";    Description: "Create a Desktop shortcut";    GroupDescription: "Shortcuts:"; Flags: checked
Name: "startmenuicon";  Description: "Create a Start Menu entry";    GroupDescription: "Shortcuts:"; Flags: checked

; ── Files to copy into C:\DocMind ────────────────────────────────────────
[Files]

; ── Core Python app files ─────────────────────────────────────────────────
Source: "{#SourceRoot}\app.py";              DestDir: "{app}"; Flags: ignoreversion
Source: "{#SourceRoot}\admin_app.py";        DestDir: "{app}"; Flags: ignoreversion
Source: "{#SourceRoot}\config.py";           DestDir: "{app}"; Flags: ignoreversion
Source: "{#SourceRoot}\watcher.py";          DestDir: "{app}"; Flags: ignoreversion
Source: "{#SourceRoot}\requirements.txt";    DestDir: "{app}"; Flags: ignoreversion
Source: "{#SourceRoot}\.env.example";        DestDir: "{app}"; Flags: ignoreversion
Source: "{#SourceRoot}\qdrant.exe";          DestDir: "{app}"; Flags: ignoreversion
Source: "{#SourceRoot}\qdrant_config.yaml";  DestDir: "{app}"; Flags: ignoreversion

; ── utils/ package ────────────────────────────────────────────────────────
Source: "{#SourceRoot}\utils\*"; DestDir: "{app}\utils"; Flags: ignoreversion recursesubdirs createallsubdirs

; ── db/ package ───────────────────────────────────────────────────────────
Source: "{#SourceRoot}\db\*"; DestDir: "{app}\db"; Flags: ignoreversion recursesubdirs createallsubdirs

; ── static/ (CSS, JS, images) ─────────────────────────────────────────────
Source: "{#SourceRoot}\static\*"; DestDir: "{app}\static"; Flags: ignoreversion recursesubdirs createallsubdirs

; ── templates/ (HTML) ─────────────────────────────────────────────────────
Source: "{#SourceRoot}\templates\*"; DestDir: "{app}\templates"; Flags: ignoreversion recursesubdirs createallsubdirs

; ── scripts/ (utility scripts) ────────────────────────────────────────────
Source: "{#SourceRoot}\scripts\*"; DestDir: "{app}\scripts"; Flags: ignoreversion recursesubdirs createallsubdirs

; ── Installer assets (launcher + helper) ─────────────────────────────────
Source: "assets\install_helper.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "assets\launcher.bat";       DestDir: "{app}"; Flags: ignoreversion
Source: "assets\DocMind.ico";        DestDir: "{app}\assets"; Flags: ignoreversion

; ── Shortcuts ─────────────────────────────────────────────────────────────
[Icons]
Name: "{userdesktop}\DocMind";                   Filename: "{app}\launcher.bat"; IconFilename: "{app}\assets\DocMind.ico"; Tasks: desktopicon
Name: "{group}\DocMind";                          Filename: "{app}\launcher.bat"; IconFilename: "{app}\assets\DocMind.ico"; Tasks: startmenuicon
Name: "{group}\Uninstall DocMind";                Filename: "{uninstallexe}"

; ── Run install_helper.bat after copying files ───────────────────────────
[Run]
Filename: "{app}\install_helper.bat"; \
    Parameters: """{app}"""; \
    Description: "Setting up DocMind (creating environment, installing packages, downloading AI models)..."; \
    Flags: runhidden waituntilterminated; \
    StatusMsg: "Installing Python packages and downloading AI models. This may take 15-30 minutes..."

; Launch app after install (optional checkbox on finish page)
Filename: "{app}\launcher.bat"; \
    Description: "Launch DocMind now"; \
    Flags: postinstall nowait skipifsilent

; ── Uninstall — remove everything ────────────────────────────────────────
[UninstallRun]
Filename: "taskkill"; Parameters: "/F /IM python.exe";   Flags: runhidden; RunOnceId: "KillPython"
Filename: "taskkill"; Parameters: "/F /IM qdrant.exe";   Flags: runhidden; RunOnceId: "KillQdrant"
Filename: "taskkill"; Parameters: "/F /IM ollama.exe";   Flags: runhidden; RunOnceId: "KillOllama"

[UninstallDelete]
Type: filesandordirs; Name: "{app}\env"
Type: filesandordirs; Name: "{app}\vector_store"
Type: filesandordirs; Name: "{app}\logs"
Type: filesandordirs; Name: "{app}\uploads"
Type: filesandordirs; Name: "{app}\snapshots"
Type: filesandordirs; Name: "{app}\.env"
Type: filesandordirs; Name: "{app}\install_log.txt"

; ============================================================
;  Pascal Script — dependency checks + downloads
;  Runs BEFORE files are copied (PrepareToInstall phase)
; ============================================================
[Code]

// ── Globals ─────────────────────────────────────────────────────────────
var
  NeedPython  : Boolean;
  NeedMongo   : Boolean;
  NeedOllama  : Boolean;
  DepPage     : TWizardPage;
  DepLabel    : TLabel;

// ── Helper: run a command and return exit code ──────────────────────────
function ExecAndWait(Cmd, Params: String): Integer;
var
  ResultCode: Integer;
begin
  Exec(Cmd, Params, '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Result := ResultCode;
end;

// ── Helper: download a file via PowerShell ──────────────────────────────
function DownloadFile(URL, DestPath: String): Boolean;
var
  PS, Params: String;
  ResultCode: Integer;
begin
  PS     := ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe');
  Params := Format('-NoProfile -NonInteractive -Command "' +
    '$ProgressPreference=''SilentlyContinue''; ' +
    'Invoke-WebRequest -Uri ''%s'' -OutFile ''%s'' -UseBasicParsing"',
    [URL, DestPath]);
  Exec(PS, Params, '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Result := (ResultCode = 0) and FileExists(DestPath);
end;

// ── Check: Python 3.11+ installed ───────────────────────────────────────
function PythonInstalled(): Boolean;
var
  PythonPath: String;
begin
  Result := False;
  // Check registry for Python 3.11 (user install)
  if RegQueryStringValue(HKCU, 'Software\Python\PythonCore\3.11\InstallPath', '', PythonPath) then
    Result := FileExists(PythonPath + '\python.exe');
  // Check registry for Python 3.11 (machine install)
  if not Result then
    if RegQueryStringValue(HKLM, 'Software\Python\PythonCore\3.11\InstallPath', '', PythonPath) then
      Result := FileExists(PythonPath + '\python.exe');
  // Check registry for Python 3.12
  if not Result then
    if RegQueryStringValue(HKCU, 'Software\Python\PythonCore\3.12\InstallPath', '', PythonPath) then
      Result := FileExists(PythonPath + '\python.exe');
  if not Result then
    if RegQueryStringValue(HKLM, 'Software\Python\PythonCore\3.12\InstallPath', '', PythonPath) then
      Result := FileExists(PythonPath + '\python.exe');
  // Fallback: check PATH
  if not Result then
    Result := (ExecAndWait(ExpandConstant('{sys}\cmd.exe'),
      '/C python --version >nul 2>&1') = 0);
end;

// ── Check: MongoDB service running / installed ──────────────────────────
function MongoInstalled(): Boolean;
var
  ResultCode: Integer;
begin
  // Check if MongoDB service exists
  Exec(ExpandConstant('{sys}\sc.exe'), 'query MongoDB', '', SW_HIDE,
    ewWaitUntilTerminated, ResultCode);
  Result := (ResultCode = 0);
  // Also check common install path
  if not Result then
    Result := DirExists('C:\Program Files\MongoDB\Server');
end;

// ── Check: Ollama installed ──────────────────────────────────────────────
function OllamaInstalled(): Boolean;
begin
  Result := FileExists(ExpandConstant('{localappdata}\Programs\Ollama\ollama.exe'))
         or FileExists('C:\Program Files\Ollama\ollama.exe')
         or (ExecAndWait(ExpandConstant('{sys}\cmd.exe'),
             '/C where ollama >nul 2>&1') = 0);
end;

// ── Custom page: dependency status ──────────────────────────────────────
procedure CreateDepPage();
begin
  DepPage := CreateCustomPage(wpWelcome, 'Checking Requirements',
    'DocMind is checking your system for required software...');

  DepLabel := TLabel.Create(DepPage);
  DepLabel.Parent := DepPage.Surface;
  DepLabel.Left   := 0;
  DepLabel.Top    := 0;
  DepLabel.Width  := DepPage.SurfaceWidth;
  DepLabel.Height := 300;
  DepLabel.WordWrap := True;
  DepLabel.Caption := 'Scanning system...';
end;

// ── InitializeWizard — build UI ──────────────────────────────────────────
procedure InitializeWizard();
begin
  CreateDepPage();
end;

// ── NextButtonClick — run checks when user hits Next on dep page ─────────
function NextButtonClick(CurPageID: Integer): Boolean;
var
  Status: String;
begin
  Result := True;

  if CurPageID = DepPage.ID then
  begin
    // ── Run all checks ──────────────────────────────────────────────────
    WizardForm.NextButton.Enabled := False;
    DepLabel.Caption := 'Checking Python 3.11...';

    NeedPython := not PythonInstalled();
    NeedMongo  := not MongoInstalled();
    NeedOllama := not OllamaInstalled();

    // ── Build status report ─────────────────────────────────────────────
    Status := 'System Check Results:' + #13#10 + #13#10;

    if NeedPython then
      Status := Status + '  [WILL INSTALL]  Python 3.11.9' + #13#10
    else
      Status := Status + '  [OK]            Python (already installed)' + #13#10;

    if NeedMongo then
      Status := Status + '  [WILL INSTALL]  MongoDB 8.0' + #13#10
    else
      Status := Status + '  [OK]            MongoDB (already installed)' + #13#10;

    if NeedOllama then
      Status := Status + '  [WILL INSTALL]  Ollama (AI model server)' + #13#10
    else
      Status := Status + '  [OK]            Ollama (already installed)' + #13#10;

    Status := Status + #13#10;
    Status := Status + '  [WILL INSTALL]  Python packages (from requirements.txt)' + #13#10;
    Status := Status + '  [WILL DOWNLOAD] AI model: bge-m3  (~670 MB)' + #13#10;
    Status := Status + '  [WILL DOWNLOAD] AI model: llama3.1 (~4.7 GB)' + #13#10;
    Status := Status + #13#10;
    Status := Status + 'Total estimated download: 5-7 GB' + #13#10;
    Status := Status + 'Estimated time: 15-45 minutes depending on internet speed.' + #13#10;
    Status := Status + #13#10;
    Status := Status + 'Click Next to begin installation.';

    DepLabel.Caption := Status;
    WizardForm.NextButton.Enabled := True;
  end;
end;

// ── PrepareToInstall — download & silently install missing deps ──────────
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  TempDir   : String;
  FilePath  : String;
  ResultCode: Integer;
begin
  Result   := '';
  TempDir  := ExpandConstant('{tmp}');

  // ── Install Python 3.11 ────────────────────────────────────────────────
  if NeedPython then
  begin
    WizardForm.StatusLabel.Caption := 'Downloading Python 3.11.9...';
    FilePath := TempDir + '\python_installer.exe';

    if not DownloadFile('{#PythonURL}', FilePath) then
    begin
      Result := 'Failed to download Python 3.11.9. ' +
                'Please check your internet connection and try again.';
      Exit;
    end;

    WizardForm.StatusLabel.Caption := 'Installing Python 3.11.9...';
    // Silent install: add to PATH, install for all users
    Exec(FilePath,
      '/quiet InstallAllUsers=1 PrependPath=1 Include_test=0 Include_doc=0',
      '', SW_HIDE, ewWaitUntilTerminated, ResultCode);

    if ResultCode <> 0 then
    begin
      Result := 'Python installation failed (exit code: ' +
                IntToStr(ResultCode) + '). ' +
                'Please install Python 3.11 manually from python.org and re-run this installer.';
      Exit;
    end;
  end;

  // ── Install MongoDB ────────────────────────────────────────────────────
  if NeedMongo then
  begin
    WizardForm.StatusLabel.Caption := 'Downloading MongoDB 8.0...';
    FilePath := TempDir + '\mongodb_installer.msi';

    if not DownloadFile('{#MongoURL}', FilePath) then
    begin
      Result := 'Failed to download MongoDB. ' +
                'Please check your internet connection and try again.';
      Exit;
    end;

    WizardForm.StatusLabel.Caption := 'Installing MongoDB 8.0...';
    // Silent install: install as service, no compass
    Exec(ExpandConstant('{sys}\msiexec.exe'),
      '/i "' + FilePath + '" /quiet /norestart ' +
      'ADDLOCAL="ServerService" ' +
      'SHOULD_INSTALL_COMPASS=0 ' +
      'SERVICENAME=MongoDB ' +
      'SERVICEUSER=LocalSystem',
      '', SW_HIDE, ewWaitUntilTerminated, ResultCode);

    if (ResultCode <> 0) and (ResultCode <> 3010) then
    begin
      Result := 'MongoDB installation failed (exit code: ' +
                IntToStr(ResultCode) + '). ' +
                'Please install MongoDB Community manually from mongodb.com and re-run.';
      Exit;
    end;

    // Start MongoDB service
    Exec(ExpandConstant('{sys}\net.exe'), 'start MongoDB',
      '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  end;

  // ── Install Ollama ─────────────────────────────────────────────────────
  if NeedOllama then
  begin
    WizardForm.StatusLabel.Caption := 'Downloading Ollama...';
    FilePath := TempDir + '\OllamaSetup.exe';

    if not DownloadFile('{#OllamaURL}', FilePath) then
    begin
      Result := 'Failed to download Ollama. ' +
                'Please check your internet connection and try again.';
      Exit;
    end;

    WizardForm.StatusLabel.Caption := 'Installing Ollama...';
    // Ollama installer is silent by default
    Exec(FilePath, '/S', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);

    if ResultCode <> 0 then
    begin
      Result := 'Ollama installation failed (exit code: ' +
                IntToStr(ResultCode) + '). ' +
                'Please install Ollama manually from ollama.com and re-run.';
      Exit;
    end;
  end;

  WizardForm.StatusLabel.Caption := 'Dependencies ready. Installing DocMind...';
end;

// ── CurStepChanged — show helpful message during long install_helper run ─
procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    WizardForm.StatusLabel.Caption :=
      'Installing Python packages and downloading AI models...' + #13#10 +
      'This step takes 15-45 minutes. Please be patient.';
  end;
end;
