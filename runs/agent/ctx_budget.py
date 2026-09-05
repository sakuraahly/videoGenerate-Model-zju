"""
runs/agent/ctx_budget.py — 本地 Qwen(SGLang, ctx=8192) 的上下文预算工具（ui_app/CLI 共用）。

背景（2026-09-04 实测记录，见 docs/session-summary §13）：
- SGLang 服务端 max_model_len=8192（= config/llm_mem.json context_length），请求校验为
  「输入 tokens + max_tokens ≤ 8192」，超出直接 HTTP 400（qwen_agent 包装为
  ModelServiceError, code 400 —— 曾导致界面“继续”后报错）。
- qwen_agent(nous 函数调用) 每次 LLM 调用都会把工具定义模板追加进 system 消息，
  该固定开销不计入 qwen_agent 自带的粗略截断；实测（Qwen tokenizer / /v1 usage）：
  SYSTEM_MESSAGE=1828t + nous 工具定义/模板≈1270t ⇒ 每轮固定开销 ≈3090~3130 token。
- qwen_agent 的输入截断由 generate_cfg['max_input_tokens'] 控制（默认 58000，远大于
  8192 ≈ 从不生效）⇒ 必须显式设置，并让 ui_app 的历史裁剪与之对齐（token 口径）。

本模块导出：
- 常量：MODEL_MAX_CTX_TOKENS / REPLY_MAX_TOKENS / TOOL_PRELUDE_TOKENS / SAFETY_TOKENS
- count_tokens(text)      —— 精确优先（qwen_agent 自带 QWen tokenizer）；不可用时
                             退保守启发式（CJK≈1 token/字，ASCII≈1/3，只多不少）
- trim_messages(...)      —— token 口径裁剪：保最新轮次，预算内尽量保留首条 user
- request_budgets(system) —— (max_input_tokens, 固定开销)：
                             max_input_tokens 供 generate_cfg，qwen_agent 按
                             available = max_input_tokens − count(system) 截断对话部分
"""
from __future__ import annotations

# 服务端上下文上限（SGLang max_model_len；与 config/llm_mem.json context_length 同源，
# 若调服务端配置需同步本文件与 llm_mem.json）
MODEL_MAX_CTX_TOKENS = 8192

# 单轮回复 token 上限；同时 = 每次请求预留给 completion 的预算
# （8192 − 2048 ⇒ 输入部分最多 6144 token，超出即服务端 400）
REPLY_MAX_TOKENS = 800  # book-16 复读根治：2048→800（2048 长回复+超长 system 触发复读/ReadTimeout；实测 256/512 完全正常；不足 800 token 的长输出由工具轮/续接补足）

# nous 工具定义/模板固定开销（不含 SYSTEM_MESSAGE）：实测 5 工具 tool_descs 1207t
# + FN_CALL_TEMPLATE 93t ≈ 1300t；常量取 1500 覆盖未来新增文档清单/工具导致的增长。
TOOL_PRELUDE_TOKENS = 1500

# 本地计数 vs 服务端计数偏差、模板特判、时间戳等不确定量
SAFETY_TOKENS = 300

# 界面/CLI 存档历史裁剪预算（本地计数口径；对话部分在 qwen_agent 层的硬上限
# 为 framework 预算，本值略小，给「本回合内」工具往返结果留余量）
UI_TRIM_TOKENS = 2200

# 对话消息（user/assistant/function 往返，不含 system）在 qwen_agent 截断层允许的
# 本地计数预算：6144 − 固定开销(~3090~3130) − SAFETY ≈ 2500。
CONV_MSG_BUDGET_TOKENS = 2500

_tokenizer = None


def _get_tokenizer():
    """qwen_agent 自带 QWen tokenizer（惰性导入，仅 spark 运行时存在）。"""
    global _tokenizer
    if _tokenizer is None:
        try:
            from qwen_agent.utils.tokenization_qwen import tokenizer  # noqa: PLC0415
            _tokenizer = tokenizer
        except Exception:  # noqa: BLE001
            _tokenizer = False
    return _tokenizer or None


def count_tokens(text) -> int:
    """消息/文本的 token 估计：精确优先；无 tokenizer 时用保守启发式。

    实测比例（Qwen tokenizer）：中文散文 ≈0.4~1.0 token/字、英文 ≈0.16/字符；
    启发式取 CJK=1/字、其余=1/3，属“只多不少”的保守口径，保证裁剪不越界。
    """
    text = str(text or '')
    if not text:
        return 0
    tok = _get_tokenizer()
    if tok is not None:
        try:
            n = int(tok.count_tokens(text))
            return max(n, 0)
        except Exception:  # noqa: BLE001
            pass
    cjk = 0
    for ch in text:
        o = ord(ch)
        if (0x3400 <= o <= 0x4DBF or 0x4E00 <= o <= 0x9FFF
                or 0x20000 <= o <= 0x2FA1F or 0x3000 <= o <= 0x30FF
                or 0xAC00 <= o <= 0xD7AF or 0x2500 <= o <= 0x257F
                or 0xFF00 <= o <= 0xFFEF):
            cjk += 1
    return cjk + max(1, (len(text) - cjk) // 3)


def _msg_cost(m) -> int:
    return count_tokens(str(m.get('content', '')) if isinstance(m, dict) else str(m))


def trim_messages(msgs, budget_tokens: int = UI_TRIM_TOKENS,
                  keep_head: bool = True) -> tuple:
    """把消息列表裁到预算内（token 口径，替代旧字符口径）。

    策略：最新消息（本轮的 user 提问/“继续”）必须保留；从新到旧贪心纳入，
    预算内尽量保留首条 user 消息（旧语义“首轮意图”）；单条超预算时仍保留
    最新条（由 qwen_agent 层再按 keep_both_sides 做单条截断）。

    返回 (新列表, 是否发生裁剪)。不改动原列表。
    """
    if not msgs:
        return [], False
    total = sum(_msg_cost(m) for m in msgs)
    if total <= budget_tokens:
        return list(msgs), False

    head = []
    rest = msgs
    if keep_head and msgs[0].get('role') == 'user':
        hc = _msg_cost(msgs[0])
        if hc + 64 <= budget_tokens:
            head = [msgs[0]]
            rest = msgs[1:]
    cost = sum(_msg_cost(m) for m in head)
    keep = []  # 新→旧
    for m in reversed(rest):
        c = _msg_cost(m)
        if cost + c <= budget_tokens or not keep:
            keep.append(m)
            cost += c
        else:
            break
    out = head + list(reversed(keep))
    return out, len(out) < len(msgs)


def request_budgets(system_message: str = '') -> tuple:
    """按当前 system 文本计算本轮请求预算。

    返回 (max_input_tokens, fixed_overhead_tokens)：
    - max_input_tokens 写入 generate_cfg：qwen_agent 截断时
      available = max_input_tokens − count(system)，即对话往返部分 ≤
      CONV_MSG_BUDGET_TOKENS（本地口径）⇒ 服务端总输入 ≈ 固定开销 + 对话 ≤ 6144，
      与 REPLY_MAX_TOKENS=2048 合起来不越 ctx=8192。
    - fixed_overhead_tokens ≈ system + 工具模板实测开销（供日志/提示参考）。
    """
    sys_tok = count_tokens(system_message or '')
    overhead = sys_tok + TOOL_PRELUDE_TOKENS
    max_input = sys_tok + CONV_MSG_BUDGET_TOKENS
    # 兜底钳位：对话预算整体不许逼近服务端上限
    max_input = min(max_input,
                    MODEL_MAX_CTX_TOKENS - REPLY_MAX_TOKENS - SAFETY_TOKENS)
    return max(max_input, 0), overhead


def is_context_overflow_error(exc) -> bool:
    """判断异常是否 SGLang「请求超上下文」400（ModelServiceError 或 HTTP 400）。"""
    text = f'{type(exc).__name__}: {exc}'
    return ('maximum context length' in text
            or 'Requested token count exceeds' in text)
