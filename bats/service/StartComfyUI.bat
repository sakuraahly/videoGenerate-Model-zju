@echo off
chcp 65001 >nul
title ComfyUI 远程服务管理器
rem 启动远程 ComfyUI / 隧道 / 浏览器（bats\service\StartComfyUI.bat）
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\..\shell\ForSparkService\ComfyUI-Launcher.ps1"
if errorlevel 1 (
  echo.
  echo [错误] ComfyUI 管理器退出异常，请查看上方日志。
  pause
)
exit /b %errorlevel%