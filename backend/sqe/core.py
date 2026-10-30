"""
CUSTOM-SQE's core: what a question family is, how new versions are made and checked, and the shared tools.

The tools are:
  - choosing new numbers like the student's (same size, same kind, same roundness);
  - keeping answers as clean as the original's;
  - back-solving slots so equations keep whole-number roots and a 0/0 limit stays 0/0;
  - building wrong options.

Every version is read back from its own displayed text and must give the same answer, so the student always
works on exactly the question we solved.
"""
from __future__ import annotations

import hashlib
import math
import random
import re
import time
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Callable, Dict, Iterable, List, Optional, Sequence

import sympy as sp

from .text import exact, Question, Slot, fmt_num, frac, terminating


@dataclass
class Item:
    """One practice question, worked out."""
    question: str
    answer: str
    steps: List[str]
    wrong: List[str] = field(default_factory=list)
    kind: str = "maths"
    value: object = None              # the exact answer (a sympy number when there is one), for niceness checks


class Spec:
    """What a family understood about a question (a free-form bag of attributes)."""

    def __init__(self, **kw):
        self.__dict__.update(kw)


class Family:
    """A kind of question.
    - parse() reads a Question (None = not mine).
    - solve() works out a version from slot values (None = not a good version). With full=False it only needs the
      answer and its value; the steps and wrong options are made only for versions that are kept.
    - vary() proposes new slot values."""
    name = "family"
    kind = "maths"                    # the chip the SQE window shows ("Differentiation", "Equations" …)

    def parse(self, q: Question) -> Optional[Spec]:
        return None

    def solve(self, q: Question, spec: Spec, vals: Sequence[Fraction], full: bool = True) -> Optional[Item]:
        return None

    def vary(self, q: Question, spec: Spec, rng: random.Random) -> Optional[List[Fraction]]:
        return vary_slots(q, getattr(spec, "free", None), rng)

    def nice(self, base: Item, item: Item) -> bool:
        return like(item.value, base.value)


# ── new numbers like the student's ───────────────────────────────────────────────────────────────────────────

def similar_int(a: int, rng: random.Random, *, allow_one: bool = False) -> int:
    """A new whole number about the size of a (a ≥ 0): 7 -> 2..9, 84 -> 42..99, 5000 -> 2000..9000, 126 -> 63..252."""
    if a <= 1:
        return a
    z = 0
    while a % 10 ** (z + 1) == 0 and a // 10 ** (z + 1) >= 1:
        z += 1
    if z >= 1 and rng.random() < 0.5:                  # 100 -> 150, 200 -> 120: one digit finer, within ×½…×2
        step = 10 ** (z - 1)
        lo, hi = max(step, a // 2), a * 2
        for _ in range(6):
            k = rng.randrange(lo, hi + 1, step)
            if k != a and k % (5 * step) == 0:         # still a round number (…50, …00)
                return k
    r, m = 10 ** z, a // 10 ** z
    if m < 10:
        lo, hi = (1 if allow_one else 2), 9
        if z >= 1:                                      # 200 -> 100…400, not 900
            lo, hi = max(1, m // 2), min(9, m * 2)
            if hi <= lo:
                hi = lo + 1
    elif m < 100:
        lo, hi = max(10, m // 2), min(99, m * 2)
    else:
        lo, hi = m // 2, m * 2
    for _ in range(6):
        k = rng.randint(lo, hi)
        if k != m:
            return k * r
    return (m + 1) * r


def new_value(s: Slot, rng: random.Random, *, flip: float = 0.0, allow_one: bool = False) -> Fraction:
    """A new number for one slot: same sign (unless flipped), same kind (whole / decimal places), similar size."""
    v = s.value
    sign = -1 if v < 0 else 1
    if flip and rng.random() < flip:
        sign = -sign
    a = abs(v)
    if a == 1:
        return Fraction(sign * rng.randint(2, 9))
    if a.denominator == 1:
        return Fraction(sign * similar_int(int(a), rng, allow_one=allow_one))
    scale = 10 ** max(1, s.dp)
    n = similar_int(int(round(a * scale)), rng, allow_one=True)
    return Fraction(sign * n, scale)


def varying(q: Question, idxs: Optional[Iterable[int]] = None) -> List[int]:
    """The slots that may change: every plain number or coefficient except the structural 0 and 1 — unless 1s are
    all there is ("1/x", "x + 1"), then those."""
    pool = list(range(len(q.slots)) if idxs is None else idxs)
    out = [i for i in pool if q.slots[i].role in ("num", "coef") and abs(q.slots[i].value) > 1]
    return out or [i for i in pool if q.slots[i].role in ("num", "coef") and abs(q.slots[i].value) == 1]


def vary_slots(q: Question, idxs: Optional[Iterable[int]], rng: random.Random, *, flip: float = 0.0,
               fixed: Optional[Dict[int, Fraction]] = None) -> List[Fraction]:
    vals = list(q.vals)
    pool = varying(q, idxs)
    if pool and all(abs(q.slots[i].value) == 1 for i in pool) and len(pool) > 1:
        pool = [i for i in pool if rng.random() < 0.5] or [rng.choice(pool)]   # only 1s: change some of them
    for i in pool:
        vals[i] = new_value(q.slots[i], rng, flip=flip)
    for i, v in (fixed or {}).items():
        vals[i] = Fraction(v)
    return vals


# ── how clean an answer is ───────────────────────────────────────────────────────────────────────────────────

def shape(v):
    """('int',) | ('dec', places) | ('frac', denominator) | ('irr',) | ('none',)"""
    if v is None:
        return ("none",)
    try:
        v = exact(v) if isinstance(v, float) else sp.sympify(v)
    except Exception:                                                        # noqa: BLE001
        return ("none",)
    if isinstance(v, (list, tuple)):
        return ("none",)
    if v.is_Integer:
        return ("int",)
    if v.is_Rational:
        if terminating(v, 6):
            return ("dec", len(str(float(v)).split(".")[-1].rstrip("0")))
        return ("frac", int(v.q))
    if getattr(v, "is_number", False):
        return ("irr",)
    return ("none",)


def like(new, orig) -> bool:
    """Is a version's answer as clean as the original's? (whole -> whole, short decimal -> short decimal …)"""
    if isinstance(orig, (list, tuple)):
        return isinstance(new, (list, tuple)) and len(new) == len(orig) and all(like(a, b) for a, b in zip(new, orig))
    so, sn = shape(orig), shape(new)
    if so[0] == "none":
        return True
    if sn[0] == "none":
        return False
    try:
        if sp.sympify(new) == 0 and sp.sympify(orig) != 0:                  # x = 0 is too easy a version
            return False
    except Exception:                                                        # noqa: BLE001
        pass
    try:
        if abs(float(sp.N(new))) > max(1e6, 1000 * abs(float(sp.N(orig)))):
            return False
    except Exception:                                                        # noqa: BLE001
        pass
    if so[0] == "int":
        return sn[0] == "int"
    if so[0] == "irr":                                   # a surd or π answer: any real number of that kind
        return sn[0] in ("irr", "int", "dec", "frac")
    qo = int(exact(orig).q) if so[0] in ("dec", "frac") else 1
    qn = int(exact(new).q) if sn[0] in ("dec", "frac") else 1
    if qo <= 20:                                         # a simple fraction (1/4, 5/2, 2/3): any simple fraction
        return sn[0] == "int" or (sn[0] in ("dec", "frac") and qn <= 20) or (sn[0] == "dec" and sn[1] <= 2)
    if so[0] == "dec":                                   # a measured decimal (2.08): a short decimal
        return sn[0] == "int" or (sn[0] == "dec" and sn[1] <= max(so[1], 2))
    if so[0] == "frac":
        return sn[0] in ("int", "dec") or (sn[0] == "frac" and qn <= max(20, qo))
    return True


def is_whole(v) -> bool:
    v = exact(v)
    return bool(v.is_Integer)


# ── back-solving: choose the answer first, then the numbers that give it ───────────────────────────────────────

def _rational_roots(P, x) -> Dict:
    try:
        poly = sp.Poly(sp.expand(P), x)
    except Exception:                                                        # noqa: BLE001
        return {}
    if poly.degree() < 1 or poly.degree() > 6:
        return {}
    try:
        return {r: m for r, m in sp.roots(poly, filter="Q").items()}
    except Exception:                                                        # noqa: BLE001
        return {}


def _new_root(r: sp.Rational, rng: random.Random, used: set) -> sp.Rational:
    """A new rational root like r: whole -> whole of similar size; p/q -> p'/q with p' coprime to q."""
    q = int(r.q)
    a = abs(int(r.p))
    for _ in range(20):
        if q == 1:
            m = rng.randint(1, max(9, min(15, 2 * a)))
        else:
            m = rng.randint(1, max(9, 2 * a))
            if math.gcd(m, q) != 1:
                continue
        cand = sp.Rational(m, q)
        if cand not in used:
            return cand
    return sp.Rational(a, q)


def keep_roots(q: Question, polys: Sequence[sp.Expr], x: sp.Symbol, rng: random.Random, *,
               free: Optional[Iterable[int]] = None, flip_roots: float = 0.35,
               max_size: int = 60, same_sign: bool = False) -> Optional[List[Fraction]]:
    """New slot values where each polynomial (a template in the slot symbols) keeps rational roots like the
    original's.
    - A root shared by two polynomials stays shared, and r and -r stay a pair.
    - Other slots vary freely, except that a polynomial with fractional roots keeps its non-solved slots, so the
      denominators still work.
    Returns None when the numbers don't come out clean (the caller just tries again)."""
    orig = q.subs(q.vals)
    fixed = {q.S[i]: orig[q.S[i]] for i, s in enumerate(q.slots) if s.role in ("exp", "base", "ord")}
    polys = [sp.expand(P.subs(fixed)) for P in polys]                      # exponents are never solved for
    plans = []
    for P in polys:
        roots = _rational_roots(P.subs(orig), x)
        if roots:
            plans.append((P, roots))
    if not plans:
        return None
    # new magnitudes per |root| class, signs kept (a whole class may flip)
    classes, used = {}, set()
    for _, roots in plans:
        for r in roots:
            a = abs(r)
            if a not in classes:
                if a == 0:
                    classes[a] = (sp.Integer(0), 1)
                else:
                    na = _new_root(a, rng, used)
                    used.add(na)
                    classes[a] = (na, -1 if rng.random() < flip_roots else 1)
    newroot = lambda r: (0 if r == 0 else classes[abs(r)][0] * classes[abs(r)][1] * (1 if r > 0 else -1))
    vals = list(q.vals)
    frac_polys = {id(P) for P, roots in plans if any(r.q != 1 for r in roots)}
    free_set = set(varying(q, free))
    in_frac = set()
    for P, _ in plans:
        if id(P) in frac_polys:
            in_frac |= set(q.slot_symbols(P))
    for i in free_set - in_frac:
        vals[i] = new_value(q.slots[i], rng)
    # choose the slots to solve for: per polynomial, as many as it has root conditions, lowest power of x first
    eqs, deps, short_eqs, picked = [], [], [], []
    for P, roots in plans:
        need = sum(roots.values())
        cands = []
        Pe = sp.expand(P)
        for i in q.slot_symbols(P):
            s = q.slots[i]
            if s.role in ("exp", "base", "ord") or i in deps or s.value == 0:     # never solve for "= 0"
                continue
            S = q.S[i]
            power = min((sp.Poly(term, x).degree() if term.has(x) else 0)
                        for term in sp.Add.make_args(Pe) if term.has(S)) if Pe.has(S) else 99
            cands.append((power, -i, i))
        cands.sort()
        chosen, powers = [], set()
        for power, _, i in cands:                       # one per power of x first, so the conditions are independent
            if len(chosen) < need and power not in powers:
                chosen.append(i)
                powers.add(power)
        for _, _, i in cands:
            if len(chosen) < need and i not in chosen:
                chosen.append(i)
        if not chosen:                                  # fewer is fine when conditions coincide (roots ±r)
            return None
        deps += chosen
        picked.append(len(chosen))
    for (P, roots), k_chosen in zip(plans, picked):     # all the solved-for slots stay unknown together
        known = {q.S[k]: sp.Rational(frac(vals[k]).numerator, frac(vals[k]).denominator)
                 for k in q.slot_symbols(P) if k not in deps}
        Pk = P.subs(known)
        conds = []
        for r, mult in roots.items():
            rr = newroot(r)
            for d in range(mult):
                conds.append(sp.expand(sp.diff(Pk, x, d).subs(x, rr)))
        eqs += conds
        short_eqs += conds[:k_chosen]                   # if the roots are tied (no slot for a term), fix only some
    syms = [q.S[i] for i in deps]
    sol = None
    while len(syms) > 1:                                # tied roots (±r): fewer unknowns may be all it takes
        try:
            A, b = sp.linear_eq_to_matrix(eqs, syms)
            if A.rank() >= len(syms):
                break
        except Exception:                                                    # noqa: BLE001
            break
        drop = deps.pop()                               # the highest-power one goes back to a free number
        syms.pop()
        vals[drop] = q.vals[drop] if drop in in_frac else new_value(q.slots[drop], rng)
        eqs = [sp.expand(e.subs(q.S[drop], sp.Rational(frac(vals[drop]).numerator, frac(vals[drop]).denominator))) for e in eqs]
        short_eqs = [sp.expand(e.subs(q.S[drop], sp.Rational(frac(vals[drop]).numerator, frac(vals[drop]).denominator))) for e in short_eqs]
    for system in (eqs, short_eqs):
        try:
            A, b = sp.linear_eq_to_matrix(system, syms)
        except Exception:                                                    # noqa: BLE001 - not linear in them
            return None
        if A.shape[0] < A.shape[1] or A.rank() < len(syms):
            continue
        try:
            found = list(sp.linsolve((A, b), syms))
        except Exception:                                                    # noqa: BLE001
            continue
        if len(found) == 1:
            sol = found
            break
    if sol is None:
        return None
    trial = {q.S[k]: sp.Rational(frac(v).numerator, frac(v).denominator) for k, v in enumerate(vals)}
    trial.update({S: exact(v) for S, v in zip(syms, sol[0])})
    for P, roots in plans:                              # every polynomial must still have roots like its old ones
        got = _rational_roots(P.subs(trial), x)
        if sum(got.values()) != sum(roots.values()):
            return None
        if all(r.q == 1 for r in roots) and not all(r.q == 1 for r in got):
            return None
    for i, v in zip(deps, sol[0]):
        v = exact(v)
        if not v.is_Rational:
            return None
        s = q.slots[i]
        fv = frac(v)
        if s.is_int and fv.denominator != 1:
            return None
        if not s.is_int and not terminating(v, max(1, s.dp) + 1):
            return None
        if s.value != 0 and fv == 0:
            return None
        if same_sign and (fv < 0) != (s.value < 0):
            return None
        if abs(fv) > max(max_size, 6 * abs(s.value)):
            return None
        vals[i] = fv
    return vals


def back_solve(q: Question, cond: sp.Expr, dep: int, vals: List[Fraction]) -> Optional[Fraction]:
    """The value of one slot that makes cond == 0, with every other slot at vals (cond linear in that slot)."""
    S = q.S[dep]
    known = {q.S[k]: sp.Rational(frac(v).numerator, frac(v).denominator) for k, v in enumerate(vals) if k != dep}
    e = sp.expand(cond.subs(known))
    a, b = e.coeff(S, 1), e.coeff(S, 0)
    if sp.expand(e - a * S - b) != 0 or a == 0:
        return None
    v = exact(-b / a)
    if not v.is_Rational:
        return None
    return frac(v)


# ── answers to options ───────────────────────────────────────────────────────────────────────────────────────

def numeric_wrong(v, fmt: Callable, extra: Sequence = ()) -> List[str]:
    """Wrong numbers students really get, then near misses, all written like the answer."""
    out = []
    right = fmt(v)
    cands = list(extra)
    try:
        fv = exact(v)
        cands += [fv * 2, fv / 2, fv * 10, fv / 10, -fv, fv + 1, fv - 1, fv + 2, fv * 3, fv + 10]
    except Exception:                                                        # noqa: BLE001
        pass
    for c in cands:
        try:
            s = fmt(c)
        except Exception:                                                    # noqa: BLE001
            continue
        if s and s != right and s not in out:
            out.append(s)
    return out


_PROBES = (sp.Rational(37, 100), sp.Rational(121, 100), sp.Rational(213, 100), sp.Rational(-89, 100))


def same_expr(a, b) -> bool:
    """Equal as functions? Checked at a few points (fast), so no slow simplify."""
    a, b = sp.sympify(a), sp.sympify(b)
    syms = sorted((a.free_symbols | b.free_symbols), key=lambda s: s.name)
    if not syms:
        try:
            return abs(complex(sp.N(a - b))) < 1e-9 * max(1.0, abs(complex(sp.N(b))))
        except Exception:                                                    # noqa: BLE001
            return False
    hits = 0
    for k, p in enumerate(_PROBES):
        pt = {s: p + sp.Rational(j, 7) for j, s in enumerate(syms)}
        try:
            va, vb = complex(sp.N(a.subs(pt))), complex(sp.N(b.subs(pt)))
        except Exception:                                                    # noqa: BLE001
            continue
        if not (math.isfinite(va.real) and math.isfinite(vb.real)):
            continue
        if abs(va - vb) > 1e-7 * max(1.0, abs(vb)):
            return False
        hits += 1
    return hits >= 2


def expr_wrong(right: sp.Expr, cands: Iterable, fmt: Callable) -> List[str]:
    """Wrong expressions (common mistakes first), skipping any that equal the right one."""
    out, rs = [], fmt(right)
    for c in cands:
        if c is None:
            continue
        try:
            c = sp.sympify(c)
            if same_expr(c, right):
                continue
            s = fmt(c)
        except Exception:                                                    # noqa: BLE001
            continue
        if s and s != rs and s not in out:
            out.append(s)
        if len(out) >= 6:
            break
    return out


def shuffled_options(item: Item) -> Optional[List[str]]:
    wrong = [w for w in dict.fromkeys(item.wrong) if w and w != item.answer]
    if len(wrong) < 3:
        return None
    opts = [item.answer] + wrong[:3]
    return sorted(opts, key=lambda o: hashlib.md5((item.question + "|" + o).encode()).hexdigest())


def canon(text: str) -> str:
    """The same question however it's spaced or bracketed: 'sin x' = 'sin(x)'."""
    s = re.sub(r"\s+", "", text.lower())
    return re.sub(r"\(([a-z])\)", r"\1", s)


# ── making versions ─────────────────────────────────────────────────────────────────────────────────────────

def make_versions(q: Question, fam: Family, spec: Spec, base: Item, n: int, rng: random.Random,
                  seen: set, deadline: float) -> List[Item]:
    out: List[Item] = []
    seen.add(canon(q.display))                          # never the student's own question back
    tries, limit = 0, max(60, n * 30)
    while len(out) < n and tries < limit and time.monotonic() < deadline:
        tries += 1
        try:
            vals = fam.vary(q, spec, rng)
        except Exception:                                                    # noqa: BLE001 - a bad draw
            vals = None
        if not vals or [Fraction(v) for v in vals] == q.vals:                # the student's own numbers again
            continue
        text = q.render(vals)
        key = canon(text)
        if key in seen:
            continue
        try:
            item = fam.solve(q, spec, vals, full=False)
        except Exception:                                                    # noqa: BLE001
            item = None
        if item is None or not fam.nice(base, item):
            continue
        # read the displayed text back from scratch: it must be the same question with the same answer
        try:
            q2 = Question(text)
            spec2 = fam.parse(q2)
            again = fam.solve(q2, spec2, q2.vals, full=False) if spec2 is not None else None
        except Exception:                                                    # noqa: BLE001
            again = None
        if again is None or again.answer != item.answer:
            continue
        try:
            item = fam.solve(q, spec, vals, full=True)
        except Exception:                                                    # noqa: BLE001
            item = None
        if item is None:
            continue
        seen.add(key)
        out.append(item)
    return out
