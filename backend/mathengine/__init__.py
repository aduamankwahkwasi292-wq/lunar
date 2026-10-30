"""CUSTOM-Mx — MrSOLIS's maths engine. Code does every calculation; the brain only explains the working.

    r = solve(text)                  # equations, calculus, statistics, sums: nothing to misread, answered at once
    d = command.draft(text)          # a word problem → a /CUSTOM-Mx command the student checks, then runs
    md = working_markdown(r)

Word problems are never answered unreviewed. Measured on 2,680 OpenStax textbook problems with answer keys, the
rules' own reading of the words was right only about half the times they answered, and a trained checker still let
about 1 in 8 wrong answers through. So a word problem becomes a draft in CUSTOM-Mx's precise language
(command.py): code copies every number, the rules (or the brain, picking from fixed lists) say what each one is,
and the student checks that before anything is worked.

Formulas: library.py (hand-written, checked) and library_books.py (OpenStax Key Equations, CC BY 4.0,
"Access for free at openstax.org"). Self-tests: python -m backend.mathengine.selftest,
python -m backend.mathengine.command_test
"""

NAME = "CUSTOM-Mx"


def _has_units(text):
    from .engine import clean, givens
    try:
        return any(it.unit is not None for it in givens(clean(text)))
    except Exception:
        return False


def solve(text: str):
    """A worked answer {answer, value, steps, kind, …} for maths with no words to misread — or None (word problems
    included: they get a draft to check instead). Never raises."""
    from . import algebra
    text = (text or "").strip()
    if not text or len(text) > 1500 or _has_units(text):
        return None
    try:
        return algebra.solve_math(text)
    except Exception:
        return None


def reading_request(text: str, slide_text: str = ""):
    """The brain's labelling request for a word problem the rules couldn't read, or None."""
    from . import reader
    try:
        return reader.request(text, ())
    except Exception:
        return None


def read_labels(req, reply: str):
    from . import reader
    try:
        return reader.read(req, reply)
    except Exception:
        return None


_ASK = None


def question_text(slide_text: str) -> str:
    """Slide text the way the question was written: PDF line wraps rejoined ('If the full-' + 'load speed'),
    bullets as separate parts ('; …'), slide numbers dropped, and the printed solution cut off — its numbers are
    working, not data."""
    import re
    text = ""
    for line in (slide_text or "").splitlines():
        s = re.sub(r"[ \t]+", " ", line).strip()
        if re.match(r"(?i)(solution|soln|answer|working)s?\b", s):
            break
        if not s or re.fullmatch(r"\d{1,3}", s):
            text += "\n" if s == "" else ""
            continue
        if s[0] in "▪•●◦*":
            text += "\n; " + s.lstrip("▪•●◦* ").strip()
        elif text.endswith("-") and not text.endswith(" -"):
            text += s                                  # "full-" + "load" → "full-load"
        elif text and not text.endswith("\n") and not re.search(r"[.?!:]$", text):
            text += " " + s
        else:
            text += ("\n" if text else "") + s
    return text.strip()


def slide_questions(slide_text: str, limit: int = 2) -> list:
    """Questions printed on a slide ('Calculate the current…') as CUSTOM-Mx drafts the student can run exactly →
    [(question, draft)]. Rules only: this runs while a lesson is being prepared, so it has to be instant."""
    import re
    from . import command
    global _ASK
    if _ASK is None:
        from .engine import _CUE
        _ASK = _CUE
    text = question_text(slide_text)
    out = []
    # The whole question first ("Example 2: … calculate: ▪ … ▪ …"), with its parts.
    whole = re.sub(r"\s*\n\s*", " ", text).strip()
    if _ASK.search(whole) and len(re.findall(r"\d", whole)) >= 2 and len(whole) < 900:
        d = _draft(command, whole)
        if d:
            return [(whole, d)]
    # else a question is a sentence with a cue ("calculate", "find") — plus the sentences before it, which hold its data
    sents = [s.strip() for s in re.split(r"(?<=[.?!])\s+|\n+", text) if s.strip()]
    for i, s in enumerate(sents):
        if not _ASK.search(s) or len(out) >= limit:
            continue
        for back in (0, 1, 2):
            q = " ".join(sents[max(0, i - back):i + 1])
            if len(re.findall(r"\d", q)) < 2 or len(q) > 400:
                continue
            d = _draft(command, q)
            if d:
                out.append((q, d))
                break
    return out


def _draft(command, q):
    """A draft that runs (the student still checks it); None for one CUSTOM-Mx would refuse as it stands."""
    try:
        d = command.draft(q)
    except Exception:
        return None
    return d if d and d.get("runs") else None


def working_markdown(r) -> str:
    """The worked solution as Markdown for the chat bubble / Solver."""
    lines = [f"**Worked by {NAME}**"] + r["steps"]
    if r.get("source") == "OpenStax":
        lines.append("*Formula from OpenStax (openstax.org, CC BY 4.0).*")
    return "\n".join(lines)
