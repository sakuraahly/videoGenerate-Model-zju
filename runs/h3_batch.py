#!/usr/bin/env python3
"""h3_batch — 批量提交引擎（多图转场一次性提交 N-1 段 flf2v）。

用法：
  python runs/h3_batch.py submit --stage flf2v --images a.png,b.png,c.png \\
      [--seconds 5] [--resolution 360p] [--prompt "..."] [--dry-run]
  python runs/h3_batch.py status [--wait] [--timeout 600] [--batch <dir>] [--json]
  python runs/h3_batch.py retry --batch <dir> --segments 0,2

submit: 验证图片 → 生成 manifest → 逐段 subprocess 调 h3_submit.py --submit-only
status: 加载 manifest → 逐段轮询 → 输出性能统计
retry: 重新提交失败段（--force-new 绕过断点）

文件锁：workflows/.batch_lock（submit/retry 独占，status 无锁只读）。
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SUBMIT_SCRIPT = PROJECT_ROOT / 'runs' / 'h3_submit.py'
BATCH_DIR = PROJECT_ROOT / 'workflows'
LOCK_FILE = BATCH_DIR / '.batch_lock'


def _now() -> str:
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _acquire_lock():
    BATCH_DIR.mkdir(parents=True, exist_ok=True)
    fd = open(LOCK_FILE, 'w')
    fcntl.flock(fd, fcntl.LOCK_EX)
    return fd


def _release_lock(fd):
    fcntl.flock(fd, fcntl.LOCK_UN)
    fd.close()


def _save_manifest(manifest_dir: Path, manifest: dict):
    tmp = manifest_dir / 'manifest.json.tmp'
    tmp.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding='utf-8')
    os.replace(str(tmp), str(manifest_dir / 'manifest.json'))


def _resolve_image(name: str) -> Path:
    """解析图片路径：支持裸文件名（在 uploads/ 或 ComfyUI input/ 中查找）或绝对路径。"""
    p = Path(name).expanduser()
    if p.is_file():
        return p
    uploads = PROJECT_ROOT / 'uploads'
    for sub in sorted(uploads.iterdir(), reverse=True) if uploads.is_dir() else []:
        if sub.is_dir():
            candidate = sub / p.name
            if candidate.is_file():
                return candidate
    comfy_input = Path.home() / 'ai' / 'ComfyUI' / 'input'
    try:
        env = json.loads((PROJECT_ROOT / 'config' / 'environment.json').read_text(encoding='utf-8-sig'))
        comfy_dir = env.get('remote_comfyui_dir', '~/ai/ComfyUI').replace('~', str(Path.home()))
        comfy_input = Path(comfy_dir) / 'input'
    except Exception:
        pass
    for sub in [comfy_input] + list(comfy_input.iterdir()) if comfy_input.is_dir() else []:
        if sub.is_file():
            candidate = sub
            if candidate.name == p.name:
                return candidate
    raise ValueError(f'找不到图片: {name}')


def cmd_submit(args) -> int:
    images = [s.strip() for s in args.images.split(',') if s.strip()]
    if len(images) < 2:
        print('[错误] 至少需要 2 张图片才能生成转场', file=sys.stderr)
        return 3

    from runs.h3 import mediacheck
    resolved = []
    for name in images:
        try:
            p = _resolve_image(name)
        except ValueError as e:
            print(f'[错误] {e}', file=sys.stderr)
            return 3
        ok, reason = mediacheck.check_image_file(p)
        if not ok:
            print(f'[错误] 图片无效: {p.name} ({reason})', file=sys.stderr)
            return 3
        resolved.append(p)

    if args.stage == 'flf2v':
        segments = [{'idx': i, 'images': [str(resolved[i]), str(resolved[i + 1])],
                      'prompt_id': '', 'state': 'pending', 'error': '', 'output': '',
                      'submit_time': 0, 'complete_time': 0}
                     for i in range(len(resolved) - 1)]
    else:
        segments = [{'idx': i, 'images': [str(resolved[i])],
                      'prompt_id': '', 'state': 'pending', 'error': '', 'output': '',
                      'submit_time': 0, 'complete_time': 0}
                     for i in range(len(resolved))]

    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    batch_id = f'batch_{ts}'
    manifest_dir = BATCH_DIR / batch_id
    manifest_dir.mkdir(parents=True, exist_ok=True)

    manifest = {
        'batch_id': batch_id,
        'stage': args.stage,
        'resolution': args.resolution or '',
        'seconds': args.seconds or 5,
        'prompt': args.prompt or '',
        'segments': segments,
        'created': _now(),
        'total_submit_time': 0,
    }

    if args.dry_run:
        _save_manifest(manifest_dir, manifest)
        print(f'DRY RUN: manifest 已生成 {manifest_dir}')
        print(f'共 {len(segments)} 段')
        for seg in segments:
            print(f"  SEG {seg['idx']}: images={seg['images']}")
        print(f'BATCH_MANIFEST: {manifest_dir}')
        return 0

    lock_fd = _acquire_lock()
    try:
        _save_manifest(manifest_dir, manifest)
        t0 = time.time()
        for seg in segments:
            cmd = [sys.executable, str(SUBMIT_SCRIPT),
                   '--stage', args.stage, '--submit-only']
            for img in seg['images']:
                cmd.extend(['--image', img])
            if args.resolution:
                cmd.extend(['--resolution', args.resolution])
            if args.seconds:
                cmd.extend(['--seconds', str(args.seconds)])
            if args.prompt:
                cmd.extend(['--prompt', args.prompt])
            cmd.extend(['--force-new'])

            seg['submit_time'] = time.time()
            try:
                result = subprocess.run(cmd, capture_output=True, text=True,
                                        timeout=60, cwd=str(PROJECT_ROOT))
                if result.returncode == 0:
                    pid_line = next((ln.strip() for ln in result.stdout.splitlines()
                                     if ln.startswith('TASK_SUBMITTED:')), '')
                    seg['prompt_id'] = pid_line.split(':', 1)[1].strip() if ':' in pid_line else ''
                    seg['state'] = 'submitted'
                    print(f"SEG {seg['idx']}/{len(segments)} TASK_SUBMITTED: {seg['prompt_id']}")
                else:
                    seg['state'] = 'failed'
                    seg['error'] = result.stderr[:200] if result.stderr else f'exit {result.returncode}'
                    print(f"SEG {seg['idx']}/{len(segments)} FAILED: {seg['error']}", file=sys.stderr)
            except subprocess.TimeoutExpired:
                seg['state'] = 'timeout'
                seg['error'] = 'submit timeout (60s)'
                print(f"SEG {seg['idx']}/{len(segments)} TIMEOUT", file=sys.stderr)
            except Exception as e:
                seg['state'] = 'failed'
                seg['error'] = str(e)[:200]
            _save_manifest(manifest_dir, manifest)
        manifest['total_submit_time'] = round(time.time() - t0, 1)
        _save_manifest(manifest_dir, manifest)
        print(f'BATCH_MANIFEST: {manifest_dir}')
        print(f'提交耗时: {manifest["total_submit_time"]}s')
    finally:
        _release_lock(lock_fd)
    return 0


def cmd_status(args) -> int:
    batch_dir = _find_batch_dir(args.batch)
    if not batch_dir:
        print('[错误] 找不到批次目录', file=sys.stderr)
        return 3
    manifest_path = batch_dir / 'manifest.json'
    if not manifest_path.is_file():
        print(f'[错误] manifest 不存在: {manifest_path}', file=sys.stderr)
        return 3
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    timeout = args.timeout or 600
    t0 = time.time()

    while True:
        all_done = True
        for seg in manifest['segments']:
            if seg['state'] in ('completed', 'failed'):
                continue
            if not seg['prompt_id']:
                all_done = False
                continue
            cmd = [sys.executable, str(SUBMIT_SCRIPT), '--resume', seg['prompt_id']]
            try:
                result = subprocess.run(cmd, capture_output=True, text=True,
                                        timeout=30, cwd=str(PROJECT_ROOT))
                out = result.stdout + result.stderr
                if result.returncode == 0:
                    local = next((ln.strip() for ln in result.stdout.splitlines()
                                  if ln.startswith('LOCAL_OUTPUT:')), '')
                    remote = next((ln.strip() for ln in result.stdout.splitlines()
                                   if ln.startswith('REMOTE_VIDEO_PATH:')), '')
                    seg['state'] = 'completed'
                    seg['output'] = local or remote
                    seg['complete_time'] = time.time()
                    print(f"SEG {seg['idx']} 完成: {seg['output']}")
                elif result.returncode == 2:
                    all_done = False
                else:
                    seg['state'] = 'failed'
                    seg['error'] = out[:200]
            except subprocess.TimeoutExpired:
                all_done = False
            except Exception as e:
                seg['error'] = str(e)[:200]
            _save_manifest(batch_dir, manifest)

        if all_done or (not args.wait):
            break
        if time.time() - t0 > timeout:
            print(f'[超时] 等待超过 {timeout}s')
            break
        time.sleep(15)

    completed = sum(1 for s in manifest['segments'] if s['state'] == 'completed')
    failed = sum(1 for s in manifest['segments'] if s['state'] == 'failed')
    pending = sum(1 for s in manifest['segments'] if s['state'] not in ('completed', 'failed'))
    total_time = round(time.time() - t0, 1)
    avg = round(total_time / max(completed, 1), 1)

    if args.json:
        print(json.dumps(manifest, indent=2, ensure_ascii=False))
    else:
        print(f"\n批次 {manifest['batch_id']} 状态:")
        print(f"  完成: {completed}/{len(manifest['segments'])}")
        if failed:
            print(f"  失败: {failed}")
        if pending:
            print(f"  待处理: {pending}")
        print(f"  总耗时: {total_time}s，平均每段: {avg}s")
        for seg in manifest['segments']:
            status_icon = {'completed': '✅', 'failed': '❌', 'submitted': '⏳',
                           'pending': '⏸', 'timeout': '⏰'}.get(seg['state'], '?')
            print(f"  SEG {seg['idx']}: {status_icon} {seg['state']} "
                  + (seg.get('output', '') or seg.get('error', '')))

    return 0 if pending == 0 and failed == 0 else 2


def cmd_retry(args) -> int:
    batch_dir = _find_batch_dir(args.batch)
    if not batch_dir:
        print('[错误] 找不到批次目录', file=sys.stderr)
        return 3
    manifest_path = batch_dir / 'manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    seg_indices = {int(s.strip()) for s in args.segments.split(',') if s.strip()}

    lock_fd = _acquire_lock()
    try:
        for seg in manifest['segments']:
            if seg['idx'] not in seg_indices:
                continue
            if seg['state'] not in ('failed', 'timeout'):
                print(f"SEG {seg['idx']} 状态为 {seg['state']}，跳过")
                continue
            old_output = seg.get('output', '')
            if old_output and Path(old_output).exists():
                backup = Path(old_output).with_suffix('.bak')
                Path(old_output).rename(backup)
            cmd = [sys.executable, str(SUBMIT_SCRIPT),
                   '--stage', manifest['stage'], '--submit-only', '--force-new']
            for img in seg['images']:
                cmd.extend(['--image', img])
            if manifest.get('resolution'):
                cmd.extend(['--resolution', manifest['resolution']])
            if manifest.get('seconds'):
                cmd.extend(['--seconds', str(manifest['seconds'])])
            if manifest.get('prompt'):
                cmd.extend(['--prompt', manifest['prompt']])
            try:
                result = subprocess.run(cmd, capture_output=True, text=True,
                                        timeout=60, cwd=str(PROJECT_ROOT))
                if result.returncode == 0:
                    pid_line = next((ln.strip() for ln in result.stdout.splitlines()
                                     if ln.startswith('TASK_SUBMITTED:')), '')
                    seg['prompt_id'] = pid_line.split(':', 1)[1].strip() if ':' in pid_line else ''
                    seg['state'] = 'submitted'
                    seg['error'] = ''
                    seg['submit_time'] = time.time()
                    print(f"SEG {seg['idx']} 重试提交: {seg['prompt_id']}")
                else:
                    seg['error'] = result.stderr[:200] if result.stderr else f'exit {result.returncode}'
                    print(f"SEG {seg['idx']} 重试失败: {seg['error']}", file=sys.stderr)
            except Exception as e:
                seg['error'] = str(e)[:200]
            _save_manifest(batch_dir, manifest)
    finally:
        _release_lock(lock_fd)
    return 0


def _find_batch_dir(batch_ref: str | None) -> Path | None:
    if batch_ref:
        p = Path(batch_ref)
        if p.is_dir():
            return p
        candidate = BATCH_DIR / batch_ref
        if candidate.is_dir():
            return candidate
    dirs = sorted(BATCH_DIR.glob('batch_*'), key=lambda d: d.stat().st_mtime, reverse=True)
    return dirs[0] if dirs else None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description='批量提交引擎（多图转场）')
    sub = ap.add_subparsers(dest='cmd', required=True)

    p_sub = sub.add_parser('submit')
    p_sub.add_argument('--stage', required=True, choices=['flf2v', 'i2v', 'r2v', 't2v'])
    p_sub.add_argument('--images', required=True, help='逗号分隔的图片路径')
    p_sub.add_argument('--seconds', type=int, default=None)
    p_sub.add_argument('--resolution', default=None)
    p_sub.add_argument('--prompt', default='')
    p_sub.add_argument('--dry-run', action='store_true')

    p_stat = sub.add_parser('status')
    p_stat.add_argument('--wait', action='store_true')
    p_stat.add_argument('--timeout', type=int, default=600)
    p_stat.add_argument('--batch', default=None)
    p_stat.add_argument('--json', action='store_true')

    p_retry = sub.add_parser('retry')
    p_retry.add_argument('--batch', required=True)
    p_retry.add_argument('--segments', required=True, help='逗号分隔的段索引')

    args = ap.parse_args(argv)
    if args.cmd == 'submit':
        return cmd_submit(args)
    if args.cmd == 'status':
        return cmd_status(args)
    if args.cmd == 'retry':
        return cmd_retry(args)
    return 0


if __name__ == '__main__':
    sys.exit(main())
