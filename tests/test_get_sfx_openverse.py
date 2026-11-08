"""Offline runtime SFX fallback contracts; acquisition has its own HTTP/rights tests."""
import importlib
import sys
from pathlib import Path
from unittest.mock import patch
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))
MP3 = b"ID3" + b"0" * 64

@pytest.fixture
def sfx(tmp_path, monkeypatch):
    monkeypatch.setenv("NIGHTFILES_OPENVERSE_SFX", "1")
    monkeypatch.delenv("FREESOUND_API_KEY", raising=False)
    import get_sfx
    obj = importlib.reload(get_sfx)
    monkeypatch.setattr(obj, "OUT", tmp_path / "sfx")
    monkeypatch.setattr(obj, "ROOT", tmp_path)
    monkeypatch.setattr(obj, "SOURCES", {"door": {"fs": "door creak", "dur": [1, 15]}})
    (tmp_path / "data").mkdir()
    return obj

def hit(seconds=3, **kw):
    return {"id": "a", "duration": seconds * 1000, **kw}

def test_openverse_filters_duration_and_records_rights(sfx, tmp_path):
    from pipeline import openverse_assets as ov
    cached = tmp_path / "cached"
    cached.with_suffix(".mp3").write_bytes(M3 := MP3)
    record = {"license": "cc0", "source_verified": True, "attribution": "Openverse CC0 credit"}
    with patch.object(ov, "search", return_value=[hit(30), hit(3)]), \
            patch.object(ov, "acquire", return_value=(cached, record)) as acquire:
        meta = {}
        data, credit = sfx.openverse("door creak", [1, 15], meta)
    assert data == M3 and meta == record and "CC0" in credit
    assert acquire.call_count == 1

def test_openverse_failure_is_bounded(sfx):
    from pipeline import openverse_assets as ov
    with patch.object(ov, "search", return_value=[hit()]), patch.object(ov, "acquire", side_effect=ValueError("unverified")):
        with pytest.raises(RuntimeError, match="no CC0"):
            sfx.openverse("x", [1, 15])

def test_ensure_uses_fallback_without_freesound_key(sfx):
    def fallback(q, dur, meta):
        meta.update(license="cc0", source_verified=True, source_url="https://source.example/a")
        return MP3, "CC0 credit"
    with patch.object(sfx, "openverse", side_effect=fallback) as get:
        path = sfx.ensure("door")
        assert path and path.read_bytes() == MP3 and path.with_suffix(".license.json").exists()
        assert sfx.ensure("door") == path
        assert get.call_count == 1

def test_ensure_off_keeps_previous_silent_fallback(sfx, monkeypatch):
    monkeypatch.setattr(sfx, "OPENVERSE_SFX", False)
    with patch.object(sfx, "openverse") as get:
        assert sfx.ensure("door") is None
        get.assert_not_called()

def test_main_falls_back_only_when_enabled(sfx, monkeypatch):
    with patch.object(sfx, "openverse", return_value=(MP3, "Openverse credit")) as get:
        assert sfx.main() == 0
        get.assert_called_once()
    monkeypatch.setattr(sfx, "OPENVERSE_SFX", False)
    with patch.object(sfx, "openverse") as get:
        assert sfx.main() == 1
        get.assert_not_called()
