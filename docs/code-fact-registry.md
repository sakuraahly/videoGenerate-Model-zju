# 代码事实登记表（Code Fact Registry）— 全仓唯一口径

> 版本：v1.0 · 日期：2026-09-04 · 性质：**单一事实源**。凡路径/端口/常量/工具数/部署形态/模型/模板，改动前先查本表；
> 与本表冲突的文档以**运行中代码/实测**为准，并回写本表与相关文档（见 START-HERE §5）。
> 机器可读侧：`runs/agent/runtime_check.py` 中的 `FACTS`（与本表同源，改这里须同步）。

---

## 1. 仓库拓扑与权威（谁是真源、谁被谁覆盖）

| 位置 | 角色 | 说明 |
|---|---|---|
| `D:/MY_CODING_PROGRAM/videoGenerate-Model-zju`（Windows 主库） | **源码真源** | 唯一推 GitHub 的一端；一切改动先改这里 |
| `git@github.com:sakuraahly/videoGenerate-Model-zju.git`（GitHub） | 镜像/备份 | 仅由 Windows push；spark 永不 push |
| `/home/Developer/videoGenerate-Model-zju`（spark 运行时） | **运行实例** | 由 sync_to_spark.py（或定点 scp）同步；git 仅本地记录 commit（内联身份 Developer/dev@spark）；磁盘代码=运行代码 |
| ⚠️ `C:/Users/39163/videoGenerate-Model-zju`、`C:/Users/39163/ai` | 残留部分副本 | **勿用**（只有 uploads 等残留）；注意：`scheduler.py` 会把 `VIDEOGEN_PROJECT_ROOT` 设为 `expanduser(~/...)`，Windows 上会指到该残留——代码一律以 `__file__` 推导根目录 |
| ⚠️ `Z:/...` | 网络映射盘 | **禁用**；一律写 spark 真实 `~/...` 或 Windows 主库 |

### 1.1 两端本就不同、不随 sync 覆盖的文件
- `config/deploy.json`、`config/llm.json(.bak)`、`config/pipeline.json`、`config/transfer.json`、`config/autosync.json`、`config/upload_watch.json`、`.sync-state.json`、`last_job.json`、`.tunnel.json`、`.run.lock`；产物 `logs/`、`outputs/`；审计 `workflows/h3_*`、`workflows/batch_*`（排除清单见 `runs/sync_to_spark.py EXCLUDE_*`）。

---

## 2. 服务端口与环境

| 服务 | 端口 | 位置 | 说明 |
|---|---|---|---|
| SGLang 本地 LLM | 8000（127.0.0.1） | spark | Qwen3.8-27B；ctx=8192；共存 mem≈0.50-0.55 |
| ComfyUI | 8188（127.0.0.1） | spark | systemd `comfyui.service`，**勿重启/勿改 systemd** |
| Agent（Gradio，本仓库调度器） | 7860 | spark | **tmux 会话 `agent`**（会话名不是 `qwen-agent`）；启动：`cd /home/Developer/videoGenerate-Model-zju && /home/Developer/qwen-agent-venv/bin/python runs/agent/scheduler.py 2>&1 | tee ~/agent.log` |
| Open WebUI | 3000 | spark | 纯聊天，无工具调用能力；当前未启用 |
| 部署形态 | — | 按端 | **Windows 主库**=win-remote（ssh 隧道）；**spark 运行时**=spark-local（同机直连）；两端各自合法，切换用 `runs/h3/deploy.py --set` |

---

## 3. 关键路径

| 用途 | 路径 | 备注 |
|---|---|---|
| spark 运行时仓库 | `/home/Developer/videoGenerate-Model-zju` | git 最新见版本指纹 |
| spark ComfyUI | `~/ai/ComfyUI` | `input/`（含 user_uploads 镜像）、`output/`（产物）、`user/default/workflows/`（**同事模板只读**） |
| spark Qwen venv（agent） | `/home/Developer/qwen-agent-venv` | `bin/python` 为调度器运行时解释器 |
| spark LLM 模型 | `~/Qwen3.8-27B/models/NVFP4` | 扩散模型等；入口 `start_qwen_agent.py`（薄壳→ `runs.agent.scheduler.main`） |
| 工作流模板镜像 | `workflows/remote_workflows/` + `config/templates/` | 只改镜像；spark 同事模板永不修改 |
| 输出 | `outputs/`（spark-local 直存）/ scp 下载（win-remote） | 产物 `video_N.mp4` |
| 运行日志 | `logs/run_<ts>_<ms>.log` 等 | 见 `docs/planbook/book-11`（日志体系） |
| 会话存档 | `logs/agent_chats/<cid>.jsonl`（spark） | user/assistant 轮次 |

---

## 4. 关键常量（与 `runs/agent/ctx_budget.py` / `runtime_check.FACTS` 同源）

| 常量 | 值 | 含义 |
|---|---|---|
| `MODEL_MAX_CTX_TOKENS` | 8192 | SGLang 服务端 ctx 硬顶（改服务端须同步 llm_mem.json/start 脚本/本表） |
| `REPLY_MAX_TOKENS` | 2048 | 单轮回复预算 = completion 上限 |
| `UI_TRIM_TOKENS` | 2200 | 界面/CLI 历史裁剪预算（**skills 文档曾写 1800，以本表为准**） |
| `CONV_MSG_BUDGET_TOKENS` | 2500 | 对话部分硬预算 |
| `TOOL_PRELUDE_TOKENS` | 1500 | nous 工具模板固定开销 |
| `SAFETY_TOKENS` | 300 | 计数偏差/模板特判余量 |
| `LLM_CFG.generate_cfg.max_tokens` | 2048 | 调度器 completion 上限（与 REPLY_MAX_TOKENS 一致） |
| `_SCRIPT_TIMEOUT`（tools.run_script） | 120s | ⚠️ 与 h3_batch `--timeout` 默认 600 错配（book-07 待修） |

---

## 5. Agent 工具与消费说明

- **白名单工具（6 个）**：`run_script` / `modify_workflow` / `call_comfyui` / `read_doc` / `list_references` / `batch_submit`（**旧文档多处写"5 工具"，以本表为准**；需在 spark（qwen_agent）环境才可导入）。
- 阶段（stage）：`t2v / i2v / r2v / flf2v`（本地 `video_*`；`api_*` 云模板不使用/不提及）。工作流注册表统一化见 `docs/planbook/book-12`。
- 生成提示词规则：英文；属性词库见 `docs/prompt-taxonomy.md`（10 正 + 9 负）；模板内嵌只留图像属性词（book-06 待实施）。

---

## 6. 模型与模板事实

- H3 四件套（spark `~/ai/ComfyUI/models/`）：diffusion `*_pruned_int8_convrot.safetensors`(21GB)、text_encoder `qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors`(16GB)、video VAE `fp16`(5.2GB)、audio VAE `fp32`(0.6GB)；清单 sha 见 `config/minimax_h3_models.json`。
- 模板族：`video_minimax_h3_{t2v,i2v,r2v,flf2v}.json`（本地推理；flf2v 为本地扩展双帧变体）；`api_minimax_h3_*`（Comfy 云通道，不使用）。
- 分辨率预设：360p(608×352)/480p/540p/720p(1280×736,推荐)/768p(1344×768)；帧数须满足 17k+5 网格。

---

## 7. 相关核对工具

- `python runs/agent/runtime_check.py`：运行时一致性（常量/工具/形态/路径/版本指纹），`[DIFF]`=不一致。
- `python runs/consistency_check.py`：静态一致性（含 runtime_check 汇总）。
- `python tests/e2e_smoke.py`：防绕过基座门禁（smoke），输出 `SMOKE_OK`。
- `python runs/dev.py check`：三端状态漂移核对（含 spark 是否含本提交）。

---

## 8. 素材上传/镜像命名与防覆盖（2026-09-05 定稿）

- 归档：`uploads/YYYYMMDD/<sha8>_<原名>`；镜像：`<ComfyUI>/input/user_uploads/<sha8>_<原名>` —— **均带 sha8 前缀**，同名不同内容的图片互不覆盖（修复前镜像用原名，后传同名会覆盖先传，导致素材池只见一张）。
- `ingest_upload` 的去重与归属：按内容 sha（16 位）全局去重；重复上传仍写一行（`dup:true`+`cid`）供会话归属；同名不同图=两个不同 sha=两行、两归档、两镜像。
- 旧镜像（无 sha8 前缀、原名）仍被 `stage._resolve_input_image` 递归命中，不需迁移；新上传一律新命名。
- 上传预览（Gradio Gallery）**累积展示本会话全部预览**（book-11 修复：后上传不再覆盖先上传的预览），切换/新建会话时清空。

---

## 9. 会话保留策略（book-14 L1，2026-09-05）

- 策略配置：`config/session_retention.json`（**全项目统一、入库 tracked，非机器配置**，不进 dev.py EXCLUDE_FILES）：`{"enabled": true, "days": 90, "dry_run": true}`；缺失/损坏回退内置默认（90 天）。
- 会话存档路径：`logs/agent_chats/<cid>.jsonl`（对话）+ `<cid>.meta.json`（`run_log`/`ts`/`n_msgs`，见 `ui_app.save_chat`）；随 `logs/` gitignore，仅本机/运行时存在。
- 判定基准：文件 mtime 与 `meta.ts`（格式 `%Y-%m-%d %H:%M:%S`）的**较新者**（取 max）；超过 `days` 才算超期——只要有一个信号说明"最近动过"就不删（宁可漏删不可误删）。
- 删除边界（红线）：**只删聊天档** `<cid>.jsonl` 与 `<cid>.meta.json`；`thumbs/<sha>.jpg` 按内容 sha 命名、无法关联 cid → **一律不删**；严禁触碰 `uploads/`、`workflows/`、`outputs/`、`logs/run_*.log`（运行期产物）。
- 命令：`python runs/agent/session_cleanup.py status`（统计总数/超期/保留）｜`clean`（默认 dry-run，打印将删清单）｜`clean --yes`（真正删除）｜`clean --days N`（覆盖保留天数）。返回 `(统计字典, exit_code)`，纯手动 CLI，不接生成流程。