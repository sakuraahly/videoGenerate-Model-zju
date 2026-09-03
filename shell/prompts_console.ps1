<#
.SYNOPSIS 提示词快捷编辑（被 prompts.bat 启动）
    列出 6 个工作流 + default 的提示词文件；可打开记事本编辑，或把 default 复制到某槽。
#>
$ErrorActionPreference = 'Continue'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $here
$mf = Join-Path $root 'prompts\manifest.json'
$cfg = Get-Content $mf -Raw | ConvertFrom-Json
$rows = @()
$rows += [pscustomobject]@{ Id='default'; Label='默认/内置 T2V'; Pos=$cfg.default.positive; Neg=$cfg.default.negative }
foreach ($p in $cfg.slots.PSObject.Properties) {
  $s = $cfg.slots.($p.Name)
  $rows += [pscustomobject]@{ Id=$p.Name; Label=$s.label; Pos=$s.positive; Neg=$s.negative }
}
Write-Host '== 提示词槽位 =='
for ($i = 0; $i -lt $rows.Count; $i++) {
  $r = $rows[$i]
  $posPath = Join-Path $root $r.Pos
  $state = if (Test-Path $posPath) { $len = (Get-Item $posPath).Length; if ($len -gt 0) { "($len B)" } else { '(空=回退default)' } } else { '(缺文件=回退default)' }
  Write-Host ("  [{0}] {1,-18} {2,-30} {3}" -f ($i + 1), $r.Id, $r.Label, $state)
}
Write-Host "  [A] 用 AI 根据一段创意自动生成（见 ai_prompts.bat）"
Write-Host "  [C] 把 default 提示词复制到某个槽（用于起步）"
Write-Host '  [0] 返回'
Write-Host ''
$choice = (Read-Host '选择').Trim()
if ($choice -eq 'A') {
  Write-Host '请双击 ai_prompts.bat（独立窗口）。'
  exit 0
}
if ($choice -eq 'C') {
  $slot = (Read-Host '要复制到哪个槽（如 video_r2v，回车取消）').Trim()
  if ($slot -ne '' -and ($cfg.slots.PSObject.Properties.Name -contains $slot)) {
    $dstPos = Join-Path $root ([string]$cfg.slots.$slot.positive)
    $dstNeg = Join-Path $root ([string]$cfg.slots.$slot.negative)
    Copy-Item (Join-Path $root ([string]$cfg.default.positive)) $dstPos -Force
    Copy-Item (Join-Path $root ([string]$cfg.default.negative)) $dstNeg -Force
    Write-Host "已复制 default 到 $slot"
  }
  exit 0
}
$idx = 0
if (-not [int]::TryParse($choice, [ref]$idx) -or $idx -lt 1 -or $idx -gt $rows.Count) { exit 0 }
$r = $rows[$idx - 1]
$p = Join-Path $root $r.Pos
if (-not (Test-Path $p)) { New-Item -ItemType File -Path $p -Force | Out-Null }
Write-Host "打开（记事本）：$p（保存关闭即可生效）"
Start-Process notepad $p
