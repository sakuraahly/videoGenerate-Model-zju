#!/usr/bin/env python3
"""queue_worker — 创空间 ↔ 本机引擎 的"任务队列桥"（本机执行端）。

架构（2026-09-10 用户质问"创空间和本地程序到底什么关系"后的答案）：
  创空间（免费 CPU，只做前端 Agent）  →  写任务到 ModelScope 私有数据集  →
  **本机 worker（本文件）轮询取任务** → 调用本项目真实引擎（talk_one / h3_submit / story_film）→
  产物与状态回写数据集  →  创空间前端轮询读到 → 页面上直接看成片。

为什么用数据集当队列：本机只需**出站**访问（无需公网入站/端口映射），且两端同用一个 token；
数据集=git 仓库，天然带版本与审计。

仓库布局（dataset: <owner>/h3-video-job-queue）：
  jobs/<id>.json         任务（status: queued → running → done|error）
  jobs/<id>/ref.png      可选参考图（创空间上传）
  results/<id>/video.mp4 产物
  results/<id>/meta.json 产物元信息（时长/ASR/日志摘要）

用法（spark；常驻建议 tmux/nohup）：
  python3 runs/bridge/queue_worker.py --once          # 跑一轮
  python3 runs/bridge/queue_worker.py --interval 15   # 常驻轮询
环境变量：MS_TOKEN（必填，写队列用）、MS_QUEUE_DATASET（默认 wumingyong0/h3-video-job-queue）
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
WORK = Path(os.environ.get('H3_QUEUE_DIR', str(Path.home() / 'h3queue')))
DATASET = os.environ.get('MS_QUEUE_DATASET', 'wumingyong0/h3-video-job-queue')
TOKEN = (os.environ.get('MS_TOKEN') or '').strip()


def _log(msg: str) -> None:
    print('[queue] %s %s' % (time.strftime('%H:%M:%S'), msg), flush=True)


REMOTE_URL = 'https://oauth2:%s@www.modelscope.cn/datasets/%s.git' % (TOKEN, DATASET)


def _git(*args, timeout: int = 300):
    return subprocess.run(['git', '-C', str(WORK), *args], capture_output=True,
                          text=True, timeout=timeout)


def _repo():
    """确保队列仓库已克隆且 remote 带 token（ModelScope 数据集仓库=git）。"""
    from modelscope.hub.repository import DatasetRepository
    WORK.parent.mkdir(parents=True, exist_ok=True)
    if not (WORK / '.git').is_dir():
        DatasetRepository(repo_work_dir=str(WORK), dataset_id=DATASET,
                          revision='master', auth_token=TOKEN).clone()
    _git('remote', 'set-url', 'origin', REMOTE_URL)
    return WORK


def _pull(repo=None) -> None:
    r = _git('pull', '--rebase', '--autostash')
    if r.returncode != 0:
        _log('pull 警告: %s' % ((r.stderr or r.stdout or '')[-140:]).replace('\n', ' '))


def _push(repo=None, msg: str = 'update') -> None:
    _git('add', '-A')
    _git('-c', 'user.email=queue@spark', '-c', 'user.name=spark-queue', 'commit', '-m', msg)
    r = _git('push', 'origin', 'HEAD:master', timeout=600)
    if r.returncode != 0:
        _log('push 警告: %s' % ((r.stderr or r.stdout or '')[-160:]).replace('\n', ' '))


def _run(cmd, timeout=3600) -> tuple:
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=str(ROOT))
    return r.returncode, (r.stdout or '') + (r.stderr or '')


def exec_task(task: dict, task_dir: Path, out_dir: Path) -> dict:
    """执行一个任务；返回 {'ok', 'video', 'meta'}。"""
    kind = task.get('kind', 't2v')
    res = {'ok': False, 'video': None, 'meta': {}}
    out_dir.mkdir(parents=True, exist_ok=True)
    ref = None
    for cand in ('ref.png', 'ref.jpg', 'ref.jpeg', 'ref.webp'):
        p = task_dir / cand
        if p.is_file():
            ref = p
            break
    if kind == 'talk':
        text = (task.get('text') or '').strip()
        cmd = ['python3', str(ROOT / 'runs' / 'h3' / 'talk_one.py'),
               '--text', text, '--resolution', task.get('resolution', '480p')]
        if ref:
            cmd += ['--ref-image', str(ref)]
        else:
            # 无参考图时，用最近一次生成产物抽帧兜底（或直接报错）
            return {'ok': False, 'video': None,
                    'meta': {'error': '说话镜头需要参考图（chats 上传 ref.png）'}}
        if task.get('no_subtitle', True):
            cmd += ['--no-subtitle']
        if task.get('voice') and task['voice'] != 'h3':
            cmd += ['--audio-source', 'tts', '--voice', task['voice']]
        rc, log = _run(cmd, timeout=int(task.get('timeout') or 3600))
        m = re_search(r'"?(?:FINAL|成品):\s*(\S+\.mp4)', log) or re_search(r'(outputs/\S+_final\.mp4)', log)
        if rc == 0 and m:
            src = Path(m) if Path(m).is_absolute() else ROOT / m
            if src.is_file():
                shutil.copy2(src, out_dir / 'video.mp4')
                res.update(ok=True, video='results/%s/video.mp4' % task.get('id'))
        res['meta'] = {'rc': rc, 'log_tail': log[-600:]}
        return res
    if kind in ('t2v', 'i2v', 'r2v'):
        stage = kind
        cmd = ['python3', str(ROOT / 'runs' / 'h3_submit.py'), '--stage', stage,
               '--prompt', (task.get('prompt') or '')[:1500],
               '--resolution', task.get('resolution', '480p'),
               '--seconds', str(int(task.get('seconds') or 5)), '--force-new']
        if stage != 't2v' and ref:
            cmd += ['--image', str(ref)]
        rc, log = _run(cmd, timeout=int(task.get('timeout') or 3600))
        m = re_search(r'LOCAL_OUTPUT:\s*(outputs/\S+\.mp4)', log)
        if rc == 0 and m:
            src = ROOT / m
            if src.is_file():
                shutil.copy2(src, out_dir / 'video.mp4')
                res.update(ok=True, video='results/%s/video.mp4' % task.get('id'))
        res['meta'] = {'rc': rc, 'log_tail': log[-600:]}
        return res
    if kind == 'answer':
        res.update(ok=True, meta={'text': task.get('text', '')})
        return res
    res['meta'] = {'error': '未知任务类型: %s' % kind}
    return res


def re_search(pat: str, text: str):
    import re
    m = re.search(pat, text or '')
    return m.group(1) if m else None


def one_round(verbose: bool = True) -> int:
    _repo()
    _pull()
    jobs_dir = WORK / 'jobs'
    jobs_dir.mkdir(parents=True, exist_ok=True)
    done = 0
    for jf in sorted(jobs_dir.glob('*.json')):
        try:
            task = json.loads(jf.read_text(encoding='utf-8'))
        except Exception:  # noqa: BLE001
            continue
        if task.get('status') != 'queued':
            continue
        tid = task.get('id') or jf.stem
        _log('取任务 %s kind=%s' % (tid, task.get('kind')))
        task['status'] = 'running'
        task['started_at'] = time.strftime('%Y-%m-%d %H:%M:%S')
        jf.write_text(json.dumps(task, ensure_ascii=False, indent=2), encoding='utf-8')
        _push(msg='claim %s' % tid)
        out_dir = WORK / 'results' / tid
        try:
            res = exec_task(task, jobs_dir / tid, out_dir)
        except Exception as e:  # noqa: BLE001
            res = {'ok': False, 'video': None, 'meta': {'error': str(e)[:400]}}
        task['status'] = 'done' if res['ok'] else 'error'
        task['finished_at'] = time.strftime('%Y-%m-%d %H:%M:%S')
        task['video'] = res.get('video')
        task['engine'] = 'spark-local/H3'
        jf.write_text(json.dumps(task, ensure_ascii=False, indent=2), encoding='utf-8')
        (out_dir / 'meta.json').write_text(
            json.dumps(res.get('meta') or {}, ensure_ascii=False, indent=2), encoding='utf-8')
        _push(msg='result %s -> %s' % (tid, task['status']))
        _log('任务 %s → %s' % (tid, task['status']))
        done += 1
    if verbose and not done:
        _log('无待办任务')
    return done


def main() -> int:
    ap = argparse.ArgumentParser('任务队列 worker（创空间 ↔ 本机引擎）')
    ap.add_argument('--once', action='store_true')
    ap.add_argument('--interval', type=int, default=15)
    ap.add_argument('--status', action='store_true')
    args = ap.parse_args()
    if not TOKEN:
        print('[错误] 需要环境变量 MS_TOKEN', file=sys.stderr)
        return 3
    if args.status:
        _repo()
        _pull()
        js = list((WORK / 'jobs').glob('*.json'))
        print('队列目录: %s（%d 个任务）' % (WORK, len(js)))
        for jf in sorted(js)[-10:]:
            d = json.loads(jf.read_text(encoding='utf-8'))
            print('  %s %-7s %s' % (d.get('id'), d.get('status'), d.get('kind')))
        return 0
    if args.once:
        one_round()
        return 0
    _log('常驻轮询启动（interval=%ds, dataset=%s）' % (args.interval, DATASET))
    while True:
        try:
            one_round()
        except Exception as e:  # noqa: BLE001
            _log('轮询异常: %s' % str(e)[:200])
        time.sleep(max(5, args.interval))


if __name__ == '__main__':
    sys.exit(main())
