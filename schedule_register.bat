@echo off
setlocal
rem Registers two Windows scheduled tasks for the current user:
rem   - every Monday 09:00  : collect weekly customs FX rates   (run_collect_fx.bat)
rem   - 1st of month 09:10  : monthly change alert report       (run_watch.bat)
schtasks /Create /F /SC WEEKLY /D MON /ST 09:00 /TN "LiquorAgent_CollectFx" /TR "\"%~dp0run_collect_fx.bat\" nostart"
schtasks /Create /F /SC MONTHLY /D 1 /ST 09:10 /TN "LiquorAgent_MonthlyAlert" /TR "\"%~dp0run_watch.bat\" nostart"
echo.
echo Done. To remove them later, run schedule_remove.bat
pause