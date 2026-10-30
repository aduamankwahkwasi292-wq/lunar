"""
CUSTOM-SQE trigonometry:
  - right-angled triangles (SOH CAH TOA, ladders, heights);
  - the angle from a ratio;
  - the sine rule, the cosine rule, and the area ½ab sin C;
  - degrees and radians;
  - trigonometric equations in a range;
  - exact values (sin 60 + cos 30).

Angles in versions stay sensible (strictly between 0° and 90° in a right triangle, and a triangle's angles add to
less than 180°). Equations keep the standard values that give exact angles. Lengths are given to 3 significant
figures and angles to 1 decimal place, as exams ask.
"""
from __future__ import annotations

import math
import random
import re
from fractions import Fraction
from typing import List, Optional

import sympy as sp

from .core import Family, Item, Spec, numeric_wrong, similar_int
from .text import Question, exact, fmt_expr, fmt_num, fmt_sig

DEG = sp.pi / 180
_EXACT_ANGLES = [30, 45, 60]


def deg(v) -> str:
    """An angle in degrees, 1 decimal place unless whole."""
    f = float(v)
    return f"{int(round(f))}°" if abs(f - round(f)) < 1e-9 else f"{f:.1f}°"


def length(v, unit: str) -> str:
    v = exact(v)
    if v.is_Rational and (v.q == 1 or len(f"{float(v):.10g}") <= 5):
        txt = f"{float(v):.10g}"
    else:
        txt = fmt_sig(float(v), 3)
    return f"{txt} {unit}".strip()


def unit_after(q: Question, i: int) -> str:
    m = re.match(r"\s?(cm|mm|km|m)\b", q.display[q.slots[i].end:q.slots[i].end + 4])
    return m.group(1) if m else ""


def is_angle(q: Question, i: int) -> bool:
    after = q.display[q.slots[i].end:q.slots[i].end + 10].lower()
    return bool(re.match(r"\s?(?:°|degrees?|deg\b|º)", after))


def trig_roots(e, x, lo: float, hi: float):
    """Angles (degrees) in [lo, hi] solving e = 0, where e is a polynomial in one of sin x, cos x, tan x — the
    textbook way (u = cos x, solve for u, then every angle with that value), fast and exact for standard values."""
    fns = {type(g) for g in sp.preorder_traversal(e) if isinstance(g, (sp.sin, sp.cos, sp.tan)) and g.args[0] == x}
    if len(fns) != 1 or any(isinstance(g, (sp.sin, sp.cos, sp.tan)) and g.args[0] != x for g in sp.preorder_traversal(e)):
        return None
    f = fns.pop()
    u = sp.Symbol("u")
    P = e.subs(f(x), u)
    if P.has(x):
        return None
    try:
        roots = [r for r in sp.Poly(sp.expand(P), u).all_roots() if r.is_real] if sp.expand(P).is_polynomial(u) else sp.solve(P, u)
    except Exception:                                                        # noqa: BLE001
        return None
    out = set()
    for r in roots:
        v = float(r)
        if f in (sp.sin, sp.cos) and not -1 <= v <= 1:
            continue
        if f is sp.sin:
            base = math.degrees(math.asin(v))
            cands = [base, 180 - base]
            period = 360
        elif f is sp.cos:
            base = math.degrees(math.acos(v))
            cands = [base, 360 - base]
            period = 360
        else:
            base = math.degrees(math.atan(v))
            cands = [base]
            period = 180
        for c in cands:
            for k in range(-2, 4):
                a = c + k * period
                if lo - 1e-9 <= a <= hi + 1e-9:
                    out.add(round(a, 6) + 0.0)
    return sorted(out) if 0 < len(out) <= 8 else None


class Trig(Family):
    name = "trigonometry"
    kind = "trigonometry"

    def parse(self, q: Question) -> Optional[Spec]:
        low, d = q.low, q.display.lower()
        angles, links = [], {}
        for s in q.slots:                                   # "an angle of 40° … the 40° angle": one angle, said twice
            if is_angle(q, s.i):
                first = next((a for a in angles if q.vals[a] == s.value), None)
                if first is not None and re.search(r"\bthe\s*$", q.display[:s.start].lower()):
                    links[s.i] = first
                else:
                    angles.append(s.i)
        self._links = links
        lengths = [s.i for s in q.slots if unit_after(q, s.i)]
        # degrees <-> radians
        m = re.search(r"\bconvert\b|\bexpress\b|\bin\s+radians\b|\bto\s+radians\b|\bto\s+degrees\b", low)
        if m and re.search(r"radian", low):
            if re.search(r"to\s+radians|in\s+radians", low) and angles:
                return Spec(task="d2r", ids=angles[:1])
            if re.search(r"to\s+degrees|in\s+degrees", low):
                nums = [s.i for s in q.slots if s.role in ("num", "coef")]
                pim = re.search(r"(\(S\d+\))\s*pi\s*/\s*(\(S\d+\))|(\(S\d+\))?\s*pi\s*/\s*(\(S\d+\))", q.sym)
                if pim:
                    a = pim.group(1) or pim.group(3)
                    b = pim.group(2) or pim.group(4)
                    return Spec(task="pi2d", ids=[int(a[2:-1]) if a else None, int(b[2:-1])])
                if nums:
                    return Spec(task="r2d", ids=nums[:1])
        # trig equations in a range
        if re.search(r"\bsolve\b", low) and re.search(r"\b(?:sin|cos|tan)\b", low) and re.search(r"(?:<=|≤|<|between|for\s+0)", q.display + q.sym):
            rng_m = re.search(r"(\(S\d+\))\s*(?:°|deg)?\s*(?:<=|≤|<)\s*[a-zθ]\s*(?:<=|≤|<)\s*(\(S\d+\))", q.sym)
            body = re.split(r"\bfor\b|,", q.sym, maxsplit=1)[0]
            body = re.sub(r"^.*?\bsolve\b\s*", "", body, flags=re.I)
            from .text import to_expr, split_relation
            rel = split_relation(body)
            if not rel or not rng_m:
                return None
            L, R = to_expr(rel[0]), to_expr(rel[2])
            if L is None or R is None:
                return None
            return Spec(task="equation", e=L - R, lo=int(rng_m.group(1)[2:-1]), hi=int(rng_m.group(2)[2:-1]), inside=q.slot_symbols(L - R))
        # exact values: sin 60 + cos 30
        if re.search(r"exact\s+value|without\s+(?:using\s+)?(?:a\s+)?(?:calculator|tables)", low) and re.search(r"\b(?:sin|cos|tan)\b", low):
            body = re.sub(r"^.*?\b(?:of|evaluate|find)\b\s*", "", q.sym.split("exact value")[-1], flags=re.I)
            body = re.sub(r"\b(sin|cos|tan)\s*\(?\s*(\(S\d+\))\s*\)?\s*(?:deg)?", r"\1(\2*pi/180)", body)
            from .text import to_expr
            e = to_expr(body)
            if e is None:
                return None
            return Spec(task="exact", e=e, ids=q.slot_symbols(e))
        # angle from a ratio
        m = re.search(r"angle\s+whose\s+(sine|cosine|tangent)\s+is\s+(\(S\d+\))", q.sym, re.I)
        if m:
            return Spec(task="inverse", fn=m.group(1).lower(), ids=[int(m.group(2)[2:-1])])
        # triangles: area ½ab sin C, cosine rule, sine rule
        if re.search(r"\barea\b", low) and len(angles) == 1 and len(lengths) == 2 and re.search(r"triangle|included", low):
            return Spec(task="area", a=lengths[0], b=lengths[1], C=angles[0], unit=unit_after(q, lengths[0]))
        tri = re.search(r"\btriangle\b", low)
        if tri and len(angles) == 1 and len(lengths) == 2 and not re.search(r"right[\s-]*angled", low):
            return Spec(task="cosine", a=lengths[0], b=lengths[1], C=angles[0], unit=unit_after(q, lengths[0]))
        if tri and len(angles) == 2 and len(lengths) == 1 and not re.search(r"right[\s-]*angled", low):
            return Spec(task="sine", A=angles[0], B=angles[1], a=lengths[0], unit=unit_after(q, lengths[0]))
        # right-angled triangles / ladders
        if len(angles) == 1 and len(lengths) == 1 and re.search(r"right[\s-]*angled|ladder|hypotenuse|opposite|adjacent|leans|elevation|depression|"
                                                                    r"how\s+(?:high|far|tall)|\bheight\b|\bfoot\b|\bshadow\b", low):
            given = ("hyp" if re.search(r"hypotenuse|ladder|long\b|string|rope|wire", d) and not re.search(r"hypotenuse\.?\s*$", d) else
                     "adj" if re.search(r"adjacent|from\s+the\s+(?:foot|base)|away\s+from", d) else "opp")
            want = ("opp" if re.search(r"opposite|how\s+high|height|up\s+the\s+wall|how\s+tall", d.split(".")[-1] + d[-60:]) else
                    "adj" if re.search(r"adjacent|foot|how\s+far|distance|from\s+the\s+wall|base", d[-70:]) else
                    "hyp" if re.search(r"hypotenuse|length\s+of\s+the\s+ladder|how\s+long", d[-60:]) else None)
            angle_with_ground = not re.search(r"with\s+the\s+wall|with\s+the\s+vertical", d)
            if want is None or want == given:
                return None
            return Spec(task="right", L=lengths[0], A=angles[0], given=given, want=want, ground=angle_with_ground, unit=unit_after(q, lengths[0]),
                        links=dict(links))
        return None

    def solve(self, q, spec, vals, full=True):
        V = [Fraction(v) for v in vals]
        R = lambda i: sp.Rational(V[i].numerator, V[i].denominator)
        text = q.render(vals)
        t = spec.task
        if t == "d2r":
            a = R(spec.ids[0])
            r = sp.nsimplify(a / 180) * sp.pi
            ans = fmt_expr(r) + " rad"
            ans = ans.replace("pi", "π")
            if not full:
                return Item(text, ans, [], [], self.kind, value=a)
            steps = [f"Radians = degrees × π/180 = {fmt_num(a)} × π/180 = {ans}"]
            wrong = [fmt_expr(sp.nsimplify(180 / a) * sp.pi).replace("pi", "π") + " rad", fmt_expr(sp.nsimplify(a / 90) * sp.pi).replace("pi", "π") + " rad",
                     fmt_expr(sp.nsimplify(a / 360) * sp.pi).replace("pi", "π") + " rad", f"{float(a * 180 / sp.pi):.1f} rad"]
            return Item(text, ans, steps, [w for w in dict.fromkeys(wrong) if w != ans], self.kind, value=a)
        if t == "r2d":
            r = R(spec.ids[0])
            dval = r * 180 / sp.pi
            ans = deg(dval)
            if not full:
                return Item(text, ans, [], [], self.kind, value=None)
            steps = [f"Degrees = radians × 180/π = {fmt_num(r)} × 180/π = {ans}"]
            return Item(text, ans, steps, [w for w in dict.fromkeys([deg(r * sp.pi / 180), deg(r * 180), deg(dval / 2), deg(dval * 2)]) if w != ans], self.kind)
        if t == "pi2d":
            a = R(spec.ids[0]) if spec.ids[0] is not None else sp.Integer(1)
            b = R(spec.ids[1])
            dval = a * 180 / b
            ans = deg(dval)
            if not full:
                return Item(text, ans, [], [], self.kind, value=dval)
            steps = [f"π rad = 180°, so {fmt_num(a) if a != 1 else ''}π/{fmt_num(b)} = {fmt_num(a)} × 180/{fmt_num(b)} = {ans}"]
            return Item(text, ans, steps, [w for w in dict.fromkeys([deg(b * 180 / a), deg(dval / 2), deg(dval + 90), deg(a * 90 / b)]) if w != ans], self.kind, value=dval)
        if t == "inverse":
            x = float(R(spec.ids[0]))
            fn = {"sine": math.asin, "cosine": math.acos, "tangent": math.atan}[spec.fn]
            if spec.fn != "tangent" and not -1 <= x <= 1:
                return None
            a = math.degrees(fn(x))
            ans = deg(a)
            if not full:
                return Item(text, ans, [], [], self.kind)
            short = {"sine": "sin", "cosine": "cos", "tangent": "tan"}[spec.fn]
            steps = [f"Use the inverse: θ = {short}⁻¹({x:g}) = {ans}"]
            alts = [math.degrees(math.atan(1 / x)) if x else 45, 90 - a, math.degrees(fn(min(1, x / 2)) if spec.fn != "tangent" else math.atan(x / 2)), a + 10]
            return Item(text, ans, steps, [w for w in dict.fromkeys(deg(v) for v in alts) if w != ans], self.kind)
        if t == "right":
            Lv, A = R(spec.L), R(spec.A)
            if not 0 < A < 90:
                return None
            ang = A * DEG if spec.ground else (90 - A) * DEG
            # sides named for the angle with the ground: opposite = up the wall, adjacent = along the ground
            g, w = spec.given, spec.want
            sides = {}
            if g == "hyp":
                sides = {"opp": Lv * sp.sin(ang), "adj": Lv * sp.cos(ang), "hyp": Lv}
            elif g == "adj":
                sides = {"opp": Lv * sp.tan(ang), "hyp": Lv / sp.cos(ang), "adj": Lv}
            else:
                sides = {"adj": Lv / sp.tan(ang), "hyp": Lv / sp.sin(ang), "opp": Lv}
            v = sp.nsimplify(sides[w])
            ans = length(v, spec.unit)
            if not full:
                return Item(text, ans, [], [], self.kind, value=None)
            fn = {("hyp", "opp"): "sin", ("hyp", "adj"): "cos", ("adj", "opp"): "tan", ("opp", "adj"): "tan", ("adj", "hyp"): "cos", ("opp", "hyp"): "sin"}[(g, w)]
            steps = [f"{'SOH' if fn == 'sin' else 'CAH' if fn == 'cos' else 'TOA'}: {fn} {deg(A if spec.ground else 90 - A)} links the {g}otenuse".replace("hypotenuse", "hypotenuse").replace("oppotenuse", "opposite side").replace("adjotenuse", "adjacent side") +
                     f" and the {w}.".replace("opp.", "opposite side.").replace("adj.", "adjacent side.").replace("hyp.", "hypotenuse."),
                     f"So the {'opposite side' if w == 'opp' else 'adjacent side' if w == 'adj' else 'hypotenuse'} = {ans}"]
            alts = [sides[k] for k in sides if k != w] + [Lv * sp.tan(ang), Lv * sp.sin(ang) * 2]
            return Item(text, ans, steps, [x for x in dict.fromkeys(length(sp.nsimplify(a), spec.unit) for a in alts) if x != ans], self.kind)
        if t == "cosine":
            a, b, C = R(spec.a), R(spec.b), R(spec.C)
            if not 0 < C < 180:
                return None
            c2 = a ** 2 + b ** 2 - 2 * a * b * sp.cos(C * DEG)
            c = sp.sqrt(sp.nsimplify(c2))
            ans = length(c, spec.unit)
            if not full:
                return Item(text, ans, [], [], self.kind)
            steps = [f"Cosine rule: c² = a² + b² - 2ab cos C = {fmt_num(a)}² + {fmt_num(b)}² - 2 × {fmt_num(a)} × {fmt_num(b)} × cos {deg(C)}",
                     f"c² = {fmt_sig(float(c2), 4)}, so c = {ans}"]
            alts = [sp.sqrt(a ** 2 + b ** 2 + 2 * a * b * sp.cos(C * DEG)), sp.sqrt(a ** 2 + b ** 2), c2, a + b - c]
            return Item(text, ans, steps, [x for x in dict.fromkeys(length(v, spec.unit) for v in alts) if x != ans], self.kind)
        if t == "sine":
            A, B, a = R(spec.A), R(spec.B), R(spec.a)
            if not (0 < A and 0 < B and A + B < 180):
                return None
            b = a * sp.sin(B * DEG) / sp.sin(A * DEG)
            ans = length(b, spec.unit)
            if not full:
                return Item(text, ans, [], [], self.kind)
            steps = [f"Sine rule: b/sin B = a/sin A, so b = a sin B / sin A = {fmt_num(a)} × sin {deg(B)} / sin {deg(A)} = {ans}"]
            alts = [a * sp.sin(A * DEG) / sp.sin(B * DEG), a * sp.sin(B * DEG), a * B / A, a * sp.sin((180 - A - B) * DEG) / sp.sin(A * DEG)]
            return Item(text, ans, steps, [x for x in dict.fromkeys(length(v, spec.unit) for v in alts) if x != ans], self.kind)
        if t == "area":
            a, b, C = R(spec.a), R(spec.b), R(spec.C)
            if not 0 < C < 180:
                return None
            A = a * b * sp.sin(C * DEG) / 2
            ans = length(A, (spec.unit + "^2") if spec.unit else "")
            if not full:
                return Item(text, ans, [], [], self.kind)
            steps = [f"Area = ½ab sin C = ½ × {fmt_num(a)} × {fmt_num(b)} × sin {deg(C)} = {ans}"]
            alts = [a * b * sp.sin(C * DEG), a * b / 2, a * b * sp.cos(C * DEG) / 2, A * 2]
            return Item(text, ans, steps, [x for x in dict.fromkeys(length(v, (spec.unit + "^2") if spec.unit else "") for v in alts) if x != ans], self.kind)
        if t == "exact":
            e = spec.e.subs(q.subs(vals))
            r = sp.radsimp(sp.expand(e))                    # √2/2 + √3/2, not a nested root
            ans = fmt_expr(r)
            if not full:
                return Item(text, ans, [], [], self.kind)
            steps = ["Use the exact values: sin 30 = cos 60 = 1/2, sin 60 = cos 30 = √3/2, sin 45 = cos 45 = √2/2, tan 45 = 1.", f"So it equals {ans}"]
            from .core import expr_wrong
            return Item(text, ans, steps, expr_wrong(r, [r * 2, r / 2, r + 1, sp.sqrt(3) / 2 if r != sp.sqrt(3) / 2 else 1], fmt_expr), self.kind)
        if t == "equation":
            x = sp.Symbol("x")
            e = spec.e.subs(q.subs(vals))
            free = [s for s in e.free_symbols]
            if len(free) != 1:
                return None
            x = free[0]
            lo, hi = float(R(spec.lo)), float(R(spec.hi))
            sols = trig_roots(e, x, lo, hi)
            if sols is None:
                return None
            if not sols or len(sols) > 6:
                return None
            ss = sorted(sols)
            ans = ", ".join(deg(s) for s in ss)
            exact_angles = all(abs(s - round(s)) < 1e-6 for s in ss)
            if not full:
                return Item(text, ans, [], [], self.kind, value=("exact" if exact_angles else "approx", len(ss)))
            steps = [f"Find the basic angle, then every angle between {deg(lo)} and {deg(hi)} with the same value (use the CAST diagram).",
                     f"So x = {ans}"]
            alts = [ss[:1], [180 - s for s in ss][:len(ss)], [s + 180 for s in ss if s + 180 <= hi] or [360 - ss[0]], [ss[0], 360 - ss[0]]]
            return Item(text, ans, steps, [w for w in dict.fromkeys(", ".join(deg(v) for v in sorted(a)) for a in alts) if w != ans], self.kind,
                        value=("exact" if exact_angles else "approx", len(ss)))
        return None

    def vary(self, q, spec, rng):
        vals = list(q.vals)
        V = [Fraction(v) for v in q.vals]
        t = spec.task
        new_len = lambda i: Fraction(similar_int(int(V[i]), rng)) if V[i].denominator == 1 and V[i] > 1 else Fraction(rng.randint(2, 20))
        if t == "d2r":
            vals[spec.ids[0]] = Fraction(rng.choice([a for a in (15, 30, 45, 60, 75, 90, 120, 135, 150, 210, 225, 240, 270, 300, 315, 330) if a != V[spec.ids[0]]]))
            return vals
        if t == "r2d":
            vals[spec.ids[0]] = Fraction(rng.randint(1, 6)) if V[spec.ids[0]].denominator == 1 else Fraction(rng.randint(5, 30), 10)
            return vals
        if t == "pi2d":
            b = rng.choice([2, 3, 4, 6, 12])
            a = rng.choice([k for k in range(1, 2 * b) if math.gcd(k, b) == 1])
            if spec.ids[0] is not None:
                vals[spec.ids[0]] = Fraction(a)
            vals[spec.ids[1]] = Fraction(b)
            return vals
        if t == "inverse":
            dp = max(1, q.slots[spec.ids[0]].dp)
            top = 10 ** dp - 1 if spec.fn != "tangent" else 3 * 10 ** dp
            vals[spec.ids[0]] = Fraction(rng.randint(1, top), 10 ** dp)
            return vals
        if t == "right":
            vals[spec.L] = new_len(spec.L)
            vals[spec.A] = Fraction(rng.choice([a for a in range(15, 80, 5) if a != V[spec.A]]))
            for dup, first in getattr(spec, "links", {}).items():
                vals[dup] = vals[first]                     # the same angle, mentioned again
            return vals
        if t in ("cosine", "area"):
            vals[spec.a], vals[spec.b] = new_len(spec.a), new_len(spec.b)
            vals[spec.C] = Fraction(rng.choice([a for a in range(30, 150, 10) if a != V[spec.C]]))
            return vals
        if t == "sine":
            A = rng.choice(range(30, 80, 5))
            B = rng.choice([b for b in range(30, 110, 5) if A + b < 160 and b != A])
            vals[spec.A], vals[spec.B], vals[spec.a] = Fraction(A), Fraction(B), new_len(spec.a)
            return vals
        if t == "exact":
            for i in spec.ids:
                vals[i] = Fraction(rng.choice(_EXACT_ANGLES))
            return vals
        if t == "equation":
            # change the right-hand value to another standard one, or the coefficients of a quadratic in sin/cos
            free = [i for i in spec.inside if q.slots[i].role in ("num", "coef") and i not in (spec.lo, spec.hi)]
            std = [Fraction(1, 2), Fraction(-1, 2), Fraction(0), Fraction(1), Fraction(-1)]
            dec = [i for i in free if not q.slots[i].is_int]
            if dec:
                for i in dec:
                    vals[i] = rng.choice([v for v in std if v != V[i] and v not in (0, 1, -1)] + [Fraction(1, 2)])
                return vals
            for i in free:
                if abs(V[i]) > 1:
                    vals[i] = Fraction(rng.randint(2, 4)) * (1 if V[i] > 0 else -1)
            return vals
        return None

    def nice(self, base, item):
        if isinstance(base.value, tuple) and base.value and base.value[0] in ("exact", "approx"):
            return item.value is not None and item.value[0] == base.value[0] and item.value[1] >= 1
        return True
