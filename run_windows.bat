@echo off
setlocal
cd /d "%~dp0"
if not exist .venv (py -m venv .venv)
call .venv\Scripts\activate.bat
python -m pip install -r requirements-ui.txt
python -m streamlit run app.py
pause
