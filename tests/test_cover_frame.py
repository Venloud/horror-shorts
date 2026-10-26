"""Night Files-only, offline one-second cover acceptance tests."""
import io
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))
import cover_frame
from common import media_duration, run


def source_scene(folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "scene_00a.png"
    im = Image.new("RGB", (720, 1280), (35, 75, 170))
    ImageDraw.Draw(im).rectangle((220, 360, 530, 790), fill=(225, 205, 130))
    im.save(path)
    return path


def frame_at(video: Path, point: float, destination: Path) -> Image.Image:
    run(["ffmpeg", "-y", "-v", "error", "-ss", str(point), "-i", str(video),
         "-frames:v", "1", str(destination)])
    return Image.open(destination).convert("RGB")


class CoverTests(unittest.TestCase):
    def test_generates_separate_mono_cover_from_current_story_image_without_tokens(self):
        with tempfile.TemporaryDirectory() as d:
            work = Path(d)
            source_scene(work / "images")
            story = {"story_id": "case1", "title": "Footprints in Snow",
                     "true_story": True, "scenes": [{"narration": "No footprints led out."}]}
            with mock.patch.dict(os.environ, {"CLOUDFLARE_API_TOKEN": "", "CLOUDFLARE_ACCOUNT_ID": ""}):
                meta = cover_frame.make_cover(story, work, work / "images", work / "unused.mp4")
            self.assertEqual(meta["duration_seconds"], 1.0)
            self.assertEqual(meta["source"], "story_image")
            self.assertTrue(meta["illustration_not_archival_evidence"])
            self.assertTrue((work / "cover_main.png").is_file())
            self.assertTrue((work / "cover_thumb.jpg").is_file())
            self.assertEqual(json.loads((work / "cover_meta.json").read_text())["story_id"], "case1")
            with Image.open(work / "cover_main.png") as im:
                self.assertEqual(im.size, (1080, 1920))
                self.assertEqual(im.convert("RGB").getpixel((420, 500))[0],
                                 im.convert("RGB").getpixel((420, 500))[1])
            old = (work / "cover_main.png").stat().st_mtime_ns
            with mock.patch.dict(os.environ, {"CLOUDFLARE_API_TOKEN": "", "CLOUDFLARE_ACCOUNT_ID": ""}):
                cover_frame.make_cover(story, work, work / "images", work / "unused.mp4")
            self.assertEqual((work / "cover_main.png").stat().st_mtime_ns, old)

    def test_cloudflare_cover_is_requested_as_photoreal_without_paid_provider(self):
        with tempfile.TemporaryDirectory() as d:
            work = Path(d)
            im = Image.new("RGB", (640, 1024), (56, 98, 120))
            raw = io.BytesIO()
            im.save(raw, format="PNG")
            calls = []
            fake = types.SimpleNamespace(
                _STATE={"cf_out": False},
                _cloudflare=lambda prompt, seed: calls.append(prompt) or raw.getvalue(),
            )
            story = {"story_id": "generated", "title": "The Hidden Barn",
                     "scenes": [{"narration": "Someone approached the barn at night.",
                                 "image_prompt": "An isolated rural barn"}]}
            with (mock.patch.dict(os.environ, {"CLOUDFLARE_API_TOKEN": "test-only",
                                               "CLOUDFLARE_ACCOUNT_ID": "test-only"}),
                  mock.patch.dict(sys.modules, {"images": fake})):
                meta = cover_frame.make_cover(story, work, work / "empty", work / "unused.mp4")
            self.assertEqual(meta["source"], "cloudflare_workers_ai")
            self.assertEqual(len(calls), 1)
            self.assertIn("PHOTO-REALISTIC black-and-white", calls[0])
            self.assertIn("Someone approached the barn", calls[0])

    def test_exact_first_second_preserves_audio_runtime_and_main_edit(self):
        with tempfile.TemporaryDirectory() as d:
            work = Path(d)
            source_scene(work / "images")
            story = {"story_id": "video", "title": "Farmhouse",
                     "scenes": [{"narration": "The footsteps led inside."}]}
            with mock.patch.dict(os.environ, {"CLOUDFLARE_API_TOKEN": "", "CLOUDFLARE_ACCOUNT_ID": ""}):
                cover_frame.make_cover(story, work, work / "images", work / "unused.mp4")
            original = work / "video.mp4"
            run(["ffmpeg", "-y", "-v", "error",
                 "-f", "lavfi", "-i", "color=c=blue:s=1080x1920:r=30:d=2.5",
                 "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=2.5",
                 "-map", "0:v:0", "-map", "1:a:0",
                 "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                 "-c:a", "aac", "-b:a", "96k", str(original)])
            before = media_duration(original)
            cover_frame.insert_cover(original, work, work / "cover_main.png")
            self.assertAlmostEqual(before, media_duration(original), delta=0.15)
            with frame_at(original, 0.5, work / "early.png") as first:
                r, g, b = first.getpixel((500, 800))
                self.assertLessEqual(max(r, g, b) - min(r, g, b), 3,
                                     "cover must be entirely grayscale for the full first second")
            with frame_at(original, 1.5, work / "later.png") as later:
                r, g, b = later.getpixel((500, 800))
                self.assertGreater(b, r + 60, "after second 1, the original video must resume")
            self.assertIn("audio", run(["ffprobe", "-v", "error",
                                        "-show_entries", "stream=codec_type",
                                        "-of", "csv=p=0", str(original)]))

    def test_pipeline_has_one_shared_cover_stage_before_production_gate(self):
        script = (ROOT / "pipeline" / "main.py").read_text()
        self.assertIn("from cover_frame import make_cover, insert_cover", script)
        self.assertLess(script.index("video = insert_cover("), script.index('stage = "qa"'))
        self.assertLess(script.index("video = insert_cover("), script.index('stage = "production_gate"'))


if __name__ == "__main__":
    unittest.main()
