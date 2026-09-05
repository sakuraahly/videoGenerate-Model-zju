# 阶段 12 — 加速 LoRA 候选筛选 + 交付质量增强 + 自动化自检（book-14）

> 状态：**部分实施**（T1/T2/T2b v1/T6/L1–L5 已完成；**T2b 语音链 2026-09-05 升级 P0**） · 日期：2026-09-05 · 来源：用户指令（加速 LoRA 用法/质量链/90 天会话清理/刷新语义/自检自动化）+ 用户四问（语音不可辨析/验收口径）
> 优先级：🟠 中（其中 L 类**低耦合任务**拆给另外的 agent 执行）
> 红线（升级纪律，来自既往事故——**千万不能踩之前的坑**，先读 docs/dev-workflow.md §10 与 §11）：
>   - 文件写入 EIO(1175)/JS 转义/引号嵌套陷阱；**作用域 NameError**（本次 imgs 事故：引用别函数局部变量）；
>   - **绑图不得写共享模板**（须副本，防污染）；断点锁（--force-new 明确）；**队列为共享服务器**——任务可能属于他人，
>     删除/取消必须按 last_job/任务目录登记的 prompt_id 归属校验后才允许；
>   - 中文编码经 PowerShell→ssh 会乱码（用临时脚本直跑）；不改 ComfyUI systemd/同事模板；新增参数须同步
>     注册表(capabilities.json)/事实登记表(code-fact-registry.md)/运行时一致性(runtime_check)，防再漂移。

---

## 1. 背景与目标

1. **更快抽取候选镜头**：加载明确支持 H3 的**加速 LoRA**，按作者要求降低采样步数（4 步/8 步蒸馏），
   缩短单次采样时间 → 相同时间内测试更多 提示词/seed。
2. **交付质量增强链**：生成的视频后处理——超分、插帧、降噪、调色、字幕与声音
   （人物语音要合理清晰；视频/图片中字幕、场景字体等**不能错乱**）。
  **⚠️ 2026-09-05 用户实测**：t2v 成品**语音混乱不可辨析（实为无音轨→输出噪声）** → 语音链升级为 **P0**（见 T2b）。
3. **历史会话自动定期清除**（保留 90 天）。
4. **agent 界面“刷新内容”语义化**：改为指明用途（刷新什么），不再含糊。
5. **自动化任务流程（甜点，优先级很低）**：qwen3.8Max 自己检验生成视频/图像质量（重点=**连贯性**；
   为**上下文限制**把长视频拆分多个小片段检验）+ 调用上述超分/降噪等，在**无人工监督**（任务仍由人工发布）
   条件下智能执行，如“做一个 5 分钟小故事，主题是科研的艰难，人物连贯、场景转换不生硬”。

---

## 2. 加速 LoRA 事实登记（spark 实测路径）

目录：/home/Developer/ai/ComfyUI/models/loras/MiniMax_H3/（3 个，均由 Lightx2v/ModelTC 社区制作，ComfyUI bf16）：

| 文件 | 模式 | 步数 | 分辨率/训练 | 适用 |
|---|---|---|---|---|
| minimax_h3_fl2v_turbo_4step_v1.0_768p_comfyui_bf16 | FL2VA（T2V/I2V/FLF2V） | 4 步 | 768p（1344×768）v1.0 | 快速出片/简单场景验证；文生视频、首帧图生、首尾帧补间 |
| minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16 | Ref2VA（参考生视频） | 4 步 | 544p 混合宽高比 v0.1 预览 | 多模态参考：最多 9 图 + 3 参考视频 + 3 参考音频；提示词用 <Picture N>/<Video N>/<Audio N> 指定 |
| minimax_h3_ref2v_turbo_8step_v1.0_768p_comfyui_bf16 | Ref2VA | 8 步 | 768p v1.0 正式 | 同上但质量更高（细节/人物一致性/复杂运镜更稳），速度≈4 步版 2 倍；正式出片/需高稳定性 |

- **加速 LoRA ≠ 风格/角色 LoRA**：后者用于固定特定视觉特征（画风/角色一致性），与加速 LoRA 是不同用途，可叠加（需校验兼容）。
- **候选流程落地**：模板中接入 LoRA 节点 + 把 BasicScheduler steps 降为 4（或 8）；h3_submit 增加
  --lora <fl2v_4step|ref2v_4step|ref2v_8step|none>（或从注册表 features 声明），默认 none 保持现状（金丝雀）。

---

## 3. 任务清单（分级）

### P0（用户价值，正文案）
- [x] T1 候选加速（**引擎侧完成 2026-09-05**）：capabilities.json 顶层 `lora` 注册（3 文件/steps/适用阶段）；`h3stage.apply_lora`（LoraLoaderModelOnly 注入+model 引用替换+steps 4/8 覆写+防自环）；`h3_submit --lora`（choices+日志同步）；tools.py CallComfyUI 新增 `lora` 参数（注册表派生枚举，agent 重启后可见）；单测 138 全绿；spark dry-run 双验证（r2v+ref2v_4step / t2v+fl2v_4step → LoraLoader+steps=4）。
      **真机对比（2026-09-05 完成，全程项目程序）**：r2v 360p/5s/seed42 同提示词：A=ref2v_4step（bb4387d9）**72s** vs B=none 20 步（0727000d）**163s** → **≈2.26× 加速**；两产物 ffprobe 完全一致（608×352/24fps/5.17s/124 帧）；修复 lora_name 须带 `MiniMax_H3/` 前缀（ComfyUI /object_info 枚举确认，原 400 提交拒绝已修）；B2 守卫补 resume 参数恢复（下次完成自动 verify 对冲）。
      **⚠️ 用户实测反馈（2026-09-05）：4 步加速版画面瑕疵比 20 步正常流程多**（速度换质量代价，已实证）。策略：候选/构景筛选用 4 步；确认出片/正式交付用 ref2v_8step(v1.0) 或禁用加速(20 步)；T2 质量链（超分/降噪/插帧）对低步瑕疵有补偿；T7 自检把“低步瑕疵”列为重点项。**⚠️ 2026-09-05 用户指令（已批准，book-17 §3.1 实施中）**：LoRA **必须用上**——验证/普通档默认 `fl2v_4step/ref2v_4step + 360p/5s`；交付/精品档 `ref2v_8step 768p 或 none 20 步`；工具 `lora` 默认值由 none 改为验证档 4 步（不再“仅用户同意才用”）。落地：`runs/agent/agent_params.py` + CallComfyUI 默认参数/转发 `--lora` + SYSTEM_MESSAGE 档位规则。
- [x] **T2 v1 完成（2026-09-05，ffmpeg 管线）**：`runs/h3/postprocess.py`（probe/process/run_fast；2x lanczos 超分 + hqdn3d 降噪 + unsharp 锐化 + 可选调色滤镜串 + `--interp` 插帧[默认关]；**ffprobe 断言输出分辨率/时长漂移**，失败非 0 不打折）；`h3_submit --postprocess none|fast`（spark-local 完成后自动增强，失败不阻断主产物）；`dev.py postprocess`（Windows 侧一键调 spark 执行）；真机集成：video_12.mp4(608×352) → **1200 路 1216×704**/5.17s/124 帧 ✓。
- [x] **T2b v1 完成（2026-09-05）**：字幕烧录（`render_subtitle`：libass subtitles 滤镜 + Noto Sans CJK SC 字体、`validate_srt` 先验、输出分辨率不变断言）+ 音频混流（`mix_audio`：-shortest + AAC 192k）+ `run_full` 完整链（增强→字幕→音频，失败即抛不产半成品）；`dev.py postprocess --subtitle/--audio/--font-size` 透传；真机集成：video_12 → **video_12_full.mp4 1216×704 + AAC 5s + 中文 SRT 烧录**，抽帧目检中文无乱码 ✓；单测 148 全绿。
- [x] **T2b 语音链 v1 完成（2026-09-05）**：P0-1 **edge-tts**（pypi 200/bing 可达/实测合成成功；中文女声 XiaoxiaoNeural 默认）；P0-2 `runs/h3/tts.py`（合成/替换/apad 保留完整时长；修复 -shortest 截断、原地写、edge-tts 三路定位）；P0-3 自动接线（call_comfyui `tts_text` → h3_submit `--tts-text` → 任务记录 → 完成钩子 `TTS_OUT`）；真实链：`--tts-text 再见了，故乡。` → `outputs/video_23.mp4`（608×352/5.167s/124f/AAC 5.167s 完整时长）。**待收尾**：① 逐句对齐（SRT→逐句语音，`build_srt_speech` 已实现待接 dev.py 流程）；② 听测判据（用户确认可辨析）；③ 无台词策略（保留环境音/静音轨）听测后定（book-17 决策点 C）。

      - **根因**：t2v 工作流**无音频通道**（capabilities `features.audio=false`）→ 无音轨输入 → 输出音频=**随机噪声**；任何“说话/配音”需求都不可达（非 TTS 质量问题，是通道缺失）。
      - **子任务**：
        1. **P0-1 TTS 引擎选型**（spark 环境探测出网与本地推理；候选：edge-tts 离线模型 / piper / ComfyUI 本地 TTS 节点；判据=中文音质+离线可用）；
        2. **P0-2 音轨替换**：`postprocess.py run_full` 增 `--tts <文本>`：文本→中文语音 wav→转码→与视频混流（音量归一化；`mix_audio` 已有外部音轨能力，只缺语音生成环节）；
        3. **P0-3 自动接线**：字幕 SRT 已存在 → 用 SRT 文本逐句合成语音并对齐（最贴合“说话”）；`h3_submit --postprocess full` 默认带语音，无台词视频→静音轨替代噪声轨；SYSTEM_MESSAGE 决策规则同步（book-16 台账#6）。
      - **完成标准（严）**：真实 UI 出片 → 音轨为**可辨析中文语音**（非噪声）、与字幕逐句对齐；ffprobe 含 AAC 音轨且时长≈视频。
      - **取消条件**：spark 若无可行的本地 TTS → 降级“静音轨+字幕”并如实文档化（**不得宣称语音通过**）。
      - **⚠️ 2026-09-05 用户指令**：当前仍为氛围音（未达语音判据）→ 本子项为**批准后第一优先**；与 book-17 §4 联动（无台词视频“保留环境音 vs 静音轨”听测决策 + 低参验证档联动 W1/W3 痛点测试）。
      - **T2b v2 修复批（2026-09-05 用户实测“视频 23 没有中文人声+无字幕+重复提交”后登记，待实施）**：
        1. **钩子改“本任务文件”**：`_finalize_local_outputs` 返回本次本地路径传入完成钩子；**禁止**全目录 glob-mtime 选文件（曾命中 video_22 而非本次 video_23）；
        2. **时长守卫**：目标文件时长 < 原时长 60% → 拒绝替换并重新取源（防 -shortest 截断源再入，video_22 曾因此保持 2.06s）；
        3. **台词字幕一步到位**：`tts_text` → 同时生成 SRT（整句/逐句）→ `render_subtitle` 烧录进成片（成品=画面+中文语音+对白字幕）；
        4. **会话级防重复提交**：同会话 30 分钟内“stage+分辨率+时长+提示词指纹”相同 → 复用上次 prompt_id 并提示（audit 记 `dedup`；SYSTEM_MESSAGE 规则）；末端再防：模型自动续接曾 10:40 三连/10:59 双发；
        5. **成品验收客观化**：回执含 ffprobe 实测（w/h/fps/dur/frames）+ 音轨来源指纹（合成语音文件 vs 原氛围音）；音轨必须为合成语音产物而非“有 AAC”。
- [ ] **T2b 剩余子项（降级为 P1）**：② 真实超分模型（Real-ESRGAN）与 RIFE 插帧（ComfyUI 节点）接入（v1 为低依赖 ffmpeg 兜底；对 4 步加速瑕疵有补偿价值，接在 P0 语音后）。
- [ ] T3 参数注入回归守卫（book-12 已修）：consistency_check 增加「模板默认值 vs 注册表 params」核对
      （防止再做"默认 480p/5s"模板翻车）。

### P1（明确收益）
- [x] **T4 完成**（由 L1 交付：session_cleanup.py + config/session_retention.json + 6 单测；详见 L1 记录）。
- [x] **T5 完成**（由 L2 交付：ui_app 刷新→「刷新历史列表」+相邻提示；/config 已实测命中）。
- [x] **T6 完成（2026-09-05）**：capabilities.json 新增顶层 `style_lora` 段（dir/prompt_rule/与加速 LoRA 分离说明；引擎侧暂不接线，登记+规范先行——视觉特征固定建议：提示词声明+固定 seed；与加速 LoRA 叠加前须兼容性校验）。
- [ ] **T9 qwen 取消自己任务（用户提出 2026-09-05；现状：agent 无取消工具、引擎无取消路径）**：
      - 可行性已实测：ComfyUI 5.23.1 取消端点 = **POST /queue** + body `{"delete": [qid]}`（空载荷 200；旧 `/queue/delete`/DELETE 方法均 405；`POST /prompt` 400 为正常）。
      - 实现分两层：① `dev.py queue cancel <qid> --prompt-id <pid>` —— **归属校验**（pid 必须命中本机登记 last_job.json 或任务目录 job.json，否则拒绝并提示）；② agent 新工具 `cancel_task(prompt_id)`（内部转 RunScript/或直接调 dev.py queue cancel；仅允许取消**自己会话登记的**任务），工具描述含取消后果（后台任务停止、断点清理）；
      - 红线：**只允许取消本机登记的任务**；他人/未知任务一律拒绝；取消后提示可重新提交。

### P2（甜点，优先级很低）
- [ ] T7 自动化自检/小故事任务：qwen3.8Max 自检质量（**重点=连贯性**；按上下文限制把长视频拆多个片段逐一检视：
      帧间一致/人物不变形/场景不跳变）+ 调用 T2 后处理；agent 增加 verify_video/check_consistency 类工具；
      端到端 demo：“5 分钟科研艰难小故事”，人工只发布任务。
- [ ] T8 参考视频/音频原生支持（原 book-13 P1#10 迁移）：Ref2VA 支持 3 视频/3 音频 → 注册表 slots 已预留 videos/audios；
      refimage 接线 LoadVideo/LoadAudio + <Video N>/<Audio N> 提示词规范。

### L（低耦合·简单·拆给另一个 agent）
> 另 agent 命名约定：只改指定文件、跑 python runs/dev.py test + 单测、更新 docs（事实登记表）、
> 双端 sync/commit 用 python runs/dev.py；不重启 ComfyUI、不碰生成引擎核心、不可修改共享模板。

- [x] L1 90 天会话清理脚本（纯新增：runs/agent/session_cleanup.py + 配置 + 单测 + 文档；不接生成流程）。**已完成 2026-09-05**：`session_cleanup.py`（status/clean，默认 dry-run，只删 `<cid>.jsonl`+`.meta.json`、thumbs 不删、判定基准=mtime 与 meta.ts 较新者）+ `config/session_retention.json`（tracked）+ `test_session_cleanup.py`（6 例）+ code-fact-registry §9；全量单测 138 绿。
- [x] L2 UI 刷新语义（runs/agent/ui_app.py 文案与事件名小改；只读校验 /config 文案变化）。**代码已完成并提交 master 2026-09-05**：`刷新`→`刷新历史列表` + 相邻 Markdown 提示（仅刷新左侧历史下拉），`.click` 事件绑定未动；docs/agent-workflow.md 同步。⚠️ **spark /config 文案验证待两端 reconcile 后随一次 agent 重启确认**（协作裁定 #3：不 sync/覆盖 spark；当前 spark ui_app 为分叉版本）。
- [x] L3 加速 LoRA 事实登记（只写 docs/code-fact-registry.md 新章 + capabilities.json 的 lora 段 + 文档图表；
      不改引擎）。**已完成（被 T1 吸收）2026-09-05**：capabilities.json 顶层 `lora` 段以 **T1 引擎 schema 为准**（`choices/files/steps/stages`），按协作裁定 #1 **不再改**；L3 保留 code-fact-registry §10 登记小节（3 个 LoRA 路径/步数/用途）。
- [x] L4 book-13↔book-14 条目迁移核对（仅文档：把 book-13 §3.1/3.2/见闻迁移到本册，串引用）。**已完成 2026-09-05**：book-13 参考视频支持(P2#10)→T8、§3.1/§3.2/§3.3 各加「关联 book-14」前向指针；本册 §4 加「架构优化项归属」；git diff 仅增标注、原文无损。
- [x] L5 dev.py queue status（只读：队列清单+归属判定=本会话登记/未知/他人；**禁止**实现删除——删除/取消由 **T9** 实现，含归属校验）。**L5 已完成**（book-12 A5：`dev.py queue`，只读+归属，spark 实测）。**2026-09-05 补**：dev.py 加 `queue status` 动作（`queue`/`queue status` 均可）、queue_probe 输出加节点数；grep 确认无 delete/cancel 写路径。⚠️ 与 spark 侧 T9（`queue cancel`）在 dev.py/queue_probe.py 上分叉，待 reconcile 合并。

> **协作裁定（2026-09-05，给执行 L 类的 agent）**：
> 1. **L3 已由 T1 吸收**：capabilities.json 顶层 `lora` 段以 **T1 引擎 schema 为准**（`files` 值为 ComfyUI 枚举名，含 `MiniMax_H3/` 前缀；`choices/steps/stages` 为运行字段）——**不要再改 capabilities.json 的 lora 段**；L3 仅需在 docs/code-fact-registry.md 追加登记小节（3 个 LoRA 路径/步数/用途）。
> 2. **L2 验证**：改 runs/agent/ui_app.py 后需重启 agent 并跑 e2e smoke（命令见 handoff-2026-09-05-L-tasks.md §6）。
> 3. **spark 未提交改动**：如看到 spark 有未提交改动（如 T9 在制品），**不要动、不要 sync/覆盖**；L 类只提交自己的文件（dev.py commit 只带自己的文件列表；必要时手动 git add 精确路径）。
> 4. **进度勾选**：完成项在 L1–L5 上改为 [x] 即可。

---

## 4. 验收与联动

- 每项 T/L 完成标准：单测/自测通过 → 文档（本册+事实登记表）→ 双端核对 → 提交；引擎类必过
  tests/e2e_smoke.py（SMOKE_OK）+ 真机 ffprobe 证据。
- 与 book-12（注册表/灵动适配——lora 声明进 features）、book-11（日志/审计）、book-09（黄金路径/验证）联动。
- book-13 剩余项处理完毕后执行**归档**（把未完成且仍有价值条目迁至各册或本册，然后 book-13 只留指针）。
- **架构优化项归属（L4 迁移核对，2026-09-05）**：book-13 §3.1（素材绑定统一入口）→ 随本册 T1/T8 落地；§3.3（事实/常量单源）→ 随本册 L3（capabilities.json lora 段 + code-fact-registry §10）+ T3 + 红线（注册表/事实登记表/runtime_check 同步）落地；§3.2（图片解析收敛）→ 本册未覆盖，暂留 book-13。book-13 参考视频支持（P2#10，旧称 P1#10）→ 已迁移至本册 T8。
