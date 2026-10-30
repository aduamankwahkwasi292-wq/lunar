"""/CUSTOM-Mx — the student talks to the engine directly, in a precise language (the Javelin idea): it does exactly
what the command says, and when a command is unclear or impossible it refuses and says why and how to say it. No
brain anywhere, nothing guessed — the same command gives the same answer every time.

    find s given u = 0 m/s, v = 20 m/s, t = 5 s
    find power given voltage = 240 V, current = 5 A using "Electrical power (P = VI)"
    find current given V = 12 V, R = 4 Ω then find power
    find v in km/h given u = 0, a = 2 m/s^2, t = 5 s
    solve 2x + 5 = 17
    rearrange "v = u + a*t" for t               rearrange "Ohm's law" for R
    substitute u = 0, a = 2, t = 5 into "v = u + a*t"
    convert 100 km/h to m/s
    formulas for kinetic energy
    what is v
    help

Everyday phrasing ("calculate the power if voltage is 240 V and current is 5 A") is first rewritten into the exact
form by fixed rules, and the rewrite is shown ("Understood as: …") so the student sees what ran.

    run(command) → {"ok": bool, "markdown": str, "understood": str}
"""
import difflib
import functools
import itertools
import re
import threading

from . import engine as E
from . import library as L
from .formulas import library, books, show_symbol, pretty, sup
from .units import fmt_num, parse_unit, si_label

NONE = L.NONE
MAX_DEPTH = 3                 # formulas chained to reach what's asked
SAME = 1e-4                   # two ways that agree this closely give the same answer (constants are rounded)
ROLE_NAMES = {"initial": "initial", "starting": "initial", "original": "initial", "final": "final",
              "first": "1", "second": "2", "input": "in", "output": "out", "primary": "primary",
              "secondary": "secondary", "line": "line", "phase": "phase", "rotor": "rotor", "actual": "rotor",
              "synchronous": "sync", "peak": "peak", "maximum": "peak", "rms": "rms", "r.m.s.": "rms", "hot": "hot",
              "cold": "cold", "incident": "incidence", "incidence": "incidence", "refracted": "refraction",
              "refraction": "refraction", "critical": "critical", "eyepiece": "eyepiece", "objective": "objective",
              "back": "back", "generated": "back", "armature": "armature", "collector": "collector", "base": "base",
              "feedback": "feedback", "mechanical": "mech", "air gap": "air gap", "air-gap": "air gap",
              "anode": "anode", "cathode": "cathode", "load": "load", "effort": "effort"}
HELP = """**/CUSTOM-Mx — talk to the maths engine directly.** It does exactly what you write, or tells you why it can't.

- `find s given u = 0 m/s, v = 20 m/s, t = 5 s`: names can be symbols (`v`, `R`) or words (`final speed`, `resistance`)
- `find power given voltage = 240 V, current = 5 A using "P = VI"`: choose the formula yourself
- `find current given V = 12 V, R = 4 Ω then find power`: `then` carries the answers on
- `find v in km/h given …`: answer in the unit you want
- `solve 2x + 5 = 17`: equations, simultaneous equations, calculus, statistics
- `rearrange "v = u + a*t" for t`: change of subject (your formula, or one by name)
- `substitute u = 0, a = 2, t = 5 into "v = u + a*t"`: your own formula, your numbers
- `convert 100 km/h to m/s`
- `formulas for kinetic energy`, `what is v`: look things up"""


class Refusal(Exception):
    def __init__(self, reason, hint=""):
        super().__init__(reason)
        self.reason, self.hint = reason, hint


# ── names: what a word or symbol can mean ────────────────────────────────────
@functools.lru_cache(maxsize=None)
def _tables():
    """symbols: 'v' → {(quantity, role)} as used in the formulas (case matters: V is not v); names: 'final speed' →
    {(quantity, role)} (case doesn't); roles each quantity really has."""
    symbols, roles = {}, {}
    for f in list(library()) + list(books()):
        for sym, (q, r) in f.vars.items():
            for s in {sym, show_symbol(sym), sym.replace("_", "")}:
                symbols.setdefault(s, set()).add((q, r))
            if q != "@" and r:
                roles.setdefault(q, set()).add(r)
    names = {}
    for q, spec in L.QUANTITIES.items():
        for w in [q, spec["name"]] + list(spec["words"]):
            names.setdefault(w.lower(), set()).add((q, ""))
    for c, (_v, _u, label, words) in L.CONSTANTS.items():
        for w in [c] + words.split("|"):
            if w and not w.startswith("take ") and "=" not in w:
                names.setdefault(w.lower(), set()).add(("@", c))
    return symbols, names, roles


_ROLE_ALSO = {"initial": "1", "final": "2", "1": "initial", "2": "final"}   # a gas law's T₁ is the initial T


def _role_of(word, q):
    r = ROLE_NAMES.get(word.lower(), word.lower())
    _s, _n, roles = _tables()
    have = roles.get(q, set())
    return r if r in have else _ROLE_ALSO[r] if _ROLE_ALSO.get(r) in have else None


def meanings(name: str) -> set:
    """Every (quantity, role) a name could be — no guessing between them here. A role word in a name counts:
    "rotor speed" is the rotor's speed, never just any rotational speed."""
    symbols, names, _roles = _tables()
    name = re.sub(r"\s+", " ", name.strip())
    low = name.lower()
    out = set(symbols.get(name, ()))
    for q, r in names.get(low, ()):
        if q != "@" and not r:
            r = next((rr for w in re.split(r"[\s-]+", low) if (rr := _role_of(w, q))), "")
        out.add((q, r))
    if out:
        return out
    m = re.fullmatch(r"(.+?)\s*\(([^()]+)\)", low)                  # "speed (initial)"
    parts = [(m.group(1), m.group(2))] if m else []
    words = low.split(" ")
    for i in range(1, len(words)):                                  # "initial speed", "power output"
        parts += [(" ".join(words[i:]), " ".join(words[:i])), (" ".join(words[:i]), " ".join(words[i:]))]
    for qname, rword in parts:
        for q, _ in names.get(qname, ()):
            if q != "@":
                r = _role_of(rword, q)
                if r:
                    out.add((q, r))
    return out


_ROLE_SAY = {"initial": "initial", "final": "final", "1": "first", "2": "second", "in": "input", "out": "output",
             "rotor": "rotor", "sync": "synchronous", "mech": "mechanical", "back": "back", "incidence": "incident",
             "refraction": "refracted"}


def _describe(q, r):
    if q == "@":
        c = L.CONSTANTS[r]
        return f"the constant {c[2]} ({c[3].split('|')[0]})"
    name = L.QUANTITIES[q]["name"]
    rtext = _ROLE_SAY.get(r, r)
    return f"{rtext} {name}" if r else name


def _unknown(name):
    symbols, names, _r = _tables()
    close = difflib.get_close_matches(name.lower(), list(names), n=4, cutoff=0.75)
    close += [s for s in difflib.get_close_matches(name, list(symbols), n=3, cutoff=0.8) if s not in close]
    hint = ("Did you mean " + ", ".join(f"`{c}`" for c in close[:4]) + "?") if close else \
        "Use a quantity's name (`final speed`, `resistance`) or a symbol from a formula (`v`, `R`). `what is v` lists what a symbol means."
    return Refusal(f"I don't know what “{name}” is.", hint)


# ── values ───────────────────────────────────────────────────────────────────
def _value(text, label):
    """'20 m/s' → a given (exact number and unit), or a refusal saying what's wrong with it."""
    t = E.clean(text.strip())
    items = E.givens(t)
    lead = t[:items[0].pos].strip() if items else ""
    if items and lead and re.fullmatch(r"GH₵|GHS|GHC|₵|\$|£|€|USD", lead):
        t, items[0].pos = t[items[0].pos:], 0               # the currency already set the unit
    if len(items) != 1 or items[0].pos != 0 or t[items[0].pos + len(items[0].text):].strip():
        if items and items[0].pos == 0:
            rest = t[len(items[0].text):].strip()
            raise Refusal(f"I can't read the unit “{rest}” in `{label} = {text.strip()}`.",
                          "Write units like `m/s`, `m/s^2`, `kΩ`, `°C`, `kWh`.")
        raise Refusal(f"`{label} = {text.strip()}` needs one number, with its unit.", "For example `t = 5 s`.")
    return items[0]


def _fits_dims(it, q, r=""):
    if q == "@":
        cu = parse_unit(L.CONSTANTS[r][1]) if L.CONSTANTS[r][1] != "1" else None
        return (it.unit.dims if it.unit else NONE) == (cu.dims if cu else NONE)
    spec = L.QUANTITIES[q]
    if it.unit is None:
        return spec["dims"] == NONE or (it.raw == 0 and q not in ("temperature",))
    return it.unit.dims in spec["accept"] or it.unit.dims == spec["dims"]


def _given(name, text):
    """A named value: an engine Item that knows every meaning its name could have (those its unit allows)."""
    ms = meanings(name)
    if not ms:
        raise _unknown(name)
    it = _value(text, name)
    ok = sorted(m for m in ms if _fits_dims(it, *m))
    if not ok:
        kinds = sorted({_describe(*m) for m in ms})[:3]
        unit = it.unit.label if it.unit else "no unit"
        need = sorted({L.QUANTITIES[q]["unit"] for q, _ in ms if q != "@"} - {""})
        raise Refusal(f"“{name}” is {' or '.join(kinds)}, but “{text.strip()}” ({unit}) isn't measured like that.",
                      f"Give it in {' or '.join(need[:3]) or 'a matching unit'}." if need else "")
    item = it
    item.symbol = name
    if any(q == "@" for q, _ in ok):                  # g = 9.8 m/s²: the constant, given a value of the student's own
        item.label = name
    item.meanings = ok
    item.name = name
    return item


# ── solving ──────────────────────────────────────────────────────────────────
def _fits(it, q, r):
    """Can this value fill a formula's slot (quantity q, role r)? A slot with no role takes any role of q."""
    for qi, ri in getattr(it, "meanings", [(it.quantity, it.role)]):
        if qi == q and (ri == r or E.same_role(ri, r) or not r):
            return True
    return False


def _is_target(tgt, f, q, r):
    """The formula's slot is what was asked: the same quantity in the same role ("speed" is not "final speed")."""
    return any(tq == q and (tr == r or E.same_role(tr, r)) for tq, tr in tgt)


def _assignments(f, sym, known, limit=40):
    slots = []
    for s, (q, r) in f.vars.items():
        if s == sym:
            continue
        if q == "@":
            mine = [it for it in known if ("@", r) in getattr(it, "meanings", ())]
            slots.append((s, mine[:1] or [E._constant_item(r)]))
        else:
            opts = [it for it in known if _fits(it, q, r)]
            if not opts:
                return []
            slots.append((s, opts))
    out = []
    for combo in itertools.product(*[o for _, o in slots]):
        if len({id(c) for c in combo}) < len(combo):
            continue                                  # one value fills one slot
        out.append(dict(zip([s for s, _ in slots], combo)))
        if len(out) >= limit:
            break
    return out


def _uses(assign):
    used = set()
    for it in assign.values():
        if it.kind == "given":
            used.add(id(it))
        used |= set(getattr(it, "uses", ()))
    return frozenset(used)


def _steps(assign):
    lines = []
    for it in assign.values():
        for line in getattr(it, "work", []) or []:
            if line not in lines:
                lines.append(line)
    return lines


def _evaluate(f, sym, assign):
    v, e, note = E.evaluate(f, sym, assign)
    if v is None:
        return None
    c = E.Candidate(f, sym, assign, 0.0, v, note, e)
    return c


def _known(known, q, r):
    """Already known: a value that is (or could be) this quantity in this role — or any role, for a slot with none."""
    return any(qi == q and (ri == r or E.same_role(ri, r) or not r)
               for it in known for qi, ri in getattr(it, "meanings", [(it.quantity, it.role)]))


def _derive(known, formulas, exclude):
    """Everything one more formula pins down from what's known (a quantity not already known)."""
    new, seen = [], set()
    for f in formulas:
        qs = {q for (q, r) in f.vars.values() if q != "@"}
        if not qs or not any(any(_fits(it, q, "") for it in known) for q in qs):
            continue
        for sym, (q, r) in f.vars.items():
            if q == "@" or (q, r) in exclude or _known(known, q, r):
                continue
            for assign in _assignments(f, sym, known, limit=8):
                c = _evaluate(f, sym, assign)
                if c is None:
                    continue
                key = (q, r, round(c.value, 9))
                if key in seen:
                    continue
                seen.add(key)
                it = E.Item(kind="derived", quantity=q, role=r, value=c.value, label=show_symbol(sym),
                            uses=_uses(assign), via=E._via(f, assign), reads=E._reads(f, assign))
                it.meanings = [(q, r)]
                it.work = _steps(assign) + E.working(c, heading=f"find {show_symbol(sym)} first")
                it.depth = 1 + max([getattr(a, "depth", 0) for a in assign.values()] + [0])
                new.append(it)
    return new


def _solutions(tgt, known, using, givens):
    """Every way the formulas reach what's asked, at the fewest steps that reach it at all — the hand-checked
    library first; the OpenStax formulas only when it has no way (as everywhere in CUSTOM-Mx). Ways that leave a
    value the student gave unused lose to ways that use them all."""
    for tier in ([using] if using else [list(library()), list(library()) + list(books())]):
        sols = _search(tgt, known, tier)
        if sols:
            full = [c for c in sols if all(id(g) in _uses(c.assign) for g in givens)]
            return full or sols
    return []


def _search(tgt, known, finals):
    pool = list(known)
    chain = list(library())                          # steps on the way: hand-checked formulas only
    for _depth in range(MAX_DEPTH):
        sols = []
        for f in finals:
            for sym, (q, r) in f.vars.items():
                if q == "@" or not _is_target(tgt, f, q, r):
                    continue
                for assign in _assignments(f, sym, pool):
                    c = _evaluate(f, sym, assign)
                    if c is not None:
                        sols.append(c)
        if sols:
            return sols
        new = _derive(pool, chain, set(tgt))
        if not new:
            return []
        pool += new
    return []


def _formula_by(text):
    """using "…": a formula by its name or as written. Refuses a name that fits none or several."""
    want = text.strip().lower()
    norm = lambda s: re.sub(r"\s+|\*", "", s.lower()).replace("²", "^2").replace("·", "")
    fs = list(library()) + list(books())
    hit = [f for f in fs if f.name.lower() == want] or [f for f in fs if norm(f.text) == norm(text)] \
        or [f for f in fs if want in f.name.lower()] or [f for f in fs if norm(text) in norm(f.text)]
    if not hit:
        close = difflib.get_close_matches(want, [f.name.lower() for f in fs], n=3, cutoff=0.5)
        raise Refusal(f"CUSTOM-Mx has no formula called “{text}”.",
                      ("Close: " + ", ".join(f"“{c}”" for c in close) + ". ") if close else
                      "`formulas for <quantity>` lists them.")
    return hit


def _find(step, known, context=""):
    """One `find …` step. Returns (markdown lines, its values and answers, for the next step). `context`: the
    command as the student typed it (its words say which special-situation formulas apply)."""
    context = (context or step).lower()
    m = re.fullmatch(r"find\s+(?P<what>.+?)(?:\s+given\s+(?P<given>.+?))?(?:\s+using\s+(?P<using>.+))?", step, re.I | re.S)
    if not m:
        raise Refusal("A find needs something to find.", "`find power given voltage = 240 V, current = 5 A`")
    using = None
    if m.group("using"):
        u = m.group("using").strip()
        using = _formula_by(u[1:-1] if u[:1] in "\"“" and u[-1:] in "\"”" else u)
    givens = []
    if m.group("given"):
        for part in re.split(r"\s*;\s*|,(?!\d{3}\b)\s*|\s+and\s+", m.group("given").strip()):
            if not part.strip():
                continue
            g = re.fullmatch(r"(.+?)\s*(?:=|:|\bis\b)\s*(.+)", part.strip())
            if not g:
                raise Refusal(f"I can't read “{part.strip()}”.", "Write each value as `name = number unit`, e.g. `t = 5 s`.")
            givens.append(_given(g.group(1), g.group(2)))
    targets = []
    for part in re.split(r"\s*,\s*|\s+and\s+", m.group("what").strip()):
        part = _article(part.strip())
        unit = None
        u = re.fullmatch(r"(.+?)\s+in\s+(\S+)", part)
        if u and parse_unit(u.group(2)):
            part, unit = u.group(1), parse_unit(u.group(2))
        ms = meanings(part)
        if not ms:
            raise _unknown(part)
        ms = {x for x in ms if x[0] != "@"}
        if unit:
            ms = {x for x in ms if unit.dims in L.QUANTITIES[x[0]]["accept"] or unit.dims == L.QUANTITIES[x[0]]["dims"]}
            if not ms:
                raise Refusal(f"“{part}” isn't measured in {unit.label}.")
        targets.append((part, ms, unit))
    for g in givens:
        for part, ms, _u in targets:
            if set(g.meanings) & ms and g.name.lower() == part.lower():
                raise Refusal(f"You gave {g.name} = {g.text} — it's already known.", "Find something else, or remove it.")
    formulas = list(library()) + list(books())
    pool = list(known) + givens
    lines, results, used, reads = [], [], set(), {}
    for part, ms, unit in targets:
        mine = givens if len(targets) == 1 else []
        sols = _solutions(ms, pool, using, mine)
        _which_role(part, ms, pool, using, mine, sols)
        if not sols:
            for g in givens:                          # "a = 2": with no unit it can't be the acceleration
                lost = sorted({(_describe(q, r), L.QUANTITIES[q]["unit"]) for q, r in meanings(g.name)
                               if q != "@" and L.QUANTITIES[q]["dims"] != NONE}) if g.unit is None and g.raw else []
                if lost:
                    raise Refusal(f"`{g.name} = {g.text}` has no unit, so it can't be "
                                  f"{' or '.join(d for d, _ in lost[:3])}.", f"Give its unit, e.g. `{g.name} = {g.text} {lost[0][1]}`.")
            raise _no_way(part, ms, pool, formulas, using)
        groups = _groups(sols)
        if len(groups) > 1:
            # A formula for a special situation ("Echo": v = 2d/t) wins when the command names that situation, and
            # gives way to the plain formula when it doesn't
            named = [c for c in sols if c.formula.needs and E._usable(c.formula, context)]
            plain = [c for c in sols if not c.formula.needs and E._usable(c.formula, context)]
            for pick in (named, plain):
                if pick and len(_groups(pick)) == 1:
                    sols, groups = pick, _groups(pick)
                    break
        if len(groups) > 1:
            ways = []
            for gr in groups[:4]:
                c = gr[0]
                num, lab = E._value_label(c.formula.vars[c.target][0], c.value)
                chain = " → ".join(E._via(c.formula, c.assign))
                ways.append(f"- “{c.formula.name}” ({chain}): {show_symbol(c.target)} = {num} {lab}".rstrip())
            raise Refusal(f"Your values give {len(groups)} different answers for {part}, depending on the formula:\n" +
                          "\n".join(ways), f'Choose one: add `using "{groups[0][0].formula.name}"` (or another name above).')
        best = sorted(groups[0], key=lambda c: (-len(_uses(c.assign)), _depth(c), c.formula.source != "library",
                                                c.formula.index))[0]
        used |= {u for c in groups[0] for u in _uses(c.assign)}
        reads.update(E._reads(best.formula, best.assign))
        q, r = best.formula.vars[best.target]
        lines += [l for l in _steps(best.assign) if l not in lines]
        lines += E.working(best)
        label = show_symbol(best.target)
        answer = E._answer_line(label, q, best.value, E.Target(quantity=q, role=r, unit=unit), givens)
        lines.append(f"**Answer:** {answer}")
        if best.formula.source != "library":
            lines.append("*Formula from OpenStax (openstax.org, CC BY 4.0).*")
        res = E.Item(kind="derived", quantity=q, role=r, value=best.value, label=label, uses=_uses(best.assign))
        res.meanings = [(q, r)]
        res.work = []                                  # already shown above
        results.append(res)
        pool.append(res)
    unused = [g for g in givens if id(g) not in used]
    if unused:
        names = ", ".join(f"{g.name} = {g.text}" for g in unused)
        raise Refusal(f"Nothing that finds {', '.join(t[0] for t in targets)} uses {names}.",
                      "Remove it, or say which formula to use with `using \"…\"`. (CUSTOM-Mx doesn't ignore values you give it.)")
    read = []
    for g in givens:
        if len(set(g.meanings)) < 2:
            continue                                  # only names that could have been read more than one way
        lab = reads.get(id(g))
        if lab and lab != "extra":
            q, _, r = lab.partition(":")
            desc = _describe(q, r) if q in L.QUANTITIES else lab
            if g.name.lower() != desc.lower():
                read.append(f"{g.name} = {desc}")
    if read:
        lines.insert(0, "**Read as:** " + "; ".join(read))
    return lines, givens + results


def _which_role(part, ms, pool, using, givens, sols):
    """'find speed' when 'initial speed' or 'final speed' is what the values give directly: ask which, never pick
    one — and don't answer a roundabout 'speed' either."""
    _s, _n, roles = _tables()
    best = min((_depth(c) for c in sols), default=None)
    can = []
    for q, r in sorted(ms):
        if q == "@" or r:
            continue
        for role in sorted(roles.get(q, ())):
            alt = _solutions({(q, role)}, pool, using, givens)
            if alt and (best is None or min(_depth(c) for c in alt) < best):
                can.append(_describe(q, role))
    if can:
        raise Refusal(f"“{part}” could mean " + " or ".join(f"`{c}`" for c in can) + ".",
                      f"Say which, e.g. `find {can[0]} given …`.")


def _groups(sols):
    """Solutions with the same answer together, smallest answer first."""
    groups = []
    for c in sorted(sols, key=lambda c: c.value):
        for gr in groups:
            if abs(gr[0].value - c.value) <= SAME * max(abs(c.value), abs(gr[0].value)):
                gr.append(c)
                break
        else:
            groups.append([c])
    return groups


def _depth(c):
    return sum(1 for it in c.assign.values() if it.kind == "derived")


def _no_way(part, ms, pool, formulas, using):
    """Why nothing reaches it: the formulas that find it, and what each still needs."""
    have = {m for it in pool for m in getattr(it, "meanings", [(it.quantity, it.role)])}
    needs = []
    for f in (using or formulas):
        for sym, (q, r) in f.vars.items():
            if q == "@" or not _is_target(ms, f, q, r):
                continue
            missing = [_describe(q2, r2) + f" ({show_symbol(s2)})" for s2, (q2, r2) in f.vars.items()
                       if s2 != sym and q2 != "@" and not any(q2 == hq and (r2 == hr or not r2 or E.same_role(r2, hr)) for hq, hr in have)]
            needs.append((len(missing), f"- {f.name}: {pretty(f.raw_lhs)} = {pretty(f.raw_rhs)} — needs {', '.join(missing) or 'nothing more'}"))
    needs.sort(key=lambda x: x[0])
    what = " or ".join(sorted({_describe(*m) for m in ms})[:3])
    if not needs:
        return Refusal(f"CUSTOM-Mx has no formula that finds {what}.", "`formulas for …` lists what it can find.")
    return Refusal(f"Your values aren't enough to find {what}. Formulas that find it:\n" +
                   "\n".join(n for _, n in needs[:5]), "Give the missing value(s), or `using \"…\"` one of these.")


# ── the other commands ───────────────────────────────────────────────────────
def _symbols_of(eq_text):
    import sympy
    from sympy.parsing.sympy_parser import parse_expr, standard_transformations, implicit_multiplication_application, \
        convert_xor
    tr = standard_transformations + (implicit_multiplication_application, convert_xor)
    if eq_text.count("=") != 1:
        raise Refusal(f"“{eq_text}” isn't one equation.", 'Write it with one `=`, e.g. `"v = u + a*t"`.')
    lhs, rhs = eq_text.split("=")
    local = {n: sympy.Symbol(n, real=True) for n in re.findall(r"[A-Za-z_][A-Za-z_0-9]*", eq_text)
             if n not in ("sqrt", "sin", "cos", "tan", "log", "exp", "pi", "ln", "asin", "acos", "atan")}
    local.update({"pi": sympy.pi, "ln": sympy.log})
    try:
        return sympy.Eq(parse_expr(lhs, local_dict=local, transformations=tr),
                        parse_expr(rhs, local_dict=local, transformations=tr)), local
    except Exception:
        raise Refusal(f"I can't read the formula “{eq_text}”.", 'Use `*` for times and `^` for powers: `"E = 0.5*m*v^2"`.')


def _quoted(s):
    m = re.fullmatch(r"[\"“](.+)[\"”]", s.strip())
    return m.group(1) if m else None


def _rearrange(arg):
    import sympy
    m = re.fullmatch(r"(.+?)\s+for\s+(\S+)", arg.strip(), re.I)
    if not m:
        raise Refusal("Say which letter to make the subject.", '`rearrange "v = u + a*t" for t`')
    src, sym = m.group(1).strip(), m.group(2)
    eq_text = _quoted(src) or src
    if "=" not in eq_text:
        f = _formula_by(eq_text)
        if len(f) > 1:
            raise Refusal(f"“{eq_text}” fits {len(f)} formulas: " + "; ".join(f"“{x.name}”" for x in f[:4]) + ".",
                          "Use the full name in quotes.")
        f = f[0]
        raw = next((s for s in f.vars if s == sym or show_symbol(s) == sym), None)
        if raw is None:
            raise Refusal(f"“{f.name}” ({f.text}) has no {sym}.", "Its letters: " + ", ".join(show_symbol(s) for s in f.vars))
        exprs = f.solve_for(raw)
        if not exprs:
            raise Refusal(f"CUSTOM-Mx can't make {sym} the subject of {f.text}.")
        lines = [f"**Formula:** {f.name}: {f.text}"] + [f"**Rearranged for {sym}:** {sym} = {pretty(e)}" for e in exprs]
        return lines
    eq, local = _symbols_of(eq_text)
    if sym not in local:
        raise Refusal(f"“{eq_text}” has no {sym}.", "Letters in it: " + ", ".join(sorted(local)))
    sols = sympy.solve(eq, local[sym])
    if not sols:
        raise Refusal(f"{sym} can't be made the subject of {eq_text}.")
    return [f"**Formula:** {eq_text}"] + [f"**Rearranged for {sym}:** {sym} = {pretty(s)}" for s in sols]


def _substitute(arg):
    import sympy
    m = re.fullmatch(r"(.+?)\s+into\s+(.+)", arg.strip(), re.I | re.S)
    if not m:
        raise Refusal("Say the values and the formula.", '`substitute u = 0, a = 2, t = 5 into "v = u + a*t"`')
    eq_text = _quoted(m.group(2)) or m.group(2).strip()
    eq, local = _symbols_of(eq_text)
    vals, shown = {}, []
    for part in re.split(r"\s*;\s*|,(?!\d{3}\b)\s*|\s+and\s+", m.group(1).strip()):
        g = re.fullmatch(r"([A-Za-z_][A-Za-z_0-9]*)\s*=\s*(.+)", part.strip())
        if not g:
            raise Refusal(f"I can't read “{part.strip()}”.", "Write each value as `letter = number`, e.g. `t = 5`.")
        if g.group(1) not in local:
            raise Refusal(f"“{eq_text}” has no {g.group(1)}.", "Letters in it: " + ", ".join(sorted(local)))
        it = _value(g.group(2), g.group(1))
        si = it.raw * (it.unit.factor if it.unit else 1.0) + (it.unit.offset if it.unit else 0.0)
        vals[local[g.group(1)]] = si
        shown.append(f"{g.group(1)} = {it.text}" + (f" (= {fmt_num(si)} {si_label(it.unit.dims)})"
                                                    if it.unit and it.unit.factor != 1 else ""))
    left = sorted(str(s) for s in (eq.free_symbols - set(vals)))
    if len(left) > 1:
        raise Refusal(f"That leaves {len(left)} unknowns: {', '.join(left)}.", "Give all but one.")
    sub = eq.subs(vals)
    lines = [f"**Formula:** {eq_text}", "**Given:** " + ", ".join(shown)]
    if not left:
        ok = bool(sympy.simplify(sub.lhs - sub.rhs) == 0) if hasattr(sub, "lhs") else bool(sub)
        return lines + [f"**Check:** both sides {'are equal' if ok else 'are NOT equal'}."]
    x = sympy.Symbol(left[0], real=True)
    sols = [s for s in sympy.solve(sub, local[left[0]]) if s.is_real]
    if not sols:
        raise Refusal(f"No real value of {left[0]} satisfies that.")
    any_units = any(" (= " in s or re.search(r"[A-Za-z]", s.split("=", 1)[1]) for s in shown)
    note = " (in SI units)" if any_units else ""
    return lines + [f"**Result:** {left[0]} = " + " or ".join(fmt_num(float(s)) for s in sols) + note]


def _convert(arg):
    m = re.fullmatch(r"(.+?)\s+(?:to|into|in)\s+(\S+)", arg.strip(), re.I)
    if not m:
        raise Refusal("Say what to convert and to which unit.", "`convert 100 km/h to m/s`")
    it = _value(m.group(1), "value")
    u = parse_unit(m.group(2))
    if not u:
        raise Refusal(f"I don't know the unit “{m.group(2)}”.")
    if not it.unit or it.unit.dims != u.dims:
        raise Refusal(f"{it.text} can't be converted to {u.label}: they measure different things.")
    si = it.raw * it.unit.factor + it.unit.offset
    return [f"**Convert:** {it.text} = {fmt_num((si - u.offset) / u.factor, 6)} {u.label}"]


def _formulas_for(name):
    ms = {m for m in meanings(name) if m[0] != "@"}
    if not ms:
        raise _unknown(name)
    lines, seen = [], set()
    for f in list(library()) + list(books()):
        if any(_is_target(ms, f, q, r) for (q, r) in f.vars.values() if q != "@") and f.name not in seen:
            seen.add(f.name)
            lines.append(f"- {f.name}: {f.text}" + ("  *(OpenStax)*" if f.source != "library" else ""))
    if not lines:
        raise Refusal(f"CUSTOM-Mx has no formula that finds {name}.")
    more = f"\n*…and {len(lines) - 15} more.*" if len(lines) > 15 else ""
    return [f"**Formulas that find {name}:**"] + lines[:15] + ([more] if more else [])


def _what_is(name):
    ms = meanings(name)
    if not ms:
        raise _unknown(name)
    lines = [f"**“{name}” can mean:**"]
    for q, r in sorted(ms):
        unit = L.CONSTANTS[r][1] if q == "@" else (L.QUANTITIES[q]["unit"] or "no unit")
        ex = next((f for f in library() if any(v == (q, r) for v in f.vars.values())), None)
        lines.append(f"- {_describe(q, r)} — measured in {unit}" + (f"; e.g. in {ex.name}: {ex.text}" if ex else ""))
    return lines


# ── everyday phrasing → the exact form ──────────────────────────────────────
_LEAD = [(r"^(?:please\s+|can you\s+|could you\s+|kindly\s+)+", ""),
         (r"^(?:calculate|compute|work out|determine|evaluate|find out)\b", "find"),
         (r"^(?:what is|what's|what are|what will be|what would be|how much)\b(?=.+\b(?:given|if|when|where|with)\b)", "find"),
         (r"^how fast\b", "find speed"), (r"^how far\b", "find distance"), (r"^how long\b", "find time"),
         (r"^how high\b", "find height")]
_TAIL = re.compile(r"\s+(?:is|are|was|will be)\s+(?:needed|required|used|produced|dissipated|stored|transferred|"
                   r"developed|consumed|released|gained|lost)$|\s+of\s+(?:the|a|an|this|that)\s+.+$|\s+(?:does it|is it)\s+.+$", re.I)


def _article(s):
    """'the mass' → 'mass'; 'a = 2 m/s²' and 'a in m/s²' keep their a (it's a symbol there)."""
    m = re.match(r"(?:the|an?)\s+(?![=:]|in\s)(.+)", s, re.I)
    return m.group(1) if m and (s.lower().startswith("the ") or meanings(re.split(r"\s*[=:]\s*|\s+in\s+", m.group(1))[0])) else s


def canonical(cmd: str) -> str:
    """Fixed rewrites only (no model): 'calculate the power if voltage is 240 V and current is 5 A' →
    'find power given voltage = 240 V, current = 5 A'. Anything it can't make exact is left for the parser to refuse."""
    s = re.sub(r"\s+", " ", cmd.strip()).rstrip("?.! ")
    for pat, rep in _LEAD:
        s = re.sub(pat, rep, s, flags=re.I)
    if not re.match(r"find\b", s, re.I):
        return s
    s = re.sub(r"^find\s+(?:the\s+|a\s+|an\s+)", "find ", s, flags=re.I)
    m = re.match(r"(find .+?)\s+(?:given that|given|if|when|where|with)\s+(.+)$", s, re.I)
    if not m:
        return s
    head, rest = m.group(1), m.group(2)
    head = "find " + ", ".join(_TAIL.sub("", t.strip()) for t in re.split(r"\s*,\s*|\s+and\s+", head[5:]))
    using = ""
    u = re.search(r"\s+using\s+.+$", rest, re.I)
    if u:
        rest, using = rest[:u.start()], u.group(0)
    parts = []
    for part in re.split(r"\s*;\s*|,(?!\d{3}\b)\s*|\s+and\s+", rest):
        part = _article(part.strip())
        part = re.sub(r"\s+(?:is|of|equals|equal to|=|:)\s+(?=[-+]?\d)", " = ", part, count=1, flags=re.I)
        part = re.sub(r"\s*=\s*", " = ", part)
        parts.append(part)
    return f"{head} given {', '.join(parts)}{using}"


# ── "Make it exact": a question in everyday words → a command the student checks ───
@functools.lru_cache(maxsize=None)
def name_for(q, r=""):
    """A name this language reads back as exactly (q, r), in words a student would write: 'initial speed',
    'resistance', 'first temperature'. Every label a draft uses must come back unchanged when run."""
    if q == "@":
        return L.CONSTANTS[r][2]
    base = L.QUANTITIES[q]["name"]
    if not r:
        tries = [base, q]
    else:
        state = q in ("temperature", "pressure", "volume")       # a gas going from state 1 to state 2
        say = {"1": "initial", "2": "final"}.get(r, r) if state else _ROLE_SAY.get(r, r)
        tries = [f"{say} {base}", f"{_ROLE_SAY.get(r, r)} {base}", f"{base} ({say})", f"{r} {base}"]
    if q == "gravitational field strength" and not r:
        return "g"                                   # the constant g, given a value of the question's own
    dims = L.QUANTITIES[q]["dims"]
    for t in tries:
        ms = meanings(t)
        if (q, r) in ms and all(m == (q, r) or m[0] == "@" or L.QUANTITIES[m[0]]["dims"] != dims
                                or (E.related(m[0], q) and m[1] == r) for m in ms):
            return t
    symbols, _n, _r = _tables()
    for s in sorted(symbols, key=lambda s: (len(s), s)):
        if symbols[s] == {(q, r)}:
            return s
    return next((t for t in tries if (q, r) in meanings(t)), tries[0])


def _value_text(it):
    """The number as the question wrote it, if this language reads it back the same; else plainly."""
    t = E.clean(it.text.strip())
    try:
        back = E.givens(t)
        if len(back) == 1 and back[0].pos == 0 and len(back[0].text) == len(t) and back[0].raw == it.raw \
                and (back[0].unit.label if back[0].unit else None) == (it.unit.label if it.unit else None):
            return t
    except Exception:
        pass
    num = "%.10g" % it.raw
    if it.unit and E._CURRENCY.search(it.unit.label):
        return f"{it.unit.label} {num}"
    return f"{num} {it.unit.label}" if it.unit else num


def _split(label):
    q, _, r = label.partition(":")
    return q, r


def _agrees(result, want):
    vals = result.get("values") or []
    return bool(result.get("ok") and vals and len(vals) >= len(want) and
                all(abs(a - b) <= 1e-6 * max(abs(a), abs(b), 1e-300) for a, b in zip(vals, want)))


def draft(text: str, labels=None):
    """The question as a command, for the student to check before it runs — or None. Code copies every number
    exactly; CUSTOM-Mx's own reading of the words (or, with `labels`, the brain's) only says what each number is.
    → {"ok", "command", "by": "rules" | "brain" | "maths", "left_out": [numbers the reading didn't use]}"""
    text = re.sub(r"\s+", " ", (text or "").strip())
    if not text or len(text) > 1500:
        return None
    t = E.clean(text)
    items = E.givens(t)
    if not any(it.unit is not None for it in items):            # no units: an equation or a sum, not physics
        from . import algebra
        bare = re.sub(r"^(?:please\s+)?(?:solve|find|calculate|work out|evaluate)\s*:?\s*", "", text, flags=re.I)
        if algebra.solve_math(bare):
            return {"ok": True, "command": "solve " + bare, "by": "maths", "left_out": [], "check": [], "runs": True}
    try:
        r = E.solve_problem(text, labels=labels) if labels else E.solve_problem(text)
    except Exception:
        r = None
    if r and r.get("reading") and len(r["reading"]["numbers"]) == len(items):
        reading = r["reading"]
    elif labels and labels.get("asks"):                          # the brain's labels, even if they don't solve
        reading = {"numbers": [("extra" if v in (None, "skip") else v[0] + (":" + v[1] if v[1] else ""))
                               for v in (labels["items"].get(i) for i in range(len(items)))],
                   "asks": [labels["asks"][0] + (":" + labels["asks"][1] if labels["asks"][1] else "")], "facts": []}
    else:
        return None
    parts, left_out, done = [], [], set()
    for fact in reading.get("facts", []):
        if fact["label"] == "temperature change" and len(fact["uses"]) == 2:
            i, j = sorted(fact["uses"])                          # "from 20 °C to 80 °C": the student's own numbers
            parts += [f"{name_for('temperature', '1')} = {_value_text(items[i])}",
                      f"{name_for('temperature', '2')} = {_value_text(items[j])}"]
            done |= {i, j}
    for i, (it, lab) in enumerate(zip(items, reading["numbers"])):
        if i in done:
            continue
        if lab == "extra":
            left_out.append(it.text)
            continue
        q, rr = _split(lab)
        parts.append(f"{name_for(q, rr)} = {_value_text(it)}")
    for fact in reading.get("facts", []):
        if fact["label"] == "temperature change" and len(fact["uses"]) == 2:
            continue
        q, rr = _split(fact["label"])
        dims = L.QUANTITIES.get(q, {}).get("dims", NONE)
        unit = si_label(dims) if dims != NONE else ""
        parts.append(f"{name_for(q, rr)} = {'%.10g' % fact['value']}{' ' + unit if unit else ''}")   # "from rest"
    asks = [name_for(*_split(a)) for a in reading["asks"]]
    if not asks or not parts:
        return None
    command = f"find {', '.join(asks)} given {', '.join(parts)}"
    # The draft must give the reading's own answer when it runs. If the values alone allow another formula (orbital
    # speed for "escape velocity"), the draft names the one the question's words chose.
    want = (r.get("values") or [r.get("value")]) if r and r.get("reading") is reading else None
    got = run(command)
    if want and not _agrees(got, want) and reading.get("formulas") and len(asks) == 1:
        named = run(command + f' using "{reading["formulas"][-1]}"')
        if _agrees(named, want) or not got["ok"]:
            command, got = command + f' using "{reading["formulas"][-1]}"', named
    names = [p.split(" = ")[0] for p in parts]
    twice = sorted({n for n in names if names.count(n) > 1})
    notes = [f"two values are both called {n}" for n in twice]
    if want and got["ok"] and not _agrees(got, want):
        notes.append("this command gives a different answer from CUSTOM-Mx's own reading — check each value")
    return {"ok": True, "command": command, "by": "brain" if labels else "rules", "left_out": left_out,
            "check": notes, "runs": bool(got["ok"])}


# ── entry point ──────────────────────────────────────────────────────────────
def warm():
    """Build the name tables once (about 2 s), so the first command doesn't wait for them."""
    try:
        _tables()
    except Exception:
        pass



def run(command: str) -> dict:
    """One /CUSTOM-Mx command → {"ok", "markdown", "understood"}. Never raises."""
    raw = (command or "").strip()
    raw = re.sub(r"^/?custom-?mx\b\s*", "", raw, flags=re.I).strip()
    if not raw or raw.lower() in ("help", "?", "commands"):
        return {"ok": True, "markdown": HELP, "understood": ""}
    understood = ""
    try:
        exact = canonical(raw)
        understood = exact if exact.lower() != raw.lower() else ""
        _RUN.values = []
        lines = _dispatch(exact, raw)
        md = ([f"**Understood as:** `{understood}`"] if understood else []) + lines
        return {"ok": True, "markdown": "**Worked by CUSTOM-Mx**\n" + "\n".join(sup(l) for l in md),
                "understood": understood, "values": list(_RUN.values)}
    except Refusal as r:
        md = (f"**Understood as:** `{understood}`\n\n" if understood else "") + \
             f"**CUSTOM-Mx didn't run this.** {r.reason}" + (f"\n\n**Try:** {r.hint}" if r.hint else "")
        return {"ok": False, "markdown": md, "understood": understood}
    except Exception as e:                                          # a bug, not the student's fault
        return {"ok": False, "markdown": f"**CUSTOM-Mx couldn't run this** (an internal error: {type(e).__name__}).",
                "understood": ""}


_RUN = threading.local()     # the answers of the command this thread is running, in SI


def _dispatch(cmd, typed=""):
    low = cmd.lower()
    if re.match(r"find\b", low):
        lines, known = [], []
        steps = re.split(r"\s+then\s+", cmd, flags=re.I)
        for i, step in enumerate(steps):
            step = step.strip()
            if i and not re.match(r"find\b", step, re.I):
                step = "find " + step
            out, results = _find(step, known, typed)
            if len(steps) > 1:
                lines.append(f"**Part {i + 1}: {step}**")
            lines += out
            known += results
            _RUN.values.extend(it.value for it in results if it.kind == "derived")
        return lines
    m = re.match(r"(?:solve|simplify|factorise|factorize|expand|differentiate|integrate)\b", low)
    if m:
        from . import algebra
        r = algebra.solve_math(cmd if not low.startswith("solve ") else cmd[6:])
        if not r:
            raise Refusal("CUSTOM-Mx can't do that one exactly.",
                          "Write the equation plainly, e.g. `solve 2x + 5 = 17` or `solve x + y = 5, x - y = 1`.")
        return r["steps"]
    for word, fn in (("rearrange", _rearrange), ("substitute", _substitute), ("convert", _convert)):
        if low.startswith(word + " "):
            return fn(cmd[len(word) + 1:])
    m = re.match(r"make\s+(\S+)\s+the\s+subject\s+of\s+(.+)", cmd, re.I)
    if m:
        return _rearrange(f"{m.group(2)} for {m.group(1)}")
    m = re.match(r"formulas?\s+(?:for|that find|to find)\s+(.+)", cmd, re.I)
    if m:
        return _formulas_for(m.group(1).strip())
    m = re.match(r"(?:what is|what's|what does|meaning of|explain)\s+(.+?)(?:\s+mean)?$", cmd, re.I)
    if m:
        return _what_is(m.group(1).strip().strip('"“”'))
    raise Refusal("I don't know that command.",
                  "Start with `find`, `solve`, `rearrange`, `substitute`, `convert`, `formulas for` or `what is` — or type `help`.")
