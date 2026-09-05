"""
h3.stage
========
“多工作流配合”的注册表与单阶段解析：读取 config/pipeline.json，
把一次运行归一化为：
  1) 阶段（stage）配置（模板 or 内置生成器）；
  2) 文本输入（提示词等，来自 CLI 或阶段配置的默认文件）；
  3) 图片输入列表（CLI --image 或阶段 default_images，可被模板占位符引用）；
  4) 需要上传的输入图（提交前由调用方调用 ComfyClient.upload_image 后回填文件名）。

依赖关系：params（校验/参数文件）、templates（占位符/校验）。
不依赖网络与远端状态。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import templates, workflow as h3workflow
from .params import LAYOUT, ParamError, read_prompt_file

PIPELINE_FILE = "pipeline.json"

# pipeline.json 缺失/损坏时的极简回退：保证旧版（内置 H3 T2V）永远可用
_DEFAULT_CONFIG = {
    "default_stage": "t2v",
    "templates_dir": "config/templates",
    "stages": {
        "t2v": {
            "description": "内置 H3 文生视频（T2V，回退模式）",
            "kind": "video",
            "template": "",
            "template_kind": "api",
            "builtin": "h3_t2v",
            "prompt_files": {
                "positive": "prompts/positive_prompts.txt",
                "negative": "prompts/negative_prompts.txt",
            },
            "default_images": [],
        }
    },
}

# 本工具自动填充的占位符（映射值均为字符串）
KNOWN_TOKENS = (
    "prompt", "negative_prompt", "seed", "width", "height",
    "seconds", "length", "fps", "steps",
)


def load_pipeline_config(project_dir: Path) -> dict:
    """读取 config/pipeline.json；缺失/损坏回退内置默认（不阻断旧流程）。"""
    path = Path(project_dir) / LAYOUT["config_dir"] / PIPELINE_FILE
    if not path.exists():
        return json.loads(json.dumps(_DEFAULT_CONFIG))
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return json.loads(json.dumps(_DEFAULT_CONFIG))
    if not isinstance(data, dict) or not isinstance(data.get("stages"), dict):
        return json.loads(json.dumps(_DEFAULT_CONFIG))
    return data


def pipeline_config_path(project_dir: Path) -> Path:
    return Path(project_dir) / LAYOUT["config_dir"] / PIPELINE_FILE


def list_stages(config: dict) -> List[Dict[str, Any]]:
    out = []
    for sid, s in (config.get("stages") or {}).items():
        out.append(
            {
                "id": sid,
                "description": str(s.get("description") or ""),
                "kind": str(s.get("kind") or ""),
                "builtin": str(s.get("builtin") or ""),
                "template": str(s.get("template") or ""),
            }
        )
    return out


def resolve_stage(config: dict, stage_id: str) -> dict:
    stages = config.get("stages") or {}
    if stage_id not in stages:
        ids = ", ".join(sorted(stages))
        raise ParamError(f"未知的生成阶段 '{stage_id}'。可用阶段: {ids}")
    out = dict(stages[stage_id])
    out["_id"] = stage_id
    return out


def default_stage_id(config: dict) -> str:
    return str(config.get("default_stage") or "t2v")


def templates_dir(config: dict, project_dir: Path) -> Path:
    rel = str(config.get("templates_dir") or "config/templates")
    return Path(project_dir) / rel


def template_path(config: dict, project_dir: Path, stage: dict) -> Path:
    name = str(stage.get("template") or "").strip()
    if not name:
        return Path()
    return templates_dir(config, project_dir) / name


def gather_prompt_paths(
    project_dir: Path, stage: dict, cli_prompt_file: Optional[str],
    cli_negative_file: Optional[str],
) -> Tuple[Optional[Path], Optional[Path]]:
    """提示词文件路径：CLI 优先，其次阶段配置默认；都没有则 None。"""
    def _pick(cli: Optional[str], key: str) -> Optional[Path]:
        if cli:
            return Path(cli).resolve()
        rel = ((stage.get("prompt_files") or {}).get(key) or "").strip()
        if not rel:
            return None
        return (Path(project_dir) / rel).resolve()

    return _pick(cli_prompt_file, "positive"), _pick(cli_negative_file, "negative")


def gather_images(
    project_dir: Path, stage: dict, cli_images: Optional[List[str]],
) -> List[Path]:
    """输入图绝对路径列表（CLI --image 优先，其次阶段 default_images）。"""
    raw: List[str] = list(cli_images or [])
    if not raw:
        raw = [str(p) for p in (stage.get("default_images") or [])]
    out: List[Path] = []
    # book-06/07：补丁——像 h3_batch 一样在 uploads/ 与 ComfyUI input/ 中做智能查找
    # （agent 传 "up:1 房间.png"/"d42fe581_飞船发射台.png" 这类素材名也能解析）
    for p in raw:
        cand = _resolve_input_image(project_dir, p)
        out.append(cand)
    return out


def _resolve_input_image(project_dir: Path, ref: str) -> Path:
    """解析输入图：绝对/相对路径 > 项目 uploads/**（按文件名）> ComfyUI input/**（按文件名）。"""
    p = Path(ref)
    if p.is_absolute() and p.exists():
        return p.resolve()
    if not p.is_absolute():
        rel = (project_dir / p)
        if rel.exists():
            return rel.resolve()
        # 素材名可能带 "up:1 " 前缀（list 输出）或纯文件名
        name = ref.split(":", 1)[-1].split("/")[-1].strip()
        for base in (project_dir / "uploads", Path.home() / "ai" / "ComfyUI" / "input"):
            try:
                env = json.loads((project_dir / "config" / "environment.json").read_text(encoding="utf-8-sig"))
                if "ai" in str(base) or "ComfyUI" in str(base):
                    base = Path(str(env.get("remote_comfyui_dir", "~/ai/ComfyUI")).replace("~", str(Path.home()))) / "input"
            except Exception:
                pass
            for sub in sorted(base.iterdir(), reverse=True) if base.is_dir() else []:
                if sub.is_dir():
                    hit = sub / name
                    if hit.is_file():
                        return hit.resolve()
                elif sub.name == name and sub.is_file():
                    return sub.resolve()
        raise ParamError(f"输入图不存在（请用本会话素材名或绝对路径）: {ref}")
    raise ParamError(f"输入图不存在: {ref}")


def read_stage_texts(
    positive_path: Optional[Path], negative_path: Optional[Path],
) -> Tuple[str, str]:
    positive = read_prompt_file(positive_path) if positive_path else ""
    negative = read_prompt_file(negative_path) if negative_path else ""
    return positive, negative


def apply_lora(wf: dict, lora_id: str, lora_map: dict) -> int:
    """book-12 B1：把加速 LoRA 注入 API 工作流。

    - 找 UNETLoader 节点（video 模型卸载源）；
    - 插入 LoraLoaderModelOnly（model-only，避免 clip 依赖）；
    - 所有引用 [unid,0] 的 model 输入改接 [lora_id,0]；
    - BasicScheduler.steps 覆写为 lora_map['steps'][lora_id]（默认 4）。
    返回改动节点数；无 UNETLoader/未知 lora 时返回 0（不报错）。
    """
    if not lora_id or lora_id == "none":
        return 0
    files = (lora_map or {}).get("files") or {}
    fname = files.get(lora_id)
    if not fname:
        return 0
    steps = int((lora_map.get("steps") or {}).get(lora_id, 4))
    unet_ids = [nid for nid, n in wf.items()
                if isinstance(n, dict) and n.get("class_type") == "UNETLoader"]
    if not unet_ids:
        return 0
    unid = unet_ids[0]
    new_id = "lora_" + str(len(wf))
    wf[new_id] = {"class_type": "LoraLoaderModelOnly",
                  "inputs": {"model": [unid, 0], "lora_name": fname,
                             "strength_model": 1.0}}
    changed = 0
    for nid, n in wf.items():
        if nid == new_id or not isinstance(n, dict):
            continue  # LoraLoader 自身保持 [unid, 0]，防自环
        ins = n.get("inputs") or {}
        for k, v in list(ins.items()):
            if isinstance(v, list) and len(v) == 2 and v[0] == unid:
                ins[k] = [new_id, 0]
                changed += 1
    for n in wf.values():
        if isinstance(n, dict) and n.get("class_type") == "BasicScheduler":
            ins = n.get("inputs") or {}
            if ins.get("steps") != steps:
                ins["steps"] = steps
                changed += 1
    return changed


def text_token_map(gp: Any) -> Dict[str, str]:
    """把生成参数转为占位符映射（不含图片 token）。"""
    return {
        "prompt": gp.prompt,
        "negative_prompt": gp.negative_prompt,
        "seed": str(gp.seed),
        "width": str(gp.width),
        "height": str(gp.height),
        "seconds": str(gp.seconds),
        "length": str(gp.length),
        "fps": str(gp.fps),
        "steps": str(gp.steps),
    }


def require_api_template_file(tpath: Path) -> None:
    """
    校验模板文件是“扁平 API 格式”；UI/无效格式或缺失时抛 ParamError（带指引）。
    """
    if not tpath or not tpath.exists():
        raise ParamError(
            f"模板不存在: {tpath}\n请把 API(扁平) 模板放入 config/templates 目录，"
            f"或在 config/pipeline.json 中修改 template 字段。"
        )
    try:
        raw = templates.load_json_file(tpath)
    except ValueError as e:
        raise ParamError(str(e)) from e
    if templates.is_api_workflow(raw):
        return
    if templates.is_ui_workflow(raw):
        raise ParamError(
            f"模板 {tpath} 是 ComfyUI UI 格式（nodes/links）。"
            "若要在命令行提交，请先经 UI→API 在线转换（需连接 ComfyUI），"
            "或在 ComfyUI 中 Save(API Format) 导出扁平 API。"
        )
    raise ParamError(f"模板 {tpath} 不是有效的扁平 API 工作流。")


def apply_generation_params(wf: dict, token_map: Dict[str, str]) -> int:
    """book-12 修复：UI→API 在线转换后的模板把参数以「模板默认值」带入
    （实测：ResolutionSelector 0.4MP=480p、时长表达式 5s —— 与请求 720p/15s 不符）。
    这里按请求参数强制覆写生成节点：MiniMaxH3* 的 width/height/length、
    BasicScheduler 的 steps、CreateVideo 的 fps。返回覆写节点数（0=无匹配，不报错）。
    """
    def num(key: str):
        try:
            return int(float(token_map.get(key, "")))
        except Exception:  # noqa: BLE001
            return None

    width, height = num("width"), num("height")
    length = num("length")
    steps = num("steps")
    fps = num("fps")
    count = 0
    for n in wf.values():
        if not isinstance(n, dict):
            continue
        ct = str(n.get("class_type") or "")
        ins = n.get("inputs") or {}
        if ct.startswith("MiniMaxH3"):
            changed = False
            for k, v in (("width", width), ("height", height), ("length", length)):
                if v is not None and k in ins and ins[k] != v:
                    ins[k] = v
                    changed = True
            if changed:
                count += 1
        elif ct == "BasicScheduler" and steps is not None and "steps" in ins and ins["steps"] != steps:
            ins["steps"] = steps
            count += 1
        elif ct == "CreateVideo" and fps is not None and "fps" in ins:
            try:
                cur = float(ins["fps"])
            except (TypeError, ValueError):
                cur = None
            if cur is not None and cur != fps:
                ins["fps"] = fps
                count += 1
    return count


def load_api_or_ui_template(
    tpath: Path, client: Optional["comfy.ComfyClient"] = None,
) -> dict:
    """
    读取模板：扁平 API 直接返回；UI 格式则调用在线转换（需 client + /object_info）。
    无法转换抛 ParamError/UiUnsupported。
    """
    from . import uiapi

    tpath = Path(tpath)
    if not tpath.exists():
        raise ParamError(f"模板不存在: {tpath}")
    raw = templates.load_json_file(tpath)
    if templates.is_api_workflow(raw):
        return raw
    if templates.is_ui_workflow(raw):
        if client is None:
            raise ParamError(
                f"模板 {tpath} 是 UI 格式，转换为可提交 API 需要连接在线 ComfyUI"
                "（object_info）。请先建立隧道后重试，或手动 Save(API Format) 导出。"
            )
        return uiapi.convert_ui_file(tpath, client)
    raise ParamError(f"模板 {tpath} 不是有效的 API 或 UI 工作流。")


def substitute_api_workflow(
    wf: dict, token_map: Dict[str, str], image_names: Dict[str, str],
) -> dict:
    """对内存中的 API 工作流做占位符替换；缺失 token 抛 ParamError。"""
    mapping = dict(token_map)
    mapping.update(image_names)
    out, missing = templates.substitute(wf, mapping)
    if missing:
        raise ParamError(
            f"模板含未提供的占位符: {', '.join(sorted(set(missing)))}。\n"
            f"可用文本占位符: {', '.join(KNOWN_TOKENS)}；图片占位符: {{image0}}, {{image1}}, ..."
        )
    return out


def build_template_workflow(
    stage: dict, config: dict, project_dir: Path,
    token_map: Dict[str, str],
    image_names: Dict[str, str],
    template_file: Optional[Path] = None,
    client: Optional["comfy.ComfyClient"] = None,
) -> dict:
    """
    读取模板并做占位符替换后返回可提交的 API 工作流。

    template_file: 显式模板路径（--template）；缺省用 stage.template。
    token_map/image_names: 占位符值（不含图片上传名，image_names 为已上传后的名字）。
    client: 在线 ComfyUI 客户端；模板为 UI 格式时必须提供以做 UI→API 转换。
    模板缺失、UI 无法转换或含未提供占位符都会抛 ParamError 提示。
    """
    tpath = Path(template_file).resolve() if template_file else \
        template_path(config, project_dir, stage)
    if not tpath.name or not tpath.exists():
        raise ParamError(
            f"阶段 '{stage.get('_id', '?')}' 的模板不存在或为空: {tpath}\n"
            f"请将模板放入 {templates_dir(config, project_dir)} 目录，"
            f"或在 config/pipeline.json 中配置 template。"
        )
    wf = load_api_or_ui_template(tpath, client=client)
    wf = substitute_api_workflow(wf, token_map, image_names)
    # book-12 修复：转换结果按请求参数覆写（模板默认值≠请求参数的历史 bug）
    n_over = apply_generation_params(wf, token_map)
    if n_over:
        print(f"[提示] 已按请求参数覆写生成节点（{n_over} 处）：width/height/length/steps/fps ''"
              f"（修复模板默认 480p/5s 与请求 720p/15s 不一致）", flush=True)
    return wf


def build_builtin_workflow(stage: dict, gp: Any, images: List[Path]) -> dict:
    """内置生成器（目前仅 h3_t2v）。"""
    builtin = str(stage.get("builtin") or "")
    if builtin == "h3_t2v":
        if images:
            raise ParamError(
                f"阶段 '{stage.get('_id', '?')}' 使用内置 H3 T2V，不支持输入图"
                f"（收到 {len(images)} 张）。请改用 r2v/i2v/flf2v 等图生视频阶段。"
            )
        if not gp.prompt:
            raise ParamError(
                "内置 H3 T2V 需要正向提示词：请提供 --prompt / --prompt-file，"
                "或保证该阶段 prompt_files.positive 指向的文件存在。"
            )
        return h3workflow.build_workflow(
            gp.prompt, gp.width, gp.height, gp.length, gp.seed,
            negative_prompt=gp.negative_prompt, steps=gp.steps, fps=gp.fps,
        )
    raise ParamError(
        f"阶段 '{stage.get('_id', '?')}' 的 API 模板缺失且无内置生成器"
        f"（builtin='{builtin}'）。请把扁平 API 模板放入 config/templates 目录，"
        f"或在 config/pipeline.json 中调整 template / builtin 字段。"
    )
