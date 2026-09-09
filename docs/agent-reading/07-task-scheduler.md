# 任务调度器（定期/定点/服从安排）

> 背景（2026-09-09 用户定案）：agent 必须能**定期定点执行任务、服从安排**。

## 机制
- `runs/agent/task_scheduler.py`：每分钟 cron 调 `--tick`；任务定义=config/agent-tasks.json（五段 cron 式 schedule）；
- 两类任务：
  - **engine**：调度器**直接**执行白名单脚本（runs/ 下 .py）——失败自动重试 3 次；可靠路径，不依赖对话 LLM；
  - **agent**：注入 7860 会话（Gradio send，prefix【定时任务·…】）→ 由 agent 执行；SYSTEM 已声明**服从条款**（收到【定时任务·…】必须执行汇报，禁止忽略/拒绝）。
- 状态：logs/agent-tasks.state.json（last_run/runs/fails/last_result）。

## 常用操作
```bash
python3 runs/agent/task_scheduler.py --list      # 任务+状态
python3 runs/agent/task_scheduler.py --tick      # 手动一轮（调试）
python3 runs/agent/task_scheduler.py --daemon    # 常驻（默认已装 crontab 每分钟）
```

## 现有任务
- sched-watchdog（每5分钟自检）/ sched-night-check（夜间窗口每20分钟巡检）/ sched-demo-minutely（**演示任务，验证后移除**）/ sched-daily-report（每日20:00 agent 生产简报）。

## 说明
- 需要"定点执行长片/夜间/巡检"→配置 schedule 后由调度器保证，不再依赖对话交互；
- agent 对话任务仍会检查执行（调度器注入+SYSTEM 服从）；若 agent 再次假完成，调度器侧有 retry 与 fail 记录（可加检测升级）。
