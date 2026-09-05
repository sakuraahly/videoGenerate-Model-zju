"""
session_cleanup 单测：90 天历史会话清理（纯本地临时目录，不碰真库/运行期产物）。

运行方式（在项目根目录）：
  python -m unittest discover -s runs/h3/tests -p "test_*.py" -v
"""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))  # runs/

# 防御：其它模块（如 test_logutil）会把全局 tempfile.tempdir 指向 .test_tmp 并在
# tearDownModule 删除它；重置为 None（系统临时目录），避免 TemporaryDirectory 建目录失败。
tempfile.tempdir = None

from agent import session_cleanup  # noqa: E402

TS_FMT = '%Y-%m-%d %H:%M:%S'


def _write_session(chats_dir: Path, cid: str, age_days: int, now: datetime):
    """造一个会话档（<cid>.jsonl + <cid>.meta.json），mtime 与 meta.ts 都设为 age_days 天前。"""
    when = now - timedelta(days=age_days)
    jsonl = chats_dir / f'{cid}.jsonl'
    jsonl.write_text(
        json.dumps({'ts': when.strftime(TS_FMT), 'role': 'user', 'content': 'hi'},
                   ensure_ascii=False) + '\n',
        encoding='utf-8')
    meta = chats_dir / f'{cid}.meta.json'
    meta.write_text(
        json.dumps({'run_log': '', 'ts': when.strftime(TS_FMT), 'n_msgs': 1},
                   ensure_ascii=False),
        encoding='utf-8')
    epoch = when.timestamp()
    os.utime(jsonl, (epoch, epoch))
    os.utime(meta, (epoch, epoch))
    return jsonl, meta


class TestSessionCleanup(unittest.TestCase):
    def setUp(self):  # noqa: N802
        tempfile.tempdir = None  # 再次防御（见模块顶注释）
        self._td = tempfile.TemporaryDirectory()
        self.chats = Path(self._td.name)
        self.now = datetime.now()
        # old = 100 天前（超 90 → 超期）；new = 1 天前（保留）
        self.old_jsonl, self.old_meta = _write_session(self.chats, 'old_cid', 100, self.now)
        self.new_jsonl, self.new_meta = _write_session(self.chats, 'new_cid', 1, self.now)

    def tearDown(self):  # noqa: N802
        self._td.cleanup()

    def test_status_counts(self):
        stats, rc = session_cleanup.status(self.chats, days=90)
        self.assertEqual(rc, 0)
        self.assertEqual(stats['total'], 2)
        self.assertEqual(stats['expired'], 1)
        self.assertEqual(stats['kept'], 1)

    def test_clean_dry_run_keeps_all(self):
        stats, rc = session_cleanup.clean(self.chats, days=90, dry_run=True)
        self.assertEqual(rc, 0)
        self.assertTrue(stats['dry_run'])
        self.assertEqual(stats['expired'], 1)
        # dry-run 不删任何文件
        self.assertTrue(self.old_jsonl.exists())
        self.assertTrue(self.old_meta.exists())
        self.assertTrue(self.new_jsonl.exists())
        self.assertTrue(self.new_meta.exists())

    def test_clean_default_is_dry_run(self):
        # 不传 dry_run / yes → 默认 dry-run（无 --yes 即不删）
        stats, _rc = session_cleanup.clean(self.chats, days=90)
        self.assertTrue(stats['dry_run'])
        self.assertTrue(self.old_jsonl.exists())

    def test_clean_yes_deletes_old_keeps_new(self):
        stats, rc = session_cleanup.clean(self.chats, days=90, yes=True)
        self.assertEqual(rc, 0)
        self.assertFalse(stats['dry_run'])
        self.assertEqual(stats['deleted']['jsonl'], 1)
        self.assertEqual(stats['deleted']['meta'], 1)
        self.assertEqual(stats['deleted']['failed'], 0)
        # 超期的删了（jsonl + meta 都删）
        self.assertFalse(self.old_jsonl.exists())
        self.assertFalse(self.old_meta.exists())
        # 未超期的保留
        self.assertTrue(self.new_jsonl.exists())
        self.assertTrue(self.new_meta.exists())

    def test_thumbs_not_deleted(self):
        # thumbs/<sha>.jpg 按内容 sha 命名、无法关联 cid → 一律不删
        thumbs = self.chats / 'thumbs'
        thumbs.mkdir()
        thumb = thumbs / 'deadbeefdeadbeef.jpg'
        thumb.write_bytes(b'x' * 64)
        session_cleanup.clean(self.chats, days=90, yes=True)
        self.assertTrue(thumb.exists(), 'thumbs 缩略图不应被删除')

    def test_missing_dir_is_safe(self):
        # 目录不存在 → status/clean 不报错，统计为 0
        stats, rc = session_cleanup.status(self.chats / 'nope', days=90)
        self.assertEqual(rc, 0)
        self.assertEqual(stats['total'], 0)


if __name__ == '__main__':
    unittest.main()
