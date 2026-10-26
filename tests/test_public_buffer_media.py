"""Offline public-media preflight; no cloud calls or credentials."""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import public_buffer_media as media


class PublicBufferMediaTests(unittest.TestCase):
    def test_missing_r2_config_fails_closed(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(media.PublicMediaNotConfigured):
                media.ensure_public_video("https://github.com/Venloud/horror-shorts/releases/download/t/v.mp4",
                                          "2026-10-23_2249")

    def test_invalid_public_origin_not_accepted(self):
        with patch.dict(os.environ, {
            "CLOUDFLARE_ACCOUNT_ID": "account", "R2_ACCESS_KEY_ID": "key",
            "R2_SECRET_ACCESS_KEY": "secret", "R2_BUCKET": "bucket",
            "R2_PUBLIC_BASE_URL": "https://github.com/releases/signed?token=temporary"}, clear=True):
            with self.assertRaises(media.PublicMediaNotConfigured):
                media.settings()

    def test_public_preflight_rejects_signed_urls(self):
        with self.assertRaises(RuntimeError):
            media.assert_public_video("https://cdn.example.test/clip.mp4?X-Amz-Expires=600")

    def test_preflight_rejects_wrong_mime(self):
        class Response:
            status_code = 200
            url = "https://cdn.example.test/clip.mp4"
            headers = {"Content-Type": "text/html"}
            def raise_for_status(self):
                pass
            def close(self):
                pass
        with patch.object(media.requests, "get", return_value=Response()):
            with self.assertRaises(RuntimeError):
                media.assert_public_video("https://cdn.example.test/clip.mp4")

    def test_preflight_accepts_direct_permanent_video(self):
        class Response:
            status_code = 206
            url = "https://cdn.example.test/clip.mp4"
            headers = {"Content-Type": "video/mp4"}
            def raise_for_status(self):
                pass
            def close(self):
                pass
        with patch.object(media.requests, "get", return_value=Response()):
            media.assert_public_video("https://cdn.example.test/clip.mp4")


if __name__ == "__main__":
    unittest.main()
