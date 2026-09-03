@echo off
chcp 65001 >nul
rem MiniMax H3 生成引擎（bats 分类入口 -> shell\generate_video.ps1）
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\..\shell\generate_video.ps1"
exit /b %errorlevel%