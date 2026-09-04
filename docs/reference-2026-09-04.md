# 项目总参考手册（2026-09-04 版）

> 本文件是**详细工程参考**：配置注册表、运行形态语义、引擎/工具/Agent 接口契约、
> 模板明细、服务与内存管理、日志/审计 schema、故障字典、测试模板。
> 快速交接与测试清单见 `docs/handoff-2026-09-04.md`；事实源 `docs/session-summary.md`。
> 双端：Windows 本机（git 主库→GitHub）与 spark `~/videoGenerate-Model-zju`（spark-local 运行时）。

---

## 1. 环境与主机约定

| 项 | 值 |
|---|---|
| 远程主机 | ssh 别名 `spark`（免密）；DGX Spark GB10 / aarch64 / CUDA 13.0 / SM12.1 / **统一内存 121GB 可用** |
| 端口 | 8000 LLM(SGLang) · 8188 ComfyUI · 7860 Agent 界面 · 3000 Open WebUI(当前未启) |
| Windows 仓库 | `D:\MY_CODING_PROGRAM\videoGenerate-Model-zju`（主库，推 GitHub `git@github.com:sakuraahly/videoGenerate-Model-zju.git`） |
| spark 仓库 | `~/videoGenerate-Model-zju`（只留本地 git 记录，永不推 GitHub；commit 需内联身份 `-c user.name=Developer -c user.email=dev@spark`） |
| 运行时形态 | `config/deploy.json` site：**spark-local（现状/交付）** / win-remote（本机+隧道） |
| 时间口径 | 本地日志=北京时间；spark ls/journalctl=UTC（差 8h） |
| 文档同步 | 改 Windows→commit→`git push`→`sync_to_spark.py`（排除机器配置/产物）→spark commit；自动合并 `sync_auto.py` |

## 2. 目录结构全图（项目根，spark 侧同构）

```
bats/                 Windows 双击入口：generate/{run,menu}.bat  config/{edit,mode}.bat
                      prompts/{prompts,ai_prompts}.bat  workflow/{pipeline_setup,workflow_setup,
                      sync_remote_workflows,sync_to_spark,autosync}.bat  service/{StartComfyUI,StopQwen}.bat
shell/                PS1 引擎+lib+ForSparkService；spark bash：manage_services.sh start_all_services.sh
                      stop_qwen.sh comfyui_only.sh(废弃) spark_{sglang_start,vllm_start,vllm_smart_start,
                      manage_services,check,chat_setup,install_flashinfer,download_qwen3.8_27b}.sh
                      start_sglang_coexist.sh(默认启动器) systemd/{sglang-qwen,qwen-agent,open-webui}.service
runs/                 CLI/引擎/工具包
  h3_submit.py        引擎 CLI（退出码契约见 §4）
  h3/                 params,workflow,templates,stage,comfy,jobstate,prompts,uiapi,subgraph,
                      idea2prompts,deploy,capabilities,logutil,refimage,upload_watch
  agent/              scheduler.py(系统提示) tools.py(5工具) ui_app.py(7860界面)
                      llm_mem.py(nap/wake) test_security.py test_tool_calling*.py
  h3_text2img.py(H3 5帧) h3_text2img_flux.py(FLUX, site-aware) sync_to_spark.py sync_merge.py
  sync_auto.py consistency_check.py
config/               environment.json deploy.json pipeline.json transfer.json llm.json(gitignore)
                      llm_mem.json(机器) upload_watch.json(机器) autosync.json(机器)
                      capabilities.json minimax_h3_models.json prompt_blueprints.json templates/
prompts/              manifest.json positive/negative_prompts.txt workflows/<slot>.{positive,negative}.txt
workflows/            remote_workflows/(7 镜像) h3_<ts>_<ms>/(运行审计) h3-flat-template.json
parameters/video.txt  resolution/seconds/seed/fps/steps/timeout
outputs/ logs/ uploads/ refs/  skills/ docs/ ai_daily_reports/(已删) agent_chats?→logs/agent_chats
```
> 机器级（不参与两端同步、不入库）：config/{deploy,llm,pipeline,transfer,autosync,upload_watch,
> llm_mem}.json、.sync-state.json、last_job.json、.tunnel.json、.run.lock、outputs/logs/uploads、
> workflows/h3_*、根目录 *.mp4。

## 3. 配置文件注册表

| 文件 | 关键键/默认 | 机器级 | 维护入口 |
|---|---|---|---|
| environment.json | remote_host=spark; remote_comfyui_dir=~/ai/ComfyUI; remote_output_dir=~/ai/ComfyUI/output; comfyui_port/local_port=8188; ssh 超时 20s/keepalive 15×4; max_attempts=3; retry_delay=5; scp_attempts=3 | 否(示例一致) | 手改 |
| deploy.json | site=win-remote|spark-local；sites.win-remote{tunnel,via_ssh_tunnel,scp,llm 8011}；sites.spark-local{local_http,local_cp,llm 8000} | 是(两端各自) | `bats\config\mode.bat` / `runs\h3\deploy.py --show/--set` |
| llm.json | enabled=true; kind=openai_compatible; base_url(形态自动切 8000/8011); api_key 可空; model=Qwen3.8-27B; temperature .7; timeout 600; max_tokens 4096 | 是 | ai_prompts 使用 |
| llm_mem.json | enabled=true; mem_fraction=0.50; context_length=8192 | 是 | llm_mem.py/手动 |
| upload_watch.json | enabled; interval=30; openwebui_data_dir=~/.cache/open-webui | 是 | upload_watch.py |
| autosync.json | enabled=false; interval=180 | 是 | sync_auto.py |
| pipeline.json | default_stage=t2v; templates_dir=workflows/remote_workflows; stages{t2v builtin; i2v/r2v/flf2v template_kind=ui}; remote_workflow_templates | 是 | pipeline_setup.bat |
| transfer.json | remote_upload_dir; active_workflow_dir; use_active_workflow | 是 | workflow_setup.bat |
| capabilities.json | engine/models; workflows(本地4+云端3); tools(2); prompt_slots; note_for_llm; llm_role_guard; download_policy | 否 | 工具只读；`runs\h3\capabilities.py --doc` 重生成 docs/capabilities-ai.md |
| prompts/manifest.json | default(legacy 两文件); slots=video_t2v/i2v/r2v/flf2v+api_t2v/r2v/flf2v(槽位文件映射) | 否 | prompts.bat |
| parameters/video.txt | resolution=360p; seconds=5（可加 seed/fps/steps/timeout） | 否 | edit.bat |
| minimax_h3_models.json | 4 模型清单(名称/大小/sha256/modelscope 源) | 否 | menu[5] 自检 |
| prompt_blueprints.json | global_rules+slots 说明文本 | 否 | idea2prompts 读 |

## 4. 引擎 CLI 契约（runs/h3_submit.py）

- 模式：`--stage t2v|i2v|r2v|flf2v`（pipeline 注册表/内置回退）；`--template <UI或API json>`；
  `--workflow-file <已存API>`（原样提交，禁止与其它参数混用）；`--resume <prompt_id>`；
  `--submit-only`（提交即打印 `TASK_SUBMITTED: <id>` 返回）；`--dry-run`（agent 路径 H3_CONCISE=1 精简输出）；`--force-new`；`--image` 可多次。
- 覆盖参数：`--resolution 360p..768p --seconds --seed(int|auto) --steps --fps --timeout --prompt/--prompt-file --negative-prompt* --output`。
- **退出码**：0 成功（打 `REMOTE_VIDEO_PATH:`，spark-local 另有 `LOCAL_OUTPUT: outputs/video_N.mp4`）；2 可恢复(断点保留，无参重跑=续传)；3 确定性失败；90 内部。
- 帧数=17k+5 网格（5s→124@24fps…）；分辨率表 360p608×352/480p864×480/540p960×544/720p1280×736/768p1344×768。
- 断点：`last_job.json{prompt_id,remote_path,...}`；成功且无编排(H3_KEEP_BREAKPOINT)即清；任务目录 `workflows/h3_<ts>_<ms>/{workflow_api,workflow_ui,job.json}`。
- 日志事件链：`start argv`→`task …`→`workflow_saved dir=`→`submitted/submitted_only`→
  `completed remote=… elapsed=N` →（spark-local）`local_output`→`root_state_cleared`；失败 `err …`。

## 5. 工具与脚本速查（spark 或按形态）

| 命令 | 用途/要点 |
|---|---|
| `python3 runs/h3/refimage.py list [--pool in|up|out] [--name kw] [--all] [--limit N]` | 素材三池（up 优先，仅图默认；input/uploads 递归） |
| `refimage.py promote --name <id|文件>` | 复制进 ComfyUI input（幂等） |
| `refimage.py use --name <id> --stage r2v --slot N` / `--info` / `--undo` | 设参考槽(自动启用+接线)/查看/还原；r2v 8 槽(0/1 启用,2-7 禁用)，flf2v 2 槽(0 首/1 末)，i2v 单槽 |
| `refimage.py grow --stage r2v --total N` | 模板扩槽（autogrow 行+禁用占位 LoadImage） |
| `python3 runs/agent/llm_mem.py {status|nap|wake --timeout 900|flush}` | SGLang 内存协同；nap 只停 sglang；wake 按 llm_mem.json 拉起并轮询 /v1/models |
| `python3 runs/h3/upload_watch.py {status|once|watch} [--dir] [--dry-run]` | Open WebUI uploads 收件箱（数据目录 ~/.cache/open-webui） |
| `python3 runs/sync_auto.py {enable --daemon --interval N|disable|status|once}` | 双文件夹自动合并（逐文件取新，冲突人工 resolve） |
| `python3 runs/h3/idea2prompts.py --idea "…" [--workflow slot] [--force|--dry-run]` | 创意→槽位 JSON（护栏只当提示词生成器） |
| `python3 runs/h3/deploy.py --show/--set` | 形态切换（联动 llm.json，bak 备份） |
| `python3 runs/consistency_check.py` | 静态审计（manifest/槽位/模板图 site-aware） |
| `python3 runs/sync_merge.py {--status|--pull-auto|--push-auto|--resolve f --from local|remote|--make-base}` | 双端逐文件同步基线 |
| `python3 runs/sync_to_spark.py` | 整仓(不含 .git/机器配置/产物)同步到 spark |

## 6. Agent（7860）契约

- 5 工具：`run_script`（runs/*.py 白名单，realpath，超时120s 保留 partial+prompt_id）、
  `modify_workflow`（仅镜像/templates 目录）、`call_comfyui`（stage/resolution/seconds/seed/prompt/
  dry_run/wait_until_done/force_new；默认 submit-only）、`read_doc`（docs/agent-reading 动态清单）、
  `list_references`。
- SYSTEM_MESSAGE 固定约束：工作流只用本地组(t2v/i2v/r2v/flf2v)；单轮 ≤600 字；提交即结束本轮等
  下一轮“继续/取片”；结论带依据；多图转场=逐对 flf2v 分镜（见 04 §6 模板）；禁止越权（无 shell/
  服务控制/任意文件）。
- 界面(ui_app.py)：自动新会话+显示 id；历史加载/删除/刷新；上传(两段式+sha去重+缩略图预览)；
  发送自动清空+幂等锁；⏹中止本轮（服务端请求可能仍在完成）；状态条=`处理中 Ns·LLM:…·引擎:<末行日志>`；
  上下文预算 MAX_CTX_CHARS=6000（≈3k token）、保留首轮+最近4轮；回复上限 REPLY_MAX_TOKENS=2048；
  并发放开 default_concurrency_limit=16，send concurrency_limit=1。
- 会话存档 schema：`logs/agent_chats/<ts>_<rand>.jsonl` 每行 {ts,role,content}（user/assistant）；
  上传缩略图 `logs/agent_chats/thumbs/<sha>.jpg`（allowed_paths 放行 thumbs/user_uploads/uploads）。

## 7. 工作流模板明细（本地镜像，改动边界）

| 文件 | 角色 | 槽位 | 备注 |
|---|---|---|---|
| video_minimax_h3_t2v.json | 本地文生(官方标准, UUID子图) | 无图 | 引擎自动解组 |
| video_minimax_h3_i2v.json | 首帧图动起来(UUID子图) | 1 | 默认 hero |
| video_minimax_h3_r2v.json | 多参考图(MiniMaxH3ReferenceToVideo, autogrow ref_images) | **8**(0/1启用,2-7禁用) | use --slot 自动接线 |
| video_minimax_h3_flf2v.json | 首帧+末帧(本地双帧变体) | 2(0=首帧 hero,1=末帧 alley) | 顶层 LoadImage,子图含 H3 节点 |
| api_minimax_h3_*.json | Comfy 云模板(需登录) | — | **不使用/不提及**(能力面已剔除) |
- 红线：只改本地镜像；spark 平台 `~/ai/ComfyUI/user/default/workflows/`（同事模板）**永不修改**；
  `--enable-manager` 保留勿动；ComfyUI 服务勿重启/勿改 systemd。

## 8. 服务与内存管理矩阵

| 操作 | 命令（spark） | 影响 |
|---|---|---|
| LLM 停(让位) | `python3 runs/agent/llm_mem.py nap` / `bash shell/stop_qwen.sh` | 只停 SGLang(或含 agent/webui)；ComfyUI 不动 |
| LLM 启 | `llm_mem.py wake` / `manage_services.sh start` / 人工 tmux | 按 0.50/8k；约 120s；flashinfer JIT 需 venv/bin 在 PATH |
| ComfyUI 临时腾内存 | `curl -X POST :8188/free -d '{"unload_models":true,"free_memory":true}'` | 只卸权重(49→18GB)，下任务自动重载；非重启 |
| 全服务 | `manage_services.sh {status|start|stop|logs}` | 会动 ComfyUI 启动顺序（人工场合） |
| 自动让位 | 界面/CLI 回合文本含 `TASK_SUBMITTED:` 自动 nap；下轮自动 wake | 见 llm_mem |

实测：SGLang 0.50/8k 就绪 ~120s；ComfyUI 空闲(卸载后)~18GB；双驻 used≈64-65GB、available≈56GB；
预载≈49GB ⇒ 0.40 必失败；0.55/32k 旧方案占用过大已弃。

## 9. 故障字典（先看状态条“引擎:”行与日志）

| 现象 | 首要检查 | 处置 |
|---|---|---|
| 界面红错 | ~/qwen-agent.log 尾部 Traceback | 多为组件/接线异常；按堆栈修复后重启 agent |
| 上传无反馈/慢 | 并发被长回合占用？(旧版已修)；预览是否走 thumbs | Ctrl+F5；单文件测；看 up_status 横幅 |
| 上传成功但无预览 | thumbs 是否存在/allowed_paths | 检查 logs/agent_chats/thumbs/ 与 demo allowed |
| agent“无输出卡死” | 状态条 LLM/引擎行、~sglang.log、logs/run_*.log | 是否在唤醒(1-3min)；否则点⏹中止并复现记录 |
| 提交后 8000 停了 | 正常：nap 让位 | 下一轮自动 wake |
| 重复生成/旧档冒充 | last_job.json 残留？ | 直跑成功已自动清；必要时 --force-new |
| 模型回复被截断 | 单轮太长/ctx 8192 | 发“继续”；控制单轮 ≤600 字 |
| flf2v/r2v 图不对 | 槽位未设/模板被覆盖 | refimage use --info；重设后提交；结束时 --undo |
| ninja 缺失 | PATH 未含 venv/bin | 已修复；若再犯手动 export PATH |

## 10. 下一轮测试模板（回写约定）

新对话执行后按表格在 handoff-2026-09-04.md §5 下记录：
| 项目 | 操作 | 期望 | 实测 | 结论 |
|---|---|---|---|---|
| 上传大图 | 单张 4.5MB PNG | ≤数秒✅+缩略图 | … | |
| 上传幂等 | 重选同批 | ⏩跳过/不重复 | … | |
| 新对话/加载 | 点击响应 | 即时(不排队) | … | |
| 发送清空+锁 | 处理中点发送 | 提示忽略 | … | |
| 状态条 | 长任务观察 | LLM/引擎行持续更新 | … | |
| 中止 | ⏹按钮 | 快速收尾可再发 | … | |
| 多图转场 | 10图逐对flf2v | 逐段TASK_SUBMITTED+取片+拼接清单 | … | |
| nap/wake | 提交后→下轮 | LLM让位→自动唤醒 | … | |
| 产物边界 | outputs/ | LOCAL_OUTPUT 一致 | … | |
| 异常取证 | 任何红错 | 文本+状态行回写 | … | |

---
维护约定：任何变更后同步更新本手册与 handoff、session-summary；spark 侧与 GitHub 保持一致。
