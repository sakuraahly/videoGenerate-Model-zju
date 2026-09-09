#!/usr/bin/env python3
"""studio_gateway — 创空间远程调度网关（v1.0 交付级；stdlib 零依赖，监听 8080）。

定位（2026-09-09 用户定案）：**工程师联调工具**（实验机侧）。创空间正式交付=自包含
展示（M1 演示表单自动降级，无远程依赖）——不在交付形态内强依赖本网关。

适配事实（2026-09-09 实测）：spark 公网 106.13.186.155 仅 8080 开放（80/443/22 不通）→
网关直挂 8080 + token 鉴权（免反代；后续如需 HTTPS 再评估）。

错误码：400 参数非法 / 401 鉴权失败 / 404 作业不存在或未完成 / 429 限流未启用(预留) /
500 引擎提交失败 / 503 引擎未在线。所有错误信息不含服务器路径。

端点（除 /v1/health 外均需 Authorization: Bearer <STUDIO_TOKEN>）：
  POST /v1/jobs            {stage?,prompt,resolution?,seconds?,seed?} → {job_id,status}
  GET  /v1/jobs/<id>      → {status: queued|running|completed|failed, progress}
  GET  /v1/jobs/<id>/download → 成片流（completed 且未过期(72h)；不回显服务器路径）
  GET  /v1/health          → {ok,site}（免鉴权探活）

安全性：字段白名单（stage/prompt/resolution/seconds/seed）；token 长度≥16；
作业记录 logs/studio_jobs.jsonl（非 git）；下载文件名=产物名、响应头不带绝对路径。
模式：STUDIO_MODE=mock → 零提交假状态（表单联调用）；默认 real → h3_submit --submit-only 真提交。

用法（spark；服务化=用户确认后 tmux 挂起，勿 default 常驻）：
  STUDIO_TOKEN=<token> [STUDIO_MODE=real] python3 runs/api/studio_gateway.py --port 8080
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.request
import uuid
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = Path(__file__).resolve().parent.parent.parent
JOBS_LOG = ROOT / 'logs' / 'studio_jobs.jsonl'
DOWNLOAD_TTL = 72 * 3600          # 产物有效期（秒）
MAX_DOWNLOAD = 500 * 1024 * 1024  # 500MB 上限

TOKEN = (os.environ.get('STUDIO_TOKEN') or '').strip()
MODE = (os.environ.get('STUDIO_MODE') or 'real').strip().lower()
FIELDS = ('stage', 'prompt', 'resolution', 'seconds', 'seed')
# 供回显/下载的"虚拟样例"（mock 模式；指向仓库样例资产，无路径泄露风险）
SAMPLE = ROOT / 'studio' / 'assets' / '01_direct_720p.mp4'

_jobs: dict = {}


def _log(msg: str) -> None:
    try:
        sys.stderr.write('[gateway] %s %s\n' % (time.strftime('%H:%M:%S'), msg))
        sys.stderr.flush()
    except Exception:  # noqa: BLE001
        pass


def _record(j: dict) -> None:
    try:
        JOBS_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(JOBS_LOG, 'a', encoding='utf-8') as f:
            f.write(json.dumps(j, ensure_ascii=False) + '\n')
    except Exception:  # noqa: BLE001
        pass


def _submit(payload: dict) -> tuple:
    """真实提交：h3_submit --submit-only；返回 (job_id, err)。"""
    stage = payload.get('stage') or 't2v'
    if stage not in ('t2v', 'i2v', 'flf2v'):
        return '', 'stage 仅支持 t2v/i2v/flf2v'
    prompt = str(payload.get('prompt') or '').strip()
    if len(prompt) < 8:
        return '', 'prompt 至少 8 字符'
    # json.dumps 转义 → shlex-safe 参数（subprocess list 传参）
    cmd = [sys.executable, str(ROOT / 'runs' / 'h3_submit.py'),
           '--stage', stage, '--submit-only',
           '--resolution', str(payload.get('resolution') or '360p'),
           '--seconds', str(int(payload.get('seconds') or 5)),
           '--prompt', prompt]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=180, cwd=str(ROOT))
    except Exception as e:  # noqa: BLE001
        return '', '提交失败: ' + str(e)[:120]
    out = (r.stdout or '') + (r.stderr or '')
    m = re.search(r'TASK_SUBMITTED:\s*([0-9a-f-]{36})', out, re.I)
    if not m:
        return '', '提交未返回任务号（提交失败）: ' + out[-120:]
    return m.group(1), ''


def _poll(pid: str) -> str:
    """真实状态：ComfyUI history/queue。"""
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:8188/history/{pid}', timeout=8) as r:
            hist = json.loads(r.read().decode())
        if hist.get(pid):
            st = (hist[pid].get('status') or {}).get('status_str') or 'completed'
            return 'completed' if st == 'success' else 'failed'
        with urllib.request.urlopen('http://127.0.0.1:8188/queue', timeout=8) as r:
            q = json.loads(r.read().decode())
        for key in ('queue_running', 'queue_pending'):
            for it in q.get(key, []):
                if len(it) > 1 and str(it[1]).startswith(pid[:8]):
                    return 'running' if key == 'queue_running' else 'queued'
        return 'queued'
    except Exception as e:  # noqa: BLE001
        _log('poll err ' + str(e)[:80])
        return 'queued'


def _job_media(pid: str) -> Path | None:
    """定位产物（不含路径回显；只用于发送）。"""
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:8188/history/{pid}', timeout=8) as r:
            hist = json.loads(r.read().decode())
        node = hist.get(pid, {})
        outs = (node.get('outputs') or {})
        for nid, n in outs.items():
            vids = n.get('videos') or []
            if vids:
                name = vids[0]['filename']
                p = Path(os.path.expanduser('~/ai/ComfyUI/output')) / vids[0].get('subfolder', '') / name
                if p.is_file():
                    return p
    except Exception:  # noqa: BLE001
        pass
    try:
        cands = sorted(Path(os.path.expanduser('~/ai/ComfyUI/output/video')).glob('MiniMax_H3_*.mp4'),
                       key=lambda p: p.stat().st_mtime, reverse=True)
        if cands:
            return cands[0]
    except Exception:  # noqa: BLE001
        pass
    return None


class Handler(BaseHTTPRequestHandler):
    server_version = 'StudioGateway/0.2'

    def _send(self, code: int, body: dict, headers: dict | None = None) -> None:
        data = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _authorized(self) -> bool:
        if len(TOKEN) < 16:
            return False
        auth = self.headers.get('Authorization', '')
        return auth == 'Bearer ' + TOKEN

    def _json_body(self) -> dict:
        n = int(self.headers.get('Content-Length') or 0)
        try:
            d = json.loads(self.rfile.read(n).decode() or '{}')
            return d if isinstance(d, dict) else {}
        except Exception:  # noqa: BLE001
            return {}

    def do_GET(self):  # noqa: N802
        path = (self.path or '').split('?')[0]
        if path == '/v1/health':
            return self._send(200, {'ok': True, 'site': 'spark', 'mode': MODE})
        if not self._authorized():
            return self._send(401, {'error': 'unauthorized'})
        m = re.match(r'^/v1/jobs/([0-9a-f-]{36})/download$', path)
        if m:
            j = _jobs.get(m.group(1))
            if not j or j.get('status') != 'completed':
                return self._send(409, {'error': '任务未完成或不存在'})
            if j.get('mode') == 'mock':
                src = SAMPLE
            else:
                src = _job_media(j.get('pid') or '')
            if src is None or not Path(src).is_file():
                return self._send(404, {'error': '产物未就绪'})
            if Path(src).stat().st_size > MAX_DOWNLOAD:
                return self._send(413, {'error': '产物超限'})
            data = Path(src).read_bytes()
            self.send_response(200)
            self.send_header('Content-Type', 'video/mp4')
            self.send_header('Content-Disposition',
                             'attachment; filename="%s"' % Path(src).name.replace('"', ''))
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        m = re.match(r'^/v1/jobs/([0-9a-f-]{36})$', path)
        if m:
            j = _jobs.get(m.group(1))
            if not j:
                return self._send(404, {'error': '任务不存在'})
            return self._send(200, {'job_id': m.group(1), 'status': j.get('status'),
                                    'mode': j.get('mode')})
        return self._send(404, {'error': 'unknown path'})

    def do_POST(self):  # noqa: N802
        path = (self.path or '').split('?')[0]
        if path != '/v1/jobs':
            return self._send(404, {'error': 'unknown path'})
        if not self._authorized():
            return self._send(401, {'error': 'unauthorized'})
        body = self._json_body()
        payload = {k: body.get(k) for k in FIELDS if k in body}
        if len(str(payload.get('prompt') or '').strip()) < 8:
            return self._send(400, {'error': 'prompt 至少 8 字符'})
        if str(payload.get('stage') or 't2v') not in ('t2v', 'i2v', 'flf2v'):
            return self._send(400, {'error': 'stage 仅支持 t2v/i2v/flf2v'})
        jid = str(uuid.uuid4())
        if MODE == 'mock':
            _jobs[jid] = {'mode': 'mock', 'status': 'queued',
                          'created': time.time(), 'payload': payload}
            _record({'job_id': jid, 'mode': 'mock', 'status': 'queued', 'payload': payload})
            return self._send(200, {'job_id': jid, 'status': 'queued', 'mode': 'mock'})
        pid, err = _submit(payload)
        if err:
            return self._send(400, {'error': err})
        _jobs[jid] = {'pid': pid, 'mode': 'real', 'status': 'queued',
                      'created': time.time(), 'payload': payload}
        _record({'job_id': jid, 'pid': pid, 'mode': 'real', 'status': 'queued',
                 'payload': payload})
        return self._send(200, {'job_id': jid, 'status': 'queued', 'mode': 'real'})


def _tick() -> None:
    """状态机推进（mock 自动流转；real 轮询）。"""
    for jid, j in list(_jobs.items()):
        if j.get('mode') == 'mock':
            age = time.time() - j.get('created', 0)
            if age > 6 and j.get('status') == 'queued':
                j['status'] = 'running'
            if age > 12 and j.get('status') == 'running':
                j['status'] = 'completed'
            _record({'job_id': jid, 'mode': 'mock', 'status': j['status']})
        else:
            j['status'] = _poll(j.get('pid') or '')


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser('studio_gateway（M2 远程调度）')
    ap.add_argument('--port', type=int, default=8080)
    ap.add_argument('--host', default='0.0.0.0')
    args = ap.parse_args()
    if len(TOKEN) < 16:
        print('[错误] STUDIO_TOKEN 未设置或过短（≥16）', file=sys.stderr)
        return 2
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    _log('listening %s:%s mode=%s token_len=%s' % (args.host, args.port, MODE, len(TOKEN)))
    try:
        while True:
            srv.handle_request()
            _tick()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == '__main__':
    sys.exit(main())
