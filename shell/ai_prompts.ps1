<#
.SYNOPSIS 单一创意 → 自动生成全部/单个工作流提示词（AI 通用模型桥）
    由 ai_prompts.bat 启动；也可直接 powershell -File 传 -Idea。
    前提：config/llm.json 里 enabled=true 并填 base_url/api_key/model。
.PARAMETER Idea 一段创意；不传则交互输入。
.PARAMETER Workflow 只生成某槽位（默认全部：default + 6 个工作流）。
.PARAMETER DryRun 只打印计划，不发请求不写文件。
#>
param([string]$Idea = '', [string]$Workflow = '', [switch]$DryRun)
$ErrorActionPreference = 'Continue'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $here

if (-not $Idea) {
  Write-Host ''
  Write-Host '================================================'
  Write-Host '  一段创意 → 自动生成各工作流提示词（AI）'
  Write-Host '================================================'
  Write-Host ''
  Write-Host '  示例：一只机械猫在雨夜屋顶追逐霓虹信标，'
  Write-Host '       决定在一个 8 秒长镜头里揭示它曾是玩具的真相。'
  Write-Host ''
  $Idea = (Read-Host '请输入创意（支持中文/英文；回车取消）').Trim()
  if (-not $Idea) { exit 0 }
}
$brief = Join-Path $root '.ai_brief.tmp.txt'
Set-Content -LiteralPath $brief -Value $Idea -Encoding UTF8
$py = Join-Path $root 'runs\h3\idea2prompts.py'
$argsList = @($py, '--idea-file', $brief)
if ($Workflow) { $argsList += @('--workflow', $Workflow) }
if ($DryRun) { $argsList += @('--dry-run') }
& python @argsList
$code = $LASTEXITCODE
Remove-Item -LiteralPath $brief -Force -ErrorAction SilentlyContinue
Write-Host ''
if ($code -eq 0) { Write-Host '提示词生成完成。可用 prompts.bat 查看/微调；运行工作流时自动使用。' }
else { Write-Host '未成功。若提示 AI(enabled=false)：编辑 config\llm.json 填入配置后重试。'
       Write-Host '  - 本地 spark vLLM(Qwen3)：参考 config\llm.spark-qwen3.example.json（api_key 可留空）。'
       Write-Host '  - 公网 OpenAI 兼容：填 base_url/api_key/model 后置 enabled=true。' }
exit $code
