@echo off
chcp 65001 >nul
rem 运行形态切换（bats\config\mode.bat -> shell\deploy_mode.ps1）
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\..\shell\deploy_mode.ps1"
exit /b %errorlevel%
