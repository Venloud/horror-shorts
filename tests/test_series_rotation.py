"""Zero-network regression suite for optional original horror trilogies."""
import hashlib
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))
import series_rotation as sr


def when(day):
    return datetime(2026, 10, day, tzinfo=timezone.utc)


def public(stamp, day, **extra):
    return {"title": "Night Files published video", "story_id": stamp,
            "public_confirmed_at": when(day).isoformat(),
            "public_post_url": "https://www.youtube.com/shorts/" + stamp,
            "public_confirmation_source": "owner-confirmed public page", **extra}


class TrilogyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name)
        patcher = patch.object(sr, "SERIES_DIR", self.dir)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.config = {"occasional_trilogies":
                       {"enabled": False, "approved_manifest": "", "minimum_days_between_starts": 7,
                        "minimum_verified_public_posts": 14}}

    def file(self, name, doc):
        data = json.dumps(doc, sort_keys=True).encode()
        (self.dir / name).write_bytes(data)
        return {"file": name, "sha256": hashlib.sha256(data).hexdigest()}

    def package(self):
        bible = {"series_id": "night-window-01", "fiction": True,
                 "characters": [{"name": "Mara", "look": "grey raincoat"}],
                 "clues": ["a repaired radio"], "episode_outlines": [{}, {}, {}]}
        chapters = []
        for number in (1, 2, 3):
            script = {"series_id": "night-window-01", "series_episode": number,
                      "true_story": False, "mode": "fiction",
                      "title": "The Night Window " + str(number),
                      "characters": [{"name": "Mara", "look": "grey raincoat"}],
                      "scenes": [{"narration": "A worker checks the radio and learns what happened to the signal.",
                                  "image_prompt": "An original radio on the desk"}] * 8,
                      "twist_scene": 6}
            chapters.append({"number": number, **self.file(f"episode-{number}.json", script)})
        manifest = {"kind": "original_fiction_trilogy", "series_id": "night-window-01",
                    "initial_baseline": {"recorded_at": when(20).isoformat(),
                                         "confirmed_posts": 0, "evidence": "verified owner check"},
                    "approval": {"concept": True, "scripts": True, "visuals": True,
                                 "production": True, "approved_by": "owner",
                                 "approved_at": when(20).isoformat()},
                    "bible": self.file("bible.json", bible), "episodes": chapters}
        (self.dir / "approved.json").write_text(json.dumps(manifest))
        self.config["occasional_trilogies"].update({"enabled": True, "approved_manifest": "approved.json"})
        return manifest

    def test_standalone_untouched_by_default(self):
        self.assertIsNone(sr.select_approved_story([], self.config, when(27)))

    def test_no_manifest_is_not_approval(self):
        self.config["occasional_trilogies"]["enabled"] = True
        with self.assertRaises(sr.SeriesSafetyError):
            sr.select_approved_story([], self.config, when(27))

    def test_first_trilogy_has_explicit_baseline_and_owner_gates(self):
        self.package()
        import types
        fake = types.SimpleNamespace(_validate=lambda story: None)
        with patch.dict(sys.modules, {"story": fake}):
            selected = sr.select_approved_story([], self.config, when(27))
        self.assertEqual(selected["series_episode"], 1)
        self.assertEqual(selected["mode"], "fiction")
        self.assertEqual(selected["source"], "approved-series:night-window-01:episode-1")
        self.assertTrue(selected["explainer_adapted"])
        self.assertEqual(selected["series_bible"]["characters"][0]["name"], "Mara")

    def test_owner_approval_or_hash_changed_is_blocked(self):
        manifest = self.package()
        manifest["approval"]["production"] = False
        (self.dir / "approved.json").write_text(json.dumps(manifest))
        with self.assertRaises(sr.SeriesSafetyError):
            sr.select_approved_story([], self.config, when(27))
        manifest["approval"]["production"] = True
        (self.dir / "approved.json").write_text(json.dumps(manifest))
        (self.dir / "episode-1.json").write_text("{}")
        with self.assertRaises(sr.SeriesSafetyError):
            sr.select_approved_story([], self.config, when(27))

    def test_evidence_counts_only_public_unduplicated_videos(self):
        entries = [public("a", 20), public("a", 21),
                   {"title": "draft", "story_id": "draft", "draft_sent": "2026-10-23_0000"},
                   {"title": "queued", "story_id": "queue", "buffer_post_id": "123"}]
        self.assertEqual(len(sr._verified_publications(entries)), 1)

    def test_cooldown_both_conditions_and_seven_full_days(self):
        history = [public("prev-1", 20, series_id="earlier", series_episode=1),
                   public("prev-2", 20, series_id="earlier", series_episode=2),
                   public("prev-3", 20, series_id="earlier", series_episode=3)]
        history += [public(f"post-{n}", 21) for n in range(11)]
        self.assertFalse(sr.new_series_eligible(history, when(26))[0])
        self.assertTrue(sr.new_series_eligible(history, when(27))[0])
        self.assertFalse(sr.new_series_eligible(history[:13], when(27))[0])
        self.assertFalse(sr.new_series_eligible(history, when(26))[0])

    def test_unfinished_previous_trilogy_blocks_new_trilogy(self):
        data = [public("prev-1", 20, series_id="earlier", series_episode=1),
                public("prev-2", 20, series_id="earlier", series_episode=2)]
        data += [public(f"post-{n}", 21) for n in range(20)]
        self.assertFalse(sr.new_series_eligible(data, when(27))[0])
        data.append({"title": "unconfirmed", "story_id": "prev-3",
                     "series_id": "earlier", "series_episode": 3, "draft_sent": "yes"})
        self.assertFalse(sr.new_series_eligible(data, when(27))[0])

    def test_episode_two_requires_earlier_publication_not_draft(self):
        self.package()
        one = {"title": "Episode 1", "story_id": "part-1",
               "series_id": "night-window-01", "series_episode": 1,
               "draft_sent": "2026-10-27_0000"}
        self.assertIsNone(sr.select_approved_story([one], self.config, when(27)))
        one.update(public("part-1", 27))
        import types
        with patch.dict(sys.modules, {"story": types.SimpleNamespace(_validate=lambda s: None)}):
            second = sr.select_approved_story([one], self.config, when(27))
        self.assertEqual(second["series_episode"], 2)
        two = {"title": "Episode 2", "story_id": "part-2",
               "series_id": "night-window-01", "series_episode": 2}
        self.assertIsNone(sr.select_approved_story([one, two], self.config, when(27)))
        two.update(public("part-2", 27))
        with patch.dict(sys.modules, {"story": types.SimpleNamespace(_validate=lambda s: None)}):
            third = sr.select_approved_story([one, two], self.config, when(27))
        self.assertEqual(third["series_episode"], 3)

    def test_missing_public_confirmation_does_not_count_legacy_posted(self):
        h = [{"title": "Night Files", "story_id": "v1", "posted": "2026-10-20_1000",
              "tiktok": {"status": "SEND_TO_USER_INBOX"}}]
        self.assertEqual(sr._verified_publications(h), [])

    def test_invalid_episode_path_rejected(self):
        manifest = self.package()
        manifest["episodes"][0]["file"] = "../other.json"
        (self.dir / "approved.json").write_text(json.dumps(manifest))
        with self.assertRaises(sr.SeriesSafetyError):
            sr.select_approved_story([], self.config, when(27))


if __name__ == "__main__":
    unittest.main()
