# TTS 语音/字幕管道（本地大模型；2026-09-07）

一句话：**台词/旁白 = 本地大模型克隆合成（默认 CosyVoice2 自然音色，音色=参考样本；F5-TTS 备选）+ SenseVoice ASR 回环验收 + 字幕/混音/超分后处理**。
详细原理与复现序列见 `docs/guides/tts-pipeline-explain.md`（讲解版）；本页只给 agent 可执行要点。

## 模型与环境（全本机，无云端）

| 用途 | 模型 | 位置（spark） | venv |
|---|---|---|---|
| **默认合成** | CosyVoice2-0.5B（更自然；**已接入 `--tts-backend cosy`=默认**；GPU 优先、OOM 自动转 CPU≈47s/句） | `~/ai/CosyVoice2-0.5B` + `~/ai/cosyvoice-src` | `~/ai/cosy-venv` |
| 备选合成 | F5-TTS v1（Flow Matching，克隆式；`--tts-backend local`） | `~/ai/ComfyUI/models/f5-tts/F5TTS_v1_Base` + `vocos/` | `~/ai/tts-venv` |
| ASR 验收 | SenseVoiceSmall ONNX（魔搭） | `~/ai/ComfyUI/models/asr/sensevoice` | `~/ai/asr-venv` |

## 音色（零样本克隆源：assets/tts_refs/{voice}.wav + .txt）

- `xiaoxiao`=官方女声（默认）；`yunxi`=真人男声；`aria`=**英文**女声。
- **aria=英文女声（2026-09-07 用户定案）**：官方 cross-lingual 样本（本地模型克隆合成、自然接近真人）——当前仓库即此；LJSpeech 真人英文样本=备选归档（换文件即切换）。

## 三种用法

1. **单条合成**（最快）：
   `~/ai/tts-venv/bin/python3 runs/h3/tts_local_check.py --text "<台词>" --ref-file assets/tts_refs/<voice>.wav --ref-text "$(cat assets/tts_refs/<voice>.txt)" --output /tmp/out.wav`
2. **视频成品链**：`h3_submit --tts-text "<台词>" --tts-backend local --finalize --asr-check`
   （默认即本地大模型；字幕/音轨替换/混音一步到位；`--tts-mix-bed <音频>` 加 -12dB 底轨；`--upscale 4x` 超分）
3. **ComfyUI**：`h3_finalize_chain.json`（H3LocalTTS/H3Finalize/H3AsrCheck，分类 h3）→ 填文本/音色 → 成品+自动验收。

**验收判据**：`asr_check.py <视频/音频> --compare "<原文>"` → `ASR_SCORE≥0.6=ok`（同链送回用户前跑一次）。

**音效/音乐**：`runs/h3/sfx_mix.py --video <v> --music <底轨> --music-db -12 --events "开始秒:文件:dB,..." --out <成品>`
（三路混音：原音轨+音乐底轨+分段音效；音效文件可先行用 ffmpeg/程序生成）。

**免责边界**：CPU 合成 ≈50-80s/句（GPU 分担=远期优化）；"音频参考≠音频复刻"（H3 原生音轨仅供参考氛围，成品音轨=以上 TTS 链）。
