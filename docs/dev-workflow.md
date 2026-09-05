# 变更与交付工作流（执行→修改→测试→自测通过→写入文档→双端核对→git 提交）

> 版本：v1.0 · 日期：2026-09-04 · 性质：**本仓库一切改动必须遵守的固定流程**（代码、文档、skill、配置更改均适用）。
> 目标：让每一次改动都**可执行、可自测、可留痕、双端一致**；杜绝「文档说了完成、实际没生效」「大模型说正常、并不算通过」两类失信。
> 速查：`skills/dev-workflow.md`（精简卡）。读者：本仓库任何新参与模型/Agent/维护者。
> 自动化：本流程已固化为 **`runs/dev.py`**（check / sync / commit / docs / test 五子命令）——能用脚本的地方优先一次调用，节省 agent token 并提速（用法见 §3/§6/§7 与 `python runs/dev.py --help`）。

---

## 0. 流程图（文字版）

```
执行任务 → 修改 → 测试 → 自我测试通过 → 写入文档 → spark/本机双向核对并更新 → git 提交
    ↑        │       │         │             │              │               │
    │        │       │         │             │              │               └─ Windows commit→push GitHub→spark commit
    └─(每步不通过则回到上一步/记录待办)──────────────────┴──────────────────┘
```

---

## 1. 步骤一：执行任务（理解与取证）

**做什么**：先读相关文档/skills、核实事实，再动手。

- 读 `START-HERE.md §2` 找到对应文档/skill；新参与一律先读总入口与 `docs/session-summary.md`（事实源）。
- 核对双端/多副本现状：
  - Windows 主库：`git -C D:/MY_CODING_PROGRAM/videoGenerate-Model-zju log --oneline -5`
  - spark 运行时：`ssh spark "git -C /home/Developer/videoGenerate-Model-zju log --oneline -5"`；再看 `git status --short` 是否有未提交改动。
  - GitHub：push 后 `git rev-parse HEAD` 与远端一致。
- **先判断「问题根因」四选一**：①代码没写 ②写了没同步 ③同步了进程没重启 ④文档先行、代码滞后的「演练稿」。
- 涉及运行实例：先确认它跑的到底是哪个版本（见 planbook book-01 版本指纹）。

**判定**：能说清「改哪端、问题属①②③④中哪类」。

---

## 2. 步骤二：修改

**做什么**：做**最小、低耦合**的改动；遵守红线；一次尽量只改一个关注点。

- 低耦合：前端/文案改动不碰后端；资源隔离不依赖模型风格调整；改动之间靠稳定契约衔接。
- 红线（不可触碰，`START-HERE.md §3.4` / planbook book-00 §P6）：
  - ComfyUI = systemd 服务，勿重启/勿改 systemd；临时腾内存只用 `POST /free`（sudo 需人工）。
  - spark 平台同事模板 `~/ai/ComfyUI/user/default/workflows/` **永不修改**；只改本地镜像 `workflows/remote_workflows/` 与 `config/templates/`。
  - `api_*`（Comfy 云）模板不提及、不调用；本地语义用 `video_*`。
  - 禁写 `Z:/...` 路径；一律 spark 真实 `~/...` 或 Windows 主库路径。
  - Agent 只做白名单内动作（无 shell/任意文件/服务管理）；越权请求拒绝并转人工。
- 改文件用 `edit`/`write`；改前先 `read`；涉及常量/路径/端口/工具数改一处须四处核对（`START-HERE.md §5`）。

**判定**：改动可回滚（git 可还原 / 有开关）；未越红线；改动范围明确。

---

## 3. 步骤三：测试

**做什么**：跑能跑的最小验证，先静态后功能。

- 静态一致性：`python runs/consistency_check.py`——检查 manifests/pipeline/capabilities/模板引用图/提示词多段拼接/残留与 git 状态。
- 单元/已有测试：`python -m pytest runs/h3/tests -q`（若相关）。
- 本项目自测/烟测：**基座门禁** `python tests/e2e_smoke.py`（已建，spark 全量）与 `python runs/agent/runtime_check.py`（常量/工具/路径/指纹核对）；对**本阶段**的最小脚本：改前端就 grep 界面字符串、改 h3_batch 就跑 `h3_batch.py submit --dry-run`。
- 涉及 LLM/Agent：跑一轮真实对话或最小对话，断言输出/行为符合预期。
- 涉及工作流注入：`h3_submit.py --stage <x> --dry-run` 打印 API 图，断言 prompt/参考图已正确注入。

**判定**：相关测试/检查通过；无新增静态问题；关键路径有输出。

---

## 4. 步骤四：自我测试通过（防绕过门禁）

**做什么**：给出「真实执行证据」，且**本项目自己跑出**，不是大模型「读代码说正常」。

- 证据形式：命令 + 关键输出行（如 `SMOKE_OK`、`TASK_SUBMITTED: <id>`、`LOCAL_OUTPUT: ...`、`consistency_check` 无问题）；或真实界面截图/产物/日志。
- 判定标准（全满足）：
  1. 改的是 Windows 主库；spark 运行实例经「可重复部署路径」更新并**实际重启进程**后一致。
  2. 有真实执行证据（见上）。
  3. 双端一致（Windows commit → GitHub → spark 经部署一致）。
  4. 口径一致（影响的路径/端口/常量/工具数/文档，按 `START-HERE.md §5` 四处核对）。
  5. 未越红线。
- **未跑出证据 = 未完成**；大模型「我看了没问题」一律不计为通过（只可用于发现线索）。

---

## 5. 步骤五：写入文档 / skills

**做什么**：把改动与结论写回文档与 skills，并使索引一致。

- 状态类：`docs/session-summary.md`（事实源，追加批次/状态）、`docs/handoff-2026-09-04.md`（最新交接/测试清单回写）。
- 参考类：`docs/reference-2026-09-04.md`（契约/故障字典/工具速查）、`docs/robustness-and-modularity.md`、`docs/agent-workflow.md`。
- 计划类：`docs/planbook/`（本阶段计划、验收结果）。
- **索引同步（`START-HERE.md §5` 强制）**：新增/修改/删除任何 `docs/`、`skills/` 文件 → 更新 `START-HERE.md §2` 索引表（条目+角色标签）与 §6 版本记录；`README.md` 的「文档」表同步增删。
- 口径一致性：本文件 ↔ README ↔ handoff/reference/session-summary ↔ skills 描述同一事实不得打架；改任一处的机制/数值必须四处核对。

**判定**：文档与代码一致；START-HERE/README 索引已含新增项；无「文档说完成但代码/运行实例未生效」的失信。

---

## 6. 步骤六：spark 与本机端相互检查并更新

**做什么**：确保**两端（Windows 主库 ↔ spark 运行时）**代码/文档一致，差异化配置不误覆盖。

- 首选集中同步：`python runs/sync_to_spark.py`（tar 整包外传，排除 .git、机器配置 deploy/llm/pipeline、产物 logs/outputs、审计 workflows/h3_*；`--clean` 才全量，默认增量；`--dry-run` 先看）。
- 保守/定点同步（只同步本次改动，避免覆盖 spark 运行时代码）：用 `scp` 只传改动文件到 spark 对应路径。
- 双向核对：
  - `ssh spark "git -C /home/Developer/videoGenerate-Model-zju status --short"`（看是否一致/有无悬空改动）。
  - `git -C <repo> rev-parse HEAD` 对照 `ssh spark "git ... rev-parse HEAD"`。
  - 涉及 agent：重启 `runs/agent/`（见 6.1），再看版本指纹/界面状态条。
- 差异化配置（deploy.json/llm.json/pipeline.json/transfer.json/autosync.json/.sync-state.json/last_job.json）两端本就不同，**不随整仓同步覆盖**；同步清单见 `runs/sync_to_spark.py` 的 `EXCLUDE_FILES`。

**判定**：两端改动文件一致、版本指纹可对应、差异化配置未被误覆盖。

### 6.1 重启 agent（需授权时）
- **实测形态（2026-09-04）**：7860 由 **tmux 会话 `agent`** 承载（会话内命令：`bash -c python runs/agent/scheduler.py 2>&1 | tee ~/agent.log`，即 `start_qwen_agent.py` 调用的 `runs.agent.scheduler.main`）。**注意：会话名是 `agent`，不是 `qwen-agent`**（旧文档写错，曾导致重启落空）。
- **正确的重启**（经授权后）：`ssh spark "tmux kill-session -t agent 2>/dev/null; tmux new-session -d -s agent 'cd /home/Developer/videoGenerate-Model-zju && python runs/agent/scheduler.py 2>&1 | tee ~/agent.log'"`；或 `bash shell/manage_services.sh start`（统筹 ComfyUI/SGLang）；仅停 Qwen：`bash shell/stop_qwen.sh`。
- **验证（关键，防假绿）**：① `ssh spark "ss -ltnp | grep 7860"` → **端口持有者 PID 的启动时间**必须 ≥ 本次重启时刻；② `curl -s http://127.0.0.1:7860/config | grep -o "加载所选历史"`（或关键新文案）确认真实渲染新文案；③ 日志 `~/agent.log` 尾部出现 `AGENT_VERSION=<commit>` 与启动完成标记。
- ⚠️ **反例**：`curl` 返回 HTML、`ps` 看到 PID **只证明有进程在监听，不证明是新代码**——2026-09-04 曾有报告据此称“重启成功”，实际新进程抢不到端口即退、旧进程仍在服务（book-09 铁律实例）。

---

## 7. 步骤七：git 提交

**做什么**：两端各自提交，事务化留痕。

- **Windows 主库（唯一推 GitHub 的一端）**：
  - `git -C D:/MY_CODING_PROGRAM/videoGenerate-Model-zju add <改动文件>`
  - `git ... commit -m "<type>(<scope>): 摘要" -m "<说明>"`（type 常用 docs/fix/feat/refactor/test）。
  - `git ... push origin master`（注意：PowerShell 下 git 把进度写 stderr，会显示 exit 1，但 `X..Y master -> master` 表示成功）。
- **spark 运行时**：
  - `ssh spark "cd /home/Developer/videoGenerate-Model-zju && git add <改动文件> && git -c user.name=Developer -c user.email=dev@spark commit -m <摘要> -m sync_from_Windows_<win_commit>"`
  - spark **永不 push GitHub**；仅本机提交留痕。
- 提交后核对：Windows `git log -1`、push 后 GitHub 一致、spark `git log -1`。

**判定**：Windows/GitHub/spark 三处版本可对应；每个改动都在 git 里有可追溯的 commit。

---

## 8. 常见反例（避免踩坑）

- ❌ 「界面没改」却直接改代码 → 先查 spark 跑的是不是旧版（步骤一 / planbook book-01）。
- ❌ 「文档标完成」但 spark 进程没重启 → 步骤四要求真实运行证据。
- ❌ 大模型「读代码说正常」当通过 → 不算（步骤四）。
- ❌ 在 spark 上乱改后再同步回 Windows → 一律 Windows 主库改、spark 跟随（单向到 spark）。
- ❌ `sync_to_spark.py --clean` 直接上 → 会删远端目录；默认增量即可（步骤六）。
- ❌ 改常量/路径/工具数只改一处 → 按 `START-HERE.md §5` 四处核对（步骤五）。
- ❌ 脚本直调 `run_turn`/`_run_tool` 就算“测试通过”——须走真实 Gradio send() 事件链（或等价全链；判据见步骤十二）。
- ❌ 要求“说话/配音”却用无音频通道的 t2v → 输出为噪声，**不得宣称语音通过**（book-16 台账#6；T2b 语音链 P0 完成前一律如实标注「无可用语音」）。
- ❌ 报告里写「模型未返回内容」＝通过 → 不通过；界面必须出现非空总结文本（END=done 且 text_len>0）。

---

## 9. 关联文档
- `START-HERE.md §3`（红线）、`§5`（同步/口径规则）、`§6`（版本记录）。
- `docs/planbook/book-01-governance-baseline.md`（基座/可信部署）、`book-09-phase8-verification-regression.md`（验证门禁）。
- `skills/dev-workflow.md`（本流程的精简卡）。

---

## 10. 附录 A：Windows 文件写入与 EIO（Win32 1175）经验（2026-09-04 归纳）

### 10.1 现象
- `ToolCallError: ReplaceFileW EIO (Win32 1175): <file>` —— **编辑/覆盖已有文件**时偶发；新建文件（CreateFile 路径）几乎不触发。

### 10.2 原因（本环境实测归纳）
- Win32 1175 = ERROR_UNABLE_TO_MOVE_REPLACEMENT_2：`ReplaceFileW`（原子替换）要求目标文件不被其它句柄独占；以下场景会短暂占住目标：
  1. 杀毒/Defender 实时扫描（写入后即刻重查）；
  2. Windows Search 索引器；
  3. 刚结束的 python/git 子进程句柄未及时释放（尤其 `python -m py_compile` 写 __pycache__、`dev.py check/sync`、scp/ssh）；
  4. 工具链自身的读缓存/mtime 跟踪（常伴生 `file changed since it was read` 提示）。
- **高频模式**：执行子进程后**立刻**编辑同一文件；或对同一文件**连续多次** edit。

### 10.3 处置（按顺序，已逐条验证）
1. 直接重试一次（大多数占用秒级释放）；
2. 仍失败 → 改用 PowerShell `[IO.File]::WriteAllText`（fopen 直写，非 ReplaceFileW；本会话零失败），配合字符串替换 patch；
3. 长链改动改为「先 read 再整体 write」（整文件重写比逐处 edit 稳）；
4. 规避：编辑前不要紧挨着跑 py_compile / consistency_check / dev.py 等子进程；同一文件一轮内避免多次 edit；看到 changed-since-read 先 re-read 再 edit。

### 10.4 关联：脚本/字符串转义教训（一并记录）
- 在 run_code 的 JS 里拼文档/Python 源码时：内容含 **ASCII 单引号** 会中断 `push(…`（改用完整字宽引号 `“ ”` 或 JS 双引号包裹）；含 **反引号** 会中断模板串（需要转义）；`$` 加 `{` 会插值；`\n` 会变成真换行。
- 经验：**优先「行数组 + join」**；文档内容一律完整字宽引号；给 PowerShell 传含反引号/美元符号的字符串时整体转义，或用 `[char]10` 拼新行，避免多层嵌套。

---

## 11. 日志体系（book-11 约定，2026-09-04）

**口径**：统一 Writer = `runs/h3/logutil.py`（唯一实现）；事件行格式 `[YYYY-MM-DD HH:MM:SS] py: <tool> <event k=v>`；文件头 `# TZ=UTC+8`；`logs/` 目录 Git 忽略、自动轮转（单文件 5MB → `.1`）。

- **查看/清理**：`python runs/dev.py logs view [-N] [--remote]`（本地 run log 尾部 + 审计 jsonl；`--remote` 追加 spark `~/agent.log` 与 logs/ 清单）、`python runs/dev.py logs check`（格式/坏行/轮转健康；自动跳过 book-11 前旧格式日志）、`python runs/dev.py logs clean [--yes]`（清 `.1` 轮转，默认 dry-run）。
- **agent 行为审计**：`logs/agent_tool_audit.jsonl`（每工具调用一行：ts/tool/关键参数/stage-resolution-seconds-images-session/prompt_id/result_len/ok）。
- **`~/agent.log` 运维（保留 360 天，用户定稿）**：该文件是 tmux 会话 `agent` 的 tee 输出（scheduler 全部 stdout/stderr），会持续增长；**临时排障**用 `tail/grep`，**不要**在 `dev.py logs` 里默认拉全量。
  - **轮转**：`python runs/dev.py logs agent-log rotate` —— 必须在 **agent 已停止、重启之前** 调用（先 `tmux kill-session -t agent`）：把当前 `~/agent.log` 归档为 `~/agent.log.<YYYYMMDD>` 并清理超过保留天数（默认 360）的旧归档、再 `touch` 新建。若在 agent 运行时轮转，旧 tee 句柄仍写旧归档（无实效）。
  - **仅清理旧档**：`python runs/dev.py logs agent-log --mode prune`。
  - 文档均以 `~/agent.log` 为准（旧文档 `~/qwen-agent.log` 已作废）。
- **不错失参数**：任务提交日志（submitted/submitted_only）必须含 `imgs/resolution/seconds/seed/steps/prompt_len`——若在日志里看不到这些字段，视为缺失（按 book-11 验收标准回归）。
- **组件事件统一格式**：`llm_mem`/`task-watch`（状态转移 `poll_state`）走进程内 logutil（run log 入库）；`sync_auto` 走 `logutil.log_file` 写 `logs/sync_auto.log`（同为 `[ts] py: …` 格式）；会话↔日志互链见 `logs/agent_chats/<cid>.meta.json`（run_log 路径）。

---

## 12. 验收纪律：『测试通过』的最低证据集（2026-09-05 用户四问后固化，来源：book-16 §6）

> 起因：用户连续质疑「你们测试究竟是 Qwen 真调工具还是你替代他调用」「每次说测试通过但网页基本没成功过」。事实：此前大量验证用脚本化 `run_turn`/`_run_tool` 直调，**绕过了真实 UI 事件链**；且“通过”未要求界面可见文本/真实产物/可辨析语音。

**“测试通过”必须同时满足以下四条件**（缺一即为未通过，只能写“部分验证”）：

1. **真实链路**：走 Gradio send() 事件链（HTTP → `_one_run` → SGLang → 工具执行 → 回填 → `done`），或明确标注等价全链；**禁止**只调函数/只跑脚本断言后宣称为“通过”。
2. **界面可见非空文本**：最终事件为 `done` 且 `final` 文本长度 > 0（防止“（模型未返回内容）”类空转；工具执行了但没有总结文本 = 未通过）。
3. **真实产物 + 可验证参数**：输出文件存在，且分辨率/时长/帧数/路径可复查（如 ffprobe：608×352/5.17s/124 帧）。
4. **语音要求时语音可辨析**：凡任务要求“说话/配音”，产物音轨须为可听懂的中文语音（非噪声）；当前 t2v **无音频通道**（`features.audio=false`，输出音频=噪声）——T2b 语音链（book-14，P0）完成前，**不得宣称任何语音类测试通过**。

**验收报告模板**（写入 planbook/会话记录）：

```
- 链路：真实 UI send / 脚本全链（注明）
- 事件：done · 文本长度 N · 工具：call_comfyui 真实执行 1 次（频控跳过 M 次）
- 产物：<path> · ffprobe 参数 <WxH/fps/时长/帧> · 音轨：有/无（有则音质=可辨析/噪声）
- 结论：通过 / 未通过（列缺口）
```

**已知待整改**（截至 2026-09-05）：① “UI 无内容”已修复（ui_app.py 轮末兜底总结 + 促收尾回填；见 book-16 §6.3）；② 语音链 T2b P0 待实施（book-14）；③ 任何将来“通过”均须套用本节模板。