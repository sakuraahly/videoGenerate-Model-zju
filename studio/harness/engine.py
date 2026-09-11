#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""studio.harness.engine - 外部视频生成引擎适配层（P2：真出片）。

空间内**不含任何算力**：本模块只做三件事 ——
  ① 把导演产出的生产指令翻译成引擎请求体（请求体由 Director 生成，这里原样透传）；
  ② 提交 → 轮询 → 取回成片的状态机（超时/失败/取消都如实上报，不编进度）；
  ③ 结果回传与验收记录（写进交付说明与 trace，供看板展示）。

复用 studio/agent_client.py 的既有加固，不另起一套：
  · ENGINE_* / VIDEO_API_* / REMOTE_API 三套命名解析（同一套口径）
  · SSRF：拒绝云元数据与链路本地地址（_is_metadata_url）
  · 任务号白名单（_safe_job_id，防路径穿越）；文件名清洗 + 随机名（_safe_filename）
  · 成片取回（download，带大小上限与旧文件清理）

红线：地址与密钥全部来自**访客**在页面上填的配置；本模块不读本机、不指向任何固定主机。
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

_STUDIO = Path(__file__).resolve().parent.parent
if str(_STUDIO.parent) not in sys.path:
    sys.path.insert(0, str(_STUDIO.parent))

from studio.agent_client import AgentClient        # noqa: E402

STATUS_DONE = ('completed', 'succeeded', 'success', 'done', 'finished')
STATUS_FAIL = ('failed', 'error', 'canceled', 'cancelled')
STATUS_RUN = ('running', 'queued', 'pending', 'processing', 'in_progress')

DEFAULT_POLL = 6.0        # 轮询间隔秒（免费 CPU 档别太密）
DEFAULT_TIMEOUT = 1800    # 单段超时秒（30 分钟；真出片常见 1-5 分钟/段）


class EngineError(RuntimeError):
    """引擎层错误（配置缺失 / 地址不可达 / 契约不符）。"""


def _first(d: dict, *names) -> str:
    """按顺序取第一个非空值（同一份配置的三套历史命名都认）。"""
    for n in names:
        v = str(d.get(n) or '').strip()
        if v:
            return v
    return ''


def _host_of(url: str) -> str:
    """只回主机名（页面展示用）—— 绝不把 query 或凭据带进看板与日志。"""
    try:
        p = urllib.parse.urlparse(str(url or ""))
        return p.hostname or ""
    except ValueError:
        return ""


class Engine:
    """一个视频生成引擎（访客自带）。

    用法：
        eng = Engine(base_url="https://host/v1/jobs", status_url="https://host/v1/jobs",
                     api_key="...")
        if eng.available():
            r = eng.run(directive)          # 提交 + 轮询 + 取回
    """

    def __init__(self, base_url: str = "", status_url: str = "", api_key: str = "",
                 *, poll: float = DEFAULT_POLL, timeout: int = DEFAULT_TIMEOUT,
                 download_dir=None, client=None):
        self.base_url = AgentClient._url(base_url)
        self.status_url = AgentClient._url(status_url)
        self.api_key = str(api_key or "")
        self.poll = max(0.5, float(poll or DEFAULT_POLL))
        self.timeout = max(30, int(timeout or DEFAULT_TIMEOUT))
        self.download_dir = download_dir
        self.client = client
        self.calls = []          # 本会话调用记录（供 trace 与看板）

    @classmethod
    def from_overrides(cls, overrides=None, **kw):
        """从**页面表单**取值（BYOK）。命名口径与 AgentClient 一致（三套历史名字都认）。

        默认 **不读环境变量**：定案是"空间自身零凭据、由访客自填"，
        所以这里只取传入的值，绝不因为部署环境里恰好有 ENGINE_* 就悄悄用上。
        自部署想用环境变量兜底时，显式调 from_env()，或传 allow_env=True。
        """
        ov = {str(k).upper(): v for k, v in dict(overrides or {}).items()}
        if kw.pop('allow_env', False):
            cli = AgentClient(ov)                # 允许环境变量兜底（自部署场景）
            return cls(cli.engine_url, cli.engine_status, cli.engine_key, client=cli, **kw)
        return cls(AgentClient._url(_first(ov, 'ENGINE_BASE_URL', 'VIDEO_API_URL', 'REMOTE_API')),
                   AgentClient._url(_first(ov, 'ENGINE_STATUS_URL', 'VIDEO_API_STATUS_URL')),
                   _first(ov, 'ENGINE_API_KEY', 'VIDEO_API_KEY', 'STUDIO_TOKEN'), **kw)

    @classmethod
    def from_env(cls, env=None, **kw):
        """从环境变量取值（**自部署**时才用；空间默认不走这条路）。"""
        import os as _os
        env = _os.environ if env is None else env
        return cls(env.get('ENGINE_BASE_URL', ''), env.get('ENGINE_STATUS_URL', ''),
                   env.get('ENGINE_API_KEY', ''), **kw)

    def available(self) -> bool:
        """有**提交地址**就算可用。

        只配提交地址 = 同步直返型引擎（POST 直接回 video_url，见 接口说明.md 协议 B）；
        两样都配 = 异步作业型（推荐，长任务必须有地方查进度）。
        """
        return bool(self.base_url)

    def describe(self) -> str:
        if not self.base_url:
            return "未配置引擎 → 仅生产计划（交付可执行生产包）"
        if not self.status_url:
            return "只配了提交地址（%s），缺状态查询地址 → 无法轮询成片" % _host_of(self.base_url)
        return "引擎已配置：%s" % _host_of(self.base_url)

    # ---------- 单次 HTTP ----------
    def _post(self, url, payload, timeout=180) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = "Bearer " + self.api_key
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                     headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as r:      # noqa: S310
            return json.loads(r.read().decode("utf-8", "replace") or "{}")

    def _get(self, url, timeout=60) -> dict:
        headers = {"Authorization": "Bearer " + self.api_key} if self.api_key else {}
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as r:      # noqa: S310
            return json.loads(r.read().decode("utf-8", "replace") or "{}")

    @staticmethod
    def _fail(detail, **kw) -> dict:
        out = {"ok": False, "error": detail}
        out.update(kw)
        return out

    # ---------- 提交 ----------
    def submit(self, request: dict) -> dict:
        """提交一段生产指令的请求体 → 成功给 job_id，失败给原因（绝不抛异常）。"""
        if not self.base_url:
            return self._fail("没有配置引擎提交地址（ENGINE_BASE_URL）")
        try:
            d = self._post(self.base_url, request)
        except urllib.error.HTTPError as e:
            body = e.read(300).decode("utf-8", "replace") if hasattr(e, "read") else ""
            return self._fail("HTTP %s：%s" % (e.code, body[:200]), status_code=e.code)
        except (urllib.error.URLError, OSError, ValueError) as e:
            return self._fail("%s: %s" % (type(e).__name__, str(e)[:200]))
        job_id = AgentClient._safe_job_id(d.get("job_id") or d.get("task_id") or d.get("id"))
        video = str(d.get("video_url") or d.get("video") or d.get("url") or "")
        if not job_id and video:            # 同步直返型引擎：一次调用就给成片
            return {"ok": True, "job_id": "", "video_url": video, "sync": True, "raw": d}
        if not job_id:
            return self._fail("引擎没有返回合法 job_id：%s"
                              % json.dumps(d, ensure_ascii=False)[:200], raw=d)
        return {"ok": True, "job_id": job_id, "video_url": video, "sync": False, "raw": d}

    # ---------- 轮询 ----------
    def query(self, job_id: str) -> dict:
        jid = AgentClient._safe_job_id(job_id)
        if not jid:
            return self._fail("任务号不合法（只允许字母数字与 . _ : -，长度不超过 64）")
        if not self.status_url:
            return self._fail("没有配置状态查询地址（ENGINE_STATUS_URL），无法得知进度")  # 同步直返型不需要轮询
        try:
            d = self._get(self.status_url.rstrip("/") + "/" + jid)
        except urllib.error.HTTPError as e:
            return self._fail("HTTP %s" % e.code, status_code=e.code)
        except (urllib.error.URLError, OSError, ValueError) as e:
            return self._fail("%s: %s" % (type(e).__name__, str(e)[:160]))
        status = str(d.get("status") or d.get("state") or "").strip().lower()
        video = str(d.get("video_url") or d.get("video") or d.get("url") or d.get("output") or "")
        err = str(d.get("error") or d.get("message") or "")
        return {"ok": True, "status": status, "video_url": video, "error": err, "raw": d}

    # ---------- 提交 → 轮询 → 取回 ----------
    def run(self, directive: dict, *, on_event=None, fetch: bool = True) -> dict:
        """跑完一段：提交 → 轮询 → 取回成片。返回结构化结果，绝不抛异常。"""
        t0 = time.time()
        request = dict(directive.get("request") or {})
        rec = {"idx": directive.get("idx"), "kind": request.get("kind"), "ok": False,
               "job_id": "", "status": "", "video_url": "", "file": "", "error": "",
               "elapsed": 0.0}
        sub = self.submit(request)
        if not sub.get("ok"):
            rec["error"] = sub.get("error", "提交失败")
            rec["elapsed"] = round(time.time() - t0, 1)
            self.calls.append(rec)
            if on_event:
                on_event("submit", rec)
            return rec
        rec["job_id"] = sub.get("job_id") or ""
        rec["video_url"] = sub.get("video_url") or ""
        if on_event:
            on_event("submit", rec)

        if sub.get("sync"):
            rec["ok"] = bool(rec["video_url"])
            rec["status"] = "completed"
            if not rec["ok"]:
                rec["error"] = "引擎同步返回里没有成片地址"
        elif not self.status_url:
            rec["error"] = ("只配了提交地址，缺状态查询地址（ENGINE_STATUS_URL）→ 无法轮询成片；"
                            "若你的引擎是同步直返，请让 POST 直接返回 video_url")
        else:
            deadline = time.time() + self.timeout
            while True:
                q = self.query(rec["job_id"])
                if not q.get("ok"):
                    rec["error"] = q.get("error", "查询失败")
                    break
                rec["status"] = q.get("status") or ""
                if q.get("video_url"):
                    rec["video_url"] = q["video_url"]
                if rec["status"] in STATUS_DONE:
                    rec["ok"] = True
                    break
                if rec["status"] in STATUS_FAIL:
                    rec["error"] = q.get("error") or ("引擎状态：%s" % rec["status"])
                    break
                if rec["video_url"] and not rec["status"]:
                    rec["ok"] = True
                    break
                if time.time() > deadline:
                    rec["error"] = "超时 %ds（最后状态：%s）" % (self.timeout, rec["status"] or "未知")
                    break
                if on_event:
                    on_event("poll", rec)
                time.sleep(self.poll)
            if rec["ok"] and not rec["video_url"]:
                rec["ok"] = False
                rec["error"] = "引擎报完成但没有给成片地址"

        if rec["ok"] and fetch and rec["video_url"]:
            rec["file"] = self.fetch(rec["video_url"])
        rec["elapsed"] = round(time.time() - t0, 1)
        self.calls.append(rec)
        if on_event:
            on_event("done", rec)
        return rec

    def fetch(self, url: str) -> str:
        """取回成片到本地（复用 agent_client 的 SSRF 与文件名、大小上限加固）。失败返回空串。"""
        if not url or not str(url).startswith(("http://", "https://")):
            return ""
        if AgentClient._is_metadata_url(url):
            return ""
        try:
            return AgentClient.download(url, dest_dir=self.download_dir) or ""
        except Exception:                                  # noqa: BLE001
            return ""

    # ---------- 探测 ----------
    def probe(self, timeout: int = 8) -> dict:
        """连通性探测：只发一个明显不完整的请求（引擎答 400 也算通），绝不真的开生成任务。"""
        if not self.base_url:
            return {"configured": False, "reachable": False, "detail": "未配置引擎（正常档）"}
        try:
            d = self._post(self.base_url, {"kind": "__harness_probe__"}, timeout=timeout)
            return {"configured": True, "reachable": True,
                    "detail": "引擎应答正常：%s" % json.dumps(d, ensure_ascii=False)[:120]}
        except urllib.error.HTTPError as e:
            body = e.read(200).decode("utf-8", "replace") if hasattr(e, "read") else ""
            reachable = e.code not in (404, 502, 503, 504)
            hint = {400: "（400 = 地址对了，只是探测请求不完整）",
                    401: "（401 = 需要 API Key）",
                    403: "（403 = Key 无权访问）",
                    404: "（404 = 提交地址路径不对）"}.get(e.code, "")
            return {"configured": True, "reachable": reachable, "status": e.code,
                    "detail": "HTTP %s%s：%s" % (e.code, hint, body[:120])}
        except (urllib.error.URLError, OSError, ValueError) as e:
            return {"configured": True, "reachable": False,
                    "detail": "%s: %s" % (type(e).__name__, str(e)[:120])}

    # ---------- 看板摘要（JSON 安全，绝不带密钥） ----------
    def summary(self, batch: dict = None) -> dict:
        out = {"configured": bool(self.base_url), "host": _host_of(self.base_url),
               "status_host": _host_of(self.status_url), "available": self.available(),
               "poll": self.poll, "timeout": self.timeout, "describe": self.describe()}
        if batch:
            out["done"] = batch.get("done")
            out["failed"] = batch.get("failed")
            out["summary"] = batch.get("summary")
            out["rows"] = [{k: r.get(k) for k in ("idx", "kind", "ok", "job_id", "status",
                                                  "video_url", "file", "error", "elapsed")}
                            for r in (batch.get("rows") or [])]
        return out


__all__ = ["Engine", "EngineError", "STATUS_DONE", "STATUS_FAIL", "STATUS_RUN"]

