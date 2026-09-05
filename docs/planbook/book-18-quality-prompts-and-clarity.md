# 阶段 16 — 质量提示词固化 + 语音/文字清晰度与正确度加强（book-18）

> 状态：**✅ 实施完成（2026-09-05，用户批准 A-D）**。§1 Q+/Q- 单源固化+consistency_check 质量词断言；§2 语法：台词规范（SYSTEM）+ 脚本规范器（_sanitize_script）+ `--rate=-8%`（等号语法，argparse 修复）+ 单句重试 + `afftdn+loudnorm(I=-14)`；§3 字幕规范参数化（字号=0.07×高、白字黑描边 Outline=2、MarginV=0.08×高）；SYSTEM 规则：台词规范/内嵌文字参考图优先/质量词不得删除。
> 验收：`dev.py test` 质量词断言通过（Q+：masterpiece/best quality/ultra detailed；Q-：blurred scene/motion blur）+ spark dry-run 注入断言（t2v 工作流 prompt/negative 均含新词）+ **语音链真实链视频_31**（608×352/5.167s/124f；旁白「再见了。」1.46s@-8%；loudnorm 后实测 **I=-12.4 LUFS**（目标 -14，含静音段统计，登记）；SRT 0→1.464s；帧目检字幕安全区白字黑描边清晰）+ W2 文字场景沿用（video_25 已过）。**✅ 听测通过（2026-09-05 用户确认）**——book-14 语音判据§12·第4条达成。
> 关联：book-14（T2b 语音链/T2 后期链已落地）、book-17（验收口径§6.5）、book-06（提示词体系/槽位注入）、book-16（台账/归档）
---

## 0. 现状取证（2026-09-05 只读）

- prompts/positive_prompts.txt（default 槽，已固化）：sharp focus, high detail, cinematic lighting, masterpiece quality, photorealistic, 8k, no blur, no distortion, no text, no watermark, smooth motion, 24fps（masterpiece/8k 类正向已含）；
- prompts/negative_prompts.txt（default 槽）：gibberish text, misspelled words, unreadable text, distorted typography, ... broken pixels in text（文字脏词长串已含，防乱码基础尚可）；
- 注入链：manifest.slots → 每槽 positive/negative（缺槽回退 default）→ 模板注入（h3prompts/stage 链路）→ ComfyUI 工作流。
- **缺口**：① 负向缺 blurred scene / motion blur / blurry background / soft focus / out of focus 等防糊词；② 正向缺「文字需求场景」的 sharp legible text 类与「立体层次」类；③ **无『每次运行强制注入+存在性断言』**——防漂移机制缺失（某槽/模板被覆写即漏网）；④ 语音/文字清晰度指导尚未成体系（见 §2-§3）。
---

## 1. 质量提示词固化（用户指令 ①）

### 1.1 统一质量提示词段（进 prompts/ 单源，槽文件引用）
- **正向通用段 Q+**（追加到 default positive 之后，各槽共引）：
  masterpiece quality, best quality, ultra detailed, sharp focus, high detail, cinematic lighting, photorealistic, 8k, no blur, no distortion, smooth motion, 24fps, volumetric lighting, rich composition（保留现状+扩层）；
  **文字需求触发段**（仅当画面含文字/招牌/字幕时由提示词生成追加）：sharp legible text, crisp typography, correct character strokes；
- **负向通用段 Q-**（追加/合并到 default negative）：
  blurred scene, motion blur, blurry background, soft focus, out of focus, distorted, low quality, jittery, warped, deformed, extra limbs, flickering, watercolor, oil painting, anime, cartoon, 3D render, lowres, worst quality；
  文字防乱码段（保留现有长串并补）：blurry letters, smeared characters, melted strokes, jumbled glyphs。

### 1.2 强制注入机制与防漂移
- **单源**：Q+/Q- 只住在 prompts/ 默认槽（+每槽 diff）；槽文件为空一律回退 default（现状已如此——用 dry-run 断言校验）；
- **注入点全覆盖**：h3_submit 各 stage（t2v/i2v/r2v/flf2v）+ batch_submit + dry-run 预览同一处；agent 生成提示词（idea2prompts/build_messages）要求「质量词不得删除、只能追加」（SYSTEM_MESSAGE 提示词规则补一条）；
- **存在性断言**：consistency_check 新增「质量词检查」——扫描各槽产物（dry-run workflow_api 的 prompt/negative）+ prompts/ 文件：必须含 Q+ 关键短语（masterpiece quality）与 Q- 关键短语（blurred scene）；缺失即 [FAIL]（防模板/文件漂移）；
- **验收**：dev.py test 走查 + 真实链 dry-run（t2v/r2v 各 1）断言注入；出片抽帧目检质量词效果登记。
## 2. 语音（人物言论）清晰度加强——取舍表

| 指导意见 | 取舍 | 落地（实施项）/ 说明 |
|---|---|---|
| 脚本层：3-4 字/秒、避生僻/注音、标点明确 | 采纳 | SYSTEM_MESSAGE 台词规则（用户给对白时按短句、常用字、明确标点）；tts.py 前置脚本规范器（标点化+长度提示；--rate -8% 慢读默认） |
| 分离式：视频模型不直接生成语音，专用 TTS + 先音频后合成 | 已落地 | edge-tts 独立合成 + 音轨替换（book-14 T2b v1/v2）；本项目模型链路即「分离式」 |
| 高质 TTS 选型 | 已落地 | edge-tts 中文女声/男声双音色，必要时 --voice 可切 |
| 逐句生成+审听（每句重生成） | 采纳（客观版） | build_srt_speech 逐句合成已实现；审听=客观检查（每句时长>0.3s、响度/峰值校验）+ 单句失败重试 1 次；真人审听项登记为「用户听测验收」 |
| 语速/情感稳定、避免极端 | 采纳 | --rate 默认 -8%；SYSTEM 台词规则避免极端语气词 |
| 口型驱动（Wav2Lip/SadTalker 等） | **暂缓（远期）** | spark 需额外模型/依赖/GPU 与口型管线，当前无素材管线支撑；先以「旁白/对白+字幕双通道」交付（即指导意见的「必加字幕兜底」）；列入远期候选，未承诺 |
| 机位/正面近景/少头部运动 | 采纳（提示词层） | 人物说话场景提示词规则：正面/近景/面部占比大、避免剧烈转头（写进 SYSTEM_MESSAGE 提示词规则） |
| **必加字幕（语音+字幕双通道）** | 已落地 | T2b v2：台词→SRT→烧录（video_27/28 已验证） |
| 音频处理：降噪、**响度标准化约 -14 LUFS**、去齿音 | 采纳（去齿音暂缓） | 音轨替换链追加：loudnorm=I=-14:TP=-1.0（ffmpeg）+ 轻降噪（afftdn）；齿音处理暂不加（收益低/风险高） |
## 3. 视频内文字清晰度/正确度加强——取舍表

| 指导意见 | 取舍 | 落地 |
|---|---|---|
| **后期叠加，不让模型生成**（字幕/标题/图表） | 采纳 | 字幕=libass 烧录（已落地）；标题/图表类=远期（当前无视频模板装配能力，登记为后期链候选） |
| 内嵌文字用参考图驱动（先做文字清晰静态图→i2v/r2v） | 采纳（现有能力） | 用户流程：h3_text2img_flux/外部做「文字图」→上传→call_comfyui stage=i2v/r2v（W2 式）；SYSTEM_MESSAGE 规则：画面内嵌文字需求→先做/要参考图，别指望视频模型直接画 |
| 局部重绘（Inpainting 修乱码区） | **暂缓（作业流候选）** | 现有模板无 inpaint stage；登记为可选新增（ComfyUI Inpaint 模板待工程化），不作为本期承诺 |
| 提示词精确描述（字体/颜色/位置/逐字枚举） | 已采纳补充 | 现有「中文文字渲染逐字枚举」保留；补：字号占比≥1/5、sans-serif、高对比色（仅辅助，效果有限——如实说明） |
| 后期叠加文字规范（黑体/字号/对比/安全区/停留 2-3s/静止） | 采纳（字幕侧） | 烧录规范参数化：Noto Sans CJK（黑体系）+ 字号（360p 基线→24，1080p→40+ 等比）+ 白字黑描边 + MarginV 安全区；SRT 由台词驱动（停留=语音时长，2-3s 可保证）；字幕固定不快速移动 |
| 输出参数：≥1080p、8-16Mbps、H.264/H.265、避免二次转码 | 部分采纳（现实化） | 交付档=720p/768p（本项目上限）+ T2 超分链（1216×704 起）+ 高码率输出（CRF 18/码率参数化）；**1080p 原生不可达**（模型 768p 上限），如实标注；避免二次转码=后处理链一次成片（已遵守） |
## 4. 推荐流程映射（本栈版）

```
创意/对白脚本（短句·常用字·标点——SYSTEM 规则）
  · 画面（视频/文字场景：参考图驱动 i2v/r2v + 逐字枚举）  ← 模型生成
  · 语音（edge-tts 逐句合成 + -8% 慢读 + 单句重试）      ← 专用 TTS
  · 后期（T2b v2 链：字幕烧录(黑体/白字黑描边/安全区) → 音轨替换(apad/loudnorm -14) → PROBE 回执）
  · 验收（PROBE + 帧目检（字幕/文字）+ 用户听测；§12 四条件）
```

## 5. 实施顺序（批准后；每项=修改→dev.py test→真实链验证→文档→dev.py sync/commit）

1. **Q+/Q- 提示词段固化**（prompts/ 单源+槽引用）；
2. **注入链覆盖 + SYSTEM_MESSAGE 规则**（台词规范/内嵌文字规则/提示词不得删质量词）；
3. **consistency_check 质量词断言**（防漂移 FAIL）；
4. **tts.py 追加**（loudnorm -14、afftdn、--rate -8%、单句重试、脚本规范器）；
5. **字幕规范参数化**（字号/描边/安全区常量）；
6. **真实链验证 W-系列复测**（默认档+文字场景+语音场景）+ 用户听测；
7. 登记远期候选（口型驱动/Inpaint/标题装配/1080p）至 book-13 对应条目。

## 6. 验收判据

1. dev.py test：consistency 质量词断言通过（masterpiece quality & blurred scene 存在），单测全绿；
2. dry-run 断言：t2v/r2v 各 1 个工作流 prompt/negative 含 Q+/Q-（含新词）；
3. 语音场景真实链：成品=画面+中文语音+字幕（loudnorm 后响度约 -14 LUFS 客观值）+ §12 第 4 条判据（用户听测）；
4. 文字场景：参考图驱动内嵌文字抽帧目检 0 错字；字幕规范性（字号/边距/对比）抽帧复核。

## 7. 待批准清单

- [ ] **A** 质量词段 Q+/Q-（§1.1）与防漂移断言（§1.2）实施；
- [ ] **B** 语音取舍（§2）：采纳项实施；**口型驱动/Inpaint/标题装配/1080p 原生=远期登记不承诺**；
- [ ] **C** 文字取舍（§3）：字幕规范参数化+参考图驱动规则；内嵌文字以「辅助提示词+参考图」为限（如实：视频模型直接画字不可靠）；
- [ ] **D** 实施顺序 §5（1-5 为本期，6 验收集，7 登记）。
