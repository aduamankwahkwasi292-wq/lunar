"""
CUSTOM-SQE sequences and series:
  - arithmetic progressions (a term, a sum, finding a and d from two terms, the nth term);
  - geometric progressions (a term, a sum, the sum to infinity);
  - the binomial expansion and one coefficient in it;
  - Σ sums.

The listed terms stay a real AP or GP: a new first term and difference (or ratio) are chosen, then the terms are
written from them. A sum to infinity keeps a ratio between -1 and 1, and terms that are whole numbers.
"""
from __future__ import annotations

import math
import random
import re
from fractions import Fraction
from typing import List, Optional

import sympy as sp

from .core import Family, Item, Spec, expr_wrong, numeric_wrong, similar_int
from .text import Question, exact, fmt_expr, fmt_num

fnum = lambda v: fmt_num(v, fractions=True)
N = sp.Symbol("n")


def listed(q: Question) -> List[int]:
    """The slots of a listed sequence: '3, 7, 11, ...' or '12 + 6 + 3 + ...' (three or more numbers in a row)."""
    d = q.display
    runs, cur, last_end = [], [], -1
    for s in q.slots:
        if s.role in ("ord",):
            continue
        gap = d[last_end:s.start] if last_end >= 0 else ""
        if cur and (re.fullmatch(r"\s*[,+]\s*", gap) or (s.binary and re.fullmatch(r"\s*", gap))):   # "8 + 4 + 2"
            cur.append(s.i)
        else:
            if len(cur) >= 3:
                runs.append(cur)
            cur = [s.i]
        last_end = s.end
    if len(cur) >= 3:
        runs.append(cur)
    return max(runs, key=len) if runs else []


class Sequence(Family):
    name = "sequence"
    kind = "sequences"

    def parse(self, q: Question) -> Optional[Spec]:
        low = q.low
        terms = listed(q)
        ordinals = [s.i for s in q.slots if s.role == "ord"]
        if re.search(r"\bexpand\b", low) and re.search(r"\)\s*\^\s*\(S\d+\)|\)\s*\^\s*\d", q.sym) and not re.search(r"\(x\s*[+-]", q.sym.replace("(S", "(Z")):
            m = re.search(r"\(\s*(\(S\d+\))?\s*([+-])?\s*(\(S\d+\))?\s*([a-z])\s*\)\s*\^\s*\((S\d+)\)", q.sym)
            if m:
                return Spec(task="binexp", sym=q.sym)
        if re.search(r"coefficient\s+of", low) and re.search(r"expansion", low):
            m = re.search(r"coefficient\s+of\s+([a-z])\^?(\(S\d+\))?.*expansion\s+of\s+(.+)$", q.sym, re.I)
            if m:
                return Spec(task="bincoef", var=m.group(1), k=int(m.group(2)[2:-1]) if m.group(2) else None, body=m.group(3).rstrip(".?"))
        if re.search(r"\bsum\s+of\s+(.+?)\s+from\s+[a-z]\s*=\s*\(S\d+\)\s+to\s+\(S\d+\)", q.sym, re.I) or re.search(r"σ|sigma", low):
            m = re.search(r"\bsum\s+of\s+(.+?)\s+from\s+([a-z])\s*=\s*(\(S\d+\))\s+to\s+(\(S\d+\))", q.sym, re.I)
            if m:
                return Spec(task="sigma", body=m.group(1), var=m.group(2), lo=int(m.group(3)[2:-1]), hi=int(m.group(4)[2:-1]))
        gp = bool(re.search(r"\bg\.?p\b|geometric", low))
        ap = bool(re.search(r"\ba\.?p\b|arithmetic", low))
        if not (gp or ap or terms):
            return None
        if len(terms) >= 3:
            v = [q.vals[i] for i in terms]
            diffs = {v[k + 1] - v[k] for k in range(len(v) - 1)}
            ratios = {v[k + 1] / v[k] for k in range(len(v) - 1)} if all(x != 0 for x in v) else set()
            if gp or (not ap and len(ratios) == 1 and len(diffs) > 1):
                if len(ratios) != 1:
                    return None
                r = ratios.pop()
                task = "gp_inf" if re.search(r"infinity|infinite|\boo\b", low) else "gp_sum" if re.search(r"\bsum\b", low) else "gp_term"
                return Spec(task=task, terms=terms, r=r, n=self._n(q, terms), kind="gp")
            if len(diffs) != 1:
                return None
            task = ("ap_nth" if re.search(r"nth\s+term|n\s*th\s+term|general\s+term|formula\s+for\s+the", low) else
                    "ap_sum" if re.search(r"\bsum\b", low) else "ap_term")
            return Spec(task=task, terms=terms, d=diffs.pop(), n=self._n(q, terms), kind="ap")
        if ap and len(ordinals) >= 2 and re.search(r"first\s+term|common\s+difference", low):
            vals_ = [s.i for s in q.slots if s.role in ("num", "coef") and s.i not in ordinals]
            if len(vals_) >= 2:
                return Spec(task="ap_two", ords=ordinals[:2], vals=vals_[:2], kind="ap")
        return None

    @staticmethod
    def _n(q, terms):
        ords = [s.i for s in q.slots if s.role == "ord"]
        if ords:
            return ords[0]
        m = re.search(r"first\s+(\(S\d+\))\s+terms", q.sym)
        return int(m.group(1)[2:-1]) if m else None

    def solve(self, q, spec, vals, full=True):
        V = [Fraction(v) for v in vals]
        text = q.render(vals)
        t = spec.task
        if t in ("ap_term", "ap_sum", "ap_nth"):
            a, d = V[spec.terms[0]], V[spec.terms[1]] - V[spec.terms[0]]
            if any(V[spec.terms[k + 1]] - V[spec.terms[k]] != d for k in range(len(spec.terms) - 1)):
                return None
            if t == "ap_nth":
                e = sp.expand(sp.Rational(a) + (N - 1) * sp.Rational(d))
                ans = f"{fmt_expr(e)}"
                if not full:
                    return Item(text, ans, [], [], self.kind)
                steps = [f"a = {fnum(a)}, d = {fnum(d)}", f"nth term = a + (n - 1)d = {fnum(a)} + (n - 1)({fnum(d)}) = {ans}"]
                wrong = expr_wrong(e, [sp.Rational(a) + N * sp.Rational(d), sp.Rational(d) * N + sp.Rational(a), sp.Rational(a) * N + sp.Rational(d),
                                       sp.expand(sp.Rational(a) + (N + 1) * sp.Rational(d))], fmt_expr)
                return Item(text, ans, steps, wrong, self.kind)
            if spec.n is None:
                return None
            n = int(V[spec.n])
            if n < 2:
                return None
            if t == "ap_term":
                r = a + (n - 1) * d
                ans = fnum(r)
                if not full:
                    return Item(text, ans, [], [], self.kind, value=sp.Rational(r))
                steps = [f"a = {fnum(a)}, d = {fnum(d)}", f"T{n} = a + (n - 1)d = {fnum(a)} + {n - 1} × {fnum(d)} = {ans}"]
                return Item(text, ans, steps, numeric_wrong(r, fnum, [a + n * d, n * d, a + (n - 2) * d, a * n]), self.kind, value=sp.Rational(r))
            s = Fraction(n, 2) * (2 * a + (n - 1) * d)
            ans = fnum(s)
            if not full:
                return Item(text, ans, [], [], self.kind, value=sp.Rational(s))
            steps = [f"a = {fnum(a)}, d = {fnum(d)}, n = {n}", f"S = n/2 (2a + (n - 1)d) = {n}/2 × ({fnum(2 * a)} + {n - 1} × {fnum(d)}) = {ans}"]
            return Item(text, ans, steps, numeric_wrong(s, fnum, [n * (2 * a + (n - 1) * d), Fraction(n, 2) * (a + (n - 1) * d), a + (n - 1) * d]),
                        self.kind, value=sp.Rational(s))
        if t in ("gp_term", "gp_sum", "gp_inf"):
            a = V[spec.terms[0]]
            r = V[spec.terms[1]] / a if a else None
            if r is None or any(V[spec.terms[k + 1]] != V[spec.terms[k]] * r for k in range(len(spec.terms) - 1)):
                return None
            if t == "gp_inf":
                if not (-1 < r < 1) or r == 0:
                    return None
                s = a / (1 - r)
                ans = fnum(s)
                if not full:
                    return Item(text, ans, [], [], self.kind, value=sp.Rational(s))
                steps = [f"a = {fnum(a)}, r = {fnum(r)} (between -1 and 1, so the sum to infinity exists)", f"S∞ = a/(1 - r) = {fnum(a)}/(1 - {fnum(r)}) = {ans}"]
                return Item(text, ans, steps, numeric_wrong(s, fnum, [a / (1 + r), a * (1 - r), a / r]), self.kind, value=sp.Rational(s))
            if spec.n is None:
                return None
            n = int(V[spec.n])
            if t == "gp_term":
                v = a * r ** (n - 1)
                ans = fnum(v)
                if not full:
                    return Item(text, ans, [], [], self.kind, value=sp.Rational(v))
                steps = [f"a = {fnum(a)}, r = {fnum(r)}", f"T{n} = ar^(n-1) = {fnum(a)} × {fnum(r)}^{n - 1} = {ans}"]
                return Item(text, ans, steps, numeric_wrong(v, fnum, [a * r ** n, a * r * (n - 1), (a * r) ** (n - 1)]), self.kind, value=sp.Rational(v))
            s = a * (r ** n - 1) / (r - 1) if r != 1 else a * n
            ans = fnum(s)
            if not full:
                return Item(text, ans, [], [], self.kind, value=sp.Rational(s))
            steps = [f"a = {fnum(a)}, r = {fnum(r)}, n = {n}", f"S = a(r^n - 1)/(r - 1) = {fnum(a)}({fnum(r)}^{n} - 1)/({fnum(r)} - 1) = {ans}"]
            return Item(text, ans, steps, numeric_wrong(s, fnum, [a * r ** (n - 1), a * (r ** (n + 1) - 1) / (r - 1), a * r ** n]), self.kind, value=sp.Rational(s))
        if t == "ap_two":
            (o1, o2), (v1, v2) = spec.ords, spec.vals
            p, qq = int(V[o1]), int(V[o2])
            x1, x2 = V[v1], V[v2]
            if p == qq:
                return None
            d = (x2 - x1) / (qq - p)
            a = x1 - (p - 1) * d
            ans = f"a = {fnum(a)}, d = {fnum(d)}"
            if not full:
                return Item(text, ans, [], [], self.kind, value=(sp.Rational(a), sp.Rational(d)))
            steps = [f"T{p} = a + {p - 1}d = {fnum(x1)} and T{qq} = a + {qq - 1}d = {fnum(x2)}",
                     f"Subtract: {qq - p}d = {fnum(x2 - x1)}, so d = {fnum(d)}", f"Then a = {fnum(x1)} - {p - 1} × {fnum(d)} = {fnum(a)}"]
            wrong = [f"a = {fnum(x1)}, d = {fnum(d)}", f"a = {fnum(a)}, d = {fnum(x2 - x1)}", f"a = {fnum(a + d)}, d = {fnum(d)}", f"a = {fnum(d)}, d = {fnum(a)}"]
            return Item(text, ans, steps, [w for w in wrong if w != ans], self.kind, value=(sp.Rational(a), sp.Rational(d)))
        if t == "sigma":
            body = sp.sympify(0)
            from .text import to_expr
            e = to_expr(spec.body)
            if e is None:
                return None
            var = sp.Symbol(spec.var)
            e = e.subs(q.subs(vals))
            lo, hi = int(V[spec.lo]), int(V[spec.hi])
            if hi <= lo:
                return None
            s = sp.summation(e, (var, lo, hi))
            ans = fnum(s)
            if not full:
                return Item(text, ans, [], [], self.kind, value=s)
            steps = [f"Add {fmt_expr(e)} for {spec.var} = {lo}, {lo + 1}, …, {hi}."]
            if e == var ** 2:
                steps.append(f"Use Σr² = n(n + 1)(2n + 1)/6 with n = {hi}.")
            elif sp.degree(e, var) == 1:
                steps.append("It's an arithmetic series: sum = (number of terms)/2 × (first + last).")
            steps.append(f"Sum = {ans}")
            return Item(text, ans, steps, numeric_wrong(s, fnum, [s - e.subs(var, hi), s + e.subs(var, hi + 1), e.subs(var, hi)]), self.kind, value=s)
        if t == "binexp":
            from .text import to_expr
            m = re.search(r"(\((?:[^()]|\(S\d+\))*\)\s*\^\s*\(S\d+\))", q.sym)
            if not m:
                return None
            e = to_expr(m.group(1))
            if e is None:
                return None
            r = sp.expand(e.subs(q.subs(vals)))
            ans = fmt_expr(r)
            if not full:
                return Item(text, ans, [], [], self.kind)
            base = e.subs(q.subs(vals))
            steps = ["Use the binomial theorem: (a + b)^n = Σ nCr a^(n-r) b^r, with the coefficients from Pascal's triangle.", f"So it is {ans}"]
            terms = sp.Add.make_args(r)
            cands = [r - terms[1] + terms[1] / 2 if len(terms) > 2 else None, r + terms[-1], sp.expand(r - 2 * terms[1]) if len(terms) > 1 else None]
            return Item(text, ans, steps, expr_wrong(r, cands, fmt_expr), self.kind)
        if t == "bincoef":
            from .text import to_expr
            e = to_expr(spec.body)
            if e is None:
                return None
            e = e.subs(q.subs(vals))
            x = sp.Symbol(spec.var)
            k = int(V[spec.k]) if spec.k is not None else 1
            c = sp.Poly(sp.expand(e), x).coeff_monomial(x ** k)
            ans = fnum(c)
            if not full:
                return Item(text, ans, [], [], self.kind, value=c)
            steps = [f"The term in {spec.var}^{k} is nCr × (first)^(n - r) × (second)^r with r = {k}.", f"Its coefficient is {ans}"]
            return Item(text, ans, steps, numeric_wrong(c, fnum, [sp.Poly(sp.expand(e), x).coeff_monomial(x ** (k + 1)), c / 2, sp.binomial(sp.degree(sp.expand(e), x), k)]),
                        self.kind, value=c)
        return None

    def vary(self, q, spec, rng):
        vals = list(q.vals)
        t = spec.task
        V = [Fraction(v) for v in q.vals]
        if t.startswith("ap") and t != "ap_two":
            a0, d0 = V[spec.terms[0]], V[spec.terms[1]] - V[spec.terms[0]]
            a = Fraction(similar_int(int(abs(a0)), rng) if abs(a0) > 1 else rng.randint(1, 9)) * (1 if a0 >= 0 else -1)
            d = Fraction(rng.randint(2, max(9, int(abs(d0)) + 3))) * (1 if d0 > 0 else -1)
            for k, i in enumerate(spec.terms):
                vals[i] = a + k * d
            if spec.n is not None and t != "ap_nth":
                n0 = int(V[spec.n])
                vals[spec.n] = Fraction(max(4, n0 + rng.randint(-5, 6)))
            return vals
        if t.startswith("gp"):
            a0, r0 = V[spec.terms[0]], V[spec.terms[1]] / V[spec.terms[0]]
            if t == "gp_inf":
                r = rng.choice([Fraction(1, 2), Fraction(1, 3), Fraction(2, 3), Fraction(1, 4), Fraction(3, 4), Fraction(-1, 2), Fraction(1, 5)])
                if (r > 0) != (r0 > 0):
                    r = -r
                den = r.denominator ** (len(spec.terms) - 1)
                a = den * rng.randint(1, max(2, int(abs(a0)) // den + 2))
                for k, i in enumerate(spec.terms):
                    vals[i] = Fraction(a) * r ** k
                return vals
            r = Fraction(rng.choice([2, 3, 4, 5]) * (1 if r0 > 0 else -1)) if r0.denominator == 1 else r0
            a = Fraction(rng.randint(1, max(5, int(abs(a0)) + 2)))
            for k, i in enumerate(spec.terms):
                vals[i] = a * r ** k
            if spec.n is not None:
                n0 = int(V[spec.n])
                vals[spec.n] = Fraction(max(3, min(10, n0 + rng.randint(-2, 3))))
            return vals
        if t == "ap_two":
            (o1, o2), (v1, v2) = spec.ords, spec.vals
            a = rng.randint(1, 12)
            d = rng.randint(2, 7)
            p = rng.randint(2, 5)
            qq = p + rng.randint(2, 6)
            vals[o1], vals[o2] = Fraction(p), Fraction(qq)
            vals[v1], vals[v2] = Fraction(a + (p - 1) * d), Fraction(a + (qq - 1) * d)
            return vals
        if t == "sigma":
            vals[spec.hi] = Fraction(max(int(V[spec.lo]) + 3, int(V[spec.hi]) + rng.randint(-4, 6)))
            return vals
        if t in ("binexp", "bincoef"):
            for s in q.slots:
                if s.role == "exp":
                    vals[s.i] = Fraction(max(3, min(7, int(s.value) + rng.randint(-1, 2))))
                elif s.role in ("num", "coef") and abs(s.value) > 1 and not (t == "bincoef" and spec.k == s.i):
                    vals[s.i] = Fraction(rng.randint(2, 5)) * (1 if s.value > 0 else -1)
            if t == "bincoef" and spec.k is not None:
                deg = max((int(vals[s.i]) for s in q.slots if s.role == "exp"), default=4)
                k0 = int(q.vals[spec.k])
                vals[spec.k] = Fraction(rng.randint(2 if k0 >= 2 else 1, max(2, deg - 1)))
            return vals
        return None

    def nice(self, base, item):
        b, v = base.value, item.value
        if b is None or v is None:
            return True
        if isinstance(b, tuple):
            return all(exact(x).is_Integer for x in v) if all(exact(x).is_Integer for x in b) else True
        b, v = exact(b), exact(v)
        if b.is_Integer:
            return v.is_Integer and abs(v) <= max(10 ** 4, 20 * abs(b))
        return v.is_Rational
