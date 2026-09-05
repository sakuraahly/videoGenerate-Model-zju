# 待做任务·具体实现规格（供外部 AI 审核）

> 文档性质：把「甜点/待做任务」的具体实现方案（含现状复用、文件级步骤、验证方法、风险取舍）写清，供**另一位 AI 审核**；审核者只需审本文件+抽查引用代码（所有路径相对项目根 `D:/MY_CODING_PROGRAM/videoGenerate-Model-zju`，spark 同构 `~/videoGenerate-Model-zju`）。
> 版本：2026-09-05 · 关联计划书：book-13 §6（S1-S14 总览）、book-14、book-15、book-18。
> 审核者请注意：文档中「待核实」= 需实施期探测确认；「不承诺」= 结论性取舍，若不同意请批注理由。

---

## 0. 审核输入：技术约束事实表（2026-09-05 实测）

| 约束 | 事实 | 影响 |
|---|---|---|
| 模型下载 | **魔搭 ModelScope 可达（2026-09-05 实测：modelscope.cn 302/域通；modelscope pip 1.39.1 可装）**；edge-tts（bing 端点）可用；HF/GitHub/translate=000（不可达但非必需——模型一律走魔搭） | **凡需下载模型的任务均可行**（真实模型 ID 须逐一下载验证） |
| 本地既有资产（实测） | `upscale_models/`：**RealESRGAN_x4plus.pth(+safetensors) + 4x-UltraSharp.pth**（已就位）；`sglang-venv`=torch 2.13.0+cu130（GPU torch 环境已有）；KJNodes 等 custom_nodes 已装 | S2 超分=零下载；口型/ASR/TTS=可本地 GPU 推理 |
| GPU | 共享队列（归属校验才可取消/删除；新任务走提交即返回）；ComfyUI=systemd 且**禁止人工重启**（崩溃自愈由 systemd 承担；运行时只允许队列空闲时 POST /free） | 一切真机验证须队列空闲等待；任务数受控 |
| 模板红线 | spark 同事模板 `~/ai/ComfyUI/user/default/workflows/` **永不修改**；只改本地镜像 `workflows/remote_workflows/` 与本地扩展 | S7 的 Ref2VA 模板只能本地镜像/本地扩展 |
| 已可用组件 | `h3.postprocess.process`（lanczos 2x + hqdn3d + unsharp，ffprobe 断言）；`render_subtitle`（libass + Noto CJK，字号/描边/安全区可参数化）；`h3.tts`（edge-tts：合成/逐句/音轨替换/字幕一步到位/loudnorm -14）；`queue_probe`（队列只读/归属/条件取消）；`svc_main`（services 观测动作）；`supervisor`（自愈守护）；`llm_mem`（planner/wake 自适应）；`comfy.history(prompt_id)`（O(1) 单任务历史） | 多数任务=接线/组合，非新建 |
| 组件能力缺口 | **gradio 版本未在仓库固定（无 requirements/pin 文件；Windows 无 gradio）**——Gallery 是否支持 (image, caption) 元组须 spark `view_api()` 实测并**登记实际版本号**；File/UploadButton.select 已条件绑定实测无异常 | S1/S6 前端实现的可选路径 |

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
2. `runs/h3_submit.py` 完成钩子（**三审定稿=合并单次编码**，与 h3_submit.py:884-895 一致）：`finalize(原片) → [fast 且 tts 并存时] tts.prepare_speech(text)→ srt_+speech → postprocess.process(原片, _pp, srt=...)  ← 增强+字幕同 -vf 单次编码 → tts.replace_audio_only(_pp, speech)（视频 copy）→ PROBE/TTS_OUT`；仅有 tts 时走 attach_speech_and_subtitle（单次烧录编码+音轨 copy）；仅 fast 时走 run_fast。**不再存在双次 CRF18 路径**；
3. 增强滤镜链（现有 `process()`，纯 ffmpeg，无 GPU）：`scale=iw*2:ih*2:flags=lanczos` → `hqdn3d=1.0` → `unsharp=5:5:0.4`（各向异性 lanczos 放大；降噪=时域去低步伪影；锐化恢复边缘；参数均可 `--postprocess fast` 固定）。
**超分方案的取舍说明**：v1 用 lanczos（平滑、零依赖、秒级）；**真实超分模型（Real-ESRGAN x4plus）**：ComfyUI 输出目录历史中存在 `UpscaleModelLoader(RealESRGAN_x4plus.pth)` 节点（同事模板在用）→ **本机 ComfyUI 已可能持有该模型文件**（实施期核实 `~/ai/ComfyUI/models/upscale_models/`）——若存在：v2 可加 `--esrgan` 走 ComfyUI 独立请求（BatchProcess? 或者本地推理需 ComfyUI API 工作流：LoadImage+ImageUpscaleWithModel+SaveImage）；**若无该模型文件：放弃 v2，保留 lanczos**（外网受限无法下载）。
**验证**：真实链 gen 一次（4 步 360p）：产物=1216×704、时长/帧数不变、字幕抽帧清晰、音轨 AAC 且时长=视频；`PROBE` 断言宽高。
**风险**：**二轮审阅修正（撤回“已遵守”声明）**：旧链 process+render_subtitle 曾为两次 CRF18；现已重构为合并单次编码（process 支持 srt 并入同一 -vf；run_full 同步；钩子 fast+tts 并存走合并链）——实测：video_31 离线合并链 2.4s，产物 1216×704/5.167s，字幕比例字号（0.07×704≈49px，旧绝对 20px 已废）帧目检清晰。P1 拆分：**P1a=默认 lanczos fast（单次编码，即时收益）**；**P1b=--esrgan 交付档可选（单帧实测 ~11.8s（1216→2432）；串行 124 帧≈24min——成本一个数量级，仅精品/交付显式启用；先做批处理并行优化，目标 3-6min，未优化前禁默认）**。工作量：P1a 小-中；P1b 中。

## 3. S3 T9 收尾（取消后任务表残留）

**现状**：`cancel_task` 取消成功即清 last_job 断点；但 `send()` 里 `all_pending_tasks/add_tasks(cid)` 登记仍在，`task_watch` 会继续轮询已取消 pid。
**实现（四审定稿：职责分层，防 add_tasks 覆盖撤销）**：`mark_cancelled(cid, pid)`=权威（负责发『已取消』done 事件并停止该 pid 轮询）；CancelTask 成功后仅调 `mark_cancelled`；**不**在 cancel 时调 `clear_tasks`（send() 每轮开头已清、line~1232 add_tasks 会重新登记——中途 clear_tasks 会被覆盖）；下一轮消息自然清空即止。
**验证**：单测（mock task_watch 状态）；真实链=取消运行中任务后在会话继续「查询」→ 收到『已取消』而非轮询等待。工作量：小。
## 4. S4 idea2prompts `--segments` 真实验证 + 与 batch 衔接

**现状（已取证）**：`h3_batch submit --prompts-file <json>` **已存在**，格式=按段索引的 JSON 字典 `{"0":"pos...","1":...}`（`runs/h3_batch.py:133-151`）；`idea2prompts --segments N` 已实现（book-13 #5）但**输出为 `video_flf2v.segment_<i>.positive.txt` 文件**（与 batch 期望不匹配），且从未用真实 LLM 跑过。
**实现（四审事实更正）**：① 改 `idea2prompts._write_segments`：追加 `--segments-json`（与 h3_batch `--prompts-file` 的 `{"0":..}` 结构对齐）；② 真实 LLM 验证：**`config/llm.json` 当前 enabled 已为 true**（非“临时启用”）；**base_url 归 `deploy.py --set` 管理**（四审实测:文件为 `:8011`（Windows 隧道形态；spark-local 下 deploy.py 切为 `:8000`）——**不得手改 base_url**）；验证=**在 spark 本机执行**（或先 `deploy.py --set spark-local`、事后还原形态）；跑 1 次 3 段校验 parse/写文件。**附**：`config/llm.json` `_comment` 误导（vLLM/tmux vllm）已当场修正为 SGLang/tmux sglang。
**验证**：dry-run `python runs/h3/idea2prompts.py --idea ... --workflow video_r2v?`（flf2v 段）→ 打印 JSON；用 `h3_batch submit --stage flf2v --image a,b,c ... --prompts-file <json> --dry-run` 断言 manifest 携带每段提示词。工作量：小。

## 5. S5 SGLang 销毁性自愈演练（selfcheck --llm）

**现状**：supervisor/`selfcheck`（agent 演练）已通过；`llm_mem.wake` 自适应链存在；**sglang 销毁性演练未做**（成本顾虑）。
**实现（四审全面修订）**：`svc_main.py` 增 `selfcheck-llm`（**一次性改动三处**：line 3 用法 docstring / line 117 choices / 分派——四审提示勿漏）：
- ① 前置 `llm_mem.comfy_queue_idle()`（**与 cmd_restart_llm 同源守卫**，勿再造 queue_probe.collect 第二套）；
- ② 销毁动作**复用 `llm_mem.nap()`**（已有 is_up 前置+kill 后确认+告警；勿重复实现 pkill/tmux——会话改名/进程更名时两处同步是隐患）；
- ③ 恢复判据**窗口 ≥300s**（四审测算：supervisor 检测 ≤30s + wake 冷启 60-180s = 90~210s；90s 位于下界会误判），`--timeout` 可调（默认 300）；
- ④ 与既有 `restart-llm` 关系=互补（restart-llm=只恢复；selfcheck-llm=先销毁再验证自愈），明示勿重复造前置；
- ⑤ **`--yes` 二次确认**：`selfcheck`（agent 演练，同样销毁服务但当前无护栏）与 `selfcheck-llm` **一并对齐**加 `--yes`（安全门槛一致化）；
- ⑥ **登记既有冲突（四审新发现）**：`llm_mem.nap()` 意图“停机让位”，但 supervisor ≤30s 拉回（NAPKILL_FINISHED 无人消费；check_once 只看 session+port）→ **nap() 实际无法维持停机**；对 §5 是利好（自愈确实发生）但对 book-15 内存编排可能失效——**另立问题登记**（处置：supervisor 识别 NAPKILL_FINISHED 跳过唤醒 vs 保留“nap 必被拉起”）。
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
**取舍（审核采纳混音方案；三审定稿）**：参考音频 + T2b 旁白并存时**不做二选一**——`TTS 旁白为主轨（loudnorm -14）+ 参考音频降 12dB 做底轨混音`；**实施载体=`postprocess.mix_tracks`（已建并已接线：run_full 增 bed_audio 参数调用；注意 volume 需 **dB 后缀**、amix normalize=0——均已在三审修复并带测试）**（勿再扩展 mix_audio——它是单轨替换）；仅当用户明确「以参考音频为准」时才旁白降级。
**验证**：dry-run 断言 LoadVideo/LoadAudio 图注入；真实链一次（提交 r2v+1 视频参考）产物 ffprobe 正常；**若 7a 探测失败（无节点/无模板）→ S7 标记为『不可行（环境缺能力）』并如实归档**，不做任何臆造接线。工作量：大（7a 小 / 7b 中 / 7c 小）。
## 8. S8 批量状态轮询优化（消除子进程开销；**非真 O(1)**——ComfyUI 无批量接口，实为 O(N) 但无逐段子进程/30s 开销）

**现状**：`h3_batch status` 每段新起 `h3_submit --resume`（每段 30s）；`comfy.history(prompt_id)` 已存在（单任务 O(1)）。
**实现（五审定稿——按现有 API 可照写）**：
1. **类名**：`from h3.comfy import ComfyClient`（**非 Client**——仓库无 Client 类；五审修正附录同步）；
2. **新增 `ComfyClient.queue_pids()`**（五审已落地代码：返回 (running_pids, pending_pids) 集合——queue() 只返回计数，无法定位 pid）；
3. **状态构造参数**：`ComfyClient(retries=1, request_timeout=5)`（五审：默认 retries=3/退避5-10s/request_timeout=30 在故障时 10 段可达 150-1050s，比现状 300s 更慢；重试语义交给外层 --wait 轮询）；
4. **归一口径=决策树**（五审：`{}` 不等于失败——在途任务 history 亦为 `{}`）：
   - history(pid) 非空且含 outputs → completed；非空且 status.error → failed；
   - history(pid) == `{}` → pid ∈ queue_running → running；∈ queue_pending → pending；皆不在 → failed；
   - **诚实标注**：cancelled 与 never-queued 在 ComfyUI 侧**不可区分**（均不在 history/queue）——「含 cancelled 标记」做不到；如需区分须本地 manifest/job 记录（可选增强，不承诺）；
5. `runs/h3_batch.py` status 分支据此改写（输出兼容，--wait 轮询间隔 10s）。
**验证**：已完成 manifest status --wait 瞬时返回且状态正确；与旧输出人工 diff。**前置**：task_watch.poll_batch 缺 pathlib 修复（已在场——见 §15），S8 须确认。工作量：中（含 API 扩展 queue_pids 与决策树——五审上调说明）。

## 9. S9 会话历史导出/搜索

**现状（审核修订）**：`dev.py` **无 sessions 子命令**（零命中；`list_chats` 在 ui_app，非 dev.py）——**全新建**。**实现（四审补两点）**：`list` 须 **glob '*.jsonl'**（`logs/agent_chats/` 下有 `thumbs/` 子目录，遍历目录条目会把 thumbs 当会话）；路径常量**复用 `session_cleanup.CHATS_DIR`**（唯一权威，防第三份硬编码）。**实现**：`dev.py sessions`（新建）：`list`、`export <cid>`、`search <kw>`；纯文件读。ut ...]`、`search <kw> [--cid]`；纯文件读。
**验证**：对真实会话 export → 目检 md 内容完整；search '水墨' 命中既有会话。工作量：小。

## 10. S10 质量看板（quality-report）

**现状（审核修订）**：`runs/h3/quality.py` **不存在**（零命中）——**全新建**。**实现（五审字段缺口修正）**：① `runs/h3/quality.py`（新建）：`append(path, prompt_id='')`——**四值来源明确**：ts=append 时自生成；prompt_id=调用点传参（h3_submit 在 PROBE 处持有）；bytes=`Path.stat().st_size`；**audio 需 `postprocess.probe_av()`（五审新增：视频+音频双流探测——原 probe() 用 `-select_streams v:0`，音频结构性缺失）**；video 字段=PROBE/probe() 既有；② `compare(a,b)`（ffmpeg ssim）、`report()`；③ `dev.py quality-report`（新建）；④ h3_submit PROBE 后自动 append（probe_av）。工作量：小-中（含 probe_av 扩展与传参路径）。
**验证**：对比命令在 video_19/24（已知 SSIM 0.864）复算一致性；report 输出含该记录。工作量：小。

## 11. S12 跨会话「显式共享区」选项

**设计（语义请审核）**：新增 `refimage list --scope-shared`（=本会话 + 用户最近 7 天内『显式授权』的会话——授权=UI 新增『允许本会话访问这些会话』多选下拉，写入 `logs/agent_chats/<cid>.meta.json` `shared_from:[]`）；`list_references` 默认仍仅本会话；用户文本含『用第 X 会话的素材』时工具校验授权否则报错（复用现有『素材边界』模板）。
**实现**：`refimage.py`（scope-shared 分支）+ `ui_app`（授权多选，小型 `gr.CheckboxGroup`）+ `tools.py list_references` 透传。**风险**：权限语义（默认不授权、显式点名、可撤销）必须先在 planbook 定稿；实现排在 S9 之后。工作量：中。

## 11b. S11（不建议近期项）——规格留空

S11=§3.2 图片解析收敛（assets.py 重构）：价值/风险比低，登记观察；不提供实施规格（详见 book-13 总览）。

## 12. S13 远期池的实现预研（**注意：个别“不可行”判定已被 §14/§16 取代**——以 §14/§16 为准）

| 项 | 方案 | 可行性判定（本环境） |
|---|---|---|
| 口型驱动（Wav2Lip/SadTalker） | 独立 venv + 模型文件推理 + 音轨→口型管线 | **⚠ 已被 §14/§16 取代：可行**（魔搭通道 + 本地 GPU torch；先冒烟后全链） |
| 局部重绘 Inpaint | ComfyUI `InpaintModelConditioning`+`VAEEncodeForInpaint`（KJNodes 等已装；模型 SD1.5/SDXL-Inpaint 走魔搭） | **⚠ 已被 §14/§16 取代：可行**（图侧修复参考图乱码区；视频内逐帧重绘=远期） |
| 标题/图表后期装配 | ffmpeg `drawtext` + Noto CJK（黑体/描边/安全区已有同参数）；数据图表=SVG 渲染→ffmpeg overlay（纯本地） | **可行**（无需新模型；工作量中） |
| 1080p-级输出 | **⚠ 已被 §14/§16 取代（口径修正）**：ESRGAN 为 **4x** 模型——608×352 源→2432×1408（≈2K）；768p 源→3072×1728；按目标分辨率做 lanczos 下采样即可得 1080p/2K 档；仍如实标注=超分合成非原生 | 可行（需视觉抽检：4x 伪影/插值叠加） |
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
| 历史查询 | `runs/h3/comfy.py::ComfyClient.history` / **`queue_pids()`（五审新增）** | S8 用（类名=ComfyClient） |
| 参数档位 | `runs/agent/agent_params.py`（验证档/交付档） | book-17 §3 |
| 一致性断言 | `runs/consistency_check.py::check_quality_prompt_baseline` | Q+/Q- |

---&nbsp;
---

## 修订历史（§14-§16：审核应答与更正——独立存档，实施者不必读）

审核演变与应答全文见 **`docs/pending-tasks-changelog.md`**（§14 模型可用性更正 / §15 一轮应答 / §16 二轮应答；后续轮次应答追加于该文件）。本文档只保留各任务**当前定稿**；任务节内“审核修订”字样仅供参考。
