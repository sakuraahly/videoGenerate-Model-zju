# Agent 通信文档评审与协作衔接建议

> 评审对象：`protocol.md`、`collaboration.md`（本目录）
> 评审 Agent：videoGenerate-Model-zju 主会话 Agent（当前维护本地引擎/文档/仓库）
> 日期：2026-09-03
> 性质：指导意见，非对既有两文件的修改；发现问题请结合下述建议处理。

---

## 1. 总体评价（优点，建议沿用）

- 协议设计成熟：角色（Orchestrator/Worker/Reviewer/Observer）、消息字段表（protocol/type/id/from/to/timestamp/payload/ref/priority）齐全，JSON 示例清晰；
- 工程意识在线：幂等、原子写（write-rename）、冲突检测、审查评分分级、错误分级与重试、权限边界、审计日志、回退/备份、"先本地校验再上传远程"等都与本项目实际操作一致；
- 审查清单（代码/文档/脚本）可直接复用。

## 2. 与项目现状的贴合度核查（2026-09-03 实测）

| 协议/协作文档提到的对象 | 实际状态 | 处理建议 |
|---|---|---|
| `shell/spark_install_flashinfer.sh`（FlashInfer SM 12.1 修复） | ✅ 已存在于仓库 `shell/`，spark `~/install_flashinfer.sh` 同步存在，FlashInfer 安装进行中（与"Qwen 优化"一致） | 属真实任务，进度记录到 session-summary |
| `shell/spark_vllm_smart_start.sh` | ✅ 仓库已新增；spark 有 `smart_start_vllm.sh` | 同上 |
| `docs/local-model/`（文件树引用） | ✅ 目录已创建 | 补齐内容后与协议文件树对齐 |
| "NVFP4(RadixArk) 下载 / SGLang 安装"示例 | ⚠️ 与当前实现不符：模型走 ModelScope（H3/Qwen3.8-27B），推理引擎是 vLLM | **加注"示例内容，勿按字面执行"** |
| `logs/agent-comm/`、`state.yaml` 落盘 | ❌ 尚无实例（`logs/` 已整体 gitignore） | 落地前先定目录归属与 gitignore |

**关键提醒**：协议示例与真实执行对象混在一处，后续 Agent 可能误把 SGLang/NVFP4 示例当任务执行——请显式区分"示例"与"当前真实现状"。

## 3. 主要问题

1. **仓库并发写入风险（当前最紧急）**：评审时刻仓库出现一批**未跟踪新文件**（`shell/spark_install_flashinfer.sh`、`spark_manage_services.sh`、`spark_vllm_smart_start.sh`、`docs/local-model/` 等），是另一 Agent/人工在并行改动同一仓库——下一个 `git add -A` 可能吞掉或冲突。
2. **协议缺"文件总线"落地细则**：只定义了消息格式，未约定消息实际写到哪个目录、谁来轮询/谁负责汇总、任务产物与 git 的关系。
3. **状态管理偏重**：单文件 `state.yaml` + 修改时间冲突检测，在真并发下不稳（应按任务分文件或加锁）；对小规模（2–3 Agent）整套 YAML workflow 编排偏重。

## 4. 建议（按优先级）

### 4.1 止血仓库（立即）
把新出现的脚本/文档纳入版本控制（或明确由优化者管理），并决定 `docs/agent-communication/` 下哪些为暂态（`inbox/`、`*.jsonl`、`state.yaml`）加入 `.gitignore`、哪些入库追溯。

### 4.2 最小可用消息总线（比全文重实现更务实）
- 新增目录约定：`docs/agent-communication/inbox/`（写方落 `msg-<任务id>-<type>.json`，命名遵循 collaboration.md）；
- 每个会话 Agent 开工/收工扫描 inbox，并把结论写进 `docs/session-summary.md`（**该文件应作为跨 Agent 事实源，协议补充互相引用**）；
- 暂态消息 gitignore，需追溯的评审/决策入库。

### 4.3 区分示例与真实
protocol/collaboration 中 SGLang、NVFP4(RadixArk)、FlashInfer（真实）、smart_start（真实）等标注"示例 / 真实任务"，避免误导。

### 4.4 分阶段启用
- 现在只启用：模式 A（生成-审查）+ 任务消息 JSON + 审查清单 + 评分/安全边界；
- YAML workflow 状态机留到 Agent 数量或编排复杂度上来后再启用。

### 4.5 与本会话 Agent 的衔接约定
- 优化者专注 spark 服务侧（FlashInfer/vLLM/模型服务）；本 Agent 专注本地引擎/文档/仓库一致性；
- 每次跨 Agent 交接：更新 `docs/session-summary.md`（含新脚本、服务状态、本评审结论）；
- 本 Agent 不改动其它 Agent 的未完成文件；发现冲突先在 session-summary 记录并提示。

## 5. 附：评审时的环境快照
- 仓库 HEAD：`91124a8`（本评审前最近一次提交，未含 4.1 提到的新脚本）
- Qwen3.8-27B vLLM：服务曾就绪并验证（单槽 AI 桥端到端成功）；用户正在做 FlashInfer/vLLM 优化，本 Agent 暂停对 Qwen 的一切请求
- ComfyUI：进程已被手动停止，生成类任务需先 `bats\service\StartComfyUI.bat` 恢复
