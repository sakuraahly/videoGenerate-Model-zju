"""book-19 S12 单测：一次性共享授权（grants.json 原子写/轮末失效/TTL/启发式/共享分支/随会话清）。

纯函数级测试（Windows 无需 ffmpeg/qwen_agent）：refimage.grant_* / cmd_list 共享分支 /
tools.explicit_authorization / session_cleanup 随删 grants。
"""
import io
import json
import os
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'runs'))  # runs/
from h3 import refimage  # noqa: E402
from runs.agent import session_cleanup  # noqa: E402

CID_A = '20260101_000000_ab12'   # 目标会话
CID_B = '20260102_000000_cd34'   # 发起会话


class TestGrantStore(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)
        self._old_env_root = os.environ.get('VIDEOGEN_PROJECT_ROOT')
        os.environ['VIDEOGEN_PROJECT_ROOT'] = str(self.tmp)

    def tearDown(self):
        if self._old_env_root is None:
            os.environ.pop('VIDEOGEN_PROJECT_ROOT', None)
        else:
            os.environ['VIDEOGEN_PROJECT_ROOT'] = self._old_env_root
        self._td.cleanup()

    def test_grant_issue_atomic_fields(self):
        g = refimage.grant_issue(CID_A, CID_B, 7, ttl=3600)
        self.assertEqual(g['target_cid'], CID_A)
        self.assertEqual(g['src_cid'], CID_B)
        self.assertEqual(g['turn_id'], 7)
        self.assertFalse(g['used'])
        p = refimage._grant_path(CID_A)
        self.assertTrue(p.exists())
        self.assertFalse(p.with_name(p.name + '.tmp').exists())  # 原子写无残留
        self.assertEqual(json.loads(p.read_text(encoding='utf-8'))['turn_id'], 7)

    def test_grant_check_ok_same_turn(self):
        refimage.grant_issue(CID_A, CID_B, 7)
        st, _ = refimage.grant_check(CID_A, turn_id='7')
        self.assertEqual(st, 'ok')

    def test_grant_check_stale_turn(self):
        refimage.grant_issue(CID_A, CID_B, 7)
        st, detail = refimage.grant_check(CID_A, turn_id='8')
        self.assertEqual(st, 'stale_turn')
        self.assertIn('轮末', detail)

    def test_grant_check_expired(self):
        refimage.grant_issue(CID_A, CID_B, 7, ttl=3600)
        p = refimage._grant_path(CID_A)
        d = json.loads(p.read_text(encoding='utf-8'))
        d['expires'] = time.time() - 60
        p.write_text(json.dumps(d), encoding='utf-8')
        st, detail = refimage.grant_check(CID_A, turn_id='7')
        self.assertEqual(st, 'expired')
        self.assertIn('过期', detail)

    def test_grant_check_missing_and_no_turn(self):
        st, _ = refimage.grant_check(CID_A, turn_id='7')
        self.assertEqual(st, 'missing')
        refimage.grant_issue(CID_A, CID_B, 7)
        st, _ = refimage.grant_check(CID_A, turn_id='')   # 无轮次 -> 拒绝（fail closed）
        self.assertEqual(st, 'no_turn')

    def test_normalize_session_shared_passthrough(self):
        v = refimage.normalize_session('shared-' + CID_A, 'cur')
        self.assertEqual(v, 'shared-' + CID_A)

    def test_cmd_grant_validation(self):
        self.assertEqual(refimage.cmd_grant('bad', CID_B, 7), 3)        # 格式无效
        self.assertEqual(refimage.cmd_grant(CID_A, '', ''), 3)          # 缺 turn
        self.assertEqual(refimage.cmd_grant(CID_A, CID_A, 7), 3)        # 自我授权


class TestListSharedBranch(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)
        self._old_env_root = os.environ.get('VIDEOGEN_PROJECT_ROOT')
        os.environ['VIDEOGEN_PROJECT_ROOT'] = str(self.tmp)
        # rows 与 batch_map 打桩（跨会话归属由 name 前缀 sha 决定）
        self._rows_orig = refimage._rows
        self._map_orig = refimage._load_batch_map
        name_tgt = 'deadbeef_客厅.png'
        name_oth = 'cafebabe_另一会话.png'
        self.rows = [
            {'pool': 'up', 'name': name_tgt, 'full': str(self.tmp / name_tgt),
             'size': 100, 'mtime': time.time(), 'kind': 'image'},
            {'pool': 'up', 'name': name_oth, 'full': str(self.tmp / name_oth),
             'size': 100, 'mtime': time.time(), 'kind': 'image'},
        ]
        self.batch_map = {
            'deadbeef_1234': {'bid': 'b1', 'cids': {CID_A}},
            'cafebabe_5678': {'bid': 'b2', 'cids': {CID_B}},
        }
        refimage._rows = lambda dirs: self.rows
        refimage._load_batch_map = lambda: self.batch_map

    def tearDown(self):
        refimage._rows = self._rows_orig
        refimage._load_batch_map = self._map_orig
        if self._old_env_root is None:
            os.environ.pop('VIDEOGEN_PROJECT_ROOT', None)
        else:
            os.environ['VIDEOGEN_PROJECT_ROOT'] = self._old_env_root
        self._td.cleanup()

    def _list(self, session, turn_id='7'):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = refimage.cmd_list(refimage.comfy_dirs(), session=session, turn_id=turn_id)
        return rc, buf.getvalue()

    def test_shared_without_grant_denied(self):
        rc, out = self._list('shared-' + CID_A)
        self.assertEqual(rc, 0)
        self.assertIn('共享授权', out)
        self.assertIn('未签发授权', out)

    def test_shared_with_grant_filters_by_target(self):
        refimage.grant_issue(CID_A, CID_B, 7)
        rc, out = self._list('shared-' + CID_A)
        self.assertEqual(rc, 0)
        self.assertIn('共享授权（一次性，轮末失效）: 会话过滤 ' + CID_A, out)
        self.assertIn('客厅', out)
        self.assertNotIn('另一会话', out)  # 目标会话外的素材不得透出

    def test_shared_stale_turn_denied(self):
        refimage.grant_issue(CID_A, CID_B, 7)
        rc, out = self._list('shared-' + CID_A, turn_id='8')
        self.assertEqual(rc, 0)
        self.assertIn('轮末失效', out)

    def test_shared_expired_denied(self):
        refimage.grant_issue(CID_A, CID_B, 7)
        p = refimage._grant_path(CID_A)
        d = json.loads(p.read_text(encoding='utf-8'))
        d['expires'] = time.time() - 10
        p.write_text(json.dumps(d), encoding='utf-8')
        rc, out = self._list('shared-' + CID_A)
        self.assertIn('过期', out)


class TestAuthorizationHeuristic(unittest.TestCase):
    def test_true_authorization(self):
        self.assertTrue(refimage.explicit_authorization(
            '可以，用上个会话的素材吧', CID_A))
        self.assertTrue(refimage.explicit_authorization(
            '同意使用会话 ' + CID_A + ' 的客厅参考图', CID_A))
        self.assertTrue(refimage.explicit_authorization(
            '允许用第X会话的图', CID_A))

    def test_false_cases(self):
        self.assertFalse(refimage.explicit_authorization('', CID_A))       # 空
        self.assertFalse(refimage.explicit_authorization('你好', CID_A))    # 无授权词
        self.assertFalse(refimage.explicit_authorization('不能用那个素材', CID_A))  # 否定
        self.assertFalse(refimage.explicit_authorization('可以用上次的素材吗？', CID_A))  # 疑问非授权
        self.assertFalse(refimage.explicit_authorization('请列一下素材', ''))  # 无目标


class TestCleanupGrants(unittest.TestCase):
    def test_clean_removes_grants_with_session(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / (CID_A + '.jsonl')).write_text('{}' + chr(10), encoding='utf-8')
            (d / (CID_A + '.meta.json')).write_text('{}', encoding='utf-8')
            (d / (CID_A + '.grants.json')).write_text('{}', encoding='utf-8')
            stats, rc = session_cleanup.clean(chats_dir=str(d), days=0, yes=True)
            self.assertEqual(rc, 0)
            self.assertEqual(stats['deleted']['grants'], 1)
            self.assertFalse((d / (CID_A + '.grants.json')).exists())
            self.assertFalse((d / (CID_A + '.jsonl')).exists())


if __name__ == '__main__':
    unittest.main()
