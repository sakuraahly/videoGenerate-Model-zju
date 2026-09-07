# CURRENT-STATE — 项目当前状态事实源（单一权威）

> 定位：**当前事实**的唯一权威（2026-09-07 起）。历史/审计/轮次记录一律不在此维护——
> 各历史文档只读；当日交接见 `docs/handoff/handoff-2026-09-07-live.md`（跨日后新建当日 handoff）。
> 本文档每轮工作结束必须核对刷新（与 handoff 同日更新，冲突以本文档为准并登记）。

## 1. 双端与主库

| 端 | 位置 | 角色 |
|---|---|---|
| Windows 主库 | `D:\MY_CODING_PROGRAM\videoGenerate-Model-zju` | git 主库，**唯一推 GitHub**（sakuraahly/videoGenerate-Model-zju）；一切开发/文档源 |
| spark 运行时 | `ssh spark` → `~/videoGenerate-Model-zju` | 引擎/agent/ComfyUI 运行端；经 `runs/sync_to_spark.py` 增量同步（不含 .git/机器配置/产物） |

## 2. spark 服务形态（tmux 体系，2026-09-07 起）

| 服务 | 会话/端口 | 说明 |
|---|---|---|
| ComfyUI | tmux `comfy` / 8188 | systemd 单位已停用（root 侧可恢复）；重启=授权项（可用 `dev.py services restart-llm` 类工具先查队列） |
| agent（Qwen 调度器） | tmux `agent` / 7860 | venv `~/qwen-agent-venv`；重启=`python3 runs/agent/svc_main.py restart-agent`（版本见日志 `AGENT_VERSION`） |
| SGLang（Qwen3.8-27B） | tmux `sglang` / 8000 | guard 自动管理；与 ComfyUI 共存 mem 0.50、**ctx=16384**（2026-09-07 用户指示放松） |
| Open WebUI | / 3000 | 纯聊天（无工具） |

## 3. 模型（统一在 ComfyUI models，用户指示）

`~/ai/ComfyUI/models/`：`f5-tts/{F5TTS_v1_Base,vocos}`（人声 TTS）；`asr/sensevoice`（ASR ONNX）；
`upscale_models/{4x-UltraSharp.pth,RealESRGAN_x4plus.pth,RealESRGAN_x4plus.safetensors}`（超分）；
`diffusers/stable-diffusion-inpainting`（Inpaint）；`checkpoints/sd-v1-5-inpainting.ckpt`；
`frame_interpolation/`（空——RIFE 权重渠道阻塞登记）。
H3 主模型（fl2va/ref2va int8 + qwen3vl text encoder + 双 VAE）在 `diffusion_models/text_encoders/vae`（ComfyUI 标准目录）。
其他：`~/ai/tts-venv`（F5-TTS）、`~/ai/asr-venv`（SenseVoice）、`~/ai/cosy-venv`+ `~/ai/CosyVoice2-0.5B`+ `~/ai/cosyvoice-src`（CosyVoice2 试点）。

## 4. 生成（H3 本地推理）

- 入口：`python runs/h3_submit.py --stage {t2v,i2v,r2v,flf2v}`；参数：--prompt/--image(可多)/--videos/--audios/--resolution/--seconds/--lora/--seed/--timeout。
- 分辨率：360p=608×352 · 480p=864×480 · 540p=960×544 · **720p=1280×736 · 768p=1344×768**；时长上限 15s（>60s 仅警告）；帧数=17k+5 网格。
- LoRA 加速：`fl2v_4step`（t2v/i2v/flf2v）、`ref2v_4step`（r2v·360p 档）、`ref2v_8step`（r2v·768p 档）；`none`=20 步全质。
- **S7 参考媒体**（已实施）：--videos/--audios 各 ≤3（r2v；注入 LoadVideo→GetVideoComponents→ref_videos/ref_video_audios、LoadAudio→ref_audios）；提示词**必须**含 `<Picture N>`（从 1 起、与 --image 顺序一致）及 `<Video N>`/`<Audio N>` tag 契约。

## 5. 成品链（语音/字幕/混音/验收/超分——标准工作流）

- 一键：`--tts-text "<台词>" --tts-backend cosy --finalize --asr-check`（**默认=CosyVoice2 自然音色**（2026-09-07 定案接入；GPU 优先、OOM 自动转 CPU）；F5-TTS=`local` 备选；edge 需显式降级）。
- 音色（assets/tts_refs/{voice}.wav+.txt）：`xiaoxiao`=官方女声(默认)；`yunxi`=真人男声；`aria`=**英文女声——定案=官方 cross-lingual 样本（本地模型克隆合成、自然接近真人；2026-09-07 用户选定）；LJSpeech 真人英文样本=备选归档（换文件即切换）**。
- 补充：`--tts-mix-bed <音频>`（-12dB 底轨）；`--postprocess fast`（2x+降噪+锐化）；`--upscale 4x`（RealESRGAN 4x-UltraSharp，608→2432，耗时长）。
- 音效链：`runs/h3/sfx_mix.py --video <v> --music <底轨> --music-db -12 --events "开始秒:文件:dB,..." --out <成品>`（原音轨+底轨+分段事件三路混音；loudnorm -14）。
- 验收：`runs/h3/asr_check.py <媒体> --compare "<原文>"` → `ASR_SCORE ≥ 0.6 = ok`（SenseVoice 回环）。
- ComfyUI 路径：`workflows/remote_workflows/h3_finalize_chain.json`（H3LocalTTS/H3Finalize/H3AsrCheck；分类 h3；模型/venv 见节点 README；ComfyUI 重启后生效——服务重启为授权项）。
- 详细讲解：`docs/guides/tts-pipeline-explain.md`（原理/复现）。

## 6. 音色与 TTS 后端现状（2026-09-07）

- F5-TTS v1+vocos：CPU ≈50-80s/句，24kHz；用户判定"电音/AI 感"为 vocoder 级限制（根因，非样本）。
- **CosyVoice2-0.5B 已接入生产（2026-09-07 定案）**：`--tts-backend cosy`=默认（自动 GPU→CPU 回落）；真机冒烟=tts 分发链路实测通过（ASR 还原；听测样 `outputs/voice_demo_cosy_zh_final.mp3`）。

## 7. 通道事实（2026-09-07 实测，勿再踩）

| 通道 | spark | Windows 主库 |
|---|---|---|
| github.com:443（git clone/push） | ✗ 不通 | ✓（git push 正常） |
| raw.githubusercontent.com / codeload.github.com / api.github.com | ✓ raw+codeload（git 不行） | ✓ |
| modelscope.cn（模型下载/文件 API） | ✓ | ✓ |
| hf-mirror.com | ✗ 超时 | ✓（API/tree/resolve 均可用） |
| 其他 | openslr 极慢（3MB/min 实测） | 未测 |

下载策略：spark 侧优先 modelscope；GitHub 库源码用 codeload/raw zip；HF 文件用 Windows 侧 hf-mirror 再 scp。

## 8. 硬纪律（红线）

1. **Z:/ 网络盘路径禁用**（SSHFS 映射 spark 主目录，仅本机调试）；路径一律 `~/…` 或 Windows 主库。
2. **队列纪律**：单实例锁；不取消/不打断他人任务；不擅自 `--force-new`；生成提交=排队 FIFO（`POST /prompt` 即排队）；重启 ComfyUI/服务=授权项。
3. **spark 同事模板只读**（`~/ai/ComfyUI/user/default/workflows/`）；只动 `workflows/remote_workflows/`；`api_*` 云模板不提不调。
4. **Agent**：无 shell/任意文件/服务管理；能力=白名单工具（run_script/modify_workflow/call_comfyui/read_doc 等）；SYSTEM_MESSAGE 2608t 预算，扩展走 `docs/agent-reading/`。
5. 改动闭环：`skil‌ls/dev-workflow.md`（改→测→证据→文档→双端→提交）。
6. 产物命名：生成=任务目录 `workflows/h3_<ts>_<ms>/`；交付=Windows `outputs/video_<N>[_描述].mp4`；听测样=`outputs/voice_demo_*.mp3`（产出后 scp 回 Windows）。
7. **夜间策略（2026-09-07 用户指示）**：≥1080p/高清重活（1080p 探测、口型冒烟、4x 超分叠加等）一律夜间机器空闲执行；白天仅 ≤768p 档。

## 9. 当前待办（快照；详见当日 handoff + planbook 状态表）

**白天可干**：①用户听测确认（cosy 中文女声/aria 英文音色）；②镜头片 f8217f22 交付取回（对话"继续"）；
③"一句话出片"回归（≤768p 全链）；④~~一体模板桥接节点~~✅（VIDEO→路径桥接+模板接线, ComfyUI 已重启激活）；⑤S12 真机演练（需用户配合一轮对话）；
**夜间自动**：⑥1080p 探测（night_runner --auto + cron 已装）；對話类：⑦口型冒烟 ⑧RIFE ⑨4x 叠加（agent 对话认领）。
**§22 定稿任务序（用户批评 2026-09-07）**：T1 音色库（语言×性别×版本 manifest + 新增英男样本 + 三处显式选择器/词表）→ T2 字幕自适应不突兀档（默认 adaptive/classic 保留）→ T3 ComfyUI 一体模板 GUI 终验（展示=成片）→ T4 文档同步。

## 10. 夜间自动化机制（2026-09-07 用户需求：不用手动喊话）

- **队列**：`config/night-tasks.json`（定义，入库）+ `config/night-tasks.state.json`（状态，gitignore）；
  工具 `runs/agent/night_runner.py`（--list/--status/--add/--done/--auto/--now）。
- **引擎类**（engine）：cron（spark：`0 22-23,0-6 * * *` 每小时）自动触发 `--auto`——
  仅「夜间窗口(北京 22-08)+ComfyUI 队列空闲」执行；先测项=原生 1080p 探测（1920×1088/无 LoRA/5s）。
- **对话类**（agent）：Wav2Lip 口型冒烟/RIFE 插帧/4x 超分叠加——需 agent 协同；
  用法=用户说“开始夜间任务”→agent `night_runner.py --list` 查看→提出计划→逐项执行→`--done`。
- **Agent 已内建**：SYSTEM 工具清单+待做/夜间清单规则（agenda 类命令）。
3. ComfyUI 一体模板（生成+Finalize 合并）打磨（可选）。
4. S13 远期：音色库（CosyVoice2 全链）/口型（Wav2Lip·GitHub 官方权重）/原生 1080p 探测（1920×1088+无 LoRA）。
