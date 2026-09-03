# 多 Agent 通信协作协议

> 定义多个 AI Agent 之间的通信方式、消息格式和协作流程
>
> ⚠️ **示例与真实区分**：本文所有 JSON/YAML 里的任务内容（如 FlashInfer、NVFP4、
> SGLang、具体脚本路径）**多为示例**。执行前必须以 `docs/session-summary.md` 的
> “当前状态/待办”和实际文件为准（当前真实对象：Qwen3.8-27B vLLM 服务、FlashInfer
> 加速安装中；引擎用 vLLM，不是 SGLang）。

## 目录

1. [概述](#1-概述)
2. [通信架构](#2-通信架构)
3. [消息格式规范](#3-消息格式规范)
4. [协作模式](#4-协作模式)
5. [工作流编排](#5-工作流编排)
6. [状态管理](#6-状态管理)
7. [错误处理](#7-错误处理)
8. [安全约束](#8-安全约束)

---

## 1. 概述

### 设计目标

本协议旨在规范多个 AI Agent（包括代码生成 Agent、审查 Agent、编排 Agent 等）之间的通信和协作方式，确保：

- **可追溯**: 每条消息有明确的发送者、接收者和意图
- **可审查**: Agent 的工作产出可被其他 Agent 审查和验证
- **松耦合**: Agent 之间通过标准化接口通信，可独立替换
- **幂等性**: 重复消息不会导致重复执行

### 适用场景

- 代码生成 → 代码审查 → 修正循环
- 任务分解与子任务分发
- 多 Agent 流水线（Pipeline）协作
- 工作成果交叉验证

---

## 2. 通信架构

### 拓扑结构

```
                    ┌─────────────┐
                    │  Orchestrator│
                    │   Agent     │
                    └──────┬──────┘
                           │
              ┌────────────┼────────────┐
              │            │            │
        ┌─────┴─────┐ ┌───┴───┐ ┌─────┴─────┐
        │  Worker   │ │Worker │ │  Worker   │
        │  Agent A  │ │Agent B│ │  Agent C  │
        └───────────┘ └───────┘ └───────────┘
```

### 角色定义

| 角色 | 职责 | 示例 |
|------|------|------|
| **Orchestrator** | 任务分解、分发、汇总 | 主编排 Agent |
| **Worker** | 执行具体子任务 | 代码生成 Agent、文档 Agent |
| **Reviewer** | 审查工作产出 | 代码审查 Agent、质量检查 Agent |
| **Observer** | 监控和报告 | 日志分析 Agent |

### 通信通道

Agent 之间通过以下方式通信：

| 通道 | 用途 | 格式 |
|------|------|------|
| **文件交换** | 大量数据、代码、文档 | 约定目录结构 + 文件命名 |
| **消息文件** | 结构化指令和反馈 | JSON / Markdown |
| **共享状态** | 任务进度、全局上下文 | 状态文件 (YAML/JSON) |

---

## 3. 消息格式规范

### 任务分发消息

Orchestrator → Worker 的任务指派：

```json
{
  "protocol": "agent-comm/v1",
  "type": "task-assign",
  "id": "task-20260903-001",
  "from": "orchestrator",
  "to": "worker-code-gen",
  "timestamp": "2026-09-03T14:30:00+08:00",
  "priority": "high",
  "payload": {
    "action": "generate-code",
    "description": "实现 FlashInfer SM 12.1 兼容性修复脚本",
    "context": {
      "project": "Qwen3.8-27B on DGX Spark",
      "constraints": [
        "ARM64 架构",
        "CUDA 13.0",
        "SM 12.1 (Blackwell)"
      ],
      "input_files": [
        "shell/spark_install_flashinfer.sh"
      ],
      "expected_output": [
        "shell/spark_install_flashinfer.sh (updated)"
      ]
    },
    "deadline": "2026-09-03T15:00:00+08:00",
    "review_required": true
  }
}
```

### 工作完成消息

Worker → Orchestrator 的结果报告：

```json
{
  "protocol": "agent-comm/v1",
  "type": "task-complete",
  "id": "task-20260903-001",
  "from": "worker-code-gen",
  "to": "orchestrator",
  "timestamp": "2026-09-03T14:55:00+08:00",
  "payload": {
    "status": "completed",
    "summary": "已更新 FlashInfer 安装脚本，添加 SM 12.1 源码编译支持",
    "artifacts": [
      {
        "path": "shell/spark_install_flashinfer.sh",
        "type": "script",
        "changes": "添加 MAX_JOBS=2 和 FLASHINFER_CUDA_ARCHS=12.1 环境变量"
      }
    ],
    "notes": "需要在远程机器上实际执行验证",
    "confidence": 0.85
  }
}
```

### 审查消息

Reviewer → Worker 的审查反馈：

```json
{
  "protocol": "agent-comm/v1",
  "type": "review",
  "id": "review-20260903-001",
  "from": "worker-reviewer",
  "to": "worker-code-gen",
  "timestamp": "2026-09-03T15:10:00+08:00",
  "ref": "task-20260903-001",
  "payload": {
    "verdict": "changes-requested",
    "score": 72,
    "issues": [
      {
        "severity": "major",
        "file": "shell/spark_install_flashinfer.sh",
        "line": 45,
        "description": "源码编译缺少 pip wheel 的缓存清理步骤，可能导致磁盘空间不足",
        "suggestion": "在编译完成后添加 rm -rf /tmp/pip-* 清理临时文件"
      },
      {
        "severity": "minor",
        "file": "shell/spark_install_flashinfer.sh",
        "line": 12,
        "description": "缺少版本号变量定义，硬编码了版本号",
        "suggestion": "提取 FLASHINFER_VERSION 变量便于后续更新"
      }
    ],
    "approved_changes": [
      "SM 12.1 架构指定方式正确",
      "MAX_JOBS 限制合理"
    ]
  }
}
```

### 消息字段说明

| 字段 | 必填 | 类型 | 说明 |
|------|------|------|------|
| `protocol` | 是 | string | 协议版本，固定为 `agent-comm/v1` |
| `type` | 是 | string | 消息类型: task-assign / task-complete / review / status-update |
| `id` | 是 | string | 消息唯一标识 |
| `from` | 是 | string | 发送者 Agent 标识 |
| `to` | 是 | string | 接收者 Agent 标识 |
| `timestamp` | 是 | string | ISO 8601 时间戳 |
| `payload` | 是 | object | 消息内容，结构因 type 而异 |
| `ref` | 否 | string | 关联的任务 ID（审查消息使用） |
| `priority` | 否 | string | 优先级: low / normal / high / critical |

---

## 4. 协作模式

### 模式 A: 生成-审查循环

最常用的协作模式，适用于代码生成和文档编写。

```
Orchestrator          Worker              Reviewer
    │                    │                    │
    │── task-assign ────>│                    │
    │                    │── (执行工作) ──→    │
    │                    │                    │
    │<── task-complete ──│                    │
    │                    │                    │
    │── review-request ──────────────────────>│
    │                    │                    │
    │                    │<── review ─────────│
    │<── review-forward ─│                    │
    │                    │                    │
    │                    │── (修正) ──→       │
    │<── task-complete ──│                    │
    │                    │                    │
    │── review-request ─────────────────────>│
    │                    │<── review (通过) ──│
    │                    │                    │
    │── task-approve ───>│                    │
```

**流程**:

1. Orchestrator 分配任务给 Worker
2. Worker 完成工作，提交结果
3. Orchestrator 将结果转发给 Reviewer
4. Reviewer 审查并返回反馈
5. 若需修改: Worker 根据反馈修正，回到步骤 2
6. 若通过: Orchestrator 确认任务完成

**退出条件**:

- Reviewer 给出 `approved` 判定
- 循环次数超过上限（默认 3 次），Orchestrator 强制决定
- 超时

### 模式 B: 流水线

适用于多步骤顺序任务。

```
Agent A ──→ Agent B ──→ Agent C ──→ 结果
 (步骤1)     (步骤2)     (步骤3)
```

每个 Agent 完成自己的步骤后，将产出传递给下一个 Agent。

**示例**:

1. Agent A: 研究 FlashInfer SM 12.1 问题 → 输出研究报告
2. Agent B: 根据报告编写修复脚本 → 输出脚本文件
3. Agent C: 审查脚本并测试 → 输出测试报告

### 模式 C: 并行扇出-汇聚

适用于可并行的独立子任务。

```
         ┌──→ Worker A ──┐
         │                │
Fan-out ─┼──→ Worker B ──┼─→ Fan-in ──→ 汇总
         │                │
         └──→ Worker C ──┘
```

**示例**:

同时研究三个优化方案:
- Worker A: FlashInfer 修复方案
- Worker B: NVFP4 模型下载方案
- Worker C: SGLang 安装方案

Fan-in Agent 汇总三个方案，生成统一执行计划。

### 模式 D: 交叉审查

适用于高可靠性要求的场景。

```
Worker A ──→ 产出 A ──→ Worker B 审查
Worker B ──→ 产出 B ──→ Worker A 审查
```

两个 Worker 互相审查对方的产出，确保质量。

---

## 5. 工作流编排

### 工作流定义

工作流通过 YAML 文件定义：

```yaml
# workflow.yaml
name: "模型优化部署"
version: "1.0"
steps:
  - id: research
    type: parallel-fanout
    workers:
      - agent: worker-research-a
        task: "研究 FlashInfer SM 12.1 修复方案"
      - agent: worker-research-b
        task: "查找 RadixArk NVFP4 模型下载地址"
      - agent: worker-research-c
        task: "研究 SGLang 在 GB10 上的安装步骤"

  - id: consolidate
    type: fanin
    depends_on: [research]
    agent: orchestrator
    task: "汇总研究结果，制定执行计划"

  - id: execute
    type: pipeline
    depends_on: [consolidate]
    steps:
      - agent: worker-infra
        task: "安装 FlashInfer 修复版"
      - agent: worker-model
        task: "下载 NVFP4 量化模型"
      - agent: worker-engine
        task: "安装 SGLang 引擎"

  - id: review
    type: review
    depends_on: [execute]
    reviewer: worker-reviewer
    criteria:
      - "所有脚本可在远程执行"
      - "文档完整且准确"
      - "无安全漏洞"
```

### 任务状态机

```
                  ┌──────────┐
                  │ pending  │
                  └────┬─────┘
                       │ assign
                  ┌────┴─────┐
            ┌─────│ assigned │─────┐
            │     └──────────┘     │
            │ timeout              │ start
            │                 ┌────┴─────┐
       ┌────┴────┐           │ in_progress│
       │ expired │           └────┬───────┘
       └─────────┘                │
                      ┌───────────┼───────────┐
                      │           │           │
                 submit      fail        cancel
                      │           │           │
                ┌─────┴─────┐ ┌──┴──┐  ┌─────┴────┐
                │ submitted │ │failed│  │ cancelled│
                └─────┬─────┘ └──────┘  └──────────┘
                      │
                 ┌────┼────┐
                 │         │
            approve    request_changes
                 │         │
           ┌─────┴────┐ ┌──┴──────┐
           │ approved │ │ revision│──→ (回到 assigned)
           └──────────┘ └─────────┘
```

---

## 6. 状态管理

### 共享状态文件

所有 Agent 通过共享状态文件协调：

```yaml
# state.yaml
workflow: "模型优化部署"
started_at: "2026-09-03T14:00:00+08:00"
status: in_progress

tasks:
  - id: task-001
    name: "FlashInfer SM 12.1 修复"
    status: in_progress
    assignee: worker-infra
    artifacts:
      - path: "shell/spark_install_flashinfer.sh"
        status: draft
    review:
      status: pending
      reviewer: worker-reviewer

  - id: task-002
    name: "NVFP4 模型下载"
    status: pending
    assignee: worker-model
    blocked_by: [task-001]

  - id: task-003
    name: "SGLang 安装"
    status: pending
    assignee: worker-engine

global_context:
  hardware: "DGX Spark GB10"
  arch: "AArch64"
  cuda: "13.0"
  sm: "12.1"
  comfyui_running: true
  vllm_running: false
```

### 状态更新规则

1. **独占写入**: 每个任务的状态仅由 assignee 或 Orchestrator 更新
2. **追加日志**: Agent 的操作记录追加到 `state.log`，不修改已有记录
3. **原子提交**: 状态文件更新使用 write-rename 模式确保原子性
4. **冲突检测**: 更新前检查文件修改时间，避免覆盖其他 Agent 的更新

---

## 7. 错误处理

### 错误分类

| 级别 | 说明 | 处理方式 |
|------|------|----------|
| `transient` | 临时性错误（网络超时、资源繁忙） | 自动重试，最多 3 次 |
| `recoverable` | 可恢复错误（缺少依赖、配置错误） | 通知 Orchestrator，等待指令 |
| `fatal` | 致命错误（硬件故障、权限不足） | 立即终止，上报 |

### 错误消息格式

```json
{
  "protocol": "agent-comm/v1",
  "type": "error",
  "id": "err-20260903-001",
  "from": "worker-infra",
  "to": "orchestrator",
  "timestamp": "2026-09-03T15:20:00+08:00",
  "ref": "task-20260903-001",
  "payload": {
    "level": "recoverable",
    "code": "DEPENDENCY_MISSING",
    "message": "FlashInfer 源码编译缺少 CUDA toolkit 头文件",
    "context": {
      "command": "pip install flashinfer-python --no-binary :all:",
      "error_output": "fatal error: cuda_runtime.h: No such file or directory"
    },
    "suggested_actions": [
      "安装 CUDA toolkit 开发包",
      "使用预编译 wheel 替代"
    ]
  }
}
```

### 重试策略

```yaml
retry:
  max_attempts: 3
  backoff:
    type: exponential
    initial_delay: 5s
    max_delay: 60s
    multiplier: 2
  retryable_errors:
    - "NETWORK_TIMEOUT"
    - "RESOURCE_BUSY"
    - "TEMPORARY_FAILURE"
```

---

## 8. 安全约束

### Agent 权限边界

| 权限 | 说明 |
|------|------|
| **文件读写** | 仅限工作目录和指定输出目录 |
| **网络访问** | 仅限指定的 API 端点和包管理器 |
| **命令执行** | 白名单制，禁止 `rm -rf /`、`sudo` 等危险操作 |
| **进程管理** | 仅限管理自己启动的进程 |

### 消息验证

- 所有消息必须包含有效的 `from` 标识
- Orchestrator 负责验证 Worker 的身份和权限
- 敏感操作（如删除文件、修改系统配置）需要 Orchestrator 显式授权

### 审计日志

所有 Agent 间通信记录保存在审计日志中：

```
logs/agent-comm/
├── 2026-09-03.jsonl    # 按日期分割的消息日志
├── audit.yaml          # 审计摘要
└── artifacts/          # 工作产出快照
```

---

## 9. 消息文件总线（最小落地约定）

> 补充（2026-09-03 评审后）：协议要真正跑起来，需要约定消息落盘位置与事实源。

- **收件箱目录**：`docs/agent-communication/inbox/`（写方在此落消息，命名沿用
  `msg-<任务id>-<type>.json`；该目录已 gitignore，属暂态）。
- **事实源**：各 Agent 开工/收工扫描 inbox，并把进展/结论写入
  `docs/session-summary.md`（跨 Agent 唯一事实源，含当前状态、待办、服务开关）。
- **审查/决策产物**：需要追溯的评审报告、决策记录直接入库（如本目录的
  `review-and-recommendations.md`），不入 inbox。
- **服务状态纪律**：spark 侧服务（vLLM/ComfyUI/FlashInfer）是否可启动、由谁启动，
  一律以 session-summary 最新记录为准，不擅自启停他人负责的服务。

---

## 10. 分阶段启用（当前生效范围）

> 补充（2026-09-03 评审后）：协议功能清单较长，但并非所有特性都需要立即实现。
> 以下为当前实际启用的子集，其余留待 Agent 数量或编排复杂度上升后再启用。

### 当前已启用（Phase 1）

| 特性 | 说明 |
|------|------|
| **模式 A：生成-审查循环** | Worker 产出 → Reviewer 审查 → 修正/通过 |
| **任务消息 JSON** | `agent-comm/v1` 格式，落 inbox 目录（§9） |
| **审查清单与评分** | collaboration.md 中的代码/文档/脚本清单 + 四级评分 |
| **安全边界** | §8 权限边界、消息验证、审计日志 |
| **消息文件总线** | §9 inbox 目录 + session-summary 事实源 |
| **Qwen-Agent 受限调度器** | `runs/agent/` 三工具（run_script / modify_workflow / call_comfyui） |

### 暂缓启用（Phase 2，条件触发）

| 特性 | 启用条件 |
|------|----------|
| **模式 B/C/D（流水线/扇出/交叉审查）** | Agent 数量 ≥ 3 且有实际多步编排需求 |
| **YAML 工作流状态机（§5）** | 编排复杂度超过线性审查循环时 |
| **共享状态文件 state.yaml（§6）** | 需要跨 Agent 持久化任务进度时 |
| **完整重试策略（§7 retry YAML）** | 出现需要自动重试的可恢复错误时 |

**原则**：先跑通最小闭环（生成 → 审查 → 通过），再按需叠加编排能力。

---

## 附录: Agent 标识规范

| Agent | 标识符 | 职责域 |
|-------|--------|--------|
| 主编排 Agent | `orchestrator` | 任务分解、分发、汇总 |
| 代码生成 Agent | `worker-code-gen` | 编写和修改代码 |
| 基础设施 Agent | `worker-infra` | 环境配置、依赖安装 |
| 模型 Agent | `worker-model` | 模型下载、转换、优化 |
| 引擎 Agent | `worker-engine` | 推理引擎安装和配置 |
| 审查 Agent | `worker-reviewer` | 代码和文档审查 |
| 文档 Agent | `worker-docs` | 文档编写和维护 |

---

*协议版本: agent-comm/v1*
*最后更新: 2026-09-03*
