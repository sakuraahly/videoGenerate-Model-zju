"""studio backend — 生成后端抽象层（demo / remote / local 三实现）。

设计（2026-09-10 v2.0）：
  前端（app.py）只调用本层；换后端不改前端。

  2026-09-10 说明：`RemoteBackend`（REMOTE_API + STUDIO_TOKEN，路径 /v1/jobs）是**早期形态**；
  现在 Agent 走的是 `ENGINE_BASE_URL/ENGINE_STATUS_URL/ENGINE_API_KEY` 契约（见 接口说明.md）。
  两者可并存：创作台表单走本层，Agent 对话走契约接口。
  · demo  ：默认（免费 CPU 档）。不产生任务：校验参数 + 返回规格卡与匹配样片。
  · remote：配置 REMOTE_API + STUDIO_TOKEN 后，真实提交到外部引擎网关
            （POST /v1/jobs、GET /v1/jobs/<id>、GET /v1/jobs/<id>/download）。
  · local ：空间内本地模型（需 GPU 硬件档；本版预留接口，未实现即报错说明）。

选后端：环境变量 STUDIO_BACKEND=demo|remote|local（默认 auto：有 REMOTE_API 用 remote，否则 demo）。
"""
from __future__ import annotations

import os
import time
import uuid

DEFAULT_MODEL_SPACE = {
    't2v': ('文生视频', '360p/480p/720p，5-15s，本地大模型推理'),
    'i2v': ('图生视频', '以首帧图为准，动作自然'),
    'talk': ('说话镜头', '一句台词→H3 自适应音色亲口说出（音画同时长）+ ASR 验收'),
    'story': ('剧本故事片', '剧本 JSON→多段连贯+台词字幕（可断点续跑）'),
}


def pick_backend():
    name = (os.environ.get('STUDIO_BACKEND') or 'auto').strip().lower()
    remote_api = (os.environ.get('REMOTE_API') or '').strip()
    token = (os.environ.get('STUDIO_TOKEN') or '').strip()
    if name == 'auto':
        name = 'remote' if (remote_api and token) else 'demo'
    if name == 'remote':
        return RemoteBackend(remote_api, token)
    if name == 'local':
        return LocalBackend()
    return DemoBackend()


class DemoBackend:
    """演示后端：不产生真实任务（免费 CPU 档默认）。"""

    name = 'demo'
    note = ('当前为**演示模式**（免费 CPU 档、无 GPU）：只做参数校验与规格说明，不产生真实生成任务。'
            '要真实出片：把本空间硬件切到 GPU 档（如 A10 24G）并挂轻量视频模型，'
            '或配置 REMOTE_API/STUDIO_TOKEN 指向你的引擎。')

    def submit(self, task: dict) -> dict:
        kind = task.get('kind', 't2v')
        title, spec = DEFAULT_MODEL_SPACE.get(kind, DEFAULT_MODEL_SPACE['t2v'])
        secs = task.get('seconds') or 5
        return {
            'job_id': 'demo-' + uuid.uuid4().hex[:8],
            'state': 'demo',
            'title': title,
            'spec': spec,
            'echo': {
                '类型': title,
                '提示词': (task.get('prompt') or '')[:120] or '（未填写）',
                '参考图': task.get('images') or '（无）',
                '分辨率': task.get('resolution'),
                '时长': '%ss' % secs,
                '音色': task.get('voice') or '—',
                '字幕': '烧录' if task.get('subtitle') else '不烧录',
            },
        }

    def poll(self, job_id: str) -> dict:
        return {'state': 'demo', 'progress': 100, 'video': None, 'files': []}


class RemoteBackend:
    """远程引擎网关后端（POST /v1/jobs 等）。"""

    name = 'remote'

    def __init__(self, api: str, token: str):
        self.api = api.rstrip('/')
        self.token = token

    @staticmethod
    def _safe_id(job_id) -> str:
        """任务号白名单：避免被拼进 URL 造成路径穿越（与 agent_client 同口径）。"""
        import re as _re
        s = str(job_id or '').strip()
        return s if _re.fullmatch(r'[A-Za-z0-9._:-]{1,64}', s) else ''

    def _req(self, method: str, path: str, payload: dict | None = None, raw: bool = False):
        import json as _json
        import urllib.request
        url = self.api + path
        data = _json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(url, data=data, method=method,
                                     headers={'Authorization': 'Bearer ' + self.token,
                                              'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=30) as r:
            body = r.read()
            if raw:
                return body
            return _json.loads(body.decode('utf-8', 'replace') or '{}')

    def submit(self, task: dict) -> dict:
        payload = {'prompt': task.get('prompt') or '',
                   'resolution': task.get('resolution') or '480p',
                   'seconds': int(task.get('seconds') or 5)}
        d = self._req('POST', '/v1/jobs', payload)
        return {'job_id': d.get('job_id'), 'state': d.get('status', 'queued'),
                'title': DEFAULT_MODEL_SPACE.get(task.get('kind', 't2v'), ('任务', ''))[0],
                'spec': '远程引擎（本机 GPU 推理）', 'echo': payload}

    def poll(self, job_id: str) -> dict:
        jid = self._safe_id(job_id)
        if not jid:
            return {'state': 'error', 'progress': 0, 'video': None, 'files': [],
                    'error': '任务号不合法'}
        d = self._req('GET', '/v1/jobs/' + jid)
        st = d.get('status')
        out = {'state': st, 'progress': 100 if st == 'completed' else (d.get('progress') or 10),
               'video': None, 'files': []}
        if st == 'completed':
            out['video'] = self.api + '/v1/jobs/%s/download' % job_id
        return out


class LocalBackend:
    """空间内本地模型后端（需 GPU 硬件档）。预留接口。"""

    name = 'local'

    def submit(self, task: dict) -> dict:
        raise RuntimeError(
            '本地模型后端未启用：本空间当前为免费 CPU 档（2vCPU/16G），无法承载视频模型。'
            '请在空间设置里切换到 GPU 硬件档（如 paid/ecs.gn7i-c8g1.2xlarge，A10 24G）'
            '并部署轻量模型（Wan2.1-1.3B / CogVideoX-2B 等），或改用 REMOTE_API 远程引擎。')

    def poll(self, job_id: str) -> dict:
        return {'state': 'error', 'progress': 0, 'video': None, 'files': []}
