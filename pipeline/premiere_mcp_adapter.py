"""Local Premiere MCP handoff manifest writer."""
from __future__ import annotations
import json
from pathlib import Path

def handoff(video: Path, workdir: Path, story: dict | None = None) -> dict:
    outdir = Path(workdir) / "premiere_mcp"
    outdir.mkdir(parents=True, exist_ok=True)
    result = {
        "integration": "Adobe Premiere Pro MCP",
        "operation": "review_handoff",
        "mutation": False,
        "source_video": str(Path(video).resolve()),
        "story_id": (story or {}).get("story_id"),
        "title": (story or {}).get("title"),
        "verify_first": "verify_premiere_connection",
        "local_only": True,
    }
    path = outdir / "handoff.json"
    path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"manifest": str(path), "local_only": True}
