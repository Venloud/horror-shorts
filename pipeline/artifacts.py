"""Inspectible, resumable run artifact manifest inspired by Content Machine/Video Factory.

No network calls. Each production run gets a JSON ledger under its output directory.
"""
from __future__ import annotations
import hashlib, json, time
from pathlib import Path

class RunManifest:
    def __init__(self, workdir: Path, story_id: str = ""):
        self.path = workdir / "run_manifest.json"
        self.data = {
            "schema": 1,
            "started_at": time.time(),
            "story_id": story_id,
            "stages": [],
            "artifacts": [],
            "provider_snapshot": [],
        }
        self._write()

    def _write(self):
        self.path.write_text(json.dumps(self.data, indent=2, ensure_ascii=False), encoding="utf-8")

    def provider_snapshot(self, providers):
        self.data["provider_snapshot"] = providers
        self._write()

    def stage(self, name: str, status: str, **meta):
        self.data["stages"].append({"name": name, "status": status, "time": time.time(), **meta})
        self._write()

    def artifact(self, path: Path, kind: str):
        if not path.exists():
            return
        digest = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() and path.stat().st_size < 50_000_000 else None
        self.data["artifacts"].append({
            "path": str(path),
            "kind": kind,
            "bytes": path.stat().st_size if path.is_file() else 0,
            "sha256": digest,
        })
        self._write()

    def finish(self, status: str):
        self.data["finished_at"] = time.time()
        self.data["status"] = status
        self._write()
