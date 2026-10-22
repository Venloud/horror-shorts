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

    def test_camera_push_is_opt_in(self):
        image = Image.new("RGBA", (1080, 1920), (25, 25, 30, 255))
        d = ImageDraw.Draw(image)
        d.rectangle((180, 150, 320, 510), fill=(255, 30, 40, 255))
        self.assertIs(noir.cinematic_camera(image, "none", 1.2, 2.0), image)
        self.assertIsNotNone(ImageChops.difference(
            noir.cinematic_camera(image, "subtle_push", 0.0, 2.0),
            noir.cinematic_camera(image, "subtle_push", 1.8, 2.0)).getbbox())

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

    def test_no_generation_or_external_services_in_toolkit(self):
        src = (ROOT / "pipeline" / "noir.py").read_text().lower()
        for disallowed in ("from openmontage", "import openmontage",
                           "fal.ai", "cloudflare_api_token", "publish.py"):
            self.assertNotIn(disallowed, src)


if __name__ == "__main__":
    unittest.main()
