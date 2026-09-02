"""
h3.uiapi
========
ComfyUI **UI(节点图) 工作流 → 扁平 API** 转换器（headless，可提交）。

动机：spark 官方模板（含名为 api_minimax_* 的文件）其实是 UI 格式（nodes/links），
CLI 引擎此前不能直接用。本模块依据“在线 ComfyUI 的 /object_info 节点定义”把
UI 节点图还原成扁平 API（class_type + inputs），从而真正以官方模板语义提交。

设计要点：
  * 连接输入：node.inputs 中带 link 的项 -> [源节点id, 输出槽位]；
  * widget 值顺序完全按 object_info 的声明顺序消费（required 再 optional）：
      - 普通 widget（INT/FLOAT/STRING/BOOLEAN/COMBO/选项数组）消耗 1 个值；
      - 动态组合 COMFY_DYNAMICCOMBO_V3（如 model、SaveVideo.codec）消耗 1 个
        选中值，若选中项带子输入（MiniMax H3 的 prompt/resolution/ratio/duration…）
        则紧接着按序消耗其子 widget 值并平铺到顶层 inputs；
      - control_after_generate 紧随其数值 widget：值 fixed/randomize/...，
        randomize 时把该数值随机化（不写入 API）；
      - autogrow/IMAGE/VIDEO 等可连线字段不作为 widget（以 node.inputs 槽位出现）。
  * LoadImage 只用第一个 widget（image=文件名），其余内部展示值忽略；
  * 占位符字符串({{token}})原样保留，由上层统一替换（图片占位符会在提交前上传）。

无法可靠转换时抛 UiUnsupported（确定性错误），由上层决定回退内置或报错。
"""
from __future__ import annotations

import random
from typing import Any, Dict, List, Tuple

from . import comfy
from .params import ParamError

_KNOWN_TYPES = {
    "MODEL", "VAE", "CLIP", "CONDITIONING", "LATENT", "IMAGE", "MASK",
    "CONTROL_NET", "NOISE", "SIGMAS", "GUIDER", "SAMPLER", "AUDIO", "VIDEO", "*",
    "MODEL_LORA", "STYLE_MODEL", "CLIP_VISION", "PERTURB_AUDIO", "IMAGEOPT",
}
_WIDGET_PRIMITIVES = {"INT", "FLOAT", "STRING", "BOOLEAN", "COMBO"}
_DYNAMIC = "COMFY_DYNAMICCOMBO_V3"


class UiUnsupported(ParamError):
    """UI 模板无法可靠转换。"""


def fetch_object_info(client: comfy.ComfyClient, class_types: List[str]) -> Dict[str, dict]:
    out: Dict[str, dict] = {}
    for c in sorted(set(class_types)):
        try:
            info = client.request("GET", f"/object_info/{c}", retries=2)
        except comfy.ComfyError as e:
            raise UiUnsupported(f"无法读取节点定义 {c}（object_info）: {e}") from e
        if not isinstance(info, dict) or c not in info:
            raise UiUnsupported(f"服务端没有节点定义: {c}")
        out[c] = info[c]
    return out


def _is_combo_options(spec_first: Any) -> bool:
    if not isinstance(spec_first, list) or not spec_first:
        return False
    return not any(isinstance(x, str) and x in _KNOWN_TYPES for x in spec_first)


def _spec_kind(name: str, spec: Any) -> str:
    """返回 widget 类别：value / dynamic / connectable / skip。"""
    s0 = spec[0]
    if isinstance(s0, str):
        if s0 == _DYNAMIC:
            return "dynamic"
        if s0 in _WIDGET_PRIMITIVES:
            return "value"
        return "connectable"  # IMAGE/VIDEO/INT-之外的类型名等
    if isinstance(s0, list):
        return "value" if _is_combo_options(s0) else "connectable"
    return "skip"


def _cfg_of(spec: Any) -> dict:
    return spec[1] if len(spec) > 1 and isinstance(spec[1], dict) else {}


def _expand_dynamic_option(spec: Any, selected_key: str) -> List[Tuple[str, Any, dict]]:
    """返回选中 option 的子输入：(name, spec, cfg)；空则 []。"""
    out: List[Tuple[str, Any, dict]] = []
    for o in _cfg_of(spec).get("options") or []:
        if not isinstance(o, dict) or o.get("key") != selected_key:
            continue
        oi = o.get("inputs") or {}
        for section in ("required", "optional"):
            for name, sub in (oi.get(section) or {}).items():
                out.append((name, sub, _cfg_of(sub)))
        break
    return out


# ---------------------------------------------------------------------------
# 转换
# ---------------------------------------------------------------------------
def ui_to_api(ui_graph: dict, client: comfy.ComfyClient) -> Dict[str, dict]:
    nodes = ui_graph.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        raise UiUnsupported("UI 模板缺少 nodes。")

    links: Dict[int, List] = {}
    for l in ui_graph.get("links") or []:
        if isinstance(l, list) and len(l) >= 6:
            links[int(l[0])] = l

    class_types = sorted({str(n.get("type")) for n in nodes})
    # UI 装饰/注释节点不参与执行，也常常没有 object_info
    ui_only = {"MarkdownNote", "Note", "WebcamNote"}
    oinfo = fetch_object_info(client, [c for c in class_types if c not in ui_only])

    api: Dict[str, dict] = {}
    for node in nodes:
        nid = str(node.get("id"))
        cls = str(node.get("type"))
        if cls in ui_only:
            continue  # 装饰节点跳过
        if int(node.get("mode", 0)) != 0:
            continue  # bypass/禁用
        inputs: Dict[str, Any] = {}

        # 1) 连接输入（含 autogrow 子槽，如 model.reference_images.image_1）
        # 源节点号用字符串：与本项目提交成功的扁平 API 保持一致
        for slot in node.get("inputs") or []:
            if not isinstance(slot, dict) or slot.get("link") is None:
                continue
            link = links.get(int(slot["link"]))
            if link:
                inputs[str(slot.get("name"))] = [str(link[1]), int(link[2])]

        info = oinfo.get(cls)
        if not info:
            raise UiUnsupported(f"节点类型 '{cls}' 缺少 object_info。")
        widgets = list(node.get("widgets_values") or [])

        def take() -> Any:
            if not widgets:
                raise UiUnsupported(f"节点 {cls}(#{nid}) widget 值不足。")
            return widgets.pop(0)

        def _consume_value(name: str, spec: Any, cfg: dict,
                           prefix: str = "", target: Optional[Dict] = None) -> None:
            target = inputs if target is None else target
            full = f"{prefix}.{name}" if prefix else name
            kind = _spec_kind(name, spec)
            if kind == "dynamic":
                val = take()
                target[full] = val
                for child in _expand_dynamic_option(spec, str(val)):
                    cname, cspe, ccfg = child
                    _consume_value(cname, cspe, ccfg, prefix=full, target=target)
                return
            if kind != "value":
                return
            val = take()
            target[full] = val
            if cfg.get("control_after_generate"):
                ctrl = take()
                if str(ctrl).lower() == "randomize" and isinstance(val, (int, float)):
                    target[full] = random.SystemRandom().randint(0, 2**31 - 1)

        if cls == "LoadImage":
            if "image" not in inputs:
                inputs["image"] = take()
            widgets.clear()
        else:
            # 2) 按 object_info 声明顺序消费 widget（动态组合的子输入键带 model. 前缀）
            slot_linked: Dict[str, bool] = {}
            for slot in node.get("inputs") or []:
                if isinstance(slot, dict):
                    slot_linked[str(slot.get("name"))] = slot.get("link") is not None

            items: List[Tuple[str, Any, dict]] = []
            for section in ("required", "optional"):
                for name, spec in (info.get("input", {}).get(section) or {}).items():
                    if _spec_kind(name, spec) in ("value", "dynamic"):
                        items.append((name, spec, _cfg_of(spec)))
            for name, spec, cfg in items:
                # 已由连接输入提供值的 widget（convertWidgetToInput/上游连线）不再消费
                if slot_linked.get(name, False):
                    continue
                _consume_value(name, spec, cfg)

            # 残留值若与“已连线而被跳过的 widget”数量一致，则是文件的陈旧值，丢弃
            stale = sum(1 for (name, _, _) in items if slot_linked.get(name, False))
            if len(widgets) > stale:
                raise UiUnsupported(
                    f"节点 {cls}(#{nid}) 有 {len(widgets)} 个 widget 值无法按定义分配。"
                    "请检查模板与该节点版本是否一致。")
            widgets.clear()

        api[nid] = {"class_type": cls, "inputs": inputs}
    return api


def convert_ui_file(path: Any, client: comfy.ComfyClient) -> Dict[str, dict]:
    """读 UI 文件并转换为扁平 API dict（占位符原样保留）。"""
    from .templates import load_json_file

    data = load_json_file(path)
    if not isinstance(data, dict) or not isinstance(data.get("nodes"), list):
        raise UiUnsupported(f"不是 ComfyUI UI 工作流: {path}")
    return ui_to_api(data, client)
