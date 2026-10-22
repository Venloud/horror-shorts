"""One-time importer: original owner-approved expression PNGs, unchanged.

The owner reuploaded F04 and F05 in chat. F05 matches already imported U01 byte for byte.
F09/U04 and F10/U02 are reused from owner originals, never AI replacements.
No image redrawing/resizing; fail before writing if any hash differs.
"""
import hashlib
import pathlib
import shutil
import urllib.request
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
HOST = ROOT / "assets" / "character" / "host"
EXPR = HOST / "expressions"
REUSE = [
    ("incoming/2026-10-21/U01_excited_fists.png", "F05_excited.png",
     "dc5fe61147b62724ec39fcaf644c240fc0b34bcca2420769a18b51f7e10420d6"),
    ("incoming/2026-10-21/U04_angry_stern.png", "F09_angry.png",
     "3f8e5137f254b96a1cbe6aa9946e277cde71a4d1c26637399d6483649114136e"),
    ("incoming/2026-10-21/U02_smirk_sideeye.png", "F10_smirk.png",
     "2c6b5010266d8a76c2bc6004978a1a46a9128ad3c7803ff627e7f44afe1cef8c"),
]
F04_URL = "https://d2ol7oe51mr4n9.cloudfront.net/user_30e5Q83ZZtAGsJs78C8eMJ9sVKC/77648841-587a-4a81-93c7-f3fb3e2d4eda.png"
F04_SHA = "6182e060da26c60968ffc312bff5247dc1616d46fe70ee2110940a9e86fb11c6"

def checked(payload: bytes, expected: str, name: str):
    digest = hashlib.sha256(payload).hexdigest()
    if digest != expected:
        raise ValueError(f"{name}: original SHA mismatch: {digest}")
    if payload[:8] != bytes.fromhex("89504e470d0a1a0a"):
        raise ValueError(f"{name}: invalid PNG")
    w, h = (int.from_bytes(payload[k:k+4], "big") for k in (16, 20))
    if (w, h) != (1374, 1145):
        raise ValueError(f"{name}: unexpected image dimensions {w}x{h}")

def main():
    payloads = []
    for source, target, expected in REUSE:
        data = (HOST/source).read_bytes()
        checked(data, expected, target)
        payloads.append((EXPR/target, data, expected))
    target = EXPR/"F04_worried.png"
    if target.exists():
        data = target.read_bytes()
    else:
        req = urllib.request.Request(F04_URL, headers={"User-Agent": "NightFiles-approved-art/1"})
        with urllib.request.urlopen(req, timeout=120) as response:
            data = response.read()
    checked(data, F04_SHA, "F04_worried.png")
    payloads.append((target, data, F04_SHA))
    # all source images verified before writing anything
    EXPR.mkdir(parents=True, exist_ok=True)
    for path, data, expected in payloads:
        if path.exists():
            checked(path.read_bytes(), expected, path.name)
        else:
            path.write_bytes(data)
        print(f"VERIFIED {path.relative_to(ROOT)} sha256={expected}")
    print("SUCCESS: F04 worried, F05 excited, F09 angry, F10 smirk original PNG bytes")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("FAILED import: " + str(e), file=sys.stderr)
        sys.exit(1)
