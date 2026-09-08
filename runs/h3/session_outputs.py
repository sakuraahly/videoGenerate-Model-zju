#!/usr/bin/env python3
"""会话产物目录协议（planbook §15d 产物可达性）：logs/agent_chats/<cid>/outputs/。

协议（三处同口径，改动必四方核对——ui_app / lipsync_chain / 本文档单元测试）：
  1) 链/引擎最终产物 → place_output() 复制到「当前会话」产物目录；
     会话 id 来自 env `VIDEOGEN_SESSION_CID`（run_script 由 CURRENT_SESSION 注入）。
  2) UI（runs/agent/ui_app.py 结果区）→ session_videos()/session_files() 读取展示
     （gr.Video 预览最新 + gr.File 全部下载）。
  3) 保留策略：每会话最多 KEEP（默认 10）个文件，更旧的自动修剪删除。

路径口径（spark 与 Windows 主库一致）：<repo>/logs/agent_chats/<cid>/outputs/。
"""
from __future__ import annotations

import os
import shutil
import time as _tm
from pathlib import Path

ENV_CID = 'VIDEOGEN_SESSION_CID'
KEEP = 10
VIDEO_EXTS = ('.mp4', '.webm', '.mov', '.mkv', '.gif')


def current_cid() -> str:
    """链侧读取：run_script 注入的 VIDEOGEN_SESSION_CID（无则空串=不落会话目录）。"""
    return (os.environ.get(ENV_CID, '') or '').strip()


def session_out_dir(repo: Path, cid: str) -> Path | None:
    """会话产物目录；cid 为空返回 None（无会话上下文不落盘）。"""
    cid = str(cid or '').strip()
    if not cid:
        return None
    return Path(repo) / 'logs' / 'agent_chats' / cid / 'outputs'


def _mtime(p: Path) -> float:
    try:
        return p.stat().st_mtime
    except OSError:
        return 0.0


def _list_dir(repo: Path, cid: str, exts: tuple | None) -> list:
    d = session_out_dir(repo, cid)
    if d is None or not d.is_dir():
        return []
    try:
        items = [p for p in d.iterdir() if p.is_file()
                 and (exts is None or p.suffix.lower() in exts)]
    except OSError:
        return []
    items.sort(key=_mtime, reverse=True)
    return items


def session_files(repo: Path, cid: str) -> list:
    """会话全部产物文件，最新在前（供 gr.File 下载列表）。"""
    return _list_dir(repo, cid, None)


def session_videos(repo: Path, cid: str) -> list:
    """会话产物视频，最新在前（供 gr.Video 预览 / 跳过非媒体文件）。"""
    return _list_dir(repo, cid, VIDEO_EXTS)


def prune_dir(d: Path, keep: int = KEEP) -> None:
    """修剪：保留最新 keep 个文件（按 mtime），更旧的删除。"""
    try:
        items = [p for p in d.iterdir() if p.is_file()]
        items.sort(key=_mtime, reverse=True)
        for p in items[keep:]:
            try:
                p.unlink(missing_ok=True)
            except OSError:
                pass
    except OSError:
        pass


def place_output(repo: Path, cid: str, src: Path,
                 name: str | None = None, keep: int = KEEP) -> Path | None:
    """把最终产物复制到会话产物目录（mtime 刷新为当前，修剪旧文件）。

    失败（无会话上下文/IO 异常）返回 None，调用方按警告处理、不得中断主流程。
    """
    d = session_out_dir(repo, cid)
    if d is None:
        return None
    try:
        d.mkdir(parents=True, exist_ok=True)
        dst = d / (name or Path(src).name)
        shutil.copy2(str(src), str(dst))
        os.utime(dst, (_tm.time(), _tm.time()))
        prune_dir(d, keep)
        return dst
    except OSError:
        return None
