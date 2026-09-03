@echo off
chcp 65001 >nul
rem 工作流上传/使用指定工作流设置
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\..\shell\transfer_setup.ps1"
exit /b %errorlevel%