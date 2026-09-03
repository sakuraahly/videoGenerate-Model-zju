# 会话总结（Session Handoff / 新对话交接用）

> 用途：把本项目的当前状态一次性交给“新对话/AI”继续工作。本文件随项目维护，
> 请先读它再读其他文档。**项目根 = `D:\MY_CODING_PROGRAM\videoGenerate-Model-zju`**
> （旧目录 `videoGenerate_Model&zju` 已于 2026-09-02 删除，勿再引用旧路径）。

---

## 1. 一句话
Windows 本机 + 远程 `spark`（自建 ComfyUI，`~/ai/ComfyUI`，ssh 免密）：用 MiniMax H3
本地模型生成视频；同事提供 6 份工作流模板（镜像在 `workflows/remote_workflows/`）；
整套工具=双击 .bat → 隧道/远程检查/提交/轮询/下载/日志/断点续传；提示词按工作流管理，
最终目标是“只给一个创意 → 中间通用模型 → 各工作流提示词 → 自动出片”。

## 2. 目录速览
```
bats\                      全部启动 .bat（分类）
  generate\  run.bat menu.bat         config\  edit.bat
  prompts\   prompts.bat ai_prompts.bat
  workflow\  workflow_setup.bat pipeline_setup.bat sync_remote_workflows.bat
  service\   StartComfyUI.bat（远程 ComfyUI 管理：启动/隧道/浏览器）
shell\                       PowerShell 引擎（程序模块，非入口）
  generate_video.ps1 console_menu.ps1 run_scheduled.ps1 check_environment.ps1
  transfer_setup.ps1 pipeline_setup.ps1 prompts_console.ps1 ai_prompts.ps1
  sync_remote_workflows.ps1 lib\*.ps1 ForSparkService\{ComfyUI-Launcher,Start,Stop}-ComfyUI.ps1
runs\h3\                    Python 引擎包
  h3_submit.py  CLI 入口（stage/template/workflow-file/断点/日志）
  workflow.py params.py comfy.py templates.py uiapi.py subgraph.py stage.py jobstate.py prompts.py idea2prompts.py
  tests\test_h3.py          87 项单测
config\ environment.json llm.json(.example) pipeline.json pipeline.example.json
        minimax_h3_models.json prompt_blueprints.json transfer.json
prompts\ manifest.json positive/negative_prompts.txt workflows\<slot>.positive/.negative.txt
workflows\ remote_workflows\（6 份 spark 镜像 + 本地扩展 video_minimax_h3_flf2v.json） + h3_<时间戳>\（每次任务 api/ui/job.json）
parameters\video.txt         每任务参数（resolution/seconds；可选 seed/fps/steps/timeout）
outputs\                     生成视频 video_N.mp4
logs\run_<时间戳>.log         运行日志（PS 步骤 + Python 事件）
docs\ 见 §9；skills\ h3-video-generation.md / h3-prompt-engineering.md
```

## 3. 三个“事实”必须记住（前几轮踩坑结论）
1. 6 份同事工作流在 spark `~/ai/ComfyUI/user/default/workflows/`；本地镜像
   `workflows/remote_workflows/`（引擎只用镜像；改动/注入都作用于本地文件）。
   **同事会不定期更新 spark 侧模板**（曾把 api_r2v/video_r2v/video_i2v/api_flf2v 的参考图
   改指 `drama_asset_{hero,alley}.png`、video_r2v 内嵌 prompt 改为 `<Picture 1/2>` 占位模板）。
   本地镜像过期会表现为“缺图/旧语义”假象——跑 `bats\workflow\sync_remote_workflows.bat`
   把 spark 最新 6 份拉回镜像即可（2026-09-02 已拉齐并 MD5 复核 SAME）。
2. 分类与用途（实测 + 团队实际语义）：
   - `api_minimax_h3_{t2v,r2v,flf2v}.json`：**T2V/R2V/FLF2V 的 API 格式**（扁平、无 subgraph
     坑、命令行用更稳）。执行 = Comfy 云通道（节点 `MinimaxHailuo03*` 定义在 ComfyUI 自带
     `comfy_api_nodes/nodes_minimax.py`，经 Comfy 云代理 `/proxy/minimax/...` 转发 MiniMax
     **Hailuo 官方 API**）→ 需 Comfy 账号登录，否则 `Unauthorized: Please login first`。
     **登录后即可作 CLI/管线内核**——团队 15 镜短片《于勒》以 `api_minimax_h3_r2v` 做内核；
     `api_flf2v` 示例图（angel-warrior…）不在 spark input，**需自备**。
   - `video_minimax_h3_t2v.json`：文生视频：文字→一段视频（**官方标准模板**，本地 H3）；
   - `video_minimax_h3_i2v.json`：图生视频：一张**首帧图**→延续它动起来（本地 H3）；
   - `video_minimax_h3_r2v.json`：多参考图生视频：1–2 张参考图（角色/场景）→保证连贯地生成
     （本地 H3 开放图，含 `MiniMaxH3ReferenceToVideo`）；
   - `video_minimax_h3_t2v/i2v` 为 **UUID 子图封装**（type=`4c314f31-ecda-4b08-ae98-faaba1bf613f`，
     图体在 `definitions.subgraphs`）——已实现自动解组（`runs/h3/subgraph.py`，uiapi 转换前
     自动 flatten）并 CLI 实跑验收，见 §8；
   - `video_minimax_h3_flf2v.json`：**本地新增双帧变体**（非 spark 原文件，只存本地镜像）——
     由 video i2v 扩展：两个 LoadImage 接 `MiniMaxH3ImageToVideo` 的 first/last_frame，
     覆盖本地 FLF2V（首帧 drama_asset_hero / 末帧 drama_asset_alley，已实跑出片，见 §8）。
3. 本地内置 T2V（`--stage t2v` / run.bat 默认）走 spark **本地推理**，无需登录任何云端，
   是当前稳定可出片的路径。
4. **ComfyUI 运行形态（2026-09-03 起）：systemd 服务 `comfyui.service`**（`ExecStart=…
   main.py --listen 127.0.0.1 --port 8188 --disable-auto-launch --reserve-vram 12
   --enable-manager`，root 属主，随开机自启）。历史上有 tmux/裸进程两种形态，一律按
   **端口探测**（`ss -ltn | grep :8188`）判断是否在跑，不要假设 tmux 一定存在；
   重启/看日志用 `ssh spark 'sudo systemctl restart comfyui.service'` /
   `journalctl -u comfyui.service`（注意：**sudo 需交互密码，自动化改配置不可行**）。
   ⚠️ `--enable-manager` 仍在（用户决定保留，勿擅动；其 GitHub 拉取超时是“假卡死”来源之一，见 §12）。

## 4. 入口与常规流程
- 环境自检：`bats\generate\menu.bat → [5]`（本地依赖、ssh、ComfyUI、4 模型，缺失可自动下载）。
- 立即生成：`run.bat` 或 `menu [1]`（内置本地 T2V；参数 parameters\video.txt=360p/5s）。
- 定时/延迟：`menu [2]/[3]`（先预检再倒计时）。
- 6 工作流手动（GUI 最稳）：见 `docs/manual-use-6-workflows.md`。
- 脚本/CLI 多工作流：
  `python runs\h3_submit.py --stage r2v --image a.png` / `--template <file>` /
  `--workflow-file saved_api.json` / `--dry-run`；占位符 `{{prompt}}{{image0}}...`；
  退出码 0/2/3/90；标记行 `REMOTE_VIDEO_PATH:`、`WORKFLOW_SAVED_DIR:`。

## 5. 提示词体系（本轮重点）
- `prompts/manifest.json`：槽位=default + 6 个工作流（video_t2v/i2v/r2v、api_t2v/r2v/flf2v），
  文件 `prompts/workflows/<槽>.positive/.negative.txt`；空=回退 default。
- 引擎自动注入：运行任一工作流（stage/template）时，按
  CLI > 该工作流槽位 > 阶段默认 > default 取提示词，并**覆盖模板内嵌 prompt**（含
  `model.prompt`、上游 PrimitiveString 等）。优先级逻辑在 `runs/h3/prompts.py`。
- 快捷编辑：`bats\prompts\prompts.bat`（列槽位/记事本/复制 default）。
- AI 创意桥：`bats\prompts\ai_prompts.bat` → `shell/ai_prompts.ps1` →
  `runs/h3/idea2prompts.py`：一句创意 → 通用模型为各槽生成 {positive,negative} 并写入。
  未配模型时可 `--dry-run` 预览。模型配置：`config/llm.json`（enabled=true + base_url/
  api_key/model，OpenAI 兼容；`llm.json` 已 gitignore，模板 `llm.example.json`）。
  **api_key 可留空**：空 key 时引擎不发 Authorization 头，兼容 spark 本地自部署端点
  （vLLM/Ollama 等）。本地 Qwen3 接入示例：`config/llm.spark-qwen3.example.json`
  （base_url=http://127.0.0.1:8000/v1，model=Qwen3-8B/27B；如 vLLM 只监听 127.0.0.1 需
  先 `ssh -N -L 8000:127.0.0.1:8000 spark`）。

## 6. 可靠性/工程特性（已实现）
- 断点重连 `last_job.json`（提交写 prompt_id、成功后补 remote_path，下载完清除；`--resume` 不重复生成）。
- 隧道：本地端点复用/断线自愈/端口被占自动换；只清理自己记录的 ssh。
- 单实例锁 `.run.lock`（防误双击并发）。
- Comfy 客户端：请求重试(指数退避+抖动)、HTTP 4xx 不重试、轮询 5s→30s 自适应、
  `/upload/image` 上传输入图、全节点输出收集（mp4 优先）。
- UI→API 在线转换 `uiapi.py`（依据 /object_info；动态组合键 `model.*`、字符串节点引用、
  装饰节点跳过、widget 陈旧值处理、COMBO 枚举规范化、死链清理）——官方/同事 UI 模板可转 API。
- **UUID 子图自动解组 `subgraph.py`**：uiapi 转换前调用 `flatten_subgraphs()`，把
  `definitions.subgraphs` 内节点搬入顶层、-10/-20 端口桩重接（外层连线优先、widget 值
  注入内部槽、IMAGE 无源断开）、id/link 重映射，输出开放图（限制：不支持嵌套子图）。
- 工作流上传：`workflow_setup.bat`（spark 绝对目录 + 使用指定工作流 + 每任务自动上传）。
- 模型清单检查/补货：`menu [5]`（4 个文件，curl -C - 断点续传）。
- 日志：`logs\run_<yyyyMMdd_HHmmss>_<毫秒>.log`（PS+Python 同一文件）。PS 引擎（run.bat）
  先建文件并经 `H3_LOG_FILE` 注入；**Python CLI 直跑无注入时自动自举**（`runs/h3_submit.py`
  `_ensure_run_log`）在 `logs\` 建同名日志并打印"运行日志: <路径>"。毫秒后缀保证同秒多次
  运行不撞名。**任务联结（双向）**：日志内 `workflow_saved dir=h3_<同秒>_<ms>` 行→任务目录；
  任务目录 `job.json` 的 `log_file: run_....log` →日志文件。`--resume` 续传会沿用原任务日志
  （`_adopt_task_log` 合并本次会话起始行），保证"一个任务一份完整日志"。
  事件（py: 前缀，带时间戳）：`start argv=...` → `task mode=.. stage=.. source=..
  resolution=.. duration=.. seed=.. steps=.. prompt_len=..`（任务配置摘要）→
  `workflow_saved dir=..` → `submitted prompt_id=..` → 结束行
  `completed/interrupted/timed_out/task_error`（含 `elapsed=Ns`、remote 路径）；
  `dry_run` 会记 `dry_run mode=.. stage=.. nodes=.. (预览，未提交)`。
- 模板可用性策略：可用 API→用；UI→在线转；缺失/不可转换→有内置则提示回退，无内置报错。

## 7. 6 个工作流在 spark 上的绝对路径（来源记录）
`/home/Developer/ai/ComfyUI/user/default/workflows/{api_minimax_h3_flf2v,api_minimax_h3_r2v,api_minimax_h3_t2v,video_minimax_h3_i2v,video_minimax_h3_r2v,video_minimax_h3_t2v}.json`
同步命令：`bats\workflow\sync_remote_workflows.bat`。

## 8. 当前可运行基线（验证过）
- 内置本地 T2V：360p/5s，已实际出片（旧目录产物 video_1..3.mp4）；
- **video_r2v 已 CLI 实跑验收通过**（2026-09-02）：`python runs\h3_submit.py --stage r2v
  --force-new --seed 12345`，双参考图 drama_asset_hero/alley.png，出片
  `outputs\video_r2v_accept.mp4`（远程 `~/ai/ComfyUI/output/video/MiniMax_H3_00013_.mp4`，
  记录在 `workflows\h3_20260902_213409_674\`）。修复前被两个 bug 挡住：空提示词槽位不回退
  default、COMBO `ref_image_size=''` 未规范化（均已在 runs/h3 修复，见 §11 历史）。
- **video t2v / i2v（UUID 子图）已解组并 CLI 实跑验收通过**（2026-09-02）：用
  `python runs\h3_submit.py --template workflows\remote_workflows\video_minimax_h3_t2v.json
  --force-new --seed 4321` 等命令出片 `outputs\video_t2v_subgraph_accept.mp4` /
  `video_i2v_subgraph_accept.mp4`（远程 MiniMax_H3_00014_/00015_，记录
  workflows\h3_20260902_220028_695\ 与 \220622_124\）。i2v 首帧=drama_asset_hero.png。
- **video flf2v（本地双帧变体）实跑验收通过**（2026-09-02）：`python runs\h3_submit.py
  --stage flf2v --force-new --seed 8888` 出片 `outputs\video_flf2v_accept.mp4`（远程
  MiniMax_H3_00016_，记录 workflows\h3_20260902_223338_454\）。首帧 hero / 末帧 alley。
  至此**本地语义 4 类全覆盖**：video t2v/i2v/r2v/flf2v 均 spark 本地出片（api_* 三份为
  Comfy 云模板，登录 Comfy 账号可用，非本地能力缺口）。
- api_* 3 份 + 其余 video UI→API 转换均通过 /prompt 校验；api_* 实测被 Comfy 云登录拦截。
- 单测 **74 项通过**；PowerShell 全部 ps1 语法通过；日志/清单/槽位/注入/创意桥 dry-run 冒烟通过。

## 8b. service 工具（bats\service\StartComfyUI.bat）2026-09-02 重写
- 旧问题：Launcher 用 `.\Start-*.ps1` 相对路径（依赖 cwd，双击 bat 必失败）；Start 用
  `ssh -N -f`（Windows OpenSSH 后台化不可靠）；Stop 静默吞掉 Stop-Process 失败；
  远程“在跑”判定只看 tmux 会话（裸进程场景失效）。
- 现状：三件套（`shell\ForSparkService\{ComfyUI-Launcher,Start-ComfyUI,Stop-ComfyUI}.ps1`）
  已重写并实测 Start/Stop 全链路：远程端口探测（tmux 或裸进程都认）→ 60s 等远程 UP →
  Start-Process ssh -N 建隧道并 HTTP 探活（本地已有可用端点则复用；死隧道自动清理，
  权限不足如实报错）→ 可选 -NoBrowser。Stop 先停本地隧道再停远程（tmux kill，兜底按
  main.py 命令行补杀裸进程），杀不掉如实提示 taskkill。
- 附加文件：`config\llm.spark-qwen3.example.json`（AI 桥本地 Qwen3 vLLM 接入示例）。

## 9. 文档地图（docs/）
- `session-summary.md`（本文件）
- `quickstart.md`（⭐ 新手快速上手：三步出片 + 模板/参考图选择，小白先读这个）
- `workflow-and-prompt.md`（⭐ 怎么指定"工作流"与"提示词"：有/无本地通用模型两种情形）
- `user-guide.md` 操作指南（入口/配置/流程/多工作流/日志）
- `capabilities-ai.md`（项目能力注册表可读版——由 config/capabilities.json 生成，勿手改）
- `deploy-modes.md`（运行形态 win-remote / spark-local 手册：切换/副作用/交付用法）
- `manual-use-6-workflows.md` 6 个工作流逐文件手动步骤（GUI+脚本）
- `robustness-and-modularity.md` 架构/断点/隧道/扩展/测试；§9 工作流分类与占位符
- `h3-troubleshooting.md`、`h3-manual-operations.md`(legacy)、`comfyui-startup-and-access.md`、
  `long-term-maintenance.md`、`h3-workflow-architecture.md`
- `agent-communication/` 多 Agent 协作（protocol / collaboration / review-and-recommendations /
  inbox 总线 / scheduler-agent-design=Qwen 调度器 Function Calling 落地设计）
- `local-model/` 本地模型部署文档（另 Agent 维护：quick-start / full-manual）
- `skills/h3-video-generation.md`（智能体技能卡）、`skills/h3-prompt-engineering.md`（提示词规则）

## 10. 待办 / 下一步（给新对话的明确任务）
1. **ComfyUI 依赖已修复（2026-09-03）**：`comfy_kitchen` 已升级到 0.2.31。
   一键全启：`bash ~/videoGenerate-Model-zju/shell/manage_services.sh start`。
2. **开机自启已配置（2026-09-03）**：XDG autostart `.desktop` → `start_all_services.sh`
   协调启动（先停 ComfyUI → SGLang 加载 2min → 再启 ComfyUI → qwen-agent → Open WebUI）。
   管理命令：`bash ~/videoGenerate-Model-zju/shell/manage_services.sh {start|stop|restart|status|enable|disable|logs}`。
   SGLang 共存模式 `mem=0.55`（独占模式改 0.95）。
3. **Qwen-Agent 调度器端到端已验证（2026-09-03）**：
   - `call_comfyui` dry_run 成功（t2v 参数验证通过）
   - `run_script` idea2prompts dry-run 成功
   - `modify_workflow` 已修复（适配 ComfyUI nodes[] 数组格式）
   - 安全回归测试 13 项全部通过（目录穿越、绝对路径、非 .py、非法 JSON 等）
   - SGLang 无需 `--enable-auto-tool-choice`（qwen-agent nous 模式绕过）
   - tmux `qwen-agent` 端口 7860，Gradio Web UI 可用
4. **文生图已实现（2026-09-03）**：`runs/h3_text2img.py` 用 H3 视频模型生成 5 帧图片。
   Spark 只有 H3 模型（无 SD/SDXL），故复用 H3 生成极短视频取首帧。
   用法：`python runs/h3_text2img.py --prompt “描述” --output goodboy`。
   Qwen Agent 调用提示词：`请用 run_script 运行 h3_text2img.py --prompt “...” --output goodboy`。
5. **Open WebUI 已运行（2026-09-03）**：tmux `webui`，端口 3000。
   访问：`http://spark:3000`（或隧道 `ssh -N -L 3000:127.0.0.1:3000 spark`）。
   首次访问需注册管理员账号。重启务必保留 `HF_HUB_OFFLINE=1`。
6. **AI 桥：已基本接通，待全量验证**：idea2prompts 单槽（api_t2v）端到端成功一次。
   待全槽位生成 + `bats\prompts\ai_prompts.bat` 交互验证。
7. **本地语义已全覆盖**：video t2v/i2v/r2v/flf2v 均已本地实跑出片。
8. **维护提醒**：
   - 同事更新 spark 模板后，`bats\workflow\sync_remote_workflows.bat` 拉齐镜像。
   - spark 服务管理统一用 `manage_services.sh`（不再手动 tmux）。
   - ComfyUI venv 在 `~/ai/venv/`（非 `~/ai/ComfyUI/venv/`）。
   - 每次工作后更新 `skills/h3-video-generation.md` 和 `docs/session-summary.md`。
9. 可选项：把”创意→提示词”做成单页 GUI/Web 入口；为 6 工作流补”参考图自动回传/占位符”
   自动化；modify_workflow 端到端实测（test_tool_calling3.py 在 spark 上跑）。

## 11. 2026-09-02 会话修复记录（供回溯）
- `runs/h3/prompts.py`：pick_prompt_paths 只判文件存在不判空 → 空槽位文件挡住回退 default，
  注入被跳过。改为“空文件视为未设置”继续回退（+4 单测）。
- `runs/h3/uiapi.py`：COMBO widget 值未规范化，video_r2v 的 `ref_image_size=''` 提交 HTTP 400。
  新增 `_combo_options_of`/`_normalize_combo`（兼容老式 options 列表与新式 ["COMBO",{options}]），
  非法值回退 cfg.default/首项（+4 单测）。
- `runs/h3/uiapi.py`：新增 `prune_dead_output_nodes`——移除输出无消费者且非文件输出类的
  死链节点（i2v 模板顶层 ImageScaleToTotalPixels→GetImageSize 未接线碎片即由此清理，+2 单测）。
- **`runs/h3/subgraph.py`（新增）**：UUID 子图自动解组 `flatten_subgraphs()`，接入 uiapi
  convert_ui_file 前。视频 t2v/i2v 两份同事模板已解组→转换→/prompt 校验→实跑出片（+4 单测）。
- **本地 flf2v 模板（新增）**：`workflows/remote_workflows/video_minimax_h3_flf2v.json` 由
  video i2v 扩展（第二 LoadImage 接 last_frame，hero→first / alley→last），注册
  manifest 槽位 video_flf2v、prompt_blueprints、pipeline flf2v 阶段（template_kind=ui），
  实跑出片 `outputs/video_flf2v_accept.mp4`（+1 单测）。**未上传 spark、未改远端任何工作流**。
- **api_* 定性更正**：api_minimax_h3_* 为 Comfy 云模板（comfy_api_nodes MinimaxHailuo03*
  经 Comfy 云代理 MiniMax 官方 API），本地同语义已由 video_*（t2v/i2v/r2v/flf2v）全覆盖；
  同步更正 user-guide/manual/robustness/pipeline 措辞。
- `runs/h3/idea2prompts.py`：chat_once 空 api_key 时不发 Authorization 头（本地 vLLM/Ollama 兼容，
  +2 单测）；错误提示指向 config/llm.spark-qwen3.example.json。
- **logs 修复与增强（2026-09-02）**：① 原日志只靠 PS 注入 H3_LOG_FILE，CLI 直跑不写；
  `_ensure_run_log` 自举（无注入自动建日志，打印"运行日志: <路径>"）；② 事件补全：task
  配置摘要 / workflow_saved / 结束行含 `elapsed=Ns`，dry_run 记预览行；③ 日志名毫秒化
  `run_<ts>_<ms>.log`（py + PS Initialize-RunLog 同步）；④ 任务联结：`job.json` 新增
  `log_file` 字段（任务→日志），日志 `workflow_saved dir=` 行（日志→任务）；⑤ `--resume`
  用 `_adopt_task_log` 沿用原任务日志并并入本会话起始行。测试注入临时 H3_LOG_FILE 防污染
  真实 logs（+5 单测，套件 79）。
- `shell\ForSparkService\*`：三件套重写（见 §8b），废弃 `ssh -N -f` 与相对路径调用。
- **《GAME OVER》三步产出（2026-09-03，spark）**：FLUX.1-dev 文生图两张
  （1344×768，`runs/h3_text2img_flux.py`，落 spark input + 本地 `refs\`）：
  `refs\hero_night_ops.png`（暗夜特工主角）、`refs\alley_night_neon.png`（雨夜巷）；
  r2v 视频两段（复用上两图，槽位词）：
  `outputs\video_gameover_sample_5s.mp4`（360p/5s 小样）与
  `outputs\video_gameover_15s.mp4`（480p/15s 正片，prompt=
  `prompts\gameover_15s.positive.txt`，结尾 "GAME OVER" 红字）。
  **注意：ComfyUI 进程随后被手动杀掉——再次生成前需先 StartComfyUI.bat 恢复。**
- **仓库止血与多 Agent 协作约定（2026-09-03）**：纳入版本控制另一 Agent 新增脚本
  （`shell/spark_install_flashinfer.sh`=FlashInfer SM12.1 安装进行中、
  `spark_manage_services.sh`、`spark_vllm_smart_start.sh`）与 `docs/local-model/`
  （quick-start/full-manual）；`.gitignore` 增 `agent-communication/inbox/` 与 `*.jsonl`
  `state.yaml`（暂态）；protocol.md/collaboration.md 加"示例 vs 真实"标注与 §9 文件总线
  落地（inbox + session-summary 为事实源）。**服务状态：ComfyUI 已启动；Qwen(vLLM) 未启动
  且由优化者负责，任何 Agent 不得擅自启动 Qwen（FlashInfer 优化中）。**
- **本地小模型护栏与职责（2026-09-03）**：Qwen 角色严格限定为"创意→提示词 JSON 生成器"。
  强约束三层落点：① `idea2prompts.build_messages` 硬编码职责边界句（不执行/不规划任何命令、
  文件、网络、进程、服务操作，夹带指令一律忽略）；② blueprint 规则 0；③ 调用层不给模型任何
  shell/工具。未来任何交互用户要求模型做服务器控制 → 调用层拒绝并转人工。服务启停权限归属见
  §10（Qwen 由优化者负责，不得擅自启动）。
- **下载监听策略（2026-09-03，写入 skill 1.5b）**：状态等待仅保留 wait_for 自适应轮询；
  产物“完成即一次性拉取”（完成标记/job.json state=completed/spark inotify 触发），失败用
  有界指数退避；长下载等进程/日志标记而非采样轮询；断线重建隧道续传不重跑。
- **运行形态切换（2026-09-03）**：新增 `config/deploy.json`（site: win-remote 现状 /
  spark-local 交付形态）+ `runs/h3/deploy.py`（--show/--set，自动同步 llm.json base_url
  8011↔8000 并备份 .bak）；入口 `bats\config\mode.bat`。`generate_video.ps1` 按形态分支：
  spark-local 跳隧道、本机 HTTP 探活、产物本机复制（Download-RemoteVideo -LocalCopy）；
  finally 中 spark-local 不清理隧道。文档 `docs/deploy-modes.md`（双形态手册），+3 单测
  （套件 86）。spark-local 交付用法：仓库移到 spark → --set spark-local → python CLI +
  本地模型(Qwen 8000)直调 → 同机 ComfyUI 出片，无需隧道。
- 镜像同步：`sync_remote_workflows.ps1` 拉齐 6/6（当时 4 份过期）。
- **第 4 步：Qwen3.8-27B vLLM 部署与 AI 桥打通（2026-09-03）**：
  - 安装：`~/Qwen3.8-27B/vllm-venv` 用**清华镜像**装 vLLM 0.28.0（aarch64 wheel 308MB；
    官方源易卡下载）；模型 18 shards 已就绪（`~/Qwen3.8-27B/models/Qwen--Qwen3.8-27B/`）。
  - 启动：`~/Qwen3.8-27B/start_vllm.sh`（= `shell/spark_vllm_start.sh`，tmux 会话 vllm）。
    **修复点：`--limit-mm-per-prompt` 参数旧格式 `image=4,video=2` 不被 vLLM 0.28 接受，
    必须 JSON 格式 `'{"image": 4, "video": 2}'`**（已修）；识别架构
    Qwen3_5ForConditionalGeneration；加载约 8 分钟。
  - 访问：spark 监听 127.0.0.1:8000 → 本地隧道（因本地 8000 曾被残留进程占用，
    权宜用 **8011**：`ssh -N -L 8011:127.0.0.1:8000 spark`）。
  - AI 桥修复：idea2prompts 新增 `max_tokens`（llm.json 限 500；不限长=65536 空转拖垮队列，
    曾导致后续请求超时）；端到端单槽 api_t2v 成功一次（+1 单测，套件 80）。
    吞吐约 4.5 tok/s（无优化 kernel），**用户正在优化 Qwen 服务中，勿打扰**。
  - 其余 spark 侧脚本（仓库内）：`shell/spark_chat_setup.sh`（一键复制脚本+隧道+聊天）、
    `shell/spark_chat_terminal.py`（OpenAI 兼容终端聊天）、`shell/spark_vllm_start.sh`（服务启动）。
- 提示词：`prompts/workflows/video_r2v.positive.txt`、`video_i2v.positive.txt` 已按
  skills/h3-prompt-engineering.md 填写（空槽位回退 default 见上）。
- **文档/知识沉淀（2026-09-02）**：新增 `docs/quickstart.md`（新手三步上手）；
  模板用途语义（video t2v=文生视频官方标准模板、i2v=首帧图生、r2v=多参考角色/场景连贯；
  api 三份=对应能力的 API 格式：扁平无 subgraph 坑、命令行更稳、走 Comfy 云通道需登录、
  《于勒》15 镜以 api_r2v 做内核、api_flf2v 示例图需自备）已写入
  session-summary §3 / user-guide / manual-use-6-workflows / quickstart / skills/h3-video-generation。
- **Qwen-Agent 受限调度器落地（2026-09-03）**：
  - 代码：`runs/agent/tools.py`（3 个受控工具 run_script / modify_workflow / call_comfyui）+
    `runs/agent/scheduler.py`（入口，Gradio Web UI + CLI 双模式）。
  - 框架：阿里官方 qwen-agent 0.0.34，`@register_tool` + `BaseTool` 子类，
    参数为 plain JSON schema（非 function definition 包装）。
  - 独立 venv：spark `~/qwen-agent-venv`（与 sglang-venv / vllm-venv / open-webui-venv2 隔离）。
  - 运行：tmux 会话 `qwen-agent`，Gradio Web UI 在 spark 端口 7860（已确认 HTTP 200）。
  - 启动器：`~/Qwen3.8-27B/start_qwen_agent.py`（薄包装，调用 `runs.agent.scheduler.main`）。
  - LLM 配置：连接 SGLang `http://127.0.0.1:8000/v1`，temperature=0.2，fncall_prompt_type='nous'。
  - 安全：realpath 前缀校验（runs/ / workflows/remote_workflows/ / config/templates/），
    输出截断 ≤5000 字符，脚本超时 120s。
- **Open WebUI 部署完成（2026-09-03）**：
  - 独立 venv：spark `~/open-webui-venv2`（与 qwen-agent-venv 隔离）。
  - 安装：`pip install open-webui`（阿里云镜像，146MB wheel）。
  - embedding 模型：`sentence-transformers/all-MiniLM-L6-v2` 经 hf-mirror.com 下载缓存于
    `~/.cache/huggingface/hub/models--sentence-transformers--all-MiniLM-L6-v2/`
    （需 `HF_HUB_DISABLE_XET=1` 禁用 xet 协议，否则 401）。
  - 运行：tmux 会话 `webui`，端口 3000，HTTP 200 已确认。
    启动命令：`HF_HUB_OFFLINE=1 ENABLE_RAG=false
    OPENAI_API_BASE_URL=http://127.0.0.1:8000/v1 open-webui serve --host 0.0.0.0 --port 3000`。
  - 用途：ChatGPT 风格网页对话，API 指向 spark 本地 Qwen3.8-27B（SGLang 端口 8000）。
  - 首次访问需注册管理员账号；重启务必保留 `HF_HUB_OFFLINE=1` 防止联网。
- **Agent 通信文档评审采纳（2026-09-03）**：
  - protocol.md：新增 §9 消息文件总线（inbox + session-summary 事实源）+ §10 分阶段启用
    （Phase 1 = 模式 A + 消息 JSON + 审查清单 + 安全边界 + Qwen-Agent；Phase 2 暂缓 YAML
    状态机/扇出/交叉审查）。
  - collaboration.md：文件树更新（加入 runs/agent/ + scheduler-agent-design.md）。
  - 两文件顶部均已标注"示例 vs 真实"免责声明。
  - .gitignore 已加入 inbox/ / *.jsonl / state.yaml（暂态消息不入库）。
- **Qwen-Agent 工具修复与安全测试（2026-09-03 续）**：
  - `modify_workflow` 修复：原代码按 flat dict 查找节点（`data[node_id]`），实际工作流是
    ComfyUI `nodes[]` 数组格式。改为按 `id` 搜索节点，修正 `changes` 参数描述（去掉多余
    `inputs` 包装层）。`run_script` 校验顺序修复（.py 扩展名检查提前到文件存在性检查前）。
  - 安全回归测试 `runs/agent/test_security.py`：13 项全部通过（目录穿越、绝对路径、非 .py、
    非法 JSON、不存在节点、非整数节点 ID 等）。可本地运行（mock qwen_agent 依赖）。
  - `modify_workflow` 端到端测试 `runs/agent/test_tool_calling3.py`：备份→agent 修改→验证→恢复。
  - 文生图 `runs/h3_text2img.py`：用 H3 视频模型（无 SD/SDXL）生成 5 帧极短视频，保存为
    图片序列。工作流：UNETLoader + CLIPLoader(type=minimax) + VAELoader +
    MiniMaxH3ImageToVideo(length=5) + BasicGuider + KSamplerSelect(res_multistep) +
    BasicScheduler(simple) + RandomNoise + SamplerCustomAdvanced + VAEDecode + SaveImage。
  - 模型文档：spark ComfyUI 只有 H3 模型（diffusion_model 21GB + text_encoder 16GB + VAE 5.2GB），
    已记录到 memory `project-spark-comfyui-models.md`。
  - skills 更新：`skills/h3-video-generation.md` 新增 §1.3c（SGLang 部署）和 §1.3d（文生图）。
  - Qwen Agent 系统消息更新：明确列出 `h3_text2img.py` 可用，给出调用示例。
- **RAG 默认启用 + Agent 必读文档（2026-09-03 续）**：
  - `shell/start_all_services.sh`：移除 `ENABLE_RAG=false`，Open WebUI 启动即启用 RAG。
  - `shell/systemd/open-webui.service`：同步移除 `ENABLE_RAG=false`。
  - `docs/qwen38-deployment.md`、`docs/local-model/quick-start.md`：更新启动命令和 RAG 说明。
  - `docs/agent-reading/` 新建 4 篇必读文档：
    - `00-project-overview.md` — 项目概览、能力清单、硬性限制、关键路径
    - `01-tools-reference.md` — 3 个工具的参数、用法、安全限制
    - `02-prompt-rules.md` — H3 提示词工程速查（结构模板、示例、常见错误）
    - `03-models-and-environment.md` — Spark 模型清单、服务端口、GPU 内存协调
  - `runs/agent/scheduler.py` SYSTEM_MESSAGE 更新：新增「任务前必读（强制）」段落，
    要求 agent 每次接到新任务时先通过 run_script 读取 docs/agent-reading/ 文件。
- **Agent 知识内嵌 + read_doc 工具（2026-09-03 续）**：
  - 问题诊断：用户在 Open WebUI (端口 3000) 对话，该界面是纯聊天，无工具调用能力。
    带工具的调度器在 Qwen-Agent Gradio UI (端口 7860)。
  - 原「任务前必读」要求 agent 用 run_script 读 .md 文件，但 run_script 只允许 .py，
    导致 agent 无法读取文档。
  - 修复方案（双管齐下）：
    1. 新增 `read_doc` 工具（`runs/agent/tools.py`）：读取 docs/agent-reading/ 下的 .md/.txt，
       realpath 前缀校验 + 扩展名检查 + 输出截断。
    2. 将核心知识（项目架构、能力清单、硬性限制、模型信息、分辨率、提示词规则、典型工作流）
       直接嵌入 SYSTEM_MESSAGE，agent 无需工具调用即具备基础知识。
  - SYSTEM_MESSAGE 重写：从「强制读取」改为「已内嵌 + 可选 read_doc 深入参考」。
  - TOOL_NAMES 新增 'read_doc'，scheduler.py import 同步更新。
  - 安全测试 13/13 通过（原有测试未受影响）。
  - **交接文档**：`docs/handoff-2026-09-03.md`（本地）+ `~/Qwen3.8-27B/PROJECT-STATUS.md`（spark），
    包含服务状态、启动命令、已知缺陷、诊断结论、新对话快速启动清单。

---

## 12. 2026-09-03 晚间会话：ComfyUI “假卡死”诊断 + 日志系统退化修复（本会话）

### 12.1 重要：用户撤销了 ComfyUI 配置修改
- 之前诊断建议“去掉 comfyui.service 的 `--enable-manager`”（选项 A）**已被用户明确撤回**：
  **禁止修改 ComfyUI 配置**（`/etc/systemd/system/comfyui.service` 保持原样，用户要查的
  其实不是那次 systemd 日志里的“第二次”，而是更早“人类工作流用猫图生成视频”的那次）。
- 结论：**ComfyUI 未做任何改动**；如需重启/改配置只能由用户人工操作（sudo 要交互密码）。

### 12.2 时间线换算提醒（易错点！）
- **日志文件名/内容 = 北京时间（UTC+8，由本地 Windows 生成）**；spark 的
  `ls -l` / `journalctl` / `date` 显示 **UTC**。同一时刻两者相差 8 小时。
- 例：spark 日志 `Sep 3 09:19 Utc` = 北京 `17:19`；`run_20260903_153644_675.log`（北京 15:36 启动）
  的 spark mtime 显示为 `Sep 3 07:36`。**跨端比对时间必须先换算。**

### 12.3 诊断结论一：猫图 i2v 那次“卡住”其实成功了，只是超慢
- 现场记录（北京时）：
  - `15:38:13` 本地提交 i2v（prompt_id `0504cacd-e95f-497d-8805-f24f00d69a10`，
    608×352@360p，5s→124f@24fps，timeout=3600s），任务目录
    `workflows/h3_20260903_153813_525/`（job.json state=timed_out）。
  - `16:38:46` 客户端 `timed_out`（等满 1 小时放弃）；**ComfyUI 实际继续执行**，
    到 `17:19` 产出 `~/ai/ComfyUI/output/video/MiniMax_H3_00024_.mp4`（5.9MB）——
    **全过程约 101 分钟，任务其实是成功的**，只是远超客户端 1h 等待上限。
- 教训与修复的关系：客户端超时后**断点保留**（root_state 仍有 prompt_id），期间再开新任务
  会被“断点拦截”挡住 → 用户看到“卡住/无响应”+ 只有两行的粗略日志。三者叠加造成“假卡死”。
- 处置建议：**无参数重跑 h3_submit 即自动续传**，能马上定位
  `MiniMax_H3_00024_.mp4`（无需重新生成）。

### 12.4 诊断结论二：“粗略日志”= 提前退出路径不落日志（已修复 ✅）
- 现象：`logs/run_*.log` 从 15:30 起出现多份**只有 95B、两行**的文件
  （`run start` + `start argv=`），没有 task/submitted/interrupted/timed_out/错误行。
- 根因：`runs/h3_submit.py` 多条提前退出路径（断点拦截、`--workflow-file` 参数混用、
  `ParamError`、顶层异常兜底）**只 `_err()` 打印到 stderr、从不 `_log_event`**；
  且 CLI 直跑时 `argv=None`，`start argv=` 记的是空串。
- 修复（本地提交 `20f89ae`，spark 提交 `a6c8f01`，两文件哈希一致）：
  1. `_err()` 现在同步写运行日志（`py: err …`）→ 所有失败路径统一留痕；
  2. `start argv=` 记录真实命令行（`sys.argv[1:]`）；
  3. `__main__` 顶层 `ParamError`/内部异常兜底也落日志；
  4. 断点拦截提示增强：显示断点 prompt_id，并提示“可直接无参重跑自动续传继续等待”。
  5. 回归测试 `test_err_writes_log_too`（+1 单测，套件 87 全过）。
- 证据/日志事件规范（完整链条）：`start argv=…` → `task mode=.. stage=.. …` →
  `workflow_saved dir=…` → `submitted prompt_id=…` → 结束行
  `completed / interrupted / timed_out / task_error`（含 `elapsed=Ns`）或新的
  `err …`（提前退出）。

### 12.5 残留缺陷 / 待办（给新对话）
1. **ComfyUI 为何 360p/5s 跑了 ~101 分钟仍未查明**（正常约 4-6 分钟/480p/124f）。
   已知线索：`--enable-manager` 实例启动后做 GitHub fetch 超时（journal 见大量
   `asyncio TimeoutError` + `[ComfyUI-Manager] Due to a network error, switching to local mode`，
   09:04-09:11 UTC 一段），且有一次 `Prompt executed in 00:16:48`；journal 还有
   `ModuleNotFoundError: No module named 'nvvfx'`（08:59 UTC，疑似无害）。
   用户暂不想动 ComfyUI 配置；下次复现时优先看 `journalctl -u comfyui.service` 的
   “Prompt executed in …”行两侧（真正执行时长 vs 排队/Manager 阻塞），并对比
   `system_stats`/`nvidia-smi`。
2. **ComfyUI 本机自动化无法重启**：改配置/重启需用户手动（sudo 密码无法非交互）。
   文档 §3 已同步为“systemd 服务”现状（旧 troubleshooting 文档仍写 tmux，需随下次
   会话一并更正——见 §9 文档地图，可只读参考）。
3. **spark 侧 git 提交需内联身份**：`git -c user.name=Developer -c user.email=dev@spark
   commit …`（仓库未配置 user.name/email，直接 commit 会报
   `unable to auto-detect email address`）。
4. ~~本地领先 GitHub~~ → **已推送**：本地 master=02a8261 == origin/master（此前领先的
   20f89ae / 7d14d56 与移除 AI 日报的 02a8261 均已 push；spark 只保留本地 git 记录，永不推 GitHub）。
5. ~~提示词残留~~ → **已清理**：`prompts/workflows/video_i2v.positive.txt` 中
   2026-09-03 15:30 追加注入的 cat 提示词段已移除，文件现仅含当前正片提示词
   （历史遗留，非本次引入）。
6. 老文档中 ComfyUI “tmux 进程”叙述（h3-troubleshooting.md 等）已过时：
   现行 = systemd `comfyui.service`（§3 与 §12.1）。

### 12.6 本会话改动的文件清单
- `runs/h3_submit.py`（日志修复，commit `20f89ae`）
- `runs/h3/tests/test_h3.py`（+1 回归测试；套件 87）
- `docs/session-summary.md`（本文件更新）
（以上均已通过 scp 同步 spark 并各自提交；transferred 时遵循“不含 .git”约定。）

### 12.7 后续会话：spark-local 交付形态验证与修复
- 两端已合并并推送 GitHub（本地 02a8261/8e310cf/a9f8e74/4f23900；spark HEAD 05cd559 + 53e926b）。
- **spark-local 全服务共存启动成功**：SGLang(Qwen3.8-27B, 8000, coexist mem=0.55) + ComfyUI(8188,
  tmux) + qwen-agent(7860) + Open WebUI(3000) 同时在线；Qwen 曾因缺 `ninja` 启动失败，由用户手工修复。
- **AI 桥实测（真实 SGLang）**：单槽与全槽位生成成功；发现 max_tokens=1200 截断导致非 JSON
  杂讯被旧 parse_prompt_json“纯文本回退”写入槽位文件 → 修复：JSON 提取加固 + 截断/指令杂讯
  直接报错不落盘 + llm.json/示例 max_tokens→4096（本地 commit `a9f8e74`）。
- **程序实测**：h3_submit t2v 360p/5s 真实出片 `MiniMax_H3_00025_.mp4`（~252s）；h3_text2img
  出 5 帧；h3_text2img_flux 发现**无 spark-local 感知**（在 spark 本机仍 ssh/scp 自己→解析失败）
  → 修复为读 config/deploy.json 分支、同机 copy2 落位 input/ 与 refs/（本地 commit `4f23900`）。
- **agent 工具链**：7860 HTTP 200；安全回归 13/13；modify_workflow 真实 LLM 端到端 PASS
  （test_tool_calling3.py，改后校验并恢复）。
- 旧断点 0504cacd（此前 101 分钟慢任务）清理：产物 `MiniMax_H3_00024_.mp4` 已恢复至
  `outputs/video_recovered_i2v_cat_00024.mp4`，last_job.json 已删。
- 其它：全槽位生成补出 `prompts/workflows/video_flf2v.negative.txt`（通用词表，入库）；
  `.gitignore` 增 `config/llm.json.bak`。
- **日志系统全流程升级**：新增 `runs/h3/logutil.py` 统一日志模块（格式与 h3_submit
  一致：`[ts] py: <tool> event k=v`；优先沿用环境变量 `H3_LOG_FILE`，否则自举
  `logs/run_<ts>_<ms>.log`）。已接线：idea2prompts（task/slot_written/completed/
  dry_run/err）、h3_text2img、h3_text2img_flux（submitted/completed/err/落位事件）、
  agent 工具 tools.py 四工具（call/ok/error 透明审计包装，不改变 schema）。PS 侧
  ai_prompts.ps1 / prompts_console.ps1 接入 Initialize-RunLog 并导出 H3_LOG_FILE →
  PowerShell 行与子进程 py: 事件汇入同一份会话日志。AI 桥测试数据此前不入日志的
  盲区已消除（实测：PS+py 交错日志、dry-run 与真实生成均有留痕）。
- **提交/等待分离 + spark-local 直存 outputs + 自动合并（commit 19a22e6）**：
  - 修复“任务已提交并持续运行，但 call_comfyui 600s 超时误报并丢失 prompt_id”：
    h3_submit 新增 `--submit-only`（提交即打印 `TASK_SUBMITTED: prompt_id` 返回、
    断点保留）；call_comfyui 默认提交即返回（新参数 wait_until_done/force_new），
    真超时也从 partial stdout 提取 prompt_id 并指引“无参重跑续传”。
  - spark-local 直跑成功后按 deploy.json site 把产物**本机复制直存 outputs/**
    （video_N.mp4 递增命名，打印 `LOCAL_OUTPUT:`）；win-remote 保持 scp（编排层下载）。
  - 双模式隔离：spark-local 一切操作 spark 程序文件夹；win-remote 走隧道/scp。
  - 两个文件夹自动化合并：`runs/sync_auto.py {enable|disable|status|once|watch}`
    + `bats\workflow\autosync.bat`；enable --daemon 后台周期合并（默认 180s），
    每轮 sync_merge 逐文件取新、冲突留人工 `--resolve`；config/autosync.json
    两端各自维护（不入库/不参与同步）。实测：submit-only→续传→出片并 LOCAL_OUTPUT
    直存 outputs/video_4.mp4（fox 演示）；两端基线已重建。
- **参考素材池（ComfyUI 已存图 / Open WebUI 上传件，commit 9e05368）**：
  - `runs/h3/refimage.py`：三池（in=ComfyUI input / out=ComfyUI output 递归产物 /
    up=上传收件箱 uploads/）list / promote / use(--stage i2v|r2v|flf2v 改写镜像模板
    LoadImage) / use --undo；win-remote 自动经 ssh 委托 spark 执行。
  - `runs/h3/upload_watch.py`：Open WebUI 上传看门狗（数据目录实测
    `~/.cache/open-webui`）→ 归档 uploads/YYYYMMDD/ + log.jsonl 去重，图片镜像到
    ComfyUI input/user_uploads/；spark 上 tmux `upload-watch` 已在跑。
  - agent 新增第 5 工具 `list_references`（调度器已注册，重启生效）。
- **sync_to_spark 排除机器配置/产物（commit dc01831/0ff0689）**：整仓 tar 不再携带
  deploy.json/llm.json/pipeline/transfer/autosync/upload_watch/.sync-state、logs/
  outputs/workflows/h3_*、根目录 *.mp4 —— 两端机器文件各自维护，spark-local 形态
  不会被同步覆盖（此前实测被覆盖后 refimage 误判发起 ssh 自我委托）。
