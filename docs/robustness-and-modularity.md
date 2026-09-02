# 健壮性与模块化设计（Robustness & Modularity）

本文件说明“一键生成视频”工具链当前的分层结构、可靠性机制，以及后续如何
低成本地新增功能。目标是：**任何一处修改都不需要动到另一层的核心逻辑**。

---

## 1. 分层结构

```
项目根/
├── run.bat                      # 小白入口（双击，原样保留：立即生成）
├── edit.bat                     # 小白改参数（原样保留，只写 resolution/seconds）
├── menu.bat                     # ★ 统一入口（双击）：立即/定时/延迟/改参/检查/工作流工具
├── workflow_setup.bat           # ★ 工作流工具入口：设置 spark 上传目录 / 指定生成用工作流
├── pipeline_setup.bat           # ★ 流水线/多工作流设置：默认阶段、模板状态、dry-run 校验
├── config/environment.json      # 环境级配置（远程主机/端口/重试/超时）
├── config/minimax_h3_models.json# 远程 4 个基础模型清单（modelscope 前缀/大小/SHA-256）
├── config/transfer.json         # 工作流上传目录(绝对路径) + 激活工作流设置
├── config/pipeline.json         # 多工作流阶段注册表 + 默认阶段 + 远程模板路径记录
├── config/templates/            # 本地模板目录（含从 spark 拉取的官方模板留档；注意官方 api_* 实为 UI 格式）
├── parameters/video.txt         # 每次任务的生成参数（key=value，# 注释）
├── prompts/positive_prompts.txt # 正向提示词
├── prompts/negative_prompts.txt # 负向提示词（缺失时自动按“空”继续，不阻断）
├── outputs/                     # 生成视频（video_N.mp4 自动递增）
├── logs/                        # 每次运行日志 run_<时间戳>.log（PS 步骤 + Python 事件）
├── workflows/h3_<时间戳>_<毫秒>/  # 每次提交的工作流（api+ui，ui 含完整连线）
├── runs/                        # Python 侧（模块化包）
│   ├── h3_submit.py             #   薄 CLI 编排入口（--workflow-file 可提交已存工作流）
│   └── h3/
│       ├── params.py            #   参数解析/校验/归一化 + 环境配置读取
│       ├── workflow.py          #   预设/帧数/工作流构建与落盘（UI 转 LiteGraph 连线格式）
│       ├── templates.py         #   模板读取/校验 + {{占位符}} 递归替换 + 残留检测
│       ├── uiapi.py             #   UI(节点图)→扁平API 在线转换（官方模板可用化）
│       ├── stage.py             #   流水线阶段注册表/默认阶段/输入解析
│       ├── comfy.py             #   ComfyUI API 客户端（重试/轮询/上传图/输出解析）
│       ├── jobstate.py          #   断点状态 + 每任务审计记录（原子写）
│       └── tests/test_h3.py     #   单元测试（unittest，纯标准库）
└── shell/                       # PowerShell 侧（模块化）
    ├── console_menu.ps1         #   交互主菜单（中文 UI，被 menu.bat 启动）
    ├── generate_video.ps1       #   编排入口（不写业务细节）
    ├── run_scheduled.ps1        #   定时/延迟：预检 → 倒计时 → 执行 generate_video
    ├── check_environment.ps1    #   环境+远程模型检查（可交互自动下载）
    ├── transfer_setup.ps1       #   工作流上传/使用设置（被 workflow_setup.bat 启动）
    ├── pipeline_setup.ps1       #   流水线默认阶段/模板状态/校验（被 pipeline_setup.bat 启动）
    └── lib/
        ├── utils.ps1            #   日志/键值与 JSON 读取/探活/单实例锁
        ├── state.ps1            #   断点状态读取与清理
        ├── remote.ps1           #   远程 ComfyUI 检查/启动
        ├── tunnel.ps1           #   SSH 隧道生命周期（复用/自愈/换端口）
        ├── preflight.ps1        #   本地文件/依赖、远程连通、模型清单检查与补货
        ├── scheduler.ps1        #   HH:MM 解析、剩余时间格式化、倒计时
        └── transfer.ps1         #   transfer.json 读写 + scp 上传 + 激活工作流解析
```

原则：
- **单一事实源**：环境配置只维护 `config/environment.json`（PS 与 Py 各自读取）；
  生成参数只由 Python 解析 `parameters/video.txt`（PS 仅做展示性提示）；
  阶段/模板注册表维护在 `config/pipeline.json`。
- **单向依赖**：PS 编排层 → Python CLI → h3 包内各模块；模块之间不互相调用编排层。
- **接口即契约**：跨层只通过「命令行参数」「stdout 标记行
  `REMOTE_VIDEO_PATH: <path>` / `WORKFLOW_SAVED_DIR: <目录>`」「退出码」
  「last_job.json」四样东西通信。

---

## 2. 退出码契约（Python）

| 退出码 | 含义 | 外层行为 |
|---|---|---|
| 0  | 成功并已定位远程输出（打印 `REMOTE_VIDEO_PATH:`） | 下载 |
| 2  | 可恢复失败（网络中断/轮询超时），断点保留 | 重建隧道重试 / 保留下次续传 |
| 3  | 确定性失败（参数错误、任务被 ComfyUI 拒绝/执行失败） | 不重试，报错停止 |
| 90 | 未预期的内部错误 | 按确定性失败处理（打印 traceback） |

> 命令行“用法错误”（如非法 resolution）也归一化为 3，避免被外层误判为
> “可恢复”而反复重试。

---

## 3. 断点与资源可靠性

### 3.1 断点状态机（项目根 `last_job.json`，gitignore 已忽略）

```
提交成功 ──写入 {prompt_id}──────────────┐
        │ 轮询/网络中断(exit 2)          │
        └──► 断点保留；重跑 run.bat ──► 自动 --resume 原任务（不重复生成）
定位到输出 ──补写 {remote_path} ──────────┘
        │ 下载失败
        └──► 断点保留；重跑 run.bat ──► 直接 scp 续传（不再跑 Python）
下载成功 ──清除断点
任务执行失败(exit 3) ──由 Python 清除断点
```

- 旧版纯文本 `last_prompt_id.txt` 仍可被读取并自动迁移到 JSON 后删除。
- 所有 JSON 写入采用“临时文件 + rename”的原子写，进程被杀不会留半截文件。

### 3.2 隧道（shell/lib/tunnel.ps1）

- 本地已有可用端点（ComfyUI /system_stats 200）→ **直接复用**，不重复建隧道；
- 只清理**自己记录过 PID** 的隧道（`.tunnel.json`），绝不误杀用户其他 ssh；
- 端口被占用 / 转发失败 → 自动尝试后续 19 个端口（最多启动 5 次）；
- `ExitOnForwardFailure=yes`：转发失败立即退出，不会“假活”。

### 3.3 单实例锁（`.run.lock`）

`run.bat` 被误双击多次时，只有第一个进程能获得独占文件句柄；其余进程直接报错
退出。句柄由 OS 在进程退出/崩溃时自动释放，不存在“僵尸锁”。

### 3.4 Python 请求层（runs/h3/comfy.py）

- 连接类错误：指数退避 + 随机抖动重试（默认 3 次），避免“隧道刚恢复瞬间多路齐冲”；
- HTTP 4xx/5xx（确定性拒绝）不重试，直接抛 `ComfyRejected`；
- 轮询间隔自适应增长 5s→30s，长时间生成时显著降低对服务器与隧道的请求压力；
- 输出解析兼容 `images/gifs/video/files/audio` 等不同键名，并做兜底遍历；
- `upload_image()`：i2v/r2v/flf2v 等输入图通过 `/upload/image` 上传并回填模板占位符。

### 3.5 运行日志

- `utils.ps1::Initialize-RunLog` 在 `logs\run_<时间戳>.log` 建日志；`Write-Info /
  Write-Warn / Write-ErrorExit` 同时写日志与屏幕。
- Python CLI 通过环境变量 `H3_LOG_FILE`（由 generate_video.ps1 注入）把
  submit/resume/interrupted/timed_out/task_error/completed 等关键事件写进同一文件。
- `logs/` 已 gitignore。

---

## 4. 边界与极限防护（已落地）

| 场景 | 处理 |
|---|---|
| 参数文件缺失/损坏/空 | 确定性报错或回退默认值（Python 为准） |
| 分辨率非法、宽高非 8 倍数 | 确定性报错，列出可用预设 |
| seconds 为 0/负数/非数字/超上限 | 边界校验（0.1~600s），超 60s 给出长视频警告 |
| 帧数换算 | 恒落入 H3 的 17k+5 网格，任意输入可被模型接受 |
| 提示词文件为空/缺失 | 正向：报错；负向：自动按“空”继续并提示 |
| 中途断网/服务器断开 | 隧道自愈 + `--resume` 续传，不重复生成 |
| 端口被占用 | 自动换端口，并把实际地址通过 `COMFYUI_URL` 注入 Python |
| 下载半截/空文件 | scp 重试 + 大小校验，失败保留断点下次直接续传 |
| 同一秒重复运行 | 任务文件夹名带毫秒；另有运行锁防并发 |
| 状态文件损坏 | 按“无断点”容错处理（仅提示） |

---

## 5. 测试

Python（无需网络，纯标准库）：

```
python -m unittest discover -s runs/h3/tests -p "test_*.py" -v
```

覆盖：帧数网格边界、分辨率预设、BOM/CRLF/大小写解析、越界参数、CLI 退出码、
工作流构建/UI 转换、输出文件解析、客户端重试语义（模拟断连/HTTP 拒绝）、
状态文件原子读写/损坏容错/旧版迁移、环境配置回退。

PowerShell 库函数通过 `Parser.ParseFile` 语法校验 + 开发期一次性功能自检
（键值解析、JSON 状态、探活、单实例锁等）验证；自检脚本不随仓库保留。

---

## 6. 使用：统一控制台与定时 / 延迟生成

双击项目根的 **`menu.bat`**（薄启动器）会进入中文交互控制台：

```
[1] 立即生成视频            -> shell/console_menu.ps1 -> generate_video.ps1
[2] 定时生成（HH:MM）       -> run_scheduled.ps1 -AtTime HH:MM
[3] 延迟生成（N 分钟）      -> run_scheduled.ps1 -DelayMinutes N
[4] 修改生成参数             -> edit.bat
[5] 环境与远程模型检查       -> check_environment.ps1（可自动下载缺失模型）
[6] 工作流上传/使用指定工作流 -> transfer_setup.ps1（同 workflow_setup.bat）
[7] 退出
```

- `run_scheduled.ps1` 先做**前置预检**（本地文件/依赖、`ssh spark` 连通性、
  远程 4 个基础模型是否就位），通过后才倒计时，避免“白等两小时最后才发现
  远程不可达/模型缺失”；倒计时期间保留窗口即可，到点自动执行完整流程。
- `config/minimax_h3_models.json` 记录了 4 个基础模型（modelscope 下载前缀、
  远程目标目录、约略大小、SHA-256）；[5] 环境检查会用一次 `ssh stat` 汇总
  远程模型状态，缺失时可选择自动下载（远程 `curl -fL -C -` 断点续传 + 重试），
  只下载这 4 个文件，不整仓下载。
- 定时时刻规则：24 小时制 `HH:MM`；若该时刻已过则自动顺延到明天。
- `run.bat` 仍保留为“立即生成”的极简快捷入口，行为不变。

---

## 7. 工作流文件（UI 含连线）与 scp 上传 / 使用指定工作流

### 7.1 workflow_ui.json 现在包含完整连线信息

`runs/h3/workflow.py::workflow_to_ui` 输出的 UI 文件采用 ComfyUI/LiteGraph
标准结构，可直接拖进 ComfyUI 加载并看到全部连线：

- 顶层 `links` 为数组格式 `[id, origin_id, origin_slot, target_id, target_slot, type]`；
- 节点 connectable 输入带 `link` 引用，输出带 `links` 引用；
- 节点输出槽位数根据实际引用自动推导（如 H3 主节点 2 输出、SaveVideo 0 输出）。

局限：widget 顺序来自本工具构建工作流时的写入顺序；若与节点类定义顺序不同，
载入后个别数值可能错位，连线不受影响，可手动核对（此问题不影响 API 格式提交）。

### 7.2 配置（config/transfer.json，由脚本维护，勿手改）

```json
{
  "remote_upload_dir": "/home/xxx/ai/ComfyUI/user/default/workflows",
  "active_workflow_dir": "workflows/h3_20260902_124954",
  "use_active_workflow": false
}
```

- `remote_upload_dir`：**spark 上的绝对路径**（必须以 `/` 开头，不允许 `~`），
  每次生成把新保存的 `workflow_api.json` / `workflow_ui.json`
  scp 到 `remote_upload_dir/<任务文件夹名>/`（自动 `mkdir -p`）。
- `active_workflow_dir` + `use_active_workflow`：开启后生成时不再解析提示词/参数，
  而是直接用该文件夹的 `workflow_api.json` 提交（内部走 Python `--workflow-file`），
  适合“复现/微调某次已保存工作流”。

### 7.3 操作入口

双击 **`workflow_setup.bat`**（或统一控制台 [6]）进入设置工具：
1. 设置 spark 绝对上传目录；
2. 从 `workflows/` 选择“生成时使用”的工作流（并开启/关闭该模式）；
3. 立即把某个本地工作流上传到远程目录（scp，含重试提示）；
4. 查看 / 切换开关 / 清除设置。

### 7.4 运行期行为

- Python 动态构建并保存工作流后打印标记行 `WORKFLOW_SAVED_DIR: <目录>`，
  PowerShell 编排层解析后自动按配置上传一次（失败仅警告，不阻断生成）。
- 开启“使用指定工作流”后，`generate_video.ps1` 会跳过提示词参数检查并传
  `--workflow-file`，其余断点/隧道/下载逻辑完全不变。

---

## 8. 如何扩展新功能（不破坏现有流程）

1. **新增分辨率预设**：改 `runs/h3/workflow.py` 的 `RESOLUTION_PRESETS`（Py 自动生效）；
   若希望 `edit.bat` 也提供选项，再同步改 `edit.bat` 菜单。
2. **新增每次任务参数（如 fps/steps/seed）**：在 `parameters/video.txt` 加一行
   `key=value`，在 `runs/h3/params.py` 的解析里读取校验，Python 端自动消费；
   未知键会被保留在 `GenParams.raw` 中供扩展使用，**不报错**。
3. **新增运行时开关（如“生成后自动打开”“静默模式”）**：加到
   `config/environment.json`（环境级）或作为 CLI 覆盖项加在 `h3_submit.py`。
4. **新增“历史列表/按 prompt_id 重下”**：直接读 `workflows/*/job.json`
   （每次提交都已记录参数、prompt_id、输出路径），无需改生成主链路。
5. **切换/新增生成模型（H3 → 其他）**：在 `runs/h3/workflow.py` 新增一个
   `build_xxx_workflow()`，CLI 增加 `--workflow-builder` 选择；comfy/jobstate
   层无需改动。
6. **换远程主机/改端口/调重试次数**：只编辑 `config/environment.json`。

---

## 9. 多工作流配合（流水线 / 阶段）与占位符

目标流水线（多工作流依次配合，全部由同一套 ComfyUI/远程引擎驱动）：

```
[文字描述]→SDXL→人物形象图 → SDXL+IP-Adapter→分镜关键帧 →
[人物图+分镜帧]→H3 Ref2VA→每段~10s 视频 → ffmpeg 拼接 → 成片
```

### 9.1 注册表：config/pipeline.json

- `default_stage`：默认生成阶段。**默认 t2v 且未显式指定 --stage 时走“经典内置 H3 T2V”路径，与历史版本完全一致**（向后兼容）。
- `stages.<id>`：每个阶段一条：
  - `template`：`config/templates/` 下的 API(扁平) 模板文件名（t2v/i2v/r2v/flf2v/character/keyframes 等）；
  - `template_kind`：`api`（可 CLI 提交）或 `ui`（video_*.json 仅供 ComfyUI 界面，CLI 明确拒绝）；
  - `builtin`：内置生成器（目前仅 `h3_t2v`）——模板缺失时回退，保证“无模板也能跑”；
  - `prompt_files`：该阶段默认正/负提示词文件（相对项目根）；
  - `default_images`：该阶段默认输入图（i2v/r2v/flf2v 等需要）。

> **真实模板注意（实测）**：官方 `api_minimax_h3_*.json`（位于 spark
> `~/ai/ComfyUI/user/default/workflows/`）其实是 **ComfyUI UI 格式**（nodes/links），
> 且其节点（`MinimaxHailuo03*`）走 **Comfy API 云端**，需要 Comfy 账号登录/
> API key（object_info 含 `auth_token_comfy_org / api_key_comfy_org` 隐藏输入）。
> 引擎对模板的策略：
> 1. 扁平 API 模板 → 直接用 + 占位符替换；
> 2. **UI 模板 → 引擎已支持在线 UI→API 转换**（`runs/h3/uiapi.py`，依赖在线
>    ComfyUI 的 `/object_info`；动态组合子输入按服务器期望输出为
>    `model.prompt`/`model.resolution`/`model.ratio`/`model.duration` 等键，
>    源节点引用为字符串 id）——实测 `/prompt` 校验通过、可进入执行；
> 3. 模板缺失或不可转换 → 有内置生成器则提示并回退内置，否则报错。
> 说明：官方云端节点的真正生成还需要 Comfy 账号在 ComfyUI 中登录；本机内置
> H3 图（UNET/VAE 底层节点）是 **spark 本地推理**，不依赖 Comfy API，开箱即用。

**同事 6 份工作流的实际构成（实测分类）**：`api_minimax_h3_{t2v,r2v,flf2v}.json` =
`MinimaxHailuo03*` 封装节点（是否可执行取决于你 ComfyUI 实例是否登录 Comfy 服务；
GUI 打开最直接，若报 Unauthorized 即该节点插件的登录要求）；`video_minimax_h3_r2v.json`
= 本地 H3 **开放图**（`MiniMaxH3ReferenceToVideo` 等 20 节点，引擎可 UI→API 转换并本地跑，
仅需参考图）；`video_minimax_h3_t2v/i2v.json` = 本地图但被 **UUID 子图**封装（CLI 解组为
TODO，当前 t2v 由内置本地生成器等效覆盖）。
> 📖 逐文件手动步骤：`docs/manual-use-6-workflows.md`

### 9.6 远程模板路径记录（spark）

`config/pipeline.json` 的 `remote_workflow_templates` 记录了 spark 官方模板的绝对路径
（t2v/i2v/r2v/flf2v 的 api 与 video 版本）。需要时可用
`ssh spark "cat <绝对路径>" > config/templates/<同名文件>` 拉取留档，
或直接在 ComfyUI 界面打开该文件做人工编辑（video_*.json 为 UI 模板）。

### 9.2 模板占位符（放入模板字符串即可被自动替换）

```
{{prompt}} {{negative_prompt}} {{seed}} {{width}} {{height}}
{{seconds}} {{length}} {{fps}} {{steps}}      （数值/文本）
{{image0}} {{image1}} ...                      （输入图：自动上传后填入远端文件名）
```

例如 r2v 模板里写 `{"inputs":{"image":"{{image0}}"}}`，运行时本地图会被
`POST /upload/image` 上传并用返回文件名替换；`--dry-run` 预览时不上传，用本地文件名占位。

### 9.3 CLI（多工作流）

```
python h3_submit.py --stage r2v --image 角色图.png --image 场景图.png   # 阶段+输入图
python h3_submit.py --stage t2v --prompt "..."                          # 内置 T2V
python h3_submit.py --template path/to/api.json --prompt "..."          # 任意模板+占位符
python h3_submit.py --workflow-file saved_api.json                      # 原样提交（不动）
```

输出定位不再写死节点 14：会在全部输出节点里收集文件，mp4 优先、其次静态图，
仍打印 `REMOTE_VIDEO_PATH:`（多个文件打多行）供外层下载。

> 阶段模板的可用性策略：`--stage X` 会优先使用 `config/templates` 下同名模板；
> 模板缺失或为 UI 格式时，若该阶段配置了 `builtin` 则提示并自动回退内置生成器
> （控制台会标注“工作流来源: 内置生成器”），无内置才确定性报错。

### 9.4 配置工具

双击 **`pipeline_setup.bat`**：查看各阶段与模板状态（内置/就绪/缺失/UI 不可用）、
设置默认生成阶段、对某阶段做 dry-run 校验（不提交不上传）。
每个阶段是否就绪在工具里一目了然；缺模板时把对应 API 文件放进 `config/templates/` 即可。

### 9.5 流水线逐阶段配合（当前形态与路线图）

当前形态：各阶段作为“独立一次运行”串联 —— 上一阶段产物下载到本地
（`outputs/` 或 `workflows/<task>/`），再用 `pipeline_setup.bat`/配置文件把该图设为
下一阶段 `default_images`，或直接用 `--image` 传入，逐段执行即可覆盖
“角色图 → 关键帧 → R2V 视频 → 拼接”的生产流程。
已规划但尚未内置（需按真实模板做节点级映射后再补）：一次 `run` 内自动串联多阶段、
关键帧成组多图处理、本地 ffmpeg 拼接步骤；上述链路全部沿用现有断点/隧道/下载机制。
