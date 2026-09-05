#!/usr/bin/env python3
"""queue_probe — ComfyUI 队列【只读】探测与归属判定（book-12 A5/L5）。

共享服务器纪律：只读！本脚本绝不包含任何 /queue/delete、取消、清队等写操作；
删除/取消必须先按归属校验（见 book-14 红线），未实现=禁止。

输出 JSON：
  {"running": [{"qid","prompt_id","nodes","tag"}], "pending": [...],
   "known_count": N, "last_known": bool}
tag: 本机登记（last_job.json 命中）| 本项目任务（workflows/*/job.json 命中）| 外部/他人
"""
from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path

ROOT = Path(os.environ.get(
    "VIDEOGEN_PROJECT_ROOT", os.path.expanduser("~/videoGenerate-Model-zju")))
COMFY = "http://127.0.0.1:8188"


def _get(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=5) as r:
        return json.loads(r.read().decode())


def collect() -> dict:
    q = _get(COMFY + "/queue")
    last = ""
    rj = ROOT / "last_job.json"
    if rj.exists():
        try:
            last = str(json.loads(rj.read_text(encoding="utf-8")).get("prompt_id") or "")
        except Exception:  # noqa: BLE001
            pass
    known: set = set()
    for f in ROOT.glob("workflows/h3_*/job.json"):
        try:
            pid = str(json.loads(f.read_text(encoding="utf-8")).get("prompt_id") or "")
            if pid:
                known.add(pid)
        except Exception:  # noqa: BLE001
            continue
    rows = {"running": [], "pending": []}
    for kind, items in (("running", q.get("queue_running") or []),
                        ("pending", q.get("queue_pending") or [])):
        for it in items:
            pid = str(it[1] if len(it) > 1 else "")
            if pid and pid == last:
                tag = "本机登记"
            elif pid in known:
                tag = "本项目任务"
            else:
                tag = "外部/他人"
            rows[kind].append({"qid": it[0], "prompt_id": pid[:16],
                               "nodes": (len(it[2]) if len(it) > 2 and isinstance(it[2], dict) else None),
                               "tag": tag})
    return {"running": rows["running"], "pending": rows["pending"],
            "known_count": len(known), "last_known": bool(last)}


def main() -> int:
    try:
        print(json.dumps(collect(), ensure_ascii=False))
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"error": str(e)}, ensure_ascii=False))
        return 1
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
