"""Fail-closed, disabled-by-default selector for owner-approved ORIGINAL horror trilogies.

Does not publish, schedule, generate art, or approve concepts. Reuses the regular
Night Files writer checkpoint, story bible, narrator, rendering, QA and FIFO buffer.
Eligibility uses explicitly verified PUBLIC posts, never drafts or Buffer queue
receipts. Every approved story file is SHA-256 pinned in one approved manifest.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from common import ROOT

SERIES_DIR = ROOT / "data" / "series"
REQUIRED_APPROVALS = ("concept", "scripts", "visuals", "production")


class SeriesSafetyError(ValueError):
    """An enabled serialized production configuration is incomplete or unsafe."""


def utc(value: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise SeriesSafetyError("Missing UTC timestamp")
    try:
        d = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SeriesSafetyError("Invalid UTC timestamp") from exc
    if d.tzinfo is None or d.utcoffset() != timedelta(0):
        raise SeriesSafetyError("Series timestamps must have UTC timezone")
    return d.astimezone(timezone.utc)


def _verified_publications(history: list[dict]) -> list[tuple[datetime, str]]:
    """Count a VIDEO once across platforms, only with explicit public evidence."""
    posts: dict[str, datetime] = {}
    for entry in history:
        if entry.get("skipped") or not entry.get("title"):
            continue
        at = entry.get("public_confirmed_at")
        url = entry.get("public_post_url")
        provenance = entry.get("public_confirmation_source")
        if not (at and url and provenance and str(url).startswith("https://")):
            # TikTok SEND_TO_USER_INBOX, 'posted', Buffer 'queued', and accepted
            # workflow runs are deliberately NOT proof of a public post.
            continue
        key = str(entry.get("story_id") or entry.get("buffered") or entry.get("date") or "")
        if not key:
            continue
        timestamp = utc(at)
        if key not in posts or timestamp < posts[key]:
            posts[key] = timestamp
    return [(at, key) for key, at in posts.items()]


def prior_series_starts(history: list[dict]) -> list[tuple[datetime, str]]:
    """A trilogy begins when Episode 1 is VERIFIED PUBLIC, never at render time."""
    starts = []
    verified = {key for _, key in _verified_publications(history)}
    for entry in history:
        if entry.get("series_episode") != 1 or not entry.get("series_id"):
            continue
        key = str(entry.get("story_id") or entry.get("buffered") or entry.get("date") or "")
        if key not in verified:
            # Treat an unconfirmed episode as unfinished/pending. Do not start
            # a new trilogy while the existing one's public state is unknown.
            continue
        starts.append((utc(entry["public_confirmed_at"]), str(entry["series_id"])))
    return sorted(starts)


def new_series_eligible(history: list[dict], now: datetime, min_days=7, min_posts=14) -> tuple[bool, str]:
    if now.tzinfo is None:
        raise SeriesSafetyError("An aware UTC 'now' is required")
    if any(e.get("series_episode") == 1 and
           not (e.get("public_confirmed_at") and e.get("public_post_url") and
                e.get("public_confirmation_source")) for e in history):
        return False, "Earlier trilogy episode 1 has no verified public delivery"
    # An earlier trilogy is not completed until all THREE episodes are
    # publicly confirmed. Buffered files and drafts cannot satisfy this gate.
    ids = {str(e["series_id"]) for e in history if e.get("series_id")}
    for sid in ids:
        public_nums = {e.get("series_episode") for e in history
                       if str(e.get("series_id")) == sid and
                       all(e.get(k) for k in ("public_confirmed_at",
                                              "public_post_url",
                                              "public_confirmation_source"))}
        if public_nums != {1, 2, 3}:
            return False, "Existing trilogy has unfinished or unconfirmed episodes"
    starts = prior_series_starts(history)
    if not starts:
        return True, "First series, requires explicit approved baseline and owner gates"
    last, _ = starts[-1]
    if now.astimezone(timezone.utc) - last < timedelta(days=min_days):
        return False, "Seven full days have not passed"
    count = sum(1 for at, _ in _verified_publications(history) if last <= at <= now)
    if count < min_posts:
        return False, f"Only {count} verified public Night Files posts since last series, need {min_posts}"
    return True, f"{count} confirmed posts and >= {min_days} days"


def _load(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SeriesSafetyError("Missing or invalid series record: " + path.name) from exc
    if not isinstance(value, dict):
        raise SeriesSafetyError("Series records must be JSON objects")
    return value


def _pinned_file(name: str, digest: str) -> tuple[dict, str]:
    if (not isinstance(name, str) or not name.endswith(".json") or
            Path(name).name != name or not isinstance(digest, str) or len(digest) != 64):
        raise SeriesSafetyError("A series file needs a safe basename and SHA-256")
    source = SERIES_DIR / name
    try:
        raw = source.read_bytes()
    except OSError as exc:
        raise SeriesSafetyError("Approved file unavailable: " + name) from exc
    checksum = hashlib.sha256(raw).hexdigest()
    if checksum != digest:
        raise SeriesSafetyError("Approved file changed since owner review: " + name)
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise SeriesSafetyError("Approved file is not JSON: " + name) from exc
    if not isinstance(data, dict):
        raise SeriesSafetyError("Approved file must be an object: " + name)
    return data, checksum


def approved_package(config: dict) -> tuple[dict, dict, list[dict]] | None:
    opts = config.get("occasional_trilogies") or {}
    if not opts.get("enabled", False):
        return None
    name = opts.get("approved_manifest")
    if name != "approved.json":
        raise SeriesSafetyError("Series enabled without explicit approved.json manifest")
    manifest = _load(SERIES_DIR / name)
    if manifest.get("kind") != "original_fiction_trilogy" or not manifest.get("series_id"):
        raise SeriesSafetyError("Trilogy must be explicitly identified as original fiction")
    approvals = manifest.get("approval") or {}
    if any(approvals.get(k) is not True for k in REQUIRED_APPROVALS):
        raise SeriesSafetyError("Concept, scripts, visuals and production all need owner approval")
    if approvals.get("approved_by") != "owner" or not approvals.get("approved_at"):
        raise SeriesSafetyError("Approval must identify the owner and UTC timestamp")
    utc(approvals["approved_at"])
    baseline = manifest.get("initial_baseline") or {}
    if not baseline.get("recorded_at") or not isinstance(baseline.get("confirmed_posts"), int) or (
            baseline.get("confirmed_posts") < 0) or not baseline.get("evidence"):
        raise SeriesSafetyError("First-series baseline must be explicitly documented")
    utc(baseline["recorded_at"])
    bible_ref = manifest.get("bible") or {}
    bible, _ = _pinned_file(bible_ref.get("file"), bible_ref.get("sha256"))
    if bible.get("series_id") != manifest["series_id"] or bible.get("fiction") is not True:
        raise SeriesSafetyError("Series bible identity/fiction flag does not match")
    if not (isinstance(bible.get("characters"), list) and
            isinstance(bible.get("clues"), list) and
            isinstance(bible.get("episode_outlines"), list) and len(bible["episode_outlines"]) == 3):
        raise SeriesSafetyError("Approved bible requires characters, clues, three episode outlines")
    episodes = manifest.get("episodes") or []
    if len(episodes) != 3 or [e.get("number") for e in episodes] != [1, 2, 3]:
        raise SeriesSafetyError("Only complete, ordered three-episode plans are allowed")
    return manifest, bible, episodes


def select_approved_story(history: list[dict], config: dict,
                          now: datetime | None = None) -> dict | None:
    """None means leave the existing standalone writer 100% unchanged."""
    package = approved_package(config)
    if package is None:
        return None
    manifest, bible, episodes = package
    sid = str(manifest["series_id"])
    now = now or datetime.now(timezone.utc)

    # Fail closed for unfinished trilogies of *any* identity before another starts.
    other = [h for h in history if h.get("series_id") and h["series_id"] != sid]
    for prev_sid in {str(h["series_id"]) for h in other}:
        nums = {h.get("series_episode") for h in other if h["series_id"] == prev_sid}
        if nums != {1, 2, 3}:
            return None

    existing = [h for h in history if h.get("series_id") == sid]
    completed = {h.get("series_episode") for h in existing}
    if 3 in completed:
        return None
    if any(n not in (1, 2, 3) for n in completed):
        raise SeriesSafetyError("Bad episode index in history")
    number = next((n for n in (1, 2, 3) if n not in completed), None)
    if number is None:
        return None
    if number == 1:
        options = config.get("occasional_trilogies") or {}
        # Owner's fixed minimums cannot be relaxed by local config.
        days = max(7, int(options.get("minimum_days_between_starts", 7)))
        posts = max(14, int(options.get("minimum_verified_public_posts", 14)))
        eligible, _ = new_series_eligible(history, now, min_days=days, min_posts=posts)
        if not eligible:
            return None
    else:
        # A buffered episode, TikTok draft or Buffer queue is not an approved
        # public series episode. Do not draft #2/#3 until previous is confirmed.
        previous = [h for h in existing if h.get("series_episode") == number - 1]
        if len(previous) != 1 or not all((previous[0].get(k) for k in
                                          ("public_confirmed_at", "public_post_url",
                                           "public_confirmation_source"))):
            return None
        if any(h.get("series_episode") not in range(1, number) for h in existing):
            raise SeriesSafetyError("Series order inconsistent with history")

    part = episodes[number - 1]
    story, _ = _pinned_file(part.get("file"), part.get("sha256"))
    if story.get("series_id") != sid or story.get("series_episode") != number:
        raise SeriesSafetyError("Approved episode identity does not match manifest")
    if story.get("true_story") is not False or story.get("mode") != "fiction":
        raise SeriesSafetyError("Original series cannot be labelled documented history")
    from story import _validate
    _validate(story)
    if not story.get("title") or not story.get("scenes") or not story.get("characters"):
        raise SeriesSafetyError("Approved script needs title, scenes and characters")
    story["source"] = f"approved-series:{sid}:episode-{number}"
    story["series_bible"] = bible
    story["series_review_sha256"] = part["sha256"]
    # Never rewrite an owner-approved final script in explainer.adapt.
    story["explainer_adapted"] = True
    return story
