"""Cloudflare neurons used per UTC day, by every build (tests and production).

The free allocation is 10,000 neurons/day (resets 00:00 UTC). Test builds may use at most `cloudflare_test_share`
(35%) of it, so a day of testing can never starve production. The ledger is cache/cf-usage/usage.json, carried
from run to run by build.yml (Actions cache "cf-usage-*", saved even when a build fails). Our own count is an
figure: Cloudflare's own cf-ai-neurons header (172.8 per FLUX schnell image); its daily-limit answer (code 3036) still wins.
"""
import json
from datetime import datetime, timezone

from common import CONFIG, ROOT, log

PATH = ROOT / "cache" / "cf-usage" / "usage.json"
IMAGE_NEURONS = 172.8  # one FLUX schnell image, as Cloudflare bills it (header cf-ai-neurons; ~57 images/day)


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
        past = dict(d.get("past") or {})
        if d.get("day"):
            past[d["day"]] = {"tests": d.get("tests", 0.0), "production": d.get("production", 0.0)}
        past = dict(sorted(past.items())[-8:])  # last 8 days, for the daily freeze summary
        d = {"day": _today(), "tests": 0.0, "production": 0.0, "past": past}
    return d


def day_line(day: str) -> str:
    """'tests N, production N' for a past UTC day (or today)."""
    d = load()
    x = d if day == d["day"] else (d.get("past") or {}).get(day)
    if not x:
        return "no record"
    return (f"{x['tests'] + x['production']:.0f}/{limit():.0f} neurons "
            f"(tests {x['tests']:.0f}, production {x['production']:.0f}, ~{(x['tests'] + x['production']) / IMAGE_NEURONS:.0f} images)")


_REPORTED = {"done": False}


def analytics_report(force: bool = False) -> str:
    """Cloudflare's OWN count of today's Workers AI neurons (GraphQL analytics, per model and hour), logged once per
    run. Needs the API token to have Account Analytics: Read; without it the log says so. Never raises."""
    if _REPORTED["done"] and not force:
        return ""
    _REPORTED["done"] = True
    import os
    import requests
    acct, token = os.environ.get("CLOUDFLARE_ACCOUNT_ID"), os.environ.get("CLOUDFLARE_API_TOKEN")
    if not (acct and token):
        return ""
    now = datetime.now(timezone.utc)
    since = now.strftime("%Y-%m-%dT00:00:00Z")
    query = """query($acct: String!, $since: Time!, $until: Time!) { viewer { accounts(filter: {accountTag: $acct}) {
      aiInferenceAdaptiveGroups(limit: 200, filter: {datetime_geq: $since, datetime_leq: $until},
                                orderBy: [datetimeHour_ASC]) {
        sum { totalNeurons } count dimensions { modelId datetimeHour } } } } }"""
    try:
        r = requests.post("https://api.cloudflare.com/client/v4/graphql", timeout=30,
                          headers={"Authorization": f"Bearer {token}"},
                          json={"query": query, "variables": {"acct": acct, "since": since,
                                                              "until": now.strftime("%Y-%m-%dT%H:%M:%SZ")}})
        data = r.json()
        if data.get("errors"):
            errors = data["errors"]
            msg_text = str(errors)[:300]
            # Analytics is diagnostic only. A token can successfully run Workers AI
            # without having Account Analytics: Read, so never treat this as an
            # image-generation or quota failure.
            if any("authz" in str(e).lower() or "not authorized" in str(e).lower() for e in errors):
                msg = "Cloudflare analytics unavailable (Account Analytics: Read is not granted); image generation is unaffected."
            else:
                msg = f"Cloudflare analytics unavailable: {msg_text}"
            log(msg)
            return msg
        rows = data["data"]["viewer"]["accounts"][0]["aiInferenceAdaptiveGroups"]
        total = sum(float(x["sum"].get("totalNeurons") or 0) for x in rows)
        parts = [f"{x['dimensions']['datetimeHour'][11:16]} {x['dimensions']['modelId'].split('/')[-1]} "
                 f"{x['count']}x={float(x['sum'].get('totalNeurons') or 0):.0f}" for x in rows]
        msg = (f"Cloudflare's own count today (UTC): {total:.0f} neurons in {sum(x['count'] for x in rows)} calls; "
               f"our ledger: {line()}; by hour/model: {'; '.join(parts)[:900]}")
        log(msg)
        return msg
    except Exception as e:  # noqa: BLE001
        msg = f"Cloudflare analytics unavailable: {type(e).__name__}: {str(e)[:200]}"
        log(msg)
        return msg


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
