"""One-time verified importer of Venloud-approved Night Files reference PNGs.

The original image files were uploaded by the owner in chat, staged at HTTPS URLs for
transfer to this repository, and checked against the SHA256 digest of EACH original byte stream.
Never infer approval from filenames alone. No neural/image generation and no resizing.
This is intentionally safe to rerun: existing correct assets are reused; wrong hashes fail.

Once all eight originals exist, retire the old unrelated vector close-up pack.
Older full-body action sprites remain until their corresponding IDs have approved replacements.
"""
from __future__ import annotations

import hashlib
import shutil
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "assets" / "character" / "host"
IMAGES = (
    ("M01", "masters/M01_front_neutral.png", "https://d2ol7oe51mr4n9.cloudfront.net/user_30e5Q83ZZtAGsJs78C8eMJ9sVKC/f06fa508-a4df-46e0-a3f1-13cba5321009.png", "73b20c204d75462fd9c56d8cc8d6cd90d2b47f03ca6dbe37e795be62db0bd57c"),
    ("M02", "masters/M02_three_quarter_neutral.png", "https://d2ol7oe51mr4n9.cloudfront.net/user_30e5Q83ZZtAGsJs78C8eMJ9sVKC/21eab4ae-4bd2-44a8-a0ec-88a22a9590c2.png", "cb1abd8b62a41ab5a209e24e46ac9fd15124d10914120e2ec57dda06d3e875bc"),
    ("M03", "masters/M03_side_neutral.png", "https://d2ol7oe51mr4n9.cloudfront.net/user_30e5Q83ZZtAGsJs78C8eMJ9sVKC/5e8ed632-99fe-4644-ba4a-33b586c164ac.png", "85013234e79cda4dde49e5722152ca015965b173ec613458c402f92521a7d461"),
    ("M04", "masters/M04_back_neutral.png", "https://d2ol7oe51mr4n9.cloudfront.net/user_30e5Q83ZZtAGsJs78C8eMJ9sVKC/f7431693-24e4-4907-becc-d748d2c25dc1.png", "271355455057782a6b22040ae2e00ddbc477c9618585927579e5d981a1887eaa"),
    ("M05", "masters/M05_front_neutral_closeup.png", "https://d2ol7oe51mr4n9.cloudfront.net/user_30e5Q83ZZtAGsJs78C8eMJ9sVKC/e838f96e-b64c-4095-b59f-3b028374d3e9.png", "70454399c941f0eda31bd9f2160676790331f6ef33d38d6cbebd0bdd9a14d23b"),
    ("F01", "expressions/F01_happy.png", "https://d2ol7oe51mr4n9.cloudfront.net/user_30e5Q83ZZtAGsJs78C8eMJ9sVKC/e31f6df8-ba5d-4995-ad77-297288c7fe47.png", "fa2e59e289eb4537fec790456e6696c0901cdf4a0d9a0240f60ec329b442774f"),
    ("F02", "expressions/F02_serious.png", "https://d2ol7oe51mr4n9.cloudfront.net/user_30e5Q83ZZtAGsJs78C8eMJ9sVKC/64130ef2-ae02-4b3c-af6a-28b4e7aa9125.png", "5d85e1c79bf25378c185a755a512f3f96f830c95d6ffc22481422efd9d772bd0"),
    ("F03", "expressions/F03_confused.png", "https://d2ol7oe51mr4n9.cloudfront.net/user_30e5Q83ZZtAGsJs78C8eMJ9sVKC/16704f93-8b7c-4cad-8cae-059feffada6e.png", "aa891339c4927fb731b7485484e487348f87daa8cdb9fd3ca0301f06597cb9eb"),
)


def validate(content: bytes, expected: str, name: str):
    got = hashlib.sha256(content).hexdigest()
    if got != expected:
        raise ValueError(f"{name}: SHA256 mismatch. Expected {expected}; got {got}")
    if content[:8] != b"\\x89PNG\\r\\n\\x1a\\n":
        raise ValueError(f"{name}: not original PNG bytes")


def main() -> int:
    missing = []
    for key, relative, url, sha in IMAGES:
        dest = BASE / relative
        if dest.exists():
            validate(dest.read_bytes(), sha, key)
            print(f"VERIFIED {key}: {dest.relative_to(ROOT)}")
            continue
        missing.append((key, relative, url, sha))

    # Download and validate ALL new images before altering old artwork.
    payloads = []
    for key, relative, url, sha in missing:
        print(f"Downloading approved original {key}...")
        with urllib.request.urlopen(
            urllib.request.Request(url, headers={"User-Agent": "NightFiles-asset-import/1.0"}),
            timeout=90,
        ) as response:
            data = response.read()
        validate(data, sha, key)
        payloads.append((relative, data))

    for relative, data in payloads:
        dest = BASE / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        print(f"SAVED {dest.relative_to(ROOT)} ({len(data):,} original bytes)")

    # Do NOT delete the old pack if this import was incomplete.
    for key, relative, _, sha in IMAGES:
        validate((BASE / relative).read_bytes(), sha, key)

    legacy = BASE / "closeups"
    if legacy.is_dir():
        shutil.rmtree(legacy)
        print("RETIRED old mismatched vector close-up pack")

    print(f"SUCCESS: {len(IMAGES)} user-approved original PNGs tracked, original bytes intact.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"IMPORT FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
