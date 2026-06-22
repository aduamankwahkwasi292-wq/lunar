import os
import sys
import io
import uuid
import json
import asyncio
import contextlib

# Make the project root importable so `from backend.X import ...` works no
# matter where the server is launched from.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from backend.file_processor import extract_rich_slides, slide_plain_text
from backend import local_llm, classroom, file_processor, questions

app = FastAPI(title="Lunar AI")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
MEDIA_DIR = os.path.join(DATA_DIR, "uploads", "media")
# Slide embeddings for "Find anything" are cached on disk keyed by content hash so
# the same deck is only ever embedded once — instant search on every later open.
EMBED_CACHE_DIR = os.path.join(DATA_DIR, "cache", "embeds")
FRONTEND_DIR = os.environ.get("LUNAR_FRONTEND_DIR") or os.path.join(BUNDLE_DIR, "frontend")
# Static assets (css/js/images) live in frontend/static/; HTML pages in frontend/.
STATIC_DIR = os.path.join(FRONTEND_DIR, "static")
if not os.path.isdir(STATIC_DIR):
    STATIC_DIR = FRONTEND_DIR          # fallback for the old flat layout
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(MEDIA_DIR, exist_ok=True)
os.makedirs(EMBED_CACHE_DIR, exist_ok=True)

# Uploaded documents, keyed by session id.
sessions = {}

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
    """Board-ready view of a slide: a rendered chalk image, or ordered blocks."""
    if not isinstance(slide, dict):
        slide = {"blocks": [{"type": "text", "text": slide or ""}], "text": slide or "",
                 "links": [], "examinable": True}

    # PDF / image slides render the real page as a chalk-on-board image.
    if slide.get("board"):
        if slide.get("blank"):
            return {"title": _slide_title(slide), "blank": True, "examinable": False}
        grounding = (classroom.clean_board_text(slide.get("text", "")) + " " +
                     (slide.get("ocr", "") or "")).strip()
        return {
            "title": _slide_title(slide),
            "image": f"/api/classroom/slide_image/{session_id}/{idx}",
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
    """Warm the PDF→chalk render stack in the background so the first slide is fast."""
    import threading
    threading.Thread(target=file_processor.warm_render, daemon=True).start()


_render_locks = {}


async def _ensure_board_image(session_id: str, idx: int):
    """Render+cache a board slide's chalk image if missing; return its path or None.

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
    out = os.path.join(media_dir, f"board_{idx}.png")
    if os.path.isfile(out):
        return out
    lock = _render_locks.setdefault((session_id, idx), asyncio.Lock())
    async with lock:
        if os.path.isfile(out):          # rendered while we waited on the lock
            return out
        if slide.get("board") == "pdf":
            await asyncio.to_thread(file_processor.render_pdf_page_chalk,
                                    session["file_path"], slide.get("page", idx), out)
        elif slide.get("board") == "image":
            await asyncio.to_thread(file_processor.render_image_chalk, session["file_path"], out)
    return out if os.path.isfile(out) else None


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
    session_id = str(uuid.uuid4())
    file_ext = os.path.splitext(file.filename)[1] if file.filename else ""
    file_path = os.path.join(UPLOAD_DIR, f"{session_id}{file_ext}")

    with open(file_path, "wb") as f:
        f.write(await file.read())

    # One pass: verbatim text + inline media (figures/video) + links per slide.
    media_dir = os.path.join(MEDIA_DIR, session_id)
    slides = extract_rich_slides(file_path, media_dir)
    extracted_text = "\n\n".join(slide_plain_text(s) for s in slides)

    if not slides or not extracted_text.strip():
        return {
            "session_id": session_id,
            "filename": file.filename,
            "text_preview": extracted_text or "No text could be extracted.",
            "warning": "Limited or no text extracted. The file may be an unsupported format or empty.",
        }

    sessions[session_id] = {
        "filename": file.filename,
        "file_path": file_path,
        "media_dir": media_dir,
        "text": extracted_text,
        "slides": slides,
        "slide_index": 0,
    }

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
        "filename": file.filename,
        "text_preview": preview,
        "text_length": len(extracted_text),
        "slides": len(slides),
    }


# ---- board slide image (PDF page / image, recolored to chalk) -------
@app.get("/api/classroom/slide_image/{session_id}/{idx}")
async def slide_image(session_id: str, idx: int):
    """Render (and cache) the chalk-on-board image for one slide, on demand."""
    if not sessions.get(session_id):
        raise HTTPException(status_code=404, detail="Session not found.")
    try:
        out = await _ensure_board_image(session_id, idx)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not render slide: {e}")
    if not out:
        raise HTTPException(status_code=404, detail="This slide has no board image.")
    return FileResponse(out)


@app.get("/api/classroom/slide_text/{session_id}/{idx}")
async def slide_text(session_id: str, idx: int):
    """Word boxes for a PDF board slide so the real slide is selectable on the board.

    Returns {"words": [{x,y,w,h,t}, ...]} as page fractions (0..1). Non-PDF or
    text-free slides simply return an empty list — the slide image stays put,
    there's just nothing to highlight on it.
    """
    session = sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")
    slides = session.get("slides") or []
    if idx < 0 or idx >= len(slides):
        return {"words": []}
    slide = slides[idx]
    if not isinstance(slide, dict) or slide.get("board") != "pdf" or slide.get("blank"):
        return {"words": []}
    cache = session.setdefault("_slide_words", {})
    if idx in cache:
        return {"words": cache[idx]}
    try:
        # One span per text LINE (not per word) so selection follows whole lines and
        # doesn't bleed into the lines above/below when grabbing a sentence.
        words = await asyncio.to_thread(
            file_processor.pdf_page_lines, session["file_path"], slide.get("page", idx))
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
    session = sessions.get(session_id)
    media_dir = session.get("media_dir") if session else os.path.join(MEDIA_DIR, session_id)
    path = os.path.normpath(os.path.join(media_dir, filename))
    if not path.startswith(os.path.normpath(media_dir)) or not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Media not found.")
    return FileResponse(path)


# ---- classroom ------------------------------------------------------
@app.post("/api/classroom/start")
async def classroom_start(req: ClassroomStartRequest):
    """Return the slide count + short titles for the classroom progress bar."""
    session = sessions.get(req.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found. Upload a file first.")
    slides = session.get("slides") or []
    session["slide_index"] = 0
    return {"count": len(slides), "titles": [_slide_title(s) for s in slides]}


@app.post("/api/classroom/teach_stream")
async def classroom_teach_stream(req: TeachRequest):
    """Stream Lunar teaching one slide (tokens written live to the board)."""
    session = sessions.get(req.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found. Upload a file first.")
    slides = session.get("slides") or []
    if not slides:
        raise HTTPException(status_code=400, detail="This document has no slides to teach.")
    idx = max(0, min(req.slide_index, len(slides) - 1))
    session["slide_index"] = idx

    slide = slides[idx]
    grounding = _grounding_text(slide)
    payload = _slide_payload(req.session_id, slide, idx)

    async def gen():
        # 1) For board slides, render the chalk image NOW (CPU is free here) so
        # it's cached before the note generation pins all cores — otherwise the
        # render competes with the LLM and the board sits blank for seconds.
        if payload.get("image"):
            try:
                await _ensure_board_image(req.session_id, idx)
            except Exception:
                pass
        # The verbatim board: a chalk slide image, or ordered text blocks.
        yield json.dumps({"slide": payload}) + "\n"
        # 2) Lunar's grounded explanation under it (only if examinable).
        if payload.get("examinable") and grounding.strip():
            try:
                async with _interactive():
                    async for piece in classroom.teach_slide_stream(grounding, idx + 1, len(slides)):
                        yield json.dumps({"token": piece}) + "\n"
            except local_llm.LocalLLMError as e:
                yield json.dumps({"error": str(e)}) + "\n"
                return
            except Exception as e:
                yield json.dumps({"error": f"Failed to teach slide: {e}"}) + "\n"
                return
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
    session = sessions.get(req.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found. Upload a file first.")
    slides = session.get("slides") or []
    idx = max(0, min(req.slide_index, len(slides) - 1)) if slides else 0
    slide_text = _grounding_text(slides[idx]) if slides else session.get("text", "")

    async def gen():
        try:
            async with _interactive():
                async for piece in classroom.chat_stream(slide_text, req.message, req.history):
                    yield json.dumps({"token": piece}) + "\n"
        except local_llm.LocalLLMError as e:
            yield json.dumps({"error": str(e)}) + "\n"
            return
        except Exception as e:
            yield json.dumps({"error": f"Failed to respond: {e}"}) + "\n"
            return
        yield json.dumps({"done": True}) + "\n"

    return StreamingResponse(gen(), media_type="application/x-ndjson", headers=_STREAM_HEADERS)


@app.post("/api/classroom/explain")
async def classroom_explain(req: ExplainRequest):
    """Explain (or solve) the portion the student highlighted on the board."""
    session = sessions.get(req.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found. Upload a file first.")
    slides = session.get("slides") or []
    idx = max(0, min(req.slide_index, len(slides) - 1)) if slides else 0
    slide_text = _grounding_text(slides[idx]) if slides else session.get("text", "")
    mode = "solve" if req.mode == "solve" else "explain"

    async def gen():
        try:
            async with _interactive():
                async for piece in classroom.explain_stream(slide_text, req.selection, mode):
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
    session = sessions.get(req.session_id)
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


# ---- frontend -------------------------------------------------------
@app.get("/")
async def root():
    return FileResponse(os.path.join(FRONTEND_DIR, "home.html"))


@app.get("/app")
async def serve_frontend():
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
