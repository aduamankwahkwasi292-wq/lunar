"""The crib sheet's promise, checked: formulas and definitions exactly as the slides print them, nothing invented.
Cases from a real run (2026-10-30): "1/R = 1/R1 + 1/R2" became "R = 1/R1 + 1/R2", "P = V I = I^2 R = V^2/R" became
"R = V^2/R", and "An ammeter measures current and is …" gave the term "ammeter measures current and".

    python -m backend.crib_test
"""
import sys

from . import questions as Q

SUB1, SUB2, SUB3, SQ = chr(0x2081), chr(0x2082), chr(0x2083), chr(0x00B2)
OHM, DIV, TIMES = chr(0x03A9), chr(0x00F7), chr(0x00D7)

# slide text → the formula lines it must give (in order)
FORMULAS = [
    (f"Parallel: each resistor has the same voltage across it;  1/R = 1/R{SUB1} + 1/R{SUB2}",
     [f"1 / R = 1 / R{SUB1} + 1 / R{SUB2}"]),
    (f"Power is the rate of transferring energy:  P = V I = I{SQ} R = V{SQ} / R", [f"P = V I = I{SQ} R = V{SQ} / R"]),
    (f"Series: the same current flows through each resistor;  R = R{SUB1} + R{SUB2} + R{SUB3}",
     [f"R = R{SUB1} + R{SUB2} + R{SUB3}"]),
    ("Current is the rate of flow of electric charge:  I = Q / t", ["I = Q / t"]),
    (f"I = V / R = 12 V {DIV} 4 {OHM} = 3 A", ["I = V / R"]),             # a worked example keeps only its formula
    ("Current:  I = V / R = 12 / 4 = 3 A", ["I = V / R"]),
    (f"Power:  P = V I = 12 {TIMES} 3 = 36 W", []),                      # "P = V I" has no operator to show
    ("I = 12 / 4 = 3 A", []),                                             # numbers only: not a formula
    ("1 kWh = 3.6 MJ: a 2 kW kettle used for 30 minutes uses 1 kWh", []),
    ("y = 2x + 3", ["y = 2x + 3"]),
    ("E = mc^2", ["E = mc^2"]),
    ("v = u + a t", ["v = u + a t"]),
    ("Speed = distance / time", ["Speed = distance / time"]),
    (f"F = m {TIMES} a", [f"F = m {TIMES} a"]),
    ("Acceleration:  a = (v - u) / t", ["a = (v - u) / t"]),
    ("units in m\na = F / m", ["a = F / m"]),                           # the line before doesn't count
]

# slide text → the (term, meaning) pairs it must give
DEFINITIONS = [
    ("An ammeter measures current and is always connected in series", []),
    (f"Resistance is measured in ohms ({OHM})", [("Resistance", f"measured in ohms ({OHM})")]),
    ("Current is the rate of flow of electric charge:  I = Q / t",
     [("Current", "rate of flow of electric charge: I = Q / t")]),
]


def main() -> int:
    bad = 0
    for text, want in FORMULAS:
        got = Q.formula_lines(text)
        if got != want:
            bad += 1
            print(f"FORMULA  {text!r}\n   want {want}\n    got {got}")
    for text, want in DEFINITIONS:
        got = Q.definition_pairs(text)
        if got != want:
            bad += 1
            print(f"DEFINITION  {text!r}\n   want {want}\n    got {got}")
    total = len(FORMULAS) + len(DEFINITIONS)
    print(f"crib sheet: {total - bad}/{total} right")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
