# 阶段 12 — 加速 LoRA 候选筛选 + 交付质量增强 + 自动化自检（book-14）

> 状态：计划(未实施) · 日期：2026-09-05 · 来源：用户指令（加速 LoRA 用法/质量链/90 天会话清理/刷新语义/自检自动化）
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
- [ ] T1 候选加速：三个 LoRA 分别接线到本地模板（t2v/i2v/flf2v → fl2v_turbo_4step；r2v → ref2v 4/8step 可选），
      按作者步数写 BasicScheduler.steps=4/8；h3_submit --lora + 注册表 features 声明；dry-run + 真机 ffprobe 回归
      （同一提示词 4 步 vs 20 步输出参数/耗时对比进证据区）。
- [ ] T2 质量增强链（新管线 runs/h3/postprocess.py，接入取片）：超分（Real-ESRGAN 类）/插帧（RIFE）/降噪/调色、
      字幕与声音（TTS 语音清晰；字幕字体不乱码——必须校验字体渲染，中文字体嵌入）；
      dev.py postprocess 子命令 + 单测（输入输出参数断言 + ffprobe）。
- [ ] T3 参数注入回归守卫（book-12 已修）：consistency_check 增加「模板默认值 vs 注册表 params」核对
      （防止再做"默认 480p/5s"模板翻车）。

### P1（明确收益）
- [ ] T4 历史会话自动清除（90 天）：配置 config/session_retention.json（或复用机器配置）；脚本按 cid 的 meta/聊天档
      mtime 清 logs/agent_chats/<cid>* 与关联上传（仅清理**无任务引用**的 cid）；文档+单测。
- [ ] T5 UI“刷新内容”语义化：把按钮/菜单改为指明用途（如“刷新素材池/刷新历史/刷新状态”），
      按钮文案+提示与实际刷新目标一一对应（核对 Gradio 事件绑定，不许“刷新全屏”含糊行为）。
- [ ] T6 风格/角色 LoRA 支持：config/capabilities.json 增加 style_lora 字段 + 注入点（与加速 LoRA 分离），
      仅作为固定视觉特征用途（明确提示词注入规范）。

### P2（甜点，优先级很低）
- [ ] T7 自动化自检/小故事任务：qwen3.8Max 自检质量（**重点=连贯性**；按上下文限制把长视频拆多个片段逐一检视：
      帧间一致/人物不变形/场景不跳变）+ 调用 T2 后处理；agent 增加 verify_video/check_consistency 类工具；
      端到端 demo：“5 分钟科研艰难小故事”，人工只发布任务。
- [ ] T8 参考视频/音频原生支持（原 book-13 P1#10 迁移）：Ref2VA 支持 3 视频/3 音频 → 注册表 slots 已预留 videos/audios；
      refimage 接线 LoadVideo/LoadAudio + <Video N>/<Audio N> 提示词规范。

### L（低耦合·简单·拆给另一个 agent）
> 另 agent 命名约定：只改指定文件、跑 python runs/dev.py test + 单测、更新 docs（事实登记表）、
> 双端 sync/commit 用 python runs/dev.py；不重启 ComfyUI、不碰生成引擎核心、不可修改共享模板。

- [ ] L1 90 天会话清理脚本（纯新增：runs/agent/session_cleanup.py + 配置 + 单测 + 文档；不接生成流程）
- [ ] L2 UI 刷新语义（runs/agent/ui_app.py 文案与事件名小改；只读校验 /config 文案变化）
- [ ] L3 加速 LoRA 事实登记（只写 docs/code-fact-registry.md 新章 + capabilities.json 的 lora 段 + 文档图表；
      不改引擎）
- [ ] L4 book-13↔book-14 条目迁移核对（仅文档：把 book-13 §3.1/3.2/见闻迁移到本册，串引用）
- [ ] L5 dev.py queue status（只读：队列清单+归属判定=本会话登记/未知/他人；**禁止**实现删除，删除属 T 级待归属校验）

---

## 4. 验收与联动

- 每项 T/L 完成标准：单测/自测通过 → 文档（本册+事实登记表）→ 双端核对 → 提交；引擎类必过
  tests/e2e_smoke.py（SMOKE_OK）+ 真机 ffprobe 证据。
- 与 book-12（注册表/灵动适配——lora 声明进 features）、book-11（日志/审计）、book-09（黄金路径/验证）联动。
- book-13 剩余项处理完毕后执行**归档**（把未完成且仍有价值条目迁至各册或本册，然后 book-13 只留指针）。
