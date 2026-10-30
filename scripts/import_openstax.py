"""Import formulas from OpenStax "Key Equations" pages (CC BY 4.0) into backend/mathengine/library_books.py.

    python scripts/import_openstax.py [raw_dir]      # raw_dir: the downloaded *.html pages (book--chapter.html)

Each equation is converted from MathML to sympy. Each symbol is given a quantity from textbook conventions (and the
equation's name), and only readings that are dimensionally consistent are kept. Calculus and vector forms are
skipped. Prints a report: kept, skipped (and why), and any disagreement with the hand-written library.
"""
import collections
import glob
import html
import itertools
import os
import re
import sys
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from backend.mathengine import library as L                      # noqa: E402
from backend.mathengine.formulas import dims_of, library          # noqa: E402
from backend.mathengine.units import parse_unit, NONE              # noqa: E402

RAW = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(ROOT), "..", "books", "raw")
OUT = os.path.join(ROOT, "backend", "mathengine", "library_books.py")
BOOKS = {"university-physics-volume-1": "University Physics Volume 1", "university-physics-volume-2": "University Physics Volume 2",
         "university-physics-volume-3": "University Physics Volume 3", "chemistry-2e": "Chemistry 2e", "physics": "Physics"}

GREEK = {"λ": "lam", "θ": "theta", "ω": "omega", "ρ": "rho", "μ": "mu", "ε": "eps", "η": "eta", "φ": "phi", "ϕ": "phi",
         "Φ": "Phi", "τ": "tau", "σ": "sigma", "α": "alpha", "β": "beta", "γ": "gamma", "π": "pi", "ν": "nu",
         "ψ": "psi", "Ω": "Omega", "κ": "kappa", "χ": "chi", "ξ": "xi", "Γ": "Gamma", "Λ": "Lam", "δ": "delta",
         "ζ": "zeta", "Σ": "Sigma", "ℏ": "hbar", "Ψ": "Psi", "υ": "upsilon"}
FUNCS = {"sin", "cos", "tan", "ln", "log", "exp", "sinh", "cosh", "arcsin", "arccos", "arctan"}


from backend.mathengine.symbols import Skip  # noqa: E402


def _text(e):
    return "".join(e.itertext()).strip()


LOOKALIKE = str.maketrans({"Τ": "T", "Β": "B", "Α": "A", "Ε": "E", "Ζ": "Z", "Η": "H",
                           "Ι": "I", "Κ": "K", "Μ": "M", "Ν": "N", "Ο": "O", "Ρ": "P",
                           "Χ": "X", "Υ": "Y", "ℓ": "l", "​": ""})


def _name(s):
    s = s.translate(LOOKALIKE).replace(" ", "").replace(" ", "")
    out = "".join(GREEK.get(ch, ch) for ch in s)
    out = re.sub(r"[^A-Za-z0-9_]", "", out)
    return out


class Conv:
    """Presentation MathML → a sympy-ready string."""

    def __init__(self):
        self.symbols = set()

    def node(self, e):
        tag = e.tag.split("}")[-1]
        if tag in ("math", "semantics", "mrow", "mstyle", "mpadded", "mphantom"):
            return self.row(list(e))
        if tag in ("annotation", "annotation-xml", "mspace"):
            return ("none", "")
        if tag == "mtext" and _text(e).strip() in ("−", "-", "+", "/", "(", ")", "=", "×", "·", "′"):
            mo = ET.Element("mo")
            mo.text = _text(e).strip()
            return self.node(mo)
        if tag == "mi" or tag == "mtext":
            t = _text(e).translate(LOOKALIKE)
            if not t or t in (" ", " "):
                return ("none", "")
            if t == "Δ":
                return ("delta", "")
            if t in ("d", "∂") and tag == "mi":
                return ("operand", "d__")             # a differential: rejected when it's a derivative
            if t in FUNCS:
                return ("func", "log" if t == "ln" else ("exp" if t == "exp" else t))
            if re.fullmatch(r"[A-Za-z]{2,}", t) and tag == "mtext" and t.lower() in ("total", "avg", "max", "min"):
                return ("operand", "_" + t.lower())
            n = _name(t)
            if not n:
                raise Skip(f"odd text {t!r}")
            if n == "pi":
                return ("operand", "pi")
            if n == "e" and tag == "mi":
                return ("operand", "e")
            self.symbols.add(n)
            return ("operand", n)
        if tag == "mn":
            t = _text(e).replace(",", "").replace(" ", "").replace(" ", "").replace("−", "-")
            if re.fullmatch(r"-\d+(\.\d+)?", t):
                return ("operand", f"({t})")
            if not re.fullmatch(r"\d+(\.\d+)?", t):
                raise Skip(f"odd number {t!r}")
            return ("operand", t)
        if tag == "mo":
            t = _text(e)
            if t in ("=", "≡", "≈"):
                return ("eq", "=")
            if t in ("+",):
                return ("op", "+")
            if t in ("−", "-", "–"):
                return ("op", "-")
            if t in ("×", "·", "⋅", "*"):
                return ("op", "*")
            if t == "/":
                return ("op", "/")
            if t in ("(", "["):
                return ("open", "(")
            if t in (")", "]"):
                return ("close", ")")
            if t in ("′", "'"):
                return ("prime", "")
            if t in ("⁡", "⁢", ""):
                return ("none", "")
            raise Skip(f"operator {t!r}")
        if tag == "msub":
            base, sub = list(e)[:2]
            b = self.node(base)
            if b[0] != "operand" or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", b[1]):
                raise Skip("subscript on an expression")
            s = _name(_text(sub))
            if not s:
                raise Skip("odd subscript")
            n = f"{b[1]}_{s}"
            self.symbols.discard(b[1])
            self.symbols.add(n)
            return ("operand", n)
        if tag == "msup":
            base, sup = list(e)[:2]
            b = self.node(base)
            p = self.node(sup)
            if b[0] != "operand" or p[0] != "operand":
                if p[0] == "prime" or _text(sup) in ("′", "*"):
                    return b
                raise Skip("odd power")
            if b[1] == "e":
                return ("operand", f"exp({p[1]})")
            return ("operand", f"({b[1]})**({p[1]})")
        if tag == "msubsup":
            base, sub, sup = list(e)[:3]
            b = self.node(ET.Element("msub")) if False else None
            m = ET.Element("msub")
            m.append(base)
            m.append(sub)
            b = self.node(m)
            p = self.node(sup)
            return ("operand", f"({b[1]})**({p[1]})")
        if tag == "mfrac":
            a, b = list(e)[:2]
            x, y = self.node(a), self.node(b)
            if "d__" in x[1] or "d__" in y[1]:
                raise Skip("derivative")
            return ("operand", f"(({x[1]})/({y[1]}))")
        if tag == "msqrt":
            x = self.row(list(e))
            return ("operand", f"sqrt({x[1]})")
        if tag == "mroot":
            a, n = list(e)[:2]
            return ("operand", f"(({self.node(a)[1]})**(1/({self.node(n)[1]})))")
        if tag == "mover":
            base, acc = list(e)[:2]
            a = _text(acc)
            if a in ("→", "⇀", "^", "˙", "·", "¨", "̂"):
                raise Skip("vector, unit vector or time derivative")
            b = self.node(base)
            if a in ("–", "¯", "-", "_", "‾"):
                return ("operand", b[1] + "_avg") if re.fullmatch(r"\w+", b[1]) else b
            raise Skip(f"accent {a!r}")
        if tag in ("munder", "munderover", "mtable", "mmultiscripts", "menclose", "mfenced"):
            raise Skip(tag)
        raise Skip(f"tag {tag}")

    def row(self, children):
        toks = [self.node(c) for c in children]
        toks = [t for t in toks if t[0] != "none"]
        out, i = [], 0
        while i < len(toks):
            k, v = toks[i]
            if k == "delta":
                if i + 1 < len(toks) and toks[i + 1][0] == "operand" and re.fullmatch(r"[A-Za-z]\w*", toks[i + 1][1]):
                    n = "Delta_" + toks[i + 1][1]
                    self.symbols.discard(toks[i + 1][1])
                    self.symbols.add(n)
                    out.append(("operand", n))
                    i += 2
                    continue
                raise Skip("Δ of an expression")
            if k == "prime":
                if out and out[-1][0] == "operand" and re.fullmatch(r"[A-Za-z]\w*", out[-1][1]):
                    self.symbols.discard(out[-1][1])
                    out[-1] = ("operand", out[-1][1] + "_prime")
                    self.symbols.add(out[-1][1])
                i += 1
                continue
            if k == "operand" and v.startswith("_") and out and out[-1][0] == "operand":
                out[-1] = ("operand", out[-1][1] + v)
                i += 1
                continue
            out.append((k, v))
            i += 1
        s = ""
        prev = None
        in_arg = False                                    # inside "sin 2θ": the argument is the run of operands
        for j, (k, v) in enumerate(out):
            if in_arg and k != "operand":
                s += ")"
                in_arg = False
                prev = "close"
            if k == "func":
                if prev in ("operand", "close"):
                    s += "*"
                nxt = out[j + 1] if j + 1 < len(out) else None
                if nxt and nxt[0] == "operand":           # sin θ → sin(theta), sin 2θ → sin(2*theta)
                    s += f"{v}("
                    in_arg = True
                    prev = "open"
                else:
                    s += v
                    prev = "func"
                continue
            if k in ("operand", "open") and prev in ("operand", "close"):
                s += "*"
            s += v
            prev = "operand" if k == "operand" else k
        if in_arg:
            s += ")"
        return ("operand", s)


def parse_math(m):
    m = re.sub(r"<annotation-xml.*?</annotation-xml>", "", m, flags=re.S)
    m = re.sub(r"<annotation.*?</annotation>", "", m, flags=re.S)
    m = re.sub(r"&(nbsp|thinsp|ThinSpace|InvisibleTimes|ApplyFunction);", " ", m)
    m = html.unescape(m.replace("&lt;", "‹").replace("&gt;", "›").replace("&amp;", "＆"))
    m = re.sub(r'\sxmlns(:\w+)?="[^"]*"', "", m)
    if any(ch in m for ch in "∑∫∮∂∇±∓‹›≤≥⊥⋯…|{}"):
        raise Skip("sum, integral, inequality or set")
    root = ET.fromstring(m)
    c = Conv()
    k, s = c.node(root)
    return s, c.symbols


# ── what each symbol means ────────────────────────────────────────────────
from backend.mathengine.symbols import CONV, HINTS, hints_for, ROLES_SUB, options, QROLES, dims, read  # noqa: E402,F401

# My review of every imported formula (2026-10-22). Units can't tell apart quantities with the same units (moles vs
# refractive index, period vs temperature in a ratio), so each reading was checked by eye.
# eq text → None (drop) or {symbol: corrected quantity}.
OVERRIDES = {
    "Delta_U = Q-W": {"Delta_U": "internal energy"},
    "((D*y)/(L)) = lam": {"y": "fringe spacing", "L": "screen distance"},
    "theta = 1.22*((lam)/(D))": {"D": "diameter"},
    "F = ((k*q_1*q_2)/((r)**(2)))": {"r": "distance"},
    "eps = -N*((Delta_Phi)/(Delta_t))": {"N": "turns"},
    "tau = r*F*sin(theta)": {"theta": "angle"},
    "(T)**(2) = ((4*(pi)**(2))/(G*M))*(a)**(3)": {"a": "radius"},
    "eps = N*B*A*omega*sin(omega*t)": {"N": "turns"},
    "U = ((1)/(2))*L*(I)**(2)": {"U": "energy"},
    "lam = ((V)/(4*sqrt(2)*pi*(r)**(2)*N))": {"lam": "distance"},
    "C = ((2*pi*eps_0*l)/(log(R_2/R_1)))": {"R_1": "radius", "R_2": "radius"},
    "kappa = ((E_0)/(E))": {"E_0": "electric field strength", "E": "electric field strength"},
    "rho = rho_0*(1+alpha*(T-T_0))": {"alpha": "temperature coefficient"},
    "R = R_0*(1+alpha*Delta_T)": {"alpha": "temperature coefficient", "R": "resistance:2", "R_0": "resistance:1"},
    "T_avg = ((1)/(lam))": {"T_avg": "time"},
    "h*f = ((h*c)/(lam))": {"h": "@h"},
    "V_H = u*B*w": {"u": "speed"},
    "R = sqrt((R_x)**(2)+(R_y)**(2))": None, "m*a = m*g": None, "f = w": None, "x_max = A": None, "T = w": None,
    "c = ((1)/(sqrt(eps_0*mu_0)))": None, "r = r_0*(A)**(1/3)": None, "Delta_t = ((h)/(E))": None,
    "y = y_prime": None, "y_prime = y": None, "E_1 = -E_0": None,
}
OVERRIDE_NAMES = [(r"^the lens maker", {"n_1": "refractive index:1", "n_2": "refractive index:2"}),
                  (r"^mean free time", {"tau": "time"})]
DROP_NAMES = re.compile(r"conservation of momentum along|rocket|poiseuille|lorentz|space-time|wien|planck.s constant|"
                        r"nth orbit|ground state|ionization|ionic|rotational energy of|energy in a metal|fermi|compton|"
                        r"nuclear radius|exchange of|^\s*$", re.I)


def main():
    import sympy
    from sympy.parsing.sympy_parser import parse_expr
    kept, skipped, seen = [], collections.Counter(), set()
    examples = collections.defaultdict(list)
    files = sorted(glob.glob(os.path.join(RAW, "*.html")))
    for path in files:
        book, chap = os.path.basename(path)[:-5].split("--")
        page = open(path, encoding="utf-8").read()
        for table in re.findall(r"<table.*?</table>", page, re.S):
            for row in re.findall(r"<tr.*?</tr>", table, re.S):
                cells = re.findall(r"<td.*?>(.*?)</td>", row, re.S)
                if len(cells) < 2 or "<math" not in cells[-1]:
                    continue
                name = html.unescape(re.sub(r"<.*?>", "", cells[0])).strip()
                math = re.search(r"<math.*?</math>", cells[-1], re.S)
                try:
                    s, symbols = parse_math(math.group(0))
                    if "d__" in s:
                        raise Skip("derivative")
                    parts = [p for p in s.split("=")]
                    if len(parts) < 2:
                        raise Skip("not an equation")
                    for i in range(len(parts) - 1):
                        a, b = parts[i].strip(), parts[i + 1].strip()
                        if not a or not b:
                            raise Skip("empty side")
                        names = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", a + " " + b)) - {"sqrt", "sin", "cos", "tan", "log", "exp", "pi"}
                        local = {n: sympy.Symbol(n, positive=True) for n in names}
                        local.update({"pi": sympy.pi})
                        lhs, rhs = parse_expr(a, local_dict=local), parse_expr(b, local_dict=local)
                        if lhs.is_Symbol and rhs.could_extract_minus_sign() and not rhs.is_Add:
                            rhs = -rhs                        # F = −kx: the sign gives a direction; the engine works in sizes
                            b = str(rhs)
                        used = {str(x) for x in (lhs.free_symbols | rhs.free_symbols)}
                        if not used or len(used) > 7:
                            raise Skip("too many symbols")
                        eq = f"{a} = {b}"
                        if DROP_NAMES.search(name) or (eq in OVERRIDES and OVERRIDES[eq] is None):
                            raise Skip("dropped in review")
                        reading = read((lhs, rhs), used, name)
                        fixes = dict(OVERRIDES.get(eq) or {})
                        for rx, fx in OVERRIDE_NAMES:
                            if re.search(rx, name, re.I):
                                fixes.update(fx)
                        for sym, q in fixes.items():
                            if sym in reading:
                                qq, _, rr = q.partition(":")
                                reading[sym] = (qq, rr)
                        if fixes:                                     # a corrected reading must still be consistent
                            vd = {s: dims(q) for s, (q, r) in reading.items()}
                            if tuple(round(float(x), 6) for x in dims_of(lhs, vd)) != \
                                    tuple(round(float(x), 6) for x in dims_of(rhs, vd)):
                                raise Skip("review fix is inconsistent")
                        key = (eq, tuple(sorted(reading.items())))
                        if key in seen:
                            continue
                        seen.add(key)
                        kept.append({"name": name[:1].upper() + name[1:], "topic": BOOKS.get(book, book), "eq": eq,
                                     "vars": {k: (q if q.startswith("@") else q + (":" + r if r else "")) for k, (q, r) in reading.items()},
                                     "needs": [], "nodims": False, "source": f"OpenStax {BOOKS.get(book, book)}, ch. {chap}"})
                except Skip as e:
                    why = str(e).split(" for ")[0] if str(e).startswith("no reading") else str(e)
                    skipped[why if not why.startswith("no reading") else "no reading for a symbol"] += 1
                    if len(examples[str(e)[:40]]) < 3:
                        examples[str(e)[:40]].append(name)
                except Exception as e:
                    skipped[f"parse error: {type(e).__name__}"] += 1
    with open(OUT, "w", encoding="utf-8") as f:
        f.write('"""Formulas imported from OpenStax textbooks\' Key Equations (CC BY 4.0): "Access for free at openstax.org".\n'
                'Generated by scripts/import_openstax.py — do not edit by hand; fix the importer or the conventions instead.\n'
                'The engine uses these only when the hand-checked library has no answer."""\n\nFORMULAS = [\n')
        for k in kept:
            f.write(f"    {k!r},\n")
        f.write("]\n")
    print(f"kept {len(kept)} formulas from {len(files)} pages → {OUT}")
    for why, n in skipped.most_common():
        print(f"  skipped {n:4d}: {why}")
    return kept


if __name__ == "__main__":
    main()
