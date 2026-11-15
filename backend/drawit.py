"""Draw it (/draw) — a study diagram the brain plans and code draws, exactly.

The user (2026-11-14), after seeing a 1B image model: picture models paint things that look right but often aren't
(gibberish labels, parts in the wrong place, circuits that don't connect), so MrSOLIS doesn't paint. The brain only
picks the kind of diagram and fills in its words and numbers; code lays it out and draws it as SVG:

  graph     y = f(x) on axes. The curve, its x-intercepts and its y-intercept are worked out by code — and when the
            student typed the equation ("/draw y = x^2 - 4 from -3 to 3") no brain is asked at all
  steps     a process in order            cycle     a process that repeats
  mindmap   a topic and its parts         timeline  events in date order
  bars      numbers to compare            circuit   a series or parallel circuit with its parts

Every label is cleaned like /summarize's (summary.plain_text: no LaTeX, no **bold**; classroom._HIDE: no real model's
name). A function is read by _Parser, a tiny reader of our own: nothing a student, a slide or the brain wrote is ever
run as code. The drawing uses currentColor, so it suits the dark chat and prints black on white when saved.
"""
import html
import json
import math
import re

from backend import brain, classroom
from backend.summary import plain_text

KINDS = ("graph", "steps", "cycle", "mindmap", "bars", "timeline", "circuit")
PARTS = ("resistor", "lamp", "ammeter", "voltmeter", "switch", "capacitor", "motor")
FONT = "Inter Tight, Segoe UI, Arial, sans-serif"


class DrawError(ValueError):
    """What to tell the student, in plain words."""


def _e(s) -> str:
    return html.escape(str(s), quote=True)


_SUP = str.maketrans("-0123456789", "⁻⁰¹²³⁴⁵⁶⁷⁸⁹")


def _clean(s, limit: int) -> str:
    """A label as the drawing shows it: plain text, one line, no real model's name, at most `limit` characters, maths
    as a student writes it (x², 2t, 3 × 4 — not x^2, 2*t, 3*4)."""
    s = classroom._HIDE.sub("MrSOLIS", plain_text(str(s or "")))
    s = re.sub(r"\^\(?(-?\d+)\)?", lambda m: m.group(1).translate(_SUP), s)
    s = re.sub(r"(\d)\s*\*\s*(?=[A-Za-z(])", r"\1", s)       # 2*t -> 2t
    s = re.sub(r"\s*\*\s*", " × ", s)
    s = re.sub(r"\s+", " ", s.replace("#", "")).strip(" -–•*")
    return s if len(s) <= limit else s[:limit - 1].rstrip() + "…"


def _fmt(v: float) -> str:
    """A number as a student writes it: 3 significant figures, no trailing zeros, a real minus sign."""
    if not math.isfinite(v):
        return "?"
    if abs(v) < 1e-9:
        return "0"
    s = f"{v:.3g}"
    if "e" in s:
        m, ex = s.split("e")
        s = f"{m} × 10^{int(ex)}"
    return s.replace("-", "−")


def _wrap(text: str, chars: int) -> list:
    """Words into lines of at most `chars` characters (a longer word is cut)."""
    lines, line = [], ""
    for word in str(text).split():
        while len(word) > chars:
            if line:
                lines.append(line)
                line = ""
            lines.append(word[:chars])
            word = word[chars:]
        if not line:
            line = word
        elif len(line) + 1 + len(word) <= chars:
            line += " " + word
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines or [""]


def _chars(width: float, size: float, bold: bool = False) -> int:
    """How many characters fit in `width` at font `size` (an average letter is ~0.55 em, bold ~0.6)."""
    return max(4, int(width / (size * (0.6 if bold else 0.54))))


def _svg(w: float, h: float, body: str, label: str) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w:.0f} {h:.0f}" width="{w:.0f}" height="{h:.0f}" '
            f'class="drawit" role="img" aria-label="{_e(label)}" font-family="{FONT}">{body}</svg>')


def _text(x, y, s, size=14, weight=400, anchor="start", opacity=1.0, extra="") -> str:
    op = f' fill-opacity="{opacity}"' if opacity < 1 else ""
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" font-weight="{weight}" text-anchor="{anchor}" '
            f'fill="currentColor"{op}{extra}>{_e(s)}</text>')


def _lines(x, y, lines, size=14, weight=400, anchor="start", opacity=1.0, lead=1.3) -> str:
    return "".join(_text(x, y + i * size * lead, ln, size, weight, anchor, opacity) for i, ln in enumerate(lines))


def _box(x, y, w, h, rx=10, soft=0.07, edge=0.45) -> str:
    return (f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="{rx}" fill="currentColor" '
            f'fill-opacity="{soft}" stroke="currentColor" stroke-opacity="{edge}" stroke-width="1.4"/>')


def _line(x1, y1, x2, y2, width=2.0, opacity=1.0, dash="") -> str:
    d = f' stroke-dasharray="{dash}"' if dash else ""
    op = f' stroke-opacity="{opacity}"' if opacity < 1 else ""
    return (f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="currentColor" '
            f'stroke-width="{width}"{op}{d} stroke-linecap="round"/>')


def _head(x, y, angle, size=9) -> str:
    """An arrowhead with its tip at (x, y), pointing along `angle` (radians)."""
    a, b = angle + math.pi - 0.42, angle + math.pi + 0.42
    pts = [(x, y), (x + size * math.cos(a), y + size * math.sin(a)), (x + size * math.cos(b), y + size * math.sin(b))]
    return '<polygon points="' + " ".join(f"{px:.1f},{py:.1f}" for px, py in pts) + '" fill="currentColor"/>'


# ══ reading a function: a tiny parser of our own — nothing is ever eval'd ═════════════════════════════════════════════
_FUNCS = {"sin": math.sin, "cos": math.cos, "tan": math.tan, "asin": math.asin, "acos": math.acos, "atan": math.atan,
          "arcsin": math.asin, "arccos": math.acos, "arctan": math.atan, "sinh": math.sinh, "cosh": math.cosh,
          "tanh": math.tanh, "sqrt": math.sqrt, "exp": math.exp, "ln": math.log, "log": math.log10, "abs": abs}
_CONSTS = {"pi": math.pi, "e": math.e}
_TOKEN = re.compile(r"\s*(?:(\d+\.?\d*(?:[eE][-+]?\d+)?|\.\d+)|([A-Za-z]+)|([-+*/^()|]))")
_NAMES = sorted(list(_FUNCS) + ["pi"], key=len, reverse=True)


def _normal(text: str) -> str:
    s = plain_text(text)
    for a, b in (("×", "*"), ("·", "*"), ("⋅", "*"), ("÷", "/"), ("−", "-"), ("–", "-"), ("π", "pi"), ("√", "sqrt"),
                 ("²", "^2"), ("³", "^3"), ("**", "^"), ("[", "("), ("]", ")")):
        s = s.replace(a, b)
    return s.strip().rstrip(".")


def free_letters(text: str) -> list:
    """The variables in an expression: letters that aren't a function or a constant ("2x + sin(x)" -> ["x"])."""
    out = []
    for name in re.findall(r"[A-Za-z]+", _normal(text)):
        i = 0
        while i < len(name):
            fn = next((f for f in _NAMES if name.startswith(f, i)), None)
            if fn:
                i += len(fn)
                continue
            if name[i] != "e" and name[i] not in out:
                out.append(name[i])
            i += 1
    return out


class _Parser:
    """expr := term (± term)*   term := unary ((*|/|implied) unary)*   unary := (±) unary | power
       power := atom (^ unary)?  atom := number | var | constant | func atom-or-(expr) | (expr) | |expr|"""

    def __init__(self, text: str, var: str):
        self.var, self.toks, self.i, self.bars = var, [], 0, 0
        s, pos = _normal(text), 0
        while pos < len(s):
            m = _TOKEN.match(s, pos)
            if not m or m.end() == pos:
                if s[pos:].strip():
                    raise DrawError(f"MrSOLIS can't read “{s[pos:pos + 12]}” in that function.")
                break
            pos = m.end()
            if m.group(1):
                self.toks.append(("num", float(m.group(1))))
            elif m.group(2):
                self._name(m.group(2))
            else:
                self.toks.append(("op", m.group(3)))

    def _name(self, name: str):
        i = 0
        while i < len(name):                                # "2xsinx" -> x, sin, x
            fn = next((f for f in _NAMES if name.startswith(f, i)), None)
            if fn:
                self.toks.append(("const", _CONSTS[fn]) if fn == "pi" else ("func", fn))
                i += len(fn)
            elif name[i] == self.var:
                self.toks.append(("var", None))
                i += 1
            elif name[i] == "e":
                self.toks.append(("const", math.e))
                i += 1
            else:
                raise DrawError(f"“{name}” isn't something MrSOLIS can draw: use {self.var} as the variable.")

    def peek(self):
        return self.toks[self.i] if self.i < len(self.toks) else (None, None)

    def take(self):
        t = self.peek()
        self.i += 1
        return t

    def parse(self):
        if not self.toks:
            raise DrawError("There's no function to draw.")
        node = self.expr()
        if self.i < len(self.toks):
            raise DrawError("MrSOLIS couldn't read that function to the end.")
        return node

    def expr(self):
        node = self.term()
        while self.peek() in (("op", "+"), ("op", "-")):
            node = (self.take()[1], node, self.term())
        return node

    def _starts_atom(self) -> bool:
        k, v = self.peek()
        return k in ("num", "var", "const", "func") or (k == "op" and (v == "(" or (v == "|" and not self.bars)))

    def term(self):
        node = self.unary()
        while True:
            if self.peek() in (("op", "*"), ("op", "/")):
                node = (self.take()[1], node, self.unary())
            elif self._starts_atom():                       # 2x, 3(x + 1), x sin x
                node = ("*", node, self.power())
            else:
                return node

    def unary(self):
        if self.peek() in (("op", "-"), ("op", "+")):
            sign = self.take()[1]
            node = self.unary()
            return ("neg", node) if sign == "-" else node
        return self.power()

    def power(self):
        base = self.atom()
        if self.peek() == ("op", "^"):
            self.take()
            return ("^", base, self.unary())
        return base

    def atom(self):
        k, v = self.take()
        if k == "num":
            return ("num", v)
        if k == "const":
            return ("num", v)
        if k == "var":
            return ("var",)
        if k == "func":
            if self.peek() == ("op", "("):
                self.take()
                arg = self.expr()
                self._close(")")
            else:
                arg = self.power()                          # sin x
            return ("fn", v, arg)
        if (k, v) == ("op", "("):
            node = self.expr()
            self._close(")")
            return node
        if (k, v) == ("op", "|"):
            self.bars += 1
            node = self.expr()
            self._close("|")
            self.bars -= 1
            return ("fn", "abs", node)
        raise DrawError("MrSOLIS couldn't read that function.")

    def _close(self, ch: str):
        if self.take() != ("op", ch):
            raise DrawError(f"A “{'(' if ch == ')' else ch}” in that function isn't closed.")


def _ev(n, x: float) -> float:
    t = n[0]
    if t == "num":
        return n[1]
    if t == "var":
        return x
    if t == "neg":
        return -_ev(n[1], x)
    if t == "fn":
        return float(_FUNCS[n[1]](_ev(n[2], x)))
    a, b = _ev(n[1], x), _ev(n[2], x)
    if t == "+":
        return a + b
    if t == "-":
        return a - b
    if t == "*":
        return a * b
    if t == "/":
        return a / b
    return math.pow(a, b)


class Function:
    """y = f(var), read once, evaluated safely: a point it can't have (1/0, √−1) is NaN, never an error."""

    def __init__(self, text: str, var: str = "x"):
        self.var, self.text = var, _normal(text)
        if len(self.text) > 120:
            raise DrawError("That function is too long to draw.")
        self.tree = _Parser(self.text, var).parse()

    def __call__(self, x: float) -> float:
        try:
            y = _ev(self.tree, x)
            return y if isinstance(y, float) and math.isfinite(y) else float(y) if isinstance(y, int) else float("nan")
        except (ValueError, ZeroDivisionError, OverflowError, TypeError):
            return float("nan")

    def pretty(self) -> str:
        s = re.sub(r"\^\(?(-?\d+)\)?", lambda m: "".join("⁻⁰¹²³⁴⁵⁶⁷⁸⁹"[("-0123456789".index(c))] for c in m.group(1)),
                   self.text)
        s = s.replace("sqrt", "√").replace("pi", "π").replace("*", "·").replace("-", "−")
        return re.sub(r"\s+", " ", s)


# ══ the drawings ═══════════════════════════════════════════════════════════════════════════════════════════════════════
def _nice_step(span: float, count: int) -> float:
    raw = span / max(1, count)
    mag = 10 ** math.floor(math.log10(raw)) if raw > 0 else 1
    return next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)


def _ticks(lo: float, hi: float, count: int) -> list:
    step = _nice_step(hi - lo, count)
    t, out = math.ceil(lo / step - 1e-9) * step, []
    while t <= hi + 1e-9:
        out.append(0.0 if abs(t) < step * 1e-6 else t)
        t += step
    return out


def _roots(f, a: float, b: float) -> list:
    """Where f crosses 0 between a and b (a sign change that isn't an asymptote), to 4 significant figures."""
    out, n = [], 400
    xs = [a + (b - a) * i / n for i in range(n + 1)]
    ys = [f(x) for x in xs]
    for i in range(n):
        y0, y1 = ys[i], ys[i + 1]
        if not (math.isfinite(y0) and math.isfinite(y1)):
            continue
        if y0 == 0:
            r = xs[i]
        elif y0 * y1 < 0:
            lo, hi, flo = xs[i], xs[i + 1], y0
            for _ in range(60):
                mid = (lo + hi) / 2
                fm = f(mid)
                if not math.isfinite(fm):
                    break
                if flo * fm <= 0:
                    hi = mid
                else:
                    lo, flo = mid, fm
            r = (lo + hi) / 2
            if not math.isfinite(f(r)) or abs(f(r)) > 1e-6 * (1 + abs(y0) + abs(y1)):
                continue                                    # a jump through infinity (1/x at 0), not a root
        else:
            continue
        if not out or abs(r - out[-1]) > (b - a) / n:
            out.append(r)
    if ys and math.isfinite(ys[-1]) and ys[-1] == 0 and (not out or abs(out[-1] - b) > (b - a) / n):
        out.append(b)
    return out[:6]


def render_graph(funcs: list, a: float, b: float, x_label: str, y_label: str, title: str, name: str = "y",
                 var: str = "x") -> tuple:
    """(svg, caption): the curves on axes, with code-found intercepts marked. funcs: [(Function, label)]."""
    W, H, L, R, T, B = 600, 400, 62, 22, 24, 50
    pw, ph = W - L - R, H - T - B
    n = 600
    xs = [a + (b - a) * i / n for i in range(n + 1)]
    series = [[f(x) for x in xs] for f, _ in funcs]
    finite = sorted(y for s in series for y in s if math.isfinite(y))
    if not finite:
        raise DrawError(f"That function has no values to draw between {_fmt(a)} and {_fmt(b)}.")
    lo, hi = finite[0], finite[-1]
    if len(finite) > 40:                                    # an asymptote (tan x, 1/x): frame the curve, not infinity
        p_lo, p_hi = finite[int(0.04 * len(finite))], finite[int(0.96 * len(finite)) - 1]
        if hi - lo > 6 * (p_hi - p_lo + 1e-12):
            lo, hi = p_lo - 0.5 * (p_hi - p_lo), p_hi + 0.5 * (p_hi - p_lo)
    if lo > 0 and lo < 0.4 * hi:
        lo = 0.0
    if hi < 0 and hi > 0.4 * lo:
        hi = 0.0
    if hi - lo < 1e-9:
        lo, hi = lo - 1, hi + 1
    pad = (hi - lo) * 0.08
    lo, hi = lo - pad, hi + pad
    X = lambda x: L + (x - a) / (b - a) * pw
    Y = lambda y: T + (hi - y) / (hi - lo) * ph
    body = []
    xt, yt = _ticks(a, b, 8), _ticks(lo, hi, 6)
    for t in xt:
        body.append(_line(X(t), T, X(t), T + ph, 1, 0.12))
    for t in yt:
        body.append(_line(L, Y(t), L + pw, Y(t), 1, 0.12))
    ax_y = Y(0) if lo <= 0 <= hi else T + ph               # the x-axis where y = 0, else along the bottom
    ax_x = X(0) if a <= 0 <= b else L
    body.append(_line(L, ax_y, L + pw, ax_y, 1.6, 0.85))
    body.append(_line(ax_x, T, ax_x, T + ph, 1.6, 0.85))
    body.append(_head(L + pw + 6, ax_y, 0, 8) + _head(ax_x, T - 6, -math.pi / 2, 8))
    for t in xt:
        if abs(X(t) - ax_x) > 4 or not (a <= 0 <= b):
            body.append(_text(X(t), min(ax_y + 17, T + ph + 17), _fmt(t), 13.5, anchor="middle", opacity=0.8))
    for t in yt:
        if abs(Y(t) - ax_y) > 4:
            body.append(_text(ax_x - 7, Y(t) + 4, _fmt(t), 13.5, anchor="end", opacity=0.8))
    body.append(_text(L + pw, T + ph + 38, x_label, 15, 700, "end"))
    body.append(_text(ax_x + 8, T + 6, y_label, 15, 700))
    dashes = ("", "9 6", "2.5 5")
    span = hi - lo
    for k, s in enumerate(series):
        segs, cur = [], []
        for i, y in enumerate(s):
            ok = math.isfinite(y) and lo <= y <= hi
            if cur and i and math.isfinite(s[i - 1]) and math.isfinite(y) and abs(y - s[i - 1]) > span * 0.9:
                segs.append(cur)                            # a jump: an asymptote, don't join it
                cur = []
            if ok:
                if not cur and i and math.isfinite(s[i - 1]) and not (lo <= s[i - 1] <= hi):
                    yb = hi if s[i - 1] > hi else lo        # coming in through the edge of the frame
                    xb = xs[i - 1] + (xs[i] - xs[i - 1]) * (yb - s[i - 1]) / (y - s[i - 1])
                    cur.append((X(xb), Y(yb)))
                cur.append((X(xs[i]), Y(y)))
            elif cur:
                if math.isfinite(y):                        # going out through the edge
                    yb = hi if y > hi else lo
                    xb = xs[i - 1] + (xs[i] - xs[i - 1]) * (yb - s[i - 1]) / (y - s[i - 1])
                    cur.append((X(xb), Y(yb)))
                segs.append(cur)
                cur = []
        if cur:
            segs.append(cur)
        d = " ".join("M" + " L".join(f"{px:.1f},{py:.1f}" for px, py in seg) for seg in segs if len(seg) > 1)
        dash = f' stroke-dasharray="{dashes[k % 3]}"' if dashes[k % 3] else ""
        body.append(f'<path d="{d}" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linejoin="round"'
                    f' stroke-linecap="round"{dash}/>')
    notes = []
    if len(funcs) == 1:                                     # the intercepts, found by code
        f = funcs[0][0]
        roots = _roots(f, a, b)
        d = (b - a) * 50 / pw                               # about one label's width, in x units
        for r in roots:                                     # each label goes where the curve isn't
            body.append(f'<circle cx="{X(r):.1f}" cy="{ax_y:.1f}" r="4.5" fill="currentColor"/>')
            left = f(r + d) > 0 and X(r) - 60 > L and not 0 <= X(r) - ax_x <= 60   # rises through: up-left
            body.append(_text(X(r) + (-6 if left else 6), ax_y - 8, f"({_fmt(r)}, 0)", 12.5, 600,
                              "end" if left else "start"))
        y0 = f(0.0) if a <= 0 <= b else float("nan")
        if math.isfinite(y0) and lo <= y0 <= hi and all(abs(r) > 1e-9 for r in roots):
            body.append(f'<circle cx="{X(0):.1f}" cy="{Y(y0):.1f}" r="4.5" fill="currentColor"/>')
            py = Y(y0)                                      # under a curve that climbs to the right, if it fits
            below = f(d) > y0 and (py + 20 < ax_y or py > ax_y + 22)
            body.append(_text(X(0) + 7, py + (18 if below else -8), f"(0, {_fmt(y0)})", 12.5, 600))
        if roots:
            notes.append(f"Crosses the {var}-axis at {var} = "
                         + ", ".join(_fmt(r) for r in roots[:-1]) + (" and " if len(roots) > 1 else "")
                         + _fmt(roots[-1]) + ".")
        if math.isfinite(y0):
            notes.append(f"Meets the {name}-axis at {name} = {_fmt(y0)}.")
    if len(funcs) > 1 or funcs[0][1]:                       # which line is which
        ly = T + 16
        for k, (f, label) in enumerate(funcs):
            dash = dashes[k % 3]
            body.append(_line(L + pw - 190, ly - 4, L + pw - 160, ly - 4, 2.6, 1.0, dash))
            body.append(_text(L + pw - 152, ly, label or f"y = {f.pretty()}", 13, 600))
            ly += 20
    said = [label if "=" in (label or "") else f"{name} = {f.pretty()}" for f, label in funcs]
    cap = "Drawn exactly from " + "; ".join(said) + ". " + " ".join(notes)
    return _svg(W, H, "".join(body), title), cap.strip()


def render_steps(title: str, steps: list) -> str:
    """A process in order: numbered boxes down the page, joined by arrows. steps: [(label, note)]."""
    W, bx = 560, 66
    bw = W - bx - 14
    y, boxes = 10, []
    for label, note in steps:
        lab = _wrap(label, _chars(bw - 28, 15.5, True))[:3]
        nt = _wrap(note, _chars(bw - 28, 13))[:4] if note else []
        h = 18 + 20 * len(lab) + (17 * len(nt) + 4 if nt else 0) + 8
        boxes.append((y, h, lab, nt))
        y += h + 22
    H = y - 22 + 10
    body = []
    for i, (y, h, lab, nt) in enumerate(boxes):
        cy = y + h / 2
        body.append(_box(bx, y, bw, h))
        body.append(f'<circle cx="33" cy="{cy:.1f}" r="17" fill="none" stroke="currentColor" stroke-width="2"/>')
        body.append(_text(33, cy + 6, str(i + 1), 17, 700, "middle"))
        body.append(_lines(bx + 14, y + 18 + 14, lab, 15.5, 700, lead=1.29))
        if nt:
            body.append(_lines(bx + 14, y + 18 + 20 * len(lab) + 12, nt, 13, 400, opacity=0.78, lead=1.3))
        if i < len(boxes) - 1:
            ny = boxes[i + 1][0] + boxes[i + 1][1] / 2
            body.append(_line(33, cy + 19, 33, ny - 26, 2) + _head(33, ny - 19, math.pi / 2))
    return _svg(W, H, "".join(body), title)


def render_cycle(title: str, stages: list) -> str:
    """A process that repeats: stages round a circle, clockwise from the top, arrows between them. [(label, note)]"""
    n = len(stages)
    W = H = 620 if n >= 6 else 580
    cx, cy, R = W / 2, H / 2, W / 2 - 112
    bw = 152 if n >= 7 else 166
    step = 2 * math.pi / n
    nodes = []
    for k, (label, note) in enumerate(stages):
        ang = -math.pi / 2 + step * k
        lab = _wrap(label, _chars(bw - 18, 14.5, True))[:2]
        nt = _wrap(note, _chars(bw - 18, 12))[:3] if note else []
        h = 14 + 18 * len(lab) + (15 * len(nt) + 4 if nt else 0) + 8
        x = min(max(cx + R * math.cos(ang), bw / 2 + 6), W - bw / 2 - 6)
        y = min(max(cy + R * math.sin(ang), h / 2 + 6), H - h / 2 - 6)
        # how far round the circle the box reaches: its half-width where the circle runs sideways, half-height where
        # it runs up and down, plus a little air — the arrows start and end outside the boxes
        reach = (abs(math.sin(ang)) * bw / 2 + abs(math.cos(ang)) * h / 2 + 10) / R
        nodes.append((ang, x, y, h, lab, nt, min(reach, 0.45 * step)))
    body = []
    for k, (ang, x, y, h, lab, nt, reach) in enumerate(nodes):
        nxt = nodes[(k + 1) % n]
        a0, a1 = ang + reach, ang + step - nxt[6]
        if a1 - a0 < 0.05:
            continue
        p0 = (cx + R * math.cos(a0), cy + R * math.sin(a0))
        p1 = (cx + R * math.cos(a1), cy + R * math.sin(a1))
        body.append(f'<path d="M{p0[0]:.1f},{p0[1]:.1f} A{R:.1f},{R:.1f} 0 0 1 {p1[0]:.1f},{p1[1]:.1f}" fill="none" '
                    f'stroke="currentColor" stroke-width="2.2" stroke-opacity="0.75"/>')
        body.append(_head(p1[0], p1[1], a1 + math.pi / 2, 10))
    for ang, x, y, h, lab, nt, _r in nodes:
        body.append(_box(x - bw / 2, y - h / 2, bw, h, 12, 0.1, 0.5))
        top = y - h / 2 + 14 + 13
        body.append(_lines(x, top, lab, 14.5, 700, "middle", lead=1.24))
        if nt:
            body.append(_lines(x, top + 18 * len(lab) + 4, nt, 12, 400, "middle", 0.78, lead=1.25))
    t = _wrap(title, 16)[:3]
    body.append(_lines(cx, cy - (len(t) - 1) * 11 + 6, t, 17, 700, "middle", 0.9))
    return _svg(W, H, "".join(body), title)


def render_mindmap(title: str, center: str, branches: list) -> str:
    """A topic on top and its parts in two columns below it, each joined to the topic. [(label, [points])]"""
    W, gap = 580, 14
    cw = (W - 3 * gap) / 2
    cards = []
    for label, points in branches:
        lab = _wrap(label, _chars(cw - 24, 16, True))[:2]
        pts = []
        for pt in points:
            w = _wrap(pt, _chars(cw - 36, 13.5))
            pts += ["• " + w[0]] + ["   " + more for more in w[1:2]]
        cards.append((lab, pts, 14 + 20 * len(lab) + (18 * len(pts) + 4 if pts else 0) + 10))
    clab = _wrap(center, _chars(W * 0.6, 18, True))[:2]
    chw, chh = min(W * 0.62, 40 + max(len(x) for x in clab) * 18 * 0.62), 26 + 23 * len(clab)
    top0 = 12 + chh + 40                                    # where the parts begin
    rows, y = [], top0
    for i in range(0, len(cards), 2):
        pair = cards[i:i + 2]
        rh = max(c[2] for c in pair)
        rows.append((y, pair, rh))
        y += rh + gap
    H = y - gap + 10
    ccx = W / 2
    body = [_box(ccx - chw / 2, 12, chw, chh, 14, 0.16, 0.85),
            _lines(ccx, 12 + 22 + 6, clab, 18, 800, "middle", lead=1.28)]
    bus = 12 + chh + 20                                     # the line the branches hang from
    xs = [gap + cw / 2, 2 * gap + cw * 1.5]
    body.append(_line(ccx, 12 + chh, ccx, bus, 2, 0.7))
    body.append(_line(xs[0], bus, xs[1] if len(cards) > 1 else xs[0], bus, 2, 0.7))
    for ri, (y, pair, rh) in enumerate(rows):
        for k, (lab, pts, h) in enumerate(pair):
            x = gap + k * (cw + gap)
            if ri == 0:
                body.append(_line(xs[k], bus, xs[k], y, 2, 0.7))
            body.append(_box(x, y, cw, h))
            body.append(_lines(x + 12, y + 14 + 14, lab, 16, 700, lead=1.25))
            if pts:
                body.append(_lines(x + 12, y + 14 + 20 * len(lab) + 12, pts, 13.5, 400, opacity=0.82, lead=1.3))
    for k in range(2):                                      # each later card hangs from the card above it
        col = [(y, pair[k][2]) for y, pair, rh in rows if len(pair) > k]
        for (y0, h0), (y1, _h1) in zip(col, col[1:]):
            body.append(_line(xs[k], y0 + h0, xs[k], y1, 2, 0.7))
    return _svg(W, H, "".join(body), title)


def render_timeline(title: str, events: list) -> str:
    """Events in order down a line: the date on the left, what happened on the right. [(when, label)]"""
    W, lx = 580, 150
    tw = W - lx - 30
    y, rows = 14, []
    for when, label in events:
        wl = _wrap(when, _chars(lx - 30, 15, True))[:2]
        ll = _wrap(label, _chars(tw, 15))[:4]
        h = max(len(wl), len(ll)) * 20 + 16
        rows.append((y, wl, ll))
        y += h
    H = y + 6
    body = [_line(lx, rows[0][0] + 6, lx, rows[-1][0] + 6, 2.2, 0.7)]
    for y, wl, ll in rows:
        body.append(f'<circle cx="{lx}" cy="{y + 6:.1f}" r="6.5" fill="currentColor"/>')
        body.append(_lines(lx - 16, y + 11, wl, 15, 700, "end", lead=1.3))
        body.append(_lines(lx + 18, y + 11, ll, 15, 400, lead=1.3))
    return _svg(W, H, "".join(body), title)


def render_bars(title: str, bars: list, unit: str) -> str:
    """Numbers to compare: one bar each, drawn to scale, the value at its end. [(label, value)]"""
    W, lw = 600, 168
    x0, bmax = lw + 10, W - lw - 10 - 86
    vals = [v for _, v in bars]
    vmin, vmax = min(0.0, min(vals)), max(0.0, max(vals))
    span = (vmax - vmin) or 1.0
    zx = x0 + (0 - vmin) / span * bmax
    body, y = [], 14
    for label, v in bars:
        ll = _wrap(label, _chars(lw - 6, 15))[:2]
        h = max(32, len(ll) * 19 + 12)
        vx = x0 + (v - vmin) / span * bmax
        bx, bwid = min(zx, vx), max(abs(vx - zx), 1.5)
        body.append(f'<rect x="{bx:.1f}" y="{y + h / 2 - 9:.1f}" width="{bwid:.1f}" height="18" rx="3" '
                    f'fill="currentColor" fill-opacity="0.8"/>')
        body.append(_lines(lw, y + h / 2 + 5 - (len(ll) - 1) * 9.5, ll, 15, 600, "end", lead=1.26))
        tx = max(vx, zx) + 8 if v >= 0 else min(vx, zx) - 8
        body.append(_text(tx, y + h / 2 + 5, _fmt(v) + (f" {unit}" if unit else ""), 14.5, 700,
                          "start" if v >= 0 else "end"))
        y += h + 8
    H = y + 4
    body.insert(0, _line(zx, 8, zx, H - 4, 1.6, 0.6))
    return _svg(W, H, "".join(body), title)


def _symbol(kind: str) -> str:
    """A circuit part drawn across the origin, horizontal, its leads ending at x = ±24."""
    s = lambda a, b: _line(a, 0, b, 0, 2.2)
    if kind == "resistor":
        return s(-24, -20) + s(20, 24) + ('<rect x="-20" y="-8" width="40" height="16" fill="none" '
                                           'stroke="currentColor" stroke-width="2.2"/>')
    if kind == "lamp":
        return (s(-24, -12) + s(12, 24) + '<circle r="12" fill="none" stroke="currentColor" stroke-width="2.2"/>'
                + _line(-8.5, -8.5, 8.5, 8.5, 2) + _line(-8.5, 8.5, 8.5, -8.5, 2))
    if kind in ("ammeter", "voltmeter", "motor"):
        letter = {"ammeter": "A", "voltmeter": "V", "motor": "M"}[kind]
        return (s(-24, -13) + s(13, 24) + '<circle r="13" fill="none" stroke="currentColor" stroke-width="2.2"/>'
                + _text(0, 5.5, letter, 15, 700, "middle"))
    if kind == "switch":
        return (s(-24, -14) + s(14, 24) + '<circle cx="-14" r="2.8" fill="currentColor"/>'
                + '<circle cx="14" r="2.8" fill="currentColor"/>' + _line(-14, 0, 11, -12, 2.2))
    if kind == "capacitor":
        return s(-24, -4) + s(4, 24) + _line(-4, -12, -4, 12, 2.4) + _line(4, -12, 4, 12, 2.4)
    return s(-24, 24)


def _cell(x: float, y: float, battery: bool) -> str:
    """A cell (or two, for a battery) on a vertical wire at x, centred on y: long plate +, short plate −."""
    out, offs = "", ([-10, 10] if battery else [0])
    for o in offs:
        out += _line(x - 15, y + o - 5, x + 15, y + o - 5, 2.4) + _line(x - 8, y + o + 5, x + 8, y + o + 5, 4)
    if battery:
        out += _line(x, y - 10 + 5, x, y + 10 - 5, 1.6, 0.8, "3 3")
    return out


def _voltmeter_across(x: float, y: float, out: int) -> str:
    """A voltmeter bridged across the part at (x, y): leads from both of its ends, the meter `out` (-1 up, +1 down)."""
    vy = y + 50 * out
    return (_line(x - 34, y, x - 34, vy) + _line(x - 34, vy, x - 13, vy) + _line(x + 13, vy, x + 34, vy)
            + _line(x + 34, vy, x + 34, y) + f'<circle cx="{x - 34:.1f}" cy="{y:.1f}" r="3.2" fill="currentColor"/>'
            + f'<circle cx="{x + 34:.1f}" cy="{y:.1f}" r="3.2" fill="currentColor"/>'
            + f'<g transform="translate({x:.1f},{vy:.1f})"><circle r="13" fill="none" stroke="currentColor" '
              f'stroke-width="2.2"/>{_text(0, 5.5, "V", 15, 700, "middle")}</g>')


def _wire_with(x0: float, x1: float, y: float, items: list) -> tuple:
    """A horizontal wire from x0 to x1 with each (kind, label) part spaced along it: (svg, the parts' x)."""
    xs = [x0 + (x1 - x0) * (i + 1) / (len(items) + 1) for i in range(len(items))]
    edges = [x0] + [v for x in xs for v in (x - 24, x + 24)] + [x1]
    out = "".join(_line(edges[i], y, edges[i + 1], y) for i in range(0, len(edges), 2))
    for x, (kind, _label) in zip(xs, items):
        out += f'<g transform="translate({x:.1f},{y:.1f})">{_symbol(kind)}</g>'
    return out, xs


def render_circuit(title: str, layout: str, supply: str, supply_label: str, parts: list,
                   across: int = -1, main_ammeter: bool = False) -> str:
    """A series loop (the parts along its top wire, then its bottom wire) or parallel branches between two rails,
    the cell or battery on the left. parts: [(kind, label)]; across: the part a voltmeter is bridged across."""
    battery = supply == "battery"
    if layout == "parallel":
        left, top, bottom = 90, 60, 250
        bx = [left + 160 + i * 120 for i in range(len(parts))]
        W, H, right, mid = bx[-1] + 90, 310, bx[-1], (60 + 250) / 2
        body = [_line(left, bottom, right, bottom), _line(left, top, left, mid - 22), _line(left, mid + 22, left, bottom),
                _cell(left, mid, battery)]
        if main_ammeter:                                    # an ammeter in the main wire, before the branches
            wire, _xs = _wire_with(left, bx[0], top, [("ammeter", "")])
            body += [wire, _line(bx[0], top, right, top)]
        else:
            body.append(_line(left, top, right, top))
        if supply_label:
            body.append(_text(left - 24, mid + 5, supply_label, 14, 700, "end"))
        for x, (kind, label) in zip(bx, parts):
            body.append(_line(x, top, x, mid - 24) + _line(x, mid + 24, x, bottom))
            body.append(f'<g transform="translate({x:.1f},{mid:.1f}) rotate(90)">{_symbol(kind)}</g>')
            if label:
                body.append(_text(x + 20, mid + 5, label, 13.5, 600))
            body.append(f'<circle cx="{x}" cy="{top}" r="3.2" fill="currentColor"/>'
                        f'<circle cx="{x}" cy="{bottom}" r="3.2" fill="currentColor"/>')
        return _svg(W, H, "".join(body), title)
    ntop = (len(parts) + 1) // 2
    top_parts, bot_parts = parts[:ntop], list(reversed(parts[ntop:]))   # round the loop: along the top, back below
    W = max(460, 170 + 130 * max(len(top_parts), len(bot_parts), 1))
    up, down = 0 <= across < ntop, ntop <= across < len(parts)
    top = 110 if up else 60
    bottom = top + 170
    H = bottom + (110 if down else 60)
    left, right, mid = 90, W - 50, (top + bottom) / 2
    body = [_line(left, top, left, mid - 22), _line(left, mid + 22, left, bottom), _cell(left, mid, battery),
            _line(right, top, right, bottom)]
    if supply_label:
        body.append(_text(left - 24, mid + 5, supply_label, 14, 700, "end"))
    wire, xs = _wire_with(left, right, top, top_parts)
    body.append(wire)
    for i, (x, (_kind, label)) in enumerate(zip(xs, top_parts)):
        if label:
            body.append(_text(x, top + 32 if across == i else top - 20, label, 13.5, 600, "middle"))
        if across == i:
            body.append(_voltmeter_across(x, top, -1))
    wire, xs = _wire_with(left, right, bottom, bot_parts)
    body.append(wire)
    for j, (x, (_kind, label)) in enumerate(zip(xs, bot_parts)):
        if label:
            body.append(_text(x, bottom + 32, label, 13.5, 600, "middle"))
        if across == len(parts) - 1 - j:
            body.append(_voltmeter_across(x, bottom, 1))
    return _svg(W, H, "".join(body), title)


# ══ a graph straight from the student's equation: no brain at all ════════════════════════════════════════════════════
_EQUATION = re.compile(
    r"(?:^|[\s(:])(?P<lhs>[A-Za-z](?:\s*\(\s*[A-Za-z]\s*\))?)\s*=\s*(?P<rhs>[^=,;]+?)"
    r"(?:\s*[,;]?\s*(?:from|for|between)\s+(?:[A-Za-z]\s*=\s*)?(?P<a>[-−]?\d+(?:\.\d+)?)\s*(?:to|until|and|\.\.|–|-)\s*"
    r"(?P<b>[-−]?\d+(?:\.\d+)?))?\s*[.?!]?\s*$", re.I)


def direct_graph(request: str):
    """{kind, title, svg, caption} when the request is an equation MrSOLIS can draw by itself ("y = x^2 - 4 from -3
    to 3", "plot v = 2 + 3t for t = 0 to 10"), else None — then the brain plans the drawing."""
    m = _EQUATION.search(request or "")
    if not m:
        return None
    lhs, rhs = m.group("lhs").replace(" ", ""), m.group("rhs")
    letters = free_letters(rhs)
    var = re.search(r"\((\w)\)", lhs).group(1) if "(" in lhs else (letters[0] if len(letters) == 1 else "x")
    if len(letters) > 1 or (letters and letters[0] != var):
        return None
    try:
        f = Function(rhs, var)
    except DrawError:
        return None
    a = float(m.group("a").replace("−", "-")) if m.group("a") else (0.0 if var == "t" else -5.0)   # time starts at 0
    b = float(m.group("b").replace("−", "-")) if m.group("b") else (10.0 if var == "t" else 5.0)
    if not b > a:
        a, b = -5.0, 5.0
    name = lhs[0] if "(" not in lhs else lhs
    title = f"{name} = {f.pretty()}"
    svg, cap = render_graph([(f, "")], a, b, var, name, title, name, var)
    return {"kind": "graph", "title": title, "svg": svg, "caption": cap}


# ══ the brain plans the rest ══════════════════════════════════════════════════════════════════════════════════════════
_SYSTEM = ("You plan one study diagram for MrSOLIS, a study tutor app; the app draws it exactly from what you fill in. "
           "When a slide is given and covers the topic, use only its facts; otherwise use standard textbook facts. "
           "Keep labels short and in plain words: no markdown, no LaTeX, no emojis. Write numbers and units as the "
           "slide does.")

_KIND_INFO = (
    "graph: a maths function or physics relation drawn as a curve (y = x^2, velocity against time)\n"
    "steps: a process in order (how a bill becomes law, the stages of mitosis, how to solve a problem)\n"
    "cycle: a process that repeats (the water cycle, the cell cycle, the carbon cycle)\n"
    "mindmap: one topic and its main parts, types or ideas (types of rock, parts of a computer)\n"
    "bars: numbers to compare (marks per subject, populations) — only numbers given by the slide or the student\n"
    "timeline: events in date order\n"
    "circuit: an electric circuit with a cell or battery and its parts")

_TITLE = {"type": "string", "maxLength": 60}
_STR = lambda n: {"type": "string", "maxLength": n}
_SCHEMAS = {
    "kind": {"type": "object", "properties": {"kind": {"type": "string", "enum": list(KINDS)}}, "required": ["kind"]},
    "graph": {"type": "object", "properties": {
        "title": _TITLE,
        "functions": {"type": "array", "minItems": 1, "maxItems": 3, "items": {"type": "object", "properties": {
            "expr": _STR(60), "label": _STR(30)}, "required": ["expr", "label"]}},
        "x_from": {"type": "number"}, "x_to": {"type": "number"},
        "x_label": _STR(24), "y_label": _STR(24)},
        "required": ["title", "functions", "x_from", "x_to", "x_label", "y_label"]},
    "steps": {"type": "object", "properties": {
        "title": _TITLE,
        "steps": {"type": "array", "minItems": 2, "maxItems": 8, "items": {"type": "object", "properties": {
            "label": _STR(48), "note": _STR(90)}, "required": ["label", "note"]}}},
        "required": ["title", "steps"]},
    "cycle": {"type": "object", "properties": {
        "title": _TITLE,
        "stages": {"type": "array", "minItems": 3, "maxItems": 8, "items": {"type": "object", "properties": {
            "label": _STR(32), "note": _STR(60)}, "required": ["label", "note"]}}},
        "required": ["title", "stages"]},
    "mindmap": {"type": "object", "properties": {
        "title": _TITLE, "center": _STR(32),
        "branches": {"type": "array", "minItems": 2, "maxItems": 7, "items": {"type": "object", "properties": {
            "label": _STR(32), "points": {"type": "array", "minItems": 0, "maxItems": 3, "items": _STR(44)}},
            "required": ["label", "points"]}}},
        "required": ["title", "center", "branches"]},
    "bars": {"type": "object", "properties": {
        "title": _TITLE, "unit": _STR(16),
        "bars": {"type": "array", "minItems": 2, "maxItems": 10, "items": {"type": "object", "properties": {
            "label": _STR(24), "value": {"type": "number"}}, "required": ["label", "value"]}}},
        "required": ["title", "unit", "bars"]},
    "timeline": {"type": "object", "properties": {
        "title": _TITLE,
        "events": {"type": "array", "minItems": 2, "maxItems": 10, "items": {"type": "object", "properties": {
            "when": _STR(20), "label": _STR(60)}, "required": ["when", "label"]}}},
        "required": ["title", "events"]},
    "circuit": {"type": "object", "properties": {
        "title": _TITLE,
        "layout": {"type": "string", "enum": ["series", "parallel"]},
        "supply": {"type": "string", "enum": ["cell", "battery"]}, "supply_label": _STR(12),
        "parts": {"type": "array", "minItems": 1, "maxItems": 5, "items": {"type": "object", "properties": {
            "type": {"type": "string", "enum": list(PARTS)}, "label": _STR(12)}, "required": ["type", "label"]}},
        "voltmeter_across": {"type": "integer"}, "main_ammeter": {"type": "boolean"}},
        "required": ["title", "layout", "supply", "supply_label", "parts", "voltmeter_across", "main_ammeter"]},
}
_FILL = {
    "graph": "Fill in a graph. Write each function in plain maths with x as the variable (2*x^2 - 3, sin(x), 1/x); "
             "for a physics relation put in the slide's numbers and use x for the quantity across (for v = u + a*t "
             "with u = 2 and a = 3 write 2 + 3*x, x_label \"t (s)\", y_label \"v (m/s)\"). Choose x_from and x_to so "
             "the important part shows. Draw one function unless the student asked to compare several.",
    "steps": "Fill in the steps in order, 3 to 7 of them: a short label each and a one-line note.",
    "cycle": "Fill in the stages of the cycle in order, 3 to 7 of them, starting anywhere sensible: a short label "
             "each and a short note.",
    "mindmap": "Fill in the topic in the centre and its main branches, 3 to 6 of them, each with up to 3 short points.",
    "bars": "Fill in the bars: a short label and the number for each, and the unit. Use only numbers the slide or the "
            "student gave.",
    "timeline": "Fill in the events in date order, 3 to 8 of them: when, and what happened.",
    "circuit": "Fill in the circuit: series or parallel; a cell or a battery and its label (like \"12 V\"); the parts "
               "in order with short labels (like \"4 Ω\"), only the parts the slide or the student gives — an "
               "ammeter shows as A, a voltmeter as V; voltmeter_across = the number of the part a voltmeter is "
               "connected across, counting from 0, or -1 for none (series circuits); main_ammeter = true if an "
               "ammeter is in the main wire of a parallel circuit.",
}
_HINTS = (("circuit", r"\bcircuits?\b"), ("cycle", r"\bcycles?\b"), ("timeline", r"\btime ?line\b|\bhistory of\b"),
          ("mindmap", r"\bmind ?map\b|\bconcept map\b|\btypes of\b|\bkinds of\b|\bparts of\b"),
          ("bars", r"\bbar (?:chart|graph)\b"), ("steps", r"\bsteps?\b|\bstages of\b|\bprocess\b|\bflow ?chart\b"),
          ("graph", r"\bgraph\b|\bplot\b|\bcurve\b|\bagainst\b"))


def hint(request: str):
    """The kind the student named ("the water cycle" -> cycle), or None."""
    r = (request or "").lower()
    return next((k for k, pat in _HINTS if re.search(pat, r)), None)


async def _ask(request: str, slide: str, slide_no: int, total: int, task: str, schema: dict, room: int) -> dict:
    ctx = (f"Slide {slide_no} of {total}:\n\"\"\"\n{classroom._slide(slide)}\n\"\"\"\n\n" if slide.strip() else "")
    messages = [{"role": "system", "content": _SYSTEM},
                {"role": "user", "content": f"{ctx}The student asked for a diagram: \"{request.strip()[:300]}\"\n\n{task}"}]
    raw = await brain.chat(messages, temperature=0.2, max_tokens=room, schema=schema)
    try:
        data = json.loads(raw)
    except Exception:
        raise DrawError("MrSOLIS couldn't plan that drawing. Try asking for it in other words.")
    if not isinstance(data, dict):
        raise DrawError("MrSOLIS couldn't plan that drawing. Try asking for it in other words.")
    return data


def _caption(slide: str) -> str:
    return ("Drawn from your slide by MrSOLIS: the layout is exact, but check the words and numbers against the slide."
            if slide.strip() else
            "Drawn by MrSOLIS: the layout is exact, but check the words and numbers against your notes.")


async def make(request: str, slide: str = "", slide_no: int = 0, total: int = 0) -> dict:
    """{kind, title, svg, caption} for the student's request (raises DrawError, local_llm.LocalLLMError)."""
    direct = direct_graph(request)
    if direct:
        return direct
    kind = hint(request)
    if not kind:
        got = await _ask(request, slide, slide_no, total, "Which kind of diagram fits best?\n" + _KIND_INFO,
                         _SCHEMAS["kind"], 40)
        kind = got.get("kind") if got.get("kind") in KINDS else "mindmap"
    d = await _ask(request, slide, slide_no, total, _FILL[kind], _SCHEMAS[kind], 700)
    return render(kind, d, slide)


def render(kind: str, d: dict, slide: str = "") -> dict:
    """The brain's filled-in plan -> {kind, title, svg, caption}; anything missing or unreadable -> DrawError."""
    title = _clean(d.get("title"), 60) or "Diagram"
    cap = _caption(slide)
    if kind == "graph":
        funcs = []
        for item in (d.get("functions") or [])[:3]:
            try:
                funcs.append((Function(str(item.get("expr", "")), "x"), _clean(item.get("label"), 30)))
            except (DrawError, AttributeError):
                continue
        if not funcs:
            raise DrawError("MrSOLIS couldn't write that as a function to draw. Try typing the equation, "
                            "like /draw y = x^2 - 4 from -3 to 3.")
        a, b = d.get("x_from"), d.get("x_to")
        a, b = (float(a), float(b)) if isinstance(a, (int, float)) and isinstance(b, (int, float)) and b > a \
            else (-5.0, 5.0)
        svg, gcap = render_graph(funcs, a, b, _clean(d.get("x_label"), 24) or "x", _clean(d.get("y_label"), 24) or "y",
                                 title)
        return {"kind": kind, "title": title, "svg": svg, "caption": gcap}
    if kind in ("steps", "cycle"):
        items = [(_clean(s.get("label"), 48), _clean(s.get("note"), 90)) for s in (d.get(kind if kind == "steps" else
                 "stages") or []) if isinstance(s, dict) and _clean(s.get("label"), 48)][:8]
        if len(items) < (2 if kind == "steps" else 3):
            raise DrawError("MrSOLIS didn't find enough stages to draw.")
        svg = render_steps(title, items) if kind == "steps" else render_cycle(title, items)
    elif kind == "mindmap":
        branches = [(_clean(b.get("label"), 32), [_clean(p, 44) for p in (b.get("points") or [])[:3] if _clean(p, 44)])
                    for b in (d.get("branches") or []) if isinstance(b, dict) and _clean(b.get("label"), 32)][:7]
        if len(branches) < 2:
            raise DrawError("MrSOLIS didn't find enough parts to draw.")
        svg = render_mindmap(title, _clean(d.get("center"), 32) or title, branches)
    elif kind == "bars":
        bars = [(_clean(b.get("label"), 24), float(b["value"])) for b in (d.get("bars") or [])
                if isinstance(b, dict) and isinstance(b.get("value"), (int, float)) and math.isfinite(b["value"])
                and _clean(b.get("label"), 24)][:10]
        if len(bars) < 2:
            raise DrawError("There were no numbers to compare. A bar chart needs numbers from your slide or your "
                            "question.")
        svg = render_bars(title, bars, _clean(d.get("unit"), 16))
    elif kind == "timeline":
        events = [(_clean(e.get("when"), 20), _clean(e.get("label"), 60)) for e in (d.get("events") or [])
                  if isinstance(e, dict) and _clean(e.get("label"), 60)][:10]
        if len(events) < 2:
            raise DrawError("MrSOLIS didn't find enough events to draw.")
        svg = render_timeline(title, events)
    elif kind == "circuit":
        parts = [(p.get("type"), _clean(p.get("label"), 12)) for p in (d.get("parts") or [])
                 if isinstance(p, dict) and p.get("type") in PARTS][:5]
        if not parts:
            raise DrawError("MrSOLIS couldn't work out the circuit's parts.")
        layout = "parallel" if d.get("layout") == "parallel" else "series"
        across = d.get("voltmeter_across")
        across = across if isinstance(across, int) and 0 <= across < len(parts) and layout == "series" \
            and parts[across][0] != "voltmeter" else -1
        svg = render_circuit(title, layout, "battery" if d.get("supply") == "battery" else "cell",
                             _clean(d.get("supply_label"), 12), parts, across, bool(d.get("main_ammeter")))
    else:
        raise DrawError("MrSOLIS can't draw that kind of diagram yet.")
    return {"kind": kind, "title": title, "svg": svg, "caption": cap}
