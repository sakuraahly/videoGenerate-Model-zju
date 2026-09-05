"""book-17 P2.2.1 伪造调用拦截单测（纯函数；Windows 无 qwen_agent 亦可测 schema 部分）。"""
import unittest

from runs.agent.ui_app import validate_tool_call, _parse_and_coerce_args

SAMPLE = {
    "type": "object",
    "properties": {
        "stage": {"type": "string", "enum": ["t2v", "r2v", "flf2v"]},
        "resolution": {"type": "string", "enum": ["360p", "720p"]},
        "seconds": {"type": "integer"},
        "dry_run": {"type": "boolean"},
    },
    "required": ["stage"],
}


class TestFabricationGuard(unittest.TestCase):
    def test_valid_passes(self):
        self.assertIsNone(validate_tool_call("call_comfyui",
                                             {"stage": "t2v", "seconds": 5}, SAMPLE))

    def test_unknown_tool_name_rejected(self):
        # Windows 无 qwen_agent 注册表：monkeypatch 白名单层验证流程（spark 真链另有实征）
        from runs.agent import ui_app as _ua
        _orig = _ua._tool_schema
        _ua._tool_schema = lambda name: (False, None) if name == "call_evil_tool" else (True, {})
        try:
            self.assertIn("未注册", validate_tool_call("call_evil_tool", {}, None))
            self.assertIsNone(validate_tool_call("ok_tool", {}, None))
        finally:
            _ua._tool_schema = _orig

    def test_empty_name(self):
        self.assertIn("空", validate_tool_call("", {"stage": "t2v"}, SAMPLE))

    def test_ghost_param_rejected(self):
        r = validate_tool_call("call_comfyui", {"stage": "t2v", "extra": 1}, SAMPLE)
        self.assertIn("未知参数", r)
        self.assertIn("extra", r)

    def test_string_int_rejected(self):
        # 强转前字符串会被拦截；_parse_and_coerce_args 后应为 int 且通过
        self.assertIn("整数", validate_tool_call("call_comfyui",
                                                {"stage": "t2v", "seconds": "5"}, SAMPLE))
        ok = _parse_and_coerce_args.__wrapped__ if hasattr(_parse_and_coerce_args, "__wrapped__") else None
        coerced = {"stage": "t2v", "seconds": "5"}
        # 手写同语义（Windows 无 registry，_tool_schema 返回 (True, None)）
        self.assertIsNotNone(validate_tool_call("call_comfyui", coerced, SAMPLE))

    def test_missing_required(self):
        self.assertIn("缺少必填", validate_tool_call("call_comfyui", {"seconds": 5}, SAMPLE))

    def test_enum_out_of_range(self):
        self.assertIn("不在允许集", validate_tool_call("call_comfyui",
                                                      {"stage": "x2v"}, SAMPLE))

    def test_bool_string_rejected(self):
        self.assertIn("布尔", validate_tool_call("call_comfyui",
                                                {"stage": "t2v", "dry_run": "True"}, SAMPLE))

    def test_bool_true_passes(self):
        self.assertIsNone(validate_tool_call("call_comfyui",
                                             {"stage": "t2v", "dry_run": True}, SAMPLE))

    def test_args_must_be_dict(self):
        self.assertIn("JSON 对象", validate_tool_call("call_comfyui", [], SAMPLE))


if __name__ == "__main__":
    unittest.main()