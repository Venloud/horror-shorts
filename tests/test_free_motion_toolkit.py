"""Free, original Night Files visual toolkit regression tests.

No API calls, no video uploads, no social or buffer operations, no paid dependencies.
"""
import sys
import unittest
from pathlib import Path
from PIL import Image, ImageDraw, ImageChops

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))
import noir
import explainer


class CinematicToolTests(unittest.TestCase):
    def setUp(self):
        self.ctx = {"accent": (240, 23, 103), "seed": 3, "tone": "midnight", "words": []}

    def test_cinematic_templates_render_and_animate(self):
        examples = (
            ("photo_scan", {"text": "THE PHOTOGRAPH", "count": 2, "accent": "PHOTOGRAPH"}),
            ("clock_stop", {"text": "CLOCK STOPPED"}),
            ("shadow_reveal", {"text": "TWO SHADOWS", "count": 2, "accent": "SHADOWS"}),
        )
        for name, fields in examples:
            with self.subTest(template=name):
                start = noir.render(name, fields, 0.05, 2.5, self.ctx)
                end = noir.render(name, fields, 1.7, 2.5, self.ctx)
                self.assertEqual(start.mode, "RGBA")
                self.assertEqual(start.size, (1080, 1920))
                self.assertIsNotNone(ImageChops.difference(start, end).getbbox(),
                                     f"{name} rendered identical static frames")

    def test_any_clock_time_is_accurate(self):
        import math

        examples = (
            ({"kicker": "MIDNIGHT", "text": "CLOCK STOPPED"}, "12:00 AM", -90, -90),
            ({"kicker": "NOON", "text": "STOPPED AT NOON"}, "12:00 PM", -90, -90),
            ({"time": "3:15 PM"}, "3:15 PM", 7.5, 0),
            ({"time": "6:30 AM"}, "6:30 AM", 105, 90),
            ({"kicker": "CLOCK", "text": "TIME UNKNOWN"}, "", 215, -30),
        )
        for fields, resolved, hour_degrees, minute_degrees in examples:
            with self.subTest(fields=fields):
                self.assertEqual(noir._resolve_clock_time(fields), resolved)
                hr, minute = noir._clock_angles(resolved)
                self.assertAlmostEqual(math.degrees(hr), hour_degrees, places=4)
                self.assertAlmostEqual(math.degrees(minute), minute_degrees, places=4)
        # When a narration label explicitly states midnight, both fixed
        # hour and minute hands must aim at the 12 marker, regardless of story.
        final = noir.render("clock_stop", {"kicker": "MIDNIGHT", "text": "CLOCK STOPPED"},
                            1.6, 2.0, self.ctx)
        self.assertEqual(final.size, (1080, 1920))

    def test_freehand_ring_contains_every_target_corner(self):
        # This check is about targeting accuracy, not roundness.
        def inside(point, polygon):
            x, y = point
            count = 0
            for a, b in zip(polygon, polygon[1:] + polygon[:1]):
                if ((a[1] > y) != (b[1] > y)):
                    edge = a[0] + (y - a[1]) * (b[0] - a[0]) / (b[1] - a[1])
                    if edge > x:
                        count += 1
            return count % 2 == 1

        for bounds in ((320, 550, 480, 970), (421, 877, 610, 1203),
                       (120, 160, 340, 340), (570, 900, 610, 940)):
            for seed in (0, 7, 11):
                with self.subTest(bounds=bounds,seed=seed):
                    vertices = noir._focus_ring_points(bounds, seed=seed)
                    x0, y0, x1, y1 = bounds
                    for corner in ((x0,y0),(x1,y0),(x1,y1),(x0,y1)):
                        self.assertTrue(inside(corner, vertices),
                            f"Ring misses {corner} for target {bounds}")

    def test_camera_push_is_opt_in(self):
        image = Image.new("RGBA", (1080, 1920), (25, 25, 30, 255))
        d = ImageDraw.Draw(image)
        d.rectangle((180, 150, 320, 510), fill=(255, 30, 40, 255))
        self.assertIs(noir.cinematic_camera(image, "none", 1.2, 2.0), image)
        self.assertIsNotNone(ImageChops.difference(
            noir.cinematic_camera(image, "subtle_push", 0.0, 2.0),
            noir.cinematic_camera(image, "subtle_push", 1.8, 2.0)).convert("RGB").getbbox())

    def test_storyboard_rejects_fabricated_counts_or_subjects(self):
        def ctx(low, said):
            return {"said": said, "low": low, "cast": {},
                    "locs": [{"name": "empty"}], "loc_names": {"empty": "empty"},
                    "ins": {}, "dates": 0}
        self.assertIsNone(explainer._valid_graphic(
            {"template": "shadow_reveal", "fields": {"text": "TWO SHADOWS", "count": 2}},
            0, ctx("one shadow", {1})))
        self.assertIsNone(explainer._valid_graphic(
            {"template": "clock_stop", "fields": {"text": "CLOCK STOPPED"}},
            0, ctx("someone looked at their phone", set())))
        self.assertIsNone(explainer._valid_graphic(
            {"template": "photo_scan", "fields": {"text": "A PHOTOGRAPH"}},
            0, ctx("a suitcase moved", set())))
        good = explainer._valid_graphic(
            {"template": "shadow_reveal", "fields": {"text": "TWO SHADOWS", "count": 2}},
            0, ctx("two shadows appeared", {2}))
        self.assertEqual(good["fields"]["count"], 2)

    def test_existing_mixer_supports_short_effect_cues(self):
        import tempfile
        import numpy as np
        import soundfile as sf
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as temp:
            voice = Path(temp) / "voice.wav"
            output = Path(temp) / "mixed.wav"
            rate = 16000
            sf.write(voice, np.zeros(rate // 2, dtype=np.float32), rate)
            tone = np.ones(rate, dtype=np.float32) * 0.1
            with patch.object(explainer, "_load_sfx", return_value=tone):
                explainer._mix_audio({"path": str(voice)}, 0.5,
                                     [(0.0, "clock_ticking", 1.0, 0.10)], output)
            sound, _ = sf.read(output)
            self.assertGreater(abs(sound[:100]).sum(), 0)
            self.assertLess(abs(sound[int(.12*rate):]).max(), 0.0001)

    def test_no_generation_or_external_services_in_toolkit(self):
        src = (ROOT / "pipeline" / "noir.py").read_text().lower()
        for disallowed in ("from openmontage", "import openmontage",
                           "fal.ai", "cloudflare_api_token", "publish.py"):
            self.assertNotIn(disallowed, src)


if __name__ == "__main__":
    unittest.main()
