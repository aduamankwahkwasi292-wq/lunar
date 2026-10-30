import os
import re
import sys
import io
import time
import uuid
import hashlib
import json
import random
import shutil
import asyncio
import contextlib
import functools
from concurrent.futures import ThreadPoolExecutor

# Make the project root importable so `from backend.X import ...` works no
# matter where the server is launched from.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, UploadFile, File, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse, Response
from pydantic import BaseModel, Field

from backend.file_processor import extract_rich_slides, slide_plain_text
from backend import local_llm, classroom, file_processor, questions, voice, finder, brain, quizgen, mathengine, video
from backend import gate, guard
from backend.mathengine import command as mx_command
from backend.sqe import api as sqe
import numpy as np
from backend.library import Library

app = FastAPI(title="Lunar AI")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _bundle_dir() -> str:
    """Read-only resource root: the PyInstaller bundle when frozen, else the repo."""
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.normpath(os.path.join(BASE_DIR, ".."))


def _default_data_dir() -> str:
    """Writable per-user data dir for uploads/media/cache (never the bundle)."""
    if getattr(sys, "frozen", False):
        if sys.platform == "win32":
            base = os.environ.get("APPDATA") or os.path.expanduser("~")
        elif sys.platform == "darwin":
            base = os.path.expanduser("~/Library/Application Support")
        else:
            base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
        return os.path.join(base, "Lunar")
    return os.path.normpath(os.path.join(BASE_DIR, ".."))


BUNDLE_DIR = _bundle_dir()
# The desktop shell passes LUNAR_DATA_DIR (app userData); fall back sensibly.
DATA_DIR = os.environ.get("LUNAR_DATA_DIR") or _default_data_dir()
brain.DATA_DIR, brain.BRAIN_DIR = DATA_DIR, os.path.join(DATA_DIR, "brains")   # brains live with the student's data

# Only MrSOLIS's own windows on this computer, and (installed app) only with a licence: backend/guard.py. The old
# allow-every-website CORS rule is gone — the UI is served from here, so it never needed it.
app.add_middleware(guard.Guard, token=os.environ.get("LUNAR_TOKEN", ""),
                   licensed=not gate.required() or gate.licensed(DATA_DIR))
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
MEDIA_DIR = os.path.join(DATA_DIR, "uploads", "media")
# Slide embeddings for "Find anything" are cached on disk keyed by content hash so
# the same deck is only ever embedded once — instant search on every later open.
# Not "cache": on Windows that is the same folder as Electron's own browser "Cache".
STUDY_CACHE_DIR = os.path.join(DATA_DIR, "study-cache")
EMBED_CACHE_DIR = os.path.join(STUDY_CACHE_DIR, "embeds")
video.CACHE_DIR = os.path.join(STUDY_CACHE_DIR, "videos")      # prepared videos: frames + what is said
VIDEO_UPLOAD_DIR = os.path.join(UPLOAD_DIR, "videos")           # videos sent without a file path (browser dev)
FRONTEND_DIR = os.environ.get("LUNAR_FRONTEND_DIR") or os.path.join(BUNDLE_DIR, "frontend")
# Static assets (css/js/images) live in frontend/static/; HTML pages in frontend/.
STATIC_DIR = os.path.join(FRONTEND_DIR, "static")
if not os.path.isdir(STATIC_DIR):
    STATIC_DIR = FRONTEND_DIR          # fallback for the old flat layout
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(MEDIA_DIR, exist_ok=True)
os.makedirs(EMBED_CACHE_DIR, exist_ok=True)

# Uploaded documents, keyed by session id (= the deck's id in the library).
sessions = {}
# Everything that outlives a restart: decks, subjects, notes, quizzes, history, settings.
lib = Library(DATA_DIR)


def _get_session(session_id: str):
    """The deck's session — in memory, or reopened from the library after a restart."""
    session = sessions.get(session_id)
    if session:
        return session
    deck = lib.deck(session_id)
    if not deck or not os.path.isfile(deck.get("file_path") or ""):
        return None
    slides = lib.load_slides(session_id)
    if slides is None:                      # no cached copy: read the file again
        slides = extract_rich_slides(deck["file_path"], deck["media_dir"])
        lib.save_slides(session_id, slides)
    session = {
        "filename": deck["filename"],
        "file_path": deck["file_path"],
        "media_dir": deck["media_dir"],
        "text": "\n\n".join(slide_plain_text(s) for s in slides),
        "slides": slides,
        "slide_index": deck.get("last_slide", 0),
    }
    sessions[session_id] = session
    return session

_STREAM_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}

# Tracks whether an interactive LLM stream (lecture / chat / explain) is running,
# so background work (slide pre-render + embedding) can pause and not steal CPU.
_interactive_count = 0


@contextlib.asynccontextmanager
async def _interactive():
    global _interactive_count
    _interactive_count += 1
    try:
        yield
    finally:
        _interactive_count = max(0, _interactive_count - 1)


async def _wait_until_idle(poll: float = 0.4):
    while _interactive_count > 0:
        await asyncio.sleep(poll)


# ---- request models -------------------------------------------------
class ClassroomStartRequest(BaseModel):
    session_id: str


class TeachRequest(BaseModel):
    session_id: str
    slide_index: int = 0


class ClassroomChatRequest(BaseModel):
    session_id: str
    slide_index: int = 0
    message: str
    history: list[dict] = Field(default_factory=list)
    image: str | None = None            # a picture the student attached (data: URL), for a brain that sees
    video: str | None = None            # a video the student attached (its id from /api/video/prepare)


class SearchRequest(BaseModel):
    session_id: str
    query: str
    top_k: int = 6


class ExplainRequest(BaseModel):
    session_id: str
    slide_index: int = 0
    selection: str
    mode: str = "explain"          # "explain" | "solve"




def _slide_title(slide) -> str:
    """A short label for a slide (its title, or first meaningful line)."""
    if isinstance(slide, dict):
        if slide.get("title"):
            return str(slide["title"])[:48]
        text = slide.get("text", "")
    else:
        text = slide
    for line in (text or "").splitlines():
        line = line.strip()
        if len(line) >= 3:
            return line[:48]
    return "Slide"


def _slide_payload(session_id: str, slide, idx: int = 0) -> dict:
    """Board-ready view of a slide: a rendered page image, or ordered blocks."""
    if not isinstance(slide, dict):
        slide = {"blocks": [{"type": "text", "text": slide or ""}], "text": slide or "",
                 "links": [], "examinable": True}

    # PDF / image slides render the real page, in its own colours.
    if slide.get("board"):
        if slide.get("blank"):
            return {"title": _slide_title(slide), "blank": True, "examinable": False}
        grounding = (classroom.clean_board_text(slide.get("text", "")) + " " +
                     (slide.get("ocr", "") or "")).strip()
        return {
            "title": _slide_title(slide),
            "image": f"/api/classroom/slide_image/{session_id}/{idx}?look=colour",   # not a cached chalk image
            "links": slide.get("links", []),
            "examinable": bool(slide.get("examinable", True)) and bool(grounding),
        }

    blocks = []
    has_text = False
    for b in slide.get("blocks", []):
        b = dict(b)
        if b.get("type") == "text":
            # Skip reference/dedication parts; keep everything else verbatim.
            cleaned = classroom.clean_board_text(b.get("text", ""))
            if not cleaned.strip():
                continue
            b["text"] = cleaned
            has_text = True
        elif b.get("type") in ("image", "video") and b.get("src"):
            b["url"] = f"/api/media/{session_id}/{b['src']}"
        blocks.append(b)
    return {
        "title": _slide_title(slide),
        "blocks": blocks,
        "links": slide.get("links", []),
        "examinable": bool(slide.get("examinable", True)) and has_text,
    }


def _grounding_text(slide) -> str:
    """Slide text Lunar reasons over: references/dedications removed, OCR kept."""
    if not isinstance(slide, dict):
        return classroom.clean_board_text(slide or "")
    base = classroom.clean_board_text(slide.get("text", ""))
    ocr = slide.get("ocr", "")
    return "\n".join(p for p in (base, ocr) if p and p.strip()).strip()


# ---- render warm-up + prefetch -------------------------------------
@app.on_event("startup")
async def _warm_render_pipeline():
    """Warm the PDF render stack (and the voice models) in the background so first use is fast."""
    import threading
    threading.Thread(target=file_processor.warm_render, daemon=True).start()
    threading.Thread(target=voice.warm, daemon=True).start()
    threading.Thread(target=_drop_chalk_renders, daemon=True).start()
    brain.CHOICE = lib.settings().get("brain")      # load the brain now, so the first lesson doesn't wait
    brain.warm()
    # list the student's study files for /find a little after start-up, so the first search is instant
    t = threading.Timer(12.0, finder.refresh)
    t.daemon = True
    t.start()
    t = threading.Timer(20.0, mx_command.warm)      # /CUSTOM-Mx's name tables (about 2 s), off the start-up path
    t.daemon = True
    t.start()


def _drop_chalk_renders():
    """Slides now show in their own colours (page_N.png). The old chalk renders (board_N.png) are only
    a cache — remove them so updated installs get the space back. Nothing else in the folder is touched."""
    import re as _re_local
    try:
        for deck in os.listdir(MEDIA_DIR):
            folder = os.path.join(MEDIA_DIR, deck)
            if not os.path.isdir(folder):
                continue
            for name in os.listdir(folder):
                if _re_local.fullmatch(r"board_\d+\.png", name):
                    try:
                        os.remove(os.path.join(folder, name))
                    except OSError:
                        pass
    except OSError:
        pass


_render_locks = {}


async def _ensure_board_image(session_id: str, idx: int):
    """Render+cache a board slide's page image if missing; return its path or None.

    Serialised per (session, slide) so the on-demand fetch and the background
    pre-render never render the same page twice.
    """
    session = sessions.get(session_id)
    if not session:
        return None
    slides = session.get("slides") or []
    if idx < 0 or idx >= len(slides):
        return None
    slide = slides[idx]
    if not isinstance(slide, dict) or not slide.get("board") or slide.get("blank"):
        return None
    media_dir = session.get("media_dir") or os.path.join(MEDIA_DIR, session_id)
    os.makedirs(media_dir, exist_ok=True)
    out = os.path.join(media_dir, f"page_{idx}.png")       # colour; "board_N.png" was the old chalk look
    if os.path.isfile(out):
        return out
    lock = _render_locks.setdefault((session_id, idx), asyncio.Lock())
    async with lock:
        if os.path.isfile(out):          # rendered while we waited on the lock
            return out
        if slide.get("board") == "pdf":                     # a PDF, or a PowerPoint deck's PDF
            await asyncio.to_thread(file_processor.render_pdf_page,
                                    file_processor.ppt_render_path(session["file_path"]), slide.get("page", idx), out)
        elif slide.get("board") == "image":
            await asyncio.to_thread(file_processor.render_image, session["file_path"], out)
        elif slide.get("board") == "pptx":                   # drawn by MrSOLIS (no office suite)
            words = await asyncio.to_thread(file_processor.render_pptx_slide,
                                            session["file_path"], slide.get("page", idx), out)
            with open(out + ".words.json", "w", encoding="utf-8") as f:
                json.dump(words, f)
        old = os.path.join(media_dir, f"board_{idx}.png")   # drop the old chalk render (updated installs)
        if os.path.isfile(old):
            try:
                os.remove(old)
            except OSError:
                pass
    return out if os.path.isfile(out) else None


def _image_data_url(path: str, max_side: int | None = None) -> str | None:
    """A picture as a JPEG data: URL, shrunk so its longest side is max_side.

    The brain spends one token per 32x32 pixels, so a 1024 px slide costs ~1000
    tokens instead of the ~4000 a full-size page render would. By default (CUSTOM-Kx, 2026-10-24) a
    landscape slide goes at 832 px (~360 tokens): Smarts read 8 real slides word for word the same as at
    768 tokens and started answering in 8.8 s instead of 19.9 s; a portrait page of dense notes keeps
    1024 px — at fewer tokens Smarts once misread "0.04 x 38.5" as "0.6 x 38.5".
    """
    try:
        from PIL import Image
        import base64
        with Image.open(path) as im:
            im = im.convert("RGB")
            side = max_side or (832 if im.width >= im.height else 1024)
            im.thumbnail((side, side))
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=88)
        return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception:
        return None


async def _slide_picture(session_id: str, idx: int) -> str | None:
    """The slide's page as a data: URL for a brain that sees (cached per session)."""
    session = sessions.get(session_id)
    if not session:
        return None
    cache = session.setdefault("_pictures", {})
    if idx in cache:
        return cache[idx]
    path = await _ensure_board_image(session_id, idx)
    url = await asyncio.to_thread(_image_data_url, path) if path else None
    if len(cache) > 40:                       # a long deck: keep memory bounded
        cache.clear()
    cache[idx] = url
    return url


# Questions about something drawn on the slide: send the brain the slide's picture.
_VISUAL_ASK = re.compile(r"\b(diagram|figure|fig|picture|image|photo|graph|chart|plot|curve|circuit|"
                         r"drawing|drawn|shown|shows|table|map|label(?:led|ed)?|arrow|colou?r|look(?:s)? like)\b",
                         re.IGNORECASE)


def _checked_image(image: str | None) -> str | None:
    """A student's attached picture, if it is a real image data: URL of a sane size."""
    if not image or not isinstance(image, str):
        return None
    if not image.startswith("data:image/") or len(image) > 8_000_000:
        return None
    return image if brain.sees() else None


async def _prerender_all(session_id: str):
    """Render every board slide in the background so navigation is always instant.

    Starts after a short delay and paces itself so it never starves the live
    lecture generation of CPU (the on-demand render for the slide being viewed
    still happens immediately in teach_stream).
    """
    await asyncio.sleep(6)                    # let the first lecture get going first
    session = sessions.get(session_id)
    if not session:
        return
    n = len(session.get("slides") or [])
    for idx in range(n):
        if not sessions.get(session_id):     # session went away
            return
        await _wait_until_idle()             # never compete with a live LLM stream
        try:
            await _ensure_board_image(session_id, idx)
        except Exception:
            pass
        await asyncio.sleep(0.4)              # gentle: yield CPU to the lecture


# ---- status ---------------------------------------------------------
@app.get("/api/health")
async def health():
    """Readiness probe for the on-device AI status chip."""
    info = await local_llm.health()
    return info


# ---- upload ---------------------------------------------------------
@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...)):
    """Upload a file and split it into the slides the classroom will teach."""
    return await _ingest(file.filename, await file.read())


# ---- /find: open a study file from this computer by name ---------------
@app.get("/api/files/find")
async def files_find(q: str = ""):
    """The student's documents whose name (or folder) matches `q` — best match first."""
    results = await asyncio.to_thread(finder.search, q)
    return {"results": results, **finder.status()}


class OpenFileRequest(BaseModel):
    path: str


@app.post("/api/files/open")
async def files_open(req: OpenFileRequest):
    """Open a file /find showed, exactly as if it had been uploaded."""
    if not finder.allowed(req.path):
        raise HTTPException(status_code=403, detail="Search for the file with /find first.")
    try:
        if os.path.getsize(req.path) > 300 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="That file is too big to open (over 300 MB).")
        data = await asyncio.to_thread(lambda: open(req.path, "rb").read())
    except OSError as e:
        raise HTTPException(status_code=404, detail=f"Couldn't read the file: {e.strerror or e}")
    return await _ingest(os.path.basename(req.path), data)


async def _ingest(filename: str, data: bytes):
    """Split a file into the slides the classroom will teach (Upload and /find both land here).

    A file that's already in the library (same bytes, any name) isn't copied again:
    the existing deck reopens with its subject, progress and notes.
    """
    fingerprint = hashlib.sha256(data).hexdigest()
    existing = await asyncio.to_thread(lib.find_by_fingerprint, fingerprint)
    if existing:
        await asyncio.to_thread(_upgrade_ppt_session, existing["id"])      # an old mangled PowerPoint deck
        session = await asyncio.to_thread(_get_session, existing["id"])
        if session:
            lib.log("open", existing["id"])
            return {
                "session_id": existing["id"],
                "filename": existing.get("filename"),
                "slides": len(session["slides"]),
                "existing": True,
                "title": existing.get("title") or existing.get("filename"),
                "last_slide": existing.get("last_slide", 0),
                "seen": existing.get("seen", []),
            }

    session_id = str(uuid.uuid4())
    file_ext = os.path.splitext(filename)[1] if filename else ""
    file_path = os.path.join(UPLOAD_DIR, f"{session_id}{file_ext}")

    with open(file_path, "wb") as f:
        f.write(data)

    # One pass: verbatim text + inline media (figures/video) + links per slide. Off the event loop:
    # a PowerPoint deck is drawn by PowerPoint first (10-25 s), and the app must stay responsive.
    media_dir = os.path.join(MEDIA_DIR, session_id)
    slides = await asyncio.to_thread(extract_rich_slides, file_path, media_dir)
    extracted_text = "\n\n".join(slide_plain_text(s) for s in slides)

    if not slides or not extracted_text.strip():
        return {
            "session_id": session_id,
            "filename": filename,
            "text_preview": extracted_text or "No text could be extracted.",
            "warning": "Limited or no text extracted. The file may be an unsupported format or empty.",
        }

    sessions[session_id] = {
        "filename": filename,
        "file_path": file_path,
        "media_dir": media_dir,
        "text": extracted_text,
        "slides": slides,
        "slide_index": 0,
    }
    # Keep the deck in the library so it can be reopened (and its slides read instantly) later.
    try:
        lib.save_slides(session_id, slides)
        lib.add_deck(session_id, filename or "Untitled", file_path, media_dir,
                     [_slide_title(s) for s in slides], sha256=fingerprint)
        lib.log("upload", session_id)
    except Exception:
        pass

    # Pre-render slide images in the background for instant navigation — but start
    # AFTER the first lecture has had a head start and pace it gently, so it doesn't
    # steal CPU from the (much more important) lecture generation. Slide embeddings
    # for "Find anything" are computed lazily on first search (which is gated to
    # after the lecture), so they never compete with the LLM either.
    try:
        asyncio.create_task(_prerender_all(session_id))
        # If we've embedded this exact deck before, load it from disk now (free) so
        # "Find anything" is instant; new decks are embedded after the first lecture.
        asyncio.create_task(_load_cached_embeddings(session_id))
    except Exception:
        pass

    preview = extracted_text[:500] + "..." if len(extracted_text) > 500 else extracted_text
    return {
        "session_id": session_id,
        "filename": filename,
        "text_preview": preview,
        "text_length": len(extracted_text),
        "slides": len(slides),
    }


# ---- board slide image (PDF page / image, in its own colours) -------
@app.get("/api/classroom/slide_image/{session_id}/{idx}")
async def slide_image(session_id: str, idx: int):
    """Render (and cache) the page image for one slide, on demand."""
    if not _get_session(session_id):
        raise HTTPException(status_code=404, detail="Session not found.")
    try:
        out = await _ensure_board_image(session_id, idx)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not render slide: {e}")
    if not out:
        raise HTTPException(status_code=404, detail="This slide has no board image.")
    return FileResponse(out, headers={"Cache-Control": "no-cache"})   # revalidate: cheap 304s, never a stale look


@app.get("/api/classroom/slide_text/{session_id}/{idx}")
async def slide_text(session_id: str, idx: int):
    """Word boxes for a PDF board slide so the real slide is selectable on the board.

    Returns {"words": [{x,y,w,h,t}, ...]} as page fractions (0..1). Non-PDF or
    text-free slides simply return an empty list — the slide image stays put,
    there's just nothing to highlight on it.
    """
    session = _get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")
    slides = session.get("slides") or []
    if idx < 0 or idx >= len(slides):
        return {"words": []}
    slide = slides[idx]
    if not isinstance(slide, dict) or slide.get("board") not in ("pdf", "pptx") or slide.get("blank"):
        return {"words": []}
    cache = session.setdefault("_slide_words", {})
    if idx in cache:
        return {"words": cache[idx]}
    if slide.get("board") == "pptx":                     # words recorded while MrSOLIS drew the slide
        try:
            png = await _ensure_board_image(session_id, idx)
            with open(png + ".words.json", encoding="utf-8") as f:
                cache[idx] = json.load(f)
        except Exception:
            cache[idx] = []
        return {"words": cache[idx]}
    try:
        # One box PER WORD: the frontend overlays each word with an invisible span
        # stretched to exactly cover it, so selection is character-precise (WPS-style)
        # and grabs only what the user drags over — not the surrounding text.
        words = await asyncio.to_thread(
            file_processor.pdf_page_words, file_processor.ppt_render_path(session["file_path"]), slide.get("page", idx))
    except Exception:
        words = []
    cache[idx] = words
    return {"words": words}


# ---- media (figures / videos extracted from slides) -----------------
@app.get("/api/media/{session_id}/{filename}")
async def get_media(session_id: str, filename: str):
    """Serve a figure/video extracted from an uploaded slide."""
    # Guard against path traversal — only a bare filename is allowed.
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid media path.")
    session = _get_session(session_id)
    media_dir = session.get("media_dir") if session else os.path.join(MEDIA_DIR, session_id)
    path = os.path.normpath(os.path.join(media_dir, filename))
    if not path.startswith(os.path.normpath(media_dir)) or not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Media not found.")
    return FileResponse(path)


# ---- classroom ------------------------------------------------------
@app.post("/api/classroom/start")
async def classroom_start(req: ClassroomStartRequest):
    """Return the slide count + short titles for the classroom progress bar."""
    session = _get_session(req.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found. Upload a file first.")
    slides = session.get("slides") or []
    session["slide_index"] = 0
    return {"count": len(slides), "titles": [_slide_title(s) for s in slides]}


def _transition(slides: list, idx: int) -> str:
    """The sentence after slide idx's lesson: names the next slide, or closes the lecture when nothing
    after it is left to teach (only blank pages or a "Thank you" / "Questions?" slide)."""
    for j in range(idx + 1, len(slides)):
        s = slides[j]
        if isinstance(s, dict) and s.get("blank"):
            continue
        text = _grounding_text(s)
        if not text.strip():
            continue
        note = classroom._heading_note(text, j + 1) or ""
        if note.startswith("That's the end"):                # a closing slide: this was the last real one
            continue
        nxt, cur = _heading_title(s), _heading_title(slides[idx])
        if nxt and cur and _norm_line(nxt) == _norm_line(cur):
            return "When you're ready, let's continue to the next slide."     # same section carries on
        return classroom.lesson_transition(idx + 1, len(slides), nxt)
    return classroom.lesson_transition(idx + 1, len(slides), at_end=True)


# First lines that are not headings: sentences carried over ("Therefore, exactly one of…"), dividers.
_NOT_HEADING = re.compile(r"(?i)^(therefore|hence|thus|so|for (instance|example)|and|but|also|i\.e|e\.g|where|which|"
                          r"it|this|these|that|then|if|when|since|because|note)\b|^(table of contents|contents|outline|"
                          r"agenda|overview|thank you|questions?)\W*$")


def _heading_title(slide) -> str:
    """The slide's title if it reads like a heading ("Section 1.1.2: Construction - Stator",
    "SETS AND ELEMENTS"), else "" — PDFs often have no title, and their first line is a sentence."""
    raw = (slide.get("title") if isinstance(slide, dict) else "") or ""
    if not raw:
        text = slide.get("text", "") if isinstance(slide, dict) else str(slide or "")
        raw = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    raw = re.sub(r"\s+", " ", raw.strip(" ▶•-–\t"))
    if (not raw or len(raw) > 48 or len(raw.split()) > 9 or raw[:1].islower() or _NOT_HEADING.search(raw)
            or re.search(r"[a-z]\.\s+[A-Z]", raw) or raw[-1] in ",;:-"):
        return ""
    return raw


@app.post("/api/classroom/teach_stream")
async def classroom_teach_stream(req: TeachRequest):
    """Stream Lunar teaching one slide (tokens written live to the board)."""
    session = _get_session(req.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found. Upload a file first.")
    slides = session.get("slides") or []
    if not slides:
        raise HTTPException(status_code=400, detail="This document has no slides to teach.")
    idx = max(0, min(req.slide_index, len(slides) - 1))
    session["slide_index"] = idx
    lib.touch_slide(req.session_id, idx)             # progress + history
    length = lib.settings().get("lesson_length", "standard")

    slide = slides[idx]
    grounding = _grounding_text(slide)
    payload = _slide_payload(req.session_id, slide, idx)
    look = bool(payload.get("image")) and brain.sees() and lib.settings().get("look_at_slides", True)
    if look:                                      # look only where words alone miss something
        if "_fig" not in slide:
            slide["_fig"] = await asyncio.to_thread(file_processor.slide_has_figure, session["file_path"], slide)
        look = slide["_fig"] or len(grounding.strip()) < 300
    if look and not payload.get("blank") and isinstance(slide, dict) and slide.get("examinable", True):
        payload["examinable"] = True              # a diagram-only slide can be taught from its picture

    async def gen():
        # 1) For board slides, render the page image NOW (CPU is free here) so
        # it's cached before the note generation pins all cores — otherwise the
        # render competes with the LLM and the board sits blank for seconds.
        if payload.get("image"):
            try:
                await _ensure_board_image(req.session_id, idx)
            except Exception:
                pass
        # The verbatim board: the slide's page image, or ordered text blocks.
        yield json.dumps({"slide": payload}) + "\n"
        # 2) Lunar's grounded explanation under it (only if examinable).
        picture = await _slide_picture(req.session_id, idx) if look else None
        if picture and payload.get("examinable"):
            yield json.dumps({"looking": True}) + "\n"     # "MrSOLIS is looking at the slide…"
        if payload.get("examinable") and (grounding.strip() or picture):
            # A question printed on the slide becomes a CUSTOM-Mx draft under the lesson, for the student to check
            # and run; the brain teaches its method but leaves the numbers to CUSTOM-Mx.
            try:
                offers = await asyncio.to_thread(mathengine.slide_questions, grounding)
            except Exception:
                offers = []
            try:
                async with _interactive():
                    async for piece in classroom.teach_slide_stream(grounding, idx + 1, len(slides), length,
                                                                    image=picture, exact=[q for q, _d in offers]):
                        yield json.dumps({"token": piece}) + "\n"
                if offers:
                    yield json.dumps({"exact": [d for _q, d in offers]}) + "\n"
            except local_llm.LocalLLMError as e:
                yield json.dumps({"error": str(e)}) + "\n"
                return
            except Exception as e:
                yield json.dumps({"error": f"Failed to teach slide: {e}"}) + "\n"
                return
            # 3) The way on: "Next, we'll look at …", or a close after the last slide worth teaching.
            if classroom.is_lesson_slide(grounding, idx + 1, picture):
                yield json.dumps({"next": _transition(slides, idx)}) + "\n"
        # The lecture just finished, so Ollama is free and the student is reading:
        # warm the "Find anything" slide embeddings now (once) so search is instant.
        if not session.get("_search_warmed"):
            session["_search_warmed"] = True
            try:
                asyncio.create_task(_embed_slides_bg(req.session_id))
            except Exception:
                pass
        yield json.dumps({"done": True, "slide_index": idx,
                          "last": idx >= len(slides) - 1}) + "\n"

    return StreamingResponse(gen(), media_type="application/x-ndjson", headers=_STREAM_HEADERS)


@app.post("/api/classroom/chat_stream")
async def classroom_chat_stream(req: ClassroomChatRequest):
    """Stream Lunar's reply to the student, grounded in the current slide."""
    session = _get_session(req.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found. Upload a file first.")
    slides = session.get("slides") or []
    idx = max(0, min(req.slide_index, len(slides) - 1)) if slides else 0
    slide_text = _grounding_text(slides[idx]) if slides else session.get("text", "")
    lib.log("ask", req.session_id, slide=idx, text=req.message[:300])
    if req.video:
        return _video_answer(req.video, req.message, req.history)
    photo = _checked_image(req.image)

    async def gen():
        picture = photo
        if not picture and brain.sees() and slides and lib.settings().get("look_at_slides", True) \
                and classroom.fixed_answer(req.message, True) is None \
                and (_VISUAL_ASK.search(req.message) or len(slide_text.strip()) < 200):
            picture = await _slide_picture(req.session_id, idx)
        if picture:
            yield json.dumps({"looking": True}) + "\n"
        try:
            async with _interactive():
                async for piece in classroom.chat_stream(slide_text, req.message, req.history,
                                                         image=picture, photo=bool(photo)):
                    yield json.dumps({"token": piece}) + "\n"
        except local_llm.LocalLLMError as e:
            yield json.dumps({"error": str(e)}) + "\n"
            return
        except Exception as e:
            yield json.dumps({"error": f"Failed to respond: {e}"}) + "\n"
            return
        yield json.dumps({"done": True}) + "\n"

    return StreamingResponse(gen(), media_type="application/x-ndjson", headers=_STREAM_HEADERS)


class FreeChatRequest(BaseModel):
    message: str
    history: list[dict] = Field(default_factory=list)
    image: str | None = None            # a picture the student attached (data: URL)
    video: str | None = None            # a video the student attached (its id from /api/video/prepare)


@app.post("/api/chat_stream")
async def free_chat_stream(req: FreeChatRequest):
    """Chat with MrSOLIS before any slides are open: general answers, each ending with a
    reminder to upload material (or carry on with a recent deck) and start learning."""
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="Say something first.")
    lib.log("ask", None, text=req.message[:300])
    if req.video:
        return _video_answer(req.video, req.message, req.history)
    recent = [d.get("title") or os.path.splitext(d.get("filename") or "")[0] for d in lib.decks()[:3]]

    async def gen():
        try:
            async with _interactive():
                async for piece in classroom.free_chat_stream(req.message, req.history, recent,
                                                              image=_checked_image(req.image)):
                    yield json.dumps({"token": piece}) + "\n"
        except local_llm.LocalLLMError as e:
            yield json.dumps({"error": str(e)}) + "\n"
            return
        except Exception as e:
            yield json.dumps({"error": f"Failed to respond: {e}"}) + "\n"
            return
        yield json.dumps({"done": True}) + "\n"

    return StreamingResponse(gen(), media_type="application/x-ndjson", headers=_STREAM_HEADERS)


# ---- videos: watch and listen (backend/video.py) --------------------
class VideoRequest(BaseModel):
    path: str
    name: str = ""


def _video_error(e: Exception):
    raise HTTPException(status_code=400, detail=str(e) if isinstance(e, (RuntimeError, ValueError, OSError))
                        else "MrSOLIS couldn't open this video.")


@app.post("/api/video/prepare")
async def video_prepare(req: VideoRequest):
    """Start watching a video on this computer (the desktop app passes its path): frames + what is said."""
    try:
        return await asyncio.to_thread(video.prepare, req.path, req.name)
    except Exception as e:
        _video_error(e)


@app.post("/api/video/upload")
async def video_upload(file: UploadFile = File(...)):
    """The same for a video sent as a file (no path, e.g. the browser): kept under uploads/videos/."""
    name = os.path.basename(file.filename or "video")
    if not name.lower().endswith(video.VIDEO_EXT + video.AUDIO_EXT):
        raise HTTPException(status_code=400, detail="That isn't a video or sound file MrSOLIS can open.")
    os.makedirs(VIDEO_UPLOAD_DIR, exist_ok=True)
    dest = os.path.join(VIDEO_UPLOAD_DIR, re.sub(r'[\\/:*?"<>|]+', "_", name))
    with open(dest, "wb") as f:
        while chunk := await file.read(1 << 20):
            f.write(chunk)
    try:
        return await asyncio.to_thread(video.prepare, dest, name)
    except Exception as e:
        _video_error(e)


@app.get("/api/video/{vid}")
async def video_status(vid: str):
    return video.status(vid)


@app.get("/api/video/{vid}/frame/{n}")
async def video_frame(vid: str, n: int):
    path = video.frame_path(vid, n)
    if not path or not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="No such frame.")
    return FileResponse(path, media_type="image/jpeg")


_VIDEO_WARMED = set()


@app.post("/api/video/{vid}/warm")
async def video_warm(vid: str):
    """Have the brain read a prepared video now, while the student types: the first question then
    starts from it (the engine keeps it, see classroom.video_messages). Measured 2026-10-24 on an
    i5-13420H: the first question took 23 s to its first word on Smarts (9 s on Speedy), follow-ups 1–2 s."""
    meta = video.load(vid)
    if not meta or vid in _VIDEO_WARMED or not brain.active() or _interactive_count > 0:
        return {"warming": False}
    _VIDEO_WARMED.add(vid)
    frames = video.frame_urls(meta, classroom._VIDEO_FRAMES) if brain.sees() else []

    async def read_it():
        try:
            await brain.chat(classroom.video_messages(meta, frames, "", None), temperature=0.0, max_tokens=1)
        except Exception:
            _VIDEO_WARMED.discard(vid)
    asyncio.create_task(read_it())
    return {"warming": True}


def _video_answer(vid: str, message: str, history):
    """Stream the answer to a question about an attached video, waiting for it to be prepared first."""
    async def gen():
        st = video.status(vid)
        if st["state"] == "missing":
            yield json.dumps({"error": "That video isn't open any more — attach it again."}) + "\n"
            return
        yield json.dumps({"looking": True}) + "\n"                  # "MrSOLIS is watching the video…"
        if st["state"] != "ready":
            st = await asyncio.to_thread(video.wait, vid)
        if st["state"] != "ready":
            yield json.dumps({"error": st.get("error") or "MrSOLIS couldn't watch this video."}) + "\n"
            return
        meta = video.load(vid)
        frames = video.frame_urls(meta, classroom._VIDEO_FRAMES) if brain.sees() else []
        try:
            async with _interactive():
                async for piece in classroom.video_chat_stream(meta, frames, message, history):
                    yield json.dumps({"token": piece}) + "\n"
        except local_llm.LocalLLMError as e:
            yield json.dumps({"error": str(e)}) + "\n"
            return
        except Exception as e:
            yield json.dumps({"error": f"Failed to respond: {e}"}) + "\n"
            return
        yield json.dumps({"done": True}) + "\n"

    return StreamingResponse(gen(), media_type="application/x-ndjson", headers=_STREAM_HEADERS)


async def _retrieve_grounding(session, query, exclude_idx=None, k=2):
    """Top-k most relevant slide snippets across the deck for `query` (RAG context).

    Best-effort: only runs if the deck's embeddings are already warmed, so it never
    blocks Explain/Solve on embedding the whole deck. Gives the small model the exact
    definitions/formulas it needs from elsewhere in the notes.
    """
    vecs = session.get("slide_vectors")
    texts = session.get("slide_search_texts")
    q = (query or "").strip()
    if not vecs or not texts or not q:
        return ""
    try:
        qv = (await local_llm.embed([q]))[0]
    except Exception:
        return ""
    scored = sorted(((questions._cos(qv, v), i) for i, v in enumerate(vecs)), reverse=True)
    out = []
    for score, i in scored:
        if i == exclude_idx or score < 0.4 or i >= len(texts):
            continue
        snippet = " ".join((texts[i] or "").split())[:260].strip()
        if snippet:
            out.append(snippet)
        if len(out) >= k:
            break
    return "\n---\n".join(out)


@app.post("/api/classroom/explain")
async def classroom_explain(req: ExplainRequest):
    """Explain (or solve) the portion the student highlighted on the board."""
    session = _get_session(req.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found. Upload a file first.")
    slides = session.get("slides") or []
    idx = max(0, min(req.slide_index, len(slides) - 1)) if slides else 0
    slide_text = _grounding_text(slides[idx]) if slides else session.get("text", "")
    mode = "solve" if req.mode == "solve" else "explain"
    lib.log(mode, req.session_id, slide=idx, text=req.selection[:300])

    # Solve: CUSTOM-Mx works it exactly; the brain then only explains the idea. When CUSTOM-Mx can't, the old
    # path: sympy pins a bare equation's answer and the brain solves toward it.
    mx = await asyncio.to_thread(mathengine.solve, req.selection) if mode == "solve" else None
    offer = (await _draft_exact(req.selection))[0] if mode == "solve" and not mx else None
    verified = ""
    if mode == "solve" and not mx and not offer:
        try:
            verified = questions.solve_selection(req.selection) or ""
        except Exception:
            verified = ""
    # RAG: pull the most relevant facts from elsewhere in the deck (if warmed).
    context = await _retrieve_grounding(session, req.selection, exclude_idx=idx, k=2) if not (mx or offer) else ""

    async def gen():
        if offer:                              # a word problem: the student checks the reading before it's worked
            for line in _offer_events(offer):
                yield line
            return
        if mx:
            working = mathengine.working_markdown(mx)
            yield json.dumps({"token": working + "\n\n"}) + "\n"
            try:
                async with _interactive():
                    async for piece in classroom.explain_working_stream(req.selection, working, slide_text):
                        yield json.dumps({"token": piece}) + "\n"
            except Exception:
                pass                           # the working is the answer; the explanation is a bonus
            yield json.dumps({"done": True}) + "\n"
            return
        try:
            async with _interactive():
                async for piece in classroom.explain_stream(
                        slide_text, req.selection, mode, context=context, verified=verified):
                    yield json.dumps({"token": piece}) + "\n"
        except local_llm.LocalLLMError as e:
            yield json.dumps({"error": str(e)}) + "\n"
            return
        except Exception as e:
            yield json.dumps({"error": f"Failed to respond: {e}"}) + "\n"
            return
        yield json.dumps({"done": True}) + "\n"

    return StreamingResponse(gen(), media_type="application/x-ndjson", headers=_STREAM_HEADERS)


# ---- Find Anything: semantic search across the whole deck -----------
def _embed_inputs(session):
    """The per-slide search texts + the on-disk cache path (keyed by their content)."""
    import hashlib
    slides = session.get("slides") or []
    texts = []
    for s in slides:
        t = (_grounding_text(s) or "").strip() or _slide_title(s)
        texts.append(t[:1500] or " ")
    key = hashlib.sha1(("\x01".join(texts)).encode("utf-8")).hexdigest()
    return texts, os.path.join(EMBED_CACHE_DIR, f"{key}.json")


def _read_cached_vectors(cache_path, n):
    """Load a cached embedding list from disk iff it matches the expected length."""
    if not os.path.isfile(cache_path):
        return None
    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            cached = json.load(f)
        if isinstance(cached, list) and len(cached) == n:
            return cached
    except Exception:
        pass
    return None


async def _slide_vectors(session):
    """Embed every slide's text once (cached on the session) for semantic search.

    Serialised per session so the background warm-up and a live search never both
    embed the whole deck at the same time.
    """
    if session.get("slide_vectors") is not None and session.get("slide_search_texts") is not None:
        return session["slide_vectors"], session["slide_search_texts"]
    lock = session.get("_embed_lock")
    if lock is None:
        lock = session["_embed_lock"] = asyncio.Lock()
    async with lock:
        if session.get("slide_vectors") is not None and session.get("slide_search_texts") is not None:
            return session["slide_vectors"], session["slide_search_texts"]
        texts, cache_path = _embed_inputs(session)
        # Disk cache keyed by the exact text we embed → a deck is embedded only once
        # ever (survives restarts), so "Find anything" is instant on every later open.
        vecs = _read_cached_vectors(cache_path, len(texts))
        if vecs is None:
            vecs = await local_llm.embed(texts) if texts else []
            try:
                with open(cache_path, "w", encoding="utf-8") as f:
                    json.dump(vecs, f)
            except Exception:
                pass
        session["slide_vectors"] = vecs
        session["slide_search_texts"] = texts
        return vecs, texts


async def _embed_slides_bg(session_id: str):
    """Warm the deck's slide embeddings in the background (best effort).

    Waits for any live LLM stream to finish first so embedding the whole deck
    never steals CPU from the lecture / explain / solve the user is watching.
    """
    try:
        await _wait_until_idle()
        s = sessions.get(session_id)
        if s:
            await _slide_vectors(s)
    except Exception:
        pass


async def _load_cached_embeddings(session_id: str):
    """At upload: if this exact deck was embedded before, load the vectors from disk
    (free — no Ollama) so the very first search is instant even right after a restart.

    For a brand-new deck there's nothing cached, so this is a no-op and the embed is
    deferred to `_embed_slides_bg` (run after the first lecture) to avoid stealing CPU.
    """
    try:
        session = sessions.get(session_id)
        if not session or session.get("slide_vectors") is not None:
            return
        texts, cache_path = _embed_inputs(session)
        if not texts:
            return
        vecs = _read_cached_vectors(cache_path, len(texts))
        if vecs is not None:
            session["slide_vectors"] = vecs
            session["slide_search_texts"] = texts
            session["_search_warmed"] = True
    except Exception:
        pass


def _slide_fulltext(slide) -> str:
    """Everything literally on a slide (text + OCR + title + block text) for exact
    keyword search — the 'Windows search' literal layer over the semantic ranking."""
    if not isinstance(slide, dict):
        return str(slide or "")
    parts = [slide.get("text", ""), slide.get("ocr", ""), slide.get("title", "")]
    for b in slide.get("blocks", []) or []:
        if isinstance(b, dict) and b.get("type") == "text":
            parts.append(b.get("text", ""))
    return " ".join(p for p in parts if p)


_SEARCH_STOP = {"slide", "slides", "page", "pages", "pg", "no", "number", "the", "a", "an",
                "of", "on", "in", "is", "to", "and", "for", "with", "about", "show", "find",
                "me", "what", "where"}


def _snippet(text: str, query: str) -> str:
    """A short, relevant excerpt of a slide for the search results."""
    clean = " ".join((text or "").split())
    q_tokens = [w for w in query.lower().split() if len(w) > 2]
    low = clean.lower()
    for w in q_tokens:
        pos = low.find(w)
        if pos >= 0:
            start = max(0, pos - 60)
            return ("…" if start else "") + clean[start:start + 160].strip() + "…"
    return clean[:160].strip() + ("…" if len(clean) > 160 else "")


@app.post("/api/classroom/search")
async def classroom_search(req: SearchRequest):
    """Find slides by query — exact slide number + literal keyword match (instant,
    like a file search) blended with semantic ranking, so 'slide 7' always returns
    slide 7 and any word printed on a slide is found verbatim."""
    import re
    session = _get_session(req.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found. Upload a file first.")
    query = (req.query or "").strip()
    if not query:
        return {"results": []}
    slides = session.get("slides") or []
    n = len(slides)
    texts, _ = _embed_inputs(session)               # per-slide snippet text (no embedding)
    full = [_slide_fulltext(slides[i]).lower() for i in range(n)]
    titles = [_slide_title(slides[i]).lower() for i in range(n)]
    scores = {}

    # 1) Exact slide / page number — "slide 7", "page 7", "#7", or a bare "7".
    m = re.search(r"\b(?:slide|page|pg|sl|no\.?|number)\s*#?\s*(\d+)\b", query, re.I)
    if not m:
        m = re.fullmatch(r"\s*#?\s*(\d+)\s*", query)
    if m:
        k = int(m.group(1))
        if 1 <= k <= n:
            scores[k - 1] = scores.get(k - 1, 0.0) + 1000.0

    # 2) Literal keyword match (the "Windows search" layer).
    ql = query.lower().strip()
    terms = [t for t in re.findall(r"[a-z0-9]+", ql) if len(t) >= 2 and t not in _SEARCH_STOP]
    for i in range(n):
        if not terms:
            break
        body, title = full[i], titles[i]
        present = sum(1 for t in terms if t in body or t in title)
        if present:
            sc = 100.0 * (present / len(terms))      # all terms present → 100
            if ql in body or ql in title:
                sc += 60.0                            # exact phrase appears on the slide
            sc += 12.0 * sum(1 for t in terms if t in title)   # title hits weigh more
            scores[i] = scores.get(i, 0.0) + sc

    # 3) Semantic ranking — only when we don't already have a strong literal hit, so
    #    literal queries ('slide 7', a keyword) return instantly without embedding.
    strong = max(scores.values(), default=0.0) >= 100.0
    if not strong:
        vecs = session.get("slide_vectors")
        if vecs is None:
            try:
                vecs, _ = await _slide_vectors(session)   # disk-cached → usually instant
            except Exception:
                vecs = None
        if vecs and len(vecs) == n:
            try:
                qv = (await local_llm.embed([query]))[0]
                for i, v in enumerate(vecs):
                    scores[i] = scores.get(i, 0.0) + max(0.0, questions._cos(qv, v))
            except Exception:
                pass

    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    results = []
    for i, sc in ranked[:max(1, min(req.top_k, 12))]:
        if sc <= 0.18:                                # drop near-zero semantic noise
            continue
        results.append({
            "index": i,
            "title": _slide_title(slides[i]) if i < n else f"Slide {i + 1}",
            "snippet": _snippet(texts[i] if i < len(texts) else "", query),
            "score": round(float(sc), 3),
        })
    return {"results": results}


# ---- Uploads: the library of decks ----------------------------------
def _deck_view(d: dict) -> dict:
    return {
        "id": d["id"], "filename": d.get("filename"), "title": d.get("title"),
        "count": d.get("count", 0), "seen": len(d.get("seen") or []),
        "last_slide": d.get("last_slide", 0), "added": d.get("added"), "opened": d.get("opened"),
        "subject_id": d.get("subject_id"), "available": os.path.isfile(d.get("file_path") or ""),
    }


@app.get("/api/library")
async def library_list():
    return {"decks": [_deck_view(d) for d in lib.decks()], "subjects": lib.subjects()}


def _upgrade_ppt_session(deck_id: str):
    """A PowerPoint deck read before MrSOLIS could draw slides (text-and-pictures blocks, which
    "mangled" them): draw it properly now — once — keeping the student's place. A no-op for any other
    deck, one already drawn, or a computer with no office suite (tried once per run)."""
    session = _get_session(deck_id)
    if not session or session.get("ppt_tried"):
        return
    path = session.get("file_path") or ""
    if os.path.splitext(path)[1].lower() not in (".pptx", ".ppt"):
        return
    if any(isinstance(s, dict) and s.get("board") for s in session.get("slides") or []):
        return
    session["ppt_tried"] = True
    slides = file_processor._ppt_board_slides(path) or file_processor._pptx_drawn_slides(path)
    if not slides:
        return
    session.update(slides=slides, text="\n\n".join(slide_plain_text(s) for s in slides),
                   slide_vectors=None, slide_search_texts=None, _search_warmed=False)
    lib.save_slides(deck_id, slides)


@app.post("/api/library/{deck_id}/open")
async def library_open(deck_id: str):
    """Reopen a deck (after a restart too) and say where the student got to."""
    await asyncio.to_thread(_upgrade_ppt_session, deck_id)
    session = await asyncio.to_thread(_get_session, deck_id)
    if not session:
        raise HTTPException(status_code=404, detail="That deck's file is gone — upload it again.")
    deck = lib.deck(deck_id) or {}
    lib.log("open", deck_id)
    return {"session_id": deck_id, "filename": session["filename"], "count": len(session["slides"]),
            "last_slide": deck.get("last_slide", 0), "seen": deck.get("seen", [])}


class DeckUpdate(BaseModel):
    subject_id: str | None = None
    title: str | None = None


@app.patch("/api/library/{deck_id}")
async def library_update(deck_id: str, req: DeckUpdate):
    fields = req.model_dump(exclude_unset=True)
    sid = fields.get("subject_id")
    if sid and sid not in {s["id"] for s in lib.subjects()}:
        raise HTTPException(status_code=400, detail="No such subject.")
    if "title" in fields:
        fields["title"] = (fields["title"] or "").strip()[:120] or None
    deck = lib.update_deck(deck_id, **fields)
    if not deck:
        raise HTTPException(status_code=404, detail="No such deck.")
    return _deck_view(deck)


@app.delete("/api/library/{deck_id}")
async def library_delete(deck_id: str):
    """Remove a deck and everything stored for it (file, rendered slides, notes)."""
    deck = lib.remove_deck(deck_id)
    if not deck:
        raise HTTPException(status_code=404, detail="No such deck.")
    _remove_deck_files(deck)
    return {"ok": True}


def _remove_deck_files(deck: dict):
    """Delete a deck's uploaded file, rendered slides and cached text (only inside our folders)."""
    sessions.pop(deck["id"], None)
    lib.drop_slides(deck["id"])
    path = deck.get("file_path")
    drawn = file_processor.ppt_render_path(path) if path else None      # a PowerPoint deck's PDF
    for p in {path, drawn}:
        try:
            if p and os.path.normpath(p).startswith(os.path.normpath(UPLOAD_DIR)):
                os.remove(p)
        except OSError:
            pass
    media = deck.get("media_dir")
    if media and os.path.normpath(media).startswith(os.path.normpath(MEDIA_DIR)):
        shutil.rmtree(media, ignore_errors=True)


@app.on_event("startup")
async def _merge_duplicate_decks():
    """Decks uploaded twice before fingerprints existed are folded into one."""
    def run():
        for deck in lib.merge_duplicates():
            _remove_deck_files(deck)
    await asyncio.to_thread(run)


# ---- Subjects ---------------------------------------------------------
class SubjectIn(BaseModel):
    name: str


@app.post("/api/subjects")
async def subject_add(req: SubjectIn):
    if not req.name.strip():
        raise HTTPException(status_code=400, detail="Give the subject a name.")
    return lib.add_subject(req.name)


@app.patch("/api/subjects/{sid}")
async def subject_rename(sid: str, req: SubjectIn):
    s = lib.rename_subject(sid, req.name)
    if not s:
        raise HTTPException(status_code=404, detail="No such subject.")
    return s


@app.delete("/api/subjects/{sid}")
async def subject_delete(sid: str):
    if not lib.remove_subject(sid):
        raise HTTPException(status_code=404, detail="No such subject.")
    return {"ok": True}


# ---- Notes ------------------------------------------------------------
class NoteIn(BaseModel):
    deck_id: str | None = None
    text: str
    kind: str = "mine"            # mine | saved (a lesson / answer) | highlight
    slide: int | None = None


class NoteEdit(BaseModel):
    text: str


@app.get("/api/notes")
async def notes_list(deck_id: str | None = None):
    return {"notes": lib.notes(deck_id)}


@app.post("/api/notes")
async def notes_add(req: NoteIn):
    if not req.text.strip():
        raise HTTPException(status_code=400, detail="The note is empty.")
    return lib.add_note(req.deck_id, req.text, req.kind, req.slide)


@app.patch("/api/notes/{note_id}")
async def notes_edit(note_id: str, req: NoteEdit):
    n = lib.update_note(note_id, req.text)
    if not n:
        raise HTTPException(status_code=404, detail="No such note.")
    return n


@app.delete("/api/notes/{note_id}")
async def notes_delete(note_id: str):
    if not lib.remove_note(note_id):
        raise HTTPException(status_code=404, detail="No such note.")
    return {"ok": True}


def _crib_markdown(deck_id: str) -> str:
    session = _get_session(deck_id)
    if not session:
        raise HTTPException(status_code=404, detail="Deck not found.")
    slides = session.get("slides") or []
    return questions.build_crib_sheet([(i + 1, _grounding_text(s)) for i, s in enumerate(slides)])


@app.get("/api/notes/crib/{deck_id}")
async def notes_crib(deck_id: str):
    """Formulas, definitions and laws pulled verbatim from the deck."""
    return {"markdown": await asyncio.to_thread(_crib_markdown, deck_id)}


@app.get("/api/notes/export/{deck_id}")
async def notes_export(deck_id: str):
    """Everything for one deck as a Markdown file: crib sheet, saved parts, own notes."""
    deck = lib.deck(deck_id)
    if not deck:
        raise HTTPException(status_code=404, detail="Deck not found.")
    name = deck.get("title") or deck.get("filename") or "Deck"
    parts = [f"# {name} — notes", "", await asyncio.to_thread(_crib_markdown, deck_id)]
    for kind, heading in (("saved", "Saved from lessons"), ("highlight", "Highlights"), ("mine", "My notes")):
        ns = [n for n in lib.notes(deck_id) if n.get("kind") == kind]
        if ns:
            parts += ["", f"## {heading}", ""]
            for n in ns:
                where = f"_Slide {n['slide'] + 1}_ — " if isinstance(n.get("slide"), int) else ""
                parts += [where + n["text"].strip(), ""]
    stem = re.sub(r"[^\w\- ]+", "", os.path.splitext(name)[0]).strip() or "notes"
    return Response("\n".join(parts), media_type="text/markdown; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{stem} - notes.md"'})


# ---- Quizzes ----------------------------------------------------------
# With a brain, MrSOLIS writes each question from a slide and marks answers against it
# (quizgen.py) — a question takes ~10 s on a laptop CPU, so they are written in the background,
# _QUIZ_AHEAD ahead of the student. Questions already asked of a deck are remembered
# (library "asked") and never asked again. Without a brain, questions.py builds them by rules.
_live_quizzes = {}
_QUIZ_AHEAD = 2


class QuizStart(BaseModel):
    session_id: str
    count: int = 10


class QuizAnswer(BaseModel):
    quiz_id: str
    qid: int
    answer: str


# Slide admin that is never quiz material: who teaches, where, the course code, dates, contact details.
_ADMIN_LINE = re.compile(
    r"(?i)\b(universit(y|ies)|college|faculty|department|school of|institute|polytechnic|lecturer|instructor|"
    r"prepared by|presented by|compiled by|course (code|title)|credit hours?|semester|academic year|e-?mail|"
    r"tel\.?|phone)\b|\S+@\S+\.\w{2,}|\b(dr|prof|mr|mrs|ms)\.\s|\(ph\.?\s?d\.?\)")


def _quiz_text(session, i: int, text: str) -> str:
    """A slide's text for writing quiz questions: without the deck's repeated headers / footers (the
    lecturer's name, the institution, "SET THEORY 110/119" on every page), admin lines or page numbers —
    the brain once asked "What is the name of the institution?" from a footer."""
    if "_boilerplate" not in session:
        seen = {}
        for s in session.get("slides") or []:
            for ln in {_norm_line(x) for x in _grounding_text(s).splitlines() if x.strip()}:
                seen[ln] = seen.get(ln, 0) + 1
        n = len(session.get("slides") or [])
        session["_boilerplate"] = {ln for ln, c in seen.items() if n >= 4 and c >= max(3, n * 0.3)}
    keep = [ln for ln in text.splitlines() if ln.strip() and _norm_line(ln) not in session["_boilerplate"]
            and not _ADMIN_LINE.search(ln) and not re.fullmatch(r"\s*\d+(\s*/\s*\d+)?\s*", ln)]
    return "\n".join(keep)


def _norm_line(line: str) -> str:
    return re.sub(r"\d+", "#", re.sub(r"\s+", " ", line.strip().lower()))


def _quiz_slides(session) -> list:
    """[(index, text)] of the slides worth a question: not blank, not a title/outline/closing slide,
    with the slide admin taken out (see _quiz_text)."""
    out = []
    for i, s in enumerate(session.get("slides") or []):
        if isinstance(s, dict) and (s.get("blank") or not s.get("examinable", True)):
            continue
        text = _quiz_text(session, i, _grounding_text(s))
        if len(text.strip()) < 40 or classroom._heading_note(text, i + 1):
            continue
        out.append((i, text))
    return out


async def _rule_questions(slides: list, count: int) -> list:
    """The old way (no brain): questions built by rules, round-robin across the slides."""
    by_slide = []
    for i, text in slides:
        try:
            qs = await questions.generate(text, max_n=4)
        except Exception:
            qs = []
        if qs:
            by_slide.append([{**q, "slide": i} for q in qs])
    pool = []
    while by_slide and len(pool) < count:
        for group in list(by_slide):
            if group:
                pool.append(group.pop(0))
            if not group:
                by_slide.remove(group)
            if len(pool) >= count:
                break
    pool.sort(key=lambda q: q["slide"])
    return pool


async def _write_one(quiz: dict, idx: int, k: int):
    """One new question about slide idx, written once the student is close enough; None if the brain couldn't."""
    cond = quiz["cond"]
    while True:
        async with cond:                                  # stay ahead, but never while an answer is marked
            await cond.wait_for(lambda: len(quiz["questions"]) < quiz["answered"] + _QUIZ_AHEAD
                                and not quiz["marking"])
        before = [a for a in quiz["asked"] if a.get("slide") == idx] + \
                 [q for q in quiz["questions"] if q["slide"] == idx]
        job = quiz["writing"] = asyncio.create_task(quizgen.write(
            quiz["texts"][idx], [b["q"] for b in before], k, [b.get("a", "") for b in before]))
        try:
            async with _interactive():
                return await job
        except asyncio.CancelledError:
            if quiz.pop("preempted", False) and not quiz.get("ended"):
                continue                                  # stopped so an answer could be marked: write it again
            raise                                         # the quiz was ended
        except Exception:
            return None
        finally:
            quiz["writing"] = None


async def _write_quiz(quiz: dict):
    """Background: write the quiz's questions one by one, staying _QUIZ_AHEAD ahead of the student. A slide that
    gives no new question hands its turn to up to two other slides (least asked first), so the quiz keeps the
    number of questions the student picked (2026-10-30: 5 picked, 2 slides failed, the quiz stopped at 3)."""
    cond = quiz["cond"]
    try:
        for k, idx in enumerate(quiz["plan"]):
            q = await _write_one(quiz, idx, k)
            if not q:
                seen = [x.get("slide") for x in quiz["asked"] + quiz["questions"]]
                for alt in sorted((i for i in quiz["texts"] if i != idx), key=seen.count)[:2]:
                    q = await _write_one(quiz, alt, k + 1)
                    if q:
                        idx = alt
                        break
            async with cond:
                if q:
                    quiz["questions"].append({**q, "slide": idx})
                else:                                    # couldn't write a new one for this slide
                    quiz["total"] -= 1
                cond.notify_all()
    finally:
        quiz["done"] = True
        try:
            async with cond:
                cond.notify_all()
        except Exception:
            pass


async def _quiz_question(quiz: dict, i: int):
    """Question i once it's written (waits for the writer), or None if the quiz has fewer."""
    cond = quiz["cond"]
    async with cond:
        try:
            await asyncio.wait_for(cond.wait_for(
                lambda: len(quiz["questions"]) > i or quiz["done"] or i >= quiz["total"]), 240)
        except asyncio.TimeoutError:
            return None
    if i >= len(quiz["questions"]):
        return None
    q = quiz["questions"][i]
    if not q.get("_noted"):                              # the student has seen it: never ask it again
        q["_noted"] = True
        lib.note_asked(quiz["deck_id"], q["slide"], q["q"], q.get("a", ""))
    return {"id": i, "slide": q["slide"], "q": q["q"], "kind": q.get("kind", "text")}


def _end_quiz(quiz_id: str):
    quiz = _live_quizzes.pop(quiz_id, None)
    if quiz:
        quiz["ended"] = True
        if quiz.get("task") and not quiz["task"].done():
            quiz["task"].cancel()
    return quiz


@app.post("/api/quiz/start")
async def quiz_start(req: QuizStart):
    session = _get_session(req.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Deck not found.")
    for old in [k for k, v in _live_quizzes.items() if time.time() - v["started"] > 3 * 3600]:
        _end_quiz(old)                                   # abandoned quizzes
    slides = _quiz_slides(session)
    count = max(1, min(req.count, 30))
    quiz = {"deck_id": req.session_id, "texts": dict(slides), "results": {}, "answered": 0,
            "cond": asyncio.Condition(), "started": time.time(), "task": None, "marking": False, "writing": None}
    if brain.active():
        plan = quizgen.plan(slides, lib.asked(req.session_id), count)
        if not plan:
            return {"quiz_id": None, "message": "These slides don't have enough on them to quiz you on."}
        quiz.update(by="brain", plan=plan, asked=lib.asked(req.session_id), questions=[],
                    total=len(plan), done=False)
        quiz["task"] = asyncio.create_task(_write_quiz(quiz))
    else:
        pool = await _rule_questions(slides, count)
        if not pool:
            return {"quiz_id": None, "message": "These slides have no definitions, rules or worked examples to quiz you on."}
        quiz.update(by="rules", questions=pool, total=len(pool), done=True)
    quiz_id = uuid.uuid4().hex[:12]
    _live_quizzes[quiz_id] = quiz
    first = await _quiz_question(quiz, 0)
    if not first:
        _end_quiz(quiz_id)
        return {"quiz_id": None, "message": "MrSOLIS couldn't write questions from these slides. Try again."}
    return {"quiz_id": quiz_id, "total": quiz["total"], "first": first}


@app.get("/api/quiz/{quiz_id}/question/{i}")
async def quiz_question(quiz_id: str, i: int):
    """The next question (waits while MrSOLIS writes it); null when the quiz has no more."""
    quiz = _live_quizzes.get(quiz_id)
    if not quiz:
        raise HTTPException(status_code=404, detail="That quiz has ended.")
    q = await _quiz_question(quiz, i)
    return {"question": q, "total": quiz["total"]}


@app.post("/api/quiz/answer")
async def quiz_answer(req: QuizAnswer):
    quiz = _live_quizzes.get(req.quiz_id)
    if not quiz or not (0 <= req.qid < len(quiz["questions"])):
        raise HTTPException(status_code=404, detail="That quiz has ended.")
    q = quiz["questions"][req.qid]
    # The student comes first: stop the question being written (the brain does one thing at a
    # time — marking waited 25 s behind it), mark, then let the writer start that question again.
    quiz["marking"] = True
    job = quiz.get("writing")
    if job and not job.done():
        quiz["preempted"] = True
        job.cancel()
    try:
        if quiz["by"] == "brain":
            async with _interactive():
                m = await quizgen.mark(quiz["texts"].get(q["slide"], ""), q, req.answer)
        else:
            m = {"verdict": "correct" if await questions.grade(req.answer, q) else "wrong", "feedback": ""}
    except Exception:
        m = {"verdict": "correct" if await questions.grade(req.answer, q) else "wrong", "feedback": ""}
    finally:
        quiz["marking"] = False
    quiz["results"][req.qid] = {"answer": req.answer.strip()[:500], **m}
    async with quiz["cond"]:                             # marked first, then the writer carries on
        quiz["answered"] = max(quiz["answered"], req.qid + 1)
        quiz["cond"].notify_all()
    return {"correct": m["verdict"] == "correct", "verdict": m["verdict"], "feedback": m["feedback"],
            "answer": q.get("a", ""), "work": q.get("work", "")}


@app.post("/api/quiz/{quiz_id}/finish")
async def quiz_finish(quiz_id: str):
    quiz = _end_quiz(quiz_id)
    if not quiz:
        raise HTTPException(status_code=404, detail="That quiz has ended.")
    review = []
    for i, q in enumerate(quiz["questions"]):
        r = quiz["results"].get(i)
        if r is None:                                    # never reached (the quiz was ended early)
            continue
        review.append({"slide": q["slide"], "q": q["q"], "a": q.get("a", ""), "given": r["answer"],
                       "correct": r["verdict"] == "correct", "verdict": r["verdict"],
                       "feedback": r.get("feedback", "")})
    score = sum(1 if r["verdict"] == "correct" else 0.5 if r["verdict"] == "partly" else 0 for r in review)
    score = int(score) if float(score).is_integer() else score
    return lib.add_quiz(quiz["deck_id"], score, len(review), review)


@app.delete("/api/quiz/{quiz_id}")
async def quiz_quit(quiz_id: str):
    """Leave a quiz without a score (nothing answered yet)."""
    _end_quiz(quiz_id)
    return {"ok": True}


@app.get("/api/quizzes")
async def quizzes_list():
    return {"quizzes": lib.quizzes()}


# ---- History ----------------------------------------------------------
@app.get("/api/history")
async def history_list():
    return {"events": lib.events()}


@app.delete("/api/history")
async def history_clear():
    lib.clear_history()
    return {"ok": True}


# ---- Settings ---------------------------------------------------------
@app.get("/api/settings")
async def settings_get():
    return {"settings": lib.settings(), "engine": await local_llm.health()}


@app.put("/api/settings")
async def settings_put(changes: dict):
    before = lib.settings().get("brain")
    out = lib.update_settings(changes or {})
    if out.get("brain") != before:                  # the student picked another brain: load it now
        brain.CHOICE = out.get("brain")
        brain.warm()
    return {"settings": out}


# ---- Brain: the student picks which AI model MrSOLIS thinks with ---------
class BrainRequest(BaseModel):
    id: str


@app.get("/api/brain")
async def brain_status():
    """The brain cards (with estimates), which is installed / in use, and any download."""
    return {**brain.status(), "look_at_slides": lib.settings().get("look_at_slides", True)}


@app.post("/api/brain/download")
async def brain_download(req: BrainRequest):
    if req.id not in brain.BY_ID:
        raise HTTPException(status_code=404, detail="Unknown brain.")
    if not brain.start_download(req.id):
        raise HTTPException(status_code=409, detail="A brain is already downloading.")
    return brain.status()


@app.post("/api/brain/cancel")
async def brain_cancel():
    brain.DOWNLOAD["cancel"] = True
    return brain.status()


@app.post("/api/brain/select")
async def brain_select(req: BrainRequest):
    if not brain.installed(req.id):
        raise HTTPException(status_code=400, detail="Download this brain first.")
    lib.update_settings({"brain": req.id})
    brain.CHOICE = req.id
    brain.warm()                                     # load it in the background
    return brain.status()


@app.delete("/api/brain/{bid}")
async def brain_remove(bid: str):
    if bid not in brain.BY_ID:
        raise HTTPException(status_code=404, detail="Unknown brain.")
    if brain.DOWNLOAD.get("state") == "downloading" and brain.DOWNLOAD.get("id") == bid:
        raise HTTPException(status_code=409, detail="Cancel the download first.")
    await asyncio.to_thread(brain.remove, bid)
    if lib.settings().get("brain") == bid:
        lib.update_settings({"brain": None})
        brain.CHOICE = None
    brain.warm()                                     # fall back to another installed brain, if any
    return brain.status()


# ---- Voice: Transcription (dictate into the chat box) and Live (talk with MrSOLIS) ----
@app.get("/api/voice/status")
async def voice_status():
    return voice.status()


# Microphone in, words out. The page opens a listening session, then posts the audio
# it has captured (16 kHz mono float32, a few hundred ms at a time) and gets back the
# events it produced: {"type": "speech_start"}, {"type": "partial", "text"} while the
# student talks, {"type": "final", "text"} when they pause.
_listeners = {}             # session id → {"listener", "lock", "used"}


class ListenStart(BaseModel):
    mode: str = "dictate"   # dictate | live (live ends a turn on a shorter pause)


@app.post("/api/voice/listen")
async def voice_listen_start(req: ListenStart):
    if not voice.status()["hear"]:
        raise HTTPException(status_code=404, detail="The speech model isn't installed.")
    now = asyncio.get_running_loop().time()
    for sid in [k for k, v in _listeners.items() if now - v["used"] > 120]:   # forgotten sessions
        _listeners.pop(sid, None)
    listener = await asyncio.to_thread(voice.Listener, 0.7 if req.mode == "live" else 0.9)
    sid = uuid.uuid4().hex[:12]
    _listeners[sid] = {"listener": listener, "lock": asyncio.Lock(), "used": now}
    return {"id": sid}


@app.post("/api/voice/listen/{sid}")
async def voice_listen_audio(sid: str, request: Request, final: bool = False):
    """`?final=1` is the last post: the mic was stopped, so finish the sentence in progress."""
    s = _listeners.get(sid)
    if not s:
        raise HTTPException(status_code=404, detail="Listening stopped.")
    body = await request.body()
    samples = np.frombuffer(body[: len(body) // 4 * 4], dtype=np.float32)
    async with s["lock"]:
        s["used"] = asyncio.get_running_loop().time()
        # more than ~0.7 s waiting means we're behind: skip the words-so-far pass this time
        events = await asyncio.to_thread(s["listener"].feed, samples, len(samples) < 11200 and not final)
        if final:
            events += await asyncio.to_thread(s["listener"].finish)
            _listeners.pop(sid, None)
    return {"events": events}


@app.delete("/api/voice/listen/{sid}")
async def voice_listen_stop(sid: str):
    _listeners.pop(sid, None)
    return {"ok": True}


class SpeakRequest(BaseModel):
    text: str


@app.post("/api/voice/speak")
async def voice_speak(req: SpeakRequest):
    """One sentence read aloud by MrSOLIS (WAV), at the speed chosen in Settings."""
    if not voice.status()["speak"]:
        raise HTTPException(status_code=404, detail="The voice model isn't installed.")
    from backend.library import VOICE_SPEEDS
    speed = VOICE_SPEEDS.get(lib.settings().get("voice_speed"), 1.0)
    wav = await asyncio.to_thread(voice.speak, req.text, speed)
    if not wav:
        return Response(status_code=204)
    return Response(wav, media_type="audio/wav", headers={"Cache-Control": "no-store"})


# ---- Tools → Solver ---------------------------------------------------
class SolveRequest(BaseModel):
    problem: str


class MxRequest(BaseModel):
    command: str


# ---- CUSTOM-SQE: similar-questions practice (the SQE window, opened from Quizzes) ----------------------------
# One question at a time on its own thread: the engine is plain sympy (no brain), and a question that takes too
# long to work out gets a friendly answer after SQE_TIME_LIMIT instead of piling up work.
_SQE_EXEC = ThreadPoolExecutor(max_workers=1, thread_name_prefix="custom-sqe")
SQE_TIME_LIMIT = 25.0


class SqeRequest(BaseModel):
    question: str
    n: int = 10
    session: str | None = None         # the SQE window's practice session: nothing repeats within it
    reset: bool = False


class SqeCheckRequest(BaseModel):
    given: str
    correct: str
    kind: str = ""                     # the question's fact_type ("word_problem", "differentiation", ...)


@app.post("/api/sqe/generate")
async def sqe_generate(req: SqeRequest):
    """New practice questions like the one the student typed, each with its answer, steps and options."""
    question = (req.question or "").strip()[:600]
    run = functools.partial(sqe.generate, question, n=req.n, session=(req.session or "")[:64] or None, reset=req.reset)
    try:
        return await asyncio.wait_for(asyncio.get_running_loop().run_in_executor(_SQE_EXEC, run), SQE_TIME_LIMIT)
    except asyncio.TimeoutError:
        return {"ok": False, "message": "That question is taking too long to work out. Try a simpler version of it."}


@app.post("/api/sqe/check")
async def sqe_check(req: SqeCheckRequest):
    """Is a typed answer right? Fair to how students write answers (backend/sqe/api.py)."""
    return await asyncio.to_thread(sqe.check, req.given[:200], req.correct[:200], req.kind[:30])


class SqeDoneRequest(BaseModel):
    question: str
    score: int
    total: int


@app.post("/api/sqe/done")
async def sqe_done(req: SqeDoneRequest):
    """A finished SQE practice goes into History."""
    lib.log("practice", None, text=req.question[:300], score=max(0, req.score), total=max(0, req.total))
    return {"ok": True}


_MX_PREFIX = re.compile(r"^\s*/(?:custom-?mx|mx)\b", re.I)


class DraftRequest(BaseModel):
    text: str


@app.post("/api/mx/draft")
async def mx_draft(req: DraftRequest):
    """"Make it exact": a question in everyday words → a /CUSTOM-Mx command the student checks before sending.
    Code copies every number exactly; CUSTOM-Mx's rules (instant), else the brain, only say what each number is —
    the brain picks from fixed lists and never types a number. Nothing is solved until the student sends it."""
    text = (req.text or "").strip()
    if not text:
        return {"ok": False, "reason": "Type your question first."}
    if len(text) > 1500:
        return {"ok": False, "reason": "That question is too long to set up."}
    d, reason = await _draft_exact(text)
    return d or {"ok": False, "reason": reason}


async def _draft_exact(text: str):
    """(draft, reason): the question as a /CUSTOM-Mx command for the student to check. CUSTOM-Mx's rules first
    (instant); when they can't read it, the brain labels each number from fixed lists — it never types a number,
    and nothing is worked until the student runs the command."""
    d = await asyncio.to_thread(mx_command.draft, text)
    if d:
        return d, ""
    if not brain.active():
        return None, ("CUSTOM-Mx couldn't set that up by itself, and no brain is installed to help. "
                      "Write it yourself — /mx help shows how.")
    rq = await asyncio.to_thread(mathengine.reading_request, text)
    if not rq:
        return None, "There are no numbers with units here to set up."
    try:
        async with _interactive():
            reply = await asyncio.wait_for(brain.chat(rq["messages"], temperature=0.1, max_tokens=160,
                                                      schema=rq["schema"]), timeout=45)
    except Exception:
        return None, "The brain didn't answer in time. Try again, or write it yourself (/mx help)."
    labels = mathengine.read_labels(rq, reply)
    d = await asyncio.to_thread(mx_command.draft, text, labels) if labels else None
    return d, ("" if d else "That couldn't be set up as a command. Write it yourself — /mx help shows how.")


def _offer_events(d):
    """The stream for a word problem: the draft to check (the frontend shows Run / Edit), and why it's there."""
    yield json.dumps({"exact": [d]}) + "\n"
    yield json.dumps({"token": EXACT_LINE}) + "\n"
    yield json.dumps({"done": True}) + "\n"


EXACT_LINE = 'CUSTOM-Mx can work this exactly. Check that the command below says what the question means — every value and what it is — then press **Run**, or **Edit** it first.'


@app.post("/api/mx")
async def mx_run(req: MxRequest):
    """/CUSTOM-Mx: a command in CUSTOM-Mx's precise language, run exactly as written or refused with the reason.
    No brain is involved (backend/mathengine/command.py)."""
    command = (req.command or "").strip()
    if len(command) > 1500:
        raise HTTPException(status_code=400, detail="That command is too long.")
    r = await asyncio.to_thread(mx_command.run, command)
    lib.log("solve", None, text=("/CUSTOM-Mx " + command)[:300])
    return r


@app.post("/api/tools/solve")
async def tools_solve(req: SolveRequest):
    """Solve any problem step by step: CUSTOM-Mx works it when it can; else sympy pins a bare equation's answer."""
    problem = (req.problem or "").strip()
    if not problem:
        raise HTTPException(status_code=400, detail="Type a problem to solve.")
    if _MX_PREFIX.match(problem):                    # "/CUSTOM-Mx find …" typed in the Solver: the exact language
        r = await asyncio.to_thread(mx_command.run, _MX_PREFIX.sub("", problem))
        lib.log("solve", None, text=problem[:300])

        async def exact():
            ans = re.search(r"\*\*Answer:\*\* (.+)", r["markdown"]) if r["ok"] else None
            if ans:
                yield json.dumps({"verified": ans.group(1), "engine": mathengine.NAME}) + "\n"
            yield json.dumps({"token": r["markdown"]}) + "\n"
            yield json.dumps({"done": True}) + "\n"
        return StreamingResponse(exact(), media_type="application/x-ndjson", headers=_STREAM_HEADERS)
    mx = await asyncio.to_thread(mathengine.solve, problem)
    offer = None if mx else (await _draft_exact(problem))[0]
    verified = ""
    if not mx and not offer:
        try:
            verified = questions.solve_selection(problem) or ""
        except Exception:
            verified = ""
    lib.log("solve", None, text=problem[:300])

    async def gen():
        if offer:                              # a word problem: the student checks the reading before it's worked
            for line in _offer_events(offer):
                yield line
            return
        if mx:
            working = mathengine.working_markdown(mx)
            yield json.dumps({"verified": mx["answer"], "engine": mathengine.NAME}) + "\n"
            yield json.dumps({"token": working + "\n\n"}) + "\n"
            try:
                async with _interactive():
                    async for piece in classroom.explain_working_stream(problem, working):
                        yield json.dumps({"token": piece}) + "\n"
            except Exception:
                pass                           # the working is the answer; the explanation is a bonus
            yield json.dumps({"done": True}) + "\n"
            return
        if verified:
            yield json.dumps({"verified": verified}) + "\n"
        try:
            async with _interactive():
                async for piece in classroom.solve_free_stream(problem, verified):
                    yield json.dumps({"token": piece}) + "\n"
        except local_llm.LocalLLMError as e:
            yield json.dumps({"error": str(e)}) + "\n"
            return
        except Exception as e:
            yield json.dumps({"error": f"Failed to solve: {e}"}) + "\n"
            return
        yield json.dumps({"done": True}) + "\n"

    return StreamingResponse(gen(), media_type="application/x-ndjson", headers=_STREAM_HEADERS)


# ---- frontend -------------------------------------------------------
@app.get("/")
async def root():
    return FileResponse(os.path.join(FRONTEND_DIR, "home.html"))


@app.get("/app")
async def serve_frontend():
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))


@app.get("/sqe")
async def serve_sqe():
    """The SQE window (MrSOLIS 2-AL): maths practice from a question the student brings (CUSTOM-SQE)."""
    return FileResponse(os.path.join(FRONTEND_DIR, "sqe.html"))


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)       # this computer only, never the network
