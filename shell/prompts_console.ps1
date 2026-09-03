<#
.SYNOPSIS
    工作流提示词向导（bats\prompts\prompts.bat 启动）。
    选择工作流（槽位）→ 查看/记事本/从 default 复制/覆盖新词/追加注入/AI 生成。
    槽位与工作流的映射来自 prompts/manifest.json（动态，勿写死数量）。

非交互参数（供 AI/脚本调用）：
  -Workflow <slot>      例如 video_r2v / default
  -Show                 打印该槽文件状态与内容摘要
  -CopyDefault          用 default 覆盖该槽
  -Set "text"           覆盖写入 positive（negative 留空=回退 default）
  -Append "text"        把新提示词追加注入已有文件（带分隔注释头，保留旧词）
  -Idea "创意"          调 idea2prompts 用本地模型为该槽生成（需 llm.json enabled）
#>
param(
    [string]$Workflow = '',
    [switch]$Show,
    [switch]$CopyDefault,
    [string]$Set = '',
    [string]$Append = '',
    [string]$Idea = ''
)
$ErrorActionPreference = 'Continue'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $here
. (Join-Path $here 'lib\utils.ps1')

$ManifestFile = Join-Path $ProjectRoot 'prompts\manifest.json'

function Read-Manifest {
    try {
        return (Get-Content -LiteralPath $ManifestFile -Raw -Encoding UTF8 | ConvertFrom-Json)
    }
    catch { return $null }
}

function Get-SlotRows {
    $m = Read-Manifest
    if (-not $m) { Write-Warn "无法读取 prompts\manifest.json"; return @() }
    $rows = @()
    $d = $m.default
    $rows += [pscustomobject]@{ Id='default'; Label='默认/内置 T2V（经典模式）';
        Pos=[string]$d.positive; Neg=[string]$d.negative }
    foreach ($p in $m.slots.PSObject.Properties) {
        $s = $m.slots.($p.Name)
        $rows += [pscustomobject]@{ Id=$p.Name; Label=[string]$s.label;
            Pos=[string]$s.positive; Neg=[string]$s.negative }
    }
    return $rows
}

function Get-SlotRow {
    param([string]$Id)
    return (Get-SlotRows | Where-Object { $_.Id -eq $Id } | Select-Object -First 1)
}

function Get-FileState {
    param([string]$Path)
    $abs = Join-Path $ProjectRoot $Path
    if (-not (Test-Path -LiteralPath $abs)) { return '(缺文件=回退default)' }
    $len = (Get-Item -LiteralPath $abs).Length
    if ($len -gt 0) { return "($len B)" } else { return '(空=回退default)' }
}

function Show-SlotTable {
    $rows = Get-SlotRows
    Write-Info ("槽位总数：{0}（default + {1} 个工作流槽）" -f $rows.Count, ($rows.Count - 1))
    Write-Host ''
    foreach ($r in $rows) {
        Write-Host ("  [{0,-10}] {1}" -f $r.Id, $r.Label)
        Write-Host ("      positive: {0}  {1}    negative: {2}  {3}" -f $r.Pos,
            (Get-FileState $r.Pos), $r.Neg, (Get-FileState $r.Neg))
    }
    Write-Host ''
    Write-Host '提示：留空/缺文件 = 运行该工作流时自动使用 default（prompts\positive_prompts.txt 等）。'
}

function Invoke-Notepad {
    param([string]$Slot)
    $r = Get-SlotRow $Slot
    if (-not $r) { Write-Warn "未知槽位: $Slot"; return }
    $p = Join-Path $ProjectRoot $r.Pos
    New-Item -ItemType Directory -Force -Path (Split-Path $p) | Out-Null
    if (-not (Test-Path -LiteralPath $p)) { Set-Content -LiteralPath $p -Value '' -Encoding UTF8 }
    Write-Info "打开记事本编辑: $($r.Pos)（保存后关闭即可）"
    & notepad.exe $p
}

function Invoke-CopyDefault {
    param([string]$Slot)
    if ($Slot -eq 'default') { Write-Warn 'default 已是它自己，无需复制。'; return }
    $r = Get-SlotRow $Slot
    if (-not $r) { Write-Warn "未知槽位: $Slot"; return }
    $m = Read-Manifest
    $dPos = Join-Path $ProjectRoot ([string]$m.default.positive)
    $dNeg = Join-Path $ProjectRoot ([string]$m.default.negative)
    $dstPos = Join-Path $ProjectRoot $r.Pos
    $dstNeg = Join-Path $ProjectRoot $r.Neg
    New-Item -ItemType Directory -Force -Path (Split-Path $dstPos) | Out-Null
    Copy-Item -LiteralPath $dPos -Destination $dstPos -Force
    Copy-Item -LiteralPath $dNeg -Destination $dstNeg -Force
    Write-Info "已把 default 复制到 $Slot（positive+negative）。可再编辑微调。"
}

function Write-SlotText {
    param([string]$Slot, [string]$Text)
    $r = Get-SlotRow $Slot
    if (-not $r) { Write-Warn "未知槽位: $Slot"; return $false }
    if (-not $Text) { Write-Warn '内容为空，未写入。'; return $false }
    $p = Join-Path $ProjectRoot $r.Pos
    New-Item -ItemType Directory -Force -Path (Split-Path $p) | Out-Null
    Set-Content -LiteralPath $p -Value ($Text.TrimEnd() + "`n") -Encoding UTF8
    Write-Info "已写入 $Slot positive（$($Text.Length) 字符）。negative 留空=运行时回退 default。"
    return $true
}

function Append-SlotText {
    param([string]$Slot, [string]$Text)
    $r = Get-SlotRow $Slot
    if (-not $r) { Write-Warn "未知槽位: $Slot"; return $false }
    if (-not $Text) { Write-Warn '注入内容为空。'; return $false }
    $p = Join-Path $ProjectRoot $r.Pos
    New-Item -ItemType Directory -Force -Path (Split-Path $p) | Out-Null
    $stamp = Get-Date -Format 'yyyy-MM-dd HH:mm'
    $sep = "`n`n--- 注入 ($stamp) ---`n"
    Add-Content -LiteralPath $p -Value ($sep + $Text.TrimEnd()) -Encoding UTF8
    Write-Info "已在 $Slot 追加注入新提示词（保留原内容，可记事本再整理）。"
    return $true
}

function Invoke-AiGenerate {
    param([string]$Slot, [string]$Idea)
    if (-not $Idea) { $Idea = (Read-Host '请输入一句创意').Trim(); if (-not $Idea) { return } }
    Write-Info "调用本地模型为 $Slot 生成提示词（idea2prompts --workflow $Slot）..."
    & python (Join-Path $ProjectRoot 'runs\h3\idea2prompts.py') --idea $Idea --workflow $Slot
    Write-Host ("  退出码: " + $LASTEXITCODE)
}

function Show-SlotDetail {
    param([string]$Slot)
    $r = Get-SlotRow $Slot
    if (-not $r) { Write-Warn "未知槽位: $Slot"; return }
    Write-Info "槽位 $Slot（$($r.Label)）"
    $p = Join-Path $ProjectRoot $r.Pos
    Write-Host "文件: $($r.Pos)"
    if (Test-Path -LiteralPath $p) {
        $c = Get-Content -LiteralPath $p -Raw
        Write-Host '---- 内容摘要（前 400 字）----'
        if ($c) { Write-Host $c.Substring(0, [Math]::Min(400, $c.Length)) }
    }
    else { Write-Host '(无文件，运行时会回退 default)' }
}

function Run-SlotMenu {
    param([string]$Slot)
    while ($true) {
        Show-SlotDetail $Slot
        Write-Host ''
        Write-Host ("  槽位 [$Slot] 操作：")
        Write-Host '   [E] 记事本编辑 positive'
        Write-Host '   [C] 用 default 覆盖（复制起步）'
        Write-Host '   [N] 输入新提示词（覆盖写入 positive）'
        Write-Host '   [A] 追加注入新提示词（保留旧词）'
        Write-Host '   [G] AI 生成（本地模型，需 llm.json enabled）'
        Write-Host '   [0] 返回'
        $c = (Read-Host '请选择 (E/C/N/A/G/0)').Trim().ToUpper()
        switch ($c) {
            'E' { Invoke-Notepad $Slot }
            'C' { Invoke-CopyDefault $Slot }
            'N' {
                Write-Host '请输入提示词内容（粘贴后空行回车结束）：'
                $lines = @()
                while ($true) {
                    $ln = Read-Host
                    if (-not $ln) { if ($lines.Count -gt 0) { break } else { continue } }
                    $lines += $ln
                }
                $text = $lines -join "`n"
                if ($text) { [void](Write-SlotText $Slot $text) }
            }
            'A' {
                Write-Host '请输入要注入的新提示词（粘贴后空行回车结束）：'
                $lines = @()
                while ($true) {
                    $ln = Read-Host
                    if (-not $ln) { if ($lines.Count -gt 0) { break } else { continue } }
                    $lines += $ln
                }
                $text = $lines -join "`n"
                if ($text) { [void](Append-SlotText $Slot $text) }
            }
            'G' { Invoke-AiGenerate $Slot '' }
            '0' { return }
            default { Write-Warn "无效选择：'$c'" }
        }
        Write-Host ''
        $null = Read-Host '按回车继续'
    }
}

# ------------------------- 非交互（脚本/AI）-----------------------------
if ($Workflow) {
    if ($Show) { Show-SlotDetail $Workflow; return }
    if ($CopyDefault) { Invoke-CopyDefault $Workflow; return }
    if ($Set) { [void](Write-SlotText $Workflow $Set); return }
    if ($Append) { [void](Append-SlotText $Workflow $Append); return }
    if ($Idea) { Invoke-AiGenerate $Workflow $Idea; return }
    Show-SlotDetail $Workflow
    return
}

# ------------------------- 交互入口 --------------------------------------
Write-Host ''
Write-Host '  ============================================================'
Write-Host '      工作流提示词向导' -ForegroundColor Cyan
Write-Host '  ============================================================'
Write-Host '  目的：按"工作流/模板"管理提示词（t2v/i2v/r2v/flf2v 与 api_*）'
Write-Host '  流程：选工作流 → 填 / 注入 / AI 生成提示词 → 跑工作流时自动使用'
Write-Host '  ============================================================'
Write-Host ''

while ($true) {
    Show-SlotTable
    Write-Host ''
    Write-Host '   [W] 选择一个工作流槽位开始操作（输入槽位 id）'
    Write-Host '   [0] 退出'
    $c = (Read-Host '输入槽位 id（如 video_r2v）或 0 退出').Trim().ToLower()
    if ($c -eq '0') { Write-Host '再见！'; return }
    if ($c) { Run-SlotMenu $c }
}
