"""Builds word-by-word animated captions as an .ass subtitle file."""
import re
from pathlib import Path

from common import CONFIG, ROOT

W, H = 1080, 1920


def _ass_color(hex_color: str, alpha: str = "00") -> str:
    h = hex_color.lstrip("#")
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H{alpha}{b}{g}{r}".upper()


def _ts(t: float) -> str:
    t = max(0.0, t)
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def _safe(word: str) -> str:
    return re.sub(r"[{}\\]", "", word).upper()


def font_setup() -> tuple[str, str]:
    """Returns (font name, fonts dir) — Anton if bundled, else a system fallback."""
    font_file = ROOT / CONFIG["caption_font_file"]
    if font_file.exists() and font_file.stat().st_size > 10_000:
        return CONFIG["caption_font"], str(font_file.parent)
    return CONFIG["caption_fallback_font"], ""


def _groups(words: list[dict], max_words: int) -> list[list[dict]]:
    groups, cur = [], []
    for w in words:
        cur.append(w)
        ends_phrase = bool(re.search(r"[.,!?;:…]$", w["word"]))
        if len(cur) >= max_words or ends_phrase:
            groups.append(cur)
            cur = []
    if cur:
        groups.append(cur)
    return groups


def build_ass(words: list[dict], hook_text: str, total: float, out: Path, end_start: float | None = None) -> Path:
    font, _ = font_setup()
    size = int(CONFIG.get("caption_size", 96))
    if font != CONFIG["caption_font"]:
        size = int(size * 0.8)  # fallback fonts are wider
    hi = _ass_color(CONFIG.get("caption_highlight", "#FFD84D"))
    white = _ass_color("#FFFFFF")
    black = _ass_color("#000000")

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,{font},{size},{white},{white},{black},{_ass_color('#000000', '80')},-1,0,0,0,100,100,1,0,1,7,3,5,80,80,0,1
Style: End,{font},{int(size * 1.05)},{white},{white},{black},{_ass_color('#000000', '60')},-1,0,0,0,100,100,1,0,1,6,2,8,60,60,1060,1
Style: Hook,{font},{int(size * 1.15)},{white},{white},{black},{_ass_color('#000000', '40')},-1,0,0,0,100,100,1,0,3,24,0,8,70,70,260,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    cap_y = int(H * 0.66)

    if hook_text:
        lines.append(
            f"Dialogue: 1,{_ts(0)},{_ts(min(4.0, total))},Hook,,0,0,0,,"
            f"{{\\fad(150,300)}}{_safe(hook_text)}"
        )

    if end_start is not None and end_start < total:
        name = CONFIG.get("channel_name", "").upper()
        lines.append(
            f"Dialogue: 2,{_ts(end_start + 0.2)},{_ts(total)},End,,0,0,0,,"
            f"{{\\fad(300,0)}}FOLLOW FOR MORE\\N{{\\c{hi}\\fscx80\\fscy80}}{_safe(name)}"
        )

    groups = _groups(words, int(CONFIG.get("caption_words_per_group", 3)))
    for gi, g in enumerate(groups):
        g_end = groups[gi + 1][0]["start"] if gi + 1 < len(groups) else min(total, g[-1]["end"] + 0.6)
        g_end = min(g_end, g[-1]["end"] + 0.6)
        for wi, w in enumerate(g):
            start = w["start"]
            end = g[wi + 1]["start"] if wi + 1 < len(g) else g_end
            if end <= start:
                end = start + 0.05
            parts = []
            for wj, other in enumerate(g):
                txt = _safe(other["word"])
                if wj == wi:
                    parts.append(f"{{\\c{hi}\\fscx112\\fscy112\\t(0,90,\\fscx100\\fscy100)}}{txt}{{\\c{white}}}")
                else:
                    parts.append(txt)
            text = " ".join(parts)
            lines.append(
                f"Dialogue: 0,{_ts(start)},{_ts(end)},Cap,,0,0,0,,{{\\pos({W // 2},{cap_y})}}{text}"
            )

    out.write_text(header + "\n".join(lines) + "\n", encoding="utf-8")
    return out
