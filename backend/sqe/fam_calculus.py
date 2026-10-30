"""
CUSTOM-SQE calculus families: differentiation, integration, limits.

Versions keep the student's expression with new coefficients. Stationary points stay at whole numbers, a 0/0
limit stays 0/0, and an area stays on one side of the axis. Every answer is checked a second way:
  - a derivative against a numerical slope;
  - an integral by differentiating it back;
  - a limit numerically near the point.
"""
from __future__ import annotations

import random
import re
from fractions import Fraction
from typing import List, Optional

import sympy as sp

from .core import (Family, Item, Spec, back_solve, expr_wrong, keep_roots, like, numeric_wrong, same_expr,
                   varying, vary_slots)
from .text import exact, Question, fmt_expr, fmt_num, frac, to_expr

fnum = lambda v: fmt_num(v, fractions=True)       # maths answers: 1/4, 5/2

X = sp.Symbol("x")
_STOP = re.compile(
    r"\s+(?:at|when|where|with\s+respect|w\.?r\.?t\.?|for|and\s+hence|and\s+find|and\s+state|and\s+determine|"
    r"hence|giving|leaving|correct|from|between|as\s+[a-z]\s+(?:approaches|tends|goes|->))\b|\s*(?:[,;?]|\.\s|\.$|$)",
    re.I)


def cut(expr_text: str) -> str:
    """An expression with the words after it cut off ("x^2 - 4x + 3 at the point x = 5" -> "x^2 - 4x + 3")."""
    t = expr_text.strip()
    m = _STOP.search(t)
    t = t[:m.start()] if m else t
    t = re.sub(r"\s*\bd[a-z]\s*$", "", t)                       # a trailing "dx"
    return t.strip().rstrip(".").strip()


def assigned(sym: str) -> Optional[str]:
    """The right-hand side of 'y = …' or 'f(x) = …' (or f(x, y) = …)."""
    m = re.search(r"(?:\by|\bf\s*\(\s*[a-z]\s*(?:,\s*[a-z]\s*)?\))\s*=\s*(.+)", sym)
    return cut(m.group(1)) if m else None


def var_of(q: Question, e: sp.Expr) -> Optional[sp.Symbol]:
    m = re.search(r"(?:with\s+respect\s+to|w\.?r\.?t\.?)\s+([a-z])\b", q.low) or re.search(r"\bd/d([a-z])\b|\bd[a-z]?/d([a-z])\b", q.low)
    if m:
        name = next(g for g in m.groups() if g)
        return sp.Symbol(name)
    free = sorted((s for s in e.free_symbols if not re.fullmatch(r"S\d+", s.name)), key=lambda s: s.name)
    if sp.Symbol("x") in free:
        return sp.Symbol("x")
    return free[0] if len(free) == 1 else None


def concrete(q: Question, e, vals):
    return e.subs(q.subs(vals))


def short(*cands) -> sp.Expr:
    """The tidiest of several equal forms."""
    best, blen = None, 10 ** 9
    for c in cands:
        if c is None:
            continue
        try:
            n = len(fmt_expr(c))
        except Exception:                                                    # noqa: BLE001
            continue
        if n < blen:
            best, blen = c, n
    return best


def tidy(e: sp.Expr) -> sp.Expr:
    """A tidy equal form, fast:
    - polynomials written out (2xy + 3y^2);
    - fractions cancelled or factorised (-7/(x - 3)^2);
    - products of functions written out (x^2 cos(x) + 2x sin(x));
    - otherwise whichever reads shortest."""
    syms = list(e.free_symbols)
    try:
        if not syms:
            return e
        ex = sp.expand(e)
        if e.is_polynomial(*syms):
            return ex
        if e.is_rational_function(*syms):
            return short(sp.cancel(e), sp.factor(e), ex, e)
        best = short(e, ex)
        if len(fmt_expr(ex)) <= 1.4 * len(fmt_expr(best)):
            return ex
        return best
    except Exception:                                                        # noqa: BLE001
        return e


def power_terms(f: sp.Expr, x: sp.Symbol):
    """[(c, n)] when f is written as a sum of terms c·x^n (n a number: x^3, 4/x^2, sqrt(x)), else None."""
    out = []
    for t in sp.Add.make_args(f):
        c, rest = t.as_independent(x, as_Add=False)
        if rest == 1:
            out.append((c, sp.Integer(0)))
        elif rest == x:
            out.append((c, sp.Integer(1)))
        elif isinstance(rest, sp.Pow) and rest.base == x and rest.exp.is_number:
            out.append((c, rest.exp))
        else:
            return None
    return out


def poly_exponent_vary(q: Question, slots: List[int], vals: List[Fraction], rng: random.Random,
                       always: bool = False) -> None:
    """New exponents, keeping their order (biggest first stays biggest first)."""
    exps = [i for i in slots if q.slots[i].role == "exp" and q.slots[i].is_int and 2 <= q.slots[i].value <= 9]
    if len(exps) < 1 or (not always and rng.random() < 0.5):
        return
    order = sorted(exps, key=lambda i: -q.slots[i].value)
    for _ in range(12):                                 # each within -1..+2 of the original, still in order
        new = [int(q.slots[i].value) + rng.randint(-1, 2) for i in order]
        if all(v >= 2 for v in new) and all(a > b for a, b in zip(new, new[1:])):
            for i, v in zip(order, new):
                vals[i] = Fraction(v)
            return


# ══ differentiation ══════════════════════════════════════════════════════════════════════════════════════════

_DIFF = re.compile(r"differentiat|derivative|\bd/d[a-z]\b|\bd[a-z]/d[a-z]\b|f\s*'|gradient\s+(?:of\s+the\s+curve|function)|"
                   r"(?:gradient|slope)\s+of\s+(?:y|f\s*\(\s*x\s*\))\s*=|"
                   r"stationary\s+point|turning\s+point|\btangent\b|\bnormal\b|\bpartial\b|d\^?2y/dx\^?2|maximum\s+and\s+minimum", re.I)


def diff_steps(f: sp.Expr, x: sp.Symbol, lhs: str, answer: sp.Expr) -> List[str]:
    pt = power_terms(f, x)
    if pt:
        steps = ["Differentiate term by term with the power rule: d/dx(ax^n) = n·a·x^(n-1); a constant gives 0."]
        for c, n in sorted(pt, key=lambda cn: -float(cn[1])):
            t = c * x ** n
            steps.append(f"d/dx({fmt_expr(t)}) = {fmt_expr(sp.diff(t, x))}")
        steps.append(f"So {lhs}{fmt_expr(answer)}")
        return steps
    steps = []
    terms = sp.Add.make_args(f)
    if len(terms) > 1:
        steps.append("Differentiate each term on its own, then add.")
    for t in terms:
        num, den = sp.fraction(sp.together(t)) if t.is_Mul or t.is_Pow else (t, sp.Integer(1))
        factors = [a for a in sp.Mul.make_args(t) if a.has(x)]
        if den.has(x) and num.has(x) and not t.is_Pow:
            u, v = num, den
            steps.append(f"Quotient rule for {fmt_expr(t)}: d/dx(u/v) = (u'v - uv')/v^2, with u = {fmt_expr(u)}, "
                         f"v = {fmt_expr(v)}: u' = {fmt_expr(sp.diff(u, x))}, v' = {fmt_expr(sp.diff(v, x))}.")
        elif len(factors) >= 2:
            u, v = factors[0], sp.Mul(*factors[1:])
            c = sp.Mul(*[a for a in sp.Mul.make_args(t) if not a.has(x)])
            pre = f"{fmt_expr(c)} × " if c != 1 else ""
            steps.append(f"Product rule for {pre}{fmt_expr(u)}·{fmt_expr(v)}: d/dx(uv) = u'v + uv', with u = {fmt_expr(u)}, "
                         f"v = {fmt_expr(v)}: u' = {fmt_expr(sp.diff(u, x))}, v' = {fmt_expr(sp.diff(v, x))}.")
        else:
            core = factors[0] if factors else t
            inner = None
            if isinstance(core, sp.Pow) and core.base.has(x) and core.base != x:
                inner = core.base
            elif isinstance(core, sp.Function) and core.args and core.args[0] != x and core.args[0].has(x):
                inner = core.args[0]
            elif isinstance(core, sp.Pow) and core.exp.has(x) and core.exp != x:
                inner = core.exp
            if inner is not None:
                steps.append(f"Chain rule for {fmt_expr(t)}: let u = {fmt_expr(inner)}, so du/dx = "
                             f"{fmt_expr(sp.diff(inner, x))}; differentiate the outside, then multiply by du/dx.")
            elif t.has(x):
                steps.append(f"d/dx({fmt_expr(t)}) = {fmt_expr(tidy(sp.diff(t, x)))}")
    steps.append(f"So {lhs}{fmt_expr(answer)}")
    return steps


def diff_mistakes(f: sp.Expr, x: sp.Symbol, d: sp.Expr) -> list:
    out = []
    pt = power_terms(f, x)
    if pt:
        out.append(sum(c * n * x ** n for c, n in pt if n != 0))                           # kept the power
        out.append(sum(c * x ** (n - 1) for c, n in pt if n != 0))                         # forgot to multiply
        out.append(sum(c * n * x ** (n + 1) for c, n in pt if n != 0))                     # raised the power
        const = sum(c for c, n in pt if n == 0)
        if const:
            out.append(d + const)                                                          # kept the constant
    parts = sp.Add.make_args(d)
    if len(parts) >= 2:
        out.append(d - 2 * parts[0])                                                       # one sign wrong
        out.append(d - 2 * parts[-1])
    for g in sp.preorder_traversal(d):                                                     # a sign slip inside
        if isinstance(g, sp.Add) and g.has(x) and any(not a.has(x) for a in g.args):
            c = sum(a for a in g.args if not a.has(x))
            out.append(d.xreplace({g: g - 2 * c}))
            break
    num, den = sp.fraction(sp.together(f))
    if den.has(x) and num.has(x):
        out.append(sp.cancel((num * sp.diff(den, x) - sp.diff(num, x) * den) / den ** 2))    # u'v, uv' swapped
        out.append(sp.cancel(sp.diff(num, x) / sp.diff(den, x)))
    factors = [a for a in sp.Mul.make_args(f) if a.has(x)]
    if len(factors) == 2 and not den.has(x):
        u, v = factors
        c = f / (u * v)
        out.append(sp.expand(c * sp.diff(u, x) * sp.diff(v, x)))                           # u'v'
        out.append(sp.expand(c * sp.diff(u, x) * v))                                       # only u'v
    for g in sp.preorder_traversal(f):                                                     # forgot the inside
        if isinstance(g, (sp.Function, sp.Pow)) and g != x and g.args and g.args[0].has(x) and g.args[0] != x:
            inner = g.args[0] if isinstance(g, sp.Function) else g.base
            k = sp.diff(inner, x)
            if k != 0 and k != 1:
                out.append(d / k)                                                          # forgot du/dx
                out.append(d * k)
            if isinstance(g, sp.Pow) and g.exp.is_number:
                out.append(d * inner)                                                      # power not lowered
            break
    out += [2 * d, -d, sp.integrate(f, x) if pt else None]
    return out


class Differentiate(Family):
    name = "differentiation"
    kind = "differentiation"

    def parse(self, q: Question) -> Optional[Spec]:
        if not _DIFF.search(q.low) or re.search(r"\bintegra|∫|\blim\b|\blimit\b", q.low):
            return None
        low = q.low
        task = ("partial" if ("partial" in low or re.search(r"\bdf/d[a-z]\b", low)) else
                "second" if re.search(r"second\s+derivative|d\^?2y/dx\^?2|f\s*''|d²y", low) else
                "stationary" if re.search(r"stationary|turning\s+point|maximum\s+and\s+minimum|minimum\s+and\s+maximum", low) else
                "tangent" if "tangent" in low else "normal" if re.search(r"\bnormal\b", low) else
                "at" if re.search(r"\b(?:at|when)\s+(?:the\s+point\s+)?(?:where\s+)?x\s*=|\bat\s+the\s+point\s*\(|\bat\s*\(", low) else
                "derivative")
        body = assigned(q.sym)
        if body is None:
            m = re.search(r"(?:differentiate|derivative\s+of|d/d[a-z]\s*(?:of)?|find\s+f\s*'\s*\(\s*x\s*\)\s*(?:of|for|if)?)\s*"
                          r"(?:with\s+respect\s+to\s+[a-z]\s*:?\s*)?(.+)", q.sym, re.I)
            if not m:
                return None
            body = cut(m.group(1))
        body = re.sub(r"^(?:the\s+(?:function|curve|expression)\s+)", "", body.strip(), flags=re.I)
        if not body:
            return None
        f = to_expr(body)
        if f is None:
            return None
        x = var_of(q, f) if task == "partial" else (sp.Symbol("x") if f.has(sp.Symbol("x")) else var_of(q, f))
        if x is None or not f.has(x):
            return None
        point = None
        if task in ("tangent", "normal", "at"):
            m = (re.search(r"x\s*=\s*(\(S\d+\)|-?\d+(?:\.\d+)?)", q.sym.split(body, 1)[-1]) or
                 re.search(r"point\s*\(\s*(\(S\d+\)|-?\d+)\s*,", q.sym) or re.search(r"\bat\s*\(\s*(\(S\d+\)|-?\d+)\s*,", q.sym))
            if not m:
                return None
            point = to_expr(m.group(1))
            if point is None:
                return None
        lhs = ("f'(x) = " if re.search(r"\bf\s*\(", q.low) and task in ("derivative",) else
               "dy/dx = " if task == "derivative" else "")
        if task == "derivative" and x != sp.Symbol("x"):
            lhs = f"d/d{x.name} = "
        inside = q.slot_symbols(f) + (q.slot_symbols(point) if point is not None else [])
        fo = f.subs(q.subs(q.vals))
        return Spec(f=f, x=x, task=task, point=point, lhs=lhs, inside=inside, poly=bool(fo.is_polynomial(x)),
                    expanded=power_terms(fo, x) is not None)

    def solve(self, q: Question, spec: Spec, vals, full: bool = True) -> Optional[Item]:
        sub = q.subs(vals)
        f, x = sp.expand(spec.f.subs(sub)) if spec.expanded else spec.f.subs(sub), spec.x
        text = q.render(vals)
        task = spec.task
        if task == "partial":
            d = sp.diff(f, x)
            ans = f"∂f/∂{x.name} = {fmt_expr(tidy(d))}"
            if not full:
                return Item(text, ans, [], [], self.kind)
            steps = [f"Treat every letter except {x.name} as a constant and differentiate with respect to {x.name}.",
                     f"So ∂f/∂{x.name} = {fmt_expr(tidy(d))}"]
            wrong = [f"∂f/∂{x.name} = {w}" for w in expr_wrong(d, [sp.diff(f, s) for s in f.free_symbols if s != x] + diff_mistakes(f, x, d), fmt_expr)]
            return Item(text, ans, steps, wrong, self.kind)
        d = sp.diff(f, x)
        if task == "derivative":
            dd = d if (spec.poly and not spec.expanded) else tidy(d)      # (3x^2 + 5)^4 -> 24x(3x^2 + 5)^3
            if not self._slope_ok(f, x, dd):
                return None
            if not full:
                return Item(text, spec.lhs + fmt_expr(dd), [], [], self.kind)
            fmt_like = (lambda e: fmt_expr(e)) if (spec.poly and not spec.expanded) else (lambda e: fmt_expr(tidy(e)))
            wrong = [spec.lhs + w for w in expr_wrong(dd, diff_mistakes(f, x, dd), fmt_like)]
            return Item(text, spec.lhs + fmt_expr(dd), diff_steps(f, x, spec.lhs, dd), wrong, self.kind)
        if task == "second":
            d2 = tidy(sp.diff(f, x, 2))
            lhs = "d²y/dx² = " if not re.search(r"\bf\s*\(", q.low) else "f''(x) = "
            if not full:
                return Item(text, lhs + fmt_expr(d2), [], [], self.kind)
            steps = [f"First derivative: {fmt_expr(tidy(d))}", f"Differentiate again: {lhs}{fmt_expr(d2)}"]
            wrong = [lhs + w for w in expr_wrong(d2, [d, sp.diff(d2, x), 2 * d2, sp.expand(d2 + 2)] +
                                                 diff_mistakes(d, x, d2), fmt_expr)]
            return Item(text, lhs + fmt_expr(d2), steps, wrong, self.kind)
        if task == "at":
            x0 = spec.point.subs(sub)
            m = exact(d.subs(x, x0))
            if not m.is_real:
                return None
            if not full:
                return Item(text, fnum(m), [], [], self.kind, value=m)
            steps = [f"dy/dx = {fmt_expr(tidy(d))}", f"At x = {fnum(x0)}: dy/dx = {fnum(m)}"]
            wrong = numeric_wrong(m, fnum, [f.subs(x, x0)] + [w.subs(x, x0) for w in diff_mistakes(f, x, d) if w is not None and w.has(x)])
            return Item(text, fnum(m), steps, wrong, self.kind, value=m)
        if task in ("tangent", "normal"):
            x0 = spec.point.subs(sub)
            y0 = exact(f.subs(x, x0))
            m = exact(d.subs(x, x0))
            if task == "normal":
                if m == 0:
                    return None
                m = -1 / m
            c = exact(y0 - m * x0)
            line = lambda mm, cc: "y = " + fmt_expr(sp.expand(mm * x + cc))
            if not full:
                return Item(text, line(m, c), [], [], self.kind, value=(m, c))
            steps = [f"dy/dx = {fmt_expr(tidy(d))}", f"At x = {fnum(x0)}: y = {fnum(y0)}, gradient = {fnum(exact(d.subs(x, x0)))}"]
            if task == "normal":
                steps.append(f"The normal's gradient is -1/(that) = {fnum(m)}")
            steps.append(f"y - {fnum(y0)} = {fnum(m)}(x - {fnum(x0)}), so {line(m, c)}")
            wrong = []
            for mm, cc in ((m, -c), (-m, c), (m, y0), (exact(d.subs(x, x0)) if task == "normal" else -1 / m if m else 2 * m, c), (m, c + m), (2 * m, c)):
                s = line(mm, cc)
                if s != line(m, c) and s not in wrong:
                    wrong.append(s)
            return Item(text, line(m, c), steps, wrong, self.kind, value=(m, c))
        if task == "stationary":
            try:
                xs = [r for r in sp.solve(sp.Eq(d, 0), x) if r.is_real]
            except Exception:                                                # noqa: BLE001
                return None
            if not xs or len(xs) > 4:
                return None
            xs = sorted(xs, key=lambda r: float(r))
            d2 = sp.diff(f, x, 2)
            pts, steps = [], [f"dy/dx = {fmt_expr(tidy(d))}", f"Stationary points where dy/dx = 0: x = {', '.join(fnum(r) for r in xs)}"]
            for r in xs:
                y = exact(f.subs(x, r))
                k = d2.subs(x, r)
                nature = "minimum" if k > 0 else "maximum" if k < 0 else "point of inflection"
                pts.append(f"({fnum(r)}, {fnum(y)}) {nature}")
                steps.append(f"x = {fnum(r)}: y = {fnum(y)}; d²y/dx² = {fnum(k)}, so a {nature}")
            ans = " and ".join(pts)
            wrong = []
            for alt in (
                " and ".join(p.replace("minimum", "MAX").replace("maximum", "minimum").replace("MAX", "maximum") for p in pts),
                " and ".join(f"({fnum(-r)}, {fnum(exact(f.subs(x, -r)))}) {p.rsplit(' ', 1)[-1]}" for r, p in zip(xs, pts)),
                " and ".join(f"({fnum(r)}, {fnum(exact(d2.subs(x, r)))}) {p.rsplit(' ', 1)[-1]}" for r, p in zip(xs, pts)),
                " and ".join(f"({fnum(r)}, {fnum(exact(f.subs(x, r)) + 1)}) {p.rsplit(' ', 1)[-1]}" for r, p in zip(xs, pts)),
            ):
                if alt != ans and alt not in wrong:
                    wrong.append(alt)
            return Item(text, ans, steps, wrong, self.kind, value=tuple(xs))
        return None

    @staticmethod
    def _slope_ok(f, x, d) -> bool:
        """Independent check: the derivative matches the slope measured numerically."""
        for x0 in (0.37, 1.21, 2.13):
            try:
                h = 1e-6
                num = (complex(f.subs(x, x0 + h).evalf()) - complex(f.subs(x, x0 - h).evalf())) / (2 * h)
                val = complex(d.subs(x, x0).evalf())
            except Exception:                                                # noqa: BLE001
                continue
            if abs(num - val) > 1e-3 * max(1, abs(val)):
                return False
        return True

    def vary(self, q: Question, spec: Spec, rng: random.Random):
        if spec.task == "stationary" and spec.poly:
            return keep_roots(q, [sp.diff(spec.f, spec.x)], spec.x, rng, free=spec.inside, flip_roots=0.2)
        vals = vary_slots(q, spec.inside, rng)
        if spec.task in ("derivative", "second", "partial") and (spec.poly or not varying(q, spec.inside)):
            poly_exponent_vary(q, spec.inside, vals, rng, always=not varying(q, spec.inside))
        return vals

    def nice(self, base: Item, item: Item) -> bool:
        return like(item.value, base.value) if base.value is not None else True


# ══ integration ═════════════════════════════════════════════════════════════════════════════════════════════

_INT = re.compile(r"\bintegra|∫|antiderivative|anti-derivative|area\s+(?:under|enclosed|bounded|between)", re.I)
_LIM = r"(\(S\d+\)(?:\s*\*?\s*pi(?:\s*/\s*\(S\d+\))?)?|-?\d+(?:\.\d+)?|pi(?:\s*/\s*\(S\d+\))?|\(S\d+\)\s*/\s*\(S\d+\)|e|E)"


def int_mistakes(f, x, F):
    out = []
    pt = power_terms(f, x)
    if pt:
        out.append(sum(c * x ** (n + 1) for c, n in pt))                                    # forgot to divide
        out.append(sum((c * x ** (n + 1) / n if n else c * x) for c, n in pt))              # divided by n
        out.append(sum(c * x ** (n - 1) * n for c, n in pt))                                # differentiated
    out.append(sp.diff(f, x))                                                              # differentiated
    parts = sp.Add.make_args(sp.expand(F))
    if len(parts) >= 2:
        out.append(sp.expand(F - 2 * parts[0]))
    out += [2 * F, F / 2, -F]
    return out


def int_steps(f, x, F, limits=None) -> List[str]:
    steps = []
    pt = power_terms(f, x)
    if pt and all(n != -1 for _, n in pt):
        steps.append("Integrate term by term: ∫ax^n dx = a·x^(n+1)/(n+1).")
        for c, n in sorted(pt, key=lambda cn: -float(cn[1])):
            t = c * x ** n
            steps.append(f"∫{fmt_expr(t)} dx = {fmt_expr(sp.integrate(t, x))}")
    elif f.is_rational_function(x) and sp.fraction(sp.together(f))[1].has(x) and sp.apart(f, x) != f:
        parts = sp.apart(f, x)
        steps.append(f"Split the fraction first: {fmt_expr(f)} = {fmt_expr(parts)}.")
        steps.append("Integrate each term (∫1/x dx = ln|x|, ∫1/(x + a) dx = ln|x + a|).")
    else:
        rule = ""
        try:
            from sympy.integrals.manualintegrate import integral_steps
            r = integral_steps(f, x)
            for _ in range(4):                             # look through "constant times …" wrappers
                if type(r).__name__ in ("ConstantTimesRule", "AlternativeRule") and hasattr(r, "substep"):
                    r = r.substep
                elif type(r).__name__ == "AlternativeRule" and getattr(r, "alternatives", None):
                    r = r.alternatives[0]
                else:
                    break
            rule = type(r).__name__
            if rule == "URule":
                steps.append(f"Substitute u = {fmt_expr(r.u_func)}: the integral becomes one in u.")
            elif rule in ("PartsRule", "CyclicPartsRule"):
                steps.append(f"Integrate by parts, ∫u dv = uv - ∫v du, with u = {fmt_expr(r.u)} and dv = {fmt_expr(r.dv)} dx.")
            elif rule in ("RewriteRule",):
                steps.append(f"Rewrite it first: {fmt_expr(r.rewritten)}.")
        except Exception:                                                    # noqa: BLE001
            pass
        if not steps:
            steps.append("Use the standard integral of each part (and the reverse chain rule for a linear inside).")
    if limits is None:
        steps.append(f"So the integral is {fmt_expr(F)} + C")
    else:
        a, b, val = limits
        steps.append(f"F(x) = {fmt_expr(F)}")
        steps.append(f"F({fnum(b)}) - F({fnum(a)}) = {fnum(val)}")
    return steps


class Integrate(Family):
    name = "integration"
    kind = "integration"

    def parse(self, q: Question) -> Optional[Spec]:
        if not _INT.search(q.low):
            return None
        sym = q.sym.replace("∫", " integral ")
        area = bool(re.search(r"\barea\b", q.low))
        a = b = None
        m = (re.search(rf"\bfrom\s+(?:x\s*=\s*)?{_LIM}\s+to\s+(?:x\s*=\s*)?{_LIM}", sym, re.I) or
             re.search(rf"\bbetween\s+x\s*=\s*{_LIM}\s+and\s+x\s*=\s*{_LIM}", sym, re.I) or
             re.search(rf"\blines\s+x\s*=\s*{_LIM}\s+and\s+x\s*=\s*{_LIM}", sym, re.I) or
             re.search(rf"\blimits\s+{_LIM}\s+and\s+{_LIM}", sym, re.I) or
             re.search(rf"\bx\s*=\s*{_LIM}\s+(?:and|to)\s+x\s*=\s*{_LIM}", sym, re.I))
        if m:
            a, b = to_expr(m.group(1)), to_expr(m.group(2))
            if a is None or b is None:
                return None
        body = assigned(sym) if area else None
        if body is None:
            mm = (re.search(r"\bof\s+(.+?)\s*(?:\bd[a-z]\b|$)", sym.split(m.group(0))[-1] if m and " of " in sym.split(m.group(0))[-1] else "", re.I)
                  or re.search(r"(?:integrate|integral\s+of|integral|antiderivative\s+of|anti-derivative\s+of)\s*(?:the\s+function\s+)?(.+)", sym, re.I))
            if not mm:
                return None
            body = mm.group(1)
            if m and m.group(0) in body:
                body = body.replace(m.group(0), " ")
            body = re.sub(r"^\s*(?:from|between)\b.*?\bof\b", "", body, flags=re.I)
            body = cut(body)
        body = re.sub(r"^\s*(?:the\s+)?(?:definite\s+)?(?:integral\s+)?(?:of\s+)?", "", body, flags=re.I)
        body = re.sub(r"\bd[a-z]\s*$", "", body).strip()
        f = to_expr(body)
        if f is None:
            return None
        x = var_of(q, f) or X
        if not f.has(x):
            return None
        inside = q.slot_symbols(f) + (q.slot_symbols([a, b]) if a is not None else [])
        fo = f.subs(q.subs(q.vals))
        return Spec(f=f, x=x, a=a, b=b, area=area, inside=inside, poly=bool(fo.is_polynomial(x)),
                    expanded=power_terms(fo, x) is not None)

    def solve(self, q: Question, spec: Spec, vals, full: bool = True) -> Optional[Item]:
        sub = q.subs(vals)
        f, x = spec.f.subs(sub), spec.x
        if spec.expanded:
            f = sp.expand(f)
        text = q.render(vals)
        F = None
        if not spec.expanded:
            try:
                from sympy.integrals.manualintegrate import manualintegrate
                F = manualintegrate(f, x)                  # the textbook form: (x^2 + 1)^4/4, not expanded
            except Exception:                              # noqa: BLE001
                F = None
            if F is not None and F.has(sp.Integral):
                F = None
        if F is None or not spec.expanded:
            G = sp.integrate(f, x)                         # whichever form reads best: ln(x), not ln(x^2)/2
            if not G.has(sp.Integral):
                F = short(F, tidy(G)) if F is not None else tidy(G)
        if F is None:
            return None
        if not same_expr(sp.diff(F, x), f):                                  # independent check: differentiate back
            return None
        if spec.a is None:
            if not full:
                return Item(text, f"{fmt_expr(F)} + C", [], [], self.kind)
            pows = [g for g in sp.preorder_traversal(F) if isinstance(g, sp.Pow) and g.base.is_Add and g.exp.is_number]
            if pows and not spec.expanded:              # (x^3 + 9)^5/5 form: wrong options in the same form
                pw = pows[0]
                c = sp.simplify(F / pw)
                cands = [F * pw.exp, F / pw.exp, 2 * F, c * pw.exp * pw.base ** (pw.exp - 1), c * pw.base ** (pw.exp + 1) / (pw.exp + 1)]
                wrong = [w + " + C" for w in expr_wrong(F, cands, fmt_expr)]
            else:
                wrong = [w + " + C" for w in expr_wrong(F, int_mistakes(f, x, F), lambda e: fmt_expr(tidy(e)))]
            return Item(text, f"{fmt_expr(F)} + C", int_steps(f, x, F), wrong, self.kind)
        a, b = spec.a.subs(sub), spec.b.subs(sub)
        if not (a.is_real and b.is_real) or not a < b:
            return None
        if spec.area:
            cuts = sorted({r for r in sp.solve(sp.Eq(f, 0), x) if r.is_real and a < r < b}, key=float) if spec.poly else []
            pts = [a] + cuts + [b]
            val = sum(abs(sp.integrate(f, (x, pts[k], pts[k + 1]))) for k in range(len(pts) - 1))
        else:
            val = sp.integrate(f, (x, a, b))
        val = exact(val)
        if val.has(sp.Integral) or not val.is_real:
            return None
        try:                                                                 # independent check: numerically
            import mpmath
            fl = sp.lambdify(x, sp.Abs(f) if spec.area else f, "mpmath")
            if abs(float(mpmath.quad(fl, [float(a), float(b)])) - float(val)) > 1e-6 * max(1, abs(float(val))):
                return None
        except Exception:                                                    # noqa: BLE001
            pass
        Fa, Fb = exact(F.subs(x, a)), exact(F.subs(x, b))
        unit = " square units" if spec.area else ""
        if not full:
            return Item(text, fnum(val) + unit, [], [], self.kind, value=val)
        wrong = [w + unit for w in numeric_wrong(val, fnum, [Fa - Fb, Fb, Fb + Fa, exact(f.subs(x, b) - f.subs(x, a))])]
        return Item(text, fnum(val) + unit, int_steps(f, x, F, (a, b, val)), wrong, self.kind, value=val)

    def vary(self, q: Question, spec: Spec, rng: random.Random):
        vals = vary_slots(q, spec.inside, rng)
        if spec.expanded and spec.a is None:
            poly_exponent_vary(q, spec.inside, vals, rng)
        return vals

    def nice(self, base: Item, item: Item) -> bool:
        return like(item.value, base.value) if base.value is not None else True


def has_root(f) -> bool:
    return any(isinstance(g, sp.Pow) and g.exp == sp.Rational(1, 2) for g in sp.preorder_traversal(f))


# ══ limits ══════════════════════════════════════════════════════════════════════════════════════════════════

_POINT = r"(\(S\d+\)|-?\d+(?:\.\d+)?|oo|-oo|\+oo|0)"


class Limit(Family):
    name = "limit"
    kind = "limit"

    def parse(self, q: Question) -> Optional[Spec]:
        if not re.search(r"\blim\b|\blimit\b", q.low):
            return None
        s = q.sym
        m = (re.search(rf"\b[a-z]\s*(?:->|tends\s+to|approaches|goes\s+to)\s*{_POINT}", s, re.I) or
             re.search(rf"\bas\s+[a-z]\s+(?:->|tends\s+to|approaches|goes\s+to)\s+{_POINT}", s, re.I))
        if not m:
            return None
        pt = m.group(1).replace("+oo", "oo")
        a = sp.oo if pt == "oo" else -sp.oo if pt == "-oo" else to_expr(pt)
        if a is None:
            return None
        rest = s[m.end():]
        before = s[:m.start()]
        body = None
        mo = re.search(r"\bof\s+(.+)", rest)
        if mo:
            body = mo.group(1)
        elif re.search(r"\blimit\s+of\s+(.+)", before, re.I):
            body = re.search(r"\blimit\s+of\s+(.+)", before, re.I).group(1)
            body = re.sub(r"\s+as(?:\s+[a-z])?\s*$", "", body.strip())
        else:
            body = re.sub(r"^\s*\)?\s*", "", rest)
        body = cut(re.sub(r"\s+as\s+[a-z]\s+.*$", "", body))
        f = to_expr(body)
        if f is None:
            return None
        x = sp.Symbol(re.search(r"\b([a-z])\s*(?:->|tends|approaches|goes)", s).group(1)) if re.search(r"\b([a-z])\s*(?:->|tends|approaches|goes)", s) else X
        if not f.has(x):
            return None
        orig = q.subs(q.vals)
        num, den = sp.fraction(f)
        a0 = a.subs(orig) if a not in (sp.oo, -sp.oo) else a
        zero = False
        if a0 not in (sp.oo, -sp.oo):
            try:
                zero = sp.simplify(num.subs(orig).subs(x, a0)) == 0 and sp.simplify(den.subs(orig).subs(x, a0)) == 0
            except Exception:                                                # noqa: BLE001
                zero = False
        point_slots = q.slot_symbols(a) if a not in (sp.oo, -sp.oo) else []
        return Spec(f=f, x=x, a=a, num=num, den=den, zero=zero, point=point_slots, inside=q.slot_symbols(f),
                    square=bool(a0 not in (sp.oo, -sp.oo) and a0.is_Integer and a0 > 0 and sp.sqrt(a0).is_Integer and
                                any(isinstance(g, sp.Pow) and g.exp == sp.Rational(1, 2) for g in sp.preorder_traversal(f))))

    def solve(self, q: Question, spec: Spec, vals, full: bool = True) -> Optional[Item]:
        sub = q.subs(vals)
        f, x = spec.f.subs(sub), spec.x
        a = spec.a.subs(sub) if spec.a not in (sp.oo, -sp.oo) else spec.a
        try:
            L = sp.limit(f, x, a)
        except Exception:                                                    # noqa: BLE001
            return None
        if L.has(sp.oo, -sp.oo, sp.zoo, sp.nan) or not L.is_real or isinstance(L, sp.Limit):
            return None
        L = exact(L)
        if a not in (sp.oo, -sp.oo):                                         # independent check: close to the point
            try:
                near = complex(f.subs(x, a + sp.Rational(1, 10 ** 7)).evalf())
                if abs(near - complex(L.evalf())) > 1e-4 * max(1, abs(complex(L.evalf()))):
                    return None
            except Exception:                                                # noqa: BLE001
                pass
        text = q.render(vals)
        if not full:
            return Item(text, fnum(L), [], [], self.kind, value=L)
        num, den = sp.fraction(f)
        steps: List[str] = []
        if a in (sp.oo, -sp.oo):
            steps.append("Divide every term by the highest power of x; every term with x underneath goes to 0.")
        elif spec.zero:
            if has_root(f):
                c = sp.simplify(f)
                steps.append(f"Putting x = {fnum(a)} gives 0/0. Multiply top and bottom by the conjugate and cancel: "
                             f"for x ≠ {fnum(a)} it equals {fmt_expr(c)}.")
            elif f.has(sp.sin, sp.cos, sp.tan, sp.exp, sp.log):
                steps.append("Putting x = 0 gives 0/0. Use the standard limits sin(u)/u → 1 and (e^u - 1)/u → 1 as u → 0.")
            else:
                c = sp.cancel(f)
                steps.append(f"Putting x = {fnum(a)} gives 0/0, so factorise and cancel: {fmt_expr(sp.factor(num))} over {fmt_expr(sp.factor(den))}.")
                steps.append(f"For x ≠ {fnum(a)} it equals {fmt_expr(c)}.")
        else:
            steps.append(f"The expression is defined at x = {fnum(a)}, so substitute x = {fnum(a)}.")
        steps.append(f"The limit is {fnum(L)}")
        extra = []
        if a in (sp.oo, -sp.oo):
            try:
                n0, d0 = num.subs(x, 0), den.subs(x, 0)
                extra += [n0 / d0 if d0 else None, 1 / L if L else None, sp.Integer(0), sp.Poly(num, x).LC()]
            except Exception:                                                # noqa: BLE001
                pass
        else:
            extra += [a, 2 * L, sp.Integer(0), L + 1, L - 1]
            if L.q != 1:
                extra.insert(0, 1 / L)
        extra = [e for e in extra if e is not None and sp.sympify(e).is_real]
        return Item(text, fnum(L), steps, numeric_wrong(L, fnum, extra), self.kind, value=L)

    def vary(self, q: Question, spec: Spec, rng: random.Random):
        vals = vary_slots(q, spec.inside + spec.point, rng)
        if spec.zero and spec.point:
            p = spec.point[0]
            if spec.square:
                vals[p] = Fraction(rng.choice([4, 9, 16, 25, 36, 49, 64, 81, 100]))
            orig = q.subs(q.vals)
            for part in (spec.num, spec.den):
                cands = [i for i in q.slot_symbols(part) if q.slots[i].role not in ("exp",) and i != p]
                if not cands:
                    continue
                # the slot nearest the end that is a plain constant of this part
                cands.sort(key=lambda i: (sp.expand(part).coeff(q.S[i]).has(spec.x), -i))
                cond = part.subs(spec.x, spec.a)
                if sp.simplify(cond.subs(q.subs(vals))) == 0:
                    continue                                     # already 0 there (sin(kx) at 0)
                v = back_solve(q, cond, cands[0], vals)
                if v is None or (q.slots[cands[0]].is_int and v.denominator != 1) or v == 0:
                    return None
                vals[cands[0]] = v
            del orig
        return vals
