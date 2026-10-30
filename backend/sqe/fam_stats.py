"""
CUSTOM-SQE statistics and probability:
  - the mean, median, mode, range, variance and standard deviation of a list;
  - simple probability (a bag of balls, two dice, coins);
  - arrangements, nPr and nCr, committees;
  - the probability that something does not happen.

A list's versions are made with a new scale and shift (k·x + c, sometimes reordered), so the shape that made the
original work stays: a mode stays a mode, and a whole standard deviation stays whole. Probabilities are exact
fractions in lowest terms.
"""
from __future__ import annotations

import math
import random
import re
from fractions import Fraction
from itertools import product
from typing import List, Optional

import sympy as sp

from .core import Family, Item, Spec, numeric_wrong, similar_int
from .text import Question, exact, fmt_num, fmt_sig

fnum = lambda v: fmt_num(v, fractions=True)
_WORDS = ["MATHS", "PAPER", "GHANA", "ACCRA", "BOOKS", "TABLE", "LEMON", "APPLE", "SCHOOL", "LETTER", "BANANA", "KUMASI",
          "EXAM", "TEST", "NUMBER", "ALGEBRA", "MANGO", "PENCIL", "RULER", "COCOA", "GARDEN", "MOTHER", "STREET"]


def the_list(q: Question) -> List[int]:
    """Slots of a list of 3+ numbers separated by commas (or 'and')."""
    d = q.display
    runs, cur, last = [], [], -1
    for s in q.slots:
        gap = d[last:s.start] if last >= 0 else ""
        if cur and re.fullmatch(r"\s*(?:,|,?\s*and)\s*", gap):
            cur.append(s.i)
        else:
            if len(cur) >= 3:
                runs.append(cur)
            cur = [s.i]
        last = s.end
    if len(cur) >= 3:
        runs.append(cur)
    return max(runs, key=len) if runs else []


def stats_of(xs: List[Fraction]):
    n = len(xs)
    mean = sum(xs) / n
    srt = sorted(xs)
    med = srt[n // 2] if n % 2 else (srt[n // 2 - 1] + srt[n // 2]) / 2
    counts = {}
    for x in xs:
        counts[x] = counts.get(x, 0) + 1
    top = max(counts.values())
    modes = sorted(x for x, c in counts.items() if c == top) if top > 1 else []
    var = sum((x - mean) ** 2 for x in xs) / n
    return {"mean": mean, "median": med, "modes": modes, "range": srt[-1] - srt[0], "var": var, "sd": sp.sqrt(sp.Rational(var.numerator, var.denominator))}


def show(v) -> str:
    v = exact(v)
    if v.is_Rational:
        return fnum(v) if v.q <= 20 else fmt_sig(float(v), 3)
    return fmt_sig(float(v), 3)


class Statistics(Family):
    name = "statistics"
    kind = "statistics"

    def parse(self, q: Question) -> Optional[Spec]:
        low = q.low
        lst = the_list(q)
        want = [w for w in ("mean", "median", "mode", "range", "variance", "standard deviation") if re.search(rf"\b{w}\b", low)]
        if lst and want:
            return Spec(task="list", ids=lst, want=want)
        if re.search(r"\barranged?\b|\barrangements?\b", low) and re.search(r"letters\s+of\s+the\s+word\s+([A-Z]{3,})", q.display, re.I):
            return Spec(task="word", word=re.search(r"letters\s+of\s+the\s+word\s+([A-Za-z]{3,})", q.display).group(1).upper())
        nums = [s.i for s in q.slots if s.role in ("num", "coef")]
        m = re.search(r"(\(S\d+\))\s*([cp])\s*(\(S\d+\))", q.sym, re.I)
        if m:
            return Spec(task="nCr" if m.group(2).lower() == "c" else "nPr", ids=[int(m.group(1)[2:-1]), int(m.group(3)[2:-1])])
        if re.search(r"\bdice\b|\bdie\b", low) and re.search(r"\bsum\b|\btotal\b", low):
            target = [i for i in nums if 2 <= q.vals[i] <= 12]
            return Spec(task="dice", ids=target[-1:]) if target else None
        if re.search(r"\bcoin\b", low) and re.search(r"exactly", low) and len(nums) >= 2:
            return Spec(task="coin", ids=nums[:2], tails=bool(re.search(r"\btails?\b", low)))
        if re.search(r"\bprobability\b", low) and re.search(r"\bnot\b|\bfails?\b|\bdoes\s+not\b|\bwon'?t\b", low) and len(nums) == 1 and not q.slots[nums[0]].is_int:
            return Spec(task="complement", ids=nums)
        if re.search(r"\bprobability\b", low) and re.search(r"\bbag\b|\bbox\b|\bbasket\b|\bpicked\b|\bchosen\b|\bat\s+random\b", low):
            groups = re.findall(r"(\(S\d+\))\s+([a-z]+)", q.sym)
            ids = [int(g[0][2:-1]) for g in groups if g[1] not in ("cm", "kg", "times")]
            names = [g[1] for g in groups if g[1] not in ("cm", "kg", "times")]
            target = re.search(r"(?:that\s+it\s+is|is\s+an?|being|of\s+(?:picking|getting|choosing)\s+an?)\s+([a-z]+)", q.low)
            if len(ids) >= 2 and target and target.group(1) in names:
                return Spec(task="bag", ids=ids, names=names, target=names.index(target.group(1)))
        if re.search(r"\b(?:ways|arrangements?|arranged)\b", low):
            m = re.search(r"\bcommittee\s+of\s+(\(S\d+\))\b.*\bfrom\s+(\(S\d+\))", q.sym, re.I) or \
                re.search(r"\b(?:select|choose|chosen|picked|selected)\b.*?(\(S\d+\)).*?\bfrom\s+(\(S\d+\))", q.sym, re.I) or \
                re.search(r"(\(S\d+\))\s+\w+\s+(?:be\s+)?(?:selected|chosen|picked)\s+from\s+(\(S\d+\))", q.sym, re.I)
            if m:
                return Spec(task="choose", ids=[int(m.group(2)[2:-1]), int(m.group(1)[2:-1])])
            if len(nums) == 1 and re.search(r"\b(?:row|line|order|arranged|arrangements?)\b", low):
                return Spec(task="fact", ids=nums)
        return None

    def solve(self, q, spec, vals, full=True):
        V = [Fraction(v) for v in vals]
        text = q.render(vals)
        t = spec.task
        if t == "list":
            xs = [V[i] for i in spec.ids]
            st = stats_of(xs)
            parts, val = [], []
            for w in spec.want:
                if w == "mean":
                    parts.append(f"mean = {show(st['mean'])}")
                    val.append(st["mean"])
                elif w == "median":
                    parts.append(f"median = {show(st['median'])}")
                    val.append(st["median"])
                elif w == "mode":
                    if not st["modes"] or len(st["modes"]) > 1:
                        return None
                    parts.append(f"mode = {show(st['modes'][0])}")
                    val.append(st["modes"][0])
                elif w == "range":
                    parts.append(f"range = {show(st['range'])}")
                    val.append(st["range"])
                elif w == "variance":
                    parts.append(f"variance = {show(st['var'])}")
                    val.append(st["var"])
                elif w == "standard deviation":
                    parts.append(f"standard deviation = {show(st['sd'])}")
                    val.append(st["sd"])
            ans = ", ".join(parts) if len(parts) > 1 else parts[0].split(" = ")[1]
            value = tuple(exact(v) for v in val)
            if not full:
                return Item(text, ans, [], [], self.kind, value=value)
            n = len(xs)
            steps = []
            if "mean" in spec.want or "variance" in spec.want or "standard deviation" in spec.want:
                steps.append(f"Mean = sum ÷ count = {fmt_num(sum(xs))} ÷ {n} = {show(st['mean'])}")
            if "median" in spec.want:
                steps.append(f"In order: {', '.join(fmt_num(x) for x in sorted(xs))}; the middle {'value' if n % 2 else 'two values (averaged)'} = {show(st['median'])}")
            if "mode" in spec.want:
                steps.append(f"The most frequent value is {show(st['modes'][0])}")
            if "range" in spec.want:
                steps.append(f"Range = largest - smallest = {fmt_num(max(xs))} - {fmt_num(min(xs))} = {show(st['range'])}")
            if "variance" in spec.want or "standard deviation" in spec.want:
                steps.append(f"Variance = mean of (x - mean)^2 = {show(st['var'])}")
                if "standard deviation" in spec.want:
                    steps.append(f"Standard deviation = √variance = {show(st['sd'])}")
            wrong = []
            srt = sorted(xs)
            alt_sets = []
            if "mean" in spec.want:
                alt_sets.append({"mean": sum(xs) / (n - 1), "median": st["median"]})
            if "median" in spec.want:
                alt_sets.append({"median": xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2})
                alt_sets.append({"median": srt[n // 2] if n % 2 == 0 else srt[n // 2] + 1})
            if "mode" in spec.want:
                others = [x for x in xs if x != st["modes"][0]]
                alt_sets.append({"mode": max(others) if others else st["modes"][0] + 1})
            if "standard deviation" in spec.want or "variance" in spec.want:
                alt_sets.append({"sd": st["var"], "var": st["sd"] ** 2 * n / (n - 1) if n > 1 else st["var"]})
                alt_sets.append({"sd": sp.sqrt(sp.Rational((st["var"] * n / (n - 1)).numerator, (st["var"] * n / (n - 1)).denominator)), "var": st["var"] * 2})
            if "range" in spec.want:
                alt_sets.append({"range": srt[-1] + srt[0]})
            for alt in alt_sets + [{"mean": st["mean"] + 1, "median": st["median"] - 1, "range": st["range"] + 2, "sd": st["sd"] + 1, "var": st["var"] + 1,
                                    "mode": st["modes"][0] + 1 if st["modes"] else 0}]:
                ps = []
                for w in spec.want:
                    key = {"standard deviation": "sd", "variance": "var"}.get(w, w)
                    v = alt.get(key, st[key][0] if key == "modes" else (st["modes"][0] if key == "mode" else st[key]))
                    ps.append(f"{w} = {show(v)}")
                wa = ", ".join(ps) if len(ps) > 1 else ps[0].split(" = ")[1]
                if wa != ans and wa not in wrong:
                    wrong.append(wa)
            if len(spec.want) == 1:                         # the other averages, and near misses
                v0 = val[0]
                for c in [st["mean"], st["median"], st["modes"][0] if st["modes"] else None, st["range"], sum(xs), v0 + 1, v0 - 1, v0 + 2]:
                    if c is None:
                        continue
                    w = show(c)
                    if w != ans and w not in wrong:
                        wrong.append(w)
            return Item(text, ans, steps, wrong, self.kind, value=value)
        if t == "word":
            w = spec.word if vals == q.vals else spec.word
            return self._word(text, w, full)
        if t in ("nCr", "nPr", "choose"):
            n_, r_ = int(V[spec.ids[0]]), int(V[spec.ids[1]])
            if not (0 < r_ <= n_):
                return None
            r = math.comb(n_, r_) if t in ("nCr", "choose") else math.perm(n_, r_)
            ans = str(r)
            if not full:
                return Item(text, ans, [], [], self.kind, value=sp.Integer(r))
            if t == "nPr":
                steps = [f"{n_}P{r_} = {n_}!/({n_} - {r_})! = {' × '.join(str(n_ - k) for k in range(r_))} = {r}"]
                wrong = numeric_wrong(r, str, [math.comb(n_, r_), math.factorial(n_), n_ * r_])
            else:
                steps = ["Order doesn't matter, so use combinations.", f"{n_}C{r_} = {n_}!/({r_}! × {n_ - r_}!) = {r}"]
                wrong = numeric_wrong(r, str, [math.perm(n_, r_), n_ * r_, math.comb(n_, r_ - 1) if r_ > 1 else n_ + 1])
            return Item(text, ans, steps, wrong, self.kind, value=sp.Integer(r))
        if t == "fact":
            n_ = int(V[spec.ids[0]])
            if not 2 <= n_ <= 10:
                return None
            r = math.factorial(n_)
            ans = str(r)
            if not full:
                return Item(text, ans, [], [], self.kind, value=sp.Integer(r))
            steps = [f"The first place can be filled in {n_} ways, the next in {n_ - 1}, and so on.", f"{n_}! = {' × '.join(str(k) for k in range(n_, 0, -1))} = {r}"]
            return Item(text, ans, steps, numeric_wrong(r, str, [n_ * n_, math.factorial(n_ - 1), n_ * (n_ - 1)]), self.kind, value=sp.Integer(r))
        if t == "dice":
            k = int(V[spec.ids[0]])
            ways = sum(1 for a, b in product(range(1, 7), repeat=2) if a + b == k)
            if ways == 0:
                return None
            p = sp.Rational(ways, 36)
            ans = fnum(p)
            if not full:
                return Item(text, ans, [], [], self.kind, value=p)
            pairs = [f"({a},{b})" for a, b in product(range(1, 7), repeat=2) if a + b == k]
            steps = ["Two dice give 6 × 6 = 36 equally likely outcomes.", f"A total of {k}: {', '.join(pairs)} — {ways} outcomes.", f"P = {ways}/36 = {ans}"]
            return Item(text, ans, steps, [w for w in dict.fromkeys([fnum(sp.Rational(ways, 12)), fnum(sp.Rational(1, 11)), fnum(sp.Rational(ways + 1, 36)),
                                                                     fnum(sp.Rational(ways, 6))]) if w != ans], self.kind, value=p)
        if t == "coin":
            a, b = int(V[spec.ids[0]]), int(V[spec.ids[1]])
            n_, k = (a, b) if a >= b else (b, a)
            if not (1 <= k <= n_ <= 8):
                return None
            p = sp.Rational(math.comb(n_, k), 2 ** n_)
            ans = fnum(p)
            if not full:
                return Item(text, ans, [], [], self.kind, value=p)
            steps = [f"{n_} tosses give 2^{n_} = {2 ** n_} equally likely outcomes.", f"Exactly {k}: {n_}C{k} = {math.comb(n_, k)} of them.", f"P = {math.comb(n_, k)}/{2 ** n_} = {ans}"]
            return Item(text, ans, steps, [w for w in dict.fromkeys([fnum(sp.Rational(1, 2 ** n_)), fnum(sp.Rational(k, n_)), fnum(sp.Rational(k, 2 ** n_)),
                                                                     fnum(sp.Rational(math.comb(n_, k), 2 ** (n_ + 1)))]) if w != ans], self.kind, value=p)
        if t == "complement":
            p0 = V[spec.ids[0]]
            if not 0 < p0 < 1:
                return None
            r = 1 - p0
            ans = f"{float(r):.10g}"
            if not full:
                return Item(text, ans, [], [], self.kind, value=sp.Rational(r.numerator, r.denominator))
            steps = [f"P(not) = 1 - P = 1 - {float(p0):g} = {ans}"]
            return Item(text, ans, steps, [w for w in dict.fromkeys([f"{float(p0):g}", f"{float(1 + p0):g}", f"{float(1 - p0 / 2):g}", f"{float(p0 * (1 - p0)):.4g}"]) if w != ans],
                        self.kind, value=sp.Rational(r.numerator, r.denominator))
        if t == "bag":
            counts = [int(V[i]) for i in spec.ids]
            if any(c <= 0 for c in counts):
                return None
            p = sp.Rational(counts[spec.target], sum(counts))
            ans = fnum(p)
            if not full:
                return Item(text, ans, [], [], self.kind, value=p)
            steps = [f"Total = {' + '.join(map(str, counts))} = {sum(counts)}", f"P({spec.names[spec.target]}) = {counts[spec.target]}/{sum(counts)} = {ans}"]
            others = sum(counts) - counts[spec.target]
            return Item(text, ans, steps, [w for w in dict.fromkeys([fnum(sp.Rational(counts[spec.target], others)) if others else "1",
                                                                     fnum(sp.Rational(others, sum(counts))), fnum(sp.Rational(1, sum(counts))),
                                                                     fnum(sp.Rational(counts[spec.target], sum(counts) + 1))]) if w != ans], self.kind, value=p)
        return None

    def _word(self, text, word, full):
        n = len(word)
        reps = [word.count(c) for c in set(word)]
        r = math.factorial(n)
        for k in reps:
            r //= math.factorial(k)
        ans = str(r)
        if not full:
            return Item(text, ans, [], [], self.kind, value=sp.Integer(r))
        rep_txt = ", ".join(f"{c} appears {word.count(c)} times" for c in sorted(set(word)) if word.count(c) > 1)
        steps = [f"{n} letters: {n}! arrangements" + (f", divided by the repeats ({rep_txt})" if rep_txt else "") + f" = {r}"]
        return Item(text, ans, steps, numeric_wrong(r, str, [math.factorial(n), math.factorial(n - 1), n * n]), self.kind, value=sp.Integer(r))

    def versions(self, q, spec, n, rng, seen):
        """Only 'the letters of the word …' needs other words; everything else varies numbers (see make_versions)."""
        if spec.task != "word":
            return None
        out = []
        pool = [w for w in _WORDS if w != spec.word]
        rng.shuffle(pool)
        for w in pool[:n]:
            text = re.sub(rf"\b{spec.word}\b", w, q.display, flags=re.I)
            key = re.sub(r"\s+", "", text.lower())
            if key in seen:
                continue
            seen.add(key)
            out.append(self._word(text, w, True))
        return out

    def vary(self, q, spec, rng):
        vals = list(q.vals)
        V = [Fraction(v) for v in q.vals]
        t = spec.task
        if t == "list":
            xs = [V[i] for i in spec.ids]
            k = rng.choice([1, 1, 2, 3]) if all(x.denominator == 1 for x in xs) else 1
            span = max(xs) - min(xs)
            c = rng.randint(-int(min(xs)) + 1 if min(xs) > 0 else 1, max(3, int(span) + 5))
            new = [k * x + c for x in xs]
            if rng.random() < 0.5:
                order = list(range(len(new)))
                rng.shuffle(order)
                new = [new[o] for o in order]
            if new == xs or any(x <= 0 for x in new) and all(x > 0 for x in xs):
                return None
            for i, v in zip(spec.ids, new):
                vals[i] = v
            return vals
        if t in ("nCr", "nPr", "choose"):
            n0, r0 = int(V[spec.ids[0]]), int(V[spec.ids[1]])
            nn = max(3, n0 + rng.randint(-3, 4))
            rr = max(1, min(nn - 1, r0 + rng.randint(-1, 2)))
            vals[spec.ids[0]], vals[spec.ids[1]] = Fraction(nn), Fraction(rr)
            return vals
        if t == "fact":
            vals[spec.ids[0]] = Fraction(rng.choice([k for k in range(3, 9) if k != int(V[spec.ids[0]])]))
            return vals
        if t == "dice":
            vals[spec.ids[0]] = Fraction(rng.choice([k for k in range(2, 13) if k != int(V[spec.ids[0]])]))
            return vals
        if t == "coin":
            a, b = int(V[spec.ids[0]]), int(V[spec.ids[1]])
            nn = rng.randint(3, 6)
            kk = rng.randint(2 if min(a, b) >= 2 else 1, nn - 1)            # "exactly 1 heads" reads badly
            if a >= b:
                vals[spec.ids[0]], vals[spec.ids[1]] = Fraction(nn), Fraction(kk)
            else:
                vals[spec.ids[0]], vals[spec.ids[1]] = Fraction(kk), Fraction(nn)
            return vals
        if t == "complement":
            dp = max(1, q.slots[spec.ids[0]].dp)
            vals[spec.ids[0]] = Fraction(rng.randint(1, 10 ** dp - 1), 10 ** dp)
            return vals
        if t == "bag":
            for i in spec.ids:
                vals[i] = Fraction(rng.randint(2, max(9, int(V[i]) + 3)))
            return vals
        return None

    def nice(self, base, item):
        b, v = base.value, item.value
        if isinstance(b, tuple):
            for x, y in zip(b, v):
                x, y = exact(x), exact(y)
                if x.is_Integer and not y.is_Integer:
                    return False
                if x.is_Rational and not y.is_Rational:
                    return False
            return True
        return True
