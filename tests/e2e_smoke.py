#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/e2e_smoke.py — 防绕过自测门禁（book-01 步骤 5 / book-09 铁律）。

在 spark 真实环境运行（Windows 可部分运行；工具项需 qwen_agent）：
  1. 版本指纹非空且与 git HEAD 一致
  2. 六个白名单工具类可导入
  3. h3_submit.py --stage t2v --dry-run 返回 0 且输出含 Resolution
  4. runtime_check 无 [DIFF]
输出末尾 SMOKE_OK / SMOKE_FAIL；exit 0/1。
用法：python tests/e2e_smoke.py   （spark 上：python3 tests/e2e_smoke.py）
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

IS_SPARK = (str(ROOT.resolve()) == "/home/Developer/videoGenerate-Model-zju")

FAIL = 0


def _check(ok: bool, name: str, detail: str = ""):
    global FAIL
    tag = "OK" if ok else "FAIL"
    print(f"  [{tag}] {name}  {detail}")
    if not ok:
        FAIL += 1


def _run(argv, cwd=None, timeout=120):
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                           cwd=cwd or str(ROOT))
        return p.returncode, p.stdout or "", p.stderr or ""
    except FileNotFoundError:
        return 127, "", "command not found"
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"


def main() -> int:
    print("== e2e smoke（book-01 基座门禁） ==")

    # 1) 版本指纹
    try:
        from runs.agent import version
        v = version.version()
        head = version.git_head()
        good = bool(v) and (v == head or v.startswith("file:"))
        _check(good, "版本指纹", f"AGENT_VERSION={v} git={head if head else '（无 git）'}")
        print(f"  [info] root={version.project_root()} site={version.deploy_site()}")
    except Exception as e:  # noqa: BLE001
        _check(False, "版本指纹", f"异常 {e}")

    # 2) 工具类可导入（需要 qwen_agent）
    try:
        from runs.agent import tools
        names = ["RunScript", "ModifyWorkflow", "CallComfyUI", "ReadDoc",
                 "ListReferences", "BatchSubmit"]
        missing = [n for n in names if not hasattr(tools, n)]
        _check(not missing, "工具类导入", "6 类齐全" if not missing else f"缺 {missing}")
    except ImportError as e:  # noqa: BLE001
        if IS_SPARK:
            _check(False, "工具类导入", f"spark 上缺 qwen_agent: {e}")
        else:
            print(f"  [SKIP] 工具类导入  需 spark(qwen_agent)，本机跳过: {e}")
    except Exception as e:  # noqa: BLE001
        _check(False, "工具类导入", f"异常 {e}")

    # 3) h3_submit --dry-run（dry-run 不消耗 GPU/不提交；--force-new 仅用于绕过遗留断点守卫做纯校验）
    rc, out, err = _run([sys.executable, str(ROOT / "runs" / "h3_submit.py"),
                         "--stage", "t2v", "--dry-run", "--force-new"])
    ok = (rc == 0) and ("Resolution:" in out) and len(out) > 0
    tail = out.splitlines()[-1] if out.splitlines() else (err.strip()[-120:] or "")
    _check(ok, "h3_submit t2v --dry-run", f"rc={rc} tail={tail[:80]}")

    # 3b) UI 实况（spark）：/config 是否渲染已知新文案（防"编译通过但 UI 不构建/静默退出"）
    if IS_SPARK:
        try:
            import urllib.request
            cfg = urllib.request.urlopen("http://127.0.0.1:7860/config", timeout=15).read().decode("utf-8", "replace")
            ok = ("加载所选历史会话" in cfg) and ("继续承接任务" in cfg)
            _check(ok, "UI /config 实况", "命中新按钮文案" if ok else "未命中（UI 未构建/旧版？查看 ~/agent.log）")
        except Exception as e:  # noqa: BLE001
            _check(False, "UI /config 实况", f"无法访问 7860: {e}")
    else:
        print("  [SKIP] UI /config 实况  需 spark")

    # 4) runtime_check 一致性
    rc, out, err = _run([sys.executable, str(ROOT / "runs" / "agent" / "runtime_check.py")])
    ok = (rc == 0) and ("[DIFF]" not in out)
    last = [l for l in out.splitlines() if l.strip()]
    _check(ok, "runtime_check", f"rc={rc} last={last[-1][:80] if last else (err.strip()[-80:] or '')}")

    print("SMOKE_OK" if FAIL == 0 else f"SMOKE_FAIL（{FAIL} 项未过）")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
