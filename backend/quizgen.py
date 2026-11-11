"""
Quizzes written and marked by the brain (backend/brain.py), grounded in the student's slides.

The rule-built quizzes (questions.py) were "really bad" (the user, 2026-10-20), who asked that the
model write the questions, check answers against the slides, and never repeat a question. So:
- plan(): which slides to ask about — spread across the deck, least-quizzed slides first.
- write(): one question per call, as strict JSON (llama-server turns the schema into a grammar),
  told what was already asked about that slide; near-duplicates are rejected here and retried.
  Each question is nudged towards a different style (meaning, reason, calculation, ...).
- A calculation's answer is recomputed from the brain's own arithmetic (`calc`), so a slip in
  its mental arithmetic never becomes the "correct" answer; other questions are checked against
  the slide by a second pass (`_CHECKER` caught 4/4 planted bad questions) before being asked.
- Each written answer comes with its 1–3 key points. mark() asks the brain one yes/no per point
  ("does the answer express it?"); the verdict and the comment are then built here ("You left
  out: …"), so the brain can't praise what the student never wrote — asked for a verdict and a
  comment directly, it did. Numbers, "I don't
  know" and answers that repeat the key words are marked without the brain.
Writing a question takes ~10 s on a laptop CPU, so main.py writes them in the background while
the student answers. Without a brain, main.py falls back to questions.py.
"""

import ast
import json
import math
import operator
import re

from backend import brain, questions

def _question_schema(can_calc: bool) -> dict:
    """The shape of a written question. On a slide with no formula a calculation isn't even allowed
    (the brain kept inventing mole counts for photosynthesis); lengths are capped so it can't ramble."""
    props = {
        "question": {"type": "string", "maxLength": 300},
        "answer": {"type": "string", "maxLength": 300},
        "points": {"type": "array", "items": {"type": "string", "maxLength": 60}, "minItems": 1, "maxItems": 3},
    }
    if can_calc:
        props["kind"] = {"type": "string", "enum": ["text", "numeric"]}
        props["calc"] = {"type": "string", "maxLength": 80}
    return {"type": "object", "properties": props, "required": list(props)}


# The writer and the checker share one system prompt and put the slide first, so llama-server can
# reuse the slide it already read (its prompt cache keeps the longest common prefix): checking a
# question then costs the length of the question, not of the slide again.
_QUIZ_SYSTEM = "You make and check quiz questions from a student's lecture slide."
_WRITER = (
    "Write one quiz question for the student from this slide. Test understanding of the "
    "slide's main content: a definition, a law, a reason, a comparison, or a calculation with the "
    "slide's own formula and new numbers. The answer must come from the slide, with nothing from "
    "outside it. Ask only about the subject itself, never about who teaches it, the institution, the "
    "course, dates or the slide. The question must make sense on its own; no multiple choice.\n"
    "answer: the correct answer in at most two sentences (for a calculation, the value with units). "
    "points: the 1 to 3 key facts your answer states, each in a few words."
)
_WRITER_CALC = (" kind: \"numeric\" for a calculation, else \"text\". calc: for a calculation, the arithmetic "
                "that gives the answer, written with numbers only; otherwise an empty string.")
_WRITER_NO_CALC = " This slide has no formula, so don't ask for a calculation."
# (No example arithmetic above: given "e.g. 24/(4+2)" it asked "Using the formula 24 ÷ (4+2), calculate the value.")
_CHECKER = (
    "Check this quiz question, written from the slide above. reason: in one short sentence, "
    "whether the slide supports the question's premise and its answer. ok: true only if the slide "
    "clearly supports both and the answer is correct; false if the question mixes up ideas, asks "
    "about something not on the slide or about the lecturer, institution or course rather than the "
    "subject, or the answer is wrong or incomplete."
)
_CHECK = {"type": "object", "properties": {"reason": {"type": "string"}, "ok": {"type": "boolean"}},
          "required": ["reason", "ok"]}
# Marking, tested on 8 answers with known verdicts: all points in one call scored 2/8 (booleans)
# and 4/8 (quote + verdict — it quoted the key point, not the student); one yes/no per point, 8/8.
_MARKER = ("Does the student's answer express the key point, in any words? Everyday words and synonyms "
           "count; a contradiction does not. Reply yes or no.")
_YES_NO = {"type": "object", "properties": {"answer": {"type": "string", "enum": ["yes", "no"]}},
           "required": ["answer"]}
# "…as described on the slide", "According to the slide, …": the brain adds these despite being told not to.
_SLIDE_REF = re.compile(r"(?i)(\s*\b(according to|based on)\s+(the|this)\s+slide\s*,?"
                        r"|\s+(as\s+)?(described|stated|shown|defined|given|provided|mentioned|listed)?\s*(on|in|from)\s+"
                        r"(the|this)\s+slide\b)")
# A different kind of question each time keeps a quiz varied (and away from repeats).
_STYLES = ["what something means", "why something happens or matters", "calculation with new numbers",
           "comparison of two ideas", "applying an idea to a short example", "fact to recall"]


# Words that don't change what a question asks ("State Ohm's law" = "What is Ohm's law?").
_FILLER = {"the", "a", "an", "of", "is", "are", "what", "in", "to", "and", "which", "does", "do", "how", "s",
           "state", "define", "explain", "describe", "give", "name", "write", "list", "briefly", "main",
           "for", "by", "on", "this", "that", "it", "be", "can", "you", "your", "according", "slide",
           "calculate", "find", "determine", "work", "out", "when", "if", "given", "use", "using"}


def _words(text: str) -> set:
    words = {w[:-1] if len(w) > 3 and w.endswith("s") else w for w in re.findall(r"[a-z0-9]+", (text or "").lower())}
    return words - _FILLER


def _alike(a: str, b: str) -> bool:
    """Two questions that ask the same thing ("What is Ohm's law?" / "State Ohm's law")."""
    wa, wb = _words(a), _words(b)
    return bool(wa and wb) and len(wa & wb) / max(len(wa), len(wb)) >= 0.7


def plan(slides: list, asked: list, count: int) -> list:
    """Which slides to ask about: `slides` is [(index, text)] of slides worth quizzing, `asked` the
    deck's past questions. Least-quizzed slides first, spread evenly across the deck; a slide comes
    up twice only when the deck has fewer usable slides than questions, and then in a later round,
    not straight after itself (a second question on the same slide is the hardest to write)."""
    usable = [i for i, _ in slides]
    if not usable:
        return []
    times = {i: 0 for i in usable}
    for a in asked:
        if a.get("slide") in times:
            times[a["slide"]] += 1
    chosen = []
    while len(chosen) < count:
        level = min(times.values())
        group = [i for i in usable if times[i] == level]
        need = count - len(chosen)
        if len(group) > need:                          # evenly spaced across the deck
            group = sorted({group[round(k * (len(group) - 1) / max(1, need - 1))] for k in range(need)})
        for i in group:
            chosen.append(i)
            times[i] += 1
    return chosen                                          # round by round, each in deck order


# ── arithmetic the brain wrote (numbers only), evaluated safely ───────────
_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.Pow: operator.pow, ast.USub: operator.neg, ast.UAdd: operator.pos}
_FUNCS = {"sqrt": math.sqrt, "sin": lambda x: math.sin(math.radians(x)), "cos": lambda x: math.cos(math.radians(x)),
          "tan": lambda x: math.tan(math.radians(x)), "log": math.log10, "ln": math.log, "exp": math.exp}


def _eval(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        left, right = _eval(node.left), _eval(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > 50:
            raise ValueError("too big")
        return _OPS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval(node.operand))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNCS and len(node.args) == 1:
        return _FUNCS[node.func.id](_eval(node.args[0]))
    if isinstance(node, ast.Name) and node.id in ("pi", "e"):
        return math.pi if node.id == "pi" else math.e
    raise ValueError("not arithmetic")


def _calc(expr: str):
    expr = (expr or "").replace("×", "*").replace("÷", "/").replace("^", "**").replace("√", "sqrt").strip()
    if not expr or len(expr) > 120 or not re.fullmatch(r"[\d\s.+\-*/()a-z,]*", expr):
        return None
    try:
        value = _eval(ast.parse(expr, mode="eval").body)
    except Exception:
        return None
    return value if math.isfinite(value) else None


def _fix_numeric(q: dict, slide: str) -> dict | None:
    """Recompute a calculation's answer from its arithmetic and show the working; None if the
    arithmetic is missing or uses numbers that are neither in the question nor on the slide
    (the brain once answered "72 V" for 6 Ω × 2 A with no working, and invented molar masses)."""
    calc = q.get("calc", "")
    numbers = questions._NUMBER.findall(calc)
    if len(numbers) < 2 or not re.search(r"[-+*/^×÷]", calc.lstrip("-")):
        return None
    given = questions._NUMBER.findall(questions._mathify(q["q"] + " " + slide))
    if any(n not in given for n in numbers):
        return None
    value = _calc(calc)
    if value is None:
        return None
    shown = questions._format_num(value)
    nums = questions._NUMBER.findall(questions._mathify(q["a"]))
    if nums:
        stated = float(nums[0])
        if abs(stated - value) > max(abs(value) * 0.01, 1e-9):        # the brain's arithmetic slipped
            q["a"] = q["a"].replace(nums[0], shown, 1)
    else:
        q["a"] = f"{shown} {q['a']}".strip()
    q["work"] = f"{q['calc'].strip()} = {shown}"
    return q


# ── units: right arithmetic with the wrong units is a wrong question ──────
# Speedy wrote "A battery supplies 40 A through a load in 3 s. What current…?" with 40/3 = 13.33 A (it meant 40 C) and
# marked the student's literal "40 A" wrong; and "A 12 V battery drives 4 Ω of current" (2026-11-06, phone test).
# The arithmetic was right both times, so _fix_numeric can't see it. Each unit is its powers of the SI base units
# (kg, m, s, A, K); the working must give the answer's unit, and a value can't be called another quantity. Both
# checks judge only what they can read: a number whose unit they don't know (4200 from "J/kg°C") leaves it alone.
_UNIT = (r"(?:volts?|amps?|amperes?|watts?|joules?|coulombs?|newtons?|hertz|kilograms?|grams?|metres?|meters?"
         r"|m/s²|m/s\^?2|m/s|km/h|kWh|Wh|[kM]?Ω|k?ohms?|[kMmµu]?A|[kMm]?V|[kMm]?W|[kM]?J|[mµun]?C|[kM]?Hz|k?N|k?Pa"
         r"|kg|g|km|cm|mm|ms|minutes?|mins?|hours?|hrs?|h|seconds?|s|m)")
_UNIT_WORDS = {"volt": "V", "amp": "A", "ampere": "A", "watt": "W", "joule": "J", "coulomb": "C", "newton": "N",
               "hertz": "Hz", "kilogram": "kg", "gram": "kg", "metre": "m", "meter": "m"}
_QUANTITY = re.compile(r"(\d+(?:\.\d+)?)\s*(" + _UNIT + r")(?![\w/²^])")
_DIMS = {"A": (0, 0, 0, 1, 0), "C": (0, 0, 1, 1, 0), "V": (1, 2, -3, -1, 0), "Ω": (1, 2, -3, -2, 0),
         "W": (1, 2, -3, 0, 0), "J": (1, 2, -2, 0, 0), "Hz": (0, 0, -1, 0, 0), "N": (1, 1, -2, 0, 0),
         "Pa": (1, -1, -2, 0, 0), "kg": (1, 0, 0, 0, 0), "m": (0, 1, 0, 0, 0), "s": (0, 0, 1, 0, 0),
         "m/s": (0, 1, -1, 0, 0), "m/s²": (0, 1, -2, 0, 0)}
_PLAIN = (0, 0, 0, 0, 0)
# "4 Ω of current", "a 40 A charge": a value named as a quantity its unit isn't (only words with one meaning here:
# "3 h of work" is labour, not energy)
_NAMED = re.compile(r"(\d+(?:\.\d+)?)\s*(" + _UNIT + r")\s+(?:of\s+)?(?i:(current|charge|voltage|potential difference|"
                    r"emf|resistance|power|energy|frequency|force|pressure|mass|speed|velocity|acceleration))\b")
_NAMED_UNIT = {"current": "A", "charge": "C", "voltage": "V", "potential difference": "V", "emf": "V",
               "resistance": "Ω", "power": "W", "energy": "J", "frequency": "Hz", "force": "N", "pressure": "Pa",
               "mass": "kg", "speed": "m/s", "velocity": "m/s", "acceleration": "m/s²"}


def _base_unit(token: str):
    word = token[:-1] if token.endswith("s") and token[:-1] in _UNIT_WORDS else token
    if word in _UNIT_WORDS:
        return _UNIT_WORDS[word]
    t = token.replace("ohms", "Ω").replace("ohm", "Ω")
    if t in ("m/s²", "m/s^2", "m/s2"):
        return "m/s²"
    if t in ("m/s", "km/h"):
        return "m/s"
    if t in ("kWh", "Wh"):
        return "J"
    if t in ("kg", "g"):
        return "kg"
    if t in ("km", "cm", "mm", "m"):
        return "m"
    if t in ("ms", "s", "second", "seconds", "min", "mins", "minute", "minutes", "h", "hr", "hrs", "hour", "hours"):
        return "s"
    if t.endswith("Hz") or t.endswith("Pa"):
        return t[-2:]
    return t[-1] if t[-1] in "AVWJCNΩ" else None


class _CantTell(Exception):
    """A number with no unit the check knows: it says nothing."""


class _Mismatch(Exception):
    """Units that don't add up."""


def _dims(node, units: dict):
    """The SI powers of what this arithmetic works out, from the units written beside its numbers."""
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        found = units.get(round(float(node.value), 9))
        if found:
            if len(found) > 1:                             # "12 V … 12 Ω": which 12?
                raise _CantTell
            return next(iter(found))
        if node.value in (1, 2):                           # 1/R, x², ½: no unit of their own
            return _PLAIN
        raise _CantTell
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        return _dims(node.operand, units)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow):
        power = _eval(node.right)                          # a plain number
        return tuple(round(d * power, 6) for d in _dims(node.left, units))
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
        a, b = _dims(node.left, units), _dims(node.right, units)
        if isinstance(node.op, (ast.Add, ast.Sub)):
            if a != b:
                raise _Mismatch                            # ohms plus volts
            return a
        sign = 1 if isinstance(node.op, ast.Mult) else -1
        return tuple(round(x + sign * y, 6) for x, y in zip(a, b))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and len(node.args) == 1:
        inner = _dims(node.args[0], units)
        if node.func.id == "sqrt":
            return tuple(round(d / 2, 6) for d in inner)
        if inner != _PLAIN:                                # sin(4 Ω)
            raise _Mismatch
        return _PLAIN
    if isinstance(node, ast.Name) and node.id in ("pi", "e"):
        return _PLAIN
    raise _CantTell


def _units_agree(q: dict) -> bool:
    """False when a question's units show it's wrong: a value named as another quantity, or working whose units
    don't give the answer's unit. True when they agree, and whenever the check can't tell."""
    for m in _NAMED.finditer(q.get("q", "")):
        if _base_unit(m.group(2)) != _NAMED_UNIT[m.group(3).lower()]:
            return False
    if q.get("kind") != "numeric" or not q.get("calc"):
        return True
    answer = _QUANTITY.search(q.get("a", ""))
    want = answer and _base_unit(answer.group(2))
    if not want:
        return True
    units = {}
    for m in _QUANTITY.finditer(q.get("q", "")):
        base = _base_unit(m.group(2))
        if base:
            units.setdefault(round(float(m.group(1)), 9), set()).add(_DIMS[base])
    expr = q["calc"].replace("×", "*").replace("÷", "/").replace("^", "**").replace("√", "sqrt")
    try:
        got = _dims(ast.parse(expr, mode="eval").body, units)
    except _Mismatch:
        return False
    except Exception:                                      # _CantTell, or arithmetic it can't read
        return True
    return got == _DIMS[want]


def _slide_block(slide: str) -> str:
    return f'Slide:\n"""\n{slide}\n"""\n\n'


async def _supported(slide: str, q: str, a: str) -> bool:
    """The second pass: does the slide really support this question and its answer?"""
    user = _slide_block(slide) + f"{_CHECKER}\nQuestion: {q}\nAnswer: {a}"
    try:
        raw = await brain.chat([{"role": "system", "content": _QUIZ_SYSTEM}, {"role": "user", "content": user}],
                               temperature=0.1, max_tokens=120, schema=_CHECK)
        return bool(json.loads(raw).get("ok"))
    except Exception:
        return True                                        # can't check: don't lose the question


# "Which of the following…" with no options to choose from: the brain wrote one.
_CHOICE_Q = re.compile(r"(?i)\b(which|what) of the following\b|\b(choose|select) (one|the correct)\b")
# Questions about slide admin, not the subject ("What is the name of the institution?" — the user saw one).
_ADMIN_Q = re.compile(
    r"(?i)\b(lecturer|instructor|professor|presenter|course (code|title)|credit hours?|academic year|semester|"
    r"slide (number|title)|page number)\b"
    r"|\bauthor of (the|this|these) (slides?|lecture|notes|deck|presentation)\b"
    r"|\bwho (prepared|presented|wrote|teaches|taught|created|made|designed|delivered) (the|this|these)\b"
    r"|\b(which|what) (university|institution|college)\b"      # ("which department handles recruitment?" is fine)
    r"|\bname of (the|this) (university|institution|college|school|department|faculty|course|lecturer|programme|program)\b")


async def write(slide_text: str, avoid: list, style_no: int, avoid_answers: list = ()) -> dict | None:
    """One new, checked question about this slide that isn't like any in `avoid` (questions) and
    doesn't test a fact already tested (`avoid_answers`: "price rises, quantity falls" twice), or None."""
    slide = (slide_text or "").strip()[:2400]
    can_calc = bool(re.search(r"[A-Za-z]\s*=\s*[-A-Za-z0-9(√]", slide))      # the slide has a formula
    styles = [s for s in _STYLES if can_calc or "calculation" not in s]
    for attempt in range(2):                               # a third try rarely helped and cost ~20 s
        style = styles[(style_no + attempt) % len(styles)]
        user = _slide_block(slide) + _WRITER + (_WRITER_CALC if can_calc else _WRITER_NO_CALC) + "\n"
        if avoid:
            user += "\nAlready asked about this slide (ask something different):\n" + \
                    "\n".join(f"- {q}" for q in avoid[-8:]) + "\n"
        user += f"\nIf the slide allows, ask about {style}."
        raw = await brain.chat([{"role": "system", "content": _QUIZ_SYSTEM}, {"role": "user", "content": user}],
                               temperature=0.8, max_tokens=300, schema=_question_schema(can_calc))
        try:
            data = json.loads(raw)
        except Exception:
            continue
        q, a = str(data.get("question", "")).strip(), str(data.get("answer", "")).strip()
        q = _SLIDE_REF.sub("", q).strip()
        q = q[:1].upper() + q[1:]
        numeric = data.get("kind") == "numeric"
        if len(q) < 8 or not a or _CHOICE_Q.search(q) or _ADMIN_Q.search(q) or any(_alike(q, old) for old in avoid) \
                or (not numeric and any(_alike(a, old) for old in avoid_answers if old)):
            continue                                       # (two sums can share an answer like "2 A")
        points = [str(p).strip() for p in (data.get("points") or []) if str(p).strip()][:3] or [a]
        if len(a.split()) <= 8:          # a short answer is its own key point (its "points" wandered off:
            points = [a]                 # "Where is O2 made?" — 3 points, one about the Calvin cycle)
        out = {"q": q, "a": a, "points": points, "kind": "numeric" if data.get("kind") == "numeric" else "text",
               "calc": str(data.get("calc", "")), "work": ""}
        if out["kind"] == "numeric":
            if not can_calc or not _fix_numeric(out, slide):   # arithmetic we can't check: another kind
                styles = [s for s in styles if "calculation" not in s] or styles
                continue
        if not _units_agree(out):                          # "40 A … in 3 s" for 40 C; "4 Ω of current"
            continue
        # right arithmetic can still be the wrong formula ("(6+4+2)*12/3 = 48 V"): check those too
        shown = out["a"] + (f" (working: {out['work']})" if out["work"] else "")
        if await _supported(slide, q, shown):
            return out
    return None


_NOT = re.compile(r"(?i)\b(not|no|never|isn'?t|aren'?t|doesn'?t|don'?t|cannot|can'?t|inversely)\b")


def _joined(items: list) -> str:
    items = [i.rstrip(". ") for i in items]
    items = [i[:1].lower() + i[1:] if i[1:2].islower() else i for i in items]
    return "; ".join(items)                                # points can hold commas of their own


async def mark(slide_text: str, question: dict, given: str) -> dict:
    """{"verdict": "correct" | "partly" | "wrong", "feedback": "..."} for the student's answer."""
    given = (given or "").strip()
    if not given or questions.is_giveup(given):
        return {"verdict": "wrong", "feedback": ""}
    if question.get("kind") == "numeric":                  # numbers: checked exactly, never by the brain
        gold = questions._NUMBER.findall(questions._mathify(question.get("a", "")))
        mine = questions._NUMBER.findall(questions._mathify(given))
        if gold and mine and abs(float(mine[-1]) - float(gold[0])) <= max(abs(float(gold[0])) * 0.02, 0.01):
            return {"verdict": "correct", "feedback": "Right."}
        return {"verdict": "wrong", "feedback": "That isn't the right value; compare your working with the steps below."
                if mine else "Give the value as a number, with its units."}
    # Has every key word of the correct answer, with no "not": right, whatever the brain might say.
    gold_words = _words(question.get("a", ""))
    if gold_words and not _NOT.search(given) and len(gold_words & _words(given)) / len(gold_words) >= 0.85:
        return {"verdict": "correct", "feedback": "Right."}
    points = question.get("points") or [question.get("a", "")]
    found = []
    try:
        for p in points:                                   # one small yes/no per point: 8/8 in testing
            user = f'Question: {question["q"]}\nStudent\'s answer: "{given[:500]}"\nKey point: {p}'
            raw = await brain.chat([{"role": "system", "content": _MARKER}, {"role": "user", "content": user}],
                                   temperature=0.1, max_tokens=20, schema=_YES_NO)
            found.append(json.loads(raw).get("answer") == "yes")
    except Exception:
        return {"verdict": "correct" if await questions.grade(given, question) else "wrong", "feedback": ""}
    missed = [p for p, f in zip(points, found) if not f]
    if not missed:
        return {"verdict": "correct", "feedback": "Right."}
    if len(missed) < len(points):
        return {"verdict": "partly", "feedback": f"Good start, but you left out: {_joined(missed)}."}
    return {"verdict": "wrong", "feedback": ""}            # the correct answer is shown right under it
