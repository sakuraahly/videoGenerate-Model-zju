"""
h3.templates
============
工作流模板工具：读取/校验模板 JSON，并在字符串值里递归替换占位符。

占位符约定（模板字符串中写 ``{{token}}``，如 ``{{prompt}}`` / ``{{image0}}``）：
  * 仅匹配字符串值，数字/列表/对象不受影响；
  * 大小写敏感、允许空白（``{{ prompt }}`` 亦可）；
  * 未提供的 token 会被收集返回，供调用方决定是否报错。

纯标准库、无网络，便于单测。模板示例见 config/pipeline.json。
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

_TOKEN_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}")


def load_json_file(path: Path) -> Any:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"文件不存在: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as e:
        raise ValueError(f"JSON 解析失败（{e}）: {path}") from e


def is_ui_workflow(obj: Any) -> bool:
    """ComfyUI UI 格式（含 nodes/links 顶层键）。"""
    return isinstance(obj, dict) and isinstance(obj.get("nodes"), list)


def is_api_workflow(obj: Any) -> bool:
    """扁平 API 格式：所有值为含 class_type 的节点对象。"""
    return (
        isinstance(obj, dict)
        and bool(obj)
        and all(
            isinstance(v, dict) and isinstance(v.get("class_type"), str)
            for v in obj.values()
        )
    )


def validate_workflow(obj: Any) -> None:
    """校验：API 或 UI 格式均可，否则抛 ValueError。"""
    if is_ui_workflow(obj):
        bad = [n for n in obj.get("nodes", []) if not isinstance(n, dict) or not n.get("type")]
        if bad:
            raise ValueError("UI 模板存在缺少 type 的节点。")
        return
    if is_api_workflow(obj):
        return
    raise ValueError("工作流模板既不是扁平 API 格式（节点均有 class_type），"
                     "也不是 UI 格式（含 nodes/links）。请确认文件内容。")


def api_to_submittable(obj: Any) -> dict:
    """返回可直接提交的扁平 API dict；UI 格式模板抛错（CLI 不支持 UI 模板）。"""
    if not is_api_workflow(obj):
        raise ValueError(
            "该模板是 ComfyUI UI 格式（nodes/links），命令行无法直接提交。"
            "请改放扁平 API 格式模板，或在 ComfyUI 界面中加载后另存 API 格式。"
        )
    return obj


def collect_tokens(obj: Any) -> List[str]:
    """收集所有字符串值中出现的占位符 token 名（去重、按首次出现排序）。"""
    found: List[str] = []
    seen = set()

    def walk(x: Any) -> None:
        if isinstance(x, str):
            for m in _TOKEN_RE.finditer(x):
                t = m.group(1)
                if t not in seen:
                    seen.add(t)
                    found.append(t)
        elif isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)

    walk(obj)
    return found


def substitute(
    obj: Any,
    mapping: Dict[str, str],
    ignore_missing: Iterable[str] = (),
) -> Tuple[Any, List[str]]:
    """
    递归替换字符串里的 ``{{token}}``。

    mapping: token -> 替换文本（不要带花括号）。
    返回 (新对象, 缺失token列表)。缺失检测忽略 ignore_missing 中的 token。
    """
    ignore = set(ignore_missing)

    def _sub(text: str) -> str:
        def repl(m: "re.Match[str]") -> str:
            token = m.group(1)
            return mapping.get(token, m.group(0))

        return _TOKEN_RE.sub(repl, text)

    missing: List[str] = []
    seen_missing = set()

    def walk(x: Any) -> Any:
        if isinstance(x, str):
            out = _sub(x)
            for m in _TOKEN_RE.finditer(out):
                t = m.group(1)
                if t not in mapping and t not in ignore and t not in seen_missing:
                    seen_missing.add(t)
                    missing.append(t)
            return out
        if isinstance(x, dict):
            return {k: walk(v) for k, v in x.items()}
        if isinstance(x, list):
            return [walk(v) for v in x]
        return x

    return walk(obj), missing
