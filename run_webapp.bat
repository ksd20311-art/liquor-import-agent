@echo off
setlocal
cd /d "%~dp0"
set "PY="
python -c "import sys" >nul 2>nul && set "PY=python"
if not defined PY py -3 -c "import sys" >nul 2>nul && set "PY=py -3"
if not defined PY goto nopython
rem Web app (runs on this PC, opens in your browser). First run installs streamlit.
%PY% -c "import streamlit" >nul 2>nul || (echo Installing the web app package ^(streamlit^), this can take a few minutes... & %PY% -m pip install -q -r webapp\requirements.txt)
%PY% -m streamlit run webapp\streamlit_app.py
if errorlevel 1 pause
exit /b 0
:nopython
echo.
echo Python was not found on this PC.
echo  1) Install Python 3.9 or later: https://www.python.org/downloads/
echo  2) On the first installer screen, check "Add python.exe to PATH".
echo  3) Then double-click this file again.
if /i not "%~1"=="nostart" (start "" https://www.python.org/downloads/ & start "" notepad "%~dp0START_HERE.txt" & pause)
exit /b 1