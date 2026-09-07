# docs/README — 文档地图与治理规则

> **一句话**：现状事实看 `docs/CURRENT-STATE.md`；当日交接看 `docs/handoff-<日期>[-live].md`；
> 本表回答"每个文档是干什么的、还维护吗、以谁为准"。
> **任何新增文档必须先在此表登记**（skills/dev-workflow.md §5 索引同步规则）。

## A. 状态类（当前，必须维护）

| 文档 | 角色 | 权威 |
|---|---|---|
| `docs/CURRENT-STATE.md` | **当前事实唯一权威**（服务/模型/参数/音色/通道/纪律/待办） | 最高；每轮工作结束核对刷新 |
| `docs/handoff-2026-09-07-live.md` | 当日现场交接（问题/修复/实战记录/运维记录） | 当日；跨日后新建当日 handoff |
| `docs/agent-reading/00-04.md` | qwen agent 参考文档（read_doc 工具自动列出） | agent 能力来源；改动=agent 重启生效 |
| `skills/h3-video-generation.md` | 视频生成 skill（端到端） | 操作标准 |
| `skills/h3-postproduction.md` | 成品链 skill（TTS/字幕/混音/ASR/超分） | 操作标准 |
| `skills/h3-prompt-engineering.md` | 提示词 skill | 操作标准 |
| `skills/dev-workflow.md` | 开发交付纪律速查 | 必守 |

## B. 计划/规格类

| 文档 | 角色 |
|---|---|
| `docs/planbook/book-19-execution-ready.md` | S1-S13 执行计划与状态表（**编号含历史轮次、非顺序**；进度以 §1 状态表为准） |
| `docs/code-fact-registry.md` | 代码事实登记（节点 schema/模型 ID/行号级事实） |
| `docs/tts-pipeline-explain.md` | TTS 管道详解（模型/原理/复现，讲解版） |

## C. 操作指南类（手工/参考，按需更新）

`quickstart.md`（快速开始）· `user-guide.md`（操作手册）· `manual-use-6-workflows.md`（6 工作流 GUI）·
`h3-manual-operations.md` / `h3-troubleshooting.md` / `h3-workflow-architecture.md` ·
`workflow-and-prompt.md`（提示词与工作流选择）· `prompt-taxonomy.md`（提示词分类）·
`comfyui-startup-and-access.md`（ComfyUI 启动/访问——**注意：现形态=tmux comfy，见 CURRENT-STATE §2**）·
`deploy-modes.md`（双端模式）· `style-guide.md`（问询纪律/汇报格式）·
`qwen38-deployment.md` / `llm-memory-optimization.md` / `agent-workflow.md` ·
`send-integration-guide.md` / `capabilities-ai.md` / `long-term-maintenance.md` ·
`robustness-and-modularity.md` / `localhost-model/full-manual.md|quick-start.md`

## D. 历史档案（只读；不再更新；现状一律以 A 类为准）

| 文档 | 说明 |
|---|---|
| `session-summary.md` | 2026-09-05 前的状态快照 + 20.x 轮次审计志（审计价值保留） |
| `handoff-2026-09-03.md` / `-04.md` / `-05-continue.md` / `-05-L-tasks.md` / `-06-continue.md` | 各日交接（历史） |
| `pending-tasks-changelog.md`（84KB）/ `pending-tasks-implementation.md`（61KB） | S 系列审计/实现长卷（历史） |
| `reference-2026-09-04.md` / `implementation-status-2026-09-04.md` / `optimization-plan-2026-09-04.md` | 早前状态/计划快照 |
| `docs/test-results/` `docs/agent-communication/` `docs/local-model/` | 测试/通信/本地模型子目录（历史或专题） |

## 治理规则

1. **状态类文档**（A）任何工作结束必须核对；禁止在 C/D 类写"当前事实"。
2. **历史不重写**：D 类只追加注记（"以 CURRENT-STATE 为准"），禁止修订旧结论；翻案请在新日期记录并登记。
3. **同事实多处出现**：以运行代码/CURRENT-STATE 为准，冲突处就地标注。
4. **新增文档**：先登记本表 + `START-HERE.md`/README 引用入口。
5. **handoff 轮换**：新一天开始时，前一日 live 改称 `handoff-<日期>.md`（历史），新建当日 live；CURRENT-STATE 照常维护。
