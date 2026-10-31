"""Downloads the sound-effect library into assets/sfx (run by the 'Download sound effects' workflow).

Sources (both free for commercial use, no credit required):
  - BigSoundBank (CC0), by sound ID
  - Freesound, searched automatically, CC0 results only, most-downloaded first (needs FREESOUND_API_KEY)
"""
import json
import os
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "sfx"
SOURCES = json.loads((ROOT / "data" / "sfx_sources.json").read_text())
UA = {"User-Agent": "Mozilla/5.0 (NightFilesBot)"}
FS_KEY = os.environ.get("FREESOUND_API_KEY", "").strip()


def is_mp3(data: bytes) -> bool:
    return data[:3] == b"ID3" or data[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2")


def bigsoundbank(sid: str) -> tuple[bytes, str]:
    url = f"https://bigsoundbank.com/UPLOAD/mp3/{sid}.mp3"
    r = requests.get(url, headers=UA, timeout=60)
    r.raise_for_status()
    return r.content, f"BigSoundBank #{sid} (CC0) {url}"


def freesound(query: str, dur: list[float], meta: dict | None = None) -> tuple[bytes, str]:
    if not FS_KEY:
        raise RuntimeError("no FREESOUND_API_KEY secret")
    params = {
        "query": query,
        "filter": f'license:"Creative Commons 0" duration:[{dur[0]} TO {dur[1]}]',
        "sort": "downloads_desc",
        "fields": "id,name,username,previews,duration,license",
        "page_size": 5,
        "token": FS_KEY,
    }
    for path in ("search/text/", "search/"):
        r = requests.get(f"https://freesound.org/apiv2/{path}", params=params, headers=UA, timeout=60)
        if r.status_code != 404:
            break
    r.raise_for_status()
    results = r.json().get("results", [])
    if not results:
        raise RuntimeError(f"no CC0 results for '{query}'")
    for hit in results:
        prev = (hit.get("previews") or {}).get("preview-hq-mp3")
        if not prev:
            continue
        a = requests.get(prev, headers=UA, timeout=60)
        if a.ok and is_mp3(a.content):
            if meta is not None:
                meta.update({"source": "freesound", "freesound_id": hit["id"], "title": hit.get("name"),
                             "author": hit.get("username"), "license": hit.get("license") or "Creative Commons 0",
                             "url": f"https://freesound.org/s/{hit['id']}/", "query": query,
                             "duration": hit.get("duration")})
            return a.content, f"Freesound #{hit['id']} '{hit['name']}' by {hit['username']} (CC0)"
    raise RuntimeError(f"could not download any result for '{query}'")


DOWNLOADED: list[str] = []  # names fetched by ensure() in this run (main.py copies them next to the video)


def ensure(name: str) -> Path | None:
    """assets/sfx/<name>.mp3 for the editor, fetched once from Freesound (CC0 ONLY, sfx_sources.json query) when it
    is missing, with assets/sfx/<name>.license.json (id, author, url, licence). None when it can't be had: no
    FREESOUND_API_KEY (logged loudly, the effect stays silent), no CC0 result, or a network error."""
    path = OUT / f"{name}.mp3"
    if path.exists():
        return path
    info = SOURCES.get(name) or {}
    if "fs" not in info:
        return None
    if not FS_KEY:
        print(f"SFX: FREESOUND_API_KEY is not set: '{name}' cannot be fetched (CC0), that effect sound is skipped")
        return None
    try:
        meta: dict = {}
        data, credit = freesound(info["fs"], info.get("dur", [0.05, 3]), meta)
        if not is_mp3(data) or "creative commons 0" not in str(meta.get("license", "")).lower() \
                and "publicdomain/zero" not in str(meta.get("license", "")).lower():
            raise RuntimeError(f"not a CC0 mp3 ({meta.get('license')})")
        OUT.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        meta.update({"name": name, "credit": credit,
                     "fetched_at": __import__("datetime").datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")})
        (OUT / f"{name}.license.json").write_text(json.dumps(meta, indent=1, ensure_ascii=False))
        DOWNLOADED.append(name)
        print(f"SFX: fetched '{name}' from Freesound: {credit}")
        return path
    except Exception as e:  # noqa: BLE001
        print(f"SFX: could not fetch '{name}' from Freesound ({str(e)[:160]}); that effect sound is skipped")
        return None


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    credits, failed = {}, []
    if not FS_KEY:
        print("NOTE: FREESOUND_API_KEY not set, so Freesound sounds are skipped (BigSoundBank ones still download).")
    for name, info in SOURCES.items():
        if name.startswith("_"):
            continue
        try:
            if "bsb" in info:
                data, credit = bigsoundbank(info["bsb"])
            else:
                data, credit = freesound(info["fs"], info.get("dur", [1, 15]))  # noqa: E501
            if not is_mp3(data):
                raise RuntimeError("not an mp3")
            (OUT / f"{name}.mp3").write_bytes(data)
            credits[name] = credit
            print(f"OK    {name:20s} {credit}")
        except Exception as e:  # noqa: BLE001
            failed.append(name)
            print(f"FAIL  {name:20s} {e}")
    (ROOT / "data" / "sfx_credits.json").write_text(json.dumps(credits, indent=2, ensure_ascii=False))
    print(f"\n{len(credits)} downloaded, {len(failed)} failed: {', '.join(failed) or 'none'}")
    return 0 if credits else 1


if __name__ == "__main__":
    sys.exit(main())
