# MiniMax H3 视频生成 · 新手快速上手（小白版）

> 适用：第一次用这台电脑跑视频的人。**不需要懂任何技术**，照着点就行。
> 想看原理/更多命令：`docs/user-guide.md`；逐模板细步骤：`docs/manual-use-6-workflows.md`。

---

## 1. 这是干嘛的？（30 秒理解）

你给一段**文字**（或一张**图**），本工具调用远端的 MiniMax H3 模型，
生成一段 **5～15 秒、带声音的视频**，并自动下载到本地。

全程你只需要：
- 写"剧本"（一个 txt 文件）
- 双击几个 `.bat`（就像双击一个按钮）
- 等窗口出现 **"全部完成！"** → 去 `outputs\` 文件夹看成品

---

## 2. 先认识这几个地方（5 分钟）

```
videoGenerate-Model-zju\
├─ bats\            ★ 你双击的"按钮"都在这（按用途分文件夹）
│   ├─ generate\    run.bat=立即生成   menu.bat=功能主菜单
│   ├─ prompts\     prompts.bat=改剧本   ai_prompts.bat=一句话自动写剧本(需配模型)
│   ├─ config\      edit.bat=改清晰度/时长
│   ├─ service\     StartComfyUI.bat=打开/管理远程画图软件
│   └─ workflow\    （进阶用）
├─ prompts\         ★ 你的"剧本"放这（.txt）
├─ parameters\video.txt  清晰度/时长
├─ outputs\         ★★ 成品视频在这：video_1.mp4、video_2.mp4…
└─ logs\            每次运行的记录（出问题时看它）
```

第一次使用前必做一步：双击 `bats\generate\menu.bat` → 按 `5`（环境检查）。
看到"通过"就可以开始了；显示缺模型它会问你是否自动下载，选 Y 即可。

---

## 3. 第一条视频：3 步走（预计 3～8 分钟）

**第 1 步 · 写剧本**
用记事本打开 `prompts\positive_prompts.txt`。
里面已经有一篇示例"剧本"，你只需**整篇替换成你自己的话**，例如：

```
A five-second cinematic shot. A white cat sits on a rainy windowsill at night,
city lights blurred behind the glass. Camera slowly pushes in toward the cat's eyes.
Soft rain sound, gentle ambient music. No text, no watermark, no cuts.
```

> 想写得更好：中文也行，但英文效果更稳。参考 `skills\h3-prompt-engineering.md` 的写法规则
> （先写时长+镜头，再写动作、运镜、声音，最后写"不要什么"）。

`prompts\negative_prompts.txt`（负面清单，默认已填好）**不用改**。

**第 2 步 · 选清晰度/时长**
双击 `bats\config\edit.bat` → 选分辨率（新手用 `1`=360p 最便宜）→ 输入秒数（5）。

**第 3 步 · 生成**
双击 `bats\generate\run.bat`（或 menu → `1`）。
窗口里会出现进度（`[0s] [21s] [74s]…`），**别关窗口**，等出现：

```
全部完成！视频已保存
```

然后去 `outputs\` 找到 `video_1.mp4`，双击播放。🎉

---

## 4. "我想做不同效果" → 选哪种模板

上面第 3 步是**最简单的玩法（纯文字→视频）**。想做"图动起来""两张图过渡"等，
就要用"模板"。先看需求表：

| 我想要的 | 模板名 | 需要我准备 |
|---|---|---|
| 纯文字 → 一段画面（快速，最稳） | **t2v** | 只写剧本 |
| 一张图 → 让图动起来 | **i2v** | 1 张起始图（首帧） |
| 角色/场景/道具图 → 生成连贯故事镜头（可多张） | **r2v** | 1 张起，模板支持多张（默认 8 槽） |
| 一张"开头图"+一张"结尾图" → AI 补中间过程 | **flf2v** | 2 张图（首帧、末帧） |

对应文件在 `workflows\remote_workflows\`：`video_minimax_h3_t2v.json`（文生视频，官方标准模板）、
`video_minimax_h3_i2v.json`（首帧图动起来）、`video_minimax_h3_r2v.json`（多参考图：角色/场景
保证连贯）、`video_minimax_h3_flf2v.json`（首尾帧，本地扩展）。

> **云端版 `api_minimax_h3_*`（进阶）**：t2v/r2v/flf2v 三份还有"API 格式"版本——**扁平、无子图
> 坑、命令行用更稳**（团队 15 镜短片《于勒》就是用 api_r2v 做内核）。但它走 **Comfy 云**通道
> （MiniMax 官方 Hailuo API）：只有 ComfyUI **已登录 Comfy 账号**才跑得动，否则报
> `Unauthorized`。没登录云端账号时，本地一律用上面 `video_*` 四份即可；`api_flf2v` 的示例图
> 不在 spark input，要用需自备图片。

### 怎么跑一个模板？二选一

**方式 A：看界面操作（最直观，推荐新手）**
1. 双击 `bats\service\StartComfyUI.bat` → 按 `1`（会弹开一个网页）；
2. 在网页里点 **Workflow → Open**，选上面某个 `.json` 文件；
3. 网页里找到 **LoadImage**（选图）和 **prompt**（写词）两个格子填好；
4. 点 **Queue**（排队生成），完成后网页里有视频可下载/查看。

**方式 B：命令行（更省事，复制粘贴即可）**
打开命令行（在项目文件夹地址栏输入 `cmd` 回车），粘贴下面任一行后回车：

```
python runs\h3_submit.py --stage t2v   --force-new
python runs\h3_submit.py --stage i2v   --force-new
python runs\h3_submit.py --stage r2v   --force-new
python runs\h3_submit.py --stage flf2v --force-new
```

> 每个模板的"剧本"写在不同文件里（见第 6 节），生成前记得填好。

---

## 5. 参考图怎么加？（i2v / r2v / flf2v 都要图）

记住一句话：**图必须先放到远程服务器的 input 文件夹里**。

**第 1 步：把图传过去**（任选一种）
- 网页方式：打开 ComfyUI 网页后，把图片文件**直接拖进网页窗口**即可（自动上传）；
- 命令方式：在项目文件夹开 cmd，执行：
  ```
  scp 你的图片.png spark:~/ai/ComfyUI/input/
  ```

**第 2 步：告诉模板"用哪张图"**（任选一种）
- 界面方式（当次有效）：网页 LoadImage 节点里下拉选图；
- 永久方式（以后每次 CLI 都用它）：记事本打开对应模板 json
  （如 `workflows\remote_workflows\video_minimax_h3_r2v.json`），
  搜索 `drama_asset_hero.png`，把它替换成你传上去的图片文件名（例如 `hero.png`），保存。

> 模板里有两个 LoadImage 的（r2v、flf2v），分别代表"角色图/开始图"和"场景图/结尾图"，
> 看图名或文件顺序即可分辨，都改成你的图。
> **重要：只改本地这份 json**（`workflows\remote_workflows\` 里），不要动远程 spark 里的文件。

### 模板目前默认用哪两张图（内置示例，可先直接试）
| 模板 | 图 1（开始/角色） | 图 2（场景/结尾） |
|---|---|---|
| i2v | `drama_asset_hero.png` | — |
| r2v | `drama_asset_hero.png` | `drama_asset_alley.png` |
| flf2v | `drama_asset_hero.png` | `drama_asset_alley.png` |

想先"零准备试一把"，直接跑 r2v/flf2v 就能出片。

---

## 6. 剧本（提示词）到底写哪个文件？—— 新旧两种玩法的区别

| 玩法 | 你写的文件 | 什么时候生效 |
|---|---|---|
| **经典玩法**（第 3 步，纯文字出片） | `prompts\positive_prompts.txt`（正向）与 `prompts\negative_prompts.txt`（负向） | 双击 run.bat / menu 生成时 |
| **模板玩法**（第 4 步） | `prompts\workflows\video_t2v.positive.txt`、`video_i2v…`、`video_r2v…`、`video_flf2v…`（一个模板一个文件） | 跑对应模板时 |

- 模板文件里**留空** = 自动使用经典玩法的 default 剧本（即 `prompts\positive_prompts.txt`）；
- 想快速起步：双击 `bats\prompts\prompts.bat`，按 `C` 可把经典剧本复制到某个模板文件里再改。

---

## 7. 想要"一个完整小片子"（多镜头）

H3 一次只生成**一个镜头**（最长约 15 秒）。想讲完整故事：
1. 把故事拆成 3～5 个镜头；
2. 每个镜头按第 4、5 节跑一次（同角色记得每次用同一张角色参考图）；
3. 把 `outputs\` 里的几段 mp4 用剪映/快剪辑/ffmpeg 拼起来。

---

## 8. 出问题了怎么办？

| 现象 | 处理 |
|---|---|
| 窗口红字 `Unauthorized: Please login first` | 你用了云端模板 api_*。改用 `video_*` 模板（第 4 节），或忽略 |
| 提示找不到模型 / 环境未通过 | menu → `5`，按提示让它自动下载 |
| 中途断网/卡住 | **别重开新任务**，直接再双击一次 run.bat（或重跑刚才那条命令）→ 会自动接着原来的任务，**不会重复生成** |
| 窗口报错看不懂 | 把窗口内容，或 `logs\` 里最新的 `run_*.log` 内容发我 |
| 一直等没结果 | 看窗口进度数字是否在涨；涨就是正常（一段 360p 视频约 2～5 分钟） |

日志位置：`logs\` 文件夹，文件名带时间（如 `run_20260902_224925.log`）。
成品位置：`outputs\video_N.mp4`（N 会自动变大，不会覆盖旧片）。

---

## 9. 名词扫盲（看文档时用得上）

- **工作流/模板**：一份"怎么生成"的图纸（.json 文件）。
- **提示词（prompt）**：你写给 AI 的剧本文字；**正向**=要什么，**负向**=不要什么。
- **参考图/首帧/末帧**：给 AI 看的图——照着画/让它动起来/作为开头与结尾。
- **出片**：成功生成视频的意思。
- **spark**：远处那台干活的大电脑（存图/跑模型都靠它）。

---

## 10. 想了解更多

| 文档 | 内容 |
|---|---|
| `docs/workflow-and-prompt.md` | 怎么选工作流、提示词写哪（有/无 AI 两种情形） |
| `docs/deploy-modes.md` | 项目搬到 spark 上运行的形态切换（交付用） |
| `docs/user-guide.md` | 全部入口与命令的完整说明（进阶） |
| `docs/manual-use-6-workflows.md` | 每个模板的逐文件操作步骤 |
| `skills/h3-prompt-engineering.md` | 怎么写剧本效果更好（提示词规则） |
| `docs/session-summary.md` | 项目当前状态与待办（给开发/智能体） |
