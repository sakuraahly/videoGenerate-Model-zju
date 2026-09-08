#!/usr/bin/env python3
"""ui_app — 受限调度器的轻量 Gradio 界面（替换 qwen_agent 自带 WebUI）。

能力（对应实测需求）：
  1) 历史对话：按会话文件存档（<项目>/logs/agent_chats/*.jsonl），下拉可
     刷新/加载/删除；“新对话”立即开新会话。
  2) 生成中指示：模型/工具在后台线程执行，界面独立“心跳”线程刷新状态栏
     （“输出中… / 任务进行中（长任务请等待，勿重复提交）…”），不会出现
     “界面卡住却不知道是否还在跑”。
  3) 输出长度纪律：单轮回复设 max_tokens 上限 + 系统提示约束精炼输出；
     模型超长被截断时自动追加提示“回复较长已在此暂停，发送 继续 即可续写”。
  4) 上下文防膨胀（token 口径，见 ctx_budget.py 实测说明）：SGLang ctx=8192、
     每轮固定开销(系统提示+工具模板)≈3.1k token、回复预留 2048 ⇒ 对话部分预算
     ≈2.5k token。每轮调用前按该预算裁剪历史（保最新轮次+尽量保留首轮意图），
     并向 qwen_agent 显式传 max_input_tokens 硬预算（回合内工具往返同样受控），
     裁剪发生时在本次请求中附加说明；若服务端仍报超上下文（400），自动压缩重试。

用法：由 runs/agent/scheduler.py run_gui() 调用（python3 runs/agent/scheduler.py）。
本模块不启动任何外部服务；不含服务管理能力。
"""
from __future__ import annotations

import hashlib
import json
import os
import queue
import secrets
import shutil
import sys
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = os.environ.get(
    'VIDEOGEN_PROJECT_ROOT',
    os.path.expanduser('~/videoGenerate-Model-zju'),
)
CHATS_DIR = Path(PROJECT_ROOT) / 'logs' / 'agent_chats'
THUMBS_DIR = CHATS_DIR / 'thumbs'      # 上传预览缩略图（项目内，随 logs/ gitignore）
UPLOADS_DIR = Path(PROJECT_ROOT) / 'uploads'
UPLOADS_LOG = UPLOADS_DIR / 'log.jsonl'
IMG_EXT = {'.png', '.jpg', '.jpeg', '.webp', '.bmp'}
VID_EXT = {'.mp4', '.webm', '.mov', '.mkv', '.gif'}

_active_turn = threading.Lock()  # 发送幂等锁：忙碌时再次点击直接忽略，不产生重复任务
_stop_requested = threading.Event()  # 停止按钮信号：置位后当前轮尽早收尾（程序级中止）
_upload_in_progress = False  # 上传进行中标志：防止上传/发送竞争
_pending_batch_id: str | None = None  # 当前待发送批次的 batch_id
_gal_previews: list = []  # 兼容旧引用（保留）
_gal_by_cid: dict = {}  # book-16：预览按会话隔离（cid -> list）


# ---------------------------------------------------------------- 状态栏 HTML 常量
def _pill(text, fg, bg, border):
    return (f'<div style="padding:4px 8px;background:{bg};'
            f'border:1px solid {border};border-radius:4px;'
            f'color:{fg};font-weight:600;font-size:13px">{text}</div>')


IDLE_HTML = '<span style="color:green">● 等待输入</span>'
BUSY_HTML = lambda t: f'<span style="color:#b45309">● {t}</span>'
ERROR_HTML = '<span style="color:red">● 出错</span>'
ABORT_HTML = '<span style="color:#b45309">● 已中止</span>'
UP_IDLE = '<span style="color:#888">尚未为本会话上传素材</span>'
UP_LOADING = lambda n: _pill(f'⏳ 正在上传 {n} 个文件（归档+镜像中，大文件需数秒）…', '#8a6d1a', '#fff8e1', '#e7d492')



from runs.agent import ctx_budget
from runs.agent.ctx_budget import UI_TRIM_TOKENS, CONV_MSG_BUDGET_TOKENS, is_context_overflow_error
from runs.h3.session_outputs import session_files as _soc_session_files
from runs.h3.session_outputs import session_videos as _soc_session_videos
REPLY_MAX_TOKENS = ctx_budget.REPLY_MAX_TOKENS  # 兼容旧引用（唯一真值在 ctx_budget）


# 上下文预算（token 口径；模型 ctx=8192，扣除固定开销与回复预算后对话部分
# 约 2.5k token —— 各数值与实测依据见 runs/agent/ctx_budget.py）
MAX_CTX_CHARS = 6000  # 兼容旧引用（已废弃的字符口径）；新逻辑一律走 token 预算
KEEP_TAIL_TURNS = 4   # 兼容旧引用；trim 以 token 预算为准
HEARTBEAT_SEC = 3


def _now() -> str:
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


# ---------------------------------------------------------------- 会话存档
def _cid_file(cid: str) -> Path:
    return CHATS_DIR / f'{cid}.jsonl'


def new_chat_id() -> str:
    CHATS_DIR.mkdir(parents=True, exist_ok=True)
    return datetime.now().strftime('%Y%m%d_%H%M%S') + '_' + uuid.uuid4().hex[:4]


def list_chats() -> list:
    """返回 [(cid, 标题), ...]，按修改时间倒序。标题=首条用户消息摘要。

    注意：st_mtime 是 float，格式化必须经 datetime.fromtimestamp。
    """
    if not CHATS_DIR.is_dir():
        return []
    items = []
    try:
        entries = sorted(CHATS_DIR.glob('*.jsonl'),
                         key=lambda x: x.stat().st_mtime, reverse=True)
    except OSError:
        return []
    for p in entries:
        title = ''
        try:
            for line in p.read_text(encoding='utf-8').splitlines():
                d = json.loads(line)
                if d.get('role') == 'user' and d.get('content'):
                    title = str(d['content']).strip().replace('\n', ' ')[:36]
                    break
        except Exception:  # noqa: BLE001
            title = '(损坏)'
        if not title:
            title = '(空会话)'
        try:
            # 2026-09-08 修复：历史列表强制北京时间（24h 制）——服务器为 UTC 时区，
            # 用 fromtimestamp(本地) 会慢 8 小时（用户反馈长时间未修的老问题）。
            import zoneinfo
            ts = datetime.fromtimestamp(p.stat().st_mtime,
                                        tz=zoneinfo.ZoneInfo('Asia/Shanghai')).strftime('%m-%d %H:%M')
        except Exception:  # noqa: BLE001
            try:
                ts = datetime.fromtimestamp(p.stat().st_mtime).strftime('%m-%d %H:%M')
            except Exception:  # noqa: BLE001
                ts = '--'
        items.append((p.stem, f'{ts} {title}'))
    return items


def load_chat(cid: str) -> list:
    path = _cid_file(cid)
    if not path.exists():
        return []
    msgs = []
    try:
        for line in path.read_text(encoding='utf-8').splitlines():
            d = json.loads(line)
            if d.get('role') in ('user', 'assistant') and d.get('content'):
                msgs.append({'role': d['role'], 'content': d['content']})
    except Exception:  # noqa: BLE001
        pass
    return msgs


def save_chat(cid: str, msgs: list, append_role: str = '', append_content: str = '') -> None:
    """整段重写（简单可靠）；可选追加一条消息。
    book-11：同步写 <cid>.meta.json —— 会话 ↔ run_log 互链（不错失"哪次会话用了哪个日志"）。
    """
    CHATS_DIR.mkdir(parents=True, exist_ok=True)
    path = _cid_file(cid)
    if append_role and append_content:
        msgs = msgs + [{'role': append_role, 'content': append_content}]
    try:
        with open(path, 'w', encoding='utf-8') as f:
            for m in msgs:
                f.write(json.dumps(
                    {'ts': _now(), 'role': m['role'], 'content': m['content']},
                    ensure_ascii=False) + '\n')
        try:
            with open(path.with_suffix('.meta.json'), 'w', encoding='utf-8') as f2:
                json.dump({'run_log': os.environ.get('H3_LOG_FILE', ''),
                           'ts': _now(), 'n_msgs': len(msgs)},
                          f2, ensure_ascii=False)
        except OSError:
            pass
    except OSError:
        pass


def delete_chat(cid: str) -> None:
    try:
        _cid_file(cid).unlink(missing_ok=True)
    except OSError:
        pass


# ---------------------------------------------------------------- 上下文裁剪
def trim_context(msgs: list) -> tuple:
    """把 messages 裁到预算内（token 口径，见 ctx_budget.trim_messages）。

    保留最新轮次（含本轮新提问/“继续”）；预算内尽量保留首条用户消息（旧语义
    “首轮意图”）；发生裁剪时置位返回标志（调用方在最新条附加说明）。

    返回 (裁剪后的列表, 是否发生裁剪)。不改动原列表。
    """
    if not msgs:
        return [], False
    out, dropped = ctx_budget.trim_messages(msgs, UI_TRIM_TOKENS)
    return out, dropped


from runs.agent.toolcall_parse import _parse_tool_calls  # noqa: E402  book-16：qwen3.8 native tool-call


LLM_HTTP = 'http://127.0.0.1:8000/v1/chat/completions'
LLM_MODEL = 'Qwen3.8-27B'


def _http_chat_once(messages: list, tools_schemas: list, timeout: int = 900) -> dict:
    """book-16 自管循环：直连 SGLang OpenAI 端点（tools= 格式触发 qwen3.8 的 <tool_call> 标签）。
    返回 message dict（含 content / function_call / tool_calls）；异常抛 ValueError。
    2026-09-07 超时根治：默认读超时 120→900s（实测长剧本 300 输出 token≈55s、单轮 2-3 分钟）。
    """
    import json as _json
    import urllib.request as _ur
    body = {'model': LLM_MODEL, 'messages': messages,
            'tools': [{'type': 'function', 'function': s} for s in (tools_schemas or [])],
            'max_tokens': REPLY_MAX_TOKENS, 'temperature': 0.2, 'top_p': 0.8,
            'repetition_penalty': 1.05, 'frequency_penalty': 0.05, 'stream': False,
            'chat_template_kwargs': {'enable_thinking': False}}  # book-16 #5：正确开关位置（qwen3 官方）
    req = _ur.Request(LLM_HTTP, data=_json.dumps(body).encode(),
                      headers={'Content-Type': 'application/json'}, method='POST')
    try:
        with _ur.urlopen(req, timeout=timeout) as r:
            d = _json.loads(r.read().decode())
    except _ur.HTTPError as e:
        raw = e.read().decode('utf-8', 'replace')[:500]
        raise ValueError(f'HTTP {e.code}: {raw}') from e
    except Exception as e:  # noqa: BLE001
        raise ValueError(f'{getattr(e, "code", "?")} {str(e)[:160]}') from e
    try:
        return (d.get('choices') or [{}])[0].get('message') or {}
    except Exception as e:  # noqa: BLE001
        raise ValueError('响应解析失败: ' + str(e)[:120]) from e


_TOOL_SCHEMA_CACHE: dict = {}  # key = 子集指纹
# book-17 P2.1.2：按任务能力动态下发子集（最小权限）——仅当用户明确要求工作流改造时才下发 modify_workflow
_WORKFLOW_EDIT_KEYS = ('修改工作流', '改工作流', '工作流改动', '模板修改', '自定义工作流', '新增工作流', 'workflow')


def _wants_workflow_edit(text: str) -> bool:
    if not text:
        return False
    return any(k in text for k in _WORKFLOW_EDIT_KEYS)


def _tool_defs(user_text: str = '') -> list:
    """book-16 自管循环：从 qwen_agent 工具注册表生成 OpenAI functions schema（模块级，可单测）。
    book-17 P2.1.2：按 user_text 动态下发子集（默认不含 modify_workflow，减少幻觉表面积）。"""
    try:
        from runs.agent.scheduler import TOOL_NAMES
    except Exception:
        TOOL_NAMES = []
    subset = sorted(set(TOOL_NAMES) - ({'modify_workflow'} if not _wants_workflow_edit(user_text) else set()))
    key = tuple(subset)
    if key in _TOOL_SCHEMA_CACHE:
        return _TOOL_SCHEMA_CACHE[key]
    out: list = []
    try:
        from qwen_agent.tools import TOOL_REGISTRY
        for name in subset:
            cls = TOOL_REGISTRY.get(name)
            if cls is None:
                continue
            inst = cls()
            fn = getattr(inst, 'function', None)
            if isinstance(fn, dict):
                out.append(dict(fn))
            else:
                out.append({'name': getattr(inst, 'name', name),
                            'description': str(getattr(inst, 'description', ''))[:1500],
                            'parameters': getattr(inst, 'parameters', {})})
        _TOOL_SCHEMA_CACHE[key] = out
    except Exception:  # noqa: BLE001
        # 注册表不可用（Windows 单测环境）→ 回退空集，运行时不拦截真实链路
        out = []
    return out


_TOOL_LIMITS = {'call_comfyui': 1, 'batch_submit': 1, 'list_references': 2,
                'grant_refs': 2, 'run_script': 3, 'read_doc': 2,
                'modify_workflow': 1}  # book-16 频控
_SESSION_GEN_LIMIT = 10  # book-17 P2.3.4：每会话生成类任务上限（待批准项E=10）
_SESSION_GEN_USED: dict = {}  # key=会话 cid（CURRENT_SESSION）
_SESSION_SUBMITS: dict = {}  # book-14 T2b v2#4：会话级同任务指纹→{fingerprint:{pid,ts}}；30 分钟内复用
_SESSION_SUBMIT_WINDOW = 1800  # 秒


def _submit_fp(fname, args) -> str:
    """同任务指纹：stage/res/seconds/images + 提示词归一化前 300 字符（防措辞微变绕过去重）。"""
    import re as _re2
    parts = [str(fname)]
    for k in ('stage', 'resolution', 'seconds', 'images'):
        parts.append(str((args or {}).get(k, '')))
    p = _re2.sub(r'[^\w\u4e00-\u9fff]', '', str((args or {}).get('prompt', '')))[:300]
    parts.append(p)
    return '|'.join(parts)[:520]


# ---------------------------------------------------------------- book-17 P2.2 硬约束
def _tool_schema(name):
    """白名单 + 工具实例 schema。返回 (ok, schema)。未注册/非法名 → ok=False。"""
    try:
        from runs.agent.scheduler import TOOL_NAMES
        if name not in TOOL_NAMES:
            return False, None
        from qwen_agent.tools import TOOL_REGISTRY
        cls = TOOL_REGISTRY.get(name)
        if cls is None:
            return False, None
        inst = cls()
        return True, (getattr(inst, 'parameters', None) or {})
    except Exception:  # noqa: BLE001
        return True, None


def validate_tool_call(name, args, schema=None):
    """book-17 P2.2.1：调用前 schema 校验（白名单/必填/类型/枚举/未知参数）。
    返回 None=通过；字符串=首个错误。纯内置实现（可单测，Windows 无 qwen_agent 也可测 schema 部分）。"""
    if not name or not str(name).strip():
        return '工具名为空'
    ok, sch = _tool_schema(name) if schema is None else (True, schema)
    if not ok:
        return f'工具未注册/不在白名单: {name}'
    if not isinstance(args, dict):
        return f'{name} 参数必须为 JSON 对象'
    if not sch:
        return None
    props = sch.get('properties') or {}
    req = sch.get('required') or []
    for k in req:
        if k not in args:
            return f'缺少必填参数 {k!r}'
    for k, v in args.items():
        p = props.get(k)
        if p is None:
            return f'未知参数 {k!r}（允许: {chr(44).join(sorted(props)) or "无"}）'
        t = p.get('type')
        if t == 'integer' and not isinstance(v, int):
            return f'参数 {k} 应为整数（int），收到 {type(v).__name__}: {v!r}'
        if t == 'boolean' and not isinstance(v, bool):
            return f'参数 {k} 应为布尔（true/false），收到 {type(v).__name__}: {v!r}'
        if t == 'string' and not isinstance(v, str):
            return f'参数 {k} 应为字符串，收到 {type(v).__name__}: {v!r}'
        if t == 'number' and not isinstance(v, (int, float)):
            return f'参数 {k} 应为数值，收到 {type(v).__name__}: {v!r}'
        enum = p.get('enum')
        if enum and v not in enum:
            return f'参数 {k} 取值 {v!r} 不在允许集 {enum}'
    return None


def _parse_and_coerce_args(fname, raw):
    """book-16/17：参数解析 + 按工具 schema 通用 int/bool/number 强转（统一入口）。"""
    args = _parse_tool_args(raw)
    ok, sch = _tool_schema(fname)
    props = (sch or {}).get('properties') or {}
    if isinstance(args, dict):
        for _k, _v in list(args.items()):
            if not isinstance(_v, str):
                continue
            _pt = props.get(_k, {}).get('type')
            _sv = _v.strip()
            if _pt == 'integer' and _sv.lstrip('-').isdigit():
                try:
                    args[_k] = int(_sv)
                except ValueError:
                    pass
            elif _pt == 'boolean' and _sv.lower() in ('true', 'false'):
                args[_k] = _sv.lower() == 'true'
            elif _pt == 'number':
                try:
                    args[_k] = float(_sv)
                except ValueError:
                    pass
    return args


def _parse_tool_args(text) -> dict:
    """工具参数解析（book-16）：兼容 JSON、```围栏、以及 qwen3.8 KV 裸串（stage=t2v, seconds=5）。"""
    if isinstance(text, dict):
        return text
    s = str(text or '').strip()
    if not s:
        return {}
    # 剥代码围栏
    if s.startswith('```'):
        s = s.strip('`')
        if s.startswith('json'):
            s = s[4:]
        s = s.strip()
    # JSON 优先
    try:
        d = json.loads(s)
        return d if isinstance(d, dict) else {}
    except Exception:  # noqa: BLE001
        pass
    # XML 参数（qwen3.8 关闭 thinking 后的工具参数形态）：<parameter=name>value</parameter>…
    import re as _re
    if '<parameter=' in s:
        xout = {}
        for mm in _re.finditer(r'<parameter=([^>]+)>\s*(.*?)\s*</parameter>', s, _re.S):
            xout[mm.group(1).strip()] = mm.group(2).strip()
        if xout:
            return xout
    # 裸 KV：按“引号外逗号”切分
    parts = _re.split(r',(?=(?:[^"]*"[^"]*")*[^"]*$)', s)
    out = {}
    for part in parts:
        if '=' not in part:
            continue
        k, v = part.split('=', 1)
        k = k.strip()
        v = v.strip().strip('\"\'')
        for iv in ('true', 'True'):
            if v == iv:
                v = True
        for iv in ('false', 'False'):
            if v == iv:
                v = False
        try:
            v = int(v) if _re.fullmatch(r'-?\d+', v) else v
        except Exception:  # noqa: BLE001
            pass
        try:
            v = float(v) if _re.fullmatch(r'-?\d+\.\d+', str(v)) else v
        except Exception:  # noqa: BLE001
            pass
        out[k] = v
    return out


def _run_tool(name: str, args) -> str:
    """执行工具（qwen_agent 0.0.34 实例约定）并返回字符串结果（模块级，可单测）。"""
    try:
        from qwen_agent.tools import TOOL_REGISTRY
        cls = TOOL_REGISTRY.get(name)
        if cls is None:
            return f'[错误] 工具未注册: {name}'
        inst = cls()
        args = _parse_and_coerce_args(name, args)  # book-17：统一参数解析+schema 强转
        out = inst.call(args) if args else inst.call({})
        return str(out)
    except Exception as e:  # noqa: BLE001
        return f'[错误] {name} 执行失败: {type(e).__name__}: {e}'


# ---------------------------------------------------------------- 模型回合
def run_turn(history: list, user_text: str, events: 'queue.Queue'):
    """后台线程：新开一个 Assistant 处理当前轮（无状态，历史由外部传入）。"""
    from qwen_agent.agents import Assistant
    from runs.agent.scheduler import LLM_CFG, TOOL_NAMES, get_system_message
    system_message = get_system_message()  # book-12 A4：注册表动态工作流段
    from runs.agent import turn_state
    global _LAST_TOOL  # P0 受控续接：模块级（run_turn 写入 / send 读取）
    _LAST_TOOL = ('', '')
    global _pending_batch_id
    turn_state.begin_turn(batch_id=_pending_batch_id)
    _pending_batch_id = None

    # book-16：自动续接时 user_text=None → 不得追加 content=None 的 user 消息（SGLang tools 模式 400）
    _payload_src = list(history)
    if user_text:
        _payload_src.append({'role': 'user', 'content': user_text})
    trimmed, dropped = trim_context(_payload_src)
    _retried = False  # 2026-09-07 超时自动重试一次标记
    payload = dedupe_messages(list(trimmed))  # 连续重复消息剔除（污染防御）
    try:
        from h3 import logutil
        logutil.ensure_run_log(PROJECT_ROOT, 'agent-llm')
        logutil.log_event('agent-llm', _llm_input_preview(payload, 'send'))
    except Exception:  # noqa: BLE001
        pass
    if dropped:
        note = ('\n\n[上下文提示] 较早的对话轮次已按 token 预算自动压缩'
                '（最新轮次与任务状态仍在）。如需回顾可让我重述。')
        payload[-1] = {'role': 'user',
                       'content': str(payload[-1].get('content', '')) + note}

    llm = dict(LLM_CFG)
    # 回复上限 + qwen_agent 输入硬预算（实测依据见 ctx_budget.py）：
    # 截断层 available = max_input_tokens − tokens(system)，保证每次调用
    # （含回合内工具往返）服务端总输入 ≤ 6144，与 2048 回复合计不越 ctx=8192。
    max_input, overhead = ctx_budget.request_budgets(system_message)
    llm['generate_cfg'] = {**(llm.get('generate_cfg') or {}),
                           'max_tokens': REPLY_MAX_TOKENS,
                           'max_input_tokens': max_input}
    # 内存协同：模型不在跑时先自动唤醒（期间界面心跳继续显示进度）
    try:
        from runs.agent import llm_mem as lmem
        lmem.ensure_llm_up(
            timeout_s=900,
            progress=lambda s: events.put(
                {'kind': 'phase',
                 'text': f'⏳ 正在唤醒本地模型…（{s}s；仅首次或让位后需要）'}))
    except Exception as e:  # noqa: BLE001
        events.put({'kind': 'error', 'text': f'模型唤醒失败: {e}'})
        return
    events.put({'kind': 'phase', 'text': '🔶 模型就绪：推理/工具调度中（长任务期间此状态会持续跳动，请勿重复发送）'})

    def _one_run(msgs):
        """book-16 根治：直连 SGLang（tools= 格式）+ 自管工具循环（≤6 轮、每轮审计、复读即断）。"""
        cur = [{'role': 'system', 'content': system_message}] + dedupe_messages(list(msgs))  # book-16：自管循环须显式带 system
        final = ''
        acc = 0
        _last = ['']
        _tool_call_cache: dict = {}  # book-16：本轮同参数去重
        _tool_count: dict = {}  # book-16：本轮频控计数
        _tool_errs: list = []  # book-16：本轮工具失败结果（如实兜底）
        _fix_budget: dict = {}  # book-17 P2.2.3：参数校验失败-修复重试次数限定（≤3）
        _tkey_fail: dict = {}  # book-17 P2.3.3：同指纹失败快速熔断
        _deadline = time.time() + 900  # book-17 P2.3.3：轮级总超时
        for rnd in range(6):
            if time.time() > _deadline:
                _m = '本轮处理超时（900s），已终止；可点"继续"或重试。'
                events.put({'kind': 'error', 'text': _m})
                return _m
            try:
                msg = _http_chat_once(cur, _tool_defs(user_text))
            except Exception as e:  # noqa: BLE001
                # 2026-09-07 超时安全网：长提示偶发超时→自动重试一次再交还界面
                if not _retried and any(k in str(e).lower() for k in ('timed out', 'readtimeout', 'timeout')):
                    _retried = True
                    try:
                        msg = _http_chat_once(cur, _tool_defs(user_text))
                    except Exception as e2:  # noqa: BLE001
                        events.put({'kind': 'error', 'text': f'[超时] {type(e2).__name__}: {e2}'})
                        return final
                else:
                    events.put({'kind': 'error', 'text': f'{type(e).__name__}: {e}'})
                    return final
            msgs_out = [msg]
            text = _content_text(msg.get('content') if isinstance(msg, dict) else '')
            fc = (msg.get('function_call') if isinstance(msg, dict) else None) or {}
            raw_text = text
            # book-16：qwen3.8 native tool-call（<tool_call> 标签，SGLang 原样吐出）解析
            tag_calls, clean_text = _parse_tool_calls(text)
            if tag_calls or fc:
                if tag_calls:
                    fname = tag_calls[0][0]
                    fc = {'name': fname, 'arguments': tag_calls[0][1]}
                    text = clean_text
                else:
                    fname = str(fc.get('name') or '')
                if text and text != raw_text:
                    final = text
                elif text:
                    final = text
                if text:
                    if text == _last[0]:
                        delta = ''
                    elif text.startswith(_last[0]) and len(text) > len(_last[0]):
                        delta = text[len(_last[0]):]
                    else:
                        delta = text
                    _last[0] = text
                    acc += len(delta)
                    if acc > MAX_OUTPUT_CHARS:
                        events.put({'kind': 'error',
                                    'text': '输出异常超限（模型可能复读，已中断展示；请重试或换一种说法）'})
                        return final
                    if delta:
                        events.put({'kind': 'chunk', 'text': delta})
                if fname:
                    events.put({'kind': 'tool', 'text': fname[:36]})
                    # book-17 P2.2.1/P2.2.3：白名单+Schema 前置校验；失败回传具体错误，修复重试 ≤3 次
                    _p_args = _parse_and_coerce_args(fname, fc.get('arguments'))
                    _verr = validate_tool_call(fname, _p_args)
                    if _verr:
                        _tool_errs.append((fname, '校验拦截: ' + _verr[:70]))
                        _fix_budget[fname] = _fix_budget.get(fname, 0) + 1
                        if _fix_budget[fname] > 3:
                            _fin = (f'{fname} 参数校验连续 4 次未通过（最近: {_verr[:120]}）；'
                                    '已终止本轮，请调整请求后再试。')
                            events.put({'kind': 'error', 'text': _fin})
                            return _fin
                        cur = cur + [{'role': 'assistant', 'content': (clean_text or text or '')[:6000]},
                                     {'role': 'user',
                                      'content': f'[参数校验失败] {fname}: {_verr}。请修正参数后重新调用（本次未执行，不计次数）。'}]
                        continue
                    # book-16：同参数去重 + 频控（模型反复提交 → 只执行一次；防重复生成/六连提交）
                    tkey = fname + '|' + json.dumps(_p_args, ensure_ascii=False, sort_keys=True)
                    if tkey in _tool_call_cache:
                        out = _tool_call_cache[tkey]
                        # book-17 P2.3.3：同指纹失败（缓存错误被反复重试）→ Fast-Fail
                        if (out.startswith('[错误]') or out.startswith('提交失败') or out.startswith('错误：')):
                            _tkey_fail[tkey] = _tkey_fail.get(tkey, 0) + 1
                            if _tkey_fail[tkey] >= 2:
                                _f2 = f'{fname} 同一请求已持续失败（{out[:80]}），停止重复尝试；请调整参数后重试。'
                                events.put({'kind': 'error', 'text': _f2})
                                return _f2
                        events.put({'kind': 'tool', 'text': f'{fname[:28]}（已执行过，结果复用）'})
                    elif _tool_count.get(fname, 0) >= _TOOL_LIMITS.get(fname, 4):
                        out = f'[频控] {fname} 本轮已执行 {_tool_count.get(fname)} 次，跳过重复调用（结果以第一次为准）'
                        events.put({'kind': 'tool', 'text': f'{fname[:28]}（频控跳过）'})
                    elif fname in ('call_comfyui', 'batch_submit') and not _p_args.get('dry_run') and _SESSION_GEN_USED.get(str(getattr(__import__('runs.agent.tools', fromlist=['CURRENT_SESSION']), 'CURRENT_SESSION', '')), 0) >= _SESSION_GEN_LIMIT:
                        out = f'[限流] 本会话生成任务已达 {_SESSION_GEN_LIMIT} 次上限（book-17 P2.3.4）；请新开会话再提交。'
                        events.put({'kind': 'tool', 'text': f'{fname[:28]}（会话限流）'})
                    else:
                        # book-14 T2b v2#4：会话级同任务去重（30 分钟内同指纹 → 复用，不重复提交）
                        _fp = ''
                        if fname in ('call_comfyui', 'batch_submit') and not _p_args.get('dry_run'):
                            _fp = _submit_fp(fname, _p_args)
                            try:
                                from runs.agent import tools as _t
                                _sg = str(getattr(_t, 'CURRENT_SESSION', ''))
                            except Exception:  # noqa: BLE001
                                _sg = ''
                            import time as _time
                            _rec = _SESSION_SUBMITS.get(_sg, {}).get(_fp)
                            if _rec and (_time.time() - _rec['ts']) < _SESSION_SUBMIT_WINDOW:
                                out = (f"[复用] 本会话 30 分钟内已提交同任务（prompt_id={_rec['pid'] or '?'}），"
                                       "未重复提交；可用 run_script(h3_submit.py) 查询/续传取回。")
                                events.put({'kind': 'tool', 'text': f'{fname[:28]}（同任务复用，未新提交）'})
                                cur = cur + [{'role': 'assistant', 'content': (clean_text or text or '')[:6000]},
                                             {'role': 'user', 'content': f'[工具 {fname} 返回]\n{out}'}]
                                cur.append({'role': 'user', 'content': '（任务已在队列中，直接查询取回即可，不要再提交）'})
                                continue
                        out = _run_tool(fname, fc.get('arguments'))
                        _tool_count[fname] = _tool_count.get(fname, 0) + 1
                        _LAST_TOOL = (fname, str(out or '')[:180])  # P0 受控续接：供 should_continue 与续接消息（进度摘要）
                        _tool_call_cache[tkey] = out
                        if out.startswith('[错误]') or out.startswith('提交失败') or out.startswith('错误：'):
                            # 现场修缮（2026-09-06）：失败不占用频控名额——模型修正参数后重试合法
                            # （绝对 1 次/轮曾把"失败→修正→重试"拦死，导致多段分镜批量提交中断）
                            _tool_count[fname] = max(0, _tool_count.get(fname, 0) - 1)
                            _tool_errs.append((fname, out[:90]))
                            _fn = sum(1 for _e in _tool_errs if _e[0] == fname)
                            if _fn >= 3:
                                _f3 = f'{fname} 连续 {_fn} 次失败（最近: {out[:90]}），本轮已熔断；请调整后重试。'
                                events.put({'kind': 'error', 'text': _f3})
                                return _f3
                        else:
                            try:
                                if fname in ('call_comfyui', 'batch_submit') and not _p_args.get('dry_run') and 'TASK_SUBMITTED' in out:
                                    from runs.agent import tools as _t
                                    _sg = str(getattr(_t, 'CURRENT_SESSION', ''))
                                    _SESSION_GEN_USED[_sg] = _SESSION_GEN_USED.get(_sg, 0) + 1
                                    import time as _time
                                    _pids = extract_prompt_ids(out) or ['']
                                    _SESSION_SUBMITS.setdefault(_sg, {})[_fp] = {'pid': _pids[0], 'ts': _time.time()}
                            except Exception:  # noqa: BLE001
                                pass
                        events.put({'kind': 'tool', 'text': f'{fname[:28]} 完成'})
                    # book-16：回填用【清洗后文本】(无 <tool_call> 标签，规避 SGLang tools 模式序列校验 400)
                    # 且结果以 user 视角注入（规避 function/tool role 校验）
                    cur = cur + [{'role': 'assistant', 'content': (clean_text or text or '')[:6000]},
                                 {'role': 'user', 'content': f'[工具 {fname} 返回]\\n{out}'}]
                    # book-16：促收尾（模型常继续重试；明确提示完成任务后直接总结）
                    cur.append({'role': 'user', 'content': '（若上述结果已满足用户需求，请直接给中文总结收尾，不要再调用工具）'})
                    continue
                continue
            if text:
                if text == _last[0]:
                    delta = ''
                elif text.startswith(_last[0]) and len(text) > len(_last[0]):
                    delta = text[len(_last[0]):]
                else:
                    delta = text
                _last[0] = text
                acc += len(delta)
                if acc > MAX_OUTPUT_CHARS:
                    events.put({'kind': 'error',
                                'text': '输出异常超限（模型可能复读，已中断展示；请重试或换一种说法）'})
                    return final
                final = text
                if delta:
                    events.put({'kind': 'chunk', 'text': delta})
            break
        # book-16：工具轮后无总结文本 → 兜底补状态行（防 UI“（模型未返回内容）”）
        if not final and _tool_count:
            ok_exec = sum(_tool_count.values()) - len(_tool_errs)
            if _tool_errs and ok_exec <= 0:
                final = ('本轮工具执行未成功：' + '；'.join('%s: %s' % (n, e[:70])
                                                          for n, e in _tool_errs[:3])
                         + '。请根据错误信息调整请求。')
            else:
                final = ('任务已完成：本轮共调用工具 %d 次（%s）。结果见“工具执行”状态条；'
                         '可点“继续”查询结果或换一种说法。' % (sum(_tool_count.values()),
                            ', '.join('%s×%d' % (k, v) for k, v in _tool_count.items())))
            events.put({'kind': 'chunk', 'text': final})
        return final

    try:
        final = _one_run(payload)
        events.put({'kind': 'done', 'text': final})
    except Exception as e:  # noqa: BLE001
        # 2026-09-07 超时根治：长剧本单轮 2-3 分钟，客户端超时后自动重试一次（不打扰用户）
        _msg = f'{type(e).__name__}: {e}' if False else str(e)
        if not _retried and isinstance(e, Exception) and any(
                k in str(e).lower() for k in ('timed out', 'readtimeout', 'apitimeouterror', 'connect timeout')):
            _retried = True
            note = '\n\n[超时重试] 上一请求模型响应超时（长提示较慢），已自动重试一次；请稍候。'
            try:
                last = dict(payload[-1])
                last['content'] = str(last.get('content', '')) + note
                final = _one_run([*payload[:-1], last])
                events.put({'kind': 'done', 'text': final})
                return
            except Exception:  # noqa: BLE001
                events.put({'kind': 'error',
                            'text': '[模型响应超时] 已自动重试仍超时：请点"继续"重试，或换更简洁的说法；连续出现请反馈'})
                return
        # 服务端仍报“超上下文”（如本地计数偏差/超长单条）：压缩到只剩最新
        # 消息重试一次；仍失败则把可读错误交还界面。
        if is_context_overflow_error(e) and len(payload) > 1:
            try:
                note = ('\n\n[上下文提示] 历史与本次内容超出模型上下文（8192），'
                        '已自动压缩到仅保留最新消息重试；过长内容请分轮提交。')
                last = dict(payload[-1])
                last['content'] = str(last.get('content', '')) + note
                final = _one_run([last])
                events.put({'kind': 'done', 'text': final})
                return
            except Exception as e2:  # noqa: BLE001
                events.put({'kind': 'error',
                            'text': f'[上下文过载] {type(e2).__name__}: {e2}'})
                return
        events.put({'kind': 'error', 'text': f'{type(e).__name__}: {e}'})


def dedupe_messages(msgs: list) -> list:
    """去掉连续同 role+content 的重复消息（污染防御；保留跨类型顺序）。"""
    out = []
    for m in msgs:
        sig = (m.get('role'), str(m.get('content') or ''))
        if out and sig == (out[-1].get('role'), str(out[-1].get('content') or '')):
            continue
        out.append(m)
    return out


def _llm_input_preview(payload: list, tag: str) -> str:
    """发给模型的输入摘要（book-13 故障定位：消息数/各角色长度/首尾预览）。"""
    try:
        parts = []
        for m in payload:
            c = str(m.get('content') or '')
            parts.append(f"{m.get('role')}:{len(c)}")
        head = str(payload[0].get('content') or '')[:80] if payload else ''
        return f"{tag} msgs={len(payload)} roles=[{','.join(parts)}] head={head!r}"
    except Exception:  # noqa: BLE001
        return f"{tag} preview-failed"


def _dup_text(text: str, last_text: str) -> bool:
    """book-13 防复读：新块与已有内容尾部高度重复（前 60 字符一致或完全相同）→ 丢弃。"""
    t = (text or "").strip()
    if not t:
        return False
    tail = (last_text or "").strip()
    if not tail:
        return False
    if t in tail or tail.endswith(t[:60]):
        return True
    return False


MAX_OUTPUT_CHARS = 30000  # 单轮累计 assistant 输出上限（模型复读/异常保护）


def _content_text(content) -> str:
    """qwen_agent content 字段兼容：str 或 [{'text':...}, ...] 或 None。"""
    if content is None:
        return ''
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for c in content:
            if isinstance(c, str):
                parts.append(c)
            elif isinstance(c, dict):
                parts.append(str(c.get('text') or c.get('content') or ''))
        return ''.join(parts)
    return str(content)



# ---------------------------------------------------------------- 素材上传入口
def _comfy_input_dir() -> Path:
    """ComfyUI input 目录（agent 跑在 spark 上，取本机路径）。"""
    comfy = '~/ai/ComfyUI'
    try:
        env = json.loads((PROJECT_ROOT / 'config' / 'environment.json')
                         .read_text(encoding='utf-8-sig'))
        comfy = env.get('remote_comfyui_dir') or comfy
    except Exception:  # noqa: BLE001
        pass
    return Path(comfy.replace('~', str(Path.home()))) / 'input'


_LOG_MTIME = -1.0
_SEEN_SHA = set()
_current_cid = ''  # book：当前会话 cid（_auto_new/_new/_load 维护；send 兜底，防止"发消息触发新建会话"）
_LAST_TOOL = ('', '')  # P0 受控续接：最后工具（名, 摘要）——模块级（run_turn 写入 / send 读取）


def _known_shas() -> set:
    """读取 log.jsonl 的 sha 集合（带 mtime 缓存，避免每次上传全量重读）。"""
    global _LOG_MTIME, _SEEN_SHA
    try:
        mt = UPLOADS_LOG.stat().st_mtime
    except OSError:
        return set()
    if mt == _LOG_MTIME:
        return set(_SEEN_SHA)
    seen = set()
    try:
        for line in UPLOADS_LOG.read_text(encoding='utf-8').splitlines():
            try:
                seen.add(json.loads(line).get('sha'))
            except Exception:  # noqa: BLE001
                continue
    except OSError:
        return set()
    _LOG_MTIME = mt
    _SEEN_SHA = seen
    return set(seen)


def _make_thumb(src: Path, sha: str):
    """在项目内 logs/agent_chats/thumbs/ 生成 128px 缩略图（预览走缩略图，
    避免整张原图经 SSH 隧道传输导致延迟）。"""
    try:
        from PIL import Image
        THUMBS_DIR.mkdir(parents=True, exist_ok=True)
        out = THUMBS_DIR / f'{sha}.jpg'
        if out.exists():
            return out
        im = Image.open(src)
        im.thumbnail((128, 128))
        im.convert('RGB').save(out, 'JPEG', quality=60)
        return out
    except Exception:  # noqa: BLE001  Pillow 不可用时退回原图
        return None


def _to_path(raw) -> Path:
    """兼容各种上传事件值：str / os.PathLike / dict{path|name} / FileData 等对象。"""
    if isinstance(raw, dict):
        raw = raw.get('path') or raw.get('name') or raw.get('orig_name')
    elif not isinstance(raw, (str, Path)):
        raw = (getattr(raw, 'path', None) or getattr(raw, 'name', None)
                or getattr(raw, 'orig_name', None))
    return Path(str(raw)).expanduser() if raw else Path('')


def _session_pool_count(cid: str) -> int:
    """本会话素材池条目数（按 log.jsonl 中该 cid 的 sha 去重计数）。"""
    try:
        seen = set()
        for line in UPLOADS_LOG.read_text(encoding='utf-8').splitlines():
            try:
                d = json.loads(line)
            except Exception:  # noqa: BLE001
                continue
            if str(d.get('cid') or '') == cid and d.get('sha'):
                seen.add(d['sha'])
        return len(seen)
    except OSError:
        return 0


def ingest_upload(paths, cid='') -> tuple:
    """把界面/上传文件收进素材池（与 upload_watch 同语义）：

    - 任意类型 → 归档 uploads/YYYYMMDD/<sha8>_<原名>（sha 去重）+ log.jsonl 流水；
    - 图片额外镜像到 ComfyUI input/user_uploads/<原名>（refimage 立即可见——它主动递归扫 user_uploads；LoadImage 不可见——仅认 input/ 根目录文件，须经 /upload/image 上传后由 API 返回名绑定）。
    - 图片类先经 mediacheck 校验，无效图片跳过归档和镜像。
    返回 (给用户的中文摘要, 图片预览路径列表, 无效文件详情列表, batch_id)。
    """
    from runs.h3 import mediacheck
    if isinstance(paths, (str, Path)):
        paths = [paths]
    input_mirror = _comfy_input_dir() / 'user_uploads'
    added = dup = err = 0
    kinds = []
    seen = _known_shas()
    previews = []
    added_names: list = []
    dup_names: list = []
    invalid_details = []
    batch_id = 'b_' + secrets.token_hex(4)
    for raw in paths or []:
        p = _to_path(raw)
        if not p or not p.is_file():
            err += 1
            continue
        try:
            data = p.read_bytes()
        except OSError:
            err += 1
            continue
        sha = hashlib.sha256(data).hexdigest()[:16]
        ext = p.suffix.lower()
        kind = 'video' if ext in VID_EXT else ('image' if ext in IMG_EXT else 'other')
        kinds.append(kind)
        if kind == 'image':
            ok, reason = mediacheck.check_image_bytes(data)
            if not ok:
                invalid_details.append((p.name, reason))
                continue
        if sha not in seen:
            day = datetime.now().strftime('%Y%m%d')
            dst_dir = UPLOADS_DIR / day
            dst_dir.mkdir(parents=True, exist_ok=True)
            dst = dst_dir / f'{sha[:8]}_{p.name}'
            try:
                shutil.copy2(p, dst)
                with open(UPLOADS_LOG, 'a', encoding='utf-8') as f:
                    f.write(json.dumps({'ts': _now(), 'sha': sha, 'src': str(p),
                                        'archived': str(dst), 'kind': kind,
                                        'batch_id': batch_id, 'cid': cid},
                                       ensure_ascii=False) + '\n')
                seen.add(sha)
                added += 1
                added_names.append(p.name)
            except OSError:
                err += 1
                continue
        else:
            # book-05 修复：重复素材也要登记「当前会话归属」（同一图可属于多个会话），
            # 否则会话过滤看不到"重传"的素材（用户反馈：5 张重复图 → 当前会话暂无）
            try:
                with open(UPLOADS_LOG, 'a', encoding='utf-8') as f:
                    f.write(json.dumps({'ts': _now(), 'sha': sha, 'src': str(p),
                                        'archived': '', 'kind': kind,
                                        'batch_id': batch_id, 'cid': cid,
                                        'dup': True},
                                       ensure_ascii=False) + '\n')
            except OSError:
                pass
            dup += 1
        if kind == 'image':
            try:
                input_mirror.mkdir(parents=True, exist_ok=True)
                # book-11 bugfix：镜像名带 sha8 前缀——同名不同图不再互相覆盖
                # （旧镜像为原名，仍可被 _resolve_input_image 递归命中，兼容）
                mir_name = f'{sha[:8]}_{p.name}'
                _mir = input_mirror / mir_name
                if not _mir.exists():  # 现场故障修复：dup 素材不再重复镜像（重复上传事件的 I/O 与混乱源）
                    shutil.copy2(p, _mir)
            except OSError:
                err += 1
            # book-13 S14：ingest 不再生成缩略图（耗时步骤移到 _upload 分段状态内），返回 (源文件, sha)
            previews.append((str(p), sha))
    parts = []
    if added:
        _names = '、'.join(added_names[:8]) + ('…' if len(added_names) > 8 else '')
        parts.append(f'✅ 已收录 {added} 个素材：{_names}（本会话专属）')
    if dup:
        _dn = '、'.join(dup_names[:4]) + ('…' if len(dup_names) > 4 else '')
        if added:
            parts.append(f'⏩ {dup} 个重复已跳过（已在池中）：{_dn}')
        else:
            # book-16：文案含本会话池总数（防“只有 1 个”误解；实际池=历史+本次）
            parts.append(f'⏩ {dup} 个素材已在本会话池中（可直接使用）')
            _n = _session_pool_count(cid)
            if _n > 1:
                parts[-1] += f'——本会话素材池现有 {_n} 项（含此前上传）'
    if invalid_details:
        detail_str = '，'.join(f'{name}（{reason}）' for name, reason in invalid_details)
        parts.append(f'🚫 {len(invalid_details)} 个无效：{detail_str}')
    if err:
        parts.append(f'❌ {err} 项处理失败')
    if not parts:
        parts.append('⚠️ 未收到有效文件')
    return ' · '.join(parts), previews, invalid_details, batch_id



def _caption_for(cid: str) -> str:
    """S1：gallery 条目 caption——会话来历 + 已用/可用（本会话重建的预览=池内素材=已用）。"""
    return f'会话 {cid} · 已用'


def _pool_update(cid: str):
    """发送后刷新预览池（本会话 + 有效共享授权），S12 可见性即时化。"""
    import gradio as _gr
    try:
        return _gr.update(value=_previews_for_cid(cid) + _shared_for_cid(cid))
    except Exception:  # noqa: BLE001
        return _gr.update()


def _results_update(cid: str):
    """§15d 会话结果区刷新：gr.Video 预览最新成片 + gr.File 全部产物下载；空态提示。

    与 _pool_update 同模式：每个 send yield / 会话加载时调用（cid 为会话 id）。
    """
    import gradio as _gr
    try:
        vids = _soc_session_videos(Path(PROJECT_ROOT), cid)
        if not vids:
            return (_gr.update(value=None, label='本轮结果视频（暂无结果）'),
                    _gr.update(value=None, label='本轮结果文件（暂无）'))
        files = _soc_session_files(Path(PROJECT_ROOT), cid)
        return (_gr.update(value=str(vids[0]), label='本轮结果视频（预览 · 最新）'),
                _gr.update(value=[str(p) for p in files],
                           label='本轮结果文件（下载）'))
    except Exception:  # noqa: BLE001
        return _gr.update(), _gr.update()


def _shared_for_cid(cid: str) -> list:
    """S12：当前会话有效共享授权（grants 文件 src==本会话、未过期未用）的目标会话预览（UI 预览池可见性补齐）。"""
    out: list = []
    try:
        import json as _ij
        for fn in os.listdir(str(CHATS_DIR)):
            if not fn.endswith('.grants.json'):
                continue
            try:
                g = _ij.loads((CHATS_DIR / fn).read_text(encoding='utf-8'))
            except Exception:  # noqa: BLE001
                continue
            if str(g.get('src_cid') or '') != str(cid):
                continue
            if g.get('used'):
                continue
            exp = g.get('expires')
            if exp and time.time() > float(exp):
                continue
            tgt = str(g.get('target_cid') or '')
            if not tgt:
                continue
            for p, cap in _previews_for_cid(tgt):
                if all(p != x[0] for x in out):
                    out.append((p, f'共享授权·会话 {tgt}'))
    except OSError:
        pass
    return out


def _previews_for_cid(cid: str) -> list:
    """book-13 P2#9b：按上传归档日志重建某会话的图片预览列表（加载历史会话时用）。

    S1：输出统一为 [(path, caption), ...]——caption 标注会话来历+可用性
    （可用性=本地归档/缩略图存在性判定；丢失条目隐藏，素材以 list_references 为准）。
    """
    try:
        import json as _j
        out: list = []
        seen: set = set()
        cap = _caption_for(cid)
        with open(UPLOADS_LOG, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = _j.loads(line)
                except Exception:  # noqa: BLE001
                    continue
                if str(rec.get('cid') or '') != str(cid) or rec.get('kind') != 'image':
                    continue
                sha = str(rec.get('sha') or '')
                if not sha or sha in seen:
                    continue
                seen.add(sha)
                thumb = THUMBS_DIR / f'{sha}.jpg'
                if thumb.is_file():
                    out.append((str(thumb), cap))
                    continue
                arch = str(rec.get('archived') or '')
                if arch and Path(arch).is_file():
                    # 现场修缮（2026-09-06）：不再回退归档路径——归档/缓存路径进入组件值会被
                    # Gradio 当作"非用户上传对象"拒绝（InvalidPathError → 事件链断 → 等待输入）；
                    # 缺失缩略图时按需生成，失败则隐藏该预览（素材仍以 list_references 为准）
                    th = _make_thumb(Path(arch), sha)
                    if th:
                        out.append((str(th), cap))
        return out
    except Exception:  # noqa: BLE001
        return []


# ---------------------------------------------------------------- 程序级状态源
def llm_state_text() -> str:
    try:
        from runs.agent import llm_mem as _lm
        return '运行中' if _lm.is_up(1.5) else '暂歇'
    except Exception:  # noqa: BLE001
        return '未知'


def tail_run_log(max_chars: int = 120) -> str:
    """最新 logs/run_*.log 的末行（引擎真实进展，程序级事实，不依赖模型自述）。"""
    try:
        env = os.environ.get('H3_LOG_FILE', '').strip()
        if env and os.path.isfile(env):
            files = [Path(env)]  # book-11：优先当前任务日志（会话↔任务精准定位）
        else:
            logs = (Path(PROJECT_ROOT) / 'logs')
            files = sorted(logs.glob('run_*.log'),
                           key=lambda p: p.stat().st_mtime, reverse=True) if logs.is_dir() else []
        if not files:
            return ''
        data = files[0].read_bytes()
        return data[-max_chars:].decode('utf-8', errors='replace').strip().splitlines()[-1]
    except Exception:  # noqa: BLE001
        return ''
def _prewarm_on_load():
    """页面加载后预热（daemon 线程中调用）。"""
    try:
        from runs.agent import doc_state
        doc_state.prewarm()
    except Exception:
        pass


# ---------------------------------------------------------------- Gradio 界面
def _choices() -> list:
    return [(label, cid) for cid, label in list_chats()]


# book-04：自动续接判别（截断嫌疑 vs 自然停 vs 任务意图；寒暄不续接）
_TASK_KEYWORDS = ('视频', '生成', '图片', '转场', '参考', '图生', '文生', '素材',
                  '上传', '制作', '创建', '拼接', '角色', '场景', '动画', '短片')
_TERMINAL = ('。', '！', '？', '!', '?', '.', '"', '”', '）', ')', '」', '>')


def should_continue(user_text, final_text, prompt_ids, last_tool: str = '', last_tool_hint: str = '') -> bool:
    """判别是否自动续接（book-04）。

    已有 prompt_id / 无输出 / 熔断标记 → 不续（交由监控/用户）；
    P0 目标驱动：提交类工具后按结果继续（成功→查询取片；失败→修正重试；批量成功后由监控接管→不续）
    截断嫌疑（超长且无终止符号结尾）→ 续；
    用户意图含生成类关键词（模型尚未提交）→ 续一次推进；
    其余（寒暄/已完整回答）→ 不续（修「你好续接两次」）。
    """
    # P0 受控续接：提交类工具结果驱动（在 prompt_ids 一刀切之前判——单段成功需要续查取片）
    if last_tool in ('call_comfyui', 'batch_submit') and last_tool_hint:
        if ('错误' in last_tool_hint or '失败' in last_tool_hint or '找不到' in last_tool_hint
                or '被拒' in last_tool_hint or '校验失败' in last_tool_hint):
            return True  # 失败修正重试（失败不占频控）——否则批处理失败后模型无法继续
        if last_tool == 'call_comfyui' and ('TASK_SUBMITTED' in last_tool_hint or 'prompt_id' in last_tool_hint):
            return True  # 单段已提交：续接查询进度/取片汇报（工作到完成）
        if last_tool == 'batch_submit' and 'BATCH_MANIFEST' in last_tool_hint:
            return False  # 批量已提交：监控接管，不再空转
    if prompt_ids:
        return False
    if not final_text:
        return False
    if any(marker in final_text for marker in ('⛔', '不可恢复', '熔断')):
        return False
    tail = final_text.rstrip()
    if len(final_text) > 1200 and not tail.endswith(_TERMINAL):
        return True  # 疑似被 max_tokens 截断
    # book-16：征询式结尾（问号/“即可/吗/尽快说”等）→ 自然停，不续接（防“列素材”误续）
    if tail.endswith('？') or tail.endswith('?') or '即可' in tail[-20:] or tail.endswith('吗'):
        return False
    if any(k in (user_text or '') for k in _TASK_KEYWORDS):
        return True
    return False


def _err_hint(t: str) -> str:
    """错误分类 + 解决建议（book-02）。"""
    t = t or ''
    if 'maximum context length' in t or 'ModelServiceError' in t:
        return '上下文超限：请精简对话或点"继续"分轮；已自动压缩一次'
    if 'one system message' in t.lower() or 'system message' in t.lower():
        return '消息格式错误：自动续接曾注入重复 system 消息，已修复为 user 角色；若再现请反馈'
    if 'ModuleNotFoundError' in t or 'No module named' in t:
        return '脚本导入异常：已记录待修；可重试一次'
    if '⛔' in t or '熔断' in t or '不可恢复' in t:
        return '已连续失败熔断：请更换素材或稍后再试，勿连续重试'
    if 'TimeoutExpired' in t or '超时' in t:
        return '提交/轮询卡顿：任务可能在后台运行，用"继续"/"取片"确认，勿重复提交'
    if 'ReadTimeout' in t or 'timed out' in t.lower():
        return '模型响应超时（可能是异常长/重复输出）：请点"继续"重试，或换更简洁的说法；连续出现请反馈'
    if 'ModelServiceError' in t or 'error code: 400' in t.lower():
        return '接口 400：消息/参数格式错误（详见日志）；自动续接 system 冲突已修复，若重复出现请反馈'
    if 'comfyui' in t.lower() or '8188' in t or 'connection' in t.lower():
        return '生成服务未就绪：请人工检查 spark 的 ComfyUI（勿自行重启）'
    return '请按上述信息排查；可点"继续"重试或查看日志'


def run_app(port: int = 7860, share: bool = False) -> None:
    import gradio as gr

    def fmt_msgs(msgs):
        return [{'role': m['role'], 'content': str(m.get('content', ''))}
                for m in msgs if m.get('role') in ('user', 'assistant')]

    def _send_impl(chat_hist, cid, user_text):
        MAX_AUTO_CONTINUE = 5  # P0：2→5（任务延续需要；超出即停提示，防无限空转）
        from runs.agent.session_state import (
            get_stop_event, clear_tasks, add_tasks, increment_turn_id, check_turn_valid
        )

        MAX_AUTO_CONTINUE = 5  # P0 受控续接：2→5（目标驱动后需要；超出即停提示，防无限空转）
        ABORT_MARKERS = ('⛔', '不可恢复', '熔断')

        user_text = (user_text or '').strip()
        if not _active_turn.acquire(blocking=False):
            yield (fmt_msgs(chat_hist or []),
                   BUSY_HTML('上一轮仍在处理中，本次点击已忽略'),
                   '上一轮仍在处理中；请等状态变绿或点"停止当前任务"。', gr.update(), cid,
                   chat_hist or [], _pool_update(cid), gr.update())
            return
        try:
            global _stop_requested
            _stop_requested = threading.Event()

            if _upload_in_progress:
                yield (fmt_msgs(chat_hist or []),
                       BUSY_HTML('上传尚未完成，请稍候再发送'),
                       '⏳ 素材上传进行中，请等待上传完成后再发送。', gr.update(), cid,
                       chat_hist or [], _pool_update(cid), gr.update())
                return

            if not user_text:
                yield (fmt_msgs(chat_hist or []), IDLE_HTML, '请输入内容。', gr.update(), cid,
                       chat_hist or [], _pool_update(cid), gr.update())
                return

            if not cid:
                cid = _current_cid or new_chat_id()  # 优先当前会话，避免与 demo.load/新建竞争而误建新会话

            try:
                from runs.agent import tools as _tools
                _tools.CURRENT_SESSION = cid  # book-05：素材工具默认隔离到本会话
            except Exception:  # noqa: BLE001
                pass

            msgs = list(chat_hist or [])
            stop_event = get_stop_event(cid)
            stop_event.clear()
            clear_tasks(cid)
            current_turn_id = increment_turn_id(cid)
            try:  # book-19 S12：当前轮上下文注入（grant_refs 授权校验/轮末失效）
                from runs.agent import tools as _tools_t
                _tools_t.CURRENT_TURN_ID = current_turn_id
                _tools_t.CURRENT_USER_TEXT = user_text
            except Exception:  # noqa: BLE001
                pass

            ev = queue.Queue()
            stop_hb = threading.Event()
            clear_box = gr.update(value='')

            def _heartbeat():
                t0 = time.time()
                while not stop_hb.is_set():
                    secs = int(time.time() - t0)
                    text = BUSY_HTML(
                        f'处理中 {secs}s · 模型:{llm_state_text()} · '
                        f'进度: {tail_run_log() or "等待生成事件"}')
                    ev.put({'kind': 'hb', 'text': text})
                    stop_hb.wait(HEARTBEAT_SEC)

            threading.Thread(target=_heartbeat, daemon=True).start()

            all_pending_tasks = []
            monitor_reported_completion = False
            noop = gr.update()
            first = True
            final_text = ''
            phase = 'ok'
            aborted = False
            _dup_streak = 0  # book-13 防复读：连续重复块计数
            _prev_final = ''  # book-16：空转检测

            try:
                for attempt in range(MAX_AUTO_CONTINUE + 1):
                    if stop_event.is_set() or _stop_requested.is_set():
                        aborted = True
                        break

                    if attempt == 0:
                        msgs.append({'role': 'user', 'content': user_text})

                    shown = fmt_msgs(msgs)

                    turn_args = (msgs[:-1] if attempt > 0 else msgs[:-1], 
                                user_text if attempt == 0 else None, ev)
                    threading.Thread(target=run_turn, args=turn_args, daemon=True).start()

                    while True:
                        if stop_event.is_set() or _stop_requested.is_set():
                            aborted = True
                            break

                        if not check_turn_valid(cid, current_turn_id):
                            aborted = True
                            break

                        try:
                            item = ev.get(timeout=0.5)
                        except queue.Empty:
                            yield shown, BUSY_HTML('处理中...'), '', noop, cid, msgs, _pool_update(cid), (clear_box if first else noop)
                            first = False
                            continue

                        kind = item.get('kind')
                        if kind in ('hb', 'phase'):
                            status_text = item.get('text', '')
                            yield shown, status_text, '', noop, cid, msgs, _pool_update(cid), (clear_box if first else noop)
                            first = False
                        elif kind == 'chunk':
                            # book-13 C1：消息级分批渲染——立即追加，不等待整轮
                            # book-13 防复读：连续重复块丢弃并计数，超阈值中止本轮展示
                            text = item.get('text', '')
                            if text:
                                if _dup_text(text, str(msgs[-1].get('content', '')) if msgs and msgs[-1].get('role') == 'assistant' else ''):
                                    _dup_streak += 1
                                    if _dup_streak > 2:  # 收紧：第 3 个重复块即停（用户真实测试：上一版 8 次太晚）
                                        phase = 'error'
                                        final_text = '输出异常（检测到持续重复），已自动停止展示；请重试或换一种说法。'
                                        yield shown, ERROR_HTML, '⚠️ 模型输出重复，已自动停止', noop, cid, msgs, _pool_update(cid), (clear_box if first else noop)
                                        first = False
                                        break
                                else:
                                    _dup_streak = 0
                                    if msgs and msgs[-1].get('role') == 'assistant':
                                        msgs[-1]['content'] = str(msgs[-1].get('content', '')) + text
                                    else:
                                        msgs.append({'role': 'assistant', 'content': text})
                                    shown = fmt_msgs(msgs)
                                    yield shown, BUSY_HTML('生成中（内容已输出）...'), '', noop, cid, msgs, _pool_update(cid), (clear_box if first else noop)
                                    first = False
                            continue
                        elif kind == 'tool':
                            yield shown, BUSY_HTML('工具调用中...'), f'🔧 工具：{item.get("text", "")}', noop, cid, msgs, _pool_update(cid), (clear_box if first else noop)
                            first = False
                            continue
                        elif kind == 'done':
                            final_text = item.get('text') or ''
                            phase = 'ok'
                            break
                        elif kind == 'error':
                            phase = 'error'
                            final_text = item.get('text') or '未知错误'
                            break

                    if aborted or phase == 'error':
                        break

                    prompt_ids = extract_prompt_ids(final_text)
                    if prompt_ids:
                        tasks = [{'prompt_id': pid, 'type': 'single'} for pid in prompt_ids]
                        all_pending_tasks.extend(tasks)
                    # book-07：批量任务入会话任务表（BATCH_MANIFEST: <dir>）
                    import re as _re
                    bm = _re.findall(r'BATCH_MANIFEST:\s*(\S+)', final_text or '')
                    for d in bm:
                        all_pending_tasks.append({'manifest': d, 'type': 'batch'})

                    needs_continuation = should_continue(
                        user_text, final_text, prompt_ids,
                        last_tool=(_LAST_TOOL or ('', ''))[0], last_tool_hint=(_LAST_TOOL or ('', ''))[1])

                    # book-16: spin-stop (empty-progress repeat)
                    if _prev_final and (final_text.startswith(_prev_final[:80])
                                        or _prev_final.startswith(final_text[:80])):
                        note_md = 'spin-stop'
                        break
                    _prev_final = final_text

                    if not needs_continuation or attempt >= MAX_AUTO_CONTINUE:
                        break

                    msgs.append({"role": "user", "content": '[系统自动续接] 请继续完成当前任务。'
                                 + (('[上一步] ' + ((_LAST_TOOL or ('', ''))[1])[:140]) if _LAST_TOOL else '') + '（重试/继续需按真实工具结果；不得虚构提交结果）'})
                    user_text = None
                    yield (shown, BUSY_HTML('自动续接中...'), ' 自动续接中...', noop, cid, msgs, _pool_update(cid), noop)

            finally:
                stop_hb.set()

            # P1：send 正常走完监控（完成/失败已由状态条展示）→ 标记，watcher 不重复注入；
            # 仅当 send 提前断开/未走完时 watcher 接管注入通知。
            try:
                from runs.agent import task_watch as _twm
                for _t in all_pending_tasks:
                    _tk = str(_t.get('prompt_id') or _t.get('manifest') or '')
                    try:
                        if _t.get('type') == 'single':
                            _st = _twm.poll_single(_t['prompt_id']).get('status')
                        elif _t.get('type') == 'batch':
                            _st = _twm.poll_batch(str(_t.get('manifest') or '')).get('status')
                        else:
                            _st = None
                    except Exception:  # noqa: BLE001
                        _st = None
                    # 只 mark 已被状态条展示的终态任务；进行中任务保留给 watcher 接管
                    if _st in ('completed', 'failed'):
                        _twm.p1_mark(cid, _tk)
            except Exception:  # noqa: BLE001
                pass

            add_tasks(cid, all_pending_tasks)

            if all_pending_tasks and check_turn_valid(cid, current_turn_id):
                try:
                    from runs.agent.task_watch import _monitor_worker
                    monitor_queue = queue.Queue(maxsize=10)
                    monitor_thread = threading.Thread(
                        target=_monitor_worker, 
                        args=(cid, current_turn_id, monitor_queue, stop_event),
                        daemon=True
                    )
                    monitor_thread.start()

                    while True:
                        try:
                            msg = monitor_queue.get(timeout=0.5)
                        except queue.Empty:
                            if not monitor_thread.is_alive():
                                break
                            if not check_turn_valid(cid, current_turn_id) or stop_event.is_set():
                                break
                            continue

                        if msg['type'] == 'update':
                            yield (gr.update(), msg['status_html'], msg['note_md'], noop, cid, msgs, _pool_update(cid), noop)
                        elif msg['type'] == 'done':
                            monitor_reported_completion = True
                            if msg['status_html']:
                                yield (gr.update(), msg['status_html'], msg['note_md'], noop, cid, msgs, _pool_update(cid), noop)
                            break
                except Exception:
                    pass

            if aborted or _stop_requested.is_set():
                final_status = ABORT_HTML
                note = '已中止本轮。'
                msgs.append({'role': 'assistant', 'content': '[已中止]'})
            elif phase == 'error':
                final_status = ERROR_HTML
                _hint = _err_hint(final_text)
                msg = f'[执行出错] {final_text}\n建议：{_hint}'
                msgs.append({'role': 'assistant', 'content': msg})
                note = f'本轮执行出错：{_hint}'
            elif final_text:
                # book-16：done 文本即流式已展示文本 → 不得再走 else 占位（防“（模型未返回内容）”误追加）
                final_status = IDLE_HTML
                if not (msgs and msgs[-1].get('role') == 'assistant'
                        and str(msgs[-1].get('content', '')).rstrip()
                        .endswith(final_text.rstrip()[-60:])):
                    # book-13 C1：流式未含该文本（工具轮兜底/非流式）→ 追加
                    msgs.append({'role': 'assistant', 'content': final_text})
                try:
                    _ctx_n = sum(ctx_budget.count_tokens(str(m.get('content', ''))) for m in msgs)
                except Exception:  # noqa: BLE001
                    _ctx_n = 0
                note = f'✅ 本轮完成 · 上下文约 {_ctx_n} token（预算 ~{CONV_MSG_BUDGET_TOKENS}）'
            else:
                final_status = IDLE_HTML
                msgs.append({'role': 'assistant', 'content': '(模型未返回内容)'})
                note = '模型未返回内容'

            save_chat(cid, msgs)

            if check_turn_valid(cid, current_turn_id):
                if stop_event.is_set() or _stop_requested.is_set():
                    yield (msgs, ABORT_HTML, ' 已中止', noop, cid, msgs, _pool_update(cid), [])
                elif monitor_reported_completion:
                    yield (msgs, noop, noop, noop, cid, msgs, _pool_update(cid), [])
                else:
                    yield (msgs, final_status, note, gr.update(choices=_choices()), cid, msgs, _pool_update(cid), clear_box)
        finally:
            _active_turn.release()

        def send(chat_hist, cid, user_text):
            """send 包装（§15d）：为每个 yield 追加会话结果区刷新——结果随轮次/心跳即时可见。

            内部实现=_send_impl（8 元组：chatbot/status/note/hist_dd/cid_state/hist_state/gallery/box）；
            此处按 cid 补上 res_video/res_files 两个输出位。
            """
            for _item in _send_impl(chat_hist, cid, user_text):
                _cid = _item[4] if len(_item) > 4 else cid
                yield tuple(_item) + tuple(_results_update(_cid))

    with gr.Blocks(title='H3 视频生成助手', theme=gr.themes.Soft()) as demo:
        # 注意：gr.State 必须在 Blocks 上下文内创建（上下文外创建会 KeyError: 0）
        hist_state = gr.State([])   # 完整消息（存档口径：user/assistant 交替）
        cid_state = gr.State('')    # 会话 id（demo.load / ＋新对话 时自动创建）
        try:
            from runs.agent import version as _vg
            _ver = _vg.AGENT_VERSION
        except Exception:  # noqa: BLE001
            _ver = 'unknown'
        gr.Markdown('## 🎬 H3 视频生成助手\n'
                    '说出你的创意，我来生成视频。支持文生视频/图生视频/参考图/首末帧转场。\n'
                    f'_版本指纹：`{_ver}`（与 dev.py check / 日志 AGENT_VERSION 核对）_')
        with gr.Row():
            hist_dd = gr.Dropdown(label='历史会话', choices=_choices(), scale=4)
            load_btn = gr.Button('加载所选历史会话')
            del_btn = gr.Button('删除所选历史会话')
            ref_btn = gr.Button('刷新历史列表')
            new_btn = gr.Button('＋新建会话', variant='primary')
        gr.Markdown('_「刷新历史列表」仅更新左侧历史会话下拉；不影响正在进行的任务。_')
        status_html = gr.HTML(IDLE_HTML)
        with gr.Row():
            stop_btn = gr.Button('⏹ 停止当前任务', variant='stop', size='sm')
            gr.Markdown('_状态条动态显示：模型状态 + 生成进度；长时间不动可点"停止当前任务"。_\n_已提交的任务会在后台完成，用"继续"/"取片"获取结果；素材为本会话专属_')
        chatbot = gr.Chatbot(type='messages', height=440, label='对话')
        with gr.Row():
            up_btn = gr.UploadButton('📤 上传素材（图片/视频）· 本会话专属',
                                     file_types=['image', 'video'],
                                     file_count='multiple', scale=3)
            continue_btn = gr.Button('继续承接任务', size='sm', scale=1)
            box = gr.Textbox(placeholder='描述你的创意，我来生成视频…（Enter 发送；多行建议分次发送）',
                             show_label=False, lines=1, scale=5)
            send_btn = gr.Button('开始生成', variant='primary', scale=1)
        up_status = gr.HTML(UP_IDLE)
        gallery = gr.Gallery(label='上传预览',
                             columns=6, object_fit='cover', interactive=False)
        # §15d 会话结果区：链/引擎成片自动落 logs/agent_chats/<cid>/outputs/（页面预览+下载）
        with gr.Row():
            res_video = gr.Video(label='本轮结果视频（暂无结果）', interactive=False, scale=2)
            res_files = gr.File(label='本轮结果文件（暂无）', file_count='multiple',
                                interactive=False, scale=1)
        gr.Markdown('_结果区：本会话产出的成片自动出现在上方（预览+下载）；加载历史会话可查该会话产物。_')
        note_md = gr.Markdown('_…_')

        out = [chatbot, status_html, note_md, hist_dd, cid_state, hist_state]
        send_out = out + [gallery, box, res_video, res_files]  # 发送输出追加预览池+输入框+结果区（§15d）
        new_out = out + [gallery, up_status, res_video, res_files]  # 新建/加载：预览/上传状态+结果区同步刷新

        def _auto_new():
            global _current_cid, _pending_batch_id
            cid = new_chat_id()
            _current_cid = cid
            _pending_batch_id = None
            threading.Thread(
                target=lambda: _prewarm_on_load(),
                daemon=True).start()
            return ([], IDLE_HTML,
                    f'✅ 已自动开启新对话（会话 id：`{cid}`），直接输入即可。\n（新会话：上传预览已清空，素材需重新上传到本会话）',
                    gr.update(choices=_choices()), cid, [],
                    gr.update(value=[]), UP_IDLE, *_results_update(cid))

        def _load(sel):
            global _current_cid
            if not sel:
                return [], IDLE_HTML, '请先选择历史会话。', gr.update(), '', [], gr.update(value=[]), UP_IDLE, *_results_update('')
            _current_cid = sel
            msgs = load_chat(sel)
            _prevs = _previews_for_cid(sel) + _shared_for_cid(sel)  # book-13 P2#9b + S12：本会话+有效共享授权预览
            _gal_by_cid[sel] = _prevs
            return (fmt_msgs(msgs), IDLE_HTML,
                    f'已加载会话 {sel}（{len(msgs) // 2} 轮），已重建 {len(_prevs)} 项素材预览。\n（本会话全部素材以 list_references 为准）',
                    gr.update(), sel, msgs,
                    gr.update(value=_prevs), UP_IDLE, *_results_update(sel))

        def _new():
            global _current_cid, _pending_batch_id
            cid = new_chat_id()
            _current_cid = cid
            _pending_batch_id = None
            _gal_by_cid[cid] = []  # book-16：预览按会话隔离
            return [], IDLE_HTML, f'✅ 已开启新对话（会话 id：`{cid}`）。\n（新会话：素材需重新上传到本会话）', \
                gr.update(choices=_choices()), cid, [], gr.update(value=[]), UP_IDLE, *_results_update(cid)

        def _del(sel):
            if sel:
                delete_chat(sel)
            return gr.update(choices=_choices())

        def _upload(files, cid):
            cid = str(cid or '') or str(_current_cid or '')  # P0：cid_state 异常时兜底当前会话（否则上传素材被记错会话=\"上传了却认为没有\"）
            global _upload_in_progress
            n = len(files) if files else 0
            _upload_in_progress = True
            try:
                yield UP_LOADING(n), gr.update()
                if not files:
                    yield (_pill('⚠️ 未收到文件（请重新选择图片/视频）',
                                 '#c0392b', '#fdf2f2', '#e5b8b8'), [])
                    return
                try:
                    msg, previews, _invalid, batch_id = ingest_upload(files, cid)
                    if '✅' in msg:
                        global _pending_batch_id
                        _pending_batch_id = batch_id
                        from runs.agent import turn_state
                        turn_state.reset_all_on_upload()
                    has_reject = '🚫' in msg or '❌' in msg
                    color = '#0a7d32' if not has_reject else '#c0392b'
                    bg = '#f4fbf6' if color == '#0a7d32' else '#fdf2f2'
                    border = '#9dd6ae' if color == '#0a7d32' else '#e5b8b8'
                    html = (f'<div style=”padding:4px 8px;background:{bg};'
                            f'border:1px solid {border};border-radius:4px;'
                            f'color:{color};font-weight:600;font-size:13px”>'
                            f'{msg}</div>')
                    # book-13 S14：预览强耦合拆分——先归档/镜像，再逐张生成缩略图并逐步报状态
                    _thumbs = []
                    if len(previews) > 3:
                        yield (_pill(f'⏳ 正在生成 {len(previews)} 张缩略图（并行）…',
                                     '#8a6d1a', '#fff8e1', '#e7d492'), gr.update())
                        import concurrent.futures as _cf
                        def _th(kv):  # 现场故障修复：多素材上传卡顿——缩略图并行生成（大图 PIL 解码并行）
                            src, sha = kv
                            th = _make_thumb(Path(src), sha) if Path(src).exists() else None
                            # S1：统一元组化（path, caption）；缩略图失败不append（保留安全：不回退源路径进组件值）
                            return (str(th), _caption_for(cid)) if th else None
                        with _cf.ThreadPoolExecutor(max_workers=4) as _ex:
                            _thumbs = [x for x in _ex.map(_th, previews) if x]
                    else:
                        for i, (src, sha) in enumerate(previews, 1):
                            yield (_pill(f'⏳ 正在生成预览 {i}/{len(previews)}（{Path(src).name[:24]}）…',
                                         '#8a6d1a', '#fff8e1', '#e7d492'), gr.update())
                            th = _make_thumb(Path(src), sha) if Path(src).exists() else None
                            if th:
                                # S1：统一元组化（path, caption）——失败不append（不回退源路径进组件值）
                                _thumbs.append((str(th), _caption_for(cid)))
                    _gal_by_cid[cid] = _previews_for_cid(cid)  # P0：全量重建（缩略图已缓存）——并发/重复上传不再互相覆盖
                    yield html, _gal_by_cid[cid]
                except Exception as e:  # noqa: BLE001
                    yield (_pill(f'❌ 上传处理异常：{type(e).__name__}: {e}',
                                 '#c0392b', '#fdf2f2', '#e5b8b8'), [])
            finally:
                _upload_in_progress = False

        def _stop():
            global _stop_requested
            _stop_requested.set()
            return (ABORT_HTML + ' 已发出停止请求；若任务已提交仍会在后台完成，'
                    '可用"继续"或"取片"查看结果',
                    '已请求停止')

        load_btn.click(_load, hist_dd, new_out)
        new_btn.click(_new, None, new_out)
        del_btn.click(_del, hist_dd, hist_dd)
        ref_btn.click(lambda: gr.update(choices=_choices()), None, hist_dd)
        stop_btn.click(_stop, None, [status_html, note_md])
        # book-13 S14：文件管理器选择成功即显示“正在上传…”（早于预览，解耦等待感知）
        def _up_select(files):
            n = len(files) if files else 0
            if n:
                return _pill(f'📂 已选择 {n} 个文件，正在上传…（传输需数秒；预览稍后生成）',
                             '#8a6d1a', '#fff8e1', '#e7d492')
            return UP_IDLE
        if getattr(up_btn, 'select', None):
            up_btn.select(_up_select, up_btn, up_status)
        up_btn.upload(_upload, [up_btn, cid_state], [up_status, gallery], concurrency_limit=1)  # P0：上传串行（并发上传曾致预览竞态丢失/异常图标）
        def _inject_notify(cid: str, text: str) -> None:
            """P1：把通知文本以用户消息注入会话（复用 send 全链；_active_turn 互斥保证仅 idle）。

            消费 send 生成器：消息写入会话档+触发模型总结；用户回合中 send 会自拒（不打扰）。
            """
            try:
                msgs = load_chat(cid)
                if not msgs:
                    return
                # 保守：send 会 clear_tasks(cid)（其尾部 add_tasks 提取新 pid）——
                # 注入前备份本会话任务表，注入后合并回写（防同会话多任务时丢失监控）
                try:
                    from runs.agent import session_state as _ss2
                    _before = list(_ss2.get_tasks(cid) or [])
                except Exception:  # noqa: BLE001
                    _before = []
                for _ in send(msgs, cid, text):
                    pass
                if _before:
                    try:
                        from runs.agent import session_state as _ss3
                        _after = list(_ss3.get_tasks(cid) or [])
                        _ss3.add_tasks(cid, _before + [t for t in _after if t not in _before])
                    except Exception:  # noqa: BLE001
                        pass
                from runs.agent import task_watch as _tw
                _tw._log_tw("p1_inject cid=%s text=%s" % (cid, text[:60]))
            except Exception as e:  # noqa: BLE001
                try:
                    from runs.agent.task_watch import _log_tw as _l
                    _l("p1_inject_error cid=%s err=%s" % (cid, type(e).__name__))
                except Exception:  # noqa: BLE001
                    pass

        def _notify_watcher(stop_evt=None):
            """P1：常驻结果通知 watcher（book-19 §9；P1_NOTIFY_EVENTS=off 回滚）。

            每 15s：心跳→遍历会话任务→S8/poll 判定→四类事件/降级→去重→idle 时注入。
            同任务同类目仅通知一次；用户回合进行中(_active_turn)跳过(下轮再试)。
            """
            from runs.agent import task_watch as _tw
            notified = set()
            QUEUE_AGE = 1800   # 排队超阈值(30min)→队列超时文案
            RUN_AGE = 7200     # 运行超阈值(2h)→运行超时文案
            while True:
                try:
                    time.sleep(15)
                except BaseException:  # noqa: BLE001
                    break
                if str(os.environ.get("P1_NOTIFY_EVENTS", "on")).strip().lower() in ("0", "false", "off", "no"):
                    continue
                try:
                    _tw.watcher_beat()
                    if _active_turn.locked():
                        continue  # 仅 idle 注入；用户回合进行中不打断
                    from runs.agent import session_state as _ss
                    cids = _ss.list_cids()
                    if cids:
                        _tw._log_tw("p1_watch tick cids=%s" % cids)
                    for cid in cids:
                        tasks = _ss.get_tasks(cid) or []
                        if not tasks:
                            continue
                        health_ok, _age = _tw.watcher_health()
                        for task in tasks:
                            try:
                                if task.get("type") == "single":
                                    pid = str(task.get("prompt_id") or "")
                                    r = _tw.poll_single(pid)
                                    st = r.get("status")
                                    ekey = None
                                    if st == "completed":
                                        ekey = "done"
                                        text = _tw.build_notify_message(
                                            "completed", pid, detail=_tw.describe_output(pid))
                                    elif st == "failed":
                                        ekey = "fail"
                                        text = _tw.build_notify_message(
                                            "failed", pid, detail=r.get("progress", ""))
                                    elif st in ("queued", "pending"):
                                        el = _tw._elapsed(pid)
                                        if el > QUEUE_AGE:
                                            ekey = "qtimeout"
                                            text = _tw.build_notify_message(
                                                "queue_timeout", pid, elapsed=el)
                                    elif st == "running":
                                        el = _tw._elapsed(pid)
                                        if el > RUN_AGE:
                                            ekey = "rtimeout"
                                            text = _tw.build_notify_message(
                                                "run_timeout", pid, elapsed=el)
                                    if ekey and not _tw.p1_was(cid, pid):
                                        # 产物落盘保障（2026-09-06 现场问题：send 提前结束时任务完成
                                        # 但无人 resume → 视频只在 ComfyUI output，spark 项目 outputs 缺失）。
                                        # watcher 接管路径=注入前先 resume（幂等；失败不阻断通知）。
                                        if ekey == "done":
                                            try:
                                                import subprocess as _sp, sys as _sys2
                                                _sp.run([_sys2.executable,
                                                         os.path.join(PROJECT_ROOT, 'runs', 'h3_submit.py'),
                                                         '--resume', pid],
                                                        capture_output=True, timeout=300,
                                                        cwd=PROJECT_ROOT)
                                            except Exception:  # noqa: BLE001
                                                pass
                                        # 用户已停止/切换会话（stop_event 置位）→ 不注入（用户已接管）
                                        try:
                                            from runs.agent import session_state as _ss4
                                            if _ss4.get_stop_event(cid).is_set():
                                                continue
                                        except Exception:  # noqa: BLE001
                                            pass
                                        key = _tw.notify_key(cid, pid, ekey)
                                        if key not in notified:
                                            notified.add(key)
                                            _tw._log_tw("p1_inject_single cid=%s pid=%s ev=%s" % (cid, pid[:8], ekey))
                                            _inject_notify(cid, text)
                                elif task.get("type") == "batch":
                                    r = _tw.poll_batch(str(task.get("manifest") or ""))
                                    st = r.get("status")
                                    ekey = None
                                    if st == "completed":
                                        ekey = "done"
                                        text = _tw.build_notify_message(
                                            "completed", "batch", detail=r.get("progress", ""))
                                    elif st == "failed":
                                        ekey = "fail"
                                        text = _tw.build_notify_message(
                                            "failed", "batch", detail=r.get("progress", ""))
                                    if ekey and not _tw.p1_was(cid, str(task.get("manifest") or "")):
                                        key = _tw.notify_key(cid, str(task.get("manifest")), ekey)
                                        if key not in notified:
                                            notified.add(key)
                                            _inject_notify(cid, text)
                                if not health_ok:
                                    key = _tw.notify_key(cid, str(task.get("prompt_id") or task.get("manifest") or ""), "health")
                                    if key not in notified:
                                        notified.add(key)
                                        _inject_notify(cid, _tw.build_notify_message("watch_health"))
                            except Exception as _e:  # noqa: BLE001
                                _tw._log_tw("p1_watch_task_err cid=%s err=%s" % (cid, _e))
                                continue
                except BaseException as _e:  # noqa: BLE001
                    try:
                        _tw._log_tw("p1_watch_cycle_err err=%s" % _e)
                    except Exception:  # noqa: BLE001
                        pass
                    continue

        def _continue(hist, cid):
            yield from send(hist, cid, '继续')
        send_btn.click(send, [hist_state, cid_state, box], send_out,
                       concurrency_limit=1)
        continue_btn.click(_continue, [hist_state, cid_state], send_out,
                           concurrency_limit=1)
        box.submit(send, [hist_state, cid_state, box], send_out,
                   concurrency_limit=1)
        demo.load(_auto_new, None, new_out)
        demo.load(lambda: gr.update(value=None), None, up_btn)  # 现场故障修复：页面加载即清空上传组件值（防恢复态携带非上传对象引发 Gradio InvalidPathError）

    print(f'Qwen-Agent 调度器 Web UI: http://127.0.0.1:{port}')
    print(f'项目根目录: {PROJECT_ROOT}')
    print(f'历史会话目录: {CHATS_DIR}')
    # 预览白名单：Gradio 默认只服务临时目录文件，需放行素材镜像/归档目录
    allowed = [str(THUMBS_DIR), str(_comfy_input_dir() / 'user_uploads'),
               str(UPLOADS_DIR), str(CHATS_DIR)]  # §15d：会话产物目录（results 区预览/下载）
    threading.Thread(target=_notify_watcher, daemon=True, name="p1-notify-watcher").start()
    demo.queue(default_concurrency_limit=16)
    demo.launch(server_name='0.0.0.0', server_port=port, share=share,
                show_error=True, quiet=True, allowed_paths=allowed)

# ---------------------------------------------------------------- 任务 ID 提取
def extract_prompt_ids(text: str) -> list:
    """从工具输出文本中提取所有 prompt_id。
    
    支持格式：
    - prompt_id: xxx-xxx-xxx
    - TASK_SUBMITTED: xxx-xxx-xxx
    """
    import re
    ids = []
    if not text:
        return ids
    
    # 匹配 prompt_id: <uuid> 或 TASK_SUBMITTED: <uuid>
    patterns = [
        r'prompt_id:\s*([a-f0-9\-]{36})',
        r'TASK_SUBMITTED:\s*([a-f0-9\-]{36})',
    ]
    
    for pattern in patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        ids.extend(matches)
    
    return list(set(ids))  # 去重
