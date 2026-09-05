# 待做任务·具体实现规格（供外部 AI 审核）

> 文档性质：把「甜点/待做任务」的具体实现方案（含现状复用、文件级步骤、验证方法、风险取舍）写清，供**另一位 AI 审核**；审核者只需审本文件+抽查引用代码（所有路径相对项目根 `D:/MY_CODING_PROGRAM/videoGenerate-Model-zju`，spark 同构 `~/videoGenerate-Model-zju`）。
> 版本：2026-09-05 · 关联计划书：book-13 §6（S1-S14 总览）、book-14、book-15、book-18。
> 审核者请注意：文档中「待核实」= 需实施期探测确认；「不承诺」= 结论性取舍，若不同意请批注理由。

---

## 0. 审核输入：技术约束事实表（2026-09-05 实测）

| 约束 | 事实 | 影响 |
|---|---|---|
| 外网 | pypi.org=200；huggingface/github/translate=000（不可达）；speech.platform.bing.com 可达（edge-tts 可用）；cdn.jsdelivr=301 | **任何需下载模型/数据的任务默认不可行**（S13 口型驱动=不可行；Inpaint 若需新模型=不可行，除非已有本地资产） |
| GPU | 共享队列（归属校验才可取消/删除；新任务走提交即返回）；ComfyUI=systemd 且**禁止人工重启**（崩溃自愈由 systemd 承担；运行时只允许队列空闲时 POST /free） | 一切真机验证须队列空闲等待；任务数受控 |
| 模板红线 | spark 同事模板 `~/ai/ComfyUI/user/default/workflows/` **永不修改**；只改本地镜像 `workflows/remote_workflows/` 与本地扩展 | S7 的 Ref2VA 模板只能本地镜像/本地扩展 |
| 已可用组件 | `h3.postprocess.process`（lanczos 2x + hqdn3d + unsharp，ffprobe 断言）；`render_subtitle`（libass + Noto CJK，字号/描边/安全区可参数化）；`h3.tts`（edge-tts：合成/逐句/音轨替换/字幕一步到位/loudnorm -14）；`queue_probe`（队列只读/归属/条件取消）；`svc_main`（services 观测动作）；`supervisor`（自愈守护）；`llm_mem`（planner/wake 自适应）；`comfy.history(prompt_id)`（O(1) 单任务历史） | 多数任务=接线/组合，非新建 |
| 组件能力缺口 | gradio 5.23 `Gallery` 支持 (image, caption) 元组（文档声明，实施时以 `view_api` 实测为准）；`File/UploadButton.select` 事件存在（已条件绑定实测无异常） | S1/S6 前端实现的可选路径 |

---

## 1. S1 上传预览可判定性（gallery 缩略图标注所属会话/可用性）

**目标**：预览缩略图标注「会话来历/已用/可用」，用户不再混淆多会话素材。
**现状**：`_previews_for_cid(cid)` 已按 cid 重建预览（book-13 #9b）；`_gal_by_cid` 存路径列表；gallery 无 caption。
**实现（文件级）**：
1. `runs/agent/ui_app.py`：`_previews_for_cid`/`_upload` 输出改为 `[(path, caption), ...]`，caption 由 `uploads/log.jsonl`（cid/sha/ts）拼装：`[会话 20260905_… · 已用/可用]`；可用性=该 sha 是否仍存在于 uploads 归档或 ComfyUI input/user_uploads（`_known_shas` 已有同构判定，抽为 `_asset_available(sha)`）；
2. `gr.Gallery` 直接收元组；若无 caption 支持则降级：加 `gr.Markdown` 行列出可用项（计划 B，不改组件）。
**验证**：真实链 `_load`（驱动脚本 `load_drv.py` 模式）断言 gallery 元素含 caption 文本；浏览器目检。
**风险/取舍**：低；captions 为静态生成（上传时点），已用标记以「是否出现在本会话 list_references 输出」为基准（读取时计算，不持久）。工作量：小。

## 2. S2 agent 出片默认走 T2 增强（超分/降噪/锐化）——「超分怎么实现」

**目标**：agent 提交的每个任务完成后默认产出增强版（4 步瑕疵补偿），`--postprocess none` 可关。
**现状**：T2 链已存在且真机验证过（video_12：608×352→1216×704/720p、5.17s/124f，ffprobe 断言）。`h3_submit --postprocess fast` 现有完成钩子；**但 agent（call_comfyui）当前不传 `--postprocess`**。
**实现（文件级）**：
1. `runs/agent/tools.py`：CallComfyUI 提交参数追加 `--postprocess fast`（在 `--submit-only` 之后追加；dry_run 不带）；
2. `runs/h3_submit.py` 完成钩子**顺序重构**：`finalize(原片) → run_fast(原片→_pp) → tts.attach_speech_and_subtitle(_pp, tts_text) → PROBE/TTS_OUT`（**先增强后字幕/语音**——否则字幕被放大产生软边、语音在 608 源上烧录后增强音轨 copy 不受影响但画面字幕模糊）；有 `tts_text` 且无 `postprocess` 时仍走原路径；
3. 增强滤镜链（现有 `process()`，纯 ffmpeg，无 GPU）：`scale=iw*2:ih*2:flags=lanczos` → `hqdn3d=1.0` → `unsharp=5:5:0.4`（各向异性 lanczos 放大；降噪=时域去低步伪影；锐化恢复边缘；参数均可 `--postprocess fast` 固定）。
**超分方案的取舍说明**：v1 用 lanczos（平滑、零依赖、秒级）；**真实超分模型（Real-ESRGAN x4plus）**：ComfyUI 输出目录历史中存在 `UpscaleModelLoader(RealESRGAN_x4plus.pth)` 节点（同事模板在用）→ **本机 ComfyUI 已可能持有该模型文件**（实施期核实 `~/ai/ComfyUI/models/upscale_models/`）——若存在：v2 可加 `--esrgan` 走 ComfyUI 独立请求（BatchProcess? 或者本地推理需 ComfyUI API 工作流：LoadImage+ImageUpscaleWithModel+SaveImage）；**若无该模型文件：放弃 v2，保留 lanczos**（外网受限无法下载）。
**验证**：真实链 gen 一次（4 步 360p）：产物=1216×704、时长/帧数不变、字幕抽帧清晰、音轨 AAC 且时长=视频；`PROBE` 断言宽高。
**风险**：**二轮审阅修正（撤回“已遵守”声明）**：旧链 process+render_subtitle 曾为两次 CRF18；现已重构为合并单次编码（process 支持 srt 并入同一 -vf；run_full 同步；钩子 fast+tts 并存走合并链）——实测：video_31 离线合并链 2.4s，产物 1216×704/5.167s，字幕比例字号（0.07×704≈49px，旧绝对 20px 已废）帧目检清晰。P1 拆分：**P1a=默认 lanczos fast（单次编码，即时收益）**；**P1b=--esrgan 交付档可选（单帧实测 ~11.8s（1216→2432）；串行 124 帧≈24min——成本一个数量级，仅精品/交付显式启用；先做批处理并行优化，目标 3-6min，未优化前禁默认）**。工作量：P1a 小-中；P1b 中。

## 3. S3 T9 收尾（取消后任务表残留）

**现状**：`cancel_task` 取消成功即清 last_job 断点；但 `send()` 里 `all_pending_tasks/add_tasks(cid)` 登记仍在，`task_watch` 会继续轮询已取消 pid。
**实现**：`runs/agent/task_watch.py` 新增 `mark_cancelled(cid, pid)`；`tools.py CancelTask.call` 取消成功后调用之（去重同方法）；task_watch 轮询到 cancelled 标记→立即发 done 事件（『已取消』）并停止；同时 `send()` 在收到 cancel 结果后 `clear_tasks(cid)` 清该会话任务表。
**验证**：单测（mock task_watch 状态）；真实链=取消运行中任务后在会话继续「查询」→ 收到『已取消』而非轮询等待。工作量：小。
## 4. S4 idea2prompts `--segments` 真实验证 + 与 batch 衔接

**现状（已取证）**：`h3_batch submit --prompts-file <json>` **已存在**，格式=按段索引的 JSON 字典 `{"0":"pos...","1":...}`（`runs/h3_batch.py:133-151`）；`idea2prompts --segments N` 已实现（book-13 #5）但**输出为 `video_flf2v.segment_<i>.positive.txt` 文件**（与 batch 期望不匹配），且从未用真实 LLM 跑过。
**实现**：① 改 `idea2prompts._write_segments`：追加写入 `--segments-json <path>`（默认 `prompts/workflows/video_flf2v.segments.json`，即 `{"0":..,"1":..}` 结构，与 `--prompts-file` 对齐；旧 txt 文件保留兼容）；② 真实 LLM 验证：临时启用 `config/llm.json`（`enabled=true; base_url=http://127.0.0.1:8000/v1; model=Qwen3.8-27B`，`chat_once` 走 urllib 直连 spug sglang——与 ui_app 同栈）跑 1 次 3 段 → 校验 parse/写文件；验证后关闭（默认不启用，避免二义性）。
**验证**：dry-run `python runs/h3/idea2prompts.py --idea ... --workflow video_r2v?`（flf2v 段）→ 打印 JSON；用 `h3_batch submit --stage flf2v --image a,b,c ... --prompts-file <json> --dry-run` 断言 manifest 携带每段提示词。工作量：小。

## 5. S5 SGLang 销毁性自愈演练（selfcheck --llm）

**现状**：supervisor/`selfcheck`（agent 演练）已通过；`llm_mem.wake` 自适应链存在；**sglang 销毁性演练未做**（成本顾虑）。
**实现**：`svc_main.py` 增 `selfcheck-llm`：① 前置校验 ComfyUI 队列空闲（`queue_probe.collect`）+ 本会话无生成任务（提示语：演练会中断当前对话）；② `pkill -f sglang.launch_server` + `tmux kill-session -t sglang`；③ 轮询 90s：`/v1/models` 200 或 supervisor 已拉起（supervisor 会调用 `llm_mem.wake`）；④ 输出 `{ok, detail}`；`dev.py services` 增参数透传；**本命令须显式 `--yes` 二次确认**（红线：非授权不执行）。
**验证**：授权后执行一次（队列空闲窗口），断言 `wake 完成 档位=0`；记录耗时与降额日志。**风险**：SGLang 冷启动 1-3 分钟；若失败自动回退监督（supervisor 最多 3 次拉起后报警）。工作量：小。

## 6. S6 男/女声可选 + 字幕字号可调

**实现**：`runs/h3/tts.py` 已支持 `voice` 参数（`DEFAULT_VOICE=XiaoxiaoNeural`；备选 `zh-CN-YunxiNeural`）；① `tools.py CallComfyUI` schema 增 `tts_voice`（enum: xiaoxiao|yunxi，缺省=默认）→ `h3_submit --tts-voice` → 任务记录 `tts_voice` → 完成钩子传入 `tts.attach(..., voice=...)`（`record_task_start` 已存 tts_text，扩展同结构）；② `--font-size`：`h3_submit` 已有?（无——`postprocess` CLI 有 `--font-size`；h3_submit 完成钩子烧录字幕走 `attach_speech_and_subtitle`→`render_subtitle` 默认字号=0.07×高）→ 增 `h3_submit --font-size` + `tools.py tts_font_size` 透传；③ SYSTEM_MESSAGE 台词规则加一句：『用户指定男/女声或字号→传给 tts_voice/tts_font_size』。
**验证**：真实链指定 `tts_voice=yunxi` → run log `start argv` 含 `--tts-voice yunxi` + `tts_done ... voice=zh-CN-YunxiNeural`；字号=抽帧目检（更大/更小）。工作量：小。

## 7. S7 参考视频/音频原生支持（book-14 T8）——最大工程

**现状（已取证）**：本地模板仅 7 份（t2v/i2v/r2v/flf2v × api/video），**无 Ref2VA 模板**；capabilities.json slots 含 `videos/audios: []` 占位；`MiniMaxH3ReferenceToVideo` 为多图节点（r2v 现模板）；T1 真机曾用 `ref2v_4step` LoRA（说明 spark 侧存在 Ref2VA 模板或节点 `MiniMaxH3ReferenceToVideo` 支持视频/音频槽位——**实施第一步必须探测**：`curl /object_info` 枚举节点（MiniMaxH3ReferenceToVideo 的 inputs 是否含 video/audio）＋ spark 同事模板目录/`~/ai/ComfyUI/user/default/workflows` 是否为 ref2v；`T1 用 ref2v lora` 意味着节点存在）。
**分三步实现（每步可独立验收）**：
- **7a 探测登记**：节点/模板存在性 → 结果写入 capabilities.json 新 stage `video_ref2v`（slots=videos up to 3 / audios up to 3 / images up to 9）与 code-fact-registry；若本地无模板→**从 spark 模板库复制镜像**（不改同事原件，仅本地镜像，遵守红线）；
- **7b 引擎接线（审核修订：`bind_images_to_template` 实际在 `runs/h3/refimage.py:175`，非 stage.py；`bind_refs_to_template` 为新建函数，与它同文件并列）**：增 `bind_refs_to_template(stage, images, videos, audios)`（复用其图像路径 + 扩展 LoadVideo/LoadAudio 注入，节点 key 探测期确定；**并发安全：在任务目录副本上操作，参照 h3_batch 的 batch_lock 模式**）；`h3_submit --videos/--audios`；`capabilities` 注册 params；
- **7c 工具/提示词**：`tools.py call_comfyui` 增 `videos/audios`（枚举 id）；SYSTEM_MESSAGE 加 `<Video N>/<Audio N>` 提示词规范（N 与槽位序号一一对应）与使用边界（视频=动作参考/音频=氛围参考；不一致会导致编辑层重音轨，见下）；
**取舍（审核采纳混音方案）**：参考音频 + T2b 旁白并存时**不做二选一**——推荐 `TTS 旁白为主轨（loudnorm -14）+ 参考音频降 12dB 做底轨混音`（ffmpeg amix+volume；`postprocess.mix_audio` 已有外部音轨混流，需扩展为双轨音量配比）；仅当用户明确「以参考音频为准」时才旁白降级。
**验证**：dry-run 断言 LoadVideo/LoadAudio 图注入；真实链一次（提交 r2v+1 视频参考）产物 ffprobe 正常；**若 7a 探测失败（无节点/无模板）→ S7 标记为『不可行（环境缺能力）』并如实归档**，不做任何臆造接线。工作量：大（7a 小 / 7b 中 / 7c 小）。
## 8. S8 批量状态轮询优化（消除子进程开销；**非真 O(1)**——ComfyUI 无批量接口，实为 O(N) 但无逐段子进程/30s 开销）

**现状**：`h3_batch status` 每段新起 `h3_submit --resume`（每段 30s）；`comfy.history(prompt_id)` 已存在（单任务 O(1)）。
**实现**：`runs/h3_batch.py`：`status` 分支改为：读 manifest `segments[].prompt_id` 列表 → 复用 `comfy.Client`（同进程连接，不新起子进程）逐段 `client.history(pid)` + 一次 `/queue` 判断 pending/running → 汇总打印（与现有输出格式兼容，`--wait` 语义保留（轮询间隔 10s））。
**验证**：对已完成的 batch manifest 跑 `status --wait`（瞬时返回）断言各段状态正确；与旧输出 diff 人工核对一次。**归一口径（审核修订）**：已取消/从未入队=`/history/{pid}` 空 dict `{}`；提交前错误=404/连接错——`{}`→failed（含 cancelled 标记），404/连接错→pending（下次再查）。**S8 前置（审核抓出的真 bug）**：`runs/agent/task_watch.py::poll_batch` 缺 `from pathlib import Path`（NameError→恒 failed）——已在审核当轮修复（见 §15）；S3/S8 须确认修复在场。工作量：中。

## 9. S9 会话历史导出/搜索

**现状（审核修订）**：`dev.py` **无 sessions 子命令**（零命中；`list_chats` 在 ui_app，非 dev.py）——**全新建**。**实现**：`dev.py sessions`（新建）：`list`（复用会话目录口径）、`export <cid> [--out ...]`、`search <kw> [--cid]`；纯文件读。
**验证**：对真实会话 export → 目检 md 内容完整；search '水墨' 命中既有会话。工作量：小。

## 10. S10 质量看板（quality-report）

**现状（审核修订）**：`runs/h3/quality.py` **不存在**（零命中）——**全新建**。**实现**：① `runs/h3/quality.py`（新建）：`append(path)`（读 PROBE 行/ffprobe → 追加 `logs/quality.jsonl`）、`compare(a,b)`（ffmpeg ssim）、`report()`；② `dev.py quality-report`（新建）；③ `h3_submit` PROBE 后自动 append。
**验证**：对比命令在 video_19/24（已知 SSIM 0.864）复算一致性；report 输出含该记录。工作量：小。

## 11. S12 跨会话「显式共享区」选项

**设计（语义请审核）**：新增 `refimage list --scope-shared`（=本会话 + 用户最近 7 天内『显式授权』的会话——授权=UI 新增『允许本会话访问这些会话』多选下拉，写入 `logs/agent_chats/<cid>.meta.json` `shared_from:[]`）；`list_references` 默认仍仅本会话；用户文本含『用第 X 会话的素材』时工具校验授权否则报错（复用现有『素材边界』模板）。
**实现**：`refimage.py`（scope-shared 分支）+ `ui_app`（授权多选，小型 `gr.CheckboxGroup`）+ `tools.py list_references` 透传。**风险**：权限语义（默认不授权、显式点名、可撤销）必须先在 planbook 定稿；实现排在 S9 之后。工作量：中。

## 11. S11（不建议近期项）——规格留空

S11=§3.2 图片解析收敛（assets.py 重构）：价值/风险比低，登记观察；不提供实施规格（详见 book-13 总览）。

## 12. S13 远期池的实现预研（**注意：个别“不可行”判定已被 §14/§16 取代**——以 §14/§16 为准）

| 项 | 方案 | 可行性判定（本环境） |
|---|---|---|
| 口型驱动（Wav2Lip/SadTalker） | 独立 venv + 模型文件推理 + 音轨→口型管线 | **⚠ 已被 §14/§16 取代：可行**（魔搭通道 + 本地 GPU torch；先冒烟后全链） |
| 局部重绘 Inpaint | ComfyUI `InpaintModelConditioning`+`VAEEncodeForInpaint`+SAM mask（需 SAM/Inpaint 节点与模型） | **待探测**：若 `~/ai/ComfyUI/custom_nodes` 含 ComfyUI-Inpaint 类节点且模型存在→可行（`/object_info` 枚举）；否则不可行 |
| 标题/图表后期装配 | ffmpeg `drawtext` + Noto CJK（黑体/描边/安全区已有同参数）；数据图表=SVG 渲染→ffmpeg overlay（纯本地） | **可行**（无需新模型；工作量中） |
| 1080p 输出 | 模型上限 768p；增强链 2x 可得 **1216×704（≈720p）**；如需 1080p 类：`--scale 2.84` 到 1728×1000? **建议口径**：交付档=768p 原生或 2x 增强，**不宣称 1080p 原生**；`--scale` 自定义允许用户自选 | 可行（如实标注：超分非原生） |
| 齿音处理 | ffmpeg `afftdn` 已加；齿音=谱减（`highpass`+`deesser` 类无内建） | 低价值，维持暂缓 |

## 13. 请审核者重点评审（**“五大”实为六条；各疑点结论见 §15/§16，本节保留原问供比对**）

1. **S2 顺序**：『先增强后字幕/语音』是否优于『先字幕/语音后增强』？（我的理由：增强后再烧录字幕=字号语义一致、drawtext 在 2x 画布上更清晰；语音在增强前后无差别（音轨 copy））；
2. **S7 前提检测失败时的处置**：我定为『探测失败→标记不可行并如实归档』，是否同意（vs 预留抽象接口等待模型）？
3. **S7 音轨冲突决策**：参考音频 + T2b 旁白并存时以旁白为准——是否有更优次序（如参考音频做底、旁白做叠层混音）？
4. **S8 语义差异**：history vs 轮询在『取消/失败/从未入队』三种状态下的归一口径（我方案：空/404→标记 failed，未知→pending 再查一次）；
5. **S12 权限模型**：显式共享区（meta 授权+可撤销）vs 维持『线索+逐次授权』现状——哪个更符合本项目共享纪律；
6. **通用**：所有真机验证的 GPU 占用（S2/S6 各 1 次 4 步 ×2 等）预算与队列纪律（一意图一驱动、队列空闲等待）是否认可。

---

## 附录：可复用实现索引（审核者抽查用；**二轮审阅后：process 已支持 srt 单编码；run_fast/run_full 为合并链速查**）

| 能力 | 文件/函数 | 备注 |
|---|---|---|
| 超分/降噪/锐化 | `runs/h3/postprocess.py::process`（lanczos/hqdn3d/unsharp/**srt 并入同 -vf 单编码**）；`run_fast`；`run_full`（完整链=单编码+音轨） | T2/T2b 已验收；二轮审阅已重构 |
| 字幕 | `postprocess.render_subtitle`（libass/Noto CJK/字号描边安全区参数化） | book-18 已参数化 |
| 语音 | `runs/h3/tts.py::synthesize/attach_speech_and_subtitle/build_srt_speech`（edge-tts/逐句/重试/loudnorm） | 听测通过 |
| 队列/取消 | `runs/h3/queue_probe.py::collect/find_owned/cancel_owned_task` | T9 已验证 |
| 服务/自愈/内存 | `runs/agent/{supervisor,svc_main,llm_mem}.py` | book-15 |
| 历史查询 | `runs/h3/comfy.py::Client.history` | S8 用 |
| 参数档位 | `runs/agent/agent_params.py`（验证档/交付档） | book-17 §3 |
| 一致性断言 | `runs/consistency_check.py::check_quality_prompt_baseline` | Q+/Q- |

---

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
4. 混音扩展 `mix_audio` 双轨音量配比参数（amix 权重语义）。

**审核闭环**：以上即对审阅意见的完整应答；如审核方复轮，仅需针对 §15.1 未接受项说明理由。
---

## 16. 二轮审核应答与实测修订（2026-09-05）

**审核方主要结论与处置**：

1. S2 不二次转码声明与自身方案矛盾（双次 CRF18）——**已重构为合并单次编码并实测**（process 支持 srt 并入同 -vf；run_full 同步；钩子 fast+tts 并存走合并链）：离线实测 video_31 合并链 **2.4s** 出 1216×704/5.167s；
2. render_subtitle 默认绝对 20px 使先增强后字幕字号静默变小——**默认改比例字号**（0.07xH；实测 704p 字幕≈49px 帧目检清晰）；
3. mix_audio 实为替换非混流（§7 前提错误）——**docstring 更正为单轨替换 + 新增 mix_tracks 双轨混音**（旁白主轨 -14 + 底轨 -12dB amix）；
4. ESRGAN 视频超分成本低估一个数量级——**实测单帧 ~11.8s（1216 到 2432，双模型同），串行 124 帧约 24min**；采纳 **P1a/P1b 拆分**：P1a=lanczos fast 默认；P1b=--esrgan 交付档可选 + 先做批处理并行优化（目标 3-6min，未优化前禁默认）；
5. §0/§12/§13 与 §14 矛盾——已就地标注（§12 行改注、§13 说明、§12 标题注）；次要项（附录补 run_fast/run_full、S11 缺号补注、§15.2 序号说明、§15.3 次数回填）全部落地。

**实测新增事实（登记）**：ComfyUI 超分节点 schema：`UpscaleModelLoader` 输入键=**model_name**（非 upscale_model）；`ImageUpscaleWithModel`=upscale_model；LoadImage 需 input/ 根目录（user_uploads 子目录不能被直接解析）。

**审核问题“需要我直接落补丁吗？”**——已由本项目落地提交（commit 8c971f7/84f7b69 + 1c4c4d7/d2d4c95），证据=上述实测。

**仍未决/待实施前置（如实）**：① ESRGAN 批处理并行优化（S2-P1b 第一步）；② §15.5 其余项（魔搭模型真实 ID、Ref2VA 探测、amix 权重语义）按确认一项动工一项；③ S2 正式实施（钩子默认 fast 接线）：前置=合并链已就绪（✓）+ 队列空闲窗口 + 回滚开关 --postprocess none（已有）——待第一批整体拍板。

**第三轮建议聚焦**：批处理并行超分可行性验证 + Wav2Lip 冒烟流程设计。