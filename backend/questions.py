"""
Deterministic question generation + grading for Lunar.

Questions and answers are built STRICTLY from the slide — the LLM never invents
them (it only explains/chats elsewhere).

- Calculation questions: parse the slide's worked example (its formula + the
  numeric givens), tweak the numbers, and re-solve with sympy following the SAME
  formula — so the answer is provably correct and the steps mirror the example.
- Recall questions: definitions, enumerations and theorems/rules taken verbatim
  from the slide. Slides with none of these (titles, author/dedication pages)
  simply produce zero questions, so no quiz button appears for them.

nomic-embed-text embeddings are used throughout: to rank sentences by salience,
to guarantee every question is unique (cosine dedupe, not string match), and to
grade free-text answers by meaning. Calculation answers are graded numerically.
"""

import re

from backend import local_llm

MAX_QUESTIONS = 10
_MAX_SLIDE_CHARS = 2400

_WORD = re.compile(r"[a-z0-9]+")
_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")

# Operator glyphs (incl. legacy Symbol-font PUA codepoints) PDFs use, by code
# point so the source never holds an exotic literal (an empty/garbled dict key
# would make str.replace corrupt every string).
_MUL = [0x00D7, 0x00B7, 0x2219, 0x2715, 0x2217, 0x22C5, 0xF0B4, 0xF0D7]  # x . * etc.
_DIV = [0x00F7, 0x2215, 0x2044, 0xF0B8]
_MINUS = [0x2212, 0x2013, 0x2014, 0xF02D]
_SQRT_CLASS = "[" + chr(0x221A) + chr(0xF0D6) + "]"
_FUNC_APP = chr(0x2061)

# Names sympy must keep as functions/constants (everything else in a formula is
# treated as a variable symbol).
_RESERVED = {"sqrt", "sin", "cos", "tan", "cot", "sec", "csc", "log", "ln",
             "exp", "abs", "pi", "e"}


def _mathify(s: str) -> str:
    for cp in _MUL:
        s = s.replace(chr(cp), "*")
    for cp in _DIV:
        s = s.replace(chr(cp), "/")
    for cp in _MINUS:
        s = s.replace(chr(cp), "-")
    s = s.replace(_FUNC_APP, "")
    s = s.replace("\\times", "*").replace("\\cdot", "*").replace("\\div", "/")
    s = re.sub(r"\^\s*", "**", s)                                       # 2^3 -> 2**3
    s = re.sub(_SQRT_CLASS + r"\s*\(", "sqrt(", s)                      # sqrt( forms
    s = re.sub(_SQRT_CLASS + r"\s*(\d+(?:\.\d+)?)", r"sqrt(\1)", s)     # sqrt2 -> sqrt(2)
    return s


def _sentences(text: str) -> list:
    """Split a slide into clean candidate sentences."""
    out = []
    for raw in re.split(r"(?<=[.!?])\s+|\n+", text or ""):
        s = re.sub(r"\s+", " ", raw).strip(" \t-")
        if 14 <= len(s) <= 320 and re.search(r"[a-zA-Z]", s):
            out.append(s)
    return out


# ----------------------------------------------------------------------
# Calculation questions (sympy)
# ----------------------------------------------------------------------
_ASSIGN = re.compile(r"\b([A-Za-z][A-Za-z0-9_]{0,12})\s*=\s*([^=,\n;]+?)(?=(?:[,;\n]|\.\s|\s{2,}|$))")
_UNIT = re.compile(r"=\s*-?\d+(?:\.\d+)?\s*([A-Za-z" + chr(0x03A9) + chr(0x00B0) + r"%/]+)")


def _format_num(x) -> str:
    if x is None:
        return ""
    try:
        xf = float(x)
    except (TypeError, ValueError):
        return str(x)
    if abs(xf - round(xf)) < 1e-9:
        return str(int(round(xf)))
    return f"{round(xf, 3):g}"


def _parse_example(slide_text: str):
    """Pull the governing formula + numeric givens out of a worked example.

    Returns (lhs, rhs_expr, input_vars, givens, unit) or None.
    """
    try:
        import sympy
    except Exception:
        return None

    math = _mathify(slide_text)
    givens, formulas = {}, []
    for m in _ASSIGN.finditer(math):
        var, rhs = m.group(1), m.group(2).strip()
        first = rhs.split()[0] if rhs else ""
        if re.fullmatch(r"-?\d+(?:\.\d+)?", first):
            try:
                givens.setdefault(var, float(first))
            except ValueError:
                pass
        elif re.search(r"[A-Za-z]", rhs):
            formulas.append((var, rhs))

    for lhs, rhs in formulas:
        rhs_clean = re.split(r"\s{2,}", rhs)[0].strip()        # drop trailing prose
        if not re.search(r"[+\-*/]", rhs_clean):               # must be a real operation
            continue
        # Force identifiers to be symbols — otherwise sympy reads I, E, etc. as
        # the imaginary unit / Euler's number. Keep real functions/constants.
        ids = {n for n in re.findall(r"[A-Za-z][A-Za-z0-9_]*", rhs_clean)
               if n.lower() not in _RESERVED}
        local = {n: sympy.Symbol(n) for n in ids}
        try:
            expr = sympy.sympify(rhs_clean, locals=local, evaluate=False)
        except Exception:
            continue
        in_vars = sorted({str(s) for s in expr.free_symbols})
        if not in_vars or lhs in in_vars:
            continue
        if not all(v in givens for v in in_vars):              # need every input's value
            continue
        unit_m = re.search(re.escape(lhs) + r"\s*=\s*-?\d+(?:\.\d+)?\s*([A-Za-z" +
                           chr(0x03A9) + chr(0x00B0) + r"%/]+)", math)
        unit = unit_m.group(1) if unit_m else ""
        return lhs, expr, in_vars, {v: givens[v] for v in in_vars}, unit
    return None


def solve_selection(text: str):
    """Best-effort EXACT solve of a highlighted equation / inequality / arithmetic.

    The 1.5B model is poor at computation, so when the student boxes something that
    is actually solvable we compute it with sympy and feed the result to the model
    to *explain* — anchoring its working to the correct answer. Returns a short
    answer string, or None when it can't parse confidently (then the LLM solves
    unaided, exactly as before — never worse).
    """
    raw = (text or "").strip()
    if not raw or len(raw) > 220:
        return None
    try:
        import sympy
        from sympy.parsing.sympy_parser import (
            parse_expr, standard_transformations, implicit_multiplication_application)
    except Exception:
        return None

    s = _mathify(raw).replace("≤", "<=").replace("≥", ">=").replace("≠", "!=")
    s = re.sub(r"\s+", " ", s).strip()
    # take only the leading mathematical part (drop trailing prose)
    s = re.split(r"\b(where|hence|so|therefore|thus|find|solve|given)\b", s, flags=re.I)[0].strip()
    if not re.search(r"[0-9A-Za-z]", s):
        return None
    transf = standard_transformations + (implicit_multiplication_application,)

    def _p(e):
        ids = {n for n in re.findall(r"[A-Za-z][A-Za-z0-9_]*", e) if n.lower() not in _RESERVED}
        return parse_expr(e, local_dict={n: sympy.Symbol(n) for n in ids},
                          transformations=transf, evaluate=True)

    rels = list(re.finditer(r"(<=|>=|!=|=|<|>)", s))
    try:
        if len(rels) == 1:
            op = rels[0].group(1)
            lhs = _p(s[:rels[0].start()].strip())
            rhs = _p(re.split(r"[,;]\s", s[rels[0].end():].strip())[0].strip())
            syms = sorted((lhs - rhs).free_symbols, key=str)
            if len(syms) != 1:
                return None
            x = syms[0]
            if op == "=":
                sols = sympy.solve(sympy.Eq(lhs, rhs), x)
                if not sols:
                    return None
                return ", ".join(f"{x} = {_format_num(v) if v.is_number else v}" for v in sols)
            rel = {"<": lhs < rhs, "<=": lhs <= rhs, ">": lhs > rhs,
                   ">=": lhs >= rhs, "!=": sympy.Ne(lhs, rhs)}[op]
            res = sympy.reduce_inequalities(rel, x)
            out = str(res).replace("&", "and").replace("|", "or")
            out = re.sub(r"\(-oo < \w+\) and ", "", out)
            out = re.sub(r" and \(\w+ < oo\)", "", out)
            return out.replace("oo", "∞")
        if len(rels) == 0:
            if not re.fullmatch(r"[0-9.+\-*/() ]+", s):   # pure arithmetic only
                return None
            expr = _p(s)
            if expr.free_symbols:
                return None
            return _format_num(sympy.N(expr))
    except Exception:
        return None
    return None


def _var_name(slide_text: str, sym: str) -> str:
    """A readable name for a symbol if the slide spells it out (e.g. 'V = voltage')."""
    m = re.search(re.escape(sym) + r"\s*(?:=|is|:)\s*(?:the\s+)?([a-z][a-z ]{2,24})", slide_text, re.I)
    if m:
        name = m.group(1).strip()
        if not re.search(r"\d", name):
            return name
    return sym


def _tweak(value: float, i: int, j: int) -> float:
    factors = [2, 3, 1.5, 4, 0.5, 5, 2.5, 6, 0.25, 8]
    f = factors[(i + j) % len(factors)]
    nv = value * f
    nv = round(nv) if float(value).is_integer() else round(nv, 2)
    if nv == 0:
        nv = value + i + j + 1
    return nv


def calc_questions(slide_text: str, want: int) -> list:
    """Up to `want` calculation questions built from the slide's example."""
    parsed = _parse_example(slide_text)
    if not parsed:
        return []
    import sympy
    lhs, expr, in_vars, givens, unit = parsed
    target_name = _var_name(slide_text, lhs)
    syms = {v: sympy.Symbol(v) for v in in_vars}

    out, seen = [], set()
    i = 0
    while len(out) < want and i < want * 5:
        i += 1
        tw = {v: _tweak(givens[v], i, j) for j, v in enumerate(in_vars)}
        key = tuple(tw[v] for v in in_vars)
        if key in seen or all(tw[v] == givens[v] for v in in_vars):
            continue
        seen.add(key)
        try:
            val = float(expr.subs({syms[v]: tw[v] for v in in_vars}))
        except Exception:
            continue
        if val != val or abs(val) == float("inf"):             # NaN / inf
            continue
        given_str = ", ".join(f"{_var_name(slide_text, v)} = {_format_num(tw[v])}" for v in in_vars)
        ans = f"{_format_num(val)}{(' ' + unit) if unit else ''}".strip()
        if len(out) % 3 == 2:
            q = (f"Suppose {given_str}. Using the method from this slide, "
                 f"work out {target_name}.")
        else:
            q = f"Given {given_str}, calculate {target_name}."
        # Worked step that mirrors the example: substitute the tweaked numbers.
        sub_str = str(expr)
        for v in in_vars:
            sub_str = re.sub(r"\b" + re.escape(v) + r"\b", _format_num(tw[v]), sub_str)
        pretty = lambda t: t.replace("**", "^").replace("*", " " + chr(0x00D7) + " ").replace("/", " / ")
        work = f"{lhs} = {pretty(str(expr))}\n{lhs} = {pretty(sub_str)} = {ans}"
        out.append({"type": "calculation", "kind": "numeric", "q": q, "a": ans, "work": work})
    return out


# ----------------------------------------------------------------------
# Recall questions (definitions / enumerations / theorems)
# ----------------------------------------------------------------------
_DEF = re.compile(
    r"^(?:the\s+|an?\s+)?(?P<term>[A-Za-z][\w\-'()]*(?:\s+[\w\-'()]+){0,5}?)\s+"
    r"(?:is|are)\s+(?:defined as|called|known as|the\s+)?"
    r"(?P<rest>.+)$", re.I)
_DEF_COLON = re.compile(r"^(?P<term>[A-Za-z][\w\-'() ]{2,48}?):\s+(?P<rest>.{8,})$")
_ENUM_CUE = re.compile(
    r"\b(types|kinds|categories|forms|classes|properties|steps|stages|components|"
    r"elements|parts|conditions|axioms|include|includes|consist[s]? of|are|"
    r"the following)\b", re.I)
_THEOREM = re.compile(r"\b(theorem|lemma|corollary|axiom|postulate|law|principle|rule|property)\b", re.I)
_BAD_SUBJECT = re.compile(
    r"\b(lecturer|instructor|professor|department|faculty|university|college|school|"
    r"chapter|exercise|author|page|references?|figure|table|example)\b", re.I)
# Words a real definition's subject never starts with (proof connectives,
# pronouns, prepositions) — these are sentence fragments, not concepts.
_STOP_LEAD = {
    "since", "thus", "therefore", "hence", "however", "then", "if", "when", "where",
    "while", "because", "so", "and", "but", "for", "this", "that", "these", "those",
    "it", "its", "they", "we", "you", "here", "there", "now", "also", "finally",
    "first", "second", "third", "next", "given", "let", "suppose", "consider", "note",
    "recall", "clearly", "every", "each", "any", "all", "some", "to", "in", "on", "of",
    "as", "by", "with", "from", "at", "which", "who", "what", "no",
}


def _definition_q(s: str):
    m = _DEF.match(s) or _DEF_COLON.match(s)
    if not m:
        return None
    term = m.group("term").strip().rstrip(".")
    rest = m.group("rest").strip()
    words = term.split()
    if not words or _BAD_SUBJECT.search(term) or len(rest) < 8:
        return None
    if len(words) > 5 or words[0].lower() in _STOP_LEAD:
        return None
    # A generic single lowercase variable ("a", "x") isn't a definable concept;
    # a single uppercase symbol (Q, N, R) usually is. Otherwise require a real word.
    if len(term) == 1 and term.islower():
        return None
    if not term.isupper() and not re.search(r"[A-Za-z]{3}", term):
        return None
    return {"type": "definition", "kind": "text", "q": f"What is {term}?", "a": s}


def _enumeration_q(s: str):
    if not _ENUM_CUE.search(s) or _BAD_SUBJECT.search(s):
        return None
    tail = re.sub(r"^.*?(?:are|include[s]?|consist[s]? of|:)\s*", "", s, flags=re.I)
    items = [it.strip(" .;") for it in re.split(r",\s*|\s+and\s+|\s+or\s+", tail)]
    items = [it for it in items if len(it) > 1]
    if len(items) < 2:
        return None
    cue = _ENUM_CUE.search(s).group(0).lower()
    return {"type": "enumeration", "kind": "text",
            "q": f"List the {cue} described on this slide.", "a": s}


def _theorem_q(s: str):
    if not _THEOREM.search(s) or _BAD_SUBJECT.search(s):
        return None
    kind = _THEOREM.search(s).group(0).lower()
    return {"type": "theorem", "kind": "text", "q": f"State the {kind} given on this slide.", "a": s}


# ----------------------------------------------------------------------
# Crib sheet — deterministic formulas / definitions / theorems across a deck
# ----------------------------------------------------------------------
_PROSE_RHS = re.compile(r"\b(the|is|are|of|set|called|where|number|value|"
                        r"function|given|denoted|such|that|domain|range)\b", re.I)
_REAL_OP = re.compile(r"[+\-/^]|\*|sqrt|sin|cos|tan|log|ln")
_FUNC_CALL = re.compile(r"^[A-Za-z][A-Za-z0-9]*\s*\([^()]*\)\.?$")
_STOP_TERM = re.compile(
    r"^(since|this|that|these|those|there|then|thus|hence|therefore|so|where|for|"
    r"let|we|it|if|when|which|in|on|by|as|also|now|here|each|every|both|either|such)\b", re.I)


def formula_lines(text: str) -> list:
    """Real formula relations on a slide, e.g. 'V = I × R' or 'A = pi × r^2'."""
    math = _mathify(text)
    out = []
    for m in _ASSIGN.finditer(math):
        var, rhs = m.group(1), m.group(2).strip()
        rhs = re.split(r"\s{2,}", rhs)[0]
        rhs = re.split(r"\.\s", rhs)[0].strip().rstrip(".")   # cut trailing prose/sentence
        if not (1 <= len(rhs) <= 40) or not re.search(r"[A-Za-z0-9]", rhs):
            continue
        if "{" in rhs or "}" in rhs:               # set-builder notation, not a formula
            continue
        if _FUNC_CALL.match(rhs):                   # 'y = f(x)' is notation, not a formula
            continue
        if _PROSE_RHS.search(rhs) or not _REAL_OP.search(rhs):
            continue
        pretty = f"{var} = {rhs}".replace("**", "^").replace("*", " " + chr(0x00D7) + " ").replace("/", " / ")
        out.append(re.sub(r"\s+", " ", pretty).strip())
    return out


def definition_pairs(text: str) -> list:
    """(term, meaning) pairs — meaning is just the predicate, not the whole line."""
    out = []
    for s in _sentences(text):
        if _THEOREM.search(s):          # belongs in the theorems section
            continue
        m = _DEF.match(s) or _DEF_COLON.match(s)
        if not m:
            continue
        term = m.group("term").strip().rstrip(".")
        rest = m.group("rest").strip().rstrip(".")
        tl = term.lower()
        # The term must be a real concept word, not a proof fragment or a symbol.
        if _BAD_SUBJECT.search(term) or _STOP_TERM.match(term):
            continue
        if len(term) < 3 or len(term.split()) > 6 or re.search(r"\d", term):
            continue
        if not re.search(r"[aeiou]", tl) or tl in ("it", "this", "that", "there", "they"):
            continue
        if len(rest) < 10:
            continue
        # Skip when the "definition" is really a formula (e.g. "Ohm's Law: V = I·R").
        if _REAL_OP.search(rest) and not re.search(r"[A-Za-z]{4,}", rest):
            continue
        out.append((term, rest))
    return out


def theorem_lines(text: str) -> list:
    return [s for s in _sentences(text)
            if _THEOREM.search(s) and not _BAD_SUBJECT.search(s)]


def build_crib_sheet(indexed_slides: list) -> str:
    """One faithful study sheet from the whole deck: formulas, definitions, laws.

    `indexed_slides` is [(slide_number, slide_text), ...]. Everything is pulled
    verbatim from the slides and deduped — nothing is invented.
    """
    formulas, defs, thms = [], [], []
    seen_f, seen_d, seen_t = set(), set(), set()
    for num, text in indexed_slides:
        for f in formula_lines(text):
            k = re.sub(r"\s+", "", f.lower())
            if k and k not in seen_f:
                seen_f.add(k)
                formulas.append((f, num))
        for term, meaning in definition_pairs(text):
            k = term.lower()
            if k not in seen_d:
                seen_d.add(k)
                defs.append((term, meaning, num))
        for t in theorem_lines(text):
            k = re.sub(r"\s+", "", t.lower())[:90]
            if k not in seen_t:
                seen_t.add(k)
                thms.append((t, num))

    parts = ["# Exam Crib Sheet", "", "Pulled straight from your slides — nothing invented."]
    if formulas:
        parts.append("\n## Formulas")
        parts += [f"- {f}  (slide {n})" for f, n in formulas]
    if defs:
        parts.append("\n## Key definitions")
        parts += [f"- **{term}** — {meaning}  (slide {n})" for term, meaning, n in defs]
    if thms:
        parts.append("\n## Theorems, laws & rules")
        parts += [f"- {t}  (slide {n})" for t, n in thms]
    if not (formulas or defs or thms):
        parts.append("\nNo formulas, definitions, or theorems were found to summarise.")
    return "\n".join(parts)


def recall_questions(slide_text: str) -> list:
    out, seen = [], set()
    for s in _sentences(slide_text):
        # Theorems and lists first, so "X are A, B, C" / "Theorem: …" aren't
        # mislabeled as a plain definition.
        for builder in (_theorem_q, _enumeration_q, _definition_q):
            q = builder(s)
            if not q:
                continue
            key = q["q"].lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(q)
            break
    return out


# ----------------------------------------------------------------------
# Embeddings: salience ranking, uniqueness, grading
# ----------------------------------------------------------------------
def _cos(a, b) -> float:
    import numpy as np
    va, vb = np.asarray(a, dtype="float32"), np.asarray(b, dtype="float32")
    na, nb = np.linalg.norm(va), np.linalg.norm(vb)
    if na == 0 or nb == 0:
        return 0.0
    return float(va.dot(vb) / (na * nb))


async def _embed(texts):
    try:
        return await local_llm.embed(texts)
    except Exception:
        return None


def _token_overlap(a: str, b: str) -> float:
    ta = {t for t in _WORD.findall(a.lower()) if len(t) > 2}
    tb = {t for t in _WORD.findall(b.lower()) if len(t) > 2}
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


async def generate(slide_text: str, max_n: int = MAX_QUESTIONS) -> list:
    """All deterministic questions for a slide: calc first, then unique recall."""
    slide = (slide_text or "").strip()[:_MAX_SLIDE_CHARS]
    if not slide:
        return []

    calc = calc_questions(slide, want=max(3, max_n // 2))
    recall = recall_questions(slide)
    if not calc and not recall:
        return []

    remaining = max_n - len(calc)
    chosen = []
    if recall and remaining > 0:
        vecs = await _embed([slide] + [r["q"] + " " + r["a"] for r in recall])
        if vecs and len(vecs) == len(recall) + 1:
            centroid, qvecs = vecs[0], vecs[1:]
            order = sorted(range(len(recall)), key=lambda i: -_cos(centroid, qvecs[i]))
            picked = []
            for i in order:
                if all(_cos(qvecs[i], pv) < 0.88 for pv in picked):
                    chosen.append(recall[i])
                    picked.append(qvecs[i])
                if len(chosen) >= remaining:
                    break
        else:  # embeddings unavailable — token-overlap dedupe
            for r in recall:
                if all(_token_overlap(r["q"], c["q"]) < 0.6 for c in chosen):
                    chosen.append(r)
                if len(chosen) >= remaining:
                    break

    return (calc + chosen)[:max_n]


_GIVEUP = re.compile(
    r"\b(i (do ?n'?t|don'?t) know|no idea|not sure|idk|skip|give up|tell me|"
    r"reveal|show( me)? the answer|pass)\b", re.I)


def is_giveup(answer: str) -> bool:
    return bool(_GIVEUP.search((answer or "").strip()))


async def grade(student_answer: str, question: dict) -> bool:
    """True if the student's answer is right. Numeric for calc, embeddings for text."""
    student = (student_answer or "").strip()
    if not student or is_giveup(student):
        return False
    gold = question.get("a", "")

    if question.get("kind") == "numeric":
        golds = _NUMBER.findall(_mathify(gold))
        if not golds:
            return False
        target = float(golds[0])
        for ns in _NUMBER.findall(_mathify(student)):
            try:
                if abs(float(ns) - target) <= max(abs(target) * 0.02, 0.01):
                    return True
            except ValueError:
                pass
        return False

    # Text answer: meaning match via embeddings, with a token-overlap floor.
    if _token_overlap(student, gold) >= 0.6:
        return True
    vecs = await _embed([student, gold])
    if vecs and len(vecs) == 2:
        return _cos(vecs[0], vecs[1]) >= 0.72
    return _token_overlap(student, gold) >= 0.45
