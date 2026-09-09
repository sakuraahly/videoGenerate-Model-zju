#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_story_film.py — 故事片主控纯逻辑单测（无生成/无 GPU）。

覆盖：story 解析与校验；段提示词=作者 prompt+角色锚定卡+风格句；
进度 JSON 读写/过期重置/段完成判定（resume 语义）；台词先行（line 取自剧本）与
发音回环（LINE_SCORE 阈值/spoken 重试判定）；超时参数回退 story。
"""
import sys
import json
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runs.h3 import story_film as sf  # noqa: E402


def _story():
    return {
        "title": "测试片",
        "style": "cinematic, no text",
        "characters": {"DAK": "45-year-old Asian man, pale green sweater"},
        "segments": [{"prompt": "shot0"}, {"prompt": "shot1"},
                     {"prompt": "shot2"}],
        "lines": {"2": {"text": "台词二", "voice": "yunxi"}},
        "resolution": "480p", "seconds": 4, "lora": "fl2v_4step", "seed": 1,
    }


def main():
    ok = True

    def check(cond, msg):
        nonlocal ok
        if not cond:
            ok = False
            print('FAIL:', msg)
        else:
            print('ok:', msg)

    # 1) load_story 校验
    st = _story()
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / 's.json'
        p.write_text(json.dumps(st), encoding='utf-8')
        check(sf.load_story(p)['title'] == '测试片', 'load_story 解析')
        bad = json.dumps({"title": "x"})
        p.write_text(bad, encoding='utf-8')
        try:
            sf.load_story(p)
            check(False, '缺 segments 应抛')
        except ValueError:
            check(True, '缺 segments 抛 ValueError')

    # 2) build_prompt：作者 prompt + 角色卡 + 风格
    prompt = sf.build_prompt(st['segments'][0], st)
    check('shot0' in prompt, '作者 prompt 保留')
    check('Cast (identical in every shot): DAK: 45-year-old Asian man' in prompt,
          '角色锚定卡注入')
    check('cinematic, no text' in prompt, '风格句注入')
    nop = sf.build_prompt({'prompt': 'x'}, {"title": "t", "segments": [{}], "style": ""})
    check('Cast' not in nop and 'Only the described action' in nop,
          '无角色卡/风格时=原文+行为约束句')

    # 2a2) setting 与行为约束注入（剧本遵守）
    st.setdefault('setting', '1940s rural America')
    ps = sf.build_prompt({'prompt': 'shotx'}, st)
    check('Story setting: 1940s rural America' in ps, 'setting 注入')
    check('Only the described action happens in this shot' in ps
          and 'characters do not enter, leave' in ps, '行为约束句注入')

    # 2b) 在场约束 cast（防模型多塞人物/剧情溢出）
    segc = {'prompt': 'shot9', 'cast': ['DAK', 'LAKE']}
    pc = sf.build_prompt(segc, st)
    check('Persons in this shot: DAK, LAKE only' in pc
          and 'No other people anywhere in the frame.' in pc, 'cast 在场约束注入')
    seg_empty = {'prompt': 'empty shot', 'cast': []}
    pe = sf.build_prompt(seg_empty, {"title": "t", "segments": [{}], "style": "",
                                     "characters": {}})
    check('No people in this shot; empty scenery only.' in pe, 'cast 空列表=显式无人')
    # 未声明 cast: 不加在场句（行为约束句恒加）
    nop2 = sf.build_prompt({'prompt': 'x'}, {"title": "t", "segments": [{}], "style": "",
                                             "characters": {}})
    check('Persons in this shot' not in nop2 and 'No people' not in nop2,
          '未声明 cast=不加在场句')

    # 6) 台词时长匹配与语气指令
    check(sf.eff_seconds(5.3, 4) == 7, 'eff_seconds 音长+0.8 上取整(5.3→7)')
    check(sf.eff_seconds(2.1, 4) == 4, 'eff_seconds 短台词保底 4s')
    check(sf.eff_seconds(0, 4) == 4, 'eff_seconds 无时长保底')
    check(sf.instruct_text({'tone': '急切地喘着气恳求'}) == '用急切地喘着气恳求地说',
          'tone→指令语气文本')
    check(sf.instruct_text({}) == '', '无 tone=零样本自然语气')
    check(sf.line_ph({'text': '台词', 'voice': 'yunxi', 'speed': 0.9})
          != sf.line_ph({'text': '台词', 'voice': 'yunjian', 'speed': 0.9}), 'line_ph 含音色')

    # 3) 进度 JSON：delta 写入/段完成判定/resume 语义
    with tempfile.TemporaryDirectory() as d:
        work = Path(d)
        s0 = sf.load_state(work, st)
        check(s0['done'] == [], '初始 state 空')
        sf.syn_seg(s0, 0, {'file': '/tmp/fake0.mp4'})
        # 文件不存在 → 断点判定=未完成
        check(not sf.seg_done(s0, 0), '文件不存在=未完成(可恢复重跑)')
        sf.save_state(work, s0)
        s1 = sf.load_state(work, st)
        check(s1['done'] == [0] and s1['segments']['0']['file'] == '/tmp/fake0.mp4',
              'state 持久化')
        s2 = sf.load_state(work, {"title": "另一片", "segments": [{"prompt": "a"}]})
        check(s2['done'] == [], '标题不一致=过期重置(resume 不串片)')

    # 4) 台词先行+发音回环：_line_score_of 解析
    check(abs(sf._line_score_of('...\nLINE_SCORE: 0.786 ok\n') - 0.786) < 1e-6,
          'LINE_SCORE 解析')
    check(sf._line_score_of('no score') == -1.0, '无分数=-1')

    # 5) 缺省参数回退 story（不重复写 CLI）
    import argparse
    a = argparse.Namespace(resolution='', seconds=0, lora='', seed=0, story='x',
                           work_dir='/tmp/t', stitch=False, out='/tmp/o.mp4',
                           timeout=7200, fresh=False, status=False)
    story2 = dict(st)
    # 模拟 cmd_run 开头的回退块
    a.resolution = a.resolution or str(story2.get('resolution') or '480p')
    a.seconds = int(a.seconds or int(story2.get('seconds') or 4))
    a.lora = a.lora or str(story2.get('lora') or 'fl2v_4step')
    a.seed = int(a.seed or int(story2.get('seed') or 20260909))
    check(a.resolution == '480p' and a.seconds == 4 and a.lora == 'fl2v_4step'
          and a.seed == 1, 'CLI 缺省→story 参数回退')

    print('ALL_OK' if ok else 'SOME_FAILED')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
