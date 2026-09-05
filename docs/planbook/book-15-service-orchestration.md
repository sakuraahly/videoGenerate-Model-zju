# 阶段 13 — 服务编排：自启自愈 + 内存智能共存（book-15）

> 状态：**✅ 实施完成（2026-09-05）** · 日期：2026-09-05 · 来源：用户实测（htop 显示 mem 富余却进程失败；SGLang 死活起不来）与 2026-09-05 SGLang 恢复事件复盘
> 实施记录：L6 `runs/agent/supervisor.py`（once/watch，tmux `supervisor` 守护，4 单测）+ §3.2 `llm_mem` 内存编排（`comfy_queue_idle`/`planner_prep`(/free 队列空闲才执行)/`free_comfy`/wake 自适应降额表 0.25→0.20→0.15·max4→3→2，内存内不写机器配置，3 单测）+ L7 `runs/agent/svc_main.py` + `dev.py services status|restart-llm|restart-agent|selfcheck`。
> 验收：`dev.py services status` 六项全绿（comfyui systemd enabled/端口；sglang/agent/supervisor session+端口；llm 档位 0.25/4/8192/spec-off）；**自愈演练通过**：selfcheck kill agent → supervisor 90s 内拉起（AGENT_VERSION=c71b17e 复活）——sglang 自愈复盘走同链（llm_mem.wake 自适应），未做销毁性演练（SGLang 内存成本/影响面，登记为可选；restart-llm 需授权且队列空闲才执行）。
> 目标：三服务（SGLang LLM / ComfyUI 视频 / Agent 调度）各自「开机自启 + 崩溃自愈」，并**按工作负载智能切换共存模式**——不再出现"ComfyUI 或 Qwen 重启死活不行"。
> 红线：不**人工**重启/停止 ComfyUI 服务（崩溃恢复由 systemd 承担，见 §1）；不覆盖机器配置（config/llm_mem.json 等本机文件）；观测一律走项目程序（dev.py）。

---

## 1. 现状登记（2026-09-05 实测）

| 服务 | 启动方式 | 开机自启 | 崩溃自愈 | 备注 |
|---|---|---|---|---|
| ComfyUI | systemd comfyui.service | ✅ enabled | ✅ **Restart=on-failure（10s）** | 已满足；维持"不人工重启"红线即可 |
| SGLang (Qwen) | tmux 会话 sglang（llm_mem wake 拉起） | ❌ 无 | ❌ 无（崩溃即死，需手动） | 本次事故主缺口 |
| Agent 调度 | tmux 会话 agent | ❌ 无（人工） | ❌ 无 | 影响面小但应纳入守护 |

## 2. 根因：为什么「内存明明够，进程却失败」（用户 htop 质疑标准答案）

- 实证（2026-09-05）：`MemAvailable=51GB / 121GB 总`；`Shmem≈512MB`（远小于 16GB 上限）——**物理内存没有耗尽，htop 观察正确**。
- **失败机制**：DGX Spark 为统一内存；但 SGLang 的分配策略是"**按总内存比例静态预留 + 显式 mamba/linear KV 预算**"：
  1. `--mem-fraction-static 0.25` ⇒ 预留 0.25×121GB≈30GB 的**固定档**（与实际空闲无关）；
  2. 它在 CUDA 分配视图的"**可用**"= 总池 − ComfyUI 实持（/free 前 ≈49GB，CUDA 缓存被 ComfyUI 占用）；
  3. `rest_memory = 探测可用 − 预留档 − 模型等` ⇒ **为负**（-0.7~-1.2GB）→ `max_mamba_cache_size=-5` 拒绝。
- **结论**：不是"资源没被用"，而是 **SGLang 的"静态预留档"与"ComfyUI 占用的分配视图"互相顶牛**；htop 的 51GB 空闲 ≠ CUDA allocator 可径直接管的 51GB。**智能共存=在 LLM 需要时把 ComfyUI 的模型运行时卸载（/free），让其释放视图；在视频需要时 nap SGLang（已有）**——双向让位，余额才真实可用。

## 3. 目标与方案

### 3.1 `runs/agent/supervisor.py`（自愈守护，先做）
- 每 30s 探测 tmux 会话 agent/sglang 存活（`tmux has-session`）；死亡→按启动命令自动拉起（sglang 走 llm_mem.wake 恢复链；agent 走 scheduler 命令）；单次拉起失败 3 次→报警（写运行日志+状态条）不再死循环；
- window 已存在但端口不通→先 kill 会话再拉起（防僵尸）；
- CLI：`python runs/agent/supervisor.py once|watch`；由 tmux 会话 supervisor 承载（自启文档）。

### 3.2 内存编排器 `memory_planner.py`（升级 llm_mem）
- 状态机：`idle | llm_active | video_active`；
- **LLM 需要（ensure_llm_up 前置）**：探测 ComfyUI 队列+生成活动（`/queue` 空且无本会话待生成）→ 自动 `POST /free`（幂等，已在恢复手册验证）→ wake（fraction 自适应表：先 0.25/max4 → 失败降 max_running_requests 2 → 再失败报可读原因）；
- **视频需要（提交后）**：nap（既有）+ 记录"ComfyUI 重载模型约 1-2 分钟"（C2 已有提示）；
- 所有动作落 logutil 事件（`planner_free/planner_wake/planner_fail reason=…`）。

### 3.3 `dev.py services`（编排观测入口）
- `dev.py services status`：三服务端口/进程/开机自启状态/ComfyUI 模型态（RSS 峰值对比）/fraction 配置/最近 planner 事件（跨端 ssh）；
- `dev.py services restart-llm`（安全恢复链：检查队列→/free→wake→probe）/ `restart-agent`（tmux kill+拉起）；
- `dev.py services selfcheck`：验证自愈（kill sglang → 60s 内 supervisor 拉起）——演练专用，明示会中断当前对话。

### 3.4 文档
- docs/llm-memory-optimization.md 已有恢复手册（§2 更新为「编排器行为说明」）；START-HERE/运维文档登记三服务自启矩阵（§1 表格）+ 手册命令。

## 4. 验收（可复现）
- 故障演练：① `kill` sglang 调度进程 → 60s 内 supervisor 自动拉起且 /v1/models 200；② ComfyUI 满载模拟（提交一次生成后立即 nap/wake 循环）→ planner 自动 /free后 wake 成功，流程 120s 内闭环；③ `dev.py services status` 一次输出三服务+模型态+最近规划事件；④ 无"手动重启死循环"（失败 3 次自动停止并报警）。

## 5. 拆分建议（可交另一个 agent 的低耦合项）
- **L6**：supervisor.py（纯新增+单测（mock tmux）+文档；不碰 llm_mem）
- **L7**：dev.py services status（只读汇总，复用 queue_probe 模式）
- 内存编排器/自适应 fraction 由主流程做（与 llm_mem/ComfyUI 深度耦合）。

## 6. 与既有册关系
- book-01（基座事实登记：三服务自启矩阵）；book-11（事件审计：planner_* 入 run log）；book-14 T2b（视频重载时长提示）；book-13 长期维护。
