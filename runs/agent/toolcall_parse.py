"""toolcall_parse — qwen3.8 native tool-call 解析（SGLang 原样吐出 <tool_call> 标签）。"""
import re

_TOOL_CALL_RE = re.compile(
    r"<tool_call>\s*<function=(?P<name>[^>]+)>(?P<args>.*?)</function>\s*</tool_call>",
    re.DOTALL)


def _parse_tool_calls(text: str) -> tuple:
    """解析 <tool_call>/<function=..> 内嵌调用。返回 (调用列表[(name, args)], 剔除标签后的纯文本)。"""
    if not text or "<tool_call>" not in text:
        return [], (text or "")
    calls = []
    for m in _TOOL_CALL_RE.finditer(text):
        calls.append((m.group("name").strip(), (m.group("args") or "").strip()))
    cleaned = _TOOL_CALL_RE.sub("", text).strip()
    return calls, cleaned
