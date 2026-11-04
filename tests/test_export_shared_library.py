"""One-way Night Files -> shared library export, offline from a LIBRARY_DIR folder. Skipped without vandam_assets."""
import json
import sys
from pathlib import Path

import pytest

pytest.importorskip("vandam_assets")
from vandam_assets import Library  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import export_shared_library as ex  # noqa: E402


def entry(i, **kw):
    base = {"id": f"a{i}", "file": f"a{i}.jpg", "kind": "image", "source": "wikimedia", "url": f"https://c/{i}",
            "license": "CC0 1.0", "author": "X", "description": "empty lighthouse at dusk",
            "tags": ["lighthouse", "dusk"], "character_specific": False, "subjects": []}
    return {**base, **kw}


def test_exports_only_reusable(tmp_path, monkeypatch, capsys):
    src = tmp_path / "nf"
    src.mkdir()
    assets = [entry(1), entry(2, character_specific=True), entry(3, source="ai", license="AI-generated (Night Files)"),
              entry(4, license="CC BY-SA 4.0"), entry(5, subjects=["mara"]), entry(6, license="CC BY 4.0")]
    for i, a in enumerate(assets, 1):
        (src / a["file"]).write_bytes(f"img{i}".encode())
    (src / "index.json").write_text(json.dumps({"assets": assets}))
    monkeypatch.setenv("VANDAM_ASSET_LIBRARY", str(tmp_path / "lib"))

    assert ex.main(["--dir", str(src)]) == 0          # dry run writes nothing
    assert not (tmp_path / "lib").exists()

    assert ex.main(["--dir", str(src), "--apply"]) == 0
    recs = Library(tmp_path / "lib").records().values()
    assert sorted(r["nightfiles_id"] for r in recs) == ["a1", "a6"]
    assert all(r["rights_status"] == "verified" and r["added_by"] == "nightfiles" for r in recs)
    assert ex.main(["--dir", str(src), "--apply"]) == 0   # second run: nothing new
    assert len(Library(tmp_path / "lib").records()) == 2
    assert Library(tmp_path / "lib").find("lighthouse dusk", "image", "bouriko")
