#!/usr/bin/env python3
"""本地假引擎：验证 studio 的「视频生成模型接口」契约（POST /v1/jobs + GET /v1/jobs/{id}）。

用法：py -3 tests/mock_engine.py --port 7999 --video studio/assets/01_direct_720p.mp4
契约（与 studio/接口说明.md 一致）：
  POST /v1/jobs            -> {"job_id": "..."}（异步）或 {"video_url": "..."}（同步）
  GET  /v1/jobs/<job_id>   -> {"status": "running|done|failed", "video_url": "..."}
"""
from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

STATE = {"posts": [], "gets": 0, "video": b"", "sync": False}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):  # 安静
        pass

    def _send(self, obj, code=200, raw=None, ctype="application/json"):
        body = raw if raw is not None else json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        payload = json.loads(self.rfile.read(n) or b"{}")
        if self.path.startswith("/v1/llm/chat/completions"):
            # 假大脑：记录收到的 system 提示与消息，然后返回一个规范的 {tool,args,say} JSON
            STATE.setdefault("llm", []).append(
                {"auth": self.headers.get("Authorization"), "model": payload.get("model"),
                 "system": (payload.get("messages") or [{}])[0].get("content", "")[:400],
                 "user": (payload.get("messages") or [{}])[-1].get("content", "")})
            plan = json.loads(STATE.get("llm_plan") or
                              '{"tool":"generate_talk","args":{"text":"你好，我是外置大脑选的台词。",'
                              '"voice":"native"},"say":"大脑决定：用说话镜头工具。"}')
            self._send({"choices": [{"message": {"role": "assistant",
                                                 "content": json.dumps(plan, ensure_ascii=False)}}]})
            return
        STATE["posts"].append({"path": self.path, "payload": payload,
                               "auth": self.headers.get("Authorization")})
        if STATE["sync"]:
            self._send({"video_url": "http://127.0.0.1:%d/video.mp4" % self.server.server_port})
        else:
            self._send({"job_id": "mock-1"})

    def do_GET(self):
        if self.path.startswith("/v1/llm/stats"):
            self._send(STATE.get("llm", []))
        elif self.path.startswith("/v1/jobs/mock-1"):
            STATE["gets"] += 1
            self._send({"status": "done" if STATE["gets"] >= 1 else "running",
                        "video_url": "http://127.0.0.1:%d/video.mp4" % self.server.server_port})
        elif self.path.startswith("/stats"):
            self._send(STATE["posts"])
        elif self.path.startswith("/video.mp4"):
            self._send(None, raw=STATE["video"], ctype="video/mp4")
        else:
            self._send({"error": "not found"}, code=404)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=7999)
    ap.add_argument("--video", default="")
    ap.add_argument("--sync", action="store_true", help="模拟同步直返 video_url")
    a = ap.parse_args()
    STATE["sync"] = a.sync
    if a.video and Path(a.video).is_file():
        STATE["video"] = Path(a.video).read_bytes()
    ThreadingHTTPServer(("127.0.0.1", a.port), H).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
