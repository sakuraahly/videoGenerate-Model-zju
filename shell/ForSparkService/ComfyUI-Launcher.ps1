# ComfyUI-Launcher.ps1
# 交互式菜单：管理 spark ComfyUI 的连接（启动/停止/浏览器）。
# 注意：所有子脚本用 $PSScriptRoot 绝对定位，勿用相对路径（cwd 不可靠）。

$RemoteHost = "spark"
$LocalPort = 8188
$StartScript = Join-Path $PSScriptRoot 'Start-ComfyUI.ps1'
$StopScript = Join-Path $PSScriptRoot 'Stop-ComfyUI.ps1'

function Show-Menu {
    Clear-Host
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host "      ComfyUI 远程服务管理器      " -ForegroundColor Cyan
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host "当前目标: $RemoteHost (端口 $LocalPort)"
    Write-Host ""
    Write-Host "[1] 🚀 启动连接 (Start ComfyUI & Tunnel)"
    Write-Host "[2] 🛑 断开连接 (Stop Tunnel & Service)"
    Write-Host "[3] 🌐 仅打开浏览器 (Open Browser)"
    Write-Host "[0] ❌ 退出 (Exit)"
    Write-Host "========================================"
}

if (-not (Test-Path -LiteralPath $StartScript)) {
    Write-Host "[错误] 找不到 $StartScript" -ForegroundColor Red
    exit 1
}

while ($true) {
    Show-Menu
    $userChoice = Read-Host "请输入选项 (0-3)"

    switch ($userChoice) {
        '1' {
            Write-Host "`n正在执行启动脚本..." -ForegroundColor Yellow
            & $StartScript -RemoteHost $RemoteHost -LocalPort $LocalPort
            Write-Host "`n按任意键返回菜单..."
            $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
        }
        '2' {
            Write-Host "`n正在执行关闭脚本..." -ForegroundColor Yellow
            & $StopScript -RemoteHost $RemoteHost -LocalPort $LocalPort
            Write-Host "`n按任意键返回菜单..."
            $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
        }
        '3' {
            Write-Host "`n正在打开浏览器..." -ForegroundColor Yellow
            Start-Process "http://localhost:${LocalPort}"
            Start-Sleep -Seconds 1
        }
        '0' {
            Write-Host "再见！" -ForegroundColor Green
            exit 0
        }
        default {
            Write-Host "无效的选项，请重试。" -ForegroundColor Red
            Start-Sleep -Seconds 1
        }
    }
}
