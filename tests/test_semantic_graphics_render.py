"""Offline real Pillow render of narrative clue graphics."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))
import noir


class SemanticNoirTests(unittest.TestCase):
    def test_clue_graphics_are_phone_size_and_not_placeholder_text(self):
        ctx = {"accent": (240, 23, 103)}
        for obj in ("newspaper", "key", "letter", "photograph", "weapon"):
            frame = noir.render("clue_object", {"object": obj, "label": obj, "missing": obj == "key"},
                                0.85, 2.5, ctx)
            self.assertEqual(frame.size, (1080, 1920))
            self.assertEqual(frame.mode, "RGBA")

    def test_location_tag_is_schematic_not_a_fake_map(self):
        frame = noir.render("location_tag", {"place": "Bavarian"}, 0.8, 2, {"accent": (240, 23, 103)})
        self.assertEqual(frame.size, (1080, 1920))

    def test_footprint_direction_draws_a_graphic(self):
        ctx = {"accent": (240, 23, 103)}
        early = noir.render("footprint_route", {}, 0.0, 2, ctx)
        late = noir.render("footprint_route", {}, 1.4, 2, ctx)
        self.assertEqual(late.size, (1080, 1920))
        self.assertNotEqual(early.tobytes(), late.tobytes())


if __name__ == "__main__":
    unittest.main()
