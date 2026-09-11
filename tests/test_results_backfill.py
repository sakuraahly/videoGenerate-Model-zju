#!/usr/bin/env python3
"""UI 回传兜底回归（2026-09-11）：生成好的任务必须自动回到 7860 结果区。

背景（handoff-2026-09-11 §二.1「UI 反查兜底仍返回 None」）：实测
    latest_final(Path('.'), '20260911_013310_24b9') -> None   （成片实际已生成）
本文件把断链拆成三条，逐条钉住：
  ① job.json.log_file 存的是 **basename**，真实日志在 <repo>/logs/；原实现拼成
     task_dir/<name> → 该文件恒不存在 → 任务日志里的 LOCAL_OUTPUT 永远读不到
     （原代码只扫「最近 20 个 run_*.log」，任务自己的日志一旦被挤出窗口就彻底找不到）；
  ② 会话产物目录为空、反查命中时，session_videos() 原实现用「f in vids」判定 →
     反查到的（会话目录之外的）成品被整个丢掉 → 结果区恒「暂无结果」（最后一公里）；
  ③ UI 只在 send / 加载会话时刷新 → 任务在本轮结束后完成就永远停在「暂无结果」
     （现加定时轮询 _poll_results + adopt_outputs 回写）。
另钉两条安全红线：job.json.videos 是**输入**参考素材（不得当成品回传）、
跨任务扫日志必须先用 prompt_id 过滤（不得把别人的产物认成本会话成品）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runs.h3 import session_outputs as so  # noqa: E402

CID = '20260911_013310_24b9'
PID = 'ac88b2cb-1111-4222-8333-444455556666'
OTHER_PID = 'bbbbbbbb-2222-4333-8444-555566667777'


def _build(tmp_path, *, cid=CID, pid=PID, log_name=None, output_file=None,
           videos=None, log_lines=None, product='video_85.mp4',
           task='h3_20260911_013000_123'):
    """搭一个「任务已完成、产物只在 outputs/」的真实形态仓库。返回 (任务目录, 产物)。"""
    logs = tmp_path / 'logs'
    chats = logs / 'agent_chats'
    chats.mkdir(parents=True, exist_ok=True)
    (chats / (cid + '.jsonl')).write_text(
        json.dumps({'role': 'assistant', 'content': 'TASK_SUBMITTED: ' + pid},
                   ensure_ascii=False) + '\n', encoding='utf-8')
    task_dir = tmp_path / 'workflows' / task
    task_dir.mkdir(parents=True, exist_ok=True)
    job = {'schema': 1, 'task_dir': task_dir.name, 'state': 'completed', 'prompt_id': pid}
    if log_name:
        job['log_file'] = log_name
    if output_file:
        job['output_file'] = output_file
    if videos is not None:
        job['videos'] = list(videos)
    (task_dir / 'job.json').write_text(json.dumps(job, ensure_ascii=False), encoding='utf-8')
    outdir = tmp_path / 'outputs'
    outdir.mkdir(exist_ok=True)
    prod = None
    if product:
        prod = outdir / product
        prod.write_bytes(b'mp4')
    if log_name and log_lines is not None:
        (logs / log_name).write_text('\n'.join(log_lines) + '\n', encoding='utf-8')
    so._reverse_cache.clear()
    return task_dir, prod


def _crowd_logs(tmp_path, n=25):
    """在任务日志之后再造 n 个更新的 run_*.log（把任务日志挤出「最近 20」窗口）。"""
    import os
    import time
    logs = tmp_path / 'logs'
    for i in range(n):
        p = logs / ('run_20260911_1%03d00_%03d.log' % (i, i))
        p.write_text('py: 无关日志\n', encoding='utf-8')
        os.utime(p, (time.time() + i + 1, time.time() + i + 1))


# ---------------------------------------------------------------- ① 日志定位
def test_reverse_lookup_finds_product_when_task_log_left_recent_window(tmp_path):
    """handoff 原样复现：任务日志被更新的 20 个 run_*.log 挤出窗口 → 仍必须命中。"""
    _task, prod = _build(tmp_path, log_name='run_20260911_013000_123.log',
                         log_lines=['py: LOCAL_OUTPUT: outputs/video_85.mp4'])
    _crowd_logs(tmp_path)

    got = so.latest_final(tmp_path, CID)
    assert got is not None, '反查兜底必须命中任务自己的日志（<repo>/logs/<log_file>）'
    assert Path(got).is_file()
    assert Path(got).name == prod.name


def test_reverse_lookup_uses_output_file_from_job_record(tmp_path):
    """任务完成时 job.json 记的 output_file 是权威产物名（无需读日志）。"""
    _task, prod = _build(tmp_path, output_file='video_85.mp4')
    got = so.latest_final(tmp_path, CID)
    assert got is not None and Path(got).name == prod.name


def test_local_output_line_with_spaces_is_parsed(tmp_path):
    """产物名含空格/中文时也要解析（原来的非空白正则只取到空格前一段）。"""
    _task, prod = _build(tmp_path, log_name='run_x.log', product='video_85_终版 带字幕.mp4',
                         log_lines=['py: LOCAL_OUTPUT: outputs/video_85_终版 带字幕.mp4'])
    got = so.latest_final(tmp_path, CID)
    assert got is not None and Path(got).name == prod.name


def test_missing_product_returns_none(tmp_path):
    """任务真没产物（日志里也没有 LOCAL_OUTPUT）→ 必须 None，不许猜一个文件。"""
    _build(tmp_path, product=None, log_name='run_x.log', log_lines=['py: start'])
    assert so.latest_final(tmp_path, CID) is None


# ---------------------------------------------------------------- ② 安全红线
def test_input_reference_videos_are_not_returned_as_product(tmp_path):
    """job.json.videos 是**输入**素材（--videos/resume 恢复用），绝不可当成品回传。"""
    _build(tmp_path, videos=['ref_input.mp4'], product='ref_input.mp4')
    assert so.latest_final(tmp_path, CID) is None


def test_other_tasks_product_is_not_adopted(tmp_path):
    """LOCAL_OUTPUT 行不带任务号：跨任务扫日志必须先按 prompt_id 过滤，否则会串片。"""
    _build(tmp_path, pid=PID, product='别人的片.mp4',
           log_name='run_other.log', log_lines=['py: LOCAL_OUTPUT: outputs/别人的片.mp4'],
           task='h3_20260911_020000_000')
    jobf = tmp_path / 'workflows' / 'h3_20260911_020000_000' / 'job.json'
    job = json.loads(jobf.read_text(encoding='utf-8'))
    job['prompt_id'] = OTHER_PID
    job.pop('log_file', None)          # 无 log_file → 只能靠扫日志（必须被 pid 过滤挡住）
    jobf.write_text(json.dumps(job, ensure_ascii=False), encoding='utf-8')
    so._reverse_cache.clear()
    assert so.latest_final(tmp_path, CID) is None


# ---------------------------------------------------------------- ③ 最后一公里
def test_session_videos_includes_reverse_product_outside_session_dir(tmp_path):
    """会话目录为空但反查命中 → 结果区必须有东西（原实现「f in vids」把结果丢了）。"""
    _task, prod = _build(tmp_path, output_file='video_85.mp4')
    assert so.session_out_dir(tmp_path, CID).is_dir() is False
    vids = so.session_videos(tmp_path, CID)
    assert [Path(p).name for p in vids] == [prod.name]


def test_session_files_includes_reverse_product_outside_session_dir(tmp_path):
    """下载列表同理：否则「查得到却下载不了」。"""
    _task, prod = _build(tmp_path, output_file='video_85.mp4')
    assert [Path(p).name for p in so.session_files(tmp_path, CID)] == [prod.name]


def test_adopt_outputs_writes_product_back_into_session_dir(tmp_path):
    """Gradio 只服务 allowed_paths 内的文件 → 反查命中必须回写会话目录并打标。"""
    _task, _prod = _build(tmp_path, output_file='video_85.mp4', log_name='run_x.log',
                          log_lines=['py: LOCAL_OUTPUT: outputs/video_85.mp4'])
    adopted = so.adopt_outputs(tmp_path, CID)
    assert adopted is not None
    assert so.session_out_dir(tmp_path, CID) in Path(adopted).parents   # 已进会话目录
    assert Path(adopted).is_file()
    # 回写后 _final.json 打标 → 下次刷新走最快路径（不再反查）
    assert so.latest_final(tmp_path, CID) == Path(adopted)
    # 内部标记文件不进给用户的下载列表
    assert '_final.json' not in [p.name for p in so.session_files(tmp_path, CID)]
    # 幂等：再调一次不重复复制、不报错
    assert so.adopt_outputs(tmp_path, CID) == Path(adopted)


def test_reverse_cache_does_not_pin_a_deleted_file(tmp_path):
    """反查结果有 TTL 记忆（UI 每 5s 轮询）；文件被清掉后必须能重新扫描。"""
    _task, prod = _build(tmp_path, output_file='video_85.mp4')
    assert so.latest_final(tmp_path, CID) is not None
    assert (str(tmp_path), CID) in so._reverse_cache
    prod.unlink()
    assert so.latest_final(tmp_path, CID) is None     # 缓存条目失效 → 重扫 → 确实没有了


# ---------------------------------------------------------------- ④ UI 结果区
def test_ui_results_update_shows_reverse_product(tmp_path, monkeypatch):
    """UI 结果区（_results_update）必须把反查命中的成片放进预览位 + 下载列表。"""
    __import__('pytest').importorskip('gradio')
    from runs.agent import ui_app

    _build(tmp_path, output_file='video_85.mp4', log_name='run_x.log',
           log_lines=['py: LOCAL_OUTPUT: outputs/video_85.mp4'])
    monkeypatch.setattr(ui_app, 'PROJECT_ROOT', str(tmp_path))
    ui_app._RESULTS_SHOWN.clear()

    video, files = ui_app._results_update(CID)
    assert video.get('value'), '结果区预览位必须给出成片（回传断链时这里是 None）'
    assert Path(video['value']).is_file()
    assert Path(video['value']).parent == so.session_out_dir(tmp_path, CID)  # 已回写到可服务目录
    assert '成品' in video.get('label', '')
    assert [Path(f).name for f in files.get('value') or []] == ['video_85.mp4']


def test_ui_poll_results_is_noop_when_nothing_changed(tmp_path, monkeypatch):
    """定时轮询（自动回传）：值没变就回 no-op，避免每 5 秒重载视频打断播放。"""
    __import__('pytest').importorskip('gradio')
    from runs.agent import ui_app

    _build(tmp_path, output_file='video_85.mp4')
    monkeypatch.setattr(ui_app, 'PROJECT_ROOT', str(tmp_path))
    ui_app._RESULTS_SHOWN.clear()

    first = ui_app._poll_results(CID)
    assert first[0].get('value'), '首次轮询必须把成片拉出来'
    second = ui_app._poll_results(CID)
    assert 'value' not in second[0] and 'value' not in second[1], '无变化应回 no-op'
    # 会话为空（无 cid）时也不能抛异常
    assert ui_app._poll_results('')[0].get('__type__') == 'update'


def test_ui_results_update_empty_state_is_clean(tmp_path, monkeypatch):
    """没有任何产物时给空态标签（不报错、不显示别人的东西）。"""
    __import__('pytest').importorskip('gradio')
    from runs.agent import ui_app

    monkeypatch.setattr(ui_app, 'PROJECT_ROOT', str(tmp_path))
    ui_app._RESULTS_SHOWN.clear()
    video, files = ui_app._results_update('nothing_here')
    assert video.get('value') is None and '暂无结果' in video.get('label', '')
    assert files.get('value') is None and '暂无' in files.get('label', '')


# ---------------------------------------------------------------- ①b 真机口径（2026-09-11 spark 实测）
def test_real_spark_log_format_local_output_and_tts_done(tmp_path):
    """真机日志里**没有** LOCAL_OUTPUT 行（那是子进程 stdout，被调用方吞掉）；
    真正落盘的是 _log_event 的 key=value 行 —— 必须认，且成品 _pp 优先于队列直出。
    """
    _build(tmp_path, output_file='MiniMax_H3_00363_.mp4',   # ComfyUI 侧名，本机不存在
           log_name='run_x.log', product=None)
    out = tmp_path / 'outputs'
    (out / 'video_620.mp4').write_bytes(b'raw')
    (out / 'video_620_pp.mp4').write_bytes(b'final')
    (tmp_path / 'logs' / 'run_x.log').write_text(
        '[2026-09-11 09:35:33] py: local_output file=video_620.mp4 bytes=271461\n'
        '[2026-09-11 09:35:33] py: verify_ok file=video_620.mp4 w=608 h=352\n'
        '[2026-09-11 09:35:54] py: tts_done file=video_620_pp.mp4 voice=zh-CN-XiaoxiaoNeural '
        'speech=1.22s srt=yes merged_encode=1 backend=cosy\n',
        encoding='utf-8')
    so._reverse_cache.clear()
    got = so.latest_final(tmp_path, CID)
    assert got is not None and Path(got).name == 'video_620_pp.mp4', \
        '必须回传配音合并后的成品（video_N_pp.mp4），不是队列直出的 video_N.mp4'


def test_quality_board_pid_mapping_is_used(tmp_path):
    """运行日志丢了时靠 logs/quality.jsonl 的 pid→文件名映射兜底（append-only）。"""
    _build(tmp_path, product=None)
    out = tmp_path / 'outputs'
    (out / 'video_621.mp4').write_bytes(b'raw')
    (out / '别人的.mp4').write_bytes(b'other')
    (tmp_path / 'logs' / 'quality.jsonl').write_text(
        json.dumps({'ts': '2026-09-11 01:36:23', 'prompt_id': PID, 'path': 'video_621.mp4',
                    'width': 608}, ensure_ascii=False) + '\n' +
        json.dumps({'ts': '2026-09-11 01:36:23', 'prompt_id': OTHER_PID, 'path': '别人的.mp4'}) + '\n',
        encoding='utf-8')
    so._reverse_cache.clear()
    got = so.latest_final(tmp_path, CID)
    assert got is not None and Path(got).name == 'video_621.mp4'


def test_final_named_product_wins_even_if_raw_is_newer(tmp_path):
    """重跑会把 raw 写得更新；回传给用户的仍必须是成品命名的那份。"""
    import os
    import time
    _build(tmp_path, product=None, log_name='run_x.log',
           log_lines=['py: local_output file=video_630.mp4',
                      'py: tts_done file=video_630_pp.mp4 voice=x'])
    out = tmp_path / 'outputs'
    fin = out / 'video_630_pp.mp4'
    raw = out / 'video_630.mp4'
    fin.write_bytes(b'final')
    raw.write_bytes(b'raw')
    os.utime(fin, (time.time() - 100, time.time() - 100))   # 成品更旧
    os.utime(raw, (time.time(), time.time()))               # 直出更新
    so._reverse_cache.clear()
    assert Path(so.latest_final(tmp_path, CID)).name == 'video_630_pp.mp4'


# ---------------------------------------------------------------- ⑤ 落盘侧契约（glue）
def test_session_place_requires_cid_env(tmp_path, monkeypatch):
    """契约：h3_submit 只在 VIDEOGEN_SESSION_CID 存在时落会话目录。

    watcher 的 --resume 子进程若没带这个 env，产物只会留在 outputs/，
    页面结果区就"生成好了却回传不到"（2026-09-11 修复的根因之一）。
    """
    import importlib
    if str(ROOT / 'runs') not in sys.path:
        sys.path.insert(0, str(ROOT / 'runs'))
    h3_submit = importlib.import_module('h3_submit')

    src = tmp_path / 'video_85.mp4'
    src.write_bytes(b'mp4')
    monkeypatch.delenv('VIDEOGEN_SESSION_CID', raising=False)
    h3_submit._session_place(tmp_path, src, final=True)
    assert not so.session_out_dir(tmp_path, 'cid_env').exists()      # 无 cid → 不落盘

    monkeypatch.setenv('VIDEOGEN_SESSION_CID', 'cid_env')
    h3_submit._session_place(tmp_path, src, final=True)
    out = so.session_out_dir(tmp_path, 'cid_env')
    assert (out / 'video_85.mp4').is_file()
    so._reverse_cache.clear()
    assert so.latest_final(tmp_path, 'cid_env') == out / 'video_85.mp4'   # 打标成品


def test_watcher_resume_is_gated_by_notify_dedup():
    """glue 守卫：--resume 必须在 P1 去重门**之内**。

    回归背景（2026-09-11 现场）：原实现把 resume 放在去重判断之前 → 每个 15s 轮询周期都
    把同一个已完成任务重下 + 重跑 TTS，5 分钟产出 5 份重复成品（video_620..624_pp.mp4），
    结果区被反复顶掉；且取片带着刚加的 cid 会把重复件也写进会话目录。
    """
    src = (ROOT / 'runs' / 'agent' / 'ui_app.py').read_text(encoding='utf-8')
    i_key = src.index('key = _tw.notify_key(cid, pid, ekey)')
    i_resume = src.index("'--resume'")
    assert i_key < i_resume, '取片（--resume）必须排在去重判断之后，否则会重复下载/重复 TTS'
    assert 'if key in notified:' in src[i_key:i_resume], '去重门内应有已处理即跳过的分支'


def test_watcher_resume_subprocess_carries_session_cid():
    """glue 守卫：ui_app 的 watcher --resume 调用点必须传 VIDEOGEN_SESSION_CID。"""
    src = (ROOT / 'runs' / 'agent' / 'ui_app.py').read_text(encoding='utf-8')
    i = src.index("'--resume'")
    window = src[max(0, i - 400):i + 400]
    assert 'VIDEOGEN_SESSION_CID' in window, (
        'watcher 取片（--resume）必须带上本会话 cid，否则 _session_place 直接返回、'
        '产物不进会话结果区')
