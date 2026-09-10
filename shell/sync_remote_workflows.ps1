# ============================================================================
# sync_remote_workflows.ps1 — 取回 spark 上同事的工作流**原件**（只作对照）
#
# 2026-09-10 重要变更（防事故）：
#   旧行为 = 直接把同事原件下载到镜像根目录 workflows/remote_workflows/，
#   而那里放的是**我们改造过的在用模板**（book-06：删内嵌故事、注入属性词模板），
#   于是「跑一次同步」就会静默覆盖我们自己的改造（当天真的发生过，靠 git 回滚救回）。
#   新行为 = 一律下载到 workflows/remote_workflows/archive/originals/，
#   **绝不触碰根目录的在用模板**；要对比请自行 git diff。
#
# 源路径记录在 config/pipeline.json 的 remote_workflow_templates。
# 引擎实际读取的模板目录 = 根目录（见 docs/guides/workflow-single-source.md）。
# ============================================================================
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $here
$dest = Join-Path $root 'workflows\remote_workflows\archive\originals'
New-Item -ItemType Directory -Force -Path $dest | Out-Null
$base = '/home/Developer/ai/ComfyUI/user/default/workflows'
$names = @('api_minimax_h3_flf2v.json','api_minimax_h3_r2v.json','api_minimax_h3_t2v.json',
           'video_minimax_h3_i2v.json','video_minimax_h3_r2v.json','video_minimax_h3_t2v.json')
$ok = $true
foreach ($n in $names) {
  $dst = Join-Path $dest $n
  scp -q -o BatchMode=yes spark:"$base/$n" $dst
  if ($LASTEXITCODE -eq 0 -and (Test-Path $dst)) {
    Write-Host "取回原件 $n ($((Get-Item $dst).Length) B)"
  } else {
    Write-Host "[WARN] 取回失败 $n"
    $ok = $false
  }
}
if ($ok) {
  Write-Host ''
  Write-Host '同事原件已放到 workflows\remote_workflows\archive\originals\（仅供参考，不参与生成）。'
  Write-Host '在用模板仍是 workflows\remote_workflows\ 根目录下那几份；要对比差异用 git diff / 直接比文件。'
}
exit $(if ($ok) { 0 } else { 1 })
