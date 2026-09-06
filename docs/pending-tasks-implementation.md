# 待做任务·具体实现规格（供外部 AI 审核）

> 文档性质：把「甜点/待做任务」的具体实现方案（含现状复用、文件级步骤、验证方法、风险取舍）写清，供**另一位 AI 审核**；审核者只需审本文件+抽查引用代码（所有路径相对项目根 `D:/MY_CODING_PROGRAM/videoGenerate-Model-zju`，spark 同构 `~/videoGenerate-Model-zju`）。
> 版本：2026-09-06 · **19 轮审核定稿**（changelog §14-§29）· 执行入口=docs/planbook/book-19-execution-ready.md · 关联计划书：book-13 §6（S1-S14 总览）、book-14、book-15、book-18。
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
| UI 模板转换链（九审定稿） | **本地全部 7 份模板均为 UI 格式**（按内容判定 nodes/links/widgets_values；含 3 份名为 `api_*` 的——命名是 Comfy 云通道，不是 API 格式）；**完整链=convert_ui_file → subgraph.flatten_subgraphs（解组，uiapi.py:318-324）→ ui_to_api**：4 份 video_ 中 t2v/i2v/flf2v 为子图封装（顶层节点 type=UUID，含 definitions.subgraphs），仅 r2v 为纯开放图；flatten 每次转换从 max(top_ids)+1（subgraph.py:117）/max(used_lids)+1（:119）**重排节点与 link id**、且只替换 nodes/links 不更新 last_node_id/last_link_id（:243-246——恒内存转换，现无害）——任何跨转换引用节点 id 的预置逻辑不可用（S7 设计 B 注入在转换后发生，不受影响；详见 §7 边界）。UI→API 转换依赖**在线 ComfyUI 的 `/object_info`**（只读），`stage.load_api_or_ui_template` 无 client 抛 ParamError（stage.py:322-326） | S7 在线判据**无需队列空闲**（仅真实提交/生成受队列纪律约束）；dry-run 无法完成 API 层图注入断言 |
| 长度/时长口径（十六审新增） | length 量化式（模板节点 131）：`max(5, round(s×24)) + (5-(…) % 17) % 17` ⇒ **length ≡ 5 (mod 17)**——实测 5s→124、15s→362（§2"124f"同源）；§2/§6 帧数判据应改用该式而非 seconds×24。时长上限三处并存：workflow.py:28 MAX_SECONDS=60.0（**仅警告**）/capabilities.json 四 video_ seconds{min:5,max:15}/scheduler.py:55 时长>15s=冲突——以 15s 为事实口径，60s 仅提醒；capabilities 工具级 schema `/tools/1/params/seconds` 仅有 note 无数值界（与 workflow 条目形状不一致，按数值界读取的消费者拿不到约束——登记低项） |
| 分辨率/长度输入链（十七审新增） | node 136 的 width/height/length 为**连线输入**（←node 115 ResolutionSelector 槽 0/1、node 131 ComfyMathExpression 槽 1），ui_to_api 按连线发键并把 widget 值（1344/768/124）跳过（stale=3）；随后 `apply_generation_params`（stage.py:286-293）用标量覆写（真实提交=608/352/124 360p 档）→ **node 115/131/132 在提交 dict 中成零下游消费者死重量**（prune 发生在 ui_to_api 内部、早于覆写）；length 侧语义等价（snap_length 与厂商表达式 111 点逐点对比 0 差异；5s→124、15s→362），**分辨率侧不等价——megapixels 杠杆不可达**（被 RESOLUTION_PRESETS 标量覆盖）；**死重量节点来自 custom_nodes.comfyui-logicutils**（ResolutionSelector/ComfyMathExpression/min 节点 MinNode 同源）——对产物零贡献但缺包则提交整体 400（§0 既有 KJNodes 表述未精确到这一层） |

---

## 1. S1 上传预览可判定性（gallery 缩略图标注所属会话/可用性）

# S1 上传预览可判定性（gallery 缩略图标注所属会话/可用性）——**spark-only 任务**

**目标**：预览缩略图标注「会话来历/已用/可用」，用户不再混淆多会话素材。
**现状**：`_previews_for_cid(cid)` 已按 cid 重建预览（book-13 #9b）；`_gal_by_cid` 存路径列表；gallery 无 caption。
**前提更正（十二审定稿——原"风险：低/工作量：小"标注基于两个错误前提，撤销）**：
- ① **`_known_shas` 不是存在性判据**：`_known_shas()`（ui_app.py:755-774）返回的是 log.jsonl 中出现过的 sha 集合（"曾上传过"语义 + mtime 缓存）；文件已删除/归档失败/spark 镜像未写时它仍留在集合里 → 据其判定会把已失效素材标为"可用"（重现 S1 要消除的混淆）。**`_asset_available` 必须做文件系统存在性检查**（uploads 归档 + 缩略图缓存/源文件可读），`_known_shas` 只能当**候选集**缩小检查范围，不能作判据本体。
- ② **可用性判据只在本地，不在 spark 镜像**：提交链＝`h3_submit --image` 对**本地源文件** `client.upload_image(img)`（h3_submit.py:468）→ `/upload/image`（comfy.py:202；subfolder 默认 "" → input/ **根目录**，comfy.py:58）→ 用 API 返回名 bind（h3_submit.py:486）。`input/user_uploads/` 镜像（ui_app.py:832）只服务 **refimage 列举**（refimage.py:105 注明"thread input/user_uploads 子目录，顶层扫描会漏"——refimage 是递归扫），**不是绑定来源**；ui_app.py:825 原注释"LoadImage/refimage 立即可见"中 **LoadImage 部分是错的**（LoadImage 仅认 input/ 根目录文件——六审已实测；注释已于十二审修正为"refimage 可见、LoadImage 不可见"）。**可用性判据＝本地归档/源文件是否还在（"可重新上传即可用"）**；spark 镜像状态不作判据。
**实现（文件级，三个改动点——勿漏第三个生产者）**：
1. `ui_app.py` `_previews_for_cid`/`_upload`（`_gal_by_cid[sel] = _prevs`，:1364-1365）：输出改为 `[(path, caption), ...]`，caption 由 `uploads/log.jsonl`（cid/sha/ts）拼装：`[会话 20260905_… · 已用/可用]`；**可用性=本地归档/源文件存在性（见前提 ②），已用=该 sha 是否出现在本会话 list_references 输出**（读取时计算，不持久）；
2. **第三个生产者（十二审新增，勿漏）**：`ui_app.py:1411-1417` 的 `_thumbs`（缩略图生成/回退源路径的裸字符串列表）→ 同样元组化，且**回退路径（`_make_thumb` 失败 → `str(src)`，:1416）必须加 caption 兜底**（如"缩略图不可用，核对源文件"）——该分支恰是"可用性存疑"最需标注的条目；否则 gallery 收到混合形状列表（部分有 caption、部分没有），S1 目标只实现一半；
3. `gr.Gallery` 直接收统一形状元组；若无 caption 支持则降级：加 `gr.Markdown` 行列出可用项（计划 B，不改组件）。
**验证（spark-only——Windows 侧不可开发/不可验证）**：本任务依赖 gradio（Windows 无，五审已确认）+ `_comfy_input_dir`（ui_app.py:738-747）取 spark 本机路径（Windows 克隆上恒不存在→所有 .exists() 恒 False）→ **只能在 spark 真机验证**：真实链 `_load`（驱动脚本 `load_drv.py` 模式）断言 gallery 元素含 caption 文本 + 浏览器目检。**Windows 侧只改码不验证，改后 sync 到 spark 再验证**（不得在 Windows 宣称"已通过"）。
**风险/取舍**：中-小（前提修正 + 第三改动点 + spark-only 验证成本，上调自原"低/小"）；captions 静态生成（上传时点）；已用标记以"是否出现在本会话 list_references 输出"为基准（读取时计算，不持久）。> **状态：✅ 已实施（2026-09-06，见 changelog §36 / session §20.49）**——gallery 元组化 caption（会话/已用）；spark 真机断言 PASS；浏览器目检=下次上传时登记。

工作量：小-中。**需 spark 环境**（与 §15.3 GPU 预算表并列标注）。

## 2. S2 agent 出片默认走 T2 增强（超分/降噪/锐化）——「超分怎么实现」

**目标**：agent 提交的每个任务完成后默认产出增强版（4 步瑕疵补偿），`--postprocess none` 可关。
**现状**：T2 链已存在且真机验证过（video_12：608×352→1216×704/720p、5.17s/124f，ffprobe 断言）。`h3_submit --postprocess fast` 现有完成钩子；**但 agent（call_comfyui）当前不传 `--postprocess`**。
**实现（文件级）**：
1. `runs/agent/tools.py`：CallComfyUI 提交参数追加 `--postprocess fast`（在 `--submit-only` 之后追加；dry_run 不带）；
2. `runs/h3_submit.py` 完成钩子（**三审定稿=合并单次编码**；位置以「# 二轮审阅：postprocess fast + 台词并存」注释行为准，防行号漂移）：`finalize(原片) → [fast 且 tts 并存时] tts.prepare_speech(text)→ srt_+speech → postprocess.process(原片, _pp, srt=...)  ← 增强+字幕同 -vf 单次编码 → tts.replace_audio_only(_pp, speech)（视频 copy）→ PROBE/TTS_OUT`；仅有 tts 时走 attach_speech_and_subtitle（单次烧录编码+音轨 copy）；仅 fast 时走 run_fast。**不再存在双次 CRF18 路径**；
3. 增强滤镜链（现有 `process()`，纯 ffmpeg，无 GPU）：`scale=iw*2:ih*2:flags=lanczos` → `hqdn3d=1.0` → `unsharp=5:5:0.4`（各向异性 lanczos 放大；降噪=时域去低步伪影；锐化恢复边缘；参数均可 `--postprocess fast` 固定）。
**超分方案（六审定稿——回填已确定事实，删除已撤回/未核实措辞）**：① v1 lanczos 保留兜底；② **v2 真实超分=本机已就位零下载**（§0 实测：`upscale_models/` 有 `RealESRGAN_x4plus.pth(+safetensors)` 与 `4x-UltraSharp.pth`）；**schema 已实测**（changelog 登记）：`UpscaleModelLoader` 输入键=**model_name**、`ImageUpscaleWithModel`=**upscale_model**、`LoadImage` 需 **input/ 根目录**（user_uploads 子目录不被解析）；工作流=`UpscaleModelLoader+ImageUpscaleWithModel+SaveImage`（经 `/prompt` 独立请求，不等 H3 生成队列）；**默认模型=4x-UltraSharp**（锐利/纹理优）；③ **倍率口径（六审更正）**：两模型均 **4x**——源 608×352→**2432×1408**；测试帧 1216×704→**4864×2816**（此前“1216→2432/2x”系误写）；按目标分辨率配合 lanczos 下采样即可得 720p/1080p/2K 档（如实标注=超分合成非原生）；④ 可选 RIFE 插帧（`frame_interpolation/` 为空→魔搭下载；`--interp 60fps`）；⑤ 顺序仍=增强→字幕/语音（合并单次编码）。**验证**：真实链 gen 一次（4 步 360p）：产物=1216×704、时长/帧数不变、字幕抽帧清晰、音轨 AAC 且时长=视频；`PROBE` 断言宽高。
**风险**：**二轮审阅修正（撤回“已遵守”声明）**：旧链 process+render_subtitle 曾为两次 CRF18；现已重构为合并单次编码（process 支持 srt 并入同一 -vf；run_full 同步；钩子 fast+tts 并存走合并链）——实测：video_31 离线合并链 2.4s，产物 1216×704/5.167s，字幕比例字号（0.07×704≈49px，旧绝对 20px 已废）帧目检清晰。P1 拆分：**P1a=默认 lanczos fast（单次编码，即时收益）**；**P1b=--esrgan 交付档可选（单帧实测 ~11.8s，测试帧 1216×704→**4864×2816**（4x，与 line 40 口径一致）；串行 124 帧≈24min——成本一个数量级，仅精品/交付显式启用；先做批处理并行优化，目标 3-6min，未优化前禁默认）**。工作量：P1a 小-中；P1b 中。
> **P1a 状态：✅ 已实施（2026-09-06，见 changelog §33）：tools.py 默认 --postprocess fast + postprocess job 持久化 + resume 恢复补丁。**

## 3. S3 T9 收尾（取消后任务表残留）

**现状**：`cancel_task` 取消成功即清 last_job 断点；但 `send()` 里 `all_pending_tasks/add_tasks(cid)` 登记仍在，`task_watch` 会继续轮询已取消 pid。
**前提链补齐（十八审实测——原"取消成功即清断点"假定建立在不可达的取消路径上）**：CancelTask.call（tools.py:562）此前是 7 工具中唯一不做参数归一的（JSON 字符串参数当整个串送 find_owned 必失败）；且运行中取消 /interrupt 发空 body=**全局中断**（误伤同队列他人任务，与 §0 红线矛盾）。**两条已于十八审修复**（CancelTask 归一；queue_probe.py:68-73 定向中断 body={prompt_id: pid}+服务端未命中 skip；last_job 清断点改 tmp+replace 原子写）——§3 的 mark_cancelled 分层以"CancelTask 能成功"为前提，现已成立。**
**实现（四审定稿：职责分层，防 add_tasks 覆盖撤销）**：`mark_cancelled(cid, pid)`=权威（负责发『已取消』done 事件并停止该 pid 轮询）；CancelTask 成功后仅调 `mark_cancelled`；**不**在 cancel 时调 `clear_tasks`（send() 每轮开头已清、line~1232 add_tasks 会重新登记——中途 clear_tasks 会被覆盖）；下一轮消息自然清空即止。
**验证**：单测（mock task_watch 状态）；真实链=取消运行中任务后在会话继续「查询」→ 收到『已取消』而非轮询等待。工作量：小。

> **状态：✅ 已实施（2026-09-06，见 changelog §34 / session §20.46）**——task_watch mark_cancelled 分层（登记+轮询遮蔽+worker 终态化已取消）；CancelTask 成功后调用 mark；真机：提交 720p/15s→立即取消成功（归属校验+断点清理）。
## 4. S4 idea2prompts `--segments` 真实验证 + 与 batch 衔接

**现状（已取证）**：`h3_batch submit --prompts-file <json>` **已存在**，格式=按段索引的 JSON 字典 `{"0":"pos...","1":...}`（`runs/h3_batch.py:133-151`）；`idea2prompts --segments N` 已实现（book-13 #5）但**输出为 `video_flf2v.segment_<i>.positive.txt` 文件**（与 batch 期望不匹配），且从未用真实 LLM 跑过。
**前提更正（十八审实测——原"已实现但格式不匹配"低估了问题）**：① **默认路径下 --segments 不可达**：idea2prompts.py:292 判定 `slot == "flf2v"`（裸名），而 slot_list()（:154-157）实际返回 `default, api_flf2v, api_r2v, api_t2v, video_flf2v, video_i2v, video_r2v, video_t2v`——无任何槽名等于 "flf2v" → `_write_segments` 永不执行（--segments 3 静默什么都不做、无警告；且 `--workflow flf2v` 强指时 blueprints 键是 video_flf2v → build_messages 取不到 label/extra → 丢失 flf2v 专属指导）；② **段索引基准差一且静默**：idea2prompts.py:220 1-based（segment_1..N）vs h3_batch.py:118/123 0-based（idx）→ --segments-json 若沿用 1-based 产出 {1..N}，h3_batch 查 "0"/"1"/"2"：idx0 静默回退、第 N 段永不被消费（批量照常成功、每段画面配错位提示词——与 §7c tag 硬约束同型静默错配，§4 无守卫）；③ **段数关系未声明**：h3_batch flf2v=N 图→N-1 段（range(len-1)）vs idea2prompts --segments n 写 n 段（且 :216-217 不强制数量、以 LLM 返回数为准）→ 调用方必须传 --segments (图数-1)；④ **验证方法抓不到错位**：h3_batch.py:161 dry-run 只打 SEG {idx}: images=，不打 prompt → 必须读落盘 manifest JSON 逐段比对 idx↔提示词；⑤ 验证命令含残留占位符 `--workflow video_r2v?`（字面 ?）且 video_r2v 既非 flf2v 也不能产出 flf2v 段——按字面跑得到 0 段。**实施前置（十八审定稿）**：双向槽名对齐（比较侧 slot=="flf2v"→改为匹配 video_flf2v 或 slot_list 内成员 + blueprints 查表侧用真实键）；idx 基准统一（建议 --segments-json 沿用 h3_batch 0-based 键）；段数守卫（--segments 不匹配时报错而非以 LLM 为准）；**以上为 §4 实现步骤 ① 的前置，工作量小 → 小-中（含对齐+守卫+验证改造）**。
**实现（四审事实更正）**：① 改 `idea2prompts._write_segments`：追加 `--segments-json`（与 h3_batch `--prompts-file` 的 `{"0":..}` 结构对齐）；② 真实 LLM 验证：**`config/llm.json` 当前 enabled 已为 true**（非“临时启用”）；**base_url 归 `deploy.py --set` 管理**（四审实测:文件为 `:8011`（Windows 隧道形态；spark-local 下 deploy.py 切为 `:8000`）——**不得手改 base_url**）；验证=**在 spark 本机执行**（或先 `deploy.py --set spark-local`、事后还原形态）；跑 1 次 3 段校验 parse/写文件。**附**：`config/llm.json` `_comment` 误导（vLLM/tmux vllm）已当场修正为 SGLang/tmux sglang。
> **状态：✅ 已实施（2026-09-06，见 changelog §37 / session §20.50）**——槽名/蓝图键对齐 + --segments-json(0-based) + 段数守卫 + 死 import 修复；真机：模型 1 段→守卫拒写（验证过）；登记：27B 分段遵循度弱（提示词强化待下轮）。

**验证（十八审修正——按字面命令不可执行+抓不到错位）**：① 关键对齐后：`python runs/h3/idea2prompts.py --idea ... --workflow video_flf2v --segments N --segments-json`（**N=图数-1**）→ 打印/写入 0-based JSON（`{"0":..,"N-1":..}` 结构，与 h3_batch 键一致）；② `h3_batch submit --stage flf2v --image a,b,c ... --prompts-file <json> --dry-run`；③ **断言必须读落盘 manifest JSON 逐段比对 idx↔提示词**（dry-run 输出不含 prompt，仅看 dry-run 会漏错位）；④ 真实 LLM 验证在 spark 本机（llm.json 口径见上）。工作量：小-中。

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

**实现（七审定稿+八审定稿——引擎已预接通，含 else 路径）**：`tts.py` 已支持 voice（XiaoxiaoNeural 女 / YunxiNeural 男）。**引擎（commit 93c1533+1d3e3bb+八审修复）**：`h3_submit --tts-voice`（**choices=[xiaoxiao, yunxi, 两全名]**，默认女声；**短名/全名映射层 `VOICE_ALIASES`（八审提升为 `tts.py` 公开常量，原 main() 局部 `_V_ALIASES` 工具侧无法复用——勿再还原到函数内**；h3_submit 入口归一：xiaoxiao→Xiaoxiao、yunxi→Yunxi，记录/CLI 统一全名））+ 任务记录 `tts_voice` + 完成钩子**两条路径均传 voice**（合并链 prepare_speech / **非合并链 attach_speech_and_subtitle（七审补修 else）**）+ `tts_done` 日志实际 voice。**八审补充（钩子回归修复）**：`_voice` 与 `_tj` 在 fast/非 fast 两分支共用前置归一（原 if 内赋值→else 引用 UnboundLocalError，且被 except 吞成“无语音无字幕”）；钩子已抽为模块级 `_run_tts_hook` + 分支单测（tests 7 例，无 ffmpeg）。**S6 剩余项**：① `tools.py` schema 增 `tts_voice`（**enum=短名 xiaoxiao|yunxi**，LLM 友好；**八审 Option A：tools 直接透传短名、不做映射**——归一由 h3_submit 入口完成；勿再写“tools 侧复用映射”）；② `tts_font_size` 字段（CLI `--font-size` 对应；**schema 字段名=tts_font_size**，与 CLI 名区分——七审统一）；③ SYSTEM_MESSAGE 台词规则补一句。
> **状态：✅ 已实施（2026-09-06，见 changelog §35）**——tools schema+转发+font-size 全链；真机=队列空闲窗补验。

**验证**：真实链指定 yunxi → `start argv` 含 `--tts-voice yunxi`（**八审判据更正：tools 透传短名**）且 `tts_done ... voice=zh-CN-YunxiNeural`（**记录/日志=归一全名**）；且 `TTS_OUT:` 出现、产物含 AAC 音轨+字幕（**八审重新强调：仅 `TTS_OUT:` 出现即验证语音链生效**）；字号=抽帧目检。工作量：小。

## 7. S7 参考视频/音频原生支持（book-14 T8）——最大工程

**现状（十审定稿·模板计数修正 + 簿记回填）**：本地镜像共 7 份模板（`workflows/remote_workflows/`），**全部是 UI 格式**（按内容判定：nodes/links/widgets_values；3 份名为 `api_*` 的属 Comfy 云通道模板，不是 API 格式；本地可执行的是 4 份 `video_*`）。其中 `video_minimax_h3_r2v.json` **就是 Ref2VA（ref2va）模板**：`MiniMaxH3ReferenceToVideo`（id 136）+ 参考槽位仅 `ref_videos*`/`ref_audio*` 未接线（link=null），其余事实沿用九审（LoadImage 8 张仅 2 张接 ref_image_0/1；spark core 已有 LoadVideo/LoadAudio；**ref_videos 槽位类型=IMAGE（24fps 帧序列，2-15s）→ LoadVideo 不能直连，须经 GetVideoComponents 拆帧/拆声**——spark 同事模板 utility-gan_upscaler.json 已实证同型链）。**槽位计数（十审实测·两栏口径，勿再混写）**：
**双模板树事实（十四审定案——remote_workflows 为权威）**：仓库存在两棵模板树——`workflows/remote_workflows/`（同步目标：`bats/workflow/sync_remote_workflows.bat`→`shell/sync_remote_workflows.ps1`，6 文件）与 `config/templates/`（pipeline.example.json 历史默认值，6 文件，**含 r2v 在内的全部共享文件已与前者分叉**：r2v=29 节点/8 LoadImage/8 图槽 vs 23 节点/2 LoadImage/3 图槽；i2v/t2v 等为节点数相同但字段级差异）。**权威=remote_workflows**（十四审实测：win 与 spark 的 `config/pipeline.json`（机器配置不入库）`templates_dir` 均=workflows/remote_workflows；capabilities.json template 路径、refimage `_stage_template`、template_health 均以它为基准）。`config/templates/` 已不生效（仅显式指定时可用）——S7 全部操作只认 remote_workflows；若未来清理 config/templates 需先确认无显式引用（tools.py allowlist 两棵均允许，工具描述已同步）。
**十六审补充（孤儿模板与适用边界）**：① 第 7 份模板 `video_minimax_h3_flf2v.json` 是**孤儿**——capabilities.json:262 声明在用（video_flf2v，§8 line 59 `--stage flf2v` 批量提交目标），但不在 `shell/sync_remote_workflows.ps1` 的 $names（6 项）、也不在 pipeline.example.json 的 remote_workflow_templates（6 项）→ 无登记的 spark 源路径、永不被同步刷新、来源不可追溯（解释“7 份模板 vs 同步 6 文件”差值；flf2v=本地扩展，系本地双帧变体）；② **设计 B 适用边界**：B 的“注入 id 用数字字符串”论证仅在 r2v（开放图，注入发生在转换后）成立；t2v/i2v/flf2v 为子图模板（flatten 重排 id），B 的注入虽不受影响（转换后注入），但任何“跨转换预置节点 id”逻辑不可用；若将设计 A（UI 层行合成）作用于子图模板，flatten 不更新 last_node_id/last_link_id（subgraph.py:243-246）将形成**第二个 stale 簿记源**（与十一审 ⑤ grow_slots 同类）——A 备选清单因此仅适用于 r2v 开放图模板。
**十七审补充（设计 B 生产证据 + AUTOGROW 机制根因 + id 空间口径）**：① **设计 B 前提=生产既成事实**——spark 12 份真实 r2v 提交的 node 136 输入键全部一致（audio_vae/clip/height/length/prompt/ref_image_size/ref_images.ref_image_0/ref_images.ref_image_1/vae/width）：点分 AUTOGROW 子键被服务端接受（12 次成功提交）；**不存在组选择器键**（无裸 ref_images/ref_videos——注入 ref_videos.ref_video_0 无需同步任何选择器状态，零成本论断确证）；ref_videos/ref_video_audios/ref_audios 键在生产 dict 中**一个都没有**（全部为新增键、无冲突）；ref_image_size=match 每份都在（普通标量键→参数化=纯 key-value 覆写）。② **机制根因**：_DYNAMIC=COMFY_DYNAMICCOMBO_V3（uiapi.py:39），AUTOGROW 组 spec[0]=**COMFY_AUTOGROW_V3**（cfg 仅 template 键）→ 两者不等 → _spec_kind 返回 connectable（:105）→ 四个 AUTOGROW 组不进 items（:288 只收 value/dynamic）→ 组不消费 widget（node 136 的 5 widget 恰好对应 prompt/width/height/length/ref_image_size），子槽仅可能由已连线 UI 行产生。③ **注入 id 空间具体化**：UI 文件 29 节点、id 至 146；prune 后 API dict 20 节点 id={92,115,119-132,136,137,138,139}；被 prune 9 个=3 MarkdownNote（116/117/140）+6 未接线 LoadImage（141-146）→ **注入 id 必须 >146**（不因 UI 141-146 已占用而撞车；LoRA 注入的 lora_+len(wf) 字符串 id 属 96d2188 已容错历史，注入新节点仍用数字串）。④ **LoadImage 口径**：8 个 LoadImage=UI 文件事实；提交时 API dict 仅 2 个——template_health（workflow_registry.py:94）以**模板文件（UI 侧）**数 LoadImage=8，验收判据先声明数的是 UI 侧（期望 8 实际 8），勿按提交 dict 侧误判。
**模板内嵌官方文档（十四审回填——MarkdownNote id 116，Comfy-Org 官方说明，前 13 轮无人读取）**：① **调度器建议**——官方“Sampler: res_multistep. beta or normal scheduler tends to outperform simple for reference-heavy prompts like this one”；模板实测 KSamplerSelect=res_multistep（:123✅）但 **BasicScheduler=simple（:124）**——参考密集（S7 正是让参考更密集）场景下为官方不推荐值；**零成本改进落点=stage.py:292 同点覆写 `scheduler` 键（十七审键名勘误：object_info required=[model,scheduler,steps,denoise]——**无 scheduler_name**，全仓 0 命中；scheduler=COMBO options 含 simple/beta/normal；16 份生产提交键集一致；守卫模式="scheduler" in ins，验证档 simple/交付档 beta），agent_params.py 档位映射；② **ref_image_size 未参数化**——官方“match scales references down to the generation's resolution (faster); max keeps up to a 2048px short edge for stronger identity fidelity, at the cost of speed”；模板当前固定 match（node 136 第 5 widget）；全仓仅 uiapi.py:129 注释认识它；参数化落点=capabilities params、CLI `--ref-image-size`、agent_params 档位（验证档 match/交付档 max）、uiapi 转换已兼容；③ **原生 2K 上限**——官方“Output is up to 2K resolution, 24fps”；当前链路上限 768p（来源待查=加速 LoRA 训练/受限 vs 模型本身），§13 已改标注为待探测；④ **tag 契约原文**——官方“reference the inputs by tag, in the exact order they were connected...matching the reference tags precisely...tends to work best”——§7c 的 N-1 映射与 tag==列表硬约束由此取得**厂商契约依据**（非仅审核建议）。
模板已暴露行数 vs 节点 object_info 支持上限——
`ref_images`：模板 **8 行**（ref_image_0..7，0/1 已接；8 个 LoadImage 节点）｜节点上限 **9**（AUTOGROW max；第 9 行属行合成扩容，非本任务目标）；
`ref_videos` / `ref_video_audios` / `ref_audios`：模板**各 1 行**（index 0，均未接）｜节点上限 **3 / 3 / 3**（AUTOGROW max；接入 N=2..3 需要行或键合成，两栏含义实施成本差一个量级——见 7b 设计决策）。
**模板簿记实测**：last_node_id=140、last_link_id=282、nodes=29、links=25（新建节点/链接时的同步参考；`_wire_slot` 用 max+1 规避簿记，但新建节点需同步 last_node_id）。
**分三步实现（每步可独立验收）**：
- **7a 探测登记（十审修订：目标条目计数修正 + 校验改造）**：复核 `MiniMaxH3ReferenceToVideo`/`LoadVideo`/`LoadAudio`/`GetVideoComponents` 的 object_info（`/object_info/<type>` **只读、不需队列空闲**——见 §0）与本地镜像完整性 → 结果写入 capabilities.json 新 stage `video_ref2v` 与 code-fact-registry。**登记后必须补全**（九审中项保留）：`workflow_registry.add_local`（workflow_registry.py:177-200）写入空 slots + features 全 false（:190-196，返回消息即写“请补全”）——方案＝扩展 `add_local` 接受 slots/features（推荐），或登记后 patch + `validate_all`。**目标条目（十审计数修正）**：slots={images:[{role:reference,count:**8**}], videos:[{role:reference,count:3}], audios:[{role:reference,count:3}]}、features={reference_videos:true, audio:true, negative_support:true}、template=`workflows/remote_workflows/video_minimax_h3_r2v.json`、prompt_inject/inject_spec 按 `video_r2v` 现条目同构。**images 勿写 9**：`template_health`（workflow_registry.py:127-130）按 LoadImage 节点数校验（need=image_slot_count=9 > got=8 → “期望 9 实际 8”拦截）；**videos/audios 的 3 为能力口径**（设计 B 下注入层可达；模板仅预置 1 行——现状段两栏已标注）。**落点 4（登记校验改造）**：`template_health` 扩展按所选设计分型——设计 B（主案）：videos/audios 不数模板行，改为 validate 时对注入能力做 object_info 复核（节点存在 + features 一致）；设计 A（备选）：数模板行数 ≥ count（行合成后计）。**复核清单新增（十二审）：**以 `curl -F` 上传一个 .mp4 到 `POST /upload/image` 抽验（**十七审升级为服务端源码级确证，非必须**：spark server.py image_upload :397-441 无 MIME/扩展名/内容校验、仅路径逃逸检查+裸写字节；get_dir_by_type :370-381 type=input→input/ 根目录；同名重传走 compare_image_hash :383-395 裸字节哈希不经 PIL→mp4/mp3 不抛异常，overwrite=false 重复上传安全——抽验留作实施期 5 秒余量，不再阻塞 7b）。若复核失败（节点/槽位缺失或版本不符）→ **标记『不可行（环境缺能力）』并如实归档**（取舍保留）。
**十四审补充**：① **params 增 ref_image_size**（match=验证档/max=交付档；官方“max keeps up to a 2048px short edge for stronger identity fidelity, at the cost of speed”——速度代价如实登记）；② **pipeline.json 注册（7a 新增、缺则不可提交）**：h3_submit 的 stage 定义来自 `config/pipeline.json`（**机器配置不入库**，spark 侧须就地改）：stages 增 `video_ref2v`（template=video_minimax_h3_r2v.json、template_kind=ui）+ `remote_workflow_templates` 键同步 + 确认 templates_dir=workflows/remote_workflows（win/spark 现配置已是；pipeline.example.json 十四审已改正默认值）；若只登记 capabilities.json 而不注册 pipeline.json，stage 将不可提交；③ **images=8 vs 官方 9 显式取舍**：count=8=模板现状（template_health 按 LoadImage 节点数=8 校验）；第 9 位需 grow_slots 行合成=可选增强（**注意**：capabilities 向 agent 声明 8 后，agent 会拒绝第 9 张参考图——若需 9 张能力，先做 grow_slots 扩容再改 count，否则注册表与实际能力不符）。
**十九审定稿（命名空间定案——原"新 stage video_ref2v"废弃）**：capabilities 条目同时携带 id 与 stage 两套命名（id=video_X、stage=X；tools.py enum 派生自 stage；resolve 按 stage/id/slot 首个命中）；"新 stage video_ref2v"两种读法均有缺陷：A（id=video_ref2v, stage=r2v）→ resolve 首个命中遮蔽新条目 + agent enum 出现重复 r2v→S7 能力 agent 不可选；B（stage=video_ref2v）→ agent_params.default_lora_for_stage（仅精确匹配 r2v）返回 None→**加速 LoRA 静默消失**（20 步而非 4 步≈5× GPU、exit 0 无警告）。**定稿=不新建 stage，扩展现有 video_r2v 条目**：id/stage/slot 保持 video_r2v/r2v（无命名空间冲突）；slots.videos/audios 填 3/3、features.reference_videos=True、params 增 ref_image_size；lora.stages=[r2v] 已覆盖（agent_params 无需改）；pipeline.json 无需新 stage（r2v 已存在——**7a 原"stages 增 video_ref2v"删去**，仅确认 templates_dir）；agent stage enum 不变（t2v/i2v/r2v/flf2v）；若未来产品需区分"纯图 r2v/视频参考 r2v"档位再引入变体（登记，非 S7 范围）。**7a 一级判据补充（十九审 §四）**：_apply_registry_derived_schema 被 except:pass 包住且导入时执行——注册表文件坏/导入失败时 enum 静默停留 fallback（进程正常、工具可用、无报错）；7a 验收必须**在 agent 进程内打印 CallComfyUI.parameters.properties.stage.enum 实际值**（而非只查 capabilities.json 文件内容），否则"登记没生效"的真因（导入期吞掉的异常）不可见；tools.py 侧同步已加导入期失败 stderr 告警（十九审修复）。
- **7b 引擎接线（十审定稿：主案=API 层注入，循 apply_lora 先例——可省九审落点 1 全部与落点 2 大部）**：
  - **设计决策（十审 §四→定稿）**：两设计对照——A=UI 层绑定（行合成/uiapi 分支：模板可往返调试，但需文件选择器分支+UI 行合成+簿记，N=2..3 重）；B=先 `load_api_or_ui_template` 转出扁平 API dict，再**直接在 API 层注入三类节点与槽位键**（同 `apply_lora` 先例 stage.py:180-220，调用点 h3_submit.py:545 同链）：**主案=设计 B**。理由：① 同型先例已被生产验证（LoRA 注入 + 96d2188 字符串 id 修复后 API→UI 存档往返可用）；② N=2..3 只加一个键、零行合成；③ 免 uiapi.py 文件选择器分支与 UI 簿记；④ 注入节点 id 用**数字字符串**（避开 apply_lora `lora_N` 字符串 id 曾致 UI 存档崩溃的脆弱史，workflow_to_ui 已容错）。代价（如实记录）：双注入点分裂（images 仍在 UI 层 bind_images_to_template、videos/audios 在 API 层注入；统一迁移 images 到 API 层=可选低优先，不动现存 bind 链）；模板副本 UI 中看不到参考视频/音频节点（存档 UI 版为反推近似，含注入节点）；若未来复用含 LoadVideo/LoadAudio 的 UI 模板，转换器仍会抛 UiUnsupported（uiapi.py:302-305）——S7 不采用此类模板，属已知边界。
  - **落点 2（主案·API 层注入函数）**：新建 `inject_media_refs(wf, video_names, audio_names)`（建议 `runs/h3/refimage.py` 或 `stage.py`，与 apply_lora 同型）：对每个视频 i（0-based，≤2）：新建 `LoadVideo`（id 用数字字符串）`{"class_type":"LoadVideo","inputs":{"file": <远端名>}}`、`GetVideoComponents` `{"inputs":{"video":[lv_id,0]}}`，写槽位键 `h3["inputs"]["ref_videos.ref_video_i"]=[gvc_id,0]`（images 槽）、`h3["inputs"]["ref_video_audios.ref_video_audio_i"]=[gvc_id,1]`（audio 槽）；每个音频 j（≤2）：新建 `LoadAudio` `{"inputs":{"audio": <远端名>}}`，写 `h3["inputs"]["ref_audios.ref_audio_j"]=[la_id,0]`。目标节点=class_type `MiniMaxH3ReferenceToVideo`（或按 inject_spec.class_prefix 匹配）；**守卫**：目标节点缺失/上限超 3 报错、`--dry-run` 不注入仅打印。
  - **落点 3（上传顺序，九审保留）**：videos/audios 先上传到 spark ComfyUI **input/ 根目录**（LoadVideo/LoadAudio 的 COMBO options=input 根目录文件列表；现有 `--image` 链即“先上传后转换”，机制同源）→ 后注入 `file`/`audio`=远端名；`h3_submit` 增 `--videos/--audios`（append）；**上传定稿（十二审正面确证）：直接复用 `ComfyClient.upload_image`，无需新增 upload_file**——四证据：字段名 name="image" 为 /upload/image 端点要求（comfy.py:52）；Content-Type: application/octet-stream 与文件类型无关（:53）；type=input（:42）；subfolder 非空才追加→默认落 input/ 根目录（:58），与本节要求一致（唯一未验证项=服务端是否校验扩展名/MIME，见 7a 复核清单）；`capabilities` 注册 params（沿用 r2v 口径）。
  - **备选（设计 A，不实施·记录供将来翻案——十一审成本更正：非"从零构建 UI 行合成"而是"参数化已有函数"，且十审"现有代码无此能力"表述按十一审更正为"能力已有、泛化缺失"）**：已有能力＝`grow_slots`（refimage.py:497-526：`ref_image_N` 目标行追加+`_clone_loadimage` 克隆占位，COMFY_AUTOGROW_V3 机制）＋`_wire_slot`（:541-556：链接合成）。**A 的必要前置=uiapi.py 文件选择器分支**（A 下模板含 LoadVideo/LoadAudio，转换器必然遇到：2 值 widgets（文件名+展示值）→通用路径消费 1 值触发 uiapi.py:302-305 UiUnsupported；需与 LoadImage 特例同型：首值+widgets.clear()。**双源证据**：① spark 实测 utility-gan_upscaler.json node 9（LoadVideo widgets=["MiniMax_H3_00035_.mp4","image"]）；② 本地佐证 refimage.py:487 `new["widgets_values"] = [defaults[...], "image"]`——本项目克隆逻辑自身就在生成"文件名+展示值 image"双值模式（同构，LoadImage 声明 2 输入故不残留、LoadVideo 只声明 1 输入故必残留——与 :302-305 的 stale 检查吻合）。**。**A 的首要缺口（十七审新增，比簿记严重一个量级）＝行合成≠生效**：ui_to_api:195（`if not isinstance(slot, dict) or slot.get(link) is None: continue`）——**合成但 link=None 的 UI 输入行对 API dict 贡献为零**；grow_slots 只追加行+克隆占位（不接线），接线是 _wire_slot 的独立步骤 → A 必须**行合成+接线两步都做对**才生效；错了的后果=提交照常成功、产物照常出、参考关系静默缺失（与 §7c tag 硬约束针对的同一类静默错配）。****A 的剩余缺口=四处硬编码参数化**：① 前缀 `ref_images.ref_image_`（:511）→ `ref_videos.`/`ref_video_audios.`/`ref_audios.`（`_owner_rows` 已前缀泛化，:529-538）；② 类型 "IMAGE"（:520 行、:551 链接）→ 音频槽 "AUDIO"；③ 源输出槽 0＋按名匹配 ("IMAGE","")（:551/:554）→ GVC audio=输出槽 1；④ 占位节点克隆 `_clone_loadimage`（:522）→ 需克隆 LoadVideo/LoadAudio（LoadImage 无 audio 输出）。**另补两条（十一审 §3）**：⑤ `grow_slots` 不更新 `last_node_id`（`_clone_loadimage` 用 max(id)+1 分配新节点 id 但模板簿记不动，:485-486/:525）——正确算法在 workflow.py:255（max(node_ids)）但 refimage.py 未导入 workflow（:432 仅局部导入 workflow_registry），A 下须复用，否则扩槽模板在 ComfyUI UI 中打开并新增节点时 id 冲突；⑥ `grow_slots` 原地写回且无 template 副本参数（:525 write_text；签名仅 tpl,total,defaults）——并发风险高于 bind_images_to_template（后者至少允许传副本），A 下须按"template 必填/任务副本"原则改造（与 bind_refs_to_template 相同）。①-⑥=工作量"中"（参数化+簿记/副本改造，低于上轮"大上沿"估计）；因 B 连 uiapi 分支都省掉（B 下注入在 API 层、转换器见不到 LoadVideo/LoadAudio），**主案 B 维持不变**。

- **7c 工具/提示词（十一定稿：tag 不对称说明 + 双通道硬约束——S7 中唯一可能"静默产出错误结果"的设计点）**：`tools.py call_comfyui` 增 `videos/audios`（同 `images` 语义；上限 3/3）；SYSTEM_MESSAGE 加 `<Video N>/<Audio N>` 提示词规范——**`<Video N>`↔`ref_videos.ref_video_(N-1)`、`<Audio N>`↔`ref_audios.ref_audio_(N-1)`**（tag=1-based 按连接顺序、槽位键=0-based；**厂商契约依据**=模板内嵌 MarkdownNote id 116 原文"reference the inputs by tag, in the exact order they were connected"+"matching the reference tags precisely...tends to work best"——非仅审核建议）。**为何只给 video/audio tag、images 保持位置序**（十一审 2.1 对称性说明）：① 视频=动作/运动参考、音频=氛围参考，语义上必须在提示词里显式指代（与画面内容共同描述"怎么动/什么氛围"）；图片=身份/场景参考，既有链已由 `refimage use --slot N`（位置管理）与 tools.py:296 位置序约定覆盖（全仓无 `<Picture N>` tag 约定），保持现状不动；② 若未来统一，images 可走官方 `<Picture N>`（node 支持，ref_images max 9）——可选增强低优先，不在 S7 范围。**双通道硬约束（十一审 2.2，最实质风险）**：tag（提示词文本）与槽位（`--videos/--audios` 列表顺序）是**两个独立通道**——顺序错位时产物照常生成、ffprobe 与一级判据全部通过、但参考关系错误（静默错配，比崩溃更难发现）——**定稿：槽位由列表顺序唯一决定；tools.py 拼装时校验 tag 序号集合 == 列表索引集合（{1..len(列表)}），不一致即报错拒提交**；SYSTEM_MESSAGE 明示"提示词中引用的 <Video N>/<Audio N> 必须与提交的 videos/audios 列表一一对应"。

**取舍（审核采纳混音方案；三审定稿）**：参考音频 + T2b 旁白并存时**不做二选一**——`TTS 旁白为主轨（loudnorm -14）+ 参考音频降 12dB 做底轨混音`；**实施载体=`postprocess.mix_tracks`**（已建并已接线，volume 需 dB 后缀、amix normalize=0）；勿再扩展 mix_audio（单轨替换）；仅当用户明确「以参考音频为准」时才旁白降级。
**验证（十审修订：一级判据改在“注入后 API dict”上断言——uiapi 分支已随设计 B 移除，原“无 image 展示值”断言随分支一并撤除）**：
- **一级（转换+注入判据，需在线 client；`/object_info` 只读、不需队列空闲，见 §0）**：`convert_ui_file` 后 + `inject_media_refs` 后断言——① 注入后 wf 含 class_type `LoadVideo`/`GetVideoComponents`/`LoadAudio`；② 各注入节点 inputs 只含预期键（`file`/`video`/`audio`，无多余键）；③ `MiniMaxH3ReferenceToVideo.inputs` 含 `ref_videos.ref_video_0=[gvc,0]`、`ref_video_audios.ref_video_audio_0=[gvc,1]`、`ref_audios.ref_audio_0=[la,0]`；④ 一致性守卫（视频/音频上限 >3 报错；提示词 tag 集合与列表索引集合一致——见 7c 双通道硬约束）。该层可单测打桩（mock `fetch_object_info`/client + 构造 wf，无 ffmpeg、不占生成队列）。
- **二级（真机判据，一次真实提交）**：`--stage r2v --videos ref1.mp4 --audios amb1.mp3` 真实提交（队列空闲窗口）→ 产物 ffprobe 正常（视频+音频流）→ 提示词含 `<Video 1>` 时抽样帧目检（参考视频动作/风格可辨识——如实评估）+ 音频槽位采纳情况听测/ASR 抽检（口径同八审）。
- **dry-run 边界**：dry-run 仍无法完成 UI→API 转换（stage.py:322-326 无 client 抛 ParamError）→ dry-run 仅打印注入计划；API 层断言须在线。
- **若 7a 复核失败（无节点/无模板）→ S7 标记为『不可行（环境缺能力）』并如实归档**，不做任何臆造接线。工作量：**大（7a 小 / 7b 中 / 7c 小）**——设计 B 下 7b=注入函数+上传+登记校验改造+两级验证（4 落点），从九审“中-大”回落（因落点 1 与 UI 行合成被设计 B 省掉）；若翻案走设计 A=中-大乃至大上沿（3 视频槽行合成）。
## 8. S8 批量状态轮询优化（消除子进程开销

> **状态：✅ 已实施（2026-09-06，见 changelog §31 / session §20.41）**——comfy.classify_task_state 决策树 + h3_batch status 改写（无子进程、--wait 10s、absent 如实标注）；真机：已完成批瞬时 3/3、失败批如实 failed。；**非真 O(1)**——ComfyUI 无批量接口，实为 O(N) 但无逐段子进程/30s 开销）

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
**验证**：已完成 manifest status --wait 瞬时返回且状态正确；与旧输出人工 diff。**前置**：task_watch.poll_batch 缺 pathlib 修复（已在场——见 changelog §15 与提交记录），S8 须确认。工作量：中（含 API 扩展 queue_pids 与决策树——五审上调说明）。

## 9. S9 会话历史导出/搜索

**现状（审核修订）**：`dev.py` **无 sessions 子命令**（零命中；`list_chats` 在 ui_app，非 dev.py）——**全新建**。**实现（七审清理回填）**：① `list` 须 `glob '*.jsonl'`（`logs/agent_chats/` 下有 `thumbs/` 子目录，遍历目录条目会把 thumbs 当会话）；② 路径常量**复用 `session_cleanup.CHATS_DIR`**（唯一权威）；③ 子命令=`dev.py sessions list` / `export <cid> [--out docs/exports/<cid>.md]` / `search <kw> [--cid]`（纯文件读）。
**十八审更正**："唯一权威"表述不成立——`session_cleanup.py:36` 与 `ui_app.py:40` 各自独立定义同值 CHATS_DIR（ui_app.py:41 另有 THUMBS_DIR=CHATS_DIR/thumbs），今日同值但属典型漂移点；S9 实施时抽公共常量（或保持引用并注明双定义）；thumbs/ 子目录确实在 CHATS_DIR 下（glob 必要性成立）。**§9 标注 spark-only**：logs/agent_chats/ 在 Windows 克隆不存在（与 §1 同病），验证只能在 spark 做。
**验证**：对真实会话 export（md 完整：用户/助手分段+UTC+8 时间戳）→ 目检；search '水墨' 命中既有会话。工作量：小。

## 10. S10 质量看板（quality-report）

**现状（审核修订）**：`runs/h3/quality.py` **不存在**（零命中）——**全新建**。**实现（五审字段缺口修正）**：① `runs/h3/quality.py`（新建）：`append(path, prompt_id='')`——**四值来源明确**：ts=append 时自生成；prompt_id=调用点传参（h3_submit 在 PROBE 处持有）；bytes=`probe_av()` 返回的 size（与其余字段同源，**择一**；不另用 Path.stat）**audio 需 `postprocess.probe_av()`（五审新增：视频+音频双流探测——原 probe() 用 `-select_streams v:0`，音频结构性缺失）**；video 字段=PROBE/probe() 既有；② `compare(a,b)`（ffmpeg ssim）、`report()`；③ `dev.py quality-report`（新建）；④ h3_submit PROBE 后自动 append（probe_av）。工作量：小-中（含 probe_av 扩展与传参路径）。
**十八审备注（低）**：probe_av 超时比 probe 紧（postprocess.py:38 timeout=30 vs :72 timeout=60）——§10 以 probe_av 为主取值源，大文件更易超时；实施时对齐超时或按文件大小选择探针。
**验证**：对比命令在 video_19/24（已知 SSIM 0.864）复算一致性；report 输出含该记录。工作量：小-中（与 §10 实现估值一致）。

## 11. S11（不建议近期项）——规格留空

S11=§3.2 图片解析收敛（assets.py 重构）：价值/风险比低，登记观察；不提供实施规格（详见 book-13 总览）。

## 12. S12 跨会话「显式共享区」选项

**设计（十三审定稿——五项全部定案；原"写入 meta.json / --scope-shared flag / 调试点签发 token"三处设计废止后重写）**：用户点名『用第 X 会话的素材』→ 系统生成一次性 token 写入**独立文件** `logs/agent_chats/<target>.grants.json`（**不写入 meta.json**——该文件被 ui_app.py:160-163 以 3 键字面字典每轮 w 模式无条件覆写，写入即静默丢失；独立文件避开热路径、无需回合话保存逻辑）；grants 文件**必须 tmp+replace 原子写**（仿 tts.py:194 先例；meta.json 是仓库少数非原子写持久化点、三写者无锁，本项目不复用该模式）→ `list_references --session shared-<target>`（**接口定稿=复用 session 魔术值 shared-<target>，不新增 CLI flag**；`--scope-shared` 方案作废——两方案改动面差异见实现 3）校验 token → **轮末失效**（生命周期绑定 turn_id：grant 时记录 turn；一轮内可重复读——LLM 重试安全；下一轮 `increment_turn_id`（ui_app.py:1099）后自动失效，无需持久的"焚毁"状态机）。
**实现（十三审定稿——五处触发点齐列）**：
1. **存放与签发存储**：`refimage.py` 增 `grant <target> <turn_id> [--ttl]`（token 生成/原子写/校验/失效回调；会话删除时随 jsonl/meta 一并清 grants，`session_cleanup` 加一行）；token 字段={target_cid, src_cid, turn_id, expires, used:false}。
2. **签发者=对话显式确认轮（人类弱在环定稿）**：`tools.py` 增白名单工具 `grant_refs(target, reason)`——**仅当当前轮用户消息含明确授权声明**（启发式：用户消息含"允许/可以/同意/用…素材"且指明目标会话）时放行；**模型自行签发/自动签发=禁止**（与"默认不授权"一致；audit 留痕；更强在环=UI 瞬态确认弹窗列为可选增强，不阻塞）。scheduler.py:55 情形②（素材授权询问）/scheduler.py:121/123 铁律（须用户明确授权并指明）已有落点。**代价登记**：弱在环（启发式可被绕过，纵深防御下有 audit；显式弹窗为后续增强）。
3. **接口与解析（magic 值定稿）**：`normalize_session`（refimage.py:259-269）增 shared- 前缀识别（拆出 target，返回特殊标记，禁止原样透传——现状 shared-X 会按 cid 过滤→静默空结果且提示语反向引导）；`cmd_list`（:309-317）增 shared 分支（校验 token→通过则按 target 过滤；失败=区分"未签发/过期/已失效"三种提示——含"注：token 若写入 meta.json 会被会话保存覆写"的排障提示）；`tools.py:441-448` 分派点增第三分支；**同节提示语反引导修正**（:306/:313 "如需全部素材请用 --scope-all"→改为指向 shared-<target> 精授权路径；--scope-all 仅保留用户显式授权语义）。
4. **宽路径定稿（session=all 去留=保留但登记收窄）**：不退役、不要求 token（既有功能+工具描述已要求"用户明确授权"）；**收窄引导**=list_references 工具描述升级（"单会话共享请用 shared-<target>（精授权，需用户确认后签发）；确需全部素材（--scope-all）仍要求用户明确授权并明示暴露面"）。**登记**：S12 不改变 --scope-all 的暴露面（若未来收窄 --scope-all 需另立项，非 S12 范围）——这是 S12 安全收益的上限，如实标注。
5. **与重试交互定稿**：token 一轮内可重复读（"用后即焚"语义=轮末失效，非一次调用焚毁）——杜绝"LLM 重试→token 已焚→空结果→模型回退 --scope-all"的退化（十三审 §四，比一次性调用更优）。
**风险**：token 生命周期（轮末失效+过期+来源校验+与重试交互——一轮内重复读安全）；弱在环（对话确认+启发式，audit 兜底）；--scope-all 暴露面未收窄（登记）；实现排在 S9 之后。工作量：中。

## 13. S13 远期池（**当前结论**；演变见 changelog）

| 项 | 方案 | 当前结论 |
|---|---|---|
| 口型驱动（Wav2Lip/SadTalker） | 独立 venv + 模型(魔搭) + 音轨→口型管线；先 5s 冒烟后全链 | 可行（魔搭通道 + sglang-venv torch；工作量=大） |
| 局部重绘 Inpaint | SD1.5/SDXL-Inpaint（魔搭）+ ComfyUI inpaint 节点（KJNodes 已装） | 可行（图侧修复参考图乱码区；视频内逐帧=远期） |
| 标题/图表后期装配 | ffmpeg drawtext（Noto CJK）/ 数据图=SVG→overlay | 可行（无新模型；工作量中） |
| 1080p-级输出 | 4x 模型 608→2432×1408（测试帧 1216→4864×2816），按目标 lanczos 降采样 | 可行但标注修正（十六审查实：**模型本体不施加 768p**——MiniMaxH3ReferenceToVideo width/height max=16384/step=32、ResolutionSelector megapixels max=16.0、官方标称 up to 2K；**768p=项目侧硬编码（十九审更正：有效站点 4 处、原"6 处"中 tools.py:260/:792 不准确）**：workflow.py:18-24 RESOLUTION_PRESETS（CLI/校验侧）/capabilities.json 四 workflow params.resolutions（**agent 侧真实杠杆**——_apply_registry_derived_schema 导入时用注册表派生值覆写 CallComfyUI.parameters enum，:260 静态 enum 运行时无效、:792 仅为注册表读不到时的 fallback）/workflow_registry.py:193 默认模板/h3_text2img.py:40 重复表；**原生 1080p/2K 探测无需改代码**（十七审修正：**ResolutionSelector 的 megapixels 杠杆在现行链路上不可达**——node 136 的 width/height/length 是连线输入（node 115 ResolutionSelector / node 131 ComfyMathExpression），首次提交会被 apply_generation_params 标量覆写（真实提交=608/352/124），node 115/131/132 成为零下游消费者的死重量节点；唯一分辨率杠杆=RESOLUTION_PRESETS 或 --width/--height 逃生口（勿再提调 megapixels 探测））+ h3_submit.py:285-286 `--width/--height`（**CLI-only：tools.py 全文 0 命中 width/height，agent 路径够不着**）；**口径冲突**：逃生口 %8 vs 节点 step=32——正确探测值=**1920×1088**（均 %32；朴素 1920×1080 会通过项目校验但违反节点约束）；项目上限 4096 < 节点 16384；探测提交=1920×1088 + `--lora none`（20 步）一次定三事（墙钟/显存、ref2v_4step/8step 在 768p+ 是否可用、服务端是否强制 step=32）——**待用户授权队列空闲窗口**（**十七审定案：768p 上限=LoRA 非模型**——LoraLoaderModelOnly.lora_name options=3 且文件名自带标签：fl2v_4step→minimax_h3_fl2v_turbo_4step_v1.0_768p_comfyui_bf16（768p）/ref2v_4step→minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16（**无分辨率标签且 v0.1**）/ref2v_8step→minimax_h3_ref2v_turbo_8step_v1.0_768p_comfyui_bf16（768p）→ 模型本体不限 768p，限制来自加速 LoRA（待查二选一划掉）；**产品级取舍**：交付档=720p/768p+ref2v_8step（agent_params.py:17/scheduler.py:71/99）——若原生 1080p 成立则交付档必须改为 1080p+`--lora none`（20 步），**两者互斥**；粗算 GPU 成本≈**5×**（步数 8→20=2.5× × 像素 1.03→2.09MP=2.02×）——§15.3/§15.5 已登记（比表内任何项贵）；**探测最不确定环节**=ref2v_4step v0.1 无标签（验证档在 768p+ 的行为完全未声明）；另正面确证：capabilities.json lora.files/steps/choices 与 COMBO options 逐字符一致（无错配）、ref2va 权重=**int8 剪量化**（2.1MP 显存余量正面信号）。）；若原生成立：P1b 分辨率立论消失、§13"超分合成非原生"改"原生可达 1080p 级"、S2-v2 优先级重排；**另记录**（十六审）：ref_images tooltip 原文"downscaled to 2048 short edge if larger, never upscaled"→参考图修复/增强产物有效分辨率**封顶 2048 短边**（§13 Inpaint 行适用）） |
**十九审补充（顺序耦合陷阱）**：agent 的 resolution enum 派生自**首个** enabled+有 params 条目（_derive_tool_enums:771-775 命中即 break——实测=video_t2v，index 0）；若探测成功后要加 1080p 预设，必须加到 video_t2v **或全部四条**（只加 r2v/ref2v 条目则 agent enum 不变、看不到新档位；四条现 resolutions 相同故今日无差异）。
| 齿音处理 | afftdn 已加；齿音=谱减类无内建 | 暂缓（低价值） |

## 14. 疑点与结论（对照表；演变见 changelog）

| # | 疑点 | 结论 |
|---|---|---|
| 1 | S2 先增强后字幕？（原论证基于字号语义） | 成立（三审后字号=比例，增强后更清晰）；顺序定稿=合并单次编码（§2） |
| 2 | S7 探测失败处置 | 同意「标记不可行并归档」（§7） |
| 3 | 参考音频 vs 旁白 | 定稿混音（§7 mix_tracks） |
| 4 | S8 归一口径 | 定稿决策树（§8：空 dict 须队列消歧；cancelled 不可区分） |
| 5 | S12 权限模型 | 定稿一次性 token（§12） |
| 6 | GPU 预算/队列纪律 | 认可（changelog §15.3 预算表；按一意图一驱动） |

---

## 修订历史（§14-§16：审核应答与更正——独立存档，实施者不必读）

审核演变与应答全文见 **`docs/pending-tasks-changelog.md`**（§14 模型可用性更正 / §15 一轮应答 / §16 二轮应答；后续轮次应答追加于该文件）。本文档只保留各任务**当前定稿**；任务节内“审核修订”字样仅供参考。
