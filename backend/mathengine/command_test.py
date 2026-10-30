"""/CUSTOM-Mx's promises, checked: exact answers for exact commands, a refusal (with the reason) for anything
unclear, and the same output every time.

    python -m backend.mathengine.command_test
"""
import re
import sys
import time

from . import command as C

# command → the answer it must give, or None: it must refuse (and the refusal must mention the word given)
CASES = [
    ("find s given u = 0 m/s, v = 20 m/s, t = 5 s", "s = 50 m"),
    ("find s given u = 0, v = 20 m/s, t = 5 s", "s = 50 m"),
    ("find power given voltage = 240 V, current = 5 A", "1200 W"),
    ("find power given V = 240 V, R = 60 Ω", "P = 960 W"),
    ("find current given V = 12 V, R = 4 Ω then find power", "P = 36 W"),
    ("find v in km/h given u = 0, a = 2 m/s^2, t = 5 s", "v = 36 km/h"),
    ("find final speed given u = 0, a = 2 m/s^2, t = 5 s", "v = 10 m/s"),
    ("find force given m = 5 kg, a = 2 m/s^2", "F = 10 N"),
    ("calculate the force if the mass is 5 kg and the acceleration is 2 m/s^2", "F = 10 N"),
    ("what is the kinetic energy of the ball if mass is 0.5 kg and speed is 4 m/s", "4 J"),
    ("find kinetic energy given mass = 2 kg, speed = 3 m/s", "9 J"),
    ("find speed given distance = 100 m, time = 20 s", "v = 5 m/s"),
    ("find speed of the echo given distance = 100 m, time = 20 s", "v = 10 m/s"),
    ("find rotor speed given poles = 4, frequency = 50 Hz, slip = 4 %", "nr = 1440 rpm"),
    ("find synchronous speed given f = 50 Hz, p = 4", "ns = 1500 rpm"),
    ("find slip given ns = 1500 rpm, nr = 1440 rpm", "s = 4 %"),
    ("find height given u = 20 m/s, v = 0 m/s, g = 9.8 m/s^2", "h = 20.41 m"),
    ("find efficiency given output power = 800 W, input power = 1000 W", "η = 80 %"),
    ("find pressure given force = 600 N, area = 0.02 m^2", "30000 Pa"),
    ("find wavelength given frequency = 500 Hz, wave speed = 340 m/s", "0.68 m"),
    ("find resistance given resistivity = 1.7e-8 Ω m, length = 100 m, area = 1 mm^2", "R = 1.7 Ω"),
    ("solve 2x + 5 = 17", "x = 6"),
    ('rearrange "v = u + a*t" for t', "t = (-u + v) / a"),
    ('rearrange "Ohm\'s law" for R', "R = V / I"),
    ('substitute u = 0, a = 2, t = 5 into "v = u + a*t"', "v = 10"),
    ("convert 100 km/h to m/s", "27.7778 m/s"),
    ("convert 25 °C to K", "298.15 K"),
    # refusals: never a guess
    ("find speed given u = 0, a = 2 m/s^2, t = 5 s", None, "final speed"),              # initial or final?
    ("find rotor speed given poles = 4, frequency = 50 Hz", None, "slip"),               # not the synchronous speed
    ("find resistance given R1 = 4 Ω, R2 = 6 Ω", None, "parallel"),                       # series or parallel?
    ("find power given V = 240 V, I = 5 A, t = 10 s", None, "t = 10 s"),                 # a value it would ignore
    ("find force given mass = 5 m/s", None, "kg"),                                       # wrong unit
    ("find wobble given mass = 2 kg", None, "wobble"),                                   # unknown name
    ("find speed given mass = 2 kg", None, "Formulas that find it"),                     # not enough
    ("find force given m = 5 kg, a = 2", None, "a = 2"),                                 # a needs a unit
    ("tell me a joke", None, "help"),
]


def main():
    t0 = time.time()
    bad = 0
    for case in CASES:
        cmd, want = case[0], case[1]
        r1, r2 = C.run(cmd), C.run(cmd)
        md = r1["markdown"]
        if r1 != r2:
            bad += 1
            print(f"NOT DETERMINISTIC: {cmd}")
            continue
        if want is not None:
            ok = r1["ok"] and want in md
        else:
            ok = not r1["ok"] and case[2].lower() in md.lower()
        if not ok:
            bad += 1
            print(f"FAIL: {cmd}\n   wanted {'answer ' + repr(want) if want else 'a refusal about ' + repr(case[2])}\n   got: "
                  + md.replace("\n", " | ")[:300])
    for question, want in DRAFTS:                    # "Make it exact": the draft must run to the right answer
        d = C.draft(question)
        r = C.run(d["command"]) if d else {"ok": False, "values": []}
        if not (d and r["ok"] and r["values"] and abs(r["values"][0] - want) <= 1e-6 * abs(want)):
            bad += 1
            print(f"DRAFT FAIL: {question}\n   draft: {d and d['command']}\n   got: {r.get('values')}")
    total = len(CASES) + len(DRAFTS)
    print(f"{total - bad}/{total} as promised ({time.time() - t0:.1f}s)")
    return bad


# question in everyday words → the SI answer its drafted command must give
DRAFTS = [
    ("A car accelerates from rest to 20 m/s in 5 s. How far does it travel?", 50.0),
    ("Calculate the escape velocity from a planet of mass 6 × 10^24 kg and radius 6.4 × 10^6 m.", 11186.48738434009),
    ("How much heat is needed to warm 2 kg of water from 20 °C to 80 °C? (c = 4200 J/kg K)", 504000.0),
    ("A 4-pole, 50 Hz induction motor has a slip of 4%. Find the rotor speed.", 24.0),
    ("Two resistors of 4 Ω and 6 Ω are connected in series. Find the total resistance.", 10.0),
]


if __name__ == "__main__":
    sys.exit(1 if main() else 0)
