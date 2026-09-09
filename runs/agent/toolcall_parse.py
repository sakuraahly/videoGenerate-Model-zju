"""toolcall_parse — qwen3.8 native tool-call 解析（SGLang 原样吐出 <tool_call> 标签）。"""
import re


def _split_args(extra_args: str) -> list:
    """run_script 参数解析（2026-09-09 修复高频坑）：shlex 保留引号语义——

    模型曾以 --prompt \"A cat at night...\" 传参，旧 split() 按空白切开导致
    'unrecognized arguments'（'提示词含空格未加引号'循环失败的根因）；
    shlex 正确处理成对引号；解析失败回退空白切分（旧行为保底）。
    """
    if not extra_args:
        return []
    try:
        import shlex
        return shlex.split(extra_args)
    except Exception:  # noqa: BLE001
        return str(extra_args).split()


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
