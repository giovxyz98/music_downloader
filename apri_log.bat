@echo off
rem Rigenera i dati dal log e apre il viewer nel browser.
cd /d "%~dp0"
python viewer\prepara_log.py || pause
