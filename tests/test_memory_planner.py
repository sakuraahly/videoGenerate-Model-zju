"""book-15 §3.2 内存编排单测（注入探测函数；Windows 可跑）。"""
import unittest

from runs.agent import llm_mem as mem


class TestPlanner(unittest.TestCase):
    def test_queue_idle_false_on_error(self):
        old = mem.urllib.request.urlopen
        mem.urllib.request.urlopen = lambda *a, **k: (_ for _ in ()).throw(OSError())
        try:
            self.assertFalse(mem.comfy_queue_idle())
        finally:
            mem.urllib.request.urlopen = old

    def test_queue_idle_true_empty(self):
        class Fake:
            status = 200
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False
            def read(self):
                return b"{\"queue_running\": [], \"queue_pending\": []}"
        old = mem.urllib.request.urlopen
        mem.urllib.request.urlopen = lambda *a, **k: Fake()
        try:
            self.assertTrue(mem.comfy_queue_idle())
        finally:
            mem.urllib.request.urlopen = old

    def test_adapt_table(self):
        self.assertEqual(len(mem._ADAPT), 3)
        self.assertEqual(mem._ADAPT[0]["mem_fraction"], 0.25)
        self.assertLess(mem._ADAPT[1]["mem_fraction"], mem._ADAPT[0]["mem_fraction"])


if __name__ == "__main__":
    unittest.main()