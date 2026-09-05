# 阶段 10 — Agent 工具自动化/模块化/通用化 + 灵动多工作流适配（为便捷更换工作流做准备）

> 状态：实施中（步骤1 完成；步骤2 进行中——含参数注入修复） | 目标：让「某个工作流怎么用、用什么模板/槽位/提示词注入点/参数上限、是否支持参考视频/逐段转场」全部由**单一声明式注册表**驱动；新增/替换/禁用工作流=改配置+校验，**不改工具代码、不改系统提示词**；agent 工具层做到「灵动的多工作流适配」 |
> 主负责人：后端/Agent | 依赖：book-06(提示词注入)、book-07(引擎契约/批量)、book-01(基座校验) | 对后端影响：高 | 优先级：🟠 中

---

## 1. 问题背景（用户需求）
- 「把 agent 调用工具的自动化和模块化还有通用化进一步升级。」
- 「比如支持灵动的多工作流适配，为未来的便捷更换工作流做准备。」

---

## 2. 现状与根因（实测核查）

### 2.1 已有雏形：capabilities.json 声明式注册表
- `config/capabilities.json` 已有 tools/workflows/prompt_slots/note_for_llm 等；`runs/h3/capabilities.py --doc/--digest` 可生成 `docs/capabilities-ai.md`（人读）与模型 digest。
- 但 workflows 条目**只有** id/engine/purpose/needs_images/slot——**缺**：模板文件名、槽位规格（LoadImage 数量与语义、ref_video）、提示词注入点（ui widget 下标/api key）、参数上限（resolutions/seconds）、特性位（参考视频/逐段转场/音频）、启停状态。

### 2.2 真正驱动执行的仍是硬编码（这就是"不灵动"的根源）
- `runs/agent/tools.py` `CallComfyUI`：`stage` **enum 硬编码** `[t2v,i2v,r2v,flf2v]`、`resolution` enum `[360p..768p]`（描述也是手写枚举）。
- `runs/h3/refimage.py` `_stage_template(stage)`：**固定文件名** `video_minimax_h3_{stage}.json`；`template_slots`/`_wire_slot` 只认识 `ref_images.*`（不认 ref_videos/ref_audios）。
- `runs/h3/prompts.py`：manifest `workflow_files` → slot 映射**按文件名枚举**；`inject_local_prompts` 按 **key basename 启发式**（prompt/positive/text）定位注入点——脆弱。
- `runs/h3/stage.py`：`_DEFAULT_CONFIG`+`KNOWN_TOKENS` 固化；`config/pipeline.json` stages 手工登记。
- `runs/agent/scheduler.py` SYSTEM_MESSAGE：**枚举 4 阶段与工具语义**；`docs/agent-reading/01/03/04` 同样硬编码。
- 结论：**加一种工作流/换一个模板版本 = 动 5+ 处代码与文档**，且 agent 的"能力认知"是背下来的，不是查出来的。

---

## 3. 目标与范围

**目标**：单一注册表（`config/capabilities.json` 升级为「工作流注册表」）+ 适配器层 + 动态 Agent 认知 + 工具/引擎全部按表驱动。

**做**：
- **注册表补全**：每个 workflow 增加 `template`（文件路径）、`slots`（类型/数量/语义：first_frame/last_frame/ref_images/ref_videos/ref_audios）、`prompt_inject`（ui widget 下标 或 api key 路径）、`params`（resolutions/seconds 上限/fps/steps 默认）、`features`（reference_videos/per_segment/audio/negative_support）、`enabled`。
- **适配器 `runs/h3/workflow_registry.py`**：load/validate/query；`resolve(stage)` → 模板路径+槽位规格+注入点+参数上限；`is_enabled`；`template_health(tpl)`（模板存在、必需节点/槽位在、注入点可定位、UI↔API 可转换）。
- **消费方重构（去硬编码）**：`tools.py CallComfyUI` 的 stage/resolution enum 与描述改为**注册表派生**（动态生成工具描述）；`refimage._stage_template`/`template_slots`/`_wire_slot` 改按注册表槽位规格（支持 ref_videos/ref_audios）；`prompts.py` 注入点按注册表定位；`stage.py`/`pipeline.json` 以注册表为源合并（保留 p 兼容）。
- **Agent 动态认知**：`capabilities.py --digest` 输出「当前可用工作流 + 参数范围 + 特性」摘要，SYSTEM_MESSAGE 改为**运行时注入 digest**（不再手写枚举）；read_doc 增加自动生成的 `05-workflows-registry.md`；新增工作流=agent 自动可见，无需改提示词。
- **灵动适配**：支持组合（例如注册表声明 `per_segment: true` → 自动获得「N 图 → N-1 段」批量能力）；参考视频位开启→适配器自动接线 LoadVideo+ref_videos（顺接 book-06/07 的"甜点"项）；`enabled=false`→工具拒绝并提示禁用原因。
- **便捷更换工作流**：`dev.py workflows` 子命令：`list` / `add <id> --template <path>` / `disable|enable` / `validate --all` / `swap <id> --template <new>`（含 sha 记录+干跑校验）；模板版本换新=注册表指到新文件+`validate` 通过。
- **一致性**：`consistency_check.py` 增加「注册表 vs pipeline/manifest/templates 引用 vs 工具描述」核对；`capabilities.py --doc/--digest` 与注册表同源。

**不做**：不引入运行时插件系统/热加载（先"配置驱动+校验"）；不改 ComfyUI 服务/同事模板；不跳过 dry-run 校验（适配必须可验证）。

---

## 4. 改动点清单（拟议）

| 文件 | 拟改内容 | 目的 |
|---|---|---|
| `config/capabilities.json` | workflows 条目补 template/slots/prompt_inject/params/features/enabled | 单一注册表 |
| 新增 `runs/h3/workflow_registry.py` | load/validate/query/resolve/template_health | 适配器 |
| `runs/agent/tools.py` | CallComfyUI `stage`/`resolution` 枚举与描述改为注册表派生；新增校验（禁用即拒） | 去硬编码 |
| `runs/h3/refimage.py` | `_stage_template`/`template_slots`/`_wire_slot` 改按注册表槽位规格；支持 ref_videos/ref_audios 接线 | 灵活槽位 |
| `runs/h3/prompts.py` / `h3_submit.py` | 注入点按注册表定位（替代 basename 启发式）；`--stage` 校验走注册表 | 稳健注入 |
| `runs/h3/stage.py` / `config/pipeline.json` | 以注册表为源合并（保留兼容）；KNOWN_TOKENS 由注册表汇总 | 单源 |
| `runs/agent/scheduler.py` | SYSTEM_MESSAGE 改为运行时注入 `capabilities --digest`（工作流/参数/特性） | 动态认知 |
| `runs/agent/doc_utils.py` / `docs/agent-reading/` | 自动生成 `05-workflows-registry.md`（含各工作流用法、参数范围、特性、启停状态） | 可查询 |
| `runs/dev.py` | 新增 `workflows` 子命令（list/add/disable/enable/validate/swap） | 便捷管理 |
| `runs/consistency_check.py` | 注册表 vs pipeline/manifest/templates/工具描述 一致性核对 | 防漂移 |
| 文档 | `docs/reference-2026-09-04.md`/`skills/h3-video-generation.md`/`START-HERE.md`：注册表即工作流唯一来源 | 口径一致 |

---

## 5. 实施步骤

### 步骤 1：注册表 schema + 适配器
- 给 capabilities.json 每条 workflow 补字段；写 `workflow_registry.py`（load/validate/resolve）；单测：schema 完整、模板存在、注入点可定位、UI↔API 可转换。

### 步骤 2：消费方去硬编码（按表驱动）
- 依次：h3_submit `--stage` 校验 → refimage 槽位/模板 → prompts 注入点 → tools.py 枚举+描述 → stage.py/pipeline 合并。每步保持旧行为（金丝雀：全部已注册工作流 dry-run 通过）。

### 步骤 3：Agent 动态认知
- `capabilities --digest` 内容扩充（含参数范围/特性/启停）；`scheduler.py` 运行时注入；`05-workflows-registry.md` 自动生成进 read_doc。验证：新增一条注册表条目后，**不改 SYSTEM_MESSAGE**，agent 便能在对话中说出该工作流。

### 步骤 4：灵动适配 + 便捷更换
- 实现 `per_segment`/`reference_videos`/`negative_support` 特性位驱动（配合 book-06/07）；`dev.py workflows` 子命令 + `validate` 门禁；**演示性换模板版本**：注册表指向新模板+sha 记录→validate→dry-run→agent 用新版。

### 步骤 5：一致性收口 + 端到端
- `consistency_check` 增加注册表核对；跑 book-09 黄金路径（含一次"新增工作流仅改配置"的演示）。

---

## 6. 验收标准（可复现）

- [ ] **新增一种工作流（如 video_multi_scene）只改注册表+模板**：`dev.py workflows validate --all` 通过；`call_comfyui`/`refimage`/`prompts`/`h3_submit` 无需改码即可 `--stage video_multi_scene --dry-run` 通过；agent 对话中无需改 SYSTEM_MESSAGE 即知道它。
- [ ] **更换模板版本**：注册表 `swap` 指到新模板 → validate + dry-run 通过 → 后续提交用新版（sha 留痕，可回滚）。
- [ ] 禁用工作流：`disabled` 后工具立即拒绝并提示原因（含 dry-run）。
- [ ] 所有已注册工作流 `dry-run` 通过；注册表/pipeline/manifest/templates/工具描述一致性检查 0 问题。
- [ ] `refimage use --slot` 对 r2v（ref_images）与未来 ref_videos 工作流按注册表规格工作；flf2v first/last 语义来自注册表，不再硬编码文件名。
- [ ] SYSTEM_MESSAGE 不再包含硬编码阶段清单；digest 内容与注册表一致。

---

## 7. 风险与回滚
- **风险：注册表成为新单源，迁移期不一致**——保留 pipeline/manifest 兼容层 + `consistency_check` 核对；任何校验不通过即 fail-fast。
- **风险：模板结构差异导致槽位/注入点误判**——`template_health` 显式探针（节点存在/槽位可达/注入点可定位），失败给出可读错误而非静默错注入。
- **风险：模型滥用新工作流/参数**——enabled 门禁 + dry-run 校验 + 参数上限来自注册表；修改工具描述不放开权限。
- **回滚**：注册表为增量扩展；消费方改动均可单点回退（保留旧函数路径）；`dev.py workflows` 独立。

---

## 10. 实施记录（截至 2026-09-04）

### 步骤1 完成：注册表 schema + 适配器
- `config/capabilities.json`：4 个本地工作流补全 `stage/template/format/slots(role+count)/prompt_inject(node_type+widget_index)/params(resolutions·seconds·fps·steps·seed)/features(reference_videos·per_segment·audio·negative_support)/enabled`（事实来自模板结构扫描：t2v/i2v/flf2v 提示词节点 `4c314f31-…` widget0；r2v `PrimitiveStringMultiline` widget0；r2v 8×LoadImage、flf2v first+last、r2v audio=true）。
- 新增 `runs/h3/workflow_registry.py`：`load_registry/local_entries/resolve(兼容 stage·id·slot，禁用给原因)/enabled_stages/template_path/params_for/slot_spec/image_slot_count/template_health(模板存在·JSON·注入节点·槽位数)/validate_all/digest_entries(agent 动态认知文本)`。
- 单测 `runs/h3/tests/test_workflow_registry.py` 10 用例（真实模板健康 4/4、禁用/未知/云引擎拒绝、槽位不足探测等）；全量 113 用例全绿。
- 注：步骤1 未接入消费方（tools/refimage/prompts）——agent 无需重启，仍走旧路径（金丝雀：行为不变）。

### 步骤2 进行中（2026-09-05）
- **实测缺陷（用户报告）**：请求 720p/24fps/15s，产出 864×480/24fps/5.17s —— UI→API 在线转换保留模板默认值（ResolutionSelector 0.4MP=480p、时长表达式 5s），gp 参数从未写入转换后的节点（`substitute_api_workflow` 只替换字符串 token）。
- **修复**：`stage.apply_generation_params`（按 token_map 覆写 MiniMaxH3* width/height/length、BasicScheduler steps、CreateVideo fps）+ 3 个单测（全量 117 全绿）。
- **A 阶段完成**：① 参数注入 ffprobe 回归通过（1280×736/24fps/15.08s，用户已确认）；② `--stage` 校验走注册表（未知/禁用即拒）；③ refimage 模板路径走注册表（缺失回退）；④ **prompts 注入点按注册表 `inject_spec`**（class_prefix MiniMaxH3 + prompt/negative_prompt 直写，替代 basename 启发式；未命中回退启发式；单测 5 例，全量 122 全绿）。
- **A 阶段完成 ⑤**：tools.py CallComfyUI/BatchSubmit 的 stage/resolution enum 与描述改为**注册表派生**（`_derive_tool_enums` 纯函数 + `_apply_registry_derived_schema`；enabled 过滤；异常回退旧值；spark 实测 ENUM_DERIVE_OK）。
- **A 阶段完成 ⑥（修订边界）**：pipeline.json 是**机器配置**（两端各自维护，dev.py EXCLUDE），故不做自动合并——新增 `consistency_check.check_registry_vs_pipeline`：注册表启用工作流未在 pipeline 登记引擎参数 → ISSUES；pipeline 多出阶段 → NOTES（占位阶段除外）。实测问题 0。
- **待办**：⑦ 步骤3 动态认知（digest 注入 SYSTEM_MESSAGE + 05-workflows-registry.md）；⑧ 步骤4 `dev.py workflows` 子命令 + 步骤5 黄金路径回归。

---

## 8. 与其它册/红线的关系
- 与 book-06（提示词注入点按注册表定位）、book-07（批量/引擎契约、参考视频甜点项）强联动；与 book-01（模板/注册表校验纳入基座）、book-09（黄金路径）随行。
- 红线：不改 ComfyUI 服务/同事模板；不引入 api_* 云模板使用；不越过现有白名单安全边界。

---

## 9. 待用户输入 / 待定项
- 注册表「特性位」是否现在就为参考视频设计（还是待其从"甜点"移入正式后再补）——建议 schema 先行、实现后置。
- 是否允许 `dev.py workflows add` 带"自动探测模板槽位"（自动识别 LoadImage/slot）——建议 v1 先显式声明、v2 加探测。
- 系统提示词改"运行时注入 digest"对 ctx 预算的影响评估（digest 大小须计入 book-03/04 的上下文预算）。