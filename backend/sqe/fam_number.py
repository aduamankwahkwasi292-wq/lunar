"""
CUSTOM-SQE number families: HCF and LCM, prime factors, fractions and mixed numbers, standard form, significant
figures and decimal places, number bases, remainders (mod), percentages, square roots of decimals, and decimals as
fractions.

Versions are made answer-first where clean answers need it:
  - an HCF that isn't 1;
  - a number with several prime factors;
  - a percentage like 25%;
  - a perfect square under the root;
  - a base-2 number written with 0s and 1s only.
"""
from __future__ import annotations

import math
import random
import re
from fractions import Fraction
from functools import reduce
from typing import List, Optional

import sympy as sp

from .core import Family, Item, Spec, new_value, similar_int
from .text import Question, exact, fmt_num

fnum = lambda v: fmt_num(v, fractions=True)


def mixed(v: Fraction) -> str:
    """5/2 -> '2 1/2'; 3/4 -> '3/4'; 6 -> '6'."""
    v = Fraction(v)
    if v.denominator == 1:
        return str(v.numerator)
    sign = "-" if v < 0 else ""
    v = abs(v)
    w, r = divmod(v.numerator, v.denominator)
    return f"{sign}{w} {r}/{v.denominator}" if w else f"{sign}{r}/{v.denominator}"


def ival(vals, i) -> int:
    return int(Fraction(vals[i]))


def sci(x: Fraction, sig: Optional[int] = None) -> str:
    """0.000456 -> '4.56 × 10^-4'."""
    x = Fraction(x)
    if x == 0:
        return "0"
    e = math.floor(math.log10(abs(float(x))))
    m = x / Fraction(10) ** e
    if abs(m) >= 10:
        m /= 10
        e += 1
    mm = f"{float(m):.10g}" if sig is None else f"{float(m):.{max(0, sig - 1)}f}"
    return f"{mm} × 10^{e}"


class Number(Family):
    name = "number"
    kind = "number"

    def parse(self, q: Question) -> Optional[Spec]:
        low, sym = q.low, q.sym
        nums = [s.i for s in q.slots if s.role in ("num", "coef", "base", "ord")]
        if re.search(r"\b(?:hcf|gcd|highest\s+common\s+factor|greatest\s+common\s+divisor)\b", low):
            return Spec(task="hcf", ids=[s.i for s in q.slots if s.role in ("num", "coef")])
        if re.search(r"\b(?:lcm|lowest\s+common\s+multiple|least\s+common\s+multiple)\b", low):
            return Spec(task="lcm", ids=[s.i for s in q.slots if s.role in ("num", "coef")])
        if re.search(r"prime\s+factor", low) and len(nums) == 1:
            return Spec(task="primes", ids=nums)
        m = re.search(r"\bbase\s*(?:\(S\d+\)|two|ten|eight|2|10|8)\b.*\bto\s+base\s*(\(S\d+\)|two|ten|eight|sixteen|\d+)", low) or \
            re.search(r"\bconvert\b.*\bto\s+base\s*(\(S\d+\)|\w+)", low)
        if m and re.search(r"\bbase\b", low):
            words = {"two": 2, "ten": 10, "eight": 8, "sixteen": 16, "five": 5}
            bases = re.findall(r"base\s*(\d+|two|ten|eight|sixteen|five)", low)
            if len(bases) >= 2:
                b_from = words.get(bases[0], None) or int(bases[0])
                b_to = words.get(bases[1], None) or int(bases[1])
                digits = [s.i for s in q.slots if s.role in ("num", "coef") and str(int(s.value)) not in bases[:2]]
                if not digits:
                    return None
                return Spec(task="base", ids=digits[:1], b_from=b_from, b_to=b_to)
        if re.search(r"\bmod\b|\bmodulo\b|remainder\s+when\s+\(S\d+\)\s+is\s+divided", low) and len(nums) == 2:
            return Spec(task="mod", ids=nums)
        if re.search(r"standard\s+form|scientific\s+notation", low):
            if re.search(r"\b10\^|×\s*10", q.display):
                return Spec(task="sci_op", ids=[s.i for s in q.slots])
            if len(nums) == 1:
                return Spec(task="sci", ids=nums)
        m = re.search(r"(\(S\d+\))\s+(?:significant\s+figures?|s\.?\s?f\.?)\b", sym, re.I)
        if m:
            k = int(m.group(1)[2:-1])
            others = [i for i in nums if i != k]
            if len(others) == 1:
                return Spec(task="sf", ids=others, k=k)
        m = re.search(r"(\(S\d+\))\s+(?:decimal\s+places?|d\.?\s?p\.?)\b", sym, re.I)
        if m:
            k = int(m.group(1)[2:-1])
            others = [i for i in nums if i != k]
            if len(others) == 1:
                return Spec(task="dp", ids=others, k=k)
        if re.search(r"as\s+a\s+fraction|fraction\s+in\s+its\s+(?:lowest|simplest)|in\s+its\s+simplest\s+form", low) and len(nums) == 1 \
                and not q.slots[nums[0]].is_int:
            return Spec(task="tofrac", ids=nums)
        if re.search(r"\bsquare\s+root\s+of\b|√|sqrt", low) and len(nums) == 1 and not q.slots[nums[0]].is_int:
            return Spec(task="sqrt", ids=nums)
        m = re.search(r"(\(S\d+\))\s*%\s*of\s*(?:GH¢|GHS)?\s*(\(S\d+\))", sym)
        if m and not re.search(r"\bincrease|\bdecrease|\bspend|\bsave|\bsalary", low):
            return Spec(task="pct_of", ids=[int(m.group(1)[2:-1]), int(m.group(2)[2:-1])])
        m = re.search(r"(?:express|write)\s+(?:GH¢|GHS)?\s*(\(S\d+\))\s+as\s+a\s+percentage\s+of\s+(?:GH¢|GHS)?\s*(\(S\d+\))", sym, re.I)
        if m:
            return Spec(task="as_pct", ids=[int(m.group(1)[2:-1]), int(m.group(2)[2:-1])])
        # fraction arithmetic: 2 3/4 + 1 5/6 ; 3/5 of 2 1/2 divided by 3/4
        if re.search(r"(\(S\d+\))\s*/\s*(\(S\d+\))", sym) and re.search(r"\bsimplify|\bevaluate|\bcalculate|\bwork\s+out|\bfind|\bwhat\s+is", low) \
                and not re.search(r"[a-z]\s*[\^(]|\bx\b", re.sub(r"\(S\d+\)", "", sym.split(":")[-1]).lower().replace("simplify", "")
                                  .replace("evaluate", "").replace("calculate", "").replace("of", "").replace("divided by", "")
                                  .replace("what is", "").replace("work out", "").replace("find", "").replace("multiplied by", "")):
            expr = sym
            expr = re.sub(r"^.*?\b(?:simplify|evaluate|calculate|work\s+out|find|what\s+is)\b\s*:?", "", expr, flags=re.I)
            # 2 3/4 -> (2 + 3/4); "- 1 2/3" (the slot holds -1) -> (-1 - 2/3): the sign covers the whole number
            expr = re.sub(r"(\(S\d+\))\s+(\(S\d+\))\s*/\s*(\(S\d+\))", r"(\1 + sign(\1)*\2/\3)", expr)
            expr = re.sub(r"(?<![+/])\s(\(S\d+\))\s*/\s*(\(S\d+\))(?!\s*\))", r" (\1/\2)", " " + expr)  # ÷ 3/7 is ÷ (3/7)
            expr = re.sub(r"\bof\b", "*", expr)
            expr = re.sub(r"\bdivided\s+by\b", "/", expr)
            expr = re.sub(r"\bmultiplied\s+by\b|\btimes\b", "*", expr)
            expr = expr.replace("×", "*").replace("÷", "/").strip().rstrip("?.")
            if re.search(r"[a-zA-Z](?<!S)", re.sub(r"\(S\d+\)|\bsign\b", "", expr)):
                return None
            try:
                e = sp.sympify(expr.replace("^", "**"), locals={**{f"S{k}": sp.Symbol(f"S{k}") for k in range(len(q.slots))}, "sign": sp.sign})
            except Exception:                                                # noqa: BLE001
                return None
            return Spec(task="fractions", e=e, ids=[s.i for s in q.slots], mixed=bool(re.search(r"\(S\d+\)\s+\(S\d+\)\s*/", sym)))
        return None

    def solve(self, q, spec, vals, full=True):
        t = spec.task
        text = q.render(vals)
        V = [Fraction(v) for v in vals]
        steps, wrong = [], []
        if t == "hcf":
            ns = [int(V[i]) for i in spec.ids]
            if any(n <= 0 for n in ns):
                return None
            h = reduce(math.gcd, ns)
            ans, value = str(h), sp.Integer(h)
            if full:
                steps = ["Write each number as a product of primes: " + "; ".join(f"{n} = {prime_text(n)}" for n in ns) + ".",
                         "Multiply the primes they share (lowest power of each).", f"HCF = {h}"]
                l = reduce(lambda a, b: a * b // math.gcd(a, b), ns)
                wrong = [str(x) for x in dict.fromkeys([l, h * 2, max(1, h // 2), min(ns), math.prod(ns) // h if len(ns) == 2 else h + 1]) if x != h]
        elif t == "lcm":
            ns = [int(V[i]) for i in spec.ids]
            if any(n <= 0 for n in ns):
                return None
            l = reduce(lambda a, b: a * b // math.gcd(a, b), ns)
            ans, value = str(l), sp.Integer(l)
            if full:
                steps = ["Write each number as a product of primes: " + "; ".join(f"{n} = {prime_text(n)}" for n in ns) + ".",
                         "Take every prime that appears, to its highest power, and multiply.", f"LCM = {l}"]
                wrong = [str(x) for x in dict.fromkeys([reduce(math.gcd, ns), math.prod(ns), l * 2, l // 2 if l % 2 == 0 else l + 6]) if x != l]
        elif t == "primes":
            n = int(V[spec.ids[0]])
            if n < 4 or sp.isprime(n):
                return None
            ans, value = prime_text(n), sp.Integer(len(sp.factorint(n)))
            if full:
                steps = ["Divide by the smallest prime that goes in, again and again: " + ladder(n) + ".", f"So {n} = {ans}"]
                f = sp.factorint(n)
                alt = []
                ps = sorted(f)
                alt.append(" × ".join(f"{p}" for p in ps))                            # each prime once
                g = dict(f)
                g[ps[0]] = g[ps[0]] + 1
                alt.append(prime_text_from(g))
                if len(ps) > 1:
                    h = dict(f)
                    h[ps[-1]] += 1
                    h[ps[0]] = max(1, h[ps[0]] - 1)
                    alt.append(prime_text_from(h))
                alt.append(" × ".join(str(p) for p in ps) + f" × {n // math.prod(ps)}" if n // math.prod(ps) > 1 else prime_text(n + 2))
                wrong = [a for a in alt if a != ans]
        elif t == "base":
            raw_digits = q.slots[spec.ids[0]].text if vals == q.vals else str(ival(vals, spec.ids[0]))
            digits = str(ival(vals, spec.ids[0]))
            try:
                n = int(digits, spec.b_from)
            except ValueError:
                return None
            out = to_base(n, spec.b_to)
            ans, value = f"{out}" if spec.b_to == 10 else f"{out} (base {spec.b_to})", sp.Integer(n)
            if full:
                if spec.b_from != 10:
                    steps = [" + ".join(f"{d}×{spec.b_from}^{len(digits) - 1 - k}" for k, d in enumerate(digits)) + f" = {n}"]
                else:
                    steps = [f"Divide by {spec.b_to} repeatedly and read the remainders from the bottom up: {n} -> {out}"]
                steps.append(f"So the answer is {ans}")
                wrong = [w for w in (str(int(digits[::-1], spec.b_from)) if spec.b_to == 10 else f"{out[::-1]} (base {spec.b_to})",
                                     str(n + spec.b_from) if spec.b_to == 10 else f"{to_base(n + 1, spec.b_to)} (base {spec.b_to})",
                                     str(n - 1) if spec.b_to == 10 else f"{to_base(max(1, n - 2), spec.b_to)} (base {spec.b_to})",
                                     str(2 * n) if spec.b_to == 10 else f"{to_base(n * 2, spec.b_to)} (base {spec.b_to})") if w != ans]
        elif t == "mod":
            a, b = int(V[spec.ids[0]]), int(V[spec.ids[1]])
            if b <= 1 or a <= b:
                return None
            r = a % b
            ans, value = str(r), sp.Integer(r)
            if full:
                steps = [f"{a} = {a // b} × {b} + {r}", f"So {a} mod {b} = {r}"]
                wrong = [str(x) for x in dict.fromkeys([a // b, b - r, (r + 1) % b, a % (b + 1)]) if x != r]
        elif t == "sci":
            x = V[spec.ids[0]]
            ans, value = sci(x), None
            if full:
                steps = ["Move the decimal point so there is one non-zero digit in front of it.",
                         "Count the places moved: that is the power of 10 (negative for small numbers).", f"So it is {ans}"]
                e = int(ans.split("^")[1])
                mant = ans.split(" ×")[0]
                wrong = [w for w in (f"{mant} × 10^{-e}", f"{mant} × 10^{e - 1}", f"{mant} × 10^{e + 1}",
                                     f"{float(Fraction(mant)) * 10:.10g} × 10^{e - 1}") if w != ans]
        elif t == "sci_op":
            nums_ = [V[s.i] for s in q.slots]
            disp = q.render(vals)
            parts = re.findall(r"(\d+(?:\.\d+)?)\s*[x×]\s*10\^\s*\(?(-?\d+)\)?", disp)
            if len(parts) != 2:
                return None
            (m1, e1), (m2, e2) = parts
            op = "/" if re.search(r"divided|÷|/\s*\(?\d", disp[disp.find(m1) + len(m1):]) else "*"
            a = Fraction(m1) * Fraction(10) ** int(e1)
            b = Fraction(m2) * Fraction(10) ** int(e2)
            r = a * b if op == "*" else a / b
            ans, value = sci(r), None
            if full:
                steps = [f"{'Multiply' if op == '*' else 'Divide'} the numbers in front: {m1} {'×' if op == '*' else '÷'} {m2}; "
                         f"{'add' if op == '*' else 'subtract'} the powers of 10.", f"Write the result in standard form: {ans}"]
                e = int(ans.split("^")[1])
                mant = ans.split(" ×")[0]
                wrong = [w for w in (f"{mant} × 10^{e + 1}", f"{mant} × 10^{e - 1}", f"{mant} × 10^{-e}", sci(a + b if op == '*' else a * b)) if w != ans]
        elif t in ("sf", "dp"):
            x, k = V[spec.ids[0]], int(V[spec.k])
            if k < 1 or k > 6:
                return None
            ans = round_sf(x, k) if t == "sf" else f"{float(x):.{k}f}"
            value = None
            if full:
                steps = [f"Look at the digit after the {'last kept figure' if t == 'sf' else str(k) + 'th decimal place'}: 5 or more rounds up, less leaves it.",
                         f"So it is {ans}"]
                alts = [round_sf(x, k + 1) if t == "sf" else f"{float(x):.{k + 1}f}",
                        round_sf(x, k - 1) if (t == "sf" and k > 1) else f"{float(x):.{max(0, k - 1)}f}",
                        truncate(x, k, t)]
                wrong = [w for w in dict.fromkeys(alts) if w != ans]
        elif t == "tofrac":
            x = V[spec.ids[0]]
            ans, value = f"{x.numerator}/{x.denominator}", sp.Rational(x.numerator, x.denominator)
            if full:
                dp = q.slots[spec.ids[0]].dp
                steps = [f"{float(x):g} = {int(x * 10 ** dp)}/{10 ** dp}", f"Divide top and bottom by {math.gcd(int(x * 10 ** dp), 10 ** dp)}: {ans}"]
                wrong = [w for w in dict.fromkeys([f"{int(x * 10 ** dp)}/{10 ** dp}", f"{x.denominator}/{x.numerator}",
                                                   f"{x.numerator}/{x.denominator * 2}", f"{x.numerator + 1}/{x.denominator}"]) if w != ans]
        elif t == "sqrt":
            x = V[spec.ids[0]]
            r = sp.sqrt(sp.Rational(x.numerator, x.denominator))
            if not r.is_Rational:
                return None
            ans, value = fmt_num(r), r
            if full:
                steps = [f"{float(x):g} = {sp.Rational(x.numerator, x.denominator)}", f"√ of a fraction = √top / √bottom = {r}", f"So it is {ans}"]
                wrong = [w for w in dict.fromkeys([fmt_num(r * 10), fmt_num(r / 10), fmt_num(sp.Rational(x.numerator, x.denominator) / 2)]) if w != ans]
        elif t == "pct_of":
            p, whole = V[spec.ids[0]], V[spec.ids[1]]
            r = p * whole / 100
            ans, value = fmt_num(sp.Rational(r.numerator, r.denominator)), sp.Rational(r.numerator, r.denominator)
            if full:
                steps = [f"{fmt_num(p)}% of {fmt_num(whole)} = {fmt_num(p)}/100 × {fmt_num(whole)} = {ans}"]
                wrong = [w for w in dict.fromkeys([fmt_num(sp.nsimplify(float(whole * 100 / p))) if p else "0", fmt_num(sp.Rational(p * whole)),
                                                   fmt_num(sp.Rational(whole - r)), fmt_num(sp.Rational(r * 10))]) if w != ans]
        elif t == "as_pct":
            part, whole = V[spec.ids[0]], V[spec.ids[1]]
            if whole == 0:
                return None
            r = part / whole * 100
            ans, value = f"{fmt_num(sp.Rational(r.numerator, r.denominator))}%", sp.Rational(r.numerator, r.denominator)
            if full:
                steps = [f"{fmt_num(part)}/{fmt_num(whole)} × 100 = {ans}"]
                wrong = [w for w in dict.fromkeys([f"{fmt_num(sp.Rational(whole * 100 / part))}%" if part else "0%",
                                                   f"{fmt_num(sp.Rational(part * whole / 100))}%", f"{fmt_num(sp.Rational(100 - r))}%"]) if w != ans]
        elif t == "fractions":
            e = spec.e.subs({sp.Symbol(f"S{k}"): sp.Rational(V[k].numerator, V[k].denominator) for k in range(len(V))})
            r = exact(e)
            if not r.is_Rational or r <= 0:
                return None
            fr = Fraction(int(r.p), int(r.q))
            ans, value = (mixed(fr) if spec.mixed or abs(fr) > 1 and fr.denominator != 1 else fnum(r)), None
            if fr.denominator > 72:
                return None
            if full:
                steps = ["Change mixed numbers to improper fractions first.",
                         "Add or subtract over a common denominator; multiply tops and bottoms; to divide, multiply by the reciprocal.",
                         f"So the answer is {ans}"]
                alts = [fr + 1, fr - Fraction(1, fr.denominator) if fr.denominator > 1 else fr - 1, 1 / fr, fr * 2]
                wrong = [w for w in dict.fromkeys(mixed(a) for a in alts if a > 0) if w != ans]
        else:
            return None
        if not full:
            return Item(text, ans, [], [], self.kind, value=value)
        return Item(text, ans, steps, wrong, self.kind, value=value)

    def vary(self, q, spec, rng):
        t = spec.task
        vals = list(q.vals)
        V = [Fraction(v) for v in q.vals]
        if t == "hcf":
            ns = [int(V[i]) for i in spec.ids]
            h0 = reduce(math.gcd, ns)
            h = similar_int(h0, rng) if h0 > 1 else 1
            for _ in range(30):                              # n_i = h × k_i with the k_i sharing nothing
                ks = [max(2, n // max(1, h0) + rng.randint(-2, 2)) for n in ns]
                if reduce(math.gcd, ks) == 1 and len(set(ks)) == len(ks):
                    for i, k in zip(spec.ids, ks):
                        vals[i] = Fraction(h * k)
                    return vals
            return None
        if t == "primes":
            n0 = int(V[spec.ids[0]])
            want = sum(sp.factorint(n0).values())
            for _ in range(40):
                n = similar_int(n0, rng)
                f = sp.factorint(n)
                if sum(f.values()) >= max(3, want - 1) and max(f) <= 13 and n != n0:
                    vals[spec.ids[0]] = Fraction(n)
                    return vals
            return None
        if t == "base":
            s = q.slots[spec.ids[0]].text.replace(",", "")
            if spec.b_from == 10:
                vals[spec.ids[0]] = Fraction(similar_int(int(s), rng))
                return vals
            L = len(s)
            for _ in range(10):
                digits = str(rng.randint(1, spec.b_from - 1)) + "".join(str(rng.randint(0, spec.b_from - 1)) for _ in range(L - 1))
                if digits != s:
                    vals[spec.ids[0]] = Fraction(int(digits))
                    return vals
            return None
        if t == "sqrt":
            x = V[spec.ids[0]]
            dp = q.slots[spec.ids[0]].dp
            half = dp // 2
            r = rng.randint(2, 30)
            vals[spec.ids[0]] = Fraction(r * r, 10 ** (2 * half))
            return vals
        if t == "tofrac":
            dp = q.slots[spec.ids[0]].dp
            dens = [d for d in (2, 4, 5, 8, 10, 16, 20, 25, 40, 50) if len(str(Fraction(1, d)).split("/")) and (10 ** dp) % d == 0 and d > 10 ** (dp - 1) / 2]
            dens = dens or [8]
            d = rng.choice(dens)
            n = rng.choice([k for k in range(1, d) if math.gcd(k, d) == 1])
            vals[spec.ids[0]] = Fraction(n, d)
            return vals
        if t == "as_pct":
            whole = similar_int(int(V[spec.ids[1]]), rng) if V[spec.ids[1]] > 1 else 80
            p = rng.choice([10, 20, 25, 30, 40, 50, 60, 75, 80, 12.5, 5, 15, 35, 45])
            part = Fraction(str(p)) * whole / 100
            if part.denominator != 1 or part == V[spec.ids[0]]:
                return None
            vals[spec.ids[0]], vals[spec.ids[1]] = part, Fraction(whole)
            return vals
        if t == "fractions":
            return self._fractions(q, spec, rng)
        if t in ("sf", "dp"):
            x = V[spec.ids[0]]
            dp = q.slots[spec.ids[0]].dp
            k = int(V[spec.k])
            digits = rng.randint(10 ** (len(str(int(abs(x) * 10 ** dp))) - 1), 10 ** len(str(int(abs(x) * 10 ** dp))) - 1)
            vals[spec.ids[0]] = Fraction(digits, 10 ** dp)
            if rng.random() < 0.4:
                vals[spec.k] = Fraction(max(1, min(4, k + rng.choice([-1, 1]))))
            return vals
        if t == "sci":
            x = V[spec.ids[0]]
            dp = q.slots[spec.ids[0]].dp
            s = q.slots[spec.ids[0]].text
            sig = len(s.replace(".", "").replace(",", "").lstrip("0"))
            mant = rng.randint(10 ** (sig - 1), 10 ** sig - 1)
            if x < 1:
                lead0 = len(s.split(".")[1]) - len(s.split(".")[1].lstrip("0")) + rng.choice([-1, 0, 1])
                lead0 = max(0, lead0)
                vals[spec.ids[0]] = Fraction(mant, 10 ** (lead0 + sig))
            else:
                vals[spec.ids[0]] = Fraction(mant * 10 ** max(0, len(str(int(x))) - sig + rng.choice([-1, 0, 1])))
            return vals
        if t == "sci_op":
            for s in q.slots:
                if s.role == "exp":
                    vals[s.i] = Fraction(int(s.value) + rng.randint(-2, 2) or 1)
                elif s.text != "10":
                    vals[s.i] = new_value(s, rng)
            return vals
        if t == "mod":
            vals[spec.ids[0]] = Fraction(similar_int(int(V[spec.ids[0]]), rng))
            vals[spec.ids[1]] = Fraction(rng.randint(3, 12))
            return vals
        if t == "pct_of":
            for _ in range(20):
                p = rng.choice([5, 10, 15, 20, 25, 30, 35, 40, 45, 60, 75, 12.5, 2.5])
                whole = similar_int(int(V[spec.ids[1]]), rng)
                r = Fraction(str(p)) * whole / 100
                if r.denominator == 1 and Fraction(str(p)) != V[spec.ids[0]]:
                    vals[spec.ids[0]], vals[spec.ids[1]] = Fraction(str(p)), Fraction(whole)
                    return vals
            return None
        for i in spec.ids:
            if q.slots[i].role in ("num", "coef") and q.vals[i] > 1:
                vals[i] = new_value(q.slots[i], rng)
        return vals

    def _fractions(self, q, spec, rng):
        """New proper fractions with small denominators; whole parts stay whole."""
        vals = list(q.vals)
        disp = q.display
        pairs = re.finditer(r"(\d+)\s*/\s*(\d+)", disp)
        spans = {s.start: s.i for s in q.slots}
        for m in pairs:
            ni, di = spans.get(m.start(1)), spans.get(m.start(2))
            if ni is None or di is None:
                continue
            d = rng.choice([2, 3, 4, 5, 6, 7, 8, 9, 10, 12])
            nn = rng.choice([k for k in range(1, d) if math.gcd(k, d) == 1])
            vals[ni], vals[di] = Fraction(nn), Fraction(d)
        for s in q.slots:
            if s.role in ("num", "coef") and not any(s.i in (spans.get(m.start(1)), spans.get(m.start(2))) for m in re.finditer(r"(\d+)\s*/\s*(\d+)", disp)):
                if s.value >= 1:
                    vals[s.i] = Fraction(rng.randint(1, max(4, int(s.value) + 2)))
        return vals

    def nice(self, base, item):
        if base.value is None or item.value is None:
            return True
        b, v = exact(base.value), exact(item.value)
        if self and b.is_Integer:
            return v.is_Integer and 0 < v <= max(100, 6 * b)
        if b.is_Rational:
            return v.is_Rational and v.q <= max(24, b.q * 2)
        return True


def prime_text_from(f: dict) -> str:
    return " × ".join(f"{p}^{e}" if e > 1 else str(p) for p, e in sorted(f.items()))


def prime_text(n: int) -> str:
    return prime_text_from(sp.factorint(n))


def ladder(n: int) -> str:
    out, m = [], n
    for p in sorted(sp.factorint(n)):
        while m % p == 0:
            out.append(f"{m} ÷ {p} = {m // p}")
            m //= p
    return ", ".join(out[:6]) + (", …" if len(out) > 6 else "")


def to_base(n: int, b: int) -> str:
    if b == 10:
        return str(n)
    digits = "0123456789ABCDEF"
    out = ""
    while n:
        out = digits[n % b] + out
        n //= b
    return out or "0"


def round_sf(x: Fraction, k: int) -> str:
    v = float(x)
    if v == 0:
        return "0"
    d = k - 1 - math.floor(math.log10(abs(v)))
    r = round(v, d)
    return f"{r:.{max(0, d)}f}" if d > 0 else f"{int(round(r))}"


def truncate(x: Fraction, k: int, t: str) -> str:
    v = float(x)
    if t == "dp":
        f = 10 ** k
        return f"{math.floor(v * f) / f:.{k}f}"
    d = k - 1 - math.floor(math.log10(abs(v)))
    f = 10 ** d
    r = math.floor(v * f) / f
    return f"{r:.{max(0, d)}f}" if d > 0 else f"{int(r)}"
