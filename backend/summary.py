"""/summarize — MrSOLIS summarises a deck one slide at a time; code puts the summaries into a PDF.

The user (2026-11-14): "ADD A '/summarize' THEN THE BRAIN SUMMARIZES THE SLIDES ONE SLIDE AT A TIME AND THEN CODE
PULLS EVERYTHING INTO A FILE AND THE USER GETS IT IN THE CHAT" — it replaced the rule-built Exam Crib Sheet. The
file was a Word document for an hour; the user: "OK MAKE IT PDF".

- The brain writes each slide's summary: `classroom._system` (who MrSOLIS is, plain-text maths) + a word limit next
  to the slide — where small models obey it. Title / outline / closing slides are left out (`worth_summarising`).
- `clean` makes whatever the brain wrote fit a document: bullets as "- ", LaTeX as plain text (Gemma writes LaTeX
  even when asked not to), no "Here is a summary:" line, and never a real model's name (the user's rule).
- `build_pdf` lays the file out in code with PDFium (pypdfium2 — already shipped for MrSOLIS's PDF layer, so no new
  package): A4, title, one heading per slide, bullets, **bold**, page numbers. Text is real text (it can be searched
  and copied). The font is Windows' Verdana (embedding allowed, fsType 8): it has Ω, ², R₁, √, ≤ and keeps a summary
  near 0.3 MB (Segoe UI would be ~2 MB); a character the font lacks is written another way (`_fit`).
  The run itself (one slide at a time, cached, stoppable) is in main.py (/api/summary/...).
"""

import ctypes
import json
import os
import re
import struct
import unicodedata

from backend import brain, classroom

WORDS = 80                      # per slide; the limit sits next to the slide in the user turn
MAX_TOKENS = 320                # room for 80 words + bullets, with a margin for a brain that pads

_TASK = ("Summarise one slide for a student's revision notes: 3 to 6 short bullet points, each starting with "
         "\"- \". Keep every formula, definition, number and unit exactly as the slide gives it. Use only the "
         "slide's facts. No title, greeting, introduction or closing line.")


def worth_summarising(text: str, slide_no: int, picture: bool = False) -> bool:
    """False for a blank slide and for a title, outline or closing slide (they need no summary)."""
    words = (text or "").strip()
    if not words:
        return picture
    return classroom.is_lesson_slide(words, slide_no)


def slide_title(text: str) -> str:
    """The slide's own heading — its first short line — or "" when it has none."""
    for line in (text or "").splitlines():
        line = line.strip(" \t•-–*#")
        if line:
            return line if len(line) <= 80 and len(line.split()) <= 12 else ""
    return ""


def messages(text: str, slide_no: int, total: int, image=None) -> list:
    words = classroom._slide(text).strip() if text else ""
    ask = (f"Slide {slide_no} of {total}:\n\"\"\"\n{words}\n\"\"\"\n\nSummarise this slide in under {WORDS} words."
           if words else
           f"Slide {slide_no} of {total} has no text: it is the picture attached. Summarise this slide in under "
           f"{WORDS} words.")
    return [classroom._system(_TASK, classroom._SEE_SLIDE if image else ""),
            {"role": "user", "content": classroom._with_picture(ask, image)}]


async def summarise_slide(text: str, slide_no: int, total: int, image=None) -> str:
    """One slide's summary from the brain, cleaned for the document (raises local_llm.LocalLLMError)."""
    raw = await brain.chat(messages(text, slide_no, total, image), temperature=0.3, max_tokens=MAX_TOKENS)
    return clean(raw)


# ── LaTeX → plain text ───────────────────────────────────────────────────────────────────────────────────────────────
_SYMBOLS = {
    "times": "×", "cdot": "·", "div": "÷", "pm": "±", "mp": "∓", "approx": "≈", "neq": "≠", "ne": "≠",
    "leq": "≤", "le": "≤", "geq": "≥", "ge": "≥", "infty": "∞", "rightarrow": "→", "to": "→", "leftarrow": "←",
    "Rightarrow": "⇒", "propto": "∝", "degree": "°", "circ": "°", "partial": "∂", "nabla": "∇", "sum": "Σ",
    "int": "∫", "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "Delta": "Δ", "epsilon": "ε",
    "varepsilon": "ε", "theta": "θ", "lambda": "λ", "mu": "µ", "pi": "π", "rho": "ρ", "sigma": "σ", "Sigma": "Σ",
    "tau": "τ", "phi": "φ", "varphi": "φ", "Phi": "Φ", "omega": "ω", "Omega": "Ω", "eta": "η", "zeta": "ζ",
    "kappa": "κ", "chi": "χ", "psi": "ψ", "Psi": "Ψ", "Gamma": "Γ", "Lambda": "Λ", "Theta": "Θ",
    "ldots": "…", "dots": "…", "cdots": "…", "quad": " ", "qquad": " ", "%": "%",
}
_WRAP = re.compile(r"\\(?:text|mathrm|mathbf|mathit|textbf|textit|operatorname|vec|bar|hat|overline)\s*\{([^{}]*)\}")
_FRAC = re.compile(r"\\[dt]?frac\s*\{([^{}]*)\}\s*\{([^{}]*)\}")
_SQRT = re.compile(r"\\sqrt\s*\{([^{}]*)\}")
_POWER = re.compile(r"([\^_])\{([^{}]*)\}")
_SIMPLE = re.compile(r"^[\w.µ°Ω]+$")


def _unwrap(m) -> str:
    """$…$ around maths loses its dollars; a pair of prices ("$5 and $10") is left alone."""
    inner = m.group(1).strip()
    if re.search(r"[\\^_=]", inner) or re.fullmatch(r"[A-Za-z]{1,3}", inner):
        return inner
    return m.group(0)


def _group(s: str) -> str:
    """A fraction's part as plain text: "a" stays "a", "a + b" becomes "(a + b)"."""
    s = s.strip()
    return s if _SIMPLE.match(s) else f"({s})"


def plain_maths(text: str) -> str:
    """LaTeX the brain wrote ($\\frac{V}{R}$, \\times, R_{1}) as plain text the PDF shows as written (V/R, ×, R1)."""
    if "\\" not in text and "$" not in text:
        return text
    s = re.sub(r"\$\$(.+?)\$\$", r"\1", text, flags=re.S)
    s = re.sub(r"\$([^$\n]+?)\$", _unwrap, s)           # "$R_1$" -> "R_1", but "$5 and $10" stays money
    s = re.sub(r"\\\[|\\\]|\\\(|\\\)", "", s)
    s = re.sub(r"\\left|\\right", "", s)
    s = re.sub(r"\\[,;:! ]", " ", s)
    for _ in range(6):                                    # innermost first: \frac{\text{V}}{R_{1}} needs passes
        s2 = _WRAP.sub(r"\1", s)
        s2 = _FRAC.sub(lambda m: f"{_group(m.group(1))}/{_group(m.group(2))}", s2)
        s2 = _SQRT.sub(lambda m: f"√{_group(m.group(1))}", s2)
        s2 = _POWER.sub(lambda m: m.group(1) + (m.group(2) if _SIMPLE.match(m.group(2).strip()) else f"({m.group(2)})"), s2)
        if s2 == s:
            break
        s = s2
    s = re.sub(r"\^\\circ|\^\{\\circ\}", "°", s)
    s = re.sub(r"\\([A-Za-z]+|%)", lambda m: _SYMBOLS.get(m.group(1), m.group(1)), s)
    s = re.sub(r"_(\w)", r"\1", s)                       # R_1 -> R1 (the way slides write it)
    s = s.replace("{", "").replace("}", "")
    return re.sub(r"[ \t]{2,}", " ", s)


# ── the brain's text → document lines ────────────────────────────────────────────────────────────────────────────────
_PREAMBLE = re.compile(r"(?i)^\W*(here('s| is| are)\b|summary\b|slide \d+\b|this slide\b.*:\s*$|key points\b)[^\n]*:\s*$")
_BULLET = re.compile(r"^\s*(?:[-*•–·]|\d+[.)])\s+")


def clean(text: str) -> str:
    """Bullets as "- ", maths in plain text, no preamble line, no real model's name."""
    text = classroom._HIDE.sub("MrSOLIS", text or "")
    lines = [ln.rstrip() for ln in plain_maths(text).replace("\r", "").split("\n")]
    lines = [ln for ln in lines if ln.strip() and not re.fullmatch(r"\s*[-*_=]{3,}\s*", ln)]
    if lines and _PREAMBLE.match(lines[0]):
        lines = lines[1:]
    out = []
    for ln in lines:
        ln = re.sub(r"^\s*#+\s*", "", ln)                 # a heading the brain added: plain text
        out.append("- " + _BULLET.sub("", ln).strip() if _BULLET.match(ln) else ln.strip())
    return "\n".join(out).strip()


# ── the per-slide cache: a stopped run carries on, a second /summarize of a deck is instant ─────────────────────────
class Cache:
    def __init__(self, folder: str):
        self.path = os.path.join(folder, "slides.json")
        try:
            with open(self.path, encoding="utf-8") as f:
                self.data = json.load(f)
        except (OSError, ValueError):
            self.data = {}

    @staticmethod
    def key(idx: int, text: str, brain_id: str, picture: bool) -> str:
        import hashlib
        return f"{idx}:{brain_id}:{int(picture)}:" + hashlib.sha1((text or "").encode("utf-8")).hexdigest()[:16]

    def get(self, key: str):
        return self.data.get(key)

    def put(self, key: str, summary: str):
        self.data[key] = summary
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False)
        os.replace(tmp, self.path)


# ── the PDF ──────────────────────────────────────────────────────────────────────────────────────────────────────────
PAGE_W, PAGE_H = 595.28, 841.89                 # A4, in points
_LEFT, _RIGHT, _TOP, _BOTTOM = 56.0, 56.0, 62.0, 64.0
_INK, _DIM = (24, 24, 24), (112, 112, 112)
_FONTS = (("verdana.ttf", "verdanab.ttf"), ("segoeui.ttf", "segoeuib.ttf"), ("tahoma.ttf", "tahomabd.ttf"),
          ("arial.ttf", "arialbd.ttf"))
_STAND_IN = {"→": "->", "←": "<-", "↔": "<->", "⇒": "=>", "⇐": "<=", "⇔": "<=>", "∓": "-/+", "−": "-",
             "“": '"', "”": '"', "‘": "'", "’": "'", "—": "-", "–": "-", "…": "...", "•": "-", "·": "."}


def font_files():
    """(regular, bold) TrueType files from Windows' own fonts: Verdana first, then Segoe UI, Tahoma, Arial."""
    root = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
    for regular, bold in _FONTS:
        r, b = os.path.join(root, regular), os.path.join(root, bold)
        if os.path.isfile(r) and os.path.isfile(b):
            return r, b
    raise RuntimeError("No font to write the PDF with was found on this computer.")


def _cmap(data: bytes) -> set:
    """The characters a TrueType font can draw (its Windows Unicode cmap, format 4 or 12)."""
    n = struct.unpack(">H", data[4:6])[0]
    table = next((struct.unpack(">II", data[12 + 16 * i + 8:12 + 16 * i + 16])[0]
                  for i in range(n) if data[12 + 16 * i:16 + 16 * i] == b"cmap"), None)
    if table is None:
        return set()
    subs = {}
    for i in range(struct.unpack(">H", data[table + 2:table + 4])[0]):
        pid, eid, off = struct.unpack(">HHI", data[table + 4 + 8 * i:table + 12 + 8 * i])
        subs[(pid, eid)] = table + off
    have = set()
    if (3, 10) in subs and struct.unpack(">H", data[subs[(3, 10)]:subs[(3, 10)] + 2])[0] == 12:
        at = subs[(3, 10)]
        for g in range(struct.unpack(">I", data[at + 12:at + 16])[0]):
            start, end, _gid = struct.unpack(">III", data[at + 16 + 12 * g:at + 28 + 12 * g])
            have.update(range(start, min(end, 0x10FFFF) + 1))
        return have
    at = subs.get((3, 1))
    if at is None or struct.unpack(">H", data[at:at + 2])[0] != 4:
        return have
    segs = struct.unpack(">H", data[at + 6:at + 8])[0] // 2
    ends = struct.unpack(f">{segs}H", data[at + 14:at + 14 + 2 * segs])
    starts = struct.unpack(f">{segs}H", data[at + 16 + 2 * segs:at + 16 + 4 * segs])
    deltas = struct.unpack(f">{segs}h", data[at + 16 + 4 * segs:at + 16 + 6 * segs])
    ro_at = at + 16 + 6 * segs
    ranges = struct.unpack(f">{segs}H", data[ro_at:ro_at + 2 * segs])
    for k in range(segs):
        for c in range(starts[k], ends[k] + 1):
            if c == 0xFFFF:
                continue
            if ranges[k] == 0:
                gid = (c + deltas[k]) & 0xFFFF
            else:
                p = ro_at + 2 * k + ranges[k] + 2 * (c - starts[k])
                gid = struct.unpack(">H", data[p:p + 2])[0] if p + 2 <= len(data) else 0
                gid = (gid + deltas[k]) & 0xFFFF if gid else 0
            if gid:
                have.add(c)
    return have


def _fit(text: str, have: set) -> str:
    """Text the font can draw: a missing character is written another way (→ as ->, ₁ as 1), else dropped."""
    out = []
    for ch in text:
        if ord(ch) in have or ch in "\n":
            out.append(ch)
        elif ch in _STAND_IN:
            out.append(_STAND_IN[ch])
        else:
            alt = unicodedata.normalize("NFKD", ch)
            out.append(alt if alt != ch and all(ord(a) in have for a in alt) else "")
    return "".join(out)


def _runs(text: str) -> list:
    """[(piece, bold)] — **bold** marks the bold pieces."""
    return [(p.replace("**", ""), bool(i % 2)) for i, p in enumerate(re.split(r"\*\*(.+?)\*\*", text)) if p]


class _Pdf:
    """A small typesetter on PDFium: lines of text (regular / bold pieces) flowed down A4 pages."""

    def __init__(self):
        import pypdfium2 as pdfium
        import pypdfium2.raw as raw
        from PIL import ImageFont
        self.raw = raw
        self.doc = pdfium.PdfDocument.new()
        self.pages, self.y = [], 0.0
        self.fonts, self.keep = {}, []
        for bold, path in zip((False, True), font_files()):
            with open(path, "rb") as f:
                data = f.read()
            buf = (ctypes.c_uint8 * len(data)).from_buffer_copy(data)
            self.keep.append(buf)                         # PDFium reads it again when the file is saved
            handle = raw.FPDFText_LoadFont(self.doc.raw, buf, len(data), raw.FPDF_FONT_TRUETYPE, True)
            if not handle:
                raise RuntimeError(f"PDFium couldn't load the font {os.path.basename(path)}.")
            self.fonts[bold] = (handle, ImageFont.truetype(path, 1000), _cmap(data))
        self.have = self.fonts[False][2] & self.fonts[True][2]

    def width(self, text: str, bold: bool, size: float) -> float:
        return self.fonts[bold][1].getlength(text) * size / 1000.0

    def new_page(self):
        self.pages.append(self.doc.new_page(PAGE_W, PAGE_H))
        self.y = PAGE_H - _TOP

    def room(self, height: float):
        """Start a new page unless `height` more fits on this one."""
        if not self.pages or self.y - height < _BOTTOM:
            self.new_page()

    def put(self, page, text: str, bold: bool, size: float, x: float, y: float, rgb=_INK):
        raw = self.raw
        obj = raw.FPDFPageObj_CreateTextObj(self.doc.raw, self.fonts[bold][0], size)
        w = (text + "\0").encode("utf-16-le")
        raw.FPDFText_SetText(obj, (ctypes.c_ushort * (len(w) // 2)).from_buffer_copy(w))
        raw.FPDFPageObj_SetFillColor(obj, *rgb, 255)
        raw.FPDFPageObj_Transform(obj, 1, 0, 0, 1, x, y)
        raw.FPDFPage_InsertObject(page.raw, obj)

    def wrap(self, runs: list, width: float, size: float) -> list:
        """Lines of [(text, bold, x)] no wider than `width` (a word longer than a line gets its own line)."""
        lines, line, x = [], [], 0.0
        for text, bold in runs:
            for tok in re.findall(r"\s+|\S+\s*", text):
                word = tok.rstrip()
                if not word:                              # spaces between two pieces
                    if line:
                        x += self.width(" ", bold, size)
                    continue
                w = self.width(word, bold, size)
                if line and x + w > width:
                    lines.append(line)
                    line, x = [], 0.0
                line.append((word, bold, x))
                x += w + (self.width(" ", bold, size) if tok != word else 0.0)
        if line:
            lines.append(line)
        return lines

    def paragraph(self, text: str, size: float, *, bold=False, indent=0.0, bullet=False, rgb=_INK,
                  before=0.0, after=0.0, keep=0.0):
        """Flow one paragraph; `keep` asks for that much more room on its page (a heading with its first line)."""
        text = _fit(text, self.have)
        lead = size * 1.45
        x0 = _LEFT + indent + (16.0 if bullet else 0.0)
        lines = self.wrap(_runs(text) if not bold else [(text.replace("**", ""), True)],
                          PAGE_W - _RIGHT - x0, size) or [[("", False, 0.0)]]
        self.room(before + lead + keep)
        self.y -= before
        for i, line in enumerate(lines):
            self.room(lead)
            base = self.y - size
            page = self.pages[-1]
            if bullet and i == 0:
                self.put(page, "•" if ord("•") in self.have else "-", False, size, _LEFT + indent + 3.0, base, rgb)
            k = 0
            while k < len(line):                          # one text object per run of the same style
                j, words = k, []
                while j < len(line) and line[j][1] == line[k][1]:
                    words.append(line[j][0])
                    j += 1
                self.put(page, " ".join(words), line[k][1], size, x0 + line[k][2], base, rgb)
                k = j
            self.y -= lead
        self.y -= after

    def save(self, path: str, footer: str):
        for n, page in enumerate(self.pages, 1):
            note = _fit(f"{footer} · page {n} of {len(self.pages)}", self.have)
            self.put(page, note, False, 8.0, (PAGE_W - self.width(note, False, 8.0)) / 2, 34.0, _DIM)
            self.raw.FPDFPage_GenerateContent(page.raw)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        self.doc.save(tmp)
        self.doc.close()
        os.replace(tmp, path)


def build_pdf(path: str, deck_title: str, entries: list) -> str:
    """`entries`: [(slide_no, slide_title, summary_text)]. Writes the PDF and returns its path."""
    pdf = _Pdf()
    pdf.paragraph(f"{deck_title} — Summary", 19.0, bold=True, after=4.0)
    pdf.paragraph("Made by MrSOLIS from your slides, one slide at a time. Check anything important against the "
                  "slides.", 9.0, rgb=_DIM, after=10.0)
    for slide_no, title, text in entries:
        pdf.paragraph(f"Slide {slide_no}" + (f": {title}" if title else ""), 12.0, bold=True, before=10.0,
                      after=3.0, keep=10.5 * 1.45)
        for line in text.split("\n"):
            if line.startswith("- "):
                pdf.paragraph(line[2:], 10.5, bullet=True, after=2.0)
            elif line.strip():
                pdf.paragraph(line, 10.5, after=2.0)
    pdf.save(path, f"MrSOLIS · {deck_title}")
    return path


def file_name(deck_title: str) -> str:
    stem = re.sub(r"[^\w\- ]+", "", os.path.splitext(deck_title or "")[0]).strip() or "Slides"
    return f"{stem} - summary.pdf"
