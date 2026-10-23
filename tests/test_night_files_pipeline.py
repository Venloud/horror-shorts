"""Night Files production pipeline: checkpoints, fresh_images, parking, approved character, shot lists.

Mocks only: no Gemini / Cloudflare / TikTok / buffer call, no production build, nothing published.
The Actions cache is simulated by FakeActionsCache (same key / restore-keys prefix rules as actions/cache).
  python -m unittest discover -s tests -p test_night_files_pipeline.py -v
"""
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))
os.environ.setdefault("CLOUDFLARE_API_TOKEN", "test-token-not-used")

import checkpoint  # noqa: E402
import explainer  # noqa: E402
import images  # noqa: E402
import sprites  # noqa: E402

HOST = ROOT / "assets" / "character" / "host"


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
            "scenes": [{"narration": "You open the door of the old hotel lobby.", "image_location": "lobby"},
                       {"narration": "The clock on the station platform stopped at midnight.",
                        "image_location": "platform"},
                       {"narration": "Down by the river, the lantern is still burning. Who lit it?",
                        "image_location": "riverbank"}],
            "locations": [{"name": "lobby", "look": "old hotel lobby with a brass counter"},
                          {"name": "platform", "look": "empty railway platform in fog"},
                          {"name": "riverbank", "look": "muddy riverbank at night with reeds"}]}


def _plan(story):
    return {"cast": {}, "inserts": [],
            "locations": [dict(l) for l in story["locations"]],
            "scenes": [{"shots": [{"type": "scene", "location": l["name"], "shot_type": "wide"}]}
                       for l in story["locations"]]}


def _narration(story):
    words, t = [], 0.0
    for i, sc in enumerate(story["scenes"]):
        for w in sc["narration"].split():
            words.append({"word": w, "start": round(t, 2), "end": round(t + 0.38, 2), "scene": i})
            t += 0.42
    spans, k = [], 0
    for i in range(len(story["scenes"])):
        ws = [w for w in words if w["scene"] == i]
        spans.append((ws[0]["start"], ws[-1]["end"]))
    return {"duration": round(t + 0.3, 2), "words": words, "scene_times": spans, "speed": 1.1}


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
                        mock.patch.object(images, "test_mode", lambda: False)]
        for p in self.patches:
            p.start()
        self.draws = []
        self.library_calls = []

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def fake_draw(self, crash_after=None):
        def draw(prompt, dest, budget):
            if crash_after is not None and len(self.draws) >= crash_after:
                raise RuntimeError("runner lost mid-image (simulated)")
            budget.call()
            self.draws.append(prompt)
            Image.new("RGB", (576, 1024), (len(self.draws) * 30 % 255, 40, 60)).save(dest)
            return dest
        return draw

    def fake_library(self, match: set):
        def lib(story, look, dest, taken):
            self.library_calls.append(look)
            if any(m in look for m in match):
                Image.new("RGB", (576, 1024), (90, 90, 90)).save(dest)
                return "lib-" + hashlib.sha1(look.encode()).hexdigest()[:6]
            return ""
        return lib

    def assets(self, story, fresh: bool, crash_after=None, library=frozenset()):
        with mock.patch.dict(os.environ, {"FRESH_IMAGES": "true" if fresh else "false"}), \
                mock.patch.object(explainer, "_draw", self.fake_draw(crash_after)), \
                mock.patch.object(explainer, "_from_library", self.fake_library(set(library))):
            return explainer.make_assets(story, _plan(story), checkpoint.IMAGES)

    def first_run(self, story):
        checkpoint.start(story)
        wav = self.tmp / "narration.wav"
        wav.write_bytes(b"RIFF" + os.urandom(2000))
        n = _narration(story)
        checkpoint.save_narration(story, {**n, "path": wav})
        return n


class FreshImages(Base):
    def test_new_run_fresh_on_draws_every_plate_and_skips_library(self):
        story = _story()
        self.first_run(story)
        a = self.assets(story, fresh=True, library={"hotel"})
        self.assertEqual(len(self.draws), 3)
        self.assertEqual(self.library_calls, [])
        self.assertEqual(set(a["plates"]), {"lobby", "platform", "riverbank"})
        self.assertTrue(all("no people" in p for p in self.draws))

    def test_new_run_fresh_off_uses_matching_library_plate_then_generates_the_rest(self):
        story = _story()
        self.first_run(story)
        a = self.assets(story, fresh=False, library={"hotel"})
        self.assertEqual(len(self.draws), 2)  # lobby came from the library
        self.assertEqual(story["explainer_assets"]["library"], 1)
        self.assertEqual(len(a["plates"]), 3)

    def test_checkbox_value_reaches_the_pipeline(self):
        with mock.patch.dict(os.environ, {"FRESH_IMAGES": "false"}):
            self.assertFalse(explainer.fresh_images())
        with mock.patch.dict(os.environ, {"FRESH_IMAGES": "true"}):
            self.assertTrue(explainer.fresh_images())


class ResumeAcrossRuns(Base):
    def _two_runs(self, fresh_second: bool, library=frozenset()):
        cache = FakeActionsCache(self.tmp / "actions-cache")
        story = _story()
        # ---- run 1: story + narration saved, 2 of 3 plates drawn, the runner dies on the 3rd
        self.first_run(story)
        with self.assertRaises(RuntimeError):
            self.assets(story, fresh=True, crash_after=2)
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
        a = self.assets(resumed, fresh=fresh_second, library=library)
        self.assertEqual(len(a["plates"]), 3)
        self.assertEqual(len(checkpoint.attempts()), 1)
        return resumed

    def test_failed_run_resumes_with_fresh_on_and_only_draws_the_missing_plate(self):
        s = self._two_runs(fresh_second=True)
        self.assertEqual(len(self.draws), 1)
        self.assertEqual(s["explainer_assets"]["story_reused"], 2)
        print(f"\n[2-run checkpoint test] run 2 resumed {s['story_id']}: narration reused, 2 plates reused, "
              f"{len(self.draws)} drawn")

    def test_failed_run_resumes_with_fresh_off_reuses_cache_then_library(self):
        s = self._two_runs(fresh_second=False, library={"riverbank"})
        self.assertEqual(len(self.draws), 0)  # 2 cached + the missing one from the library
        self.assertEqual(s["explainer_assets"]["library"], 1)

    def test_partial_image_set_draws_only_what_is_missing(self):
        story = _story()
        self.first_run(story)
        with self.assertRaises(RuntimeError):
            self.assets(story, fresh=True, crash_after=1)
        self.draws.clear()
        self.assertIsNotNone(checkpoint.resume([], set()))
        self.assets(story, fresh=True)
        self.assertEqual(len(self.draws), 2)

    def test_corrupt_plate_is_dropped_and_redrawn(self):
        story = _story()
        self.first_run(story)
        a = self.assets(story, fresh=True)
        victim = a["plates"]["platform"]
        victim.write_bytes(b"not a png any more")
        self.assertIsNotNone(checkpoint.resume([], set()))  # sha256 mismatch -> deleted
        self.assertFalse(victim.exists())
        self.draws.clear()
        self.assets(story, fresh=True)
        self.assertEqual(len(self.draws), 1)

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
        self.assertFalse(checkpoint.CK.exists())  # the next run starts a new story
        self.assertEqual(json.loads((d / "status.json").read_text())["status"], "parked")

    def test_retry_story_id_resumes_a_parked_story(self):
        story = _story()
        self.first_run(story)
        with mock.patch("notify.notify_text", lambda *a, **k: None):
            for k in range(3):
                checkpoint.failed_attempt(story, "explainer", f"boom {k}")
        other = _story("ffffffffffff")
        self.first_run(other)  # a newer unfinished story is active
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
            plate = tmp / "plate.png"
            Image.new("RGB", (576, 1024), (40, 44, 50)).save(plate)
            story = _story()
            n = _narration(story)
            p = {"cast": {}, "locations": story["locations"], "inserts": [], "scenes": [{"shots": []}] * 3}
            r = explainer.Renderer(story, n, p, {"plates": {"lobby": plate}, "inserts": {}}, [])
            for st, view, ex in (("wide", "three_quarter", "neutral"), ("medium", "front", "worried"),
                                 ("over_shoulder", "back", "neutral"), ("close", "front", "shocked")):
                shot = {"type": "scene", "location": "lobby", "insert": "", "primary": "you", "action": "standing",
                        "expression": ex, "view": view, "facing": "right", "shot_type": st, "motion": "none",
                        "text_mode": "none", "text": ""}
                frame = r.scene_frame({"shot": shot, "scene": 0, "start": 0.0, "end": 2.0}, 0.5)
                self.assertEqual(frame.size, (1080, 1920))
            self.assertTrue(r.used_assets <= set(before))
            self.assertIn("F15", r.used_assets)  # "shocked": F16 is opaque until re-exported -> F15
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
    "mystery": {"title": "The Clock That Stopped", "mode": "mystery", "true_story": False,
                "setting": "a mill town in the 1920s",
                "locations": [{"name": "the mill", "look": "abandoned textile mill with broken windows"},
                              {"name": "the station", "look": "small railway station in fog"}],
                "scenes": [{"narration": "You find the clock in the mill stopped at midnight.", "image_location":
                            "the mill"},
                           {"narration": "The station master swears the last train never left.",
                            "image_location": "the station"},
                           {"narration": "Three men boarded it. Only two came back. What happened to the third?",
                            "image_location": "the station"}]},
    "lore": {"title": "The Lantern Man", "mode": "lore", "setting": "fenland villages",
             "locations": [{"name": "the fen", "look": "misty fen at night with dark water and reeds"},
                           {"name": "the cottage", "look": "candle-lit cottage kitchen"}],
             "scenes": [{"narration": "You see a light moving across the fen where nobody walks.",
                         "image_location": "the fen"},
                        {"narration": "The village believed it was the Lantern Man, and you shut the door.",
                         "image_location": "the cottage"},
                        {"narration": "The light stops at your window. Do you blow out your candle?",
                         "image_location": "the cottage"}]},
    "fiction": {"title": "Room 14", "mode": "fiction", "setting": "a roadside motel",
                "locations": [{"name": "motel room", "look": "cheap motel room with a buzzing lamp"},
                              {"name": "parking lot", "look": "empty motel parking lot under one streetlight"},
                              {"name": "blank studio", "look": "plain grey studio backdrop"}],
                "scenes": [{"narration": "You check in to room 14 and the key is already warm.",
                            "image_location": "motel room"},
                           {"narration": "Outside, the same car circles the parking lot four times.",
                            "image_location": "parking lot"},
                           {"narration": "The knock comes at three. Would you open it?",
                            "image_location": "motel room"}]},
}


class ShotLists(unittest.TestCase):
    def _plan(self, story):
        n = _narration(story)
        with mock.patch.object(explainer, "_plan_call", lambda prompt: None):  # LLM off: keyword storyboard
            p = explainer.plan(story, n)
        return p, n

    def test_three_sample_stories_build_valid_shot_lists(self):
        approved = {r["id"] for r in sprites.approved_registry()["approved"]}
        for mode, story in SAMPLES.items():
            with self.subTest(mode=mode):
                p, n = self._plan(json.loads(json.dumps(story)))
                explainer.validate_shot_list(p)
                names = {l["name"] for l in p["locations"]}
                self.assertNotIn("blank studio", names)
                for sc, src in zip(p["scenes"], story["scenes"]):
                    scene_shots = [s for s in sc["shots"] if s["type"] == "scene"]
                    self.assertTrue(scene_shots)
                    self.assertEqual(scene_shots[0]["location"], src["image_location"])
                    for s in scene_shots:
                        self.assertEqual(s["primary"], "you")
                        self.assertIn(s["pose_id"], {"M01", "M02", "M03", "M04"})
                        self.assertIn(s["pose_id"], approved)
                        if s["shot_type"] == "close":
                            self.assertRegex(s["face_id"], r"^F\d\d$")
                segs = explainer.timeline(story, n, p)
                body = [s for s in segs if s["shot"]["type"] not in ("opener", "opener_title")]
                lens = [s["end"] - s["start"] for s in body]
                self.assertLessEqual(max(lens), 3.0 + 1.4 + 1e-6)
                print(f"\n[shot list {mode}] " + "; ".join(
                    f"{s['shot']['type']}:{s['shot'].get('location', s['shot'].get('template', ''))}:"
                    f"{s['shot'].get('pose_id', '')}{('/' + s['shot']['face_id']) if s['shot'].get('face_id') else ''}"
                    f" {s['end'] - s['start']:.1f}s" for s in body))

    def test_blank_studio_is_rejected_in_production(self):
        p = {"locations": [{"name": "blank studio", "look": "plain grey studio backdrop"}],
             "scenes": [{"shots": [{"type": "scene", "location": "blank studio"}]}]}
        with self.assertRaises(explainer.ExplainerUnavailable):
            explainer.validate_shot_list(p)
        with self.assertRaises(explainer.ExplainerUnavailable):
            explainer.validate_shot_list({"locations": [], "scenes": []})

    def test_scene_without_plate_never_renders_blank(self):
        story = _story()
        r = explainer.Renderer(story, _narration(story), _plan(story), {"plates": {}, "inserts": {}}, [])
        shot = {"type": "scene", "location": "lobby", "primary": "you", "shot_type": "wide", "view": "front"}
        with self.assertRaises(explainer.ExplainerUnavailable):
            r.scene_frame({"shot": shot, "scene": 0, "start": 0.0, "end": 2.0}, 0.5)


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


if __name__ == "__main__":
    unittest.main()
