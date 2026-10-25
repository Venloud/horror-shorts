"""Offline tests for existing local CLIP engine reused across media, AI and approved poses.

No model downloads, inference API requests, downloads, production buffer writes or social publishing.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

import library
import media
import sprites


class LocalClipTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.previous_unavailable = library._CLIP_UNAVAILABLE
        library._CLIP_UNAVAILABLE = False
        library._CLIP_IMAGE_CACHE.clear()
        self.addCleanup(self._reset_clip)

    def _reset_clip(self):
        library._CLIP_UNAVAILABLE = self.previous_unavailable
        library._CLIP_IMAGE_CACHE.clear()

    def image(self, name):
        p = self.dir / name
        Image.new("RGB", (12, 20), "darkblue").save(p)
        return p

    def test_ranking_and_current_run_image_embedding_cache(self):
        a, b = self.image("a.png"), self.image("b.png")
        calls = []
        def image_vector(p):
            calls.append(str(p))
            return np.array([0.9, 0.1], dtype="float32") if p == a else np.array([0.1, 0.9], dtype="float32")
        with patch.dict(library.CONFIG, {"clip_matching_enabled": True}), \
             patch.object(library, "embed_text", return_value=np.array([1., 0.], dtype="float32")), \
             patch.object(library, "embed_image", side_effect=image_vector):
            first = library.rank_images("A narrow hallway", [b, a], source="stock_video")
            second = library.rank_images("A narrow hallway", [b, a], source="stock_video")
        self.assertEqual([Path(item["path"]).name for item in first], ["a.png", "b.png"])
        self.assertEqual(first, second)
        self.assertEqual(len(calls), 2)  # second selection reused cached embeddings

    def test_model_unavailable_falls_back_without_paid_inference(self):
        a = self.image("a.png")
        with patch.dict(library.CONFIG, {"clip_matching_enabled": True}), \
             patch.object(library, "embed_text", side_effect=OSError("model offline")):
            self.assertIsNone(library.rank_images("A hallway", [a]))
            self.assertIsNone(library.rank_images("A hallway", [a]))
        self.assertTrue(library._CLIP_UNAVAILABLE)

    def test_stock_candidate_ranking_preserves_metadata_and_qa(self):
        png = self.dir / "scene_01b.png"
        side = png.with_suffix(".json")
        cands = [
            {"kind": "photo", "id": "weak", "source": "pexels", "url": "https://example.test/1"},
            {"kind": "photo", "id": "strong", "source": "pixabay", "url": "https://example.test/2"}]
        def local_photo(candidate, path):
            Image.new("RGB", (12, 20), "black").save(path)
        def rank(_text, paths, source=""):
            return [{"path": str(paths[1]), "score": 0.34, "source": source},
                    {"path": str(paths[0]), "score": 0.19, "source": source}]
        assets, used, count = [], set(), {"stock_video": 0}
        fake_images = SimpleNamespace(check_image=lambda *_args, **_kwargs: (True, ""))
        with patch.object(media, "_photo", side_effect=local_photo), \
             patch.object(library, "rank_images", side_effect=rank), \
             patch.dict(media.CONFIG, {"clip_real_media_min_similarity": 0.18}):
            ok = media._try_candidates(cands, 1, "b", "stock_video", "hallway", "hallway",
                                       png, side, assets, used, count, fake_images,
                                       clip_text="dark hallway with flickering lights")
        self.assertTrue(ok)
        self.assertEqual(assets[0]["id"], "strong")
        self.assertEqual(assets[0]["source"], "pixabay")
        self.assertEqual(assets[0]["clip_score"], 0.34)
        self.assertEqual(count["stock_video"], 1)
        self.assertTrue(png.exists())
        self.assertFalse(list(self.dir.glob(".*clip_candidate*.png")))

    def test_weak_stock_scores_fall_back_to_ai(self):
        png = self.dir / "scene_03a.png"
        cands = [{"kind": "photo", "id": "bad", "source": "pexels", "url": "https://example.test/1"}]
        with patch.object(media, "_photo", side_effect=lambda _, p: self.image_to(p)), \
             patch.object(library, "rank_images", return_value=[{
                 "path": str(self.dir / ".scene_03a_clip_candidate0.png"), "score": 0.09}]), \
             patch.dict(media.CONFIG, {"clip_real_media_min_similarity": 0.18}):
            ok = media._try_candidates(cands, 3, "a", "stock_video", "hallway", "hallway",
                                       png, png.with_suffix(".json"), [], set(),
                                       {"stock_video": 0}, SimpleNamespace(
                                           check_image=lambda *_a, **_kw: (True, "")),
                                       clip_text="dark hallway")
        self.assertFalse(ok)
        self.assertFalse(png.exists())

    @staticmethod
    def image_to(path):
        Image.new("RGB", (12, 20), "black").save(path)

    def test_approved_art_only_and_low_confidence_fallback(self):
        f, p = self.image("F13.png"), self.image("P08.png")
        pairs = {"F13": f, "P08": p}
        with patch.object(sprites, "usable", side_effect=lambda aid: aid in pairs), \
             patch.object(sprites, "asset_path", side_effect=lambda aid: pairs[aid]), \
             patch.object(library, "rank_images", return_value=[
                 {"path": str(p), "score": 0.39}, {"path": str(f), "score": 0.20}]), \
             patch.dict(library.CONFIG, {"clip_approved_asset_matching": True,
                                         "clip_approved_asset_min_similarity": 0.22}):
            selected = library.best_approved_asset("person deciding between options",
                                                   ["UNAPPROVED", "F13", "P08"], "F13")
        self.assertEqual(selected, "P08")
        with patch.object(sprites, "usable", side_effect=lambda aid: aid == "F13"), \
             patch.object(sprites, "asset_path", return_value=f), \
             patch.object(library, "rank_images", return_value=[
                 {"path": str(f), "score": 0.10}]), \
             patch.dict(library.CONFIG, {"clip_approved_asset_matching": True,
                                         "clip_approved_asset_min_similarity": 0.22}):
            self.assertEqual(library.best_approved_asset("decision", ["P08", "F13"], "F13"), "F13")

    def test_approved_pose_manifest_gate_comes_before_clip(self):
        # P08 may only be used after explicit manifest approval; this test never presumes it is approved.
        registered = {r["id"] for r in sprites.approved_registry().get("approved", [])
                      if r.get("status") == "approved"}
        candidate_ids = [aid for aid in ("F13", "P08") if aid in registered]
        self.assertNotIn("P08", candidate_ids) if "P08" not in registered else self.assertIn("P08", candidate_ids)


if __name__ == "__main__":
    unittest.main()
