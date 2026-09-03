# ============================================================================
# sync_remote_workflows.ps1 — 把 spark 上的 6 个工作流同步到本地镜像
# 镜像目录：workflows/remote_workflows/（后续所有修改/注入都作用于这些本地文件）
# 源路径记录在 config/pipeline.json 的 remote_workflow_templates。
# ============================================================================
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $here
$mirror = Join-Path $root 'workflows\remote_workflows'
New-Item -ItemType Directory -Force -Path $mirror | Out-Null
$base = '/home/Developer/ai/ComfyUI/user/default/workflows'
$names = @('api_minimax_h3_flf2v.json','api_minimax_h3_r2v.json','api_minimax_h3_t2v.json',
           'video_minimax_h3_i2v.json','video_minimax_h3_r2v.json','video_minimax_h3_t2v.json')
$ok = $true
foreach ($n in $names) {
  $dst = Join-Path $mirror $n
  scp -q -o BatchMode=yes spark:"$base/$n" $dst
  if ($LASTEXITCODE -eq 0 -and (Test-Path $dst)) {
    Write-Host "同步 $n ($((Get-Item $dst).Length) B)"
  } else {
    Write-Host "[WARN] 同步失败 $n"
    $ok = $false
  }
}
if ($ok) { Write-Host '远端工作流镜像已更新：workflows\remote_workflows\（后续修改都基于这些本地文件）。' }
exit $(if ($ok) { 0 } else { 1 })
