"""book-19 单测：task_scheduler 的 cron 匹配（五段式 _match/due_now）。"""
import sys
import time
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from runs.agent.task_scheduler import _match, due_now, load_tasks  # noqa: E402


class TestCronMatch(unittest.TestCase):
    def test_star(self):
        self.assertTrue(_match('*', 7))

    def test_step(self):
        self.assertTrue(_match('*/5', 0)); self.assertTrue(_match('*/5', 5)); self.assertFalse(_match('*/5', 3))

    def test_range(self):
        self.assertTrue(_match('22-23,0-6', 23)); self.assertTrue(_match('22-23,0-6', 2)); self.assertFalse(_match('22-23,0-6', 12))

    def test_single_and_list(self):
        self.assertTrue(_match('0,30', 30)); self.assertFalse(_match('0,30', 15))

    def test_due_now_hour_window(self):
        t = time.struct_time((2026, 9, 9, 22, 5, 0, 0, 1, -1))  # 22:05
        task = {'schedule': {'min': '*/5', 'hour': '22-23'}}
        self.assertTrue(due_now(task, t))
        t2 = time.struct_time((2026, 9, 9, 12, 5, 0, 0, 1, -1))
        self.assertFalse(due_now(task, t2))

    def test_tasks_config_parses(self):
        self.assertGreaterEqual(len(load_tasks()), 3)


if __name__ == '__main__':
    unittest.main()
