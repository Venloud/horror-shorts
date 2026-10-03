"""Quota-aware image provider broker for Night Files.

This module is intentionally small and dependency-light. It wraps the existing image
provider functions instead of replacing the renderer or media library.

Tier order:
1. Cloudflare FLUX.1 schnell (existing caller)
2. Pollinations FLUX (optional, only when POLLINATIONS_API_KEY/POLLINATIONS_KEY exists)
3. Hugging Face ZeroGPU Spaces (existing caller, with quota preflight)
4. Local SD-Turbo CPU (existing emergency fallback)
5. Existing same-scene virtual/cached shots (existing images.py logic)
6. Real media remains upstream of AI generation in main.py

Pollinations is not treated as unlimited free capacity. Current generation requires
an API key and may consume the account's Pollen balance, so the broker skips it
unless explicitly configured.
"""
from __future__ import annotations

import os
import time
from urllib.parse import quote

import requests


def _enabled() -> bool:
    return str(os.environ.get("POLLINATIONS_IMAGE_ENABLED", "1")).lower() not in {
        "0", "false", "no", "off"
    }


def _key() -> str:
    return (os.environ.get("POLLINATIONS_API_KEY")
            or os.environ.get("POLLINATIONS_KEY")
            or "").strip()


def _quota_snapshot(images, minimum_seconds: int = 65):
    """Return (usable, remaining_seconds, reset_text).

    Unknown quota is deliberately treated as usable. The existing HF Space call
    still handles scheduler-side quota errors. This avoids falsely disabling HF
    when an older huggingface_hub package cannot expose the quota endpoint.
    """
    token = os.environ.get("HF_TOKEN")
    if not token:
        return None, None, "HF_TOKEN missing"

    try:
        from huggingface_hub import HfApi
        quota = HfApi(token=token).get_zero_gpu_quota()
        remaining = float(quota.remaining)
        reset = getattr(quota, "resets_at", None)
        reset_text = str(reset) if reset else "unknown"
        usable = remaining >= minimum_seconds
        images.log(
            f"HF ZeroGPU quota preflight: {remaining:.0f}s remaining; "
            f"minimum {minimum_seconds}s; resets_at={reset_text}"
        )
        return usable, remaining, reset_text
    except Exception as exc:
        images.log(f"HF ZeroGPU quota preflight unavailable: {type(exc).__name__}: {str(exc)[:140]}")
        return None, None, "unknown"


def _pollinations(prompt: str, seed: int, width: int, height: int) -> bytes:
    key = _key()
    if not key:
        raise RuntimeError("Pollinations disabled: no POLLINATIONS_API_KEY/POLLINATIONS_KEY")
    model = os.environ.get("POLLINATIONS_IMAGE_MODEL", "flux")
    url = "https://gen.pollinations.ai/image/" + quote(prompt[:1800], safe="")
    params = {
        "model": model,
        "width": width,
        "height": height,
        "seed": int(seed) % 2_147_483_647,
        "nologo": "true",
    }
    r = requests.get(
        url,
        params=params,
        headers={"Authorization": f"Bearer {key}"},
        timeout=150,
    )
    if r.status_code == 200 and r.content:
        return r.content
    if r.status_code in (401, 402, 403):
        raise RuntimeError(
            f"Pollinations account unavailable HTTP {r.status_code}: {r.text[:180]}"
        )
    if r.status_code == 429:
        retry = r.headers.get("Retry-After", "")
        raise RuntimeError(f"Pollinations rate limited HTTP 429 retry_after={retry}")
    raise RuntimeError(f"Pollinations HTTP {r.status_code}: {r.text[:180]}")


def install(namespace: dict) -> None:
    """Patch images.py's existing HF provider into a broker.

    generate_images() already knows how to order Cloudflare -> _hf_space -> local.
    Keeping that shape avoids a risky renderer rewrite. The broker makes the
    _hf_space slot itself two-tiered: Pollinations first, then real HF ZeroGPU.
    """
    if namespace.get("_IMAGE_PROVIDER_BROKER_INSTALLED"):
        return

    original_hf = namespace.get("_hf_space")
    if original_hf is None:
        raise RuntimeError("image provider broker installed before _hf_space exists")

    state = namespace.setdefault("_STATE", {})
    state.setdefault("broker_counts", {
        "pollinations": 0,
        "hf_space": 0,
        "pollinations_failed": 0,
        "hf_quota_checks": 0,
    })
    state.setdefault("pollinations_out", False)
    state.setdefault("hf_quota_unknown", False)

    config = namespace.get("CONFIG", {})
    polli_size = config.get("pollinations_image_size", [576, 1024])
    polli_width, polli_height = int(polli_size[0]), int(polli_size[1])
    polli_max = int(config.get("pollinations_image_max", 12))
    hf_min_seconds = int(config.get("hf_min_quota_seconds", 65))

    def broker_hf(prompt: str, seed: int, width=None, height=None, steps=None) -> bytes:
        # Tier 2: Pollinations. It is opt-in by the presence of a secret/key,
        # never assumed to be free or unlimited.
        if _enabled() and _key() and not state["pollinations_out"]:
            if state["broker_counts"]["pollinations"] < polli_max:
                try:
                    raw = _pollinations(
                        prompt,
                        seed,
                        width or polli_width,
                        height or polli_height,
                    )
                    state["broker_counts"]["pollinations"] += 1
                    namespace["log"](
                        f"Image broker: provider=pollinations model="
                        f"{os.environ.get('POLLINATIONS_IMAGE_MODEL', 'flux')} "
                        f"count={state['broker_counts']['pollinations']}/{polli_max}"
                    )
                    return raw
                except Exception as exc:
                    state["broker_counts"]["pollinations_failed"] += 1
                    namespace["log"](
                        f"Image broker: Pollinations failed: {type(exc).__name__}: {str(exc)[:180]}"
                    )
                    # Auth/balance failures should not be retried for every shot.
                    msg = str(exc).lower()
                    if "http 401" in msg or "http 402" in msg or "http 403" in msg:
                        state["pollinations_out"] = True

        # Tier 3: HF ZeroGPU. Ask the current quota endpoint before spending a
        # scheduler request. If the endpoint is unavailable, retain old behavior.
        state["broker_counts"]["hf_quota_checks"] += 1
        usable, remaining, reset = _quota_snapshot(namespace, hf_min_seconds)
        if usable is False:
            state["spaces_out"] = True
            raise RuntimeError(
                f"HF ZeroGPU quota too low ({remaining:.0f}s < {hf_min_seconds}s); "
                f"resets_at={reset}"
            )

        raw = original_hf(prompt, seed, width=width, height=height, steps=steps)
        state["broker_counts"]["hf_space"] += 1
        namespace["log"](
            f"Image broker: provider=hf_space "
            f"count={state['broker_counts']['hf_space']}"
        )
        return raw

    broker_hf.__name__ = "_hf_space"
    namespace["_hf_space"] = broker_hf

    # The outer generator uses this name for logging/counting. Its internal
    # max is enforced by the broker and the existing HF scheduler/quota guard.
    names = namespace.get("_NAMES", {})
    names["_hf_space"] = "image_broker"
    namespace["_NAMES"] = names

    namespace["_IMAGE_PROVIDER_BROKER_INSTALLED"] = True

    namespace["log"](
        "Image provider broker installed: Cloudflare -> "
        + ("Pollinations -> " if _key() else "")
        + "HF ZeroGPU -> local SD-Turbo; "
        + ("Pollinations key detected" if _key() else "Pollinations standby (no key)")
    )
