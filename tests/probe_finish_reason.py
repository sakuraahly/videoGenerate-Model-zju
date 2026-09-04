#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""book-04 调研：dump Message.extra（usage/finish_reason 可能在此）。"""
import sys, json
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from runs.agent.scheduler import LLM_CFG, SYSTEM_MESSAGE, TOOL_NAMES
from runs.agent import ctx_budget
llm = dict(LLM_CFG)
max_input, _ = ctx_budget.request_budgets(SYSTEM_MESSAGE)
llm["generate_cfg"] = {**(llm.get("generate_cfg") or {}), "max_input_tokens": max_input}
from qwen_agent.agents import Assistant
bot = Assistant(llm=dict(llm), system_message=SYSTEM_MESSAGE, function_list=list(TOOL_NAMES))
last = None
for chunk in bot.run(messages=[{"role": "user", "content": "你好"}]):
    last = chunk
m = last[0] if isinstance(last, list) and last else None
if isinstance(m, dict):
    print("KEYS:", list(m.keys()))
    print("EXTRA:", json.dumps(m.get("extra", {}), ensure_ascii=False)[:800])
else:
    print("TYPE:", type(m))
    for a in ("extra", "usage", "finish_reason"):
        if hasattr(m, a):
            print(a, "=", str(getattr(m, a))[:300])
