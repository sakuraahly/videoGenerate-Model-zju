#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""frames — 帧网格与参数推导（纯函数，零依赖）。

口径来源（搬自 spark 真机项目，勿改）：
  * 帧数必须落 **5 + 17k** 网格（@24fps）：5, 22, 39, 56, 73, 90, 107, 124, 141, ...
    —— H3 模型硬约束；非网格值会被吸附，事先算准可避免「时长与预期不符」。
  * 分辨率档位：360p=608x352 / 480p=864x480 / 540p=960x544 / 720p=1280x736 / 768p=1344x768。
  * 台词段时长服从语音：先估音长，再选**最小 ≥ 音长+余量** 的帧档，避免「说完还在动嘴」。
"""
from __future__ import annotations

FPS = 24
FRAME_STEP = 17          # 5 + 17k
FRAME_BASE = 5
MAX_FRAMES = 3000        # 安全上限（约 125s）

RESOLUTION_PRESETS = {
    "360p": (608, 352),
    "480p": (864, 480),
    "540p": (960, 544),
    "720p": (1280, 736),
    "768p": (1344, 768),
}

# 语速经验值（字/词 每秒）：无 TTS 时估算台词时长
ZH_CHARS_PER_SEC = 4.6
EN_WORDS_PER_SEC = 2.6


def frame_grid(max_frames: int = MAX_FRAMES) -> list:
    """完整帧档列表（5+17k，整数帧）。"""
    out, f = [], FRAME_BASE
    while f <= max_frames:
        out.append(f)
        f += FRAME_STEP
    return out


def frames_for_seconds(seconds: float) -> int:
    """秒数 → 帧档（向上取，保证不短于请求时长）。"""
    need = max(0.0, float(seconds or 0.0))
    for f in frame_grid():
        if f / FPS >= need:
            return f
    return MAX_FRAMES


def fit_frames_seconds(dur: float, margin: float = 0.2) -> float:
    """音长 → 视频秒数（选**最小** ≥ dur+margin 的帧档）。

    台词 2.76s + 0.2s → 3.042s（73 帧），而不是 4.458s（107 帧）。
    """
    need = max(0.5, float(dur or 0.0) + float(margin))
    for f in frame_grid():
        if f / FPS >= need:
            return round(f / FPS, 3)
    return round(MAX_FRAMES / FPS, 3)


def frames_of(seconds: float) -> int:
    """秒数 → 帧数（落网格，向上）。"""
    return frames_for_seconds(seconds)


def estimate_speech_seconds(text: str, *, cjk_per_sec: float = ZH_CHARS_PER_SEC,
                            en_words_per_sec: float = EN_WORDS_PER_SEC) -> float:
    """按字数/词数粗略估算台词时长（无 TTS 时的推导依据）。"""
    s = str(text or "")
    cjk = sum(1 for ch in s if "\u4e00" <= ch <= "\u9fff")
    words = len([w for w in "".join(
        ch if (ch.isascii() and (ch.isalnum() or ch in "'-")) else " " for ch in s
    ).split() if w])
    sec = cjk / max(0.1, cjk_per_sec) + words / max(0.1, en_words_per_sec)
    return round(max(0.6, sec), 3)


def resolution_of(name: str) -> tuple:
    """分辨率档名 → (宽, 高)；未知返回 480p。"""
    return RESOLUTION_PRESETS.get(str(name or "").strip().lower(), RESOLUTION_PRESETS["480p"])


def allocate_segments(total_seconds: float, n: int, *, min_seg: float = 2.0) -> list:
    """把总时长分配给 n 段，每段落帧网格，总和尽量不超过 total_seconds。

    返回 [秒数, ...]（长度 = n）。

    实现要点（2026-09-11 修 bug）：**全程用整数帧数运算**，绝不做「秒数→帧数→秒数」往返取整 ——
    round(175/24, 3) = 7.292 比真实值 7.2917 略大，再回查帧档会得到 192，
    于是「压低一段」变成不动点，while 永不退出（实测把整个测试套件挂死）。
    另外加迭代上限兜底：任何逻辑滑落都只会「略超总时长」，不会死循环。
    """
    n = max(1, int(n))
    max_iters = n * 8 + 16
    total = max(float(min_seg) * n, float(total_seconds or 0.0))
    each = total / n
    grid = frame_grid()
    # 先各自向上取档，再压低超标的那几段（整数帧严格递减 → 必然终止）
    counts = [frames_for_seconds(each) for _ in range(n)]
    for _ in range(max_iters):
        if sum(f / FPS for f in counts) <= total + 0.05 or len(counts) <= 1:
            break
        i = max(range(len(counts)), key=lambda k: counts[k])
        idx = grid.index(counts[i]) if counts[i] in grid else 0
        if idx == 0:
            break
        nxt = grid[idx - 1]
        if nxt / FPS < float(min_seg) - 1e-9:
            break
        counts[i] = nxt
    return [round(f / FPS, 3) for f in counts]


def valid_lengths() -> dict:
    """常用时长 → 帧数对照（给页面/文档展示）。"""
    return {("%ss" % round(f / FPS, 2)): f for f in frame_grid(400)}
