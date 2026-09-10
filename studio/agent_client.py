"""studio agent_client - 创空间内可交付的 Agent:**工具集 + 外置大脑(接口控制)**。

设计原则(定案):
  1. 交付物就是一个 Agent:①工具集(本文具定义,全部走接口) ②外置大脑(LLM 由 LLM_* 接口控制,
     system 提示可外置注入)。二者齐备才算 Agent。
  2. 不依赖任何本机环境:不调用本机 ComfyUI / 脚本 / 本地文件;所有能力 = HTTP 接口。
  3. 通过预留的视频生成模型接口工作:ENGINE_BASE_URL(兼容旧名 VIDEO_API_URL),
     协议见 studio/接口说明.md(异步 job 轮询 / 同步直返两种)。
  4. 无 key 也能演:内置规则规划器产出同样的 {tool,args,say},前端照常展示决策轨迹。

环境变量(全部外置,代码不含密钥):
  LLM_BASE_URL / LLM_API_KEY / LLM_MODEL                       外置大脑(OpenAI 兼容 /chat/completions)
  AGENT_SYSTEM_PROMPT 或 AGENT_SYSTEM_PROMPT_FILE              自定义 system 提示
  ENGINE_BASE_URL / ENGINE_API_KEY (旧名 VIDEO_API_URL / VIDEO_API_KEY)
  ENGINE_STATUS_URL (旧名 VIDEO_API_STATUS_URL)                异步作业查询地址
  LLM_EXTRA_JSON                                               可选,附加请求字段(如关思考降延迟)
  TOOLSET=all|generate_video,generate_talk,...                 暴露给大脑的工具子集
"""
from __future__ import annotations

import base64
import json
import os
import time
from pathlib import Path

# ---------------- 工具集(Agent 的手脚;全部接口化,无本机依赖) ----------------
TOOLS = [
    {"name": "generate_video",
     "description": "根据一段创意生成视频(文生视频;给了参考图则按参考图生成)",
     "params": {"prompt": "创意/分镜描述(英文更稳)",
                "resolution": "360p|480p|540p|720p|768p",
                "seconds": "时长秒数 2-15",
                "image_b64": "参考图(可选,data URL 或纯 base64)"}},
    {"name": "generate_talk",
     "description": "说话镜头:让参考图里的人物亲口说出一句台词(口型/音色/时长由模型处理)",
     "params": {"text": "台词原文(照抄,不要改写)",
                "image_b64": "人物参考图(建议必填)",
                "voice": "native(默认,模型原生音色)|或指定音色名",
                "resolution": "480p|720p"}},
    {"name": "make_story_film",
     "description": "把剧本/多段剧情做成连贯短片(可分段提交,逐段返回结果)",
     "params": {"script": "剧情或剧本",
                "segments": "段数(默认 3)",
                "resolution": "480p|720p", "seconds": "每段秒数"}},
    {"name": "answer",
     "description": "不生成,只解释/建议/答疑(架构、参数、怎么用)",
     "params": {"text": "回答内容"}},
]

# 大脑可能自创键名（实测 Qwen3.5-27B 会用 dialogue/character/style）——统一归一化到工具 schema
ARG_ALIASES = {
    'text': ('text', 'dialogue', 'line', 'speech', 'content', 'script_line', '台词', '对话', '文案'),
    'prompt': ('prompt', 'description', 'scene', 'desc', 'content_prompt', '创意', '描述'),
    'seconds': ('seconds', 'duration', 'length', 'duration_seconds', '时长'),
    'resolution': ('resolution', 'size', 'quality', '分辨率'),
    'voice': ('voice', 'speaker', 'timbre', '音色'),
    'segments': ('segments', 'parts', 'shots', '段数'),
    'image_b64': ('image_b64', 'image', 'ref_image', 'reference_image', 'img', '参考图'),
}


def normalize_args(tool: str, args: dict) -> dict:
    """把大脑给的参数归一化到该工具的 schema：认别名、丢自创键（否则会生成空台词）。"""
    spec = next((t for t in TOOLS if t['name'] == tool), None)
    if spec is None:
        return {}
    out = {}
    for key in spec['params']:
        for alias in ARG_ALIASES.get(key, (key,)):
            v = (args or {}).get(alias)
            if isinstance(v, (str, int, float)) and str(v).strip():
                out[key] = v
                break
    return out


DEFAULT_SYSTEM = """你是 H3 视频生成工坊的创作 Agent,部署在魔搭创空间(免费 CPU,本地不跑模型)。
你的职责:理解用户创意 -> 从工具集里选一个工具 -> 给出可直接执行的参数 -> 交由外部生成接口执行。
规则:
1) 用户要"说话镜头/台词/口型/配音" -> generate_talk;台词原文照抄,不要改写、不要加旁白。
2) 用户要"故事/短剧/多段/连贯" -> make_story_film。
3) 其他创意 -> generate_video;只问不生成 -> answer。
4) 默认 resolution=480p、seconds=5;说话镜头时长由接口按语音自动匹配。
5) args 只能使用这些键名,不要自创(不要出现 dialogue/character/style 之类):
   generate_video: prompt, resolution, seconds;  generate_talk: text, voice;
   make_story_film: script, segments;           answer: text。
6) 只输出一个 JSON:{"tool":"<工具名>","args":{...},"say":"给用户的一句中文说明"},不要输出多余文本。
"""


# 平台不接受空值变量(必填校验),所以允许先占位;占位符一律视为"未配置"——
# 好处:变量可以先建好放在那儿,填什么都不会被误当成真实地址去调用。
PLACEHOLDERS = {'', '-', '--', 'none', 'null', 'n/a', 'na', 'todo', 'tbd', 'xxx', '???',
                'changeme', 'placeholder', 'unset', '未配置', '未设置', '待填', '待配置'}


def _env(*names, default: str = '') -> str:
    for n in names:
        v = (os.environ.get(n) or '').strip()
        if v and v.lower() not in PLACEHOLDERS:
            return v
    return default


class AgentClient:
    """Agent = 外置大脑(LLM 接口) + 工具集(HTTP 接口执行)。"""

    @staticmethod
    def _url(v: str) -> str:
        """只认 http(s) 开头的地址;其余(占位符/脏值)返回空串 = 未配置。"""
        v = (v or '').strip().rstrip('/')
        return v if v.startswith(('http://', 'https://')) else ''

    def __init__(self):
        self.llm_base = self._url(_env('LLM_BASE_URL'))
        self.llm_key = _env('LLM_API_KEY')
        self.llm_model = _env('LLM_MODEL', default='qwen-plus')
        # 只接受合法 http(s) 地址:占位符/脏值(如平台编码问题产生的 '???')一律当作未配置
        self.engine_url = self._url(_env('ENGINE_BASE_URL', 'VIDEO_API_URL'))
        self.engine_key = _env('ENGINE_API_KEY', 'VIDEO_API_KEY')
        self.engine_status = self._url(_env('ENGINE_STATUS_URL', 'VIDEO_API_STATUS_URL'))
        self.toolset = [t.strip() for t in _env('TOOLSET', default='all').split(',') if t.strip()]
        # 平台标准通道（2026-09-10 按《ModelScope-Agent 学习指南》对齐）：
        #   文档的做法是「零代码创建 Agent → 发布 → 只取 AGENT_URL → 在创空间里替换该环境变量 → 重启空间展示」。
        #   所以 AGENT_URL 是**首选大脑**：平台上的 Agent（自带 prompt/tools/知识）负责决策；
        #   我们只做「工具集 + 前端」，与 LLM_* 通道并存，优先级 AGENT_URL > LLM_* > 规则规划器。
        self.agent_url = self._url(_env('AGENT_URL'))
        self.agent_token = _env('AGENT_TOKEN')
        try:
            self.agent_timeout = int(float(_env('AGENT_TIMEOUT', default='90') or 90))
        except Exception:  # noqa: BLE001
            self.agent_timeout = 90
        self.llm_extra = {}
        raw_extra = _env('LLM_EXTRA_JSON')      # 例:{"chat_template_kwargs":{"enable_thinking":false}}
        if raw_extra:
            try:
                parsed = json.loads(raw_extra)
                if isinstance(parsed, dict):
                    self.llm_extra = parsed
            except Exception:  # noqa: BLE001
                pass
        self.system_prompt = self._load_system_prompt()
        self.builder_cfg = self._load_builder_config()
        if self.builder_cfg:                     # 平台约定的代码级配置入口（config/builder_config.json）
            if str(self.builder_cfg.get('prompt') or '').strip():
                self.system_prompt = str(self.builder_cfg['prompt'])
            tools = self.builder_cfg.get('tools')
            if isinstance(tools, list) and tools and self.toolset == ['all']:
                names = [t if isinstance(t, str) else str((t or {}).get('name') or '') for t in tools]
                names = [n.strip() for n in names if n and n.strip()]
                if names:
                    self.toolset = names

    @staticmethod
    def _load_builder_config() -> dict:
        """读 config/builder_config.json（平台 Agent 代码级配置约定）。

        文档《ModelScope-Agent 学习指南》QA5：代码级魔改 = 在本地 config/builder_config.json
        改字段并调试 → commit & push → 重启空间展示。这里只取我们关心的三样：prompt / tools / 变量。
        """
        for cand in (Path(__file__).resolve().parent / 'builder_config.json',
                     Path(__file__).resolve().parent.parent / 'config' / 'builder_config.json'):
            try:
                if cand.is_file():
                    data = json.loads(cand.read_text(encoding='utf-8-sig'))
                    return data if isinstance(data, dict) else {}
            except Exception:  # noqa: BLE001
                continue
        return {}

    # ---------- 外置大脑:system 提示可注入 ----------
    @staticmethod
    def _load_system_prompt() -> str:
        inline = _env('AGENT_SYSTEM_PROMPT')
        if inline:
            return inline
        path = _env('AGENT_SYSTEM_PROMPT_FILE')
        cands = [Path(path)] if path else []
        cands.append(Path(__file__).resolve().parent / 'agent_prompt.md')
        for cand in cands:
            try:
                if cand.is_file():
                    return cand.read_text(encoding='utf-8')
            except Exception:  # noqa: BLE001
                pass
        return DEFAULT_SYSTEM

    @property
    def brain(self) -> str:
        """当前决策通道：agent-url（平台 Agent，首选）/ llm（自建大脑）/ rule（内置规则规划器）。"""
        if self.agent_url:
            return 'agent-url'
        if self.llm_key:
            return 'llm'
        return 'rule'

    @property
    def mode(self) -> str:
        if self.agent_url or self.llm_key or self.engine_url:
            return 'agent-api'
        return 'demo-planner'

    def tools(self) -> list:
        if not self.toolset or 'all' in self.toolset:
            return TOOLS
        return [t for t in TOOLS if t['name'] in self.toolset]

    def status(self) -> dict:
        """给 UI 用的自检信息(不泄露密钥,只表明是否已配置)。"""
        return {'mode': self.mode, 'brain': bool(self.llm_key or self.agent_url),
                'brain_channel': self.brain,
                'agent_url': bool(self.agent_url),
                'builder_config': bool(self.builder_cfg),
                'model': self.llm_model,
                'engine': bool(self.engine_url), 'status_api': bool(self.engine_status),
                'tools': [t['name'] for t in self.tools()],
                'system_prompt': 'custom' if self.system_prompt != DEFAULT_SYSTEM else 'default'}

    # ---------- 平台 Agent 通道（AGENT_URL，容错适配） ----------
    def _ask_agent_url(self, messages: list) -> str:
        """把对话发给平台上的 Agent（AGENT_URL），返回它的文本回复。

        平台 Agent 的返回形态不固定（OpenAI 兼容 JSON / 通用 JSON / SSE 流），这里逐个尝试并统一抽文本；
        全部失败就抛异常，由上层降级——绝不假装成功。
        """
        import urllib.request
        headers = {'Content-Type': 'application/json',
                   'Accept': 'application/json, text/event-stream'}
        if self.agent_token:
            headers['Authorization'] = 'Bearer ' + self.agent_token
        payloads = [
            {'model': _env('AGENT_MODEL', default='modelscope-agent'),
             'messages': messages, 'stream': False},
            {'messages': messages},
            {'input': messages[-1].get('content', ''), 'messages': messages},
        ]
        last = None
        for body in payloads:
            try:
                req = urllib.request.Request(self.agent_url, data=json.dumps(body).encode(),
                                             headers=headers)
                with urllib.request.urlopen(req, timeout=self.agent_timeout) as r:
                    raw = r.read().decode('utf-8', 'replace')
                    ctype = r.headers.get('Content-Type') or ''
                txt = self._extract_agent_text(raw, ctype)
                if txt:
                    return txt
                last = ValueError('平台 Agent 返回体里没解析出文本')
            except Exception as e:  # noqa: BLE001
                last = e
        raise last if last else RuntimeError('AGENT_URL 调用失败')

    @staticmethod
    def _extract_agent_text(raw: str, ctype: str = '') -> str:
        """从平台 Agent 返回里抽文本：OpenAI 兼容 JSON / 通用 JSON / SSE 三种形态都认。"""
        raw = (raw or '').strip()
        if not raw:
            return ''
        if 'event-stream' in (ctype or '').lower() or raw.startswith('data:'):
            chunks = []
            for line in raw.splitlines():
                line = line.strip()
                if not line.startswith('data:'):
                    continue
                piece = line[5:].strip()
                if not piece or piece == '[DONE]':
                    continue
                chunks.append(AgentClient._pick_text(piece) or piece)
            return ''.join(chunks).strip()
        return AgentClient._pick_text(raw)

    @staticmethod
    def _pick_text(raw: str) -> str:
        """按常见字段路径抽文本（不同平台/版本字段名不一样，全试一遍）。"""
        try:
            d = json.loads(raw)
        except Exception:  # noqa: BLE001
            return raw if not raw.lstrip().startswith(('{', '[')) else ''
        paths = (('choices', 0, 'message', 'content'), ('choices', 0, 'text'),
                 ('data', 'text'), ('data', 'response'), ('data', 'content'),
                 ('data', 0, 'text'), ('response',), ('answer',), ('content',),
                 ('text',), ('output_text',), ('message',), ('result',))
        for path in paths:
            cur = d
            ok = True
            for k in path:
                if isinstance(cur, list) and isinstance(k, int) and len(cur) > k:
                    cur = cur[k]
                elif isinstance(cur, dict) and k in cur:
                    cur = cur[k]
                else:
                    ok = False
                    break
            if ok and isinstance(cur, str) and cur.strip():
                return cur.strip()
        return ''

    def _plan_agent_url(self, user_msg: str, history: list) -> dict:
        """让平台 Agent 决策：把 system 提示 + 工具清单 + 最近对话发过去，收 {tool,args,say}。

        容错：平台 Agent 若只回自然语言（没按我们的 JSON 约定），就把它的文本当 answer 交付，
        不做假动作、也不硬套工具。
        """
        msgs = [{"role": "system", "content": self.system_prompt
                 + "\n可用工具(JSON 列表):" + json.dumps(self.tools(), ensure_ascii=False)}]
        for h in (history or [])[-6:]:
            c = h.get('content')
            if isinstance(c, list):
                c = ' '.join(x.get('text', '') for x in c if isinstance(x, dict))
            msgs.append({"role": h.get('role', 'user'), "content": str(c or '')[:800]})
        msgs.append({"role": "user", "content": user_msg})
        try:
            txt = self._ask_agent_url(msgs)
        except Exception as e:  # noqa: BLE001
            return {'tool': 'answer',
                    'args': {'text': '(平台 Agent 暂不可用：%s；本轮按内置规则执行。)' % str(e)[:120]},
                    'say': '平台 Agent 没接上，我先用内置规则给你方案。'}
        try:
            plan = json.loads(txt)
            if isinstance(plan, dict) and plan.get('tool'):
                plan['args'] = normalize_args(plan['tool'], plan.get('args') or {})
                return plan
        except Exception:  # noqa: BLE001
            pass
        return {'tool': 'answer', 'args': {'text': txt}, 'say': ''}

    # ---------- 决策(大脑) ----------
    def plan(self, user_msg: str, history: list) -> dict:
        if self.brain == 'agent-url':
            return self._plan_agent_url(user_msg, history)
        if not self.llm_key:
            return self._rule_plan(user_msg)
        msgs = [{"role": "system", "content": self.system_prompt
                 + "\n可用工具(JSON 列表):" + json.dumps(self.tools(), ensure_ascii=False)}]
        for h in (history or [])[-6:]:
            c = h.get('content')
            if isinstance(c, list):  # gradio Chatbot messages 形态
                c = ' '.join(x.get('text', '') for x in c if isinstance(x, dict))
            msgs.append({"role": h.get('role', 'user'), "content": str(c or '')[:800]})
        msgs.append({"role": "user", "content": user_msg})
        payload = {"model": self.llm_model, "messages": msgs, "temperature": 0.3,
                   "response_format": {"type": "json_object"}}
        payload.update(self.llm_extra)          # 外置扩展:关思考/调 top_p/换模板,不改代码
        last_err = ''
        for attempt in range(3):        # 实测大脑偶发空响应/抖动:重试 3 次(间隔 1s)再降级
            try:
                d = self._post_json(self.llm_base + '/chat/completions', payload, self.llm_key, timeout=90)
                txt = ((d.get('choices') or [{}])[0].get('message') or {}).get('content') or ''
                plan = json.loads(txt)
                if isinstance(plan, dict) and plan.get('tool'):
                    plan['args'] = normalize_args(plan['tool'], plan.get('args') or {})
                    return plan
                last_err = '模型未返回 tool 字段(可能被限流)'
            except Exception as e:  # noqa: BLE001
                last_err = str(e)[:120]
            time.sleep(1.0)
        return {'tool': 'answer',
                'args': {'text': '(外置大脑暂不可用:%s;本轮按内置规则执行。)' % last_err},
                'say': '大脑接口抖动,我先用内置规则给你方案。'}

    @staticmethod
    def _rule_plan(user_msg: str) -> dict:
        """无外置大脑时的规则规划器:输出结构与 LLM 完全一致,保证演示不断档。"""
        t = user_msg or ''
        quoted = ''
        for q in ('"', '\u201c', '\u300e', '\u300c'):
            if q in t:
                parts = t.split(q)
                if len(parts) >= 2:
                    quoted = parts[1].strip().strip('\u201d\u300d\u300f"')
                break
        talk_kw = ('\u53f0\u8bcd', '\u8bf4\u8bdd', '\u8bf4\u4e00\u53e5', '\u53e3\u578b', '\u914d\u97f3', '\u72ec\u767d',
                   'say:', 'says:', 'speak', 'dialogue', 'voiceover', 'voice-over', 'lipsync', 'lip sync')
        story_kw = ('\u6545\u4e8b', '\u77ed\u5267', '\u5267\u672c', '\u591a\u6bb5', '\u8fde\u8d2f',
                    'story', 'short film', 'screenplay', 'script', 'multi-shot')
        answer_kw = ('\u600e\u4e48', '\u5982\u4f55', '\u4e3a\u4ec0\u4e48', '\u5efa\u8bae', '\u8bf4\u660e', '\u67b6\u6784',
                     'how does', 'how do', 'why ', 'explain', 'architecture', 'what is')
        import re
        if not quoted:  # 英文/无引号写法："say: <台词>" / "让老人说：..."
            m = re.search(r'(?:say|says|speak|tell(?:\s+\w+)?|台词|说)\s*[:：]\s*(.+)', t, re.I)
            if m:
                quoted = m.group(1).strip().strip('"\u201d\u300d\u300f')
        # 有明确"说"的动作 + 取到了台词 → 直接判为说话镜头（比关键词更可靠）
        said = bool(quoted) and bool(re.search(r'say|says|speak|tell|台词|说|念', t, re.I))
        if any(k in t for k in talk_kw) or said:
            return {'tool': 'generate_talk',
                    'args': {'text': quoted or '\u4f60\u597d,\u5f88\u9ad8\u5174\u89c1\u5230\u4f60\u3002',
                             'voice': 'native'},
                    'say': '明白,做一个说话镜头:让人物亲口说出台词,时长由接口按语音自动匹配。'}
        if any(k in t for k in story_kw):
            return {'tool': 'make_story_film', 'args': {'script': t[:200], 'segments': 3},
                    'say': '这是多段故事需求:我按段提交,逐段出片并给你汇总。'}
        if any(k in t for k in answer_kw):
            return {'tool': 'answer',
                    'args': {'text': '本空间只部署 Agent(工具集 + 外置大脑),不跑模型:'
                                     '大脑(LLM 接口)决定用哪个工具与参数,工具再调外部视频生成接口出片。'},
                    'say': '这是架构说明。'}
        return {'tool': 'generate_video',
                'args': {'prompt': t[:400] or 'a cinematic shot', 'resolution': '480p', 'seconds': 5},
                'say': '收到创意,我按文生视频出片(480p/5s 起步)。'}

    # ---------- 工具集执行(HTTP,无本机依赖) ----------
    def _post_json(self, url: str, payload: dict, key: str = '', timeout: int = 120) -> dict:
        import urllib.request
        headers = {'Content-Type': 'application/json'}
        if key:
            headers['Authorization'] = 'Bearer ' + key
        req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode('utf-8', 'replace') or '{}')

    def _get_json(self, url: str, key: str = '', timeout: int = 60) -> dict:
        import urllib.request
        headers = {'Authorization': 'Bearer ' + key} if key else {}
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode('utf-8', 'replace') or '{}')

    def build_payload(self, tool: str, args: dict) -> dict:
        """把工具参数翻译成视频生成接口的请求体(协议见 studio/接口说明.md)。"""
        kind = {'generate_video': 't2v', 'generate_talk': 'talk',
                'make_story_film': 'story'}.get(tool, 't2v')
        payload = {'kind': kind,
                   'resolution': args.get('resolution', '480p'),
                   'seconds': int(float(args.get('seconds') or 5))}
        if kind == 't2v':
            payload['prompt'] = args.get('prompt') or ''
            if args.get('image_b64'):
                payload['image_b64'] = args['image_b64']
                payload['kind'] = 'i2v'
        elif kind == 'talk':
            payload['text'] = args.get('text') or ''
            payload['voice'] = args.get('voice') or 'native'
            if args.get('image_b64'):
                payload['image_b64'] = args['image_b64']
        elif kind == 'story':
            payload['script'] = args.get('script') or ''
            payload['segments'] = int(float(args.get('segments') or 3))
        return payload

    @staticmethod
    def _brief(args: dict) -> dict:
        out = {}
        for k, v in (args or {}).items():
            out[k] = (str(v)[:48] + '...') if isinstance(v, str) and len(v) > 48 else v
        return out

    def run_tool(self, plan: dict) -> dict:
        tool = plan.get('tool')
        args = normalize_args(tool, plan.get('args') or {})
        allowed = {t['name'] for t in self.tools()}
        trace = {'tool': tool, 'args': self._brief(args)}
        if plan.get('_repaired'):
            trace['repaired'] = plan['_repaired']
        if tool not in allowed:
            trace['result'] = 'tool-not-in-toolset'
            return {'ok': False, 'kind': 'error', 'trace': trace,
                    'text': '工具 %s 未在本空间开放(受 TOOLSET 限制)。' % tool}
        if tool == 'answer':
            trace['result'] = 'answer'
            return {'ok': True, 'kind': 'answer', 'text': args.get('text', ''), 'trace': trace}
        if not self.engine_url:
            trace['result'] = 'demo(未配置 ENGINE_BASE_URL)'
            payload = self.build_payload(tool, args)
            trace['request'] = self._brief(payload)
            return {'ok': True, 'kind': 'demo', 'tool': tool, 'args': args,
                    'payload': payload, 'trace': trace,
                    'text': '演示模式:未接入视频生成接口,以下是把交给接口的请求体。'}
        try:
            payload = self.build_payload(tool, args)
            trace['request'] = self._brief(payload) if 'image_b64' not in payload else \
                {**self._brief(payload), 'image_b64': '<base64 已省略>'}
            d = self._post_json(self.engine_url, payload, self.engine_key, timeout=180)
            trace['response'] = self._brief(d)
            job_id = d.get('job_id') or d.get('task_id') or d.get('id')
            video = d.get('video_url') or d.get('url')
            if job_id and not video and self.engine_status:
                t0 = time.time()
                trace['polls'] = []
                while time.time() - t0 < 600:
                    time.sleep(10)
                    sd = self._get_json(self.engine_status.rstrip('/') + '/' + str(job_id), self.engine_key)
                    trace['polls'].append(sd.get('status'))
                    if sd.get('video_url') or sd.get('url'):
                        video = sd.get('video_url') or sd.get('url')
                        break
                    if sd.get('status') in ('failed', 'error'):
                        raise RuntimeError(sd.get('error') or '外部服务返回失败')
            return {'ok': True, 'kind': 'remote', 'task': job_id, 'video': video,
                    'payload': payload, 'trace': trace}
        except Exception as e:  # noqa: BLE001
            trace['result'] = 'ERR ' + str(e)[:160]
            return {'ok': False, 'kind': 'error', 'trace': trace,
                    'text': '外部生成接口调用失败:%s' % str(e)[:200]}

    def answer(self, user_msg: str, history: list, image_path: str = '', image_b64: str = '') -> dict:
        plan = self.plan(user_msg, history)
        allowed = {t['name'] for t in self.tools()}
        if plan.get('tool') not in allowed:      # 大脑选了未开放的工具 -> 按规则规划器修复
            plan = self._rule_plan(user_msg)
            plan['_repaired'] = 'tool-not-allowed'
        need = {'generate_talk': ('text',)}      # 关键参数缺失(模型爱自创键名) -> 补齐
        miss = [k for k in need.get(plan.get('tool'), ()) if not (plan.get('args') or {}).get(k)]
        if miss:
            fixed = self._rule_plan(user_msg)
            if fixed.get('tool') == plan.get('tool'):
                merged = dict(plan.get('args') or {})
                for k in miss:
                    if (fixed.get('args') or {}).get(k):
                        merged[k] = fixed['args'][k]
                plan['args'] = merged
                plan['_repaired'] = 'args:' + ','.join(miss)
        img = image_b64 or (self.file_to_b64(image_path) if image_path else '')
        if img and plan.get('tool') in ('generate_video', 'generate_talk', 'make_story_film'):
            args = dict(plan.get('args') or {})
            args.setdefault('image_b64', img)
            plan['args'] = args
        out = self.run_tool(plan)
        if out.get('video'):
            out['video_local'] = self.download(out['video'])
        out['say'] = plan.get('say') or ''
        out['mode'] = self.mode
        return out

    def poll_job(self, job_id: str) -> dict:
        """任务面板用:查询外部接口的作业状态(未配置状态接口时返回 unknown,不报错)。"""
        if not (job_id and self.engine_status):
            return {'status': 'unknown', 'video_url': None}
        try:
            d = self._get_json(self.engine_status.rstrip('/') + '/' + str(job_id), self.engine_key)
            return {'status': d.get('status') or 'running',
                    'video_url': d.get('video_url') or d.get('url'),
                    'error': d.get('error')}
        except Exception as e:  # noqa: BLE001
            return {'status': 'unknown', 'video_url': None, 'error': str(e)[:120]}

    # ---------- 空间内等价实现:把外部成片取回本地,供页面预览/下载 ----------
    OUTPUT_DIR = Path(__file__).resolve().parent / 'outputs'

    @classmethod
    def download(cls, url: str, dest_dir=None, max_mb: int = 300, timeout: int = 180) -> str:
        """把接口返回的成片下载到空间本地(页面才能内嵌预览/下载)。

        说明:免费 CPU 档不做转码(耗时且无必要);只做「取回 + 落盘 + 顺手清理旧文件」。
        失败一律返回空串,由界面退化为「打开链接」,绝不让下载问题挡住 Agent 主流程。
        """
        if not url or not str(url).startswith(('http://', 'https://')):
            return ''
        import urllib.request
        out_dir = Path(dest_dir) if dest_dir else cls.OUTPUT_DIR
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
            name = (str(url).split('?')[0].rstrip('/').split('/')[-1] or 'result.mp4')[-80:]
            if not name.lower().endswith(('.mp4', '.webm', '.mov', '.mkv')):
                name += '.mp4'
            dest = out_dir / ('%d_%s' % (int(time.time()), name))
            with urllib.request.urlopen(url, timeout=timeout) as r, open(dest, 'wb') as f:
                total = 0
                while True:
                    chunk = r.read(1 << 20)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > max_mb * (1 << 20):
                        raise RuntimeError('超过 %dMB 上限' % max_mb)
                    f.write(chunk)
            cls.prune_outputs(out_dir)
            return str(dest)
        except Exception:  # noqa: BLE001
            return ''

    @staticmethod
    def prune_outputs(out_dir=None, keep: int = 12):
        """只留最近 keep 个成片(免费档磁盘有限)。"""
        d = Path(out_dir) if out_dir else AgentClient.OUTPUT_DIR
        try:
            files = sorted(d.glob('*'), key=lambda p: p.stat().st_mtime, reverse=True)
            for p in files[keep:]:
                p.unlink()
        except Exception:  # noqa: BLE001
            pass

    # ---------- 便捷:上传文件 -> data URL ----------
    @staticmethod
    def file_to_b64(path: str) -> str:
        try:
            p = Path(path)
            raw = p.read_bytes()
            ext = p.suffix.lower().lstrip('.') or 'png'
            mime = {'jpg': 'jpeg', 'jpeg': 'jpeg', 'png': 'png', 'webp': 'webp'}.get(ext, 'png')
            return 'data:image/%s;base64,%s' % (mime, base64.b64encode(raw).decode())
        except Exception:  # noqa: BLE001
            return ''


