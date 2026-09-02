"""
h3.params
=========
参数领域模块：解析参数文件（parameters/video.txt）与环境配置
（config/environment.json），做类型/边界校验并归一化。

关键点：
  * 兼容 BOM / CRLF / 注释（# 或 ; 起始）/ key 大小写 / 行内空格
  * 未知参数不会被丢弃，会放进 ``raw`` 供后续功能扩展读取
  * 所有确定性错误抛出 :class:`ParamError`（调用方映射为退出码 3）
"""
from __future__ import annotations

import json
import os
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional, Tuple

from . import workflow

ENV_FILE_NAME = "environment.json"
PARAMS_FILE_NAME = "video.txt"

DEFAULT_ENV = {
    "remote_host": "spark",
    "remote_comfyui_dir": "~/ai/ComfyUI",
    "remote_python": "~/ai/venv/bin/python",
    "tmux_session": "comfyui",
    "remote_output_dir": "~/ai/ComfyUI/output",
    "comfyui_port": 8188,
    "local_port": 8188,
    "ssh_connect_timeout_seconds": 20,
    "server_alive_interval_seconds": 15,
    "server_alive_count_max": 4,
    "python_exe": "python",
    "max_attempts": 3,
    "retry_delay_seconds": 5,
    "scp_attempts": 3,
}

# 本项目约定的目录布局（相对项目根）
LAYOUT = {
    "parameters_dir": "parameters",
    "prompts_dir": "prompts",
    "runs_dir": "runs",
    "workflows_dir": "workflows",
    "outputs_dir": "outputs",
    "config_dir": "config",
    "shell_dir": "shell",
}

DEFAULTS = {
    "resolution": "480p",
    "seconds": 5.0,
    "seed": 12345,       # 固定种子可复现；配置成 auto 则每次随机
    "steps": workflow.DEFAULT_STEPS,
    "fps": workflow.DEFAULT_FPS,
    "timeout": 3600,     # 轮询总超时（秒）
    "negative_prompt_optional": True,
}


class ParamError(ValueError):
    """参数/配置错误（确定性、不可恢复）。"""


def project_root_from_file(file_path: Path) -> Path:
    """根据 ``runs/h3/...`` 或 ``runs/h3_submit.py`` 定位项目根目录。"""
    p = Path(file_path).resolve()
    if p.name == "h3_submit.py":
        return p.parent.parent
    return p.parent.parent.parent  # runs/h3/xxx.py -> runs -> root


def load_environment(project_dir: Path) -> Dict[str, object]:
    """
    读取 config/environment.json；缺失或损坏时回退默认值并给出警告，
    绝不因环境文件问题阻断运行。
    """
    env = dict(DEFAULT_ENV)
    path = Path(project_dir) / LAYOUT["config_dir"] / ENV_FILE_NAME
    if path.exists():
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                for k, v in data.items():
                    env[k] = v
            else:
                print(f"[警告] 环境配置文件格式异常（应为 JSON 对象）: {path}", file=__import__("sys").stderr)
        except (OSError, json.JSONDecodeError) as e:
            print(f"[警告] 无法读取环境配置文件 {path}（{e}），使用默认值。", file=__import__("sys").stderr)
    return env


def parse_keyvalue_file(path: Path) -> Dict[str, str]:
    """
    解析 ``key=value`` 文本文件。兼容：
      * UTF-8 BOM、CRLF/CR/LF
      * 以 # 或 ; 开头的整行注释
      * key 大小写不敏感（统一转小写）、值首尾空白被去除
    返回小写 key -> 原始字符串值 的字典；无有效行返回空字典。
    """
    result: Dict[str, str] = {}
    try:
        text = Path(path).read_text(encoding="utf-8-sig")
    except OSError:
        return result  # 不存在/不可读 => 空，由调用方决定是否报错
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith(";"):
            continue
        if "=" not in line:
            continue  # 非法行静默跳过（容错），后续可扩展为警告
        key, _, value = line.partition("=")
        key = key.strip().lower()
        value = value.strip()
        if key:
            result[key] = value
    return result


# ---------------------------------------------------------------------------
# 解析后的生成参数
# ---------------------------------------------------------------------------
@dataclass
class GenParams:
    prompt: str = ""
    negative_prompt: str = ""
    resolution: str = "480p"
    width: int = 864
    height: int = 480
    seconds: float = 5.0
    length: int = 0
    seed: int = 12345
    steps: int = workflow.DEFAULT_STEPS
    fps: float = workflow.DEFAULT_FPS
    timeout: int = 3600
    raw: Dict[str, str] = field(default_factory=dict)  # 参数文件中的全部原始键值

    @property
    def dims(self) -> Tuple[int, int]:
        return (self.width, self.height)

    def workflow_dict(self) -> dict:
        return {
            "resolution": self.resolution,
            "width": self.width,
            "height": self.height,
            "seconds": self.seconds,
            "length": self.length,
            "seed": self.seed,
            "steps": self.steps,
            "fps": self.fps,
        }


def _as_float(key: str, value: str, lo: float, hi: float) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise ParamError(f"参数 {key} 不是有效数字: {value!r}")
    if not (lo <= v <= hi):
        raise ParamError(f"参数 {key} 超出允许范围 [{lo}, {hi}]: {value!r}")
    return v


def resolve_params(
    raw: Dict[str, str],
    *,
    prompt: str = "",
    negative_prompt: str = "",
    cli_overrides: Optional[Dict[str, object]] = None,
) -> GenParams:
    """
    把参数文件原始键值 + 命令行覆盖项归一化为 :class:`GenParams`。

    cli_overrides 里的键优先级最高（对应 argparse 同名参数）。
    缺少可选键时使用 DEFAULTS，保证 edit.bat 只写两行也能运行。
    """
    raw = {k.lower(): v for k, v in raw.items()}
    merged = dict(raw)
    if cli_overrides:
        for k, v in cli_overrides.items():
            if v is not None:
                merged[k.lower()] = str(v)

    # 分辨率：合法预设 或 显式宽高
    resolution = merged.get("resolution", DEFAULTS["resolution"]).strip().lower()
    if resolution not in workflow.RESOLUTION_PRESETS:
        if resolution:
            raise ParamError(
                f"分辨率 {resolution!r} 不受支持。可用: {', '.join(workflow.RESOLUTION_PRESETS)}"
            )
        resolution = DEFAULTS["resolution"]
    width, height = workflow.RESOLUTION_PRESETS[resolution]

    if "width" in merged and "height" in merged:
        w = int(_as_float("width", merged["width"], 64, 4096))
        h = int(_as_float("height", merged["height"], 64, 4096))
        if (w % 8) or (h % 8):
            raise ParamError(f"width/height 需为 8 的倍数: {w}x{h}")
        width, height = w, h

    seconds = _as_float("seconds", merged.get("seconds", DEFAULTS["seconds"]), 0.1, 600.0)
    if seconds > workflow.MAX_SECONDS:
        print(f"[提示] 时长 {seconds}s 超过推荐上限 {workflow.MAX_SECONDS}s，"
              f"长视频将显著增加显存与耗时。", file=__import__("sys").stderr)

    fps = _as_float("fps", merged.get("fps", DEFAULTS["fps"]), 1.0, 120.0)
    steps = int(_as_float("steps", merged.get("steps", DEFAULTS["steps"]), 1, 100))

    seed_str = str(merged.get("seed", DEFAULTS["seed"])).strip().lower()
    if seed_str == "auto":
        seed = random.SystemRandom().randint(0, 2**31 - 1)
    else:
        seed = int(_as_float("seed", seed_str, 0, 2**31 - 1))

    timeout = int(
        _as_float("timeout", merged.get("timeout", DEFAULTS["timeout"]), 60, 6 * 3600)
    )

    p = GenParams(
        prompt=prompt,
        negative_prompt=negative_prompt,
        resolution=resolution,
        width=width,
        height=height,
        seconds=seconds,
        seed=seed,
        steps=steps,
        fps=fps,
        timeout=timeout,
        raw=raw,
    )
    p.length = workflow.snap_length(p.seconds, p.fps)
    return p


def read_prompt_file(path: Optional[Path]) -> str:
    """读取提示词文件；空内容返回空串；文件不存在按可选处理（调用方决定）。"""
    if not path:
        return ""
    try:
        return Path(path).read_text(encoding="utf-8-sig").strip()
    except OSError:
        return ""
