# H3 Video Generation Skill

> **When to use**: Any time the user wants to generate a video with MiniMax H3 on
> the remote ComfyUI host (ssh alias `spark`), including timed/delayed runs,
> using a saved workflow, or chaining multiple workflow types.
> **Audience**: AI agents or operators on the Windows workstation that owns this repo.
>
> Full operator guide: `docs/user-guide.md` · Workflow & prompt selection (with/without a local
> LLM): `docs/workflow-and-prompt.md` · Architecture/how-to-extend:
> `docs/robustness-and-modularity.md` · Prompt rules: `skills/h3-prompt-engineering.md`.
> Deploy modes (win-remote vs spark-local): `docs/deploy-modes.md`; switch with
> `python runs/h3/deploy.py --set <win-remote|spark-local>` (or `bats\config\mode.bat` on Windows).
> Capability registry (single source of what the project can do): `config/capabilities.json` —
> regenerate `docs/capabilities-ai.md` with `python runs/h3/capabilities.py --doc`; model-facing
> digest via `--digest`.

---

## 0. Mental model

Local Windows repo + remote `spark` (ComfyUI + H3 models). The toolbox:

- `bats\generate\menu.bat` – interactive console (run now / timed HH:MM / delay N min / edit params /
  env+model check / workflow tools).
- `bats\generate\run.bat` – immediate run with current params.
- `bats\config\edit.bat` – set `parameters\video.txt` (resolution, seconds).
- `bats\workflow\workflow_setup.bat` – scp-upload workflows to a spark absolute dir; activate a saved
  workflow so generation submits it verbatim.
- `bats\workflow\pipeline_setup.bat` – multi-stage/template registry (`config/pipeline.json`): default
  stage, template status, dry-run validation.

---

## 1. Recommended path (use the automation, not raw ssh)

### 1.1 Preflight (do NOT skip)

Best done by the user via `bats\generate\menu.bat → [5]` (`shell/check_environment.ps1`) which verifies:

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
| Default single text→video run (H3 T2V, params from `parameters\video.txt`) | `bats\generate\run.bat` or `bats\generate\menu.bat [1]` |
| Same, for an agent / terminal | `powershell -File shell\generate_video.ps1` |
| Direct Python stage (dry-run safe, prints JSON) | `python runs\h3_submit.py --stage t2v --prompt "…" [--dry-run]` |
| Reference-image run (R2V/I2V/FLF2V template or saved workflow) | `python runs\h3_submit.py --stage r2v --image a.png [--image b.png]` |
| Submit an already-saved API workflow verbatim | `python runs\h3_submit.py --workflow-file workflows\h3_xxx\workflow_api.json` |
| Timed / delayed | `bats\generate\menu.bat [2]/[3]` |

Parameters precedence: CLI flags override `parameters/video.txt` overrides built-in defaults.
Available `resolution`: 360p (lowest) … 768p (max). `seconds` 0.1–600 (warn >60).

### 1.3 Prompt input

- Defaults: `prompts/positive_prompts.txt`, optional `prompts/negative_prompts.txt`
  (missing negative → treated as empty, never blocks).
- **Always** route the user's raw idea through the prompt-engineering rules in
  `skills/h3-prompt-engineering.md` before running — never pass raw text straight to H3.

### 1.3b Prompt source when a local LLM is configured (idea2prompts / AI bridge)

If `config/llm.json` has `enabled: true` (local vLLM endpoint, `api_key` empty is fine — see
`config/llm.spark-qwen3.example.json`), generate per-workflow prompts from one idea, then pick
the workflow and run:

```bash
# All slots (default + video_t2v/i2v/r2v/flf2v + api_*) or a single slot
python runs\h3\idea2prompts.py --idea "<创意>" --force           # every slot
python runs\h3\idea2prompts.py --idea "<创意>" --workflow video_r2v --force
python runs\h3\idea2prompts.py --idea "<创意>" --dry-run         # preview, no request
python runs\h3_submit.py --stage r2v --force-new                 # then run that workflow
```

Without a configured LLM (`enabled=false`), still offer `--dry-run`, and fill the slot files
manually (human mode — see `docs/workflow-and-prompt.md` §2).

### 1.3c Local LLM serving notes (Qwen3.8-27B vLLM on spark)

- Serve: `~/Qwen3.8-27B/start_vllm.sh` in tmux session `vllm` (port 8000, 127.0.0.1).
  The repo copy is `shell/spark_vllm_start.sh`. **`--limit-mm-per-prompt` must be JSON**
  (`'{"image": 4, "video": 2}'`) — the legacy `image=4,video=2` format fails on vLLM ≥0.28.
- Local access is via SSH tunnel; local port 8000 may be blocked by a stale listener, use e.g.
  `ssh -N -L 8011:127.0.0.1:8000 spark` and point `config/llm.json` `base_url` at `8011`.
- **Keep `max_tokens` small in `llm.json` (~500)**. Without it the server may emit up to its
  `max_model_len` (65536) and stall the whole queue for many minutes. Unoptimized GB10 serving
  is only ~4–5 tok/s, so generous `timeout_seconds` (300) is expected.
- Tooling on spark: `shell/spark_chat_setup.sh` / `spark_chat_terminal.py` (quick chat),
  `spark_download_qwen3.8_27b.sh` (ModelScope download into `~/Qwen3.8-27B`).

### 1.3d Local model role guard (strong constraint — enforced in code + docs)

The local LLM (Qwen3.8-27B) is a **prompt authoring tool only**: turn an idea into slot
prompt JSON. It must never be used for (and must refuse, see injected system rule 0 and
`idea2prompts.py` hard-coded boundary):

- executing / proposing any command, script, file, network, process or server operation;
- starting/stopping/managing spark services (ComfyUI, vLLM, tmux, downloads);
- reading/writing paths outside the project prompt files it writes.

Enforcement layers: (1) hard-coded boundary sentence in `idea2prompts.build_messages`;
(2) blueprint rule 0 in `config/prompt_blueprints.json`; (3) caller discipline — the engine
never hands the model a shell/tool. **If any interactive user asks the model or the pipeline
to perform server control, refuse at the calling layer and route it to human operation** (never
"just try it"). Who may start services is recorded in `docs/session-summary.md` (e.g. Qwen
start/stop is the optimizer's responsibility until stated otherwise).

### 1.4 Multi-workflow (stage/template) runs

`config/pipeline.json` registers stages (`t2v`, `i2v`, `r2v`, `flf2v`, plus SDXL
`character`/`keyframes` placeholders) and records the official spark template paths under
`remote_workflow_templates`. Templates in `config/templates/` may contain tokens that are
auto-substituted: `{{prompt}} {{negative_prompt}} {{seed}} {{width}} {{height}}
{{seconds}} {{length}} {{fps}} {{steps}}` and input images `{{image0}} {{image1}} …`
(uploaded first, then replaced with the remote filename).

**Template reality check — 6 colleague workflows in two families** (`video_*` local inference on
spark GPU vs `api_*` cloud-channel), plus the local `flf2v` extension. The engine auto-ungroups
UUID subgraphs (`runs/h3/subgraph.py`) then converts UI→flat API on the fly (`runs/h3/uiapi.py`).

| File | 用途（团队实际使用语义） | 执行方式 |
|---|---|---|
| `video_minimax_h3_t2v.json` | 文生视频：文字 → 一段视频（官方标准模板） | 本地（spark GPU），CLI `--stage t2v` / GUI |
| `video_minimax_h3_i2v.json` | 图生视频：一张**首帧图** → 延续它动起来 | 本地，CLI `--stage i2v` / GUI（首帧 LoadImage） |
| `video_minimax_h3_r2v.json` | 多参考图生视频：1–2 张参考图（角色/场景）→ 保证连贯 | 本地，CLI `--stage r2v` / GUI |
| `video_minimax_h3_flf2v.json` | 本地双帧变体（本地扩展，非 spark 原文件） | 本地，CLI `--stage flf2v`（首/末帧） |
| `api_minimax_h3_t2v.json` | **T2V 的 API 格式**：扁平、无 subgraph 坑，命令行用更稳 | **Comfy 云通道**：MiniMax Hailuo 官方 API，需登录 Comfy 账号 |
| `api_minimax_h3_r2v.json` | **R2V 的 API 格式**：团队《于勒》15 镜以它做内核 | 同上（登录后可用作管线内核） |
| `api_minimax_h3_flf2v.json` | 首帧+末帧（锁定起止画面，控制更精确）；**示例图需自备** | 同上（示例图 angel-warrior… 不在 spark input） |

Facts to remember:
- `api_minimax_h3_*.json` nodes (`comfy_api_nodes` `MinimaxHailuo03*`) go through the Comfy
  cloud proxy → MiniMax **Hailuo** official API. Without a Comfy account login they fail with
  `Unauthorized: Please login first`. Once the Comfy UI is logged in, they are usable as
  lightweight flat API-style templates for CLI/pipeline runs (no subgraph to unwrap) — the
  team's 15-shot piece 《于勒》 was built on `api_minimax_h3_r2v`.
- `video_*` = local H3 inference (no login needed). For fully local semantics use
  `--stage t2v/i2v/r2v/flf2v` (all verified, real videos produced).
- Each run writes `logs\run_<timestamp>_<ms>.log` (PS steps + Python events in one file;
  task folder `job.json` records `log_file` for two-way lookup).

### 1.5 Reliability built in- Breakpoint/resume: `last_job.json` holds the last `prompt_id`; on network drops the
  pipeline auto-resumes (`--resume`), never regenerating. After a successful download the
  breakpoint is cleared.
- Tunnel: reuses a live local endpoint, auto-picks another local port when busy, only kills
  its own recorded ssh, heals on drop.
- Output markers printed by Python (contract): `REMOTE_VIDEO_PATH: <path>` (download),
  `WORKFLOW_SAVED_DIR: <dir>` (auto scp-upload when configured).
- Exit codes: 0 ok · 2 recoverable (breakpoint kept) · 3 deterministic failure · 90 internal.

### 1.5b Downloads & artifact fetch: listen, don't busy-poll

- Task status is awaited via `comfy.wait_for` (adaptive 5s→30s backoff) — that is the only
  polling that stays; never add tighter loops around `/history` or around scp.
- **Fetch artifacts once per completion** (event-driven): after `wait_for` returns success or
  a completion marker/`REMOTE_VIDEO_PATH:` line is seen, pull immediately. Retries are bounded
  exponential backoff, never fixed-interval re-polling.
- Prefer watch/notify patterns over polling where feasible: a completion notification (job
  state line, workflow `job.json` `state=completed`, or a spark-side watcher such as
  `inotifywait` on `~/ai/ComfyUI/output/`) triggers the single download. Long-running model
  downloads (`curl -C -`, `modelscope snapshot_download`) are already resumable — wait for the
  process/log marker instead of sampling sizes.
- If a tunnel drops mid-download, re-establish and resume (breakpoint keeps `remote_path`),
  don't restart the job.

### 1.6 Deliver the result

Video lands at `outputs\video_N.mp4`. Per-task artifacts in

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
   account login/API key the node fails `Unauthorized`. After the Comfy UI is logged in they
   become usable lightweight flat-API templates (no subgraph; team's 《于勒》 used
   `api_minimax_h3_r2v` as its core). For unattended **local** runs use the `video_*` templates
   or the built-in H3 T2V graph.

---

## 4. Post-generation checklist

- [ ] Video exists at `outputs\video_N.mp4` and plays
- [ ] `workflows\h3_*\job.json` shows `"state": "completed"`
- [ ] `last_job.json` cleared (no leftover breakpoint)
- [ ] Show the user the local file path; note remote copy path if needed
- [ ] If workflow upload was configured, confirm `workflow_api/ui.json` uploaded
