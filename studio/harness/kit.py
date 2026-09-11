"""studio.harness.kit - 可执行生产包（Production Kit）：一次"一句话"产出一个 zip。

包里装的不是演示，而是**一套能复制的系统**（book-20 §4.4）：

  plan.json      剧本 + 分镜表 + 参数 + 一致性锚点 + 质检结果
  jobs.jsonl     每段一行：完整引擎请求体（复制即用）
  commands.md    每段的命令行等价形式（给用本机 GPU 的人）
  run_plan.py    一条命令跑完全片（提交→轮询→取回→拼接→验收，可断点续跑）
  accept.md      验收规则（规则验收 + 引擎侧可选 VLM 检查项 + 诚实边界）
  post.md        后期指令（超分/插帧/混音/字幕：命令与参数，**空间内不执行**）
  film.srt       字幕原文（台词表直出，不经 ASR，无错别字）
  trace.json     全程决策轨迹（5 角色分工与重试的证据）
  README.md      怎么用、需要什么、每步耗时、失败怎么续跑

空间内**只生成指令、不执行**（C1/C4 红线）：包里没有任何指向本机的调用，
run_plan.py 只认环境变量里的引擎地址，跑不跑、在哪跑由拿到包的人决定。
"""
from __future__ import annotations

import io
import json
import zipfile
from datetime import datetime

from ..rules import frames as _fr
from ..rules import post as _post
from . import state as _st

KIT_FORMAT = 'film-agent/kit@1'

# 注意：必须是 **raw** 字符串 —— 里面全是给"别人机器"看的 \n / \\，不能被本文件解释掉
RUN_PLAN_PY = r'''#!/usr/bin/env python3
"""按生产包跑完全片：提交 → 轮询 → 取回 → 拼接 → 验收（纯标准库 + 可选 ffmpeg）。

用法：
  ENGINE_BASE_URL=https://你的引擎/v1 ENGINE_STATUS_URL=https://你的引擎/v1/jobs \
  ENGINE_API_KEY=xxx python3 run_plan.py                 # 全部跑完
  python3 run_plan.py --only 2,3                         # 只重跑失败段（断点续跑）
  python3 run_plan.py --dry-run                          # 只打印将要提交的请求体，不联网
环境变量：
  ENGINE_BASE_URL    提交地址（POST，返回 {"job_id": "..."}）
  ENGINE_STATUS_URL  查询地址（GET <status>/<job_id> → {"status","video"}）
  ENGINE_API_KEY     可选，会以 Authorization: Bearer 发送
  ENGINE_POLL        轮询间隔秒（默认 10）；ENGINE_TIMEOUT 单段超时秒（默认 1800）
产物：out/shot_00.mp4 ... / out/film.mp4 / out/accept.json / out/state.json
退出码：0 全成功；2 有段失败（已完成段仍然保留，可 --only 续跑）；3 没配引擎
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / 'out'
STATE = OUT / 'state.json'


def load_jobs():
    jobs = []
    with open(HERE / 'jobs.jsonl', 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                jobs.append(json.loads(line))
    return jobs


def load_state():
    if STATE.exists():
        try:
            return json.loads(STATE.read_text(encoding='utf-8'))
        except ValueError:
            return {}
    return {}


def save_state(st):
    OUT.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding='utf-8')


def post(url, body, key, timeout=180):
    data = json.dumps(body).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
    if key:
        req.add_header('Authorization', 'Bearer ' + key)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode('utf-8', 'replace') or '{}')


def get(url, key, timeout=60):
    req = urllib.request.Request(url)
    if key:
        req.add_header('Authorization', 'Bearer ' + key)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode('utf-8', 'replace') or '{}')


def download(url, path, key):
    req = urllib.request.Request(url)
    if key:
        req.add_header('Authorization', 'Bearer ' + key)
    with urllib.request.urlopen(req, timeout=600) as r, open(path, 'wb') as f:
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
    return path


def run_shot(job, base, status_url, key, poll, timeout):
    idx = int(job.get('idx', 0))
    target = OUT / ('shot_%02d.mp4' % idx)
    body = {k: v for k, v in job.items() if k not in ('idx', 'ref_slots', 'accept', 'command')}
    d = post(base, body, key)
    job_id = d.get('job_id') or d.get('task_id') or d.get('id')
    if not job_id:
        return {'idx': idx, 'ok': False, 'error': '引擎没有返回 job_id：%s' % json.dumps(d)[:200]}
    t0 = time.time()
    while True:
        if time.time() - t0 > timeout:
            return {'idx': idx, 'ok': False, 'job_id': job_id, 'error': '超时 %ds' % timeout}
        time.sleep(poll)
        s = get(status_url.rstrip('/') + '/' + str(job_id), key)
        status = str(s.get('status') or '').lower()
        if status in ('completed', 'succeeded', 'success', 'done'):
            url = s.get('video') or s.get('video_url') or s.get('url') or s.get('output')
            if not url:
                return {'idx': idx, 'ok': False, 'job_id': job_id, 'error': '完成但没有成片链接'}
            download(url, target, key)
            return {'idx': idx, 'ok': True, 'job_id': job_id, 'file': str(target)}
        if status in ('failed', 'error', 'canceled', 'cancelled'):
            return {'idx': idx, 'ok': False, 'job_id': job_id,
                    'error': str(s.get('error') or s.get('message') or status)}


def probe(path):
    """有 ffprobe 就核帧数/时长；没有就如实说没校验。"""
    try:
        r = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-count_frames',
                            '-show_entries', 'stream=nb_read_frames,duration', '-of', 'json', str(path)],
                           capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            return {'checked': False, 'why': 'ffprobe 返回 %d' % r.returncode}
        s = (json.loads(r.stdout or '{}').get('streams') or [{}])[0]
        return {'checked': True, 'frames': int(s.get('nb_read_frames') or 0),
                'seconds': float(s.get('duration') or 0)}
    except (OSError, ValueError, subprocess.SubprocessError) as e:
        return {'checked': False, 'why': '没有 ffprobe 或调用失败：%s' % e}


def stitch(files, out):
    """有 ffmpeg 就拼成一整片（无损 concat）；没有就把分段清单写出来。"""
    if not files:
        return {'stitched': False, 'why': '没有可拼接的段'}
    lst = OUT / 'concat.txt'
    lst.write_text(''.join("file '%s'\n" % Path(f).resolve().as_posix() for f in files),
                   encoding='utf-8')
    try:
        r = subprocess.run(['ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', str(lst),
                            '-c', 'copy', str(out)], capture_output=True, text=True, timeout=1800)
    except (OSError, subprocess.SubprocessError) as e:
        return {'stitched': False, 'why': '没有 ffmpeg：%s' % e}
    if r.returncode != 0:
        return {'stitched': False, 'why': r.stderr[-300:]}
    return {'stitched': True, 'file': str(out)}


def main():
    ap = argparse.ArgumentParser(description='按生产包跑完全片（可断点续跑）')
    ap.add_argument('--only', default='', help='只跑这些段，如 2,3（默认全部）')
    ap.add_argument('--dry-run', action='store_true', help='只打印请求体，不联网')
    ap.add_argument('--force', action='store_true', help='忽略已完成记录，全部重跑')
    args = ap.parse_args()

    jobs = load_jobs()
    only = {int(x) for x in args.only.replace('，', ',').split(',') if x.strip().isdigit()}
    if args.dry_run:
        for job in jobs:
            if only and int(job.get('idx', 0)) not in only:
                continue
            print(json.dumps({k: v for k, v in job.items() if k != 'ref_slots'},
                             ensure_ascii=False))
        return 0

    base = os.environ.get('ENGINE_BASE_URL', '').strip()
    status_url = os.environ.get('ENGINE_STATUS_URL', '').strip()
    if not base or not status_url:
        print('没有配置引擎：请设 ENGINE_BASE_URL 与 ENGINE_STATUS_URL。')
        print('本生产包不包含任何算力；你可以接自己的网关、云上视频模型或本机 GPU 服务。')
        return 3
    key = os.environ.get('ENGINE_API_KEY', '').strip()
    poll = int(os.environ.get('ENGINE_POLL', '10') or 10)
    timeout = int(os.environ.get('ENGINE_TIMEOUT', '1800') or 1800)
    OUT.mkdir(parents=True, exist_ok=True)
    state = load_state()
    results = []
    for job in jobs:
        idx = int(job.get('idx', 0))
        if only and idx not in only:
            continue
        done = state.get(str(idx)) or {}
        if done.get('ok') and Path(done.get('file', '')).exists() and not args.force:
            print('[%02d] 已完成，跳过（--force 可重跑）' % idx)
            results.append(done)
            continue
        print('[%02d] 提交：%s' % (idx, str(job.get('prompt'))[:60]))
        try:
            r = run_shot(job, base, status_url, key, poll, timeout)
        except Exception as e:
            r = {'idx': idx, 'ok': False, 'error': '%s: %s' % (type(e).__name__, e)}
        if r.get('ok'):
            r['probe'] = probe(r['file'])
        results.append(r)
        state[str(idx)] = r
        save_state(state)
        print('[%02d] %s %s' % (idx, 'OK' if r.get('ok') else '失败', r.get('error') or r.get('file')))

    good = [r['file'] for r in results if r.get('ok') and r.get('file')]
    s = stitch(good, OUT / 'film.mp4')
    report = {'shots': results, 'stitch': s,
              'failed': [r['idx'] for r in results if not r.get('ok')],
              'done': [r['idx'] for r in results if r.get('ok')]}
    (OUT / 'accept.json').write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                     encoding='utf-8')
    print('\n=== 验收 ===')
    print('完成 %d 段，失败 %d 段' % (len(report['done']), len(report['failed'])))
    for r in results:
        p = r.get('probe') or {}
        if r.get('ok') and p.get('checked'):
            print('[%02d] %d 帧 / %.2fs' % (r['idx'], p.get('frames', 0), p.get('seconds', 0)))
        elif not r.get('ok'):
            print('[%02d] 失败：%s' % (r['idx'], r.get('error')))
    if s.get('stitched'):
        print('整片：%s' % s['file'])
    else:
        print('未拼接：%s' % s.get('why'))
    if report['failed']:
        print('续跑：python3 run_plan.py --only %s'
              % ','.join(str(x) for x in report['failed']))
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
'''


def _plan(st: _st.StoryState) -> dict:
    shots = []
    for shot in st.shots:
        d = next((x for x in st.directives if x.get('idx') == shot['idx']), {})
        shots.append({
            'idx': shot['idx'], 'beat': shot['beat'], 'seconds': shot['seconds'],
            'frames': shot['frames'], 'resolution': shot.get('resolution'),
            'cast': shot.get('cast') or [], 'line': shot.get('line'),
            'prompt': d.get('prompt') or shot['prompt'],
            'negative': d.get('negative') or '',
            'camera': shot.get('camera'), 'light': shot.get('light'),
            'environment': shot.get('environment'), 'audio': shot.get('audio'),
            'anchor': shot.get('anchor'), 'silent': shot.get('silent'),
            'ref_slots': shot.get('ref_slots') or [], 'seed': (d.get('params') or {}).get('seed'),
            'accept': d.get('accept') or [],
        })
    return {
        'format': KIT_FORMAT,
        'generated_by': 'AI+∞ 电影 Agent（魔搭创空间 Harness：规则引擎 / 访客自带大脑）',
        'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'brief': st.brief, 'title': (st.script or {}).get('title') or st.brief[:24],
        'style': st.style, 'brain': st.brain_kind, 'mode': st.mode,
        'fps': _fr.FPS, 'resolution': (st.shots[0] or {}).get('resolution') if st.shots else '',
        'total_seconds': round(sum(s['seconds'] for s in st.shots), 2),
        'total_frames': sum(s['frames'] for s in st.shots),
        'characters': (st.script or {}).get('characters') or {},
        'persona_voices': (st.script or {}).get('persona_voices') or {},
        'lines': (st.script or {}).get('lines') or {},
        'setting': (st.script or {}).get('setting') or '',
        'anchor': bool(st.anchor),
        'assets_licensed': bool(st.assets_licensed),
        'shots': shots,
        'critic': st.critic,
        'prelint': st.prelint,
    }


def _jobs_jsonl(st: _st.StoryState) -> str:
    out = []
    for shot in st.shots:
        d = next((x for x in st.directives if x.get('idx') == shot['idx']), {})
        body = dict(d.get('request') or {})
        body['idx'] = shot['idx']
        body['ref_slots'] = shot.get('ref_slots') or []
        body['accept'] = d.get('accept') or []
        out.append(json.dumps(body, ensure_ascii=False))
    return '\n'.join(out) + '\n'


def _commands_md(st: _st.StoryState) -> str:
    res = (st.shots[0] or {}).get('resolution', '480p') if st.shots else '480p'
    sec = max(2, int(round((st.shots[0] or {}).get('seconds', 5)))) if st.shots else 5
    seed = (st.shots[0] or {}).get('seed', 20260915) if st.shots else 20260915
    L = ['# 命令行等价形式', '',
         '> 给"自带本机 GPU"的人：把 `plan.json` 与 `refs/` 放到项目根目录，逐段执行。',
         '> 台词铁律：台词由视频模型**原声说出**（`--audio-source h3` / `--voice-mode native`），',
         '> 不要走 TTS 链，否则音画不同步、口型对不上。', '',
         '## 整片一条命令', '', '```bash',
         'python3 runs/h3/story_film.py --story plan.json --resolution %s --seconds %d '
         '--lora fl2v_4step --seed %d --stitch --no-subtitle --voice-mode native --out film.mp4'
         % (res, sec, seed),
         '```', '', '## 逐段命令', '']
    for d in st.directives:
        shot = next((s for s in st.shots if s['idx'] == d['idx']), {})
        L += ['### 第 %d 段（%s，%d 帧 / %.2fs）'
              % (d['idx'], '说话段' if d.get('kind') == 'talk' else '静默段',
                 shot.get('frames', 0), shot.get('seconds', 0)), '',
              '```bash', d['command'], '```']
        if shot.get('line'):
            L += ['台词：`%s`（%s，原声说出，不写进画面提示词）'
                  % (shot['line'].get('text'), shot['line'].get('voice'))]
        L += ['', '正向提示词：', '', '```text', d.get('prompt', ''), '```',
              '负向提示词：', '', '```text', d.get('negative', ''), '```', '']
    return '\n'.join(L)


def _accept_md(st: _st.StoryState) -> str:
    from ..rules.delivery import VLM_CHECKLIST
    pre = st.prelint or {}
    cri = st.critic or {}
    L = ['# 验收规则', '',
         '## 一、规则验收（空间内已完成，0 算力）', '',
         '- 剧本静态预检：%s' % (pre.get('summary') or '-'),
         '- 帧网格：全部段落在 5+17k 网格（%d fps）' % _fr.FPS,
         '- 质检：%s' % (cri.get('summary') or '-'),
         '- 自动改写重试：%d 轮' % int(cri.get('rounds') or 0), '']
    if pre.get('errors'):
        L += ['### 未消除的预检错误', ''] + ['- %s' % e for e in pre['errors'][:20]] + ['']
    if pre.get('warnings'):
        L += ['### 预检告警（建议改，不改也能拍）', ''] + ['- %s' % w for w in pre['warnings'][:20]] + ['']
    L += ['## 二、逐段验收（拿到成片后逐条打勾）', '']
    for d in st.directives:
        L += ['### 第 %d 段' % d['idx'], ''] + ['- [ ] %s' % a for a in (d.get('accept') or [])] + ['']
    L += ['## 三、引擎侧可选检查（空间内不判帧，交给执行方）', '']
    L += ['- [ ] %s' % v for v in VLM_CHECKLIST] + ['']
    L += ['## 四、后期与成片规格（命令见 post.md）', '',
          '- [ ] 超分/插帧按 post.md 执行（合成清晰度要如实标注）',
          '- [ ] 混音：台词清楚、环境声不盖台词、响度约 -16 LUFS',
          '- [ ] 字幕用 film.srt（台词原文，不经 ASR）', '',
          '## 五、成片规格验收（run_plan.py 有 ffprobe 时会写进 out/accept.json）', '',
          '- [ ] 每段帧数与 plan.json 一致（±0 帧）',
          '- [ ] 整片时长 = 各段之和',
          '- [ ] 无文字/字幕/水印残留',
          '- [ ] 台词段口型同步、静默段无唇动',
          '- [ ] 片尾含 AI 生成声明', '']
    return '\n'.join(L)


def _post_md(st: _st.StoryState) -> str:
    """后期指令（超分/插帧/混音/字幕）—— 只出指令，空间内不执行。"""
    return _post.post_markdown(st)


def _readme(st: _st.StoryState) -> str:
    shots = len(st.shots)
    secs = round(sum(s['seconds'] for s in st.shots), 1)
    frames = sum(s['frames'] for s in st.shots)
    L = ['# 生产包使用说明', '',
         '本包由「AI+∞ 电影 Agent」在魔搭创空间内生成。**空间内不部署、不运行任何模型**：',
         '它负责规划、质检与产出可执行指令；成片算力来自**你自己**的引擎。', '',
         '## 一句话', '', '> %s' % st.brief, '',
         '## 包里有什么', '', '| 文件 | 用途 |', '|---|---|',
         '| `plan.json` | 剧本 + 分镜表 + 参数 + 一致性锚点 + 质检结果 |',
         '| `jobs.jsonl` | 每段一行完整引擎请求体（复制即用） |',
         '| `commands.md` | 逐段命令行等价形式（自带本机 GPU 的人用这个） |',
         '| `run_plan.py` | 一条命令跑完全片（提交→轮询→取回→拼接→验收，可断点续跑） |',
         '| `accept.md` | 验收规则（规则验收 + 引擎侧可选检查） |',
         '| `post.md` | 后期指令：超分/插帧/混音/字幕的命令与参数（空间内不执行） |',
         '| `film.srt` | 字幕原文（台词表直出，不经 ASR，无错别字） |',
         '| `trace.json` | 决策轨迹：5 个角色分别做了什么、重试了几轮 |',
         '| `README.md` | 本文件 |', '',
         '## 怎么用', '',
         '### A. 有引擎（云上视频模型 / 自建网关）', '', '```bash',
         'ENGINE_BASE_URL=https://你的引擎/v1 \\',
         'ENGINE_STATUS_URL=https://你的引擎/v1/jobs \\',
         'ENGINE_API_KEY=xxx python3 run_plan.py', '```', '',
         '先干跑看看请求体长什么样：`python3 run_plan.py --dry-run`；',
         '某段失败只重跑它：`python3 run_plan.py --only 2,3`。', '',
         '### B. 有本机 GPU', '',
         '照 `commands.md` 逐段执行，或直接用 `plan.json` 跑整片命令。', '',
         '### C. 只想看看', '',
         '`plan.json` 里的分镜表白纸黑字写着每段的提示词、帧数、秒数、是否说话、台词与参考图槽位，',
         '照着拍、照着生成都行。', '',
         '## 引擎契约', '',
         '- `POST <ENGINE_BASE_URL>` 提交，body 见 `jobs.jsonl`，返回 `{"job_id": "..."}`；',
         '- `GET <ENGINE_STATUS_URL>/<job_id>` 返回 '
         '`{"status": "queued|running|completed|failed", "video": "<url>"}`；',
         '- `ffmpeg` / `ffprobe` 可选：有就自动拼接与核验帧数，没有也能跑。', '',
         '## 规模与耗时预估', '',
         '- %d 段 / 约 %.1f 秒成片 / %d 帧（%d fps）' % (shots, secs, frames, _fr.FPS),
         '- 单段生成耗时取决于引擎：按每段 1-3 分钟保守估计，%d 段约 %d-%d 分钟；'
         '段与段之间无依赖，可并发提交（`jobs.jsonl` 每行独立）' % (shots, shots, shots * 3), '',
         '## 失败了怎么办', '',
         '- `out/state.json` 记录每段结果；重跑会自动跳过已完成的段。',
         '- 某段失败：看 `out/accept.json` 里的 error，改 `jobs.jsonl` 对应行（或换 seed）后 `--only N`。',
         '- 实在跑不动：用已完成的段拼一版，交付说明里**如实标注**缺哪段（不要假装完整）。', '',
         '## 边界（必须如实说明）', '',
         '- 本包不含任何模型与权重；空间内不推理、不下载、不连接任何本机 GPU。',
         '- 成片质量取决于**引擎侧模型**；空间侧保证的是"可拍、合规、可复现"。',
         '- 本片由 AI 生成；请勿使用未经授权的真人肖像或受版权保护的素材。', '']
    return '\n'.join(L)


def build_kit(st: _st.StoryState) -> dict:
    """组装生产包（全量，含 zip 字节）；页面要下载请用 save_kit()。"""
    files = {
        'plan.json': json.dumps(_plan(st), ensure_ascii=False, indent=2),
        'jobs.jsonl': _jobs_jsonl(st),
        'commands.md': _commands_md(st),
        'run_plan.py': RUN_PLAN_PY,
        'accept.md': _accept_md(st),
        'post.md': _post_md(st),
        'film.srt': _post.srt_from_shots(st.shots),
        'README.md': _readme(st),
        'trace.json': json.dumps({
            'format': KIT_FORMAT, 'brief': st.brief, 'state': st.state, 'mode': st.mode,
            'brain': st.brain_kind, 'retries': st.retries,
            'roles': {k: {kk: vv for kk, vv in v.items() if kk != 'lines'}
                      for k, v in (st.roles or {}).items()},
            'steps': [s.to_dict() for s in st.trace],
            'critic': st.critic, 'prelint': st.prelint,
        }, ensure_ascii=False, indent=2),
    }
    zip_bytes = make_zip(files)
    name = 'production_kit_%s.zip' % datetime.now().strftime('%Y%m%d_%H%M')
    summary = {
        'format': KIT_FORMAT, 'name': name, 'zip_name': name,
        'bytes': len(zip_bytes),
        'files': {k: {'chars': len(v), 'lines': v.count('\n') + 1} for k, v in files.items()},
        'shots': len(st.shots),
        'seconds': round(sum(s['seconds'] for s in st.shots), 2),
        'summary': '生产包 %d 个文件 / %.1f KB ｜ %d 段 / %.1fs'
                   % (len(files), len(zip_bytes) / 1024.0, len(st.shots),
                      sum(s['seconds'] for s in st.shots)),
    }
    return {'name': name, 'files': files, 'zip_bytes': zip_bytes, 'summary': summary}


ORDER = ('plan.json', 'jobs.jsonl', 'commands.md', 'run_plan.py', 'accept.md', 'post.md',
         'film.srt', 'trace.json', 'README.md')


def make_zip(files: dict) -> bytes:
    """files → zip 字节（固定时间戳：同内容两次生成字节一致，便于比对与复现）。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        for name in ORDER:
            _write(z, name, files.get(name))
        for name in sorted(set(files) - set(ORDER)):
            _write(z, name, files.get(name))
    return buf.getvalue()


def _write(z: zipfile.ZipFile, name: str, text) -> None:
    if text is None:
        return
    info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    z.writestr(info, text)


def save_kit(kit: dict, out_dir) -> str:
    """把 zip 落到磁盘（创空间里写 /tmp），返回路径供页面下载。"""
    from pathlib import Path
    d = Path(out_dir)
    d.mkdir(parents=True, exist_ok=True)
    p = d / (kit.get('name') or 'production_kit.zip')
    p.write_bytes(kit.get('zip_bytes') or make_zip(kit.get('files') or {}))
    return str(p)


def plan_preview(st: _st.StoryState) -> dict:
    """不打包，只要 plan（页面/接口说明复用）。"""
    return _plan(st)


__all__ = ['KIT_FORMAT', 'RUN_PLAN_PY', 'ORDER', 'build_kit', 'make_zip', 'save_kit',
           'plan_preview']
