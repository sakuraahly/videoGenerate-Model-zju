"""studio.rules — 创空间「电影 Agent」的规则引擎（零依赖、可单测）。

设计定位（见 docs/planbook/book-20-studio-film-agent.md §2.3）：
  本包是**零配置保底**：不填任何模型 key 时，也要能产出一份「照做就能拍」的剧本 /
  分镜表 / 生产包。规则引擎做得很厚，是 P0 的验收项。

模块划分：
  frames.py     帧网格与参数推导（5+17k @24fps、分辨率档、段时长分配、音长估算）
  lint.py       剧本静态预检（搬自 runs/h3/story_lint.py）+ 版权/IP 词表 + 素材授权
  voice.py      台词语言 → 音色匹配（中文 xiaoxiao/yunxi、英文 aria/daler）
  prompts.py    六段式提示词组装（主体/环境/光影/风格/运镜/音频）+ 正负词库
  templates.py  科幻母题 × 时长 × 风格 的分镜骨架库（组合 ≥50 套）

约束：纯标准库；不联网；不依赖 studio 之外的东西；全部函数可单测。
"""
from __future__ import annotations

__all__ = ["frames", "lint", "voice", "prompts", "templates", "roles", "delivery", "post"]
