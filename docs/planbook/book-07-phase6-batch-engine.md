# 阶段 6 — 批量提交与引擎契约（修 h3_batch 导入/超时，统一参数契约，参考视频）

> 状态：计划(未实施) | 目标：修掉 `h3_batch.py`/`batch_submit` 的导入与超时/卡死 bug，统一「提示词/参考图/参考视频位置」参数契约，可选支持参考视频 |
> 主负责人：引擎/后端 | 依赖：book-05(会话)、book-06(逐段提示词) | 对后端影响：高 | 优先级：🟠 中

---

## 1. 问题背景（用户可见现象 + 模型输出片段）
- 模型执行时 `batch_submit` 报：`from runs.h3 import mediacheck` → `ModuleNotFoundError: No module named runs`；`h3_batch.py` 同错。
- `h3_batch.py status` **一直超时**。
- 模型困惑「提示词、参考图位置、参考视频位置如何指定」；且「对模型的提示不够明朗」。

---

## 2. 根因分析（实测）

### 2.1 h3_batch 导入错误 ModuleNotFoundError（已定位）
- `h3_batch.py:90` 用 `from runs.h3 import mediacheck`。脚本以 `python runs/h3_batch.py`（或从 `runs/` 下）运行时，`sys.path[0]` = `runs/`，于是 `import runs` 去找 `runs/runs/__init__.py`（不存在）→ `No module named runs`。
- 正确做法（与同目录 `h3_submit.py:39-41` 一致）：改用 `from h3 import mediacheck`；或在模块顶部一次性把 `PROJECT_ROOT` 加入 `sys.path`。
- **同样的隐疾**：`refimage.py:522`、`upload_watch.py:104` 也用 `from runs.h3 import mediacheck`，在非项目根运行会同样失败。
- `h3_batch.py:19 import fcntl` 是 **Unix-only**：在本 Windows 机上该脚本在更早处就报 `No module named fcntl`（实测），在 spark 上 `fcntl` 可解析但随后 `runs` 导入仍是第一个失败。

### 2.2 h3_batch status 超时/卡死（已定位）
- **工具超时错配（主要）**：agent 用 `run_script` 驱动，`tools.py` 把每个脚本钳在 `_SCRIPT_TIMEOUT=120s`，而 `h3_batch status --wait` 默认 `--timeout 600`（`h3_batch.py:206,353`）。于是 `run_script("h3_batch.py","status --wait")` 在 120s 就被杀，agent 看到「调用等待超时」。`BatchSubmit` 用 300s（`tools.py:469`）、`call_comfyui` 用 180/600（`tools.py:316`）——三处不对齐。
- **每次轮询成本高**：`status` 对每个未完成段都新起一个 `h3_submit.py --resume <pid>`（内层 30s 超时，`h3_batch.py:219-220`）串行，再 sleep 15s（`:247`）。N 段一轮最坏 `N*30s+15s`，多段时很快撞 600s 外层超时 → 打印「等待超过 600s」退出，表现为假「超时/卡死」。
- **卡在空 prompt_id**：段不在 (completed,failed) 且无 prompt_id（`:214-215`）会永久把 `all_done` 置 False，`--wait` 每 15s 空转到 600s。
- **边界 bug（可能提前判成功）**：`except Exception`（`:238-239`）只设 `seg[error]`，没把 state 归一、也没把 `all_done` 置 False——非超时异常时段仍非终态但 `all_done` 可能仍 True → 提前报完成。
- `status` 无锁；`_find_batch_dir` 默认取最近 `workflows/batch_*`（`:335-336`），本地无 batch 目录会报「找不到批次目录」。

### 2.3 批量任务未按会话跟踪 / poll_batch 是桩
- `send` 只从 `extract_prompt_ids`（匹配 `prompt_id:`/`TASK_SUBMITTED:`）收集任务，**不解析 `BATCH_MANIFEST:`**；`task_watch.poll_batch` 是占位实现（`task_watch.py:74-80`），始终返回「批量任务处理中」。

---

## 3. 目标与范围

**目标**：`batch_submit`/`h3_batch` 在 spark 稳定可用（导入 OK、status 不再假超时、可断点续跑），参数契约清晰，参考视频边界明确。

**做**：
- 修 `h3_batch.py`/`refimage.py`/`upload_watch.py` 的导入（`from h3 import ...` 或模块顶部加 project root 到 sys.path）。
- 修 `fcntl`：仅在 `os.name == posix` 上使用；Windows 下给出非致命降级（或明确「仅 spark 运行」）。
- 对齐工具超时：`run_script`/`BatchSubmit`/`call_comfyui` 的超时与 `h3_batch` 的 `--wait`/`--timeout` 设计一致；`status` 轮询改为**一次性读 ComfyUI /history + /queue**（或每段一次但上限），避免 N 段串行 30s 轮询。
- 加全局上限与超时：给 `status --wait` 设总时长与「连续无进展即停」；空 prompt_id 段不空转。
- 修 `all_done` 边界 bug；用锁/原子写避免竞争。
- 统一参数契约：`call_comfyui`/`modify_workflow` 的 `stage/prompt/resolution/seconds/seed` 与参考图/参考视频语义讲清；在工具描述 + `agent-reading/01` + SYSTEM_MESSAGE 写清。
- 会话级批量跟踪：`send` 解析 `BATCH_MANIFEST:` 为 `type:batch` 任务；实现 `poll_batch`（读 manifest 状态、取片）。
- 参考视频边界：当前明确「不支持」（给出替代建议）；若需支持再新增 LoadVideo 链路。

**不做**：不改 ComfyUI 服务/模板；不引入 api_* 云模板；不越白名单做 shell/文件/服务管理。

---

## 4. 改动点清单（拟议）

| 文件 | 拟改内容 | 目的 |
|---|---|---|
| `runs/h3_batch.py` | ①`from runs.h3 import mediacheck` → `from h3 import mediacheck` 或模块顶部加 `sys.path.insert(0, str(PROJECT_ROOT))`；②`import fcntl` 做 Linux 保护并对 Windows 降级；③`status --wait` 轮询改一次读状态+上限；④修 `all_done` 边界；⑤段记录加 `prompt/negative_prompt` | 修导入/超时，逐段提示词 |
| `runs/h3/refimage.py` | `:522` 同样修导入；`use` 对非图片/参考视频给出可读错误 | 修隐疾 |
| `runs/h3/upload_watch.py` | `:104` 同样修导入；`_record` 加 batch/会话字段 | 修隐疾 |
| `runs/agent/tools.py` | 对齐 `run_script`/`BatchSubmit`/`call_comfyui` 超时；`call_comfyui`/`modify_workflow` 描述写清参数契约与参考视频边界 | 消除契约困惑 |
| `runs/agent/task_watch.py` | 实现 `poll_batch`（读 manifest 状态、提取产物）；`status` 显示段进度 | 会话级批量跟踪 |
| `runs/agent/ui_app.py` | `extract_prompt_ids` 增加 `BATCH_MANIFEST:` 解析 → `type:batch` 任务 | 批量入会话任务表 |
| `runs/agent/scheduler.py` | SYSTEM_MESSAGE 把多图转场流程改为「逐段提示词生成→batch/逐段提交→取片」，并说明参数契约 | 模型侧明确 |
| `docs/agent-reading/01-tools-reference.md`/`04-agent-workflow.md` | 写明「提示词用 --prompt/注入；参考图用 refimage use --slot N；参考视频当前不支持」；多图流程改为逐段提示词 | 口径一致 |

---

## 5. 实施步骤

### 步骤 1：修导入（先，因为它是「跑不起来」的第一因）
- 把 `h3_batch.py`/`refimage.py`/`upload_watch.py` 的三处 `from runs.h3 import mediacheck` 改为 `from h3 import mediacheck`（与 `h3_submit.py` 一致）；或统一在 `run_script`/`batch_submit` 调用前确保 `cwd=PROJECT_ROOT` 且 `PYTHONPATH` 含项目根。
- 验证：`python runs/h3_batch.py submit --stage flf2v --images a.png,b.png --dry-run`（在 spark 上）不再 ModuleNotFoundError。

### 步骤 2：修 fcntl / 跨平台
- `fcntl` 只在 `os.name == posix` 时用；Windows 走 `msvcrt` 或简化为「无锁」（明确记录）——保证脚本在本机测试也不崩。

### 步骤 3：修 status 超时/卡死
- 工具超时对齐：让 `run_script`/`BatchSubmit` 的超时 ≥ `h3_batch --wait` 的期望，或把 `h3_batch --wait` 默认降到与工具超时匹配，并在返回信息里写明「仍在生成，可再次查询」。
- 轮询成本：`status` 改为对每个段**一次性**查询 ComfyUI 状态（不每段新起 h3_submit --resume），或每段只查 `/history`/`/queue`；避免 N*30s 串行。
- 空 prompt_id / 无进展：加「连续 N 次无进展即停 + 全局上限」，不再 15s 空转到 600s。
- 修 `all_done` 边界：非超时异常也要把 `all_done=False` 且归一 state。

### 步骤 4：逐段提示词（与 book-06 联动）
- manifest 每段加 `prompt/negative_prompt`；提交段时按段注入，不再全局共享。

### 步骤 5：会话级批量跟踪
- `send`/`extract_prompt_ids` 解析 `BATCH_MANIFEST:`；`poll_batch` 读 manifest 状态并取片；状态条显示「已完成 X/N 段」。

### 步骤 6：参数契约与参考视频边界
- 工具描述 + 文档 + SYSTEM_MESSAGE 明确：提示词=--prompt/注入；参考图=refimage use --slot N；参考视频=当前不支持（替代：首帧图）。

---

## 6. 验收标准（spark 真实环境）

- [ ] `h3_batch.py submit --dry-run` 与 `status` 在 spark 不再 `ModuleNotFoundError`（导入固定）。
- [ ] `status` 有明确总超时与「连续无进展即停」，不再假「一直超时」；长时间任务可多次查询并如实返回。
- [ ] `batch_submit`/`call_comfyui`/`run_script` 三处工具超时语义一致、可预期。
- [ ] 批量任务入会话任务表；`poll_batch` 返回真实段状态与产物路径；状态条显示「已完成 X/N」。
- [ ] 多图任务各段提示词不同（配合 book-06）；不因共享 prompt 导致「五个一样」。
- [ ] 工具描述/文档讲清参数契约；模型不再困惑「如何指定提示词/参考图/参考视频位置」。
- [ ] 整条「上传→选素材→逐段提示词→提交→取片→拼接」端到端跑通（配合 book-09）。

---

## 7. 风险与回滚
- **风险：逐段注入后各段画面不可控**——先在 dry-run/单段真跑验证，再接批量。
- **风险：超时对齐改坏「提交即返回」语义**——保持 `call_comfyui` 默认 submit-only 不变；只调整 `status` 的轮询骨架。
- **风险：批量会话跟踪引入重复/串session**——`turn_state`/`session_state` 按 cid 隔离，锁粒度按会话。
- **回滚**：导入/超时/逐段为增量修改，可独立回退；`poll_batch` 从桩到实现可开关。

---

## 8. 与其它册/红线的关系
- 与 book-06（逐段提示词与注入）强耦合；与 book-05（会话素材）联动。
- 红线：不动 ComfyUI 服务/模板；不引入 api_*；不越白名单。

---

## 9. 待用户输入 / 待定项
- ✅ 参考视频：用户定级为**甜点/低优先**，列入待做清单（`docs/planbook/` 附录「待做-低优先」）；当前维持「不支持 + 替代建议」即可，不阻塞主线。
- 批量任务的断点续跑与「取消」交互（配合 handoff 提到的任务取消）。
- 时间上限与进度显示粒度的偏好。