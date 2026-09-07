# H3 Finalize 成品链节点（ComfyUI）

2026-09-07 用户指示：升级后的工作流直接在 ComfyUI 获得最终成品——本节点=ComfyUI 节点化路径
（项目侧 h3_submit 钩子链=引擎管线化路径，两者并存；§13③ 定案）。

## 节点

| 节点 | 输入 | 输出 | 说明 |
|---|---|---|---|
| **H3 Local TTS (F5-TTS)** | text, voice(xiaoxiao/yunxi/aria) | audio(wav 路径) | 本地 F5-TTS 合成（魔搭权重，克隆参考样本音色；CPU≈53s/句） |
| **H3 Finalize (TTS+Subtitle+Mix)** | video(路径), text, voice; 可选 bed_audio(参考音频/配乐), font_size | filepath(成品 mp4) | 本地 TTS → 字幕 SRT → 烧录 → 音轨替换 → （可选 bed_audio -12dB 底轨混音）→ 成品 |
| **H3 ASR Check (SenseVoice)** | media(路径); 可选 text_compare | text, score | 本地 SenseVoice ASR 验收（可辨析/台词回环比对，score≥0.6=ok） |

## 接线（ComfyUI 工作流）

1. 现有 H3 生成工作流（video_minimax_h3_r2v / t2v / i2v / flf2v）结果节点
   （SaveVideo / 任意输出节点）路径 → **H3 Finalize.video**；
2. **H3 Finalize** 输出（filepath）→ 可直接保存，或接 **H3 ASR Check.media** 做验收回环
   （text_compare 填台词文本 → score 即 ASR 回环相似度）；
3. 也可先 **H3 Local TTS** 单独合成音轨再走后续自定义链（灵活组合）。

## 环境（spark 部署现状）

- 模型（用户指示统一放 ComfyUI models）：`~/ai/ComfyUI/models/f5-tts/{F5TTS_v1_Base,vocos}`、
  `~/ai/ComfyUI/models/asr/sensevoice`（SenseVoice ONNX 量化）；
- 合成/ASR 执行：`~/ai/tts-venv` / `~/ai/asr-venv`（独立 venv，避免污染 ComfyUI 环境）；
- 参考音色样本：项目 `assets/tts_refs/{xiaoxiao,yunxi,aria}.wav`（edge-tts 预生成；
  aria=英文样本）；
- 业务代码：项目 `runs/h3/{tts_local_check,asr_check}.py`（节点经 subprocess 调用，
  路径由 H3_REPO/H3_TTS_PY/H3_ASR_PY 环境变量可覆盖）。

## 部署

`shell/deploy_h3_nodes.sh` —— 复制本目录到 `~/ai/ComfyUI/custom_nodes/h3_finalize/`；
**ComfyUI 下次重启后生效**（本项目不自动重启 ComfyUI 服务——queue 纪律）。

## 已知边界

- 成品链运行在 spark（F5-TTS/SenseVoice 模型与 venv 都在 spark）；win-remote 侧
  ComfyUI 无此环境（登记：远期为远端可用性评估）；
- 节点间传递=文件路径字符串（简单可靠；未来可用 ComfyUI 原生类型增强）；
- 字号 font_size=0=随分辨率等比（字幕规范同项目侧）。
