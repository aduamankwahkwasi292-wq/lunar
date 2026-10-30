"""
Document text extraction for Lunar AI.

Handles the common case the user cares about most: slides that are really just
images. Native text is extracted where present, and OCR (RapidOCR, ONNX, fully
bundled — no Tesseract/Poppler system install needed) is used for:

  * standalone image files,
  * image-only / scanned PDF pages (drawn by MrSOLIS's own PDF layer, backend/pdf.py, on PDFium), and
  * pictures embedded inside PowerPoint slides.
"""

import io
import os
import sys
import threading

# Minimum characters a PDF page / image must yield before we trust the native
# text layer; below this we fall back to OCR.
_MIN_NATIVE_CHARS = 16

_ocr_engine = None
_ocr_lock = threading.Lock()
_ocr_available = True


def extract_text_from_file(file_path: str) -> str:
    """Extract text content from various file types."""
    ext = os.path.splitext(file_path)[1].lower()

    try:
        if ext == '.pdf':
            return _extract_pdf(file_path)
        elif ext in ('.docx', '.doc'):
            return _extract_docx(file_path)
        elif ext in ('.pptx', '.ppt'):
            return _extract_pptx(file_path)
        elif ext == '.xlsx':
            return _extract_xlsx(file_path)
        elif ext == '.csv':
            return _extract_csv(file_path)
        elif ext in ('.txt', '.md', '.log', '.py', '.js', '.html', '.css', '.json',
                      '.xml', '.yaml', '.yml', '.ini', '.cfg', '.env', '.sh', '.bat',
                      '.c', '.cpp', '.h', '.java', '.rb', '.go', '.rs', '.ts', '.tsx',
                      '.jsx', '.sql', '.r', '.m', '.swift', '.kt', '.scala'):
            return _extract_text(file_path)
        elif ext in ('.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.gif', '.webp'):
            return _extract_image(file_path)
        else:
            return _extract_text(file_path)
    except Exception as e:
        return f"[Error extracting text from {os.path.basename(file_path)}: {str(e)}]"


# ======================================================================
# OCR engine (RapidOCR / ONNX) — lazy, bundled, offline
# ======================================================================
def _get_ocr():
    """Lazily build the RapidOCR engine; returns None if it can't be loaded."""
    global _ocr_engine, _ocr_available
    if _ocr_engine is not None or not _ocr_available:
        return _ocr_engine
    with _ocr_lock:
        if _ocr_engine is None and _ocr_available:
            try:
                from rapidocr_onnxruntime import RapidOCR
                _ocr_engine = RapidOCR()
            except Exception:
                _ocr_available = False
                _ocr_engine = None
    return _ocr_engine


def _ocr_image_obj(image) -> str:
    """Run OCR on a PIL image (or path). Returns recognized text, or ''."""
    engine = _get_ocr()
    if engine is None:
        return _ocr_with_tesseract(image)
    try:
        import numpy as np
        from PIL import Image

        if not isinstance(image, Image.Image):
            image = Image.open(image)
        arr = np.array(image.convert("RGB"))
        result, _elapse = engine(arr)
        if not result:
            return ""
        # result rows are [box, text, score]
        return "\n".join(row[1] for row in result if len(row) > 1 and row[1]).strip()
    except Exception:
        return _ocr_with_tesseract(image)


def _ocr_with_tesseract(image) -> str:
    """Optional fallback if RapidOCR is unavailable but Tesseract is installed."""
    try:
        import pytesseract
        from PIL import Image
        if not isinstance(image, Image.Image):
            image = Image.open(image)
        return (pytesseract.image_to_string(image) or "").strip()
    except Exception:
        return ""


# ======================================================================
# Per-format extractors
# ======================================================================
def _extract_pdf(file_path: str) -> str:
    """Extract PDF text; OCR any page whose native text layer is empty/sparse."""
    text_parts = []
    native_by_page = []
    try:
        import PyPDF2
        with open(file_path, 'rb') as f:
            reader = PyPDF2.PdfReader(f)
            for page in reader.pages:
                native_by_page.append((page.extract_text() or "").strip())
    except ImportError:
        native_by_page = []
    except Exception:
        native_by_page = []

    # Rasterize + OCR pages that have little or no native text.
    rasterizer = _open_pdf_for_render(file_path)
    for idx, native in enumerate(native_by_page or []):
        if len(native) >= _MIN_NATIVE_CHARS:
            text_parts.append(native)
        elif rasterizer is not None:
            ocr_text = _ocr_pdf_page(rasterizer, idx)
            text_parts.append(ocr_text or native)
        else:
            text_parts.append(native)

    # PyPDF2 unavailable but we can still render: OCR the whole document.
    if not native_by_page and rasterizer is not None:
        for idx in range(rasterizer.page_count):
            text_parts.append(_ocr_pdf_page(rasterizer, idx))

    if rasterizer is not None:
        try:
            rasterizer.close()
        except Exception:
            pass

    combined = "\n".join(p for p in text_parts if p).strip()
    if combined:
        return combined
    if not native_by_page and rasterizer is None:
        return "[Could not read this PDF.]"
    return combined


def _open_pdf_for_render(file_path: str):
    """The PDF opened with MrSOLIS's own PDF layer (backend/pdf.py, PDFium), or None."""
    try:
        from backend import pdf
        return pdf.Doc(file_path)
    except Exception:
        return None


def _ocr_pdf_page(doc, page_index: int, dpi: int = 200) -> str:
    """Render a single PDF page to an image and OCR it."""
    try:
        return _ocr_image_obj(doc.render(page_index, dpi))
    except Exception:
        return ""


def _extract_docx(file_path: str) -> str:
    try:
        from docx import Document
        doc = Document(file_path)
        return '\n'.join([para.text for para in doc.paragraphs if para.text.strip()])
    except ImportError:
        return "[python-docx not installed. Install with: pip install python-docx]"


def _extract_pptx(file_path: str) -> str:
    """Extract slide text boxes AND OCR any pictures embedded in the slides."""
    try:
        from pptx import Presentation
        from pptx.enum.shapes import MSO_SHAPE_TYPE
    except ImportError:
        return "[python-pptx not installed. Install with: pip install python-pptx]"

    prs = Presentation(file_path)
    text_parts = []
    for slide in prs.slides:
        for shape in slide.shapes:
            # Native text in text boxes / placeholders.
            if hasattr(shape, "text") and shape.text and shape.text.strip():
                text_parts.append(shape.text.strip())
            # OCR pictures (image-based slides).
            try:
                if shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
                    from PIL import Image
                    blob = shape.image.blob
                    ocr_text = _ocr_image_obj(Image.open(io.BytesIO(blob)))
                    if ocr_text:
                        text_parts.append(ocr_text)
            except Exception:
                pass
    return '\n'.join(text_parts)


def _extract_xlsx(file_path: str) -> str:
    try:
        import openpyxl
        wb = openpyxl.load_workbook(file_path, data_only=True)
        text_parts = []
        for sheet in wb.worksheets:
            for row in sheet.iter_rows(values_only=True):
                row_text = ' '.join([str(cell) for cell in row if cell is not None])
                if row_text.strip():
                    text_parts.append(row_text)
        return '\n'.join(text_parts)
    except ImportError:
        return "[openpyxl not installed. Install with: pip install openpyxl]"


def _extract_csv(file_path: str) -> str:
    import csv
    text_parts = []
    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
        reader = csv.reader(f)
        for row in reader:
            text_parts.append(' '.join(row))
    return '\n'.join(text_parts)


def _extract_text(file_path: str) -> str:
    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
        return f.read()


def _extract_image(file_path: str) -> str:
    text = _ocr_image_obj(file_path)
    return text if text else "[No text found in image]"


# ======================================================================
# Slide-by-slide extraction (for the classroom: one board lesson per slide)
# ======================================================================
import re as _re


def extract_slides(file_path: str) -> list:
    """Split a document into its real slides/pages.

    Returns a list of slide texts (one per PPTX slide / PDF page / image),
    or an auto-split into slide-sized sections for plain documents. Empty
    slides are dropped.
    """
    ext = os.path.splitext(file_path)[1].lower()
    try:
        if ext in ('.pptx', '.ppt'):
            slides = _pptx_slides(file_path)
        elif ext == '.pdf':
            slides = _pdf_slides(file_path)
        elif ext in ('.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.gif', '.webp'):
            slides = [_extract_image(file_path)]
        else:
            slides = _autosplit(extract_text_from_file(file_path))
    except Exception as e:  # noqa: BLE001
        slides = _autosplit(f"[Error reading {os.path.basename(file_path)}: {e}]")

    cleaned = [s.strip() for s in slides if s and s.strip() and not s.strip().startswith("[")]
    return cleaned or [s.strip() for s in slides if s and s.strip()]


def _pptx_slides(file_path: str) -> list:
    try:
        from pptx import Presentation
        from pptx.enum.shapes import MSO_SHAPE_TYPE
    except ImportError:
        return _autosplit(_extract_pptx(file_path))

    prs = Presentation(file_path)
    slides = []
    for slide in prs.slides:
        parts = []
        for shape in slide.shapes:
            if hasattr(shape, "text") and shape.text and shape.text.strip():
                parts.append(shape.text.strip())
            try:
                if shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
                    from PIL import Image
                    ocr = _ocr_image_obj(Image.open(io.BytesIO(shape.image.blob)))
                    if ocr:
                        parts.append(ocr)
            except Exception:
                pass
        slides.append("\n".join(parts))
    return slides


def _pdf_slides(file_path: str) -> list:
    native = []
    try:
        import PyPDF2
        with open(file_path, 'rb') as f:
            reader = PyPDF2.PdfReader(f)
            native = [(p.extract_text() or "").strip() for p in reader.pages]
    except Exception:
        native = []

    rasterizer = _open_pdf_for_render(file_path)
    pages = []
    page_count = len(native) if native else (rasterizer.page_count if rasterizer else 0)
    for idx in range(page_count):
        text = native[idx] if idx < len(native) else ""
        if len(text) < _MIN_NATIVE_CHARS and rasterizer is not None:
            text = _ocr_pdf_page(rasterizer, idx) or text
        pages.append(text)
    if rasterizer is not None:
        try:
            rasterizer.close()
        except Exception:
            pass
    return pages or _autosplit(_extract_pdf(file_path))


def _autosplit(text: str, target: int = 850) -> list:
    """Split plain text into slide-sized sections respecting natural breaks."""
    text = (text or "").strip()
    if not text:
        return []

    # Explicit page breaks (form feed) from PDF-style extraction.
    if "\f" in text:
        parts = [p.strip() for p in text.split("\f") if p.strip()]
        if len(parts) > 1:
            return parts

    # Explicit "Slide N" / "Page N" / "Section N" markers.
    marked = _re.split(r"\n(?=(?:slide|page|section|chapter|topic|unit)\s*\d+\b)", text, flags=_re.I)
    if len(marked) > 1:
        return [m.strip() for m in marked if m.strip()]

    # Otherwise pack paragraphs up to ~target chars.
    paras = [p.strip() for p in _re.split(r"\n\s*\n", text) if p.strip()] or [text]
    slides, buf = [], ""
    for p in paras:
        if buf and len(buf) + len(p) + 2 > target:
            slides.append(buf)
            buf = p
        else:
            buf = f"{buf}\n\n{p}".strip() if buf else p
    if buf:
        slides.append(buf)
    return slides


# ======================================================================
# Rich slide extraction — verbatim text + inline media (images / video) +
# links, as ordered "blocks" the classroom board renders in slide order.
# Each slide is:
#   {"title": str,
#    "blocks": [ {"type":"text","text":..}
#              | {"type":"image","src":<filename>,"alt":..}
#              | {"type":"video","src":<filename>} ],
#    "text":  "<verbatim text only>",   # what gets typed on the board
#    "ocr":   "<text recognised inside figures>",  # grounding only
#    "links": [ {"text":.., "url":..} ],
#    "examinable": bool }
# `src` is a bare filename inside media_dir; the web layer maps it to a URL.
# ======================================================================

# A picture covering more than this fraction of the whole slide/page is a
# full-slide scan: we OCR it to text rather than pasting the slide as an
# image (the user explicitly does not want the slide dumped as a picture).
_FULLSLIDE_IMG_FRAC = 0.7


def extract_rich_slides(file_path: str, media_dir: str) -> list:
    """Split a document into slides.

    PDFs and images become "board" slides: the page is rendered (lazily, on
    demand) as an image in its own colours, so it shows on the board exactly as in
    the file — perfect math symbols / figures / number lines; native text is kept only for
    grounding. PowerPoint decks become board slides too when an office suite on the computer can
    draw them (see office_to_pdf); otherwise they keep the verbatim text+figure blocks.
    """
    try:
        os.makedirs(media_dir, exist_ok=True)
    except Exception:
        pass
    ext = os.path.splitext(file_path)[1].lower()
    try:
        if ext in ('.pptx', '.ppt'):
            # the real slides: drawn by PowerPoint / WPS / LibreOffice if the computer has one, else by
            # MrSOLIS itself (pptx_render); text and pictures only as a last resort
            slides = _ppt_board_slides(file_path) or _pptx_drawn_slides(file_path) or _pptx_rich(file_path, media_dir)
        elif ext == '.pdf':
            slides = _pdf_slides_meta(file_path)
        elif ext in ('.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.gif', '.webp'):
            slides = _image_slide_meta(file_path)
        else:
            slides = _text_rich(extract_text_from_file(file_path))
    except Exception as e:  # noqa: BLE001
        slides = _text_rich(f"[Error reading {os.path.basename(file_path)}: {e}]")

    cleaned = []
    for s in slides:
        if (s.get("text") or "").strip() or s.get("blocks") or s.get("board"):
            s.setdefault("title", _first_line(s.get("text", "")))
            cleaned.append(s)
    return cleaned


# ----- board slides: render the real page, in its own colours -----
def _page_links(doc, pi) -> list:
    links = []
    try:
        for uri in doc.links(pi):
            links.append({"text": uri, "url": uri})
    except Exception:
        pass
    return _dedupe_links(links)


def _pdf_slides_meta(file_path: str) -> list:
    """One board slide per PDF page: native text (grounding) + lazy colour render."""
    doc = _open_pdf_for_render(file_path)
    if doc is None:
        return _text_rich(_extract_pdf(file_path))
    out = []
    try:
        for pi in range(doc.page_count):
            text = doc.text(pi)
            # Blank page: nothing but maybe a page number, no images, no real
            # drawings. Cheap native check (no render) so we can tell the user.
            compact = _re.sub(r"\s+", "", text)
            page_num_only = bool(_re.fullmatch(r"\d{1,4}", compact or ""))
            has_content = len(compact) > 2 and not page_num_only
            try:
                objs = doc.objects(pi)
                n_draw, n_img = len(objs["paths"]), len(objs["images"])
            except Exception:
                n_draw, n_img = 0, 0
            blank = (not has_content) and n_img == 0 and n_draw <= 2
            out.append({
                "board": "pdf", "page": pi,
                "text": text, "ocr": "",
                "links": _page_links(doc, pi),
                "examinable": True,
                "blank": blank,
                "title": _first_line(text) or f"Slide {pi + 1}",
            })
    finally:
        try:
            doc.close()
        except Exception:
            pass
    return out


def _image_slide_meta(file_path: str) -> list:
    """A single image file becomes one board slide (shown as it is), OCR for grounding."""
    ocr = _ocr_image_obj(file_path) or ""
    return [{
        "board": "image", "page": 0,
        "text": ocr, "ocr": ocr, "links": [],
        "examinable": True,
        "title": _first_line(ocr) or "Slide",
    }]


_MAX_SIDE = 2200          # big phone photos are scaled down to this (longest side), plenty for the board


def render_pdf_page(file_path: str, page_index: int, out_path: str, dpi: int = 130) -> str:
    """Render a PDF page to a PNG at out_path, in its own colours — exactly as it looks in the file."""
    from backend import pdf
    with pdf.Doc(file_path) as doc:
        doc.render(page_index, dpi).save(out_path, format="PNG", compress_level=1)     # RGB, white paper
    return out_path


def slide_has_figure(file_path: str, slide: dict) -> bool:
    """Does this board slide hold a picture, chart or drawn diagram worth *looking* at?

    Looking at a slide costs a brain that sees ~15 s on a laptop CPU, so text-only
    slides are taught from their words alone. Small pictures (logos, icons) don't count.
    """
    board = slide.get("board")
    if board == "image":
        return True
    try:
        if board == "pdf":
            from backend import pdf
            with pdf.Doc(ppt_render_path(file_path)) as doc:
                objs = doc.objects(slide.get("page", 0))
            w, h = objs["size"]
            area = (w * h) or 1
            if any(pdf.area(b) / area > 0.06 for b in objs["images"]):
                return True
            drawn = [b for b in objs["paths"] if pdf.area(b) / area > 0.0005]
            return len(drawn) >= 12                        # a chart, circuit or diagram drawn in lines
        if board == "pptx":
            from pptx import Presentation
            prs = Presentation(file_path)
            every = list(prs.slides)                       # "page" counts hidden slides too
            sl = every[slide.get("page", 0)] if slide.get("page", 0) < len(every) else None
            if sl is None:
                return False
            area = (prs.slide_width or 1) * (prs.slide_height or 1)
            for sh in sl.shapes:
                big = (sh.width or 0) * (sh.height or 0) / area > 0.06
                if big and (sh.shape_type in (3, 6, 13) or getattr(sh, "has_chart", False)
                            or sh._element.find(".//{*}relIds") is not None):   # picture, chart, group, SmartArt
                    return True
    except Exception:
        return False
    return False


def pdf_page_words(file_path: str, page_index: int) -> list:
    """Word boxes for a PDF page as fractions of the page (for a selectable text layer).

    Returns a reading-ordered list of {x, y, w, h, t} where x/y/w/h are 0..1
    fractions of the page width/height, so the frontend can overlay an invisible,
    selectable <span> per word on top of the page image at any display size.
    """
    from backend import pdf
    with pdf.Doc(file_path) as doc:
        pw, ph = doc.size(page_index)
        raw = doc.words(page_index)
    pw, ph = float(pw) or 1.0, float(ph) or 1.0
    # sort by block, line, word so selection follows reading order
    raw.sort(key=lambda w: (w[5], w[6], w[7]))
    out = []
    for x0, y0, x1, y1, text, *_rest in raw:
        t = (text or "").strip()
        if not t:
            continue
        out.append({
            "x": round(x0 / pw, 5), "y": round(y0 / ph, 5),
            "w": round((x1 - x0) / pw, 5), "h": round((y1 - y0) / ph, 5),
            "t": t,
        })
    return out


def pdf_page_lines(file_path: str, page_index: int) -> list:
    """Line boxes for a PDF page as page fractions, for a selectable text layer.

    Groups words into their text lines (one span per line) so the on-screen
    selection follows whole lines cleanly — dragging a sentence no longer bleeds
    into the line above or below the way per-word spans do. Returns reading-ordered
    {x, y, w, h, t} where t is the full line text and x/y/w/h are 0..1 fractions.
    """
    from backend import pdf
    with pdf.Doc(file_path) as doc:
        pw, ph = doc.size(page_index)
        raw = doc.words(page_index)
    pw, ph = float(pw) or 1.0, float(ph) or 1.0
    # group by (block, line); each word tuple is (x0,y0,x1,y1,text,block,line,word)
    groups = {}
    for w in raw:
        if len(w) < 8 or not str(w[4]).strip():
            continue
        key = (w[5], w[6])
        groups.setdefault(key, []).append(w)
    lines = []
    for key in sorted(groups):
        ws = sorted(groups[key], key=lambda w: w[7])
        x0 = min(w[0] for w in ws)
        y0 = min(w[1] for w in ws)
        x1 = max(w[2] for w in ws)
        y1 = max(w[3] for w in ws)
        text = " ".join(str(w[4]) for w in ws).strip()
        if not text:
            continue
        lines.append({
            "x": round(x0 / pw, 5), "y": round(y0 / ph, 5),
            "w": round((x1 - x0) / pw, 5), "h": round((y1 - y0) / ph, 5),
            "t": text,
        })
    return lines


def render_image(src_path: str, out_path: str) -> str:
    """Render an uploaded image to a PNG at out_path, in its own colours (upright, not oversized)."""
    from PIL import Image, ImageOps
    img = ImageOps.exif_transpose(Image.open(src_path))     # phone photos: the way up they were taken
    if img.mode in ("RGBA", "LA", "P"):                       # see-through parts show as white paper
        rgba = img.convert("RGBA")
        img = Image.new("RGB", rgba.size, "white")
        img.paste(rgba, mask=rgba.getchannel("A"))
    else:
        img = img.convert("RGB")
    if max(img.size) > _MAX_SIDE:
        img.thumbnail((_MAX_SIDE, _MAX_SIDE))
    img.save(out_path, format="PNG", compress_level=1)
    return out_path


def warm_render():
    """Pre-import the render stack so the first slide isn't a ~5s cold start.

    The PDF engine + PIL import (and the first render / PNG encode) cost a few seconds
    the first time; doing it once at startup makes every real render fast.
    """
    try:
        import io as _io
        from backend import pdf
        from PIL import Image
        with pdf.new_blank() as doc:
            doc.render(0, 72).save(_io.BytesIO(), format="PNG", compress_level=1)
        Image.new("RGB", (8, 8), "white").save(_io.BytesIO(), format="PNG", compress_level=1)
    except Exception:
        pass


def slide_plain_text(slide) -> str:
    """Combined text used for grounding/quiz (verbatim text + figure OCR)."""
    if isinstance(slide, str):
        return slide
    parts = [slide.get("text", "")]
    if slide.get("ocr"):
        parts.append(slide["ocr"])
    return "\n".join(p for p in parts if p and p.strip()).strip()


def _first_line(text: str) -> str:
    for line in (text or "").splitlines():
        line = line.strip().lstrip("•▪◦●○■□➢➤►▶✓✔-–—*· \t").strip()
        # not a page number or a footer date ("14", "10/18/2026") — slides exported to PDF start with those
        if len(line) >= 3 and not _re.fullmatch(r"[\d\s/.:\-–|]+", line):
            return line[:60]
    return "Slide"


def _save_media(media_dir: str, base_name: str, data: bytes, ext: str):
    """Write media bytes to media_dir; return the bare filename or None."""
    if not data:
        return None
    ext = ext if str(ext).startswith(".") else "." + str(ext)
    fn = f"{base_name}{ext.lower()}"
    try:
        with open(os.path.join(media_dir, fn), "wb") as f:
            f.write(data)
        return fn
    except Exception:
        return None


def _dedupe_links(links: list) -> list:
    seen, out = set(), []
    for l in links or []:
        u = (l or {}).get("url")
        if u and u not in seen:
            seen.add(u)
            out.append(l)
    return out


def _text_rich(text: str) -> list:
    return [
        {"blocks": [{"type": "text", "text": t}], "text": t, "ocr": "",
         "links": [], "examinable": True}
        for t in _autosplit(text)
    ]


# ----- PowerPoint: an office suite on this computer draws the real slides -----
# python-pptx can read a deck's text and pictures but can't draw a slide, so laying them out
# ourselves "mangled" decks (lost positions, backgrounds, shapes, colours). Instead the deck is
# turned into a PDF by PowerPoint (or WPS, or LibreOffice) — exactly what "Save as PDF" makes —
# and that PDF goes through the same board pipeline as any PDF. With no office suite on the
# computer, the old text-and-pictures layout is the fallback.
_PPT_TO_PDF_PS1 = r"""
param([string]$Src, [string]$Dst, [string]$ProgId)
$ErrorActionPreference = 'Stop'
$app = New-Object -ComObject $ProgId
$before = 0
try { $before = $app.Presentations.Count } catch {}
$pres = $null
try {
    $pres = $app.Presentations.Open($Src, -1, 0, 0)     # read-only, keep its name, no window
    $pres.SaveAs($Dst, 32)                               # 32 = PDF
} finally {
    if ($pres) { try { $pres.Close() } catch {} }
    # never close the student's own PowerPoint: quit only if nothing else was open
    try { if ($before -eq 0 -and $app.Presentations.Count -eq 0) { $app.Quit() } } catch {}
    [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($app)
}
"""
_OFFICE_APPS = [("PowerPoint.Application", "PowerPoint"), ("KWPP.Application", "WPS")]


def _com_registered(progid: str) -> bool:
    try:
        import winreg
        winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, progid + "\\CLSID"))
        return True
    except OSError:
        return False


def _ppt_via_com(src: str, dst: str, progid: str, timeout: int) -> bool:
    import subprocess
    import tempfile
    script = os.path.join(tempfile.gettempdir(), "mrsolis_ppt_to_pdf.ps1")
    try:
        with open(script, "w", encoding="utf-8") as f:
            f.write(_PPT_TO_PDF_PS1)
        subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-File", script, os.path.abspath(src), os.path.abspath(dst), progid],
            capture_output=True, timeout=timeout, creationflags=0x08000000)     # no console window
    except Exception:
        return False
    return os.path.isfile(dst) and os.path.getsize(dst) > 0


def _soffice_path():
    import shutil
    found = shutil.which("soffice") or shutil.which("libreoffice")
    if found:
        return found
    for p in (r"C:\Program Files\LibreOffice\program\soffice.exe",
              r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
              "/Applications/LibreOffice.app/Contents/MacOS/soffice"):
        if os.path.isfile(p):
            return p
    return None


def _ppt_via_libreoffice(src: str, dst: str, timeout: int) -> bool:
    import shutil
    import subprocess
    import tempfile
    soffice = _soffice_path()
    if not soffice:
        return False
    out_dir = tempfile.mkdtemp(prefix="mrsolis_lo_")
    profile = tempfile.mkdtemp(prefix="mrsolis_lo_profile_")      # works even while LibreOffice is open
    try:
        subprocess.run(
            [soffice, "--headless", "--norestore", f"-env:UserInstallation=file:///{profile.replace(os.sep, '/')}",
             "--convert-to", "pdf", "--outdir", out_dir, os.path.abspath(src)],
            capture_output=True, timeout=timeout, creationflags=0x08000000 if sys.platform == "win32" else 0)
        made = os.path.join(out_dir, os.path.splitext(os.path.basename(src))[0] + ".pdf")
        if os.path.isfile(made) and os.path.getsize(made) > 0:
            shutil.move(made, dst)
            return True
    except Exception:
        pass
    finally:
        shutil.rmtree(out_dir, ignore_errors=True)
        shutil.rmtree(profile, ignore_errors=True)
    return False


def office_to_pdf(src: str, dst: str, timeout: int = 300):
    """Turn a PowerPoint file into a PDF with an office suite on this computer.
    Returns which one drew it ("PowerPoint", "WPS", "LibreOffice"), or None if there's none.
    LUNAR_NO_OFFICE=1 skips them (MrSOLIS then draws the slides itself — for testing that path)."""
    if os.environ.get("LUNAR_NO_OFFICE"):
        return None
    if sys.platform == "win32":
        for progid, label in _OFFICE_APPS:
            if _com_registered(progid) and _ppt_via_com(src, dst, progid, timeout):
                return label
    if _ppt_via_libreoffice(src, dst, timeout):
        return "LibreOffice"
    return None


def ppt_render_path(file_path: str) -> str:
    """The file a deck's board slides are drawn from: for a PowerPoint deck, its PDF next to it."""
    if os.path.splitext(file_path)[1].lower() in (".pptx", ".ppt"):
        pdf = os.path.splitext(file_path)[0] + ".pdf"
        if os.path.isfile(pdf):
            return pdf
    return file_path


def _pptx_titles_and_notes(file_path: str):
    """Per slide: its title and speaker notes, from the PowerPoint file (the PDF has neither)."""
    try:
        from pptx import Presentation
        prs = Presentation(file_path)
    except Exception:
        return []
    out = []
    for slide in prs.slides:
        if slide._element.get("show") == "0":          # hidden slides aren't in the PDF either
            continue
        title, notes = "", ""
        try:
            if slide.shapes.title is not None:
                title = (slide.shapes.title.text or "").strip()
        except Exception:
            pass
        try:
            if slide.has_notes_slide:
                notes = (slide.notes_slide.notes_text_frame.text or "").strip()
        except Exception:
            pass
        out.append((title, notes))
    return out


def _ppt_board_slides(file_path: str):
    """A PowerPoint deck as real slide images (via an office suite), or None if none is installed."""
    pdf = os.path.splitext(file_path)[0] + ".pdf"
    if not os.path.isfile(pdf) and not office_to_pdf(file_path, pdf):
        return None
    slides = _pdf_slides_meta(pdf)
    extra = _pptx_titles_and_notes(file_path) if file_path.lower().endswith(".pptx") else []
    for s, (title, notes) in zip(slides, extra):
        if title:
            s["title"] = " ".join(title.split())[:60]
        if notes:
            s["text"] = (s.get("text", "") + "\n\nSpeaker notes:\n" + notes).strip()
            s["blank"] = False
    return slides


def _pptx_renderer():
    try:
        from backend import pptx_render
    except ImportError:                     # the frozen app's flat layout
        import pptx_render
    return pptx_render


def _pptx_drawn_slides(file_path: str):
    """A PowerPoint deck MrSOLIS draws itself (pptx_render) — for computers with no office suite.
    Board slides of kind "pptx": the text (for teaching), title, speaker notes and links come from the
    file; a slide that is just a picture is read with OCR. None if the file can't be read as a deck."""
    try:
        pr = _pptx_renderer()
        prs = pr._open(file_path)
    except Exception:
        return None
    A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
    RID = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
    out = []
    for i, slide in enumerate(prs.slides):
        if slide._element.get("show") == "0":          # hidden: not shown in PowerPoint either
            continue
        paras = []
        roots = [slide._element]
        try:                                           # SmartArt keeps its words in its own parts
            from lxml import etree
            for rel in slide.part.rels.values():
                if rel.reltype.endswith("/diagramDrawing"):
                    roots.append(etree.fromstring(rel.target_part.blob))
        except Exception:
            pass
        for root in roots:
            for p in root.iter(A + "p"):
                t = "".join(x.text or "" for x in p.iter(A + "t")).strip()
                if t:
                    paras.append(t)
        text = "\n".join(paras)
        links = []
        for h in slide._element.iter(A + "hlinkClick"):
            rel = slide.part.rels.get(h.get(RID)) if h.get(RID) else None
            if rel is not None and rel.is_external and str(rel.target_ref).startswith(("http", "mailto")):
                links.append({"text": rel.target_ref, "url": rel.target_ref})
        ocr = ""
        if len(text) < 20:                             # a picture of a slide: read it for teaching
            try:
                pics = [sh for sh in slide.shapes if sh.shape_type == 13]
                if pics:
                    from PIL import Image
                    big = max(pics, key=lambda sh: (sh.width or 0) * (sh.height or 0))
                    ocr = _ocr_image_obj(Image.open(io.BytesIO(big.image.blob))) or ""
            except Exception:
                ocr = ""
        title = ""
        try:
            if slide.shapes.title is not None:
                title = " ".join((slide.shapes.title.text or "").split())[:60]
        except Exception:
            pass
        try:
            if slide.has_notes_slide:
                notes = (slide.notes_slide.notes_text_frame.text or "").strip()
                if notes:
                    text = (text + "\n\nSpeaker notes:\n" + notes).strip()
        except Exception:
            pass
        out.append({"board": "pptx", "page": i, "text": text, "ocr": ocr, "links": _dedupe_links(links),
                    "examinable": True, "blank": False,
                    "title": title or (_first_line(text or ocr) if (text or ocr).strip() else f"Slide {len(out) + 1}")})
    return out or None


def render_pptx_slide(file_path: str, index: int, out_png: str) -> list:
    """Draw one slide of a deck (no office suite needed); returns its words for the selectable layer."""
    return _pptx_renderer().render_slide(file_path, index, out_png)


def _pptx_rich(file_path: str, media_dir: str) -> list:
    try:
        from pptx import Presentation
        from pptx.enum.shapes import MSO_SHAPE_TYPE
    except ImportError:
        return _text_rich(_extract_pptx(file_path))
    from PIL import Image

    prs = Presentation(file_path)
    slide_area = float(prs.slide_width or 1) * float(prs.slide_height or 1) or 1.0
    out = []
    for si, slide in enumerate(prs.slides):
        items = []      # (top, left, block)
        ocr_all = []
        links = []
        for shi, shape in enumerate(slide.shapes):
            top = shape.top if shape.top is not None else 0
            left = shape.left if shape.left is not None else 0
            stype = getattr(shape, "shape_type", None)

            # verbatim text + run hyperlinks
            txt = ""
            try:
                if shape.has_text_frame:
                    txt = shape.text_frame.text or ""
                    for para in shape.text_frame.paragraphs:
                        for run in para.runs:
                            try:
                                addr = run.hyperlink.address
                                if addr:
                                    links.append({"text": (run.text or addr).strip(), "url": addr})
                            except Exception:
                                pass
                elif hasattr(shape, "text"):
                    txt = shape.text or ""
            except Exception:
                txt = getattr(shape, "text", "") or ""
            if txt and txt.strip():
                items.append((top, left, {"type": "text", "text": txt.strip()}))

            # pictures (figures) — full-slide scans become text via OCR
            if stype == MSO_SHAPE_TYPE.PICTURE:
                try:
                    blob = shape.image.blob
                    iext = shape.image.ext or "png"
                    frac = 0.0
                    if shape.width and shape.height:
                        frac = (float(shape.width) * float(shape.height)) / slide_area
                    ocr = _ocr_image_obj(Image.open(io.BytesIO(blob))) or ""
                    if frac >= _FULLSLIDE_IMG_FRAC:
                        if ocr:
                            items.append((top, left, {"type": "text", "text": ocr}))
                    else:
                        if ocr:
                            ocr_all.append(ocr)
                        fn = _save_media(media_dir, f"s{si}_p{shi}", blob, iext)
                        if fn:
                            items.append((top, left, {"type": "image", "src": fn, "alt": ocr[:200]}))
                except Exception:
                    pass

        # embedded videos via slide relationships (appended after the text)
        try:
            for rel in slide.part.rels.values():
                rt = (getattr(rel, "reltype", "") or "").lower()
                if "video" in rt or ("media" in rt and "image" not in rt):
                    try:
                        part = rel.target_part
                        pn = str(getattr(part, "partname", "media.mp4"))
                        vext = os.path.splitext(pn)[1] or ".mp4"
                        fn = _save_media(media_dir, f"s{si}_v{abs(hash(pn)) % 100000}", part.blob, vext)
                        if fn:
                            items.append((10 ** 9, 0, {"type": "video", "src": fn}))
                    except Exception:
                        pass
        except Exception:
            pass

        items.sort(key=lambda t: (t[0], t[1]))
        blocks = [b for _, _, b in items]
        text_only = "\n".join(b["text"] for b in blocks if b["type"] == "text")
        out.append({
            "blocks": blocks,
            "text": text_only,
            "ocr": "\n".join(ocr_all),
            "links": _dedupe_links(links),
            "examinable": True,
        })
    return out


def _image_rich(file_path: str, media_dir: str) -> list:
    ocr = _ocr_image_obj(file_path) or ""
    blocks = []
    fn = None
    try:
        with open(file_path, "rb") as f:
            data = f.read()
        iext = os.path.splitext(file_path)[1].lstrip(".") or "png"
        fn = _save_media(media_dir, "img0", data, iext)
    except Exception:
        fn = None
    if ocr:
        blocks.append({"type": "text", "text": ocr})
    if fn:
        blocks.append({"type": "image", "src": fn, "alt": ocr[:200]})
    return [{"blocks": blocks, "text": ocr, "ocr": ocr, "links": [], "examinable": True}]
