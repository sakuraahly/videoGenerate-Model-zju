## 14. 修订记录（2026-09-05 用户批评后：模型可用性更正——原「受限/不可行」结论作废）

**用户批评（原话要点）**：① 模型下载不是问题——用**魔搭社区**链路而非 HuggingFace；② 对「Real-ESRGAN 没有则放弃 v2」与「口型驱动=不可行（HF 不可达）」两处结论批评。

**修正（均附实测证据）**：

| 原结论 | 修正 | 证据 |
|---|---|---|
| HF 不可达→任何模型下载类任务默认不可行 | **模型通道=魔搭**：`modelscope.cn` 域可达（302）、`pip index versions modelscope`=1.39.1 可安装；HF 常用模型魔搭有镜像/同构库 | 2026-09-05 linux curl/pip 实测 |
| S2-v2 超分：本地可能没有 Real-ESRGAN→没有则放弃 | **本地已存在，零下载**：`~/ai/ComfyUI/models/upscale_models/` 有 `RealESRGAN_x4plus.pth`(67MB) + `RealESRGAN_x4plus.safetensors` + `4x-UltraSharp.pth` | ls 实测 |
| 口型驱动（Wav2Lip/SadTalker）=不可行 | **可行**：模型走魔搭下载；已有 GPU torch 环境（`sglang-venv` torch 2.13.0+cu130）；管线=人脸检测(S3FD,魔搭)→Wav2Lip 逐帧口型→mux；**与本链 T2b 的关系=先旁白/对白语音→驱动口型→合成**（正是指导意见「先音频→口型→合成」） | 需求=独立 venv 推理；实施期列真实模型 ID 逐一下载验证 |
| 局部重绘 Inpaint=待探测/或不可行 | **可行（升级用途）**：SD1.5/SDXL-Inpaint 模型魔搭可下 + ComfyUI inpaint 节点（KJNodes 已装，核心 inpaint 类节点 ComfyUI 自带）——**主要用途=修复参考图文字乱码区→再 i2v/r2v（文字正确度链）**；视频内局部重绘=逐帧 mask 工程化（远期） | 视频模型 H3 无 inpaint 能力，故定位为「图侧修复」 |
| 中文语音客观验收=依赖人工听测 | **可行（自动化）**：FunASR/Paraformer 或 whisper（魔搭）→ 对 TTS 产物 ASR 转写→与原文比对→自动判「可辨析」；人工听测降为抽检 | 需首次下载 ASR 模型（魔搭） |
| TTS 音色=仅 edge-tts 两音色 | **可行（升级）**：F5-TTS / Coqui 类（魔搭权重+本地 GPU）→ 更自然音色/克隆（克隆需样本，标注隐私边界） | GPU 环境已具备 |
| 交付档=768p 上限 | **可行（管道增强）**：超分 2x（本地模型）→1536×864（>1080p 类）；+RIFE 插帧(魔搭 rife 模型)→60fps；仍如实标注=超分合成，非原生 | 帧率/分辨率由用户选档 |

**新增可行清单（此前被我误判受限）**：① 超分（本地即有）② 插帧（魔搭下载）③ 口型驱动（Wav2Lip）④ SadTalker（更重：3DMM/GFPGAN 魔搭）⑤ 参考图 Inpaint 修复（SD 系）⑥ 中文 ASR 客观验收 ⑦ F5-TTS/音色升级 ⑧ 人脸修复 CodeFormer/GFPGAN（配合口型/人物清晰度）⑨ 伪 1080p/60fps 交付管线。

**新建议优先级（请用户拍板；替换 §13 旧序）**：`P1: S2-v2 超分(本地就位零下载, 即时收益) → P2: 中文 ASR 客观验收(把语音判据自动化) → P3: Wav2Lip 口型(解决「人物说话」终极痛点, 大工程) → P4: 参考图 Inpaint 修复(文字正确度) → P5: SadTalker/F5-TTS/CodeFormer 音色与人脸增强 → P6: RIFE 插帧+伪 1080p 交付管线`。

**自查批评（我此前三处过度保守）**：① 声称「可能没有」却没先 ls 本地 models 目录；② 未测试魔搭可达性即断言「模型下载受限」；③ 将「可行性未知」直接写成「不可行」。均已改正；审核者若发现类似未验证即下结论处，请直接标注。
---

## 15. 审核应答与最终修订（2026-09-05，外部 AI 审阅后）

**结论**：审核全部接受。事实性错误已改入正文（S7 文件定位/S9·S10 全新建标注/S8 更名为“优化”）；设计意见采纳；以下为最终定稿。

### 15.1 审核意见 → 处置对照表

| 意见 | 处置 | 落地位置 |
|---|---|---|
| S7 bind_images_to_template 实际在 refimage.py:175 | 已修订正文 | §7b |
| S9 sessions/list_chats 为全新建 | 已修订正文（标注现状） | §9 |
| S10 quality.py 不存在为全新建 | 已修订正文 | §10 |
| task_watch.poll_batch 缺 `from pathlib import Path`（真 bug） | **已当场修复**（runs/agent/task_watch.py 顶部 import；提交见 git log） | 代码 |
| queue_probe 模块 docstring 与实现矛盾 | 已当场修复（改写为“只有 collect 只读 + cancel_owned_task 唯一写路径且强制归属”） | 代码 |
| S2 先增强后字幕 = 行为反转，需警示 & 检查调用方 | 已警示；回滚=`--postprocess none` 即恢复旧顺序 | §15.4 回滚表 |
| S2 fast 参数固定 vs process() 参数化 | 说明：fast=固定快捷；自定义走 `postprocess.py` CLI 或后期扩展 `--pp-scale/--pp-denoise/--pp-sharpen` | §2（本表） |
| S2 Real-ESRGAN v2 不够具体 | 定稿：**默认 4x-UltraSharp.pth**（锐利、纹理/细节优，适合视频）；RealESRGAN_x4plus 备选（平滑但更稳）；实现=ComfyUI 独立请求：draft 工作流 JSON（UpscaleModelLoader+ImageUpscaleWithModel+SaveVideo? 输出为图序帧或 SaveImage 序列→ffmpeg 组帧）**待核实项：/object_info 确认 ImageUpscaleWithModel 与 SaveImage 的 inputs schema**（写入实施第一步）；触发=agent 提交时 `--esrgan`（h3_submit 新档，独立于 H3 生成队列，走 ComfyUI /prompt 一次性请求） | §2（本表） |
| S7 音轨冲突→混音 | 采纳：旁白-14 主轨 + 参考音轨 -12dB 底轨 amix | §7（已改） |
| S8 O(1) 名不副实 | 采纳更名 | §8（已改） |
| S12 权限过重 | 采纳简化：**一次性 token**（用户点名“用第 X 会话素材”→生成 token 写入目标会话 meta→工具校验 token 即用即弃；无需 CheckboxGroup/持久授权列表） | §11（本表） |
| §14 乐观偏差（Wav2Lip/伪1080p/工作量） | 修正：Wav2Lip 升级为 **L 级（大）**；流程=**先可行性冒烟**（单段 5s 视频+旁白→Wav2Lip→目检口型与画质→合格才全链）；伪 1080p+RIFE 叠加**强制视觉抽检**（双重插值伪影登记）；总工作量按 **Σ单项 ×2-4（集成/测试/回滚）** 估列 | §15.3 |
| 缺依赖图/回滚/并发/GOU 预算/S11 说明 | 补齐：§15.2 依赖图与优先序、§15.4 回滚表、并发=任务目录副本+锁（各处已加）、GPU 预算表 §15.3、S11=“不建议近期”项故规格留空（见 book-13 总览） | §15 |
| §0 cdn.jsdelivr=301 归为不可达不准确 | 已更正：301 为重定向且非必需路径（模型通道已定为魔搭）——见 §14 表 | 事实表 |

### 15.2 依赖图与推荐实施序（含审核建议）

```
S4 idea2prompts↔batch 衔接      ┐
S5 selfcheck-llm（授权）        ├ 第 2 批
S6 音色/字号                    ┘
┊
S1 预览标注  ── 第 1 批（审核认可 S2→S3→S8 为主线）
S2 超分 v2（本地模型就位）── 主线优先（即时收益）
S3 取消残留（依赖 task_watch 修复✅在场）
S8 批量优化（依赖 comfy.history✅ + poll_batch 修复✅）
┊
P2 ASR 客观验收（魔搭模型）── 主线第二批（语音判据自动化）
P3 Wav2Lip（大工程：先冒烟后全链）
P4 参考图 Inpaint 修复 → P5 音色/人脸增强 → P6 RIFE+伪1080p
```
审核建议序=**S2 → S3 → S8**（加上已有 S1/S14）；新 P 序需用户对工作量确认后启动（见 §14）。

### 15.3 工作量与 GPU 预算（诚实口径）

| 任务 | 工作量 | 真机 GPU 预算（每次=提交+等待+取片） | 备注 |
|---|---|---|---|
| S1/S9/S10/S14 | 小 | 0（无 GPU） | 纯 UI/文件 |
| S2-v2 | 中 | 生成链已有（默认 4 步）；超分走 ComfyUI 单次请求≈数十秒×N 次验证 | 超分模型本地就位 |
| S3/S8 | 小-中 | 0 | 依赖修复已在场 |
| S5 | 小 | SGLang 冷启 1-3 分钟×1（授权+队列空闲窗口） | |
| S6 | 小 | ~1 次验证 | |
| P2 ASR | 中 | ASR 推理 CPU/GPU 短时 | 模型下载=魔搭 |
| P3 Wav2Lip | **大（Σ小×4-6）** | 冒烟 5s 视频×1；全链验证×3-5 段 | 先冒烟；质量/耗时实测后决定是否全链 |
| P4-P6 | 中-大 | 各 1-3 次验证 | P6 强制视觉抽检 |

### 15.4 回滚策略（至少对 S2/S7）

| 任务 | 回滚路径 |
|---|---|
| S2 | `--postprocess none` 全局回退旧顺序；v2 超分失败自动降级 lanczos；变更集中在一处钩子（`h3_submit 完成链`）可整段撤销 |
| S7 | 新模板/新函数全部**新增**不触碰现有模板；`--videos/--audios` 未传时行为=现状；废除=删注册与功能开关 |
| S3/S8 | 工具改动作可 `--no-clean` 开关；status 改造保留旧子进程模式为 `--legacy` |
| S12 token | 仅 meta 字段新增；不产生即无行为变化 |

### 15.5 仍待核实的清单（实施第一步逐项确认，确认后再动工）

1. ComfyUI `/object_info`：ImageUpscaleWithModel / SaveImage / Min v（v2 超分工作流 schema）；
2. 魔搭模型真实 ID：RIFE、SD1.5/SDXL-Inpaint、Wav2Lip(含 S3FD)、FunASR/Paraformer、F5-TTS（下一条=下载时长与大小登记）；
3. Ref2VA 节点/模板（spark `/object_info` + 同事模板目录——未确认前 S7 只做 7a 探测）；
4. ~~混音扩展 mix_audio 双轨音量配比~~（**已由三审完成并回填**：mix_tracks 新建+接线+dB 修正+spark 测试通过）；**新增**：ESRGAN 批处理并行的**单卡并发路数与显存上限实测**（3-6min=待验证目标，非承诺）；**新增（五审）**：**建立 requirements/lock 文件口径**——仓库无任何依赖 pin 文件，S13/P2-P6 将引入 modelscope/FunASR/Wav2Lip/F5-TTS 等多套新依赖（独立 venv），无 lock 会快速产生依赖漂移与 venv 边界问题。

**审核闭环**：以上即对审阅意见的完整应答；如审核方复轮，仅需针对 §15.1 未接受项说明理由。
---

## 16. 二轮审核应答与实测修订（2026-09-05）

**审核方主要结论与处置**：

1. S2 不二次转码声明与自身方案矛盾（双次 CRF18）——**已重构为合并单次编码并实测**（process 支持 srt 并入同 -vf；run_full 同步；钩子 fast+tts 并存走合并链）：离线实测 video_31 合并链 **2.4s** 出 1216×704/5.167s；
2. render_subtitle 默认绝对 20px 使先增强后字幕字号静默变小——**默认改比例字号**（0.07xH；实测 704p 字幕≈49px 帧目检清晰）；
3. mix_audio 实为替换非混流（§7 前提错误）——**docstring 更正为单轨替换 + 新增 mix_tracks 双轨混音**（旁白主轨 -14 + 底轨 -12dB amix）；
4. ESRGAN 视频超分成本低估一个数量级——**三审实测更正口径：源帧 1216×704 → 实际输出 4864×2816（4x 模型，非 2432）；单帧 ~11.8s；串行 124 帧约 24min**；采纳 **P1a/P1b 拆分**：P1a=lanczos fast 默认；P1b=--esrgan 交付档可选 + 先做批处理并行优化（**目标 3-6min=待验证目标，非承诺**——加速来源=单请求多上采样分支，需实测并发路数与显存上限（新增 §15.5 项））;
5. §0/§12/§13 与 §14 矛盾——已就地标注（§12 行改注、§13 说明、§12 标题注）；次要项（附录补 run_fast/run_full、S11 缺号补注、§15.2 序号说明、§15.3 次数回填）全部落地。

**实测新增事实（登记）**：ComfyUI 超分节点 schema：`UpscaleModelLoader` 输入键=**model_name**（非 upscale_model）；`ImageUpscaleWithModel`=upscale_model；LoadImage 需 input/ 根目录（user_uploads 子目录不能被直接解析）。

**审核问题“需要我直接落补丁吗？”**——已由本项目落地提交（**Windows 侧哈希：8c971f7/1c4c4d7/fecbcee（三审修复）**；spark 侧对应 84f7b69/d2d4c95/7f5da21；三审修复 fecbcee=dB 后缀+normalize=0+afftdn 补回+run_full 接线+测试），证据=上述实测。**三审新增实测**（spark）：volume 语义=`0.0→-91dB 静音 / -12.0→0dB 削波 / -12dB→-33.1dB 衰减`（审核判断证实）；mix_tracks 真实测试通过（dB 相对差≈12 assert；**该护栏=四审补强后成立**——三审时仅 is_file 断言）；afftdn 已补回 replace_audio_only（attach 与合并路径一致）。

**仍未决/待实施前置（如实）**：① ESRGAN 批处理并行优化（S2-P1b 第一步）；② §15.5 其余项（魔搭模型真实 ID、Ref2VA 探测、amix 权重语义）按确认一项动工一项；③ S2 正式实施（钩子默认 fast 接线）：前置=合并链已就绪（✓）+ 队列空闲窗口 + 回滚开关 --postprocess none（已有）——待第一批整体拍板。

**第三轮建议聚焦**：批处理并行超分可行性验证 + Wav2Lip 冒烟流程设计。