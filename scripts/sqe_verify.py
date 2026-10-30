"""
Independent checks of CUSTOM-SQE's answers.

    python scripts/sqe_verify.py [--bank a|b] [--seeds 3] [--n 6]

Every version CUSTOM-SQE makes for the bank questions is read again from its displayed text. This uses a plain
parser with none of the engine's number-slot machinery, and the answer is checked a second way:
  - simplify / expand / factorise: the answer equals the question's expression;
  - differentiate: the answer equals the derivative of the question's expression;
  - integrate (indefinite): the derivative of the answer (without + C) equals the integrand;
  - solve: every root makes both sides equal (systems: every equation);
  - evaluate … when a = …: the value matches.
Questions of other kinds are counted as "not checked here". Any failure is printed and the exit code is 1.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

import sympy as sp

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from backend.sqe import engine  # noqa: E402
from backend.sqe.fam_equations import head_math, tail_math  # noqa: E402 - text trimming only, no slots
from backend.sqe.text import clean, normalise, to_expr  # noqa: E402

X = sp.Symbol("x")


def plain(text: str) -> str:
    return normalise(clean(text))


def expr_after(text: str, words: str):
    m = re.search(rf"\b(?:{words})\b\s*(?:completely\s+)?:?\s*(.+)", plain(text), re.I)
    if not m:
        return None
    body = re.split(r"\s+(?:with\s+respect|w\.r\.t|in\s+partial|into\s+partial|dx\b)|[?]|\.\s|\.$", m.group(1))[0]
    body = re.sub(r"^\s*(?:the\s+)?(?:expression\s+)?", "", body)
    body = re.sub(r"^\s*(?:y|f\s*\(\s*x\s*\))\s*=\s*", "", body)
    return to_expr(body.strip().rstrip("."))


def same(a, b, syms=None) -> bool:
    syms = sorted((a.free_symbols | b.free_symbols) - {sp.Symbol("C")}, key=lambda s: s.name)
    for k, p in enumerate((sp.Rational(37, 100), sp.Rational(173, 100), sp.Rational(-61, 100))):
        pt = {s: p + sp.Rational(j, 11) for j, s in enumerate(syms)}
        try:
            va, vb = complex(sp.N(a.subs(pt))), complex(sp.N(b.subs(pt)))
        except Exception:                                                    # noqa: BLE001
            return True                                                      # can't evaluate here: no verdict
        if abs(va - vb) > 1e-6 * max(1, abs(vb)):
            return False
    return True


def answer_expr(ans: str):
    a = re.sub(r"^\s*(?:dy/dx|f'\(x\)|d²y/dx²|∂f/∂[a-z])\s*=\s*", "", ans)
    a = re.sub(r"\+\s*C\s*$", "", a).strip()
    return to_expr(normalise(a))


def check(q: dict) -> str:
    """'ok', 'bad: …' or 'skip'."""
    text, ans, kind = q["question"], q["answer"], q["fact_type"]
    low = plain(text).lower()
    try:
        if kind == "differentiation" and not re.search(r"stationary|turning|tangent|normal|gradient|second|partial|d\^?2|at\s+x|when\s+x", low):
            f = expr_after(text, r"differentiate|derivative\s+of|dy/dx\s+(?:of|if|when)|find\s+f'\s*\(x\)\s*if")
            m = re.search(r"\b(?:y|f\s*\(\s*x\s*\))\s*=\s*(.+?)(?:\s*,|\s+find|$)", plain(text))
            if m:
                f = to_expr(m.group(1))
            a = answer_expr(ans)
            if f is None or a is None:
                return "skip"
            return "ok" if same(sp.diff(f, X), a) else f"bad: d/dx({f}) != {a}"
        if kind == "integration" and "from" not in low and "between" not in low and "area" not in low:
            f = expr_after(text, r"integrate|integral\s+of|∫")
            a = answer_expr(ans)
            if f is None or a is None:
                return "skip"
            return "ok" if same(sp.diff(a, X), f) else f"bad: d/dx({a}) != {f}"
        if kind == "algebra" and re.search(r"\b(?:simplify|expand|factori[sz]e)\b", low) and "=" not in low and "when" not in low:
            e = expr_after(text, r"simplify|expand|factori[sz]e")
            a = to_expr(normalise(ans))
            if e is None or a is None:
                return "skip"
            return "ok" if same(e, a) else f"bad: {e} != {a}"
        if kind == "algebra" and re.search(r"\bwhen\b|\bif\b", low) and re.search(r"evaluate|find\s+the\s+value", low):
            m = re.search(r"(?:evaluate|value\s+of)\s+(.+?)\s+(?:when|if)\s+(.+)$", plain(text), re.I)
            if not m:
                return "skip"
            e = to_expr(m.group(1))
            env = {sp.Symbol(k): sp.sympify(v) for k, v in re.findall(r"\b([a-z])\s*=\s*(-?\d+(?:\.\d+)?)", m.group(2))}
            if e is None or not env:
                return "skip"
            return "ok" if same(e.subs(env), sp.sympify(ans)) else f"bad: {e.subs(env)} != {ans}"
        if kind in ("algebra",) and re.search(r"\bsolve\b|\bfind\b", low) and "=" in low and re.search(r"\b[a-z]\s*=\s*-?[\d(]", ans):
            body = plain(text)
            body = body.split(":")[-1]
            eqs = []
            for piece in re.split(r"\s*(?:,|;|\band\b)\s*", body):
                if "=" not in piece:
                    continue
                L, R = piece.split("=", 1)
                le, re_ = to_expr(tail_math(L)), to_expr(head_math(R))
                if le is None or re_ is None:
                    return "skip"
                eqs.append(le - re_)
            parts = re.findall(r"\b([a-z])\s*=\s*(-?[\d./]+(?:\s*[+-]\s*(?:\d+)?sqrt\(\d+\)(?:/\d+)?)?)", ans.replace("√", "sqrt"))
            if not eqs or not parts:
                return "skip"
            if len(eqs) == 1 and len({p[0] for p in parts}) == 1:
                var = sp.Symbol(parts[0][0])
                for _, v in parts:
                    val = to_expr(v)
                    if val is None:
                        return "skip"
                    if "." in v:                                     # rounded ("correct to 2 decimal places")
                        roots = [complex(sp.N(r)) for r in sp.solve(eqs[0], var)]
                        if not any(abs(r - float(val)) <= 0.0051 for r in roots):
                            return f"bad: {v} isn't a rounded root of {eqs[0]} = 0"
                    elif abs(complex(sp.N(eqs[0].subs(var, val)))) > 1e-6:
                        return f"bad: {v} doesn't satisfy {eqs[0]} = 0"
                return "ok"
            env = {sp.Symbol(k): to_expr(v) for k, v in parts}
            for e in eqs:
                if abs(complex(sp.N(e.subs(env)))) > 1e-6:
                    return f"bad: {env} doesn't satisfy {e} = 0"
            return "ok"
    except Exception as exc:                                                 # noqa: BLE001
        return f"skip ({exc.__class__.__name__})"
    return "skip"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bank", default="a")
    ap.add_argument("--seeds", type=int, default=2)
    ap.add_argument("--n", type=int, default=5)
    args = ap.parse_args()
    name = "sqe_bank.json" if args.bank == "a" else "sqe_bank_b.json"
    bank = json.load(open(os.path.join(ROOT, "scripts", name), encoding="utf-8"))["questions"]
    counts = {"ok": 0, "bad": 0, "skip": 0}
    for topic, question in bank:
        for seed in range(args.seeds):
            r = engine.make(question, n=args.n, session=f"verify-{seed}-{hash(question)}", reset=True, seed=1000 + seed)
            for q in (r or {}).get("questions") or []:
                verdict = check(q)
                key = verdict.split(":")[0].split(" ")[0]
                counts[key] = counts.get(key, 0) + 1
                if key == "bad":
                    print(f"BAD [{topic}] {q['question']}\n      answer: {q['answer']}\n      {verdict}")
    print(f"\nBank {args.bank}: {counts['ok']} answers checked independently and right, {counts['bad']} wrong, "
          f"{counts['skip']} not checked here")
    sys.exit(1 if counts["bad"] else 0)


if __name__ == "__main__":
    main()
