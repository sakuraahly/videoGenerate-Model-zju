# book-19 执行就绪计划书（Execution Readiness）

> 版本：v1.0 · 2026-09-06 · 前置：`docs/history/pending-tasks-implementation.md` 经 **19 轮审核定稿**（changelog §14-§29）；本件把"定稿规格"转成"可执行清单"——执行者在每项完成后按 §7 回写并更新状态列。
> 事实权威：START-HERE §2 索引 / session-summary / reference；仓库三端一致（win=github=spark，0 dirty），单测基线 **165 例**。
> 引用约定：`S#`=pending-tasks-implementation.md 的节号；`☆`=spark 真机路径（需队列空闲窗口）。

---

## 1. 执行总纲

**目标**：按推荐序把 S1-S13 待做项逐一落地，每项过"单测全绿 → ☆真机验收 → 文档回写 → dev.py sync+commit"闭环。

> ⚠️ **结构说明**：本文档=执行计划与验收长卷；**章节编号含历史轮次、非顺序**（§10-§16 为 2026-09-06 轮次追加，含 11/11b-11d/12/12b 变体）——当前进度以**文件头状态表（§1）**为准；每节标注日期；新内容末尾追加新节号。当前事实见 `docs/CURRENT-STATE.md`。
**红线（每项动工前重读）**：ComfyUI systemd 勿动（唯一动作=`POST /free` 完整 body）；共享队列取消/删除必须归属校验（已修复为定向中断）；共享模板只读、绑定用任务副本；模型下载走魔搭；中文经 ssh 一律临时脚本文件；单测从仓库根运行。
**执行者纪律**："已修正必 grep 落点"；新钩子/新分支必有单测；两条路径共用变量必须前置初始化；决策记录必须同步正文修改。

## 2. 打开门禁（前置条件状态表——动工前逐项确认，均不阻塞 S2-P1a）

| #   | 前置                                                                                                                                         | 状态                                          | 说明                                                                   |
| --- | -------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------- | ---------------------------------------------------------------------- |
| 1   | **S2-P1a**：agent 默认 --postprocess fast+合并单次编码链｜✅已实施（2026-09-06；含 job 持久化+resume 恢复补丁；增强产物判据=1216×704 已通过） | 三端一致+基线                                 | ✅ 已闭环（2026-09-06 现场检查，165 例）                                | dev.py check 0 问题 |
| 2   | Ref2VA 探测（S7 7a）                                                                                                                         | ✅ 已完成（九~十七审 all-spark 取证）          | 模板树权威=remote_workflows；节点/槽位/id>146 均已定案                 |
| 3   | 上传复用 upload_image                                                                                                                        | ✅ 服务端源码级确证                            | server.py 无类型校验/重传安全；curl .mp4 抽验可选                      |
| 4   | 768p 上限来源                                                                                                                                | ✅ 定案=加速 LoRA（非模型）                    | 原生 1080p 探测=1920×1088+`--lora none`（☆待授权队列窗口；不阻塞主链） |
| 5   | 模型真实 ID（魔搭：RIFE/SD-Inpaint/Wav2Lip+SF3D/FunASR/F5-TTS）                                                                              | ✅ 已闭合（2026-09-06；魔搭 API Code:200 验证） | 见 §13 表：F5-TTS/CosyVoice/SenseVoice/Paraformer/RIFE/SD-Inpainting；Wav2Lip 魔搭无官方→GitHub 权重；S13/P 链可开工          |
| 6   | config/pipeline.json（机器配置）                                                                                                             | ✅ win/spark 均 templates_dir=remote_workflows | S7a 双注册提醒已知                                                     |

## 3. 执行顺序与每项规格索引

| 序  | 任务                                                                                                   | 规格        | 工作量 | 真机需求           | 关键前提/陷阱                                                                                                                      |
| --- | ------------------------------------------------------------------------------------------------------ | ----------- | ------ | ------------------ | ---------------------------------------------------------------------------------------------------------------------------------- |
| 1   | **S2-P1a**：agent 默认 `--postprocess fast`+合并单次编码链                                             | §2          | 小-中  | ☆1 次              | tools.py 追加参数（`--submit-only` 后）；dry_run 不带；回滚=`--postprocess none`；验证判据=1216×704+字幕+音轨+AAC                  |
| 2   | **S3**：取消后任务表残留（mark_cancelled 分层）｜✅已实施（2026-09-06）                                 | §3          | 小     | ☆1 次              | 取消链已修（定向中断+参数归一）；mark_cancelled 全仓 0 命中=待建；单测 mock task_watch 状态                                        |
| 0   | **P0 受控续接**（先于 S 序列）                                                                         | §8（本书）  | 小     | ☆1 次              | 目标驱动+上限 5+轮空熔断+尊重用户；修复"多段任务第一段成功后中断/失败重试后自熄"                                                   |
| 0.5 | **P1 事件驱动完成通知**（先于 S8；与 S8 复用任务状态）                                                 | §9（本书）  | 中     | ☆1 次              | 监听脚本→模型（零轮询）；模型侧校验监听健康+超时分型；去重防重复注入                                                               |
| 0.6 | **P1.5 参考语义修复**（用户首验发现·当前最高优先）                                                     | §10（本书） | 中     | ☆1 次×3 抽检       | tag 契约缺失=参考图被当首尾帧；ref_image_size 默认改 max；实施< P1                                                                 |
| 3   | **S8**：批量状态重写（queue_pids+决策树）｜✅已实施（2026-09-06）                                       | §8          | 中     | ☆1 次              | 前置=task_watch.poll_batch 缺 pathlib 修复已在场须确认；cancelled/never-queued 不可区分如实标注                                    |
| 4   | **S6**：男/女声+schema tts_voice/tts_font_size+SYSTEM 一句｜✅已实施（2026-09-06；真机已验证通过） | §6          | 小     | ☆1 次              | 引擎已预接通（VOICE_ALIASES）；tools 透传短名不映射；判据=argv 短名+tts_done 全名                                                  |
| 5   | **S1**：gallery caption/可用性｜✅已实施（2026-09-06；spark-only 断言 PASS）                            | §1          | 小-中  | ☆（spark-only）    | _asset_available=文件系统存在性（非 _known_shas）；第三改动点 :1411-1417 元组化+回退兜底                                           |
| 6   | **S4**：idea2prompts --segments-json｜✅已实施（2026-09-06；登记：27B 分段遵循度弱）                    | §4          | 小-中  | ☆LLM spark 本机    | 十八审前置：双向槽名对齐+0-based 统一+段数守卫；验证读落盘 manifest JSON                                                           |
| 7   | **S5**：selfcheck-llm｜✅已实施（2026-09-06）；销毁性演练=待用户授权                                    | §5          | 小     | ☆1 次（授权+空闲） | 三处改动点（docstring/choices/分派）；复用 nap()+comfy_queue_idle；恢复窗口≥300s；--yes 一致化                                     |
| 8   | **S9**：dev.py sessions                                                                                | §9          | 小     | ☆                  | CHATS_DIR 双定义（实施时抽公共常量）；spark-only                                                                                   |
| 9   | **S10**：quality.py+quality-report｜✅已实施（2026-09-06；SSIM 复算一致）                          | §10         | 小-中  | ☆?（只读探测）     | probe_av 为主取值源（timeout 已对齐 60）；bytes 择一                                                                             |
| 10  | **S12**：一次性 token（跨会话精授权）｜✅已实施（2026-09-06；14 单测绿+CLI 冒烟；spark 真机验证=☆待队列窗口） | §12         | 中     | ☆1-2 次            | 定稿：grants.json 独立文件+原子写/魔术值 shared-<target>/对话确认轮签发（grant_refs）/轮末失效（turn_id）/--scope-all 保留登记收窄 |
| —   | **S7**（最大工程）｜✅ 已实施（2026-09-06；单测 8 绿+一级在线 PASS+**二级真机 PASS**：video_46.mp4 产物 608×352/124f+AAC；抽帧目检场景锁定+镜头推近；音频采纳听测=待用户/ASR） | §7          | 大     | ☆多轮              | 主案=API 层注入（inject_media_refs）；7a 双注册；两级判据；官方文档三条一并实施；audio 采纳听测判据=待人工/ASR（P 链）     |
| —   | S11                                                                                                    | §11         | —      | —                  | 观察（不发规格）                                                                                                                   |
| —   | S13/P 链                                                                                               | §13         | —      | —                  | 待魔搭 ID 闭合+逐项批注后动工（P2 ASR→P3 Wav2Lip 冒烟→P4→P5→P6）                                                                   |

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

**状态：✅ 已实施（2026-09-06，见 session §20.42/changelog §32）**——task_watch 原语+ui_app 常驻 watcher+注入复用 send；单测 10 例+165 绿；watcher 运行确认；注入分支为低概率场景（单测覆盖，登记待自然观察）。

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
- **☆真机验证（2026-09-06 完成，待用户确认）**：3 段 r2v（18s 分镜/360p/4 参考图）全部 success；一级证据=wired 4 槽/tags{1..4}/ref_image_size=max/persist 句；抽帧目检=身份/道具一致、无首尾帧化、seg2 尾帧场景漂移（模型行为，登记）、seg3 独白 10.2s>8s（字幕越出，待用户定夺）。
- **勘误（2026-09-06 收尾核查）**：用户首验 3 段实为 flf2v（首末帧转场）而非 r2v——原“无 tag 契约 → 首尾帧化”归因对 flf2v 不适用（flf2v 无 tag/无 ref_image_size；首尾帧=设计语义）；查 12 份历史真实 r2v 提交（09-02~09-05）全部 tags=[]+match——**r2v 通道契约缺失属实**，本 P1.5 修复有效命中。☆真机验证改走 r2v 3 段（用户已确认意图=参考贯穿全片）。
- ⏳ ④ ☆真机验证（用户侧）：3 段 r2v×每段抽 3 帧（首/中/尾）目检=人物身份/场景空间/道具外观全程一致、无首尾帧化；用户侧临时缓解=提示词手工加 <Picture N>+贯穿句。

## 11c. 甜点项登记：图片生成速率优化（2026-09-06 用户指示·未来计划）

**指示**：主要任务=视频生成做电影；图片/参考图生成（t2img/flux/refimage 等）的速率优化**作为甜点内容列入未来计划**（当前不做、不占主序列权重）。
**登记**：未来批次优先度=低；纳入 S2-P1b/P6（超分/品质链）同类升级批次时一并考虑（届时再列规格）。

## 11d. 自动续接断链登记（2026-09-06 用户反馈·后修复）

**现象（用户原话要点）**：提交任务后 [系统自动续接] 出现，但模型列表可用素材后要求用户提供创意——任务明明在生成中，模型却停止工作/丢失任务上下文（应自动补提示词、设计镜头、一气呵成 提交→查询→取回→汇报）。
**待查根因方向（修复前取证）**：① should_continue 在提交成功帧后未续（last_tool 判定与 TASK_SUBMITTED 提取）；② 续接轮 messages 上下文裁剪/丢失任务信息；③ 模型把素材列表轮误判为用户无创意（SYSTEM_MESSAGE 创意询问门限过宽）。
**修复计划（后置）**：取证会话档/日志→定位断点→修复+单测→真机复验。

## 14. S5 演练结果（2026-09-06 授权执行·**失败**）

**执行**：队列空闲守卫过（running 瞬时清零）→ nap（SGLang 已不在运行，跳过）→ wake ×3 档（0.25/0.20/0.15）全超时。
**恢复尝试**：手动 tmux 重启 0.50/0.40/0.30（spec off）全部 RuntimeError=Not enough GPU memory for hybrid state cache（total_rest_memory 恒负：-1.4~-7.3GB）。
**根因**：ComfyUI 当前 CUDA 池驻留 ~40GB（nvidia-smi compute apps 1672180=40.7GB；含 --reserve-vram 12+驻留模型栈），GB10 统一内存池不足以同时容纳 SGLang（需≥~49GB）。12:30 前 SGLang 可运行=当时 Comfy 占用更低。
**影响**：agent 的 LLM（SGLang 8000）当前 DOWN；ComfyUI/工具链正常。**恢复依赖**：ComfyUI 侧驻留释放（用户工作流结束/模型重载；ComfyUI systemd 纪律=不重启、不代为操作）。
**工具（用户提议整合）**：runs/agent/sglang_guard.py——自动监控+自动修复一体化守护（端口/v1/models 健康探测→ComfyUI 占用阈值判定→低占用自动拉起（mem=0.40/spec off/max_run=1，含引号修复）→验证→防抖 10min；once/loop 两模式；tmux guard 会话常驻；5 决策单测；日志 logs/sglang_guard.log。同期修复 start_sglang_coexist.sh MAX_RUN 引号 bug（echo 带 " 进值）。
**llm_mem 档位缺陷登记**：wake 降额档（0.25/0.20/0.15）实际无法满足 SGLang 最小需求（≥~0.40 且需 Comfy 空闲），自适应降额区间错误——修复项（档位下限/与 Comfy 共享预算检测，后续实施）。

## 12b. 产物对照说明（用户疑问登记 2026-09-06）

**问题**：用户在 ComfyUI 看到的是“裸视频”（无字幕/无人声）——原始生成产物。
**对照**：ComfyUI output/MiniMax_H3_*.mp4=模型原生产物（画面+原生音频）；项目 outputs/*_pp.mp4=后处理成品（2x 增强+字幕烧录+TTS 人声替换，由 h3_submit 完成钩子链生成，**不在 ComfyUI output/，在项目 outputs/**）。
**排障提示**：找“带字幕人声”成品一律去项目 outputs/（或 outputs/*_pp.mp4）；ComfyUI 目录=母版。

## 13. 本地化集成路线登记（2026-09-06 用户指示：集成度不足）

**用户认知**：原以为生成全部在 ComfyUI 工作流内完成；实际=拼接线（ComfyUI 生成 + 项目侧 ffmpeg/edge-tts/srt 后处理），集成度不够好。
**目标（登记/远期）**：人声、字幕**全部改用魔搭社区模型或现有小模型**本地处理：
① 人声：edge-tts（在线云 API）→ 本地 TTS（魔搭：F5-TTS/CosyVoice 等，见 S13/P 链待魔搭真实 ID 闭合项）；
② 字幕：SRT 生成与烧录本地化（当前 ffmpeg 本地已用；ASR/文本对齐可下沉魔搭 FunASR 等）；
③ 集成形态评估：ComfyUI 工作流内节点化（如 ComfyUI-TTS 节点）vs 引擎管线化（现 h3_submit 钩子链）——实施前评估取舍（登记，不预设）；**定案（2026-09-07 用户指示）**：走 ComfyUI 节点化——`comfy_nodes/h3_finalize/`（H3LocalTTS/H3Finalize/H3AsrCheck 三节点，部署 shell/deploy_h3_nodes.sh → custom_nodes，**ComfyUI 下次重启生效**；节点经独立 tts/asr venv subprocess 执行，避免污染 ComfyUI 环境）；
④ 现有链（edge-tts/ffmpeg）=过渡方案，保留直至替代就绪；与 S13/P 链（魔搭 ID 闭合）联动排期。
**P 链① 人声·F5-TTS 本地冒烟 PASS（2026-09-06）**：spark `~/ai/tts-venv`（f5-tts pip + torch；权重=魔搭 F5TTS_v1_Base/safetensors 1.35G + vocos-mel-24khz 54M（HF 直连不通，**经 hf-mirror.com 下载**；bigvgan vocoder 需 git submodule，pip 包不含→放弃，改 vocos 路线）；新工具 `runs/h3/tts_local_check.py`（--text/--ref-file/--ref-text/--output；自动探测权重路径）→ 中文句合成 CPU 53s/句、输出 24kHz wav，**ASR 回环验证=还原原句**（“欢迎使用本地语音合成系统这是摩达 f t t s 的中文冒烟测试”）→ 可辨析 ✓。**接入生产（2026-09-07 真机链 PASS）**：h3_submit `--tts-backend local`（+`--tts-mix-bed <音频>` 音效链底轨、`--asr-check` 回环验收）→ 真实任务 `a7432834`（t2v 360p/5s）产物 video_45：**TTS_OUT speech_s=3.58s srt=yes（本地 F5-TTS 后端）→ ASR_CHECK ASR_SCORE=1.000 ASR_MATCH=ok（SenseVoice 回环还原原句）**；混音直验 video_45_mix.mp4（TTS 主轨+老人声 -12dB 底轨，608×352/5.167s）——**P 链① 接入生产完成**（edge-tts 保留为默认过渡，`--tts-backend local` 显式切换；CPU 53s/句 为已知成本，GPU 分担=后续优化登记）。

**模型位置（2026-09-07 用户指示统一放 ComfyUI models）**：`~/ai/ComfyUI/models/f5-tts/{F5TTS_v1_Base,vocos}`（1.35G+54M）、`~/ai/ComfyUI/models/asr/sensevoice`（ONNX 量化 241M+config/am.mvn/bpe）；工具探测已改 ComfyUI models 优先（tts_local_check/asr_check 回落旧缓存）。
**ComfyUI 节点化成品链（2026-09-07 真机 PASS）**：`comfy_nodes/h3_finalize/`（H3LocalTTS/H3Finalize/H3AsrCheck；部署 shell/deploy_h3_nodes.sh → custom_nodes/h3_finalize，ComfyUI 下次重启生效——不自动重启服务纪律；节点经独立 tts-venv/asr-venv subprocess，不污染 ComfyUI）→ H3Finalize 直出 `video_45_final_mix.mp4`（本地 TTS+字幕+音轨替换+老人声 -12dB 混音；h264 5.167s+aac 5.111s）→ H3AsrCheck 回环 **ASR_SCORE=0.75 ok**。项目侧 h3_submit 钩子链（引擎管线化）保留并存。
**P 链① 接入生产（2026-09-07 真机链 PASS）**：h3_submit `--tts-backend local`（+`--tts-mix-bed`、`--asr-check`）→ 任务 a7432834：TTS_OUT 3.58s srt=yes（F5-TTS 本地）+ ASR_SCORE=1.000；edge-tts 保留默认过渡（`--tts-backend local` 显式切换；CPU 53s/句=已知成本，GPU 分担=登记后续）。
**S7 二级实测登记（2026-09-06）**：参考音频《老人缓慢讲述.mp3》被模型采纳（产物含人声音轨），但生成声为**快速讲述**、不复刻原声语速/音色——模型把参考音频当氛围语义参考而非音频复刻；如需精确复刻=音效链（独立音效轨+混音，§11 ②③ 同链）或参考音频上传为模板/后续 TTS 链（登记，不阻塞）。ASR 客观验收（P 链④）落地后自动判可辨析。

## 17. 2026-09-07 晚间 UI/Agent 异常清单（用户报告→根因→状态）

**异常 1：上下文 8192 超限（提交前必现；压缩提示后仍 8204/8195 vs 8192）**——
根因：SGLang ctx=8192 硬顶被系统性触碰（对话 + 工具往返）；且服务端 400 后"仅保留最新重试"的兜底
仅认 ModelServiceError 类型，裸 `ValueError: HTTP 400 {...}` 不命中 → 兜底未触发。
**状态：已修**——① ctx 放松至 16384（start_sglang_coexist.sh 默认 + ctx_budget/runtime_check 常量 +
  各文档口径）；② is_context_overflow_error 兼容裸 400 + 'context length'（ctx_budget.py）。

**异常 2：参考图 `up:0` 无法解析为有效路径（用户已上传图片）**——
根因：CallComfyUI images 参数描述宣传"池:序号如 up:0"写法，但引擎解析只认文件名/sha8 前缀——
描述与实现不一致；模型照描述填写必然 400/失败（本次靠回落文件名自愈）。
**状态：已修**——tools.py images 描述改为只推荐文件名/sha8 前缀 + 明示"不支持 up: 序号写法"。

**异常 3：模型自称可用 `--prompt-id` 查询（h3_submit.py 无此参数）**——
根因：RunScript 工具描述"使用边界"把 --prompt-id 列入 h3_submit 合法参数（实为 dev.py/golden_path.py
的参数）；queue_watch 文档同错。**状态：已修**——tools.py 参数白名单改正+明示"查询/续传=无参或 --resume"；
queue_watch docstring 更正；调度器 SYSTEM 工具铁律同步（禁止 --prompt-id）。

**异常 4：输入框 Enter 无效**——根因：Gradio Textbox lines=2 多行模式下 Enter=换行（占位符却写"Enter 发送"）。
**状态：已修**——输入框改 lines=1（Enter 发送；多行建议分次发送）。

**异常 5：长剧本（多镜头 integrated_multimodal_description）→ 模型响应超时**——
根因：长 prompt + 长工具输出 + 8192 顶格 → 响应超时/复读风险（投机解码 NextN 为已知复读风险源，默认 on）。
**状态：缓解**——ctx 放大至 16384（主解）；响应超时提示已有；后续如果仍复读→关闭投机解码（SGLANG_SPEC=off 登记）。

**异常 6：时长/清晰度决策权**（用户要求：模型按理解自设；用户给且合理→用；不合理→模型自控并说明）——
**状态：已修**——调度器 SYSTEM 参数行新增决策规则（默认自行判断，用户显式合理值采用，不合理则调整+说明）。

**待窗口登记**：SGLang 重启生效（ctx 16384）=队列空闲窗口（restart-llm 前置=队列空闲）；重启后需 runtime_check 全量 OK 复核。✅ 已完成（2026-09-07 11:03 强重启，ctx=16384 实测生效）。

## 18. 夜间优先策略（2026-09-07 用户指示）

- **原则**：1080p 及更高清晰度的图片/视频生成（含原生 1080p 探测、电影级 4x 超分叠加等重活）**一律改到夜间机器空闲时执行**；白天队列只跑验证档/交付档（≤768p）。
- **落地**：①本计划书 §4/§13 的 1080p 探测标记=夜间窗口；②调度器 SYSTEM 已加规则（用户要求 ≥1080p→告知夜间；当前上限 768p）；③Agent/引擎不再提交任何 1080p/4x 超分任务（用户取消 2026-09-07 拟执行的 1080p 探测）。
- **夜间清单**：原生 1080p 探测（1920×1088+无 LoRA）；Wav2Lip 口型冒烟（GPU 推理重活，同列夜间）；RIFE 插帧（渠道阻塞，夜间补下）；电影级 4x 超分叠加验证。

## 19. 夜间自动化机制（2026-09-07 实现）

- 需求：用户不想每晚手动对助手喊话；方案=**夜间任务队列**（`runs/agent/night_runner.py` + `config/night-tasks.json`），
  引擎类由 spark crontab（`0 22-23,0-6 * * *`）自动执行（限夜间窗口 22-08 北京 + ComfyUI 队列空闲）；
  对话类（口型/RIFE/4x）由 agent 在用户说"开始夜间任务"时经 `run_script(night_runner.py, --list)` 认领执行；
- Agent SYSTEM 已内建待做/夜间清单规则；单测 5 绿（状态合并/done/门控/入库模式）。
- 现场：cron 安装后次日 22:00 起自动运行 1080p 探测（单实例锁+门控防误跑）；日志 ~/night_runner.log。

## 20. 内存 shared 与模型超时（2026-09-07 用户报告→根因→修复）

**① "mem 110/122 却占 13G shared"**：
- 排查：/dev/shm 仅 720K、ipcs 无 SysV 段、当前 shared=187Mi——13G 为**生成期瞬时值**：
  H3 生成时 ComfyUI 视频编解码/统一内存缓冲在 tmpfs-shared 峰值出现（与 buff/cache 一起被 free 计入 shared 列）；
- **真正的隐患=swap 15G 用满 13G**（共存内存峰值遗留）：进程页被换出→LLM 推理触碰页面→延迟升高（实测长请求 55s/300tok 高于标称 23tok/s 的一部分原因）；
- 处置：登记观察（ComfyUI /free 腾内存可回落；如需清零 swap 需 root——留夜间巡检清单）；不阻塞主链。

**② 模型响应超时（长剧本 3 连 "? timed out"）未根治→现已根治**：
- 根因 A：客户端读超时 **120s**（ui_app._http_chat_once 默认 urllib timeout=120）——长剧本单轮 2-3 分钟必超；
- 根因 B：超时提示语无法区分（`? timed out`=urllib URLError 无 code）；无自动重试；
- **修复**：① 默认超时 120→**900s**；② 单轮超时**自动重试一次**（http 调用层+事件层双保险）；③ 提示语更明确；
  ④ 另有 ctx 8192→16384（上轮）与投机解码关闭（sglang restarted）作系统级缓解；单测 23 绿。
- 登记：LLM 吞吐受 swap/共存影响（夜间窗口更快）；长剧本若仍偶发超时→单轮拆分提示规则回归。
**魔搭真实 ID 闭合（2026-09-06，API Code:200 逐项验证）**：
- 人声-TTS：`AI-ModelScope/F5-TTS`、`iic/CosyVoice-300M`、`iic/CosyVoice2-0.5B`（推荐 2-0.5B 优先冒烟；edge-tts 过渡保留）；
- 字幕-ASR：`iic/SenseVoiceSmall`（短语音/多语/可辨析验收首选）、`iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch`（长文本简体）；
- 超分-插帧：`AI-ModelScope/RIFE`（插帧；**2026-09-07 冒烟=阻塞如实归档**：该 repo flownet.pkl=精简插值主干(160 键 block0..4+block_tea,无 encode.cnn3)——ComfyUI core RIFE 检测(需全量 IFNet)不兼容、hf-mirror 标准 RIFE-4x 未镜像 → 备选=GitHub 官方 Practical-RIFE 权重(项目侧运行)或待魔搭完整版；Real-ESRGAN 4x-UltraSharp 在 ComfyUI 模板链已有(utility-gan_upscaler,超分链=远期登记)）；
- 重绘：`AI-ModelScope/stable-diffusion-inpainting`（**2026-09-07 落地**：HF 单文件 checkpoint 已下架(runwayml 移库)→ 魔搭 diffusers 格式直用——ComfyUI 内置 `DiffusersLoader`(MODEL/CLIP/VAE)加载 `models/diffusers/stable-diffusion-inpainting/`；inpaint 链节点齐(InpaintModelConditioning/VAEEncodeForInpaint 等,1321 节点)；模板 `workflows/remote_workflows/sd_inpaint_fix.json`(LoadImage(原图)+LoadImageMask+DiffusersLoader+InpaintModelConditioning+KSampler+VAEDecode+ImageCompositeMasked+SaveImage,10 节点)；**冒烟 PASS(2026-09-07)**：真实提交 ac36a758(房间图 2848×1600+中央椭圆掩码)→产物 s13_inpaint_00001_.png(2848×1600,修复区自然、无破绽)——局部重绘链可用(修参考图乱码/瑕疵)）；
- 口型：Wav2Lip 魔搭无官方（iic/wav2lip、AI-ModelScope/Wav2Lip 均不存在）→ 用 GitHub 官方权重 + sglang-venv torch 推理（计划书 13 可行性路线标注）；SF3D 同理登记待查（不阻塞 P2/P3）。
**P 链④ ASR 冒烟（2026-09-06 落地）**：`iic/SenseVoiceSmall-onnx`(ONNX 量化 241MB，模型+tokenizer 缓存于 spark ~/.cache/modelscope) + funasr-onnx(独立 asr-venv，**未污染 ai/venv**——numpy 已恢复 2.5.2)；新工具 `runs/h3/asr_check.py`（ffmpeg 提取 16k wav→SenseVoiceSmall→ASR_TEXT/VERDICT）。对 S7 二级产物 video_46 音轨首测：`ASR_TEXT: you are and a seminal brings the blood on that is to serated it`（英文乱语）——**印证用户反馈④「语音不清晰、疑似胡言乱语」**（模型以参考媒体音轨为氛围参考生成旁白，节奏速率不受控=「很快的讲述声」同源）；**处置**：可辨析语音=项目 tts_text 链（已有，替代音轨）；参考媒体音频语义边界=已登记（§13 音频行）；本判据=「人力可复核的客观文本」而非自动 pass/fail（人工判读/后续语义模型）。
**P 链①b CosyVoice2 试点（2026-09-07 已完成）**：用户判定 F5-TTS(vocos 24k) 输出"电音/AI 感"；
换参考样本无法根治→换后端试点：spark `~/ai/cosy-venv`（torch 2.14+cu130 复用 tts-venv 符号链接+
补齐 numpy/onnxruntime/whisper/pyworld/lightning/Matcha-TTS/cudatoolkit 依赖链——**github.com:443 通道被墙**、
源码经 codeload/raw 通道落地登记；模型 `~/ai/CosyVoice2-0.5B`（魔搭 15 文件齐全）；
`inference_zero_shot` **CPU 成功**（GPU 队列忙时 CUDA OOM→CUDA_VISIBLE_DEVICES="" 兜底，加载+47s/句）：
同句 A/B（voice_demo_cosy_zh.mp3 vs voice_demo_official.mp3）+平和旁白句（voice_demo_cosy_zh2.mp3）
ASR 均还原；**待用户听测 → 通过后接入 h3_submit --tts-backend cosy（音色库/口型/1080p 仍远期）**。

## 12. 断点自动清理（2026-09-06 用户反馈：新任务总被断点拦）

**现象**：任务完成后 last_job.json 断点残留；agent 新任务每次被拦（需用户确认续传/强制新开）——影响正常使用。
**方案（已实施）**：task_watch.poll_single 在 completed/failed 终态时调用 clear_breakpoint_on_done（同 pid 才清；幂等；失败静默）——任务完成自动清断点，新任务不再被拦；3 单测+17 相关绿。
**边界**：断点仍承担“进行中/超时任务防重复提交”职责（未完成不清）；用户任务断点只在完成后自动清。

## 11b. UI 缺陷登记：历史会话下拉条目时间错误（2026-09-06 用户反馈）

**现象**：交互页面（7860）历史会话下拉列表条目时间=日期正确、小时/分钟错误（会话实际时间与显示不符）。
**处置**：登记后续再做（当前不修）；实施时查 ui_app._choices() 的时间来源与格式化（会话文件 mtime/首条消息时间/跨时区），
修复=统一以会话档首条消息的本地时间展示，并加单测；不阻塞 S2-P1a 及后续项。

## 11. 用户视频效果反馈登记（2026-09-06 用户验收 3 段 r2v 后）——升级工作流时一并解决，当前不重跑
**用户反馈（原话要点）**：① 字体模糊；② 音乐不够自然；③ 第一段脚步声奇怪、人物停止移动后仍存在；④ 人物语音不清晰、疑似胡言乱语；⑤ 第三段开头桌子上放的是钟、拿起来变成眼镜——多处分镜穿帮；建议之后升级工作流（超分等）时一并解决。
**登记（联动项）**：
- ① 字体/细节模糊 → **S2 超分（Real-ESRGAN 4x-UltraSharp，本地已有）+ 分辨率升级**（书-13 P 链）时一并；备注：当前 360p 文本渲染天然低清，交付档 768p 可部分缓解，但仍标注需超分。**超分链已落地（2026-09-07 PASS）**：ComfyUI API 链（UpscaleModelLoader(4x-UltraSharp.pth)+LoadVideo+GetVideoComponents+ImageUpscaleWithModel+CreateVideo(fps=24)+SaveVideo(format/codec)）对 video_45(608×352)→ **s13_upscale_00001_.mp4 2432×1408/24fps/h264 4x 超分**：抽帧目检画面细腻+**字幕文字清晰**（模板转换坑已登记：SaveVideo 需 format/codec、旧模板 widget 与新版不匹配→直接组 API）。
- ② 音乐不自然 → 模型原生配乐局限；**音乐链=参考音频/曲库 + mix_tracks 混音（-12dB 底轨）**，S7 参考音频能力落地时一并。
- ③ 脚步声奇怪/停止后仍在 → 模型原生音频语义与时长不可控；**音效链（独立音效轨+混音）**，与 ② 同链。**音效链工具已落地（2026-09-07）**：`runs/h3/sfx_mix.py`——原音轨(0dB)+音乐底轨(默认-12dB,淡入淡出 3s)+分段音效事件(开始秒:文件:dB,adelay)三路 amix(normalize=0)+loudnorm；冒烟：video_45(旁白)+男声配乐 → video_49_sfx.mp4(5.157s AAC)与 events 分支(1.2s:-9dB)均 PASS。
- ④ 语音不清晰/疑似胡言乱语 → 英文台词 TTS（Aria）+ seg3 独白 10.2s>8s 已知；**ASR 客观验收（FunASR/魔搭，P 链④）**落地后自动判可辨析；台词规范/语速或分句重合成在 TTS 升级链。
- ⑤ 钟→眼镜穿帮 → 参考图含客厅红色时钟+道具眼镜，模型在道具序列上混淆；**参考语义边界登记**：提示词需对道具变换点显式描述（这属于 P1.5 同类参考语义问题的表现面），后续参考语义增强时一并（不得作为本次回滚理由）。
**处置**：用户指示当前不重跑；全部登记为升级工作流（书-13/S2/S7/P 链）联动项；本次 3 段产物保留为基线（win outputs video_39/40/41）。
## 15. S12 实施记录（2026-09-06）

**实现**（按 pending-tasks §12 十三审定稿逐条落地）：
- ① 存放：`runs/h3/refimage.py` 新增 `grant <target> <turn_id> [--src] [--ttl]` + `grant_issue/grant_check/cmd_grant`（`<cid>.grants.json` 独立文件，tmp+replace 原子写；字段 {target_cid, src_cid, turn_id, expires, used}；`grants_dir()` 与 session_cleanup.CHATS_DIR 同源）；
- ② 签发者：`runs/agent/tools.py` 新增白名单工具 `grant_refs(target, reason)`——仅当当前轮用户消息命中授权启发式（允许/可以/同意…+使用动词+目标指向；否定/疑问句拒发；弱在环，audit 兜底）才放行；上下文=ui_app 每轮注入 CURRENT_TURN_ID/CURRENT_USER_TEXT；
- ③ 接口：`list --session shared-<target>`（魔术值复用，无新 flag；cmd_list 共享分支=校验授权→按 target 过滤；缺失/过期/轮末失效三型提示+“勿写 meta.json 会被覆写”排障提示）；提示语反引导修正（--scope-all 文案改为指向 shared-<cid> 精授权）；hint-recent 显示完整 cid（供授权用）；
- ④ 宽路径：--scope-all/session=all 保留但工具描述+SYSTEM_MESSAGE 优先引导 shared-<target>（暴露面未收窄=登记）；
- ⑤ 重试交互：一次性=轮末失效（turn_id 校验；一轮内重复读安全）；
- 会话清理：session_cleanup clean 随 jsonl/meta 删 `<cid>.grants.json`；
- 系统提示：scheduler SYSTEM_MESSAGE 素材边界②落地（线索→请授权→grant_refs→shared-<cid>）；TOOL_NAMES/_TOOL_LIMITS/_TOOL_NAMES/_wrap_call 四注册点齐。
**验证**：14 单测（tests/test_s12_grant.py：原子写/轮末/过期/缺失/无轮/启发式正反/共享分支过滤与拒绝/随会话删）+ 全套 251 绿；CLI 冒烟（grant→list 共享过滤）通过；☆真机（agent 真实轮：授权→签发→list shared）待队列窗口。
**剩余登记**：① grants 文件属纯磁盘态，agent 重启后 turn_id 归零→旧授权自动失效（fail-closed，符合预期）；② 弱在环启发式可被绕过（audit 留痕；UI 瞬态确认弹窗=未来增强）；③ --scope-all 暴露面收窄=另立项。
## 16. S7 实施记录（2026-09-06；7a/7b/7c 已实施，**二级真机 2026-09-06 已 PASS**（video_46 608×352/124f，参考视频+参考音频采纳；抽帧目检场景锁定+推近运镜；音频采纳判据=待用户/ASR——P 链④ 已落地））

- **7a 登记（十九审定稿：扩展现有 video_r2v，不新建 stage）**：capabilities video_r2v 增 slots.videos=[reference×3]、slots.audios=[reference×3]、features.reference_videos=true、params.reference_media note；object_info 在线复核四节点全绿（ref_videos/ref_video_audios/ref_audios 均 COMFY_AUTOGROW_V3、prefix=ref_video_/ref_video_audio_/ref_audio_、max=3、子输入 IMAGE/AUDIO；LoadVideo file/LoadAudio audio 均 COMBO+input 根；GetVideoComponents 输出 images/audio）；workflow_registry add_local 扩展 slots=/features= kw；template_health 设计 B 分型（videos/audios 不数模板行；仅复核注入目标前缀节点存在）+ 注入前缀取 inject_spec.class_prefix；pipeline.json 无需新 stage（r2v 已存在，templates_dir 已确认）。
- **7b 引擎接线（主案=API 层注入）**：stage.py `inject_media_refs(wf, video_names, audio_names)`——LoadVideo(file)→GetVideoComponents(video) 拆帧/拆声，槽位键 `ref_videos.ref_video_i`=[gvc,0]、`ref_video_audios.ref_video_audio_i`=[gvc,1]、`ref_audios.ref_audio_j`=[la,0]；注入 id=数字串且 > 现有 max id（避开 apply_lora 字符串 id 脆弱史）；守卫=目标节点缺失/视频>3/音频>3 抛 ParamError；h3_submit `--videos/--audios`（append）+ 上传复用 client.upload_image（落 input/ 根）+ 引擎层 tag 契约校验（--no-check-media-tags 降级开关）+ job 持久化/resume 恢复；dry-run 仅打印计划。
- **7c 工具/提示词**：tools CallComfyUI schema 增 videos/audios（逗号分隔；≤3；仅 r2v 生效）+ 拼装前双通道硬约束（<Video N>/<Audio N> tag 集合==列表索引集合 {1..N}，不一致拒提交；prompt 缺省时由引擎层校验兜底）；SYSTEM_MESSAGE 增参考媒体 tag 规范（videos/audios 顺序一一对应+驱动镜头显式说明）；prompts.py 增 media_tag_set/missing_media_tags（仿 Picture 契约）。
- **验证**：8 单测（tests/test_s7_media.py）+ 全套 249 绿；**一级（在线）PASS**——spark 真实 convert_ui_file（20 节点/目标 136）+ inject_media_refs（5 节点）断言槽位键/GVC→LoadVideo 链全过；**二级真机（2026-09-06 通过，queue_watch 复检后入队）**：r2v 360p/5s/ref2v_4step + 客厅参考图×2（模板预置 2 槽）+ 分镜视频-#1.mp4 + 老人缓慢讲述.mp3 → TASK_SUBMITTED df684e84… → h3_submit --resume 轮询 → success（608×352/24fps/124f/5.167s + AAC 5.167s/32kHz/2ch）；抽帧目检：场景锁定（沙发/窗/植物与参考图一致）+ 0.5s→4.5s 推近运镜（参考视频驱动采纳）；**音频采纳听测判据=待用户收听/ASR（P 链④）**——产物 win outputs/video_46.mp4。


