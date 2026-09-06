"""book-19 队列监听（queue_watch）单测：复检状态机/probe 三态/失败安全。

mock ComfyClient + 注入时间；无网络。
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "runs"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from h3 import queue_watch as qw  # noqa: E402


class FakeClient:
    """模拟 queue_pids：按序列返回 (running, pending)；'raise' 触发异常。"""

    def __init__(self, states):
        self._states = list(states)
        self.calls = 0

    def queue_pids(self):
        idx = min(self.calls, len(self._states) - 1)
        self.calls += 1
        s = self._states[idx]
        if s == "raise":
            raise RuntimeError("comfy down")
        if s == "idle":
            return (set(), set())
        if s == "busy_v":
            return ({"pid1"}, set())
        if s == "busy_p":
            return (set(), {"pid2"})
        return ({"pid1"}, {"pid2"})


class TestProbe(unittest.TestCase):
    def test_states(self):
        self.assertEqual(qw.probe(FakeClient(["idle"])), "idle")
        self.assertEqual(qw.probe(FakeClient(["busy_v"])), "busy")
        self.assertEqual(qw.probe(FakeClient(["busy_p"])), "busy")
        self.assertEqual(qw.probe(FakeClient(["raise"])), "unreachable")  # 失败安全


class TestWaitIdle(unittest.TestCase):
    def _run(self, states, confirm=2, timeout=1800.0):
        fc = FakeClient(states)
        logs = []
        with mock.patch("time.sleep", return_value=None):
            ok = qw.wait_idle(fc, confirm=confirm, confirm_wait=10.0,
                              interval=10.0, timeout=timeout, log=logs.append)
        return ok, fc.calls, logs

    def test_idle_then_idle_confirmed(self):
        ok, calls, logs = self._run(["idle", "idle"])
        self.assertTrue(ok)
        self.assertEqual(calls, 2)  # 首探 idle + 复检 idle
        self.assertTrue(any("streak=2/2" in l for l in logs))

    def test_busy_resets_streak(self):
        # busy->idle->(busy 插队)->idle->idle 才确认
        ok, calls, logs = self._run(["busy", "idle", "busy", "idle", "idle"])
        self.assertTrue(ok)
        self.assertEqual(calls, 5)
        self.assertTrue(any("streak=1/2" in l for l in logs))

    def test_unreachable_resets_streak(self):
        ok, calls, _ = self._run(["raise", "idle", "idle"])
        self.assertTrue(ok)
        self.assertEqual(calls, 3)  # 不可达重置，需重来 2 次 idle

    def test_timeout_returns_false(self):
        # busy 持续；用推进的 monotonic 模拟超时
        fc = FakeClient(["busy"] * 50)
        t = [0.0]

        def fake_mono():
            t[0] += 5.0
            return t[0]

        with mock.patch("time.sleep", return_value=None),                 mock.patch("time.monotonic", side_effect=fake_mono):
            ok = qw.wait_idle(fc, confirm=2, confirm_wait=10.0,
                              interval=10.0, timeout=6.0, log=lambda *a: None)
        self.assertFalse(ok)


class TestCli(unittest.TestCase):
    def test_once_idle_exit(self):
        with mock.patch.object(qw, "make_client", return_value=FakeClient(["idle"])):
            self.assertEqual(qw.main(["once"]), 0)

    def test_once_busy_exit(self):
        with mock.patch.object(qw, "make_client", return_value=FakeClient(["busy_v"])):
            self.assertEqual(qw.main(["once"]), 2)


if __name__ == "__main__":
    unittest.main()
