
#define MyApp "AeroEscuela"
[Setup]
AppId={{6E4F5A21-6B5C-4F2B-9A0D-AE5C0E5C1A01}
AppName=AeroEscuela
AppVersion=1.3.0
AppPublisher=AeroEscuela
DefaultDirName={autopf}\AeroEscuela
DefaultGroupName=AeroEscuela
SourceDir=..
OutputDir=dist
OutputBaseFilename=AeroEscuela_Instalador
SetupIconFile=assets\icono.ico
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "es"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "Crear un acceso directo en el escritorio"; GroupDescription: "Accesos directos:"

[Files]
Source: "dist\AeroEscuela\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\AeroEscuela"; Filename: "{app}\AeroEscuela.exe"
Name: "{group}\Desinstalar AeroEscuela"; Filename: "{uninstallexe}"
Name: "{autodesktop}\AeroEscuela"; Filename: "{app}\AeroEscuela.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\AeroEscuela.exe"; Description: "Abrir AeroEscuela ahora"; Flags: nowait postinstall skipifsilent
