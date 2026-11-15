"""Checks for Imagine (backend/imagine.py). Without the picture model: the safety rules, the painter's words, the
brain's schema as a grammar, and the refusals before anything runs. With LUNAR_IMAGINE_MODEL pointing at the model
file (and the engine in runtime/sd.cpp), it also paints one picture.

    python -m backend.imagine_test
"""
import asyncio
import os
import sys
import tempfile

from backend import imagine as I
from backend import json_grammar

REFUSED = ["a naked woman", "NSFW anime girl", "a gory car crash with corpses", "people having sex",
           "someone self-harming", "a nazi rally with swastikas", "a woman in lingerie", "topless sunbathers"]
ALLOWED = ["sex cells in a flower", "red blood cells flowing in a vein", "rapeseed fields in spring", "the human heart",
           "a mother breastfeeding her baby", "Essex county", "the reproductive organs of plants", "a cocoa farm"]


def main() -> int:
    bad = total = 0

    def check(ok, what):
        nonlocal bad, total
        total += 1
        if not ok:
            bad += 1
            print("FAIL ", what)

    for t in REFUSED:
        check(I.unsuitable(t), f"should refuse: {t}")
    for t in ALLOWED:
        check(not I.unsuitable(t), f"should allow: {t}")
    p = I.compose("A farmer **harvesting** cocoa pods under tall trees.", "photo")
    check(p == "A farmer harvesting cocoa pods under tall trees, fully clothed in modest clothes, " + I.STYLES["photo"], p)
    p = I.compose("a lake in the mist", "nonsense")
    check(p.endswith(I.STYLES["digital art"]) and "clothed" not in p, p)
    check(I.compose("Gemma painting a lake", "photo").startswith("MrSOLIS painting"), "a real model's name is hidden")
    check(len(json_grammar.from_schema(I.SCHEMA)) > 100, "the brain's schema becomes a grammar")
    long = ("A low-angle close-up captures a lush cocoa tree swaying gently in heavy afternoon drizzle. The bark is "
            "dark and textured, splattered with fresh green raindrops that glisten under soft, diffused sunlight "
            "filtering through the canopy above. The ground below is a")
    s = I._sentence(long + " " + long)
    check(s == "A low-angle close-up captures a lush cocoa tree swaying gently in heavy afternoon drizzle. The bark is "
               "dark and textured, splattered with fresh green raindrops that glisten under soft, diffused sunlight "
               "filtering through the canopy above", s)
    coral = ("An underwater scene featuring a dense cluster of colorful corals branching out from a central lagoon, "
             "with small fish swimming among the structures, bathed in soft, dappled sunlight filtering down from the "
             "bright surface far above the quiet reef on a calm and clear summer morning")
    s = I._sentence(coral)
    check(s == "An underwater scene featuring a dense cluster of colorful corals branching out from a central lagoon",
          f"not inside an adjective list: {s!r}")
    for said, want in (("A single, transparent cross-section of a plant cell floating in clear liquid",
                        "A close-up of a plant cell floating in clear liquid"),
                       ("a labelled diagram of the heart with arrows showing blood flow", "A close-up of the heart"),
                       ("a volcano with clear labels for each part, at dusk", "A volcano, at dusk")):
        got = I.compose(said, "photo").replace(", " + I.STYLES["photo"], "")
        check(got == want, f"scrubbed: {got!r}")
    check(I._sentence("ripe yellow cocoa pods on a cocoa tree, morning light.") ==
          "ripe yellow cocoa pods on a cocoa tree, morning light.", "a short description stays whole")

    # refusals before the engine or the brain is touched: empty, unsuitable, no model
    real_dir = I.IMAGINE_DIR
    with tempfile.TemporaryDirectory() as tmp:
        I.IMAGINE_DIR = tmp
        try:
            for req, want in (("", "Say what to imagine"), ("a naked man", "suit a study app")):
                try:
                    asyncio.run(I.make(req))
                    check(False, f"make({req!r}) should be refused")
                except I.ImagineError as e:
                    check(want in str(e), f"make({req!r}): {e}")
            if I.engine_exe():
                try:
                    asyncio.run(I.make("a volcano at night"))
                    check(False, "no model: should ask for the download")
                except I.ImagineError as e:
                    check(str(e) == I.NOT_INSTALLED, f"no model: {e}")
            try:
                asyncio.run(I.again("a beach, topless"))
                check(False, "again() should refuse")
            except I.ImagineError as e:
                check("suit a study app" in str(e), str(e))
            check(I.status()["installed"] is False and I.status()["download_gb"] == 0.68, str(I.status()))
        finally:
            I.IMAGINE_DIR = real_dir

    model = os.environ.get("LUNAR_IMAGINE_MODEL")             # optional: paint one picture for real
    if model and os.path.isfile(model) and I.engine_exe():
        I.IMAGINE_DIR = os.path.dirname(model)
        I.MODEL["file"] = os.path.basename(model)
        png = I.paint(I.compose("a pyramid in the desert at sunset", "photo"), 7)
        check(png[:8] == b"\x89PNG\r\n\x1a\n" and len(png) > 50_000, "a real picture")
        print(f"painted in {I.LAST['seconds']} s")
    print(f"imagine_test: {total - bad}/{total} right")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
