"""Night Files production pipeline: checkpoints, fresh_images, parking, approved character, the explainer's visual
storytelling (story pictures -> graphics -> rare host), media sources and licences, visual QA.

Mocks and saved fixtures only: no Gemini / Cloudflare / Pexels / Pixabay / Wikimedia / TikTok / buffer call, no
production build, nothing published. The Actions cache is simulated by FakeActionsCache (actions/cache rules).
  python -m unittest discover -s tests -p test_night_files_pipeline.py -v
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
import yaml
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))
os.environ.setdefault("CLOUDFLARE_API_TOKEN", "test-token-not-used")

import checkpoint  # noqa: E402
import common  # noqa: E402
import explainer  # noqa: E402
import images  # noqa: E402
import library  # noqa: E402
import media  # noqa: E402
import sprites  # noqa: E402

HOST = ROOT / "assets" / "character" / "host"
FIXTURES = ROOT / "tests" / "fixtures"
AMELIA = FIXTURES / "amelia_f8f477b53755.json"


class FakeActionsCache:
    """actions/cache semantics: save(key) is immutable; restore(key, restore_keys) = exact key, else the NEWEST
    entry whose key starts with the first matching prefix."""

    def __init__(self, root: Path):
        self.root, self.order = root, []

    def save(self, key: str, path: Path) -> None:
        if key in self.order:
            return
        shutil.copytree(path, self.root / key)
        self.order.append(key)

    def restore(self, key: str, restore_keys: list[str], path: Path) -> str | None:
        hit = key if key in self.order else None
        for prefix in restore_keys:
            if hit:
                break
            hit = next((k for k in reversed(self.order) if k.startswith(prefix)), None)
        if hit:
            shutil.copytree(self.root / hit, path)
        return hit


def _story(sid="abc123def456", mode="mystery"):
    return {"story_id": sid, "title": f"Test story {sid}", "mode": mode, "setting": "a small town, 1920s",
            "scenes": [{"narration": "You open the door of the old hotel lobby.", "image_location": "lobby",
                        "image_prompt": "an old hotel lobby with a brass counter", "image_prompt_2": "a brass bell"},
                       {"narration": "The clock on the station platform stopped at midnight.",
                        "image_prompt": "an empty railway platform in fog", "image_prompt_2": "a stopped clock"},
                       {"narration": "Down by the river, the lantern is still burning. Who lit it?",
                        "image_prompt": "a muddy riverbank at night", "image_prompt_2": "a burning lantern"}],
            "locations": [{"name": "lobby", "look": "old hotel lobby with a brass counter"}]}


def _narration(story, gap=0.43):
    words, t = [], 0.0
    for i, sc in enumerate(story["scenes"]):
        for w in sc["narration"].split():
            words.append({"word": w, "start": round(t, 2), "end": round(t + 0.35, 2), "scene": i})
            t += gap
    return {"duration": round(t + 0.3, 2), "words": words, "speed": 1.1}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        ck = self.tmp / "runner" / "cache" / "checkpoint"
        self.patches = [mock.patch.object(checkpoint, "CK", ck),
                        mock.patch.object(checkpoint, "IMAGES", ck / "images"),
                        mock.patch.object(checkpoint, "FAILED", self.tmp / "repo" / "data" / "failed_stories"),
                        mock.patch.object(checkpoint, "ROOT", self.tmp / "repo"),
                        mock.patch.dict(images._STATE, {"cf_out": False}),
                        mock.patch.object(images, "check_image", lambda *a, **k: (True, "")),
                        mock.patch.object(images, "test_mode", lambda: False),
                        mock.patch("common.load_history", lambda: [])]
        for p in self.patches:
            p.start()
        self.draws, self.library_calls, self.media_calls = [], [], []

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def fake_generate(self, crash_after=None):
        """images.generate_images stand-in with the real contract: existing valid files are kept (checkpoint),
        missing shots are drawn (counted), [[scene pictures], ...] is returned."""
        def gen(story, outdir):
            out = []
            for i, sc in enumerate(story["scenes"]):
                row = []
                for l in images._letters():
                    if not sc.get(images.PROMPT_KEYS[l]):
                        continue
                    f = outdir / f"scene_{i:02d}{l}.png"
                    if not images._is_image(f):
                        if crash_after is not None and len(self.draws) >= crash_after:
                            raise RuntimeError("runner lost mid-image (simulated)")
                        self.draws.append(f.name)
                        Image.new("RGB", (576, 1024), (len(self.draws) * 30 % 255, 40, 60)).save(f)
                        story.setdefault("_shot_provider", {})[f"{i:02d}{l}"] = "cloudflare"
                    row.append(f)
                out.append(row)
            return out
        return gen

    def fake_library(self, match: set):
        def fill(story, outdir, history):
            self.library_calls.append(story["story_id"])
            for i, sc in enumerate(story["scenes"]):
                if any(m in sc["image_prompt"] for m in match):
                    f = outdir / f"scene_{i:02d}a.png"
                    Image.new("RGB", (576, 1024), (90, 90, 90)).save(f)
                    f.with_suffix(".reuse.json").write_text(json.dumps({"asset": "lib1"}))
        return fill

    def pictures(self, story, fresh: bool, crash_after=None, lib_match=frozenset()):
        with mock.patch.dict(os.environ, {"FRESH_IMAGES": "true" if fresh else "false"}), \
                mock.patch.object(images, "generate_images", self.fake_generate(crash_after)), \
                mock.patch.object(library, "fill_shots", self.fake_library(set(lib_match))), \
                mock.patch.object(media, "fill_shots", lambda s, o, h: self.media_calls.append(1) or []):
            return explainer.story_images(story, checkpoint.IMAGES)

    def first_run(self, story):
        checkpoint.start(story)
        wav = self.tmp / "narration.wav"
        wav.write_bytes(b"RIFF" + os.urandom(2000))
        n = _narration(story)
        checkpoint.save_narration(story, {**n, "path": wav})
        return n


class FreshImages(Base):
    def test_new_run_fresh_on_draws_every_scene_picture_and_skips_library(self):
        story = _story()
        self.first_run(story)
        pics = self.pictures(story, fresh=True, lib_match={"hotel"})
        self.assertEqual(len(self.draws), 6)  # 3 scenes x shots_per_scene 2, each from its own prompt
        self.assertEqual(self.library_calls, [])
        self.assertEqual(len(self.media_calls), 1)  # licensed real media is always searched first
        self.assertEqual([len(p) for p in pics], [2, 2, 2])
        self.assertTrue(all(p.name.startswith(f"scene_{i:02d}") for i, row in enumerate(pics) for p in row))

    def test_new_run_fresh_off_uses_matching_library_picture_then_generates_the_rest(self):
        story = _story()
        self.first_run(story)
        self.pictures(story, fresh=False, lib_match={"hotel"})
        self.assertEqual(len(self.draws), 5)  # the lobby came from the asset library
        self.assertEqual(self.library_calls, [story["story_id"]])

    def test_checkbox_value_reaches_the_pipeline(self):
        with mock.patch.dict(os.environ, {"FRESH_IMAGES": "false"}):
            self.assertFalse(explainer.fresh_images())
        with mock.patch.dict(os.environ, {"FRESH_IMAGES": "true"}):
            self.assertTrue(explainer.fresh_images())

    def test_ai_picture_is_cached_by_prompt_and_checksum(self):
        story = _story()
        self.first_run(story)
        self.pictures(story, fresh=True)
        meta = json.loads((checkpoint.IMAGES / "scene_01b.ai.json").read_text())
        self.assertEqual(meta["prompt"], "a stopped clock")
        self.assertEqual(meta["provider"], "cloudflare")
        self.draws.clear()
        story["scenes"][1]["image_prompt_2"] = "a cracked pocket watch"  # the shot changed: only it is redrawn
        self.pictures(story, fresh=True)
        self.assertEqual(self.draws, ["scene_01b.png"])

    def test_planner_query_in_image_source_slot_is_kept_as_query(self):
        story = _story()
        story["scenes"][0]["image_source_3"] = "old tree backyard"
        self.first_run(story)
        self.pictures(story, fresh=True)
        self.assertEqual(story["scenes"][0]["image_source_3"], "ai")
        self.assertEqual(story["scenes"][0]["image_query_3"], "old tree backyard")


class ResumeAcrossRuns(Base):
    def _two_runs(self, fresh_second: bool, lib_match=frozenset()):
        cache = FakeActionsCache(self.tmp / "actions-cache")
        story = _story()
        # ---- run 1: story + narration saved, 2 of 6 pictures drawn, the runner dies on the 3rd
        self.first_run(story)
        with self.assertRaises(RuntimeError):
            self.pictures(story, fresh=True, crash_after=2)
        self.assertEqual(checkpoint.failed_attempt(story, "explainer", "runner lost"), False)
        sid = json.loads((checkpoint.CK / "story.json").read_text())["story_id"]
        cache.save(f"ckpt-{sid}-1001-1", checkpoint.CK)  # "Save checkpoint for the next run" (if: always())
        shutil.rmtree(self.tmp / "runner")  # a NEW runner: nothing on disk
        # ---- run 2: restore by prefix, resume BEFORE picking a story
        hit = cache.restore("ckpt-restore-1002", ["ckpt-none-", "ckpt-"], checkpoint.CK)
        self.assertEqual(hit, f"ckpt-{sid}-1001-1")
        resumed = checkpoint.resume(history=[], buffered=set())
        self.assertIsNotNone(resumed)
        self.assertEqual(resumed["story_id"], sid)
        workdir = self.tmp / "work"
        workdir.mkdir()
        self.assertIsNotNone(checkpoint.load_narration(resumed, workdir))  # narration reused
        self.draws.clear()
        pics = self.pictures(resumed, fresh=fresh_second, lib_match=lib_match)
        self.assertEqual(sum(len(p) for p in pics), 6)
        self.assertEqual(len(checkpoint.attempts()), 1)
        return resumed

    def test_failed_run_resumes_with_fresh_on_and_only_draws_the_missing_pictures(self):
        s = self._two_runs(fresh_second=True)
        self.assertEqual(len(self.draws), 4)
        print(f"\n[2-run checkpoint test] run 2 resumed {s['story_id']}: narration reused, 2 pictures reused, "
              f"{len(self.draws)} drawn")

    def test_failed_run_resumes_with_fresh_off_reuses_cache_then_library(self):
        self._two_runs(fresh_second=False, lib_match={"riverbank"})
        self.assertEqual(len(self.draws), 3)  # 2 cached + the riverbank from the library

    def test_corrupt_picture_is_dropped_and_redrawn(self):
        story = _story()
        self.first_run(story)
        self.pictures(story, fresh=True)
        victim = checkpoint.IMAGES / "scene_02a.png"
        victim.write_bytes(b"not a png any more")
        self.assertIsNotNone(checkpoint.resume([], set()))  # sha256 mismatch -> deleted
        self.assertFalse(victim.exists())
        self.draws.clear()
        self.pictures(story, fresh=True)
        self.assertEqual(self.draws, ["scene_02a.png"])

    def test_corrupt_story_file_is_never_trusted(self):
        story = _story()
        self.first_run(story)
        raw = json.loads((checkpoint.CK / "story.json").read_text())
        raw["title"] = "tampered"
        (checkpoint.CK / "story.json").write_text(json.dumps(raw))
        self.assertIsNone(checkpoint.resume([], set()))
        self.assertFalse(checkpoint.CK.exists())

    def test_corrupt_narration_is_redone(self):
        story = _story()
        self.first_run(story)
        (checkpoint.CK / "narration.wav").write_bytes(b"garbage")
        self.assertIsNotNone(checkpoint.resume([], set()))
        self.assertIsNone(checkpoint.load_narration(story, self.tmp))

    def test_stale_checkpoint_from_another_story_is_cleared(self):
        self.first_run(_story("aaaaaaaaaaaa"))
        m = json.loads((checkpoint.CK / "manifest.json").read_text())
        m["story_id"] = "bbbbbbbbbbbb"
        (checkpoint.CK / "manifest.json").write_text(json.dumps(m))
        self.assertIsNone(checkpoint.resume([], set()))
        self.assertFalse((checkpoint.CK / "story.json").exists())

    def test_already_buffered_story_never_gets_a_second_video(self):
        story = _story()
        self.first_run(story)
        self.assertIsNone(checkpoint.resume([], {story["story_id"]}))  # in the buffer
        self.assertTrue((checkpoint.CK / "done.json").exists())
        self.first_run(story)
        self.assertIsNone(checkpoint.resume([{"story_id": story["story_id"], "title": "x"}], set()))  # in history

    def test_completion_only_after_validation_and_buffer(self):
        src = (ROOT / "pipeline" / "main.py").read_text()
        self.assertLess(src.index("gate_final_video(video"), src.index("buffer.add(stamp"))
        self.assertLess(src.index("buffer.add(stamp"), src.rindex("checkpoint.finish(story)"))
        self.assertEqual(src.count("checkpoint.finish("), 1)
        for wf in ("buffer_fill.yml", "daily.yml"):
            self.assertNotIn("finish_from_artifact", (ROOT / ".github" / "workflows" / wf).read_text())

    def test_shot_rules_never_rerun_on_a_resume(self):
        src = (ROOT / "pipeline" / "main.py").read_text()
        self.assertIn('if not story.get("_shot_rules_done")', src)


class Parking(Base):
    def test_three_fails_park_the_story_and_alert(self):
        story = _story()
        self.first_run(story)
        sent = []
        with mock.patch("notify.notify_text", lambda title, body, warn=False: sent.append(title)):
            self.assertFalse(checkpoint.failed_attempt(story, "narration", "boom 1"))
            self.assertFalse(checkpoint.failed_attempt(story, "explainer", "boom 2"))
            self.assertTrue(checkpoint.failed_attempt(story, "explainer", "boom 3"))
        d = checkpoint.FAILED / story["story_id"]
        for f in ("story.json", "narration.json", "assets.json", "attempts.json", "status.json"):
            self.assertTrue((d / f).exists(), f)
        att = json.loads((d / "attempts.json").read_text())
        self.assertEqual([a["stage"] for a in att], ["narration", "explainer", "explainer"])
        self.assertEqual(sent, [f"Night Files: story {story['story_id']} parked after 3 fails at stage explainer"])
        self.assertFalse(checkpoint.CK.exists())
        self.assertEqual(json.loads((d / "status.json").read_text())["status"], "parked")

    def test_retry_story_id_resumes_a_parked_story(self):
        story = _story()
        self.first_run(story)
        with mock.patch("notify.notify_text", lambda *a, **k: None):
            for k in range(3):
                checkpoint.failed_attempt(story, "explainer", f"boom {k}")
        other = _story("ffffffffffff")
        self.first_run(other)
        checkpoint.retry(story["story_id"])
        back = checkpoint.resume([], set())
        self.assertEqual(back["story_id"], story["story_id"])
        self.assertEqual(checkpoint.attempts(), [])
        self.assertEqual(json.loads((checkpoint.FAILED / other["story_id"] / "status.json").read_text())["status"],
                         "shelved")
        checkpoint.finish(back)
        self.assertEqual(json.loads((checkpoint.FAILED / story["story_id"] / "status.json").read_text())["status"],
                         "recovered")

    def test_retry_unknown_id_fails_loudly(self):
        with self.assertRaises(RuntimeError):
            checkpoint.retry("000000000000")


class ApprovedCharacter(unittest.TestCase):
    def _hashes(self):
        m = json.loads((HOST / "manifest.json").read_text())
        return {r["id"]: (hashlib.sha256((HOST / r["path"]).read_bytes()).hexdigest(), r["sha256"])
                for r in m["approved"]}

    def test_approved_assets_unchanged_by_rendering(self):
        before = self._hashes()
        for aid, (now, want) in before.items():
            self.assertEqual(now, want, aid)
        tmp = Path(tempfile.mkdtemp())
        try:
            pic = tmp / "scene_00a.png"
            Image.new("RGB", (576, 1024), (40, 44, 50)).save(pic)
            story = _story()
            segs = [{"start": 0.0, "end": 2.0, "scene": 0, "shot": {"type": "image", "scene": 0, "file": str(pic),
                                                                    "crop": "full"}}]
            for k, ex in enumerate(("worried", "shocked", "neutral")):
                segs.append({"start": 2.0 + k * 2, "end": 4.0 + k * 2, "scene": 0,
                             "shot": {"type": "host", "scene": 0, "expression": ex}})
            r = explainer.Renderer(story, _narration(story), segs, tmp)
            for s in segs:
                self.assertEqual(r.frame_at(s["start"] + 0.5).size, (1080, 1920))
            self.assertTrue(r.used_assets <= set(before))
            self.assertIn("F15", r.used_assets)  # "shocked": F16 is opaque until re-exported -> F15
            self.assertIn("M02", r.used_assets)  # every third host shot: the approved full body
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        self.assertEqual(before, self._hashes())

    def test_missing_or_changed_asset_fails_by_id(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            shutil.copytree(HOST / "masters", tmp / "masters")
            shutil.copytree(HOST / "expressions", tmp / "expressions")
            shutil.copy(HOST / "manifest.json", tmp / "manifest.json")
            (tmp / "expressions" / "F03_smiling.png").write_bytes(b"changed")
            os.remove(tmp / "masters" / "M04_back_neutral.png")
            caches = [sprites.approved_registry, sprites.asset_path, sprites.usable, sprites._trimmed,
                      sprites.full_body]
            with mock.patch.object(sprites, "DIR", tmp):
                for c in caches:
                    c.cache_clear()
                problems = " | ".join(sprites.verify_all())
                self.assertIn("F03", problems)
                self.assertIn("M04", problems)
                with self.assertRaises(sprites.MissingAsset) as e:
                    sprites.full_body("back", 900)
                self.assertEqual(e.exception.asset_id, "M04")
            for c in caches:
                c.cache_clear()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


SAMPLES = {
    "amelia_mystery": json.loads(AMELIA.read_text()),
    "lore": {"title": "The Lantern Man", "mode": "lore", "setting": "fenland villages", "story_id": "lore00000001",
             "locations": [{"name": "the fen", "look": "misty fen at night"}],
             "scenes": [{"narration": "You see a light moving across the fen where nobody walks."},
                        {"narration": "The village believed it was the Lantern Man, and you shut the door. "
                                      "Three lights followed the cart that night."},
                        {"narration": "Old Martha Reed swore she saw it on the bridge at Whittlesey Mere."},
                        {"narration": "The light stops at your window. Do you blow out your candle?"}]},
    "fiction": {"title": "Room 14", "mode": "fiction", "setting": "a roadside motel", "story_id": "fict00000001",
                "characters": [{"name": "Dana Cole"}],
                "locations": [{"name": "motel room", "look": "cheap motel room"}],
                "scenes": [{"narration": "You check in to room 14 and the key is already warm."},
                           {"narration": "Outside, the same car circles the parking lot four times."},
                           {"narration": "Dana Cole, the night clerk, says the room has been empty since nineteen "
                                         "ninety-four."},
                           {"narration": "The knock comes at three. Would you open it?"}]},
}


def _plan(story):
    n = _narration(story)
    with mock.patch.object(explainer, "_plan_call", lambda prompt: None):  # LLM off: factual auto graphics
        g = explainer.plan_graphics(story, n)
    pics = [[Path(f"/x/scene_{i:02d}a.png"), Path(f"/x/scene_{i:02d}b.png")] for i in range(len(story["scenes"]))]
    total = explainer._total(n)
    return n, g, explainer.sequence(story, n, pics, g, total), total


class ShotLists(unittest.TestCase):
    def test_three_sample_stories_tell_the_story_with_pictures_and_graphics(self):
        for name, story in SAMPLES.items():
            with self.subTest(story=name):
                n, g, segs, total = _plan(json.loads(json.dumps(story)))
                body = [s for s in segs if not s["shot"]["type"].startswith("opener")]
                secs = {k: sum(s["end"] - s["start"] for s in body if s["shot"]["type"] == k)
                        for k in ("image", "graphic", "host")}
                self.assertGreater(secs["image"] / total, 0.4)
                self.assertGreaterEqual(secs["graphic"] / total, 0.2)
                self.assertLessEqual(secs["host"] / total, 0.15 + 1e-6)
                for i in range(len(story["scenes"])):
                    mine = [s for s in body if s["scene"] == i]
                    self.assertTrue(any(s["shot"]["type"] == "image" for s in mine), f"scene {i} no picture")
                    if g[i]:  # a planned meaningful graphic is shown; no meaningful phrase = picture only (Oct 25)
                        self.assertTrue(any(s["shot"]["type"] == "graphic" for s in mine), f"scene {i} no graphic")
                    self.assertLessEqual(sum(1 for s in mine if s["shot"]["type"] == "host"), 1)
                    for s in mine:
                        if s["shot"]["type"] == "image":
                            self.assertTrue(Path(s["shot"]["file"]).name.startswith(f"scene_{i:02d}"))
                        if s["shot"]["type"] == "graphic" and s["shot"]["template"] != "closing":
                            self.assertIsNone(explainer.graphic_problem(story, i, s["shot"]))
                for a, b in zip(body, body[1:]):
                    self.assertFalse(a["shot"]["type"] == b["shot"]["type"] == "host")
                for s in body:
                    if s["shot"]["type"] == "host":
                        self.assertLessEqual(s["end"] - s["start"], 2.0 + 1e-6)
                    if s is not segs[-1]:
                        self.assertLessEqual(s["end"] - s["start"], explainer.SHOT_MAX + 0.05)
                self.assertAlmostEqual(segs[-1]["end"], total, places=2)  # no end card: the story runs to the end
                print(f"\n[shot list {name}] {len(segs)} shots, image {secs['image'] / total:.0%}, graphic "
                      f"{secs['graphic'] / total:.0%}, host {secs['host'] / total:.0%}; graphics: "
                      + ", ".join(f"{x['template']}" for gs in g for x in gs))

    def test_amelia_graphics_are_factual(self):
        story = json.loads(AMELIA.read_text())
        _, g, _, _ = _plan(story)
        flat = {(x["template"], json.dumps(x["fields"], sort_keys=True)) for gs in g for x in gs}
        years = {json.loads(f)["year"] for t, f in flat if t == "date_stamp"}
        self.assertEqual(years, {"1897", "1928", "1932", "1937", "1939"})  # every one in the narration AND ledger
        texts = {json.loads(f).get("text") for t, f in flat}
        self.assertIn("Distinguished Flying Cross", texts)
        self.assertIn("Fred Noonan", texts)
        self.assertIn("Oh, Pidge, it's just like flying!", texts)
        self.assertEqual(g[-1][-1]["template"], "closing")

    def test_graphic_with_invented_fact_is_rejected(self):
        story = json.loads(AMELIA.read_text())
        bad_year = {"template": "date_stamp", "fields": {"year": "1936", "label": ""}}
        self.assertIn("not said", explainer.graphic_problem(story, 6, bad_year))
        bad_text = {"template": "evidence", "fields": {"text": "Howland Island", "kicker": "LAST KNOWN"}}
        self.assertIn("not said", explainer.graphic_problem(story, 6, bad_text))
        ok = {"template": "evidence", "fields": {"text": "Fred Noonan", "kicker": "NAVIGATOR"}}
        self.assertIsNone(explainer.graphic_problem(story, 6, ok))

    def test_scene_without_its_own_picture_never_renders(self):
        story = _story()
        n = _narration(story)
        with mock.patch.object(explainer, "_plan_call", lambda p: None):
            g = explainer.plan_graphics(story, n)
        with self.assertRaises(explainer.ExplainerUnavailable):
            explainer.sequence(story, n, [[Path("/x/scene_00a.png")], [], [Path("/x/scene_02a.png")]], g,
                               explainer._total(n))


class MediaSources(unittest.TestCase):
    def test_licences(self):
        for ok in ("Public domain", "CC0", "CC BY 4.0", "CC BY 2.0"):
            self.assertTrue(media.license_ok(ok), ok)
        for bad in ("CC BY-SA 4.0", "CC BY-NC 2.0", "GFDL", "CC BY-ND 3.0", ""):
            self.assertFalse(media.license_ok(bad), bad)
        self.assertTrue(media.loc_rights_ok("No known restrictions on publication."))
        self.assertFalse(media.loc_rights_ok("Publication may be restricted."))
        self.assertFalse(media.loc_rights_ok("Rights status not evaluated."))
        self.assertIsNone(explainer._license_valid({"source": "wikimedia", "license": "Public domain", "url": "u"}))
        self.assertIn("not allowed", explainer._license_valid({"source": "wikimedia", "license": "CC BY-SA 4.0",
                                                               "url": "u"}))
        self.assertEqual(explainer._license_valid({"source": "pexels", "license": "Pexels License"}), "no source URL")

    def _fake_get(self, payloads):
        class R:
            def __init__(self, data):
                self.data, self.status_code = data, 200

            def raise_for_status(self):
                pass

            def json(self):
                return self.data
        return lambda url, **k: R(next(v for key, v in payloads.items() if key in url))

    def test_pexels_and_pixabay_photos_and_clips_parse(self):
        payloads = {
            "api.pexels.com/v1/search": {"photos": [{"id": 7, "width": 3000, "height": 4500, "url": "https://p/7",
                                                       "photographer": "Ann", "alt": "foggy airfield",
                                                       "src": {"large2x": "https://img/7.jpg"}}]},
            "api.pexels.com/v1/videos": {"videos": [{"id": 9, "url": "https://p/v9", "duration": 12,
                                                      "user": {"name": "Bo"},
                                                      "video_files": [{"link": "https://v/9.mp4", "width": 1080,
                                                                       "height": 1920}]}]},
            "pixabay.com/api/videos": {"hits": []},
            "pixabay.com/api/": {"hits": [{"id": 3, "largeImageURL": "https://px/3.jpg", "imageHeight": 2400,
                                            "pageURL": "https://px/3", "user": "Cy", "tags": "ocean, storm"}]},
        }
        tmp = Path(tempfile.mkdtemp())
        try:
            with mock.patch.object(media, "CACHE", tmp), mock.patch.object(media.requests, "get",
                                                                           self._fake_get(payloads)), \
                    mock.patch.dict(os.environ, {"PEXELS_API_KEY": "k", "PIXABAY_API_KEY": "k"}):
                cands = [c for prov in media.PROVIDERS["stock_video"] for c in prov("foggy airfield")]
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        self.assertEqual([(c["source"], c["kind"]) for c in cands],
                         [("pexels", "video"), ("pexels", "photo"), ("pixabay", "photo")])
        self.assertTrue(all(c["license"] in ("Pexels License", "Pixabay Content License") and c["url"]
                            for c in cands))

    def test_provider_fallback_without_keys_is_empty_not_an_error(self):
        with mock.patch.dict(os.environ, {"PEXELS_API_KEY": "", "PIXABAY_API_KEY": "", "SI_API_KEY": ""}):
            for prov in (media.pexels, media.pexels_photo, media.pixabay, media.pixabay_photo, media.smithsonian):
                self.assertEqual(prov("anything"), [])

    def test_failed_media_search_leaves_the_shot_to_ai(self):
        story = {"title": "t", "mode": "mystery", "true_story": True, "story_id": "s1",
                 "scenes": [{"narration": f"A storm {k}.", "image_prompt": "storm clouds over the sea",
                             "image_prompt_2": "dark ocean waves"} for k in range(4)]}
        tmp = Path(tempfile.mkdtemp())
        boom = mock.Mock(side_effect=RuntimeError("HTTP 503"))
        boom.__name__ = "provider_down"
        try:
            with mock.patch.dict(media.PROVIDERS, {"stock_video": (boom,), "real_photo": (boom,),
                                                   "archive_print": (boom,)}), \
                    mock.patch.object(images, "check_image", lambda *a, **k: (True, "")):
                assets = media.fill_shots(story, tmp, [])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        self.assertEqual(assets, [])
        self.assertTrue(boom.called)

    def test_amelia_shots_get_archival_searches_for_her_and_her_aircraft(self):
        story = json.loads(AMELIA.read_text())
        media.auto_tag(story)
        tags = {(i, l): (sc.get(media.SRC_KEYS[l]), sc.get(media.QUERY_KEYS[l]))
                for i, sc in enumerate(story["scenes"]) for l in images._letters()}
        self.assertEqual(tags[(0, "a")][0], "ai")  # the hook stays AI
        self.assertEqual(tags[(5, "a")], ("real_photo", "Amelia Earhart"))  # "a lone aviator beside an airplane"
        # the ledger's aircraft is never said: no Electra photo over the 1928 / 1932 flights (wrong plane, wrong era)
        self.assertNotEqual(tags[(4, "a")], ("real_photo", "Lockheed Model 10 Electra"))
        said = json.loads(AMELIA.read_text())
        said["scenes"][6]["narration"] += " Their Lockheed Electra was never found."
        said["scenes"][6]["image_prompt_2"] = "a silver twin engine airplane on a runway"
        media.auto_tag(said)
        self.assertEqual((said["scenes"][6]["image_source_2"], said["scenes"][6]["image_query_2"]),
                         ("real_photo", "Lockheed Model 10 Electra"))  # said in this scene: the real aircraft
        self.assertNotEqual(tags[(0, "b")][0], "real_photo")  # childhood shots never get an adult's photo

    def test_provenance_records_everything(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            f = tmp / "scene_03a.png"
            Image.new("RGB", (600, 1000)).save(f)
            f.with_suffix(".json").write_text(json.dumps({
                "type": "real_photo", "kind": "photo", "source": "wikimedia", "id": "wikimedia:1",
                "url": "https://commons.wikimedia.org/wiki/File:X.jpg", "author": "US Navy",
                "license": "Public domain", "query": "Amelia Earhart", "title": "File:Earhart.jpg"}))
            p = explainer.provenance_of(str(f))
            self.assertEqual((p["kind"], p["provider"], p["license"], p["query"], p["asset_id"]),
                             ("archival", "wikimedia", "Public domain", "Amelia Earhart", "wikimedia:1"))
            self.assertEqual(p["sha256"], hashlib.sha256(f.read_bytes()).hexdigest())
            self.assertIsNone(p["license_problem"])
            g = tmp / "scene_03b.png"
            Image.new("RGB", (600, 1000)).save(g)
            self.assertEqual(explainer.provenance_of(str(g))["license_problem"], "no provenance record")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class RenderAndVisualQA(unittest.TestCase):
    """A real (short) render with placeholder pictures: duration, audio, frame log, visual QA, no rail/end card."""

    def test_render_duration_audio_and_visual_qa(self):
        import soundfile as sf
        tmp = Path(tempfile.mkdtemp())
        try:
            story = _story("render000001")
            n = _narration(story, gap=0.6)
            sf.write(tmp / "n.wav", np.zeros(int(n["duration"] * 24000), dtype="float32"), 24000)
            n["path"] = tmp / "n.wav"
            pics = []
            for i in range(3):
                row = []
                for l in "ab":
                    f = tmp / f"scene_{i:02d}{l}.png"
                    Image.new("RGB", (576, 1024), (30 + 60 * i, 50, 80 if l == "a" else 140)).save(f)
                    f.with_name(f.stem + ".ai.json").write_text(json.dumps({"provider": "cloudflare", "prompt": "p"}))
                    row.append(f)
                pics.append(row)
            with mock.patch.object(explainer, "_plan_call", lambda p: None), \
                    mock.patch.dict(common.CONFIG, {"remotion_polish": False}), \
                    mock.patch("render.tail_for", lambda d: 1.0):
                g = explainer.plan_graphics(story, n)
                total = explainer._total(n)
                segs = explainer.sequence(story, n, pics, g, total)
                video, ren = explainer.render(story, n, segs, tmp, tmp)
                rep = explainer.visual_qa(story, segs, ren, video, total)
            probe = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                                               "stream=codec_type,duration", "-of", "json", str(video)],
                                              capture_output=True, text=True).stdout)
            kinds = {s["codec_type"]: float(s.get("duration") or 0) for s in probe["streams"]}
            self.assertIn("audio", kinds)
            self.assertAlmostEqual(kinds["video"], total, delta=0.1)
            self.assertAlmostEqual(kinds["audio"], total, delta=0.15)  # narration + SFX in sync with the frames
            self.assertEqual(rep["failures"], [])
            self.assertEqual(rep["rendered_frames"]["end_card"], 0)
            self.assertEqual(explainer._rail_in_video(video), 0)
            used = {s["shot"]["file"] for s in segs if s["shot"]["type"] == "image"}
            self.assertEqual(rep["media_used"]["ai_reconstruction"], len(used))  # every picture has provenance
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_visual_qa_catches_character_overuse(self):
        story = _story("qa0000000001")
        tmp = Path(tempfile.mkdtemp())
        try:
            f = tmp / "scene_00a.png"
            Image.new("RGB", (576, 1024)).save(f)
            f.with_name(f.stem + ".ai.json").write_text(json.dumps({"provider": "cloudflare", "prompt": "p"}))
            segs = [{"start": 0.0, "end": 2.0, "scene": 0, "shot": {"type": "image", "scene": 0, "file": str(f),
                                                                    "crop": "full"}},
                    {"start": 2.0, "end": 4.5, "scene": 0, "shot": {"type": "host", "scene": 0}},
                    {"start": 4.5, "end": 6.0, "scene": 0, "shot": {"type": "host", "scene": 0}}]
            ren = explainer.Renderer(story, _narration(story), segs, tmp)
            rep = explainer.visual_qa(story, segs, ren, None, 6.0)
            text = " | ".join(rep["failures"])
            for want in ("character runtime", "consecutive character shots", "character shot of 2.5s"):
                self.assertIn(want, text)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_no_progress_rail_and_no_end_card_in_the_code(self):
        jsx = (ROOT / "remotion" / "src" / "polish.jsx").read_text()
        self.assertNotIn("TimelineRail", jsx)
        self.assertNotIn("ContextMark", jsx)
        src = (ROOT / "pipeline" / "explainer.py").read_text()
        self.assertNotIn("FOLLOW FOR MORE", src)


class Workflow(unittest.TestCase):
    def test_buffer_fill_passes_checkbox_and_retry_and_saves_checkpoint_always(self):
        wf = yaml.safe_load((ROOT / ".github" / "workflows" / "buffer_fill.yml").read_text())
        inputs = wf.get(True, wf.get("on"))["workflow_dispatch"]["inputs"]
        self.assertIn("fresh_images", inputs)
        self.assertIn("retry_story_id", inputs)
        steps = wf["jobs"]["fill"]["steps"]
        make = next(s for s in steps if s.get("run", "").strip() == "cd pipeline && python main.py")
        self.assertEqual(make["env"]["FRESH_IMAGES"], "${{ inputs.fresh_images }}")
        self.assertEqual(make["env"]["RETRY_STORY_ID"], "${{ inputs.retry_story_id }}")
        self.assertEqual(make["env"]["MAKEUP_POSTS"], "0")  # a manual fill never posts
        save = next(s for s in steps if s.get("name") == "Save checkpoint for the next run")
        self.assertTrue(save["if"].startswith("always()"))
        self.assertIn("ckpt_key", save["with"]["key"])
        restore = next(s for s in steps if s.get("name") == "Restore checkpoint cache")
        self.assertEqual(restore["with"]["restore-keys"].split(),
                         ["ckpt-${{", "inputs.retry_story_id", "||", "'none'", "}}-", "ckpt-"])
        self.assertFalse(re.search(r"publish\.py", (ROOT / ".github" / "workflows" / "buffer_fill.yml").read_text()))



class FinalNarrationApproval(unittest.TestCase):
    def test_approval_is_invalidated_when_final_words_change(self):
        import story
        item = {"title": "The Disappearance", "scenes": [{"narration": "The plane vanished."}]}
        reply = {"approved": True, "reasons": [], "title_alignment": 9,
                 "narrative_logic": 9, "payoff": 9, "fact_integrity": 9}
        with mock.patch.object(story, "_json_call", return_value=reply) as judge:
            story.final_script_gate(item, "test")
            story.final_script_gate(item, "test")
            self.assertEqual(judge.call_count, 1)
            item["scenes"][0]["narration"] += " Investigators searched."
            story.final_script_gate(item, "test")
            self.assertEqual(judge.call_count, 2)

    def test_blocked_narration_stays_blocked_after_checkpoint_resume(self):
        # PR #24 review: a blocked script saved in a checkpoint must be blocked again on resume, not waved through
        # by its cached approval (same SHA). Only the advisory LLM call is spared.
        import story
        item = {"title": "The Disappearance", "mode": "mystery", "scenes": [{"narration": "A biography."}]}
        reply = {"approved": True, "reasons": [], "title_alignment": 9, "narrative_logic": 9, "payoff": 9,
                 "fact_integrity": 9}
        with mock.patch.object(story, "_json_call", return_value=reply) as judge:
            with self.assertRaises(story.StoryDiscarded):
                story.final_script_gate(item, "test")
            self.assertTrue(item["final_script_approval"]["blocked"])
            resumed = json.loads(json.dumps(item))  # what checkpoint.save_story / resume round-trips
            with self.assertRaises(story.StoryDiscarded):
                story.final_script_gate(resumed, "test")
            with self.assertRaises(story.StoryDiscarded):
                story.final_script_gate(resumed, "test")
            self.assertEqual(judge.call_count, 1)
        self.assertTrue(resumed["final_script_approval"]["blocked"])

    def test_cached_block_is_kept_even_if_checks_cannot_rerun(self):
        # the same words were blocked before (e.g. the fact source was not saved with the checkpoint): still blocked
        import story
        item = {"title": "The Lantern", "mode": "lore", "scenes": [{"narration": "The lantern man walked."}]}
        digest = hashlib.sha256("The lantern man walked.".encode("utf-8")).hexdigest()
        item["final_script_approval"] = {"sha256": digest, "checked": True, "blocked": True, "approved": True,
                                         "checks": [{"code": "unsupported_fact", "severity": "serious",
                                                     "detail": "1888 is not in the source"}]}
        with mock.patch.object(story, "writing_checks", return_value=[]), \
                mock.patch.object(story, "_json_call") as judge:
            with self.assertRaises(story.StoryDiscarded) as err:
                story.final_script_gate(item, "test")
        judge.assert_not_called()
        self.assertIn("unsupported_fact", str(err.exception))

    def test_stale_clean_approval_does_not_hide_a_new_serious_finding(self):
        # a cached "not blocked" result for the same words is re-measured; a serious finding now still blocks
        import story
        item = {"title": "The Disappearance", "mode": "mystery", "scenes": [{"narration": "A biography."}]}
        digest = hashlib.sha256("A biography.".encode("utf-8")).hexdigest()
        item["final_script_approval"] = {"sha256": digest, "checked": True, "blocked": False, "approved": True}
        with mock.patch.object(story, "_json_call") as judge:
            with self.assertRaises(story.StoryDiscarded):
                story.final_script_gate(item, "test")
        judge.assert_not_called()
        self.assertTrue(item["final_script_approval"]["blocked"])

    def test_critic_failure_is_not_approval(self):
        # Owner, Oct 24: an unavailable editor is NOT recorded as an approval, and does not stop a safe video.
        import story
        item = {"title": "The Disappearance", "scenes": [{"narration": "The plane vanished."}]}
        with mock.patch.object(story, "_json_call", side_effect=RuntimeError("offline")):
            out = story.final_script_gate(item, "test")
        self.assertIsNone(out["final_script_approval"]["approved"])
        self.assertIn("unavailable", out["final_script_approval"]["editor"])

    def test_off_title_story_rejected_even_with_approved_flag(self):
        # measured by code (the title's event is never told), whatever the editor says
        import story
        item = {"title": "The Disappearance", "mode": "mystery", "scenes": [{"narration": "A biography."}]}
        reply = {"approved": True, "reasons": [], "title_alignment": 9, "narrative_logic": 9, "payoff": 9,
                 "fact_integrity": 9}
        with mock.patch.object(story, "_json_call", return_value=reply):
            with self.assertRaises(story.StoryDiscarded):
                story.final_script_gate(item, "test")



if __name__ == "__main__":
    unittest.main()


class TestMultiModelWriter(unittest.TestCase):
    def setUp(self):
        import story
        self.story = story
        self.primary = {"title": "Disappeared", "scenes": [
            {"narration": "This mystery contains enough grounded spoken words " * 4}
            for _ in range(6)], "twist_scene": 4, "model": "gemini-3.8-flash", "writer": "gemini"}
        self.prompt = "Use ONLY the supplied facts. Title: Disappeared. Facts: flight lost at sea."

    def test_challenger_selects_independently_judged_draft(self):
        candidate = {**self.primary, "title": "Disappeared", "writer": "temporary"}
        with mock.patch.dict(os.environ, {"NVIDIA_API_KEY": "test-key"}), \
             mock.patch.object(self.story, "_call_model", side_effect=[candidate, {"winner": "B", "reason": "better hook"}]) as call, \
             mock.patch.object(self.story, "model_chain", return_value=["gemini-3.8-flash", "groq:judge-model"]), \
             mock.patch.object(self.story, "_writer", return_value="nvidia writer"), \
             mock.patch.dict(self.story.CONFIG, {"writer_challenge_enabled": True, "writer_challenger_model": "nvidia:deepseek-ai/deepseek-v4.1-flash"}):
            result = self.story.challenge_true_story(self.primary.copy(), self.prompt, "dummy")
        self.assertEqual(result["writer_comparison"]["selected"], "B")
        self.assertEqual(result["model"], "nvidia:deepseek-ai/deepseek-v4.1-flash")
        self.assertEqual(call.call_count, 2)

    def test_challenger_failure_preserves_original(self):
        with mock.patch.dict(os.environ, {"NVIDIA_API_KEY": "test-key"}), \
             mock.patch.object(self.story, "_call_model", side_effect=RuntimeError("429 quota")), \
             mock.patch.dict(self.story.CONFIG, {"writer_challenge_enabled": True}):
            result = self.story.challenge_true_story(self.primary.copy(), self.prompt, "dummy")
        self.assertEqual(result["model"], "gemini-3.8-flash")

    def test_no_independent_critic_preserves_original(self):
        candidate = self.primary.copy()
        with mock.patch.dict(os.environ, {"NVIDIA_API_KEY": "test-key"}), \
             mock.patch.object(self.story, "_call_model", return_value=candidate) as call, \
             mock.patch.object(self.story, "model_chain", return_value=["gemini-3.8-flash", "nvidia:deepseek-ai/deepseek-v4.1-flash"]), \
             mock.patch.dict(self.story.CONFIG, {"writer_challenge_enabled": True}):
            result = self.story.challenge_true_story(self.primary.copy(), self.prompt, "dummy")
        self.assertEqual(result["model"], "gemini-3.8-flash")
        call.assert_called_once()



class VirtualShotProvenanceRegression(unittest.TestCase):
    """Real generator stores an absolute .origin path; QA must accept it and preserve image identity."""

    def test_absolute_origin_checkpoint_does_not_crash_provenance_or_visual_qa(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            original = folder / "scene_10b.png"
            crop = folder / "scene_10a.png"
            Image.new("RGB", (64, 96), "darkred").save(original)
            images._virtual_shot(original, crop, "a")
            self.assertTrue(Path(crop.with_suffix(".origin").read_text().strip()).is_absolute())
            original.with_name(original.stem + ".ai.json").write_text(
                json.dumps({"provider": "local_sd", "prompt": "dark hallway"}))
            meta = explainer.provenance_of(str(crop))
            self.assertEqual(meta["virtual_crop_of"], "scene_10b.png")
            self.assertEqual(meta["kind"], "ai_reconstruction")
            self.assertEqual(meta["provider"], "local_sd")

    def test_stale_absolute_path_resolves_from_current_checkpoint_folder(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            original = folder / "scene_01b.png"
            crop = folder / "scene_01a.png"
            Image.new("RGB", (64, 96), "black").save(original)
            Image.new("RGB", (64, 96), "gray").save(crop)
            crop.with_suffix(".origin").write_text("/old-runner/workspace/scene_01b.png")
            original.with_name(original.stem + ".ai.json").write_text(
                json.dumps({"provider": "cloudflare", "prompt": "eerie bathroom"}))
            meta = explainer.provenance_of(str(crop))
            self.assertEqual(meta["virtual_crop_of"], "scene_01b.png")
            self.assertEqual(meta["kind"], "ai_reconstruction")
            self.assertEqual(meta["provider"], "cloudflare")


class PreferredNarratorContract(unittest.TestCase):
    def test_new_stories_use_owner_approved_aka_manto_voice(self):
        self.assertEqual(common.CONFIG["voice_test_pool"], ["am_adam"])
        self.assertEqual(common.CONFIG["voice"], "am_adam")
        self.assertAlmostEqual(common.CONFIG["voice_speed"], 1.1)


class OwnerQueueAndApprovedSoundtrack(unittest.TestCase):
    """An approved already-buffered video goes next without deleting older entries or new publishing routes."""

    def test_owner_priority_only_affects_existing_buffered_stamp(self):
        import publish
        waiting = [
            {"stamp": "2026-10-23_2133"},
            {"stamp": "2026-10-23_2249"},
            {"stamp": "2026-10-25_0354"},
        ]
        with mock.patch.dict(publish.CONFIG, {"publish_priority_stamps": ["2026-10-25_0354"]}):
            result = publish._next_buffered_video(waiting)
        self.assertIs(result, waiting[2])
        self.assertEqual([x["stamp"] for x in waiting],
                         ["2026-10-23_2133", "2026-10-23_2249", "2026-10-25_0354"])
        with mock.patch.dict(publish.CONFIG, {"publish_priority_stamps": ["missing"]}):
            self.assertIs(publish._next_buffered_video(waiting), waiting[0])

    def test_publisher_uses_approved_track_and_revalidates_before_delivery(self):
        import publish
        import background_music
        import production_gate
        with tempfile.TemporaryDirectory() as temporary:
            mp4 = Path(temporary) / "final.mp4"
            mp4.write_bytes(b"placeholder; neither audio nor video is transmitted during unit tests")
            meta = {"title": "generic owner-approved test", "story_id": "example", "caption_text": "test"}
            stamp = "2026-10-25_0354"
            with mock.patch.dict(publish.CONFIG, {"publish_music_overrides": {
                    stamp: "unsolved_mystery.mp3"}}), \
                 mock.patch.object(background_music, "add_background_music") as mix, \
                 mock.patch.object(production_gate, "validate_final_video") as validate:
                publish._apply_approved_publish_music({"stamp": stamp}, mp4, meta)
            mix.assert_called_once_with(mp4, mp4.parent, meta, approved_track="unsolved_mystery.mp3")
            validate.assert_called_once_with(mp4)
            self.assertEqual(json.loads((mp4.parent / "caption.json").read_text())["story_id"], "example")

    def test_no_override_does_not_modify_video(self):
        import publish
        with tempfile.TemporaryDirectory() as temporary:
            mp4 = Path(temporary) / "final.mp4"
            with mock.patch.dict(publish.CONFIG, {"publish_music_overrides": {
                    "different_stamp": "bk_grnde.mp3"}}):
                publish._apply_approved_publish_music({"stamp": "ordinary_video"}, mp4, {})
            self.assertFalse((mp4.parent / "caption.json").exists())

    def test_unapproved_or_unsafe_music_paths_are_rejected(self):
        import background_music
        with mock.patch.dict(background_music.CONFIG, {
                "music_policy": "approved_files", "approved_music": [
                    "unsolved_mystery.mp3", "bk_grnde.mp3"]}), \
             mock.patch.object(background_music, "media_duration", return_value=58.65):
            for invalid in ("../private.mp3", "unauthorized.mp3", "/tmp/unsolved_mystery.mp3"):
                with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                    background_music.add_background_music(
                        Path("not_real.mp4"), Path("/tmp"), {}, approved_track=invalid)

    def test_story_music_override_matches_existing_approved_owner_track(self):
        self.assertEqual(common.CONFIG["publish_priority_stamps"], ["2026-10-25_0354"])
        self.assertEqual(common.CONFIG["publish_music_overrides"]["2026-10-25_0354"],
                         "unsolved_mystery.mp3")
        self.assertIn("unsolved_mystery.mp3", common.CONFIG["approved_music"])
        self.assertTrue((ROOT / "assets/music/unsolved_mystery.mp3").is_file())
