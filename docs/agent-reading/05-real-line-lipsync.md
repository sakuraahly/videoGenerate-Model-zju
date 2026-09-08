# 真实台词口型链（agent 调用：run_script lipsync_chain.py）

> 2026-09-08 定案：**台词=真台词**。模型生成视频自带的人声为伪英语（ASR 乱码级），
> 不算“人物说的话”。用户要求：角色真的说出设定台词 → 用本链。

## 何时用
用户提出如下任一：人物说话 / 台词 / 对白 / 嘴型同步 / 角色讲旁白（且要有嘴型）/ “真台词”。

## 工具调用（一次完成）
```
run_script(script="runs/h3/lipsync_chain.py", params="--video <人脸源> --line \"台词\" [--voice yunxi] [--narration \"旁白\"] [--asr-check]")
```
- **--line**：台词由你按剧情自主设计（一句话，口语化、切场景；用户给了台词就用用户的）；
- --voice：匹配角色（默认 yunxi 中文男；xiaoxiao 女；aria 英文女；daler 英文男）；
- --narration：可选旁白（垫轨 -15dB，不影响角色台词）；
- --asr-check：自动 ASR 回环验真（台词原文）——报告里引用 ASR_SCORE；
- --video：**近景/正面清晰人脸**的素材（遮挡严重的源会 Face not detected）。

## 链的内容（内部）
1. 台词 TTS（cosy，自然音色）→ 2. Wav2Lip 用台词驱动人物嘴型（人物真的说这句）→
3. keep 收尾（台词字幕默认楷体 + 旁白垫轨 + 原声保留）→ 4. ASR 回环验真。

## 验收判据
- ASR_TEXT 包含 --line 内容（ASR_SCORE ≥0.6=ok）；
- 成品=output 路径（工具返回 LOC）。

## 已知限制
- 人脸源必须可检测（正面/无手遮挡）；口型纹理为 Wav2Lip 96px 模型上限（GFPGAN 修复可选）；
- Wav2Lip GPU 推理 ~1-3 分钟/5 秒片（白天 ≤768p 素材可用；夜间更稳）。