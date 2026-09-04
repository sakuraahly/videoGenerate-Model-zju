#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/regress_auto_continue_round.py — 自动续接不再注入 role:system（book-03 §0 回归）。

spark 运行（venv python）：/home/Developer/qwen-agent-venv/bin/python tests/regress_auto_continue_round.py
链路：确保 LLM 就绪 → 第一轮 user=你好 → 模拟修复后的续接（role=user）→ 第二轮不得再报 400。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    from runs.agent.scheduler import LLM_CFG, SYSTEM_MESSAGE, TOOL_NAMES
    from runs.agent import ctx_budget, llm_mem as lmem

    print("== regress: 自动续接 system->user ==")
    if not lmem.ensure_llm_up(timeout_s=600):
        print("REGRESS_FAIL: LLM 唤醒失败（人工查 ~/sglang.log）")
        return 1

    llm = dict(LLM_CFG)
    max_input, _ = ctx_budget.request_budgets(SYSTEM_MESSAGE)
    llm["generate_cfg"] = {**(llm.get("generate_cfg") or {}), "max_input_tokens": max_input}

    from qwen_agent.agents import Assistant

    def run_one(msgs):
        bot = Assistant(llm=dict(llm), system_message=SYSTEM_MESSAGE, function_list=list(TOOL_NAMES))
        last = None
        for chunk in bot.run(messages=msgs):
            last = chunk
        return last or []

    msgs = [{"role": "user", "content": "你好"}]
    try:
        last = run_one(msgs)
        msgs = msgs + list(last)
        print("  [round1] 输出片段: " + str((last or [{}])[-1].get('content', ''))[:60])
        # 修复后的续接（role=user；旧版为 role=system 会触发 one-system-message 400）
        msgs.append({"role": "user", "content": "[系统自动续接] 请继续完成当前任务。"})
        last2 = run_one(msgs)
        print("  [round2] 输出片段: " + str((last2 or [{}])[-1].get('content', ''))[:60])
        print("REGRESS_OK: 两轮通过，无 one-system-message 400")
        return 0
    except Exception as e:  # noqa: BLE001
        print("REGRESS_FAIL:", type(e).__name__, str(e)[:400])
        return 1


if __name__ == "__main__":
    sys.exit(main())
