@echo off
rem Crea dist\MusicDownloader\MusicDownloader.exe (cartella standalone, senza Python).
rem Richiede: pip install pyinstaller  e  ffmpeg.exe + ffprobe.exe in FFMPEG_SRC.
cd /d "%~dp0.."
set FFMPEG_SRC=C:\Program Files\ffmpeg\bin

python -m PyInstaller --noconfirm --clean --windowed --name MusicDownloader ^
  --collect-all customtkinter ^
  --collect-submodules yt_dlp ^
  --add-binary "%FFMPEG_SRC%\ffmpeg.exe;ffmpeg" ^
  --add-binary "%FFMPEG_SRC%\ffprobe.exe;ffmpeg" ^
  music_downloader.py
pause
