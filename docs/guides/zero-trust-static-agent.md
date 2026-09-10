# 零信任形态：只发布工具，密钥不出用户浏览器（2026-09-10 调研 + 落地）

> 起因：用户提出「让别人用我的 API 不可靠」→ 改成 BYOK 后又有新问题：**BYOK 里 Key 仍要经过空间服务器**，
> 等于要使用者信任运营方。本文是调研结论与落地结果。

## 1. 结论（先看这段）

**可以做成真正的零信任**：把 Agent 逻辑放到**纯前端页面**里，由**使用者的浏览器直接调用他自己填的模型服务**，
我们的服务器只提供静态文件——**Key 从头到尾不经过我们**。可行性取决于服务商是否允许浏览器跨域调用，
**实测三家主流服务商都允许**：

| 服务商 | 预检 OPTIONS | `Access-Control-Allow-Origin` | 结论 |
|---|---|---|---|
| 阿里云百炼（DashScope compatible-mode） | 200 | `*`（还允许 `authorization,content-type`） | ✅ 可浏览器直连 |
| DeepSeek | 200 | 回显请求 Origin（等价允许任意站点） | ✅ 可浏览器直连 |
| 魔搭 API-Inference | 200 | `*` | ✅ 可浏览器直连 |

（实测命令见文末附录。）

## 2. 三种形态与取舍

| 形态 | 使用者要信谁 | 你的成本 | 使用门槛 | 适合 |
|---|---|---|---|---|
| **① 零信任单页**（本次新增） | **谁都不用信**（Key 只在浏览器） | **0** | 打开网页 + 填自己 Key | 公开分享给任何人 |
| ② 创空间 BYOK | 要信运营方（Key 经其服务器） | 0（不含算力） | 同上 | 想要在线对话式体验 |
| ③ 自己部署（clone 本仓库） | 谁都不用信 | 0 | 会跑 Python | 团队内、要接自己的 GPU |

## 3. 现在怎么用（已上线）

**零信任单页**（GitHub Pages 托管，仓库公开即自动发布）：

- 入口：<https://sakuraahly.github.io/videoGenerate-Model-zju/>
- 直接用：<https://sakuraahly.github.io/videoGenerate-Model-zju/web/agent.html>

页面里填「模型服务地址 / 模型名 / API Key」（以及可选的你自己的视频生成接口），然后直接说需求：

- Agent 逻辑（工具选择 + 参数）在浏览器里跑，**请求直发你填的服务**；
- 选好工具后页面给出**交给视频接口的请求体**，可「复制 curl」在自己机器上跑（不受浏览器跨域限制），
  或点「用我的引擎直接跑」由浏览器直发你的网关（需要你的网关允许 CORS）；
- 勾选「记住到本浏览器」才会写入 `localStorage`（仅本机）；不勾则关页面即失效；
- 页面不含任何第三方脚本、CDN、埋点——单文件 HTML，可另存到本地/内网自行托管。

## 4. 两种托管方式（都不用我们）

1. **GitHub Pages（现在这个）**：文件在仓库 `web/agent.html`，推送即生效；
2. **自己/内网托管**：把 `web/agent.html` 下载下来丢进任意静态服务器（nginx/对象存储/甚至本地双击打开）。
   注意：以 `file://` 打开时浏览器 Origin 为 `null`，百炼/魔搭（`*`）可用，DeepSeek（回显 Origin）可能被拒——
   稳妥做法是放到任意 http(s) 静态服务上。

## 5. 创空间（形态②/演示页）该怎么摆

推荐 posture（**只发布工具**）：

1. 空间变量/密钥里**不要留任何你的 Key**（填 `unset`）；
2. 加一个变量 **`ALLOW_ENV_FALLBACK=0`** → 页面会提示使用者填自己的（不填只能看演示/规则规划器）；
3. 页面已挂上零信任单页的链接，引导「完全不信任运营方」的人走形态①；
4. 想给体验额度时再填自己的 Key（默认 `ALLOW_ENV_FALLBACK=1`，使用者填了自己的就优先用他的）。

## 6. 边界与已知限制（如实说明）

- **模型服务必须允许浏览器跨域**（上面三家已实测）；若使用者用的是不允许 CORS 的私有网关，页面会报错并提示改用「复制 curl」；
- **视频引擎同理**：多数自建网关默认不开 CORS → 页面提供 curl 兜底；
- 零信任单页**没有服务端任务台账/持久化**（这是有意的：不落任何数据），任务查询靠使用者自己的引擎接口；
- 前端能看到的逻辑都是公开的（本就是发布工具），但**不含任何密钥**；
- 仍需提醒使用者：Key 用完请轮换/删除，额度用尽风险由他自己控制。

## 附录：CORS 实测命令

```powershell
# 预检
Invoke-WebRequest -Uri 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions' -Method Options `
  -Headers @{ 'Origin'='https://example.com'; 'Access-Control-Request-Method'='POST';
              'Access-Control-Request-Headers'='authorization,content-type' } -UseBasicParsing
# 实测结果：access-control-allow-origin: * ；allow-headers: authorization, content-type
```

## 附录：前端逻辑自测（node，无需浏览器）

```bash
# 抽出页面里的 <script> 后：
node --check agent_check.js          # 语法
node test_static.js                  # 解析容错 + 四个工具的请求体映射（本次全部通过）
```
