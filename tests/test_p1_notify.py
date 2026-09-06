"""book-19 §9 P1 单测：通知文案/去重键/心跳（纯函数，Windows 可跑）。

不触碰网络与 grader 交互；watcher 循环本体由 ☆真机验证（提交→零轮询收到通知→
模型总结；健康降级文案）。""" 
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'runs'))  # runs/

from runs.agent.task_watch import (  # noqa: E402
    build_notify_message, notify_key, watcher_beat, watcher_health,
)


class TestNotifyMessage(unittest.TestCase):
    def test_completed_contains_real_ids(self):
        m = build_notify_message('completed', 'abc-123', detail='~/ai/ComfyUI/output/video/x.mp4（608x352, 5.00s）')
        self.assertIn('[任务完成]', m)
        self.assertIn('abc-123', m)
        self.assertIn('x.mp4', m)
        self.assertNotIn('虚构', m)

    def test_failed_contains_reason(self):
        m = build_notify_message('failed', 'p-9', detail='ComfyUI error: OOM')
        self.assertIn('[任务失败]', m)
        self.assertIn('OOM', m)

    def test_queue_timeout_contains_minutes(self):
        m = build_notify_message('queue_timeout', 'p-9', elapsed=1850)
        self.assertIn('[任务长时间排队]', m)
        self.assertIn('30 分钟', m)

    def test_run_timeout_contains_hours(self):
        m = build_notify_message('run_timeout', 'p-9', elapsed=7300)
        self.assertIn('[任务长时间运行]', m)
        self.assertIn('121 分钟', m)

    def test_watch_health_degrade(self):
        m = build_notify_message('watch_health')
        self.assertIn('[监听异常]', m)
        self.assertIn('查询工具', m)


class TestNotifyKey(unittest.TestCase):
    def test_key_format(self):
        k = notify_key('cid1', 'pid1', 'done')
        self.assertEqual(k, 'cid1|pid1|done')

    def test_key_distinguishes_events(self):
        self.assertNotEqual(notify_key('c', 't', 'done'), notify_key('c', 't', 'fail'))


class TestWatcherHeartbeat(unittest.TestCase):
    def test_initial_not_fresh(self):
        # 未 beat 过的 watcher 视为不新鲜(降级路径触发条件; 先重置保证隔离)
        from runs.agent.task_watch import _notify_hb
        _notify_hb['ts'] = 0.0
        # 未 beat 过的 watcher 视为不新鲜(降级路径触发条件)
        ok, age = watcher_health()
        self.assertFalse(ok)
        self.assertLess(age, 0)

    def test_beat_then_fresh(self):
        watcher_beat()
        ok, age = watcher_health()
        self.assertTrue(ok)
        self.assertGreaterEqual(age, 0.0)

    def test_stale_after_age(self):
        watcher_beat()
        time.sleep(0.05)
        ok, _ = watcher_health(max_age=0.01)
        self.assertFalse(ok)


if __name__ == '__main__':
    unittest.main()
