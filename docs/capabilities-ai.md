# 项目生成能力（自动生成：由 config/capabilities.json 生成，勿手改本文件）

引擎：`videoGenerate-Model-zju` @ spark (DGX Spark, ComfyUI 127.0.0.1:8188, ssh 免密)
模型：视频 MiniMax H3（本地推理，spark GPU，无需云）；文生图 FLUX.1-dev（本地文生图）；LLM Qwen3.8-27B（vLLM, OpenAI 兼容 /v1, spark 127.0.0.1:8000）

## 视频工作流（workflows）

| id | 用途 | 引擎 | 图需求 | 提示词槽位 |
|---|---|---|---|---|
| `video_t2v` | text-to-video (official standard template) | `local` | none | `video_t2v` |
| `video_i2v` | image-to-video: animate from one first frame | `local` | 1 first-frame image | `video_i2v` |
| `video_r2v` | reference-to-video: keep 1-2 reference images (character/scene) consistent | `local` | 1-2 reference images | `video_r2v` |
| `video_flf2v` | first-frame + last-frame video (local extension of i2v) | `local` | 2 images (first, last) | `video_flf2v` |
| `api_t2v` | text-to-video via MiniMax Hailuo official API (Comfy cloud login required) | `comfy-cloud` | none | `api_t2v` |
| `api_r2v` | reference-to-video via Hailuo API (Comfy cloud login required) | `comfy-cloud` | 1-2 reference images | `api_r2v` |
| `api_flf2v` | first+last frame via Hailuo API (Comfy cloud login required) | `comfy-cloud` | 2 images (self-provided example) | `api_flf2v` |

- 槽位文件：`prompts/workflows/<slot>.{positive,negative}.txt`；空/缺失回退 default（`prompts/positive_prompts.txt`）；编辑入口 `bats/prompts/prompts.bat`。

## 工具（tools）

### generate_reference_image
Generate a reference image with local FLUX.1-dev (text-to-image). Output lands in spark ~/ai/ComfyUI/input/<name>.png (usable by image-conditioned video workflows) and a local copy under refs/.

用法：
```
python runs/h3_text2img_flux.py --text "<detailed English visual description>" --name <snake_case> [--width 1344] [--height 768] [--steps 28] [--seed N]
```

参数：
  - `text` (string): English visual description, concrete subject/scene/lighting/style
  - `name` (string): Output base name; becomes spark input/<name>.png and refs/<name>.png
  - `width` (integer): ，默认 1344
  - `height` (integer): ，默认 768
  - `steps` (integer): ，默认 28
  - `seed` (integer): ，默认 random
### generate_video
Run a video-generation workflow with MiniMax H3 (local inference on spark). Prompt content is taken automatically from the workflow's prompt slot file (see prompts/), or override with --prompt-file.

用法：
```
python runs/h3_submit.py --stage <workflow_id> [--resolution 360p|480p|540p|720p|768p] [--seconds 5..15] [--seed N] [--force-new] [--dry-run]
```

参数：
  - `stage` (string): workflow id, see workflows below
  - `template` (string): exact template json path as alternative to --stage
  - `resolution` (string): 
  - `seconds` (number): 
  - `seed` (['integer', 'string']): 
  - `timeout` (integer): ，默认 3600
  - `dry_run` (boolean): validate without consuming GPU

## 给 LLM 的提示
Prompts you write for the video workflows must follow the rules in config/prompt_blueprints.json (positive & negative in English JSON, include audio, end with negative constraints).
