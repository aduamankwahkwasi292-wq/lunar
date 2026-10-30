"""The brain reads the question; CUSTOM-Mx does the maths.

Code finds every number and unit (exactly — the brain never types a number). The brain only labels them: for each
number it picks what it measures from a short list that fits its unit, and it picks what the question asks for.
Its reply is forced into a JSON schema, so even the smallest brain only makes small choices.

    req = request(text)                         # messages + schema for brain.chat(..., schema=req["schema"])
    labels = read(req, reply)                   # → {"items": {index: (quantity, role) | "skip"}, "asks": (q, r)}
    result = solve(text, labels=labels)         # both readings; an answer only when they agree (or one is silent)
"""
import json

from . import engine as E
from . import library as L
from .formulas import library, books

ROLE_TEXT = {"initial": "initial", "final": "final", "1": "first / before", "2": "second / after",
             "primary": "primary", "secondary": "secondary", "in": "input", "out": "output", "incidence": "incidence",
             "refraction": "refraction", "critical": "critical", "hot": "hot side", "cold": "cold side",
             "sync": "synchronous", "rotor": "rotor / actual", "eyepiece": "eyepiece", "objective": "objective",
             "peak": "peak", "rms": "r.m.s.", "line": "line", "phase": "phase", "a": "first parallel side",
             "b": "second parallel side", "load": "load", "effort": "effort", "air gap": "air gap",
             "rotor cu": "rotor copper loss", "mech": "mechanical", "cathode": "cathode", "anode": "anode",
             "back": "back / generated", "armature": "armature", "collector": "collector", "base": "base",
             "feedback": "feedback", "input": "input"}
NAME_TEXT = {"poles": "number of poles", "turns": "number of turns", "particles": "number of particles",
             "sides": "number of sides", "conductors": "number of conductors", "parallel paths": "number of parallel paths",
             "channels": "number of channels", "generations": "number of generations", "pixels": "number of pixels",
             "colours": "number of colours", "order": "order (n)", "years": "time in years", "q10": "Q10",
             "bmi": "BMI", "sa:v ratio": "surface area to volume ratio", "mmf": "mmf (magnetomotive force)",
             "emf": "emf", "count": "a count", "amount": "amount of substance (moles)"}
SKIP = "not needed"
MAX_OPTIONS = 18


def _label(q, r):
    name = NAME_TEXT.get(q, q)
    return f"{name} ({ROLE_TEXT.get(r, r)})" if r else name


def _usable(text_low, slide_formulas):
    return [f for f in list(slide_formulas) + list(library()) + list(books()) if E._usable(f, text_low)]


def request(text: str, slide_formulas=()):
    """The labelling request for the brain, or None when there's nothing to label."""
    t = E.clean(text)
    low = t.lower()
    items = E.givens(t)
    if not items or len(items) > 8:
        return None
    formulas = _usable(low, slide_formulas)
    pairs = sorted({(q, r) for f in formulas for (q, r) in f.vars.values() if q != "@"})
    key, props, lines = {}, {}, []
    for i, it in enumerate(items):
        scored = []
        for q, r in pairs:
            spec = L.QUANTITIES[q]
            if it.unit is None and spec["dims"] != L.NONE and not it.symbol:
                continue
            s = E.pair_score(it, "", q, r, {r} if r else set(), set())
            if s is None:
                continue
            scored.append((s, q, r))
        scored.sort(key=lambda x: -x[0])
        with_roles = {q for _, q, r in scored if r}
        opts = {}
        for s, q, r in scored:
            if not r and q in with_roles:
                continue                         # "speed (initial)" / "speed (final)", not a bare "speed" to hide behind
            opts.setdefault(_label(q, r), (q, r))
            if len(opts) >= MAX_OPTIONS:
                break
        if not opts:
            continue
        name = f"n{i + 1}"
        key[name] = (i, opts)
        props[name] = {"type": "string", "enum": list(opts)}
        lines.append(f"{name} = {it.text}: " + "; ".join(opts))
    if not key:
        return None
    # What can be asked: quantities in formulas that touch these numbers' options; the rule-based guess first.
    reachable = {q for _, opts in key.values() for (q, r) in opts.values()}
    asks = {}
    for tgt in E.find_targets(t):
        if tgt.quantity:
            asks.setdefault(_label(tgt.quantity, tgt.role), (tgt.quantity, tgt.role))
            asks.setdefault(_label(tgt.quantity, ""), (tgt.quantity, ""))
    for f in formulas:
        qs = {q for (q, r) in f.vars.values() if q != "@"}
        if qs & reachable:
            for q, r in f.vars.values():
                if q != "@":
                    asks.setdefault(_label(q, r), (q, r))
        if len(asks) >= 40:
            break
    props["asks"] = {"type": "string", "enum": list(asks)}
    key["asks"] = asks
    system = ("You read a student's science or maths question and say what each number in it measures, and what the "
              "question asks for. Choose only from the options listed. Don't calculate anything.")
    user = (f"Question: {t}\n\nNumbers and what each could be:\n" + "\n".join(lines) +
            "\n\nasks (what the question wants found): " + "; ".join(asks) +
            "\n\nReply in JSON with " + ", ".join(list(k for k in key if k != "asks")) + " and asks.")
    schema = {"type": "object", "properties": props, "required": list(props)}
    return {"messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "schema": schema, "key": key, "text": t}


def read(req, reply: str):
    """The brain's JSON reply → labels for solve(). None if it can't be read."""
    try:
        data = json.loads(reply)
    except Exception:
        return None
    labels = {"items": {}, "asks": None}
    for name, (i, opts) in ((k, v) for k, v in req["key"].items() if k != "asks"):
        pick = data.get(name)
        labels["items"][i] = "skip" if pick == SKIP else opts.get(pick)
    labels["asks"] = req["key"]["asks"].get(data.get("asks"))
    if labels["asks"] is None:
        return None
    return labels


def solve(text: str, slide_formulas=(), labels=None):
    """CUSTOM-Mx's answer, or None. With the brain's labels, both readings are tried: an answer when they agree
    or when only one of them finds one; nothing when they disagree."""
    code = E.solve_problem(text, slide_formulas)
    if not labels:
        return code
    brain = E.solve_problem(text, slide_formulas, labels=labels)
    if code and brain:
        if abs(code["value"] - brain["value"]) <= 0.01 * max(abs(code["value"]), 1e-12):
            brain["confirmed"] = True
            return brain
        return None
    return brain or code
