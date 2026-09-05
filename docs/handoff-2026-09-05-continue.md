# 交接文档（2026-09-05 · 八审闭环后 · 新 Agent 接手专用）

> 用途：**让新 Agent 无缝接手规划任务**（不依赖原会话上下文）。本档自包含；
> 与 `docs/handoff-2026-09-05-L-tasks.md`（book-14 L1–L5，已完成）互不覆盖。
> 现状时间点：**十二轮外部审核闭环**（八轮=代码修复+真机验收；九/十/十一审=S7 规格专项修订；十二审=S1 专项+§7b 上传链确证——权威见 changelog §20-§23 与 pending-tasks-implementation §1/§7 十二审定稿）；仓库双端干净。
>
> 一句话现状：规划书 `docs/pending-tasks-implementation.md`（S1–S13 + P2–P6）经 **10 轮审核**定稿（十审=S7 计数修正 + 主案改 API 层注入（apply_lora 同型）/GetVideoComponents 链/登记补全/两级验证判据），
> 唯二被审出的**代码回归**（TTS 钩子两处 UnboundLocalError、workflow UI 存档缺失）已修复；
> **剩余全部为待实施任务**，推荐从 S2-P1a → S3 → S8 开始（§5）。

---

## 0. 仓库与版本事实（先读，再动手）

| 端 | 路径 | 角色 |
|---|---|---|
| Windows 主库（**源码真源**） | `D:\MY_CODING_PROGRAM\videoGenerate-Model-zju` | 一切改动先改这里；唯一 push GitHub 的一端 |
| GitHub | `sakuraahly/videoGenerate-Model-zju` | Windows push；**spark 永不 push** |
| spark 运行时 | `/home/Developer/videoGenerate-Model-zju`（`ssh spark` 免密） | 运行实例；只能经 dev.py sync/commit 同步 |
| ⚠️ 禁用 | `C:\Users\39163\videoGenerate-Model-zju`（残留副本）、`Z:/` 网络映射 | 勿用 |

**当前 HEAD（2026-09-05 八审提交后）**：windows=`3f42488` · github=`3f42488` · spark=`d10b6be`（两端 0 dirty；
spark commit 哈希与 win 不同是常态，spark 用内联身份提交）。上次工作流修复：win `96d2188`/spark `2c3db4b`。

**必读文档（按顺序）**：
1. `START-HERE.md`（§2 索引、§3 架构）
2. `docs/dev-workflow.md` —— **全程遵守**（执行→修改→测试→自测通过→写入文档→双端核对→git 提交）；§10 环境坑
3. `docs/pending-tasks-implementation.md` —— **当前定稿的待做任务规格**（§0 约束表/§1–§13 各任务 现状/实现/验证/风险；权威）
4. `docs/pending-tasks-changelog.md` —— §14–§19 审核应答史（**仅供追溯**，含 8 轮意见与修复机制）
5. `docs/session-summary.md`（历史事实源；§20.17/§20.18 为最近两个 bug 的完整记录）
6. `docs/code-fact-registry.md`（代码事实唯一口径，改动须同步）
7. `docs/planbook/book-13-backlog.md`（S1–S14 目录与来历）、`book-18`（质量提示词/清晰度，已归档）

**铁律速查**（违反即返工）：
- 不改 ComfyUI systemd、**不重启 ComfyUI**（唯一允许的运行时动作=`POST /free`，body 必须完整 `{"unload_models":true,"unload_lowvram":true,"unload_cuda":true}`，空/缺字段会 4xx）；
- 共享服务器队列：**删除/取消必须归属校验**（`queue_probe.find_owned / cancel_owned_task` 双路径）；`dev.py queue` 只读；**一意图一驱动**，不碰他人任务；
- 共享模板 `workflows/remote_workflows/*`、`~/ai/ComfyUI/user/default/workflows/*` **只读**；绑定参考图必须用副本；
- 模型下载一律 **ModelScope（魔搭）**，不是 HuggingFace（HF 不可达；魔搭 302 可达、pip 1.39.1 已验证）；
- 机器配置 `config/llm.json` **gitignored**、不随同步覆盖；`base_url` 归 `deploy.py --set` 管理（**不得手改**；win 形态 `:8011`，spark-local `:8000`）；
- 中文/引号经 PowerShell→ssh 会乱码：**一律临时脚本文件 scp 到 spark 再执行**（附 §8 模板）；
- 删除操作默认 dry-run；不触碰 `uploads/`、`outputs/`、`workflows/h3_*/`、`logs/run_*.log` 运行期产物（自己验收产物除外）。

---

## 1. 服务与环境事实

| 服务 | spark 端点 | 形态 | 备注 |
|---|---|---|---|
| ComfyUI | `http://127.0.0.1:8188` | systemd，`Restart=on-failure` | **永不手动重启**；空闲内存回收仅 `POST /free`（完整 body） |
| SGLang Qwen3.8-27B | `http://127.0.0.1:8000/v1` | tmux `sglang`（sglang-venv torch 2.13+cu130） | ctx=8192；`chat_template_kwargs={"enable_thinking": False}` 是正确关思考位 |
| Gradio Agent | `http://127.0.0.1:7860` | tmux `agent`（qwen-agent-venv） | 自研 ui_app；**supervisor（tmux `supervisor`）自动拉起**，无需手动重启 |
| 文件依赖 | `~/qwen-agent-venv` | spark python 权威 | 系统 python3 缺依赖 |

- agent = qwen_agent 0.0.34；运行机制=self-managed `_one_run` 循环；`tools=` 格式触发 `<tool_call>`；
- 代码改动同步后 agent 无需重启（supervisor 兜底）；**仅 S6 类 UI/schema 改动后**需重启时：`ssh spark "tmux kill-session -t agent; tmux new-session -d -s agent 'cd /home/Developer/videoGenerate-Model-zju && /home/Developer/qwen-agent-venv/bin/python runs/agent/scheduler.py 2>&1 | tee ~/agent.log'"; sleep 18; grep -m1 AGENT_VERSION ~/agent.log`，再 `tests/e2e_smoke.py`（期望 SMOKE_OK）；
- spark 运行日志：仓库 `logs/run_*.log`（`dev.py logs view/check`）；agent 日志 `~/agent.log`；会话 `logs/agent_chats/*.jsonl`。

---

## 2. 工作流与验收纪律（不可跳过）

**开发工作流**（dev.py 固化，替代手敲 git/ssh）：
```
python runs/dev.py check      # 三端状态+漂移+一致性+文档索引（exit 0=一致）
python runs/dev.py sync       # 把本次改动定点同步 spark（不整仓、不覆盖机器配置）
python runs/dev.py commit -m "摘要" --files <改到的文件…>  # win commit+push GitHub+spark commit（事务化）
python runs/dev.py docs       # START-HERE §2 索引校验
python runs/dev.py test [--unit|--smoke]
python runs/dev.py queue      # 队列只读状态
python runs/dev.py logs view -N / check / clean [--yes]
```
- **提交顺序**：先 `sync` 再 `commit`（dev.py commit 本身不 sync）；
- **Windows 单测命令**：默认 python（msys）无 pytest → 用 `py -3.13 -m pytest runs/h3/tests -q`（**165 例全绿**为基线，含 `test_tts_hook_voice.py` 7 例）；
- **每次“已修正/已落地”声明后，必须 grep 目标文件对应行做机械核对**（8 轮审核多次抓出“commit 说改但没改”的教训——机制见 changelog §17/§18）；
- **真机验收定义**（用户口径）：真实提交链（或等价 Gradio API）→ 非空文本 → 真实产物（ffprobe 参数）→ 语音需可辨析（听测或 ASR 抽检）。仅单测通过 ≠ 完成。

---

## 3. 已完成（可作背景，不必重做）

| 批次 | 内容 | 落点 |
|---|---|---|
| book-13 | S1–S14 目录、sweet 区间、nap/supervisor 冲突登记 #16 | `docs/planbook/book-13-backlog.md` |
| book-14 | 参考视频 T8、LoRA 加速 T9、T2b 中文语音链 v2、上传分区 S14 | book-14 / `runs/h3/tts.py` |
| book-15 | supervisor / memory-planner / dev.py 服务 | `runs/agent/{supervisor,llm_mem}.py`、`runs/dev.py` |
| book-16 | 归档 + 验收纪律 §12 / §6.5 | book-16 |
| book-17 | 模型伪造工具调用纵深防御（白名单/schema 校验/修复重试/钩子/幂等/审计/人在回路） | `runs/agent/{tools,ui_app,scheduler}.py` |
| book-18 | Q+/Q- 质量提示词每轮注入+防漂移断言；语音/文字清晰度 | book-18 |
| 工作流存档 bug | `workflow_to_ui` 遇字符串节点 id（apply_lora 注入 `lora_14`）抛错→UI 静默缺失；已修+回填 13 目录（61==61）+2 单测 | `runs/h3/workflow.py` |
| **八审 TTS 钩子回归** | `_voice`/`_tj` 两处 UnboundLocalError（六审/七审引入）→ 钩子抽为 `_run_tts_hook()`（共用量前置初始化）+except 代码缺陷分类（`tts_code_error`+stdout `TTS_CODE_ERROR:`）+`VOICE_ALIASES` 提升 tts.py 公开常量+7 单测；真机验收：非 fast（h264+aac+srt）与 fast（_pp.mp4 h264+aac）双双通过 | `runs/h3_submit.py`、`runs/h3/tts.py` |

**当前产物（供抽检/听测）**：`outputs/video_16..video_31`（video_27/28/31=T2b 全链；video_25=中文招牌；video_31=合并单次编码 1216×704+字幕+语音）、`video_32`（八审真机任务）、`video_tts_a.mp4`（非 fast 声+字幕成品）、`video_tts_b_pp.mp4`（fast 合并链成品）。

---

## 4. 待做总览（权威规格见 `pending-tasks-implementation.md`）

| 任务 | 一句话 | 关键事实/陷阱 |
|---|---|---|
| **S2-P1a**（§2） | agent 默认 `--postprocess fast` + 合并单次编码链 | 钩子 fast 分支现已修复+测试（八审），P1a 绿灯；回滚开关 `--postprocess none` 已存在；tools.py 在 `--submit-only` 之后追加；dry_run 不带 |
| **S3**（§3） | 取消后任务表残留 → `mark_cancelled(cid,pid)` 是唯一权威（发『已取消』+停轮询）；CancelTask 成功仅调它，`clear_tasks` 会在下一轮 send 被覆盖 | `runs/agent/{task_watch,tools,queue_probe}.py`；单测 mock task_watch 状态 |
| **S8**（§8） | `h3_batch` 状态重写：`ComfyClient(retries=1, request_timeout=5)` + `queue_pids()` + 决策树 | “cancelled/从未排队”不可区分（如实标注）；勿改 queue_probe.collect 职责 |
| **S7**（§7） | 参考视频/音频原生支持（ref2va；**最大工程**，推荐排在 S8 后） | 十审定稿：本地 r2v 模板即 Ref2VA（ref_* 槽位已有、仅未接线）；**ref_videos 槽位类型=IMAGE**——LoadVideo（VIDEO）须经 GetVideoComponents 拆帧/拆声（images→ref_videos、audio→同号 ref_video_audios；utility-gan_upscaler.json 已实证同型链）；**主案=API 层注入**（循 apply_lora 先例 stage.py:180-220：转换后注 LoadVideo/GetVideoComponents/LoadAudio + 槽位键；免 uiapi 文件选择器分支与 UI 行合成；注入 id 用数字字符串）；**计数口径=模板 8/1/1 行、node 上限 9/3/3**（7a 目标 images count=8，勿写 9）；7a 登记后必须补全 slots/features（add_local 默认全空）；验证=两级判据（在线注入后 API dict 断言 + 真实提交）；**7c 双通道硬约束（tag 集合==列表索引集合，tools.py 校验报错）**；备选 A 成本=参数化已有函数（grow_slots/_wire_slot）+6 缺口，非从零构建；探测失败→如实归档不臆造 |
| S1（§1） | gallery caption/可用性 | 读时计算不持久 |
| S4（§4） | `idea2prompts --segments-json` 对齐 h3_batch `--prompts-file`；真 LLM 验证**在 spark 本机** | `config/llm.json` 别手改；deploy.py --set 管 base_url |
| S5（§5） | `svc_main.py` 增 `selfcheck-llm`：前置 `llm_mem.comfy_queue_idle()`、复用 `llm_mem.nap()`、恢复窗口 **≥300s**、与 restart-llm 互补、`selfcheck` 与 `selfcheck-llm` 一并对齐 `--yes` | 一次性改动三处（docstring/choices/分派）+ 注册 nap vs supervisor 冲突（book-13 #16） |
| S6（§6） | tools.py schema `tts_voice`（enum=**短名** xiaoxiao|yunxi，工具透传短名不映射——八审 Option A）、`tts_font_size`、SYSTEM 台词规则一句 | 归一已在 h3_submit 入口；判据=`start argv 含 --tts-voice yunxi` 且 `tts_done voice=zh-CN-YunxiNeural`（全名） |
| S9（§9） | dev.py `sessions list/export/search`（glob `*.jsonl`，复用 `session_cleanup.CHATS_DIR`） | 新增 CLI 子命令 |
| S10（§10） | `quality.py`（质量评估）+ `dev.py quality-report` | 用 `probe_av()`（单 ffprobe 不限流按 codec_type 分拣）；src 源 |
| S12（§12） | 一次性访问 token 设计（grant_tokens:[]、用后即焚、来源校验、UI 无需新控件） | 七审定稿；勿回归 CheckBoxGroup 旧设计 |
| S11（§11） | 空（无任务） | — |
| S13（§13） | 当前结论表（F5-TTS/音色扩展等远期） | 音色映射复用 `tts.VOICE_ALIASES` |

**P 链（远期管线，动工前先做 §15.5 前置验证）**：P2 ASR 客观验收（FunASR/Paraformer，魔搭）→ P3 Wav2Lip 口型（**先冒烟**）→ P4 参考图 Inpaint 修复（文字正确度）→ P5 F5-TTS/CodeFormer → P6 RIFE 插帧+伪 1080p（4x 下采样）。

**推荐实施顺序（评审建议）**：S2-P1a → S3 → S8（先修链上 3 件小改），然后 S1/S4/S5/S6/S9/S10/S12；P 链按前置验证逐项批准。

---

## 5. 关键技术事实与坑（改代码前必读）

| 项 | 事实 |
|---|---|
| ESRGAN | 两模型均 **4x**：608×352→2432×1408；测试帧 1216×704→**4864×2816**；单帧 ~11.8s；串行 124 帧≈24min；P1b 目标 3-6min=待验证非承诺；**单卡并发路数/显存上限未测** |
| ComfyUI schema | `UpscaleModelLoader` 输入键=`model_name`；`ImageUpscaleWithModel`=`upscale_model`；LoadImage 需 `input/` 根目录（user_uploads 子目录不被解析）；`/queue` item[1]=prompt_id；运行中取消=`POST /interrupt`（本 build `/queue {"interrupt":true}` 无效）；pending 取消=`/queue {"delete":[pid]}`；`/history/{pid}` 未知=运行中均返回 `{}`（须靠队列判别） |
| Ref2VA 链（十审定稿） | `LoadVideo`=io.Combo(file+video_upload 标记)→VIDEO；`LoadAudio`=io.Combo(audio+audio_upload)→AUDIO；`MiniMaxH3ReferenceToVideo` 四 AUTOGROW 槽：ref_images（**模板 8 行**/上限 9，IMAGE）/ref_videos（**模板 1 行**/上限 3，**IMAGE=24fps 帧序列**）/ref_video_audios（模板 1 行/上限 3，AUDIO 与同号视频配对）/ref_audios（模板 1 行/上限 3，AUDIO）；**LoadVideo/LoadAudio 的 UI widgets_values=[文件名,image] 双值**——uiapi 通用路径会抛 UiUnsupported（设计 B 主案下注入在 API 层、转换器遇不到，属已知边界）；拆帧链=LoadVideo→GetVideoComponents（VIDEO→images IMAGE+audio AUDIO+fps）；UI 行合成先例=grow_slots（refimage.py:497-526）；模板簿记 last_node_id=140/last_link_id=282/nodes=29/links=25 |
| 上传链（十二审定稿） | `/upload/image` 端点：字段名 name="image"（与类型无关，:52）/Content-Type: application/octet-stream（:53）/type=input（:42）/subfolder 非空才追加→默认落 input/ 根目录（:58）；**ComfyClient.upload_image 可直接复用于视频/音频**（唯一未验证项=服务端是否校验扩展名/MIME——S7 7a 复核清单已加 curl .mp4 验证）；提交链=本地源文件上传→API 返回名 bind，input/user_uploads 镜像仅服务 refimage 列举（LoadImage 不认子目录，六审实测；ui_app.py:825 注释已修正） |
| ffmpeg | volume dB 语义：`0.0`=-91dB 静音、`-12.0`=0dB 削波、`-12dB`=正确衰减；amix 需 `normalize=0`；`-shortest` 会截断（用 apad+`-t duration`）；音轨替换用 tmp+rename（原地写会 EIO） |
| argparse | `--rate -8%` 会被当旗标 → 必须 `--rate=-8%`；`--tts-voice` choices=[xiaoxiao,yunxi,两全名] |
| TTS | edge-tts 经 CLI 子进程调用（`_edge_tts_cmd` 三路探测 qwen-agent-venv）；**偶发 NoAudioReceived 网络抖动**（会以 `tts_error err=ValueError` 落日志，主产物不受影响——这不是代码缺陷，重试即好） |
| 钩子 | `_run_tts_hook` 返回解析后 tts_text（下方仅-fast 分支依赖它）；代码缺陷事件名=`tts_code_error`（行内关键字 `TTS_CODE_ERROR:`/`POSTPROCESS_CODE_ERROR:`） |
| 存档 | 任务目录=job.json+workflow_api.json+workflow_ui.json 三者俱全（字符串节点 id 已容错）；`save_workflow_ui` 失败会 logutil 留痕 |
| 断点 | 成功（无外层下载器）即清 root_state；`--submit-only` 会保留（收集靠无参重跑）；遗留断点=`--force-new` 或删 last_job.json（**确认归属后**） |

**文件写入防坑**：改长文档优先小步 `edit` 工具；PowerShell `[IO.File]::ReadAllText/WriteAllText` **整写曾把 100+ 行文档写坏成 0 行**（教训 changelog §18）——禁止用于 >100 行文件；连续 edit/紧贴 py_compile 会遇 EIO(1175)，等 ~2.5s 重试；run_code 大字符串转义失败时用行数组 join 或 temp 文件+正则替换。

**ssh 直跑中文/引号模板**（避免转义地狱，直接抄）：
```bash
# 本地写脚本 → scp → 远端执行
#!/bin/bash
set -o pipefail
cd /home/Developer/videoGenerate-Model-zju || exit 2
/home/Developer/qwen-agent-venv/bin/python runs/h3_submit.py --stage t2v --resolution 360p --seconds 5 --force-new \
  --prompt 'A single red kite flying over a green hill ...' \
  --tts-text '风筝真美。' --tts-voice yunxi 2>&1 | tail -45
# 执行：scp -q tmp.sh spark:run.sh && ssh spark 'bash ~/run.sh'
```

---

## 6. 未决/待拍板（动工前向用户确认）

1. **nap() vs supervisor 冲突**（book-13 #16）：`llm_mem.nap()` 停机意图被 supervisor ≤30s 拉回——对 §5 自愈利、对内存编排可能失效；二选一（supervisor 识别 NAPKILL_FINISHED 跳过唤醒 vs 保留“nap 必被拉起”）；
2. ESRGAN 批处理并行的单卡并发路数与显存上限（§15.5 项）；
3. requirements/lock 文件口径（仓库无任何 pin；S13/P2-P6 会引入 modelscope/FunASR/Wav2Lip/F5-TTS 多套依赖，需独立 venv）；
4. Ref2VA 探测**已定案（十审实测，§7 十审定稿）**：槽位计数=模板 8/1/1 行、node 上限 9/3/3；接线设计=**API 层注入**（apply_lora 同型，免 uiapi 分支与 UI 行合成，实施期仅复核模板版本+节点存在）；
5. 魔搭模型真实 ID 清单（RIFE/SD-Inpaint/Wav2Lip+S3FD/FunASR/Paraformer/F5-TTS）+ 下载时长与大小登记（§15.5）。

---

## 7. 本次交接后的下一步

1. `python runs/dev.py check` 确认三端 OK（当前 HEAD：win `3f42488` / spark `d10b6be`）；
2. **动 S2-P1a**（tools.py 追加 `--postprocess fast` + 真机验证合并链产物=1216×704/字体/音轨/字幕）→ 回归 S3 → S8（各自单测+真机）；
3. 每项完成即：单测全绿 → 真实提交链验收 → 更新 `pending-tasks-implementation.md` 对应节（把“待做”改“已实施/已回滚”）→ dev.py sync+commit（--files 列全）→ dev.py check 一致；
4. 全程遵守 §2 验收纪律与“已修正必 grep 核对”机制；每轮改动后更新 changelog（新 §20）与 session-summary（新 §b）。

---

## 8. 备忘（意外时查这里）

- `docs/session-summary.md`：历史事实源（§14 文件夹速查、§20 逐批记录）；
- `docs/reference-2026-09-04.md`：配置注册表/引擎契约/故障字典；
- `docs/planbook/book-00-overview.md`：全局计划书与验收门禁；
- `runs/h3/tests/`：165 例单测（当前基线）；`tests/`：e2e 冒烟等工具脚本；
- 每个服务都由 supervisor/系统托管——**永远不要 kill ComfyUI 或手动重启**；必要时只 `POST /free`（完整 body）。
