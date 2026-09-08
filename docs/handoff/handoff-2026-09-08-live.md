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