"""Reading a formula's symbols: which quantity is v, n, R? Textbook conventions, hints from the formula's name or
topic, and only dimensionally consistent readings. Used by the OpenStax importer (scripts/import_openstax.py) and
by the slide reader (slideforms.py)."""
import collections
import itertools
import re

from . import library as L
from .formulas import dims_of
from .units import parse_unit, NONE


class Skip(Exception):
    pass

CONV = {
    "a": ["acceleration", "centripetal acceleration", "side"], "A": ["area", "amplitude", "activity", "absorbance"],
    "B": ["flux density"], "C": ["capacitance", "heat capacity"],
    "c": ["@c", "specific heat capacity", "concentration", "wave speed"], "d": ["distance", "diameter", "slit separation"],
    "D": ["diameter", "screen distance"], "E": ["energy", "electric field strength", "emf", "photon energy", "cell potential"],
    "e": ["@e"], "F": ["force", "@F_c"], "f": ["frequency", "focal length"], "g": ["@g", "gravitational field strength"],
    "G": ["@G", "gibbs energy"], "h": ["height", "@h", "image size"], "H": ["magnetic field strength", "enthalpy change"],
    "I": ["current", "intensity", "moment of inertia"], "i": ["current", "angle:incidence"], "J": ["impulse"],
    "k": ["spring constant", "@k_B", "@k_e", "rate constant", "thermal conductivity"], "K": ["kinetic energy"],
    "KE": ["kinetic energy"], "PE": ["potential energy"], "L": ["length", "inductance", "angular momentum", "specific latent heat"],
    "l": ["length", "magnetic path length"], "m": ["mass", "magnification"], "M": ["mass", "molar mass", "magnification"],
    "n": ["amount", "refractive index", "order", "rotational speed"], "N": ["particles", "turns", "normal reaction"],
    "p": ["momentum", "pressure"], "P": ["power", "pressure"], "q": ["charge", "heat"], "Q": ["charge", "heat", "flow rate"],
    "r": ["radius", "distance", "internal resistance"], "R": ["resistance", "radius", "@R"], "s": ["distance"],
    "t": ["time"], "T": ["period", "temperature", "force", "half-life"], "U": ["potential energy", "energy"],
    "u": ["speed:initial", "object distance"], "v": ["speed", "image distance", "wave speed"],
    "V": ["voltage", "volume", "electric potential"], "W": ["work", "weight"], "w": ["weight", "width"],
    "x": ["distance", "extension"], "y": ["height", "distance"], "Z": ["impedance"], "X": ["reactance"],
    "lam": ["wavelength", "decay constant"], "theta": ["angle"], "omega": ["angular velocity"],
    "rho": ["density", "resistivity"], "mu": ["friction coefficient", "permeability"], "mu_0": ["@mu0"],
    "eps": ["emf", "strain"], "eps_0": ["@eps0"], "eta": ["efficiency"], "tau": ["moment", "time constant"],
    "sigma": ["@sigma", "stress"], "phi": ["phase angle", "work function", "angle"], "Phi": ["magnetic flux", "work function"],
    "alpha": ["expansivity", "temperature coefficient"], "nu": ["frequency"], "Delta_t": ["time"], "Delta_x": ["distance", "extension"],
    "Delta_T": ["temperature change"], "Delta_V": ["voltage", "volume"], "Delta_U": ["energy", "potential energy"],
    "Delta_E": ["energy"], "Delta_H": ["enthalpy change"], "Delta_G": ["gibbs energy"], "Delta_S": ["entropy change"],
    "Delta_L": ["extension"], "Delta_p": ["momentum"], "Delta_v": ["speed"], "Delta_Phi": ["magnetic flux"],
    "N_A": ["@N_A"], "k_B": ["@k_B"], "m_e": ["@m_e"], "m_p": ["@m_p"], "K_w": ["@K_w"], "hbar": ["@hbar"],
    "Delta_theta": ["angular displacement", "angle"], "Delta_s": ["distance"], "Delta_omega": ["angular velocity"],
    "Delta_m": ["mass defect", "mass"], "Delta_KE": ["kinetic energy"], "Delta_Q": ["heat"], "Delta_l": ["extension"],
    "Delta_y": ["distance", "height"], "Delta_z": ["distance"], "Delta_A": ["area"], "Delta_lam": ["wavelength"],
    "Delta_E_int": ["internal energy"], "Delta_U_E": ["potential energy"], "strain": ["strain"], "stress": ["stress"],
    "Y": ["young modulus"], "elasticmodulus": ["young modulus"], "kappa": ["relative permittivity"],
    "Averagespeed": ["speed"], "Totaldistance": ["distance"], "Elapsedtime": ["time"], "time": ["time"],
    "distance": ["distance"], "lengthofthestring": ["length"], "massofthestring": ["mass"], "S": ["entropy"],
}

# The equation's name says what its symbols mean ("Snell's law": n is a refractive index, not moles).
# None: a topic the engine can't use (vector components, relativity, quantum).
HINTS = [
    (r"component of|vector|ellipse|semi-major|eccentric|relativ|lorentz factor|time dilation|length contraction|"
     r"uncertainty|schr|wave ?function|probability|mach|shock|bohr|rydberg|quantum|dose|rbe|\brem\b|sievert|"
     r"intensity level|decibel|binding energy per|spin|orbital magnetic|tunnel", None),
    (r"refract|snell|brewster|critical angle|optical fib|index of refraction|apparent depth", {"n": "refractive index"}),
    (r"\bgas\b|gases|kinetic theory|root-mean-square|rms speed|molecul|mean free path|boltzmann|equipartition|"
     r"internal energy|ideal gas|van der waals|avogadro",
     {"R": "@R", "T": "temperature", "M": "molar mass", "k": "@k_B", "N": "particles", "n": "amount", "m": "mass",
      "p": "pressure", "P": "pressure", "V": "volume"}),
    (r"carnot|engine|efficiency|refrigerator|heat pump|performance",
     {"e": "efficiency", "T": "temperature", "Q": "heat", "W": "work", "eta": "efficiency"}),
    (r"interference|diffraction|slit|grating|fringe|resolution|thin film|rayleigh|bragg",
     {"m": "order", "d": "slit separation", "D": "slit separation", "a": "slit separation", "n": "order"}),
    (r"inductance|solenoid|toroid|coil|transformer|faraday|induced|induction|motional",
     {"N": "turns", "n": "turns", "L": "inductance", "eps": "emf", "l": "length"}),
    (r"photoelectric|photon|work function|cut-off|cutoff|threshold|compton",
     {"phi": "work function", "K": "kinetic energy", "E": "photon energy"}),
    (r"capacit|dielectric", {"C": "capacitance", "Q": "charge", "U": "energy", "kappa": "relative permittivity", "d": "distance"}),
    (r"lens|mirror|magnification|focal|image|object",
     {"m": "magnification", "M": "magnification", "f": "focal length", "d_o": "object distance", "d_i": "image distance",
      "h_i": "image size", "h_o": "object size"}),
    (r"time of flight|range|projectile|trajectory", {"T": "time", "R": "distance", "H": "height"}),
    (r"decay|half-life|half life|radioactiv|activity", {"N": "particles", "lam": "decay constant", "T": "half-life", "A": "activity"}),
    (r"heat|thermal|calorim|specific heat|latent|phase change|melting|vapori|conduction|expansion",
     {"Q": "heat", "c": "specific heat capacity", "T": "temperature", "L": "specific latent heat", "k": "thermal conductivity",
      "alpha": "expansivity"}),
    (r"pressure|fluid|pascal|buoyan|archimedes|bernoulli|hydrostat|continuity|flow",
     {"p": "pressure", "P": "pressure", "A": "area", "Q": "flow rate", "rho": "density"}),
    (r"electric field|coulomb|point charge|charge distribution|electric force|electric potential|potential energy of|electrostatic",
     {"E": "electric field strength", "k": "@k_e", "q": "charge", "Q": "charge", "V": "electric potential", "U": "potential energy"}),
    (r"resist|ohm|current|circuit|power dissipat|drift|joule heating|terminal voltage|emf|kirchhoff",
     {"R": "resistance", "V": "voltage", "I": "current", "P": "power", "r": "internal resistance", "eps": "emf",
      "rho": "resistivity", "L": "length", "A": "area"}),
    (r"spring|hooke|oscillat|harmonic|pendulum", {"k": "spring constant", "x": "extension", "L": "length", "T": "period",
                                                  "A": "amplitude", "m": "mass"}),
    (r"rotat|angular|torque|rolling|moment of inertia|rigid body|flywheel",
     {"I": "moment of inertia", "L": "angular momentum", "tau": "moment", "alpha": "angular acceleration",
      "theta": "angular displacement", "r": "radius", "R": "radius"}),
    (r"magnetic field|ampere|biot|wire|loop|hall|cyclotron|charged particle|magnetic force|lorentz force|magnetic dipole",
     {"B": "flux density", "I": "current", "q": "charge", "R": "radius", "r": "radius", "N": "turns", "n": "turns"}),
    (r"wave|string|sound|doppler|beat|resonan|standing", {"f": "frequency", "v": "wave speed", "lam": "wavelength",
                                                          "T": "period", "L": "length", "A": "amplitude"}),
    (r"gravit|orbit|satellite|escape|kepler|planet", {"M": "mass", "m": "mass", "r": "radius", "R": "radius", "T": "period",
                                                      "G": "@G", "g": "gravitational field strength"}),
    (r"momentum|impulse|collision", {"p": "momentum", "J": "impulse", "v": "speed", "m": "mass"}),
    (r"work|energy|power|kinetic|potential", {"W": "work", "K": "kinetic energy", "U": "potential energy", "P": "power"}),
]


def hints_for(name, topic=False):
    """Symbol meanings suggested by an equation's name. `topic`: a whole slide's text, not one equation's name —
    the "skip this topic" rules don't apply (a slide about machines isn't about Mach numbers)."""
    merged = {}
    for rx, mapping in HINTS:
        if re.search(rx, name, re.I):
            if mapping is None:
                if topic:
                    continue
                return None
            for k, v in mapping.items():
                merged.setdefault(k, v)
    return merged


ROLES_SUB = {"0": "initial", "i": "initial", "f": "final", "1": "1", "2": "2", "p": "primary", "s": "secondary",
             "in": "in", "out": "out", "o": "object"}


def options(sym, hinted=None):
    """Candidate (quantity, role) readings for a symbol."""
    if hinted:
        base = sym.split("_")[0] if not sym.startswith("Delta_") else sym
        key = sym if sym in hinted else (base if base in hinted else None)
        if key is not None:
            q = hinted[key]
            sub = sym[len(key) + 1:] if sym != key else ""
            if q.startswith("@"):
                return [(q, "")]
            role = ROLES_SUB.get(sub.split("_")[0], "")
            return [(q, role if role in QROLES.get(q, set()) else "")]
    if sym in CONV:
        base, sub = sym, ""
    else:
        base, _, sub = sym.partition("_")
        if sym.startswith("Delta_"):
            base, sub = sym, ""
    opts = CONV.get(sym) or CONV.get(base) or []
    if sym.endswith("_avg"):
        opts = CONV.get(sym[:-4], [])
    out = []
    for q in opts:
        if q.startswith("@"):
            out.append((q, ""))
            continue
        q, _, role = q.partition(":")
        role = role or ROLES_SUB.get(sub.split("_")[0], "")
        if role and role not in QROLES.get(q, set()):
            role = ""
        out.append((q, role))
    return out


QROLES = collections.defaultdict(set)
for _f in L.FORMULAS:
    for _q in _f["vars"].values():
        if ":" in _q and not _q.startswith("@"):
            a, _, b = _q.partition(":")
            QROLES[a].add(b)


def dims(q):
    if q.startswith("@"):
        c = L.CONSTANTS[q[1:]]
        u = parse_unit(c[1]) if c[1] != "1" else None
        return u.dims if u else NONE
    return tuple(float(x) for x in L.QUANTITIES[q]["dims"])


def read(eq, symbols, name, extra=None, topic=False):
    """The best dimensionally consistent reading of the symbols, or None. `extra`: {symbol: quantity} that must win
    (a slide's own "where V is the voltage")."""
    import sympy
    lhs, rhs = eq
    syms = sorted(symbols)
    hinted = hints_for(name, topic)
    if hinted is None:
        raise Skip("topic the engine can't use")
    if extra:
        hinted = {**hinted, **extra}
    opts = [options(s, hinted) for s in syms]
    if any(not o for o in opts):
        missing = [s for s, o in zip(syms, opts) if not o]
        raise Skip(f"no reading for {', '.join(missing)}")
    words = name.lower()
    best = []
    for combo in itertools.islice(itertools.product(*opts), 4000):
        consts = [q for q, _ in combo if q.startswith("@")]
        if len(consts) != len(set(consts)):
            continue
        var_dims = {s: dims(q) for s, (q, r) in zip(syms, combo)}
        try:
            a, b = dims_of(lhs, var_dims), dims_of(rhs, var_dims)
        except (ValueError, KeyError):
            continue
        if tuple(round(float(x), 6) for x in a) != tuple(round(float(x), 6) for x in b):
            continue
        score = 0.0
        for s, (q, r) in zip(syms, combo):
            if not q.startswith("@") and any(w in words for w in L.QUANTITIES[q]["words"][:4] + [q]):
                score += 2
            score -= 0.1 * opts[syms.index(s)].index((q, r))   # conventions are listed most likely first
        best.append((score, combo))
    if not best:
        raise Skip("no consistent reading")
    best.sort(key=lambda x: -x[0])
    if len(best) > 1 and best[1][0] == best[0][0] and best[1][1] != best[0][1]:
        raise Skip("ambiguous reading")
    return dict(zip(syms, best[0][1]))
