"""Pure maths with worked steps: equations (one or simultaneous), calculus, algebra, arithmetic, number bases,
statistics, HCF/LCM, primes, combinatorics and matrices. sympy computes; this file shows the working.
solve_math(text) → result dict like engine.solve_problem, or None when the text isn't a maths task it can read.
"""
import math
import re
import statistics

from .units import fmt_num

_SUPMAP = str.maketrans({"⁰": "0", "¹": "1", "²": "2", "³": "3", "⁴": "4", "⁵": "5", "⁶": "6", "⁷": "7", "⁸": "8",
                         "⁹": "9", "⁻": "-", "−": "-", "–": "-", "×": "*", "·": "*", "⋅": "*", "÷": "/", "π": "pi"})
_SUPS = str.maketrans("0123456789-", "⁰¹²³⁴⁵⁶⁷⁸⁹⁻")
_RESERVED = {"sqrt", "sin", "cos", "tan", "cot", "sec", "csc", "log", "ln", "exp", "abs", "pi", "e", "asin", "acos",
             "atan", "sinh", "cosh", "tanh", "factorial", "oo"}


def _norm(s: str) -> str:
    s = re.sub(r"([⁰¹²³⁴⁵⁶⁷⁸⁹⁻]+)", lambda m: "^" + m.group(1), s)
    s = s.translate(_SUPMAP)
    s = re.sub(r"√\s*\(", "sqrt(", s)
    s = re.sub(r"√\s*([A-Za-z0-9.]+)", r"sqrt(\1)", s)
    s = s.replace("^", "**")
    s = re.sub(r"\bln\b", "log", s)
    return s.strip().rstrip(".?!")


def _parse(e: str):
    import sympy
    from sympy.parsing.sympy_parser import parse_expr, standard_transformations, \
        implicit_multiplication_application, convert_xor
    e = _norm(e)
    ids = {n for n in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", e) if n.lower() not in _RESERVED}
    local = {n: sympy.Symbol(n) for n in ids}
    local.update({"e": sympy.E, "pi": sympy.pi, "log": sympy.log})
    return parse_expr(e, local_dict=local, evaluate=True,
                      transformations=standard_transformations + (implicit_multiplication_application, convert_xor))


def _show(expr) -> str:
    """sympy → how a student writes it: x^2, 3x, √(x), π."""
    import sympy
    s = sympy.sstr(expr, order="lex") if not isinstance(expr, str) else expr
    s = s.replace("**", "^")
    s = re.sub(r"\^\(?(-?\d+)\)?(?![\d.])", lambda m: m.group(1).translate(_SUPS), s)    # x^2 → x²
    s = re.sub(r"(\d)\*([A-Za-z(])", r"\1\2", s)          # 3*x → 3x
    s = re.sub(r"(?<=[A-Za-z)])\*(?=[A-Za-z(])", "", s)   # x*y → xy
    s = re.sub(r"(?<=[A-Za-z0-9)])\*(?=(?:sin|cos|tan|log|exp|sqrt)\()", " ", s)    # x^2 sin(x)
    s = re.sub(r"(?<=[A-Za-z0-9)])(?=(?:sin|cos|tan|log|exp|sqrt)\()", " ", s)
    s = s.replace("*", " × ")
    s = re.sub(r"\bsqrt\(", "√(", s)
    s = re.sub(r"\bpi\b", "π", s)
    s = re.sub(r"\blog\(", "ln(", s)
    s = s.replace("oo", "∞")
    return s


def _num(v) -> str:
    import sympy
    if isinstance(v, (int, float)):
        return fmt_num(v)
    if v.is_Integer or (v.is_Rational and v.q < 1000):
        return _show(v)
    if v.is_number and v.is_real:
        exact = _show(sympy.nsimplify(v)) if len(str(v)) < 25 else ""
        approx = fmt_num(float(v))
        return f"{exact} ≈ {approx}" if exact and exact != approx and len(exact) < 20 and not exact.replace(".", "").isdigit() else approx
    return _show(v)


def _result(answer, steps, value=None, kind="algebra"):
    return {"kind": kind, "answer": answer, "value": value, "steps": steps + [f"**Answer:** {answer}"],
            "formulas": [], "confident": True}


# ── equations ─────────────────────────────────────────────────────────────
def _equations(text):
    """'2x + 3 = 7', 'x + y = 5 and x - y = 1' → list of (lhs, rhs) strings."""
    body = re.sub(r"(?i)^.*?\b(solve|find|determine)\b(\s+(the\s+)?(equation|equations|simultaneous equations|for\s+\w+))?\s*:?", "", text)
    body = re.split(r"(?i)\b(hence|then|where|given that)\b", body)[0]
    parts = [p for p in re.split(r"(?i)\s*(?:;|\band\b|,(?=[^=]*=)|\n)\s*", body) if "=" in p]
    eqs = []
    for p in parts:
        if p.count("=") != 1 or re.search(r"[<>≤≥]", p):
            return []
        a, b = p.split("=")
        if not re.search(r"[A-Za-z]", a + b) or len(a + b) > 160:
            return []
        if re.search(r"\b[a-z]{4,}\b", (a + b).lower().replace("sqrt", "").replace("sin", "")):
            return []                                  # words, not maths: a word problem
        eqs.append((a.strip(), b.strip()))
    return eqs


def _linear_steps(lhs, rhs, x):
    """Steps for a linear equation in one unknown: collect x terms, then divide."""
    import sympy
    expr = sympy.expand(lhs - rhs)
    a = expr.coeff(x, 1)
    b = expr.subs(x, 0)
    if a == 0 or sympy.expand(expr - a * x - b) != 0:
        return None
    steps = [f"**Collect the {x} terms on one side:** {_show(a * x)} = {_show(-b)}"]
    sol = sympy.simplify(-b / a)
    if a != 1:
        steps.append(f"**Divide both sides by {_show(a)}:** {x} = {_show(-b)} / {_show(a)} = {_num(sol)}")
    return steps, sol


def _quadratic_steps(lhs, rhs, x):
    import sympy
    expr = sympy.expand(lhs - rhs)
    poly = sympy.Poly(expr, x)
    if poly.degree() != 2:
        return None
    a, b, c = poly.all_coeffs()
    d = sympy.simplify(b ** 2 - 4 * a * c)
    steps = [f"**Write it as ax² + bx + c = 0:** {_show(expr)} = 0, so a = {_show(a)}, b = {_show(b)}, c = {_show(c)}",
             f"**Discriminant:** b² − 4ac = ({_show(b)})² − 4({_show(a)})({_show(c)}) = {_show(d)}"]
    try:
        fac = sympy.factor(expr)
        if fac != expr and fac.is_Mul:
            steps.append(f"**Factorise:** {_show(fac)} = 0")
    except Exception:
        pass
    sols = sympy.solve(sympy.Eq(expr, 0), x)
    if d.is_number and d < 0:
        steps.append("**The discriminant is negative,** so there are no real roots; the roots are complex.")
    else:
        steps.append(f"**Quadratic formula:** {x} = (−b ± √(b² − 4ac)) / 2a = (−({_show(b)}) ± √({_show(d)})) / {_show(2 * a)}")
    return steps, sols


def solve_equations(text):
    import sympy
    eqs = _equations(text)
    if not eqs:
        return None
    try:
        pairs = [(_parse(a), _parse(b)) for a, b in eqs]
    except Exception:
        return None
    syms = sorted(set().union(*[(l - r).free_symbols for l, r in pairs]), key=str)
    if not syms or len(syms) > 3:
        return None
    want = re.search(r"(?i)\bfor\s+([a-z])\b", text)
    if len(pairs) == 1:
        lhs, rhs = pairs[0]
        x = sympy.Symbol(want.group(1)) if want and sympy.Symbol(want.group(1)) in syms else (syms[0] if len(syms) == 1 else None)
        if x is None:
            return None
        steps = [f"**Equation:** {_show(lhs)} = {_show(rhs)}"]
        lin = _linear_steps(lhs, rhs, x)
        if lin:
            steps += lin[0]
            return _result(f"{x} = {_num(lin[1])}", steps, float(lin[1]) if lin[1].is_real else None)
        quad = _quadratic_steps(lhs, rhs, x)
        if quad:
            qs, sols = quad
            steps += qs
            if not sols:
                return None
            ans = " or ".join(f"{x} = {_num(s)}" for s in sols)
            real = [float(s) for s in sols if s.is_real]
            return _result(ans, steps, real[0] if real else None)
        sols = sympy.solve(sympy.Eq(lhs, rhs), x)
        if not sols:
            return None
        ans = " or ".join(f"{x} = {_num(s)}" for s in sols[:6])
        real = [float(s) for s in sols if s.is_real]
        return _result(ans, steps, real[0] if real else None)
    if len(pairs) < len(syms):
        return None
    sol = sympy.solve([sympy.Eq(l, r) for l, r in pairs], syms, dict=True)
    if not sol or len(sol) > 2:
        return None
    s0 = sol[0]
    if any(v not in s0 for v in syms):
        return None
    steps = ["**Equations:** " + "; ".join(f"({i}) {_show(l)} = {_show(r)}" for i, (l, r) in enumerate(pairs, 1))]
    if len(pairs) == 2 and len(syms) == 2:
        x, y = syms
        steps.append(f"**Eliminate one unknown:** combine (1) and (2) so {x} or {y} cancels, solve for the other, "
                     f"then substitute back.")
    ans = ", ".join(f"{v} = {_num(s0[v])}" for v in syms)
    check = "; ".join(f"({i}) {_show(l.subs(s0))} = {_show(r.subs(s0))}" for i, (l, r) in enumerate(pairs, 1))
    steps.append(f"**Check by substituting:** {check}")
    return _result(ans, steps, float(s0[syms[0]]) if s0[syms[0]].is_real else None)


# ── calculus and algebra ──────────────────────────────────────────────────
def _expr_after(text, words):
    m = re.search(r"(?i)\b(?:" + words + r")\b\s*(?:the\s+)?(?:expression\s+|function\s+)?(?:of\s+)?(?:y\s*=\s*|f\(x\)\s*=\s*)?(.+)$",
                  text)
    if not m:
        return None
    e = m.group(1)
    e = re.split(r"(?i)\s+(?:with respect to|w\.?r\.?t\.?|from|between|as)\b", e)[0]
    return e.strip().rstrip(".?")


def calculus(text):
    import sympy
    low = text.lower()
    wrt = re.search(r"(?i)(?:with respect to|w\.?r\.?t\.?|d/d)\s*([a-z])\b", text)
    if re.search(r"\b(differentiate|derivative|dy/dx|d/dx|gradient function)\b", low):
        e = _expr_after(text, r"differentiate|derivative of|find dy/dx (?:if|when|for)|find dy/dx|dy/dx (?:of|for)|d/dx")
        if not e:
            return None
        try:
            f = _parse(e)
        except Exception:
            return None
        x = sympy.Symbol(wrt.group(1)) if wrt else (sorted(f.free_symbols, key=str) or [sympy.Symbol("x")])[0]
        raw = sympy.diff(f, x)
        d = min((sympy.expand(raw), sympy.simplify(raw), raw), key=lambda e: len(str(e)) + (5 if e.is_Mul and e.args[0].is_Symbol else 0))
        steps = [f"**Function:** y = {_show(f)}"]
        if f.is_polynomial(x) and f.is_Add:
            steps.append("**Power rule** term by term: d/d" + str(x) + "(a" + str(x) + "ⁿ) = na" + str(x) + "ⁿ⁻¹")
            steps.append("**Each term:** " + "; ".join(f"{_show(t)} → {_show(sympy.diff(t, x))}" for t in f.as_ordered_terms()))
        elif f.is_Mul and len([a for a in f.args if a.has(x)]) == 2:
            steps.append("**Product rule:** d(uv)/dx = u dv/dx + v du/dx")
        elif f.is_Pow and f.args[0].has(x) and not f.args[0].is_Symbol:
            steps.append("**Chain rule:** differentiate the outside, then multiply by the derivative of the inside")
        elif isinstance(f, sympy.Mul) and any(a.is_Pow and a.args[1] == -1 for a in f.args):
            steps.append("**Quotient rule:** d(u/v)/dx = (v du/dx − u dv/dx) / v²")
        return _result(f"dy/d{x} = {_show(d)}", steps, None)
    if re.search(r"\b(integrate|integral|antiderivative|∫)", low):
        e = _expr_after(text, r"integrate|integral of|antiderivative of|∫")
        if not e:
            return None
        e = re.sub(r"\s*d([a-z])\s*$", "", e)
        try:
            f = _parse(e)
        except Exception:
            return None
        x = sympy.Symbol(wrt.group(1)) if wrt else (sorted(f.free_symbols, key=str) or [sympy.Symbol("x")])[0]
        F = sympy.integrate(f, x)
        if F.has(sympy.Integral):
            return None
        lim = re.search(r"(?i)\b(?:from|between)\s+(-?[\w./]+)\s+(?:to|and)\s+(-?[\w./]+)", text)
        steps = [f"**Integrand:** {_show(f)}", f"**Antiderivative:** ∫{_show(f)} d{x} = {_show(F)}"]
        if lim:
            try:
                a, b = _parse(lim.group(1)), _parse(lim.group(2))
            except Exception:
                return None
            val = sympy.simplify(F.subs(x, b) - F.subs(x, a))
            steps.append(f"**Limits:** [{_show(F)}] from {_show(a)} to {_show(b)} = ({_show(F.subs(x, b))}) − ({_show(F.subs(x, a))})")
            return _result(f"{_num(val)}", steps, float(val) if val.is_real else None)
        return _result(f"{_show(F)} + C", steps, None)
    if re.search(r"\blim(it)?\b", low):
        m = re.search(r"(?i)\blim(?:it)?\s*(?:of)?\s*(.+?)\s+as\s+([a-z])\s*(?:->|→|tends to|approaches)\s*(-?[\w.]+|∞|infinity)", text)
        if not m:
            return None
        try:
            f = _parse(m.group(1))
            x = sympy.Symbol(m.group(2))
            a = sympy.oo if m.group(3) in ("∞", "infinity") else _parse(m.group(3))
            val = sympy.limit(f, x, a)
        except Exception:
            return None
        return _result(_num(val), [f"**Limit:** lim {_show(f)} as {x} → {_show(a)}"], float(val) if val.is_real and val.is_finite else None)
    for word, fn, label in (("factori[sz]e|factor", sympy.factor, "Factorised"), ("expand", sympy.expand, "Expanded"),
                            ("simplify", sympy.simplify, "Simplified")):
        if re.search(r"\b(" + word + r")\b", low):
            e = _expr_after(text, word)
            if not e or "=" in e:
                return None
            try:
                f = _parse(e)
                out = fn(f)
            except Exception:
                return None
            if out == f and label != "Simplified":
                return None
            return _result(_show(out), [f"**Expression:** {_show(f)}", f"**{label}:** {_show(out)}"], None)
    return None


# ── numbers ───────────────────────────────────────────────────────────────
_NUMS = re.compile(r"-?\d+(?:\.\d+)?")


def _numbers(s):
    return [float(x) for x in _NUMS.findall(s)]


def statistics_task(text):
    low = text.lower()
    m = re.search(r"\b(mean|average|median|mode|range|variance|standard deviation)\b", low)
    if not m:
        return None
    data_part = re.split(r"\b(?:of|for|are|is|data|numbers|values|scores|marks)\b\s*:?", text, flags=re.I)[-1]
    xs = _numbers(data_part)
    if len(xs) < 3 or re.search(r"[A-Za-z]{2,}", re.sub(r"\band\b", "", data_part)):
        return None                                   # "average speed of a car that travels 150 m": not a data set
    srt = sorted(xs)
    steps = [f"**Data ({len(xs)} values), in order:** " + ", ".join(fmt_num(v) for v in srt)]
    out = []
    kinds = re.findall(r"\b(mean|average|median|mode|range|variance|standard deviation)\b", low)
    for k in dict.fromkeys(kinds):
        if k in ("mean", "average"):
            v = sum(xs) / len(xs)
            steps.append(f"**Mean:** ({' + '.join(fmt_num(x) for x in xs)}) / {len(xs)} = {fmt_num(sum(xs))} / {len(xs)} = {fmt_num(v)}")
            out.append(f"mean = {fmt_num(v)}")
        elif k == "median":
            v = statistics.median(xs)
            n = len(xs)
            how = f"the middle value (position {(n + 1) // 2})" if n % 2 else f"the mean of the two middle values ({fmt_num(srt[n // 2 - 1])} and {fmt_num(srt[n // 2])})"
            steps.append(f"**Median:** {how} = {fmt_num(v)}")
            out.append(f"median = {fmt_num(v)}")
        elif k == "mode":
            counts = {x: xs.count(x) for x in set(xs)}
            top = max(counts.values())
            modes = sorted(x for x, c in counts.items() if c == top)
            if top == 1:
                steps.append("**Mode:** every value appears once, so there is no mode")
                out.append("no mode")
            else:
                steps.append(f"**Mode:** the most frequent value ({top} times): {', '.join(fmt_num(x) for x in modes)}")
                out.append("mode = " + ", ".join(fmt_num(x) for x in modes))
        elif k == "range":
            steps.append(f"**Range:** {fmt_num(srt[-1])} − {fmt_num(srt[0])} = {fmt_num(srt[-1] - srt[0])}")
            out.append(f"range = {fmt_num(srt[-1] - srt[0])}")
        else:
            sample = "sample" in low
            mu = sum(xs) / len(xs)
            ss = sum((x - mu) ** 2 for x in xs)
            var = ss / (len(xs) - 1 if sample else len(xs))
            steps.append(f"**Mean:** {fmt_num(mu)}; **sum of squared deviations:** Σ(x − x̄)² = {fmt_num(ss)}")
            steps.append(f"**Variance ({'sample, ÷ (n − 1)' if sample else 'population, ÷ n'}):** {fmt_num(ss)} / "
                         f"{len(xs) - 1 if sample else len(xs)} = {fmt_num(var)}")
            if k == "standard deviation":
                steps.append(f"**Standard deviation:** √{fmt_num(var)} = {fmt_num(math.sqrt(var))}")
                out.append(f"standard deviation = {fmt_num(math.sqrt(var))}")
            else:
                out.append(f"variance = {fmt_num(var)}")
    if not out:
        return None
    return _result("; ".join(out), steps, None, kind="statistics")


_BASES = {"binary": 2, "base 2": 2, "octal": 8, "base 8": 8, "decimal": 10, "denary": 10, "base 10": 10,
          "hexadecimal": 16, "hex": 16, "base 16": 16}


def bases(text):
    low = text.lower()
    if not re.search(r"\b(convert|binary|octal|hex|hexadecimal|denary|base \d+)\b", low):
        return None
    m = re.search(r"\b([0-9a-f]+)\s*(?:\(|_)?\s*(?:base\s*)?(2|8|10|16)?\)?\s*(?:₂|₈|₁₀|₁₆)?\s*(?:in\s+(binary|octal|hex|hexadecimal|decimal|denary))?"
                  r"\s*(?:to|into|in)\s+(binary|octal|hexadecimal|hex|decimal|denary|base\s*\d+)", low)
    if not m:
        return None
    digits, frm, frm_word, to_word = m.groups()
    to = _BASES.get(re.sub(r"\s+", " ", to_word))
    src = int(frm) if frm else (_BASES.get(frm_word) if frm_word else None)
    if src is None:
        before = low[:m.start()]
        src = next((b for w, b in _BASES.items() if w in before), None)
    if src is None:
        src = 2 if set(digits) <= {"0", "1"} and to != 2 else (16 if re.search(r"[a-f]", digits) else 10)
    if to is None or src == to:
        return None
    try:
        n = int(digits, src)
    except ValueError:
        return None
    steps = []
    if src != 10:
        terms = [f"{int(d, 16)}×{src}^{p}" for p, d in enumerate(reversed(digits)) if d != "0"]
        steps.append(f"**To decimal:** {' + '.join(reversed(terms))} = {n}")
    if to != 10:
        q, rems = n, []
        while q:
            rems.append(q % to)
            q //= to
        out = "".join("0123456789ABCDEF"[r] for r in reversed(rems)) or "0"
        steps.append(f"**Divide by {to} repeatedly and read the remainders upwards:** remainders "
                     f"{', '.join('0123456789ABCDEF'[r] for r in rems)} → {out}")
    else:
        out = str(n)
    sub = {2: "₂", 8: "₈", 10: "₁₀", 16: "₁₆"}
    return _result(f"{digits.upper()}{sub[src]} = {out}{sub[to]}", steps, None, kind="bases")


def number_theory(text):
    low = text.lower()
    xs = [int(x) for x in re.findall(r"\b\d+\b", text)]
    if re.search(r"\b(hcf|gcd|highest common factor|greatest common divisor)\b", low) and len(xs) >= 2:
        g = xs[0]
        for v in xs[1:]:
            g = math.gcd(g, v)
        steps = [f"**Prime factors:** " + "; ".join(f"{v} = {_factor_str(v)}" for v in xs),
                 "**HCF:** the product of the primes they all share, with the lowest powers"]
        return _result(f"HCF = {g}", steps, g, kind="numbers")
    if re.search(r"\b(lcm|lowest common multiple|least common multiple)\b", low) and len(xs) >= 2:
        l = xs[0]
        for v in xs[1:]:
            l = l * v // math.gcd(l, v)
        steps = [f"**Prime factors:** " + "; ".join(f"{v} = {_factor_str(v)}" for v in xs),
                 "**LCM:** every prime that appears, with the highest power"]
        return _result(f"LCM = {l}", steps, l, kind="numbers")
    if re.search(r"\bprime factor", low) and xs:
        n = xs[0]
        return _result(f"{n} = {_factor_str(n)}", [f"**Divide by primes in turn:** {_division_ladder(n)}"], None, kind="numbers")
    m = re.search(r"\b(\d+)\s*([CP])\s*(\d+)\b", text) or re.search(r"\b([CP])\s*\(\s*(\d+)\s*,\s*(\d+)\s*\)", text)
    if m:
        g = m.groups()
        kind, n, r = (g[1], int(g[0]), int(g[2])) if g[0].isdigit() else (g[0], int(g[1]), int(g[2]))
        if r > n:
            return None
        if kind == "C":
            v = math.comb(n, r)
            steps = [f"**Combinations:** ⁿCᵣ = n! / (r!(n − r)!) = {n}! / ({r}! × {n - r}!)"]
            return _result(f"{n}C{r} = {v}", steps, v, kind="numbers")
        v = math.perm(n, r)
        return _result(f"{n}P{r} = {v}", [f"**Permutations:** ⁿPᵣ = n! / (n − r)! = {n}! / {n - r}!"], v, kind="numbers")
    m = re.fullmatch(r"\s*(?:what is|find|calculate|evaluate)?\s*(\d+)\s*!\s*\??\s*", low)
    if m:
        n = int(m.group(1))
        if n <= 30:
            v = math.factorial(n)
            return _result(f"{n}! = {v}", [f"**Factorial:** {n}! = {' × '.join(str(i) for i in range(n, 0, -1))}"], v, kind="numbers")
    return None


def _factor_str(n):
    import sympy
    f = sympy.factorint(n)
    return " × ".join(f"{p}^{e}" if e > 1 else str(p) for p, e in sorted(f.items())) if f else str(n)


def _division_ladder(n):
    out, p, q = [], 2, n
    while q > 1 and p * p <= q:
        while q % p == 0:
            out.append(f"{q} ÷ {p} = {q // p}")
            q //= p
        p += 1
    if q > 1 and out:
        out.append(f"{q} is prime")
    return "; ".join(out) if out else f"{n} is prime"


def percentages(text):
    low = text.lower()
    m = re.search(r"(-?\d+(?:\.\d+)?)\s*(?:%|percent|per cent)\s+of\s+(-?\d+(?:\.\d+)?)", low)
    if m:
        p, n = float(m.group(1)), float(m.group(2))
        v = p / 100 * n
        return _result(f"{fmt_num(v)}", [f"**{fmt_num(p)}% of {fmt_num(n)}:** {fmt_num(p)}/100 × {fmt_num(n)} = {fmt_num(v)}"],
                       v, kind="numbers")
    m = re.search(r"\b(increase|decrease|reduce)\s+(-?\d+(?:\.\d+)?)\s+by\s+(\d+(?:\.\d+)?)\s*%", low)
    if m:
        verb, n, p = m.group(1), float(m.group(2)), float(m.group(3))
        k = 1 + p / 100 if verb == "increase" else 1 - p / 100
        return _result(fmt_num(n * k), [f"**Multiplier:** {fmt_num(k)}", f"**{fmt_num(n)} × {fmt_num(k)}** = {fmt_num(n * k)}"],
                       n * k, kind="numbers")
    m = re.search(r"(-?\d+(?:\.\d+)?)\s+as\s+a\s+percentage\s+of\s+(-?\d+(?:\.\d+)?)", low)
    if m:
        a, b = float(m.group(1)), float(m.group(2))
        v = a / b * 100
        return _result(f"{fmt_num(v)}%", [f"**{fmt_num(a)} / {fmt_num(b)} × 100** = {fmt_num(v)}%"], v, kind="numbers")
    return None


def matrices(text):
    import sympy
    low = text.lower()
    if not re.search(r"\b(determinant|inverse|det)\b", low):
        return None
    m = re.search(r"\[\s*\[.*\]\s*\]", text, re.S)
    if not m:
        return None
    try:
        rows = re.findall(r"\[([^\[\]]+)\]", m.group(0))
        M = sympy.Matrix([[_parse(x) for x in r.split(",")] for r in rows])
    except Exception:
        return None
    if M.rows != M.cols or M.rows > 4:
        return None
    d = M.det()
    steps = [f"**Matrix:** {_show(M.tolist())}"]
    if M.rows == 2:
        a, b, c, dd = M
        steps.append(f"**Determinant:** ad − bc = ({_show(a)})({_show(dd)}) − ({_show(b)})({_show(c)}) = {_show(d)}")
    else:
        steps.append(f"**Determinant** (expansion along the first row) = {_show(d)}")
    if "inverse" in low:
        if d == 0:
            return _result("no inverse (the determinant is 0)", steps, None, kind="matrices")
        inv = M.inv()
        steps.append("**Inverse:** (1/det) × adjugate")
        return _result(_show(inv.tolist()), steps, None, kind="matrices")
    return _result(f"det = {_show(d)}", steps, float(d) if d.is_real else None, kind="matrices")


def arithmetic(text):
    """A bare calculation: '3.5 × 2^4 − √49', 'what is 15/4 + 2'."""
    import sympy
    m = re.fullmatch(r"\s*(?:what is|calculate|evaluate|work out|find|compute)?\s*(?:the value of)?\s*([-+*/^().\d\s×÷·√%πe!]+?)\s*[=?.]*\s*",
                     text.lower().replace("−", "-").replace("–", "-"))
    if not m or not re.search(r"\d", m.group(1)) or not re.search(r"[-+*/^×÷√!]", m.group(1)):
        return None
    e = m.group(1).replace("%", "/100")
    try:
        v = _parse(e)
    except Exception:
        return None
    if v.free_symbols or not v.is_number:
        return None
    exact = sympy.nsimplify(v) if v.is_Rational else v
    return _result(_num(exact), [f"**Calculate:** {_show(_parse(e) if False else e.replace('**', '^'))} = {_num(exact)}"],
                   float(v), kind="arithmetic")


def solve_math(text: str):
    """The first maths task CUSTOM-Mx recognises in `text`, worked; None otherwise."""
    t = re.sub(r"\s+", " ", (text or "").strip())
    if not t or len(t) > 400:
        return None
    for fn in (matrices, bases, statistics_task, number_theory, percentages, calculus, solve_equations, arithmetic):
        try:
            r = fn(t)
        except Exception:
            r = None
        if r:
            return r
    return None
