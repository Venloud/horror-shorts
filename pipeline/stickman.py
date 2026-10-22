"""Code-drawn stick-figure rig for the explainer style (Oct 21, replaces the FLUX pose set): the host "you" in a
suit jacket, white shirt and tie, stick legs, no pants; any view (front / three_quarter / side / back), any action,
crisp at every size, 0 neurons, no workflow. Other cast members (real people, witnesses) use the same rig with their
own props (hat, beard, dress, coat colour) so they read as different people. Adults only.

draw(look, action, expression, view, facing, t, height) -> (RGBA image, (foot_x, foot_y) inside it)
Hands and feet are placed by 2-bone IK from per-action targets in body units (u = height / 10, feet at y = 0,
y up is negative): legs 4u, torso 3u, head radius 1.4u.
"""
import math
from functools import lru_cache

from PIL import Image, ImageDraw

SS = 2  # supersampling
INK = (20, 20, 24, 255)
WHITE = (250, 250, 248, 255)
HOST = {"name": "you", "jacket": (29, 30, 35), "tie": (227, 25, 48), "shirt": (251, 250, 248), "hat": "",
        "beard": False, "dress": False, "hair": ""}

ACTIONS = ("standing", "walking", "running", "pointing", "reacting", "turning", "looking", "observing", "reaching",
           "presenting", "waiting", "boarding", "seated", "thinking", "holding", "scared", "sneaking", "leaving")
EXPRESSIONS = ("neutral", "worried", "shocked", "scared", "angry", "determined", "curious", "sad", "sneaky", "happy", "confident", "serious", "thinking", "talking", "suspicious", "confused", "smirk")
VIEWS = ("front", "three_quarter", "side", "back")
MOVING = {"walking", "running", "boarding", "sneaking", "leaving"}  # these move across the frame
SIDE_ONLY = {"walking", "running", "boarding", "sneaking", "seated"}  # drawn in profile whatever was asked


def look_for(name: str, text: str = "") -> dict:
    """Props for a cast member from a short description ("late 40s, full dark beard, bowler hat")."""
    t = f"{name} {text}".lower()
    look = dict(HOST, name=name, tie=(70, 70, 76))
    palette = {"brown": (92, 64, 44), "gray": (96, 98, 104), "grey": (96, 98, 104), "black": (30, 30, 34),
               "green": (40, 74, 52), "red": (120, 36, 36), "blue": (40, 62, 110), "tan": (150, 120, 80)}
    look["jacket"] = next((v for k, v in palette.items() if k in t), (88, 74, 60))
    if any(w in t for w in ("woman", "wife", "daughter", "mother", "sister", "lady", "girl", "she ", "her ",
                            "dress", "skirt", "gown")):
        look.update(dress=True, hair="bun", tie=None)
    if "beard" in t:
        look["beard"] = True
    if "top hat" in t:
        look["hat"] = "top"
    elif "bowler" in t or "derby" in t:
        look["hat"] = "bowler"
    elif "cap" in t:
        look["hat"] = "cap"
    elif "hat" in t:
        look["hat"] = "bowler"
    return look


# ---------------------------------------------------------------- geometry

def _ik(root, target, l1, l2, bend):
    """Elbow / knee point for a 2-bone limb from root to target; bend = +1 / -1 picks the side."""
    dx, dy = target[0] - root[0], target[1] - root[1]
    d = max(1e-6, min(math.hypot(dx, dy), l1 + l2 - 1e-4))
    a = math.atan2(dy, dx)
    cos_b = max(-1.0, min(1.0, (l1 * l1 + d * d - l2 * l2) / (2 * l1 * d)))
    b = math.acos(cos_b) * bend
    return (root[0] + l1 * math.cos(a + b), root[1] + l1 * math.sin(a + b)), \
        (root[0] + d * math.cos(a), root[1] + d * math.sin(a))


def _pose(action: str, view: str, t: float) -> dict:
    """Targets in body units (feet centre at 0,0; facing +x in profile). hands = [near/right, far/left]."""
    side = view in ("side",)
    p = {"hands": [(2.15, -4.25), (-2.15, -4.25)], "feet": [(0.45, 0.0), (-0.45, 0.0)], "lean": 0.0, "bob": 0.0,
         "drop": 0.0, "dx": 0.0, "head_back": False, "fists": False}
    if side:
        p["hands"], p["feet"] = [(1.35, -4.5), (-1.15, -4.35)], [(0.15, 0.0), (-0.15, 0.0)]
    breath = 0.05 * math.sin(t * 2.4)
    p["bob"] = breath
    if action in ("walking", "boarding", "leaving", "sneaking", "running"):
        run = action == "running"
        f = 2.6 if run else 1.7
        amp = 1.5 if run else 0.95
        ph = 2 * math.pi * f * t
        s = math.sin(ph)
        lift = lambda c: -0.45 * max(0.0, c) * (1.6 if run else 1.0)  # noqa: E731
        p["feet"] = [(amp * s, lift(math.cos(ph))), (-amp * s, lift(-math.cos(ph)))]
        if run:
            p["hands"] = [(-0.9 * s + 0.4, -5.2), (0.9 * s + 0.4, -5.2)]
            p["lean"] = 10.0
        elif action == "sneaking":
            p["hands"] = [(0.7, -6.0), (0.1, -6.3)]
            p["lean"] = 9.0
            p["feet"] = [(0.5 * s, lift(math.cos(ph)) * 0.6), (-0.5 * s, lift(-math.cos(ph)) * 0.6)]
        else:
            p["hands"] = [(-0.75 * s, -4.4), (0.75 * s, -4.4)]
        p["bob"] = -0.12 * abs(math.sin(2 * ph))
        if action == "boarding":
            p["drop"] = -0.7 * min(1.0, t / 1.6)  # stepping up
        return p
    if action == "seated":
        p["drop"] = 1.7
        p["feet"] = [(1.9, 0.0), (1.6, 0.0)] if side else [(0.7, 0.0), (-0.7, 0.0)]
        p["hands"] = [(1.4, -2.9), (1.1, -3.0)] if side else [(1.0, -3.0), (-1.0, -3.0)]
        return p
    if action == "pointing":
        p["hands"][0] = (3.6, -7.2) if not side else (3.5, -7.2)
    elif action == "reaching":
        p["hands"][0] = (2.6, -5.0) if side else (2.4, -5.4)
    elif action == "presenting":
        p["hands"][0] = (2.9, -5.7)
        if not side:
            p["hands"][1] = (-1.55, -4.6)
    elif action in ("looking", "observing"):
        p["hands"][0] = (0.55, -8.95) if not side else (0.9, -8.8)
        p["lean"] = 5.0
    elif action == "waiting":
        p["hands"] = [(-0.55, -5.55), (0.6, -5.35)] if not side else [(0.7, -5.5), (0.5, -5.6)]
    elif action == "thinking":
        p["hands"] = [(0.25, -7.45), (-0.35, -5.3)] if not side else [(0.9, -7.6), (0.4, -5.4)]
    elif action == "holding":
        p["hands"] = [(2.20, -5.4), (-2.20, -5.4)] if not side else [(2.1, -5.4), (1.1, -5.0)]
    elif action == "reacting":
        k = min(1.0, t / 0.18)
        p["hands"] = [(2.2, -8.1), (-2.2, -8.1)] if not side else \
            [(1.9, -7.9), (1.0, -7.8)]
        p["lean"] = -4.0 * k
    elif action == "scared":
        jit = 0.06 * math.sin(t * 40)
        p["hands"] = [(2.2 + jit, -9.0), (-2.2 + jit, -9.0)] if not side else [(1.6, -8.8), (0.9, -9.0)]
        p["lean"] = -7.0
    elif action == "turning":
        p["head_back"] = t < 0.35
    return p


# ---------------------------------------------------------------- face

def _face(d, cx, cy, r, expr, view, blink):
    """Eyes, brows and mouth. view front / three_quarter / side; head centre (cx, cy), radius r."""
    k = {"front": (0.0, 1.0), "three_quarter": (0.32, 0.86), "side": (0.55, 0.0)}[view]
    off = k[0] * r
    big = expr in ("shocked", "scared")
    ex, ey = 0.42 * r, -0.05 * r
    ew, eh = 0.2 * r * (1.25 if big else 1.0), 0.27 * r * (1.25 if big else 1.0)
    w = max(2, int(0.07 * r))
    eyes = [cx + off + ex * (1 if view != "side" else 0.5), cx + off - ex * k[1]] if view != "side" else \
        [cx + 0.55 * r]
    for i, x in enumerate(eyes):
        s = 0.82 if (view == "three_quarter" and i == 1) else 1.0
        if blink:
            d.line((x - ew * s, cy + ey, x + ew * s, cy + ey), fill=INK, width=w)
            continue
        d.ellipse((x - ew * s, cy + ey - eh * s, x + ew * s, cy + ey + eh * s), fill=WHITE, outline=INK, width=w)
        pr = (0.11 if not big else 0.08) * r * s
        px = x + (0.06 * r if view != "front" else 0) + (0.04 * r if expr == "sneaky" else 0)
        py = cy + ey + 0.04 * r
        d.ellipse((px - pr, py - pr, px + pr, py + pr), fill=INK)
        d.ellipse((px - pr * 0.35 + pr * 0.3, py - pr * 0.75, px + pr * 0.25 + pr * 0.3, py - pr * 0.15),
                  fill=WHITE)
        # brows: inner end up (worried / sad / scared), down (angry / determined)
        inner = {"worried": -0.12, "sad": -0.12, "scared": -0.15, "angry": 0.12, "determined": 0.07,
                 "shocked": -0.05, "curious": -0.02, "sneaky": 0.05}.get(expr, 0.0) * r
        lift = (0.16 if big else 0.0) * r
        by = cy + ey - eh * s - 0.12 * r - lift
        side_sign = 1 if x > cx + off else -1
        if view == "side":
            side_sign = -1
        x_in, x_out = x - side_sign * ew * s, x + side_sign * ew * s * 1.1
        if expr == "curious" and i == 0:
            by -= 0.1 * r
        d.line((x_in, by + inner, x_out, by - inner * 0.3), fill=INK, width=max(3, int(0.09 * r)))
    mx, my = cx + off * 1.05 + (0.15 * r if view == "side" else 0), cy + 0.5 * r
    mw = 0.28 * r if view != "side" else 0.14 * r
    if expr in ("shocked", "scared"):
        h = 0.22 * r if expr == "shocked" else 0.16 * r
        d.ellipse((mx - mw * 0.55, my - h * 0.5, mx + mw * 0.55, my + h), fill=(60, 18, 24, 255), outline=INK, width=w)
    elif expr in ("worried", "sad"):
        d.arc((mx - mw, my - 0.02 * r, mx + mw, my + 0.28 * r), 200, 340, fill=INK, width=w)
    elif expr == "angry":
        d.rectangle((mx - mw * 0.8, my - 0.04 * r, mx + mw * 0.8, my + 0.08 * r), fill=WHITE, outline=INK, width=w)
    elif expr in ("determined", "sneaky", "confident", "smirk", "suspicious"):
        d.arc((mx - mw, my - 0.3 * r, mx + mw * 1.1, my + 0.1 * r), 30, 130, fill=INK, width=w)
    elif expr == "happy":
        d.arc((mx - mw * 1.1, my - 0.25 * r, mx + mw * 1.1, my + 0.26 * r), 10, 170, fill=INK, width=max(4, int(0.09 * r)))
    elif expr == "talking":
        d.ellipse((mx - 0.18 * r, my - 0.07 * r, mx + 0.18 * r, my + 0.21 * r),
                  fill=(54, 18, 25, 255), outline=INK, width=w)
    elif expr in ("thinking", "confused"):
        d.arc((mx - mw, my - 0.16 * r, mx + mw, my + 0.12 * r), 160, 345, fill=INK, width=w)
    elif expr == "curious":
        d.ellipse((mx - 0.06 * r, my - 0.03 * r, mx + 0.06 * r, my + 0.09 * r), outline=INK, width=w)
    else:
        d.line((mx - mw * 0.7, my + 0.04 * r, mx + mw * 0.7, my + 0.04 * r), fill=INK, width=w)
    if expr in ("worried", "scared") and view != "side":  # sweat drop
        sx, sy = cx + 0.82 * r + off * 0.3, cy - 0.35 * r
        d.polygon([(sx, sy - 0.16 * r), (sx - 0.08 * r, sy + 0.02 * r), (sx + 0.08 * r, sy + 0.02 * r)],
                  fill=(130, 200, 255, 255))
        d.ellipse((sx - 0.08 * r, sy - 0.04 * r, sx + 0.08 * r, sy + 0.12 * r), fill=(130, 200, 255, 255))


# ---------------------------------------------------------------- draw

def draw(look: dict, action: str = "standing", expression: str = "neutral", view: str = "front",
         facing: str = "right", t: float = 0.0, height: int = 900, blink: bool = False) -> tuple:
    """The figure on a transparent canvas. Returns (image, (foot_x, foot_y)) in image pixels."""
    action = action if action in ACTIONS else "standing"
    view = view if view in VIEWS else "front"
    if action in SIDE_ONLY:
        view = "side"
    if action == "leaving":
        view = "back" if view in ("back", "front") else view
    return _draw(tuple(sorted((k, v if not isinstance(v, list) else tuple(v)) for k, v in look.items())),
                 action, expression, view, facing, round(t, 3), int(height), blink)


@lru_cache(maxsize=96)
def _draw(look_items, action, expression, view, facing, t, height, blink):
    look = dict(look_items)
    SS = 2 if height <= 1100 else 1  # big close-ups are smooth enough without supersampling
    S = height * SS
    u = S / 10.0
    W_, H_ = int(S * 1.25), int(S * 1.2)
    ox, oy = W_ / 2, H_ - 0.12 * S  # feet centre
    im = Image.new("RGBA", (W_, H_), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    p = _pose(action, view, t)
    side = view == "side"
    back = view == "back"
    xs = 1.0 if view != "three_quarter" else 0.82
    lean = math.radians(p["lean"])

    def P(x, y):  # body units -> pixels (lean rotates around the hips)
        hip_y = -4.0 + p["drop"]
        yy = y + p["drop"] + p["bob"]
        if y < -4.0:  # above the hips: lean
            dy = yy - hip_y
            x, yy = x + math.sin(lean) * -dy, hip_y + dy * math.cos(lean)
        return ox + x * xs * u, oy + yy * u

    lw_leg, lw_arm = max(3, int(0.17 * u)), max(4, int(0.42 * u))
    hips = [(0.38, -4.0), (-0.38, -4.0)] if not side else [(0.05, -4.0), (-0.05, -4.0)]
    shoulders = [(1.0, -6.75), (-1.0, -6.75)] if not side else [(0.15, -6.7), (-0.1, -6.7)]
    jacket = tuple(look.get("jacket") or HOST["jacket"]) + (255,)
    far_jacket = tuple(int(c * 0.72) for c in jacket[:3]) + (255,)

    def leg(i, col=INK):
        root = hips[i]
        tgt = (p["feet"][i][0], p["feet"][i][1])
        if p["drop"] > 1.0 and side:  # seated: thigh forward at hip height, shin down to the floor
            knee = (root[0] + 1.85, root[1] + 0.1)
        elif not side:  # front / back / 3q stand: straight legs (IK made them cross)
            knee = ((root[0] + tgt[0]) / 2 + (0.06 if i == 0 else -0.06), (root[1] + p["drop"] + tgt[1]) / 2 - p["drop"])
        else:
            knee, _ = _ik((root[0], root[1] + p["drop"]), tgt, 2.0, 2.05, -1)
            knee = (knee[0], knee[1] - p["drop"])
        a, b, c = P(*root), P(*knee), (ox + tgt[0] * xs * u, oy + tgt[1] * u)
        d.line([a, b, c], fill=col, width=lw_leg, joint="curve")
        # shoe
        sw, sh = 0.62 * u, 0.32 * u
        fx = 1 if (side or i == 0) else -1
        shoe = (c[0] - sw * (0.35 if fx > 0 else 1.0), c[1] - sh * 0.8, c[0] + sw * (1.0 if fx > 0 else 0.35),
                c[1] + sh * 0.35)
        if back:
            shoe = (c[0] - sw * 0.5, c[1] - sh * 0.8, c[0] + sw * 0.5, c[1] + sh * 0.35)
        d.rounded_rectangle(shoe, radius=sh * 0.5, fill=INK)

    def arm(i, col):
        root = shoulders[i]
        tgt = p["hands"][i]
        elbow, hand = _ik(root, tgt, 1.55, 1.45, (1 if i == 0 else -1) if not side else 1)
        a, b, c = P(*root), P(*elbow), P(*hand)
        d.line([a, b, c], fill=col, width=lw_arm, joint="curve")
        hr = 0.3 * u
        d.ellipse((c[0] - hr * 0.95, c[1] - hr * 0.95, c[0] + hr * 0.95, c[1] + hr * 0.95), fill=WHITE,
                  outline=INK, width=max(2, int(0.06 * u)))

    # draw order: far limbs, legs, torso, head, near arm
    if side or view == "three_quarter":
        arm(1, far_jacket)
    if look.get("dress"):
        top, hem = P(0, -5.0), P(0, -1.3)
        wd = 1.6 * u * xs
        d.polygon([(top[0] - wd * 0.55, top[1]), (top[0] + wd * 0.55, top[1]), (hem[0] + wd, hem[1]),
                   (hem[0] - wd, hem[1])], fill=jacket, outline=INK)
        for i in (0, 1):  # legs below the hem
            c = (ox + p["feet"][i][0] * xs * u, oy + p["feet"][i][1] * u)
            d.line([(hem[0] + (0.35 if i == 0 else -0.35) * u, hem[1]), c], fill=INK, width=lw_leg)
            d.rounded_rectangle((c[0] - 0.35 * u, c[1] - 0.25 * u, c[0] + 0.35 * u, c[1] + 0.1 * u),
                                radius=0.12 * u, fill=INK)
    else:
        leg(1)
        leg(0)
    # torso (jacket)
    if side:
        poly = [(-0.55, -6.95), (0.6, -6.95), (0.72, -3.7), (-0.6, -3.7)]
    else:
        poly = [(-1.16, -6.98), (1.16, -6.98), (1.05, -5.6), (0.81, -3.82),
                (0.55, -3.64), (-0.55, -3.64), (-0.81, -3.82), (-1.05, -5.6)]
    pts = [P(x, y) for x, y in poly]
    d.polygon(pts, fill=jacket)
    d.line(pts + [pts[0]], fill=INK, width=max(3, int(0.08 * u)), joint="curve")
    if not side and not back and not look.get("dress"):
        sh_ = [P(-0.49, -6.94), P(0.49, -6.94), P(0.0, -4.73)]
        d.polygon(sh_, fill=tuple(look.get("shirt") or HOST["shirt"]) + (255,), outline=INK)
        if look.get("tie"):
            tie = [P(-0.12, -6.82), P(0.12, -6.82), P(0.19, -5.05),
                   P(0.0, -4.79), P(-0.19, -5.05)]
            d.polygon(tie, fill=tuple(look["tie"]) + (255,), outline=INK)
        for by in (-5.0, -4.5):
            b = P(0.0, by)
            d.ellipse((b[0] - 0.07 * u, b[1] - 0.07 * u, b[0] + 0.07 * u, b[1] + 0.07 * u), fill=INK)
        # Defined angular lapels make the jacket read as a fitted suit rather than a black box.
        # Drawn over the shoulders, outside the expanded white-shirt wedge.
        lapel = tuple(min(255, int(c * 1.55)) for c in jacket[:3]) + (255,)
        d.line([P(-1.12, -6.91), P(-0.83, -5.76), P(-0.46, -5.55)],
               fill=lapel, width=max(4, int(0.065 * u)), joint="curve")
        d.line([P(1.12, -6.91), P(0.83, -5.76), P(0.46, -5.55)],
               fill=lapel, width=max(4, int(0.065 * u)), joint="curve")
        d.line([P(-0.85, -5.77), P(-0.55, -4.80)], fill=INK, width=max(3, int(0.06 * u)))
        d.line([P(0.85, -5.77), P(0.55, -4.80)], fill=INK, width=max(3, int(0.06 * u)))
    elif back:
        a, b = P(0, -6.9), P(0, -3.65)
        d.line([a, b], fill=INK, width=max(2, int(0.05 * u)))
    elif side and look.get("tie"):
        t1 = P(0.55, -6.9)
        d.line([t1, P(0.66, -5.3)], fill=tuple(look["tie"]) + (255,), width=max(3, int(0.12 * u)))
    # head
    r = 1.4 * u
    hc = P(0.0 if not side else 0.15, -8.55)
    if look.get("hair") == "bun" and True:
        bx = hc[0] - (0.6 * r if side else 0)
        d.ellipse((bx - 0.45 * r, hc[1] - 1.25 * r, bx + 0.45 * r, hc[1] - 0.45 * r), fill=(60, 40, 30, 255),
                  outline=INK, width=max(2, int(0.05 * u)))
    d.ellipse((hc[0] - r, hc[1] - r, hc[0] + r, hc[1] + r), fill=WHITE, outline=INK, width=max(3, int(0.1 * u)))
    face_view = view
    if p["head_back"] or back:
        face_view = None
    if face_view:
        if look.get("beard"):
            d.chord((hc[0] - 0.85 * r + (0.3 * r if side else 0), hc[1] - 0.05 * r,
                     hc[0] + 0.85 * r + (0.3 * r if side else 0), hc[1] + 1.02 * r), 0, 180,
                    fill=(52, 38, 30, 255), outline=INK)
        _face(d, hc[0], hc[1], r, expression, face_view, blink)
    hat = look.get("hat")
    if hat:
        col = (28, 28, 32, 255)
        if hat == "top":
            d.rectangle((hc[0] - 0.62 * r, hc[1] - 2.0 * r, hc[0] + 0.62 * r, hc[1] - 0.72 * r), fill=col)
        elif hat == "bowler":
            d.chord((hc[0] - 0.78 * r, hc[1] - 1.55 * r, hc[0] + 0.78 * r, hc[1] - 0.1 * r), 180, 360, fill=col)
        else:  # cap
            d.chord((hc[0] - 0.92 * r, hc[1] - 1.2 * r, hc[0] + 0.92 * r, hc[1] + 0.2 * r), 180, 360, fill=col)
        bw = 1.15 if hat != "cap" else 0.9
        d.rounded_rectangle((hc[0] - bw * r + (0.25 * r if hat == "cap" and side else 0), hc[1] - 0.86 * r,
                             hc[0] + bw * r + (0.55 * r if hat == "cap" else 0), hc[1] - 0.7 * r),
                            radius=0.06 * r, fill=col)
    if view == "front" or back:  # arms over the head: hands on the cheeks / raised stay visible
        arm(1, jacket)
    arm(0, jacket)
    if action == "seated":  # a plain crate under the hips
        c1, c2 = (ox - 0.9 * u, oy - 2.25 * u), (ox + 0.9 * u, oy)
        d.rectangle((c1[0], c1[1], c2[0], c2[1]), fill=(86, 64, 44, 255), outline=INK, width=max(2, int(0.06 * u)))
    out = im.resize((W_ // SS, H_ // SS), Image.LANCZOS)
    if facing == "left":
        from PIL import ImageOps
        out = ImageOps.mirror(out)
        return out, (out.width - ox / SS, oy / SS)
    return out, (ox / SS, oy / SS)
