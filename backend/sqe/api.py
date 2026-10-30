"""
CUSTOM-SQE's front door for MrSOLIS (backend/main.py: /api/sqe/generate and /api/sqe/check).

  generate(question, n, session): new practice questions like the one typed, each with its answer, worked steps
      and (usually) multiple-choice options. `session` is the SQE window's practice session: nothing is repeated
      within it.
  check(given, correct): is a typed answer right? Fair to how students write it: 0.5 = 1/2 = 50% where the answer
      is a number, 2(x+1) = 2x+2, units optional, "x =" optional, "+ C" optional on an integral, roots in any order.
"""
from __future__ import annotations

import hashlib
import re
from typing import Optional

import sympy as sp
from sympy.parsing.sympy_parser import (
    convert_xor, implicit_multiplication_application, parse_expr, standard_transformations,
)

from . import engine
from .calculus import normalize_math_text
from .pipeline import NO_MATCH_MESSAGE, generate_from_question
from .text import to_expr

MAX_QUESTIONS = 30
_TRANSFORMS = standard_transformations + (implicit_multiplication_application, convert_xor)
_NAMES = {name: getattr(sp, name) for name in ("sin", "cos", "tan", "sqrt", "exp", "log", "ln", "pi", "E", "oo")
          if hasattr(sp, name)}
_NAMES.update({"ln": sp.log, "e": sp.E, "x": sp.Symbol("x"), "y": sp.Symbol("y"), "C": sp.Symbol("C")})


def generate(question: str, n: int = 10, session: Optional[str] = None, reset: bool = False) -> dict:
    question = (question or "").strip()
    if not question:
        return {"ok": False, "message": "Type a maths question first."}
    n = max(1, min(int(n or 10), MAX_QUESTIONS))
    r = engine.make(question, n=n, session=session, reset=reset)           # CUSTOM-SQE's families
    if r is None or not r.get("questions"):
        deck = session or hashlib.sha1(question.encode()).hexdigest()[:16]
        old = generate_from_question(deck_id=deck, question_text=question, n=n, reset=reset)   # MrSOLIS 2-AL's own
        if old.get("questions"):
            r = old
    if r is None or not r.get("questions"):
        msg = (r or {}).get("message") or NO_MATCH_MESSAGE
        return {"ok": False, "detected_type": (r or {}).get("detected_type"), "message": msg}
    for q in r["questions"]:
        if q.get("options"):
            q["options"] = even_options(q["answer"], q["options"])
    return {"ok": True, **r}


_LHS = re.compile(r"^\s*(?:[A-Za-z]\w*'*(?:\([^()]*\))?|d\w/d\w)\s*=\s*(?!=)")


def even_options(answer: str, options: list) -> list:
    """Every option written the way the answer is, so its look never gives it away: "f'(x) = " on all four or
    none, and the same unit on every number. The answer itself is never changed (it is the key)."""
    lhs = _LHS.match(answer)
    prefix = lhs.group(0) if lhs else ""
    num_unit = _NUMBER_UNIT.fullmatch(answer.strip())
    unit = answer.strip()[num_unit.end(1):] if num_unit and num_unit.group(2) else ""   # keeps the answer's spacing
    out = []
    for o in options:
        if o != answer:
            if prefix and not _LHS.match(o):
                o = prefix + o
            elif not prefix:
                o = _LHS.sub("", o, count=1)
            if unit and re.fullmatch(r"-?\d[\d.,]*(?:[eE]-?\d+)?", o.strip()):
                o = o.strip() + unit
        if o not in out:
            out.append(o)
    return out if answer in out and len(out) >= 2 else options


# ── marking typed answers ──────────────────────────────────────────────────────────────────────────────────


_NUMBER_UNIT = re.compile(r"(-?\d[\d.]*(?:/\d[\d.]*)?(?:[eE]-?\d+)?)\s*([A-Za-zΩµμ°][A-Za-zΩµμ°/^·\d]*)?")
_VARIABLES = {"x", "y", "z", "t", "i", "n", "k"}


def _clean(s: str) -> str:
    s = str(s or "").strip().rstrip(".")
    s = re.sub(r"^\s*(?:dy/dx|d²y/dx²|d\^?2y/dx\^?2|∂f/∂[a-z]|df/d[a-z]|f''?\s*\(\s*x\s*\))\s*=\s*", "", s)   # "dy/dx =" …
    s = re.sub(r"^\s*(?:GH¢|GHS|GH₵|Gh¢|¢|\$)\s*", "", s)                # GHS 630.00 -> 630.00
    s = re.sub(r"\s*(?:rad|radians)\s*$", "", s)                          # π/4 rad -> π/4
    s = s.replace("°", "")                                               # 30°, 150° -> 30, 150
    s = re.sub(r"(?<![\d/.])(\d+)\s+(\d+)\s*/\s*(\d+)(?![\d/])", r"(\1 + \2/\3)", s)   # 6 13/24 -> (6 + 13/24)
    s = normalize_math_text(s).strip()
    s = re.sub(r"^[a-zA-Z]'*\s*\(?\s*[a-zA-Z]?\s*\)?\s*=\s*", "", s)    # "x =", "f'(x) =", "y="
    s = re.sub(r"\+\s*C\s*$", "", s).strip()                            # an integral's "+ C"
    if re.fullmatch(r"-?\d{1,3}(?:,\d{3})+(?:\.\d+)?", s):              # 12,500 -> 12500 (not "3, 2")
        s = s.replace(",", "")
    return s.replace("×", "*").replace("÷", "/").replace("−", "-")


def _split_unit(s: str, word_problem: bool = False):
    """("2.08", "A") for "2.08A" / "2.08 A"; (s, "") when it isn't a number followed by one unit. A lone variable
    letter ("21x") is algebra, not a unit, except in a word problem's answer."""
    m = _NUMBER_UNIT.fullmatch(s.strip())
    if m and m.group(2) and (word_problem or m.group(2) not in _VARIABLES):
        return m.group(1), m.group(2)
    return s, ""


def _value(s: str):
    """A sympy value for one answer: a number, a percentage or an expression; None when it can't be read."""
    s = s.strip()
    if not s:
        return None
    pct = re.fullmatch(r"(-?[\d.]+)\s*%", s)
    if pct:
        return sp.Rational(pct.group(1)) / 100
    return to_expr(normalize_math_text(s), complex_i=True)       # safe: only maths characters and names get read


def _numeric(v) -> Optional[float]:
    try:
        f = complex(sp.N(v))
        return f.real if abs(f.imag) < 1e-12 else None
    except Exception:                                                    # noqa: BLE001
        return None


def _same(a, b) -> bool:
    fa, fb = _numeric(a), _numeric(b)
    if fa is not None and fb is not None:                               # rounded answers count (3 significant figures)
        return abs(fa - fb) <= max(1e-9, 5e-3 * abs(fb))
    try:
        return sp.simplify(sp.sympify(a) - sp.sympify(b)) == 0
    except Exception:                                                    # noqa: BLE001
        return False


def _parts(s: str) -> list:
    return [p for p in re.split(r"\s*(?:,|;|\bor\b|\band\b)\s*", s) if p.strip()]


def check(given: str, correct: str, kind: str = "") -> dict:
    """{correct: bool} for a typed answer against the engine's answer. kind: the question's fact_type."""
    g, c = _clean(given), _clean(correct)
    if not g:
        return {"correct": False}
    if g.replace(" ", "").lower() == c.replace(" ", "").lower():
        return {"correct": True}
    if c.endswith("%") and not g.endswith("%") and re.fullmatch(r"-?[\d.]+", g):
        g = g + "%"                                                     # "25" for 25%
    word = kind == "word_problem"
    c_num, c_unit = _split_unit(c, word)
    if c_unit:                                                          # "2.08A": the number counts; a unit, if typed, must match
        g_num, g_unit = _split_unit(g, True)
        gv, cv = _value(g_num), _value(c_num)
        ok = gv is not None and cv is not None and _same(gv, cv)
        return {"correct": bool(ok and (not g_unit or g_unit.lower() == c_unit.lower()))}
    gv, cv = _value(g), _value(c)
    if gv is not None and cv is not None and _same(gv, cv):
        return {"correct": True}
    gp, cp = _parts(g), _parts(c)                                       # several roots, in any order
    if len(cp) > 1 and len(gp) == len(cp):
        gvals = [_value(_clean(p)) for p in gp]
        cvals = [_value(_clean(p)) for p in cp]
        if all(v is not None for v in gvals + cvals):
            left = list(cvals)
            for v in gvals:
                hit = next((i for i, w in enumerate(left) if _same(v, w)), None)
                if hit is None:
                    return {"correct": False}
                left.pop(hit)
            return {"correct": True}
    return {"correct": False}
