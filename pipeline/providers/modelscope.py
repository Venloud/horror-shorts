"""ModelScope image-generation adapter.

Uses the current async OpenAI-compatible image-generation endpoint:
POST /v1/images/generations, then GET /v1/tasks/{task_id}.
"""
from __future__ import annotations
import time
import requests

BASE = "https://api-inference.modelscope.cn"


def key() -> str:
    import os
    return (os.environ.get("MODELSCOPE_TOKEN") or os.environ.get("MODELSCOPE_API_KEY") or "").strip()


def generate_image(prompt: str, *, model: str = "Qwen/Qwen-Image-2.1",
                   timeout: int = 240) -> bytes:
    token = key()
    if not token:
        raise RuntimeError("ModelScope image provider disabled: MODELSCOPE_TOKEN missing")
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    r = requests.post(
        f"{BASE}/v1/images/generations",
        headers={**headers, "X-ModelScope-Async-Mode": "true"},
        json={"model": model, "prompt": prompt[:8000]},
        timeout=60,
    )
    if r.status_code not in (200, 201):
        raise RuntimeError(f"ModelScope image submit HTTP {r.status_code}: {r.text[:240]}")
    task_id = r.json().get("task_id")
    if not task_id:
        raise RuntimeError(f"ModelScope image submit returned no task_id: {r.text[:240]}")
    deadline = time.time() + timeout
    while time.time() < deadline:
        q = requests.get(
            f"{BASE}/v1/tasks/{task_id}",
            headers={**headers, "X-ModelScope-Task-Type": "image_generation"},
            timeout=60,
        )
        if q.status_code != 200:
            raise RuntimeError(f"ModelScope task HTTP {q.status_code}: {q.text[:240]}")
        data = q.json()
        status = str(data.get("task_status", "")).upper()
        if status == "SUCCEED":
            urls = data.get("output_images") or []
            if not urls:
                raise RuntimeError("ModelScope task succeeded without output_images")
            img = requests.get(urls[0], timeout=90)
            img.raise_for_status()
            return img.content
        if status == "FAILED":
            raise RuntimeError(f"ModelScope image task failed: {str(data)[:240]}")
        time.sleep(5)
    raise RuntimeError(f"ModelScope image task timed out after {timeout}s")
