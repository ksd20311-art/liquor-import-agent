@echo off
schtasks /Delete /F /TN "LiquorAgent_CollectFx"
schtasks /Delete /F /TN "LiquorAgent_MonthlyAlert"
pause