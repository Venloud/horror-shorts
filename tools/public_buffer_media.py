"""Stable public media for Buffer posts.

GitHub release downloads may redirect through short-lived object URLs. Buffer fetches
queued media at publication, so mirror accepted video to a durable public R2 URL.
Existing Buffer receipts remain the source of truth, and NO extra post is created.
No R2 account is provisioned and no call is made unless credentials exist.
"""
from __future__ import annotations
import hashlib
import os
import tempfile
from pathlib import Path
from urllib.parse import urlsplit
import requests


class PublicMediaNotConfigured(RuntimeError):
    pass


def settings() -> dict:
    names = ("CLOUDFLARE_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY",
             "R2_BUCKET", "R2_PUBLIC_BASE_URL")
    data = {name: os.environ.get(name, "").strip() for name in names}
    if not all(data.values()):
        raise PublicMediaNotConfigured(
            "Buffer media requires stable public R2 hosting. Configure R2_ACCESS_KEY_ID, "
            "R2_SECRET_ACCESS_KEY, R2_BUCKET and R2_PUBLIC_BASE_URL. "
            "No Buffer post was queued; existing receipts are unchanged.")
    url = urlsplit(data["R2_PUBLIC_BASE_URL"])
    if (url.scheme != "https" or not url.netloc or url.username or url.password
            or url.query or url.fragment or "github.com" in url.netloc
            or url.netloc.endswith(".r2.cloudflarestorage.com")):
        raise PublicMediaNotConfigured("R2_PUBLIC_BASE_URL must be a stable, public HTTPS delivery origin")
    return data


def assert_public_video(url: str, expected_size: int | None = None) -> None:
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.query or parsed.fragment
            or not parsed.netloc or "github.com" in parsed.netloc):
        raise RuntimeError("Video URL is not a permanent direct HTTPS media URL")
    response = requests.get(url, stream=True, headers={"Range": "bytes=0-1023"}, timeout=45)
    try:
        response.raise_for_status()
        if response.status_code not in (200, 206):
            raise RuntimeError("Public video URL returned an unsupported status")
        if urlsplit(response.url).netloc != parsed.netloc:
            raise RuntimeError("Public video URL redirects to another host (possibly expiring)")
        content_type = response.headers.get("Content-Type", "").split(";")[0].lower().strip()
        if content_type not in ("video/mp4", "application/octet-stream"):
            raise RuntimeError("Public video URL is not a direct MP4: " + content_type)
        if expected_size and response.status_code == 200:
            size = response.headers.get("Content-Length")
            if size and int(size) != expected_size:
                raise RuntimeError("Public video does not match uploaded byte length")
    finally:
        response.close()


def ensure_public_video(source_url: str, stamp: str) -> str:
    """Idempotently stage a verified public MP4, never using temporary signed URLs."""
    cfg = settings()  # fail closed *before* Buffer's durable attempt receipt
    if not source_url.startswith("https://github.com/") or not stamp.replace("_", "").replace("-", "").isdigit():
        raise ValueError("Expected a Night Files GitHub release MP4 and exact timestamp stamp")
    try:
        import boto3
    except ImportError as exc:
        raise RuntimeError("boto3 is required for the optional R2 public media mirror") from exc
    client = boto3.client(
        "s3", endpoint_url="https://" + cfg["CLOUDFLARE_ACCOUNT_ID"] + ".r2.cloudflarestorage.com",
        aws_access_key_id=cfg["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=cfg["R2_SECRET_ACCESS_KEY"], region_name="auto")
    with tempfile.TemporaryDirectory(prefix="buffer_public_media_") as folder:
        target = Path(folder) / "source.mp4"
        digest = hashlib.sha256()
        size = 0
        src = requests.get(source_url, stream=True, timeout=(15, 300))
        try:
            src.raise_for_status()
            with target.open("wb") as out:
                for block in src.iter_content(1 << 20):
                    if not block:
                        continue
                    size += len(block)
                    if size > 700 * 1024 * 1024:
                        raise RuntimeError("Video exceeds configured public media upload limit")
                    digest.update(block)
                    out.write(block)
        finally:
            src.close()
        if size < 1024:
            raise RuntimeError("GitHub release video is empty")
        fingerprint = digest.hexdigest()
        key = "night-files/youtube/" + stamp + "/" + fingerprint[:20] + ".mp4"
        try:
            existing = client.head_object(Bucket=cfg["R2_BUCKET"], Key=key)
        except client.exceptions.ClientError as exc:
            if exc.response.get("Error", {}).get("Code") not in ("404", "NoSuchKey", "NotFound"):
                raise
            existing = None
        if existing and (existing.get("Metadata") or {}).get("sha256") != fingerprint:
            raise RuntimeError("R2 object has conflicting provenance; not overwriting")
        if existing is None:
            client.upload_file(
                str(target), cfg["R2_BUCKET"], key,
                ExtraArgs={"ContentType": "video/mp4", "Metadata": {"sha256": fingerprint}})
        url = cfg["R2_PUBLIC_BASE_URL"].rstrip("/") + "/" + key
        assert_public_video(url, expected_size=size)
        return url
