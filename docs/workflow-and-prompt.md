# 指定"工作流"与"提示词"指南（有 / 无本地通用模型）

> 回答两个问题：① 每次工作**用哪个工作流（生成方案）**怎么指定；② 每次工作的
> **提示词（内容）**怎么指定。两种"输入来源"分别说明：
> **没有本地通用模型 = 一切由人手工填**；**有本地通用模型 = 可说一句创意让 AI 填词**。
> 新手流程另见 `docs/quickstart.md`；逐模板细步骤 `docs/manual-use-6-workflows.md`。

---

## 1. 先分清两个概念

| 概念 | 是什么 | 由谁指定 |
|---|---|---|
| **工作流 / 模板**（t2v/i2v/r2v/flf2v 或 api_*） | 决定"用什么节点、要不要参考图"的生成方案 | 人（或自动化脚本按创意分配） |
| **提示词**（正向/负向） | 决定"画面内容"的剧本文字 | 没有本地模型：人；有本地模型：AI 代写后人确认 |

两者的指定方式是**独立的**：你可以选 r2v 工作流，提示词由 AI 按 r2v 槽位生成；
也可以不换工作流，只改提示词换个内容。

### 可用的工作流清单
| 工作流 id / 文件 | 用途 | 参考图 |
|---|---|---|
| 内置 t2v（经典模式） | 纯文字→视频（最稳、最快） | 无 |
| `--stage t2v` / `video_minimax_h3_t2v.json` | 文生视频（官方标准模板） | 无 |
| `--stage i2v` / `video_minimax_h3_i2v.json` | 首帧图动起来 | 1 张（首帧） |
| `--stage r2v` / `video_minimax_h3_r2v.json` | 角色/场景参考图，保证连贯 | 1–2 张 |
| `--stage flf2v` / `video_minimax_h3_flf2v.json` | 首帧+末帧，锁定起止 | 2 张 |
| `--template <文件.json>` | 任意指定上面任一模板文件 | 按模板 |
| `api_*`（t2v/r2v/flf2v 云版） | 登录 Comfy 云后的 API 内核（扁平、命令行更稳） | 按模板 |

---

## 2. 情形 A：没有本地通用模型（人操作一切）

### A1 怎么指定"工作流"

按你要的粒度从易到难：

1. **就用默认（经典 t2v，纯文字）**：直接双击 `bats\generate\run.bat`（或 menu `[1]`）。
2. **换成某个"组合工作流"作为默认**（例如以后双击都跑 r2v）：
   ```
   bats\workflow\pipeline_setup.bat  →  [2] 设置默认生成阶段  →  输入 r2v
   ```
   之后双击 run.bat 就按 `--stage r2v` 跑该模板（窗口会打印"运行模式：组合工作流 --stage r2v"）。
   想回纯文字：把默认阶段改回 `t2v`。
3. **只本次换工作流（不改变默认）**——用命令行（项目根开 cmd 粘贴）：
   ```
   python runs\h3_submit.py --stage t2v --force-new
   python runs\h3_submit.py --stage i2v --force-new
   python runs\h3_submit.py --stage r2v --force-new
   python runs\h3_submit.py --stage flf2v --force-new
   ```
   或精确到文件：`python runs\h3_submit.py --template workflows\remote_workflows\video_minimax_h3_r2v.json --force-new`
   先预览不烧钱：命令尾加 `--dry-run`。
4. **原样复跑某个已保存的工作流**（精调过想复现）：
   ```
   bats\generate\menu.bat → [6] 工作流上传/使用指定工作流 → 激活某次任务 → 之后 run.bat 原样提交它
   ```

> i2v/r2v/flf2v 用参考图时，请先按 `docs/quickstart.md` 第 5 节把图传到
> spark `~/ai/ComfyUI/input/` 并在模板 LoadImage 里选好/改好文件名（只改本地镜像那份 json）。

### A2 怎么指定"提示词"（人写）

| 你用的模式 | 你编辑的文件 | 说明 |
|---|---|---|
| 经典 t2v（内置） | `prompts\positive_prompts.txt` 与 `prompts\negative_prompts.txt` | 正向=要什么；负向=不要什么 |
| 组合工作流 | `prompts\workflows\<工作流槽位>.positive.txt` / `.negative.txt` | 槽位=工作流 id：`video_t2v / video_i2v / video_r2v / video_flf2v`（api 版为 `api_t2v / api_r2v / api_flf2v`） |

- 快捷编辑工具：`bats\prompts\prompts.bat`（列出全部槽位 → 记事本打开 → 改；`C`=把 default 剧本复制到某槽起步）。
- **回退规则**：槽位文件**空或缺失** → 自动使用 default（即 `prompts\positive_prompts.txt`）。所以"只想快速换内容"：改 default 两个 txt，所有用空槽的模板都会跟着变。
- 写好剧本的规则见 `skills/h3-prompt-engineering.md`（先写时长+镜头，动作、运镜、声音，最后负面约束；英文更稳）。

**结论（A）**：人 = ①在 pipeline_setup/CLI 里挑工作流 ②用 prompts.bat/记事本往对应 txt 填词 ③跑。

---

## 3. 情形 B：有本地通用模型（AI 接入，"一句话创意"形态）

前提：已部署通用模型并配置（例如 spark 上的 Qwen3-8B/27B vLLM）——
按 `config\llm.spark-qwen3.example.json` 复制为 `config\llm.json`，置 `enabled: true`
（本地端点 `api_key` 留空）。验证：`python runs\h3\idea2prompts.py --list` 能列出槽位。

### B1 提示词怎么来（AI 写词，你定工作流）

```
bats\prompts\ai_prompts.bat        # 交互输入一句创意 → 为【全部槽位】生成正/负提示词并写入
```
或命令行精确控制：
```
:: 为全部槽位生成（default + video/api 各槽）
python runs\h3\idea2prompts.py --idea "一句创意" --force

:: 只为某个工作流槽位生成（如 r2v）
python runs\h3\idea2prompts.py --idea "一句创意" --workflow video_r2v

:: 先预览不发请求：--dry-run（没配模型也能看）
python runs\h3\idea2prompts.py --idea "一句创意" --dry-run
```
生成后会写入 `prompts/workflows/<槽位>.*.txt`（default 写入 `prompts/positive_prompts.txt` 等），
随后**跑工作流时引擎自动使用对应槽位词**（覆盖模板内嵌 prompt），无需手工拷贝。

### B2 工作流仍由谁指定？
- 现阶段：**人（或你的编排脚本）选择工作流**——用 A1 的方法（默认阶段 / `--stage`）；
  AI 只负责把每个工作流槽位的词写好，保证"无论选哪个模板都有一份贴合的提示词"。
- 全自动（最终形态，可选脚本化）：写一个循环/计划，把创意依次跑过目标镜头模板
  （如按分镜用 i2v/r2v/flf2v 各跑一段），提示词已由 B1 就位。

### B3 一条完整自动化示例（AI 词 + 跑 r2v）
```
python runs\h3\idea2prompts.py --idea "雨夜楼顶追杀，主角手持匕首反杀敌人" --workflow video_r2v --force
python runs\h3_submit.py --stage r2v --force-new --seed 2026
```

**结论（B）**：AI = 填词（一句话 → 全槽/单槽）；工作流 = 人按场景挑选（或脚本编排）；
再跑命令即出片。

---

## 4. 决策速查（"我要…"）

| 我要… | 情形 A（无本地模型） | 情形 B（有本地模型） |
|---|---|---|
| 快速纯文字出片 | 改 default 词 → run.bat | `ai_prompts.bat` 填 default → run.bat |
| 用角色/场景参考图出片 | 传图→改 r2v 模板/槽位词→`--stage r2v` 或默认阶段设 r2v | `idea2prompts --workflow video_r2v` → `--stage r2v` |
| 首帧动起来 | 同 i2v | 同 i2v |
| 首尾帧控制 | 同 flf2v | 同 flf2v |
| 换一批内容 | 记事本改提示词 txt | 重新 `--idea "新创意" --force` |
| 不确定怎么选模板 | 看 `docs/quickstart.md` §4 需求表 | 让 AI 为全部槽生成，再从 GUI/CLI 挑 |

---

## 5. 能力注册表与"让模型了解项目"的两方案取舍（给开发者/后续会话）

**方案一（结构化能力，已落地基础）：System Prompt + 工具定义**
- 单一来源：`config/capabilities.json`（视频工作流 7 个、`generate_reference_image`=FLUX、
  `generate_video`=h3_submit 参数、提示词槽位规则），模型可读的英文描述与参数 schema。
- 生成人类/Agent 文档：`python runs\h3\capabilities.py --doc` → 重写
  `docs/capabilities-ai.md`（标注"由 json 生成，勿手改"）。
- 喂给本地 LLM 的精简摘要（~0.7k 字符）：`python runs\h3\capabilities.py --digest`。
  当前"槽位填词"每次请求默认**不注入**该摘要（避免挤占已调优的 7 条规则）；当模型要承担
  "创意 → 选工作流/出图/定参数"（plan 模式）时再把 digest 注入 system，或在 LLM 支持
  Function Calling 的稳定版本（vLLM ≥0.28 的 tools）下把工作流做成 tools。
- 关键约束：给 27B 级小模型的指令必须**自包含、编号、短句、含示例**（见
  `config/prompt_blueprints.json` 与 §3；模型看不到仓库其它文件）。

**方案二（RAG，当前不启用，理由与启用时机）**
- 本项目知识规模很小（8 个提示词槽 + 7 个工作流 + 3 个工具），System Prompt 放得下；
  引入 embedding/向量库（bge、Chroma 等）会增加部署与延迟且对 27B 收益低。
- 何时启用：工具/说明扩到几十个、或用户要模型回答"项目怎么用"类开放问题且命中率不足时，
  再按"文档切片 → bge-small-zh 向量化 → 检索 top-k 拼入上下文"实现（配置与查询放
  `runs/h3/`，入口预留为 `idea2prompts --rag-help` 的后续版本）。

---

## 6. 相关文档
- `docs/quickstart.md` 新手三步走（含参考图操作）
- `docs/user-guide.md` 完整命令与机制
- `docs/manual-use-6-workflows.md` 每模板 GUI+脚本细步骤
- `docs/capabilities-ai.md` 项目生成能力注册表（由 config/capabilities.json 生成）
- `skills/h3-prompt-engineering.md` 提示词写法规则
- `config/llm.spark-qwen3.example.json` AI 桥配置示例（情形 B 前提）
