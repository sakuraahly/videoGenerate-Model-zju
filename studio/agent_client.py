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
    {"name": "list_jobs",
     "description": "列出本会话提交过的任务及状态(默认最近 8 条;配了状态接口会顺手刷新)",
     "params": {"limit": "条数(默认 8,最多 20)"}},
    {"name": "query_job",
     "description": "查询某个任务的详细状态/进度/成片链接(不给 job_id 默认查最近一次)",
     "params": {"job_id": "任务 id(可省略=最近一次)"}},
    {"name": "retry_job",
     "description": "用原参数重新提交某个失败/不满意的任务(可覆盖 seed/seconds/resolution)",
     "params": {"job_id": "任务 id(可省略=最近一次)",
                "seed": "可选:换种子重试(整数)",
                "seconds": "可选:覆盖时长",
                "resolution": "可选:覆盖分辨率"}},
    {"name": "resume_story",
     "description": "故事片断点续跑(仅当生成接口声明支持 resume_from 时可用;否则明确告知只能整段重提)",
     "params": {"job_id": "故事片任务 id(可省略=最近一次)"}},
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
    'job_id': ('job_id', 'jobid', 'task_id', 'taskid', 'id', '任务', '任务id'),
    'limit': ('limit', 'count', 'n', '条数'),
    'seed': ('seed', 'random_seed', '种子'),
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
   make_story_film: script, segments;           answer: text;
   list_jobs: limit;  query_job: job_id;  retry_job: job_id, seed, seconds, resolution;
   resume_story: job_id。
6) 只输出一个 JSON:{"tool":"<工具名>","args":{...},"say":"给用户的一句中文说明"},不要输出多余文本。
7) 用户问"跑到哪了/好了没/刚才那个任务/第几个任务" -> query_job(不给 job_id 就是最近一次);
   问"都有哪些任务/队列里有什么" -> list_jobs。
8) 用户说"失败了重来/换个种子再试/不满意重做" -> retry_job。
9) 用户说"接着上次没跑完的继续/断点续跑" -> resume_story;若接口不支持,工具会如实说明只能整段重提,
   **不要**自己承诺续跑成功。
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

    def __init__(self, overrides: dict = None):
        """overrides：**用户自带的配置**（BYOK，来自页面表单，按会话隔离）。

        取值优先级：用户 override >（可选）空间环境变量 > 内置默认。
        空间可以用 ALLOW_ENV_FALLBACK=0 彻底不提供任何自带密钥——那时别人必须填自己的，
        也就是「只发布工具、不发布算力与密钥」的形态。
        """
        self._ov = {str(k).upper(): str(v).strip() for k, v in (overrides or {}).items()
                    if str(v or '').strip()}
        self.env_fallback = str(_env('ALLOW_ENV_FALLBACK', default='1')).strip().lower() not in (
            '0', 'false', 'no', 'off')
        self.apply_overrides(overrides)
        self.toolset = [t.strip() for t in self._cfg('TOOLSET', default='all').split(',') if t.strip()]
        self.job_log = []                # 本会话作业台账（供 查/重试/续跑 工具使用）
        self._brain_calls = []           # 大脑调用时间戳（限流用；仅当用的是运营方 key 时计数）
        import threading as _threading
        self._lock = _threading.Lock()   # 台账并发保护（Gradio 可能并发处理请求）
        self.engine_resume = bool(self._cfg('ENGINE_RESUME'))
        try:
            self.agent_timeout = int(float(self._cfg('AGENT_TIMEOUT', default='90') or 90))
        except Exception:  # noqa: BLE001
            self.agent_timeout = 90
        self.llm_extra = {}
        raw_extra = self._cfg('LLM_EXTRA_JSON')   # 例：{\"enable_thinking\": false}
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

    def apply_overrides(self, overrides: dict = None) -> None:
        """设置/更新用户自带凭据（BYOK）。**只改凭据，不动作业台账**。

        安全：这些值只在该会话的客户端实例内存里，不写盘、不进日志、不进请求体；
        密钥只出现在 HTTP 请求头里，发往用户自己指定的服务。"""
        if overrides is not None:
            self._ov = {str(k).upper(): str(v).strip() for k, v in (overrides or {}).items()
                        if str(v or '').strip()}
        self.llm_base = self._url(self._cfg('LLM_BASE_URL'))
        self.llm_key = self._cfg('LLM_API_KEY')
        self.llm_model = self._cfg('LLM_MODEL', default='qwen-plus')
        # 只接受合法 http(s) 地址：占位符/脏值一律当作未配置
        self.engine_url = self._url(self._cfg('ENGINE_BASE_URL', 'VIDEO_API_URL'))
        self.engine_key = self._cfg('ENGINE_API_KEY', 'VIDEO_API_KEY')
        self.engine_status = self._url(self._cfg('ENGINE_STATUS_URL', 'VIDEO_API_STATUS_URL'))
        # 平台标准通道：AGENT_URL（社区指南里的「发布 Agent 只取 AGENT_URL」）优先于 LLM_*
        self.agent_url = self._url(self._cfg('AGENT_URL'))
        self.agent_token = self._cfg('AGENT_TOKEN')
        # 只有**真正可用**的用户凭据才算 BYOK：占位符（unset/无/…）等同没填，别误报"用的是你的密钥"
        def _ov_ok(_name):
            _v = self._ov.get(_name)
            return bool(_v and _v.lower() not in PLACEHOLDERS)
        self.byok = _ov_ok('LLM_API_KEY') or _ov_ok('AGENT_TOKEN') or _ov_ok('ENGINE_API_KEY')

    def _cfg(self, name: str, *aliases, default: str = '') -> str:
        """读配置：用户 override > 空间环境变量（可被 ALLOW_ENV_FALLBACK=0 关闭）> 默认。"""
        for key in (name,) + tuple(aliases):
            v = self._ov.get(key)
            if v and v.lower() not in PLACEHOLDERS:
                return v
        if not getattr(self, 'env_fallback', True):
            return default
        return _env(name, *aliases, default=default)

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
                    # 大小上限：避免一个超大提示文件把上下文/内存打爆（免费档尤其敏感）
                    if cand.stat().st_size > 64 * 1024:
                        continue
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

    def warnings(self) -> list:
        """自检告警（对齐《ModelScope-Agent 学习指南》QA6 的教训：勾了工具却没配 key 会报错）。

        原则：**在页面上先说清缺什么**，而不是等用户点了才抛一句看不懂的错。
        """
        w = []
        if getattr(self, 'byok', False):
            w.append('本轮使用**你自己填写的密钥**（只在本会话内存里，不写盘、不进日志）。')
        elif not getattr(self, 'env_fallback', True):
            w.append('本空间不提供自带密钥：请在「🔑 我的密钥」里填你自己的 LLM_API_KEY 与模型服务地址。')
        if not self.engine_url:
            w.append('未配置 ENGINE_BASE_URL（视频生成接口）→ 只能出方案预览，点生成不会真出片。')
        elif not self.engine_status:
            w.append('未配置 ENGINE_STATUS_URL → 任务状态查询/查作业工具只能看本会话记录，')
        if self.engine_url and not self.engine_key:
            w.append('配置了 ENGINE_BASE_URL 但没有 ENGINE_API_KEY（若网关需要鉴权会 401）。')
        if self.agent_url and not self.agent_token:
            w.append('配置了 AGENT_URL 但没有 AGENT_TOKEN（平台 Agent 需要令牌时会被拒）。')
        if self.engine_resume and not self.engine_status:
            w.append('ENGLINE_RESUME 已开启但缺 ENGINE_STATUS_URL → 续跑起点只能从第 1 段算。'.replace('ENGLINE', 'ENGINE'))
        return w

    def status(self) -> dict:
        """给 UI 用的自检信息(不泄露密钥,只表明是否已配置)。"""
        return {'mode': self.mode, 'brain': bool(self.llm_key or self.agent_url),
                'warnings': self.warnings(),
                'byok': bool(getattr(self, 'byok', False)),
                'env_fallback': bool(getattr(self, 'env_fallback', True)),
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
    @staticmethod
    def _parse_plan_text(txt: str) -> dict:
        """容错解析大脑返回的 JSON（兼容 ```json 包裹 / 前后带解释文字）。

        DeepSeek 等服务的推理模型（deepseek-reasoner）不一定严格遵守 JSON 模式，
        实测会把计划包在解释文字里；这里统一抽第一个完整 JSON 对象。
        """
        t = (txt or '').strip()
        if not t:
            return {}
        if t.startswith('```'):
            t = t.strip('`')
            t = t.split('\n', 1)[1] if '\n' in t else t
            if t.rstrip().endswith('```'):
                t = t.rstrip()[:-3]
        try:
            d = json.loads(t)
            return d if isinstance(d, dict) else {}
        except Exception:
            pass
        start = t.find('{')
        while start >= 0:
            depth, in_str, esc = 0, False, False
            for i in range(start, len(t)):
                ch = t[i]
                if in_str:
                    if esc:
                        esc = False
                    elif ch == chr(92):
                        esc = True
                    elif ch == '"':
                        in_str = False
                    continue
                if ch == '"':
                    in_str = True
                elif ch == '{':
                    depth += 1
                elif ch == '}':
                    depth -= 1
                    if depth == 0:
                        try:
                            d = json.loads(t[start:i + 1])
                            if isinstance(d, dict):
                                return d
                        except Exception:
                            pass
                        break
            start = t.find('{', start + 1)
        return {}

    def brain_quota_ok(self) -> bool:
        """大脑调用限流：**只有当使用的是空间默认（运营方）凭据时才计数**。

        背景：空间变量里若填了运营方的 key，公开空间等于把额度借给所有访客；
        单个会话每小时调用上限（`BRAIN_CALLS_PER_HOUR`，默认 60，0=不限）能挡住滥用；
        访客自带 key（BYOK）时不限流——花的是他自己的额度。
        """
        if getattr(self, 'byok', False):
            return True
        try:
            limit = int(float(_env('BRAIN_CALLS_PER_HOUR', default='60') or 60))
        except Exception:  # noqa: BLE001
            limit = 60
        if limit <= 0:
            return True
        now = time.time()
        self._brain_calls = [t for t in self._brain_calls if now - t < 3600]
        if len(self._brain_calls) >= limit:
            return False
        self._brain_calls.append(now)
        return True

    def plan(self, user_msg: str, history: list) -> dict:
        if not self.brain_quota_ok():
            return {'tool': 'answer',
                    'args': {'text': ('本会话的**免费体验额度已用完**（每小时调用次数上限）。\n\n'
                                      '两个办法继续用：① 在「🔑 我的密钥」里填你自己的 API Key'
                                      '（自带 key 不受限）；② 用零信任单页版（Agent 跑在你浏览器里）：\n'
                                      'https://sakuraahly.github.io/videoGenerate-Model-zju/web/agent.html')},
                    'say': '本会话的免费体验额度用完了。'}
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
        # 推理型模型（DeepSeek deepseek-reasoner）不支持 temperature —— 自动去掉，别让它直接报错
        if 'reasoner' in str(self.llm_model or '').lower():
            payload.pop('temperature', None)
        payload.update(self.llm_extra)          # 外置扩展:关思考/调 top_p/换模板,不改代码
        last_err = ''
        for attempt in range(3):        # 实测大脑偶发空响应/抖动:重试 3 次(间隔 1s)再降级
            try:
                d = self._post_json(self.llm_base + '/chat/completions', payload, self.llm_key, timeout=90)
                txt = ((d.get('choices') or [{}])[0].get('message') or {}).get('content') or ''
                plan = self._parse_plan_text(txt)      # 容错：```json 包裹 / 散文包裹都能解
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

    def _run_job_tool(self, tool, args, trace):
        '''查作业/重试/续跑：不经过生成工具，直接读台账 + 打状态接口。'''
        if tool == 'list_jobs':
            r = self.list_jobs(int(float(args.get('limit') or 8)))
            jobs = r.get('jobs') or []
            trace['result'] = 'list_jobs:%d' % len(jobs)
            if not jobs:
                return {'ok': True, 'kind': 'answer', 'trace': trace,
                        'text': '本会话还没有提交过任务。' + (r.get('note') or '')}
            lines = ['本会话最近 %d 个任务：' % len(jobs)]
            for j in jobs:
                tag = {'completed': '✅', 'failed': '❌', 'running': '⏳', 'queued': '🕐'}.get(str(j.get('status')), '•')
                lines.append('- %s %s ｜ %s ｜ %s ｜ %s' % (tag, j.get('ts'), str(j.get('job_id'))[:8],
                                                            j.get('tool'), j.get('status')))
            if r.get('note'):
                lines.append('（%s）' % r['note'])
            return {'ok': True, 'kind': 'answer', 'trace': trace, 'text': '\n'.join(lines)}
        if tool == 'query_job':
            r = self.query_job(str(args.get('job_id') or ''))
            trace['result'] = 'query_job:%s' % ('ok' if r.get('ok') else 'miss')
            return {'ok': r.get('ok', False), 'kind': 'answer', 'trace': trace, 'text': r.get('text', '')}
        if tool == 'retry_job':
            r = self.retry_job(str(args.get('job_id') or ''), args.get('seed'),
                               args.get('seconds'), args.get('resolution'))
            trace['result'] = 'retry_job:%s' % ('ok' if r.get('ok') else 'no')
            if not r.get('ok'):
                return {'ok': False, 'kind': 'answer', 'trace': trace, 'text': r.get('text', '')}
            return {'ok': True, 'kind': 'remote', 'task': r.get('task'), 'video': r.get('video'),
                    'payload': r.get('payload'), 'trace': trace, 'text': r.get('text', '')}
        r = self.resume_story(str(args.get('job_id') or ''))
        trace['result'] = 'resume_story:%s' % ('ok' if r.get('ok') else 'no')
        if not r.get('ok'):
            return {'ok': False, 'kind': 'answer', 'trace': trace, 'text': r.get('text', '')}
        return {'ok': True, 'kind': 'remote', 'task': r.get('task'), 'payload': r.get('payload'),
                'trace': trace, 'text': r.get('text', '')}

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
        if tool in ('list_jobs', 'query_job', 'retry_job', 'resume_story'):
            return self._run_job_tool(tool, args, trace)
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
            pending = False
            jid = self._safe_job_id(job_id)
            if jid and not video and self.engine_status:
                # 等待时长可配（免费 CPU 档不宜长占工作线程；默认 120s，0=不等待直接返回任务号）
                try:
                    wait_s = int(float(_env('ENGINE_SYNC_WAIT', default='120') or 120))
                except Exception:  # noqa: BLE001
                    wait_s = 120
                t0 = time.time()
                trace['polls'] = []
                while wait_s > 0 and time.time() - t0 < wait_s:
                    time.sleep(10)
                    sd = self._get_json(self.engine_status.rstrip('/') + '/' + jid, self.engine_key)
                    trace['polls'].append(sd.get('status'))
                    if sd.get('video_url') or sd.get('url'):
                        video = sd.get('video_url') or sd.get('url')
                        break
                    if sd.get('status') in ('failed', 'error'):
                        raise RuntimeError(sd.get('error') or '外部服务返回失败')
                pending = not video
            self.record_job(tool, args, payload, job_id, video=video or '')
            out = {'ok': True, 'kind': 'remote', 'task': job_id, 'video': video,
                   'payload': payload, 'trace': trace}
            if pending:
                out['pending'] = True
                out['text'] = ('任务已提交（%s），还在生成中。可以问我「那个任务好了吗」，'
                               '或在右侧任务面板点刷新看结果。' % (jid or job_id))
            return out
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

    # ---------- 会话内作业台账 + 查/重试/续跑（2026-09-10 新增） ----------
    MAX_JOBS = 20

    def record_job(self, tool, args, payload, job_id, status='running', video='', error=''):
        '''登记一次真实提交（重试/续跑要靠它拿到原始参数）。

        内存保护：payload 里的 image_b64 可能是几 MB，存 20 条会吃满免费档内存 ——
        超过上限就丢弃并打标记（重试时如实告知「参考图不会重放」，不假装参数齐全）。
        '''
        p = dict(payload or {})
        img = p.get('image_b64')
        try:
            cap = int(float(_env('MAX_JOB_IMAGE_MB', default='4') or 4)) * (1 << 20)
        except Exception:  # noqa: BLE001
            cap = 4 * (1 << 20)
        dropped = False
        if isinstance(img, str) and len(img) > cap:
            p.pop('image_b64', None)
            dropped = True
        rec = {'job_id': str(job_id or ''), 'tool': tool, 'args': self._brief(args or {}),
               'payload': p, 'status': status, 'video': video or '',
               'error': error or '', 'image_dropped': dropped,
               'ts': time.strftime('%H:%M:%S'),
               'time': time.strftime('%Y-%m-%d %H:%M:%S')}
        with self._lock:
            self.job_log = [j for j in self.job_log if j.get('job_id') != rec['job_id']]
            self.job_log.append(rec)
            del self.job_log[:-self.MAX_JOBS]
        return rec

    def _find_job(self, job_id=''):
        '''按 id 找（认前缀，方便只报前 8 位）；不给就返回最近一次。'''
        if not self.job_log:
            return {}
        jid = str(job_id or '').strip()
        if not jid:
            return self.job_log[-1]
        for r in reversed(self.job_log):
            if r.get('job_id') == jid or (jid and str(r.get('job_id') or '').startswith(jid)):
                return r
        return {}

    def list_jobs(self, limit=8, refresh=True, refresh_limit=5):
        '''列本会话任务；配了状态接口就顺手刷新（查不到保持原状态，不谎报）。

        refresh_limit：最多刷新几个「在跑」的任务——每次刷新都是一次 HTTP 请求，
        任务多了会把页面拖死（免费档尤其明显）。
        '''
        rows = self.job_log[-max(1, min(int(limit or 8), self.MAX_JOBS)):]
        out = []
        refreshed = 0
        for r in rows:
            st = dict(r)
            if (refresh and self.engine_status and refreshed < max(0, int(refresh_limit or 0))
                    and r.get('status') in ('running', 'queued', 'unknown', '')):
                refreshed += 1
                p = self.poll_job(r.get('job_id'))
                if p.get('status') and p.get('status') != 'unknown':
                    st['status'] = p['status']
                    st['video'] = p.get('video_url') or st.get('video') or ''
                    r['status'] = st['status']
            out.append(st)
        return {'ok': True, 'jobs': out, 'status_api': bool(self.engine_status),
                'note': '' if self.engine_status else '未配置 ENGINE_STATUS_URL：状态取自本会话记录，可能不是最新。'}

    def query_job(self, job_id=''):
        rec = self._find_job(job_id)
        if not rec:
            return {'ok': False, 'text': '没找到这个任务：本会话没有 %s 的记录（未配置状态接口时只能查本会话提交过的任务）。'
                                         % (job_id or '任何任务')}
        st = {'status': rec.get('status') or 'unknown', 'video_url': rec.get('video') or '',
              'error': rec.get('error') or ''}
        stale = False
        if self.engine_status:
            p = self.poll_job(rec['job_id'])
            if p.get('status') and p.get('status') != 'unknown':
                st['status'] = p['status']
                st['video_url'] = p.get('video_url') or st['video_url']
                st['error'] = p.get('error') or st['error']
                rec['status'], rec['video'] = st['status'], st['video_url']
            else:
                stale = True       # 状态接口没答上来：沿用旧状态，但必须标注，不能让人以为是刚查到的
        segs = st.get('segments') or []
        line = '任务 %s（%s）：状态 %s' % (rec['job_id'], rec.get('tool'), st['status'])
        if segs:
            line += '，分段 %d/%d 完成' % (sum(1 for x in segs if x.get('status') == 'completed'), len(segs))
        if st.get('video_url'):
            line += '；成片：' + st['video_url']
        if st.get('error'):
            line += '；错误：' + st['error']
        if not self.engine_status:
            line += '（未配置 ENGINE_STATUS_URL，状态取自本会话记录）'
        elif stale:
            line += '（状态接口本次未返回结果，显示的是本会话记录）'
        return {'ok': True, 'job': rec, 'status': st, 'text': line}

    def retry_job(self, job_id='', seed=None, seconds=None, resolution=None):
        '''用原 payload 重提（可覆盖 seed/seconds/resolution）；没有原 payload 就如实说不能重试。'''
        rec = self._find_job(job_id)
        if not rec:
            return {'ok': False, 'text': '没法重试：本会话没有 %s 的记录。' % (job_id or '任何任务')}
        if not rec.get('payload'):
            return {'ok': False, 'text': '没法重试：任务 %s 没留下原始请求体。' % rec['job_id']}
        if not self.engine_url:
            return {'ok': False, 'text': '没法重试：还没配置 ENGINE_BASE_URL（视频生成接口）。'}
        payload = dict(rec['payload'])
        over = {}
        if seed not in (None, ''):
            try:
                payload['seed'] = int(float(seed)); over['seed'] = payload['seed']
            except Exception:
                pass
        if seconds not in (None, ''):
            try:
                payload['seconds'] = float(seconds); over['seconds'] = payload['seconds']
            except Exception:
                pass
        if resolution:
            payload['resolution'] = str(resolution); over['resolution'] = str(resolution)
        try:
            d = self._post_json(self.engine_url, payload, self.engine_key, timeout=180)
        except Exception as e:
            return {'ok': False, 'text': '重试失败（接口调用出错）：%s' % str(e)[:160]}
        new_id = d.get('job_id') or d.get('task_id') or d.get('id') or ''
        video = d.get('video_url') or d.get('url') or ''
        self.record_job(rec.get('tool') or '-', {}, payload, new_id, video=video)
        tail = ('，覆盖：' + json.dumps(over, ensure_ascii=False)) if over else ''
        if rec.get('image_dropped'):
            tail += '（注意：原任务的参考图太大未保存，重试**不带参考图**；需要带图请在对话里重新上传）'
        return {'ok': True, 'task': new_id, 'video': video, 'payload': payload,
                'text': '已用原参数重新提交（新任务 %s）%s。' % (new_id, tail)}

    def resume_story(self, job_id=''):
        '''断点续跑：只有引擎声明支持才做，否则如实说明（绝不假称已续跑）。'''
        rec = self._find_job(job_id)
        if not rec:
            return {'ok': False, 'text': '没法续跑：本会话没有 %s 的记录。' % (job_id or '任何任务')}
        if not self.engine_resume:
            return {'ok': False, 'text': '当前生成接口未提供断点续跑能力（契约里没有 resume_from），所以不能从中间接着跑；'
                                         '只能整段重提——需要的话我用 retry_job 重发一次。'}
        if not (rec.get('payload') and self.engine_url):
            return {'ok': False, 'text': '没法续跑：任务 %s 没有原始请求体，或未配置 ENGINE_BASE_URL。' % rec['job_id']}
        st = self.poll_job(rec['job_id'])
        segs = st.get('segments') or []
        done = sum(1 for x in segs if x.get('status') == 'completed')
        payload = dict(rec['payload'])
        payload['resume_from'] = int(done)
        try:
            d = self._post_json(self.engine_url, payload, self.engine_key, timeout=180)
        except Exception as e:
            return {'ok': False, 'text': '续跑请求失败：%s' % str(e)[:160]}
        new_id = d.get('job_id') or d.get('task_id') or d.get('id') or ''
        self.record_job(rec.get('tool') or '-', {}, payload, new_id)
        return {'ok': True, 'task': new_id, 'payload': payload,
                'text': '已从第 %d 段续跑（新任务 %s）。' % (int(done) + 1, new_id)}

    def selftest(self, timeout: int = 30) -> dict:
        """连接自测：验证「外置大脑」是否真的能用（给用户/答辩一键验证，也方便试新服务商）。

        只发一条极小的对话请求（"回复两个字：可用"）；**不发送任何真实生成请求**。
        生成接口只报告"是否已配置"——连通性要等真正提交任务才能验证，这里不假装测过。
        """
        out = {'channel': self.brain, 'model': self.llm_model, 'ok': False,
               'reply': '', 'error': '', 'ms': None,
               'engine_configured': bool(self.engine_url),
               'engine_note': ('已配置（连通性在提交任务时验证；本自测不发送生成请求）' if self.engine_url
                               else '未配置 ENGINE_BASE_URL：只能出方案预览')}
        if self.brain == 'rule':
            out['error'] = '未配置外置大脑（AGENT_URL 或 LLM_*），当前用内置规则规划器'
            return out
        t0 = time.time()
        try:
            if self.brain == 'agent-url':
                txt = self._ask_agent_url([{'role': 'user', 'content': '回复两个字：可用'}])
            else:
                payload = {'model': self.llm_model, 'max_tokens': 24,
                           'messages': [{'role': 'user', 'content': '回复两个字：可用'}]}
                if 'reasoner' not in str(self.llm_model or '').lower():
                    payload['temperature'] = 0
                d = self._post_json(self.llm_base + '/chat/completions', payload, self.llm_key,
                                    timeout=timeout)
                txt = ((d.get('choices') or [{}])[0].get('message') or {}).get('content') or ''
            out['ms'] = int((time.time() - t0) * 1000)
            out['reply'] = (txt or '').strip()[:80]
            out['ok'] = bool(out['reply'])
            if not out['ok']:
                out['error'] = '接口通了但返回空内容（可能被限流/额度用尽）'
        except Exception as e:
            out['ms'] = int((time.time() - t0) * 1000)
            out['error'] = str(e)[:200]
        return out

    def selftest_text(self) -> str:
        """自测结果转成给人看的一段话（页面按钮 / 命令行共用）。"""
        r = self.selftest()
        name = {'agent-url': '平台 Agent（AGENT_URL）', 'llm': '自建大脑（LLM_*）',
                'rule': '内置规则规划器'}.get(r['channel'], r['channel'])
        if r['ok']:
            return '✅ 大脑可用：%s ｜ 模型 %s ｜ %d ms ｜ 回话：%s\n\n（%s）' % (
                name, r['model'], r['ms'] or 0, r['reply'], r['engine_note'])
        return '❌ 大脑不可用：%s\n原因：%s\n\n（%s）' % (name, r['error'] or '未知', r['engine_note'])

    def poll_job(self, job_id: str) -> dict:
        """任务面板用:查询外部接口的作业状态(未配置状态接口时返回 unknown,不报错)。"""
        jid = self._safe_job_id(job_id)          # 只允许白名单字符，防路径穿越
        if not (jid and self.engine_status):
            return {'status': 'unknown', 'video_url': None}
        try:
            d = self._get_json(self.engine_status.rstrip('/') + '/' + jid, self.engine_key)
            return {'status': d.get('status') or 'running',
                    'video_url': d.get('video_url') or d.get('url'),
                    'error': d.get('error')}
        except Exception as e:  # noqa: BLE001
            return {'status': 'unknown', 'video_url': None, 'error': str(e)[:120]}

    # ---------- 安全工具（2026-09-10 加固） ----------
    _JOB_ID_RE = None          # 懒编译

    @staticmethod
    def _safe_job_id(job_id) -> str:
        """任务号白名单校验：只允许 [A-Za-z0-9._:-]，长度 ≤64。

        任务号来自外部接口，直接拼进查询 URL 会有路径穿越/注入风险（如 ../../admin）。
        """
        import re as _re
        s = str(job_id or '').strip()
        if not s or len(s) > 64:
            return ''
        return s if _re.fullmatch(r'[A-Za-z0-9._:-]+', s) else ''

    # 元数据/链路本地地址：从外部接口拿到的 URL 若指向这里，属于 SSRF 探云元数据，一律拒绝
    _METADATA_HOSTS = ('169.254.169.254', '100.100.100.200', '100.100.100.201',
                       'metadata.google.internal', 'metadata.aliyun.com')
    _METADATA_PREFIXES = ('169.254.', 'fd00:ec2::')

    @classmethod
    def _is_metadata_url(cls, url: str) -> bool:
        """判断 URL 是否指向云元数据/链路本地地址（含域名解析后的结果）。"""
        try:
            import ipaddress
            from urllib.parse import urlparse
            import socket
            host = (urlparse(str(url)).hostname or '').strip().lower()
            if not host:
                return True                      # 解析不出主机名：按不安全处理
            if host in cls._METADATA_HOSTS or host.startswith(cls._METADATA_PREFIXES):
                return True
            try:
                ips = {ai[4][0] for ai in socket.getaddrinfo(host, None)}
            except Exception:
                return False                     # 解析不了就先放行，交给下载失败分支
            for ip in ips:
                try:
                    a = ipaddress.ip_address(ip)
                except ValueError:
                    continue
                if a.is_link_local or str(a) in cls._METADATA_HOSTS:
                    return True
            return False
        except Exception:
            return False

    @staticmethod
    def _safe_filename(name: str, default: str = 'result.mp4') -> str:
        """把 URL 派生出的文件名洗成安全文件名（去掉分隔符/上跳/控制字符）。"""
        import re as _re
        s = str(name or '').strip()
        s = s.split('?')[0].split('#')[0]
        s = _re.sub(r'[^A-Za-z0-9._-]', '_', s).strip('._') or default
        if '.' in s:                      # 只保留最后一个小数点作扩展名，其余点变下划线（杜绝 ..）
            stem, _, ext = s.rpartition('.')
            stem = (stem.replace('.', '_').strip('._') or 'result')[:60]
            ext = _re.sub(r'[^A-Za-z0-9]', '', ext)[:8] or 'mp4'
            s = '%s.%s' % (stem, ext)
        return s[-80:]

    # ---------- 空间内等价实现:把外部成片取回本地,供页面预览/下载 ----------
    # 进程级随机子目录（2026-09-10 加固）：Gradio 的 allowed_paths 会把这个目录整片暴露给
    # /gradio_api/file= 服务；若固定目录 + 可猜文件名（时间戳+原名），公开空间里别人猜链接就能
    # 拿到他人的成片。改成每次启动一个不可猜的子目录，并在启动时清掉上一轮的目录。
    OUTPUT_DIR = Path(__file__).resolve().parent / 'outputs'
    _RUN_DIR = None

    @classmethod
    def run_dir(cls, clean_old: bool = False) -> Path:
        """返回本次进程的产物目录（首次调用时创建随机子目录）。"""
        import secrets
        if cls._RUN_DIR is None:
            base = cls.OUTPUT_DIR
            base.mkdir(parents=True, exist_ok=True)
            if clean_old:
                for old in base.glob('run_*'):
                    try:
                        for f in old.glob('*'):
                            f.unlink()
                        old.rmdir()
                    except Exception:  # noqa: BLE001
                        pass
            d = base / ('run_' + secrets.token_hex(6))
            d.mkdir(parents=True, exist_ok=True)
            cls._RUN_DIR = d
        return cls._RUN_DIR

    @classmethod
    def download(cls, url: str, dest_dir=None, max_mb: int = 300, timeout: int = 180) -> str:
        """把接口返回的成片下载到空间本地(页面才能内嵌预览/下载)。

        说明:免费 CPU 档不做转码(耗时且无必要);只做「取回 + 落盘 + 顺手清理旧文件」。
        失败一律返回空串,由界面退化为「打开链接」,绝不让下载问题挡住 Agent 主流程。
        """
        if not url or not str(url).startswith(('http://', 'https://')):
            return ''
        if cls._is_metadata_url(url):       # SSRF 防护：拒绝云元数据/链路本地地址
            return ''
        import urllib.request, secrets
        out_dir = Path(dest_dir) if dest_dir else cls.run_dir()
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
            name = cls._safe_filename(str(url).split('?')[0].rstrip('/').split('/')[-1])
            if not name.lower().endswith(('.mp4', '.webm', '.mov', '.mkv')):
                name += '.mp4'
            # 文件名再带一段随机串：即使目录被列出/链接被转发，也无法猜出下一个文件名
            dest = out_dir / ('%d_%s_%s' % (int(time.time()), secrets.token_hex(4), name))
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
    def prune_outputs(out_dir=None, keep: int = 8):
        """只留最近 keep 个成片(免费档磁盘有限；也缩小可被枚举的窗口)。"""
        d = Path(out_dir) if out_dir else AgentClient.run_dir()
        try:
            files = sorted(d.glob('*'), key=lambda p: p.stat().st_mtime, reverse=True)
            for p in files[keep:]:
                p.unlink()
        except Exception:  # noqa: BLE001
            pass

    # ---------- 便捷:上传文件 -> data URL ----------
    @staticmethod
    def file_to_b64(path: str) -> str:
        """上传图 -> data URL。带大小上限，避免用户传超大文件把免费档内存打爆。"""
        try:
            p = Path(path)
            try:
                limit = int(float(_env('MAX_UPLOAD_MB', default='12') or 12)) * (1 << 20)
            except Exception:  # noqa: BLE001
                limit = 12 * (1 << 20)
            if p.stat().st_size > limit:
                return ''
            raw = p.read_bytes()
            ext = p.suffix.lower().lstrip('.') or 'png'
            mime = {'jpg': 'jpeg', 'jpeg': 'jpeg', 'png': 'png', 'webp': 'webp'}.get(ext, 'png')
            return 'data:image/%s;base64,%s' % (mime, base64.b64encode(raw).decode())
        except Exception:  # noqa: BLE001
            return ''


def _cli(argv=None) -> int:
    """命令行入口：python3 agent_client.py --selftest —— 一键验证外置大脑/接口配置。"""
    import argparse
    ap = argparse.ArgumentParser('创空间 Agent 客户端')
    ap.add_argument('--selftest', action='store_true', help='测试外置大脑连接（不触发真实生成）')
    ap.add_argument('--status', action='store_true', help='打印配置状态与自检告警')
    a = ap.parse_args(argv)
    c = AgentClient()
    if a.status or not a.selftest:
        st = c.status()
        print('模式: %s ｜ 大脑通道: %s ｜ 模型: %s' % (st['mode'], st['brain_channel'], st['model']))
        print('工具: %s' % ', '.join(st['tools']))
        for w in st.get('warnings') or []:
            print('[!] ' + w)
        if not a.selftest:
            return 0
        print('')
    print(c.selftest_text())
    return 0


if __name__ == '__main__':
    raise SystemExit(_cli())


