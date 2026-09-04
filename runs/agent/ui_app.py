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
  4) 上下文防膨胀：每轮调用前按字符预算裁剪历史（保留首轮意图 + 最近若干轮），
     裁剪发生时在本次请求中附加说明，避免长会话失控。

用法：由 runs/agent/scheduler.py run_gui() 调用（python3 runs/agent/scheduler.py）。
本模块不启动任何外部服务；不含服务管理能力。
"""
from __future__ import annotations

import hashlib
import json
import os
import queue
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
UPLOADS_DIR = Path(PROJECT_ROOT) / 'uploads'
UPLOADS_LOG = UPLOADS_DIR / 'log.jsonl'
IMG_EXT = {'.png', '.jpg', '.jpeg', '.webp', '.bmp'}
VID_EXT = {'.mp4', '.webm', '.mov', '.mkv', '.gif'}

# 上下文预算（字符；模型 ctx=8192，扣除系统/工具定义后按 ~3k token 预算）
MAX_CTX_CHARS = 6000
# 裁剪后至少保留的完整轮次数（外加首轮用户意图）
KEEP_TAIL_TURNS = 4
# 单轮模型回复 token 上限（防超长输出；长交付请分轮）
REPLY_MAX_TOKENS = 2048
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
    """返回 [(cid, 标题), ...]，按修改时间倒序。标题=首条用户消息摘要。"""
    if not CHATS_DIR.is_dir():
        return []
    items = []
    for p in sorted(CHATS_DIR.glob('*.jsonl'), key=lambda x: x.stat().st_mtime,
                    reverse=True):
        title = ''
        try:
            for line in p.read_text(encoding='utf-8').splitlines():
                d = json.loads(line)
                if d.get('role') == 'user' and d.get('content'):
                    title = d['content'].strip().replace('\n', ' ')[:36]
                    break
        except Exception:  # noqa: BLE001
            title = '(损坏)'
        if not title:
            title = '(空会话)'
        items.append((p.stem, f'{p.stat().st_mtime:%m-%d %H:%M} {title}'))
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
    """把 messages 裁到预算内：保留首条用户消息 + 最近 KEEP_TAIL_TURNS 轮。

    返回 (裁剪后的列表, 是否发生裁剪)。不改动原列表。
    """
    if not msgs:
        return [], False
    total = sum(len(str(m.get('content', ''))) for m in msgs)
    if total <= MAX_CTX_CHARS:
        return list(msgs), False
    head = [msgs[0]] if msgs[0].get('role') == 'user' else []
    tail = msgs[-KEEP_TAIL_TURNS * 2:]
    out = head + tail
    # 去重防止 head 与 tail 重叠
    seen = set()
    dedup = []
    for m in out:
        key = id(m)
        if key not in seen:
            seen.add(key)
            dedup.append(m)
    return dedup, True


# ---------------------------------------------------------------- 模型回合
def run_turn(history: list, user_text: str, events: 'queue.Queue'):
    """后台线程：新开一个 Assistant 处理当前轮（无状态，历史由外部传入）。"""
    from qwen_agent.agents import Assistant
    from runs.agent.scheduler import LLM_CFG, SYSTEM_MESSAGE, TOOL_NAMES

    trimmed, dropped = trim_context(history + [{'role': 'user', 'content': user_text}])
    payload = list(trimmed)
    if dropped:
        note = ('\n\n[上下文提示] 较早的对话轮次已按预算裁剪（最近轮次与任务状态仍在）。'
                '如需回顾可让我重述。')
        payload[-1] = {'role': 'user',
                       'content': str(payload[-1].get('content', '')) + note}

    llm = dict(LLM_CFG)
    llm['generate_cfg'] = {**(llm.get('generate_cfg') or {}),
                           'max_tokens': REPLY_MAX_TOKENS}
    # 内存协同：模型不在跑时先自动唤醒（期间界面心跳继续显示进度）
    try:
        from runs.agent import llm_mem as lmem
        lmem.ensure_llm_up(
            timeout_s=900,
            progress=lambda s: events.put(
                {'kind': 'hb',
                 'text': f'⏳ 正在唤醒本地模型…（{s}s；仅首次或让位后需要）'}))
    except Exception as e:  # noqa: BLE001
        events.put({'kind': 'error', 'text': f'模型唤醒失败: {e}'})
        return
    try:
        bot = Assistant(llm=llm, system_message=SYSTEM_MESSAGE,
                        function_list=TOOL_NAMES)
        final = ''
        for chunk in bot.run(messages=payload):
            # chunk: List[Message]; 取最后一个 assistant 文本（可能含工具过程消息）
            for m in chunk:
                if m.get('role') == 'assistant':
                    final = _content_text(m.get('content'))
        events.put({'kind': 'done', 'text': final})
    except Exception as e:  # noqa: BLE001
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


def _known_shas() -> set:
    if not UPLOADS_LOG.exists():
        return set()
    seen = set()
    try:
        for line in UPLOADS_LOG.read_text(encoding='utf-8').splitlines():
            try:
                seen.add(json.loads(line).get('sha'))
            except Exception:  # noqa: BLE001
                continue
    except OSError:
        pass
    return seen


def ingest_upload(paths) -> str:
    """把界面/上传文件收进素材池（与 upload_watch 同语义）：

    - 任意类型 → 归档 uploads/YYYYMMDD/<sha8>_<原名>（sha 去重）+ log.jsonl 流水；
    - 图片额外镜像到 ComfyUI input/user_uploads/<原名>（LoadImage/refimage 立即可见）。
    返回给用户的中文摘要。
    """
    if isinstance(paths, (str, Path)):
        paths = [paths]
    input_mirror = _comfy_input_dir() / 'user_uploads'
    added = dup = err = 0
    kinds = []
    seen = _known_shas()
    for raw in paths:
        p = raw
        if isinstance(raw, dict):
            p = raw.get('name') or raw.get('path')
        p = Path(str(p)).expanduser()
        if not p.is_file():
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
        if sha not in seen:
            day = datetime.now().strftime('%Y%m%d')
            dst_dir = UPLOADS_DIR / day
            dst_dir.mkdir(parents=True, exist_ok=True)
            dst = dst_dir / f'{sha[:8]}_{p.name}'
            try:
                shutil.copy2(p, dst)
                with open(UPLOADS_LOG, 'a', encoding='utf-8') as f:
                    f.write(json.dumps({'ts': _now(), 'sha': sha, 'src': str(p),
                                        'archived': str(dst), 'kind': kind},
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
    parts = []
    previews = []
    if added:
        parts.append(f'✅ 新增 {added} 项已入素材池（uploads/ 归档'
                     + ('，图片已镜像到 ComfyUI input/user_uploads/' if 'image' in kinds else '') + '）')
    if dup:
        parts.append(f'⏩ {dup} 项与池内已有文件相同（已跳过归档，图片仍确保可用）')
    if err:
        parts.append(f'❌ {err} 项处理失败（请确认文件格式）')
    if not parts:
        parts.append('⚠️ 未收到有效文件')
    parts.append('提示：现在可以对 agent 说“列出参考素材/list_references”，'
                 '把对应 <id> 设为参考图（h3/refimage.py use --name <id> --stage r2v --slot N）。')
    # 预览：图片镜像产物（持久路径，随上传永久可见）
    for raw in paths:
        p = raw
        if isinstance(raw, dict):
            p = raw.get('name') or raw.get('path')
        p = Path(str(p)).expanduser()
        if p.suffix.lower() in IMG_EXT:
            previews.append(str(input_mirror / p.name))
    return '\n'.join(parts), previews


# ---------------------------------------------------------------- Gradio 界面
def _choices() -> list:
    return [(label, cid) for cid, label in list_chats()]


def run_app(port: int = 7860, share: bool = False) -> None:
    import gradio as gr

    def fmt_msgs(msgs):
        return [{'role': m['role'], 'content': str(m.get('content', ''))}
                for m in msgs if m.get('role') in ('user', 'assistant')]

    def send(chat_hist, cid, user_text):
        user_text = (user_text or '').strip()
        if not user_text:
            yield fmt_msgs(chat_hist or []), '请输入内容。', 'idle', gr.update(), cid
            return
        if not cid:
            cid = new_chat_id()
        msgs = list(chat_hist or [])
        msgs.append({'role': 'user', 'content': user_text})
        shown = fmt_msgs(msgs)
        ev = queue.Queue()
        stop = threading.Event()

        def _heartbeat():
            t0 = time.time()
            while not stop.is_set():
                ev.put({'kind': 'hb',
                        'text': f'⏳ 模型/任务进行中（{int(time.time() - t0)}s）… '
                                f'视频长任务会持续数分钟，请勿重复提交；完成后对我说“取片”'})
                stop.wait(HEARTBEAT_SEC)

        threading.Thread(target=run_turn, args=(msgs[:-1], user_text, ev),
                         daemon=True).start()
        threading.Thread(target=_heartbeat, daemon=True).start()

        status = '🔶 处理中…'
        assistant = ''
        phase = 'ok'
        while True:
            try:
                item = ev.get(timeout=1.0)
            except queue.Empty:
                yield fmt_msgs(msgs), status, '', gr.update(), cid
                continue
            kind = item.get('kind')
            if kind == 'hb':
                status = item.get('text', status)
                yield fmt_msgs(msgs), status, '', gr.update(), cid
            elif kind == 'done':
                assistant = item.get('text') or ''
                break
            elif kind == 'error':
                phase = 'error'
                assistant = item.get('text') or '未知错误'
                break
        stop.set()

        if phase == 'error':
            msg = f'[执行出错] {assistant}'
            msgs.append({'role': 'assistant', 'content': msg})
            note = '上一轮执行出错：可把报错内容发我，或检查 logs/run_*.log。'
        elif assistant:
            msgs.append({'role': 'assistant', 'content': assistant})
            # 输出纪律：超长自动暂停，引导下一轮“继续”
            if len(assistant) > 600:
                tip = '\n\n—— 回复较长，为控制上下文已在此暂停；继续请发送：继续 ——'
                msgs[-1]['content'] = msgs[-1]['content'] + tip
            note = ('本轮完成。若提交了生成任务，取片/查进度请发：无参重跑续传；'
                    '产出路径以 REMOTE_VIDEO_PATH / LOCAL_OUTPUT 行为准。')
        else:
            msgs.append({'role': 'assistant', 'content': '（模型未返回内容，可能被截断；发送“继续”重试）'})
            note = '模型未返回内容（可能被截断），发送“继续”续写。'
        save_chat(cid, msgs)
        # 内存协同：回合确认提交了真实生成任务 → nap 让位视频生成（下轮自动唤醒）
        nap_note = ''
        try:
            from runs.agent import llm_mem as lmem
            if lmem.maybe_nap_after(assistant):
                nap_note = '（已临时让位内存给视频生成；下轮对话会自动唤醒本地模型）'
        except Exception:  # noqa: BLE001
            pass
        if nap_note:
            note = note + '\n\n' + nap_note
        yield fmt_msgs(msgs), 'idle', note, gr.update(choices=_choices()), cid

    with gr.Blocks(title='Qwen-Agent 受限调度器', theme=gr.themes.Soft()) as demo:
        # 注意：gr.State 必须在 Blocks 上下文内创建（上下文外创建会 KeyError: 0）
        hist_state = gr.State([])   # 完整消息（存档口径：user/assistant 交替）
        cid_state = gr.State('')    # 会话 id（demo.load / ＋新对话 时自动创建）
        gr.Markdown('## 🎬 Qwen-Agent 受限调度器\n'
                    '本地工作流组：t2v / i2v / r2v（多参考图）/ flf2v。\n'
                    '- 视频任务默认“提交即返回”，后台运行时本页持续显示进度，请勿重复提交；\n'
                    '- 单轮回复过长会自动暂停（发送 **继续** 续写），避免上下文失控；\n'
                    '- 页面打开自动开启新对话；历史会话可加载续聊；素材可直接上传到下方按钮。')
        with gr.Row():
            hist_dd = gr.Dropdown(label='历史会话', choices=_choices(), scale=4)
            load_btn = gr.Button('加载所选')
            del_btn = gr.Button('删除所选')
            ref_btn = gr.Button('刷新')
            new_btn = gr.Button('＋新对话', variant='primary')
        status_html = gr.HTML('<span style="color:green">● idle</span>')
        chatbot = gr.Chatbot(type='messages', height=440, label='对话')
        with gr.Row():
            up_btn = gr.UploadButton('📤 上传素材（图片/视频，自动进入素材池）',
                                     file_types=['image', 'video'],
                                     file_count='multiple', scale=3)
            box = gr.Textbox(placeholder='描述创意 / 查任务进度 / 素材选用…（Enter 发送）',
                             show_label=False, lines=2, scale=5)
            send_btn = gr.Button('发送', variant='primary', scale=1)
        up_status = gr.HTML('<span style="color:#888">尚未上传素材</span>')
        gallery = gr.Gallery(label='本次上传图片预览（可直接引用：list_references）',
                             columns=6, object_fit='cover', interactive=False)
        note_md = gr.Markdown('_…_')

        out = [chatbot, status_html, note_md, hist_dd, cid_state]

        def _auto_new():
            cid = new_chat_id()
            return ([], 'idle',
                    f'✅ 已自动开启新对话（会话 id：`{cid}`），直接输入即可。',
                    gr.update(choices=_choices()), cid)

        def _load(sel):
            if not sel:
                return [], 'idle', '请先选择历史会话。', gr.update(), ''
            msgs = load_chat(sel)
            return (fmt_msgs(msgs), 'idle',
                    f'已加载会话 {sel}（{len(msgs) // 2} 轮），可直接继续提问。',
                    gr.update(), sel)

        def _new():
            cid = new_chat_id()
            return [], 'idle', f'✅ 已开启新对话（会话 id：`{cid}`）。', \
                gr.update(choices=_choices()), cid

        def _del(sel):
            if sel:
                delete_chat(sel)
            return gr.update(choices=_choices())

        def _upload(files):
            if not files:
                return '<span style="color:#c33">未收到文件，请重新选择。</span>', []
            msg, previews = ingest_upload(files)
            ok = '✅' in msg or '已入素材池' in msg
            color = '#0a7d32' if ok else '#c0392b'
            html = f'<div style="padding:6px 10px;background:#f4fbf6;border:1px solid #9dd6ae;'
            html += f'border-radius:6px;color:{color};font-weight:600">{msg.replace(chr(10), "<br>")}</div>'
            return html, previews

        load_btn.click(_load, hist_dd, out)
        new_btn.click(_new, None, out)
        del_btn.click(_del, hist_dd, hist_dd)
        ref_btn.click(lambda: gr.update(choices=_choices()), None, hist_dd)
        up_btn.upload(_upload, up_btn, [up_status, gallery])
        send_btn.click(send, [hist_state, cid_state, box], out)
        box.submit(send, [hist_state, cid_state, box], out)
        demo.load(_auto_new, None, out)

    print(f'Qwen-Agent 调度器 Web UI: http://127.0.0.1:{port}')
    print(f'项目根目录: {PROJECT_ROOT}')
    print(f'历史会话目录: {CHATS_DIR}')
    demo.launch(server_name='0.0.0.0', server_port=port, share=share,
                show_error=True, quiet=True)