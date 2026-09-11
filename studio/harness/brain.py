"""studio.harness.brain - 外置大脑的三档接入（AGENT_URL > LLM_* > 内置规则引擎）。

定案（book-20 第 2.3 节）：创空间**不部署任何模型**；角色由谁来"演"取决于访客：
  档 1  AGENT_URL / AGENT_TOKEN   平台 Agent（若创空间提供了 Agent 能力）
  档 2  LLM_*                    访客自带的任意 OpenAI 兼容通用大模型（BYOK，页面配置面板填）
  档 3  内置规则引擎              零 key 也能演完整条状态机（保底，也是默认档）

对上层只有一个接口：ask() -> dict | None。返回 None = "这一档答不了"，
调用方（roles）立即改用规则引擎产出同样形状的产物 —— 所以**两种大脑共用一条状态机**。

安全与成本约束：不落盘、不打印密钥；超时短、不重试风暴（空间是免费 CPU 档）；
任何异常都吞成 None（大脑坏了不能把整条流水线带崩）。
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request

DEFAULT_TIMEOUT = 60
MAX_ANSWER_CHARS = 20000

_JSON_BLOCK_RE = re.compile(r'\{[\s\S]*\}')
_FENCE_RE = re.compile(r'^\s*```(?:json)?|\s*```\s*$', re.M)


class Brain:
    """大脑接口（规则引擎与真模型都实现它）。"""

    kind = 'rule'

    def available(self) -> bool:
        return False

    def label(self) -> str:
        return {'rule': '内置规则引擎（零 key）', 'llm': '访客自带通用大模型',
                'agent': '平台 Agent'}.get(self.kind, self.kind)

    def ask(self, role: str, system: str, user: str, *, schema: str = '') -> dict:
        """让这一档产出 JSON；答不了就返回 None（上层转规则引擎）。"""
        return None


class RuleBrain(Brain):
    """零 key 档：什么都不问，直接让 roles 走规则实现。"""

    kind = 'rule'


class LLMBrain(Brain):
    """OpenAI 兼容 /chat/completions 档（亦是平台 Agent 档的实现）。"""

    def __init__(self, base_url: str = '', api_key: str = '', model: str = '',
                 *, kind: str = 'llm', timeout: int = DEFAULT_TIMEOUT, extra: dict = None):
        self.base_url = (base_url or '').rstrip('/')
        self.api_key = api_key or ''
        self.model = model or ''
        self.kind = kind
        self.timeout = int(timeout or DEFAULT_TIMEOUT)
        self.extra = dict(extra or {})
        self.last_error = ''

    def available(self) -> bool:
        return bool(self.base_url and self.api_key and self.model)

    def ask(self, role: str, system: str, user: str, *, schema: str = '') -> dict:
        if not self.available():
            return None
        payload = {'model': self.model, 'temperature': 0.4,
                   'messages': [{'role': 'system', 'content': system},
                                {'role': 'user', 'content': user}]}
        payload.update(self.extra)
        try:
            req = urllib.request.Request(
                self.base_url + '/chat/completions',
                data=json.dumps(payload).encode('utf-8'),
                headers={'Content-Type': 'application/json',
                         'Authorization': 'Bearer ' + self.api_key})
            with urllib.request.urlopen(req, timeout=self.timeout) as r:  # noqa: S310
                body = json.loads(r.read().decode('utf-8', 'replace') or '{}')
        except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError) as e:
            self.last_error = '%s: %s' % (type(e).__name__, str(e)[:160])
            return None
        obj = _extract_json(_answer_text(body))
        if obj is None:
            self.last_error = '大脑没有返回可解析的 JSON'
        return obj


def _answer_text(body: dict) -> str:
    """兼容 OpenAI 与各家小改（choices[].message.content / text / reasoning_content）。"""
    try:
        ch = (body.get('choices') or [])[0]
    except (AttributeError, IndexError, TypeError):
        return ''
    msg = ch.get('message') if isinstance(ch, dict) else None
    if isinstance(msg, dict):
        for key in ('content', 'text'):
            if isinstance(msg.get(key), str) and msg[key].strip():
                return msg[key]
        if isinstance(msg.get('reasoning_content'), str):
            return msg['reasoning_content']
    if isinstance(ch, dict) and isinstance(ch.get('text'), str):
        return ch['text']
    return ''


def _extract_json(text: str):
    """从可能带 markdown 围栏/前后废话的回答里抠出第一个 JSON 对象。"""
    s = _FENCE_RE.sub('', str(text or '')).strip()
    if not s:
        return None
    for cand in _candidates(s):
        try:
            obj = json.loads(cand)
        except ValueError:
            continue
        if isinstance(obj, dict):
            return obj
    return None


def _candidates(s: str) -> list:
    out = [s]
    m = _JSON_BLOCK_RE.search(s)
    if m:
        out.append(m.group(0))
        # 截到最后一个右花括号，容忍回答尾部还有解释
        tail = s[m.start():]
        cut = tail.rfind('}')
        if cut > 0:
            out.append(tail[:cut + 1])
    return out


def make_brain(cfg: dict = None) -> Brain:
    """按环境/面板配置挑一档大脑（挑不到就返回规则引擎，绝不报错）。"""
    cfg = dict(cfg or {})
    agent_url = str(cfg.get('agent_url') or '').strip()
    agent_tok = str(cfg.get('agent_token') or '').strip()
    if agent_url and agent_tok:
        return LLMBrain(agent_url, agent_tok, str(cfg.get('agent_model') or 'default'),
                        kind='agent', timeout=int(cfg.get('timeout') or DEFAULT_TIMEOUT))
    llm_base = str(cfg.get('llm_base') or '').strip()
    llm_key = str(cfg.get('llm_key') or '').strip()
    if llm_base and llm_key:
        return LLMBrain(llm_base, llm_key, str(cfg.get('llm_model') or 'deepseek-ai/DeepSeek-V4-Pro'),
                        kind='llm', timeout=int(cfg.get('timeout') or DEFAULT_TIMEOUT),
                        extra=cfg.get('extra') or {})
    return RuleBrain()


def brain_from_env(env=None) -> Brain:
    """从环境变量挑大脑（创空间部署时用；页面 BYOK 面板优先于环境变量）。"""
    import os
    env = os.environ if env is None else env
    return make_brain({
        'agent_url': env.get('AGENT_URL', ''), 'agent_token': env.get('AGENT_TOKEN', ''),
        'llm_base': env.get('LLM_BASE_URL', ''), 'llm_key': env.get('LLM_API_KEY', ''),
        'llm_model': env.get('LLM_MODEL', ''),
    })
