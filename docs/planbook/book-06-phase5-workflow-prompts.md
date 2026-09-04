# 阶段 5 — 工作流提示词与受控注入（清理故事文案 + 强制每段独立提示词）

> 状态：计划(未实施) | 目标：把工作流 `video_*` 里内嵌的**英文故事**提示词清掉、只保留图像属性词；并让 agent 真正**逐段自产提示词并注入**，杜绝「五个长得一样」 |
> 主负责人：工作流/提示词链 | 依赖：book-05(会话素材) | 对后端影响：高（改动模板与注入） | 优先级：🟠 中

---

## 1. 问题背景（用户可见现象 + 事故）
- 「本地的工作流组需要改造，把工作流组中的提示词（英文）除了"不要模糊""大师杰作"这样的图像属性的提示词之外，全部删掉。」
- 「该模型在执行任务的时候，使用脚本工作，生成了五个一样的视频，疑似模型只是调整了参数，但并没有按照要求自己生成提示词并且注入工作流。」
- 模型本身也困惑「如何指定提示词、参考图位置、参考视频位置」。

---

## 2. 根因分析（实测，详见 workflow/prompt deep-dive）

### 2.1 五个一样视频 = 所有段共用同一个提示词
- `runs/h3_batch.py` 生成 N-1 个 flf2v 转场段，但对**每一段**都调用 `h3_submit.py` 并传**同一个** `--prompt`（`h3_batch.py:161-162`）。
- manifest 只有一个 `prompt` 字段（`h3_batch.py:133`），每个 segment 记录里**没有自己的 prompt 字段**（`h3_batch.py:113-121`）。
- → 5 段仅数值参数不同（图），提示词相同 → 5 个视频高度相似/相同。

### 2.2 idea2prompts 是「槽位文件写入器」，没接进提交链
- `idea2prompts.py` 把一个创意变成**每个工作流类型槽位**一个 {positive,negative}，写到 `prompts/workflows/<slot>.*.txt`；`h3_submit.py`/`h3_batch.py` **从不 import 或调用它**。
- 它产的是「按工作流类型」的槽位提示词，**不是按段落**；flf2v 的多图 N-1 段都读同一个 `video_flf2v.positive.txt`。
- 若 LLM 关闭走 `--force` 的 fallback（把原始创意当 positive、negative 为空），每段更近乎相同。

### 2.3 模板里没有 {{token}} 占位符 → 替换是空操作
- 逐文件核查：`workflows/remote_workflows/` 与 `config/templates/` 下**所有**模板 `{{prompt}}/{{image0}}/{{...}}` 出现 **0 次**。
- 因此 `templates.substitute`/`stage.substitute_api_workflow` 是 no-op；真正注入只有 `h3_submit.py:439 inject_local_prompts(wf,prompt,negative)`——它按 key 的 basename（prompt/positive/text，含 negative）覆盖模型节点的 prompt；**一次只写一个 prompt**。

### 2.4 `video_*` 内嵌提示词 = 纯英文故事，没有要保留的图像属性词
- t2v 节点105 `widgets_values[0]`（L158，1647 字符）：Action 追逐故事板（Shot1-4/镜头/音频/贴图纹理）。
- i2v 节点105（L195，1501 字符）：`<Picture 1>` 游戏鼠标宣传片。
- flf2v 节点105（L195，1501 字符）：**与 i2v 逐字节相同**（同文本同 seed 同 1344x768）；仅 `last_frame` 接了图（首帧 hero/末帧 alley），与鼠标故事对不上。
- r2v：真多参考节点 `MiniMaxH3ReferenceToVideo`(136) 的 prompt 为空，真实提示词在 `PrimitiveStringMultiline`(138) L942：`<Picture 1> is the main character and <Picture 2> is the location/scene … [describe the action and camera here]. Audio: [describe the sound here]…`（占位符未填，不是故事）。
- **全文检索：`不要模糊/大师杰作/no blur/masterpiece` 这些质量词在任何模板/提示词文件中都不存在** → 所谓「保留图像属性词」意味着：删故事 + 新增/保留质量 token（当前没有，需要加）。

### 2.5 参考图/参考视频位置的两个「半机制」；参考视频根本设不了
- **参考图**：①模板 `{{imageN}}` 占位（**实际 0 个**）②`refimage use --slot N` 改写 LoadImage widget（**真正生效**）。`--image` 只上传/绑定名字，**不会**填模板槽，除非模板有 `{{imageN}}`。
- **参考视频**：槽位存在（r2v `ref_videos.ref_video_0` @L767 link=null；api `model.reference_videos.video_1`）但**无上游节点、无 LoadVideo、无占位符**；`refimage.py` **拒绝非图片**（L463-465）、只接线 `ref_images.*`（L474,511），从不动 `ref_videos`。

---

## 3. 目标与范围

**目标**：工作流里只留图像属性/质量 token；每段有自己的、由 agent 自产并注入的提示词；参考图/参考视频位置的「契约」清晰可查。

**做**：
- 清理 `video_*` 模板：删除英文故事文本，保留/注入**图像属性词**（如 sharp focus, high detail, cinematic lighting, masterpiece quality, no blur, no distortion, no text, no watermark；即用户要的「不要模糊/大师杰作」语义）。
- 建立**逐段提示词**：`idea2prompts` 能按「第 N 段转场」生成提示词；`h3_submit`/`h3_batch` 能按段注入、而非共享一个。
- 把 `idea2prompts` 接进提交链（自动生成→注入），不再靠人手动跑。
- 明确参考图/参考视频位置契约：工具描述 + 文档写明「提示词用 --prompt/注入；参考图用 refimage use --slot N；参考视频当前不支持(或新增 LoadVideo+支持)」。
- 清理被污染的 `prompts/workflows/api_t2v.positive.txt`（现为 LLM 推理转写，非可用提示词）。

**不做**：不把 api_* 云模板纳入使用（仍红线）；不改 spark 同事模板；不删除 MarkdownNote 节点（那些是文档注释，不是提示词）。

---

## 4. 改动点清单（拟议）

| 文件 | 拟改内容 | 目的 |
|---|---|---|
| `workflows/remote_workflows/video_minimax_h3_{t2v,i2v,r2v,flf2v}.json` | 删节点内嵌 story 提示词（`widgets_values[0]`/`PrimitiveStringMultiline`），改为**图像属性 token 模板**；保留各 LoadImage/槽位接线 | 清故事、留质量词 |
| `config/prompt_blueprints.json` | 增加「图像属性 token 保留清单」（依 `docs/prompt-taxonomy.md` 10 正 + 9 负）与「逐段转场提示词」指导 | 供 idea2prompts 生成属性词+逐段描述 |
| `runs/h3/idea2prompts.py` | 支持 `--segments N`/`--per-segment`：为每个 flf2v 段生成独立 {positive,negative}；输出结构含段索引 | 逐段提示词 |
| `runs/h3_batch.py` | manifest 每段加 `prompt`/`negative_prompt` 字段；提交时按段注入各自提示词（而非共享 `--prompt`） | 杜绝五个一样 |
| `runs/h3_submit.py` | `inject_local_prompts` 支持**视频模型节点 widget**（video_* 的 widgets_values[0]）与 api 节点的 inputs.prompt；按段提示词注入 | 让注入真正落到节点 |
| `runs/h3/workflow.py`/`uiapi.py` | 关键：注入后能定位到 UI 模型节点的 `widgets_values[0]`（UI↔API 往返的 prompt 字段），确保 `--prompt`/注入生效 | 打消「提示词没注入」 |
| `runs/h3/refimage.py` | 明确拒绝参考视频并给出可读错误；若需支持则新增 LoadVideo 节点链路 | 让「参考视频无法设置」成为明确事实而非困惑 |
| `runs/agent/tools.py` | `call_comfyui`/`modify_workflow` 描述写明：提示词用 `--prompt`/注入；参考图用 `refimage use --slot N`；参考视频当前不支持 | 消除契约困惑 |
| `prompts/workflows/api_t2v.positive.txt` | 清掉 LLM 推理转写，恢复为可用提示词（或置空回退 default） | 修复污染 |

---

## 5. 实施步骤

### 步骤 1：先清工作流 story 提示词，改图像属性 token
- 对 t2v/i2v/flf2v：把模型节点 `widgets_values[0]` 改为简短图像属性模板，如：`sharp focus, high detail, cinematic lighting, masterpiece quality, no blur, no distortion, no text, no watermark`。
- 对 r2v：把 `PrimitiveStringMultiline` 改为同样的属性模板 + 保留 `<Picture 1/2>` 结构占位；删掉 `[describe the action...]` 故事占位（交由 idea2prompts 填）。
- 用 `refimage use --undo`（git 还原）或手改后跑 `h3_submit --dry-run` 验证可出 JSON。

### 步骤 2：idea2prompts 支持逐段
- 新增 `--segments N`（或 `--count N-1`）：为 flf2v 生成 N-1 段各不相同的转场提示词（结合每段的首/末帧描述）；输出到 `prompts/workflows/video_flf2v.segment_<i>.positive/.negative.txt`。

### 步骤 3：batch 按段注入
- `h3_batch.py` manifest 每段存 `prompt`/`negative_prompt`；提交段时 `h3_submit.py --prompt <该段>` ；不再把 `args.prompt` 统一传给每段。

### 步骤 4：注入落点修正（UI↔API）
- 确认 `inject_local_prompts` 能命中 video_* 模型节点的 prompt（widgets_values[0] 或 UI↔API 往返后的 inputs.prompt）。用 `h3_submit --dry-run` 打印 API 图，断言 prompt 已替换为属性模板/段提示词。

### 步骤 5：参考视频边界明确
- 若用户需要参考视频，新增 LoadVideo+`ref_videos`/`model.reference_videos` 链路并扩 `refimage`；否则在工具描述与系统提示明确「参考视频暂不支持」并给出替代建议（如用首帧图模拟）。

### 步骤 6：回归验证「段各不同」
- 多图任务生成 N-1 段，断言各段提示词不同、产物不同（对 book-09 黄金路径 step 7）。

---

## 6. 验收标准

- [ ] `video_*` 模板内嵌故事提示词已删，仅剩图像属性/质量 token；无 `[describe...]` 之类未填占位。
- [ ] `idea2prompts --segments N-1` 能产出 N-1 个不同提示词；`h3_batch` 按段注入，不再共享一个。
- [ ] 多图转场实际生成的每段**内容不同**（端到端，配合 book-09 黄金路径）。
- [ ] 工具描述/文档明确写清：提示词=--prompt/注入；参考图=refimage use --slot N；参考视频=当前不支持（或已支持并有 LoadVideo）。
- [ ] `prompts/workflows/api_t2v.positive.txt` 已修（不再含 LLM 推理转写）。
- [ ] `h3_submit --stage <t2v/i2v/flf2v/r2v> --dry-run` 打印的 API 图中 prompt 已是属性 token，而非原故事。

---

## 7. 风险与回滚
- **风险：删了故事提示词后，属性 token 太短/太泛导致画面变差**——属性 token 是质量约束，画面主体内容由 agent 经 idea2prompts 注入，二者互补；先在 dry-run 验证后再真跑。
- **风险：UI↔API 往返丢 prompt**——`uiapi.py`/`subgraph.py` 已处理，但注入落点必须实测（book-07 的契约段）。
- **风险：参考视频若加 LoadVideo 链路改动大**——默认先说「不支持」，需要时再增补，避免一次改动过大。
- **回滚**：模板可用 `refimage use --undo` 或 git 还原；idea2prompts/batch 改动为新增参数，默认行为不变。

---

## 8. 与其它册/红线的关系
- 与 book-07（批量/引擎契约）强耦合：逐段提示词必须落到 `h3_batch`/`h3_submit`。
- 与 book-05（资源隔离）：注入的参考图只取本会话素材。
- 红线：不动 spark 同事模板/ComfyUI 配置；不引入 api_* 云模板；不越白名单。

---

## 9. 待用户输入 / 待定项
- ✅ 图像属性 token 清单已定：见 `docs/prompt-taxonomy.md`（10 正向 + 9 负向大类）；模板只保留基础质量/属性词，其余由 agent 注入。
- 参考视频：用户定级为「甜点/低优先」，列入待做清单（见 book-07 §9）。
- ✅ 质量 token 与画面主体分工确认：模板固定属性词；画面主体/动作/镜头/音频由 agent 逐段注入。
---

## 10. 实施记录（2026-09-04，与 book-07 联动）

- ✅ **模板清理**：video_* 四份模板内嵌 story 提示词删除，仅保留图像属性词（t2v 1647→154ch、i2v/flf2v 1501→154ch、r2v 319→227ch 并保留 `<Picture 1/2>` 结构占位）；`prompts/positive_prompts.txt` 与受污染的 `api_t2v.positive.txt` 清为属性词；模板全文已无 story 标记（grep=0），质量词 4/4 命中。
- ✅ **逐段提示词（核心，治"五个一样"）**：`h3_batch submit --prompts-file <json>`（`{"0":"...","1":"..."}` 按段索引）→ manifest 每段存 `prompt` → 提交时**按段 `--prompt` 注入**（不再全局共享）；`retry` 也按段取提示词。spark 实测：2 段 dry-run `per-seg distinct=2`（提示词不同）。
- ✅ **验证**：`h3_submit t2v --dry-run` rc=0（模板清理未破坏注入）；spark 组合验证脚本通过。
- ⏳ 设计待做（下一批）：`idea2prompts --segments N`（自动产出 N 段转场提示词写入 `video_flf2v.segment_<i>.positive.txt`，再由 agent 传 `--prompts-file`）；`注入后 dry-run 断言各段提示词已替换`（book-09 黄金路径步骤 7）。
---

## 11. 端到端事故记录与补丁（2026-09-04 用户实测：两图丝滑转场）

- **事故**：agent 提交 flf2v `TASK_SUBMITTED 5344eab7...`（agent 自写提示词"飞船发射台→房间"），但**成片内容是别人的图/早期视频内容**（前段与旧工作流+参考图提示词导出的视频相同）。用户还反馈：提交后**等待期无任何输出**（界面只有"任务排队中"，40 分钟无内容）。
- **根因（spark 取证）**：任务 API 工作流 `LoadImage 114/121` 仍是模板**默认旧资产**（`drama_asset_*`）——①`call_comfyui` 无图参数、模板无 `{{imageN}}` 占位符、`--image` 对 video_* 无效 → agent 无法把图注入槽位（其"refimage use"未生效/未调用）；②`prompts/workflows/video_flf2v.positive.txt`（hero→alley 文本）等在未传 `--prompt` 时被注入，兜底污染；③模板清理只清了内嵌 prompt，未清 LoadImage 默认图。
- **补丁**：①`refimage.bind_images_to_template(stage, names)`（把上传后的图名绑定 LoadImage 槽位：flf2v slot0/1、i2v slot0、r2v 前 N）；②`refimage.check_default_refs(stage)` 守卫——图生类阶段未传图且模板仍是默认旧资产 → **h3_submit 拒绝提交**（dry-run 也拦截，报错给指引）；③`h3_submit` 在 i2v/r2v/flf2v 且传 `--image` 时自动绑定（dry-run 仅提示）；④`call_comfyui` 新增 `images` 参数（逗号分隔，直接走绑定路径）；⑤`prompts/workflows/{video_flf2v,i2v,r2v}.positive.txt` 清为属性词（原 story 文本删除）。
- ✅ **验证**：spark 见下（dry-run 绑定提示 + 无图默认资产守卫报错 + 模板槽位未被 dry-run 污染）。
