"""Word problems: find what is given and what is asked, pick the formula (or a chain of two or three) that links
them, rearrange, substitute and compute. Returns worked steps, or None when it isn't sure — a confident wrong
answer is worse than none, because the tutor would then explain it.
"""
import math
import re
from dataclasses import dataclass, field

from . import chem
from . import library as L
from .formulas import library, books, pretty, show_symbol, sup
from .units import parse_unit, unit_after, si_label, fmt_num, NONE, Unit, PREFIX


def _rx(words):
    words = sorted({w.lower() for w in words if w}, key=len, reverse=True)
    if not words:
        return None
    return re.compile(r"(?<![a-z0-9])(" + "|".join(re.escape(w) for w in words) + r")(?![a-z0-9])")


QWORDS = {n: _rx(q["words"]) for n, q in L.QUANTITIES.items()}
RWORDS = {r: _rx(w.split("|")) for r, w in L.ROLE_WORDS.items()}
OPPOSITE = {}
for a, b in [("initial", "final"), ("1", "2"), ("primary", "secondary"), ("in", "out"), ("incidence", "refraction"),
             ("hot", "cold"), ("sync", "rotor"), ("eyepiece", "objective"), ("peak", "rms"), ("line", "phase"),
             ("cathode", "anode"), ("collector", "base"), ("feedback", "input"), ("a", "b"), ("air gap", "mech")]:
    OPPOSITE[a], OPPOSITE[b] = b, a

# A specific quantity counts as its general kind when matching a question ("energy" asked, "heat" formula).
FAMILY = {"heat": "energy", "work": "energy", "kinetic energy": "energy", "potential energy": "energy",
          "photon energy": "energy", "binding energy": "energy", "work function": "energy",
          "weight": "force", "friction": "force", "upthrust": "force", "centripetal force": "force", "load": "force",
          "effort": "force", "normal reaction": "force", "wave speed": "speed", "emf": "voltage",
          "stopping potential": "voltage", "electric potential": "voltage", "inductive reactance": "reactance",
          "capacitive reactance": "reactance", "length": "distance", "magnetic path length": "length",
          "centripetal acceleration": "acceleration", "gravitational field strength": "acceleration",
          "lens power": "power", "years": "time"}
# What the brain may call a length: "0.05 m from the wire" is the r in B = μ0 I / 2πr. (Not diameter: that's 2r.)
SPAN = {"distance", "length", "radius", "height", "width", "side", "magnetic path length", "slant height",
        "base length", "screen distance", "object distance", "image distance", "extension"}


_SAME_ROLES = [{"in", "primary"}, {"out", "secondary"}]


def same_role(a, b):
    """Roles that mean the same thing: a transformer's "input voltage" is its primary voltage."""
    return a == b or any({a, b} == pair for pair in _SAME_ROLES)


def family(q):
    return FAMILY.get(q, q)


def related(a, b):
    return a == b or family(a) == family(b) or family(a) == b or a == family(b)


SAME_DIMS = {}
for _n, _q in L.QUANTITIES.items():
    SAME_DIMS.setdefault(_q["dims"], []).append(_n)


@dataclass
class Item:
    """A number the engine can use: given in the question, implied by its wording, a constant, or worked out."""
    raw: float = 0.0
    unit: Unit = None
    text: str = ""
    pos: int = -1
    symbol: str = ""
    left: str = ""
    right: str = ""
    kind: str = "given"                         # given | implied | constant | derived
    quantity: str = ""
    role: str = ""
    value: float = None                         # internal value (implied / constant / derived)
    work: list = field(default_factory=list)    # steps that produced a derived value
    label: str = ""
    uses: frozenset = frozenset()               # explicit givens behind a derived value
    hint: object = None                         # the brain's reading: (quantity, role) or "skip"
    reads: dict = field(default_factory=dict)   # derived values: {id(given): "quantity:role"} behind them
    via: tuple = ()                             # derived values: the formulas behind them, in the order used
    facts: tuple = ()                           # derived values: facts the wording implied behind them ("from rest")

    @property
    def dims(self):
        return self.unit.dims if self.unit else NONE

    def si(self, quantity: str) -> float:
        if self.value is not None:
            return self.value
        v = self.raw
        if self.unit:
            v = v * self.unit.factor + (0.0 if quantity == "temperature change" else self.unit.offset)
        acc = L.QUANTITIES[quantity]["accept"]
        return v * acc.get(self.dims, 1.0)


# ── reading the question ──────────────────────────────────────────────────
_SUPMAP = str.maketrans({"⁰": "0", "¹": "1", "²": "2", "³": "3", "⁴": "4", "⁵": "5", "⁶": "6", "⁷": "7", "⁸": "8",
                         "⁹": "9", "⁻": "-", "₀": "0", "₁": "1", "₂": "2", "₃": "3", "₄": "4", "₅": "5", "₆": "6",
                         "₇": "7", "₈": "8", "₉": "9", " ": " ", "−": "-", "–": "-", "μ": "µ"})


_WORDNUM = {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "eight": 8, "ten": 10, "twelve": 12, "sixteen": 16}


def clean(text: str) -> str:
    s = text or ""
    s = re.sub(r"([⁰¹²³⁴⁵⁶⁷⁸⁹⁻]+)", lambda m: "^" + m.group(1), s)       # 10⁻³ → 10^-3, m² → m^2
    s = s.translate(_SUPMAP).replace("º", "°")                          # "35.0ºC": an ordinal sign typed as degrees
    s = re.sub(r"\b(two|three|four|five|six|eight|ten|twelve|sixteen)(?=[- ]poles?\b)",
               lambda m: str(_WORDNUM[m.group(1).lower()]), s, flags=re.I)      # "four-pole" → "4-pole"
    s = re.sub(r"\s+", " ", s)
    return s.strip()


_NUM = re.compile(r"(?<![\w.^/')])(?<!\^-)(?<!\^\()(?<!\^\(-)(?P<sign>-)?(?P<int>\d{1,3}(?:,\d{3})+|\d+)(?P<frac>\.\d+)?"
                  r"(?:\s*(?:[x×*]|\\times)\s*10\s*\^?\s*\(?\s*(?P<e1>[-+]?\d+)\s*\)?|[eE](?P<e2>[-+]?\d+)(?![a-zA-Z]))?")
_POWER = re.compile(r"\s*\^\s*\(?\s*([-+]?\d+)\s*\)?")
_SYM_BEFORE = re.compile(r"(?P<sym>[A-Za-zα-ωΑ-Ωµ][A-Za-z0-9_α-ωΑ-Ωµ']{0,7})\s*(?:\([^()]{1,12}\))?\s*(?:=|≈)\s*$")
_CURRENCY = re.compile(r"(GH₵|GHS|GHC|₵|\$|£|€|USD)\s*$")
_SKIP_LEFT = re.compile(r"\b(example|question|fig|figure|table|slide|page|chapter|section|step|exercise|part|no|q|"
                        r"unit|lecture|week|class|form|grade|level|year)\s*\.?\s*$", re.I)
_STOP_WORDS = {"the", "a", "an", "of", "is", "was", "are", "were", "and", "with", "has", "have", "its", "it"}


_LINKS = {"at", "of", "to", "and", "for", "from", "with", "is", "was", "are", "=", "about", "approximately", "around",
          "into", "through", "over", "under", "in", "on", "has", "have", "had", "its", "their", "a", "an", "the"}


def _context(text, start, end):
    left = text[max(0, start - 70):start]
    left = re.split(r"[.;?!]\s", left)[-1]
    right = text[end:end + 80]
    right = re.split(r"[.;?!,]\s|[.;?!,]$", right)[0]
    nxt = re.search(r"(?<![\w.])\d", right)
    if nxt:                                           # "50 Hz induction motor runs at 960 rpm": "runs at" is the rpm's
        words = right[:nxt.start()].split()
        cut = [i for i, w in enumerate(words) if w.lower() in ("and", "while", "whereas", "but")]
        if cut:                                       # "1200 turns and the secondary has 60": "secondary" is the 60's
            words = words[:cut[-1]]
        while words and words[-1].lower() in _LINKS:
            words.pop()
        right = " " + " ".join(words)
    return left.lower(), right.lower()


def givens(text: str) -> list:
    out = []
    for m in _NUM.finditer(text):
        start, end = m.start(), m.end()
        before = text[:start]
        if _SKIP_LEFT.search(before) and not _SYM_BEFORE.search(before):
            continue
        ordinal = re.match(r"(st|nd|rd|th)\s+term\b", text[end:])          # "the 10th term" → n = 10
        if re.match(r"\s*(st|nd|rd|th)\b", text[end:]) and not ordinal:     # "1st", "2nd" — other ordinals
            continue
        if re.match(r"[A-Za-z]", text[end:end + 1]) and not ordinal:         # "2x", "3V1" glued to letters
            u, _ = unit_after(text[end:])
            if not u:
                continue
        num = float(m.group("int").replace(",", "") + (m.group("frac") or ""))
        if m.group("sign"):
            num = -num
        ex = m.group("e1") or m.group("e2")
        try:
            if ex:
                num *= 10 ** int(ex)
            else:
                pw = _POWER.match(text, end)
                if pw:
                    num = num ** int(pw.group(1))
                    end = pw.end()
        except OverflowError:
            continue                                    # "94^239Pu" is an isotope, not a number
        unit, used = unit_after(text[end:])
        if not unit and re.match(r"-[A-Za-zΩµ°%]", text[end:end + 2]):        # "50-Hz", "415-V"
            unit, used = unit_after(text[end + 1:])
            used = used + 1 if unit else 0
        cur = _CURRENCY.search(before)
        if cur:
            cu = parse_unit(cur.group(1))
            tail = re.match(r"\s*(?:per|/)\s*([A-Za-z][\w/^]*)", text[end:])
            per = parse_unit(tail.group(1)) if tail else None
            if per:
                unit = Unit(cu.factor / per.factor, tuple(a - b for a, b in zip(cu.dims, per.dims)), 0.0,
                            f"{cur.group(1)}/{tail.group(1)}")
                used = tail.end()
            else:
                unit, used = Unit(cu.factor, cu.dims, 0.0, cur.group(1)), 0
        end_all = end + used
        if not unit and re.fullmatch(r"(19|20)\d\d", m.group("int")) and re.search(r"\b(in|since|year|of)\s*$", before):
            continue                                                         # a year, not a quantity
        sym = _SYM_BEFORE.search(before)
        symbol = ""
        if sym:
            s = sym.group("sym")
            if len(s) <= 4 or re.search(r"[\d_]", s) or re.match(r"[α-ωΑ-Ωµ]", s):
                if s.lower() not in _STOP_WORDS:
                    symbol = s
        left, right = _context(text, start, end_all)
        if out:                                       # words before the previous number describe that one
            gap = start - (out[-1].pos + len(out[-1].text))
            if 0 <= gap < len(left):
                left = left[len(left) - gap:]
        if ordinal:
            left, right, unit, end_all = "number of terms ", " term", None, end + ordinal.end()
        shown = re.sub(r"(?<=\d)-(?=[A-Za-zΩµ°%])", " ", text[start:end_all].strip())     # "50-Hz" → "50 Hz"
        out.append(Item(raw=num, unit=unit, text=shown, pos=start, symbol=symbol,
                        left=left, right=right))
    return out


def implied(text: str, items: list) -> list:
    low = text.lower()
    out = []
    for pattern, spec, value in L.IMPLIED:
        m = re.search(pattern, low)
        if not m:
            continue
        q, _, role = spec.partition(":")
        out.append(Item(kind="implied", quantity=q, role=role, value=value, text=m.group(0), label=m.group(0)))
    temps = [it for it in items if it.unit and it.unit.dims == L.QUANTITIES["temperature"]["dims"]]
    if len(temps) >= 2:
        a, b = temps[0], temps[1]
        d = abs(b.raw * b.unit.factor - a.raw * a.unit.factor)
        unit = "°C" if a.unit.offset else "K"
        out.append(Item(kind="derived", quantity="temperature change", value=d, label="ΔT",
                        work=[f"**Temperature change:** ΔT = {fmt_num(max(a.raw, b.raw))} − {fmt_num(min(a.raw, b.raw))} "
                              f"= {fmt_num(d)} {unit}"], uses=frozenset({id(a), id(b)})))
    chemistry = re.search(r"\b(mol|moles?|molar|mass|grams?|concentration|relative|g/mol|solution)\b", text, re.I)
    for f in (chem.formulas_in(text) if chemistry else ()):          # not "neglect the iron loss" → M(Fe)
        mm = chem.molar_mass(f)
        if mm:
            out.append(Item(kind="derived", quantity="molar mass", value=mm[0] / 1000, label=f"M({f})",
                            work=[f"**Molar mass:** {mm[1]}"]))
    poles = _poles_inferred(text, items)
    if poles:
        out.append(poles)
    paths = _parallel_paths(text, items)
    if paths:
        out.append(paths)
    return out


def _parallel_paths(text, items):
    """A DC armature's parallel paths, which questions leave to the winding: wave → 2, lap → as many as poles."""
    low = text.lower()
    if re.search(r"\bwave[- ]?(wound|winding|connected)\b", low):
        return Item(kind="derived", quantity="parallel paths", value=2.0, label="A",
                    work=["**Parallel paths:** a wave winding always has 2 parallel paths"])
    if re.search(r"\blap[- ]?(wound|winding|connected)\b", low):
        p = next((it for it in items if it.unit is None and re.match(r"\s*-?\s*poles?\b", it.right)), None)
        if p:
            return Item(kind="derived", quantity="parallel paths", value=p.raw, label="A",
                        work=[f"**Parallel paths:** a lap winding has as many parallel paths as poles: A = {fmt_num(p.raw)}"])
    return None


def _poles_inferred(text, items):
    """An induction motor's speed and supply frequency but no pole count: the lecturer expects the pole number whose
    synchronous speed (120f/p) is just above the running speed — as the textbooks do ("1440 rev/min → 1500 → 4 poles")."""
    low = text.lower()
    if "induction" not in low or re.search(r"\bpoles?\b|-pole", low):
        return None
    f = next((it for it in items if it.unit and it.unit.label in ("Hz", "kHz") and it.unit.dims == (0, 0, -1, 0, 0, 0, 0, 0, 0)), None)
    n = next((it for it in items if it.unit and it.unit.label.replace(" ", "") in ("rpm", "rev/min", "r/min", "rev/s", "rps")), None)
    if not f or not n:
        return None
    fz, nr = f.raw * f.unit.factor, n.raw * n.unit.factor * 60          # Hz, rpm
    for p in (2, 4, 6, 8, 10, 12, 16, 24):
        ns = 120 * fz / p
        if ns < nr:
            break
        best = (p, ns)
    else:
        return None
    if "best" not in locals() or best[1] <= nr or (best[1] - nr) / best[1] > 0.1:
        return None                                # slip over 10%: not a running motor; don't guess
    p, ns = best
    return Item(kind="derived", quantity="poles", value=float(p), label="p",
                work=[f"**Poles:** none given, so take the synchronous speed just above {fmt_num(nr)} rev/min: "
                      f"120 × {fmt_num(fz)} / {p} = {fmt_num(ns)} rev/min, a {p}-pole machine"],
                uses=frozenset())                 # choosing the pole count is its own deduction


@dataclass
class Target:
    quantity: str = ""
    role: str = ""
    symbol: str = ""
    unit: Unit = None
    phrase: str = ""


_CUE = re.compile(r"\b(find|calculate|determine|compute|work out|what is|what's|what are|what was|what will be|"
                  r"what would be|how much|how many|how long|how far|how fast|how high|how heavy|evaluate|obtain|"
                  r"estimate|deduce|solve for|express|show that|give)\b", re.I)
_HOW = [(r"\bhow long\b(?!\s+(is|was|are|were|must|should)\s+the)", "time"), (r"\bhow far\b", "distance"),
        (r"\bhow fast\b", "speed"), (r"\bhow high\b", "height"), (r"\bhow heavy\b", "mass"),
        (r"\bhow much time\b", "time"), (r"\bhow long is\b|\bhow long was\b", "length")]
_HOW_MANY = {"moles": "amount", "mole": "amount", "mol": "amount", "turns": "turns", "electrons": "particles",
             "photons": "particles", "atoms": "particles", "molecules": "particles", "particles": "particles",
             "ions": "particles", "nuclei": "particles", "years": "years", "terms": "number of terms",
             "sides": "sides", "generations": "generations", "colours": "colours", "colors": "colours",
             "seconds": "time", "minutes": "time", "hours": "time", "joules": "energy", "coulombs": "charge",
             "bits": "data size", "bytes": "data size", "pixels": "pixels", "poles": "poles", "cells": "total cells"}


QROLES = {}
for _f in L.FORMULAS:
    for _q in _f["vars"].values():
        if not _q.startswith("@") and ":" in _q:
            _a, _, _b = _q.partition(":")
            QROLES.setdefault(_a, set()).add(_b)


def find_targets(text: str) -> list:
    """What the question asks for: one target per part ("find the current and the power" → two)."""
    phrases = []
    text = re.sub(r"\b(p\.u|e\.m\.f|p\.d|s\.t\.p|r\.t\.p|r\.m\.s|a\.c|d\.c)\.", lambda m: m.group(1).replace(".", ""), text,
                  flags=re.I)                    # "0.65 p.u." must not end a sentence
    listing = False                              # inside "Calculate: ; part ; part": bullet parts of one question
    asked = False                                # a question word has appeared: "(a) …", "(b) …" are its parts
    for sent in re.split(r"(?<=[.!?])\s+|\(\s*(?=[a-h]\s*\))", text):
        cue = _CUE.search(sent)
        if listing and sent.lstrip().startswith(";"):
            phrases += [p for p in sent.split(";") if p.strip()]
            continue
        if asked and re.match(r"\s*[a-h]\s*\)", sent):
            part = re.sub(r"^\s*[a-h]\s*\)\s*", "", sent)
            cue_in = _CUE.search(part)
            phrases.append(part[cue_in.start():] if cue_in else part)
            continue
        asked = asked or bool(cue)
        listing = False
        if not cue or re.match(r"\s*\(?\s*(take|use|assume|given|where|let)\b", sent, re.I):
            continue
        listing = bool(re.search(r":\s*;", sent[cue.start():]))
        for part in re.split(r"\(\s*[b-h]\s*\)|\b[b-h]\)\s|;|\band (?=(?:the|its|hence|also)\b)", sent[cue.start():]):
            if part and part.strip():
                phrases.append(part)
    if not phrases:
        q = [s for s in re.split(r"(?<=[.!?])\s+", text) if s.strip().endswith("?")]
        phrases = q[-1:]
    out = []
    for ph in phrases:
        t = _target_of(ph)
        if not t:
            continue
        if any(t.quantity == o.quantity and t.role == o.role and t.symbol == o.symbol for o in out):
            return []    # the same quantity asked twice ("…at start", "…with the resistors in"): conditions we can't tell apart
        out.append(t)
    return out


def _target_of(phrase: str):
    low = phrase.lower()
    t = Target(phrase=phrase)
    m = re.search(r"\b(?:in|to)\s+(?:units of\s+)?([A-Za-zΩµ°%₵$£€][^\s,;?]*(?:\s*/\s*[^\s,;?]+)?)\s*[.?]?\s*$", phrase)
    if m:
        u = parse_unit(m.group(1).rstrip("."))
        if u:
            t.unit = u
    sym = re.search(r"\b(?:find|calculate|determine|evaluate|work out|what is|solve for)\s+(?:the value of\s+)?"
                    r"([A-Za-zα-ωΑ-Ωµ][A-Za-z0-9_]{0,4})(?=\s*[.,?;]|\s*$|\s+(?:in|if|when|for|given)\b)", phrase)
    if sym and (len(sym.group(1)) <= 2 or re.search(r"[\d_]", sym.group(1))) and sym.group(1).lower() not in ("it", "a", "an"):
        t.symbol = sym.group(1)
    for pattern, q in _HOW:
        if re.search(pattern, low):
            t.quantity = q
            break
    if not t.quantity:
        hm = re.search(r"\bhow many\s+(\w+)", low)
        if hm and hm.group(1) in _HOW_MANY:
            t.quantity = _HOW_MANY[hm.group(1)]
    where = -1
    if not t.quantity:
        best = None                                   # the first quantity named after the cue ("find the force on…")
        for name, rx in QWORDS.items():
            if rx is None:
                continue
            for mm in rx.finditer(low):
                key = (-mm.start(), len(mm.group(1)))
                if best is None or key > best[0]:
                    best = (key, name, mm.start())
        if best:
            t.quantity, where = best[1], best[2]
    if not t.quantity and not t.symbol:
        return None
    if where >= 0:                                    # "final velocity", "new pressure", "voltage across the secondary"
        word = QWORDS[t.quantity].match(low, where) if t.quantity in QWORDS and QWORDS[t.quantity] else None
        # up to the end of the quantity's own word, so "rotor loss" counts as a role phrase
        before, after = low[max(0, where - 25):(word.end() if word else where)], low[where:where + 45]
        allowed = QROLES.get(t.quantity, set())
        # nearest first; at the same place the longer phrase wins ("in the armature conductors" over "in the armature")
        hits = [(len(before) - mm.end(), -len(mm.group(1)), r) for r, rx in RWORDS.items() if rx and r in allowed
                for mm in rx.finditer(before)]
        if not hits:
            hits = [(mm.start() + 30, -len(mm.group(1)), r) for r, rx in RWORDS.items() if rx and r in allowed
                    for mm in rx.finditer(after) if r not in ("final", "2", "initial", "1") or mm.start() < 20]
        if hits:
            t.role = sorted(hits)[0][2]
    return t


# ── matching numbers to a formula's variables ─────────────────────────────
def _nearest_role(item, roles):
    best = None
    for r in roles:
        rx = RWORDS.get(r)
        if not rx:
            continue
        for mm in rx.finditer(item.left):
            d = len(item.left) - mm.end()
            if best is None or d < best[0]:
                best = (d, r)
        mm = rx.search(item.right)
        if mm and mm.start() < 14:
            d = mm.start() + 1
            if best is None or d < best[0]:
                best = (d, r)
    return best[1] if best and best[0] < 40 else ""


def _word_hit(quantity, ctx):
    rx = QWORDS.get(quantity)
    if rx and rx.search(ctx):
        return True
    fam = family(quantity)
    return fam != quantity and QWORDS.get(fam) is not None and bool(QWORDS[fam].search(ctx))


_PER_SECOND = (0, 0, -1, 0, 0, 0, 0, 0, 0)          # Hz, rpm, rad/s: the unit itself says which one it is


def pair_score(item, sym, quantity, role, formula_roles, formula_quantities):
    if item.kind in ("implied", "derived"):
        if item.quantity != quantity:
            return None
        if role and item.role and not same_role(item.role, role):
            return None
        return 6.0 + (2.0 if role and same_role(item.role, role) else 0.0)
    q = L.QUANTITIES[quantity]
    if item.hint is not None:                 # the brain read this number: its reading decides what it can be
        near = related(item.hint[0], quantity) if item.hint != "skip" else False
        near = near or (item.hint != "skip" and item.hint[0] in SPAN and quantity in SPAN)
        if item.hint == "skip" or not near or item.dims not in q["accept"]:
            return None
        hq, hr = item.hint
        if role and hr and not same_role(hr, role):
            return None
        return 8.0 + (2.0 if hq == quantity else 0.0) + (1.0 if role and same_role(hr, role) else 0.0)
    sym_hit = 0
    if item.symbol:
        names = {sym, show_symbol(sym), sym.replace("_", "")}
        if item.symbol in names:
            sym_hit = 6
        elif item.symbol.lower() in {n.lower() for n in names}:
            sym_hit = 4
    dims_ok = item.dims in q["accept"]
    if not dims_ok and not (item.unit is None and sym_hit):
        return None
    label = item.unit.label.replace(" ", "") if item.unit and item.unit.label else ""
    if label and q["dims"] == _PER_SECOND and q["hints"] and label not in q["hints"] and not sym_hit and any(
            label in L.QUANTITIES[o]["hints"] for o in SAME_DIMS.get(q["dims"], []) if o != quantity):
        return None                          # "50 Hz" is a frequency, not a speed of rotation
    ctx = item.left[-45:] + " | " + (item.unit.label.lower() if item.unit and item.unit.label else "") + " " + item.right
    s = 1.0 + sym_hit
    word = _word_hit(quantity, ctx)
    if word:
        s += 3
    else:
        rivals = [o for o in SAME_DIMS.get(q["dims"], []) if not related(o, quantity) and _word_hit(o, ctx)]
        if rivals and not sym_hit:
            s -= 2.5
    if item.unit and item.unit.label and item.unit.label.replace(" ", "") in q["hints"]:
        s += 1.5
    if role or formula_roles:
        # Any other role of this quantity counts against it: "runs at 960 rpm" is a rotor speed, not the synchronous
        # one; "friction and windage loss is 0.8 kW" is not the air-gap power.
        others = QROLES.get(quantity, set()) if role else set()
        r = _nearest_role(item, formula_roles | others | ({role, OPPOSITE[role]} if role in OPPOSITE else {role} if role else set()))
        if role and same_role(r, role):
            s += 2.5
        elif r and role and (r == OPPOSITE.get(role) or ((r in formula_roles or r in others) and not same_role(r, role))):
            if not sym_hit:
                return None                  # "the stator losses are 1.5 kW" can't be the output power
            s -= 3.0
        elif r and not role and r in formula_roles:
            s -= 1.0
    if q["dims"] == NONE and not sym_hit and not word:
        return None                          # a bare number needs words saying what it is
    return s


@dataclass
class Candidate:
    formula: object
    target: str
    assign: dict
    score: float
    value: float = None
    note: str = ""
    expr: object = None


def _constant_item(name):
    c = L.CONSTANTS[name]
    u = parse_unit(c[1]) if c[1] != "1" else None
    return Item(kind="constant", quantity="@" + name, value=c[0], unit=u, label=c[2], text=c[2])


def assignments(f, target_sym, pool, text_low, limit=6):
    others = [s for s in f.vars if s != target_sym]
    roles = {r for (q, r) in f.vars.values() if q != "@" and r}
    quantities = {q for (q, r) in f.vars.values() if q != "@"}
    cands = {}
    for s in others:
        q, role = f.vars[s]
        if q == "@":
            const = _constant_item(role)
            opts = [(2.0, const)]
            for it in pool:
                if it.kind != "given" or not const.unit or it.dims != const.unit.dims:
                    continue
                cwords = L.CONSTANTS[role][3]
                if (it.symbol and it.symbol in (s, show_symbol(s))) or (cwords and _rx(cwords.split("|")).search(it.left[-40:])):
                    opts.append((7.0, it))
            cands[s] = sorted(opts, key=lambda x: -x[0])
            continue
        opts = []
        for it in pool:
            sc = pair_score(it, s, q, role, roles, quantities)
            if sc is not None:
                opts.append((sc, it))
        if not opts:
            return []
        given_opts = [it for _, it in opts if it.kind == "given"]
        if len(given_opts) == 1 and L.QUANTITIES[q]["dims"] != NONE:
            opts = [(sc + 1.5 if it is given_opts[0] else sc, it) for sc, it in opts]   # the only mass in the question
        cands[s] = sorted(opts, key=lambda x: -x[0])[:6]
    order = sorted(others, key=lambda s: len(cands[s]))
    found = []

    def dfs(i, used, chosen, total, low_):
        if len(found) > 60:
            return
        if i == len(order):
            found.append((total, dict(chosen), low_))
            return
        s = order[i]
        for sc, it in cands[s]:
            if it.kind == "constant":
                mine = set()
            else:
                mine = {id(it)} | set(it.uses)
                if mine & used:
                    continue                     # never reuse a number, even inside a value worked out from it
            chosen[s] = it
            weakest = min(low_, sc) if it.kind == "given" else low_
            dfs(i + 1, used | mine, chosen, total + sc, weakest)
            del chosen[s]
    dfs(0, frozenset(), {}, 0.0, 99.0)
    found.sort(key=lambda x: -x[0])
    return found[:limit]


def _val(f, s, it):
    """The number substituted for variable `s`: in the quantity's internal units."""
    q, role = f.vars[s]
    if q != "@":
        return it.si(q)
    if it.kind == "constant" or it.value is not None:
        return it.value
    return it.raw * (it.unit.factor if it.unit else 1.0)


def evaluate(f, target_sym, assign):
    """The value of the target, the solved expression used and a note — or (None, None, '')."""
    exprs = f.solve_for(target_sym)
    if not exprs:
        return None, None, ""
    values = {f.syms[s]: _val(f, s, it) for s, it in assign.items()}
    tq, _ = f.vars[target_sym]
    spec = L.QUANTITIES.get(tq, {})
    angle = spec.get("dims") == NONE and spec.get("unit") == "rad"

    def run(vals):
        good = []
        for e in exprs:
            try:
                v = complex(e.subs(vals).evalf())
            except Exception:
                continue
            if not (math.isfinite(v.real) and math.isfinite(v.imag)) or abs(v.imag) > 1e-9 * max(1.0, abs(v.real)):
                continue
            good.append((v.real, e))
        return good
    good = run(values)
    note = ""
    if not good or (not spec.get("signed") and all(v < 0 for v, _ in good)):
        # Kinematics sign conventions: thrown upwards means a = −g. Try the acceleration the other way round.
        flip = {k: -v for k, v in values.items() if str(k) in ("a", "g")}
        if flip:
            alt = run({**values, **flip})
            if alt and any(v >= 0 for v, _ in alt):
                good, note = alt, "taking upwards as positive, so the acceleration is −g"
                for k in flip:
                    values[k] = flip[k]
    if not good:
        return None, None, ""
    if spec.get("signed"):
        v, e = good[0]
        return v, e, note
    pos = [(v, e) for v, e in good if v > 1e-15]
    if angle:
        pos = [(v, e) for v, e in pos if v <= math.pi + 1e-9] or pos
    if pos:
        v, e = min(pos, key=lambda x: x[0]) if angle or len(pos) > 1 else pos[0]
        return v, e, note
    v, e = good[0]
    return (abs(v), e, note) if v != 0 else (0.0, e, note)


def _relevant(target_q, depth=2):
    """Quantities within `depth` formulas of the target."""
    seen = {target_q, family(target_q)}
    frontier = set(seen)
    for _ in range(depth):
        nxt = set()
        for f in library():
            qs = {q for (q, r) in f.vars.values() if q != "@"}
            if qs & frontier or {family(q) for q in qs} & frontier:
                nxt |= qs
        nxt -= seen
        seen |= nxt
        frontier = nxt
    return seen


def _usable(f, low):
    if any(w in low for w in f.spec.get("excludes", ())):
        return False
    return not f.needs or any(w in low for w in f.needs)


def _explicit(items):
    return [it for it in items if it.kind == "given"]


def solve_for_target(target, pool, formulas, low, explicit):
    """Single-step candidates for one target."""
    out = []
    for f in formulas:
        if not _usable(f, low):
            continue
        for sym, (q, role) in f.vars.items():
            if q == "@":
                continue
            if target.symbol:
                if sym != target.symbol and show_symbol(sym) != target.symbol:
                    continue
            elif not related(q, target.quantity):
                continue
            if target.role and role and not same_role(role, target.role):
                continue
            if not target.role and role and any(q2 == q and not r2 for (q2, r2) in f.vars.values()):
                continue                         # "combined resistance" is R_T, not R_1 or R_2
            for total, assign, _weakest in assignments(f, sym, pool, low):
                v, e, note = evaluate(f, sym, assign)
                if v is None:
                    continue
                bonus = 2.0 if q == target.quantity else 0.0
                if target.role and not role and any(r2 == target.role for f2 in formulas for (q2, r2) in f2.vars.values() if q2 == q):
                    bonus -= 3.0                 # "useful output power" wants P_out, not just any P
                bonus += 1.5 if (target.role and same_role(role, target.role)) else 0.0
                bonus += 2.0 if f.source == "slide" else 0.0
                used = set()
                for it in assign.values():
                    if it.kind == "given":
                        used.add(id(it))
                    used |= set(it.uses)
                unused = [it for it in explicit if id(it) not in used and it.unit is not None and (it.dims != NONE or it.unit.label in ("%", "percent")) and it.hint != "skip"]
                score = total / max(1, len(assign)) * 2 + bonus + 1.5 * len(used) - 2.5 * len(unused) \
                    - 1.5 * sum(1 for it in assign.values() if it.kind == "derived")
                out.append(Candidate(f, sym, assign, score, v, note, e))
    return out


def derive(pool, target, formulas, low, rel):
    """Values worth working out first: quantities near the target that the givens pin down."""
    have = {(it.quantity, it.role) for it in pool if it.kind in ("derived", "implied")}
    stated = [it for it in pool if it.kind == "given"]
    new = {}
    for f in formulas:
        if not _usable(f, low):
            continue
        for sym, (q, role) in f.vars.items():
            # Not the target itself — but "a power" may be worked out on the way to "the output power".
            if q == "@" or q not in rel or (q, role) in have or (related(q, target.quantity) and (not target.role or same_role(role, target.role))):
                continue
            froles = {r for (_q, r) in f.vars.values() if r}
            if any((pair_score(it, sym, q, role, froles, set()) or 0) >= 3 for it in stated):
                continue                         # the question already gives this one
            for total, assign, weakest in assignments(f, sym, pool, low, limit=1):
                if weakest < 3:              # chains only where words say what each number is (not "the only kW")
                    continue                                     # chains only on clear matches
                v, e, note = evaluate(f, sym, assign)
                if v is None:
                    continue
                key = (q, role)
                score = total / max(1, len(assign))
                if key in new and new[key][0] >= score:
                    continue
                uses = set()
                for it in assign.values():
                    if it.kind == "given":
                        uses.add(id(it))
                    uses |= set(it.uses)
                item = Item(kind="derived", quantity=q, role=role, value=v, label=show_symbol(sym),
                            uses=frozenset(uses), reads=_reads(f, assign), via=_via(f, assign),
                            facts=_facts(assign))
                earlier = [line for it in assign.values() if it.kind == "derived" for line in it.work]
                item.work = earlier + working(Candidate(f, sym, assign, score, v, note, e),
                                              heading=f"find {show_symbol(sym)} first")
                new[key] = (score, item)
    return [it for _, it in new.values()]


# ── showing the working ───────────────────────────────────────────────────
def _label(f, s):
    q, r = f.vars[s]
    if q == "@":
        return "gravitational field strength" if r == "g" else "extra"
    return q + (":" + r if r else "")


def _reads(f, assign):
    """How a solution read the question: {id(given number): "quantity:role"}, through any chain behind it."""
    out = {}
    for s, it in assign.items():
        if it.kind == "given":
            out[id(it)] = _label(f, s)
        out.update(it.reads)
    return out


def _is_fact(it):
    """A value the wording gave without a number: "from rest" (u = 0), two temperatures → ΔT, a molar mass."""
    return it.kind == "implied" or (it.kind == "derived" and not it.via)


def _facts(assign):
    out = []
    for it in assign.values():
        for x in ((it,) if _is_fact(it) else ()) + it.facts:
            if all(x is not y for y in out):
                out.append(x)
    return tuple(out)


def _via(f, assign):
    """The formulas a solution used, the chain's first."""
    names = []
    for it in assign.values():
        names += [n for n in it.via if n not in names]
    return tuple(names + [f.name] if f.name not in names else names)


def _value_label(quantity, value):
    """(number, unit) for a value in the quantity's internal units, as used in the substitution line."""
    q = L.QUANTITIES.get(quantity)
    if not q:
        return fmt_num(value), ""
    if q["accept"] != {q["dims"]: 1.0}:
        return fmt_num(value), (q["show"] if q["show"] not in ("%",) else "")
    if q["dims"] == NONE:
        return fmt_num(value), ""
    return fmt_num(value), _LABEL.get(quantity) or si_label(q["dims"])


# Quantities whose SI unit would mislead: a speed of rotation per second isn't "Hz" to a student.
_LABEL = {"rotational speed": "rev/s", "angular velocity": "rad/s", "heart rate": "/s", "breathing rate": "/s",
          "decay constant": "/s", "rate constant": "/s", "reaction rate": "/s", "activity": "Bq"}


def _also_in(quantity, value):
    """' (= 1000 rpm)' when students usually quote this quantity in another unit; '' otherwise."""
    q = L.QUANTITIES.get(quantity) or {}
    show = q.get("show")
    if not show or show in ("%", "°") or q.get("accept") != {q.get("dims"): 1.0}:
        return ""
    u = parse_unit(show)
    if not u or u.dims != q["dims"] or u.factor == 1:
        return ""
    return f" (= {fmt_num(value / u.factor)} {show.replace('^3', '³').replace('^2', '²')})"


def _plain(label):
    return label.replace(" ", "").replace("²", "^2").replace("³", "^3").replace("⁻¹", "^-1")


def _given_line(f, sym, it):
    name = show_symbol(sym)
    q, role = f.vars[sym]
    if it.kind == "constant":
        return f"{it.label} = {fmt_num(it.value)} {L.CONSTANTS[role][1].replace('^2', '²').replace('^-1', '⁻¹')}".strip()
    if it.kind in ("implied", "derived"):
        num, lab = _value_label(q, it.value)
        why = f" ({it.label})" if it.kind == "implied" else ""
        also = _also_in(q, it.value).replace(" (= ", " = ").rstrip(")") if it.kind == "derived" else ""
        return f"{name}{also} = {num} {lab}{why}".strip() if also else f"{name} = {num} {lab}{why}".strip()
    if q == "@":
        c = L.CONSTANTS[role]
        return f"{it.label or name} = {it.text}"
    num, lab = _value_label(q, it.si(q))
    shown = f"{name} = {it.text}"
    if it.unit is None or (it.unit.factor == 1 and not it.unit.offset and it.unit.dims == L.QUANTITIES[q]["dims"]
                           and _plain(it.unit.label) in (_plain(lab), "")):
        return f"{name} = {num} {lab}".strip() if it.unit is None else shown
    return f"{shown} = {num} {lab}".strip()


def working(c: Candidate, heading=""):
    import sympy
    f, sym = c.formula, c.target
    lines = []
    if heading:
        lines.append(f"**Step — {heading}:**")
    givens_line = ", ".join(_given_line(f, s, it) for s, it in c.assign.items()
                            if it.kind != "derived" or not it.work or "Molar mass" in it.work[0])
    if givens_line:
        lines.append(f"**Given:** {givens_line}")
    lines.append(f"**Formula:** {f.name}: {f.text}")
    solved = c.expr
    if not (f.lhs == f.syms[sym] and solved == f.rhs):
        lines.append(f"**Rearrange for {show_symbol(sym)}:** {show_symbol(sym)} = {pretty(solved)}")
    if c.note:
        lines.append(f"*Note: {c.note}.*")
    placeholders, names, direct = {}, {}, {}
    for i, (s, it) in enumerate(c.assign.items()):
        val = _val(f, s, it)
        if c.note and s in ("a", "g"):
            val = -abs(val)
        ph = sympy.Symbol(f"SUBST{i}")
        placeholders[f.syms[s]] = ph
        shown = fmt_num(val)
        names[f"SUBST{i}"] = direct[s] = f"({shown})" if val < 0 or "×" in shown else shown   # 0.2 / (5 × 10⁻⁴)
    if f.lhs == f.syms[sym] and solved == f.rhs:
        sub = pretty(f.raw_rhs, names=direct)     # already the subject: substitute into the formula as written
    else:
        sub = pretty(solved.xreplace(placeholders), names=names)
    lines.append(f"**Substitute:** {show_symbol(sym)} = {sub}")
    num, lab = _value_label(f.vars[sym][0], c.value)
    lines.append(f"**Result:** {show_symbol(sym)} = {num} {lab}".rstrip() + _also_in(f.vars[sym][0], c.value))
    return [sup(line) for line in lines]


def _display(quantity, value, target_unit, items):
    """The answer as a student expects to read it: a requested unit, the question's own units, or a tidy SI."""
    q = L.QUANTITIES.get(quantity, {})
    dims = q.get("dims", NONE)
    if q.get("show") == "%":
        return fmt_num(value * 100), "%"
    if q.get("show") == "°":
        return fmt_num(math.degrees(value)), "°"
    if target_unit and target_unit.dims == dims and not target_unit.offset:
        return fmt_num(value / target_unit.factor), target_unit.label
    if quantity in ("temperature", "temperature change"):
        if any(it.unit and it.unit.offset for it in items):
            return fmt_num(value - (273.15 if quantity == "temperature" else 0)), "°C"
        return fmt_num(value), "K"
    if q.get("accept") and q["accept"] != {dims: 1.0}:
        return fmt_num(value), (q["show"] or "")
    for it in items:                                      # the question's own unit for this kind of quantity
        if it.kind == "given" and it.unit and it.unit.dims == dims and it.unit.factor != 1 and not it.unit.offset \
                and it.unit.label and dims != NONE:
            return fmt_num(value / it.unit.factor), it.unit.label
    for it in items:                                      # cm given → area in cm², volume in cm³
        if it.kind == "given" and it.unit and it.unit.dims == (1, 0, 0, 0, 0, 0, 0, 0, 0) and it.unit.factor != 1:
            for n, sup in ((2, "²"), (3, "³")):
                if dims == (n, 0, 0, 0, 0, 0, 0, 0, 0):
                    return fmt_num(value / it.unit.factor ** n), it.unit.label + sup
    if q.get("show") and q["show"] not in ("%", "°"):
        u = parse_unit(q["show"])
        if u and u.dims == dims:
            return fmt_num(value / u.factor), q["show"].replace("^3", "³").replace("^2", "²")
    label = si_label(dims)
    if label in ("A", "V", "Ω", "W", "J", "N", "Pa", "Hz", "F", "H", "C", "T", "Wb", "S", "m", "s", "bit") and value:
        for p, k in (("G", 1e9), ("M", 1e6), ("k", 1e3), ("", 1), ("m", 1e-3), ("µ", 1e-6), ("n", 1e-9), ("p", 1e-12)):
            if abs(value) >= k * 0.9999:
                if (p, label) in (("k", "s"), ("M", "s"), ("G", "s"), ("k", "m")) and abs(value) < 1e5:
                    break
                return fmt_num(value / k), p + label
    return fmt_num(value), label


def _answer_line(target_label, quantity, value, target, items):
    num, lab = _display(quantity, value, target.unit, items)
    si_num, si_lab = _value_label(quantity, value)
    extra = ""
    if lab and si_lab and lab != si_lab and lab not in ("%", "°", "°C") and si_num != num:
        extra = f" ({si_num} {si_lab})"
    lab = lab.replace("^2", "²").replace("^3", "³").replace("^-1", "⁻¹")
    return f"{target_label} = {num} {lab}".rstrip() + extra


_CONDITION_DIMS = {L.QUANTITIES["temperature"]["dims"], L.QUANTITIES["pressure"]["dims"]}


def _condition(it):
    """'at 0 °C', 'at 25 °C and 1 atm': conditions a question states, not numbers it expects us to use."""
    return it.dims in _CONDITION_DIMS and bool(re.search(r"\b(at|and)\s*$", it.left))


def _leaves_out(c, explicit):
    """Does this candidate ignore a number the question describes ("efficiency is 75%")?"""
    used = set()
    for it in c.assign.values():
        if it.kind == "given":
            used.add(id(it))
        used |= set(it.uses)
    return any(id(it) not in used and it.unit is not None and not _condition(it) and _described(it) for it in explicit)


def _described(it):
    """The question says what this number is ("efficiency is 75%", "2 cm tall"): leaving it out means a misreading."""
    if it.hint not in (None, "skip"):
        return True
    label = it.unit.label.replace(" ", "") if it.unit and it.unit.label else ""
    if label and any(label in q["hints"] for q in L.QUANTITIES.values()):
        return True                          # "60 Hz" says it's a frequency
    ctx = it.left[-45:] + " | " + label.lower() + " " + it.right
    return any(rx is not None and rx.search(ctx) for rx in QWORDS.values())


def solve_problem(text: str, slide_formulas=(), labels=None) -> dict:
    """A worked solution for a word problem, or None. The hand-checked library first; the formulas imported from
    OpenStax textbooks only when it has no answer. `labels` (reader.read): the brain's reading of what each number
    is and what is asked — it replaces the rule-based reading of the words; the arithmetic stays here."""
    r = _solve(text, slide_formulas, tier2=False, labels=labels)
    if r is None and books():
        r = _solve(text, slide_formulas, tier2=True, labels=labels)
        if r:
            r["source"] = "OpenStax"
    return r


def _echoes(value, dims, explicit) -> bool:
    """The answer is just one of the given numbers, same kind of quantity, passed through (checked on 2,700 OpenStax
    problems: wrong each time)."""
    for it in explicit:
        if it.unit is None or it.unit.dims != dims:
            continue
        for v in (it.raw * it.unit.factor, it.raw * it.unit.factor + it.unit.offset):
            if v and abs(v - value) <= 1e-3 * abs(v):
                return True
    return False


def _solve(text: str, slide_formulas=(), tier2=False, labels=None) -> dict:
    text = clean(text)
    low = text.lower()
    targets = find_targets(text)
    items = givens(text)
    if labels:
        for i, it in enumerate(items):
            it.hint = labels["items"].get(i)
        if labels.get("asks"):
            q, r = labels["asks"]
            targets = [Target(quantity=q, role=r, unit=targets[0].unit if targets else None)]
    if not targets:
        return None
    explicit = _explicit(items)
    if not explicit:
        return None
    pool = items + implied(text, items)
    formulas = list(slide_formulas) + list(library()) + (list(books()) if tier2 else [])
    steps, answers, values, used_all, weakest = [], [], [], set(), 99.0
    reads, asked, used, facts = {}, [], [], []
    for target in targets[:4]:
        cands = solve_for_target(target, pool, formulas, low, explicit)
        chain_pool = pool
        if not cands or max(c.score for c in cands) < 8 or _leaves_out(max(cands, key=lambda c: c.score), explicit):
            rel = _relevant(target.quantity) if target.quantity else set()
            for _ in range(2):
                extra = derive(chain_pool, target, formulas, low, rel)
                if not extra:
                    break
                chain_pool = chain_pool + extra
                cands += solve_for_target(target, chain_pool, formulas, low, explicit)
                if cands and max(c.score for c in cands) >= 8:
                    break
        if not cands:
            return None
        cands.sort(key=lambda c: -c.score)
        best = cands[0]
        for c in cands[1:]:
            if c.score >= best.score - 1.0 and abs(c.value - best.value) > 0.01 * max(abs(best.value), 1e-12):
                return None                                            # two readings, two answers: not sure
        if best.value == 0 or _echoes(best.value, L.QUANTITIES.get(best.formula.vars[best.target][0], {}).get("dims"), explicit):
            return None              # 0, or a number the question already gave: on real textbook problems a misreading
        weakest = min(weakest, best.score)
        for it in best.assign.values():
            if it.kind == "given":
                used_all.add(id(it))
            used_all |= set(it.uses)
        for it in best.assign.values():
            if it.kind == "derived":
                for line in it.work:
                    if line not in steps:
                        steps.append(line)
        steps += working(best)
        reads.update(_reads(best.formula, best.assign))
        asked.append(_label(best.formula, best.target))
        used += [n for n in _via(best.formula, best.assign) if n not in used]
        facts += [x for x in _facts(best.assign) if all(x is not y for y in facts)]
        label = show_symbol(best.target)
        answers.append(_answer_line(label, best.formula.vars[best.target][0], best.value, target, items))
        values.append(best.value)
        pool = pool + [Item(kind="derived", quantity=best.formula.vars[best.target][0],
                            role=best.formula.vars[best.target][1], value=best.value, label=label)]
    unused = [it for it in explicit if id(it) not in used_all and it.unit is not None and (it.dims != NONE or it.unit.label in ("%", "percent")) and it.hint != "skip"
              and not _condition(it)]
    described = [it for it in unused if _described(it)]
    if described or len(unused) > 1 or (unused and weakest < 9):
        return None                         # the question gave numbers we never used: we've probably misread it
    steps.append("**Answer:** " + "; ".join(answers))
    # how CUSTOM-Mx read the question: every number in it → "quantity:role" ("extra" if unused), and what was asked
    reading = {"numbers": [reads.get(id(it), "extra") for it in items], "asks": asked, "formulas": used,
               "facts": [{"label": x.quantity + (":" + x.role if x.role else ""), "value": x.value, "why": x.label,
                          "uses": [i for i, it in enumerate(items) if id(it) in x.uses]} for x in facts]}
    return {"kind": "formula", "answer": "; ".join(answers), "value": values[0], "values": values, "steps": steps,
            "formulas": [], "confident": True, "reading": reading}
