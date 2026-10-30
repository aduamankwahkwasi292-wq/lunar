"""
CUSTOM-SQE coordinate geometry and vectors:
  - points: the gradient, distance and midpoint of two points;
  - lines: through a point with a gradient, through two points, where two lines meet;
  - circles: the centre and radius from x² + y² + Dx + Ey + F = 0;
  - vectors: magnitude, dot product, the angle between two vectors.

Versions are made answer-first:
  - a whole gradient, a Pythagorean distance and a whole midpoint when the original had them;
  - a circle built from a whole-number centre and radius;
  - lines that meet at a whole-number point.
"""
from __future__ import annotations

import math
import random
import re
from fractions import Fraction
from typing import List, Optional

import sympy as sp

from .core import Family, Item, Spec, numeric_wrong
from .text import Question, exact, fmt_expr, fmt_num, fmt_sig, to_expr

fnum = lambda v: fmt_num(v, fractions=True)
X, Y = sp.symbols("x y")
_TRIPLES = [(3, 4, 5), (5, 12, 13), (8, 15, 17), (6, 8, 10), (7, 24, 25), (9, 12, 15), (12, 16, 20), (20, 21, 29)]


def points(q: Question) -> List[tuple]:
    """(x-slot, y-slot) for each '(a, b)' point in the text."""
    out = []
    for m in re.finditer(r"\(\s*\((S\d+)\)\s*,\s*\((S\d+)\)\s*\)", q.sym):
        out.append((int(m.group(1)[1:]), int(m.group(2)[1:])))
    return out


_I, _J, _K = sp.symbols("i j k")


def vectors(q: Question):
    """Each vector as a list of components (sympy, in the slot symbols): '3i + 4j', 'i - 4j + 2k', '(2, -1, 3)'."""
    out = []
    for m in re.finditer(r"\(\s*((?:\(S\d+\)\s*,\s*){1,2}\(S\d+\))\s*\)", q.sym):
        out.append([sp.Symbol(f"S{s}") for s in re.findall(r"S(\d+)", m.group(1))])
    if out:
        return out
    text = re.sub(r"\|", " ", q.sym)
    for m in re.finditer(r"((?:\(S\d+\)\s*)?[ij](?:\s*[+-]\s*(?:\(S\d+\)\s*)?[ijk]){1,2})", text):
        e = to_expr(m.group(1))
        if e is None or not e.free_symbols & {_I, _J, _K}:
            continue
        comps = [e.coeff(_I), e.coeff(_J)] + ([e.coeff(_K)] if e.has(_K) else [])
        out.append(comps)
    return out


def line_text(m, c) -> str:
    return "y = " + fmt_expr(sp.expand(m * X + c))


class Coordinates(Family):
    name = "coordinates"
    kind = "coordinates"

    def parse(self, q: Question) -> Optional[Spec]:
        low = q.low
        pts = points(q)
        if re.search(r"centre|center", low) and re.search(r"radius", low):
            m = re.search(r"(x\^\(S\d+\)\s*\+\s*y\^\(S\d+\)[^=]*)=\s*(\(S\d+\))", q.sym)
            if not m:
                return None
            e = to_expr(m.group(1) + " - " + m.group(2))
            return Spec(task="circle", e=e, inside=q.slot_symbols(e)) if e is not None else None
        if re.search(r"intersection|meet|intersect", low):
            eqs = re.findall(r"y\s*=\s*([^,]+?)(?=\s+and\s+y\s*=|\s*$|\.|\?|,)", q.sym)
            eqs = [re.split(r"\s+(?=[A-Za-z]{3,})", t)[0] for t in eqs]     # "x + 4 meet?" -> "x + 4"
            if len(eqs) == 2:
                es = [to_expr(t) for t in eqs]
                if all(e is not None for e in es):
                    return Spec(task="meet", es=es, inside=q.slot_symbols(es))
        if re.search(r"vector|\bi\s*[+-]|\bdot\s+product|magnitude|\|.*i.*j.*\||·|\ba\s*\*\s*b\b", low) or "|" in q.display:
            vs = vectors(q)
            if re.search(r"angle\s+between", low) and len(vs) == 2:
                return Spec(task="vangle", vs=vs)
            if re.search(r"dot\s+product|scalar\s+product|\ba\s*[·.*]\s*b\b", low) and len(vs) == 2:
                return Spec(task="dot", vs=vs)
            if re.search(r"magnitude|modulus|length|\|", low) and len(vs) == 1:
                return Spec(task="mag", vs=vs)
        if len(pts) == 2:
            task = ("gradient" if re.search(r"gradient|slope", low) and not re.search(r"equation", low) else
                    "distance" if re.search(r"distance|length", low) else
                    "midpoint" if re.search(r"midpoint|mid-point|middle", low) else
                    "line2" if re.search(r"equation", low) else None)
            return Spec(task=task, pts=pts) if task else None
        if len(pts) == 1 and re.search(r"equation", low) and re.search(r"gradient|slope", low):
            m = re.search(r"(?:gradient|slope)\s*(?:of\s*)?(\(S\d+\))", q.sym)
            if m:
                return Spec(task="line1", pts=pts, m=int(m.group(1)[2:-1]))
        return None

    def solve(self, q, spec, vals, full=True):
        V = [Fraction(v) for v in vals]
        R = lambda i: sp.Rational(V[i].numerator, V[i].denominator)
        text = q.render(vals)
        t = spec.task
        if t in ("gradient", "distance", "midpoint", "line2"):
            (a, b), (c, d) = [(R(i), R(j)) for i, j in spec.pts]
            if t == "gradient":
                if c == a:
                    return None
                g = (d - b) / (c - a)
                ans = fnum(g)
                if not full:
                    return Item(text, ans, [], [], self.kind, value=g)
                steps = [f"Gradient = (y₂ - y₁)/(x₂ - x₁) = ({fnum(d)} - {fnum(b)})/({fnum(c)} - {fnum(a)}) = {ans}"]
                return Item(text, ans, steps, numeric_wrong(g, fnum, [(c - a) / (d - b) if d != b else None, -g, (d + b) / (c + a) if c + a else None]), self.kind, value=g)
            if t == "distance":
                dist = sp.sqrt((c - a) ** 2 + (d - b) ** 2)
                ans = fmt_expr(dist) if not dist.is_Integer else str(dist)
                if not full:
                    return Item(text, ans, [], [], self.kind, value=dist)
                steps = [f"Distance = √((x₂ - x₁)² + (y₂ - y₁)²) = √({fnum(c - a)}² + {fnum(d - b)}²) = √{fnum((c - a) ** 2 + (d - b) ** 2)} = {ans}"]
                alts = [abs(c - a) + abs(d - b), (c - a) ** 2 + (d - b) ** 2, sp.sqrt((c + a) ** 2 + (d + b) ** 2)]
                return Item(text, ans, steps, [w for w in dict.fromkeys(fmt_expr(v) for v in alts) if w != ans], self.kind, value=dist)
            if t == "midpoint":
                mx, my = (a + c) / 2, (b + d) / 2
                ans = f"({fnum(mx)}, {fnum(my)})"
                if not full:
                    return Item(text, ans, [], [], self.kind, value=(mx, my))
                steps = [f"Midpoint = ((x₁ + x₂)/2, (y₁ + y₂)/2) = (({fnum(a)} + {fnum(c)})/2, ({fnum(b)} + {fnum(d)})/2) = {ans}"]
                alts = [(c - a) / 2, (d - b) / 2], [a + c, b + d], [my, mx], [mx, -my]
                return Item(text, ans, steps, [w for w in dict.fromkeys(f"({fnum(x)}, {fnum(y)})" for x, y in alts) if w != ans], self.kind, value=(mx, my))
            if c == a:
                return None
            m = (d - b) / (c - a)
            cc = b - m * a
            ans = line_text(m, cc)
            if not full:
                return Item(text, ans, [], [], self.kind, value=(m, cc))
            steps = [f"Gradient m = ({fnum(d)} - {fnum(b)})/({fnum(c)} - {fnum(a)}) = {fnum(m)}", f"y - {fnum(b)} = {fnum(m)}(x - {fnum(a)})", f"So {ans}"]
            alts = [(m, -cc), (-m, cc), (1 / m if m else 2, cc), (m, d - m * a)]
            return Item(text, ans, steps, [w for w in dict.fromkeys(line_text(x, y) for x, y in alts) if w != ans], self.kind, value=(m, cc))
        if t == "line1":
            (i, j), = spec.pts
            a, b, m = R(i), R(j), R(spec.m)
            cc = b - m * a
            ans = line_text(m, cc)
            if not full:
                return Item(text, ans, [], [], self.kind, value=(m, cc))
            steps = [f"y - y₁ = m(x - x₁): y - {fnum(b)} = {fnum(m)}(x - {fnum(a)})", f"So {ans}"]
            alts = [(m, b + m * a), (m, -cc), (-m, cc), (b, m)]
            return Item(text, ans, steps, [w for w in dict.fromkeys(line_text(x, y) for x, y in alts) if w != ans], self.kind, value=(m, cc))
        if t == "meet":
            e1, e2 = [e.subs(q.subs(vals)) for e in spec.es]
            sol = sp.solve(sp.Eq(e1, e2), X)
            if len(sol) != 1:
                return None
            x0 = sol[0]
            y0 = e1.subs(X, x0)
            ans = f"({fnum(x0)}, {fnum(y0)})"
            if not full:
                return Item(text, ans, [], [], self.kind, value=(x0, y0))
            steps = [f"Where they meet, the y-values are equal: {fmt_expr(e1)} = {fmt_expr(e2)}", f"x = {fnum(x0)}, then y = {fnum(y0)}", f"They meet at {ans}"]
            alts = [(y0, x0), (-x0, y0), (x0, e2.subs(X, -x0)), (x0 + 1, y0)]
            return Item(text, ans, steps, [w for w in dict.fromkeys(f"({fnum(a)}, {fnum(b)})" for a, b in alts) if w != ans], self.kind, value=(x0, y0))
        if t == "circle":
            e = sp.expand(spec.e.subs(q.subs(vals)))
            D, E, F = e.coeff(X, 1), e.coeff(Y, 1), e.subs({X: 0, Y: 0})
            a, b = -D / 2, -E / 2
            r2 = a ** 2 + b ** 2 - F
            if r2 <= 0:
                return None
            r = sp.sqrt(r2)
            ans = f"centre ({fnum(a)}, {fnum(b)}), radius {fmt_expr(r)}"
            if not full:
                return Item(text, ans, [], [], self.kind, value=(a, b, r))
            steps = [f"Complete the square: (x - {fnum(a)})² + (y - {fnum(b)})² = {fnum(r2)}".replace("- -", "+ "), f"So the centre is ({fnum(a)}, {fnum(b)}) and the radius is √{fnum(r2)} = {fmt_expr(r)}"]
            alts = [(-a, -b, r), (a, b, r2), (D, E, r), (b, a, r)]
            return Item(text, ans, steps, [w for w in dict.fromkeys(f"centre ({fnum(x)}, {fnum(y)}), radius {fmt_expr(z)}" for x, y, z in alts) if w != ans], self.kind, value=(a, b, r))
        if t in ("mag", "dot", "vangle"):
            sub = q.subs(vals)
            comps = [[exact(sp.sympify(c).subs(sub)) for c in v] for v in spec.vs]
            if t == "mag":
                v = comps[0]
                mag = sp.sqrt(sum(c ** 2 for c in v))
                ans = fmt_expr(mag)
                if not full:
                    return Item(text, ans, [], [], self.kind, value=mag)
                steps = [f"|v| = √({' + '.join(f'{fnum(c)}²' for c in v)}) = √{fnum(sum(c ** 2 for c in v))} = {ans}"]
                return Item(text, ans, steps, [w for w in dict.fromkeys(fmt_expr(x) for x in [sum(abs(c) for c in v), sum(c ** 2 for c in v), sp.sqrt(abs(sum(c for c in v)))]) if w != ans],
                            self.kind, value=mag)
            u, w = comps
            if len(u) != len(w):
                return None
            dot = sum(a * b for a, b in zip(u, w))
            if t == "dot":
                ans = fnum(dot)
                if not full:
                    return Item(text, ans, [], [], self.kind, value=dot)
                steps = [f"a·b = {' + '.join(f'({fnum(a)})({fnum(b)})' for a, b in zip(u, w))} = {ans}"]
                return Item(text, ans, steps, numeric_wrong(dot, fnum, [sum(abs(a * b) for a, b in zip(u, w)), sum(a + b for a, b in zip(u, w))]), self.kind, value=dot)
            mu, mw = sp.sqrt(sum(a ** 2 for a in u)), sp.sqrt(sum(b ** 2 for b in w))
            if mu == 0 or mw == 0:
                return None
            ang = math.degrees(math.acos(max(-1, min(1, float(dot / (mu * mw))))))
            ans = f"{ang:.1f}°"
            if not full:
                return Item(text, ans, [], [], self.kind)
            steps = [f"a·b = {fnum(dot)}, |a| = {fmt_expr(mu)}, |b| = {fmt_expr(mw)}", f"cos θ = a·b/(|a||b|) = {float(dot / (mu * mw)):.4f}, so θ = {ans}"]
            alts = [180 - ang, 90 - ang if ang < 90 else ang - 90, math.degrees(math.acos(max(-1, min(1, float(dot / (mu * mw)) / 2))))]
            return Item(text, ans, steps, [w for w in dict.fromkeys(f"{a:.1f}°" for a in alts) if w != ans], self.kind)
        return None

    def vary(self, q, spec, rng):
        vals = list(q.vals)
        V = [Fraction(v) for v in q.vals]
        t = spec.task
        r_int = lambda lo=-9, hi=9: Fraction(rng.choice([k for k in range(lo, hi + 1) if k != 0]))
        if t in ("gradient", "distance", "midpoint", "line2"):
            (i1, j1), (i2, j2) = spec.pts
            a, b = r_int(), r_int()
            if t == "distance":
                dx, dy, _ = rng.choice(_TRIPLES)
                if rng.random() < 0.5:
                    dx, dy = dy, dx
                c, d = a + dx * rng.choice([-1, 1]), b + dy * rng.choice([-1, 1])
            elif t == "midpoint":
                c = a + 2 * rng.randint(1, 6) * rng.choice([-1, 1])
                d = b + 2 * rng.randint(1, 6) * rng.choice([-1, 1])
                if a + c == 0 and b + d == 0:
                    return None                             # (0, 0) is too easy
            else:
                g0 = (V[j2] - V[j1]) / (V[i2] - V[i1]) if V[i2] != V[i1] else Fraction(2)
                dx = rng.randint(1, 5)
                g = Fraction(rng.choice([k for k in range(-5, 6) if k != 0])) if g0.denominator == 1 else Fraction(rng.randint(1, 4), rng.choice([2, 3])) * (1 if g0 > 0 else -1)
                c, d = a + dx, b + g * dx
                if d.denominator != 1:
                    return None
            vals[i1], vals[j1], vals[i2], vals[j2] = a, b, Fraction(c), Fraction(d)
            return vals
        if t == "line1":
            (i, j), = spec.pts
            vals[i], vals[j], vals[spec.m] = r_int(), r_int(), r_int(-6, 6)
            return vals
        if t == "meet":
            x0, y0 = r_int(-6, 6), r_int(-6, 9)
            e1, e2 = spec.es
            for e in (e1, e2):
                ids = q.slot_symbols(e)
                if not ids:
                    continue
                m_slots = [i for i in ids if sp.expand(e).coeff(X).has(q.S[i])]
                c_slots = [i for i in ids if i not in m_slots]
                m = Fraction(rng.choice([k for k in range(-5, 6) if k not in (0,)]))
                for i in m_slots:
                    vals[i] = m
                mm = m if m_slots else Fraction(sp.expand(e.subs(q.subs(q.vals))).coeff(X))
                if c_slots:
                    vals[c_slots[0]] = y0 - mm * x0
            if any(v == 0 for i, v in enumerate(vals) if i in q.slot_symbols(spec.es) and q.vals[i] != 0):
                return None
            return vals
        if t == "circle":
            a, b, r = r_int(-6, 6), r_int(-6, 6), Fraction(rng.randint(2, 9))
            e = sp.expand(spec.e)
            dx = [i for i in q.slot_symbols(e) if e.coeff(X, 1).has(q.S[i])]
            dy = [i for i in q.slot_symbols(e) if e.coeff(Y, 1).has(q.S[i])]
            rest = [i for i in q.slot_symbols(e) if i not in dx + dy and q.slots[i].role != "exp" and q.vals[i] != 0]
            if not dx or not dy or not rest:
                return None
            vals[dx[0]], vals[dy[0]] = -2 * a, -2 * b
            F = a * a + b * b - r * r
            vals[rest[-1]] = F if len(rest) == 1 or True else F
            if F == 0:
                return None
            return vals
        if t == "mag":
            v = spec.vs[0]
            slots = [int(c.name[1:]) if isinstance(c, sp.Symbol) and c.name.startswith("S") else None for c in v]
            if None in slots:                               # an unwritten 1 (i + 3j): any whole numbers for the rest
                for c in v:
                    for i in q.slot_symbols(sp.sympify(c)):
                        vals[i] = Fraction(rng.randint(2, 9) * (1 if q.vals[i] > 0 else -1))
                return vals
            if len(v) == 2:
                x, y, _ = rng.choice(_TRIPLES)
                if rng.random() < 0.5:
                    x, y = y, x
                vals[slots[0]] = Fraction(x * (1 if q.vals[slots[0]] > 0 else -1))
                vals[slots[1]] = Fraction(y * (1 if q.vals[slots[1]] > 0 else -1))
            else:
                quads = [(1, 2, 2), (2, 3, 6), (1, 4, 8), (2, 6, 9), (4, 4, 7), (2, 10, 11)]
                cs = list(rng.choice(quads))
                rng.shuffle(cs)
                for i, c in zip(slots, cs):
                    vals[i] = Fraction(c * rng.choice([-1, 1]))
            return vals
        if t in ("dot", "vangle"):
            for v in spec.vs:
                for c in v:
                    for i in q.slot_symbols(sp.sympify(c)):
                        vals[i] = Fraction(rng.randint(2, 6) * (1 if q.vals[i] > 0 else -1))   # 1 would vanish ("i")
            comps = [[sp.sympify(c).subs(q.subs(vals)) for c in v] for v in spec.vs]
            if len(comps) == 2 and comps[0] == comps[1]:
                return None                                 # the same vector twice: angle 0
            return vals
        return None

    def nice(self, base, item):
        b, v = base.value, item.value
        if b is None or v is None:
            return True
        if isinstance(b, tuple):
            return all((not exact(x).is_Integer) or exact(y).is_Integer for x, y in zip(b, v))
        b, v = exact(b), exact(v)
        if b.is_Integer:
            return v.is_Integer
        return True
