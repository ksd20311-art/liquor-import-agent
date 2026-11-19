@echo off
setlocal
cd /d "%~dp0"
set "PY="
python -c "import sys" >nul 2>nul && set "PY=python"
if not defined PY py -3 -c "import sys" >nul 2>nul && set "PY=py -3"
if not defined PY goto nopython
rem Monthly alert: re-calculates registered candidates and opens the alert report (PDF).
%PY% src\watch.py check
if /i not "%~1"=="nostart" pause
exit /b 0
:nopython
echo.
echo Python was not found on this PC.
echo  1) Install Python 3.9 or later: https://www.python.org/downloads/
echo  2) On the first installer screen, check "Add python.exe to PATH".
echo  3) Then double-click this file again.
if /i not "%~1"=="nostart" (start "" https://www.python.org/downloads/ & start "" notepad "%~dp0START_HERE.txt" & pause)
exit /b 1