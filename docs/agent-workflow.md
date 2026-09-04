# 本地 Agent（Qwen）工作链详细手册

> 面向：在 spark 上使用本地 Qwen Agent 出片的所有人 / 需要理解“一句话 → 成片”内部
> 流程的后续维护者。事实源：`docs/session-summary.md`；工具参数速查：
> `docs/agent-reading/01-tools-reference.md`；任务执行协议速查（给模型自己看）：
> `docs/agent-reading/04-agent-workflow.md`。

---

## 1. 总体架构：两个界面、一条工作链

```
┌──────────────────────── 用户 ────────────────────────┐
│ ① http://spark:3000  Open WebUI  纯聊天 + 文件上传    │
│ ② http://spark:7860  Qwen-Agent  带工具的执行入口     │
└──────────────┬──────────────────────────┬─────────────┘
               │ 对话(无工具)              │ 对话(有工具)
               ▼                          ▼
         SGLang 8000 ◄────────────── Qwen3.8-27B（受限调度器 scheduler.py）
         (Qwen3.8-27B,                 │ 工具层 tools.py（5 个白名单工具）
          OpenAI /v1)                  ▼
                             引擎 h3_submit.py / idea2prompts.py /
                             h3_text2img*.py / refimage.py / upload_watch.py
                                       ▼
                               ComfyUI 127.0.0.1:8188（H3/FLUX 推理）
                                       ▼
                       产物 → ComfyUI output +（spark-local）程序文件夹 outputs/
                       审计 → workflows/h3_*/job.json + logs/run_*.log
```

**分工（重要）**
| 入口 | 端口 | 能力 | 何时用 |
|---|---|---|---|
| Open WebUI | 3000 | 纯聊天（无工具）；**文件上传**入口 | 日常问答；上传参考图/视频素材 |
| Qwen-Agent | 7860 | 受控工具调度（生成视频/图、改工作流、读文档、列素材） | 所有“帮我生成/修改/查询”类任务 |

> 上传文件 ≠ 直接可用：Open WebUI 把附件存到它自己的数据目录，由
> `upload_watch` 看门狗收进项目素材池（见 §5），之后在 7860 让 agent 使用。

## 2. 运行形态与“程序文件夹隔离”

- **spark-local（交付/现状）**：项目在 spark `~/videoGenerate-Model-zju`，与
  ComfyUI、Qwen 同机。产物直接落**本机** `outputs/`（`LOCAL_OUTPUT:` 行），无 scp。
- **win-remote**：项目在 Windows，ComfyUI/Qwen 在 spark，经 ssh 隧道访问；产物由
  编排层 scp 拉回本地 `outputs\`。

`config/deploy.json` 的 `site` 决定分支；`sync_to_spark.py` 已排除两端机器配置，
形态不会因同步被覆盖。参考素材类命令（refimage）在 win-remote 下自动经
`ssh spark` 委托 spark 执行。

## 3. Agent 工具层（tools.py 五个受控工具）

| 工具 | 作用 | 关键安全约束 |
|---|---|---|
| `run_script(script, args)` | 运行白名单脚本（runs/ 下 .py） | realpath 前缀校验、禁 `..`/绝对路径、输出截断 ≤5000、超时 120s（超时保留 partial output 与 prompt_id） |
| `modify_workflow(workflow_path, changes)` | 改工作流 JSON 节点（如 LoadImage 参考图名） | 仅 `workflows/remote_workflows/` 与 `config/templates/`；不改 spark 原生目录 |
| `call_comfyui(stage, …)` | 提交生成任务 | 参数 enum 校验；默认“提交即返回”（见 §4） |
| `read_doc(filename)` | 读 docs/agent-reading/ 参考文档 | 仅该目录 .md/.txt，截断 ≤5000 |
| `list_references()` | 列出参考素材（ComfyUI 已存图/input/上传收件箱） | 只读 |

模型**没有** shell、任意文件、web、系统管理能力；用户若要求此类操作，agent 应
拒绝并说明需人工操作（服务启停由 `manage_services.sh` 人工执行）。

## 4. 提交 / 等待分离 —— 最关键的工作链约定

**背景教训**：早期 call_comfyui 单次调用最多等 600s，视频生成超过即报
“提交超时 (600s)”——但任务其实已提交并在 ComfyUI 正常跑，报错还丢了 prompt_id，
用户无从续传，只能重跑/误判。

**现行协议（h3_submit.py 实现）**：
1. **提交即返回**：`call_comfyui` 默认带 `--submit-only`——提交成功立即打印
   `TASK_SUBMITTED: <prompt_id>` 并返回（秒级），任务在 ComfyUI 后台运行；
   断点 `last_job.json` 保留（服务“进行中/中断恢复”，成功后直跑自动清除）。
2. **等待/取件分开做**：需要完成结果时，让 agent 用 `run_script` 运行
   `runs/h3_submit.py`（**不带任何参数**）→ 自动续传原任务并轮询到完成 →
   输出 `REMOTE_VIDEO_PATH:` 与（spark-local）`LOCAL_OUTPUT: outputs/video_N.mp4`。
3. **绝不重复提交**：任务已在跑时再次要求“新任务”会命中断点拦截（提示加
   `--force-new` 才开新）；agent 的正确动作是续传查询，而不是另开任务。
4. 等待工具超时（run_script 120s）也只会中断轮询进程，任务不受影响；再次无参
   重跑即可续等——工具输出会保留 partial output 与 prompt_id 提示。

**退出码契约**：0=成功（含标记行）｜2=可恢复（网络/轮询超时，断点保留）｜
3=确定性失败｜90=内部错误。

## 5. 参考素材工作链（图生视频 / 参考图）

```
Open WebUI 上传图片/视频
   │  └─ 文件落 ~/.cache/open-webui/uploads
   ▼
upload_watch（tmux 会话 upload-watch，30s 周期）
   ├─ 归档：  uploads/YYYYMMDD/<sha8>_<原名>
   ├─ 流水：  uploads/log.jsonl（sha 去重）
   └─ 图片镜像：ComfyUI input/user_uploads/<原名>（LoadImage 立即可选）
        ▼
refimage.py list          （三池：in=ComfyUI input / out=ComfyUI output 已存图
                            递归 / up=上传收件箱）
        ▼
refimage.py promote --name <id>          （复制进 ComfyUI input）
refimage.py use --name <id> --stage r2v  （改写本地镜像模板 LoadImage 指向该图）
refimage.py use --undo                   （git 还原模板）
        ▼
call_comfyui(stage="i2v"/"r2v"/"flf2v", prompt=…)  → §4 流程出片
```

- 素材 id 形如 `out:3`（out 池第 4 项）；win-remote 下 refimage 自动 ssh 委托 spark。
- agent 可直接 `list_references` 看素材，再经 `run_script("h3/refimage.py", …)`
  选用；参考图视频生成用 `call_comfyui(stage="r2v")`。
- 语义：`video_minimax_h3_i2v.json`=首帧图动起来；`r2v`=多张参考图（人物/场景/道具，模板默认 8 槽、可 grow 扩）；
  `flf2v`=首帧+末帧（本地双帧变体）。api_* 三份为 Comfy 云模板（需登录，本地不用）。

## 6. 提示词工作链（AI 创意桥）

```
一句话创意
   │  bats\prompts\ai_prompts.bat / idea2prompts.py --idea "..."
   ▼
Qwen（SGLang 8000，OpenAI 兼容，api_key 空=本地端点）
   └─ 职责护栏：只做“创意 → 各槽位 {positive,negative} JSON”，不执行/不规划任何
      命令/文件/服务操作（system 消息硬编码 + 调用层不给 shell）
        ▼
prompts/workflows/<slot>.positive/.negative.txt（default 槽=positive_prompts.txt）
        ▼
跑工作流时引擎自动取词（CLI > 槽位 > 阶段默认 > default）并覆盖模板内嵌 prompt
```

- `config/llm.json`：enabled=true、base_url=http://127.0.0.1:8000/v1、
  max_tokens=4096（防截断；截断/非 JSON 会报错而不落盘，见 idea2prompts 加固）。
- 模型输出质量/截断问题排查：先看 `logs/run_<ts>.log` 的
  `idea2prompts slot_written …` 事件。

## 7. 一次完整任务在日志/审计里长什么样

`logs/run_<时间戳>_<毫秒>.log`（PS 编排时与 py: 事件交错；CLI 直跑自举同名日志）：
```
[ts] py: === idea2prompts run start ===        （AI 桥示例）
[ts] py: idea2prompts event=task idea_len=… slots=… dry_run=False
[ts] py: idea2prompts event=slot_written slot=video_t2v positive_chars=… negative_chars=…
[ts] py: === h3_submit run start ===           （提交链示例）
[ts] py: task mode=stage stage=t2v source=内置生成器 resolution=… duration=… seed=…
[ts] py: workflow_saved dir=h3_20260903_… nodes=14
[ts] py: submitted stage=t2v prompt_id=…
[ts] py: submitted_only prompt_id=… (task running in background)   ← --submit-only
[ts] py: completed … remote=…/MiniMax_H3_0002x_.mp4 elapsed=…s status=success
[ts] py: local_output file=video_4.mp4 bytes=…                       ← spark-local 直存
[ts] py: root_state_cleared prompt_id=… (no outer downloader)
```
审计目录 `workflows/h3_<时间戳>_<毫秒>/`：workflow_api.json / workflow_ui.json /
job.json（含 prompt_id、state、remote_path、output_file、log_file 双向索引）。
Agent 工具调用另有 `agent-tools` 事件（`modify_workflow call/ok …`）。

## 8. 常见异常与处置（来自实测教训）

| 现象 | 原因 | 正确动作 |
|---|---|---|
| 工具报“提交超时/执行超时”但任务其实在跑 | 旧版单次调用阻塞超时 | 已修复为提交即返回；升级后按 §4 续传查询 |
| 无参重跑返回**旧产物**（编号/时间不新） | 断点残留把新请求劫持成旧任务续传 | 已修复（成功即清断点）；确认产物编号递增、日志含本次 prompt |
| dry_run 被“断点拦截”挡住 | 有未完成任务/残留断点 | 在跑任务→续传；旧残留→加 --force-new 或确认后删 last_job.json |
| 提示 negative 为空 / 槽位写入中文杂讯 | max_tokens 截断或模型未按 JSON | 调大 llm.json max_tokens（≥4096）重试；修复版会报错不落盘 |
| 素材列表为空 / 上传文件找不到 | Open WebUI 尚未产生 uploads；看门狗未起 | 先上传一次文件；`tmux ls` 查 upload-watch；`python3 runs/h3/upload_watch.py status` |
| spark 上出现“Could not resolve hostname spark” | 工具按 win-remote 分支误发 ssh | 检查 config/deploy.json site=spark-local（同步已排除机器配置，不会被打回） |
| 产物不在 Windows outputs | spark-local 模式产物在 spark | spark: outputs/ 自取或 scp 拉回；win-remote 才会自动下载 |
| 对话输出到一定长度被截断，看不出是否还在生成 | 单轮输出超长/后台长任务期间界面无反馈 | 新界面已解决：状态栏持续心跳显示“任务进行中…”，超长回复自动暂停并提示发送“继续”续写 |

## 8b. Agent 界面（7860）说明（2026-09 起自研轻量界面）
- **历史会话**：下拉列出 `logs/agent_chats/*.jsonl`（按时间倒序，标题=首句），可加载续聊/删除/刷新；
- **自动新会话**：页面打开即自动开启新对话（显示会话 id），“＋新对话”随时再开（旧会话自动存档，互不干扰）；
- **素材直传**：界面自带“📤 上传素材”按钮（图片/视频，可多选）——自动归档 uploads/ 并（图片）镜像到 ComfyUI input/user_uploads/，随后让 agent `list_references` 即可选用（与 Open WebUI 上传等价）；
- **进行中指示**：模型/工具在后台线程执行，界面独立心跳每 3s 刷新状态栏（“⏳ 任务进行中… 请勿重复提交”）——长视频任务不再“看着像卡死”；
- **自动暂停续写**：单轮回复设 max_tokens 上限 + 系统提示约束精炼输出；超长被截断时自动追加“发送：继续 续写”提示；
- **上下文预算（token 口径，2026-09-04 起）**：模型 ctx=8192，但每轮存在固定开销
  （系统提示+工具定义模板，实测 ≈3.1k token）且回复预留 2048 ⇒ 对话消息预算
  ≈2.5k token。实现在 `runs/agent/ctx_budget.py`：每轮调用前按
  UI_TRIM_TOKENS=1800（精确 token 计数，缺 tokenizer 时保守启发式）裁剪历史
  （保最新轮次+尽量保留首轮意图），裁剪时对模型附加说明；同时向 qwen_agent 显式传
  max_input_tokens（回合内工具往返也受同一硬预算），若服务端仍报“超上下文”400
  则自动压缩到最新消息重试一次——长会话不再失控、不再报 400；
- 会话内容存于 `logs/agent_chats/`（随 logs/ 一起 gitignore，仅本机）。

## 9. 服务与维护速查（spark 人工执行）

```bash
# 服务总览/启停（ComfyUI/SGLang/Qwen-Agent/Open WebUI）
bash ~/videoGenerate-Model-zju/shell/manage_services.sh {status|start|stop|logs}
# 常驻附加会话
tmux ls                                   # 应含 comfyui sglang qwen-agent webui upload-watch
# 上传收件箱看门狗（如需重启）
tmux kill-session -t upload-watch
tmux new-session -d -s upload-watch \
  'cd ~/videoGenerate-Model-zju && python3 runs/h3/upload_watch.py watch --interval 30 2>&1 | tee ~/upload-watch.log'
# 两文件夹自动合并（Windows 本机执行；可手动开关）
python runs/sync_auto.py {enable|disable|status|once}      # 或 bats\workflow\autosync.bat
# 端口：8000 LLM | 8188 ComfyUI | 7860 Agent | 3000 Open WebUI
```

## 10. 一条用户旅程（完整示范）

1. 用户在 Open WebUI 传一张角色图（对话说“参考这张图”）。
2. upload-watch 收进 uploads/ 并镜像到 ComfyUI input/user_uploads/。
3. 用户到 7860：“用我刚上传的图做参考，生成 6 秒 r2v 视频，720p”。
4. agent：`list_references`（确认素材）→ `run_script h3/refimage.py use --name <id> --stage r2v`
   （把模板 LoadImage 指向该图）→ `call_comfyui(stage="r2v", resolution="720p", seconds=6, prompt=英文描述)`。
5. 工具秒回 `TASK_SUBMITTED: …`；agent 转告用户任务已后台运行。
6. 数分钟后用户问“好了吗”→ agent `run_script h3_submit.py`（无参）续传轮询至完成，
   汇报 `REMOTE_VIDEO_PATH` 与 `LOCAL_OUTPUT: outputs/video_N.mp4`。
7. 用户到 spark outputs/（或让 agent/人工 scp）取片；agent 全程不重复提交、不越权。
