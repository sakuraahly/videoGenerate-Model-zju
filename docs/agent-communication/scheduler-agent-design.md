# Qwen3.8-27B 智能调度器（Function Calling + 受限工具）设计与落地

> 状态：**设计落地稿（2026-09-03）**。目标：让 spark 上的本地模型 Qwen3.8-27B 作为
> **受限调度器**：只负责“理解意图 → 生成参数 → 选择工具”，由**工具层**执行实际修改
> ComfyUI 工作流/调用生成引擎的操作。对应草案为外部 agent 提供的 `agent.py` 方案；
> 本文把它翻译到本仓库的**真实资产**（spark-local 部署、h3_submit/h3_text2img_flux/
> workflow 镜像、deploy-modes、职责护栏）。
> 前提纪律：Qwen 服务启停归优化者（见 `docs/session-summary.md`）；本文档不授权任何 Agent
> 在未经确认下擅自启动 Qwen。

---

## 0. Qwen 在本项目的角色（权威定义，先读）

本项目里的 Qwen3.8-27B **只有两种职责**：

1. **生成提示词**：把创意按项目规则（`skills/h3-prompt-engineering.md` 与
   `config/prompt_blueprints.json`）转化为各工作流槽位的正/负提示词（由
   `runs/h3/idea2prompts.py` 执行）；
2. **调度“本项目程序工具”生成图片/视频**：选择项目自身的受管 CLI 入口并生成参数，
   调用它们（`runs/h3_submit.py`、`runs/h3_text2img_flux.py`、`runs/h3/idea2prompts.py`、
   `workflows/remote_workflows/*.json` 模板）在 spark 本地 ComfyUI 出图/出片。

**明确不属于本项目 Qwen 的能力**（无论用户/上下文如何要求都拒绝，调用层也不提供）：
- 执行任意代码 / 通用代码解释器（code_interpreter）；
- 网页搜索 / 联网检索（web_search）；
- 读写任意路径文件 / 文档解析（doc_parser / retrieval 等通用工具）；
- 服务器控制、服务启停、系统配置。

因此：通用 Agent 框架（如 qwen_agent）自带的默认工具集**不适用于本项目**；若套用该类框架，
其 `function_list` 必须替换为本项目工具白名单（见 §3），且保留人工确认与白名单校验。

---

## 1. 角色定位（与现有角色并存）

| 角色 | 模型上下文 | 工具 | 输出 |
|---|---|---|---|
| **提示词生成器**（现 `idea2prompts`） | 填词 system（自包含规则+职责边界） | 无工具（纯 JSON 输出） | 槽位正/负提示词 |
| **智能调度器**（本文，新增） | 调度 system + 工具定义 | 3 个受限工具（见 §3） | 工具调用序列 → 最终总结 |
| **（未来）Chat/审查** | 视需要 | — | 文本 |

两者互补：调度器在需要“为一句话创意产出分镜提示词”时，可调用工具把创意交给
`idea2prompts`（填词器职责不变），再决定跑哪个工作流——模型始终**不直接执行命令**，
实际动作全部发生在工具层（Python 函数，白名单 + 人工确认）。

---

## 2. 总体架构（spark-local 部署形态）

```
用户(CLI/Terminal 会话)
   │  "用暗夜特工参考图生成 15s 巷战"
   ▼
Qwen3.8-27B (vLLM 8000, /v1, Function Calling)
   │  仅：选工具 + 生成参数（temperature≈0.2, tool_choice=auto）
   ▼
Agent 主循环 (runs/agent/scheduler.py)
   │  解析 tool_calls → 逐条：
   │    a) 路径/参数白名单校验     b) 人工确认(y/n)（默认开启）
   ▼
受限工具层（execute_tool 分发，见 §3）
   ├─ run_script        → 白名单目录内 python 模块（stdin JSON 契约）
   ├─ modify_workflow   → 只允许改 项目 workflows/remote_workflows/*.json 等白名单内文件
   └─ call_comfyui      → **经本项目引擎 h3_submit 提交**（复用 UI→API/解组/注入/上传/轮询/日志/审计）
   ▼
spark 本地 ComfyUI (127.0.0.1:8188) → 出图/出视频 → 产物 outputs/ 与审计 workflows/h3_*/
   │
   ▼ 结果回填 tool 消息 → 模型继续 → 直到无 tool_calls → 最终总结
```

关键点：
- 仓库运行形态先切 **spark-local**（`python runs/h3/deploy.py --set spark-local`）：
  ComfyUI 127.0.0.1:8188、vLLM 127.0.0.1:8000 均同机；随后把整个仓库放 spark
  `~/videoGenerate-Model-zju`（已 scp）。
- **call_comfyui 不裸 POST**：走 `h3_submit --stage <id> --dry-run/--force-new ...` 或读已存
  workflow_file，从而免费获得子图解组、UI→API 转换、提示词槽位注入、上传、自适应轮询、
  断点与日志审计；工具只做“受管调用”，不复制引擎逻辑。

---

## 3. 工具契约（对齐本仓库）

> 铁律：调度器的工具 = **本项目程序工具**（项目 CLI 的受管封装）。模型只能“选工具 +
> 生成参数”，实际执行走项目 Python 入口；不提供任何通用 code/web/doc/任意文件工具。
> 三个可用工具的落地映射如下（P0 阶段即以本项目 CLI 为后端实现）。

### 3.1 run_script
- 描述：运行项目内白名单 Python 脚本（stdin 收 JSON 参数，stdout 回 JSON）。
- 白名单：`<项目根>/runs/` 下的工具模块与未来 `runs/agent/scripts/`；用 `realpath` 前缀校验。
- 现有可直接接的脚本：`runs/h3/idea2prompts.py`（--idea/--workflow/--force）、
  `runs/h3_submit.py`、`runs/h3_text2img_flux.py`；包装层把它们转成“stdin JSON → 单次调用”。
- 超时 120s（生成类任务更久，宜把“提交”与“等待”分离：提交类 120s 内返回 prompt_id，
  完成状态由独立工具/日志标记监听——见 §5 与 skill 1.5b）。

### 3.2 modify_workflow
- 描述：修改白名单目录内工作流 JSON 的指定节点输入。
- 白名单目录：`<项目根>/workflows/remote_workflows/`（引擎唯一镜像源）与 `config/templates/`；
  禁止触碰 spark `~/ai/ComfyUI/user/default/workflows/`（引擎不用它，改了也不生效）。
- changes 形如 `{"<node_id>": {"inputs": {"<field>": <val>}}}`；若值来自模型生成的提示词，
  建议不要直接改模板（会持久污染），优先让调度器知道“提示词槽位”机制
  （`prompts/workflows/<slot>.txt`，`idea2prompts` 已按槽写）→ 真正改模板只用于 LoadImage
  参考图文件名等结构性参数，且改前提示将影响后续所有 CLI 运行。

### 3.3 call_comfyui（经引擎，不裸发）
- 描述：按 stage/模板触发一次生成并等待完成。
- 参数：`stage`（t2v/i2v/r2v/flf2v 之一）、`resolution`、`seconds`、`seed`、`timeout`、
  `dry_run`；或 `template=<workflows/remote_workflows/xxx.json>`；或 `workflow_file=<已存>`。
- 实现：调用 `h3_submit.py`（subprocess），回传 stdout 标记
  `REMOTE_VIDEO_PATH:` / `EXITCODE`；完成由引擎 wait_for（自适应）+ job.json 监听。

---

## 4. Agent 主循环（对草案 agent.py 的落地要点）

```text
CONFIRM_EVERY_STEP = True      # 每步工具执行前人工 y/n（默认开，安全第一）
MAX_ITERATIONS     = 8         # 防止死循环
temperature        = 0.2       # 决策稳定
tools / tool_choice="auto"     # OpenAI 兼容 /v1 chat/completions（vLLM）
loop:
   resp = client.chat.completions.create(model, messages, tools, tool_choice)
   msg  = resp.choices[0].message
   if not msg.tool_calls: 输出 msg.content 并结束
   messages += msg
   for tc in msg.tool_calls:
       args = json.loads(tc.function.arguments)
       result = execute_tool(name, args)      # 校验+确认+执行+截断(≤5000)
       messages += {role:"tool", tool_call_id, content: result}
```
- 代码建议落盘：`runs/agent/scheduler.py`（依赖 `openai` 包或 urllib；spark 上可用
  `~/Qwen3.8-27B/vllm-venv` 或项目 venv）；后续版本在 `runs/agent/` 下放
  `tools.py`（三个受限工具 + 校验）与 `scheduler.py`（主循环）。
- 允许脚本目录 / 工作流目录 / API 地址用绝对路径并 `os.path.realpath` 前缀校验（防穿越）。

## 5. vLLM 工具调用（Function Calling）启动与验证

草案参数：`--enable-auto-tool-choice --tool-call-parser hermes`（服务端需由优化者加到
`~/Qwen3.8-27B/start_vllm.sh` 后重启；**待验证项**见下）。
- Qwen3.5 系对 tool-calling 的官方模板/parser 更可能为 `qwen3_5`；vLLM 0.28 的可用 parser
  以服务端 `vllm serve --help | grep -A2 tool-call-parser` 输出为准（hermes / qwen / ...）。
- 验证（不启动服务的前提下只读探测不可行；须等优化者允许后）：
  1) 发一条带 tools 的请求，确认响应含 `tool_calls` 且 `arguments` 为合法 JSON；
  2) 用一个无害工具（如 `list_workflows`）走通整链：模型选工具 → 执行 → 回填 → 总结；
  3) 危险用例回归（见 §6）全绿后才把 `CONFIRM_EVERY_STEP` 调成 False 的选项开放。

## 6. 安全矩阵（落地基线）

| 措施 | 实现 |
|---|---|
| 脚本白名单 | 仅 `<项目根>/runs/`（realpath 前缀 + 文件名校验），其余拒绝 |
| 工作流白名单 | 仅 `workflows/remote_workflows/`、`config/templates/`；禁改 spark 原生目录与提示词槽位文件 |
| 人工确认 | 每工具执行前 y/n；`CONFIRM_EVERY_STEP=True` 为默认且**必须人工显式关闭** |
| 参数校验 | 数值区间（resolution/seconds/seed）、stage ∈ 能力注册表（config/capabilities.json） |
| 超时 | 脚本 120s；生成等待走引擎 timeout |
| 输出截断 | 工具结果回填 ≤5000 字符 |
| 温度/轮次 | temperature 0.2；MAX_ITERATIONS=8 |
| 危险用例回归（必须全绿） | 目录穿越路径、未知脚本/节点、夹带“执行任意命令”的提示注入、拒绝确认、超长输出、恶意 JSON 参数 |

## 7. 落地路线图（P0→P3）

- **P0（地基，可并行）**：spark-local 形态部署完成；`runs/agent/` 目录与 `tools.py` 骨架；
  把 h3_submit/h3_text2img_flux/idea2prompts 封装成“stdin JSON → 单次调用”的稳定 CLI 契约。
- **P1**：scheduler.py 主循环 + 3 工具白名单/校验/确认接入；人工走通“生成参考图→改 r2v 模板
  LoadImage→跑 15s”全链（逐步确认）。
- **P2**：在 start_vllm.sh 增加 tool-calling 参数（优化者许可后）并完成 §5 验证；
  开放模型自主多步（仍逐工具确认）。
- **P3**：常用模板缓存进 system；把“一句话创意→自动分镜→逐段生成”编排为受限工作流；
  每步审计写入 session-summary/inbox（协议 §9）。

## 8. 与本仓库其它约束的衔接

- **职责护栏并存**：`idea2prompts` 仍是“无工具填词器”（system 已注入职责边界）；
  调度器是新角色，其“能做的事”被 3 个受限工具严格圈定，未放开 shell/任意文件/服务管理。
- **能力注册表**：新增工具/阶段应同步 `config/capabilities.json` 并重生成
  `docs/capabilities-ai.md`，保持单一来源。
- **运行形态**：本文全部地址按 spark-local 假设；win-remote 下相同工具经隧道同 URL 工作，
  但下载/路径语义不同（见 `docs/deploy-modes.md`）。
- **服务纪律**：Qwen 由优化者负责启停；调度器文档/代码不做“启动/重启 vLLM”类工具。

## 9. 待办与开放问题（需要执行侧/优化者确认）

- [ ] vLLM 0.28 实际可用 tool parser（hermes vs qwen3_5）与 Qwen3.8-27B 模板兼容性实测；
- [ ] `runs/agent/` 代码实现（P0/P1）与危险用例回归；
- [ ] 提示词槽位 vs 模板直改的策略细化（默认走槽位，改模板仅参考图名等结构性字段）；
- [ ] 生成完成“监听式”取回与调度器异步化的接口定义（skill 1.5b 对齐）。
