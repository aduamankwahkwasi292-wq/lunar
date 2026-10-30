"""The formula library: quantities, constants and formulas across physics, electrical engineering, chemistry,
biology, maths, finance and computing.

Formulas are data. Each names its variables' quantities ("speed", "speed:initial", "@g" for a constant); the
engine matches a question's numbers to those quantities by units and wording. Every formula is checked for
dimensional consistency by selftest.py — add one, run the test.

Quantity words are lower-case phrases matched on word boundaries. A role ("speed:initial") adds ROLE_WORDS.
"""
from .units import parse_unit, dim, NONE

# ── quantities ────────────────────────────────────────────────────────────
# name → dict(unit=SI unit text, words, show=display unit, signed=negative values allowed,
#             hints=unit labels that point here, accept={dims: multiplier} for non-SI internal values)
QUANTITIES = {}


def Q(name, unit, words, show=None, signed=False, hints=(), accept=None, internal=None):
    u = parse_unit(unit) if unit != "1" else None
    dims = internal if internal is not None else (u.dims if u else NONE)
    QUANTITIES[name] = {"name": name, "unit": unit, "dims": dims, "words": [w.strip() for w in words.split("|") if w.strip()],
                        "show": show, "signed": signed, "hints": tuple(hints), "accept": accept or {dims: 1.0}}


YEAR = 3.15576e7
# mechanics
Q("distance", "m", "distance|displacement|how far|travels|travelled|traveled|covers|covered|moves|moved|journey|"
  "distance travelled|distance covered|stopping distance")
Q("length", "m", "length|long|length of the wire|wire length|length of wire|pendulum length")
Q("height", "m", "height|high|tall|depth|deep|altitude|elevation|maximum height|vertical height|raised|lifted|"
  "falls through|dropped from|above the ground")
Q("radius", "m", "radius|radii|orbit radius|orbital radius")
Q("diameter", "m", "diameter")
Q("width", "m", "width|wide|breadth")
Q("side", "m", "side|edge|side length|sides of")
Q("base length", "m", "base")
Q("perimeter", "m", "perimeter")
Q("circumference", "m", "circumference")
Q("slant height", "m", "slant height|slant")
Q("arc length", "m", "arc length|arc")
Q("hypotenuse", "m", "hypotenuse")
Q("opposite side", "m", "opposite side|opposite")
Q("adjacent side", "m", "adjacent side|adjacent")
Q("parallel side", "m", "parallel side|parallel sides")
Q("diagonal", "m", "diagonal|diagonals")
Q("area", "m^2", "area|cross-sectional area|cross section|cross-section|surface area|plate area|area of cross-section")
Q("volume", "m^3", "volume|capacity|occupies|volume of")
Q("time", "s", "time|how long|duration|takes|taken|interval|for how long|time taken", hints=("s", "min", "h", "hr", "hrs", "hour", "hours", "minute", "minutes", "second", "seconds", "day", "days", "week", "weeks", "year", "years", "ms"))
Q("speed", "m/s", "speed|velocity|how fast|moving at|travelling at|traveling at|travels at|average speed")
Q("acceleration", "m/s^2", "acceleration|accelerates|accelerating|deceleration|decelerates|retardation", signed=True)
Q("mass", "kg", "mass|of mass|weighing|a mass|body of|object of|load")
Q("force", "N", "force|thrust|tension|pull|push|drag|applied force|resultant force|net force|exerts|exerted")
Q("weight", "N", "weight|weighs")
Q("friction", "N", "friction|frictional force|frictional|limiting friction")
Q("normal reaction", "N", "normal reaction|normal force|reaction force|reaction")
Q("momentum", "kg m/s", "momentum", signed=True)
Q("impulse", "N s", "impulse")
Q("energy", "J", "energy|energy transferred|energy used|energy consumed|electrical energy|energy converted|"
  "energy supplied|energy stored|energy released", hints=("J", "kJ", "MJ", "kWh", "Wh"))
Q("kinetic energy", "J", "kinetic energy|k.e.|ke|kinetic")
Q("potential energy", "J", "potential energy|gravitational potential energy|p.e.|pe|gpe|gravitational energy")
Q("work", "J", "work|work done")
Q("heat", "J", "heat|heat energy|thermal energy|heat supplied|heat required|heat needed|heat absorbed|"
  "heat released|heat lost|heat gained|quantity of heat|energy required|energy needed")
Q("power", "W", "power|rate of doing work|rating|rated|power output|power consumed|power dissipated|"
  "power delivered|power developed|loss|losses|copper loss", hints=("W", "kW", "MW", "mW", "hp"))
Q("efficiency", "1", "efficiency|efficient", show="%")
Q("pressure", "Pa", "pressure|pressure exerted")
Q("density", "kg/m^3", "density|dense")
Q("moment", "N m", "moment|torque|turning effect|couple|turning moment")
Q("spring constant", "N/m", "spring constant|stiffness|force constant|elastic constant")
Q("extension", "m", "extension|extends|stretched|stretch|compressed|compression|elongation")
Q("angle", "rad", "angle|inclined at|inclination|incline|angle of|at an angle", show="°", hints=("°", "degrees"))
Q("friction coefficient", "1", "coefficient of friction|coefficient|μ|mu")
Q("frequency", "Hz", "frequency|oscillations per second|cycles per second|vibrations per second",
  hints=("Hz", "kHz", "MHz", "GHz"))
Q("period", "s", "period|periodic time|time period|period of oscillation")
Q("angular velocity", "rad/s", "angular velocity|angular speed|angular frequency|ω", hints=("rad/s",))
Q("rotational speed", "rps", "speed of rotation|rotational speed|rpm|revolutions per minute|rev/min|"
  "synchronous speed|rotor speed|shaft speed|runs at|rotates at|revolutions per second", show="rpm",
  hints=("rpm", "rev/min", "rev/s", "rps", "revolutions per minute"))
Q("stress", "Pa", "stress|tensile stress")
Q("strain", "1", "strain|tensile strain")
Q("young modulus", "Pa", "young's modulus|young modulus|modulus of elasticity|elastic modulus")
Q("flow rate", "m^3/s", "flow rate|volume flow rate|rate of flow|discharge")
Q("upthrust", "N", "upthrust|buoyant force|buoyancy|upward thrust")
Q("mechanical advantage", "1", "mechanical advantage|m.a.|ma")
Q("velocity ratio", "1", "velocity ratio|v.r.|vr|distance ratio")
Q("load", "N", "load")
Q("effort", "N", "effort")
Q("gravitational field strength", "m/s^2", "acceleration due to gravity|gravitational field strength|g")
Q("moment of inertia", "kg m^2", "moment of inertia")
Q("angular momentum", "kg m^2/s", "angular momentum")
Q("centripetal force", "N", "centripetal force|centripetal")
Q("centripetal acceleration", "m/s^2", "centripetal acceleration")
Q("amplitude", "m", "amplitude")
Q("count", "1", "number of|count")
# waves and optics
Q("wavelength", "m", "wavelength|wave length|λ")
Q("wave speed", "m/s", "speed of the wave|wave speed|speed of light|speed of sound|velocity of the wave|"
  "speed of the waves|wave velocity|travels at|speed")
Q("refractive index", "1", "refractive index|index of refraction|refractive indices")
Q("focal length", "m", "focal length|focal")
Q("object distance", "m", "object distance|object is placed|object placed|object is|from the lens|"
  "in front of|from the mirror")
Q("image distance", "m", "image distance|image is formed|image formed|image is|image")
Q("magnification", "1", "magnification|magnifying power|magnified|times larger")
Q("image size", "m", "image size|image height|size of the image|height of the image|measured length|"
  "drawing|length in the image|image length")
Q("object size", "m", "object size|object height|size of the object|height of the object|actual size|"
  "actual length|real size|real length|actual diameter|actual width")
Q("lens power", "D", "power of the lens|lens power|power of a lens")
Q("slit separation", "m", "slit separation|separation of the slits|slits are|distance between the slits|"
  "slit spacing|grating spacing|line spacing")
Q("fringe spacing", "m", "fringe spacing|fringe separation|fringe width|distance between fringes|"
  "separation of the fringes|distance between adjacent fringes")
Q("screen distance", "m", "screen distance|distance to the screen|from the screen|screen is")
Q("order", "1", "order|order of the maximum|order of diffraction|nth order")
Q("lines per metre", "m^-1", "lines per metre|lines per meter|lines per mm|lines per millimetre|lines/mm|lines/m|"
  "lines per cm")
Q("intensity", "W/m^2", "intensity")
# electricity
Q("charge", "C", "charge|quantity of charge|charge flows|charge passed", signed=True)
Q("current", "A", "current|flows|flowing|draws|amperes|current drawn|current flowing", hints=("A", "mA", "µA"))
Q("voltage", "V", "voltage|potential difference|p.d.|pd|volts|across|potential|terminal voltage",
  hints=("V", "mV", "kV"))
Q("emf", "V", "emf|e.m.f.|e.m.f|electromotive force|battery|cell|supply|source|induced emf|generator|"
  "generated voltage|generated emf|induced voltage|back emf", hints=("V",))
Q("resistance", "Ω", "resistance|resistor|resistors|ohms|load resistance", hints=("Ω", "kΩ", "MΩ"))
Q("internal resistance", "Ω", "internal resistance")
Q("resistivity", "Ω m", "resistivity")
Q("conductance", "S", "conductance")
Q("capacitance", "F", "capacitance|capacitor", hints=("F", "µF", "nF", "pF"))
Q("inductance", "H", "inductance|inductor|coil", hints=("H", "mH"))
Q("reactance", "Ω", "reactance")
Q("inductive reactance", "Ω", "inductive reactance")
Q("capacitive reactance", "Ω", "capacitive reactance")
Q("impedance", "Ω", "impedance")
Q("apparent power", "VA", "apparent power|kva|va", hints=("VA", "kVA", "MVA"))
Q("reactive power", "var", "reactive power|kvar|var", hints=("var", "kvar", "VAR", "kVAR"))
Q("power factor", "1", "power factor|p.f.|pf|cos φ|cos phi")
Q("phase angle", "rad", "phase angle|phase difference|lags|leads|lagging|leading", show="°")
Q("time constant", "s", "time constant|τ")
Q("electric field strength", "V/m", "electric field strength|electric field|field strength|E-field")
Q("electric potential", "V", "electric potential|potential at")
Q("cost", "GH₵", "cost|costs|price|bill|amount to pay|charge for", hints=("GH₵", "GHS", "cedis", "$"))
Q("unit price", "GH₵/J", "per kwh|per unit|unit price|cost per|price per|tariff", hints=("GH₵/kWh",))
Q("gain", "1", "voltage gain|gain of the amplifier|amplifier gain|amplification")
Q("current gain", "1", "current gain|β|beta|hfe")
Q("temperature coefficient", "K^-1", "temperature coefficient|temperature coefficient of resistance|α")
# magnetism and machines
Q("magnetic flux", "Wb", "flux|magnetic flux|flux per pole|Φ", hints=("Wb", "mWb", "µWb"))
Q("flux density", "T", "flux density|magnetic flux density|magnetic field|field of|b-field", hints=("T", "mT", "Wb/m^2"))
Q("magnetic field strength", "A/m", "magnetic field strength|magnetising force|magnetizing force|field intensity|"
  "magnetic field intensity|magnetising field|magnetizing field|h-field", hints=("A/m", "At/m"))
Q("mmf", "A", "mmf|m.m.f.|m.m.f|magnetomotive force|ampere-turns|ampere turns", hints=("At",))
Q("reluctance", "A/Wb", "reluctance")
Q("reluctance gradient", "A/(Wb m)", "rate of change of reluctance|reluctance changes|change of reluctance|"
  "reluctance gradient|dr/dx")
Q("permeability", "H/m", "permeability|absolute permeability")
Q("relative permittivity", "1", "relative permittivity|dielectric constant|κ|kappa")
Q("angular acceleration", "rad/s^2", "angular acceleration")
Q("angular displacement", "rad", "angular displacement|turns through|rotates through")
Q("entropy", "J/K", "entropy|change in entropy|entropy change")
Q("internal energy", "J", "internal energy|change in internal energy")
Q("relative permeability", "1", "relative permeability|μr|mur|mu_r|μ_r")
Q("turns", "1", "turns|number of turns|turn|coil of|windings", hints=("turns",))
Q("magnetic path length", "m", "mean length|magnetic path|path length|length of the magnetic circuit|"
  "mean circumference|length of the core|core length|air gap")
Q("energy density", "J/m^3", "energy density|energy per unit volume")
Q("slip", "1", "slip", show="%")
Q("poles", "1", "poles|pole|pole motor|number of poles", hints=("poles", "pole"))
Q("conductors", "1", "conductors|armature conductors|total conductors")
Q("slots", "1", "slots|armature slots|slot")
Q("conductors per slot", "1", "conductors per slot|conductors in each slot|each slot containing|each containing|per slot")
Q("parallel paths", "1", "parallel paths")
Q("turns ratio", "1", "turns ratio|transformation ratio")
# heat
Q("temperature", "K", "temperature|at a temperature|heated to|cooled to|hot|boiling", show=None)
Q("temperature change", "K", "temperature change|change in temperature|temperature rise|rise in temperature|"
  "increase in temperature|raise its temperature|raise the temperature|heated through|cooled through|by", show=None)
Q("specific heat capacity", "J/(kg K)", "specific heat capacity|specific heat|s.h.c.|shc")
Q("heat capacity", "J/K", "heat capacity|thermal capacity")
Q("specific latent heat", "J/kg", "specific latent heat|latent heat|latent heat of fusion|latent heat of vaporisation|"
  "latent heat of vaporization")
Q("thermal conductivity", "W/(m K)", "thermal conductivity")
Q("expansivity", "K^-1", "linear expansivity|coefficient of linear expansion|expansivity|cubic expansivity")
Q("emissivity", "1", "emissivity")
# matter, chemistry
Q("amount", "mol", "moles|number of moles|amount of substance|mol of|amount in moles", hints=("mol", "mmol"))
Q("molar mass", "kg/mol", "molar mass|relative molecular mass|relative formula mass|formula mass|mr|rmm|"
  "molecular mass|m_r|relative atomic mass|ar", show="g/mol", hints=("g/mol", "g mol^-1"))
Q("concentration", "mol/m^3", "concentration|molarity|molar concentration|molar|mol/dm3", show="mol/dm^3",
  hints=("mol/dm^3", "mol/L", "M", "mol dm^-3"))
Q("mass concentration", "kg/m^3", "mass concentration|g/dm3|grams per", show="g/dm^3", hints=("g/dm^3", "g/L"))
Q("particles", "1", "number of particles|molecules|atoms|ions|particles|electrons|entities|photons|nuclei|"
  "number of atoms|number of molecules|number of electrons")
Q("molar volume", "m^3/mol", "molar volume", show="dm^3/mol")
Q("pH", "1", "ph")
Q("pOH", "1", "poh")
Q("hydrogen ion concentration", "1", "hydrogen ion concentration|[h+]|h+ concentration|concentration of hydrogen ions|"
  "hydronium", accept={dim(mol=1, m=-3): 1e-3, NONE: 1.0}, show="mol/dm^3")
Q("hydroxide ion concentration", "1", "hydroxide ion concentration|[oh-]|oh- concentration|concentration of hydroxide",
  accept={dim(mol=1, m=-3): 1e-3, NONE: 1.0}, show="mol/dm^3")
Q("acid dissociation constant", "1", "ka|acid dissociation constant|dissociation constant")
Q("pKa", "1", "pka")
Q("salt concentration", "1", "salt|conjugate base|[a-]|base concentration", accept={dim(mol=1, m=-3): 1e-3, NONE: 1.0})
Q("acid concentration", "1", "acid|[ha]|acid concentration", accept={dim(mol=1, m=-3): 1e-3, NONE: 1.0})
Q("percentage yield", "1", "percentage yield|percent yield|% yield|yield", show="%")
Q("actual yield", "kg", "actual yield|obtained|actual mass|mass obtained", show="g")
Q("theoretical yield", "kg", "theoretical yield|expected|theoretical mass|expected mass", show="g")
Q("enthalpy change", "J/mol", "enthalpy change|enthalpy|δh|heat of reaction|enthalpy of combustion|"
  "enthalpy of neutralisation|enthalpy of neutralization|molar enthalpy", show="kJ/mol", signed=True)
Q("entropy change", "J/(mol K)", "entropy change|entropy|δs", signed=True)
Q("gibbs energy", "J/mol", "gibbs|free energy|δg|gibbs free energy", show="kJ/mol", signed=True)
Q("cell potential", "V", "cell potential|e.m.f. of the cell|emf of the cell|standard electrode potential|"
  "cell emf|e°cell", signed=True)
Q("electrode potential", "V", "electrode potential|reduction potential|e°", signed=True)
Q("electrons transferred", "1", "electrons transferred|number of electrons|charge on the ion|valency|z")
Q("rate constant", "s^-1", "rate constant")
Q("activation energy", "J/mol", "activation energy|ea", show="kJ/mol")
Q("pre-exponential factor", "s^-1", "pre-exponential factor|arrhenius constant|frequency factor")
Q("rate", "mol/(m^3 s)", "rate of reaction|reaction rate|average rate", show="mol/(dm^3 s)")
Q("absorbance", "1", "absorbance")
Q("molar absorptivity", "m^2/mol", "molar absorptivity|molar absorption coefficient|extinction coefficient",
  show="dm^3/(mol cm)")
Q("path length", "m", "path length|cuvette|cell length", show="cm")
Q("half-life", "s", "half-life|half life|half-lives|half lives")
Q("decay constant", "s^-1", "decay constant|λ")
Q("activity", "Bq", "activity|count rate|counts per", hints=("Bq",))
Q("percentage by mass", "1", "percentage by mass|percentage composition|% by mass|mass percent", show="%")
Q("molality", "mol/kg", "molality")
# modern physics
Q("photon energy", "J", "energy of the photon|photon energy|energy of a photon|energy of each photon|quantum",
  hints=("eV", "J"))
Q("work function", "J", "work function", hints=("eV",))
Q("threshold frequency", "Hz", "threshold frequency")
Q("stopping potential", "V", "stopping potential|stopping voltage")
Q("mass defect", "kg", "mass defect|loss of mass|mass lost|mass converted")
Q("binding energy", "J", "binding energy", hints=("MeV",))
# biology
Q("bmi", "kg/m^2", "bmi|body mass index")
Q("allele frequency", "1", "allele frequency|frequency of the allele|frequency of allele|dominant allele|"
  "recessive allele|p|q")
Q("genotype frequency", "1", "genotype frequency|frequency of homozygous|frequency of heterozygous|homozygous|"
  "heterozygous|carriers|frequency of the genotype|recessive phenotype|affected|show the recessive")
Q("population", "1", "population|population size|estimated population|number of organisms|total population|"
  "individuals")
Q("first capture", "1", "first capture|first sample|captured and marked|marked and released|caught and marked|marked")
Q("second capture", "1", "second capture|second sample|caught in the second|recaptured sample|second time")
Q("marked recaptured", "1", "recaptured|marked in the second|were marked|already marked|marked ones")
Q("population density", "m^-2", "population density|density of the population|per square metre|per m2")
Q("heart rate", "s^-1", "heart rate|pulse|beats per minute|beats/min|bpm", show="beats/min")
Q("stroke volume", "m^3", "stroke volume", show="mL")
Q("cardiac output", "m^3/s", "cardiac output", show="L/min")
Q("q10", "1", "q10|temperature coefficient q10")
Q("reaction rate", "s^-1", "rate|rate of|per second|per minute")
Q("respiratory quotient", "1", "respiratory quotient|rq")
Q("carbon dioxide", "m^3", "carbon dioxide produced|co2 produced|volume of carbon dioxide|carbon dioxide")
Q("oxygen", "m^3", "oxygen consumed|o2 consumed|volume of oxygen|oxygen used|oxygen")
Q("water potential", "Pa", "water potential|ψ", signed=True, show="kPa")
Q("solute potential", "Pa", "solute potential|osmotic potential|ψs", signed=True, show="kPa")
Q("pressure potential", "Pa", "pressure potential|turgor pressure|ψp", signed=True, show="kPa")
Q("mitotic index", "1", "mitotic index", show="%")
Q("cells in mitosis", "1", "in mitosis|dividing|undergoing mitosis|cells in mitosis")
Q("total cells", "1", "total cells|total number of cells|cells in total|cells counted|in total")
Q("generations", "1", "generations|divisions|number of generations")
Q("generation time", "s", "generation time|doubling time|divides every|divide every|doubles every")
Q("tidal volume", "m^3", "tidal volume", show="mL")
Q("breathing rate", "s^-1", "breathing rate|breaths per minute|breaths/min|ventilation rate", show="breaths/min")
Q("ventilation", "m^3/s", "pulmonary ventilation|minute volume|ventilation", show="L/min")
Q("sa:v ratio", "m^-1", "surface area to volume ratio|surface area : volume|sa:v|sa/v")
# maths / finance / statistics
Q("first term", "1", "first term|a1|first number")
Q("common difference", "1", "common difference|difference")
Q("common ratio", "1", "common ratio|ratio")
Q("number of terms", "1", "number of terms|terms|n terms|first n|how many terms")
Q("nth term", "1", "nth term|term|last term|th term")
Q("sum of terms", "1", "sum|sum of the first|total of")
Q("sum to infinity", "1", "sum to infinity|infinite sum")
Q("sides", "1", "sides|sided|-gon|polygon with")
Q("angle sum", "rad", "sum of interior angles|sum of the interior angles|angle sum", show="°")
Q("interior angle", "rad", "interior angle|each interior angle", show="°")
Q("exterior angle", "rad", "exterior angle|each exterior angle", show="°")
Q("principal", "GH₵", "principal|invested|deposit|deposited|borrowed|loan|saves|sum of|amount invested")
Q("interest", "GH₵", "interest|simple interest|compound interest|interest earned")
Q("final amount", "GH₵", "amount|total amount|final amount|accumulated|worth|will have|balance")
Q("interest rate", "1", "interest rate|rate|per annum|p.a.|annual rate|rate of interest", show="%",
  accept={NONE: 1.0, dim(s=-1): YEAR})
Q("years", "1", "years|year|annum|period", accept={dim(s=1): 1 / YEAR, NONE: 1.0})
Q("compounding periods", "1", "compounded|times a year|times per year|quarterly|monthly")
Q("cost price", "GH₵", "cost price|bought|buys|purchased|cost")
Q("selling price", "GH₵", "selling price|sold|sells|sale price")
Q("profit", "GH₵", "profit|profit made", signed=True)
Q("percentage", "1", "percentage|percent|per cent|%", show="%")
Q("original value", "1", "original value|original price|initial value|old value|old price|from")
Q("new value", "1", "new value|new price|final value|increased to|decreased to|rose to|fell to")
Q("data size", "bit", "file size|size of the file|data|file|size|storage|capacity|memory", show="MB",
  hints=("B", "KB", "MB", "GB", "TB", "bit", "kB", "Mb"))
Q("data rate", "bit/s", "transfer rate|download speed|upload speed|bandwidth|bit rate|data rate|connection speed|"
  "speed", show="Mbps", hints=("bps", "kbps", "Mbps", "Gbps", "MB/s", "KB/s"))
Q("pixels", "1", "pixels|resolution|by|x")
Q("colour depth", "bit", "colour depth|color depth|bit depth|bits per pixel|bits for each pixel|bpp", show="bit")
Q("colours", "1", "colours|colors|number of colours|number of colors|different colours")
Q("sample rate", "Hz", "sample rate|sampling rate|samples per second|sampling frequency")
Q("sample resolution", "bit", "sample resolution|bit depth|bits per sample|sample size", show="bit")
Q("channels", "1", "channels|stereo|mono")

# Roles: words that tell two quantities of the same kind apart ("initial speed" vs "final speed").
ROLE_WORDS = {
    "initial": "initial|initially|starts|starting|start|launched|thrown|projected|fired|kicked|original|"
               "originally|before|at first|from",
    "final": "final|finally|reaches|reached|after|end|ends|becomes|hits|strikes|lands|to",
    "1": "first|initial|initially|original|originally|before|from|at first",
    "2": "second|final|finally|new|after|to|becomes|changed|now",
    "primary": "primary|input side|primary coil|primary winding|input voltage|input current",
    "secondary": "secondary|output side|secondary coil|secondary winding|output voltage|output current",
    "in": "input|supplied|supply|consumed|takes in|input power|input energy|electrical input|total",
    "out": "output|useful|delivers|delivered|output power|useful output|useful energy",
    "incidence": "incidence|incident|in air|air",
    "refraction": "refraction|refracted|in glass|in water|glass|water|medium",
    "critical": "critical",
    "hot": "hot|source|hot reservoir|higher",
    "cold": "cold|sink|cold reservoir|surroundings|lower",
    "sync": "synchronous|sync|field|stator field|synchronous speed",
    "rotor": "rotor|shaft|runs at|actual|full load|full-load|rotates at|running at|motor speed",
    "eyepiece": "eyepiece|ocular",
    "objective": "objective",
    "peak": "peak|maximum|amplitude|max",
    "rms": "rms|r.m.s.|r.m.s|root mean square|effective|mains",
    "line": "line|line current|supply current|input current|takes a current|draws",
    "phase": "phase",
    "a": "first parallel side",
    "b": "second parallel side",
    "load": "load|load current|to a load|to the load|to a resistance load|delivers a current",
    "effort": "effort",
    "air gap": "air gap|air-gap",
    "rotor cu": "rotor copper loss|rotor cu loss|rotor copper|copper loss|rotor loss|rotor losses|rotor i2r",
    "stator loss": "stator loss|stator losses|stator copper|stator cu",
    "friction": "friction and windage|windage|friction loss|mechanical loss|rotational loss",
    "mech": "mechanical power|mechanical|gross mechanical|developed",
    "cathode": "cathode|reduction|positive electrode",
    "anode": "anode|oxidation|negative electrode",
    "back": "back emf|back e.m.f.|counter emf|generated|induced",
    "armature": "armature|armature current|in the armature",
    "field": "field current|field resistance|field winding|shunt field|field circuit|field",
    "brush": "brush drop|brush contact drop|brush contact|brush voltage|brush",
    "conductor": "in the armature conductors|per conductor|each conductor|conductor current|in each conductor",
    "collector": "collector|i_c|ic",
    "base": "base current|base|i_b|ib",
    "feedback": "feedback|rf|r_f",
    "input": "input resistor|input resistance|rin|r_in",
}

# ── constants ─────────────────────────────────────────────────────────────
# symbol → (value in SI, unit text, display, words that mean "this constant")
CONSTANTS = {
    "g": (9.81, "m/s^2", "g", "acceleration due to gravity|gravitational field strength|take g|g ="),
    "c": (2.998e8, "m/s", "c", "speed of light"),
    "h": (6.626e-34, "J s", "h", "planck"),
    "e": (1.602e-19, "C", "e", "electronic charge|charge on an electron|elementary charge"),
    "m_e": (9.109e-31, "kg", "mₑ", "mass of an electron|electron mass"),
    "m_p": (1.673e-27, "kg", "mₚ", "mass of a proton|proton mass"),
    "N_A": (6.022e23, "mol^-1", "Nₐ", "avogadro"),
    "R": (8.314, "J/(mol K)", "R", "gas constant|molar gas constant"),
    "k_B": (1.381e-23, "J/K", "k", "boltzmann"),
    "G": (6.674e-11, "N m^2/kg^2", "G", "gravitational constant|universal gravitational constant"),
    "eps0": (8.854e-12, "F/m", "ε₀", "permittivity of free space|permittivity"),
    "mu0": (1.2566370614e-6, "H/m", "μ₀", "permeability of free space"),
    "sigma": (5.670e-8, "W/(m^2 K^4)", "σ", "stefan|stefan-boltzmann"),
    "F_c": (96485.0, "C/mol", "F", "faraday constant|faraday's constant"),
    "k_e": (8.988e9, "N m^2/C^2", "k", "coulomb's constant|coulomb constant"),
    "K_w": (1e-14, "1", "K_w", "ionic product of water|kw"),
    "b_w": (2.898e-3, "m K", "b", "wien"),
    "hbar": (1.0546e-34, "J s", "ħ", "reduced planck"),
}

# Facts a question implies without stating a number: (pattern, quantity, value in SI).
IMPLIED = [
    (r"\b(from rest|starts? (off )?(from|at) rest|initially at rest|released from rest|at rest initially|"
     r"is released|was released|dropped|falls? freely|free[- ]?fall|let go)\b", "speed:initial", 0.0),
    (r"\b(comes? to (rest|a stop|a halt)|brought to rest|brought to a (stop|halt)|stops|stopped|"
     r"maximum height|highest point|top of its (flight|path)|to rest)\b", "speed:final", 0.0),
    (r"\b(dropped|falls? freely|free[- ]?fall|freely falling|falling freely|thrown (vertically )?(up|upwards|down)|"
     r"projected (vertically )?(up|upwards)|vertically upwards?|dropped from|falls from|fell from|"
     r"maximum height|highest point)\b", "acceleration", 9.81),
    (r"\bwater\b", "density", 1000.0),
    (r"\bwater\b", "specific heat capacity", 4200.0),
    (r"\b(ice|melt|melting|fusion)\b", "specific latent heat", 3.34e5),
    (r"\b(steam|boil|boiling|vapori[sz]e|vapori[sz]ation|evaporat)", "specific latent heat", 2.26e6),
    (r"\b(light|electromagnetic|radio waves?|microwaves?|x-?rays?|gamma|infra-?red|ultra-?violet|photons?|laser|"
     r"visible)\b", "wave speed", 2.998e8),
    (r"\b(r\.?t\.?p\.?|room temperature and pressure)\b", "molar volume", 0.024),
    (r"\b(s\.?t\.?p\.?|standard temperature and pressure)\b", "molar volume", 0.0224),
    (r"\bstereo\b", "channels", 2.0),
    (r"\bmono\b", "channels", 1.0),
    (r"\bmains\b", "frequency", 50.0),
]

# ── formulas ──────────────────────────────────────────────────────────────
# (name, topic, equation, {symbol: quantity[:role] | @constant}, needs) — `needs`: words that must appear in the
# question for the formula to be considered (keeps special-purpose formulas from firing on everything).
FORMULAS = []
_topic = "general"


def topic(name):
    global _topic
    _topic = name


def F(name, eq, needs="", _nodims=False, _excludes="", **vars):
    FORMULAS.append({"name": name, "topic": _topic, "eq": eq, "vars": vars, "nodims": _nodims,
                     "needs": [w for w in needs.split("|") if w], "excludes": [w for w in _excludes.split("|") if w]})


# Single-phase power formulas give wrong answers for a three-phase machine (S = √3·V_L·I_L there).
THREE_PHASE = "three-phase|three phase|3-phase|3 phase|3-ph|polyphase"


topic("mechanics")
F("Speed", "v = d/t", v="speed", d="distance", t="time")
F("Acceleration", "a = (v - u)/t", a="acceleration", v="speed:final", u="speed:initial", t="time")
F("Equation of motion (s = ut + ½at²)", "s = u*t + a*t**2/2", s="distance", u="speed:initial", t="time", a="acceleration")
F("Equation of motion (v² = u² + 2as)", "v**2 = u**2 + 2*a*s", v="speed:final", u="speed:initial", a="acceleration", s="distance")
F("Equation of motion (s = (u + v)t/2)", "s = (u + v)*t/2", s="distance", u="speed:initial", v="speed:final", t="time")
F("Fall from a height (s = ut + ½gt²)", "h = u*t + g*t**2/2", needs="fall|falls|dropped|drop|height|cliff|tower|building|vertically",
  h="height", u="speed:initial", t="time", g="@g")
F("Speed after falling (v² = u² + 2gh)", "v**2 = u**2 + 2*g*h", needs="fall|falls|dropped|height|cliff|tower|building|vertically|thrown|projected",
  v="speed:final", u="speed:initial", g="@g", h="height")
F("Rise to maximum height (v = u − gt)", "v = u - g*t", needs="thrown|projected|vertically|upwards|maximum height|highest",
  v="speed:final", u="speed:initial", g="@g", t="time")
F("Newton's second law", "F = m*a", F="force", m="mass", a="acceleration")
F("Weight", "W = m*g", W="weight", m="mass", g="@g")
F("Momentum", "p = m*v", p="momentum", m="mass", v="speed")
F("Impulse", "J = F*t", J="impulse", F="force", t="time")
F("Impulse and change of momentum", "F*t = m*(v - u)", F="force", t="time", m="mass", v="speed:final", u="speed:initial")
F("Kinetic energy", "E_k = m*v**2/2", E_k="kinetic energy", m="mass", v="speed")
F("Gravitational potential energy", "E_p = m*g*h", E_p="potential energy", m="mass", g="@g", h="height")
F("Work done", "W = F*d", W="work", F="force", d="distance")
F("Work done against gravity", "W = m*g*h", needs="lift|lifted|raise|raised|climb|climbs|up|height",
  W="work", m="mass", g="@g", h="height")
F("Work done by a force at an angle", "W = F*d*cos(theta)", needs="angle|°|degrees", W="work", F="force", d="distance", theta="angle")
F("Power from work", "P = W/t", P="power", W="work", t="time")
F("Power from energy", "P = E/t", P="power", E="energy", t="time")
F("Power and speed", "P = F*v", P="power", F="force", v="speed")
F("Efficiency (energy)", "eta = E_out/E_in", eta="efficiency", E_out="energy:out", E_in="energy:in")
F("Efficiency (power)", "eta = P_out/P_in", eta="efficiency", P_out="power:out", P_in="power:in")
F("Pressure", "p = F/A", p="pressure", F="force", A="area")
F("Pressure from weight", "p = m*g/A", needs="stand|stands|standing|rest|rests|block|weighs|on the floor|on the ground",
  p="pressure", m="mass", g="@g", A="area")
F("Pressure in a fluid", "p = rho*g*h", needs="depth|deep|liquid|water|fluid|column|below the surface|tank|dam|sea",
  p="pressure", rho="density", g="@g", h="height")
F("Density", "rho = m/V", rho="density", m="mass", V="volume")
F("Moment of a force", "M = F*d", M="moment", F="force", d="distance")
F("Hooke's law", "F = k*x", F="force", k="spring constant", x="extension")
F("Elastic potential energy", "E = k*x**2/2", needs="spring|stretched|elastic|compressed|extension", E="energy", k="spring constant", x="extension")
F("Elastic energy from force and extension", "E = F*x/2", needs="spring|stretched|elastic|compressed|extension|wire",
  E="energy", F="force", x="extension")
F("Friction", "F_f = mu*N", F_f="friction", mu="friction coefficient", N="normal reaction")
F("Friction on a level surface", "F_f = mu*m*g", needs="friction|rough|coefficient", F_f="friction", mu="friction coefficient", m="mass", g="@g")
F("Component of weight down a slope", "F = m*g*sin(theta)", needs="slope|incline|inclined|ramp|plane",
  F="force", m="mass", g="@g", theta="angle")
F("Stress", "sigma_s = F/A", sigma_s="stress", F="force", A="area")
F("Strain", "eps = x/L", eps="strain", x="extension", L="length")
F("Young's modulus", "Y = sigma_s/eps", Y="young modulus", sigma_s="stress", eps="strain")
F("Young's modulus (from measurements)", "Y = F*L/(A*x)", Y="young modulus", F="force", L="length", A="area", x="extension")
F("Upthrust (Archimedes)", "U = rho*V*g", needs="upthrust|buoyant|buoyancy|float|floats|immersed|submerged|displaced",
  U="upthrust", rho="density", V="volume", g="@g")
F("Flow rate", "Q_f = A*v", Q_f="flow rate", A="area", v="speed")
F("Mechanical advantage", "MA = L/E", MA="mechanical advantage", L="load", E="effort")
F("Efficiency of a machine", "eta = MA/VR", eta="efficiency", MA="mechanical advantage", VR="velocity ratio")
F("Velocity ratio of an inclined plane", "VR = 1/sin(theta)", needs="inclined plane|incline|slope|ramp",
  VR="velocity ratio", theta="angle")
F("Speed in a circle", "v = 2*pi*r/T", needs="circle|circular|orbit|revolution|rotates|round|whirled",
  v="speed", r="radius", T="period")
F("Angular velocity", "omega = 2*pi/T", omega="angular velocity", T="period")
F("Angular velocity from frequency", "omega = 2*pi*f", omega="angular velocity", f="frequency")
F("Angular velocity from rotational speed", "omega = 2*pi*n", omega="angular velocity", n="rotational speed")
F("Speed from angular velocity", "v = omega*r", v="speed", omega="angular velocity", r="radius")
F("Centripetal acceleration", "a_c = v**2/r", a_c="centripetal acceleration", v="speed", r="radius")
F("Centripetal force", "F_c = m*v**2/r", F_c="centripetal force", m="mass", v="speed", r="radius")
F("Centripetal force (ω)", "F_c = m*omega**2*r", F_c="centripetal force", m="mass", omega="angular velocity", r="radius")
F("Newton's law of gravitation", "F = G*m_1*m_2/r**2", needs="gravitational|gravity|attract|planet|earth|moon|sun|masses",
  F="force", G="@G", m_1="mass:1", m_2="mass:2", r="distance")
F("Gravitational field strength", "g_f = G*M/r**2", needs="planet|earth|moon|sun|mars|surface|field strength",
  g_f="gravitational field strength", G="@G", M="mass", r="radius")
F("Orbital speed", "v = sqrt(G*M/r)", needs="orbit|satellite|orbital", v="speed", G="@G", M="mass", r="radius")
F("Period of a pendulum", "T = 2*pi*sqrt(L/g)", needs="pendulum", T="period", L="length", g="@g")
F("Period of a mass on a spring", "T = 2*pi*sqrt(m/k)", needs="spring|oscillat", T="period", m="mass", k="spring constant")
F("Torque from power", "T = P/omega", T="moment", P="power", omega="angular velocity")
F("Range of a projectile", "R_p = u**2*sin(2*theta)/g", needs="projectile|projected|launched|fired|kicked|thrown|range",
  R_p="distance", u="speed:initial", theta="angle", g="@g")
F("Maximum height of a projectile", "H = u**2*sin(theta)**2/(2*g)", needs="projectile|projected|launched|fired|kicked|thrown",
  H="height", u="speed:initial", theta="angle", g="@g")
F("Time of flight of a projectile", "t = 2*u*sin(theta)/g", needs="projectile|projected|launched|fired|kicked|thrown",
  t="time", u="speed:initial", theta="angle", g="@g")
F("Kinetic energy of rotation", "E = I_m*omega**2/2", needs="rotat|flywheel|wheel|spinning", E="kinetic energy",
  I_m="moment of inertia", omega="angular velocity")
F("Angular momentum", "L_a = I_m*omega", L_a="angular momentum", I_m="moment of inertia", omega="angular velocity")

topic("waves and optics")
F("Wave equation", "v = f*lam", v="wave speed", f="frequency", lam="wavelength")
F("Frequency and period", "f = 1/T", f="frequency", T="period")
F("Refractive index from speeds", "n = c/v", needs="refractive|index|medium|glass|water|slow", n="refractive index", c="@c", v="wave speed")
F("Snell's law (from air)", "n = sin(i)/sin(r)", needs="refract|snell|incidence|incident|refractive",
  n="refractive index", i="angle:incidence", r="angle:refraction")
F("Snell's law", "n_1*sin(theta_1) = n_2*sin(theta_2)", needs="refract|snell|incidence|incident|refractive",
  n_1="refractive index:1", theta_1="angle:incidence", n_2="refractive index:2", theta_2="angle:refraction")
F("Critical angle", "sin(C) = 1/n", needs="critical|total internal", C="angle:critical", n="refractive index")
F("Lens formula", "1/f = 1/u + 1/v", needs="lens|mirror|focal|image|object", f="focal length", u="object distance", v="image distance")
F("Magnification (distances)", "m = v/u", needs="lens|mirror|image|object", m="magnification", v="image distance", u="object distance")
F("Magnification (sizes)", "m = h_i/h_o", m="magnification", h_i="image size", h_o="object size")
F("Power of a lens", "P = 1/f", needs="lens|dioptre|diopter|power of", P="lens power", f="focal length")
F("Young's double slit", "lam = a*x/D", needs="slit|fringe|young|interference", lam="wavelength", a="slit separation",
  x="fringe spacing", D="screen distance")
F("Diffraction grating", "d*sin(theta) = n*lam", needs="grating|diffraction|order", d="slit separation", theta="angle",
  n="order", lam="wavelength")
F("Grating spacing", "d = 1/N", needs="grating|lines", d="slit separation", N="lines per metre")
F("Echo", "2*d = v*t", needs="echo|reflected sound|sonar|returns", d="distance", v="wave speed", t="time")
F("Intensity", "I = P/A", needs="intensity", I="intensity", P="power", A="area")

topic("electricity")
F("Ohm's law", "V = I*R", V="voltage", I="current", R="resistance")
F("Electrical power (P = VI)", "P = V*I", _excludes=THREE_PHASE, P="power", V="voltage", I="current")
F("Electrical power (P = I²R)", "P = I**2*R", _excludes=THREE_PHASE, P="power", I="current", R="resistance")
F("Electrical power (P = V²/R)", "P = V**2/R", _excludes=THREE_PHASE, P="power", V="voltage", R="resistance")
F("Charge and current", "Q = I*t", Q="charge", I="current", t="time")
F("Energy and charge", "W = Q*V", W="energy", Q="charge", V="voltage")
F("Electrical energy", "E = V*I*t", _excludes=THREE_PHASE, E="energy", V="voltage", I="current", t="time")
F("Energy and power", "E = P*t", E="energy", P="power", t="time")
F("Cost of electricity", "C_e = E*p_u", C_e="cost", E="energy", p_u="unit price")
F("Resistivity", "R = rho*L/A", needs="resistivity|wire|length|cross", R="resistance", rho="resistivity", L="length", A="area")
F("Resistance and temperature", "R = R_0*(1 + alpha*dT)", needs="temperature coefficient", R="resistance:2", R_0="resistance:1",
  alpha="temperature coefficient", dT="temperature change")
F("Resistors in series (two)", "R_T = R_1 + R_2", needs="series", R_T="resistance", R_1="resistance:1", R_2="resistance:2")
F("Resistors in parallel (two)", "1/R_T = 1/R_1 + 1/R_2", needs="parallel", R_T="resistance", R_1="resistance:1", R_2="resistance:2")
F("EMF and internal resistance", "E = I*(R + r)", needs="internal resistance", E="emf", I="current", R="resistance", r="internal resistance")
F("Terminal voltage", "V = E - I*r", needs="internal resistance|terminal", V="voltage", E="emf", I="current", r="internal resistance")
F("Current from emf", "E = I*R", needs="battery|cell|emf|e.m.f|supply|source", E="emf", I="current", R="resistance")
F("Power from emf", "P = E*I", needs="battery|cell|emf|e.m.f|supply|source|generator", P="power", E="emf", I="current")
F("Conductance", "G_c = 1/R", needs="conductance", G_c="conductance", R="resistance")
F("Capacitance", "C = Q/V", C="capacitance", Q="charge", V="voltage")
F("Energy in a capacitor", "W = C*V**2/2", needs="capacitor|capacitance", W="energy", C="capacitance", V="voltage")
F("Parallel-plate capacitor", "C = eps0*eps_r*A/d", needs="plate|plates|dielectric|permittivity",
  C="capacitance", eps0="@eps0", eps_r="relative permittivity", A="area", d="distance")
F("Time constant", "tau = R*C", tau="time constant", R="resistance", C="capacitance")
F("Capacitors in parallel (two)", "C_T = C_1 + C_2", needs="parallel", C_T="capacitance", C_1="capacitance:1", C_2="capacitance:2")
F("Capacitors in series (two)", "1/C_T = 1/C_1 + 1/C_2", needs="series", C_T="capacitance", C_1="capacitance:1", C_2="capacitance:2")
F("Electric field between plates", "E = V/d", needs="field|plates", E="electric field strength", V="voltage", d="distance")
F("Force on a charge in a field", "F = q*E", needs="field", F="force", q="charge", E="electric field strength")
F("Coulomb's law", "F = k_e*q_1*q_2/r**2", needs="coulomb|charges|point charge|repel|attract",
  F="force", k_e="@k_e", q_1="charge:1", q_2="charge:2", r="distance")
F("Energy in electronvolts", "E = e*V", needs="accelerated|electron|electronvolt|ev", E="kinetic energy", e="@e", V="voltage")
F("Transistor current gain", "beta = I_C/I_B", needs="transistor|collector|base", beta="current gain", I_C="current:collector", I_B="current:base")
F("Inverting amplifier gain", "A_v = R_f/R_in", needs="inverting|op-amp|op amp|operational", A_v="gain", R_f="resistance:feedback", R_in="resistance:input")
F("Voltage gain", "A_v = V_out/V_in", needs="gain|amplifier", A_v="gain", V_out="voltage:out", V_in="voltage:in")

topic("ac circuits")
F("Inductive reactance", "X_L = 2*pi*f*L", X_L="inductive reactance", f="frequency", L="inductance")
F("Capacitive reactance", "X_C = 1/(2*pi*f*C)", X_C="capacitive reactance", f="frequency", C="capacitance")
F("Impedance (R and X)", "Z = sqrt(R**2 + X**2)", Z="impedance", R="resistance", X="reactance")
F("Impedance (R and L)", "Z = sqrt(R**2 + X_L**2)", Z="impedance", R="resistance", X_L="inductive reactance")
F("Impedance (R and C)", "Z = sqrt(R**2 + X_C**2)", Z="impedance", R="resistance", X_C="capacitive reactance")
F("Impedance (R, L and C)", "Z = sqrt(R**2 + (X_L - X_C)**2)", Z="impedance", R="resistance", X_L="inductive reactance",
  X_C="capacitive reactance")
F("Ohm's law for AC", "V = I*Z", V="voltage", I="current", Z="impedance")
F("Resonant frequency", "f = 1/(2*pi*sqrt(L*C))", needs="resonan", f="frequency", L="inductance", C="capacitance")
F("Power factor", "pf = R/Z", pf="power factor", R="resistance", Z="impedance")
F("Power factor and phase angle", "pf = cos(phi)", pf="power factor", phi="phase angle")
F("Real power", "P = V*I*pf", _excludes=THREE_PHASE, needs="power factor|pf|p.f|real power|true power|active power|lagging|leading|cos",
  P="power", V="voltage", I="current", pf="power factor")
F("Apparent power", "S = V*I", needs="apparent|va|kva", _excludes=THREE_PHASE, S="apparent power", V="voltage", I="current")
F("Three-phase apparent power", "S = sqrt(3)*V_L*I_L", needs="three-phase|three phase|3-phase|3 phase",
  S="apparent power", V_L="voltage:line", I_L="current:line")
F("Real power from apparent power", "P = S*pf", P="power", S="apparent power", pf="power factor")
F("Power triangle", "S**2 = P**2 + Q_r**2", S="apparent power", P="power", Q_r="reactive power")
F("RMS voltage", "V_rms = V_pk/sqrt(2)", needs="rms|r.m.s|peak|root mean square|effective", V_rms="voltage:rms", V_pk="voltage:peak")
F("RMS current", "I_rms = I_pk/sqrt(2)", needs="rms|r.m.s|peak|root mean square|effective", I_rms="current:rms", I_pk="current:peak")
F("Three-phase power", "P = sqrt(3)*V_L*I_L*pf", needs="three-phase|three phase|3-phase|3 phase", P="power",
  V_L="voltage:line", I_L="current:line", pf="power factor")
F("Star connection voltages", "V_L = sqrt(3)*V_ph", needs="star|wye", V_L="voltage:line", V_ph="voltage:phase")
F("Delta connection currents", "I_L = sqrt(3)*I_ph", needs="delta|mesh", I_L="current:line", I_ph="current:phase")

topic("magnetism and machines")
F("Magnetomotive force", "F_m = N*I", F_m="mmf", N="turns", I="current")
F("Magnetic field strength", "H = N*I/l", H="magnetic field strength", N="turns", I="current", l="magnetic path length")
F("Magnetic field strength from mmf", "H = F_m/l", H="magnetic field strength", F_m="mmf", l="magnetic path length")
F("Flux density and field strength", "B = mu0*mu_r*H", B="flux density", mu0="@mu0", mu_r="relative permeability",
  H="magnetic field strength")
F("Flux density in air", "B = mu0*H", needs="air|vacuum|air gap|free space|non-magnetic", B="flux density", mu0="@mu0",
  H="magnetic field strength")
F("Permeability", "mu = mu0*mu_r", mu="permeability", mu0="@mu0", mu_r="relative permeability")
F("Flux density and permeability", "B = mu*H", B="flux density", mu="permeability", H="magnetic field strength")
F("Magnetic flux", "Phi = B*A", Phi="magnetic flux", B="flux density", A="area")
F("Reluctance", "S_r = l/(mu0*mu_r*A)", S_r="reluctance", l="magnetic path length", mu0="@mu0", mu_r="relative permeability", A="area")
F("Magnetic Ohm's law", "Phi = F_m/S_r", Phi="magnetic flux", F_m="mmf", S_r="reluctance")
F("Inductance from flux", "L = N*Phi/I", L="inductance", N="turns", Phi="magnetic flux", I="current")
F("Inductance from reluctance", "L = N**2/S_r", L="inductance", N="turns", S_r="reluctance")
F("Energy stored in an inductor", "W = L*I**2/2", needs="inductor|inductance|coil|stored", W="energy", L="inductance", I="current")
F("Magnetic energy density", "w = B**2/(2*mu0*mu_r)", needs="energy density|per unit volume", w="energy density",
  B="flux density", mu0="@mu0", mu_r="relative permeability")
F("Energy stored in a magnetic field", "W = F_m*Phi/2", needs="stored|field energy|energy in the field|magnetic energy",
  W="energy", F_m="mmf", Phi="magnetic flux")
F("Force on a current-carrying conductor", "F = B*I*l", needs="conductor|wire|current-carrying|current carrying|motor",
  F="force", B="flux density", I="current", l="length")
F("Force on a moving charge", "F = B*q*v", needs="charge|electron|proton|particle|moving", F="force", B="flux density", q="charge", v="speed")
F("Torque on a coil", "T = B*A*N*I", needs="coil|galvanometer|loop|meter", T="moment", B="flux density", A="area", N="turns", I="current")
F("Faraday's law", "e = N*Phi/t", needs="induced|faraday|changes|falls|reduced|collapses|linking", e="emf", N="turns",
  Phi="magnetic flux", t="time")
F("EMF in a moving conductor", "e = B*l*v", needs="moving|moves|conductor|rod|wire|cuts", e="emf", B="flux density", l="length", v="speed")
F("Force from energy change", "F = W/x", needs="rate|energy changes|changes at|per metre|dw/dx|energy|mechanical",
  F="force", W="energy", x="distance")
F("Reluctance force", "F = Phi**2*k_r/2", needs="reluctance", F="force", Phi="magnetic flux", k_r="reluctance gradient")
F("Transformer voltage ratio", "V_s/V_p = N_s/N_p", needs="transformer|primary|secondary", V_s="voltage:secondary",
  V_p="voltage:primary", N_s="turns:secondary", N_p="turns:primary")
F("Ideal transformer power", "V_p*I_p = V_s*I_s", needs="transformer|primary|secondary", V_p="voltage:primary",
  I_p="current:primary", V_s="voltage:secondary", I_s="current:secondary")
F("Transformer EMF equation", "E = 4.44*f*N*Phi", needs="transformer|emf equation|4.44|maximum flux|peak flux",
  E="emf", f="frequency", N="turns", Phi="magnetic flux")
F("Transformer turns ratio", "a = N_p/N_s", needs="turns ratio|transformation ratio", a="turns ratio",
  N_p="turns:primary", N_s="turns:secondary")
F("Synchronous speed", "n_s = 2*f/p", needs="motor|synchronous|poles|pole|induction|alternator|generator",
  n_s="rotational speed:sync", f="frequency", p="poles")
F("Slip", "s = (n_s - n_r)/n_s", needs="slip|motor|induction", s="slip", n_s="rotational speed:sync", n_r="rotational speed:rotor")
F("Rotor frequency", "f_r = s*f", needs="rotor", f_r="frequency:2", s="slip", f="frequency:1")
F("Rotor copper loss", "P_cu = s*P_ag", needs="copper loss|air gap|air-gap|rotor", P_cu="power:rotor cu", s="slip", P_ag="power:air gap")
F("Mechanical power developed", "P_m = (1 - s)*P_ag", needs="mechanical|developed|air gap|air-gap", P_m="power:mech", s="slip",
  P_ag="power:air gap")
F("Rotor input (air-gap) power", "P_ag = P_in - P_sl", needs="stator loss|stator losses|air gap|air-gap|rotor input",
  P_ag="power:air gap", P_in="power:in", P_sl="power:stator loss")
F("Motor output power", "P_out = P_m - P_fw", needs="friction|windage|mechanical loss|rotational loss",
  P_out="power:out", P_m="power:mech", P_fw="power:friction")
F("Torque from speed", "T = P/(2*pi*n)", needs="torque", T="moment", P="power", n="rotational speed")
F("DC motor back EMF", "E_b = V - I_a*R_a", needs="motor|back emf|back e.m.f", _excludes="brush|generator",
  E_b="emf:back", V="voltage", I_a="current:armature", R_a="resistance:armature")
F("DC generator EMF", "E_g = V + I_a*R_a", needs="generator|generated", _excludes="brush|motor", E_g="emf:back",
  V="voltage", I_a="current:armature", R_a="resistance:armature")
F("DC generator EMF with brush drop", "E_g = V + I_a*R_a + V_b", needs="brush", _excludes="motor", E_g="emf:back",
  V="voltage", I_a="current:armature", R_a="resistance:armature", V_b="voltage:brush")
F("DC motor back EMF with brush drop", "E_b = V - I_a*R_a - V_b", needs="brush", _excludes="generator", E_b="emf:back",
  V="voltage", I_a="current:armature", R_a="resistance:armature", V_b="voltage:brush")
F("Shunt field current", "I_f = V/R_f", needs="shunt|field", I_f="current:field", V="voltage", R_f="resistance:field")
F("Shunt generator armature current", "I_a = I_L + I_f", needs="shunt", _excludes="motor", I_a="current:armature",
  I_L="current:load", I_f="current:field")
F("Shunt motor armature current", "I_a = I_L - I_f", needs="shunt", _excludes="generator", I_a="current:armature",
  I_L="current:line", I_f="current:field")
F("Total armature conductors", "Z = N_s*z_s", needs="slot|slots", Z="conductors", N_s="slots", z_s="conductors per slot")
F("Current in each armature conductor", "I_c = I_a/A_p", needs="conductor|conductors", I_c="current:conductor",
  I_a="current:armature", A_p="parallel paths")
F("Generator current at full load", "P = E*I_a", needs="full load|full-load|delivers", _excludes="motor", P="power",
  E="emf", I_a="current:armature")
F("Generator EMF equation", "E = p*Phi*Z*n/A_p", needs="generator|conductors|parallel paths|armature", E="emf", p="poles",
  Phi="magnetic flux", Z="conductors", n="rotational speed", A_p="parallel paths")

topic("heat")
F("Specific heat capacity", "Q = m*c*dT", Q="heat", m="mass", c="specific heat capacity", dT="temperature change")
F("Heat capacity", "Q = C_h*dT", Q="heat", C_h="heat capacity", dT="temperature change")
F("Temperature change", "dT = T_2 - T_1", needs="temperature change|change in temperature|rise in temperature|temperature rise",
  dT="temperature change", T_1="temperature:1", T_2="temperature:2")
F("Latent heat", "Q = m*L", needs="latent|melt|melting|boil|boiling|vapori|freez|condens|steam|ice|fusion|evaporat",
  Q="heat", m="mass", L="specific latent heat")
F("Electrical heating", "P*t = m*c*dT", needs="heater|kettle|element|immersion|electric|electrical",
  P="power", t="time", m="mass", c="specific heat capacity", dT="temperature change")
F("Thermal expansion", "dL = alpha*L*dT", needs="expan|expand|expands|lengthen|expansivity", dL="extension", alpha="expansivity",
  L="length", dT="temperature change")
F("Thermal conduction", "P = k_t*A*dT/d", needs="conduct|conduction|conductivity|through the wall|through the window|slab",
  P="power", k_t="thermal conductivity", A="area", dT="temperature change", d="distance")
F("Ideal gas equation", "p*V = n*R*T", needs="gas|ideal|mol|moles", p="pressure", V="volume", n="amount", R="@R", T="temperature")
F("Boyle's law", "p_1*V_1 = p_2*V_2", needs="boyle|compressed|expanded|gas|pressure", p_1="pressure:1", V_1="volume:1",
  p_2="pressure:2", V_2="volume:2")
F("Charles's law", "V_1/T_1 = V_2/T_2", needs="charles|gas|heated|cooled|temperature", V_1="volume:1", T_1="temperature:1",
  V_2="volume:2", T_2="temperature:2")
F("Pressure law", "p_1/T_1 = p_2/T_2", needs="pressure law|gas|heated|cooled|sealed|tyre|tire|container",
  p_1="pressure:1", T_1="temperature:1", p_2="pressure:2", T_2="temperature:2")
F("General gas law", "p_1*V_1/T_1 = p_2*V_2/T_2", needs="gas", p_1="pressure:1", V_1="volume:1", T_1="temperature:1",
  p_2="pressure:2", V_2="volume:2", T_2="temperature:2")
F("Mean kinetic energy of a molecule", "E_k = 3*k_B*T/2", needs="molecule|molecules|average kinetic|mean kinetic",
  E_k="kinetic energy", k_B="@k_B", T="temperature")
F("Heat engine efficiency (Carnot)", "eta = 1 - T_c/T_h", needs="carnot|engine|reservoir|heat engine", eta="efficiency",
  T_c="temperature:cold", T_h="temperature:hot")
F("Stefan–Boltzmann law", "P = sigma*A*T**4", needs="stefan|radiat|black body|blackbody|emits", P="power", sigma="@sigma",
  A="area", T="temperature")
F("Wien's law", "lam*T = b_w", needs="wien|peak wavelength|maximum wavelength|peak emission", lam="wavelength",
  T="temperature", b_w="@b_w")

topic("modern physics")
F("Photon energy", "E = h*f", needs="photon|quantum|planck|light|radiation|energy of", E="photon energy", h="@h", f="frequency")
F("Photon energy from wavelength", "E = h*c/lam", needs="photon|quantum|planck|light|radiation|energy of", E="photon energy",
  h="@h", c="@c", lam="wavelength")
F("Photoelectric equation", "h*f = phi + E_k", needs="photoelectric|work function|emitted|photoelectron", h="@h",
  f="frequency", phi="work function", E_k="kinetic energy")
F("Work function and threshold frequency", "phi = h*f_0", needs="work function|threshold", phi="work function", h="@h",
  f_0="threshold frequency")
F("Stopping potential", "E_k = e*V_s", needs="stopping", E_k="kinetic energy", e="@e", V_s="stopping potential")
F("de Broglie wavelength", "lam = h/(m*v)", needs="de broglie|wavelength of|electron|particle|wave nature",
  lam="wavelength", h="@h", m="mass", v="speed")
F("de Broglie wavelength (momentum)", "lam = h/p", needs="de broglie|wavelength of|wave nature", lam="wavelength", h="@h", p="momentum")
F("Mass–energy equivalence", "E = m*c**2", needs="einstein|mass-energy|converted|mass defect|e = mc|annihilat|nuclear|fission|fusion",
  E="energy", m="mass", c="@c")
F("Binding energy from mass defect", "E_b = dm*c**2", needs="binding|mass defect", E_b="binding energy", dm="mass defect", c="@c")
F("Radioactive decay (half-lives)", "N = N_0*(1/2)**(t/T_h)", needs="half-life|half life|decay|radioactive|isotope|sample",
  N="particles:2", N_0="particles:1", t="time", T_h="half-life")
F("Mass remaining after decay", "m = m_0*(1/2)**(t/T_h)", needs="half-life|half life|decay|radioactive|isotope|sample",
  m="mass:2", m_0="mass:1", t="time", T_h="half-life")
F("Activity after decay", "A = A_0*(1/2)**(t/T_h)", needs="half-life|half life|decay|radioactive|activity|count rate",
  A="activity:2", A_0="activity:1", t="time", T_h="half-life")
F("Decay constant", "lam_d = log(2)/T_h", needs="decay constant", lam_d="decay constant", T_h="half-life")
F("Activity", "A = lam_d*N", needs="activity|decay constant", A="activity", lam_d="decay constant", N="particles")

topic("chemistry")
F("Moles from mass", "n = m/M", n="amount", m="mass", M="molar mass")
F("Moles from particles", "n = N/N_A", n="amount", N="particles", N_A="@N_A")
F("Moles from concentration", "n = c*V", n="amount", c="concentration", V="volume")
F("Mass concentration", "rho_c = m/V", needs="concentration|g/dm|g dm|grams per", rho_c="mass concentration", m="mass", V="volume")
F("Concentration conversion", "rho_c = c*M", needs="concentration|g/dm|g dm", rho_c="mass concentration", c="concentration", M="molar mass")
F("Dilution", "c_1*V_1 = c_2*V_2", needs="dilut|diluted|made up|top up|topped up|water is added", c_1="concentration:1",
  V_1="volume:1", c_2="concentration:2", V_2="volume:2")
F("Moles of gas from volume", "n = V/V_m", needs="gas|r.t.p|rtp|s.t.p|stp|molar volume", n="amount", V="volume", V_m="molar volume")
F("Gas density", "rho = p*M/(R*T)", needs="gas|density of the gas", rho="density", p="pressure", M="molar mass", R="@R", T="temperature")
F("pH", "pH = -log(H, 10)", needs="ph|acid|alkali|hydrogen ion|h+", pH="pH", H="hydrogen ion concentration")
F("pOH", "pOH = -log(OH, 10)", needs="poh|hydroxide|oh-|alkali|base", pOH="pOH", OH="hydroxide ion concentration")
F("pH and pOH", "pH + pOH = 14", needs="ph|poh", pH="pH", pOH="pOH")
F("Ionic product of water", "H*OH = K_w", needs="hydroxide|oh-|[oh", H="hydrogen ion concentration", OH="hydroxide ion concentration",
  K_w="@K_w")
F("pKa", "pKa = -log(Ka, 10)", needs="pka|ka", pKa="pKa", Ka="acid dissociation constant")
F("Weak acid pH", "Ka = H**2/c_a", needs="weak acid|ka|ethanoic|acetic|dissociat", Ka="acid dissociation constant",
  H="hydrogen ion concentration", c_a="acid concentration")
F("Henderson–Hasselbalch", "pH = pKa + log(A_s/A_c, 10)", needs="buffer|henderson|salt", pH="pH", pKa="pKa",
  A_s="salt concentration", A_c="acid concentration")
F("Percentage yield", "Y = m_a/m_t", needs="yield", Y="percentage yield", m_a="actual yield", m_t="theoretical yield")
F("Enthalpy change from heat", "dH = -Q/n", needs="enthalpy|δh|heat of|per mole|kj/mol|kj mol", dH="enthalpy change", Q="heat", n="amount")
F("Gibbs free energy", "dG = dH - T*dS", needs="gibbs|free energy|δg|feasible|spontaneous", dG="gibbs energy",
  dH="enthalpy change", T="temperature", dS="entropy change")
F("Gibbs energy and cell potential", "dG = -z*F_c*E", needs="gibbs|free energy|δg", dG="gibbs energy",
  z="electrons transferred", F_c="@F_c", E="cell potential")
F("Cell potential", "E = E_c - E_a", needs="cell|electrode|half-cell|half cell", E="cell potential",
  E_c="electrode potential:cathode", E_a="electrode potential:anode")
F("Electrolysis (Faraday)", "m = Q*M/(z*F_c)", needs="electrolysis|deposited|liberated|plated|electroplat|cathode|faraday",
  m="mass", Q="charge", M="molar mass", z="electrons transferred", F_c="@F_c")
F("Moles of electrons", "n = Q/F_c", needs="electrolysis|faraday|moles of electrons", n="amount", Q="charge", F_c="@F_c")
F("Average rate of reaction", "r = dc/t", needs="rate", r="rate", dc="concentration", t="time")
F("First-order half-life", "T_h = log(2)/k", needs="first order|first-order|rate constant", T_h="half-life", k="rate constant")
F("Arrhenius equation", "k = A*exp(-E_a/(R*T))", needs="arrhenius|activation energy", k="rate constant",
  A="pre-exponential factor", E_a="activation energy", R="@R", T="temperature")
F("Beer–Lambert law", "A = eps*l*c", needs="absorbance|beer|lambert|colorimet|spectro", A="absorbance",
  eps="molar absorptivity", l="path length", c="concentration")
F("Particles from moles", "N = n*N_A", N="particles", n="amount", N_A="@N_A")
F("Molality", "b = n/m", needs="molality|molal", b="molality", n="amount", m="mass")

topic("biology")
F("Magnification", "M = I/A", needs="magnification|microscope|image|actual|micrograph|drawing|magnified|scale bar|actual size",
  M="magnification", I="image size", A="object size")
F("Total magnification", "M = M_e*M_o", needs="eyepiece|objective|microscope", M="magnification",
  M_e="magnification:eyepiece", M_o="magnification:objective")
F("Body mass index", "BMI = m/h**2", needs="bmi|body mass index", BMI="bmi", m="mass", h="height")
F("Hardy–Weinberg (alleles)", "p + q = 1", needs="allele|hardy|weinberg|recessive|dominant|gene pool",
  p="allele frequency:1", q="allele frequency:2")
F("Hardy–Weinberg (recessive genotype)", "q_2 = q**2", needs="allele|hardy|weinberg|recessive|homozygous recessive|affected",
  q_2="genotype frequency", q="allele frequency")
F("Hardy–Weinberg (heterozygotes)", "H_e = 2*p*q", needs="heterozygous|heterozygote|carrier|carriers",
  H_e="genotype frequency:2", p="allele frequency:1", q="allele frequency:2")
F("Lincoln index (capture–recapture)", "N = n_1*n_2/m_r", needs="capture|recapture|marked|lincoln|mark-release|mark release",
  N="population", n_1="first capture", n_2="second capture", m_r="marked recaptured")
F("Population density", "D = N/A", needs="density|per square|per m", D="population density", N="population", A="area")
F("Cardiac output", "CO = HR*SV", needs="cardiac|stroke volume|heart", CO="cardiac output", HR="heart rate", SV="stroke volume")
F("Pulmonary ventilation", "PV = TV*BR", needs="ventilation|tidal|breathing", PV="ventilation", TV="tidal volume", BR="breathing rate")
F("Temperature coefficient (Q10)", "Q10 = (R_2/R_1)**(10/dT)", needs="q10", _nodims=True, Q10="q10", R_2="reaction rate:2", R_1="reaction rate:1",
  dT="temperature change")
F("Respiratory quotient", "RQ = V_c/V_o", needs="respiratory quotient|rq", RQ="respiratory quotient", V_c="carbon dioxide", V_o="oxygen")
F("Water potential", "psi = psi_s + psi_p", needs="water potential|solute potential|pressure potential", psi="water potential",
  psi_s="solute potential", psi_p="pressure potential")
F("Mitotic index", "MI = n_m/n_t", needs="mitotic index|mitosis", MI="mitotic index", n_m="cells in mitosis", n_t="total cells")
F("Bacterial growth", "N = N_0*2**g_n", needs="bacteria|bacterial|divides|doubles|generation|culture|cells",
  N="population:2", N_0="population:1", g_n="generations")
F("Number of generations", "g_n = t/t_g", needs="bacteria|bacterial|divides|doubles|generation|culture|every",
  g_n="generations", t="time", t_g="generation time")
F("Rate from time", "r = 1/t", needs="rate", r="reaction rate", t="time")

topic("geometry")
F("Area of a rectangle", "A = l*w", needs="rectangle|rectangular|room|field|floor|plot|sheet", A="area", l="length", w="width")
F("Perimeter of a rectangle", "P = 2*(l + w)", needs="rectangle|rectangular|room|field|floor|plot|fence", P="perimeter", l="length", w="width")
F("Area of a square", "A = s**2", needs="square", A="area", s="side")
F("Perimeter of a square", "P = 4*s", needs="square", P="perimeter", s="side")
F("Area of a triangle", "A = b*h/2", needs="triangle|triangular", A="area", b="base length", h="height")
F("Area of a triangle (two sides and angle)", "A = a*b*sin(C)/2", needs="triangle|included angle", A="area",
  a="side:1", b="side:2", C="angle")
F("Area of a circle", "A = pi*r**2", needs="circle|circular|disc|disk|round", A="area", r="radius")
F("Area of a circle (diameter)", "A = pi*d**2/4", needs="circle|circular|disc|disk|round|pipe|wire", A="area", d="diameter")
F("Circumference", "C = 2*pi*r", needs="circle|circular|circumference|wheel|round|track", C="circumference", r="radius")
F("Circumference (diameter)", "C = pi*d", needs="circle|circular|circumference|wheel|round", C="circumference", d="diameter")
F("Diameter", "d = 2*r", d="diameter", r="radius")
F("Area of a trapezium", "A = (a + b)*h/2", needs="trapezium|trapezoid", A="area", a="parallel side:a", b="parallel side:b", h="height")
F("Area of a parallelogram", "A = b*h", needs="parallelogram", A="area", b="base length", h="height")
F("Area of a rhombus", "A = d_1*d_2/2", needs="rhombus|kite", A="area", d_1="diagonal:1", d_2="diagonal:2")
F("Arc length", "s = r*theta", needs="arc|sector", s="arc length", r="radius", theta="angle")
F("Area of a sector", "A = r**2*theta/2", needs="sector", A="area", r="radius", theta="angle")
F("Volume of a cuboid", "V = l*w*h", needs="cuboid|box|tank|rectangular|room|block|container", V="volume", l="length", w="width", h="height")
F("Volume of a cube", "V = s**3", needs="cube", V="volume", s="side")
F("Surface area of a cube", "A = 6*s**2", needs="cube", A="area", s="side")
F("Volume of a cylinder", "V = pi*r**2*h", needs="cylinder|cylindrical|pipe|tin|can|drum|tank|well", V="volume", r="radius", h="height")
F("Curved surface area of a cylinder", "A = 2*pi*r*h", needs="curved surface|cylinder", A="area", r="radius", h="height")
F("Total surface area of a cylinder", "A = 2*pi*r*h + 2*pi*r**2", needs="total surface|closed cylinder", A="area", r="radius", h="height")
F("Volume of a cone", "V = pi*r**2*h/3", needs="cone|conical", V="volume", r="radius", h="height")
F("Curved surface area of a cone", "A = pi*r*l", needs="cone|conical", A="area", r="radius", l="slant height")
F("Volume of a sphere", "V = 4*pi*r**3/3", needs="sphere|spherical|ball|globe", V="volume", r="radius")
F("Surface area of a sphere", "A = 4*pi*r**2", needs="sphere|spherical|ball|globe", A="area", r="radius")
F("Volume of a hemisphere", "V = 2*pi*r**3/3", needs="hemisphere|hemispherical|bowl", V="volume", r="radius")
F("Volume of a prism", "V = A*l", needs="prism", V="volume", A="area", l="length")
F("Volume of a pyramid", "V = A*h/3", needs="pyramid", V="volume", A="area", h="height")
F("Pythagoras' theorem", "c**2 = a**2 + b**2", needs="right-angled|right angled|right triangle|hypotenuse|pythagoras|ladder|diagonal",
  c="hypotenuse", a="side:1", b="side:2")
F("Sine ratio", "sin(theta) = o/h", needs="sin|sine|opposite|hypotenuse|right-angled|right angled|ladder|elevation|depression",
  theta="angle", o="opposite side", h="hypotenuse")
F("Cosine ratio", "cos(theta) = a/h", needs="cos|cosine|adjacent|hypotenuse|right-angled|right angled|ladder",
  theta="angle", a="adjacent side", h="hypotenuse")
F("Tangent ratio", "tan(theta) = o/a", needs="tan|tangent|opposite|adjacent|elevation|depression|shadow",
  theta="angle", o="opposite side", a="adjacent side")
F("Interior angle sum", "S_a = (n - 2)*pi", needs="polygon|sided|-gon|interior angles", S_a="angle sum", n="sides")
F("Interior angle of a regular polygon", "theta = (n - 2)*pi/n", needs="regular polygon|regular|interior angle",
  theta="interior angle", n="sides")
F("Exterior angle of a regular polygon", "theta = 2*pi/n", needs="regular polygon|regular|exterior angle",
  theta="exterior angle", n="sides")

topic("sequences")
F("nth term of an arithmetic progression", "T_n = a + (n - 1)*d", needs="arithmetic|a.p|ap|common difference|sequence|progression",
  T_n="nth term", a="first term", n="number of terms", d="common difference")
F("Sum of an arithmetic progression", "S_n = n*(2*a + (n - 1)*d)/2", needs="arithmetic|a.p|ap|common difference|sum",
  S_n="sum of terms", n="number of terms", a="first term", d="common difference")
F("nth term of a geometric progression", "T_n = a*r**(n - 1)", needs="geometric|g.p|gp|common ratio",
  T_n="nth term", a="first term", r="common ratio", n="number of terms")
F("Sum of a geometric progression", "S_n = a*(r**n - 1)/(r - 1)", needs="geometric|g.p|gp|common ratio",
  S_n="sum of terms", a="first term", r="common ratio", n="number of terms")
F("Sum to infinity", "S = a/(1 - r)", needs="infinity|infinite", S="sum to infinity", a="first term", r="common ratio")

topic("finance")
F("Simple interest", "I = P*R*T", needs="simple interest|interest|invest|borrow|loan|deposit|bank", I="interest",
  P="principal", R="interest rate", T="years")
F("Amount with simple interest", "A = P*(1 + R*T)", needs="simple interest|simple", A="final amount", P="principal",
  R="interest rate", T="years")
F("Compound interest", "A = P*(1 + R)**T", needs="compound|compounded", A="final amount", P="principal", R="interest rate", T="years")
F("Compound interest (k times a year)", "A = P*(1 + R/k)**(k*T)", needs="compounded|quarterly|monthly|semi-annual|half-yearly",
  A="final amount", P="principal", R="interest rate", k="compounding periods", T="years")
F("Depreciation (reducing balance)", "V_t = P*(1 - R)**T", needs="depreciat|loses value|reducing balance",
  V_t="final amount", P="principal", R="interest rate", T="years")
F("Profit", "Pr = SP - CP", needs="profit|loss|sold|sells|bought", Pr="profit", SP="selling price", CP="cost price")
F("Percentage profit", "pc = (SP - CP)/CP", needs="percentage profit|profit percent|% profit|percentage gain|percentage loss|profit",
  pc="percentage", SP="selling price", CP="cost price")
F("Percentage change", "pc = (x_2 - x_1)/x_1", needs="percentage change|percentage increase|percentage decrease|% change|"
  "% increase|% decrease|increased from|decreased from|rose from|fell from", pc="percentage", x_2="new value", x_1="original value")

topic("computing")
F("Transfer time", "t = S/r", needs="download|upload|transfer|send|sent|stream|connection|bandwidth|network",
  t="time", S="data size", r="data rate")
F("Image file size", "S = W_p*H_p*b", needs="image|bitmap|picture|photo|resolution|pixels", S="data size", W_p="pixels:1",
  H_p="pixels:2", b="colour depth")
F("Colours from colour depth", "N_c = 2**b", needs="colour|color|colours|colors", _nodims=True, N_c="colours", b="colour depth")
F("Sound file size", "S = f_s*b*t*ch", needs="sound|audio|sample|recording|song|music", S="data size", f_s="sample rate",
  b="sample resolution", t="time", ch="channels")
