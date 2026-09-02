# MiniMax H3 视频生成 — 用户指南（User Guide）

> 适用人群：直接操作这台 Windows 机器的“使用者/小白”，以及需要调用该工具的 AI 智能体。
> 本文讲“怎么用”；想了解内部架构/如何扩展请看 `docs/robustness-and-modularity.md`。

---

## 0. 一句话说明

本项目 = 一台装有 ComfyUI + MiniMax H3 的远程主机（ssh 别名 `spark`）+ 本地一套
自动化脚本。你只需要 **双击 .bat 选菜单**，脚本会依次完成：检查远程 → 建隧道 →
提交任务 → 等结果 → 把视频下载到本地 `outputs\`。

---

## 1. 常用入口（双击即可）

| 入口 | 作用 |
|---|---|
| **`menu.bat`** | ★ 主控台：立即 / 定时 / 延迟生成、改参数、环境检查、工作流工具 |
| **`run.bat`** | 极简：立即按当前参数生成一个视频（等进度请保留窗口） |
| **`edit.bat`** | 改参数（分辨率/时长），改完存到 `parameters\video.txt` |
| **`workflow_setup.bat`** | 设置“上传目录(绝对路径)”与“生成时直接使用某已存工作流” |
| **`pipeline_setup.bat`** | 多工作流/阶段设置：默认阶段、模板状态、dry-run 校验 |

`menu.bat` 菜单：
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
| `parameters/video.txt` | 每次任务的参数：`resolution`、`seconds`；可选 `seed`(整数或 auto)、`fps`、`steps`、`timeout` | `edit.bat`（小白）或文本编辑 |
| `config/environment.json` | 远程主机/端口/重试次数/超时 | 换机器时手动编辑 |
| `config/pipeline.json` | 阶段注册表 + 默认阶段 + spark 远程模板路径记录 | `pipeline_setup.bat` |
| `config/transfer.json` | 工作流上传远程目录 + “使用指定工作流” | `workflow_setup.bat` |
| `config/minimax_h3_models.json` | 远程 4 个基础模型的清单（大小/SHA-256） | 一般不动 |
| `prompts\positive_prompts.txt` / `negative_prompts.txt` | 正/负提示词 | 文本编辑 |
| `config/templates/` | 本地模板文件（api 用、留档用） | 放文件即可 |

**分辨率预设**：`360p`(最低) → `480p` → `540p` → `720p` → `768p`(上限)。
**时长建议**：5–15 秒；内部帧数按 H3 的 17k+5 网格自动取整。

---

## 3. 常见流程

### 3.1 立即生成
双击 `menu.bat` → `[1]`；或直接双击 `run.bat`。等待窗口出现“全部完成”。

### 3.2 定时 / 延迟生成
`menu.bat` → `[2]`（输入时刻）或 `[3]`（输入分钟）。
脚本会先做**预检**（本地文件、ssh 可达、远程 4 个模型就位），预检不通过会立即报错，
不会让你白等；预检通过后倒计时（每 60s 显示剩余），到点自动执行。

### 3.3 改参数
`menu.bat` → `[4]`（等价 `edit.bat`）→ 选择分辨率、输入秒数。

### 3.4 断网/中断后恢复（断点重连）
任务提交后会把 `prompt_id` 写入项目根 `last_job.json`（瞬态文件，成功后自动清除）。
如果中途断网/服务器断开：
- 隧道会尝试自动重建并重试（默认 3 次）；
- 仍失败则**保留断点**，网络恢复后再双击 `run.bat`（或 menu `[1]`）即自动
  `--resume` 原任务，**不会重复生成**；
- 下载失败同样保留断点，重跑会直接续传下载。

### 3.5 环境与模型检查 / 补模型
`menu.bat` → `[5]`：检查本地依赖、ssh 连通、ComfyUI 进程、远程 4 个基础模型；
模型缺失/损坏时可选择**自动下载**（远程 `curl -fL -C -` 断点续传），只下载
清单里的 4 个文件，不整仓下载。

### 3.6 把工作流上传到 spark / 用指定工作流生成
`menu.bat` → `[6]`（等价 `workflow_setup.bat`）：
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
- 阶段清单与默认阶段在 `config/pipeline.json`（可用 `pipeline_setup.bat` 查看/修改/校验）。

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
- 引擎已支持把 ComfyUI **UI 模板在线转换为可提交的扁平 API**（`--template`/`--stage`
  遇到 UI 文件时自动转换，需在线 ComfyUI 提供节点定义）——转换结果经 `/prompt`
  校验通过，能进入执行；
- 你 spark 上那 6 份工作流请以**你这台 ComfyUI 实例的实际行为为准**：GUI 打开运行最直接；
  若节点（如 `MinimaxHailuo03*`）在执行时报 `Unauthorized`，是该节点插件的登录要求，
  与本程序无关；本地模型首选 `video_*`/内置 t2v；
- 模板缺失/不可转换：有内置生成器就提示并回退内置，无内置才确定性报错。

**6 份工作流（spark 上）分类**：
| 文件 | 节点 | 建议用法 |
|---|---|---|
| `api_minimax_h3_{t2v,r2v,flf2v}.json` | `MinimaxHailuo03*` 封装节点 | GUI 打开即用；若报登录则先在其 ComfyUI 登录；CLI 可 dry-run/转换 |
| `video_minimax_h3_r2v.json` | 本地 H3 开放图（`MiniMaxH3ReferenceToVideo` + UNET/VAE…） | ✅ GUI 或本程序 CLI（UI→API）本地跑；需参考图 |
| `video_minimax_h3_t2v.json` / `video_minimax_h3_i2v.json` | 本地 H3 但子图(UUID)封装 | GUI 打开即用（CLI 解组为 TODO） |

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
- 端到端：`menu.bat` → `[5]` 环境检查 → `[1]` 生成一条 360p/5s 的冒烟任务最快。

---

## 7. 相关文档地图

| 文档 | 内容 |
|---|---|
| `docs/manual-use-6-workflows.md` | ★ 6 个工作流逐文件手动使用步骤（GUI + 脚本） |
| `docs/robustness-and-modularity.md` | 架构、模块职责、断点/隧道机制、测试、如何扩展 |
| `docs/user-guide.md`（本文） | 面向使用者的操作指南 |
| `docs/h3-manual-operations.md` | 底层手工 ssh 操作（自动化出现前的流程，保留作参考） |
| `docs/h3-troubleshooting.md` | 常见报错排查 |
| `docs/comfyui-startup-and-access.md` | 远程 ComfyUI 启动/访问/隧道 |
| `docs/long-term-maintenance.md` | 日志、清理、长期维护 |
| `skills/h3-video-generation.md` | 智能体技能卡（怎么做一次生成） |
| `skills/h3-prompt-engineering.md` | 提示词工程规则 |
