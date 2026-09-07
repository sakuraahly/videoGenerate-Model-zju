# docs/README — 文档地图与治理规则

> **一句话**：现状事实看 `docs/CURRENT-STATE.md`；当日交接看 `docs/handoff/handoff-<日期>[-live].md`；
> 本表回答"每个文档是干什么的、还维护吗、以谁为准"。
> **任何新增文档必须先在此表登记**（skills/dev-workflow.md §5 索引同步规则）。

## 目录结构（2026-09-07 归并）

```
docs/
├── README.md                 本地图（入口）
├── CURRENT-STATE.md          当前事实唯一权威（🌱 状态）
├── guides/                   操作指南与参考（生成/成品链/提示词/运维/讲解）
│   ├── dev-workflow.md              变更与交付工作流（完整版）
│   ├── tts-pipeline-explain.md      TTS 管道详解（讲解版）
│   ├── code-fact-registry.md        代码事实登记表
│   ├── capabilities-ai.md           能力注册表文档（capabilities.py --doc 生成）
│   └── quickstart / user-guide / manual-use-6-workflows / h3-manual-operations /
│       h3-troubleshooting / h3-workflow-architecture / workflow-and-prompt /
│       prompt-taxonomy / style-guide / comfyui-startup-and-access / deploy-modes /
│       llm-memory-optimization / qwen38-deployment / long-term-maintenance /
│       robustness-and-modularity / agent-workflow / send-integration-guide
├── handoff/                  各日现场交接（handoff-<日期>.md；跨日新建，旧日归档）
├── history/                  历史档案（只读）
│   ├── session-summary.md           2026-09-05 前状态快照 + 20.x 轮次审计志
│   ├── reference-2026-09-04.md / implementation-status-2026-09-04.md / optimization-plan-2026-09-04.md
│   └── pending-tasks-changelog.md / pending-tasks-implementation.md   （S 系列审计/实现长卷）
├── planbook/                计划书（book-00..19；进度看 book-19 §1 状态表）
├── agent-reading/           qwen agent 参考文档（read_doc 自动列出；改后 agent 重启生效）
├── agent-communication/     评审/协议/协作记录
├── local-model/             本地模型专题
└── test-results/            测试结果
```

## 治理规则

1. **状态类文档**（CURRENT-STATE + 当日 handoff）任何工作结束必须核对；禁止在 guides/history 写"当前事实"。
2. **历史不重写**：history/ 只读，只允许追加注记（"以 CURRENT-STATE 为准"）；旧结论翻案=新建日期记录。
3. **同事实多处出现**：以运行代码/CURRENT-STATE 为准，冲突处就地标注。
4. **新增文档**：先登记本表 + `START-HERE.md` §2 + `README.md` 文档表。
5. **handoff 轮换**：新一天开始时，前日 live 归档为 `docs/handoff/handoff-<日期>.md`，新建当日 live。
6. **agent 能力**：只经 `docs/agent-reading/`（04-tts-pipeline 等）；其余文档 agent 按需 read_doc 读取。