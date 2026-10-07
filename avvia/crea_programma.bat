@echo off
rem Crea l'exe standalone (senza Python) oppure l'installer, a scelta.
rem   1) solo exe:  dist\MusicDownloader\MusicDownloader.exe (cancella build\ e il .spec)
rem   2) installer: installer\MusicDownloader-Setup.exe (poi cancella build\, dist\ e il .spec)
rem Richiede: pip install pyinstaller  e  ffmpeg.exe + ffprobe.exe in FFMPEG_SRC.
rem Per l'installer serve anche Inno Setup 6 (winget install -e --id JRSoftware.InnoSetup).
cd /d "%~dp0.."
set FFMPEG_SRC=C:\Program Files\ffmpeg\bin

echo.
echo Cosa vuoi creare?
echo   1) Solo l'exe   (dist\MusicDownloader\MusicDownloader.exe)
echo   2) L'installer  (installer\MusicDownloader-Setup.exe)
choice /c 12 /n /m "Scelta [1/2]: "
if errorlevel 2 goto installer

:solo_exe
call :pyinstaller
if errorlevel 1 (echo Build fallito. & pause & exit /b 1)
rmdir /s /q "build" 2>nul
del /q "MusicDownloader.spec" 2>nul
echo Creato dist\MusicDownloader\MusicDownloader.exe
pause
exit /b 0

:installer
rem Inno Setup si cerca prima del build, cosi' se manca non si perde tempo con PyInstaller.
set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" goto manca_inno

call :pyinstaller
if errorlevel 1 (echo Build fallito. & pause & exit /b 1)

"%ISCC%" /Q "avvia\installer.iss"
if errorlevel 1 (echo Compilazione dell'installer fallita: build e dist restano per riprovare. & pause & exit /b 1)

rmdir /s /q "build" 2>nul
rmdir /s /q "dist" 2>nul
del /q "MusicDownloader.spec" 2>nul
echo Creato installer\MusicDownloader-Setup.exe
echo Cancellati build, dist e MusicDownloader.spec.
pause
exit /b 0

:manca_inno
echo Inno Setup 6 non trovato. Installalo con: winget install -e --id JRSoftware.InnoSetup
pause
exit /b 1

:pyinstaller
python -m PyInstaller --noconfirm --clean --windowed --name MusicDownloader ^
  --collect-all customtkinter ^
  --collect-submodules yt_dlp ^
  --add-binary "%FFMPEG_SRC%\ffmpeg.exe;ffmpeg" ^
  --add-binary "%FFMPEG_SRC%\ffprobe.exe;ffmpeg" ^
  music_downloader.py
exit /b %errorlevel%
