"""
h3.comfy
========
ComfyUI API 客户端模块：网络层职责集中于此。

特性：
  * 请求级重试：指数退避 + 随机抖动，避免隧道刚恢复时瞬间多路重连
  * HTTP 4xx（确定性拒绝）不重试，抛 ComfyRejected
  * 连接级错误抛 ComfyUnreachable（调用方按“可恢复/保留断点”处理）
  * wait_for 采用自适应轮询间隔（5s -> 30s），降低长时间生成期的请求压力
  * 支持通过 COMFYUI_URL 环境变量 / --comfyui-url 覆盖默认地址
    （由 PowerShell 层在自动更换隧道端口时注入）
"""
from __future__ import annotations

import json
import os
import random
import socket
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional, Tuple

DEFAULT_COMFYUI_URL = os.environ.get("COMFYUI_URL", "http://127.0.0.1:8188").rstrip("/")


# ---------------------------------------------------------------------------
# multipart/form-data 组装（供 /upload/image 使用；纯函数便于单测）
# ---------------------------------------------------------------------------
def _multipart_boundary() -> str:
    return "----H3Boundary" + "".join(random.choice("0123456789abcdef") for _ in range(24))


def build_image_upload_body(
    filename: str,
    content: bytes,
    *,
    subfolder: str = "",
    overwrite: str = "false",
    image_type: str = "input",
    boundary: Optional[str] = None,
) -> Tuple[bytes, str]:
    boundary = boundary or _multipart_boundary()
    if not filename:
        raise ValueError("上传文件名不能为空")
    parts: List[bytes] = []
    parts.append(f"--{boundary}\r\n".encode("utf-8"))
    parts.append(
        (
            f'Content-Disposition: form-data; name="image"; filename="{filename}"\r\n'
            f"Content-Type: application/octet-stream\r\n\r\n"
        ).encode("utf-8")
    )
    parts.append(content)
    parts.append(b"\r\n")
    if subfolder:
        parts.append(f"--{boundary}\r\n".encode("utf-8"))
        parts.append(f'Content-Disposition: form-data; name="subfolder"\r\n\r\n{subfolder}\r\n'.encode("utf-8"))
    parts.append(f"--{boundary}\r\n".encode("utf-8"))
    parts.append(f'Content-Disposition: form-data; name="overwrite"\r\n\r\n{overwrite}\r\n'.encode("utf-8"))
    parts.append(f"--{boundary}\r\n".encode("utf-8"))
    parts.append(f'Content-Disposition: form-data; name="type"\r\n\r\n{image_type}\r\n'.encode("utf-8"))
    parts.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(parts), boundary


class ComfyError(Exception):
    """ComfyUI 交互的基类错误。"""


class ComfyUnreachable(ComfyError):
    """网络/隧道不可达（可恢复：保留断点后重试）。"""


class ComfyRejected(ComfyError):
    """服务端确定性拒绝（HTTP 4xx/5xx 等），重试无意义。"""

    def __init__(self, message: str, status: Optional[int] = None, body: str = ""):
        super().__init__(message)
        self.status = status
        self.body = body


class WaitTimeout(ComfyError):
    """轮询超时（任务可能仍在远程执行，可用 --resume 继续）。"""


def _urlopen(req: urllib.request.Request, timeout: int):
    """独立包装以便单元测试打桩替换。"""
    return urllib.request.urlopen(req, timeout=timeout)


class ComfyClient:
    def __init__(
        self,
        base_url: Optional[str] = None,
        *,
        retries: int = 3,
        base_delay: float = 5.0,
        request_timeout: int = 30,
        jitter: float = 0.3,
    ):
        self.base_url = (base_url or DEFAULT_COMFYUI_URL).rstrip("/")
        self.retries = max(1, int(retries))
        self.base_delay = max(0.0, float(base_delay))
        self.request_timeout = max(1, int(request_timeout))
        self.jitter = float(jitter)

    # ------------------------------------------------------------------ 请求
    def request(
        self,
        method: str,
        path: str,
        payload: Optional[dict] = None,
        *,
        retries: Optional[int] = None,
    ) -> dict:
        """发请求；连接级错误指数退避重试，HTTP 4xx/5xx 直接抛出。"""
        attempts = retries if retries is not None else self.retries
        url = f"{self.base_url}{path}"
        last_err: Optional[Exception] = None

        for attempt in range(1, attempts + 1):
            try:
                if payload is not None:
                    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                    req = urllib.request.Request(
                        url,
                        data=data,
                        headers={"Content-Type": "application/json"},
                        method=method,
                    )
                else:
                    req = urllib.request.Request(url, method=method)
                with _urlopen(req, self.request_timeout) as resp:
                    raw = resp.read().decode("utf-8")
                    if not raw.strip():
                        return {}
                    return json.loads(raw)
            except urllib.error.HTTPError as e:
                body = ""
                try:
                    body = e.read().decode("utf-8", errors="replace")
                except Exception:  # noqa: BLE001
                    pass
                raise ComfyRejected(
                    f"ComfyUI 返回 HTTP {e.code} @ {path}", status=e.code, body=body
                ) from e
            except (urllib.error.URLError, ConnectionError, socket.timeout, OSError) as e:
                last_err = e
                if attempt < attempts:
                    # 指数退避 + 抖动：delay * 2^(attempt-1) * (0.7..1.3)
                    backoff = self.base_delay * (2 ** (attempt - 1)) * (
                        1.0 + self.jitter * (random.random() * 2 - 1)
                    )
                    print(
                        f"  [警告] 请求失败: {path} ({e})，{backoff:.1f}s 后重试 "
                        f"({attempt}/{attempts})...",
                        file=__import__("sys").stderr,
                        flush=True,
                    )
                    time.sleep(max(0.1, backoff))

        raise ComfyUnreachable(
            f"ComfyUI 连接失败，已重试 {attempts} 次: {path} (最后错误: {last_err})"
        )

    def ping(self) -> bool:
        """连通性探活：GET /system_stats。"""
        try:
            self.request("GET", "/system_stats", retries=1)
            return True
        except ComfyError:
            return False

    def upload_image(
        self,
        path: Path,
        *,
        subfolder: str = "",
        retries: Optional[int] = None,
    ) -> str:
        """
        上传本地图片到 ComfyUI（/upload/image），返回服务端文件名。

        该文件名用于替换模板里的输入图占位符（LoadImage 节点等）。
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"输入图片不存在: {path}")
        content = path.read_bytes()
        body, boundary = build_image_upload_body(
            path.name, content, subfolder=subfolder, overwrite="true"
        )
        attempts = retries if retries is not None else self.retries
        last_err: Optional[Exception] = None
        for attempt in range(1, attempts + 1):
            try:
                req = urllib.request.Request(
                    f"{self.base_url}/upload/image",
                    data=body,
                    headers={
                        "Content-Type": f"multipart/form-data; boundary={boundary}",
                    },
                    method="POST",
                )
                with _urlopen(req, self.request_timeout) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                name = data.get("name") if isinstance(data, dict) else None
                if not name:
                    raise ComfyRejected(
                        "ComfyUI 未返回上传后的文件名",
                        body=json.dumps(data, ensure_ascii=False),
                    )
                return str(name)
            except urllib.error.HTTPError as e:
                body_text = ""
                try:
                    body_text = e.read().decode("utf-8", errors="replace")
                except Exception:  # noqa: BLE001
                    pass
                raise ComfyRejected(
                    f"图片上传被拒绝 (HTTP {e.code})", status=e.code, body=body_text
                ) from e
            except (urllib.error.URLError, ConnectionError, socket.timeout, OSError) as e:
                last_err = e
                if attempt < attempts:
                    backoff = self.base_delay * (2 ** (attempt - 1)) * (
                        1.0 + self.jitter * (random.random() * 2 - 1)
                    )
                    print(
                        f"  [警告] 图片上传失败 ({e})，{backoff:.1f}s 后重试 "
                        f"({attempt}/{attempts})...",
                        file=__import__("sys").stderr,
                        flush=True,
                    )
                    time.sleep(max(0.1, backoff))
        raise ComfyUnreachable(
            f"图片上传失败，已重试 {attempts} 次: {path} (最后错误: {last_err})"
        )

    def submit(self, workflow: dict) -> str:
        """提交工作流，返回 prompt_id；拒绝/不可达抛对应异常。"""
        result = self.request("POST", "/prompt", {"prompt": workflow})
        pid = result.get("prompt_id") if isinstance(result, dict) else None
        if not pid:
            raise ComfyRejected(
                "ComfyUI 未返回 prompt_id（任务被拒绝）",
                body=json.dumps(result, ensure_ascii=False),
            )
        return str(pid)

    def history(self, prompt_id: str) -> dict:
        """读取单任务历史；未知 id 返回 {}（ComfyUI 行为）。"""
        return self.request("GET", f"/history/{prompt_id}")

    def queue(self) -> Tuple[int, int]:
        """返回 (running, pending)。"""
        q = self.request("GET", "/queue")
        running = len(q.get("queue_running", []) or [])
        pending = len(q.get("queue_pending", []) or [])
        return running, pending

    # ------------------------------------------------------------ 轮询等待
    def wait_for(
        self,
        prompt_id: str,
        timeout: int = 3600,
        *,
        poll_min: float = 5.0,
        poll_max: float = 30.0,
    ) -> Tuple[str, Optional[dict]]:
        """
        轮询直至任务完成/失败/超时。

        返回 (kind, entry)：
          kind == "completed"  -> entry 含 outputs
          kind == "error"      -> entry（ComfyUI 报告执行失败）
          kind == "timeout"    -> entry 为 None（可 --resume 续等）
        连接中断会向上抛 ComfyUnreachable（由调用方保留断点）。
        """
        start = time.time()
        deadline = start + max(1, int(timeout))
        interval = float(poll_min)
        cycle = 0

        while time.time() < deadline:
            entry = self.history(prompt_id).get(prompt_id)
            if entry is not None:
                status = entry.get("status", {}) or {}
                if status.get("status_str") == "error":
                    print(
                        f"ERROR: {json.dumps(status, ensure_ascii=False, indent=2)}",
                        file=__import__("sys").stderr,
                        flush=True,
                    )
                    return "error", entry
                if status.get("completed") or entry.get("outputs"):
                    return "completed", entry

            # 每轮都取一次队列用于进度展示；间隔自适应增长以降低请求压力
            cycle += 1
            if cycle % 3 == 1:
                try:
                    running, pending = self.queue()
                    elapsed = int(time.time() - start)
                    print(
                        f"  [{elapsed}s] running={running}, pending={pending}",
                        flush=True,
                    )
                except ComfyUnreachable:
                    pass  # 进度展示失败不致命，下一轮 history 会重试
            time.sleep(interval)
            interval = min(poll_max, interval * 1.35)

        print(
            f"TIMEOUT after {timeout}s (prompt_id={prompt_id})，任务可能仍在远程执行。",
            file=__import__("sys").stderr,
            flush=True,
        )
        return "timeout", None


# ---------------------------------------------------------------------------
# 输出解析（与具体任务解耦：可传入不同 node_id 用于不同工作流）
# ---------------------------------------------------------------------------
_OUTPUT_FILE_KEYS = ("images", "gifs", "video", "files", "audio")


def extract_output_files(node_outputs: object) -> List[Dict[str, str]]:
    """
    从 history 里某个节点的 outputs 中提取全部文件项。

    兼容不同版本 SaveVideo 节点把产物放在 images/gifs/... 不同键下的情况，
    输出 [{filename, subfolder, type, format}, ...]。
    """
    files: List[Dict[str, str]] = []
    if not isinstance(node_outputs, dict):
        return files

    def _collect(seq: object) -> None:
        if not isinstance(seq, list):
            return
        for item in seq:
            if not isinstance(item, dict):
                continue
            filename = str(item.get("filename") or "").strip()
            if not filename:
                continue
            files.append(
                {
                    "filename": filename,
                    "subfolder": str(item.get("subfolder") or "").strip(),
                    "type": str(item.get("type") or ""),
                    "format": str(item.get("format") or ""),
                }
            )

    for key in _OUTPUT_FILE_KEYS:
        _collect(node_outputs.get(key))
    # 兜底：遍历节点输出下所有“列表”键
    if not files:
        for value in node_outputs.values():
            _collect(value)
    return files


def build_remote_path(remote_output_dir: str, file_info: Dict[str, str]) -> str:
    """把文件信息拼成远端 scp 可用路径（~ 由远端 shell 展开）。"""
    base = (remote_output_dir or "~/ai/ComfyUI/output").rstrip("/")
    sub = (file_info.get("subfolder") or "").strip("/")
    filename = file_info["filename"]
    return f"{base}/{sub}/{filename}" if sub else f"{base}/{filename}"
