# 交接文档（2026-09-07 现场）

> 角色：**当日现场交接**（问题/修复/实战/运维记录）。当前事实权威=`docs/CURRENT-STATE.md`；
> 文档地图=`docs/README.md`；跨日后本文件归档为 `handoff-2026-09-07.md` 并按新日期新建。

## 1. 本次核心问题与真相

**用户疑问**：① 为什么用"便宜的 edge 语音"？② 语音生成大模型为什么没用？③ 为什么不能在 ComfyUI 直接得到带语音+字幕的版本？

**排查结论（证据）**：任务日志 `tts_done ... backend=local`——成品**确实是语音生成大模型 F5-TTS 本地合成**（50s/句级）。用户听感="edge 感"的**根因**：**参考音色样本最初用 edge-tts 预生成**——F5-TTS 克隆的是该 edge 样本的音色（音色=f(参考音频)）。**"没用大模型"是误判，但"音色非大模型级"成立**。

## 2. 已修复（本次）

| 项 | 变更 |
|---|---|
| 参考音色 | xiaoxiao(默认女声)=**CosyVoice 官方 zero_shot_prompt.wav**（真人大模型官方音色，配套官方文本）；yunxi(男声)=**真人男声素材**（ASR 转写文本）；aria(英文女声)=**LJSpeech 真人英文女声**（公开领域数据，配套官方转写文本；详见 §6 已闭环） |
| 默认后端 | h3_submit `--tts-backend` 默认 **edge→local**（语音大模型为默认；edge 仅在显式 `--tts-backend edge` 时降级使用） |
| 听感样 | `outputs/voice_demo_official.mp3`（官方女声 F5-TTS 合成，请听）；`outputs/voice_demo_aria_en.mp3`（aria 真人英文女声 F5-TTS 合成，请听） |

## 3. 语音+字幕生成的两条路径（均可得到最终成品）

### A. ComfyUI 直接出（语音+字幕版）
1. ComfyUI 打开 **H3 生成工作流**（`workflows/remote_workflows/video_minimax_h3_{r2v,i2v,t2v,flf2v}.json`）→ 运行生成（存 ComfyUI output/，如 MiniMax_H3_00152_.mp4）；
2. ComfyUI 打开 **`h3_finalize_chain.json`**（分类 h3：H3Finalize + H3AsrCheck，已随 ComfyUI 重启激活）：
   - H3Finalize.video = 产物绝对路径；text=台词；voice=xiaoxiao/yunxi/aria（均为语音大模型音色）；bed_audio=配乐（可选，-12dB）；font_size=0
   - 运行 → 得到 `*_final.mp4`（本地大模型语音+字幕+可选混音）；H3AsrCheck 自动回环比对（score≥0.6 ok）
3. 需要更清晰：用超分（模板/API，RealESRGAN 4x-UltraSharp，608→2432）。

### B. 对话（agent）一句出成品
"帮我生成…视频，台词是'…'"→ agent 自动走 **F5-TTS 本地大模型（默认 local）+字幕+ASR 验收**（`finalize` 链），取回 `*_pp.mp4`（2x）。要求超分→加"更清晰/高清"→ `upscale=true`。

## 4. 模型位置（全部在 ComfyUI models，用户要求）

`~/ai/ComfyUI/models/`：f5-tts/{F5TTS_v1_Base,vocos}；asr/sensevoice（SenseVoice ONNX）；diffusers/stable-diffusion-inpainting（Inpaint）；checkpoints/sd-v1-5-inpainting.ckpt；upscale_models/{4x-UltraSharp.pth,RealESRGAN_x4plus.*}；frame_interpolation/（空，RIFE 权重渠道阻塞登记）。
执行环境：`~/ai/tts-venv`（F5-TTS）、`~/ai/asr-venv`（FunASR）；`assets/tts_refs/{xiaoxiao,yunxi,aria}.wav+.txt`=参考音色。

## 5. 服务状态（spark）

- ComfyUI：**tmux `comfy`**（systemd 单位已停用——root 侧可恢复；用户授权下重启过，H3 节点已激活）
- agent：tmux `agent`（HTTP 200，最新代码）
- SGLang：guard tmux 自动管理（当前 up）；本机中文 prompt 生成/agent 对话依赖它

## 6. 下一步

1. （用户听测 `voice_demo_official.mp3` 与 `outputs/video_53.mp4` 的音色）→ 若满意：以官方音色重出实战片；
2. ~~aria 英文音色换官方/真人样本~~ ✅（2026-09-07 后续已闭环：aria=LJSpeech 真人英文女声（LJ006-0006，公开领域，官方转写文本）；真机 F5-TTS 合成英句 ASR 回环 **1.000**；听测样 `outputs/voice_demo_aria_en.mp3`）；
3. ComfyUI 一体模板（生成+Finalize 合并）打磨（可选）；
4. S13 远期：CosyVoice2 全链后端（音色库）/口型/1080p 探测（授权项）。

## 7. 实战演练记录（镜头17 = 原镜头13 [Shot 1]，2026-09-07 后续）

**用户指示**：以"沙朗客厅电视新闻"剧本（含 3 张资产图）做实战演练；同时答"视频参考是否已支持"。

**视频参考：已支持（无需写入待办）**——S7（2026-09-06 实施）：r2v 阶段 `--videos/--audios`（≤3）经
`stage.inject_media_refs` 注入 LoadVideo→GetVideoComponents→ref_videos（+ref_video_audios）/
LoadAudio→ref_audios；提示词必须含 `<Video N>`/`<Audio N>` tag 契约；agent 工具 CallComfyUI
videos/audios 参数同链；真机 video_46（参考视频+参考音频采纳）PASS。本片**未用**视频参考：
分镜视频 MiniMax_H3_00128_.mp4 实为另一镜头（欠款单据），不宜作运动参考——如后续需要
运动参考请提供对应分镜片段。

**生成**：r2v，3 参考图=`破旧公寓客厅/沙朗/新游戏眼镜`（资产图目录），提示词=剧本结构化英文版
（人物/场景/道具 exact reference+12s 连续单镜+分段时间轴+固定语义句），negative=用户负面清单
（无变形/无面部扭曲/无比例失调/无动作不自然/无表情模糊/语音清晰/无噪音掩盖+无文字水印）；
360p/12s/ref2v_4step/seed auto（实跑 608×352/24fps/294帧≈12.25s）；抽帧目检 0.5/2/3.5/5/8/11.5s
全通过（房间/人物/道具与参考图一致；电视出现新闻主播；笑容→皱眉→近前锁屏）。

**音轨（独立合成，替代模型原生音频）**：英文新闻台词语音=aria 真人英文女声 F5-TTS 合成
（"Robot layoffs in factories reach a record high."，ASR 回环 1.000）+ 跑步声（8 步 0-1.2s）+
电视启动音（1.5s）+ 音乐（0-1.85s 轻快电子乐 → 骤停 → 2.05s 起 Drone 至结尾，numpy 合成，
sfx_mix 三路混音：音乐 -12dB/音效 -6dB/新闻 -3dB，loudnorm -14）；成品 1216×704/24fps/11.88s。

**产物**：win `outputs/video_54_shot17_final.mp4`（spark 同名 outputs/video_shot17_final_pp.mp4）；
任务目录 workflows/h3_20260907_063905_102（raw MiniMax_H3_00158_.mp4）。

**待用户**：听测 `outputs/video_54_shot17_final.mp4`（音轨+画面）与 `voice_demo_aria_en.mp3`；
中文女声"电音"问题 → CosyVoice2 试点（见 §8 已闭环试点，接入生产待听测）。

## 8. 中文女声"电音"修复：CosyVoice2 试点（2026-09-07 后续）

**判定**：F5-TTS v1 + vocos 24kHz 的"电音/金属感"是模型/vocoder 级限制，换参考样本无法根治；
解决方案=换 TTS 后端。**试点已完成（S13 授权项落首子项）**：

- **环境**（spark）：venv `~/ai/cosy-venv`（torch 2.14.0+cu130 复用 tts-venv 符号链接；
  numpy/onnxruntime/whisper/pyworld/lightning/Matcha-TTS 等补齐）；代码 `~/ai/cosyvoice-src`
  （GitHub zip 方式落地：git clone 通道被墙——github.com:443 不通，raw/codeload 可达，已登记）；
- **模型**：`~/ai/CosyVoice2-0.5B`（魔搭 iic，15 文件齐全）；
- **推理**：`inference_zero_shot`（参考样本=官方 zero_shot_prompt.wav）——**CPU 模式成功**
  （GPU 被生成队列占满时 CUDA OOM，CUDA_VISIBLE_DEVICES="" 转 CPU：加载+合成 47s/句，rtf≈7.6）；
- **验收**：同句 A/B（"希望你以后能够比现在的你更强更优秀…"）SenseVoice ASR 还原正常；
  旁白句（"他走到电视机前…"）ASR 亦通顺；
- **听测样**：`outputs/voice_demo_cosy_zh.mp3`（同句 A/B，与 voice_demo_official.mp3 并排对比）+
  `outputs/voice_demo_cosy_zh2.mp3`（平和旁白句）；
- **登记**：① 接入 tts.py 后端（h3_submit --tts-backend cosy）待用户听测通过 + GPU 空闲窗口
  （当前队列繁忙时 CUDA OOM）；② CPU 47s/句=过渡可接受（GPU≈秒级）；③ 音色库/口型/1080p 仍远期。

**⚠️ 并发登记（16:14-16:20 有并行会话操作同一仓库）**：提交 b125901/1f4f4fd（同一作者身份）将
`assets/tts_refs/aria.wav` 换成 **CosyVoice 官方 cross_lingual_prompt.wav（中文语料原样 wav，配套中文 ASR 转写文本）**——
与本节 LJSpeech 方案是不同的 aria 双轨方案：LJSpeech=真人**英文**女声样本（英文天然无口音）；
cross-lingual=同一官方女声中文语料做跨语种克隆（英文带中式口音风险，但其 13.6s 英文旁白
ASR 逐句还原通过）。**当前仓库 aria = cross-lingual 方案（b125901）；本节 video_54 音轨
= LJSpeech 方案（生成时点仓库样本=它）**。听测对照：`outputs/voice_demo_aria_en.mp3`（LJSpeech）
与（并行会话产物）`outputs/voice_english_narration.wav`（cross-lingual）。判优后一个提示词即可切换
（参照 §2 音色表行），无需代码改动（tts.py/_voice_key 均按短名取 assets/tts_refs/{voice}）。

## 11. 本轮授权执行记录（2026-09-07 下午）

**用户定案**：① aria=本地模型生成的自然接近真人音色（官方 cross-lingual 方案，当前仓库即此；LJSpeech 归档备选）；
② CosyVoice2 支持中文女声=必须；③ 原生 1080p 探测（大队列窗口）留空闲；④ 其余执行。

**已完成**：
- **CosyVoice2 接入生产**：runs/h3/tts_cosy_check.py（GPU 优先/OOM 自动 CPU）+ tts.py synth_cosy 分发（默认 cosy）+
  h3_submit --tts-backend cosy（默认；finalize 不再强制 local；resume 归一含 cosy）+ 调度器 SYSTEM 文案 + 单测（18 绿）；
  真机冒烟：通过 tts.py 分发合成 A/B 句，ASR 还原，听测样 outputs/voice_demo_cosy_zh_final.mp3（GPU 忙→CPU 回落路径实际验证）。
- **一体模板 MVP**：workflows/remote_workflows/video_minimax_h3_r2v_finalize.json（31 节点=生成+结尾 H3Finalize→H3AsrCheck 同图）；
  登记限制：SaveVideo 输出为 VIDEO 类型、H3Finalize 入参为路径字符串——自动桥接需组合节点（组件增强候选，排期）；
  当前 MVP=同一张图里生成→填路径→配音→验收。
- **中期报告**：docs/reports/2026-09-07-midterm.md（人读版）。

**登记待办**：1080p 探测 + Wav2Lip 口型冒烟=空闲窗口（已授权）；S12 真机验证需真实对话轮（待用户侧演练）；
RIFE 插帧=渠道阻塞（魔搭精简版不兼容/官方权重待 Git 通道）。

## 10. 运维记录（2026-09-07 下午，qwen agent 能力/误删排查）

**1) "让 qwen agent 掌握 TTS 管道"已落地**：新增 agent 参考文档
`docs/agent-reading/04-tts-pipeline.md`（模型表/音色/三种用法/验收判据/音效链/边界；指向
`docs/guides/tts-pipeline-explain.md` 详解版）——agent 的 read_doc 工具描述自动随目录更新，重启 agent 即生效
（旁路：SYSTEM_MESSAGE 2608t 预算不变，扩展走文档通道）；agent 已重启（svc_main restart-agent）。

**2) 意外命令 `rm -f RealESRGAN_x4plus.safetensors` 排查（用户报告）**：该命令删的是 **home 目录副本**
（bash_history 393-396：rm → ls | grep → rm，均在 ~）；**ComfyUI 模型目录副本完好**：
`~/ai/ComfyUI/models/upscale_models/RealESRGAN_x4plus.safetensors`（66,857,836 B，safetensors 库实载
702 张量，结构体 body.0.rdb1.* = Real-ESRGAN x4plus 正常）——**无需从魔搭恢复**；
引用方确认：ComfyUI 官方模板 utility-gan_upscaler.json 用 `RealESRGAN_x4plus.safetensors`（✓在）、
项目 r2v 模板内嵌超分节用 `RealESRGAN_x4plus.pth`（✓在）；主超分链=4x-UltraSharp.pth（✓在）。
