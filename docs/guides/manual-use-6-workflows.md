# 6 个工作流 · 手动使用手册（本地 ComfyUI @ spark）

> 面向：你本人，在 Windows 这台机上，用你自己的 ComfyUI（`ssh spark` 可达，
> 服务监听 spark 的 127.0.0.1:8188，本机经隧道/本地 8188 访问）**手动**把下面
> 6 份工作流各跑一次。
>
> 6 份文件位于 spark：`/home/<用户名>/ai/ComfyUI/user/default/workflows/`
> （本工具已把同内容副本放本地 `config/templates/` 与镜像 `workflows/remote_workflows/`）。
>
> **用途速记（团队实际语义）**：`video_*`=文生/图生/多参考/首尾帧的本地 H3 模板；
> `api_*`=同一能力的 **API 格式**（扁平、无 subgraph 坑、命令行用更稳），走 Comfy 云
> 通道（MiniMax Hailuo 官方 API，需 Comfy 账号登录）——团队 15 镜短片《于勒》即以
> `api_minimax_h3_r2v` 做内核；`api_flf2v` 示例图需自备（angel-warrior… 不在 spark input）。

| 文件 | 用途 | 类型 | 手动怎么跑（GUI 最稳） |
|---|---|---|---|
| `video_minimax_h3_t2v.json` | 文生视频：文字→一段视频（官方标准模板） | 本地 H3（UUID 子图，已自动解组） | GUI 填文字→Queue；或 CLI `--stage t2v`（已实跑出片） |
| `video_minimax_h3_i2v.json` | 图生视频：一张**首帧图**→延续它动起来 | 本地 H3（UUID 子图，已自动解组） | GUI 选首帧→Queue；或 CLI `--stage i2v`（首帧当前=drama_asset_hero.png） |
| `video_minimax_h3_r2v.json` | 多参考图生视频：1–2 张参考图（角色/场景）→连贯 | 本地 H3 开放图 | GUI 选参考图→Queue；或 CLI `--stage r2v`（双参考图已实跑出片） |
| `video_minimax_h3_flf2v.json` | 首帧+末帧本地双帧（本地扩展，非 spark 原文件） | 本地 H3 双帧变体 | CLI `--stage flf2v`（首 hero/末 alley）或 GUI 打开本文件 |
| `api_minimax_h3_t2v.json` | **T2V 的 API 格式**（扁平、无 subgraph 坑，命令行更稳） | **Comfy 云模板**（MinimaxHailuo03* 经 Comfy 云代理 MiniMax 官方 API） | GUI 打开→填文字→Queue；需先登录 Comfy 账号，否则 `Unauthorized`（本地同语义用 video t2v） |
| `api_minimax_h3_r2v.json` | **R2V 的 API 格式**（《于勒》15 镜内核） | 同上（云模板） | GUI LoadImage 参考图→Queue（登录后）；本地同语义用 `--stage r2v` |
| `api_minimax_h3_flf2v.json` | 首帧+末帧（锁定起止画面，控制更精确）；**示例图需自备** | 同上（云模板） | GUI 首/末帧 LoadImage→Queue（登录后）；本地同语义用 `--stage flf2v` |

---

## 0. 一次性准备（10 分钟内）

1. 能 ssh 到 spark：
   ```powershell
   ssh spark 'echo ok'
   ```
2. ComfyUI 在运行：
   ```powershell
   ssh spark "pgrep -af main.py | head -3"
   ```
   没有输出就先启动（或手动 tmux），也可以用本套程序自动起：
   ```powershell
   cd <仓库根目录>
   .\bats\generate\menu.bat          # → [5] 环境与远程模型检查（会确认 ssh/ComfyUI/模型）
   ```
3. 确保本机能访问 ComfyUI 界面（脚本会自建/复用隧道）：
   ```powershell
   .\bats\generate\menu.bat          # 选 [5] 通过后，浏览器开 http://127.0.0.1:8188 应能出界面
   ```
   > 本工具在任何生成动作前都会自动检查并建立隧道（8188 被占会自动换端口）。

---

## 1. 先跑一次“内置 T2V”验证全链路（推荐第一步）

```powershell
cd <仓库根目录>
.\bats\generate\menu.bat            # → [1] 立即生成视频
```
- 参数在 `parameters\video.txt`（分辨率/时长；默认 360p/5s），提示词在
  `prompts\positive_prompts.txt` / `negative_prompts.txt`（用 bats\config\edit.bat 或记事本改）。
- 成功：`outputs\video_N.mp4`；日志 `logs\run_*.log`；审计 `workflows\h3_*\job.json`。
- 说明：这一步走**本地 H3 内置图**（与 `video_minimax_h3_t2v.json` 同一套本地模型语义），
  用于确认“环境+脚本”能出片；随后再逐个开 6 个工作流。

---

## 2. 逐个手动使用 6 个工作流（推荐 GUI 方式）

### 2.1 GUI 通用步骤（对全部 6 个都适用）
1. 浏览器打开 `http://127.0.0.1:8188`。
2. 菜单 `Workflow → Open`，粘贴 spark 路径或选本地副本：
   - 远端：`/home/<用户名>/ai/ComfyUI/user/default/workflows/<文件>`
   - 本地：`<仓库根目录>\config\templates\<文件>`
3. 按第 0 节表里“手动怎么跑”补输入（文字/图片）。
4. 点 `Queue`（或 Ctrl+Enter）。
5. 进度看右下角；出片点输出节点的图片/视频可下载，文件也在
   `spark:~/ai/ComfyUI/output/video/`。

### 2.2 每个文件具体补什么
| 工作流 | 需要补 | 提示 |
|---|---|---|
| `video_minimax_h3_t2v.json` | 正向文字提示词（子图内 prompt 节点） | 参数/种子通常已在图里 |
| `video_minimax_h3_i2v.json` | LoadImage 选一张首帧图 | 图片要先传到 spark `~/ai/ComfyUI/input/` 或用界面上传 |
| `video_minimax_h3_r2v.json` | LoadImage 选参考图（镜像已同步为 `drama_asset_hero.png`/`drama_asset_alley.png`，都在 spark input；也可换 character.png 等） | 也可用本套程序 CLI（见 3） |
| `api_minimax_h3_t2v.json` | 节点内的文字提示词 | 若 Queue 后报 Unauthorized → 你的 ComfyUI 需登录 Comfy 云（该节点实现如此）；否则正常 |
| `api_minimax_h3_r2v.json` | LoadImage 参考图 | 同上 |
| `api_minimax_h3_flf2v.json` | 首帧+末帧 LoadImage | 同上 |

---

## 3. 用本套程序（脚本/CLI）自动化跑（支持子集）

> 除 GUI 外，本套程序可对这些文件做：拉取（已在本地）、dry-run 校验、UI→API
> 转换、提交轮询下载。逐个试一遍的推荐命令如下（都在项目根执行）：

### 3.0 验证每个文件都能被程序识别（dry-run，不提交不生成）
```powershell
cd <仓库根目录>
python runs\h3_submit.py --template config\templates\video_minimax_h3_t2v.json   --dry-run
python runs\h3_submit.py --template config\templates\video_minimax_h3_i2v.json   --dry-run
python runs\h3_submit.py --template config\templates\video_minimax_h3_r2v.json   --dry-run
python runs\h3_submit.py --template config\templates\api_minimax_h3_t2v.json     --dry-run
python runs\h3_submit.py --template config\templates\api_minimax_h3_r2v.json     --dry-run
python runs\h3_submit.py --template config\templates\api_minimax_h3_flf2v.json   --dry-run
```
- `video_*`（t2v/i2v/r2v）与 `api_*` 会先自动解组（如需）并在线转换再打印 JSON；
- 本地视频走 `video_*`：`--stage t2v/i2v/r2v/flf2v` 或 `--template video_minimax_h3_*.json`，
  均已实跑出片；`api_*` 三份 dry-run/转换可用，真正出片需 Comfy 账号登录（云模板）。

### 3.1 本地模型 + 同事开放图 r2v（`video_minimax_h3_r2v.json`）真正跑一次
```powershell
# 1) 准备参考图：把本地图片传到 spark input（或直接用服务器已有图）
scp 你的图.png spark:~/ai/ComfyUI/input/

# 2) 把模板里 LoadImage 指向你上传的图（记事本改 config\templates\video_minimax_h3_r2v.json：
#    找到 "LoadImage"，把 widgets_values[0] 改成你上传的文件名）

# 3) 真跑（提交→轮询→打印远程视频路径）
python runs\h3_submit.py --template config\templates\video_minimax_h3_r2v.json

# 4) 下载到 outputs（文件名按提示换）
scp spark:"<第3步打印的 REMOTE_VIDEO_PATH>" outputs\video_r2v.mp4
```
更省事：把图放进 spark `input/` 后，也可以直接
`python runs\h3_submit.py --stage r2v`（阶段 r2v 已指向该本地文件；
缺图时会给出明确提示）。

### 3.2 其它文件“手动跑一次”的落点
- `video_minimax_h3_t2v.json` / `video_minimax_h3_i2v.json`：子图封装已自动解组，直接
  `python runs\h3_submit.py --template <该文件>` 或 `--stage t2v/i2v` 即可（已实跑出片）。
- `video_minimax_h3_flf2v.json`（本地扩展）：`python runs\h3_submit.py --stage flf2v`
  （首帧 hero/末帧 alley；改 LoadImage 指向 spark input 其它图即可换内容）。
- `api_minimax_h3_{t2v,r2v,flf2v}.json`：**Comfy 云模板**——dry-run/转换可用（3.0）；
  真正出片需这些 Hailuo03 节点在你实例上可执行（GUI Queue 若报 Unauthorized 即需登录
  Comfy 账号）。本地同语义请用对应 `video_*`（t2v/r2v/flf2v 均已有本地路径）。

---

## 4. 遇到问题的速查

| 现象 | 处理 |
|---|---|
| `Unauthorized: Please login first` | 该节点是 **Comfy 云模板**（`api_*` 的 MinimaxHailuo03* 经 Comfy 云代理 MiniMax API）：需在 ComfyUI 登录 Comfy 账号；不想上云就用本地对应物 `video_*`（t2v/i2v/r2v/flf2v 全部本地可跑） |
| “需要在线 object_info / 模板是 UI 格式” | 先让本程序建好隧道（跑一次 `menu [5]`），或 GUI 打开该文件 |
| LoadImage 图不存在 | `scp` 传图到 `spark:~/ai/ComfyUI/input/`，改模板文件名或用 GUI 上传 |
| 参数在哪改 | `parameters\video.txt`（resolution/seconds，可用 bats\config\edit.bat） |
| 出片在哪 | `outputs\video_N.mp4`；工作流与审计在 `workflows\h3_*\`；日志 `logs\run_*.log` |
