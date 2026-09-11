#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""voice — 台词语言 → 音色匹配（纯函数，零依赖）。

口径来源（搬 runs/h3/tts.py::match_voice_to_text，2026-09-11 修复「模型给中文台词配英文音色」）：
  · 中日韩字符占比 ≥ 20% → 视作中文；几乎全拉丁 → 视作英文（阈值与 runs/h3 一致，见 ZH_CJK_RATIO）；
  · 中文台词 → 中文音色（女 xiaoxiao / 男 yunxi）；英文台词 → 英文音色（女 aria / 男 daler）；
  · 语言或性别判不出来时给**默认**（中文 xiaoxiao、英文 aria），并在 reason 里写明「默认」二字——
    机器不猜，人可改；本项目的反虚构纪律同样适用于音色选择。

与 runs/h3 的差异（本包取更严/更明确的一侧，两处口径**不可混用**）：
  · runs/h3 的 match_voice_to_text(text, voice) 做的是「**校正**已有音色」（音色与语言不符才替换）；
    本函数是「**从零选**音色」，并把判断依据写进 reason，供页面展示与人工复核；
  · explicit 一旦给出就**原样采用**（只做短名归一化），任何情况下都不做语言校正——
    人的明确选择优先于任何启发式规则。

公开 API：
  detect_lang(text) -> "zh" | "en" | "mixed"
  match_voice_to_text(text, explicit="") -> {"voice", "lang", "reason"}
  detect_gender(text) -> "male" | "female" | ""          # 加分项：性别线索识别
  normalize_voice(name) / voice_full_name(voice)         # 短名 ↔ 语音服务全名（与 runs/h3 词表同源）
"""
from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# 音色表（短名定案；全名与 runs/h3/tts.py::VOICE_ALIASES 同源，不臆造未登记的名字）
# ---------------------------------------------------------------------------
ZH_VOICE_FEMALE = "xiaoxiao"   # zh-CN-XiaoxiaoNeural：女声/新闻小说（runs/h3 的 DEFAULT_VOICE）
ZH_VOICE_MALE = "yunxi"        # zh-CN-YunxiNeural：男声
EN_VOICE_FEMALE = "aria"       # en-US-AriaNeural：美音女声
EN_VOICE_MALE = "daler"        # 英文男声短名（runs/h3/tts.py::_EN_VOICES 已登记，全名待登记）

#: 自动选择只用这四个短名（与 book-20 §2.3-6「中文 xiaoxiao/yunxi、英文 aria/daler」定案一致）
VOICES = (ZH_VOICE_FEMALE, ZH_VOICE_MALE, EN_VOICE_FEMALE, EN_VOICE_MALE)

#: 短名 → 语言（"zh"/"en"）
VOICE_LANGS = {ZH_VOICE_FEMALE: "zh", ZH_VOICE_MALE: "zh",
               EN_VOICE_FEMALE: "en", EN_VOICE_MALE: "en"}

#: 短名 → 性别（"female"/"male"）
VOICE_GENDERS = {ZH_VOICE_FEMALE: "female", ZH_VOICE_MALE: "male",
                 EN_VOICE_FEMALE: "female", EN_VOICE_MALE: "male"}

#: (语言, 性别) → 短名；性别判不出时统一按 female 兜底（见 match_voice_to_text）
VOICE_BY_LANG_GENDER = {
    ("zh", "female"): ZH_VOICE_FEMALE, ("zh", "male"): ZH_VOICE_MALE,
    ("en", "female"): EN_VOICE_FEMALE, ("en", "male"): EN_VOICE_MALE,
}

#: 短名 → 语音服务全名。daler 全名尚未在 runs/h3 落定（该文件注释：男英文用
#: en-US-ChristopherNeural 待登记）→ 这里**故意不给**，voice_full_name("daler") 回落到短名本身。
VOICE_FULL_NAMES = {
    ZH_VOICE_FEMALE: "zh-CN-XiaoxiaoNeural",
    ZH_VOICE_MALE: "zh-CN-YunxiNeural",
    EN_VOICE_FEMALE: "en-US-AriaNeural",
}

#: 别名（小写）→ 短名；含 runs/h3/tts.py::VOICE_ALIASES 里的全名与 en-aria。
#: 这些别名只在 explicit 透传时用于归一化，**不参与自动选择**（自动选择只用 VOICES 四个）。
VOICE_ALIASES = {
    "en-aria": EN_VOICE_FEMALE,
    "zh-cn-xiaoxiaoneural": ZH_VOICE_FEMALE,
    "zh-cn-yunxineural": ZH_VOICE_MALE,
    "en-us-arianeural": EN_VOICE_FEMALE,
}

#: runs/h3 已登记、但不在本书「四短名」范围内的中文音色（显式传入时只用于判语言，原样透传）
_EXTRA_ZH_VOICES = ("yunjian", "yunyang", "xiaoyi")
_EXTRA_ZH_FULL_NAMES = ("zh-cn-yunjianneural", "zh-cn-yunyangneural", "zh-cn-xiaoyineural")

# ---------------------------------------------------------------------------
# 语言判定阈值（与 runs/h3/tts.py::match_voice_to_text 完全一致，勿改）
# ---------------------------------------------------------------------------
ZH_CJK_RATIO = 0.2      # CJK 占比 ≥ 20% 即按中文配中文音色（runs/h3 原值）
MIXED_HI = 0.85         # 仅用于 detect_lang 的三分类标签：≥85% 记 "zh"
MIXED_LO = 0.15         # ≤15% 记 "en"；两者之间记 "mixed"（配什么音色仍按 ZH_CJK_RATIO 走多数派）

_LANG_CN = {"zh": "中文", "en": "英文"}

# ---------------------------------------------------------------------------
# 性别线索词表（加分项：句子里点名了「他/爸爸/老人」这类词，就不该再默认女声）
# 中文单字线索（他/她）需要排除「其他/他人」这类**不是指人**的常见词，否则会误判成男声。
# ---------------------------------------------------------------------------
MALE_HINTS_ZH = ("他", "爸爸", "父亲", "父", "老人", "男", "爷爷", "老爷", "叔叔", "哥哥", "兄弟",
                 "先生", "少年", "男孩", "丈夫", "老公", "公子")
# 注意：**不收单字「母」**——「字母/航母」会被误判成女声线索；「母亲/妈妈」已足够覆盖。
FEMALE_HINTS_ZH = ("她", "妈妈", "母亲", "女", "奶奶", "姥姥", "阿姨", "姐姐", "妹妹", "女士",
                   "姑娘", "女孩", "少女", "妻子", "老婆", "夫人", "小姐")
MALE_HINTS_EN = ("he", "him", "his", "man", "men", "father", "dad", "boy", "brother", "sir",
                 "uncle", "grandfather", "king", "gentleman", "guy", "male")
FEMALE_HINTS_EN = ("she", "her", "hers", "woman", "women", "mother", "mom", "mum", "girl", "sister",
                   "madam", "aunt", "grandmother", "queen", "lady", "female")

#: 中文里含「他」但不指人的词（先挖掉再数「他」，否则「其他」会被算成男声线索）
_TA_FALSE_POSITIVES = ("其他", "其它", "他人", "他乡", "他日", "利他", "维他", "他国")

_EN_MALE_RE = re.compile(r"\b(?:%s)\b" % "|".join(MALE_HINTS_EN), re.IGNORECASE)
_EN_FEMALE_RE = re.compile(r"\b(?:%s)\b" % "|".join(FEMALE_HINTS_EN), re.IGNORECASE)


def _counts(text: str) -> tuple:
    """(CJK 字数, 拉丁字母数)。CJK 含汉字与日文假名——与 runs/h3 的统计口径一致。"""
    t = str(text or "")
    cjk = sum(1 for ch in t if "\u4e00" <= ch <= "\u9fff" or "\u3040" <= ch <= "\u30ff")
    letters = sum(1 for ch in t if ch.isascii() and ch.isalpha())
    return cjk, letters


def cjk_ratio(text: str) -> float:
    """CJK 字符在「CJK + 拉丁字母」里的占比（无任何可判字符时返回 1.0 = 按中文兜底）。"""
    cjk, letters = _counts(text)
    if cjk + letters == 0:
        return 1.0
    return cjk / (cjk + letters)


def detect_lang(text: str) -> str:
    """判定台词语言："zh" | "en" | "mixed"。

    标签口径（三分类，供页面展示与人复核）：
      · CJK 占比 ≥ 85% → "zh"；≤ 15% → "en"；两者之间 → "mixed"（中英混排）；
      · 空文本 / 只有标点数字（没有任何可判字符）→ "zh"（与 runs/h3 空文本回落 xiaoxiao 一致）。
    注意：**配哪个音色不由本函数决定**，而由 cjk_ratio(text) >= ZH_CJK_RATIO 决定
    （即 "mixed" 也按占比高的那一侧配），保持与 runs/h3/tts.py 的口径一致。
    """
    cjk, letters = _counts(text)
    if cjk + letters == 0:
        return "zh"
    r = cjk / (cjk + letters)
    if r >= MIXED_HI:
        return "zh"
    if r <= MIXED_LO:
        return "en"
    return "mixed"


def lang_family(text: str) -> str:
    """台词该配哪一侧音色："zh" 或 "en"（阈值口径 = runs/h3，CJK 占比 ≥ 20% 即中文侧）。"""
    cjk, letters = _counts(text)
    if cjk + letters == 0:
        return "zh"
    return "zh" if (cjk / (cjk + letters)) >= ZH_CJK_RATIO else "en"


def _zh_gender_hits(text: str) -> tuple:
    """中文性别线索命中数 (男, 女)，命中词按去重后的出现次数计。"""
    t = str(text or "")
    t_masked = t
    for w in _TA_FALSE_POSITIVES:          # 「其他/他人」不是人 → 先挖掉再数「他」
        t_masked = t_masked.replace(w, "\u3007\u3007")
    male = sum(t_masked.count(w) for w in set(MALE_HINTS_ZH))
    female = sum(t.count(w) for w in set(FEMALE_HINTS_ZH))
    return male, female


def _gender_detail(text: str) -> dict:
    """性别线索明细：{"gender": "male|female|", "male": n, "female": n}。

    男女线索**同时出现**（如「他把信递给她」）时判为 ""（不确定）→ 上层回落到默认女声，
    而不是硬挑一个——挑错比默认更贵（默认音色页面上一键可改，配错音色要重录一遍）。
    """
    m_zh, f_zh = _zh_gender_hits(text)
    t = str(text or "")
    m = m_zh + len(_EN_MALE_RE.findall(t))
    f = f_zh + len(_EN_FEMALE_RE.findall(t))
    if m > f:
        gender = "male"
    elif f > m:
        gender = "female"
    else:
        gender = ""                        # 都没有，或数量相同（含并存）→ 不确定
    return {"gender": gender, "male": m, "female": f}


def detect_gender(text: str) -> str:
    """从台词文本里识别说话人性别："male" | "female" | ""（不确定）。

    线索词表见 MALE_HINTS_ZH / FEMALE_HINTS_ZH / MALE_HINTS_EN / FEMALE_HINTS_EN；
    男女线索并存且数量相同 → 返回 ""（不确定，交给默认）。
    """
    return _gender_detail(text)["gender"]


def normalize_voice(name: str) -> str:
    """音色名归一化：去空白/转小写，全名与别名（含 en-aria）→ 短名；未登记的名字**原样返回**。"""
    v = str(name or "").strip()
    if not v:
        return ""
    low = v.lower()
    if low in VOICE_ALIASES:
        return VOICE_ALIASES[low]
    if low in VOICES:
        return low
    if low in _EXTRA_ZH_FULL_NAMES:
        return low                       # 未纳入四短名的中文音色：保留原样（不做自动选择）
    return v


def voice_full_name(voice: str) -> str:
    """短名 → 语音服务全名；未登记（如 daler）时回落为归一化后的短名，绝不臆造全名。"""
    v = normalize_voice(voice)
    return VOICE_FULL_NAMES.get(v, v)


def match_voice_to_text(text: str, explicit: str = "") -> dict:
    """台词 → 音色匹配。返回 {"voice": 短名, "lang": "zh|en", "reason": 中文依据}。

    规则（顺序即优先级）：
      ① explicit 非空 → **原样采用**（只做短名归一化，如 "zh-CN-XiaoxiaoNeural" → "xiaoxiao"），
         reason 里写明「显式指定」；explicit="auto"/"h3"/"native" 视同未指定（与 runs/h3 一致）；
      ② 否则按语言配：CJK 占比 ≥ 20% → 中文侧，否则英文侧（阈值搬 runs/h3，勿改）；
      ③ 语言内再按性别线索选：男声线索 → yunxi/daler，女声线索 → xiaoxiao/aria，
         无线索或男女并存 → 默认女声（xiaoxiao/aria），reason 里写明「默认」。

    用法：
        >>> r = match_voice_to_text("爸爸，我回来了。")   # {'voice': 'yunxi', 'lang': 'zh', ...}
        >>> r = match_voice_to_text("Hello there.", explicit="yunxi")
        >>> r["voice"]                                    # 'yunxi'（人指定优先，不做语言校正）
    """
    raw = str(text or "")
    exp = str(explicit or "").strip()

    if exp and exp.lower() not in ("auto", "h3", "native"):
        v = normalize_voice(exp)
        lang = VOICE_LANGS.get(v)
        src = "按音色登记表"
        if lang is None:                       # 不在四短名里：先看是不是已登记的中文音色
            if v.lower() in _EXTRA_ZH_VOICES:
                lang, src = "zh", "按已登记中文音色表"
            else:                              # 完全未登记：原样透传，语言只作标注
                lang, src = lang_family(raw), "按台词文本推断（未登记音色，原样透传）"
        reason = (f"显式指定 explicit={exp!r} → 原样采用 {v}（只做短名归一化，不做语言校正）；"
                  f"语言标注 {lang}（{src}）")
        return {"voice": v, "lang": lang, "reason": reason}

    lang = lang_family(raw)
    label = detect_lang(raw)
    detail = _gender_detail(raw)
    gender = detail["gender"]
    voice = VOICE_BY_LANG_GENDER[(lang, gender or "female")]
    ratio = cjk_ratio(raw)

    if gender == "male":
        g_txt = f"男声线索 {detail['male']} 处 → 男性音色"
    elif gender == "female":
        g_txt = f"女声线索 {detail['female']} 处 → 女性音色"
    else:
        g_txt = ("无性别线索或男女线索并存 → **默认女性音色**（页面可一键改）"
                 if (detail["male"] or detail["female"]) else "无性别线索 → **默认女性音色**（页面可一键改）")

    reason = (f"语言：检测标签 {label}（CJK 占比 {ratio:.0%}，≥{ZH_CJK_RATIO:.0%} 走中文侧）"
              f"→ {_LANG_CN[lang]}侧音色；{g_txt}；选定 {voice}")
    return {"voice": voice, "lang": lang, "reason": reason}


__all__ = [
    "ZH_VOICE_FEMALE", "ZH_VOICE_MALE", "EN_VOICE_FEMALE", "EN_VOICE_MALE",
    "VOICES", "VOICE_LANGS", "VOICE_GENDERS", "VOICE_BY_LANG_GENDER",
    "VOICE_FULL_NAMES", "VOICE_ALIASES", "ZH_CJK_RATIO", "MIXED_HI", "MIXED_LO",
    "MALE_HINTS_ZH", "FEMALE_HINTS_ZH", "MALE_HINTS_EN", "FEMALE_HINTS_EN",
    "detect_lang", "lang_family", "cjk_ratio", "detect_gender",
    "normalize_voice", "voice_full_name", "match_voice_to_text",
]
