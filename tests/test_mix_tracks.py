"""四轮审阅修正：mix_tracks 输出电平护栏（覆盖产物，非裸 ffmpeg 语义）。"""
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


@unittest.skipUnless(FFMPEG, "无 ffmpeg（Windows 跳过；spark 全量跑）")
class TestMixTracksOutput(unittest.TestCase):
    def _tone(self, path, freq, dur=2.0):
        subprocess.run([FFMPEG, "-y", "-v", "error", "-f", "lavfi",
                        "-i", "sine=frequency=" + str(freq) + ":duration=" + str(dur),
                        "-v", "error", "-c:a", "pcm_s16le", str(path)], check=True, capture_output=True)

    def _band_db(self, path, filt):
        r = subprocess.run([FFMPEG, "-i", str(path), "-af", filt + ",volumedetect", "-f", "null", "-"],
                           capture_output=True, text=True)
        m = re.search(r"mean_volume: ([0-9.\-]+)", r.stderr or "")
        if not m:
            raise AssertionError("volumedetect 输出缺失：" + (r.stderr or "")[-160:])
        return float(m.group(1))

    def test_main_not_silent_and_bed_db_ratio(self):
        with tempfile.TemporaryDirectory() as dd:
            d = Path(dd)
            main = d / "m.wav"; self._tone(main, 400)
            bed = d / "b.wav"; self._tone(bed, 2400)
            src = d / "v.mp4"
            subprocess.run([FFMPEG, "-y", "-v", "error", "-f", "lavfi",
                            "-i", "color=c=blue:s=160x90:d=2", "-c:v", "libx264", str(src)],
                           check=True, capture_output=True)
            from h3 import postprocess as pp
            o1 = d / "mixed0.mp4"
            o2 = d / "mixed12.mp4"
            pp.mix_tracks(src, o1, main, bed=bed, main_db=0.0, bed_db=0.0)
            pp.mix_tracks(src, o2, main, bed=bed, main_db=0.0, bed_db=-12.0)
            def _audio(p):
                w = d / (p.stem + ".wav")
                subprocess.run([FFMPEG, "-y", "-v", "error", "-i", str(p), "-vn", "-c:a", "pcm_s16le", str(w)],
                               check=True, capture_output=True)
                return w
            a1, a2 = _audio(o1), _audio(o2)
            # 1) 主轨（400Hz，lowpass 800）未被静音——r3 原 bug（volume=0.0 裸数=静音）的直接护栏
            main1 = self._band_db(a1, "lowpass=f=800")
            main2 = self._band_db(a2, "lowpass=f=800")
            self.assertGreater(main1, -60.0, "主轨疑似静音（volume 单位 bug 复发？）")
            # 2) 边带比值（bed/main，增益可抵消；loudnorm 整体归一不再干扰）+ 内两档差≈bed_db 差
            bed1 = self._band_db(a1, "highpass=f=1500")
            bed2 = self._band_db(a2, "highpass=f=1500")
            r0 = bed1 - main1
            r12 = bed2 - main2
            self.assertAlmostEqual(r0 - r12, 12.0, delta=2.0,
                                   msg="底轨 dB 未生效: ratio %.1f vs %.1f" % (r0, r12))


if __name__ == "__main__":
    unittest.main()