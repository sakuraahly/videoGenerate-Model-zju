"""book-19 S3（T9 收尾）单测：mark_cancelled 分层（纯函数，Windows 可跑）。

取消后任务表轮询停止：mark_cancelled 登记 (cid,pid)；is_cancelled 判真后
worker 不再轮询该任务（真实链判据=取消运行中任务→会话查询收到"已取消"）。
""" 
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'runs'))  # runs/
from runs.agent.task_watch import mark_cancelled, is_cancelled  # noqa: E402


class TestMarkCancelled(unittest.TestCase):
    def setUp(self):
        from runs.agent import task_watch as _tw
        _tw._cancelled.clear()

    def test_mark_then_istrue(self):
        mark_cancelled('cid1', 'pid1')
        self.assertTrue(is_cancelled('cid1', 'pid1'))

    def test_not_marked_false(self):
        self.assertFalse(is_cancelled('cid1', 'pidX'))

    def test_cid_namespace(self):
        mark_cancelled('cid1', 'pid1')
        self.assertFalse(is_cancelled('cid2', 'pid1'))

    def test_mark_idempotent(self):
        mark_cancelled('cid1', 'pid1')
        mark_cancelled('cid1', 'pid1')
        self.assertTrue(is_cancelled('cid1', 'pid1'))


if __name__ == '__main__':
    unittest.main()
