"""Offline regression tests for experimental scene repair bookkeeping."""
import json
import tempfile
import unittest
from pathlib import Path
from pipeline.scene_repair import build, invalidate, digest

class SceneRepairTests(unittest.TestCase):
    def test_missing_and_present_visuals(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            (work / "images").mkdir()
            (work / "images" / "00.png").write_bytes(b"fake-image")
            manifest = build({"title": "Test", "scenes": [{"narration": "first"}, {"narration": "second"}]}, work)
            self.assertEqual([x["status"] for x in manifest["scenes"]], ["ready", "missing_visual"])
            self.assertEqual(manifest["scenes"][0]["narration_hash"], digest("first"))
            self.assertEqual(manifest["scenes"][1]["narration_hash"], digest("second"))

    def test_invalidate_only_selected_scene(self):
        manifest = {"scenes": [{"visual_dirty": False, "audio_dirty": False, "status": "ready"} for _ in range(3)]}
        invalidate(manifest, 1, "audio")
        self.assertEqual(manifest["scenes"][0]["status"], "ready")
        self.assertTrue(manifest["scenes"][1]["audio_dirty"])
        self.assertFalse(manifest["scenes"][1]["visual_dirty"])
        self.assertEqual(manifest["scenes"][2]["status"], "ready")

    def test_invalid_index(self):
        with self.assertRaises(ValueError):
            invalidate({"scenes": []}, 0, "visual")

if __name__ == "__main__":
    unittest.main()
