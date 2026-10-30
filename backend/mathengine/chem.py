"""Chemical formulas: molar mass of 'H2SO4', 'Ca(OH)2', 'CuSO4·5H2O' with school relative atomic masses."""
import re

# Relative atomic masses as WASSCE / school data sheets give them.
AR = {
    "H": 1, "He": 4, "Li": 7, "Be": 9, "B": 11, "C": 12, "N": 14, "O": 16, "F": 19, "Ne": 20, "Na": 23, "Mg": 24,
    "Al": 27, "Si": 28, "P": 31, "S": 32, "Cl": 35.5, "Ar": 40, "K": 39, "Ca": 40, "Sc": 45, "Ti": 48, "V": 51,
    "Cr": 52, "Mn": 55, "Fe": 56, "Co": 59, "Ni": 59, "Cu": 63.5, "Zn": 65, "Ga": 70, "Ge": 73, "As": 75, "Se": 79,
    "Br": 80, "Kr": 84, "Rb": 85.5, "Sr": 88, "Y": 89, "Zr": 91, "Nb": 93, "Mo": 96, "Ag": 108, "Cd": 112,
    "Sn": 119, "Sb": 122, "I": 127, "Xe": 131, "Cs": 133, "Ba": 137, "W": 184, "Pt": 195, "Au": 197, "Hg": 201,
    "Pb": 207, "Bi": 209, "Ra": 226, "U": 238,
}
NAMES = {"hydrogen": "H2", "oxygen": "O2", "nitrogen": "N2", "chlorine": "Cl2", "carbon": "C", "sodium": "Na",
         "magnesium": "Mg", "aluminium": "Al", "aluminum": "Al", "calcium": "Ca", "iron": "Fe", "copper": "Cu",
         "zinc": "Zn", "sulphur": "S", "sulfur": "S", "potassium": "K", "silver": "Ag", "gold": "Au", "lead": "Pb",
         "water": "H2O", "carbon dioxide": "CO2", "methane": "CH4", "ammonia": "NH3", "glucose": "C6H12O6",
         "sodium chloride": "NaCl", "ethanol": "C2H5OH", "sulphuric acid": "H2SO4", "sulfuric acid": "H2SO4",
         "hydrochloric acid": "HCl", "nitric acid": "HNO3", "sodium hydroxide": "NaOH", "calcium carbonate": "CaCO3",
         "potassium hydroxide": "KOH", "ethanoic acid": "CH3COOH", "acetic acid": "CH3COOH", "magnesium oxide": "MgO",
         "copper sulphate": "CuSO4", "copper(ii) sulphate": "CuSO4", "sodium carbonate": "Na2CO3", "sucrose": "C12H22O11",
         "helium": "He", "argon": "Ar", "neon": "Ne"}

_TOKEN = re.compile(r"([A-Z][a-z]?)(\d*)|(\()|(\))(\d*)")
_SUB = str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789")


def _parse(formula: str):
    """'Ca(OH)2' → {'Ca': 1, 'O': 2, 'H': 2}; None if it isn't a valid formula."""
    f = formula.translate(_SUB).replace(" ", "")
    parts = re.split(r"[·.*•]", f)
    total = {}
    for part in parts:
        m = re.match(r"^(\d*)(.+)$", part)
        mult = int(m.group(1)) if m and m.group(1) else 1
        body = m.group(2) if m else part
        stack, pos = [{}], 0
        while pos < len(body):
            t = _TOKEN.match(body, pos)
            if not t or t.end() == pos:
                return None
            el, n, opn, cls, cn = t.groups()
            if el:
                if el not in AR:
                    return None
                stack[-1][el] = stack[-1].get(el, 0) + (int(n) if n else 1)
            elif opn:
                stack.append({})
            else:
                if len(stack) < 2:
                    return None
                inner = stack.pop()
                k = int(cn) if cn else 1
                for e, c in inner.items():
                    stack[-1][e] = stack[-1].get(e, 0) + c * k
            pos = t.end()
        if len(stack) != 1:
            return None
        for e, c in stack[0].items():
            total[e] = total.get(e, 0) + c * mult
    return total or None


def molar_mass(formula: str):
    """(g/mol, working) for a formula, or None."""
    counts = _parse(formula)
    if not counts:
        return None
    terms = [f"{c} × {AR[e]:g}" if c > 1 else f"{AR[e]:g}" for e, c in counts.items()]
    value = sum(AR[e] * c for e, c in counts.items())
    shown = formula.translate(str.maketrans("0123456789", "₀₁₂₃₄₅₆₇₈₉"))
    return value, f"M({shown}) = {' + '.join(terms)} = {value:g} g/mol"


_CANDIDATE = re.compile(r"(?<![A-Za-z0-9])(\d?(?:[A-Z][a-z]?\d*|\((?:[A-Z][a-z]?\d*)+\)\d*)+"
                        r"(?:[·.*•]\d*(?:[A-Z][a-z]?\d*)+)?)(?![A-Za-z0-9])")


def formulas_in(text: str) -> list:
    """Chemical formulas named in a question: 'H2SO4', 'CaCO3', or names like 'sodium chloride'."""
    out = []
    low = text.lower()
    for name in sorted(NAMES, key=len, reverse=True):
        if re.search(r"\b" + re.escape(name) + r"\b", low):
            out.append(NAMES[name])
            low = low.replace(name, " ")
    for m in _CANDIDATE.finditer(text):
        f = m.group(1)
        counts = _parse(f)
        if not counts:
            continue
        # Single capitals ("V", "I", "C") are symbols, not chemicals; need two elements or a count.
        if len(counts) < 2 and not re.search(r"\d", f) and len(f) < 2:
            continue
        if len(counts) < 2 and not re.search(r"\d", f) and not re.search(r"\b(of|mass of|moles of|sample of)\s+" +
                                                                        re.escape(f) + r"\b", text):
            continue
        out.append(f)
    seen, uniq = set(), []
    for f in out:
        if f not in seen:
            seen.add(f)
            uniq.append(f)
    return uniq
