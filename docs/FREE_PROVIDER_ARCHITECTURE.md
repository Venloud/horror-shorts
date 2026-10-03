# Free-provider and automation architecture

## What was implemented

Night Files now combines useful architectural patterns found in MoneyPrinterTurbo, Video Factory, Content Machine, the free-model directory supplied by the owner, and NVIDIA's current API catalog without copying those projects wholesale.

### MoneyPrinterTurbo pattern
MoneyPrinterTurbo demonstrates provider/gateway flexibility, batch generation, CLI/headless operation, and an end-to-end topic-to-video path. Night Files now has a modality provider registry and broker so adding a provider does not require rewriting the renderer. The production buffer remains the queue boundary.

### Video Factory pattern
Video Factory separates planning, script, image/audio sources, processing, rendering, assembly, thumbnails, and final review while tracking checkpoints, retries, validation failures, traces and cost. Night Files already had checkpoint/resume behavior; this update adds an inspectable run manifest with stage status and artifact hashes.

### Content Machine pattern
Content Machine uses repo-local skills/flows, deterministic runtime surfaces, inspectable artifacts, provenance, publish-prep review, and run-scoped outputs. Night Files now records provider snapshots, stage states, and key output artifacts inside each run directory without installing a second complete content-generation framework into production.

### Free model inventory pattern
The awesome-freellm-apis directory is treated as a research/catalog source, not as a runtime dependency. Its current directory lists NVIDIA NIM, ModelScope, Cloudflare Workers AI, Google Gemini and other providers with image/video/text modalities and rate-limit information. Those limits can change, so Night Files still uses credential presence plus runtime health/quota rather than assuming a provider is permanently free.

## Provider registry
pipeline/provider_registry.py is the single declarative inventory used by pipeline/provider_doctor.py and the run manifest.

Current optional modalities:
- Cloudflare: image/text/video
- NVIDIA: image/text/video/vision
- ModelScope: image/text/video/vision
- Pollinations: image
- Hugging Face: image/video
- Gemini: text/vision
- Groq: text

## New image tiers
The image broker now runs:

Cloudflare FLUX -> NVIDIA FLUX.2-klein-4b -> ModelScope Qwen-Image -> Pollinations FLUX -> Hugging Face ZeroGPU -> local SD-Turbo -> same-scene virtual/cached shots

NVIDIA and ModelScope are optional and credential-gated. They do not replace existing providers when credentials are absent.

NVIDIA's current FLUX.2-klein-4b API accepts text prompts and returns a generated image; the documented endpoint is 1024x1024 with 1-4 steps. NVIDIA's current API catalog also lists Cosmos3-Nano as a downloadable/free endpoint.

ModelScope's current Qwen-Image API uses an asynchronous image-generation task endpoint and token authentication.

## New video tier
The existing AI-motion path now tries NVIDIA Cosmos3-Nano image-to-video when NVIDIA_API_KEY exists. If it is unavailable or fails, PersonaLive, Hugging Face and 3D fallbacks remain intact.

Cosmos3-Nano currently supports text-to-video and image-to-video on NVIDIA's hosted API. The public model card documents the /v1/cosmos/nvidia/cosmos3-nano endpoint and 480/720 resolution modes. Hosted output carries NVIDIA's SynthID watermark and the trial endpoint can be rate limited, so this remains optional and non-blocking.

## New text tiers
The story model chain now supports optional:
- nvidia:z-ai/glm-5.3-flash
- modelscope:Qwen/Qwen3.5-27B

They are appended after the existing Gemini/Groq providers, so they cannot disrupt the current writer unless their credentials are supplied. They inherit the existing retry/overload/daily-limit machinery.

## Run artifacts
Every production run now gets output/<stamp>/run_manifest.json containing provider snapshot at run start, stage status/timestamps, final-video artifact metadata and SHA-256 when small enough to hash, story/caption artifacts, and final success/failure state.

This is deliberately lightweight. It does not replace the existing checkpoint files or buffer.

## Provider doctor
Run from pipeline: python provider_doctor.py
It reports which optional provider credentials are present. It never makes generation calls and never writes secrets.

## Manual setup required
The code is already wired. The owner only needs to do provider-account steps if those optional tiers should be active:
1. NVIDIA: create an NVIDIA API key. Current free/preview access can require account/phone verification. Store it in GitHub Actions as NVIDIA_API_KEY.
2. ModelScope: create a ModelScope token. Store it as MODELSCOPE_TOKEN.
3. Pollinations: create/use a Pollinations API key if desired. Store it as POLLINATIONS_API_KEY. Pollinations is not treated as unlimited free capacity.
4. Hugging Face: keep the existing HF_TOKEN.
5. Cloudflare: keep the existing CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN.
6. Gemini/Groq: keep the existing secrets.

No one has to set up all optional providers. Missing credentials simply disable those tiers.

## Safety boundary
No provider in this update is allowed to bypass Night Files' existing image QA, render validation, buffer queue, or platform publishing logic. NVIDIA Cosmos output is also subject to its hosted safety screening and SynthID watermarking according to NVIDIA's current model documentation.

## External references
- MoneyPrinterTurbo: https://github.com/harry0703/MoneyPrinterTurbo
- Video Factory: https://github.com/NesDevr/video-factory
- Content Machine: https://github.com/45ck/content-machine
- Free LLM/API directory: https://github.com/open-free-llm-api/awesome-freellm-apis
- NVIDIA FLUX.2-klein API: https://docs.api.nvidia.com/nim/reference/black-forest-labs-flux_2-klein-4b-infer
- NVIDIA Cosmos3-Nano: https://build.nvidia.com/nvidia/cosmos3-nano/modelcard
- ModelScope Qwen-Image: https://modelscope.cn/models/Qwen/Qwen-Image-2.1/summary
