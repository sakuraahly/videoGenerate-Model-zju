@echo off
rem ============================================================
rem  MiniMax H3 Video Console - unified entry (菜单在 PowerShell 内)
rem  提供：立即生成 / 定时生成 / 延迟生成 / 修改参数 / 环境检查
rem ============================================================
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0shell\console_menu.ps1"
exit /b %errorlevel%
