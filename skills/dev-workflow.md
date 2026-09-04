# Dev Workflow Skill — 变更与交付工作流（速查卡）

> 用途：**本仓库一切改动**（代码/文档/skill/配置）必须按此流程执行。完整版：`docs/dev-workflow.md`。
> 一句话：`执行任务→修改→测试→自测通过→写入文档→双端核对更新→git 提交`，**每步不通过回到上一步**。

---

## 1. 执行任务（先读后做，先取证后动手）
- 先读 `START-HERE.md §2`、`docs/session-summary.md`（事实源）、相关 skill/文档。
- 先判断「问题根因」四选一：①代码没写 ②写了没同步 ③同步了进程没重启 ④文档先行、代码滞后。
- 涉及运行实例：先确认 spark 跑的版本（`git rev-parse HEAD` / 版本指纹），别一上来就改代码。

## 2. 修改
- 最小、低耦合改动；一次一个关注点；改前 `read`，改后能 git 还原。
- 红线：不动 ComfyUI systemd/配置；不改 spark 同事模板；不提 api_*；禁 `Z:/` 路径；Agent 只做白名单动作。
- 常量/路径/端口/工具数：改一处须四处核对（`START-HERE.md §5`）。

## 3. 测试
- 静态：`python runs/consistency_check.py`。
- 单元：`python -m pytest runs/h3/tests -q`（若相关）。
- 烟测/最小自测：对**本阶段**跑最小脚本；前端→grep 字符串；h3_batch→`submit --dry-run`；工作流→`h3_submit --dry-run` 看注入。

## 4. 自我测试通过（防绕过门禁）
- 必须给出**本项目自己跑出的**真实证据（`SMOKE_OK`/`TASK_SUBMITTED`/`LOCAL_OUTPUT`/`consistency_check` 无问题/截图/日志）。
- 大模型「我看了没问题」**一律不算通过**；未跑出证据 = 未完成。
- 五项全满足才叫过：①改的是 Windows 主库且 spark 经部署/重启一致 ②有真实执行证据 ③双端一致 ④口径一致 ⑤未越红线。

## 5. 写入文档 / skills
- 状态类：`docs/session-summary.md`、`docs/handoff-2026-09-04.md`。
- 参考类：`docs/reference-2026-09-04.md`、`docs/agent-workflow.md`、`docs/robustness-and-modularity.md`。
- 计划类：`docs/planbook/`（各阶段计划与验收结果）。
- **索引同步**：新增/改/删任何 `docs/`、`skills/` → 更新 `START-HERE.md §2` 与 `README.md` 文档表、`START-HERE.md §6` 版本记录。
- 口径一致：同事实四处核对，不得打架；冲突处以运行代码为准并登记。

## 6. spark 与本机端相互检查并更新
- 集中同步：`python runs/sync_to_spark.py`（增量，`--dry-run` 先看；`--clean` 慎用）。
- 定点同步：只 `scp` 本次改动文件到 spark（避免覆盖运行时代码）。
- 核对：`git -C <repo> rev-parse HEAD` 对照 `ssh spark "git -C ... rev-parse HEAD"`；看 spark `git status --short`。
- 差异化配置（deploy/llm/pipeline/transfer/autosync/.sync-state/last_job）两端本就不同，**不整仓覆盖**。
- 需要重启 agent（先获授权）：按 `docs/qwen38-deployment.md` / `shell/stop_qwen.sh` / `manage_services.sh start` 重启，验证 7860 + 日志 + 版本指纹。

## 7. git 提交
- Windows（唯一推 GitHub）：`add` → `commit` → `push origin master`（PowerShell 下 git 进度写 stderr 会 exit 1，看到 `X..Y master -> master` 即成功）。
- spark（永不 push GitHub）：`git add <改动文件> && git -c user.name=Developer -c user.email=dev@spark commit -m <摘要> -m sync_from_Windows_<win_commit>`。
- 核对三处：Windows `git log -1`、GitHub 一致、spark `git log -1`。

---

## 红线速查（再次强调）
- ComfyUI = systemd，勿重启/勿改 systemd；只 `POST /free` 腾内存。
- spark 同事模板只读，永不修改；只改 `workflows/remote_workflows/`、`config/templates/`。
- `api_*` 云模板不提及不调用；本地用 `video_*`。
- 禁 `Z:/` 路径；一律 `~/...` 或 Windows 主库。
- Agent 无 shell/任意文件/服务管理；越权即拒并转人工。
