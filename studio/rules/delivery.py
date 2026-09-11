"""studio.rules.delivery - 交付规范：验收规则 / 交付清单 / 续跑与诚实降级文案（纯文本）。

口径来源：runs/session_outputs.py / runs/quality.py 的产物登记与交付语义，
在创空间语境下改写成"访客/评审看得懂、能照做"的清单。

反虚构纪律：失败就是失败 —— 失败段如实标注、可跳过、给续跑命令，
绝不用"已完成"糊过去（book-20 §4.5 / §9）。
"""
from __future__ import annotations

FPS = 24

#: 交付说明里固定输出的 AI 声明（合规 4 分：AI 生成须声明）
AI_DISCLAIMER = ('本片由 AI 生成：全片画面与声音均为模型合成，未使用任何未经授权的真人肖像'
                 '或受版权保护的素材。')

#: 片尾建议文案
CREDITS_SUGGESTION = '片尾建议加一行：本片由 AI 生成 · 由「AI+∞ 电影 Agent」规划与质检'

#: 引擎侧可选的 VLM 检查项（空间内不判帧，交给执行方）
VLM_CHECKLIST = [
    '画面里是否出现任何文字/字幕/水印（出现即不合格）',
    '人物是否与参考图一致（换脸/串脸即不合格）',
    '说话镜头的口型与台词是否同步（唇动无声即不合格）',
    '相邻段的场景与光线是否连贯（跳变即不合格）',
]

DELIVERABLE_KIT = 'production_kit.zip（plan.json / jobs.jsonl / commands.md / run_plan.py / accept.md / trace.json / README.md）'
DELIVERABLE_SEGMENTS = '每段成片或可复制的生产指令（jobs.jsonl 一行一段，复制即用）'
DELIVERABLE_ACCEPT = '验收清单 accept.md（规则验收 + 引擎侧可选 VLM 检查项）'
DELIVERABLE_TRACE = '决策轨迹 trace.json（5 角色分工与重试的证据）'


def accept_rules(frames: int, has_line: bool, line_text: str = '', resolution: str = '480p') -> list:
    """单段验收规则（写进生产包 accept.md，也是页面"照做就能拍"的判据）。"""
    out = ['帧数 %d（5+17k 网格 @ %d fps）→ %.2fs ｜ 画幅 %s'
           % (int(frames), FPS, int(frames) / float(FPS), resolution),
           '画面无任何文字/字幕/水印（正向提示词已不含文字指令）']
    if has_line and line_text:
        out.append('台词「%s」由模型原声说出且口型同步（唇动无声即不合格）' % line_text)
    else:
        out.append('该段无人说话：出现唇动/口型即视为不合格')
    out.append('人物与参考图一致（跨段同一张脸）')
    return out


def manifest(title: str, *, shots: int, seconds: float, frames: int, talking_shots: int,
             resolution: str, has_kit: bool = True) -> dict:
    """交付清单（页面"交付说明"面板 + 生产包 README）。"""
    items = [DELIVERABLE_KIT if has_kit else '生产计划（plan.json / jobs.jsonl / commands.md）',
             DELIVERABLE_SEGMENTS, DELIVERABLE_ACCEPT, DELIVERABLE_TRACE]
    return {
        'title': title, 'shots': shots, 'seconds': round(float(seconds), 2), 'frames': frames,
        'talking_shots': talking_shots, 'resolution': resolution,
        'ai_disclaimer': AI_DISCLAIMER, 'credits_suggestion': CREDITS_SUGGESTION,
        'deliverables': items, 'vlm_checklist': list(VLM_CHECKLIST),
    }


def resume_advice(failed: list, total: int, done: list = None) -> str:
    """失败段续跑建议（诚实降级：跳过失败段也能交付）。"""
    failed = list(failed or [])
    if not failed:
        return '全部 %d 段就绪，无需续跑。' % int(total)
    done = list(done or [])
    return ('第 %s 段失败/未完成（共 %d 段，已完成 %d 段）→ 修好后**只重跑失败段**：'
            'run_plan.py --only %s ；成片可先用已完成段拼接交付，交付说明里如实标注缺哪段。'
            % ('/'.join(str(x) for x in failed), int(total), len(done),
               ','.join(str(x) for x in failed)))


def honest_notes(mode: str = 'plan', engine_ready: bool = False) -> list:
    """必须如实说明的边界（页面 MODE 提示 + README 固定段）。"""
    notes = ['本空间**不部署任何模型、不推理**：它负责规划、质检与生成可执行指令。',
             '成片算力来自**访客自带**的视频生成引擎（或执行方本机 GPU），与本空间无关。']
    if mode == 'engine' and engine_ready:
        notes.append('当前已配置引擎 → MODE = 真出片（成片由访客配置的引擎生成）。')
    else:
        notes.append('当前未配置引擎 → MODE = 仅生产计划（交付可复制的生产包，仍可完整复现）。')
    notes.append('失败段如实标注并可跳过，不用"已完成"掩盖。')
    return notes


__all__ = ['AI_DISCLAIMER', 'CREDITS_SUGGESTION', 'VLM_CHECKLIST', 'DELIVERABLE_KIT',
           'DELIVERABLE_SEGMENTS', 'DELIVERABLE_ACCEPT', 'DELIVERABLE_TRACE',
           'accept_rules', 'manifest', 'resume_advice', 'honest_notes']
