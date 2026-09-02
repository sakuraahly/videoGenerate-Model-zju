<#
.SYNOPSIS
    定时/延迟执行生成流程：先预检（本地文件、远程连通、模型就位），
    通过后倒计时等待，到点自动调用 shell\generate_video.ps1 执行完整流程。

.PARAMETER AtTime
    24 小时制 "HH:MM"。若时刻已过则顺延到明天。
.PARAMETER DelayMinutes
    从当前时间起延迟多少分钟后开始（可与 AtTime 二选一，AtTime 优先）。

示例（由 bat 调用，无需手工使用）：
  powershell -ExecutionPolicy Bypass -File run_scheduled.ps1 -AtTime "21:30"
  powershell -ExecutionPolicy Bypass -File run_scheduled.ps1 -DelayMinutes 10
#>
param(
    [string]$AtTime = '',
    [double]$DelayMinutes = 0
)

$ErrorActionPreference = 'Continue'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path          # shell\
$ProjectRoot = Split-Path -Parent $here                          # 项目根
. (Join-Path $here 'lib\utils.ps1')
. (Join-Path $here 'lib\scheduler.ps1')
. (Join-Path $here 'lib\preflight.ps1')

$envCfg = Read-EnvConfig -Path (Join-Path $ProjectRoot 'config\environment.json')
$RemoteHost = [string]$envCfg.remote_host
$ModelsRoot = "$([string]$envCfg.remote_comfyui_dir)/models"

# ---------------- 计算目标时刻 ----------------
$target = $null
if ($AtTime) {
    $target = ConvertTo-NextRunTime -Time $AtTime
    if ($null -eq $target) {
        Write-ErrorExit "无法解析计划时间 '$AtTime'。请使用 24 小时制 HH:MM（如 21:30）。"
    }
}
elseif ($DelayMinutes -gt 0) {
    $target = (Get-Date).AddMinutes($DelayMinutes)
}
else {
    Write-ErrorExit '缺少参数：请提供 -AtTime "HH:MM" 或 -DelayMinutes N。'
}

# ---------------- 前置预检（尽早暴露问题，避免白等） ----------------
Write-Info '执行前置检查...'
if (-not (Assert-PreflightBasics -ProjectRoot $ProjectRoot)) {
    Write-ErrorExit '本地前置检查未通过。请先通过“统一控制台”的 [5] 环境检查修复后，再重新定时。'
}
if (-not (Test-RemoteReachable -RemoteHost $RemoteHost)) {
    Write-ErrorExit "远程主机 $RemoteHost 不可达（ssh 失败）。请确认网络/免密登录后再重新定时。"
}
$manifest = Get-ModelManifest -ProjectRoot $ProjectRoot
if ($manifest) {
    $status = Get-RemoteModelStatus -RemoteHost $RemoteHost -ModelsRoot $ModelsRoot -Manifest $manifest
    $missing = @($status | Where-Object { -not $_.Ok })
    if ($missing.Count -gt 0) {
        Write-Warn "远程缺少/损坏的模型文件（${missing.Count} 个），已取消本次定时任务："
        foreach ($m in $missing) { Write-Warn "  - $($m.Name)" }
        Write-ErrorExit '请先在“统一控制台”选择 [5] 环境与模型检查 下载补齐模型，再重新定时。'
    }
}

# ---------------- 倒计时并执行 ----------------
Write-Info '预检通过。'
Start-Countdown -Target $target

$generate = Join-Path $here 'generate_video.ps1'
Write-Info "开始执行完整生成流程: $generate"
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $generate
$code = $LASTEXITCODE
Write-Info "生成流程结束（退出码 $code）。"
exit $code
