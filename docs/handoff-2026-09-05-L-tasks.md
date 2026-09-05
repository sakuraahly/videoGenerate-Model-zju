# L 类任务交接文档（book-14 §L1–L5 · 独立执行 Agent 专用）

> 用途：把 book-14 的 5 个**低耦合、简单**任务交给独立 Agent 执行。本档**自包含**（不依赖原会话上下文）。
> 产出纪律：每项完成 = 单测/自测通过 → 更新 docs → 双端核对 → 提交（一次 commit 可含多项）。

---

## 0. 仓库事实（先读，再动手）

| 端 | 绝对路径 | 角色 |
|---|---|---|
| Windows 主库（**源码真源**） | D:\MY_CODING_PROGRAM\videoGenerate-Model-zju | 一切改动先改这里；唯一 push GitHub 的一端 |
| GitHub | git@github.com:sakuraahly/videoGenerate-Model-zju.git | Windows push；**spark 永不 push** |
| spark 运行时 | /home/Developer/videoGenerate-Model-zju（ssh spark，已免密） | 运行实例；只能经 dev.py sync/commit 同步；spark 侧 commit 用内联身份 |
| ⚠️ 禁用 | C:\Users\39163\videoGenerate-Model-zju | 残留副本，勿用 |
| ⚠️ 禁用 | Z:/ 网络映射 | 禁用 |

**必读文档（按顺序）**：
1. START-HERE.md（§2 索引、§3 约定）
2. docs/dev-workflow.md —— **全程遵守**；§10 有本环境文件写入 EIO(1175) 与 JS/PowerShell 转义教训；§11 日志体系
3. docs/code-fact-registry.md（单一事实源，改动须同步）
4. docs/planbook/book-14-lora-accel-delivery.md（L 类定义与红线）
5. docs/planbook/book-13-backlog.md（归档衔接说明）

**铁律（违反即返工）**：
- 不改 ComfyUI systemd 服务；不改共享模板（workflows/remote_workflows/*.json —— **只读**）；不重启 agent（除非任务说明）；
- 本批 L 类为前后台小改——L2 需在 spark 侧校验 /config 文案；需要重启时命令见 §6；
- 中文/引号经 PowerShell→ssh 会乱码：**一律用临时脚本文件传输执行**（scp 本地脚本到 spark:/tmp/… 再 bash/venv python）；
- 删除操作默认 dry-run；不要触碰 uploads/、outputs/、workflows/h3_*/、logs/run_*.log（运行期产物）；
- dev.py 的 EXCLUDE 清单（机器配置：config/deploy|llm|pipeline|transfer|autosync|upload_watch.json 等）**不随同步覆盖**，新增机器配置须同时加进 runs/dev.py 的 EXCLUDE_FILES。

**常用命令（在 Windows 主库根目录执行）**：

    python runs/dev.py check            # 三端状态核对
    python runs/dev.py sync             # 定点同步本次改动到 spark
    python runs/dev.py commit -m "msg"  # Windows commit + push + spark commit（事务化）
    python -m unittest discover -s runs/h3/tests -p "test_*.py"   # 全量单测（Windows 用标准库 unittest，无 pytest）
    python runs/dev.py logs view --remote   # 日志尾部/跨端

> 注：Windows 的 python = C:\msys64\mingw64\bin\python.exe；spark 用 /home/Developer/qwen-agent-venv/bin/python（系统 python3 无依赖）。

**文件写入防坑（dev-workflow §10）**：改已有文件用「read → 整体 write」或 PowerShell
[IO.File]::WriteAllText；连续多次 edit / 紧挨 py_compile 会 EIO(1175)；JS 字符串转义：内容用行数组+join，
反引号与插值符会破坏模板串。

---

## 任务详细规格

### L1 — 90 天历史会话自动清理
- **新增文件**：D:\MY_CODING_PROGRAM\videoGenerate-Model-zju\runs\agent\session_cleanup.py
- **新增配置**：D:\MY_CODING_PROGRAM\videoGenerate-Model-zju\config\session_retention.json
  （格式：{"enabled": true, "days": 90, "dry_run": true}；该配置为**全项目统一策略，入库 tracked**，不是机器配置）
- **行为**：
  - 扫 logs/agent_chats/*.jsonl 与 *.meta.json；判定基准 = 文件 mtime 或 meta.ts（取较新）；
  - 超过 days（默认 90）的会话 → 删除 <cid>.jsonl、<cid>.meta.json 与 logs/agent_chats/thumbs/ 中该 cid 缩略图
    （缩略图文件名为 <sha>.jpg，无法直接关联 cid 时**不删**，仅删 jsonl/meta——写明注释）；
  - **只删聊天档**：严禁删 uploads/、workflows/、outputs/、logs/run_*.log；
  - CLI：python runs/agent/session_cleanup.py status|clean [--yes] [--days N]；clean 默认 dry-run 输出将删清单；--yes 真正删除；
  - 返回 (统计字典, exit code)。
- **单测**：新增 runs/h3/tests/test_session_cleanup.py（unittest）：临时目录造 old/new 聊天档 → clean(dry_run) 不删；--yes 删旧留新；status 输出含数量。
- **文档**：docs/code-fact-registry.md 增补「会话保留策略」小节（默认 90 天、路径、命令）。

### L2 — UI“刷新”按钮语义化
- **文件**：D:\MY_CODING_PROGRAM\videoGenerate-Model-zju\runs\agent\ui_app.py（约 765 行）与 docs/agent-workflow.md（约 166 行）
- **现状**（已勘定）：ref_btn = gr.Button('刷新')，其 click 仅刷新**历史会话下拉** hist_dd 的 choices（gr.update(choices=_choices())）。
- **改动**：按钮文案改为**指明用途**，如「刷新历史列表」（或「刷新历史会话」）；并在按钮附近加简短提示
  （标题/tooltip 或相邻 Markdown 说明"刷新仅更新左侧历史会话下拉"）。文档同步。
- **禁止**：不得改变任何事件绑定/逻辑；不得新增“全屏刷新/刷新全部”之类含糊行为。
- **验收**：spark 侧 /config 命中新文案（用 python 临时脚本取 http://127.0.0.1:7860/config 判断，勿依赖 grep 中文——会乱码）；
  e2e_smoke 通过（§6 命令）。

### L3 — 加速 LoRA 事实登记（纯文档/配置）
- **文件**：docs/code-fact-registry.md（追加章节）；config/capabilities.json（新增顶层 "lora" 段：路径/模式/步数/分辨率/用途）
- **内容**（来自用户实测调研，原样登记）：
  目录 /home/Developer/ai/ComfyUI/models/loras/MiniMax_H3/ 下 3 个 ComfyUI bf16 加速 LoRA：
  1) minimax_h3_fl2v_turbo_4step_v1.0_768p_comfyui_bf16 — FL2VA（T2V/I2V/FLF2V），4 步，768p(1344×768)，v1.0；
  2) minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16 — Ref2VA（最多 9 参考图+3 参考视频+3 参考音频，提示词 <Picture N>/<Video N>/<Audio N>），4 步，544p 混合，v0.1 预览；
  3) minimax_h3_ref2v_turbo_8step_v1.0_768p_comfyui_bf16 — Ref2VA，8 步，768p，v1.0（质量更高，速度≈4 步版 2 倍）。
  另注明：加速 LoRA ≠ 风格/角色 LoRA（不同用途，可叠加需校验）。
- **验收**：python -c "import json; json.load(open('config/capabilities.json', encoding='utf-8-sig'))" 通过；dev.py check 一致。

### L4 — book-13 ↔ book-14 条目迁移核对（纯文档）
- **文件**：docs/planbook/book-13-backlog.md、docs/planbook/book-14-lora-accel-delivery.md
- **动作**：把 book-13 中「适合放下一本」的条目**串引用**到 book-14：P1#10（参考视频支持）→ book-14 T8；
  §3.1 素材绑定统一入口、§3.2 图片解析收敛、§3.3 事实/常量单源 → 在 book-14 相应章节标注归属（保留 book-13 原文，仅加"见 book-14 §x"字样）；其余 P0/P1/P2 保持不动。
- **验收**：两册内容无损（git diff 仅增标注）；文档无重复矛盾。

### L5 — dev.py queue status（只读）
- **文件**：D:\MY_CODING_PROGRAM\videoGenerate-Model-zju\runs\dev.py（新增 cmd_queue/argparse 子命令 queue）
- **行为**：python runs/dev.py queue status → ssh curl http://127.0.0.1:8188/queue 展示 running/pending 列表
  （id、prompt_id 前 16 位、节点数），并对每个 prompt_id 判定**归属**：
  本会话登记（last_job.json / workflows/*/job.json 的 prompt_id 集合内，读取本地与 spark 两处）→ 其他 → 未知。
- **禁止**：**不得实现 /queue/delete、取消、清队**（共享服务器，删除须按归属校验后再做，属 book-14 T 级）。只读。
- **验收**：python runs/dev.py queue status 输出正常；代码 grep 无 DELETE/delete 写路径。

---

## 6. 交付与验证顺序（每项必做）
1. Windows 改码 → 单测全绿（unittest discover；L1/L2/L3/L5 新增或复跑既有 117+ 用例）；
2. python runs/dev.py sync → 三端核对（dev.py check 显示两端 0 dirty）；
3. spark 侧验证（临时脚本传 spark 执行；L2 需检查 /config 文案 + SGLang 在线）；
4. python runs/dev.py commit -m "book-14 Lx: …"（一个 commit 可含多项，消息注明 L 编号）；
5. 最终 dev.py check 一致后，在 docs/planbook/book-14 下勾选对应 L 项并提交。

**Agent 重启（仅 L2 需要）+ 冒烟**（其余 L 类不需要重启）：

    ssh spark "tmux kill-session -t agent 2>/dev/null; sleep 1; tmux new-session -d -s agent 'cd /home/Developer/videoGenerate-Model-zju && /home/Developer/qwen-agent-venv/bin/python runs/agent/scheduler.py 2>&1 | tee ~/agent.log'; sleep 18; grep -m1 AGENT_VERSION ~/agent.log"
    ssh spark "cd /home/Developer/videoGenerate-Model-zju && /home/Developer/qwen-agent-venv/bin/python tests/e2e_smoke.py 2>&1 | tail -9"   # 期望 SMOKE_OK

---

## 7. 常见坑速查（本次事故复盘）
- 模板（workflows/remote_workflows/*）**只读**；绑定参考图必须用副本（refimage.bind_images_to_template(template=副本)），严禁 in-place 写共享模板。
- 参数注入：模板经 UI→API 转换后保留模板默认值（曾致 480p/5s 翻车）——凡改 h3_submit/stage.py 需跑 test_stage_params.py 且真机 ffprobe。
- h3_submit 的 submitted 行曾在 main() 引用 _stage_mode 局部变量 images（NameError 事故）：任何"补日志/补参数"必须先确认变量作用域。
- 队列是**共享服务器**：看到的任务可能属于他人；只可查询（queue status），任何删除/取消须归属校验（未做=禁止）。
- 中文字符串经 PowerShell 双引号→ssh 会乱码：一律临时脚本文件方式执行。
