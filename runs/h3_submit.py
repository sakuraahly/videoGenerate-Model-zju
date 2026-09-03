#!/usr/bin/env python3
"""
MiniMax H3 / 多工作流生成 — CLI 入口（模块化、断点可恢复、支持多阶段模板）

职责：参数解析 -> 状态编排 -> 提交/轮询/输出标记；具体逻辑分布在
runs/h3/{params,workflow,templates,stage,comfy,jobstate}.py。

运行方式（兼容旧参数）：
  python3 h3_submit.py --prompt "..." | --prompt-file FILE        # 旧方式：默认阶段 T2V
  python3 h3_submit.py --stage r2v --image ref1.png --image ref2.png
  python3 h3_submit.py --template path/to/api_wf.json --prompt "..."   # 用任意 API 模板
  python3 h3_submit.py --workflow-file saved_api.json              # 原样提交已存工作流
  python3 h3_submit.py --resume <prompt_id>                        # 断点恢复
  python3 h3_submit.py --dry-run --stage t2v --prompt "hello"

阶段（stage）来自 config/pipeline.json（默认阶段默认 t2v=旧行为）。模板文件支持
占位符 {{prompt}} {{negative_prompt}} {{seed}} {{width}} {{height}}
{{seconds}} {{length}} {{fps}} {{steps}} 与 {{image0}} {{image1}} ...

退出码契约（供外层 PowerShell 编排）：
  0  = 成功并已定位远程输出路径（打印 REMOTE_VIDEO_PATH: <path>）
  2  = 可恢复失败（网络中断/轮询超时），断点保留，重跑自动续传
  3  = 确定性失败（参数错误/任务被拒/任务执行失败），不重试
  90 = 未预期的内部错误（可视为确定性失败）
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from h3 import comfy, jobstate, params as h3params, workflow as h3workflow
from h3 import prompts as h3prompts
from h3 import stage as h3stage

EXIT_OK = 0
EXIT_RECOVERABLE = 2
EXIT_DETERMINISTIC = 3
EXIT_INTERNAL = 90

_LOG_ENV = "H3_LOG_FILE"


def _err(msg: str) -> None:
    print(f"[错误] {msg}", file=sys.stderr, flush=True)


def _ensure_run_log(project_dir: Path):
    """确保本次运行有日志文件可追加，返回 (path, created)。

    - 外层 PowerShell 已注入 H3_LOG_FILE（generate_video.ps1 同文件日志）→ 沿用；
    - 否则 CLI 直跑时自动在 <项目根>/logs/ 建 run_<时间戳>_<毫秒>.log（不再丢日志）。
    毫秒后缀保证同秒多次运行不撞名，且与任务目录 h3_<时间戳>_<毫秒> 秒段对齐。
    """
    existing = os.environ.get(_LOG_ENV, "").strip()
    if existing:
        return existing, False
    log_dir = Path(project_dir) / "logs"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        now = datetime.now()
        name = f"run_{now.strftime('%Y%m%d_%H%M%S')}_{now.microsecond // 1000:03d}.log"
        path = log_dir / name
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] "
                    f"py: === MiniMax H3 run start ===\n")
        os.environ[_LOG_ENV] = str(path)
        return str(path), True
    except OSError:
        return "", False


def _log_event(msg: str) -> None:
    """追加运行日志（路径：PS 注入或 Python 自举，见 _ensure_run_log）。"""
    path = os.environ.get(_LOG_ENV, "")
    if not path:
        return
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] py: {msg}\n")
    except OSError:
        pass


def _adopt_task_log(project_dir: Path, task_folder: Optional[Path]) -> None:
    """续传（--resume）时沿用原任务日志：job.json 记有 log_file 则切换过去，
    并把本次会话自举新日志的起始行并入原日志，保证“一个任务一份完整日志”。"""
    if task_folder is None:
        return
    try:
        job = jobstate.read_json(jobstate.task_job_path(project_dir, task_folder))
    except OSError:
        return
    lf = str((job or {}).get("log_file") or "")
    if not lf:
        return
    orig = Path(project_dir) / "logs" / Path(lf).name
    if not orig.exists():
        return
    cur = os.environ.get(_LOG_ENV, "")
    if cur and Path(cur) != orig:
        try:
            with open(cur, encoding="utf-8") as f:
                head = f.read()
            if head:
                with open(orig, "a", encoding="utf-8") as f:
                    f.write(head)
            os.environ.pop(_LOG_ENV, None)
            Path(cur).unlink(missing_ok=True)
        except OSError:
            pass
    os.environ[_LOG_ENV] = str(orig)


class _CliParser(argparse.ArgumentParser):
    """命令行用法错误也按“确定性失败(3)”退出，避免被外层误判为可恢复。"""

    def error(self, message):
        print(f"参数错误: {message}", file=sys.stderr)
        sys.exit(EXIT_DETERMINISTIC)


def build_arg_parser() -> argparse.ArgumentParser:
    p = _CliParser(
        description="Submit video/image generation to ComfyUI（多阶段/多模板，支持断点恢复）"
    )
    p.add_argument("--prompt", type=str, default=None, help="Scene description")
    p.add_argument("--prompt-file", type=str, default=None, help="Read prompt from file")
    p.add_argument("--negative-prompt", type=str, default=None, help="Negative prompt text")
    p.add_argument("--negative-prompt-file", type=str, default=None,
                   help="Read negative prompt from file")
    # 多工作流/阶段参数
    p.add_argument("--stage", type=str, default=None,
                   help="使用 config/pipeline.json 中注册的生成阶段（t2v/i2v/r2v/flf2v/...）")
    p.add_argument("--template", type=str, default=None,
                   help="直接指定一个 API 模板文件（含 {{token}} 占位符，会做替换）")
    p.add_argument("--image", type=str, action="append", default=None,
                   help="输入图（i2v/r2v/flf2v 等），可多次指定；未指定时用阶段 default_images")
    p.add_argument("--workflow-file", type=str, default=None,
                   help="直接使用已保存的 API 工作流 JSON 原样提交（跳过提示词/占位符处理）")
    # 覆盖项：未提供(None)时以 parameters/video.txt / 默认值为准
    p.add_argument("--resolution", type=str, default=None,
                   choices=sorted(h3workflow.RESOLUTION_PRESETS),
                   help="Use a resolution preset (overrides file value)")
    p.add_argument("--width", type=int, default=None)
    p.add_argument("--height", type=int, default=None)
    p.add_argument("--seconds", type=float, default=None)
    p.add_argument("--seed", type=str, default=None,
                   help="Random seed (int, or 'auto' for random per run)")
    p.add_argument("--steps", type=int, default=None)
    p.add_argument("--fps", type=float, default=None)
    p.add_argument("--timeout", type=int, default=None, help="Max wait seconds")
    p.add_argument("--comfyui-url", type=str, default=None,
                   help="Override ComfyUI base URL (default: env COMFYUI_URL or 127.0.0.1:8188)")
    p.add_argument("--output", type=str, default=".",
                   help="Local directory shown in download hint")
    p.add_argument("--resume", type=str, default="",
                   help="Resume polling an existing prompt_id (skip submission)")
    p.add_argument("--force-new", action="store_true",
                   help="忽略遗留断点，强制开启新任务")
    p.add_argument("--no-save-workflow", action="store_true",
                   help="不保存工作流文件（测试用）")
    p.add_argument("--dry-run", action="store_true",
                   help="Prepare/print workflow without submitting or uploading")
    return p


def _has_new_task_args(args: argparse.Namespace) -> bool:
    return bool(args.prompt or args.prompt_file or args.workflow_file
                or args.stage or args.template)


def _load_workflow_file(path: Path) -> dict:
    """读取并校验 API 格式工作流 JSON（原样提交用）；无效抛 ParamError。"""
    path = Path(path)
    if not path.exists():
        raise h3params.ParamError(f"工作流文件不存在: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as e:
        raise h3params.ParamError(f"工作流文件无法解析（{e}）: {path}")
    if not isinstance(data, dict) or not data:
        raise h3params.ParamError(f"工作流文件内容不是有效的 API 工作流: {path}")
    bad = [
        k for k, node in data.items()
        if not isinstance(node, dict) or not isinstance(node.get("class_type"), str)
    ]
    if bad:
        raise h3params.ParamError(
            f"工作流文件缺少 class_type 字段（问题节点前几个: {bad[:5]}）: {path}"
        )
    return data


def _task_folder_for_prompt(project_dir: Path, prompt_id: str) -> Optional[Path]:
    """在 workflows/ 里按 job.json 反查包含该 prompt_id 的任务文件夹。"""
    root = Path(project_dir) / "workflows"
    if not root.is_dir():
        return None
    for child in sorted(root.iterdir(), reverse=True):
        if not child.is_dir():
            continue
        job = jobstate.read_json(child / "job.json")
        if job and str(job.get("prompt_id") or "") == prompt_id:
            return child
    return None


def _read_text_source(text: Optional[str], path: Optional[Path],
                      stage_default: Optional[Path], what: str) -> str:
    """文本取值优先级：--xx 文本 > --xx-file > 阶段默认文件 > ''。"""
    if text is not None:
        return text.strip()
    src = path if path is not None else stage_default
    if src is None:
        return ""
    if not src.exists():
        raise h3params.ParamError(f"{what}文件不存在: {src}")
    val = h3params.read_prompt_file(src)
    return val


def _resolve_gp_text(args: argparse.Namespace, project_dir: Path,
                     prompt: str, negative_prompt: str) -> h3params.GenParams:
    """由文本+参数文件+CLI 覆盖归一化为 GenParams。"""
    raw = h3params.parse_keyvalue_file(
        Path(project_dir) / h3params.LAYOUT["parameters_dir"] / h3params.PARAMS_FILE_NAME
    )
    overrides = {
        "resolution": args.resolution,
        "width": args.width,
        "height": args.height,
        "seconds": args.seconds,
        "seed": args.seed,
        "steps": args.steps,
        "fps": args.fps,
        "timeout": args.timeout,
    }
    return h3params.resolve_params(raw, prompt=prompt, negative_prompt=negative_prompt,
                                   cli_overrides=overrides)


def _legacy_prompt_mode(args: argparse.Namespace, project_dir: Path) -> tuple:
    """旧方式：仅 CLI 提示词 + 动态构建 H3 T2V。返回 (workflow, gp, stage_id, used_builtin)。"""
    prompt = ""
    if args.prompt:
        prompt = args.prompt
    elif args.prompt_file:
        path = Path(args.prompt_file)
        if not path.exists():
            raise h3params.ParamError(f"正向提示词文件不存在: {path}")
        prompt = h3params.read_prompt_file(path)
        if not prompt:
            raise h3params.ParamError(f"正向提示词文件为空: {path}")
    else:
        raise h3params.ParamError("需要 --prompt 或 --prompt-file")

    negative_prompt = args.negative_prompt or ""
    if args.negative_prompt_file:
        path = Path(args.negative_prompt_file)
        if path.exists():
            negative_prompt = h3params.read_prompt_file(path)
        else:
            print(f"[提示] 负向提示词文件不存在（{path}），按空负向提示词继续。",
                  file=sys.stderr, flush=True)

    gp = _resolve_gp_text(args, project_dir, prompt, negative_prompt)
    wf = h3workflow.build_workflow(
        gp.prompt, gp.width, gp.height, gp.length, gp.seed,
        negative_prompt=gp.negative_prompt, steps=gp.steps, fps=gp.fps,
    )
    return wf, gp, "t2v", True


def _stage_mode(args: argparse.Namespace, project_dir: Path,
                client: comfy.ComfyClient, dry_run: bool) -> tuple:
    """
    注册表阶段 / 自定义模板模式。返回 (workflow, gp, stage_id)。

    client 用于在真实提交前上传输入图（dry_run 时不上传，占位用本地文件名）。
    """
    pcfg = h3stage.load_pipeline_config(project_dir)
    default_id = h3stage.default_stage_id(pcfg)

    # 选择阶段：--stage 显式 > 自定义 --template 沿用默认阶段输入配置 > pipeline 默认
    stage_id = args.stage or default_id
    stage = h3stage.resolve_stage(pcfg, stage_id)
    stage = dict(stage)
    stage["_id"] = stage_id

    # 提示词：CLI(--prompt/--prompt-file) > 该工作流槽位文件 > 阶段默认文件 > 默认文件
    tname_for_slot = Path(args.template).name if args.template else str(stage.get("template") or "")
    slot_tpl = Path(tname_for_slot) if tname_for_slot else None
    pp, np = h3prompts.pick_prompt_paths(project_dir, stage, slot_tpl, None, None)

    explicit_pos_file = Path(args.prompt_file).resolve() if args.prompt_file else None
    if explicit_pos_file and not explicit_pos_file.exists():
        raise h3params.ParamError(f"正向提示词文件不存在: {explicit_pos_file}")
    if args.prompt is not None:
        prompt = args.prompt
    elif explicit_pos_file:
        prompt = h3prompts.read_text_path(explicit_pos_file, "正向提示词")
        if not prompt:
            raise h3params.ParamError(f"正向提示词文件为空: {explicit_pos_file}")
    else:
        prompt = h3prompts.read_text_path(pp, "正向提示词")

    explicit_neg_file = Path(args.negative_prompt_file).resolve() if args.negative_prompt_file else None
    if args.negative_prompt is not None:
        negative = args.negative_prompt
    elif explicit_neg_file:
        negative = h3prompts.read_text_path(explicit_neg_file, "负向提示词")
    else:
        negative = h3prompts.read_text_path(np, "负向提示词")

    images = h3stage.gather_images(project_dir, stage, args.image)
    gp = _resolve_gp_text(args, project_dir, prompt, negative)

    # 上传输入图 -> 占位符 {{imageN}}（dry_run 仅预览，用本地文件名）
    image_names: dict = {}
    for i, img in enumerate(images):
        if dry_run:
            image_names[f"image{i}"] = img.name
        else:
            image_names[f"image{i}"] = client.upload_image(img)

    tpath = Path(args.template).resolve() if args.template else \
        h3stage.template_path(pcfg, project_dir, stage)
    used_builtin = False
    token_map = h3stage.text_token_map(gp)
    template_usable = bool(tpath.name) and tpath.exists()
    if args.template:
        # 用户显式指定模板：必须可用（API 或可在线转换的 UI），失败即报错
        wf = h3stage.build_template_workflow(
            stage, pcfg, project_dir, token_map, image_names,
            template_file=tpath, client=client,
        )
    elif template_usable:
        # 阶段默认模板文件存在：API 直接用；UI 格式尝试在线转换；
        # 转换失败/不可用且本阶段有内置生成器时提示并回退内置
        try:
            wf = h3stage.build_template_workflow(
                stage, pcfg, project_dir, token_map, image_names, client=client)
        except h3params.ParamError as e:
            if not stage.get("builtin"):
                raise
            print(f"[提示] 阶段 '{stage_id}' 的模板不可用或转换失败（{e}），"
                  f"回退到内置生成器 {stage.get('builtin')}。",
                  file=sys.stderr, flush=True)
            used_builtin = True
            wf = h3stage.build_builtin_workflow(stage, gp, images)
    else:
        # 模板缺失 -> 尝试内置生成器；无内置时由 build_builtin_workflow 报错
        used_builtin = True
        wf = h3stage.build_builtin_workflow(stage, gp, images)

    # 关键：把本地提示词自动注入工作流（覆盖模板内嵌 prompt；内置生成器幂等）
    changed = h3prompts.inject_local_prompts(wf, prompt, negative)
    if changed:
        print(f"[提示] 已用本地提示词覆盖工作流内嵌字段（{changed} 处）。", flush=True)
    return wf, gp, stage_id, used_builtin


def _wait_timeout(args: argparse.Namespace, task_folder: Optional[Path],
                  gp: Optional[h3params.GenParams]) -> int:
    """确定轮询超时：CLI > 本次参数 > 任务审计记录 > 默认值。"""
    if args.timeout:
        return args.timeout
    if gp is not None:
        return gp.timeout
    if task_folder is not None:
        job = jobstate.read_json(task_folder / "job.json")
        p = (job or {}).get("params") or {}
        if p.get("timeout"):
            return int(p["timeout"])
    return int(h3params.DEFAULTS["timeout"])


def _collect_outputs(entry: dict) -> List[dict]:
    """从 history 的全部输出节点收集文件（兼容模板输出节点 id 不固定）。"""
    outputs = entry.get("outputs") or {}
    files: List[dict] = []
    for node_outputs in outputs.values():
        for f in comfy.extract_output_files(node_outputs):
            if f not in files:
                files.append(f)
    if not files:
        # 个别版本主输出在固定节点 14（SaveVideo）
        files = comfy.extract_output_files(outputs.get("14"))
    return files


def main(argv: Optional[list] = None) -> int:
    args = build_arg_parser().parse_args(argv)
    project_dir = h3params.project_root_from_file(Path(__file__))
    env = h3params.load_environment(project_dir)

    # 运行日志：PS 注入则沿用；CLI 直跑自动在 logs\ 建 run_<ts>.log
    run_log, log_created = _ensure_run_log(project_dir)
    if run_log:
        if log_created:
            print(f"[INFO] 运行日志: {run_log}", flush=True)
        _log_event(f"start argv={' '.join(argv) if argv is not None else ''}")

    base_url = args.comfyui_url or comfy.DEFAULT_COMFYUI_URL
    client = comfy.ComfyClient(base_url=base_url)
    root_state = jobstate.load_root_state(project_dir)

    # ------------------------------------------------------------ 任务路由
    resume_id = args.resume.strip() if args.resume else ""
    if not resume_id and not _has_new_task_args(args) and root_state.get("prompt_id"):
        resume_id = root_state["prompt_id"]  # 无参数 + 有断点 => 自动续传

    task_folder: Optional[Path] = None
    gp: Optional[h3params.GenParams] = None

    # 仅在“即将开新任务”时才拦截遗留断点；带 --resume 的续传不受影响
    if (not resume_id and _has_new_task_args(args)
            and root_state.get("prompt_id") and not args.force_new):
        _err("检测到上次任务尚未完成（断点存在）。若确要开新任务，请先删除 "
             f"{jobstate.root_state_path(project_dir)}，或加 --force-new 强制新开。")
        return EXIT_DETERMINISTIC

    stage_id = "t2v"
    wf: Optional[dict] = None

    if resume_id:
        print(f"恢复任务: prompt_id={resume_id}（跳过提交，直接轮询原任务）", flush=True)
        task_folder = _task_folder_for_prompt(project_dir, resume_id)
        _adopt_task_log(project_dir, task_folder)
        _log_event(f"resume prompt_id={resume_id}")
    else:
        # ---- 模式选择 ----
        if args.workflow_file and (args.prompt or args.prompt_file
                                   or args.stage or args.template or args.image
                                   or args.negative_prompt or args.negative_prompt_file):
            _err("--workflow-file 为“原样提交”，不能与 --stage/--template/--prompt*/--image 混用。")
            return EXIT_DETERMINISTIC

        mode = "workflow_file" if args.workflow_file else "stage"
        used_builtin = False
        try:
            if mode == "workflow_file":
                wf = _load_workflow_file(Path(args.workflow_file))
                print(f"使用已保存的工作流原样提交: {args.workflow_file}"
                      f"（{len(wf)} 个节点）", flush=True)
            else:
                pcfg = h3stage.load_pipeline_config(project_dir)
                default_id = h3stage.default_stage_id(pcfg)
                # 保持旧行为：默认阶段为内置 t2v 且用户未显式指定 stage/template 时
                # 走经典提示词路径（结果与历史版本完全一致）
                if (not args.stage and not args.template and not args.image
                        and default_id == "t2v"):
                    wf, gp, stage_id, used_builtin = _legacy_prompt_mode(args, project_dir)
                else:
                    wf, gp, stage_id, used_builtin = _stage_mode(
                        args, project_dir, client, dry_run=args.dry_run)
        except h3params.ParamError as e:
            _err(str(e))
            return EXIT_DETERMINISTIC

        if gp is not None:
            if mode == "workflow_file":
                label = "已存工作流原样提交"
            elif used_builtin:
                label = "内置生成器"
            else:
                label = "模板文件"
            print(f"阶段: {stage_id}   工作流来源: {label}")
            if gp.prompt:
                print(f"Prompt: {gp.prompt[:80]}{'...' if len(gp.prompt) > 80 else ''}")
            if gp.negative_prompt:
                print(f"Negative Prompt: {gp.negative_prompt[:80]}"
                      f"{'...' if len(gp.negative_prompt) > 80 else ''}")
            print(f"Resolution: {gp.width}x{gp.height} ({gp.resolution})")
            print(f"Duration: {gp.seconds}s -> {gp.length} frames @ {gp.fps}fps")
            print(f"Seed: {gp.seed}   Steps: {gp.steps}   Timeout: {gp.timeout}s", flush=True)
            _log_event(
                f"task mode={mode} stage={stage_id} source={label} "
                f"resolution={gp.width}x{gp.height}({gp.resolution}) "
                f"duration={gp.seconds}s->{gp.length}f@{gp.fps}fps "
                f"seed={gp.seed} steps={gp.steps} timeout={gp.timeout}s "
                f"prompt_len={len(gp.prompt or '')} neg_len={len(gp.negative_prompt or '')}")

        if args.dry_run:
            _log_event(f"dry_run mode={mode} stage={stage_id} "
                       f"nodes={len(wf) if isinstance(wf, dict) else 0} (预览，未提交)")
            print(json.dumps(wf, indent=2, ensure_ascii=False))
            return EXIT_OK

        # 任务文件夹 + 工作流落盘 + 审计记录（workflow-file 原样模式不重存）
        if mode != "workflow_file" and not args.no_save_workflow:
            workflows_root = Path(project_dir) / h3params.LAYOUT["workflows_dir"]
            task_folder = workflows_root / h3workflow.make_task_folder_name()
            task_folder.mkdir(parents=True, exist_ok=True)
            api_path = h3workflow.save_workflow_api(wf, task_folder / "workflow_api.json")
            ui_path = h3workflow.save_workflow_ui(wf, task_folder / "workflow_ui.json")
            jobstate.record_task_start(project_dir, task_folder, {
                "prompt_id": "",
                "stage": stage_id,
                "params": gp.workflow_dict() if gp else {},
                "log_file": os.path.basename(run_log) if run_log else "",
                "prompt_files": {
                    "positive": args.prompt_file or "",
                    "negative": args.negative_prompt_file or "",
                },
                "workflow_files": {
                    "api": api_path.name,
                    "ui": ui_path.name if ui_path else None,
                },
            })
            # 机器可读标记：外层 PowerShell 解析后把该任务的工作流 scp 上传到 spark
            print(f"WORKFLOW_SAVED_DIR: {task_folder}", flush=True)
            _log_event(f"workflow_saved dir={task_folder.name} nodes={len(wf)}")

        # 提交
        print("\nSubmitting...", flush=True)
        try:
            resume_id = client.submit(wf)
        except comfy.ComfyRejected as e:
            _err(f"提交被 ComfyUI 拒绝: {e}")
            _log_event(f"submit_rejected stage={stage_id} err={e}")
            if e.body:
                print(e.body[:2000], file=sys.stderr, flush=True)
            return EXIT_DETERMINISTIC
        except comfy.ComfyUnreachable as e:
            _err(f"提交失败，无法连接 ComfyUI（{e}）。请检查 SSH 隧道后重试。")
            _log_event(f"submit_unreachable stage={stage_id} err={e}")
            return EXIT_RECOVERABLE

        jobstate.save_root_state(project_dir, prompt_id=resume_id)
        if task_folder:
            jobstate.update_task_record(project_dir, task_folder, {"prompt_id": resume_id})
        print(f"prompt_id: {resume_id}\n", flush=True)
        _log_event(f"submitted stage={stage_id} prompt_id={resume_id}")

    # ------------------------------------------------------------ 轮询等待
    timeout = _wait_timeout(args, task_folder, gp)
    poll_start = time.monotonic()
    try:
        kind, entry = client.wait_for(resume_id, timeout=timeout)
    except comfy.ComfyUnreachable as e:
        el = int(time.monotonic() - poll_start)
        _err(f"与 ComfyUI 的连接中断: {e}")
        _log_event(f"interrupted prompt_id={resume_id} elapsed={el}s err={e}")
        print("断点仍保留，网络恢复后重新运行 run.bat / 本脚本将自动续传，不会重复生成。",
              file=sys.stderr, flush=True)
        if task_folder:
            jobstate.update_task_record(project_dir, task_folder, {"state": "interrupted"})
        return EXIT_RECOVERABLE

    if kind == "timeout":
        el = int(time.monotonic() - poll_start)
        _err("等待任务超时。任务可能仍在远程执行。")
        _log_event(f"timed_out prompt_id={resume_id} elapsed={el}s")
        print("断点仍保留，稍后重新运行即可继续等待。", file=sys.stderr, flush=True)
        if task_folder:
            jobstate.update_task_record(project_dir, task_folder, {"state": "timed_out"})
        return EXIT_RECOVERABLE

    assert entry is not None
    status = entry.get("status") or {}
    status_str = status.get("status_str", "")
    print(f"\nStatus: {status_str or 'unknown'}", flush=True)

    if kind == "error" or status_str == "error":
        el = int(time.monotonic() - poll_start)
        _err("任务在 ComfyUI 中执行失败（不可恢复），已清除断点。")
        _log_event(f"task_error prompt_id={resume_id} elapsed={el}s status={status_str}")
        jobstate.clear_root_state(project_dir)
        if task_folder:
            jobstate.update_task_record(project_dir, task_folder, {"state": "failed"})
        return EXIT_DETERMINISTIC

    # ------------------------------------------------------------ 输出定位
    files = _collect_outputs(entry)
    # 优先 mp4 视频，其次静态图（PNG/JPG 等）
    def _rank(f: dict) -> int:
        fmt = str(f.get("format", "")).lower()
        if fmt in ("mp4", ""):
            return 0
        return 1 if fmt in ("png", "jpg", "jpeg", "webp") else 2

    files.sort(key=_rank)
    if not files:
        _err("任务已完成，但未能从历史记录中定位输出文件。")
        print("断点仍保留，可稍后重新运行再次查询。", file=sys.stderr, flush=True)
        return EXIT_RECOVERABLE

    file_info = files[0]
    remote_base = str(env.get("remote_output_dir") or "~/ai/ComfyUI/output")
    remote_path = comfy.build_remote_path(remote_base, file_info)
    print(f"Output file: {file_info['filename']}", flush=True)

    # 更新断点（写入 remote_path，外层下次可直接下载、免重复轮询）
    jobstate.save_root_state(project_dir, prompt_id=resume_id, remote_path=remote_path)
    if task_folder:
        jobstate.update_task_record(
            project_dir, task_folder,
            {"state": "completed", "remote_path": remote_path,
             "output_file": file_info["filename"]},
        )

    # 机器可读标记：外层 PowerShell 依赖此行
    print(f"REMOTE_VIDEO_PATH: {remote_path}", flush=True)
    for extra in files[1:]:
        extra_path = comfy.build_remote_path(remote_base, extra)
        print(f"REMOTE_VIDEO_PATH: {extra_path}", flush=True)
    _log_event(f"completed prompt_id={resume_id} remote={remote_path} files={len(files)} "
               f"elapsed={int(time.monotonic() - poll_start)}s status={status_str}")
    host = str(env.get("remote_host") or "spark")
    print(f"\nTo download:")
    print(f"  scp {host}:{remote_path} {args.output}/", flush=True)
    return EXIT_OK


if __name__ == "__main__":
    try:
        sys.exit(main())
    except h3params.ParamError as e:
        print(f"[错误] {e}", file=sys.stderr, flush=True)
        sys.exit(EXIT_DETERMINISTIC)
    except Exception as e:  # noqa: BLE001 - 兜底：任何未预期异常都给出可定位输出
        print("发生未预期的内部错误：", file=sys.stderr, flush=True)
        traceback.print_exc()
        print(f"[内部错误] {e}", file=sys.stderr, flush=True)
        sys.exit(EXIT_INTERNAL)
