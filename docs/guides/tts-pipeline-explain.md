# 本地语音合成管道详解（F5-TTS 大模型 + 项目程序）

> 2026-09-07 整理：解答"怎么合成的、怎么工作的、用什么模型、怎么用项目程序"。

## 1. 用了什么模型（全部本地、魔搭/开源）

| 组件 | 模型/权重 | 来源 | 位置 |
|---|---|---|---|
| **语音生成大模型** | F5-TTS v1（SWivid，Flow Matching 文本转语音，~1.35B 参数量级） | 魔搭 AI-ModelScope/F5-TTS（F5TTS_v1_Base/model_1250000.safetensors，1.35GB） | ~/ai/ComfyUI/models/f5-tts/F5TTS_v1_Base/ |
| **声码器（波形合成）** | vocos-mel-24khz | HF charactr/vocos-mel-24khz（54MB，经 hf-mirror.com 镜像下载） | ~/ai/ComfyUI/models/f5-tts/vocos/ |
| **参考音色样本**（音色=克隆源） | 女声：CosyVoice 官方 zero_shot_prompt.wav（真人录音+配套文本）；男声：真人男声素材（ASR 转写文本）；英文/跨语种：CosyVoice 官方 cross_lingual_prompt.wav | GitHub FunAudioLLM/CosyVoice asset/ | 项目 assets/tts_refs/{xiaoxiao,yunxi,aria}.wav+.txt |
| **验收（ASR 回环）** | SenseVoiceSmall（FunASR，魔搭 iic/SenseVoiceSmall-onnx，量化 ONNX 241MB） | 魔搭 | ~/ai/ComfyUI/models/asr/sensevoice/ |
| **运行环境** | ~/ai/tts-venv（python3.12：torch 2.14(cu13)、f5-tts、transformers 4.47.1、tokenizers 0.21.4 等） | pip 安装（独立 venv，不污染 ComfyUI 环境） | spark |

注意：F5-TTS 是 zero-shot 克隆——合成音色完全来自参考音频（不是模型自带预置音色）。所以参考样本质量决定音色：edge-tts 合成的样本 → 音色=edge 感（这就是之前"听着像便宜的 edge 语音"的根因，虽然合成器一直是大模型）；换官方/真人样本后音色=真人级。

## 2. 合成是怎么工作的（原理）

    你的文本 → 【1】文本 tokenizer(T5 分词→词嵌入)+参考音频/文本(音色特征) → 【2】Flow Matching 流匹配生成器(高斯噪声流成语音隐变量；参考特征 conditioning 音色/韵律，目标文本控制内容) → 【3】vocos 声码器 → 24kHz PCM 波形(.wav，本机 CPU，无云端请求)

- F5-TTS v1 = Flow Matching(流匹配)+Transformer 架构 TTS 大模型（SWivid/F5-TTS，论文 Fairytaler），比 VITS/edge-tts 强在多说话人克隆与自然度；
- 参数：ode_method=euler、32 步采样、cfg_strength=2（默认）；
- 速度：CPU 约 50s 生成 5s 语音（13.6s 英文旁白 ≈ 4.4 分钟）；GPU（--device cuda）快一个量级——登记为后续优化。

## 3. 我们写的项目程序（调用链）

### A. 工具/入口（单条命令合成）

    # spark 上，激活 TTS 环境后：
    . ~/ai/tts-venv/bin/activate
    cd ~/videoGenerate-Model-zju
    python3 runs/h3/tts_local_check.py \
        --text "要合成的文本（中/英文均可）" \
        --ref-file assets/tts_refs/xiaoxiao.wav \        # 参考音色（xiaoxiao/yunxi/aria）
        --ref-text "参考音频对应文本（必须与音频匹配）" \
        --output /tmp/out.wav
    # 输出 OUT_WAV: /tmp/out.wav (N bytes, T s)

tts_local_check.py 内部逻辑：1) _comfy_paths() 自动探测模型（优先 ComfyUI models，回落旧缓存）；2) F5TTS(model=F5TTS_v1_Base, ckpt_file=魔搭权重, vocoder_local_path=vocos, device=...)加载；3) tts.infer(ref_file, ref_text, gen_text, file_wave)生成；4) 打印 OUT_WAV。

### B. 生成流水线接入（视频配音/字幕/成品）

    python3 runs/h3_submit.py --stage t2v --prompt ... --tts-text "台词" \
        --tts-backend local \        # 默认 local(F5-TTS)；edge 为显式降级
        --finalize \                 # 组合：local TTS + ASR 回环验收
        --asr-check                  # 完成时 SenseVoice 回环比对

- runs/h3/tts.py：synth_local()(子进程封装 tts_local_check)、synthesize(backend=)、attach_speech_and_subtitle()(语音→SRT→libass 烧字幕→替换音轨)、prepare_speech()；
- runs/h3_submit.py：--tts-backend/--finalize/--tts-mix-bed(配乐-12dB)/--upscale 4x(超分)/--asr-check——全部持久化，续传自动恢复；
- hook 链：apply_finalize() → _run_tts_hook()(fast/普通两分支) → _post_tts_checks()(混音+ASR) → (可选)_run_upscale()。

### C. ComfyUI 节点版（UI 点点点）

- 节点包 comfy_nodes/h3_finalize/（部署 ~/ai/ComfyUI/custom_nodes/h3_finalize/，重启后分类 h3 可见）：H3LocalTTS(text+voice→wav)、H3Finalize(video+text+voice±bed/font→成品 mp4)、H3AsrCheck(media±compare→text/score)；
- 模板 workflows/remote_workflows/h3_finalize_chain.json（spark ComfyUI user/workflows，打开即用）。

### D. 验收闭环

runs/h3/asr_check.py（我们写的）→ ffmpeg 提 16k wav → funasr_onnx.SenseVoiceSmall（魔搭 ONNX）→ ASR_TEXT/VERDICT；--compare 台词 → ASR_SCORE/ASR_MATCH(≥0.6 ok)。本次英文旁白 ASR 逐句还原原文即闭环证据。

## 4. 复现本次"英文旁白"的完整命令序列

    1) 参考音色：GitHub contents API 下载 CosyVoice cross_lingual_prompt.wav → assets/tts_refs/aria.wav
    2) 参考文本：asr_check 转写 prompt 原文 → assets/tts_refs/aria.txt
    3) 合成：. ~/ai/tts-venv/bin/activate && cd ~/videoGenerate-Model-zju &&
       python3 runs/h3/tts_local_check.py --text "We can't control genetics yet. But scientists found a hormone that slows aging. Rich people pay fortunes for it. Sell yours, and you'll be rich — at the cost of some of your life. Maybe you'll die suddenly when you are old, but who cares?" --ref-file assets/tts_refs/aria.wav --ref-text "$(cat assets/tts_refs/aria.txt)" --output /tmp/en_narr.wav
    4) 验收：asr_check /tmp/en_narr.wav → ASR_TEXT 与原文对比

## 5. 关键约定（防再踩坑）

1. 默认=大模型：--tts-backend local 是默认；edge 仅显式降级；
2. 音色=参考样本：必须真人/官方（edge 样本严禁再用）；改样本即改音色；
3. 模型统一放 ComfyUI models/（f5-tts、asr 等）；
4. 环境隔离：tts-venv/asr-venv 独立；依赖改动后先合成冒烟（transformers/tokenizers 对齐教训）；
5. 长文本耗时：CPU≈50s/句；--device cuda 加速（GPU 空闲时）；

---
样例产物：outputs/voice_english_narration.wav（13.6s/24kHz）、outputs/voice_demo_official.mp3（官方女声）。