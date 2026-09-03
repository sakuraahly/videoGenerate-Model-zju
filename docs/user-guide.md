# MiniMax H3 视频生成 — 用户指南（User Guide）

> 适用人群：直接操作这台 Windows 机器的“使用者/小白”，以及需要调用该工具的 AI 智能体。
> 本文讲“怎么用”；想了解内部架构/如何扩展请看 `docs/robustness-and-modularity.md`。
> ⭐ **第一次上手请先看 `docs/quickstart.md`（新手三步走 + 模板/参考图选择）**，本文是完整参考。

---

## 0. 一句话说明

本项目 = 一台装有 ComfyUI + MiniMax H3 的远程主机（ssh 别名 `spark`）+ 本地一套
自动化脚本。你只需要 **双击 .bat 选菜单**，脚本会依次完成：检查远程 → 建隧道 →
提交任务 → 等结果 → 把视频下载到本地 `outputs\`。

---

## 1. 常用入口（双击即可）

| 入口 | 作用 |
|---|---|
| **`bats\generate\menu.bat`** | ★ 主控台：立即 / 定时 / 延迟生成、改参数、环境检查、工作流工具 |
| **`bats\generate\run.bat`** | 极简：立即按当前参数生成一个视频（等进度请保留窗口） |
| **`bats\config\edit.bat`** | 改参数（分辨率/时长），改完存到 `parameters\video.txt` |
| **`bats\workflow\workflow_setup.bat`** | 设置“上传目录(绝对路径)”与“生成时直接使用某已存工作流” |
| **`bats\workflow\pipeline_setup.bat`** | 多工作流/阶段设置：默认阶段、模板状态、dry-run 校验 |

`bats\generate\menu.bat` 菜单：
```
[1] 立即生成视频
[2] 定时生成（24 小时制 HH:MM，如 21:30；已过自动顺延到明天）
[3] 延迟生成（N 分钟后自动开始）
[4] 修改生成参数（分辨率/时长）
[5] 环境与远程模型检查（可自动下载缺失模型）
[6] 工作流上传 / 使用指定工作流
[7] 退出
```

生成完成后视频保存在 `outputs\video_N.mp4`（自动递增、不覆盖），同时在
`workflows\h3_<时间戳>_<毫秒>\` 留下本次的 `workflow_api.json`（可再次提交）、
`workflow_ui.json`（含完整连线，可拖进 ComfyUI 界面查看/微调）与 `job.json`（审计记录）。

---

## 2. 配置文件一览

| 文件 | 说明 | 常用修改方式 |
|---|---|---|
| `parameters/video.txt` | 每次任务的参数：`resolution`、`seconds`；可选 `seed`(整数或 auto)、`fps`、`steps`、`timeout` | `bats\config\edit.bat`（小白）或文本编辑 |
| `config/environment.json` | 远程主机/端口/重试次数/超时 | 换机器时手动编辑 |
| `config/pipeline.json` | 阶段注册表 + 默认阶段 + spark 远程模板路径记录 | `bats\workflow\pipeline_setup.bat` |
| `config/transfer.json` | 工作流上传远程目录 + “使用指定工作流” | `bats\workflow\workflow_setup.bat` |
| `config/minimax_h3_models.json` | 远程 4 个基础模型的清单（大小/SHA-256） | 一般不动 |
| `prompts\positive_prompts.txt` / `negative_prompts.txt` | 正/负提示词 | 文本编辑 |
| `config/templates/` | 本地模板文件（api 用、留档用） | 放文件即可 |

**分辨率预设**：`360p`(最低) → `480p` → `540p` → `720p` → `768p`(上限)。
**时长建议**：5–15 秒；内部帧数按 H3 的 17k+5 网格自动取整。

---

## 3. 常见流程

### 3.1 立即生成
双击 `bats\generate\menu.bat` → `[1]`；或直接双击 `bats\generate\run.bat`。等待窗口出现“全部完成”。

### 3.2 定时 / 延迟生成
`bats\generate\menu.bat` → `[2]`（输入时刻）或 `[3]`（输入分钟）。
脚本会先做**预检**（本地文件、ssh 可达、远程 4 个模型就位），预检不通过会立即报错，
不会让你白等；预检通过后倒计时（每 60s 显示剩余），到点自动执行。

### 3.3 改参数
`bats\generate\menu.bat` → `[4]`（等价 `bats\config\edit.bat`）→ 选择分辨率、输入秒数。

### 3.4 断网/中断后恢复（断点重连）
任务提交后会把 `prompt_id` 写入项目根 `last_job.json`（瞬态文件，成功后自动清除）。
如果中途断网/服务器断开：
- 隧道会尝试自动重建并重试（默认 3 次）；
- 仍失败则**保留断点**，网络恢复后再双击 `bats\generate\run.bat`（或 menu `[1]`）即自动
  `--resume` 原任务，**不会重复生成**；
- 下载失败同样保留断点，重跑会直接续传下载。

### 3.5 环境与模型检查 / 补模型
`bats\generate\menu.bat` → `[5]`：检查本地依赖、ssh 连通、ComfyUI 进程、远程 4 个基础模型；
模型缺失/损坏时可选择**自动下载**（远程 `curl -fL -C -` 断点续传），只下载
清单里的 4 个文件，不整仓下载。

### 3.6 把工作流上传到 spark / 用指定工作流生成
`bats\generate\menu.bat` → `[6]`（等价 `bats\workflow\workflow_setup.bat`）：
1. 设置 spark 上的**绝对上传目录**（如 `/home/<用户名>/ai/ComfyUI/user/default/workflows`，以 `/` 开头）；
2. 选择本地某次保存的工作流为“激活”，并可开启**生成时直接使用该工作流**；
3. 立即上传某个工作流（`workflow_api.json` / `workflow_ui.json`）。

> 开启“使用指定工作流”后，生成时跳过提示词/参数解析，用所选工作流原样提交
> （内部 `--workflow-file`）。此后每次正常动态生成保存的工作流也会自动按配置
> 上传到远程目录（失败仅警告，不影响出片）。

---

## 4. 多工作流配合（阶段 / 流水线）

针对“文字→SDXL→角色图 → 关键帧 → H3 Ref2VA→片段 → ffmpeg 成片”这类
**多工作流配合**场景，脚本提供“阶段（stage）”机制：

- 默认阶段 `t2v` = 老行为（内置 H3 文生视频），双击入口不受影响；
- 阶段清单与默认阶段在 `config/pipeline.json`（可用 `bats\workflow\pipeline_setup.bat` 查看/修改/校验）。

命令行示例（给智能体 / 高级用户）：
```
python runs\h3_submit.py --stage t2v --prompt "…"                    # 内置 T2V（360p 等参数来自 parameters\video.txt）
python runs\h3_submit.py --stage r2v --image 角色图.png --image 场景图.png
python runs\h3_submit.py --stage flf2v --image 首帧.png --image 末帧.png
python runs\h3_submit.py --template path\to\api.json --prompt "…"    # 任意扁平 API 模板 + {{占位符}}
python runs\h3_submit.py --workflow-file workflows\h3_xxx\workflow_api.json
python runs\h3_submit.py --dry-run --stage r2v --image a.png          # 只预览不提交不上传
```

模板占位符（写进 API 模板字符串即可被自动替换）：
`{{prompt}} {{negative_prompt}} {{seed}} {{width}} {{height}} {{seconds}} {{length}} {{fps}} {{steps}}`
以及输入图 `{{image0}} {{image1}} …`（运行时会先上传本地图，再填入远端文件名）。

**模板可用性（重要）**：
- 引擎支持把 ComfyUI **UI 模板自动解组 + 在线转换**为可提交扁平 API（`--template`/`--stage`
  遇到 UI/子图文件时自动处理，需在线 ComfyUI 提供节点定义）——video_* 四份已实测出片；
- **6 份同事工作流分两类**：`video_*`=本地 H3 推理（spark GPU，推荐；t2v/i2v/r2v/flf2v 全可用）；
  `api_*`=**Comfy 云模板**（comfy_api_nodes 的 MinimaxHailuo03* 经 Comfy 云代理 MiniMax 官方
  API，GUI 报 `Unauthorized` = 需登录 Comfy 账号，与本地框架无关；本地同语义用 video_*）；
- 模板缺失/不可转换：有内置生成器就提示并回退内置，无内置才确定性报错。

**工作流清单（本地镜像）分类**：
| 文件 | 用途 | 执行 | 建议用法 |
|---|---|---|---|
| `video_minimax_h3_t2v.json` | 文生视频（官方标准模板） | 本地 H3 | ✅ CLI `--stage t2v` / GUI；已实跑出片 |
| `video_minimax_h3_i2v.json` | 图生视频（首帧图动起来） | 本地 H3（子图自动解组） | ✅ CLI `--stage i2v` / GUI；已实跑出片 |
| `video_minimax_h3_r2v.json` | 多参考图（角色/场景，保证连贯） | 本地 H3 开放图 | ✅ CLI `--stage r2v` / GUI；已实跑出片 |
| `video_minimax_h3_flf2v.json` | 首帧+末帧（本地双帧，本地扩展） | 本地 H3 | ✅ CLI `--stage flf2v`；已实跑出片 |
| `api_minimax_h3_t2v.json` | **T2V 的 API 格式**（扁平、无 subgraph 坑，命令行更稳） | **Comfy 云**（Hailuo API，需登录） | 登录后可用作 CLI 内核；未登录 `Unauthorized` |
| `api_minimax_h3_r2v.json` | **R2V 的 API 格式**（团队《于勒》15 镜内核） | 同上 | 同上 |
| `api_minimax_h3_flf2v.json` | 首帧+末帧（锁定起止更精确）；**示例图需自备** | 同上 | 同上 |

> 📖 **逐文件手动使用步骤（GUI + 脚本两种方式）请看：
> `docs/manual-use-6-workflows.md`**。

**运行日志**：每次执行在 `logs\run_<时间戳>.log` 生成一份日志（PowerShell 步骤 +
Python 事件写同一文件，文件路径在运行时窗口/日志首行显示）；`logs/` 已 gitignore，
可随时删除。

---

## 5. 退出码与关键提示（给脚本/智能体）

Python CLI 退出码契约：`0` 成功并已打印 `REMOTE_VIDEO_PATH: <远程路径>`；
`2` 可恢复（网络/超时，断点保留）；`3` 确定性失败（参数错/任务被拒/执行失败）；
`90` 内部错误。机器可读标记行：`REMOTE_VIDEO_PATH:`（下载用）、
`WORKFLOW_SAVED_DIR:`（本次工作流目录，配合自动上传）。

---

## 6. 自检与测试（给维护者）

- Python 单测（无需网络）：`python -m unittest discover -s runs/h3/tests -p "test_*.py" -v`
- PowerShell 库：全部 `.ps1` 可用 `Parser.ParseFile` 做语法校验。
- 端到端：`bats\generate\menu.bat` → `[5]` 环境检查 → `[1]` 生成一条 360p/5s 的冒烟任务最快。

---

## 7. 相关文档地图

| 文档 | 内容 |
|---|---|
| `docs/quickstart.md` | ⭐ 新手快速上手（三步出第一条视频 + 模板/参考图选择） |
| `docs/session-summary.md` | ★ 会话交接总结（给新对话看，含待办） |
| `docs/manual-use-6-workflows.md` | ★ 6 个工作流逐文件手动使用步骤（GUI + 脚本） |
| `docs/robustness-and-modularity.md` | 架构、模块职责、断点/隧道机制、测试、如何扩展 |
| `docs/user-guide.md`（本文） | 面向使用者的操作指南 |
| `docs/h3-manual-operations.md` | 底层手工 ssh 操作（自动化出现前的流程，保留作参考） |
| `docs/h3-troubleshooting.md` | 常见报错排查 |
| `docs/comfyui-startup-and-access.md` | 远程 ComfyUI 启动/访问/隧道 |
| `docs/long-term-maintenance.md` | 日志、清理、长期维护 |
| `skills/h3-video-generation.md` | 智能体技能卡（怎么做一次生成） |
| `skills/h3-prompt-engineering.md` | 提示词工程规则 |

---

## 8. 本轮：工作流镜像 + 按工作流提示词 + AI 创意桥

- **本地工作流镜像**：`workflows/remote_workflows/`（先双击 `bats\workflow\sync_remote_workflows.bat`
  从 spark 同步；此后引擎使用/修改的都是这些本地文件）。`config/pipeline.json` 的
  `templates_dir` 已指向镜像。
- **按工作流提示词**：`prompts/manifest.json` 把 6 个工作流映射到槽位
  `prompts/workflows/<槽>.positive/.negative.txt`；文件为空＝回退默认
  `prompts/positive_prompts.txt`。运行任一工作流（`--template`/`--stage`）时引擎会
  **自动用本地槽位提示词覆盖工作流内嵌 prompt**（优先级：CLI > 槽位 > 阶段默认 > 默认）。
- **快捷编辑**：双击 `bats\prompts\prompts.bat`（列出/记事本打开各槽提示词；可复制 default 起步）。
- **AI 创意桥（最终形态的入口）**：双击 `bats\prompts\ai_prompts.bat` → 输入一段创意 →
  `runs/h3/idea2prompts.py` 调用 `config/llm.json` 里的通用模型，为 default + 各工作流槽位
  （video t2v/i2v/r2v/flf2v、api t2v/r2v/flf2v）生成 `{positive, negative}` 并写入槽位文件。
  未配好 AI 时可用 `python runs\h3\idea2prompts.py --idea "你的创意" --dry-run` 预览计划；
  本地模型配置模板：`config/llm.spark-qwen3.example.json`（公网示例 `llm.example.json`）。
- 校验：PowerShell 全部 ps1 语法通过；Python 单测通过（含槽位/注入/创意工具相关）。
