"""Check the library: every formula parses and is dimensionally consistent, every quantity's units parse.

    python -m backend.mathengine.selftest
"""
from . import library as L
from .formulas import library, check
from .units import parse_unit


def main():
    bad = 0
    for name, q in L.QUANTITIES.items():
        if q["unit"] != "1" and parse_unit(q["unit"]) is None:
            print(f"quantity {name}: unit '{q['unit']}' doesn't parse")
            bad += 1
        if q["show"] and q["show"] not in ("%", "°") and parse_unit(q["show"]) is None:
            print(f"quantity {name}: display unit '{q['show']}' doesn't parse")
            bad += 1
    for sym, c in L.CONSTANTS.items():
        if c[1] != "1" and parse_unit(c[1]) is None:
            print(f"constant {sym}: unit '{c[1]}' doesn't parse")
            bad += 1
    fs = library()
    if len(fs) != len(L.FORMULAS):
        bad += len(L.FORMULAS) - len(fs)
    for f in fs:
        if f.spec.get("nodims"):
            continue
        problem = check(f)
        if problem:
            print(f"formula '{f.name}' ({f.spec['eq']}): {problem}")
            bad += 1
    print(f"{len(fs)} formulas, {len(L.QUANTITIES)} quantities, {len(L.CONSTANTS)} constants: "
          f"{'all consistent' if not bad else f'{bad} problems'}")
    return bad


def problems(verbose=False):
    """Right / abstained / WRONG on the problem bank."""
    import time
    from .engine import solve_problem
    from .problems import PROBLEMS
    right = wrong = none = 0
    t0 = time.time()
    for text, want in PROBLEMS:
        try:
            r = solve_problem(text)
        except Exception as e:
            r = None
            print(f"CRASH {text[:70]}: {e!r}")
        if not r:
            none += 1
            print(f"  --  {text}")
            continue
        ok = abs(r["value"] - want) <= 0.01 * max(abs(want), 1e-12)
        right += ok
        wrong += not ok
        if not ok or verbose:
            print(f"{'ok ' if ok else 'BAD'} {text}\n      → {r['answer']} (want {want:g})")
            if verbose or not ok:
                print("      " + "\n      ".join(r["steps"]))
    print(f"\n{right} right, {none} abstained, {wrong} WRONG of {len(PROBLEMS)}  ({time.time() - t0:.1f}s)")
    return wrong


if __name__ == "__main__":
    import sys
    bad = main()
    bad += problems(verbose="-v" in sys.argv)
    raise SystemExit(1 if bad else 0)
