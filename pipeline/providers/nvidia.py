"""NVIDIA NIM/API Catalog adapters.

Image: FLUX.2-klein-4b at /v1/genai/black-forest-labs/flux.2-klein-4b.
Video: Cosmos3-Nano at /v1/cosmos/nvidia/cosmos3-nano.

Both are opt-in through NVIDIA_API_KEY. NVIDIA's hosted endpoints can be rate
limited, so callers must treat failures as fallthrough conditions.
"""
from __future__ import annotations
import base64
import requests

IMAGE_URL = "https://ai.api.nvidia.com/v1/genai/black-forest-labs/flux.2-klein-4b"
VIDEO_URL = "https://ai.api.nvidia.com/v1/cosmos/nvidia/cosmos3-nano"


def key() -> str:
    import os
    return (os.environ.get("NVIDIA_API_KEY") or os.environ.get("NVIDIA_NIM_API_KEY") or "").strip()


def generate_image(prompt: str, seed: int, steps: int = 4) -> bytes:
    token = key()
    if not token:
        raise RuntimeError("NVIDIA image provider disabled: NVIDIA_API_KEY missing")
    body = {
        "mode": "Image Generation",
        "prompt": prompt[:10000],
        "height": 1024,
        "width": 1024,
        "cfg_scale": 0,
        "samples": 1,
        "seed": int(seed) % 2_147_483_647,
        "steps": max(1, min(4, int(steps))),
    }
    r = requests.post(IMAGE_URL, headers={"Authorization": f"Bearer {token}",
                                           "Accept": "application/json",
                                           "Content-Type": "application/json"},
                      json=body, timeout=180)
    if r.status_code != 200:
        raise RuntimeError(f"NVIDIA FLUX.2 HTTP {r.status_code}: {r.text[:240]}")
    data = r.json()
    encoded = data.get("image") or data.get("b64_image") or (data.get("data") or [{}])[0].get("b64_json")
    if not encoded:
        raise RuntimeError(f"NVIDIA FLUX.2 returned no image: {str(data)[:240]}")
    if encoded.startswith("data:"):
        encoded = encoded.split(",", 1)[1]
    return base64.b64decode(encoded, validate=True)


def generate_image_video(image_bytes: bytes, prompt: str, *, resolution: str = "480_16_9",
                         num_frames: int = 25, steps: int = 35, fps: int = 24) -> bytes:
    token = key()
    if not token:
        raise RuntimeError("NVIDIA video provider disabled: NVIDIA_API_KEY missing")
    import mimetypes
    mime = "image/png"
    ref = "data:image/png;base64," + base64.b64encode(image_bytes).decode("ascii")
    body = {
        "model_mode": "image2video",
        "prompt": prompt[:4000],
        "input_reference": ref,
        "resolution": resolution,
        "num_frames": max(25, int(num_frames)),
        "num_inference_steps": int(steps),
        "fps": int(fps),
    }
    r = requests.post(VIDEO_URL, headers={"Authorization": f"Bearer {token}",
                                          "Accept": "application/json",
                                          "Content-Type": "application/json"},
                      json=body, timeout=900)
    if r.status_code != 200:
        raise RuntimeError(f"NVIDIA Cosmos3-Nano I2V HTTP {r.status_code}: {r.text[:240]}")
    encoded = r.json().get("b64_video")
    if not encoded:
        raise RuntimeError("NVIDIA Cosmos3-Nano I2V returned no video")
    return base64.b64decode(encoded, validate=True)


def generate_video(prompt: str, *, resolution: str = "480_16_9",
                   num_frames: int = 25, steps: int = 35, fps: int = 24) -> bytes:
    token = key()
    if not token:
        raise RuntimeError("NVIDIA video provider disabled: NVIDIA_API_KEY missing")
    body = {
        "model_mode": "text2video",
        "prompt": prompt[:4000],
        "resolution": resolution,
        "num_frames": max(25, int(num_frames)),
        "num_inference_steps": int(steps),
        "fps": int(fps),
    }
    r = requests.post(VIDEO_URL, headers={"Authorization": f"Bearer {token}",
                                          "Accept": "application/json",
                                          "Content-Type": "application/json"},
                      json=body, timeout=900)
    if r.status_code != 200:
        raise RuntimeError(f"NVIDIA Cosmos3-Nano HTTP {r.status_code}: {r.text[:240]}")
    data = r.json()
    encoded = data.get("b64_video")
    if not encoded:
        raise RuntimeError(f"NVIDIA Cosmos3-Nano returned no video: {str(data)[:240]}")
    return base64.b64decode(encoded, validate=True)


def chat(model: str, prompt: str, *, temperature: float = 0.7, as_json: bool = True,
         schema: dict | None = None) -> str:
    """OpenAI-compatible NVIDIA NIM chat fallback."""
    token = key()
    if not token:
        raise RuntimeError("NVIDIA text provider disabled: NVIDIA_API_KEY missing")
    if as_json:
        prompt += "\nReturn ONLY valid JSON matching this schema:\n" + str(schema or {})
    body = {"model": model, "messages": [{"role": "user", "content": prompt}],
            "temperature": float(temperature), "max_tokens": 8000}
    if as_json:
        body["response_format"] = {"type": "json_object"}
    r = requests.post("https://integrate.api.nvidia.com/v1/chat/completions",
                      headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                      json=body, timeout=180)
    if r.status_code != 200:
        raise RuntimeError(f"NVIDIA chat HTTP {r.status_code}: {r.text[:300]}")
    return r.json()["choices"][0]["message"]["content"] or ""
