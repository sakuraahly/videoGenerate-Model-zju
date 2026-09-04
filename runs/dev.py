#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
runs/dev.py — 变更与交付工作流工具盒（节省 agent token / 提升性能）。

背景：仓库里"核对状态、双端同步、提交、写文档、跑测试"这些环节，agent 常常要
一次次手动 git/log、ssh、read 大文件，极其消耗上下文。本脚本把这些环节固化为
"一次调用、精简输出"的命令，让 agent 只调用一次就拿到结论。

用法（在 Windows 主库项目根运行；ssh spark 需免密）：
    python runs/dev.py check                 # 双端状态 + 漂移 + 一致性 + 文档索引（exit 0=一致）
    python runs/dev.py sync                  # 把"本次改动"定点同步到 spark（不整仓、不覆盖机器配置）
    python runs/dev.py commit -m "<摘要>"    # Windows commit + push GitHub + spark commit（事务化）
    python runs/dev.py docs                  # 校验 START-HERE §2 索引覆盖全部 docs/skills
    python runs/dev.py test [--unit] [--smoke]  # 运行一致性/单测/干跑校验（精简输出）
    python runs/dev.py logs view [-N]       # 日志尾部/审计 jsonl（book-11）
    python runs/dev.py logs check           # 日志格式/坏行/轮转健康
    python runs/dev.py logs clean [--yes]   # 清 .1 轮转（默认 dry-run）

约定与红线（见 docs/dev-workflow.md / START-HERE.md §3.4）：
  - 不重启/不改 ComfyUI systemd；不改 spark 同事模板；不提 api_*；禁 Z:/ 路径。
  - 机器差异化配置（deploy/llm/pipeline/transfer/autosync/upload_watch/.sync-state/last_job）两端本就不同，同步/提交一律排除。
  - spark 永不 push GitHub；spark commit 用内联身份（Developer/dev@spark）。
  - 删除动作需显式 --clean（默认绝不删远端）。
"""
from __future__ import annotations
import argparse, json, os, re, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # Windows 主库项目根
SPARK = "spark"
SPARK_REPO = "/home/Developer/videoGenerate-Model-zju"  # spark 运行时目录（与 START-HERE 一致）

# 两端本就不同、不随同步覆盖的机器/运行期配置（与 runs/sync_to_spark.py EXCLUDE_* 对齐）
EXCLUDE_FILES = {
    "config/deploy.json", "config/llm.json", "config/llm.json.bak",
    "config/pipeline.json", "config/transfer.json", "config/autosync.json",
    "config/upload_watch.json", ".sync-state.json", "last_job.json",
    ".tunnel.json", ".run.lock", ".ai_brief.tmp.txt", ".sync-manifest.json",
}
EXCLUDE_DIRS = {".git", "__pycache__", ".pytest_cache", ".test_tmp"}
EXCLUDE_NAME = {"logs", "outputs"}
EXCLUDE_PREFIX = ("workflows/h3_",)


def _run(argv, cwd=None, timeout=60, env=None):
    """run a command, return (rc, stdout, stderr)."""
    try:
        p = subprocess.run(argv, cwd=cwd or str(ROOT), capture_output=True,
                           text=True, timeout=timeout, env=env)
        return p.returncode, p.stdout or "", p.stderr or ""
    except FileNotFoundError:
        return 127, "", f"command not found: {argv[0]}"
    except subprocess.TimeoutExpired:
        return 124, "", f"timeout: {argv}"


def _git(argv, cwd=None, timeout=60):
    """注意：out 只用 rstrip —— status --porcelain 首行的前导空格有语义，strip() 会丢。"""
    rc, out, err = _run(["git", "-C", str(cwd or ROOT)] + argv, timeout=timeout)
    return rc, out.rstrip(), err.strip()


def _ssh(cmd, timeout=90):
    """同 _git：只用 rstrip，保首行前导空格（spark 的 git status 首行也可能带空格）。"""
    rc, out, err = _run(["ssh", "-o", "BatchMode=yes", SPARK, cmd], timeout=timeout)
    return rc, out.rstrip(), err.strip()


def _is_excluded(rel: str) -> bool:
    parts = Path(rel).parts
    if not parts:
        return False
    if parts[0] in EXCLUDE_DIRS or parts[0] in EXCLUDE_NAME:
        return True
    if parts[0].startswith(EXCLUDE_PREFIX) and parts[0] != "workflows":
        return True
    if rel in EXCLUDE_FILES:
        return True
    if rel.startswith("workflows/h3_"):
        return True
    return False


def _changed_files():
    """return list of tracked changed file paths on Windows (excl. excluded).
    用 -uall 让未跟踪目录展开为文件；跳过目录/非文件条目。"""
    rc, out, err = _git(["status", "--porcelain", "-uall"])
    files = []
    for line in out.splitlines():
        if not line or len(line) < 4:
            continue
        p = line[3:].strip().strip('"')
        if not p or p.endswith('/'):
            continue
        if not (ROOT / p).is_file():
            continue
        if not _is_excluded(p):
            files.append(p)
    return sorted(set(files))


def _win_head():
    rc, out, err = _git(["rev-parse", "--short", "HEAD"])
    return out if rc == 0 else ""


def _gh_head():
    rc, out, err = _git(["rev-parse", "--short", "origin/master"])
    return out if rc == 0 else ""


def _spark_head():
    rc, out, err = _ssh(f"cd {SPARK_REPO} && git rev-parse --short HEAD 2>/dev/null")
    return out if rc == 0 else ""


def _spark_last_msg():
    rc, out, err = _ssh(f"cd {SPARK_REPO} && git log -1 --format=%B 2>/dev/null")
    return out if rc == 0 else ""


def _status_short(loc):
    """status --porcelain for Windows root or spark; return (count, first lines)."""
    if loc == "win":
        rc, out, err = _git(["status", "--porcelain"])
    else:
        rc, out, err = _ssh(f"cd {SPARK_REPO} && git status --porcelain 2>/dev/null")
    lines = [l for l in out.splitlines() if l]
    return len(lines), lines[:4]


def cmd_check(args):
    win = _win_head()
    gh = _gh_head()
    sp = _spark_head()
    sp_msg_full = _spark_last_msg()
    sp_msg = sp_msg_full.splitlines()[0] if sp_msg_full else ""
    sp_cnt, sp_top = _status_short("spark")
    win_cnt, win_top = _status_short("win")

    # consistency
    rc, cout, cerr = _run([sys.executable, str(ROOT / "runs" / "consistency_check.py")], timeout=90)
    m = re.search(r"问题 (\d+)", cout)
    issues = int(m.group(1)) if m else -1

    # docs index check
    missing = _docs_missing()
    spark_synced = bool(sp_msg_full and win and win in sp_msg_full)

    print("=== dev check ===")
    print(f"windows HEAD   : {win or '?'}")
    print(f"github  HEAD   : {gh or '?'}")
    print(f"spark  HEAD    : {sp or '?'}  (last: {sp_msg[:60]})")
    print(f"win dirty      : {win_cnt} 项")
    for l in win_top:
        print("   " + l)
    print(f"spark dirty    : {sp_cnt} 项")
    for l in sp_top:
        print("   " + l)
    print(f"consistency    : 问题 {issues}")
    print(f"docs index缺漏  : {len(missing)}  项" + ((" -> " + ", ".join(missing[:8])) if missing else ""))
    print(f"spark 已含本提交: {'是' if spark_synced else '否'}")
    print("---")
    ok = True
    if win and gh and win != gh:
        print("[WARN] Windows 与 GitHub 不一致（未推送或本地超前）")
        ok = False
    if sp and win and win != sp and not spark_synced:
        print("[WARN] spark 落后/未同步到本提交（spark HEAD ≠ win, 且 last msg 未含本次 win HEAD）")
        ok = False
    if issues > 0:
        print("[WARN] consistency_check 有问题")
        ok = False
    if missing:
        print("[info] 部分 docs/skills 未逐字出现在 START-HERE §2（可能是按组索引；新增项必须补索引，请人工确认）")
    print("[OK] 状态一致" if ok else "[FAIL] 需处理（见上 WARN）")
    return 0 if ok else 1


def cmd_sync(args):
    files = _changed_files()
    if not files:
        print("没有可同步的改动文件（已排除机器配置/产物/审计目录）。")
        return 0
    print(f"待同步 {len(files)} 个文件（定点，不整仓）：")
    for f in files:
        print("  " + f)
    if args.dry_run:
        print("[dry-run] 未实际同步。")
        return 0
    # 先确保远端目标目录存在（scp 不能自动建目录）
    dirs = sorted({str(Path(f).parent) for f in files if Path(f).parent != Path('.')})
    if dirs:
        mk = "mkdir -p " + " ".join(f'\"{SPARK_REPO}/{d}\"' for d in dirs)
        _ssh(mk)
    ok = 0
    for f in files:
        local = ROOT / f
        remote = f"{SPARK_REPO}/{f}"
        rc, out, err = _run(["scp", "-q", "-o", "BatchMode=yes", str(local),
                             f"{SPARK}:{remote}"], timeout=60)
        if rc != 0:
            print(f"  [FAIL] {f}: {err.strip()}")
            ok = 1
        else:
            print(f"  [OK]   {f}")
    if ok == 0:
        print("同步完成。建议随后：python runs/dev.py check")
    return ok


def cmd_commit(args):
    msg = args.message or "chore(dev): 通过 dev.py 提交"
    files = args.files or _changed_files()
    if not files:
        print("没有待提交的改动（已排除机器配置/产物/审计目录）。")
        return 0
    print("== Windows commit ==")
    add = ["git", "-C", str(ROOT), "add"] + files
    rc, out, err = _run(add)
    if rc != 0:
        print("[FAIL] git add:", err.strip())
        return 1
    rc, out, err = _git(["commit", "-m", msg])
    if rc != 0:
        print("[FAIL] git commit:", err.strip() or out)
        return 1
    win = _win_head()
    print(f"  {win}  {msg}")

    if not getattr(args, 'no_push', False):
        print("== push GitHub ==")
        rc, out, err = _git(["push", "origin", "master"], timeout=120)
        if rc != 0:
            # PowerShell 下 git 把进度写 stderr，rc 可能非 0 但已成功；用 origin/master 校验
            rc2, gh, _ = _git(["rev-parse", "--short", "origin/master"])
            if gh == win:
                print(f"  [OK] push 成功（origin/master = {gh}）")
            else:
                print("[FAIL] push:", err.strip() or out)
                return 1
        else:
            print("  [OK] push origin master")

    print("== spark commit ==")
    # 简化并避免远端 shell 引号问题：消息去除单/双引号，用单引号包裹
    safe_msg = re.sub(r"[^\w\s\-._:()]", "", msg).strip()[:100] or "chore(dev): sync"
    remote_files = [f'"{SPARK_REPO}/{f}"' for f in files]
    ssh_cmd = (
        f"cd {SPARK_REPO} && git add {' '.join(remote_files)} && "
        f"git -c user.name=Developer -c user.email=dev@spark commit "
        f"-m '{safe_msg}' -m 'sync from Windows {win}' 2>&1 | tail -3"
    )
    try:
        rc, out, err = _ssh(ssh_cmd)
        tail = (out or err).strip()
        print("  " + (tail[-400:] if tail else "done"))
    except Exception as e:  # noqa: BLE001
        print(f"  [FAIL] spark commit 异常: {e}")

    print("== 核对 ==")
    try:
        sp = _spark_head()
    except Exception:  # noqa: BLE001
        sp = ""
    gh = _gh_head()
    print(f"  windows={win}  github={gh}  spark={sp}")
    ok = (win == gh) and bool(sp)
    if not ok:
        print("[WARN] 请复核三端 HEAD；可手动：ssh spark 内 git commit（sync from Windows " + win + "）")
    print("[OK] 提交完成" if ok else "[FAIL] 有未完成项")
    return 0 if ok else 1


def _docs_all():
    """top-level docs/*.md and skills/*.md (nested dirs are indexed as groups)."""
    res = []
    for d in ("docs", "skills"):
        for f in sorted((ROOT / d).glob("*.md")):
            res.append(f.relative_to(ROOT).as_posix())
    return res


def _docs_missing():
    """docs/skills not found in START-HERE §2 index."""
    allf = _docs_all()
    idx = (ROOT / "START-HERE.md").read_text(encoding="utf8") if (ROOT / "START-HERE.md").exists() else ""
    missing = []
    for rel in allf:
        name = Path(rel).name
        if name not in idx:
            missing.append(rel)
    return missing


def cmd_docs(args):
    allf = _docs_all()
    missing = _docs_missing()
    miss_skill = [m for m in missing if m.startswith("skills/")]
    miss_doc = [m for m in missing if m.startswith("docs/")]
    print(f"docs/skills 顶层 .md 共 {len(allf)} 个")
    print(f"未逐字进 START-HERE §2: docs {len(miss_doc)} / skills {len(miss_skill)}")
    for m in missing:
        print("  MISSING  " + m)
    if miss_skill:
        print("[FAIL] 存在技能卡未进 START-HERE §2（§5 强制，必须补索引）")
        return 1
    if miss_doc:
        print("[info] 上述 docs 未逐字在 §2（可能是既有按组索引；**新增项**必须补索引）")
    print("[OK] skills 索引完整")
    return 0


def cmd_test(args):
    fail = 0
    print("== consistency_check ==")
    rc, cout, cerr = _run([sys.executable, str(ROOT / "runs" / "consistency_check.py")], timeout=90)
    first = cout.splitlines()
    for l in first[:8]:
        print("  " + l)
    m = re.search(r"问题 (\d+)", cout)
    issues = int(m.group(1)) if m else -1
    if issues > 0:
        print("  [FAIL] 有问题")
        fail = 1
    else:
        print("  [OK] 问题 0")

    if args.unit:
        print("== pytest runs/h3/tests ==")
        rc, cout, cerr = _run([sys.executable, "-m", "pytest", "runs/h3/tests", "-q"], timeout=180)
        tail = cout.strip().splitlines()[-3:] if cout.strip() else []
        print("  " + (" | ".join(tail) if tail else (cerr.strip()[-120:] or "(no output)")))
        if rc != 0:
            fail = 1

    if args.smoke:
        print("== h3_submit --stage t2v --dry-run ==")
        rc, cout, cerr = _run([sys.executable, str(ROOT / "runs" / "h3_submit.py"),
                               "--stage", "t2v", "--dry-run"], timeout=120)
        # H3_CONCISE to reduce output is handled by tools.py; here just report success
        ok = rc == 0
        print("  " + ("[OK] dry-run 通过" if ok else f"[FAIL] rc={rc} {cerr.strip()[-200:]}"))
        if not ok:
            fail = 1

    print("[OK] dev test 通过" if fail == 0 else "[FAIL] dev test 有失败项")
    return fail


def _logs_dir():
    d = ROOT / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def cmd_logs(args):
    """日志系统工具盒：view / check / clean（book-11）。"""
    d = _logs_dir()
    if args.action == "view":
        # 文件清单
        files = sorted(d.glob("**/*"), key=lambda x: x.stat().st_mtime if x.is_file() else 0)
        print(f"== logs/ 共 {len([f for f in files if f.is_file()])} 个文件 ==")
        tot = 0
        for f2 in [f for f in files if f.is_file()][-10:]:
            size = f2.stat().st_size
            tot += size
            print(f"  {f2.relative_to(d)}  {size/1024:.1f} KB")
        print(f"  （近 10 个合计 {tot/1024:.1f} KB；Git 已忽略 logs/）")
        au = d / "agent_tool_audit.jsonl"
        if au.exists():
            lines = au.read_text(encoding="utf-8", errors="replace").splitlines()
            n = args.limit or 15
            print(f"== agent_tool_audit.jsonl 共 {len(lines)} 行 / 最近 {min(n, len(lines))} 行 ==")
            for ln in lines[-n:]:
                try:
                    o = json.loads(ln)
                    pp = o.get("params") or {}
                    ps = " ".join(f"{k}={v}" for k, v in pp.items())[:80]
                    pid = o.get("prompt_id", "")[:8]
                    print(f"  {o.get('ts','?')} {o.get('tool','?'):<16} ok={o.get('ok')} "
                          f"len={o.get('result_len')} {ps} pid={pid}")
                except Exception:
                    print(f"  [BAD] {ln[:120]}")
        # 运行日志尾部
        runlogs = sorted(d.glob("**/run_*.log"), key=lambda x: x.stat().st_mtime)
        if runlogs:
            rl = runlogs[-1]
            tail = rl.read_text(encoding="utf-8", errors="replace").splitlines()[-args.limit or 8:]
            print(f"== {rl.relative_to(d)} 尾部 {len(tail)} 行 ==")
            for ln in tail:
                print("  " + ln[:160])
        if args.remote:
            # 跨端查看：spark 侧 agent 日志 + 运行日志目录
            n = args.limit or 15
            rc, out, err = _ssh(f"tail -n {n} ~/agent.log 2>/dev/null")
            if rc == 0 and out:
                print(f"== spark ~/agent.log 尾部 {n} 行 ==")
                for ln in out.splitlines()[-n:]:
                    print("  " + ln[:160])
            else:
                print(f"== spark ~/agent.log: (不可读 {err.strip()[:60] or '空'}) ==")
            rc2, out2, _ = _ssh(f"cd {SPARK_REPO} && ls -t logs 2>/dev/null | head -8")
            if rc2 == 0 and out2:
                print("== spark logs/ 最近文件 ==")
                for ln in out2.splitlines():
                    print("  " + ln)
        return 0

    if args.action == "check":
        issues = 0
        # 1) 库目录存在
        print(f"== 日志健康 ==")
        print(f"  logs/ 目录: {'OK' if d.is_dir() else '缺失'}")
        # 2) agent 工具审计 jsonl
        au = d / "agent_tool_audit.jsonl"
        if au.exists():
            bad = 0
            lines = au.read_text(encoding="utf-8", errors="replace").splitlines()
            for ln in lines:
                try:
                    json.loads(ln)
                except Exception:
                    bad += 1
            print(f"  agent_tool_audit.jsonl: {len(lines)} 行, 坏行 {bad}")
            if bad:
                issues += 1
        else:
            print("  agent_tool_audit.jsonl: (尚无 —— agent 调用工具后生成)")
        # 3) 运行日志格式正则
        fmt = re.compile(r"^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\] py: ")
        checked = 0
        badfmt = 0
        legacy = 0
        for rl in d.glob("**/run_*.log"):
            txt = rl.read_text(encoding="utf-8", errors="replace")
            if "# TZ=" not in txt[:2000]:
                legacy += 1
                continue  # book-11 之前旧格式，跳过
            for x in txt.splitlines()[-200:]:
                if x.strip():
                    checked += 1
                    if not fmt.match(x.strip()):
                        badfmt += 1
        print(f"  运行日志样本 {checked} 行, 非标准格式 {badfmt} (跳过旧格式 {legacy} 个)")
        if badfmt:
            issues += 1
        print("[OK] 日志系统健康" if issues == 0 else f"[FAIL] 日志系统 {issues} 处异常")
        return 0 if issues == 0 else 1

    if args.action == "clean":
        # 只清 .1 轮转与超期审计行（默认 dry-run；--yes 才删）
        removed = []
        kept = []
        for f2 in d.glob("**/*.1"):
            if args.yes:
                f2.unlink(missing_ok=True)
                removed.append(str(f2.relative_to(d)))
            else:
                kept.append(str(f2.relative_to(d)))
        if args.yes and removed:
            print("已删除轮转日志: " + " ".join(removed))
        elif kept:
            print("将删除轮转日志 (--yes 生效): " + " ".join(kept))
        else:
            print("无轮转日志 (.1) 可清。")
        return 0

    print("未知日志动作: " + args.action)
    return 2


def main(argv=None):
    ap = argparse.ArgumentParser(description="dev 工具盒：check/sync/commit/docs/test/logs")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check", help="双端状态+漂移+一致性+文档索引")
    s = sub.add_parser("sync", help="定点同步本次改动到 spark")
    s.add_argument("--dry-run", action="store_true")
    c = sub.add_parser("commit", help="Windows commit+push GitHub+spark commit")
    c.add_argument("-m", "--message", default="")
    c.add_argument("--no-push", action="store_true")
    c.add_argument("--files", nargs="*", default=None)
    sub.add_parser("docs", help="校验 START-HERE §2 索引")
    t = sub.add_parser("test", help="consistency+unit+smoke")
    t.add_argument("--unit", action="store_true")
    t.add_argument("--smoke", action="store_true")
    lg = sub.add_parser("logs", help="日志工具盒：view/check/clean（book-11）")
    lg.add_argument("action", choices=["view", "check", "clean"])
    lg.add_argument("--limit", type=int, default=None, help="view 显示行数")
    lg.add_argument("--remote", action="store_true", help="view 额外显示 spark 端 agent/日志")
    lg.add_argument("--yes", action="store_true", help="clean 真正删除（默认 dry-run）")
    args = ap.parse_args(argv)

    if args.cmd == "check":
        return cmd_check(args)
    if args.cmd == "sync":
        args.dry_run = getattr(args, "dry_run", False)
        return cmd_sync(args)
    if args.cmd == "commit":
        args.files = args.files
        return cmd_commit(args)
    if args.cmd == "docs":
        return cmd_docs(args)
    if args.cmd == "test":
        return cmd_test(args)
    if args.cmd == "logs":
        return cmd_logs(args)
    return 2


if __name__ == "__main__":
    sys.exit(main())
