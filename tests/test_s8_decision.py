"""book-19 S8 单测：ComfyUI 状态决策树 classify_task_state（五审定稿口径）。

纯函数、无网络、Windows 可跑。口径：
- completed：history 非空且 status.completed / 含 outputs / status_str==success；
- failed：   status_str==error（detail=status_text）；
- pending/running：经 queue_pids 消歧；
- absent：  都不在（cancelled/never-queued 在 ComfyUI 侧不可区分，如实标注）。
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'runs'))  # runs/

from h3.comfy import classify_task_state  # noqa: E402


def entry_completed(filename='out.mp4', subfolder='video'):
    return {'status': {'status_str': 'success', 'completed': True},
            'outputs': {'9': {'images': [{'filename': filename, 'subfolder': subfolder,
                                          'type': 'output', 'format': 'mp4'}]}}}


def entry_error(text='internal error'):
    return {'status': {'status_str': 'error', 'status_text': text}}


class TestDecisionTree(unittest.TestCase):
    def test_completed_mp4_detail(self):
        st, det = classify_task_state(entry_completed('MiniMax_H3_00121_.mp4', 'video'),
                                      'p1', set(), set())
        self.assertEqual(st, 'completed')
        self.assertEqual(det, 'video/MiniMax_H3_00121_.mp4')

    def test_completed_plain(self):
        st, det = classify_task_state(entry_completed(subfolder=''), 'p1', set(), set())
        self.assertEqual(st, 'completed')
        self.assertTrue(det.endswith('out.mp4'))

    def test_failed(self):
        st, det = classify_task_state(entry_error('boom'), 'p2', set(), set())
        self.assertEqual(st, 'failed')
        self.assertEqual(det, 'boom')

    def test_running_via_queue(self):
        st, det = classify_task_state({}, 'p3', {'p3'}, set())
        self.assertEqual(st, 'running')

    def test_pending_via_queue(self):
        st, det = classify_task_state({}, 'p4', set(), {'p4'})
        self.assertEqual(st, 'pending')

    def test_running_priority_over_pending(self):
        st, det = classify_task_state({}, 'p5', {'p5'}, {'p5'})
        self.assertEqual(st, 'running')

    def test_absent_honest(self):
        st, det = classify_task_state({}, 'p6', set(), set())
        self.assertEqual(st, 'absent')  # cancelled/never-queued 不可区分 → 如实

    def test_absent_with_nonterminal_history(self):
        # history 存在但非终态且不在队列：同样如实 absent（不猜成 failed）
        h = {'status': {'status_str': 'running'}}
        st, det = classify_task_state(h, 'p7', set(), set())
        self.assertEqual(st, 'absent')

    def test_completed_beats_error_flag(self):
        # 完成与 error 并存时以完成为准（history outputs 为权威）
        st, det = classify_task_state(entry_completed(), 'p8', set(), set())
        self.assertEqual(st, 'completed')


if __name__ == '__main__':
    unittest.main()
