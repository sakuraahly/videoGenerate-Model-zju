#!/usr/bin/env python3
"""ctx_budget 预算逻辑回归测试（无需 pytest / 无需 LLM）。

运行：python3 runs/agent/test_ctx_budget.py
在 spark 上（有 qwen_agent）走精确 tokenizer；本地无 qwen_agent 时走保守启发式，
断言都按“保守口径也必须成立”编写。
"""
import os
import sys

_here_root = os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))  # runs/agent/test_x.py → 仓库根
if os.path.isfile(os.path.join(_here_root, 'config', 'pipeline.json')):
    PROJECT_ROOT = _here_root   # 仓库内直跑（本机/spark 均可）
else:
    PROJECT_ROOT = os.environ.get(
        'VIDEOGEN_PROJECT_ROOT',
        os.path.expanduser('~/videoGenerate-Model-zju'),
    )
sys.path.insert(0, PROJECT_ROOT)
os.environ['VIDEOGEN_PROJECT_ROOT'] = PROJECT_ROOT

from runs.agent import ctx_budget as cb  # noqa: E402

_ZH = ('这是一段用于测试的中文内容，包含视频生成、参考素材选择、提示词工程与'
       '生成参数调整等话题的对话历史，用于验证上下文预算裁剪逻辑是否按 token '
       '口径正确工作，并保证不会撑爆模型的上下文窗口。')


def _hist(n, per_msg=2):
    msgs = []
    for i in range(n):
        msgs.append({'role': 'user', 'content': _ZH * per_msg + str(i)})
        msgs.append({'role': 'assistant', 'content': f'第{i}轮回复：' + _ZH[:80]})
    return msgs


def test_count_tokens():
    assert cb.count_tokens('') == 0
    assert cb.count_tokens('hi') > 0
    assert cb.count_tokens(_ZH * 5) > cb.count_tokens(_ZH)
    # 保守口径必须“只多不少”：中英文混合长文本 token 数 ≥ 字符数/4
    blob = (_ZH * 8 + 'eng words here ' * 50)
    assert cb.count_tokens(blob) >= len(blob) // 4, (cb.count_tokens(blob), len(blob))


def test_short_history_not_trimmed():
    msgs = _hist(2)
    out, dropped = cb.trim_messages(msgs, 100000)
    assert not dropped and len(out) == len(msgs)
    out, dropped = cb.trim_messages([])
    assert out == [] and not dropped


def test_long_history_trimmed_to_budget():
    msgs = _hist(25)  # 远超大预算
    msgs.append({'role': 'user', 'content': '继续'})  # 本轮新消息（界面语义）
    out, dropped = cb.trim_messages(msgs)
    assert dropped and 0 < len(out) < len(msgs)
    # 最新消息必须保留
    assert out[-1]['content'] == msgs[-1]['content']
    assert out[-1]['role'] == 'user'
    # 预算合规（head 已含在预算计算内）
    total = sum(cb.count_tokens(m.get('content', '')) for m in out)
    assert total <= cb.UI_TRIM_TOKENS, total
    # 保留的头以 user 开头（首轮意图尽量在）
    roles = [m['role'] for m in out]
    assert roles[0] == 'user'


def test_head_first_user_kept_when_affordable():
    msgs = _hist(20, per_msg=2)   # 精确 tokenizer 下总长仍 > UI_TRIM_TOKENS
    out, dropped = cb.trim_messages(msgs)
    assert dropped
    # 预算内应尽量保留首轮意图
    assert out[0]['content'] == msgs[0]['content'], out[0]


def test_request_budgets_within_server_limit():
    sys_text = ('你是受限调度器。\n' + _ZH) * 5   # ≈ 数千 token 的 system
    max_input, overhead = cb.request_budgets(sys_text)
    assert max_input > 0
    # max_input 语义 = tokens(system) + 对话预算，且整体不许逼近服务端上限
    assert max_input >= cb.count_tokens(sys_text)
    assert max_input <= (cb.MODEL_MAX_CTX_TOKENS - cb.REPLY_MAX_TOKENS
                         - cb.SAFETY_TOKENS)
    assert max_input + cb.REPLY_MAX_TOKENS < cb.MODEL_MAX_CTX_TOKENS
    assert overhead >= cb.count_tokens(sys_text)
    # 无 system 文本也能给出预算（>0）
    m2, _ = cb.request_budgets('')
    assert m2 > 0


def test_overflow_detector():
    real = ('ModelServiceError: Error code: 400 - {\'object\': \'error\', \'message\': '
            '"Requested token count exceeds the model\'s maximum context length of '
            '8192 tokens."}')
    class E(Exception):
        pass
    assert cb.is_context_overflow_error(E(real))
    assert not cb.is_context_overflow_error(E('connect timeout'))


if __name__ == '__main__':
    fns = [v for k, v in sorted(globals().items())
           if k.startswith('test_') and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f'PASS {fn.__name__}')
        except AssertionError as e:
            failed += 1
            print(f'FAIL {fn.__name__}: {e}')
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f'ERROR {fn.__name__}: {type(e).__name__}: {e}')
    print(f'{len(fns) - failed}/{len(fns)} passed')
    sys.exit(1 if failed else 0)
