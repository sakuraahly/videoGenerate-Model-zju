# ============================================================================
# shell/lib/scheduler.ps1 — 定时/延迟工具
# 纯逻辑（可单测）：把 “HH:MM” 转成下一次运行时刻、格式化剩余时间、倒计时等待。
# ============================================================================

function ConvertTo-NextRunTime {
    <#
    .SYNOPSIS 把 24 小时制 "HH:MM"（或 "H:MM"）解析为今天/明天最近一次运行时刻。
    .RETURNS [datetime]；无法解析返回 $null。
    #>
    param([string]$Time)
    $t = ([string]$Time).Trim()
    if (-not $t) { return $null }
    $parts = $t -split ':'
    if ($parts.Count -lt 1 -or $parts.Count -gt 2) { return $null }
    $hourText = $parts[0].Trim()
    $minText = if ($parts.Count -ge 2) { $parts[1].Trim() } else { '0' }
    $hour = 0; $minute = 0
    if (-not [int]::TryParse($hourText, [ref]$hour)) { return $null }
    if (-not [int]::TryParse($minText, [ref]$minute)) { return $null }
    if ($hour -lt 0 -or $hour -gt 23 -or $minute -lt 0 -or $minute -gt 59) { return $null }

    $now = Get-Date
    $target = Get-Date -Year $now.Year -Month $now.Month -Day $now.Day `
        -Hour $hour -Minute $minute -Second 0 -Millisecond 0
    # 已过（含不足 1 分钟）则顺延到明天
    if ($target -le $now.AddMinutes(1)) {
        $target = $target.AddDays(1)
    }
    return $target
}

function Format-Duration {
    param([double]$Seconds)
    $t = [timespan]::FromSeconds([math]::Max(0, $Seconds))
    return ('{0:00}:{1:00}:{2:00}' -f [int]$t.TotalHours, $t.Minutes, $t.Seconds)
}

function Start-Countdown {
    <#
    .SYNOPSIS 阻塞直到 $Target，期间每 60 秒打印一次剩余时间（HH:MM:SS）。
    #>
    param([datetime]$Target)
    $now = Get-Date
    if ($Target -le $now) { return }
    Write-Info "计划执行时间: $($Target.ToString('yyyy-MM-dd HH:mm:ss'))"
    Write-Info '倒计时中…… 如需取消请按 Ctrl+C。'
    while ($true) {
        $now = Get-Date
        $remain = ($Target - $now).TotalSeconds
        if ($remain -le 0) { break }
        $sleep = [int][math]::Min(60, [math]::Ceiling($remain))
        Write-Host ("  剩余 {0}" -f (Format-Duration -Seconds $remain))
        Start-Sleep -Seconds $sleep
    }
    Write-Info '时间到，开始执行！'
}
