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
其他：`~/ai/tts-venv`（F5-TTS；主引擎 venv：torch 2.14.0+cu130 + torchvision 0.29+cu130 + torchaudio 2.11+cu130 + cv2 5.0 + numpy 1.26.4 + scipy 1.13.1 + librosa 0.10.2 + onnxruntime + diffusers 0.24.0 + transformers 4.38.2 + huggingface-hub 0.25.1 + facenet_pytorch 2.5.0（MTCNN 权重 wheel 内置；**2.6.0 在 numpy1.26 下返回 object dtype 致 EchoMimic np.round 崩，2026-09-09 降回 2.5.0**）+ moviepy 1.0.3（2.x 无 moviepy.editor；EchoMimic requirements 对齐）+ av/einops/omegaconf/torchmetrics/modelscope——2026-09-08 为 EchoMimic 增装；**pip 一律显式清华源，禁默认源**）、`~/ai/asr-venv`（SenseVoice）、`~/ai/cosy-venv`+ `~/ai/CosyVoice2-0.5B`+ `~/ai/cosyvoice-src`（CosyVoice2 试点）、`~/ai/echomimic`（antgroup/echomimic 代码 + pretrained_weights 12.3GB（ModelScope BadToBest/EchoMimic 子集：denoising_unet_acc/reference_unet/motion_module_acc/face_locator/whisper_tiny/sd-vae-ft-mse/sd-image-variations-diffusers-unet）——§15e 无框路线资产，冒烟=夜间任务 nt-echomimic-smoke）。

## 4. 生成（H3 本地推理）

- 入口：`python runs/h3_submit.py --stage {t2v,i2v,r2v,flf2v}`；参数：--prompt/--image(可多)/--videos/--audios/--resolution/--seconds/--lora/--seed/--timeout。
- 分辨率：360p=608×352 · 480p=864×480 · 540p=960×544 · **720p=1280×736 · 768p=1344×768**；时长上限 15s（>60s 仅警告）；帧数=17k+5 网格。
- LoRA 加速：`fl2v_4step`（t2v/i2v/flf2v）、`ref2v_4step`（r2v·360p 档）、`ref2v_8step`（r2v·768p 档）；`none`=20 步全质。
- **S7 参考媒体**（已实施）：--videos/--audios 各 ≤3（r2v；注入 LoadVideo→GetVideoComponents→ref_videos/ref_video_audios、LoadAudio→ref_audios）；提示词**必须**含 `<Picture N>`（从 1 起、与 --image 顺序一致）及 `<Video N>`/`<Audio N>` tag 契约。

## 5. 成品链（语音/字幕/混音/验收/超分——标准工作流）

- 一键：`--tts-text "<台词>" --tts-backend cosy --finalize --asr-check`（**默认=CosyVoice2 自然音色**（2026-09-07 定案接入；GPU 优先、OOM 自动转 CPU）；F5-TTS=`local` 备选；edge 需显式降级）。
- 音色（assets/tts_refs/{voice}.wav+.txt + **assets/tts_voices/manifest.json**=音色库：id/显示名/语言/性别/sample/ref/note——2026-09-07 §22 T1）：**xiaoxiao=中文女**（官方,默认）；**yunxi=中文男**（真人）；**aria=英文女**（官方 cross-lingual）；**daler=英文男**（LibriSpeech 1272 真人,f0 中位 113.7Hz,2026-09-07 新增+样本已录）；lao=中文老年男（**样本弃用**：克隆后 ASR 回环乱语）；yue_zh=中文女Ⅱ（待定样本）。显式选择三处同步：ComfyUI voice 下拉 / `--tts-voice` / agent 词表（语言×性别×版本）。
- 补充：`--tts-mix-bed <音频>`（-12dB 底轨）；`--postprocess fast`（2x+降噪+锐化）；`--upscale 4x`（RealESRGAN 4x-UltraSharp，608→2432，耗时长）。
- 音效链：`runs/h3/sfx_mix.py --video <v> --music <底轨> --music-db -12 --events "开始秒:文件:dB,..." --out <成品>`（原音轨+底轨+分段事件三路混音；loudnorm -14）。
- 验收：`runs/h3/asr_check.py <媒体> --compare "<原文>"` → `ASR_SCORE ≥ 0.6 = ok`（SenseVoice 回环）。
- ComfyUI 路径：`workflows/remote_workflows/h3_finalize_chain.json` + **`video_minimax_h3_r2v_finalize.json`（一体化：生成→SaveVideo→H3Finalize(VIDEO 桥接)→H3AsrCheck）**（H3LocalTTS/H3Finalize/H3AsrCheck；分类 h3；模型/venv/路径见节点头部注释；ComfyUI 重启后生效——服务重启为授权项）。
- **H3Finalize 节点（2026-09-07 §22 终验版）**：可选 video_in(VIDEO)=接 SaveVideo 输出；subtitle_style(harmony 默认/kai/song/black/minimal/classic)+subtitle_font+subtitle_color；**backend(cosy 默认/local/edge)**；子进程 TTS 强制 CUDA_VISIBLE_DEVICES=""（防与 ComfyUI GPU 争抢挂起）；**成品自动落 ComfyUI 输出区 output/video（预览画廊即成片，含 .srt 同步复制）**。
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

**2026-09-10 空间外置大脑接通（实测）**：①空间变量（明文）`LLM_BASE_URL=https://api-inference.modelscope.cn/v1`、`LLM_MODEL=Qwen/Qwen3.5-35B-A3B`、`LLM_EXTRA_JSON={"chat_template_kwargs":{"enable_thinking":false}}`；密钥 `LLM_API_KEY`=用户魔搭 SDK token（存 Space secrets，列表只回 key）；②模型选型实测（`GET /v1/models` 共 46 个、**全是 LLM/图像编辑，无视频模型**）：Qwen3.5-35B-A3B 4/4 最快、Qwen3.5-27B 4/4 但说话轮 10.3s、Step-3.7-Flash 2/4、GLM-4.7-Flash 1/4（113s 卡顿）→ 定 Qwen3.5-35B-A3B；关思考后说话轮 3.3s→1.4s；③实测暴露两真问题并已修（v2.4.2）：模型自创键名（dialogue/character/style）→ `normalize_args` 别名归一化+丢未知键；偶发空响应 → `plan` 重试 3 次再降级；工具越权/关键参数缺失 → 规则规划器修复并在轨迹标 `repaired`；新增 `LLM_EXTRA_JSON` 外置扩展开关；④**公开空间端到端验证**（`https://wumingyong0-automated-video-generation.ms.show/gradio_api/call/_step`）：3.1s 返回，`mode=agent-api`、大脑选 `generate_talk`、台词原样、演示模式请求体预览正确；⑤**待办：视频生成接口 `ENGINE_*` 未接**（平台无视频模型 → 需第三方 key 或我们自己的 H3 网关，且需一层协议适配）。

**2026-09-10 创空间 Agent 解耦交付（当日事实）**：①新定案——**交付件就是 Agent 本身 = 工具集 + 外置大脑，不依赖任何本机**：空间只放 Agent（决策+前端），模型能力全部走接口（符合课程「空间只放 agent、模型走外部 API」要求）；②`studio/agent_client.py` 重写：**工具集** 4 件（`generate_video`/`generate_talk`/`make_story_film`/`answer`，全部 HTTP、空间内零本机依赖）+ **外置大脑**（`LLM_BASE_URL/KEY/MODEL`，system 提示可用 `AGENT_SYSTEM_PROMPT`/`AGENT_SYSTEM_PROMPT_FILE` 外置注入，换行业只改提示不改码）+ `TOOLSET` 白名单（大脑越权选工具会被拒）+ 统一引擎变量 `ENGINE_BASE_URL/ENGINE_API_KEY/ENGINE_STATUS_URL`（旧名 `VIDEO_API_*` 兼容）；③**本机功能在空间内等价实现**：参考图上传即时预览并转 `image_b64` 注入工具参数、演示模式打印「即将发出的请求体」、**任务面板**（时间/任务号/工具/状态/成片 + 一键刷新）、成片自动取回 `studio/outputs/`（保留 12 个）后内嵌播放+原链接下载（外部 CDN 域名会被 Gradio 前端校验拦掉，故先落盘再预览）；④**真机验证**（Windows 本地 Gradio 6.26 + 新增 `tests/mock_engine.py` 假引擎/假大脑）：demo 模式 → 请求体预览 ✅；ENGINE 路径 → `POST` 带 `Bearer` → `job_id` → 轮询 `done` → 取回 210143B 成片 → 页面可播 ✅；LLM 路径 → 自定义 system 提示 + 工具 schema 送达假大脑 → 按其返回的 `{tool,args}` 执行 `generate_talk` ✅；⑤测试 **210 passed / 1 skipped**（新增 `tests/test_studio_agent_client.py` 21 例；顺手修 `test_session_filter_unit.py` 的 `sys.exit` 打断整会话问题）；⑥空间版本 → **v2.4.1 已发布并 Running**（Space 仓库 `wumingyong0/Automated_video_generation`：v2.4=8b64f84、v2.4.1=00a910f；两次 deploy 均 Building→Deploying→Running，运行日志无异常、MCP 警告已消除；GitHub 主库同步 7f936b0/d64308b；**部署文件与本地验证过的文件逐字节一致**（SHA256 比对 OK）；私有空间外网直连 403，页面级确认需用户点开）；接口契约文档 `studio/接口说明.md`、创作手记 `studio/创作手记.md` 同步改写（含「本机功能→空间等价实现」对照表）；⑦**本空间无任何 spark/本机适配代码**（不读本机路径、不调本机脚本、不依赖内网地址）。

**2026-09-09 凌晨-白天闭环（当日事实；详见 handoff 当日 + planbook §15e⑦）**：①**定时 agent 注入验证通过**：sched-agent-test 每 3 分钟连 3 轮——注入(保留会话历史)→agent 收到(SYSTEM 服从条款)→run_script 执行→110s 审计「有工具调用」✅（实测 05:54 注入→末次 05:57 前完成）；测试任务 sched-demo-minutely/sched-agent-test 已下线，保留 sched-watchdog/sched-night-check/sched-daily-report（**daily-report 今晚 20:00 首次真机**）；②**nt-echomimic-smoke 全链 PASS**（人像模式 512²/6 步/1.5s 带音轨；父亲.png 参考图；入参 bug/np.round object dtype→facenet 2.5.0/moviepy 1.0.3/em_out 相对路径 4 连修）；③nt-ref-video-test 修复版重跑（720p r2v 2图+<Video 1>，tag 契约已过；进行中）；④nt-hd-4x-ultimate / nt-hd-4x-r2v-refs 昨夜 PASS（EXIT=0，video_461 4x 收尾）；⑤猫 demo v2（老屋木门 3 段 13.46s/864×480 已拼）待交付；⑥tts-venv 依赖表更新（facenet_pytorch 2.5.0/moviepy 1.0.3；EchoMimic requirements 对齐；教训=新装后必验 CUDA/f5_tts/检测链）。

**2026-09-08 全天闭环（晚间集中登记，事实=handoff 当日 §五-§十一）**：①**§15d 结果区+会话产物协议**（runs/h3/session_outputs.py：VIDEOGEN_SESSION_CID→logs/agent_chats/<cid>/outputs/，保留10；run_script env 注入；h3_submit _session_place（LOCAL_OUTPUT/POSTPROCESS/TTS/MIX 均 SESSION_OUT）；UI gr.Video+gr.File 结果区+send 包装逐 yield 刷新；**提交真实性硬校验+工具输出真 id 优先登记**+素材池提示注入；②ASR 双轨（asr_check --start/--dur；LINE_*/NARRATION_* 分窗验真）；③S12 --scope-all 收窄（authorized_all_text：未授权即拒，原=警告放行）；④EchoMimic 无框路线装弹+排障（tts-venv torch 2.14+cu130 恢复/依赖 pin 教训 §15e⑥；12.3GB 权重 ModelScope 直拉；echomimic_talk.py 集成脚本；冒烟任务已修重跑中）；⑤夜间队列：nt-hd-4x-ultimate（t2v 版 video_461 1920×1088 已出，4x 收尾）+ **nt-hd-4x-r2v-refs（参考图版终极档：r2v@1080p 已 dry-run 验证模板支持+契约校验）** + nt-echomimic-smoke(修复版)；⑥**M1 创空间静态展示版发布+验收通过**（studio/ 全套→wumingyong0/Automated_video_generation，远端 bda7c3b；用户确认运行中/片墙/表单；入口=空间页内嵌）；⑦交付 video_80（720p 直出）/video_81（r2v 参考图连贯）；⑧1080p 直出片复盘（planbook §15g：全链已通，spark-local 编号独立口径）。

**白天可干**：①用户听测确认（cosy 中文女声/aria 英文音色）；②镜头片 f8217f22 交付取回（对话"继续"）；
③"一句话出片"回归（≤768p 全链）；④~~一体模板桥接节点~~✅（VIDEO→路径桥接+模板接线, ComfyUI 已重启激活）；⑤S12 真机演练（需用户配合一轮对话）；
**ComfyUI 兼容升级（2026-09-08 凌晨，planbook §15c）**：核心 RIFE 打通（flownet.pkl→models/frame_interpolation/flownet.pth，FrameInterpolationModelLoader+FrameInterpolate 可用）；一体模板升级=新 GUI 模板 video_minimax_h3_r2v_rife_finalize.json（生成→插帧 2x(48fps)→H3Finalize(cosy+kai)→ASR 全链 5b308ac9 PASS：outputs/video_65_rife_final_48fps_chain.mp4，864×480@48fps/5.15s，ASR 0.889）；语义坑=插帧后 CreateVideo fps 必须×2（否则慢动作）；S12 真机演练=机械预演全绿，待用户会话轮。
**v3 无缝克隆版（2026-09-08）**：v2 羽化版未根治框痕（用户复验）→ 改用 cv2.seamlessClone（Poisson 融合）：GFPGAN 修复结果+人脸盒 mask → NORMAL_CLONE 贴回（光照/颜色连续、无框界）；85 帧重跑+RIFE→outputs/w2l_lipsync_final_v3_48fps.mp4（video_66，1728×960@48fps/3.52s）；双帧抽检（1.8/2.9s）框痕零可见。
**voice 匹配修正（2026-09-08）**：video_65（男像+女声）为演示参数不匹配（模板默认 ref 图=男主人公 + 默认女声）→ 重跑 voice=yunxi → outputs/video_67_rife_48fps_yunxi.mp4（864×480@48fps/5.15s，ASR 0.917）。规范（已记入待办）：**正式出片音色必须与角色性别/语言匹配——ComfyUI voice 下拉/引擎 --tts-voice/agent 词表三处显式选择**。
**框痕 v5 + S12 全局错误修复（2026-09-08 三轮）**：①v5=自适应边距（边距=bbox 高的 0.35/0.35/0.35/0.55（下），随人脸尺寸逐帧动态）+ 全区宽羽化泊松——video_69（1728×960/48fps/3.52s）多帧抽检无框痕；②S12 全局错误定位修复：_pool_update 使用模块级不存在的 gr（gradio 在 send 内局部导入）→ 改为局部 import gradio as _gr；③回答用户关切：处理区本就逐帧跟随检测框（动态），v5 起边距亦随人脸尺寸自适应（非固定矩形）。**GFPGAN 节点化全链终验（2026-09-08，planbook §15b#5 完成）**：0397f564 COMPLETE——生成→SaveVideo→GetVideoComponents→FrameInterpolate(2x/48fps)→**H3FaceRestore**（215 帧修复）→H3Finalize(yunxi/cosy/kai)→H3AsrCheck 全链在 ComfyUI 队列内 success；产物 outputs/w2l_restore_rife_chain_comfy.mp4（video_71：864×480@48fps/5.146s+楷体+srt，ASR 0.917 ok）；GUI 模板 video_minimax_h3_r2v_restore_finalize.json（36 节点）；节点=face_restore_video.py（tts-venv 子进程 CPU；自适应边距+泊松无框痕）；两连小坑登记（onnx ~ 未展开 / 147 video_in 误接空串——均脚本接线问题，已修）；重启门禁已装（restart_comfy2.sh 非空队列即 ABORT）。**新目标（2026-09-08 用户定案）：魔搭创空间打包上传**——调研完成（git+token 发布/免费 CPU 2vCPU16G/PAI 付费 GPU/休眠策略）；设计=创空间(展示+交互入口)→spark(引擎层公网 API)；M1 静态展示版→M2 远程调度→M3 单点模型；详见 docs/guides/studio-porting.md + skills/studio-packaging.md + 计划书 §15f（未动工，等确认）。**7860 页面结果区 + ASR 双指标（§15d，2026-09-08 夜间落地，代码已入库；spark 侧待 agent 重启生效）**：协议模块 `runs/h3/session_outputs.py`（env `VIDEOGEN_SESSION_CID`→`logs/agent_chats/<cid>/outputs/`，KEEP=10 修剪；单测 6 绿）；run_script 对子进程注入该 env；链终版产物落会话目录（`lipsync_<YYYYmmdd_HHMMSS>_<台词前4字>.mp4`，脱敏打印 SESSION_OUT）；7860 UI=结果区 `gr.Video`（预览最新）+ `gr.File`（全部下载），send 包装逐 yield 刷新、加载历史会话同步刷新、空态「暂无结果」；`--asr-check` 改双轨——台词窗 [0, line_dur] 报 LINE_SCORE + 旁白窗报 NARRATION_SCORE（非重叠不混判；asr_check.py 增 `--start/--dur`）。证据：单测 337 passed/1 skipped + consistency 0 问题。**夜间自动（2026-09-07 首轮执行记录）**：⑥1080p 原生探测 ✅PASS（1920×1088/无LoRA/20步/5s→`MiniMax_H3_00174_.mp4`（h264+aac,5.167s,124帧）→ outputs/video_53.mp4；night_runner 自动验证+标记完成）⑦口型冒烟 ✅（Wav2Lip：权重 HF camenduru（wav2lip_gan 436MB+s3fd 90MB）经 Windows hf-mirror 下载再 scp；代码 codeload；依赖=tts-venv torch2.14+cv2+librosa（清华 pip 源）；首测产出 `outputs/w2l_smoke_talk.mp4`（864x480 h264+aac，输入=00171 人脸+cosy 台词 6.04s；前后帧嘴型差异确认）；排障：librosa1.0 mel 签名、opencv5(arm64)无 FFMPEG 写后端→PNG 序列+mux；证据 w2l_before/after_2s.png）**口型质量追击（用户反馈不自然→根因+修补 ✅）**：根因=①mel 块步长 16=5fps 幻灯片 ②音轨 6.04s>视频 5.17s→尾部 0.9s 冻结帧 ③96px 口型纹理上限；修复=帧对齐 mel 窗口（每输出帧取 t 时刻 16 宽窗口，模型输入保持 [80,16]）+短台词 3.56s 对齐+4x-UltraSharp 整帧增强（压回 1728×960）+RIFE 2x→**outputs/w2l_lipsync_hd48.mp4（1728×960/48fps/3.52s h264+aac）**；三帧抽检（0.6/1.8/3.0s）嘴型随台词逐帧变化；遗留=口型纹理 96px 上限→**已破（GFPGAN ONNX 路线 ✅2026-09-08 凌晨）**：Neus/GFPGANv1.4.onnx(340MB, hf-mirror)→onnxruntime(tts-venv, 清华源)+sfd 逐帧人脸盒→512 修复回贴，85 帧 83s 实测；修复后人脸/眼/牙/唇线锐利（对比帧存档）；最终链=Wav2Lip(帧对齐)→4x 增强→GFPGAN→RIFE 2x→**outputs/w2l_lipsync_final_48fps.mp4（1728×960/48fps/3.52s h264+aac）**；更优换模型（MuseTalk/VideoReTalking）仍远期⑧RIFE ✅打通（2026-09-07 深夜续：用户指正=镜像站有货——**HF `gpanaretou/practical-rife-interpolation` 的 train_log 包（flownet.pkl 24.6MB+IFNet_HDv3/RIFE_HDv3/refine.py）就是官方模型格式（README 第 45 行原文：*.py+flownet.pkl 放 train_log/）**→ 经 Windows hf-mirror 下载转 spck；用 Practical-RIFE 自身引擎（codeload 代码+tts-venv）+ 三个适配补丁（PracticalRIFE 包 shim/EPE+SOBEL loss stub、skvideo np.float→float）→ 实测 `w2l_lipsync_hd48.mp4`（1728×960/48fps 2x 插帧/3.52s/音轨 aac）——插帧能力正式可用；**2026-09-08 补验：1080p 原生片（00174_）2x 插帧→`outputs/rife_1080p_48fps_sample.mp4`（1920×1088/48fps/5.15s/aac）——1080p 插帧也过**；注：走自家引擎（项目侧运行），ComfyUI 核心节点兼容仍远期（pkl 格式）⑨4x 叠加 ✅PASS（00170_ 1216×672 12.25s → RealESRGAN 4x-UltraSharp → outputs/upscale4x_00170.mp4 4864×2688/12.46s h264+aac；排障：首跑整体提交致 ComfyUI 内存压力崩溃→重启+分 3 段×4s 逐段超分再 concat，稳定完成）。**夜间收尾**：night_runner 4/4 已结算（probe/wav2lip/upscale=done PASS；rife=done→逆转：用户指正镜像站有货→已打通（见⑧）；Windows outputs 已同步 video_58_1080p_probe/video_59_w2l_smoke/upscale4x_00170 + w2l 前后帧证据图。
**§22 定稿任务序（用户批评 2026-09-07）——全部完成 ✅（2026-09-07）**：T1 音色库（manifest+英男 daler 样本+三处显式选择器/词表）✅ → T2 字幕自适应档（harmony 默认+kai/song/black/classic；_subtitle_style+三下拉+引擎参数+13 测试绿）✅ → T3 ComfyUI 一体 GUI 终验（21e3e652：生成→SaveVideo→H3Finalize(cosy+kai)→H3AsrCheck 全链 success；成片在 output/video h3_bridge_2373727_final.mp4（864×480+配音+字幕烧录）；ASR 回环 0.889 ok；字幕截图确认无突兀）✅ → T4 文档/词表同步 ✅（本表+planbook §22；双端提交；agent SYSTEM 词表更新待重启生效）。

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
