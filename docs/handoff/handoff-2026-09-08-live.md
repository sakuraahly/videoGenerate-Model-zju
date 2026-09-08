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