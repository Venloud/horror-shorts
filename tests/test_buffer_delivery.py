"""Offline only: Buffer.com delivery, durable dedup, source authorization, API retirement."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import auto_buffer_backfill as queue  # noqa: E402
import buffer_recovery as recovery  # noqa: E402


class BufferDeliveryTests(unittest.TestCase):
    def test_selects_only_complete_unique_production_pair(self):
        assets = {
            "2026-10-23_0001.mp4": {"name": "mp4"},
            "2026-10-23_0001.json": {"name": "json"},
            "2026-10-23_0002.mp4": {"name": "incomplete"},
            "2026-10-22_0003.mp4": {"name": "old-mp4"},
            "2026-10-22_0003.json": {"name": "old-json"},
        }
        self.assertEqual([v[0] for v in queue.pairs(assets, {})],
                         ["2026-10-22_0003", "2026-10-23_0001"])
        self.assertEqual([v[0] for v in queue.pairs(assets, {"2026-10-22_0003": {}})],
                         ["2026-10-23_0001"])
        self.assertEqual([v[0] for v in queue.pairs(assets, {}, after="2026-10-23")],
                         ["2026-10-23_0001"])

    def test_daily_stamp_is_exact_and_missing_stamp_is_noop(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / "receipt"
            self.assertEqual(queue.read_stamp_file(p), "")
            p.write_text(json.dumps({"stamp": "2026-10-25_0354"}))
            self.assertEqual(queue.read_stamp_file(p), "2026-10-25_0354")

    def test_queue_has_write_ahead_before_buffer_mutation(self):
        record = {"queued": {}}
        events = []

        def persist(state, sha):
            events.append(("persist", state["queued"]["2026-10-23_0001"]["status"]))
            return "new-sha"

        def send(query):
            events.append(("buffer", record["queued"]["2026-10-23_0001"]["status"]))
            return {"createPost": {"post": {"id": "buffer-123", "dueAt": "future"}}}

        class Response:
            def raise_for_status(self):
                pass

            def json(self):
                return {"title": "Original Night Files story", "caption_text": "Description"}

        with patch.object(queue, "public_asset"), \
             patch.object(queue.requests, "get", return_value=Response()), \
             patch.object(queue, "persist", side_effect=persist), \
             patch.object(queue, "graph", side_effect=send):
            done, sha = queue.queue_one(
                "2026-10-23_0001",
                {"browser_download_url": "https://github.com/video.mp4"},
                {"browser_download_url": "https://github.com/video.json"},
                record, "old-sha", [],
            )
        self.assertTrue(done)
        self.assertEqual(sha, "new-sha")
        self.assertEqual(events, [("persist", "attempt_started"),
                                  ("buffer", "attempt_started"),
                                  ("persist", "queued")])

    def test_in_flight_receipt_blocks_retry(self):
        record = {"queued": {"2026-10-23_0001": {"status": "attempt_started"}}}
        with patch.object(queue, "graph", side_effect=AssertionError("duplicate!")):
            done, sha = queue.queue_one("2026-10-23_0001", {}, {}, record, "sha", [])
        self.assertFalse(done)
        self.assertEqual(sha, "sha")

    def test_only_verified_owner_backfill_is_recovered(self):
        records = [
            {"stamp": "older", "title": "night", "tiktok_published": True, "status": "queued"},
            {"stamp": "already", "title": "night", "tiktok_published": True, "status": "queued"},
            {"stamp": "draft", "title": "night", "tiktok_published": False, "status": "queued"},
            {"stamp": "bad", "title": "night", "tiktok_published": True, "status": "skipped"},
            {"stamp": "clip", "title": "MrBeast", "tiktok_published": True, "status": "queued"},
        ]
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / "backfill.json"
            p.write_text(json.dumps({"videos": records}))
            with patch.object(recovery, "BACKFILL", p):
                got = recovery.legacy_candidates({"already": {"status": "queued"}})
        self.assertEqual([x["stamp"] for x in got], ["older"])

    def test_tiktok_recovery_requires_exact_caption_evidence(self):
        record = {"caption": "The father of cinema vanished before his biggest premiere."}
        self.assertTrue(recovery.matches(
            {"video_description": "The father of cinema vanished before his biggest premiere. #horror"},
            record))
        self.assertFalse(recovery.matches({"video_description": "Cinema mystery video"}, record))
        self.assertFalse(recovery.matches({"video_description": "Other account post"}, record))

    def test_public_tiktok_recovery_requires_owner_caption_and_safe_token_rotation(self):
        post = {
            "id": "7691234567890123456", "create_time": 1,
            "share_url": "https://www.tiktok.com/@nightfiles/video/7691234567890123456",
            "title": "Water mystery",
            "video_description": "A night shift worker watches a security monitor showing a woman standing on the surface #horror",
        }
        with patch.dict("os.environ", {"GH_TOKEN": "", "TIKTOK_REFRESH_TOKEN": "secret",
                                       "TIKTOK_CLIENT_KEY": "key", "TIKTOK_CLIENT_SECRET": "secret"}):
            with patch.object(recovery, "owned_public_posts", side_effect=AssertionError("token rotated")):
                self.assertFalse(recovery.from_tiktok([], {}))
        with tempfile.TemporaryDirectory() as tmp:
            backup = Path(tmp) / "backfill.json"
            backup.write_text('{"videos": []}')
            with patch.dict("os.environ", {"GH_TOKEN": "exists", "TIKTOK_REFRESH_TOKEN": "secret",
                                           "TIKTOK_CLIENT_KEY": "key", "TIKTOK_CLIENT_SECRET": "secret"}), \
                 patch.object(recovery, "BACKFILL", backup), \
                 patch.object(recovery, "owned_public_posts", return_value=[post]), \
                 patch.object(recovery, "release_assets", return_value={}), \
                 patch.object(recovery, "download_public_post", return_value="tt_7691234567890123456") as download:
                self.assertEqual(recovery.from_tiktok([], {}), "tt_7691234567890123456")
                download.assert_called_once()

    def test_direct_youtube_api_not_called_from_live_publisher(self):
        publisher = (ROOT / "pipeline" / "publish.py").read_text()
        self.assertNotIn("youtube.upload(", publisher)
        self.assertNotIn("youtube.configured()", publisher)
        self.assertNotIn("youtube_pending.upload_some()", publisher)
        daily = (ROOT / ".github/workflows" / "daily.yml").read_text()
        self.assertNotIn("secrets.YT_CLIENT_ID", daily)
        self.assertIn("--stamp-file .posted --production-only", daily)
        self.assertIn("tools/auto_buffer_backfill.py", daily)
        worker = (ROOT / ".github/workflows" / "buffer_backfill_auto.yml").read_text()
        self.assertIn("*/15 * * * *", worker)
        self.assertIn("group: night-files", worker)


if __name__ == "__main__":
    unittest.main()
