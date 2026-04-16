@echo off
cd /d "%~dp0prog"
start http://127.0.0.1:5000
python app.py
pause