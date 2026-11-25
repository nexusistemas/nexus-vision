; =============================================================================
; Instalador Windows — Nexus Vision (NexuSistemas Tecnologia)
; Gerado automaticamente por desktop-app/build_installer.py
; =============================================================================

#define MyAppName "Nexus Vision"
#define MyAppVersion "1.0.5"
#define MyAppPublisher "NexuSistemas Tecnologia"
#define MyAppURL "https://vision.nexusistemas.app.br"
#define MyAppExeName "NexusVision.exe"

[Setup]
AppId={{7B4F91D2-9C35-4D8E-A123-8E55F4A0E911}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} v{#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\NexuSistemas\{#MyAppName}
DefaultGroupName=NexuSistemas\{#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=C:\Users\Guilh\OneDrive\Área de Trabalho\nexus vision\Output
OutputBaseFilename=NexusVision_Setup_v1.0.5
SetupIconFile=C:\Users\Guilh\OneDrive\Área de Trabalho\nexus vision\desktop-app\assets\nexus_vision.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar atalho na Área de Trabalho (Nexus Vision)"; GroupDescription: "Atalhos e Inicialização:"
Name: "autostart"; Description: "Iniciar o Nexus Vision automaticamente com o Windows (Recomendado para Portaria)"; GroupDescription: "Atalhos e Inicialização:"

[Files]
Source: "C:\Users\Guilh\OneDrive\Área de Trabalho\nexus vision\desktop-app\dist\NexusVision\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\_internal\assets\nexus_vision.ico"
Name: "{group}\Desinstalar {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\_internal\assets\nexus_vision.ico"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "NexusVision"; ValueData: """{app}\{#MyAppExeName}"""; Flags: uninsdeletevalue; Tasks: autostart

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Iniciar o {#MyAppName} agora"; Flags: nowait postinstall skipifsilent
