"""studio agent_client — 创空间内的「对话式 agent」前端（不部署模型，只调外部 API）。

老师的架构要求（2026-09-10）：创空间部署的是 **agent**，不必把模型一起部署——
留 **API 接口调用外部 API** 即可。本模块即这层接口：

  1) LLM（OpenAI 兼容 /chat/completions）：负责 **决策** —— 读用户自然语言 → 选工具 → 组参数；
  2) 视频生成 API（可配置）：真正出片的**外部算力**；
  3) TTS API（可选）：台词语音；
  未配置任何 key → **demo 模式**：用规则化的"规划器"演示 agent 的决策轨迹 + 匹配样片（比赛演示可用）。

环境变量：
  LLM_BASE_URL / LLM_API_KEY / LLM_MODEL      （如 https://api.deepseek.com/v1, deepseek-chat）
  VIDEO_API_URL / VIDEO_API_KEY               （你的视频生成服务，POST {prompt,resolution,seconds} → {task_id}）
  VIDEO_API_STATUS_URL                        （可选，GET 查询；缺省视为同步返回 {video_url}）
  STUDIO_BACKEND=agent|demo|form              （默认 agent：有 LLM key 走真循环，否则 demo 规划器）
"""
from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path

TOOLS = [
    {"name": "generate_video",
     "description": "根据一段创意生成视频（文生视频；若有参考图则图生视频）",
     "params": {"prompt": "英文或中文创意描述", "resolution": "360p|480p|720p|768p",
                "seconds": "时长秒数 2-15", "image": "参考图路径（可选）"}},
    {"name": "generate_talk",
     "description": "让参考图里的人物说一句台词（说话镜头：口型+音色+时长自动匹配）",
     "params": {"text": "台词原文", "image": "人物参考图路径", "voice": "h3(自适应)|yunxi|xiaoxiao|aria|daler"}},
    {"name": "make_story_film",
     "description": "把一个剧本/多段剧情做成连贯故事片（多段+台词+字幕）",
     "params": {"script": "剧情或剧本", "segments": "段数（默认自动）"}},
    {"name": "answer",
     "description": "不需要生成，只需要解释/建议/答疑",
     "params": {"text": "回答内容"}},
]

SYSTEM_PROMPT = """你是"H3 视频生成工坊"的创作 agent，部署在魔搭创空间（免费 CPU，本地不跑模型）。
你的职责：理解用户创意 → 选择合适工具 → 给出**可直接执行**的参数方案 → 交由外部视频 API 执行。
规则：
1) 用户要"说话镜头/台词/口型"→ generate_talk（台词原文照抄，不要改写）。
2) 用户要"故事/短剧/多段"→ make_story_film。
3) 其他创意 → generate_video；只问不生成 → answer。
4) 参数：默认 resolution=480p、seconds=5（说话镜头按时长自动匹配）；台词语言与音色要匹配。
5) 只输出一个 JSON：{"tool":"<工具名>","args":{...},"say":"给用户的一句中文说明"}，不要输出多余文本。
"""


def _env(name: str, default: str = '') -> str:
    return (os.environ.get(name) or default).strip()


class AgentClient:
    def __init__(self):
        self.llm_base = _env('LLM_BASE_URL').rstrip('/')
        self.llm_key = _env('LLM_API_KEY')
        self.llm_model = _env('LLM_MODEL', 'deepseek-chat')
        self.video_url = _env('VIDEO_API_URL')
        self.video_key = _env('VIDEO_API_KEY')
        self.video_status = _env('VIDEO_API_STATUS_URL')

    @property
    def mode(self) -> str:
        if self.llm_key or self.video_url:
            return 'agent-api'
        return 'demo-planner'

    # ---------- LLM 决策 ----------
    def plan(self, user_msg: str, history: list) -> dict:
        if not self.llm_key:
            return self._rule_plan(user_msg)
        msgs = [{"role": "system", "content": SYSTEM_PROMPT}]
        for h in (history or [])[-6:]:
            msgs.append({"role": h.get('role', 'user'), "content": h.get('content', '')[:800]})
        msgs.append({"role": "user", "content": user_msg})
        payload = {"model": self.llm_model, "messages": msgs, "temperature": 0.3,
                   "response_format": {"type": "json_object"}}
        try:
            import urllib.request
            req = urllib.request.Request(self.llm_base + '/chat/completions',
                                         data=json.dumps(payload).encode(),
                                         headers={'Authorization': 'Bearer ' + self.llm_key,
                                                  'Content-Type': 'application/json'})
            with urllib.request.urlopen(req, timeout=60) as r:
                d = json.loads(r.read().decode('utf-8', 'replace'))
            txt = (d.get('choices') or [{}])[0].get('message', {}).get('content', '{}')
            plan = json.loads(txt)
            if plan.get('tool'):
                return plan
        except Exception as e:  # noqa: BLE001
            return {'tool': 'answer', 'args': {'text': '（模型接口暂不可用：%s）' % str(e)[:120]},
                    'say': '我先按规则给你方案。'}
        return self._rule_plan(user_msg)

    @staticmethod
    def _rule_plan(user_msg: str) -> dict:
        """无 LLM key 时的规则规划器（演示 agent 的决策轨迹）。"""
        t = user_msg or ''
        quoted = ''
        for q in ('"', '“', '『'):
            if q in t:
                parts = t.split(q)
                if len(parts) >= 2:
                    quoted = parts[1].strip()
                break
        if any(k in t for k in ('台词', '说话', '口型', '说一句', '独白', '配音')):
            text = quoted or '你好，很高兴见到你。'
            return {'tool': 'generate_talk', 'args': {'text': text, 'voice': 'h3'},
                    'say': '明白，做一个说话镜头：让人物亲口说出"…"，时长按语音自动匹配。'}
        if any(k in t for k in ('故事', '短剧', '剧本', '多段', '连贯')):
            return {'tool': 'make_story_film', 'args': {'script': t[:200], 'segments': 3},
                    'say': '这是一个多段故事片需求：先出分镜，再逐段生成并拼接。'}
        if any(k in t for k in ('怎么', '如何', '为什么', '建议', '说明')):
            return {'tool': 'answer',
                    'args': {'text': '本空间=agent 前端（免费 CPU）：我负责理解需求、定参数、调外部生成 API；'
                                     '真实出片由外部视频服务完成。配置 LLM/VIDEO 接口后即可端到端生成。'},
                    'say': '这是做法说明。'}
        return {'tool': 'generate_video',
                'args': {'prompt': t[:400] or 'cinematic shot', 'resolution': '480p', 'seconds': 5},
                'say': '收到创意，我按文生视频出片（480p/5s 起步）。'}

    # ---------- 工具执行 ----------
    def run_tool(self, plan: dict) -> dict:
        tool = plan.get('tool')
        args = plan.get('args') or {}
        trace = {'tool': tool, 'args': args}
        if tool == 'answer':
            trace['result'] = 'answer'
            return {'ok': True, 'kind': 'answer', 'text': args.get('text', ''), 'trace': trace}
        if not self.video_url:
            trace['result'] = 'demo（未配置 VIDEO_API_URL）'
            return {'ok': True, 'kind': 'demo', 'tool': tool, 'args': args, 'trace': trace}
        # 调外部视频 API（约定：POST {prompt,seconds,resolution} → {task_id|video_url}）
        try:
            import urllib.request
            payload = {'prompt': args.get('prompt') or args.get('text') or args.get('script') or '',
                       'resolution': args.get('resolution', '480p'),
                       'seconds': int(args.get('seconds') or 5)}
            if tool == 'generate_talk':
                payload['text'] = args.get('text')
                payload['voice'] = args.get('voice', 'h3')
            req = urllib.request.Request(self.video_url,
                                         data=json.dumps(payload).encode(),
                                         headers={'Authorization': 'Bearer ' + self.video_key,
                                                  'Content-Type': 'application/json'})
            with urllib.request.urlopen(req, timeout=120) as r:
                d = json.loads(r.read().decode('utf-8', 'replace') or '{}')
            trace['result'] = d
            return {'ok': True, 'kind': 'remote', 'task': d.get('task_id') or d.get('id'),
                    'video': d.get('video_url'), 'trace': trace}
        except Exception as e:  # noqa: BLE001
            trace['result'] = 'ERR ' + str(e)[:160]
            return {'ok': False, 'kind': 'error', 'text': '外部生成接口调用失败：%s' % str(e)[:200],
                    'trace': trace}

    def answer(self, user_msg: str, history: list) -> dict:
        plan = self.plan(user_msg, history)
        out = self.run_tool(plan)
        out['say'] = plan.get('say') or ''
        out['mode'] = self.mode
        return out
