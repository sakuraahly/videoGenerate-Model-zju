# 阶段 14 — 复读故障根因排查与根治（book-16）

> 状态：待实验（只取证、未修复。用户指示：先写清楚再动手）
> 日期：2026-09-05 · 触发：用户真实测试复现「输出复读/逐步递增重复」，并怀疑"流式输出模块让 AI 变这样"。

---

## 1. 取证（已做，只读）

**会话** 20260905_050131_d2a2（spark logs/agent_chats/）：
- user(58 字, 任务描述) → **assistant#1(412 字) 首块即复读**（"用户用户要求：用户要求：- 主题：用户要求：…"）→ [执行出错：防复读拦截] → 用户"继续" → assistant#2(312 字) 同样复读 → 拦截。
- **llm_input_preview（run log）**：05:33:40 send **msgs=1 roles=[user:58]** ——**输入干净**（无重复消息、无历史污染）。
- 对照：05:28 同一 SGLang 进程"你好"→ 正常长回复（74 chunks/13k 字符**但内容正常**，此前误判——正常对话才会这么长）。

**推论**：
1. **"流式输出模块导致 AI 复读"不成立**：输入无重复、消息结构正常、流式只是把模型输出的复读逐块显示（观感放大）。C1 已加的三层防护正确地在**展示层**拦截（每 3 块即停）——但**没有阻止生成继续烧 GPU**（防护在 send 侧，模型后台仍跑完）。
2. **根因在生成侧，且与"输入规模/内容"相关**：长中文任务 → 复读；短句（你好）→ 正常。候选机制（按嫌疑排序）：
   - **A. 投机解码 NEXTN 缺陷**：`--speculative-algorithm NEXTN --speculative-num-steps 3`（start_sglang_coexist.sh）在长序列/draft 分支下可能产生重复 token（SGLang 已知风险类）；"你好"短（draft 少）不触发，长任务触发——与观察吻合。
   - **B. 生成参数缺去重惩罚**：qwen_agent LLM_CFG.generate_cfg 无 repetition_penalty/frequency_penalty；长回复模型自身复读倾向（27B 中文长输出常见）。
   - **C. SGLang 服务随上下文/会话退化**（KV cache/Radix 状态病）——但"你好"与任务仅隔 5 分钟、同进程，若服务退化短句也该坏；倾向弱。
   - **D. qwen_agent 消息级 yield 的迭代器在 tools 循环里把响应重复 append**（框架 bug 类）——可被 A/B 判据区分（若工具调用轮复读 vs 纯文本轮复读）。

## 1.5 用户真实测试三问题归因（2026-09-05 第二轮）
- **素材池「只有一个」**：取证=数据/列表正常（log.jsonl 2 行带 cid；`refimage list --session` 实测 2 项）。根因=**上传提示文案误导**（dup 上传提示「⏩ 1 个素材已在本会话池中」只描述本批次）+ 复读吞掉了 list 正常输出。**修复**：上传提示含「本会话素材池现有 N 项」；文案与 _err_hint 中文案同步。
- **输出依旧错误（复读）**：见 §2 实验；**已获用户授权，按风险最小顺序执行 E2 → E1**。
- **大量错误日志**：取证=`~/agent.log` 今日 0 Traceback/0 ReadTimeout（已按天轮转）；run log 错误行 1/3 —— 日志本身干净；感知来自「复读+ReadTimeout+[执行出错]」在 UI 反复。修复：ReadTimeout/timed out 归入 _err_hint 可读文案；复用 book-11 防垃圾（事件化已经在）。

## 2. A/B 受控实验（2026-09-05 用户授权执行；每项一次独立短会话，禁止手工修补）

| 实验 | 改动（spark 临时，不动 Windows 默认） | 假设判定 |
|---|---|---|
| E1 | 关投机：`--no-speculative?（脚本加 SGLANG_SPEC=off 或手动去掉 NEXTN 参数重启 SGLang）` | 若复读消失 → 假设 A 成立 → 默认去掉/改造投机（性能代价量化后保留取舍：+30% 速度 vs 稳定） |
| E2 | 加惩罚：qwen_agent generate_cfg `repetition_penalty 1.08 / frequency_penalty 0.08`（仅 LLM_CFG 增字段） | 若改善 → 假设 B 确认（推荐参数化，中等收益） |
| E3 | E1+E2 同开，跑 10 次长中文任务 | 统计复读率（预期 0） |
| E4 | 仅复现（不改）跑 3 次 → 量化基线复读率 | 对照 |

每步用**项目程序**：run_turn 驱动 + 事件流统计（chunk 数/总字符/是否 done）+ 会话档存档；结果写回本册。

## 2.5 最终定位（2026-09-05 深夜，抓包+二分探针全链路）
- **服务端任何单请求组合全部 200 正常**（system 2945/8232/截断、token 256/512/800、penalty、nous、stream、seed）——SGLang 与模型无罪；
- **qwen_agent 0.0.34 完整链必然复读**（nous 开/关、128→146 次 LLM 重调、每轮 300-800 token 重新生成相同开头）；
- **真凶：qwen_agent 0.0.34 的 function-call 循环协议与 SGLang 不合**——模型自然文本回复（无 tool_calls）被框架误判为“未完成工具调用”→ 反复重调 LLM → 累计膨胀=肉眼“复读/死循环”（**用户最初的“内容追加导致重复”直觉方向正确**；此前“模型复读/服务端污染”判断回退纠正）。
- 已落地（本批）：① **增量差分解码**（qwen_agent 流式 yield 为累计体而非增量→取 len 前缀差；防“TheThe user wants”型渲染重复）；② REPLY_MAX_TOKENS 2048→800（256/512 全正常且快）；③ 上传提示含池总数；④ ReadTimeout/_err_hint 分类；⑤ 参考 audit。
- **根治（拟）**：夺回循环控制——弃用 qwen_agent Assistant.run() 自动工具循环，改 `bot.chat(messages)`（服务端单发，已验证 13s/822 正常）+ **自管工具循环**（解析回复→调工具→追加→再 chat，上限 6 轮、逐轮审计日志、复读即断）；预计改动 ui_app.run_turn + tools 调用面；需回归：工具实际调用（list_references/call_comfyui）端到端。

## 3. 修复方向（实验后定）
- 若 A：`start_sglang_coexist.sh` 投机默认关闭或降为 1 步；性能评估（TTFT/tok/s 对照）进 llm-memory-optimization.md。
- 若 B：LLM_CFG 增加惩罚（可配置 `config/llm.json?`——LLM_CFG 在代码，改为读 config 覆盖项，默认开启去重惩罚）。
- **防御升级（无论结果）**：① 防复读拦截从"展示层"提升到**生成层**：run_turn 检测到连续重复块（计数达阈值）→ 主动 `events.put('abort')`+**中断本轮**（qwen_agent 无法中途停模型，但可停止后续轮次/自动续接，避免继续烧 GPU与继续污染）；② MAX_AUTO_CONTINUE 出错后不再自动续（已是）；③ 出错文案指引"新开对话"（模型会话隔离）。
- 回归测试：把「长中文任务×10 → 复读率 0」固化为 `tests/e2e_anti_echo.py`（冒烟门禁候选）。

## 4. 与其它册
- book-13 P0（输出异常保护已做展示层；本册补生成层）；book-15（服务编排：E1 需要改 sglang 启动参数，经 memory_planner 管理）；book-01（基线：复读率作为稳定性指标）。

## 5. 根治完成记录（2026-09-05）
- **补丁（同日）**：① qwen 工具参数支持**裸 KV**（`stage=t2v, seconds=5, dry_run=true`——模型实际输出此格式而非 JSON；`_parse_tool_args` 兼容 JSON/KV/围栏，run log 实锤 dry-run 预览未提交）；② 上传预览**按会话隔离**（`_gal_by_cid`，堵“新会话混显上一会话预览”）；③ **空转提前停**（连续两轮输出前缀重复→停+提示）；④ 工具审计 jsonl 为排查提供“调用是否真实发生”证据。
- **✅ 已实施并全链路验证**：① 自管工具循环（_one_run 重写：≤6 轮、增量解码、超限即断、每轮审计）；② 直连 SGLang 用 **tools= 格式**（关键：只有 tools= 触发 qwen3.8 的 <tool_call><function=..> 标签；functions= 不触发）；③ 新增 runs/agent/toolcall_parse.py；④ 工具结果 user 视角回填（规避 tools 模式 function/tool role 400）；⑤ SYSTEM_MESSAGE 增“工具执行铁律”；⑥ 真实 run_turn 验证：A 问候 done / B 素材链 done（list_references→回填→中文收尾 3883 字）/ C 5 工具连锁 done；无复读、无 146 次循环；单测 152 全绿。
