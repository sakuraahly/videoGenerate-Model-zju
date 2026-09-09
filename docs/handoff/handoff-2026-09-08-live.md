# Handoff 2026-09-08（Live）

> 当日交接；事实权威=docs/CURRENT-STATE.md；历史入口=docs/history；计划书=docs/planbook/book-19-execution-ready.md。
> 双端基线：Windows 主库 `9573eac`（已推 GitHub sakuraahly/videoGenerate-Model-zju）；spark `…`（同批同步）；agent `AGENT_VERSION`=重启后最新提交。

## 一、今日完成（2026-09-08）
1. **口型质量全链路修复**（用户多轮验收驱动）：音频轨截断系列根因（amix duration=first / dropout_transition=2 / 面源短于台词）→ 终版=**concat 顺序拼接**（台词完整+0.52s 静音+旁白）+ **人脸补帧到台词全长**（FACE_PAD）——ASR 全句含末词；
2. **无框方案**（用户'方框更明显'）：链条 `--face-restore`=W2L 后**整脸 GFPGAN 重渲染**（自适应边距+泊松）吸收贴皮框 → **video_79 验收通过**；修复 face_restore mux 漏音轨 bug；
3. **真实台词链 agent 化**：`runs/h3/lipsync_chain.py`（TTS→Wav2Lip→字幕→旁白错开→ASR）+ **Qwen 自主可调**（agent venv 自动重投递 tts-venv；--video 自动选人脸源+预筛+无脸段裁剪）；agent SYSTEM 内建该能力（无需'读文档'）；
4. **输出边界**：面向用户回复禁绝对路径/系统信息；链输出脱敏（文件名+相对说法）；
5. **S12 智能性**：轮末失效→TTL 时间窗（3600s 跨轮有效）+ 短确认级联 + UI 预览池即时刷新（含共享授权；修 `_pool_update` gr 名缺失全局错误）；S12 真机轮 PASS（授权→签发→4 素材列出）；
6. **ComfyUI 兼容**：核心 RIFE 打通（flownet.pkl→frame_interpolation/flownet.pth）+ 一体模板升级（gen→RIFE 2x 48fps→H3FaceRestore→H3Finalize(keep)→H3AsrCheck，0397f564 全链 PASS）+ GUI 模板 `video_minimax_h3_r2v_restore_finalize.json`；
7. **keep 语义**（角色原声优先）：attach/节点/引擎 audio_mode=keep 默认；台词字幕=ASR/文本；旁白=垫轨（不影响角色话语）；
8. **S12 UI 时间修复**：历史列表强制北京时间 24h（原 UTC 慢 8h）；
9. **魔搭创空间目标入库**：调研完成+分层设计（M1 静态版/M2 远程调度/M3 单点模型）+ 文档（guides/studio-porting.md）+ skill 卡（skills/studio-packaging.md）+ 计划书 §15f（未动工）；
10. **清理/纪律**：重启脚本装队列硬门禁（非空 ABORT——今日事故 8225e9fa 打断已登记）；temp/ 入库污染清理+gitignore；lipsync 链 cwd 修正。

## 二、服务/系统状态
- spark 服务（tmux）：comfy(8188, 队列空闲, 节点含 H3FaceRestore/audio_mode 参数)、agent(7860, AGENT_VERSION=最新)、sglang(8000, ctx16384)、guard、supervisor——**全部正常**；
- 引擎资产：tts-venv（torch2.14+cv2+librosa+onnxruntime）、cosy-venv、asr-venv、wav2lip（代码+gan/s3fd 权重）、gfpgan（GFPGANv1.4.onnx）、rife（Practical-RIFE+flownet.pkl/comfy pth 双路径）；
- 依赖渠道结论：hf-mirror=Windows 中转 ✅；modelscope ✅；pypi=清华源 ✅；codeload/raw github ✅。

## 三、下一步工作（=完善项目功能，按优先级）
### P1（近期，自主可干）
1. **7860 页面结果区**（§15d）：会话产物目录（VIDEOGEN_SESSION_CID env → logs/agent_chats/<cid>/outputs/）+ gr.Video/gr.File 组件（预览+下载）+ 发送/加载刷新 —— 用户直接下载成片；
2. **双声轨 ASR 验真改进**（小项）：台词时间窗（0→line_dur）单独 ASR 评分（报 line-score + narration 存在性双指标）；
3. **LivePortrait/EchoMimic 无框路线**（§15e，镜像有货）：下载（Windows 中转）→ 整脸原生重生成（音频驱动）→ 接入 lipsync 链（替代贴皮）——目标=彻底无框；夜间窗口动工；
4. **studio M1**（创空间静态展示版）：app.py（Gradio 片墙+流程+演示表单）+ config.yaml + requirements —— 用户确认后动工。
### P2（需用户输入/夜间）
5. S12 剩余：--scope-all 暴露面收窄（登记）；
6. 夜间窗口：1080p×4x 终极档（7680×4352）、RIFE 在正式出片的应用、夜 queue 巡检；
7. museTalk/VideoReTalking 远期（§15b）；1080p 素材直出片流程复盘。
### P3（观察）
8. 创空间 M2（远程调度，需出网实测）；免费 GPU 活动跟进→M3。

## 四、验收样本索引（Windows outputs\）
video_56/57（通用链/口型基础）、video_58（1080p 探测）、video_60（48fps 口型）、video_62（GFPGAN v1 修复）、video_64（羽化版）、video_66（泊松 v3）、video_68（v4 宽边距）、video_69（v5 自适应）、video_70（keep 原声）、video_71（ComfyUI 全链）、video_72（keep 演示）、video_73（真台词初版）、video_74/75/76（错开/修复/台词完整）、video_77-79（终版：**video_79=current 最佳**：无框+完整台词+旁白错开）。

## 五、纪律/红线复述
- 队列门禁后重启=安全；**不动 ComfyUI 需先 /tmp/restart_comfy2.sh（自带门禁）**；
- 面向用户输出=零路径；agent 边界=只做制作相关指令（无关拒绝）；
- 双端同步+文档闭环（skills/dev-workflow）；产物命名规范（lipsync_<ts>_<前4字>.mp4）。

## 六、夜间追加：P1 页面结果区 + ASR 双指标（2026-09-08 晚，代码级完成；spark 未重启）

**做什么**（planbook §15d item 2/3 + 小项）：用户'找不到结果在哪里'——页面可预览/下载本会话成片；ASR 混判改双轨。

**1. 协议模块**：`runs/h3/session_outputs.py`——`VIDEOGEN_SESSION_CID` env → `logs/agent_chats/<cid>/outputs/`；`place_output`（复制+刷新 mtime+修剪保留最近 10）+ `session_videos/session_files`（最新在前）。
**2. run_script env 注入**：`tools.py RunScript` CURRENT_SESSION 非空 → 注入 `VIDEOGEN_SESSION_CID`（链侧 `os.environ` 读取）。
**3. 链落盘**：`lipsync_chain.py` 终版产物复制到会话目录；命名 = `lipsync_<YYYYmmdd_HHMMSS>_<台词前4字>.mp4`（原 HHMMSS 升级全时间戳防跨日重名）；脱敏打印 `SESSION_OUT: logs/agent_chats/<cid>/outputs/<name>…`。
**4. UI 结果区**：`ui_app.py`——gallery 下 `gr.Video`（预览最新）+ `gr.File`（全部下载）；send 改包装器（_send_impl + 逐 yield 追加 `_results_update(cid)`，send_out/new_out 各增 2 输出位）；加载历史会话同步刷新；空态=组件 label『暂无结果』；launch allowed_paths 增 `CHATS_DIR`。
**5. ASR 双指标**：`asr_check.py` 增 `--start/--dur` 时间窗（ffmpeg 裁剪 → SameVoice 验真）；链 `--asr-check` = 台词窗 [0, line_dur+0.3] 报 `LINE_ASR/LINE_SCORE/LINE_MATCH` + 旁白窗 [line_dur+0.45, +nar_dur+0.4] 报 `NARRATION_ASR/NARRATION_SCORE`（非重叠，不再混判）。

**证据**：`py -3.13 -m pytest runs/h3/tests tests -q` → **337 passed / 1 skipped**（含新增 test_session_outputs.py 6 例）；`consistency_check` 问题 0；ui_app 结果区 glue 冒烟（假 gradio 桩；空态/有产物两分支）过；附修一处**预存**测试失败（test_upscale_arg tts_backend 期望 local→实际默认 cosy，2026-09-07 定案后的索引滞后）。

**未做/下一步**：spark 侧 `runs/sync_to_spark.py` 同步 + **重启 agent（tmux `agent`；重启=授权项）**；然后真机验收=页面预览可播/下载可存（§15d item 4）；剩 P1：LivePortrait/EchoMimic 无框路线（§15e 夜间窗口）、studio M1（等确认）；P2 S12 --scope-all 收窄、1080p×4x 终极档、RIFE 正式出片。

## 七、夜间追加 2：P1.3 EchoMimic 无框路线启动（2026-09-08 晚，用户授权重启 agent 后）

**Agent 重启 ✅**：`svc_main.py restart-agent` 后版本指纹 `7a8df97`（spark 本地 commit），7860 页面已含结果区组件（send 输出 10 位：…chatbot/status/note/hist_dd/cid/hist/gallery/box/res_video/res_files）+ 结果区文案；§15d item 4 待用户页面点验（预览可播/下载可存）。过程记录：首版 send 包装缩进误嵌 `_send_impl`（run_app 作用域无 send → NameError，页面启动即崩）→ 修复 commit `4b588bb`（Windows）/ `7a8df97`（spark）→ 重启验证通过。教训：涉及嵌套函数/闭包改动必须 spark 真机启动验证（本地起不来界面）。

**P1.3 选型与启动**：**选型=EchoMimic**（音频驱动+加速版；MuseTalk 因 mmcv/mmpose+Google Drive 权重 ARM64 高风险列为备选，详见 planbook §15e ⑤）。货源=ModelScope 全量镜像（spark 直连）；最小集 ≈12.3GB；代码已落 `~/ai/echomimic`（codeload）；依赖安装中（tts-venv：diffusers 0.24/transformers/moviepy/av/facenet_pytorch/modelscope 等；torch 2.14+cu130 超其 ≤2.2.2 上限待兼容验证）；集成脚本 `runs/h3/echomimic_talk.py` 已写（参考帧→同口径裁切→重渲染→seamlessClone 回贴→mux 台词音轨）。**待夜间窗口（22:00+，队列空闲门槛）**：重量级 W=512 fp16 冒烟（嘴型同步+纹理+无框目检），通过后接入 lipsync 链（--talking-backend echomimic 替代贴皮段）。

## 八、夜间追加 3：用户四联问题修复（2026-09-08 21:00-21:20，agent 重启后首轮真实反馈驱动）

**用户反馈**（任务：母亲卧床/父亲悲痛/5s/720p）：①模型提交后直接等待输入（无自动续接）②模型没用上传的参考图 ③网页没自动传回视频 ④结果文件显示为空。

**根因链（已取证）**：①④=模型转述用**全角冒号**「prompt_id：e0099beb-…」→ `extract_prompt_ids` 旧正则只认半角 `prompt_id:` → **任务未登记进任务表**（session_state tasks=[]，会话 jsonl 仅 1 轮）→ watcher 每 15s tick 有 cid 无任务 → 永不注入「完成」通知（=①、③：不 resume/不取回/无消息）→ 结果区无刷新事件（④ 且普通生成本来就不写会话结果区——原实现只覆盖 lipsync 链）。②=模型本轮未调用 list_references 直接 t2v（agent 日志工具调用计数 0；SYSTEM 词表已有素材规则但模型未执行）。

**修复（Windows 3e78e23 / spark baa31ff，agent 已重启生效，测试 177 绿）**：①`extract_prompt_ids` 支持 `[：:]` 全角+半角，且文本含「TASK_SUBMITTED/已提交」时兜底取首个 UUID（新单测 6 例）；②`h3_submit.py` 新增 `_session_place`：产物（LOCAL_OUTPUT/POSTPROCESS_OUT/TTS_OUT/MIX_OUT）在 VIDEOGEN_SESSION_CID 存在时落 `logs/agent_chats/<cid>/outputs/` + 打印 SESSION_OUT（普通生成入结果区）；③send 注入素材提示：本会话素材池有图且用户未提及时附加一行「人物/场景一致性请 list_references 按 r2v+<Picture N> 契约使用」（参考图未用的行为修正，观察下轮）；④原任务补救：`VIDEOGEN_SESSION_CID=20260908_124614_0863 h3_submit.py --resume e0099beb-…` → LOCAL_OUTPUT video_458.mp4 + POSTPROCESS_OUT video_458_pp.mp4（2560×1472/5.17s/aac）+ 两 SESSION_OUT 入会话结果区；抽帧目检（2s）=母亲病床+父亲悲痛注视，场景契合；Windows 交付 `outputs/video_80_母亲病床.mp4`。

**遗留观察**：①用户页面需「加载所选历史会话」触发结果区刷新（无事件源的已完成任务不自动弹）；②同步注意 spark-local 直跑编号独立（video_458）≠ Windows 目录编号（video_80），交付以 Windows 命名为准；③P1.3 EchoMimic 冒烟任务 22:00 自动执行中，互不影响。

## 九、夜间追加 4：加载历史会话续接——假 id 真相与四修（2026-09-08 21:20-22:00）

**用户反馈**（加载 0863 会话后「重新生成一遍」）：①上传状态变“尚未为本会话上传素材” ②ComfyUI 找不到模型回复的 prompt_id：4f8b1c2a… ③又是等待输入态 ④模型不该承诺“完成后我会取回…”。

**真相（取证）**：模型**确实提交了 r2v**——21:21:07 `run_20260908_132107_630.log` `submitted stage=r2v prompt_id=ac88b2cb-… imgs=母亲,父亲,卧室 720p/5s`（job `h3_20260908_132107_723`，ComfyUI 队列 running）；但**回复里编造了假 id 4f8b1c2a**（history 空）→ 登记走了假 id → watcher poll failed “任务不存在”→ 真实任务无人监控/取回/刷新。①=旧 `_load` 硬编码 UP_IDLE；④=输出纪律漏洞。

**修复（Windows 3c69880/ffcb017；spark bc4e7ac/219500d，agent 重启生效，测试 343 绿）**：①提交真实性硬校验——声称已提交但本轮无提交类工具调用且工具输出无 TASK_SUBMITTED → 本轮作废+提示（防纯虚构）；②**任务登记以工具输出真实 id 优先**（模型转述 id 不可信；合并去重）；③`_load` 上传状态真实化（素材池 N 项 pill）；④SYSTEM：提交回复只写「已提交（任务 id:…）」+一行参数，禁「我会取回/完成后…」承诺句。

**真实任务补救**：`ac88b2cb` resume 完成（本地无参重跑+env）→ `MiniMax_H3_00194_.mp4`（1280×736/5.17s/24fps）→ outputs/video_460.mp4 + SESSION_OUT（会话结果区 video_460.mp4）+ Windows 交付 `outputs/video_81_母亲病床_v2.mp4`（抽帧 2.2s 目检：绿衣父亲床侧握母亲手+监护仪/吊瓶/夜景窗=参考一致性✅）。

## 十、夜间追加 5：任务书扫描 + S12 收窄 + M1 动工（2026-09-08 21:50-22:10，用户确认 M1）

**任务书扫描**：planbook §3 全部 S 项已闭环；剩余=handoff P1(③冒烟 22:00 自动/④M1)/P2/P3。
**P2-⑤ 完成**：S12 `--scope-all` 暴露面收窄（§15 登记项）——`refimage.authorized_all_text`（全部/所有+素材/会话/历史；否定/疑问即拒）；tools 层未授权即拒（原=警告+放行），CLI 无上下文亦拒+调试提示；S12 测 16 绿/全量 345 绿；Windows a4ddf64 / spark 同步+agent 重启生效。
**P2-⑥ 登记**：夜间任务 `nt-hd-4x-ultimate`（1920×1088 无 LoRA 20 步 + --upscale 4x→7680×4352 终极档，单命令提交即等待）。
**P2-⑦ 完成**：1080p 直出片流程复盘 → planbook §15g（全链已通无阻塞；编号口径=spark-local video_4xx≠Windows video_N，交付以 Windows 命名为准；≥768p 夜间排产）。
**P1-④ M1 动工（用户确认）**：`studio/` 创空间项目根全套——app.py（Gradio 配置驱动：介绍/6 样片墙/五步流程/演示表单→结果卡+风格样片）、config.yaml（sdk gradio 4.44+展示元数据）、requirements.txt、README.md、assets/（12 文件 ≈1.2MB；样片经 spark ffmpeg 压缩 640w/CRF28 + 封面）。**证据**：本地 Gradio 6.26 启动→HTTP 200→/config=53 组件/13 媒体/1 表单依赖。**待用户 token 发布创空间**+M1 验收；M2 待出网实测。
**夜间窗口**：22:00 自动执行 nt-echomimic-smoke + nt-hd-4x-ultimate（队列空闲门槛）——结果下轮汇报。

## 十一、夜间追加 6：M1 发布创空间完成（2026-09-08 22:00+，用户给 token 一次性推送）

**发布**：`wumingyong0/Automated_video_generation`——匿名 clone（初始模板）→ 铺入 studio/ 全套（app.py/config.yaml/requirements.txt/assets 12 文件≈1.2MB/README 改造为创空间卡片 front matter：domain=multi-modal/tags/license Apache2.0）→ 本地 commit `bda7c3b` → **token 环境变量一次性 push**（`4df4f44..bda7c3b`，ModelScope Validation passed checked 1 commit 1011ms）→ `ls-remote` 远端=bda7c3b ✅。**token 未落盘/未入库**（仅本次命令环境变量；用户对话提供）。

**M1 验收 ✅ 通过（2026-09-08 深夜，用户确认）**：空间页「运行中」，应用内嵌正常——片墙可播+演示表单可用（用户原话：'是运行中,确实都有,很正常'）。入口=https://www.modelscope.cn/studios/wumingyong0/Automated_video_generation（Gradio 应用内嵌于空间页；`.modelscope.space` 独立域名仅'新标签打开'时分配，未分配≠失败——探测 000 属正常）。

**夜间任务（自动推进中）**：nt-hd-4x-ultimate——1080p 原生已出（outputs/video_461.mp4，1920×1088/5.17s ✅），**4x 超分进行中**（RealESRGAN 4x，GPU 队列处理）→ 待 7680×4352 落盘后收尾；nt-echomimic-smoke——首跑 EXIT=5 已修复（阈值 0.8→0.5+参考帧多候选，Windows 4271147/spark 已同步+状态重置 pending），**等队列空闲自动重跑**。

## 十二、夜间追加 7：参考视频测试+长片 agent 自主任务+遗留扫描（23:00-23:30）

**用户新指令**：①用 ComfyUI 别人的视频做参考生成指定内容（S7 videos 真机测试）②夜间时间充足做长片（主题=我定，其余 agent 自主调用工具）③扫描计划书可做遗留。

**①登记 nt-ref-video-test**：参考视频=MiniMax_H3_00188_.mp4（他人产物，1216×672 手部装钞票特写；抽帧目检内容确证）；指定内容=「父亲在病房床边把钞票装入信封」（r2v + 父亲.png + `--videos 00188` + `<Video 1>` 契约句：hand motion/framing guided by Video 1）；预期=动作/特写镜头由参考视频驱动、人物按参考图锁定。

**②长片《站台上的灯》已交给 agent（Gradio API 注入 send，event 6320b681）**：8 段父子深夜车站告别短片（①空站台长椅 ②父亲拖箱入画 ③列车头灯扫铁轨 ④车厢窗景 ⑤父子对视（此段真台词链 lip-sync，agent 自主设计台词 yunxi+ASR）⑥列车启动手扶车窗 ⑦雾中空站台 ⑧黎明蓝调进站）；指令=agent 自主分镜/逐段提交/第 5 段成品链/汇总剧本+产物清单。证据=run_20260908_151227_212.log agent-llm start→list_references 已调用（自主动工）。**agent 提交任务走 ComfyUI FIFO，与夜间 engine 任务自然排队**。

**③遗留扫描+闭合**：book-13-backlog（已归档册）扫描——**✅已闭合 book-07 遗留**：`_SCRIPT_TIMEOUT` 120→600 对齐 h3_batch `--timeout`（原 100→600；多段 status 查询曾被 120s 误杀；Windows bf89712=3 文件+code-fact-registry 更新）；仍在池观察（不阻塞）：§3.5 h3_batch 轮询 O(1) 重构（book-07，中风险）、§3.4 六工具描述注册表派生（随 book-12，大改）、§3.2 图片解析收敛（标记不建议近期）、nap()/supervisor 语义冲突（§book-13#16，涉服务侧）、book-12 状态复核（描述派生是否随册完成，下一步核）。

**兼容说明**：space sdk_version=gradio 4.44；app.py 用 Blocks/Video/Image/Dropdown/Radio/Button/Markdown 通用 API（4.x/6.x 均兼容；6.x 下 Blocks(theme=…) 仅告警不影响）。

**夜间任务**：待查（cron 窗口 22:00 后执行 nt-echomimic-smoke → nt-hd-4x-ultimate，见 state 文件/日志）。

## 十三、夜间任务收尾+三修复+长片重启（2026-09-09 晨 08:00-08:40）

**夜间任务全部收尾但完成度打折（ComfyUI 中途挂起事件）**：①nt-hd-4x-ultimate EXIT=0→video_462（1920×1088）✅，**4x 超分被'ComfyUnreachable'跳过**；②nt-hd-4x-r2v-refs EXIT=0→**video_463（参考图版 1920×1088，1.98MB）✅ 已交付 Windows outputs/video_82_母亲病床_r2v1080.mp4（抽帧 2.2s 目检：绿衣父/病床母/卧室环境锁定✅）**，4x 同样跳过；③nt-echomimic-smoke 重跑仍 EXIT=5（**根因实锤**：MTCNN 仅对高分辨率原图有效——00187 全部候选帧 0 boxes、缩放即 0，而参考图 1600×2848→5 框 0.99+；非脸小/非库坏）；④nt-ref-video-test EXIT=3（契约校验：模板 2 槽 vs 传 1 图→要求 <Picture 1/2>）。

**三修复（Windows 551d6e8/d7ad7ad，spark 已同步）**：①`echomimic_talk.py` 新增 **--ref-image 人像模式**（高分辨率人像原图直入 EchoMimic，输出即成品；视频模式错误提示指引）+ 判据修正；night exec 改为父亲.png；②ref-video-test exec 改 2 图+2 tag（父亲+卧室，<Picture 1/2>+<Video 1> 契约）；③新增 `runs/h3/upscale_once.py`（`_run_upscale` 复用）+ **nt-upscale-backfill**（video_462/463 补 4x→7680×4352）。状态已重置（echomimic-smoke/ref-video-test=pending），**今晚 22:00 窗口自动收尾**。

**长片《站台上的灯》**：agent 昨夜提交第 1 段后 Comfy 重启使其失效+通知注入失败为'任务不存在'；agent 陷入断点查询循环、续接耗尽停摆（a265 会话 6 行）。已注入'继续'（event 0ae3f462）重启：指示忽略无关旧断点、重新提交全部 8 段（第 5 段真台词链），白天自主推进。

**观察登记**：ComfyUI 服务形态=pid 2897957 `~/ai/venv/bin/python main.py --listen --reserve-vram 12 --enable-manager`，**不在 tmux comfy 会话**（与 CURRENT-STATE §2 记录不符）——托管方=supervisor/系统侧；与 book-13 #16 nap/supervisor 同族（服务侧逻辑，非本仓面），维持观察并建议下次与用户核对形态。

## 十四、《站台上的灯》工程化交付 + Agent 自主性边界结论（2026-09-09 上午）

**Agent 多段自主性实测（两轮注入均失败）**：第一轮注入后 agent 提交第 1 段（Comfy 重启致其失效）+'任务不存在'；续接耗尽停摆。第二轮（结构化 8 段指令+成品 prompt 全给）:agent 复读'第 1 段提交失败：提示词含空格未加引号'并进入同文案循环（spin 熔断后停），**0 提交**。结论：**Qwen3.8-27B 对'长序列多段制作'自主性不足**（假完成/复读/引号细节不修），agent 适合单段查询/单次提交；多段长片=工程化路径（脚本/批次/夜间任务），登记为 Agent 能力边界（agent-reading 后续注明：不承诺多段自主链，长片类走 runs 脚本）。

**工程化交付（已启动，后台 pwsh-153）**：`config/film_station_lights_prompts.json`（8 段成品英文 prompt：老站台/父亲入画/列车头灯/车厢窗景/j车窗父了对视/列车启动/雾中空站台/黎明进站，480p/4s/seed 20260908）→ 串行脚本 `/tmp/film_run.sh`：段0 无参续传等待→段1-7 逐段提交-轮询-落盘→**段5(车窗父子对视)接 lipsync_chain（--line '路上小心。' --voice yunxi --asr-check）**；段产物按 prompt_id 逐段留档（film_seg_N.log）。完成后：concat 8 段成片→Windows 交付（video_83_站台上的灯.mp4）；第 1 段 note=已失效 ef680224 不采用。

**h3_batch 能力边界记录**：submit=多图转场 N-1 段（images≥2 fo flf2v），不支持 t2v 独立序列批次——长片序列脚本化时勿走 batch（登记）。

## 十五、《站台上的灯》成片交付 + cosy 环境连环雷修复（2026-09-09 09:00-09:50）

**成片 ✅**：8 段串行生成（00200-00203/00205-00207=480p/4s/同 seed；第 5 段=**真台词链**：TTS→Wav2Lip→字幕旁白→**LINE_SCORE 1.000 ok（'路上小心。' ASR 回环满分）**）→ 逐段归一化（864×480/24fps/aac）→ concat → **32.7s《站台上的灯》** → Windows `outputs/video_83_站台上的灯.mp4`（抽帧 16.5s：车厢夜行氛围✓；父子近景段（00204 源）为近景弱/空镜，后续可选高清源重跑第 5 段）。段清单：00200/01/02/03→链→05/06/07。

**cosy-venv 连环雷修复（运维教训，重要）**：台词链首跑 rc=0→遇 `modelscope import TypeError replace(None)`。根因链=①cosy-venv 数个包**本地安装无 dist-info 元数据**（torch 等）→ `importlib.metadata.version()` 抛错；②site-packages **多版本同名 dist-info 冲突**（tokenizers-0.15.2 vs 0.23.2；torch-2.14.0+cu130 vs symlink 至 tts-venv 的 torch-2.14.0）→ stdlib metadata 返回 None；③transformers 4.x `get_torch_version`（其 import 链在 modelscope→cosyvoice 路径上）。修复（env 级，记录且不移库）：清理冲突 dist-info（tokenizers-0.23.2 / torch-2.14.0 symlink）、补 torch 元数据 METADATA、transformers==4.38.2 + tokenizers==0.15.2 重装、import_utils 加 `_torch_version` 兜底 patch（`torch.__version__` 回退）→ 全链 import 验证通过，链跑通。**教训：装依赖后必验 `importlib.metadata.version` 与 `pip show` 一致性；同名多 dist-info=stdlib 元数据静默返回 None（第三方 importlib_metadata 宽松掩盖）**。

## 十六、用户三批评落实：程序化+连贯性+配音（2026-09-09 10:00-12:00）

**①concat 程序化+教给 Qwen**：`runs/h3/film_stitch.py`（逐段归一化→demuxer concat→STITCH_OUT/PROBE；参数字段化）与 `runs/h3/film_series.py`（长片连贯链）入库；run_script 白名单描述增两脚本+SYSTEM 增「长片/多段必须 film_series（i2v 首帧继承），禁止逐段独立 t2v」条款；新增 docs/agent-reading/06-film-series.md；agent 已重启生效（教学完成）。注：603d672 一次提交误带 tools.py 描述拼接语法错→f47d88a 修复（教训：大字符串 edit 后必 py_compile 再提交）。

**②连贯性重制（用户批评'各自为战'）**：v1（逐段独立 t2v，32.7s）弃用；**v2=film_series i2v 首帧继承链**——每段首帧=上段末帧+延续句（same characters/location/lighting, continuous, no cuts）；8 段视频 video_474-481 → stitch → **station_lights_v2.mp4 35.86s**（抽帧 6s：同站台/站灯/绿衣父身影/雾中铁轨，段间衔接✓）→ Windows `outputs/video_84_站台上的灯_v2连贯版.mp4`。`--start-image` 也可由首帧图启动。

**③配音机械味**：初版 cosy 未传 speed（默认 1.0，节奏平直）；`tts_cosy_check.py` 增 `--speed 0.95`（默认）并传入 inference_zero_shot；lipsync_chain 子进程默认继承 cosy 参数（0.95）；**听感待用户复验**（仍机械→后续候选：换更长/更贴角色参考样本、增大 speed 档差、或不同声学模型）。

**后续候选（用户可点）**：①v2 第 5 段（车窗对视）未接台词链（v2 为纯视效连贯版）；可对近景脸段接 lipsync_chain（音色=0.95 版）。②第 5 段近景观感重制（高清源）。③Qwen 长片演示轮（现在已教学完成，可让 agent 直接跑 film_series）。

## 十七、用户新批评（内容莫名/物理逻辑/伪语音乱码/字幕乱码）→ v3 修复包+候选全部执行（2026-09-09 12:30-13:00）

**定性**：①'不符合现实物理逻辑'=4 步快档+抽象动作（H3 低档通病）；②'说的话无法解析'=**H3 原生伪语音（乱码级，项目已知缺陷）**，v2 未剔除；③'字幕乱码'=**模型画面内自画文字**（提示词未零字化）。

**v3 修复包（Windows 1c3a269，spark 已同步）**：①film_series 增 `--lora`（none=20 步全质=物理/细节最佳；v3 用 none）与提示词追加物理延续句（natural movement/believable weight/plausible camera）；②**零文字化**：8 段与延续句全部加 'NO written characters/signage text/readable letters/numbers anywhere'；③film_stitch 增 `--strip-audio`（剔除 H3 伪语音；真台词由语音段补）；④film_series 增 `--voice-segment N --line …`：句段生成后自动接 lipsync_chain（0.95 版 cosy）并替换段文件；⑤第 5 段 prompt 改为'绿衣父站台窗旁中近景（自然微动+现实）'作脸源。

**v3 联产中（pwsh-160 后台）**：8 段 720p/20 步/同 seed/零文字 → 第5段真台词（路上小心。/yunxi/0.95）→ stitch --strip-audio → /tmp/station_lights_v3.mp4（预计 60-90min）；完成后交付 Windows video_85 + 抽帧+ASR。

## 十九、v3 终版交付 + 链排障 + 方向修正收尾（2026-09-09 13:00-14:30）

**v3 终版 ✅**：8 段 720p/none(20步)/i2v 首帧继承/零文字（video_482-489，35.7s）→ **台词段重制**：v3 各段均无近景脸（远景脸 18-47px→Wav2Lip Face not detected）→ **单独生成特写近景**（MiniMax_H3_00225_：263×303 大脸 ✓）→ **逐帧全检**（107 帧中 92 有脸；最长连续 80 帧=1.13-4.46s）→ 显式裁剪该区间入链 → **LININE_SCORE 1.000（“路上小心。”）** → film_stitch 新增 **--keep-audio-segs 4**（仅台词段保留音轨，其余全去 H3 伪语音）→ **station_lights_v3_final.mp4 32.58s** → Windows `outputs/video_85_站台上的灯_v3终版.mp4`（抽帧 16s：绿衣老人大脸站台+车窗人影✓）。

**方向修正（用户定案）**：①spark 仅为实验机——「创空间→spark 远程调度（M2 gateway）」**作废、非交付形态**（gateway 仅实验联调）；创空间适配正解=**自包含**：M1（展示交互，已验收）→ M3（平台免费 GPU/PAI 单点演示，视规格）；H3 引擎（40GB+/GPU）在免费 CPU 档**不可行并如实告知**。②**M1 精修 v1.2**：requirements 零依赖+表单多行/示例填充/说明卡/页脚版本/README 限制如实；本地回归 200/56 组件/3 交互。③公网实测：仅 8080 TCP 可达、HTTP 无回（云侧未转发），打通路线=账号侧（已记 studio-porting §3）。

**候选③ agent 演示已备**：`config/demo_cat_night_prompts.json`（3 段《雨夜便利店前的猫》零文字版）——v3 完成后注入 agent：run_script(h3/film_series.py …demo… --stitch)，验证 Qwen 学会长片链（SYS+06 文档已教学）。