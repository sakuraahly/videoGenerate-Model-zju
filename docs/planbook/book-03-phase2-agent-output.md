# 阶段 2 — Agent 输出行为与语言（中文 / 流式 / 分块）

> 状态：计划(未实施) | 目标：回复**中文**、**分块/打字机**式出现，而不是"一次性暴长英文 + 干等" |
> 主负责人：Agent/前端 | 依赖：book-01(确认版本)、book-02(前端渲染) | 对后端影响：低 | 优先级：🔴 高

---


---

## 0. 阻塞性发现（2026-09-04 实机复现 —— 必须先修）

- **现象**：book-02 界面验证后，发送"你好"即返回：`[执行出错] ModelServiceError: Error code: 400. Error message: The input messages must contain no more than one system message. And the system message, if exists, must be the first message.`
- **根因**：`runs/agent/ui_app.py:606` 自动续接向 `messages` 追加 `{"role": "system", "content": "[系统自动续接] 请继续完成当前任务。"}`；qwen_agent 每次调用会再注入自己的 `system_message` → 对话中出现两条 system 消息（且续接那条不在首位）→ SGLang 400。触发条件＝agent 回复纯文本（无工具调用），如"你好"的寒暄回复后 `needs_continuation` 判定成立 → 续接循环 → 400。
- **修复**：① 续接提示改为 `{"role": "user", "content": "[系统自动续接] 请继续完成当前任务。"}`（语义上仍被模型视为"继续"指令，且不违反单 system 约束）；② `_err_hint` 增加"one system message"类 400 的正确建议（并把 ModelServiceError/400 从"上下文超限"分类中拆出，避免误导）。
- **归属**：机制属 book-04（自动续接）；因阻塞基本使用且用户点名本册先行，故在 book-03 先修（book-04 同步参考此根因）。
- **验证**：spark 上跑"你好"回归（`tests/regress_auto_continue_round.py` 或真实 UI 发送），并跑 `e2e_smoke`（含 UI /config 实况）。


## 1. 问题背景（用户可见现象）
- "agent 的输出不是流式输出，而是一次性全部输出然后等待用户输入。"
- "并且主要是英文，需要强制为输出为中文（但是英文原文如代码等就保留）。"

---

## 2. 根因分析

### 2.1 语言为何是英文
- `runs/agent/scheduler.py` 的 `SYSTEM_MESSAGE` 已在末尾写了"请用中文回答"，输出纪律也写了"中文回复，精炼（≤600字）"。
- 但同一系统提示里**大量指令本身就是英文语境**："生成详细英文提示词"、`prompt` / `resolution` / `seconds` / `TASK_SUBMITTED` / `LOCAL_OUTPUT` 等技术词、以及 `skills/h3-prompt-engineering.md` 通篇英文样例。
- 模型在"工程执行"语境下更容易切到英文；且 `04-agent-workflow.md` 的输出纪律说"中文 ≤600 字"，但工具返回（脚本 stdout/stderr、JSON）本就是英文，模型常直接引用。
- → 指令不一致/优先级不清，导致模型把"回复"也写成英文。

### 2.2 为何非流式（一次性）
- `scheduler.py run_cli`：`for chunk in bot.run(messages): response = chunk` —— 循环体把 `chunk` 整个覆盖给 `response`，取其 `content` 一次性打印。这里其实按"轮次"而非"token"取 chunk。
- `ui_app.py`：`run_turn()` 何时如何消费 `bot.run()` 的 chunk，决定前端是否能看到中间态。
- `qwen_agent` 的 `Assistant.run()` 是生成器，但**每个 yield 通常是一整条消息/一整段内容**（按工具调用/消息边界），而非逐 token；Gradio `Chatbot` 组件默认需要特殊配置才能做到打字机流式。
- `ctx_budget` 又因 ctx=8192 限制要求"精炼 ≤600 字"，进一步强化了"一次性给完整小回复"的形态。
- → "非流式"是**消费方式**（把 yield 当"最后结果"）+ **渲染方式**（Gradio 一次性渲染）+ **qwen_agent 的 chunk 粒度**（非逐 token）共同导致。

---

## 3. 目标与范围

**目标**：让用户看到"逐段/逐块"出现的中文回复；强制中文（保留英文原文：代码、提示词、技术名词、工具标记行）。

**做**：
- 强化 `SYSTEM_MESSAGE` 的中文强制指令（明确"除了代码/提示词/技术名词/工具标记行，一切面向用户的文字一律中文"）。
- 在 `skills` 与 `agent-reading/04` 中同步该口径。
- 实现"分块呈现"：前端打字机效果或按 `bot.run()` 的 yield 逐步更新（若 qwen_agent 粒度粗，则用打字机平滑）。
- 探索 qwen_agent/后端是否可逐 token stream（若能则优先）。
- 若无法逐 token，则降低"等待感"：显示中间状态/占位提示。

**不做**：不改生成语义/不改 ctx 硬顶；不破坏"提示词必须英文"的规则（提示词仍英文，但**向用户解释/汇报**用中文）。

---

## 4. 改动点清单（拟议）

| 文件 | 拟改内容 | 目的 |
|---|---|---|
| `runs/agent/scheduler.py` | `SYSTEM_MESSAGE` 新增/强化"语言铁律"：明确仅"代码/提示词/技术名词/工具标记行"用英文，其余一律简体中文；给出"中英对照"示例 | 强制中文 |
| `runs/agent/scheduler.py` | 增加 `stream` 相关配置调研位（如 `generate_cfg` 是否有 stream、`bot.run` 是否有 `stream` 参数）；记录实际行为 | 明确流式可行性 |
| `runs/agent/ui_app.py` | `run_turn()` 改为**逐 chunk 更新**消息（若支持）或在前端打字机渲染；收集 `bot.run()` 的中间 yield | 分块呈现 |
| `runs/agent/ui_app.py` | 增加一个轻量"语言自检"提示：若检测到整段为英文，追加一行"（注：已按需转为中文，代码/提示词保留英文）" | 兜底 |
| `docs/agent-reading/02-prompt-rules.md`、`04-agent-workflow.md` | 明确"回复=中文；提示词=英文"的边界 | 口径一致 |
| `skills/h3-video-generation.md` | 在输出纪律处补"面向用户一律中文（技术名词除外）" | 口径一致 |

> 说明：以上为拟议；**强规则以 SYSTEM_MESSAGE 为前提，前端渲染以打字机为主**（最稳、不依赖后端逐 token 能力）。

---

## 5. 实施步骤

### 步骤 1：写强语言规则进 SYSTEM_MESSAGE
- 在 `SYSTEM_MESSAGE` 末尾新增一节（优先级最高），如："**语言铁律**：除①代码片段②生成提示词本体③工具标记行（TASK_SUBMITTED/REMOTE_VIDEO_PATH/LOCAL_OUTPUT/退出码）④技术名词（ComfyUI/分辨率/阶段名）外，一切面向用户的话一律使用简体中文。向用户解释、汇报、提问、总结都必须中文。示例：不要回复 'submitted successfully'，应回复 '已提交成功。'"
- 同步到 `agent-reading` 与 `skills`。

### 步骤 2：落实分块/打字机渲染
- 先在 `ui_app.py` 收到 `bot.run()` 的每个 yield 后，把内容**增量**追加到当前 assistant 气泡（若 Gradio 支持）或保留每个 token 状态用于前端打字机。
- 若 qwen_agent 只能整体 yield：实现**前端打字机**（一次拿到全文，但界面逐字/逐句显示），立刻消除"一次性暴长"观感，且不改后端。

### 步骤 3：调研后端逐 token 流式（可选，不影响交付）
- 查询 qwen_agent `Assistant`/`LLM` 是否暴露 stream；是否可 `generate_cfg` 加 `stream=true`；SGLang 是否支持 SSE。记录结论到 `docs/test-results/`。

### 步骤 4：验证语言与流式
- 跑一轮真实对话，断言：回复为中文；代码/提示词/工具行仍英文；呈现为分块（而非一次暴长）。

---

## 6. 验收标准

- [x]（先确认）`SYSTEM_MESSAGE` 含明确中文铁律，且 `agent-reading`/`skills` 同步。
- [ ] 真实对话中，agent 面向用户的说明/汇报/提问为**简体中文**；代码/提示词/`TASK_SUBMITTED` 等仍英文。
- [ ] 回复**逐块/逐字**出现（打字机 or 增量），不再"一次性全部冒出"。
- [ ] 不因改动破坏"提示词必须英文"的生成规则（生成的提示词仍英文）。

---

## 7. 风险与回滚
- **风险：过度约束中文导致提示词被中文化**——用"生成提示词本体除外"明确豁免；验证时检查提示词仍英文。
- **风险：打字机若实现不当造成重复/乱序**——用"状态刷新只追加、不替换"保证顺序；回滚=改回一次性渲染。
- **回滚**：前端打字机独立于后端逻辑，可一键关闭；语言规则是提示词层面，可回退 SYSTEM_MESSAGE。

---

## 8. 与其它册/红线的关系
- 依赖 book-02（前端渲染管道）承载打字机；与 book-08（风格/系统提示词）融合，本书定"语言/流式"，book-08 定"风格/完成导向"。
- 红线：不改提示词生成语义（仍英文）；不改 ctx 硬顶。

---

## 9. 待用户输入 / 待定项
- "流式"期望到哪种粒度：逐 token / 逐句 / 打字机即可 → 建议先满足"逐块+打字机"，逐 token 作为增强。
- 是否接受"生成提示词本体仍英文"作为语言铁律的豁免（用户已明确"英文原文如代码等保留"，提示词属此类）。

---

## 10. 实施记录（2026-09-04 第一批，book-03）

- ✅ **阻塞修复（§0）**：ui_app.py:606 自动续接 追加 role:user（原 role:system → SGLang 400）。spark 回归：tests/regress_auto_continue_round.py 两轮通过 REGRESS_OK（round1 你好，round2 续接），无 one-system-message 400；round1 输出为中文。
- ✅ **错误分类修正**：_err_hint 增加 "one system message / system message" 分支（正确建议"已修复为 user 角色"）；把 ModelServiceError/400 从"上下文超限"拆分为独立"接口 400"提示。
- ✅ **语言铁律**：scheduler SYSTEM_MESSAGE 新增"语言铁律（优先级最高）"：面向用户一律简体中文；仅 ①代码/命令 ②英文提示词本体 ③工具标记行 ④技术名词 豁免；并给正反例。同步 agent-reading/02（提示词=英文、回复=中文）、04 §5、skills §1.3c。
- ✅ **流式可行性调研**（docs/test-results/streaming-findings.md）：qwen_agent 0.0.34 仅消息级粒度、无 stream；逐 token 流式需直连 SGLang SSE（低优先）；可行路径＝消息级分批渲染（待重构 send/run_turn，列为增强）+ 心跳持续反馈。
- ⏳ 增强（未做，列入本册待办）：消息级分批渲染（逐批 yield 而非最后一次性）；打字机（需自定义前端 JS）。
- ⚠️ 观察：round2 对续接消息的**内部**思考输出可能含英文（模型对"[系统自动续接]"消息的转述）；用户可见回复以中文为准，风格问题由 book-08 继续收紧。
- 📌 **UX 缺口记录（2026-09-04 实测：两图转场）**：提交后等待期（<40 分钟）界面只有"任务排队中"，**对话里无任何新输出**——设计上"提交类动作成功即结束本轮"（回报在后），用户感知为"空转"。待办：①消息级分批渲染（逐批 yield，见 §10 增强）；②监控通知更丰富（阶段+已耗时+预计）；③提交时提示"后台执行中，可用【取片】查询，预计 X 分钟"。
