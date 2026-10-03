# Night Files DESIGN.md

> Visual source of truth for Night Files UI surfaces.
> Inspired by the DESIGN.md convention used by VoltAgent/awesome-design-md.
> Upstream reference: https://github.com/voltagent/awesome-design-md

## Visual Theme & Atmosphere
Night Files is a dark editorial operations interface for an automated horror-video pipeline.
Use a restrained production-control-room aesthetic. Horror belongs in content previews, not interface decoration.
- dark surfaces with clear hierarchy
- near-black canvas and charcoal panels
- warm off-white primary text
- restrained electric-blue interaction accent
- muted semantic colors for success, warning, and error
- compact data-dense layouts for runs, buffer items, and diagnostics
- large media previews for video review
- no occult, illuminati, all-seeing-eye, pentagram, or similar decorative imagery
- no gratuitous blood/gore motifs in interface chrome

## Color Palette & Roles
| Token | Value | Role |
|---|---|---|
| canvas | #0B0B0D | application background |
| surface | #121216 | primary panels |
| surface-elevated | #19191F | cards, dialogs, active panels |
| surface-soft | #222229 | inputs and secondary controls |
| border | #2D2D35 | default hairline |
| border-strong | #3B3B46 | emphasized separators |
| text | #F3F1EC | primary text |
| text-strong | #FFFFFF | headings and critical values |
| text-muted | #A6A3AA | secondary text |
| text-disabled | #68666E | disabled state |
| accent | #3D7EFF | links, active controls, progress |
| accent-soft | #18315F | selected/hover background |
| success | #35C47C | completed/healthy |
| warning | #E7B84B | attention/non-blocking issue |
| error | #E45B65 | failed/destructive |
| info | #66B5FF | informational state |

Accent blue is for interaction and machine state, not decorative gradients.

## Typography
Use a modern sans-serif stack. Prefer Inter when available.

| Token | Size | Weight | Line Height | Use |
|---|---:|---:|---:|---|
| display-xl | 40px | 650 | 1.05 | page title |
| display-lg | 32px | 650 | 1.1 | section title |
| title-md | 20px | 600 | 1.25 | card title |
| title-sm | 16px | 600 | 1.3 | row/group heading |
| body-md | 15px | 400 | 1.5 | normal UI text |
| body-strong | 15px | 550 | 1.5 | emphasized text |
| caption | 13px | 400 | 1.4 | metadata |
| label | 12px | 600 | 1.3 | status labels / badges |
| mono | 12px | 400 | 1.45 | commit SHAs, IDs, logs, timestamps |

Use tabular numerals for counters, durations, buffer depth, and analytics values.

## Layout Principles
- Base spacing unit: 4px.
- Common spacing: 4, 8, 12, 16, 20, 24, 32, 40.
- Main desktop content max width: 1440px.
- Prefer a 12-column grid for dashboards.
- Sidebars may be 240-280px wide.
- Keep dashboard cards aligned to a shared baseline.
- Media review pages may use a two-column layout: video/preview left, diagnostics/metadata right.
- Mobile collapses side navigation and stacks diagnostic panels.

## Radius & Depth
| Token | Value | Use |
|---|---:|---|
| radius-xs | 4px | compact controls |
| radius-sm | 6px | inputs, small cards |
| radius-md | 10px | normal cards |
| radius-lg | 14px | large media panels |
| radius-pill | 9999px | badges / compact statuses |

Depth should come primarily from surface contrast and 1px borders. Use very soft shadows only for dialogs/popovers.
Avoid glowing neon effects except for very small state indicators.

## Core Components
### Top Bar
Dark surface with Night Files name, current pipeline status, compact actions, and optional settings/account area. Height 56-64px.

### Sidebar
Compact navigation: Overview, Buffer, Runs, Stories, Media, Publishing, Analytics, Integrations, Settings. Active item uses accent-soft background and accent text/icon.

### Status Badge
Use pill-shaped badges for BUFFERED, PUBLISHED, FAILED, RUNNING, QUEUED, DRAFT, TRUE STORY, and FICTION. State colors are semantic and consistent.

### Metric Card
Surface-elevated panel with a small label, large value, optional delta/status, and optional supporting line.

### Buffer Item
Show title, story ID, queued timestamp, duration, platform readiness, thumbnail, status, and external-media source/license metadata when applicable.

### Video Review Panel
Large 9:16 preview with playback, duration/timestamp, visual-source summary, QA status, and media provenance.

### Log / Diagnostic Panel
Use monospace type. Preserve timestamps and structured IDs. Errors should be obvious without making the entire interface red.

### Data Table
Dense rows, clear headers, sticky headers when useful, and monospace for IDs and technical values.

## Media & Content Rules
- Video thumbnails may be cinematic and dark.
- Interface decorations remain abstract and restrained.
- Never use real victim imagery as decorative UI.
- Never add occult symbols to make a horror dashboard scarier.
- For externally sourced footage, show source URL/domain and license/rights metadata.
- AI-generated visuals should be labeled as such where provenance is exposed.

## Buffer-First UX
Represent the real architecture:

Generate -> Buffer -> Scheduled Publisher -> TikTok / YouTube

The Buffer page is the central staging surface. Show waiting count, oldest item, next publishing eligibility, successful/failed publish state, and whether an item remains queued after failure.
Never present a test generation as automatically published.

## Integrations UX
External tools should be displayed with explicit status:
- Remotion
- PersonaLive
- MuMuAINovel
- AutoClip
- Ruflo
- HyperFrames
- Premiere Pro MCP
- yt-dlp
- Claude Watch

Each integration card should show enabled/disabled, local-only vs CI-capable, pinned version/commit, last verification result, and whether it can mutate production output.

## Do
- Keep information hierarchy obvious.
- Prefer spacing and surface contrast over decoration.
- Use semantic statuses consistently.
- Keep technical identifiers copyable.
- Show media provenance.
- Make buffer state impossible to misunderstand.
- Optimize review screens for fast human verification.

## Don't
- Don't copy a third-party brand's complete visual identity.
- Don't use large gradients as the main UI treatment.
- Don't use horror imagery as navigation decoration.
- Don't imply a local Premiere MCP operation occurred in GitHub Actions.
- Don't imply an external clip is copyright-free merely because yt-dlp downloaded it.
- Don't expose API keys or secrets in UI.
- Don't turn QA warnings into fake success states.

## Responsive Behavior
### < 640px
Sidebar becomes a menu; dashboard cards stack; two-column review becomes one column; tables scroll or transform into cards.
### 640-1024px
Condensed sidebar and two-column grids where content permits.
### > 1024px
Full navigation, multi-column dashboard, media and diagnostics side-by-side.

## Agent Prompt Guide
Before editing Night Files UI, read DESIGN.md. Preserve its tokens and component rules. Use the buffer-first architecture, expose media provenance, and do not invent production capabilities the pipeline does not actually have.
