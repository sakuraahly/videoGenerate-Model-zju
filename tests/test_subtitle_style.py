# -*- coding: utf-8 -*-
"""字幕样式引擎单测（2026-09-07 定稿）：preset/覆盖/自适应口径。"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'runs'))
from h3 import postprocess as _pp  # noqa: E402


def _style(preset='harmony', font='auto', color='auto', h=352):
    cfg = dict(_pp.SUBTITLE_STYLES.get(preset, _pp.SUBTITLE_STYLES['harmony']))
    if font == 'kai':
        cfg['font'] = 'AR PL UKai CN'
    elif font == 'song':
        cfg['font'] = 'Noto Serif CJK SC'
    elif font == 'sans':
        cfg['font'] = 'Noto Sans CJK SC'
    if color == 'black':
        cfg.update(dict(text='&H00000000', outline='&H00FFFFFF', shadow=None, sh=0))
    fs = max(int(cfg['min']), int(round(h * cfg['ratio'])))
    fs = min(fs, int(cfg['cap']))
    style = ('FontName=' + cfg['font'] + ',FontSize=' + str(fs) + ',PrimaryColour=' + cfg['text']
             + ',OutlineColour=' + cfg['outline'] + ',Alignment=2,WrapStyle=0')
    return style


def test_presets_distinct():
    s1 = _style('harmony')
    s2 = _style('kai')
    s3 = _style('black')
    s4 = _style('classic')
    assert 'Noto Sans CJK SC' in s1 and 'AR PL UKai CN' in s2
    assert '&H00000000' in s3 and '&H00FFFFFF' in s3
    assert s1 != s2 and s2 != s3 and s3 != s4


def test_adaptive_size():
    assert int(round(704 * 0.05)) == 35
    assert _pp.SUBTITLE_STYLES['harmony']['ratio'] == 0.05
    assert _pp.SUBTITLE_STYLES['classic']['ratio'] == 0.07


def test_styles_registry_keys():
    for k in ('harmony', 'kai', 'song', 'black', 'minimal', 'classic'):
        assert k in _pp.SUBTITLE_STYLES


def test_harmony_defaults():
    assert _pp.SUBTITLE_STYLES['harmony']['margin_v'] == 0.10
    assert _pp.SUBTITLE_STYLES['harmony']['min'] == 14
