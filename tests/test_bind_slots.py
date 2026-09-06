"""book-19 P1.5 补丁单测：bind_images_to_template 自动启用+接线前 N 槽（agent 全链真机暴露的缺口）。

纯本地（复制真实模板到临时副本），无网络。
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'runs'))  # runs/

from h3 import refimage as _refimg  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
TPL = REPO / 'workflows' / 'remote_workflows' / 'video_minimax_h3_r2v.json'


def _load(p):
    return json.loads(p.read_text(encoding='utf-8-sig'))


def _wired_rows(data):
    tgt = next(n for n in data['nodes'] if n.get('type') == 'MiniMaxH3ReferenceToVideo')
    return {i.get('name'): i.get('link') for i in tgt.get('inputs', [])
            if str(i.get('name') or '').startswith('ref_images.ref_image_')}


class TestBindSlots(unittest.TestCase):
    def _tmp_tpl(self):
        td = tempfile.TemporaryDirectory()
        tmp = Path(td.name) / 'video_minimax_h3_r2v.json'
        tmp.write_bytes(TPL.read_bytes())
        return td, tmp

    def test_bind_four_images_wires_all(self):
        td, tmp = self._tmp_tpl()
        try:
            _refimg.bind_images_to_template(
                'r2v', ['aa.png', 'bb.png', 'cc.png', 'dd.png'], template=tmp)
            data = _load(tmp)
            rows = _wired_rows(data)
            wired = [k for k, v in rows.items() if v is not None]
            self.assertEqual(wired, ['ref_images.ref_image_0', 'ref_images.ref_image_1',
                                     'ref_images.ref_image_2', 'ref_images.ref_image_3'])
            loads = [n for n in data['nodes'] if n.get('type') == 'LoadImage' and n.get('mode') == 0]
            self.assertEqual(len(loads), 4)
            firsts = [n['widgets_values'][0] for n in loads]
            self.assertEqual(firsts, ['aa.png', 'bb.png', 'cc.png', 'dd.png'])
        finally:
            td.cleanup()

    def test_bind_fewer_images_after_many_keeps_wiring(self):
        td, tmp = self._tmp_tpl()
        try:
            _refimg.bind_images_to_template('r2v', ['aa.png', 'bb.png', 'cc.png', 'dd.png'], template=tmp)
            _refimg.bind_images_to_template('r2v', ['zz.png', 'yy.png'], template=tmp)
            data = _load(tmp)
            rows = _wired_rows(data)
            wired = [k for k, v in rows.items() if v is not None]
            self.assertEqual(len(wired), 4)  # 已接线不丢；仅换前 2 图
            loads = [n for n in data['nodes'] if n.get('type') == 'LoadImage' and n.get('mode') == 0]
            self.assertEqual(loads[0]['widgets_values'][0], 'zz.png')
            self.assertEqual(loads[1]['widgets_values'][0], 'yy.png')
            self.assertEqual(loads[2]['widgets_values'][0], 'cc.png')
        finally:
            td.cleanup()

    def test_template_file_untouched(self):
        before = TPL.read_bytes()
        td, tmp = self._tmp_tpl()
        try:
            _refimg.bind_images_to_template('r2v', ['aa.png', 'bb.png', 'cc.png', 'dd.png'], template=tmp)
        finally:
            td.cleanup()
        self.assertEqual(TPL.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
