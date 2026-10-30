"""
CUSTOM-SQE's engine: one student question in, new versions of it out.

The families are tried in order; the first one that reads the question and can solve it makes the versions.
Every family is imported here statically, which is how the packaged app finds them. Nothing is repeated within
one practice session (the SQE window's session id).
"""
from __future__ import annotations

import hashlib
import random
import re
import threading
import time
from collections import OrderedDict
from typing import List, Optional

from .core import Family, Item, canon, make_versions, shuffled_options
from .fam_calculus import Differentiate, Integrate, Limit
from .fam_equations import Equation, Inequality, Subject
from .fam_words import WordProblem
from .fam_algebra import Manipulate, Powers, Quadratic, Theorems
from .fam_number import Number
from .fam_sequences import Sequence
from .fam_stats import Statistics
from .fam_trig import Trig
from .fam_geometry import Coordinates
from .fam_misc import Complex, Matrices, Proof
from .text import Question

FAMILIES: List[Family] = [
    Differentiate(), Integrate(), Limit(),
    Proof(), Matrices(), Complex(), Coordinates(), Trig(), Statistics(), Sequence(), Number(), WordProblem(),
    Theorems(), Quadratic(), Manipulate(), Powers(),
    Subject(), Inequality(), Equation(),
]

MAX_SESSIONS = 200
_SESSIONS: "OrderedDict[str, set]" = OrderedDict()
_LOCK = threading.Lock()


def _seen(session: Optional[str], reset: bool) -> set:
    key = session or "-"
    with _LOCK:
        if reset or key not in _SESSIONS:
            _SESSIONS[key] = set()
        _SESSIONS.move_to_end(key)
        while len(_SESSIONS) > MAX_SESSIONS:
            _SESSIONS.popitem(last=False)
        return _SESSIONS[key]


_SEEDS = [                                              # hidden 1s made visible, so there is a number to change
    (re.compile(r"(?<![A-Za-z])e\^\(?(-?)x\)?(?![\w^(])"), r"e^(\g<1>1x)"),
    (re.compile(r"(?<![A-Za-z])(sin|cos|tan)\s*\(?x\)?(?![\w^(])"), r"\1(1x)"),
    (re.compile(r"(?<![A-Za-z])ln\s*\(?x\)?(?![\w^(])"), r"ln(1x)"),
]


def seeded(text: str) -> str:
    """'Integrate x e^x' -> 'Integrate x e^(1x)': versions can then be x e^(2x), x e^(3x) …"""
    hits = sum(len(pat.findall(text)) for pat, _ in _SEEDS)
    if hits != 1:                                       # sin x cos x: changing one would change the question
        return text
    out = text
    for pat, rep in _SEEDS:
        out = pat.sub(rep, out)
    return out


def _out(item: Item, fam: Family) -> dict:
    options = shuffled_options(item)
    return {
        "fact_type": item.kind or fam.kind,
        "fact_key": hashlib.sha1(canon(item.question).encode()).hexdigest()[:16],
        "question_type": "mcq" if options else "short_answer",
        "question": item.question,
        "answer": item.answer,
        "options": options,
        "steps": item.steps,
        "difficulty": "medium",
        "engine": "custom-sqe",
    }


def make(question: str, n: int = 10, session: Optional[str] = None, reset: bool = False,
         budget: float = 14.0, seed: Optional[int] = None) -> Optional[dict]:
    """{questions: [...], detected_type} — or None when no family reads the question."""
    q = Question(question)
    if not q.display:
        return None
    deadline = time.monotonic() + budget
    rng = random.Random(seed if seed is not None else time.time_ns())
    seen = _seen(session, reset)
    for fam in FAMILIES:
        if time.monotonic() > deadline:
            break
        try:
            spec = fam.parse(q)
            base = fam.solve(q, spec, q.vals, full=False) if spec is not None else None
        except Exception:                                                    # noqa: BLE001 - not this family
            base = None
        if base is None:
            continue
        items = fam.versions(q, spec, n, rng, seen) if hasattr(fam, "versions") else None   # not by numbers
        if items is None:
            items = make_versions(q, fam, spec, base, n, rng, seen, deadline)
            if len(items) < max(1, n // 3) and seeded(q.display) != q.display:   # little or nothing to vary: seed 1s
                try:
                    q2 = Question(seeded(q.display))
                    spec2 = fam.parse(q2)
                    base2 = fam.solve(q2, spec2, q2.vals, full=False) if spec2 is not None else None
                except Exception:                                            # noqa: BLE001
                    base2 = None
                if base2 is not None and base2.answer == base.answer:
                    seen.add(canon(q.display))
                    items += make_versions(q2, fam, spec2, base2, n - len(items), rng, seen, deadline)
        try:                                                                 # the student's own question, answered
            own = fam.solve(q, spec, q.vals, full=True) or base
        except Exception:                                                    # noqa: BLE001
            own = base
        original = {"question": q.display, "answer": own.answer, "steps": own.steps}
        understood = fam.describe(spec) if hasattr(fam, "describe") else ""
        if items:
            return {"detected_type": fam.name, "questions": [_out(it, fam) for it in items], "original": original,
                    "understood": understood}
        return {"detected_type": fam.name, "questions": [], "original": original, "understood": understood,
                "message": "CUSTOM-SQE understood this question but couldn't make new versions of it with clean "
                           "numbers. Try a similar question with different numbers."}
    return None
