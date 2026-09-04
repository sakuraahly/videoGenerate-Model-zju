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
- 本项目自测/烟测：在 spark 跑 `tests/e2e_smoke.py`（若已建）或对**本阶段**的最小脚本；改前端就 grep 界面字符串、改 h3_batch 就跑 `h3_batch.py submit --dry-run`。
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
- 用户授权后：重启 spark 上的 `qwen-agent` 会话（Gradio 7860），按 `docs/qwen38-deployment.md` / `shell/stop_qwen.sh` 所述方式（或 `bash shell/manage_services.sh start`）。
- 或按 `shell/manage_services.sh restart`（会统筹 ComfyUI/SGLang，需人工场合）。
- 仅停 Qwen（不碰 ComfyUI）：`bash shell/stop_qwen.sh`。
- 重启后验证：`ssh spark "ss -ltn | grep 7860"` + 看 `~/qwen-agent.log` 尾部 + 界面版本指纹。

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

---

## 9. 关联文档
- `START-HERE.md §3`（红线）、`§5`（同步/口径规则）、`§6`（版本记录）。
- `docs/planbook/book-01-governance-baseline.md`（基座/可信部署）、`book-09-phase8-verification-regression.md`（验证门禁）。
- `skills/dev-workflow.md`（本流程的精简卡）。