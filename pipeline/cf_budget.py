"""Cloudflare neurons used per UTC day, by every build (tests and production).

The free allocation is 10,000 neurons/day (resets 00:00 UTC). Test builds may use at most `cloudflare_test_share`
(35%) of it, so a day of testing can never starve production. The ledger is cache/cf-usage/usage.json, carried
from run to run by build.yml (Actions cache "cf-usage-*", saved even when a build fails). Our own count is an
estimate (images.py: 4.8 neurons per 512x512 tile + 9.6 per step); Cloudflare's own 4006 answer still wins.
"""
import json
from datetime import datetime, timezone

from common import CONFIG, ROOT, log

PATH = ROOT / "cache" / "cf-usage" / "usage.json"
IMAGE_NEURONS = 57.6  # one 1024x1024 FLUX schnell image at 4 steps


def limit() -> float:
    return float(CONFIG.get("cloudflare_daily_neurons", 10000))


def test_cap() -> float:
    return limit() * float(CONFIG.get("cloudflare_test_share", 0.35))


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def load() -> dict:
    try:
        d = json.loads(PATH.read_text())
    except (OSError, ValueError):
        d = {}
    if d.get("day") != _today():  # a new UTC day: Cloudflare's allocation reset too
        d = {"day": _today(), "tests": 0.0, "production": 0.0}
    return d


def _save(d: dict) -> None:
    try:
        PATH.parent.mkdir(parents=True, exist_ok=True)
        PATH.write_text(json.dumps(d))
    except OSError as e:
        log(f"Cloudflare usage not saved ({e})")


def add(neurons: float) -> None:
    import images
    d = load()
    d["tests" if images.test_mode() else "production"] += float(neurons)
    _save(d)


def test_room() -> float:
    """Neurons a test build may still use today."""
    return max(0.0, test_cap() - load()["tests"])


def test_allowed(neurons: float = IMAGE_NEURONS) -> bool:
    return test_room() >= neurons


def line() -> str:
    d = load()
    return (f"Cloudflare today: {d['tests'] + d['production']:.0f}/{limit():.0f} "
            f"(tests {d['tests']:.0f}, production {d['production']:.0f})")
