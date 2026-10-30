"""
CUSTOM-SQE word problems: physics (electricity, mechanics, heat, waves, gases), money (interest, profit and loss,
discount, ratio, proportion, depreciation) and mensuration (areas and volumes).

How a word problem is read:
  - every number is read with its unit (200 W, 3 minutes, 20 µF, GHS 5000, 8%) and the words around it (radius,
    height, …);
  - then what is asked ("calculate the current", "how long", "how much is left");
  - then the rule that links them. Physics is worked in SI units, exactly.

Versions are the student's own sentence with new numbers, about the same size and roundness. The answer stays
as clean as the original's (a whole number stays whole; money stays in cedis and pesewas). Constants the question
gives (g = 10, c = 4200, π = 22/7) stay as given.
"""
from __future__ import annotations

import math
import random
import re
from dataclasses import dataclass
from fractions import Fraction
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import sympy as sp

from .core import Family, Item, Spec, like, new_value
from .text import exact, Question, fmt_num, fmt_sig

# ── units: what a unit measures and its size in SI ────────────────────────────────────────────────────────────

_U: Dict[str, Tuple[str, object]] = {}


def _unit(q, factor, *names):
    for n in names:
        _U[n] = (q, exact(factor))


_unit("power", 1, "W", "watt", "watts")
_unit("power", 1000, "kW", "kilowatt", "kilowatts")
_unit("power", 10 ** 6, "MW")
_unit("power", sp.Rational(1, 1000), "mW")
_unit("voltage", 1, "V", "volt", "volts")
_unit("voltage", 1000, "kV")
_unit("voltage", sp.Rational(1, 1000), "mV")
_unit("current", 1, "A", "amp", "amps", "ampere", "amperes")
_unit("current", sp.Rational(1, 1000), "mA")
_unit("current", sp.Rational(1, 10 ** 6), "µA", "μA", "uA")
_unit("resistance", 1, "Ω", "ohm", "ohms")
_unit("resistance", 1000, "kΩ", "kohm", "kohms", "kilohm", "kilohms")
_unit("resistance", 10 ** 6, "MΩ")
_unit("energy", 1, "J", "joule", "joules")
_unit("energy", 1000, "kJ")
_unit("energy", 10 ** 6, "MJ")
_unit("energy", 3600000, "kWh", "units")
_unit("charge", 1, "C", "coulomb", "coulombs")
_unit("charge", sp.Rational(1, 1000), "mC")
_unit("charge", sp.Rational(1, 10 ** 6), "µC", "μC", "uC")
_unit("capacitance", 1, "F", "farad", "farads")
_unit("capacitance", sp.Rational(1, 10 ** 6), "µF", "μF", "uF")
_unit("capacitance", sp.Rational(1, 10 ** 9), "nF")
_unit("capacitance", sp.Rational(1, 10 ** 12), "pF")
_unit("inductance", 1, "H", "henry", "henries")
_unit("inductance", sp.Rational(1, 1000), "mH")
_unit("frequency", 1, "Hz", "hertz")
_unit("frequency", 1000, "kHz")
_unit("frequency", 10 ** 6, "MHz")
_unit("time", 1, "s", "sec", "secs", "second", "seconds")
_unit("time", sp.Rational(1, 1000), "ms")
_unit("time", 60, "min", "mins", "minute", "minutes")
_unit("time", 3600, "h", "hr", "hrs", "hour", "hours")
_unit("time", 86400, "day", "days")
_unit("years", 1, "year", "years", "yr", "yrs")
_unit("months", 1, "month", "months")
_unit("length", 1, "m", "metre", "metres", "meter", "meters")
_unit("length", sp.Rational(1, 100), "cm", "centimetre", "centimetres")
_unit("length", sp.Rational(1, 1000), "mm")
_unit("length", 1000, "km", "kilometre", "kilometres")
_unit("mass", 1, "kg", "kilogram", "kilograms")
_unit("mass", sp.Rational(1, 1000), "g", "gram", "grams")
_unit("mass", 1000, "tonne", "tonnes")
_unit("speed", 1, "m/s", "ms^-1", "m s^-1")
_unit("speed", sp.Rational(5, 18), "km/h", "km/hr", "kmh", "kph")
_unit("acceleration", 1, "m/s^2", "m/s²", "ms^-2", "m s^-2", "m/s2", "N/kg")
_unit("force", 1, "N", "newton", "newtons")
_unit("force", 1000, "kN")
_unit("pressure", 1, "Pa", "N/m^2", "N/m²", "pascal", "pascals")
_unit("pressure", 1000, "kPa")
_unit("area", 1, "m^2", "m²", "m2")
_unit("area", sp.Rational(1, 10 ** 4), "cm^2", "cm²", "cm2")
_unit("volume", 1, "m^3", "m³", "m3")
_unit("volume", sp.Rational(1, 10 ** 6), "cm^3", "cm³", "cm3", "ml", "mL")
_unit("volume", sp.Rational(1, 1000), "litre", "litres", "liter", "liters", "l", "L")
_unit("shc", 1, "J/kgK", "J/kg K", "J/kg°C", "J/kg °C", "J/kg/K", "J kg^-1 K^-1")
_unit("spring", 1, "N/m")
_unit("density", 1, "kg/m^3", "kg/m³")
_unit("density", 1000, "g/cm^3", "g/cm³")
_unit("temperature", 1, "°C", "degrees Celsius", "degree Celsius", "degrees celsius", "K", "kelvin")
_unit("percent", 1, "%", "percent", "per cent")
_unit("angle", 1, "°", "degrees", "degree")
_unit("turns", 1, "turns", "turn")
_unit("count", 1, "men", "workers", "people", "pens", "books", "exercise books", "students", "items", "boys", "girls",
      "oranges", "balls", "machines", "taps", "players", "persons", "bags", "pencils", "chairs", "tables")

_UNIT_RE = re.compile(r"\s?(" + "|".join(sorted((re.escape(u) for u in _U), key=len, reverse=True)) + r")(?![A-Za-z²³])")
_MONEY = re.compile(r"(GH¢|GHS|GH₵|GHC|Gh¢|¢|\$|£|€|₦|cedis?)\s?$", re.I)

SI = {"power": "W", "voltage": "V", "current": "A", "resistance": "Ω", "energy": "J", "charge": "C",
      "capacitance": "F", "inductance": "H", "frequency": "Hz", "time": "s", "length": "m", "mass": "kg",
      "speed": "m/s", "acceleration": "m/s^2", "force": "N", "pressure": "Pa", "area": "m^2", "volume": "m^3",
      "density": "kg/m^3", "spring": "N/m", "momentum": "kg m/s", "reactance": "Ω", "period": "s", "shc": "J/kg K"}
_PREFIX = [(sp.Rational(1, 10 ** 6), "µ"), (sp.Rational(1, 1000), "m"), (1000, "k"), (10 ** 6, "M")]
_PREFIXABLE = {"power", "voltage", "current", "energy", "charge", "capacitance", "resistance", "frequency", "force", "pressure"}

_ASK = [
    (r"effective\s+resistance|total\s+resistance|equivalent\s+resistance|combined\s+resistance", "resistance"),
    (r"kinetic\s+energy|\bk\.?e\b", "ke"), (r"potential\s+energy|\bp\.?e\b|gain\s+in\s+(?:gravitational\s+)?potential", "pe"),
    (r"energy\s+stored|stored\s+energy", "energy"), (r"\bheat\b|quantity\s+of\s+heat", "heat"),
    (r"work\s+done|\bwork\b", "work"), (r"\bcurrent\b", "current"),
    (r"\bvoltage|\bp\.?d\.?(?![a-z])|potential\s+difference|e\.?m\.?f", "voltage"),
    (r"\bresistance\b", "resistance"), (r"\breactance\b", "reactance"), (r"\bpower\b", "power"),
    (r"\bcharge\b", "charge"), (r"\benergy\b|how\s+many\s+kwh", "energy"), (r"acceleration", "acceleration"),
    (r"final\s+(?:velocity|speed)", "speed"), (r"average\s+speed|\bspeed\b|\bvelocity\b", "speed"),
    (r"\bforce\b(?!\s+constant)|\bweight\b", "force"), (r"momentum", "momentum"), (r"density", "density"),
    (r"pressure", "pressure"), (r"spring\s+constant|force\s+constant|stiffness", "spring"), (r"wavelength", "wavelength"),
    (r"\bperiod\b", "period"), (r"frequency", "frequency"),
    (r"how\s+long|\btime\b|how\s+many\s+(?:seconds|minutes|hours)", "time"),
    (r"how\s+far|distance", "distance"), (r"how\s+high|height", "height"), (r"\bvolume\b", "volume"),
    (r"\bturns\b", "turns"),
]

_TAGS = [("radius", "radius"), ("radii", "radius"), ("diameter", "diameter"), ("height", "height"), ("high", "height"),
         ("tall", "height"), ("deep", "height"), ("depth", "height"), ("wavelength", "wavelength"),
         ("extension", "extension"), ("stretch", "extension"), ("compress", "extension"),
         ("distance", "distance"), ("moves", "distance"), ("travels", "distance"), ("covers", "distance"),
         ("pushing", "distance"), ("side", "side"), ("edge", "side"), ("length", "lengthw"), ("long", "lengthw"),
         ("width", "width"), ("wide", "width"), ("breadth", "width"), ("raised", "height"), ("lifted", "height"),
         ("lifts", "height"), ("dropped", "height"), ("fall", "height"), ("base", "base"), ("slant", "slant"),
         ("parallel sides", "parallel")]


@dataclass
class Given:
    slot: int
    qty: str            # "power", "length", "money", "percent" …
    factor: object      # to SI
    unit: str           # as written
    tag: str = ""       # radius / height / … for lengths
    const: bool = False # g = 10, c = 4200, π = 22/7: given constants stay fixed
    pos: int = 0


def read_givens(q: Question) -> List[Given]:
    out = []
    d = q.display
    skip = set()
    for s in q.slots:
        if s.role in ("exp", "ord") or s.style or s.i in skip:
            continue
        after = d[s.end:s.end + 24]
        before = d[max(0, s.start - 48):s.start]
        sci = re.match(r"\s*[x×]\s*10\s*\^\s*\(?(-?\d+)\)?", after)          # 1.0 x 10^5 Pa: one quantity
        power = 1
        if sci:
            power = sp.Integer(10) ** int(sci.group(1))
            skip |= {t.i for t in q.slots if s.end < t.start < s.end + sci.end() + 1}
            after = after[sci.end():] + d[s.end + 24:s.end + 24 + sci.end()]
        m = _UNIT_RE.match(after)
        if m:
            unit = m.group(1)
            qty, factor = _U[unit]
            factor = factor * power
            if unit in ("degrees", "degree") and re.match(r"\s?degrees?\s+(?:celsius|centigrade)", after, re.I):
                qty, factor, unit = "temperature", 1, "°C"
        elif _MONEY.search(before.rstrip()):
            qty, factor, unit = "money", 1, _MONEY.search(before.rstrip()).group(1)
        elif re.match(r"\s?(?:cedis?|pesewas?)\b", after, re.I):
            qty, factor, unit = "money", 1, "cedis"
        else:
            qty, factor, unit = "number", 1, ""
        word = before.lower()
        tag = ""
        best = -1
        for w, t in _TAGS:
            for mm in re.finditer(rf"\b{w}\w*", word):
                if mm.start() > best and not re.search(r"[.;]", word[mm.end():]):
                    tag, best = t, mm.start()
        const = bool(re.search(r"(?:\bg\s*=|\bc\s*=|\btake\s+g\b(?:\s+as)?|\bg\s+as|\bgravity\b[^.,;]*|specific\s+heat"
                               r"(?:\s+capacity)?(?:\s+of\s+water)?\s*(?:=|is|of)|π\s*=|\bpi\s*=|take\s+π\s+as|\bwhere\s+g)\s*$",
                               word.rstrip()))
        if qty == "shc" or (qty == "acceleration" and re.search(r"\bg\b", word[-12:])):
            const = True
        out.append(Given(s.i, qty, factor, unit, tag, const, s.start))
    return out


def asked(low: str) -> Tuple[Optional[str], Optional[str]]:
    """(what is asked, the unit wanted) from the question's last request."""
    m = list(re.finditer(r"(?:find|calculate|determine|what\s+is|what\s+are|work\s+out|compute|obtain|estimate|"
                         r"how\s+(?:long|far|high|much|many)|what\s+(?:current|power|voltage|force|time|pressure|volume))", low))
    tail = low[m[-1].start():] if m else low[-90:]
    want = None
    for pat, name in _ASK:
        if re.search(pat, tail):
            want = name
            break
    unit = None
    mu = re.search(r"\b(?:in|to)\s+(km/h|m/s|kwh|kj|mj|cm\^?3|cm³|m\^?3|cm\^?2|m\^?2|litres|minutes|hours|seconds|grams|"
                   r"g/cm\^?3|kg/m\^?3|µc|uc|mc|ma|ms)\b", tail)
    if mu:
        unit = {"kwh": "kWh", "kj": "kJ", "mj": "MJ", "cm^3": "cm^3", "cm3": "cm^3", "cm³": "cm^3", "m^3": "m^3", "m3": "m^3",
                "cm^2": "cm^2", "cm2": "cm^2", "m^2": "m^2", "m2": "m^2", "µc": "µC", "uc": "µC", "mc": "mC",
                "ma": "mA", "ms": "ms"}.get(mu.group(1), mu.group(1))
    elif re.search(r"how\s+many\s+kwh|\bkwh\b|\bunits\b", tail):
        unit = "kWh"
    return want, unit


def pi_of(low: str):
    m = re.search(r"(?:π|\bpi\b)\s*(?:=|as|to\s+be|is)\s*(22\s*/\s*7|3\.14\d*)", low)
    if not m:
        return sp.pi
    return sp.Rational(22, 7) if "22" in m.group(1) else exact(m.group(1).replace(" ", ""))


def show(v, unit: str = "", money: bool = False, qty: str = "") -> str:
    """A worked-out quantity: exact when short (2, 0.25, 154), else 3 significant figures; tiny or huge values
    with a prefix (240 µC, 4.46 MJ); money to 2 places."""
    v = exact(v)
    if money:
        txt = f"{float(v):,.2f}"
        return f"GHS {txt}"
    if qty in _PREFIXABLE and unit == SI.get(qty) and v != 0:
        fv = abs(float(v))
        if fv < 0.01 or fv >= 10 ** 6:
            for fac, pre in _PREFIX:
                if 1 <= fv / float(fac) < 1000:
                    v, unit = v / fac, pre + unit
                    break
    try:
        r = sp.Rational(v)
    except (TypeError, ValueError):
        r = None
    if r is not None and r.q == 1:
        n = int(r)
        txt = f"{n:,}" if abs(n) >= 10000 else str(n)
    elif r is not None and all(pq in (2, 5) for pq in sp.factorint(int(r.q))) and \
            len(f"{float(r):.10g}".replace(".", "").replace("-", "").lstrip("0")) <= 4:
        txt = f"{float(r):.10g}"
    else:
        txt = fmt_sig(float(v), 3)
    return f"{txt}%" if unit == "%" else f"{txt} {unit}".strip()


def mistakes(right, unit: str, extra=(), money: bool = False, qty: str = "") -> List[str]:
    cands = list(extra) + [right * 2, right / 2, right * 10, right / 10, right * 1000, right / 1000]
    out, rs = [], show(right, unit, money, qty)
    for c in cands:
        try:
            c = exact(c)
            if c is None or not c.is_positive:
                continue
            ratio = float(c) / float(right) if float(right) else 1
            if not 1e-3 <= ratio <= 1e3:                                     # 10²³ cm³ is no one's real mistake
                continue
            w = show(c, unit, money, qty)
        except Exception:                                                    # noqa: BLE001
            continue
        if w not in out and w != rs:
            out.append(w)
    return out


# ── reading values for a version ─────────────────────────────────────────────────────────────────────────────

def si(vals, g: Given):
    return sp.Rational(Fraction(vals[g.slot]).numerator, Fraction(vals[g.slot]).denominator) * g.factor


def raw(vals, g: Given):
    return sp.Rational(Fraction(vals[g.slot]).numerator, Fraction(vals[g.slot]).denominator)


def written(vals, g: Given) -> str:
    n = raw(vals, g)
    if g.qty == "money":
        return f"GHS {fmt_num(n)}"
    if g.qty == "percent":
        return f"{fmt_num(n)}%"
    return f"{fmt_num(n)} {g.unit}".strip()


# ── the rules ───────────────────────────────────────────────────────────────────────────────────────────────

class Rule:
    """One kind of word problem.
    - when: words that must be in the question; ask: what it must ask for.
    - roles: (name, test(given)) picked in reading order.
    - work(X, W, ctx) -> (value, unit, steps, wrong values) where X holds SI values and W the values as written."""

    def __init__(self, name, when, roles, work, ask=None, unless=None, money=False, si_units=True, extra_ok=False):
        self.name, self.when, self.roles, self.work = name, when, roles, work
        self.ask, self.unless, self.money, self.si_units, self.extra_ok = ask, unless, money, si_units, extra_ok

    def parse(self, q, low, givens):
        if not re.search(self.when, low) or (self.unless and re.search(self.unless, low)):
            return None
        want, unit = asked(low)
        if self.ask and want not in self.ask and not re.search(self.ask_words(), low[-90:]):
            return None
        pick, used = {}, set()
        for role, test in self.roles:
            optional = role.endswith("?")
            cands = [g for g in givens if g.slot not in used and test(g)]
            if not cands:
                if optional:
                    continue
                return None
            pick[role.rstrip("?")] = cands[0]
            used.add(cands[0].slot)
        rest = [g for g in givens if g.slot not in used and not g.const and g.qty not in ("number",)]
        if rest and not self.extra_ok:
            return None
        return Spec(rule=self, pick=pick, want=want, unit=unit, low=low, uses=[g.slot for g in pick.values()])

    def ask_words(self):
        return r"$^"

    def solve(self, q, spec, vals):
        X = {r: si(vals, g) for r, g in spec.pick.items()}
        W = {r: raw(vals, g) for r, g in spec.pick.items()}
        got = self.work(X, W, spec)
        if got is None:
            return None
        value, unit, steps, extra = got
        if value is None or not exact(value).is_positive:
            return None
        qty = {v: k for k, v in SI.items()}.get(unit, "")
        ans = show(value, unit, self.money, qty)
        return ans, exact(value), steps, mistakes(value, unit, extra, self.money, qty)


def is_(qty, tag=None, const=None):
    def test(g):
        if g.qty != qty:
            return False
        if tag is not None and g.tag not in (tag if isinstance(tag, tuple) else (tag,)):
            return False
        if const is not None and g.const != const:
            return False
        return True
    return test


def n(x):
    """A number for the working: exact if short, else 3 s.f."""
    return show(x)


def _g(spec, X, default=sp.Rational(98, 10)):
    return X.get("g", default) if "g" in X else (sp.Integer(10) if re.search(r"\bg\s*=\s*10\b|take\s+g\s+as\s+10", spec.low) else default)


def _si_unit(spec, qty, value):
    """The answer in the unit the question asks for (km/h, kWh …) when it asks, else SI."""
    u = spec.unit
    if u and u in _U and _U[u][0] == qty:
        return value / _U[u][1], u
    return value, SI[qty]


# electricity ---------------------------------------------------------------------------------------------------

def w_series(X, W, spec):
    Rs = [X[k] for k in sorted(X) if k.startswith("r")]
    Rt = sum(Rs)
    steps = [f"In series the resistances add: R = {' + '.join(n(r) for r in Rs)} = {n(Rt)} Ω."]
    if "v" in X and spec.want == "current":
        I = X["v"] / Rt
        steps.append(f"I = V/R = {n(X['v'])}/{n(Rt)} = {show(I, 'A')}")
        return I, "A", steps, [X["v"] / sum(1 / r for r in Rs) ** -1 if Rs else None, X["v"] * Rt, X["v"] / Rs[0]]
    return Rt, "Ω", steps, [1 / sum(1 / r for r in Rs), Rt / len(Rs), max(Rs)]


def w_parallel(X, W, spec):
    Rs = [X[k] for k in sorted(X) if k.startswith("r")]
    Rt = 1 / sum(1 / r for r in Rs)
    steps = [f"In parallel: 1/R = {' + '.join('1/' + n(r) for r in Rs)} = {fmt_num(sum(1 / r for r in Rs))}",
             f"R = {show(Rt, 'Ω')}"]
    if "v" in X and spec.want == "current":
        I = X["v"] / Rt
        steps.append(f"I = V/R = {show(I, 'A')}")
        return I, "A", steps, [X["v"] / sum(Rs), X["v"] * Rt]
    return Rt, "Ω", steps, [sum(Rs), sum(1 / r for r in Rs), Rt * 2, sum(Rs) / len(Rs)]


def w_transformer(X, W, spec):
    Np = W["np"]
    if "ns" in W and "vp" in X and spec.want != "turns":
        Ns = W["ns"]
        Vs = X["vp"] * Ns / Np
        return Vs, "V", [f"Vs/Vp = Ns/Np, so Vs = Vp × Ns/Np = {n(X['vp'])} × {fmt_num(Ns)}/{fmt_num(Np)} = {show(Vs, 'V')}"], \
            [X["vp"] * Np / Ns, X["vp"] * Ns, X["vp"] / Ns]
    if "vs" in X and "vp" in X:                         # how many turns on the secondary?
        Ns2 = Np * X["vs"] / X["vp"]
        return Ns2, "turns", [f"Ns/Np = Vs/Vp, so Ns = Np × Vs/Vp = {fmt_num(Np)} × {n(X['vs'])}/{n(X['vp'])} = {show(Ns2, 'turns')}"], \
            [Np * X["vp"] / X["vs"], X["vs"] * X["vp"] / Np, Np / X["vs"]]
    return None


def w_cap_energy(X, W, spec):
    E = X["c"] * X["v"] ** 2 / 2
    return E, "J", [f"Energy stored E = ½CV² = ½ × {n(X['c'])} × {n(X['v'])}² = {show(E, 'J', qty='energy')}"], \
        [X["c"] * X["v"] ** 2, X["c"] * X["v"] / 2, X["c"] * X["v"]]


def w_reactance(X, W, spec):
    if "l" in X:
        Xl = 2 * sp.pi * X["f"] * X["l"]
        return Xl, "Ω", [f"X_L = 2πfL = 2π × {n(X['f'])} × {n(X['l'])} = {show(Xl, 'Ω')}"], [X["f"] * X["l"], sp.pi * X["f"] * X["l"], 1 / Xl]
    Xc = 1 / (2 * sp.pi * X["f"] * X["c"])
    return Xc, "Ω", [f"X_C = 1/(2πfC) = 1/(2π × {n(X['f'])} × {n(X['c'])}) = {show(Xc, 'Ω')}"], [2 * sp.pi * X["f"] * X["c"], 1 / (X["f"] * X["c"])]


def w_period(X, W, spec):
    T = 1 / X["f"]
    v, u = _si_unit(spec, "time", T)
    return v, u, [f"T = 1/f = 1/{n(X['f'])} = {show(T, 's')}"], [X["f"], 2 / X["f"], 1 / (2 * X["f"])]


def w_cost(X, W, spec):
    kW = X["p"] / 1000
    hours = X["t"] / 3600
    units = kW * hours
    cost = units * W["rate"]
    return cost, "GHS", [f"Energy = power (kW) × time (h) = {fmt_num(kW)} × {fmt_num(hours)} = {fmt_num(units)} kWh",
                         f"Cost = {fmt_num(units)} × {fmt_num(W['rate'])} = GHS {float(cost):.2f}"], \
        [X["p"] * hours * W["rate"], kW * X["t"] / 60 * W["rate"], units]


def w_energy_pt(X, W, spec):
    E = X["p"] * X["t"]
    v, u = _si_unit(spec, "energy", E)
    steps = [f"E = Pt = {n(X['p'])} W × {n(X['t'])} s = {show(E, 'J', qty='energy')}"]
    if u == "kWh":
        steps.append(f"In kWh: {fmt_num(X['p'] / 1000)} kW × {fmt_num(X['t'] / 3600)} h = {show(v, 'kWh')}")
    return v, u, steps, [v * 60, v / 60, W["p"] * W["t"]]


# mechanics -----------------------------------------------------------------------------------------------------

def w_free_fall(X, W, spec):
    g = _g(spec, X)
    if spec.want == "time" and "h" in X:
        t = sp.sqrt(2 * X["h"] / g)
        return t, "s", [f"From rest: h = ½gt², so t = √(2h/g) = √(2 × {n(X['h'])}/{n(g)}) = {show(t, 's')}"], \
            [2 * X["h"] / g, sp.sqrt(X["h"] / g), X["h"] / g]
    if spec.want in ("distance", "height") and "t" in X:
        h = g * X["t"] ** 2 / 2
        return h, "m", [f"From rest: h = ½gt² = ½ × {n(g)} × {n(X['t'])}² = {show(h, 'm')}"], [g * X["t"] ** 2, g * X["t"], g * X["t"] / 2]
    if spec.want == "speed":
        v = g * X["t"] if "t" in X else sp.sqrt(2 * g * X["h"])
        return v, "m/s", [f"v = {'gt' if 't' in X else '√(2gh)'} = {show(v, 'm/s')}"], [v / 2, v ** 2]
    return None


def w_suvat(X, W, spec):
    u = X.get("u", sp.Integer(0))
    a, tt = X.get("a"), X.get("t")
    if spec.want == "speed" and a is not None and tt is not None:
        v = u + a * tt
        return v, "m/s", [f"v = u + at = {n(u)} + {n(a)} × {n(tt)} = {show(v, 'm/s')}"], [a * tt if u else u + a, u * a * tt if u else a / tt, u + a * tt / 2]
    if spec.want in ("distance",) and a is not None and tt is not None:
        s = u * tt + a * tt ** 2 / 2
        return s, "m", [f"s = ut + ½at² = {show(s, 'm')}"], [u * tt + a * tt ** 2, a * tt]
    if spec.want == "acceleration" and "v" in X and tt is not None:
        acc = (X["v"] - u) / tt
        return acc, "m/s^2", [f"a = (v - u)/t = ({n(X['v'])} - {n(u)})/{n(tt)} = {show(acc, 'm/s^2')}"], [X["v"] / tt, (X["v"] + u) / tt]
    return None


def w_avg_speed(X, W, spec):
    v = X["s"] / X["t"]
    want_kmh = spec.unit == "km/h" or (spec.pick["s"].unit in ("km", "kilometres") and spec.pick["t"].factor == 3600 and spec.unit != "m/s")
    if want_kmh:
        vv = v * sp.Rational(18, 5)
        return vv, "km/h", [f"Speed = distance/time = {written({}, spec.pick['s']) if False else n(X['s'] / 1000)} km ÷ {n(X['t'] / 3600)} h = {show(vv, 'km/h')}"], \
            [X["s"] / 1000 * X["t"] / 3600, X["t"] / 3600 / (X["s"] / 1000), v]
    return v, "m/s", [f"Speed = distance/time = {n(X['s'])} m ÷ {n(X['t'])} s = {show(v, 'm/s')}"], [X["s"] * X["t"], X["t"] / X["s"]]


def w_pe(X, W, spec):
    g = _g(spec, X)
    E = X["m"] * g * X["h"]
    return E, "J", [f"PE = mgh = {n(X['m'])} × {n(g)} × {n(X['h'])} = {show(E, 'J', qty='energy')}"], \
        [X["m"] * X["h"], X["m"] * g * X["h"] / 2, X["m"] * g]


def w_lift_power(X, W, spec):
    g = _g(spec, X)
    Wk = X["m"] * g * X["h"]
    Pw = Wk / X["t"]
    return Pw, "W", [f"Work = mgh = {n(X['m'])} × {n(g)} × {n(X['h'])} = {n(Wk)} J", f"Power = work/time = {n(Wk)}/{n(X['t'])} = {show(Pw, 'W')}"], \
        [Wk, X["m"] * X["h"] / X["t"], Wk * X["t"]]


def w_heat(X, W, spec):
    dT = X["dt"] if "dt" in X else abs(X["t2"] - X["t1"])
    c = X.get("c", sp.Integer(4200))
    Qh = X["m"] * c * dT
    steps = []
    if "t2" in X:
        steps.append(f"Temperature rise = {n(X['t2'])} - {n(X['t1'])} = {n(dT)} °C")
    steps.append(f"Q = mcΔθ = {n(X['m'])} × {n(c)} × {n(dT)} = {show(Qh, 'J', qty='energy')}")
    return Qh, "J", steps, [X["m"] * c, X["m"] * c * (X["t2"] if "t2" in X else dT * 2), c * dT]


def w_boyle(X, W, spec):
    V2 = X["p1"] * X["v1"] / X["p2"]
    u = spec.pick["v1"].unit
    f = spec.pick["v1"].factor
    return V2 / f, u, [f"Boyle's law: p₁V₁ = p₂V₂, so V₂ = p₁V₁/p₂ = {fmt_num(W['p1'])} × {fmt_num(W['v1'])}/{fmt_num(W['p2'])} = {show(V2 / f, u)}"], \
        [X["p2"] * X["v1"] / X["p1"] / f, X["p1"] * X["p2"] / X["v1"] / f]


def w_weight(X, W, spec):
    g = _g(spec, X)
    Fw = X["m"] * g
    return Fw, "N", [f"W = mg = {n(X['m'])} × {n(g)} = {show(Fw, 'N')}"], [X["m"], X["m"] / g]


# money ---------------------------------------------------------------------------------------------------------

def _years(X, W):
    return W["t"] if "t" in W else W["n"]


def w_simple_interest(X, W, spec):
    I = W["p"] * W["r"] * _years(X, W) / 100
    total = re.search(r"\bamount\b|\btotal\b", spec.low)
    steps = [f"Simple interest = PRT/100 = {fmt_num(W['p'])} × {fmt_num(W['r'])} × {fmt_num(_years(X, W))}/100 = GHS {float(I):,.2f}"]
    if total:
        steps.append(f"Amount = principal + interest = GHS {float(W['p'] + I):,.2f}")
        return W["p"] + I, "GHS", steps, [I, W["p"] * (1 + W["r"] / 100) ** _years(X, W), W["p"] + I * 2]
    return I, "GHS", steps, [W["p"] + I, W["p"] * W["r"] * _years(X, W), I / _years(X, W)]


def w_compound(X, W, spec):
    years = _years(X, W)
    A = W["p"] * (1 + W["r"] / 100) ** years
    steps = [f"Amount = P(1 + R/100)^n = {fmt_num(W['p'])} × (1 + {fmt_num(W['r'])}/100)^{fmt_num(years)} = GHS {float(A):,.2f}"]
    if re.search(r"compound\s+interest|\binterest\b", spec.low) and not re.search(r"\bamount\b", spec.low):
        steps.append(f"Interest = amount - principal = GHS {float(A - W['p']):,.2f}")
        return A - W["p"], "GHS", steps, [A, W["p"] * W["r"] * years / 100, A - W["p"] * 2]
    return A, "GHS", steps, [A - W["p"], W["p"] * (1 + W["r"] * years / 100), W["p"] * (1 + W["r"] / 100) * years]


def w_depreciation(X, W, spec):
    years = _years(X, W)
    V = W["p"] * (1 - W["r"] / 100) ** years
    return V, "GHS", [f"Value = P(1 - R/100)^n = {fmt_num(W['p'])} × (1 - {fmt_num(W['r'])}/100)^{fmt_num(years)} = GHS {float(V):,.2f}"], \
        [W["p"] * (1 - W["r"] * years / 100), W["p"] - V, W["p"] * (1 + W["r"] / 100) ** years]


def w_profit(X, W, spec):
    cp, sp_ = W["cp"], W["sp"]
    pct = (sp_ - cp) / cp * 100
    word = "profit" if pct > 0 else "loss"
    if pct == 0:
        return None
    asks = re.findall(r"\b(profit|loss|gain)\b", spec.low)                  # a "loss" question must be a loss
    if asks and {"gain": "profit"}.get(asks[-1], asks[-1]) != word:
        return None
    steps = [f"{word.capitalize()} = {fmt_num(abs(sp_ - cp))}", f"{word.capitalize()} % = {fmt_num(abs(sp_ - cp))}/{fmt_num(cp)} × 100 = {fmt_num(exact(abs(pct)))}%"]
    return abs(pct), "%", steps, [abs(sp_ - cp) / sp_ * 100, abs(sp_ - cp), 100 - abs(pct)]


def w_discount(X, W, spec):
    mp, d = W["mp"], W["d"]
    price = mp * (1 - d / 100)
    if re.search(r"\bdiscount\b[^.]*\?$|how\s+much\s+(?:is|was)\s+the\s+discount|find\s+the\s+discount", spec.low) and not re.search(r"selling\s+price|pay", spec.low):
        disc = mp * d / 100
        return disc, "GHS", [f"Discount = {fmt_num(d)}% of {fmt_num(mp)} = GHS {float(disc):,.2f}"], [price, mp * d, mp - d]
    return price, "GHS", [f"Discount = {fmt_num(d)}% of {fmt_num(mp)} = {fmt_num(mp * d / 100)}", f"Selling price = {fmt_num(mp)} - {fmt_num(mp * d / 100)} = GHS {float(price):,.2f}"], \
        [mp * d / 100, mp - d, mp * (1 + d / 100)]


def w_percent_of(X, W, spec):
    total, p = W["money"], W["p"]
    part = total * p / 100
    left = re.search(r"\bleft\b|\bremain|\bbalance\b", spec.low)
    value = total - part if left else part
    yearly = re.search(r"\bin\s+a\s+year\b|\bper\s+year\b|\bannually\b|\byearly\b", spec.low) and re.search(r"month", spec.low)
    steps = [f"{fmt_num(p)}% of {fmt_num(total)} = {fmt_num(part)}"]
    if left:
        steps.append(f"Left = {fmt_num(total)} - {fmt_num(part)} = GHS {float(value):,.2f}")
    if yearly:
        value = value * 12
        steps.append(f"In a year: × 12 = GHS {float(value):,.2f}")
    return value, "GHS", steps, [part if left else total - part, total * p, value * 12 if not yearly else value / 12]


def w_change_by(X, W, spec):
    num_, p = W["x"], W["p"]
    up = re.search(r"\bincrease", spec.low)
    v = num_ * (1 + p / 100) if up else num_ * (1 - p / 100)
    return v, "", [f"{'Increase' if up else 'Decrease'} by {fmt_num(p)}%: {fmt_num(num_)} × {fmt_num(100 + p if up else 100 - p)}/100 = {fmt_num(v)}"], \
        [num_ * p / 100, num_ * (1 - p / 100) if up else num_ * (1 + p / 100), num_ + p if up else num_ - p]


def w_ratio(X, W, spec):
    parts = [int(x) for x in spec.ratio]
    total = W["money"] if "money" in W else W["x"]
    tot = sum(parts)
    shares = [total * k / tot for k in parts]
    names = spec.names or [f"share {i + 1}" for i in range(len(parts))]
    money = "money" in W
    fmtv = (lambda v: f"GHS {float(v):,.2f}") if money else (lambda v: fmt_num(exact(v)))
    ans = ", ".join(f"{nm}: {fmtv(v)}" for nm, v in zip(names, shares))
    steps = [f"Total parts = {' + '.join(map(str, parts))} = {tot}", f"One part = {fmt_num(total)}/{tot} = {fmt_num(exact(total / tot))}"] + \
            [f"{nm}: {k} × {fmt_num(exact(total / tot))} = {fmtv(v)}" for nm, k, v in zip(names, parts, shares)]
    return ("ratio", ans, tuple(shares), steps, names, money)


def w_proportion(X, W, spec):
    n1, cost, n2 = W["n1"], W["cost"], W["n2"]
    v = cost / n1 * n2
    return v, "GHS", [f"One costs {fmt_num(cost)}/{fmt_num(n1)} = {fmt_num(exact(cost / n1))}", f"{fmt_num(n2)} cost {fmt_num(n2)} × {fmt_num(exact(cost / n1))} = GHS {float(v):,.2f}"], \
        [cost * n1 / n2, cost + (n2 - n1), cost * n2]


def w_inverse(X, W, spec):
    a1, d1, a2 = W["a1"], W["d1"], W["a2"]
    v = a1 * d1 / a2
    unit = spec.pick["d1"].unit or "days"
    return v, unit, [f"More workers take less time: {fmt_num(a1)} × {fmt_num(d1)} = {fmt_num(a1 * d1)} worker-{unit}", f"{fmt_num(a1 * d1)}/{fmt_num(a2)} = {show(v, unit)}"], \
        [d1 * a2 / a1, d1 + a1 - a2, d1 * a2]


def w_convert_speed(X, W, spec):
    g = spec.pick["x"]
    if g.unit in ("km/h", "km/hr", "kmh", "kph"):
        v = W["x"] * sp.Rational(5, 18)
        return v, "m/s", [f"1 km/h = 1000 m ÷ 3600 s = 5/18 m/s", f"{fmt_num(W['x'])} × 5/18 = {show(v, 'm/s')}"], [W["x"] * sp.Rational(18, 5), W["x"] * 1000 / 60, W["x"] / 1000]
    v = W["x"] * sp.Rational(18, 5)
    return v, "km/h", [f"1 m/s = 3.6 km/h", f"{fmt_num(W['x'])} × 3.6 = {show(v, 'km/h')}"], [W["x"] * sp.Rational(5, 18), W["x"] * 60, W["x"] * 1000]


# mensuration ---------------------------------------------------------------------------------------------------

def _r(W, spec):
    if "r" in W:
        return W["r"]
    return W["d"] / 2


def _lu(spec, *roles):
    for r in roles:
        if r in spec.pick:
            return spec.pick[r].unit or "units"
    return "units"


def w_circle_area(X, W, spec):
    pi = pi_of(spec.low)
    r = _r(W, spec)
    A = pi * r ** 2
    u = _lu(spec, "r", "d")
    return A, f"{u}^2", [("Radius = diameter ÷ 2 = " + fmt_num(r) + f" {u}. ") * ("d" in W) + f"Area = πr² = {'22/7' if pi != sp.pi else 'π'} × {fmt_num(r)}² = {show(A, u + '^2')}"], \
        [2 * pi * r, pi * (2 * r) ** 2, pi * r]


def w_circumference(X, W, spec):
    pi = pi_of(spec.low)
    r = _r(W, spec)
    Cc = 2 * pi * r
    u = _lu(spec, "r", "d")
    return Cc, u, [f"Circumference = 2πr = πd = {show(Cc, u)}"], [pi * r ** 2, pi * r, 4 * pi * r]


def w_sphere(X, W, spec):
    pi = pi_of(spec.low)
    r = _r(W, spec)
    u = _lu(spec, "r", "d")
    if re.search(r"surface", spec.low):
        A = 4 * pi * r ** 2
        return A, f"{u}^2", [f"Surface area = 4πr² = {show(A, u + '^2')}"], [pi * r ** 2, 4 * pi * r ** 3 / 3, 2 * pi * r ** 2]
    Vv = 4 * pi * r ** 3 / 3
    return Vv, f"{u}^3", [f"Volume = (4/3)πr³ = (4/3) × {'22/7' if pi != sp.pi else 'π'} × {fmt_num(r)}³ = {show(Vv, u + '^3')}"], \
        [4 * pi * r ** 2, pi * r ** 3, 4 * pi * r ** 3]


def w_cylinder(X, W, spec):
    pi = pi_of(spec.low)
    r, h = _r(W, spec), W["h"]
    u = _lu(spec, "r", "d")
    if re.search(r"curved\s+surface", spec.low):
        A = 2 * pi * r * h
        return A, f"{u}^2", [f"Curved surface = 2πrh = {show(A, u + '^2')}"], [pi * r ** 2 * h, 2 * pi * r * (r + h)]
    if re.search(r"surface", spec.low):
        A = 2 * pi * r * (r + h)
        return A, f"{u}^2", [f"Total surface = 2πr(r + h) = {show(A, u + '^2')}"], [2 * pi * r * h, pi * r ** 2 * h]
    Vv = pi * r ** 2 * h
    return Vv, f"{u}^3", [f"Volume = πr²h = {'22/7' if pi != sp.pi else 'π'} × {fmt_num(r)}² × {fmt_num(h)} = {show(Vv, u + '^3')}"], \
        [2 * pi * r * h, pi * r * h, pi * (2 * r) ** 2 * h]


def w_cone(X, W, spec):
    pi = pi_of(spec.low)
    r, h = _r(W, spec), W["h"]
    u = _lu(spec, "r", "d")
    Vv = pi * r ** 2 * h / 3
    return Vv, f"{u}^3", [f"Volume = (1/3)πr²h = (1/3) × {'22/7' if pi != sp.pi else 'π'} × {fmt_num(r)}² × {fmt_num(h)} = {show(Vv, u + '^3')}"], \
        [pi * r ** 2 * h, pi * r * h / 3, pi * r ** 2 * h / 2]


def w_trapezium(X, W, spec):
    a, b, h = W["a"], W["b"], W["h"]
    A = (a + b) * h / 2
    u = _lu(spec, "a")
    return A, f"{u}^2", [f"Area = ½(a + b)h = ½ × ({fmt_num(a)} + {fmt_num(b)}) × {fmt_num(h)} = {show(A, u + '^2')}"], \
        [(a + b) * h, a * b * h / 2, (a + b) / 2]


def w_rect_diagonal(X, W, spec):
    l, w = W["l"], W["w"]
    d = sp.sqrt(l ** 2 + w ** 2)
    u = _lu(spec, "l")
    return d, u, [f"By Pythagoras: diagonal = √({fmt_num(l)}² + {fmt_num(w)}²) = √{fmt_num(l ** 2 + w ** 2)} = {show(d, u)}"], \
        [l + w, l ** 2 + w ** 2, sp.sqrt(abs(l ** 2 - w ** 2))]


def w_cube(X, W, spec):
    s = W["s"]
    u = _lu(spec, "s")
    if re.search(r"volume", spec.low):
        return s ** 3, f"{u}^3", [f"Volume = s³ = {fmt_num(s)}³ = {show(s ** 3, u + '^3')}"], [6 * s ** 2, 3 * s, s ** 2]
    A = 6 * s ** 2
    return A, f"{u}^2", [f"A cube has 6 square faces: 6 × {fmt_num(s)}² = {show(A, u + '^2')}"], [s ** 3, 4 * s ** 2, 6 * s]


def w_cuboid(X, W, spec):
    l, w, h = W["l"], W["w"], W["h"]
    u = _lu(spec, "l")
    if re.search(r"volume", spec.low):
        return l * w * h, f"{u}^3", [f"Volume = lwh = {fmt_num(l)} × {fmt_num(w)} × {fmt_num(h)} = {show(l * w * h, u + '^3')}"], \
            [2 * (l * w + l * h + w * h), l * w, l + w + h]
    A = 2 * (l * w + l * h + w * h)
    return A, f"{u}^2", [f"Surface area = 2(lw + lh + wh) = 2({fmt_num(l * w)} + {fmt_num(l * h)} + {fmt_num(w * h)}) = {show(A, u + '^2')}"], \
        [l * w * h, l * w + l * h + w * h, 2 * (l + w + h)]


def w_rect_area(X, W, spec):
    l, w = W["l"], W["w"]
    u = _lu(spec, "l")
    if re.search(r"perimeter", spec.low):
        return 2 * (l + w), u, [f"Perimeter = 2(l + w) = {show(2 * (l + w), u)}"], [l * w, l + w]
    return l * w, f"{u}^2", [f"Area = length × width = {fmt_num(l)} × {fmt_num(w)} = {show(l * w, u + '^2')}"], [2 * (l + w), l + w]


def w_triangle_area(X, W, spec):
    b, h = W["b"], W["h"]
    u = _lu(spec, "b")
    return b * h / 2, f"{u}^2", [f"Area = ½ × base × height = ½ × {fmt_num(b)} × {fmt_num(h)} = {show(b * h / 2, u + '^2')}"], [b * h, b + h]


L_ = lambda tag=None: is_("length", tag)
_RES = lambda g: g.qty == "resistance"


def _many(qty, k):
    return [(f"r{i}", is_(qty)) for i in range(k)]


RULES: List[Rule] = []


def _rule(*a, **k):
    RULES.append(Rule(*a, **k))


# electricity
_rule("transformer", r"transformer|\bturns\b", [("np", is_("turns")), ("ns", is_("turns")), ("vp", is_("voltage")), ("vs?", is_("voltage"))], w_transformer)
_rule("transformer turns", r"transformer|\bturns\b", [("vp", is_("voltage")), ("vs", is_("voltage")), ("np", is_("turns"))], w_transformer)
_rule("cost", r"\bcost", [("p", is_("power")), ("t", is_("time")), ("rate", lambda g: g.qty in ("money", "number"))], w_cost, extra_ok=True, money=True)
_rule("cap energy", r"energy\s+stored|stored\s+energy|energy\s+in\s+(?:a|the)\s+capacitor", [("c", is_("capacitance")), ("v", is_("voltage"))], w_cap_energy)
_rule("reactance L", r"reactance", [("l", is_("inductance")), ("f", is_("frequency"))], w_reactance)
_rule("reactance C", r"reactance", [("c", is_("capacitance")), ("f", is_("frequency"))], w_reactance)
_rule("period", r"\bperiod\b", [("f", is_("frequency"))], w_period)
_rule("energy Pt", r"\benergy\b|\bkwh\b|how\s+much\s+(?:electrical\s+)?energy|\bunits\b", [("p", is_("power")), ("t", is_("time"))], w_energy_pt,
      unless=r"\bcost\b")
# mechanics
_rule("free fall", r"\bdropped|\bfalls?\s+freely|free\s+fall|falls?\s+from\s+(?:rest|a\s+height)|\bfrom\s+a\s+height\b",
      [("h?", L_()), ("t?", is_("time")), ("g?", is_("acceleration", const=True))], w_free_fall)
_rule("suvat", r"accelerat|decelerat|from\s+rest|uniformly", [("u?", lambda g: g.qty == "speed"), ("a", lambda g: g.qty == "acceleration" and not g.const),
                                                            ("t", is_("time"))], w_suvat, unless=r"\bforce\b|\bmass\b|\bkg\b")
_rule("avg speed", r"\btravels?|\bcovers?|\bjourney|average\s+speed|\bspeed\b", [("s", L_()), ("t", is_("time"))], w_avg_speed,
      unless=r"accelerat|wave|frequency")
_rule("pe", r"potential\s+energy|\bp\.?e\b|gain\s+in", [("m", is_("mass")), ("h", L_()), ("g?", is_("acceleration", const=True))], w_pe)
_rule("lift power", r"\bpower\b", [("m", is_("mass")), ("h", L_()), ("t", is_("time")), ("g?", is_("acceleration", const=True))], w_lift_power)
_rule("heat", r"\bheat\b|temperature|raise", [("m", is_("mass")), ("t1", is_("temperature")), ("t2", is_("temperature")), ("c?", is_("shc"))], w_heat)
_rule("heat dT", r"\bheat\b|temperature|raise", [("m", is_("mass")), ("dt", is_("temperature")), ("c?", is_("shc"))], w_heat)
_rule("boyle", r"pressure|\bgas\b|boyle|temperature\s+(?:is\s+)?constant|constant\s+temperature", [("v1", is_("volume")), ("p1", is_("pressure")), ("p2", is_("pressure"))], w_boyle)
_rule("weight", r"\bweight\b", [("m", is_("mass")), ("g?", is_("acceleration", const=True))], w_weight)
# money
_rule("compound", r"compound", [("p", is_("money")), ("r", is_("percent")), ("t", lambda g: g.qty in ("years", "number"))], w_compound, money=True)
_rule("depreciation", r"depreciat", [("p", is_("money")), ("r", is_("percent")), ("t", lambda g: g.qty in ("years", "number"))], w_depreciation, money=True)
_rule("simple interest", r"\binterest\b|\bper\s+annum\b", [("p", is_("money")), ("r", is_("percent")), ("t", lambda g: g.qty in ("years", "months", "number"))],
      w_simple_interest, money=True)
_rule("profit", r"\bprofit\b|\bloss\b", [("cp", is_("money")), ("sp", is_("money"))], w_profit)
_rule("discount", r"discount", [("mp", is_("money")), ("d", is_("percent"))], w_discount, money=True)
_rule("percent of", r"\bspends?\b|\bsaves?\b|\bpays?\b|\buses?\b|\bgives?\b|\bsalary\b|\bincome\b",
      [("p", is_("percent")), ("money", is_("money"))], w_percent_of, money=True)
_rule("change by", r"\b(?:increase|decrease)\s", [("x", lambda g: g.qty in ("number", "money")), ("p", is_("percent"))], w_change_by)
_rule("inverse", r"\bhow\s+(?:long|many\s+days)|\bwould\b.*\btake\b|\bwill\b.*\btake\b",
      [("a1", is_("count")), ("d1", lambda g: g.qty in ("time", "number") or g.unit in ("days", "day", "hours", "weeks")), ("a2", is_("count"))], w_inverse)
_rule("proportion", r"\bcost", [("n1", is_("count")), ("cost", is_("money")), ("n2", is_("count"))], w_proportion, money=True)
_rule("convert speed", r"\bconvert\b|\bexpress\b|\bchange\b", [("x", lambda g: g.qty == "speed")], w_convert_speed)
# mensuration
_rule("sphere", r"\bsphere|\bball\b|hemisphere", [("r?", L_(("radius", ""))), ("d?", L_("diameter"))], w_sphere)
_rule("cylinder", r"cylind", [("r?", L_("radius")), ("d?", L_("diameter")), ("h", L_(("height", "lengthw")))], w_cylinder)
_rule("cone", r"\bcone\b", [("r?", L_(("radius", "base"))), ("d?", L_("diameter")), ("h", L_("height"))], w_cone)
_rule("circle area", r"\bcircle\b.*\barea\b|\barea\b.*\bcircle\b|\bcircular\b.*\barea\b", [("r?", L_(("radius", ""))), ("d?", L_("diameter"))], w_circle_area)
_rule("circumference", r"circumference|perimeter\s+of\s+(?:a|the)\s+circle", [("r?", L_(("radius", ""))), ("d?", L_("diameter"))], w_circumference)
_rule("trapezium", r"trapezium|trapezoid", [("a", L_()), ("b", L_()), ("h", L_())], w_trapezium)
_rule("diagonal", r"diagonal", [("l", L_()), ("w", L_())], w_rect_diagonal)
_rule("cube", r"\bcube\b", [("s", L_())], w_cube)
_rule("cuboid", r"cuboid|rectangular\s+box|\bbox\b", [("l", L_()), ("w", L_()), ("h", L_())], w_cuboid)
_rule("rectangle", r"rectang|\bfield\b|\bplot\b", [("l", L_()), ("w", L_())], w_rect_area)
_rule("triangle", r"\btriangle\b", [("b", L_()), ("h", L_())], w_triangle_area, unless=r"angle\s+of|\bsin|\bcos|degrees|°")


# ── series / parallel resistors and ratios need their own readers ───────────────────────────────────────────

class ResistorRule(Rule):
    def __init__(self, kind, work):
        super().__init__(kind, kind, [], work)
        self.kind = kind

    def parse(self, q, low, givens):
        if not re.search(rf"\b{self.kind}\b", low):
            return None
        Rs = [g for g in givens if g.qty == "resistance"]
        if len(Rs) < 2:
            return None
        pick = {f"r{i}": g for i, g in enumerate(Rs)}
        Vs = [g for g in givens if g.qty == "voltage"]
        if Vs:
            pick["v"] = Vs[0]
        want, unit = asked(low)
        return Spec(rule=self, pick=pick, want=want, unit=unit, low=low, uses=[g.slot for g in pick.values()])


class RatioRule(Rule):
    def __init__(self):
        super().__init__("ratio", r"ratio", [], w_ratio)

    def parse(self, q, low, givens):
        m = re.search(r"ratio\s+(\d+)\s*:\s*(\d+)(?:\s*:\s*(\d+))?", low)
        if not m or not re.search(r"\bshare|\bdivide|\bsplit", low):
            return None
        ratio_slots = [s.i for s in q.slots if m.start(1) <= s.start < m.end()]
        amt = [g for g in givens if g.slot not in ratio_slots and g.qty in ("money", "number", "count")]
        if not amt:
            return None
        names = re.search(r"(?:between|among|amongst)\s+(.+?)\s+in\s+the\s+ratio", q.display, re.I)
        nm = [x.strip() for x in re.split(r",|\band\b", names.group(1))] if names else None
        if nm and len(nm) != len([g for g in m.groups() if g]):
            nm = None
        g0 = amt[0]
        role = "money" if g0.qty == "money" else "x"
        return Spec(rule=self, pick={role: g0}, ratio_slots=ratio_slots, names=nm, low=low, want=None, unit=None,
                    uses=[g0.slot] + ratio_slots)

    def solve(self, q, spec, vals):
        spec.ratio = [raw(vals, Given(i, "number", 1, "")) for i in spec.ratio_slots]
        W = {r: raw(vals, g) for r, g in spec.pick.items()}
        _, ans, shares, steps, names, money = w_ratio({}, W, spec)
        if any(exact(s).q != 1 for s in shares):                     # whole shares (to the cedi)
            return None
        if len(set(spec.ratio)) < len(spec.ratio):                          # 9:9 isn't a ratio question
            return None
        alt = list(reversed(shares))
        fmtv = (lambda v: f"GHS {float(v):,.2f}") if money else (lambda v: fmt_num(exact(v)))
        wrong = [", ".join(f"{nm}: {fmtv(v)}" for nm, v in zip(names, alt))]
        tot = W.get("money", W.get("x"))
        wrong.append(", ".join(f"{nm}: {fmtv(tot * k / 10)}" for nm, k in zip(names, spec.ratio)))
        wrong.append(", ".join(f"{nm}: {fmtv(v / 2)}" for nm, v in zip(names, shares)))
        return ans, tuple(exact(s) for s in shares), steps, wrong


_SPECIAL: List[Rule] = [ResistorRule("series", w_series), ResistorRule("parallel", w_parallel), RatioRule()]


# ── physics with one formula (P = VI, F = ma, …) ────────────────────────────────────────────────────────────

Sy = sp.symbols
P, V, I, R, Q, C, E, t, f, T = Sy("P V I R Q C E t f T", positive=True)
m, a, F, v, s, k, x, lam, rho, Vol, A, p = Sy("m a F v s k x lam rho Vol A p", positive=True)

FORMULAS = [
    ("P = VI", P - V * I, {P: "power", V: "voltage", I: "current"}),
    ("V = IR", V - I * R, {V: "voltage", I: "current", R: "resistance"}),
    ("P = I²R", P - I ** 2 * R, {P: "power", I: "current", R: "resistance"}),
    ("P = V²/R", P - V ** 2 / R, {P: "power", V: "voltage", R: "resistance"}),
    ("Q = It", Q - I * t, {Q: "charge", I: "current", t: "time"}),
    ("Q = CV", Q - C * V, {Q: "charge", C: "capacitance", V: "voltage"}),
    ("F = ma", F - m * a, {F: "force", m: "mass", a: "acceleration"}),
    ("p = mv", p - m * v, {p: "momentum", m: "mass", v: "speed"}),
    ("ρ = m/V", rho - m / Vol, {rho: "density", m: "mass", Vol: "volume"}),
    ("P = F/A", P - F / A, {P: "pressure", F: "force", A: "area"}),
    ("F = kx", F - k * x, {F: "force", k: "spring", x: "length"}),
    ("W = Fs", E - F * s, {E: "work", F: "force", s: "length"}),
    ("P = W/t", P - E / t, {P: "power", E: "work", t: "time"}),
    ("v = fλ", v - f * lam, {v: "speed", f: "frequency", lam: "wavelength"}),
    ("KE = ½mv²", E - m * v ** 2 / 2, {E: "ke", m: "mass", v: "speed"}),
    ("f = 1/T", f - 1 / T, {f: "frequency", T: "period"}),
]
_SAME = {"work": "energy", "ke": "energy", "wavelength": "length", "heat": "energy", "pe": "energy"}


class FormulaRule(Rule):
    def __init__(self):
        super().__init__("formula", ".", [], None)

    def parse(self, q, low, givens):
        want, unit = asked(low)
        if not want:
            return None
        known = [g for g in givens if g.qty not in ("number", "percent", "money", "count")]
        if not known:
            return None
        for name, eq, qs in FORMULAS:
            inv = {}
            for sym, qq in qs.items():
                inv.setdefault(qq, sym)
            tsym = inv.get(want)
            if tsym is None and want == "energy":
                tsym = inv.get("work") or (inv.get("ke") if re.search(r"kinetic|k\.?e\b|moving", low) else None)
            if tsym is None and want == "distance":
                tsym = next((sy for sy, qq in qs.items() if qq == "length"), None)
            if tsym is None:
                continue
            need = {sym: _SAME.get(qq, qq) for sym, qq in qs.items() if sym != tsym}
            pick, used = {}, set()
            for sym, qq in need.items():
                cands = [g for g in known if g.qty == qq and g.slot not in used]
                if not cands:
                    break
                pick[sym] = cands[0]
                used.add(cands[0].slot)
            if len(pick) != len(need):
                continue
            if [g for g in known if g.slot not in used and not g.const]:
                continue
            return Spec(rule=self, name=name, eq=eq, target=tsym, pick=pick, qty=_SAME.get(qs[tsym], qs[tsym]),
                        unit=unit, want=want, low=low, uses=[g.slot for g in pick.values()])
        return None

    def solve(self, q, spec, vals):
        sub = {sym: si(vals, g) for sym, g in spec.pick.items()}
        sols = [r for r in sp.solve(spec.eq.subs(sub), spec.target) if r.is_positive]
        if len(sols) != 1:
            return None
        r = exact(sols[0])
        unit, out = SI.get(spec.qty, ""), r
        if spec.unit and spec.unit in _U and _U[spec.unit][0] == spec.qty:
            unit, out = spec.unit, r / _U[spec.unit][1]
        ans = show(out, unit, qty=spec.qty)
        rearr = sp.solve(spec.eq, spec.target)[0]
        steps = [f"Use {spec.name}" + ("" if spec.name.startswith(f"{spec.target} =") else
                                       f", so {spec.target} = {sp.sstr(rearr).replace('**', '^').replace('*', '')}") + "."]
        conv = [f"{written(vals, g)} = {show(si(vals, g), SI.get(g.qty, ''))}" for g in spec.pick.values() if g.factor != 1]
        if conv:
            steps.append("In SI units: " + ", ".join(conv) + ".")
        steps.append("Substitute " + ", ".join(f"{sym} = {show(sub[sym], SI.get(_SAME.get(g.qty, g.qty), ''), qty=g.qty)}"
                                               for sym, g in spec.pick.items()) + ".")
        steps.append(f"{spec.target} = {ans}")
        extra = []
        vals_ = list(sub.values())
        if len(vals_) == 2:
            a1, a2 = vals_
            extra += [a1 * a2, a1 / a2, a2 / a1]
        extra.append(r * 2 if "½" in spec.name else r / 2)
        div = _U[spec.unit][1] if spec.unit in _U else 1
        return ans, r, steps, mistakes(out, unit, [e / div for e in extra], qty=spec.qty)


# ── answer first, where clean answers need special numbers ─────────────────────────────────────────────────

_PARALLEL = {2: [(3, 6), (4, 12), (6, 12), (5, 20), (10, 15), (12, 24), (6, 30), (20, 30), (8, 24), (9, 18), (12, 36),
                 (10, 40), (15, 30), (4, 4), (6, 3), (30, 60), (40, 60), (24, 48)],
             3: [(4, 6, 12), (2, 3, 6), (6, 10, 15), (8, 12, 24), (6, 9, 18), (12, 18, 36), (10, 20, 20), (6, 12, 12),
                 (3, 6, 6), (12, 24, 24), (20, 30, 60), (10, 15, 30), (5, 20, 20), (10, 40, 40)]}
_TRIPLES = [(3, 4), (5, 12), (8, 15), (7, 24), (20, 21), (9, 40), (12, 35), (6, 8), (9, 12), (12, 16), (15, 20),
            (10, 24), (15, 36), (16, 30), (24, 32), (18, 24), (21, 28), (30, 40), (11, 60), (28, 45), (33, 56)]


def fix_parallel(q, spec, vals, rng):
    rs = [g for k, g in sorted(spec.pick.items()) if k.startswith("r")]
    sets = _PARALLEL.get(len(rs))
    orig = [q.vals[g.slot] for g in rs]
    if not sets or sum(1 / Fraction(r) for r in orig).denominator > 1 and (1 / sum(1 / Fraction(r) for r in orig)).denominator > 1:
        return vals                                         # the original's total wasn't whole either
    for _ in range(8):
        base = list(rng.choice(sets))
        if rng.random() < 0.5:
            base.reverse()
        if base != [int(o) for o in orig]:
            for g, r in zip(rs, base):
                vals[g.slot] = Fraction(r)
            return vals
    return vals


def fix_free_fall(q, spec, vals, rng):
    if spec.want != "time" or "h" not in spec.pick:
        return vals
    g = spec.pick["h"]
    gval = exact(_g(spec, {r: si(vals, gg) for r, gg in spec.pick.items()}))
    t_old = sp.sqrt(2 * si(q.vals, g) / gval)
    if not exact(t_old).is_Integer:
        return vals
    t_new = rng.choice([k for k in range(2, 11) if k != int(t_old)])
    h = gval * t_new ** 2 / 2 / g.factor
    if exact(h).q != 1:
        return None
    vals[g.slot] = Fraction(int(h))
    return vals


def fix_diagonal(q, spec, vals, rng):
    l, w = spec.pick["l"], spec.pick["w"]
    a, b = int(q.vals[l.slot]), int(q.vals[w.slot])
    if not sp.sqrt(a * a + b * b).is_Integer:
        return vals
    x, y = rng.choice([t for t in _TRIPLES if sorted(t) != sorted((a, b))])
    if a > b:
        x, y = max(x, y), min(x, y)
    else:
        x, y = min(x, y), max(x, y)
    vals[l.slot], vals[w.slot] = Fraction(x), Fraction(y)
    return vals


_FIXES = {"parallel": fix_parallel, "free fall": fix_free_fall, "diagonal": fix_diagonal}


# ── the family ───────────────────────────────────────────────────────────────────────────────────────────────

_READ_AS = {
    "series": "resistors in series: R = R₁ + R₂ + …", "parallel": "resistors in parallel: 1/R = 1/R₁ + 1/R₂ + …",
    "transformer": "a transformer: Vs/Vp = Ns/Np", "transformer turns": "a transformer: Ns/Np = Vs/Vp",
    "cost": "cost = power (kW) × time (h) × price per kWh", "cap energy": "energy in a capacitor: E = ½CV²",
    "reactance L": "an inductor's reactance: X = 2πfL", "reactance C": "a capacitor's reactance: X = 1/(2πfC)",
    "period": "T = 1/f", "energy Pt": "energy = power × time", "free fall": "falling from rest: h = ½gt²",
    "suvat": "steady acceleration: v = u + at", "avg speed": "speed = distance ÷ time", "pe": "potential energy: mgh",
    "lift power": "power = mgh ÷ time", "heat": "heat: Q = mcΔθ", "heat dT": "heat: Q = mcΔθ",
    "boyle": "Boyle's law: p₁V₁ = p₂V₂", "weight": "weight: W = mg",
    "compound": "compound interest: A = P(1 + R/100)^n", "depreciation": "depreciation: V = P(1 - R/100)^n",
    "simple interest": "simple interest: I = PRT/100", "profit": "profit or loss % = change ÷ cost price × 100",
    "discount": "a discount off the marked price", "percent of": "a percentage of an amount",
    "change by": "increasing or decreasing by a percentage", "inverse": "inverse proportion (more workers, less time)",
    "proportion": "direct proportion (the cost of one, then of many)", "convert speed": "1 km/h = 5/18 m/s",
    "sphere": "a sphere: V = (4/3)πr³", "cylinder": "a cylinder: V = πr²h", "cone": "a cone: V = (1/3)πr²h",
    "circle area": "a circle: A = πr²", "circumference": "a circle: C = 2πr", "trapezium": "a trapezium: A = ½(a + b)h",
    "diagonal": "Pythagoras: d = √(l² + w²)", "cube": "a cube", "cuboid": "a cuboid", "rectangle": "a rectangle",
    "triangle": "a triangle: A = ½ × base × height", "ratio": "sharing in a ratio",
}


class WordProblem(Family):
    name = "word_problem"
    kind = "word_problem"

    def parse(self, q: Question) -> Optional[Spec]:
        low = q.display.lower()
        if len(re.findall(r"[a-z]{3,}", low)) < 1 or len(re.findall(r"[a-z]{2,}", low)) < 2:   # words, not bare maths
            return None
        givens = read_givens(q)
        if not givens:
            return None
        for rule in _SPECIAL + RULES + [FormulaRule()]:
            try:
                spec = rule.parse(q, low, givens)
            except Exception:                                                # noqa: BLE001
                spec = None
            if spec is None:
                continue
            if rule.solve(q, spec, q.vals) is None:
                continue
            spec.givens = givens
            spec.free = [i for i in spec.uses if not next((g.const for g in givens if g.slot == i), False)
                         and q.slots[i].role in ("num", "coef") and q.slots[i].value > 0]
            spec.pi7 = pi_of(low) == sp.Rational(22, 7)
            return spec
        return None

    def solve(self, q: Question, spec: Spec, vals, full: bool = True) -> Optional[Item]:
        try:
            res = spec.rule.solve(q, spec, vals)
        except Exception:                                                    # noqa: BLE001
            return None
        if res is None:
            return None
        ans, value, steps, wrong = res
        text = q.render(vals)
        if not full:
            return Item(text, ans, [], [], self.kind, value=value)
        return Item(text, ans, steps, [w for w in wrong if w and w != ans], self.kind, value=value)

    def vary(self, q: Question, spec: Spec, rng: random.Random):
        vals = list(q.vals)
        for i in spec.free:
            if getattr(spec, "pi7", False) and next((g.tag in ("radius", "diameter", "") and g.qty == "length"
                                                      for g in spec.givens if g.slot == i), False):
                base = float(q.vals[i])
                choices = [c for c in (sp.Rational(7, 2), 7, sp.Rational(21, 2), 14, 21, 28, 35, 42, 49, 56, 70)
                           if base / 3 <= float(c) <= base * 3 and c != q.vals[i]]
                if choices:
                    vals[i] = Fraction(str(rng.choice(choices)))
                    continue
            vals[i] = new_value(q.slots[i], rng)
        fix = _FIXES.get(spec.rule.name)
        if fix is not None:                                 # answer first: numbers that give a clean answer
            vals = fix(q, spec, vals, rng)
            if vals is None:
                return None
        by_qty = {}
        for g in spec.givens:                               # two different pressures must stay different
            if g.slot in spec.uses:
                by_qty.setdefault(g.qty, []).append(g.slot)
        for slots in by_qty.values():
            if len(slots) > 1 and len({q.vals[i] for i in slots}) == len(slots) and len({vals[i] for i in slots}) < len(slots):
                return None
        return vals

    def describe(self, spec) -> str:
        """How the question was read, shown to the student (a misread word problem is then plain to see)."""
        r = spec.rule
        if r.name == "formula":
            return f"{spec.name}, finding the {spec.want if spec.want not in ('ke', 'pe') else 'energy'}"
        return _READ_AS.get(r.name, r.name)

    def nice(self, base: Item, item: Item) -> bool:
        b, v = base.value, item.value
        money = "GHS" in base.answer
        if isinstance(b, tuple):
            return isinstance(v, tuple) and len(v) == len(b) and all(self._ok(x, y, money) for x, y in zip(v, b))
        if re.search(r"\bwater\b", base.question.lower()):
            if any(int(t) > 100 for t in re.findall(r"(\d+)\s*°C", item.question)):
                return False                                 # water boils at 100 °C
        return self._ok(v, b, money)

    @staticmethod
    def _ok(v, b, money: bool = True) -> bool:
        try:
            fv, fb = float(v), float(b)
        except (TypeError, ValueError):
            return True
        if fv <= 0 < fb or not math.isfinite(fv):
            return False
        if fb != 0 and not (fb / 25 <= fv <= fb * 25):
            return False
        bb = exact(b)
        if bb.is_Rational:
            vv = exact(v)
            if bb.q == 1:                                   # a whole answer stays whole (money: to the pesewa)
                return vv.is_Rational and (vv.q == 1 or (money and (vv * 100).q == 1 and abs(fb) >= 100))
            return like(vv, bb) or (vv.is_Rational and (vv * 100).q == 1)
        return True
