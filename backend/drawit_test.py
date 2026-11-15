"""Checks for Draw it (backend/drawit.py) — no brain needed: the maths reader, its safety, the exact graph, and every
kind of drawing from a hand-written plan.

    python -m backend.drawit_test
"""
import math
import sys
import xml.etree.ElementTree as ET

from backend import drawit as D

VALUES = [   # (function, x, f(x))
    ("x^2 - 4", 3, 5), ("2x+1", 2, 5), ("sin(pi/2)", 0, 1), ("-x^2", 2, -4), ("2^-1", 0, 0.5), ("√(x)", 9, 3),
    ("3x²", 2, 12), ("|x-2|", 0, 2), ("(x+1)(x-1)", 3, 8), ("2 sin x", math.pi / 2, 2), ("e^0", 5, 1),
    ("x^2^3", 1.1, 1.1 ** 8), ("10 ÷ 4 × x", 2, 5), ("ln(e^2)", 0, 2), ("log(1000)", 0, 3),
]
UNSAFE = ['__import__("os")', "x.real", "open(1)", "exec(x)", "().__class__", "lambda x: x"]

PLANS = {
    "graph": {"title": "v against t", "functions": [{"expr": "2 + 3*x", "label": "v = 2 + 3t"}], "x_from": 0, "x_to": 10,
              "x_label": "t (s)", "y_label": "v (m/s)"},
    "steps": {"title": "Making tea", "steps": [{"label": "Boil water", "note": "100 °C at sea level"},
                                              {"label": "Add the **tea**", "note": ""}, {"label": "Wait", "note": "3 min"}]},
    "cycle": {"title": "Water cycle", "stages": [{"label": "Evaporation", "note": "Sun heats water"},
                                                 {"label": "Condensation", "note": ""}, {"label": "Precipitation", "note": ""},
                                                 {"label": "Collection", "note": "Rivers and seas"}]},
    "mindmap": {"title": "Rocks", "center": "Rocks", "branches": [{"label": "Igneous", "points": ["Granite"]},
                                                                  {"label": "Sedimentary", "points": []},
                                                                  {"label": "Metamorphic", "points": ["Marble", "Slate"]}]},
    "bars": {"title": "Marks", "unit": "%", "bars": [{"label": "Maths", "value": 78}, {"label": "Physics", "value": -4}]},
    "timeline": {"title": "Ghana", "events": [{"when": "1949", "label": "The CPP is formed"},
                                              {"when": "1957", "label": "Independence"}]},
    "circuit": {"title": "Series", "layout": "series", "supply": "battery", "supply_label": "12 V",
                "parts": [{"type": "resistor", "label": "4 Ω"}, {"type": "lamp", "label": ""}, {"type": "ammeter", "label": ""}],
                "voltmeter_across": 2, "main_ammeter": False},
}


def good_svg(svg: str) -> bool:
    try:
        ET.fromstring(svg)
    except ET.ParseError:
        return False
    return "nan" not in svg.lower() and "inf" not in svg.lower().replace("info", "")


def main() -> int:
    bad = total = 0

    def check(ok, what):
        nonlocal bad, total
        total += 1
        if not ok:
            bad += 1
            print("FAIL ", what)

    for text, x, want in VALUES:
        got = D.Function(text, "x")(x)
        check(math.isclose(got, want, rel_tol=1e-9, abs_tol=1e-9), f"{text} at {x}: {got} != {want}")
    check(math.isnan(D.Function("1/x")(0)) and math.isnan(D.Function("sqrt(x)")(-1)), "1/0 and √−1 are no value")
    for text in UNSAFE:
        try:
            D.Function(text, "x")
            check(False, f"unsafe accepted: {text}")
        except D.DrawError:
            check(True, "")
    g = D.direct_graph("/draw y = x^2 - 4 from -3 to 3")
    check(g and g["kind"] == "graph" and "x = −2 and 2" in g["caption"] and "y = −4" in g["caption"]
          and good_svg(g["svg"]), f"direct graph: {g and g['caption']}")
    g = D.direct_graph("plot v = 2 + 3t for t = 0 to 10")
    check(g and g["title"] == "v = 2 + 3t" and good_svg(g["svg"]), f"v against t: {g and g['title']}")
    check(D.direct_graph("draw the water cycle") is None and D.direct_graph("y = mx + c") is None,
          "a request that isn't an equation goes to the brain")
    g = D.direct_graph("y = tan(x) from -3 to 3")
    check(g and good_svg(g["svg"]) and "x = 0." in g["caption"], f"tan x: {g and g['caption']}")
    for kind, plan in PLANS.items():
        try:
            r = D.render(kind, plan)
            check(r["kind"] == kind and good_svg(r["svg"]), f"{kind}: bad svg")
            check("**" not in r["svg"], f"{kind}: markdown left in a label")
        except Exception as e:
            check(False, f"{kind}: {e}")
    try:
        D.render("bars", {"title": "x", "unit": "", "bars": [{"label": "a", "value": "lots"}]})
        check(False, "bars without numbers should be refused")
    except D.DrawError:
        check(True, "")
    par = dict(PLANS["circuit"], layout="parallel", main_ammeter=True)
    check(good_svg(D.render("circuit", par)["svg"]), "parallel circuit")
    check(D.hint("draw the water cycle") == "cycle" and D.hint("a series circuit") == "circuit"
          and D.hint("parts of a cell") == "mindmap" and D.hint("explain Ohm's law") is None, "kind hints")
    check(D._clean("**Evaporation** of $H_2O$", 40) == "Evaporation of H2O", D._clean("**Evaporation** of $H_2O$", 40))
    print(f"drawit_test: {total - bad}/{total} right")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
