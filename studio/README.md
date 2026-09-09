---
# 详细文档见https://modelscope.cn/docs/%E5%88%9B%E7%A9%BA%E9%97%B4%E5%8D%A1%E7%89%87
domain: multi-modal
tags:
- video-generation
- text-to-video
- cool-demo
- gradio
datasets:
  evaluation: []
  test: []
  train: []
models: []
license: Apache License 2.0
---

# H3 视频生成工坊（创空间自包含演示版 v1.2）

> 本项目完成的**成品能力展示空间**：片墙 + 制作流程 + 演示表单（**自包含**，不依赖任何外部服务器；
> 免费 CPU 档零依赖、秒级启动）。

## 本空间提供
- **成品片墙**：6 部本机生成样片（720p 直出 / r2v 参考图连贯 / 真台词无框 / keep 原声 / ComfyUI 全链 / RIFE 48fps），可播放；
- **制作流程**：灵感 → 提示词 → 生成 → 成品链（真台词/字幕/旁白/口型无框）→ ASR 双轨验真 五步；
- **演示表单**：剧情/台词/音色/风格/分辨率 → 演示结果卡 + 风格匹配样片（示例一键填充）。

## 限制（如实说明）
- 演示表单**不产生真实生成任务**（H3 视频引擎需要 GPU 与数十 GB 模型，免费 CPU 档无法承载）；
- 完整生成能力（含口型/字幕/旁白）见项目文档；M3（平台 GPU/TTS 单点演示）视免费 GPU 规格到位后另行上线。

## 运行
```bash
# 本地预览（创空间零依赖，本地也仅需平台同款 gradio）
pip install gradio
python app.py --port 7860
```

## 许可
Apache License 2.0；样片与代码为本项目（videoGenerate-Model-zju）自有；参考素材=项目自备。
