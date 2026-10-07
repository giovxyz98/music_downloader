@echo off
rem Disinstalla Music Downloader: cancella i collegamenti (Desktop e menu Start), i dati in
rem %APPDATA%\MusicDownloader (config, cache, log) e i file del programma. NON tocca la musica scaricata.
rem Si trova nella cartella del programma. Con il parametro --si salta la domanda di conferma.
setlocal

rem --- seconda fase: gira dalla copia in %TEMP% (un .bat non puo' cancellare la propria cartella) ---
if /i "%~1"=="--esegui" goto esegui

set "APPDIR=%~dp0"
if "%APPDIR:~-1%"=="\" set "APPDIR=%APPDIR:~0,-1%"

if not exist "%APPDIR%\MusicDownloader.exe" (
  echo Non trovo MusicDownloader.exe in "%APPDIR%": questa non sembra la cartella del programma. Annullato.
  pause
  exit /b 1
)
tasklist /fi "imagename eq MusicDownloader.exe" 2>nul | "%SystemRoot%\System32\find.exe" /i "MusicDownloader.exe" >nul
if not errorlevel 1 (
  echo Music Downloader e' in esecuzione: chiudilo e riprova.
  pause
  exit /b 1
)

echo Verra' rimosso Music Downloader:
echo   programma : %APPDIR%
echo   dati      : %APPDATA%\MusicDownloader  (config, cache, log)
echo   collegamenti sul Desktop e nel menu Start
echo La musica scaricata non viene toccata.
echo.
if /i not "%~1"=="--si" (
  choice /c SN /n /m "Procedere? [S/N] "
  if errorlevel 2 exit /b 0
)

copy /y "%~f0" "%TEMP%\md_disinstalla.bat" >nul
start "" cmd /c ""%TEMP%\md_disinstalla.bat" --esegui "%APPDIR%" "%~1""
exit /b 0

:esegui
set "APPDIR=%~2"
rem fuori dalla cartella del programma, altrimenti Windows non la lascia cancellare
cd /d "%TEMP%"
rem lascia il tempo alla prima fase di chiudersi
ping -n 3 127.0.0.1 >nul

powershell -NoProfile -Command "foreach($d in 'Desktop','Programs'){ $p=Join-Path ([Environment]::GetFolderPath($d)) 'Music Downloader.lnk'; if(Test-Path -LiteralPath $p){ Remove-Item -LiteralPath $p -Force; 'rimosso collegamento: ' + $p } }"

rem Windows annota da solo i collegamenti del menu Start in HKCU (Start\TileProperties): si tolgono quelle del programma
powershell -NoProfile -Command "$k='HKCU:\Software\Microsoft\Windows\CurrentVersion\Start\TileProperties'; if(Test-Path $k){ Get-ChildItem $k | Where-Object { $_.PSChildName -like ('*' + [WildcardPattern]::Escape($env:APPDIR) + '*') } | Remove-Item -Recurse -Force }"

if exist "%APPDATA%\MusicDownloader" (
  rd /s /q "%APPDATA%\MusicDownloader"
  echo rimossi i dati: %APPDATA%\MusicDownloader
)

rem si cancella solo cio' che l'installer ha messo, poi la cartella se resta vuota
rem (se avevi aggiunto altri file nella cartella del programma, vengono lasciati)
if exist "%APPDIR%\_internal" rd /s /q "%APPDIR%\_internal"
del /f /q "%APPDIR%\MusicDownloader.exe" "%APPDIR%\Disinstalla.bat" 2>nul
rd "%APPDIR%" 2>nul
if exist "%APPDIR%" (echo La cartella "%APPDIR%" non e' stata rimossa: contiene altri file o e' in uso.) else (echo rimossa la cartella: %APPDIR%)

echo.
echo Music Downloader e' stato disinstallato.
if /i not "%~3"=="--si" pause
(goto) 2>nul & del /f /q "%~f0"
