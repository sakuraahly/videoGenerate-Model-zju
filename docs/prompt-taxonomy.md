# H3 提示词属性词库（正向 / 负向 分类清单）

> 版本：v1.0 · 日期：2026-09-04 · 来源：用户提供（2026-09-04）。
> 用途：作为 `docs/planbook` book-06（工作流提示词清理与注入）**保留/注入的图像属性词库**，也是 `skills/h3-prompt-engineering.md` 词库的补充。
> 原则：工作流 `video_*` 模板内嵌的**英文故事文案**要删除，**只保留这类图像属性/质量词**；画面主体内容由 agent 经 `idea2prompts`（按段）注入。

---

## 一、正向提示词（10 大类）

| # | 类别 | 关键词（示例） |
|---|---|---|
| 1 | Quality & Rendering | masterpiece, best quality, ultra detailed, 8k, photorealistic, octane render |
| 2 | Lighting | cinematic lighting, volumetric lighting, golden hour, rim lighting, chiaroscuro |
| 3 | Composition & Framing | rule of thirds, depth of field, close-up, low angle, POV |
| 4 | Camera & Lens | shot on 35mm, anamorphic lens, film grain, cinematic color grading |
| 5 | Color & Tone | vibrant colors, warm tones, teal and orange, HDR |
| 6 | Style & Aesthetic | concept art, cyberpunk, studio ghibli style, oil painting |
| 7 | Atmosphere & Mood | ethereal, epic, mysterious, immersive |
| 8 | Subject-Specific Details | detailed face, perfect anatomy, realistic skin |
| 9 | Environment & Background | detailed background, scenic, futuristic city |
| 10 | Video-Specific | smooth motion, tracking shot, slow motion, 24fps |

### 保留/注入约定
- 工作流模板内嵌质量/属性词按 **类别 1（Quality & Rendering）** 为主，可结合 2/3/4/5/10 形成稳定的「属性前缀」（见 book-06 示例）。
- 风格（类别 6）与特定画风按任务需要选用；**默认模板**只保留「基础质量 + 高清 + 去模糊/去噪 + 无瑕疵」等通用属性。
- 画面主体/动作/镜头/音频描述由 agent 逐段生成并注入，不作为模板固定文案。

---

## 二、负向提示词（9 大类）

| # | 类别 | 关键词（示例） |
|---|---|---|
| 1 | Quality Degradation | blurry, low quality, noisy, jpeg artifacts |
| 2 | Anatomy & Proportion Errors | bad anatomy, extra fingers, deformed, bad hands |
| 3 | Artifacts & Glitches | distortion, watermark, text, logo, chromatic aberration |
| 4 | Lighting & Exposure Issues | overexposed, flickering, red eye |
| 5 | Composition Issues | cropped, cut off, cluttered |
| 6 | Unwanted Content | nude, nsfw, gore |
| 7 | Style Unwanted | cartoon, anime, sketch（按任务反向使用） |
| 8 | Video-Specific Negatives | flickering, jittery, identity drift, temporal inconsistency |
| 9 | Rendering Errors | clipping, uncanny valley, plastic skin, z-fighting |

### 使用约定
- 负向词作为**负面约束收尾**（H3 提示词工程 `skills/h3-prompt-engineering.md` 规则 6：`No text, no watermark, no cuts...`），并按任务在类别 8（视频特异）上重点加。
- 类别 7（Style Unwanted）**按任务反向使用**：如要写实，则禁止 cartoon/anime；若任务要动画风则相反。
- 与 `prompts/negative_prompts.txt` 现有负向块合并时避免重复，保留「文字/水印/低清/扭曲」等核心项。

---

## 三、与现有文件的关系
- `prompts/negative_prompts.txt`：当前为"文字/水印/低清"等负向块，可并入本词库类别 1/3/5/8 的精选集合。
- `prompts/positive_prompts.txt`：当前含一段 10 秒故事 + 中文字幕（`2077年，新上海...`）——**属故事文案**，按 book-06 需清为属性词或交给 idea2prompts 注入。
- `config/prompt_blueprints.json`：补充「属性词保留清单」与「逐段转场生成」指导。

---

## 四、待定
- 各工作流模板实际固化哪几类、哪些词作为默认「属性前缀」→ 待实施时与用户确认主清单（用户已给 10 正 + 9 负分类，可据此筛选）。
- 是否把本词库接入 `idea2prompts.py` 的 `build_messages`/`prompt_blueprints.json` 作为生成约束 → book-06/07 实施时落地。