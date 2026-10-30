"""
How much of the question bank CUSTOM-SQE (backend/sqe) can make practice questions from.

    python scripts/sqe_check.py [--bank a|b] [--n 3] [--out results.json] [--topic algebra] [--show]

Each bank question goes through CUSTOM-SQE (backend/sqe/api.py, what the SQE window calls) in a worker process
with a time limit, so one hard input can't stall the run.
- Bank a: scripts/sqe_bank.json. Bank b: scripts/sqe_bank_b.json, held out: never tune against it.
- "Made" means at least one new version came back.
- Quality flags: a version identical to the question, repeats, answers missing from their own options, fractions
  or decimals the student didn't use, or a slow make.
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import sys
import time
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TIME_LIMIT = 10.0


def _work(question: str, n: int) -> dict:
    sys.path.insert(0, ROOT)
    import re
    from backend.sqe.api import generate
    t = time.time()
    r = generate(question, n=n, session=f"bank-{abs(hash(question))}", reset=True)
    qs = r.get("questions") or []
    flags = []
    texts = [q["question"] for q in qs]
    canon = lambda s: re.sub(r"\s+", "", s.lower())
    if any(canon(x) == canon(question) for x in texts):
        flags.append("same as the question")
    if len(set(map(canon, texts))) < len(texts):
        flags.append("repeats")
    if any(q.get("options") and q["answer"] not in q["options"] for q in qs):
        flags.append("answer not in options")
    if "/" not in question and any(re.search(r"\d/\d", x) for x in texts):
        flags.append("new fractions")
    if "." not in question and any(re.search(r"\d\.\d", x) for x in texts):
        flags.append("new decimals")
    secs = round(time.time() - t, 2)
    if secs > 8:
        flags.append("slow")
    return {"type": r.get("detected_type"), "made": len(qs), "seconds": secs, "engine": (qs[0].get("engine") if qs else ""),
            "examples": [(q["question"], q["answer"]) for q in qs[:2]], "mcq": sum(1 for q in qs if q.get("options")),
            "flags": flags, "message": r.get("message", "")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=3)
    ap.add_argument("--bank", default="a")
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--out", default="")
    ap.add_argument("--topic", default="")
    args = ap.parse_args()
    name = "sqe_bank.json" if args.bank == "a" else "sqe_bank_b.json"
    bank = json.load(open(os.path.join(ROOT, "scripts", name), encoding="utf-8"))["questions"]
    if args.topic:
        bank = [b for b in bank if b[0] == args.topic]

    results, pool = [], mp.Pool(1)
    for topic, question in bank:
        try:
            res = pool.apply_async(_work, (question, args.n)).get(TIME_LIMIT)
        except mp.TimeoutError:
            pool.terminate()
            pool = mp.Pool(1)
            res = {"type": None, "made": 0, "seconds": TIME_LIMIT, "examples": [], "flags": ["timed out"], "message": "timed out"}
        except Exception as e:                                   # noqa: BLE001 - a crash counts as not understood
            res = {"type": None, "made": 0, "seconds": 0, "examples": [], "flags": [f"error: {e}"], "message": f"error: {e}"}
        results.append({"topic": topic, "question": question, **res})
    pool.terminate()

    by_topic = defaultdict(lambda: [0, 0])
    for r in results:
        by_topic[r["topic"]][1] += 1
        by_topic[r["topic"]][0] += 1 if r["made"] else 0
    ok = sum(v[0] for v in by_topic.values())
    flagged = [r for r in results if r.get("flags")]
    new = sum(1 for r in results if r.get("made") and r.get("engine") == "custom-sqe")
    print(f"\nBank {args.bank}: CUSTOM-SQE makes versions of {ok} of {len(results)} questions "
          f"({100 * ok / max(1, len(results)):.0f}%), {new} by the new families; {len(flagged)} with quality flags\n")
    for topic, (good, total) in sorted(by_topic.items(), key=lambda kv: kv[1][0] / kv[1][1]):
        print(f"  {topic:<15} {good:>3}/{total:<3} {'#' * good}{'.' * (total - good)}")
    if args.show:
        for r in results:
            mark = "OK" if r["made"] else "--"
            print(f"\n{mark} [{r['topic']}] {r['question']}  ({r['seconds']}s, {r.get('engine') or r.get('type') or ''}, "
                  f"{r.get('mcq', 0)} with options)" + (f"  FLAGS: {', '.join(r['flags'])}" if r.get("flags") else ""))
            for qq, aa in r.get("examples") or []:
                print(f"     {qq}  =  {aa}")
            if not r["made"] and r.get("message"):
                print(f"     {r['message'][:140]}")
    if args.out:
        json.dump(results, open(args.out, "w", encoding="utf-8"), indent=1, ensure_ascii=False)


if __name__ == "__main__":
    main()
