# 阶段 9 — 日志系统治理与升级（全场景、稳定、无垃圾、不错失 agent 行为与参数）

> 状态：实施中（步骤1 完成；步骤2 核心完成；步骤3 部分；步骤5 核心完成） | 目标：让日志体系在 spark/Windows 全操作场景下稳定工作——无垃圾/无效日志，完整记录 agent 行为操作与本地输送的 key 参数（分辨率/时长/seed/提示词/参考图/批量段等），并可跨会话、跨端、跨组件互相回溯 |
> 主负责人：运维/后端 | 依赖：book-01(基座/版本指纹)、book-07(引擎契约) | 对后端影响：中 | 优先级：🟠 中

---

## 1. 问题背景（用户反馈）
- 「把整个项目系统的日志系统更新也写入计划书，包括但不限于优化各种操作场景下的日志工作能力（spark 上、windows 上等）。」
- 「保证日志系统的工作稳定性，不会出现垃圾日志和无效日志。」
- 「错失记录 agent 的行为操作和本地输送分辨率等参数。」

---

## 2. 现状与根因（实测核查）

### 2.1 多套日志实现，格式同构但分裂、易漂移
- ①`runs/h3/logutil.py`：统一事件日志（`[ts] py: <tool> <event k=v>`），经 `H3_LOG_FILE` 注入或自举 `logs/run_<ts>_<ms>.log`；供 refimage / idea2prompts / h3_text2img* / agent 工具共用。
- ②`runs/h3_submit.py`：自建**同构实现**（`_log_event`/`_ensure_run_log`，`_LOG_ENV=H3_LOG_FILE`）——格式一样但代码是第二份（维护双份=漂移风险；其 `local_output`/`submitted` 等行不与 logutil 走同一函数）。
- ③`runs/agent/llm_mem.py:41`、`runs/sync_auto.py:53`：各自 `_log` 只 `print` 到 stdout（进 `~/agent.log` 火海，无结构化、无落盘、无事件字段）。
- ④`runs/agent/ui_app.py`：状态条 `tail_run_log`、会话存档 `logs/agent_chats/<cid>.jsonl`、上传 `uploads/log.jsonl`——与 run log 无自动关联。
- ⑤`runs/agent/task_watch.py`：**无任何日志调用**（Grep 证实）——ComfyUI 轮询的进度/状态/完成只出现在界面气泡，**不持久化**，重启即丢。

### 2.2 垃圾/无效日志的来源
- **stdout 火海**：`~/agent.log`（= tmux `tee` 的 scheduler 全部 stdout/stderr）混入 Gradio 启动横幅、心跳 print、`[llm_mem]` 行、版本行、Traceback——无类别、无轮转、会无限增长。
- **文档/实现漂移**：文档写 `~/qwen-agent.log`，实际进程 tee 到 `~/agent.log`（已导致取证错向）。
- **空/多份 run log**：每次直跑 CLI（未注入 `H3_LOG_FILE`）都会自举一个新 `run_*.log`；同秒多进程靠毫秒撞名；偶发空文件（只有 `=== run start ===` 一行）。
- **超长/截断行**：工具返回/JSON 刷屏已有 `H3_CONCISE` 与 5000 字符截断，但截断标记本身、重复 start 行、raw JSON 残段仍会污染日志。
- **时区不一致**：本地日志=北京，spark `ls/journalctl`=UTC（差 8h），日志行本身不带 TZ 标注，易认错。

### 2.3 错失记录（agent 行为 + 本地输送参数）
- **工具调用**：`tools.py._log_tool` 记录工具名+事件+参数（截 300 字符）+结果——**但**：参数被截断（`resolution`/`seconds`/`images`/`prompt` 可能在截断后不可见）；未记**调用时刻/时长**；未区分「agent 决策（为何选它）」与「执行结果」。
- **本地输送参数**：`h3_submit` 的 `task` 行**有** resolution/duration/seed/steps/prompt_len（实测 561-566 行），但 `submitted` 行只有 `stage/prompt_id`（629 行）——从「提交行」无法单独看到参数，需回看 task 行；`h3_batch` 各段 在 manifest 里有 images/prompt_id；**agent 侧** call_comfyui 传的 `stage/resolution/seconds/seed/prompt/参考图` 未经结构化落审计（仅截断参数 log）。
- **决策/自然语言**：每轮 assistant 的完整输出只在 `logs/agent_chats/<cid>.jsonl`；工具推理过程、finish_reason（截断/自然停）、自动续跑次数、预算裁掉哪些轮——**无记录**（book-04 相关）。
- **资源/素材**：`refimage use/promote/undo`、上传 `batch_id/cid`、熔断计数——部分有、部分只到界面；与「哪次任务用了哪张图」无索引。

### 2.4 跨端场景间隙
- win-remote：提交在 spark、下载到 Windows；现在 logs 分处两端，**无「任务 id 跨端串联」**（本地 run log 有 prompt_id，但 Windows 下载日志与 spark 提交日志不在同一文件）。
- spark-local：全部在 spark——但 run log 与 `~/agent.log` 分开，且 `~/agent.log` 无轮转。
- Windows 编排层（`shell/lib` `Initialize-RunLog`）与 Python `logutil` 的 `H3_LOG_FILE` 约定已合作，但**无一致性校验**（命名/格式/TZ 约定散落各文档）。

---

## 3. 目标与范围

**目标**：一套 Writer（logutil 唯一化）、一套事件模型（全覆盖）、一份「任务=一份日志」、一套防垃圾机制（轮转/上限/去重/类别），并在**两端场景**可跨组件回溯 agent 行为与参数。

**做**：
- **统一**：logutil 成为唯一实现；`h3_submit.py`/`h3_batch.py` 改走 logutil（或提供「格式一致性测试」）；`llm_mem`/`sync_auto`/`task_watch`/`ui_app` 的关键事件全部走 logutil。
- **事件模型**：用户层（会话/上传/继续/中止/取片）→ 决策层（轮次开始/选择的 stage/工具调用**含全参数与时刻**/结果/熔断/预算裁剪/续跑）→ 引擎层（start/task/submitted/completed…，补 `submitted` 行的 resolution 等）→ 素材层（list/promote/use/批次）→ 资源层（wake/nap/轮询进度/段完成）→ 环境层（启动/版本指纹/致命错误）。
- **防垃圾**：日志类别分「事件(结构化)/诊断(DEBUG)`」；`~/agent.log` 只留关键行（scheduler 层摘要），详实行落 run log；run log 单文件上限（如 5MB）自动换文件；`logs/` 保留 N 天自动清理；空文件/重复 start 行清理；超长行截断+标记；时区统一（文件头标注 TZ，事件行带 TZ）。
- **不错失**：`_log_tool` 改为结构化字段（工具名/参数 JSON/关键值 stage-resolution-seconds-seed-images-prompt_len/开始时刻/耗时/退出码/结果摘要/prompt_id）并存审计文件（`logs/agent_tool_audit.jsonl`，不同于 run log 的人读格式）；每轮 assistant 输出摘要+finish_reason+续跑次数入 run log；会话↔任务↔日志↔产物 互链索引（cid、turn、run_log 路径、job.json、prompt_id、LOCAL_OUTPUT）。
- **跨端**：任务 id（prompt_id/batch dir）作为贯穿键；win-remote 下载后把 spark 提交日志段回写到本地 run log；两端日志目录约定写入文档并校验。
- **可观测**：`dev.py` 增加 `logs` 子命令（查/关联/清理/校验），并给 `tail_run_log` 加「当前任务日志」精准定位。

**不做**：不改变生成语义；不改 ComfyUI 服务配置；不把工具返回全文写日志；不引入外部日志系统（先 logutil 单点）。

---

## 4. 改动点清单（拟议）

| 文件 | 拟改内容 | 目的 |
|---|---|---|
| `runs/h3/logutil.py` | 增强：类别(diagnostic/info)、TZ 标注、单文件上限+换文件、`log_call(tool, params, result)` 结构化审计辅助、`fmt` 保持 | 唯一 Writer |
| `runs/h3_submit.py` | `_log_event`/`_ensure_run_log` 改为调 logutil（删除同构实现）；`submitted`/`completed` 行补 `resolution/seconds/seed/prompt_len/images`；提交/下载跨端补关联字段 | 收敛+补参 |
| `runs/h3_batch.py` | 每段提交/状态/重试事件走 logutil；事件含 `batch_dir/seg_idx/stage/resolution/seconds/prompt_len/images` | 批量段留痕 |
| `runs/agent/tools.py` | `_log_tool` 升级：结构化的 `logs/agent_tool_audit.jsonl`（时间/工具/参数JSON/关键值/耗时/结果/prompt_id）；run log 保留摘要行 | 不错失 agent 行为 |
| `runs/agent/ui_app.py` | `save_chat`/心跳/上传/中止/续跑事件写 run log 摘要；会话存档与 run log 互链（存 run_log 路径到 jsonl 头）；`tail_run_log` 精准定位当前任务日志 | 会话↔任务关联 |
| `runs/agent/task_watch.py` | 轮询进度/状态/段完成/失败 全部 logutil 持久化 | 进度不错失 |
| `runs/agent/llm_mem.py` | `_log` 改走 logutil（wake/nap/超时/结果）；保留一行 stdout 供 agent.log） | 资源事件入库 |
| `runs/sync_auto.py` | 同 `_log` 收敛 | 同步留痕 |
| `shell/lib/*.ps1` | `Initialize-RunLog` 与 logutil 约定一致化（命名/格式/TZ）；win-remote 下载后回写 spark 提交日志段 | 跨端串联 |
| `runs/dev.py` | 新增 `logs` 子命令：查看/关联(按 prompt_id/cid)/清理(保留N天)/校验(垃圾行统计、事件覆盖检查) | 可观测+自检 |
| 文档 | `docs/reference-2026-09-04.md`/`docs/robustness-and-modularity.md`/`START-HERE.md`：日志体系章节统一（文件位置、格式、TZ、轮转） | 口径一致 |

---

## 5. 实施步骤

### 步骤 1：统一 Writer 与格式
- logutil 增加「类别+TZ+上限换文件+审计辅助」；`h3_submit.py` 切换到 logutil（保留 `_log_event` 薄壳以兼容现测试）；跑 `pytest runs/h3/tests`（有 logutil/h3_submit 日志测试）。

### 步骤 2：事件模型填空（先补「错失」项）
- `tools.py` 审计 jsonl + key 字段；`submitted`/`completed` 补参；`h3_batch` 段事件；`task_watch` 持久化；`llm_mem`/`sync_auto`/`ui_app` 关键事件入库。

### 步骤 3：防垃圾与稳定性
- run log 上限换文件；`~/agent.log` 只留关键行（scheduler 摘要，其余进 run log）+ 轮转（按天/大小，`logrotate` 或 in-app）；`logs/` 保留 N 天；空文件/重复 start 清理；时区统一。

### 步骤 4：跨端串联
- `win-remote`：任务 id（prompt_id/batch）为键；下载后把 spark 提交/进度段回写本地；`Initialize-RunLog` 与 logutil 约定一致化；文档统一。

### 步骤 5：可观测 + 自检
- `dev.py logs`（view/link/clean/check）；`tail_run_log` 精准定位；`dev.py logs check` 输出「垃圾行数/事件覆盖矩阵」。

### 步骤 6：端到端验证（配合 book-09 黄金路径）
- 跑一次完整任务（上传→选素材→逐段提示词→提交→取片），断言 run log 覆盖矩阵非空、参数齐全、无垃圾行、`dev.py logs check` 通过。

---

## 6. 验收标准

- [ ] `logutil` 为唯一实现：`h3_submit.py`/`h3_batch.py` 不再有第二套 logger（或一致性测试通过）；`task_watch.py`/`llm_mem.py`/`sync_auto.py` 关键事件均入库。
- [ ] 一次完整任务的 run log 可还原：用户意图（cid/turn）→ agent 工具调用（时刻/全参数：stage/resolution/seconds/seed/prompt_len/参考图）→ 结果（耗时/退出码/prompt_id）→ 提交（含 resolution/seconds/seed）→ 进度/段完成 → 产物（LOCAL_OUTPUT/文件名）。
- [ ] **关键参数不错失**：对同一任务，`submitted` 行与 task 行参数一致且完整；`call_comfyui` 传输的参数与引擎 task 行一致（本地输送分辨率等）。
- [ ] 无垃圾：dev.py logs check 输出垃圾行数=0（或仅白名单）；`~/agent.log` 有轮转；`logs/` 保留策略生效；无空 run log。
- [ ] 稳定性：日志写入 try/except 不反抛（模拟磁盘只读/write 异常不崩主流程）；长时间运行内存/文件句柄不回涨（压测 1h+）。
- [ ] 跨端串联：win-remote 一次任务，Windows 本地日志含 spark 提交/进度段（通过任务 id 关联）。
- [ ] 时区/TZ 标注一致，事件行可区分北京/UTC。

---

## 7. 风险与回滚
- **风险：日志写入开销拖慢主流程**——写失败静默（不反抛）、缓冲或低频；提供开关（`H3_LOG_LEVEL`）。
- **风险：日志文件增长失控**——上限/保留策略为默认值，可按 `logs/` 大小告警；回滚=关闭轮转即可。
- **风险：审计 jsonl 含参数敏感/超长**——限长+关键值成结构；敏感字段可配置脱敏。
- **回滚**：logutil 增强为增量；`h3_submit` 的薄壳保证兼容；`dev.py logs` 独立可移除。

---

## 8. 与其它册/红线的关系
- 与 book-01（版本指纹/基线）、book-04（finish_reason/续跑）、book-07（引擎契约/h3_batch）、book-09（黄金路径证据）联动；输出常驻日志可成 book-09 的证据源。
- 红线：不改 ComfyUI 服务/模板；不把工具全文/敏感内容写成垃圾；不越白名单。

---

## 9. 待用户输入 / 待定项
- `~/agent.log` 轮转方式（系统 logrotate vs 应用内轮转）与保留天数（建议 7~14 天）。
- 是否需要「诊断级」日志（DEBUG）开关与默认级别（建议默认 info，诊断可选）。
- 日志是否加入版本指纹行（建议加：每个 run log 头部写入 `AGENT_VERSION`+root+形态）。
- 审计 jsonl 的保留策略与是否需要脱敏。

---

## 10. 实施记录（截至 2026-09-04）

### 已完成
- **步骤1 收敛**：`logutil` 增强（5MB 上限+`.1` 轮转、`# TZ=UTC+8` 文件头、`bare` 模式、`fmt`）；`h3_submit` 的 `_ensure_run_log`/`_log_event` 改为委托 logutil（保留同名薄壳，101 单测兼容）。
- **步骤2 关键参数不错失**：`tools.py` 新增 `_log_tool_audit` → `logs/agent_tool_audit.jsonl`（ts/tool/关键参数 stage-resolution-seconds-images-session-script_name/result_len/ok/prompt_id）；`h3_submit` submitted/submitted_only 行补 `resolution/seconds/seed/steps/prompt_len/imgs`（复用 `_gp_summary`）。
- **步骤5 可观测**：`dev.py logs view/check/clean`（view 含 `--remote` 跨端查看 spark `~/agent.log` 与 logs/；check 只检 book-11 格式/TZ 头，自动跳过旧格式；clean 清 `.1` 轮转，默认 dry-run）。
- **测试**：`runs/h3/tests` 101 用例全绿（含修复两处过时用例：refimage 单字节测试数据不满足 book-08 的 ≥1KB 有效图过滤；r2v 模板用例接受 book-10 默认资产守卫新文案）。

### 未完成（下一批）
- task_watch 轮询进度/段完成持久化；ui_app 会话↔run log 互链与 `tail_run_log` 精准定位；llm_mem/sync_auto 关键事件入库（两者现无自建 logger，仅需补事件）。
- 跨端回写：win-remote 下载后把 spark 提交段回写本地 run log（当前提供 `dev.py logs view --remote` 轻量联通观察）。
- `~/agent.log` 轮转落地方案（见 dev-workflow 文档指引；建议保留 7~14 天，重启 agent 时 `: > ~/agent.log` 或按需 truncate）。
- 步骤6 端到端验收（配合 book-09 黄金路径）。