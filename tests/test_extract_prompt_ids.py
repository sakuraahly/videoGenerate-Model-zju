"""book-19 §15d 单测：extract_prompt_ids（提交登记兜底——全角冒号/转述漂移）。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from runs.agent.ui_app import extract_prompt_ids  # noqa: E402


class TestExtractPromptIds(unittest.TestCase):
    def test_half_width_colon(self):
        ids = extract_prompt_ids('prompt_id: e0099beb-ac5e-4f05-8d0b-11eb021a9bee')
        self.assertEqual(ids, ['e0099beb-ac5e-4f05-8d0b-11eb021a9bee'])

    def test_full_width_colon(self):
        # 2026-09-08 现场：模型转述用全角冒号「prompt_id：xxx」→ 旧正则漏登（任务不监控根因）
        ids = extract_prompt_ids('状态：TASK_SUBMITTED\nprompt_id：e0099beb-ac5e-4f05-8d0b-11eb021a9bee')
        self.assertIn('e0099beb-ac5e-4f05-8d0b-11eb021a9bee', ids)

    def test_task_submitted_full_width(self):
        ids = extract_prompt_ids('TASK_SUBMITTED：3fdd6a77-31f0-4cfc-a4a4-1f1b223c0e9a done')
        self.assertIn('3fdd6a77-31f0-4cfc-a4a4-1f1b223c0e9a', ids)

    def test_fallback_when_submitted_text(self):
        # 转述措辞再漂移（无 prompt_id 前缀）→ 提交语义兜底取首个 UUID
        ids = extract_prompt_ids('已提交，后台执行中 e0099beb-ac5e-4f05-8d0b-11eb021a9bee')
        self.assertEqual(ids, ['e0099beb-ac5e-4f05-8d0b-11eb021a9bee'])

    def test_no_false_positive_without_keywords(self):
        self.assertEqual(extract_prompt_ids('视频已生成完成，请查收'), [])
        self.assertEqual(extract_prompt_ids(''), [])

    def test_dedupe(self):
        ids = extract_prompt_ids('prompt_id: e0099beb-ac5e-4f05-8d0b-11eb021a9bee '
                                 'TASK_SUBMITTED: e0099beb-ac5e-4f05-8d0b-11eb021a9bee')
        self.assertEqual(len(ids), 1)


if __name__ == '__main__':
    unittest.main()
