"""Interactive mode: MrSOLIS teaches the slides at a blackboard, out loud, and answers when the student raises
a hand (frontend: static/mrsolis-class.js writes and speaks it; static/mrsolis-board.js is the board).

What is written is NORMAL MODE'S OWN LESSON (the user, 2026-11-11: "make it write as though it was on the board,
the normal mode"). The class asks for exactly the lesson a student reads under the slide
(classroom.teach_slide_stream: same prompt, same length setting, same brain), cuts it into sentences as it
arrives, and each sentence becomes a step: written on the board by hand while it is said. Answers to the
student are normal chat answers (classroom.chat_stream), cut the same way.

An earlier design had the brain fill a rigid "BOARD: / SAY:" format point by point under a grammar: a small
brain writes worse under such rules than in its own prose, and the board showed nonsense ("A = 3 A", fake
"Answer:" lines). Prose it writes well; code only cuts it up.

Maths goes through CUSTOM-Mx, never the brain's arithmetic (the user, 11-11: "ROUTE MATH THROUGH CUSTOM-Mx"):
  - a conversion ("how many joules is 2 kWh") or maths with nothing to misread ("12 divided by 4",
    "solve 2x + 3 = 15") is worked exactly, and its working is written and said step by step;
  - a word problem is SET UP by CUSTOM-Mx and shown for the student to check and run (Run it), as in normal
    mode: its reading of words is right only about half the time, so it is never worked unchecked;
  - the slide's own questions are offered the same way after the lesson (normal mode's "exact" drafts).
Steps: {"board": [lines], "say": "spoken", "kind": "lesson"|"maths"|"offer"|"answer", "gap": new paragraph,
"fin": last sentence of the lesson, "offer": {"command"}, "end": the slide's closing line}.
"""
import re

from backend import classroom

# ── the lesson, a sentence at a time ────────────────────────────────────────────────────────────────────────
_END = re.compile(r"([.!?][\"'”’)\]*]*)(\s+)(?=[\"'“(*]*[A-Z0-9√(])")
# "1." of a numbered step, "e.g.", "Fig." are not the end of a sentence (a lone letter is: "V = I × R.", "3 A.")
_NOT_END = re.compile(r"(?i)(?:^|\s)(\d{1,2}[.)]|e\.g\.|i\.e\.|etc\.|vs\.|fig\.|eq\.|no\.|approx\.)$")


def _cut(buf: str):
    """(sentence, paragraph break after it, rest) for the first complete sentence in buf, or None."""
    nl = buf.find("\n")
    pos = 0
    while True:
        m = _END.search(buf, pos)
        if m and (nl < 0 or m.end(1) <= nl):
            head = buf[:m.end(1)]
            if _NOT_END.search(head):
                pos = m.end(1)
                continue
            return head, m.group(2).count("\n") >= 2, buf[m.end():]
        if nl >= 0:
            j = nl
            while j < len(buf) and buf[j] in "\n \t":
                j += 1
            if j == len(buf):
                return None                      # what follows the line break hasn't come yet
            return buf[:nl], buf[nl:j].count("\n") >= 2, buf[j:]
        return None


def board_line(md: str) -> str:
    """A sentence of the lesson as it is written on the board: **bold** stays (the board writes it in colour),
    other markdown goes."""
    s = md.strip()
    s = re.sub(r"(?<![*\w])\*(?!\*)([^*\n]+?)(?<!\*)\*(?![*\w])", r"\1", s)      # *italic*
    s = s.replace("`", "")
    s = re.sub(r"^#{1,6}\s*", "", s)
    s = re.sub(r"^[•*]\s+", "- ", s)
    return s


def speech(md: str) -> str:
    """What is said for a sentence: its words, without markdown (the voice reads the symbols, voice.speakable)."""
    s = re.sub(r"\*\*|`", "", md.strip())
    s = re.sub(r"(?<![*\w])\*(?!\*)([^*\n]+?)\*", r"\1", s)
    s = re.sub(r"^#{1,6}\s*|^[-•*]\s+", "", s)
    return s.strip()


_LATEX = {"times": "×", "cdot": "·", "div": "÷", "pm": "±", "approx": "≈", "leq": "≤", "le": "≤", "geq": "≥",
          "ge": "≥", "neq": "≠", "ne": "≠", "to": "→", "rightarrow": "→", "Rightarrow": "⇒", "infty": "∞",
          "degree": "°", "circ": "°", "propto": "∝", "Omega": "Ω", "omega": "ω", "mu": "μ", "pi": "π", "Delta": "Δ",
          "delta": "δ", "theta": "θ", "alpha": "α", "beta": "β", "gamma": "γ", "lambda": "λ", "rho": "ρ",
          "sigma": "σ", "Sigma": "Σ", "tau": "τ", "phi": "φ", "eta": "η", "epsilon": "ε", "varepsilon": "ε"}


def _wrap(x: str) -> str:
    x = x.strip()
    return x if re.fullmatch(r"[\w.]+", x) else f"({x})"


def unlatex(s: str) -> str:
    """LaTeX in a lesson ("$I = V/R$", "\\times", "12\\,\\text{V}") as the signs a teacher writes and the voice
    reads ("×" is said "times"; the voice skipped "\\times" altogether)."""
    s = re.sub(r"\$\$?|\\\(|\\\)|\\\[|\\\]", "", s or "")
    s = re.sub(r"\\(?:left|right|displaystyle|limits)\b", "", s)
    s = re.sub(r"\\[,;:! ]|\\q?quad\b", " ", s)
    for _ in range(3):                                   # innermost braces first: \sqrt{x^{2}+1}
        s = re.sub(r"\^\{([^{}]*)\}", lambda m: "^" + _wrap(m.group(1)), s)
        s = re.sub(r"_\{([^{}]*)\}", lambda m: "_" + _wrap(m.group(1)), s)
        s = re.sub(r"\\(?:text|mathrm|mathbf|textbf|mathit|operatorname)\s*\{([^{}]*)\}", r"\1", s)
        s = re.sub(r"\\[dt]?frac\s*\{([^{}]*)\}\s*\{([^{}]*)\}", lambda m: f"{_wrap(m.group(1))}/{_wrap(m.group(2))}", s)
        s = re.sub(r"\\sqrt\s*\{([^{}]*)\}", lambda m: "√" + _wrap(m.group(1)), s)
    s = re.sub(r"\\sqrt\b", "√", s)
    s = re.sub(r"\\([A-Za-z]+)", lambda m: _LATEX.get(m.group(1), m.group(1)), s)
    return re.sub(r"[ \t]+", " ", s.replace("{", "").replace("}", "")).strip()


_UNIT_AFTER = re.compile(r"(?<=\d)\s*(?:[A-Za-zΩμµ°]{1,4}(?:\s*/\s*[A-Za-z]{1,3})?)(?=[\s)+\-×*/÷^]|$)")
_SUM = re.compile(r"[\d.,\s()+\-×*/÷^]+$")
_RESULT = re.compile(r"^\s*(-?\d[\d,]*(?:\.\d+)?)")


def check_sums(text: str) -> str:
    """Every "sum = result" in a sentence recomputed by code (quizgen's safe calculator), and a wrong result
    replaced with the right one: the brain's own arithmetic never reaches the board unchecked (the user,
    2026-11-11: "ROUTE MATH THROUGH CUSTOM-Mx"). "I = V/R = 12 V ÷ 4 Ω = 3 A": 12 ÷ 4 is checked; I, V/R are not
    numbers and are left alone."""
    from backend import quizgen, questions
    if "=" not in text or not re.search(r"\d", text):
        return text
    parts = text.split("=")
    for i in range(len(parts) - 1):
        left = _UNIT_AFTER.sub("", parts[i])
        m = _SUM.search(left)
        claim = _RESULT.match(parts[i + 1])
        if not m or not claim:
            continue
        expr = m.group().replace(",", "").strip()
        if len(re.findall(r"\d+(?:\.\d+)?", expr)) < 2 or not re.search(r"[-+×*/÷^]", expr.lstrip("-(")):
            continue
        value = quizgen._calc(expr)
        if value is None:
            continue
        said = float(claim.group(1).replace(",", ""))
        places = len(claim.group(1).split(".")[1]) if "." in claim.group(1) else 0
        if round(value, places) == round(said, places) or abs(value - said) <= 0.005 * max(abs(value), 1e-9):
            continue
        right = questions._format_num(value)
        parts[i + 1] = parts[i + 1][:claim.start(1)] + right + parts[i + 1][claim.end(1):]
    return "=".join(parts)


def _plain(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", re.sub(r"\*\*|[’']", "", s.lower())).strip()


def _step(md: str, kind: str, gap: bool = False, heading: str = "") -> dict | None:
    md = check_sums(unlatex(md.strip()))
    if not re.search(r"[A-Za-z0-9]", md):
        return None
    board = ([f"# {heading}"] if heading else []) + [board_line(md)]
    return {"kind": kind, "board": board, "say": speech(md), "md": md, "gap": gap}


async def sentences(pieces, kind: str, heading: str = ""):
    """Steps from a stream of text: one per sentence, sent as soon as the next one has begun (so the last can be
    marked "fin"). The first carries the slide's heading."""
    buf, gap, held = "", False, None
    title = _plain(heading)
    async for piece in pieces:
        buf += piece
        while True:
            c = _cut(buf)
            if not c:
                break
            sent, para, buf = c
            # a bold title line that only repeats the slide's heading ("**Ohm’s Law**" under "# Ohm's law")
            step = None if title and _plain(sent) == title else _step(sent, kind, gap, heading)
            gap = para
            if step:
                heading = ""
                if held:
                    yield held
                held = step
    last = _step(buf, kind, gap, heading)
    if last:
        if held:
            yield held
        held = last
    if held:
        held["fin"] = True
        yield held


async def lesson_steps(slide_text: str, slide_no: int, total: int, length: str = "standard", image=None,
                       exact=None, heading: str = "", prior: str = ""):
    """The slide's normal-mode lesson, a sentence at a time. `prior`: the part already taught (the student cut in
    while it was being prepared): the brain carries on from there."""
    stream = classroom.teach_slide_stream(slide_text, slide_no, total, length, image=image, exact=exact, prior=prior)
    async for step in sentences(stream, "lesson", "" if prior else heading):
        yield step


async def answer_steps(slide_text: str, question: str, history=None, image=None, subject=None):
    """A normal chat answer to what the student asked, a sentence at a time."""
    stream = classroom.chat_stream(slide_text, question, history, image=image, subject=subject)
    async for step in sentences(stream, "answer"):
        yield step


# ── maths: CUSTOM-Mx ────────────────────────────────────────────────────────────────────────────────────────
_ONES = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve thirteen "
                                    "fourteen fifteen sixteen seventeen eighteen nineteen".split())}
_TENS = {w: 10 * i for i, w in enumerate("_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()) if w != "_"}
_SCALES = {"hundred": 100, "thousand": 1000, "million": 10 ** 6, "billion": 10 ** 9}
_NUMWORD = "|".join(sorted([*_ONES, *_TENS, *_SCALES], key=len, reverse=True))
_RUN = re.compile(rf"(?i)\b(?:{_NUMWORD})(?:[\s-]+(?:{_NUMWORD}|point))*\b")
_OPS = [(r"\bdivided by\b", "/"), (r"\bover\b(?=\s*[\d(])", "/"), (r"\bmultiplied by\b|\btimes\b", "*"),
        (r"\bplus\b|\badd\b", "+"), (r"\bminus\b|\btake away\b", "-"), (r"\bsquared\b", "^2"), (r"\bcubed\b", "^3"),
        (r"\bto the power of\b|\braised to\b", "^"), (r"\bsquare root of\b", "√"), (r"\bis equal to\b|\bequals\b", "=")]


def _number(words: list) -> str:
    total, cur, dec = 0, 0, None
    for w in words:
        if w == "point":
            dec = ""
        elif dec is not None:
            if w in _ONES and _ONES[w] < 10:
                dec += str(_ONES[w])
        elif w in _ONES:
            cur += _ONES[w]
        elif w in _TENS:
            cur += _TENS[w]
        elif w == "hundred":
            cur = max(cur, 1) * 100
        elif w in _SCALES:
            total += max(cur, 1) * _SCALES[w]
            cur = 0
    n = total + cur
    return f"{n}.{dec}" if dec else str(n)


def spoken_maths(text: str) -> str:
    """Maths as it is said ("twelve divided by four", "two kilowatt hours") in symbols: "12 / 4", "2 kilowatt
    hours". Only for trying CUSTOM-Mx: what the student said is kept as it was for everything else."""
    s = _RUN.sub(lambda m: _number([w.lower() for w in re.split(r"[\s-]+", m.group()) if w]), text or "")
    for pattern, sign in _OPS:
        s = re.sub(pattern, sign, s, flags=re.I)
    return re.sub(r"\s+", " ", s).strip()


_CONVERT = [
    re.compile(r"(?i)\b(?:convert|change|express)\s+(?P<n>-?\d[\d.,]*)\s*(?P<a>[^\d?=]+?)\s+(?:to|into|in)\s+"
               r"(?P<b>[^\d?=]+?)\s*[?.!]*$"),
    re.compile(r"(?i)\bhow many\s+(?P<b>[^\d?=]+?)\s+(?:are\s+)?(?:there\s+)?(?:is|are|in|make|makes|equals?|=)\s+"
               r"(?P<n>-?\d[\d.,]*)\s*(?P<a>[^\d?=]+?)\s*[?.!]*$"),
    re.compile(r"(?i)^(?:what(?:'s| is)\s+)?(?P<n>-?\d[\d.,]*)\s*(?P<a>[^\d?=/*+^]+?)\s+(?:in|into|to)\s+"
               r"(?P<b>[^\d?=]+?)\s*[?.!]*$"),
]


def conversion(text: str) -> str | None:
    """A unit conversion asked in words, as a CUSTOM-Mx command: "how many joules is 2 kWh" → "convert 2 kWh to
    joules". CUSTOM-Mx itself refuses units that don't match."""
    for rx in _CONVERT:
        m = rx.search(text or "")
        if m and m.group("a").strip() and m.group("b").strip():
            return f"convert {m.group('n').replace(',', '')} {m.group('a').strip()} to {m.group('b').strip()}"
    return None


_ASKING = re.compile(r"(?i)^\s*(?:please\s+|can you\s+|could you\s+)*(?:tell me\s+)?(?:what(?:'s| is| are| does)|"
                     r"how much is|calculate|compute|work out|evaluate|simplify)\s+")


def bare_maths(text: str) -> str:
    """"what is 12 / 4?" → "12 / 4": the sum without the asking."""
    return _ASKING.sub("", text or "").strip(" ?.!")


_MX_CMD = re.compile(r"(?i)^\s*(find|solve|rearrange|substitute|convert)\b")


def maths_candidates(text: str) -> list:
    """CUSTOM-Mx commands to try first, in order (each runs exactly, or is refused)."""
    out = []
    conv = conversion(text)
    if conv:
        out.append(conv)
    if _MX_CMD.match(text):
        out.append(text.strip(" ?.!"))
    return out


def working_steps(markdown: str, intro: str = "") -> list:
    """CUSTOM-Mx's working (its Markdown) as class steps: each line written and said; the answer boxed."""
    steps = []
    if intro:
        steps.append({"kind": "maths", "board": ["**CUSTOM-Mx** works it exactly:"], "say": intro})
    for ln in (markdown or "").splitlines():
        ln = ln.strip()
        if not ln or re.match(r"(?i)\*\*worked by", ln):
            continue
        if re.match(r"(?i)\*?formula from openstax", ln):
            steps.append({"kind": "maths", "board": [ln.strip("*")], "say": "", "color": "grey", "scale": 0.7})
            continue
        ln = re.sub(r"^[-•]\s+", "", ln)
        answer = re.match(r"(?i)\*\*answer:\*\*\s*(.+)", ln)
        board = f"Answer: {answer.group(1)}" if answer else ln
        if answer and steps and re.sub(r"(?i)^\*\*result:\*\*\s*", "", steps[-1]["board"][0]) == answer.group(1):
            steps.pop()                                # "Result: I = 3 A" then "Answer: I = 3 A": the boxed one stays
        steps.append({"kind": "maths", "board": [board], "say": speech(board)})
    return steps


def offer_step(d: dict, about: str = "your question") -> dict:
    """A word problem CUSTOM-Mx has set up: shown for the student to check, then Run it (normal mode's rule)."""
    return {"kind": "offer", "board": ["**CUSTOM-Mx** set it up as:", d["command"]],
            "say": (f"My maths engine has set up {about} like this. Check that every value is right, and that it "
                    "asks for the right thing. If it does, press Run it."),
            "offer": {"command": d["command"]}}


# ── slides that need no lesson, and moving on ───────────────────────────────────────────────────────────────
_SMALL = set("a an and as at but by for in of on or the to via vs with".split())


def _shouting(line: str) -> bool:
    letters = [c for c in line if c.isalpha()]
    return (len(re.findall(r"[A-Za-z]{3,}", line)) >= 2 and len(letters) >= 8
            and sum(c.isupper() for c in letters) >= 0.8 * len(letters) and "=" not in line)


def caps_kept(slide_text: str) -> set:
    """Words in capitals inside the slide's ordinary lines (acronyms: DNA, ATP), kept when a heading is calmed."""
    keep = set()
    for ln in (slide_text or "").splitlines():
        if ln.strip() and not _shouting(ln):
            keep |= set(re.findall(r"\b[A-Z][A-Z0-9]{1,}\b", ln))
    return keep


def calm(line: str, keep: set, heading: bool = False) -> str:
    """A SHOUTED title written normally (Title Case), acronyms kept (the user: no headings in all caps)."""
    if not _shouting(line):
        return line
    out = []
    for i, w in enumerate(line.split(" ")):
        core = re.sub(r"[^A-Za-z0-9]", "", w)
        if not core or core in keep or any(c.isdigit() for c in core) or len(core) <= 1:
            out.append(w)
        elif heading and (i == 0 or core.lower() not in _SMALL) or (not heading and i == 0):
            out.append(w[:1] + w[1:].lower())
        else:
            out.append(w.lower())
    return " ".join(out)


def transition(title: str, next_title, n: int) -> str:
    """What is said at the end of a slide: where the class goes next. next_title None: nothing after it;
    "": a next slide with no title."""
    here = f"That's it for {title}." if title else "That covers this slide."
    if next_title is None:
        return here
    if not next_title:
        return here + " Now let's move on to the next slide."
    t = next_title.rstrip(".:;,")
    return here + " " + ("Now let's move on to the next slide: {t}.", "Next, we'll look at {t}.",
                         "Now we move on to {t}.")[n % 3].format(t=t)


def repeated_lines(slides_text: list) -> set:
    """Lines printed on most slides of a deck (a footer, the lecturer's name, the course code): not part of any
    slide's lesson."""
    seen = {}
    for text in slides_text:
        for line in {ln.strip().lower() for ln in (text or "").splitlines()}:
            if 3 <= len(line) <= 90:
                seen[line] = seen.get(line, 0) + 1
    need = max(3, (len(slides_text) + 1) // 2)
    return {line for line, n in seen.items() if n >= need}


def without(slide_text: str, lines: set) -> str:
    """The slide's text without those lines."""
    if not lines:
        return slide_text
    return "\n".join(ln for ln in (slide_text or "").splitlines() if ln.strip().lower() not in lines)


def fixed_steps(slide_text: str, slide_no: int, title: str = "", next_title=None) -> list | None:
    """Title, outline and closing slides need no brain: what is written and said is decided here, as in normal
    lessons. None for a slide worth teaching; [] for one to pass over (a closing "Thank you" slide)."""
    words = classroom._slide(slide_text).strip() if slide_text else ""
    lines = [ln.strip(" •-–*\t") for ln in words.splitlines() if ln.strip(" •-–*\t")]
    if not lines or classroom._heading_note(words, slide_no) is None:
        return None
    keep = caps_kept(slide_text)
    first = calm(lines[0], keep, heading=True)
    if classroom._CLOSING.match(lines[0]):
        return []
    if classroom._OUTLINE.match(lines[0]) and len(lines) >= 2:
        items = [calm(it, keep) for it in lines[1:7]]
        steps = [{"kind": "lesson", "board": ["# " + first], "say": "Here is what we are going to cover."}]
        steps += [{"kind": "lesson", "board": ["- " + it], "say": it.rstrip(".") + "."} for it in items]
        steps.append({"kind": "lesson", "board": [], "say": "We will take them one at a time.", "end": True})
        return steps
    name = calm(title, keep, heading=True) if title else first
    begin = (f" Let's begin with {next_title.rstrip('.:;,')}." if next_title else " Let's begin.")
    return [{"kind": "lesson", "board": ["# " + name],
             "say": f"Today we are looking at {name}. I will write it all on the board as we go. If you have a "
                    "question, raise your hand, and I will stop and listen." + begin, "end": True}]
