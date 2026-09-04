#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""book-03 流式可行性调研：qwen_agent 版本 / Assistant.run 粒度 / stream 相关 API。"""
import inspect

from qwen_agent import __version__ as _v
from qwen_agent.agents import Assistant

print("qwen_agent_version=", _v)
print("Assistant.run signature=", inspect.signature(Assistant.run))
try:
    from qwen_agent.llm.base import BaseChatModel  # noqa: F401
    print("BaseChatModel import ok")
except Exception as e:  # noqa: BLE001
    print("BaseChatModel err:", type(e).__name__, str(e)[:80])
try:
    import qwen_agent.llm as qa_llm
    print("qwen_agent.llm members:", [m for m in dir(qa_llm) if not m.startswith('_')][:20])
except Exception as e:  # noqa: BLE001
    print("qa_llm err:", e)
src = inspect.getsource(Assistant.run)
print("run source has 'stream':", "stream" in src)
print("run source has 'yield':", "yield" in src)
print("--- run source head ---")
for i, line in enumerate(src.splitlines()[:40]):
    print(f"{i:3d}| {line[:96]}")
