"""studio.harness.state - 多 Agent Harness 的状态 / 轨迹 / 制片看板数据源。

设计要点（对齐 docs/planbook/book-20-studio-film-agent.md 第 4 章）：
  · 一条状态机跑两种大脑：访客填了模型 key 就是真模型在演，不填就是规则引擎在演，
    角色、状态、轨迹、看板**完全相同** —— 这是"调度与上下文(8 分)"能拿证据的前提。
  · 每一步都留 TraceStep：谁（role）、在哪个状态（state）、做了什么（action）、
    结果如何（status）、花了多久（ms）、产出什么（data）。trace.json 直接由它导出。
  · 状态迁移是**白名单**：非法跳转直接抛错，避免"看起来跑完了其实没跑"的假完成。

本模块纯标准库，不读文件、不联网、不打印，可单测。
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
import time

# ── 状态定义（顺序即正常流水线顺序） ──────────────────────────────────────────
IDLE = 'IDLE'
STORY = 'STORY'
SHOTS = 'SHOTS'
PRELINT = 'PRELINT'
DIRECT = 'DIRECT'
CRITIC = 'CRITIC'
KIT = 'KIT'
ENGINE = 'ENGINE'
DELIVER = 'DELIVER'
READY = 'READY'
DONE = 'DONE'
BLOCKED = 'BLOCKED'

ORDER = (IDLE, STORY, SHOTS, PRELINT, DIRECT, CRITIC, KIT, ENGINE, DELIVER, READY, DONE)

LABELS = {
    IDLE: '接收一句话',
    STORY: '编剧：一句话 → 剧本',
    SHOTS: '分镜：剧本 → 分镜表（帧网格校验）',
    PRELINT: '预检：规则闸门（不合格先改，不浪费算力）',
    DIRECT: '导演：逐段生产指令',
    CRITIC: '质检：规则轨打分 + 自动改写重试',
    KIT: '剪辑：组装可执行生产包',
    ENGINE: '执行：可选外部引擎出片',
    DELIVER: '交付：成片 / 清单 / 轨迹',
    READY: '方案就绪（未接引擎：交付生产包）',
    DONE: '完成',
    BLOCKED: '被闸门拦住（需改稿）',
}

# 迁移白名单：src -> 允许到达的下一批状态
TRANSITIONS = {
    IDLE: (STORY, BLOCKED),          # 连一句话都没有 → 直接 BLOCKED（拦在门外，不进流水线）
    STORY: (SHOTS, BLOCKED),
    SHOTS: (PRELINT, BLOCKED),
    PRELINT: (DIRECT, BLOCKED),
    DIRECT: (CRITIC,),
    CRITIC: (KIT, READY, BLOCKED),
    KIT: (ENGINE, READY, DONE),
    ENGINE: (DELIVER, READY),
    DELIVER: (DONE,),
    READY: (ENGINE, KIT),
    BLOCKED: (STORY, IDLE),
    DONE: (),
}

TERMINAL = (DONE, BLOCKED)


class StateError(RuntimeError):
    """非法状态跳转（白名单外）→ 上层应当报错而不是继续跑。"""


def can_go(src: str, dst: str) -> bool:
    return dst in TRANSITIONS.get(str(src), ())


def next_states(src: str) -> tuple:
    return tuple(TRANSITIONS.get(str(src), ()))


@dataclass
class TraceStep:
    """一步可观测的执行记录（trace.json 的元素）。"""

    i: int
    state: str
    role: str
    action: str
    status: str = 'ok'          # ok | warn | error | retry | info
    detail: str = ''
    via: str = 'rule'           # rule | llm | agent | engine
    ms: int = 0
    data: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    def line(self) -> str:
        tag = {'ok': 'OK ', 'warn': 'WARN', 'error': 'ERR', 'retry': 'RETRY', 'info': 'INFO'}.get(self.status, 'OK ')
        return '[%02d] %-9s %-12s %s %s %s' % (self.i, self.state, self.role, tag,
                                               ('(%s)' % self.via) if self.via != 'rule' else '', self.detail)


@dataclass
class StoryState:
    """一次"一句话出片"全过程的共享上下文（Harness 的上下文，也是看板的数据源）。"""

    brief: str = ''
    style: str = 'cinematic'
    target_seconds: float = 30.0
    cast_mode: str = 'solo'
    resolution: str = '480p'
    seed: str = ''
    anchor: bool = False
    assets_licensed: bool = False

    state: str = IDLE
    mode: str = 'plan'              # plan（只出方案/生产包）| engine（接了引擎，真出片）
    brain_kind: str = 'rule'        # rule | llm | agent

    script: dict = field(default_factory=dict)
    shots: list = field(default_factory=list)
    prelint: dict = field(default_factory=dict)
    directives: list = field(default_factory=list)
    critic: dict = field(default_factory=dict)
    kit: dict = field(default_factory=dict)          # 看板用的摘要（JSON 安全）
    kit_blob: dict = field(default_factory=dict)     # 全量生产包（含 zip 字节；不进看板）
    delivery: dict = field(default_factory=dict)

    trace: list = field(default_factory=list)
    roles: dict = field(default_factory=dict)
    retries: int = 0
    warnings: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    started_at: float = field(default_factory=time.time)
    t0: float = field(default_factory=time.perf_counter)

    # ── 轨迹 ────────────────────────────────────────────────────────────────
    def log(self, role: str, action: str, *, status: str = 'ok', detail: str = '',
            via: str = 'rule', data: dict = None, ms: int = 0) -> TraceStep:
        step = TraceStep(i=len(self.trace) + 1, state=self.state, role=role, action=action,
                         status=status, detail=detail, via=via, ms=int(ms or 0),
                         data=(data or {}))
        self.trace.append(step)
        if status == 'error':
            self.errors.append('%s: %s' % (action, detail or role))
        elif status == 'warn' and detail:
            self.warnings.append('%s: %s' % (action, detail))
        if status == 'retry':
            self.retries += 1
        return step

    def role_status(self, key: str, status: str = None, *, via: str = None,
                    summary: str = None, ms: int = None) -> dict:
        row = self.roles.setdefault(str(key), {'status': 'pending', 'via': 'rule',
                                               'summary': '', 'ms': 0, 'lines': []})
        if status:
            row['status'] = status
        if via:
            row['via'] = via
        if summary is not None:
            row['summary'] = summary
        if ms is not None:
            row['ms'] = int(ms)
        return row

    def enter(self, dst: str) -> str:
        """状态迁移（白名单）。非法跳转抛 StateError —— 不静默吞掉。"""
        if not can_go(self.state, dst):
            raise StateError('非法状态跳转: %s -> %s（允许: %s）'
                             % (self.state, dst, '/'.join(next_states(self.state)) or '无'))
        prev, self.state = self.state, dst
        self.log('orchestrator', 'state', status='info',
                 detail='%s → %s（%s）' % (prev, dst, LABELS.get(dst, dst)))
        return dst

    def block(self, reason: str, role: str = 'guard') -> None:
        """被闸门拦住：记 error 并进入 BLOCKED（仍可回 STORY 改稿）。"""
        self.log(role, 'blocked', status='error', detail=reason)
        if can_go(self.state, BLOCKED):
            self.enter(BLOCKED)

    # ── 输出 ────────────────────────────────────────────────────────────────
    def progress(self) -> dict:
        """进度按 ORDER 里已到达的状态数估算（页面进度条用）。"""
        idx = ORDER.index(self.state) if self.state in ORDER else 0
        return {'done': idx, 'total': len(ORDER) - 1, 'state': self.state,
                'percent': int(round(idx * 100.0 / (len(ORDER) - 1)))}

    def to_dict(self) -> dict:
        return {
            'brief': self.brief, 'style': self.style, 'target_seconds': self.target_seconds,
            'cast_mode': self.cast_mode, 'resolution': self.resolution, 'seed': self.seed,
            'anchor': self.anchor, 'assets_licensed': self.assets_licensed,
            'state': self.state, 'state_label': LABELS.get(self.state, self.state),
            'mode': self.mode, 'brain': self.brain_kind,
            'script': self.script, 'shots': self.shots, 'prelint': self.prelint,
            'directives': self.directives, 'critic': self.critic, 'kit': self.kit,
            'delivery': self.delivery, 'trace': [s.to_dict() for s in self.trace],
            'retries': self.retries, 'warnings': self.warnings, 'errors': self.errors,
            'elapsed_ms': int((time.perf_counter() - self.t0) * 1000),
        }

    def board(self) -> dict:
        """制片看板（页面直接渲染这个 dict，不必理解内部结构）。"""
        return {
            'state': self.state,
            'state_label': LABELS.get(self.state, self.state),
            'mode': self.mode,
            'mode_label': ('接引擎真出片' if self.mode == 'engine' else '仅生产计划（未接引擎）'),
            'brain': self.brain_kind,
            'progress': self.progress(),
            'brief': self.brief,
            'roles': self.roles,
            'cards': {
                'script': self.script,
                'shots': self.shots,
                'prelint': self.prelint,
                'critic': self.critic,
                'kit': self.kit,
                'delivery': self.delivery,
            },
            'counts': {
                'segments': len(self.script.get('segments') or []),
                'shots': len(self.shots),
                'directives': len(self.directives),
                'lines': len(self.script.get('lines') or {}),
                'retries': self.retries,
                'errors': len(self.errors),
                'warnings': len(self.warnings),
            },
            'trace': [s.to_dict() for s in self.trace],
            'elapsed_ms': int((time.perf_counter() - self.t0) * 1000),
        }
