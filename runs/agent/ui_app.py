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
UP_LOADING = lambda n: _pill(f'⏳ 正在上传中… {n} 个文件', '#8a6d1a', '#fff8e1', '#e7d492')



from runs.agent import ctx_budget
from runs.agent.ctx_budget import UI_TRIM_TOKENS, CONV_MSG_BUDGET_TOKENS, is_context_overflow_error
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
    """整段重写（简单可靠）；可选追加一条消息。"""
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


# ---------------------------------------------------------------- 模型回合
def run_turn(history: list, user_text: str, events: 'queue.Queue'):
    """后台线程：新开一个 Assistant 处理当前轮（无状态，历史由外部传入）。"""
    from qwen_agent.agents import Assistant
    from runs.agent.scheduler import LLM_CFG, SYSTEM_MESSAGE, TOOL_NAMES
    from runs.agent import turn_state
    global _pending_batch_id
    turn_state.begin_turn(batch_id=_pending_batch_id)
    _pending_batch_id = None

    trimmed, dropped = trim_context(history + [{'role': 'user', 'content': user_text}])
    payload = list(trimmed)
    if dropped:
        note = ('\n\n[上下文提示] 较早的对话轮次已按 token 预算自动压缩'
                '（最新轮次与任务状态仍在）。如需回顾可让我重述。')
        payload[-1] = {'role': 'user',
                       'content': str(payload[-1].get('content', '')) + note}

    llm = dict(LLM_CFG)
    # 回复上限 + qwen_agent 输入硬预算（实测依据见 ctx_budget.py）：
    # 截断层 available = max_input_tokens − tokens(system)，保证每次调用
    # （含回合内工具往返）服务端总输入 ≤ 6144，与 2048 回复合计不越 ctx=8192。
    max_input, overhead = ctx_budget.request_budgets(SYSTEM_MESSAGE)
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
        bot = Assistant(llm=llm, system_message=SYSTEM_MESSAGE,
                        function_list=TOOL_NAMES)
        final = ''
        for chunk in bot.run(messages=msgs):
            # chunk: List[Message]; 取最后一个 assistant 文本（可能含工具过程消息）
            for m in chunk:
                if m.get('role') == 'assistant':
                    final = _content_text(m.get('content'))
        return final

    try:
        final = _one_run(payload)
        events.put({'kind': 'done', 'text': final})
    except Exception as e:  # noqa: BLE001
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


def ingest_upload(paths) -> tuple:
    """把界面/上传文件收进素材池（与 upload_watch 同语义）：

    - 任意类型 → 归档 uploads/YYYYMMDD/<sha8>_<原名>（sha 去重）+ log.jsonl 流水；
    - 图片额外镜像到 ComfyUI input/user_uploads/<原名>（LoadImage/refimage 立即可见）。
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
                                        'batch_id': batch_id},
                                       ensure_ascii=False) + '\n')
                seen.add(sha)
                added += 1
            except OSError:
                err += 1
                continue
        else:
            dup += 1
        if kind == 'image':
            try:
                input_mirror.mkdir(parents=True, exist_ok=True)
                shutil.copy2(p, input_mirror / p.name)
            except OSError:
                err += 1
            thumb = _make_thumb(p, sha)
            previews.append(str(thumb) if thumb else str(input_mirror / p.name))
    parts = []
    if added:
        parts.append(f'✅ {added} 个新素材已加入本会话素材池')
    if dup:
        if added:
            parts.append(f'⏩ {dup} 个重复已跳过')
        else:
            parts.append(f'⏩ {dup} 个素材已在本会话池中（可直接使用）')
    if invalid_details:
        detail_str = '，'.join(f'{name}（{reason}）' for name, reason in invalid_details)
        parts.append(f'🚫 {len(invalid_details)} 个无效：{detail_str}')
    if err:
        parts.append(f'❌ {err} 项处理失败')
    if not parts:
        parts.append('⚠️ 未收到有效文件')
    return ' · '.join(parts), previews, invalid_details, batch_id



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


def _err_hint(t: str) -> str:
    """错误分类 + 解决建议（book-02）。"""
    t = t or ''
    if 'maximum context length' in t or 'ModelServiceError' in t:
        return '上下文超限：请精简对话或点"继续"分轮；已自动压缩一次'
    if 'ModuleNotFoundError' in t or 'No module named' in t:
        return '脚本导入异常：已记录待修；可重试一次'
    if '⛔' in t or '熔断' in t or '不可恢复' in t:
        return '已连续失败熔断：请更换素材或稍后再试，勿连续重试'
    if 'TimeoutExpired' in t or '超时' in t:
        return '提交/轮询卡顿：任务可能在后台运行，用"继续"/"取片"确认，勿重复提交'
    if 'comfyui' in t.lower() or '8188' in t or 'connection' in t.lower():
        return '生成服务未就绪：请人工检查 spark 的 ComfyUI（勿自行重启）'
    return '请按上述信息排查；可点"继续"重试或查看日志'


def run_app(port: int = 7860, share: bool = False) -> None:
    import gradio as gr

    def fmt_msgs(msgs):
        return [{'role': m['role'], 'content': str(m.get('content', ''))}
                for m in msgs if m.get('role') in ('user', 'assistant')]

    def send(chat_hist, cid, user_text):
        """重构版 send()：集成 auto-continue + 任务监控。"""
        from runs.agent.session_state import (
            get_stop_event, clear_tasks, add_tasks, increment_turn_id, check_turn_valid
        )

        MAX_AUTO_CONTINUE = 2
        ABORT_MARKERS = ('⛔', '不可恢复', '熔断')

        user_text = (user_text or '').strip()
        if not _active_turn.acquire(blocking=False):
            yield (fmt_msgs(chat_hist or []),
                   BUSY_HTML('上一轮仍在处理中，本次点击已忽略'),
                   '上一轮仍在处理中；请等状态变绿或点"停止当前任务"。', gr.update(), cid,
                   chat_hist or [], gr.update())
            return
        try:
            global _stop_requested
            _stop_requested = threading.Event()

            if _upload_in_progress:
                yield (fmt_msgs(chat_hist or []),
                       BUSY_HTML('上传尚未完成，请稍候再发送'),
                       '⏳ 素材上传进行中，请等待上传完成后再发送。', gr.update(), cid,
                       chat_hist or [], gr.update())
                return

            if not user_text:
                yield (fmt_msgs(chat_hist or []), IDLE_HTML, '请输入内容。', gr.update(), cid,
                       chat_hist or [], gr.update())
                return

            if not cid:
                cid = new_chat_id()

            msgs = list(chat_hist or [])
            stop_event = get_stop_event(cid)
            stop_event.clear()
            clear_tasks(cid)
            current_turn_id = increment_turn_id(cid)

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
                            yield shown, BUSY_HTML('处理中...'), '', noop, cid, msgs, (clear_box if first else noop)
                            first = False
                            continue

                        kind = item.get('kind')
                        if kind in ('hb', 'phase'):
                            status_text = item.get('text', '')
                            yield shown, status_text, '', noop, cid, msgs, (clear_box if first else noop)
                            first = False
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

                    needs_continuation = (
                        final_text and 
                        not any(marker in final_text for marker in ABORT_MARKERS) and
                        not prompt_ids
                    )

                    if not needs_continuation or attempt >= MAX_AUTO_CONTINUE:
                        break

                    msgs.append({"role": "system", "content": '[系统自动续接] 请继续完成当前任务。'})
                    user_text = None
                    yield (shown, BUSY_HTML('自动续接中...'), ' 自动续接中...', noop, cid, msgs, noop)

            finally:
                stop_hb.set()

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
                            yield (gr.update(), msg['status_html'], msg['note_md'], noop, cid, msgs, noop)
                        elif msg['type'] == 'done':
                            monitor_reported_completion = True
                            if msg['status_html']:
                                yield (gr.update(), msg['status_html'], msg['note_md'], noop, cid, msgs, noop)
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
                final_status = IDLE_HTML
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
                    yield (msgs, ABORT_HTML, ' 已中止', noop, cid, msgs, [])
                elif monitor_reported_completion:
                    yield (msgs, noop, noop, noop, cid, msgs, [])
                else:
                    yield (msgs, final_status, note, gr.update(choices=_choices()), cid, msgs, clear_box)
        finally:
            _active_turn.release()
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
            ref_btn = gr.Button('刷新')
            new_btn = gr.Button('＋新建会话', variant='primary')
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
            box = gr.Textbox(placeholder='描述你的创意，我来生成视频…（Enter 发送）',
                             show_label=False, lines=2, scale=5)
            send_btn = gr.Button('开始生成', variant='primary', scale=1)
        up_status = gr.HTML(UP_IDLE)
        gallery = gr.Gallery(label='上传预览',
                             columns=6, object_fit='cover', interactive=False)
        note_md = gr.Markdown('_…_')

        out = [chatbot, status_html, note_md, hist_dd, cid_state, hist_state]
        send_out = out + [box]   # 发送输出追加输入框（提交后自动清空）

        def _auto_new():
            cid = new_chat_id()
            threading.Thread(
                target=lambda: _prewarm_on_load(),
                daemon=True).start()
            return ([], IDLE_HTML,
                    f'✅ 已自动开启新对话（会话 id：`{cid}`），直接输入即可。',
                    gr.update(choices=_choices()), cid, [])

        def _load(sel):
            if not sel:
                return [], IDLE_HTML, '请先选择历史会话。', gr.update(), '', []
            msgs = load_chat(sel)
            return (fmt_msgs(msgs), IDLE_HTML,
                    f'已加载会话 {sel}（{len(msgs) // 2} 轮），可直接继续提问。',
                    gr.update(), sel, msgs)

        def _new():
            cid = new_chat_id()
            return [], IDLE_HTML, f'✅ 已开启新对话（会话 id：`{cid}`）。', \
                gr.update(choices=_choices()), cid, []

        def _del(sel):
            if sel:
                delete_chat(sel)
            return gr.update(choices=_choices())

        def _upload(files):
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
                    msg, previews, _invalid, batch_id = ingest_upload(files)
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
                    yield html, previews
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

        load_btn.click(_load, hist_dd, out)
        new_btn.click(_new, None, out)
        del_btn.click(_del, hist_dd, hist_dd)
        ref_btn.click(lambda: gr.update(choices=_choices()), None, hist_dd)
        stop_btn.click(_stop, None, [status_html, note_md])
        up_btn.upload(_upload, up_btn, [up_status, gallery])
        def _continue(hist, cid):
            yield from send(hist, cid, '继续')
        send_btn.click(send, [hist_state, cid_state, box], send_out,
                       concurrency_limit=1)
        continue_btn.click(_continue, [hist_state, cid_state], send_out,
                           concurrency_limit=1)
        box.submit(send, [hist_state, cid_state, box], send_out,
                   concurrency_limit=1)
        demo.load(_auto_new, None, out)

    print(f'Qwen-Agent 调度器 Web UI: http://127.0.0.1:{port}')
    print(f'项目根目录: {PROJECT_ROOT}')
    print(f'历史会话目录: {CHATS_DIR}')
    # 预览白名单：Gradio 默认只服务临时目录文件，需放行素材镜像/归档目录
    allowed = [str(THUMBS_DIR), str(_comfy_input_dir() / 'user_uploads'),
               str(UPLOADS_DIR)]
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
