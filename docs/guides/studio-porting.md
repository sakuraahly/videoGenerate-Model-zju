# 魔搭创空间打包适配方案（2026-09-08）

## 1. 目标与边界
用户目标：本项目（text/video 生成管线 + ComfyUI + Qwen 调度 + 成品链）**整体打包上传魔搭创空间（ModelScope Studio）**。
**硬边界（实事求是）**：本管线核心=spark（DGX GB10）上 MiniMax-H3 推理（>40GB 模型）+ ComfyUI + 多 venv 工具链；创空间免费档=2vCPU/16GB（GPU 仅为计划/付费）——**整体不可迁移**。创空间定位=**展示+交互入口层**；spark=**引擎层**（其 106.13.186.155 有公网 IP，可暴露受控 API）。

## 2. 创空间事实（2026-09-08 调研）
| 项 | 结论 | 来源 |
|---|---|---|
| 形态 | HF Spaces 式应用托管（Gradio/Streamlit/Static） | CSDN《ModelScope创空间使用》 |
| 发布方式 | 创建后获得 git 仓储地址；git clone→改 app.py→push | 同上 |
| 认证 | 个人头像→账号设置→访问令牌（token）供 git push | 同上 |
| 资源 | 免费 CPU 2vCPU/16GB（闲置休眠、访问自动激活）；免费 GPU 活动计划；付费升配=绑定阿里云+PAI，可设休眠 | 同上 |
| 计费 | 公开空间访问触发运行并计费（付费规格时） | 同上 |
| 社区实践 | 有在创空间部署 ComfyUI/sd-webui 的尝试（Torch/CUDA 报错=GPU 规格问题） | 阿里云问答 589001 |

## 3. 适配设计（M1→M3）
**M1 静态展示版**（免费 CPU，先上线）：
- Gradio `app.py`：项目介绍 + **片墙**（video_50-79 精选样片内嵌/外链）+ 流程说明（意图→参考→生成→成品链）+ 交互表单（剧情描述/台词/音色/风格）→ 提交后展示「演示模式」结果（prebuilt 结果卡）；
- `config.yaml`（sdk: gradio；app_file: app.py）+ `requirements.txt`（gradio）+ `README.md`（项目说明+许可）+ `assets/`（样片压缩小尺寸）。
**M2 远程调度版——实施中（2026-09-09）**：
- spark 侧：`runs/api/studio_gateway.py` **已写+本机全流程自测通过**（stdlib 零依赖；`STUDIO_TOKEN` 鉴权(≥16)、字段白名单、留痕 logs/studio_jobs.jsonl、72h 下载有效期、`STUDIO_MODE=mock|real` 双模式；证据：401/400/提交/状态流转/download 200/404 全过）。
- 创空间侧：`studio/app.py` 已升级**双模式**（env `REMOTE_API`+`STUDIO_TOKEN` 注入→远程提交卡；失败自动降级演示卡——本地 stub 联调 OK/FAIL 双分支通过）。
- **公网通道实测（负结论，关键）**：106.13.186.155 **仅 8080 TCP 可连**（80/443/22/8000/8188/7860 全不通），但**外部 HTTP 无响应**（curl -v：TCP 建立+GET 发出+服务端无回；spark 本机 localhost API 正常）→ 判定 8080 被云侧代收但未转发实例（或 EIP 映射缺失），非应用问题。
- **打通路线（账号侧/用户操作）**：①阿里云控制台核实 8080 端口映射/安全组（期望公网 8080 直达 http.server；当前疑云网关代收）②HTTPS 方案（证书+443+反代）或云 API 网关 ③创空间部署后云端出网实测 `requests.get('http://106.13.186.155:8080/v1/health')`；三选一验证通过→启用 real 模式。
- 服务化挂 tmux/开机=授权项；mock 模式随时可演示。
**M3 可选**：创空间免费 GPU 到位 → 单点模型演示（CosyVoice TTS 等小模型）。

## 4. 里程碑与验收
- M1：创空间 URL 可打开、片墙播放、表单可用；**✅ 验收通过（2026-09-08）**——`wumingyong0/Automated_video_generation`（应用内嵌空间页；用户确认运行中/片墙/表单正常）；发布路径=匿名 clone→铺入 repo `studio/` 全套→token 一次性 push（未落盘）；本地验证=HTTP200/53 组件/13 媒体/1 表单依赖。
- M2：从创空间提交一个真实任务→进度→下载成片（ASR 判据同引擎）；前置实测=创空间应用出网可达性（106.13.186.155）→ 通过后实施 `runs/api/studio_gateway.py`（鉴权+提交/状态/下载）；
- 每里程碑后文档回写 + 双端提交（按 skills/dev-workflow）。

## 5. 红线/注意
- 不暴露引擎服务器路径（沿用输出边界）；token 不入库（环境变量/密钥文件 gitignore）；
- 样片均为本机生成（版权安全）；参考素材=项目自有；
- 公开空间计费与休眠政策：演示期选免费档并注意访问触发；
- 若平台不支持出网→M2 改为「结果回传=用户填邮件/网盘」或仅 M1（如实告知用户）。