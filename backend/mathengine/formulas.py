"""The library's formulas as sympy equations, with rearranging (making any variable the subject) and printing."""
import functools
import re

from . import library as L
from .units import parse_unit, NONE

# How a symbol is shown to students.
GREEK = {"lam": "λ", "lam_d": "λ", "theta": "θ", "theta_1": "θ₁", "theta_2": "θ₂", "omega": "ω", "rho": "ρ", "rho_c": "ρ",
         "mu": "μ", "mu_r": "μr", "mu0": "μ₀", "eps0": "ε₀", "eps_r": "εr", "eps": "ε", "eta": "η", "phi": "φ",
         "Phi": "Φ", "tau": "τ", "sigma": "σ", "sigma_s": "σ", "alpha": "α", "beta": "β", "psi": "ψ", "psi_s": "ψs",
         "psi_p": "ψp", "dT": "ΔT", "dL": "ΔL", "dm": "Δm", "dH": "ΔH", "dG": "ΔG", "dS": "ΔS", "dc": "Δc",
         "N_A": "Nₐ", "k_B": "k", "F_c": "F", "k_e": "k", "b_w": "b", "K_w": "K_w", "m_e": "mₑ", "m_p": "mₚ",
         "E_k": "Eₖ", "E_p": "Eₚ", "F_m": "F", "S_r": "S", "k_r": "dS/dx", "F_f": "F", "Q_f": "Q", "Q_r": "Q",
         "R_p": "R", "C_e": "Cost", "p_u": "price", "G_c": "G", "C_h": "C", "k_t": "k", "g_f": "g", "a_c": "a",
         "F_c_": "F", "I_m": "I", "L_a": "L", "A_p": "A", "T_h": "T½", "g_n": "n", "t_g": "g", "W_p": "width",
         "H_p": "height", "N_c": "colours", "f_s": "f", "ch": "channels", "pc": "percentage", "Pr": "profit",
         "SP": "SP", "CP": "CP", "S_a": "S", "x_1": "x₁", "x_2": "x₂"}
_SUB = str.maketrans("0123456789", "₀₁₂₃₄₅₆₇₈₉")
_SUP = str.maketrans("0123456789-", "⁰¹²³⁴⁵⁶⁷⁸⁹⁻")


def show_symbol(name: str) -> str:
    if name in GREEK:
        return GREEK[name]
    if "_" in name:
        head, tail = name.split("_", 1)
        head = GREEK.get(head, head)
        return head + (tail.translate(_SUB) if tail.isdigit() else tail)
    return name


class Formula:
    def __init__(self, spec: dict, index: int, source: str = "library"):
        import sympy
        self.spec, self.index, self.source = spec, index, source
        self.name, self.topic, self.needs = spec["name"], spec.get("topic", ""), spec.get("needs", [])
        self.vars = {}                                    # symbol → (quantity, role) or ("@", const)
        for sym, q in spec["vars"].items():
            if q.startswith("@"):
                self.vars[sym] = ("@", q[1:])
            else:
                quantity, _, role = q.partition(":")
                self.vars[sym] = (quantity, role)
        self.syms = {}
        for sym, (q, _) in self.vars.items():
            signed = q != "@" and L.QUANTITIES.get(q, {}).get("signed")
            self.syms[sym] = sympy.Symbol(sym, real=True) if signed or q == "@" else sympy.Symbol(sym, positive=True)
        local = dict(self.syms)
        local.update({"pi": sympy.pi, "sqrt": sympy.sqrt, "sin": sympy.sin, "cos": sympy.cos, "tan": sympy.tan,
                      "log": sympy.log, "exp": sympy.exp, "asin": sympy.asin})
        lhs, rhs = spec["eq"].split("=")
        self.raw_lhs, self.raw_rhs = lhs.strip(), rhs.strip()
        self.lhs = sympy.sympify(self.raw_lhs, locals=local)
        self.rhs = sympy.sympify(self.raw_rhs, locals=local)
        self.eq = sympy.Eq(self.lhs, self.rhs)
        # shown as written in the library ("2*pi*sqrt(L/g)"), not as sympy rearranges it
        self.text = f"{pretty(self.raw_lhs)} = {pretty(self.raw_rhs)}"

    def quantity(self, sym):
        return self.vars[sym]

    @functools.lru_cache(maxsize=None)
    def solve_for(self, sym: str) -> tuple:
        """Every expression for `sym` (the formula rearranged), simplest first."""
        import sympy
        target = self.syms[sym]
        if self.lhs == target and target not in self.rhs.free_symbols:
            return (self.rhs,)
        try:
            sols = sympy.solve(self.eq, target, rational=False)
        except Exception:
            return ()
        sols = [s for s in sols if target not in s.free_symbols]
        return tuple(sorted(sols, key=lambda e: len(str(e))))


def pretty(expr, names=None) -> str:
    """'2*pi*r' → '2 × π × r', 'sqrt(L/g)' → '√(L / g)'."""
    s = str(expr)
    s = re.sub(r"\*\*", "^", s)
    s = re.sub(r"(?<=\w|\))\*(?=\w|\()", " × ", s)
    s = s.replace("*", " × ").replace("/", " / ")
    s = re.sub(r"\bsqrt\(", "√(", s)
    s = re.sub(r"\bpi\b", "π", s)
    s = re.sub(r"\blog\(([^(),]+), 10\)", r"log₁₀(\1)", s)
    s = re.sub(r"\blog\(", "ln(", s)

    def sym(m):
        name = m.group(0)
        if names and name in names:
            return names[name]
        return show_symbol(name)
    s = re.sub(r"\b[A-Za-z][A-Za-z0-9_]*\b(?!\()", sym, s)
    return sup(re.sub(r"\s+", " ", s).strip())


def sup(s: str) -> str:
    """Whole-number powers as superscripts — last, after symbols are named: 'v^2' → 'v²', 'x^(-1)' → 'x⁻¹'."""
    return re.sub(r"\^(?:\((-?\d+)\)|(-?\d+))(?![\d.])", lambda m: (m.group(1) or m.group(2)).translate(_SUP), s)


def pretty_eq(lhs, rhs) -> str:
    return f"{pretty(lhs)} = {pretty(rhs)}"


@functools.lru_cache(maxsize=1)
def library() -> tuple:
    out = []
    for i, spec in enumerate(L.FORMULAS):
        try:
            out.append(Formula(spec, i))
        except Exception as e:                            # a broken formula must never break the app
            print(f"[mathengine] skipped formula {spec.get('name')}: {e}")
    return tuple(out)


@functools.lru_cache(maxsize=1)
def books() -> tuple:
    """Formulas imported from OpenStax Key Equations (library_books.py): the engine's second tier."""
    try:
        from .library_books import FORMULAS as B
    except Exception:
        return ()
    out = []
    for i, spec in enumerate(B):
        try:
            out.append(Formula(spec, 10000 + i, source="book"))
        except Exception as e:
            print(f"[mathengine] skipped book formula {spec.get('name')}: {e}")
    return tuple(out)


# ── dimensional analysis (selftest) ───────────────────────────────────────
def dims_of(expr, var_dims: dict):
    """Dimensions of a sympy expression, or raise ValueError if it adds unlike things."""
    import sympy
    zero = NONE
    if expr.is_Number or expr in (sympy.pi, sympy.E):
        return zero
    if expr.is_Symbol:
        return var_dims[str(expr)]
    if expr.is_Mul:
        total = zero
        for a in expr.args:
            total = tuple(x + y for x, y in zip(total, dims_of(a, var_dims)))
        return total
    if expr.is_Pow:
        base, ex = expr.args
        if dims_of(ex, var_dims) != zero:
            raise ValueError(f"dimensioned exponent in {expr}")
        bd = dims_of(base, var_dims)
        if bd == zero:
            return zero
        if not ex.is_Number:
            raise ValueError(f"symbolic power of a dimensioned base in {expr}")
        return tuple(float(x) * float(ex) for x in bd)
    if expr.is_Add:
        ds = {dims_of(a, var_dims) for a in expr.args}
        if len(ds) > 1:
            raise ValueError(f"adds unlike quantities in {expr}")
        return ds.pop()
    if isinstance(expr, (sympy.sin, sympy.cos, sympy.tan, sympy.asin, sympy.exp, sympy.log)):
        for a in expr.args:
            if dims_of(a, var_dims) != zero:
                raise ValueError(f"dimensioned argument in {expr}")
        return zero
    raise ValueError(f"can't check {expr!r}")


def check(f: Formula) -> str:
    """'' when the formula is dimensionally consistent, else what's wrong."""
    var_dims = {}
    for sym, (q, role) in f.vars.items():
        if q == "@":
            c = L.CONSTANTS[role]
            u = parse_unit(c[1]) if c[1] != "1" else None
            var_dims[sym] = u.dims if u else NONE
        else:
            if q not in L.QUANTITIES:
                return f"unknown quantity '{q}'"
            var_dims[sym] = tuple(float(x) for x in L.QUANTITIES[q]["dims"])
    try:
        a, b = dims_of(f.lhs, var_dims), dims_of(f.rhs, var_dims)
    except (ValueError, KeyError) as e:
        return str(e)
    a, b = tuple(round(float(x), 6) for x in a), tuple(round(float(x), 6) for x in b)
    return "" if a == b else f"sides differ: {a} vs {b}"
