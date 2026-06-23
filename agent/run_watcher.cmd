@echo off
REM ─────────────────────────────────────────────────────────────────────────
REM  Pawse media watcher — continuous background run (windowless via pyw).
REM
REM  Easiest "run at login": press Win+R, type  shell:startup , and drop a
REM  shortcut to THIS file in the folder that opens. It then watches your Teams
REM  recordings forever and pushes voice + facial-expression signals.
REM
REM  Point it at your dashboard once (persists across reboots):
REM      setx PAWSE_API_URL "https://<your-container-app>"
REM ─────────────────────────────────────────────────────────────────────────
if "%PAWSE_API_URL%"=="" set "PAWSE_API_URL=http://localhost:8000"
pyw "%~dp0recording_watcher.py" --interval 300
