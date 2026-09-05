"""
h3.workflow
===========
Workflow 领域模块：分辨率预设、帧数换算、工作流构建，以及工作流文件的
API / UI 格式保存。

该模块只依赖标准库，不依赖网络与磁盘布局，便于单测与将来更换模型
（只需替换 build_workflow 或增加新的 builder）。
"""
from __future__ import annotations

import datetime
import json
from pathlib import Path
from typing import Dict, Optional, Tuple

# MiniMax H3 原生推荐分辨率预设（宽, 高）
RESOLUTION_PRESETS: Dict[str, Tuple[int, int]] = {
    "360p": (608, 352),
    "480p": (864, 480),
    "540p": (960, 544),
    "720p": (1280, 736),
    "768p": (1344, 768),
}

DEFAULT_FPS = 24.0
DEFAULT_STEPS = 20
MAX_SECONDS = 60.0  # 超过该时长只是警告（H3 建议 5~15s）


def snap_length(seconds: float, fps: float = DEFAULT_FPS) -> int:
    """
    把秒数换算为 H3 合法帧数（H3 使用 17k+5 的帧数网格）。

    结果恒满足 (frames - 5) % 17 == 0 且 frames >= 5，
    从而保证任何输入都能被模型接受。
    """
    raw = max(5, int(round(seconds * fps)))
    return raw + (5 - (raw % 17)) % 17


def build_workflow(
    prompt: str,
    width: int,
    height: int,
    length: int,
    seed: int,
    negative_prompt: str = "",
    steps: int = DEFAULT_STEPS,
    fps: float = DEFAULT_FPS,
) -> dict:
    """
    构建 flat API 格式的 MiniMax H3 工作流。

    negative_prompt 为空时不写该输入键，避免某些节点对空串报错。
    steps / fps 可配置，便于不同画质/速度需求。
    """
    node5_inputs: Dict[str, object] = {
        "clip": ["2", 0],
        "vae": ["3", 0],
        "prompt": prompt,
        "width": int(width),
        "height": int(height),
        "length": int(length),
    }
    if negative_prompt:
        node5_inputs["negative_prompt"] = negative_prompt

    return {
        "1": {
            "class_type": "UNETLoader",
            "inputs": {
                "unet_name": "minimax_h3_fl2va_pruned_int8_convrot.safetensors",
                "weight_dtype": "default",
            },
        },
        "2": {
            "class_type": "CLIPLoader",
            "inputs": {
                "clip_name": "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors",
                "type": "minimax",
            },
        },
        "3": {
            "class_type": "VAELoader",
            "inputs": {"vae_name": "minimax_h3_video_vae_fp16.safetensors"},
        },
        "4": {
            "class_type": "VAELoader",
            "inputs": {"vae_name": "minimax_h3_audio_vae_fp32.safetensors"},
        },
        "5": {"class_type": "MiniMaxH3ImageToVideo", "inputs": node5_inputs},
        "6": {
            "class_type": "BasicGuider",
            "inputs": {"model": ["1", 0], "conditioning": ["5", 0]},
        },
        "7": {
            "class_type": "KSamplerSelect",
            "inputs": {"sampler_name": "res_multistep"},
        },
        "8": {
            "class_type": "BasicScheduler",
            "inputs": {
                "model": ["1", 0],
                "scheduler": "simple",
                "steps": int(steps),
                "denoise": 1.0,
            },
        },
        "9": {"class_type": "RandomNoise", "inputs": {"noise_seed": int(seed)}},
        "10": {
            "class_type": "SamplerCustomAdvanced",
            "inputs": {
                "noise": ["9", 0],
                "guider": ["6", 0],
                "sampler": ["7", 0],
                "sigmas": ["8", 0],
                "latent_image": ["5", 1],
            },
        },
        "11": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["10", 0], "vae": ["3", 0]},
        },
        "12": {
            "class_type": "VAEDecodeAudio",
            "inputs": {"samples": ["10", 0], "vae": ["4", 0]},
        },
        "13": {
            "class_type": "CreateVideo",
            "inputs": {
                "images": ["11", 0],
                "fps": float(fps),
                "audio": ["12", 0],
            },
        },
        "14": {
            "class_type": "SaveVideo",
            "inputs": {
                "video": ["13", 0],
                "filename_prefix": "video/MiniMax_H3",
                "format": "auto",
                "codec": "auto",
            },
        },
    }


# ---------------------------------------------------------------------------
# API 格式 -> UI 格式（标准 ComfyUI/LiteGraph 结构，含完整连线信息）
# ---------------------------------------------------------------------------
def workflow_to_ui(workflow: dict) -> dict:
    """
    把 flat API 工作流转换为可被 ComfyUI 前端加载的标准 UI 格式。

    与旧版的关键差异：`links` 采用 LiteGraph 要求的数组形式
    ``[id, origin_id, origin_slot, target_id, target_slot, type]``，
    每个节点的 connectable 输入带 ``link`` 引用、输出带 ``links`` 引用，
    因此重新打开 /workflows/*/workflow_ui.json 时能正确显示全部连线。

    局限说明：widget 值的顺序来自本工具构建 API 工作流时写入的顺序；
    若想获得与远程节点定义完全一致的 widget 顺序，可在 ComfyUI 界面中
    载入本文件后按提示手动核对（不影响连线的读取）。
    """
    # 新bug修复：apply_lora 注入字符串 id（如 lora_14）→ 旧实现 int(k) 抛错（UI 仅 API）。
    # 统一映射为确定性 int：数值 id 原样；字符串 id 排在数值后顺延分配。
    _mapping: dict = {}
    _used: set = set()
    for k in workflow:
        try:
            _used.add(int(k))
        except (TypeError, ValueError):
            pass
    _next = (max(_used) + 1) if _used else 1
    for k in workflow:
        try:
            _mapping[k] = int(k)
        except (TypeError, ValueError):
            while _next in _used:
                _next += 1
            _mapping[k] = _next
            _used.add(_next)
            _next += 1
    node_by_id: Dict[int, dict] = {_mapping[k]: v for k, v in workflow.items()}
    node_ids = sorted(node_by_id)

    # 第一次遍历：收集所有连接并确定每个源节点的输出槽位数
    # API 连接形式为 {"src_node": int(id), "slot": int}
    edges: list = []  # (origin_id, origin_slot, target_id, input_name)
    out_slot_count: Dict[int, int] = {}
    for tid in node_ids:
        for iname, val in node_by_id[tid].get("inputs", {}).items():
            if isinstance(val, list) and len(val) == 2 and isinstance(val[0], str):
                try:
                    oid = _mapping[val[0]]
                    oslot = int(val[1])
                except (TypeError, ValueError):
                    continue
                edges.append((oid, oslot, tid, iname))
                out_slot_count[oid] = max(out_slot_count.get(oid, -1), oslot)

    # 构建节点（只把“可连线输入”放进 inputs；标量值进 widgets_values）
    nodes = []
    node_input_idx: Dict[int, Dict[str, int]] = {}  # node_id -> {input_name: inputs 下标}
    for order, nid in enumerate(node_ids, start=1):
        node = node_by_id[nid]
        class_type = node.get("class_type", "")
        row, col = divmod(order - 1, 5)
        inputs_list = []
        input_index = {}  # input_name -> inputs 数组下标
        widgets = []
        for iname, val in node.get("inputs", {}).items():
            if isinstance(val, list) and len(val) == 2 and isinstance(val[0], str):
                input_index[iname] = len(inputs_list)
                inputs_list.append({"name": iname, "type": "*", "link": None})
            else:
                widgets.append(val)
        node_input_idx[nid] = input_index
        # 输出槽位：= 被引用最大槽位 + 1（无人引用的节点如 SaveVideo 无输出）
        out_count = (out_slot_count.get(nid, -1) + 1) if nid in out_slot_count else 0
        outputs = [
            {"name": f"output_{i}", "type": "*", "links": []}
            for i in range(out_count)
        ]
        nodes.append(
            {
                "id": nid,
                "type": class_type,
                "pos": [col * 350, row * 250],
                "size": [300, 200],
                "flags": {},
                "order": order,
                "mode": 0,
                "inputs": inputs_list,
                "outputs": outputs,
                "properties": {"Node name for S&R": class_type},
                "widgets_values": widgets,
            }
        )

    node_ref = {n["id"]: n for n in nodes}

    # 第二次遍历：生成 LiteGraph 数组格式的 links 并回填引用
    links = []
    for link_id, (oid, oslot, tid, iname) in enumerate(edges, start=1):
        origin = node_ref[oid]
        target = node_ref[tid]
        target_slot = node_input_idx[tid][iname]
        target["inputs"][target_slot]["link"] = link_id
        if oslot < len(origin["outputs"]):
            origin["outputs"][oslot]["links"].append(link_id)
        links.append([link_id, oid, oslot, tid, target_slot, "*"])

    return {
        "last_node_id": max(node_ids) if node_ids else 0,
        "last_link_id": len(links),
        "nodes": nodes,
        "links": links,
        "groups": [],
        "config": {},
        "extra": {},
        "version": 0.4,
    }


# ---------------------------------------------------------------------------
# 工作流文件落盘
# ---------------------------------------------------------------------------
def _atomic_write_json(path: Path, obj: object) -> None:
    """先写临时文件再替换，避免进程中断留下半个 JSON 文件。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
        f.flush()
    tmp.replace(path)


def save_workflow_api(workflow: dict, filepath: Path) -> Path:
    """保存 API 格式工作流，返回写入路径。"""
    filepath = Path(filepath)
    _atomic_write_json(filepath, workflow)
    print(f"API 工作流已保存: {filepath}")
    return filepath


def save_workflow_ui(workflow: dict, filepath: Path) -> Optional[Path]:
    """保存 UI 格式工作流；转换失败返回 None（不影响主流程）。"""
    try:
        filepath = Path(filepath)
        _atomic_write_json(filepath, workflow_to_ui(workflow))
        print(f"UI 工作流已保存: {filepath}")
        return filepath
    except Exception as e:  # noqa: BLE001 - UI 转换失败不应阻断提交
        _msg = f"警告：UI 工作流转换失败（{e}），仅保存 API 格式。"
        print(_msg, file=__import__("sys").stderr, flush=True)
        # 新bug：失败必须留痕（logutil），避免“有 api 无 ui”不可溯源
        try:
            from h3 import logutil
            logutil.ensure_run_log(Path(__file__).resolve().parents[2], "workflow")
            logutil.log_event("workflow", f"ui_convert_failed err={type(e).__name__}: {e}")
        except Exception:  # noqa: BLE001
            pass
        return None


def make_task_folder_name(now: Optional[datetime.datetime] = None) -> str:
    """生成带毫秒的任务文件夹名，避免同一秒内重复运行发生目录冲突。"""
    dt = now or datetime.datetime.now()
    return f"h3_{dt:%Y%m%d_%H%M%S}_{dt.microsecond // 1000:03d}"
