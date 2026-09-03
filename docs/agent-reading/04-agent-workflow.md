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
