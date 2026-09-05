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
    # book-13 P2#11：日志统一按北京时间显示（spark 系统为 UTC，避免日志与用户时区差 8h）
    beijing = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))
    return beijing.strftime("%Y-%m-%d %H:%M:%S")


def _append(path: str, text: str) -> None:
    try:
        # book-11：单文件上限 5MB，超出旋转到 .1（防无限膨胀）
        try:
            if os.path.getsize(path) > 5_000_000:
                os.replace(path, path + ".1")
        except OSError:
            pass
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"[{_ts()}] py: {text}\n")
    except OSError:
        pass


def _tz() -> str:
    """时区标注：统一北京时间 UTC+8（book-13 P2#11；原实现取本地偏移，spark=UTC 造成 8h 差）"""
    return "UTC+8"


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
        _append(str(path), f"# TZ={_tz()}")
        os.environ[ENV_NAME] = str(path)
        return str(path)
    except OSError:
        return ""


def log_event(tool: str, event: str, bare: bool = False) -> None:
    """追加一行 `<tool> <event>`（event 内自带 key=value 或短语）。

    bare=True 时不加工具前缀（供 h3_submit 等既有同构实现收敛，保持旧行格式）。
    """
    path = os.environ.get(ENV_NAME, "").strip()
    if not path:
        return
    _append(path, event if (bare or not tool) else f"{tool} {event}")


def log_file(path: str, tool: str, event: str, rotate_mb: int = 5) -> None:
    """向【指定文件】写入统一格式行（book-11：专供 sync_auto 等长生命周期工具）。
    """
    import os as _os
    try:
        from pathlib import Path as _P
        _P(path).parent.mkdir(parents=True, exist_ok=True)
        if rotate_mb > 0:
            try:
                if _os.path.getsize(path) > rotate_mb * 1_000_000:
                    _os.replace(path, path + ".1")
            except OSError:
                pass
        with open(path, "a", encoding="utf-8") as _fh:
            _fh.write(f"[{_ts()}] py: {tool} {event}\n")
    except OSError:
        pass


def fmt(**fields) -> str:
    """结构化字段 → 'k=v ...'（值含空格会被原样保留，便于人读）。"""
    return " ".join(f"{k}={v}" for k, v in fields.items())


def log_start(tool: str, argv=None) -> None:
    argv = list(argv) if argv is not None else []
    log_event(tool, f"start argv={argv}")
