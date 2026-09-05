# 阶段 11 — 待做池与架构优化清单（Backlog & Architecture Tasks）

> 状态：**活文档**（随每轮实施更新）· 日期基线：2026-09-04 · 用途：汇总各册"剩余项 + 实测新观察 + 架构优化任务"，按优先级排池，供后续轮次取用。
> 归档衔接（2026-09-05）：新增需求（加速 LoRA/质量增强/90 天清理/刷新语义/自检自动化）已列入 **book-14**；本册剩余问题处理完毕后执行归档（未完成且有价值条目迁至各册或 book-14，本册只留指针）。
> 约定：**P0=阻塞用户价值/回归风险；P1=明确收益；P2=甜点/低优先**。已完成项不在本册，见 book-00 §10 状态总览。

---

## 1. 实施状态总览（2026-09-04 基线）

| 册 | 目标 | 状态 | 证据/记录 |
|---|---|---|---|
| 01 基座 | 版本指纹/可信门禁/事实登记 | ✅ 完成 | version.py/runtime_check/e2e_smoke(SMOKE_OK)/code-fact-registry；登基演练+三端一致 |
| 02 前端 | 文案/去术语/继续按钮/错误分类/上下文 | ✅ 完成(增强待) | /config 实况；new_send_function 删除；新会话清空+_current_cid 修复 |
| 03 输出行为 | 中文铁律/400 修复/流式调研 | 🟡 核心完成/增强待 | 语言铁律+SYSTEM_MESSAGE；流式=消息级、逐 token 不可行(调研)；**消息级分批渲染未做** |
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
2. **book-08 风格册开工**：SYSTEM_MESSAGE/agent-reading 收紧「只问必要问题」清单+反例（分辨率/时长/seed/镜头/是否OK 一律不问；内容不明才问、一次只问一个）；补 `docs/style-guide.md`（好/坏回复对照）；用**真实对话任务**（用户提供的关键片段）做回归：是否多问/是否完成/是否中文。
3. **消息级分批渲染（book-03 增强，治"等待期无输出"）**：qwen_agent 为**消息级** yield（已调研）→ 重构 `run_turn`/`send`：把 agent 中间文本/工具结果**逐批 yield** 到对话（而非最终一次性）；用户提交后即可看到"正在…/已提交/进度"，无需等整轮。
5. **模板默认数值≠请求参数（用户实测 2026-09-05，已修复待回归）**：请求 720p/24fps/15s，产出**864×480/24fps/5.17s**（模板 ResolutionSelector=0.4MP、时长表达式=5s 的默认值，UI→API 转换后未被覆写）。根因修复：`stage.apply_generation_params`（按 token_map 覆写 MiniMaxH3* width/height/length、BasicScheduler steps、CreateVideo fps）+ 单测 3 例（117 全绿）。**剩余回归**：真实提交→ffprobe 断言产出参数；并加「产出参数回执」到取片流程（见 P0.6）。
6. **产出参数校验/诊断工具（"agent 没有合适的工具"落地）**：① 取片/完成回执带 ffprobe 实测（width/height/fps/duration/nb_frames）与请求参数对照；② 提交前「模板默认 vs 请求」校验开关（默认值≠请求时告警，防再翻车）；③ 供 agent 查询的 `verify_video` 类工具（book-09 延伸；book-12 步骤4 联动）。
7. **⚠️ 队列共享：删除/取消必须归属校验（2026-09-05 实测教训）**：ComfyUI 是**多用户共享服务器**，`/queue` 可见所有人的任务——队列中的任务**未必是当前用户/我的**。规则（红线）：① `h3_submit --submit-only` 已把 prompt_id 写入 `last_job.json`/任务目录 job.json，**只允许操作/查询本会话登记过的 prompt_id**；② `/queue/delete`、取消、清理等接口目前 405/500 且不可用——**不要在工具/脚本中裸调队列删除**；③ 记录为工具需求：`dev.py queue status`（只读，含归属判定：本会话/未知/他人）与 `queue cancel <id>`（先校验归属+确认，未登记即拒绝）；④ 处置经验：等待期间看到队列任务可能属于他人，勿惊讶、勿删除。
4. **任务监控反馈增强（book-03/09 联动）**：`task_watch` 状态含「阶段+已耗时+预计」；提交类动作后 agent 明示「后台执行中，预计 X 分钟，可用[取片]查询」；ComfyUI 首次加载/排队>30 分钟给出提示（观测：H3 首载+排队是 40 分钟事件主因，非卡死）。

### 🟧 P1（明确收益）
5. **idea2prompts --segments N**：自动产出 N 段转场提示词（写入 `video_flf2v.segment_<i>.positive.txt`），再交给 batch `--prompts-file`；与 book-06 §5 步骤 2 一致。
6. **book-11 日志体系落地**：logutil 唯一化（h3_submit/h3_batch/llm_mem/sync_auto/task_watch 收敛）；事件模型（用户/决策/工具含参数/提交含参数/进度/产物）；防垃圾（轮转/上限/时区统一）；`dev.py logs`（view/link/clean/check）。
7. **book-12 注册表化**：`config/capabilities.json` 补 template/slots/prompt_inject/params/features/enabled；`runs/h3/workflow_registry.py`；工具描述与 SYSTEM_MESSAGE 动态化（digest）；`dev.py workflows`（list/add/disable/enable/validate/swap）→「便捷更换工作流」。
8. **参考图使用审计**：`use`/`bind_images`/`h3_submit` 把 {cid, stage, slot, image, prompt_id} 写入运行日志（与 book-11 联动）——本次事故教训：只能从 job.json 反查。
9. **"素材绑定"路径统一（架构重构，见 §3.1）**。

### 🟨 P2（甜点/低优先）
10. 参考视频支持（LoadVideo+ref_videos 接线）——维持"甜点/低优先"。（→ 见 book-14 T8「参考视频/音频原生支持」，已迁移登记）
11. 时区显示统一（线索/日志时间：北京 vs UTC 差 8h；随 book-11 统一）。
12. `turn_state._active_batch` 消费或清理（现为死隔离；接 cid 或删除）。
13. seed 策略：h3_submit 默认 seed 12345 硬编码 → 默认随机/可指定。
14. 上传预览"可判定性"：gallery 缩略图标注所属会话/是否仍可用（配合 book-05/11）。

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