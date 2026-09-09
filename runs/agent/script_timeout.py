"""script_timeout — RunScript 动态计时（纯 stdlib，独立可测）。

2026-09-09 用户要求"不能像这样因为超时而中断任务"：
  按脚本名给足任务体量的超时；未列出=默认（单段/查询类）。
  故事片主控等长任务另有进度 JSON + resume（story_film --status/续跑），
  中断/重启不重头。
"""
from __future__ import annotations

from pathlib import Path

_SCRIPT_TIMEOUT = 600  # 默认（单段/查询类）
_SCRIPT_TIMEOUTS = {
    'h3_submit.py': 900,          # 单段生成（480p 4s≈1-3 分钟；1080p 20 步可能 >10 分钟）
    'lipsync_chain.py': 1800,     # 单段台词链（TTS+W2L+修复+ASR≈3-6 分钟）
    'film_series.py': 5400,       # 多段电影系列（9 段×逐段生成≈15-25 分钟）
    'story_film.py': 7200,        # 故事片主控（9 段+4 段台词+拼接≈25-40 分钟）
    'upscale_once.py': 3600,      # 4x 超分（7680×4352≈5-8 分钟/个）
    'film_stitch.py': 900,        # 拼接（9 段 480p≈1 分钟）
    'night_runner.py': 300,       # 状态/巡检
}


def script_timeout(script_name: str) -> int:
    """脚本名（或 runs/ 相对路径）→ 超时秒数；未列出=默认 600。"""
    return _SCRIPT_TIMEOUTS.get(Path(script_name).name, _SCRIPT_TIMEOUT)
