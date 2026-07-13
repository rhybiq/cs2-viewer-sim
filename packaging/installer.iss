; Inno Setup script for CS2 Viewer Sim -- one installer, two apps: CS2 Viewer
; Sim (video-clip analysis) and CS2 Demo Highlights (CS2 demo-file
; analysis) -- a separate onefile exe/UI (see demo_highlights_app.spec)
; sharing this installer/uninstaller since they're the same overall release.
; Compile with: iscc packaging\installer.iss
; Or with an explicit version (CI does this): iscc /DMyAppVersion=0.1.5 packaging\installer.iss
; Expects both PyInstaller onefile exes already built at dist\CS2ViewerSim.exe
; and dist\CS2DemoHighlights.exe (run packaging\build.ps1 first).

#define MyAppName "CS2 Viewer Sim"
#ifndef MyAppVersion
  #define MyAppVersion "0.0.0-dev"
#endif
#define MyAppExeName "CS2ViewerSim.exe"
#define DemoHighlightsAppName "CS2 Demo Highlights"
#define DemoHighlightsExeName "CS2DemoHighlights.exe"

[Setup]
AppId={{B6C1E6B0-6B7B-4B0D-9B7A-9C2E6F6E7B10}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\dist\installer
OutputBaseFilename=CS2ViewerSim-Setup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}
; Default (CloseApplications=yes) uses RestartManager to detect + auto-close
; anything holding a lock on our exe, then instantly aborts (under
; /VERYSILENT /SUPPRESSMSGBOXES) if even one of those can't be closed -- a
; real self-update failure was traced to exactly this: RestartManager also
; flagged an antivirus process (a transient real-time-scan handle, not an
; actual persistent lock) alongside our own app, couldn't close it, and
; silently rolled back the whole install. Disabling this falls back to the
; plain per-file copy routine, which already retries several times on a
; locked file before giving up -- far more tolerant of a brief AV scan blip
; than an instant abort.
CloseApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional icons:"; Flags: unchecked

[Files]
Source: "..\dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\{#DemoHighlightsExeName}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{#DemoHighlightsAppName}"; Filename: "{app}\{#DemoHighlightsExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent
