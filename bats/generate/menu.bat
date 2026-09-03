@echo off
chcp 65001 >nul
rem 统一控制台（bats\generate\menu.bat -> shell\console_menu.ps1）
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\..\shell\console_menu.ps1"
exit /b %errorlevel%