#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""lint — 剧本静态预检（纯逻辑，零依赖；搬自 runs/h3/story_lint.py + 合规预检）。

为什么需要（spark 定案 2026-09-10；创空间 P0 见 docs/planbook/book-20-studio-film-agent.md
§2.3「规则引擎做得很厚」第 5 条：搬 story_lint 全部规则 + IP 专有名词/版权词表 + 素材授权检查）：
故事片的坑几乎都出在"文本层"，一旦开跑就是几分钟 GPU 白烧；创空间更严 —— 剧本直接来自
访客的一句话，还可能整段带着"别人的角色"。所以两件事都做成 **0 成本静态检查**：
  · 台词用引号写进 prompt → 模型会把台词**画成画面字幕**（实测几乎必画），成片变成两条叠字；
  · 台词没写 speaker 而本镜头有多个角色 → 不知道谁在说；
  · cast 里写了 characters 里没有的人 → 人物形象卡注入失败，脸会漂；
  · 台词太长而 seconds 太小 → 话说一半画面就结束；
  · 一个镜头堆 3 个以上动作 / prompt 过长 → 模型容易漏动作；
  · style 里同时要字又不要字 → 自相矛盾；
  · prompt 里塞中文指令文本 → 被画成乱码叠字（除非确实要画面文字）；
  · 有角色、没台词 → 模型自己让人物说话，剔掉乱语音轨后成片"唇动无声"；
    **（创空间新增豁免）** 但 prompt 里显式写了 "the character stays silent here: mouth closed,
    no speech" 时不再告警 —— 静默是设计，不是疏漏；
  · **（创空间新增）** 出现已知影视 IP 的专有名词/角色名/台词特征词 → 版权风险，必须改写为原创设定；
  · **（创空间新增）** 声明了参考图/素材却没有授权标记 → 素材来源不明，平台合规风险。

error 与 warning 的判据：
  error   = 改一处就能改对、且不改**必然出事**（画面叠字 / 说话人错 / 人物卡失效 / 索引越界 /
            版权命中）→ 只要有一条 error，ok = False，上层应拦住不往下拍，先把稿子交给 agent 改。
  warning = 建议改；不改也能拍，但成片质量可能掉（时长不匹配 / 动作过多 / 中文文本 /
            素材授权待确认）→ 不影响 ok，如实展示给访客即可。

用法（上层只认这一个入口；本模块不读文件、不联网、不打印）：
    from studio.rules import lint
    rep = lint.lint_story(story)          # story 就是剧本 JSON（dict）
    if not rep["ok"]:
        ...                               # rep["errors"] 逐条给访客看 / 丢回给 agent 改稿
    rep["summary"]                        # 'LINT_SUMMARY: errors=0 warnings=1'

约束：纯标准库（只用 re）；不 import 项目内其它模块；全部函数可单测。
"""
from __future__ import annotations

import re

__all__ = ["lint_story", "lint", "IP_TERMS", "IP_WEAK_TERMS", "SEC_PER_CHAR"]

# ── 与 spark 对齐的常量（原样搬，勿改：story_film / frames 的口径必须一致） ──────────
SEC_PER_CHAR = 0.36        # 台词秒数估算：0.36s/字 + 1s 余量（与 story_film 一致）
PROMPT_MAX_CHARS = 1600    # 单段 prompt 字符上限（超了模型容易漏动作）
BASE_SECONDS = 4           # story 没写 seconds 时的默认段时长
MAX_IP_REPORTS = 12        # IP 命中最多逐条报这么多（访客剧本可能整篇照搬，别刷屏）

# 引号 = 模型"把台词画成画面字幕"的触发开关（半角 + 弯引号 + 中日式引号全算）
_QUOTE_RE = re.compile(r'[\u201c\u201d"\u300c\u300d\u300e\u300f]')
# 单镜头单动作（粗判：then/然后 堆到 3 个说明该拆段）
_ACTION_RE = re.compile(r'\bthen\b|然后|接着|随后', re.I)
# "确实要画面文字"的显式写法（招牌原文等）
_WANT_TEXT_RE = re.compile(r'sign reads|招牌上写着|字样是', re.I)
# style 里的禁字声明
_BAN_TEXT_RE = re.compile(r'no (on-screen )?(text|lettering|subtitles)', re.I)
# 中文指令文本（会被画进画面）
_CJK_RE = re.compile(r'[\u4e00-\u9fff]{2,}')
# 5.6) 新增：静默镜的**显式不说话声明**（有它才算"本镜就该没声音"，否则才报警）
_SILENCE_RE = re.compile(
    r'(no speech|stays? silent|remain[s]? silent|does not speak|do not speak|mouth closed|'
    r'silent here|no dialogue|no lip movement)', re.I)

# ── 版权/IP 词表（可扩展：加词条即可） ─────────────────────────────────────────
# 命中即 **error**：这些是受版权保护的影视 IP 的专有名词 / 角色名 / 台词特征词，
# 写进 prompt 就会把"别人的角色和标志性道具"画进成片 —— 平台合规风险，不是风格问题。
# 格式：(词条, 归属)；ASCII 词条按整词匹配，中文词条按子串匹配（见 _term_pattern）。
IP_TERMS = (
    # 《星球大战》
    ("star wars", "《星球大战》"), ("jedi", "《星球大战》绝地武士"), ("sith", "《星球大战》西斯"),
    ("darth vader", "《星球大战》达斯·维达"), ("darth", "《星球大战》达斯·维达"),
    ("stormtrooper", "《星球大战》风暴兵"), ("lightsaber", "《星球大战》光剑"),
    ("skywalker", "《星球大战》天行者"), ("millennium falcon", "《星球大战》千年隼"),
    ("x-wing", "《星球大战》X 翼战机"), ("tatooine", "《星球大战》塔图因"),
    ("chewbacca", "《星球大战》楚巴卡"), ("yoda", "《星球大战》尤达"),
    ("may the force", "《星球大战》台词"), ("i am your father", "《星球大战》台词"),
    ("星球大战", "《星球大战》"), ("风暴兵", "《星球大战》风暴兵"), ("暴风兵", "《星球大战》风暴兵"),
    ("黑武士", "《星球大战》达斯·维达"), ("达斯维达", "《星球大战》达斯·维达"),
    ("达斯·维达", "《星球大战》达斯·维达"), ("绝地", "《星球大战》绝地武士"),
    ("光剑", "《星球大战》光剑"), ("天行者", "《星球大战》天行者"), ("千年隼", "《星球大战》千年隼"),
    ("愿原力与你同在", "《星球大战》台词"), ("尤达", "《星球大战》尤达"), ("楚巴卡", "《星球大战》楚巴卡"),
    ("塔图因", "《星球大战》塔图因"),
    # 《2001 太空漫游》（裸 2001/HAL 太容易误伤普通用词 → 见 IP_WEAK_TERMS）
    ("2001: a space odyssey", "《2001 太空漫游》"), ("a space odyssey", "《2001 太空漫游》"),
    ("space odyssey", "《2001 太空漫游》"), ("hal 9000", "《2001 太空漫游》HAL 9000"),
    ("hal9000", "《2001 太空漫游》HAL 9000"), ("2001太空漫游", "《2001 太空漫游》"),
    ("太空漫游", "《2001 太空漫游》"), ("哈尔9000", "《2001 太空漫游》HAL 9000"),
    ("i'm sorry, dave", "《2001 太空漫游》台词"), ("i'm afraid i can't do that", "《2001 太空漫游》台词"),
    ("open the pod bay doors", "《2001 太空漫游》台词"),
    # 《黑客帝国》
    ("the matrix", "《黑客帝国》"), ("morpheus", "《黑客帝国》墨菲斯"),
    ("agent smith", "《黑客帝国》史密斯"), ("黑客帝国", "《黑客帝国》"), ("黑帝国", "《黑客帝国》"),
    ("红色药丸", "《黑客帝国》"), ("子弹时间", "《黑客帝国》"),
    # 《银翼杀手》/《攻壳机动队》/《阿基拉》
    ("blade runner", "《银翼杀手》"), ("银翼杀手", "《银翼杀手》"), ("deckard", "《银翼杀手》戴克"),
    ("replicant", "《银翼杀手》复制人"), ("tyrell", "《银翼杀手》泰瑞公司"),
    ("ghost in the shell", "《攻壳机动队》"), ("攻壳机动队", "《攻壳机动队》"),
    ("akira", "《阿基拉》"), ("阿基拉", "《阿基拉》"),
    # 科幻/灾难片
    ("terminator", "《终结者》"), ("终结者", "《终结者》"), ("i'll be back", "《终结者》台词"),
    ("hasta la vista", "《终结者》台词"), ("jurassic park", "《侏罗纪公园》"),
    ("侏罗纪公园", "《侏罗纪公园》"), ("godzilla", "《哥斯拉》"), ("哥斯拉", "《哥斯拉》"),
    ("star trek", "《星际迷航》"), ("星际迷航", "《星际迷航》"), ("spock", "《星际迷航》史波克"),
    ("transformers", "《变形金刚》"), ("变形金刚", "《变形金刚》"),
    ("cyberpunk 2077", "《赛博朋克 2077》"), ("流浪地球", "《流浪地球》"),
    ("the wandering earth", "《流浪地球》"), ("西部世界", "《西部世界》"), ("westworld", "《西部世界》"),
    ("怪奇物语", "《怪奇物语》"), ("stranger things", "《怪奇物语》"),
    # 奇幻/魔幻
    ("harry potter", "《哈利·波特》"), ("hogwarts", "《哈利·波特》霍格沃茨"),
    ("voldemort", "《哈利·波特》伏地魔"), ("哈利波特", "《哈利·波特》"),
    ("哈利·波特", "《哈利·波特》"), ("霍格沃茨", "《哈利·波特》"), ("伏地魔", "《哈利·波特》"),
    ("the lord of the rings", "《指环王》"), ("lord of the rings", "《指环王》"),
    ("指环王", "《指环王》"), ("魔戒", "《指环王》"), ("霍比特人", "《指环王》"),
    ("frodo", "《指环王》弗罗多"), ("gandalf", "《指环王》甘道夫"),
    ("game of thrones", "《权力的游戏》"), ("winter is coming", "《权力的游戏》台词"),
    ("权力的游戏", "《权力的游戏》"), ("铁王座", "《权力的游戏》"),
    # 超级英雄（漫威 / DC）
    ("avengers", "《复仇者联盟》"), ("the avengers", "《复仇者联盟》"), ("复仇者联盟", "《复仇者联盟》"),
    ("iron man", "《钢铁侠》"), ("钢铁侠", "《钢铁侠》"),
    ("spider-man", "《蜘蛛侠》"), ("spiderman", "《蜘蛛侠》"), ("蜘蛛侠", "《蜘蛛侠》"),
    ("captain america", "《美国队长》"), ("美国队长", "《美国队长》"),
    ("thanos", "《复仇者联盟》灭霸"), ("灭霸", "《复仇者联盟》灭霸"), ("hulk", "《绿巨人》"),
    ("绿巨人", "《绿巨人》"), ("batman", "《蝙蝠侠》"), ("蝙蝠侠", "《蝙蝠侠》"),
    ("the dark knight", "《蝙蝠侠：黑暗骑士》"), ("why so serious", "《蝙蝠侠》台词"),
    ("superman", "《超人》"), ("wonder woman", "《神奇女侠》"), ("神奇女侠", "《神奇女侠》"),
    ("x-men", "《X 战警》"), ("wolverine", "《X 战警》金刚狼"), ("金刚狼", "《X 战警》金刚狼"),
    ("marvel", "漫威"), ("漫威", "漫威"), ("disney", "迪士尼"), ("迪士尼", "迪士尼"),
    ("disneyland", "迪士尼"), ("pixar", "皮克斯"), ("皮克斯", "皮克斯"),
    ("ghibli", "吉卜力"), ("吉卜力", "吉卜力"),
    # 动画 / 游戏 IP
    ("mickey mouse", "迪士尼米老鼠"), ("米老鼠", "迪士尼米老鼠"), ("唐老鸭", "迪士尼唐老鸭"),
    ("hello kitty", "三丽鸥 Hello Kitty"), ("super mario", "《超级马里奥》"),
    ("超级马里奥", "《超级马里奥》"), ("马里奥", "《超级马里奥》"),
    ("sonic the hedgehog", "《刺猬索尼克》"), ("刺猬索尼克", "《刺猬索尼克》"),
    ("spongebob", "《海绵宝宝》"), ("海绵宝宝", "《海绵宝宝》"),
    ("tom and jerry", "《猫和老鼠》"), ("猫和老鼠", "《猫和老鼠》"),
    ("the simpsons", "《辛普森一家》"), ("辛普森一家", "《辛普森一家》"),
    ("kung fu panda", "《功夫熊猫》"), ("功夫熊猫", "《功夫熊猫》"),
    ("shrek", "《怪物史莱克》"), ("史莱克", "《怪物史莱克》"),
    ("冰雪奇缘", "《冰雪奇缘》"), ("玩具总动员", "《玩具总动员》"),
    ("to infinity and beyond", "《玩具总动员》台词"), ("小黄人", "《神偷奶爸》小黄人"),
    ("spirited away", "《千与千寻》"), ("千与千寻", "《千与千寻》"),
    ("totoro", "《龙猫》"), ("龙猫", "《龙猫》"), ("gundam", "《机动战士高达》"),
    ("机动战士高达", "《机动战士高达》"), ("新世纪福音战士", "《新世纪福音战士》"),
    ("doraemon", "《哆啦A梦》"), ("哆啦a梦", "《哆啦A梦》"), ("机器猫", "《哆啦A梦》"),
    ("pokemon", "《宝可梦》"), ("pikachu", "《宝可梦》皮卡丘"), ("皮卡丘", "《宝可梦》皮卡丘"),
    ("宝可梦", "《宝可梦》"), ("神奇宝贝", "《宝可梦》"),
    ("naruto", "《火影忍者》"), ("火影忍者", "《火影忍者》"), ("鸣人", "《火影忍者》"),
    ("one piece", "《海贼王》"), ("海贼王", "《海贼王》"), ("路飞", "《海贼王》"),
    ("dragon ball", "《龙珠》"), ("龙珠", "《龙珠》"),
    ("ultraman", "《奥特曼》"), ("奥特曼", "《奥特曼》"), ("saint seiya", "《圣斗士星矢》"),
    ("圣斗士星矢", "《圣斗士星矢》"), ("minecraft", "《我的世界》"), ("tetris", "《俄罗斯方块》"),
    ("俄罗斯方块", "《俄罗斯方块》"), ("pac-man", "《吃豆人》"), ("吃豆人", "《吃豆人》"),
    ("warcraft", "《魔兽世界》"), ("魔兽世界", "《魔兽世界》"), ("nintendo", "任天堂"),
    ("任天堂", "任天堂"),
    # 经典片名 / 台词特征词
    ("titanic 1997", "《泰坦尼克号》"), ("泰坦尼克号", "《泰坦尼克号》"),
    ("盗梦空间", "《盗梦空间》"), ("james bond", "007 系列"), ("007", "007 系列"),
    ("詹姆斯·邦德", "007 系列"), ("here's johnny", "《闪灵》台词"),
    ("you're gonna need a bigger boat", "《大白鲨》台词"),
    ("forrest gump", "《阿甘正传》"), ("阿甘正传", "《阿甘正传》"),
    ("life is like a box of chocolates", "《阿甘正传》台词"),
    ("the godfather", "《教父》"), ("教父", "《教父》"),
    ("the truth is out there", "《X 档案》"), ("x-files", "《X 档案》"),
    ("houston, we have a problem", "《阿波罗 13 号》台词"),
)

# 弱命中（歧义词）→ **warning**：既是 IP 名词、也是常见普通词（Hal 是人名、2001 是年份、
# minions 泛指喽啰），报 error 会误伤正常剧本，所以降级成"请确认一下"的告警。
IP_WEAK_TERMS = (
    ("hal", "《2001 太空漫游》HAL 9000（Hal 也是常见人名, 若指人名可忽略）"),
    ("2001", "《2001 太空漫游》（2001 也常指年份, 若指年份可忽略）"),
    ("mario", "《超级马里奥》（Mario 也是常见人名, 若指人名可忽略）"),
    ("minions", "《神偷奶爸》小黄人（minions 也常泛指喽啰, 若泛指可忽略）"),
    ("titanic", "《泰坦尼克号》（titanic 也常作形容词「巨大的」, 若泛指可忽略）"),
)


def _term_pattern(term: str):
    """词条 → 正则：ASCII 词条按整词匹配（star wars 不该命中 starwarrior），中文词条子串匹配。"""
    if term.isascii():
        return re.compile(r'(?<![0-9a-z])' + re.escape(term) + r'(?![0-9a-z])', re.I)
    return re.compile(re.escape(term))


_IP_STRONG_RE = tuple((_term_pattern(t), t, owner) for t, owner in IP_TERMS)
_IP_WEAK_RE = tuple((_term_pattern(t), t, owner) for t, owner in IP_WEAK_TERMS)


def _report(err: list, warn: list) -> dict:
    """统一出口：error 存在即 ok=False（判据见模块 docstring）。"""
    return {
        "errors": err,
        "warnings": warn,
        "summary": "LINT_SUMMARY: errors=%d warnings=%d" % (len(err), len(warn)),
        "ok": not err,
    }


def _as_int(val, default: int) -> int:
    """宽松取整（访客 JSON 不可信，不能让 int('x') 抛异常把接口打挂）。"""
    try:
        return int(float(val))
    except (TypeError, ValueError):
        return default


def _as_list(val) -> list:
    """cast 之类的字段 → list（缺失/None → []；单个字符串 → 单元素列表）。"""
    if not val:
        return []
    if isinstance(val, str):
        return [val]
    if isinstance(val, (list, tuple)):
        return list(val)
    return []


def _flat_text(val) -> str:
    """任意 JSON 值 → 一段可扫文本（dict/list 递归拼接，None → ''）。"""
    if val is None:
        return ''
    if isinstance(val, str):
        return val
    if isinstance(val, dict):
        return ' '.join(_flat_text(v) for v in val.values())
    if isinstance(val, (list, tuple, set)):
        return ' '.join(_flat_text(v) for v in val)
    return str(val)


def _iter_lines(lines) -> list:
    """lines → [(str 索引, 行对象), ...]（索引统一转字符串，避免 int/str 键语义漂移）。"""
    if not isinstance(lines, dict):
        return []
    return [(str(k), v if isinstance(v, dict) else {}) for k, v in lines.items()]


def _story_texts(story: dict) -> list:
    """收集参与合规扫描的全部文本 → [(位置标签, 文本), ...]（标题/风格/角色卡/提示词/台词）。"""
    out = []

    def _add(label: str, val) -> None:
        s = _flat_text(val).strip()
        if s:
            out.append((label, s))

    for key in ('title', 'style', 'logline', 'synopsis', 'idea', 'brief', 'prompt'):
        _add('story.%s' % key, story.get(key))
    chars = story.get('characters')
    if isinstance(chars, dict):
        for name, desc in chars.items():
            _add('characters[%s]' % name, desc)
    for i, seg in enumerate(story.get('segments') or []):
        if not isinstance(seg, dict):
            continue
        for key in ('prompt', 'negative', 'negative_prompt'):
            _add('seg%d.%s' % (i, key), seg.get(key))
    for k, line in _iter_lines(story.get('lines')):
        _add('lines[%s].text' % k, line.get('text'))
    return out


def _match_terms(text: str, table: tuple, claimed: list) -> tuple:
    """在一段文本里跑词表 → (命中 [(start, end, 词条, 归属)], 占用区间)。

    同一处命中多个词条时（darth vader 同时命中 darth）只留最长的那个；
    claimed 是上一轮已占用的区间（强词表先跑，弱词表不再重复报同一处）。
    """
    hits = []
    for pat, term, owner in table:
        for m in pat.finditer(text):
            hits.append((m.start(), m.end(), term, owner))
    hits.sort(key=lambda h: (h[0], -(h[1] - h[0])))
    spans, kept = list(claimed), []
    for h in hits:
        s, e = h[0], h[1]
        if any(not (e <= cs or s >= ce) for cs, ce in spans):
            continue
        spans.append((s, e))
        kept.append(h)
    return kept, spans


def _scan_ip(story: dict) -> tuple:
    """扫全剧文本 → (强命中, 弱命中)；每个元素是 (词条, 归属, [位置标签, ...])。"""
    strong, weak, group_s, group_w = [], [], {}, {}

    for label, text in _story_texts(story):
        s_hits, spans = _match_terms(text, _IP_STRONG_RE, [])
        w_hits, _ = _match_terms(text, _IP_WEAK_RE, spans)
        for item, bucket in ((s_hits, (strong, group_s)), (w_hits, (weak, group_w))):
            for _s, _e, term, owner in item:
                bucket[0].append(term)
                got = bucket[1].setdefault(term, (owner, []))
                if label not in got[1]:
                    got[1].append(label)

    def _ordered(seq, grouped):
        seen, out = set(), []
        for term in seq:
            if term in seen:
                continue
            seen.add(term)
            owner, labels = grouped[term]
            out.append((term, owner, labels))
        return out

    return _ordered(strong, group_s), _ordered(weak, group_w)


# 声明"参考图/素材"的字段名（story 级 + 段级）——只判断有没有声明，不去读文件
_ASSET_KEYS = ('assets', 'refs', 'references', 'reference_images', 'ref_images',
               'materials', 'images', 'source_images', 'ref_video', 'ref_videos')
_SEG_ASSET_KEYS = ('assets', 'ref', 'refs', 'ref_image', 'reference_image', 'reference_images',
                   'image', 'images', 'init_image', 'first_frame', 'ref_video')


def _declared_assets(story: dict) -> list:
    """剧本里声明的参考图/素材 → ['story.assets[2]', 'seg0.ref_image', ...]（位置标签）。"""
    out = []

    def _collect(label: str, val) -> None:
        if isinstance(val, dict):
            val = [k for k, v in val.items() if v]
        if isinstance(val, (list, tuple)):
            n = len(val)
        elif isinstance(val, str):
            n = 1 if val.strip() else 0
        else:
            n = 0
        if n:
            out.append('%s(%d)' % (label, n) if n > 1 else label)

    for key in _ASSET_KEYS:
        _collect('story.%s' % key, story.get(key))
    for i, seg in enumerate(story.get('segments') or []):
        if not isinstance(seg, dict):
            continue
        for key in _SEG_ASSET_KEYS:
            _collect('seg%d.%s' % (i, key), seg.get(key))
    return out


def lint_story(story: dict) -> dict:
    """剧本静态预检（0 成本闸门）→ {"errors": [...], "warnings": [...], "summary": ..., "ok": bool}。

    errors / warnings 都是 '位置: 说明' 形式的字符串（位置如 story / seg0 / lines[1]），
    可以直接逐条显示给访客，也可以整段丢回给 agent 让它改稿。
    """
    err: list = []
    warn: list = []

    if not isinstance(story, dict):
        err.append('story: 剧本必须是 JSON 对象（dict）')
        return _report(err, warn)

    if not _flat_text(story.get('title')).strip():
        err.append('story: 缺 title')
    segs = story.get('segments') or []
    has_segs = isinstance(segs, list) and bool(segs)
    if not has_segs:
        err.append('story: segments 必须是非空数组')
        segs = []
    chars = story.get('characters') or {}
    if not chars:
        warn.append('story: 没有 characters 角色卡 → 跨镜头人物形象容易漂')
    base_sec = max(1, _as_int(story.get('seconds') or BASE_SECONDS, BASE_SECONDS))
    lines = story.get('lines') or {}
    line_keys = {k for k, _ in _iter_lines(lines)}
    style = _flat_text(story.get('style'))

    # ── 分镜与提示词（以下 1)~4) 全部搬自 runs/h3/story_lint.lint） ─────────────
    if has_segs:
        for i, seg in enumerate(segs):
            seg = seg if isinstance(seg, dict) else {}
            p = _flat_text(seg.get('prompt'))
            if not p.strip():
                err.append('seg%d: prompt 为空' % i)
            # 1) 引号 = 模型画字幕的触发开关（实测）
            if _QUOTE_RE.search(p):
                err.append('seg%d: prompt 里出现引号 → 模型会把这句话画成画面字幕'
                           '（字幕由后期加, 必须去掉引号）' % i)
            # 2) cast 必须是角色卡里的名字（否则人物形象卡注入失败, 脸会漂）
            for c in _as_list(seg.get('cast')):
                if str(c) not in chars:
                    err.append('seg%d: cast 里的 %r 不在 characters 中' % (i, c))
            # 3) 单镜头单动作（粗判：then/然后 ≥3 说明需要拆段）
            if len(_ACTION_RE.findall(p)) >= 3:
                warn.append('seg%d: 一个镜头里动作太多（then/然后 ≥3）→ 建议拆段' % i)
            if len(p) > PROMPT_MAX_CHARS:
                warn.append('seg%d: prompt 过长（%d 字符）→ 模型容易漏动作' % (i, len(p)))
            # 3.5) 中文指令文本会被画进画面（实测：前缀"无抗锯齿失真"被渲染成乱码叠字）
            cjk = _CJK_RE.findall(p)
            wants_text = bool(_WANT_TEXT_RE.search(p))
            if cjk and not wants_text:
                warn.append('seg%d: prompt 里有中文文本 %s —— 模型会把中文指令文本直接画进画面，'
                            '除"确实要出现在画面上的字"外请一律用英文' % (i, '/'.join(cjk[:3])))
            # 3.6) 有角色、没台词 → 模型可能自己让人物说话，剔掉乱语音轨后成片"有口型没声音"
            #      5.6) 新增豁免：prompt 里已显式声明"本镜不说话"就不必再报（静默是设计而非疏漏）
            if (str(i) not in line_keys and _as_list(seg.get('cast'))
                    and not _SILENCE_RE.search(p)):
                warn.append('seg%d: 有角色、没有台词 —— 模型可能自己让人物说话，成片会出现"唇动无声"；'
                            '建议该镜改为无人定场、给它一句台词，或在 prompt 里显式写 '
                            '"the character stays silent here: mouth closed, no speech"（推荐）' % i)
            # 4) style 与 prompt 自相矛盾：本镜头要画面文字，整体却禁字
            if wants_text and _BAN_TEXT_RE.search(style):
                warn.append('seg%d: 本镜头要画面文字，但 style 里禁字 → 自相矛盾, 二选一' % i)

        # ── 台词（原 story_lint 的 lines 段，编号沿用原注释） ──────────────────
        for k, line in _iter_lines(lines):
            idx = int(k) if k.isdigit() else -1
            if idx < 0 or idx >= len(segs):
                err.append('lines[%s]: 段索引越界（共 %d 段）' % (k, len(segs)))
                continue
            text = _flat_text(line.get('text')).strip()
            if not text:
                err.append('lines[%s]: text 为空' % k)
                continue
            # 4) 说话人（本镜头只有一个角色时可以省略 speaker）
            seg = segs[idx] if isinstance(segs[idx], dict) else {}
            cast = _as_list(seg.get('cast'))
            if not _flat_text(line.get('speaker')).strip() and len(cast) != 1:
                err.append('lines[%s]: 没写 speaker 且本镜头有 %d 个角色 → 必须指名谁在说'
                           % (k, len(cast)))
            # 5) 时长匹配（字数 → 约需秒数；不够就告警，生成时会自动抬段长）
            need = max(base_sec, int(len(text) * SEC_PER_CHAR) + 1)
            seg_sec = _as_int(seg.get('seconds') or base_sec, base_sec)
            if seg_sec < need:
                warn.append('lines[%s]: 台词 %d 字约需 %ds，本段只有 %ds（生成时会自动抬到 %ds）'
                            % (k, len(text), need, seg_sec, need))

    # ── 5) 合规：版权/IP 词表（新增；命中即 error：不改就是平台风险） ────────────
    strong, weak = _scan_ip(story)
    for term, owner, labels in strong[:MAX_IP_REPORTS]:
        err.append('%s: 命中已知影视 IP「%s」(%s) → 这是受版权保护的专有名词，'
                   '请改写为原创设定（换角色名/换标志性道具/换台词），不要复用其角色与世界观'
                   % ('/'.join(labels[:3]), owner, term))
    if len(strong) > MAX_IP_REPORTS:
        err.append('story: 另有 %d 处 IP 命中未逐条列出（剧本疑似整体照搬, 建议重写）'
                   % (len(strong) - MAX_IP_REPORTS))
    for term, owner, labels in weak[:MAX_IP_REPORTS]:
        warn.append('%s: 疑似 IP 名词 %r（%s）→ 若确为原创/普通用词可忽略，'
                    '否则请改写为原创设定' % ('/'.join(labels[:3]), term, owner))

    # ── 6) 合规：素材授权（新增；缺授权标记只告警：能拍，但来源要访客自己确认） ──
    assets = _declared_assets(story)
    if assets and not story.get('assets_licensed'):
        warn.append('assets: 声明了 %d 项参考素材（%s）但没有授权标记 assets_licensed=true → '
                    '素材来源/授权未确认，请只用自有或已授权素材（或删掉素材改纯文生视频）'
                    % (len(assets), ', '.join(assets[:5])))

    return _report(err, warn)


def lint(story: dict) -> tuple:
    """兼容壳：对齐 runs/h3/story_lint.lint 的 (errors, warnings) 元组返回，方便老调用点。"""
    rep = lint_story(story)
    return rep["errors"], rep["warnings"]
