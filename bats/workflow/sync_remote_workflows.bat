@echo off
chcp 65001 >nul
rem 同步 spark 的 6 个工作流到本地镜像 workflows\remote_workflows
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\..\shell\sync_remote_workflows.ps1"
pause