"""
CUSTOM-SQE algebra families:
  - expanding and simplifying (including algebraic fractions);
  - factorising, partial fractions, the remainder and factor theorems, substituting values;
  - quadratic features (discriminant and nature of the roots, completing the square, sum and product of roots);
  - indices, surds and logarithms.

Versions keep the structure that makes the question work:
  - a factorisable quadratic stays factorisable and a cancelling fraction still cancels;
  - 27^(2/3) gets another perfect cube, √50 + √18 other multiples of one surd, log 8 + log 5 - log 4 another
    power of 10.
"""
from __future__ import annotations

import math
import random
import re
from fractions import Fraction
from typing import List, Optional

import sympy as sp

from .core import Family, Item, Spec, expr_wrong, keep_roots, like, numeric_wrong, same_expr, varying, vary_slots
from .text import Question, exact, fmt_expr, fmt_num, frac, split_relation, to_expr

fnum = lambda v: fmt_num(v, fractions=True)
X = sp.Symbol("x")


def after(sym: str, words: str) -> Optional[str]:
    """The maths after a command word ("Expand (x + 3)(x - 5)" -> "(x + 3)(x - 5)")."""
    m = re.search(rf"\b(?:{words})(?![A-Za-z])\s*(?:completely\s+|fully\s+|and\s+simplify\s+|the\s+expression\s+)?:?\s*(.+)", sym, re.I)
    if not m:
        return None
    t = m.group(1)
    t = re.split(r"\s+(?:in\s+partial|into\s+partial|in\s+the\s+form|giving|leaving|is\s+divided|hence|and\s+hence|"
                 r"when\b|if\b|where\b|correct|and\s+state|,\s*giving)\b|[?;]|\.\s|\.$", t, flags=re.I)[0]
    return t.strip().rstrip(".")


def var_in(e) -> sp.Symbol:
    syms = sorted((s for s in e.free_symbols if not re.fullmatch(r"S\d+", s.name)), key=lambda s: s.name)
    return sp.Symbol("x") if sp.Symbol("x") in syms else (syms[0] if syms else X)


# ══ expand / simplify / factorise ═══════════════════════════════════════════════════════════════════════════

class Manipulate(Family):
    name = "algebra"
    kind = "algebra"

    def parse(self, q: Question) -> Optional[Spec]:
        low = q.low
        task = ("partial" if re.search(r"partial\s+fraction", low) else
                "factorise" if re.search(r"\bfactori[sz]e|\bfactor\s+(?:completely|fully)", low) else
                "expand" if re.search(r"\bexpand\b|multiply\s+out|remove\s+the\s+brackets", low) else
                "simplify" if re.search(r"\bsimplify\b", low) and not re.search(r"\blog|\bsqrt|√|\^\s*\(?-?\d+/|\bdeg|sin|cos|tan|i\b", low) else
                None)
        if task is None:
            return None
        body = after(q.sym, {"partial": r"express|resolve|decompose|write|split|put", "factorise": r"factori[sz]e|factor",
                             "expand": r"expand|multiply\s+out|remove\s+the\s+brackets(?:\s+(?:from|in))?",
                             "simplify": r"simplify"}[task])
        if not body or "=" in body:
            return None
        e = to_expr(body)
        if e is None or not e.free_symbols - set(q.S):
            return None
        x = var_in(e)
        orig = q.subs(q.vals)
        eo = e.subs(orig)
        polys, num, den = [], None, None
        if task in ("simplify", "partial"):
            num, den = sp.fraction(sp.together(e))
            if den.has(x):
                polys = [num, den]
        if task == "factorise":
            polys = [e]
        if task == "simplify" and polys:
            try:
                if sp.cancel(eo) == eo or sp.degree(sp.cancel(eo).as_numer_denom()[1], x) == sp.degree(den.subs(orig), x):
                    pass
            except Exception:                                                # noqa: BLE001
                pass
        return Spec(e=e, task=task, x=x, polys=polys, inside=q.slot_symbols(e))

    def solve(self, q, spec, vals, full=True):
        sub = q.subs(vals)
        e, x = spec.e.subs(sub), spec.x
        text = q.render(vals)
        if spec.task == "expand":
            r = sp.expand(e)
        elif spec.task == "factorise":
            r = sp.factor(e)
            if r == sp.expand(e) or not isinstance(r, (sp.Mul, sp.Pow)):
                return None
        elif spec.task == "partial":
            r = sp.apart(sp.together(e), x)
            if r == sp.together(e) or not r.is_Add:
                return None
        else:
            r = sp.cancel(sp.together(e)) if spec.polys else sp.expand(e)
            if spec.polys:
                r = sp.factor(r)
                n0, d0 = sp.fraction(sp.together(e))
                if sp.degree(sp.fraction(r)[1], x) >= sp.degree(d0, x):     # nothing cancelled: not a version
                    return None
        if not same_expr(r, e):
            return None
        ans = fmt_expr(r)
        if not full:
            return Item(text, ans, [], [], self.kind)
        steps = self._steps(e, r, x, spec.task)
        cands = []
        ex = sp.expand(e)
        terms = sp.Add.make_args(ex)
        if spec.task == "expand":
            cands += [ex - 2 * t for t in terms[1:3]]
            base = sp.factor(e)
            if isinstance(e, sp.Pow) and e.base.is_Add:
                cands.append(sum(a ** e.exp for a in sp.Add.make_args(e.base)))          # (a + b)^2 = a^2 + b^2
            cands += [ex + terms[-1], sp.expand(ex * 2) if len(terms) == 1 else None]
        elif spec.task == "factorise":
            for f in sp.Mul.make_args(r):
                if isinstance(f, sp.Add) and f.has(x):
                    c = f.subs(x, 0)
                    if c != 0:
                        cands.append(r.xreplace({f: f - 2 * c}))
            cands.append(-r)
        else:
            cands += [r + 1, r * 2, -r, ex - 2 * terms[0] if len(terms) > 1 else None]
            if spec.task == "partial":
                parts = sp.Add.make_args(r)
                if len(parts) == 2:
                    a, b = parts
                    na, da = sp.fraction(a)
                    nb, db = sp.fraction(b)
                    cands += [nb / da + na / db, -na / da + nb / db, na / da - nb / db]
        fmt_like = (lambda z: fmt_expr(sp.factor(z))) if spec.task == "factorise" else \
                   (lambda z: fmt_expr(sp.expand(z))) if spec.task == "expand" else fmt_expr
        return Item(text, ans, steps, expr_wrong(r, cands, fmt_like), self.kind)

    def _steps(self, e, r, x, task) -> List[str]:
        if task == "expand":
            return ["Multiply every term in the first bracket by every term in the next, then collect like terms.",
                    f"So {fmt_expr(e)} = {fmt_expr(r)}"]
        if task == "factorise":
            out = []
            c = sp.Poly(sp.expand(e), x).content() if sp.expand(e).is_polynomial(x) else 1
            if c != 1:
                out.append(f"Take out the common factor {fnum(c)} first.")
            out.append("Find the factors (try values of x that make it 0, or split the middle term).")
            out.append(f"So {fmt_expr(e)} = {fmt_expr(r)}")
            out.append("Check: multiplying the brackets out gives back the original.")
            return out
        if task == "partial":
            return ["Write it as A/(first factor) + B/(second factor).",
                    "Multiply through by the denominator, then put in the x-values that make each factor 0 to find A and B.",
                    f"So it equals {fmt_expr(r)}"]
        num, den = sp.fraction(sp.together(e))
        if den.has(x):
            return [f"Factorise the top and the bottom: {fmt_expr(sp.factor(num))} over {fmt_expr(sp.factor(den))}.",
                    "Cancel the common factor.", f"So it simplifies to {fmt_expr(r)}"]
        return ["Expand the brackets (watch the signs), then collect like terms.", f"So it simplifies to {fmt_expr(r)}"]

    def vary(self, q, spec, rng):
        if spec.polys and spec.task in ("factorise", "simplify"):
            for _ in range(3):
                v = keep_roots(q, spec.polys, spec.x, rng, free=spec.inside)
                if v is not None:
                    return v
            return None
        if spec.task == "partial" and spec.polys:
            return self._partial(q, spec, rng)
        return vary_slots(q, spec.inside, rng)

    def _partial(self, q, spec, rng):
        """New factors underneath, then whole numbers A and B: the top is set to A(x + b) + B(x + a)."""
        x = spec.x
        num, den = spec.polys
        vals = vary_slots(q, q.slot_symbols(den), rng)
        sub = q.subs(vals)
        d = sp.factor(den.subs(sub))
        lin = [f for f in sp.Mul.make_args(d) if f.has(x)]
        if len(lin) != 2 or any(sp.degree(f, x) != 1 for f in lin):
            return None
        orig = sp.apart(sp.together(spec.e.subs(q.subs(q.vals))), x)
        old = [sp.fraction(t)[0] for t in sp.Add.make_args(orig)]
        A, B = [sp.Integer(rng.choice([-1, 1]) * rng.randint(1, max(5, int(abs(o)) + 3)) if o.is_number and o < 0
                           else rng.randint(1, max(5, int(abs(o)) + 3))) for o in (old + [1, 1])[:2]]
        target = sp.expand(A * lin[1] + B * lin[0])
        ns = q.slot_symbols(num)
        if not ns:
            return None
        known = {q.S[k]: sp.Rational(frac(vals[k]).numerator, frac(vals[k]).denominator) for k in range(len(vals)) if k not in ns}
        try:
            sol = sp.solve(sp.Poly(sp.expand(num.subs(known) - target), x).all_coeffs(), [q.S[i] for i in ns], dict=True)
        except Exception:                                                    # noqa: BLE001
            return None
        if len(sol) != 1:
            return None
        for i in ns:
            v = exact(sol[0].get(q.S[i], sp.nan))
            if not v.is_Integer or v == 0:
                return None
            vals[i] = Fraction(int(v))
        return vals

    def nice(self, base, item):
        if base.answer and "/" not in base.answer and "/" in item.answer and self.name == "algebra":
            return False
        if base.answer and re.search(r"/\(\d", item.answer) and not re.search(r"/\(\d", base.answer):
            return False                                                     # 25/(3(x + 7)): fractions inside
        return True


# ══ remainder / factor theorem / substitution ════════════════════════════════════════════════════════════════

class Theorems(Family):
    name = "algebra_theorems"
    kind = "algebra"

    def parse(self, q: Question) -> Optional[Spec]:
        low, sym = q.low, q.sym
        if re.search(r"\bremainder\b", low):
            m = re.search(r"\bwhen\s+(.+?)\s+is\s+divided\s+by\s+(.+?)\s*$", sym.rstrip(".?"), re.I)
            if not m:
                return None
            P, D = to_expr(m.group(1)), to_expr(m.group(2))
            if P is None or D is None:
                return None
            x = var_in(P)
            return Spec(task="remainder", P=P, D=D, x=x, inside=q.slot_symbols([P, D]))
        if re.search(r"\bis\s+a\s+factor\b|\bfactor\s+of\b", low):
            m = re.search(r"\(?([a-z]\s*[-+]\s*\(S\d+\))\)?\s+is\s+a\s+factor\s+of\s+(.+?)(?:\s+and\b|\s*,|\.|$)", sym, re.I)
            if not m:
                return None
            D, P = to_expr(m.group(1)), to_expr(m.group(2))
            if P is None or D is None:
                return None
            x = var_in(P)
            return Spec(task="factor", P=P, D=D, x=x, inside=q.slot_symbols([P, D]))
        m = re.search(r"\b(?:evaluate|find\s+the\s+value\s+of|calculate|work\s+out|what\s+is)\s+(.+?)\s*,?\s*(?:when|if|where|given\s+that)\s+(.+)$", sym, re.I) or \
            re.search(r"\b(?:if|when|given\s+that)\s+(.+?)\s*,\s*(?:evaluate|find|calculate|work\s+out)\s+(?:the\s+value\s+of\s+)?(.+)$", sym, re.I)
        if m:
            a, b = m.group(1), m.group(2)
            if re.match(r"\s*[a-z]\s*=", a):                                # "If p = 3 and q = -1, evaluate …"
                a, b = b, a
            assigns = re.findall(r"\b([a-z])\s*=\s*(\(S\d+\)|-?\d+(?:\.\d+)?)", b)
            e = to_expr(a.strip().rstrip("?."))
            if not assigns or e is None:
                return None
            env = {sp.Symbol(k): to_expr(v) for k, v in assigns}
            if not e.free_symbols - set(q.S) <= set(env):
                return None
            return Spec(task="evaluate", e=e, env=env, inside=q.slot_symbols([e] + list(env.values())))
        return None

    def solve(self, q, spec, vals, full=True):
        sub = q.subs(vals)
        text = q.render(vals)
        if spec.task == "evaluate":
            e = spec.e.subs(sub)
            env = {k: v.subs(sub) for k, v in spec.env.items()}
            val = exact(e.subs(env))
            if not val.is_Rational:
                return None
            ans = fnum(val)
            if not full:
                return Item(text, ans, [], [], self.kind, value=val)
            steps = ["Put the values in: " + ", ".join(f"{k} = {fnum(v)}" for k, v in env.items()) + ".",
                     f"{fmt_expr(e)} = {fnum(val)}", "Brackets round negative numbers keep the signs right."]
            wrong_vals = []
            for k, v in env.items():
                wrong_vals.append(e.subs({**env, k: -v}))                                  # a sign slip
            terms = sp.Add.make_args(e)
            if len(terms) > 1:
                wrong_vals.append(sum(abs(t.subs(env)) for t in terms))
            return Item(text, ans, steps, numeric_wrong(val, fnum, wrong_vals), self.kind, value=val)
        P, D, x = spec.P.subs(sub), spec.D.subs(sub), spec.x
        a = sp.solve(D, x)
        if len(a) != 1:
            return None
        a = a[0]
        rem = exact(P.subs(x, a))
        if spec.task == "remainder":
            ans = fnum(rem)
            if not full:
                return Item(text, ans, [], [], self.kind, value=rem)
            steps = [f"Remainder theorem: the remainder on dividing by {fmt_expr(D)} is P({fnum(a)}).",
                     f"P({fnum(a)}) = {fnum(rem)}"]
            return Item(text, ans, steps, numeric_wrong(rem, fnum, [P.subs(x, -a), P.subs(x, 0), sp.LC(sp.Poly(P, x))]), self.kind, value=rem)
        if rem != 0:
            return None
        r = sp.factor(P)
        lin = [f for f in sp.Mul.make_args(r) for _ in range(1) if isinstance(f, (sp.Add, sp.Pow))]
        ans = fmt_expr(r)
        if not full:
            return Item(text, ans, [], [], self.kind)
        steps = [f"Factor theorem: P({fnum(a)}) = 0, so {fmt_expr(D)} is a factor.",
                 f"Divide P(x) by {fmt_expr(D)} to get the quadratic, then factorise it.", f"So P(x) = {ans}"]
        cands = []
        for f in sp.Mul.make_args(r):
            if isinstance(f, sp.Add):
                c = f.subs(x, 0)
                if c != 0:
                    cands.append(r.xreplace({f: f - 2 * c}))
        return Item(text, ans, steps, expr_wrong(r, cands + [-r], lambda z: fmt_expr(sp.factor(z))), self.kind)

    def vary(self, q, spec, rng):
        if spec.task == "factor":
            for _ in range(3):
                v = keep_roots(q, [spec.P, spec.D], spec.x, rng, free=spec.inside)
                if v is not None:
                    return v
            return None
        return vary_slots(q, spec.inside, rng, flip=0.0)


# ══ quadratic features ══════════════════════════════════════════════════════════════════════════════════════

class Quadratic(Family):
    name = "quadratic_features"
    kind = "algebra"

    def parse(self, q: Question) -> Optional[Spec]:
        low = q.low
        task = ("nature" if re.search(r"discriminant|nature\s+of\s+(?:the|its)\s+roots", low) else
                "sumprod" if re.search(r"sum\s+and\s+(?:the\s+)?product|α\s*\+\s*β|alpha\s*\+\s*beta|sum\s+of\s+the\s+roots", low) else
                "square" if re.search(r"complet\w*\s+the\s+square", low) and "=" not in q.sym else None)
        if not task:
            return None
        m = re.search(r"((?:\(S\d+\))?[a-z]\^\(S\d+\)[^=,]*?)(?:\s*=\s*\(S\d+\)|\s+and\b|\s*,|\s*$|\.|\?)", q.sym)
        if not m:
            return None
        e = to_expr(m.group(1))
        if e is None:
            return None
        x = var_in(e)
        try:
            if sp.Poly(e.subs(q.subs(q.vals)), x).degree() != 2:
                return None
        except Exception:                                                    # noqa: BLE001
            return None
        return Spec(task=task, e=e, x=x, inside=q.slot_symbols(e))

    def solve(self, q, spec, vals, full=True):
        e, x = sp.expand(spec.e.subs(q.subs(vals))), spec.x
        a, b, c = sp.Poly(e, x).all_coeffs()
        text = q.render(vals)
        if spec.task == "nature":
            d = b ** 2 - 4 * a * c
            kind = ("two distinct real roots" if d > 0 and sp.sqrt(d).is_Rational is False else
                    "two distinct real (rational) roots" if d > 0 else "two equal (repeated) real roots" if d == 0 else "no real roots")
            ans = f"b^2 - 4ac = {fnum(d)}: {kind}"
            if not full:
                return Item(text, ans, [], [], self.kind, value=(sp.sign(d),))
            steps = [f"a = {fnum(a)}, b = {fnum(b)}, c = {fnum(c)}", f"b^2 - 4ac = {fnum(b ** 2)} - {fnum(4 * a * c)} = {fnum(d)}",
                     "Positive: two different real roots; zero: two equal roots; negative: no real roots."]
            alts = [b ** 2 + 4 * a * c, -b ** 2 - 4 * a * c, b - 4 * a * c]
            wrong = []
            for dd in alts:
                k2 = "two distinct real roots" if dd > 0 else "two equal (repeated) real roots" if dd == 0 else "no real roots"
                w = f"b^2 - 4ac = {fnum(dd)}: {k2}"
                if w != ans and w not in wrong:
                    wrong.append(w)
            other = {"two distinct real roots": "no real roots", "no real roots": "two distinct real roots"}.get(kind, "two distinct real roots")
            wrong.append(f"b^2 - 4ac = {fnum(d)}: {other}")
            return Item(text, ans, steps, wrong, self.kind, value=(sp.sign(d),))
        if spec.task == "sumprod":
            s, p = exact(-b / a), exact(c / a)
            ans = f"sum = {fnum(s)}, product = {fnum(p)}"
            if not full:
                return Item(text, ans, [], [], self.kind, value=(s, p))
            steps = [f"a = {fnum(a)}, b = {fnum(b)}, c = {fnum(c)}", f"Sum of roots = -b/a = {fnum(s)}", f"Product of roots = c/a = {fnum(p)}"]
            wrong = [f"sum = {fnum(-s)}, product = {fnum(p)}", f"sum = {fnum(s)}, product = {fnum(-p)}",
                     f"sum = {fnum(exact(b / a))}, product = {fnum(exact(a / c))}", f"sum = {fnum(p)}, product = {fnum(s)}"]
            return Item(text, ans, steps, [w for w in wrong if w != ans], self.kind, value=(s, p))
        h = exact(b / (2 * a))
        k = exact(c - b ** 2 / (4 * a))
        form = (f"{fnum(a)}" if a != 1 else "") + f"(x + {fnum(h)})^2".replace("+ -", "- ") + (f" + {fnum(k)}" if k >= 0 else f" - {fnum(-k)}")
        if not full:
            return Item(text, form, [], [], self.kind, value=(h, k))
        steps = [f"Halve the coefficient of x: {fnum(b / a)}/2 = {fnum(h)}.", f"x^2 + {fnum(b / a)}x = (x + {fnum(h)})^2 - {fnum(h ** 2)}".replace("+ -", "- "),
                 f"So the expression = {form}"]
        wrong = []
        for hh, kk in ((h, -k), (-h, k), (h, c + h ** 2), (2 * h, c - 4 * h ** 2)):
            w = (f"{fnum(a)}" if a != 1 else "") + f"(x + {fnum(hh)})^2".replace("+ -", "- ") + (f" + {fnum(kk)}" if kk >= 0 else f" - {fnum(-kk)}")
            if w != form and w not in wrong:
                wrong.append(w)
        return Item(text, form, steps, wrong, self.kind, value=(h, k))

    def vary(self, q, spec, rng):
        if spec.task == "nature":
            orig = q.subs(q.vals)
            e0 = sp.expand(spec.e.subs(orig))
            a, b, c = sp.Poly(e0, spec.x).all_coeffs()
            if b ** 2 - 4 * a * c == 0:                                     # equal roots stay equal
                return keep_roots(q, [spec.e], spec.x, rng, free=spec.inside)
        return vary_slots(q, spec.inside, rng)

    def nice(self, base, item):
        if self.name and base.value and item.value and len(base.value) == 1:
            return base.value == item.value                                  # the same kind of roots
        return like(item.value, base.value)


# ══ indices, surds, logarithms ═══════════════════════════════════════════════════════════════════════════════

_SQUAREFREE = [2, 3, 5, 6, 7, 10, 11]


class Powers(Family):
    """2^5 × 2^3 ÷ 2^4; 27^(2/3); (8x^6)^(1/3); √50 + √18; 6/(√3 - 1); log base 2 of 64; log 8 + log 5 - log 4."""
    name = "indices"
    kind = "indices"

    def parse(self, q: Question) -> Optional[Spec]:
        low, sym = q.low, q.sym
        if "=" in sym and not re.search(r"\bwhen\b", low):
            return None
        m = re.search(r"\blog\s*(?:base\s*\(S\d+\)\s*(?:of\s*)?|_\s*\(S\d+\)\s*)\(?(\(S\d+\))\)?", sym)
        if m and re.search(r"\bevaluate|\bfind|\bwhat|\bcalculate|\bsimplify", low):
            bm = re.search(r"\blog\s*(?:base\s*|_\s*)(\(S\d+\))", sym)
            return Spec(task="logval", base=int(bm.group(1)[2:-1]), arg=int(m.group(1)[2:-1]))
        if re.search(r"\blog\b", low) and re.search(r"simplify|evaluate|without", low):
            terms = re.findall(r"([+-]?)\s*(\(S\d+\))?\s*log\s*\(?(\(S\d+\))\)?", sym)
            if len(terms) >= 2:
                return Spec(task="logsum", terms=[(t[0] or "+", int(t[2][2:-1]), int(t[1][2:-1]) if t[1] else None) for t in terms])
        body = after(sym, r"simplify|evaluate|rationali[sz]e(?:\s+the\s+denominator\s+of)?|find\s+the\s+value\s+of|calculate|work\s+out|what\s+is")
        if not body:
            return None
        body = re.sub(r"^\s*(?:the\s+denominator\s+of)\s+", "", body, flags=re.I)
        e = to_expr(body)
        if e is None or e.free_symbols - set(q.S) - {sp.Symbol("x"), sp.Symbol("a"), sp.Symbol("y")}:
            return None
        orig = q.subs(q.vals)
        eo = e.subs(orig)
        if e.has(sp.sin, sp.cos, sp.tan, sp.sec, sp.csc, sp.cot, sp.log, sp.exp):
            return None                                     # trig identities and logs aren't index laws
        has_root = any(isinstance(g, sp.Pow) and g.exp.is_Rational and g.exp.q != 1 for g in sp.preorder_traversal(e.subs(orig, evaluate=False)))
        if re.search(r"√|sqrt", q.display + q.sym):
            task = "surd"
        elif has_root or re.search(r"\^\s*\(\(S\d+\)\s*/\s*\(S\d+\)\)", sym):
            task = "fracpow"
        elif re.search(r"\^", sym):
            task = "laws"
        else:
            return None
        return Spec(task=task, e=e, inside=q.slot_symbols(e))

    def solve(self, q, spec, vals, full=True):
        text = q.render(vals)
        V = lambda i: exact(sp.Rational(Fraction(vals[i]).numerator, Fraction(vals[i]).denominator))
        if spec.task == "logval":
            b, a = V(spec.base), V(spec.arg)
            if b <= 1 or a <= 0:
                return None
            r = sp.log(a, b)
            r = exact(sp.simplify(r))
            if not r.is_Rational:
                return None
            ans = fnum(r)
            if not full:
                return Item(text, ans, [], [], self.kind, value=r)
            steps = [f"log base {fnum(b)} of {fnum(a)} = k means {fnum(b)}^k = {fnum(a)}.", f"{fnum(b)}^{fnum(r)} = {fnum(a)}, so k = {fnum(r)}"]
            return Item(text, ans, steps, numeric_wrong(r, fnum, [a / b, a * b, r + 1, b ** 2]), self.kind, value=r)
        if spec.task == "logsum":
            tot = sp.Integer(0)
            prod = sp.Integer(1)
            for sign, i, c in spec.terms:
                k = V(c) if c is not None else 1
                prod *= V(i) ** (k if sign != "-" else -k)
            r = exact(sp.log(prod, 10))
            r = exact(sp.simplify(r))
            if not r.is_Rational:
                return None
            ans = fnum(r)
            if not full:
                return Item(text, ans, [], [], self.kind, value=r)
            steps = ["log a + log b = log(ab) and log a - log b = log(a/b).", f"So it is log {fnum(prod)} = {fnum(r)}"]
            return Item(text, ans, steps, numeric_wrong(r, fnum, [prod, r + 1, 10 * r]), self.kind, value=r)
        e = spec.e.subs(q.subs(vals))
        if spec.task == "surd":
            r = sp.radsimp(e) if e.has(sp.Pow) else e
            r = sp.simplify(r)
        else:                                               # letters taken as positive: (27x^9)^(1/3) = 3x^3
            pos = {s: sp.Symbol(s.name, positive=True) for s in e.free_symbols}
            r = sp.simplify(sp.powdenest(sp.powsimp(sp.expand_power_base(e.subs(pos), force=True), force=True), force=True))
            r = r.subs({v: k for k, v in pos.items()})
        if r.has(sp.Float):
            return None
        ans = fmt_expr(r)
        if not full:
            return Item(text, ans, [], [], self.kind, value=r if r.is_number else None)
        if spec.task == "laws":
            steps = ["Multiplying: add the powers; dividing: subtract them; a power of a power: multiply them.", f"So it equals {ans}"]
        elif spec.task == "fracpow":
            steps = ["a^(m/n) means the nth root of a, raised to the power m: take the root first.", f"So it equals {ans}"]
        else:
            steps = ["Write each surd as (a square) × (what's left): √(a²b) = a√b.",
                     "To rationalise, multiply top and bottom by the conjugate of the bottom.", f"So it equals {ans}"]
        cands = [r * 2, r + 1, -r, r / 2]
        if r.is_number and r.is_Integer:
            return Item(text, ans, steps, numeric_wrong(r, fnum, cands), self.kind, value=r)
        return Item(text, ans, steps, expr_wrong(r, cands, fmt_expr), self.kind, value=r if r.is_number else None)

    def vary(self, q, spec, rng):
        vals = list(q.vals)
        V = lambda i: q.vals[i]
        if spec.task == "logval":
            b = int(V(spec.base))
            k0 = sp.log(V(spec.arg), b)
            k0 = int(k0) if exact(k0).is_Integer else 3
            k = rng.choice([v for v in range(2, 8) if v != k0] or [k0 + 1])
            vals[spec.arg] = Fraction(b ** k)
            return vals
        if spec.task == "logsum":
            ids = [i for _, i, _ in spec.terms]
            signs = [s for s, _, _ in spec.terms]
            for _ in range(20):
                new = [new_int(int(V(i)), rng) for i in ids[:-1]]
                prod = Fraction(1)
                for s, v in zip(signs[:-1], new):
                    prod *= v if s != "-" else Fraction(1, v)
                target = 10 ** rng.choice([1, 2]) if sp.log(abs(prod), 10) < 3 else 10 ** 3
                last = Fraction(target) / prod if signs[-1] != "-" else prod / target
                if last.denominator == 1 and 1 < last < 1000:
                    for i, v in zip(ids, new + [last]):
                        vals[i] = Fraction(v)
                    return vals
            return None
        if spec.task == "fracpow":
            return self._fracpow(q, spec, rng)
        if spec.task == "surd":
            return self._surds(q, spec, rng)
        if spec.task == "laws":
            exps = [i for i in spec.inside if q.slots[i].role == "exp"]
            for i in exps:
                vals[i] = Fraction(max(1, int(V(i)) + rng.randint(-2, 3)))
            return vals
        return vary_slots(q, spec.inside, rng)

    def _fracpow(self, q, spec, rng):
        """27^(2/3): a new base that is a perfect power of the root (k^3), maybe a new top power; the root stays.
        (8x^6)^(1/3): the number a perfect cube, the power of x a multiple of 3."""
        vals = list(q.vals)
        for g in sp.preorder_traversal(spec.e):
            if not (isinstance(g, sp.Pow) and g.exp.has(*q.S)):
                continue
            top_e, bot_e = sp.fraction(g.exp)
            bots = q.slot_symbols(bot_e)
            if not bots:
                continue
            nroot = int(q.vals[bots[0]])
            if nroot < 2:
                continue
            tops = [i for i in q.slot_symbols(top_e) if q.vals[i] > 1]
            for i in q.slot_symbols(g.base):
                s = q.slots[i]
                if s.role == "exp":
                    vals[i] = Fraction(nroot * rng.randint(1, 4))
                else:
                    vals[i] = Fraction(rng.choice([k for k in range(2, 6) if k ** nroot != q.vals[i]]) ** nroot)
            if tops and rng.random() < 0.5:
                vals[tops[0]] = Fraction(rng.choice([k for k in range(2, nroot + 2) if math.gcd(k, nroot) == 1] or [1]))
            return vals
        return None

    def _surds(self, q, spec, rng):
        """√50 + √18 -> √(a²s) ± √(b²s). n/(√s - c) -> numbers that still rationalise to whole numbers:
        s stays squarefree and n is a multiple of s - c²."""
        vals = list(q.vals)
        roots = []
        for g in sp.preorder_traversal(spec.e):
            if isinstance(g, sp.Pow) and g.exp == sp.Rational(1, 2) and q.slot_symbols(g.base):
                roots.append(q.slot_symbols(g.base)[0])
        if len(roots) >= 2:
            s = rng.choice(_SQUAREFREE[:5])
            ks = rng.sample(range(2, 7), len(roots))        # different multiples: √108 + √12, not √150 + √150
            if "-" in q.display and ks[0] < ks[1]:
                ks[0], ks[1] = ks[1], ks[0]                 # √75 - √27 stays positive
            for i, k in zip(roots, ks):
                vals[i] = Fraction(k ** 2 * s)
            return vals
        if len(roots) == 1:
            num, den = sp.fraction(spec.e)
            rs = roots[0]
            others = [i for i in q.slot_symbols(den) if i != rs]
            tops = q.slot_symbols(num)
            for _ in range(20):
                s = rng.choice(_SQUAREFREE)
                vals[rs] = Fraction(s)
                c = 0
                for i in others:
                    c = rng.randint(1, 4) * (-1 if q.vals[i] < 0 else 1)
                    vals[i] = Fraction(c)
                diff = s - c * c
                old_diff = q.vals[rs] - sum(q.vals[i] ** 2 for i in others)
                if diff == 0 or not tops or (diff > 0) != (old_diff > 0):
                    continue
                vals[tops[0]] = Fraction(abs(diff) * rng.randint(1, 4))
                return vals
        return vary_slots(q, spec.inside, rng)

    def nice(self, base, item):
        if base.value is None or item.value is None:
            return True
        b, v = exact(base.value), exact(item.value)
        if b.is_Integer:
            return v.is_Integer and abs(v) <= max(10 ** 4, 50 * abs(b))
        return like(v, b)


def new_int(a: int, rng: random.Random) -> int:
    from .core import similar_int
    return similar_int(a, rng) if a > 1 else rng.randint(2, 9)
