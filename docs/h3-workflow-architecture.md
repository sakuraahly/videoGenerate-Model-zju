# MiniMax H3 Video Generation — Workflow Architecture

## Overview

MiniMax H3 is an omni-modal video generation model that jointly produces video + native stereo audio from a text prompt. It runs on ComfyUI via a flat API-format workflow graph of 14 nodes.

**Target hardware**: DGX Spark (NVIDIA GB10, aarch64, 128 GB unified memory)  
**Model format**: INT8 quantized diffusion model + NVFP4-AWQ text encoder + FP16 video VAE + FP32 audio VAE  
**Output**: MP4 video with audio, up to 2K resolution, 24 fps, ~5–15 seconds

---

## Model Files

| File | Location on Spark | Purpose |
|---|---|---|
| `minimax_h3_fl2va_pruned_int8_convrot.safetensors` | `models/diffusion_models/` | Diffusion model (INT8) |
| `qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors` | `models/text_encoders/` | Text encoder (Qwen3VL 32B, NVFP4-AWQ) |
| `minimax_h3_video_vae_fp16.safetensors` | `models/vae/` | Video VAE decoder |
| `minimax_h3_audio_vae_fp32.safetensors` | `models/vae/` | Audio VAE decoder |

All paths relative to `~/ai/ComfyUI/`.

---

## Node Graph (Flat API Format)

```
UNETLoader [1] ────── MODEL ──┬── BasicScheduler [8] ── SIGMAS ──┐
                              │                                   │
                              └── BasicGuider [6] ── GUIDER ──┐  │
CLIPLoader [2] ── CLIP ──┐                                    │  │
                          ├── MiniMaxH3ImageToVideo [5]       │  │
VAELoader [3] ── VAE ──┤   ├─ positive ── BasicGuider [6]    │  │
                          └─ LATENT ── SamplerCustomAdvanced [10]
VAELoader [4] ── VAE ───────────────────────────────────┐      │
                                                         │      │
RandomNoise [9] ── NOISE ───────────────────── SamplerCustomAdvanced [10]
KSamplerSelect [7] ── SAMPLER ───────────────── SamplerCustomAdvanced [10]
BasicScheduler [8] ── SIGMAS ────────────────── SamplerCustomAdvanced [10]
                                                         │
                                              output LATENT
                                                  │
                                          ┌───────┴───────┐
                                     VAEDecode [11]   VAEDecodeAudio [12]
                                          │                │
                                       IMAGE            AUDIO
                                          │                │
                                          └── CreateVideo [13]
                                                   │
                                                 VIDEO
                                                   │
                                            SaveVideo [14]
```

---

## Node Details

### 1. UNETLoader
Loads the diffusion model into GPU memory.
- `unet_name`: `"minimax_h3_fl2va_pruned_int8_convrot.safetensors"`
- `weight_dtype`: `"default"` (let ComfyUI handle precision)

### 2. CLIPLoader
Loads the text encoder. The `type` field MUST be `"minimax"` — using any other type will cause silent failures or garbled output.
- `clip_name`: `"qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors"`
- `type`: `"minimax"`

### 3. VAELoader (video)
- `vae_name`: `"minimax_h3_video_vae_fp16.safetensors"`

### 4. VAELoader (audio)
- `vae_name`: `"minimax_h3_audio_vae_fp32.safetensors"`

### 5. MiniMaxH3ImageToVideo
Core conditioning node. Takes the prompt, encodes it with the CLIP, and produces:
- **Output 0** (`positive`): CONDITIONING — used by BasicGuider
- **Output 1** (`LATENT`): empty latent with correct dimensions — used by SamplerCustomAdvanced

Parameters:
- `clip`: link from CLIPLoader
- `vae`: link from video VAELoader
- `prompt`: STRING — the scene description (see prompt engineering guide)
- `width`: INT — 必须是 **8 的倍数**（引擎校验值；内置预设本身均为 32 的倍数）。推荐：864（16:9，约 0.4 MP）
- `height`: INT — 必须是 **8 的倍数**（同宽）。推荐：480
- `length`: INT — frame count at 24 fps. Must snap to `17k+5` grid. Use 124 for ~5 seconds.
- `first_frame` (optional): IMAGE — for image-to-video
- `last_frame` (optional): IMAGE — for image-to-video

### 6. BasicGuider
Wraps the model + conditioning into a GUIDER object for advanced sampling.
- `model`: from UNETLoader
- `conditioning`: from MiniMaxH3ImageToVideo output 0

### 7. KSamplerSelect
Selects the sampling algorithm.
- `sampler_name`: `"res_multistep"` (recommended for H3)

### 8. BasicScheduler
Computes the noise schedule.
- `model`: from UNETLoader
- `scheduler`: `"simple"`
- `steps`: 20 (higher = better quality, slower)
- `denoise`: 1.0 (full denoise for text-to-video)

### 9. RandomNoise
Generates the initial noise tensor.
- `noise_seed`: INT (any value; same seed = reproducible output)

### 10. SamplerCustomAdvanced
The actual denoising loop. All five inputs are required.
- `noise`: from RandomNoise
- `guider`: from BasicGuider
- `sampler`: from KSamplerSelect
- `sigmas`: from BasicScheduler
- `latent_image`: from MiniMaxH3ImageToVideo output 1

### 11. VAEDecode
Decodes the denoised latent into pixel-space video frames (IMAGE batch).
- `samples`: from SamplerCustomAdvanced output 0
- `vae`: from video VAELoader

### 12. VAEDecodeAudio
Decodes the audio portion of the same latent.
- `samples`: from SamplerCustomAdvanced output 0
- `vae`: from audio VAELoader

### 13. CreateVideo
Combines IMAGE frames + AUDIO into a VIDEO container.
- `images`: from VAEDecode
- `fps`: 24.0
- `audio`: from VAEDecodeAudio

### 14. SaveVideo
Writes the final MP4 to disk.
- `video`: from CreateVideo
- `filename_prefix`: `"video/MiniMax_H3"` (saved to `ComfyUI/output/video/`)
- `format`: `"auto"`
- `codec`: `"auto"`

---

## ComfyUI API Format

The workflow is submitted as JSON to `POST /prompt`:

```json
{
  "prompt": {
    "1": { "class_type": "UNETLoader", "inputs": { ... } },
    "2": { "class_type": "CLIPLoader", "inputs": { ... } },
    ...
  }
}
```

Node links use the format `["source_node_id", output_slot_index]` in the `inputs` dict.

---

## Resource Requirements

| Metric | Value |
|---|---|
| VRAM during generation | ~36 GB |
| GPU utilization | ~96% |
| Generation time (864x480, 124 frames) | ~5 minutes on GB10 |
| Output file size | ~400 KB for 5 seconds |
| Disk for models | ~40 GB total |

---

## Known Issues

### Subgraph UUID Bug
The default workflow (`first-h3.json`) wraps the H3 pipeline in a subgraph node with UUID `4c314f31-ecda-4b08-ae98-faaba1bf613f`. This subgraph type is NOT registered as a standalone node in ComfyUI's API, causing `missing_node_type` errors when submitted via `/prompt`.

**Fix**: Use the flat workflow template (`workflows/h3-flat-template.json`) which inlines all 14 nodes without subgraph wrapping.

### Duration Snapping
H3 uses a `17k+5` frame grid. Valid `length` values: 5, 22, 39, 56, 73, 90, 107, 124, 141, ... The formula: `length = max(5, round(seconds * 24)) + (5 - (max(5, round(seconds * 24)) % 17)) % 17`

For common durations:
- 5 seconds → 124 frames
- 10 seconds → 243 frames
- 15 seconds → 362 frames (maximum tested)
