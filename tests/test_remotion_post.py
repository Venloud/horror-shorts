"""Validate the existing Night Files -> Remotion editorial integration contract.

No npm, video encoding, external websites or user credentials are needed.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"pipeline"))
from remotion_post import manifest, polish


class RemotionEditorialContract(unittest.TestCase):
    def setUp(self):
        self.shots=[
            {"start":0,"end":1.25,"shot":{"type":"scene","expression":"worried","text":""}},
            {"start":1.25,"end":2.15,"shot":{"type":"graphic","template":"clock_stop","text":"CLOCK STOPPED"}},
        ]
        self.voice={"words":[
            {"word":"The","start":0.0,"end":0.24},
            {"word":"clock","start":0.24,"end":0.62},
            {"word":"stopped.","start":0.62,"end":1.05},
        ]}

    def test_converts_timestamped_storyboard_without_changing_words(self):
        m=manifest(Path("/tmp/source.mp4"),Path("/tmp/target.mp4"),
                   self.shots,self.voice,24,52)
        self.assertEqual([s["startFrame"] for s in m["shots"]],[0,30])
        self.assertEqual(m["shots"][-1]["endFrame"],52)
        self.assertEqual([w["word"] for w in m["words"]],
                         ["The","clock","stopped."])
        self.assertEqual(m["fps"],24)
        self.assertEqual(m["totalFrames"],52)

    def test_rejects_invalid_rate_and_blank_render(self):
        with self.assertRaises(ValueError):
            manifest(Path("a.mp4"),Path("b.mp4"),self.shots,self.voice,13,50)
        with self.assertRaises(ValueError):
            manifest(Path("a.mp4"),Path("b.mp4"),self.shots,self.voice,24,0)
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):
                polish(Path(tmp)/"missing.mp4",Path(tmp)/"out.mp4",
                       self.shots,self.voice,24,52)

    def test_copyable_remotion_entrypoint_and_safe_default(self):
        path=ROOT/"remotion"/"src"/"index.jsx"
        self.assertIn("NightFilesJoin",path.read_text())
        self.assertIn("NightFilesPolish",path.read_text())
        self.assertIn("registerRoot(RemotionRoot)",path.read_text())
        cfg=json.loads((ROOT/"config.json").read_text())
        self.assertFalse(cfg.get("remotion_polish",False),
                         "Remotion production post-pass must be opt-in")
        post=(ROOT/"pipeline"/"remotion_post.py").read_text()
        self.assertNotIn("publish(",post)
        self.assertNotIn("cloudflare",post.lower())


if __name__=="__main__":
    unittest.main()
