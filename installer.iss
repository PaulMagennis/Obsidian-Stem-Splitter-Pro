; Inno Setup 6 Script for Obsidian Stem Splitter Pro
; Creates a standard Windows Setup Installer (.exe) with desktop icons, start menu, and uninstaller.

#define MyAppName "Obsidian Stem Splitter Pro"
#define MyAppVersion "2.0.0"
#define MyAppPublisher "Obsidian Project"
#define MyAppExeName "ObsidianStemSplitterPro.exe"
#define SourceAppDir "dist\ObsidianStemSplitterPro"
#define UserProfile GetEnv('USERPROFILE')

[Setup]
AppId={{D8A6891B-54F2-4F8A-98C1-F09D73A6B431}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} v{#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\Obsidian Stem Splitter Full Installer
OutputBaseFilename=Obsidian_Stem_Splitter_Pro_Setup
SetupIconFile=assets\app_icon.ico
WizardImageFile=assets\installer_sidebar.bmp
WizardSmallImageFile=assets\installer_small.bmp
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
DisableWelcomePage=no
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
UninstallDisplayIcon={app}\assets\app_icon.ico
VersionInfoVersion=2.0.0.0
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription={#MyAppName} Setup Wizard
VersionInfoProductName={#MyAppName}
VersionInfoProductVersion=2.0.0.0

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "{#SourceAppDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#UserProfile}\.cache\huggingface\hub\models--adefossez--HTDemucs-6s\*"; DestDir: "{%USERPROFILE}\.cache\huggingface\hub\models--adefossez--HTDemucs-6s"; Flags: ignoreversion recursesubdirs createallsubdirs skipifsourcedoesntexist

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\assets\app_icon.ico"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\assets\app_icon.ico"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Classes\*\shell\ObsidianStemSplitter"; ValueType: string; ValueName: ""; ValueData: "Separate Stems with Obsidian Stem Splitter Pro"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\*\shell\ObsidianStemSplitter"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\assets\app_icon.ico"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\*\shell\ObsidianStemSplitter\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" ""%1"""; Flags: uninsdeletekey

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent
