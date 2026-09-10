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

## 2. 三类文件，别搞混

1. **注册模板**（上表 4 个）——引擎会按 stage 自动使用；
2. **未注册模板**——放在同一目录但没有任何 stage 引用，**引擎不会自动用**，只有 GUI 手动打开或
   `--template <路径>` 显式指定才会跑。当前包括：
   `h3_finalize_chain.json`（H3Finalize→H3AsrCheck 成品链**片段**，不是完整工作流）、
   `sd_inpaint_fix.json`（重绘修补）、`video_minimax_h3_t2v.json`（t2v 走内置生成器，故未注册）、
   `api_minimax_h3_*.json`（Comfy 云节点模板）；
   > 命名提醒：`api_*` 是「Comfy 云通道」的命名约定，**不代表 API 格式**——这三个文件其实是 **UI 格式**
   > （审计命令会把每个文件的真实格式列出来）。
   >
   > 2026-09-10 起，三份成品链模板（`..._finalize` / `..._rife_finalize` / `..._restore_finalize`）
   > **已注册为 stage**：`finalize` / `rife` / `restore`（实跑验证：`--stage finalize` 出片 608×352/4.46s ✔）。
3. **废弃目录 `config/templates/`**——历史副本树，**引擎不读**，内容已与镜像分叉。目录里放了 `README.md` 说明，
   并且 `modify_workflow` 工具**已不允许**再往那里写。

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
