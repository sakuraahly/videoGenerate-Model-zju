#!/usr/bin/env python3
"""成品标记单测：UI 回传/下载必须是成品（用户 2026-09-10 要求）。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runs.h3 import session_outputs as so  # noqa: E402


def _place(tmp_path, cid, name, data=b'x', final=False):
    src = tmp_path / name
    src.write_bytes(data)
    return so.place_output(tmp_path, cid, src, final=final)


def test_final_product_is_preferred_over_newer_raw_output(tmp_path):
    cid = 'c1'
    _place(tmp_path, cid, 'raw_1.mp4')                       # 队列直出
    _place(tmp_path, cid, 'story_final.mp4', final=True)     # 成品（打标）
    assert so.latest_final(tmp_path, cid).name == 'story_final.mp4'
    assert so.session_videos(tmp_path, cid)[0].name == 'story_final.mp4'
    # 之后又落了一个更"新"的直出产物 → 成品仍必须排第一（UI 回传的就是它）
    _place(tmp_path, cid, 'raw_2.mp4')
    assert so.session_videos(tmp_path, cid)[0].name == 'story_final.mp4'
    assert so.latest_final(tmp_path, cid).name == 'story_final.mp4'


def test_latest_final_falls_back_to_naming_when_no_marker(tmp_path):
    cid = 'c2'
    _place(tmp_path, cid, 'video_900.mp4')
    _place(tmp_path, cid, 'video_900_pp.mp4')                # 老数据没有标记 → 按命名猜
    assert so.latest_final(tmp_path, cid).name == 'video_900_pp.mp4'


def test_no_marker_no_final_named_file_returns_none(tmp_path):
    cid = 'c3'
    _place(tmp_path, cid, 'video_1.mp4')
    assert so.latest_final(tmp_path, cid) is None
    # 没有成品时，预览退化为最新产物（不报错、不空）
    assert so.session_videos(tmp_path, cid)[0].name == 'video_1.mp4'


def test_mark_final_survives_missing_source(tmp_path):
    cid = 'c4'
    _place(tmp_path, cid, 'a.mp4')
    assert so.mark_final(tmp_path, cid, tmp_path / 'not_there.mp4') is True
    # 标记指向的文件不存在 → 回退（不抛异常）
    assert so.latest_final(tmp_path, cid) is None
