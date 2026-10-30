"""Formulas written on a slide ('B = µH = µr µ0 H', 'Xc = 1/(2πfC)', 'F = BIL sin θ') → Formula objects the engine
can use for a question on that slide, alongside the library.

NOT used by solve() yet (2026-10-22): on PDF-extracted text it found 6 "formulas" across 168 slides and 5 were wrong
(unit conversions, set notation, a slip s read as a distance) — units can't catch those. Meant for clean text, e.g.
formulas the vision brain transcribes from the slide picture, checked here before use.

Slide text comes out of PDFs damaged: fractions split across lines ('H = B' over 'µrµ0'), superscripts flattened
('N 2' for N², 'πd2' for πd²). So the reader is conservative: every way of reading an ambiguous piece is tried, a
formula is kept only if exactly one reading is dimensionally consistent, and its symbols are read like the OpenStax
import (textbook conventions, the slide's topic, and the slide's own "where V is the voltage" definitions).
"""
import functools
import itertools
import re

from . import library as L
from .formulas import Formula
from .symbols import read, Skip

_GREEK = [("µ", "mu"), ("μ", "mu"), ("θ", "theta"), ("ε", "eps"), ("Φ", "Phi"), ("φ", "phi"), ("ϕ", "phi"),
          ("λ", "lam"), ("ρ", "rho"), ("ω", "omega"), ("π", "pi"), ("η", "eta"), ("σ", "sigma"), ("τ", "tau"),
          ("α", "alpha"), ("Ω", "Omega"), ("ν", "nu")]
_FUNCS = {"sin", "cos", "tan", "ln", "log", "exp", "sqrt"}
_WORDS = {"mmf": "F_m", "emf": "eps"}                 # written-out symbols
_SUBS = {"c", "l", "L", "C", "p", "s", "r", "m", "e", "b", "i", "f", "o", "x", "y", "t", "n", "d", "g", "a", "k",
         "rms", "max", "min", "in", "out", "net", "avg", "th", "ph", "fld", "gap"}
_EQ = re.compile(r"[^=\n]{1,40}(?:=[^=\n]{1,60}){1,4}")


def _normalise(s):
    s = s.replace("−", "-").replace("–", "-").replace("×", "*").replace("·", "*").replace("⋅", "*").replace("÷", "/")
    s = s.replace("²", "^2").replace("³", "^3").replace("√", "sqrt").replace("Δ", "Delta_")
    for ch, name in _GREEK:
        s = s.replace(ch, f" {name} ")
    s = re.sub(r"\b(mu|eps)\s+(r|0|o)\b", r"\1_\2", s)          # µr, µ0 → mu_r, mu_0
    return re.sub(r"\s+", " ", s).strip()


_TOKEN = re.compile(r"(Delta_[A-Za-z]+|[A-Za-z]+(?:_[A-Za-z0-9]+)?\d*|\d+(?:\.\d+)?|\S)")


def _choices(tok):
    """Ways to read one token: 'BIL' → B*I*L; 'Xc' → X_c or X*c; 'N2' → N_2 or N**2."""
    if tok in _FUNCS or tok == "pi":
        return [tok]
    if tok.lower() in _WORDS:
        return [_WORDS[tok.lower()]]
    if re.fullmatch(r"[a-zA-Z]+_[A-Za-z0-9]+", tok) or tok.startswith("Delta_"):
        return [tok]
    m = re.fullmatch(r"([A-Za-z]+)(\d+)", tok)
    if m:
        out = []
        for base in _choices(m.group(1)):
            last = re.split(r"\*", base)[-1]
            head = base[:len(base) - len(last)]
            out += [f"{head}{last}_{m.group(2)}", f"{head}({last})**{m.group(2)}"]
        return out
    if not re.fullmatch(r"[A-Za-z]+", tok):
        return [tok]
    if len(tok) == 1:
        return [tok]
    for g in ("theta", "omega", "sigma", "alpha", "lam", "rho", "phi", "Phi", "tau", "eta", "eps"):
        if tok == g:
            return [tok]
    out = ["*".join(tok)]
    if len(tok) <= 4 and tok[1:] in _SUBS:
        out.append(f"{tok[0]}_{tok[1:]}")
    return out


def _variants(segment, limit=48):
    toks = _TOKEN.findall(segment)
    opts = [_choices(t) for t in toks]
    for combo in itertools.islice(itertools.product(*opts), limit):
        s, prev = "", None
        for t in combo:
            kind = "op" if t in "+-*/^()=," else ("func" if t in _FUNCS else "operand")
            if t == "(" and prev in ("operand", "close"):
                s += "*"
            elif kind == "operand" and prev in ("operand", "close"):
                s += "*"
            elif kind == "func" and prev in ("operand", "close"):
                s += "*"
            s += t.replace("^", "**")
            prev = "close" if t == ")" else ("open" if t == "(" else kind)
        yield s


def _definitions(text):
    """'where V is the voltage', 'I = current (A)' → {symbol: quantity}."""
    from .engine import QWORDS
    out = {}
    for m in re.finditer(r"\b([A-Za-zµμθλρωΦφ][A-Za-z0-9_µμ]{0,3})\s*(?:=|is|:|-|–)\s*(?:the\s+)?([a-z][a-z \-']{3,45})",
                         text):
        sym, desc = m.group(1), m.group(2).lower()
        best = None
        for q, rx in QWORDS.items():
            if rx is not None:
                mm = rx.search(desc)
                if mm and mm.start() < 6 and (best is None or len(mm.group(1)) > best[0]):
                    best = (len(mm.group(1)), q)
        if best:
            out.setdefault(_normalise(sym).replace(" ", "_").replace("__", "_"), best[1])
    return out


def _signature(f):
    qs = [q if q != "@" else "@" + r for (q, r) in f.vars.values()]
    return tuple(sorted(qs)) if len(qs) == len(set(qs)) else None


def _agrees(f, g) -> bool:
    """Do two formulas over the same quantities give the same numbers? (Random values, solved for one quantity.)"""
    import random
    rnd = random.Random(7)
    by_f = {(q if q != "@" else "@" + r): s for s, (q, r) in f.vars.items()}
    by_g = {(q if q != "@" else "@" + r): s for s, (q, r) in g.vars.items()}
    sig = _signature(f)
    target = next(q for q in sig if not q.startswith("@"))
    vals = {q: (L.CONSTANTS[q[1:]][0] if q.startswith("@") else rnd.uniform(0.5, 3.0)) for q in sig if q != target}
    try:
        a = [complex(e.subs({f.syms[by_f[q]]: v for q, v in vals.items()}).evalf()).real for e in f.solve_for(by_f[target])]
        b = [complex(e.subs({g.syms[by_g[q]]: v for q, v in vals.items()}).evalf()).real for e in g.solve_for(by_g[target])]
    except Exception:
        return False
    return any(abs(x - y) <= 1e-6 * max(1.0, abs(x)) for x in a for y in b)


def _checked(f):
    """A slide formula that links the same quantities as a library or book formula must agree with it: PDF text
    loses factors ('A = πd²/4' arrives as 'A = πd2' over '4'), and units can't see a missing 4."""
    from .formulas import library, books
    sig = _signature(f)
    if not sig:
        return True
    same = [g for g in list(library()) + list(books()) if _signature(g) == sig]
    return all(_agrees(f, g) for g in same) if same else True


_BROKEN_NEXT = re.compile(r"^\s*(?:[\d(]|[-−]\s*\d)")


@functools.lru_cache(maxsize=64)
def parse(slide_text: str) -> tuple:
    """The formulas on a slide as Formula objects (source 'slide'). Empty when none can be read safely."""
    import sympy
    from sympy.parsing.sympy_parser import parse_expr
    text = slide_text or ""
    topic = text[:600]
    extra = _definitions(text)
    out, seen = [], set()
    lines = text.splitlines()
    for n, line in enumerate(lines):
        nxt = lines[n + 1] if n + 1 < len(lines) else ""
        if nxt and (_BROKEN_NEXT.match(nxt) or len(nxt.strip()) <= 14):
            continue                                          # the line probably goes on below: a split fraction
        for seg in re.split(r"[;,]\s+|\s+where\s+|\(|\)", line):
            if "=" not in seg or len(seg) > 120:
                continue
            m = _EQ.search(seg)
            if not m:
                continue
            norm = _normalise(m.group(0))
            parts = [p.strip() for p in norm.split("=")]
            if any(not p for p in parts) or all(re.fullmatch(r"[-\d.\s*^]+", p) for p in parts[1:]):
                continue                                      # "m = 2 kg": a given, not a formula
            for a, b in zip(parts, parts[1:]):
                if re.fullmatch(r"[-\d.\s*^]+", b) or re.fullmatch(r"[-\d.\s*^]+", a):
                    continue
                readings = {}
                for va in _variants(a):
                    for vb in _variants(b):
                        try:
                            names = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", va + " " + vb)) - _FUNCS - {"pi"}
                            if not names or len(names) > 6:
                                continue
                            local = {n: sympy.Symbol(n, positive=True) for n in names}
                            local.update({"pi": sympy.pi, "sqrt": sympy.sqrt, "sin": sympy.sin, "cos": sympy.cos,
                                          "tan": sympy.tan, "log": sympy.log, "exp": sympy.exp})
                            lhs, rhs = parse_expr(va, local_dict=local), parse_expr(vb, local_dict=local)
                            used = {str(x) for x in (lhs.free_symbols | rhs.free_symbols)}
                            if len(used) < 2:
                                continue
                            reading = read((lhs, rhs), used, topic, extra, topic=True)
                        except (Skip, Exception):
                            continue
                        key = (sympy.srepr(sympy.simplify(lhs - rhs)), tuple(sorted((s, q) for s, (q, r) in reading.items())))
                        readings[key] = (f"{va} = {vb}", reading)
                if len(readings) != 1:
                    continue                                  # nothing consistent, or more than one: not safe
                eq, reading = next(iter(readings.values()))
                if eq in seen:
                    continue
                seen.add(eq)
                spec = {"name": f"Formula on this slide: {a} = {b}", "topic": "slide", "eq": eq, "needs": [],
                        "nodims": False, "vars": {s: (q if q.startswith("@") else q + (":" + r if r else ""))
                                                  for s, (q, r) in reading.items()}}
                try:
                    f = Formula(spec, 20000 + len(out), source="slide")
                except Exception:
                    continue
                if _checked(f):
                    out.append(f)
    return tuple(out)
