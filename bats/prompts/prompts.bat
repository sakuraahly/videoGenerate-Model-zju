@echo off
chcp 65001 >nul
rem 提示词快捷编辑（bats\prompts\prompts.bat -> shell\prompts_console.ps1）
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\..\shell\prompts_console.ps1"
exit /b %errorlevel%