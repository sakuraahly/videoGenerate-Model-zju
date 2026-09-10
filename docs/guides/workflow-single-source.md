# 工作流：唯一权威与自检（2026-09-10 统一）

> 一页说清：**引擎到底读哪个文件、改哪里、怎么确认**。历史上这里有三处同名不同内容的副本，
> 当天就因为改错目录白干了一轮。看完这页 + 跑一条命令即可确认。

## 1. 唯一权威：`workflows/remote_workflows/`

引擎读哪个目录**由 `config/pipeline.json` 的 `templates_dir` 决定**，当前值是：

```json
"templates_dir": "workflows/remote_workflows"
```

| stage | 实际使用的模板 | 说明 |
|---|---|---|
| `t2v` | **（内置生成器 `h3_t2v`）** | 不读模板文件，代码直接构建 API 工作流 |
| `i2v` | `video_minimax_h3_i2v.json` | UI 格式（含子图），引擎在线解组为 API |
| `r2v` | `video_minimax_h3_r2v.json` | 多参考图；含 `MiniMaxH3ReferenceToVideo` |
| `flf2v` | `video_minimax_h3_flf2v.json` | 本地双帧变体（非同事原件） |
| `finalize` | `video_minimax_h3_r2v_finalize.json` | r2v + 成品链一体（生成→H3Finalize→H3AsrCheck，31 节点），实跑验证过 |
| `rife` | `video_minimax_h3_r2v_rife_finalize.json` | r2v + RIFE 插帧 + 成品链（35 节点） |
| `restore` | `video_minimax_h3_r2v_restore_finalize.json` | r2v + 整脸修复 + RIFE + 成品链（36 节点） |

代码里第二处硬编码：`runs/h3/refimage.py::_stage_template()` → 参考图接线固定走 `workflows/remote_workflows/video_minimax_h3_<stage>.json`。

## 2. 目录怎么分的（2026-09-10 整理后）

```
workflows/remote_workflows/
├── video_minimax_h3_i2v.json             ← 在用（注册模板）
├── video_minimax_h3_r2v.json             ← 在用
├── video_minimax_h3_flf2v.json           ← 在用
├── video_minimax_h3_r2v_finalize.json    ← 在用（stage finalize）
├── video_minimax_h3_r2v_rife_finalize.json    ← 在用（stage rife）
├── video_minimax_h3_r2v_restore_finalize.json ← 在用（stage restore）
├── video_h3_t2v_builtin.json             ← 在用（stage t2v_ui：内置 T2V 的可视化孪生）
├── archive/                              ← 归档：不在用，引擎不会读
│   ├── api_minimax_h3_{t2v,r2v,flf2v}.json   （Comfy 云通道模板）
│   ├── video_minimax_h3_t2v.json             （同事的 t2v 原件，被内置生成器取代）
│   ├── h3_finalize_chain.json                （成品链片段，不是完整工作流）
│   ├── sd_inpaint_fix.json                   （重绘修补）
│   └── originals/                            ← 同事原件（sync 脚本的落点，仅对照）
└── （根目录不再放任何未注册文件——审计会检查这一点）
```

- **根目录＝在用**：只有注册模板；`python runs/h3/workflow_audit.py` 会报「未注册模板: 无」；
- **`archive/`＝归档**（引擎不读，只有 `--template archive/xxx.json` 显式指定才会跑）；
- **`archive/originals/`＝同事原件**（`bats/workflow/sync_remote_workflows.bat` 的落点）；
- **`config/templates/`＝废弃**（历史副本树，引擎不读，目录里有 `README.md`，`modify_workflow` 已禁止写入）；
- 命名提醒：`api_*` 是「Comfy 云通道」的命名约定，**不代表 API 格式**——那几个文件其实是 UI 格式。

### 2.1 内置生成器 ↔ UI 模板（`t2v` / `t2v_ui`）

| stage | 走什么 | 何时用 |
|---|---|---|
| `t2v` | **内置生成器**（代码现场拼 15 节点 API 流） | 默认；**快且离线可用**（不依赖 ComfyUI 在线） |
| `t2v_ui` | 读 `video_h3_t2v_builtin.json`（UI 格式） | 想在 ComfyUI 里**打开/修改**内置 T2V 的默认参数时 |

两者产出的工作流是同一套节点（UNETLoader/CLIPLoader/VAELoader×2/MiniMaxH3ImageToVideo/BasicGuider/
KSamplerSelect/BasicScheduler/RandomNoise/SamplerCustomAdvanced/VAEDecode/VAEDecodeAudio/CreateVideo/SaveVideo）；
`t2v_ui` 在模板不可用或转换失败时会**自动回退**到内置生成器。

重新导出这份 UI 模板（改了内置生成器参数后）：

```bash
# 必须在能访问 ComfyUI /object_info 的机器上跑（如 spark）
python3 runs/h3/export_ui_template.py --builtin-t2v \
    --out workflows/remote_workflows/video_h3_t2v_builtin.json
```

> 为什么需要专门工具：`workflow.py::workflow_to_ui()` 只保证连线正确，widget 值沿用构建顺序；
> 而引擎的 UI→API 转换器**严格按 object_info 声明顺序**消费 widget 值，顺序不对就会报
> 「有 N 个 widget 值无法按定义分配」并回退。`export_ui_template.py` 按同一套规则反向生成，
> 因此导出后引擎能原样读回（实测：dry-run 显示「工作流来源: 模板文件」，实跑出片 608×352）。

## 3. 改工作流的正确流程

```bash
# 1) 改镜像目录（唯一权威）
#    workflows/remote_workflows/video_minimax_h3_xxx.json
# 2) 推到 spark（引擎在那里跑）
bats\workflow\sync_to_spark.bat
# 3) 自检：确认每个 stage 用哪份、sha1、有没有缺失
python runs/h3/workflow_audit.py
```

## 4. 自检命令（只读，不改任何东西）

```
python runs/h3/workflow_audit.py          # 人看的表
python runs/h3/workflow_audit.py --json   # 机器可读
```

输出四段：① 各 stage 的实际模板（是否存在 / sha1 / 节点数 / 格式）；② 未注册模板清单；
③ 废弃目录与镜像同名文件的差异；④ 体检结论。**任何一个 stage 指向的模板缺失时退出码为 1**（脚本/CI 可直接用）。

## 5. 红线与坑

- spark 同事原件 `~/ai/ComfyUI/user/default/workflows/` **永不修改**；
- `bats/workflow/sync_remote_workflows.bat` 是**用同事原件覆盖镜像**的脚本——镜像里装的是我们改造过的版本
  （book-06：删内嵌故事、注入属性词模板）；直接跑会冲掉改造，**先 `git status` / `git diff` 或先备份**。
  它只该用于「取回原件做对照」，不该在改完工作流之后随手跑；
- `pipeline.json` 不入库（本机配置），入库的是 `config/pipeline.example.json`——**改示例后必须保证是合法 JSON**，
  它是别人复制成真实配置的入口（2026-09-10 曾因备注写在字符串外而变成非法 JSON，现已由测试拦住）；
- 死配置要清：曾存在 `character` / `keyframes` 两个 stage 指向从未放入的 `api_sdxl_*.json`；
  现已移除（需要文生图请直接用 `runs/h3_text2img.py`）。

## 6. 相关文档

- 注册表（自动生成）：`docs/agent-reading/05-workflows-registry.md`（源 `config/capabilities.json`）
- 手动跑 6 个工作流：`docs/guides/manual-use-6-workflows.md`
- 提示词与模板契约：`docs/guides/workflow-and-prompt.md`
- 计划书里当初的改造清单：`docs/planbook/book-06-phase5-workflow-prompts.md`
