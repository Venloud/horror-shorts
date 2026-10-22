# Night Files: Approved Character Asset Library

This is the **source of truth** for Venloud's reusable character identity and expression assets. 
Assets are approved **one at a time or in batches of up to 10**. Preserve the original uploaded PNG bytes; do not upsample, redraw, recolor, regenerate, or silently alter them.

## Locked visual identity
- Large perfectly round white head, black expressive oval eyes, bold brows, illustrated gentle shading.
- Slim **tailored black suit trousers**, jacket and lapels, white shirt, bright red tie, black dress shoes. 
- Preserve the **existing fine red aura exactly as approved**. DO NOT diminish or amplify it.
- No facial/body redesign between shots. Strong readability, genuinely transparent RGBA, consistent crop and screen position at render time.
- Characters in a blank editorial stage with purposeful still poses. Movement is not required; use cut timing, props, typography and graphics.
- Expression-specific punctuation, question marks, and icons should normally be separate reusable overlays (F03 currently includes a question mark in the approved source image; preserve the user's original as-is).

## Locked master references (original owner-uploaded PNGs)
| ID | Meaning | Canonical path |
|----|---------|----------------|
| M01 | Front full-body neutral | [masters/M01_front_neutral.png](masters/M01_front_neutral.png) |
| M02 | Three-quarter full-body neutral | [masters/M02_three_quarter_neutral.png](masters/M02_three_quarter_neutral.png) |
| M03 | Side full-body neutral, facing right | [masters/M03_side_neutral.png](masters/M03_side_neutral.png) |
| M04 | Back full-body neutral | [masters/M04_back_neutral.png](masters/M04_back_neutral.png) |
| M05 | Front bust neutral / close-up | [masters/M05_front_neutral_closeup.png](masters/M05_front_neutral_closeup.png) |

## Approved expressions
| ID | Name | Canonical file |
|----|------|----------------|
| F01 | Happy | [expressions/F01_happy.png](expressions/F01_happy.png) |
| F02 | Serious | [expressions/F02_serious.png](expressions/F02_serious.png) |
| F03 | Confused | [expressions/F03_confused.png](expressions/F03_confused.png) |
| F04 | Worried | [expressions/F04_worried.png](expressions/F04_worried.png) |
| F05 | Excited | [expressions/F05_excited.png](expressions/F05_excited.png) |
| F07 | Thinking | [incoming/2026-10-21/U09_thinking_skeptical.png](incoming/2026-10-21/U09_thinking_skeptical.png) |
| F08 | Suspicious | [incoming/2026-10-21/U08_suspicious_crossed_arms.png](incoming/2026-10-21/U08_suspicious_crossed_arms.png) |
| F09 | Angry | [expressions/F09_angry.png](expressions/F09_angry.png) |
| F10 | Smirk | [expressions/F10_smirk.png](expressions/F10_smirk.png) |

## Still needed
F06 Scared, F11 Talking, F12 Curious, F13 Sad. Additional emotional expressions can be added later under stable new IDs.

Each incoming image will have the same character, outfit, shading, approved red aura, clean transparent background, and a clear emotion. Names/IDs **never** get reused for different expressions.

## Replacement policy
- The previous `assets/character/host/closeups/` flat-vector pack is **retired**; these owner-approved assets replace it.
- The 102 older cutout action sprites under the host root are **legacy placeholders** until approved replacement action poses exist. Remove each as the new matching P-series arrives; never rely on mismatched legacy close-ups.
- Register new art in `manifest.json`, including SHA256, image dimensions, approval status, and canonical path.
- Prefer original PNG sources; normalized crop/padding/caption placement are render-time transforms, never destructive changes to the originals.
- Remotion/FFmpeg motion graphics, overlays, lower-thirds and filler are *separate reusable libraries*, not background pictures baked into character PNGs.
- No story-specific backgrounds or images should be required just to show an action.

## Owner-confirmed intake labels, October 21

The newest nine uploaded candidate images are [preserved here](incoming/2026-10-21/). Venloud specifically confirmed this order:

- U06: **Confused**, the one with a yellow question mark (F03 variant).
- U07: **Skeptical**, distinct from Suspicious.
- U08: **Suspicious**, canonical **F08**.
- U09: **Thinking**, canonical **F07**.

**F04 Worried and F05 Excited are now stored** as original user-supplied PNGs, with verified SHA-256 hashes. F05 is byte-identical to previously saved U01. F09 Angry uses U04 and F10 Smirk uses U02. The files remain unchanged; the registered F-series IDs determine selection.
