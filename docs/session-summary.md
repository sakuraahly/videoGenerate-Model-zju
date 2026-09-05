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
   - `video_minimax_h3_r2v.json`：多参考图生视频：多张参考图（角色/场景/道具；本地模板默认 8 槽、refimage grow 可扩）→保证连贯地生成
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
- `agent-workflow.md`（⭐ 本地 Agent(Qwen) 工作链手册：两入口/工具/提交-续传-取件/素材链/异常处置）
- `agent-reading/04-agent-workflow.md`（agent 任务执行协议速查，随调度器 read_doc 提供）
- `handoff-2026-09-04.md`（⭐ 最新交接：服务现状/机制/界面能力/测试清单/待观察项）
- `reference-2026-09-04.md`（⭐ 总参考手册：配置注册表/运行形态/引擎与工具契约/模板明细/故障字典/测试模板）

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
   - **新增/修订任何文档或 skills → 回写根目录 `START-HERE.md` 的 §2 索引与版本记录**（它是所有新参与模型的总入口，见其 §5 同步规则）。
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
- **stop_qwen 脚本：仅停 Qwen 不碰 ComfyUI（2026-09-03 晚间）**：
  - 背景：需要频繁启停 Qwen 系列服务（SGLang / Qwen-Agent / Open WebUI）做开发调试，
    但 ComfyUI 必须保持运行。此前 `start_all_services.sh` 的 pkill 模式
    `ComfyUI/main.py` 匹配不到孤儿进程（cmdline 只有 `main.py`），且
    `tmux kill-session` 会杀死 tmux server 导致 ComfyUI 变孤儿。
  - **Spark 版** `shell/stop_qwen.sh`：
    - 只操作 `sglang` / `qwen-agent` / `webui` 三个 tmux 会话
    - pkill 只匹配 `sglang.launch_server`（精确，不波及 ComfyUI）
    - `--status` 查看全部 4 个服务端口状态
    - 零 ComfyUI 操作：不 kill、不检查端口、不重启
  - **Windows 本地版** `bats\service\StopQwen.bat`：
    - 双击或命令行运行，SSH 到 spark 执行 `stop_qwen.sh`
    - 支持 `--status` 参数
  - **`start_all_services.sh` 修复**（同步进行）：
    - ComfyUI 启动参数补回 `--disable-auto-launch --reserve-vram 12 --enable-manager`
      （用户明确要求保留 `--enable-manager`）
    - pkill 模式从 `ComfyUI/main.py` 改为 `main.py.*--port 8188`（能匹配孤儿进程）
  - 旧脚本 `shell/comfyui_only.sh` 已废弃（含 ComfyUI 启停操作，不符合"不碰 ComfyUI"原则）。
  - **SGLang ninja 问题**：`ninja` 已安装在 sglang-venv 内（1.13.2），此前启动失败是
    因为未正确激活 venv；`start_all_services.sh` 用 `source activate` 方式已解决。
  - 协调启动实测：SGLang 加载 121s，全服务 2 分 15 秒就绪（共存模式 mem=0.55）。

### 12.9 2026-09-04：Agent 界面/内存/上传 批次（交接见 docs/handoff-2026-09-04.md）
- 服务现状：ComfyUI(systemd, 勿动, 曾 /free 卸载权重 49→18GB)；SGLang mem 0.50/ctx 8192
  （0.40 实测不足：NVFP4 预载≈49GB）；7860 新自研界面运行中；Open WebUI/upload-watch 未运行（可 7860 直传替代）。
- 自研界面 ui_app.py：自动新会话/历史加载/素材直传(两段式反馈+缩略图)/发送自动清空/幂等锁/
  停止按钮/程序级状态条(LLM+引擎日志行)/并发放开(16)/上下文预算 6k 字符。
- 修复链：FileData 取值、allowed_paths、缩略图、st_mtime 格式化红错、残留 previews 清空、
  接线丢 _upload 定义、全局并发=1 排队。
- 内存协同 llm_mem nap/wake 自动接线（TASK_SUBMITTED 后让位，下轮自动唤醒）；转场=逐对 flf2v 分镜法（SYSTEM+04）。
- 下一轮测试清单与已知待观察项见 docs/handoff-2026-09-04.md §5/§6。

## 13. 2026-09-04 第二批：Agent 上下文 8192 溢出根因定位与 token 预算化修复（本批）

### 13.1 现场与根因（三层）
- **现场**：7860 界面长会话点“继续”后，模型工作一会报
  `[执行出错] ModelServiceError: Error code: 400 … Requested token count exceeds the model's
  maximum context length of 8192 tokens. … 7177 tokens from the input messages and 2048 tokens
  for the completion`。SP/引擎侧任务不受影响。
- **根因（服务端规则，实测确认）**：SGLang max_model_len=8192，请求校验=输入+max_tokens≤8192
  （/v1/models 确认；本地 curl 验证 6116+2048 通过、57+8192 报 400）。
- **根因（客户端，三层叠加）**：
  1. qwen_agent(nous) 每次 LLM 调用把工具定义模板**追加进 system 消息**，固定开销大且不参与其
     自身截断：实测 SYSTEM_MESSAGE 1828t + nous 工具模板/定义 ≈1270t ⇒ 每轮 ≈3100t
     （/v1 usage 口径 3040~3093，与本地 QWen tokenizer 差 <3%）。
  2. qwen_agent 的输入截断按 generate_cfg max_input_tokens 执行，**默认 58000**（≫8192≈从不
     生效）——须显式传值。
  3. ui_app 原裁剪是**字符口径** MAX_CTX_CHARS=6000“≈3k token”——中文内容按 token 实算远超
     3k，且不约束“本回合内”工具往返累积 ⇒ 长历史/长回合输入可达 7177。
  - 附带发现：scheduler.py LLM_CFG `max_tokens: 8192` ⇒ **CLI 模式任何请求都 400**
    （57+8192>8192 实测复现），只有界面路径用 2048 覆盖而幸免。

### 13.2 修复内容（代码 commit `dd473e1`）
- **新增 `runs/agent/ctx_budget.py`**（唯一预算真值源）：常量 MODEL_MAX_CTX_TOKENS=8192 /
  REPLY_MAX_TOKENS=2048 / TOOL_PRELUDE_TOKENS=1500 / SAFETY_TOKENS=300 /
  UI_TRIM_TOKENS=1800 / CONV_MSG_BUDGET_TOKENS=2500；count_tokens（精确优先：
  qwen_agent 自带 QWen tokenizer，缺省保守启发式 CJK=1/字+其余/3）；
  trim_messages（token 口径：保最新轮次+预算内尽量保留首轮）；
  request_budgets（max_input_tokens = tokens(system)+2500，钳位 ≤8192−2048−300）；
  is_context_overflow_error。
- **ui_app.py**：trim 改 token 口径（UI_TRIM_TOKENS=1800）；每次请求 generate_cfg 带
  max_tokens=2048 + max_input_tokens（含回合内工具往返的硬预算）；服务端仍报 400 超上下文时
  自动压缩到仅剩最新消息重试一次并提示，不再裸抛 ModelServiceError。
- **scheduler.py**：LLM_CFG max_tokens 8192→2048（修 CLI 必 400）；run_cli 同样注入
  max_input_tokens 并对累积 messages 做同口径 trim（超限打印提示）。
- 预算推导（实测）：6144 输入预算 − 固定开销 ~3100 ⇒ 对话 ~2500t（≈长会话 4-6 轮），
  UI 存档裁剪 1800t 给回合内工具往返留余量。
- **测试**：新增 runs/agent/test_ctx_budget.py（6 项，本机+spark 各 6/6 通过；
  本机走启发式、spark 走精确 tokenizer）。

### 13.3 端到端验证（spark 真实 SGLang）
- 复刻现场（超长首轮 ~3k 字 + 10 轮 + “继续”）→ 正常回复，无 400；
- 巨型单条粘贴（~4 万字符）→ 框架 keep_both_sides 截断兜底，正常回复；
- 正常短对话 sanity 通过。
- 7860 界面进程已用新代码重启（tmux qwen-agent）。

### 13.4 仍待观察 / 边界
- 对话容量仍受服务端 ctx=8192 硬顶（预算机制保证“不越界”，不保证“不裁剪”）：
  超长交付请分轮 + “继续”；要更大对话窗口需调 SGLang context_length
  （config/llm_mem.json + llm-memory-optimization.md 的内存账本），并同步 ctx_budget.py。
- count_tokens 用 qwen_agent 自带 QWen tokenizer 与 SGLang(Qwen3.8-27B) 服务端计数有 <3% 偏差，
  已由 SAFETY_TOKENS=300 覆盖。
- 本批改动文件：runs/agent/{ctx_budget.py(新), ui_app.py, scheduler.py, test_ctx_budget.py(新)}；
  文档：docs/{handoff,reference}-2026-09-04.md、docs/agent-workflow.md、本文件。

### 13.5 提交与同步记录（2026-09-04）
- Windows 主库（D:\MY_CODING_PROGRAM\videoGenerate-Model-zju）commit：代码 `dd473e1`
  （fix(agent): 上下文 8192 溢出修复——token 预算化）+ 文档提交（同批）；已 push GitHub
  origin/master（sakuraahly/videoGenerate-Model-zju）。
- spark 运行时副本（~/videoGenerate-Model-zju，Z: 挂载）：4 个代码文件与 4 份文档已 scp
  同步；spark 本地 git 以内联身份 commit（仓库约定永不推 GitHub）。
- 7860 界面进程已重启（tmux qwen-agent，新代码生效，HTTP 200 已验证）。
- 验证：test_ctx_budget.py 本机 6/6 + spark 6/6；E2E 真实 SGLang 复刻崩溃现场
  （超长首轮+10 轮+“继续”）、巨型单条粘贴、正常短对话——全部正常回复、无 400。
- 遗留：本批 E2E 未动 ComfyUI/SGLang 服务（SGLang 未 nap，仍在 8000 运行）。

## 15. 2026-09-04 第三批：Agent 界面/提示词/体验优化

### 15.1 对话历史丢失修复（关键 bug）
- **根因**：`ui_app.py` 的 `hist_state`（gr.State）从未出现在 `send_out` 输出列表中，
  导致每轮 `send()` 收到的 `chat_hist` 始终为初始空列表 `[]`。模型每轮只看到当前一条消息，
  完全没有上下文。
- **修复**：将 `hist_state` 加入 `out` 和 `send_out`，所有 yield 点（锁忙/空输入/心跳/完成）
  均返回更新后的 `msgs` 列表；`_load`/`_new`/`_auto_new` 同步返回 msgs。

### 15.2 禁用自动 nap（模型休眠）
- 移除 `ui_app.py` 和 `scheduler.py` CLI 中的 `maybe_nap_after()` 调用。
- 模型提交任务后不再自动停止 SGLang，保持随时响应。nap/wake 机制保留供手动使用。

### 15.3 系统提示词重写（自主性）
- 重写 `SYSTEM_MESSAGE`：自主行动优先、只问必要问题、工作到完成、"继续"=承接上次工作、
  创意→成片全流程自主完成。
- 移除旧的冗长描述，精简为行为导向的准则。

### 15.4 上下文预算调整
- `UI_TRIM_TOKENS` 从 1800 提升到 2200，允许更多对话历史保留。

### 15.5 上传体验优化
- 缩略图从 256px/quality=80 降为 128px/quality=60（加速生成和加载）。
- 上传反馈消息简化：去掉技术性提示（list_references/refimage 命令），改为简洁状态。
- 页面标题/描述/输入框占位符改为更友好的文案。

### 15.6 改动文件
- `runs/agent/ui_app.py`：hist_state 修复、禁用 nap、上传优化、UI 文案
- `runs/agent/scheduler.py`：SYSTEM_MESSAGE 重写、CLI 禁用 nap
- `runs/agent/ctx_budget.py`：UI_TRIM_TOKENS 1800→2200

## 16. 2026-09-04 第四批：tools.py 超时处理 bug 修复 + 压力测试

### 16.1 tools.py TimeoutExpired bytes/str 拼接 bug
- **根因**：`subprocess.run(timeout=...)` 超时后，`TimeoutExpired` 异常的 `stdout`/`stderr`
  在某些情况下仍为 `bytes`（即使 `text=True`），代码直接拼接 `'\n'`（str）导致
  `TypeError: can't concat str to bytes`。
- **修复**：在 `TimeoutExpired` 处理块中增加 `isinstance` 检查 + `decode` 回退：
  ```python
  _out = e.stdout if isinstance(e.stdout, str) else (e.stdout.decode('utf-8', errors='replace') if e.stdout else '')
  _err = e.stderr if isinstance(e.stderr, str) else (e.stderr.decode('utf-8', errors='replace') if e.stderr else '')
  ```
  两处 `TimeoutExpired` 处理（`run_script` 和 `h3_submit` 工具）均已修复。

### 16.2 压力测试结果
- **同步**：`python runs/sync_to_spark.py` 增量同步 311 项/5MB 到 spark ✅
- **服务启动**：Agent(7860) + SGLang(8000) + ComfyUI(8188) 全部 HTTP 200 ✅
- **tools.py 修复验证**：spark 侧 `grep TimeoutExpired` 确认两处均已包含 `isinstance` 检查 ✅
- **CLI E2E 多轮对话测试**（完整通过）：
  - 输入"帮我生成一段10秒的猫咪在花园里玩耍的视频，720p"
  - 模型**自主选择 t2v 工作流**、生成详细英文提示词、直接提交（未反复确认）
  - 获得 `prompt_id: a148a1d2-82a7-4371-8fe6-4c65789717bb`
  - **持续轮询 24 分钟**（12次×120s）直到任务仍在运行
  - 给出清晰状态报告，建议稍后说"继续"取回视频
  - 全程未出现"当前没有进行中的任务"——**历史上下文保持完整**
  - token 从 19→3410 增长，模型主动工作到完成
  - **结论**：新系统提示词行为完全符合预期（自主行动、工作到完成、只在必要时汇报）

### 16.3 改动文件
- `runs/agent/tools.py`：两处 `TimeoutExpired` 处理的 bytes/str 兼容

## 17. 2026-09-04 第五批：Agent 体验/性能/隔离 6 阶段优化

> 设计文档：`docs/optimization-plan-2026-09-04.md`（7 问题 → 6 Phase）

### 17.1 Phase 1 — 上传多态状态 + 状态栏 HTML（P1+P6）
- **文件**：`runs/agent/ui_app.py`
- 新增状态 HTML 常量：`IDLE_HTML`（绿●等待）、`BUSY_HTML(t)`（橙●处理中）、`ERROR_HTML`（红●出错）、`ABORT_HTML`（橙●已中止）、`UP_IDLE`、`UP_LOADING(n)`（黄色药丸）
- `_upload()` 改为三态生成器：loading → 处理 → 成功/失败，`try/finally` 保证 `_upload_in_progress` 复位
- `send()` 开头检查上传中标志 → 提示等待
- 心跳状态改用 `BUSY_HTML(...)`，完成 → `✅ 本轮完成`

### 17.2 Phase 2 — 无效图片拦截（P5）
- **新建**：`runs/h3/mediacheck.py` — `check_image_bytes(data)`：大小检查 + PIL verify + 像素解码 + 尺寸校验，全异常捕获
- **修改**：`ui_app.py` `ingest_upload()` — 图片先过 mediacheck，无效跳过归档/镜像，返回 `invalid_details`
- **修改**：`upload_watch.py` `scan_once()` — 归档前校验，无效记录 `rejected` 到 log
- **修改**：`refimage.py` — `_rows()` 跳过 <1KB + 排除 `_quarantine/`；新增 `prune` 子命令（无效图片移至 `uploads/_quarantine/`）

### 17.3 Phase 3 — 失败处理 + 熔断器（P7）
- **新建**：`runs/agent/turn_state.py` — 双计数器（不可恢复 max 3 / 可恢复 max 5），per-key SHA 追踪
- **修改**：`tools.py` `_wrap_call()` — 分类返回值（确定/可恢复/成功），超阈值返回熔断消息，成功重置计数
- **修改**：`scheduler.py` SYSTEM_MESSAGE — 硬性限制段增加 `⛔ 不可恢复` 指令

### 17.4 Phase 4 — 批量提交工具（P4）
- **新建**：`runs/h3_batch.py` — submit/status/retry 子命令，manifest 编排，文件锁
- **修改**：`tools.py` — 新增 `BatchSubmit` 工具类（`batch_submit`）
- **修改**：`scheduler.py` — TOOL_NAMES + SYSTEM_MESSAGE 多图转段改用 batch_submit

### 17.5 Phase 5 — 任务级素材隔离（P2）
- **修改**：`ui_app.py` — `_pending_batch_id` 追踪，`ingest_upload()` 生成 `secrets.token_hex(4)`
- **修改**：`refimage.py` `cmd_list()` — 新增 `--batch latest|all|<id>` 和 `--recent <minutes>` 过滤
- **修改**：`tools.py` `ListReferences` — 新增 `batch` 参数（默认 'latest'）

### 17.6 Phase 6 — 文档状态追踪 + 预热（P3）
- **新建**：`runs/agent/doc_utils.py` — 提取 `scan_agent_reading_docs()` 避免循环导入
- **新建**：`runs/agent/doc_state.py` — sha256 变更检测 + 单飞预热（Lock + Event）
- **修改**：`ui_app.py` `_auto_new()` — 启动预热守护线程

### 17.7 改动文件汇总
| 文件 | 操作 |
|---|---|
| `runs/agent/ui_app.py` | 修改（Phase 1/2/3/5/6） |
| `runs/agent/tools.py` | 修改（Phase 3/4/5） |
| `runs/agent/scheduler.py` | 修改（Phase 3/4） |
| `runs/h3/refimage.py` | 修改（Phase 2/5） |
| `runs/h3/upload_watch.py` | 修改（Phase 2） |
| `runs/h3/mediacheck.py` | **新建**（Phase 2） |
| `runs/agent/turn_state.py` | **新建**（Phase 3） |
| `runs/h3_batch.py` | **新建**（Phase 4） |
| `runs/agent/doc_utils.py` | **新建**（Phase 6） |
| `runs/agent/doc_state.py` | **新建**（Phase 6） |

### 17.8 验证
- 6 Phase 全部语法检查通过
- git commit + push → sync_to_spark.py 双端同步
- spark 侧 agent 已重启（端口 7860 监听中，PID 待查）

## 14. 工作文件夹速查（双端）与 Z: 盘路径规范（2026-09-04 增补）

> 目的：新对话/新 Agent 一次性拿到“所有主要工作文件夹在哪”。**先看本表，再决定用哪个路径。**
> 同一套速查也写入 `skills/h3-video-generation.md §0b`（agent 侧必读）。

### 14.1 ⚠️ Z: 盘 = 网络映射盘，禁止使用 Z: 路径
- 本机（Windows 调试机）的 `Z:\` 是经 SSHFS-Win 把 **spark 主目录**（`/home/Developer`）挂载成
  网络盘得来的映射，**仅限本机调试读取方便**，不属于项目正式路径。
- **红线：任何脚本 / 命令 / 配置 / 文档 / skill / git 提交都不得出现 `Z:\…` 路径**——
  换台机器/换个会话就不存在；写路径一律用 spark 侧真实路径（`~/…` 或 `/home/Developer/…`），
  或 Windows 主库路径（`D:\MY_CODING_PROGRAM\videoGenerate-Model-zju`）。

### 14.2 主要工作文件夹一览（实测核对于 2026-09-04）
| # | 位置（规范路径） | 是什么 / 里面有什么 | 维护约定 |
|---|---|---|---|
| 1 | Windows 主库 `D:\MY_CODING_PROGRAM\videoGenerate-Model-zju` | **git 主库**（唯一推 GitHub 的一端，`sakuraahly/videoGenerate-Model-zju`）：全部代码+文档；改代码/文档都在这里 → commit → push → 同步 spark | 配置类机器文件（deploy/llm/llm_mem 等）不入库 |
| 2 | spark 程序副本 `~/videoGenerate-Model-zju` | **spark-local 运行时**：同仓库同结构（本机 Z: 即它的挂载视图）；agent/引擎在此运行；含 `runs/agent/`（ui_app/scheduler/tools/ctx_budget/llm_mem）、`logs/agent_chats/`（会话存档）、`tmp_transfer/`（临时中转） | 随 Windows 同步（sync_to_spark / scp）；spark git 内联身份提交、永不推 GitHub |
| 3 | spark `~/ai/` | **AI 平台目录**：`ComfyUI/`（ComfyUI 代码与运行，systemd `comfyui.service`，端口 8188）、`venv/`（ComfyUI venv）、`models_dl/`（模型下载暂存）、`logs/ runs/ tools/ workflows/`、H3 模型清单 sha（h3-t2v / h3-ref2va.sha256） | ComfyUI **勿重启/勿改 systemd**；同事工作流在 `~/ai/ComfyUI/user/default/workflows/` **只读永不修改** |
| 3a | spark `~/ai/ComfyUI/` 子目录 | `models/`：H3 四件套（diffusion_models 21GB / text_encoders 16GB / vae 5.2GB…）；`input/`（素材，`user_uploads/`=界面直传镜像）；`output/`（产物，视频在 `output/video/`） | 参考图先入 input 再被模板引用；产物由引擎自动落位 |
| 4 | spark `~/Qwen3.8-27B/` | **Qwen 全家桶**：`models/`（NVFP4 ≈21GB 优先，或 `Qwen--Qwen3.8-27B` bf16）、`sglang-venv/`（SGLang 服务 8000）、`vllm-venv/`（备用）、`start_sglang.sh / start_vllm.sh / install_flashinfer.sh`、`start_qwen_agent.py`（**7860 agent 入口**）、`manage_services.sh`、`PROJECT-STATUS.md` | 内存协同见 llm_mem（nap/wake）；ctx=8192 服务端配置在 config/llm_mem.json |
| 5 | spark agent 相关 | 代码=仓库 `runs/agent/`（见 #2）；venv=`~/qwen-agent-venv`；入口=`~/Qwen3.8-27B/start_qwen_agent.py`；tmux 会话 `qwen-agent`（端口 7860）；运行日志 `~/qwen-agent.log`；聊天存档=仓库 `logs/agent_chats/*.jsonl`（缩略图 `thumbs/`） | 重启/查错先看 §12.7/handoff §1；日志时间=北京时间 |
| 6 | spark Open WebUI | venv `~/open-webui-venv2`、tmux `webui`（端口 3000，当前未运行） | 重启必须保留 `HF_HUB_OFFLINE=1` |
| 7 | Windows 侧残留副本 | `C:\Users\39163\ai`（仅 `ComfyUI\input`）、`C:\Users\39163\videoGenerate-Model-zju`（仅 `uploads\`，含 2026-09-04 10:06 一次上传测试产物）——**早期/测试残留的部分副本，不是可用工作副本** | 勿在其中读写；正式路径见 #1/#2 |

- 文档更新范围：本表与 `skills/h3-video-generation.md §0b`、`docs/reference-2026-09-04.md §1`、
  `docs/handoff-2026-09-04.md §6` 口径一致（2026-09-04）。

## 18. 2026-09-04 第六批：会话状态管理 + 任务监控基础架构

### 18.1 新增模块
- **session_state.py**：会话级状态管理中心
  - `_session_tasks`: cid → 任务列表（支持多轮 auto-continue 累积）
  - `_session_turn_ids`: cid → UI 更新令牌（防止旧状态覆盖）
  - `_stop_events`: cid → threading.Event（会话级停止信号）
  - 提供原子操作函数：get/add/clear_tasks, increment/check_turn_id, get_stop_event
  
- **task_watch.py**：ComfyUI 任务后台监控
  - `poll_single(prompt_id)`: HTTP API 查询单任务状态（history/queue 端点）
  - `_monitor_worker(cid, turn_id, queue, stop_event)`: 后台线程，15s 间隔轮询
  - 通过队列推送更新消息（update/done），主循环非阻塞消费
  
- **ui_app.py**：添加 `extract_prompt_ids(text)` 函数
  - 正则匹配 `prompt_id: <uuid>` 和 `TASK_SUBMITTED: <uuid>`
  - 用于从工具输出中提取任务 ID 供监控使用

### 18.2 设计要点
- **避免循环导入**：session_state 为独立模块，不依赖 ui_app/tools
- **非阻塞监控**：后台线程 + queue，主循环用短超时（0.5s）保持响应
- **状态优先级**：turn_id 令牌验证，只有最新 turn 的更新才生效
- **任务累积**：add_tasks() 支持追加，auto-continue 多轮不会丢失前序任务

### 18.3 测试状态
- ✅ session_state.py 语法检查通过
- ✅ task_watch.py 语法检查通过  
- ✅ ui_app.py 语法检查通过（含新增 extract_prompt_ids）
- ✅ 同步 spark 并重启 agent（端口 7860 正常响应）
- ⏳ 待测试：上传大文件反馈、后台监控非阻塞、auto-continue 集成

### 18.4 下一步工作
需要继续重构 `ui_app.py` 的 `send()` 函数以集成：
1. Change 1: 上传按钮 elem_id + JS 即时反馈
2. Change 2: 按钮文案改为"加载所选历史"/"删除所选历史"
3. Change 4: send() 重构（auto-continue 循环 + 任务提取 + 监控启动）
4. scheduler.py Change 4c: SYSTEM_MESSAGE 输出纪律强化

### 18.5 改动文件汇总
| 文件 | 操作 |
|---|---|
| `runs/agent/session_state.py` | 新建（64 行） |
| `runs/agent/task_watch.py` | 新建（175 行） |
| `runs/agent/ui_app.py` | 修改（+30 行，添加 extract_prompt_ids） |

## 19. 2026-09-04 第七批：交接文档与待改进清单

### 19.1 新增文档
- **handoff-2026-09-04.md** - 完整交接文档，包含用户反馈的所有改进点

### 19.2 待改进清单（用户反馈）
1. **性能优化**
   - 调整MONITOR_SEC频率（当前15s）
   - 优化队列大小（当前maxsize=10）
   - 添加超时控制（监控线程无明确超时）

2. **用户体验**
   - 上传等待提示："文件上传较慢，请耐心等待"
   - 按钮文案优化（已完成"加载所选历史"/"删除所选历史"）
   - 增加进度条显示（当前仅文本状态）

3. **功能增强**
   - 任务取消功能（ComfyUI API调用）
   - 改进错误提示（分类+解决建议）
   - LLM流式输出修复（🔴 高优先级）

4. **LLM输出问题**
   - 现状：一次性输出大量文本，非流式
   - 影响：用户等待时间长，体验差
   - 可能原因：qwen_agent Assistant未启用stream模式
   - 建议：检查generate_cfg配置或前端打字机效果

### 19.3 下一步行动
- 短期：修复LLM流式输出、添加上传提示、实现任务取消
- 中期：性能调优、错误提示改进
- 长期：进度条可视化、架构重构

### 19.4 改动文件
| 文件 | 操作 |
|---|---|
| `docs/handoff-2026-09-04.md` | 新建（交接文档） |
| `docs/session-summary.md` | 修改（+§19） |

## 20. 2026-09-05 批次：复读根治（book-16）+ 用户四问反思 + 语音链 P0 升级

### 20.1 本批结论（评审摘要，详细见 docs/planbook/book-16-echo-root-cause.md）
- **复读根因定案**：非模型/服务端；是 qwen_agent 0.0.34 function-call 循环协议与 SGLang 不合（自然文本被误判为未完成工具调用 → 反复重调 LLM 146 次 → 累增=复读观感）。用户最初「内容追加导致重复」判断方向正确。
- **已根治**：自管工具循环（`_one_run` ≤6 轮 + 增量差分解码 + 工具三格式参数解析 + 同参数去重 + 频控 + 直连 SGLang `tools=` 格式 + 清洗回填 + SYSTEM_MESSAGE 铁律）。
- **思维链定案**：`chat_template_kwargs={"enable_thinking": False}`（顶层字段无效且有 400 风险）为 qwen3 tools 模式标准；关闭的是「将英文推理链注入 content」而非内部思考；探针实证（默认 content 被英文链污染 / 关闭后干净中文+有效 `<tool_call>`）。
- **验收口径加严**（docs/dev-workflow.md 新增 §12，强制）：真实 UI send 链 / 界面可见非空文本（done 且 text_len>0）/ 真实产物+可验证参数 / 语音要求时可辨析语音——四者缺一不得称「通过」。

### 20.2 用户四问处置（2026-09-05）
| 用户问题 | 结论与处置 |
|---|---|
| 测试是 Qwen 真调工具还是你替代调用？ | 此前多用脚本化 run_turn/直调——已如实承认；自本轮起以真实 UI 链为准（dev-workflow §12） |
| 每次说测试通过但网页没成功过？ | 口径过宽；「UI 无内容」已修复（ui_app 轮末兜底总结 + 促收尾回填，见 book-16 §6.3） |
| 成品语音混乱不可辨析？ | **根因=t2v 无音频通道（features.audio=false）→ 输出=噪声**；语音链升级 book-14 T2b **P0**（默认 TTS 中文语音+音轨替换+字幕逐句对齐；无本地方案则降级静音轨+字幕并如实标注） |
| 关闭思维链=关闭深度思考？ | 否；model 内部推理保留；见 §20.1 思维链定案 |

### 20.3 本批改动文件
| 文件 | 操作 |
|---|---|
| `runs/agent/ui_app.py` | 修改：工具回填促收尾指令 + 轮末空 final 兜底总结（防「（模型未返回内容）」） |
| `docs/planbook/book-16-echo-root-cause.md` | 修改：台账 #5/#6 定案 + 新增 §6（四问反思/验收口径/UI 修复/思维链结论） |
| `docs/planbook/book-14-lora-accel-delivery.md` | 修改：T2b 语音链升级 P0（P0-1 选型/P0-2 音轨替换/P0-3 自动接线 + 严完成标准） |
| `docs/dev-workflow.md` | 修改：§8 反例补充 + 新增 §12 验收纪律（四条件+报告模板） |
| `docs/session-summary.md` | 修改：+§20（本批） |
| `runs/agent/ui_app.py`（复验期再修） | done占位误追加；自动续接 content=None 的 400；工具结果错误体质兜底；schema 通用 int/bool/number 强转 |
| `runs/agent/tools.py`（复验期再修） | `_coerce_fields` 校验前强转；异常时 audit ok=false |
| `runs/agent/scheduler.py` | 铁律：如实报告工具结果/禁止虚构提交/参数类型/查询带真实 id |

### 20.4 真实链复验结果（2026-09-05 深夜，判据见 dev-workflow §12）
- **链路**：Gradio HTTP send 端点（=前端 send 同链）→ `_one_run` → SGLang → 工具 → 回填 → done；会话经真实会话档存档（logs/agent_chats/*.jsonl）。
- **t0 你好**：done / 66 字 / note ✅（顺带修复：done 文本已流式展示时不再误追加“(模型未返回内容)”占位）。
- **list 素材**：done / 212 字 / ✅ / list_references 真实执行×2（频控上限 2）。
- **gen 生成**：`call_comfyui` ok=true + 真实 `prompt_id`（9dcb5b1e…/535acf00…）；run log 含 submitted/submitted_only + task-watch queued→running 监控；`Status: success / LOCAL_OUTPUT: outputs/video_17.mp4`（1280×736/24fps/124 帧/5.167s/AAC 立体声，817KB）。
- **过程中修复的同类问题**（台账 8-10）：① 参数类型强转（seconds/seed 整数、bool 字符串化）须在校验**前**执行——顺序曾写反导致连败，audit 曾假绿 ok；② 模型虚构“TASK_SUBMITTED/prompt_id”——SYSTEM_MESSAGE 诚实铁律（输出含 `TASK_SUBMITTED: <id>` 才可声称；失败如实转达），修复后模型如实报告失败并二选一征询；③ 断点守卫（上次任务未完成时拦截提交并续传取回）符合预期。
- **口径**：语音类“说话/配音”**仍未通过**——t2v 音频为模型生成环境/氛围音（AAC，2 声道）；人物说话须等 **book-14 T2b P0 TTS 语音链**（P0-1 选型/P0-2 音轨替换/P0-3 字幕对齐接线）。

### 20.5 下一步（按计划书顺序，已更新）
1. book-15 服务编排（SGLang 内存管理/共存参数）+ book-16 台账#6 SYSTEM_MESSAGE 声音决策规则；
2. **book-14 T2b P0 语音链**（TTS 引擎选型 → 音轨替换 → 字幕对齐接线；用户四问最高优先）；
3. book-13 P2-9b 历史会话预览重建 + C3–C5。
4. 有素材/多人称（r2v/人物“说话口型”）链：真实链再验（list 已过；r2v 待有图后验）。

### 20.9 book-13 完结（2026-09-05，按册序）
- **完成**：P0#2（随 book-08 已完）/P0#5（720p/15s dry-run 回归通过）/P0#6（PROBE 回执）/P1#5（segments，真实 LLM 验证待 enabled）/P1#8（审计覆盖确认）/P2#9b（预览重建，真实链 2 项）/P2#11（UTC+8）/P2#12（死隔离清理）/P2#13（seed 默认 auto）。
- **登记保留（低优先）**：§3.2 图片解析收敛、P2#14 预览可判定性标注。
- 提交：win `5253ba5`+`b14a03e` ↔ spark `e70890b`+`300a3a1`；agent=e70890b；单测 162（158+4）全绿。
- **下一册 = book-14（T2b v2 修复批 #1-#5 → T9）**。

### 20.8 整合与执行路线（2026-09-05 用户指示：全部待做整合进计划书→一本一本做）
- **待做已整合**：book-14（T2b v2 修复批 #1-#5：钩子本任务文件/时长守卫/台词字幕/会话级去重/验收客观化；T9 不变）+ book-16（台账 #11-#14 + §6.5 语音/成品验收口径强化 + §6.6 测试纪律）+ book-13（P0#8 标已完成；其余待办见册）。
- **执行序（按册序 01→…→16）**：先清 book-13 剩余（P0#5 回归/P0#6 产出诊断/P1#5 segments/P2#9b 预览重建/#11 时区/#12 turn_state/#13 seed/#14 预览标注/§3.2 低优先）→ book-14（T2b v2 → T9）→ book-15 → book-16 归档闭环。
- 纪律回写：book-16 §6.6（一意图一驱动/队列只读等待/不擅自 force_new/承诺前验证文件本身）随 book-14 落实。

### 20.7 批准后实施记录（2026-09-05，book-17 §5 顺序）
- **§3.1/3.2 参数策略 ✅**：`agent_params.py`（验证档 360p/5s+4 步；交付档 8/20 步）；工具默认+SYSTEM_MESSAGE 三分同步；真实链 `--lora fl2v_4step --resolution 360p --seconds 5` → video_18（608×352/5.167s/124f）。
- **P2.1（指令/数据区/边界描述/动态下发）✅** + **P2.2（Schema 前置校验+修复重试≤3，guard 单测 10 例）✅** + **P2.3（轮级 900s/指纹熔断/会话限流 10 次；回归捕获 getattr bug 修复）✅** + **P2.6 v1（audit injection_flag/validation；人在回路清单）✅** + **P2.2.2 约束解码（负结论：SGLang structured_output 接受但不生效；依赖生成后校验闭环）✅登记**。
- **T2b 语音链 v1 ✅**：P0-1=edge-tts（实测）；P0-2 `runs/h3/tts.py`（apad 保时长/原子替换/三路定位）；P0-3 tts_text→任务记录→完成钩子；真实链 `--tts-text 再见了，故乡。` → **video_23.mp4（608×352/5.167s/124f/AAC 5.167s 完整时长）**。⚠️ **听测判据待用户**（音轨= edge-tts 中文女声 XiaoxiaoNeural；起始 2.06s 语音+静音）。
- **痛点测试 ✅**：W4（4 步 vs 20 步 SSIM 0.864/码率 434k vs 372k）结论回写 T1 策略；**W2（中文招牌“山间茶舍”抽帧目检 0 错字）**——逐字枚举路线有效。
- 全程自动化：`dev.py test（158+20 单测全绿）→ sync → commit`（win 领先哈希 2493c47…742ccb2/321a2fb…，spark 对应）；队列纪律：全部待外部任务自然结束、未取消任何人任务。

### 20.6 计划·待批准（2026-09-05 用户指示：先思考→列计划书→批准后再工作）
- **book-17（新建）**：模型伪造工具调用纵深防御 + 流程自动化合规（必用 `dev.py`；模型/验证一律 spark 项目文件）+ LoRA 必须用上&验证低参档（360p/5s+4 步）+ T2b 语音链联动 + 痛点测试集（音频/中文文字/字幕/低步瑕疵/多段）。待批准项见 book-17 §7（A–F）。
- **book-14 更新**：T1 策略补丁（LoRA 默认验证档 4 步）；T2b 置顶为批准后第一优先；取消条件保留（无本地 TTS → 静音轨+字幕并如实标注）。
- **未批准前不改运行代码**；后续任何改动一律 `dev.py check → test → sync → commit` 自动化闭环。

