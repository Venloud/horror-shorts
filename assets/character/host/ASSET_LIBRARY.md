# Night Files: Approved Character Asset Library

> **Reconciled 2026-10-22:** Canonical existing expression files now follow [the original 118-item catalog](MASTER_ASSET_CATALOG.md). Original PNG contents are unchanged. Only listed approved files are verified present; sent-but-unimported pictures remain pending.

This is the **source of truth** for Venloud's reusable character identity and expression assets. 
Assets are approved **one at a time or in batches of up to 10**. Preserve the original uploaded PNG bytes; do not upsample, redraw, recolor, regenerate, or silently alter them.

## Locked visual identity
- Large perfectly round white head, black expressive oval eyes, bold brows, illustrated gentle shading.
- Slim **tailored black suit trousers**, jacket and lapels, white shirt, bright red tie, black dress shoes. 
- Preserve the **existing fine red aura exactly as approved**. DO NOT diminish or amplify it.
- No facial/body redesign between shots. Strong readability, genuinely transparent RGBA, consistent crop and screen position at render time.
- Characters in a blank editorial stage with purposeful still poses. Movement is not required; use cut timing, props, typography and graphics.
- Expression-specific punctuation, question marks, and icons should normally be separate reusable overlays (F10 confused alternate includes a question mark in the approved source image; preserve the user's original as-is).

## Locked master references (original owner-uploaded PNGs)
| ID | Meaning | Canonical path |
|----|---------|----------------|
| M01 | Front full-body neutral | [masters/M01_front_neutral.png](masters/M01_front_neutral.png) |
| M02 | Three-quarter full-body neutral | [masters/M02_three_quarter_neutral.png](masters/M02_three_quarter_neutral.png) |
| M03 | Side full-body neutral, facing right | [masters/M03_side_neutral.png](masters/M03_side_neutral.png) |
| M04 | Back full-body neutral | [masters/M04_back_neutral.png](masters/M04_back_neutral.png) |
| M05 | Front bust neutral / close-up | [masters/M05_front_neutral_closeup.png](masters/M05_front_neutral_closeup.png) |

## Approved expressions (original F01–F22 order)
| ID | Visually identified expression | Correct unchanged PNG |
|---|---|---|
| F01 | Neutral | [expressions/F01_neutral.png](expressions/F01_neutral.png) |
| F05 | Excited | [expressions/F05_excited.png](expressions/F05_excited.png) |
| F06 | Smirk | [expressions/F06_smirk.png](expressions/F06_smirk.png) |
| F07 | Confident | [expressions/F07_confident.png](expressions/F07_confident.png) |
| F08 | Serious | [expressions/F08_serious.png](expressions/F08_serious.png) |
| F10 | Confused | [expressions/F10_confused.png](expressions/F10_confused.png) |
| F11 | Skeptical | [expressions/F11_skeptical.png](expressions/F11_skeptical.png) |
| F12 | Suspicious | [expressions/F12_suspicious.png](expressions/F12_suspicious.png) |
| F13 | Thinking | [expressions/F13_thinking.png](expressions/F13_thinking.png) |
| F14 | Worried | [expressions/F14_worried.png](expressions/F14_worried.png) |
| F18 | Angry | [expressions/F18_angry.png](expressions/F18_angry.png) |

## Pending or missing canonical original
F02 talking, F03 smiling, F04 laughing, F09 curious, F15 scared, F16 shocked, F17 sad, F19 determined, F20 frustrated, F21 relieved, F22 tired.

F02 Talking image submitted in conversation has closed eyes, open-mouthed laughter and pointing, pending owner confirmation before import. F03 Smiling submitted, exact importable file not yet verified. F15 Scared submitted previously, not yet committed in this canonical folder.

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
- U08: **Suspicious**, canonical **F12**.
- U09: **Thinking**, canonical **F13**.

**F14 Worried (formerly misnumbered F04) and F05 Excited are now stored** as original user-supplied PNGs, with verified SHA-256 hashes. F05 is byte-identical to previously saved U01. F18 Angry uses U04 and F06 Smirk uses U02. The files remain unchanged; the registered F-series IDs determine selection.

## F04 Laughing receipt, October 22

The owner supplied **F04 Laughing**, a 1374×1145 transparent RGBA PNG with the approved host, pointing gesture and laughter accents, SHA-256 `758b94e77e8552c17d1d71e701d80b1b6f43de9a279632f7fc8fbd9d57cec44c`. **The original image bytes are not yet in GitHub**, although the upload is preserved in the conversation. Correct destination: `expressions/F04_laughing.png`. Never use F14 Worried as F04 Laughing.
