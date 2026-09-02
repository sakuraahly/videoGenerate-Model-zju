# H3 Video Generation Skill

> **When to use**: Any time the user wants to generate a video with MiniMax H3 on
> the remote ComfyUI host (ssh alias `spark`), including timed/delayed runs,
> using a saved workflow, or chaining multiple workflow types.
> **Audience**: AI agents or operators on the Windows workstation that owns this repo.
>
> Full operator guide: `docs/user-guide.md` · Architecture/how-to-extend:
> `docs/robustness-and-modularity.md` · Prompt rules: `skills/h3-prompt-engineering.md`.

---

## 0. Mental model

Local Windows repo + remote `spark` (ComfyUI + H3 models). The toolbox:

- `menu.bat` – interactive console (run now / timed HH:MM / delay N min / edit params /
  env+model check / workflow tools).
- `run.bat` – immediate run with current params.
- `edit.bat` – set `parameters\video.txt` (resolution, seconds).
- `workflow_setup.bat` – scp-upload workflows to a spark absolute dir; activate a saved
  workflow so generation submits it verbatim.
- `pipeline_setup.bat` – multi-stage/template registry (`config/pipeline.json`): default
  stage, template status, dry-run validation.

---

## 1. Recommended path (use the automation, not raw ssh)

### 1.1 Preflight (do NOT skip)

Best done by the user via `menu.bat → [5]` (`shell/check_environment.ps1`) which verifies:

- local tools/files (python, ssh, scp, folders, prompts)
- `ssh spark` reachability + remote ComfyUI process
- the 4 base model files on spark (manifest: `config/minimax_h3_models.json`) and can
  auto-download any missing via `curl -fL -C -` (only the 4 files, never the whole repo).

For an agent, the programmatic equivalent is `Assert-PreflightBasics` +
`Test-RemoteReachable` in `shell/lib/preflight.ps1`, or simply run the pipeline and read
its early errors (preflight runs first and fails fast).

### 1.2 Choose how to generate

| Goal | Command / action |
|---|---|
| Default single text→video run (H3 T2V, params from `parameters\video.txt`) | `run.bat` or `menu.bat [1]` |
| Same, for an agent / terminal | `powershell -File shell\generate_video.ps1` |
| Direct Python stage (dry-run safe, prints JSON) | `python runs\h3_submit.py --stage t2v --prompt "…" [--dry-run]` |
| Reference-image run (R2V/I2V/FLF2V template or saved workflow) | `python runs\h3_submit.py --stage r2v --image a.png [--image b.png]` |
| Submit an already-saved API workflow verbatim | `python runs\h3_submit.py --workflow-file workflows\h3_xxx\workflow_api.json` |
| Timed / delayed | `menu.bat [2]/[3]` |

Parameters precedence: CLI flags override `parameters/video.txt` overrides built-in defaults.
Available `resolution`: 360p (lowest) … 768p (max). `seconds` 0.1–600 (warn >60).

### 1.3 Prompt input

- Defaults: `prompts/positive_prompts.txt`, optional `prompts/negative_prompts.txt`
  (missing negative → treated as empty, never blocks).
- **Always** route the user's raw idea through the prompt-engineering rules in
  `skills/h3-prompt-engineering.md` before running — never pass raw text straight to H3.

### 1.4 Multi-workflow (stage/template) runs

`config/pipeline.json` registers stages (`t2v`, `i2v`, `r2v`, `flf2v`, plus SDXL
`character`/`keyframes` placeholders) and records the official spark template paths under
`remote_workflow_templates`. Templates in `config/templates/` may contain tokens that are
auto-substituted: `{{prompt}} {{negative_prompt}} {{seed}} {{width}} {{height}}
{{seconds}} {{length}} {{fps}} {{steps}}` and input images `{{image0}} {{image1}} …`
(uploaded first, then replaced with the remote filename).

**Template reality check**: official `api_minimax_h3_*.json` fetched from
`spark:~/ai/ComfyUI/user/default/workflows/` are **UI format** (nodes/links), and their
`MinimaxHailuo03*` nodes call the **Comfy API cloud** — they need a Comfy account login /
API key and fail with `Unauthorized: Please login first` otherwise. The engine now converts
UI templates to flat API on the fly (`runs/h3/uiapi.py`, uses live `/object_info`;
dynamic-combo children are emitted as `model.prompt`/`model.resolution`/… keys, string node
refs) — conversion passes `/prompt` validation. If Comfy API is not authenticated, prefer the
built-in local H3 graph (default `t2v` stage, local inference on spark, no cloud dependency).
The colleague `video_minimax_h3_r2v.json` is an open **local** graph (converts cleanly to ~20 API
nodes incl. `MiniMaxH3ReferenceToVideo`) — usable once reference images exist on spark `input/`.
`video_minimax_h3_t2v/i2v.json` are local graphs wrapped as UUID subgraphs (unwrapping pending).
Each run also writes `logs\run_<timestamp>.log` (PS steps + Python events in one file).

### 1.5 Reliability built in

- Breakpoint/resume: `last_job.json` holds the last `prompt_id`; on network drops the
  pipeline auto-resumes (`--resume`), never regenerating. After a successful download the
  breakpoint is cleared.
- Tunnel: reuses a live local endpoint, auto-picks another local port when busy, only kills
  its own recorded ssh, heals on drop.
- Output markers printed by Python (contract): `REMOTE_VIDEO_PATH: <path>` (download),
  `WORKFLOW_SAVED_DIR: <dir>` (auto scp-upload when configured).
- Exit codes: 0 ok · 2 recoverable (breakpoint kept) · 3 deterministic failure · 90 internal.

### 1.6 Deliver the result

Video lands at `outputs\video_N.mp4`. Per-task artifacts in
`workflows\h3_<ts>_<ms>\`: `workflow_api.json`, `workflow_ui.json` (full LiteGraph links,
loadable in ComfyUI), and `job.json` (automatic audit: stage, params, prompt_id, remote
path, status) — the modern replacement for manual run logs.

---

## 2. Resolution / duration reference

| Preset | W×H | | Seconds | frames (length, 24fps, 17k+5 grid) |
|---|---|---|---|---|
| 360p (lowest) | 608×352 | | 5 | 124 |
| 480p | 864×480 | | 10 | 243 |
| 540p | 960×544 | | 15 | 362 |
| 720p | 1280×736 | | recommended | 5–15s |
| 768p (max) | 1344×768 | | | |

`length = max(5, round(sec*fps)) + (5 - (max(5, round(sec*fps)) % 17)) % 17`
(custom width/height must be multiples of 8; presets already are).

---

## 3. Hard constraints

1. Never submit raw **UI-format** workflow JSON to `/prompt` (incl. official `api_*`
   templates in `user/default/workflows`) — flatten or use the automation that validates.
2. Never skip prompt engineering (`skills/h3-prompt-engineering.md`).
3. One generation at a time (a single-instance lock already prevents double-click races).
4. Max frame size 1344×768; length must obey the 17k+5 grid.
5. `CLIPLoader type="minimax"`, sampler `res_multistep` — fixed by the built-in builder.
6. Don't delete `last_job.json` while a task is genuinely running; clearing it forces a new
   task (or pass `--force-new`).
7. If you need to reset to text-driven default behavior, set `default_stage: t2v` in
   `config/pipeline.json` (or just never pass `--stage`).
8. Official `MinimaxHailuo03*` UI templates call the **Comfy API cloud**: without a Comfy
   account login/API key the node fails `Unauthorized`. For unattended runs use the built-in
   H3 T2V graph, or an official template only after the Comfy UI is logged in.

---

## 4. Post-generation checklist

- [ ] Video exists at `outputs\video_N.mp4` and plays
- [ ] `workflows\h3_*\job.json` shows `"state": "completed"`
- [ ] `last_job.json` cleared (no leftover breakpoint)
- [ ] Show the user the local file path; note remote copy path if needed
- [ ] If workflow upload was configured, confirm `workflow_api/ui.json` uploaded
