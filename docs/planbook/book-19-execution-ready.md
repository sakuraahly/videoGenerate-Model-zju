# book-19 执行就绪计划书（Execution Readiness）

> 版本：v1.0 · 2026-09-06 · 前置：`docs/pending-tasks-implementation.md` 经 **19 轮审核定稿**（changelog §14-§29）；本件把"定稿规格"转成"可执行清单"——执行者在每项完成后按 §7 回写并更新状态列。
> 事实权威：START-HERE §2 索引 / session-summary / reference；仓库三端一致（win=github=spark，0 dirty），单测基线 **165 例**。
> 引用约定：`S#`=pending-tasks-implementation.md 的节号；`☆`=spark 真机路径（需队列空闲窗口）。

---

## 1. 执行总纲

**目标**：按推荐序把 S1-S13 待做项逐一落地，每项过"单测全绿 → ☆真机验收 → 文档回写 → dev.py sync+commit"闭环。
**红线（每项动工前重读）**：ComfyUI systemd 勿动（唯一动作=`POST /free` 完整 body）；共享队列取消/删除必须归属校验（已修复为定向中断）；共享模板只读、绑定用任务副本；模型下载走魔搭；中文经 ssh 一律临时脚本文件；单测从仓库根运行。
**执行者纪律**："已修正必 grep 落点"；新钩子/新分支必有单测；两条路径共用变量必须前置初始化；决策记录必须同步正文修改。

## 2. 打开门禁（前置条件状态表——动工前逐项确认，均不阻塞 S2-P1a）

| # | 前置 | 状态 | 说明 |
|---|---|---|---|
| 1 | 三端一致+基线 | ✅ 已闭环（2026-09-06 现场检查，165 例） | dev.py check 0 问题 |
| 2 | Ref2VA 探测（S7 7a） | ✅ 已完成（九~十七审 all-spark 取证） | 模板树权威=remote_workflows；节点/槽位/id>146 均已定案 |
| 3 | 上传复用 upload_image | ✅ 服务端源码级确证 | server.py 无类型校验/重传安全；curl .mp4 抽验可选 |
| 4 | 768p 上限来源 | ✅ 定案=加速 LoRA（非模型） | 原生 1080p 探测=1920×1088+`--lora none`（☆待授权队列窗口；不阻塞主链） |
| 5 | 模型真实 ID（魔搭：RIFE/SD-Inpaint/Wav2Lip+SF3D/FunASR/F5-TTS） | 🔲 未闭合（通道级已验证） | 仅阻塞 S13/P 链；S1-S12 不依赖 |
| 6 | config/pipeline.json（机器配置） | ✅ win/spark 均 templates_dir=remote_workflows | S7a 双注册提醒已知 |

## 3. 执行顺序与每项规格索引

| 序 | 任务 | 规格 | 工作量 | 真机需求 | 关键前提/陷阱 |
|---|---|---|---|---|---|
| 1 | **S2-P1a**：agent 默认 `--postprocess fast`+合并单次编码链 | §2 | 小-中 | ☆1 次 | tools.py 追加参数（`--submit-only` 后）；dry_run 不带；回滚=`--postprocess none`；验证判据=1216×704+字幕+音轨+AAC |
| 2 | **S3**：取消后任务表残留（mark_cancelled 分层） | §3 | 小 | ☆1 次 | 取消链已修（定向中断+参数归一）；mark_cancelled 全仓 0 命中=待建；单测 mock task_watch 状态 |
| 0 | **P0 受控续接**（先于 S 序列） | §8（本书） | 小 | ☆1 次 | 目标驱动+上限 5+轮空熔断+尊重用户；修复"多段任务第一段成功后中断/失败重试后自熄" |
| 0.5 | **P1 事件驱动完成通知**（先于 S8；与 S8 复用任务状态） | §9（本书） | 中 | ☆1 次 | 监听脚本→模型（零轮询）；模型侧校验监听健康+超时分型；去重防重复注入 |
| 0.6 | **P1.5 参考语义修复**（用户首验发现·当前最高优先） | §10（本书） | 中 | ☆1 次×3 抽检 | tag 契约缺失=参考图被当首尾帧；ref_image_size 默认改 max；实施< P1
| 3 | **S8**：批量状态重写（queue_pids+决策树） | §8 | 中 | ☆1 次 | 前置=task_watch.poll_batch 缺 pathlib 修复已在场须确认；cancelled/never-queued 不可区分如实标注 |
| 4 | **S6**：男/女声+schema tts_voice/tts_font_size+SYSTEM 一句 | §6 | 小 | ☆1 次 | 引擎已预接通（VOICE_ALIASES）；tools 透传短名不映射；判据=argv 短名+tts_done 全名 |
| 5 | **S1**：gallery caption/可用性 | §1 | 小-中 | ☆（spark-only） | _asset_available=文件系统存在性（非 _known_shas）；第三改动点 :1411-1417 元组化+回退兜底 |
| 6 | **S4**：idea2prompts --segments-json | §4 | 小-中 | ☆LLM spark 本机 | 十八审前置：双向槽名对齐+0-based 统一+段数守卫；验证读落盘 manifest JSON |
| 7 | **S5**：selfcheck-llm | §5 | 小 | ☆1 次（授权+空闲） | 三处改动点（docstring/choices/分派）；复用 nap()+comfy_queue_idle；恢复窗口≥300s；--yes 一致化 |
| 8 | **S9**：dev.py sessions | §9 | 小 | ☆ | CHATS_DIR 双定义（实施时抽公共常量）；spark-only |
| 9 | **S10**：quality.py+quality-report | §10 | 小-中 | ☆?（只读探测） | probe_av 为主取值源（timeout=30 注意）；bytes 择一 |
| 10 | **S12**：一次性 token（跨会话精授权） | §12 | 中 | ☆1-2 次 | 定稿：grants.json 独立文件+原子写/魔术值 shared-<target>/对话确认轮签发（grant_refs）/轮末失效（turn_id）/--scope-all 保留登记收窄 |
| — | **S7**（最大工程） | §7 | 大 | ☆多轮 | 排在 S12 之后或独立窗口；主案=API 层注入（inject_media_refs）；7a 双注册；两级判据；官方文档三条一并实施 |
| — | S11 | §11 | — | — | 观察（不发规格） |
| — | S13/P 链 | §13 | — | — | 待魔搭 ID 闭合+逐项批注后动工（P2 ASR→P3 Wav2Lip 冒烟→P4→P5→P6） |

## 4. 统一验收判据（每项必须四件套）

1. **单测**：新增/修改代码的测试全绿（165 基线不回退）；新钩子/分支必须带测；
2. **☆真机**：真实提交链（或等价 Gradio API）→ 非空文本 → 真实产物（ffprobe 参数断言）→ 语音类需可辨析（听测/ASR）；
3. **文档**：spec 对应节"待做→已实施"、changelog 新节（记录证据行）、session-summary 批次、handoff 状态刷新；
4. **一致性**：`dev.py check`（三端 0 dirty）+ `dev.py docs`（新文档入索引）+ git 提交（sync 先于 commit）。

## 5. 资源与队列纪律（真机窗口）

- GPU：共享队列；**一意图一驱动**；提交即返回（默认 --submit-only），轮询不占生成；
- 每项 ★真机 = 提交+等待+取片 1 次（S5 额外 SGLang 冷启 1-3min ×1；S7 多段）；
- 空闲内存回收仅 `POST /free`（完整 body，勿手动重启 ComfyUI）；/object_info 只读不需窗口；
- **待授权项**（勿单方执行）：1920×1088+`--lora none` 原生探测（三合一定案）；S5 销毁性演练。
## 8. P0 受控续接（高优先级——先于 S 序列；2026-09-06 已实施）

**背景**：现场事故（2026-09-06 三次复现）——①多段分镜首段提交成功后 `should_continue` 因"已有 prompt_id→不续"一刀切，后续段无人接做；②失败重试轮中续接消息（"请继续完成当前任务"）不含关键词，判定自我熄灭；③模型反复陈述"现在提交"却不发起工具调用（通道缺口，前修已补）。
**方案（受控续接，非无脑放开）**：
- **目标驱动**：`should_continue` 增任务延续分支——提交类工具结果驱动：失败（错误/失败/找不到/被拒/校验失败）→ 续（修正重试，失败不占频控）；`call_comfyui` 成功（TASK_SUBMITTED/prompt_id）→ 续（查询取片/工作到完成）；`batch_submit` 成功（BATCH_MANIFEST）→ **不续**（监控接管，防空转）；
- **上限**：`MAX_AUTO_CONTINUE` 2→**5**（每用户轮；超出即停并提示用户确认）；
- **轮空熔断**：book-16 spin-stop（前 80 字符重复）保留；
- **尊重边界**：用户新消息/停止按钮/会话切换即刻终止（并发限 1 复用）；
- **防失忆**：续接消息附 `[上一步] <最后工具结果摘要 140 字>`；
- **防幻觉**：续接消息含"重试/继续需按真实工具结果；不得虚构提交结果"。
**实现（runs/agent/ui_app.py）**：run_turn 记录 `_last_tool=(fname,out[:180])`；should_continue 增 last_tool/last_tool_hint 参数与三态分支；MAX_AUTO_CONTINUE=5；续接消息带摘要+不虚构约束；`_last_tool=None` 初始化。scheduler.py（CLI 备用路径）同步=登记待办（低优先）。
**验证**：☆真机——多段分镜批量提交后自动续接查询/取片并总结；失败→修正重试自动续接；上限触发提示；用户新消息打断。**回滚**：恢复 should_continue 旧参数分支（MAX=2）+删除 _last_tool 记录。
**风险登记（回答"多次续接"的风险面）**：共享队列重复提交（同参数指纹已拦、变体需靠轮空/上限兜底）；ctx 漂移（上限 5 受限）；幻觉完成（续接消息防虚构约束+bool 校验）；用户控制（新消息即断）。

## 9. P1 事件驱动完成通知（监听→模型，零轮询）——2026-09-06 登记

**动机与边界**：现状=模型轮询（提交后多次 run_script 查进度；每轮消耗 LLM 轮次/上下文）或依赖 task_watch 的 UI 事件（状态条/done 提示**不注入模型**）。本任务=把"任务结果"作为**事件**推给模型会话，模型不再轮询；同时满足用户要求的三道约束：**监听脚本失败可校验、超时处理健全、不替代模型对工具真实性的校验**。

**设计**：
- **事件源（复用现有）**：task_watch._monitor_worker 已对 pending 任务查询完成/失败（轮询 ComfyUI 是脚本侧职责——**轮询从模型转移到监听脚本**）；在其上扩展"结果通知钩子"：任务完成/失败/超时 → 向会话注入一条 **user 角色消息**（如 `[任务完成] prompt_id=… 产物=outputs/video_N.mp4（分辨率/音轨/时长）…` / `[任务失败] …原因`）→ 若会话 idle 则触发下一轮（复用 send 注入路径）；模型收到即总结/继续（不再主动查）。
- **监听健康校验（用户约束 1）**：watcher 每事件/每 60s 写心跳（内存+时间戳）；结果通知前置校验：①watcher 心跳新鲜（<90s）②事件计数单调 ③注入前确认不是重复（cid+pid+事件序号去重）；**watcher 崩/心跳过期→ 注入"[监听异常] 结果通知可能丢失，请用查询工具确认"**（降级消息而非静默）。
- **超时分型（用户约束 2）**：四类——完成（ffprobe 校验）/失败（ComfyUI error）/队列超时（pending > 阈值如 30min → 告知仍排队，不取消）/生成超时（运行 > 上限如 2h → 告知"长时间未完成，请查询"）；每类有对应注入文案与后续建议（是否重试/取片）。
- **与回合生命周期对齐**：仅当会话无进行中回合（无 active turn）才注入（不打断模型输出）；stop_event/用户新消息到来→ 取消本任务的通知注入（用户已接管）；check_turn_valid 对齐（注入后的事件由 turn 机制自然承接）。
- **与轮询工具的兼容**：轮询工具（run_script 查询）保留——模型可主动查（如用户要求），但默认不再需要；**模型仍然校验监听消息真实性**（消息含真实 pid/路径，模型可再查证——不得仅凭消息声称产物存在）。
- **与 S8 的关系**：S8 是"脚本侧状态判定决策树"（history/queue 消歧）；P1 是"判定结果→通知模型"的最后一环——**先 S8 定判定、再 P1 接通知**（P1 登记在 S8 之前但实施依赖其判定；实施序=S8 then P1，或以 S8 的 queue_pids/history 为准）。
**实现（文件级，实施期细化）**：runs/agent/task_watch.py（事件源+心跳+通知钩子+去重）、runs/agent/ui_app.py（注入路径：send 同款 history 注入+触发 run_turn；idle 判定）、runs/agent/scheduler.py（CLI 路径同步）、可选 dev.py 子命令（watch status 心跳/队列概览）。
**验证（☆真机）**：①提交 1 段→模型**零工具轮询**自动收到"任务完成"消息并总结产物（记录消息注入时间/模型后续动作）；②手动 kill watcher（或注入假心跳过期）→ 收到"监听异常"降级消息且模型可查询确认；③超时场景=将 manifest 置 pending 超阈值（单测可模拟）→ 超时文案；④重复通知去重（同任务仅一次）；⑤用户新消息打断注入（不再发出）。
**风险/回滚**：注入消息与模型交互竞争（在注入前检查 active turn；“仅 idle 注入”为硬条件）；去重键=任务标识+事件类目；回滚=通知钩子开关（默认关，逐个任务启用），故障字典登记四类消息样板。工作量：中。

## 6. 回滚策略（引用 §15.4，要点）

- S2：`--postprocess none` 全局回退；S7：新增函数/注册不触碰现有模板，废除=删注册与开关；
- S3/S8：`--no-clean`/`--legacy` 开关；S12：无 grant 即无行为变化（独立 grants 文件）；
- 每项实施前记录**现状行为快照**（命令+输出），回滚后 diff 对照。

## 7. 执行记录模板（每项完成即填）

```
## K.#### S# 名称（日期）
实施：<文件级改动>；
测试：<新测试名/数量>；全套 <N> 例绿；
真机：<产品路径+ffprobe 参数+语音判定>；
文档：spec §# 已改"已实施"；changelog §X；session §Y；commit <hash>；
证据：<关键 grep/日志行>；
状态：✅ 完成 / 🔲 回滚（原因）。
## 10. P1.5 参考语义修复（tag 契约 + ref_image_size 保真）——2026-09-06 用户首验发现（当前最高优先）

**现象（用户首验 3 段 r2v 产物）**：每段都是"参考图=首帧+尾帧"（镜头1：首帧=客厅/尾帧=男主；镜头2：首帧=男主/尾帧=父亲；镜头3：首帧=父亲/尾帧=道具），中间帧仅"人物/道具"部分参考、**场景参考未发挥作用**（除首尾帧外）。
**归因（取证定案）**：3 段任务 workflow_api.json **`<Picture` tag 计数 = 0**——提示词未按官方契约引用参考图（官方："reference the inputs by tag, in the exact order they were connected…matching the reference tags precisely…tends to work best"）；无 tag 时模型把参考图按注入顺序解读为**首→尾关键帧**；且模板 `ref_image_size` 固定 `match`（官方：match=缩到生成分辨率=快但**弱身份保真**；max=2048px 短边=**强身份保真**、代价=参考 token 随每个采样步）。**非绑定/脚本 bug**（绑定此前取证正确）——归属提示词契约缺失（§7c/书-18 的参考 tag 规范未实施）。
**方案**：
- ① **提示词契约强制**（根治）：SYSTEM_MESSAGE（agent 提示词生成规则）与 idea2prompts 提示词模板强制：r2v 提示词必须含 `<Picture N>`（1-based=连接顺序，<Picture 1>=第一个连接参考）**且**固定语义句"参考图（场景/角色/道具）贯穿全片锁定，**不是首帧/尾帧**；每帧保持一致"；生成后**校验**（tag 数量==参考数，缺失即拒绝重生成/补 tag）；
- ② **ref_image_size 默认 max**（身份保真优先；速度代价登记：参考 token 随采样步，验证档亦 max 会略慢；提供 `--ref-image-size match` 可选与 params/CLI/capabilities 开关）；
- ③ **验证判据**：☆真机 3 段→每段抽 3 帧（首/中/尾）目检：人物身份/场景空间/道具外观**全程一致**（不再首尾帧化）；无 tag 契约时的"首尾帧化"登记为**已知限制**（用户侧临时缓解=提示词手工加 `<Picture N>`）。
**实现（实施期细化）**：runs/agent/scheduler.py（SYSTEM_MESSAGE 参考引用规则+校验）、runs/h3/idea2prompts.py（模板）、runs/h3_submit.py/params/capabilities（ref_image_size 开关+默认 max）、配置：模板 node 136 第 5 widget match→max（本地镜像）。
**回滚**：SYSTEM 语句与校验开关删除；ref_image_size 回 match；模板 widget 回滚。工作量：中。**实施序**：P1.5（当前最高优先，先于 P1/S2-P1a）。

**实施记录（2026-09-06，代码层✅ / ☆真机 3 段抽帧目检待验证）**：
- ✅ ① 契约强制：scheduler.py SYSTEM_MESSAGE（r2v tag 规则+贯穿句+生成后校验要求）；idea2prompts.py（build_messages 追加规则+_ref_contract_violation 存在性校验+违规重生成一次+仍违规拒写）；prompt_blueprints.json（global 规则 8+video_r2v/api_r2v extra）；**提交前硬校验**=h3_submit.py 按实际接线参考数 N 校验 <Picture 1..N> 齐全，缺失即 exit 3（含指引），开关 --no-check-ref-tags；贯穿句缺失=警告（措辞容错）。
- ✅ ② ref_image_size：params（GenParams/DEFAULTS= max/枚举校验）、CLI（h3_submit/h3_batch+manifest）、tools.py（call_comfyui/batch_submit 转发）、stage.apply_ref_image_size+build_template_workflow 接线、capabilities.json video_r2v（params.ref_image_size{default:max} + features.ref_tag_required）、**模板 node 136 第 5 widget→max**（本地镜像；参数覆写兜底，sync 回退无害）。
- ✅ ③ 单测：tests/test_ref_tag_contract.py 新增 21 例；全套 165 基线+顶层 unittest 56 例绿；consistency 问题 0。
- ⏳ ④ ☆真机验证（用户侧）：3 段 r2v×每段抽 3 帧（首/中/尾）目检=人物身份/场景空间/道具外观全程一致、无首尾帧化；用户侧临时缓解=提示词手工加 <Picture N>+贯穿句。