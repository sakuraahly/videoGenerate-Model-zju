# Studio Packaging Skill — 魔搭创空间打包上传（目标卡）

> 目标（2026-09-08 用户定案）：**本视频生成项目整体打包上传到魔搭创空间（ModelScope Studio）**。
> 先读：`docs/CURRENT-STATE.md`、`docs/guides/studio-porting.md`（适配方案）、`docs/planbook/book-19-execution-ready.md §15f`（计划）。

## 关键事实（已调研，2026-09-08）
- 创空间=HF-Spaces 式应用托管：创建后获得 **git 仓储地址**（git clone 下载 → 修改 app.py 等 → push 上传）；
- 上传认证：**个人头像 → 账号设置 → 访问令牌（token）** 用于 git push；
- 资源：新用户免费基础 **CPU（2vCPU/16GB）**，闲置休眠自动激活；计划提供免费 GPU 活动；付费升配（绑定阿里云+开通 PAI，可选 CPU/GPU，计费+可设休眠）；
- 应用结构（通用）：`app.py`（入口）+ `sdk: gradio/streamlit` 配置 + `requirements.txt` + `README.md`；
- 参考链接：CSDN《ModelScope创空间使用》（144987975）+ 社区 modelscope-studio-deploy skill + 阿里云问答（创空间部署 ComfyUI 场景）。

## 适配方案（设计定稿）
- **不能整体塞入**：本管线=GB10 推理+ComfyUI（>40GB 模型+GPU）——创空间免费档 2vCPU/16G 跑不动；付费 GPU 档也不承载本机全套。
- **分层**：创空间=「展示+交互入口」层；spark（106.13.186.155 公网 IP）=「引擎」层（远程 API 调度，鉴权 token）。
- **M1（静态展示版，免费 CPU 即可）**：Gradio 应用——片墙（video_52-79 精选）+ 流程说明 + 交互表单（剧情/台词/风格），提交=演示如何询价/排队（不发真实任务）；
- **M2（远程调度版）**：应用经公网 HTTPS 调用 spark 提交服务（新建轻量 API：鉴权 token + 提交/查询/下载），成片回传（尺寸限制）；平台出网需实测（创空间应用能否访问公网 IP）；
- **M3（可选）**：若平台免费 GPU 到位 → 轻量模型演示（如本项目 TTS/CosyVoice 单点能力）。

## 执行清单（实施时用）
1. 注册/登录 modelscope → 创建创空间（名称/描述/公开）→ 记 git 地址+生成 token；
2. `git clone` 空间仓库 → 编写 `app.py`（Gradio）+ `config.yaml` + `requirements.txt` + `README` + `assets/`（样片）；
3. 本地验证（gradio 启动）→ M1 提交（片墙+表单）；
4. M2：spark 新增 `runs/api/studio_gateway.py`（FastAPI? 最小 flask：POST /submit, GET /status, GET /download + token) + 系统服务 + 公网安全组放行 + HTTPS/自签；创空间侧 `studio_remote.py` 对接；
5. 文档回写（本卡+§15f）+ 双端提交；
6. 验收：创空间页面可打开、样片可播、表单可达；M2 真机任务=提交→进度→成片下载。

## 陷阱/注意
- 创空间休眠：免费档闲置自动休眠（激活=访问触发）；长任务时段选择付费不休眠；
- 样本版权：demo 样片均为本机生成（无外部素材版权风险）；参考图=自备素材；
- 输出脱敏：创空间 UI 同样不暴露服务器路径（沿用输出边界规则）；
- git 上传：token 授权；大文件（>100MB）慎入 git（样片压缩/外链）；
- 公开空间访问即触发运行（计费注意）。