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
| S2-v2 | 中 | 生成链已有（默认 4 步）；超分走 ComfyUI 单次请求（**作用域=单帧**：实测 ~11.8s/帧 → 124 帧≈24min；单卡并发路数/显存上限未测——勿按"数十秒×N"估算） | 超分模型本地就位 |
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

1. ~~ComfyUI `/object_info`：ImageUpscaleWithModel / SaveImage / Min v（v2 超分工作流 schema）~~（**已闭合（十六审 spark 实测）**：三者存在；**更正节点名**：spark 1317 个 class 中无 Min v，真名=**MinNode**（display_name Min，custom_nodes.comfyui-logicutils，Category Math，input1/input2 通配→输出通配——S2-v2 这条依赖属 logicutils 而非 §0 所记 KJNodes）；ImageUpscaleWithModel required={upscale_model, image}→IMAGE；SaveImage required={images, filename_prefix}）
2. 魔搭模型真实 ID：RIFE、SD1.5/SDXL-Inpaint、Wav2Lip(含 S3FD)、FunASR/Paraformer、F5-TTS（下一条=下载时长与大小登记）；
3. ~~Ref2VA 节点/模板（spark `/object_info` + 同事模板目录）~~（**已闭合（九十六审全部取证）**：MiniMaxH3ReferenceToVideo 四 AUTOGROW 槽位 9/3/3/3、ref_videos=IMAGE 帧序列、LoadVideo/LoadAudio/GetVideoComponents 存在且输出槽序一致、双模板树定案=remote_workflows 权威——§7 十～十六审定稿）
4. ~~混音扩展 mix_audio 双轨音量配比~~（**已由三审完成并回填**：mix_tracks 新建+接线+dB 修正+spark 测试通过）；**新增**：ESRGAN 批处理并行的**单卡并发路数与显存上限实测**（3-6min=待验证目标，非承诺）；**新增（十七审）**：交付档升档预算（1080p+`--lora none`20 步 ≈5× 于现行交付档：8→20 步 2.5× × 1.03→2.09MP 2.02×——比表内任何项贵，待原生 1080p 探测成立后启用）；**新增（五审）**：**建立 requirements/lock 文件口径**——仓库无任何依赖 pin 文件，S13/P2-P6 将引入 modelscope/FunASR/Wav2Lip/F5-TTS 等多套新依赖（独立 venv），无 lock 会快速产生依赖漂移与 venv 边界问题。

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
---

## 17. 六审应答（2026-09-05）

**要点**：① §6 高：代码级真伤——`prepare_speech` 未传 voice + `tts_done` 日志硬编码 DEFAULT_VOICE（S6 默认路径失效且验证判据必然误判）→ **已修**（commit 93c1533：`--tts-voice` 参数+任务记录+两路径传 voice+日志实际值）；② 重构残留（6 处悬空引用/§12-§13 双层结构/§9 编辑残片/编号/`---&nbsp;`/§10 双估值）→ 已清理：主文档 §12/§13 改写为当前结论（§13=当前结论表、§14=疑点→结论对照表），编号顺延，悬空引用指向 changelog；③ §2 内部三处矛盾→ 回填已确定事实（schema=UpscaleModelLoader model_name / ImageUpscaleWithModel upscale_model / LoadImage input/ 根目录；倍率=4x：608→2432×1408，测试帧 1216→4864×2816），删除“放弃 v2/外网受限”已撤回措辞与“BatchProcess?”问号；④ probe_av 返回类型归一（int/float；缺失 None）已修；⑤ **自我批评与机制改进**：次轮出现“commit message 声称已修但实际未改”（§6 三轮未动）——**更正机制**：每次“已修正”声明后，对声明落点做机械核对（grep/diff 该文件该行），并以“落点行号+验证输出”记录证据（本轮全部落点均已如此核对）。

---

## 18. 七审应答（2026-09-05）

**两条高**：① §6 声称两条路径传 voice——**else（非合并）分支实际未传 + 日志仍硬编码**（而 P1a 前 else 是唯一路径，voice 会静默失效、验证判据必误判）→ **已修**（commit 1d3e3bb：else 传 voice + 日志实际值；并补 `--tts-voice` **choices=短名/全名**与 **`_V_ALIASES` 短名归一映射**——§6 三处不可执行项同步回填）；② §12 正文仍是被否决的 CheckboxGroup+shared_from[] 设计，一次性 token 只在 changelog（标注“实施者不必读”）→ **§12 已改写为 token 定稿**（§14 结论表述同步）。

**机制（第三次同型后落地）**：应答表/changelog 记录决策、正文未回填、commit message 记成“已修”——**收尾强制检查**：每轮修订后，对应答表每条“已修/已采纳”，**grep 正文关键词必须真出现**（本轮即用 grep 核验：`七审定稿`/`一次性 token`/`sessions list`/`bytes=probe_av` 逐条命中）。

**事故与恢复（诚实记录）**：本轮文档批量 PS 替换中主文件一度被写坏（0 行）→ 已从 git（ac87020）恢复，其余七审编辑改用小步 edit 工具重做并核验；**教训：对 100+ 行单文件，避免用 PowerShell ReadAllText/WriteAllText 整写**，改用 edit 工具定位替换。

**其余中低项**：§9 残片/双“实现”清理（单段明确 list/export/search 参数）；§10 bytes 双源→择一（probe_av size）；§2 行号引用→注释标记；§2/§14 表尾粘连、物理顺序（S11→S12）均已处理。

---

## 19. 八审应答（2026-09-05）

**两条严重（线上回归，均已修复并加测试）**：
① **`_voice` UnboundLocalError**（七审 1d3e3bb 引入）——else（非合并）分支引用仅在 if 分支赋值的 `_voice`；而 P1a 前非 fast 是 agent 唯一路径 → **今天所有带台词 agent 提交“有画面、无语音、无字幕”且不报错**（被宽泛 except 吞掉）；② **`_tj` UnboundLocalError**（六审 93c1533 引入）——仅 CLI 未给 tts_text 时赋值，但 task_folder 为真即引用（P1a 落地后 fast+CLI 台词路径必炸）。

**影响评估（取证）**：spark 现行代码（87f3979 起）确认含缺陷行（897/908）；但 spark 日志全部 `tts_done` 成功事件（video_22/27/28/29/31）均发生于 **22:06（回归提交）之前**（10:26–20:34，运行代码为回归前版本）→ **尚无任何生产任务在缺陷代码下运行**；下次带台词提交即中招。日志 grep：`tts_error err=UnboundLocalError` = 0（spark）；本地 logs 无 tts 事件（非 spark 运行日志）。

**修复（待提交）**：
- `h3_submit.py`：钩子抽为模块级 `_run_tts_hook()`，`_voice`（任务记录>args>默认）与 `_tj`（无条件初始化，job.json 缺失→{}）移至两分支共用前置；**except 分类**：NameError/AttributeError（含 UnboundLocalError）→ `tts_code_error` 事件 + stdout `TTS_CODE_ERROR:` 显式标记（不再混入“不影响主产物”提示）；ValueError 等环境异常保持 `tts_error`；钩子返回解析后的 tts_text（下方仅-fast 分支历史语义保留）。
- `tts.py`：新增公开 `VOICE_ALIASES`（短名→全名）；**`_V_ALIASES`（原 main() 局部，§6“tools 侧复用”不可执行）已提升并删除**——八审方案 A：tools 透传短名、不做映射，归一仍由 h3_submit 入口完成；文档判据同步改 `--tts-voice yunxi`（argv 短名）/ `tts_done voice=zh-CN-YunxiNeural`（记录全名）。
- **测试**：`runs/h3/tests/test_tts_hook_voice.py` 7 例（monkeypatch h3.tts/h3.postprocess，无 ffmpeg）——覆盖 1.1（else 用 voice）、1.2（fast+CLI 文本+task_folder 无 job.json）、无 task_folder、任务记录回读、无台词跳过、代码缺陷 vs 环境异常分类；全套 165 例绿（158+7）。

**真机验收（spark 实测，2026-09-05 22:43）**：① 非 fast 路径——真实 h3_submit 任务（video_32 源）跑通提交/轮询/落盘，钩子失败点为 edge-tts 网络抖动（`tts_error err=ValueError` 正确归类为环境异常）；随后在真实产物+真实任务记录（job.json=风筝真美。/全名 yunxi）上重跑钩子 → `TTS_OUT speech_s=2.06 srt=yes`，产物 video_tts_a.mp4=**h264+aac**，video_tts_a.srt 内容正确（0→2.064s），时长 5.167s 不变——**修复 1.1 + 任务记录回读 + 短名归一（记录=全名）真机通过**；② fast 路径——CLI 台词+无 task_folder → 合并单次编码链输出 video_tts_b_pp.mp4=**h264+aac**（`TTS_OUT`+`POSTPROCESS_OUT` 双标记）——**修复 1.2 真机通过**（单元层面同套件 7 例亦绿）。

**机制补充（第 N 次同型后落地）**：`_run_tts_hook` 之前的主干钩子属“新代码路径零测试”——此轮后**新钩子/新分支必有单测**（无 ffmpeg 也可 via monkeypatch），且“两条路径共用变量”必须前置初始化（而非分支内首次赋值）。

**其余**：§2 line 41 残留误写“（1216→2432）”已更正为“1216×704→4864×2816（4x，与 line 40 口径一致）”；§6 实现/验证按八审 Option A 回填（映射层位置+短名判据+“勿再写 tools 侧复用映射”）。

---

## 20. 九审应答（2026-09-05 · S7 最大工程专项）

**九审意见 → 处置对照表**（每条均已按“声明后 grep 落点”机制核对；除文档修订外**未改任何代码**——S7 仍是待实施任务，本轮只修规格）：

| # | 级别 | 意见 | 核查结果（证据） | 处置 |
|---|---|---|---|---|
| 1 | 高 | §7 漏必需落点：uiapi.py 需为 LoadVideo/LoadAudio 增转换分支（LoadImage 有专属特例 uiapi.py:273-276，通用路径对文件选择器类节点是错的） | **成立，且查明了精确失效机制**：LoadVideo/LoadAudio 的 object_info 只声明 1 个必需 COMBO（file/audio，cfg 含 video_upload/audio_upload 标记），但 UI 节点 widgets_values 记 2 值（文件名 + upload 展示值 "image"）——实证 spark 同事模板 utility-gan_upscaler.json node 9（LoadVideo widgets=["MiniMax_H3_00035_.mp4","image"]）；走通用路径（uiapi.py:277-306）消费 1 值后触发 :302-305 残留值检查 → UiUnsupported（“2 个 widget 值无法按定义分配”） | §7 7b 新增**落点 1**：文件选择器类转换分支（与 LoadImage 特例并列：只取首值写入 file/audio 并 widgets.clear()），列为 7b 完成度必要判据 |
| 2 | 高 | §7 “dry-run 断言图注入”离线不可达成——7 份模板全为 UI 格式，转换需 live client，否则 ParamError | **成立**：本地 7 份模板按内容判定全部为 UI（nodes/links/widgets_values）；stage.py:322-326 无 client 抛 ParamError | §7 验证改为**两级判据**：一级=在线 convert_ui_file 的 API dict 断言（class_type 存在/inputs 只含预期 key/ref 槽位接线正确，可 mock client 单测）；二级=真实提交 ffprobe/抽帧/听测；dry-run 只保留 UI 层图注入断言；原表述标记作废 |
| 3 | 中 | 3 份 api_.json 实为 UI 格式，“×api/video”表述误导格式判断 | **成立**（逐一实测：api_minimax_h3_* 全部 nodes/links/widgets_values；如 api_minimax_h3_r2v.json 含 MinimaxHailuo03ReferenceNode+LoadImage+SaveVideo） | §7 现状改写：7 份全 UI；“api_*”=Comfy 云通道模板命名≠API 格式（本地可执行=4 份 video_*）；同步 §0 新增转换链事实行 |
| 4 | 中 | §7a 登记默认值与需求相反（add_local 写空 slots + reference_videos:False；workflow_registry.py:190-200 返回消息即写“请补全”）；另更正上轮怀疑：reference_videos 非双源 | **成立**：add_local（workflow_registry.py:184-200）写入 slots 三池全空 + features 全 false（:190-196），返回 “已登记 …请补全 slots/inject_spec 并 validate”；**更正接受**：workflow_registry.py:4 明确“单一来源：config/capabilities.json”，:195 只是 add_local 的默认值模板，非第二来源（上轮“双源”判断有误，在此更正） | §7 7a 增加**登记后补全**步骤（扩展 add_local 接受 slots/features 参数为推荐方案，或登记后 patch+validate_all；禁止只登记不补全），并给目标条目（slots=9/3/3、features.reference_videos=True/audio=True）与 template_health 需扩展数 LoadVideo/LoadAudio 的提示 |
| 5 | 中 | bind_images_to_template 的 template 参数可选、默认原地写共享模板（book-11 事故）；新建 bind_refs_to_template 应设为必填 | **成立**：refimage.py:184 tpl=Path(template) if template else _stage_template(stage)；:201 tpl.write_text(...) 原地写回；docstring 自记“默认绑定【共享模板】（历史行为）；调用方传入 template 时绑定该副本” | §7 7b 落点 2：新函数签名 **template 设为必填**（无历史负担），任务副本沿用 h3_submit.py:484-487 的 copy2+绑定模式 |
| — | 对应补充 | （九审结论段）7b 工作量应上调；“探测失败即归档”取舍正确 | 采纳 | 工作量改为**大（7a 小 / 7b 中-大 / 7c 小）**，7b 五个落点写明；归档取舍保留 |

**九审过程中新取证（超出九审意见本身，写入 §7 作为已定案事实，实施期无需再探测）**：
- MiniMaxH3ReferenceToVideo（spark live object_info）optional=COMFY_AUTOGROW_V3 ×4：ref_images（ref_image: IMAGE，max 9）、**ref_videos（ref_video: IMAGE，“Reference video frames at 24 fps (2-15s)”，max 3）**、ref_video_audios（ref_video_audio: AUDIO，“Soundtrack of the same-numbered reference video”，max 3）、ref_audios（ref_audio: AUDIO，max 3）→ **ref_videos 槽位类型是 IMAGE 而非 VIDEO**：LoadVideo 不能直连，必须经 **GetVideoComponents**（VIDEO→images IMAGE + audio AUDIO + fps/bit_depth/color_space；spark 同事模板 utility-gan_upscaler.json 已实证同型链）→ images 接 ref_videos、audio 接同号 ref_video_audios；LoadAudio（audio COMBO）→ ref_audios。
- **本地 video_minimax_h3_r2v.json 就是 Ref2VA 模板**（MiniMaxH3ReferenceToVideo id 136 + 全套 ref_* 槽位仅未接线；8 张 LoadImage 仅 2 张接 ref_image_0/1，其余 6 张为死链由 prune_dead_output_nodes 清理）——原“无 Ref2VA 模板、第一步须探测”表述更正；7a 的“探测失败即归档”仍保留为版本不符时的兜底。
- spark core 已有 LoadVideo（comfy_extras/nodes_video.py，io.Combo file + video_upload）与 LoadAudio（nodes_audio.py，io.Combo audio + audio_upload）。

**机制备注**：本轮为纯规格修订（spec §0/§7 + changelog + session-summary + handoff 同步），未动代码，故无单测/真机验收；所有“成立/采纳”声明均已按落点 grep 机械核对（§7 更新后 grep：uiapi.py 文件选择器、GetVideoComponents、template 设为必填、登记后必须补全、两级判据、中-大 逐条命中）。
---

## 21. 十审应答（2026-09-05 · S7 规格复核）

**正面清单确认（九审 §7 断言逐条抽查，全部属实）**：node id 136／四类前缀名一致／ref_videos 槽位类型=IMAGE（最反直觉且最关键）/ref_video_audios+ref_audios=AUDIO／8 张 LoadImage 仅 2 张接（link 278/282）／uiapi.py:302-305 残留 widget 触发 UiUnsupported（stale 语义推理成立）／prune_dead_output_nodes 在 :48／template_health 只数 LoadImage（:128-130）／add_local 空 slots+features 全 false（:177-200/:190-196）／stage.py:322-326 ParamError。

**十审意见 → 处置对照表**：

| # | 级别 | 意见 | 核查（证据） | 处置 |
|---|---|---|---|---|
| 1 | 高 | 槽位计数错误（images 实为 8 非 9；videos/audios 各 1 行非 3），且同段自相矛盾（后文自写 slots.images=8） | **成立**：实测 node 136 inputs——ref_images=8 行（ref_image_0..7，仅 0/1 接）、ref_videos/ref_video_audios/ref_audios 各 1 行（index 0，均 link=null）；2.1 数学链成立（按 count:9 登记 → template_health :130 “期望 9 实际 8”） | §7 现状段改两栏口径（模板已暴露行数 8/1/1 vs node 上限 9/3/3）；7a 目标条目 images count=**8**（勿写 9；第 9 行=行合成扩容，非本任务目标）；videos/audios 保持 3=能力口径并标注来源 |
| 2 | 高 | “上限 3”未区分模板行与 node 支持上限，实施成本差一个量级 | 成立（两栏实测数字见上） | 同上（现状段两栏表列式；7a/7b 引用时注明口径） |
| 3 | 高 | 7b 接 N=2..3 需合成 UI 输入行；_wire_slot 硬编码 “IMAGE”（:551）与源拾 0（:554），音频接线需 “AUDIO”+GVC 槽 1 | **成立**：_wire_slot（refimage.py:541-556）:551 链接类型硬编码、:554 输出匹配按 IMAGE/“”且只取首个；:547 假定目标行已存在。**更正一点**：目标行合成并非“现有代码无能力”——同构先例= `grow_slots`（refimage.py:497-526：追加 ref_image_N 行 + _clone_loadimage 克隆占位），仅泛化缺失（前缀/类型/输出槽/节点克隆硬编码） | 此缺口在**设计 B（主案）下全部消失**（无 UI 行合成）；已写入 §7 备选（设计 A）清单作翻案记录，含 grow_slots 先例引用 |
| 4 | 中 | 设计替代未记录：API 层注入（apply_lora 先例 stage.py:196-213）可省掉落点 1 与落点 2 大部；代价=UI 往返缺失与字符串 id 脆弱史（96d2188） | **成立**：apply_lora 实为 :180-220（`new_id="lora_"+str(len(wf))` 字符串 id + 全图重接线），调用点 h3_submit.py:545；96d2188 注释（workflow.py:165）确认字符串 id 曾致 UI 仅 API**——采纳并定稿：主案=设计 B**（理由：同型先例生产验证过/槽位键注入零成本/免 uiapi 分支与簿记；注入 id 用数字字符串规避脆弱史；代价=双注入点分裂与模板副本 UI 无参考节点，如实记录） | §7 新增“设计决策”段（A/B 对照+定稿+代价）；落点 1（uiapi 文件选择器分支）**从主案移除**（B 下转换器不会遇到 LoadVideo/LoadAudio，降级为已知边界）；备选 A 完整记录三缺口+ grow_slots 先例 |
| 5 | 低 | 模板簿记实测可回填：last_link_id=282、links 25 条、节点总数 29 | 成立（另实测 last_node_id=140）；_wire_slot 用 max(links)+1 规避了 link 簿记，但新建节点需同步 last_node_id | §7 现状段回填四值（A 备选清单含簿记同步项） |

**自查补充（十审未点名、按印证逻辑发现并已修）**：上轮 7c 的 tag 映射差 1——官方 `<Video N>` 从 1 起（按连接顺序）、槽位键从 0 起（ref_video_0），上版写 “<Video N>→ref_videos.ref_video_N” 错误，已更正为 **N-1**（`<Audio N>` 同）。

**机制**：本轮零代码改动（S7 仍待实施）；“采纳/成立”均已按落点 grep 核对；模板计数用程序化统计（collections.Counter 按点分键前缀），非目测。
---

## 22. 十一审应答（2026-09-05 · S7 接口约定层复核）

**一、更正接受（十审曾断言"追加 UI 输入行现有代码没有"——十一审的更正本身也须再核）**：核验 `grow_slots`（refimage.py:497-526）确实已实现目标行追加（:518-521）+ `_clone_loadimage` 占位克隆（:480-494，docstring 点名 COMFY_AUTOGROW_V3）；**采纳更准确的缺口表述**：能力已有（grow_slots＋_wire_slot），A 的缺口=参数化。已按"四处硬编码"表写入 §7 备选 A（① 前缀 :511 → ref_videos./ref_video_audios./ref_audios.（_owner_rows :529-538 已前缀泛化）；② 类型 :520/:551 "IMAGE"→"AUDIO"；③ 源输出槽 :551/:554（0＋按名匹配）→GVC audio=槽 1；④ 占位节点克隆 :522 → LoadVideo/LoadAudio），并**降低 A 成本估计**（"中"而非"大上沿"）；主案 B 维持不变（B 连 uiapi 分支都省）。

**二、【中】§7c 双通道（tag 文本 vs --videos 列表顺序）不一致风险——最实质**：
- 核验对称性：tools.py:296 明确"r2v 按顺序绑定"（位置序）；bind_images_to_template:191-200 顺序填槽；全仓无 `<Picture N>` tag 约定——**images 位置序、video/audio 将引入 tag，不对称属实**。处置=§7c 写明理由：视频=动作参考/音频=氛围参考须在提示词显式指代（H3 官方 Markdown 即 "reference the inputs by tag, in the exact order they were connected"）；图片=身份/场景参考，既有链已由 refimage use --slot N 位置管理覆盖，保持不动（官方 `<Picture N>` 列为可选增强低优先）。
- 核验静默错配：情形表成立（tag 越界/顺序错位时产物正常、ffprobe 与一级判据全过、参考关系错）——**采纳定稿硬约束**：槽位由 `--videos/--audios` 列表顺序**唯一**决定；tools.py 拼装时校验 tag 序号集合 == 列表索引集合（{1..len}），不一致**报错拒提交**；SYSTEM_MESSAGE 明示一一对应；一级验证判据④升级为"一致性守卫（上限>3 报错 + tag/列表一致）"。

**三、【中】设计 A 缺口补两条**：
- 3.1 **核验成立**：`_clone_loadimage`（:485-486）max(id)+1 分配新 id，但 grow_slots（:497-526）全程未触碰 `last_node_id`（:525 直接写回）；正确算法在 workflow.py:255（max(node_ids)）但 refimage.py 未导入 workflow（:432 仅局部导入 workflow_registry）→ §7 备选 A 已补"⑤ 复用 max(node_ids) 更新 last_node_id"（后果=UI 打开扩槽模板后新节点 id 冲突）。
- 3.2 **核验成立**：grow_slots 签名仅 (tpl, total, defaults)，:525 原地 write_text、无副本参数——并发风险高于 bind_images_to_template → §7 备选 A 已补"⑥ 按 template 必填/任务副本原则改造"（与 bind_refs_to_template 同原则）。

**四、【低·正面】本地佐证采纳**：refimage.py:487 `new["widgets_values"] = [defaults[slot % len(defaults)], "image"]` —— 本项目克隆逻辑自身生成"文件名+展示值 image"双值模式，与 spark utility-gan_upscaler.json node 9 实测同构（LoadImage 声明 2 输入故不残留、LoadVideo 仅声明 1 输入故必残留——与 uiapi.py:302-305 stale 检查吻合）→ 已作为**双源证据**写入 §7 备选 A 前置（uiapi 文件选择器分支）依据栏。

**五、【低】defaults 取模**：确认 8 项取模（:487/:504-508）slot=8 回绕复用 defaults[0]，但占位节点 mode=4（:490）不参与生成、无害——支持"7a images=8 勿写 9"（写 9 不会 IndexError，但引入重复占位名且被 template_health 判"槽位不足"）→ 已记录在本应答，spec 维持 8。

**机制**：零代码改动（S7 仍待实施）；"成立/采纳"均按证据行 grep 核对；A 成本估计下调已同步 §7 备选段与工作量（主案 B 不变）。
---

## 23. 十二审应答（2026-09-05 · S1 专项 + §7b 上传链确证）

**十二审意见 → 处置对照表**（本轮含**代码小修**：注释/文案——其余仍为规格修订，S1/S7 均待实施）：

| # | 级别 | 意见 | 核查（证据） | 处置 |
|---|---|---|---|---|
| 1 | 高 | _known_shas 非存在性判定（日志 sha 集合），与 _asset_available 语义相反 | **成立**：ui_app.py:755-774（mtime 缓存 + log.jsonl sha 集合）；文件已删/归档失败后仍在集合 | §1 前提更正 ①：_asset_available=文件系统存在性检查；_known_shas 仅作候选集；**撤销原"风险低/小"标注**（元观察采纳） |
| 2 | 高 | 可用性判据查错位置：提交链经 /upload/image（subfolder=""）落 input/ 根目录；user_uploads 镜像只服务 refimage 列举；ui_app.py:825 "LoadImage 立即可见"注释错误 | **成立**：h3_submit.py:468→comfy.py:202/58/217→:486（API 返回名 bind）；refimage.py:105（递归扫 user_uploads，注明"顶层扫描会漏"）；六审实测"LoadImage 需 input/ 根目录"与之无冲突——冲突源是 :825 注释 | §1 前提更正 ②（可用性=本地归档/源文件存在性；"可重新上传即可用"）；**已修正代码注释** ui_app.py:825（refimage 可见/LoadImage 不可见） |
| 3 | 中 | S1 在 Windows 侧不可开发不可验证（_comfy_input_dir 本机路径 + 无 gradio） | **成立**：ui_app.py:738-747（本机路径，Windows 克隆恒不存在）；五审已确认 Windows 无 gradio | §1 标题与验证段显式标注 **spark-only**（Windows 只改码不验证，sync 后在 spark 验证；不得 Windows 宣称通过） |
| 4 | 中 | gallery 第三个生产者 :1417+list(_thumbs) 未列入 → 混合形状列表；回退路径需 caption 兜底 | **成立**：ui_app.py:1411-1417（_thumbs 裸字符串；:1416 失败回退 str(src)）；:1365/:1376/:1417 共 4 处写点（:1376 空列表无需改） | §1 实现改为**三个改动点**（:1411-1417 元组化 + 回退路径 caption 兜底） |
| 5 | 正面 | §7b 上传复用可行（客户端无需新增 upload_file）；未验证项=服务端类型校验；comfy.py:225 文案宜中性 | **成立**：comfy.py:52（name="image" 端点要求）/53（octet-stream 与类型无关）/42（type=input）/58（subfolder 空→input/ 根）；:225 文案"图片上传被拒绝" | §7b 上传段**定稿=直接复用 upload_image**（四证据+删"或新增 upload_file"）；§7a 复核清单加一条 curl .mp4 上传验证；**已修代码** comfy.py:225 → "上传被拒绝"（中性；grep 测试无断言，安全） |

**元观察回应（十二审点明"审阅覆盖度由注意力驱动"）**：成立——S1 被标注"风险低/小"且 11 轮未动，与两处前提性错误（均高）矛盾；已修正 S1 的风险/工作量标注并完成前提修复。**按十二审建议登记后续覆盖计划**：下一轮覆盖 S12 一次性 token 生命周期（meta.json 并发写/token 过期判定/用后即焚与 refimage 调用时序）→ S13 远期池 → changelog 文件本身（~210 行）——这些此前同样从未逐条核验。

**机制**：本轮代码改动=2 处（注释/文案，无逻辑）；已跑单测基线（165 例）确认无断言依赖；规格落点 grep 核对。
---

## 24. 十三审应答（2026-09-05 · S12 专项）

**十三审意见 → 处置对照表**（本轮零代码改动——S12 仍待实施；按用户要求"慎重采纳、不引入副作用"：选方案时避开对热路径/既有接口的改动）：

| # | 级别 | 意见 | 核查（证据） | 处置（定案） |
|---|---|---|---|---|
| 1 | 高 | token 写 meta.json 会被 ui_app.py:160-163 每轮 w 模式 3 键覆写 → 静默消失且失效滞后 | **成立**（ui_app.py:160-163 实读：w 模式 + json.dump 3 固定键字面；session_cleanup.py:51/93 为读者；无锁非原子） | **定案=方案 (b)**：独立文件 `<cid>.grants.json` + tmp+replace 原子写（仿 tts.py:194；meta.json 非原子写问题一并规避）；**不改 ui_app.py:160-163 热路径**（避免回归；方案 (a) read-modify-write 列为备选、不采纳） |
| 2 | 高 | shared- 被 normalize_session 原样透传 → 按 cid 过滤 → 静默空 + 提示反引导 --scope-all | **成立**（normalize_session :259-269 return v；cmd_list :309-319 按 cid 过滤；:306/:313 提示语确反引导） | **接口定案=魔术值 shared-<target>**（不新增 flag）：normalize_session 增前缀识别拆分 target；cmd_list 增 shared 分支（含区分失败原因提示）；tools.py:441-448 增第三分支；提示语反引导修正写进实现 3 |
| 3 | 高 | §12 接口不一致（设计行 shared- 魔术值 vs 实现行 --scope-shared flag） | **成立**（原文两行并存；两方案改动点已在表内） | 统一为魔术值（改动面：normalize_session+cmd_list+tools 分派点）；--scope-shared 作废 |
| 4 | 高 | 签发者未定义；调试点/工具自动签发=模型自我授权，与"默认不授权"矛盾 | **成立**（§12 原文"token 由调试点写入"）；**自我归因接纳**：该缺口部分源自上轮（审查者一轮建议"只说了用户点名→生成 token→用后即焚，未指定签发者"）——本轮定案补齐 | **签发者定案=对话显式确认轮**（人类弱在环）：新白名单工具 `grant_refs(target, reason)`，守卫=当前轮用户消息含明确授权声明（启发式"允许/可以/同意+目标会话"）；禁止模型/自动签发；audit 留痕；更强在环（UI 瞬态确认弹窗）=可选增强；scheduler.py:55 情形②与 :121/:123 铁律已有落点 |
| 5 | 高 | 宽松路径 session=all → --scope-all 仍敞开且被工具描述主动教给模型 → S12 无安全收益 | **成立**（tools.py:443-448 else 分支 + 工具描述原文） | **定案=保留但登记收窄**：不退役、不要求 token；收窄引导=工具描述升级（优先指出 shared-<target> 精授权路径）；**登记**：S12 不改变 --scope-all 暴露面，收窄需另立项（如实标注为 S12 安全收益上限） |
| 6 | 中 | 用后即焚+只读工具+LLM 重试 → 二次调用失败 → 回退 --scope-all，比现状更差；建议绑 turn_id | **成立**（turn 机制实测：ui_app.py:1099 increment_turn_id 每轮递增 + :1147/:1234/:1251/:1295 check_turn_valid） | **生命周期定案=轮末失效**：grant 记录 turn_id；一轮内可重复读（重试安全）；下一轮自动失效；无需持久焚毁状态机（"用后即焚"语义=轮末，非一次调用） |
| 7 | 低 | meta.json 三写者/无锁/非原子写；项目已有 tmp+replace 先例 | **成立**（ui_app.py:160 写者/refimage 未来消费者/session_cleanup 读者） | grants.json 原子写要求写入 §12 实现 1；不修 meta.json（避开热路径） |

**元观察回应**：剩余未审查=changelog 本身（~227 行，承载全部修订历史，仅抽查过零星 spark 实测数值）、S13 模型可得性依据、§15.3 GPU 预算表——**登记为下一轮覆盖计划**（建议先 changelog，其事实性声明对后续轮次响应具有基准作用）。

**机制**：零代码改动（S12 待实施）；"成立/采纳"均按证据行 grep 核对；用户要求"慎重采纳、不引入副作用"已落实——所有定案选择均优先"独立文件/复用既有机制/不碰热路径"。
---

## 25. 十四审应答（2026-09-05 · changelog 核验 + 模板树专项）

**一、changelog 抽查（正面确认）**：簿记四值（140/282/29/25）精确；165 例绿可复现（仓库根 `py -3.13 -m pytest runs/h3/tests -q` → 165 passed，跳过项=ffmpeg 依赖 test_mix_tracks，符合 docstring）；官方 tag 原文命中；COMFY_AUTOGROW 上限与官方一致；差 1 更正记录准确；两处自我归因记录完整——§18 后"声明后 grep 落点"机制确证生效。

**二、【高】双模板树分叉——定案完成（一条命令级探测，非推测）**：
- 实测：win 双树 r2v=32283B/a0b6e74f9be7/29 节点/8 LoadImage/8 图槽 vs 28839B/51023413dfea/23 节点/2 LoadImage/3 图槽（与十四审完全一致）；**且 i2v/t2v/api_* 5 个共享文件亦分叉**（节点数相同、字段级差异；config/templates 缺 flf2v）；
- **定案（ssh 实测）**：win 与 spark 的 `config/pipeline.json`（机器配置不入库）`templates_dir` **均=workflows/remote_workflows**；`bats/workflow/sync_remote_workflows.bat`→`shell/sync_remote_workflows.ps1` 同步目标=remote_workflows；capabilities/refimage/template_health 均以它为基准 → **权威=remote_workflows**；pipeline.example.json 默认值 config/templates=陈旧（仅显式指定才生效）；
- **处置（零副作用）**：不改 config/templates 内容（不覆盖/不删除）；修正 `pipeline.example.json`（templates_dir→workflows/remote_workflows + _comment 说明）；`tools.py:159` 描述与 :35-38 allowlist 一致化（两棵均允许、spark 同事模板只读）；§7 新增"双模板树事实"段 + 7a 补 **pipeline.json 注册**（stages/remote_workflow_templates 键/templates_dir 确认；pipenline.json 不入库→spark 就地改）——缺此则 7a 登记后 stage 不可提交。

**三、【高】模板内嵌官方文档三条回填（MarkdownNote id 116，14 轮来首读）**：① BasicScheduler=simple（:124）而官方建议参考密集用 beta/normal（KSamplerSelect=res_multistep :123 一致）→ §7 登记零成本改进（stage.py:292 同点覆写 scheduler_name；验证档 simple/交付档 beta）；② ref_image_size 从未参数化（固定 match；uiapi.py:129 注释是唯一提及）→ 7a 目标 params 增 ref_image_size（match 验证档/max 交付档+速度代价官方原文登记）；③ 官方"up to 2K"→ §13 1080p 行标注改为"原生 1080p/2K 待探测（不带 LoRA 提交一次）+768p 上限来源待查"，撤除"非原生"定论；④ tag 契约原文（in the exact order...matching the reference tags precisely）→ §7c 提升为**厂商契约依据**。

**四、【中】images=8 vs 官方 9**：§7a 已补显式取舍登记（count=8=模板现状+template_health 口径；第 9 位=grow_slots 可选增强；**注意**：count=8 时 agent 会拒绝第 9 张参考图——注册表与实际能力一致性如实标注）。

**五、【低】测试套需从仓库根运行**：确认（runs/ 下 discover → 3 个 ModuleNotFoundError: No module named runs；仓库根 → 165 OK）；**已采纳**：handoff §2 单测命令补"必须从仓库根运行"；本应答记录（含十四审自述"第一次误判"的复现路径）。

**机制**：本轮改动=代码/配置 2 处小修（tools.py:159 描述、pipeline.example.json 值+注释；均无行为面扩大：描述与 allowlist 一致化/example 默认值向运行配置对齐）+文档（§7/§7a/§7c/§13 回填）+changelog/session/handoff；单测基线 165 例重跑确认。
---

## 26. 十六审应答（2026-09-05 · spark 全量只读取证 + 分辨率/模板真相）

**一、正面确认**：§0/§7/§13 的 spark 断言逐条实测为真（魔搭 302+1.39.1、torch 2.13.0+cu130、超分三文件+UpscaleModelLoader COMBO 确认、LoadVideo/LoadAudio 单 COMBO、GVC 输出槽序、AUTOGROW 9/3/3/3、ref_videos=IMAGE、templates_dir 一致）；**ref_image_size 口径更正**：required COMBO（options=[match,max]，default=match）而非 optional——API dict 必须始终携带该键（§7 引用已按此表述）。§15.5 第 1/3 项闭合（1 更正节点名=MinNode/comfyui-logicutils，非 Min v/KJNodes）。

**二、高——768p 上限已查实（结论强于待探测）**：模型本体不施加 768p（width/height max=16384 step=32、ResolutionSelector megapixels max=16.0）；768p=项目侧硬编码 6 处（workflow.py:18-24 RESOLUTION_PRESETS/tools.py:260/792/capabilities.json 四 workflow params.resolutions/workflow_registry.py:193/h3_text2img.py:40）；**探测无需改代码**：params.py:200-204 逃生口（width+height 同时给出→绕预设表，%8、64-4096）+ h3_submit.py:285-286 --width/--height；**CLI-only**（tools.py 全文 width/height 0 命中，agent 路径够不着）；**口径冲突**：逃生口 %8 vs 节点 step=32 → 正确探测值=**1920×1088**（朴素 1920×1080 会通过项目校验但违反节点约束）；项目上限 4096 < 节点 16384。→ §13 已改写（含三合一探测提交方案=1920×1088+--lora none 一次定三事，**待用户授权队列空闲窗口**；若原生成立 P1b 立论消失、S2-v2 优先级重排）。

**三、高——孤儿模板与设计 B 边界**：① `video_minimax_h3_flf2v.json`=孤儿（capabilities.json:262 在用 / §8 line 59 批量目标，但 sync 脚本 $names 与 pipeline.example remote_workflow_templates 均 6 项缺它——无 spark 源、不可追溯；解释"7 vs 6"差值；flf2v=本地扩展）→ §7 双树段补充；② 设计 B 边界：注入在转换后发生故不受 flatten 重排影响，但任何跨转换预置节点 id 逻辑不可用；设计 A 作用于子图模板会出现第二个 stale 簿记源（subgraph.py:243-246 只换 nodes/links；与十一审 ⑤ 同类）——§7 已补适用边界（A 仅适用 r2v 开放图）。

**四、中**：§0 转换链行补完整链（convert→flatten→ui_to_api）与子图事实（4 份 video_ 中仅 r2v 开放图）；§15.3 S2-v2 预算行修正（作用域=单帧：11.8s/帧→124 帧≈24min，非"数十秒×N"）；ref_images tooltip 2048 短边封顶（downscaled to 2048 short edge if larger, never upscaled）→ §13 Inpaint/参考图增强记录（修复产物有效分辨率封顶 2048）。

**五、低**：length 量化式（length ≡ 5 mod 17；5s→124、15s→362）→ §0 新增事实行+§2/§6 判据引用该式；三时长上限并存（60.0 仅警告/15s 能力上限/scheduler 冲突口径）→ §0 登记（事实口径=15s）；capabilities 工具级 schema /tools/1/params/seconds 无数值界 → §0 登记低项；pipeline.example.json:2 自相矛盾（追加修正未改正，字符串内仍写 config/templates）→ **已修**（改为 templates_dir 下模板文件名）；RealESRGAN_x4plus.safetensors 权限 600（同属主，ComfyUI 已正常读入）→ 仅记录。

**六、唯一待真机项（不单方执行）**：1920×1088 + --lora none（20 步）探测提交（定：墙钟/显存、LoRA 768p+ 可用性、服务端 step 强制）——已登记 §13 + §15.5 对应更新（项 5 待用户授权队列窗口）；§15.5 第 2 项（魔搭真实模型 ID）仍未闭合（本轮=通道级验证 ≠ 模型可得）→ §13 三项"可行"维持通道级结论。

**机制**：本轮文档/配置修订（§0/§7/§13/§15.3/§15.5 + pipeline.example.json 注释修正）；零行为面扩大；165 例单测基线重跑确认。
---

## 27. 十七审应答（2026-09-05 · 高爆炸半径专项：每次提交/静默失效/设计前提）

**一、最高影响·BasicScheduler 键名勘误（scheduler_name→scheduler）**：成立并已修——object_info required=[model,scheduler,steps,denoise]（scheduler=COMBO，options 含 simple/beta/normal）；16 份生产提交键集=denoise/model/scheduler/steps（无 scheduler_name）；全仓 scheduler_name 0 命中。§7 line 84 已改：落点=stage.py:292 同点覆写 **scheduler** 键，守卫=("scheduler" in ins)（防"决策记录、正文未落地"与"无守卫直写→每次 400"双失败模式）；denoise required（FLOAT 1.0）与模板 widgets 3 值+model 连线=4 吻合（转换无残留）。

**二、最高影响·连线输入被标量覆写（width/height/length）**：成立并已修——实测 node 136 三键为连线输入（115 ResolutionSelector 槽 0/1→276/277；131 ComfyMathExpression 槽 1→275），ui_to_api 按连线发键+widget 值跳过（stale=3），apply_generation_params 标量覆写（真实提交 608/352/124）；node 115/131/132=零下游死重量（prune 在 ui_to_api 内部、早于覆写）。**length 侧语义等价（111 点逐点对比 0 差异：5s→124、15s→362——snap_length 与厂商表达式一致，覆写安全）；分辨率侧不等价：megapixels 杠杆不可达**（被 PRESETS 标量覆盖）→ §13 已修正（唯一杠杆=RESOLUTION_PRESETS 或 --width/--height 逃生口）；§0 新增"分辨率/长度输入链+死重量节点依赖（custom_nodes.comfyui-logicutils 三节点：ResolutionSelector/ComfyMathExpression/MinNode——对产物零贡献但缺包提交 400）"事实行。

**三、高（正面定案）设计 B 生产证据**：spark 12 份真实 r2v 提交 node 136 键集完全一致（含 ref_images.ref_image_0/1 点分键、无裸组选择器键、ref_videos/ref_video_audios/ref_audios 全为新增）→ **设计 B 核心前提=既成事实**（不是推理）；**AUTOGROW 机制根因记录**（COMFY_AUTOGROW_V3≠_DYNAMIC→connectable→组不进 items→组不消费 widget、子槽仅由已连线 UI 行产生）；**注入 id 空间具体化>146**（UI 文件 id 至 146；prune 后 20 节点={92,115,119-132,136,137,138,139}；被 prune=3 MarkdownNote+6 未接 LoadImage）；**LoadImage 口径**（8=UI 文件事实/提交 dict 仅 2 个；template_health 以模板文件侧数=8，验收先声明口径）。→ 全部写入 §7。

**四、高·设计 A 首要缺口（比已登记六条严重）**：ui_to_api:195 link=None 行继续→**合成行不接线对 API dict 贡献为零**；grow_slots 只追加行+克隆占位，接线=_wire_slot 独立步骤 → A 必须行合成+接线两步都对；错误后果=提交照常成功/产物照常出/参考关系静默缺失（与 §7c tag 硬约束同型静默错配）→ §7 备选 A 缺口清单已补为第 0 条（首要缺口）。

**五、高·768p 上限定案=LoRA（非模型）**：lora_name options=3（fl2v_4step→…768p/ref2v_4step→…v0.1 无标签/ref2v_8step→…768p）→ 待查划掉；**产品级取舍登记**：交付档（720p/768p+ref2v_8step）与原生 1080p（+--lora none 20 步）互斥，≈5× 成本（8→20 步 2.5× × 1.03→2.09MP 2.02×）→ §13 已写+§15.3/§15.5 登记（比表内任何项贵）；**正面确证**：capabilities.json lora.files/steps/choices 与 COMBO options 逐字符一致（无错配=无 400 风险来源）；UNETLoader unet_name 含 ref2va **int8 剪量化**权重（2.1MP 探测显存余量正面信号）。

**六、中高**：%8 vs %32 口径（预设表全 %32 干净；逃生口仅 %8——正确探测值=1920×1088）+CLI-only（tools.py width/height 0 命中）→ §13 已写（十六审同）。

**七、中**：设计 B 注入 id 空间→具体化 >146（见三）；template_health 验收口径（以模板文件 UI 侧计）→ §7 已写。

**八、正面确证·上传复用升级**：spark server.py 源码级——image_upload（:397-441）无 MIME/扩展名/内容校验（仅 commonpath 逃逸检查+裸写字节）；get_dir_by_type（:370-381）type=input→input/ 根；compare_image_hash（:383-395）裸字节哈希不经 PIL→mp4/mp3 同名重传安全 → §7b 上传段升级为"源码确证（含重传路径）"；§7a 复核清单 curl .mp4 从"必要"降"抽验"（不阻塞）。

**九、低**：① 死重量三节点=comfyui-logicutils（§0 已补；KJNodes 表述精确化）；② ref_images tooltip 2048 短边（§13 Inpaint 已登记）；③ capabilities.json lora.dir=spark 绝对路径入库（与 pipeline.json 不入库口径不一致；Windows 恒无效）→ **登记低项**（机器相关值不该入库；下次涉及 capabilities 改动时一并回退为相对/注释——本轮不动避免行为面）。

**十、仍不可验证**（不单方执行）：1920×1088+--lora none 探测（定：2.1MP 墙钟/显存、服务端 step=32 强制、原生画质）；**ref2v_4step v0.1 无标签=探测最不确定环节**（验证档 768p+ 行为未声明）；§15.5 项 2（魔搭真实模型 ID）未闭合（通道级≠模型级）。
---

## 28. 十八审应答（2026-09-05 · §3/§4/§5/§8/§9/§10 专项 + 共享队列安全）

**一、【最高·已修代码】取消运行中任务=全局中断（与 §0 红线矛盾）→ 定向中断化**：
- 取证成立：queue_probe.py:70 `Request(/interrupt, data=b"")` 空 body→server.py:1160-1189（0.34.3）`await request.json()` 抛 JSONDecodeError→`json_data={}`→走 `Global interrupt (no prompt_id specified)`→`nodes.interrupt_processing()`（进程级、不携带身份）；TOCTOU（:60 读队列/:67 判 running/:81 POST）+归属校验对中断无效+无条件清断点——三步全坏。
- **已修**：`/interrupt` 改带 `{"prompt_id": pid}` body+Content-Type（服务端定向分支 `item[1]==prompt_id`→interrupt；未命中→skip 不误伤）；docstring/注释同步；last_job 清断点改 **tmp+replace 原子写**（:86-93；非原子写与 §12 meta.json 同类，补入清单）；py_compile+165 例全绿。
- 对照（正面）：`/queue {"delete":[pid]}` 传 prompt_id 正确（server.py:1152-1156 `a[1]==id_to_delete`，item structure=(number,prompt_id,…)）——十八审自查"我怀疑传队列序号"不成立，如实记录。

**二、【高·已修代码】CancelTask=7 工具中唯一缺参数归一（取消链必失败）**：tools.py:562 无 `_verify_json_format_args`（6/7 工具都有）+签名缺 Union 标注——JSON 字符串到达时 `isinstance(params,dict)` 为假→pid=整个 JSON 串→find_owned 必失败→"取消被拒"。**已修**（统一路径：`params = self._verify_json_format_args(params)`）；§3 前提链随之成立（mark_cancelled 分层设计以"CancelTask 能成功"为前提）。

**三、【高·§4 规格修正】--segments 三处缺陷**（默认路径不可达：:292 `slot=="flf2v"` vs slot_list 返回 video_flf2v 等 8 槽+blueprints 键名不一致；段索引 1-based vs 0-based 静默错位+`:216-217` 不强制数量；验证 dry-run 不打 prompt+字面 `?` 残留）→ §4 已补"前提更正（十八审定稿）"段（双向对齐/0-based 统一/段数守卫/验证读落盘 manifest JSON）；工作量 小→小-中。

**四、中**：§9 CHATS_DIR 双定义（session_cleanup.py:36+ui_app.py:40 同值独立定义——"唯一权威"表述更正+实施时抽公共常量；thumbs/ 子目录在 CHATS_DIR 下✓）+**§9 标 spark-only**（Windows 无 logs/agent_chats/）；§10 probe_av timeout=30 vs probe=60（低，备注已补）；config/llm.json `_comment` 编辑残片（"llm)；2)"孤立尾巴——**已修**（本机机器配置，不入库不同步；§4 line 60"已当场修正"实际留了残片——changelog §18 同型失败模式再现，记录）。

**五、正面确证（勿再重查）**：§8 全部属实——queue_pids()（comfy.py:266-271）返回 Tuple[set,set]（running+pending 双集合；**十八审自查上轮"只返回 running"记述有误，更正**）；queue() 仅计数✓；history() 未知 id 返回 {}✓；类名 ComfyClient✓；retries/request_timeout 可构造✓；h3_batch 未引用 queue_pids/history（item 5 确为待做）✓。§5 三处行号精确（svc_main.py:3/117/118-129）✓。§10 quality.py 不存在/probe 只用 v:0 流/probe_av 已存在且 size 同源✓。§9 dev.py 无 sessions 子命令✓。§3 mark_cancelled 全仓 0 命中（待建）✓；clear_tasks/add_tasks=session_state.py:37/43、调用 ui_app.py:1098/1232 ✓（行号精确）。

**六、优先级执行**：第一条已独立于 S3 立即修复（影响共享 GPU 他人任务、修复面极小——携 body 即用服务端定向分支）；二~四条=取消链/规格修正全部落地；§4 实施前置已并入规格。

**机制**：本轮**代码修复 2 文件**（queue_probe.py 定向中断+原子写、tools.py CancelTask 归一）+配置文件（llm.json 残片，不入库）+文档（§3/§4/§9/§10/§12 清单补充）；断言双抽查后落地（16 份生产 BasicScheduler 键集）；165 例全绿。

**机制**：本轮全部文档修订（§0/§7/§13/§15.3/§15.5/handoff），零代码改动；关键断言本地双抽查（16 份生产 BasicScheduler 键集、snap_length 111 点对比）后落地；决策与正文同步（回应"决策记录必须实际修改"）。
---

## 29. 十九审应答（2026-09-05 · tools.py CallComfyUI 全链专项）

**一、自我更正接受（十六审→十九审）**：§13"768p 硬编码 6 处"中 tools.py:260/:792 不准确（:260 静态 enum 运行时被注册表派生覆写、:792 仅为 fallback）→ **§13 已改为有效站点 4 处**+结构说明（agent 侧杠杆=capabilities params.resolutions；CLI/校验侧=RESOLUTION_PRESETS）。排查排除三条（已取证）：supervisor 自愈先 activate venv（system python3 无 qwen_agent 但自愈链走 venv）；布尔字符串 false→jsonschema 硬拒绝（非静默误判）；stage 必填先由 :310 jsonschema 强制（KeyError 不会到 :311）。

**二、【高·已定稿】§7a 命名空间定案（原"新 stage video_ref2v"废弃）**：两套命名（id=video_X/stage=X；tools enum 派生自 stage；resolve 首个命中）下两种读法均缺陷——A：id=video_ref2v+stage=r2v→resolve 遮蔽+enum 重复（agent 不可选）；B：stage=video_ref2v→default_lora_for_stage 仅精确匹配 r2v→**加速 LoRA 静默消失（20 步 vs 4 步≈5× GPU、exit 0 无警告）**。**定稿=不新建 stage，扩展现有 video_r2v 条目**（id/stage/slot 不变；slots 3/3、features.reference_videos=True、params 增 ref_image_size；lora.stages=[r2v] 已覆盖、agent_params 无需改；pipeline.json 无需新 stage，7a 原"stages 增 video_ref2v"删去）——§7a 已写入；若未来需区分纯图/视频参考档位=另立项（登记）。

**三、【高·已修代码】_coerce_fields 非确定性 + 扩大覆盖**：字符串路径下 _coerce_fields 不执行（_verify_json_format_args 内才 loads+validate）→ 同一 payload dict 成功/字符串失败（实测两例）；且默认元组不含 docstring 自述的 motivating case（wait_until_done 布尔串→裸 jsonschema 异常、call() try 从 :361 起不捕获）。**已修**：CallComfyUI.call 字符串先 json.loads（失败保留原样→_verify 报错）+ _coerce_fields 默认元组扩为 seconds/seed/dry_run/wait_until_done（布尔强转已支持；BatchSubmit 同受益）；结构性说明记录（qwen_agent 把 parse+validate 融合，coerce 只能前置——新增 videos/audios/tts_voice/tts_font_size 沿用此修复后路径，不再继承非确定性）。

**四、【高·已修代码】导入期异常静默**：_apply_registry_derived_schema（except:pass 包住、导入时执行）→ capabilities 坏/导入失败时 enum 静默停留 fallback（进程正常无报错）。**已修**：except 改 stderr 打印（导入期失败可观测）；§7a 一级判据补充=必须在 agent 进程内打印 stage enum 实际值（防"登记没生效"误判）。

**五、中**：① 分辨率 enum 来源=首个条目（video_t2v，命中即 break）+顺序耦合陷阱→ §13 已补（加 1080p 预设须加第一条目/全部四条）；② avail vs fallback[stage] str/list 恒真比较（描述总被追加）→ **已修**（改为 join 后比较；与 mix_tracks 音量单位 bug 同型）；③ VERIFY_TIER 静默降级 ≈10×（480p+20 步 vs 360p+4 步；触发面窄=不经 scheduler 的导入路径；已登记为潜在陷阱非现行 bug）；④ tool_timeout=180 submit-only 路径：h3_submit 已 POST 成功但 TASK_SUBMITTED 未 flush→agent 拿不到 pid→模型可能重复提交（共享队列双份 GPU）；**断点写入顺序未核实**（TASK_SUBMITTED 仅 :852 resume 路径确认——如实标注未核实）；⑤ 依赖版本未登记：spark 实测 qwen_agent 0.0.34 + jsonschema 4.26.0（承载整个工具框架校验语义，比 gradio 更载荷）→ 登记实际版本。

**六、覆盖与剩余**：已覆盖 CallComfyUI 全链/_coerce_fields/_derive_tool_enums/_apply_registry_derived_schema/workflow_registry 解析/agent_params 档位/qwen_agent 校验实现/自愈命令。**登记下一轮**：tools.py 其余工具（RunScript/ModifyWorkflow/BatchSubmit/ReadDoc，尤其 BatchSubmit×§4/§8）、scheduler.py SYSTEM_MESSAGE（§6③/§7c/§12 引用均未逐字核过）、ui_app turn 机制×S12 grants 时序。

**机制**：本轮**代码修复 tools.py 4 处**（字符串预解析/coerce 元组扩充/enum 比较修正/导入期告警）+文档（§7a 定稿/§13 更正+顺序陷阱/版本登记）；COMPILE_OK+165 例全绿；每处修复后 grep 落点核对（含一次修复过程自纠：coerce 函数误替换后当场还原重做，终态正确）。
---

## 30. P1.5 参考语义修复实施记录（2026-09-06 · book-19 §10）

**一、设计定稿（用户首验归因后）**：P1.5=提示词 tag 契约强制（根治）+ 生成后校验 + ref_image_size 默认 max（身份保真优先）+ 验证=3 段抽 3 帧目检。与 §7c「images 保持位置序、不做 <Picture N>」的旧取舍**冲突**——P1.5 以用户首验实证推翻旧取舍（无 tag → 参考图被解读为首→尾关键帧），定稿=实施 <Picture N> 契约（与 §7b/§7c 的 <Video N>/<Audio N> 映射同源：tag 1-based 按连接顺序、槽位键 0-based）。

**二、实施落点（11 文件）**：
- `runs/agent/scheduler.py`：SYSTEM_MESSAGE 提示词规则新增 r2v tag 契约+固定语义句+生成后校验要求（行为规则）。
- `runs/h3/prompts.py`：REF_TAG_RE（大小写不敏感）、REF_PERSIST_MARKERS、reference_tag_set/missing_reference_tags/has_ref_persist_sentence/ref_tag_contract_rule。
- `runs/h3/idea2prompts.py`：build_messages 追加 r2v 契约规则；_ref_contract_violation 存在性校验（tag+贯穿句）；_enforce_ref_tag_contract 违规→追加强制提醒重生成一次→仍违规 ParamError 拒写。
- `config/prompt_blueprints.json`：global_rules 规则 8（r2v 类槽位 tag 契约+固定语义句）+ video_r2v/api_r2v extra。
- `runs/h3_submit.py`：--ref-image-size（max/match）、--no-check-ref-tags（校验开关，默认开）；_stage_mode 提交前硬校验——stage=r2v 且 wf 含 MiniMaxH3ReferenceToVideo → count_wired_reference_images(N) → missing_reference_tags 缺失即 ParamError exit 3（含补 tag 指引）；贯穿句缺失=警告（措辞容错不硬拒）。
- `runs/h3/stage.py`：REF_IMAGE_SIZE_CHOICES、apply_ref_image_size（仅覆写存在该键的 RefToVideo 节点）、count_wired_reference_images（槽位键前缀+连线值判定）；build_template_workflow 增 ref_image_size kwarg（与 apply_generation_params 同点覆写）。
- `runs/h3/params.py`：DEFAULTS.ref_image_size=max、GenParams.ref_image_size（workflow_dict 含）、resolve_params 枚举校验（非法→ParamError）。
- `runs/h3_batch.py`：--ref-image-size + manifest 持久化 + submit/retry 转发。
- `runs/agent/tools.py`：call_comfyui/batch_submit 增 ref_image_size 参数（enum max/match）并转发。
- `config/capabilities.json`：video_r2v params.ref_image_size{default:max,options}+features.ref_tag_required=true（agent digest 可见）。
- `workflows/remote_workflows/video_minimax_h3_r2v.json`：node 136 widgets_values[4] "match"→"max"（本地镜像；参数覆写兜底，故 sync_remote_workflows 回退无害，登记）。

**三、验证**：py_compile 全部 8 文件 OK；新增 tests/test_ref_tag_contract.py 21 例；基线 py -3.13 -m pytest runs/h3/tests -q = 164 passed+1 skipped（=165 基线）+顶层 unittest 56 例 OK；consistency_check 问题 0。**一级判据（agent 进程内 stage enum 实值）不受影响**（未动注册表 stage 枚举）。**二级=☆真机 3 段×抽 3 帧目检**——待用户（队列空闲窗口）+ 抽帧目检判据：人物身份/场景空间/道具外观全程一致、无首尾帧化。

**四、风险/遗留登记**：① 硬校验对「手工提示词无 tag」的既有用法=行为变更（拒绝+指引；开关 --no-check-ref-tags 降级，已登记）；② idea2prompts 只做存在性校验（张数未知），准确数校验在 h3_submit（按实际接线数）；③ ref_image_size 速度代价（参考 token 随采样步）如实写入文档/工具描述；④ 真机验证=抽帧目检（人工判据，不可自动化——用户首次验收环节）。

---

## 31. S8 批量状态轮询优化实施记录（2026-09-06 · 五审定稿落地）

**一、实现**：comfy.py 决策树 classify_task_state（completed/failed/running/pending/absent；absent=两个来源皆不可区分如实标注）+ h3_batch cmd_status 改写（本进程 ComfyClient 判定，无子进程；输出兼容：SEG 行/图标/总耗时/REMOTE_VIDEO_PATH/manifest 回写；--wait 10s）。

**二、验证**：test_s8_decision 9 例；165 基线+顶层 unittest OK；spark 真机：已完成批瞬时 3/3（旧 3×30s）、失败批如实 4 failed。

**三、遗留**：task_watch.poll_batch 的 pathlib 修复确认在场（P1 前置）；cancelled 不可区分已按规格如实标注（P1 事件文案沿用）。

---

## 32. P1 事件驱动完成通知实施记录（2026-09-06 · book-19 §9）

**一、实现**：task_watch 原语（heartbeat 90s / notify_key / build_notify_message 四类+降级 / describe_output ffprobe）+ session_state.list_cids + ui_app 常驻 watcher（15s；开关 P1_NOTIFY_EVENTS=off；仅 idle 注入；stop_event=用户接管不注入；p1_was 防重复；_inject_notify 复用 send）。回滚=环境变量 off（默认 on；与规格默认关差异已登记）。

**二、验证**：test_p1_notify 10 例；165 基线+全套绿；spark watcher tick 周期确认（17 条）；正常链抑制正确（send 已展示不重复）；注入分支=低概率场景未复现，单测+代码覆盖，如实登记待自然观察。

**三、顺带登记**：submit-only 链的 last_job 残留（任务完成后断点未清）——低优先增强候选。

---

## 33. S2-P1a agent 默认 T2 增强实施记录（2026-09-06）

**一、实现**：tools.py 默认 --postprocess fast（dry_run 不带）；补丁=postprocess 持久化到 job + resume 恢复（防无参续传丢增强参数；CLI 显式优先，args 默认 None 区分显式 none）。

**二、验证**：164+1skip 绿；spark job.json postprocess=fast 实证；真机判据已过：cc8adc87 resume 后 video_37_pp.mp4=1216×704 h264+aac 5.167s + postprocess_done 日志 + agent argv 均带 --postprocess fast；增强片=win outputs/video_44.mp4。登记：增强选片按最新 mtime 可能二次增强（_pp_pp）——低优先。

---

## 34. S3 T9 收尾实施记录（2026-09-06）

**一、实现**：task_watch mark_cancelled/is_cancelled（cid+pid 登记，poll 遮蔽→已取消终态，worker 完成判定含 cancelled）+ CancelTask 成功路径调 mark（四审定稿：不 clear_tasks，防 add_tasks 覆盖）。

**二、验证**：test_s3_mark_cancelled 4 例；165+53 绿；真机=720p/15s 提交后立即取消成功（归属校验+断点清理+工具链闭环）。

---

## 35. S6 男/女声可选 + 字幕字号参数化实施记录（2026-09-06）

**一、实现**：tools CallComfyUI schema（tts_voice 短名enum/tts_font_size）+ 转发；h3_submit --font-size + job/resume 持久化；tts.attach fontsize 透传；SYSTEM_MESSAGE 音色句。

**二、验证**：test_s6_voice 4 例；165+27 绿。真机=待队列空闲窗（当前 5 pending/1 running 未占）。

---

## 36. S1 上传预览可判定性实施记录（2026-09-06）

**一、实现**：ui_app gallery 元组化（path, caption）=会话来历+已用；三改动点（_previews_for_cid/并行 _th/串行 _thumbs）统一；安全回退保持（不可用隐藏不回退源路径）。spark-only。

**二、验证**：spark 真机 _previews_for_cid 断言 PAAS=元组+caption（4 条）；Windows 仅改码+编译。

---

## 37. S4 实施记录（2026-09-06）

**一、实现**：槽名/蓝图键对齐、--segments-json 0-based、段数守卫、死 import 修复（h3prompts）。真机：deploy 切 spark-local（按纪律）；模型 1 段→守卫拒写（验证通过）。

**二、登记**：Qwen3.8-27B 分段遵循度弱（单段输出）——提示词强化待下轮（不阻塞 S4 本体）。

---

## 38. S5 selfcheck-llm 实施记录（2026-09-06；演练待授权）

**一、实现**：svc_main 三处（docstring/choices/分派）+ cmd_selfcheck_llm（队列守卫→nap→wake>=300s）+ --yes 对齐双演练 + --timeout。

**二、验证**：编译 OK；无 --yes 拒绝路径实测；销毁性演练=待授权（队列空闲窗）。登记 nap 冲突（supervisor ≤30s 拉回）另立。

---

## 39. S9 dev.py sessions 实施记录（2026-09-06）

**一、实现**：list/export/search（函数化+单测）；CHATS_DIR 注同值双定义；search 位置语义修正。

**二、验证**：5 单测+165 绿；spark 真机 list/export/search PASS。
