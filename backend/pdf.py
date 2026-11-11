"""
MrSOLIS's own PDF layer, on Google's PDFium (the engine inside Chrome) through pypdfium2 — both
permissively licensed (BSD-3-Clause / Apache-2.0), so a paid MrSOLIS can ship it.

It replaced PyMuPDF on 2026-10-26: PyMuPDF is AGPL-3.0 (or a paid Artifex licence), which would have made the
whole app AGPL. Code ported from PyMuPDF would carry the same licence, so nothing here is based on it — this
is the small set of jobs MrSOLIS needs, written on PDFium's own calls:
  page count and size, the page's text, its words and lines with boxes (the selectable layer and box-select),
  where its pictures and drawn shapes are (is there a figure? is the page blank?), its links, and drawing
  the page as a picture (the board, OCR of scanned pages, the brain's look at a slide).

Boxes use the top-left origin and PDF points (1/72 inch), like the rest of MrSOLIS; PDFium's own are bottom-left.
"""

import threading

import pypdfium2 as pdfium
import pypdfium2.raw as raw

_LOCK = threading.Lock()        # PDFium is not thread-safe: one call into it at a time across the backend


class Doc:
    """An open PDF. Use as `with Doc(path) as d:` — pages are 0-based."""

    def __init__(self, path):
        with _LOCK:
            self._pdf = pdfium.PdfDocument(path)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        with _LOCK:
            if self._pdf is not None:
                self._pdf.close()
                self._pdf = None

    @property
    def pages(self) -> int:
        return len(self._pdf)

    page_count = pages

    def _page(self, i):
        return self._pdf[max(0, min(i, len(self._pdf) - 1))]

    def size(self, i) -> tuple:
        with _LOCK:
            return tuple(self._page(i).get_size())

    def text(self, i) -> str:
        """The page's text in reading order, lines separated by newlines."""
        with _LOCK:
            tp = self._page(i).get_textpage()
            try:
                return tp.get_text_range().replace("\r\n", "\n").replace("\r", "\n").strip()
            finally:
                tp.close()

    def words(self, i) -> list:
        """[(x0, y0, x1, y1, text, block, line, word)] in reading order — the shape MrSOLIS's text layer uses.

        Built from PDFium's character boxes: a word ends at a space or a gap wider than a third of the letter
        height; a line ends where PDFium breaks the line or the baseline moves; a block ends at a gap of more
        than a line between lines."""
        with _LOCK:
            page = self._page(i)
            height = page.get_size()[1]
            ox, oy = _origin(page)
            tp = page.get_textpage()
            try:
                chars = []
                for k in range(tp.count_chars()):
                    ch = chr(raw.FPDFText_GetUnicode(tp.raw, k) or 32)
                    left, bottom, right, top = tp.get_charbox(k, loose=True)   # font-height boxes: lines select cleanly
                    chars.append((ch, (left - ox, bottom - oy, right - ox, top - oy)))
            finally:
                tp.close()
        return _group(chars, height)

    def objects(self, i) -> dict:
        """Where the page's pictures and drawn shapes are: {"images": [boxes], "paths": [boxes], "size": (w, h)}."""
        with _LOCK:
            page = self._page(i)
            w, h = page.get_size()
            ox, oy = _origin(page)
            images, paths = [], []
            for o in page.get_objects(max_depth=3):
                if o.type not in (raw.FPDF_PAGEOBJ_IMAGE, raw.FPDF_PAGEOBJ_PATH):
                    continue
                left, bottom, right, top = o.get_bounds()
                left, bottom, right, top = left - ox, bottom - oy, right - ox, top - oy
                box = (max(0.0, left), max(0.0, h - top), min(w, right), min(h, h - bottom))
                if box[2] > box[0] and box[3] > box[1]:
                    (images if o.type == raw.FPDF_PAGEOBJ_IMAGE else paths).append(box)
            return {"images": images, "paths": paths, "size": (w, h)}

    def links(self, i) -> list:
        """The web addresses the page links to: its link annotations, and web addresses written in its text
        (http, https, www — not e-mail addresses, which a lecturer's title slide is full of)."""
        import ctypes
        out = []
        with _LOCK:
            page = self._page(i)
            pos, link = ctypes.c_int(0), raw.FPDF_LINK()
            while raw.FPDFLink_Enumerate(page.raw, ctypes.byref(pos), ctypes.byref(link)):
                action = raw.FPDFLink_GetAction(link)
                if action and raw.FPDFAction_GetType(action) == raw.PDFACTION_URI:
                    n = raw.FPDFAction_GetURIPath(self._pdf.raw, action, None, 0)
                    if n > 1:
                        buf = (ctypes.c_char * n)()
                        raw.FPDFAction_GetURIPath(self._pdf.raw, action, buf, n)
                        out.append(bytes(buf)[: n - 1].decode("utf-8", "replace"))
            tp = page.get_textpage()
            try:
                wl = raw.FPDFLink_LoadWebLinks(tp.raw)
                try:
                    for k in range(raw.FPDFLink_CountWebLinks(wl)):
                        n = raw.FPDFLink_GetURL(wl, k, None, 0)
                        if n > 1:
                            buf = (ctypes.c_ushort * n)()
                            raw.FPDFLink_GetURL(wl, k, buf, n)
                            url = bytes(buf)[: (n - 1) * 2].decode("utf-16-le", "replace")
                            if url.lower().startswith(("http://", "https://", "www.")):
                                out.append(url)
                finally:
                    raw.FPDFLink_CloseWebLinks(wl)
            finally:
                tp.close()
        seen, uniq = set(), []
        for u in out:
            if u and u not in seen:
                seen.add(u)
                uniq.append(u)
        return uniq

    def render(self, i, dpi: int = 130):
        """The page drawn as an RGB picture (PIL), in its own colours on white paper."""
        with _LOCK:
            bitmap = self._page(i).render(scale=dpi / 72, fill_color=(255, 255, 255, 255))
            return bitmap.to_pil().convert("RGB")


def _origin(page) -> tuple:
    """The lower-left corner of the page as drawn. PDFium draws a page from its crop box (the media box when there is
    none) and measures it from that corner, but gives text and object positions in the PDF's own space — and a book's
    pages often don't start at 0,0. The student's 1118-page textbook starts at (42, 43.3): every word box was 6.9 % of
    the page too far right and 5.7 % too high, so a box drawn round "Find the negation of the proposition" picked the
    words two lines below (2026-11-11). Slide decks start at 0,0, which is why it went unseen."""
    left, bottom, _right, _top = page.get_cropbox()
    return left, bottom


def area(box) -> float:
    """A shape's area for "is this a drawing?" — a straight line (thinner than 2.5 pt) counts as none, as in the
    old PyMuPDF rule; PDFium draws each table border as its own line, which made tables look like diagrams."""
    w, h = box[2] - box[0], box[3] - box[1]
    return 0.0 if min(w, h) < 2.5 else w * h


def new_blank(width=40, height=40):
    """A one-page blank PDF in memory (to warm the engine up at start-up)."""
    with _LOCK:
        pdf = pdfium.PdfDocument.new()
        pdf.new_page(width, height)
    d = Doc.__new__(Doc)
    d._pdf = pdf
    return d


# ── words and lines from character boxes ─────────────────────────────────
def _group(chars, page_height):
    """PDFium characters [(char, (left, bottom, right, top))] -> words with (block, line, word) numbers."""
    words, cur, line_no, block_no, word_no = [], None, 0, 0, 0
    line_box = None                                  # (top, bottom, last right edge, letter height) of this line

    def finish():
        nonlocal cur, word_no
        if cur and cur["t"].strip():
            words.append((cur["x0"], cur["y0"], cur["x1"], cur["y1"], cur["t"], block_no, line_no, word_no))
            word_no += 1
        cur = None

    for ch, (left, bottom, right, top) in chars:
        if ch in "\r\n":
            finish()
            if line_box is not None:
                line_box = (line_box[0], line_box[1], -1e9, line_box[3])     # a new line starts at the next letter
            continue
        y0, y1 = page_height - top, page_height - bottom
        hgt = max(1.0, y1 - y0)
        if ch.isspace() or right <= left:
            finish()
            continue
        if line_box is not None:
            ltop, lbot, last_right, lh = line_box
            mid = (y0 + y1) / 2
            same_line = ltop - 0.4 * lh <= mid <= lbot + 0.4 * lh and left > last_right - 0.5 * lh
            if not same_line:
                finish()
                gap = y0 - lbot
                if gap > 1.0 * max(lh, hgt) or y1 < ltop - 0.2 * lh:           # a paragraph gap, or back up the page
                    block_no += 1
                    line_no = 0
                else:
                    line_no += 1
                word_no = 0
                line_box = (y0, y1, right, hgt)
            else:
                if cur and left - cur["x1"] > 0.33 * max(hgt, lh):            # a gap wider than a third of a letter
                    finish()
                line_box = (min(ltop, y0), max(lbot, y1), right, max(lh, hgt))
        else:
            line_box = (y0, y1, right, hgt)
        if cur is None:
            cur = {"x0": left, "y0": y0, "x1": right, "y1": y1, "t": ch}
        else:
            cur["x0"], cur["y0"] = min(cur["x0"], left), min(cur["y0"], y0)
            cur["x1"], cur["y1"] = max(cur["x1"], right), max(cur["y1"], y1)
            cur["t"] += ch
    finish()
    return words

