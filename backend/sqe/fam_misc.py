"""
CUSTOM-SQE matrices, complex numbers and proofs:
  - matrices: the determinant (2×2, 3×3), the inverse of a 2×2, a product, solving equations with matrices, and
    the value that makes a matrix singular;
  - complex numbers: products, quotients in a + bi form, modulus, argument, z² + k = 0;
  - proofs: that √p is irrational, for a prime p, by contradiction.

An inverse keeps a determinant of ±1 when the original had one, so its entries stay whole. A modulus question
gets a Pythagorean pair.
"""
from __future__ import annotations

import math
import random
import re
from fractions import Fraction
from typing import List, Optional

import sympy as sp

from .core import Family, Item, Spec, numeric_wrong
from .text import Question, exact, fmt_expr, fmt_num

fnum = lambda v: fmt_num(v, fractions=True)
_TRIPLES = [(3, 4), (5, 12), (8, 15), (6, 8), (7, 24), (9, 12), (12, 16), (20, 21), (9, 40)]


def matrices(q: Question):
    """Each [[a, b], [c, d]] in the text as rows of slots (or symbols, for 'x')."""
    out = []
    for m in re.finditer(r"\[\s*(\[[^\[\]]+\](?:\s*,\s*\[[^\[\]]+\])+)\s*\]", q.sym):
        rows = []
        for r in re.findall(r"\[([^\[\]]+)\]", m.group(1)):
            cells = [c.strip() for c in r.split(",")]
            rows.append(cells)
        if len({len(r) for r in rows}) == 1:
            out.append(rows)
    return out


def mat_of(rows, q: Question, vals) -> sp.Matrix:
    sub = q.subs(vals)
    def cell(c):
        m = re.fullmatch(r"\(S(\d+)\)", c)
        if m:
            return sub[q.S[int(m.group(1))]]
        return sp.Symbol(c) if re.fullmatch(r"[a-z]", c) else sp.sympify(c)
    return sp.Matrix([[cell(c) for c in r] for r in rows])


def mat_text(M: sp.Matrix) -> str:
    return "[" + ", ".join("[" + ", ".join(fnum(x) for x in M.row(i)) + "]" for i in range(M.rows)) + "]"


class Matrices(Family):
    name = "matrices"
    kind = "matrices"

    def parse(self, q: Question) -> Optional[Spec]:
        low = q.low
        ms = matrices(q)
        if re.search(r"\bmatri|\bdeterminant", low) and re.search(r"\bsolve\b", low) and "=" in q.sym and not ms:
            return None                                                      # 'use matrices to solve': the equations family
        if not ms:
            return None
        if re.search(r"singular", low) and len(ms) == 1:
            letters = {c for r in ms[0] for c in r if re.fullmatch(r"[a-z]", c)}
            if len(letters) == 1:
                return Spec(task="singular", ms=ms, var=letters.pop())
        if re.search(r"determinant|\bdet\b|\|", low) and len(ms) == 1:
            return Spec(task="det", ms=ms)
        if re.search(r"inverse", low) and len(ms) == 1:
            return Spec(task="inverse", ms=ms)
        if re.search(r"multiply|product|\bab\b|find\s+ab|× |\*", low) and len(ms) == 2:
            return Spec(task="product", ms=ms)
        return None

    def solve(self, q, spec, vals, full=True):
        text = q.render(vals)
        t = spec.task
        if t == "det":
            M = mat_of(spec.ms[0], q, vals)
            if M.rows != M.cols:
                return None
            d = M.det()
            ans = fnum(d)
            if not full:
                return Item(text, ans, [], [], self.kind, value=d)
            if M.rows == 2:
                steps = [f"det = ad - bc = ({fnum(M[0, 0])})({fnum(M[1, 1])}) - ({fnum(M[0, 1])})({fnum(M[1, 0])}) = {ans}"]
                alts = [M[0, 0] * M[1, 1] + M[0, 1] * M[1, 0], M[0, 1] * M[1, 0] - M[0, 0] * M[1, 1], M[0, 0] * M[1, 0] - M[0, 1] * M[1, 1]]
            else:
                steps = ["Expand along the first row: a(ei - fh) - b(di - fg) + c(dh - eg).", f"det = {ans}"]
                alts = [M[0, 0] * M[1:, 1:].det() + M[0, 1] * M.minor_submatrix(0, 1).det() + M[0, 2] * M.minor_submatrix(0, 2).det(), -d, d + M[0, 0]]
            return Item(text, ans, steps, numeric_wrong(d, fnum, alts), self.kind, value=d)
        if t == "inverse":
            M = mat_of(spec.ms[0], q, vals)
            if M.shape != (2, 2) or M.det() == 0:
                return None
            Inv = M.inv()
            d = M.det()
            ans = mat_text(Inv)
            if not full:
                return Item(text, ans, [], [], self.kind, value=d)
            a, b, c, dd = M
            steps = [f"det = ad - bc = {fnum(d)}", f"Inverse = (1/det) × [[d, -b], [-c, a]] = (1/{fnum(d)}) × [[{fnum(dd)}, {fnum(-b)}], [{fnum(-c)}, {fnum(a)}]]", f"= {ans}"]
            alts = [sp.Matrix([[dd, -b], [-c, a]]), sp.Matrix([[dd, b], [c, a]]) / d, sp.Matrix([[a, -b], [-c, dd]]) / d, -Inv]
            return Item(text, ans, steps, [w for w in dict.fromkeys(mat_text(A) for A in alts) if w != ans], self.kind, value=d)
        if t == "product":
            A, B = [mat_of(m, q, vals) for m in spec.ms]
            if A.cols != B.rows:
                return None
            P = A * B
            ans = mat_text(P)
            if not full:
                return Item(text, ans, [], [], self.kind)
            steps = ["Each entry = (row of the first) · (column of the second): multiply in pairs and add.", f"AB = {ans}"]
            alts = [B * A if B.cols == A.rows else A + B, A.multiply_elementwise(B) if A.shape == B.shape else 2 * P, P.T]
            return Item(text, ans, steps, [w for w in dict.fromkeys(mat_text(X) for X in alts) if w != ans], self.kind)
        if t == "singular":
            M = mat_of(spec.ms[0], q, vals)
            x = sp.Symbol(spec.var)
            sols = sp.solve(M.det(), x)
            if len(sols) != 1:
                return None
            r = sols[0]
            ans = f"{spec.var} = {fnum(r)}"
            if not full:
                return Item(text, ans, [], [], self.kind, value=r)
            steps = ["Singular means the determinant is 0.", f"det = {fmt_expr(sp.expand(M.det()))} = 0", f"So {ans}"]
            return Item(text, ans, steps, [f"{spec.var} = {w}" for w in numeric_wrong(r, fnum, [-r, 1 / r if r else 1, r + 1])], self.kind, value=r)
        return None

    def vary(self, q, spec, rng):
        vals = list(q.vals)
        V = [Fraction(v) for v in q.vals]
        ids = [int(m.group(1)) for rows in spec.ms for r in rows for c in r for m in [re.fullmatch(r"\(S(\d+)\)", c)] if m]
        rnd = lambda i: Fraction(rng.randint(1, 9) * (1 if V[i] >= 0 else -1)) if V[i] != 0 else Fraction(0)
        if spec.task == "inverse":
            d0 = mat_of(spec.ms[0], q, q.vals).det()
            for _ in range(40):
                for i in ids:
                    vals[i] = rnd(i)
                d = mat_of(spec.ms[0], q, vals).det()
                if (abs(d0) == 1 and abs(d) == 1) or (abs(d0) != 1 and d != 0 and abs(d) <= 12):
                    return vals
            return None
        if spec.task == "singular":
            for _ in range(40):
                for i in ids:
                    vals[i] = rnd(i)
                M = mat_of(spec.ms[0], q, vals)
                r = sp.solve(M.det(), sp.Symbol(spec.var))
                if len(r) == 1 and (exact(r[0]).is_Integer or not exact(mat_of(spec.ms[0], q, q.vals).det()).is_number):
                    return vals
            return None
        for i in ids:
            vals[i] = rnd(i) if rng.random() < 0.85 else Fraction(rng.randint(0, 9))
        return vals

    def nice(self, base, item):
        if base.value is None or item.value is None:
            return True
        b, v = exact(base.value), exact(item.value)
        if b.is_Integer:
            return v.is_Integer
        return v.is_Rational


# ══ complex numbers ═════════════════════════════════════════════════════════════════════════════════════════

class Complex(Family):
    name = "complex"
    kind = "complex"

    def parse(self, q: Question) -> Optional[Spec]:
        low = q.low
        if not re.search(r"\bi\b|\di\b|complex|\bz\b", low):                # 3 + 2i, 5 - 12i, 1 + i
            return None
        from .text import to_expr
        if re.search(r"\bsolve\b", low) and "z" in low:
            m = re.search(r"z\^\(S(\d+)\)\s*\+\s*\(S(\d+)\)\s*=\s*\(S\d+\)", q.sym)
            if m:
                return Spec(task="zroots", k=int(m.group(2)))
            return None
        task = ("modulus" if re.search(r"modulus|\|z\||absolute\s+value", low) else
                "argument" if re.search(r"argument|\barg\b", low) else
                "form" if re.search(r"form\s+a\s*\+\s*bi|simplify|express|evaluate|find", low) else None)
        if not task:
            return None
        body = re.sub(r"^.*\b(?:modulus\s+of|argument\s+of|simplify|express|evaluate|find)\b\s*", "", q.sym, flags=re.I)
        body = re.split(r"\s+in\s+the\s+form|\s*,|\?|\.\s|\.$", body)[0]
        e = to_expr(body, complex_i=True)
        if e is None or not e.has(sp.I):
            return None
        return Spec(task=task, e=e, inside=q.slot_symbols(e))

    def solve(self, q, spec, vals, full=True):
        text = q.render(vals)
        if spec.task == "zroots":
            k = Fraction(vals[spec.k])
            r = sp.sqrt(sp.Rational(k.numerator, k.denominator))
            ans = f"z = {fmt_expr(r * sp.I)} or z = {fmt_expr(-r * sp.I)}".replace("I", "i")
            if not full:
                return Item(text, ans, [], [], self.kind, value=r)
            steps = [f"z² = -{fnum(sp.Rational(k.numerator, k.denominator))}, so z = ±√{fnum(sp.Rational(k.numerator, k.denominator))} × i (since i² = -1)", f"So {ans}"]
            wrong = [f"z = {fmt_expr(r)} or z = {fmt_expr(-r)}", f"z = {fmt_expr(r * r * sp.I)} or z = {fmt_expr(-r * r * sp.I)}", f"z = {fmt_expr(r * sp.I)}"]
            return Item(text, ans, steps, [w.replace("I", "i") for w in wrong], self.kind, value=r)
        e = spec.e.subs(q.subs(vals))
        z = sp.expand(sp.simplify(e))
        re_, im_ = sp.re(z), sp.im(z)
        if spec.task == "modulus":
            r = sp.sqrt(re_ ** 2 + im_ ** 2)
            ans = fmt_expr(r)
            if not full:
                return Item(text, ans, [], [], self.kind, value=r)
            steps = [f"|a + bi| = √(a² + b²) = √({fnum(re_)}² + {fnum(im_)}²) = {ans}"]
            return Item(text, ans, steps, [w for w in dict.fromkeys(fmt_expr(x) for x in [abs(re_) + abs(im_), re_ ** 2 + im_ ** 2, sp.sqrt(abs(re_ ** 2 - im_ ** 2))]) if w != ans],
                        self.kind, value=r)
        if spec.task == "argument":
            ang = sp.atan2(im_, re_)
            degs = float(ang) * 180 / math.pi
            exact_ = sp.nsimplify(ang / sp.pi)
            ans = f"{fmt_expr(exact_ * sp.pi).replace('pi', 'π')} ({degs:.1f}°)" if exact_.is_Rational and exact_.q <= 12 else f"{degs:.1f}°"
            if not full:
                return Item(text, ans, [], [], self.kind)
            steps = [f"arg = angle from the positive real axis: tan θ = b/a = {fnum(im_)}/{fnum(re_)}, in the right quadrant.", f"θ = {ans}"]
            alts = [math.degrees(math.atan(float(im_ / re_))) if re_ else 90, 180 - degs, -degs]
            return Item(text, ans, steps, [w for w in dict.fromkeys(f"{a:.1f}°" for a in alts) if w != ans and w not in ans], self.kind)
        ans = fmt_expr(re_ + im_ * sp.I).replace("I", "i")
        if not full:
            return Item(text, ans, [], [], self.kind, value=(re_, im_))
        steps = (["Multiply top and bottom by the conjugate of the bottom, then use i² = -1."] if sp.fraction(sp.together(e))[1].has(sp.I) else
                 ["Multiply out the brackets and use i² = -1."]) + [f"So the answer is {ans}"]
        alts = [re_ - im_ * sp.I, -re_ + im_ * sp.I, im_ + re_ * sp.I, re_ + 2 * im_ * sp.I]
        return Item(text, ans, steps, [w for w in dict.fromkeys(fmt_expr(a).replace("I", "i") for a in alts) if w != ans], self.kind, value=(re_, im_))

    def vary(self, q, spec, rng):
        vals = list(q.vals)
        if spec.task == "zroots":
            vals[spec.k] = Fraction(rng.choice([k * k for k in range(2, 10) if k * k != q.vals[spec.k]]))
            return vals
        if spec.task == "modulus" and len(spec.inside) == 2:
            a, b = rng.choice(_TRIPLES)
            if rng.random() < 0.5:
                a, b = b, a
            i, j = spec.inside
            vals[i] = Fraction(a * (1 if q.vals[i] > 0 else -1))
            vals[j] = Fraction(b * (1 if q.vals[j] > 0 else -1))
            return vals
        if spec.task == "argument":
            for i in spec.inside:
                vals[i] = Fraction(rng.randint(1, 6) * (1 if q.vals[i] > 0 else -1))
            return vals
        for i in spec.inside:
            if abs(q.vals[i]) >= 1:
                vals[i] = Fraction(rng.randint(1, 7) * (1 if q.vals[i] > 0 else -1))
        return vals

    def nice(self, base, item):
        if isinstance(base.value, tuple) and isinstance(item.value, tuple):
            return all(exact(y).is_Rational and (not exact(x).is_Integer or exact(y).q <= 10) for x, y in zip(base.value, item.value))
        if base.value is not None and item.value is not None and exact(base.value).is_Integer:
            return exact(item.value).is_Integer
        return True


# ══ proofs ══════════════════════════════════════════════════════════════════════════════════════════════════

class Proof(Family):
    """'Prove that √3 is irrational': the same argument for other primes (from MrSOLIS 2-AL)."""
    name = "proof"
    kind = "proof"

    def parse(self, q: Question) -> Optional[Spec]:
        from .proofs import detect_irrationality_proof
        pf = detect_irrationality_proof(q.display.replace("√", " sqrt "))
        if not pf or not sp.isprime(pf.n):
            return None
        slot = next((s.i for s in q.slots if int(s.value) == pf.n), None)
        return Spec(n=pf.n, slot=slot)

    def solve(self, q, spec, vals, full=True):
        from .proofs import irrationality_proof_steps
        n = int(vals[spec.slot]) if spec.slot is not None else spec.n
        if not sp.isprime(n):
            return None
        text = q.render(vals)
        ans = f"√{n} is irrational (proof by contradiction)"
        return Item(text, ans, irrationality_proof_steps(n) if full else [], [], self.kind)

    def versions(self, q, spec, n, rng, seen):
        if spec.slot is None:
            return []
        pool = [p for p in (2, 3, 5, 7, 11, 13, 17, 19, 23, 29) if p != spec.n]
        rng.shuffle(pool)
        out = []
        for p in pool[:n]:
            vals = list(q.vals)
            vals[spec.slot] = Fraction(p)
            text = q.render(vals)
            key = re.sub(r"\s+", "", text.lower())
            if key in seen:
                continue
            seen.add(key)
            out.append(self.solve(q, spec, vals, True))
        return out
