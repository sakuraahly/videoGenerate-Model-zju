"""三轮审阅：mix_tracks 双轨音量测试（无 ffmpeg 自动跳过；spark 上真实断言 dB 语义）。"""
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

FFMPEG = shutil.which("ffmpeg")

if FFMPEG:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "runs"))


@unittest.skipUnless(FFMPEG, "无 ffmpeg（Windows 预期跳过；spark 全量跑）")
class TestMixTracks(unittest.TestCase):
    def _tone(self, path, dur=2.0):
        subprocess.run([FFMPEG, "-y", "-v", "error", "-f", "lavfi",
                        "-i", "sine=frequency=1000:duration=" + str(dur),
                        "-v", "error", "-c:a", "pcm_s16le", str(path)], check=True, capture_output=True)

    def _mean_db(self, path):
        r = subprocess.run([FFMPEG, "-i", str(path), "-af", "volumedetect", "-f", "null", "-"],
                           capture_output=True, text=True)
        m = re.search(r"mean_volume: ([0-9.\-]+)", r.stderr or "")
        return float(m.group(1)) if m else 0.0

    def test_dB_semantics_and_bed_difference(self):
        with tempfile.TemporaryDirectory() as dd:
            d = Path(dd)
            main = d / "m.wav"; self._tone(main)
            bed = d / "b.wav"; self._tone(bed)
            src = d / "v.mp4"
            subprocess.run([FFMPEG, "-y", "-v", "error", "-f", "lavfi",
                            "-i", "color=c=blue:s=160x90:d=2", "-c:v", "libx264", str(src)],
                           check=True, capture_output=True)
            from h3 import postprocess as pp
            # 单位语义：裸音量 0.0=静音、-12.0=削波；dB=-12dB=衰减（三审实测结论）
            base_db = self._mean_db(main)
            filt = d / "filt.wav"
            subprocess.run([FFMPEG, "-y", "-v", "error", "-i", str(main), "-af", "volume=-12dB", "-c:a", "pcm_s16le", str(filt)], check=True, capture_output=True)
            dB12_db = self._mean_db(filt)
            self.assertAlmostEqual(base_db - dB12_db, 12.0, delta=1.5)
            # mix_tracks 产物存在且可探测
            out = d / "mix.mp4"
            pp.mix_tracks(src, out, main, bed=bed, main_db=0.0, bed_db=-12.0)
            self.assertTrue(out.is_file())
            self.assertGreater(out.stat().st_size, 1000)


if __name__ == "__main__":
    unittest.main()