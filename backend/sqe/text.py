"""
CUSTOM-SQE: reading and writing maths text.

A student's question is kept exactly as they wrote it. Every number in it becomes a *slot*, so a new version is
the same words with new numbers. Signs ("x - 5" -> "x + 7"), superscripts (x² stays x²), decimals, thousands
commas and "1x" -> "x" are handled when it is written back.

For working the question out, the text is normalised to plain maths with each slot as a symbol S0, S1, ... A family
parses that once with sympy, then puts new numbers in. `to_expr` only lets through maths characters and maths
names, because sympy's parser runs Python's eval.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from fractions import Fraction
from typing import Dict, List, Optional, Sequence

import sympy as sp
from sympy.parsing.sympy_parser import (
    convert_xor, implicit_multiplication_application, parse_expr, standard_transformations,
)

SUP = "⁰¹²³⁴⁵⁶⁷⁸⁹"
SUB = "₀₁₂₃₄₅₆₇₈₉"
_DIGIT_OF = {c: str(i) for i, c in enumerate(SUP)} | {c: str(i) for i, c in enumerate(SUB)}
_MARK_A, _MARK_B = "\ue000", "\ue001"           # wrap a slot's number while the text is normalised

# ── the student's text, made plain (LaTeX -> ordinary maths; unicode kept for display) ──────────────────────

_LATEX = [
    (r"\\(?:left|right|displaystyle|quad|qquad)|\\[,;!]", ""),
    (r"\\(?:times|cdot)", "×"), (r"\\div", "÷"), (r"\\pi\b", "π"), (r"\\theta\b", "θ"), (r"\\alpha\b", "α"),
    (r"\\beta\b", "β"), (r"\\infty", "∞"), (r"\\(?:leqslant|leq|le)\b", "≤"), (r"\\(?:geqslant|geq|ge)\b", "≥"),
    (r"\\(?:neq|ne)\b", "≠"), (r"\\(?:to|rightarrow)\b", "→"), (r"\\int\b", "∫"), (r"\\partial\b", "∂"),
    (r"\\pm\b", "±"), (r"\^\s*\\circ|\^\{\\circ\}|\\circ|\\degree", "°"),
    (r"\\(sinh|cosh|tanh|sin|cos|tan|sec|csc|cot|ln|log|exp|lim|arcsin|arccos|arctan)\b", r"\1"),
]


def clean(text: str) -> str:
    """The question as it will be shown: one line, LaTeX turned into plain maths, unicode symbols kept."""
    s = str(text or "").replace("\r", " ").replace("\n", " ").replace("\t", " ").strip()
    if "\\" in s or "$" in s:
        s = s.replace("$", "")
        for _ in range(6):                                                   # nested \frac / \sqrt
            t = re.sub(r"\\[dt]?frac\s*\{([^{}]*)\}\s*\{([^{}]*)\}", r"(\1)/(\2)", s)
            t = re.sub(r"\\sqrt\s*\{([^{}]*)\}", r"√(\1)", t)
            if t == s:
                break
            s = t
        for pat, rep in _LATEX:
            s = re.sub(pat, rep, s)
        s = re.sub(r"\^\{([^{}]*)\}", lambda m: "^" + (m.group(1) if re.fullmatch(r"-?\w+", m.group(1)) else f"({m.group(1)})"), s)
        s = re.sub(r"_\{([^{}]*)\}", r"_\1", s)
        s = s.replace("{", "(").replace("}", ")").replace("\\", "")
    s = s.replace("**", "^")
    return re.sub(r" {2,}", " ", s).strip()


# ── slots: every number in the text ──────────────────────────────────────────────────────────────────────────

_NUM = re.compile(
    r"(?P<sup>⁻?[⁰¹²³⁴⁵⁶⁷⁸⁹]+)|(?P<sub>[₀₁₂₃₄₅₆₇₈₉]+)"
    r"|(?P<num>(?<![\d.])(?:\d{1,3}(?:,\d{3})+(?![\d,])|\d+)(?:\.\d+)?|(?<![\w.])\.\d+)"
)
_SMALL_WORDS = {"is", "be", "by", "of", "to", "and", "are", "was", "the", "for", "if", "at", "on", "in", "as", "or",
                "an", "a", "it", "its", "has", "had", "get", "got", "let", "set", "say", "use", "per", "via", "but",
                "not", "now", "all", "any", "few", "two", "one", "new", "lies", "from", "than", "then"}


@dataclass
class Slot:
    i: int
    start: int              # span in the displayed text (includes an owned "+"/"-" or a unary "-")
    end: int
    value: Fraction         # signed value
    dp: int = 0             # decimal places as written
    style: str = ""         # "" | "sup" | "sub"
    binary: bool = False    # owns a binary +/- between two terms ("x - 5")
    gap: str = ""           # spacing between that operator (or a unary "-") and the digits
    commas: bool = False    # written with thousands commas
    role: str = "num"       # "exp" | "base" | "ord" | "coef" | "num"
    text: str = ""          # the digits as written

    @property
    def is_int(self) -> bool:
        return self.value.denominator == 1


def _prev_word(text: str, k: int) -> str:
    j = k
    while j >= 0 and text[j].isalpha():
        j -= 1
    return text[j + 1:k + 1]


def find_slots(text: str) -> List[Slot]:
    slots: List[Slot] = []
    for m in _NUM.finditer(text):
        start, end = m.span()
        style = "sup" if m.group("sup") else "sub" if m.group("sub") else ""
        raw = m.group(0)
        if style:
            neg = raw.startswith("⁻")
            digits = "".join(_DIGIT_OF[c] for c in raw.lstrip("⁻"))
            value = Fraction(int(digits)) * (-1 if neg else 1)
            slots.append(Slot(len(slots), start, end, value, 0, style, role="exp" if style == "sup" else "base", text=raw))
            continue
        prev = text[start - 1] if start else ""
        if prev.isalpha():                                                   # "x2", "R1": part of a name …
            word = _prev_word(text, start - 1).lower()
            ok = word.endswith("log") or (prev in "CP" and start >= 2 and text[start - 2].isdigit())   # … but log2 8, 8C3
            if not ok:
                continue
        digits = raw.replace(",", "")
        value = Fraction(digits) if "." not in digits else Fraction(digits)
        dp = len(digits.split(".")[1]) if "." in digits else 0
        s = Slot(len(slots), start, end, value, dp, "", commas="," in raw, text=raw)
        # a sign in front: "x - 5" owns the operator (binary); "= -2", "(4, -1)" is a negative number (unary)
        j = start - 1
        while j >= 0 and text[j] == " ":
            j -= 1
        if j >= 0 and text[j] in "-−–+":
            k = j - 1
            while k >= 0 and text[k] == " ":
                k -= 1
            p = text[k] if k >= 0 else ""
            word = _prev_word(text, k).lower() if p.isalpha() else ""
            # after a number, a bracket or a variable it's an operator ("3a + 2", "x - 5"); after a word it's a sign
            binary = bool(p) and (p.isdigit() or p in ")]|!%πθ°" or p in SUP or p in SUB
                                  or (p.isalpha() and (len(word) == 1 or (len(word) <= 3 and word not in _SMALL_WORDS))))
            if binary:
                s.binary, s.start, s.gap = True, j, text[j + 1:start]
                if text[j] in "-−–":
                    s.value = -s.value
            elif text[j] in "-−–" and (k < 0 or text[k] in "(=,[:<>≤≥^/*×÷ ") or p.isalpha():
                s.start, s.gap = j, text[j + 1:start]
                s.value = -s.value
        before = text[:s.start].rstrip()
        after = text[end:end + 3]
        if (before.endswith("^") or before.endswith("^(") or re.search(r"\^\(?-?$", text[:start])) and \
                not (after[:1].isalpha() or after[:1] == "("):                # e^(3x): 3 is a coefficient
            s.role = "exp"
        elif before.endswith("_") or re.search(r"\b(?:base|log)\s*_?$", before, re.I):
            s.role = "base"
        elif re.match(r"(?:st|nd|rd|th)\b", after):
            s.role = "ord"                                                   # "20th": the suffix goes with it
            s.end += 2
        elif after[:1] in ("(", "√", "π") or (after[:1].isalpha() and not re.match(_UNIT_AFTER, text[end:])):
            s.role = "coef"
        slots.append(s)
    return slots


_UNIT_AFTER = re.compile(
    r"\s?(?:k?W|kWh|MW|mW|V|kV|mV|A|mA|µA|μA|Ω|kΩ|MΩ|ohms?|J|kJ|MJ|N|kN|Pa|kPa|Hz|kHz|MHz|kg|g|mg|m|cm|mm|km|s|ms|"
    r"min|mins|h|hrs?|hours?|F|µF|μF|uF|nF|pF|H|mH|C|K|L|ml|mL|l|t|cal|kcal|°|%|rad|days?|years?|yrs?|months?|"
    r"weeks?|cedis?|pesewas?|men|workers|people|pens|books|students|balls|oranges)\b"
)


def fmt_value(v: Fraction, slot: Slot) -> str:
    """One slot's new number, written the way the original was (decimals, commas, superscript)."""
    mag = abs(v)
    if mag.denominator == 1:
        digits = f"{mag.numerator:,}" if slot.commas else str(mag.numerator)
    else:
        dp = max(1, slot.dp)
        q = round(float(mag), dp + 6)
        digits = (f"{q:,.{dp}f}" if slot.commas else f"{q:.{dp}f}")
        if "." in digits and not slot.text.endswith("0"):                 # 0.3, not 0.30 (unless written 2.50)
            digits = digits.rstrip("0").rstrip(".")
    if slot.style == "sup":
        return ("⁻" if v < 0 else "") + "".join(SUP[int(c)] for c in digits)
    if slot.style == "sub":
        return "".join(SUB[int(c)] for c in digits)
    return digits


class Question:
    """A student's question: the text as shown, its number slots, and the normalised text for parsing."""

    def __init__(self, text: str):
        self.display = clean(text)
        self.slots = find_slots(self.display)
        self.vals: List[Fraction] = [s.value for s in self.slots]
        self.S = [sp.Symbol(f"S{s.i}") for s in self.slots]
        self.sym = self._normalised(symbolic=True)        # "Differentiate f(x) = (S0)x^(S1) + (S2)x"
        self.norm = self._normalised(symbolic=False)      # "Differentiate f(x) = 3x^2 + 2x"
        self.low = self.norm.lower()

    # writing a version back
    def render(self, vals: Sequence) -> str:
        out, pos = [], 0
        for s in self.slots:
            v = Fraction(vals[s.i])
            out.append(self.display[pos:s.start])
            body = fmt_value(v, s)
            if s.role == "coef" and abs(v) == 1:
                body = ""                                                    # "1x" -> "x"
            if s.role == "ord":
                k = int(abs(v))
                body += "th" if 10 <= k % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(k % 10, "th")
            if s.binary:
                out.append(("-" if v < 0 else "+") + (s.gap or "") + body)
            elif v < 0 and s.style != "sup":
                out.append("-" + body)
            else:
                out.append(body)
            pos = s.end
        out.append(self.display[pos:])
        return "".join(out)

    def subs(self, vals: Sequence) -> Dict[sp.Symbol, sp.Rational]:
        return {self.S[k]: sp.Rational(Fraction(v).numerator, Fraction(v).denominator) for k, v in enumerate(vals)}

    def slot_symbols(self, e) -> List[int]:
        """Indexes of the slots appearing in a sympy expression (or several)."""
        found = set()
        for x in (e if isinstance(e, (list, tuple, set)) else [e]):
            for s in getattr(x, "free_symbols", set()):
                if s.name.startswith("S") and s.name[1:].isdigit():
                    found.add(int(s.name[1:]))
        return sorted(found)

    def _normalised(self, symbolic: bool) -> str:
        out, pos = [], 0
        for s in self.slots:
            out.append(self.display[pos:s.start])
            mark = f"{_MARK_A}{s.i}{_MARK_B}"
            if s.binary:
                out.append(" + " + mark)
            elif s.style == "sup":
                out.append("^" + mark)
            elif s.style == "sub":
                out.append("_" + mark)
            else:
                out.append(mark)
            pos = s.end
        out.append(self.display[pos:])
        t = normalise("".join(out))

        def put(m):
            k = int(m.group(1))
            if symbolic:
                return f"(S{k})"
            v = self.vals[k]
            txt = str(v.numerator) if v.denominator == 1 else repr(float(v))
            return f"({txt})" if v < 0 else txt
        return re.sub(f"{_MARK_A}(\\d+){_MARK_B}", put, t)


def normalise(s: str) -> str:
    """Unicode maths -> plain ASCII maths (slot marks untouched)."""
    rep = {"−": "-", "–": "-", "—": "-", "×": "*", "÷": "/", "·": "*", "∙": "*", "π": " pi ", "θ": "theta",
           "∞": "oo", "≤": "<=", "≥": ">=", "≠": "!=", "→": "->", "⟶": "->", "α": "alpha", "β": "beta",
           "µ": "u", "μ": "u", "Ω": "ohm", "°": " deg ", "²": "^2", "³": "^3", "√": "√", "’": "'", "‘": "'",
           "∂": "d", "≈": "=", "＝": "="}
    for a, b in rep.items():
        s = s.replace(a, b)
    s = re.sub(r"√\s*\(", "sqrt(", s)
    s = re.sub(rf"√\s*((?:{_MARK_A}\d+{_MARK_B}|\d+(?:\.\d+)?)?[A-Za-z]?)", r"sqrt(\1)", s)
    s = re.sub(r"(?<=[A-Za-z0-9)])(?=sqrt\()", "*", s)                     # i√3 -> i*sqrt(3), not "isqrt"
    s = re.sub(r"\binfinity\b|\binfinite\b", "oo", s, flags=re.I)
    s = re.sub(rf"(?<=[\d){_MARK_B}])\s+[xX]\s+(?=[\d({_MARK_A}])", " * ", s)        # 2^5 x 2^3, 1.2 x 10^3
    s = re.sub(r"\s+", " ", s)
    return s.strip()


# ── turning maths text into sympy, safely ─────────────────────────────────────────────────────────────────────

_TRANSFORMS = standard_transformations + (implicit_multiplication_application, convert_xor)
_FUNC_NAMES = ["asin", "acos", "atan", "sinh", "cosh", "tanh", "sin", "cos", "tan", "sec", "csc", "cot",
               "ln", "log", "sqrt", "exp", "Abs"]
_KNOWN = set(_FUNC_NAMES) | {"pi", "oo", "E", "I", "theta", "alpha", "beta", "lamda", "mu", "phi", "omega",
                             "logb", "log10"}
_WORDS = {"as", "of", "and", "at", "to", "in", "is", "be", "by", "or", "the", "for", "if", "on", "it", "an", "its",
          "are", "was", "has", "not", "but", "can", "use", "any", "all", "how", "who", "why", "one", "two"}
_LETTERS = {c: sp.Symbol(c) for c in "abcdfghjklmnopqrstuvwxyzABCDFGHJKLMNOPQRSTUVWXYZ"}
_GREEK = {n: sp.Symbol(n) for n in ("theta", "alpha", "beta", "lamda", "mu", "phi", "omega")}


def _balanced(s: str, i: int) -> int:
    """Index just past the ")" matching the "(" at s[i] (or -1)."""
    depth = 0
    for j in range(i, len(s)):
        if s[j] == "(":
            depth += 1
        elif s[j] == ")":
            depth -= 1
            if depth == 0:
                return j + 1
    return -1


_ARG = r"(?:\((?:S\d+|-?\d+(?:\.\d+)?)\)|-?\d+(?:\.\d+)?)?\s*(?:[a-zA-Z]|theta|pi)(?:\^(?:\(S\d+\)|\d+))?"


def prepare(s: str) -> str:
    """Plain maths text -> text sympy's parser reads the way a student means it."""
    s = s.strip().rstrip(".?!;:").strip()
    s = re.sub(r"\bcosec\b", "csc", s)
    s = re.sub(r"\barc(sin|cos|tan)\b", r"a\1", s)
    s = re.sub(r"\|([^|]+)\|", r"Abs(\1)", s)
    s = re.sub(r"\be\s*\^", "E^", s)
    # log base: log_2(x), log_(S0) x, log2 x  ->  logb(x, 2)
    for _ in range(4):
        m = re.search(r"\blog\s*_?\s*(\(S\d+\)|\d+)\s*(?=[\w(])", s)
        if not m:
            break
        base, rest_at = m.group(1), m.end()
        if s[rest_at] == "(":
            close = _balanced(s, rest_at)
            if close < 0:
                break
            arg = s[rest_at + 1:close - 1]
            s = s[:m.start()] + f"logb({arg}, {base})" + s[close:]
        else:
            a = re.match(_ARG, s[rest_at:])
            if not a:
                break
            s = s[:m.start()] + f"logb({a.group(0)}, {base})" + s[rest_at + a.end():]
    # sin^2 x -> sin(x)^2 ;  sin^2(x) -> sin(x)^2
    s = re.sub(rf"(?<![A-Za-z])(sin|cos|tan|sec|csc|cot)\s*\^\s*(\(S\d+\)|\d+)\s*\(", r"\1^\2(", s)
    for _ in range(4):
        m = re.search(r"(?<![A-Za-z])(sin|cos|tan|sec|csc|cot)\^(\(S\d+\)|\d+)\(", s)
        if not m:
            break
        close = _balanced(s, m.end() - 1)
        if close < 0:
            break
        s = s[:m.start()] + f"{m.group(1)}({s[m.end():close - 1]})^{m.group(2)}" + s[close:]
    s = re.sub(rf"(?<![A-Za-z])(sin|cos|tan|sec|csc|cot)\s*\^\s*(\(S\d+\)|\d+)\s+({_ARG})", r"\1(\3)^\2", s)
    # sin x, sin 3x, ln x, sqrt x, sinx  ->  sin(x) …
    s = re.sub(rf"(?<![A-Za-z])(asin|acos|atan|sinh|cosh|tanh|sin|cos|tan|sec|csc|cot|ln|log|sqrt|exp)\s+({_ARG})",
               r"\1(\2)", s)
    s = re.sub(r"(?<![A-Za-z])(sin|cos|tan|sec|csc|cot|ln)([a-z])\b", r"\1(\2)", s)
    s = re.sub(r"(\d)\s+(?=[a-zA-Z(])", r"\1*", s)             # "2 x" -> 2*x
    s = re.sub(r"(\))\s+(?=[\w(])", r"\1*", s)                  # "(x+1) (x-2)"
    return s


def to_expr(text: str, *, complex_i: bool = False, natural_log: bool = True, formula: bool = False) -> Optional[sp.Expr]:
    """Plain maths text (slots as (S0)…) -> a sympy expression, or None if it isn't clean maths.
    formula=True: a formula already cut out cleanly, where "at" in "u + at" means a times t."""
    s = prepare(text)
    if not s or len(s) > 300 or "__" in s or re.search(r"[^0-9A-Za-z_+\-*/^().,\s]", s):
        return None
    for name in re.findall(r"[A-Za-z_][A-Za-z_0-9]*", s):
        if name.startswith("_"):
            return None
        if name in _WORDS and not (formula and len(name) <= 3):              # "as", "of", "and": words, not maths
            return None
        if name in _KNOWN or re.fullmatch(r"S\d+", name) or (name.isalpha() and len(name) <= 3 and name.islower()):
            continue
        if len(name) == 1:
            continue
        return None
    local = dict(_LETTERS) | dict(_GREEK)
    local.update({"e": sp.E, "E": sp.E, "pi": sp.pi, "oo": sp.oo, "Abs": sp.Abs, "sqrt": sp.sqrt, "exp": sp.exp,
                  "ln": sp.log, "sin": sp.sin, "cos": sp.cos, "tan": sp.tan, "sec": sp.sec, "csc": sp.csc,
                  "cot": sp.cot, "asin": sp.asin, "acos": sp.acos, "atan": sp.atan, "sinh": sp.sinh,
                  "cosh": sp.cosh, "tanh": sp.tanh, "logb": lambda a, b: sp.log(a, b),
                  "log": sp.log if natural_log else (lambda a, b=10: sp.log(a, b)),
                  "log10": lambda a: sp.log(a, 10)})
    for k in range(60):
        local[f"S{k}"] = sp.Symbol(f"S{k}")
    if complex_i:
        local["i"] = sp.I
        local["j"] = sp.I
    else:
        local["i"] = sp.Symbol("i")
    try:
        e = parse_expr(s, local_dict=local, transformations=_TRANSFORMS, evaluate=True)
    except Exception:                                                        # noqa: BLE001 - unreadable = not maths
        return None
    if not isinstance(e, sp.Basic) or isinstance(e, (sp.logic.boolalg.Boolean,)) and not isinstance(e, sp.Expr):
        return None
    return e if isinstance(e, sp.Expr) else None


def split_relation(text: str):
    """'lhs = rhs' / '<' / '<=' … -> (lhs text, op, rhs text) using the first relation sign, or None."""
    m = re.search(r"(<=|>=|!=|=|<|>)", text)
    if not m:
        return None
    return text[:m.start()], m.group(1), text[m.end():]


# ── writing answers the way students read them ─────────────────────────────────────────────────────────────────

def _swap_func(s: str, name: str, build) -> str:
    out, i = [], 0
    pat = re.compile(rf"(?<![A-Za-z]){name}\(")
    while True:
        m = pat.search(s, i)
        if not m:
            out.append(s[i:])
            return "".join(out)
        close = _balanced(s, m.end() - 1)
        if close < 0:
            out.append(s[i:])
            return "".join(out)
        out.append(s[i:m.start()])
        out.append(build(_swap_func(s[m.end():close - 1], name, build)))
        i = close


def fmt_expr(e, *, var_first: Sequence[sp.Symbol] = ()) -> str:
    """A sympy expression in student notation: 3x^2 + 2x, e^(2x), ln(x), sqrt(3), |x|, x sin(x)."""
    e = sp.sympify(e)
    try:
        s = sp.sstr(e, order="lex")
    except Exception:                                                        # noqa: BLE001
        s = sp.sstr(e)
    s = s.replace("**", "^")
    s = _swap_func(s, "exp", lambda a: "e^" + (a if re.fullmatch(r"-?[\w.]+", a) else f"({a})"))
    s = _swap_func(s, "Abs", lambda a: f"|{a}|")
    s = _swap_func(s, "log", lambda a: f"ln({a})")
    s = re.sub(r"\bE\b", "e", s)
    s = re.sub(r"\bI\b", "i", s)
    s = s.replace("oo", "∞")
    s = re.sub(r"(\^(?:\([^()]*\)|[\w./]+))\*(?=[A-Za-z(])", r"\1 ", s)    # x^2*y -> x^2 y
    s = re.sub(r"(?<=\d)\*(?=[A-Za-z(])", "", s)                            # 3*x -> 3x
    s = re.sub(r"(?<=[A-Za-z)])\*(?=(?:(?:sqrt|sin|cos|tan|sec|csc|cot|ln|asin|acos|atan)\b|e\^))", " ", s)
    s = re.sub(r"(?<=[A-Za-z)])\*(?=[A-Za-z(|])", "", s)                    # x*y -> xy, x*(x+1) -> x(x+1)
    s = re.sub(r"(?<=\))\*(?=\d)", "*", s)
    return s


def terminating(q: sp.Rational, max_dp: int = 6) -> bool:
    d = int(q.q)
    for p in (2, 5):
        while d % p == 0:
            d //= p
    if d != 1:
        return False
    return len(str(abs(float(q))).split(".")[-1]) <= max_dp if "." in str(float(q)) else True


def fmt_sig(x, sf: int = 3) -> str:
    """A measured quantity to `sf` significant figures: 6.11, 0.25, 154, 360,000."""
    x = float(x)
    if x == 0 or not math.isfinite(x):
        return "0" if x == 0 else str(x)
    d = sf - 1 - int(math.floor(math.log10(abs(x))))
    r = round(x, d)
    if d <= 0:
        n = int(round(r))
        return f"{n:,}" if abs(n) >= 10000 else str(n)
    out = f"{r:.{d}f}".rstrip("0").rstrip(".")
    return out


def fmt_num(v, *, exact: bool = True, sf: int = 3, fractions: bool = False) -> str:
    """A number:
    - whole numbers as they are;
    - 2.5 rather than 5/2, unless fractions=True (maths answers: 1/4, 5/2);
    - 8/9 when exact is wanted, else 0.889;
    - surds and π kept exact when exact is wanted."""
    v = sp.nsimplify(v) if isinstance(v, float) and exact else sp.sympify(v)
    if v.is_Integer:
        n = int(v)
        return f"{n:,}" if abs(n) >= 10000 and not exact else str(n)
    if v.is_Rational:
        if fractions and v.q <= 20:
            return f"{v.p}/{v.q}"
        if terminating(v, 4):
            return fmt_sig(float(v), 12).rstrip("0").rstrip(".") if "." in str(float(v)) else str(float(v))
        return f"{v.p}/{v.q}" if exact else fmt_sig(float(v), sf)
    if v.is_number and exact:
        return fmt_expr(v)
    try:
        return fmt_sig(float(v), sf)
    except TypeError:
        return fmt_expr(v)


def exact(v):
    """An exact sympy value. Floats become fractions (0.25 -> 1/4); exact values stay as they are — fast, unlike
    nsimplify, which runs a slow numerical search on values like 49π or ln 2."""
    if isinstance(v, float):
        return sp.nsimplify(v, rational=True)
    v = sp.sympify(v)
    if v.has(sp.Float):
        return sp.nsimplify(v, rational=True)
    return v


def frac(v) -> Fraction:
    """Any exact number (int, Fraction, sympy Rational) -> Fraction."""
    if isinstance(v, Fraction):
        return v
    if isinstance(v, int):
        return Fraction(v)
    v = sp.Rational(v)
    return Fraction(int(v.p), int(v.q))
