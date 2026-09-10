# H3 视频创作 Agent · 魔搭创空间

> **本空间只部署 Agent，不部署任何模型**；模型能力全部由你（或访客）通过 **API 接口**接进来。
> 代码可下载、可自部署：<https://github.com/sakuraahly/videoGenerate-Model-zju>（目录 `studio/`）
> 版本 **v3.2**（2026-09-10）

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

## 三、密钥归属（谁来付钱）

1. **访客自带（BYOK）**：页面「🔑 我的密钥」填自己的 key，只在该会话内存里，**不写盘、不进日志**，按会话隔离；
2. **零信任单页**：Agent 跑在访客浏览器里直连其模型服务，**key 不经过任何服务器** →
   <https://sakuraahly.github.io/videoGenerate-Model-zju/web/agent.html>；
3. **运营方体验额度**：空间变量里填一套（默认），访客填了自己的优先用他的；设 `ALLOW_ENV_FALLBACK=0` 则空间完全不提供密钥。

## 四、下载与自部署

```bash
git clone https://github.com/sakuraahly/videoGenerate-Model-zju.git
cd videoGenerate-Model-zju/studio
pip install -r requirements.txt
python app.py --port 7860        # 打开 http://127.0.0.1:7860
```

- 不接任何接口也能跑：进入**规划演示**（展示决策与请求体，不产生任务、不联网）；
- 接上第一节的两个接口即真实出片；**空间内不跑任何模型**，画质由你接的服务决定；
- 部署到魔搭创空间：把 `studio/` 内容推到空间仓库 → 触发平台重建即可。

## 五、页面结构

- **🤖 Agent 对话**：说需求 → 工具调用轨迹 + 本轮产物 + 任务面板（可刷新状态）；
- **🎛 创作台**：表单式创作（任务类型/提示词/参考图/分辨率/时长/音色/字幕 → 提交 → 预览下载）；
- **🎞 样片墙**：参考样片（含 ASR 分数、字幕、口型）；
- **🧭 能力与部署**：能力点、流程、部署说明，以及 **🔌 测试外置大脑连接**（一键验证你的 key 通不通）。

## 六、安全与边界

- 已加固：拒云元数据地址（SSRF）、任务号白名单（防路径穿越）、下载文件名清洗、上传与台账内存上限、
  产物目录随机化（防跨用户猜链接）、刷新与轮询限流、密钥不回显；
- 空间**无持久化**：会话结束即清（有意为之，不落用户数据）；
- 空间**不产生真实任务**，除非配置了接口或访客自填 key。
