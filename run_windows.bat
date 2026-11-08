@echo off
setlocal
cd /d "%~dp0"
if not exist .venv (py -3 -m venv .venv)
if errorlevel 1 (echo Cannot create Python virtual environment. Install Python 3.11+ & pause & exit /b 1)
call .venv\Scripts\activate.bat
python -m pip install -r requirements-ui.txt
if errorlevel 1 (echo Dependency installation failed & pause & exit /b 1)
python -m streamlit run app.py
if errorlevel 1 (echo Application stopped with an error & pause & exit /b 1)
