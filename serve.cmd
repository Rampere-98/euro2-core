@echo off
rem Starts the Euro2 server (API + app) from any folder. Double-click or run in a terminal.
rem Web: http://localhost:8000/app/   Stop: Ctrl+C
cd /d "%~dp0"
uv run python -m euro2core serve
