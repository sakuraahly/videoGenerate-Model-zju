@echo off
chcp 65001 >nul
title 停止 Spark Qwen 服务
rem 远程停止 Spark 上的 Qwen 三件套（SGLang / Qwen-Agent / Open WebUI）
rem 不碰 ComfyUI（bats\service\StopQwen.bat）

if "%~1"=="--status" (
    echo === 查看 Spark 服务状态 ===
    ssh spark "bash ~/videoGenerate-Model-zju/shell/stop_qwen.sh --status"
    goto :done
)

echo === 停止 Spark 上的 Qwen 服务（保留 ComfyUI）===
echo.
ssh spark "bash ~/videoGenerate-Model-zju/shell/stop_qwen.sh"

:done
if errorlevel 1 (
    echo.
    echo [错误] 远程执行失败，请检查 SSH 连接。
    pause
)
exit /b %errorlevel%
