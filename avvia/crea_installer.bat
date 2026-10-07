@echo off
rem Crea installer\MusicDownloader-Setup.exe dalla cartella dist\MusicDownloader (prima: avvia\build_exe.bat).
rem Richiede Inno Setup 6 (winget install -e --id JRSoftware.InnoSetup).
cd /d "%~dp0.."

if not exist "dist\MusicDownloader\MusicDownloader.exe" (
  echo Manca dist\MusicDownloader\MusicDownloader.exe: lancia prima avvia\build_exe.bat
  pause
  exit /b 1
)

set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" (
  echo Inno Setup 6 non trovato. Installalo con: winget install -e --id JRSoftware.InnoSetup
  pause
  exit /b 1
)

"%ISCC%" /Q "avvia\installer.iss"
if errorlevel 1 (echo Compilazione fallita. & pause & exit /b 1)
echo Creato installer\MusicDownloader-Setup.exe
pause
