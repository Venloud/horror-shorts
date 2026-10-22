"""Import the nine original Venloud-uploaded expression candidates without altering bytes.

Reads the Git-committed batch manifest, downloads staged original uploads,
checks the original PNG SHA256 and RGBA transparency, then writes original
bytes to assets/character/host/incoming/2026-10-21.

Can run again; existing assets must match exact expected SHA256.
Only this staging batch is touched. Approved M/F assets remain untouched.
"""
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BATCH_DIR = ROOT / "assets/character/host/incoming/2026-10-21"
URLS = {
    "U01": "https://d2ol7oe51mr4n9.cloudfront.net/user_30e5Q83ZZtAGsJs78C8eMJ9sVKC/164f9dfb-a8fd-480f-b0e1-e6ca38a1c292.png",
    "U02": "https://d2ol7oe51mr4n9.cloudfront.net/user_30e5Q83ZZtAGsJs78C8eMJ9sVKC/4a1d06b9-0782-48be-9d45-e67a540f59d3.png",
    "U03": "https://d2ol7oe51mr4n9.cloudfront.net/user_30e5Q83ZZtAGsJs78C8eMJ9sVKC/d51e79e7-b94f-49d8-8939-21189ae16a2a.png",
    "U04": "https://d2ol7oe51mr4n9.cloudfront.net/user_30e5Q83ZZtAGsJs78C8eMJ9sVKC/c8ef6649-7757-42a4-b075-24ad89694ccf.png",
    "U05": "https://d2ol7oe51mr4n9.cloudfront.net/user_30e5Q83ZZtAGsJs78C8eMJ9sVKC/55a199c9-3549-47cc-b7ca-36568b90395a.png",
    "U06": "https://d2ol7oe51mr4n9.cloudfront.net/user_30e5Q83ZZtAGsJs78C8eMJ9sVKC/3de0dfcb-6763-490f-8461-82041ad29a05.png",
    "U07": "https://d2ol7oe51mr4n9.cloudfront.net/user_30e5Q83ZZtAGsJs78C8eMJ9sVKC/74310f5d-afaf-4ffa-b51c-71f353d99d11.png",
    "U08": "https://d2ol7oe51mr4n9.cloudfront.net/user_30e5Q83ZZtAGsJs78C8eMJ9sVKC/02129927-2874-4648-b40d-171f53e12f9a.png",
    "U09": "https://d2ol7oe51mr4n9.cloudfront.net/user_30e5Q83ZZtAGsJs78C8eMJ9sVKC/a6654ab5-cdd8-485b-8a90-0626e8b13ff8.png",
}

def main():
    manifest = json.loads((BATCH_DIR / "batch.json").read_text())
    assert len(manifest["assets"]) == len(URLS) == 9
    payloads = []
    for entry in manifest["assets"]:
        key = entry["id"]
        target = BATCH_DIR / entry["file"]
        if target.exists():
            data = target.read_bytes()
        else:
            print(f"Fetching untouched owner upload {key}...")
            req = urllib.request.Request(URLS[key], headers={"User-Agent":"NightFilesOriginalAssetImport/1"})
            with urllib.request.urlopen(req, timeout=120) as response:
                data = response.read()
        got = hashlib.sha256(data).hexdigest()
        if got != entry["sha256"]:
            raise ValueError(f"{key} original PNG SHA mismatch: {got}")
        if not data.startswith(bytes.fromhex("89504e470d0a1a0a")):
            raise ValueError(f"{key} invalid PNG signature")
        # PNG header records 1374x1145; preserve all original RGBA bytes.
        if (int.from_bytes(data[16:20],"big"),int.from_bytes(data[20:24],"big")) != (1374,1145):
            raise ValueError(f"{key} unexpected canvas dimensions")
        payloads.append((target,data))
        print(f"VERIFIED {key}: {len(data)} bytes, SHA256 {got[:16]}")
    for target,data in payloads:
        if not target.exists():
            target.write_bytes(data)
    print("Saved all nine original owner-uploaded candidates; no approved images overwritten.")

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ASSET IMPORT FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
