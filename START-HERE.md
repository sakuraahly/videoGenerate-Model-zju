# ⛳ START HERE — 新参与模型 / Agent 总入口（先读本文件）

> **位置与角色**：本文件位于仓库**根目录**（最显眼处，README 顶部已放入口链接）。
> 它是“所有新参与的模型/Agent/协作者”的**单一入口**，同时是**文档与 skills 的活索引**：
> 任何新增/修订文档或技能都必须回写本文件（见 §7 同步规则），保证后来者永远能从这里
> 找到正确、最新、完整的阅读路径与项目架构。
>
> 最近更新：**2026-09-04**（创建；含 ctx-8192 token 预算化修复批次成果与工作文件夹速查；
> 第三批：对话历史丢失修复、禁用自动 nap、系统提示词自主性重写、上传体验优化；
> 第四批：tools.py TimeoutExpired bytes/str 拼接 bug 修复、压力测试验证；
> 计划书：新增 `docs/planbook/`（系统性修复计划，含基座/前端/输出/自动完成/资源隔离/工作流/引擎/风格/验证，见 §2 第 10 条））
> 事实权威：`docs/session-summary.md`（历史批次与现状）；最新交接：`docs/handoff-2026-09-04.md`；
> 详细参考：`docs/reference-2026-09-04.md`。仓库双端：Windows 主库 ↔ GitHub ↔ spark 运行时。

---

## 1. 一句话项目概览

MiniMax H3（Hailuo-03）**视频生成自动化工具集**：输入场景描述/素材 → 在远程 DGX Spark
（ssh 别名 `spark`）上用 **ComfyUI + H3 本地模型**推理出带原生音轨的视频
（`outputs/video_N.mp4`）；本地 Qwen3.8-27B（SGLang）作为**受限调度器**（7860 界面）与
**提示词生成器**（AI 桥），全程可控工具、不越权、不碰云端（`api_*` 模板需 Comfy 云登录，
本地语义由 `video_*` 四类覆盖）。

## 2. 阅读顺序与必读清单（角色标注）

| 优先级 | 文件（仓库根相对路径） | 读它获得什么 | 适用 |
|---|---|---|---|
| 1 | **`START-HERE.md`（本文件）** | 总入口：架构速览、阅读索引、路径/红线、参与规范 | 所有新参与模型/Agent |
| 2 | `README.md` | 功能清单、快速开始、目录结构 | 所有 |
| 3 | `docs/session-summary.md` | **历史事实源**：逐批次做了什么/当前状态/双端路径（§14 文件夹速查） | 所有（事实以它为准） |
| 4 | `docs/handoff-2026-09-05-continue.md` | **最新交接（2026-09-05 八审后）**：仓库/服务事实、已完成批次、待做总览（S2-P1a→S3→S8 起始）、铁律/防坑/未决项 | 所有（接手下一轮工作前） |
| 5 | `docs/reference-2026-09-04.md` | 详细工程参考：配置注册表、引擎/工具/Agent 契约、模板明细、故障字典 | 所有（查参数/契约/排障） |
| 6 | `skills/h3-video-generation.md` | 生成任务全流程技能卡（§0b 路径速查与 Z 盘红线、§1.3c 上下文预算机制） | Agent/操作者做生成任务 |
| 7 | `skills/h3-prompt-engineering.md` | 提示词工程规则（结构/中文渲染/音频句等） | 写任何生成提示词前 |
| 8 | `docs/agent-workflow.md`、`docs/agent-reading/00–04` | 7860 Agent 工作链手册与执行协议（提交/续传/取件、素材链、输出纪律） | 调度/使用 Agent 完成任务 |
| 9 | `docs/quickstart.md` / `docs/user-guide.md` / `docs/deploy-modes.md` / `docs/llm-memory-optimization.md` / `docs/qwen38-deployment.md` / `docs/h3-workflow-architecture.md` / `docs/h3-troubleshooting.md` / `docs/long-term-maintenance.md` 等 | 新手入门 / 用户手册 / 部署形态 / 内存账本 / Qwen 部署 / 工作流架构 / 故障排查 / 长期维护 | 按需定向阅读 |
| 10 | **`docs/planbook/book-00-overview.md`**（+ book-01…book-17） | **系统性修复计划书**：痛点→阶段映射、基座/可信部署、前端/输出/自动完成/资源隔离/工作流/引擎/风格、验收门禁与黄金路径 | 修复负责人（多轮校验先读 book-00） |
| 10b | `docs/planbook/book-17-model-fabrication-defense.md` | **计划·待批准**：模型伪造工具调用纵深防御（白名单/Schema 前置校验/修复重试/钩子/幂等/审计/人在回路）+ 流程自动化合规（必用 dev.py + spark 项目文件口径）+ LoRA/低参验证策略 + T2b 语音链联动 | 批准后实施负责人 |
| 10c | `docs/planbook/book-18-quality-prompts-and-clarity.md` | **已实施完成**：质量提示词固化（Q+/Q- 每轮注入+防漂移断言）+ 语音/文字清晰度加强（取舍表已定；听测通过） | 已归档 |
| 10d | `docs/pending-tasks-implementation.md` | **待做任务·实现规格（当前定稿）**：S1-S13 各任务现状/实现/验证/风险/回滚 + 约束事实表（供外部 AI 审核与实施；审核应答演变见 `docs/pending-tasks-changelog.md`） | 待实施 |
| 10e | `docs/pending-tasks-changelog.md` | **审核应答与修订历史（§14-§19 及后续轮次）**：仅供追溯，不指导实施 | 存档 |
| 10f | `docs/handoff-2026-09-05-L-tasks.md` | **book-14 L1–L5 交接（已完成批次）**：独立执行 Agent 规格与坑速查 | 已归档 |
| 11 | `docs/dev-workflow.md` / `skills/dev-workflow.md` | **变更与交付工作流**：执行→修改→测试→自测通过→写入文档→双端核对→git 提交（含如何操作） | 所有改动者（改任何文件前必读） |
| 12 | `docs/prompt-taxonomy.md` | **H3 提示词属性词库**：10 正向 + 9 负向分类（book-06 保留/注入的图像属性词） | 工作流/提示词维护者 |
| 13 | `docs/code-fact-registry.md` | **代码事实登记表**：路径/端口/常量/工具数/部署形态/模型模板唯一口径（冲突以运行代码为准） | 所有改动者（改前查表） |

> `docs/agent-reading/` 是 agent `read_doc` 工具的动态清单（新增文档自动出现在工具描述中），
> 任务执行细节以其中 `04-agent-workflow.md` 为速查。

## 3. 项目架构速览（必要背景）

### 3.1 拓扑与运行形态

```
[Windows 工作站]                          [spark: DGX Spark GB10 / aarch64 / 121GB 统一内存]
 D:\MY_CODING_PROGRAM\videoGenerate-Model-zju     ┌──────────────────────────────────────────────┐
 （git 主库，唯一推 GitHub 的一端）                │ ~/ai/ComfyUI           :8188 (systemd,勿动)    │
   │  git push / sync_to_spark / scp              │   + H3 四件套模型（本地推理 4 类工作流）      │
   ▼                                              │ ~/Qwen3.8-27B (SGLang) :8000  ctx=8192       │
 spark: ~/videoGenerate-Model-zju（运行时仓库）────▶ │ ~/qwen-agent-venv UI  :7860 (自研 ui_app)     │
 （spark-local 形态：同机直连，无隧道）              │ Open WebUI            :3000 (纯聊天,当前未启) │
                                                  │ 内存协同：llm_mem nap/wake（视频任务让位）     │
                                                  └──────────────────────────────────────────────┘
```

- 运行形态由 `config/deploy.json` 的 site 决定：**spark-local（现状/交付）** / win-remote（本机+隧道），切换见 `docs/deploy-modes.md`。
- 两端代码同步：改 Windows → commit → push GitHub → sync/spark commit（spark 永不推 GitHub，commit 需内联身份 `-c user.name=Developer -c user.email=dev@spark`）；机器配置（deploy/llm/llm_mem/pipeline 等）不入库、不随同步。

### 3.2 工作文件夹（双端全景，详见 `docs/session-summary.md §14` / `skills/h3-video-generation.md §0b`）

| 规范路径 | 内容 |
|---|---|
| `D:\MY_CODING_PROGRAM\videoGenerate-Model-zju` | Windows 主库（git → GitHub sakuraahly/videoGenerate-Model-zju） |
| `~/videoGenerate-Model-zju`（spark） | 运行时仓库；`runs/agent/`=调度器代码；`logs/agent_chats/`=会话存档 |
| `~/ai`（spark） | AI 平台：`ComfyUI/`、`venv/`、`models_dl/`、H3 清单 sha |
| `~/ai/ComfyUI/` | `models/`（H3 四件套）、`input/`（user_uploads 上传镜像）、`output/`（产物 video/）、`user/default/workflows/`（同事模板**只读**） |
| `~/Qwen3.8-27B/`（spark） | Qwen 全家桶：models（NVFP4/bf16）、sglang-venv、vllm-venv、启动脚本、`start_qwen_agent.py`（7860 入口） |
| agent（spark） | 代码 `runs/agent/`；venv `~/qwen-agent-venv`；tmux `qwen-agent`；日志 `~/qwen-agent.log` |

⚠️ **Z: 盘 = 本机 SSHFS 网络映射盘（spark 主目录）——脚本/命令/配置/文档/skill/git 一律禁用 `Z:\…` 路径**，写 spark 真实路径 `~/…` 或 Windows 主库路径。

### 3.3 核心组件与数据流

- **引擎（生成）**：`runs/h3_submit.py` CLI（`--stage t2v|i2v|r2v|flf2v` / `--workflow-file` / 断点续传 / `--submit-only`），runs/h3/ 包做模板/UUID 子图解组/UI→API 转换/参数/日志；提示词按槽位注入（`prompts/manifest.json`）。
- **素材链**：上传（7860 直传 / upload_watch）→ `uploads/` 归档 + ComfyUI input 镜像 → `runs/h3/refimage.py` 三池 list/promote/use。
- **AI 桥**：`runs/h3/idea2prompts.py` 一句创意 → Qwen 生成各槽位提示词 JSON（模型有职责护栏：只当提示词生成器）。
- **Agent（调度器）**：7860 界面 `runs/agent/ui_app.py`（历史会话/直传/继续/中止/状态条/上下文预算）→ 调度器（`SYSTEM_MESSAGE` 内嵌核心知识）→ 5 个白名单工具（`run_script`/`modify_workflow`/`call_comfyui`/`read_doc`/`list_references`）→ 提交即返回（`TASK_SUBMITTED`），续传/取片走“无参重跑”。
- **开发工具盒（dev.py，2026-09-04 新增）**：`runs/dev.py` —— 把变更与交付工作流固化为 `check`（双端状态/漂移/一致性/文档索引）/ `sync`（定点同步改动文件到 spark）/ `commit`（Windows commit+push GitHub+spark commit）/ `docs`（START-HERE §2 索引校验）/ `test`（consistency+单测+干跑）五个子命令；一次调用拿到精简结论，节省 agent token（详见 `docs/dev-workflow.md`）。
- **上下文预算**（2026-09-04 修复，`runs/agent/ctx_budget.py`）：SGLang ctx=8192 硬顶 + 每轮固定开销 ≈3.1k token（系统+工具模板，实测）⇒ 对话精炼 ≤600 字/轮、历史 token 口径裁剪、超限自动压缩重试；改服务端 ctx 必须同步该文件常量。
- **内存协同**：`runs/agent/llm_mem.py` nap/wake——检测到 `TASK_SUBMITTED:` 自动停 SGLang 给 ComfyUI 让位，下一轮对话自动唤醒（1-3 分钟）。
- **审计/可靠性**：logs/run_*.log 全事件留痕 + workflows/h3_<ts>/job.json 任务联结；断点续传不重复生成；单实例锁；提交/等待分离。

### 3.4 红线速查（详见对应文档/skill）

1. ComfyUI = systemd 服务，**勿重启/勿改配置**；临时腾内存只用 `POST /free`（sudo 需人工）。
2. spark 同事工作流 `~/ai/ComfyUI/user/default/workflows/` **永不修改**；只改本地镜像 `workflows/remote_workflows/` 与 `config/templates/`。
3. `api_*`（Comfy 云）模板**不提及、不调用**（能力面已剔除）；本地语义用 `video_*`。
4. Qwen 本地模型带护栏：不执行服务器控制/任意文件/shell；越权请求拒绝并转人工。
5. ctx=8192：单轮回复精炼（≤600 字）、长内容分轮 + “继续”；不塞超长历史。
6. 路径规范：禁 `Z:\…`；时间口径：本地日志=北京，spark ls/journalctl=UTC（差 8h）。
7. 机器配置不入库；spark git 永不推 GitHub；会话存档/产物/logs 均 gitignore。

## 4. 参与规范（新模型 / Agent 开工 Checklist）

**开工前**
- [ ] 读完 §2 中 1–7 必读项（本文件 → README → session-summary → handoff → reference → skills）
- [ ] 核对 `config/deploy.json` site 与 §3.1 服务端口状态（LLM 8000 / ComfyUI 8188 / Agent 7860）
- [ ] 认清自己的角色与允许动作（生成任务 / 与 agent 对话 / 填词 / 只读分析），不越权

**工作中**
- [ ] 结论带依据：TASK_SUBMITTED / REMOTE_VIDEO_PATH / LOCAL_OUTPUT / logs/run_*.log
- [ ] 不重复提交、不删运行中断点（last_job.json）；超时≠失败（无参重跑=续传）

**收工后（写回知识，见 §7）**
- [ ] 执行了测试 → 在 `docs/handoff-2026-09-04.md §5` 测试清单回写实测
- [ ] 有批次成果 → 在 `docs/session-summary.md` 追加批次记录（§12/§13 样式）
- [ ] 改了代码/文档/skill → 同步 README/本文件索引；Windows 主库 commit → push → spark 同步 commit
- [ ] 改了服务端配置/ctx → 同步 `ctx_budget.py`、`llm_mem.json`、`llm-memory-optimization.md` 等口径

## 5. 本文件的同步规则（维护约定）

本文件是全仓文档与 skills 的**总索引与架构基线**，以下情况**必须**回写本文件：

1. **文档/skills 增删改**：新增、重命名或删除任何 `docs/`、`skills/` 文件 → 更新 §2 索引表（条目+角色标签）；README 的“文档”表同步增删。
2. **结构性变化**：拓扑/端口/服务启动方式/工作文件夹/模型/运行形态变化 → 更新 §3 各小节（并同步 handoff/reference/session-summary 对应处）。
3. **批次成果**：完成一轮工作 → 在 `docs/session-summary.md` 记批次，把“最近更新”行与相关小节刷新，新批次日期与内容记入 §6 版本记录。
4. **口径一致性**：本文件 ↔ README ↔ `docs/{handoff,reference}-2026-09-04.md` ↔ `docs/session-summary.md` ↔ skills 描述同一事实时不得打架；改任一处的机制/数值必须四处核对（例如 ctx/内存/端口/路径）。
5. 双端同步：Windows 主库改 → push GitHub → spark 副本同步（含本文件本身）。

## 6. 版本记录

| 日期 | 变更 |
|---|---|
| 2026-09-04 工具模块化计划 | 新增 docs/planbook/book-12-agent-tool-modular.md：Agent 工具自动化/模块化/通用化 + 多工作流配置驱动与便捷更换（注册表+适配器+动态 digest） |
| 2026-09-04 待做池 | 新增 docs/planbook/book-13-backlog.md：实施状态总览 + P0-P2 待办 + 架构优化任务（绑定统一/解析收敛/单源/轮询成本）+ 新观察 |
| 2026-09-04 日志计划 | 新增 docs/planbook/book-11-logging-system.md：日志系统治理与升级（全场景稳定/无垃圾/不错失 agent 行为与参数，含 dev.py logs 子命令规划） |
| 2026-09-04 EIO经验 | docs/dev-workflow.md §10 记录 Windows ReplaceFileW EIO(1175) 根因与处置（重试/WriteAllText/读写顺序/转义教训）；skills 同步一行 |
| 2026-09-04 基座实施 | book-01 第一轮：version.py / runtime_check.py / tests/e2e_smoke.py / consistency_check 扩展 / code-fact-registry.md；修复 project_root 误入残留副本 |
| 2026-09-04 工具盒 | 新增 runs/dev.py（check/sync/commit/docs/test 五子命令），把变更与交付工作流固化为脚本，节省 agent token |
| 2026-09-04 流程固化 | 新增 **变更与交付工作流**（`docs/dev-workflow.md` + `skills/dev-workflow.md`）并纳入 `START-HERE.md §2`；新增 `docs/prompt-taxonomy.md`（10 正 + 9 负）；planbook 更新确认输入 |
| 2026-09-04 计划书 | 新增 `docs/planbook/` 系统性修复计划：痛点→阶段矩阵、基座/可信部署、前端/输出/自动完成/资源隔离/工作流/引擎/风格/验证（book-00…book-10） |
| 2026-09-04 第五批 | 体验/性能/隔离 6 阶段优化：上传三态+状态栏HTML、无效图片拦截(mediacheck)、熔断器(turn_state)、批量提交(h3_batch)、素材隔离(batch_id)、文档预热(doc_state) |
| 2026-09-04 第四批 | tools.py TimeoutExpired bytes/str 拼接修复（两处）、同步 spark 并重启验证、CLI 多轮对话测试通过 |
| 2026-09-04 第三批 | 对话历史丢失修复（hist_state 未更新）、禁用自动 nap、系统提示词自主性重写、上传体验优化、UI 文案简化 |
| 2026-09-04 | 创建。纳入：ctx-8192 溢出修复批次（ctx_budget.py token 预算化）、工作文件夹双端速查（session-summary §14）、Z: 盘禁用规范、阅读索引与同步规则。 |
