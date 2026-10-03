# Night Files image provider broker

## Implementation: 2026-10-03

### Why this exists

The buffer-fill image failure was caused by a provider chain that could exhaust Cloudflare, exhaust Hugging Face ZeroGPU, and then spend the remaining generation budget on CPU SD-Turbo without a centralized quota/health decision. Increasing the SD-Turbo cap alone is not a durable fix.

The image system now has a quota-aware broker while preserving the existing renderer and media pipeline.

### Runtime tier order

1. Cloudflare Workers AI / FLUX.1 schnell
- Existing first provider remains unchanged.
- Cloudflare's own cf-ai-neurons response header is still recorded when available.
- Existing daily Cloudflare ledger and daily-limit detection remain authoritative.
- Current Cloudflare pricing documentation lists 10,000 free Workers AI Neurons per day, with limits resetting at 00:00 UTC. FLUX.1 schnell is priced by 512x512 tiles and inference steps. The repository therefore must not treat Cloudflare as unlimited.

2. Pollinations / FLUX
- New optional broker tier.
- Activated only when POLLINATIONS_API_KEY or POLLINATIONS_KEY is present.
- Uses gen.pollinations.ai/image/{prompt} with Bearer authentication.
- Default model is flux; size is 576x1024.
- Hard per-run cap is pollinations_image_max (12 by default).
- HTTP 401/402/403 disables this provider for the remainder of the run so an invalid key or exhausted account does not cause repeated failures.
- HTTP 429/5xx/network failures fall through to Hugging Face.
- Pollinations is explicitly not documented as unlimited free capacity. Current Pollinations generation requires authentication and uses Pollen/account budget.

3. Hugging Face ZeroGPU Spaces
- Existing FLUX Spaces remain the next real generation tier.
- Before each broker attempt, the code calls HfApi.get_zero_gpu_quota() when HF_TOKEN is available.
- If remaining GPU time is below hf_min_quota_seconds (65 seconds), the provider is skipped before another generation request is sent.
- If the installed huggingface_hub cannot expose the quota endpoint, the broker logs the failure and preserves the old scheduler-side behavior rather than falsely declaring HF unavailable.
- Existing Space endpoint discovery, multiple Space fallback, and scheduler quota error handling remain intact.

4. Local SD-Turbo CPU
- Remains the emergency fallback.
- The existing 12-image and 18-minute caps remain in force.
- It is not promoted to the primary production generator because CPU diffusion is the slowest and least predictable tier on the GitHub runner.

5. Same-scene virtual/cached shots
- Existing images.py behavior remains the visual safety net after provider generation.
- A missing shot may be generated as a crop from a fitting image in the same scene.
- Cross-scene borrowing remains prohibited.
- .origin metadata lets visual QA count virtual crops as the same underlying picture.

6. Real media / asset library
- Real media and reusable library assets are still filled before AI generation in main.py.
- The broker does not replace the rights/provenance-aware media layer.
- Downloading media does not itself establish copyright clearance; source/license metadata remains required.

### Broker design

pipeline/image_provider_broker.py does not replace images.generate_images() or the renderer. It patches the existing _hf_space provider slot after images.py has defined all provider functions.

The existing chain remains structurally stable:

Cloudflare -> broker(HF slot) -> local SD

Inside the broker slot:

Pollinations -> HF ZeroGPU

This avoids a large renderer rewrite and keeps the existing QA, rejection, redraw, checkpoint, and same-scene virtual-shot logic active.

### Quota behavior

- Cloudflare daily-limit detection still stops Cloudflare when Cloudflare explicitly reports its daily free allocation is exhausted.
- Pollinations is attempted only when explicitly configured with a key.
- Pollinations authentication/balance failures disable Pollinations for the run instead of retrying every scene.
- Hugging Face quota is checked before an expensive Space call when the quota API is available.
- Unknown Hugging Face quota does not automatically fail a build. The existing Space error parser remains the final scheduler-side guard.
- Local SD only runs after the upstream providers are unavailable or fail.
- Existing local time and image-count limits remain intact.

### No new mandatory secret

No generation workflow requires a new secret to run.

POLLINATIONS_API_KEY is optional. If it is absent, the broker logs Pollinations standby (no key) and continues directly to Hugging Face ZeroGPU.

If the owner later adds the optional secret, both buffer_fill.yml and daily.yml pass it to the generation process.

### Files changed

- pipeline/image_provider_broker.py: New quota-aware broker, Pollinations adapter, HF ZeroGPU quota preflight, per-run provider health/counters, and explicit Pollinations account failure handling.
- pipeline/images.py: Installs the broker after the existing provider functions are defined. Existing image QA, redraw, virtual-shot and local fallback logic remains intact.
- config.json: Adds Pollinations model/size/cap and HF quota threshold, plus the complete image-provider tier order.
- .github/workflows/buffer_fill.yml: Passes optional POLLINATIONS_API_KEY into generation.
- .github/workflows/daily.yml: Passes optional POLLINATIONS_API_KEY into production generation.

### Expected log lines

With no Pollinations key:
Image provider broker installed: Cloudflare -> HF ZeroGPU -> local SD-Turbo; Pollinations standby (no key)

With a Pollinations key:
Image provider broker installed: Cloudflare -> Pollinations -> HF ZeroGPU -> local SD-Turbo; Pollinations key detected

When HF quota is available:
HF ZeroGPU quota preflight: <seconds>s remaining; minimum 65s; resets_at=<timestamp>

When Pollinations succeeds:
Image broker: provider=pollinations model=flux count=<n>/12

When HF succeeds:
Image broker: provider=hf_space count=<n>

### Verification boundary

This implementation was reviewed against the current provider documentation before coding. A live GitHub Actions generation run was not executed by this edit, so provider availability, current account balances, actual ZeroGPU quota, and the first end-to-end MP4 remain runtime checks.

The first validation run should be the buffer fill workflow, not YouTube backfill and not the publishing workflow.

### External documentation checked

- Cloudflare Workers AI pricing and FLUX.1 schnell documentation.
- Hugging Face ZeroGPU usage/quota documentation and get_zero_gpu_quota() API.
- Pollinations current unified image API and authentication documentation.

These external limits can change; the broker therefore treats provider quota/health as runtime state rather than hard-coding a claim that a provider is permanently free or unlimited.

## Final implementation commit ledger

- `a4f0858a0822220297ad5a67dfbd78e40c68d122` - Added the initial quota-aware image provider broker.
- `204770b6f4236ca79ce149e78a0c89462d7093fd` - Installed the broker into the existing image generator provider slot.
- `455fdbdf60cbffc0839e0b0596699c75a7cbd5f8` - Fixed broker logging to use the images module namespace correctly.
- `810bd72d4636087a19f3a39b7e4702daf745de03` - Preserved existing HF provider accounting so the generator's outer cap remains valid.
- `365cbbd400b836b6ca79baddeb6ffc97db32be70` - Added broker configuration and tier order.
- `55a3139f4cdab86ed77f1f47e31968ac77c5aa24` - Raised the broker-slot ceiling to 12 total provider attempts so the new tier can actually operate before fallback.
- `fb5dd85394dd0fb1e6045921a2dafb4db4547f0d` - Passed optional Pollinations credentials into buffer-fill generation.
- `eff7afdeaf154fc19a248853e78ee1a641897123` - Passed optional Pollinations credentials into daily production generation.
- `d8592f957280430cbee499995eaba3883505b326` - Added this detailed image-provider broker reference.
- `27086d3f788094dc598cf6422032d39bb7471318` - Added the cumulative implementation ledger to NIGHT_FILES_UPDATE.md.
