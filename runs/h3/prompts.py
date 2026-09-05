"""
h3.prompts
==========
按工作流管理提示词：读 prompts/manifest.json，把“某工作流文件”映射到槽位
（prompts/workflows/<slot>.{positive,negative}.txt）；并支持把本地提示词
**自动注入**已转换/加载的扁平 API 工作流（覆盖模板内嵌的 prompt 字段）。

优先级：CLI(--prompt/--prompt-file) > 该工作流槽位文件(非空) > 阶段默认文件 >
manifest default（prompts/positive_prompts.txt 等）。文件为空视为未设置。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Optional, Tuple

from .params import ParamError, read_prompt_file

MANIFEST_NAME = "manifest.json"
_DEFAULT_MANIFEST = {
    "prompt_dir": "prompts/workflows",
    "default": {
        "positive": "prompts/positive_prompts.txt",
        "negative": "prompts/negative_prompts.txt",
    },
    "slots": {},
    "workflow_files": {},
}


def manifest_path(project_dir: Path) -> Path:
    return Path(project_dir) / "prompts" / MANIFEST_NAME


def load_manifest(project_dir: Path) -> dict:
    p = manifest_path(project_dir)
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8-sig"))
            if isinstance(data, dict) and isinstance(data.get("slots"), dict):
                return data
        except (OSError, json.JSONDecodeError):
            pass
    return json.loads(json.dumps(_DEFAULT_MANIFEST))


def slot_for_workflow_file(project_dir: Path, template_name: str) -> str:
    """由工作流文件名查槽位；未注册返回 ''。"""
    if not template_name:
        return ""
    m = load_manifest(project_dir)
    return str((m.get("workflow_files") or {}).get(template_name) or "")


def slot_text_paths(project_dir: Path, slot: str,
                    manifest: Optional[dict] = None) -> Tuple[Optional[Path], Optional[Path]]:
    m = manifest or load_manifest(project_dir)
    entry = (m.get("slots") or {}).get(slot)
    if not entry:
        return None, None

    def _abs(rel: str) -> Optional[Path]:
        if not rel:
            return None
        p = Path(project_dir) / rel
        return p

    return _abs(str(entry.get("positive") or "")), _abs(str(entry.get("negative") or ""))


def default_text_paths(project_dir: Path,
                       manifest: Optional[dict] = None) -> Tuple[Optional[Path], Optional[Path]]:
    m = manifest or load_manifest(project_dir)
    d = m.get("default") or {}
    p = Path(project_dir) / str(d.get("positive") or "prompts/positive_prompts.txt")
    n = Path(project_dir) / str(d.get("negative") or "prompts/negative_prompts.txt")
    return p, n


def pick_prompt_paths(
    project_dir: Path,
    stage: dict,
    template_file: Optional[Path],
    cli_positive: Optional[str],
    cli_negative: Optional[str],
) -> Tuple[Optional[Path], Optional[Path]]:
    """
    决定本次运行的提示词文件：CLI 文件 > 该工作流槽位文件 > 阶段默认文件。
    cli_positive/cli_negative 为 --prompt-file/--negative-prompt-file。
    """
    m = load_manifest(project_dir)

    def _nonempty(p: Optional[Path]) -> bool:
        """文件存在且 strip 后非空（空文件视为未设置，与模块 docstring 一致）。"""
        if p is None or not p.exists():
            return False
        try:
            return bool(p.read_text(encoding="utf-8-sig").strip())
        except OSError:
            return False

    def _first(existing: Optional[Path], slot_opt: Optional[Path],
               stage_default: Optional[Path]) -> Optional[Path]:
        for cand in (existing, slot_opt, stage_default):
            if _nonempty(cand):
                return cand
        return None

    tname = Path(template_file).name if template_file else ""
    slot = slot_for_workflow_file(project_dir, tname)
    slot_p, slot_n = slot_text_paths(project_dir, slot, m)

    sp_pos = Path(project_dir) / str((stage.get("prompt_files") or {}).get("positive") or "")
    sp_neg = Path(project_dir) / str((stage.get("prompt_files") or {}).get("negative") or "")

    pos = _first(Path(cli_positive) if cli_positive else None,
                 slot_p if slot_p and slot_p.exists() else None,
                 sp_pos if str(sp_pos) and sp_pos.exists() else None)
    neg = _first(Path(cli_negative) if cli_negative else None,
                 slot_n if slot_n and slot_n.exists() else None,
                 sp_neg if str(sp_neg) and sp_neg.exists() else None)
    if pos is None:
        pos, _ = default_text_paths(project_dir, m)
    if neg is None:
        _, neg = default_text_paths(project_dir, m)
    return pos, neg


def read_text_path(path: Optional[Path], what: str) -> str:
    if path is None or not path.exists():
        return ""
    return read_prompt_file(path)


def write_slot_texts(
    project_dir: Path, slot: Optional[str], positive: str, negative: str,
    defaults: bool = False,
) -> Tuple[Path, Path]:
    """
    写入某槽位（或 default 槽）的正/负提示词文件。
    slot=None 且 defaults=True 时写 manifest.default（即 legacy 正/负两个文件）。
    """
    m = load_manifest(project_dir)
    if defaults:
        p1, p2 = default_text_paths(project_dir, m)
    else:
        p1, p2 = slot_text_paths(project_dir, slot or "", m)
    if p1 is None or p2 is None:
        raise ParamError(f"未知提示词槽位: {slot}")

    def _write(p: Optional[Path], text: str) -> None:
        if p is None:
            return
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text.strip() + ("\n" if text.strip() else ""), encoding="utf-8")

    _write(p1, positive)
    _write(p2, negative)
    return p1, p2


# ---------------------------------------------------------------------------
# 注入：把本地提示词写进 API 工作流（覆盖模板内嵌值）
# ---------------------------------------------------------------------------
_PROMPT_KEY_HITS = ("prompt", "positive", "text")
_NEG_KEY_HITS = ("negative",)


def _basename(key: str) -> str:
    return key.split(".")[-1].lower()


def inject_local_prompts(api: dict, positive: str, negative: str, spec: dict = None) -> int:
    """
    就地修改 api 工作流，把 prompt/negative 写入可识别的字段。
    - spec（book-12 注册表声明）：形如 {"class_prefix": "MiniMaxH3", "positive_key": "prompt",
      "negative_key": "negative_prompt"} —— 在 class_type 以 class_prefix 开头的节点上直接写入
      positive_key/negative_key（字符串直写，与内置生成器提交格式一致；不依赖上游 primitives）；
      命中即返回，不走到启发式（避免误改其它 prompt 字段）。
    - 无 spec / 未命中：回退 basename 启发式（普通 widget 字符串值 basename 命中
      prompt/positive/text 或 negative 则替换；连线输入则改写上游 primitive 节点字符串值）。
    返回发生替换的字段数。
    """
    if not positive and not negative:
        return 0

    # ---- book-12：注册表注入点优先（精确、不误伤） ----
    if spec and isinstance(spec, dict):
        prefix = str(spec.get("class_prefix") or "")
        pkey = str(spec.get("positive_key") or "")
        nkey = str(spec.get("negative_key") or "")
        if prefix:
            for node in api.values():
                if not isinstance(node, dict):
                    continue
                if not str(node.get("class_type") or "").startswith(prefix):
                    continue
                ins = node.get("inputs") or {}
                changed = 0
                if positive and pkey and pkey in ins and ins[pkey] != positive:
                    ins[pkey] = positive
                    changed += 1
                if negative and nkey and nkey in ins and ins[nkey] != negative:
                    ins[nkey] = negative
                    changed += 1
                return changed
    return _inject_heuristic(api, positive, negative)


def _inject_heuristic(api: dict, positive: str, negative: str) -> int:
    """旧启发式（无注册表 spec 时的回退路径）。"""
    changed = 0

    def _set(key: str, val: str) -> bool:
        nonlocal changed
        if key not in node_inputs:
            return False
        if isinstance(node_inputs[key], str):
            node_inputs[key] = val
            changed += 1
            return True
        return False

    for node in api.values():
        if not isinstance(node, dict):
            continue
        cls = str(node.get("class_type") or "")
        node_inputs = node.get("inputs") or {}
        if not isinstance(node_inputs, dict):
            continue
        for key, value in list(node_inputs.items()):
            base = _basename(key)
            if isinstance(value, str):
                if positive and base in _PROMPT_KEY_HITS:
                    _set(key, positive)
                elif negative and any(n in base for n in _NEG_KEY_HITS):
                    _set(key, negative)
                continue
            # 连线输入：尝试改写上游 primitive 节点
            if positive and base in _PROMPT_KEY_HITS and isinstance(value, list) and value:
                src = str(value[0])
                src_node = api.get(src)
                if not isinstance(src_node, dict):
                    continue
                scls = str(src_node.get("class_type") or "").lower()
                if "primitive" in scls or "string" in scls or "text" in scls:
                    sin = src_node.get("inputs") or {}
                    for sk, sv in list(sin.items()):
                        if isinstance(sv, str):
                            sin[sk] = positive
                            changed += 1
                            break
    return changed
