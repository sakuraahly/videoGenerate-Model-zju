"""
h3.jobstate
===========
任务状态领域模块：断点状态（项目根 last_job.json）与每任务审计记录
（workflows/<task>/job.json）的读写。

两个文件的职责分离：
  * last_job.json        —— 瞬态“恢复指针”，成功下载后由外层脚本清除
  * workflows/<task>/job.json —— 每次提交的审计记录（长期保留，
    便于复盘/将来新增“历史列表”“按 id 重下”等功能）

状态 JSON 采用原子写入（临时文件 + rename），进程中途被杀也不会留下半截文件。
"""
from __future__ import annotations

import datetime
import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

ROOT_STATE_FILE = "last_job.json"  # 兼容旧版纯文本 last_prompt_id.txt 的读取

ISO = "%Y-%m-%dT%H:%M:%S"


def atomic_write_json(path: Path, obj: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    tmp.replace(path)


def read_json(path: Path) -> Optional[dict]:
    """读取 JSON；不存在/损坏返回 None（绝不抛出）。"""
    path = Path(path)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


# ---------------------------------------------------------------------------
# 根级断点状态 last_job.json
# ---------------------------------------------------------------------------
def root_state_path(project_dir: Path) -> Path:
    return Path(project_dir) / ROOT_STATE_FILE


def load_root_state(project_dir: Path) -> Dict[str, Any]:
    """
    读取断点状态。向后兼容旧版纯文本（内容为一行 prompt_id）。

    返回统一结构：
      {"schema": 1, "prompt_id": str|"", "remote_path": str|"", ...}
    """
    path = root_state_path(project_dir)
    empty = {"schema": 1, "prompt_id": "", "remote_path": "", "created_at": "", "updated_at": ""}
    data = read_json(path)
    if data is not None:
        out = dict(empty)
        out.update({k: data[k] for k in ("prompt_id", "remote_path", "created_at", "updated_at") if k in data})
        out["prompt_id"] = str(out["prompt_id"] or "").strip()
        out["remote_path"] = str(out["remote_path"] or "").strip()
        return out

    # 兼容旧版纯文本断点文件
    legacy = Path(project_dir) / "last_prompt_id.txt"
    if legacy.exists():
        try:
            pid = legacy.read_text(encoding="utf-8-sig").strip()
            if pid:
                out = dict(empty)
                out["prompt_id"] = pid
                out["created_at"] = datetime.datetime.now().strftime(ISO)
                out["updated_at"] = out["created_at"]
                return out
        except OSError:
            pass
    return empty


def save_root_state(project_dir: Path, *, prompt_id: str = "", remote_path: str = "") -> Path:
    """写入/更新根级断点状态；prompt_id 为空等同于清空 remote 信息。"""
    path = root_state_path(project_dir)
    now = datetime.datetime.now().strftime(ISO)
    data = load_root_state(project_dir)
    data["schema"] = 1
    data["prompt_id"] = str(prompt_id or "").strip()
    data["remote_path"] = str(remote_path or "").strip()
    data["updated_at"] = now
    if not data.get("created_at"):
        data["created_at"] = now
    atomic_write_json(path, data)
    # 迁移：写入新格式后清理旧版纯文本断点文件，保持单一事实源
    legacy = Path(project_dir) / "last_prompt_id.txt"
    if legacy.exists():
        try:
            legacy.unlink()
        except OSError:
            pass
    return path


def clear_root_state(project_dir: Path) -> bool:
    """成功下载后清除断点；旧版纯文本文件一并删除。"""
    removed = False
    path = root_state_path(project_dir)
    if path.exists():
        try:
            path.unlink()
            removed = True
        except OSError:
            pass
    legacy = Path(project_dir) / "last_prompt_id.txt"
    if legacy.exists():
        try:
            legacy.unlink()
        except OSError:
            pass
    return removed


# ---------------------------------------------------------------------------
# 每任务审计记录 workflows/<task>/job.json
# ---------------------------------------------------------------------------
def task_job_path(project_dir: Path, task_folder: Path) -> Path:
    return Path(project_dir) / "workflows" / task_folder.name / "job.json"


def record_task_start(project_dir: Path, task_folder: Path, meta: Dict[str, Any]) -> Path:
    """提交前记录任务开始（含参数快照）。返回 job.json 路径。"""
    now = datetime.datetime.now().strftime(ISO)
    job = {
        "schema": 1,
        "task_dir": task_folder.name,
        "created_at": now,
        "updated_at": now,
        "state": "submitted",
        **meta,
    }
    path = task_job_path(project_dir, task_folder)
    atomic_write_json(path, job)
    return path


def update_task_record(project_dir: Path, task_folder: Path, patch: Dict[str, Any]) -> Optional[Path]:
    """更新任务审计记录（幂等）；记录不存在时静默跳过。"""
    path = task_job_path(project_dir, task_folder)
    job = read_json(path)
    if job is None:
        return None
    job.update(patch)
    job["updated_at"] = datetime.datetime.now().strftime(ISO)
    atomic_write_json(path, job)
    return path
