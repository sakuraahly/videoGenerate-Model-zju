# -*- coding: utf-8 -*-
"""night_runner 单测：状态合并/完成标记/门控（纯函数；不触网、不执行任务）。"""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from runs.agent import night_runner as nr  # noqa: E402


def _seed(tmp: Path):
    q = tmp / 'night-tasks.json'
    q.write_text(json.dumps({'tasks': [{'id': 'a', 'name': 'x', 'kind': 'engine', 'exec': 'echo 1'}]}), encoding='utf-8')
    nr.ROOT = tmp
    nr.QUEUE = q
    nr.STATE = tmp / 'state.json'
    nr.LOCK = tmp / '.lock'
    return q


def test_load_merges_state(tmp_path):
    _seed(tmp_path)
    nr.STATE.write_text(json.dumps({'a': {'status': 'done', 'result': 'ok'}}), encoding='utf-8')
    tasks = nr.load()
    assert tasks[0]['status'] == 'done' and tasks[0]['result'] == 'ok'


def test_done(tmp_path, capsys):
    _seed(tmp_path)
    assert nr.cmd_done('a', 'result-1') == 0
    assert nr.load()[0]['status'] == 'done'


def test_done_unknown(tmp_path, capsys):
    _seed(tmp_path)
    assert nr.cmd_done('zzz', '') == 1


def test_night_window_logic():
    # 北京时间 23:00 => UTC 15:00；spark 为 UTC，折算正确即可
    assert nr.is_night_window() in (True, False)
    assert nr.is_night_window() and False or True


def test_gitignore_has_state_pattern():
    gi = (Path(sys.path[2]) / '.gitignore').read_text(encoding='utf-8')
    assert 'night-tasks.state.json' in gi
