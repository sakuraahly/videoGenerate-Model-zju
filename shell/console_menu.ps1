<#
.SYNOPSIS
    统一控制台（由 menu.bat 启动）：立即 / 定时 / 延迟生成 + 参数修改 + 环境检查。

.DESCRIPTION
    交互菜单（中文 UI 放在 PowerShell 中，避免 .bat 的中文编码坑）。
    各动作都启动子 powershell.exe 执行对应脚本，异常不会影响菜单本身。
#>
$ErrorActionPreference = 'Continue'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path          # shell\
$ProjectRoot = Split-Path -Parent $here
. (Join-Path $here 'lib\utils.ps1')
. (Join-Path $here 'lib\scheduler.ps1')

$envCfg = Read-EnvConfig -Path (Join-Path $ProjectRoot 'config\environment.json')
$RemoteHost = [string]$envCfg.remote_host
$GenerateScript = Join-Path $here 'generate_video.ps1'
$ScheduledScript = Join-Path $here 'run_scheduled.ps1'
$CheckScript = Join-Path $here 'check_environment.ps1'

function Pause-Back {
    Write-Host ''
    $null = Read-Host '按回车返回主菜单'
}

function Invoke-ConsoleAction {
    param([string]$Title, [string]$ScriptPath, [string[]]$ExtraArgs)
    Write-Info $Title
    $cmd = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $ScriptPath) + $ExtraArgs
    & powershell.exe @cmd
    $code = $LASTEXITCODE
    Write-Host ''
    if ($code -eq 0) { Write-Info "流程结束（成功）。" } else { Write-Warn "流程结束（退出码 $code），请查看上方日志。" }
    Pause-Back
}

function Run-Now { Invoke-ConsoleAction -Title '开始立即生成（进度见下方，请勿关闭窗口）...' -ScriptPath $GenerateScript }

function Run-AtTime {
    while ($true) {
        Write-Host ''
        $at = (Read-Host '请输入计划执行时刻（24 小时制 HH:MM，例如 21:30；直接回车返回菜单）').Trim()
        if (-not $at) { return }
        $target = ConvertTo-NextRunTime -Time $at
        if ($target) {
            Write-Host ''
            Write-Info "已接受计划时刻：$($target.ToString('yyyy-MM-dd HH:mm:ss'))"
            $null = Read-Host '确认无误请按回车开始预检并进入倒计时'
            break
        }
        Write-Warn "无法解析 '$at'，请使用 HH:MM 格式（如 21:30）。"
    }
    Invoke-ConsoleAction -Title '正在预检并等待定时执行（窗口保留即可，到点自动开始）...' `
        -ScriptPath $ScheduledScript -ExtraArgs @('-AtTime', $at)
}

function Run-AfterDelay {
    $mins = 10
    while ($true) {
        Write-Host ''
        $text = (Read-Host '请输入延迟分钟数（直接回车默认 10 分钟；输入 0 返回菜单）').Trim()
        if ($text -eq '') { $mins = 10; break }
        if ($text -eq '0') { return }
        if ([int]::TryParse($text, [ref]$mins) -and $mins -gt 0) { break }
        Write-Warn "分钟数无效：'$text'，请输入正整数。"
    }
    Write-Host ''
    Write-Info "将延迟 ${mins} 分钟后自动执行。"
    Invoke-ConsoleAction -Title '正在预检并延迟执行（窗口保留即可，到点自动开始）...' `
        -ScriptPath $ScheduledScript -ExtraArgs @('-DelayMinutes', "$mins")
}

function Edit-Params {
    Write-Host ''
    Write-Info '打开参数修改工具（edit.bat）...'
    & (Join-Path $ProjectRoot 'edit.bat')
    Pause-Back
}

function Check-Environment {
    Invoke-ConsoleAction -Title '开始环境与远程模型检查（远程不可达时会等待连接超时）...' -ScriptPath $CheckScript
}

function Run-TransferSetup {
    Invoke-ConsoleAction -Title '打开工作流上传 / 使用指定工作流设置...' `
        -ScriptPath (Join-Path $here 'transfer_setup.ps1')
}

# =============================== 主菜单循环 ================================
Write-Host ''
Write-Host ('已加载环境配置：远程主机 = ' + $RemoteHost) -ForegroundColor DarkGray
while ($true) {
    Write-Host ''
    Write-Host '  ============================================================'
    Write-Host '      MiniMax H3 视频生成 - 统一控制台' -ForegroundColor Cyan
    Write-Host '      （立即 / 定时 / 延迟 / 参数 / 环境检查）'
    Write-Host '  ============================================================'
    Write-Host ''
    Write-Host '   [1] 立即生成视频'
    Write-Host '   [2] 定时生成：在指定时刻自动开始（HH:MM，如 21:30）'
    Write-Host '   [3] 延迟生成：N 分钟后自动开始'
    Write-Host '   [4] 修改生成参数（分辨率 / 时长）'
    Write-Host '   [5] 环境与远程模型检查（可自动下载缺失模型）'
    Write-Host '   [6] 工作流上传 / 使用指定工作流（设置远程目录）'
    Write-Host '   [7] 退出'
    Write-Host ''
    $choice = (Read-Host '请选择 (1-7)').Trim()
    switch ($choice) {
        '1' { Run-Now }
        '2' { Run-AtTime }
        '3' { Run-AfterDelay }
        '4' { Edit-Params }
        '5' { Check-Environment }
        '6' { Run-TransferSetup }
        '7' { Write-Host ''; Write-Info '再见！'; return }
        default { Write-Warn "无效选择：'$choice'，请输入 1-7。" }
    }
}
