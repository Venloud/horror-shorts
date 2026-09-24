"""Shared helpers: paths, config, logging, retries."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = json.loads((ROOT / "config.json").read_text())
HISTORY_FILE = ROOT / "data" / "history.json"


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def env(name: str, required: bool = True, default: str = "") -> str:
    val = os.environ.get(name, default).strip()
    if required and not val:
        sys.exit(f"Missing required secret/env var: {name}")
    return val


def retry(fn, attempts: int = 3, wait: float = 5.0, what: str = "request"):
    last = None
    for i in range(1, attempts + 1):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            last = e
            log(f"{what} failed (attempt {i}/{attempts}): {e}")
            if i < attempts:
                time.sleep(wait * i)
    raise RuntimeError(f"{what} failed after {attempts} attempts: {last}")


def run(cmd: list[str]) -> str:
    """Run a command, raise with stderr on failure."""
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(cmd[:6])}...\n{p.stderr[-3000:]}")
    return p.stdout


def media_duration(path: Path) -> float:
    out = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
               "-of", "default=nw=1:nk=1", str(path)])
    return float(out.strip())


def load_history() -> list[dict]:
    if HISTORY_FILE.exists():
        return json.loads(HISTORY_FILE.read_text() or "[]")
    return []


def save_history(items: list[dict]) -> None:
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_FILE.write_text(json.dumps(items, indent=2, ensure_ascii=False))
