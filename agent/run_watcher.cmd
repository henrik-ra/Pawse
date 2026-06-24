@echo off
REM ─────────────────────────────────────────────────────────────────────────
REM  Pawse unified agent — continuous background run (windowless via pyw).
REM
REM  Pushes the live day (real meetings + wearable) AND analyses any new Teams
REM  recordings (voice + facial expression) on every poll.
REM
REM  Easiest "run at login": press Win+R, type  shell:startup , and drop a
REM  shortcut to THIS file in the folder that opens.
REM
REM  Point it at your dashboard once (persists across reboots):
REM      setx PAWSE_API_URL "https://<your-container-app>"
REM ─────────────────────────────────────────────────────────────────────────
if "%PAWSE_API_URL%"=="" set "PAWSE_API_URL=http://localhost:8000"
pyw "%~dp0pawse_agent.py" --interval 900
