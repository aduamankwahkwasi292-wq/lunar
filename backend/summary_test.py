"""Checks for /summarize's code (backend/summary.py) — no brain needed. Replaced crib_test (2026-11-14).

    python -m backend.summary_test
"""
import os
import sys
import tempfile

from backend import summary as S

MATHS = [   # what a brain writes -> what the Word file shows
    (r"$\frac{V}{R}$", "V/R"),
    (r"$R_{1} + R_{2}$", "R1 + R2"),
    (r"$P = I^{2} R$", "P = I^2 R"),
    (r"\(\frac{1}{R_1} + \frac{1}{R_2}\)", "1/R1 + 1/R2"),
    (r"$\text{V} = \text{I} \times \text{R}$", "V = I × R"),
    (r"$\frac{a+b}{c}$", "(a+b)/c"),
    (r"$\sqrt{x^2 + y^2}$", "√(x^2 + y^2)"),
    (r"$10\,\Omega$", "10 Ω"),
    (r"an angle of $30^\circ$", "an angle of 30°"),
    (r"$$E = \frac{1}{2} L I^2$$", "E = 1/2 L I^2"),
    ("It costs $5 and $10 a month.", "It costs $5 and $10 a month."),       # money stays money
    ("V = I × R, nothing to change", "V = I × R, nothing to change"),
]

CLEAN = [
    ("Here is a summary of slide 3:\n* Current is the flow of charge.\n* Unit: ampere (A).",
     "- Current is the flow of charge.\n- Unit: ampere (A)."),
    ("1. First point\n2) Second point", "- First point\n- Second point"),
    ("## Key ideas\n- **Ohm's law**: $V = IR$", "Key ideas\n- **Ohm's law**: V = IR"),
    ("- I am Gemma, made by Google DeepMind.", "- I am MrSOLIS, made by Google MrSOLIS."),
    ("---\n- One\n\n\n- Two", "- One\n- Two"),
]

WORTH = [   # (slide text, slide number, has a picture) -> summarise it?
    ("Electric Circuits\nCurrent, voltage and resistance", 1, False, False),       # title slide
    ("Thank you", 12, False, False),                                              # closing slide
    ("Outline\nCurrent\nVoltage\nResistance", 2, False, False),                   # outline slide
    ("Ohm's law\nThe current through a conductor is proportional to the voltage across it: V = I R.", 3, False, True),
    ("", 4, True, True),                                                          # a picture-only slide, brain sees
    ("", 5, False, False),                                                        # blank
]


def main() -> int:
    bad = 0
    for raw, want in MATHS:
        got = S.plain_maths(raw)
        if got != want:
            bad += 1
            print(f"MATHS  {raw!r}\n   got  {got!r}\n   want {want!r}")
    for raw, want in CLEAN:
        got = S.clean(raw)
        if got != want:
            bad += 1
            print(f"CLEAN  {raw!r}\n   got  {got!r}\n   want {want!r}")
    for text, n, pic, want in WORTH:
        got = S.worth_summarising(text, n, picture=pic)
        if got != want:
            bad += 1
            print(f"WORTH  slide {n} {text[:40]!r}: got {got}, want {want}")
    if S.slide_title("• Ohm's law\nV = I R") != "Ohm's law" or S.slide_title("") != "":
        bad += 1
        print("TITLE  wrong")
    if S.file_name("EE 172: Circuits.pdf") != "EE 172 Circuits - summary.pdf":
        bad += 1
        print("NAME  ", S.file_name("EE 172: Circuits.pdf"))

    with tempfile.TemporaryDirectory() as d:
        c = S.Cache(os.path.join(d, "deck"))
        k = S.Cache.key(2, "V = I R", "qwen3.5-2b", False)
        c.put(k, "- One point")
        if S.Cache(os.path.join(d, "deck")).get(k) != "- One point" or S.Cache.key(2, "V = I R", "gemma4-e4b", False) == k:
            bad += 1
            print("CACHE  wrong")
        import pypdfium2 as pdfium
        long = "\n".join(f"- Point {i}: the current I = V / R through R₁ → stays the same in series." for i in range(40))
        path = S.build_pdf(os.path.join(d, "out", "x.pdf"), "Circuits",
                           [(3, "Ohm's law", "- **V = I × R** links them.\n- Unit of R: ohm (Ω)."),
                            (5, "", "A plain sentence."), (6, "Many points", long)])
        doc = pdfium.PdfDocument(path)
        text = "\n".join(doc[i].get_textpage().get_text_range() for i in range(len(doc)))
        pages = len(doc)
        doc.close()
        want = ["Circuits — Summary", "Slide 3: Ohm's law", "V = I × R links them.", "Unit of R: ohm (Ω).",
                "Slide 5", "A plain sentence.", "R₁ -> stays", f"page 1 of {pages}", f"page {pages} of {pages}"]
        missing = [w for w in want if w not in text.replace("\r", "")]
        if pages < 2 or missing or os.path.getsize(path) > 800_000:
            bad += 1
            print("PDF   pages", pages, "missing", missing, "bytes", os.path.getsize(path))

    total = len(MATHS) + len(CLEAN) + len(WORTH) + 4
    print(f"summary_test: {total - bad}/{total} right")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
