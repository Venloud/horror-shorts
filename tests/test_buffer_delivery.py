"""Offline only: Buffer.com delivery, durable dedup, source authorization, API retirement."""
import json
import io
from contextlib import ExitStack, redirect_stdout
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
    def run_empty_worker(self, state, argv=(), stamp=None, **overrides):
        """Exercise entrypoint with all external effects forbidden or mocked."""
        with tempfile.TemporaryDirectory() as temp, ExitStack() as stack:
            summary = Path(temp) / "summary"
            outputs = Path(temp) / "outputs"
            stack.enter_context(patch.dict("os.environ", {
                "GITHUB_STEP_SUMMARY": str(summary), "GITHUB_OUTPUT": str(outputs)}))
            mocks = {"read_stamp_file": lambda _: stamp,
                     "read_state": lambda: (state, "sha"),
                     "candidates": lambda *a, **k: [],
                     "historical_candidates": lambda *a: [],
                     "already_youtube": lambda *a: False,
                     "needs_tiktok": lambda *a: True}
            mocks.update(overrides)
            for name, fn in mocks.items():
                stack.enter_context(patch.object(queue, name, side_effect=fn))
            stack.enter_context(patch.object(recovery, "recover_one", return_value=False))
            for name in ("graph", "persist", "queue_one"):
                stack.enter_context(patch.object(queue, name, side_effect=AssertionError("unexpected mutation")))
            before = json.dumps(state, sort_keys=True)
            with redirect_stdout(io.StringIO()) as logs:
                code = queue.main(list(argv))
            self.assertEqual(before, json.dumps(state, sort_keys=True))
            return code, logs.getvalue(), summary.read_text(), outputs.read_text()

    def test_exhaustion_is_explicit_noop_not_claim_queue_caught_up(self):
        state = {"queued": {"old": {"status": "attempt_started"}}, "tiktok_queued": {}}
        code, logs, summary, outputs = self.run_empty_worker(state)
        self.assertEqual(code, 0)  # normal periodic exhaustion, not a delivery success
        self.assertIn("outcome=no_eligible_video", outputs)
        self.assertIn("tiktok_queued=0", outputs)
        self.assertIn("::warning::", logs)
        self.assertIn("1 uncertain attempt", summary)
        self.assertIn("Channel health was not checked", summary)
        self.assertNotIn("caught up", logs)

    def test_missing_exact_daily_pair_fails_without_recovery_or_mutation(self):
        code, _, summary, outputs = self.run_empty_worker(
            {"queued": {}, "tiktok_queued": {}},
            ("--stamp-file", ".posted", "--production-only"), stamp="2026-11-08_0700")
        self.assertEqual(code, 1)
        self.assertIn("outcome=missing_accepted_inventory", outputs)
        self.assertIn("unmet delivery", summary)

    def test_prior_draft_and_youtube_receipt_remain_safe_noop(self):
        code, _, _, outputs = self.run_empty_worker(
            {"queued": {"2026-11-07_1936": {"status": "queued"}}, "tiktok_queued": {}},
            ("--stamp-file", ".posted", "--production-only"), stamp="2026-11-07_1936",
            needs_tiktok=lambda _: False)
        self.assertEqual(code, 0)
        self.assertIn("outcome=no_new_production_video", outputs)

    def test_missing_daily_receipt_reports_no_accepted_video(self):
        code, _, _, outputs = self.run_empty_worker({}, ("--stamp-file", ".posted"), stamp="")
        self.assertEqual(code, 0)
        self.assertIn("outcome=no_accepted_video", outputs)

    def test_rollout_video_with_draft_receipt_is_not_replayed(self):
        assets = {"2026-11-07_1936.mp4": {}, "2026-11-07_1936.json": {}}
        history = [{"buffered": "2026-11-07_1936", "draft_sent": "confirmed",
                    "tiktok": {"mode": "draft", "status": "SEND_TO_USER_INBOX"}}]
        with patch.object(queue, "release_assets", return_value=assets), \
             patch.object(queue, "safe_history", return_value=history), \
             patch.object(queue, "already_youtube", return_value=False), \
             patch.object(queue, "TIKTOK_BUFFER_FROM", "2026-11-07"):
            self.assertFalse(queue.needs_tiktok("2026-11-07_1936"))
            self.assertEqual(queue.candidates({"2026-11-07_1936": {}}, {}), [])

    def test_uncertain_tiktok_failure_preserves_write_ahead_and_youtube_receipt(self):
        record = {"queued": {"new": {"status": "queued", "buffer_post_id": "yt-id"}},
                  "tiktok_queued": {}}
        metadata = unittest.mock.Mock()
        metadata.json.return_value = {"title": "Night Files", "caption_text": "Approved caption"}
        with patch.object(queue, "public_asset"), \
             patch.object(queue.requests, "get", return_value=metadata), \
             patch.object(queue, "persist", return_value="write-ahead") as save, \
             patch.object(queue, "graph", side_effect=queue.requests.Timeout("uncertain")):
            with self.assertRaises(queue.requests.Timeout):
                queue.queue_one("new", {"browser_download_url": "https://github.com/video.mp4"},
                                {"browser_download_url": "https://github.com/video.json"},
                                record, "sha", [], "tiktok")
            save.assert_called_once()
        self.assertEqual(record["tiktok_queued"]["new"]["status"], "attempt_started")
        self.assertEqual(record["queued"]["new"]["buffer_post_id"], "yt-id")

    def test_success_summary_counts_only_new_channel_acknowledgments(self):
        with tempfile.TemporaryDirectory() as temp, ExitStack() as stack:
            summary = Path(temp) / "summary"
            stack.enter_context(patch.dict("os.environ", {"GITHUB_STEP_SUMMARY": str(summary),
                                                         "GITHUB_OUTPUT": ""}))
            state = {"queued": {"new": {}}, "tiktok_queued": {}}
            for name, value in {"read_state": (state, "sha"), "read_stamp_file": None,
                                "candidates": [("new", {}, {})], "needs_tiktok": True,
                                "existing_posts": [], "queue_one": (True, "next")}.items():
                stack.enter_context(patch.object(queue, name, return_value=value))
            with redirect_stdout(io.StringIO()):
                self.assertEqual(queue.main([]), 0)
            text = summary.read_text()
            self.assertIn("Buffer delivery: queued", text)
            self.assertIn("YouTube **0**, TikTok **1**", text)
            self.assertIn("not queue depth or confirmed public posts", text)

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

    def test_older_youtube_pending_release_is_backfilled_before_tiktok_download(self):
        assets = {
            "2026-10-08_1100.mp4": {"name": "old-video"},
            "2026-10-08_1100.json": {"name": "old-metadata"},
        }
        with patch.object(queue, "release_assets", side_effect=lambda tag: assets if tag == "youtube-pending" else {}), \
             patch.object(queue, "already_youtube", return_value=False), \
             patch.object(queue, "BACKFILL", Path("/nonexistent-night-files-history.json")):
            older = queue.historical_candidates({})
        self.assertEqual([v[0] for v in older], ["2026-10-08_1100"])

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

    def test_public_tiktok_recovery_requires_vetted_unposted_source_and_safe_token_rotation(self):
        post = {
            "id": "7691234567890123456", "create_time": 1,
            "share_url": "https://www.tiktok.com/@nightfiles/video/7691234567890123456",
            "title": "Verified old story",
            "video_description": "The father of cinema vanished before his biggest premiere. #horror",
        }
        verified = {"stamp": "old-night-files-video", "tiktok_published": True,
                    "title": "Verified old story",
                    "caption": "The father of cinema vanished before his biggest premiere."}
        with patch.dict("os.environ", {"GH_TOKEN": "", "TIKTOK_REFRESH_TOKEN": "secret",
                                       "TIKTOK_CLIENT_KEY": "key", "TIKTOK_CLIENT_SECRET": "secret"}):
            with patch.object(recovery, "owned_public_posts", side_effect=AssertionError("token rotated")):
                self.assertFalse(recovery.from_tiktok([verified], {}))
        with patch.dict("os.environ", {"GH_TOKEN": "exists", "TIKTOK_REFRESH_TOKEN": "secret",
                                       "TIKTOK_CLIENT_KEY": "key", "TIKTOK_CLIENT_SECRET": "secret"}):
            with patch.object(recovery, "owned_public_posts", side_effect=AssertionError("unmapped scrape")):
                self.assertFalse(recovery.from_tiktok([], {}))
            with patch.object(recovery, "owned_public_posts", return_value=[post]), \
                 patch.object(recovery, "download_public_post", return_value="old-night-files-video") as download:
                self.assertEqual(recovery.from_tiktok([verified], {}), "old-night-files-video")
                download.assert_called_once()
                self.assertFalse(recovery.from_tiktok(
                    [{"stamp": "wrong", "caption": "some other video"}], {}))

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
