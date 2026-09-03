# 运行形态（部署模式）：win-remote 与 spark-local

> 项目存在两种运行位置，二者**可随时切换**（同一份仓库）：
> - **win-remote（默认/现状）**：仓库在 Windows 本机，通过 ssh + 隧道访问 spark 的
>   ComfyUI 与本地模型；
> - **spark-local（交付形态）**：仓库整体部署在 spark 上，ComfyUI 与本地模型**同机直连**，
>   无需隧道——由 spark 上的本地模型（Qwen）直接调用本项目生成图片/视频，形成本机闭环。
>
> 切换入口：`bats\config\mode.bat`（交互）或命令行：
> `python runs\h3\deploy.py --set <win-remote|spark-local>` / `--show`。

## 1. 两种形态的差异与切换副作用

| 项 | win-remote | spark-local |
|---|---|---|
| 仓库位置 | Windows（`D:\MY_CODING_PROGRAM\videoGenerate-Model-zju`） | spark（如 `~/videoGenerate-Model-zju`） |
| ComfyUI | spark 上，经 **ssh 隧道**访问（本地 127.0.0.1:8188） | 同机 127.0.0.1:8188 直连 |
| 生成前检查 | ssh 可达 + 隧道自动建/自愈 | 本机 HTTP 探活，不建隧道 |
| 产物拉取 | `scp` 到本机 `outputs\` | 本机复制（`~/ai/ComfyUI/output → outputs/`） |
| LLM（idea2prompts） | 经隧道 `http://127.0.0.1:8011/v1` | 直连 `http://127.0.0.1:8000/v1` |
| 适用的入口 | `run.bat`/`menu.bat`（PowerShell）与 python CLI | **python CLI / spark bash 脚本**（`.bat` 需 Windows；spark 上有 pwsh 也可跑 ps1） |
| 隧道清理 | 结束自动停（只清自己） | 不涉及 |

切换器自动完成的动作：改写 `config/deploy.json` 的 `site`；把 `config/llm.json` 的
`base_url` 切到该形态（旧值备份 `llm.json.bak`）。状态保存在 `config/deploy.json`
（无敏感信息，可入库；示例 `config/deploy.example.json`）。

## 2. 形态 A：本地 Windows + 远程 spark（现状，推荐日常开发用）

1. 双击 `bats\service\StartComfyUI.bat` 或让生成流程自动处理；
2. `run.bat` / `menu.bat` → 生成（自动检查 ssh/ComfyUI/隧道/模型）；
3. 产物自动 `scp` 到 `outputs\video_N.mp4`。
4. 确认当前形态：`python runs\h3\deploy.py --show`（应显示 win-remote）。

## 3. 形态 B：整体部署在 spark（交付形态，供本地模型直接调用）

把仓库作为模块化包放到 spark 后切换即可：

```bash
# 在 spark 上（bash）
rsync -a <本机仓库>/ ~/videoGenerate-Model-zju/     # 或 git clone/pull
cd ~/videoGenerate-Model-zju
python runs/h3/deploy.py --set spark-local           # 同机直连：无需隧道，LLM 直连 8000

# 起本机服务（ComfyUI、Qwen vLLM 由优化者脚本负责：shell/spark_manage_services.sh 等）
# 生成视频：直接 python CLI（ComfyUI 127.0.0.1:8188）
python runs/h3_submit.py --stage t2v --force-new
python runs/h3_submit.py --stage r2v --force-new

# 文生图参考图（FLUX 本机）
python runs/h3_text2img_flux.py --text "..." --name ref01

# 本地模型(Qwen 8000) → 本项目 → 本地出片（全本机闭环）
python runs/h3/idea2prompts.py --idea "一句话创意" --force
python runs/h3_submit.py --stage video_r2v --force-new
```

- spark-local 下 `generate_video.ps1`（若用 pwsh 运行）会跳过隧道、直接探活本机 ComfyUI、
  产物用本机复制；`bats\*.bat` 本身面向 Windows，spark 上请用 python CLI。
- spark 上“本地模型再调用生成模型”的职责链：Qwen(vLLM 8000) → idea2prompts 写槽 →
  h3_submit(127.0.0.1:8188) → 出片；产物与日志仍在 `outputs/`、`logs/`、`workflows/h3_*/`。

## 4. 注意事项
- 切换只改两份本地配置（deploy.json / llm.json），不动 spark 远端任何文件。
- 服务启停权限以 `docs/session-summary.md` 最新记录为准（例如 Qwen 优化期间勿擅自启动）。
- 模型职责护栏（只做提示词生成、拒绝服务器控制指令）对两种形态同样生效。

## 5. 同步项目到 spark（传输约定：**不携带 .git**）
> 约定（2026-09-03 起）：整目录外传一律排除 `.git` 等 git/缓存文件——版本历史走 GitHub
> （`git push` / 远端 `git pull`），文件同步只传代码/配置/资产。原因：远端 git 对象只读权限会
> 令 scp 整目录覆盖失败；且 .git 应唯一由 GitHub 维护。
>
> **合并语义（重要，2026-09-03 修正）**：同步以**文件为单位取两端较新版本**——不是"某一端
> 单向覆盖"。代码与文档的合并首选 **git**（本地 commit/push → 远端 `git pull`，自动三向合并）；
> 本节的 tar 工具只用于 git 之外/覆盖层文件（如 `config/llm.json`、产物、spark 本地配置），
> 使用前先确认方向：新文件在哪一端就用对应的"正向/反向"命令，避免把较新文件覆盖回旧版。
> 实例：本地新增"同步工具/约定文档"并推送 git 后，spark 因不传 .git 而缺这两项；随后一次
> "spark→本地"反向整传把本地较新文件覆盖成旧版——已用 `git checkout` 恢复。正确流程是
> git 推送后用远端 `git pull` 取新，或按较新端方向做定向同步。

- **推荐工具**：`python runs\sync_to_spark.py`（入口 `bats\workflow\sync_to_spark.bat`）：
  打包时排除 `.git/.test_tmp/__pycache__` → scp 临时 tar → 远端解包到 `~/videoGenerate-Model-zju`。
  选项：`--clean`（先删远端目录再传）、`--dry-run`（本地预览不含 .git）。
- 只传已提交内容也可用 `git archive HEAD | ssh spark tar -x -C ~`（但会漏 gitignored 的
  本地配置如 `config/llm.json`、产物；本仓库同步默认保留这些，故用上面的 tarfile 工具）。
- 更新代码更推荐：`ssh spark "git -C ~/videoGenerate-Model-zju pull origin master"`
  （需远端已配置 remote 与认证）。
