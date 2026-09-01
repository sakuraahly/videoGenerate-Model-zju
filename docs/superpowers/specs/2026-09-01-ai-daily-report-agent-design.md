# AI 每日资讯日报 Agent 设计

日期：2026-09-01
状态：已批准（用户确认采用方案一）

## 目标

每天 08:00 自动采集过去 24 小时的泛 AI 全领域新闻（中英文信息源），整理成带中文摘要的 Markdown 日报，保存到项目下 `ai_daily_reports/YYYY-MM-DD.md`，供用户上班前翻阅。

## 架构

- **调度器**：Qoder 自动化（qoder_cron）
  - schedule：cron 表达式 `0 8 * * *`，本地时区
  - outputMode：`independent`（每次运行一个独立会话）
  - executionAuthorization：`true`（Full Access，允许写文件和联网）
- **执行体**：自动化会话中的 agent，使用 WebSearch / WebFetch 采集信息，用 Write / Bash 写入日报文件
- **产物**：`D:\MY_CODING_PROGRAM\videoGenerate_Model&zju\ai_daily_reports\YYYY-MM-DD.md`

## 组件

1. **定时触发器**：qoder_cron 任务，名称如「AI 每日日报」
2. **自包含运行 prompt**：自动化会话不继承当前对话历史，prompt 必须包含全部采集范围、搜索策略、日报格式、文件路径、错误处理指令
3. **日报文件生成器**：agent 按模板渲染 Markdown 并写入指定路径

## 数据流

1. 定时触发（每天 08:00）
2. agent 用 WebSearch 进行多轮中英文搜索（见关键词策略）
3. 对高价值条目用 WebFetch 抓取详情补充摘要
4. 去重、按板块分类
5. 渲染 Markdown 日报，写入 `ai_daily_reports/YYYY-MM-DD.md`
6. 会话中输出日报文件路径和条数摘要

## 日报格式

```
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
来源：OpenAI 博客、HuggingFace、arXiv、机器之心、量子位、X 等公开渠道（通过 WebSearch 检索）
```

板块固定 6 类；某类无内容时写「今日无相关动态」。

## 搜索关键词策略

英文轮次：
- `AI model release 2026`
- `LLM agent news today`
- `diffusion video generation model`
- `HuggingFace trending model`
- `arXiv AI paper 2026`

中文轮次：
- `AI 大模型 发布 今天`
- `人工智能 行业 动态`
- `AI 开源 项目`
- `AI 融资 政策`

要求：优先采集近 24 小时内容；同一事件多来源时保留权威来源并去重；每条新闻必须给出真实可访问的链接。

## 错误处理

- **搜索失败或无结果**：仍生成日报骨架，注明「今日未获取到有效信息，可能网络异常」，不伪造内容
- **文件写入失败**：在会话中输出完整日报内容并明确说明错误，不静默丢弃
- **网络超时**：对失败的关键搜索重试一次

## 验证

1. 创建自动化任务后立即用 `qoder_cron run` 手动触发一次
2. 检查 `ai_daily_reports/` 目录下是否生成当日文件
3. 检查格式：标题、板块、摘要、链接是否齐全
4. 如有问题修订 prompt 后再次触发

## 边界

- 只采集公开信息，不抓取需要登录/付费的内容
- 不存储个人数据；日报仅含公开信息的摘要与链接
- 按天归档文件，不建数据库
- 依赖 Qoder 桌面应用运行；Qoder 未启动时当天任务不执行（Qoder 自动化固有约束）
