# 阶段 11 — 待做池与架构优化清单（Backlog & Architecture Tasks）

> 状态：**活文档**（随每轮实施更新）· 日期基线：2026-09-04 · 用途：汇总各册"剩余项 + 实测新观察 + 架构优化任务"，按优先级排池，供后续轮次取用。
> 归档衔接（2026-09-05）：新增需求（加速 LoRA/质量增强/90 天清理/刷新语义/自检自动化）已列入 **book-14**；**本册已归档闭环（2026-09-05）**：P0/P1/P2 全部完成或登记保留（§3.2 图片解析收敛、P2#14 预览可判定性——低优先·登记保留；book-13 只留指针与登记）。
> 约定：**P0=阻塞用户价值/回归风险；P1=明确收益；P2=甜点/低优先**。已完成项不在本册，见 book-00 §10 状态总览。

---

## 1. 实施状态总览（2026-09-04 基线）

| 册 | 目标 | 状态 | 证据/记录 |
|---|---|---|---|
| 01 基座 | 版本指纹/可信门禁/事实登记 | ✅ 完成 | version.py/runtime_check/e2e_smoke(SMOKE_OK)/code-fact-registry；登基演练+三端一致 |
| 02 前端 | 文案/去术语/继续按钮/错误分类/上下文 | ✅ 完成(增强待) | /config 实况；new_send_function 删除；新会话清空+_current_cid 修复 |
| 03 输出行为 | 中文铁律/400 修复/流式调研 | ✅ 完成（2026-09-05） | 语言铁律+SYSTEM_MESSAGE；流式=消息级逐批（非逐 token）；**消息级分批渲染已完成（C1）** |
| 04 自动完成 | 截断/任务意图才续、寒暄不续 | ✅ 核心 | should_continue 纯函数 8/8 + CLI 同判 + E2E（你好只回一次） |
| 05 资源隔离 | 会话级素材隔离 | ✅ 完成(含补丁) | cid 落盘(含 dup)/--session/归一化/空会话线索+授权引导；GRADIO cid 接线修复 |
| 06 工作流提示词 | 属性词化+逐段注入+参考图绑定 | ✅ 核心 | 模板/槽位清理；--prompts-file+按段注入；bind_images+默认资产守卫；**idea2prompts --segments 未做** |
| 07 引擎/批量 | 导入/超时/批量跟踪 | ✅ 核心 | 导入三处+fcntl；status 即时返回；BATCH_MANIFEST+poll_batch；轮询成本=多次查询(已文档化) |
| 08 风格 | 不纠结细节/中文/完成导向 | ⬜ 未开始 | 语言铁律已就位，风格/决策清单/真对话回归待做 |
| 09 验证 | 端到端黄金路径 | 🟡 方法就绪/黄金路径未闭环 | smoke 门禁每日执行；**真实"上传→绑定→提交→取片→各段不同"未完整跑通一次** |
| 10 验收 | 汇总 | 🟡 维护中 | 本册按 §2 待办滚动更新 |
| 11 日志 | 全场景/无垃圾/不错失 | ✅ 完成（2026-09-05） | logutil 唯一化+审计 jsonl+dev.py logs(含 360 天轮转)；103→117 单测；SMOKE_OK |
| 12 工具/工作流模块化 | 注册表驱动/便捷更换 | 🟡 实施中（步骤1 完成，步骤2 进行） | workflow_registry+10 单测；步骤2 发现并修复「模板默认参数≠请求参数」（见 §2 P0.5） |
| 14 加速与交付 | LoRA 候选/质量链/自检 | ⬜ 未开始（2026-09-05 新建） | book-14：T1-T8 + L1-L5（L 类拆给另 agent） |

---

## 2. 待做池（按优先级）

### 🟥 P0（下一批优先：解锁用户价值/回归风险）
1. ~~端到端黄金路径闭环~~ **✅ 已完成（2026-09-04）**：`tests/golden_path.py` 引擎级闭环——提交(87dccd14) → `/queue` 断言 LoadImage=已绑定参考图（非旧资产）→ 取片 `outputs/video_11.mp4`(521KB) → GOLDEN_OK；**剩余人工项：画面一致性确认**（详见 book-09 §6b）。
2. **~~book-08 风格册~~ ✅ 已完成（随 book-08）**：`docs/style-guide.md` 已建、必要问题清单已收紧（分辨率/时长/seed/镜头/是否OK 一律不问）——见 book-08 记录（用户提供的关键片段）做回归：是否多问/是否完成/是否中文。
3. ~~消息级分批渲染~~ **✅ 已完成（2026-09-05，C1）**：run_turn 消息级 chunk 即时送显（assistant 文本+工具名状态条）；send 只追加不替换（同条合并、done 去重）；spark 实测事件流 phase → chunk×70 → done；SMOKE_OK。：qwen_agent 为**消息级** yield（已调研）→ 重构 `run_turn`/`send`：把 agent 中间文本/工具结果**逐批 yield** 到对话（而非最终一次性）；用户提交后即可看到"正在…/已提交/进度"，无需等整轮。
5. **~~模板默认数值≠请求参数~~ ✅ 完成（2026-09-05 回归通过）**：请求 720p/15s → dry-run 工作流断言 **1280×736 / 15.0s→362 帧@24fps**（模板 0.4MP/5s 默认已被覆写）；回归证据：`h3_submit --stage t2v --resolution 720p --seconds 15 --dry-run`。根因修复见原条目：`stage.apply_generation_params`（按 token_map 覆写 MiniMaxH3* width/height/length、BasicScheduler steps、CreateVideo fps）+ 单测 3 例（117 全绿）。**剩余回归**：真实提交→ffprobe 断言产出参数；并加「产出参数回执」到取片流程（见 P0.6）。
6. **~~产出参数校验/诊断工具~~ ✅ 完成（2026-09-05）**：① 取片/完成回执新增 **`PROBE:`** 行（width/height/fps/frames/duration 实测，无条件输出）；② 模板默认 vs 请求校验（`_probe_diff`+`verify_mismatch/verify_ok` 事件，gp 可用时）；③ 供 agent 查询的 `verify_video` 类工具（book-09 延伸；book-12 步骤4 联动）。
8. **~~输出异常保护~~ ✅ 已完成**（`_dup_text` 连续重复块丢弃+`MAX_OUTPUT_CHARS=30000`+中断展示；见 book-16 §6.3 系列修复，含三级防护与增量解码）限。（已实现+2 单测，150 全绿）
9. ~~队列共享~~ 见 7。
7（原）**⚠️ 队列共享：删除/取消必须归属校验（2026-09-05 实测教训）**：ComfyUI 是**多用户共享服务器**，`/queue` 可见所有人的任务——队列中的任务**未必是当前用户/我的**。规则（红线）：① `h3_submit --submit-only` 已把 prompt_id 写入 `last_job.json`/任务目录 job.json，**只允许操作/查询本会话登记过的 prompt_id**；② `/queue/delete`、取消、清理等接口目前 405/500 且不可用——**不要在工具/脚本中裸调队列删除**；③ 记录为工具需求：`dev.py queue status`（只读，含归属判定：本会话/未知/他人）与 `queue cancel <id>`（先校验归属+确认，未登记即拒绝）；④ 处置经验：等待期间看到队列任务可能属于他人，勿惊讶、勿删除。
4. ~~任务监控反馈增强~~ **✅ 完成（2026-09-05，C2）**：task_watch 状态含「已耗时 X 分 X 秒」+ 诚实区间提示（queued=排队中/running=1-20 分钟区间/failed 指引）；首次 update 明示「已后台执行，可继续查询/取片」；超 30 分钟提示（共享队列/H3 首载，非卡死）；2 单测（145 全绿）。

### 🟧 P1（明确收益）
5. **~~idea2prompts --segments N~~ ✅ 完成（2026-09-05）**：`--segments N`（flf2v）+ `parse_segments_json` + 分段文件写入（`video_flf2v.segment_<i>.positive/negative.txt`）；单测 4 例全绿。**注**：真实 LLM 分段生成待 llm.json(enabled) 会话验证一次。
6. **book-11 日志体系落地**：logutil 唯一化（h3_submit/h3_batch/llm_mem/sync_auto/task_watch 收敛）；事件模型（用户/决策/工具含参数/提交含参数/进度/产物）；防垃圾（轮转/上限/时区统一）；`dev.py logs`（view/link/clean/check）。
7. **book-12 注册表化**：`config/capabilities.json` 补 template/slots/prompt_inject/params/features/enabled；`runs/h3/workflow_registry.py`；工具描述与 SYSTEM_MESSAGE 动态化（digest）；`dev.py workflows`（list/add/disable/enable/validate/swap）→「便捷更换工作流」。
8. **~~参考图使用审计~~ ✅ 覆盖确认（2026-09-05）**：audit jsonl 已含 params{session(cid), stage, images}+prompt_id；run log 含 submitted 事件 imgs/分辨率；与 book-11 联动——如需 slot 级明细再评估。
9. **"素材绑定"路径统一（架构重构，见 §3.1）**。

### 🟨 P2（甜点/低优先）
9b. **~~加载历史会话素材预览空白~~ ✅ 完成（2026-09-05）**：`_previews_for_cid` 按 uploads/log.jsonl 按 cid 重建缩略图（sha→thumbs）；真实链 `_load` 验证：会话 20260905_005543_ee20 → **已重建 2 项素材预览**（gallery 返回 2 图）。
10. 参考视频支持（LoadVideo+ref_videos 接线）——维持"甜点/低优先"。（→ 见 book-14 T8「参考视频/音频原生支持」，已迁移登记）
11. **~~时区显示统一~~ ✅ 完成（2026-09-05）**：logutil `_ts()` 固定北京时间（spark 系统 UTC+0 → 日志与用户差 8h），`_tz()` 统一标注 UTC+8。
12. **~~turn_state._active_batch 清理~~ ✅ 完成（2026-09-05）**：无消费者死隔离已删除；`begin_turn` 保底空实现（提交路径用 `_pending_batch_id`）。
13. **~~seed 策略~~ ✅ 完成（2026-09-05）**：params DEFAULTS seed=12345 → **"auto"**（每次随机）；显式 `--seed` 可指定复现。
14. 上传预览"可判定性"：gallery 缩略图标注所属会话/是否仍可用（配合 book-05/11）。
15. **远期候选·不承诺（book-18 §7 登记 2026-09-05）**：① 口型驱动（Wav2Lip/SadTalker——需额外模型/依赖/管线）；② 局部重绘 Inpaint（修乱码区，需新模板工程化）；③ 标题/图表装配（后期链模板）；④ 1080p 原生生成（模型上限 768p，当前不可达）；⑤ 齿音处理（音频链可选）。
## 6. 甜点任务候选总览（2026-09-05 整理；含思路/取舍/建议序，用户拍板后按序做）

| # | 候选 | 价值 | 工作量 | 依赖/风险 | 思路与建议序 |
|---|---|---|---|---|
| S1 | 上传预览可判定性（P2#14）：gallery 缩略图标注所属会话/是否仍可用 | 中 | 小 | 依赖 _previews_for_cid（已有）+ thumbs；低风险 | 建议第 1 批：标注会话日期/已用/可用徽标+悬停提示；配合 book-05 边界语义 |
| S2 | agent 出片默认走 T2 增强（--postprocess fast 默认开，可选关）：超分+降噪+锐化 | 中高（所有出片直接受益；4 步瑕疵补偿） | 小 | 仅 ffmpeg（无 GPU）；需验证超分后字幕/音轨不受影响（顺序=增强后再字幕/语音） | 建议第 1 批：默认 fast；--postprocess none 可关；验证 T2b 全链仍通过 |
| S3 | T9 后续小项：取消任务后 task-watch/会话任务表残留联动清理 | 低 | 小 | 无 | 第 1-2 批随 S2 顺手 |
| S4 | idea2prompts --segments 真实 LLM 验证一次（P1#5 注记）；并给 batch --prompts-file 通道打通 | 中 | 中 | 需 llm.json enabled 一次 + batch 侧参数验证；无 GPU | 第 2 批 |
| S5 | dev.py services selfcheck --llm（SGLang 销毁性演练，队列空闲+授权下） | 中（补 book-15 最后一块证据） | 小 | 需授权（可能中断）；已有 wake 自适应链 | 第 2 批（授权后） |
| S6 | 多音色选择：SYSTEM 台词规则允许用户指定男/女声（Yunxi/Xiaoxiao 切换）+ 字幕字号用户可调 | 低中 | 小 | 无 | 第 2 批 |
| S7 | 参考视频/音频原生支持（book-14 T8：Ref2VA videos/audios 槽 + Video N/Audio N 提示词规范） | 中高（多模态参考直接解锁人物/音效一致性） | 中大 | 需 ComfyUI Ref2VA 模板 slots 接线；风险=模板属同事镜像（本地扩展预案） | 第 3 批（有价值但工程量最大） |
| S8 | 批量状态轮询 O(1)（§3.5：h3_batch status 直接查 /history+/queue 一次查询） | 低（性能） | 中 | 无 GPU；与 book-11 日志联动 | 第 3 批 |
| S9 | 会话历史导出/搜索（logs/agent_chats 导出 md/json + 关键字过滤） | 低中 | 中 | 无 | 第 3 批 |
| S10 | 质量看板：dev.py quality-report（W-系列指标持久化：SSIM/码率/瑕疵登记汇总表） | 低 | 小 | 无 | 第 4 批（数据积累型） |
| S11 | §3.2 图片解析收敛（assets.py 共享模块） | 低（重构收益） | 中 | 回归风险高（触碰引擎三处调用） | 不建议近期：价值/风险比低，登记观察 |
| S12 | book-05 跨会话显式共享区选项 | 中 | 中 | 权限语义需明确 | 第 4 批（用户有跨会话需求时再启） |
| S13 | book-18 远期（口型驱动/Inpaint/标题装配/1080p/齿音） | 高（未来） | 大 | 外部模型/模板/工程化 | 远期池（不承诺；有需求再单独立册） |

**推荐起手批次（价值/工作量比最优）**：S1 → S2 → S3 → S4/S5/S6（第一批可直接开工；S7 作为下一个大甜点预留；S11 明确不建议近期）。

---

## 3. 架构优化任务（低耦合重构，防漂移）

### 3.1 统一"素材→模板槽位"绑定入口
- 现状三处路径：`refimage use --slot N`（工具）、`h3_submit --image`→`bind_images_to_template`（引擎）、未来 `call_comfyui images`（agent）。均改同一模板文件，语义易漂移。
- 方案：**单一入口 `refimage.bind_images_to_template(stage, names)`**（已存在）供三者共同调用；`use`/`--image`/`images` 仅做参数归一 → 收敛后行为一致、可审计、可 undo。
> 关联 book-14：绑定入口的收敛随 book-14 T1（LoRA 接线复用同一 `bind_images_to_template` 入口）与 T8（参考视频/音频接线）落地。

### 3.2 图片解析收敛（_resolve_image / gather_images）
- `h3_batch._resolve_image` 与 `stage._resolve_input_image` 功能重复（uploads/input 池查找），且都以"项目根/uploads + ComfyUI input"为范围；抽到共享模块（如 `runs/h3/assets.py`），两端复用，防改动不一致。
> 关联 book-14：book-14 未覆盖图片解析收敛，本项**暂留 book-13**（架构优化·低优先）。

### 3.3 事实/常量单源
- 已有 code-fact-registry + runtime_check.FACTS；把 `DEFAULT_ASSET_MARKERS`（模板默认资产标记）纳入登记表，新增默认资产时须更新；`REPLY_MAX_TOKENS` 等常量核对继续由 runtime_check 把关。
> 关联 book-14：事实/常量单源随 book-14 L3（加速 LoRA 登记进 `capabilities.json` + code-fact-registry §10）、T3（模板默认值 vs 注册表 params 核对）与红线（新增参数须同步注册表/事实登记表/runtime_check）落地。

### 3.4 角色化工具描述/参数动态化（随 book-12）
- 六工具描述仍手写枚举（stage/resolution/工作流）→ 注册表派生，避免"新工作流=改代码+改描述"。

### 3.5 状态轮询成本（book-07 遗留）
- `h3_batch status` 每段新起 `h3_submit --resume`（每段≤30s）；重构：直接用 `h3/comfy` 的 `/history`+`/queue` 查询（一次性），批状态查询 O(1)；与 book-11 日志联动。

---

## 4. 新观察 / 风险（记录，不阻塞）
- **"等待 40 分钟"**：H3 首次加载 + 旧提交排队 + 720p 生成（队列现已空，非卡死）——属环境/GPU 现实；对策=反馈增强（P0.4）+ 允许"取片"分次查询。
- **模型措辞口径**：agent 曾把 `session` 传字面值 `current`、曾自行未授权翻全部——已由工具归一化+警示+素材边界；风格册（P0.2）继续收紧。
- **守卫误报风险**：`check_default_refs` 以文件名标记（drama_asset_* 等）判定默认——若用户恰好想用同名素材会误拒；方案=标记维护 + 允许显式 `--image` 放行（已规避：传图即跳过守卫）。
- **隔离与"跨会话复用"的张力**：默认本会话 vs 用户"这两张"引用——已用"线索+授权"桥接；如用户常需跨会话，可评估"最近会话共享区(显式)"选项（book-05 待定项）。

---

## 5. 建议执行顺序（按册序推进，P0 项随册落地）

> 维持 **book 顺序**（08→09→10→11→12），P0 项按归属册插入：风格册任务随 book-08；黄金路径闭环随 book-09；**流式（消息级分批渲染）＝ book-03 增强批次**，在推进 book-08/09 期间一并实施（它对缓解「等待期无输出」最有体感，尤其黄金路径验证时）。

## 5. 建议执行顺序（下一批）
1. P0.1 黄金路径闭环（先跑通，作为一切的门禁用例）。
2. P0.3+P0.4 消息级分批渲染 + 监控反馈（治"无输出"体验，收益最直接）。
3. P0.2 风格册（配合真实对话回归）。
4. P1.6 book-11 日志（为所有后续提供证据源）→ P1.7 book-12 注册表（为更换工作流铺路）。
5. P1.8 参考图使用审计、P2 项按需。