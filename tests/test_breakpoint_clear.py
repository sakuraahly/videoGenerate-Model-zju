"""book-19 §12 单测：任务完成自动清断点（clear_breakpoint_on_done，幂等/非目标不清）。"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runs'))  # runs/
from runs.agent import task_watch as _tw  # noqa: E402


class TestClearBreakpoint(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name)
        self._orig = _tw._PROJECT_ROOT
        _tw._PROJECT_ROOT = str(self.root)

    def tearDown(self):
        _tw._PROJECT_ROOT = self._orig
        self._td.cleanup()

    def _bp(self, pid):
        p = self.root / "last_job.json"
        p.write_text(json.dumps({"prompt_id": pid}), encoding="utf-8")
        return p

    def test_clears_when_same_pid(self):
        p = self._bp("abc-123")
        _tw.clear_breakpoint_on_done("abc-123")
        self.assertFalse(p.exists())

    def test_keeps_other_pid(self):
        p = self._bp("abc-123")
        _tw.clear_breakpoint_on_done("xyz-999")
        self.assertTrue(p.exists())

    def test_idempotent_no_file(self):
        _tw.clear_breakpoint_on_done("nope")
        self.assertFalse((self.root / "last_job.json").exists())


class TestStaleBreakpoint(unittest.TestCase):
    """2026-09-11 现场：watcher 的 --resume 被中断 → last_job.json 残留 → 新生成全被拦死。

    判据=项目自己的任务审计记录：state=completed（或质量看板已有产物）= 任务其实完成了，
    断点是陈旧的，应清掉放行；任务仍在跑则维持原拦截行为。
    """

    PID = 'ac88b2cb-1111-4222-8333-444455556666'

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name)

    def tearDown(self):
        self._td.cleanup()

    def _task(self, state, pid=None):
        import h3_submit  # noqa: F401  (确保 runs/ 已在 sys.path)
        from h3 import jobstate
        tf = self.root / 'workflows' / 'h3_20260911_013326_536'
        tf.mkdir(parents=True, exist_ok=True)
        jobstate.atomic_write_json(tf / 'job.json',
                                   {'state': state, 'prompt_id': pid or self.PID})
        return tf

    def test_completed_task_means_stale(self):
        import h3_submit
        self._task('completed')
        self.assertTrue(h3_submit._breakpoint_is_stale(self.root, self.PID))

    def test_running_task_is_not_stale(self):
        import h3_submit
        self._task('submitted')
        self.assertFalse(h3_submit._breakpoint_is_stale(self.root, self.PID))

    def test_unknown_pid_is_not_stale(self):
        import h3_submit
        self.assertFalse(h3_submit._breakpoint_is_stale(self.root, 'no-such-pid'))
        self.assertFalse(h3_submit._breakpoint_is_stale(self.root, ''))

    def test_quality_board_is_a_completion_proof(self):
        """任务记录缺失时，质量看板里已有该 pid 的产物 = 已完成。"""
        import h3_submit
        logs = self.root / 'logs'
        logs.mkdir(parents=True, exist_ok=True)
        (logs / 'quality.jsonl').write_text(
            json.dumps({'ts': '2026-09-11 01:36:23', 'prompt_id': self.PID,
                        'path': 'video_621.mp4'}) + '\n', encoding='utf-8')
        self.assertTrue(h3_submit._breakpoint_is_stale(self.root, self.PID))

    def test_guard_checks_staleness_before_blocking(self):
        """glue 守卫：拦截前必须先判陈旧再决定——否则残留断点让用户"点了没反应"。"""
        src = (ROOT / 'runs' / 'h3_submit.py').read_text(encoding='utf-8')
        i = src.index('检测到上次任务尚未完成')
        window = src[max(0, i - 1500):i]
        self.assertIn('_breakpoint_is_stale', window)
        self.assertIn('clear_root_state', window)


if __name__ == '__main__':
    unittest.main()
