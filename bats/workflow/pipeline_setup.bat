@echo off
chcp 65001 >nul
rem 流水线/多工作流设置（默认阶段/模板状态/校验）
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\..\shell\pipeline_setup.ps1"
exit /b %errorlevel%