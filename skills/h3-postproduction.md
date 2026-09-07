# H3 Post-Production Skill（成品链：语音/字幕/音效/验收/超分）

> **When to use**: 生成出片后，需要"带人声台词/字幕/混音音效/ASR 客观验收/超分交付"的任一环节——
> 即**标准成品链**（S13/P 链，2026-09-06/07 实施并多轮真机 PASS）。
> **Audience**: AI agents 或操作者。原理详解见 `docs/guides/tts-pipeline-explain.md`；当前事实见 `docs/CURRENT-STATE.md`。

---

## 0. 认知速记

- **音色 = f(参考音频)**：F5-TTS 是克隆式模型，参考样本 `assets/tts_refs/{voice}.wav` 决定音色，
  `.txt` 为其对应转写文本（必须与音频一致）。换音色=换这对文件，无需改码。
- **成品音轨 = 独立合成的音轨替换**（不是让 H3 模型"念"台词）：模型原生音频仅供参考氛围，
  不支持精确复刻；台词/音效/音乐全部由成品链生成后隔离替换。
- **验收=客观回环**：SenseVoice ASR 对成品语音转写并与原文比对（`ASR_SCORE≥0.6=ok`），
  不依赖人工听测（听测仅作最终抽检）。

## 1. 模型与 venv（spark）

| 用途 | 模型 | venv |
|---|---|---|
| 人声合成 | F5-TTS v1（`~/ai/ComfyUI/models/f5-tts/`）+ vocos 24kHz | `~/ai/tts-venv` |
| ASR 回环 | SenseVoiceSmall ONNX（`models/asr/sensevoice`） | `~/ai/asr-venv` |
| 超分 | 4x-UltraSharp（默认）/ RealESRGAN_x4plus（备选），均在 `models/upscale_models/` | ComfyUI |
| **默认人声（2026-09-07 定案）** | CosyVoice2-0.5B（`~/ai/CosyVoice2-0.5B`+code `~/ai/cosyvoice-src`；**已接入 `--tts-backend cosy`=默认**；GPU 优先、忙时自动转 CPU≈47s/句） | `~/ai/cosy-venv` |

## 2. 标准流程（生产用法）

### 2.1 一键成品链（首选）

```bash
cd ~/videoGenerate-Model-zju
python3 runs/h3_submit.py --stage <t2v|i2v|r2v|flf2v> --prompt "...(经 prompt-engineering)" \
  --tts-text "<台词>" --tts-voice xiaoxiao --tts-backend cosy \
  --finalize --asr-check \
  [--tts-mix-bed <配乐/参考音频>] [--postprocess fast] [--upscale 4x]
```

顺序（链内）：生成 → 本地 TTS（F5-TTS）→ SRT 字幕 → 音轨替换 →（可选 -12dB 底轨混音）→
ASR 回环（失败不阻断主产物，打印 `ASR_SCORE`）→ postprocess/超分。

### 2.2 分步（调试/自定义音效时）

| 步 | 命令 | 判据 |
|---|---|---|
| 单独 TTS | `~/ai/tts-venv/bin/python3 runs/h3/tts_local_check.py --text <台词> --ref-file assets/tts_refs/<voice>.wav --ref-text "$(cat assets/tts_refs/<voice>.txt)" --output /tmp/t.wav` | `OUT_WAV` 行；CPU ≈50-80s/句 |
| 音效混合 | `python3 runs/h3/sfx_mix.py --video <v> --music <底轨> --music-db -12 --events "开始秒:文件:dB,..." --out <成品>` | 三路 amix normalize=0；loudnorm -14 |
| ASR 验收 | `~/ai/asr-venv/bin/python3 runs/h3/asr_check.py <媒体> --compare <原文>` | `ASR_SCORE ≥ 0.6`/文本目检 |
| 2x 增强 | `python3 runs/h3/postprocess.py process <in> --out <pp.mp4> --scale 2.0 --audio <音轨>` | 宽高翻倍、音轨 intact |
| ComfyUI | `workflows/remote_workflows/h3_finalize_chain.json`（h3 分类：H3LocalTTS/H3Finalize/H3AsrCheck） | 节点输出 filepath + score |

## 3. 音色表（assets/tts_refs/）

| 短名 | 性别/用途 | 样本来源（2026-09-07 状态） |
|---|---|---|
| `xiaoxiao` | 中文女（默认） | CosyVoice 官方 zero_shot_prompt.wav + 官方文本 |
| `yunxi` | 中文男 | 真人男声素材 + ASR 转写文本 |
| `aria` | **英文女** | **双轨**：仓库当前=CosyVoice 官方 cross-lingual 样本（中文语料跨语种克隆）；备选=LJSpeech 真人英文样本（更地道）。**听测判优后换文件即切换**；判据=与 `outputs/voice_demo_aria_en.mp3`（LJSpeech）/ `voice_english_narration.wav`（cross-lingual）对照 |

## 4. 音效/音乐实操要点（sfx_mix）

- events 格式：`开始秒:音效文件:dB`（逗号分隔）；无音轨视频自动只混 music/events。
- 音效文件可先程序/ffmpeg 预合成（脚步=低频噪声脉冲序列、电视启动=click+50Hz hum+静态噪声、
  Drone=低频正弦堆+LFO）——2026-09-07 镜头17 实战即 numpy 合成（无外部资产也能出）。
- 配比参考：音乐底轨 -12dB（淡入淡出 3s）、音效 -6dB、**台词/旁白 -3~0dB 主导**；最后 loudnorm -14 LUFS。

## 5. 交付与存档

- 成品：Windows `outputs/video_<N>[_描述].mp4`（raw 在 spark 任务目录 `workflows/h3_<ts>_<ms>/`，`job.json` 存档参数）。
- 听测样：`outputs/voice_demo_*.mp3`（生成后 scp 回 Windows 主库）。
- 移交标准：`REMOTE_VIDEO_PATH:` / `LOCAL_OUTPUT:` / `ASR_SCORE:` 三行齐全 + 抽帧目检记录。

## 6. 已知边界（如实）

- CPU 合成成本 50-80s/句（GPU 分担=远期）；CosyVoice2 接入待用户听测+GPU 窗口。
- 字幕=台词 SRT 烧录（libass+Noto CJK；`--font-size 0`=随分辨率等比）；英文台词同样可烧。
- 超分 4x=合成非原生（608→2432），耗时长；"更清晰"场景才用（`--upscale 4x`）。
