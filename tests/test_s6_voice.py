"""book-19 S6 单测：音色枚举（短名→全名）+ 字幕字号参数透传签名（纯静态断言）。"""
import inspect
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'runs'))  # runs/
from h3 import tts as _tts  # noqa: E402
from h3 import postprocess as _pp  # noqa: E402


class TestVoiceAliases(unittest.TestCase):
    def test_alias_mapping(self):
        self.assertEqual(_tts.VOICE_ALIASES['xiaoxiao'], 'zh-CN-XiaoxiaoNeural')
        self.assertEqual(_tts.VOICE_ALIASES['yunxi'], 'zh-CN-YunxiNeural')
        self.assertEqual(_tts.VOICE_ALIASES['aria'], 'en-US-AriaNeural')

    def test_default_voice_female(self):
        self.assertEqual(_tts.DEFAULT_VOICE, 'zh-CN-XiaoxiaoNeural')


class TestFontSizePassthrough(unittest.TestCase):
    def test_attach_signature(self):
        sig = inspect.signature(_tts.attach_speech_and_subtitle)
        self.assertIn('fontsize', sig.parameters)
        self.assertEqual(sig.parameters['fontsize'].default, 0)

    def test_process_signature(self):
        sig = inspect.signature(_pp.process)
        self.assertIn('fontsize', sig.parameters)
        self.assertEqual(sig.parameters['fontsize'].default, 0)


if __name__ == '__main__':
    unittest.main()
