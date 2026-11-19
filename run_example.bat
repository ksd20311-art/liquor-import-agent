@echo off
setlocal
cd /d "%~dp0"
set "PY="
python -c "import sys" >nul 2>nul && set "PY=python"
if not defined PY py -3 -c "import sys" >nul 2>nul && set "PY=py -3"
if not defined PY goto nopython
%PY% -c "import reportlab" >nul 2>nul || (echo Preparing one small helper package, please wait... & %PY% -m pip install -q -r requirements.txt >nul 2>nul)
echo Reproducing the submitted example report (Yamazaki 12, no input needed)...
%PY% src\main.py --input inputs\candidate_whisky.json --sample --out "%~dp0outputs\example"
if errorlevel 1 goto fail
if /i not "%~1"=="nostart" start "" "%~dp0outputs\example\report_yamazaki12.pdf"
echo.
echo Done. To try your own product, double-click run_gui.bat and type a product name, price and country.
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
:fail
echo.
echo Something went wrong. Please read START_HERE.txt (Korean) in this folder.
if /i not "%~1"=="nostart" (start "" notepad "%~dp0START_HERE.txt" & pause)
exit /b 1
