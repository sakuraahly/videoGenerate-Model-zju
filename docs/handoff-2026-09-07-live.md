# 交接文档（2026-09-07 现场）

## 1. 本次核心问题与真相

**用户疑问**：① 为什么用"便宜的 edge 语音"？② 语音生成大模型为什么没用？③ 为什么不能在 ComfyUI 直接得到带语音+字幕的版本？

**排查结论（证据）**：任务日志 `tts_done ... backend=local`——成品**确实是语音生成大模型 F5-TTS 本地合成**（50s/句级）。用户听感="edge 感"的**根因**：**参考音色样本最初用 edge-tts 预生成**——F5-TTS 克隆的是该 edge 样本的音色（音色=f(参考音频)）。**"没用大模型"是误判，但"音色非大模型级"成立**。

## 2. 已修复（本次）

| 项 | 变更 |
|---|---|
| 参考音色 | xiaoxiao(默认女声)=**CosyVoice 官方 zero_shot_prompt.wav**（真人大模型官方音色，配套官方文本）；yunxi(男声)=**真人男声素材**（ASR 转写文本）；aria 暂保留（登记后续换） |
| 默认后端 | h3_submit `--tts-backend` 默认 **edge→local**（语音大模型为默认；edge 仅在显式 `--tts-backend edge` 时降级使用） |
| 听感样 | `outputs/voice_demo_official.mp3`（官方女声 F5-TTS 合成，请听） |

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
2. aria 英文音色换官方/真人样本；
3. ComfyUI 一体模板（生成+Finalize 合并）打磨（可选）；
4. S13 远期：CosyVoice2 全链后端（音色库）/口型/1080p 探测（授权项）。
