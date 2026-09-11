# AI+∞ 电影 Agent（多 Agent Harness）· 魔搭创空间

> **本空间只部署 Agent，不部署任何模型，也不提供任何密钥**；模型能力全部由**使用者自己**通过 **API 接口**接进来。
> 代码可下载、可自部署：<https://github.com/sakuraahly/videoGenerate-Model-zju>（目录 `studio/`）
> 版本 **v3.5**（2026-09-11）

## 零、它是什么（电影 Agent 赛道）

一句话 → **五个角色分工**（编剧 StoryWriter → 分镜 ShotPlanner → 导演 Director → 质检 Critic → 剪辑 Editor）
→ 一条状态机调度 → **剧本卡 + 分镜表 + 预检闸门 + 质检打分 + 决策轨迹 + 可执行生产包**。

- **零配置可用**：不填任何 key 也有**内置规则引擎**保底 —— 帧网格（5+17k @24fps）、六段式英文提示词、
  正负词库分离、台词语言→音色匹配、108 套分镜骨架、剧本静态预检（含版权词表），产出的分镜表"照做就能拍"；
- **访客自带大脑**：填自己的通用大模型 key → 编剧/导演由真模型产出，**Critic 判分择优**（模型提案分高才采用）；
- **访客自带引擎**：填视频生成模型接口 → 页面内逐段提交、轮询、回传成片；不填则交付**生产包**（可复制执行）；
- **生产包**（zip）：`plan.json / jobs.jsonl / commands.md / run_plan.py / accept.md / post.md / film.srt / trace.json / README.md`；
- **一键自检**：`py -3 studio/selfcheck.py` → RULES / HARNESS / KIT / ENGINE 四段 + MODE。

**红线**：空间内不推理、不下载权重、不连任何本机 GPU；超分/混音/字幕只出**指令**（`post.md`），不执行。

## 零点五、页面有什么、三档怎么走

页面上只有一件事：**写一句话 → 看制片方案 →（可选）出片**。

| 档 | 你填了什么 | 页面会做什么 |
|---|---|---|
| 档 0 | 什么都不填 | 内置规则引擎给出剧本 / 分镜表 / 预检 / 质检 / 生产包（零算力、约 1 秒） |
| 档 1 | 只填通用大模型（**🎛 模型配置**里的 Base URL + 模型名 + Key） | 编剧/导演由你的模型产出，Critic 判分择优；仍不出片 |
| 档 2 | 再填引擎（`ENGINE_BASE_URL` / `ENGINE_STATUS_URL` / `ENGINE_API_KEY`） | 点「🚀 出片」逐段提交到你的引擎 → 轮询 → 成片回传 |

**边界（一句话）**：空间里只跑编排与规则（**不推理、不下权重、不连本机 GPU**）；
大脑与引擎都在**你那一侧**，凭据只存会话内存（不落盘、不进日志）。
「🚀 出片」才会调用你的引擎，算力与费用由你承担。

## 一、30 秒接上你自己的模型（两条接口）

### 1）通用大模型（Agent 的「大脑」）—— OpenAI 兼容

页面上直接填，点一下预设就行（**推荐**）：

| 预设 | 地址 | 模型名 |
|---|---|---|
| 阿里云百炼（DashScope 兼容模式） | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen-plus` |
| DeepSeek | `https://api.deepseek.com` | `deepseek-chat` |
| 魔搭 API-Inference（社区免费额度） | `https://api-inference.modelscope.cn/v1` | `Qwen/Qwen3.5-35B-A3B` |
| 智谱 GLM | `https://open.bigmodel.cn/api/paas/v4` | `glm-4-flash` |

也可以写成空间变量（运营方给默认值时）：`LLM_BASE_URL` / `LLM_MODEL` / `LLM_API_KEY`（密钥区）。
可选 `LLM_EXTRA_JSON`（例：`{"enable_thinking": false}` 关思考、更快）。

### 2）视频生成模型 —— 只用两个动作的 HTTP 接口

| 变量 | 含义 |
|---|---|
| `ENGINE_BASE_URL` | 提交作业：`POST`，请求体见下表，返回 `{"job_id": "..."}` |
| `ENGINE_STATUS_URL` | 查询作业：`GET {ENGINE_STATUS_URL}/{job_id}`，返回 `{"status":"running|completed|failed", "video_url":"...", "progress":0.42}` |
| `ENGINE_API_KEY` | 上面的鉴权（密钥区），会以 `Authorization: Bearer` 发送 |

**提交请求体**（Agent 自动按工具拼好，你只要实现服务端）：

| 字段 | 取值 |
|---|---|
| `kind` | `t2v`（文生视频）/ `i2v`（图生视频）/ `talk`（说话镜头）/ `story`（多段故事片） |
| `prompt` 或 `text` / `script` | 提示词 / 台词 / 剧本（`kind` 对应） |
| `image_b64` | 参考图（`data:image/...;base64,...`） |
| `resolution` / `seconds` / `voice` / `segments` | 分辨率 / 时长 / 音色 / 段数 |

完整契约、错误码与示例见同目录 **[`接口说明.md`](接口说明.md)**；本地可用仓库里的 `tests/mock_engine.py`（假引擎）
先跑通整条链，再换成你自己的服务。

## 二、Agent 由哪两半组成

| 半边 | 内容 |
|---|---|
| **工具集**（手脚，全部 HTTP，零本机依赖） | `generate_video` / `generate_talk` / `make_story_film` / `list_jobs` / `query_job` / `retry_job` / `resume_story` / `answer`（`TOOLSET` 可收窄） |
| **外置大脑**（决策） | 任何 OpenAI 兼容服务；模型只回一个 `{tool,args,say}` JSON；提示可外置（`AGENT_SYSTEM_PROMPT`） |

缺大脑 → 内置**规则规划器**兜底（照样展示决策与请求体预览）；缺视频接口 → **规划演示**。
**不做假动作、不谎报成功**。

## 三、密钥归属：**本空间不提供任何密钥**（零成本）

- **不代付**：空间变量里**没有**任何 API Key（`ALLOW_ENV_FALLBACK=0`），**不花运营方一分钱**；
- 访客**不填 key** → 走内置**规则规划器**：照样展示决策轨迹与将发给接口的请求体，**不联网、不产生费用**；
- 访客**填自己的 key** → 真实调用；key 只在该会话内存里（**不写盘、不进日志**，按会话隔离，2 小时回收）；
- **留存策略（两条链路不同）**：「🎬 一句话出片」的凭据**用一次即弃**（只在单次请求内存里，服务端不保存）；
  「🤖 旧版对话工具」因为要多轮复用客户端，会在服务端内存按会话缓存，**2 小时 TTL + 最多 200 会话**自动释放；
- **不想把 key 交给本空间** → 用零信任单页版（Agent 在浏览器里直连你的模型服务，key 不经过任何服务器）：
  <https://sakuraahly.github.io/videoGenerate-Model-zju/web/agent.html>
- （仅运营方需要时）想给体验额度：填回 `LLM_*` 并把 `ALLOW_ENV_FALLBACK` 设为 `1`；
  已内置**大脑调用限流**，只对运营方凭据生效（`BRAIN_CALLS_PER_HOUR`，默认 60 次/会话/小时，BYOK 不限）。

## 四、下载与自部署

```bash
git clone https://github.com/sakuraahly/videoGenerate-Model-zju.git
cd videoGenerate-Model-zju/studio
pip install -r requirements.txt
python app.py --port 7860        # 打开 http://127.0.0.1:7860
```

- 不接任何接口也能跑：**规则引擎档**（完整剧本/分镜/预检/生产包，不联网、不产生任务）；
- 编排链自检：`python selfcheck.py`（打印 RULES/HARNESS/KIT/ENGINE 与 MODE）；
- 接上第一节的两个接口即真实出片；**空间内不跑任何模型**，画质由你接的服务决定；
- 部署到魔搭创空间：把 `studio/` 内容推到空间仓库 → 触发平台重建即可。

## 五、页面结构

- **🎛 模型配置（我的密钥）**：Agent Tab 顶部常驻 —— 服务商预设 / Base URL / 模型名 / key / 🔌 测试连接
  （失败原因分类：401/403=key、404=地址、400=模型名、429=限流、超时与连不上分开说）；
  引擎三项 + 🔌 测试引擎。**仅本会话内存**：不落盘、不进日志；
- **🎬 一句话出片**：输入一句话 → 制片看板（5 张角色卡 / 剧本卡 / 分镜表 / 预检 / 质检 / 决策轨迹 / 交付说明）
  → 下载生产包；配置了引擎后点 **🚀 出片** 即逐段真出片（可先填"出片段数=1"试水）；
- **🤖 Agent 对话**：说需求 → 工具调用轨迹 + 本轮产物 + 任务面板（可刷新状态）；
- **🎛 创作台**：表单式创作（任务类型/提示词/参考图/分辨率/时长/音色/字幕 → 提交 → 预览下载）；
- **🎞 样片墙**：参考样片（含 ASR 分数、字幕、口型）；
- **🧭 能力与部署**：能力点、流程、部署说明，以及 **🔌 测试外置大脑连接**（一键验证你的 key 通不通）。

## 五·五、可执行生产包（"可复制系统"的证据）

一次"一句话"产出一个 zip：`plan.json`（剧本+分镜+参数+锚点+质检）、
`jobs.jsonl`（每段一行请求体，复制即用）、`commands.md`（本机 GPU 的命令行等价形式）、
`run_plan.py`（一条命令跑完全片：提交→轮询→取回→拼接→验收，可断点续跑）、
`accept.md`（验收规则）、`post.md`（超分/插帧/混音/字幕指令）、
`film.srt`（字幕原文，台词表直出无错别字）、`trace.json`（5 角色决策轨迹）、
`README.md`（怎么用/耗时/失败续跑）。

## 六、安全与边界

- 已加固：拒云元数据地址（SSRF）、任务号白名单（防路径穿越）、下载文件名清洗、上传与台账内存上限、
  产物目录随机化（防跨用户猜链接）、刷新与轮询限流、密钥不回显；
- 空间**无持久化**：会话结束即清（有意为之，不落用户数据）；
- 空间**不产生真实任务**，除非配置了接口或访客自填 key。
