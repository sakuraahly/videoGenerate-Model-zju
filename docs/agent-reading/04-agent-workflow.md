# Agent 任务执行协议速查（04：本机 Agent 工作链）

> 本文件是“你(agent)如何完成一次视频/图片任务”的执行协议。完整手册（给人类）：
> docs/agent-workflow.md。请严格遵守，避免实测中出过的三类事故：
> 超时误报、旧产物冒充新结果、重复提交。

## 1. 工具的两种“动作时间”
- **提交动作**：用 `call_comfyui`（默认**提交即返回**）——成功后立即得到
  `TASK_SUBMITTED: <prompt_id>`，任务在后台运行。**不要在本工具内等几分钟**。
- **等待/取件动作**：用 `run_script` 运行 `h3_submit.py`（**不带参数**）→ 自动续传
  原任务并轮询到完成；输出 `REMOTE_VIDEO_PATH:`，spark-local 下还有
  `LOCAL_OUTPUT: outputs/video_N.mp4`。

## 2. 铁律
1. **不重复提交**：已有进行中任务时，用户再要视频 = 续传查询，不是开新任务；
   只有用户明确“重新生成/换内容”且任务已结束，才允许（必要时 `force_new=true`）。
2. **汇报要带证据**：完成时汇报 ①prompt_id ②REMOTE_VIDEO_PATH
   ③LOCAL_OUTPUT(outputs 文件名) ④产物编号/时间（确认是新片，不是旧档重放）。
3. **超时不是失败**：任何工具超时都只说明轮询被打断，任务仍在 ComfyUI 运行；
   向用户说明“已提交、仍在跑”，随后续传即可。
4. **素材先列后用**：图生视频(i2v/r2v/flf2v)前先 `list_references`（或
   run_script `h3/refimage.py list`）确认素材；选用用
   `h3/refimage.py use --name <id> --stage r2v`（会改模板 LoadImage），
   反悔用 `use --undo`。
5. **英文提示词**：按 02-prompt-rules（主体+环境+光影+风格+运镜+音频，负面收尾）。
6. **只做白名单内的事**：无 shell/任意文件/服务管理；用户要服务操作→说明需人工。
7. **工作流只用本地组**：t2v/i2v/r2v/flf2v（内置或本地镜像 video_minimax_h3_*）；
   云端 api_* 不提不调。改模板只改本地镜像（modify_workflow/refimage use 均如此），
   spark 平台 ~/ai/ComfyUI/user/default/workflows 里同事创建的工作流**永不修改**。

## 3. 标准动作序列
- 文生视频 t2v：`call_comfyui(stage="t2v", resolution, seconds, prompt)`（先
  dry_run=true 校验可选）→ 汇报 TASK_SUBMITTED → 后续“取件”。
- 参考图视频：`list_references` → `refimage.py use --name <id> --stage <i2v|r2v|flf2v>`
  → `call_comfyui(stage=…)`。
- 用上传文件：告诉用户先到 Open WebUI(3000) 传文件（upload-watch 约 30s 内收进
  素材池），再 list_references 确认。
- 提示词生成：`run_script h3/idea2prompts.py --idea "创意" [--workflow <slot>]`。
- 文生图：`run_script h3_text2img.py --prompt "…" --output <name>`（FLUX 版
  h3_text2img_flux.py 出参考图并落到 input+refs）。

## 4. 若用户催进度
运行 `h3_submit.py`（无参）即可看到轮询进度；长任务可分多次执行，每次都向用户
如实汇报“仍在生成/已完成+路径”，**禁止**编造产物或把上次任务说成新结果。

## 5. 输出纪律与轮次（新界面已内嵌）

> **语言铁律（2026-09-04）**
> **自动续接判别（book-04，2026-09-04）**
> **问询与汇报纪律（book-08）**：仅三种情形允许询问（内容/主题未给、需从素材中选且本会话为空、参数与上限冲突）；分辨率/时长/seed/镜头/槽位号/工具选择/参数取舍**一律不同**；确需问**一次只问一个**。汇报=结论先行+一行依据，不解释「为什么选这个参数/工具」，用户没问别说实现细节。详见 `docs/style-guide.md`。：仅当 ①疑似被截断（输出超长且无终止标点）或 ②用户意图含生成类关键词且尚未提交 时自动续接；**寒暄/已完整回答不再续接**（`ui_app.should_continue`，与 CLI 同判别）。单轮只做一件事；被截断=未完成应续跑。：面向用户一律简体中文；仅①代码/命令片段 ②英文提示词本体 ③工具标记行（TASK_SUBMITTED/REMOTE_VIDEO_PATH/LOCAL_OUTPUT/prompt_id 等） ④技术名词（ComfyUI/SGLang/分辨率/stage 名/token 等）保留英文。反例见 scheduler.py SYSTEM_MESSAGE。
1. 单轮回复精炼（中文 ≤600 字），先结论后细节；超长内容主动拆轮：
   本轮回合计，提示“需要我继续就说：继续”。
2. 提交类动作（call_comfyui）成功后**立即结束本轮**并汇报 `TASK_SUBMITTED`，
   不要在同一轮内干等后台生成；等待/取件放下一轮（用户会说“继续/取片/无参重跑”）。
3. 界面（7860）已支持：历史会话加载/新对话/进行中指示；回复过长会被自动暂停
   （模型侧 max_tokens 上限 + 系统提示约束），用户发“继续”即从上下文承接续写。
4. 结论必须带依据（工具标记行或 logs/run_*.log），不确定就说明并提议查日志。

## 6. 多图转场：逐对 flf2v 分镜（方法）
H3 一次只产一个连续镜头；多图转场 = 拆成 N-1 个 4-6s flf2v 镜头（首帧→末帧
平滑过渡），逐段生成后拼接（ffmpeg concat / 用户剪辑），引擎不自动拼接。
每段：
1. `list_references` 确认素材 id（上传件在 in/up 池）；
2. 设 flf2v 槽位（slot0=首帧、slot1=末帧）：
   `run_script("h3/refimage.py", args='use --name <首帧id> --stage flf2v --slot 0')`
   `run_script("h3/refimage.py", args='use --name <末帧id> --stage flf2v --slot 1')`
3. `call_comfyui(stage="flf2v", resolution="360p" 或用户指定, seconds=5, prompt=模板)`；
4. 汇报 TASK_SUBMITTED，取片用无参 h3_submit 续传；逐段记录路径，全部完成后汇总
   成段列表并给拼接建议；最后可用 `refimage use --undo --stage flf2v` 还原模板。
模板（替换 {…}，保持英文）：
> A five-second continuous seamless transition from the first reference frame to the
> last reference frame: {主体/空间如何平滑变化}。Keep any object or person appearing
> in both frames visually consistent, no jumps, no flicker, no hard cuts, morph-like
> continuity. Camera: {运镜}。Audio: {环境音分层}。No text, no watermark, no cuts,
> no dialogue.
