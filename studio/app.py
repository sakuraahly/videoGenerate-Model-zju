#!/usr/bin/env python3
"""H3 视频生成工坊 — 魔搭创空间应用（v2.4：Agent = 工具集 + 外置大脑）。

结构（2026-09-10 重构：v1.x 的展示页 → 专业创作台）：
  Tab1 创作台：任务类型 / 提示词 / 参考图上传 / 参数（分辨率·时长·音色·字幕）→ 提交 → 任务区（状态·预览·下载·历史）
  Tab2 样片墙：本机生成样片（可播放）
  Tab3 能力与部署：能力点、制作流程、部署与"真实生成"说明
后端（studio/backend.py）三实现：demo（默认，免费 CPU）/ remote（引擎网关）/ local（空间内 GPU 模型）。
环境变量：STUDIO_BACKEND=demo|remote|local（默认 auto）；REMOTE_API + STUDIO_TOKEN 走远程。
"""
from __future__ import annotations

import argparse
import html as _html
import json
import os
import queue as _queue
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ASSETS = HERE / "assets"
sys.path.insert(0, str(HERE))

from backend import pick_backend  # noqa: E402

DEFAULT_SHOW = {
    "title": "H3 视频生成工坊",
    "tagline": "一句创意 / 一张参考图 / 一句台词 → 本地大模型生成 → 台词·字幕·口型成品链 → ASR 验收交付",
    "hero_points": [
        "文生视频 / 图生视频 / 多参考图连贯 / 首末帧转场",
        "说话镜头：一句台词→H3 自适应音色亲口说出（音画同时长）+ ASR 验收",
        "故事片主控：剧本→分镜→台词→成片 单命令出片（9 段连贯·可断点续跑）",
        "台词先行+发音回环；字幕可选；ComfyUI 全链一体化；1280×736/4x 超分档",
    ],
    "flow_steps": [
        "① 灵感：一句话剧情；也可上传参考图锁定场景/角色/道具",
        "② 提示词：英文提示词+参考图契约（<Picture N> 全片锁定）+故事背景/角色形象卡自动注入",
        "③ 生成：ComfyUI + MiniMax H3 本地推理（本机 GPU，日间≤768p，夜间 1080p 档）",
        "④ 成品链：台词先行（剧本台词表）→ CosyVoice2 真台词 → 口型同步 → 字幕=台词原文烧录 → 旁白垫轨 → 整脸无框修复",
        "⑤ 验收：SenseVoice ASR 双轨验真（台词窗/旁白窗；发音回环不达标自动用发音写法重试）→ 交付命名归档",
    ],
    "samples": [
        {"file": "01_direct_720p.mp4", "cover": "01_direct_720p_cover.jpg",
         "title": "720p 直出 · 病房戏", "desc": "1280×736/24fps/5.17s；剧情直出+成品链", "style": "电影感"},
        {"file": "02_ref2v_720p.mp4", "cover": "02_ref2v_720p_cover.jpg",
         "title": "多参考图连贯（r2v）", "desc": "3 张参考图（角色/场景）全片锁定；720p", "style": "电影感"},
        {"file": "03_talk_nobox.mp4", "cover": "03_talk_nobox_cover.jpg",
         "title": "真台词 · 无框终版", "desc": "角色真的说出设定台词；整脸重渲染无贴皮框", "style": "真实"},
        {"file": "04_keep_orig.mp4", "cover": "04_keep_orig_cover.jpg",
         "title": "角色原声保留 · 旁白错开", "desc": "台词=角色原声+字幕；旁白独立垫轨（不干扰话语）", "style": "纪录片"},
        {"file": "05_comfy_chain.mp4", "cover": "05_comfy_chain_cover.jpg",
         "title": "ComfyUI 全链一体化", "desc": "生成→48fps 插帧→整脸修复→配音字幕→ASR 全链", "style": "真实"},
        {"file": "06_rife_48fps.mp4", "cover": "06_rife_48fps_cover.jpg",
         "title": "RIFE 48fps 插帧", "desc": "24fps→48fps 高帧率（插帧后画面顺滑）", "style": "纪录片"},
        {"file": "07_story_script.mp4", "cover": "07_story_script_cover.jpg",
         "title": "剧本→故事片（主控）", "desc": "希区柯克《油价涨了》短篇：剧本 JSON→9 段连贯+4 句真台词字幕；断点续跑", "style": "电影感"},
        {"file": "08_talk_one.mp4", "cover": "08_talk_one_cover.jpg",
         "title": "说话镜头（H3 自适应音色）", "desc": "一句台词→按语音时长生成→H3 自己选音色说话（音画同时长）+ ASR 验收 1.000", "style": "真实"},
    ],
    "voices": [("H3 自适应（按人物形象）", "h3"), ("中文·男声 yunxi", "yunxi"),
               ("中文·女声 xiaoxiao", "xiaoxiao"), ("英文·男声 daler", "daler"),
               ("英文·女声 aria", "aria")],
    "styles": ["电影感", "真实", "纪录片"],
    "footer": "免费 CPU 档=演示模式（不产生任务）；真实生成需 GPU 硬件档或配置引擎网关（见「能力与部署」）。",
}


# ---------- 会话注册表（2026-09-10 加固） ----------
# 为什么不把客户端对象放进 gr.State：那会把『用户 key + 作业台账』的对象交给前端状态层保管；
# 这里改成 State 只存**不透明随机 id**，客户端（含 key）只活在服务端内存里，并且有寿命与总量上限。
_SESS = {}                                   # sid -> {'client': AgentClient, 'ts': float}
_SESS_LOCK = None


def _sess_limits():
    import os as _os
    try:
        ttl = int(float(_os.environ.get('SESSION_TTL_SEC') or 7200))
    except Exception:  # noqa: BLE001
        ttl = 7200
    try:
        cap = int(float(_os.environ.get('SESSION_MAX') or 200))
    except Exception:  # noqa: BLE001
        cap = 200
    return max(60, ttl), max(1, cap)


def _session_client(sid: str, ov: dict):
    """按会话取/建客户端：State 里只带 sid；过期的会话（连同其内存里的 key）自动清掉。"""
    import secrets, threading as _th, time as _t
    global _SESS_LOCK
    if _SESS_LOCK is None:
        _SESS_LOCK = _th.Lock()
    ttl, cap = _sess_limits()
    now = _t.time()
    with _SESS_LOCK:
        for k in [k for k, v in _SESS.items() if now - v['ts'] > ttl]:
            _SESS.pop(k, None)                      # 过期即释放（key 不长期驻留）
        rec = _SESS.get(sid or '')
        cli = rec['client'] if rec else None
        if not sid or rec is None:
            sid = secrets.token_hex(8)              # 不透明随机 id（State 里只有它）
        while len(_SESS) >= cap:                    # 超量丢最旧
            oldest = min(_SESS.items(), key=lambda kv: kv[1]['ts'])[0]
            _SESS.pop(oldest, None)
    cli = _client_from(ov, cli)
    with _SESS_LOCK:
        _SESS[sid] = {'client': cli, 'ts': now}
    return sid, cli


def session_count() -> int:
    """当前活跃会话数（给运维/自检用）。"""
    with _SESS_LOCK if _SESS_LOCK else __import__('contextlib').nullcontext():
        return len(_SESS)


def _shared_client():
    """进程级客户端（仅用于启动自检/无会话场景）。**不要用来处理用户请求**——

    2026-09-10 BYOK 改造：用户密钥必须按会话隔离，处理请求一律走 _client_from()。
    """
    global _SHARED_ONE
    if _SHARED_ONE is None:
        from agent_client import AgentClient
        _SHARED_ONE = AgentClient()
    return _SHARED_ONE


_SHARED_ONE = None



# 服务商预设：让「接外部通用大模型」变成点一下（2026-09-10）
PROVIDER_PRESETS = {
    '阿里云百炼（DashScope 兼容模式）': ('https://dashscope.aliyuncs.com/compatible-mode/v1', 'qwen-plus'),
    'DeepSeek': ('https://api.deepseek.com', 'deepseek-chat'),
    '魔搭 API-Inference（社区免费额度）': ('https://api-inference.modelscope.cn/v1', 'Qwen/Qwen3.5-35B-A3B'),
    '智谱 GLM（开放平台）': ('https://open.bigmodel.cn/api/paas/v4', 'glm-4-flash'),
    '自定义（自己填地址与模型名）': ('', ''),
}


def provider_choices():
    return list(PROVIDER_PRESETS.keys())

def _client_from(ov: dict = None, existing=None):
    """按会话构建/更新 AgentClient（BYOK：用户自带密钥优先，且只跟着这个会话）。

    - 同一个会话复用同一个实例 → 作业台账（"查刚才那个任务"）不丢；
    - 用户在页面上改了密钥 → 就地更新凭据，台账仍保留；
    - 不同会话各自一个实例 → 绝不会串用别人的 key。
    """
    from agent_client import AgentClient
    if existing is None:
        return AgentClient(overrides=ov or {})
    try:
        existing.apply_overrides(ov or {})
        return existing
    except Exception:  # noqa: BLE001
        return AgentClient(overrides=ov or {})


def load_show() -> dict:
    try:
        import yaml
        cfg = HERE / "config.yaml"
        if cfg.is_file():
            data = yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}
            show = {k: v for k, v in data.items() if k not in ("sdk", "app_file", "sdk_version")}
            show.update(data.get("showcase") or {})
            for k, v in DEFAULT_SHOW.items():
                show.setdefault(k, v)
            return show
    except Exception:  # noqa: BLE001
        pass
    return dict(DEFAULT_SHOW)


def agent_step(user_text: str, history, image_path=None, client=None) -> dict:
    """Agent 一步（模块级，便于单测）：返回 {'history','trace','video','job','payload'}。

    行为：调用 agent_client.AgentClient().answer()（= 外置大脑决策 + 工具集执行），
    把「工具选择 + 参数 + 将要发出的请求体 + 调用轨迹」写进对话与轨迹区；
    异常兜底成人话，绝不抛给用户。参考图（image_path）会自动转 data URL 注入工具参数。
    """
    history = list(history or [])
    if not (user_text or '').strip():
        return {'history': history, 'trace': None, 'video': None, 'job': None}
    try:
        from agent_client import AgentClient
        out = (client or _shared_client()).answer(user_text, history, image_path=image_path or '')
    except Exception as e:  # noqa: BLE001
        out = {'say': '（agent 层异常：%s）' % str(e)[:150], 'kind': 'error'}
    kind = out.get('kind')
    reply = out.get('say') or ''
    if kind == 'answer':
        reply += "\n\n" + (out.get('text') or '')
    elif kind == 'demo':
        reply += ("\n\n**工具** `%s` → 即将发给视频生成接口的请求体（预览）：\n\n```json\n%s\n```\n\n"
                  "> 演示模式：尚未接入外部生成接口。到「设置 → 变量 / 密钥」填 "
                  "`ENGINE_BASE_URL`（可选 `LLM_*`）后，这里会真实出片。"
                  % (out.get('tool'), json.dumps(out.get('payload') or {}, ensure_ascii=False, indent=2)))
    elif kind == 'remote':
        reply += "\n\n已提交外部生成服务（任务 `%s`）。" % out.get('task')
        if out.get('video'):
            reply += "\n\n成片：%s" % out['video']
    else:
        reply += "\n\n" + (out.get('text') or '')
    history = history + [{"role": "user", "content": user_text},
                         {"role": "assistant", "content": reply}]
    tr = out.get('trace') or {}
    trace_md = ("**模式**：%s　**工具**：%s\n\n```json\n%s\n```"
                % (out.get('mode', '-'), tr.get('tool') or '-',
                   json.dumps(tr, ensure_ascii=False, indent=2)[:1500]))
    job = None
    if kind == 'remote' and out.get('task'):
        job = {"id": str(out['task']), "tool": tr.get('tool') or '-', "status": "running",
               "ts": time.strftime("%H:%M:%S"), "video": out.get('video') or None}
    # 预览优先用空间本地文件(外部 CDN 域名可能被前端校验拦掉)；没有则退回原链接
    preview = out.get('video_local') or out.get('video') or None
    return {'history': history, 'trace': trace_md, 'video': preview,
            'job': job, 'payload': out.get('payload')}


def jobs_table(jobs, client=None, refresh: bool = False) -> str:
    """任务面板渲染（会话内任务 + 可选向外部接口刷新状态）。"""
    jobs = list(jobs or [])
    if not jobs:
        return "_（本会话还没有任务：在下面说一句需求即可）_"
    if refresh and client is not None:
        # 一次刷新最多查 5 个在跑的任务：每次查询都是一次 HTTP 往返，任务多了会把页面拖死
        probed = 0
        for j in jobs:
            if probed >= 5:
                break
            if j.get('status') in ('running', 'queued', 'unknown'):
                probed += 1
                st = client.poll_job(j['id'])
                j['status'] = st.get('status') or j['status']
                if st.get('video_url'):
                    j['video'] = st['video_url']
    rows = ["| 时间 | 任务号 | 工具 | 状态 | 成片 |", "|---|---|---|---|---|"]
    for j in jobs[-12:]:
        v = j.get('video')
        rows.append("| %s | `%s` | %s | %s | %s |"
                    % (j.get('ts', '-'), j.get('id', '-'), j.get('tool', '-'),
                       j.get('status', '-'), ("[打开](%s)" % v) if v else '-'))
    return "\n".join(rows)


# ══════════════════════════════════════════════════════════════════════════════
# 多 Agent Harness：制片看板（一句话出片）+ 模型配置面板 —— 全部是模块级纯函数
# ══════════════════════════════════════════════════════════════════════════════
# 为什么写成纯函数：看板的每一块（状态条/角色卡/剧本/分镜/预检/质检/轨迹/交付）都要能被
# tests/test_studio_board_ui.py 直接断言 —— 不必起 gradio、不必联网、不必有 GPU。
# build_app() 只做三件事：建控件 → 调这里的函数 → 把结果塞进组件。
# 口径（红线，不可逾越）：空间内**不跑任何模型、不推理、不下载权重、不连本机 GPU**；
#   大脑（通用大模型 API）与引擎（视频生成模型 API）都由访客自带；不填 key 时由
#   studio.harness 的内置规则引擎保底 —— 两种大脑共用同一条状态机，看板结构完全一致。

# 表单取值域（与 studio.rules.frames / harness 的口径对齐）
HARNESS_STYLES = ['cinematic', 'documentary', 'anime']
HARNESS_RESOLUTIONS = ['360p', '480p', '540p', '720p', '768p']
HARNESS_CAST_MODES = ['solo', 'duo']

#: 边界话术（交付面板/能力页固定出现，避免任何"空间内出片"的误读）
BOUNDARY_NOTE = '创空间内不跑视频模型（空间零模型、零权重、不推理、不连任何本机 GPU）。'

# 内联样式（不用 <style>/class：看板可能被塞进任何容器，内联最不挑环境）
_ST_BOX = ('border:1px solid #e5e7eb;border-radius:8px;padding:10px;margin:8px 0;'
           'background:#fff;box-shadow:0 1px 2px rgba(0,0,0,.04)')
_ST_CARD = ('flex:1 1 210px;min-width:210px;border:1px solid #e9ecef;border-radius:8px;'
            'padding:8px;background:#fbfbfd;font-size:12.5px;line-height:1.5')
_ST_MUTED = 'color:#6c757d;font-size:12px'
_ST_TABLE = 'width:100%;border-collapse:collapse;font-size:12.5px'
_ST_TH = ('text-align:left;padding:4px 6px;border-bottom:1px solid #dee2e6;'
          'background:#f8f9fa;white-space:nowrap')
_ST_TD = 'padding:4px 6px;border-bottom:1px solid #f1f3f5;vertical-align:top'
_ST_CODE = ('font-family:ui-monospace,Consolas,monospace;font-size:11.5px;'
            'background:#f8f9fa;padding:1px 4px;border-radius:4px')

_STATUS_STYLE = {
    'ok':      ('#0f5132', '#d1e7dd', '成功'),
    'warn':    ('#664d03', '#fff3cd', '警告'),
    'error':   ('#842029', '#f8d7da', '失败'),
    'retry':   ('#4a1d6b', '#e7d6f7', '改写重试'),
    'running': ('#084298', '#cfe2ff', '进行中'),
    'info':    ('#343a40', '#e9ecef', '信息'),
    'pending': ('#6c757d', '#f1f3f5', '待运行'),
}
_RED = '#842029'
_AMBER = '#664d03'
_GREEN = '#0f5132'


# ── 导入 harness / rules：创空间里 cwd 可能就在 studio/，得兜住 ────────────────
def _import_root(modpath: str):
    """按全名导入（如 studio.harness.roles）；失败就把仓库根塞进 sys.path 再试一次。

    为什么不能简单地 `import harness`：harness/rules 内部用的是相对导入
    （`from ..rules import frames`），必须以 `studio.harness` 这个包名加载，
    否则 ImportError。创空间里进程 cwd 可能就是 studio/（sys.path[0]=studio），
    所以这里补一次仓库根。**只读它们，不改它们。**
    """
    import importlib
    try:
        return importlib.import_module(modpath)
    except Exception:                                        # noqa: BLE001
        root = str(HERE.parent)
        if root not in sys.path:
            sys.path.insert(0, root)
        return importlib.import_module(modpath)


def harness_roles():
    """studio.harness.roles（导入失败返回 None：页面降级成人话，不把 UI 打挂）。"""
    try:
        return _import_root('studio.harness.roles')
    except Exception:                                        # noqa: BLE001
        return None


def _fps() -> int:
    """帧率（取自 studio.rules.frames，取不到按 24）—— 不在页面里硬编第二份真相。"""
    try:
        return int(_import_root('studio.rules.frames').FPS)
    except Exception:                                        # noqa: BLE001
        return 24


#: 5 角色的静态说明。harness 可用时以 harness.roles.ROLES 为准；这张表是"harness 导不进来
#: 也要能画出角色分工卡"的兜底（空看板同样画 5 张，保证评审任何时候都看得到分工）。
ROLE_FALLBACK = [
    {'key': 'scriptwriter', 'name': 'StoryWriter', 'title': '编剧',
     'duty': '一句话 → 剧本 JSON（片名/主题/角色卡/台词）',
     'inputs': '访客一句话 + 风格/时长/阵容', 'outputs': 'script（剧本 JSON）'},
    {'key': 'shotplanner', 'name': 'ShotPlanner', 'title': '分镜',
     'duty': '剧本 → 分镜表：帧网格定时长、运镜/光影/情绪、一致性锚点',
     'inputs': 'script + 画幅', 'outputs': 'shots[]（每段可拍）'},
    {'key': 'director', 'name': 'Director', 'title': '导演',
     'duty': '逐段生成完整生产指令：六段式提示词、参数推导、请求体、命令行、参考图槽位',
     'inputs': 'shots[]', 'outputs': 'directives[]（复制即用）'},
    {'key': 'critic', 'name': 'Critic', 'title': '质检',
     'duty': '规则轨 0-10 分 + 改进建议 → 自动改写重试（有界）',
     'inputs': 'shots[] + directives[]', 'outputs': 'critic（分数与问题清单）'},
    {'key': 'editor', 'name': 'Editor', 'title': '剪辑',
     'duty': '交付清单 + 可执行生产包 + 决策轨迹导出',
     'inputs': '全链产物', 'outputs': 'kit / delivery / trace'},
]
_ROLE_SPECS = None


def role_specs() -> list:
    """5 角色说明表（顺序 = 流水线顺序；harness 在就用它的，保证与编排单一真相）。"""
    global _ROLE_SPECS
    if _ROLE_SPECS is None:
        rows = None
        mod = harness_roles()
        try:
            rows = [dict(r) for r in (getattr(mod, 'ROLES', None) or [])] or None
        except Exception:                                    # noqa: BLE001
            rows = None
        _ROLE_SPECS = rows or [dict(r) for r in ROLE_FALLBACK]
    return _ROLE_SPECS


# ── HTML 小组件 ──────────────────────────────────────────────────────────────
def _esc(v) -> str:
    """外部文本（模型产出/访客输入）一律走这里 —— 看板是 HTML，不转义就等于 XSS 口子。"""
    return _html.escape('' if v is None else str(v), quote=True)


def _clip(v, n: int = 160) -> str:
    s = '' if v is None else str(v)
    return s if len(s) <= n else s[:n] + '…'


def _badge(text, kind: str = 'info') -> str:
    fg, bg, _ = _STATUS_STYLE.get(str(kind or 'info'), _STATUS_STYLE['info'])
    return ('<span style="display:inline-block;padding:1px 8px;border-radius:10px;font-size:12px;'
            'font-weight:600;color:%s;background:%s">%s</span>' % (fg, bg, _esc(text)))


def _status_badge(status) -> str:
    """状态徽标：中文标签 + 原始码（既好看，又能对得上 harness 的 status 字段）。"""
    s = str(status or 'pending')
    label = _STATUS_STYLE.get(s, _STATUS_STYLE['info'])[2]
    return ('%s <code style="font-size:11px;color:#6c757d">%s</code>'
            % (_badge(label, s), _esc(s)))


def _ul(items, color: str = '', empty: str = '—') -> str:
    rows = [x for x in (items or []) if str(x).strip()]
    if not rows:
        return '<span style="%s">%s</span>' % (_ST_MUTED, _esc(empty))
    c = 'color:%s;' % color if color else ''
    return ('<ul style="margin:4px 0 0 18px;padding:0;%s">%s</ul>'
            % (c, ''.join('<li>%s</li>' % _esc(x) for x in rows)))


def _panel_html(title, body, extra: str = '') -> str:
    ex = ('<span style="%s;font-weight:400;margin-left:8px">%s</span>' % (_ST_MUTED, _esc(extra))
          if extra else '')
    return ('<div style="%s"><div style="font-weight:700;font-size:15px">%s%s</div>'
            '<div style="margin-top:4px">%s</div></div>' % (_ST_BOX, _esc(title), ex, body))


def _table(head: list, rows: list) -> str:
    """表头转义、行内是已构建好的 HTML（徽标/嵌套列表），所以行不再转义。"""
    th = ''.join('<th style="%s">%s</th>' % (_ST_TH, _esc(h)) for h in head)
    return ('<table style="%s"><thead><tr>%s</tr></thead><tbody>%s</tbody></table>'
            % (_ST_TABLE, th, ''.join(rows)))


# ── 看板取值器（看板 dict → 各部分；任何一层缺失都返回安全的空值）────────────────
def board_dict(board) -> dict:
    return board if isinstance(board, dict) else {}


def board_card(board, name: str) -> dict:
    cards = board_dict(board).get('cards')
    v = cards.get(name) if isinstance(cards, dict) else None
    return v if isinstance(v, dict) else {}


def board_shots(board) -> list:
    cards = board_dict(board).get('cards')
    v = cards.get('shots') if isinstance(cards, dict) else None
    return [s for s in (v or []) if isinstance(s, dict)]


def board_trace(board) -> list:
    return [t for t in (board_dict(board).get('trace') or []) if isinstance(t, dict)]


def board_progress(board) -> dict:
    v = board_dict(board).get('progress')
    return v if isinstance(v, dict) else {}


def board_counts(board) -> dict:
    v = board_dict(board).get('counts')
    return v if isinstance(v, dict) else {}


_BRAIN_LABELS = {'rule': '规则引擎模式（零 key）', 'llm': '访客自带模型（LLM_*）',
                 'agent': '平台 Agent（AGENT_URL）'}


def brain_tier_label(kind, model: str = '') -> str:
    """大脑档位的中文标签（顶部状态条/配置面板共用一份口径）。"""
    k = str(kind or 'rule')
    label = _BRAIN_LABELS.get(k, k)
    if model and k in ('llm', 'agent'):
        label += '：%s' % str(model)
    return label


# ── 1) 顶部状态条 ─────────────────────────────────────────────────────────────
def board_status_html(board, model: str = '') -> str:
    """状态条：state_label / 进度百分比 / 大脑档位 / MODE。"""
    b = board_dict(board)
    if not b:
        return ('<div style="%s">还没有制片方案：在上面写一句话，点「🎬 生成制片方案（零算力）」'
                '—— <b>不填任何 key 也能跑</b>（内置规则引擎，约 1 秒出完整剧本+分镜+生产包）。</div>'
                % _ST_BOX)
    prog = board_progress(b)
    pct = max(0, min(100, int(prog.get('percent') or 0)))
    state = str(b.get('state') or '-')
    skind = 'ok' if state in ('READY', 'DONE') else ('error' if state in ('BLOCKED', 'ERROR') else 'running')
    mkind = 'ok' if str(b.get('mode')) == 'engine' else 'info'
    counts = board_counts(b)
    cnt = ' ｜ '.join('%s %s' % (k, v) for k, v in (
        ('段', counts.get('shots')), ('指令', counts.get('directives')), ('台词', counts.get('lines')),
        ('重试', counts.get('retries')), ('错误', counts.get('errors')), ('告警', counts.get('warnings'))))
    err = ''
    if b.get('error'):
        err = ('<div style="color:%s;margin-top:6px">❌ 编排异常：%s</div>'
               % (_RED, _esc(_clip(b.get('error'), 300))))
    return (
        '<div style="%s">'
        '<div style="font-size:15px;font-weight:700">🎬 制片看板 %s '
        '<span style="%s">state=%s</span></div>'
        '<div style="margin-top:6px">进度 <b>%d%%</b> '
        '<span style="%s">（%s/%s 个状态）</span></div>'
        '<div style="height:10px;background:#e9ecef;border-radius:6px;overflow:hidden;margin-top:4px">'
        '<div style="height:100%%;width:%d%%;background:#0d6efd"></div></div>'
        '<div style="margin-top:8px">大脑档位：%s ｜ MODE：%s ｜ 耗时 %s ms</div>'
        '<div style="margin-top:6px;%s">一句话：%s ｜ %s</div>%s</div>'
        % (_ST_BOX, _badge(b.get('state_label') or state, skind), _ST_MUTED, _esc(state),
           pct, _ST_MUTED, prog.get('done', 0), prog.get('total', 0), pct,
           _badge(brain_tier_label(b.get('brain'), model), 'info'),
           _badge(b.get('mode_label') or b.get('mode') or '-', mkind),
           int(b.get('elapsed_ms') or 0), _ST_MUTED,
           _esc(_clip(b.get('brief') or '（空）', 120)), _esc(cnt), err))


# ── 2) 角色分工卡（多 Agent 分工 + 调度状态的证据面板）────────────────────────
def board_roles_html(board) -> str:
    """5 张角色卡：角色名 / 职责 / 输入→输出 / 状态徽标 / 档位 / 耗时 / 产出摘要。

    即使 harness 没跑（空看板）也照样画出 5 张 —— 分工是架构事实，不该因为一次空输入
    就"看不见 Agent"。
    """
    rows = board_dict(board).get('roles')
    rows = rows if isinstance(rows, dict) else {}
    cards = []
    for spec in role_specs():
        key = str(spec.get('key') or '')
        run = rows.get(key) if isinstance(rows.get(key), dict) else {}
        status = str(run.get('status') or 'pending')
        via = str(run.get('via') or 'rule')
        ms = run.get('ms') if run.get('ms') is not None else 0
        summary = _clip(run.get('summary') or '（还没跑：点「🎬 生成制片方案（零算力）」）', 220)
        cards.append(
            '<div style="%s">'
            '<div style="font-weight:700">%s · %s %s</div>'
            '<div style="margin-top:4px"><b>职责</b>：%s</div>'
            '<div><b>输入 → 输出</b>：%s → %s</div>'
            '<div><b>档位</b>：<code style="%s">%s</code> ｜ <b>耗时</b>：%s ms</div>'
            '<div><b>产出摘要</b>：%s</div></div>'
            % (_ST_CARD, _esc(spec.get('title')), _esc(spec.get('name')), _status_badge(status),
               _esc(spec.get('duty')), _esc(spec.get('inputs')), _esc(spec.get('outputs')),
               _ST_CODE, _esc(via), int(ms), _esc(summary)))
    head = ('<div style="font-weight:700;font-size:15px">🧩 角色分工（5 个 Agent 同跑一条状态机）'
            '<span style="%s;font-weight:400;margin-left:8px">规则引擎档与访客模型档：'
            '角色/状态/轨迹/看板完全一致</span></div>' % _ST_MUTED)
    return ('<div style="%s">%s<div style="display:flex;flex-wrap:wrap;gap:8px;margin-top:6px">%s</div></div>'
            % (_ST_BOX, head, ''.join(cards)))


# ── 3) 剧本卡 ────────────────────────────────────────────────────────────────
def board_script_html(board) -> str:
    """剧本卡：片名/主题/设定/风格/角色卡表/台词表/音色依据。"""
    sc = board_card(board, 'script')
    if not sc:
        return _panel_html('📖 剧本卡（编剧 Agent）',
                           '<span style="%s">还没有剧本：先点「🎬 生成制片方案（零算力）」。</span>'
                           % _ST_MUTED)
    chars = sc.get('characters') if isinstance(sc.get('characters'), dict) else {}
    personas = sc.get('persona_voices') if isinstance(sc.get('persona_voices'), dict) else {}
    lines = sc.get('lines') if isinstance(sc.get('lines'), dict) else {}

    char_rows = []
    for name, desc in chars.items():
        pv = personas.get(str(name)) if isinstance(personas.get(str(name)), dict) else {}
        char_rows.append(
            '<tr data-cast="%s"><td style="%s"><b>%s</b></td><td style="%s">%s</td>'
            '<td style="%s">%s</td><td style="%s">%s</td></tr>'
            % (_esc(name), _ST_TD, _esc(name), _ST_TD, _esc(desc),
               _ST_TD, _esc(pv.get('voice') or '—'), _ST_TD, _esc(pv.get('reason') or '—')))
    char_tbl = (_table(['角色', '形象描述（注入提示词，跨段同一张脸）', '音色', '音色依据'], char_rows)
                if char_rows else '<span style="%s">（本条一句话没有角色：纯空镜/环境片）</span>' % _ST_MUTED)

    line_rows = []
    for seg_no, ln in lines.items():
        ln = ln if isinstance(ln, dict) else {}
        spk = str(ln.get('speaker') or '')
        pv = personas.get(spk) if isinstance(personas.get(spk), dict) else {}
        line_rows.append(
            '<tr data-line="%s"><td style="%s"><b>%s</b></td><td style="%s">%s</td>'
            '<td style="%s">%s</td><td style="%s">%s</td><td style="%s">%s</td></tr>'
            % (_esc(seg_no), _ST_TD, _esc(seg_no), _ST_TD, _esc(spk or '—'),
               _ST_TD, _esc(ln.get('text') or ''), _ST_TD, _esc(ln.get('voice') or pv.get('voice') or '—'),
               _ST_TD, _esc(ln.get('tone') or pv.get('tone') or '—')))
    line_tbl = (_table(['段号', '说话人', '台词（原文，不进画面提示词）', '音色', '语气'], line_rows)
                if line_rows else '<span style="%s">（全片无台词：不需要配音，验收按"静默镜"卡）</span>' % _ST_MUTED)

    meta = ('片名：<b>%s</b> ｜ 来源：%s ｜ 风格：<code style="%s">%s</code> ｜ 母题：%s ｜ '
            '全长 %.2fs / %s 帧 ｜ 画幅 %s'
            % (_esc(sc.get('title') or '（未命名）'), _esc(sc.get('source') or '—'),
               _ST_CODE, _esc(sc.get('style') or '—'), _esc(sc.get('motif_label') or sc.get('motif') or '—'),
               float(sc.get('total_seconds') or 0), _esc(sc.get('total_frames') or 0),
               _esc(sc.get('resolution') or '—')))
    setting = ('<div>设定：%s</div><div>主题：%s</div>'
               % (_esc(_clip(sc.get('setting'), 300)), _esc(_clip(sc.get('theme'), 300))))
    body = (meta + setting
            + '<div style="margin-top:6px;font-weight:600">角色卡</div>' + char_tbl
            + '<div style="margin-top:6px;font-weight:600">台词表</div>' + line_tbl)
    return _panel_html('📖 剧本卡（编剧 Agent：一句话 → 剧本 JSON）', body)


# ── 4) 分镜表（照做就能拍 / 照做就能验）───────────────────────────────────────
def shot_accept_rules(shot: dict, story: dict = None) -> list:
    """单段验收规则（**至少两条**）—— 写进分镜表，零 key 时也"照做就能验"。

    口径统一：优先用 studio.rules.delivery.accept_rules（与生产包 accept.md 同一套话术），
    取不到就本地兜底，但两条硬判据（帧网格 / 无文字水印）任何情况下都在。
    """
    shot = shot if isinstance(shot, dict) else {}
    story = story if isinstance(story, dict) else {}
    line = shot.get('line') if isinstance(shot.get('line'), dict) else None
    text = str((line or {}).get('text') or '')
    try:
        frames = int(shot.get('frames') or 0)
    except (TypeError, ValueError):
        frames = 0
    res = str(shot.get('resolution') or story.get('resolution') or '480p')
    try:
        rules = list(_import_root('studio.rules.delivery').accept_rules(frames, bool(line), text, res))
        if len(rules) >= 2:
            return rules
    except Exception:                                        # noqa: BLE001
        pass
    fps = float(_fps() or 24)
    rules = ['帧数 %d（5+17k 网格 @ %d fps）→ %.2fs ｜ 画幅 %s' % (frames, int(fps), frames / fps, res),
             '画面无任何文字/字幕/水印（正向提示词已不含文字指令）']
    rules.append('台词「%s」由模型原声说出且口型同步（唇动无声即不合格）' % text
                 if (line and text) else '该段无人说话：出现唇动/口型即视为不合格')
    cast = [str(c) for c in (shot.get('cast') or [])]
    if cast:
        slots = [s for s in (shot.get('ref_slots') or []) if isinstance(s, dict)]
        rules.append('人物与参考图一致（跨段同一张脸）：%s ← %s'
                     % ('/'.join(cast), (slots[0].get('path') if slots else 'refs/%s.png' % cast[0])))
    if shot.get('anchor'):
        rules.append('本段已开一致性锚点：与前后段同一张脸、同一套光影与调色')
    return rules


def board_shots_html(board) -> str:
    """分镜表：段号 / 帧数 / 秒数 / 是否说话+台词 / 运镜 / 锚点 / 参考图槽位 / 提示词 / 验收规则。

    "零 key 照做就能拍"意味着每一行必须自足：提示词（可折叠，长文本不挤坏表格）、
    精确到帧的时长、说不说话与台词、一致性锚点、参考图槽位、以及 ≥2 条验收规则。
    """
    shots = board_shots(board)
    if not shots:
        return _panel_html('🎥 分镜表（分镜 Agent：照做就能拍）',
                           '<span style="%s">还没有分镜：先点「🎬 生成制片方案（零算力）」。</span>'
                           % _ST_MUTED)
    sc = board_card(board, 'script')
    rows = []
    for s in shots:
        line = s.get('line') if isinstance(s.get('line'), dict) else None
        text = str((line or {}).get('text') or '')
        if line:
            talk = ('%s <b>%s</b><div style="%s">音色 %s ｜ 说话人 %s ｜ 语气 %s</div>'
                    % (_badge('说话', 'ok'), _esc(text), _ST_MUTED,
                       _esc(line.get('voice') or '—'), _esc(line.get('speaker') or '—'),
                       _esc(line.get('tone') or '—')))
        else:
            talk = ('%s <span style="%s">该段无人说话（出现唇动/口型即不合格）</span>'
                    % (_badge('静默', 'info'), _ST_MUTED))
        slots = [x for x in (s.get('ref_slots') or []) if isinstance(x, dict)]
        slot_html = ('<br>'.join('%s → <code style="%s">%s</code>（%s）'
                                 % (_esc(x.get('slot')), _ST_CODE, _esc(x.get('path')), _esc(x.get('name')))
                                 for x in slots)
                     or '<span style="%s">纯文生视频（无参考图）</span>' % _ST_MUTED)
        rules = shot_accept_rules(s, sc)
        rules_html = '<ul style="margin:2px 0 0 16px;padding:0">%s</ul>' % ''.join(
            '<li>%s</li>' % _esc(r) for r in rules)
        prompt = str(s.get('prompt') or '')
        prompt_html = ('<details><summary style="cursor:pointer;color:#0d6efd">'
                       '展开提示词（%d 字符）</summary>'
                       '<div style="margin-top:4px;white-space:pre-wrap;%s;background:#f8f9fa;'
                       'padding:6px;border-radius:6px">%s</div></details>'
                       % (len(prompt), _ST_CODE, _esc(prompt)))
        anchor = _badge('已锁定', 'ok') if s.get('anchor') else _badge('未开', 'warn')
        rows.append(
            '<tr data-shot="%s">'
            '<td style="%s"><b>#%s</b><div style="%s">%s</div></td>'
            '<td style="%s"><b>%s</b> 帧</td>'
            '<td style="%s"><b>%.2f</b> s<div style="%s">%s</div></td>'
            '<td style="%s">%s</td>'
            '<td style="%s">%s</td>'
            '<td style="%s">%s<div style="%s">seed %s</div></td>'
            '<td style="%s">%s</td>'
            '<td style="%s">%s</td>'
            '<td style="%s">%s</td></tr>'
            % (_esc(s.get('idx')), _ST_TD, _esc(s.get('idx')), _ST_MUTED, _esc(s.get('beat')),
               _ST_TD, _esc(s.get('frames')), _ST_TD, float(s.get('seconds') or 0), _ST_MUTED,
               _esc(s.get('resolution')), _ST_TD, talk, _ST_TD, _esc(_clip(s.get('camera'), 90)),
               _ST_TD, anchor, _ST_MUTED, _esc(s.get('seed')), _ST_TD, slot_html,
               _ST_TD, prompt_html, _ST_TD, rules_html))
    total_frames = sum(int(x.get('frames') or 0) for x in shots)
    total_sec = sum(float(x.get('seconds') or 0) for x in shots)
    extra = ('%d 段 ｜ 合计 %d 帧 / %.2fs ｜ 说话段 %d ｜ 每段都带提示词·帧数·台词·锚点·参考图槽位·验收规则'
             % (len(shots), total_frames, total_sec, sum(1 for x in shots if x.get('line'))))
    return _panel_html('🎥 分镜表（分镜 Agent：照做就能拍）',
                       _table(['段', '帧数', '秒数 / 画幅', '是否说话 + 台词', '运镜',
                               '一致性锚点', '参考图槽位', '提示词（英文·六段式）', '验收规则（≥2 条）'], rows),
                       extra)


# ── 5) 预检面板 ──────────────────────────────────────────────────────────────
def board_prelint_html(board) -> str:
    """预检（花算力之前的规则闸门）：errors 红、warnings 黄、stats 一行；干净就绿。"""
    pl = board_card(board, 'prelint')
    if not pl:
        return _panel_html('🚦 预检面板（质检 Agent · 规则闸门）',
                           '<span style="%s">还没预检：先点「🎬 生成制片方案（零算力）」。</span>' % _ST_MUTED)
    errs = [str(e) for e in (pl.get('errors') or []) if str(e).strip()]
    warns = [str(w) for w in (pl.get('warnings') or []) if str(w).strip()]
    grid_bad = [x for x in (pl.get('grid_bad') or []) if str(x).strip() != '']
    stats = pl.get('stats') if isinstance(pl.get('stats'), dict) else {}
    st_txt = ('段 %s ｜ 总 %.2fs / %s 帧 ｜ 台词段 %s ｜ 有人物段 %s'
              % (stats.get('segments', 0), float(stats.get('seconds') or 0), stats.get('frames', 0),
                 stats.get('lines', 0), stats.get('cast_segments', 0)))
    if pl.get('ok') and not errs and not grid_bad:
        head = ('<div data-precheck="pass" style="color:%s;background:#d1e7dd;padding:6px 8px;'
                'border-radius:6px;font-weight:700">✅ 预检通过（帧网格 / 台词铁律 / 原创性 / '
                '可执行性 全部达标）</div>' % _GREEN)
    else:
        head = ('<div data-precheck="fail" style="color:%s;background:#f8d7da;padding:6px 8px;'
                'border-radius:6px;font-weight:700">❌ 预检未通过：%d 条硬伤%s —— '
                '不合格先改稿，不浪费算力</div>'
                % (_RED, len(errs) or len(grid_bad),
                   ('，帧网格异常段 %s' % _esc(grid_bad)) if grid_bad else ''))
    err_html = ('<div style="margin-top:6px;font-weight:600;color:%s">错误（必须先改）</div>%s'
                % (_RED, _ul(errs, color=_RED, empty='（无）')))
    warn_html = ('<div style="margin-top:6px;font-weight:600;color:%s">告警（建议改）</div>%s'
                 % (_AMBER, _ul(warns, color=_AMBER, empty='（无）')))
    body = (head + ('<div style="margin-top:6px;%s">%s</div>' % (_ST_MUTED, _esc(st_txt)))
            + err_html + warn_html
            + ('<div style="margin-top:6px;%s">%s</div>' % (_ST_MUTED, _esc(pl.get('summary') or ''))))
    return _panel_html('🚦 预检面板（质检 Agent · 规则闸门：不合格先改，不浪费算力）', body)


# ── 6) 质检面板 ──────────────────────────────────────────────────────────────
def board_critic_html(board) -> str:
    """质检（Critic）：段均分 / 最低分 / 改写轮数 + 每段分数与 issues（含 fix 建议）。"""
    cr = board_card(board, 'critic')
    if not cr:
        return _panel_html('🧪 质检面板（Critic：0-10 规则轨）',
                           '<span style="%s">还没质检：先点「🎬 生成制片方案（零算力）」。</span>' % _ST_MUTED)
    rows = []
    for row in (cr.get('shots') or []):
        row = row if isinstance(row, dict) else {}
        issues = [i for i in (row.get('issues') or []) if isinstance(i, dict)]
        iss_html = ''.join(
            '<li style="color:%s">%s <b>%s</b>：%s%s</li>'
            % (_RED if str(i.get('level')) == 'error' else _AMBER,
               '❌' if str(i.get('level')) == 'error' else '⚠️', _esc(i.get('code')),
               _esc(i.get('msg')), ('　→ 建议：%s' % _esc(i.get('fix'))) if i.get('fix') else '')
            for i in issues) or ('<span style="%s">（无问题）</span>' % _ST_MUTED)
        detail = row.get('detail') if isinstance(row.get('detail'), dict) else {}
        det_txt = ' ｜ '.join('%s %.2f' % (_esc(k), float(v or 0)) for k, v in detail.items())
        rows.append(
            '<tr data-critic="%s"><td style="%s"><b>#%s</b></td>'
            '<td style="%s"><b>%.2f</b></td><td style="%s">%s</td>'
            '<td style="%s"><span style="%s">%s</span></td>'
            '<td style="%s"><ul style="margin:0 0 0 16px;padding:0">%s</ul></td></tr>'
            % (_esc(row.get('idx')), _ST_TD, _esc(row.get('idx')), _ST_TD, float(row.get('score') or 0),
               _ST_TD, _badge('通过' if row.get('pass') else '未达标', 'ok' if row.get('pass') else 'warn'),
               _ST_TD, _ST_MUTED, det_txt, _ST_TD, iss_html))
    extra = ('段均 %.2f/10 ｜ 最低 %.2f ｜ 改写 %s 轮 ｜ 硬伤 %s'
             % (float(cr.get('score') or 0), float(cr.get('min_score') or 0),
                cr.get('rounds', 0), cr.get('errors', 0)))
    return _panel_html('🧪 质检面板（Critic：规则轨打分 + 自动改写重试）',
                       _table(['段', '分数', '结论', '五维明细', '问题与修改建议'], rows), extra)


# ── 7) 决策轨迹表（反馈闭环与可观测的证据）────────────────────────────────────
def board_trace_html(board) -> str:
    """trace 一行一条：序号 / 状态机 / 角色 / 动作 / 结果徽标 / 档位 / 耗时 / 说明。

    行数严格等于 len(trace) —— 页面看到的轨迹就是 harness 记的轨迹，不加工不省略。
    """
    trace = board_trace(board)
    if not trace:
        return _panel_html('🧭 决策轨迹（反馈闭环与可观测）',
                           '<span style="%s">还没有轨迹：先点「🎬 生成制片方案（零算力）」。</span>' % _ST_MUTED)
    rows = []
    for t in trace:
        rows.append(
            '<tr data-trace-i="%s"><td style="%s"><b>%s</b></td>'
            '<td style="%s"><code style="%s">%s</code></td>'
            '<td style="%s">%s</td><td style="%s">%s</td>'
            '<td style="%s">%s</td><td style="%s">%s</td>'
            '<td style="%s">%s ms</td><td style="%s">%s</td></tr>'
            % (_esc(t.get('i')), _ST_TD, _esc(t.get('i')), _ST_TD, _ST_CODE, _esc(t.get('state')),
               _ST_TD, _esc(t.get('role')), _ST_TD, _esc(t.get('action')),
               _ST_TD, _status_badge(t.get('status')), _ST_TD, _esc(t.get('via')),
               _ST_TD, int(t.get('ms') or 0), _ST_TD, _esc(_clip(t.get('detail'), 300))))
    return _panel_html('🧭 决策轨迹（谁在什么时候做了什么、结果如何）',
                       _table(['#', '状态机', '角色', '动作', '结果', '档位', '耗时', '说明'], rows),
                       '%d 步 ｜ 这份表就是 trace.json 的页面版' % len(trace))


# ── 8) 交付说明面板 ──────────────────────────────────────────────────────────
def board_delivery_html(board) -> str:
    """交付说明：AI 声明 / 片尾建议 / 交付清单 / claims 的"可说-不可说"边界。"""
    dl = board_card(board, 'delivery')
    kit = board_card(board, 'kit')
    if not dl and not kit:
        return _panel_html('📦 交付说明（剪辑 Agent）',
                           '<span style="%s">还没有交付清单：先点「🎬 生成制片方案（零算力）」。'
                           '<br>%s</span>' % (_ST_MUTED, _esc(BOUNDARY_NOTE)))
    claims = dl.get('claims') if isinstance(dl.get('claims'), dict) else {}
    must_not = [str(x) for x in (claims.get('must_not_say') or [])]
    may = [str(x) for x in (claims.get('may_say') or [])]
    stat = ('%s ｜ %s 段 ｜ %.2fs / %s 帧 ｜ 说话段 %s ｜ 画幅 %s'
            % (_esc(dl.get('title') or '—'), dl.get('shots', 0), float(dl.get('seconds') or 0),
               dl.get('frames', 0), dl.get('talking_shots', 0), _esc(dl.get('resolution') or '—')))
    kit_html = ''
    if kit:
        # 生产包 = 评审能直接拿去复现的那份东西：把文件名与体量摊开给他看。
        # 摘要形状（harness 定的）：files = {文件名: {'chars': N, 'lines': M}}；旧形状是纯文本，两种都认。
        files = kit.get('files') if isinstance(kit.get('files'), dict) else {}

        def _kit_file_li(name, meta):
            if isinstance(meta, dict):
                return '<li><code style="%s">%s</code> <span style="%s">（%s 字符 / %s 行）</span></li>' % (
                    _ST_CODE, _esc(name), _ST_MUTED, int(meta.get('chars') or 0), int(meta.get('lines') or 0))
            text = str(meta or '')
            return '<li><code style="%s">%s</code> <span style="%s">（%d 字符 / %d 行）</span></li>' % (
                _ST_CODE, _esc(name), _ST_MUTED, len(text), text.count(chr(10)) + 1)

        flist = ''.join(_kit_file_li(n, m) for n, m in files.items())
        kit_html = ('<div data-kit="1" style="margin-top:6px;background:#f6f8fa;padding:6px 8px;'
                    'border-radius:6px"><span style="font-weight:600">📦 生产包（拿到就能跑）</span>'
                    '<div style="%s">%s ｜ %d 个文件 ｜ %s 字节 ｜ %s 段 / %s s</div>'
                    '<ul style="margin:4px 0 0 18px;padding:0">%s</ul>'
                    '<div style="margin-top:4px;%s">%s</div></div>'
                    % (_ST_MUTED, _esc(kit.get('name') or kit.get('zip_name') or '—'),
                       len(files), kit.get('bytes', 0), kit.get('shots', '—'), kit.get('seconds', '—'),
                       flist or '<li>（空）</li>', _ST_MUTED,
                       _esc('点「⬇️ 下载生产包」取走 zip：里面是 plan.json / jobs.jsonl / '
                            'run_plan.py / accept.md / trace.json，复制即用。')))
    engine = dl.get('engine') if isinstance(dl.get('engine'), dict) else {}
    engine_html = ''
    if engine:
        # 真出片分支：成片/失败/为什么失败都要摊开（失败如实标注，不用"已完成"糊过去）
        erows = [r for r in (engine.get('rows') or []) if isinstance(r, dict)]
        etbl = _table(['段', '类型', '结果', '状态', '耗时', '成片 / 失败原因'], [
            '<tr data-engine-shot="%s"><td style="%s"><b>#%s</b></td><td style="%s">%s</td>'
            '<td style="%s">%s</td><td style="%s">%s</td><td style="%s">%s s</td><td style="%s">%s</td></tr>'
            % (_esc(r.get('idx')), _ST_TD, _esc(r.get('idx')), _ST_TD, _esc(r.get('kind') or '—'),
               _ST_TD, _badge('已成片' if r.get('ok') else '失败', 'ok' if r.get('ok') else 'error'),
               _ST_TD, _esc(r.get('status') or '—'), _ST_TD,
               _esc(r.get('elapsed') if r.get('elapsed') is not None else '—'),
               _ST_TD, _esc(_clip(r.get('file') or r.get('video_url') or r.get('error') or '—', 140)))
            for r in erows]) if erows else ''
        engine_html = ('<div data-engine="1" style="margin-top:6px;background:#eef6ff;padding:6px 8px;'
                       'border-radius:6px"><span style="font-weight:600">🎥 引擎出片结果'
                       '（算力在访客自己的引擎上）</span>'
                       '<div style="%s">%s ｜ 成片 %s 段 ｜ 失败 %s 段</div>%s%s</div>'
                       % (_ST_MUTED, _esc(engine.get('summary') or engine.get('describe') or '—'),
                          engine.get('done', '—'), engine.get('failed', '—'), etbl,
                          ('<div style="margin-top:4px">%s</div>' % _esc(engine.get('advice')))
                          if engine.get('advice') else ''))
    body = [
        '<div data-delivery="stat" style="%s">%s</div>' % (_ST_MUTED, stat),
        '<div data-delivery="disclaimer" style="margin-top:6px;color:%s;background:#f8f9fa;'
        'padding:6px 8px;border-radius:6px">📢 AI 声明：%s</div>'
        % (_RED, _esc(dl.get('ai_disclaimer') or '（缺 AI 生成声明，交付前必须补）')),
        '<div style="margin-top:6px">🎞 片尾建议：%s</div>' % _esc(dl.get('credits_suggestion') or '—'),
        kit_html,
        engine_html,
        '<div style="margin-top:6px;font-weight:600">交付清单</div>%s'
        % _ul(list(dl.get('deliverables') or []), empty='（暂无）'),
        '<div style="margin-top:6px;font-weight:600;color:%s">边界提示（不可说的话）</div>%s'
        % (_RED, _ul(must_not or [BOUNDARY_NOTE], color=_RED)),
        '<div style="margin-top:6px;font-weight:600;color:%s">可以这样说</div>%s'
        % (_GREEN, _ul(may, color=_GREEN, empty='（—）')),
    ]
    if dl.get('vlm_checklist'):
        body.append('<div style="margin-top:6px;font-weight:600">引擎侧可选 VLM 抽检项</div>%s'
                    % _ul(list(dl['vlm_checklist'])))
    if dl.get('honest_notes'):
        body.append('<div style="margin-top:6px;font-weight:600">诚实说明</div>%s'
                    % _ul(list(dl['honest_notes'])))
    body.append('<div style="margin-top:6px;%s">红线：%s</div>' % (_ST_MUTED, _esc(BOUNDARY_NOTE)))
    return _panel_html('📦 交付说明（剪辑 Agent：清单 + 声明 + 话术边界）', ''.join(body))


# ── 9) 看板整页（UI 只调用这一个函数）────────────────────────────────────────
def board_html(board, model: str = '') -> str:
    """看板整页 HTML = 状态条 + 角色卡 + 剧本 + 分镜 + 预检 + 质检 + 轨迹 + 交付。"""
    b = board_dict(board)
    if not b:
        return ('<div style="%s">%s</div>'
                % (_ST_BOX, '还没有制片方案：写一句话（例：一个陪伴机器人，永远同意你说的一切），'
                            '点「🎬 生成制片方案（零算力）」—— 规则引擎档约 1 秒出完整剧本/分镜/'
                            '预检/质检/轨迹/交付清单，<b>不需要任何 key，也不占任何 GPU</b>。'))
    return ''.join([
        board_status_html(b, model=model),
        board_roles_html(b),
        board_script_html(b),
        board_shots_html(b),
        board_prelint_html(b),
        board_critic_html(b),
        board_trace_html(b),
        board_delivery_html(b),
    ])


#: 生产包还没生成时的那行提示（页面初始态）
KIT_IDLE_MD = ('_生产包（zip）生成后会出现在这里（点右边「⬇️ 下载生产包」取走）：'
               'plan.json / jobs.jsonl / commands.md / run_plan.py / accept.md / post.md / '
               'film.srt / trace.json / README.md。_\n\n'
               '**还没有生产包：点「🎬 生成制片方案（零算力）」后这里会出现可下载的 zip。**_')


def kit_note_md(board, zip_path: str = '') -> str:
    """生产包那一行提示：生成了 / 没生成 / 落盘失败，三种都如实说。

    页面两个按钮（规划、出片）共用这一份口径，避免"看起来有包其实下不动"。
    """
    kit = board_card(board, 'kit') if isinstance(board, dict) else {}
    if zip_path:
        return ('✅ **生产包已生成**：`%s`（%s 字节，%d 个文件）→ 点「⬇️ 下载生产包」取走；'
                '里面是 plan.json / jobs.jsonl / run_plan.py / accept.md / trace.json，复制即用。'
                % (kit.get('name') or Path(str(zip_path)).name, kit.get('bytes', 0),
                   len(kit.get('files') or {})))
    if kit:
        return ('⚠️ 生产包已生成但**落盘失败**（下载按钮点不动）：看板上有完整文件清单，'
                '可对照交付说明手动重建。')
    return 'ℹ️ 本次没有生产包：%s。' % ((board or {}).get('state_label') if isinstance(board, dict)
                                        else '方案没跑完')


# ── 编排入口（UI 与单测共用的唯一通道）───────────────────────────────────────
def brain_from_cfg(cfg: dict = None):
    """面板配置 → 大脑对象：页面填了就用页面的；没填退环境变量档；都没有=规则引擎。

    绝不因为"配置不全"报错：规则引擎档必须永远可用（这是零 key 保底的承诺）。
    """
    cfg = dict(cfg or {})
    base = str(cfg.get('llm_base') or '').strip()
    key = str(cfg.get('llm_key') or '').strip()
    model = str(cfg.get('llm_model') or '').strip()
    try:
        make_brain = _import_root('studio.harness.brain').make_brain
        if base and key:
            return make_brain({'llm_base': base, 'llm_key': key, 'llm_model': model})
        return make_brain()          # 环境变量档（AGENT_URL / LLM_*）；都没有 → RuleBrain
    except Exception:                                        # noqa: BLE001
        return None


def kit_builder_of():
    """studio.harness.kit.build_kit（导入失败返回 None —— 没有生产包也要能出方案）。"""
    try:
        return _import_root('studio.harness.kit').build_kit
    except Exception:                                        # noqa: BLE001
        return None


def _safe_kit_builder(build_kit):
    """把生产包构建包一层：**打包失败不能带走整块看板**（如实记一笔警告，方案照出）。"""
    def _build(st):
        try:
            return build_kit(st) or {}
        except Exception as e:                               # noqa: BLE001
            try:
                st.log('editor', 'build_kit', status='warn',
                       detail='生产包构建失败（%s: %s）→ 看板照常出，交付清单仍可用'
                              % (type(e).__name__, str(e)[:120]))
            except Exception:                                # noqa: BLE001
                pass
            return {}
    return _build


def kit_out_dir() -> str:
    """生产包落盘目录：优先复用 agent_client 的"本次进程产物目录"。

    为什么不是随便找个临时目录：launch(allowed_paths=[assets, run_dir]) 只放行了这两个，
    写别处 gradio 会把下载拦掉（页面上点了没反应，比报错更难查）。
    """
    try:
        from agent_client import AgentClient
        return str(AgentClient.run_dir())
    except Exception:                                        # noqa: BLE001
        d = HERE / 'outputs'
        try:
            d.mkdir(parents=True, exist_ok=True)
        except Exception:                                    # noqa: BLE001
            pass
        return str(d)


def save_kit_blob(blob, out_dir=None) -> str:
    """把生产包全量（含 zip 字节）落盘，返回路径供页面下载；失败返回 ''（下载不了不许把页面打挂）。"""
    if not isinstance(blob, dict) or not blob:
        return ''
    try:
        save = _import_root('studio.harness.kit').save_kit
        return str(save(blob, out_dir or kit_out_dir()))
    except Exception:                                        # noqa: BLE001
        return ''


def _error_board(form: dict, msg: str, label: str = '编排异常') -> dict:
    """失败也要"可渲染"：页面显示红字，但不白屏（演示现场最怕的是页面挂掉）。"""
    return {'state': 'ERROR', 'state_label': label, 'mode': 'plan',
            'mode_label': '仅生产计划（未接引擎）', 'brain': 'rule',
            'progress': {'done': 0, 'total': 10, 'percent': 0, 'state': 'ERROR'},
            'brief': str((form or {}).get('brief') or ''), 'roles': {}, 'cards': {},
            'counts': {}, 'trace': [], 'elapsed_ms': 0, 'error': msg}


def plan_state_full(form: dict, cfg: dict = None, brain=None, engine=None) -> dict:
    """与 plan_board_full 同一套编排，但**把 StoryState 也带出来**。

    为什么需要它：真出片时要拿着**同一个** StoryState 逐段提交、逐段刷新看板
    （否则每刷一次就重跑一遍编排，既慢又会丢进度）。
    """
    form = dict(form or {})
    roles_mod = harness_roles()
    if roles_mod is None:
        return {'st': None, 'kit_blob': {},
                'board': _error_board(form, 'studio.harness 导入失败'
                                              '（检查 studio/harness 是否随应用一起部署）',
                                      label='harness 不可用')}
    if brain is None:
        brain = brain_from_cfg(cfg or {})
    kw = {'brain': brain}
    if engine is not None and getattr(engine, 'available', lambda: False)():
        kw['engine'] = engine                     # 只有显式传进来且可用才会真出片
    build_kit = kit_builder_of()
    if build_kit is not None:
        kw['kit_builder'] = _safe_kit_builder(build_kit)
    try:
        st = roles_mod.plan_request(form, **kw)
        board = st.board() if hasattr(st, 'board') else None
        if not isinstance(board, dict):
            raise TypeError('harness 没有返回看板 dict')
        blob = getattr(st, 'kit_blob', None)
        return {'st': st, 'board': board, 'kit_blob': blob if isinstance(blob, dict) else {}}
    except Exception as e:                                   # noqa: BLE001
        return {'st': None, 'kit_blob': {},
                'board': _error_board(form, '%s: %s' % (type(e).__name__, str(e)[:200]))}


def plan_board_full(form: dict, cfg: dict = None, brain=None, engine=None) -> dict:
    """表单 → harness 编排 → {'board': 看板 dict, 'kit_blob': 生产包全量}。

    为什么把 blob 单独带出来而不是塞进看板：zip 字节进看板/JSON 组件会把组件打挂
    —— harness 自己也是这么分的（st.kit=JSON 安全摘要 / st.kit_blob=全量）。
    页面下载走 save_kit_blob(blob) → save_kit() → 落盘路径。

    engine 传了且可用 → harness 会走"真出片"分支（算力在访客自己的引擎上）；
    不传（默认）= 仅生产计划：**本页默认零算力**，绝不偷偷替访客调外部引擎。

    任何异常都落成"可渲染的失败看板"（页面显示红字，但不白屏）——
    演示现场最怕的不是跑不通，是页面挂掉。
    """
    out = plan_state_full(form, cfg=cfg, brain=brain, engine=engine)
    return {'board': out.get('board') if isinstance(out.get('board'), dict)
                    else _error_board(form, '编排没有返回看板'),
            'kit_blob': out.get('kit_blob') if isinstance(out.get('kit_blob'), dict) else {}}


def build_engine(cfg: dict = None):
    """面板里的引擎三项 → Engine 对象（没填提交地址就返回 None = 仅生产计划档）。"""
    cfg = dict(cfg or {})
    base = str(cfg.get('engine_base') or '').strip()
    if not base:
        return None
    try:
        Engine = _import_root('studio.harness.engine').Engine
        return Engine.from_overrides({
            'ENGINE_BASE_URL': base,
            'ENGINE_STATUS_URL': str(cfg.get('engine_status') or '').strip(),
            'ENGINE_API_KEY': str(cfg.get('engine_key') or '').strip(),
        }, poll=max(1.0, float(os.environ.get('HARNESS_ENGINE_POLL', '5') or 5)),
            timeout=int(os.environ.get('HARNESS_ENGINE_TIMEOUT', '1800') or 1800))
    except Exception:                                        # noqa: BLE001
        return None


def board_stream(form: dict, cfg: dict = None, limit: int = 0, model: str = '',
                 engine=None, hold: dict = None):
    """生成器：**先出规划看板，再逐段出片并实时刷新**（页面按钮的流式回调）。

    为什么用后台线程 + 队列：出片是分钟级的长任务，Gradio 的同步回调会把页面卡死；
    生成器每次 yield 一版看板，访客就能看到"第 N 段正在跑/已成片"，中断也不丢已完成段。
    没有可用引擎时**不假装出片**：只出规划看板，并在提示行里说清楚。
    """
    out = plan_state_full(form, cfg=cfg)              # 规划阶段（零算力）
    st = out.get('st')
    if isinstance(hold, dict):
        # 回填"最新看板 + 生产包全量字节"，供页面「⬇️ 下载生产包」落盘
        # （看板里只放 JSON 安全摘要：zip 字节进看板会把组件打挂）
        hold['board'] = out.get('board') if isinstance(out.get('board'), dict) else {}
        hold['kit_blob'] = out.get('kit_blob') if isinstance(out.get('kit_blob'), dict) else {}
    yield out.get('board'), None, None                # None = 不改会话/提示
    if st is None:
        return
    eng = engine if engine is not None else build_engine(cfg)
    if eng is None or not eng.available():
        yield st.board(), None, ('⚠️ 还没有配置引擎（ENGINE_BASE_URL）→ 本次只出'
                                 '**生产计划 + 生产包**。填上引擎地址后再点「🚀 出片」即可逐段出片。')
        return
    box = _queue.Queue()

    def _worker():
        try:
            harness_roles().run_engine(st, eng, limit=int(limit or 0),
                                       on_event=lambda kind, row: box.put(('ev', '')))
        except Exception as e:                               # noqa: BLE001
            box.put(('err', '%s: %s' % (type(e).__name__, str(e)[:200])))
        finally:
            box.put(('done', ''))

    threading.Thread(target=_worker, daemon=True).start()
    while True:
        try:
            kind, msg = box.get(timeout=2.0)
        except _queue.Empty:
            yield st.board(), None, None                      # 心跳：让页面知道还在跑
            continue
        if kind == 'done':
            break
        if kind == 'err':
            try:
                st.log('orchestrator', 'engine_error', status='error', detail=msg)
            except Exception:                                 # noqa: BLE001
                pass
        yield st.board(), None, None

    # 出片结束后**重打一次生产包**：包里 trace.json 必须含 engine 步骤与成片结果，
    # 否则下载到的 zip 只有"规划证据"，评审看不到"真出片"这一段（诚实性优先于省一次打包）。
    kit_builder = kit_builder_of()
    if kit_builder is not None:
        try:
            full = kit_builder(st)
            if isinstance(full, dict) and full.get('files'):
                st.kit_blob = full
                st.kit = full.get('summary') or {}
                st.log('editor', 'build_kit', detail='出片后重打生产包：%s'
                       % (st.kit.get('summary') or ''),
                       data={'files': list(full.get('files') or {}), 'rebuilt': True})
                if isinstance(hold, dict):
                    hold['kit_blob'] = full
        except Exception as e:                                # noqa: BLE001
            st.log('editor', 'build_kit', status='warn',
                   detail='出片后重打生产包失败（%s）→ 仍交付规划阶段那一份'
                          % type(e).__name__)
    if isinstance(hold, dict):
        hold['board'] = st.board()
    yield st.board(), None, None


def plan_board(form: dict, cfg: dict = None, brain=None, engine=None) -> dict:
    """只要看板 dict 的便捷入口（plan_board_full 的薄包装）。"""
    out = plan_board_full(form, cfg=cfg, brain=brain, engine=engine)
    board = out.get('board')
    return board if isinstance(board, dict) else _error_board(form, '编排没有返回看板')


# ══════════════════════════════════════════════════════════════════════════════
# 🎛 模型配置（我的密钥）：服务商预设 / 会话内存缓存 / 连通性自测
# ══════════════════════════════════════════════════════════════════════════════
# 定案（book-20 v5 凭据策略）：面板**保留、默认可见可填、填了立即生效**；
# 不做"为安全而拦截"的额外动作。作用域只有一条：**仅本会话内存**——
# 不落盘、不进日志、不 print、随会话 TTL 回收（key 只用于发出访客自己指定的那次请求）。
HARNESS_PROVIDER_PRESETS = {
    '魔搭 API-Inference(https://api-inference.modelscope.cn/v1)':
        ('https://api-inference.modelscope.cn/v1', 'deepseek-ai/DeepSeek-V4-Pro'),
    'DeepSeek(https://api.deepseek.com/v1)': ('https://api.deepseek.com/v1', 'deepseek-chat'),
    '智谱(https://open.bigmodel.cn/api/paas/v4)': ('https://open.bigmodel.cn/api/paas/v4', 'glm-4-flash'),
    '百炼(https://dashscope.aliyuncs.com/compatible-mode/v1)':
        ('https://dashscope.aliyuncs.com/compatible-mode/v1', 'qwen-plus'),
    '自定义(OpenAI 兼容)': ('', ''),
}
CFG_FIELDS = ('llm_base', 'llm_model', 'llm_key',
              'engine_base', 'engine_status', 'engine_key', 'engine_model')

_CFG_MEM = {}                       # sid -> {字段..., 'ts': float}（只在进程内存里）
_CFG_LOCK = threading.Lock()
_CFG_CAP = 200


def _cfg_ttl() -> float:
    try:
        return max(60.0, float(os.environ.get('SESSION_TTL_SEC') or 7200))
    except Exception:                                        # noqa: BLE001
        return 7200.0


def harness_provider_choices() -> list:
    return list(HARNESS_PROVIDER_PRESETS.keys())


def preset_values(name) -> tuple:
    """服务商预设 → (Base URL, 模型名)；未知预设给空串（不抛错）。"""
    base, model = HARNESS_PROVIDER_PRESETS.get(str(name or ''), ('', ''))
    return base, model


def cfg_of_form(base, model, key, eng_base='', eng_status='', eng_key='', engine_model='') -> dict:
    """页面控件值 → 配置 dict（键名对齐 harness.brain.make_brain 的 cfg，少一层翻译）。"""
    return {'llm_base': base or '', 'llm_model': model or '', 'llm_key': key or '',
            'engine_base': eng_base or '', 'engine_status': eng_status or '',
            'engine_key': eng_key or '', 'engine_model': engine_model or ''}


def remember_cfg(sid: str, cfg: dict) -> str:
    """把面板填的值（**含 key**）缓存进进程内存，只认这个会话 id；过期/超量自动回收。

    sid 为空就新发一个不透明随机 id（和 agent_client 的会话登记同一套路数）。
    这里**不落盘、不打印**：密钥的生命周期 = 这次会话。
    """
    import secrets
    now = time.time()
    sid = str(sid or '')
    with _CFG_LOCK:
        for k in [k for k, v in _CFG_MEM.items() if now - float(v.get('ts') or 0) > _cfg_ttl()]:
            _CFG_MEM.pop(k, None)
        if not sid:
            sid = secrets.token_hex(8)
        elif sid not in _CFG_MEM and len(_CFG_MEM) >= _CFG_CAP:
            oldest = min(_CFG_MEM.items(), key=lambda kv: float(kv[1].get('ts') or 0))[0]
            _CFG_MEM.pop(oldest, None)
        rec = {'ts': now}
        rec.update({k: ('' if cfg.get(k) is None else str(cfg.get(k))) for k in CFG_FIELDS})
        _CFG_MEM[sid] = rec
    return sid


def recall_cfg(sid: str) -> dict:
    """取回本会话缓存的配置（不含 ts；取不到就是空配置=规则引擎档）。"""
    with _CFG_LOCK:
        rec = _CFG_MEM.get(str(sid or ''))
        return {k: v for k, v in (rec or {}).items() if k in CFG_FIELDS}


def config_notice_md(cfg: dict = None) -> str:
    """配置面板顶部那行**必须显眼**的话：没 key 也能用 + 当前档位 + MODE。"""
    cfg = dict(cfg or {})
    has_brain = bool(str(cfg.get('llm_base') or '').strip() and str(cfg.get('llm_key') or '').strip())
    has_engine = bool(str(cfg.get('engine_base') or '').strip())
    if has_brain:
        brain_line = ('✅ **大脑已配置**（访客自带）→ 当前档位：**访客自带模型（LLM_*）**：%s\n\n'
                      '_规则引擎仍会同时产出一版，由 Critic 判分择优 —— 模型不行也拍得成。_'
                      % ('`%s`' % str(cfg.get('llm_model') or '（未填模型名，用默认）')))
    else:
        brain_line = ('⚠️ **未配置也能用：规则引擎会给出完整剧本/分镜/生产包** —— 现在就是'
                      '**『规则引擎模式（零 key）』**：不填任何 key 也能跑完整条状态机'
                      '（5 角色分工 / 预检闸门 / 质检打分 / 决策轨迹 / 交付清单）。')
    engine_line = ('🎬 **引擎已配置** → MODE = **真出片**：点「🚀 出片」即逐段提交到'
                   '上面的引擎，成片与算力都在你自己那边；点「🎬 生成制片方案」仍只做规划与质检，'
                   '不会碰你的引擎（可先用它看方案再决定要不要花钱出片）。' if has_engine else
                   '🎬 **引擎未配置** → MODE = **仅生产计划**（交付可复制的生产包；%s）' % BOUNDARY_NOTE)
    return ('**🎛 模型配置（我的密钥）** —— 仅本会话内存：不落盘、不进日志\n\n%s\n\n%s\n\n'
            '_🤖 大脑（通用大模型 API，决定"怎么拍"）+ 🎥 引擎（视频生成模型 API，真正出片）'
            '都在你自己那边；本空间只做编排、质检与可执行生产包。'
            '生效优先级：**页面填写 > 空间环境变量 > 内置规则引擎**，实际档位以看板顶部状态条为准。_'
            % (brain_line, engine_line))


def _chat_url(base: str) -> str:
    """OpenAI 兼容地址归一：没写 /chat/completions 就补上（写全了也不重复补）。"""
    b = str(base or '').strip().rstrip('/')
    if not b:
        return ''
    return b if b.endswith('/chat/completions') else b + '/chat/completions'


def _http_category(code: int) -> str:
    return {400: 'model', 401: 'auth', 403: 'auth', 404: 'notfound', 405: 'method',
            429: 'rate'}.get(int(code or 0), 'server' if int(code or 0) >= 500 else 'http')


def _net_problem(e, timeout: float = 15.0) -> dict:
    """网络层异常 → 分类文案（超时/连不上分开说，别让用户猜）。"""
    msg = str(e)
    if isinstance(e, TimeoutError) or 'timed out' in msg.lower():
        return {'ok': False, 'status': 'timeout', 'category': 'timeout',
                'message': '超时（>%gs）→ 网络不通 / 被墙 / Base URL 不可达' % float(timeout)}
    return {'ok': False, 'status': '-', 'category': 'network',
            'message': '连不上（%s）→ 检查 Base URL、代理与出网；原文：%s'
                       % (type(e).__name__, _clip(msg, 160))}


def _http_problem(e, timeout: float = 15.0) -> dict:
    """HTTP 状态 → 分类文案 + 服务端原文（截断 200 字符）。"""
    code = int(getattr(e, 'code', 0) or 0)
    try:
        detail = (e.read() or b'').decode('utf-8', 'replace')
    except Exception:                                        # noqa: BLE001
        detail = ''
    why = {
        400: '请求被拒 → 多半是**模型名**不在该服务商（或参数不被支持）',
        401: '**key 不对**或没有该模型权限',
        403: '**key 不对** / 没有该模型权限（被拒绝）',
        404: '**Base URL 或路径不对**：应形如 `https://xxx/v1`（本空间会自动补 `/chat/completions`）',
        405: '该方法不被支持（多半 Base URL 指到了非 OpenAI 兼容端点）',
        429: '触发**限流**：稍等再试或换 key',
    }.get(code) or ('服务端错误（5xx）→ 稍后再试' if code >= 500 else '未预期的 HTTP 状态')
    return {'ok': False, 'status': code, 'category': _http_category(code),
            'message': 'HTTP %s → %s%s' % (code, why,
                                           ('；原文：%s' % _clip(detail.strip(), 200)) if detail.strip() else '')}


def test_llm_connection(base, model, key, *, timeout: float = 15.0, opener=None) -> dict:
    """探活「大脑」：POST `<base>/chat/completions`，body 为 model + 一条 ping + max_tokens=8。

    只发一条极小请求（不触发生成、费用可控）；失败**必须分类**说清楚，这是可用性证据：
    401/403 → key 不对；404 → Base URL/路径不对；400 → 模型名不对；超时 → 网络。
    `opener` 可注入（单测传假实现，**绝不联网**）。异常在这里全部收口，不抛给 UI。
    """
    missing = [n for n, v in (('Base URL', base), ('模型名', model), ('API Key', key))
               if not str(v or '').strip()]
    if missing:
        return {'ok': False, 'status': '-', 'category': 'config',
                'message': '还没填完：%s（三项都填上才能测；不填也能用规则引擎档）' % '、'.join(missing)}
    payload = {'model': str(model).strip(),
               'messages': [{'role': 'user', 'content': 'ping'}], 'max_tokens': 8}
    req = urllib.request.Request(
        _chat_url(base), data=json.dumps(payload).encode('utf-8'),
        headers={'Content-Type': 'application/json',
                 'Authorization': 'Bearer ' + str(key).strip()})
    send = opener or urllib.request.urlopen
    try:
        with send(req, timeout=timeout) as r:
            raw = r.read().decode('utf-8', 'replace')
            code = int(getattr(r, 'status', 0) or getattr(r, 'code', 0) or 200)
    except urllib.error.HTTPError as e:
        return _http_problem(e, timeout)
    except Exception as e:                                   # noqa: BLE001
        return _net_problem(e, timeout)
    got = ''
    try:
        got = str(json.loads(raw or '{}').get('model') or '')
    except Exception:                                        # noqa: BLE001
        got = ''
    return {'ok': True, 'status': code, 'category': 'ok',
            'message': '连接成功（模型 %s）' % (got or str(model).strip())}


def test_engine_connection(base, status_url='', key='', model='', *,
                           timeout: float = 15.0, opener=None) -> dict:
    """探活「引擎」：有 ENGINE_STATUS_URL 就 GET 它，否则 POST ENGINE_BASE_URL（带 ping 体）。

    没有 key 就不带 Authorization（自建引擎常常不校验）；把 HTTP 状态与错误原文
    （截断 200 字符）显示出来。同样绝不抛异常：连不上只是"没配好"，不该把页面打挂。
    """
    base = str(base or '').strip()
    if not base:
        return {'ok': False, 'status': '-', 'category': 'config',
                'message': '还没填 ENGINE_BASE_URL（视频生成模型接口）；不填 = MODE 仅生产计划，'
                           '一样能交付可复制的生产包'}
    status_url = str(status_url or '').strip()
    target = status_url or base
    headers = {}
    data = None
    if str(key or '').strip():
        headers['Authorization'] = 'Bearer ' + str(key).strip()
    if not status_url:
        headers['Content-Type'] = 'application/json'
        data = json.dumps({'ping': True, 'probe': 'studio', 'model': str(model or '')}).encode('utf-8')
    req = urllib.request.Request(target, data=data, headers=headers)
    send = opener or urllib.request.urlopen
    try:
        with send(req, timeout=timeout) as r:
            raw = r.read().decode('utf-8', 'replace')
            code = int(getattr(r, 'status', 0) or getattr(r, 'code', 0) or 200)
    except urllib.error.HTTPError as e:
        code = int(getattr(e, 'code', 0) or 0)
        try:
            body = (e.read() or b'').decode('utf-8', 'replace')
        except Exception:                                    # noqa: BLE001
            body = ''
        hint = ('地址不通或该方法不被支持（检查 ENGINE_BASE_URL 是否指向推理端点）'
                if code in (404, 405) else
                'key 被拒（检查 ENGINE_API_KEY）' if code in (401, 403) else
                '服务端错误 → 稍后再试' if code >= 500 else '请求被拒（检查请求体契约）')
        return {'ok': False, 'status': code, 'category': _http_category(code),
                'message': 'HTTP %s → %s；原文：%s' % (code, hint, _clip(body.strip(), 200) or '（空）')}
    except Exception as e:                                   # noqa: BLE001
        return _net_problem(e, timeout)
    ok = code < 400
    return {'ok': ok, 'status': code, 'category': 'ok' if ok else 'http',
            'message': '引擎可达（HTTP %s）：%s' % (code, _clip(raw.strip(), 200) or '（空响应）')}


def format_conn_result(res) -> str:
    """连通性结果 → 页面文案：「✅ 连接成功（模型 …）」/「❌ 失败：<分类原因>」。"""
    res = res if isinstance(res, dict) else {}
    if res.get('ok'):
        return '✅ %s（HTTP %s）' % (res.get('message'), res.get('status'))
    return '❌ 失败：%s' % res.get('message')


# ── 能力与部署页新增两段（纯文本，可单测）────────────────────────────────────
def boundary_diagram_md() -> str:
    """边界图：左「本空间」→ 中「契约」→ 右「访客自带」。"""
    return """### 边界图：空间内**不推理**，模型全在访客侧
```text
┌────────────────────────────────┐   ┌────────────────────────────┐   ┌──────────────────────────────┐
│ 左：本空间（魔搭免费 CPU）      │   │ 中：契约（唯一接口）        │   │ 右：访客自带（BYOK）          │
│ · 0 个模型 / 0 权重 / 0 GPU     │   │ · ENGINE_* 请求体（一段一单）│   │ · 🤖 大脑：通用大模型 API     │
│ · 只做编排/预检/质检/生产包      │──▶│ · jobs.jsonl（一行一段）    │──▶│   决定"怎么拍"（可选）        │
│ · 密钥只在内存、随会话回收       │   │ · trace.json / accept.md    │   │ · 🎥 引擎：视频生成模型 API   │
│ · 不连任何本机 GPU、不下载权重   │◀──│ · ENGINE_STATUS_URL 回执     │◀──│   真正出片（可选）            │
└────────────────────────────────┘   └────────────────────────────┘   └──────────────────────────────┘
```

| 位置 | 有什么 | 没有什么（红线） |
|---|---|---|
| 本空间（免费 CPU） | 5 个 Agent 角色的编排、规则引擎、预检闸门、质检打分、可执行生产包、决策轨迹 | **不跑视频模型**、不下载权重、**不连任何本机 GPU**、不代付、不共享任何密钥 |
| 契约（接口） | `ENGINE_BASE_URL` 的请求体（每段一单）、`jobs.jsonl`、`ENGINE_STATUS_URL` 回执、`trace.json` | 不规定你用什么模型、什么算力、什么云；契约之下完全自由 |
| 访客自带 | 大脑（通用大模型 API，BYOK，页面可填）+ 引擎（视频生成模型 API，BYOK） | 空间不保存你的 key：只在内存里用一次，随会话回收 |"""


def mode_explain_md() -> str:
    """MODE 说明：未配引擎 = 仅生产计划；配了引擎 = 真出片。"""
    return """### MODE：配了引擎才是「真出片」
| MODE | 触发条件 | 交付物 | 可以怎么说（话术边界） |
|---|---|---|---|
| **仅生产计划**（默认） | 未填 `ENGINE_BASE_URL` | plan.json / jobs.jsonl / commands.md / accept.md / trace.json —— 复制即用 | "交付**可执行的生产包**，由你的引擎复现" |
| **真出片** | 填了 `ENGINE_BASE_URL`（可选 `ENGINE_STATUS_URL` / `ENGINE_API_KEY`） | 上面全部 + 每段成片 | "分镜由本空间规划并质检，**成片由访客自带引擎生成**" |

**三档大脑**（页面「🎛 模型配置」随时可切；规则引擎档永远可用，不需要任何 key）：

| 档 | 条件 | 作用 |
|---|---|---|
| 平台 Agent | `AGENT_URL` + `AGENT_TOKEN` | 魔搭平台 Agent 扮演 5 个角色 |
| 访客自带模型 | 页面填 Base URL + 模型名 + API Key（或 `LLM_*` 环境变量） | 任意 OpenAI 兼容大模型扮演 5 个角色；规则档同时出一版，Critic 判分择优 |
| **内置规则引擎（默认）** | 什么都不填 | 零 key 跑完整条状态机：剧本 / 分镜 / 预检 / 质检 / 轨迹 / 生产包 |

> **红线**：%s
> 免费 CPU 档下，本页的"出片"一律指**在你的引擎上出片**；空间侧只产出可执行方案与验收判据。""" % BOUNDARY_NOTE

def build_app(show: dict):
    import gradio as gr

    backend = pick_backend()
    job_history: list = []

    def _asset(name):
        p = ASSETS / name
        return str(p) if name and p.is_file() else None

    def _sample_for(kind):
        key = {"talk": "08_", "story": "07_", "t2v": "01_", "i2v": "02_"}.get(kind, "01_")
        return next((s for s in show["samples"] if s["file"].startswith(key)), show["samples"][0])

    # ---------------- 创作台 ----------------
    def submit_job(kind, prompt, images, resolution, seconds, voice_src, voice, subtitle, negative):
        sel = {"文生视频": "t2v", "图生视频": "i2v", "说话镜头": "talk", "剧本故事片": "story"}
        k = sel.get(kind, "t2v")
        if not (prompt or "").strip() and k != "i2v":
            return ("⚠️ 请先填写创意/提示词。", None, None,
                    _hist_md(), gr.update())
        imgs = [Path(f).name for f in (images or [])]
        # 语音来源：默认=模型原生语音（自适应音色，不做 TTS 替换）；仅显式选择时才用本地 TTS 音色
        native = str(voice_src or '').startswith('模型原生')
        voice_key = 'h3（模型原生·自适应音色）' if native else dict(show["voices"]).get(voice, voice)
        task = {"kind": k, "prompt": prompt, "images": ", ".join(imgs) or None,
                "resolution": resolution, "seconds": seconds, "voice": voice_key,
                "subtitle": bool(subtitle), "negative": negative}
        t0 = time.time()
        try:
            res = backend.submit(task)
        except Exception as e:  # noqa: BLE001
            return ("❌ 提交失败：%s" % str(e)[:300], None, None, _hist_md(), gr.update())
        dt = time.time() - t0
        rec = _sample_for(k)
        job_history.append({"id": res.get("job_id"), "kind": sel.get(kind, k),
                            "state": res.get("state"), "ts": time.strftime("%H:%M:%S")})
        echo = res.get("echo") or {}
        rows = "\n".join("| %s | %s |" % (kk, vv) for kk, vv in echo.items())
        md = (f"### {'🧪 演示结果' if backend.name == 'demo' else '🚀 已提交'}\n\n"
              f"**任务类型**：{res.get('title')}　**任务号**：`{res.get('job_id')}`\n\n"
              f"| 参数 | 值 |\n|---|---|\n{rows}\n\n"
              f"**规格**：{res.get('spec')}\n\n"
              f"> {backend.note if backend.name == 'demo' else '任务已交给引擎；下方可查看状态与成片。'}\n\n"
              f"_耗时 {dt:.2f}s_")
        video = _asset(rec["file"]) if backend.name != 'remote' else None
        files = None
        if backend.name != 'demo':
            try:
                st = backend.poll(res['job_id'])
                video = st.get('video') or video
            except Exception:  # noqa: BLE001
                pass
        return md, video, files, _hist_md(), gr.update(value="")

    def _hist_md():
        if not job_history:
            return "_（暂无任务记录）_"
        return "\n".join("| %s | %s | %s |" % (h["ts"], h["kind"], h["state"]) for h in job_history[-10:])

    # Gradio 6.x：theme 从 Blocks 移到 launch()
    with gr.Blocks(title=show["title"]) as demo:
        gr.Markdown(f"## 🎬 {show['title']}\n\n{show['tagline']}")

        with gr.Tabs():
            with gr.Tab("🤖 Agent 对话"):
                gr.Markdown("### 直接说需求：agent 自己选工具、定参数、调外部生成接口")

                # ── 🎛 模型配置（我的密钥）—— Agent Tab 顶部常驻 ──────────────────
                # 定案：面板保留、默认可见可填、填了立即生效；**不**做"为安全而拦截"的额外动作。
                # 作用域只有一条：仅本会话内存（模块级 _CFG_MEM + 锁；不落盘、不进日志、不 print）。
                # 未配置时这一行必须显眼：让评审第一眼就知道"没有 key 也拿得到完整产出"。
                hcfg_notice = gr.Markdown(config_notice_md({}))
                hcfg_sid = gr.State("")     # 只放不透明会话 id；key 只在服务端内存
                with gr.Accordion("🎛 模型配置（我的密钥）—— 🤖 大脑（可选）· 🎥 引擎（可选·真出片）",
                                  open=True):
                    gr.Markdown(
                        "**🤖 大脑 · 调用 API 的 key**：填了就由你自己的通用大模型扮演 5 个角色"
                        "（不填也完全可用：内置规则引擎给出完整剧本/分镜/生产包）。\n\n"
                        "**🎥 引擎 · 可选，真出片**：填 `ENGINE_BASE_URL` 才会真正出片；"
                        "不填 = MODE 仅生产计划（交付可复制的生产包）。\n\n"
                        "🔒 这两组凭据**只在本次会话的进程内存**里使用：不落盘、不进日志、不打印，"
                        "随会话回收；换会话/刷新页面请重填。本面板服务于下面的「🎬 一句话出片"
                        "（多 Agent Harness）」；「🤖 Agent 对话」的密钥仍可填在下方「🔑 我的密钥」。")
                    hpreset = gr.Dropdown(label="服务商预设（自动填 Base URL 与模型名，可改）",
                                          choices=harness_provider_choices(),
                                          value=harness_provider_choices()[0])
                    with gr.Row():
                        hbase = gr.Textbox(label="Base URL（OpenAI 兼容）", scale=3,
                                           placeholder="例：https://api-inference.modelscope.cn/v1")
                        hmodel = gr.Textbox(label="模型名（可手填）", scale=2,
                                            placeholder="例：deepseek-ai/DeepSeek-V4-Pro")
                    with gr.Row():
                        hkey = gr.Textbox(label="API Key（你自己的 · 只在本会话内存里）", type="password",
                                          scale=3, placeholder="sk-...（不写盘、不进日志）")
                        htest_brain = gr.Button("🔌 测试连接", scale=1)
                    hbrain_out = gr.Markdown("_点「🔌 测试连接」验证大脑通道：只发一条 ping"
                                             "（max_tokens=8），不触发生成。_")
                    with gr.Accordion("（可选）🎥 引擎 · 真出片：ENGINE_* 视频生成模型接口", open=False):
                        with gr.Row():
                            heng_base = gr.Textbox(label="ENGINE_BASE_URL", scale=3,
                                                   placeholder="例：https://your-engine.example.com/v1")
                            heng_status = gr.Textbox(label="ENGINE_STATUS_URL（异步查询，可留空）", scale=2)
                        with gr.Row():
                            heng_key = gr.Textbox(label="ENGINE_API_KEY", type="password", scale=3)
                            heng_model = gr.Textbox(label="引擎模型名（可留空）", scale=2)
                        htest_eng = gr.Button("🔌 测试引擎", size="sm")
                        heng_out = gr.Markdown("_点「🔌 测试引擎」探活：GET/POST 到 ENGINE_BASE_URL"
                                               "（没填 key 就不带 Authorization）。_")
                    with gr.Row():
                        happly = gr.Button("✅ 应用到本会话（立即生效）", size="sm")
                        happly_out = gr.Markdown("_不点它也行：上面的测试与下面的生成都会立即生效。_")

                # 配置面板的控件顺序 = cfg_of_form 的参数顺序（少一层翻译，少一处出错）
                HCFG_IN = [hbase, hmodel, hkey, heng_base, heng_status, heng_key, heng_model]
                HFULL_IN = HCFG_IN + [hcfg_sid]

                def _apply_hpreset(name):
                    """选服务商 → 自动填 Base URL 与模型名（Key 永远要用户自己填）。"""
                    base, model = preset_values(name)
                    return gr.update(value=base), gr.update(value=model)

                hpreset.change(_apply_hpreset, [hpreset], [hbase, hmodel])

                def _do_brain_test(base, model, key, eng_base, eng_status, eng_key, eng_model, sid):
                    """测试大脑：POST <base>/chat/completions（分类报错，绝不把 UI 打挂）。"""
                    cfg = cfg_of_form(base, model, key, eng_base, eng_status, eng_key, eng_model)
                    sid = remember_cfg(sid, cfg)
                    return (format_conn_result(test_llm_connection(base, model, key)),
                            config_notice_md(cfg), sid)

                htest_brain.click(_do_brain_test, HFULL_IN, [hbrain_out, hcfg_notice, hcfg_sid])

                def _do_engine_test(base, model, key, eng_base, eng_status, eng_key, eng_model, sid):
                    """测试引擎：有 ENGINE_STATUS_URL 就 GET 它，否则 POST ENGINE_BASE_URL。"""
                    cfg = cfg_of_form(base, model, key, eng_base, eng_status, eng_key, eng_model)
                    sid = remember_cfg(sid, cfg)
                    return (format_conn_result(test_engine_connection(eng_base, eng_status, eng_key,
                                                                      eng_model)),
                            config_notice_md(cfg), sid)

                htest_eng.click(_do_engine_test, HFULL_IN, [heng_out, hcfg_notice, hcfg_sid])

                def _do_apply_cfg(base, model, key, eng_base, eng_status, eng_key, eng_model, sid):
                    cfg = cfg_of_form(base, model, key, eng_base, eng_status, eng_key, eng_model)
                    sid = remember_cfg(sid, cfg)
                    return (config_notice_md(cfg), sid,
                            "✅ 已应用到本会话（只在本进程内存里；换会话/刷新请重填）")

                happly.click(_do_apply_cfg, HFULL_IN, [hcfg_notice, hcfg_sid, happly_out])
                try:
                    from agent_client import AgentClient as _AC
                    _st = _AC().status()
                except Exception:  # noqa: BLE001
                    _st = {"mode": "demo-planner", "tools": [], "brain": False, "engine": False,
                           "model": "-", "system_prompt": "default"}
                # 三态要说清楚：能不能出片只看视频接口，别拿"大脑已接"糊弄用户
                if _st.get('engine'):
                    _mode_txt = "✅ 已接入视频生成接口 —— 可以真实出片"
                elif _st.get('brain'):
                    _mode_txt = ("🧠 外置大脑已接入（决策由真实模型完成）；**视频生成接口未接** → "
                                 "当前是演示预览，不做假动作")
                else:
                    _mode_txt = "🧪 规划演示模式（未配置外部接口：仍完整展示工具决策 + 请求体预览）"
                _warn = _st.get('warnings') or []
                _warn_md = ("\n\n> ⚠️ **配置自检**：\n" + "\n".join("> - " + w for w in _warn)) if _warn else ""
                _chan = _st.get('brain_channel') or 'rule'
                _brain_txt = {'agent-url': "✅ 平台 Agent（AGENT_URL）",
                              'llm': "✅ 自建大脑（LLM_*：%s）" % _st.get('model'),
                              'rule': "内置规则规划器（未配置大脑接口）"}.get(_chan, _chan)
                gr.Markdown("**当前模式**：%s　|　**外置大脑**：%s　|　**视频生成接口**：%s%s"
                            % (_mode_txt, _brain_txt,
                               "已配置" if _st.get('engine') else "未配置", _warn_md))
                _byok_txt = ('本空间**不提供**自带密钥：请在下面「🔑 我的密钥」里填你自己的（模型服务地址 + 模型名 + API Key）。'
                             if not _st.get('env_fallback', True) else
                             '本空间有一个默认大脑配置；**你也可以在下面「🔑 我的密钥」填自己的**，你自己的优先、且只在本会话内存里。')
                gr.Markdown("**密钥来源**：%s" % _byok_txt)
                gr.Markdown("**工具集**（agent 的手脚，全部走接口）：%s\n\n"
                            "_本空间不部署模型：大脑由 `LLM_*` 接口控制，出片由 `ENGINE_*` 接口控制；"
                            "接口清单见「能力与部署」页与仓库 studio/接口说明.md。_"
                            % "、".join("`%s`" % t for t in (_st.get('tools') or [])))
                with gr.Accordion("🔑 我的密钥（自带 API Key · 只在本会话·不上传不保存）", open=False):
                    gr.Markdown(
                        "🔒 **不想把 Key 交给本空间？** 用「零信任单页版」：Agent 跑在你的浏览器里，"
                        "直接调用你填的服务，Key 不经过任何服务器 → "
                        "<https://sakuraahly.github.io/videoGenerate-Model-zju/web/agent.html>\n\n"
                        "填你自己的模型服务凭据即可用本工具；**本空间不代付、不共享任何密钥**。"
                        " 密钥只随本次请求发到本进程内存里用于调用你指定的服务，"
                        "**不写盘、不进日志**；换会话/刷新页面后请重填。留空则使用空间默认（若有）。")
                    byok_preset = gr.Dropdown(label="① 选服务商（自动填地址与模型名）",
                                              choices=provider_choices(), value=provider_choices()[0])
                    with gr.Row():
                        byok_base = gr.Textbox(label="② 模型服务地址（OpenAI 兼容）", scale=3,
                                               placeholder="例：https://dashscope.aliyuncs.com/compatible-mode/v1")
                        byok_model = gr.Textbox(label="模型名", scale=1, placeholder="例：qwen-plus")
                    byok_key = gr.Textbox(label="③ 模型服务 API Key（你自己的）", type="password",
                                          placeholder="sk-...（只在本会话内存里）")

                    def _apply_preset(name):
                        """选服务商 → 自动填地址与模型名（Key 仍要用户自己填）。"""
                        base, model = PROVIDER_PRESETS.get(name, ('', ''))
                        return gr.update(value=base), gr.update(value=model)

                    byok_preset.change(_apply_preset, [byok_preset], [byok_base, byok_model])
                    with gr.Accordion("（可选）视频生成接口 —— 你自己的", open=False):
                        with gr.Row():
                            byok_eng = gr.Textbox(label="ENGINE_BASE_URL", scale=3)
                            byok_eng_key = gr.Textbox(label="ENGINE_API_KEY", type="password", scale=1)
                        byok_eng_status = gr.Textbox(label="ENGINE_STATUS_URL（异步查询，可留空）")
                    sess_id = gr.State("")     # 只存不透明会话 id；客户端与 key 只在服务端内存
                with gr.Row():
                    with gr.Column(scale=3):
                        chatbot = gr.Chatbot(label="对话", height=330)  # Gradio 6.x 默认 messages 格式
                        with gr.Row():
                            msg = gr.Textbox(label="说点什么", scale=4,
                                             placeholder="例：让参考图里的老人说一句“天冷了，快进屋坐坐吧。”"
                                                         "／做一段雨夜老屋门口有猫的 5 秒镜头")
                            send = gr.Button("发送", variant="primary", scale=1)
                        with gr.Row():
                            ex1 = gr.Button("示例·说话镜头", size="sm")
                            ex2 = gr.Button("示例·5 秒镜头", size="sm")
                            ex3 = gr.Button("示例·故事片", size="sm")
                            clr = gr.Button("清空对话", size="sm")
                    with gr.Column(scale=2):
                        ref_img = gr.Image(label="参考图（说话镜头建议上传：人物形象）", type="filepath",
                                           height=200)
                        jobs_state = gr.State([])
                        agent_video = gr.Video(label="本轮产物（若有）", interactive=False)
                        jobs_md = gr.Markdown("_（本会话还没有任务：在下面说一句需求即可）_")
                        refresh = gr.Button("🔄 刷新任务状态", size="sm")
                        trace_md = gr.Markdown("_（这里会显示 agent 的工具调用轨迹）_")

                TRACE_IDLE = "_（这里会显示 agent 的工具调用轨迹）_"
                JOBS_IDLE = "_（本会话还没有任务：在下面说一句需求即可）_"
                BYOK_IN = [byok_base, byok_model, byok_key, byok_eng, byok_eng_status, byok_eng_key]
                STEP_IN = [msg, chatbot, ref_img, jobs_state, sess_id] + BYOK_IN
                STEP_OUT = [chatbot, trace_md, agent_video, msg, jobs_state, jobs_md, sess_id]

                def _ov_of(base, model, key, eng, eng_status, eng_key):
                    """页面上的「我的密钥」→ 客户端 override（BYOK）。"""
                    return {'LLM_BASE_URL': base, 'LLM_MODEL': model, 'LLM_API_KEY': key,
                            'ENGINE_BASE_URL': eng, 'ENGINE_STATUS_URL': eng_status,
                            'ENGINE_API_KEY': eng_key}

                def _step(user_text, history, ref, jobs, sid, *byok):
                    """UI 包装：调用模块级 agent_step（可单测）。

                    BYOK + 会话隔离：State 只传 sid，客户端（含用户 key 与本会话台账）只活在服务端内存，
                    并有 TTL/上限自动回收——不把含密钥的对象交给前端状态层。"""
                    sid, cli = _session_client(sid, _ov_of(*byok))
                    r = agent_step(user_text, history, image_path=ref, client=cli)
                    jobs = list(jobs or [])
                    if r.get('job'):
                        jobs.append(r['job'])
                    return (r['history'], r.get('trace') or TRACE_IDLE, r.get('video') or None,
                            gr.update(value=""), jobs, jobs_table(jobs, cli), sid)

                def _refresh(jobs, sid, *byok):
                    try:
                        sid, cli = _session_client(sid, _ov_of(*byok))
                        return jobs_table(jobs, cli, refresh=True), jobs, sid
                    except Exception:  # noqa: BLE001
                        return jobs_table(jobs), jobs, sid

                send.click(_step, STEP_IN, STEP_OUT)
                msg.submit(_step, STEP_IN, STEP_OUT)
                ex1.click(lambda h, r, j, s, *b: _step('让参考图里的老人说一句“天冷了，快进屋坐坐吧，外面风大。”',
                                                       h, r, j, s, *b),
                          [chatbot, ref_img, jobs_state, sess_id] + BYOK_IN, STEP_OUT)
                ex2.click(lambda h, r, j, s, *b: _step('做一段雨夜老屋门口有猫望着门内暖光的 5 秒镜头', h, r, j, s, *b),
                          [chatbot, ref_img, jobs_state, sess_id] + BYOK_IN, STEP_OUT)
                ex3.click(lambda h, r, j, s, *b: _step('把“父子在病房道别”做成一段连贯的 3 段故事片', h, r, j, s, *b),
                          [chatbot, ref_img, jobs_state, sess_id] + BYOK_IN, STEP_OUT)
                refresh.click(_refresh, [jobs_state, sess_id] + BYOK_IN, [jobs_md, jobs_state, sess_id])
                clr.click(lambda: ([], TRACE_IDLE, None, JOBS_IDLE, []), None,
                          [chatbot, trace_md, agent_video, jobs_md, jobs_state])

                # ── 🎬 一句话出片（多 Agent Harness）──────────────────────────────
                gr.Markdown("### 🎬 一句话出片（多 Agent Harness）\n\n"
                            "一句话 → **5 个 Agent 分工**（编剧 → 分镜 → 导演 → 质检 → 剪辑）→ "
                            "剧本卡 · 分镜表（照做就能拍）· 预检闸门 · 质检打分 · 决策轨迹 · 交付清单。\n\n"
                            "_零算力：本空间不跑任何模型（不推理、不下载权重、不连任何本机 GPU）；"
                            "不填 key 走内置规则引擎，约 1 秒出结果。_")
                with gr.Row():
                    hbrief = gr.Textbox(label="一句话（越具体越好：人物 / 处境 / 情绪）", scale=4,
                                        placeholder="例：一个陪伴机器人，永远同意你说的一切")
                    hstyle = gr.Dropdown(choices=HARNESS_STYLES, value=HARNESS_STYLES[0],
                                         label="风格", scale=1)
                    hsec = gr.Number(value=45, label="目标时长（秒）", precision=0, scale=1)
                with gr.Row():
                    hcast = gr.Radio(choices=HARNESS_CAST_MODES, value=HARNESS_CAST_MODES[0],
                                     label="阵容（solo 独角戏 / duo 双人）", scale=2)
                    hres = gr.Dropdown(choices=HARNESS_RESOLUTIONS, value="480p", label="画幅", scale=1)
                    hanchor = gr.Checkbox(value=True, label="跨镜头锁定同一张脸（一致性锚点）", scale=2)
                    hlic = gr.Checkbox(value=False, label="我有权使用我上传的素材", scale=2)
                with gr.Row():
                    hrun = gr.Button("🎬 生成制片方案（零算力）", variant="primary", scale=3)
                    hrun_eng = gr.Button("🚀 出片（用我配置的引擎真出片）", variant="primary", scale=3)
                    hkit_dl = gr.DownloadButton("⬇️ 下载生产包（zip）", value=None, scale=2)
                    hlimit = gr.Number(value=0, label="出片段数（0=全部；先出 1 段试水更省时间）",
                                       precision=0, scale=1)
                    hclear = gr.Button("🧹 清空", scale=1)
                gr.Markdown("_「🎬 生成制片方案」只做规划与质检（零算力、不会碰你的引擎）；"
                            "「🚀 出片」才会把每一段提交到**你配置的引擎**，逐段回传成片 —— "
                            "算力与费用都在你这一侧。_")
                hkit_note = gr.Markdown(KIT_IDLE_MD)
                hboard = gr.HTML(board_html(None))

                def _run_board(brief, style, sec, cast, res, anchor, lic,
                               base, model, key, eng_base, eng_status, eng_key, eng_model, sid):
                    """UI 包装：表单 + 面板配置 → 看板 + 可下载的生产包（纯函数层可单测）。"""
                    cfg = cfg_of_form(base, model, key, eng_base, eng_status, eng_key, eng_model)
                    sid = remember_cfg(sid, cfg)
                    out = plan_board_full({'brief': brief, 'style': style, 'target_seconds': sec,
                                           'cast_mode': cast, 'resolution': res,
                                           'anchor': bool(anchor), 'assets_licensed': bool(lic)},
                                          cfg=cfg)
                    board = out.get('board') or {}
                    # 生产包落盘：kit.save_kit → agent_client 的本次进程产物目录
                    # （它已在 launch(allowed_paths) 里，写别处 gradio 会把下载拦掉）
                    zip_path = save_kit_blob(out.get('kit_blob') or {})
                    return (board_html(board, model=str(cfg.get('llm_model') or '')),
                            sid, config_notice_md(cfg), (zip_path or None), kit_note_md(board, zip_path))

                hrun.click(_run_board, [hbrief, hstyle, hsec, hcast, hres, hanchor, hlic] + HFULL_IN,
                           [hboard, hcfg_sid, hcfg_notice, hkit_dl, hkit_note])

                def _run_board_engine(brief, style, sec, cast, res, anchor, lic, limit,
                                      base, model, key, eng_base, eng_status, eng_key,
                                      eng_model, sid):
                    """流式出片：先出规划看板，再逐段提交到访客自己的引擎，每段刷新一次。

                    生产包在**规划阶段**就已生成（引擎跑完不重打包），所以第一轮刷新起就能下载；
                    这里通过 board_stream(hold=...) 把它的全量字节取回来落盘。
                    """
                    cfg = cfg_of_form(base, model, key, eng_base, eng_status, eng_key, eng_model)
                    sid = remember_cfg(sid, cfg)
                    mname = str(cfg.get('llm_model') or '')
                    form = {'brief': brief, 'style': style, 'target_seconds': sec,
                            'cast_mode': cast, 'resolution': res,
                            'anchor': bool(anchor), 'assets_licensed': bool(lic)}
                    hold, note, last, zip_path = {}, '', board_html(None), ''
                    for board, _sid, extra in board_stream(form, cfg=cfg, limit=limit,
                                                           model=mname, hold=hold):
                        if extra:
                            note = extra
                        if isinstance(board, dict):
                            last = board_html(board, model=mname)
                        if not zip_path and hold.get('kit_blob'):
                            zip_path = save_kit_blob(hold.get('kit_blob') or {})
                        yield last, sid, (note or config_notice_md(cfg)), (zip_path or None), \
                            kit_note_md(hold.get('board') or board, zip_path)

                hrun_eng.click(_run_board_engine,
                               [hbrief, hstyle, hsec, hcast, hres, hanchor, hlic, hlimit]
                               + HFULL_IN,
                               [hboard, hcfg_sid, hcfg_notice, hkit_dl, hkit_note])

                def _clear_board():
                    return ('', HARNESS_STYLES[0], 45, HARNESS_CAST_MODES[0], '480p', True, False,
                            board_html(None), None, KIT_IDLE_MD)

                hclear.click(_clear_board, None,
                             [hbrief, hstyle, hsec, hcast, hres, hanchor, hlic, hboard,
                              hkit_dl, hkit_note])

            with gr.Tab("🎛 创作台"):
                with gr.Row():
                    with gr.Column(scale=3):
                        kind = gr.Radio(choices=["文生视频", "图生视频", "说话镜头", "剧本故事片"],
                                        value="文生视频", label="任务类型")
                        prompt = gr.Textbox(label="创意 / 提示词 / 台词", lines=4,
                                            placeholder="例：雨夜老屋门口，一只猫望着门内的暖光；"
                                                        "或（说话镜头）天冷了，快进屋坐坐吧，外面风大。")
                        images = gr.Files(label="参考图（可选，多张；图生视频必填）",
                                          file_types=["image"])
                        with gr.Row():
                            resolution = gr.Dropdown(choices=["360p", "480p", "720p", "768p"],
                                                     value="480p", label="分辨率")
                            seconds = gr.Slider(2, 15, value=5, step=1, label="时长（秒）")
                        with gr.Row():
                            voice_src = gr.Radio(choices=["模型原生语音（推荐·自适应音色）", "指定本地 TTS 音色"],
                                                 value="模型原生语音（推荐·自适应音色）", label="语音来源")
                            subtitle = gr.Checkbox(value=False, label="额外烧录后期字幕（模型自带画面字幕，一般不用勾）")
                        with gr.Accordion("高级：本地 TTS 音色（仅当上面选择「指定本地 TTS 音色」时生效）", open=False):
                            voice = gr.Dropdown(choices=[v[0] for v in show["voices"][1:]],
                                                value=show["voices"][1][0], label="TTS 音色")
                        negative = gr.Textbox(label="负面词（可选）", lines=2,
                                              placeholder="no text, no watermark, no distortion …")
                        with gr.Row():
                            submit = gr.Button("🚀 生成", variant="primary", scale=3)
                            clear = gr.Button("清空", scale=1)
                    with gr.Column(scale=2):
                        status = gr.Markdown("_等待提交…_")
                        out_video = gr.Video(label="成片预览", interactive=False)
                        out_files = gr.File(label="下载", file_count="multiple")
                        hist = gr.Markdown("_（暂无任务记录）_", label="最近任务")
                submit.click(submit_job,
                             [kind, prompt, images, resolution, seconds, voice_src, voice, subtitle, negative],
                             [status, out_video, out_files, hist, prompt])
                clear.click(lambda: ("", None, "480p", 5, "模型原生语音（推荐·自适应音色）",
                                     show["voices"][1][0], True, ""),
                            None, [prompt, images, resolution, seconds, voice_src, voice, subtitle, negative])

            with gr.Tab("🎞 样片墙"):
                gr.Markdown("### 本机生成样片（点击播放）")
                rows = [show["samples"][i:i + 3] for i in range(0, len(show["samples"]), 3)]
                for row in rows:
                    with gr.Row():
                        for s in row:
                            with gr.Column():
                                gr.Image(value=_asset(s["cover"]), label=s["title"],
                                         show_label=True, interactive=False)
                                gr.Markdown(f"**{s['title']}** — {s['desc']}")
                                gr.Video(value=_asset(s["file"]), label=s["title"], interactive=False)

            with gr.Tab("🧭 能力与部署"):
                gr.Markdown("### 能力")
                for pt in show["hero_points"]:
                    gr.Markdown(f"- {pt}")
                gr.Markdown("### 制作流程")
                for t in show["flow_steps"]:
                    gr.Markdown(f"- {t}")
                gr.Markdown(f"""### 部署与「真实生成」
| 档位 | 能做什么 |
|---|---|
| **免费 CPU（2vCPU/16G，本页默认）** | 展示与参数化演示（本页表单）；不产生真实生成任务 |
| **GPU 硬件档（如 A10 24G）** | 空间内跑**轻量视频模型**（Wan2.1-1.3B / CogVideoX-2B 等）→ 页面上真实出片 |
| **引擎网关（REMOTE_API）** | 表单直连你的本地大模型引擎（H3 全链：生成→台词→字幕→口型→ASR） |

当前后端：**{backend.name}**。**形态①（已定案）：创空间只放 Agent，模型走外部 API**——
在空间「设置 → 变量 / 密钥」里填这几项即可真实出片（不填=规划演示）：
| 变量 | 说明 |
|---|---|
| `ENGINE_BASE_URL` / `ENGINE_API_KEY` | **视频生成模型接口**（预留口；旧名 `VIDEO_API_URL`/`VIDEO_API_KEY` 仍兼容） |
| `ENGINE_STATUS_URL` | 可选，异步作业查询地址（旧名 `VIDEO_API_STATUS_URL`） |
| `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL` | **外置大脑**：OpenAI 兼容决策模型（不填=内置规则规划器）。例：DeepSeek 填 `https://api.deepseek.com` + `deepseek-chat`；平台 Agent 也可直接用 `AGENT_URL` |
| `AGENT_URL` / `AGENT_TOKEN` | 可选：魔搭平台上「构建-发布」得到的 Agent 地址（**首选通道**，优先于 `LLM_*`） |
| `TOOLSET` | 可选，暴露给大脑的工具子集（默认 all） |
| `AGENT_SYSTEM_PROMPT`（或 `AGENT_SYSTEM_PROMPT_FILE`） | 可选，外置 system 提示：注入行业规则/铁律 |

**Agent 的两半**：①**工具集** `generate_video` / `generate_talk` / `make_story_film` / `list_jobs` / `query_job` /
`retry_job` / `resume_story` / `answer`（全部 HTTP，空间内无本机依赖）；②**外置大脑**（`AGENT_URL` 或 `LLM_*`，
决定用哪个工具、什么参数）。两半齐备即为完整 Agent，缺大脑时用内置规则规划器兜底演示。

**空间内等价实现的本地功能**：参考图上传与预览、请求体预览（演示模式）、任务面板与状态刷新、成片预览/下载、
画布内字幕与拼接由引擎接口返回的成片直接承载（空间侧不做重编码，避免占用免费 CPU）。

_{show['footer']}_""")
                gr.Markdown(boundary_diagram_md())
                gr.Markdown(mode_explain_md())
                with gr.Row():
                    _probe = gr.Button("🔌 测试外置大脑连接", size="sm")
                _probe_out = gr.Markdown("_点上面的按钮验证「外置大脑」是否真的可用（只发一条极小请求，不触发生成）。_")

                def _probe_click(sid, *byok):
                    """一键自测：用**你自己填的密钥**验证大脑通道（百炼/DeepSeek/平台 Agent/自建 LLM 通用）。"""
                    try:
                        _sid, cli = _session_client(sid, _ov_of(*byok))
                        return cli.selftest_text()
                    except Exception as e:  # noqa: BLE001
                        return "❌ 自测失败：%s" % str(e)[:200]

                _probe.click(_probe_click, [sess_id] + BYOK_IN, [_probe_out])

        gr.Markdown(f"\n---\n_空间版本 v3.5（2026-09-11 · 多 Agent Harness「一句话出片」制片看板 + 🎛 模型配置面板（BYOK·仅会话内存）；"
                    f"沿用 v3.4：Agent=工具集+外置大脑、服务商预设、零信任单页、密钥 TTL 回收、大脑调用限流）_")
    return demo


def launch_kwargs(app) -> dict:
    """按当前 gradio 版本能力组装 launch 参数（跨版本安全，缺能力就少传一个参数）。"""
    kw = {}
    try:
        kw['theme'] = __import__('gradio').themes.Soft()
    except Exception:  # noqa: BLE001
        pass
    try:  # Gradio 5.30+/6.x 才有 MCP；本空间用不到，关掉它（也避免 gr.State 的 MCP 警告）
        import inspect as _inspect
        if 'mcp_server' in _inspect.signature(app.launch).parameters:
            kw['mcp_server'] = False
    except Exception:  # noqa: BLE001
        pass
    return kw


def main() -> int:
    ap = argparse.ArgumentParser("H3 视频生成工坊（创空间 Agent v2.4）")
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", "7860")))
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--share", action="store_true")
    args = ap.parse_args()
    show = load_show()
    app = build_app(show)
    app.queue()
    # allowed_paths 只放「本次进程的随机产物目录」（不再是整个 outputs/）——
    # 公开空间里固定目录 + 可猜文件名会让别人拿到他人的成片（2026-09-10 加固）。
    try:
        from agent_client import AgentClient as _ACD
        _out_dir = _ACD.run_dir(clean_old=True)
    except Exception:  # noqa: BLE001
        _out_dir = HERE / "outputs"
    app.launch(server_name=args.host, server_port=args.port, share=args.share,
               show_error=True, quiet=True,
               allowed_paths=[str(ASSETS), str(_out_dir)],
               **launch_kwargs(app))
    return 0


if __name__ == "__main__":
    sys.exit(main())
