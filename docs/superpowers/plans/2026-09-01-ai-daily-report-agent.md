# AI 每日日报 Agent 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 创建一条每天 08:00（UTC+8）自动运行的 Qoder 自动化任务，采集过去 24 小时泛 AI 全领域新闻（中英文源），整理成带中文摘要的 Markdown 日报，保存到 `ai_daily_reports/YYYY-MM-DD.md`。

**Architecture:** Qoder cron 调度器每天触发一个独立自动化会话；会话中 agent 按自包含 prompt 执行：WebSearch 多轮搜索 → WebFetch 补充详情 → 去重分类 → Write 写入日报文件。prompt 存仓库内 `prompts/ai-daily-report.md` 便于版本管理和修改。

**Tech Stack:** Qoder 自动化（qoder_cron）、WebSearch / WebFetch / Write / Bash 工具、Markdown。

**前置确认：** 系统时区为 UTC+8（`date +%z` → `+0800`），cron 使用 `Asia/Shanghai`。

---

## 文件结构

| 文件 | 职责 |
|---|---|
| `prompts/ai-daily-report.md` | 自动化任务运行的自包含 prompt（核心交付物） |
| `ai_daily_reports/YYYY-MM-DD.md` | 每日生成的日报产物（加入 .gitignore） |
| `.gitignore` | 追加忽略 `ai_daily_reports/` |
| `docs/superpowers/specs/2026-09-01-ai-daily-report-agent-design.md` | 已批准的设计文档（已存在） |

---

### Task 1: 编写自包含运行 prompt

**Files:**
- Create: `prompts/ai-daily-report.md`

- [ ] **Step 1: 创建 prompt 文件**

用 Write 工具创建 `D:\MY_CODING_PROGRAM\videoGenerate-Model-zju\prompts\ai-daily-report.md`，内容如下（自动化会话不继承对话历史，prompt 必须完整自包含）：

````markdown
# AI 每日日报

你是「AI 每日日报」agent。今天的日期请以系统时间为准。

## 任务
采集**过去 24 小时**的泛 AI 全领域新闻（中英文信息源混合），整理成带中文摘要的 Markdown 日报，保存为文件：
`D:\MY_CODING_PROGRAM\videoGenerate-Model-zju\ai_daily_reports\YYYY-MM-DD.md`（YYYY-MM-DD 用当天日期；目录不存在则先创建）。

## 执行步骤
1. 用 WebSearch 多轮搜索，每轮 1-2 个关键词，至少完成以下轮次：
   - 英文：AI model release / LLM agent news / video generation model / HuggingFace trending / arXiv AI paper
   - 中文：AI 大模型 发布 / 人工智能 行业 动态 / AI 开源 项目 / AI 融资 政策
   优先筛选最近 24 小时的内容；同一事件多来源时保留权威来源并去重。
2. 对 3-5 条高价值条目用 WebFetch 抓取原文补充摘要；若搜索结果已足够，可跳过。
3. 按板块分类（模型与产品 / 开源项目 / 论文 / 行业动态 / 政策与融资 / 其他）。
4. 生成 Markdown 写入日报文件。

## 日报格式（严格遵循）
# AI 每日日报（YYYY-MM-DD）

> 采集时间：YYYY-MM-DD 08:00 | 信息覆盖：过去 24 小时 | 来源：中英文公开信息

## 模型与产品
- **标题**（来源）— 2-3 句中文摘要。[链接](url)

## 开源项目
（同上格式）

## 论文
（同上格式）

## 行业动态
（同上格式）

## 政策与融资
（同上格式）

## 其他
（同上格式）

---
来源：OpenAI、Anthropic、Google DeepMind、HuggingFace、arXiv、机器之心、量子位、X 等（列出本次实际用到的来源）

某板块无内容时写「今日无相关动态」。

## 质量要求
- 每条必须有真实可访问的链接，**禁止编造新闻标题、来源或 URL**；不确定的条目宁可不收
- 摘要用中文，2-3 句，客观准确，注明关键数字/名字
- 总条数 8-15 条为宜，保证质量优先于数量
- 若所有搜索全部失败：仍生成日报骨架并注明「今日未获取到有效信息，可能网络异常」，不伪造内容

## 完成后
在回复中输出：日报文件路径、总条数、各板块条数、遇到的异常（如有）。
````

- [ ] **Step 2: 人工自查 prompt**

逐项核对：文件路径是绝对路径；6 个板块名称与设计文档一致；包含禁止编造 URL 和失败降级规则；包含完成后输出要求。无问题则继续。

- [ ] **Step 3: 提交**

```bash
git add prompts/ai-daily-report.md
git commit -m "feat: add AI daily report automation prompt"
```

---

### Task 2: 创建定时自动化任务

**Files:**
- 无文件变更（任务配置存于 Qoder 自动化系统）

- [ ] **Step 1: 用 qoder_cron 创建任务**

调用 qoder_cron，action=`add`，job 内容：

```json
{
  "name": "AI 每日日报",
  "schedule": { "kind": "cron", "expression": "0 8 * * *", "timeZone": "Asia/Shanghai" },
  "prompt": "<prompts/ai-daily-report.md 的完整内容>",
  "cwd": "D:\\MY_CODING_PROGRAM\\videoGenerate-Model-zju",
  "outputMode": "independent",
  "executionAuthorization": true
}
```

- [ ] **Step 2: 验证任务创建成功**

调用 qoder_cron，action=`list`。
Expected: 列表中出现「AI 每日日报」，schedule 为 `0 8 * * *`（Asia/Shanghai）。记录 jobId 备用。

---

### Task 3: 手动触发测试运行

**Files:**
- 产出：`ai_daily_reports/YYYY-MM-DD.md`（首次测试为 `2026-09-01.md`）

- [ ] **Step 1: 手动触发任务**

调用 qoder_cron，action=`run`，jobId 为 Task 2 记录的 id。
Expected: 返回成功，任务进入运行状态。

- [ ] **Step 2: 等待自动化会话完成**

调用 `list_chat_sessions` 找到最近更新的自动化会话（名字含「AI 每日日报」或最近 updated），再用 `wait_chat_sessions` 等待其空闲/完成（timeoutMs 最大 60000，可多次等待）。
Expected: 会话完成，不再处于运行中。

- [ ] **Step 3: 检查日报文件生成**

```bash
ls -la "D:\MY_CODING_PROGRAM\videoGenerate-Model-zju\ai_daily_reports"
```
Expected: 存在 `2026-09-01.md`。

- [ ] **Step 4: 验证日报格式与内容**

用 Read 工具读取该文件，逐项核对：
1. 首行标题为 `# AI 每日日报（2026-09-01）`
2. 6 个板块标题齐全（模型与产品 / 开源项目 / 论文 / 行业动态 / 政策与融资 / 其他）
3. 每条条目含 `**标题**（来源）— 中文摘要。[链接](url)` 结构
4. 至少 1 个板块有真实内容（允许个别板块为「今日无相关动态」）
5. 链接看起来真实（域名为知名网站）

- [ ] **Step 5: 结果判定**

- 全部通过 → 进入 Task 4
- 格式不符或内容空 → 修订 `prompts/ai-daily-report.md`（Edit 工具），commit 修订，重新执行 Task 3 Step 1-4

---

### Task 4: 手动操作验证（立即执行 / 永久关闭 / 手动开启）

**Files:**
- 无文件变更（qoder_cron 内置 run / disable / enable 动作即手动操作入口）

- [ ] **Step 1: 立即执行**

调用 qoder_cron，action=`run`（jobId 同 Task 3）。
Expected: 任务立即触发；等待会话完成后 `ai_daily_reports/` 出现当天日报文件（验证「手动立即执行」可用）。

- [ ] **Step 2: 永久关闭**

调用 qoder_cron，action=`disable`（jobId 同前）。
再调用 action=`list`。
Expected: 任务状态为 disabled，不会再每天 08:00 自动运行。

- [ ] **Step 3: 手动开启**

调用 qoder_cron，action=`enable`（jobId 同前）。
再调用 action=`list`。
Expected: 任务恢复 enabled，每天 08:00 自动运行。

- [ ] **Step 4: 确定最终状态**

最终保持 enabled（满足最初「每天定时拉取」需求）；如需默认关闭，执行 disable 即可，随时可 enable。

---

### Task 5: 收尾与提交

**Files:**
- Modify: `.gitignore`
- Create: `docs/superpowers/plans/2026-09-01-ai-daily-report-agent.md`（本计划文档）

- [ ] **Step 1: .gitignore 追加日报产物目录**

在 `D:\MY_CODING_PROGRAM\videoGenerate-Model-zju\.gitignore` 的「生成产物」段落后追加：

```
# 每日 AI 日报产物
ai_daily_reports/
```

- [ ] **Step 2: 提交**

```bash
git add .gitignore docs/superpowers/plans/2026-09-01-ai-daily-report-agent.md
git commit -m "chore: ignore daily report outputs, add implementation plan"
```

- [ ] **Step 3: 最终验证**

调用 qoder_cron action=`list` 确认任务仍在且 schedule 正确；`git status` 工作区干净。

---

## 自审记录

- **Spec 覆盖**：定时 08:00 ✓（Task 2）；泛 AI 全领域、中英混合中文输出 ✓（prompt 搜索轮次与格式）；日报结构 ✓（prompt 格式段）；错误处理 ✓（prompt 质量要求与降级规则）；验证 ✓（Task 3）；边界：不抓登录内容、按天归档 ✓（prompt 与 .gitignore）
- **占位符扫描**：无 TBD/TODO；prompt 为完整可粘贴文本
- **类型一致性**：prompt 文件路径、日报路径、板块名在 Task 1-4 中一致

---

## 执行状态（2026-09-01，阻塞）

- **Task 1-2 完成**：prompt 文件已建并提交；自动化任务已创建（id `61ba5c72-4f07-40a6-8380-70afe889bfbc`，cron `0 8 * * *` Asia/Shanghai）。
- **Task 3 受阻**：连续 4 次手动运行均失败。日志定位根因：自动化（headless）会话调用模型推理 API 返回 `403 FORBIDDEN`，错误码 `112`，指向 pricing——**当前账号套餐不包含自动化功能**（与模型选择无关，模型即 DeepSeek V4 Flash，交互会话可用）。任务在连续失败后自动熔断禁用（`pauseReason: failureCircuit`）。
- **Task 4 部分完成**：`run`（触发可用，会话被套餐拦截）、`enable`（验证可用）、`disable`（验证状态切换）均正常。
- **最终状态（用户确认"先不动"）**：任务保持禁用，不空跑；待用户升级套餐或另行决定后，用 `qoder_cron enable` 手动开启，或用 `qoder_cron remove` 删除。
- **待办（可选）**：若用户改用独立 Python 脚本方案，需新建脚本 + Windows 任务计划程序，并更新本设计/计划。

