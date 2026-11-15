"""Imagine (/imagine): a picture of an idea, painted on this computer by a small picture model.

The user asked for it on 2026-11-14, right after Draw it ("LET'S DO Imagine NOW"): students see a picture of a concept.
The brain writes what the picture shows — one concrete scene, from the student's words and the slide they're on — and a
one-step picture model paints it: SDXS-512 (distilled from DreamShaper by IDKiro et al., OpenRAIL++), a Q8_0 GGUF run by
stable-diffusion.cpp's sd-cli. Without a brain the student's own words are painted. Optional: one download of 0.68 GB
from Settings → Imagine.

Measured 2026-11-14 on the i5-13420H, CPU only, 512 x 512: about 6–7 s a picture (load 0.6 s, words 0.3 s, one step
3.0 s, decode 2.3 s with 8 threads; 6 threads 0.5 s slower, 12 no faster, flash attention / direct conv no help).
Memory: 1.2 GB working set at the peak, of which only 0.83 GB is the engine's own with --mmap (1.48 GB without — the
mapped model file can be dropped by Windows instead of paged out); all of it goes back when sd-cli closes, once a picture.

What it's good and bad at (same test, 24 pictures): places, landscapes, objects, animals, people and scenes from history
look good; inner structures — a cell, an organ, a cut-away volcano — come out as pretty guesses (a heart becomes a
valentine), "cut in half" splits the picture into panels, and it can't write (labels turn into scribbles). So the brain
never asks for words, labels, diagrams or cut-aways, and the card says the picture is for imagining, not for facts —
exact diagrams are Draw it's job (drawit.py).

Safety (a study app for students): requests for sexual content, nudity, gore, self-harm or hate are refused by rules
before the brain sees them (and its description is checked again), the brain can refuse too, and people are always
asked for fully clothed. The model was distilled from an SD 1.5 model, which can paint nudity — these rules are the guard.
"""
import asyncio
import base64
import ctypes
import json
import os
import random
import re
import subprocess
import sys
import tempfile
import threading
import time

import httpx

from backend import brain, classroom
from backend.local_llm import MODEL_DIR
from backend.summary import plain_text

# The picture model: one pinned revision of its repo, checked by SHA-256 before it is ever used (as the brains are).
MODEL = {
    "repo": "concedo/sdxs-512-tinySDdistilled-GGUF",
    "revision": "3144d898d61492f8382ffcabec055733fc5b2a0e",
    "file": "sdxs-512-tinySDdistilled_Q8_0.gguf",
    "bytes": 682847200,
    "sha256": "409ab23582ee074c6b9d5395784fc0741b0599fb9d138686c69087c71678eb6a",
}
IMAGINE_DIR = os.path.join(brain.DATA_DIR, "imagine")
SIZE = 512                       # the model's own size; it paints nothing better at other sizes
STYLES = {                       # the brain picks one; these words suit the model (the style test, 2026-11-14)
    "photo": "realistic photo, natural light, sharp focus, highly detailed",
    "3d model": "3d render, soft studio lighting, highly detailed",
    "digital art": "digital art, highly detailed, vibrant colours, sharp focus",
}
CAPTION = ("Imagined by MrSOLIS to help you picture it — not a diagram: shapes, parts and colours can be wrong, so "
           "check the details in your notes. For an exact diagram, type /draw.")
NOT_INSTALLED = "Imagine needs its picture model first — get it once in Settings → Imagine (0.68 GB)."
REFUSE = ("MrSOLIS only imagines pictures that suit a study app. Try an idea from your lessons — "
          "like /imagine a cocoa farm in the rainy season.")


class ImagineError(ValueError):
    """Something the student should read: no model, refused, no memory, the engine failed."""


# ══════════════════════════════════════════════════════════════════════
#   the engine and the model file
# ══════════════════════════════════════════════════════════════════════
def engine_exe():
    """sd-cli: LUNAR_SD_CLI, else the pinned build beside the AI engine (runtime/sd.cpp, scripts/fetch_runtime.py)."""
    env = os.environ.get("LUNAR_SD_CLI")
    if env and os.path.isfile(env):
        return env
    name = "sd-cli.exe" if sys.platform == "win32" else "sd-cli"
    base = os.path.dirname(MODEL_DIR)
    for d in (os.path.join(base, "runtime", "sd.cpp"), os.path.join(base, "sd.cpp")):
        p = os.path.join(d, name)
        if os.path.isfile(p):
            return p
    return None


def model_path() -> str:
    return os.path.join(IMAGINE_DIR, MODEL["file"])


def installed() -> bool:
    p = model_path()
    return os.path.isfile(p) and os.path.getsize(p) == MODEL["bytes"]


DOWNLOAD = {"state": "idle", "done": 0, "total": MODEL["bytes"], "error": "", "cancel": False}
LAST = {"seconds": None}         # how long the last picture took here (shown on the Settings card)


def _download():
    os.makedirs(IMAGINE_DIR, exist_ok=True)
    final, size = model_path(), MODEL["bytes"]
    part = final + ".part"
    url = f"{brain.HF}/{MODEL['repo']}/resolve/{MODEL['revision']}/{MODEL['file']}"
    DOWNLOAD.update(state="downloading", done=0, total=size, error="", cancel=False)
    try:
        # Students' connections drop: carry on from where it stopped, a few times with growing pauses (as brains do).
        for attempt in range(6):
            have = os.path.getsize(part) if os.path.isfile(part) else 0
            DOWNLOAD["done"] = have
            if have >= size:
                break
            headers = {"Range": f"bytes={have}-"} if have else {}
            try:
                with httpx.Client(follow_redirects=True, timeout=httpx.Timeout(60, read=120)) as c:
                    with c.stream("GET", url, headers=headers) as r:
                        if r.status_code == 200 and have:           # the server ignored Range: start over
                            have = 0
                        r.raise_for_status()
                        with open(part, "ab" if have else "wb") as f:
                            for chunk in r.iter_bytes(1 << 20):
                                if DOWNLOAD["cancel"]:
                                    DOWNLOAD.update(state="cancelled")
                                    return
                                f.write(chunk)
                                have += len(chunk)
                                DOWNLOAD["done"] = have
                break
            except httpx.TransportError:
                if attempt == 5 or DOWNLOAD["cancel"]:
                    raise
                time.sleep(min(30, 3 * 2 ** attempt))               # 3, 6, 12, 24, 30 s
        if os.path.getsize(part) != size:
            if os.path.getsize(part) > size:
                os.remove(part)
            DOWNLOAD.update(state="error", error="the file came down incomplete")
            return
        if brain._sha256(part) != MODEL["sha256"]:
            os.remove(part)
            DOWNLOAD.update(state="error", error="the file came down damaged, so MrSOLIS threw it away")
            return
        os.replace(part, final)
        DOWNLOAD.update(state="done", done=size)
    except httpx.HTTPStatusError as e:                              # never show the URL: it names the model
        DOWNLOAD.update(state="error", error=f"the download server said {e.response.status_code}")
    except httpx.TransportError:
        DOWNLOAD.update(state="error", error="the connection dropped")
    except OSError:
        DOWNLOAD.update(state="error", error="this computer couldn't save the file (is the disk full?)")
    except Exception:
        DOWNLOAD.update(state="error", error="something went wrong")


def start_download() -> bool:
    if DOWNLOAD["state"] == "downloading" or installed():
        return False
    threading.Thread(target=_download, daemon=True, name="imagine-download").start()
    return True


def cancel():
    DOWNLOAD["cancel"] = True


def remove():
    """Delete the picture model (blocking: waits for a picture being painted)."""
    with _PAINTING:
        for p in (model_path(), model_path() + ".part"):
            try:
                os.remove(p)
            except OSError:
                pass
    DOWNLOAD.update(state="idle", done=0, error="")


def status() -> dict:
    return {"installed": installed(), "engine": bool(engine_exe()), "download_gb": round(MODEL["bytes"] / 1e9, 2),
            "seconds": LAST["seconds"], "download": {k: v for k, v in DOWNLOAD.items() if k != "cancel"}}


# ══════════════════════════════════════════════════════════════════════
#   what may be painted
# ══════════════════════════════════════════════════════════════════════
_UNSUITABLE = re.compile(
    r"\b(nud(?:e|es|ity)|naked|nsfw|sex(?!\s*-?\s*(?:cells?|chromosomes?|linked|hormones?|organs?\s+of\s+plants))|"
    r"sexy|sexual\w*|porn\w*|erotic\w*|hentai|lingerie|underwear|bikinis?|topless|breasts?|nipples?|genital\w*|"
    r"penis\w*|vagina\w*|buttocks|gore|gory|bloody|corpses?|dead\s+bod(?:y|ies)|decapitat\w*|behead\w*|"
    r"dismember\w*|mutilat\w*|suicid\w*|self[\s-]?harm\w*|torture\w*|rap(?:e|ed|ing)|molest\w*|swastikas?|nazis?|kkk)\b",
    re.I)
_PEOPLE = re.compile(
    r"\b(person|people|man|men|woman|women|boys?|girls?|child|children|kids?|bab(?:y|ies)|students?|teachers?|"
    r"farmers?|workers?|doctors?|nurses?|scientists?|soldiers?|kings?|queens?|chiefs?|athletes?|runners?|swimmers?|"
    r"family|crowd|humans?|someone|traders?|fishermen|players?|leaders?|dancers?|drummers?|villagers?)\b", re.I)


def unsuitable(text: str) -> bool:
    return bool(_UNSUITABLE.search(text or ""))


def _clean(s, limit: int) -> str:
    s = classroom._HIDE.sub("MrSOLIS", plain_text(str(s or "")))
    s = re.sub(r"\s+", " ", s.replace("#", "")).strip(" \"'“”‘’-–•*")
    return s if len(s) <= limit else s[:limit - 1].rstrip(" ,.;") + "…"


# What the painter can't do, said anyway by a small brain (Middler wrote "a cross-section of a plant cell" against the
# instructions): asked for as something it can paint, or dropped.
_SCRUB = [
    (re.compile(r"\b(?:labell?ed|annotated|captioned)\s+", re.I), ""),
    (re.compile(r"\b(?:a\s+|an\s+|the\s+)?(?:single,?\s+)?(?:transparent,?\s+)?(?:cross[\s-]?sections?|cut[\s-]?aways?|"
                r"cutaway\s+views?|diagrams?|infographics?|charts?|schematics?)\s+(?:showing|of)\s+", re.I), "a close-up of "),
    (re.compile(r",?\s*\b(?:with|and|showing)\s+(?:clear\s+|neat\s+|small\s+)?(?:labels?|text|words|captions?|arrows?|"
                r"numbers?|letters?)\b[^,.;]*", re.I), ""),
]


def compose(picture: str, style: str) -> str:
    """The words the painter gets: the scene, people fully clothed, then the style's words."""
    picture = _clean(picture, 300).rstrip(" .…")
    for rx, to in _SCRUB:
        picture = rx.sub(to, picture)
    picture = re.sub(r"\s+", " ", picture).strip(" ,")
    picture = picture[:1].upper() + picture[1:]
    if _PEOPLE.search(picture):          # "fully clothed" alone still gave a dancer a crop top (2026-11-14)
        picture += ", fully clothed in modest clothes"
    return f"{picture}, {STYLES.get(style, STYLES['digital art'])}"


# ══════════════════════════════════════════════════════════════════════
#   the brain describes the picture
# ══════════════════════════════════════════════════════════════════════
# Tuned on Middler, 2026-11-14: long descriptions ran past the field and were cut mid-word (and past the painter's
# 77-token reading window, which drops the style words at the end); a cocoa farm became "bark and raindrops" with no
# pods; "No trees are visible" painted trees; an "ok" flag refused a plain "what this slide is about". So: the main
# subject first in everyday words, one short sentence, only what IS there, and a flag that is true only when unsuitable.
# A single example ("ripe cocoa pods…") leaked: "Ghana's independence in 1957" became a cocoa tree. Two pairs that
# show the change from request to caption, on topics far from a student's usual ones, leak less.
_SYSTEM = (
    "You write the description of a picture for a small painting model. MrSOLIS, a study app, shows the picture to "
    "help a student imagine an idea from their lessons. Picture exactly what the student asked about. Write it like a "
    "short caption: the main subject first, in plain everyday words a painter knows, then where it is, then the light "
    "— ONE sentence of 12 to 25 words. Two examples of the change: \"a Viking voyage\" -> \"a wooden longship with a "
    "striped sail crossing a stormy grey sea, men rowing, cold morning light\"; \"how glaciers shape valleys\" -> \"a "
    "huge white glacier filling a wide U-shaped mountain valley, rocks along its edges, bright sunlight\". "
    "Say only what is in the picture, never what isn't. The "
    "painter cannot write or draw diagrams, so never ask for words, letters, labels, numbers, arrows, charts, diagrams, "
    "cut-aways, cross-sections or things cut in half. Never name a real person — describe them instead (\"a leader "
    "speaking to a cheering crowd\"). When the student means the slide (\"this\", \"this slide\"), picture the slide's "
    "topic. Style: photo for real places, plants, animals and people; 3d model for one object on its own (an organ, a "
    "machine, a molecule, a fossil); digital art for what nobody can photograph (space, the far past, the very small). "
    "Set unsuitable to true only for sexual content, nudity, gore, cruelty, hate or self-harm.")
SCHEMA = {"type": "object", "additionalProperties": False,
          "properties": {"title": {"type": "string", "maxLength": 60},
                         "picture": {"type": "string", "maxLength": 260},
                         "style": {"type": "string", "enum": list(STYLES)},
                         "unsuitable": {"type": "boolean"}},
          "required": ["title", "picture", "style", "unsuitable"]}
_WORDS = 40                      # the description's words at most (it is asked for 12–25)


def _sentence(text: str) -> str:
    """The brain's description, cut back to a clause if it ran long (past _WORDS words, or into the field's end, where
    its last word may be cut) — never mid-word, and not inside a list of adjectives ("bathed in soft, dappled light"
    cut at its comma left "bathed in soft")."""
    words = text.split()
    capped = len(text) >= 250
    if len(words) <= _WORDS and not capped:
        return text.rstrip(" ,;:")
    cut = " ".join(words[:min(len(words) - (1 if capped else 0), _WORDS)])
    for sep in (". ", "; ", ", with ", ", and ", ", while ", ", where ", ", as "):   # a sentence, else a clause
        stop = cut.rfind(sep)
        if stop > len(cut) // 3:
            return cut[:stop].rstrip(" ,;:.")
    return cut.rstrip(" ,;:.")


async def _describe(request: str, slide: str, slide_no: int, total: int) -> dict:
    ctx = (f"Slide {slide_no} of {total}:\n\"\"\"\n{classroom._slide(slide)}\n\"\"\"\n\n" if slide.strip() else "")
    messages = [{"role": "system", "content": _SYSTEM},
                {"role": "user", "content": f"{ctx}The student asked to imagine: \"{request[:300]}\"\n\n"
                                            "Write the title (a few words) and the picture's description."}]
    raw = await brain.chat(messages, temperature=0.4, max_tokens=220, schema=SCHEMA)
    try:
        data = json.loads(raw)
    except Exception:
        data = None
    if not isinstance(data, dict):
        raise ImagineError("MrSOLIS couldn't describe that picture. Try asking for it in other words.")
    return data


# ══════════════════════════════════════════════════════════════════════
#   painting
# ══════════════════════════════════════════════════════════════════════
_PAINTING = threading.Lock()     # one picture at a time: two would only share the processor and both be slow


def _threads() -> int:
    env = os.environ.get("LUNAR_SD_THREADS")
    if env and env.isdigit():
        return int(env)
    return max(2, min(8, (os.cpu_count() or 4) * 2 // 3))           # 12 logical -> 8, the fastest here


def _free_gb() -> float:
    """Physical memory free now (Windows); elsewhere assume enough."""
    if sys.platform != "win32":
        return 99.0

    class MS(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong)] + [
            (n, ctypes.c_ulonglong) for n in ("total", "avail", "tpage", "apage", "tvirt", "avirt", "aext")]
    m = MS()
    m.dwLength = ctypes.sizeof(m)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
        return 99.0
    return m.avail / 2 ** 30


def paint(prompt: str, seed: int) -> bytes:
    """One 512 x 512 picture as PNG bytes (blocking — run it in a thread). Raises ImagineError."""
    exe = engine_exe()
    if not exe:
        raise ImagineError("The picture engine is missing from this install — reinstall MrSOLIS to get it back.")
    if not installed():
        raise ImagineError(NOT_INSTALLED)
    if _free_gb() < 0.9:
        raise ImagineError("This computer is short of free memory for a picture (it needs about 1 GB). Close a few "
                           "programs, or switch to a smaller brain in Settings, then try again.")
    with _PAINTING, tempfile.TemporaryDirectory(prefix="mrsolis-imagine-") as tmp:
        words, out = os.path.join(tmp, "prompt.txt"), os.path.join(tmp, "picture.png")
        with open(words, "w", encoding="utf-8") as f:                # a file: no quoting trouble on a command line
            f.write(prompt)
        args = [exe, "-m", model_path(), "--prompt-file", words, "-W", str(SIZE), "-H", str(SIZE), "--steps", "1",
                "--cfg-scale", "1", "-s", str(seed), "-t", str(_threads()), "--mmap", "-o", out]
        t = time.time()
        proc = subprocess.Popen(args, cwd=os.path.dirname(exe), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, creationflags=0x08000000 if sys.platform == "win32" else 0)
        job = brain._bind_to_us(proc)                                # dies with the backend; no EcoQoS slow-down
        try:
            log = proc.communicate(timeout=240)[0].decode("utf-8", "replace")
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            raise ImagineError("The picture took too long. Close a few programs and try again.")
        finally:
            if job:
                ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(job))
        if proc.returncode != 0 or not os.path.isfile(out):
            tail = [ln for ln in log.splitlines() if "[E]" in ln or "error" in ln.lower()][-1:]
            raise ImagineError("The picture engine stopped" + (f": {tail[0][-160:]}" if tail else "") + ".")
        with open(out, "rb") as f:
            png = f.read()
        LAST["seconds"] = round(time.time() - t, 1)
        return png


def _result(title: str, picture: str, prompt: str, seed: int, png: bytes) -> dict:
    return {"title": title, "picture": picture, "prompt": prompt, "seed": seed, "caption": CAPTION,
            "image": base64.b64encode(png).decode("ascii"), "seconds": LAST["seconds"]}


async def make(request: str, slide: str = "", slide_no: int = 0, total: int = 0) -> dict:
    """{title, picture, prompt, seed, caption, image (base64 PNG)} — raises ImagineError, local_llm.LocalLLMError."""
    request = _clean(request, 300)
    if not request:
        raise ImagineError("Say what to imagine — e.g. /imagine a cocoa farm in the rainy season.")
    if unsuitable(request):
        raise ImagineError(REFUSE)
    if not engine_exe():
        raise ImagineError("The picture engine is missing from this install — reinstall MrSOLIS to get it back.")
    if not installed():
        raise ImagineError(NOT_INSTALLED)
    title, picture, style = request[:1].upper() + request[1:60], request, "digital art"
    if brain.active():
        d = await _describe(request, slide, slide_no, total)
        if d.get("unsuitable") is True:
            raise ImagineError(REFUSE)
        title = _clean(d.get("title"), 60) or title
        picture = _sentence(_clean(d.get("picture"), 300)) or picture
        style = d.get("style") if d.get("style") in STYLES else style
        if unsuitable(picture) or unsuitable(title):
            raise ImagineError(REFUSE)
    prompt = compose(picture, style)
    seed = random.randrange(1, 2 ** 31 - 1)
    png = await asyncio.to_thread(paint, prompt, seed)
    return _result(title, picture, prompt, seed, png)


async def again(prompt: str, title: str = "", picture: str = "") -> dict:
    """Try again: the same description, a new seed — no brain needed."""
    prompt = _clean(prompt, 400)
    if not prompt or unsuitable(prompt):
        raise ImagineError(REFUSE)
    seed = random.randrange(1, 2 ** 31 - 1)
    png = await asyncio.to_thread(paint, prompt, seed)
    return _result(_clean(title, 60) or "Imagined", _clean(picture, 300), prompt, seed, png)
