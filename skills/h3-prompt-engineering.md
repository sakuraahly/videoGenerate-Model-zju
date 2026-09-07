# H3 Prompt Engineering Guide

> **Purpose**: Transform a user's raw scene idea into a prompt that maximizes MiniMax H3 output quality.  
> **Applies to**: All H3 video generation tasks.

---

## Prompt Structure

Every H3 prompt must follow this structure (order matters):

```
[Duration + shot type + setting]
[Camera framing + subject description + action]
[Specific visual details / text rendering instructions]
[Camera movement]
[Audio description: ambience, SFX, dialogue, music]
[Negative constraints: what NOT to include]
```

---

## Rules

### 1. Lead with Duration and Shot Type

Always start with the expected duration and shot classification:
```
A five-second cinematic shot...
A three-second close-up...
A ten-second wide establishing shot...
```

This anchors the model's temporal expectations.

### 2. Describe Physical Actions, Not Abstract Concepts

BAD: `A teacher demonstrates calligraphy`  
GOOD: `A teacher's back and right hand as they slowly write characters on a dark green chalkboard with white chalk`

H3 understands physicality. Describe bodies, hands, tools, surfaces.

### 3. Chinese Text Rendering (Critical — 乱码 Prevention)

H3 was primarily trained on English text. Chinese character rendering requires special techniques:

**a) Enumerate characters individually:**
```
The characters appear one by one: first '你', then '好', then '，', then '朋', then '友'
```

**b) Specify the script style:**
```
in clear, standard regular script (楷体)
```

**c) Describe the physical writing process:**
```
writing with white chalk, stroke by stroke
```

**d) Limit text to 5-6 characters maximum.** Longer strings almost always produce garbling.

**e) If exact text is critical, add a fallback:**
```
If characters are unclear, the overall impression of writing on a chalkboard should still be clear.
```

### 4. Camera Movement — Be Specific

BAD: `The camera moves around`  
GOOD: `The camera holds steady with slight handheld movement`  
GOOD: `One slow lateral tracking shot from left to right`  
GOOD: `A gentle push-in toward the subject's face`

H3 responds well to cinematography vocabulary: tracking, push-in, pull-back, pan, tilt, handheld, steadicam, locked-off.

### 5. Audio Description — Always Include

H3 generates video and audio jointly. Even if the user says "no sound", describe the absence:

```
No dialogue, no music. Only ambient room tone and the soft click of keyboard keys.
```

If there IS sound, describe it in layers:
```
Foreground: chalk scratching on the board.
Midground: a chair creaking softly.
Background: distant birds chirping outside the window.
```

### 6. Negative Constraints — End the Prompt

Always close with explicit exclusions:
```
No dialogue, no music, no cuts.
No text overlays, no subtitles.
No fast motion, no camera shake.
```

This prevents the model from hallucinating unwanted elements.

### 7. One Continuous Shot

H3 works best with single-shot descriptions. Avoid:
```
First the teacher writes, then the students applaud, then the bell rings.
```

Instead:
```
The camera holds on the teacher for the full five seconds as they complete the phrase.
```

If multiple shots are needed, generate them as separate videos and edit together.

---

## Prompt Templates

### Template: Person Writing Text

```
A {duration}-second {shot_type} in a {setting}.
{Camera framing} of {subject}'s {body part} as they {action} on {surface} with {tool}.
The {characters/text} appear one by one in {script_style}: first '{char1}', then '{char2}', ...
forming the complete phrase '{full_text}'.
{Camera movement}.
{Audio layers}.
No dialogue, no music, no cuts.
```

### Template: Environmental Scene

```
A {duration}-second {shot_type} of {environment}.
{Weather/lighting description}.
{Foreground elements and motion}.
{Camera movement}.
{Ambient audio description}.
No text, no dialogue, no cuts.
```

### Template: Object/Product Showcase

```
A {duration}-second {shot_type} of {object} on {surface/background}.
{Lighting description: studio, natural, dramatic, etc.}.
{Object details: material, color, texture}.
{Camera movement: orbit, push-in, etc.}.
{Subtle audio: surface contact sounds, ambient room tone}.
No text, no music.
```

---

## Common Mistakes

| Mistake | Why It Fails | Fix |
|---|---|---|
| `Write "你好朋友" on the board` | Model tries to render all chars at once → garbled | Enumerate: first '你', then '好'... |
| `A beautiful sunset` | Too abstract, no physical detail | Describe colors, cloud shapes, light angles |
| `The character talks about AI` | Dialogue is hard for H3 | Describe the physical act of speaking, or use ambient sound only |
| `A 30-second video` | Exceeds tested max of 15s | Split into multiple 5-10s clips |
| `In the style of Studio Ghibli` | Style transfer not supported | Describe the visual qualities directly: soft pastel colors, hand-drawn feel |
| Omitting audio | Wastes joint audio-video capacity | Always describe audio, even if it's "silence" |

---

## Language Notes

- Prompts in **English** produce more reliable results than Chinese prompts
- Chinese characters should appear only as **quoted target text**, not as prompt language
- Use English cinematography terms (tracking shot, close-up, etc.)
- Specify Chinese script style in both English and Chinese: `regular script (楷体)`

---

## 8. 参考图/参考媒体 tag 契约（R2V 与分镜剧本必守，2026-09-07 沉淀）

- **`<Picture N>` 从 1 起**，与 `--image` 参数顺序**一一对应**（第 1 张=Picture 1）；tag 数量=参考图数量，多余/缺失会触发引擎校验拒绝（`--no-check-ref-tags` 仅调试）。用户分镜工具脚本里的 `<Picture 0>` 需改写为 1 起。
- **明确"谁管什么"**：第一段必须逐图声明用途，如 `<Picture 1> is the interior room ... <Picture 2> is the protagonist ... <Picture 3> is the prop ...`，并紧跟 "Use them as exact references --- match their art style, color and lighting exactly."——防止模型把参考图当首尾关键帧。
- **参考贯穿全片**（身份/风格保真）：加固定语义句 "All references define identity and style that persist through the whole shot; they are not first-frame or last-frame keyframes."
- **S7 媒体**：`<Video N>`（运动/镜头参考）与 `<Audio N>`（氛围/音色参考）同样一一对应；只能参考**同镜头**素材（错误示例：2026-09-07 把另一镜头分镜当运动参考会带偏）。
- **剧本块（多时间点连续单镜）写法**：`Shot N -- scene ...:` 后逐行 `0.0-1.2s: 动作描述`——每行写**物理可见动作**（人从哪跑到哪、看什么、表情变化），不写抽象情绪；结尾补镜头语言（"Keep the action natural and the camera steady but slightly following him."）。
- **负面清单有效写法**（直接给出排除集）：`no warped or distorted human bodies, no mumbling or slurred speech, no missing characters, no distorted faces, no improper limb proportions, no unnatural motion, no blurred facial expressions, no unclear speech, no noise covering dialogue, no text, no watermark, no extra people`。
- **实战样例**：`docs/handoff-2026-09-07-live.md` §7（镜头17：3 参考图 + 时间轴剧本 + 上述负面集，抽帧全过）。
