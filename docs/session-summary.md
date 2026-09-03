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
  tests\test_h3.py          74 项单测
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
4. spark 上 ComfyUI 可能由 **tmux 会话 comfyui** 或**裸进程**运行（本机看到的裸进程已被
   `bats\service\StartComfyUI.bat` 重新纳管为 tmux）。判断“是否在跑”一律按**端口探测**
   （`ss -ltn | grep :8188`），不要假设 tmux 一定存在。

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
1. **ComfyUI 需修复依赖（2026-09-03）**：`comfy_kitchen` 模块缺 `int8_attention_is_available`
   属性，启动报 `AttributeError`。正在 `pip install --upgrade comfy_kitchen`（后台进行中）。
   修复后：`bash ~/videoGenerate-Model-zju/shell/manage_services.sh start` 可一键全启。
2. **开机自启已配置（2026-09-03）**：XDG autostart `.desktop` → `start_all_services.sh`
   协调启动（先停 ComfyUI → SGLang 加载 2min → 再启 ComfyUI → qwen-agent → Open WebUI）。
   管理命令：`bash ~/videoGenerate-Model-zju/shell/manage_services.sh {start|stop|restart|status|enable|disable|logs}`。
   SGLang 共存模式 `mem=0.55`（独占模式改 0.95）。
3. **Qwen-Agent 调度器端到端已验证（2026-09-03）**：
   - `call_comfyui` dry_run 成功（t2v 参数验证通过）
   - `run_script` idea2prompts dry-run 成功
   - SGLang 无需 `--enable-auto-tool-choice`（qwen-agent nous 模式绕过）
   - tmux `qwen-agent` 端口 7860，Gradio Web UI 可用
4. **Open WebUI 已运行（2026-09-03）**：tmux `webui`，端口 3000。
   访问：`http://spark:3000`（或隧道 `ssh -N -L 3000:127.0.0.1:3000 spark`）。
   首次访问需注册管理员账号。重启务必保留 `HF_HUB_OFFLINE=1`。
5. **AI 桥：已基本接通，待全量验证**：idea2prompts 单槽（api_t2v）端到端成功一次。
   待全槽位生成 + `bats\prompts\ai_prompts.bat` 交互验证。
6. **本地语义已全覆盖**：video t2v/i2v/r2v/flf2v 均已本地实跑出片。
7. **维护提醒**：
   - 同事更新 spark 模板后，`bats\workflow\sync_remote_workflows.bat` 拉齐镜像。
   - spark 服务管理统一用 `manage_services.sh`（不再手动 tmux）。
   - ComfyUI venv 在 `~/ai/venv/`（非 `~/ai/ComfyUI/venv/`）。
8. 可选项：把”创意→提示词”做成单页 GUI/Web 入口；为 6 工作流补”参考图自动回传/占位符”
   自动化；危险用例回归测试（目录穿越、提示注入等）。

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
