"""Owner-approved SFX pack (2026-11-25): twist riser + boom, swoosh/whip sounds on their cuts, glitch event,
peak alignment in the mixer, rights records next to every owner file."""
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

import explainer  # noqa: E402

OWNER = ("footsteps_wood", "knocking", "whoosh", "glitch", "impact_boom", "riser", "transition_swoosh")


def _segs(*spec):
    return [{"start": s, "end": s + 2.0, "scene": sc, "transition": tr, "shot": {"type": "image"}}
            for s, sc, tr in spec]


class OwnerSfx(unittest.TestCase):
    def test_every_owner_file_has_a_rights_record(self):
        for n in OWNER:
            rec = json.loads((ROOT / "assets" / "sfx" / f"{n}.license.json").read_text(encoding="utf-8"))
            self.assertEqual(rec["license"], "owner-approved, license unknown")
            self.assertTrue(rec["source"] and rec["approved"])
            self.assertTrue((ROOT / "assets" / "sfx" / f"{n}.mp3").is_file())

    def test_twist_gets_riser_and_boom_only_there(self):
        segs = _segs((0.0, 0, "cut"), (5.0, 1, "cut"), (12.0, 2, "cut"), (20.0, 3, "cut"))
        with mock.patch.object(explainer, "event_sfx", return_value=[]):
            ev = explainer.sound_plan({"twist_scene": 2}, {"words": []}, segs)
        names = [(e[0], e[1]) for e in ev]
        self.assertIn((12.0, "riser"), names)
        self.assertIn((12.0, "impact_boom"), names)
        self.assertEqual(sum(1 for _, n in names if n == "impact_boom"), 1)

    def test_no_twist_hit_in_the_hook_or_without_twist(self):
        segs = _segs((0.0, 0, "cut"), (2.0, 1, "cut"))
        self.assertIsNone(explainer.twist_hit({"twist_scene": 1}, segs))  # 2.0 s: inside the hook
        self.assertIsNone(explainer.twist_hit({}, segs))
        with mock.patch.dict(explainer.CONFIG, {"sfx_twist_hit": False}):
            self.assertIsNone(explainer.twist_hit({"twist_scene": 1}, _segs((0.0, 0, "cut"), (9.0, 1, "cut"))))

    def test_swoosh_and_whip_sounds(self):
        segs = _segs((0.0, 0, "cut"), (5.0, 1, "swoosh"), (10.0, 2, "whip"))
        with mock.patch.object(explainer, "event_sfx", return_value=[]):
            ev = explainer.sound_plan({}, {"words": []}, segs)
        got = {e[1]: e for e in ev}
        self.assertEqual(got["transition_swoosh"][0], 5.0)
        self.assertTrue(got["transition_swoosh"][4]["peak"])
        self.assertEqual(got["whoosh"][0], 10.0)

    def test_glitch_event(self):
        from test_cinematic_editor import _words
        with mock.patch.object(explainer, "sfx_index", return_value={}):
            ev = explainer.event_sfx({"words": _words("It was late. Then the lights flickered in the hall.", step=0.5)})
        self.assertEqual([e[1] for e in ev], ["glitch"])

    def test_mixer_lands_the_peak_on_time(self):
        import soundfile as sf
        import tempfile
        sr = 48000
        snd = np.zeros(sr, np.float32)
        snd[int(0.7 * sr):int(0.72 * sr)] = 0.5  # loudest moment 0.7 s into the sound
        with tempfile.TemporaryDirectory() as d:
            voice = Path(d) / "v.wav"
            sf.write(str(voice), np.zeros(3 * sr, np.float32), sr)
            with mock.patch.object(explainer, "_load_sfx", return_value=snd):
                out = explainer._mix_audio({"path": voice}, 3.0, [(2.0, "x", 1.0, None, {"peak": True})],
                                           Path(d) / "m.wav")
            mix, _ = sf.read(str(out))
        self.assertAlmostEqual(np.argmax(np.abs(mix)) / sr, 2.0, delta=0.03)


if __name__ == "__main__":
    unittest.main()
