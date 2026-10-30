"""
CUSTOM-SQE self-test:  python -m backend.sqe.selftest   (all must pass)

  1. Safety: text that isn't maths (Python code) is refused, never run.
  2. Marking typed answers: fair to how students write them.
  3. The student's own question, read and answered right (answers worked out by hand).
  4. Versions for every family: made, new, clean, answer among the options, quick.

The bigger measures are scripts/sqe_check.py (how many bank questions get versions) and scripts/sqe_verify.py (every
version's answer re-checked independently).
"""
from __future__ import annotations

import sys
import time

from . import api, engine
from .text import to_expr

FAILS: list = []


def expect(ok: bool, what: str) -> None:
    if not ok:
        FAILS.append(what)
        print("FAIL", what)


def safety() -> None:
    for bad in ["__import__('os').system('echo hacked')", "().__class__.__bases__", "exec('x = 1')", "lambda: 1",
                "open('secret.txt')", "eval('2')", "x.__dict__", "[x for x in (1,)]", "import os"]:
        expect(to_expr(bad) is None, f"to_expr refused {bad!r}")
        expect(api.check(bad, "2")["correct"] is False, f"check refused {bad!r}")


MARKING = [
    ("630", "GHS 630.00", "word_problem", True), ("25", "25%", "word_problem", True), ("20", "25%", "word_problem", False),
    ("157/24", "6 13/24", "number", True), ("6x + 2", "dy/dx = 6x + 2", "differentiation", True),
    ("6x+3", "dy/dx = 6x + 2", "differentiation", False), ("pi/4", "π/4 rad", "trigonometry", True),
    ("150, 30", "30°, 150°", "trigonometry", True), ("2.08", "2.08 A", "word_problem", True),
    ("2.08 kg", "2.08 A", "word_problem", False), ("3, 2", "x = 2 or x = 3", "algebra", True), ("0.5", "1/2", "limit", True),
    ("11.3", "8sqrt(2)", "indices", True), ("0.048", "4.8 × 10^-2", "number", True),
    ("x^4/4 - x^2", "x^4/4 - x^2 + C", "integration", True), ("2(x+1)", "2x + 2", "algebra", True),
    ("x < 5", "x < 5", "inequalities", True), ("-4", "x = 4", "algebra", False), ("12,500", "12500", "number", True),
]


def marking() -> None:
    for given, right, kind, want in MARKING:
        expect(api.check(given, right, kind)["correct"] is want, f"check({given!r}, {right!r}) == {want}")


# the student's own question and its answer, worked out by hand
OWN = [
    ("Differentiate f(x) = 3x^2 + 2x", "f'(x) = 6x + 2"),
    ("Find the stationary points of y = x^3 - 3x + 2", "(-1, 4) maximum and (1, 0) minimum"),
    ("Integrate x^3 - 2x", "x^4/4 - x^2 + C"),
    ("Evaluate lim x->2 of (x^2 - 4)/(x - 2)", "4"),
    ("Solve 2x + 3 = 11", "x = 4"),
    ("Solve x^2 - 5x + 6 = 0", "x = 2 or x = 3"),
    ("Solve simultaneously: 2x + y = 7 and x - y = 2", "x = 3, y = 1"),
    ("Solve 3x - 4 > 11", "x > 5"),
    ("Simplify 4(3a + 2) - 5(a - 1)", "7a + 13"),
    ("Factorise x^2 - 7x + 12", "(x - 4)(x - 3)"),
    ("Evaluate 2a^2 - 3b when a = 4 and b = -2", "38"),
    ("Simplify 3 1/2 - 1 2/3", "1 5/6"),
    ("Evaluate 3/5 of 2 1/2 divided by 3/4", "2"),
    ("Find the HCF of 84 and 126", "42"),
    ("A lamp consumes 200W of power, if the voltage is 100V, calculate the current", "2 A"),
    ("Find the simple interest on GHS 5000 at 8% per annum for 3 years.", "GHS 1,200.00"),
    ("A radio bought for GHS 250 was sold for GHS 200. Calculate the percentage loss.", "20%"),
    ("Find the 20th term of the arithmetic progression 3, 7, 11, ...", "79"),
    ("Find the mean of 4, 8, 6, 10, 12", "8"),
    ("Find the distance between the points (1, 2) and (4, 6)", "5"),
    ("Find the determinant of the matrix [[3, 2], [1, 4]]", "10"),
    ("Simplify (3 + 2i)(1 - 4i)", "11 - 10i"),
    ("Evaluate 27^(2/3)", "9"),
    ("Simplify sqrt(50) + sqrt(18)", "8sqrt(2)"),
    ("In how many ways can 5 students be arranged in a row?", "120"),
]


def own_answers() -> None:
    for question, answer in OWN:
        r = engine.make(question, n=3, seed=7, session="selftest-own", reset=True) or {}
        got = (r.get("original") or {}).get("answer")
        expect(got is not None and api.check(got, answer)["correct"], f"own answer of {question!r}: got {got!r}, want {answer!r}")


def versions() -> None:
    for question, _ in OWN + [("Prove that root 3 is irrational", ""), ("Make r the subject of the formula A = pi r^2", "")]:
        t = time.monotonic()
        r = engine.make(question, n=6, seed=3, session="selftest-versions", reset=True) or {}
        qs = r.get("questions") or []
        expect(len(qs) >= 1, f"versions made for {question!r}")
        expect(time.monotonic() - t < 10, f"quick enough for {question!r}")
        for q in qs:
            expect(q["question"].replace(" ", "").lower() != question.replace(" ", "").lower(), f"a new question, not {question!r}")
            if q.get("options"):
                expect(q["answer"] in q["options"] and len(set(q["options"])) == len(q["options"]), f"options of {q['question']!r}")
            expect(bool(q.get("steps")), f"working for {q['question']!r}")
        texts = [q["question"] for q in qs]
        expect(len(set(texts)) == len(texts), f"no repeats for {question!r}")


def main() -> int:
    t = time.monotonic()
    safety()
    marking()
    own_answers()
    versions()
    print(f"\nCUSTOM-SQE self-test: {'all passed' if not FAILS else f'{len(FAILS)} failed'} ({time.monotonic() - t:.0f} s)")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
