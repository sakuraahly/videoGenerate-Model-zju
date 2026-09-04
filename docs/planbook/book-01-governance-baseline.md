# 阶段 0 — 基座与可信部署（Governance & Trusted Baseline）

> 状态：计划(未实施) | 目标：让"改什么、去哪跑、凭什么说好了"都有唯一事实源与可重复部署路径 |
> 主负责人：运维/接手者 | 依赖：无 | 对后端影响：治理性（不改业务行为） | 优先级：🔴 前置必读

---

## 1. 问题背景

用户反馈的一组现象看似都是"代码没写好"，但实测发现它们很可能是**同一个根因**的多种表现：

- 界面"依旧处于没有修改的状态"，按钮仍是"加载所选"（文档却标了"已完成 ✅"）。
- 运行中 Agent 报 `ModuleNotFoundError: No module named runs`，而 Windows 主库最新提交就是修这个的（`0761374`）。
- 文档说"5 工具"，代码已是 6 工具；`UI_TRIM_TOKENS` 文档=1800、代码=2200。
- 之前的云端大模型"审查/测试"疑似绕开真实执行，输出"一切正常"。

→ 共同指向：**运行实例(spark)上跑的代码与 Windows 主库/GitHub 不一致，且没有任何可靠的"从某个提交到运行实例"的路径，也没有验证"跑的就是想要的代码"的手段。**

---

## 2. 根因分析（实测证据，见 book-00 §1）

### 2.1 三处副本状态漂移
- **Windows 主库** `D:/MY_CODING_PROGRAM/videoGenerate-Model-zju`：git 最新 `0761374`（第六/七批之后，含 h3_batch 修复）。
- **spark 运行时** `/home/Developer/videoGenerate-Model-zju`：git 最新 `2ee5a0b`（sync from Windows a5cfbcc），显著落后；工作区另有大量**未提交**改动（新增 `session_state.py`/`task_watch.py`/`turn_state.py`/`mediacheck.py` 等，修改 `ui_app.py`/`scheduler.py`/`tools.py`/`refimage.py` 等）。
- **GitHub** `sakuraahly/videoGenerate-Model-zju`：仅由 Windows 主库 push，与 spark 无直接关系。
- 结论（写作时）：spark 上"能跑"的 = 旧 git 提交 + 手改/未提交副本 的混合物，**无法复现**。
- **2026-09-04 晚更新**：该漂移已由 `runs/dev.py` 的 sync/commit 追平——spark HEAD `d0da789` = Windows `1d42902`（仅提交身份不同）；spark 磁盘 `ui_app.py` 已是含新文案的版本（`08:18` 落盘）。**但真正没解决的是运行进程**：7860 端口持有者 `python runs/agent/scheduler.py`（PID 746835，`06:18` 启动，早于代码 2 小时）——即「**代码对、进程旧**」。本册的版本指纹/重启验证因而是当务之急（重启实测方法见 `docs/dev-workflow.md §6.1`，已按实测修正：tmux 会话名=`agent`、必须验证端口持有者启动时间与新文案/指纹）。

### 2.2 同步机制本身可能造成"半同步"
- `runs/sync_to_spark.py` 是 **tar 整包外传**（排除 .git、机器配置 deploy/llm/pipeline、产物 logs/outputs、审计 workflows/h3_*），解包到 spark `~/<项目名>`。
- 它**不改 spark 的 git 状态**，只覆盖磁盘文件。因此 spark 出现"磁盘文件=新、git log=旧"的**半同步**常态。
- 每次 sync 之后 spark 的 git 是否 commit、commit 身份（内联 `-c user.name=Developer -c user.email=dev@spark`）、是否 push，取决于人工，**没有强制门禁**。

### 2.3 没有"运行实例版本指纹"
- 目前没有任何机制让 runtime（Gradio/SGLang）**自报**它跑的是哪个 commit/代码版本。
- 因此无从判断"界面未改"是因为代码没写、没同步，还是进程没重启。

### 2.4 验证可信度缺失（防绕过缺口）
- 既有"验证"大量依赖大模型阅读结论；没有一套**本项目自己的、在 spark 真实环境跑的最小自测/端到端**。

---

## 3. 目标与范围

**目标**：建立一条**可重复、可验证、自带版本指纹**的"代码→spark 运行实例"路径，并让"完成=有真实执行证据"。

**做**：
- 确立唯一事实源与部署路径（源码=Windows 主库；镜像=GitHub；运行实例=spark 经部署）。
- 给运行实例加**版本自报**机制（启动打印 + 界面状态条显示 commit/版本）。
- 加**运行时配置核对**（关键常量/路径/工具数是否与代码一致）。
- 建立**防绕过自测门禁**（最小自测/端到端 + 证据留痕）。
- 建立**口径一致性登记/检查**（复用/扩展 `runs/consistency_check.py`）。

**不做/红线**（见 book-00 §P6）：不重启/改 ComfyUI systemd；不改 spark 同事模板；不提 api_* 云模板；不写 Z: 盘；不越白名单工具做 shell/文件/服务管理。

---

## 4. 改动点清单（拟议，精确到文件）

| 文件 | 拟改内容 | 目的 |
|---|---|---|
| `runs/agent/ui_app.py` | 启动/界面状态条打印当前代码版本（读仓库 commit 或 `VERSION` 文件） | 版本自报 |
| 新增 `runs/agent/version.py` | 计算并暴露当前版本/commit 指纹（git describe 或文件哈希兜底） | 唯一指纹来源 |
| 新增 `runs/agent/runtime_check.py` | 核对关键常量/路径/工具数（`ctx_budget` 常量 vs 文档、spark 路径、工具注册数） | 运行时一致性 |
| `runs/consistency_check.py` | 扩展：增加"工具数/常量/路径"与文档登记表的一致性检查 | 静态口径一致性 |
| 新增 `docs/code-fact-registry.md` | 单一事实登记：路径、端口、常量、工具数、deploy 形态、关键模型/模板 | 口径唯一源 |
| 新增 `shell/sync_and_verify.ps1`（或扩展 `runs/sync_to_spark.py`） | 一键：同步 → 重启用例 → 等待就绪 → 跑版本自报/自测 → 结果 | 可重复部署门禁 |
| 新增 `tests/e2e_smoke.py`（spark 运行） | 最小自测：读版本指纹 + 关键常量核对 + 白名单工具可导入 + `h3_submit --dry-run` | 防绕过证据 |

> 说明：以上为**拟议**改动点，供校验；实际实施时以"能自证身份、能自证一致、能自证可跑"为最低目标，不必拘泥本表。

---

## 5. 实施步骤（每步可独立验证）

### 步骤 1：登记三处副本现状快照
- 在 `docs/code-fact-registry.md` 记录：Windows 当前 commit、GitHub 最新 commit、spark 当前 git 与磁盘差异（`git status` + 关键文件 diff）。
- 证据：三条命令的输出（`git -C <repo> log -1` / `git rev-parse HEAD` / `ssh spark "git -C /home/Developer/videoGenerate-Model-zju status --short"`）。

### 步骤 2：确立并写死"唯一事实源 + 部署路径"
- 写清：源码=Windows 主库（唯一 push GitHub）；spark 运行镜像=经 `sync_to_spark.py`（或 `sync_auto.py`）同步；spark git 只做记录、永不 push GitHub；机器配置不入库。
- 在 `docs/code-fact-registry.md` 用"谁是真源/谁被谁覆盖/哪些文件两端本就不同"表格钉死。

### 步骤 3：给运行实例加版本指纹 + 启动自报
- 实现 `runs/agent/version.py`：优先 `git rev-parse --short HEAD`（spark 仓），失败则用关键文件 mtime/hash 兜底，产出 `AGENT_VERSION=<commit>`。
- `ui_app.py` 启动时打印 `AGENT_VERSION`，并在界面状态条/页脚显示；使"当前跑的是哪个代码"一眼可查。
- 验收：重启 agent 后，tty/日志/状态条能看到与 Windows 主库一致的版本指纹。

### 步骤 4：加运行时配置核对
- `runs/agent/runtime_check.py`：比对 `ctx_budget` 关键常量、`tools` 注册工具集、spark 项目路径、`config/deploy.json` 形态，与登记表一致；不一致则输出醒目告警并提示"以代码为准"。
- 在 `ui_app` 状态条前端提示"配置漂移告警"（可选）。

### 步骤 5：建立防绕过自测门禁
- 落一个 `tests/e2e_smoke.py`（在 spark 跑）：读版本指纹 → 断言常量一致 → 导入 5/6 个白名单工具 → 跑 `h3_submit.py --stage t2v --dry-run`（需能出 dry-run JSON）→ 打印 `SMOKE_OK`。
- 约定：**未跑出 `SMOKE_OK`，任何"完成"声明一律视为未完成**；大模型"阅读说正常"不作为证据。

### 步骤 6：口径一致性登记 + 扩展 consistency_check
- 把 `code-fact-registry.md` 的关键事实与 `consistency_check.py` 打通（新增对工具数/常量/端口等登记项的核对）。
- 修复已知文档-代码漂移（`UI_TRIM_TOKENS`、spark 路径 `/home/Developer/...`、工具数 5→6、deploy 形态说明），以代码为准回写登记表与文档。

### 步骤 7：一次可信的"基线部署"演练
- 从 Windows 主库出发：commit → push GitHub → `sync_to_spark.py` → 重启 agent → 跑 `e2e_smoke` → 确认版本指纹一致。
- 用此基线作为后续各阶段"改动前对照"，任何阶段改动都回到该基线再增量叠加。

---

## 6. 验收标准（可在 spark 真实环境复现）

- [ ] `ssh spark "cd /home/Developer/videoGenerate-Model-zju && git rev-parse --short HEAD"` 与 Windows 主库 `git rev-parse --short HEAD` 指向**同一代码基线**（或明确记录差异并说明）。
- [x] 重启 agent 后日志/界面可见 `AGENT_VERSION` 指纹；该指纹可追溯到某个 commit。
- [x] `python tests/e2e_smoke.py` 在 spark 输出 `SMOKE_OK`，且不依赖任何大模型判定。
- [x] `python runs/consistency_check.py` 不再报告已登记的关键不一致项（工具数/常量/路径）。
- [x] 一次基线部署演练成功：Windows→GitHub→spark→重启→自测全链路有留痕。

---

## 6b. 实施记录（2026-09-04 第一轮）

- ✅ 已落地：`runs/agent/version.py`（版本指纹；以 `__file__` 推导根目录，不信 env——因 `scheduler.py` 会把 `VIDEOGEN_PROJECT_ROOT` 设为 `expanduser(~/...)`，Windows 上会落到残留副本）；`runs/agent/runtime_check.py`（常量/工具/形态/路径/指纹 6 项核对）；`tests/e2e_smoke.py`（指纹+工具+`h3_submit t2v --dry-run`+runtime_check → `SMOKE_OK`）；`scheduler.py` 集成 version（启动打印 `[agent] AGENT_VERSION=...`）；`ui_app.py` 头部显示 `版本指纹：<commit>`；`consistency_check.py` 增加 `check_runtime_facts`；`docs/code-fact-registry.md`（单一事实登记）。
- ✅ 本机自测：`runtime_check` 全 [OK]（工具/LLM 项 [SKIP]，需 spark）；`e2e_smoke` 本机 `SMOKE_OK`（工具项 [SKIP]）；`consistency_check` 问题 0。
- ⏳ 待 spark 验证（同步+重启后）：e2e_smoke 全量（工具项真实检查）；重启后日志与界面头部可见 `AGENT_VERSION`。
- ✅ spark 验证（2026-09-04）：`/home/Developer/qwen-agent-venv/bin/python tests/e2e_smoke.py` → **SMOKE_OK**（版本指纹 9396309、工具 6 类齐全、`h3_submit t2v --dry-run --force-new` rc=0、runtime_check [OK]）；重启 agent（tmux `agent`）后日志与 /config 头部均显示 `AGENT_VERSION=9396309`（PID 831077，11:12 启动）。
- 📌 实测要点（已写入 smoke/文档）：① 必须用 **venv python**（system python3 无 qwen_agent）；② dry-run 需 `--force-new`（否则被遗留 last_job.json 断点守卫拦）；③ deploy.site 按端判定（spark=spark-local，Windows=win-remote），已按端修正 runtime_check。
- 🔧 实施中发现并修复：`scheduler.py` 无条件把 `VIDEOGEN_PROJECT_ROOT` 写成 `expanduser(~/...)`——在 Windows 指向 `C:/Users/<user>/videoGenerate-Model-zju` 残留副本，导致版本/部署探测定错根；已改 `version.project_root()` 以本文件位置为准（env 仅作“确指向真实仓库”时的覆盖）。

---

## 7. 风险与回滚

- **风险 A：sync_to_spark 覆盖两端本应不同的机器配置**——当前它已排除 deploy/llm/pipeline 等，需保持排除清单，勿把 `docs/planbook` 之外的本应差异化文件卷入。
- **风险 B：给 spark 加版本自报引入崩溃**——用 try/except 兜底，版本取不到就显示"unknown"，不影响启动。
- **风险 C：把"同步"做成破坏性**——坚持增量（默认）而非 `--clean`，且只在确认后执行；回滚=重新从 Windows 同步上一次稳定 commit。
- **回滚**：任何一步失败，恢复为改动前的源码（git stash/checkout）与 spark 上次已知良好基线；本册为治理性改动，不改变业务行为，回滚风险低。

---

## 8. 与其它册/红线的关系
- 是 book-02 之后各册的**前置**：各册"完成"都需凭本册的验证门禁给出证据。
- 与 book-09（可信验证与回归）互补：本册定"基座/版本/门禁"；book-09 定"方法/黄金路径/回归清单"。
- 红线遵守：不重启/改 ComfyUI systemd、不动 spark 同事模板、不启用 api_*、不写 Z: 盘、不越白名单。

---

## 9. 待用户输入 / 待定项
- 运行形态以哪个为准（`config/deploy.json`=win-remote vs 交付文档强调 spark-local）→ 需要用户确认或明确"当前以 win-remote 为准"并统一文档。
- 是否允许更新 spark 运行实例（涉及重启 agent 进程、可能短暂中断服务）→ 需用户授权后再执行。
