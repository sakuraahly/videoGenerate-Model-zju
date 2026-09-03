# H3 提示词工程速查

> 完整版：skills/h3-prompt-engineering.md

## 核心原则

1. **英文提示词** — H3 模型训练数据以英文为主
2. **具体描述** — 避免模糊词汇，详细描述画面内容
3. **结构化** — 主体 + 环境 + 光影 + 风格 + 镜头运动
4. **避免负面** — 不要写"不要xxx"，用正向描述替代

## 提示词结构模板

```
[主体描述], [动作/姿态], [环境/背景], [光影/氛围], [风格/画质], [镜头运动]
```

## 示例

**文生视频 (t2v)**:
```
A young warrior standing on a cliff edge, wind blowing through long hair,
overlooking a vast ocean at sunset, golden hour lighting, cinematic quality,
slow camera pan from left to right
```

**文生图 (text2img)**:
```
A mystical forest clearing with ancient trees, soft dappled sunlight
filtering through the canopy, wildflowers blooming on the mossy ground,
ethereal atmosphere, highly detailed, fantasy art style
```

## 负面提示词（可选）

```
blurry, low quality, distorted, deformed, ugly, duplicate,
watermark, text, logo, cropped, out of frame
```

## 常见错误

- 中文提示词 → 效果差，翻译为英文
- 过于简短 → "a cat" 不如 "a fluffy orange cat sitting on a windowsill"
- 包含禁止内容 → 模型会拒绝，调整描述方式
- 忽略镜头运动 → 视频生成建议加入 camera movement 描述
