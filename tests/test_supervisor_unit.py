"""book-15 L6 supervisor 单测（注入探测/拉起函数；Windows 可跑）。"""
import unittest

from runs.agent import supervisor as sup


class TestSupervisor(unittest.TestCase):
    def test_all_ok_no_action(self):
        sup.session_alive = lambda n: True
        sup.port_up = lambda p: True
        res = sup.ensure({})
        self.assertTrue(res["agent"]["ok"])
        self.assertEqual(res["agent"]["action"], "")

    def test_dead_agent_relaunched(self):
        sup.session_alive = lambda n: False
        sup.port_up = lambda p: False
        calls = {"n": 0}
        def fake_relaunch():
            calls["n"] += 1
            return True
        sup._SERVICES["agent"]["relaunch"] = fake_relaunch
        attempts = {}
        res = sup.ensure(attempts)
        self.assertEqual(res["agent"]["action"], "relaunched")
        self.assertEqual(calls["n"], 1)
        self.assertEqual(attempts["agent"], 0)

    def test_failed_then_alarm(self):
        sup.session_alive = lambda n: False
        sup.port_up = lambda p: False
        def fake_relaunch():
            return False
        sup._SERVICES["agent"]["relaunch"] = fake_relaunch
        attempts = {"agent": sup.MAX_ATTEMPTS}
        res = sup.ensure(attempts)
        self.assertEqual(res["agent"]["action"], "alarm")

    def test_port_check(self):
        sup.session_alive = lambda n: True
        sup.port_up = lambda p: False
        res = sup.check_once(strict_port=True)
        self.assertFalse(res["agent"]["ok"])
        res2 = sup.check_once(strict_port=False)
        self.assertTrue(res2["agent"]["ok"])


if __name__ == "__main__":
    unittest.main()