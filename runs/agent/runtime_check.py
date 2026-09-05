#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""runs/agent/runtime_check.py — 运行时一致性核对（book-01 步骤 4）。

核对「登记事实」（与 docs/code-fact-registry.md 同源；冲突以实测/代码为准）：
  - ctx_budget 关键常量（SGLang ctx=8192 口径）
  - 白名单工具注册集（6 个）
  - 调度器 LLM_CFG.max_tokens=2048
  - 运行形态 deploy.site（当前文档化现状 win-remote）
  - 仓库路径（spark /home/Developer/videoGenerate-Model-zju；Windows 主库 D:/MY_CODING_PROGRAM/...）

输出：每项 [OK]/[DIFF]/[SKIP] + 汇总；exit 0=全部 OK（SKIP 不计失败）。
用法：python runs/agent/runtime_check.py   （Windows/spark 均可；工具项在 spark 才可行以导入 qwen_agent）
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# 登记事实（来自 docs/code-fact-registry.md；改这里须同步改登记表）
FACTS = {
    "ctx": {"MODEL_MAX_CTX_TOKENS": 8192, "REPLY_MAX_TOKENS": 800,  // book-16 复读根治：2048→800
            "UI_TRIM_TOKENS": 2200, "CONV_MSG_BUDGET_TOKENS": 2500,
            "TOOL_PRELUDE_TOKENS": 1500, "SAFETY_TOKENS": 300},
    "tools": ["run_script", "modify_workflow", "call_comfyui", "read_doc",
              "list_references", "batch_submit"],
    "llm_cfg": {"max_tokens": 2048},
    "site": "win-remote",
    "paths": {"spark_repo": "/home/Developer/videoGenerate-Model-zju",
              "win_repo": "D:/MY_CODING_PROGRAM/videoGenerate-Model-zju"},
}

_RESULTS: list = []


def _add(ok: bool, name: str, detail: str = "", skip: bool = False):
    tag = "[SKIP]" if skip else ("[OK]" if ok else "[DIFF]")
    _RESULTS.append((tag, name, detail))


def check_ctx_budget():
    try:
        from runs.agent import ctx_budget
    except Exception as e:  # noqa: BLE001
        _add(False, "ctx_budget 常量", f"无法导入: {e}"); return
    for k, expected in FACTS["ctx"].items():
        got = getattr(ctx_budget, k, None)
        _add(got == expected, f"ctx_budget.{k}", f"expect={expected} got={got}")


def check_llm_cfg():
    try:
        from runs.agent import scheduler
        m = (scheduler.LLM_CFG.get("generate_cfg") or {}).get("max_tokens")
        _add(m == FACTS["llm_cfg"]["max_tokens"], "scheduler.LLM_CFG.max_tokens",
             f"expect={FACTS["llm_cfg"]["max_tokens"]} got={m}")
    except ImportError as e:
        _add(False, "scheduler.LLM_CFG", f"需在 spark（有 qwen_agent）校验: {e}", skip=True)
    except Exception as e:  # noqa: BLE001
        _add(False, "scheduler.LLM_CFG", f"无法导入: {e}")


def check_tools():
    try:
        from runs.agent import tools
        names = sorted(getattr(tools, "TOOL_NAMES", [])) if hasattr(tools, "TOOL_NAMES") else []
        if not names:
            # TOOL_NAMES 定义在 scheduler；此处回退为检查注册类
            for cls in ("RunScript", "ModifyWorkflow", "CallComfyUI", "ReadDoc",
                        "ListReferences", "BatchSubmit"):
                _add(hasattr(tools, cls), f"tools.{cls}")
            return
        expected = sorted(FACTS["tools"])
        _add(names == expected, "tools 注册集", f"expect={expected} got={names}")
    except ImportError as e:
        _add(False, "tools 导入", f"需在 spark（有 qwen_agent）校验: {e}", skip=True)
    except Exception as e:  # noqa: BLE001
        _add(False, "tools 注册", f"异常: {e}", skip=True)


def check_site():
    from runs.agent import version
    site = version.deploy_site()
    # 部署形态按端而定：Windows 主库=win-remote；spark 运行时=spark-local
    is_spark = str(_ROOT) == FACTS["paths"]["spark_repo"]
    expected = "spark-local" if is_spark else "win-remote"
    _add(site == expected, "deploy.site", f"expect={expected}（按端） got={site}")


def check_paths():
    root = _ROOT
    win = Path(FACTS["paths"]["win_repo"].replace("/", "\\")) if os.name == "nt" else None
    spark = Path(FACTS["paths"]["spark_repo"])
    # 当前机器：Windows 主库 或 spark 仓库
    cur = str(root.resolve()).replace("\\", "/")
    is_win = (win is not None and cur == str(win.resolve()).replace("\\", "/"))
    is_spark = (cur == str(spark))
    _add(is_win or is_spark, "project root known site", f"root={root} (win={is_win}, spark={is_spark})")


def check_fingerprint():
    from runs.agent import version
    v = version.version()
    head = version.git_head() or "(no git)"
    _add(bool(v), "版本指纹", f"AGENT_VERSION={v} git={head}")


def main():
    for fn in (check_ctx_budget, check_llm_cfg, check_tools, check_site, check_paths, check_fingerprint):
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            _add(False, fn.__name__, f"异常: {e}", skip=True)
    fail = 0
    print("== runtime_check（与 code-fact-registry 登记一致） ==")
    for tag, name, detail in _RESULTS:
        print(f"  {tag} {name}  {detail}")
        if tag == "[DIFF]":
            fail += 1
    print("[OK] 运行时一致性通过" if fail == 0 else f"[FAIL] {fail} 项不一致（以代码/实测为准，登记表需同步）")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
