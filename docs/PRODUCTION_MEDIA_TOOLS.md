# Night Files Production Media Tools

Updated 2026-10-02.

## HyperFrames

Upstream: https://github.com/heygen-com/hyperframes

Night Files files:
- pipeline/hyperframes_adapter.py
- pipeline/media_production_test.py
- .github/workflows/daily_media_test.yml

Test pin: hyperframes@0.8.100.

The current HyperFrames CLI requires Node.js 22+ and FFmpeg. The adapter copies the generated Night Files MP4 into an isolated HyperFrames project, runs the HyperFrames linter, and renders a second MP4. The first implementation is deliberately a test renderer, not a replacement for the existing FFmpeg final pass.

The HyperFrames artifact is not published or buffered by the test lane.

## Adobe Premiere Pro MCP

Repository used for the local bridge: https://github.com/DutchErwin/PremiereMCP

Night Files files:
- .mcp.json
- pipeline/premiere_mcp_adapter.py
- pipeline/media_production_test.py

The MCP is a local Premiere Pro bridge. Premiere Pro itself is not available on GitHub-hosted Ubuntu runners, so the GitHub test generates a review-only handoff manifest. It does not claim that Premiere performed an edit.

Local proof:
1. Install the Premiere MCP package on the Windows/macOS machine running Premiere.
2. Install and start its CEP bridge.
3. Open a disposable Premiere project.
4. Run verify_premiere_connection before any mutation.
5. Import the handoff source video for review.

The repository MCP registration uses the local command premiere-pro-mcp.

## Test workflow boundary

.github/workflows/daily_media_test.yml is separate from .github/workflows/daily.yml.

The test lane:
1. runs the existing Night Files generator;
2. blocks buffer/history/checkpoint production writes;
3. does not call publish.py;
4. runs HyperFrames against the generated MP4;
5. writes the Premiere MCP handoff;
6. uploads test artifacts for review.

The production daily workflow is not changed by this implementation.

## Sources

- HyperFrames: https://github.com/heygen-com/hyperframes
- Premiere MCP: https://github.com/DutchErwin/PremiereMCP


## Buffer-first distribution

The media test lane is a producer, not a publisher.

The durable queue is `pipeline/buffer.py`, which stores complete MP4 + metadata pairs in the GitHub Release named `buffer`.

The production flow is now:

1. A buffer-fill run or media-production test generates a finished video.
2. The generated video and caption metadata are placed in the real FIFO buffer.
3. The producer workflow stops. It does not call TikTok or YouTube.
4. The scheduled `daily.yml` checks the buffer first.
5. If content is waiting, daily skips generation and publishes the oldest complete buffered pair.
6. If the buffer is empty, daily generates one video, which enters the buffer, then publishes the next buffered pair.
7. After at least one platform succeeds, `publish.py` removes the buffered pair. If publishing fails, the item remains queued for the next run.

This means repeated HyperFrames/Premiere media testing can build a supply of finished content without immediately publishing every test run.

### Media test artifacts

`.github/workflows/daily_media_test.yml` still uploads:

- `final.mp4`
- `hyperframes_test.mp4`
- `media_production_test.json`
- Premiere MCP `handoff.json`
- `summary.txt`

The media test now also leaves `final.mp4` and its caption metadata in the real production buffer for later scheduled distribution.

### Buffer fill artifacts

`.github/workflows/buffer_fill.yml` uploads:

- `final.mp4`
- `caption.txt`
- `caption.json`
- `story.json`
- visual/contact sheets when present
- `summary.txt`

It never invokes the platform publisher.

