"""
h3.subgraph
===========
ComfyUI **UUID 子图解组（flatten）**：把以“子图节点”封装的工作流展开成开放图。

背景：同事的 `video_minimax_h3_t2v/i2v.json` 把整条 H3 流水线打包进一个 type 为
UUID（如 ``4c314f31-ecda-4b08-ae98-faaba1bf613f``）的节点，图内容存放在
``definitions.subgraphs`` 里。ComfyUI GUI 前端会自行展开子图再提交，但
``/prompt`` API 与本引擎的 UI→API 转换（uiapi）都不认识 UUID 类型 → CLI 无法使用。
本模块把 UUID 节点还原成 r2v 那样的顶层开放图，随后现有 uiapi 链路即可直接处理。

子图文件结构（实测 video_minimax_h3_t2v.json）：
- 顶层 ``nodes`` 含 type=UUID 的节点：``inputs`` 列出对外端口，``widgets_values``
  按 **widget 型端口顺序**保存参数值（prompt/width/height/duration/seed/模型名×4）；
- ``definitions.subgraphs`` 按 UUID 存定义：内部 ``nodes`` + ``links``
  （origin/target 为 -10=输入桩 inputNode、-20=输出桩 outputNode 的边表示
  “端口 ↔ 内部节点输入/输出”映射）。

展开要点：
1) 内部节点搬进顶层并重映射 id（顶层与内部 id 冲突）；
2) -10 输入桩：对应端口顶层已连线 → 外部源接到内部真实输入；未连线且 widget 型
   → 取 UUID widgets_values 值注入内部节点 widget 槽；IMAGE 型未连线 → 断开
   （t2v 纯文生无首/末帧）；
3) -20 输出桩：内部输出接到顶层原消费者（SaveVideo 等）；
4) 删除 UUID 节点及其顶层连线。

限制：暂不支持嵌套子图（子图内部再含 UUID 节点）。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

# widget 型端口（参数值保存在 UUID 节点 widgets_values 中）
_WIDGET_PORT_TYPES = {"STRING", "INT", "FLOAT", "COMBO", "BOOLEAN"}


class UiUnsupported(ValueError):
    """子图无法可靠解组。"""


def _is_widget_port_type(t: Any) -> bool:
    return str(t or "") in _WIDGET_PORT_TYPES


def _is_single_widget_slot(port: Dict[str, Any]) -> bool:
    """输入槽是否为“单值 widget 型”（占该节点 widgets_values 一席）。
    连接型（MODEL/IMAGE/... 或 'FLOAT,INT,BOOLEAN' 多类型）不算。"""
    t = str(port.get("type") or "")
    if "," in t:
        return False
    if t in _WIDGET_PORT_TYPES:
        return True
    return bool(port.get("widget"))


def _widget_index_of(node_inputs: List[Dict[str, Any]], slot: int) -> int:
    """目标输入槽 slot 之前有几个 widget 型槽（即值在 widgets_values 中的索引）。"""
    return sum(1 for i in range(slot) if _is_single_widget_slot(node_inputs[i]))


def _inject_widget_value(node: Dict[str, Any], slot: int, value: Any) -> None:
    """把端口值写入内部节点对应 widget 槽：去连线、覆盖或补齐 widgets_values。"""
    node_inputs = node.get("inputs") or []
    if slot < 0 or slot >= len(node_inputs):
        raise UiUnsupported(f"节点 {node.get('type')}#{node.get('id')} 输入槽越界: {slot}")
    node_inputs[slot]["link"] = None
    values = node.get("widgets_values")
    if not isinstance(values, list):
        values = []
        node["widgets_values"] = values
    widx = _widget_index_of(node_inputs, slot)
    while len(values) < widx:
        values.append(None)
    if widx < len(values):
        values[widx] = value
    else:
        values.append(value)


def collect_subgraph_ids(ui: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """由 definitions.subgraphs 建 {uuid: defn}；无则空 dict。"""
    defs = ((ui.get("definitions") or {}).get("subgraphs")) or []
    out: Dict[str, Dict[str, Any]] = {}
    for d in defs:
        if isinstance(d, dict) and d.get("id"):
            out[str(d["id"])] = d
    return out


def flatten_subgraphs(ui: Dict[str, Any]) -> Dict[str, Any]:
    """
    解组全部顶层 UUID 子图节点 → 开放 UI 图。
    无子图定义或无 UUID 节点时返回原对象（不拷贝）。
    """
    defs = collect_subgraph_ids(ui)
    if not defs:
        return ui
    nodes = ui.get("nodes") or []
    sub_nodes = [n for n in nodes if isinstance(n, dict) and str(n.get("type") or "") in defs]
    if not sub_nodes:
        return ui

    sub_ids = {int(n["id"]) for n in sub_nodes}
    top_ids = {int(n["id"]) for n in nodes if isinstance(n.get("id"), int)}

    # ---- 顶层连线分类：涉及 UUID 节点的先扣下按桩重接，无关的保留 ----
    top_links = [list(l) for l in (ui.get("links") or []) if isinstance(l, (list, tuple))]
    link_by_id: Dict[int, list] = {int(l[0]): l for l in top_links}
    involved: List[list] = []
    keep_links: List[list] = []
    for l in top_links:
        if int(l[1]) in sub_ids or int(l[3]) in sub_ids:
            involved.append(l)
        else:
            keep_links.append(l)

    next_nid = (max(top_ids) + 1) if top_ids else 1
    used_lids = {int(l[0]) for l in top_links}
    next_lid = (max(used_lids) + 1) if used_lids else 1

    out_nodes: List[Dict[str, Any]] = [dict(n) for n in nodes if n not in sub_nodes]

    def _new_link(origin_id: int, origin_slot: int,
                  target_id: int, target_slot: int, typ: Any) -> list:
        nonlocal next_lid
        lid = next_lid
        next_lid += 1
        link = [lid, origin_id, origin_slot, target_id, target_slot, typ]
        keep_links.append(link)
        return link

    def _set_input_link(node_id: int, slot: int, lid: int) -> None:
        for nn in out_nodes:
            if int(nn.get("id")) == node_id:
                ins = nn.get("inputs") or []
                if slot < len(ins) and isinstance(ins[slot], dict):
                    ins[slot]["link"] = lid
                return

    for sub in sub_nodes:
        defn = defs[str(sub.get("type"))]
        d_nodes = defn.get("nodes") or []
        d_links = defn.get("links") or []
        d_inputs = defn.get("inputs") or []
        d_outputs = defn.get("outputs") or []

        nested = [n for n in d_nodes
                  if isinstance(n, dict) and str(n.get("type") or "") in defs]
        if nested:
            raise UiUnsupported(
                f"子图 {defn.get('name')} 内部含嵌套子图节点 {nested[0].get('type')}，暂不支持。")

        # 1) 内部节点搬入顶层 + id 重映射
        id_map: Dict[int, int] = {}
        inner_by_new: Dict[int, Dict[str, Any]] = {}
        for n in d_nodes:
            old = int(n["id"])
            id_map[old] = next_nid
            new_node = dict(n)
            new_node["inputs"] = [dict(i) if isinstance(i, dict) else i
                                  for i in (n.get("inputs") or [])]
            new_node["outputs"] = [dict(o) if isinstance(o, dict) else o
                                   for o in (n.get("outputs") or [])]
            new_node["widgets_values"] = list(n.get("widgets_values") or [])
            new_node["id"] = next_nid
            out_nodes.append(new_node)
            inner_by_new[next_nid] = new_node
            next_nid += 1

        # 2) 内部连线 → litegraph；-10/-20 桩拆出
        port_in: Dict[int, Tuple[int, int]] = {}   # -10 slot -> (inner_id, inner_slot)
        port_out: Dict[int, Tuple[int, int]] = {}  # -20 slot -> (inner_id, inner_slot)
        for l in d_links:
            oid, tid = int(l.get("origin_id")), int(l.get("target_id"))
            if oid == -10:
                port_in[int(l.get("origin_slot"))] = (tid, int(l.get("target_slot")))
                continue
            if tid == -20:
                port_out[int(l.get("target_slot"))] = (oid, int(l.get("origin_slot")))
                continue
            no, nt = id_map.get(oid), id_map.get(tid)
            if no is None or nt is None:
                raise UiUnsupported(f"子图内部连线引用未知节点: {l}")
            oslot, tslot = int(l.get("origin_slot")), int(l.get("target_slot"))
            nl = _new_link(no, oslot, nt, tslot, l.get("type"))
            _set_input_link(nt, tslot, nl[0])

        # 3) -10 输入桩
        w = list(sub.get("widgets_values") or [])
        wk = 0  # widget 型端口在 UUID widgets_values 中的游标
        sub_in_by_name = {str(i.get("name")): i for i in (sub.get("inputs") or [])
                          if isinstance(i, dict)}
        for j, pin in enumerate(d_inputs):
            name = str(pin.get("name") or "")
            tgt = port_in.get(j)
            if tgt is None:
                continue  # 无内部消费者
            inner_old, inner_slot = tgt
            inner_new = id_map.get(inner_old)
            if inner_new is None:
                raise UiUnsupported(f"-10 桩 {name} 指向未知内部节点 {inner_old}")
            tgt_node = inner_by_new[inner_new]
            ext = sub_in_by_name.get(name)
            ext_link = (ext or {}).get("link") if ext else None

            if _is_widget_port_type(pin.get("type")):
                value = w[wk] if wk < len(w) else None
                wk += 1
                src = link_by_id.get(int(ext_link)) if ext_link is not None else None
                if src is not None:
                    nl = _new_link(src[1], src[2], inner_new, inner_slot, src[5])
                    _set_input_link(inner_new, inner_slot, nl[0])
                else:
                    # 无外部连线：widget 值注入内部节点
                    _inject_widget_value(tgt_node, inner_slot, value)
            else:
                src = link_by_id.get(int(ext_link)) if ext_link is not None else None
                if src is not None:
                    nl = _new_link(src[1], src[2], inner_new, inner_slot, src[5])
                    _set_input_link(inner_new, inner_slot, nl[0])
                else:
                    # IMAGE 等连接型且无源 → 断开
                    ins = tgt_node.get("inputs") or []
                    if inner_slot < len(ins) and isinstance(ins[inner_slot], dict):
                        ins[inner_slot]["link"] = None

        # 4) -20 输出桩 → 顶层原消费者
        for l in involved:
            if int(l[1]) != int(sub["id"]):
                continue
            oi = int(l[2])  # UUID 节点输出槽序 = defn.outputs 序
            inner = port_out.get(oi)
            if inner is None:
                continue
            io_old, io_slot = inner
            io_new = id_map.get(io_old)
            if io_new is None:
                raise UiUnsupported(f"-20 输出桩指向未知内部节点 {io_old}")
            nl = _new_link(io_new, io_slot, int(l[3]), int(l[4]),
                           l[5] if len(l) > 5 else None)
            _set_input_link(int(l[3]), int(l[4]), nl[0])

    result = dict(ui)
    result["nodes"] = out_nodes
    result["links"] = keep_links
    result["_flattened_subgraphs"] = True
    return result
