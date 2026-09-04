# 流式可行性调研（book-03，2026-09-04，spark 实测）

- **qwen_agent 版本**：0.0.34（spark `~/qwen-agent-venv`）。
- **`Assistant.run()` 返回**：`Iterator[List[Message]]` —— **消息级粒度**（每次 yield 是"一批消息"，不是 token 流）；源码中**无 `stream`**；`generate_cfg`/run 均不暴露逐 token 流。
- **自动语言**：`run()` 检测消息含中文 → `kwargs["lang"]="zh"`（qwen_agent 自动中文倾向，与语言铁律互补）。
- **system 合并逻辑（400 根因相关）**：源码仅在 `messages[0]` 已是 system 时把自身 system_message 合并进 `messages[0]`；**不处理列表中间/多余 system** → 追加 role:system 必定 400（已修）。
- **结论（book-03 实施取舍）**：
  1. **逐 token 流式不可行**（qwen_agent 不暴露；绕开需直连 SGLang SSE — 复杂度高、收益低，列为低优先）。
  2. **可行**：a) 消息级分块渲染（run 的多轮 tool/message yield 逐批展示——需要重构 run_turn/send 以"每批 yield"而非"最后一次性"）；b) 前端打字机（Gradio 无内置动画，需自定义 JS，列为可选）；c) 现有心跳/状态条已持续反馈（处理中 Ns）。
  3. **当前落地**：语言铁律 + 修复 400 + 心跳持续更新；消息级分批展示列为 book-03 增强项（待重构 send/run_turn 后实现）。
