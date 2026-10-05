"""Trend picking: among the unused lore / mystery / case topics, prefer the one whose Wikipedia pageviews jumped
in the last 7 days compared with its 60-day average (free Wikimedia pageviews API, proper User-Agent).

Flag trend_picking (on). trend_min_ratio (1.5): the jump needed to count as trending; trend_sample (25): how many
unused topics are checked per pick (results cached 24 h in cache/media-search/trends.json, saved by build.yml).
Any error, or nothing trending = a random pick, exactly as before.
"""
import json
import random
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import requests

from common import CONFIG, ROOT, blocked_topic, log

UA = "NightFilesBot/1.0 (https://github.com/Venloud/horror-shorts; automated short-video builder)"
API = ("https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia/all-access/user/"
       "{title}/daily/{start}/{end}")
CACHE = ROOT / "cache" / "media-search" / "trends.json"


def _load() -> dict:
    try:
        data = json.loads(CACHE.read_text())
        return {k: v for k, v in data.items() if time.time() - v.get("at", 0) < 24 * 3600}
    except Exception:  # noqa: BLE001
        return {}


def jump(title: str, cache: dict) -> float | None:
    """Average daily views of the last 7 days / average of the 60 days before. None = unknown."""
    if title in cache:
        return cache[title].get("ratio")
    today = datetime.now(timezone.utc).date()
    start, end = today - timedelta(days=68), today - timedelta(days=1)
    r = requests.get(API.format(title=quote(title.replace(" ", "_"), safe=""), start=start.strftime("%Y%m%d"),
                                end=end.strftime("%Y%m%d")), headers={"User-Agent": UA}, timeout=20)
    ratio = None
    if r.status_code == 200:
        views = [it.get("views", 0) for it in r.json().get("items", [])]
        if len(views) >= 30:
            last7, before = views[-7:], views[:-7][-60:]
            base = sum(before) / max(1, len(before))
            ratio = round((sum(last7) / 7) / base, 2) if base >= 5 else None  # ignore near-empty pages
    cache[title] = {"ratio": ratio, "at": time.time()}
    time.sleep(0.2)  # be gentle: one request at a time
    return ratio


def pick(candidates: list, title_of=lambda c: c):
    """The unused topic with the biggest pageview jump (>= trend_min_ratio), else a random one."""
    candidates = [c for c in candidates if not blocked_topic(title_of(c))]  # config blocked_topics, every caller
    if not candidates:
        raise ValueError("no candidates")
    if not CONFIG.get("trend_picking", True):
        return random.choice(candidates)
    try:
        cache = _load()
        sample = random.sample(candidates, min(len(candidates), int(CONFIG.get("trend_sample", 25))))
        scored = []
        for c in sample:
            ratio = jump(title_of(c), cache)
            if ratio:
                scored.append((ratio, c))
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(cache))
        if scored:
            ratio, best = max(scored, key=lambda x: x[0])
            if ratio >= float(CONFIG.get("trend_min_ratio", 1.5)):
                log(f"Trending pick: '{title_of(best)}' (views last 7 days = {ratio}x its 60-day average)")
                return best
            log(f"No trending topic (best jump {ratio}x < {CONFIG.get('trend_min_ratio', 1.5)}x): random pick")
    except Exception as e:  # noqa: BLE001
        log(f"Trend check skipped ({str(e)[:120]}): random pick")
    return random.choice(candidates)
