"""Regression checks for the Night Files non-destructive full-body asset standard."""
import sys
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from normalize_character_poses import (
    W, H, GROUND_Y, alpha_bbox, normalize_pose, validate_alpha,
)


def fixture(wide=False):
    im = Image.new("RGBA", (1024, 1536), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    cx = 512
    d.ellipse((cx-145, 100, cx+145, 390), fill="white", outline="black", width=10)
    d.polygon([(cx-100, 398), (cx+100, 398), (cx+110, 870), (cx-110, 870)], fill="black")
    d.polygon([(cx-25, 405), (cx+25, 405), (cx, 580)], fill="white")
    d.polygon([(cx, 430), (cx-15, 520), (cx+15, 520)], fill="#ff2233")
    d.rectangle((cx-80, 870, cx-18, 1330), fill="black")
    d.rectangle((cx+18, 870, cx+80, 1330), fill="black")
    if wide:
        d.rectangle((cx-455, 525, cx+455, 630), fill="black")
    return im


class PoseNormalizeTests(unittest.TestCase):
    def test_transparent_canvas_and_foot_alignment(self):
        ref = fixture()
        result, qa = normalize_pose(ref, ref)
        self.assertEqual(result.size, (W, H))
        self.assertEqual(result.mode, "RGBA")
        self.assertEqual(result.getpixel((0, 0))[3], 0)
        self.assertEqual(alpha_bbox(result)[3], GROUND_Y)
        self.assertEqual(qa["quality"], "pass")

    def test_wide_pose_cannot_crop(self):
        ref = fixture()
        result, qa = normalize_pose(fixture(wide=True), ref)
        x0, _, x1, y1 = alpha_bbox(result)
        self.assertGreaterEqual(x0, 32)
        self.assertLessEqual(x1, W - 32)
        self.assertEqual(y1, GROUND_Y)
        self.assertIn(qa["quality"], ("pass", "review_required"))

    def test_opaque_sources_rejected(self):
        with self.assertRaisesRegex(ValueError, "transparent"):
            validate_alpha(Image.new("RGBA", (1024, 1536), (0, 0, 0, 255)))

    def test_original_pixel_bytes_untouched(self):
        ref = fixture()
        data_before = ref.tobytes()
        out, _ = normalize_pose(ref, ref)
        self.assertEqual(ref.tobytes(), data_before)
        self.assertIsNot(ref, out)


if __name__ == "__main__":
    unittest.main()
