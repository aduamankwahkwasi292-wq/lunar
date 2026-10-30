"""Units: read '250 mA', '9.8 m/s^2', '20 °C', 'J kg^-1 K^-1', 'GH₵/kWh' into an SI factor and dimensions.

A value in SI is value * factor + offset. Only °C and °F have an offset; the engine decides whether such a value
is a temperature (use the offset) or a temperature change (don't).
"""
import math
import re
from dataclasses import dataclass

DIMS = ("m", "kg", "s", "A", "K", "mol", "cd", "bit", "cur")


def dim(**kw) -> tuple:
    return tuple(kw.get(d, 0) for d in DIMS)


NONE = dim()


@dataclass(frozen=True)
class Unit:
    factor: float
    dims: tuple
    offset: float = 0.0
    label: str = ""

    def times(self, other: "Unit") -> "Unit":
        return Unit(self.factor * other.factor, tuple(a + b for a, b in zip(self.dims, other.dims)))

    def power(self, n: int) -> "Unit":
        return Unit(self.factor ** n, tuple(a * n for a in self.dims))


_E = dim(kg=1, m=2, s=-2)          # energy
_P = dim(kg=1, m=2, s=-3)          # power
_PA = dim(kg=1, m=-1, s=-2)        # pressure
_SI = ("Y", "Z", "E", "P", "T", "G", "M", "k", "h", "da", "d", "c", "m", "µ", "μ", "u", "n", "p", "f")
_BIG = ("k", "K", "M", "G", "T", "P")
_BINARY = ("Ki", "Mi", "Gi", "Ti")
PREFIX = {"Y": 1e24, "Z": 1e21, "E": 1e18, "P": 1e15, "T": 1e12, "G": 1e9, "M": 1e6, "k": 1e3, "K": 1e3, "h": 1e2,
          "da": 1e1, "d": 1e-1, "c": 1e-2, "m": 1e-3, "µ": 1e-6, "μ": 1e-6, "u": 1e-6, "n": 1e-9, "p": 1e-12,
          "f": 1e-15, "a": 1e-18, "Ki": 1024.0, "Mi": 1024.0 ** 2, "Gi": 1024.0 ** 3, "Ti": 1024.0 ** 4}

# symbol: (factor to SI, dimensions, prefixes allowed)
BASE = {
    "m": (1, dim(m=1), _SI), "g": (1e-3, dim(kg=1), _SI), "s": (1, dim(s=1), _SI), "A": (1, dim(A=1), _SI),
    "K": (1, dim(K=1), ()), "mol": (1, dim(mol=1), _SI), "cd": (1, dim(cd=1), ()),
    "Hz": (1, dim(s=-1), _SI), "N": (1, dim(kg=1, m=1, s=-2), _SI), "J": (1, _E, _SI), "W": (1, _P, _SI),
    "Pa": (1, _PA, _SI), "C": (1, dim(A=1, s=1), _SI), "V": (1, dim(kg=1, m=2, s=-3, A=-1), _SI),
    "Ω": (1, dim(kg=1, m=2, s=-3, A=-2), _SI), "F": (1, dim(kg=-1, m=-2, s=4, A=2), _SI),
    "H": (1, dim(kg=1, m=2, s=-2, A=-2), _SI), "Wb": (1, dim(kg=1, m=2, s=-2, A=-1), _SI),
    "T": (1, dim(kg=1, s=-2, A=-1), _SI), "S": (1, dim(kg=-1, m=-2, s=3, A=2), _SI),
    "L": (1e-3, dim(m=3), _SI), "M": (1e3, dim(mol=1, m=-3), ("m", "µ", "μ", "u", "n")),
    "eV": (1.602176634e-19, _E, _SI), "Wh": (3600.0, _E, _SI), "cal": (4.184, _E, _SI),
    "VA": (1, _P, _SI), "var": (1, _P, _SI), "VAR": (1, _P, _SI), "Ah": (3600.0, dim(A=1, s=1), _SI),
    "bar": (1e5, _PA, _SI), "atm": (101325.0, _PA, ()), "mmHg": (133.322, _PA, ()), "Bq": (1, dim(s=-1), _SI),
    "Gy": (1, dim(m=2, s=-2), _SI), "Sv": (1, dim(m=2, s=-2), _SI), "D": (1, dim(m=-1), ()),
    "min": (60.0, dim(s=1), ()), "h": (3600.0, dim(s=1), ()), "hr": (3600.0, dim(s=1), ()),
    "t": (1000.0, dim(kg=1), ()), "Å": (1e-10, dim(m=1), ()), "rad": (1, NONE, ("m",)),
    "°": (math.pi / 180, NONE, ()), "%": (0.01, NONE, ()),
    "bit": (1, dim(bit=1), _BIG + _BINARY), "b": (1, dim(bit=1), _BIG + _BINARY),
    "B": (8, dim(bit=1), _BIG + _BINARY), "bps": (1, dim(bit=1, s=-1), _BIG),
    "Nm": (1, _E, ("k",)), "rpm": (1 / 60, dim(s=-1), ()), "rps": (1, dim(s=-1), ()),
    "At": (1, dim(A=1), ("k", "m")), "mph": (0.44704, dim(m=1, s=-1), ()), "kph": (1 / 3.6, dim(m=1, s=-1), ()),
    "ft": (0.3048, dim(m=1), ()), "yd": (0.9144, dim(m=1), ()),
    "mi": (1609.344, dim(m=1), ()), "lb": (0.45359237, dim(kg=1), ()), "hp": (745.7, _P, ()),
    "GH₵": (1, dim(cur=1), ()), "GHS": (1, dim(cur=1), ()), "GHC": (1, dim(cur=1), ()), "₵": (1, dim(cur=1), ()),
    "$": (1, dim(cur=1), ()), "USD": (1, dim(cur=1), ()), "£": (1, dim(cur=1), ()), "€": (1, dim(cur=1), ()),
    "Gp": (0.01, dim(cur=1), ()),
}
# Temperatures with an offset (value in K = value * factor + offset).
OFFSET = {"°C": (1.0, 273.15), "℃": (1.0, 273.15), "°F": (5 / 9, 273.15 - 32 * 5 / 9), "℉": (5 / 9, 273.15 - 32 * 5 / 9)}
# Data: school ICT uses 1 KB = 1024 bytes; network rates stay decimal (kbps = 1000 bit/s).
_DATA_BINARY = {"KB": 1024.0, "MB": 1024.0 ** 2, "GB": 1024.0 ** 3, "TB": 1024.0 ** 4}

# Spelled-out units (lower case, singular). Prefix words combine with these: "kilometres", "milliamps".
NAMES = {
    "metre": "m", "meter": "m", "gram": "g", "gramme": "g", "second": "s", "sec": "s", "ampere": "A", "amp": "A",
    "kelvin": "K", "mole": "mol", "hertz": "Hz", "newton": "N", "joule": "J", "watt": "W", "pascal": "Pa",
    "coulomb": "C", "volt": "V", "ohm": "Ω", "farad": "F", "henry": "H", "henrie": "H", "weber": "Wb",
    "tesla": "T", "siemen": "S", "siemens": "S", "litre": "L", "liter": "L", "minute": "min", "hour": "h",
    "day": (86400.0, dim(s=1)), "week": (604800.0, dim(s=1)), "year": (3.15576e7, dim(s=1)),
    "annum": (3.15576e7, dim(s=1)), "month": (3.15576e7 / 12, dim(s=1)), "tonne": "t", "ton": "t",
    "degree": "°", "radian": "rad", "percent": "%", "byte": "B", "electronvolt": "eV", "calorie": "cal",
    "bit": "bit", "inch": (0.0254, dim(m=1)), "inche": (0.0254, dim(m=1)), "foot": "ft", "feet": "ft", "mile": "mi", "pound": "lb", "dioptre": "D",
    "diopter": "D", "becquerel": "Bq", "cedi": "GH₵", "pesewa": "Gp", "dollar": "$", "bar": "bar",
    "atmosphere": "atm", "rev": (1, NONE), "revolution": (1, NONE),
    "kilohm": (1e3, dim(kg=1, m=2, s=-3, A=-2)), "megohm": (1e6, dim(kg=1, m=2, s=-3, A=-2)),
}
PREFIX_WORDS = {"kilo": "k", "mega": "M", "giga": "G", "tera": "T", "milli": "m", "micro": "µ", "nano": "n",
                "pico": "p", "centi": "c", "deci": "d"}
# Words that count things: dimensionless, but the word itself tells the engine what was counted.
COUNTS = {"turn", "turns", "pole", "poles", "cycle", "cycles", "revolutions", "electrons", "electron", "molecules",
          "atoms", "particles", "nuclei", "photons", "cells", "people", "individuals", "organisms", "students",
          "items", "times", "oscillations", "waves", "beats", "slits", "lines", "conductors", "coils", "phases",
          "pixels", "pixel", "breaths", "terms", "sides", "paths"}

# Unit-looking tokens that are something else after a number ("at 5 pm").
_NOT_UNITS = {"pm", "am"}

_SUP = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁻", "0123456789-")


def _lookup(sym: str):
    """One unit symbol, maybe prefixed: 'kΩ' → (1000, dims of Ω)."""
    if sym in OFFSET:                                      # inside a compound ("J/(kg °C)") it's a difference
        return OFFSET[sym][0], dim(K=1)
    if sym in _NOT_UNITS:
        return None
    if sym.lower() in COUNTS:
        return 1.0, NONE
    if sym in BASE:
        f, d, _ = BASE[sym]
        return float(f), d
    if sym in _DATA_BINARY:
        return _DATA_BINARY[sym] * 8, dim(bit=1)
    if sym in ("Kbps",):
        return 1e3, dim(bit=1, s=-1)
    for p in sorted(PREFIX, key=len, reverse=True):
        if sym.startswith(p) and len(sym) > len(p):
            rest = sym[len(p):]
            if rest in BASE and p in BASE[rest][2]:
                f, d, _ = BASE[rest]
                return PREFIX[p] * f, d
    word = sym.lower()
    for w in (word, word[:-1] if word.endswith("s") else word, word[:-2] if word.endswith("es") else word):
        hit = NAMES.get(w)
        if hit is None:
            for pw, p in PREFIX_WORDS.items():
                if w.startswith(pw) and NAMES.get(w[len(pw):]) and isinstance(NAMES[w[len(pw):]], str):
                    base = NAMES[w[len(pw):]]
                    f, d, allowed = BASE[base]
                    if p in allowed or p == "µ":
                        return PREFIX[p] * f, d
            continue
        if isinstance(hit, tuple):
            return float(hit[0]), hit[1]
        f, d, _ = BASE[hit]
        return float(f), d
    return None


def _normalise(text: str) -> str:
    s = text.strip().translate(_SUP)
    s = s.replace("·", " ").replace("⋅", " ").replace("•", " ").replace("−", "-").replace("–", "-")
    s = re.sub(r"\s*\bp\.a\.?$", "/annum", s, flags=re.I)              # 5 % p.a. (never "Pa", the pascal)
    s = re.sub(r"(?<=[A-Za-zΩµμ])\*(?=[A-Za-zΩµμ])", " ", s)
    s = re.sub(r"(?<=[A-Za-zΩµμ])\.(?=[A-Za-zΩµμ])", " ", s)          # "N.m", "kg.m^-3"
    s = re.sub(r"\bper\b", "/", s, flags=re.I)
    s = re.sub(r"\bsquared\b", "^2", s)
    s = re.sub(r"\bcubed\b", "^3", s)
    s = re.sub(r"\bdegrees?\s+(celsius|centigrade)\b", "°C", s, flags=re.I)
    s = re.sub(r"\b(celsius|centigrade)\b", "°C", s, flags=re.I)
    s = re.sub(r"\bdegrees?\s+fahrenheit\b|\bfahrenheit\b", "°F", s, flags=re.I)
    s = re.sub(r"°\s*C\b", "°C", s)
    s = re.sub(r"(?<=[A-Za-z])°", " °", s)                              # "J/kg°C"
    s = re.sub(r"(?<=[A-Za-zΩ])(-?\d)$", r"^\1", s)                    # "m2", "s-1" at the end
    s = re.sub(r"(?<=[A-Za-zΩ])(-?\d)(?=[\s/)])", r"^\1", s)            # "m2 s-1"
    return re.sub(r"\s+", " ", s).strip()


def _part(text: str):
    """Space-separated factors: 'kg m^-3' → product."""
    total = Unit(1.0, NONE)
    for tok in text.split():
        m = re.fullmatch(r"\(?([^\^()]+?)\)?(?:\^\(?(-?\d+)\)?)?", tok)
        if not m:
            return None
        hit = _lookup(m.group(1))
        if hit is None:
            return None
        total = total.times(Unit(hit[0], hit[1]).power(int(m.group(2) or 1)))
    return total


def parse_unit(text: str):
    """'m/s^2' → Unit(1, m s^-2). None if any piece isn't a unit."""
    raw = (text or "").strip()
    if not raw:
        return None
    s = _normalise(raw)
    if s in OFFSET:
        f, off = OFFSET[s]
        return Unit(f, dim(K=1), off, raw)
    if s.lower() in COUNTS:
        return Unit(1.0, NONE, 0.0, s.lower())
    pieces, depth, cur = [], 0, ""
    for ch in s:                                           # split on '/' outside brackets
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "/" and depth == 0:
            pieces.append(cur)
            cur = ""
        else:
            cur += ch
    pieces.append(cur)
    if any(not p.strip() for p in pieces):
        return None
    total = None
    for i, p in enumerate(pieces):
        u = _part(p.strip().strip("()") if p.strip().startswith("(") and p.strip().endswith(")") else p.strip())
        if u is None:
            return None
        total = u if i == 0 else total.times(u.power(-1))
    return Unit(total.factor, total.dims, 0.0, raw)



def unit_after(text: str):
    """The longest unit at the start of `text` (what follows a number). Returns (Unit, length used) or (None, 0)."""
    s = text[:40]
    m = re.match(r"\s*", s)
    lead = m.end()
    body = s[lead:]
    stop = re.search(r"[,;:?!]|\.(\s|$)|\s(and|or|for|with|in|at|on|of|from|to|by|is|if|when|then|find|calculate)\b",
                     body)
    if stop:
        body = body[:stop.start()]
    words = body.split(" ")
    for n in range(len(words), 0, -1):
        cand = " ".join(words[:n]).strip()
        if not cand:
            continue
        cand = cand.rstrip(".")
        if cand.count(")") > cand.count("("):
            cand = cand.rstrip(")")
        u = parse_unit(cand)
        if u is None:
            continue
        return Unit(u.factor, u.dims, u.offset, cand), lead + len(cand)
    return None, 0


# ── showing units ─────────────────────────────────────────────────────────
_NAMED = {dim(m=1): "m", dim(kg=1): "kg", dim(s=1): "s", dim(A=1): "A", dim(K=1): "K", dim(mol=1): "mol",
          dim(kg=1, m=1, s=-2): "N", _E: "J", _P: "W", _PA: "Pa", dim(A=1, s=1): "C",
          dim(kg=1, m=2, s=-3, A=-1): "V", dim(kg=1, m=2, s=-3, A=-2): "Ω", dim(kg=-1, m=-2, s=4, A=2): "F",
          dim(kg=1, m=2, s=-2, A=-2): "H", dim(kg=1, m=2, s=-2, A=-1): "Wb", dim(kg=1, s=-2, A=-1): "T",
          dim(kg=-1, m=-2, s=3, A=2): "S", dim(s=-1): "Hz", dim(m=1, s=-1): "m/s", dim(m=1, s=-2): "m/s²",
          dim(m=2): "m²", dim(m=3): "m³", dim(kg=1, m=-3): "kg/m³", dim(kg=1, m=1, s=-1): "kg m/s",
          dim(kg=1, m=2): "kg m²", dim(kg=1, s=-2): "N/m", dim(mol=1, m=-3): "mol/m³", dim(kg=1, mol=-1): "kg/mol",
          dim(m=2, s=-2, K=-1): "J/(kg K)", dim(m=2, s=-2): "J/kg", dim(kg=1, m=2, s=-2, K=-1): "J/K",
          dim(kg=1, m=2, s=-2, mol=-1): "J/mol", dim(kg=1, m=2, s=-2, mol=-1, K=-1): "J/(mol K)",
          dim(kg=1, m=1, s=-3, K=-1): "W/(m K)", dim(K=-1): "/K", dim(m=-1): "m⁻¹", dim(A=1, m=-1): "A/m",
          dim(kg=1, m=1, s=-2, A=-2): "H/m", dim(kg=-1, m=-2, s=2, A=2): "A/Wb", dim(kg=1, s=-3): "W/m²",
          dim(kg=1, m=3, s=-3, A=-2): "Ω m", dim(kg=1, m=1, s=-3, A=-1): "V/m", dim(m=3, s=-1): "m³/s",
          dim(bit=1): "bit", dim(bit=1, s=-1): "bit/s", dim(cur=1): "GH₵", dim(kg=1, m=-2): "kg/m²",
          dim(mol=1, m=-3, s=-1): "mol/(m³ s)", dim(kg=1, s=-1): "kg/s", dim(m=-2): "m⁻²", dim(cur=1, s=-1): "GH₵/s"}

_SUPER = str.maketrans("0123456789-", "⁰¹²³⁴⁵⁶⁷⁸⁹⁻")


def si_label(dims: tuple) -> str:
    if dims in _NAMED:
        return _NAMED[dims]
    if dims == NONE:
        return ""
    names = ("m", "kg", "s", "A", "K", "mol", "cd", "bit", "GH₵")
    top = [n + (str(p).translate(_SUPER) if p != 1 else "") for n, p in zip(names, dims) if p > 0]
    bottom = [n + (str(-p).translate(_SUPER) if p != -1 else "") for n, p in zip(names, dims) if p < 0]
    if not top:
        return " ".join(n + str(p).translate(_SUPER) for n, p in zip(names, dims) if p)
    return " ".join(top) + ("/" + (bottom[0] if len(bottom) == 1 else "(" + " ".join(bottom) + ")") if bottom else "")


def fmt_num(x: float, sig: int = 4) -> str:
    """4 significant figures, plain digits for everyday sizes, 'a × 10^n' for very large or small ones."""
    if x is None or x != x:
        return "?"
    if x == 0:
        return "0"
    if 1 <= abs(x) < 1e7 and abs(x - round(x)) < 1e-9 * abs(x):           # (not 4e-11 → '0')
        return str(int(round(x)))
    e = math.floor(math.log10(abs(x)))
    if -3 <= e < 7:
        s = f"{x:.{max(0, sig - 1 - e)}f}"
        return s.rstrip("0").rstrip(".") if "." in s else s
    mant = f"{x / 10 ** e:.{sig - 1}f}".rstrip("0").rstrip(".")
    return f"{mant} × 10^{e}"
