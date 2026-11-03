"""Openverse fallback in pipeline/get_sfx.py (mocked HTTP, no network)."""
import importlib
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))

MP3 = b"ID3" + b"\x00" * 64


class Reply:
    def __init__(self, status=200, body=None, content=b"", headers=None):
        self.status_code, self._body, self.content, self.headers = status, body or {}, content, headers or {}
        self.ok = status < 400

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def hit(i, lic, seconds, **kw):
    return {"id": f"a{i}", "title": f"creak {i}", "url": f"https://cdn.example/{i}.mp3", "creator": f"m{i}",
            "license": lic, "duration": seconds * 1000, "source": "freesound",
            "foreign_landing_url": f"https://freesound.org/s/{i}", **kw}


@pytest.fixture
def sfx(monkeypatch):
    monkeypatch.setenv("NIGHTFILES_OPENVERSE_SFX", "1")
    monkeypatch.delenv("FREESOUND_API_KEY", raising=False)
    import get_sfx
    return importlib.reload(get_sfx)


def test_openverse_filters_license_duration_and_mp3(sfx):
    body = {"results": [hit(1, "by", 3), hit(2, "cc0", 40), hit(3, "cc0", 4), hit(4, "pdm", 5)]}

    def get(url, **kw):
        if "api.openverse.org" in url:
            assert kw["params"]["license"] == "cc0,pdm"
            return Reply(body=body)
        return Reply(content=b"<html>" if url.endswith("3.mp3") else MP3)

    with patch.object(sfx.requests, "get", side_effect=get):
        data, credit = sfx.openverse("door creak", [1, 15])
    assert data == MP3 and "creak 4" in credit and "Public Domain Mark" in credit and "freesound.org/s/4" in credit


def test_openverse_errors(sfx):
    with patch.object(sfx.requests, "get", return_value=Reply(429, headers={"Retry-After": "60"})):
        with pytest.raises(RuntimeError, match="rate limit"):
            sfx.openverse("x", [1, 15])
    with patch.object(sfx.requests, "get", return_value=Reply(body={"detail": "bad"})):
        with pytest.raises(RuntimeError, match="no results list"):
            sfx.openverse("x", [1, 15])
    with patch.object(sfx.requests, "get", return_value=Reply(body={"results": [hit(1, "by-nc", 3)]})):
        with pytest.raises(RuntimeError, match="no CC0"):
            sfx.openverse("x", [1, 15])


def test_main_falls_back_only_when_enabled(sfx, tmp_path, monkeypatch):
    monkeypatch.setattr(sfx, "OUT", tmp_path / "sfx")
    monkeypatch.setattr(sfx, "ROOT", tmp_path)
    (tmp_path / "data").mkdir()
    monkeypatch.setattr(sfx, "SOURCES", {"door": {"fs": "door creak", "dur": [1, 15]}})
    with patch.object(sfx, "openverse", return_value=(MP3, "Openverse credit")) as ov:
        assert sfx.main() == 0
        ov.assert_called_once()
    assert (tmp_path / "sfx" / "door.mp3").read_bytes() == MP3
    monkeypatch.setattr(sfx, "OPENVERSE_SFX", False)
    with patch.object(sfx, "openverse") as ov:
        assert sfx.main() == 1, "without the flag, a missing Freesound key still fails as before"
        ov.assert_not_called()
