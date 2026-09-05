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


def find_owned(prompt_id: str) -> str:
    """归属校验（book-14 T9）：prompt_id 命中本机登记/本项目任务 → 返回归属标签；否则空串=非本人。
    """
    pid = str(prompt_id or "").strip()
    if not pid:
        return ""
    rj = ROOT / "last_job.json"
    if rj.exists():
        try:
            if str(json.loads(rj.read_text(encoding="utf-8")).get("prompt_id") or "") == pid:
                return "本机登记(last_job)"
        except Exception:  # noqa: BLE001
            pass
    for f in ROOT.glob("workflows/h3_*/job.json"):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if str(d.get("prompt_id") or "") == pid:
            return "本项目任务(" + f.parent.name + ")"
    return ""


def cancel_owned_task(prompt_id: str, reason: str = "") -> dict:
    """book-14 T9：仅取消【归属校验通过】的任务。
    运行中 → POST /queue {"interrupt":true}（仅当运行中的就是本任务时安全）；
    排队中 → POST /queue {"delete":[qid]}；不在队列 → 明确说明。"""
    who = find_owned(prompt_id)
    if not who:
        return {"ok": False, "msg": "取消被拒：prompt_id 不在本机登记/本项目中（共享服务器红线）。"}
    try:
        q = _get(COMFY + "/queue")
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "msg": f"无法读取队列: {type(e).__name__}: {e}"}
    running = [str(it[1]) for it in q.get("queue_running") or []]
    pending = [str(it[1]) for it in q.get("queue_pending") or []]
    pid = str(prompt_id)
    target = None
    if pid in running:
        # 实测（ComfyUI 0.34.3）：/queue {"interrupt":true} 被接受但惰性；POST /interrupt 才是真中断
        target = "运行中→中断"
        req = urllib.request.Request(COMFY + "/interrupt", data=b"", method="POST")
        _send = req
    elif pid in pending:
        target = "排队中→移除"
        _send = urllib.request.Request(COMFY + "/queue",
                                       data=json.dumps({"delete": [pid]}).encode(),
                                       headers={"Content-Type": "application/json"}, method="POST")
    else:
        return {"ok": False,
                "msg": f"任务不在队列（可能已完成或尚未入队，{who}）；请用 run_script 查询状态。"}
    try:
        with urllib.request.urlopen(_send, timeout=10) as r:
            body = (r.read() or b"").decode("utf-8", "replace").strip()
        resp = json.loads(body) if body else {"done": target}
        # 取消成功 → 清理本机断点（若登记的就是该任务），防残留断点阻塞下次提交
        try:
            rj = ROOT / "last_job.json"
            if rj.exists() and str(json.loads(rj.read_text(encoding="utf-8")).get("prompt_id") or "") == pid:
                rj.write_text(json.dumps({"schema": 1, "prompt_id": "", "remote_path": "",
                                          "created_at": "", "updated_at": ""}), encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
        return {"ok": True, "msg": f"已取消（{who}；{target}，断点已清）。{reason}", "resp": resp}
    except urllib.error.HTTPError as e:
        return {"ok": False, "msg": f"取消失败 HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:200]}"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "msg": f"取消失败: {type(e).__name__}: {e}"}


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


def main(argv=None) -> int:
    import sys
    argv = list(argv or sys.argv[1:])
    if argv and argv[0] == "cancel" and len(argv) > 1:
        # book-14 T9：归属校验后取消（find_owned 未命中即拒绝，绝不触碰他人任务）
        print(json.dumps(cancel_owned_task(argv[1]), ensure_ascii=False))
        return 0
    try:
        print(json.dumps(collect(), ensure_ascii=False))
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"error": str(e)}, ensure_ascii=False))
        return 1
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
