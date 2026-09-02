@echo off
rem ============================================================
rem  Workflow setup tool (upload path + use-a-saved-workflow)
rem  工作流上传 / 使用指定工作流 设置入口（双击运行）
rem ============================================================
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0shell\transfer_setup.ps1"
exit /b %errorlevel%
