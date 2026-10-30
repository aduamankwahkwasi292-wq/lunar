"""Cross-check the hand-written library against the imported OpenStax formulas.

Where a book formula and a library formula link the same quantities (one variable per quantity), solve both for the
same variable with random values and compare. A disagreement means one of them is wrong.

    python scripts/crosscheck_books.py
"""
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend.mathengine.formulas import library, books   # noqa: E402


def signature(f):
    qs = [q if q != "@" else "@" + r for (q, r) in f.vars.values()]
    return tuple(sorted(qs)) if len(qs) == len(set(qs)) else None


def main():
    random.seed(1)
    from backend.mathengine import library as L
    lib = {}
    for f in library():
        sig = signature(f)
        if sig:
            lib.setdefault(sig, []).append(f)
    agree = disagree = 0
    for b in books():
        sig = signature(b)
        if not sig or sig not in lib:
            continue
        for f in lib[sig]:
            by_q_b = {(q if q != "@" else "@" + r): s for s, (q, r) in b.vars.items()}
            by_q_f = {(q if q != "@" else "@" + r): s for s, (q, r) in f.vars.items()}
            target_q = next(q for q in sig if not q.startswith("@"))
            vals = {q: random.uniform(0.5, 3.0) for q in sig if not q.startswith("@") and q != target_q}
            for q in sig:
                if q.startswith("@"):
                    vals[q] = L.CONSTANTS[q[1:]][0]
            try:
                eb = b.solve_for(by_q_b[target_q])
                ef = f.solve_for(by_q_f[target_q])
                vb = sorted(complex(e.subs({b.syms[by_q_b[q]]: v for q, v in vals.items()}).evalf()).real for e in eb)
                vf = sorted(complex(e.subs({f.syms[by_q_f[q]]: v for q, v in vals.items()}).evalf()).real for e in ef)
            except Exception as e:
                continue
            same = any(abs(x - y) <= 1e-6 * max(1.0, abs(x)) for x in vb for y in vf)
            if same:
                agree += 1
            else:
                disagree += 1
                print(f"DIFFER: book '{b.name}' [{b.spec['eq']}]  vs  library '{f.name}' [{f.spec['eq']}]  "
                      f"solving for {target_q}: {vb} vs {vf}")
    print(f"{agree} agree, {disagree} differ")


if __name__ == "__main__":
    main()
