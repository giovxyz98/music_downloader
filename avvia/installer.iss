; Installer "finto" di Music Downloader: procedura guidata che COPIA i file e crea i collegamenti,
; senza scrivere nel registro e senza registrare il programma in Windows (come i PortableApps).
; Si compila con avvia\crea_installer.bat dopo avvia\build_exe.bat. Disinstallazione: Disinstalla.bat
; (nella cartella del programma), non da "App e funzionalita'".

[Setup]
AppName=Music Downloader
AppVersion=1.0
AppPublisher=Giovanni
DefaultDirName={localappdata}\Programs\MusicDownloader
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
; niente registro: nessun disinstallatore di Inno, nessuna voce in "App e funzionalita'"
Uninstallable=no
CreateUninstallRegKey=no
OutputDir=..\installer
OutputBaseFilename=MusicDownloader-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "it"; MessagesFile: "compiler:Languages\Italian.isl"

[Tasks]
Name: "desktopicon"; Description: "Crea un collegamento sul Desktop"
Name: "startmenuicon"; Description: "Crea un collegamento nel menu Start"; Flags: unchecked

[Files]
Source: "..\dist\MusicDownloader\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "Disinstalla.bat"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{userdesktop}\Music Downloader"; Filename: "{app}\MusicDownloader.exe"; Tasks: desktopicon
Name: "{userprograms}\Music Downloader"; Filename: "{app}\MusicDownloader.exe"; Tasks: startmenuicon

[Run]
Filename: "{app}\MusicDownloader.exe"; Description: "Avvia Music Downloader"; Flags: nowait postinstall skipifsilent
