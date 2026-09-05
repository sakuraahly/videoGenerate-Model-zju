"""book-17 §3 参数策略单测（纯函数，Windows 可跑）。"""
import unittest

from runs.agent.agent_params import (
    default_lora_for_stage, delivery_lora_for_stage, default_params_for_stage, VERIFY_TIER,
)


class TestAgentParams(unittest.TestCase):
    def test_verify_tier(self):
        self.assertEqual(VERIFY_TIER["resolution"], "360p")
        self.assertEqual(VERIFY_TIER["seconds"], 5)

    def test_default_lora_t2v(self):
        for s in ("t2v", "i2v", "flf2v"):
            self.assertEqual(default_lora_for_stage(s), "fl2v_4step")

    def test_default_lora_r2v(self):
        self.assertEqual(default_lora_for_stage("r2v"), "ref2v_4step")

    def test_default_lora_unknown(self):
        self.assertIsNone(default_lora_for_stage("bogus"))

    def test_delivery(self):
        self.assertEqual(delivery_lora_for_stage("r2v"), "ref2v_8step")
        self.assertIsNone(delivery_lora_for_stage("t2v"))

    def test_default_params_package(self):
        p = default_params_for_stage("t2v")
        self.assertEqual(p["resolution"], "360p")
        self.assertEqual(p["seconds"], 5)
        self.assertEqual(p["lora"], "fl2v_4step")


if __name__ == "__main__":
    unittest.main()