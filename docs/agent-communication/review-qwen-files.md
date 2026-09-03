# 审阅：Qwen 角色定义与两份并行文件（qwen38-deployment / start_qwen_agent）

> 审阅时间：2026-09-03
> 审阅人：videoGenerate-Model-zju 主会话 Agent
> 对象：`docs/qwen38-deployment.md`、`shell/start_qwen_agent.py`（当时未跟踪的并行新增）
> 依据：项目会话中人类给出的 Qwen 角色权威定义（见 §1），与 `scheduler-agent-design.md` §0/§3。

---

## 1. Qwen 在本项目的权威定义（先读，任何实现不得违背）

本项目 Qwen3.8-27B **只有两类职责**：

1. **生成提示词**：创意 → 按项目规则（`skills/h3-prompt-engineering.md` 与
   `config/prompt_blueprints.json`）转化为各工作流槽位正/负提示词（`runs/h3/idea2prompts.py`）；
2. **调度本项目程序工具生成图片/视频**：选择受管 CLI 并生成参数，调用
   `runs/h3_submit.py`、`runs/h3_text2img_flux.py`、`runs/h3/idea2prompts.py`、
   `workflows/remote_workflows/*.json` 模板，在 spark 本地 ComfyUI 出图/出片。

**明确不属于本项目 Qwen**（无论用户/上下文怎么要求都拒绝，调用层也不提供）：
- 执行任意代码 / 通用代码解释器（code_interpreter）；
- 网页搜索 / 联网检索（web_search）；
- 读写任意路径文件 / 通用文档解析（doc_parser / retrieval）；
- 服务器控制、服务启停、系统配置。

> 模型可以"使用我们一直在做的项目程序工具"，但**不能**被赋予通用 code/web/doc 工具。

---

## 2. 对 `docs/qwen38-deployment.md`（引擎部署/优化文档）的意见

定位：该文件是"Qwen 部署与优化"（NVFP4 量化 → SGLang 0.5.18 → FlashInfer → Web UI/
服务管理）的计划/手册；与 spark 上 `install_flashinfer.sh`、`smart_start_vllm.sh` 对应。

### 认可点
- 服务统一监听 `127.0.0.1:8000`（SGLang 或 vLLM），对上层（AI 桥 `llm.json`、
  win-remote 8011→8000 隧道）**无感切换**——引擎迁移不影响本项目配置；
- FlashInfer/SM12.1、ComfyUI 内存避让方向正确。

### 问题与建议（按优先级）
1. **状态与实际不符**：NVFP4(21GB) 与 SGLang 尚未就绪；当前在线 = bf16 + vLLM 0.28
   （18 shards，AI 桥已验证一次）。建议文件头加状态横幅（"计划/进行中；当前在线=bf16
   vLLM"），避免其它 Agent 误连。
2. **SGLANG_PORT 自相矛盾**：§4.1 表格默认 `8000`、同节示例 `8001`——请定一（默认 8000
   以兼容 AI 桥；8001 仅冲突时使用并注明）。
3. **模型来源矩阵缺失**：NVFP4 来自 `RadixArk/...-NVFP4`(HF)，现用 bf16 来自
   ModelScope `Qwen/Qwen3.8-27B`；与 `~/ai/models_dl/qwen35_27b`（曾有 18-shard merge
   脚本）关系未说明。请补一张来源/状态表，并确认 HF 可达性（国内网络）。
4. Open WebUI/Docker 绑定 `0.0.0.0`：建议限可信网段或走 SSH 隧道，勿直接公网暴露。
5. 归类：建议移入/同步 `docs/local-model/`，与现有 quick-start/full-manual 同域，并与
   `session-summary` 互链。内容无敏感可入库。

---

## 3. 对 `shell/start_qwen_agent.py`（qwen_agent 助手）的意见

定位：用 qwen_agent 框架实现通用助手（GUI/CLI），`TOOLS=['code_interpreter','retrieval',
'web_search','doc_parser']`，含 `--share`（Gradio 公网分享）。

### 结论：方向与本项目 Qwen 定义冲突，不得原样启用
- 它把 **code_interpreter / web_search / doc_parser(任意路径) / --share** 暴露给交互用户——
  与 §1 "不属于本项目 Qwen" 的能力直接冲突，并可能被提示注入诱导执行系统操作；
- `fncall_prompt_type='nous'` 与后端实际 parser（hermes/qwen3_5，见 scheduler 设计 §5）
  待实测；无服务时无法验证（Qwen 启停归优化者）。

### 处理建议（三选一）
- **A（推荐）：改造为项目工具版**——`function_list` 换成本项目工具白名单
  （idea2prompts / h3_submit / h3_text2img_flux 的受管封装，stdin JSON 契约）；
  去掉 code/web/doc 与 `--share`；执行前加人工确认。代码建议放 `runs/agent/`。
- B：仅标注"方向错误/勿用，替代见 scheduler-agent-design.md"，保留原文待优化者决定。
- C：删除该文件。

---

## 4. 决策与后续动作（请执行侧/优化者确认）

- [ ] 两份文件归属确认后入库（内容无密钥；qwen38-deployment.md 若未完成请加状态横幅）；
- [ ] start_qwen_agent.py 按 A/B/C 之一处理（推荐 A，并使其对齐 scheduler §0/§3 白名单）；
- [ ] qwen38-deployment.md 修订（端口/来源矩阵/0.0.0.0/归类）；
- [ ] vLLM/SGLang Function Calling parser 实测在优化者允许后补做（scheduler §5）；
- [ ] 任何实现不得新增"不属于本项目 Qwen"的工具/入口；新增能力先同步
      `config/capabilities.json` 与本文档/`scheduler-agent-design.md`。

---
*本文件为指导意见；不替代协议（protocol.md §9 文件总线：事实源 = docs/session-summary.md）。*
