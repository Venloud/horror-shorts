"""Single runtime registry for optional Night Files providers.

The registry is deliberately declarative. It does not make network calls and does
not claim a provider is healthy merely because credentials exist. Health/quota is
decided by the modality-specific broker.
"""
from __future__ import annotations
import os

PROVIDERS = {
    "cloudflare": {"modality": ["image", "text", "video"], "secret": "CLOUDFLARE_API_TOKEN"},
    "nvidia": {"modality": ["image", "text", "video", "vision"], "secret": "NVIDIA_API_KEY"},
    "modelscope": {"modality": ["image", "text", "video", "vision"], "secret": "MODELSCOPE_TOKEN"},
    "pollinations": {"modality": ["image"], "secret": "POLLINATIONS_API_KEY"},
    "huggingface": {"modality": ["image", "video"], "secret": "HF_TOKEN"},
    "groq": {"modality": ["text"], "secret": "GROQ_API_KEY"},
    "gemini": {"modality": ["text", "vision"], "secret": "GEMINI_API_KEY"},
}


def available(modality: str) -> list[str]:
    return [name for name, meta in PROVIDERS.items()
            if modality in meta["modality"] and os.environ.get(meta["secret"])]


def snapshot() -> list[dict]:
    return [{"provider": name, "modalities": meta["modality"],
             "configured": bool(os.environ.get(meta["secret"]))}
            for name, meta in PROVIDERS.items()]
