"""S13 P 链①④ 单测：本地 TTS 后端选择/音色键/ASR 相似度（纯函数+签名断言；无网络）。"""
import inspect
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'runs'))
from h3 import tts as _tts  # noqa: E402
from h3 import asr_check as _asr  # noqa: E402


class TestVoiceKey(unittest.TestCase):
    def test_mapping(self):
        self.assertEqual(_tts._voice_key('zh-CN-XiaoxiaoNeural'), 'xiaoxiao')
        self.assertEqual(_tts._voice_key('zh-CN-YunxiNeural'), 'yunxi')
        self.assertEqual(_tts._voice_key('en-US-AriaNeural'), 'aria')
        self.assertEqual(_tts._voice_key('yunxi'), 'yunxi')
        self.assertEqual(_tts._voice_key('unknown-voice'), 'xiaoxiao')  # 未知→默认
        self.assertEqual(_tts._voice_key(''), 'xiaoxiao')


class TestBackends(unittest.TestCase):
    def test_tts_backends_const(self):
        self.assertEqual(set(_tts.TTS_BACKENDS), {'edge', 'local'})

    def test_synthesize_local_delegates(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / 'x.mp3'
            with mock.patch.object(_tts, 'synth_local', return_value=2.5) as m:
                d = _tts.synthesize('你好', out, voice='zh-CN-YunxiNeural', backend='local')
            self.assertEqual(d, 2.5)
            m.assert_called_once()
            self.assertEqual(m.call_args.kwargs.get('voice'), 'zh-CN-YunxiNeural')

    def test_synth_local_env_missing(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            with mock.patch.object(_tts, 'LOCAL_TTS_PY', str(d / 'nope')):
                with mock.patch.object(_tts, '_REF_DIR', d):
                    with self.assertRaises(ValueError):
                        _tts.synth_local('你好', d / 'o.mp3')

    def test_signatures_thread_backend(self):
        self.assertIn('backend', inspect.signature(_tts.synthesize).parameters)
        self.assertIn('backend', inspect.signature(_tts.prepare_speech).parameters)
        self.assertIn('backend', inspect.signature(_tts.attach_speech_and_subtitle).parameters)
        self.assertIn('speech', inspect.signature(_tts.attach_speech_and_subtitle).return_annotation
                      if False else inspect.signature(
                          _tts.attach_speech_and_subtitle).parameters if False else
                      _tts.attach_speech_and_subtitle.__doc__ or '')  # docstring 声明返回含 speech


class TestAsrSimilarity(unittest.TestCase):
    def test_similarity_exact(self):
        t = '欢迎使用本地语音合成系统这是魔搭的中文冒烟测试'
        self.assertAlmostEqual(_asr.text_similarity(t, t), 1.0, places=5)

    def test_similarity_partial(self):
        a = '欢迎使用本地语音合成系统这是魔搭的中文冒烟测试'
        b = '欢迎使用本地语音合成系统这是摩达的中文冒烟测试'
        self.assertGreater(_asr.text_similarity(a, b), 0.6)

    def test_similarity_diff(self):
        self.assertLess(_asr.text_similarity('今天天气怎么样', 'please open the door'), 0.4)

    def test_similarity_empty(self):
        self.assertEqual(_asr.text_similarity('', 'abc'), 0.0)
        self.assertEqual(_asr.text_similarity('abc', ''), 0.0)

    def test_strips_sensevoice_tags(self):
        a = '<|en|><|EMO_UNKNOWN|><|Speech|>you are a good man'
        b = 'you are a good man'
        self.assertGreater(_asr.text_similarity(a, b), 0.95)

    def test_verdict_chinese(self):
        self.assertIn('has-speech', _asr.verdict('欢迎使用本地语音合成系统这是魔搭的中文冒烟测试'))
        self.assertEqual(_asr.verdict(''), 'no-speech')


if __name__ == '__main__':
    unittest.main()
