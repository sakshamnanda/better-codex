@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0windows\Select-Deployment.ps1" -Mode Keys
if errorlevel 1 pause
