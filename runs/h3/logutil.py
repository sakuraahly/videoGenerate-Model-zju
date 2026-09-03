#!/usr/bin/env python3
"""logutil — 统一运行日志（供 idea2prompts / h3_text2img* / agent 工具等全部
可调用 Python 程序共用；h3_submit.py 保留其原有同构实现）。

格式与 runs/h3_submit.py 完全一致：
    [YYYY-MM-DD HH:MM:SS] py: <tool> <event ...>          # event 可含 key=value

日志文件解析顺序：
1. 环境变量 H3_LOG_FILE 已注入（PowerShell 编排层 Initialize-RunLog 后共用同一文件，
   实现“一次会话/一个任务 = 一份完整日志”，PS 行与 py: 行交错可查）；
2. 否则本模块自动在 <项目根>/logs/ 自举 run_<时间戳>_<毫秒>.log（毫秒防同秒撞名，
   与任务目录 h3_<时间戳>_<毫秒> 命名风格一致），并把路径写回 H3_LOG_FILE，
   同进程后续工具调用自然汇入同一文件。

事件规范（全链路统一）：
  start argv=[...]        → 任务开始（含真实命令行）
  task tool=.. idea_len=.. / task tool=.. resolution=.. seconds=..（任务配置摘要）
  submitted prompt_id=..  → 提交到 ComfyUI
  completed / dry_run / ok / err … → 结束/预览/分项/失败（失败必须落 err，杜绝
  “只有 run start 两行”的粗略日志——教训见 docs/session-summary.md §12.4）
"""
from __future__ import annotations

import datetime
import os
from pathlib import Path

ENV_NAME = "H3_LOG_FILE"


def _ts() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _append(path: str, text: str) -> None:
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"[{_ts()}] py: {text}\n")
    except OSError:
        pass


def ensure_run_log(project_dir, tool: str) -> str:
    """确保本次运行有日志文件可追加，返回路径。

    - 外层已注入 H3_LOG_FILE（如 generate_video.ps1 / ai_prompts.ps1）→ 沿用；
    - 否则 CLI 直跑时自动在 <项目根>/logs/ 建 run_<时间戳>_<毫秒>.log 并写起始行，
      随后把路径写回环境变量，供同进程后续调用共享。
    """
    existing = os.environ.get(ENV_NAME, "").strip()
    if existing:
        return existing
    log_dir = Path(project_dir) / "logs"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        now = datetime.datetime.now()
        name = f"run_{now.strftime('%Y%m%d_%H%M%S')}_{now.microsecond // 1000:03d}.log"
        path = log_dir / name
        _append(str(path), f"=== {tool} run start ===")
        os.environ[ENV_NAME] = str(path)
        return str(path)
    except OSError:
        return ""


def log_event(tool: str, event: str) -> None:
    """追加一行 `<tool> <event>`（event 内自带 key=value 或短语）。"""
    path = os.environ.get(ENV_NAME, "").strip()
    if not path:
        return
    _append(path, f"{tool} {event}")


def fmt(**fields) -> str:
    """结构化字段 → 'k=v ...'（值含空格会被原样保留，便于人读）。"""
    return " ".join(f"{k}={v}" for k, v in fields.items())


def log_start(tool: str, argv=None) -> None:
    argv = list(argv) if argv is not None else []
    log_event(tool, f"start argv={argv}")
