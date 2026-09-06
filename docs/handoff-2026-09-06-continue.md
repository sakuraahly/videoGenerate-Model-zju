# 交接文档（2026-09-06 · 用户首验 3 段视频发现参考语义问题后 · 新 Agent 接手专用）

> 本档自包含，替代 `docs/handoff-2026-09-05-continue.md` 作为最新交接（该文件保留归档）。
> 现状：19 轮审核闭环 + 现场系列修复（P0 受控续接等）已上线；**用户首验 3 段 r2v 视频发现"参考图=首尾帧"问题，已取证归因并登记为最高优先任务 P1.5**。

## 0. 仓库与版本事实

| 端 | 路径/说明 |
|---|---|
| Windows 主库（源码真源） | `D:\MY_CODING_PROGRAM\videoGenerate-Model-zju`（唯一 push GitHub） |
| spark 运行时 | `~/videoGenerate-Model-zju`（仅经 dev.py sync/commit 同步） |
| 禁用 | `Z:/`、`C:\Users\39163\videoGenerate-Model-zju`（残留副本） |
| 当前 HEAD | win=github=`5570f21`+最新新文档提交；spark=对应 commit；两端 0 dirty（以 `dev.py check` 为准） |
| 运行实例 | spark agent=最新代码（每次 UI/工具改动需**重启并验证** AGENT_VERSION+SMOKE_OK） |

**铁律速查**：ComfyUI systemd 勿动（仅 `POST /free` 完整 body）；共享队列取消=**定向中断**（已修），归属校验必须；共享模板只读、绑定用副本；模型下载魔搭；中文经 ssh 一律临时脚本文件；单测**从仓库根运行**（165 例基线）；删除默认 dry-run。

## 1. 最新事实（本次首验）——最高优先

**现象（用户首验 3 段 r2v）**：每段产物"参考图=首帧+尾帧"（镜头1：客厅→男主；镜头2：男主→父亲；镜头3：父亲→眼镜）；中间帧仅人物/道具部分参考，**场景参考未发挥**（除首尾帧）。
**归因（已取证）**：3 段任务 `workflow_api.json` **`<Picture` tag 计数=0**——提示词未按官方契约（"reference the inputs by tag…`<Picture 1>`…matching the reference tags precisely tends to work best"）引用参考图；模型将参考图按顺序解读为**首→尾关键帧**；且模板 `ref_image_size` 固定 `match`（弱身份保真档；`max`=2048px 短边强保真、稍慢）。**非绑定/脚本 bug**（绑定此前已取证正确）。
**任务**：`docs/planbook/book-19-execution-ready.md` **§10 P1.5 参考语义修复**（提示词 tag 契约强制+生成后校验；ref_image_size 默认 max+开关；验证=3 段抽帧目检）——**当前最高优先，先于 P1/S2-P1a**。临时缓解（用户侧）：提示词手工加 `<Picture N>`（1-based 连接顺序）+"参考贯穿全片、非首尾帧"。

## 2. 已完成（勿重复）

| 项目 | 状态 |
|---|---|
| P0 受控续接（book-19 §8） | ✅ 已实施（目标驱动三态/上限5/轮空熔断/进度摘要） |
| 上传并发/预览 | ✅ 串行+全量重建+cid 兜底 |
| NameError 系列 | ✅ `_LAST_TOOL` 模块级+全链校验（win/spark grep=0，函数级三态验证） |
| 批量提交通道 | ✅ 池序号+逐段提示词（prompts→--prompts-file）+逐段台词（tts_texts/tts_voice）+文件名优先引导 |
| 取消链安全 | ✅ /interrupt 定向化+CancelTask 归一+last_job 原子写 |
| 单测基线 | 165 例绿（仓库根运行） |

## 3. 待做（权威规格=pending-tasks-implementation.md + book-19）

推荐实施序（book-19 顺序表）：**P1.5 参考语义修复 →（P1 事件驱动通知，先 S8 判定）→ S2-P1a → S3 → S8 → S1/S4/S5/S6/S9/S10/S12 → S7（最大工程，主案=API 层注入）**；S11 观察；S13/P 链待魔搭真实模型 ID 闭合。
关键陷阱速查：`scheduler` 键（非 scheduler_name）；node 136 width/height/length 是连线输入会被标量覆写（**megapixels 杠杆不可达**）；注入节点 id 必须 >146；`video_ref2v` 新 stage 会导致加速 LoRA 静默消失（定稿=扩展 video_r2v 条目）；批量 images 用**文件名/sha8 前缀**（池序号仅本会话一致时）；`ref_images` tooltip=2048 短边封顶（参考图增强上限）；length≡5 (mod 17)；768p 上限=加速 LoRA（模型本体 2K）。

## 4. 未决/待授权（勿单方执行）

1. 1920×1088+`--lora none` 原生分辨率探测（需队列空闲窗口+用户授权）；ref2v_4step v0.1 无标签=最不确定项；
2. 魔搭真实模型 ID（RIFE/SD-Inpaint/Wav2Lip+SF3D/FunASR/F5-TTS）——通道已验证、制品未验证（S13/P 链前置）；
3. `--scope-all` 暴露面保留但登记（收窄需另立项）；SYSTEM_MESSAGE 铁律（提交前 list_references/多段 batch_submit/不重述已完成段）部分实施待补。

## 5. 验收纪律与回写约定

每项：单测全绿 → ☆真机（真实提交+ffprobe+语音判别；参考语义=抽帧目检）→ spec/changelog/session/handoff 回写 → dev.py sync+commit → dev.py check 三端 0 dirty；"已修正必 grep 落点"；决策记录必须同步正文；UI/工具改动后**重启 agent 并验证**（AGENT_VERSION+SMOKE_OK）；行号敏感编辑用 grep 定位+事后 grep 核验（本会话 4 起编辑事故教训）。