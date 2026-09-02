@echo off
setlocal

REM 获取当前批处理所在目录（即项目根目录）
set "SCRIPT_DIR=%~dp0"

REM 使用 PowerShell 执行脚本，自动绕过执行策略，并隐藏启动横幅
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%shell\generate_video.ps1"

REM 检查上一条命令的退出码，如果不为0则暂停显示错误
if %errorlevel% neq 0 (
    echo.
    echo [错误] 视频生成失败，请查看上方详细信息。
    pause
) else (
    echo.
    echo [完成] 视频生成成功，即将自动关闭窗口。
    timeout /t 3 >nul
)

endlocal