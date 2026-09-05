#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_should_continue_unit.py — should_continue 纯函数单测（book-04；无需 qwen_agent）。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runs.agent.ui_app import should_continue as sc  # noqa: E402

CASES = [
    ("你好", "你好！我是本地视频生成助手，简单说说你的创意即可。", [], False, "寒暄答完不续"),
    ("你好", "你好！回复", ["abc"], False, "有 prompt_id 不续"),
    ("帮我生成一段转场视频", "好的，我先列出素材并规划每段转场。", [], True, "任务意图需推进"),
    ("生成视频", "TASK_SUBMITTED: xxx", ["xxx"], False, "已提交不续"),
    ("随便聊聊", "A" * 1500, [], True, "疑似截断续"),
    ("随便聊聊", "A" * 1500 + "。完成。", [], False, "长但完整不续"),
    ("你好", "⛔ 熔断：请稍后再试", [], False, "熔断不续"),
    ("你好", "", [], False, "无输出不续"),
    ("列一下当前会话素材", "当前会话素材共 2 项…需要我用其中某张做参考图生成视频，直接说即可。", [], False, "book-16：征询式结尾不续"),
    ("列一下素材", "素材列表如下…是否继续生成？", [], False, "book-16：问句结尾不续"),
]


def main() -> int:
    ok = True
    for u, fi, pid, exp, name in CASES:
        got = sc(u, fi, pid)
        t = "PASS" if got == exp else "FAIL"
        print(f"  [{t}] {name}: got={got} exp={exp}")
        ok = ok and (got == exp)
    print("UNIT_OK" if ok else "UNIT_FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
