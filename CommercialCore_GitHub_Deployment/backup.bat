@echo off
setlocal
cd /d "%~dp0"
if not exist backups mkdir backups
powershell -NoProfile -Command "$ts=Get-Date -Format yyyyMMdd_HHmmss; Copy-Item 'data\commercialcore.db' ('backups\commercialcore_'+$ts+'.db')"
echo Backup created in the backups folder.
pause
