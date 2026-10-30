"""
CUSTOM-SQE equation families: equations (linear, quadratic, higher, with fractions, exponential and log, two or
three unknowns), inequalities (linear, quadratic, double, |x|), and changing the subject of a formula.

New versions are made "answer first":
  - new whole-number roots (or roots like the original's fractions) are chosen;
  - then the constants that give them are solved for;
  - so "2x + 3 = 11" becomes "4x + 5 = 21", never "6x - 16/3 = 0";
  - every root is substituted back as a check.
"""
from __future__ import annotations

import random
import re
from fractions import Fraction
from typing import Dict, List, Optional, Sequence

import sympy as sp

from .core import (Family, Item, Spec, back_solve, keep_roots, like, new_value, numeric_wrong, varying,
                   vary_slots)
from .text import exact, Question, fmt_expr, fmt_num, frac, split_relation, to_expr

fnum = lambda v: fmt_num(v, fractions=True)
_LEAD_WORDS = re.compile(r"^(?:\s*(?:[A-Za-z]{2,}|[,:;]))+\s+(?=[\w(√-])")
_NOT_UNKNOWN = {"e", "E", "pi", "i"}


def strip_words(t: str) -> str:
    """'Solve the simultaneous equations 3x + 2y' -> '3x + 2y' (words in front of the maths)."""
    t = t.strip()
    while True:
        m = re.match(r"^\s*([A-Za-z]{2,}|[,:;])\s*", t)
        if not m or re.match(r"^\s*(?:sin|cos|tan|sec|cot|csc|ln|log|sqrt|exp|pi|theta|Abs)(?![a-z])", t):
            return t.strip()
        t = t[m.end():]


def maths_part(sym: str) -> str:
    """The part of the question holding the equations: after the last ':' if any, and before ', giving' etc."""
    s = sym
    if ":" in s:
        s = s.rsplit(":", 1)[1]
    s = re.sub(r"\b(?:by\s+(?:completing\s+the\s+square|factori[sz]ation|factori[sz]ing|using\s+the\s+(?:quadratic\s+)?formula)|"
               r"using\s+the\s+(?:quadratic\s+)?formula|graphically)\b\s*,?", " ", s, flags=re.I)     # the method, wherever it is
    s = re.split(r"\b(?:giving|correct\s+to|leaving|to\s+\(S\d+\)\s+(?:decimal|significant)|using)\b", s, flags=re.I)[0]
    s = re.sub(r"\b(?:hence|and\s+state|and\s+check)\b.*$", "", s, flags=re.I)
    return s.strip().rstrip(".?")


def unknowns_of(q: Question, exprs) -> List[sp.Symbol]:
    free = set()
    for e in exprs:
        free |= {s for s in e.free_symbols if not re.fullmatch(r"S\d+", s.name) and s.name not in _NOT_UNKNOWN}
    order = []
    for ch in re.findall(r"(?<![A-Za-z])[a-z](?![A-Za-z])", re.sub(r"\(S\d+\)", " ", q.sym)):   # order of appearance
        s = sp.Symbol(ch)
        if s in free and s not in order:
            order.append(s)
    return order + sorted(free - set(order), key=lambda s: s.name)


def surd(r) -> str:
    """-2 + sqrt(11) rather than -sqrt(11) - 2: the whole number first."""
    r = exact(r)
    rat, irr = r.as_independent(sp.Pow, sp.Mul, as_Add=True) if r.is_Add else (sp.Integer(0), r)
    if r.is_Add and rat != 0 and irr != 0:
        sign = "-" if irr.could_extract_minus_sign() else "+"
        return f"{fnum(rat)} {sign} {fmt_expr(-irr if sign == '-' else irr)}"
    return fnum(r)


def roots_text(var: sp.Symbol, sols: Sequence, decimals: Optional[int]) -> str:
    vals = []
    for r in sols:
        if decimals is not None and not exact(r).is_Rational:
            vals.append(f"{float(r):.{decimals}f}")
        else:
            vals.append(surd(r))
    return " or ".join(f"{var.name} = {v}" for v in vals)


def real_sorted(sols) -> list:
    out = []
    for r in sols:
        r = exact(r) if r.is_number else r
        if r.is_real:
            out.append(r)
    try:
        return sorted(set(out), key=lambda r: float(r))
    except TypeError:
        return out


# ══ equations ═══════════════════════════════════════════════════════════════════════════════════════════════

class Equation(Family):
    name = "equation"
    kind = "algebra"

    def parse(self, q: Question) -> Optional[Spec]:
        low = q.low
        if "=" not in q.sym or re.search(r"[<>]|<=|>=|\bsubject\b|\bsin\b|\bcos\b|\btan\b|\bcentre\b|\bradius\b|"
                                         r"\bline\b|\bcurve\b|\bdifferentiat|\bintegra|\bevaluate\b.*\bwhen\b|\bwhen\s+[a-z]\s*=|"
                                         r"\bdeterminant\b|\bsingular\b|\binverse\b|\bdiscriminant\b|\bnature\b|\bsum\s+and\s+product\b|"
                                         r"\bremainder\b|\bfactor\b", low):
            return None
        if not re.search(r"\bsolve|\bfind\b|\bvalue|\broots?\b|\bsolution|\bwhat\s+is\b|\bif\b|\bsatisf|^\s*\(?S?\d*\)?\s*[a-z(]", low) \
                and not re.match(r"^[\w\s+\-*/^().=]+$", q.norm):
            return None
        part = maths_part(q.sym)
        pieces = [p for p in re.split(r"\s*(?:,|;|\band\b)\s*", part) if "=" in p]
        if not pieces or len(pieces) > 3:
            return None
        eqs = []
        for p in pieces:
            rel = split_relation(p)
            if not rel or rel[1] != "=":
                return None
            L, R = to_expr(strip_words(tail_math(rel[0])), natural_log=False), to_expr(head_math(rel[2]), natural_log=False)
            if L is None or R is None:
                return None
            eqs.append(L - R)
        unk = unknowns_of(q, eqs)
        m = re.search(r"\b(?:for|value\s+of|values\s+of|find)\s+([a-z])\b", q.low)
        if m and sp.Symbol(m.group(1)) in unk:
            first = sp.Symbol(m.group(1))
            unk = [first] + [u for u in unk if u != first]
        if not unk or len(unk) < len(eqs):
            return None
        unk = unk[:len(eqs)]
        if len(eqs) == 1 and len(unk) == 1 and not eqs[0].has(unk[0]):
            return None
        dec = re.search(r"(\(S\d+\)|\d+)\s+decimal\s+places?", q.sym)
        decimals = int(q.vals[int(dec.group(1)[2:-1])]) if dec and dec.group(1).startswith("(S") else (int(dec.group(1)) if dec else None)
        x = unk[0]
        orig = q.subs(q.vals)
        P = None
        if len(eqs) == 1:
            num = sp.numer(sp.together(eqs[0]))
            try:
                if sp.Poly(sp.expand(num.subs(orig)), x).degree() >= 1:
                    P = num
            except Exception:                                                # noqa: BLE001 - not a polynomial
                P = None
        inside = q.slot_symbols(eqs)
        bases = set()
        for e in eqs:                                       # 2^(x+1), 3^(2x): the base stays (so do log bases)
            for g in sp.preorder_traversal(e):
                if isinstance(g, sp.Pow) and g.exp.has(*unk) and not g.base.has(*unk):
                    bases |= set(q.slot_symbols(g.base)) | set(q.slot_symbols(g.exp))   # 3^(2x): 3 and 2 stay
                if isinstance(g, sp.log) and len(g.args) == 1 and not g.args[0].has(*unk):
                    bases |= set(q.slot_symbols(g.args[0]))
        inside = [i for i in inside if i not in bases and q.slots[i].value != 0]
        return Spec(eqs=eqs, unk=unk, P=P, decimals=decimals, inside=inside,
                    formula=bool(re.search(r"\bformula\b", low)), square=bool(re.search(r"complet\w*\s+the\s+square", low)))

    def solve(self, q: Question, spec: Spec, vals, full: bool = True) -> Optional[Item]:
        sub = q.subs(vals)
        eqs = [sp.expand(e.subs(sub)) for e in spec.eqs]
        text = q.render(vals)
        if len(eqs) == 1:
            x = spec.unk[0]
            try:
                sols = real_sorted(sp.solve(eqs[0], x))
            except Exception:                                                # noqa: BLE001
                return None
            if not sols or len(sols) > 4:
                return None
            for r in sols:                                                   # check: substitute back
                try:
                    if abs(complex(sp.N(eqs[0].subs(x, r)))) > 1e-8:
                        return None
                except Exception:                                            # noqa: BLE001
                    return None
            ans = roots_text(x, sols, spec.decimals)
            if not full:
                return Item(text, ans, [], [], self.kind, value=tuple(sols))
            return Item(text, ans, self._steps1(eqs[0], x, sols, spec), self._wrong1(eqs[0], x, sols, spec), self.kind,
                        value=tuple(sols))
        try:
            sol = sp.solve(eqs, spec.unk, dict=True)
        except Exception:                                                    # noqa: BLE001
            return None
        if len(sol) != 1 or any(u not in sol[0] for u in spec.unk):
            return None
        s0 = {u: exact(sol[0][u]) for u in spec.unk}
        if any(not v.is_real for v in s0.values()):
            return None
        for e in eqs:
            if sp.simplify(e.subs(s0)) != 0:
                return None
        ans = ", ".join(f"{u.name} = {fnum(s0[u])}" for u in spec.unk)
        if not full:
            return Item(text, ans, [], [], self.kind, value=tuple(s0[u] for u in spec.unk))
        steps = ["Eliminate one unknown: multiply the equations so one letter has the same coefficient, then add or subtract."]
        if len(spec.unk) == 3:
            steps = ["Eliminate one letter from two different pairs of equations, leaving two equations in two letters."]
        steps.append("Solve for that letter, then substitute back to find the other" + ("s." if len(spec.unk) == 3 else "."))
        steps.append(f"So {ans}")
        steps.append("Check: these values make every equation true.")
        vs = [s0[u] for u in spec.unk]
        wrong = []
        alts = [vs[::-1], [-v for v in vs], [vs[0], -vs[1]] + vs[2:], [v + 1 for v in vs], [vs[0] + 1] + vs[1:]]
        for alt in alts:
            w = ", ".join(f"{u.name} = {fnum(v)}" for u, v in zip(spec.unk, alt))
            if w != ans and w not in wrong:
                wrong.append(w)
        return Item(text, ans, steps, wrong, self.kind, value=tuple(vs))

    def nice(self, base: Item, item: Item) -> bool:
        b, v = base.value or (), item.value or ()
        if len(b) != len(v):
            return False
        if any(not exact(r).is_Rational for r in b):
            return all(exact(r).is_real for r in v) and any(not exact(r).is_Rational for r in v)
        try:
            if max(abs(float(r)) for r in v) > max(30, 4 * max(abs(float(r)) for r in b)):
                return False
        except (TypeError, ValueError):
            pass
        return like(v, b)

    def _steps1(self, e, x, sols, spec) -> List[str]:
        steps = []
        try:
            poly = sp.Poly(sp.numer(sp.together(e)), x)
            deg = poly.degree()
        except Exception:                                                    # noqa: BLE001
            poly, deg = None, 0
        if poly is not None and deg == 1:
            a, b = poly.all_coeffs()
            if sp.denom(sp.together(e)) != 1:
                steps.append("Clear the fractions: multiply every term by the lowest common denominator.")
            steps.append(f"Collect the {x.name} terms on one side and the numbers on the other: {fmt_expr(a * x)} = {fnum(-b)}")
            steps.append(f"Divide both sides by {fnum(a)}: {x.name} = {fnum(sols[0])}")
        elif poly is not None and deg == 2:
            a, b, c = poly.all_coeffs()
            if spec.square:
                h = exact(b / (2 * a))
                k = exact(c / a - h ** 2)
                steps.append(f"Divide by {fnum(a)} and complete the square: ({fmt_expr(x + h)})^2 = {fnum(-k)}" if a != 1 else
                             f"Complete the square: ({fmt_expr(x + h)})^2 = {fnum(-k)}")
                steps.append(f"Take square roots: {fmt_expr(x + h)} = ±{fmt_expr(sp.sqrt(-k))}")
            elif all(exact(r).is_Rational for r in sols) and not spec.formula:
                steps.append(f"Factorise: {fmt_expr(sp.factor(poly.as_expr()))} = 0")
                steps.append("Set each bracket to 0.")
            else:
                d = b ** 2 - 4 * a * c
                steps.append(f"Use the formula x = (-b ± sqrt(b^2 - 4ac))/(2a) with a = {fnum(a)}, b = {fnum(b)}, c = {fnum(c)}.")
                steps.append(f"b^2 - 4ac = {fnum(d)}")
        else:
            steps.append("Rearrange so one side is 0, then solve (substituting u for a repeated power where it helps).")
        steps.append(f"So {roots_text(x, sols, spec.decimals)}")
        steps.append(f"Check: substituting {'each value' if len(sols) > 1 else 'it'} back makes both sides equal.")
        return steps

    def _wrong1(self, e, x, sols, spec) -> List[str]:
        wrong = []
        sets = [[-r for r in sols], [r + 1 for r in sols], [2 * r for r in sols], [r - 1 for r in sols]]
        if len(sols) == 1:
            r = sols[0]
            try:
                a, k = sp.Poly(sp.numer(sp.together(e)), x).all_coeffs()[:2]
                sets = [[-r], [-k] if -k != r else [r * 2], [r + 1], [r - 1], [2 * r]] + sets   # sign slip, forgot ÷
            except Exception:                                                # noqa: BLE001
                pass
        if len(sols) == 2:
            sets.insert(0, [sols[0], -sols[1]])
            sets.insert(1, [-sols[0], sols[1]])
        right = roots_text(x, sols, spec.decimals)
        for s in sets:
            s = sorted(set(exact(v) for v in s), key=lambda v: float(v))
            w = roots_text(x, s, spec.decimals)
            if w != right and w not in wrong:
                wrong.append(w)
        return wrong

    def vary(self, q: Question, spec: Spec, rng: random.Random):
        if spec.P is not None:
            orig = q.subs(q.vals)
            try:
                deg = sp.Poly(sp.expand(spec.P.subs(orig)), spec.unk[0]).degree()
            except Exception:                                                # noqa: BLE001
                deg = 2
            for _ in range(3):
                v = keep_roots(q, [spec.P], spec.unk[0], rng, free=spec.inside, same_sign=(deg == 1),
                               flip_roots=0.0 if deg == 1 else 0.35)
                if v is not None:
                    return v
        if len(spec.eqs) > 1:
            return self._vary_system(q, spec, rng)
        if spec.P is None:                                                   # exponential / log: root first, then a constant
            vals = vary_slots(q, spec.inside, rng)
            try:
                old = [r for r in sp.solve(spec.eqs[0].subs(q.subs(q.vals)), spec.unk[0]) if r.is_real]
            except Exception:                                                # noqa: BLE001
                return vals
            if old and all(exact(r).is_Integer for r in old):
                news = []
                for r in old:                                    # new whole-number roots, near the old ones
                    k = int(r)
                    for _ in range(8):
                        c = k + rng.randint(-3, 3)
                        if c not in news and (k == 0 or c != 0) and (c >= 0) == (k >= 0):
                            news.append(c)
                            break
                if len(news) != len(old):
                    return None
                deps = [i for i in reversed(spec.inside) if q.slots[i].role in ("num", "coef")][:len(news)]
                if len(deps) < len(news):
                    return None
                fixed_vals = list(vals)
                eqs = [spec.eqs[0].subs(spec.unk[0], sp.Integer(c)) for c in news]
                syms = [q.S[i] for i in deps]
                known = {q.S[k]: sp.Rational(frac(v).numerator, frac(v).denominator) for k, v in enumerate(fixed_vals) if k not in deps}
                try:
                    sol = sp.solve([exact(e.subs(known)) for e in eqs], syms, dict=True)
                except Exception:                                # noqa: BLE001
                    return None
                if len(sol) != 1:
                    return None
                for i in deps:
                    v = exact(sol[0].get(q.S[i], sp.nan))
                    if not v.is_Rational or v == 0 or (q.slots[i].is_int and v.q != 1) or abs(v) > 10000 or                             (v < 0) != (q.slots[i].value < 0):
                        return None
                    vals[i] = frac(v)
            return vals
        return vary_slots(q, spec.inside, rng)

    def _vary_system(self, q: Question, spec: Spec, rng: random.Random):
        orig = q.subs(q.vals)
        try:
            old = sp.solve([e.subs(orig) for e in spec.eqs], spec.unk, dict=True)[0]
        except Exception:                                                    # noqa: BLE001
            return None
        vals = list(q.vals)
        consts = []
        for e in spec.eqs:                                                   # each equation's constant
            cs = [i for i in q.slot_symbols(e) if not any(sp.expand(e).coeff(u).has(q.S[i]) for u in spec.unk)]
            if not cs:
                return None
            consts.append(cs[-1])
        for i in varying(q, spec.inside):
            if i not in consts:
                vals[i] = new_value(q.slots[i], rng)
        new = {}
        for u in spec.unk:                                                   # new whole-number answers, same signs
            o = old.get(u)
            base = abs(int(o)) if o is not None and exact(o).is_Integer else 5
            k = rng.randint(1, max(6, base + 3))
            new[u] = sp.Integer(-k if o is not None and o < 0 else k)
        for e, dep in zip(spec.eqs, consts):
            v = back_solve(q, e.subs(new), dep, vals)
            if v is None or (q.slots[dep].is_int and v.denominator != 1) or v == 0 or                     ((v < 0) != (q.slots[dep].value < 0) and q.slots[dep].value != 0):
                return None
            vals[dep] = v
        return vals


_MATH_WORD = re.compile(r"^(?:sin|cos|tan|sec|cot|csc|ln|log|sqrt|exp|pi|theta|Abs)\b")


def tail_math(t: str) -> str:
    """The maths at the end of a text chunk: 'values of x for which (S0)' -> '(S0)'."""
    words = t.split(" ")
    k = len(words)
    while k > 0:
        w = words[k - 1]
        if is_word(w):
            break
        k -= 1
    return " ".join(words[k:]).strip()


_TWO = {"if", "is", "of", "to", "in", "at", "by", "be", "as", "or", "an", "so", "on", "we", "it"}


def is_word(w: str) -> bool:
    """An English word (not maths): 'which', 'find', 'if' — but not 'x', 'xy', 'sin', '(S0)x'."""
    w = w.strip(",.:;?")
    if not re.fullmatch(r"[A-Za-z]{2,}", w) or _MATH_WORD.match(w):
        return False
    return len(w) >= 3 or w.lower() in _TWO


def head_math(t: str) -> str:
    """The maths at the start of a text chunk: '(S3), giving …' -> '(S3)'."""
    words = t.strip().split(" ")
    out = []
    for w in words:
        if is_word(w):
            break
        out.append(w)
    return " ".join(out).strip().rstrip(",.;?")


# ══ inequalities ═════════════════════════════════════════════════════════════════════════════════════════════

def set_text(sol, x) -> str:
    """A sympy solution set -> 'x > 5', '-2 < x < 3', 'x < 1 or x > 4'."""
    parts = []
    for iv in (sol.args if isinstance(sol, sp.Union) else [sol]):
        if not isinstance(iv, sp.Interval):
            return ""
        lo, hi = iv.start, iv.end
        if lo == -sp.oo and hi == sp.oo:
            parts.append(f"all real {x.name}")
        elif lo == -sp.oo:
            parts.append(f"{x.name} {'<' if iv.right_open else '≤'} {fnum(hi)}")
        elif hi == sp.oo:
            parts.append(f"{x.name} {'>' if iv.left_open else '≥'} {fnum(lo)}")
        else:
            parts.append(f"{fnum(lo)} {'<' if iv.left_open else '≤'} {x.name} {'<' if iv.right_open else '≤'} {fnum(hi)}")
    return " or ".join(parts)


def ineq_mistakes(sol) -> list:
    """Sets students wrongly give: the other side, the ends included or not, a sign slip."""
    I, U, oo = sp.Interval, sp.Union, sp.oo
    ivs = list(sol.args) if isinstance(sol, sp.Union) else [sol]
    out = []
    if len(ivs) == 1:
        iv = ivs[0]
        a, b, lo, ro = iv.start, iv.end, iv.left_open, iv.right_open
        if a == -oo:
            out += [I(b, oo, not ro, True), I(-oo, b, True, not ro), I(-oo, -b, True, ro), I(-oo, b + 1, True, ro)]
        elif b == oo:
            out += [I(-oo, a, True, not lo), I(a, oo, not lo, True), I(-a, oo, lo, True), I(a + 1, oo, lo, True)]
        else:
            out += [U(I(-oo, a, True, not lo), I(b, oo, not ro, True)), I(a, b, not lo, not ro), I(-b, -a, ro, lo),
                    I(a, b + 1, lo, ro), I(a - 1, b, lo, ro)]
    elif len(ivs) == 2:
        a, b = ivs[0].end, ivs[1].start
        out += [I(a, b, ivs[0].right_open, ivs[1].left_open), U(I(-oo, a, True, not ivs[0].right_open), I(b, oo, not ivs[1].left_open, True)),
                U(I(-oo, -b, True, True), I(-a, oo, True, True)), I(a, b, not ivs[0].right_open, not ivs[1].left_open)]
    return [o for o in out if o != sol]


class Inequality(Family):
    name = "inequality"
    kind = "inequalities"

    def parse(self, q: Question) -> Optional[Spec]:
        if not re.search(r"<|>", q.sym) or re.search(r"\bsin\b|\bcos\b|\btan\b|\bdeg\b|->|probab", q.low):
            return None
        part = maths_part(q.sym)
        toks = re.split(r"(<=|>=|<|>)", part)
        if len(toks) not in (3, 5):
            return None
        toks[0], toks[-1] = tail_math(toks[0]), head_math(toks[-1])         # "values of x for which -3 < …"
        exprs = [to_expr(strip_words(t)) for t in toks[0::2]]
        if any(e is None for e in exprs):
            return None
        ops = toks[1::2]
        unk = unknowns_of(q, exprs)
        if len(unk) != 1:
            return None
        x = unk[0]
        abs_form = any(e.has(sp.Abs) for e in exprs)
        if abs_form and len(exprs) == 2 and isinstance(exprs[0], sp.Abs):
            u = exprs[0].args[0]                       # |u| ≤ c: the ends are where u = c and u = -c
            polys = [u - exprs[1], u + exprs[1]]
        else:
            polys = [exprs[k + 1] - exprs[k] for k in range(len(ops))]
        return Spec(exprs=exprs, ops=ops, x=x, polys=polys, abs_form=abs_form, inside=q.slot_symbols(exprs))

    def _set(self, exprs, ops, x):
        rel = {"<": sp.Lt, ">": sp.Gt, "<=": sp.Le, ">=": sp.Ge}
        if len(exprs) == 2 and isinstance(exprs[0], sp.Abs):  # |u| < c  ->  -c < u < c (fast, no Abs)
            u, c = exprs[0].args[0], exprs[1]
            if ops[0] in ("<", "<="):
                return self._set([-c, u, c], [ops[0], ops[0]], x)
            inner = self._set([u, c], [ops[0]], x)
            return inner.union(self._set([u, -c], ["<" if ops[0] == ">" else "<="], x))
        sol = sp.S.Reals
        for k, op in enumerate(ops):
            r = rel[op](exprs[k], exprs[k + 1])
            sol = sol.intersect(sp.solve_univariate_inequality(r, x, relational=False))
        return sol

    def solve(self, q: Question, spec: Spec, vals, full: bool = True) -> Optional[Item]:
        sub = q.subs(vals)
        exprs = [e.subs(sub) for e in spec.exprs]
        x = spec.x
        try:
            sol = self._set(exprs, spec.ops, x)
        except Exception:                                                    # noqa: BLE001
            return None
        ans = set_text(sol, x)
        if not ans or sol == sp.S.EmptySet or "all real" in ans:
            return None
        ends = []
        for iv in (sol.args if isinstance(sol, sp.Union) else [sol]):
            ends += [v for v in (iv.start, iv.end) if v not in (sp.oo, -sp.oo)]
        text = q.render(vals)
        if not full:
            return Item(text, ans, [], [], self.kind, value=tuple(ends))
        steps = []
        if spec.abs_form:
            steps.append("|u| < b means -b < u < b; |u| > b means u < -b or u > b.")
        elif len(spec.ops) == 2:
            steps.append("Do the same thing to all three parts at once.")
        elif any(sp.Poly(sp.expand(p), x).degree() == 2 for p in [exprs[1] - exprs[0]] if p.is_polynomial(x)):
            p = sp.expand(exprs[0] - exprs[1])
            rts = real_sorted(sp.solve(p, x))
            steps.append(f"Solve {fmt_expr(p)} = 0: x = {', '.join(fnum(r) for r in rts)}.")
            steps.append("Sketch the parabola or test a value in each region to see where the inequality holds.")
        else:
            steps.append(f"Collect the {x.name} terms on one side and the numbers on the other.")
            steps.append("Divide by the coefficient of x — and turn the sign round if you divide by a negative number.")
        steps.append(f"So {ans}")
        wrong = []
        for alt in ineq_mistakes(sol):
            w = set_text(alt, x)
            if w and w != ans and w not in wrong:
                wrong.append(w)
        return Item(text, ans, steps, wrong, self.kind, value=tuple(ends))

    def vary(self, q: Question, spec: Spec, rng: random.Random):
        polys = [p for p in spec.polys if p.has(spec.x)]
        for _ in range(3):
            fixed_order = spec.abs_form or len(spec.ops) == 2                 # the two ends must stay in order
            v = keep_roots(q, polys, spec.x, rng, free=spec.inside, same_sign=fixed_order,
                           flip_roots=0.0 if fixed_order else 0.35)
            if v is not None:
                return v
        return vary_slots(q, spec.inside, rng)


# ══ changing the subject of a formula ═══════════════════════════════════════════════════════════════════════

FORMULAS = [
    ("v = u + at", "a"), ("v = u + at", "t"), ("s = ut + (1/2)at^2", "a"), ("A = pi r^2", "r"), ("V = pi r^2 h", "h"),
    ("V = pi r^2 h", "r"), ("E = mc^2", "c"), ("F = ma", "m"), ("P = 2(l + w)", "l"), ("y = mx + c", "x"),
    ("I = PRT/100", "R"), ("I = PRT/100", "T"), ("C = 2 pi r", "r"), ("A = (1/2)(a + b)h", "h"), ("v^2 = u^2 + 2as", "s"),
    ("v^2 = u^2 + 2as", "u"), ("T = 2 pi sqrt(l/g)", "l"), ("F = 9C/5 + 32", "C"), ("E = (1/2)mv^2", "v"),
    ("PV = nRT", "T"), ("A = P + PRT/100", "P"), ("y = (x + a)/b", "x"), ("p = q/(r - s)", "r"),
]


class Subject(Family):
    """'Make r the subject of A = πr²': versions are other formulas (the same skill), from a library."""
    name = "subject"
    kind = "algebra"

    def parse(self, q: Question) -> Optional[Spec]:
        m = re.search(r"\bmake\s+([A-Za-z])\s+the\s+subject\b", q.display, re.I) or \
            re.search(r"\b(?:express|solve\s+for|rearrange\b.*\bfor)\s+([A-Za-z])\s+in\s+terms\s+of\b", q.display, re.I)
        if not m:
            return None
        fm = re.search(r"([A-Za-z][A-Za-z0-9]*\s*=\s*[^,;?]+)", q.display[m.end():] or q.display) or \
             re.search(r"([A-Za-z][A-Za-z0-9]*\s*=\s*[^,;?]+)", q.display)
        if not fm:
            return None
        return Spec(var=m.group(1), formula=fm.group(1).strip().rstrip("."), span=fm.span(1), offset=m.end())

    @staticmethod
    def _rearrange(formula: str, var: str):
        rel = split_relation(formula.replace("π", "pi"))
        if not rel:
            return None
        L, R = to_expr(rel[0], natural_log=False, formula=True), to_expr(rel[2], natural_log=False, formula=True)
        v = sp.Symbol(var)
        if L is None or R is None or not (L.has(v) or R.has(v)):
            return None
        try:
            sols = sp.solve(sp.Eq(L, R), v)
        except Exception:                                                    # noqa: BLE001
            return None
        if not sols:
            return None
        pos = [s for s in sols if not str(s).startswith("-")] or sols
        r = pos[0]
        cands = [r, sp.factor(r), sp.simplify(r)]
        return min(cands, key=lambda c: len(fmt_expr(c)))

    def solve(self, q: Question, spec: Spec, vals, full: bool = True) -> Optional[Item]:
        r = self._rearrange(spec.formula, spec.var)
        if r is None:
            return None
        ans = f"{spec.var} = {fmt_expr(r)}"
        return Item(q.display, ans, [f"Undo each operation on {spec.var} in reverse order, doing the same to both sides.", f"So {ans}"],
                    [], self.kind, value=None)

    def versions(self, q: Question, spec: Spec, n: int, rng: random.Random, seen: set) -> List[Item]:
        out = []
        pool = FORMULAS[:]
        rng.shuffle(pool)
        for formula, var in pool:
            if len(out) >= n:
                break
            text = re.sub(r"\bmake\s+[A-Za-z]\s+the\s+subject", lambda m: re.sub(r"\s[A-Za-z]\s", f" {var} ", m.group(0), count=1), q.display, count=1, flags=re.I)
            fm = re.search(r"([A-Za-z][A-Za-z0-9]*\s*=\s*[^,;?]+)", text[spec.offset - 2:])
            if not fm:
                continue
            start = spec.offset - 2 + fm.start(1)
            text = text[:start] + formula.replace("pi ", "π").replace("pi", "π") + text[spec.offset - 2 + fm.end(1):]
            key = re.sub(r"\s+", "", text.lower())
            if key in seen:
                continue
            r = self._rearrange(formula, var)
            if r is None:
                continue
            ans = f"{var} = {fmt_expr(r)}"
            wrong = []
            try:
                rel = split_relation(formula)
                L, R = to_expr(rel[0], formula=True), to_expr(rel[2], formula=True)
                v = sp.Symbol(var)
                for w in (sp.simplify(1 / r) if r != 0 else None, sp.simplify(r * 2), sp.simplify(-r),
                          sp.simplify(r ** 2) if not r.is_polynomial() else sp.simplify(r + 1)):
                    if w is not None:
                        s = f"{var} = {fmt_expr(w)}"
                        if s != ans and s not in wrong:
                            wrong.append(s)
            except Exception:                                                # noqa: BLE001
                pass
            seen.add(key)
            out.append(Item(text, ans, [f"Undo each operation on {var} in reverse order, doing the same to both sides.",
                                        f"So {ans}"], wrong, self.kind))
        return out
