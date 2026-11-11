"""Builds frontend/static/board-font.json: the single-stroke handwriting the class blackboard writes with
(static/mrsolis-board.js draws every stroke with a moving pen, so a letter appears the way a hand writes it).

    python scripts/build_board_font.py <folder of the unpacked npm package "hersheytext" 2.0.0> [--font EMSTech] [--out FILE]

Sources (both in that package):
  svg_fonts/EMSTech.svg   "EMS Tech" by Sheldon B. Michaels, a single-line derivative of Architects Daughter
                          (Kimberly Geswein), SIL Open Font License 1.1: Latin letters, digits, punctuation, Latin-1.
  hersheytext.min.json    the Hershey fonts (Dr A. V. Hershey, US National Bureau of Standards; free to use with
                          this acknowledgement): the Greek alphabet.
A few maths signs neither has (arrow, approx, <=, >=, not-equal, infinity, minus, bullet, tick...) are drawn here.

The JSON: {"upm": 1000, "cap": 500, "xh": 300, "glyphs": {"A": {"a": advance, "s": [[x, y, x, y, ...], ...]}}}
with y up from the baseline, one list per pen stroke, curves already cut into short straight pieces.
"""
import html
import json
import math
import os
import re
import sys

NUM = re.compile(r"[MLCQZHVSTmlcqzhvst]|-?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")


def strokes_of(d: str) -> list:
    """An SVG path as pen strokes: lists of (x, y), curves flattened."""
    tok = NUM.findall(d)
    out, cur, i, cmd = [], [], 0, ""
    x = y = sx = sy = 0.0
    last_ctrl = None

    def num():
        nonlocal i
        v = float(tok[i])
        i += 1
        return v

    def curve(p0, p1, p2, p3):
        chord = math.dist(p0, p1) + math.dist(p1, p2) + math.dist(p2, p3)
        n = max(2, min(24, int(chord / 14) + 1))
        for k in range(1, n + 1):
            t = k / n
            a = (1 - t) ** 3
            b = 3 * (1 - t) ** 2 * t
            c = 3 * (1 - t) * t * t
            e = t ** 3
            cur.append((a * p0[0] + b * p1[0] + c * p2[0] + e * p3[0], a * p0[1] + b * p1[1] + c * p2[1] + e * p3[1]))

    while i < len(tok):
        if tok[i].isalpha():
            cmd = tok[i]
            i += 1
            if cmd in "Zz":
                if cur:
                    cur.append((sx, sy))
                x, y = sx, sy
                continue
        rel = cmd.islower()
        c = cmd.upper()
        if c == "M":
            nx, ny = num(), num()
            if rel:
                nx, ny = x + nx, y + ny
            if len(cur) > 1:
                out.append(cur)
            cur = [(nx, ny)]
            x, y, sx, sy = nx, ny, nx, ny
            cmd = "l" if rel else "L"            # further pairs are line-tos
            last_ctrl = None
        elif c == "L":
            nx, ny = num(), num()
            if rel:
                nx, ny = x + nx, y + ny
            cur.append((nx, ny))
            x, y = nx, ny
            last_ctrl = None
        elif c == "H":
            nx = num() + (x if rel else 0)
            cur.append((nx, y))
            x = nx
        elif c == "V":
            ny = num() + (y if rel else 0)
            cur.append((x, ny))
            y = ny
        elif c == "C":
            p = [num() for _ in range(6)]
            if rel:
                p = [p[0] + x, p[1] + y, p[2] + x, p[3] + y, p[4] + x, p[5] + y]
            curve((x, y), (p[0], p[1]), (p[2], p[3]), (p[4], p[5]))
            last_ctrl = (p[2], p[3])
            x, y = p[4], p[5]
        elif c == "S":
            p = [num() for _ in range(4)]
            if rel:
                p = [p[0] + x, p[1] + y, p[2] + x, p[3] + y]
            c1 = (2 * x - last_ctrl[0], 2 * y - last_ctrl[1]) if last_ctrl else (x, y)
            curve((x, y), c1, (p[0], p[1]), (p[2], p[3]))
            last_ctrl = (p[0], p[1])
            x, y = p[2], p[3]
        elif c == "Q":
            p = [num() for _ in range(4)]
            if rel:
                p = [p[0] + x, p[1] + y, p[2] + x, p[3] + y]
            q = (p[0], p[1])
            curve((x, y), (x + 2 / 3 * (q[0] - x), y + 2 / 3 * (q[1] - y)),
                  (p[2] + 2 / 3 * (q[0] - p[2]), p[3] + 2 / 3 * (q[1] - p[3])), (p[2], p[3]))
            x, y = p[2], p[3]
        else:                                    # T, A: not used by these fonts
            raise ValueError(f"path command {cmd} isn't handled")
    if len(cur) > 1:
        out.append(cur)
    return out


def thin(points, tol=1.2):
    """Drop points that sit on the straight line between their neighbours (keeps the JSON small)."""
    keep = [points[0]]
    for a, b in zip(points[1:], points[2:]):
        p = keep[-1]
        area = abs((a[0] - p[0]) * (b[1] - p[1]) - (a[1] - p[1]) * (b[0] - p[0]))
        # a point where the pen turns back on itself stays (the stem of "t" goes down, then back up to its bar)
        forward = (a[0] - p[0]) * (b[0] - a[0]) + (a[1] - p[1]) * (b[1] - a[1]) > 0
        if area / (math.dist(p, b) or 1) > tol or not forward:
            keep.append(a)
    keep.append(points[-1])
    return keep


def pack(strokes):
    return [[round(v) for pt in thin(s) for v in pt] for s in strokes if len(s) > 1]


def svg_font(path):
    text = open(path, encoding="utf-8").read()
    default = int(re.search(r'<font [^>]*horiz-adv-x="(\d+)"', text).group(1))
    glyphs = {}
    for g in re.findall(r"<glyph\s[^>]*>", text, re.S):
        uni = re.search(r'unicode="([^"]*)"', g)
        if not uni:
            continue
        ch = html.unescape(uni.group(1))
        if len(ch) != 1:
            continue
        adv = re.search(r'horiz-adv-x="([\d.]+)"', g)
        d = re.search(r'\sd="([^"]*)"', g)
        glyphs[ch] = {"a": round(float(adv.group(1))) if adv else default, "s": pack(strokes_of(d.group(1))) if d else []}
    return glyphs


# Hershey "Greek 1-stroke": the Greek alphabet sits on the Latin keys the way the Symbol font has it
# (q is theta, w is omega, c is chi...). Checked by eye on the test bench's "glyphs" sheet.
GREEK = {"α": "a", "β": "b", "γ": "g", "δ": "d", "ε": "e", "ζ": "z", "η": "h", "ι": "i", "κ": "k", "λ": "l",
         "μ": "m", "ν": "n", "ξ": "x", "ο": "o", "π": "p", "ρ": "r", "σ": "s", "τ": "t", "υ": "u", "φ": "f", "χ": "c",
         "ψ": "y", "ω": "w",
         "Α": "A", "Β": "B", "Γ": "G", "Δ": "D", "Ε": "E", "Ζ": "Z", "Η": "H", "Θ": "Q", "Ι": "I", "Κ": "K", "Λ": "L",
         "Μ": "M", "Ν": "N", "Ξ": "X", "Ο": "O", "Π": "P", "Ρ": "R", "Σ": "S", "Τ": "T", "Υ": "U", "Φ": "F", "Χ": "C",
         "Ψ": "Y", "Ω": "W"}


def hershey_greek(path, cap):
    chars = json.load(open(path, encoding="utf-8"))["greek"]["chars"]
    k = cap / 21                                 # Hershey capitals are 21 units tall
    out = {}
    for ch, key in GREEK.items():
        c = chars[ord(key) - 33]
        strokes = [[(x * k, (22 - y) * k) for x, y in s] for s in hershey_strokes(c["d"])]
        out[ch] = {"a": round(int(c["o"]) * 2 * k), "s": pack(strokes)}
    return out


def hershey_strokes(d):
    out = []
    for part in d.split("M")[1:]:
        pts = [tuple(float(v) for v in p.split(",")) for p in part.replace("L", " ").split()]
        if len(pts) > 1:
            out.append(pts)
    return out


def arc(cx, cy, rx, ry, a0, a1, n=14):
    return [(cx + rx * math.cos(math.radians(a0 + (a1 - a0) * i / n)), cy + ry * math.sin(math.radians(a0 + (a1 - a0) * i / n)))
            for i in range(n + 1)]


def wave(x0, x1, y, h, n=16):
    return [(x0 + (x1 - x0) * i / n, y + h * math.sin(2 * math.pi * i / n)) for i in range(n + 1)]


def extras():
    """Signs drawn by hand here, in the EMS fonts' own measure (capitals 500 tall, small letters 300)."""
    inf = [(250 + 200 * math.cos(t) / (1 + math.sin(t) ** 2), 250 + 260 * math.sin(t) * math.cos(t) / (1 + math.sin(t) ** 2))
           for t in [2 * math.pi * i / 40 for i in range(41)]]
    g = {
        "−": (520, [[(70, 250), (450, 250)]]),
        "–": (520, [[(60, 250), (460, 250)]]),
        "—": (760, [[(50, 250), (710, 250)]]),
        "→": (640, [[(50, 250), (590, 250)], [(450, 350), (590, 250), (450, 150)]]),
        "←": (640, [[(590, 250), (50, 250)], [(190, 350), (50, 250), (190, 150)]]),
        "⇒": (680, [[(50, 310), (540, 310)], [(50, 190), (540, 190)], [(450, 400), (630, 250), (450, 100)]]),
        "↑": (420, [[(210, 20), (210, 540)], [(90, 400), (210, 540), (330, 400)]]),
        "↓": (420, [[(210, 540), (210, 20)], [(90, 160), (210, 20), (330, 160)]]),
        "≈": (540, [wave(60, 480, 320, 38), wave(60, 480, 180, 38)]),
        "∼": (540, [wave(60, 480, 250, 42)]),
        "≠": (540, [[(60, 320), (480, 320)], [(60, 180), (480, 180)], [(360, 460), (180, 40)]]),
        "≤": (540, [[(450, 440), (80, 290), (450, 150)], [(80, 50), (450, 50)]]),
        "≥": (540, [[(80, 440), (450, 290), (80, 150)], [(80, 50), (450, 50)]]),
        "∞": (560, [[(x + 30, y) for x, y in inf]]),
        "√": (520, [[(30, 250), (110, 290), (220, 10), (370, 660), (540, 660)]]),
        "∴": (520, [arc(260, 420, 22, 22, 0, 360, 8), arc(110, 120, 22, 22, 0, 360, 8), arc(410, 120, 22, 22, 0, 360, 8)]),
        "∝": (560, [[(500, 380), (420, 380), (300, 250), (190, 130), (110, 130), (60, 190), (60, 310), (110, 370),
                     (190, 370), (300, 250), (420, 120), (500, 120)]]),
        "∫": (380, [arc(270, 600, 70, 70, 20, 180, 8) + [(200, 600), (180, -60)] + arc(110, -60, 70, 70, 0, -160, 8)]),
        "∂": (480, [[(120, 520), (220, 560), (320, 520), (380, 400), (380, 180), (320, 50), (220, 0), (120, 40),
                     (80, 150), (120, 270), (220, 320), (320, 290), (380, 200)]]),
        "∠": (560, [[(480, 480), (70, 40), (500, 40)]]),
        "⊥": (560, [[(280, 480), (280, 40)], [(60, 40), (500, 40)]]),
        "∥": (360, [[(120, 540), (120, -20)], [(240, 540), (240, -20)]]),
        "△": (600, [[(300, 500), (60, 30), (540, 30), (300, 500)]]),
        "•": (380, [arc(190, 200, 46, 46, 0, 360, 12), arc(190, 200, 20, 20, 0, 360, 8)]),
        "✓": (560, [[(60, 260), (200, 60), (500, 540)]]),
        "✗": (520, [[(80, 480), (440, 40)], [(440, 480), (80, 40)]]),
        "′": (220, [[(140, 560), (90, 400)]]),
        "″": (340, [[(140, 560), (90, 400)], [(260, 560), (210, 400)]]),
        "…": (760, [arc(120, 20, 18, 18, 0, 360, 8), arc(380, 20, 18, 18, 0, 360, 8), arc(640, 20, 18, 18, 0, 360, 8)]),
        "⋅": (300, [arc(150, 250, 20, 20, 0, 360, 8)]),
    }
    return {ch: {"a": adv, "s": pack(strokes)} for ch, (adv, strokes) in g.items()}


def redrawn(cap):
    """Letters and signs the font draws in a way a class would misread, drawn again:
    1 and I are both a bare stroke in it (so "I = 1 A" was three sticks), and its × ÷ ± sit outside their own space."""
    g = {
        "1": (330, [[(70, cap * 0.78), (185, cap), (178, 12)]]),
        "I": (330, [[(165, cap), (160, 12)], [(70, cap), (262, cap + 4)], [(66, 10), (260, 14)]]),
        "×": (520, [[(110, 400), (410, 100)], [(410, 404), (112, 98)]]),
        "÷": (540, [[(80, 250), (460, 250)], arc(270, 395, 20, 20, 0, 360, 8), arc(270, 105, 20, 20, 0, 360, 8)]),
        "±": (540, [[(270, 500), (270, 190)], [(100, 345), (440, 345)], [(100, 80), (440, 80)]]),
        "∓": (540, [[(100, 480), (440, 480)], [(270, 370), (270, 60)], [(100, 215), (440, 215)]]),
        "·": (300, [arc(150, 250, 20, 20, 0, 360, 8)]),
        "θ": (480, [arc(240, cap / 2, 150, cap / 2, 90, 450, 22), [(96, cap / 2 + 6), (384, cap / 2 - 4)]]),
    }
    return {ch: {"a": adv, "s": pack(strokes)} for ch, (adv, strokes) in g.items()}


def main():
    src = sys.argv[1]
    font = sys.argv[sys.argv.index("--font") + 1] if "--font" in sys.argv else "EMSTech"
    here = os.path.dirname(os.path.abspath(__file__))
    out = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else os.path.join(
        here, "..", "frontend", "static", "board-font.json")
    glyphs = svg_font(os.path.join(src, "svg_fonts", font + ".svg"))

    def reach(letters, pick):                    # how high / low the font's own letters go
        return pick(v for ch in letters for s in glyphs[ch]["s"] for v in s[1::2])

    cap, xh = reach("HEB", max), reach("xz", max)
    asc, desc = reach("bdhkl", max), -reach("gpqy", min)
    for ch, g in {**hershey_greek(os.path.join(src, "hersheytext.min.json"), cap), **extras()}.items():
        glyphs.setdefault(ch, g)
    glyphs.update(redrawn(cap))
    # look-alikes typed from other parts of Unicode: the ohm sign, the increment sign, the micro sign, curly quotes
    for alias, ch in {"Ω": "Ω", "∆": "Δ", "∑": "Σ", "∏": "Π",
                      "µ": "μ", "’": "'", "‘": "'", "“": '"', "”": '"',
                      "ϕ": "φ", "ϵ": "ε", "ϑ": "θ"}.items():
        if ch in glyphs:
            glyphs[alias] = glyphs[ch]
    data = {"name": font, "upm": 1000, "cap": cap, "xh": xh, "asc": asc, "desc": desc, "glyphs": glyphs}
    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    points = sum(len(s) // 2 for g in glyphs.values() for s in g["s"])
    print(f"{font}: {len(glyphs)} glyphs, {points} points, {os.path.getsize(out) / 1024:.0f} KB -> {os.path.normpath(out)}")


if __name__ == "__main__":
    main()
